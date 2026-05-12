# Phase 4: Pipeline Primitives — `shard_scratch` + `atomic_promote`

**Status**: Complete
**Started**: 2026-05-10
**Completed**: 2026-05-10
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-3.md](phase-3.md) (complete; Option-A bet validated)

---

## Objective

Extract the `tempfile.TemporaryDirectory(dir="/mnt/genomeclaw/scratch")` +
`shutil.copyfile(scratch_path, derived_path)` pattern that's currently
inlined in each orchestrator into two reusable primitives:

1. **`shard_scratch(step, run_id, shard=None)`** — context manager that
   yields a per-step (and optionally per-shard) scratch directory under
   `/mnt/genomeclaw/scratch`, auto-cleaned on exit including on
   exception. Same shape as `tempfile.TemporaryDirectory`, but with
   consistent naming the orchestrators can rely on (and that Phase-5+
   chromosome-shard scatter-gather will plug into via the `shard` arg).

2. **`atomic_promote(src, dst)`** — copy-then-rename pattern that
   guarantees `dst` is either fully written or absent. Replaces the
   bare `shutil.copyfile(scratch_path, run_dir/file)` calls that
   currently leave half-written outputs visible to readers if
   interrupted mid-copy.

These are small primitives but they tighten an `INV-R001` corner: a
crashed promote currently leaves a partially-written file in
`derived/`, which a re-run will then mistake for a complete artifact.
Atomic promotion makes the on-disk state always either "before" or
"after," never "during."

`shard_scratch`'s optional `shard` arg is forward-looking: Phase-5+
orchestrators (DeepVariant, GATK) iterate `chr1..chr22, X, Y, M` with
per-shard scratch — that 24-chromosome scatter-gather is the eventual
caller. The primitive lands now so the API doesn't have to be shaped
under deadline pressure later.

**`monitor_scratch`** (mid-run `df -h` polling, abort on projected
ENOSPC) is **deferred to Phase 5+** when actual scratch budgets exist
to assert against. No actual budgets means no useful tripwire today.

## Scope Boundaries

- **In scope**:
  - `prep/scratch.py` — `shard_scratch` + `atomic_promote` + their
    typed exceptions.
  - Migrate `prep/annotate.py` to use both primitives. Replace the
    `tempfile.TemporaryDirectory(...)` block with `shard_scratch(...)`.
    Replace the two `shutil.copyfile(work_annotated→annotated_vcf,
    work_annotated_tbi→annotated_tbi)` calls with `atomic_promote(...)`.
  - Migrate `prep/materialize.py` to use `shard_scratch` for its
    DuckDB CSV-staging dir. (Materialize writes the variants table in
    place — there's nothing to promote.)
  - Tests: ~10 unit tests on `shard_scratch` + `atomic_promote`;
    integration tests confirm orchestrators call them correctly.
  - **No real-data smoke gate.** Phase 3's smoke validated the new
    scratch tier; Phase 4 just extracts patterns. The full suite +
    a quick `annotate` smoke against the existing run dir confirms
    behaviour didn't regress.

- **Out of scope** (defer):
  - `monitor_scratch` (mid-run polling) — Phase 5+ when budgets exist.
  - Per-chromosome scatter-gather orchestration — Phase 5+.
  - `eject` / `doctor` subcommands — Phase 5.
  - Phase 5+ orchestrators (DeepVariant, GATK).

## Invariants Enforced in This Phase

- **INV-R001** Rebuildability — `atomic_promote` strengthens the
  "interrupted promote leaves derived clean" guarantee. Tested via
  simulated crash mid-copy: partial state must not become visible at
  the destination path.
- **INV-D001** Source-of-Truth — `shard_scratch` doesn't change the RO
  enforcement (raw + reference still virtiofs RO via the shim), but
  the explicit `cleanup-on-exit` semantics close a corner where a
  crashed orchestrator could leave per-run scratch behind to
  accumulate over time.

## Open Questions

- **`atomic_promote` parent-directory fsync?** The rename-within-FS is
  atomic on POSIX, but the rename's *durability* (surviving a power
  loss) requires fsync of the parent directory after the rename. Our
  workload doesn't strictly need that — INV-R001 means a lost run
  rebuilds from raw — so this is a "nice to have" not a "must
  have." Default: include the parent fsync for correctness; cheap,
  bounded cost. Document the rationale.
- **What about `shard_scratch` collisions across concurrent runs?**
  Currently the orchestrator is serial (one run at a time per run-id).
  The `step-runid-shard` naming is unique enough. If a future plan
  introduces concurrent runs of the same orchestrator on the same
  run-id, we'd need to add a process-pid suffix or move to UUIDs. Out
  of scope for now.
- **`shard_scratch` cleanup on SIGKILL?** Signal-induced exit doesn't
  run the context manager's `__exit__`. The leftover dir would
  accumulate. Phase-5+ has `monitor_scratch` to enforce budget; for
  now, document that crashed orchestrators may leave scratch dirs
  that the user can purge with `rm -rf
  /mnt/genomeclaw/scratch/{step}-*/`.

## TDD Steps

### Step 4.1 — RED

Tests live under `tests/unit/test_scratch.py` (primitives in isolation)
and `tests/integration/test_orchestrators_use_scratch_primitives.py`
(annotate / materialize call the primitives correctly).

**Test cases (sketch)**:

1. `test_shard_scratch_yields_dir_under_canonical_path` — by default,
   the dir lives under `/mnt/genomeclaw/scratch/<step>-<run_id>/`.
   With `shard="chr1"` argument, dir is
   `<step>-<run_id>-chr1/`. Tests pass `base=tmp_path` to override.
2. `test_shard_scratch_cleans_up_on_normal_exit` — after the `with`
   block, the dir is gone.
3. `test_shard_scratch_cleans_up_on_exception` — same, but the `with`
   block raises.
4. `test_shard_scratch_does_not_collide_across_steps` — two
   simultaneous `shard_scratch("a", run_id)` and `shard_scratch("b",
   run_id)` get different dirs.
5. `test_atomic_promote_writes_dst_atomically` — mid-copy `dst`
   doesn't exist (only `<dst>.tmp` does); after `atomic_promote`
   returns, `dst` exists with full content and the `.tmp` is gone.
6. `test_atomic_promote_cleans_up_tmp_on_failure` — inject a copy
   failure (e.g., source disappears mid-copy via monkey-patch); after
   the exception propagates, no `<dst>.tmp` is left behind.
7. `test_atomic_promote_creates_parent_dir` — `dst.parent` may not
   exist; `atomic_promote` mkdirs it (consistent with the existing
   `shutil.copyfile` behavior in annotate.py).
8. `test_atomic_promote_raises_FileNotFoundError_when_src_missing` —
   typed error, not a generic OSError.
9. `test_atomic_promote_overwrites_existing_dst` — explicit semantics:
   if `dst` already exists, the rename overwrites it. Re-running an
   orchestrator should always produce the latest file.
10. `test_invR001_atomic_promote_no_partial_state_visible` — the
    invariant test. Use `multiprocessing` to start a copier and a
    reader; the reader observes the destination path either as
    nonexistent or as the full file, never as a partial.

For the orchestrator-level tests:

11. `test_annotate_uses_atomic_promote_for_outputs` — observe via
    monkey-patch that annotate calls `atomic_promote(work_annotated,
    annotated_vcf)` and `atomic_promote(work_annotated_tbi,
    annotated_tbi)` (rather than `shutil.copyfile`).
12. `test_annotate_uses_shard_scratch` — same shape, observe that
    annotate uses the `shard_scratch` context manager.
13. `test_materialize_uses_shard_scratch` — same.

### Step 4.2 — GREEN

1. Create `prep/scratch.py`:

   ```python
   class ScratchError(Exception): ...
   class AtomicPromoteError(ScratchError): ...

   @contextmanager
   def shard_scratch(
       step: str,
       run_id: str,
       *,
       shard: str | None = None,
       base: Path = Path("/mnt/genomeclaw/scratch"),
   ) -> Iterator[Path]: ...

   def atomic_promote(src: Path, dst: Path) -> None: ...
   ```

2. Migrate `prep/annotate.py`:

   - Replace `tempfile.TemporaryDirectory(dir="/mnt/genomeclaw/scratch", prefix=...)`
     with `shard_scratch(step="annotate", run_id=run_dir.name)`.
   - Replace the two `shutil.copyfile(work_annotated, annotated_vcf)`
     and `shutil.copyfile(work_annotated_tbi, annotated_tbi)` calls
     with `atomic_promote(...)`.
   - The four input-staging `shutil.copyfile` calls (norm,
     norm.tbi, clinvar, clinvar.tbi) stay as-is — they're staging
     into the scratch dir, not promoting outputs.

3. Migrate `prep/materialize.py`:

   - Replace the `tempfile.TemporaryDirectory(...)` block with
     `shard_scratch(step="materialize", run_id=run_dir.name)`.
   - Materialize writes the variants table in place via DuckDB; no
     `atomic_promote` calls. (Materialize's atomicity is DuckDB's
     job — it commits the SQL transaction or rolls back.)

4. Run the full suite + a quick annotate smoke against the existing
   MPNRGLQ2K run dir. Confirm row counts unchanged.

### Step 4.3 — REFACTOR

- If `annotate.py`'s `shard_scratch` block becomes the only place that
  knows the canonical path layout, drop the `tempfile.Path` import.
- Drop the now-unused `import tempfile` in `annotate.py` and
  `materialize.py` if the migration leaves no other temp-file uses.
- Ensure `prep/scratch.py` uses only stdlib + the existing toolkit
  imports — no new dependencies.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py` | CREATE | `shard_scratch` + `atomic_promote` + 2 typed exceptions. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` | MODIFY | Migrate to primitives. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` | MODIFY | Same. |
| `packages/toolkit/tests/unit/test_scratch.py` | CREATE | Primitives in isolation. |
| `packages/toolkit/tests/integration/test_orchestrators_use_scratch_primitives.py` | CREATE | Verifies annotate / materialize call the primitives. |
| `packages/toolkit/tests/integration/test_annotate.py` | MODIFY (maybe) | Update if existing tests assumed `shutil.copyfile` calls. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/unit/test_scratch.py \
              tests/integration/test_orchestrators_use_scratch_primitives.py -v
uv run pytest -q  # full suite still green
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

**Quick smoke** (no fresh ingest needed; reuse the existing MPNRGLQ2K run dir):

```bash
RUN_ID=$(readlink /Volumes/Genome_Work/genomeclaw/derived/CURRENT)
bin/genomeclaw-prep annotate \
    --run-dir "/mnt/genomeclaw/derived/$RUN_ID" \
    --reference-dir /mnt/genomeclaw/reference
bin/genomeclaw-prep materialize --run-dir "/mnt/genomeclaw/derived/$RUN_ID"

# Assert row counts unchanged: 4,870,517 / 42,885 (Phase-3 close baseline).
```

---

## Completion Criteria

- [ ] All listed unit / integration tests pass (RED → GREEN → REFACTOR cycle visible in commits)
- [ ] Static checks pass (`ruff` check + format)
- [ ] `INV-R001` test (`test_invR001_atomic_promote_no_partial_state_visible`) passes
- [ ] No bare `shutil.copyfile(<scratch>, <run_dir>/...)` calls remain in `prep/annotate.py` or `prep/materialize.py` for output promotion (input staging stays as `shutil.copyfile` since it's into scratch, not into derived)
- [ ] `tempfile.TemporaryDirectory(dir="/mnt/genomeclaw/scratch", ...)` calls all replaced by `shard_scratch(...)`
- [ ] Quick smoke against existing run dir produces unchanged row counts (4,870,517 / 42,885)
- [ ] `work-notes.md` updated with RED state, decisions, smoke result
- [ ] Phase status updated in `development-plan.md`

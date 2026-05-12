# Phase 3: Pre-Flight Assertions + Migrate annotate/materialize off `/tmp`

**Status**: Complete (Option A bet validated at MVP scale)
**Started**: 2026-05-10
**Completed**: 2026-05-10
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-2.md](phase-2.md) (complete with Option-A pivot)

> **Re-scope note (2026-05-10)**: Original Phase 3 was the in-VM ext4
> lifecycle. Block-attached scratch was dropped in Phase 2's Option-A
> pivot, so the original phase is obsolete. Phase 3 is now: ship the
> pre-flight assertion library, migrate `annotate` and `materialize`
> off the Phase-4A `/tmp` workaround onto `/mnt/genomeclaw/scratch`,
> rename the env var to match, and validate that the full Phase-4A
> pipeline survives at row-equivalence (4,870,517 variants / 42,885
> ClinVar matches) on the new scratch tier. **No backwards compat**:
> `/tmp` paths in orchestrators are removed, the env var is renamed
> outright, and the shim defaults to the new layout.
>
> Cram-scratch-strategy report § Post-implementation discovery
> documents the Option-A pivot and the tripwires that escalate to
> Option B if Phase 5+ workloads can't survive virtiofs+APFS scratch.

---

## Objective

Three coupled changes, all required for an internally-consistent post-pivot
toolkit:

1. **Pre-flight assertion library** — orchestrators fail fast and loud on
   misconfigured environments instead of discovering the problem mid-pipeline.
2. **Migrate `annotate` and `materialize` off `/tmp`** — the
   `tempfile.TemporaryDirectory(dir="/tmp")` workaround was an apology for
   the broken-on-macOS-Sequoia work mount. The mount is fixed. The apology
   goes with the fix.
3. **Rename `GENOMECLAW_WORK_DIR` → `GENOMECLAW_SCRATCH_DIR`** (and
   `/mnt/genomeclaw/work` → `/mnt/genomeclaw/scratch` inside the container).
   The "work" name was confusing in the cram-scratch-strategy report; the
   semantic correction has been overdue.

The real-data smoke at the end is the test of the Option-A bet at MVP scale
— if the full pipeline produces row-equivalent results to the baseline run
when scratch lives on virtiofs+APFS, we have evidence that the pivot
generalizes beyond the trivial case. Failure modes (deadlock, slow,
EIO) are the tripwires that escalate to Option B.

## Scope Boundaries

- **In scope**:
  - `prep/preflight.py` — 4 assertions, 4 typed exceptions.
  - `prep/annotate.py`, `prep/materialize.py` — migrate scratch from `/tmp` to `/mnt/genomeclaw/scratch`; add pre-flight calls at the top of each orchestrator.
  - `prep/ingest.py`, `prep/normalize.py`, `prep/fetch.py` — add pre-flight calls (no scratch migration; these don't currently use `/tmp`).
  - `bin/genomeclaw-prep` — rename `GENOMECLAW_WORK_DIR` → `GENOMECLAW_SCRATCH_DIR`; update bind-mount target to `/mnt/genomeclaw/scratch`; auto-detect `/Volumes/Genome_Work/genomeclaw/{raw,reference,derived,_scratch}/` and use them as defaults; refuse to start if the canonical layout isn't present.
  - All tests + docs touched by the rename.
  - **Real-data smoke**: full Phase-4A pipeline against MPNRGLQ2K with a fresh `run_id`, asserting row-equivalence with the Phase-2-close baseline (4,870,517 variants / 42,885 ClinVar matches / schema v0.2).

- **Out of scope** (defer):
  - `shard_scratch` / `atomic_promote` pipeline primitives → Phase 4.
  - `eject` / `doctor` subcommands → Phase 5.
  - Linux host support.
  - Phase 5+ pipeline orchestrators (DeepVariant, GATK).
  - `assert_scratch_budget_gb()` — added in Phase 5+ when actual budgets exist to assert against.

## Invariants Enforced in This Phase

- **INV-D001** Source-of-Truth — pre-flight assertions verify `raw/` and `reference/` mounts refuse writes before any pipeline step runs.
- **INV-R001** Rebuildability — row-equivalence smoke vs. Phase-2-close baseline. If the migration off `/tmp` produces *different* variants-table contents from the same inputs and tools, that's an INV-R001 violation.
- **NEW INV-D003** (still proposed; promoted in Phase 5) — heavy scratch writes target `/mnt/genomeclaw/scratch`, not `/mnt/genomeclaw/derived`. The `/tmp`-removal in this phase is the first place the rule is structurally enforced.

## Open Questions Resolved

All open items from the original phase-3.md draft are decided:

| Q | Resolution |
|---|---|
| Migrate annotate/materialize now or defer? | **Now.** `/tmp` was technical debt from a broken mount that's now fixed. |
| Env var rename? | **Yes**, no alias. `GENOMECLAW_WORK_DIR` → `GENOMECLAW_SCRATCH_DIR`. |
| Backwards-compat for old layout? | **None.** Pre-flight is strict; user re-runs `setup` if needed. |
| `assert_genome_work_apfs()` inside container? | **Drop.** Setup's job, not per-invocation. |
| Smoke against existing run dir? | **No** — fresh `run_id`. |
| Pre-flight call site? | **Explicit** at the top of each orchestrator. |
| Mount target rename? | **Yes** — `/mnt/genomeclaw/work` → `/mnt/genomeclaw/scratch`. |
| Shim default behaviour? | **Auto-detect** `/Volumes/Genome_Work/genomeclaw/...`; refuse to start if absent. |

---

## TDD Steps

### Step 3.1 — RED

Tests live under `tests/integration/test_preflight.py`, `tests/integration/test_orchestrators_call_preflight.py`, `tests/determinism/test_invR001_full_pipeline_on_new_scratch.py`, plus updates to existing `test_annotate.py` and `test_materialize.py` to reflect the new scratch path.

**Test cases (sketch)**:

1. `test_assert_raw_readonly_passes_when_ro` — fake `/mnt/genomeclaw/raw` mounted RO; assertion returns silently.
2. `test_assert_raw_readonly_rejects_when_writable` — fake mount writable → `RawNotReadOnlyError("INV-D001 violation: /mnt/genomeclaw/raw is writable; re-run `genomeclaw-prep setup` to restore the read-only bind-mount discipline")`.
3. `test_assert_reference_readonly_passes_when_ro` / `test_assert_reference_readonly_rejects_when_writable` — same shape for reference.
4. `test_assert_derived_writable_passes_when_rw` / `test_assert_derived_writable_rejects_when_ro` — same shape, opposite polarity.
5. `test_assert_scratch_writable_passes_when_rw` / `test_assert_scratch_writable_rejects_when_ro` — same.
6. `test_assert_scratch_writable_rejects_when_missing` — `/mnt/genomeclaw/scratch` doesn't exist (user hasn't run setup) → `ScratchNotMountedError` with a fixable message ("run `genomeclaw-prep setup` to create the canonical layout").
7. `test_invD001_orchestrators_call_assert_raw_readonly_before_work` — monkey-patch the assertions to count calls; run each of `ingest/normalize/annotate/materialize`; assert the call happened before any I/O on `raw/`.
8. `test_annotate_writes_scratch_to_mnt_scratch_not_tmp` — observe write targets during annotate; assert all > 1 GB writes go to `/mnt/genomeclaw/scratch/`, none to `/tmp`.
9. `test_materialize_writes_csv_staging_to_mnt_scratch_not_tmp` — same shape for materialize's DuckDB CSV staging.
10. `test_invR001_full_pipeline_on_new_scratch_row_equivalent` — **the smoke** (`@needs_bio @real_data`): fresh `run_id`, full pipeline against MPNRGLQ2K. Assert variants count == 4,870,517 and `clinvar_classification IS NOT NULL` count == 42,885.
11. `test_shim_uses_genomeclaw_scratch_dir_env_var` — invoke shim with `GENOMECLAW_SCRATCH_DIR=...`; observe via `GENOMECLAW_DEBUG=1` that the docker bind-mount target is `/mnt/genomeclaw/scratch`.
12. `test_shim_refuses_to_start_when_canonical_layout_absent` — neither `GENOMECLAW_*_DIR` env vars set nor `/Volumes/Genome_Work/genomeclaw/` exists; shim exits non-zero with a "run setup first" message.

### Step 3.2 — GREEN

1. Create `prep/preflight.py`:
   ```python
   class PreflightError(Exception): ...
   class RawNotReadOnlyError(PreflightError): ...
   class ReferenceNotReadOnlyError(PreflightError): ...
   class DerivedNotWritableError(PreflightError): ...
   class ScratchNotMountedError(PreflightError): ...
   class ScratchNotWritableError(PreflightError): ...

   def assert_raw_readonly() -> None: ...
   def assert_reference_readonly() -> None: ...
   def assert_derived_writable() -> None: ...
   def assert_scratch_writable() -> None: ...
   ```
   Each writes a probe file to test the property; raises typed exception with a message that names the canonical fix ("re-run `genomeclaw-prep setup`").

2. Modify `prep/annotate.py`:
   - At the top of `annotate()`: `preflight.assert_raw_readonly(); preflight.assert_reference_readonly(); preflight.assert_derived_writable(); preflight.assert_scratch_writable()`.
   - Replace `tempfile.TemporaryDirectory(prefix="genomeclaw-annotate-", dir="/tmp")` with `tempfile.TemporaryDirectory(prefix=f"annotate-{run_dir.name}-", dir="/mnt/genomeclaw/scratch")`.

3. Modify `prep/materialize.py` similarly (annotate's twin).

4. Add pre-flight calls (only) to `prep/ingest.py`, `prep/normalize.py`, `prep/fetch.py`. `fetch` only asserts `/mnt/genomeclaw/reference` is *writable* (it's writing to it); it explicitly skips `assert_reference_readonly`.

5. Modify `bin/genomeclaw-prep`:
   - Rename `${GENOMECLAW_WORK_DIR:-…}` to `${GENOMECLAW_SCRATCH_DIR:-…}` everywhere.
   - Auto-detect canonical layout: if `/Volumes/Genome_Work/genomeclaw/{raw,reference,derived,_scratch}/` all exist, use them as defaults for the four `*_DIR` env vars when the user hasn't set them. Otherwise refuse to start with a `setup`-pointing message.
   - Bind-mount target rename: `/mnt/genomeclaw/work` → `/mnt/genomeclaw/scratch`.

6. Sweep tests + docstrings + README + plan/report docs for `WORK_DIR` / `work_dir` / `/mnt/genomeclaw/work` and rename.

7. Run the real-data smoke against MPNRGLQ2K. Assert row counts.

### Step 3.3 — REFACTOR

- Extract `preflight.run_orchestrator_checks()` if 3+ orchestrators repeat the same `assert_raw_readonly() + assert_reference_readonly() + assert_derived_writable() + assert_scratch_writable()` block (rule of three).
- Drop the Phase-4A `bin/genomeclaw-prep`'s `mkdir -p "$work_dir/tmp"` and the in-image `ENV TMPDIR=/mnt/genomeclaw/work/tmp` directive — Phase-3-and-after, scratch is the canonical location, no special TMPDIR magic.
- Re-run the full suite + lint + format after each refactor.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/preflight.py` | CREATE | Assertion library + 5 typed exceptions. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` | MODIFY | Pre-flight calls; scratch dir from `/tmp` → `/mnt/genomeclaw/scratch`. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` | MODIFY | Same as annotate. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` | MODIFY | Pre-flight calls only. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/normalize.py` | MODIFY | Pre-flight calls only. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | Pre-flight calls (writable-reference only). |
| `bin/genomeclaw-prep` | MODIFY | Env var rename; auto-detect defaults; bind-mount target rename; refuse-to-start when layout absent. |
| `packages/toolkit/Dockerfile` | MODIFY | `mkdir -p /mnt/genomeclaw/scratch` (replaces `/work`); remove `ENV TMPDIR=/mnt/genomeclaw/work/tmp`. |
| `packages/toolkit/tests/integration/test_preflight.py` | CREATE | 12 unit tests for the assertion library + shim env var coverage. |
| `packages/toolkit/tests/integration/test_orchestrators_call_preflight.py` | CREATE | Each orchestrator invokes the right assertions. |
| `packages/toolkit/tests/determinism/test_invR001_full_pipeline_on_new_scratch.py` | CREATE | Real-data row-equivalence smoke (`@needs_bio @real_data`). |
| `packages/toolkit/tests/integration/test_annotate.py` | MODIFY | Update for new scratch path; existing assertions stay. |
| `packages/toolkit/tests/integration/test_materialize.py` | MODIFY | Same. |
| All tests touching `WORK_DIR` / `/mnt/genomeclaw/work` | MODIFY | Rename. |
| `docs/reference/user-stories.md` | MODIFY | `WORK_DIR` → `SCRATCH_DIR`; `/mnt/genomeclaw/work` → `/mnt/genomeclaw/scratch`. |
| `docs/reference/architecture.md` | MODIFY | Same sweep. |
| `docs/plans/active/cram-scratch-strategy/development-plan.md` | MODIFY | Progress Tracking row update at phase close. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_preflight.py \
              tests/integration/test_orchestrators_call_preflight.py -v
uv run pytest -q  # full suite still green
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

**Real-data smoke gate** — runs against actual Nebula deliverable, fresh
`run_id`, full pipeline:

```bash
RUN_ROOT=/Volumes/Genome_Work/genomeclaw/derived
NEW_RUN=$(bin/genomeclaw-prep ingest \
    --sample-id MPNRGLQ2K \
    --reference /mnt/genomeclaw/reference/grch38 \
    --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
    | grep -oE '[0-9TZ-]+-[a-f0-9]+')

bin/genomeclaw-prep normalize    --run-dir "/mnt/genomeclaw/derived/$NEW_RUN"
bin/genomeclaw-prep annotate     --run-dir "/mnt/genomeclaw/derived/$NEW_RUN" \
                                 --reference-dir /mnt/genomeclaw/reference
bin/genomeclaw-prep materialize  --run-dir "/mnt/genomeclaw/derived/$NEW_RUN"

# Assert: 4,870,517 variants / 42,885 ClinVar matches (Phase-2-close baseline).
docker run --rm --user "$(id -u):$(id -g)" \
    --mount type=bind,source=$RUN_ROOT/$NEW_RUN,target=/run \
    --entrypoint python3 genomeclaw/toolkit:dev -c "
import duckdb
c = duckdb.connect('/run/variants.duckdb', read_only=True)
total = c.execute('SELECT COUNT(*) FROM variants').fetchone()[0]
ann = c.execute('SELECT COUNT(*) FROM variants WHERE clinvar_classification IS NOT NULL').fetchone()[0]
assert total == 4870517 and ann == 42885, f'baseline drift: {total}/{ann}'
print(f'OK: {total:,} variants / {ann:,} ClinVar matches')
"
```

---

## Completion Criteria

- [ ] All listed unit / integration tests pass (RED → GREEN → REFACTOR cycle visible in commits)
- [ ] Static checks pass (`mypy`, `ruff`)
- [ ] `INV-D001` test (`test_invD001_orchestrators_call_assert_raw_readonly_before_work`) passes
- [ ] `INV-R001` real-data smoke (`test_invR001_full_pipeline_on_new_scratch_row_equivalent`) passes — variants count + ClinVar match count match the baseline exactly (4,870,517 / 42,885)
- [ ] No `tempfile.TemporaryDirectory(dir="/tmp")` calls remain in `prep/` source
- [ ] No `/mnt/genomeclaw/work` references in code, tests, or docs (post-sweep grep returns zero)
- [ ] No `GENOMECLAW_WORK_DIR` references in code, tests, or docs (same grep)
- [ ] Shim refuses to start cleanly when the canonical layout is absent — verified by a unit test
- [ ] `work-notes.md` updated with RED state, decisions, smoke result (any new perf numbers vs. the `/tmp` baseline are noteworthy)
- [ ] Phase status updated in `development-plan.md`
- [ ] **If the smoke gate fails** (row counts diverge OR pipeline hangs/deadlocks): STOP. Document the failure mode in `work-notes.md`. The Option-A bet is wrong; Phase 3 escalates to Option B (switch from colima to direct lima); update the cram-scratch-strategy report's § Post-implementation discovery to record which tripwire fired.

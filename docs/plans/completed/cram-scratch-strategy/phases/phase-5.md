# Phase 5: `eject` + `doctor` + Docs + INV-D003 Promotion

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD or blank>
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-4.md](phase-4.md) (complete; primitives shipped)

---

## Objective

Close out the cram-scratch-strategy plan. Ship the two remaining
user-facing subcommands (`eject`, `doctor`), promote `INV-D003`
into `INVARIANTS.md`, finalise the user-stories + README sections that
went through earlier drafts during Phase 2's pivot, and migrate this
plan + its predecessor (`storage-scratch-layout/`) to `completed/`.

Phase 5 is **paperwork-heavy + small surfaces**. The two subcommands
are mostly host-side wrappers around `diskutil` and the existing
pre-flight library; no new architectural decisions.

## Scope Boundaries

- **In scope**:
  - `prep/eject.py` + `genomeclaw-prep eject` subcommand. Refuses if
    a pipeline is running; otherwise stops colima → `diskutil eject`.
  - `prep/doctor.py` + `genomeclaw-prep doctor` subcommand. Read-only
    diagnostic. Runs every pre-flight assertion (capturing results
    rather than raising), reads `_scratch/setup.log`, surfaces the
    drive identity + colima/lima version, prints a structured report.
  - `INV-D003` (Heavy Scratch Is Separated From Authoritative Outputs)
    promoted into `docs/reference/INVARIANTS.md`. Version bump v1.5 → v1.6.
  - `user-stories.md` Story 1 Step 0 — final pass; mention `eject` and
    `doctor` as available; reflect Phase-4 atomic-promote semantics
    where relevant.
  - `README.md` Storage planning section — final pass to match
    post-pivot reality.
  - `docs/reference/architecture.md` — update mount table; add
    `INV-D003` reference.
  - `docs/plans/active/storage-scratch-layout/` → `docs/plans/completed/`
    with a closing note pointing at `cram-scratch-strategy/`.
  - This plan (`docs/plans/active/cram-scratch-strategy/`) →
    `docs/plans/completed/` after all phase-5 work lands.

- **Out of scope** (defer to a future plan):
  - Linux host support — separate plan.
  - `monitor_scratch` mid-run polling — Phase-5+ orchestrators
    introduce real budgets.
  - DeepVariant / GATK / variant-calling integrations.
  - PRS computation (`pgsc_calc`) Nextflow `work/` sizing.

## Invariants Enforced in This Phase

- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs
  — promoted from "proposed" to "promoted." Verification: existing
  preflight assertions + scratch-primitive tests already cover the
  rule mechanically; the docs entry codifies the intent.
- **INV-D001** — `eject` doesn't change source-of-truth handling, but
  it does prevent the "yanked drive mid-run corrupts derived/" failure
  mode that's been a documented risk since Phase 2.

## Open Questions Resolved

| Q | Resolution |
|---|---|
| `INV-D003` exact wording? | "Heavy Scratch Is Separated From Authoritative Outputs." Original "block-attached, not virtiofs" framing is a Phase-2 implementation detail that turned out to be unimplementable on colima 0.9.1; the underlying principle (scratch ≠ derived) survives the pivot. |
| Lint guard for INV-D003 enforcement? | **Drop the static lint approach.** A correct lint rule can't easily tell "final artifact" from "heavy scratch" — both write to disk, both are large. Replace with the existing test pattern: integration tests observe write targets during a real run, asserting `> 1 GB writes go to /mnt/genomeclaw/scratch, not /mnt/genomeclaw/derived`. Phase 3's preflight + Phase 4's `shard_scratch` already constrain the behaviour at the API level; the test pattern catches regressions. |
| `doctor` — text or JSON output? | **Both.** Default is human-readable text; `--json` flag produces a structured object for `genomeclaw-prep doctor --json | jq` or shell scripting. Exit 0 if all checks pass; exit 1 if any pre-flight fails (machine-readable). |
| `eject` — what if a pipeline is running? | Refuse outright. Detect via `docker ps --filter ancestor=genomeclaw/toolkit:dev`. Print: "pipeline still running in container <id>; wait for it to finish or `docker kill <id>` deliberately, then retry." |
| Move both plans to `completed/` at end of Phase 5? | Yes for `cram-scratch-strategy/`. Yes for `storage-scratch-layout/`, with a one-paragraph closing note pointing at `cram-scratch-strategy/` as its successor. |

## TDD Steps

### Step 5.1 — RED

**Test cases**:

1. `test_eject_refuses_when_pipeline_running` — mock `docker ps`
   returning a running toolkit container; `eject()` raises
   `PipelineRunningError`; no `colima stop` or `diskutil eject` call
   happened.
2. `test_eject_stops_colima_then_ejects_drive` — mock all subprocesses;
   verify call order `[colima_stop, diskutil_eject]`; no extras.
3. `test_eject_handles_drive_not_mounted` — `diskutil eject` returns
   non-zero "drive not mounted" → `eject` raises a clear typed error
   pointing the user at the next manual step. (Or treat as success;
   pick one — leaning toward "raise with a fixable message.")
4. `test_doctor_reports_all_checks_when_layout_healthy` — fake
   platform with all 4 mounts correct; `doctor()` reports OK for each
   of the 4 pre-flight assertions; exit 0.
5. `test_doctor_reports_failures_clearly_when_layout_broken` — fake
   platform with `derived/` read-only; `doctor()` flags
   `assert_derived_writable` as FAIL; exit 1; output includes the
   actual error message.
6. `test_doctor_reads_setup_log` — fake `_scratch/setup.log` with one
   `setup_completed` event; `doctor()` reports "last setup: <ts>,
   toolkit_version=<v>".
7. `test_doctor_handles_missing_setup_log` — no `_scratch/setup.log`;
   `doctor()` reports "no setup audit log found — run
   `genomeclaw-prep setup` first" (degrades gracefully).
8. `test_doctor_json_output_is_machine_readable` — `doctor(json=True)`
   returns a dict with `checks: [...]`, `setup_log: {...}`,
   `colima: {...}`. JSON-serialisable round-trip.
9. `test_doctor_exits_0_on_healthy_environment` — integration:
   `cli.main(["doctor"])` exits 0 when all 4 mounts are correct and
   colima is up.
10. `test_doctor_exits_1_on_any_check_failure` — integration: one
    mount RO when it should be RW → cli exits 1.
11. `test_invD003_orchestrators_write_heavy_scratch_to_scratch_mount` —
    integration: monkey-patch `Path.write_bytes` to log every >1 GB
    write target during an annotate run; assert all such targets are
    under `/mnt/genomeclaw/scratch`, none under `/mnt/genomeclaw/derived`.
    (This is the "lint guard equivalent.")

### Step 5.2 — GREEN

1. Create `prep/eject.py`:
   - `eject(*, force: bool = False) -> int` — returns CLI exit code.
   - Detects running toolkit containers via `docker ps`. Raises
     `PipelineRunningError` unless `force=True`.
   - Calls `colima stop` (best-effort; succeed if already stopped).
   - Calls `diskutil eject /Volumes/Genome_Work`.
   - Prints "safe to disconnect <drive_name>" on success.

2. Create `prep/doctor.py`:
   - `doctor(*, json_output: bool = False) -> int` — returns CLI exit code.
   - Iterates each pre-flight assertion, captures
     `(name, status, message)` tuples. status ∈ `{"OK", "FAIL", "SKIP"}`.
   - Reads `_scratch/setup.log` if present; surfaces last
     `setup_completed` event (or last `setup_started` if no completion).
   - Reads drive identity from `diskutil info` for `/Volumes/Genome_Work`.
   - Reads `colima version` + `colima status`.
   - Renders text (default) or JSON (`--json` flag).
   - Exits 0 iff every check is OK or SKIP; 1 if any FAIL.

3. Wire `eject` and `doctor` subcommands in `cli.py` (alongside the
   existing `setup` route — same host-native dispatch from the shim).

4. Test the live `doctor` against the real Kingston layout. Verify
   green output. Test `eject` against the live Kingston (after
   confirming with the user — destructive in the sense of stopping
   colima and unmounting the drive).

5. Promote `INV-D003` in `docs/reference/INVARIANTS.md`:
   - Add the full entry (Rule / Requirements / Where it applies / How
     to verify).
   - Bump version v1.5 → v1.6, update Last Updated.
   - Add to the Invariant Index table.

6. Finalise `user-stories.md` Story 1 Step 0 (mention `eject` /
   `doctor` available; remove "Phase 5 of the plan" parenthetical).

7. Finalise `README.md` Storage planning section.

8. Update `docs/reference/architecture.md` with the post-pivot mount
   table and `INV-D003` reference.

9. Move `docs/plans/active/storage-scratch-layout/` →
   `docs/plans/completed/storage-scratch-layout/` with a
   `_SUPERSEDED.md` note pointing at `cram-scratch-strategy/`.

10. Move `docs/plans/active/cram-scratch-strategy/` →
    `docs/plans/completed/cram-scratch-strategy/` after all the above
    lands.

### Step 5.3 — REFACTOR

- If `prep/eject.py` and `prep/doctor.py` both call into the same
  "subprocess + interpret" patterns, extract a shared helper.
- Drop unused imports.
- Re-run full suite + lint + format.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/eject.py` | CREATE | Eject subcommand impl. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | CREATE | Doctor subcommand impl. |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | MODIFY | Add `eject` + `doctor` subparsers. |
| `packages/toolkit/tests/integration/test_eject.py` | CREATE | Unit + integration coverage. |
| `packages/toolkit/tests/integration/test_doctor.py` | CREATE | Same. |
| `packages/toolkit/tests/integration/test_invD003_scratch_discipline.py` | CREATE | The "lint guard equivalent" — observed write targets during a real annotate run. |
| `docs/reference/INVARIANTS.md` | MODIFY | Promote `INV-D003`; v1.5 → v1.6. |
| `docs/reference/user-stories.md` | MODIFY | Story 1 Step 0 final pass. |
| `docs/reference/architecture.md` | MODIFY | Mount table + `INV-D003` reference. |
| `README.md` | MODIFY | Storage planning section final pass. |
| `docs/plans/active/storage-scratch-layout/` | MOVE → completed | With `_SUPERSEDED.md` closing note. |
| `docs/plans/active/cram-scratch-strategy/` | MOVE → completed | After all of the above. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_eject.py tests/integration/test_doctor.py \
              tests/integration/test_invD003_scratch_discipline.py -v
uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

**Real-data smoke**:

```bash
# doctor: should report all green against the live Kingston.
bin/genomeclaw-prep doctor

# doctor --json: machine-readable output.
bin/genomeclaw-prep doctor --json | jq .

# eject: stops colima + diskutil eject /Volumes/Genome_Work.
# (User-facing — only when actually disconnecting the drive.)
bin/genomeclaw-prep eject
```

---

## Completion Criteria

- [ ] All listed unit / integration tests pass
- [ ] Static checks pass
- [ ] `INV-D003` test (`test_invD003_orchestrators_write_heavy_scratch_to_scratch_mount`) passes
- [ ] `doctor` reports green against the live Kingston
- [ ] `eject` cleanly stops colima + ejects the drive (one live test, manual confirmation)
- [ ] `INV-D003` is in `INVARIANTS.md` with full Rule / Requirements / Where / Verify; v1.5 → v1.6
- [ ] `user-stories.md` Story 1 Step 0 reflects post-Phase-5 reality (no aspirational "Phase 5 of the plan" parentheticals)
- [ ] `README.md` Storage planning section reflects post-pivot reality
- [ ] `docs/reference/architecture.md` mount table updated
- [ ] `storage-scratch-layout/` moved to `completed/` with closing note
- [ ] `cram-scratch-strategy/` moved to `completed/`
- [ ] `work-notes.md` final session block recording phase close
- [ ] Phase status updated in `development-plan.md`

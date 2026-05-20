# Phase 1: Doc rollup + invariant promotion + conventions tightening

**Status**: In progress
**Started**: 2026-05-20
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Close the documentation + invariant gap left by the smoke v7–v17 iterations. Most of the code already shipped as point fixes; this phase binds them into the planning protocol + promotes the operational invariants the iterations earned.

## Scope Boundaries

- **In scope**: documentation backfill (work-notes — already drafted), `INVARIANTS.md` updates for `INV-R002` + `INV-D008`, `architecture.md` traceability rows, `PgscCalcConventions` value-type descriptors + tests.
- **Out of scope**: the F3–F6 follow-ups (separate plans on demand).

## Invariants Enforced

- **`INV-R002` (NEW)** — Never Cache a Degenerate Result. Tests already exist in `test_prs_coverage_fill_*.py::test_force_genotype_tier*_refuses_to_cache_empty_vcf`.
- **`INV-D008` (NEW)** — Copy-Stage for DooD-Spawning Pipelines. Tests already exist in `test_pgsc_calc_wrapper.py::test_compute_pgs_writes_nextflow_config_redirecting_tmpdir`.
- **`INV-T001` (TIGHTENING)** — Value-type descriptors added to `PgscCalcConventions`; new tests assert wrapper argv matches descriptor patterns.

## TDD Steps

### Step 1.1 — RED: Write failing tests for conventions value-types

**Test cases** (in `tests/unit/test_pgsc_calc_conventions.py`):

1. `test_pgsc_calc_conventions_run_ancestry_value_pattern_matches_tarball`:
   - Asserts `PgscCalcConventions().run_ancestry_value_pattern` matches a tarball-shaped string (`/x/y.tar.zst`) and DOES NOT match a directory (`/x/y/`).
2. `test_pgsc_calc_conventions_input_value_pattern_matches_csv`:
   - Asserts `input_value_pattern` matches `samplesheet.csv` and rejects `samplesheet.vcf`.
3. `test_build_pgsc_calc_argv_run_ancestry_value_matches_conventions_pattern`:
   - Builds argv via `_build_pgsc_calc_argv`, locates the `--run_ancestry` value, asserts it matches the conventions' pattern. Catches the v10-class regression at unit-test time.

**Confirm failure**: tests fail with `AttributeError: 'PgscCalcConventions' object has no attribute 'run_ancestry_value_pattern'`.

### Step 1.2 — GREEN: Add descriptors + lift invariants

**Files modified**:

- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py`:
  - Add `run_ancestry_value_kind = "file"`, `run_ancestry_value_pattern = r".*\.tar\.zst$"`.
  - Add `input_value_kind = "file"`, `input_value_pattern = r".*\.csv$"`.
  - Bump `verified_against_version` if any field changes (no — version unchanged).

- `tools/pgsc_calc/probe-output.txt`:
  - Add the four new fields as KEY=VALUE lines so the probe-output baseline test (`test_invT001_pgsc_calc_conventions_field_values_match_probe_output`) keeps passing.

- `docs/reference/INVARIANTS.md`:
  - Version bump 1.13 → 1.14 + Last Updated.
  - Add §"v1.14" header note citing this plan.
  - Add `INV-R002` entry under §INV-R (alongside `INV-R001`).
  - Add `INV-D008` entry under §INV-D (after `INV-D007`).
  - Add 2 rows to the Invariant Index table.

- `docs/reference/architecture.md`:
  - Add 2 rows to the "Why this shape — invariant traceability" table (`INV-R002`, `INV-D008`).
  - One-line note in PRS pipeline subsection: "Tier 1/2 force-genotyping guards against degenerate-cache failures via `_count_vcf_records` (INV-R002); pgsc_calc nextflow inputs are copy-staged into work-dirs (INV-D008)."

### Step 1.3 — REFACTOR: Verify cross-references

- Run `grep -rn 'INV-R002\|INV-D008' docs/` and assert every "How to verify" line cites a test that exists.
- Run full suite — expect 699 + 3 new tests = 702 passed.
- Ruff + mypy clean on the conventions file.

## Files

| Action | Path | Purpose |
| --- | --- | --- |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py` | +4 value-type descriptors |
| MODIFY | `tools/pgsc_calc/probe-output.txt` | +4 KEY=VALUE baseline lines |
| MODIFY | `packages/toolkit/tests/unit/test_pgsc_calc_conventions.py` | +3 tests for value-type contract |
| MODIFY | `docs/reference/INVARIANTS.md` | v1.13 → v1.14; +2 entries + index |
| MODIFY | `docs/reference/architecture.md` | +2 traceability rows + PRS pipeline note |

## Verification

```bash
cd packages/toolkit
uv run pytest tests/unit/test_pgsc_calc_conventions.py -v --no-header
uv run pytest tests/unit tests/integration tests/invariants --no-header
uv run ruff check src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py
uv run mypy src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py
```

Cross-reference grep:
```bash
grep -rn 'INV-R002\|INV-D008' docs/
```

## Completion Criteria

- [ ] 3 new conventions tests pass; full suite green; ruff + mypy clean.
- [ ] `INVARIANTS.md` v1.14 lifted with both new entries + index updated.
- [ ] `architecture.md` carries the 2 new traceability rows.
- [ ] `tools/pgsc_calc/probe-output.txt` includes the 4 new value-type fields.
- [ ] `work-notes.md` Phase 1 closure entry written.
- [ ] Smoke v17 outcome recorded in work-notes (success or guard-fire diagnosis).

# PRS Pipeline Runtime Hardening — Development Plan

**Plan**: [spec.md](spec.md) | **Work Notes**: [work-notes.md](work-notes.md)
**Lineage**: follows [path-crossing-discipline](../../completed/path-crossing-discipline/) (closed 2026-05-19).

---

## Critical Invariants to Respect

- **`INV-D001`** Raw RO — Tier 1 + Tier 2 force-genotyping read the CRAM read-only; the new guards fail closed (raise) rather than overwrite.
- **`INV-D003`** Heavy scratch separated — empty-cache guard runs inside `shard_scratch`; the `atomic_promote` is conditional on validation passing.
- **`INV-D005` / `INV-D006` / `INV-D007`** Path-crossing discipline — every path in this plan flows host-form through the wrapper boundary into siblings.
- **`INV-T001`** External-tool conventions — this plan strengthens pgsc_calc's conventions dataclass with value-type semantics.
- **`INV-R001`** Rebuildability — the empty-cache guard MAKES Tier 1/2 rebuildable cleanly; without it, a degenerate cache poisons future runs.

## Proposed New Invariants

**`INV-R002` — Never Cache a Degenerate Result.** Lifted into [INVARIANTS.md](../../../reference/INVARIANTS.md) at plan completion.
**`INV-D008` — Copy-Stage for DooD-Spawning Pipelines.** Lifted into INVARIANTS.md at plan completion.
(Full proposed texts in [spec.md §Proposed New Invariants](spec.md#proposed-new-invariants).)

## Current State Analysis

**What's already shipped** (point-fixes during smoke iterations v7–v17):

| Fix | Location | Test coverage |
|-----|----------|---------------|
| Env-var pgsc_calc resource caps (`GENOMECLAW_PGSC_CALC_MAX_MEMORY/CPUS`) | `pgs.py:_build_pgsc_calc_argv` | argv-shape coverage in `test_pgsc_calc_wrapper.py` |
| `_ancestry_reference_bundle()` returns `.tar.zst` path, not directory | `pgs.py` | — (TBD by this plan) |
| `_TMPDIR_REDIRECT_CONFIG` writes nextflow.config to work_dir | `pgs.py:_write_pgsc_calc_nextflow_config` | `test_pgsc_calc_wrapper.py::test_compute_pgs_writes_nextflow_config_redirecting_tmpdir` |
| `stageInMode = 'copy'` in nextflow.config | `pgs.py:_TMPDIR_REDIRECT_CONFIG` | same test, additional assertions |
| Sampleset strip `.vcf` + `.gz` | `pgs.py:compute_pgs` | `test_pgsc_calc_wrapper.py::test_compute_pgs_samplesheet_sampleset_has_no_period` |
| Autosomes-only filter in merged VCF | `coverage_fill.py:_merge_tier1_tier2` | `test_prs_coverage_fill_tier2.py::test_merge_tier1_tier2_filters_to_autosomes_only` |
| `_count_vcf_records()` + empty-cache guard for Tier 1 & Tier 2 | `coverage_fill.py:_force_genotype_tier1/2` | `test_prs_coverage_fill_*.py::test_force_genotype_tier*_refuses_to_cache_empty_vcf` |

**What's left for THIS plan to deliver:**

1. **Iteration ledger** (work-notes.md): document each v7–v17 with root cause + fix + diff reference.
2. **INVARIANTS.md updates**: lift `INV-R002` + `INV-D008` with full Rule / Requirements / Where it applies / How to verify.
3. **PgscCalcConventions value-type tightening**: add per-flag value-type descriptors so a future bundle-extraction change surfaces as a typed-test failure (the gap that allowed v10's "wrong path" to silently break).
4. **Architecture.md update**: add `INV-R002` + `INV-D008` rows to the invariant-traceability table; brief note in the PRS pipeline subsection.

## Solution Design

**Phase 1 — Documentation + invariant promotion + conventions tightening.**

Single phase. Three slices:

### Slice 1.A — Smoke iteration ledger (work-notes)

Backfill the v7–v17 history into [work-notes.md](work-notes.md) as a single canonical entry. Each row: smoke version, root-cause class, observed failure, fix landed, test added, commit hash (TBD when committed).

### Slice 1.B — Promote `INV-R002` + `INV-D008` into INVARIANTS.md

- Version bump 1.13 → 1.14.
- Add `INV-R002` entry under §INV-R category (alongside `INV-R001`).
- Add `INV-D008` entry under §INV-D category (alongside `INV-D005`/`D006`/`D007`).
- Update Invariant Index with both rows.
- Add a §"v1.14" note at the top citing this plan.

The "How to verify" lines cite the existing tests landed during the smoke iterations:
- `INV-R002`: `test_force_genotype_tier1_refuses_to_cache_empty_vcf` + `test_force_genotype_tier2_refuses_to_cache_empty_vcf` in `test_prs_coverage_fill_*.py`.
- `INV-D008`: `test_compute_pgs_writes_nextflow_config_redirecting_tmpdir` in `test_pgsc_calc_wrapper.py` (asserts both TMPDIR redirect + stageInMode='copy').

### Slice 1.C — `PgscCalcConventions` value-type tightening

Add a structured "what kind of value does this flag accept" descriptor for each path-typed flag:

```python
# Currently:
run_ancestry_flag: str = "--run_ancestry"

# After Slice 1.C:
run_ancestry_flag: str = "--run_ancestry"
run_ancestry_value_kind: str = "file"  # not "dir"
run_ancestry_value_pattern: str = r".*\.tar\.zst$"  # tarball, not extracted dir
```

Plus a unit test that asserts the wrapper's argv `--run_ancestry` value matches the pattern. This means a future regression (someone pointing the value at a directory again) surfaces as a typed test failure, not as a 5-hour smoke iteration to diagnose.

Apply the same descriptor to `input_flag` (samplesheet CSV file) for symmetry — a future regression to "pass the VCF directly to --input" would surface here.

### Slice 1.D — Architecture.md cross-references

Add two rows to the invariant-traceability table (INV-R002, INV-D008) + a one-line note in the PRS pipeline subsection that "Tier 1/2 force-genotyping guards against degenerate-cache failures via `_count_vcf_records` (INV-R002)".

## Phase Overview

| Phase | TDD focus | Tests | Promotes |
|-------|-----------|-------|----------|
| **Phase 1** (this plan, single phase) | Doc-rollup + invariant promotion + conventions tightening | 2 new unit tests for conventions value-type assertions; existing tests stay green | `INV-R002`, `INV-D008` |

If the conventions tightening grows past ~3 fields, split out a Phase 2. Initial scope: 2 fields (`run_ancestry_value_*`, `input_value_*`) is enough to cover what we've learned.

## Testing Strategy

| Category | Coverage |
|----------|----------|
| **Unit** | 2 new tests asserting `--run_ancestry` value matches `*.tar.zst` pattern + `--input` value matches `*.csv` pattern. |
| **Integration** | No new ones — the empty-cache guard, TMPDIR redirect, stageInMode='copy', sampleset, autosome filter, chrX-handling all already have tests landed during the smoke iterations. |
| **Provenance** | None new (the guard preserves INV-R001's rebuildability — testing the guard IS the provenance test). |
| **Determinism** | None new. |
| **Privacy** | None new (no egress changes). |
| **Invariant** | The `INV-R002` + `INV-D008` "How to verify" lines cite the existing tests; no new invariant-discovery test needed. |
| **Real-tool smoke** | Smoke v18 (whenever Tier 2 produces real records) acts as the validation gate. Documented in work-notes; not a recurring CI test. |

## Documentation Updates

- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md): v1.13 → v1.14; +2 entries; +2 index rows.
- [docs/reference/architecture.md](../../../reference/architecture.md): +2 traceability rows; one-line note in PRS pipeline subsection.
- [docs/plans/CLAUDE.md](../../CLAUDE.md): no edits (the test-category table already covers "Provenance" + "Invariant" which subsume INV-R002/D008).

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — doc rollup + invariant promotion + conventions tightening | Complete | 2026-05-20 | 2026-05-20 | All 4 slices landed; INVARIANTS.md v1.14; 702 tests pass; 41 cross-refs verified. |

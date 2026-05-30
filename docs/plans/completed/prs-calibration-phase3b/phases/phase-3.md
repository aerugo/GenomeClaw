# Phase 3: PGS Catalog AUC-Improvement Gate

**Plan**: [development-plan.md](../development-plan.md)
**Status**: **Complete (2026-05-26)**. New `_pgs_catalog_meta.py` module + extended `classify_calibration` with `pgs_auc_delta` + `pgs_top_decile_ci_lower` kwargs + the `PGS_CATALOG_TIER_INSUFFICIENT` branch. 17 new tests landed (8 parser + 9 classifier branch). No schema change (the AUC delta + abstain reason land in `params_json` per the development plan's schema-impact table).
**Invariants enforced in this phase**: INV-C001 v1.7, INV-R001, INV-A003, INV-P001

---

## Outcome summary

### Files created

- [packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_catalog_meta.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_catalog_meta.py)
  - `EvalMetricsResult` frozen dataclass: (`source`, `auc_delta`, `top_decile_ci_lower`, `abstain_reason`).
  - `parse_pgs_catalog_eval_metrics(work_dir, reference_root, pgs_id)`:
    1. Searches `<work_dir>/**/log_scorefiles.json` (Nextflow hash-dir aware via `rglob`).
    2. Falls back to `<reference_root>/pgs_catalog/<pgs_id>.json`.
    3. Returns `source='abstain'` with structured `abstain_reason` (`metrics_unavailable` / `baseline_model_unspecified` / `auc_unavailable` / `malformed_metadata`) when no metrics are available.
- [packages/toolkit/tests/unit/test_pgs_catalog_meta.py](../../../../packages/toolkit/tests/unit/test_pgs_catalog_meta.py) — 8 tests including INV-P001 monkeypatched-`urlopen` no-network smoke.
- [packages/toolkit/tests/unit/test_pgs_qc_pgs_catalog_tier_branch.py](../../../../packages/toolkit/tests/unit/test_pgs_qc_pgs_catalog_tier_branch.py) — 9 tests covering BOTH-conditions-required trigger, abstain on missing, decline priority (overlap > ancestry > tier), threshold constants.

### Files modified

- `_pgs_qc.py`:
  - Added two threshold constants: `_QC_AUC_DELTA_THRESHOLD = 0.02`, `_QC_TOP_DECILE_CI_FLOOR = 1.5`.
  - Extended `classify_calibration` with `pgs_auc_delta: float | None` + `pgs_top_decile_ci_lower: float | None` kwargs.
  - Added the `PGS_CATALOG_TIER_INSUFFICIENT` branch (fires only when BOTH conditions hold — abstain on either missing per INV-P001).
  - Updated module docstring: Phase 3a → Phase 3b implementation status; explicit listing of the two enum-declared decline reasons that remain deferred (`POPULATION_TRANSFERABILITY_INSUFFICIENT`, `PHENOTYPE_HETEROGENEOUS`).

### Decline priority order (in `classify_calibration`)

1. Variant overlap (count + effect-weight worst-of-two axes) → `VARIANT_OVERLAP_INSUFFICIENT`.
2. Ancestry calibration (Mahalanobis distance + single-ancestry GWAS) → `ANCESTRY_CALIBRATION_UNCERTAIN`.
3. PGS Catalog tier (AUC delta + top-decile CI lower) → `PGS_CATALOG_TIER_INSUFFICIENT`.

First matching DECLINE wins; the structural decline reason carries the canonical structural meaning per INV-C001 v1.7.

### Open follow-up

The `compute_pgs` call-site in `pgs.py` does not yet automatically invoke
`parse_pgs_catalog_eval_metrics` and thread its result into the classifier.
That wiring lands in the Phase 4 real-data smoke session because the exact
key names in pgsc_calc's `log_scorefiles.json` need to be confirmed against
a real run. The classifier surface is stable; the orchestrator integration
is the remaining step.

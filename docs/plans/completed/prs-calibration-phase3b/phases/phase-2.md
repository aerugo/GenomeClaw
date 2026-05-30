# Phase 2: Mahalanobis Ancestry Trigger

**Plan**: [development-plan.md](../development-plan.md)
**Status**: **Complete (2026-05-26)**. New `_pgs_fraposa.py` module + extended `classify_calibration` + v0.4 schema bump + `PgsRow` / `stamp_pgs_row` wiring all GREEN. 28 new tests landed (13 fraposa + 10 ancestry-branch + 3 integration + 2 provenance). Real-data smoke and the per-row FRAPOSA call-site wiring in `compute_pgs` are deferred to Phase 4's project-owner smoke session.
**Invariants enforced in this phase**: INV-C001 v1.7, INV-R001, INV-R002, INV-A003, INV-P001

---

## Overview

Phase 2 creates `_pgs_fraposa.py`, which parses pgsc_calc's FRAPOSA intermediate outputs to extract per-sample top-10 PC coordinates and compute Mahalanobis distances to each 1kGP+HGDP superpopulation centroid. The minimum distance and nearest superpopulation label are persisted in two new `pgs_scores` columns. The `ANCESTRY_CALIBRATION_UNCERTAIN` branch in `classify_calibration` is implemented: decline triggers when `min_distance > 3.0` AND the PGS GWAS discovery was in exactly one ancestry group.

FRAPOSA's output files are present in the pgsc_calc work-dir after a `--run_ancestry` run. The 2026-05-21 real-data smoke confirms their locations:
- Per-sample PC file: `<work_dir>/ancestry/fraposa/project/GRCh38_norm_oriented_norm_splitfamaa.pcs`
- Reference panel PC file: `<work_dir>/ancestry/fraposa/pca/GRCh38_reference_extracted.pcs`

Both files are tab-delimited (`FID IID PC1 PC2 PC3 PC4 PC5 PC6 PC7 PC8 PC9 PC10`).

Population labels for the reference samples must be joined from the 1kGP+HGDP sample metadata TSVs under `reference_root/ancestry/`. The reference panel `.pcs` file contains only `FID`/`IID`; the population is recoverable via `IID → superpopulation` using the panel's sample metadata (e.g., `integrated_call_samples_v3.20200731.ALL.ped` for 1kGP, or HGDP's sample info TSV).

---

## Inputs

| Artifact | Location | Identity |
|---|---|---|
| Per-sample FRAPOSA PC file | `<work_dir>/ancestry/fraposa/project/<sampleset>.pcs` | path |
| Reference panel FRAPOSA PC file | `<work_dir>/ancestry/fraposa/pca/GRCh38_reference_extracted.pcs` | path |
| 1kGP sample metadata | `reference_root/ancestry/1000g/<panel_ped_or_metadata>.tsv` | path |
| HGDP sample metadata | `reference_root/ancestry/hgdp/<hgdp_metadata>.tsv` | path |
| `gwas_ancestry` metadata | From `log_scorefiles.json` or `reference_root/pgs_catalog/<pgs_id>.json` | source documented in `params_json` |

## Outputs

| Artifact | Location | Schema change |
|---|---|---|
| `pgs_scores.fraposa_min_mahalanobis_distance` | `derived/<run-id>/variants.duckdb` | New `DOUBLE` column (nullable) |
| `pgs_scores.fraposa_nearest_superpop` | Same | New `TEXT` column (nullable) |
| `params_json` additions | Same row | `fraposa_pcs_file_path`, `fraposa_ref_pcs_file_path`, `gwas_ancestry_raw` |

---

## Step 2.1 — RED: write failing tests

### Test cases to write

#### `tests/unit/test_pgs_fraposa.py`

**`test_parse_fraposa_pcs_returns_sample_vector`**
- Fixture: synthetic per-sample `.pcs` file with one row (`FID=S1, IID=S1, PC1=-10.58, …, PC10=2.24`).
- Assert: function returns a dict or dataclass with `sample_id = "S1"` and a length-10 numpy array with the correct values.

**`test_parse_fraposa_pcs_raises_on_zero_data_rows`** (INV-R002)
- Fixture: header-only `.pcs` file (no data rows).
- Assert: raises `FraposaPcsError` with message containing "0 sample rows" and "NOT processing degenerate FRAPOSA output".
- Test name contains `INV-R002`.

**`test_parse_fraposa_ref_pcs_groups_by_superpopulation`**
- Fixture: synthetic reference `.pcs` file with 6 rows; 2 from EUR, 2 from AFR, 2 from EAS.
- Population label map (from sample metadata): `{IID → superpop}`.
- Assert: function returns a dict `{superpop: ndarray(n_samples, 10)}` with three keys and correct shapes.

**`test_compute_superpop_centroids`**
- Input: `{EUR: ndarray([[1,0,0,...],[3,0,0,...]])}` (2 samples, PC1 values 1 and 3).
- Assert: centroid for EUR is `[2.0, 0, 0, …]`.

**`test_mahalanobis_distance_known_value`**
- Single superpop EUR with 3 samples forming a known covariance structure.
- Compute expected distance manually (or via scipy reference).
- Assert: function returns value within 1e-6 of expected.

**`test_mahalanobis_distance_min_and_nearest_superpop`**
- Two superpopulations with known centroids and covariances.
- Query point is closer to superpop B than superpop A.
- Assert: `fraposa_min_mahalanobis_distance` matches superpop B's distance; `fraposa_nearest_superpop == "B"`.

**`test_mahalanobis_distance_degenerate_covariance_raises`**
- Reference panel has 2 samples for EUR that are identical (zero-variance; covariance matrix is singular).
- Assert: raises `FraposaPcsError` mentioning "singular covariance matrix" and the superpopulation name.

**`test_parse_fraposa_pcs_handles_sampleset_glob`**
- Work-dir has the file at `ancestry/fraposa/project/GRCh38_norm_oriented_norm_splitfamaa.pcs`.
- Function receives `work_dir` and `sampleset = "norm_oriented_norm_splitfamaa"`.
- Assert: the file is found without knowing the exact prefix.

#### `tests/unit/test_pgs_qc_ancestry_branch.py`

**`test_classify_calibration_declines_ancestry_when_distance_exceeds_threshold_single_ancestry`** (INV-C001)
- `fraposa_min_mahalanobis_distance = 3.5`, `gwas_ancestry_superpop_count = 1`, all overlap axes above clean floor.
- Assert: `DECLINE` with `ANCESTRY_CALIBRATION_UNCERTAIN`.

**`test_classify_calibration_does_not_decline_ancestry_when_distance_below_threshold`**
- `fraposa_min_mahalanobis_distance = 2.5`, single ancestry GWAS.
- Assert: `CLEAN` (no overlap issues).

**`test_classify_calibration_does_not_decline_ancestry_when_multi_ancestry_gwas`**
- `fraposa_min_mahalanobis_distance = 4.0`, `gwas_ancestry_superpop_count = 2`.
- Assert: `CLEAN` (the multi-ancestry GWAS case is NOT declined on this axis).

**`test_classify_calibration_abstains_ancestry_when_distance_is_none`**
- `fraposa_min_mahalanobis_distance = None`.
- Assert: no decline for `ANCESTRY_CALIBRATION_UNCERTAIN` regardless of GWAS ancestry.

**`test_classify_calibration_both_overlap_and_ancestry_decline_yields_overlap_reason`**
- Overlap match rate below decline floor AND Mahalanobis distance > 3.0 + single ancestry.
- Assert: `DECLINE` with `VARIANT_OVERLAP_INSUFFICIENT` (overlap check runs first; first-matching decline is returned).
- Documents the evaluation priority: overlap → ancestry → AUC gate.

**`test_INV_C001_ancestry_calibration_branch_enforced`** (INV-C001 invariant test)
- Parametrized: for all three tier levels, with distance = 4.0 and single-ancestry GWAS, all overlap axes clean.
- Assert: `DECLINE` with `ANCESTRY_CALIBRATION_UNCERTAIN` for all tiers.

#### `tests/integration/test_pgs_fraposa_integration.py`

**`test_fraposa_distances_persisted_in_pgs_scores`**
- Fixture: synthetic FRAPOSA `.pcs` files + synthetic reference metadata + DuckDB store.
- Call `compute_pgs` with stubbed pgsc_calc subprocess (returns success; work-dir has the synthetic `.pcs` files).
- Assert: `pgs_scores` row has non-null `fraposa_min_mahalanobis_distance` and `fraposa_nearest_superpop`.

**`test_fraposa_params_json_carries_pcs_paths`** (INV-R001 + INV-A003 provenance test)
- Same fixture. Assert `params_json` contains `fraposa_pcs_file_path` and `fraposa_ref_pcs_file_path`.

**`test_fraposa_params_json_carries_gwas_ancestry_raw`** (INV-A003)
- Same fixture with a PGS Catalog metadata JSON at `reference_root/pgs_catalog/<pgs_id>.json` containing `gwas_ancestry = "EUR"`.
- Assert `params_json` contains `gwas_ancestry_raw = "EUR"`.

**`test_INV_R002_degenerate_fraposa_pcs_does_not_produce_stored_row`** (INV-R002)
- Fixture: header-only per-sample `.pcs` file (zero data rows).
- Assert: `FraposaPcsError` raised; no `pgs_scores` row is inserted.

#### `tests/provenance/test_pgs_scores_schema_version_phase2.py`

**`test_pgs_scores_schema_version_bumped_after_phase2_migration`** (INV-R001)
- Apply Phase 2 migration on a Phase-1-state store; query `schema_meta`; assert version matches expected value.
- Assert both new columns (`fraposa_min_mahalanobis_distance`, `fraposa_nearest_superpop`) are present in the schema.

### Confirm tests fail

```bash
python -m pytest packages/toolkit/tests/unit/test_pgs_fraposa.py \
  packages/toolkit/tests/unit/test_pgs_qc_ancestry_branch.py -v
```

Expected: `ImportError` on `from genomeclaw_toolkit.prep._pgs_fraposa import ...` and `TypeError` on `classify_calibration` call missing new keyword argument.

---

## Step 2.2 — GREEN: minimal implementation

### Files to CREATE

#### `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_fraposa.py`

Exports (at minimum):
- `FraposaPcsError(RuntimeError)` — typed error for degenerate or malformed `.pcs` files.
- `parse_fraposa_sample_pcs(pcs_path: Path) -> dict[str, ndarray]` — returns `{sample_id: pc_vector}` for the per-sample file.
- `parse_fraposa_ref_pcs(pcs_path: Path, pop_label_map: dict[str, str]) -> dict[str, ndarray]` — returns `{superpop: ndarray(n_samples, 10)}` for the reference panel.
- `compute_mahalanobis_distances(sample_vec: ndarray, ref_by_superpop: dict[str, ndarray]) -> tuple[float, str]` — returns `(min_distance, nearest_superpop_label)`.
- `find_fraposa_project_pcs(work_dir: Path, *, sampleset: str) -> Path | None` — globs for `<work_dir>/ancestry/fraposa/project/*<sampleset>.pcs`; returns first match or `None`.

Implementation notes:
- `compute_mahalanobis_distances`: use `scipy.spatial.distance.mahalanobis` when scipy is available; pure-numpy fallback when not. Both paths are covered by the unit tests.
- Singular covariance: catch `numpy.linalg.LinAlgError` (or equivalent from scipy) and raise `FraposaPcsError` naming the superpopulation. A superpop with fewer samples than PCs (< 10 samples) produces a rank-deficient covariance; add a pre-check that raises before the inversion.
- INV-R002 guard: after reading the per-sample `.pcs` file, if the data row count is zero, raise `FraposaPcsError` before any distance computation.
- `gwas_ancestry_superpop_count` helper: `parse_gwas_ancestry_superpops(gwas_ancestry_str: str) -> set[str]` — parses PGS Catalog's ancestry notation (e.g., `"European"`, `"EUR"`, `"European, South Asian"`) into a set of canonical superpopulation codes. When parsing fails or the string is empty, returns the empty set (which causes the ancestry trigger to abstain).

### Files to MODIFY

#### `_pgs_qc.py`

Extend `classify_calibration` with new keyword-only parameters:
```python
def classify_calibration(
    *,
    match_rate: float,
    pgs_variant_count: int,
    effect_weight_match_rate: float | None = None,
    fraposa_min_mahalanobis_distance: float | None = None,
    gwas_ancestry_superpop_count: int | None = None,
) -> CalibrationDecision:
```

Add the `ANCESTRY_CALIBRATION_UNCERTAIN` branch after the overlap check:
```python
if (
    fraposa_min_mahalanobis_distance is not None
    and fraposa_min_mahalanobis_distance > _QC_MAHAL_THRESHOLD
    and gwas_ancestry_superpop_count is not None
    and gwas_ancestry_superpop_count == 1
):
    return CalibrationDecision(
        status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN,
    )
```

Add `_QC_MAHAL_THRESHOLD: float = 3.0` constant near the existing `_TIER_SMALL_MAX` constants.

#### `pgs.py`

After pgsc_calc completes, call `_pgs_fraposa.find_fraposa_project_pcs` and, if found, `parse_fraposa_sample_pcs` and `compute_mahalanobis_distances`. Populate `PgsRow.fraposa_min_mahalanobis_distance` and `PgsRow.fraposa_nearest_superpop`. Add FRAPOSA path values to `params_json`. Load `gwas_ancestry` from `log_scorefiles.json` or `reference_root/pgs_catalog/<pgs_id>.json`; add `gwas_ancestry_raw` to `params_json`.

#### `store.py`

Add `fraposa_min_mahalanobis_distance DOUBLE` and `fraposa_nearest_superpop TEXT` to `_PGS_SCORES_DDL`. Bump schema version.

#### `pgs.py` `PgsRow` dataclass

Add `fraposa_min_mahalanobis_distance: float | None = None` and `fraposa_nearest_superpop: str | None = None`.

### Run tests green

```bash
python -m pytest packages/toolkit/tests/unit/test_pgs_fraposa.py \
  packages/toolkit/tests/unit/test_pgs_qc_ancestry_branch.py \
  packages/toolkit/tests/integration/test_pgs_fraposa_integration.py \
  packages/toolkit/tests/provenance/test_pgs_scores_schema_version_phase2.py -v

python -m pytest packages/toolkit/tests/ -v
```

---

## Step 2.3 — REFACTOR

- Ensure `_pgs_fraposa.py` exports are complete and listed in `__all__`.
- Ensure `FraposaPcsError` message format is consistent: "FRAPOSA .pcs file <path> contained N sample rows; expected >= 1. NOT processing degenerate FRAPOSA output. [Common causes: pgsc_calc did not run `--run_ancestry`, FRAPOSA failed silently, incorrect sampleset name glob]."
- Ensure `parse_gwas_ancestry_superpops` handles at least these PGS Catalog ancestry string formats: plain English (`"European"`), abbreviation (`"EUR"`), comma-separated multi-ancestry (`"European, South Asian"`), semicolon-separated, empty string. Add note for any format not handled.
- Verify that the scipy import is guarded and the fallback path is tested explicitly (add one test for the `scipy_unavailable=True` case via monkeypatching).
- Re-run full test suite.

---

## Files

| Action | File | Notes |
|---|---|---|
| CREATE | `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_fraposa.py` | New module: FRAPOSA PC parsing + Mahalanobis distance |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py` | Add `ANCESTRY_CALIBRATION_UNCERTAIN` branch + `_QC_MAHAL_THRESHOLD` constant |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | Wire FRAPOSA parsing; populate `PgsRow` fields; populate `params_json` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | Add two new columns; bump schema version |
| CREATE | `packages/toolkit/tests/unit/test_pgs_fraposa.py` | Unit tests for new module |
| CREATE | `packages/toolkit/tests/unit/test_pgs_qc_ancestry_branch.py` | Unit tests for ancestry branch |
| CREATE | `packages/toolkit/tests/integration/test_pgs_fraposa_integration.py` | Integration + provenance + INV-R002 tests |
| CREATE | `packages/toolkit/tests/provenance/test_pgs_scores_schema_version_phase2.py` | Schema version provenance test |

---

## Verification

```bash
# New tests only (fast)
python -m pytest packages/toolkit/tests/unit/test_pgs_fraposa.py \
  packages/toolkit/tests/unit/test_pgs_qc_ancestry_branch.py -v

# Integration + provenance
python -m pytest packages/toolkit/tests/integration/test_pgs_fraposa_integration.py \
  packages/toolkit/tests/provenance/test_pgs_scores_schema_version_phase2.py -v

# Full suite
python -m pytest packages/toolkit/tests/ -v
```

---

## Completion criteria

- [ ] All Phase 2 tests pass (RED → GREEN → REFACTOR).
- [ ] `INV-C001_ancestry_calibration_branch_enforced` test is green.
- [ ] `INV-R002_degenerate_fraposa_pcs_does_not_produce_stored_row` test is green.
- [ ] INV-R001 + INV-A003 provenance tests (`fraposa_params_json_*`) are green.
- [ ] Schema version bumped in `store.py`; migration SQL documented in `work-notes.md`.
- [ ] scipy-unavailable fallback test is green.
- [ ] Full toolkit test suite is green with no regressions.
- [ ] `work-notes.md` updated with Phase 2 summary.
- [ ] `development-plan.md` Phase overview table shows Phase 2 green.
- [ ] `phases/phase-3.md` exists before this phase is closed.
- [ ] _(Forward note — applies to final phase, phase-4.md, when written)_ Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

---

## Open question resolution

### Q1 — Mahalanobis threshold value

The constant `_QC_MAHAL_THRESHOLD = 3.0` is used in this phase. If review of FRAPOSA's published thresholds (see FRAPOSA GitHub repo documentation) reveals a different calibrated value, update the constant before the phase is marked complete. Document the rationale for the chosen value in the `_pgs_qc.py` comment adjacent to the constant.

### Q2 — GWAS ancestry metadata source

Before coding `pgs.py`'s call to load `gwas_ancestry`, inspect the real `log_scorefiles.json` from a pgsc_calc run to confirm whether it carries PGS Catalog ancestry metadata. If it does not, use `reference_root/pgs_catalog/<pgs_id>.json` as the primary source. Document the resolution in `work-notes.md` before Step 2.2.

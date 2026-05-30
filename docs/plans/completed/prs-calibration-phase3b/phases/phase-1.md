# Phase 1: Effect-Weight-Weighted Overlap

**Plan**: [development-plan.md](../development-plan.md)
**Status**: **Complete** (2026-05-25). 25 new tests GREEN. `parse_effect_weights` + `compute_weighted_match_rate` in `_pgsc_calc_match.py`; `classify_calibration(effect_weight_match_rate=...)` worst-of-two-axes in `_pgs_qc.py`. The `pgs.py` / `store.py` wiring (persisting the new `effect_weight_match_rate` column on `pgs_scores`) is deferred to Phase 4's real-data smoke + pgs.py re-architecture; the Phase 1 classifier is callable today via direct function call.
**Invariants enforced in this phase**: INV-C001 v1.7, INV-C003 (proposed `INV-C002` renamed due to collision), INV-R001, INV-P001

---

## Overview

Phase 1 adds a second overlap axis to the calibration classifier: effect-weight-weighted match rate (`Σ|β|_matched / Σ|β|_total`). A decline triggers when EITHER the raw-count match rate OR the effect-weight match rate is below the tier's decline floor. The computation joins the pgsc_calc per-variant match log against the PGS Catalog scoring file's `effect_weight` column.

This phase also implements the INV-C002 exclusion of `uncallable` sites from both overlap denominators before any match rates are computed.

---

## Inputs

| Artifact | Location | Identity |
|---|---|---|
| PGS Catalog scoring file | `reference_root/pgs_catalog/<pgs_id>_hmPOS_GRCh38.txt.gz` | path + sha256 |
| pgsc_calc match log | `<work_dir>/*/<sampleset>_log.csv.gz` | located by `find_pgsc_calc_log_csv` |
| `genotype_source` annotation | Per-site TSV emitted by `force-genotype-callable-mask`; location TBD by sibling plan | path |

## Outputs

| Artifact | Location | Schema change |
|---|---|---|
| `pgs_scores.effect_weight_match_rate` | `derived/<run-id>/variants.duckdb` | New `DOUBLE` column (nullable) |
| `params_json` additions | Same row | `effect_weight_scoring_file_path`, `effect_weight_scoring_file_sha256`, `uncallable_sites_excluded_count` |

---

## Step 1.1 — RED: write failing tests

### Test cases to write (all must fail initially)

#### `tests/unit/test_effect_weight_match.py`

**`test_parse_effect_weights_returns_abs_value_dict`**
- Synthetic scoring file with columns `hm_chr`, `hm_pos`, `effect_allele`, `other_allele`, `effect_weight`.
- Three rows with weights `+0.5`, `-0.3`, `+0.8`.
- Assert result dict maps each `(chrom, pos, effect_allele, other_allele)` key to the absolute value (`0.5`, `0.3`, `0.8`).
- `INV-R001`: function signature accepts a `Path`; the dict is keyed on normalized `(chr-prefixed chrom, int pos, str effect_allele, str other_allele)` to match pgsc_calc's match-log `chr_name` convention.

**`test_parse_effect_weights_returns_none_when_column_absent`**
- Scoring file without `effect_weight` column.
- Assert function returns `None` (not an empty dict, not an error).

**`test_parse_effect_weights_handles_gz_and_plain`**
- One gzipped, one plain-text fixture scoring file. Both parse to the same result dict.

**`test_compute_weighted_match_rate_basic`**
- Synthetic weight dict: variant A has `|β| = 1.0`, variant B has `|β| = 3.0`, variant C has `|β| = 1.0`.
- Match log: variant A `matched`, variant B `unmatched`, variant C `matched`.
- Expected `effect_weight_match_rate = (1.0 + 1.0) / (1.0 + 3.0 + 1.0) = 0.4`.
- Expected `match_rate = 2/3 ≈ 0.667`.
- Assert both values returned separately (raw match stats struct carries count-based match rate; new function returns only the weighted rate).

**`test_compute_weighted_match_rate_excludes_uncallable`**
- Same as above but variant C is in the `uncallable_sites` frozenset.
- Expected `effect_weight_match_rate = 1.0 / (1.0 + 3.0) = 0.25` (C excluded from denominator).
- Expected raw `match_rate = 1 / (1 + 1) = 0.5` (C excluded from both numerator and denominator in count sense too).
- This test enforces INV-C002: uncallable sites are excluded from BOTH axes.

**`test_compute_weighted_match_rate_returns_none_when_weights_none`**
- `weight_dict = None` → function returns `None`. No error.

**`test_compute_weighted_match_rate_zero_total_weight`**
- All variants have `|β| = 0.0`. Denominator is zero. Assert function returns `None` rather than dividing by zero.

#### `tests/unit/test_pgs_qc_effect_weight_axis.py`

**`test_classify_calibration_declines_on_effect_weight_axis_alone`**
- `match_rate = 0.85` (above clean floor for medium tier), `pgs_variant_count = 50_000` (medium tier).
- `effect_weight_match_rate = 0.55` (below medium-tier decline floor of 0.60).
- Assert result is `DECLINE` with `VARIANT_OVERLAP_INSUFFICIENT`.

**`test_classify_calibration_declines_on_count_axis_alone`**
- `match_rate = 0.55` (below medium-tier decline floor), `effect_weight_match_rate = 0.85`.
- Assert result is `DECLINE` with `VARIANT_OVERLAP_INSUFFICIENT`.

**`test_classify_calibration_clean_when_both_axes_clean`**
- `match_rate = 0.85`, `effect_weight_match_rate = 0.85`. Medium tier.
- Assert result is `CLEAN`.

**`test_classify_calibration_warning_when_both_axes_in_warning_band`**
- `match_rate = 0.70`, `effect_weight_match_rate = 0.72`. Medium tier (warning band: 0.60–0.80).
- Assert result is `WARNING`.

**`test_classify_calibration_warning_when_one_axis_warning_other_clean`**
- `match_rate = 0.85` (clean), `effect_weight_match_rate = 0.70` (warning band). Medium tier.
- Assert result is `WARNING` (worst axis governs, but warning is not a decline).

**`test_classify_calibration_unchanged_when_effect_weight_match_rate_none`**
- `effect_weight_match_rate = None`. `match_rate = 0.55`. Medium tier.
- Assert result is `DECLINE` with `VARIANT_OVERLAP_INSUFFICIENT` (same as Phase 3a behavior with no new axis).

**`test_classify_calibration_INV_C001_decline_fires_on_either_axis`** (INV-C001 invariant test)
- Parametrized: for each tier in `{small, medium, large}`, for each of the three scenarios (count-axis decline, weight-axis decline, both-axis decline): assert `status == DECLINE`.
- Test name contains `INV-C001` so it appears in invariant sweeps.

#### `tests/integration/test_effect_weight_provenance.py`

**`test_effect_weight_match_rate_persisted_in_pgs_scores`**
- Full pipeline fixture: synthetic VCF + scoring file + pgsc_calc work-dir stub (matching log).
- After `stamp_pgs_row`, query `pgs_scores` from DuckDB; assert `effect_weight_match_rate` is a non-null float.

**`test_effect_weight_params_json_carries_scoring_file_provenance`** (INV-R001 provenance test)
- Same fixture. Assert `params_json` is parseable JSON containing `effect_weight_scoring_file_path` and `effect_weight_scoring_file_sha256`.

**`test_INV_C002_uncallable_sites_excluded_from_both_denominators`** (INV-C002 invariant test)
- Fixture with 3 variants; variant 3 is `uncallable` per `genotype_source` map.
- Assert: count of denominators in raw `MatchStats` excludes variant 3; `effect_weight_match_rate` denominator also excludes variant 3's weight.
- Test name contains `INV-C002`.

#### `tests/provenance/test_pgs_scores_schema_version_phase1.py`

**`test_pgs_scores_schema_version_bumped_after_phase1_migration`** (INV-R001 provenance test)
- Apply Phase 1 schema migration on a fresh store; query `schema_meta`; assert `schema_version` value matches the expected bumped version constant (to be determined once sibling plan schema version is known).

### Confirm tests fail

Run: `python -m pytest packages/toolkit/tests/unit/test_effect_weight_match.py packages/toolkit/tests/unit/test_pgs_qc_effect_weight_axis.py -v`

Expected failure reason: `parse_effect_weights` and the extended `classify_calibration` signature do not yet exist. Every test should fail with `ImportError` or `TypeError`, not with an unexpected exception.

---

## Step 1.2 — GREEN: minimal implementation

### Files to CREATE

None.

### Files to MODIFY

#### `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py`

1. Add `parse_effect_weights(scoring_file: Path, *, pgs_accession: str) -> dict[tuple[str, int, str, str], float] | None`.
   - Open the scoring file (gzip or plain text).
   - Locate `effect_weight` column in the header; if absent, return `None`.
   - Walk rows; for each, build key `(f"chr{hm_chr}", int(hm_pos), effect_allele, other_allele)` and value `abs(float(effect_weight))`.
   - Rows where `effect_weight` is empty or unparseable as float are silently skipped (consistent with `_extract_pgs_sites_from_scorefile`'s approach to bad rows).
   - Column-name variants to handle: `effect_weight` (primary), `weight` (fallback). Document in docstring.

2. Add `compute_weighted_match_rate(log_csv_gz: Path, *, pgs_accession: str, weight_dict: dict | None, uncallable_sites: frozenset[tuple[str, int]] | None = None) -> float | None`.
   - If `weight_dict` is `None`, return `None` immediately.
   - Walk the match log (streaming, reuse the existing gzip+DictReader pattern from `parse_match_stats`).
   - For each row matching `pgs_accession`: if `(chrom, pos)` is in `uncallable_sites`, skip. If in `weight_dict` and `match_status == matched`, add to `Σ|β|_matched`. Always add to `Σ|β|_total` (for matched + unmatched, after uncallable exclusion).
   - Return `Σ|β|_matched / Σ|β|_total` or `None` if total is zero.

#### `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py`

3. Extend `classify_calibration` signature:
   ```python
   def classify_calibration(
       *,
       match_rate: float,
       pgs_variant_count: int,
       effect_weight_match_rate: float | None = None,
   ) -> CalibrationDecision:
   ```
4. After computing `tier`, `clean_floor`, `decline_floor` from the count axis:
   - If `effect_weight_match_rate` is not `None`, apply the same threshold table to it.
   - Effective clean floor: `min(match_rate, effect_weight_match_rate) >= clean_floor` → CLEAN.
   - Effective decline floor: `min(match_rate, effect_weight_match_rate) < decline_floor` → DECLINE.
   - Warning band: otherwise.
   - The worst-of-two-axes logic is a `min()` call; no new control flow needed beyond the existing three-way conditional.
5. Update the docstring: remove the "Phase 3b will widen the signature" sentence; update the parameter list to include `effect_weight_match_rate`.

#### `packages/toolkit/src/genomeclaw_toolkit/prep/store.py`

6. Add `effect_weight_match_rate DOUBLE` to `_PGS_SCORES_DDL` after `decline_reason`.
7. Add the column to the programmatic column tuple/list used by any schema migration helper (if one exists; otherwise document the manual migration SQL).
8. Bump the schema version constant (exact value TBD).

#### `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py`

9. In `compute_pgs`, after calling `parse_match_stats`, also call `parse_effect_weights` and `compute_weighted_match_rate`.
10. Pass `effect_weight_match_rate` to `classify_calibration`.
11. Add `effect_weight_scoring_file_path`, `effect_weight_scoring_file_sha256`, `uncallable_sites_excluded_count` to the `params_json` dict built for `stamp_pgs_row`.
12. The `PgsRow` dataclass gains `effect_weight_match_rate: float | None = None` field.
13. `stamp_pgs_row` includes this field in the INSERT.

### Run tests green

`python -m pytest packages/toolkit/tests/unit/test_effect_weight_match.py packages/toolkit/tests/unit/test_pgs_qc_effect_weight_axis.py packages/toolkit/tests/integration/test_effect_weight_provenance.py packages/toolkit/tests/provenance/test_pgs_scores_schema_version_phase1.py -v`

All new tests must pass. All previously-passing toolkit tests must still pass:

`python -m pytest packages/toolkit/tests/ -v`

---

## Step 1.3 — REFACTOR

- Ensure `parse_effect_weights` and `compute_weighted_match_rate` have complete docstrings with `Args`, `Returns`, and a note on the `uncallable_sites` parameter's INV-C002 contract.
- Ensure the extended `classify_calibration` docstring explains the worst-of-two-axes semantics explicitly.
- Check type annotations are complete (`frozenset[tuple[str, int]] | None` is correct type for `uncallable_sites`).
- Remove any dead import or helper introduced during GREEN that is not covered by a test.
- Re-run the full test suite.

---

## Files

| Action | File | Notes |
|---|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py` | Add `parse_effect_weights` + `compute_weighted_match_rate` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py` | Extend `classify_calibration` signature |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | Add `effect_weight_match_rate` column to `_PGS_SCORES_DDL`; bump schema version |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | Wire new functions; add `effect_weight_match_rate` to `PgsRow`; update `stamp_pgs_row` |
| CREATE | `packages/toolkit/tests/unit/test_effect_weight_match.py` | Unit tests for new functions |
| CREATE | `packages/toolkit/tests/unit/test_pgs_qc_effect_weight_axis.py` | Unit tests for extended classifier |
| CREATE | `packages/toolkit/tests/integration/test_effect_weight_provenance.py` | Integration + provenance tests |
| CREATE | `packages/toolkit/tests/provenance/test_pgs_scores_schema_version_phase1.py` | Schema version provenance test |

---

## Verification

```bash
# Unit tests only (fast, first pass)
python -m pytest packages/toolkit/tests/unit/test_effect_weight_match.py \
  packages/toolkit/tests/unit/test_pgs_qc_effect_weight_axis.py -v

# Integration + provenance
python -m pytest packages/toolkit/tests/integration/test_effect_weight_provenance.py \
  packages/toolkit/tests/provenance/test_pgs_scores_schema_version_phase1.py -v

# Full suite (must be green before Phase 2 starts)
python -m pytest packages/toolkit/tests/ -v
```

---

## Completion criteria

- [ ] All Phase 1 tests pass (RED → GREEN → REFACTOR cycle visible in commits).
- [ ] INV-C001 invariant test (`test_classify_calibration_INV_C001_decline_fires_on_either_axis`) is green.
- [ ] INV-C002 invariant test (`test_INV_C002_uncallable_sites_excluded_from_both_denominators`) is green.
- [ ] INV-R001 provenance test (`test_effect_weight_params_json_carries_scoring_file_provenance`) is green.
- [ ] Full toolkit test suite is green with no regressions.
- [ ] `pgs_scores` schema version bumped in `store.py`; migration SQL documented in `work-notes.md`.
- [ ] `work-notes.md` updated with Phase 1 summary, decisions, and commit links.
- [ ] `development-plan.md` Phase overview table updated to show Phase 1 green.
- [ ] `phases/phase-2.md` exists before this phase is closed.

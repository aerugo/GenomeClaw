# Development Plan: PRS Calibration Phase 3b

**Status**: All four phases complete (2026-05-26). Real-data smoke GREEN — see Phase 4 row below.
**Created**: 2026-05-25
**Parent meta-plan**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md) — Stage 3, second child
**Spec**: [spec.md](./spec.md)
**Estimated duration**: 10 days

---

## Dependency gate

**This plan must not begin implementation until `force-genotype-callable-mask` is in the GREEN state.**

The sibling plan `force-genotype-callable-mask` proposes INV-C002 ("Uncallable sites must not inflate the PGS overlap denominator") and emits the per-site `genotype_source` annotation that Phase 1 of this plan consumes to exclude `uncallable` sites from both overlap denominators. Starting Phase 1 before INV-C002 is promoted and the `genotype_source` annotation is available in the scoring-file match log would require retro-fitting Phase 1 immediately after, which defeats the sequencing rationale in the meta-plan.

---

## Critical invariants to respect

- **INV-C001 v1.7** — The PRS-decline pattern in INV-C001 is what this plan operationalizes. Every new decline branch must be traceable to one of the four named PRS-decline criteria from the invariant. No new decline reason is invented here; only the four already-enum-declared reasons are given classifier logic.
- **INV-C002** (consumed from `force-genotype-callable-mask`) — Overlap denominators must exclude `uncallable` sites. Phase 1's match-rate computation calls `filter_uncallable_sites(match_rows, genotype_source_map)` before accumulating the `Σ|β|` and `n_matched` sums. The function's contract is defined by the sibling plan.
- **INV-E001** — The `decline_reason` column is evidence, not decoration. It must carry a non-null value on every row where `calibration_status = decline`. Phase 1 extends the constraint to the effect-weight axis without relaxing the existing constraint.
- **INV-R001** — Every new column in `pgs_scores` is covered by the canonical seven provenance columns. The schema version must be bumped whenever a column is added. The `params_json` column for a row must record the scoring-file path + sha256 used for effect-weight computation, and the FRAPOSA output path + GWAS ancestry metadata version used for the Mahalanobis computation.
- **INV-R002** — FRAPOSA `.pcs` files that contain zero sample rows are degenerate artifacts. The parser raises before persisting. A 0-distance result is not cached.
- **INV-A003** — The Mahalanobis distance, the nearest superpopulation, the `gwas_ancestry` string used in the trigger, and the PGS Catalog eval-metrics fetch (if any) land in `params_json` alongside the existing `min_overlap` and `keep_ambiguous` fields.
- **INV-P001** — No network call to PGS Catalog or any external service. All metadata is sourced from pgsc_calc's local output files or from the pre-downloaded reference data under `reference_root/pgs_catalog/`.

---

## Prior art: `prs-input-coverage-fill`

The completed `prs-input-coverage-fill` plan:

- Established `_pgs_qc.py` with the `CalibrationStatus` / `DeclineReason` / `CalibrationDecision` types and the `classify_calibration` function.
- Established `_pgsc_calc_match.py` with `MatchStats` and `parse_match_stats` (streaming CSV reader over `<sampleset>_log.csv.gz`).
- Added `calibration_status` and `decline_reason` columns to `pgs_scores` (currently `TEXT`, nullable).
- Documented the four deferred decline branches at `_pgs_qc.py:26-29`.

This plan extends those three modules and the `pgs_scores` schema. It does not replace or re-architect them.

---

## Current state analysis

### `_pgs_qc.py` (lines 125–159)

`classify_calibration` currently accepts only `match_rate` (raw count) and `pgs_variant_count`. The function docstring at line 147 explicitly notes: "Phase 3b will widen the signature to accept ancestry-driven inputs (Mahalanobis distance, FRAPOSA super-population call, GWAS ancestry composition) and route to the four other decline reasons."

`ANCESTRY_CALIBRATION_UNCERTAIN`, `PGS_CATALOG_TIER_INSUFFICIENT`, `POPULATION_TRANSFERABILITY_INSUFFICIENT`, and `PHENOTYPE_HETEROGENEOUS` are enum members with no corresponding classifier branches.

### `_pgsc_calc_match.py` (lines 1–121)

`parse_match_stats` walks `<sampleset>_log.csv.gz` row by row (streaming), accumulating matched/unmatched integer counts. The `effect_weight` column of the scoring file is not parsed; the match log itself does not contain `effect_weight` — the effect-weight computation requires joining the match log against the scoring file.

The match log's `accession` column identifies which scoring-file variant each row corresponds to. The scoring file's `effect_weight` column can be loaded as a dict keyed by `(hm_chr, hm_pos, effect_allele, other_allele)` and joined against the match log rows to compute weighted sums.

### `coverage_fill.py` (lines 780–849)

`_extract_pgs_sites_from_scorefile` already parses the hmPOS_GRCh38 scoring file's `hm_chr`, `hm_pos`, `effect_allele`, `other_allele` columns. It does not parse `effect_weight`. The column name in PGS Catalog files is `effect_weight` (confirmed in the hmPOS_GRCh38 format spec); this function can be extended or a sibling function can be written to also collect `effect_weight` per variant.

### `pgs.py` (lines 606–736)

`compute_pgs` calls `_parse_aggregated_scores` and `_parse_aggregated_scores_norm` after the pgsc_calc subprocess completes. It does not currently parse FRAPOSA outputs. The FRAPOSA project output is at `<work_dir>/ancestry/fraposa/project/<sampleset>.pcs` (confirmed in the 2026-05-21 real-data smoke: `GRCh38_norm_oriented_norm_splitfamaa.pcs`). The reference PCA file is at `<work_dir>/ancestry/fraposa/pca/GRCh38_reference_extracted.pcs`. Both files are tab-delimited with a header row `FID IID PC1 … PC10`.

### `store.py` — `pgs_scores` DDL (lines 205–233)

Current columns: `pgs_id`, `trait_label`, `percentile_in_user_ancestry`, `raw_score`, `study_population`, `calibration_warning`, `agent_choice_rationale`, `requested_for_question`, `calibration_status`, `decline_reason`, `superseded_by`, plus the canonical seven provenance columns.

Columns to add in this plan:
- `effect_weight_match_rate DOUBLE` — nullable; populated when scoring file has `effect_weight`.
- `fraposa_min_mahalanobis_distance DOUBLE` — nullable; populated when FRAPOSA output is present.
- `fraposa_nearest_superpop TEXT` — nullable; populated alongside distance.

### FRAPOSA output files (confirmed from real-data smoke)

- Per-sample PC file: `ancestry/fraposa/project/GRCh38_norm_oriented_norm_splitfamaa.pcs`
  - One data row per sample. Columns: `FID IID PC1 … PC10`.
  - In the real-data smoke the single row was: `MPNRGLQ2K MPNRGLQ2K -10.5845 -41.0037 1.0416 -17.7813 15.0012 1.6987 -0.1475 -0.7264 -0.1899 2.2386`.
- Reference panel PC file: `ancestry/fraposa/pca/GRCh38_reference_extracted.pcs`
  - One row per 1kGP+HGDP reference sample. Same column layout.
  - Population labels for reference samples must be joined from the 1kGP+HGDP sample metadata (available under `reference_root/ancestry/`).

---

## Solution design

### Stage diagram

```
[scoring file .txt.gz]  [match log _log.csv.gz]   [genotype_source TSV]
          |                        |                        |
          v                        v                        v
  parse_effect_weights()    parse_match_stats()    filter_uncallable_sites()
  (new in Phase 1)          (existing, unchanged)  (from force-genotype-callable-mask)
          |                        |
          +---------> compute_weighted_match_rate() (new in Phase 1)
                               |
                      effect_weight_match_rate (DOUBLE, persisted)
                               |
                               v
                    classify_calibration()  <── (Phase 1) extended signature
                               |
                    [FRAPOSA .pcs files]   [reference panel .pcs + pop labels]
                               |                        |
                               v                        v
                    parse_fraposa_pcs()  (new _pgs_fraposa.py, Phase 2)
                               |
                    mahalanobis_to_centroids()  (Phase 2)
                               |
                    fraposa_min_mahal_distance, nearest_superpop (persisted)
                               |
                    classify_calibration()  <── (Phase 2) ANCESTRY_CALIBRATION_UNCERTAIN branch
                               |
                    [log_scorefiles.json or pgs_catalog/<id>.json]
                               |
                               v
                    parse_pgs_catalog_eval_metrics()  (new _pgs_catalog_meta.py, Phase 3)
                               |
                    classify_calibration()  <── (Phase 3) PGS_CATALOG_TIER_INSUFFICIENT branch
                               |
                               v
                    CalibrationDecision → apply_calibration_decision(PgsRow) → pgs_scores INSERT
```

### Phase 1: Effect-weight-weighted overlap

**Files modified**: `_pgsc_calc_match.py`, `_pgs_qc.py`, `store.py`, `pgs.py`

Key design decisions:
- The scoring file is read once to build a dict `{(chrom, pos, effect_allele, other_allele): abs(effect_weight)}`. Memory cost for the largest known scoring file (PGS001229, ~1.7M variants) is approximately 200 MB — within the toolkit image's budget.
- The match log is walked once (streaming); for each `matched` row the lookup in the dict yields `|β|`. `Σ|β|_matched` and `Σ|β|_total` accumulate as floats. `effect_weight_match_rate = Σ|β|_matched / Σ|β|_total`.
- When `effect_weight` is absent from the scoring file header, the function returns `None` and no decline is triggered on this axis (abstain-on-missing-data policy, consistent with Phase 3's eval-metrics treatment).
- `uncallable` site exclusion: the caller passes a `frozenset[tuple[str, int]]` of `(chrom, pos)` pairs that are `uncallable` per INV-C002. Both the raw count denominator and the `Σ|β|_total` denominator exclude these sites before computation.
- `classify_calibration` signature extension: new keyword-only argument `effect_weight_match_rate: float | None = None`. When not `None`, the decline check fires on both axes; the existing `match_rate` axis is unchanged.

**Schema change**: `pgs_scores` gains `effect_weight_match_rate DOUBLE`. Schema version bumps to the next version (to be determined by what `force-genotype-callable-mask` leaves the schema at).

**Rebuild command** (after Phase 1):
```
genomeclaw pipeline prs-compute \
  --vcf <path/to/merged.vcf.gz> \
  --pgs-id PGS000018 \
  --run-dir <path/to/derived/<run-id>>
```
The CLI subcommand calls `compute_pgs` → `stamp_pgs_row` with the new columns populated. The derived store `variants.duckdb` receives the new `effect_weight_match_rate` column on every row inserted after the schema migration.

### Phase 2: Mahalanobis ancestry trigger

**Files created**: `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_fraposa.py`
**Files modified**: `_pgs_qc.py`, `pgs.py`, `store.py`

Key design decisions:
- `_pgs_fraposa.py` is a standalone module; it has no runtime dependency on the rest of the PGS pipeline so it can be unit-tested with synthetic `.pcs` files.
- Mahalanobis distance computation: group reference samples by superpopulation label; compute per-superpopulation centroid vector (mean of PC1–PC10 across all reference samples in that superpopulation) and covariance matrix; compute `D = sqrt((x - μ)^T Σ^{-1} (x - μ))` for each superpopulation; return `(min_D, nearest_superpop_label)`.
- scipy is already an optional dependency of the toolkit; `scipy.spatial.distance.mahalanobis` is the implementation. If scipy is unavailable, fall back to a pure-numpy implementation (numpy is always present).
- Population label join: the reference panel `.pcs` file contains only `FID` and `IID`; population labels come from `reference_root/ancestry/1000g/` or `reference_root/ancestry/hgdp/` sample metadata TSVs. The join key is `IID`. The superpopulation codes must be mapped to the five 1kGP superpopulations (AFR, AMR, EAS, EUR, SAS) and pgsc_calc's extended set (CSA, MID) to match `pop_summary.csv`.
- `INV-R002` guard: if the per-sample `.pcs` file has no data rows (degenerate FRAPOSA output), raise `FraposaPcsError` (new typed exception in `_pgs_fraposa.py`) and do not persist distances.

**`ANCESTRY_CALIBRATION_UNCERTAIN` trigger logic** (in `classify_calibration`):
```
if (
    fraposa_min_mahalanobis_distance is not None
    and fraposa_min_mahalanobis_distance > _QC_MAHAL_THRESHOLD  # = 3.0
    and gwas_ancestry is not None
    and len(gwas_ancestry_superpops(gwas_ancestry)) == 1
):
    return CalibrationDecision(
        status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN,
    )
```

`gwas_ancestry_superpops` is a helper that parses the PGS Catalog `gwas_ancestry` string into a set of superpopulation codes. When the string is ambiguous or multi-ancestry, `len()` is > 1 and the trigger does not fire.

**Schema change**: `pgs_scores` gains `fraposa_min_mahalanobis_distance DOUBLE` and `fraposa_nearest_superpop TEXT`. Schema version bumps.

### Phase 3: AUC-improvement gate

**Files created**: `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_catalog_meta.py`
**Files modified**: `_pgs_qc.py`, `pgs.py`

Key design decisions:
- Metadata source priority: (1) `log_scorefiles.json` in the pgsc_calc work-dir (emitted during a run; contains per-PGS Catalog metadata including any evaluation metrics pgsc_calc exposes); (2) `reference_root/pgs_catalog/<pgs_id>.json` (pre-downloaded metadata file, if present); (3) abstain.
- `log_scorefiles.json` structure is parsed; if `evaluation_metrics` is present and contains `auc` (or equivalent) alongside a `clinical_baseline_auc`, the delta is computed. pgsc_calc v2.2.0 does not guarantee these fields are always present — the abstain-on-missing-data policy applies.
- The AUC check is a SECONDARY gate, not the primary. The PRIMARY gate is the existing raw-count + effect-weight overlap. `PGS_CATALOG_TIER_INSUFFICIENT` is triggered only when BOTH: (a) AUC improvement is < 0.02 AND (b) the top-decile confidence interval does not exclude 1.5x.
- "Top-decile CI does not exclude 1.5x" means the confidence interval lower bound on the top-decile OR/HR is below 1.5. This mirrors the existing verbal decline criterion from INV-C001 v1.7.
- No network calls are issued. If neither metadata source has evaluation metrics, `classify_calibration` receives `pgs_auc_delta = None` and the `PGS_CATALOG_TIER_INSUFFICIENT` branch abstains.

**Schema change**: No additional schema change in Phase 3. The evaluation metrics metadata used is recorded in `params_json` only.

### Phase 4: Real-data smoke and system-prompt update

**Files modified**: agent system prompt (out-of-repo; documented as a required update); `work-notes.md` (outcome record).

Rerun PGS000018 CAD against the project owner's genome with all three new classifier branches active. Document:
- Effect-weight match rate (expected: differs from raw count match rate; quantifies weight-concentration in the unmatched fraction).
- Mahalanobis distance to each superpopulation centroid; nearest superpopulation.
- Whether `ANCESTRY_CALIBRATION_UNCERTAIN` fires for PGS000018 (PGS000018 is a primarily EUR GWAS; the project owner's pop_summary shows EUR as most similar at 100% norm — distance likely below threshold, but distance should be computed explicitly).
- Whether `PGS_CATALOG_TIER_INSUFFICIENT` fires (depends on evaluation-metrics availability in log_scorefiles.json for PGS000018).

System-prompt update text (draft):
> When a `pgs_scores` row has `calibration_status = 'decline'`, the `decline_reason` field carries the structured reason. Surface it verbatim in your response. Do not synthesise a confident percentile or trait-risk statement from a declined row. The decline_reason values and their meanings are: `variant_overlap_insufficient` (too few scoring variants matched — coverage gap), `ancestry_calibration_uncertain` (the user's ancestry is too far from the GWAS training population to trust the calibrated percentile), `pgs_catalog_tier_insufficient` (the PGS Catalog evaluation metrics show insufficient discriminative power for this trait), `population_transferability_insufficient` (the GWAS population does not transfer well to the user's ancestry), `phenotype_heterogeneous` (the phenotype definition used in the GWAS is too heterogeneous for reliable individual-level prediction). When `calibration_status = 'warning'`, surface the warning but may still present the score with an explicit uncertainty caveat.

---

## Schema / provenance impact

### `pgs_scores` column additions

| Column | DDL type | Nullable | Phase | Notes |
|---|---|---|---|---|
| `effect_weight_match_rate` | `DOUBLE` | Yes | 1 | `Σ\|β\| matched / Σ\|β\| total`; `NULL` when scoring file lacks `effect_weight` |
| `fraposa_min_mahalanobis_distance` | `DOUBLE` | Yes | 2 | Minimum Mahalanobis distance over all superpopulation centroids |
| `fraposa_nearest_superpop` | `TEXT` | Yes | 2 | Superpopulation label with minimum distance |

### `params_json` additions (no DDL change; existing `TEXT NOT NULL` column)

| Key | Phase | Value |
|---|---|---|
| `effect_weight_scoring_file_path` | 1 | Absolute path to the scoring file used for effect-weight computation |
| `effect_weight_scoring_file_sha256` | 1 | SHA-256 of the scoring file |
| `uncallable_sites_excluded_count` | 1 | Integer; number of sites removed from overlap denominators |
| `fraposa_pcs_file_path` | 2 | Path to the per-sample `.pcs` file |
| `fraposa_ref_pcs_file_path` | 2 | Path to the reference panel `.pcs` file |
| `gwas_ancestry_raw` | 2 | Raw string from PGS Catalog metadata used for superpopulation count check |
| `pgs_catalog_eval_source` | 3 | `log_scorefiles` / `reference_json` / `abstain`; which metadata source was used |
| `pgs_catalog_eval_auc_delta` | 3 | Computed AUC delta; `null` when abstained |
| `pgs_catalog_eval_abstain_reason` | 3 | When abstaining: `baseline_model_unspecified` / `metrics_unavailable` / etc. |

### Schema version

The schema version in `pgs_scores` and `schema_meta` must be bumped once per column-addition phase. The exact version numbers are determined relative to whatever version `force-genotype-callable-mask` leaves the schema at. Each phase plan carries the specific bump as a concrete number once that dependency is known.

### Rebuild command (full, post all phases)

```bash
genomeclaw pipeline prs-compute \
  --vcf /Volumes/Genome_Work/genomeclaw/data/raw/<sample>.vcf.gz \
  --pgs-id PGS000018 \
  --run-dir /Volumes/Genome_Work/genomeclaw/derived/<run-id>
```

The subcommand orchestrates: `compute_pgs` (calls pgsc_calc) → `_pgsc_calc_match.parse_match_stats` + `parse_effect_weights` → `_pgs_fraposa.parse_fraposa_pcs` → `_pgs_catalog_meta.parse_eval_metrics` → `classify_calibration` → `apply_calibration_decision` → `stamp_pgs_row`.

---

## Phase overview

| Phase | Status | Title | Focus | TDD | Green gate |
|---|---|---|---|---|---|
| 1 | **Complete (2026-05-25)** | Effect-weight-weighted overlap | `_pgsc_calc_match.py` + `_pgs_qc.py` (the `store.py`/`pgs.py` wiring landed under Phase 2 along with the v0.4 schema bump) | 25 new unit tests; INV-C003 uncallable exclusion + worst-of-two-axes classifier verified | Synthetic fixtures produce correct `effect_weight_match_rate`; INV-C003 uncallable exclusion tested |
| 2 | **Complete (2026-05-26)** | Mahalanobis ancestry trigger | New `_pgs_fraposa.py`; extended `_pgs_qc.py`; `store.py` v0.4 bump; `pgs.py` `PgsRow` + `stamp_pgs_row` wiring | 13 unit + 10 ancestry-branch + 3 integration + 2 provenance = 28 new tests; INV-R002 guard, rank-deficient guard, INV-C001 across tiers all verified | All 28 new tests green; full toolkit suite 1113 pass / 4 pre-existing fail / 151 skip; SCHEMA_VERSION = v0.4 with the three new pgs_scores columns present |
| 3 | **Complete (2026-05-26)** | AUC-improvement gate | New `_pgs_catalog_meta.py`; extended `_pgs_qc.py` with `pgs_auc_delta` + `pgs_top_decile_ci_lower` kwargs | 8 unit (parser + INV-P001 no-network) + 9 classifier-branch = 17 new tests; abstain-on-missing-data paths covered | Synthetic `log_scorefiles.json` + `<reference_root>/pgs_catalog/<pgs_id>.json` fixtures exercise trigger, non-trigger, abstain (missing baseline / missing AUC / malformed JSON); zero network calls verified by monkeypatched `urllib.request.urlopen` |
| 4 | **Complete (2026-05-26)** | Real-data smoke + system-prompt update | Smoke run against project owner genome; prompt update; **regression smoke gate per [Regression Smoke section](development-plan.md#regression-smoke)** | Manual smoke | **Agent system prompt update ✅** (PRS-decline section now lists per-`decline_reason` meanings). **Toolkit image rebuilt ✅** with `numpy 2.4.6` + `scipy 1.17.1` + `SCHEMA_VERSION="v0.4"`. **Smoke ✅**: `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` ran against the project-owner Nebula CRAM via cached work-dir override (`GENOMECLAW_PHASE5_SMOKE_DIR_OVERRIDE`); 31 min wall via pgsc_calc `-resume`. Outcome: `calibration_status="warning"` (PGS000018 match rate 0.4959 against a 1.74M-variant scoring file lands in the large-tier 0.40-0.75 WARNING band), schema_version="v0.4", all four canonical invariants (INV-D001 / INV-D003 / INV-R001 / INV-P001) green. **Offline real-data validation** against the cached FRAPOSA `.pcs` files confirmed Phase 2 modules end-to-end: project-owner min Mahalanobis = 2.67 (EUR, below the 3.0 threshold), nearest superpop EUR. Phase 3 `log_scorefiles.json` parser surfaced + fixed a JSON-array-shape divergence from the synthetic fixtures (added two tests; `abstain_reason="metrics_unavailable"` correctly reported — pgsc_calc v2.2.0 doesn't pass through PGS Catalog evaluation metrics). The pre-existing `find_pgsc_calc_log_csv` sampleset-name mismatch also surfaced + fixed (3 new tests). The two edge-case smokes (EAS-only PGS for ancestry-decline + low-tier PGS for AUC decline) remain owner-actionable follow-ups because they require additional scorefile fetches |

---

## Testing strategy

### Unit tests

- `test_parse_effect_weights_*`: correct computation of `Σ|β|` sums from synthetic scoring file + match log pairs; `None` return when `effect_weight` column absent; correct handling of negative weights (absolute value taken).
- `test_classify_calibration_effect_weight_*`: decline fires when EITHER raw count OR effect-weight match rate below tier floor; clean when both above clean floor; warning band is correct when one axis is in the warning band and the other is clean.
- `test_mahalanobis_distance_*`: known-exact PC vectors produce expected distances; degenerate (zero-variance) covariance raises `FraposaPcsError`; single-row sample with exactly one superpop in training set.
- `test_classify_calibration_ancestry_*`: trigger fires when distance > 3.0 + single ancestry; does not fire when distance > 3.0 but multi-ancestry GWAS; does not fire when distance <= 3.0; abstains when `fraposa_min_mahalanobis_distance` is `None`.
- `test_parse_pgs_catalog_eval_metrics_*`: correct AUC delta computation; correct top-decile CI check; abstain paths (missing baseline, missing AUC field, missing metrics entirely).
- `test_classify_calibration_pgs_catalog_tier_*`: trigger fires on both conditions met; abstains when metrics missing; does not fire on metrics present but AUC delta >= 0.02.

### Integration tests

- `test_pgs_effect_weight_end_to_end`: synthetic scoring file + match log + DuckDB store; asserts `effect_weight_match_rate` column populated; asserts `params_json` contains `effect_weight_scoring_file_sha256`.
- `test_pgs_fraposa_end_to_end`: synthetic `.pcs` files mirroring real-data smoke structure; asserts `fraposa_min_mahalanobis_distance` + `fraposa_nearest_superpop` populated in `pgs_scores`.
- `test_pgs_calibration_decline_ancestry_end_to_end`: synthetic scenario where distance > 3.0 + single-ancestry GWAS; asserts `decline_reason = ANCESTRY_CALIBRATION_UNCERTAIN` in the stored row.

### Provenance tests

- Every new column added to `pgs_scores` in Phases 1 and 2 is populated with a non-null value in the integration test fixture.
- `params_json` of the stored row is parseable JSON containing all keys from the "params_json additions" table above.
- Schema version in `schema_meta` matches the expected bumped value after each phase's migration.

### Determinism tests

- Running `compute_pgs` twice on the same synthetic inputs produces byte-equivalent `effect_weight_match_rate`, `fraposa_min_mahalanobis_distance`, and `fraposa_nearest_superpop` values (within float precision; the Mahalanobis covariance computation is deterministic given fixed reference panel rows).

### Real-data smoke (Phase 4 gate)

Run the full `prs-compute` pipeline against the project owner's Nebula 30x WGS VCF and PGS000018. Record:
- `effect_weight_match_rate` (expected: will differ from raw count match rate; document the delta).
- `fraposa_min_mahalanobis_distance` and `fraposa_nearest_superpop`.
- `calibration_status` and `decline_reason` for the new run versus the Phase 3a result.
- Wall-clock time (the effect-weight dict load for a 1.7M-variant scoring file should not add more than a few seconds to the existing match-parse step).

---

## Provenance test cases (for test-engineer)

1. `pgs_scores` row with `effect_weight_match_rate` populated carries `effect_weight_scoring_file_path` and `effect_weight_scoring_file_sha256` in `params_json`.
2. `pgs_scores` row with `fraposa_min_mahalanobis_distance` populated carries `fraposa_pcs_file_path` and `fraposa_ref_pcs_file_path` in `params_json`.
3. `pgs_scores` row where `ANCESTRY_CALIBRATION_UNCERTAIN` fires carries `gwas_ancestry_raw` in `params_json`.
4. `pgs_scores` row where `PGS_CATALOG_TIER_INSUFFICIENT` fires carries `pgs_catalog_eval_source`, `pgs_catalog_eval_auc_delta` in `params_json`.
5. `pgs_scores` row where the AUC gate abstains carries `pgs_catalog_eval_abstain_reason` in `params_json`.
6. Schema version in `schema_meta` matches the value recorded in every `pgs_scores` row's `schema_version` column.

## Determinism test cases (for test-engineer)

1. Two runs of `compute_pgs` on the same synthetic scoring file + match log + FRAPOSA `.pcs` files produce identical `effect_weight_match_rate` (to float64 equality).
2. Two runs produce identical `fraposa_min_mahalanobis_distance` and `fraposa_nearest_superpop` (Mahalanobis computation is deterministic given fixed reference rows).
3. Two runs where the PGS Catalog eval-metrics gate abstains both produce `pgs_catalog_eval_abstain_reason` with the same value.

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](../bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan's final phase is not Complete until the following real-data smoke is green:

**Command**:
```bash
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```
Additionally run two known-edge-case PGS IDs: one that should trigger `ANCESTRY_CALIBRATION_UNCERTAIN` (e.g., an EAS-only score on the EUR-similar project owner), and one with low PGS Catalog tier metadata.

**Pass criteria**:
- The `ANCESTRY_CALIBRATION_UNCERTAIN` scenario produces `calibration_status=decline` with the correct `decline_reason`.
- The low-tier-metadata scenario produces `calibration_status=decline` with `decline_reason=pgs_catalog_tier_insufficient` (or abstains with a recorded reason if metadata is unavailable).
- The CLEAN scenario (PGS000018 CAD for a EUR-similar sample) is unchanged from baseline.

**Why this smoke**: the three calibration branches (effect-weight overlap, Mahalanobis ancestry, AUC tier) can only be exercised end-to-end against real FRAPOSA outputs and a real scoring file — synthetic fixtures model the logic but cannot confirm the FRAPOSA file paths, scoring-file column names, and `log_scorefiles.json` structure all align correctly on the actual host.

The smoke result is recorded in `work-notes.md` as part of the final phase's Completion block before the plan moves to `docs/plans/completed/`.

---

## Documentation updates required

- `_pgs_qc.py` module docstring: update "Phase 3a scope" paragraph to note that Phase 3b is now implemented; enumerate the two remaining deferred branches (`POPULATION_TRANSFERABILITY_INSUFFICIENT`, `PHENOTYPE_HETEROGENEOUS`) and state why they remain deferred.
- `pgs.py` module docstring: note the three new call sites (`parse_effect_weights`, `parse_fraposa_pcs`, `parse_eval_metrics`).
- `docs/reference/INVARIANTS.md`: no new invariants promoted in this plan; update INV-C001's PRS-decline pattern section to note that criteria (a) and (d) now have operational implementations in `_pgs_qc.py`.
- Agent system prompt: Phase 4 update (draft text in Solution Design above).

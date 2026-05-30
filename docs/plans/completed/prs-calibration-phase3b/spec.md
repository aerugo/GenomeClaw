# Spec: PRS Calibration Phase 3b

**Status**: Drafted
**Created**: 2026-05-25
**Parent meta-plan**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md) — Stage 3
**Predecessor (prior art)**: `prs-input-coverage-fill` (completed) — Phase 3b was explicitly deferred from that plan at `_pgs_qc.py:26-29`
**Sibling dependency**: [`force-genotype-callable-mask`](../force-genotype-callable-mask/) — must reach GREEN before this plan starts implementation
**Estimated duration**: 10 days

---

## Goal

Implement the four ancestry- and metadata-driven decline classifier branches in `_pgs_qc.py` that were enum-declared but deferred in `prs-input-coverage-fill` Phase 3a, plus add effect-weight-weighted overlap as a parallel axis to the existing raw-count match-rate gate.

---

## Background

`prs-input-coverage-fill` Phase 3a implemented the `VARIANT_OVERLAP_INSUFFICIENT` classifier branch and stabilised the `DeclineReason` enum and `pgs_scores` schema so downstream consumers (agent HTTP layer, plugin TypeBox schemas) could be built against a stable shape. The module docstring at `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py:26-29` deferred the remaining four classifier branches:

> "Phase 3a scope: the variant-overlap axis (`VARIANT_OVERLAP_INSUFFICIENT`). The four ancestry- and metadata-driven decline reasons are enum-declared so the schema stabilises; classifier branches for them land in Phase 3b when FRAPOSA output + PGS Catalog metadata flow through."

A bioinformatics expert reviewed GenomeClaw on 2026-05-25 and raised three deeper calibration issues (items P1-5, P1-7, P1-8 from the triage):

**P1-5 — Effect-weight-weighted overlap.** The current `match_rate` is `matched / (matched + unmatched)` over raw variant count (implemented in `_pgsc_calc_match.py`). A PGS where 49% of variants are missing but those missing variants carry 80% of the total `|β|` magnitude is substantively worse than a PGS where 49% of uniform-weight variants are missing. pgsc_calc does not surface effect-weight overlap; it must be computed from the scoring file's `effect_weight` column against the per-variant match log.

**P1-7 — Mahalanobis ancestry calibration trigger.** `ANCESTRY_CALIBRATION_UNCERTAIN` is declared in `DeclineReason` but has no classifier branch. pgsc_calc's FRAPOSA step already emits per-sample top-10 PC coordinates into `ancestry/fraposa/project/<sampleset>.pcs` (confirmed present in the 2026-05-21 real-data smoke run). The reference panel PCs for 1kGP+HGDP samples are in `ancestry/fraposa/pca/GRCh38_reference_extracted.pcs`. These files are currently parsed only to extract the `pop_summary.csv` "Most similar population" label; the raw PC vectors are not persisted. The Mahalanobis distance to each superpopulation centroid is computable from these two files.

**P1-8 — AUC-improvement gate.** The existing decline criterion "top-decile RR < 1.5x" is the floor from the `INV-C001` v1.7 PRS-decline pattern. Wand et al. *Nature* 2021 (PRS-RS reporting standard) pairs this with AUC improvement > 0.02 over a clinical baseline. PGS Catalog provides evaluation metrics per PGS ID; the availability varies by scorefile. Where available, this should be consumed to strengthen `PGS_CATALOG_TIER_INSUFFICIENT` decisions.

The sibling plan `force-genotype-callable-mask` adds per-site `genotype_source ∈ {nebula_called, force_genotyped_high_conf, force_genotyped_low_conf, uncallable}`. Phase 1 of this plan must exclude `uncallable` sites from both the raw count and the effect-weight-weighted overlap denominators. This is the INV-C002 contract proposed by `force-genotype-callable-mask`.

---

## Classifier branches this plan implements

This plan implements exactly the following classifier branches that `_pgs_qc.py` declared but deferred:

1. **Effect-weight axis for `VARIANT_OVERLAP_INSUFFICIENT`** — parallel to the existing raw-count match-rate gate; a decline triggers if EITHER axis falls below the threshold for the variant-count tier.
2. **`ANCESTRY_CALIBRATION_UNCERTAIN`** — Mahalanobis distance > 3 in top-10-PC space from nearest 1kGP+HGDP superpopulation centroid AND the PGS was discovered in only one ancestry group.
3. **`PGS_CATALOG_TIER_INSUFFICIENT`** — AUC improvement over a clinical baseline < 0.02 (where evaluation metrics are available from PGS Catalog) AND top-decile HR/OR confidence intervals do not exclude 1.5x.

The two remaining declared `DeclineReason` values — `POPULATION_TRANSFERABILITY_INSUFFICIENT` and `PHENOTYPE_HETEROGENEOUS` — are **not implemented in this plan**. They require additional metadata sources (multi-ancestry GWAS composition tables, phenotype-code mapping to known heterogeneous disease definitions) that are not yet in the reference data layout. They remain enum-declared for schema stability and will be scoped in a future plan.

---

## Acceptance criteria

1. `_pgsc_calc_match.py` is extended to parse `effect_weight` from the scoring file and compute `effect_weight_match_rate = Σ|β| over matched / Σ|β| over all variants`.
2. `_pgs_qc.classify_calibration` accepts `effect_weight_match_rate` as an optional argument; when provided, decline triggers if EITHER `match_rate` OR `effect_weight_match_rate` is below the tier's decline floor.
3. `pgs_scores` carries a new column `effect_weight_match_rate DOUBLE` (nullable; populated when the scoring file provides `effect_weight`). Schema version is bumped.
4. A new module `_pgs_fraposa.py` parses FRAPOSA `project/<sampleset>.pcs` and `pca/GRCh38_reference_extracted.pcs`; computes per-sample Mahalanobis distance to each superpopulation centroid; returns the minimum distance and the nearest superpopulation label.
5. `compute_pgs` in `pgs.py` calls `_pgs_fraposa.parse_fraposa_pcs` if the FRAPOSA output directory is present; the distances are persisted in `pgs_scores` in two new columns: `fraposa_min_mahalanobis_distance DOUBLE` and `fraposa_nearest_superpop TEXT` (nullable). Schema version is bumped.
6. `classify_calibration` implements the `ANCESTRY_CALIBRATION_UNCERTAIN` branch: min Mahalanobis distance > 3.0 AND the PGS `gwas_ancestry` metadata field (passed by the caller) contains exactly one ancestry group → `DECLINE` with `ANCESTRY_CALIBRATION_UNCERTAIN`.
7. `classify_calibration` implements the `PGS_CATALOG_TIER_INSUFFICIENT` branch using PGS Catalog evaluation metrics (fetched via pgsc_calc's local metadata pass-through, not via network): AUC < baseline_auc + 0.02 AND top-decile OR/HR CI does not exclude 1.5x → `DECLINE` with `PGS_CATALOG_TIER_INSUFFICIENT`. When evaluation metrics are absent, the branch abstains (does not decline on missing data alone).
8. `uncallable` sites from `genotype_source` (INV-C002, from `force-genotype-callable-mask`) are excluded from both overlap denominators before the overlap rate is computed.
9. All new columns added to `pgs_scores` carry correct provenance (stamped via the existing `ProvenanceTag` mechanism per INV-R001).
10. A real-data smoke (Phase 4) documents the outcome of rerunning PGS000018 CAD with the new classifier.
11. The agent system prompt is updated: a row with `calibration_status=warning` or `calibration_status=decline` carries a structured `decline_reason`; the agent surfaces it verbatim and does not synthesize a confident answer when the row is declined.

---

## Applicable invariants

- **INV-C001 v1.7** — Research/lifestyle scope + PRS-decline pattern. The decline branches implemented here are the structural enforcement of the PRS-decline criteria enumerated in INV-C001's "PRS-decline pattern" subsection. Effect-weight overlap and AUC-improvement gate are the quantitative operationalization of criteria (a) and (d).
- **INV-C002** (proposed by `force-genotype-callable-mask`) — Uncallable sites must not inflate the PGS overlap denominator. This plan consumes `genotype_source=uncallable` exclusion from the sibling plan's output.
- **INV-E001** — Evidence traceability. The `decline_reason` column is evidence — it is the structural record of why a PRS finding was not surfaced. It must flow all the way to the agent via the HTTP boundary (that flow is the `agent-decline-taxonomy-exposure` plan's responsibility, already underway in Stage 1).
- **INV-R001** — Rebuildability. Every new column in `pgs_scores` carries the canonical seven provenance columns. Schema version bumps on every column addition. The scoring-file-derived `effect_weight_match_rate` records the scoring file path in `source_path` and its sha256 in `source_sha256`.
- **INV-R002** — Never cache a degenerate result. If the FRAPOSA `.pcs` file is present but contains zero sample rows (degenerate output), the parser raises a typed error rather than persisting 0.0 distances.
- **INV-A003** — Agent-curated compute provenance. The Mahalanobis distance, `fraposa_nearest_superpop`, and the `gwas_ancestry` metadata used to trigger or abstain on `ANCESTRY_CALIBRATION_UNCERTAIN` land in `params_json` of the `pgs_scores` row, not just as in-memory values.
- **INV-P001** — Privacy default. PGS Catalog evaluation metrics are consumed from pgsc_calc's local metadata pass-through (the `log_scorefiles.json` emitted during a run). No network call to the PGS Catalog API is introduced in Phase 3; a small offline fallback cache is used when the local metadata does not include evaluation metrics.

---

## Proposed new invariants

None proposed in this plan. The `INV-C002` proposed by `force-genotype-callable-mask` is consumed here but promoted there.

---

## Out of scope

- `POPULATION_TRANSFERABILITY_INSUFFICIENT` and `PHENOTYPE_HETEROGENEOUS` classifier implementation — deferred to a future plan pending reference data for multi-ancestry GWAS composition and phenotype heterogeneity mappings.
- Network calls to PGS Catalog REST API — out per INV-P001. The plan uses only locally-available metadata from pgsc_calc's output files.
- Cloud imputation to improve match rates — out per INV-P001.
- Modifying the effect-weight overlap threshold table — the existing variant-count-aware tier table from `_pgs_qc.py:18-24` applies to both axes.

---

## Privacy and safety considerations

- No genomic data leaves the local environment. FRAPOSA PC coordinates are derived from the user's VCF; they are computed host-side and persisted only to the local DuckDB store.
- The `fraposa_min_mahalanobis_distance` and `fraposa_nearest_superpop` columns in `pgs_scores` carry ancestry-related information. They must be treated as potentially identifying derived data and governed by the same local-only access rules as the rest of `pgs_scores`. They must not appear in the minimal-sufficient payloads exposed at the HTTP boundary unless the agent explicitly needs them to explain a decline (INV-P002 minimal-sufficient rule).
- PGS Catalog evaluation metrics are accessed from local files, not via an external API call. No user-identifying data is included in any metadata fetch.

---

## Open questions

- **Q1 (threshold for Mahalanobis distance).** The value 3.0 is a common sigma-equivalent used in multivariate outlier detection (Mahalnobis distance > 3 catches roughly the top 5% of a 10-dimensional normal). Is this the right threshold for the GWAS training-distribution question, or should it be calibrated against FRAPOSA's own published thresholds? Recommend resolving via the Phase 2 implementation after reviewing FRAPOSA documentation; the threshold is a `_QC_MAHAL_THRESHOLD` constant in `_pgs_qc.py` so it can be adjusted without changing call-site logic.
- **Q2 (GWAS ancestry metadata source).** The `gwas_ancestry` field needed for the Mahalanobis trigger is in PGS Catalog's metadata. pgsc_calc's `log_scorefiles.json` contains per-PGS metadata fields — confirm which fields are present. If `gwas_ancestry` is absent from `log_scorefiles.json`, fall back to the PGS Catalog API response file under `reference_root/pgs_catalog/<pgs_id>.json` (which the existing `_check_ancestry_reference` call confirms is present). Resolve during Phase 2 implementation.
- **Q3 (baseline AUC definition).** Wand et al. define "clinical baseline" variously as age+sex, age+sex+family history, or a clinical risk score (e.g., FRS for CAD). The PGS Catalog `evaluation_metrics` table may not always specify the baseline model. Proposed policy: when the baseline model is unspecified, abstain (do not decline on missing-baseline-definition alone) and record `pgs_catalog_eval_abstain_reason = "baseline_model_unspecified"` in `params_json`. Resolve during Phase 3 implementation.
- **Q4 (scoring file `effect_weight` availability).** Not all PGS Catalog scoring files include `effect_weight` (some provide only `effect_allele` + `weight` or use different column names). The parser must handle missing columns gracefully — return `None` for `effect_weight_match_rate` rather than crashing. Confirm column name variants in the Phase 1 implementation.

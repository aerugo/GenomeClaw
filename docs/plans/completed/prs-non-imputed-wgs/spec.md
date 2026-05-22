# Feature: PRS pipeline non-imputed single-sample WGS hardening

**Status**: Draft
**Created**: 2026-05-20
**Owner**: GenomeClaw engineering
**Related Plans**:
- Lineage (closed): [prs-input-coverage-fill](../../completed/prs-input-coverage-fill/), [prs-runtime-hardening](../../completed/prs-runtime-hardening/)
- Lineage (closed 2026-05-20): [pgs-allele-orientation](../../completed/pgs-allele-orientation/) — F7 fix; smoke ledger ends here
- Reports: [research brief](../../../reports/prs-real-data-smoke-research-brief.md) + [research findings](../../../reports/prs-real-data-smoke-research-findings.md)

---

## Goal

Make the PRS path produce a healthy `pgs_scores` row on a non-imputed single-sample WGS input by replacing input-class-inappropriate `pgsc_calc` defaults with empirically-validated defaults, decomposing multi-allelics upstream, and steering the agent toward HapMap3+ / C+T scorefiles for this input class.

## Background

After 21 real-data smoke iterations (v1–v21) the PRS pipeline reaches `pgsc_calc`'s MATCH_COMBINE stage on the project owner's Nebula 30× WGS + PGS000018 / PGS001229, but the run terminates because the empirical match rate (52.97% on smoke v21) is below `pgsc_calc`'s default `--min_overlap 0.75` gate. An external research validation pass (2026-05-20, [findings](../../../reports/prs-real-data-smoke-research-findings.md)) confirmed:

- The 45–65% match-rate ceiling is bioinformatically standard for non-imputed single-sample WGS against dense imputed PGS Catalog scoring files (e.g. PGS001229 — snpnet/LASSO).
- The 0.75 default was calibrated on cohort-imputed data by Lambert et al. 2024 (*Nature Genetics*).
- ~47% structural loss decomposes as ~15% ambiguous SNPs (correctly dropped by `--keep_ambiguous false`), ~10% multi-allelic / complex records, ~22% rare-variant / coverage-dropout sites.
- Comparable tools (PRSice-2, LDpred2, PLINK2 `--score`) are permissive on low-overlap inputs by default.

The wrapper is healthy; the defaults are wrong for the input class. This plan closes that gap.

## Acceptance Criteria

- [ ] AC1: `pgsc_calc` invocation passes `--min_overlap` sourced from a configurable parameter (default `0.5` for the current non-imputed single-sample WGS class); the value is persisted to `pgs_scores.params_json` per `INV-R001`.
- [ ] AC2: A pre-pgsc_calc normalization step decomposes multi-allelics via `bcftools norm -m -any -f <fasta>` upstream of the wrapper's input VCF (Tier-2-merged VCF or its caller); a regression test asserts the resulting VCF has no multi-allelic records.
- [ ] AC3: `--keep_ambiguous false` is documented as load-bearing (with a code comment + a test guard that fails if a future contributor flips it).
- [ ] AC4: Real-data smoke v22 against `MPNRGLQ2K.cram` + PGS000018 produces a non-empty `pgs_scores` row with non-null `percentile_in_user_ancestry` and `min_overlap_used: 0.5` in `params_json`.
- [ ] AC5: A docs/reference addition documents the HapMap3+ / C+T scorefile preference for non-imputed single-sample WGS; the agent system prompt's PRS-decline criteria gain a fifth named reason (only-imputation-dependent-scorefile-available for the trait) per `INV-C001` v1.7.
- [ ] AC6: `pgsc_calc` conventions dataclass (`_pgsc_calc_conventions.py`) gains a `min_overlap_default_for_non_imputed_wgs = 0.5` field with a citation to the research findings doc; the wrapper consumes the dataclass field, not a hardcoded literal (per `INV-T001`).

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the `bcftools norm` step writes to a derived path, never mutates the source VCF.
- **INV-P001** Privacy Is the Default Operating Mode — no new external egress. Cloud imputation services remain out; the `--min_overlap` lowering is a local-only configuration change.
- **INV-R001** Derived Stores Must Stay Rebuildable — `pgs_scores.params_json` records `min_overlap_used`, `keep_ambiguous_used`, and `norm_decompose_multi_allelics: true` so the row carries enough provenance to reproduce.
- **INV-R002** Never Cache a Degenerate Result — unchanged; the existing 0-record guard in `coverage_fill.py` still applies. The new "Not to be confused with" subsection of `INV-R002` (added 2026-05-20) is the doctrinal source for distinguishing degenerate caches from low-but-valid match rates.
- **INV-T001** External-Tool Conventions Captured as Typed Wrappers — `_pgsc_calc_conventions.py` gains the new field; per-flag value-type semantics already established in v1.14.
- **INV-A003** Agent-Curated Compute Provenance — the agent's `agent_choice_rationale` should note whether the picked scorefile is imputation-friendly (HapMap3+ / C+T) for the user's input class.
- **INV-C001 v1.7** PRS-decline pattern — gains a fifth named reason: only-imputation-dependent-scorefile-available for the trait.

## Proposed New Invariants

**None.** The findings are operational refinements to existing invariants. The "Not to be confused with" clarification added to `INV-R002` (2026-05-20) is in place; the new behavior fits cleanly within `INV-R001` (provenance) and `INV-T001` (wrapper conventions).

## Technical Requirements

### Source Data Inputs

- `data/raw/<sample>/<sample>.mm2.sortdup.bqsr.cram` (read-only).
- `data/reference/pgs_catalog/PGS<id>/` (the scorefile under test; currently PGS000018 for smoke validation).
- `data/reference/genome/GRCh38_no_alt.fa` + `.fai` (fasta for `bcftools norm`).

### Derived Outputs

- A new pre-pgsc_calc-normalized VCF: `derived/prs_coverage/<sample>/v1/normalized/tier_merged.norm.vcf.gz` (decomposed multi-allelics; bgzipped + tabix-indexed; cache key includes the input Tier-2 VCF hash + the bcftools pin from `_versions.py`).
- The `pgs_scores` row (existing schema) gains three keys inside `params_json`: `min_overlap_used`, `keep_ambiguous_used`, `norm_decompose_multi_allelics`.

### Schema / Migration Impact

- `pgs_scores.params_json` is already a free-form JSON column per `INV-R001`; no schema migration. The three new keys are additive.
- The Tier 2 QC json (`tier2.qc.json`) does NOT need a schema bump for this plan (the `bcftools norm` step writes its own QC counts to a sibling `norm.qc.json`; Tier 2 QC schema v2 stays).

### Pipeline / Workflow Impact

```
Existing:  scorefile → Tier 2 force-genotype → Tier 1 merge → pgsc_calc
New:       scorefile → Tier 2 force-genotype → Tier 1 merge → bcftools norm -m -any → pgsc_calc
                                                              ^^^^^^^^^^^^^^^^^^^^^
                                                              NEW STEP
```

- `bcftools norm -m -any -f <fasta>` decomposes multi-allelics into single ALT records; the output is bgzipped + tabix-indexed; cache key includes input hash + bcftools pin.
- The `pgsc_calc` argv now sources `--min_overlap` from `PgscCalcConventions.min_overlap_default_for_non_imputed_wgs` (default `0.5`) plus an env-var override `GENOMECLAW_PGSC_CALC_MIN_OVERLAP` for ad-hoc tuning.
- Idempotent: rerunning the pipeline against the same Tier-2 VCF + same bcftools pin reuses the normalized VCF cache.

### Agent / UX Impact

- The agent's `agent_choice_rationale` (per `INV-A003`) gains a "scorefile modelling method" sentence when picking between HapMap3+ / C+T and snpnet/LASSO scorefiles for the same trait. The agent system prompt is updated to surface the rubric.
- PRS-decline pattern in `INV-C001` v1.7 gains a fifth named reason (only-imputation-dependent-scorefile-available for the trait); the prompt-content gate test for the decline pattern updates to enumerate five reasons instead of four.

### External Dependencies

- `bcftools` pin in `_versions.py` (already present).
- PGS Catalog metadata API exposes `weight_type` per scorefile (already present; agent reads this at scorefile-selection time).
- No new external datasets.

## Privacy & Safety Considerations

- **Boundary scan**: no new egress; all changes are local-only.
- **Default-off remote calls**: unchanged.
- **Redaction surface**: unchanged.
- **Clinical escalation**: unchanged. PRS findings remain `clinical-non-actionable` per `INV-C001` v1.7; the only addition is the fifth decline-pattern reason. The agent still won't issue diagnostic / prescriptive guidance based on a PRS percentile.

## Out of Scope

- **Cloud imputation** (TOPMed, Sanger, Michigan) — explicitly out per `INV-P001`. The 22% rare-variant / coverage-dropout share that imputation would recover stays gone for the non-imputed input class.
- **Zero-dosage local imputation at high-confidence reference sites** — a future plan. The existing Tier 1 + Tier 2 force-genotyping already covers part of the gap; a fuller local-zero-dosage step is a meaningful follow-up but is not in this plan's scope.
- **Per-trait scorefile metadata curation** — the agent picks scorefiles per-question per `INV-A003`; this plan does not introduce a per-trait curated list of HapMap3+/C+T scorefiles. The agent's rubric (preference + decline-pattern fifth reason) is the curation surface.
- **CI gate that runs the real-data smoke** — covered by the prs-runtime-hardening follow-up; out of scope here.

## Dependencies

- [pgs-allele-orientation](../../completed/pgs-allele-orientation/) Phase 1 must be GREEN (closed 2026-05-20).
- `bcftools` pin must be at v1.18 or later (the `-m -any` decomposition behavior verified there).

## Open Questions

- [ ] Q1: Should `min_overlap_default_for_non_imputed_wgs = 0.5` be exposed as a CLI flag on `genomeclaw pipeline prs-compute`, or strictly via env var + the conventions dataclass? *Working assumption*: env var + dataclass for now; promote to CLI flag if the agent needs per-run override.
- [ ] Q2: Does `pgsc_calc`'s `MATCH_COMBINE` step report match-rate before-and-after `bcftools norm`? *Working assumption*: yes, but verify the smoke v22 log to confirm — useful for cite-back if the lift from norm is meaningful.
- [ ] Q3: Is there a clean way to detect "only an imputation-dependent scorefile is available for this trait" automatically from PGS Catalog metadata, or does this rely on the agent's reading of `weight_type`? *Working assumption*: agent reads `weight_type` from the catalog API and applies the rubric in its system prompt; no host-side detection.

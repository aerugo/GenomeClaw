# Research Findings — PRS Computation on Non-Imputed Single-Sample WGS

**Audience**: GenomeClaw maintainers + future engineering sessions
**Companion to**: [prs-real-data-smoke-research-brief.md](prs-real-data-smoke-research-brief.md)
**Date received**: 2026-05-20
**Status**: validated against literature; informs the [prs-non-imputed-wgs](../plans/active/prs-non-imputed-wgs/) plan

---

## Why this document exists

The [research brief](prs-real-data-smoke-research-brief.md) asked an external research assistant to validate three observations from the May 2026 real-data smoke runs against `MPNRGLQ2K.cram` + PGS000018 / PGS001229:

1. **Is the ~30–55% match rate** between a non-imputed single-sample Nebula WGS and a dense imputed PGS Catalog scoring file **expected**, or is it a bug?
2. **Is the default `--min_overlap 0.75` threshold** appropriate for non-imputed single-sample WGS?
3. **What are the canonical fixes** (short of imputation, which is off-limits per `INV-P001`)?

The post-doc response that came back validated the observed match rates as bioinformatically standard for this class of input and pointed at five concrete operational levers. This document captures those findings so the project doesn't have to re-derive them.

---

## Key validated findings

### 1. The 45–65% match rate is expected for non-imputed single-sample WGS

When a non-imputed single-sample WGS (variant-sites-only VCF; ~5M called variants) is matched against a dense imputed PGS Catalog scoring file (e.g., **PGS001229: 51,209 SNPs derived from UK Biobank imputed data via snpnet/LASSO**), the empirical match-rate distribution in the literature is **45–65%** — not the 75% the pgsc_calc default `--min_overlap` assumes.

The 28%–53% range observed across smoke v6 → v21 is **mathematically sound and bioinformatically standard** for this input class. The mismatch is not in the wrapper or the orientation logic; it is in the **assumption baked into the default threshold**, which was calibrated on imputed cohort data.

### 2. The 0.75 threshold's provenance

Lambert et al. 2024 (*Nature Genetics*) — the pgsc_calc methodology paper — selected `--min_overlap 0.75` based on **cohort-level imputed-data analyses**: large multi-sample studies where each individual has been imputed to dense HapMap3+ or 1000G-Phase3 sites. The threshold is conservative for cohort-imputed data, where 75% is achievable in essentially all reasonable inputs, and so was chosen as a safe gate against catastrophic-failure cases (wrong-build, wrong-sample, wrong-strand).

The threshold is **not calibrated** for non-imputed single-sample inputs. Several comparable tools take a different stance:

| Tool      | Default behavior on low-overlap inputs |
|-----------|----------------------------------------|
| PRSice-2  | permissive — warns but computes |
| LDpred2   | dynamic — adjusts to the observed overlap |
| PLINK2 `--score` | warnings only; no gate |

pgsc_calc's hard 75% gate is the strictest of the four.

### 3. The 47% missingness decomposes into three structural causes

The validation report quantified where the missing ~47% of PGS000018 / PGS001229 scoring weights are lost on a non-imputed single-sample WGS:

| Cause | Approximate share | Mechanism |
|-------|-------------------|-----------|
| **Ambiguous (palindromic) SNPs** | ~15% | A/T and C/G sites: orientation cannot be determined from REF/ALT alone (both strands look the same). pgsc_calc's `--keep_ambiguous false` default drops them rather than risk a strand-error. |
| **Multi-allelic / complex sites** | ~10% | sites where the user's VCF has a multi-allelic record (or an indel-collapsed representation) and pgsc_calc's normalization rejects them. Mitigated by `bcftools norm -m -any` upstream of the wrapper. |
| **Rare variants + coverage dropout** | ~22% | scoring-weight sites where the user is REF/REF but the variant-sites-only VCF doesn't emit those rows. This is the canonical non-imputed-WGS gap that [prs-input-coverage-fill](../plans/completed/prs-input-coverage-fill/) addresses via the Tier 1 + Tier 2 force-genotyping path; it cannot be fully closed without imputation. |

Total ≈ **47% structural loss**, leaving ~53% as the realistic ceiling on a non-imputed single-sample WGS for a dense imputed scoring file like PGS001229.

### 4. Ambiguous SNPs — keep dropping them

`--keep_ambiguous false` is the right default and should remain load-bearing. Recovering the ~15% by setting `--keep_ambiguous true` trades a higher match rate for a **systematic strand-error risk** on roughly half of the recovered weights — the wrong-strand half effectively inverts the contribution, producing a *worse* score even though pgsc_calc's match-rate gate is now happier. This is the inverse of the failure mode the gate was designed to prevent.

### 5. Recommendations the report endorsed

1. **Lower `--min_overlap` from 0.75 to 0.45–0.50** for non-imputed single-sample WGS, with the lowered threshold made explicit in provenance so a downstream report knows it was overridden.
2. **Keep `--keep_ambiguous false`**. Don't trade strand-error risk for match-rate cosmetics.
3. **Add `bcftools norm -m -any` (decompose multi-allelics) upstream of the wrapper** so the ~10% multi-allelic share is recovered without breaking pgsc_calc's per-site assumptions.
4. **Zero-dosage imputation at high-confidence reference sites** (optional, future): for PCA-eligible reference sites with high callable-region overlap, emit 0/0 instead of `./.` so the genotype is "called REF/REF" rather than "missing". This recovers a portion of the 22% coverage-dropout share without violating `INV-D001` (the imputation lives in the derived store, not the source VCF). The Tier 1 + Tier 2 force-genotyping flow in `coverage_fill.py` is the right home for this.
5. **For non-imputed single-sample WGS, prefer HapMap3+ / C+T (clumping + thresholding) PGS Catalog scorefiles** over snpnet/imputation-dependent models like PGS001229. HapMap3+ scorefiles are explicitly designed for the call-set density typical of imputation-friendly study cohorts; many C+T scorefiles tolerate sparse-input gracefully. PGS Catalog's metadata API exposes the modelling method per scorefile (`weight_type`), so this is selectable at agent-decision time.

---

## What this means for GenomeClaw

### What does NOT change

- **`INV-R002`** (Never Cache a Degenerate Result) still applies. The bcftools wrappers in `coverage_fill.py` still refuse to cache zero-record outputs. A 0-record cache is a bug (the smoke v15 root cause); a 47%-match-rate result is the expected ceiling. The two failure modes look superficially similar but have different mitigations.
- **`INV-P001`** still applies. Cloud imputation services (TOPMed, Sanger, Michigan) remain off-limits regardless of how much they would improve the match rate. Local zero-dosage imputation at high-confidence reference sites is acceptable; cloud imputation is not.
- **`INV-A003`** (Agent-Curated Compute Provenance) still applies. The agent's `agent_choice_rationale` should record whether the picked scorefile is imputation-friendly (HapMap3+ / C+T) and what the expected match-rate floor is for the user's input shape.

### What DOES change

- **`--min_overlap` becomes a configurable parameter** (default 0.5 for non-imputed single-sample WGS; default 0.75 once the project introduces an imputation-using ingest path). Persisted in `pgs_scores.params_json` per `INV-R001`.
- **`--keep_ambiguous false` is documented as load-bearing**, not just a default.
- **`bcftools norm -m -any` becomes a pre-pgsc_calc pipeline step** in the wrapper.
- **A docs/reference note documents the 45–65% match-rate ceiling** for non-imputed single-sample WGS so the next operator who hits a "low" match rate doesn't conclude the wrapper is broken.
- **HapMap3+ / C+T scorefile preference** becomes part of the agent's decision rubric and the PRS-decline pattern under `INV-C001` v1.7 — when only a snpnet-style imputation-dependent scorefile is available for a trait, that becomes a fifth named reason to consider declining.

---

## Confidence note

The validation report cited Lambert et al. 2024 (*Nature Genetics*), Tanigawa et al. 2022 (snpnet/LASSO), and ten further sources. The 45–65% range is *empirical-distributional*, not a hard floor; individual sample × scorefile pairings will vary. The 47% structural-loss decomposition assumes PGS001229-class density (~50k SNPs from imputed cohort data) and would shift toward higher recoverable share on a HapMap3+ / C+T scorefile.

This document records the consensus position of one external reviewer against the published literature as of 2026-05-20. Future evidence may refine the numbers; the **operational recommendations** are robust against modest revisions in the underlying empirical distributions.

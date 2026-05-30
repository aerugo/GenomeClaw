# Bioinformatics Review — Triage and Ways Forward

**Date**: 2026-05-25
**Source review**: [docs/reports/bioinformatics-review-2026-05-25.md](bioinformatics-review-2026-05-25.md) (the external scientific review, written without code access)
**Companion artefact**: [docs/reports/architecture-overview-for-bioinformaticians-2026-05-25.md](architecture-overview-for-bioinformaticians-2026-05-25.md) (the brief the reviewer was given)
**Purpose**: Verify each P0/P1/P2 finding against the actual code, separate real gaps from misreads, and propose phased plans for the items that warrant work.

---

## How to read this report

The reviewer was given an architecture overview but no source access — so several "issues" are misreads of the overview's wording rather than real code gaps. Each item below carries a **verdict**:

- **REAL** — the gap exists in code; worth a plan.
- **MISREAD** — the code already does the right thing; close the loop in docs only.
- **PARTIAL** — code does some of the right thing; scope a targeted plan.
- **POLICY** — not a code bug; a defensible policy choice we should make explicit.

Code citations point at the *current* implementation, not the overview's paraphrase.

---

## P0 — items the reviewer flagged as user-facing-result-changing

### P0-1 · VEP MANE pinning — recover MANE Plus Clinical (73 genes)

**Reviewer's claim**: System runs `--mane_select` only and discards alternative transcripts, silently missing pathogenic variants in the 73 MANE Plus Clinical genes (SLC25A3, REEP6, TCF3, etc.).

**Code check**: [packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py:138](../../packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py#L138) passes `--mane_select` only. No `--pick_order` override. `pick_canonical_entry` in [materialize.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py) ranks by `MANE_SELECT non-empty → CANONICAL=YES → first entry`.

**Verdict**: **REAL — but smaller blast radius than the reviewer implied.**

The reviewer asserted that pinning to MANE Select "discards alternative-transcript consequences." That is **not what our materialize step does** — all transcripts remain in the CSQ field; only the canonical-row selection prefers MANE Select. So pathogenic alternative-transcript variants are *present* in the variants table, just not the one chosen as "the" canonical row.

But the reviewer's deeper point still bites: a downstream consumer (the findings synthesizer, the agent's `genomeclaw_variant` lookup) that reads only the canonical row will miss the MANE Plus Clinical alternative in those 73 genes. The fix is two-part:

1. Add `--mane` (which flags both Select and Plus Clinical) to the VEP invocation.
2. Update `pick_canonical_entry` to prefer `MANE_PLUS_CLINICAL` as a tied-rank alternative to MANE Select when the alternative transcript carries a more severe consequence — or, more robustly, emit *both* rows when they disagree and let the findings synthesizer mark the variant as "transcript-discordant."

**Recommendation**: Phased plan. Phase 1: change VEP flag + add `mane_plus_clinical` to the canonical-pick rank. Phase 2: decide whether to emit dual rows on disagreement (probably yes — fits the "preserve provenance, surface uncertainty" principle).

### P0-2 · Cyrius no-call handling — never default to Normal Metabolizer

**Reviewer's claim**: If Cyrius emits `None`, the system might pass that to PharmCAT's outside-call TSV and PharmCAT may "silently fall through" to Normal Metabolizer.

**Code check**: [packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py:175-189](../../packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py#L175-L189) — `_parse_cyrius_json` raises `CyriusNoGenotypeError` on empty diplotype. [pharmcat.py:71-81](../../packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py#L71-L81) — `_write_outside_call_tsv` raises `ValueError` if the diplotype is empty.

**Verdict**: **MISREAD — the code is fail-fast, not fail-permissive.**

A Cyrius no-call terminates the wrapper before the outside-call TSV is written. PharmCAT never sees `None`. The user can never get a "Normal Metabolizer" recommendation from a Cyrius no-call because the upstream pipeline halts.

**However**, "fail-fast" is itself a UX problem: if Cyrius can't call CYP2D6 on a particular sample (sub-30× coverage, structural variant in the locus), the user currently gets *no CYP2D6 row at all* — instead of an explicit "indeterminate, do not use for codeine/tramadol decisions" finding.

**Recommendation**: Small plan. Convert `CyriusNoGenotypeError` from a hard halt into an explicit `findings` row with `category=clinical-actionable`, `gene_symbols=["CYP2D6"]`, `evidence_ref` pointing at Cyrius's logs, and a body saying "CYP2D6 could not be called from this sample's coverage at the CYP2D6 / CYP2D7 locus; do not interpret as Normal Metabolizer." This preserves the safety property the reviewer wanted (never default to NM) while producing a finding the agent can surface.

### P0-3 · Coverage BED needs `difficult_region` flags

**Reviewer's claim**: PMS2, SMN1, HBA1/HBA2, CYP21A2, GBA1, STRC, NCF1, NEB, HLA all have segmental duplications or pseudogenes where short-read coverage *looks fine* but variants are uncallable. Without explicit flags, a user gets falsely reassured.

**Code check**: [packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.provenance.json](../../packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.provenance.json) — the BED is BED4 (`chrom, start, end, GENE_exon_N`). No annotation column for difficulty. GBA1 is aliased but no special handling.

**Verdict**: **REAL.** The reviewer is right that mosdepth-derived `mean_depth + low_coverage_exons` over PMS2 exons 11–15 will read "fine" even though those exons are clinically uncallable from short-read WGS. This is a real false-reassurance vector.

**Recommendation**: Phased plan. Phase 1: extend the BED schema to BED5 with a `region_class ∈ {standard, difficult_pseudogene, difficult_segdup, requires_dedicated_caller}` column. Phase 2: enumerate the difficult-region gene set against GIAB's "challenging medically relevant genes" benchmark (Wagner et al. 2022). Phase 3: surface the flag in the agent's `genomeclaw_gene` tool response with explicit wording ("coverage adequate, but this region is technically uncallable by short-read WGS").

### P0-4 · "Uncallable" tier for REF/REF coverage-fill

**Reviewer's claim**: Tier-1/Tier-2 force-genotyping silently assumes "no ALT at adequate depth = REF/REF" — but in low-MQ regions, hard-masked regions, or regions filtered by Nebula's upstream pipeline, "no ALT" actually means "no information." Without a callable-regions mask intersect, some "REF/REF inferred" sites are unknown-genotype.

**Code check**: [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py:382](../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py#L382) — uses `bcftools mpileup --regions-file ... --min-BQ 20 --min-MQ 20` followed by `bcftools call --constrain-alleles`. The MQ/BQ filters do exclude low-quality bases, but no separate callable-regions mask (GIAB high-confidence, mosdepth-derived) is intersected.

**Verdict**: **PARTIAL.** The reviewer's *first* mechanism (low-MQ regions) is handled by `--min-MQ 20`. The *second* (hard-masked / N-regions) is implicitly handled because there are no reads there. The *third* (Nebula's upstream filtering) is real and uncovered: those sites get force-genotyped from the raw CRAM, which is actually a *feature* (we recover sites Nebula's variant-sites-only VCF dropped) — but only if the CRAM has coverage there.

The honest gap: we do not currently emit a per-site `genotype_source ∈ {nebula_called, force_genotyped_high_conf, force_genotyped_low_conf, uncallable}` annotation that distinguishes provenance of each REF/REF in the forced VCF. Downstream PGS scoring treats them all identically.

**Recommendation**: Targeted plan. Add a per-site provenance annotation in the forced-genotype output (using bcftools `INFO/CALL_SOURCE` or a sidecar TSV). Intersect with a GIAB high-confidence regions BED (downloadable, well-versioned). Sites force-genotyped outside high-confidence regions get marked `uncallable` rather than `REF/REF`. PGS scoring excludes `uncallable` sites from both numerator and denominator of overlap.

---

## P1 — should-fix before broad release

### P1-5 · Effect-weight-weighted overlap

**Code check**: [packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py) — match rate is raw `matched / total`. [packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py:18-24](../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py#L18-L24) shows the variant-count-aware threshold table (75/60/40% by ≤10K, ≤500K, >500K variant counts).

**Verdict**: **REAL — but already partly mitigated.** Our decline thresholds are variant-count-aware (more permissive on large scores), which is *better* than a flat 0.75. But the reviewer's deeper point holds: a 49% match where the missing 51% accounts for 80% of effect-weight magnitude is genuinely worse than a 49% match where missing variants are weight-distributed. pgsc_calc itself doesn't surface this — we'd need to compute it from the scoring file + per-variant match log.

**Recommendation**: Small plan. Compute `effect_weight_weighted_overlap = Σ|β| over matched / Σ|β| over all` from the scoring file and the per-variant match CSV. Add it as a column in the calibration decision and use it as an *additional* gate alongside count overlap (decline if either count or weight overlap is below threshold).

### P1-6 · Confirm `_hmPOS_GRCh38` harmonized files

**Code check**: [coverage_fill.py:780-849](../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py#L780-L849) parses scoring files using PGS Catalog's harmonized column names (`hm_chr`, `hm_pos`). [pgs.py:491](../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L491) shows pgsc_calc output uses the `_hmPOS_GRCh38` suffix.

**Verdict**: **MISREAD — already correct in practice, but undocumented.** We consume harmonized files in production but the wrapper's *input contract* is column-based, not filename-based. So it would silently accept a non-harmonized file with hand-renamed columns.

**Recommendation**: Tiny plan. Add filename pattern check (`*_hmPOS_GRCh38.txt[.gz]`) and document the requirement in [INVARIANTS.md](../reference/INVARIANTS.md). One PR, no architectural change.

### P1-7 · Quantitative ancestry-calibration trigger (Mahalanobis)

**Code check**: [_pgs_qc.py:28](../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py#L28) — `ANCESTRY_CALIBRATION_UNCERTAIN` is enum-declared but classifier logic is deferred to Phase 3b ("when FRAPOSA output + PGS Catalog metadata flow through").

**Verdict**: **REAL, planned, not implemented.** The reviewer's recommendation (Mahalanobis distance > 3 in top-10-PC space from nearest centroid) is a defensible quantitative trigger.

**Recommendation**: This is the already-scoped Phase 3b. Adopt the reviewer's Mahalanobis threshold as the concrete classifier. Pull FRAPOSA's per-PC scores from pgsc_calc's intermediate outputs (they're emitted but we don't currently persist them).

### P1-8 · Pair top-decile RR with AUC-improvement check

**Reviewer's claim**: RR < 1.5× is a defensible floor but absolute-risk uplift (or AUC improvement > 0.02 over a clinical baseline) is the PRS-RS reporting standard.

**Verdict**: **POLICY.** This is a `INV-C001` invariant change, not a code change to existing logic. The `PGS_CATALOG_TIER_INSUFFICIENT` decline reason is already enum-declared. We need to define what "insufficient tier" means quantitatively, using PGS Catalog metadata (`evaluation_metrics` table has per-PGS HR/OR + AUC fields).

**Recommendation**: Update `INV-C001` to require both RR ≥ 1.5× *and* AUC improvement ≥ 0.02 over the published clinical baseline (where available; decline when unavailable for high-stakes traits). Then implement in Phase 3b alongside Mahalanobis.

### P1-9 · Coverage panel expansion: ACMG SF v3.3, CPIC Level A, lifestyle anchors

**Code check**: provenance JSON pins **v3.2** (73 genes, not v3.3's 84). MC1R, LCT, HFE, FUT2 are not in the panel; APOE *is*.

**Verdict**: **REAL.** ACMG SF v3.3 (Lee et al. 2025) adds ABCD1, CYP27A1, PLN — these should be added. The reviewer's lifestyle-anchor list (MC1R, LCT/MCM6, HFE, FUT2) plus the PharmGKB VIP non-Level-A set (ABCB1, COMT, MTHFR, etc.) are reasonable additions for personal-genomics context.

**Recommendation**: Single rebuild plan. Bump panel to v2; bump version pin to ACMG SF v3.3; add the lifestyle and PharmGKB-VIP supplements as a separate provenance section. Combine with P0-3 (BED5 difficult-region column) — these are the same file.

### P1-10 · Expose `decline_reason` to the agent (CRITICAL)

**Code check**: `decline_reason` is persisted to the `pgs_scores` table ([store.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py), [_pgs_qc.py:46-66](../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py#L46-L66)). But **neither HTTP response model carries it**:

- [packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py:43-71](../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py#L43-L71) — `PgsRowResponse` has `calibration_warning: str | None` but no `decline_reason` field.
- [packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py:73-87](../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py#L73-L87) — `PgsListRow` same omission.

The Pydantic models use `extra="forbid"`, so even if the underlying DB row has `decline_reason`, the field is *stripped* at the HTTP boundary. The agent never sees the structured decline taxonomy — only the free-text `calibration_warning`.

**Verdict**: **REAL, and arguably worse than the reviewer suspected.** A declined PGS today returns with `calibration_warning` set to some text, but the agent has no machine-readable signal that "this was DECLINED for reason X" vs "this is CLEAN with a warning." The agent could easily synthesize a confident answer from a declined row.

**Recommendation**: Small plan, high priority. Add `decline_reason: DeclineReason | None` and `calibration_status: CalibrationStatus` to both `PgsRowResponse` and `PgsListRow`. Update the TypeBox schemas in [packages/nemoclaw-plugin/src/index.ts](../../packages/nemoclaw-plugin/src/index.ts) so the agent receives the structured fields. Add a system-prompt clause: "if `calibration_status=decline`, do not present this PGS as a finding — surface the decline reason instead."

This is also a candidate for an explicit `INV-A003` strengthening: decline reasons must traverse every layer of the agent-facing stack.

---

## P2 — nice-to-have

### P2-11 · LOFTEE filter reason preserved

**Code check**: [_csq.py:144](../../packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py#L144) maps `LoF_filter` → `loftee_filter`. **Already done.**

**Verdict**: **MISREAD.** Close as already-implemented.

### P2-12 · AlphaMissense `transcript_match=1` and version pinning

**Code check**: [annotate_vep.py:207-211](../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py#L207-L211) constructs the AlphaMissense plugin without `transcript_match=1`. Missing scores → `None` → DB NULL (no "benign" default).

**Verdict**: **PARTIAL.** The defaulting behaviour is correct (NULL, not benign). The `transcript_match` omission is worth investigating — the plugin documentation suggests this is the recommended setting when MANE Select is used. Also: we don't currently verify VEP-cache release vs AlphaMissense pre-compute release alignment at toolkit-build time.

**Recommendation**: Small plan: add `transcript_match=1`; add a `refs verify` subcommand that asserts VEP-cache Ensembl release matches the AlphaMissense file metadata header. One PR.

### P2-13 · UTF-8 invariant on PharmCAT outside-call TSV

**Code check**: [pharmcat.py:78-80](../../packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py#L78-L80) uses `Path.write_text(...)` with no explicit encoding. Python defaults to UTF-8 on Linux/macOS but not guaranteed.

**Verdict**: **REAL but trivially low-impact.** All our containers run UTF-8 locales. But the fix is one keyword argument.

**Recommendation**: One-line PR, no plan needed: `output_path.write_text(content, encoding="utf-8")`.

### P2-14 · Mitochondrial coverage QC

**Verdict**: **REAL.** MT-RNR1 is a CPIC actionable gene; we don't currently emit mitochondrial coverage in the QC panel.

**Recommendation**: Roll into the P1-9 panel rebuild.

---

## Items the reviewer raised that we should explicitly *not* act on

- **PGS ancestry: "continuous vs population-label"** — the reviewer asked us to prefer continuous Z-scores for admixed users. We currently emit `percentile_MostSimilarPop` from pgsc_calc, which is pop-specific. Continuous output requires additional pgsc_calc configuration and is genuinely uncertain for personal-genomics interpretation (a continuous Z across heterogeneous ancestries is hard to interpret without a baseline distribution choice). **Policy decision**: keep `MostSimilarPop` as the primary metric; let the ancestry-calibration decline gate (P1-7) handle the admixed-user case by declining when Mahalanobis distance exceeds threshold. We do not need both.
- **MAF threshold for palindromic SNP retention** — the reviewer agreed `--keep_ambiguous false` (drop all palindromic) is correct. Nothing to do.
- **`min_overlap 0.5` vs 0.75 default** — already configurable via env var; already paired with variant-count-aware decline thresholds. The reviewer's concern is real but already partly addressed by our threshold table; P1-5 (effect-weight overlap) closes the rest.

---

## Suggested phased plans (next step)

Group the real work into the following phased plans, in approximate priority order:

1. **Plan: VEP MANE Plus Clinical recovery** (P0-1). Two phases: flag change + canonical-pick update; dual-row emit on disagreement. Touches `INV-E001` (evidence linkage) lightly.
2. **Plan: agent-facing decline taxonomy** (P1-10). Add `decline_reason` + `calibration_status` to HTTP schemas, plugin TypeBox, and agent system prompt. Highest leverage for safety; smallest code change. **Recommend this first.**
3. **Plan: coverage panel v2 + difficult-region flags** (P0-3 + P1-9 + P2-14). Single panel rebuild covering BED5 schema, ACMG SF v3.3, lifestyle anchors, mitochondrial, and `requires_dedicated_caller` flags.
4. **Plan: CYP2D6 no-call as an explicit indeterminate finding** (P0-2). Convert hard-halt to a structured `findings` row.
5. **Plan: callable-regions intersect for force-genotyping** (P0-4). Add per-site `genotype_source` annotation; intersect with GIAB high-confidence BED; treat uncallable sites correctly in PGS overlap.
6. **Plan: effect-weight-weighted overlap + Phase 3b calibration classifier** (P1-5 + P1-7 + P1-8). Single plan because these all touch `_pgs_qc.py` and the calibration decision pipeline. Implements the deferred Phase 3b.
7. **Plan: small fixes** (P1-6 + P2-12 + P2-13). Filename pattern enforcement for `_hmPOS`, AlphaMissense `transcript_match=1` + version verify, UTF-8 explicit. Group as one PR each, no formal plan.

---

## Calibration of the reviewer

Worth noting for future external reviews: the reviewer was technically rigorous and their citations check out (ACMG SF v3.3 published 2025-07-09 with 84 genes; MANE v1.5 covers 73 Plus Clinical genes; Inouye et al. 2018 metaGRS_CAD HR 4.17). But they also extrapolated several issues from the architecture overview's wording that don't exist in code (Cyrius no-call, transcript discard). That's an expected hazard of code-blind review — we should give future reviewers either repo access or a more code-literal architecture description (the overview elides several implementation details that, in retrospect, were exactly the details the reviewer worried about).

For the items where the reviewer was right, they're *importantly* right — P0-3 (difficult regions), P1-10 (decline taxonomy exposure), and P0-1 (MANE Plus Clinical) are concrete safety improvements that would change user-facing outputs.

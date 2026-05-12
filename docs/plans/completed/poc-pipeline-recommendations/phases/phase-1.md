# Phase 1: MVP spec decision capture (Q5–Q10)

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land six new Decisions Taken in `docs/plans/active/mvp/spec.md` (Q5 through Q10), annotate Q1 as superseded by Q5, and rewrite the Acceptance Criteria, Technical Requirements, Privacy & Safety, and Out of Scope sections to reflect the six-tool plugin surface, the new pipeline steps (`bcftools stats`, `mosdepth`, VEP+plugins, `Cyrius`, `pgsc_calc`), and the curated-notes lifestyle reframe (gene shortlist, PER3/CLOCK/ACTN3 dropped). No reference doc edits in this phase; those land in Phase 2.

After Phase 1: `mvp/spec.md` is internally consistent against the recommendations report; subsequent phases of this plan can cite Q5–Q10 by ID and rely on the spec as the source of truth.

## Scope Boundaries

- **In scope**:
  - `docs/plans/active/mvp/spec.md` — six new Decisions Taken (Q5–Q10), Q1 superseded annotation, AC list rewrite, Technical Requirements update, Privacy & Safety update, Out of Scope update, Open Questions section preserved-and-empty.
  - `docs/plans/active/poc-pipeline-recommendations/work-notes.md` — Phase 1 progress block, doc-checks, sections touched, invariant-diff review.
- **Out of scope**:
  - `docs/reference/INVARIANTS.md` — Phase 2.
  - `docs/reference/architecture.md` — Phase 2.
  - `docs/reference/grand-plan.md` — Phase 3.
  - `docs/reference/user-stories.md` — Phase 3.
  - `docs/plans/active/mvp/development-plan.md` — Phase 4.
  - `docs/plans/active/mvp/phases/phase-1.md` — confirmed unchanged in Phase 4.
  - `docs/plans/active/mvp/phases/phase-2.md` — Phase 4.
  - Any plugin or toolkit code under `packages/`. **Strictly no code in this phase.**
  - Curated note files (`reference/curated_notes/<gene>.md`) — those land in MVP Phase 6.

## Invariants Enforced in This Phase

This phase edits one planning doc; the invariants it enforces are *propagated forward* by Q5–Q10 into every doc that Phases 2–4 will edit. Phase 1's role is to anchor the new decisions cleanly so later phases can cite them.

- **INV-C001** Separate Research Assistance from Clinical Advice — Q9 in the spec encodes the curated-notes lifestyle track and the gene shortlist (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR). PER3, CLOCK, ACTN3 are explicitly dropped from the lifestyle track in Out of Scope. This **strengthens** INV-C001's lifestyle-track recognition.
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — Q9 in the spec encodes `gene_note:<gene>` and `topic:hard-genes` as recognized evidence-reference forms. Lifestyle findings must cite a curated-note ref; the spec's AC list captures this.
- **INV-P002** Agent Egress Is a Named, Minimal-Sufficient Boundary — Q7 (gene tool) and Q8 (PRS tool) each encode `output_class: summary` defaults plus minimal-sufficient response shapes. The new endpoints (`/v1/gene/{symbol}`, `/v1/pgs/{trait}`) are named in Q7/Q8 and propagate into AC2 in the rewritten AC list.
- **INV-D001 / INV-D002** — Q6 (Cyrius) and Q7 (mosdepth) both call out that the new tools read source artifacts read-only and run host-side; Q5 (VEP stack) inherits the same discipline.
- **INV-R001** Rebuildability — Q5/Q6/Q7/Q8 all reference the seven canonical provenance columns; the new derived tables (`coverage_qc`, `pgs_scores`) inherit them.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Doc-Checks

This phase is doc-only; "tests" are structural doc-checks captured in `work-notes.md`. The checks must run RED before edits land — i.e., grepping the current `mvp/spec.md` should confirm that Q5–Q10 are *not* present, that Q1 lacks a "Superseded" annotation, that the AC list does not mention `genomeclaw_gene` or `genomeclaw_pgs`, etc.

**Doc-check cases**:

1. `check_q5_present` — `grep -E "^### Q5 " docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
2. `check_q6_present` — `grep -E "^### Q6 " docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
3. `check_q7_present` — `grep -E "^### Q7 " docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
4. `check_q8_present` — `grep -E "^### Q8 " docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
5. `check_q9_present` — `grep -E "^### Q9 " docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
6. `check_q10_present` — `grep -E "^### Q10 " docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
7. `check_q1_superseded_annotation` — `grep -E "Superseded by Q5 on 2026-05-08" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
8. `check_ac_list_mentions_genomeclaw_gene` — `grep "genomeclaw_gene" docs/plans/active/mvp/spec.md` should match in the Acceptance Criteria block (after edit). RED before edit: zero matches anywhere in spec.md.
9. `check_ac_list_mentions_genomeclaw_pgs` — `grep "genomeclaw_pgs" docs/plans/active/mvp/spec.md` should match in the Acceptance Criteria block (after edit). RED before edit: zero matches anywhere in spec.md.
10. `check_ac2_endpoint_list_includes_gene_endpoint` — `grep "/v1/gene/{symbol}" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
11. `check_ac2_endpoint_list_includes_pgs_endpoint` — `grep "/v1/pgs/{trait}" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
12. `check_out_of_scope_drops_per3_clock_actn3` — `grep -E "(PER3|CLOCK|ACTN3).*dropped" docs/plans/active/mvp/spec.md` should match (after edit) in the Out of Scope section. RED before edit: zero matches.
13. `check_external_deps_lists_vep_loftee_alphamissense_spliceai` — each of the four strings should appear in the Technical Requirements External Dependencies list (after edit). RED before edit: zero matches.
14. `check_external_deps_lists_cyrius` — `grep "Cyrius" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
15. `check_external_deps_lists_pgsc_calc` — `grep "pgsc_calc" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
16. `check_external_deps_lists_mosdepth` — `grep "mosdepth" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.
17. `check_q9_gene_shortlist_present` — each of `LCT`, `CYP1A2`, `ADORA2A`, `ALDH2`, `ADH1B`, `APOE`, `MTHFR` appears in Q9 (after edit). RED before edit: only `CYP1A2` is present (in Out of Scope's "MVP ships one lifestyle finding" line).
18. `check_lifestyle_curated_notes_path_named` — `grep "reference/curated_notes/" docs/plans/active/mvp/spec.md` should match (after edit). RED before edit: zero matches.

**Procedure**:

```bash
# RED — run from repo root, before any edit
for check in q5_present q6_present q7_present q8_present q9_present q10_present \
             q1_superseded_annotation \
             ac_list_mentions_genomeclaw_gene ac_list_mentions_genomeclaw_pgs \
             ac2_endpoint_list_includes_gene_endpoint ac2_endpoint_list_includes_pgs_endpoint \
             out_of_scope_drops_per3_clock_actn3 \
             external_deps_lists_vep_loftee_alphamissense_spliceai \
             external_deps_lists_cyrius external_deps_lists_pgsc_calc external_deps_lists_mosdepth \
             q9_gene_shortlist_present \
             lifestyle_curated_notes_path_named; do
  echo "=== $check ==="
done
# Run each grep individually; capture output in work-notes.md as the RED state.
```

After running the RED checks, paste the (negative-match) output into `work-notes.md` Phase 1 block.

### Step 1.2 — GREEN: Edit `mvp/spec.md`

Make the smallest set of edits to turn each doc-check GREEN.

**Edit 1: Annotate Q1 as superseded.**

Locate the existing Q1 block in [mvp/spec.md](../../mvp/spec.md) (heading `### Q1 — Annotator: SnpEff + SnpSift`). Insert a new line directly after `**Decided**: 2026-05-06.`:

```markdown
**Decided**: 2026-05-06.

**Superseded by Q5 on 2026-05-08.** SnpEff was chosen for setup-cost reasons; the [POC pipeline recommendations report](../work-notes.md#archive--source-recommendations-report) demonstrates that SnpEff's pathogenicity-call divergence from VEP is large enough to make clinical-track findings unsafe. The original Q1 rationale is preserved below for historical clarity; the new annotator stack is documented in Q5.

**Decision**: ship the MVP with **SnpEff + SnpSift** as the sole variant annotator. Effect predictions come from SnpEff; ...
```

(The rest of the Q1 block stays verbatim. Q1's Affected files line is left as-is — it's a record of what was planned at the time, not a current claim.)

**Edit 2: Append Q5 — Annotator stack revised to VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno.**

After the existing Q4 block, before the `## Open Questions` heading, insert a new horizontal rule and the Q5 block:

```markdown
---

### Q5 — Annotator stack: VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno (supersedes Q1)

**Decided**: 2026-05-08.

**Decision**: ship the MVP with **VEP** as the variant annotator, augmented with **LOFTEE** (predicted-LoF confidence filter), **AlphaMissense** (missense pathogenicity), and **SpliceAI** (splice-altering variant predictor). **MANE Select** is the default reporting transcript; HGVSc and HGVSp are emitted server-side, never constructed by the LLM. **vcfanno** stamps tabix-indexed annotations onto the VCF for ClinVar (latest release) and gnomAD v4 (with per-population AFs).

**Rationale**: independent benchmarks comparing SnpEff, VEP, and ANNOVAR on curated truth sets show LoF-prediction concordance falling to 65–44% when transcript sets differ between tools, and standardized testing finds SnpEff incorrectly downgrades ~67% of pathogenic/likely-pathogenic variants. For an agent that emits clinical-track findings with `clinical_escalation` markers, this rate of disagreement with the clinical-grade reference standard is unsafe (`INV-C001`). VEP + LOFTEE + AlphaMissense + SpliceAI is the smallest stack that closes the gap; vcfanno fills in ClinVar + gnomAD without requiring SnpSift's ad-hoc joins.

**Schema additions** (land in Phase 4): zygosity, depth (DP), allele balance, FILTER, ClinVar classification + review status, gnomAD popmax + per-ancestry AFs, gene LOEUF, MANE Select HGVSc and HGVSp, AlphaMissense score + class, SpliceAI max delta, LOFTEE high-confidence flag.

**Out of scope for Q5**: dbNSFP (REVEL/CADD/PrimateAI), MaxEntScan, UTRannotator, automated ACMG/AMP rule classifiers (InterVar, Genebe). These are deferred under Q10's defer-by-default discipline.

**Revisit when**:
- Phase 4 fixture timings on the project owner's VCF exceed the personal-host budget (~30 min/genome target). Mitigation candidate: drop AlphaMissense data files to a smaller subset, or pre-filter against gnomAD AF before running plugins.
- The agent flubs answers because MANE Select's transcript choice produces wrong-gene effects for a specific gene — would prompt review of transcript-pinning policy.
- A specific ClinVar / gnomAD field we need is inaccessible via vcfanno — would prompt a VEP plugin add.

**Affected files**:
- [development-plan.md](development-plan.md) Phase 4 — rewritten in Phase 4 of the [POC pipeline recommendations plan](../development-plan.md).
- [docs/reference/architecture.md](../../../reference/architecture.md) Component 1 description — updated in Phase 2 of the [POC pipeline recommendations plan](../development-plan.md).
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) Theme B + Decisions Taken — updated in Phase 3.
```

**Edit 3: Append Q6 — Cyrius for CYP2D6 outside-call into PharmCAT.**

```markdown
---

### Q6 — CYP2D6 outside-call via Cyrius into PharmCAT

**Decided**: 2026-05-08.

**Decision**: invoke **Cyrius** (Illumina) at ingest against the BAM/CRAM, produce a star-allele diplotype, and feed it into **PharmCAT's outside-call interface**. CYP2D6 is **not** called from the VCF (PharmCAT explicitly does not support this; the official documentation directs users to provide an outside-call diplotype).

**Rationale**: CYP2D6 metabolizes ~25% of clinically prescribed drugs (codeine, tramadol, oxycodone, tamoxifen, many antidepressants, antipsychotics). It is genetically complex (>130 star alleles, copy-number variation, hybrid alleles with the CYP2D7 pseudogene); standard small-variant callers fail at the locus because of 94% sequence homology with CYP2D7. Independent benchmarking on the GeT-RM truth set: Cyrius 96.5–99.3% overall concordance, vs. Aldy 86.8–92.2% and Stargazer 84.0%. Without Cyrius, the PGx track of the agent (`INV-C001` clinical-track) is unsafe for any CYP2D6-relevant prescription.

**Implementation cost**: one extra host-side container or Python tool; ~50 lines of glue to feed the diplotype into PharmCAT. Host-side only (`INV-D002`); BAM read-only (`INV-D001`); diplotype JSON lands under `derived/<run-id>/cyp2d6_diplotype.json` with the seven canonical provenance columns reflected in the manifest.

**Revisit when**:
- Cyrius's GeT-RM concordance drops in a future release (revisit tool choice; Aldy is the next candidate).
- A CYP2D6 hybrid allele observed in the user's BAM is not in Cyrius's call set (revisit; possibly run Aldy as a cross-check).

**Affected files**:
- [development-plan.md](development-plan.md) Phase 6 — updated in Phase 4.
- [docs/reference/architecture.md](../../../reference/architecture.md) Component 1 description, data layout — updated in Phase 2.
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) Theme G — updated in Phase 3.
- [docs/reference/user-stories.md](../../../reference/user-stories.md) Story 4 — updated in Phase 3.
```

**Edit 4: Append Q7 — Coverage-aware gene queries via mosdepth + new genomeclaw_gene tool.**

```markdown
---

### Q7 — Coverage-aware gene queries: mosdepth + genomeclaw_gene (5th tool)

**Decided**: 2026-05-08.

**Decision**: add **`mosdepth`** to the ingest pipeline; materialize a **`coverage_qc` table** in the derived store with per-gene mean coverage (and per-exon mean coverage for a curated set of clinically important genes). Add **`genomeclaw_gene`** to the plugin tool surface (5th tool; tool count 4 → 5). The host service exposes a new endpoint **`GET /v1/gene/{symbol}`** returning `{top_user_variants, gene_loeuf, omim_disease, omim_inheritance, mean_coverage, low_coverage_exons}`. `mean_coverage` is a scalar (number, scaled to 1× depth); `low_coverage_exons` is a list of exon IDs whose mean depth fell below a configurable threshold (default 10×).

**Rationale**: the most dangerous failure mode of a personal genomic agent is **false reassurance** — "you don't have a pathogenic *BRCA1* variant" when the relevant exon wasn't covered. Short-read 30× WGS systematically miscalls or misses variants in regions including PMS2, GBA, CYP21A2, SMN1, STRC, NCF1, HBA1/HBA2, IKBKG, CYP2D6, and the HLA region; even in well-behaved genes, individual exons can fall below confidence thresholds. The agent reads `mean_coverage` and `low_coverage_exons` and includes them naturally in negative answers, closing most of the false-reassurance failure mode at minimal cost.

**Tool shape** (TypeBox; reflects Q2 `registerTool` + Q4 typed-array conventions):
- `genomeclaw_gene` — `Type.Object({ gene: Type.String({ minLength: 1 }) })` (single-record lookup; scalar param).
- `output_class: summary` (`INV-P002` default; minimal-sufficient response shape enumerated above).

**Companion: `topic:hard-genes` evidence reference**. A markdown note `reference/curated_notes/topics/hard-genes.md` listing the systematically poorly-resolved genes with one-paragraph caveats. Resolved by `genomeclaw_evidence(ref="topic:hard-genes")`. The agent reaches for this when the gene is on the hard-genes list.

**Revisit when**:
- The user repeatedly asks coverage-related follow-ups that `mean_coverage` alone can't answer (revisit: per-exon coverage table, per-region mappability scores).
- A gene's coverage table is consistently misleading because of repetitive regions (revisit: report mappability alongside coverage).

**Affected files**:
- [development-plan.md](development-plan.md) Phase 5 — updated in Phase 4 (adds `genomeclaw_gene` deliverable).
- [phases/phase-2.md](phases/phase-2.md) — updated in Phase 4 (adds `mosdepth` deliverable + 3 test cases).
- [docs/reference/architecture.md](../../../reference/architecture.md) Component 2 endpoint list, plugin tool table, data layout — updated in Phase 2.
- [docs/reference/user-stories.md](../../../reference/user-stories.md) Story 3 — updated in Phase 3 (BRCA1 answer references coverage from `genomeclaw_gene`).
```

**Edit 5: Append Q8 — PRS panel via pgsc_calc + new genomeclaw_pgs tool.**

```markdown
---

### Q8 — PRS panel via pgsc_calc + genomeclaw_pgs (6th tool)

**Decided**: 2026-05-08.

**Decision**: add **`pgsc_calc`** (PGS Catalog Calculator, Nextflow) to compute polygenic risk scores for **three initial traits**: **coronary artery disease (CAD)**, **type 2 diabetes (T2D)**, and **breast cancer or prostate cancer** (project owner's choice; PRS313/BCAC for breast, PRS269 for prostate). All scores **ancestry-normalized** via `pgsc_calc --run_ancestry` (continuous-ancestry normalization against 1000G+HGDP; reporting raw percentiles without ancestry calibration produces systematically wrong numbers for non-European users). Materialize a **`pgs_scores` table** in the derived store. Add **`genomeclaw_pgs`** to the plugin tool surface (6th tool; tool count 5 → 6). The host service exposes a new endpoint **`GET /v1/pgs/{trait}`** returning `{percentile_in_user_ancestry, raw_score, source_pgs_id, study_population, calibration_warning}`.

**Rationale**: single-SNP findings cannot meaningfully answer common-disease risk questions; PRS can. `pgsc_calc` handles the canonical concerns (genome build liftovers, strand alignment, multi-allelic variant matching, continuous-ancestry normalization) and runs comfortably on a personal host (16 GB RAM, 2 CPUs on Linux). Three initial traits are chosen for maximum lifestyle-motivation value (CAD, T2D both well-established and lifestyle-modifiable) plus one user-interest trait (breast or prostate). The full panel of 8–10 traits is **deferred under Q10's defer-by-default discipline** — additional traits are a one-line config change in `pgsc_calc` when the user asks.

**Privacy**: `pgsc_calc` introduces a new **deliberate, host-side, opt-in** egress — fetching PGS scoring weights from the **PGS Catalog over HTTPS**. Same shape as the existing `genomeclaw-prep fetch --source clinvar` operation. **Genomic data does not traverse the boundary**; only PGS scoring weights flow inbound. (`INV-P001` preserved.)

**Findings classification**: PRS findings carry `category: clinical-non-actionable` (population-level percentile estimates, not pathogenic variant calls). They do **not** carry a `clinical_escalation` marker. The `calibration_warning` string makes ancestry-normalization explicit when the user's continuous-ancestry estimate falls in a region with sparse training data. (`INV-C001` preserved; not blurring research vs. clinical.)

**Tool shape**:
- `genomeclaw_pgs` — `Type.Object({ trait: Type.String({ minLength: 1 }) })` (scalar param; the trait list is small).
- `output_class: summary` (`INV-P002`); response includes the calibration warning structurally; never returns raw PGS variant lists.

**Revisit when**:
- The user asks about a trait not in the panel of three (one-line config add — defer-driven, not a redesign).
- The continuous-ancestry calibration produces a warning that's hard for the agent to communicate cleanly (revisit response shape).
- `pgsc_calc` resource budget exceeds the personal-host envelope for a specific trait (revisit panel size).

**Affected files**:
- [development-plan.md](development-plan.md) Phase 6 — updated in Phase 4 (adds `pgsc_calc` + `genomeclaw_pgs` + `pgs_scores` table deliverables).
- [docs/reference/architecture.md](../../../reference/architecture.md) Component 1, Component 2, Component 3 tool table, data layout, network topology — updated in Phase 2.
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) Theme G + Decisions Taken — updated in Phase 3.
- [docs/reference/user-stories.md](../../../reference/user-stories.md) — new short PRS story added in Phase 3.
```

**Edit 6: Append Q9 — Lifestyle calibration via curated_notes/.**

```markdown
---

### Q9 — Lifestyle calibration via reference/curated_notes/; gene shortlist (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR)

**Decided**: 2026-05-08.

**Decision**: lifestyle calibration is driven by a host-side **`reference/curated_notes/`** directory of one-markdown-file-per-gene curated notes, retrieved by the agent via **`genomeclaw_evidence(ref="gene_note:<gene>")`**. The structured `evidence_quality` field on lifestyle findings (per `INV-C001` v1.4) is **preserved** in the schema for future-proofing but is **not the primary calibration surface** — the agent composes lifestyle responses from the user's variant call plus the note's framing, in the user's voice.

**Initial gene shortlist** (seven notes plus one topic note in MVP Phase 6):
- **LCT/MCM6 rs4988235** (lactase persistence) — strong evidence; ancestry caveats.
- **CYP1A2 rs762551** (caffeine metabolism) — moderate evidence; don't dichotomize.
- **ADORA2A rs5751876** (caffeine sensitivity) — moderate evidence; modulated by habituation.
- **ALDH2 rs671** (alcohol flushing) — strong in East Asians; cancer-risk caveat.
- **ADH1B rs1229984** (alcohol metabolism) — strong; population frequency caveats.
- **APOE ε2/ε3/ε4** (rs429358 + rs7412) — strong (AD risk); the note IS the disclosure protocol.
- **MTHFR C677T (rs1801133), A1298C (rs1801131)** — skeptical framing; ACMG 2013 explicitly recommended against routine MTHFR testing.

Plus **`reference/curated_notes/topics/hard-genes.md`** (resolved by `topic:hard-genes`) for the systematic-blind-spot caveat (PMS2, GBA, etc.) — companion to Q7's coverage-aware gene tool.

**Genes dropped from the lifestyle track** (see Out of Scope below for the dropped-not-deferred listing):
- **PER3 VNTR / CLOCK** (chronotype) — repeated non-replication; VNTRs unreliably called from short-read 30× WGS.
- **ACTN3 R577X** (athletic performance) — elite-cohort effect doesn't transfer to recreational performance.

**Rationale**: structured `evidence_quality` taxonomies, mandatory effect-size schema fields, and pre-built phrasing templates are over-engineering for a single-user system. The user is the curator; the agent is the reader. Curated notes carry the user's voice and judgment; the agent's responses inherit calibration without the project having to maintain a taxonomy. The user can edit notes over time as their thinking evolves. This pattern is uniquely well-suited to single-user systems and uniquely poorly-suited to multi-user systems — lean into it.

**N-of-1 experiment framing**: defensible only for outcomes with within-individual variability and short washout windows (caffeine sleep latency, alcohol flushing, post-prandial glucose response). The agent's "try this for two weeks" suggestions are constrained accordingly; not used for training response, body composition, or long-horizon weight outcomes.

**`INV-C001` recognition**: INVARIANTS.md is bumped to v1.5 in Phase 2 of the [POC pipeline recommendations plan](../development-plan.md), with `reference/curated_notes/` added to INV-C001's "Where it applies". Editing a curated note is a user-facing-copy change, reviewed by the privacy-safety-reviewer agent before merge.

**Revisit when**:
- A new lifestyle gene meets the bar (strong evidence, well-replicated, individually-meaningful effect, callable on short-read 30× WGS) and the user wants to add it. Adding a note is a one-file change.
- Usage shows the structured `evidence_quality` field is genuinely needed for some surface (e.g., a future report generator) — promote it back to primary.
- The "every shipped lifestyle finding must have a corresponding curated note" rule earns its keep — promote to a candidate INV-C002 in a follow-up plan.

**Affected files**:
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) INV-C001 v1.5 — updated in Phase 2.
- [docs/reference/architecture.md](../../../reference/architecture.md) data layout, evidence resolver — updated in Phase 2.
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) Theme H — updated in Phase 3.
- [docs/reference/user-stories.md](../../../reference/user-stories.md) Story 9 — updated in Phase 3 (caffeine answer reads `gene_note:CYP1A2`; PER3/CLOCK follow-up gracefully declined).
- [development-plan.md](development-plan.md) Phase 6 — updated in Phase 4 (curated-notes evidence resolver deliverable).
```

**Edit 7: Append Q10 — Defer-by-default trigger list.**

```markdown
---

### Q10 — Defer-by-default scope discipline + trigger list

**Decided**: 2026-05-08.

**Decision**: adopt a **defer-by-default** scope discipline for the POC. Each deferred feature has a specific **trigger condition**; building until the trigger fires is the wrong call. The grand plan codifies this as a Strategic Constraint in Phase 3 of the [POC pipeline recommendations plan](../development-plan.md).

**Deferred features and their triggers**:

| Feature | Trigger |
|---|---|
| HLA typing (T1K) | User asks about abacavir (HLA-B*57:01), carbamazepine (HLA-B*15:02 / HLA-A*31:01), celiac (HLA-DQ2/DQ8), or ankylosing spondylitis (HLA-B*27). |
| Manta / structural-variant calling | User asks about a known familial deletion. (Honest answer often "request MLPA / clinical-grade testing" first.) |
| ExpansionHunter / repeat expansions | User asks about Huntington's, ALS/FTD (C9orf72), Friedreich's (FXN), spinocerebellar ataxias, or Fragile X. |
| mt-aware mtDNA caller (mity) | User asks an mtDNA-specific question. |
| Population-specific reference panels (SweGen, GenomeAsia, etc.) | Run somalier ancestry inference; if the user's ancestry concentrates in a public-panel population, add it. |
| Schema-enforced citation stripping | LLM observed hallucinating PMIDs in practice. |
| Tool-use forcing | LLM observed answering clinical / lifestyle questions from parametric memory without calling tools. |
| Deterministic server-rendered findings card | LLM observed dropping schema fields when summarizing into prose. |
| Phrasing templates for high-risk categories | A specific category of response repeatedly produces wrong framing. |
| Automated ACMG/AMP rule classifier (InterVar, Genebe) | The agent's natural ACMG composition produces wrong P/LP calls in observed conversations. |
| Eval harness with synthetic test cases | A regression breaks something twice. |
| Additional PRS traits beyond the initial 3 | User asks about a trait not yet in the panel. |
| Quarterly automated reanalysis | A ClinVar release lands that the user actually wants reprocessed. |
| OMIM, ClinGen Gene-Disease Validity, dbNSFP, MaxEntScan, UTRannotator vcfanno sources | The agent's responses visibly need richer evidence in a specific category. |

**Rationale**: building infrastructure for hypothetical needs ages poorly; each deferred feature is a one- to two-day add when the trigger fires; the bar should be observed need, not anticipated need. This applies equally to safety scaffolding (citation stripping, tool-use forcing) — modern frontier models with clear system prompts and structured tool returns produce reasonable, calibrated output on this stack, and the architectural mitigations are real safeguards for regulated products and adversarial users, neither of which applies here.

**Where this constraint lives**: a new Strategic Constraint **"Defer-by-default"** in [docs/reference/grand-plan.md](../../../reference/grand-plan.md), authored in Phase 3 of the [POC pipeline recommendations plan](../development-plan.md). The trigger table above is duplicated into grand-plan.md's Decisions Deferred table where the existing structure permits.

**Revisit when**:
- A deferred feature's trigger fires (move it to Decisions Taken; author a small plan).
- The defer policy itself proves wrong-headed — i.e., the project regularly catches up to features it should have built sooner. (Track this in `work-notes.md` of the relevant phase.)

**Affected files**:
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) Strategic Constraints + Decisions Deferred — updated in Phase 3.
```

**Edit 8: Rewrite Acceptance Criteria.**

The current AC list has AC1–AC7. After this phase, the spec's AC list reads (drop or rewrite each AC; keep AC numbering contiguous):

- **AC1**: (preserved verbatim) — `genomeclaw-prep ingest` produces a populated derived store. Update the cross-reference in the AC text to mention `coverage_qc` table population alongside the variants table.
- **AC2**: rewritten — endpoint list now reads `/v1/health`, `/v1/findings`, `/v1/findings/{id}`, `/v1/variants`, `/v1/variants/{key}`, `/v1/evidence/{ref}`, `/v1/provenance/{run-id}`, **`/v1/gene/{symbol}`**, **`/v1/pgs/{trait}`**. Per Q3 decision: still no `/v1/report` endpoint.
- **AC3**: rewritten — sandbox image registers **six** plugin tools (`genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, **`genomeclaw_gene`**, **`genomeclaw_pgs`**) and successfully reaches the host service via `host.openshell.internal`.
- **AC4**: preserved verbatim — clinical-track question with `clinical_escalation` markers.
- **AC5**: rewritten — lifestyle question references `genomeclaw_evidence(ref="gene_note:CYP1A2")`; agent composes direct guidance from the user's variant + the curated note's framing; no clinician-deferral default.
- **AC6**: preserved verbatim — default-config integration tests confirm no extra outbound calls.
- **AC7**: preserved verbatim — pipeline determinism.
- **AC8 (new)**: a fresh `genomeclaw-prep ingest` populates the **`coverage_qc` table** under `/mnt/genomeclaw/derived/<run-id>/` with at least one row per gene in the curated gene list (BRCA1, BRCA2, CYP2D6, etc.); `mean_depth` is a non-negative real with the seven canonical provenance columns populated.
- **AC9 (new)**: a `pgsc_calc` invocation populates the **`pgs_scores` table** with rows for the three initial traits (CAD, T2D, breast or prostate cancer); each row carries `percentile_in_user_ancestry`, `raw_score`, `source_pgs_id`, `study_population`, `calibration_warning`, and the seven canonical provenance columns.
- **AC10 (new)**: the host service evidence resolver accepts `gene_note:<gene>` and `topic:hard-genes` reference forms and returns the corresponding markdown content from `reference/curated_notes/`.
- **AC11 (new)**: a fresh ingest invokes **Cyrius** against the BAM/CRAM and writes the resulting CYP2D6 diplotype as `derived/<run-id>/cyp2d6_diplotype.json`; the diplotype is consumed by PharmCAT's outside-call interface in the `annotate` step.
- **AC12 (new)**: a fresh ingest invokes **`bcftools stats`** against the input VCF and writes the summary into `manifest.json` under `qc.bcftools_stats`; **`mosdepth`** is invoked against the BAM/CRAM read-only (BAM SHA256 unchanged post-run, `INV-D001`).

**Edit 9: Update Technical Requirements.**

- **Source Data Inputs** — add a bullet "BAM/CRAM (project-owner-provided; needed for `mosdepth` and Cyrius)"; add a bullet "PGS Catalog scoring weights (downloaded host-side by `pgsc_calc` on user invocation)".
- **Derived Outputs** — add `coverage_qc` table, `pgs_scores` table, `cyp2d6_diplotype.json` per run.
- **Schema / Migration Impact** — note that schema_version reserves `v0.2` for the additional columns and tables that Phase 4/6 will land.
- **Pipeline / Workflow Impact** — add `bcftools stats`, `mosdepth`, Cyrius, `pgsc_calc` invocations.
- **Agent / UX Impact** — tool count 4 → 6; lifestyle question handling reads from `gene_note:<gene>`.
- **External Dependencies** — VEP, LOFTEE, AlphaMissense, SpliceAI, vcfanno, Cyrius, `pgsc_calc`, `mosdepth` listed; SnpEff and SnpSift listed as **superseded by Q5** rather than deleted (they're not the default, but the host can have them installed for ad-hoc use).

**Edit 10: Update Privacy & Safety Considerations.**

Add bullets:
- **PGS Catalog fetch** is a deliberate host-side opt-in egress; same discipline as `genomeclaw-prep fetch --source clinvar`. Genomic data does not traverse this boundary.
- **Lifestyle finding partition** — `INV-C001` v1.5 (Phase 2 of this plan) recognizes `reference/curated_notes/` as the calibration surface for lifestyle findings; over-deferral and over-claim both fail snapshot tests.
- **PRS findings classification** — explicitly `clinical-non-actionable`; no `clinical_escalation` marker; calibration warning surfaced structurally for non-European-ancestry users.

**Edit 11: Update Out of Scope.**

Existing list preserved with one addition:
- The MVP ships **seven** lifestyle finding categories (per Q9): caffeine metabolism, caffeine sensitivity, lactase persistence, alcohol flushing, alcohol metabolism, APOE risk, MTHFR. **PER3, CLOCK, and ACTN3 are dropped from the lifestyle track entirely** (not deferred to a later horizon — they fail the curated-notes bar of "strong-enough evidence + reliable genotyping on short-read 30× WGS"; see Q9).

**Edit 12: Open Questions.**

Replace the existing Open Questions text with:

```markdown
## Open Questions

All MVP open questions are resolved as of 2026-05-08 (Q1–Q4 on 2026-05-06; Q5–Q10 on 2026-05-08). New design questions surfaced during implementation should land here as they appear, then move to Decisions Taken once resolved.
```

### Step 1.3 — REFACTOR

With the doc-checks GREEN:

- Read the entire Decisions Taken section end-to-end. Confirm Q1–Q10 read coherently in order; the Q1 "Superseded" annotation references Q5 correctly; cross-references between Q5/Q6/Q7/Q8/Q9/Q10 are accurate (e.g., Q7's "topic:hard-genes" reference is consistent with Q9's directory layout).
- Confirm the AC list flows: each AC maps to at least one of the new decisions; no AC is left over from the pre-Q5 design that is now meaningless.
- Confirm Out of Scope's "ships seven lifestyle categories" bullet is consistent with Q9's gene shortlist (count = 7 ✓).
- Confirm Technical Requirements External Dependencies list mentions every tool named in Q5–Q9.
- Confirm cross-references to Phase 2 of the [POC pipeline recommendations plan](../development-plan.md) are accurate (each Affected files block points at the right downstream phase).
- Re-run all doc-checks; capture GREEN output in `work-notes.md`.

---

## Implementation Details

### Editing approach

This is doc work. Use `Read` to inspect, then `Edit` to land the changes. Avoid a full file rewrite — the existing Q1–Q4 blocks, ACs, Technical Requirements, and Out of Scope sections are well-structured and should be preserved verbatim where the edit doesn't apply.

Suggested edit sequence (10 separate `Edit` calls, in order):

1. Q1 superseded annotation (one `Edit` to insert one paragraph).
2. Q5 block (one `Edit` to append before "Open Questions").
3. Q6, Q7, Q8, Q9, Q10 blocks (five `Edit` calls — one per Decision Taken).
4. AC list rewrite (one `Edit` per AC change; AC2, AC3, AC5 rewrites; AC8–AC12 additions).
5. Technical Requirements updates (one `Edit` per subsection).
6. Privacy & Safety updates (one `Edit` to append three bullets).
7. Out of Scope update (one `Edit` to append one bullet).
8. Open Questions rewrite (one `Edit`).

After each `Edit`, re-read the affected region to confirm the edit is internally clean (no broken markdown, no orphaned headings).

### Edge Cases to Handle

- **Q1 was originally written with affected-files links that point at downstream files (development-plan.md Phase 4, packages/nemoclaw-plugin/...).** Those links stay accurate as references to what *was planned* on 2026-05-06; do not rewrite them. The "Superseded by Q5" annotation is sufficient signal.
- **The existing Q4 block ends with a markdown horizontal rule (`---`).** The new Q5 block should start with its own horizontal rule + heading, matching the Q1–Q4 visual rhythm.
- **The existing Open Questions section is already minimal.** The Edit 12 rewrite should preserve the spirit (an empty section that says "all resolved as of <date>") but bump the date to 2026-05-08 and reference Q5–Q10.
- **AC rewrites should preserve the empty-checkbox prefix `- [ ] **AC<n>**:`.** The MVP spec's ACs are project-tracking checkboxes; Phase 1 of *this* plan does not check them off.

### Error Handling

- If an `Edit` fails because `old_string` is not unique, widen the context until it is. The MVP spec is well-structured; no edit should require `replace_all`.
- If a doc-check goes RED after an edit (i.e., a grep that should match doesn't), re-read the file and locate the missing string. Common cause: a markdown heading typo (`### Q5 —` vs `### Q5 -`).

### Privacy / Egress Notes

- This phase makes no runtime egress changes. It documents the PGS Catalog fetch in Q8 as a deliberate, host-side, opt-in egress that the MVP Phase 6 implementation will introduce.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/mvp/spec.md` | MODIFY | Q5–Q10 added; Q1 annotated superseded; AC list rewritten; Tech Req / Privacy / Out-of-Scope / Open Questions updated. |
| `docs/plans/active/poc-pipeline-recommendations/work-notes.md` | MODIFY (append) | Phase 1 progress block, doc-checks RED → GREEN, sections-touched summary, invariant-diff review. |
| `docs/plans/active/poc-pipeline-recommendations/phases/phase-2.md` | CREATE | At end of Phase 1, author Phase 2's detailed plan (Architecture + INVARIANTS) per the existing planning protocol. |

---

## Verification

This phase has no test runner; verification is a list of grep / regex / file-existence checks captured in `work-notes.md`.

```bash
# From repo root, after edits land

# Q5–Q10 presence
grep -E "^### Q5 " docs/plans/active/mvp/spec.md
grep -E "^### Q6 " docs/plans/active/mvp/spec.md
grep -E "^### Q7 " docs/plans/active/mvp/spec.md
grep -E "^### Q8 " docs/plans/active/mvp/spec.md
grep -E "^### Q9 " docs/plans/active/mvp/spec.md
grep -E "^### Q10 " docs/plans/active/mvp/spec.md

# Q1 superseded
grep -E "Superseded by Q5 on 2026-05-08" docs/plans/active/mvp/spec.md

# AC list shape
grep -E "genomeclaw_gene" docs/plans/active/mvp/spec.md
grep -E "genomeclaw_pgs" docs/plans/active/mvp/spec.md
grep -E "/v1/gene/\\{symbol\\}" docs/plans/active/mvp/spec.md
grep -E "/v1/pgs/\\{trait\\}" docs/plans/active/mvp/spec.md

# Out of Scope drops
grep -E "(PER3|CLOCK|ACTN3).*dropped" docs/plans/active/mvp/spec.md

# Tech Req external deps
for tool in VEP LOFTEE AlphaMissense SpliceAI vcfanno Cyrius pgsc_calc mosdepth; do
  echo "=== $tool ==="
  grep -c "$tool" docs/plans/active/mvp/spec.md
done

# Q9 gene shortlist coverage
for gene in LCT CYP1A2 ADORA2A ALDH2 ADH1B APOE MTHFR; do
  echo "=== $gene ==="
  grep -c "$gene" docs/plans/active/mvp/spec.md
done

# curated_notes path
grep -E "reference/curated_notes/" docs/plans/active/mvp/spec.md

# Tool count consistency: AC3 should mention exactly six tools
grep -E "(genomeclaw_status|genomeclaw_findings|genomeclaw_variant|genomeclaw_evidence|genomeclaw_gene|genomeclaw_pgs)" docs/plans/active/mvp/spec.md | wc -l
```

Expected: every grep above returns at least one match (after edits). Capture each command's output in `work-notes.md` Phase 1 block.

Final reading-test: re-read `mvp/spec.md` end-to-end and confirm:
- Decisions Taken section reads coherently in order Q1 (with Superseded annotation) → Q2 → Q3 → Q4 → Q5 → Q6 → Q7 → Q8 → Q9 → Q10.
- AC list maps cleanly to the decisions.
- Technical Requirements External Dependencies list is consistent with Q5/Q6/Q7/Q8.
- Out of Scope is consistent with Q9.
- Open Questions is empty (date stamped 2026-05-08).

---

## Completion Criteria

- [ ] All 18 doc-checks (Step 1.1) pass GREEN after edits.
- [ ] Final reading-test: `mvp/spec.md` reads coherently with Q1–Q10 in order.
- [ ] Tool count consistency: AC3 references all six tools, no more, no less.
- [ ] Q1 carries the "Superseded by Q5" annotation; original Q1 rationale preserved verbatim below.
- [ ] No reference doc (`docs/reference/*.md`) is touched in this phase.
- [ ] No code under `packages/` is touched in this phase.
- [ ] `work-notes.md` Phase 1 block captures: RED output (pre-edit grep failures), GREEN output (post-edit grep matches), sections touched, invariant-diff review confirming no canonical INV-xxx is weakened.
- [ ] Phase 1 status set to **Complete** in [development-plan.md](../development-plan.md) Progress Tracking table.
- [ ] [phases/phase-2.md](phase-2.md) of *this* plan is authored before Phase 1 closes (Architecture + INVARIANTS detailed plan).

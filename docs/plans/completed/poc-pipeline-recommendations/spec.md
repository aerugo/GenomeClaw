# Feature: POC Pipeline Recommendations — Plan & Reference Doc Alignment

**Status**: Complete
**Created**: 2026-05-08
**Completed**: 2026-05-08
**Owner**: project owner
**Related Plans**: [docs/plans/active/mvp/](../../active/mvp/) (this plan amended the MVP spec, development-plan, and phase-2 in place)

---

## Goal

Propagate the POC-stage pipeline recommendations (VEP-based annotation stack, Cyrius for CYP2D6, coverage-aware gene queries, PRS panel via `pgsc_calc`, curated-notes-driven lifestyle calibration, defer-by-default trigger list) into the spec, development-plan, phase-2, architecture, INVARIANTS, grand-plan, and user-stories documents — without writing implementation code, and without violating any canonical invariant in the process.

## Background

The MVP plan was authored on 2026-05-06 against an annotator decision (Q1: SnpEff + SnpSift) and a four-tool plugin surface (Q2/Q3) that, on review, expose the POC to two specific catastrophic-failure modes:

1. **LoF / pathogenicity mis-annotation.** Independent benchmarks show SnpEff's predicted-LoF concordance with VEP drops below 65% under different transcript sets, and curated truth-set studies find SnpEff incorrectly downgrades ~67% of pathogenic/likely-pathogenic variants. For an agent that emits clinical-track findings with `clinical_escalation` markers (`INV-C001`), this rate of disagreement with the clinical-grade reference standard is unsafe.
2. **CYP2D6 PGx gap.** PharmCAT explicitly does **not** call CYP2D6 from VCF; the official documentation directs users to provide an outside-call diplotype. The MVP currently has no such caller. Since CYP2D6 metabolizes ~25% of clinically prescribed drugs and is the most common follow-up topic to a clopidogrel/`CYP2C19` conversation (codeine, SSRIs, tamoxifen), shipping the PGx track without it is the same class of failure as #1 above.

In addition, three high-value-low-cost additions and one structural lifestyle reframe are surfaced by the recommendations report:

3. **Coverage-aware gene queries** — `mosdepth` at ingest plus a new `genomeclaw_gene` tool. Closes the most dangerous false-reassurance failure mode ("you don't have a pathogenic *BRCA1* variant" when the relevant exon wasn't covered).
4. **PRS via `pgsc_calc`** — three initial traits (CAD, T2D, breast-or-prostate). Existing single-SNP findings cannot meaningfully answer common-disease risk questions; PRS can. Ancestry-normalized via `pgsc_calc --run_ancestry`.
5. **Curated-notes lifestyle calibration** — a host-side `reference/curated_notes/` directory of one-markdown-per-gene notes, retrieved by the agent via `genomeclaw_evidence(ref="gene_note:<gene>")`. Replaces (does not remove) the structured `evidence_quality` taxonomy as the *primary* surface for lifestyle calibration, because for a single-user system the user-as-curator pattern beats taxonomy maintenance.
6. **Defer-by-default discipline** — explicit trigger list for HLA typing, SV calling, repeat expansions, mtDNA, population-specific reference panels, eval harness, additional PRS traits, citation-stripping, tool-use forcing, etc. Defer until the user's actual usage motivates each addition.

This plan is doc-only. It propagates these decisions across the planning artifacts so the next implementation phase (and the unauthored phase-3 through phase-7 detail plans) inherits them. No code lands as part of this plan.

## Acceptance Criteria

Each criterion is structurally testable: a small grep / regex / file-existence check, or a manual reading-test against a fixture diff.

- [ ] **AC1**: `docs/plans/active/mvp/spec.md` carries six new Decisions Taken — **Q5** (annotator stack revised; supersedes Q1), **Q6** (Cyrius for CYP2D6), **Q7** (coverage-aware gene tool), **Q8** (PRS panel + `genomeclaw_pgs`), **Q9** (curated-notes lifestyle reframe), **Q10** (defer-by-default trigger list). Q1 is annotated in-place with a `**Superseded by Q5 on 2026-05-08**` line; the original SnpEff rationale stays for historical clarity.
- [ ] **AC2**: `docs/plans/active/mvp/spec.md` Acceptance Criteria section is updated: AC3 names six tools (was four); a new AC names the `coverage_qc` table; a new AC names the PRS materialization; a new AC names the `curated_notes/` evidence path. Tool count 4 → 6 propagates.
- [ ] **AC3**: `docs/reference/INVARIANTS.md` `INV-C001` Requirements section names `reference/curated_notes/` as a recognized lifestyle-calibration surface alongside the structural `evidence_quality` field; "Where it applies" lists curated-notes editing as in-scope. INVARIANTS version bumps to v1.5; Last Updated set to 2026-05-08.
- [ ] **AC4**: `docs/reference/architecture.md` Component 1 lists `bcftools stats`, `mosdepth`, `Cyrius`, and `pgsc_calc` invocations within `genomeclaw-prep`'s subcommand surface. Component 2 lists `/v1/gene/{symbol}` and `/v1/pgs/{trait}` endpoints. Component 3's tool table lists exactly six tools. Layered diagram and data layout reflect `reference/curated_notes/`, `derived/<run-id>/coverage/`, `derived/<run-id>/pgs/`. Network topology section calls out PGS Catalog fetch as a deliberate host-side opt-in egress.
- [ ] **AC5**: `docs/reference/grand-plan.md` Theme B notes the VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno stack and adds a "False-reassurance prevention via coverage-aware queries" bullet. Theme G expands to PharmCAT + Cyrius outside-call + PRS panel via `pgsc_calc`. Theme H is reframed around `curated_notes/`; the gene shortlist is updated (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR); PER3, CLOCK, ACTN3 are dropped. Strategic Constraints gains a "Defer-by-default" entry. Decisions Taken / Deferred Decisions tables are refreshed.
- [ ] **AC6**: `docs/reference/user-stories.md` Story 1 ingest sketch includes the new pipeline steps; Story 3 (BRCA1) references coverage from `genomeclaw_gene`; Story 4 (clopidogrel) is extended with a CYP2D6/codeine sub-question demonstrating Cyrius output; Story 9 (caffeine) reads from `genomeclaw_evidence(ref="gene_note:CYP1A2")` and gracefully refuses the PER3/CLOCK question (those genes are out of the curated set); a new short story or sub-story exercises `genomeclaw_pgs` for CAD or T2D. Gap-analysis items A-anything-now-resolved are marked ✅.
- [ ] **AC7**: `docs/plans/active/mvp/development-plan.md` Phase Overview tool count is 6, not 4; Phase 4 deliverables name the VEP stack and the new schema columns; Phase 5 lists `genomeclaw_gene`; Phase 6 lists Cyrius, `pgsc_calc`, `genomeclaw_pgs`, and the `curated_notes/` evidence resolver. Schema/Provenance Impact section enumerates the new derived tables (`coverage_qc`, `pgs_scores`) and columns (MANE Select HGVSc/HGVSp, AlphaMissense score+class, SpliceAI max delta, LOFTEE flag, gnomAD per-population AFs, gene LOEUF). Privacy & Egress Impact section documents PGS Catalog fetch.
- [ ] **AC8**: `docs/plans/active/mvp/phases/phase-2.md` adds three new test cases — Ts/Tv sanity check from `bcftools stats`, per-gene coverage table populated by `mosdepth`, BAM/CRAM unchanged after `mosdepth` (`INV-D001`). Deliverables list updated; Files table updated.
- [ ] **AC9**: `docs/plans/active/mvp/phases/phase-1.md` is unchanged (foundations only). A one-line review note in this plan's `work-notes.md` confirms it was inspected and no edits required.
- [ ] **AC10**: No invariant in `docs/reference/INVARIANTS.md` is *weakened* by this plan. The plan either preserves or strengthens each. A pre-merge invariant-diff review (manual, captured in `work-notes.md`) confirms.
- [ ] **AC11**: This plan and its companion edits do not commit code. No file under `packages/toolkit/` or `packages/nemoclaw-plugin/` (except `package.json` if the manifest's tool list changes — which it should, post-Phase 2) is touched by this plan. (Plugin-side manifest edits are owned by MVP Phase 5; this plan only describes them.)
- [ ] **AC12**: Each phase of *this* plan ends with `work-notes.md` updated, listing the doc files changed, the lines/sections touched, and any open questions surfaced.

## Applicable Invariants

This plan is doc-only, but it is constrained by every canonical invariant because its job is to preserve them across substantial scope changes.

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the new `mosdepth` and `Cyrius` steps read BAM/CRAM and must not mutate them. The new `bcftools stats` step reads VCF and must not mutate it. The plan documents this constraint in the architecture and phase-2 deliverables; the MVP Phase 2 test set gains an `INV-D001` test for BAM-immutability post-`mosdepth`.
- **INV-D002** Raw Artifacts Host-Side Only — `Cyrius`, `mosdepth`, `pgsc_calc`, `bcftools stats` are all host-side tools. The plan documents this explicitly in the architecture; sandbox image content is not affected.
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — the new `gene_note:<gene>` and `topic:hard-genes` evidence references **are** evidence references; the host service evidence resolver must accept them. The architecture doc and the spec both name this. Findings derived from a curated note must cite `gene_note:<gene>` as their evidence reference; lifestyle findings without a curated-note ref are explicitly disallowed for the shipped gene set.
- **INV-P001** Privacy Is the Default Operating Mode — `pgsc_calc` introduces a new opt-in egress (PGS Catalog fetch). It is host-side, deliberate, on user invocation only — same shape as `genomeclaw-prep fetch --source clinvar`. The architecture doc adds a bullet to the network topology section; INV-P001 is preserved because the egress is deliberate, named, and not active by default.
- **INV-P002** Agent Egress Is a Named, Minimal-Sufficient Boundary — the two new plugin tools (`genomeclaw_gene`, `genomeclaw_pgs`) must default to `output_class: summary`. The new endpoints (`/v1/gene/{symbol}`, `/v1/pgs/{trait}`) must shape minimal-sufficient JSON. Coverage values are scalar; PRS percentile + raw score + source PGS ID + study population + calibration warning is the documented shape — no full PGS variant lists. The architecture doc encodes this.
- **INV-R001** Derived Stores Must Stay Rebuildable — the new derived tables (`coverage_qc`, `pgs_scores`) and the Cyrius diplotype output all require the seven canonical provenance columns. Phase 2 (mosdepth + bcftools stats) and the future Phase 6 (Cyrius + pgsc_calc) inherit the determinism + provenance test discipline already established in MVP Phase 2/3.
- **INV-C001** Separate Research Assistance from Clinical Advice — this plan **strengthens** INV-C001's lifestyle track by encoding `reference/curated_notes/` as the primary calibration surface, and by trimming the lifestyle gene set to the report's defensible shortlist (dropping PER3/CLOCK/ACTN3 because the evidence base is too thin or the genotyping is unreliable on short-read 30× WGS). The over-deferral failure mode named in `INV-C001` v1.4 is addressed: curated notes carry the user's calibrated voice, so the agent's lifestyle answers stay direct without bouncing every question to a clinician. INVARIANTS bumps to v1.5 to reflect the curated-notes recognition.

## Proposed New Invariants

**None.** This plan exercises and clarifies the existing seven canonical invariants; it does not promote a new one. The "defer-by-default" constraint added to `grand-plan.md` is a *strategic constraint*, not an invariant, because it is a posture about scope management rather than a rule about correctness or safety.

(If, during Phase 3, the curated-notes pattern motivates a structural rule — e.g., "every shipped lifestyle finding must have a corresponding curated note" — that would be a candidate for a new INV-C002. The decision lives in Phase 3's exit criteria and `work-notes.md`, not preemptively here.)

## Technical Requirements

### Source Data Inputs

- **Existing reference docs**: [docs/reference/grand-plan.md](../../../reference/grand-plan.md), [docs/reference/architecture.md](../../../reference/architecture.md), [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md), [docs/reference/user-stories.md](../../../reference/user-stories.md).
- **Existing planning docs**: [docs/plans/active/mvp/spec.md](../../active/mvp/spec.md), [docs/plans/active/mvp/development-plan.md](../../active/mvp/development-plan.md), [docs/plans/active/mvp/phases/phase-1.md](../../active/mvp/phases/phase-1.md), [docs/plans/active/mvp/phases/phase-2.md](../../active/mvp/phases/phase-2.md).
- **Source motivation**: the recommendations report (provided inline in the conversation that opened this plan; archived in this plan's `work-notes.md` for reproducibility).

### Derived Outputs

- **This plan's outputs are doc-deltas only.** Specifically:
  - 6 new Decisions Taken in `mvp/spec.md` plus AC list updates.
  - `INV-C001` Requirements + "Where it applies" bullets; INVARIANTS version bump to v1.5.
  - 4-block edit to `architecture.md` (components, endpoints, tool table, data layout, network topology).
  - 5-block edit to `grand-plan.md` (Themes B, G, H; Strategic Constraints; Decisions tables).
  - User-stories edits to Stories 1/3/4/9 plus a new short story for PRS; gap-analysis updates.
  - `mvp/development-plan.md` Phase Overview + Schema Impact + Privacy & Egress sections updated.
  - `mvp/phases/phase-2.md` deliverables + 3 new test cases + Files table.

### Schema / Migration Impact

- **No application schemas change in this plan.** The plan *describes* schema changes that the MVP Phase 4/6 implementations will land:
  - Variants table gains: MANE Select transcript pinning, HGVSc, HGVSp, AlphaMissense score + class, SpliceAI max delta score, LOFTEE high-confidence flag, gnomAD per-ancestry AFs, gene LOEUF.
  - New table `coverage_qc(gene TEXT, mean_depth REAL, ten_x_pct REAL, twenty_x_pct REAL, ...)` plus seven canonical provenance columns.
  - New table `pgs_scores(trait TEXT, raw_score REAL, percentile REAL, source_pgs_id TEXT, study_population TEXT, calibration_warning TEXT, ...)` plus seven canonical provenance columns.
  - New manifest fields capturing Cyrius diplotype call + tool version, `pgsc_calc` version + PGS IDs used.
- The MVP `schema_version` will move from `v0.1` (current draft) to `v0.2` to absorb these additions when Phase 4/6 lands. This plan reserves `v0.2` and notes the rationale; it does not bump the schema version document because no derived store has been written under `v0.1` yet (Phase 2 is still pending).

### Pipeline / Workflow Impact

- `genomeclaw-prep ingest` gains: `bcftools stats` (writes summary into `manifest.json`); `mosdepth` (writes per-gene mean coverage table into derived store).
- `genomeclaw-prep annotate` is rewritten around VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno (replacing the SnpEff + SnpSift pipeline named in MVP Q1).
- New phase-6-owned subcommands (described, not implemented here): a Cyrius caller step (BAM → diplotype JSON → PharmCAT outside-call) and a PRS step (`pgsc_calc` → `pgs_scores` table).

### Agent / UX Impact

- Plugin tool count grows from four to six: `genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, **`genomeclaw_gene`**, **`genomeclaw_pgs`**.
- `genomeclaw_evidence` evidence-resolver gains two non-variant-keyed reference forms: `gene_note:<gene>` (resolves to a curated markdown note) and `topic:hard-genes` (resolves to a curated caveat note about systematically poorly-resolved genes on short-read 30× WGS).
- Lifestyle question handling shifts: agent retrieves the relevant `gene_note:<gene>` and composes its response from the user's variant call + the note's framing, rather than a structured `evidence_quality` field driving prose. The structured field stays in the schema as a backstop for findings that don't have a curated note (none ship in v0; the field is populated for future-proofing only).
- Story 4 (PGx) gains a CYP2D6 sub-question demonstrating Cyrius output; the agent's response template for "should I worry about codeine / SSRIs / tamoxifen?" is bounded by the diplotype call + CPIC guideline reference.
- Story 9 (caffeine) gracefully declines a PER3/CLOCK follow-up because those genes are not in the curated set — the agent says so directly rather than making something up.

### External Dependencies

- **No new external dependencies are introduced *by this plan*.** The plan describes new external dependencies that the MVP Phase 4/6 implementations will introduce: VEP (Perl), LOFTEE (VEP plugin), AlphaMissense (data file + VEP plugin), SpliceAI (Python tool + data files), vcfanno (Go tool), Cyrius (Python tool), `pgsc_calc` (Nextflow pipeline), `mosdepth` (Rust tool). Each is a deliberate user-installed host-side tool. None enter the sandbox image (`INV-D002`).

## Privacy & Safety Considerations

- **Boundary scan**: this plan introduces no new runtime egress points (it's doc-only). It *describes* one new egress point — `pgsc_calc`'s fetch of PGS scoring files from the PGS Catalog over HTTPS, host-side, on deliberate user invocation only — same shape as `genomeclaw-prep fetch --source clinvar`. The architecture doc adds a bullet documenting this. Genomic data does not traverse the boundary; only PGS scoring weights flow inbound.
- **Default-off remote calls**: the PGS Catalog fetch is *not* automatic; it runs only when the user invokes a phase-6-owned subcommand explicitly. Same discipline as existing `fetch --source` operations.
- **Redaction surface**: not applicable — no new data egresses to the agent that wasn't already shaped by `INV-P002`. The two new plugin tools (`genomeclaw_gene`, `genomeclaw_pgs`) inherit `output_class: summary` and the architecture doc explicitly enumerates their minimal-sufficient response shapes (gene tool returns top variants + LOEUF + OMIM + coverage scalar; PGS tool returns percentile + raw score + source PGS ID + study population + calibration warning — never raw PGS variant lists).
- **Clinical escalation**: no new clinical-actionability surface. The Cyrius + PharmCAT outside-call combination produces PGx findings that flow through the existing `clinical-actionable` category and `clinical_escalation` marker pathway; the new PRS findings are explicitly **not** clinical-actionable (they are population-level percentile estimates, not pathogenic variant calls). The architecture doc and INV-C001 commentary clarify: PRS findings carry `category: clinical-non-actionable` plus a calibration-warning string; they do **not** carry a `clinical_escalation` marker.
- **Third-party data**: this plan does not change `INV-D001`/`INV-P001`'s third-party-data posture. The curated notes are about genes and population-level effects, not about third parties; the user is the curator and the user's record is the only thing the host service indexes.

## Out of Scope

Explicit boundaries — what this plan **does not** do.

- Implement any of the changes it describes. No code lands. No `packages/toolkit/` or `packages/nemoclaw-plugin/` source files are edited.
- Author `phases/phase-3.md` through `phases/phase-7.md` for the MVP plan. Per the existing planning protocol those are authored by their predecessor's exit gate; this plan ensures `development-plan.md`'s phase summaries carry enough delta context for the future authors.
- Bump `INVARIANTS.md` past `v1.5`. Substantive new invariants (e.g., a "every lifestyle finding must have a curated note" rule) belong in a separate plan if and when they're justified by usage.
- Edit the root [CLAUDE.md](../../../CLAUDE.md) or the `.claude/agents/*.md` agent guides. CLAUDE.md's invariants are pulled from INVARIANTS.md by reference; if a v1.5 INV-C001 update reshapes anything operative, it is propagated in a separate (small) plan.
- Curate the actual `curated_notes/` markdown files. This plan documents the directory's existence, naming convention, and reference-resolver path; the seven initial notes (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR) plus `hard-genes.md` are written in MVP Phase 6.
- Author or run any new tests. Phase-2.md's three new test cases are *described* by this plan; the tests are written when MVP Phase 2 is implemented.
- Bump or revisit MVP spec Q2 (`registerTool` API), Q3 (no `/v1/report`), or Q4 (typed-array params). Those decisions stand. Q5–Q10 are additive.

## Dependencies

- Acceptance of the recommendations report (the user's "Implement!" instruction in the conversation that opened this plan is the acceptance signal).
- The existing MVP spec, development-plan, phase-1, and phase-2 documents being current as of 2026-05-08 (verified at plan-start).
- No other active plans modifying the same files (verified — only `mvp` is active).

## Open Questions

All open questions were resolved via the recommendations report. New questions surfaced during plan execution should land in `work-notes.md` and propagate back into `mvp/spec.md`'s Decisions Taken / Open Questions sections in the appropriate phase.

(Reserving for surfaced-during-execution discoveries; this list will grow if Phase 1 or Phase 2 review surfaces a tension between the recommendations and an existing invariant.)

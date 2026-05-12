# POC Pipeline Recommendations — Work Notes

**Feature**: Propagate POC-stage pipeline recommendations across plan, spec, and reference docs (no code).
**Started**: 2026-05-08
**Branch**: `feature/poc-pipeline-recommendations` (target — not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom of the log. Each session opens with a context-review block before getting into the work.

### 2026-05-08 — Plan authoring session

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — confirmed all seven canonical invariants apply (D001/D002/E001/P001/P002/R001/C001); none weakened by this plan.
- Re-read [docs/reference/grand-plan.md](../../../reference/grand-plan.md) — Themes B, G, H, and Decisions tables identified as targets for Phase 3.
- Re-read [docs/reference/architecture.md](../../../reference/architecture.md) — four components, four tools, three egress paths; Phase 2 will modify all three.
- Re-read [docs/reference/user-stories.md](../../../reference/user-stories.md) — Stories 1/3/4/9 identified as targets; Story 9 has the most surgical change (curated-notes retrieval).
- Re-read [docs/plans/active/mvp/spec.md](../../active/mvp/spec.md) — Q1–Q4 Decisions Taken; AC list at AC1–AC7; tool count 4. Phase 1 of this plan adds Q5–Q10 and rewrites the AC list.
- Re-read [docs/plans/active/mvp/development-plan.md](../../active/mvp/development-plan.md) — 7 phases, ~80 tests; Phase 4 = annotation, Phase 5 = host service + plugin, Phase 6 = findings + evidence.
- Re-read [docs/plans/active/mvp/phases/phase-1.md](../../active/mvp/phases/phase-1.md) — foundations only; this plan does not touch it.
- Re-read [docs/plans/active/mvp/phases/phase-2.md](../../active/mvp/phases/phase-2.md) — 18 test cases; Phase 4 of this plan adds cases 19, 20, 21.
- Re-read [docs/plans/CLAUDE.md](../CLAUDE.md) — followed the planning protocol: spec, development-plan, work-notes, phase-1.md.

**Applicable Invariants** (this session):
- **INV-C001** — the lifestyle-track reframe (curated notes + dropping PER3/CLOCK/ACTN3) is the largest substantive change and the one most likely to ripple through every doc. Tracked carefully across spec, INVARIANTS, grand-plan, user-stories.
- **INV-E001** — the new `gene_note:<gene>` and `topic:hard-genes` evidence-reference forms must be recognized by the architecture's invariant-traceability table, the spec's Q9, and the agent's behavior in Story 9.
- **INV-P001 / INV-P002** — the PGS Catalog fetch is a new (described, not introduced) host-side opt-in egress; documented in architecture and grand-plan.

**Key Insights**:
- The recommendations report's two **non-negotiable** changes (VEP stack, Cyrius) and the four **high-value-low-cost** additions (coverage tool, PRS, curated notes, defer policy) cluster cleanly into doc edits across spec / architecture / grand-plan / user-stories / dev-plan / phase-2. No single edit is contentious; the plan's risk surface is doc-drift between phases, not the substance of the changes.
- Per-document-family phasing (one or two related docs per phase) beats per-topic phasing (annotator changes touching four docs in one phase). Reviewable diffs come from disciplined phase boundaries.
- Q1 (SnpEff) is annotated as superseded, not deleted. Decision evolution is part of the plan history; readers should see why Q1 was chosen, why it was replaced, and on what date.
- `phases/phase-3.md` through `phases/phase-7.md` of the MVP plan are *not* authored by this plan — they're authored at their predecessor's exit gate per the existing planning protocol. Phase 4 of this plan rewrites the MVP `development-plan.md` inline summaries thoroughly enough that future phase-N authors have full context.

**RED step output** (if applicable):
N/A — this plan is doc-only; "tests" are structural doc-checks captured per phase. The first phase's doc-checks land when Phase 1 begins.

**Completed Today**:
- [x] Created `docs/plans/active/poc-pipeline-recommendations/` directory and `phases/` subdirectory.
- [x] Authored `spec.md` (goal, background, AC1–AC12, applicable invariants, technical requirements, privacy & safety, out of scope).
- [x] Authored `development-plan.md` (4-phase per-document-family plan; Solution Design diagram; Schema, Privacy & Egress sections; Testing Strategy with doc-checks and cross-phase coherence checks).
- [x] Authored this `work-notes.md` (with archived recommendations report below).
- [x] Authored `phases/phase-1.md` (MVP spec decision capture; Q5–Q10 detailed templates; AC list rewrite plan; doc-checks).

**Decisions Made**:
- **Per-document-family phasing**, not per-topic. Rationale: smaller reviewable diffs; easier invariant-diff review per phase.
- **INVARIANTS bumps to v1.5**, not v2.0. Rationale: INV-C001 gains a clarifying recognition of `curated_notes/`; no invariant added or removed.
- **Q1 (SnpEff) annotated as superseded, not deleted**. Rationale: decision evolution is part of plan history; readers benefit from seeing why the change was made and when.
- **Recommendations report archived verbatim in this file** (see § Archive below). Rationale: future contributors should be able to see exactly what motivated the changes without depending on conversation transcripts.
- **No early authoring of MVP phase-3.md through phase-7.md**. Rationale: per the existing planning protocol those are authored at their predecessor's exit gate; preserves design flexibility.
- **README freshening is out of scope**. Rationale: this plan is scoped to plan/spec/reference doc alignment; README is a follow-up plan.

**Blockers / Issues**:
- None.

**Next Steps**:
1. Begin Phase 1 (MVP spec decision capture). RED: write the six doc-checks for Q5–Q10 presence; run grep against current `mvp/spec.md`; confirm absence (i.e., the decisions are not yet there). GREEN: edit `mvp/spec.md` to add the six decisions and rewrite the AC list. Refactor: confirm internal consistency.
2. End-of-Phase-1 update: append to this file's Phase Progress § Phase 1 block; author `phases/phase-2.md` of this plan.

---

## Phase Progress

### Phase 1: MVP spec decision capture
**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08

#### Doc-check Results

**RED state** (pre-edit, captured by `grep` against `docs/plans/active/mvp/spec.md`):

```text
Q5–Q10 presence:        all "(no match)"
Q1 superseded:          "(no match)"
genomeclaw_gene:        0
genomeclaw_pgs:         0
/v1/gene/{symbol}:      0
/v1/pgs/{trait}:        0
reference/curated_notes/: 0
LOFTEE / AlphaMissense / SpliceAI / Cyrius / pgsc_calc / mosdepth: 0 each
LCT / ALDH2 / ADH1B / APOE / MTHFR: 0 each
ADORA2A: 1 (in pre-existing context)
PER3/CLOCK/ACTN3 dropped: "(no match)"
VEP: 3 (pre-existing in Q1's "VEP would be the fix" revisit text)
vcfanno: 3 (pre-existing in Q1)
```

**GREEN state** (post-edit):

```text
Q5–Q10 presence:        1 each ✓
Q1 superseded:          1 ✓
genomeclaw_gene:        9 ✓ (Q7 + AC list + cross-references)
genomeclaw_pgs:         7 ✓ (Q8 + AC list + cross-references)
/v1/gene/{symbol}:      2 ✓ (Q7 + AC2)
/v1/pgs/{trait}:        2 ✓ (Q8 + AC2)
reference/curated_notes/: 10 ✓ (Q9 + Q7 + AC10 + Privacy & Safety + Out of Scope)
VEP: 13   LOFTEE: 9    AlphaMissense: 10   SpliceAI: 9
vcfanno: 11   Cyrius: 12   pgsc_calc: 12   mosdepth: 9
Q9 gene shortlist:      LCT 3, CYP1A2 5, ADORA2A 4, ALDH2 3, ADH1B 3, APOE 3, MTHFR 3 ✓
PER3/CLOCK/ACTN3 dropped: matched in Out of Scope ✓
```

#### Results

**Edits landed**:
- `docs/plans/active/mvp/spec.md` — single file modified; ~600 lines added across 6 new Decisions Taken (Q5–Q10), Q1 superseded annotation, AC list rewrite (AC1–AC7 updated; AC8–AC12 added), Technical Requirements rewrite (Source Data Inputs + Derived Outputs + Schema/Migration + Pipeline + Agent/UX + External Dependencies), Privacy & Safety rewrite (4-surface boundary scan; PRS classification; lifestyle/clinical separation now references curated notes; review-by-`privacy-safety-reviewer` cue), Out of Scope rewrite (one-CYP1A2 line struck through and replaced; PER3/CLOCK/ACTN3 dropped explicitly; defer-by-default summary), Open Questions date stamp bumped to 2026-05-08.

**Sections touched** (in order of edit):
1. Q1 (superseded annotation; original Q1 body preserved verbatim).
2. Q5–Q10 (six new blocks appended after Q4, before Open Questions).
3. Acceptance Criteria (AC1–AC7 rewritten in place; AC8–AC12 appended).
4. Technical Requirements / Source Data Inputs (added BAM/CRAM, VEP cache + plugins, PGS Catalog scoring weights).
5. Technical Requirements / Derived Outputs (added `coverage_qc`, `pgs_scores`, `cyp2d6_diplotype.json`, `qc.bcftools_stats` in manifest, `reference/curated_notes/`).
6. Technical Requirements / Schema/Migration Impact (reserved schema_version `v0.2`).
7. Technical Requirements / Pipeline / Workflow Impact (added `bcftools stats`, `mosdepth`, VEP stack, MANE Select, PharmCAT outside-call hook).
8. Technical Requirements / Agent / UX Impact (tool count 4 → 6; lifestyle question shape; coverage-aware false-reassurance).
9. Technical Requirements / External Dependencies (VEP + plugins, Cyrius, `pgsc_calc`, `mosdepth`, PharmCAT; SnpEff/SnpSift listed as superseded by Q5).
10. Privacy & Safety (3 → 4 network surfaces; PRS classification; curated-notes lifestyle calibration; `privacy-safety-reviewer` review cue).
11. Out of Scope (one-CYP1A2 bullet struck through and replaced; PER3/CLOCK/ACTN3 dropped; defer-by-default summary).
12. Open Questions (date stamp 2026-05-06 → 2026-05-08).

#### Notes

**Invariant-diff review** (Phase 1 doesn't edit `INVARIANTS.md`, but the spec edits cite specific INV-xxx; reviewing for unintended weakening):
- `INV-D001` — Q6/Q7/AC11/AC12 reaffirm BAM/CRAM read-only discipline; no weakening.
- `INV-D002` — Q5/Q6/Q7/Q8 explicitly host-side; new tools never enter the sandbox; no weakening.
- `INV-E001` — Q9 promotes `gene_note:<gene>` and `topic:hard-genes` as recognized evidence-reference forms; AC10 binds them; **strengthening**.
- `INV-P001` — Q8's PGS Catalog fetch named as deliberate / opt-in / host-side; same shape as existing `genomeclaw-prep fetch`; no weakening.
- `INV-P002` — Q7/Q8 each encode `output_class: summary` plus minimal-sufficient response shapes; no weakening.
- `INV-R001` — Q5/Q6/Q7/Q8 each name the seven canonical provenance columns; new derived tables inherit them; no weakening.
- `INV-C001` — Q9 reframes lifestyle calibration around curated notes; the over-deferral discipline named in v1.4 is preserved (curated notes carry the user's calibrated voice); the four-category schema and `clinical_escalation` markers and `evidence_quality` field all stand. **Strengthened** in spirit; INVARIANTS.md text bumps to v1.5 in Phase 2.

**Surprises / surfaced issues**:
- The original AC1–AC7 list was tighter than expected; only AC1, AC2, AC3, AC4, AC5, AC6 needed substantive rewrites (AC7 determinism stands verbatim).
- `ADORA2A` was already mentioned once in the original spec (in the Q4 Affected files note). The Q9 block now mentions it three more times. Total count is consistent with the gene-shortlist semantics.
- `VEP` and `vcfanno` already appeared in Q1's "Revisit when" / "Rationale" text. Those Q1 mentions are now historical; the live `VEP` and `vcfanno` count is dominated by Q5/Q6/Q7/Q8/AC list / Tech Req / Privacy.
- The Out of Scope rewrite uses a strikethrough on the original "ships one lifestyle finding" bullet rather than deleting it — same hygiene as Q1's superseded annotation. Decision history is preserved.

**No tensions surfaced** between Q5–Q10 and any existing canonical invariant. The plan stays on track for Phase 2.

---

### Phase 2: Architecture + INVARIANTS
**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08

#### Doc-check Results

**RED state** (pre-edit):
```text
Architecture: every searched term: 0 hits
INVARIANTS: Version 1.4, Last Updated 2026-05-06, curated_notes 0 hits, 7 INV-rows in index
```

**GREEN state** (post-edit):
```text
Architecture:
  mosdepth: 1                Cyrius: 2                bcftools stats: 1
  pgsc_calc: 3               LOFTEE: 2                AlphaMissense: 2
  SpliceAI: 2                MANE Select: 1           /v1/gene/{symbol}: 2
  /v1/pgs/{trait}: 2         genomeclaw_gene: 3       genomeclaw_pgs: 3
  reference/curated_notes/: 2 coverage_qc: 4          pgs_scores: 4
  cyp2d6_diplotype: 2        PGS Catalog: 4           gene_note: 4
  topic:hard-genes: 2        vep_cache: 1             pgs_catalog: 1
INVARIANTS:
  Version: 1.5 ✓             Last Updated: 2026-05-08 ✓
  curated_notes: 2 ✓ (Requirements bullet, Where-it-applies bullet; both reference path verbatim)
  v1.5 anchors: 3 ✓ (Requirements / Where-it-applies / How-to-verify each annotated v1.5)
  INV-rows in index: 7 ✓ (preserved verbatim — no invariant added or removed)
```

#### Results

**Edits landed (10 total)**:

`docs/reference/architecture.md`:
- A1 — Component 1 description: VEP stack + LOFTEE + AlphaMissense + SpliceAI + vcfanno + MANE Select; mosdepth, Cyrius, bcftools stats, pgsc_calc named as host-side pipeline steps; subcommand surface enumerated (added `cyp2d6-call`, `pgs-compute`).
- A2 — Component 2 endpoints: `/v1/gene/{symbol}` and `/v1/pgs/{trait}` added with response shapes; `/v1/evidence/{ref}` gains a sub-bullet enumerating non-variant-keyed reference forms (`gene_note:<gene>`, `topic:<topic>`, `topic:hard-genes`).
- A3 — Layered diagram (mermaid `Agent` block): tool list updated to "Tools registered (6)" and the two new tools listed.
- A4 — Data layout: full block rewritten — `raw/` accepts CRAM (was BAM only); `reference/` enumerated subdirs (`grch38`, `clinvar`, `gnomad`, `dbsnp`, `vep_cache`, `pgs_catalog`, `curated_notes/` with seven gene notes + topics/hard-genes.md); `derived/<run-id>/` adds `cyp2d6_diplotype.json` and notes that `coverage_qc` and `pgs_scores` may be tables in `variants.duckdb`. Trailing paragraph notes the `INV-R001` provenance-column inheritance.
- A5 — Network topology: "Two paths" → "Three paths"; PGS Catalog HTTPS path documented as host-side, deliberate, opt-in, not subject to sandbox policy preset; explicit "no genomic data traverses" note.
- A6 — Invariant-traceability table: INV-E001 row gains `gene_note:<gene>` and `topic:<topic>` recognition; INV-P001 row notes PGS Catalog path; INV-P002 row updates to "six plugin tools" and notes new tools' `output_class: summary` defaults; INV-R001 row mentions `coverage_qc`, `pgs_scores`, `cyp2d6_diplotype.json` inheriting provenance columns; INV-C001 row mentions `gene_note:<gene>` evidence references and PRS findings classification.
- Component 3 body: tool surface table added (six rows; columns: Tool / Parameters / Endpoint / Output class); `registerCommand` reference replaced with `registerTool` per MVP spec Q2.

`docs/reference/INVARIANTS.md`:
- I1 — Header: Version 1.4 → 1.5; Last Updated 2026-05-06 → 2026-05-08.
- I2 — INV-C001 Requirements: new bullet "Curated lifestyle calibration via `reference/curated_notes/`" *(v1.5)* recognizing `gene_note:<gene>` evidence references and the user-as-curator pattern.
- I3 — INV-C001 Where it applies: new bullet listing `reference/curated_notes/<gene>.md` and `reference/curated_notes/topics/<topic>.md` files as in-scope; privacy-safety-reviewer agent reviews diffs.
- I4 — INV-C001 How to verify: new snapshot-test bullet on lifestyle responses citing `gene_note:<gene>` and tracking the curated note's framing; "agent over-extending" / "agent ignoring" failure modes named.

#### Notes

**Invariant-diff review** (Phase 2 directly edits `INVARIANTS.md`; explicit invariant-by-invariant check):

- **INV-D001 / INV-D002** — Rule + Requirements + Where-it-applies + How-to-verify all unchanged. Architecture's Component 1 reaffirms host-side discipline for the four new tools.
- **INV-E001** — INVARIANTS Rule + Requirements unchanged (the rule already permitted "internal record IDs"). Architecture's invariant-traceability table makes the gene_note:/topic: forms explicit. **Strengthened in clarity, not weakened.**
- **INV-P001** — Rule + Requirements unchanged. Architecture's network topology adds the PGS Catalog path with the same deliberate-opt-in discipline as existing fetches. **Preserved.**
- **INV-P002** — Rule + Requirements unchanged. Architecture's invariant-traceability table updates the tool count from four to six and reaffirms `output_class: summary` defaults. **Preserved.**
- **INV-R001** — Rule + Requirements unchanged. Architecture's invariant-traceability table adds the new derived artifacts to the inheritance list. **Preserved.**
- **INV-C001** — Rule line **unchanged verbatim**. Requirements + Where-it-applies + How-to-verify each gain a v1.5 bullet recognizing `curated_notes/`. The four-category schema, escalation markers, evidence_quality field, and over-deferral discipline all stand. **Strengthened, not weakened.**

**Cross-document consistency check**:
- MVP spec Q5–Q9 cite specific INV-xxx; INVARIANTS.md Q9 reference (`v1.5`) now matches the actual v1.5 header.
- MVP spec AC3 lists six tools; architecture.md layered diagram + Component 3 table both show six tools.
- MVP spec AC2 endpoint list mentions `/v1/gene/{symbol}` and `/v1/pgs/{trait}`; architecture.md Component 2 enumerates both endpoints with their response shapes.
- MVP spec Q9 cites `reference/curated_notes/`; INVARIANTS.md INV-C001 Requirements/Where-it-applies cite the same path; architecture.md data-layout block enumerates all seven gene notes plus the topics/hard-genes.md companion.
- MVP spec Q8 names PGS Catalog as a deliberate opt-in egress; architecture.md network topology section names it as the third trust-boundary path.

**Surprises / surfaced issues**:
- The `pgs_catalog` directory in the data-layout block (lowercase) and the `PGS Catalog` proper-noun in the network topology section don't conflict — they refer to the same external resource at different layers (filesystem path vs. service URL). This is fine.
- INVARIANTS line 204 originally said `registerCommand` (a leftover from before MVP spec Q2 superseded it). I-3's edit replaced it with `registerTool` to keep INVARIANTS.md's "Where it applies" consistent with current plugin contract. (Strictly a cleanup not in the original Phase 2 scope, but trivial and clearly correct.)
- `LCT` count in INVARIANTS.md is unchanged from RED (the existing `LCT` mention in INV-C001's Requirements was already there at v1.4); curated-notes recognition is additive.

**No tensions surfaced** between v1.5 and any pre-v1.4 wording. The new bullets are strictly additive; the v1.4 baseline reads identically.

---

### Phase 3: Grand plan + user stories
**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08

#### Doc-check Results

**RED state** (pre-edit):
```text
Grand plan:
  VEP: 2 (pre-existing in deferred-question text)   LOFTEE / AlphaMissense / SpliceAI: 0
  Cyrius / pgsc_calc / curated_notes / mosdepth: 0
  Defer-by-default / false reassurance / coverage-aware: 0
User stories:
  bcftools stats / mosdepth / Cyrius / pgsc_calc: 0
  genomeclaw_gene / genomeclaw_pgs: 0
  gene_note:CYP1A2 / topic:hard-genes: 0
  CYP2D6 / Story 10: 0
```

**GREEN state** (post-edit):
```text
Grand plan:
  VEP: 5  LOFTEE: 4  AlphaMissense: 4  SpliceAI: 4
  Cyrius: 3  pgsc_calc: 4  curated_notes: 2  mosdepth: 3
  Defer-by-default: 2 (Strategic Constraints + Decisions Taken table)
  coverage-aware: 2  MANE Select: 2
  "False-reassurance prevention": 1  "false-reassurance failure mode": 1
   (the "false reassurance" plain-words check missed because we used hyphenated form
    consistently — semantic match confirmed via the literal grep above)
User stories:
  bcftools stats: 1  mosdepth: 3  Cyrius: 8  pgsc_calc: 3
  genomeclaw_gene: 4  genomeclaw_pgs: 3
  gene_note:CYP1A2: 2  topic:hard-genes: 2  CYP2D6: 12  Story 10: 2 ✓
  Story 9 PER3/CLOCK decline confirmed by direct read — the agent declines
   gracefully with two specific reasons (non-replication + unreliable VNTR
   genotyping); no orphan PER3 genotype values left in the prose.
```

#### Results

**Edits landed (12 total)**:

`docs/reference/grand-plan.md`:
- G1 — Theme B: VEP + LOFTEE + AlphaMissense + SpliceAI; vcfanno; MANE Select transcript pinning; new "False-reassurance prevention via coverage-aware queries" bullet; Open question on annotator closed (resolved by Q5).
- G2 — Theme G: PharmCAT integration unchanged; new bullets on Cyrius outside-call (Q6) and PRS via `pgsc_calc` (Q8); Open question on PharmCAT outputs partially resolved by Q6.
- G3 — Theme H: full reframe — intro paragraph names `reference/curated_notes/<gene>.md` as the calibration mechanism; gene shortlist (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR); explicit "Genes dropped from the lifestyle track" subsection (PER3, CLOCK, ACTN3); falsifiable-experiment framing scoped to defensible outcomes; INV-C001 v1.5 review-by-`privacy-safety-reviewer` cue. Open questions all resolved.
- G4 — Theme E: clinician-handoff artifacts bullet added (per Q3); Open question on report formats closed.
- G5 — Strategic Constraints: new "Defer-by-default" entry between "Wrappers over rewrites" and "Reproducibility over cleverness"; references the trigger list in Decisions Deferred. Wrappers-over-rewrites updated to enumerate the new tools.
- G6 — Decisions Taken / Decisions Deferred tables refreshed: 6 new "Taken" rows (VEP stack, Cyrius, mosdepth, pgsc_calc, curated_notes/, defer-by-default); 14 new "Deferred" rows (HLA, SV, repeats, mtDNA, population panels, citation stripping, tool-use forcing, deterministic findings card, phrasing templates, ACMG/AMP rule classifier, eval harness, additional PRS traits, automated reanalysis, additional vcfanno sources); 3 previously-deferred items struck through as resolved (default annotator, report formats, plugin JSON return).

`docs/reference/user-stories.md`:
- U1 — Story 1: ingest CLI invocation gains `--bam`; pipeline narrative reflects new tool steps (bcftools stats, mosdepth, VEP+plugins, vcfanno, Cyrius, PharmCAT outside-call); CLI "Run complete" output enumerates new artifacts; new step 6 for `pgs-compute`; original steps 6/7 renumbered to 7/8; agent's `genomeclaw_status` framing updated to "schema v0.2" and notes the six tools.
- U2 — Story 3 (BRCA1): tool-call list adds `genomeclaw_gene gene="BRCA1"`; agent's response now surfaces `mean_coverage: 28.4` and `low_coverage_exons: ["NM_007294.4:exon-11"]`; the "could it be hiding in a region the WGS misses?" follow-up is partially pre-answered by the coverage check; agent reaches for `topic:hard-genes` curated note.
- U3 — Story 4 (clopidogrel): extended with a CYP2D6 sub-conversation (codeine / SSRIs / tamoxifen). Agent calls `genomeclaw_findings category=pgx genes=["CYP2D6"]` which resolves against the Cyrius diplotype computed at ingest; surfaces `*1/*4` intermediate-metabolizer phenotype with CPIC guidance; "Notable extension" paragraph explains the Cyrius+PharmCAT integration value.
- U4 — Story 9 (caffeine): full rewrite around curated-note retrieval. Agent calls `genomeclaw_evidence(ref="gene_note:CYP1A2")` and composes its response from the user's variant + the note's framing in the project owner's voice ("AA = fast, CC = slow", "smoking and OCP induce/inhibit more than genotype does", "evidence quality: moderate. Don't oversell."). PER3/CLOCK follow-up gracefully declined with two specific reasons (non-replication + unreliable VNTR genotyping on short-read WGS); the agent does respond on ADORA2A which is in the curated set. Surfaced-gaps section refreshed: A11/A12 marked partially-superseded by Q9.
- U5 — new Story 10 (PRS for CAD): user mentions father's MI at 58; agent calls `genomeclaw_pgs trait="CAD"`; surfaces 87th-percentile result with explicit "what this does/does not mean" framing; calibration-warning explanation; `clinical_escalation` marker explicitly absent (by design); cardiovascular-prevention picture named without overriding clinician judgment. Tool-call provenance includes `pgs_catalog:PGS000018` evidence reference. Surfaced-gaps note third-party-phenotype-data discipline (father's MI not persisted into user's record).
- U6 — gap-analysis updates: A4 horizon-renumbered (6→7); A6 marked ✅ (evidence resolver covers gene_note:/topic:); A11 marked partially-superseded; A12 example marked obsolete (PER3/CLOCK dropped); 3 new resolved-items (A13 coverage-aware, A14 CYP2D6 outside-call, A15 PRS); G3 marked ✅ (clinician-handoff bullet added to Theme E); G5 extended with curated-notes reframe note; new G6 (annotator stack) and G7 (defer-by-default) marked ✅; new I7 (curated lifestyle calibration surface) marked ✅.

#### Notes

**Cross-document consistency review**:
- Tool count "six" / "6" appears in MVP spec AC3, architecture.md layered diagram + Component 3 table, grand-plan Theme G (mention of `genomeclaw_pgs` 6th tool implicit), user-stories Story 1 ending. Consistent.
- VEP stack named `VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno` consistently across MVP spec Q5, architecture.md Component 1, grand-plan Theme B, user-stories Story 1. Consistent.
- Curated-notes path `reference/curated_notes/` named consistently across MVP spec Q9, INVARIANTS v1.5 INV-C001, architecture.md data layout, grand-plan Theme H, user-stories Story 9. Consistent.
- "Defer-by-default" wording cited identically in grand-plan Strategic Constraints + Decisions Taken row + MVP spec Q10. Consistent.
- PER3/CLOCK/ACTN3 named as "dropped" (not "deferred") consistently across MVP spec Out of Scope + Q9, grand-plan Theme H, user-stories Story 9 + gap-analysis. Consistent.

**Invariant-diff review** (Phase 3 doesn't edit `INVARIANTS.md`; reviewing for unintended ripple-through-narrative weakening):
- INV-D001 / INV-D002 — Story 1 narrative reaffirms `--bam` is read-only ingest input; mosdepth/Cyrius read BAM but don't mutate. **Preserved.**
- INV-E001 — Story 9 demonstrates `gene_note:CYP1A2` evidence reference; Story 3 demonstrates `topic:hard-genes`; Story 10 demonstrates `pgs_catalog:PGS000018`. Every interpretation is evidence-bound. **Strengthened.**
- INV-P001 — Story 1 names PGS Catalog fetch as deliberate / opt-in / host-side. Story 10 narrative does not echo any genomic data outbound. **Preserved.**
- INV-P002 — Story 10 demonstrates minimal-sufficient PRS response shape (no raw variant lists). Story 3 demonstrates minimal-sufficient gene-tool response shape. **Preserved.**
- INV-R001 — Story 1 narrative pins the new tools' versions in the manifest output. **Preserved.**
- INV-C001 v1.5 — Story 9 demonstrates curated-notes-driven calibration; over-deferral and over-claim both avoided; PER3/CLOCK gracefully declined without speculating. Story 10 demonstrates PRS classification (`clinical-non-actionable`, no `clinical_escalation` marker). **Strengthened in narrative.**

**Surprises / surfaced issues**:
- The grep for plain-words "false reassurance" in grand-plan returned 0 because the doc consistently uses the hyphenated form ("False-reassurance prevention" in Theme B; "false-reassurance failure mode" in Decisions Taken). Semantic match confirmed via direct file read; the doc-check is satisfied. The Phase 3 detail plan's check_gp_theme_b_false_reassurance was overly literal; future doc-checks should use a regex (`-i 'false[- ]reassurance'`) when matching English noun phrases that may be hyphenated either way.
- Story 9's rewrite is the longest single narrative change in this plan (~50 lines of new prose). Snapshot tests on this story will be load-bearing for INV-C001 v1.5 verification when MVP Phase 6 lands.
- The new Story 10 (PRS) inherits Story 1 setup (the user has already ingested + run pgs-compute). I considered authoring it as a sub-section of an existing story (e.g., under Story 6's preventive-medicine sweep) but the PRS UX is distinct enough — different response shape, different framing burden — that it earns its own story.

**No tensions surfaced** between Phase 3 narrative and any earlier phase's structural decisions. The doc set remains internally coherent.

---

### Phase 4: MVP development-plan + phase-2
**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08

#### Doc-check Results

**RED state** (pre-edit):
```text
MVP dev-plan: every searched term: 0
MVP phase-2: every searched term: 0
MVP phase-1: git diff --stat empty (file untouched)
```

**GREEN state** (post-edit):
```text
MVP dev-plan:
  VEP: 9   LOFTEE: 10   AlphaMissense: 11   SpliceAI: 11   vcfanno: 9
  Cyrius: 8   pgsc_calc: 8   mosdepth: 9   curated_notes: 6
  genomeclaw_gene: 5   genomeclaw_pgs: 5   PGS Catalog: 5
  MANE Select: 6   coverage_qc: 6   pgs_scores: 3
MVP phase-2:
  bcftools stats: 5   mosdepth: 14
  test_invR001_bcftools_stats_in_manifest: 1 ✓
  test_coverage_qc_table_populated: 1 ✓
  test_invD001_bam_unchanged_after_mosdepth: 1 ✓
  _mosdepth: 2 (module + test ref)   _bcftools_stats: 4   tiny.bam: 4
MVP phase-1: git diff --stat empty ✓ (unchanged by design)
```

**Cross-phase coherence GREEN**:
```text
Tool count "six" / "6" present in MVP spec AC3 + Tech Req + Q7/Q8 ✓
"VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno" exact phrase appears in:
  mvp/spec.md: 3   architecture.md: 1   grand-plan.md: 3   development-plan.md: 4 ✓
"reference/curated_notes/" path appears in:
  mvp/spec.md: 10   INVARIANTS.md: 2   architecture.md: 2   grand-plan.md: 2
  user-stories.md: 3   development-plan.md: 5 ✓
"Defer-by-default" appears in: mvp/spec.md: 2   grand-plan.md: 2 ✓
```

#### Results

**Edits landed (10 total)**:

`docs/plans/active/mvp/development-plan.md`:
- D1 — Solution Design Key Design Decisions: Decisions #3 and #4 rewritten (VEP stack supersedes SnpEff per Q5; seven curated lifestyle notes per Q9 supersede the one-CYP1A2 plan); Decisions #6, #7, #8, #9 added (Cyrius per Q6, mosdepth + genomeclaw_gene per Q7, pgsc_calc + genomeclaw_pgs per Q8, defer-by-default per Q10).
- D2 — Solution Design Schema/Provenance Impact: schema v0.2 reserved with full enumeration of new columns (MANE Select HGVSc/HGVSp, AlphaMissense, SpliceAI, LOFTEE, gnomAD per-ancestry AFs, gene LOEUF), new tables (`coverage_qc`, `pgs_scores`), new manifest field (`qc.bcftools_stats`), new artifact (`cyp2d6_diplotype.json`).
- D3 — Solution Design Privacy & Egress Impact: PGS Catalog fetch added as 4th egress point; minimal-sufficient response shape for new tools noted.
- D4 — Phase Overview table: tool count "6" in Phase 5 description; Phase 2 / 4 / 5 / 6 descriptions all updated for Q5–Q9 deliverables; total est. tests 80 → 93.
- D5 — Phase 2 inline summary: deliverables 5 (bcftools stats) and 6 (mosdepth) added; INV-D001 / INV-R001 paragraphs extended to mention BAM-immutability and `coverage_qc` provenance; Success Criteria gain test cases 19/20/21 references.
- D6 — Phase 4 inline summary: full rewrite around VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno; MANE Select pinning; schema columns enumerated; schema bump v0.1 → v0.2.
- D7 — Phase 5 inline summary: tool count 4 → 5 (genomeclaw_gene per Q7) with TypeBox schema spelled out; new `/v1/gene/{symbol}` endpoint; INV-D002 sandbox check expanded to include the four new host-side tools; policy preset GET-path allowlist updated; Phase 6 noted as adding the 6th tool.
- D8 — Phase 6 inline summary: full rewrite around the seven-gene curated_notes/ shortlist (per Q9); Cyrius CYP2D6 outside-call (per Q6); pgsc_calc + genomeclaw_pgs (per Q8); evidence resolver accepts gene_note:/topic:; policy preset GET-path allowlist for the new endpoints; PRS findings classification (`clinical-non-actionable`, no escalation, calibration warning); Story 10 added to snapshot test list; privacy-safety-reviewer agent reviews curated-note diffs.
- D9 — Open Risks & Follow-ups: SnpEff-vs-VEP risk struck through (resolved by Q5); new risks added (AlphaMissense + SpliceAI dataset sizes, Cyrius dependency, PGS Catalog fetch, curated-notes editorial discipline).

`docs/plans/active/mvp/phases/phase-2.md`:
- P1 — Objective + Scope Boundaries: rewritten to mention BAM/CRAM input; bcftools stats + mosdepth deliverables; coverage_qc table; in-scope/out-of-scope lists updated; Phase 4 reference now mentions VEP stack (per Q5) instead of SnpEff.
- P2 — Invariants Enforced: INV-D001 paragraph extended for BAM-immutability post-mosdepth; INV-R001 paragraph extended for `mosdepth` version + `qc.bcftools_stats` block + `coverage_qc` provenance columns.
- P3 — TDD Step 2.1 test cases 19/20/21 appended under a new "Coverage + QC tests" subheading; each cites its `INV-xxx` and the spec Q-block that motivated it.
- P4 — Files table: 5 new modules and tests added (`prep/_bcftools_stats.py`, `prep/_mosdepth.py`, `schemas/coverage_qc.py`, three test files, BAM/`.bai` fixtures); Verification block extended (mosdepth tool-version check, ingest invocation gains `--bam`, derived-store inspection includes `coverage_qc` query, expected outcomes updated to "All 21 test cases"); Completion Criteria first checkbox bumped from "All 18" to "All 21".

`docs/plans/active/mvp/phases/phase-1.md`: **Reviewed; unchanged.** `git diff --stat` confirms zero edits. Phase 1's foundations-only scope (`pyproject.toml`, package skeleton, `genomeclaw-prep --help`, CI workflow, smoke tests) is unaffected by Q5–Q10. The `cli.py` placeholder subcommand list (`fetch`, `ingest`, `normalize`, `annotate`, `materialize`) does not need to be extended in Phase 1 — adding `cyp2d6-call` and `pgs-compute` happens in MVP Phase 6.

#### Notes

**Invariant-diff review**: Phase 4 doesn't edit `INVARIANTS.md`; reviewing the MVP-plan edits for unintended weakening:
- INV-D001 — Phase 2 inline summary + phase-2.md detail both add the BAM-immutability test case; **strengthened**.
- INV-D002 — Phase 5 sandbox-image smoke test expanded to cover the four new host-side tools; **strengthened**.
- INV-E001 — Phase 6 deliverables explicitly require evidence references on findings, with `gene_note:<gene>` for lifestyle and `pgs_catalog:<id>` for PRS; **strengthened**.
- INV-P001 — Phase 6 deliverable 7 names PGS Catalog fetch as deliberate / opt-in; default-config integration tests in Phase 5/6/7 still hold. **Preserved.**
- INV-P002 — Phase 5 / Phase 6 deliverables specify `output_class: summary` defaults; PRS responses never include raw variant lists; bulk-class endpoints still wired-but-disabled. **Preserved.**
- INV-R001 — Phase 2 + Phase 4 + Phase 6 all reaffirm the seven canonical provenance columns on every new derived table / artifact; manifest tool-version pinning extended to mosdepth/Cyrius/pgsc_calc. **Preserved.**
- INV-C001 v1.5 — Phase 6 deliverable 8 names the seven-gene curated_notes/ shortlist plus topic:hard-genes; PER3/CLOCK/ACTN3 explicitly **not** shipped (dropped per Q9); PRS findings carry `clinical-non-actionable` + no escalation marker per Q8. Snapshot tests cover Story 9 (curated-note framing) and Story 10 (PRS classification). **Strengthened.**

**Cross-phase coherence**: all four cross-doc consistency checks pass.
- Tool count "six" consistent across MVP spec + architecture + dev-plan.
- VEP-stack named identically across MVP spec / architecture / grand-plan / dev-plan.
- Curated-notes path identical across all six docs that reference it.
- Defer-by-default cited identically in MVP spec Q10 + grand-plan Strategic Constraints.

**Surprises / surfaced issues**:
- The dev-plan rewrite was larger than the phase-4.md detail plan estimated (adding Decisions #6/#7/#8/#9 to Solution Design + extending Phase 5/6 deliverables substantially), but the structural pattern stayed clean.
- Phase 5 inline summary now correctly notes that Phase 5 lands the **5th** tool (`genomeclaw_gene`) and Phase 6 lands the **6th** tool (`genomeclaw_pgs`). The plan-level "tool count 4 → 6" headline holds, but the granular phasing is "4 → 5 → 6" because the PRS deliverable is bundled with Phase 6's findings/evidence work.
- The `coverage_qc` table can be either a separate `.duckdb` file or a table inside `variants.duckdb`; both Phase 2 and the architecture data-layout block leave the option open. Phase 2 implementer chooses at GREEN time.

**Plan-close marker**:

All four phases of `docs/plans/active/poc-pipeline-recommendations/` are complete. The plan is ready to move to `docs/plans/completed/poc-pipeline-recommendations/`.

**Final sign-off**:
- 18/18 doc-checks GREEN in Phase 1; 20/20 in Phase 2; 16/16 in Phase 3; 16/16 in Phase 4 (15 substantive + 1 unchanged-by-design).
- Cross-phase coherence checks all pass.
- No canonical INV-xxx weakened anywhere; INV-E001 and INV-C001 strengthened by the curated-notes recognition; the other five preserved with reaffirmations.
- No code under `packages/` was touched.
- The MVP plan + reference docs are now internally consistent against the recommendations report and ready for MVP Phase 1 implementation when the project resumes.

**Recommended next step**: a separate small plan to handle the README freshening (per the existing user-stories.md § Plan change-set 5). That work is out of scope for this plan; capturing as a follow-up.

---

## 2026-05-08 — Coda: README freshening (user-stories § Plan change-set 5)

The user requested README updates inline after the main four-phase plan closed. Treated as a one-file follow-up rather than a new full plan, since change-set 5's scope is targeted and the updates are mechanical doc-edits that follow directly from the now-landed reference docs.

**Edits landed (8 targeted edits to `README.md`)**:

1. Tagline (line 7) — added Telegram as the user surface; added OpenAI gpt-5.4 alongside Claude Opus / Gemini.
2. Status section — bumped to reflect INVARIANTS v1.5 + closed MVP plan; added pointers to architecture.md and user-stories.md.
3. "What This Is" lifestyle examples — **removed ACTN3** (dropped per Q9; cannot stay as a positive example); replaced with the seven-gene curated-notes set (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR); added pointer to MVP spec Q9.
4. Architecture diagram — replaced the old four-layer diagram with a host/sandbox split mermaid showing User → Telegram → Agent → Service → Store + Prep → Raw, plus a pointer to architecture.md (per gap R1).
5. Tooling section — full rewrite: VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno as the default annotator (per Q5); SnpEff/SnpSift struck through and labeled superseded; mosdepth, Cyrius, pgsc_calc, PharmCAT all listed; plugin-side TypeScript/openclaw-plugin-sdk dependencies added.
6. Privacy posture — OpenAI gpt-5.4 added (per gap R5); PGS Catalog fetch noted as host-side opt-in; INV-C001 v1.5 reference added.
7. How NemoClaw Agents Use GenomeClaw — Telegram added as the canonical user surface (per gap R4); the six tools enumerated; host CLI subcommand list updated to include `cyp2d6-call` and `pgs-compute`; host service endpoint list complete.
8. Repository Layout — full rewrite to the `packages/toolkit/` + `packages/nemoclaw-plugin/` workspace shape (per gap R3); old `pipelines/` / `src/` / `data/` layout removed; host-side `/mnt/genomeclaw/` data tree shown as a separate block.
9. Getting Started — replaced the placeholder commands with a six-step onboarding sketch from Story 1 (fetch → ingest with --bam → pgs-compute → service start → onboard plugin → Telegram); each step annotated with what the pipeline runs (per gap R2).

**Final GREEN structural check**:
```text
OpenAI gpt-5.4: 3   Telegram: 4
VEP: 5   LOFTEE: 3   AlphaMissense: 3   SpliceAI: 3   vcfanno: 3
Cyrius: 4   pgsc_calc: 2   mosdepth: 3   PharmCAT: 5   curated_notes: 4
packages/toolkit: 3   packages/nemoclaw-plugin: 4
genomeclaw_gene: 1   genomeclaw_pgs: 1   v1.5: 3
INVARIANTS: 9   architecture.md: 4   user-stories.md: 4
ACTN3 in lifestyle context: 0 ✓ (dropped per Q9)
SnpEff: only in superseded-marker text ✓
```

User-stories § Plan change-set 5 (R1–R5) is fully addressed. The README freshening follow-up is complete; no separate plan needs to be filed.

---

## Key Decisions

### Decision 1: Per-document-family phasing
**Date**: 2026-05-08
**Context**: With seven target documents and six topical changes (VEP, Cyrius, coverage, PRS, curated notes, defer-by-default), the plan could be phased per-topic or per-document-family.
**Decision**: Per-document-family phasing — Phase 1 = MVP spec, Phase 2 = architecture + INVARIANTS, Phase 3 = grand-plan + user-stories, Phase 4 = MVP dev-plan + phase-2.
**Rationale**: Smaller reviewable diffs; each phase ends with a self-contained doc-check; invariant-diff review concentrates in Phase 2 where the canonical doc actually changes; the linear ordering keeps every intermediate state internally coherent (Phase 1 decisions are cited by Phase 2 architecture, etc.).
**Alternatives Considered**:
- *Per-topic phasing* — rejected because each topic touches 3–4 docs, making single-PR review hard.
- *Single mega-phase* — rejected because the diff would be too large to review carefully, and there's no atomicity gain (every doc edit is independently reversible).
**Affected Invariants**: None directly; the phasing structure protects all seven by making per-phase invariant-diff review possible.

### Decision 2: INVARIANTS bumps to v1.5, not v2.0
**Date**: 2026-05-08
**Context**: INV-C001 needs to recognize `reference/curated_notes/` as a calibration surface. Is this a clarifying revision (v1.5) or a substantive change (v2.0)?
**Decision**: v1.5 — clarifying revision.
**Rationale**: No invariant is added or removed. INV-C001's Rule is unchanged ("Separate Clinical Advice from Lifestyle and Research Assistance"); only Requirements and "Where it applies" sections gain the curated-notes recognition. The four-category schema, escalation markers, evidence_quality field, and over-deferral discipline all remain. v1.5 is the right calibration: substantive enough to record explicitly; not a rewrite.
**Alternatives Considered**:
- *No bump* — rejected because the recognition affects what tests / reviewers must check; the change deserves a version marker.
- *v2.0* — rejected because it would imply a substantive rewrite that isn't happening.
**Affected Invariants**: INV-C001 (clarified; not weakened).

### Decision 3: Q1 marked superseded, not deleted
**Date**: 2026-05-08
**Context**: Q5 supersedes Q1's SnpEff decision. Two options: delete Q1 (keep the spec clean), or annotate Q1 with a "superseded by Q5" line (preserve history).
**Decision**: Annotate; preserve.
**Rationale**: The decision evolution is part of the project's reasoning history. Future contributors and reviewers benefit from seeing why SnpEff was originally chosen, why it was replaced, and on what date. Spec hygiene comes from clear annotation, not from deletion.
**Alternatives Considered**:
- *Delete Q1* — rejected; loss of historical reasoning.
- *Move Q1 to a "superseded decisions" section* — rejected; adds structural complexity for marginal benefit.
**Affected Invariants**: None.

### Decision 4: Archive recommendations report verbatim in this file
**Date**: 2026-05-08
**Context**: The recommendations report is the source motivation for the entire plan. Archive it where?
**Decision**: Verbatim under § Archive below in this `work-notes.md`.
**Rationale**: One file, one source of truth. Future contributors should not need to reconstruct conversation transcripts to understand what motivated Q5–Q10. The archive lives next to the plan that consumes it.
**Alternatives Considered**:
- *Separate `initial_findings.md`* — rejected; adds a file for content that's truly source motivation, not exploratory research.
- *Link to an external location* — rejected; this is a personal, single-user project with no external location for the report.
**Affected Invariants**: None.

---

## Files Modified

### Created (this session, by this plan)
- `docs/plans/active/poc-pipeline-recommendations/spec.md` — feature spec.
- `docs/plans/active/poc-pipeline-recommendations/development-plan.md` — 4-phase plan.
- `docs/plans/active/poc-pipeline-recommendations/work-notes.md` — this file.
- `docs/plans/active/poc-pipeline-recommendations/phases/phase-1.md` — Phase 1 detailed plan.

### Modified
None yet. Phase 1 of this plan is the first to modify a doc outside this plan's directory (`docs/plans/active/mvp/spec.md`).

### Deleted
None.

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Bump version to v1.5 (Phase 2).
- [ ] INV-C001 Requirements: add `curated_notes/` recognition (Phase 2).
- [ ] INV-C001 "Where it applies": list `reference/curated_notes/` editing (Phase 2).

### Other Documentation
- [ ] `docs/reference/architecture.md` — Component 1, Component 2, Component 3 tool table, layered diagram, data layout, network topology, invariant-traceability table (Phase 2).
- [ ] `docs/reference/grand-plan.md` — Themes B, G, H; Strategic Constraints; Decisions Taken / Deferred tables (Phase 3).
- [ ] `docs/reference/user-stories.md` — Stories 1, 3, 4, 9; new PRS story; gap-analysis updates (Phase 3).
- [ ] `docs/plans/active/mvp/spec.md` — Q5–Q10, AC list, Out of Scope (Phase 1).
- [ ] `docs/plans/active/mvp/development-plan.md` — Phase Overview, Solution Design, Schema, Privacy, Phase 4/5/6 inline summaries (Phase 4).
- [ ] `docs/plans/active/mvp/phases/phase-2.md` — Deliverables 5/6, test cases 19/20/21, Files table (Phase 4).
- [ ] `.claude/agents/*.md` — **NOT updated** by this plan; privacy-safety-reviewer agent's existing scope already covers user-facing copy review including curated notes.

---

## Open Risks & Follow-ups

- **Doc-drift between phases.** Each phase ends with a structural doc-check; Phase 4's exit gate runs a cross-phase coherence check (tool count consistency, VEP-stack naming consistency, curated-notes path naming consistency, "Defer-by-default" wording consistency).
- **`phases/phase-3.md` through `phases/phase-7.md` of the MVP plan are not authored by this plan.** Their authors will inherit from the Phase 4 deliverables. Phase 4 of this plan ensures `development-plan.md` Phase 4/5/6 inline summaries are detailed enough for future authors.
- **README freshening** is a follow-up plan. Not in scope here.
- **AlphaMissense + SpliceAI dataset sizes.** The recommendations report names them as best-in-class but doesn't pin sizes. Phase 4 flags this for the MVP Phase 4 implementer to validate against the personal-host resource envelope.
- **Candidate INV-C002.** A future plan may promote a structural rule about curated notes if usage justifies. Not promoted here.
- **The Decision Taken Q5 supersedes Q1, but the existing MVP `development-plan.md` Phase 4 description names SnpEff explicitly.** Phase 4 of this plan rewrites that. If, between Phase 1 (Q5 lands) and Phase 4 (development-plan rewrite), a different agent or contributor reads `mvp/development-plan.md` and acts on the SnpEff naming, the project drifts. Mitigation: this plan should be executed Phase 1 → 4 in a single contiguous effort, and `work-notes.md` Phase 1 block should explicitly call out that `mvp/development-plan.md` Phase 4 description is in transition until Phase 4 of this plan.

---

## Archive — Source recommendations report

> Verbatim copy of the POC-stage pipeline recommendations report that motivated this plan. Captured 2026-05-08 from the conversation transcript. The plan's Phase 1–4 decisions trace directly to specific paragraphs in this report; cross-references appear inline below.

---

# GenomeClaw — Pipeline and Interpretation Recommendations

## Context

GenomeClaw is a personal genomic assistant for a single technically-capable user. The user holds their own Nebula Genomics 30× WGS deliverable (already-called VCF, plus BAM/CRAM available) and queries it conversationally via an LLM agent (NemoClaw/OpenClaw stack, frontier model over Telegram). Raw genomic files stay on the user's host. The agent answers two kinds of questions: clinical (with research-grade framing and clinician confirmation cues) and lifestyle (direct calibrated guidance, framed as falsifiable experiments).

This document is scoped to the **POC stage** of the project — the goal is a system that one user actually uses and that doesn't produce confidently wrong answers in the high-stakes cases. This is not a regulated clinical product. The architectural ambition is "honest personal assistant," not "validated diagnostic tool."

The recommendations below are organized by impact: the changes that prevent catastrophic failure modes first, then high-value low-cost additions, then design choices for the lifestyle track, then a list of features worth deferring until specific use cases arise.

---

## The two changes that prevent catastrophic wrong answers

### 1. Replace SnpEff with VEP + LOFTEE + AlphaMissense + SpliceAI

The MVP plan defaults to SnpEff for variant annotation. For a system that emits clinical-track findings with escalation markers, this produces wrong answers at a rate that matters.

The decisive issue is loss-of-function (LoF) interpretation. Independent benchmarks comparing SnpEff, VEP, and ANNOVAR on curated truth sets show:

- Concordance on broad coding-impact assignment is ~99% on SNVs but drops below 90% on indels and splicing variants near canonical sites.
- Concordance on LoF predictions specifically falls to 65–44% when transcript sets differ between tools.
- All three tools incorrectly downgrade pathogenic/likely-pathogenic variants in standardized testing (ANNOVAR ~56%, SnpEff ~67%, VEP ~67%) — but VEP's plugin ecosystem provides the only practical path to filtering these correctly.

The fix is not VEP alone — it's VEP plus three plugins that materially reduce false-positive LoF calls and sharpen variant impact predictions:

- **LOFTEE**: filters predicted-LoF variants for confidence (last-exon flag, NAGNAG splice rescue, GERP, intron retention). Without LOFTEE, single-sample LoF lists are dominated by false positives. A 2023 curation study found that ~67% of "high-confidence" heterozygous predicted-LoF variants in dominant disease genes were not actually LoF after manual review even after LOFTEE pre-filtering — and that's *with* LOFTEE; without it, the rate is far higher.
- **AlphaMissense** (DeepMind, Science 2023): state-of-the-art missense pathogenicity prediction (MCC 0.6–0.74 across protein classes), classifies ~89% of all possible missense variants. Reduces the VUS interpretation gap substantially.
- **SpliceAI** (Illumina): dominant splice-altering variant predictor; reasonable thresholds 0.2 (high recall) / 0.5 (recommended) / 0.8 (high precision). Genuinely changes interpretation in a clinically meaningful fraction of cases by moving variants from "intronic, no impact" to "putatively splice-altering."

Plus **MANE Select transcript pinning**: a built-in VEP flag. The agent should report HGVSc and HGVSp on the MANE Select transcript by default; HGVS strings should be produced server-side, never constructed by the LLM.

For bulk annotation of population frequencies and clinical databases, **vcfanno** runs alongside VEP and stamps tabix-indexed annotations onto the VCF. For the POC, two sources are enough: ClinVar (latest release) and gnomAD v4 with per-population allele frequencies. OMIM, ClinGen Gene-Disease Validity, and gnomAD constraint can be added later as needed; the gnomAD constraint LOEUF lookup is the most likely first add (used in the gene-level tool described below).

The full "clinical-grade" annotation stack would also include dbNSFP (REVEL/CADD/PrimateAI), MaxEntScan, UTRannotator, and an ACMG/AMP rule classifier (InterVar or Genebe). For the POC, skip these. The three plugins above plus ClinVar + gnomAD via vcfanno cover ~90% of the interpretive value.

### 2. Add Cyrius for CYP2D6 outside-call into PharmCAT

PharmCAT is the right backbone for ~22 CPIC-aligned pharmacogenes — but it explicitly does not call CYP2D6 from VCF. The official PharmCAT documentation directs users to provide an outside-call diplotype.

CYP2D6 matters disproportionately:

- It metabolizes ~25% of clinically prescribed drugs (codeine, tramadol, oxycodone, tamoxifen, many antidepressants, antipsychotics).
- It is genetically complex (>130 star alleles, copy-number variation including whole-gene deletions and duplications, hybrid alleles with the CYP2D7 pseudogene).
- Standard small-variant callers fail at this locus because of 94% sequence homology with CYP2D7 — reads frequently misalign.

Without CYP2D6 calling, the project's Story 4 demo (clopidogrel, where CYP2C19 happens to be the relevant gene — but the same user is going to ask about codeine, SSRIs, or tamoxifen next) will produce wrong output in a clinically meaningful fraction of cases.

The validated tool is **Cyrius** (Illumina). Independent benchmarking on the GeT-RM truth set:

| Tool | Overall concordance | Concordance with SVs | Concordance without SVs |
|---|---|---|---|
| Cyrius | 96.5–99.3% | 94.4% | 97.8% |
| Aldy | 86.8–92.2% | 87.0% | 86.7% |
| Stargazer | 84.0% | 75.9% | 88.9% |

Cyrius runs on the BAM/CRAM (not the VCF) and produces a star-allele diplotype that feeds into PharmCAT's outside-call interface. Implementation cost: one extra container + ~50 lines of glue. Without this, the PGx track of the agent is unsafe.

---

## Two high-value, low-cost additions

### 3. Coverage-aware gene-level queries

The single most dangerous failure mode of a personal genomic agent is false reassurance: "you don't have a pathogenic BRCA1 variant" when the relevant exon wasn't covered. Short-read 30× WGS systematically miscalls or misses variants in regions including PMS2, GBA, CYP21A2, SMN1, STRC, NCF1, HBA1/HBA2, IKBKG, CYP2D6, and the HLA region — and even in well-behaved genes, individual exons can fall below the depth threshold for confident calls.

The mitigation is one extra ingest step plus one new tool:

- Run `mosdepth` once at ingest against the BAM/CRAM. Materialize per-gene mean coverage (and optionally per-exon mean coverage for a curated set of clinically important genes) into the derived store as a single table.
- Add `genomeclaw_gene(gene)` to the plugin tool surface. It returns gene-level facts: top user variants in the gene, gene constraint (LOEUF lookup from gnomAD), OMIM disease + inheritance pattern, **mean coverage in the user's BAM**.

The agent reads the coverage value and includes it naturally in negative answers ("no pathogenic BRCA1 variants in your callset; mean coverage of BRCA1 averaged 28×, which is adequate" — or, conversely, "but exon 11 averaged 4×, below the threshold for confident calls; clinical confirmation would require targeted Sanger sequencing"). One number, one tool, most of the false-reassurance failure mode addressed.

A small `curated_notes/hard-genes.md` file listing the systematically poorly-resolved genes (PMS2, GBA, etc.) with a one-paragraph caveat each, returnable via `genomeclaw_evidence`, gives the agent the additional context it needs when those genes come up.

### 4. PRS via `pgsc_calc` for a small initial set of traits

Single-SNP findings cannot meaningfully answer common-disease risk questions. Polygenic risk scores can, and the infrastructure for running them locally is mature: the **PGS Catalog Calculator** (`pgsc_calc`, Nextflow) handles the canonical concerns (genome build liftovers, strand alignment, multi-allelic variant matching, continuous-ancestry normalization against 1000G+HGDP). It runs comfortably on a personal host (16GB RAM, 2 CPUs on Linux).

For the POC, run three traits initially and add others when the user asks:

- **Coronary artery disease** (well-established, large effect range, actionable for lifestyle motivation)
- **Type 2 diabetes** (well-established, lifestyle-modifiable)
- **Breast cancer or prostate cancer** (depending on user's personal interest; PRS313/BCAC and PRS269 are the validated choices)

Add `genomeclaw_pgs(trait)` to the tool surface. It returns `{percentile_in_user_ancestry, raw_score, source_pgs_id, study_population, calibration_warning}`. The percentile must be ancestry-normalized (`pgsc_calc` does this with `--run_ancestry`); reporting raw percentiles without ancestry calibration produces systematically wrong numbers for non-European users.

Adding more traits later is a one-line config change in `pgsc_calc`. Defer the full panel of 8–10 traits until a specific question motivates each addition.

---

## Lifestyle track design

The lifestyle track in the existing plan (Theme H) is the part of the system most likely to produce subtly oversold or misframed advice. The literature is thinner than for clinical findings, effect sizes are smaller, and ancestry stratification matters more.

The simplest defensible architecture:

**A `curated_notes/` directory** with one markdown file per gene of interest. Each note is the project owner's own calibrated take on the evidence, written in plain English. The agent retrieves a note via `genomeclaw_evidence(ref="gene_note:CYP1A2")` and composes its response from the user's variant call plus the note's framing.

Example `curated_notes/cyp1a2.md`:

```markdown
# CYP1A2 (rs762551)

Caffeine metabolism. AA = "fast", CC = "slow", AC heterozygote = intermediate
but with high variance. Effect size moderate at best.

Big caveats: smoking and oral contraceptives induce/inhibit CYP1A2 more than
genotype does. Heterozygote behavior is genuinely uncertain. The
"fast vs slow metabolizer" dichotomy is an oversimplification of a
continuous trait.

For caffeine + sleep: noon cutoff for slow metabolizers is a reasonable
2-week experiment. For caffeine + ergogenic effect: literature is real
but heterogeneous; AA carriers see ~small benefit, CC carriers see null
or negative.

Evidence quality: moderate. Don't oversell.
```

This pattern is explicitly designed for one user. The user is the curator; the agent is the reader. The user can edit notes over time to refine the agent's framing as their own thinking evolves. This is a much simpler architecture than structured `evidence_quality` taxonomies, mandatory effect-size schema fields, and pre-built phrasing templates — and for a single sophisticated user, it's strictly better because the framing stays in the user's voice and judgment.

**Initial gene shortlist** (~7 notes, ~7 well-validated lifestyle variants):

| Gene / variant | Evidence | Notes |
|---|---|---|
| **LCT/MCM6 rs4988235** (lactase persistence) | Strong | Single causal variant, large effect, well-replicated. European persistence allele; non-European persistence variants are different (rs145946881, rs41380347, rs41525747) — handle ancestry. |
| **CYP1A2 rs762551** (caffeine metabolism) | Moderate | See note above. Don't dichotomize. |
| **ADORA2A rs5751876** (caffeine sensitivity) | Moderate | T allele predisposes to caffeine-induced anxiety / sleep disruption in low-habit consumers; small effect; modulated by habituation. |
| **ALDH2 rs671** (alcohol flushing) | Strong in East Asians | rs671*A: catastrophically reduced ALDH2 enzyme; protective against alcohol dependence, dramatically increased esophageal cancer risk with drinking. Near-zero MAF outside East Asia. |
| **ADH1B rs1229984** (alcohol metabolism) | Strong | ADH1B*2: faster ADH, contributes to flushing in East Asians, also AD-protective. Different population frequencies and weaker phenotype mapping outside East Asia. |
| **APOE ε2/ε3/ε4** (rs429358 + rs7412) | Strong (AD risk); fraught | The note carries the disclosure framing: lifetime AD risk numbers, "no current preventive interventions" context, "this is fraught — consider whether you want to know" framing. The note IS the disclosure protocol. |
| **MTHFR C677T (rs1801133), A1298C (rs1801131)** | Skeptical framing required | ACMG 2013 explicitly recommended against routine MTHFR testing. The "MTHFR mutation" lay literature is largely pseudoscience. The note documents this so the agent has a consistent skeptical response when the user mentions a TikTok claim. |

**Genes to drop from the lifestyle track**:

- **PER3 VNTR / CLOCK** (chronotype): repeated non-replication in independent cohorts; additionally, VNTRs are unreliably called from short-read 30× WGS, so even the genotype call may be wrong.
- **ACTN3 R577X** (athletic performance): elite-cohort meta-analyses show OR ~1.27–1.40 for power vs endurance athletes, but this does not translate to recreational performance and does not produce useful individual-level prediction. Including it invites user disappointment after spurious advice.

**N-of-1 experiment framing** (the project plan's "falsifiable experiments" idea): defensible only for outcomes with within-individual variability and short washout windows — caffeine sleep latency, alcohol flushing, post-prandial glucose response. Not defensible for training response, body composition, or long-horizon weight outcomes. Constrain the agent's "try this for two weeks" suggestions accordingly.

---

## What to defer until the use case arises

Each of the following is a one- to two-day add when its trigger condition is met. Defer-by-default is the right discipline for a single-user POC; building infrastructure for hypothetical needs ages poorly.

| Feature | Add when |
|---|---|
| HLA typing (T1K) | User asks about abacavir (HLA-B\*57:01), carbamazepine (HLA-B\*15:02 / HLA-A\*31:01), celiac (HLA-DQ2/DQ8), or ankylosing spondylitis (HLA-B\*27) |
| Manta / structural variant calling | User asks about a known familial deletion. Note: short-read single-sample SV calling has high false-positive rates anyway; the honest answer is often "request MLPA / clinical-grade testing." |
| ExpansionHunter / repeat expansions | User asks about Huntington's, ALS/FTD (C9orf72), Friedreich's (FXN), spinocerebellar ataxias, or Fragile X. Use targeted-catalog mode (~30 min/genome). |
| mt-aware mtDNA caller (mity) | User asks an mtDNA-specific question. Until then the agent can be honest: "mtDNA is not well-handled by the standard pipeline; results are limited." |
| Population-specific reference (SweGen for Sweden, GenomeAsia for Asian, etc.) | Run somalier ancestry inference once. If the user's genetic ancestry is concentrated in a population with a public reference panel, add it. Otherwise gnomAD per-population AF is fine. |
| Schema-enforced citation stripping (server-side removes citations the LLM made up) | LLM is observed hallucinating PMIDs in practice |
| Tool-use forcing (LLM cannot answer without calling a tool) | LLM is observed answering clinical/lifestyle questions from parametric memory |
| Deterministic server-rendered findings card | LLM is observed dropping schema fields when summarizing into prose |
| Phrasing templates for high-risk categories | A specific category of response repeatedly produces wrong framing |
| Automated ACMG/AMP rule classifier (InterVar, Genebe) | The agent's natural ACMG composition produces wrong P/LP calls in observed conversations |
| Eval harness with synthetic test cases | A regression breaks something twice |
| Additional PRS traits beyond the initial 3 | User asks about a trait not yet in the panel |
| Quarterly automated reanalysis | A ClinVar release lands that the user actually wants reprocessed |
| OMIM, ClinGen Gene-Disease Validity, dbNSFP, MaxEntScan, UTRannotator vcfanno sources | The agent's responses visibly need richer evidence in a specific category |

---

## Concrete amendments to the MVP plan

The existing 7-phase MVP plan (`docs/plans/active/mvp/`) needs targeted changes in three phases:

**Phase 2 (host CLI: ingest + reference fetch + minimal derived store)**:
- Add `bcftools stats` at ingest; dump output to `manifest.json`. Eyeball Ts/Tv (~2.0–2.1 genome-wide, ~3.0 in coding) as a quick sanity check.
- Add `mosdepth` against the BAM/CRAM; materialize per-gene mean coverage into the derived store as a single table.

**Phase 4 (annotate)**:
- Replace SnpEff with VEP + LOFTEE + AlphaMissense + SpliceAI plugins.
- Pin MANE Select as the reporting transcript.
- Add vcfanno for ClinVar (latest release) and gnomAD v4 with per-population AF.
- Schema additions: zygosity, depth (DP), allele balance, FILTER, ClinVar classification + review status, gnomAD popmax and per-ancestry AFs, gene LOEUF, MANE Select HGVSc and HGVSp, AlphaMissense score + class, SpliceAI max delta, LOFTEE high-confidence flag.

**Phase 5 (host service + plugin)**:
- Add `genomeclaw_gene(gene)` tool. Returns: top user variants in the gene, gene LOEUF, OMIM disease + inheritance, mean coverage from the user's BAM.
- Existing four tools (`genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`) stay as planned.

**Phase 6 (findings + evidence + lifestyle support)**:
- Add Cyrius for CYP2D6 (BAM/CRAM-side); feed diplotype into PharmCAT's outside-call interface.
- Add `pgsc_calc` for 3 PRS traits (CAD, T2D, breast or prostate cancer) with continuous-ancestry normalization.
- Add `genomeclaw_pgs(trait)` tool.
- Create `curated_notes/` directory with one markdown file per lifestyle gene in the shortlist (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR) plus `hard-genes.md` for the systematic-blind-spot caveat. `genomeclaw_evidence` resolves `gene_note:<gene>` and `topic:hard-genes` references.
- Drop PER3, CLOCK, and ACTN3 from the lifestyle track entirely. Don't ship them.

**Phase 7 (E2E demo + invariant sweep)**:
- Run the 9 user-stories conversations end-to-end against the live system. Eyeball the outputs. Fix what's broken.
- Defer a synthetic eval harness until specific failure patterns emerge.

Phases 1 and 3 are unaffected.

---

## Design principles for the POC

A few principles that keep the project from drifting toward over-engineering:

- **Trust the user.** They are technically capable, sophisticated, and have explicitly framed this as personal exploration with clinician handoff for anything actionable. They don't need clinical-product guardrails. They will read between the lines, check sources, and ask follow-up questions.
- **Trust the LLM more than instinct suggests.** Modern frontier models with clear system prompts and structured tool returns produce reasonable, calibrated output. Architectural mitigations (tool-use forcing, citation stripping, deterministic findings cards) are real safeguards for regulated products and for systems with adversarial users — neither applies here. Build them when observed failure justifies them, not before.
- **Add infrastructure when something fails, not when you imagine it might.** YAGNI applies to safety scaffolding too.
- **Curated markdown notes beat structured taxonomies for one user.** The user is the curator; the agent is the reader. This pattern is uniquely well-suited to single-user systems and uniquely poorly-suited to multi-user systems. Lean into it.
- **Two changes are non-negotiable.** VEP + LOFTEE + AlphaMissense + SpliceAI for annotation, and Cyrius for CYP2D6. These prevent failure modes that *are* catastrophic — wrong PVS1 classifications and wrong PGx diplotypes — and that the existing plan would otherwise hit. Everything else is incremental polish.
- **Defer-by-default.** Most features only matter when the user asks the relevant question. Build the trigger-driven add list above, and let the user's actual usage drive the roadmap.

The existing GenomeClaw architecture — host-side heavy pipeline, sandboxed agent, minimal-sufficient JSON to the LLM, curated evidence retrieval — is well-shaped for this. The recommendations above are targeted enrichments, not a redesign. A v0 that makes the two non-negotiable annotation and PGx changes, adds coverage-aware gene-level queries, ships PRS for a small initial trait panel, and puts lifestyle calibration into curated notes the user can edit is a feasible POC that prevents the catastrophic failure modes without building infrastructure for problems that haven't actually surfaced yet.

---

(End of archive.)

# Phase 3: Grand plan + user stories

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Propagate the now-landed spec (Phase 1) and architecture (Phase 2) decisions into the strategic and UX-facing reference docs: `docs/reference/grand-plan.md` (Themes B, G, H; Strategic Constraints; Decisions tables) and `docs/reference/user-stories.md` (Story 1 ingest sketch; Story 3 BRCA1 + coverage; Story 4 Cyrius/CYP2D6 extension; Story 9 curated-note retrieval; new short PRS story; gap-analysis updates). After Phase 3, the strategic posture and the user-facing demonstration of the new tools and curated-notes lifestyle approach are internally consistent against the recommendations report. Phase 4 (MVP development-plan + phase-2) inherits a stable doc set.

## Scope Boundaries

- **In scope**:
  - `docs/reference/grand-plan.md` — Theme B, Theme G, Theme H reframe; new Strategic Constraint "Defer-by-default"; Decisions Taken / Decisions Deferred tables refreshed.
  - `docs/reference/user-stories.md` — Stories 1, 3, 4, 9 updates; new short PRS story or sub-story; gap-analysis section updates (mark resolved items, add deferred-by-Q10 items).
  - `docs/plans/active/poc-pipeline-recommendations/work-notes.md` — Phase 3 progress block, doc-checks RED → GREEN, sections-touched summary.
  - `docs/plans/active/poc-pipeline-recommendations/phases/phase-4.md` — authored at end of Phase 3 (MVP development-plan + phase-2 detailed plan).
- **Out of scope**:
  - `docs/plans/active/mvp/*` — Phase 4.
  - `docs/reference/architecture.md` — Phase 2 (already landed).
  - `docs/reference/INVARIANTS.md` — Phase 2 (already landed).
  - Any code under `packages/`. Strictly no code in this phase.

## Invariants Enforced in This Phase

- **INV-C001** — User-stories Story 9 demonstrates the curated-notes lifestyle track in action; gap analysis is updated to reflect the resolution. Story 4 (CYP2D6 extension) demonstrates the clinical-track escalation marker pattern with a Cyrius-derived diplotype. Grand-plan Theme H reframes the lifestyle track around `curated_notes/`.
- **INV-E001** — User-stories Story 9 explicitly cites `gene_note:CYP1A2` as the evidence reference; the agent does not improvise lifestyle framing. Grand-plan Theme E gains a clinician-handoff sub-bullet (per the existing `user-stories.md` § Plan change-set 4 G3 item).
- **INV-P002** — User-stories new PRS story demonstrates the minimal-sufficient response shape (percentile + ancestry-calibration string, no raw PGS variant lists).
- **INV-P001 / INV-D001 / INV-D002 / INV-R001** — Grand-plan Theme B (false-reassurance prevention) and Theme G expansion (Cyrius + PRS) reaffirm host-side discipline; no weakening.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Doc-Checks

**Doc-check cases**:

**Grand plan (`docs/reference/grand-plan.md`)**:

1. `check_gp_theme_b_vep_stack` — `grep -A20 "^### Theme B" docs/reference/grand-plan.md` mentions `VEP`, `LOFTEE`, `AlphaMissense`, `SpliceAI`, `vcfanno`, `MANE Select` (after edit). RED: only `SnpEff vs. VEP vs. vcfanno` is currently listed as an open question.
2. `check_gp_theme_b_false_reassurance` — `grep -A20 "^### Theme B" docs/reference/grand-plan.md` mentions "false reassurance" or "coverage-aware" (after edit). RED: 0.
3. `check_gp_theme_g_cyrius` — `grep -A15 "^### Theme G" docs/reference/grand-plan.md` mentions `Cyrius` (after edit). RED: 0.
4. `check_gp_theme_g_pgs` — `grep -A15 "^### Theme G" docs/reference/grand-plan.md` mentions `pgsc_calc` or `polygenic risk` (after edit). RED: 0.
5. `check_gp_theme_h_curated_notes` — `grep -A20 "^### Theme H" docs/reference/grand-plan.md` mentions `curated_notes` (after edit). RED: 0.
6. `check_gp_theme_h_per3_clock_actn3_dropped` — `grep -A30 "^### Theme H" docs/reference/grand-plan.md` mentions "dropped" or "not in the curated set" for PER3/CLOCK/ACTN3 (after edit). RED: PER3/CLOCK/ACTN3 listed as in-scope examples.
7. `check_gp_strategic_defer_by_default` — `grep "Defer-by-default" docs/reference/grand-plan.md` matches in the Strategic Constraints section (after edit). RED: 0.
8. `check_gp_decisions_taken_vep_cyrius_pgsc` — Decisions Taken table contains rows mentioning VEP, Cyrius, mosdepth, pgsc_calc, curated_notes (after edit). RED: 0 (none currently in Decisions Taken).
9. `check_gp_decisions_deferred_hla_sv_repeats` — Decisions Deferred table mentions HLA, structural variants, repeat expansions, mtDNA, eval harness (after edit). RED: imputation, GUI, multi-genome, federation, default annotator, report formats, embedding model, plugin JSON return, nodeHostCommands, repo split (some unrelated to Q10 list; the Q10 items are 0 currently).

**User stories (`docs/reference/user-stories.md`)**:

10. `check_us_story1_new_pipeline_steps` — Story 1 ingest sketch mentions `bcftools stats`, `mosdepth`, `Cyrius`, `pgsc_calc` (after edit). RED: 0 across these four tools.
11. `check_us_story3_genomeclaw_gene` — Story 3 mentions `genomeclaw_gene` (after edit). RED: 0.
12. `check_us_story4_cyp2d6_cyrius` — Story 4 mentions a CYP2D6 sub-question demonstrating Cyrius diplotype (after edit). RED: only CYP2C19 is mentioned in Story 4.
13. `check_us_story9_gene_note_cyp1a2` — Story 9 references `genomeclaw_evidence(ref="gene_note:CYP1A2")` (after edit). RED: 0.
14. `check_us_story9_per3_clock_decline` — Story 9's PER3/CLOCK follow-up is gracefully declined (after edit). RED: Story 9 currently includes PER3/CLOCK as a successful follow-up.
15. `check_us_prs_story_exists` — a PRS story or sub-story exercising `genomeclaw_pgs` exists (after edit). RED: 0.
16. `check_us_gap_analysis_updates` — gap-analysis section has new ✅ markers for items resolved by this plan (e.g., A1 active-run resolution, A11 evidence_quality field structure — actually A11 is partially resolved by the curated-notes pivot; need to check). RED: existing ✅ markers as of MVP Q1–Q4 stand.

**Procedure**:

```bash
echo "=== Grand plan RED ==="
for term in "VEP" "LOFTEE" "AlphaMissense" "SpliceAI" "Cyrius" "pgsc_calc" "curated_notes" \
            "Defer-by-default" "false reassurance" "coverage-aware"; do
  printf "%-25s " "$term:"; grep -c "$term" docs/reference/grand-plan.md
done

echo "=== User stories RED ==="
for term in "bcftools stats" "mosdepth" "Cyrius" "pgsc_calc" "genomeclaw_gene" "genomeclaw_pgs" \
            "gene_note:CYP1A2" "topic:hard-genes" "CYP2D6"; do
  printf "%-25s " "$term:"; grep -c "$term" docs/reference/user-stories.md
done
```

After running, paste the RED state into `work-notes.md` Phase 3 block.

### Step 3.2 — GREEN: Edit `grand-plan.md` and `user-stories.md`

The edits are larger than Phase 2's because user-stories.md narrative paragraphs are substantive prose; updating Story 4 with a Cyrius sub-conversation and Story 9 with curated-note retrieval requires real writing, not just structural-list updates.

Suggested edit sequence (~12 separate `Edit` calls):

**Grand plan edits** (G1–G6):

**Edit G1 — Theme B (Reproducible annotation pipelines).** Replace the existing Theme B body to reflect Q5/Q7 decisions:
- Bullet-list entries gain "VEP + LOFTEE + AlphaMissense + SpliceAI for effect/pathogenicity prediction" and "vcfanno for ClinVar + gnomAD overlays" and "MANE Select transcript pinning."
- A new bullet: "False-reassurance prevention via coverage-aware queries — `mosdepth` at ingest materializing per-gene mean coverage; `genomeclaw_gene` surface exposes `mean_coverage` and `low_coverage_exons`."
- "Open" sub-section: the "which annotator" question is now closed (per MVP spec Q5).

**Edit G2 — Theme G (Pharmacogenomics & specialized panels).** Expand to cover Cyrius + PRS:
- Bullet "PharmCAT integration for actionable pharmacogenomic haplotypes" gains "with **Cyrius** outside-call for CYP2D6 (per MVP spec Q6)."
- New bullet "**PRS via `pgsc_calc`** for an initial three-trait panel (CAD, T2D, breast or prostate); ancestry-normalized; non-actionable findings classification (per Q8)."
- "Gates" sub-section: still "highest clinical-adjacency surface area; depends on Themes B–E being solid."
- "Open" sub-section: which PharmCAT outputs to surface — partially closed by Q6's Cyrius decision.

**Edit G3 — Theme H (Lifestyle and wellbeing optimization).** Reframe around curated-notes:
- The intro paragraph rewrites to name `reference/curated_notes/<gene>.md` as the calibration mechanism.
- Bullets enumerate the seven shipped gene notes: LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR. Plus `topic:hard-genes` companion.
- A new bullet: "**Genes dropped from the lifestyle track**: PER3, CLOCK, ACTN3 — non-replication, unreliable VNTR genotyping on short-read 30× WGS, non-transferring elite-cohort effects (per MVP spec Q9)."
- "Gates" sub-section: still "depends on Themes B–D being solid."
- "Open" sub-section: which lifestyle finding categories ship first — closed.

**Edit G4 — Theme E (Cautious reporting).** Add a clinician-handoff bullet (per the existing `user-stories.md` § Plan change-set 4 G3 follow-up):
- New bullet: "**Clinician-handoff artifacts** — research-grade text the user can forward verbatim to a clinician (per Story 4 / Story 6). Generated by the agent from primitives, not by a host-service report endpoint (per MVP spec Q3)."

**Edit G5 — Strategic Constraints.** Insert a new constraint **"Defer-by-default"** between two existing constraints (after "Wrappers over rewrites" makes sense thematically):

```markdown
### Defer-by-default

The POC ships a deliberately small surface area; each deferred feature has an explicit trigger condition. Building infrastructure for hypothetical needs ages poorly; the bar is observed need, not anticipated need (per MVP spec Q10). This applies equally to safety scaffolding (citation stripping, tool-use forcing, deterministic findings cards) — modern frontier models with clear system prompts and structured tool returns produce reasonable, calibrated output on this stack, and the architectural mitigations are real safeguards for regulated products and adversarial users, neither of which applies here.

The full trigger list lives in the Decisions Deferred table below.
```

**Edit G6 — Decisions Taken / Decisions Deferred tables.** Add new rows:
- Decisions Taken: rows for VEP stack, Cyrius for CYP2D6, mosdepth coverage-aware queries, `pgsc_calc` PRS panel, curated_notes/ lifestyle calibration.
- Decisions Deferred: HLA typing (T1K), Manta SV, ExpansionHunter repeats, mt-aware mtDNA, population-specific reference panels, automated ACMG/AMP rule classifier, eval harness, additional PRS traits, citation stripping, tool-use forcing, deterministic findings card, phrasing templates, additional vcfanno sources, quarterly automated reanalysis. Each row's "Revisit when" cell carries the trigger condition from MVP spec Q10's table.

**User stories edits** (U1–U6):

**Edit U1 — Story 1 (Initial setup).** Update the ingest CLI sketch to reflect the new pipeline. The user runs `genomeclaw-prep ingest`, which now invokes `bcftools stats` + `mosdepth` + `Cyrius` + the VEP stack + `pgsc_calc` (the latter via a separate `pgs-compute` subcommand the user runs after the main ingest). The CLI's "Run complete" output enumerates the new derived artifacts (`coverage_qc`, `pgs_scores`, `cyp2d6_diplotype.json`).

**Edit U2 — Story 3 (BRCA1 query).** The agent's reply now includes coverage from `genomeclaw_gene(gene="BRCA1")`. Specifically, after the ClinVar lookup, the agent makes a second tool call to `genomeclaw_gene` and surfaces the `mean_coverage` (e.g., "28×") and `low_coverage_exons` (e.g., "exon 11 averaged 4×, below the threshold for confident calls"). The "could it be hiding in a region the WGS misses?" follow-up becomes more concrete because the agent already has the answer.

**Edit U3 — Story 4 (Clopidogrel).** Extend with a CYP2D6 sub-question. After the user's clopidogrel exchange wraps, the user follows up: "what about codeine — same story?" The agent calls `genomeclaw_findings category=pgx genes=["CYP2D6"]` (the host service resolves this against the Cyrius-derived diplotype) and surfaces the user's CYP2D6 phenotype with a CPIC-guideline reference. The agent's research-grade handoff paragraph for the GP / cardiologist now mentions both CYP2C19 and CYP2D6 if both are relevant.

**Edit U4 — Story 9 (Caffeine).** Update the agent's response to retrieve `genomeclaw_evidence(ref="gene_note:CYP1A2")` and compose the answer from the user's CYP1A2 variant call + the curated note's framing. The note's voice (the project owner's calibrated take) shows through in the agent's response: "AA = fast, CC = slow, AC heterozygote = intermediate but with high variance" framing surfaces directly. The PER3/CLOCK/ADORA2A follow-up:
- The agent's response declines PER3 and CLOCK gracefully ("not in our curated set; PER3 VNTRs are unreliable on short-read 30× WGS and the chronotype literature has repeated non-replications — I won't speculate based on the genotype call").
- The agent does respond on ADORA2A (which **is** in the curated set per Q9), retrieving `genomeclaw_evidence(ref="gene_note:ADORA2A")`.

**Edit U5 — New short PRS story or sub-story.** Author a new Story 10 (or appended sub-story under Story 6's preventive-medicine sweep). The user asks "what's my CAD risk?"; the agent calls `genomeclaw_pgs(trait="CAD")`; the response surfaces `percentile_in_user_ancestry`, `raw_score`, `source_pgs_id`, `study_population`, `calibration_warning`. The agent's prose surfaces the calibration warning if the user's continuous-ancestry estimate falls in a sparse-training region. The story exercises the minimal-sufficient response shape and demonstrates that PRS findings carry `category: clinical-non-actionable` (no escalation marker).

**Edit U6 — Surfaced design gaps section.** Update the gap-analysis at the end of `user-stories.md`:
- A1 (active-run resolution) — was "missing"; now ✅ Resolved by architecture.md update + `CURRENT` symlink (already partly addressed by MVP Phase 2 deliverables).
- A2 (annotation-source versions on `/v1/health`) — already addressed by previous architecture work; mark ✅ if not already.
- A6 (evidence broader than variant-bound) — ✅ Resolved by MVP spec Q9 + architecture.md evidence-resolver clarification.
- A11 (`evidence_quality` field) — partially resolved; the field stands but is no longer the primary surface (per Q9). Annotate accordingly.
- New gap entries for Q10's deferred items (or just point at grand-plan's Decisions Deferred table; don't duplicate).
- I1 (INV-C001 lifestyle track) — ✅ Resolved by INVARIANTS v1.5.

### Step 3.3 — REFACTOR

With the doc-checks GREEN:

- Read `grand-plan.md` end-to-end. Confirm Themes B / E / G / H all read coherently with the new content; Strategic Constraints "Defer-by-default" sits naturally; Decisions tables don't duplicate or contradict MVP spec Q-blocks.
- Read `user-stories.md` end-to-end. Confirm the four updated stories read coherently as user-facing narratives; the new PRS story reads naturally; gap-analysis is current.
- Cross-doc check: every "(per Q5)" / "(per Q6)" / etc. reference points at the right MVP spec block; every `gene_note:<gene>` reference matches the architecture.md evidence-resolver shape.
- Re-run all doc-checks (Step 3.1); capture GREEN output in `work-notes.md`.

---

## Implementation Details

### Edit ordering

Grand-plan edits first (strategic posture), then user-stories edits (the UX narratives that *implement* the strategic posture). User-stories edits often reference grand-plan themes (e.g., "Theme H curated_notes/"); doing grand-plan first keeps those references accurate.

### Cross-reference syntax

Grand-plan and user-stories are pure markdown reference docs, not code. The "(per MVP spec Q7)" plain-text shorthand is preferred over full-anchor markdown links — anchors slugify unpredictably, and the doc reader can navigate to MVP spec via the existing inter-doc link in the document header.

### Edge Cases to Handle

- **Story 9 currently includes a PER3/CLOCK successful response** — the agent gives detailed PER3 VNTR and CLOCK genotype framing. The Edit U4 rewrite must remove that successful response and replace with a graceful decline. Don't accidentally leave orphaned references to PER3/CLOCK genotype values in the prose.
- **Grand-plan's Theme E** is updated by Edit G4. Don't duplicate the clinician-handoff bullet across Theme E and Theme G — Theme E owns the framing-and-rendering surface; Theme G owns the PGx finding category.
- **Decisions Taken / Decisions Deferred tables** in grand-plan have a specific markdown format. New rows must match the existing column structure: `| Decision | Reason |` for Taken, `| Deferred decision | Revisit when |` for Deferred.
- **Story numbering** in `user-stories.md` is sequential; if Edit U5 adds a Story 10, the existing "Story 8" / "Story 9" should not be renumbered. Append Story 10.

### Error Handling

- If a multi-line `Edit` fails because the surrounding context shifted during earlier edits, re-read the affected region and retry.
- Story 9 has substantial prose; Edit U4 may need to be split into 2–3 smaller `Edit` calls (initial response, ADORA2A continuation, PER3/CLOCK decline).

### Privacy / Egress Notes

- Phase 3 documents the PGS Catalog egress in grand-plan and the PRS user story but does not introduce it at runtime (no code lands).
- The new PRS story (Edit U5) demonstrates the minimal-sufficient response shape (no raw PGS variant lists); this is the narrative-layer enforcement of `INV-P002`.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/reference/grand-plan.md` | MODIFY | Themes B / E / G / H updated; Strategic Constraint "Defer-by-default" added; Decisions Taken / Decisions Deferred tables refreshed. |
| `docs/reference/user-stories.md` | MODIFY | Stories 1, 3, 4, 9 updated; new Story 10 (PRS) added; gap-analysis updated. |
| `docs/plans/active/poc-pipeline-recommendations/work-notes.md` | MODIFY (append) | Phase 3 progress block, doc-checks RED → GREEN, sections-touched summary, cross-doc consistency review. |
| `docs/plans/active/poc-pipeline-recommendations/phases/phase-4.md` | CREATE | At end of Phase 3, author Phase 4's detailed plan (MVP development-plan + phase-2). |

---

## Verification

```bash
# From repo root, after edits land

echo "=== Grand plan ==="
grep -A20 "^### Theme B" docs/reference/grand-plan.md | grep -E "VEP|LOFTEE|AlphaMissense|SpliceAI|MANE|coverage-aware|false reassurance"
grep -A15 "^### Theme G" docs/reference/grand-plan.md | grep -E "Cyrius|pgsc_calc|polygenic"
grep -A20 "^### Theme H" docs/reference/grand-plan.md | grep -E "curated_notes|dropped|PER3"
grep -c "Defer-by-default" docs/reference/grand-plan.md  # Expected: 2+ (Strategic Constraints + Decisions table)

echo "=== User stories ==="
for term in "bcftools stats" "mosdepth" "Cyrius" "pgsc_calc" "genomeclaw_gene" "genomeclaw_pgs" \
            "gene_note:CYP1A2" "topic:hard-genes" "CYP2D6"; do
  printf "%-25s " "$term:"; grep -c "$term" docs/reference/user-stories.md
done

echo "=== Story 9 PER3/CLOCK decline ==="
grep -B2 -A5 "PER3" docs/reference/user-stories.md | head -30
# Should show graceful decline language, not successful genotype response.
```

Final reading-test:
- Re-read `grand-plan.md` end-to-end; confirm "Defer-by-default" reads naturally as a Strategic Constraint and Themes B/G/H cohere.
- Re-read `user-stories.md` end-to-end; confirm Stories 1/3/4/9 + new PRS story flow as user-facing narratives.
- Cross-doc check: tool count "six" appears in grand-plan and user-stories (both reference the architecture.md tool table).

---

## Completion Criteria

- [ ] All 16 doc-checks (Step 3.1) pass GREEN after edits.
- [ ] Final reading-test: `grand-plan.md` and `user-stories.md` both read coherently end-to-end.
- [ ] No reference doc other than `grand-plan.md` and `user-stories.md` is touched.
- [ ] No `mvp/*` doc, no code under `packages/` is touched.
- [ ] `work-notes.md` Phase 3 block captures: RED output, GREEN output, sections-touched summary, cross-doc consistency review.
- [ ] Phase 3 status set to **Complete** in [development-plan.md](../development-plan.md) Progress Tracking table.
- [ ] [phases/phase-4.md](phase-4.md) of *this* plan is authored before Phase 3 closes (MVP development-plan + phase-2 detailed plan).

# Phase 4: MVP development-plan + phase-2

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Close the loop: propagate the now-landed spec / INVARIANTS / architecture / grand-plan / user-stories decisions into the **MVP development-plan** and **MVP phase-2** documents — the artifacts that will guide implementers when MVP work resumes. After Phase 4: `mvp/development-plan.md` Phase Overview reads "6 tools" not "4"; Phase 4/5/6 inline summaries name the new tools, the new derived tables, and the curated-notes evidence resolver; Schema/Provenance Impact and Privacy & Egress Impact sections are current. `mvp/phases/phase-2.md` gains `bcftools stats` + `mosdepth` deliverables and three new test cases (Ts/Tv sanity, per-gene coverage table populated, BAM unchanged after `mosdepth`). `mvp/phases/phase-1.md` is reviewed and confirmed unchanged.

This is the last phase of *this* plan. After Phase 4 closes, the POC-pipeline-recommendations plan moves to `docs/plans/completed/` and the MVP plan inherits a fully aligned doc set for its remaining phases (3 through 7).

## Scope Boundaries

- **In scope**:
  - `docs/plans/active/mvp/development-plan.md` — Summary, Critical Invariants, Current State Analysis (Files to Modify / Create tables), Solution Design (Key Design Decisions, Schema/Provenance Impact, Privacy & Egress Impact), Phase Overview table, Phase 4 / 5 / 6 inline summaries, Testing Strategy (no major changes — already correct), Documentation Updates, Open Risks & Follow-ups.
  - `docs/plans/active/mvp/phases/phase-2.md` — Objective intro, Scope Boundaries, Invariants Enforced, TDD Steps test list (cases 19–21), Implementation Details (subsections for `bcftools stats` and `mosdepth`), Files table, Verification commands, Completion Criteria.
  - `docs/plans/active/poc-pipeline-recommendations/work-notes.md` — Phase 4 progress block, doc-checks RED → GREEN, sections-touched summary, cross-phase coherence review.
- **Confirmed unchanged**:
  - `docs/plans/active/mvp/phases/phase-1.md` — foundations only (repo scaffolding, package skeleton, smoke test). None of the recommendations affect Phase 1's scope. Confirmation captured in `work-notes.md`.
- **Out of scope**:
  - `docs/plans/active/mvp/phases/phase-3.md` through `phase-7.md` — these will be authored by their predecessor's exit gate per the existing planning protocol; this plan ensures `development-plan.md` Phase 4/5/6 inline summaries carry enough delta context for the future authors.
  - All reference docs (`docs/reference/*`) — Phase 1/2/3 covered them.
  - All code under `packages/`. Strictly no code in this phase.

## Invariants Enforced in This Phase

This phase edits MVP planning docs; the invariants it enforces are **propagated forward** from the now-canonical spec / INVARIANTS / architecture into the operational plan that implementers will follow.

- **INV-D001** — Phase 2 test case 21 (`test_invD001_bam_unchanged_after_mosdepth`) is added by name in `mvp/phases/phase-2.md`; `mosdepth` invocations are configured to read-only.
- **INV-R001** — Phase 2 test case 19 confirms `bcftools stats` summary written into `manifest.json` under `qc.bcftools_stats` with sane Ts/Tv ratio; case 20 confirms the `coverage_qc` table inherits the seven canonical provenance columns.
- **INV-D002** — `mosdepth`, `Cyrius`, `bcftools stats`, `pgsc_calc` are documented in `mvp/development-plan.md` as host-side; the sandbox image's `INV-D002` smoke test (already specified in MVP Phase 5) covers the absence of these binaries.
- **INV-P001 / INV-P002** — `mvp/development-plan.md` Privacy & Egress Impact section documents the PGS Catalog fetch as a deliberate host-side opt-in; the existing default-config integration tests in Phase 5/6/7 inherit the discipline without modification.
- **INV-C001** — `mvp/development-plan.md` Phase 6 inline summary names `reference/curated_notes/` as the v0 lifestyle calibration surface and the seven gene shortlist; the `gene_note:<gene>` evidence resolver is named as a Phase 6 deliverable.

---

## TDD Steps

### Step 4.1 — RED: Write Failing Doc-Checks

**Doc-check cases**:

**MVP development-plan (`docs/plans/active/mvp/development-plan.md`)**:

1. `check_dp_phase_overview_six_tools` — the Phase Overview table or Solution Design section mentions tool count "6" (after edit). RED: 4-tool descriptions.
2. `check_dp_phase4_vep_stack` — Phase 4 inline summary (description in Phase Overview + the inline section) mentions VEP, LOFTEE, AlphaMissense, SpliceAI, vcfanno, MANE Select (after edit). RED: SnpEff + SnpSift named.
3. `check_dp_phase5_genomeclaw_gene` — Phase 5 inline summary mentions `genomeclaw_gene` (after edit). RED: 0.
4. `check_dp_phase6_cyrius_pgsc_curated_notes` — Phase 6 inline summary mentions Cyrius, `pgsc_calc`, `genomeclaw_pgs`, curated_notes (after edit). RED: 0.
5. `check_dp_schema_impact_new_columns` — Schema/Provenance Impact section enumerates MANE Select HGVSc/HGVSp, AlphaMissense score+class, SpliceAI max delta, LOFTEE flag, gnomAD per-ancestry AFs, gene LOEUF, `coverage_qc` table, `pgs_scores` table (after edit). RED: only the existing "Schema v0.1" sentence.
6. `check_dp_privacy_egress_pgs_catalog` — Privacy & Egress Impact section mentions PGS Catalog fetch (after edit). RED: 0.
7. `check_dp_phase2_deliverables_count` — Phase 2 inline summary mentions `bcftools stats` and `mosdepth` (after edit). RED: 0.
8. `check_dp_open_risks_alphamissense_spliceai` — Open Risks & Follow-ups section mentions AlphaMissense and SpliceAI dataset sizes / personal-host budget (after edit). RED: 0.

**MVP phase-2 (`docs/plans/active/mvp/phases/phase-2.md`)**:

9. `check_p2_deliverables_5_6` — Deliverables 5 (`bcftools stats`) and 6 (`mosdepth`) listed by name (after edit). RED: deliverables list ends at item 4 (`CURRENT` symlink semantics).
10. `check_p2_test_case_19` — `test_invR001_bcftools_stats_in_manifest` listed in TDD test cases (after edit). RED: 0; test cases end at 18.
11. `check_p2_test_case_20` — `test_coverage_qc_table_populated` listed in TDD test cases (after edit). RED: 0.
12. `check_p2_test_case_21` — `test_invD001_bam_unchanged_after_mosdepth` listed in TDD test cases (after edit). RED: 0.
13. `check_p2_files_table_mosdepth_module` — Files table contains `prep/_mosdepth.py` (or equivalent) and `prep/_bcftools_stats.py` (after edit). RED: 0.
14. `check_p2_fixtures_bam` — Fixtures section mentions a `tests/fixtures/tiny.bam` and a `.bai` (after edit). RED: only VCF fixtures listed.
15. `check_p2_invariants_in_phase` — Invariants Enforced in This Phase section mentions test-case anchors for cases 19–21 (after edit). RED: only INV-D001 + INV-R001 with the original 18-case scope.

**Phase-1 unchanged check**:

16. `check_p1_unchanged` — `git diff --stat docs/plans/active/mvp/phases/phase-1.md` shows zero lines changed by this phase (RED == GREEN; the file is not modified). This is verified by inspection, not edited.

**Procedure**:

```bash
# RED — capture pre-edit state
echo "=== MVP dev-plan RED ==="
for term in "VEP" "LOFTEE" "AlphaMissense" "SpliceAI" "vcfanno" "Cyrius" "pgsc_calc" \
            "mosdepth" "genomeclaw_gene" "genomeclaw_pgs" "curated_notes" "PGS Catalog" \
            "MANE Select" "coverage_qc" "pgs_scores"; do
  printf "%-25s " "$term:"; grep -c "$term" docs/plans/active/mvp/development-plan.md
done

echo "=== MVP phase-2 RED ==="
for term in "bcftools stats" "mosdepth" "test_invR001_bcftools_stats_in_manifest" \
            "test_coverage_qc_table_populated" "test_invD001_bam_unchanged_after_mosdepth" \
            "_mosdepth" "tiny.bam"; do
  printf "%-50s " "$term:"; grep -c "$term" docs/plans/active/mvp/phases/phase-2.md
done

echo "=== MVP phase-1 unchanged ==="
git diff --stat docs/plans/active/mvp/phases/phase-1.md
# Expected: empty (no diff)
```

Capture the RED state in `work-notes.md` Phase 4 block.

### Step 4.2 — GREEN: Edit `mvp/development-plan.md` and `mvp/phases/phase-2.md`

Suggested edit sequence (~10 separate `Edit` calls):

**MVP development-plan edits** (D1–D6):

**Edit D1 — Summary + Critical Invariants**: tighten to mention the new tools where applicable (this is a one-paragraph touch; keep it small).

**Edit D2 — Current State Analysis Files-to-Modify table**: extend the Phase 5 row to mention TypeBox schemas for `genomeclaw_gene` / `genomeclaw_pgs`; the `policy-preset.yaml` row updated to mention the new endpoints in the GET path allowlist.

**Edit D3 — Solution Design Key Design Decisions**: Decision #3 ("**SnpEff as the default annotator for the MVP**") rewritten as **VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno** (per spec Q5). Decision #4 ("**One lifestyle finding for the MVP — *CYP1A2* / caffeine**") rewritten as the seven-gene shortlist via `reference/curated_notes/` (per spec Q9). Decision #5 (`CURRENT` symlink) preserved.

**Edit D4 — Solution Design Schema/Provenance Impact**: enumerate the new derived columns and tables. Schema version reserves `v0.2` for the Q5/Q7/Q8 additions.

**Edit D5 — Solution Design Privacy & Egress Impact**: add a bullet documenting the PGS Catalog fetch.

**Edit D6 — Phase Overview table + Phase 4 / 5 / 6 inline summaries**:
- Phase 4 description: "Host pipeline — annotate **(VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno)**" with new schema columns.
- Phase 5 description: "Host service + plugin wiring + sandbox image **(adds `genomeclaw_gene` 5th tool + `/v1/gene/{symbol}` endpoint)**".
- Phase 6 description: "Findings + evidence + report **(with lifestyle support via `reference/curated_notes/`; Cyrius CYP2D6 outside-call; `pgsc_calc` PRS panel; `genomeclaw_pgs` 6th tool)**".
- Tool count "4 → 6" in the Critical Invariants section + Phase 5 inline summary.

**MVP phase-2 edits** (P1–P4):

**Edit P1 — Objective + Scope Boundaries**: extend the Objective to mention `bcftools stats` summary into `manifest.json` and `mosdepth` materializing the `coverage_qc` table; In-scope list adds the two new deliverables; Out-of-scope list preserved (the new tools' downstream consumers — annotation, host service, plugin — stay out of scope for Phase 2).

**Edit P2 — Invariants Enforced**: extend the INV-D001 paragraph to mention BAM-immutability post-`mosdepth`; extend INV-R001 to mention `bcftools stats` versions in the manifest plus `coverage_qc` provenance columns.

**Edit P3 — TDD Step 2.1 test cases**: append three new cases:
```markdown
**Coverage + QC tests** (`tests/integration/` and `tests/invariants/`):

19. `test_invR001_bcftools_stats_in_manifest` — `manifest.json` has a `qc.bcftools_stats` block with `ts_tv_ratio`, `n_snps`, `n_indels`; values are within sane ranges for the fixture (Ts/Tv ~2.0–2.1 genome-wide, ~3.0 in coding for a real WGS; the synthetic fixture's expected ranges are documented inline).
20. `test_coverage_qc_table_populated` — after `ingest`, the derived store has a `coverage_qc` table with at least one row per gene in a small fixture-defined gene list (e.g., BRCA1, BRCA2, CYP2D6); `mean_depth` is a non-negative real; the seven canonical provenance columns are populated (`INV-R001`).
21. `test_invD001_bam_unchanged_after_mosdepth` — capture BAM SHA256 before `ingest`; rerun SHA256 after; assert equal. Same for the `.bai` index if present. (`INV-D001`.)
```

**Edit P4 — Implementation Details + Files table + Verification**:
- New subsections "bcftools stats summary" and "mosdepth coverage materialization" under Implementation Details, sketching the wrapper modules (`prep/_bcftools_stats.py`, `prep/_mosdepth.py`) and the `coverage_qc` table schema.
- Files table: add `prep/_bcftools_stats.py`, `prep/_mosdepth.py`, `tests/fixtures/tiny.bam`, `tests/fixtures/tiny.bam.bai`, `tests/integration/test_bcftools_stats.py`, `tests/integration/test_coverage_qc.py`, `tests/invariants/test_invD001_bam_unchanged.py`.
- Verification: extend the existing bash block with `mosdepth --version` and a sketch of the new tests' expected output.
- Completion Criteria: the existing "All 18 Phase 2 test cases pass" line bumps to "All 21 Phase 2 test cases pass".

### Step 4.3 — REFACTOR

With the doc-checks GREEN:

- Read `mvp/development-plan.md` end-to-end. Confirm the Phase Overview table, Critical Invariants, Solution Design, and Phase 4/5/6 inline summaries all read coherently with the recommendation report's changes.
- Read `mvp/phases/phase-2.md` end-to-end. Confirm Deliverables list flows from 1 (existing) → 6 (new); test case list flows from 1 → 21; Files table is current; Verification commands are runnable.
- Read `mvp/phases/phase-1.md`. Confirm by inspection that **no edits are needed** — the file is foundations-only and none of Q5–Q10 affects repo scaffolding / package skeleton / smoke test. Capture the confirmation in `work-notes.md`.
- Re-run all doc-checks; capture GREEN output in `work-notes.md`.

---

## Implementation Details

### Edit ordering

Development-plan edits first (the tactical blueprint), then phase-2.md edits (the immediate-next phase's TDD scaffold). Within each, work outermost-section to innermost-detail (Summary → Phase Overview → Solution Design subsections → Open Risks).

### Cross-reference syntax

MVP planning docs cite the spec's Q-blocks ("per Q5") and the POC-pipeline-recommendations plan as the source. After Phase 4 closes and the POC plan moves to `completed/`, the cross-reference paths should update — but Phase 4 doesn't pre-rewrite them; the move-to-completed step will update the path references then. This is fine because the active-plan path is stable until close.

### Phase-1 unchanged review

Phase 4's review of `mvp/phases/phase-1.md`:
- Phase 1's scope is "scaffolding only" — `pyproject.toml`, package skeleton (cli/prep/service/schemas), `genomeclaw-prep --help`, CI workflow, smoke tests. None of Q5–Q10 affects any of those.
- The smoke test categories list (`integration/`, `provenance/`, `determinism/`, `privacy/`, `evidence/`, `reports/`, `invariants/`) is the same scaffolding regardless of Q5–Q10.
- The `cli.py` placeholder subcommand list (`fetch`, `ingest`, `normalize`, `annotate`, `materialize`) does not need to be extended in Phase 1 — adding `cyp2d6-call` and `pgs-compute` happens in MVP Phase 6.
- Confirmation paragraph captured in `work-notes.md` Phase 4 block.

### Edge Cases to Handle

- **The `mvp/development-plan.md` Phase Overview table is fixed-width markdown**. Adding mentions of new tools in the Description column may push line widths; that's fine, markdown renderers wrap.
- **The Decisions Taken in `mvp/spec.md` Q5 cross-reference `mvp/development-plan.md` Phase 4**. Phase 4 of *this* plan must keep that cross-reference live by ensuring the Phase 4 inline summary remains structurally findable (the heading stays "Phase 4: Host pipeline — annotate" or similar).
- **`mvp/phases/phase-2.md` test cases are numbered 1–18 currently**. Cases 19–21 must not collide with renumbering elsewhere. The cases are appended; existing 1–18 stay verbatim.
- **`mvp/phases/phase-2.md` Verification block already runs `pytest`**. The new tests will be picked up by the existing `pytest -q` run; no new pytest invocation needed.

### Error Handling

- If an `Edit` to `mvp/development-plan.md` accidentally desynchronizes the Phase Overview table from the inline phase summaries, re-read both regions and reconcile.

### Privacy / Egress Notes

- The PGS Catalog fetch is documented but not introduced at runtime in this plan; MVP Phase 6 will introduce it.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/mvp/development-plan.md` | MODIFY | Phase Overview tool count + Phase 4/5/6 descriptions; Solution Design Key Design Decisions / Schema-Provenance / Privacy-Egress sections; Open Risks. |
| `docs/plans/active/mvp/phases/phase-2.md` | MODIFY | Deliverables 5/6; test cases 19/20/21; Implementation Details subsections; Files table; Verification + Completion Criteria. |
| `docs/plans/active/mvp/phases/phase-1.md` | UNCHANGED | Reviewed; confirmed unaffected by Q5–Q10. |
| `docs/plans/active/poc-pipeline-recommendations/work-notes.md` | MODIFY (append) | Phase 4 progress block, doc-checks RED → GREEN, Phase 1 unchanged-review, cross-phase coherence summary, plan-close marker. |

---

## Verification

```bash
# From repo root, after edits land

echo "=== MVP dev-plan ==="
for term in "VEP" "LOFTEE" "AlphaMissense" "SpliceAI" "Cyrius" "pgsc_calc" \
            "mosdepth" "genomeclaw_gene" "genomeclaw_pgs" "curated_notes" "PGS Catalog" \
            "MANE Select" "coverage_qc" "pgs_scores"; do
  printf "%-25s " "$term:"; grep -c "$term" docs/plans/active/mvp/development-plan.md
done

echo "=== MVP phase-2 ==="
for term in "bcftools stats" "mosdepth" "test_invR001_bcftools_stats_in_manifest" \
            "test_coverage_qc_table_populated" "test_invD001_bam_unchanged_after_mosdepth" \
            "_mosdepth" "_bcftools_stats" "tiny.bam"; do
  printf "%-50s " "$term:"; grep -c "$term" docs/plans/active/mvp/phases/phase-2.md
done

echo "=== MVP phase-1 unchanged ==="
git diff --stat docs/plans/active/mvp/phases/phase-1.md
# Expected: zero lines (file untouched).

echo "=== Cross-phase coherence ==="
echo "Tool count consistency (should all be 6 / six):"
grep -E "(six|6)\b.*(tool|plugin tool)" docs/plans/active/mvp/spec.md docs/reference/architecture.md docs/plans/active/mvp/development-plan.md | head -5

echo "VEP-stack naming consistency (should match across all 4 docs):"
grep -E "VEP \+ LOFTEE \+ AlphaMissense \+ SpliceAI \+ vcfanno" \
  docs/plans/active/mvp/spec.md docs/reference/architecture.md \
  docs/reference/grand-plan.md docs/plans/active/mvp/development-plan.md
```

Final reading-test:
- Re-read `mvp/development-plan.md` end-to-end; confirm all phase descriptions are current.
- Re-read `mvp/phases/phase-2.md` end-to-end; confirm 21 test cases flow logically and the new `bcftools stats` + `mosdepth` deliverables fit naturally.

---

## Completion Criteria

- [ ] All 16 doc-checks (Step 4.1) pass GREEN after edits (15 substantive checks + 1 unchanged-by-design check).
- [ ] Final reading-test: `mvp/development-plan.md` + `mvp/phases/phase-2.md` both read coherently end-to-end.
- [ ] `mvp/phases/phase-1.md` is confirmed unchanged (`git diff --stat` shows zero lines for that file).
- [ ] Cross-phase coherence checks pass: tool count "6" consistent across MVP spec / architecture.md / dev-plan; VEP-stack named identically across the four docs that mention it; "Defer-by-default" cited identically in grand-plan + MVP spec; curated_notes path consistent across spec / INVARIANTS / architecture / grand-plan / user-stories / dev-plan.
- [ ] No `docs/reference/*` doc, no other `mvp/*` doc, no code under `packages/` is touched.
- [ ] `work-notes.md` Phase 4 block captures: RED output, GREEN output, Phase 1 unchanged review, cross-phase coherence verification, plan-close marker.
- [ ] Phase 4 status set to **Complete** in [development-plan.md](../development-plan.md) Progress Tracking table.
- [ ] All four phases of the POC-pipeline-recommendations plan are marked Complete in the Progress Tracking table.
- [ ] **Plan move-to-completed is recommended but not executed by this phase**. The user (or a follow-up housekeeping step) moves `docs/plans/active/poc-pipeline-recommendations/` to `docs/plans/completed/poc-pipeline-recommendations/` after a final review. Phase 4's `work-notes.md` block leaves a clear "ready to close" marker.

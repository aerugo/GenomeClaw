# Development Plan — Coverage QC / gene-list BED bundling

**Status**: Active — drafted 2026-05-23
**Spec**: [spec.md](spec.md)
**Branch**: `main` (small phases; no separate feature branch)

## Summary

Three phases: pick the panel composition, bundle the BED + auto-engage on `pipeline ingest/run`, verify against the canonical run-dir + the agent's eyesight question. Estimated 4-6 hours of focused work. Closes the MVP Phase 7 AC8 carry-forward + makes the disease-area-discovery sysprompt's coverage-warning surface actually report real data.

## Critical Invariants to Respect

- **INV-D001** — CRAM read-only; mosdepth doesn't modify the source.
- **INV-R001** — every new `coverage_qc` row carries the seven provenance columns.
- **INV-T001** — mosdepth tool conventions stay pinned (existing `MosdepthConventions` + probe baseline).
- **INV-P001** — no new egress; mosdepth + panel BED are local.

## Proposed New Invariants

None.

## Current State Analysis

### What works today

- `prep/_mosdepth.py::run_mosdepth(...)` + `parse_regions_bed(...)`: invokes mosdepth + parses its per-region output into `(gene, mean_depth, low_coverage_exons)` rows.
- `prep/store.py::write_coverage_qc(rows, *, tag=...)`: writes rows with provenance.
- `prep/ingest.py::ingest(..., bam=..., bed=...)`: when both flags are given, runs the mosdepth pipeline + writes `coverage_qc`.
- `service/store.py::query_gene(...)`: joins variants + `coverage_qc`; returns `mean_depth` + `low_coverage_exons` to `/v1/gene/{symbol}`.
- `genomeclaw_gene` plugin tool reads the endpoint + surfaces both fields to the agent.

### What's missing

- No default panel BED ships with the toolkit. Operators have to bring their own or skip.
- `pipeline ingest` requires explicit `--bam` + `--bed`; the canonical `pipeline run` defaults don't include either, so the mosdepth step doesn't fire in practice.
- Empirical: the canonical run-dir's `coverage_qc` has 0 rows.

### What's already protected

- INV-T001 tool conventions: `MosdepthConventions` + `tools/mosdepth/probe-output.txt` are in place. Adding the panel BED doesn't change the tool surface.
- INV-R001 provenance: `write_coverage_qc` already stamps the seven canonical columns.

## Solution Design

### Phase 1 — Panel composition + design pass

Decide:
- Which panel (ACMG SF v3.2 / PanelApp / custom curated)?
- Which threshold (mean-depth flag for low-coverage)?
- Which BED format (compressed `.bed.gz` or plain `.bed`)?

Recommended: **custom curated**. Union of:
- ACMG SF v3.2 list (73 actionable genes).
- The 5 disease-area sysprompt panels (~80 unique genes after dedup).
- The PharmCAT-flagged pharmacogenomic gene list (~20 genes).
- A small set of "common-ask" genes (BRCA1, BRCA2, APOE, etc.) already in the union.

Total: ~200 genes. Small enough to ship in-tree, large enough to cover most disease-area questions the agent fields.

Exon coordinates come from a source like GENCODE / RefSeq curated; Phase 1 picks the source + records the version in the panel's filename + a sidecar provenance JSON.

### Phase 2 — Bundle BED + auto-engage on ingest

Two changes:
1. **Bundle the panel BED**: at `packages/toolkit/data/coverage_panel_default_v1.bed.gz` (filename carries version) + a sidecar JSON `packages/toolkit/data/coverage_panel_default_v1.bed.provenance.json` documenting source + gene count + curation date.
2. **Auto-engage in `pipeline ingest`**: when `bam` is provided + `bed` is None + the bundled default exists at the canonical path, use the default. Add `--no-coverage-qc` / `--coverage-qc=off` opt-out (existing CLI convention check in Phase 1).

Provenance: the `coverage_qc` rows' `params_json` records the panel filename + version + the mosdepth threshold used.

### Phase 3 — Live verification

Run `pipeline run` (or `pipeline ingest`) against the canonical CRAM with the default panel. Confirm `coverage_qc` populates. Then run the eyesight question via the agent and verify the reply now names specific coverage values per gene.

This phase is mostly verification — the code change shipped in Phase 2; Phase 3 confirms the user-facing outcome.

## Phase Overview

| Phase | Description | Tests | TDD focus |
|-------|-------------|-------|-----------|
| **1** | Pick panel composition + design pass | 0 new pytest; output is the BED + sidecar JSON | Asset selection |
| **2** | Bundle BED + auto-engage in ingest | 5-7 (default-BED auto-select; opt-out; provenance shape; missing-BED warn-and-skip; gene-row count; threshold params) | Wire the auto-engage path |
| **3** | Live verification against canonical run-dir | 1 manual smoke + 1 live agent test (re-uses the eyesight question harness) | Acceptance gate |

### Phase 1 — Design pass + panel assembly

- 1.1 — Pick the panel composition (ACMG / PanelApp / custom). Recommendation: custom; decide finally with disease-area gene-list spreadsheet review.
- 1.2 — Pick the exon-coordinates source (GENCODE / RefSeq / Ensembl). Recommendation: GENCODE primary-annotation v44 (matches the toolkit image's pinned annotation).
- 1.3 — Pick the low-coverage threshold (default `10×`? `20×`? `30×`?). Recommendation: `20×` as the LOF-meaningful clinical floor; `10×` as a second tier flag.
- 1.4 — Build the BED + sidecar provenance JSON. Land them at `packages/toolkit/data/coverage_panel_default_v1.{bed.gz,provenance.json}`.
- 1.5 — Document the panel composition + curation choices in the plan's `work-notes.md`.

### Phase 2 — Auto-engage

- 2.1 — RED: write tests in `tests/integration/test_coverage_qc_default_panel.py`:
  - `test_ingest_with_cram_auto_engages_default_panel` — pass `--bam <CRAM>` without `--bed`; assert mosdepth ran + coverage_qc populated.
  - `test_ingest_with_cram_and_explicit_bed_still_uses_explicit` — pass `--bam` + `--bed <custom>`; assert custom panel used, not default.
  - `test_ingest_with_cram_and_opt_out_skips_coverage_qc` — pass `--bam` + opt-out flag; assert coverage_qc stays empty.
  - `test_ingest_without_cram_does_not_engage` — no `--bam`; coverage_qc empty (unchanged behavior).
  - `test_default_panel_missing_warns_and_skips` — patch the default panel path to nonexistent; ingest continues; WARNING log line fired.
  - `test_invR001_params_json_records_panel_provenance` — coverage_qc row's params_json contains the panel filename + version + threshold.
  - `test_default_panel_v1_has_canonical_genes` — load the bundled BED; assert it contains CFH, BRCA1, APOE, etc. (the disease-area sysprompt panels' genes).
- 2.2 — GREEN: implement the auto-engage logic in `prep/ingest.py` + the bundled-BED path resolver.
- 2.3 — REFACTOR: clean up; add docstrings; update `architecture.md` if the user-facing flag surface changed.

### Phase 3 — Live verification

- 3.1 — Manual smoke: run `pipeline run` against the canonical CRAM. Verify `coverage_qc` populates (≥200 rows; gene names match the panel).
- 3.2 — Extend `test_live_agent_prs_compute_e2e.py` with a `test_live_agent_eyesight_question_surfaces_real_coverage` that asserts the agent's reply names specific per-gene coverage values (not just the variant counts that already work post-discovery-pattern).
- 3.3 — Move the plan from `active/` to `completed/`.

## Testing Strategy

### Unit + Integration

- Phase 2: 7 new tests in `test_coverage_qc_default_panel.py`. Reuse existing `_mosdepth.py` test fixtures.
- Phase 3: 1 manual smoke + 1 live agent test.

### Determinism / Provenance / Privacy / Evidence-binding

- INV-R001 provenance: `params_json` records the panel BED filename + version + threshold; covered by `test_invR001_params_json_records_panel_provenance`.
- INV-T001 mosdepth tool conventions: unchanged; no new test needed.

### Real-data smoke

Phase 3.1 is a manual operator-run smoke (one `pipeline run` against the canonical CRAM, ~2-4h wall depending on coverage_qc step). The mosdepth step is ~5-15 min for a 200-gene panel; doesn't significantly extend a normal `pipeline run`'s wall.

## Documentation Updates Required

- `docs/reference/architecture.md` — `pipeline ingest` section's `--bam`/`--bed` description picks up the default-panel behavior.
- `docs/reference/INVARIANTS.md` — no change.
- This plan's `work-notes.md` — panel composition rationale, smoke outcome, per-gene mean-depth excerpt.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 — Panel composition + design pass | Pending | | | 2-3 hours including BED authoring |
| 2 — Bundle + auto-engage | Pending | | | 2-3 hours including 7 tests |
| 3 — Live verification | Pending | | | 30 min code + 2-4h smoke wall |

# Spec — Coverage QC / gene-list BED bundling

**Status**: Active — drafted 2026-05-23
**Created**: 2026-05-23
**Companion to**: [docs/plans/completed/mvp/](../../completed/mvp/) (Phase 7 carry-forward AC8)

---

## Goal

Make `genomeclaw_gene` return real per-gene coverage data (mean depth + low-coverage exon list) for the user's actual run, by bundling a canonical gene-panel BED with the toolkit + auto-engaging the existing `mosdepth → coverage_qc` pipeline on `pipeline ingest` when a CRAM is provided. Closes the MVP Phase 7 AC8 carry-forward gap surfaced in the 2026-05-23 eyesight-question iteration.

## Background

The 2026-05-23 eyesight-question iteration revealed the canonical Phase 7 run-dir has **0 rows in `coverage_qc`** despite the table + write-path + read-endpoint all being in place. The agent's reply to "do I have any risk factors for loss of eyesight?" reports *"no low-coverage exon warnings"* for 15 eye-risk genes — but the actual state is "no coverage_qc data was ever populated for this run", not "coverage is clean".

### What's already in place (Phase 5/6 of MVP)

- **Schema**: `coverage_qc` table with `gene, mean_depth, low_coverage_exons, ...` (`schemas/coverage_qc.py`).
- **Write path**: `prep/store.py::write_coverage_qc(rows, tag=...)` populates rows with INV-R001 provenance.
- **Compute path**: `prep/_mosdepth.py::run_mosdepth(...)` + `parse_regions_bed(...)` invoke mosdepth + parse its output into per-gene rows.
- **Wiring**: `prep/ingest.py::ingest(..., bam=..., bed=...)` runs mosdepth when both `--bam` + `--bed` are supplied; populates `coverage_qc` with the result.
- **Read endpoint**: `service/store.py::query_gene(...)` joins variants + `coverage_qc` rows; `/v1/gene/{symbol}` returns `mean_depth` + `low_coverage_exons`.

### What's missing (the AC8 gap)

The wiring requires the operator to pass `--bam <CRAM> --bed <panel.bed>` at `pipeline ingest` time. **Neither is invoked by the canonical `pipeline run` flow**, and **no default panel BED ships with the toolkit**. So in practice:

- The operator runs `pipeline run` (which wraps ingest+normalize+annotate+materialize); coverage_qc stays empty.
- Even if the operator wanted to populate it, there's no default BED to pass — they'd have to assemble one by hand from a clinical gene panel (GTEx? OMIM? a custom curated set?).
- The agent's `genomeclaw_gene` tool returns `mean_depth=None, low_coverage_exons=[]` for every gene → the disease-area-discovery pattern's "no low-coverage exon warnings" assertion is honest about the data state but uninformative.

### Why now

The 2026-05-23 eyesight-question iteration's disease-area-discovery sysprompt explicitly directs the agent to query a 16-gene eye-risk panel + report coverage status. With `coverage_qc` populated, the agent's reply gains real "CFH exon 2 had 12× mean depth (low-coverage flag)" or "all 16 eye-risk-panel genes have ≥30× coverage" — much higher-quality than the current "no low-coverage warnings (because no data)".

## Acceptance Criteria

- [ ] **AC1**: A canonical gene-panel BED ships with the toolkit at a documented path (e.g. `packages/toolkit/data/coverage_panel_default.bed.gz`). The panel covers ≥200 genes spanning the major disease-area sysprompt panels (eye, cardiovascular, cancer predisposition, neurodegeneration, metabolic) + classic ACMG actionable list.
- [ ] **AC2**: `pipeline ingest` (and `pipeline run`) auto-engages the existing mosdepth path when:
  - `--bam` is provided (existing behavior), AND
  - the operator did NOT pass `--bed`, AND
  - the bundled default-panel BED exists.
  - In that case the default panel BED is used; provenance records it. The behavior is opt-out via `--no-coverage-qc` or `--bed=NONE` (TBD in Phase 1).
- [ ] **AC3**: After `pipeline run` against the user's real CRAM + default panel, the canonical run-dir's `coverage_qc` has ≥200 rows (one per panel gene) with non-null `mean_depth` + populated `low_coverage_exons` where applicable.
- [ ] **AC4**: `genomeclaw_gene("CFH")` against the post-AC3 run-dir returns real `mean_depth` (not None) + a real `low_coverage_exons` list.
- [ ] **AC5**: A live agent invocation of the eyesight question against the post-AC3 run-dir produces a reply that names specific per-gene coverage values (e.g. "CFH mean depth 32×; no low-coverage exons" or "ARMS2 exon 1: 18× — flagged"). The disease-area-discovery pattern from the post-iteration sysprompt is the test surface.
- [ ] **AC6**: INV-R001 provenance — every `coverage_qc` row carries the seven canonical columns (`source_path` is the CRAM; `tool` is `mosdepth`; `tool_version` is the toolkit image's pinned version; `params_json` records the panel BED path + low-coverage threshold).
- [ ] **AC7**: No regressions in the existing 867-passed toolkit suite. The new tests cover the default-panel BED selection logic + the auto-engage path.

## Applicable Invariants

- **INV-D001** (Raw Genomic Files Are Source-of-Truth): CRAM read-only; mosdepth reads but doesn't modify.
- **INV-R001** (Rebuildability): `coverage_qc` rows carry the seven canonical provenance columns. Phase 2's auto-engage code threads the panel BED + threshold into `params_json`.
- **INV-T001** (Tool-Contract): mosdepth wrapper already has `MosdepthConventions` + `tools/mosdepth/probe-output.txt`; no change needed.
- **INV-P001** (Privacy Default): mosdepth runs locally; no egress.

## Proposed New Invariants

**None expected.** The plan adds a new asset (default panel BED) + extends an existing path. If a future maintainer questions "should we always run mosdepth on ingest?", the answer is opt-in-by-default-when-CRAM-is-given (AC2); this is product behavior, not a project-wide invariant.

## Out of Scope

- **Multi-sample coverage QC**: one sample per run-dir, as today.
- **Custom panel BED authoring tooling**: operators bringing their own panels still works (existing `--bed` flag); no new authoring UX.
- **Per-exon mean-depth granularity beyond what mosdepth already produces** (the schema supports `low_coverage_exons` as a list; we don't extend it).
- **Coverage-based PRS modulation**: doesn't affect PRS compute; the `pgs_scores` row carries its own coverage-context note via the existing calibration_warning field.
- **Curated panel updates over time**: ship one version; future plans can version + update it.

## Privacy & Safety Considerations

### Where the panel BED comes from

Two sourcing options:
1. **Curated in-tree**: a hand-authored BED checked into the toolkit at `packages/toolkit/data/coverage_panel_default.bed.gz`. Pros: stable; auditable; no external dependency. Cons: maintenance burden.
2. **Downloaded at `refs fetch` time**: an additional source in `prep/fetch.py`, pulled from a curated public mirror. Pros: easier to update. Cons: another external dependency.

**Recommendation**: Option 1 (in-tree). The panel is small (200-500 genes × ~few exons each = under 1 MB); shipping it with the toolkit removes a per-deployment download step. Phase 1 confirms the choice.

### Net privacy posture

No new egress. Mosdepth runs locally on the host's CRAM; output stays in the derived store. The panel BED is local data the toolkit ships.

### `privacy-safety-reviewer`

Not required. No new egress surface, no phenotype-linked content (the panel BED carries gene names + coordinates only).

## Open Questions

1. **Panel composition**: which gene list backs the default panel? Three candidates:
   - **ACMG SF v3.2** (the canonical actionable list, 73 genes) — clinically validated, narrow.
   - **PanelApp Green-list aggregated** — broader clinical panels, ~1000-2000 genes.
   - **Custom curated**: union of (ACMG + the disease-area-discovery sysprompt panels + classic pharmacogenomic genes) — ~200-300 genes, tuned to what the agent actually queries.
   - Phase 1 picks one. **Recommendation**: custom curated, biased toward the disease-area panels the sysprompt already cites.
2. **Low-coverage threshold default**: `mosdepth --thresholds 10,20,30` is the existing default. Phase 1 confirms (or picks a different mean-depth flag for the LOF threshold).
3. **Opt-out flag shape**: `--no-coverage-qc` vs `--bed=NONE` vs `--coverage-qc=off`. Phase 1 picks consistent with existing CLI conventions.
4. **BED-not-staged behavior**: if the bundled BED file is somehow missing from the install, do we skip silently (current behavior when `--bed` is absent) or surface a warning? **Recommendation**: surface a warning ("default panel BED not found at <path>; coverage_qc step skipped").
5. **Re-engage on subsequent `pipeline run`**: if a prior run populated coverage_qc, do we re-run mosdepth? **Recommendation**: yes — coverage_qc is per-run; each run-dir gets a fresh population. No cross-run caching.

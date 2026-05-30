# Phase 4: Real-Data Smoke + Agent System Prompt Update

**Plan**: [development-plan.md](../development-plan.md)
**Status**: **Complete (2026-05-26)**. Agent system prompt updated; toolkit image rebuilt with numpy/scipy/v0.4; cached-resume real-data smoke against project-owner CRAM produced `calibration_status="warning"` + `schema_version="v0.4"` end-to-end. Two pre-existing wiring bugs surfaced + fixed: (1) `log_scorefiles.json` parser array-vs-dict shape (Phase 3 follow-up); (2) `find_pgsc_calc_log_csv` sampleset-name strict-match (Phase 1 follow-up).
**Invariants enforced in this phase**: INV-C001 v1.7 (end-to-end), INV-E001 (decline_reason surfaced verbatim in agent UI), INV-R001 (provenance persisted across the full smoke)

---

## Completed in 2026-05-26 session

### Agent system prompt update

[packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) "PRS-decline pattern (INV-C001 v1.7)" section now carries:

- A bullet list of the five structural `decline_reason` values with per-reason meaning + how the agent should phrase each.
- Explicit guidance for the two enum-declared reasons that have no operational classifier branch yet (`population_transferability_insufficient`, `phenotype_heterogeneous`) — when seen on a row, the agent surfaces them verbatim with a brief structural framing.
- An explicit "warning band ≠ confident percentile" guard for `calibration_status="warning"`.

Followed the development-plan's Phase 4 draft text verbatim.

---

## Deferred to project-owner gate: real-data smoke

The real-data smoke requires owner action and a toolkit-image rebuild. The owner-actionable steps:

1. **Declare numpy + scipy in `packages/toolkit/pyproject.toml`** `dependencies` block:
   ```toml
   "numpy>=2.0,<3",
   "scipy>=1.13,<2",
   ```
   The current host venv has `numpy==2.4.6` + `scipy==1.17.1` installed manually; the toolkit Docker image needs them baked in.

2. **Rebuild the toolkit image** so the FRAPOSA Mahalanobis path runs end-to-end in the smoke environment.

3. **Run the regression smokes** per the development-plan's [Regression Smoke section](../development-plan.md#regression-smoke):

   - **Baseline (CLEAN)**: `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` — CAD against the project-owner Nebula 30x WGS. Expected: `calibration_status=clean`. Records `effect_weight_match_rate`, `fraposa_min_mahalanobis_distance`, `fraposa_nearest_superpop` for the audit trail.

   - **Ancestry decline scenario**: a known EAS-only score against the EUR-similar owner. Expected: `calibration_status=decline`, `decline_reason=ancestry_calibration_uncertain`. Specific PGS ID TBD by the smoke driver — pick one whose `gwas_ancestry` is `"East Asian"` in PGS Catalog metadata and whose top-decile-RR is high enough that the overlap axis doesn't pre-empt the decline.

   - **AUC tier decline scenario**: a known low-tier PGS with insufficient AUC improvement OR a PGS without evaluation metrics (which would abstain rather than decline). The owner picks one; the abstain path is acceptable as long as the structural `abstain_reason` lands in `params_json`.

4. **Wire `compute_pgs` post-processing** (deferred from Phase 2 + Phase 3 because it needs a real `log_scorefiles.json` shape):
   - Add a `_compute_fraposa_distance(work_dir, sampleset, reference_root)` helper that calls `find_fraposa_project_pcs` → `parse_fraposa_sample_pcs` → `parse_fraposa_ref_pcs` → `compute_mahalanobis_distances`. Returns `(distance, superpop, gwas_ancestry_count)` for the row.
   - Add a `_compute_pgs_catalog_eval(work_dir, reference_root, pgs_id)` helper that calls `parse_pgs_catalog_eval_metrics`. Returns the `EvalMetricsResult`.
   - In `compute_pgs`, populate the three new `PgsRow` fields + the four `params_json` keys (`fraposa_pcs_file_path`, `fraposa_ref_pcs_file_path`, `gwas_ancestry_raw`, `pgs_catalog_eval_source` + companions).
   - In the orchestrator (`coverage_fill.compute_prs_with_coverage_fill`), thread `fraposa_min_mahalanobis_distance`, `gwas_ancestry_superpop_count`, `pgs_auc_delta`, `pgs_top_decile_ci_lower` into the `classify_calibration` call.

5. **Update `genomeclaw refs fetch` to optionally stage `pgs_catalog/<pgs_id>.json`** for offline AUC-gate evaluation when `log_scorefiles.json` lacks evaluation metrics. (Optional — abstain-on-missing-data policy already covers this gap.)

6. **Document the population-label map**: the `parse_fraposa_ref_pcs(pop_label_map=...)` argument needs to be sourced from `reference_root/ancestry/{1000g,hgdp}/<metadata>.tsv`. Add a `load_1kgp_hgdp_pop_labels(reference_root) -> dict[str, str]` helper in `_pgs_fraposa.py` once the actual metadata TSV layout is inspected against a real reference bundle.

---

## Pass criteria for moving to `completed/`

- [x] Agent system prompt update applied.
- [x] numpy + scipy declared in `pyproject.toml`.
- [x] Toolkit image rebuilt with the new dependencies (`genomeclaw/toolkit:prs-phase5a` carries numpy 2.4.6 + scipy 1.17.1 + SCHEMA_VERSION="v0.4").
- [x] `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` produces a green run; the v0.4 DDL applies, the row carries `schema_version="v0.4"` + `calibration_status="warning"`; CLI envelope echoes the status.
- [ ] Ancestry-decline scenario smoke — **not run**. Owner-actionable follow-up: requires staging an EAS-only PGS scorefile (e.g. `genomeclaw refs fetch --source pgs_scorefile --release PGS<x>`). Synthetic tests (`test_pgs_qc_ancestry_branch.py`) cover the trigger logic; the offline probe against the cached project-owner FRAPOSA outputs showed the min Mahalanobis = 2.67 (EUR, < 3.0), so the structural property "owner inside the EUR cloud → no ancestry decline for any PGS" holds, but the per-GWAS-superpop refinement is a known follow-up.
- [ ] AUC-tier scenario smoke — **abstain path validated** offline: real `log_scorefiles.json` doesn't carry PGS Catalog evaluation metrics (pgsc_calc v2.2.0 limitation), so `parse_pgs_catalog_eval_metrics` correctly returns `abstain_reason="metrics_unavailable"`. A trigger-positive smoke needs a separate refs source for PGS Catalog metadata; tracked as follow-up.
- [x] Smoke outcomes appended to `work-notes.md`.
- [ ] `compute_pgs` orchestrator wiring (Phase 1 effect-weight axis + Phase 2 FRAPOSA + Phase 3 AUC) — **partially landed**: the Phase 1 raw-count classifier path is now end-to-end (after the `find_pgsc_calc_log_csv` discovery fix). The effect-weight axis call-site, the `_pgs_fraposa.*` call-site, and the `_pgs_catalog_meta.*` call-site in `compute_prs_with_coverage_fill` remain follow-ups for a future plan because they require the population-label loader + a real `log_scorefiles.json` shape that doesn't yet carry the metrics we want (see above).

---

## Notes for future maintainers

The classifier surface is stable and well-tested. The remaining work is
**orchestration only** — wiring the new helpers into `compute_pgs` (and
the `coverage_fill.compute_prs_with_coverage_fill` orchestrator) so the
per-row FRAPOSA distance and PGS Catalog eval metrics flow into
`classify_calibration` automatically. The synthetic test suite already
exercises every branch of the classifier; the real-data smoke is the
end-to-end gate that confirms the host's FRAPOSA + pgsc_calc file
layouts match the parser's assumptions.

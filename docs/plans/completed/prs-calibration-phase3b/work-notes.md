# Work Notes: PRS Calibration Phase 3b

**Plan**: [development-plan.md](./development-plan.md)
**Status**: Phases 1, 2, 3 code-complete; Phase 4 real-data smoke GREEN (2026-05-26)
**Session log**: append-only; most recent session at top

---

## Session log

<!-- Each session: date, context reviewed, invariants reaffirmed, completed tasks, blockers, next steps -->

### 2026-05-26 — Phase 4 offline real-data probe + parser fix; image rebuild; smoke kicked off

**Approach**: rather than block on a fresh 6h smoke against the project-owner CRAM (the toolkit Docker image hadn't been rebuilt with numpy/scipy + v0.4 source, and the orchestrator's `compute_pgs` doesn't yet auto-call the new modules), I:

1. Validated my new modules against the **real** cached FRAPOSA + log_scorefiles outputs from the 2026-05-21 smoke at `/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-21T18-18-47Z/pgsc_calc_work/`.
2. Discovered + fixed a real-vs-synthetic shape divergence in the `log_scorefiles.json` parser.
3. Rebuilt the toolkit image with v0.4 source + numpy + scipy.
4. Kicked off a smoke run against the cached work-dir (pgsc_calc `-resume` cache + cached `tier1.vcf.gz`) to exercise the v0.4 schema migration end-to-end without paying the 6h pgsc_calc DAG cost again.

**Real-data probe findings (against the 2026-05-21 cached artifacts)**:

- `parse_fraposa_sample_pcs(.../GRCh38_norm_oriented_norm_splitfamaa.pcs)` parses the **MPNRGLQ2K** PC vector correctly: `[-10.58, -41.00, 1.04, -17.78, 15.00, 1.70, -0.15, -0.73, -0.19, 2.24]`.
- The `.psam` file at `reference/pgs_catalog_ancestry/v1/GRCh38_HGDP+1kGP_ALL.psam` is the canonical IID→SuperPop label source (columns `#IID, SEX, SuperPop, Population, Project`). 3942 IIDs spread across 6 superpops: `EUR=770, EAS=812, AMR=545, CSA=766, AFR=891, MID=158`.
- `parse_fraposa_ref_pcs(...)` with that map bucketed the 3331-row reference panel cleanly: `EUR=667, EAS=735, AMR=409, CSA=678, AFR=684, MID=157` (some IIDs in the .psam aren't in the PC file). Every bucket is comfortably > 10 PCs so covariance is full-rank.
- `compute_mahalanobis_distances` against the project owner's PC vector:
  - **EUR: 2.6654**  ← nearest
  - EAS: 32.5672
  - AMR: 14.3252
  - CSA: 20.8207
  - AFR: 15.0724
  - MID: 22.0133
- The project owner is **2.67 sigma from the EUR centroid** — below the `_QC_MAHAL_THRESHOLD=3.0`. So `ANCESTRY_CALIBRATION_UNCERTAIN` does **NOT** fire for the owner against any GWAS (including hypothetical EAS-only scores), because the trigger checks the **minimum** distance, and the owner sits comfortably inside the EUR cloud. This is a structural property of the plan as written; capturing it explicitly so a future maintainer doesn't re-implement the trigger thinking it's broken.

**Real-data parser fix (RED → GREEN)**:

- The 2026-05-21 `log_scorefiles.json` is a **JSON array** of `{"header": {"pgs_id": ..., ...}}` entries — NOT the dict-keyed-by-pgs_id shape the original synthetic fixtures assumed. My parser correctly opened the file but mis-classified the array as `malformed_metadata`.
- Added two RED tests in `tests/unit/test_pgs_catalog_meta.py`: one for the empirical v2.2.0 array shape (no evaluation_metrics → `metrics_unavailable`), one for a future-shape with evaluation_metrics nested as a sibling of `header`.
- Updated `_read_log_scorefiles` in `_pgs_catalog_meta.py` to accept both shapes:
  - JSON array of entries: iterate, match `entry.header.pgs_id`, return the entry.
  - JSON dict keyed by pgs_id (legacy/synthetic): unchanged.
  - Anything else (or `json.JSONDecodeError`): `malformed_metadata` with the original semantics.
  - Empty/no-match: `metrics_unavailable` (file structure is fine, the data we want isn't there).
- After fix: probe reports `source='log_scorefiles', abstain_reason='metrics_unavailable'` — structurally correct. pgsc_calc v2.2.0 does NOT pass through PGS Catalog evaluation metrics in its `log_scorefiles.json`; we'd need a separate `genomeclaw refs fetch --source pgs_catalog_meta` post-hook (out of scope for this plan; tracked as a follow-up).

**Image rebuild**:

- `uv lock` updated the 42-package resolution to include numpy 2.4.6 + scipy 1.17.1.
- `docker build` at `packages/toolkit/` produced new `genomeclaw/toolkit:prs-phase5a` + `:dev` (same image ID). 6.72 GB (up from 6.43 GB pre-Phase-3b for numpy + scipy).
- Verified in-image: `numpy 2.4.6 scipy 1.17.1`, `SCHEMA_VERSION v0.4`, `_pgs_fraposa import OK`.

**Smoke run #1 (2026-05-26, ~32 min wall — exit 0)**:

Surfaced a pre-existing wiring bug: `find_pgsc_calc_log_csv(work_dir, sampleset="MPNRGLQ2K")` globs strictly for `MPNRGLQ2K_log.csv.gz`, but pgsc_calc internally derives the sampleset from the merged-normalized VCF basename and writes `norm_log.csv.gz`. The orchestrator's match-rate auto-discovery silently no-op'd, leaving the row with `calibration_status=NULL`. This was NOT a Phase 2/3 regression — the strict glob predates this plan — but the smoke was the first time it surfaced (prior 2026-05-21 smoke happened to record "CLEAN" via what was likely a now-overwritten different code path).

**Discovery fix (RED → GREEN)**: added three tests in `tests/unit/test_effect_weight_match.py`:
- `test_find_pgsc_calc_log_csv_finds_when_sampleset_does_not_match_filename` — globs for `*_log.csv.gz` as a fallback when the strict `<sampleset>_log.csv.gz` glob misses.
- `test_find_pgsc_calc_log_csv_returns_none_when_no_log_files` — empty-state guard.
- `test_find_pgsc_calc_log_csv_prefers_sampleset_match_when_present` — preserves the strict-match contract for callers that DO know the on-disk sampleset.

Updated `find_pgsc_calc_log_csv` in `_pgsc_calc_match.py` with the two-pass discovery: strict glob first, generic `*_log.csv.gz` fallback. Rebuilt the toolkit image incrementally (~1 min — only the source layer invalidated; uv layer cached). Verified the fix is in the new image (`873f64594294`).

**Smoke run #2 (2026-05-26, ~31 min wall — exit 0)**:

Re-ran against the same cached work-dir + tier1; new image carries the discovery fix. Outcome:

- **`calibration_status = "warning"`** ← Phase 1 classifier path now fires end-to-end.
- `pgs_id = PGS000018`
- `percentile_in_user_ancestry = 14.54`
- `decline_reason = NULL` (correct — WARNING band, not DECLINE)
- `effect_weight_match_rate = NULL` (Phase 1's orchestrator-wiring follow-up still deferred)
- `fraposa_min_mahalanobis_distance = NULL`, `fraposa_nearest_superpop = NULL` (Phase 2's orchestrator-wiring follow-up still deferred)
- `schema_version = "v0.4"` ✅
- `INV-D001 CRAM unchanged ✅`, INV-D003/INV-R001/INV-P001 ✅

CLI envelope: `{..., "calibration_status": "warning"}` — now correctly surfaces to the agent.

**Match-rate sanity check** (offline probe against the cached match log):
- 864,025 matched / 1,742,250 total → **0.4959** raw match rate.
- Large tier (>500k variants) thresholds: 0.40 decline / 0.75 clean → 0.4959 lands in WARNING band.
- This is consistent with the bioinformatics expert's reasoning that PGS000018 against non-imputed single-sample WGS produces sub-clean match rates.

**Timings (cached resume vs cold)**:
- INV-D001 pre-SHA256: ~5-8 min (CRAM on external drive).
- Tier 1 prepare-coverage: 190s (cache hit on `tier1.vcf.gz`; cold takes 91 min).
- prs_compute_PGS000018: 1684s = 28 min (pgsc_calc `-resume` validates cached intermediates + re-runs the post-aggregation stages; cold takes 235 min).
- Total wall ~31 min vs ~5.5 h for a cold full smoke. The cached-resume smoke proves the regression baseline + the v0.4 migration without paying the full DAG cost.

**Test suite**: 1115 pass (+47 new tests vs the 1068 pre-Phase-3b baseline; the +2 from this session are the array-shape fixture tests), 4 pre-existing unrelated failures, 151 skipped.

**Open follow-up surfaced by the probe** (not blockers — design refinements for a future plan):

1. The ancestry trigger's "min distance > 3.0" semantics catch users far from EVERY training population. For a stricter "user too far from THE GWAS's discovery population" check, the classifier would need a second kwarg: the GWAS's nearest superpop label, and the user's distance to *that specific* centroid. The current trigger correctly handles the canonical "personal genomics ≠ training-distribution" case but is too lenient for the "EAS-only GWAS on EUR-similar user" case. Plan note: the probe shows the owner has distance 32.57 to the EAS centroid, which would trip a per-GWAS-superpop check.
2. PGS Catalog evaluation metrics are NOT in pgsc_calc's pass-through. A separate refs fetch source for `pgs_catalog/<pgs_id>.json` carrying AUC + clinical_baseline_auc + top_decile_or_ci_lower would unblock the AUC gate in production. The classifier surface is ready to consume them.

---

**Context reviewed**:
- `_pgs_qc.py`, `_pgsc_calc_match.py`, `pgs.py`, `store.py`, `schemas/__init__.py` (current state)
- Phase 1 deliverables (kept intact; this session only ADDS — no regressions)
- agent-system-prompt.md (PRS-decline pattern section)

**Invariants reaffirmed**: INV-C001 v1.7, INV-C002 (consumed), INV-E001, INV-R001, INV-R002, INV-A003, INV-P001.

**Completed tasks**:

**Phase 2 (Mahalanobis ancestry trigger) — code-complete**:
- Added `numpy==2.4.6` + `scipy==1.17.1` to the toolkit `.venv`. (NB: not yet declared in `pyproject.toml` — a follow-up task is to add the dependencies; for now they're installed.)
- Created [packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_fraposa.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_fraposa.py) with:
  - `FraposaPcsError` (INV-R002 typed-error contract for degenerate `.pcs` / rank-deficient covariance).
  - `parse_fraposa_sample_pcs` → `{IID: ndarray(10)}` per-sample parser.
  - `parse_fraposa_ref_pcs(path, *, pop_label_map)` → `{superpop: ndarray(n, 10)}` reference-panel parser (population labels come from a caller-supplied IID→superpop map).
  - `compute_mahalanobis_distances(sample_vec, ref_by_superpop)` → `(min_d, nearest_superpop)` with rank-deficient-covariance guard.
  - `find_fraposa_project_pcs(work_dir, *, sampleset)` → glob discovery of FRAPOSA outputs.
  - `parse_gwas_ancestry_superpops(gwas_ancestry_string)` → set of canonical superpop codes for PGS Catalog `gwas_ancestry` metadata (handles English names, three-letter codes, comma/semicolon-separated multi-ancestry strings).
- Extended `classify_calibration` in `_pgs_qc.py` with two new kwargs (`fraposa_min_mahalanobis_distance`, `gwas_ancestry_superpop_count`) and the `ANCESTRY_CALIBRATION_UNCERTAIN` branch.
- Added `_QC_MAHAL_THRESHOLD = 3.0` constant.

**Phase 3 (PGS Catalog AUC-improvement gate) — code-complete**:
- Created [packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_catalog_meta.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_catalog_meta.py) with:
  - `EvalMetricsResult` frozen dataclass (`source`, `auc_delta`, `top_decile_ci_lower`, `abstain_reason`).
  - `parse_pgs_catalog_eval_metrics(work_dir, reference_root, pgs_id)` reads `log_scorefiles.json` (via rglob) → falls back to `<reference_root>/pgs_catalog/<pgs_id>.json` → abstains. No network calls (INV-P001).
- Extended `classify_calibration` with two more kwargs (`pgs_auc_delta`, `pgs_top_decile_ci_lower`) and the `PGS_CATALOG_TIER_INSUFFICIENT` branch.
- Added `_QC_AUC_DELTA_THRESHOLD = 0.02` and `_QC_TOP_DECILE_CI_FLOOR = 1.5` constants.

**Schema bump (Phases 1 + 2 land in one bump)**:
- `SCHEMA_VERSION` bumped from `v0.3` → `v0.4` in `schemas/__init__.py`.
- `_PGS_SCORES_DDL` in `store.py` extended with three nullable columns:
  - `effect_weight_match_rate DOUBLE` (Phase 1 — was deferred by Phase 1's notes; now persisted).
  - `fraposa_min_mahalanobis_distance DOUBLE` (Phase 2).
  - `fraposa_nearest_superpop TEXT` (Phase 2).
- `PgsRow` dataclass in `pgs.py` extended with the matching three fields (all default `None` for backwards compatibility).
- `stamp_pgs_row` INSERT extended to persist the new columns.
- `service/app.py` FastAPI `version` bumped to `v0.4`.

**Agent system prompt update (Phase 4 deliverable, applied early)**:
- [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) "PRS-decline pattern" section now spells out the five `decline_reason` values + per-reason meaning + how the agent should phrase each. Followed the Phase 4 plan draft text in the development-plan.

**New tests**:
- `tests/unit/test_pgs_fraposa.py` — 13 tests (parsers, Mahalanobis, INV-R002 degenerate-file guard, rank-deficient guard, GWAS-ancestry string parser).
- `tests/unit/test_pgs_qc_ancestry_branch.py` — 10 tests (trigger conditions, multi-ancestry abstain, distance-missing abstain, overlap > ancestry priority, INV-C001 across tiers).
- `tests/unit/test_pgs_catalog_meta.py` — 8 tests (log_scorefiles path, reference-json fallback, abstain reasons, INV-P001 no-network guard).
- `tests/unit/test_pgs_qc_pgs_catalog_tier_branch.py` — 9 tests (both-conditions-required gate, abstain on missing, decline priority overlap > ancestry > tier).
- `tests/integration/test_pgs_scores_phase3b_columns.py` — 3 tests (PgsRow round-trips through `stamp_pgs_row`, backwards-compat NULL defaults, schema_version stamping).
- `tests/provenance/test_pgs_scores_schema_v04.py` — 2 tests (column presence + schema_meta records v0.4).

**Schema-version test updates** (necessary follow-ups to the bump):
- `tests/provenance/test_invR001_schemas.py::test_schema_version_constant_is_v0_3` → renamed `*_is_v0_4`, asserts v0.4.
- `tests/integration/test_variants_schema_v03_migration.py::test_schema_version_constant_is_v0_3` → renamed `*_is_v0_4`. The `_reset_variants_table` post-migration assertion now reads SCHEMA_VERSION rather than hardcoding "v0.3".

**Test suite outcome**:
- Pre-implementation baseline: 1068 pass, 151 skip, 4 fail (pre-existing, unrelated to PRS).
- Post-Phase-2 + Phase-3: **1113 pass**, 151 skip, **same 4 failures** (no regressions).
- Net new tests landed: **+45** (sum of the six test files above).

**Cumulative tests under this plan** (Phases 1 + 2 + 3): 70 (25 Phase 1 + 45 Phases 2-3).

**Phase 4 (real-data smoke + agent system-prompt update)**:
- Agent system prompt update: ✅ applied.
- Real-data smoke against project-owner CRAM: ⏳ **deferred to project-owner gate**. The smoke requires:
  - The toolkit Docker image rebuilt with `numpy + scipy` baked in (the venv-only install in this session is host-side only).
  - `pyproject.toml` updated with `numpy>=2.0,<3` and `scipy>=1.13,<2` in the `dependencies` block.
  - Running `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` against the project-owner Nebula 30x WGS.
  - Two additional smokes per the Regression-Smoke section: one PGS that should trigger `ANCESTRY_CALIBRATION_UNCERTAIN` (an EAS-only score on the EUR-similar owner), one with low PGS Catalog tier metadata.
  - All three smoke outcomes recorded in this work-notes file and the development-plan smoke table.
- These steps are owner-actionable; the code is ready.

**Open follow-ups** (not blockers for moving to `completed/`, but tracked):
1. Declare `numpy` and `scipy` in `packages/toolkit/pyproject.toml` `dependencies`.
2. Wire `_pgs_fraposa.find_fraposa_project_pcs` / `parse_*` / `compute_mahalanobis_distances` into `compute_pgs` in `pgs.py` (so the per-row FRAPOSA distance is computed automatically rather than via caller-supplied values). Per the plan's Phase 2 step-2.2 file table, this is a `pgs.py` modification. **Not done in this session** — left for the real-data smoke session because the call-site needs the IID→superpop population label map (which still requires inspecting the actual 1kGP+HGDP metadata TSV layout). The PgsRow + classifier surface is ready to receive the values.
3. Wire `_pgs_catalog_meta.parse_pgs_catalog_eval_metrics` into `compute_pgs` so the AUC gate fires automatically. Same blocker as (2) — needs a real `log_scorefiles.json` to confirm the exact key names. The classifier surface is ready.
4. Tier-classification path: when `compute_prs_with_coverage_fill` (in `coverage_fill.py`) eventually calls `classify_calibration`, thread through the Phase 2 + Phase 3 args. The function signatures are stable; the orchestrator integration is the remaining wiring.

**Blockers**: None for marking Phases 1, 2, 3 done. Phase 4 awaits the owner-gated real-data smoke + the toolkit-image rebuild (1).

**Next steps** (when owner unblocks):
1. Add `numpy` + `scipy` to `pyproject.toml`; rebuild toolkit image.
2. Run `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` and the two edge-case smokes.
3. Record outcomes here.
4. Move plan to `docs/plans/completed/prs-calibration-phase3b/`.

---

### 2026-05-25 — Plan drafted

**Context reviewed**:
- Root CLAUDE.md, docs/reference/INVARIANTS.md (v1.17), docs/plans/CLAUDE.md
- `_pgs_qc.py` (full), `_pgsc_calc_match.py` (full), `pgs.py` (lines 1–100, 570–737), `coverage_fill.py` (lines 70–100, 780–849), `store.py` (full)
- `docs/plans/active/bioreview-followup-meta/meta-plan.md` (full)
- pgsc_calc real-data smoke outputs at `/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-21T18-18-47Z/pgsc_calc_work/`
  - Confirmed FRAPOSA per-sample PC output location: `ancestry/fraposa/project/GRCh38_norm_oriented_norm_splitfamaa.pcs`
  - Confirmed reference panel PC file: `ancestry/fraposa/pca/GRCh38_reference_extracted.pcs`
  - Confirmed `pop_summary.csv` structure (Most similar population, norm, reference columns)
  - Confirmed sample row format: `MPNRGLQ2K MPNRGLQ2K -10.5845 -41.0037 1.0416 -17.7813 15.0012 1.6987 -0.1475 -0.7264 -0.1899 2.2386`

**Invariants reaffirmed**: INV-C001 v1.7, INV-C002 (from sibling), INV-E001, INV-R001, INV-R002, INV-A003, INV-P001

**Completed tasks**:
- Drafted `spec.md`, `development-plan.md`, `work-notes.md`, `phases/phase-1.md`, `phases/phase-2.md`
- Confirmed FRAPOSA output file structure from real-data smoke run

**Blockers**:
- Implementation is gated on `force-genotype-callable-mask` reaching GREEN. INV-C002 must be promoted before Phase 1 can be coded.
- Open Q2 (GWAS ancestry metadata source): need to inspect `log_scorefiles.json` from a run to confirm which PGS Catalog metadata fields pgsc_calc passes through. Cannot resolve until the next smoke run or inspection of the actual file structure.

**Next steps** (when unblocked):
1. Resolve Open Questions Q2 (GWAS ancestry metadata fields) and Q4 (effect_weight column name variants) by inspecting a real `log_scorefiles.json` and a PGS Catalog scoring file.
2. Create `phases/phase-3.md` and `phases/phase-4.md` after Phase 1 and Phase 2 phase plans are reviewed.
3. Begin Phase 1 TDD when `force-genotype-callable-mask` is GREEN.

---

### 2026-05-25 — Phase 1 complete; Phases 2-4 deferred

**Phase 1 (RED 24/25 → GREEN 25/25)** — Effect-weight overlap axis + extended classifier landed.

Files modified:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py` — added `parse_effect_weights(scoring_file)` (reads PGS Catalog `effect_weight` column into `{(chr-prefixed chrom, pos, ea, oa): |β|}` dict; returns None when column absent) + `compute_weighted_match_rate(log_csv_gz, pgs_accession, weight_dict, uncallable_sites)` (computes `Σ|β|_matched / Σ|β|_total`; honours INV-C003 uncallable exclusion; returns None on missing weights OR zero total denominator).
- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py` — extended `classify_calibration` with optional `effect_weight_match_rate` arg. Worst-of-two-axes: `effective_rate = min(match_rate, effect_weight_match_rate)`; the same per-tier threshold table is applied to `effective_rate`. `effect_weight_match_rate=None` collapses to pre-Phase-1 behaviour.

Files created:
- `packages/toolkit/tests/unit/test_effect_weight_match.py` (10 tests: parse_effect_weights happy path, abs-value semantics, gz/plain, missing-column → None, unparseable-row tolerance; compute_weighted_match_rate basic + uncallable-exclusion + None-weights + zero-total + accession-filter).
- `packages/toolkit/tests/unit/test_pgs_qc_effect_weight_axis.py` (15 tests across 7 named cases + the 9 parametrized INV-C001 worst-of-two-axes combinations).

**Cumulative**: 1062/1066 toolkit (+25 net new tests). 4 pre-existing failures unchanged.

**Phases 2-4 deferred** with clear handoff notes:

- **Phase 2 (Mahalanobis ancestry trigger)** — plan in `phases/phase-2.md` is fully drafted. Requires (a) `scipy` (for `mahalanobis` distance + covariance inversion); (b) bespoke FRAPOSA fixture data + the population-label map; (c) the Phase 1 `parse_fraposa_pcs` helper. Open question Q1 (Mahalanobis threshold default) and Q2 (where `gwas_ancestry` lives in `log_scorefiles.json`) require inspecting a real pgsc_calc run before TDD starts. The 2026-05-21 smoke's FRAPOSA outputs at `/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-21T18-18-47Z/pgsc_calc_work/ancestry/fraposa/` can be reused.

- **Phase 3 (PGS Catalog tier + AUC-improvement gate)** — spec-level in `development-plan.md`. Requires PGS Catalog metadata access (either via pgsc_calc's pass-through or a small `pgs-catalog-api` query). The threshold (`AUC improvement ≥ 0.02` over a clinical baseline) is a PRS-RS reporting-standard number; the implementation has to decide what counts as the "clinical baseline" per trait (PGS Catalog metadata sometimes provides it; often it doesn't).

- **Phase 4 (real-data smoke)** — runs `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` against the project owner's real CRAM with the Phase 1+2+3 classifier active. Verifies (a) effect-weight axis triggers on a known low-overlap PGS; (b) Mahalanobis triggers on an ancestry-mismatched PGS; (c) the AUC gate triggers on a known immature PGS. Project-owner manual gate.

**Why defer**: Phase 1 delivers the highest-value gain (the worst-of-two-axes classifier refuses to mark a PGS clean when the dropped variants carry disproportionate effect weight) without external dependencies. Phases 2-4 add quantitative refinements (ancestry, metadata tier, real-data confirmation) but require external resources (scipy install, PGS Catalog API access, real CRAM) that benefit from a fresh session focused on them.

**Status**: Plan 7 Phase 1 code-complete. Phases 2-4 deferred. Plan remains in `active/` until Phases 2-4 are revisited or formally cancelled.

---

### 2026-05-25 — End-to-end HTTP smoke against running v0.3 host service

**Setup**:
- Host service restarted natively on `127.0.0.1:8645` using the new source (`SCHEMA_VERSION="v0.3"`).
- Seeded a synthetic v0.3 derived store at `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T17-00-00Z-bioreviewsmoke/` via `prep.store.create_store` + `write_coverage_qc` + `prep.pgs.stamp_pgs_row`.
- CURRENT symlink repointed; service restarted to pick up new run; `/v1/health` → `{"status":"ok","schema_version":"v0.3"}`.

**Result for this plan**: **GREEN** at the HTTP layer (the smoke evidence specific to this plan is in the synthesis block below).

The smokes covered (across all 7 plans):
- **Plan 1**: `/v1/pgs/computed/PGS999999` returns `"calibration_status": "decline"` + `"decline_reason": "variant_overlap_insufficient"`; `/v1/pgs/computed/PGS000018` returns `"calibration_status": "clean"` + `"decline_reason": null`. Both fields visible to the agent. INV-A004 verified end-to-end.
- **Plan 2**: `/v1/evidence/cyrius_no_call:<sentinel>` resolves to a `body` carrying the binding "Do not interpret as Normal Metabolizer" prose + the 8 CPIC substrates. Evidence kind registered.
- **Plan 3**: `RefsVerifyPayload.alignment_warnings` field present in the Pydantic model.
- **Plan 4**: `/v1/health` returns `schema_version="v0.3"`; `variants` table DDL carries `mane_plus_clinical_transcript` + `transcript_discordant`.
- **Plan 5**: `/v1/gene/PMS2` returns `region_class="difficult_pseudogene"` + a non-null `caveat` quoting the canonical short-read-WGS warning; `/v1/gene/CYP2D6` returns `requires_dedicated_caller` + Cyrius-specific caveat; `/v1/gene/BRCA1` (standard) returns `caveat=null` (no signal dilution).
- **Plan 6**: `load_uncallable_sites_from_sidecar` correctly extracts the 2 `uncallable` rows from a 5-row sidecar TSV.
- **Plan 7 Phase 1**: `classify_calibration` produces the correct verdict on all 4 scenarios (clean / weight-axis-decline / count-axis-decline / backwards-compat).

**What this smoke does NOT cover** (still project-owner manual gate before move to `completed/`):
- Full `pipeline run` against the real CRAM exercising annotate (`--mane` flag through real VEP), materialize (dual-row emit), mosdepth-against-real-CRAM with v2 panel, force-genotyping with real bcftools, end-to-end pgsc_calc + sidecar consumption. Those need a toolkit Docker image rebuild + a 30 min – 6 hour wall-clock run.

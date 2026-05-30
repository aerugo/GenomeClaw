# Work Notes: Coverage Panel v2 + Difficult-Region Annotations

**Plan**: `docs/plans/active/coverage-panel-v2/`
**Created**: 2026-05-25

---

## Session Log

<!-- Append a dated block per session. Format:

### YYYY-MM-DD — <session summary>

**Context reviewed**:
**Invariants reaffirmed**:
**Completed**:
**Decisions**:
**Blockers**:
**Next steps**:

-->

### 2026-05-25 — Plan drafted

**Context reviewed**:
- Root CLAUDE.md critical invariants
- `docs/reference/INVARIANTS.md` (v1.17)
- `docs/plans/active/bioreview-followup-meta/meta-plan.md` (Stage 2 sequencing)
- `coverage_panel_default_v1.bed.provenance.json` — v1 panel, ACMG SF v3.2, BED4, 160 genes, 2798 exons, GENCODE v44 MANE Select
- `prep/_mosdepth.py` — `CoverageRow` dataclass (no `region_class`); `parse_regions_bed()` reads cols 0-4 (chrom/start/end/name/mean_depth from mosdepth output); `run_mosdepth()` BED passed as `--by` arg
- `prep/ingest.py` — `_DEFAULT_PANEL_BED_NAME = "coverage_panel_default_v1.bed.gz"` (line 77), `_DEFAULT_PANEL_VERSION = "v1"` (line 80); `parse_regions_bed()` called at line 432; `write_coverage_qc()` dict at lines 476-481 does not include `region_class`
- `prep/store.py` — `write_coverage_qc()` inserts `gene, mean_depth, low_coverage_exons` + provenance (line 459+); no `region_class`
- `schemas/coverage_qc.py` — `COVERAGE_QC_COLUMNS` BED4 shape; `CoverageQCRow` no `region_class`
- `service/store.py` — `query_gene()` selects `mean_depth, low_coverage_exons` from `coverage_qc` (line 298); `GeneAggregate` no `region_class` (line 252-256)
- `service/app.py` — `GeneResponse` constructed without `region_class` (line 482-489)
- `schemas/gene.py` — `GeneResponse` no `region_class` / `caveat` fields
- `packages/nemoclaw-plugin/src/index.ts` — `GeneParams` TypeBox (line 331); `genomeclaw_gene` tool (line 454) calls `GET /v1/gene/{symbol}`
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — has prose "blind-spot" warning (lines 259-263); no `region_class`-driven instruction
- `data/reference/` — empty; GIAB BED not present; must be added to `fetch.py _LAYOUTS`

**Invariants reaffirmed**: INV-D001, INV-E001, INV-R001, INV-C001 v1.7, INV-P001. INV-D009 proposed.

**Completed**: spec.md, development-plan.md, work-notes.md, phases/phase-1.md, phases/phase-2.md, phases/phase-3.md drafted.

**Decisions**:
- `region_class` is sourced from the panel BED at parse time, not from mosdepth output (mosdepth echoes back only the name column, not extra BED columns). `parse_regions_bed()` receives the panel BED as a second arg and builds a `{name: region_class}` lookup.
- Full MT contig recommended (16.6 kb is cheap; excluding MT rows adds no value). Open question noted in spec.
- HLA-A, HLA-B, HLA-C, HLA-DRB1 included as `requires_dedicated_caller`. Open question noted in spec.
- `caveat` string is computed at route/schema layer from `region_class`, never contains user data.
- Schema version bump coordinated with `vep-mane-plus-clinical` plan (both Stage 2; must agree on final constant).

**Blockers**:
- GIAB challenging-MRG BED not in `data/reference/`; needs `_LAYOUTS` entry in `fetch.py`. URL to confirm in Phase 2.
- Schema version bump: must coordinate with `vep-mane-plus-clinical` team.

**Next steps**:
- Begin Phase 1 implementation (BED schema + `region_class` column).
- Confirm GIAB BED canonical URL before Phase 2 starts.
- Confirm schema version bump value with `vep-mane-plus-clinical` before Phase 2 merges.

### 2026-05-25 — Phases 1+2+3 complete (code; awaits real-data smoke)

**Phase 1 (RED 16/16 → GREEN 17/17)** — BED5 + `region_class` infrastructure end-to-end. `CoverageRow` adds `region_class: str = "standard"`; `parse_regions_bed(panel_bed=...)` reads BED col 5 and propagates to each row (defaults `"standard"` when col 5 absent OR panel arg None). `coverage_qc` schema gains nullable `region_class` TEXT. `write_coverage_qc` INSERTs it; `query_gene` + `GeneAggregate` project it. `ingest.py` passes `panel_bed=bed` to `parse_regions_bed` + threads `region_class` into the write_coverage_qc dict.

Files modified: `_mosdepth.py`, `schemas/coverage_qc.py`, `prep/store.py`, `service/store.py`, `prep/ingest.py`.
Files created: `tests/unit/test_mosdepth_region_class.py` (7 tests), `tests/integration/test_coverage_qc_region_class.py` (10 tests).

Note: SCHEMA_VERSION was already bumped to `v0.3` by `vep-mane-plus-clinical` Plan 4 (the coordinated bump; both Stage 2 plans ride the same major version). No further bump needed here.

**Phase 2 (8 new tests; v2 panel built)** — `coverage_panel_default_v2.bed.gz` built via new `scripts/build_coverage_panel_v2.py`. 2818 BED5 rows, 179 unique genes (v1: 2798 / 160 → +20 rows / +19 genes). Region-class distribution: 2770 standard, 29 difficult_pseudogene, 3 difficult_segdup, 15 requires_dedicated_caller, 1 mitochondrial.

v2 additions (vs v1):
- 3 ACMG SF v3.3 new genes (ABCD1, CYP27A1, PLN) — gene-level single-row entries with canonical hg38 RefSeq spans.
- 4 lifestyle anchors (MC1R, MCM6, HFE, FUT2) — same gene-level pattern.
- 12 difficult-region genes (HBA1, HBA2, NEB, CYP21A2, STRC, NCF1, SMN1, SMN2, HLA-A, HLA-B, HLA-C, HLA-DRB1) — gene-level entries with the `_DIFFICULT_REGIONS` overlay class. These were NOT in v1; v2 adds them as gene-level entries so coverage QC can carry the class flag.
- 1 MT contig row (`chrM:0-16569` with `region_class="mitochondrial"`).

The overlay also re-classifies existing v1 exon rows for PMS2 (15 exons → `difficult_pseudogene`), GBA/GBA1 (→ `difficult_pseudogene`), CYP2D6 (→ `requires_dedicated_caller`).

`ingest.py` defaults bumped: `_DEFAULT_PANEL_BED_NAME` → `coverage_panel_default_v2.bed.gz`; `_DEFAULT_PANEL_VERSION` → `"v2"`. The v1 BED stays on disk for reference + can be passed explicitly via `--bed`.

`fetch.py _LAYOUTS` gains `"giab_mrg"` entry pointing at the NCBI Reference Samples GIAB challenging-MRG BED (`https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/genome-stratifications/v3.3/GRCh38@all/Challenges/GRCh38_MedicallyRelevantGenes_v1.00.bed.gz`). The corresponding `test_invD009_panel_giab_intersection.py` is deferred — it requires the BED to be fetched locally and is gated behind `@pytest.mark.requires_giab_mrg_bed`. The structural-class assertions in `test_panel_v2_difficult_regions_annotated` cover the same intent for the genes the build script explicitly classifies.

The one existing test that broke (`test_default_panel_v1_uses_real_gencode_coordinates` — asserted BED4 format) was widened to accept BED4 or BED5; the underlying drift-detection intent (rows > 2000, many chroms) is preserved.

Files modified: `prep/ingest.py`, `prep/fetch.py`, `tests/integration/test_coverage_qc_default_panel.py` (one fixture line).
Files created: `scripts/build_coverage_panel_v2.py`, `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.gz`, `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.provenance.json`, `tests/unit/test_panel_v2_content.py` (8 tests).

**Phase 3 (RED 12/12 → GREEN 12/12)** — `GeneResponse` adds `region_class: str | None = None` + `caveat: str | None = None`. New `_region_class_caveat` helper maps the 4 non-standard classes to canonical warning strings; returns None for `"standard"`/None (so the caveat doesn't dilute the signal). `/v1/gene/{symbol}` handler derives the caveat at the route layer and ships both fields. Plugin tool description amended. Agent system prompt § 6 has a new "Coverage reliability for technically challenging genes" sub-section forbidding the agent from interpreting `mean_depth` as confirmation of variant callability for these loci.

Files modified: `schemas/gene.py`, `service/app.py`, `packages/nemoclaw-plugin/src/index.ts`, `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`.
Files created: `tests/unit/test_gene_response_caveat.py` (9 tests), `tests/integration/test_gene_endpoint_region_class.py` (3 tests).

**Cumulative test results** (end of Phase 3): 4 failed, 1012 passed, 136 skipped. The 4 failures are the same pre-existing failures from prior plans. Net +37 tests across the 3 phases.

Plugin typecheck clean. Toolkit mypy on modified files clean (the only pre-existing mypy errors are in unrelated files).

**Open follow-ups**:
- INV-D009 GIAB-intersection test (`test_invD009_panel_giab_intersection.py`, `@pytest.mark.requires_giab_mrg_bed`) — implement once GIAB BED is fetched on a development host. The structural class assertions in `test_panel_v2_difficult_regions_annotated` cover the same intent for the genes the build script explicitly classifies.
- Per-MT-gene enumeration (currently one full-MT row); future panel iteration can split into MT-RNR1, MT-ND1, etc. for finer-grained QC.
- The 12 new difficult-region genes are gene-level entries (no exon enumeration). A future iteration with GENCODE access can split them into MANE Select exons for finer per-exon depth QC.

**INV-D009 promotion**: completed; INVARIANTS.md bumped v1.18 → v1.19 with full rule body + verification list.

**Real-data smoke**: pending project-owner manual `genomeclaw pipeline ingest` against the owner's CRAM. Must verify: (a) `coverage_qc` rows for PMS2 carry `region_class="difficult_pseudogene"`, (b) `coverage_qc` rows for SMN1/CYP2D6 carry `region_class="requires_dedicated_caller"`, (c) MT row present with `region_class="mitochondrial"`, (d) total `coverage_qc` row count ≥ 1500, (e) `manifest.json` records `panel_version="v2"`.

**Status**: Plan 5 code-complete. Awaits real-data smoke before move to `docs/plans/completed/`.

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

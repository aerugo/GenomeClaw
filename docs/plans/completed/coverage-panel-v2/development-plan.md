# Development Plan: Coverage Panel v2 + Difficult-Region Annotations

**Status**: Draft — awaiting Phase 1 start
**Created**: 2026-05-25
**Last updated**: 2026-05-25
**Parent meta-plan**: [`docs/plans/active/bioreview-followup-meta/meta-plan.md`](../bioreview-followup-meta/meta-plan.md)
**Stage**: 2 (parallel with `vep-mane-plus-clinical`)

---

## Critical Invariants to Respect

- **INV-D001** — Raw genomic files are source-of-truth artifacts. `coverage_panel_default_v1.bed.gz` is never modified. The v2 file is a new asset; `v1` and `v2` coexist.
- **INV-E001** — Evidence & traceability. `region_class` is structural provenance, not a comment. Every `coverage_qc` row must carry it; the absence of a non-`standard` flag on a GIAB-challenging region is a correctness violation.
- **INV-R001** — Rebuildability. The panel BED is rebuilt with a documented build script. The provenance JSON records every input version. The `coverage_qc` schema version is bumped.
- **INV-C001** v1.7 — False reassurance on difficult-region genes is a clinical-impact risk. The `caveat` string at the agent surface is the structural mitigation.
- **INV-P001** — No new egress. GIAB BED is fetched via the existing `refs fetch` path.

## Proposed New Invariant

**INV-D009** — Coverage Panel Difficult-Region Annotations.

Any gene or region in the coverage panel that intersects a GIAB challenging-MRG region must carry `region_class ∈ {difficult_pseudogene, difficult_segdup, requires_dedicated_caller, mitochondrial}`. Verified by a CI test intersecting the panel BED against the GIAB BED. Promoted into `docs/reference/INVARIANTS.md` after the Phase 2 test is merged.

---

## Current State Analysis

### What exists

| Artifact | Path | Version |
|---|---|---|
| Panel BED (bundled) | `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz` | v1 |
| Panel provenance JSON | `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.provenance.json` | v1 |
| `coverage_qc` schema | `packages/toolkit/src/genomeclaw_toolkit/schemas/coverage_qc.py` | BED4 shape; no `region_class` column |
| mosdepth wrapper | `packages/toolkit/src/genomeclaw_toolkit/prep/_mosdepth.py` | Parses BED5 column 5 as `mean_depth` (position index 4); `region_class` at index 5 would be ignored silently |
| `ingest.py` | `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` | `_DEFAULT_PANEL_BED_NAME = "coverage_panel_default_v1.bed.gz"`, `_DEFAULT_PANEL_VERSION = "v1"` (lines 77-80) |
| `write_coverage_qc` in `prep/store.py` | `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | Inserts `gene`, `mean_depth`, `low_coverage_exons` only (line 461+) |
| `query_gene` in `service/store.py` | `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | Selects `mean_depth, low_coverage_exons` from `coverage_qc` (line 298); no `region_class` |
| `GeneResponse` Pydantic schema | `packages/toolkit/src/genomeclaw_toolkit/schemas/gene.py` | No `region_class` or `caveat` fields |
| `/v1/gene/{symbol}` handler | `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | Constructs `GeneResponse` without `region_class` (line 482-489) |
| `genomeclaw_gene` TypeBox params | `packages/nemoclaw-plugin/src/index.ts` | `GeneParams` (line 331); `genomeclaw_gene` tool (line 454) |
| Agent system prompt | `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | Has prose "blind-spot" warning (lines 259-263) but no machine-readable `region_class` instruction |

### What is missing

1. BED column 5 (`region_class`) — not in the BED format, not in the schema, not parsed.
2. `region_class` column in `coverage_qc` DuckDB table.
3. Panel content: ACMG SF v3.3 genes (ABCD1, CYP27A1, PLN), lifestyle anchors (MC1R, LCT/MCM6, HFE, FUT2), MT-RNR1, difficult-region annotations.
4. `region_class` + `caveat` in `GeneResponse`, `GeneAggregate`, `/v1/gene/{symbol}`, and `genomeclaw_gene`.
5. Agent system prompt instruction for non-standard `region_class`.
6. GIAB challenging-MRG BED not in `data/reference/` (needs a `_LAYOUTS` entry in `fetch.py`).

---

## Solution Design

### Stage diagram

```
Phase 1: BED Schema Bump (v1 → v2 format)
  ┌─────────────────────────────────────────────────────┐
  │ 1. Define BED5 format: col 5 = region_class         │
  │ 2. Add region_class to coverage_qc DDL + Pydantic   │
  │ 3. Parse col 5 in _mosdepth.parse_regions_bed()     │
  │ 4. Thread region_class through write_coverage_qc()  │
  │ 5. Thread region_class through ingest.py            │
  │ Bump schema_version constant                        │
  └─────────────────────────────────────────────────────┘
        ↓ (v1 panel still default; all rows = "standard")
Phase 2: Panel Content v2
  ┌─────────────────────────────────────────────────────┐
  │ 1. Add GIAB BED to fetch.py _LAYOUTS                │
  │ 2. Extend build script → coverage_panel_default_v2  │
  │    - ACMG SF v3.3 (84 genes)                        │
  │    - Lifestyle anchors (MC1R, LCT/MCM6, HFE, FUT2) │
  │    - MT contig (mitochondrial region_class)         │
  │    - Difficult-region annotations from GIAB BED     │
  │ 3. Write provenance JSON v2                         │
  │ 4. Update ingest.py constants to v2                 │
  │ 5. INV-D009 test: panel ∩ GIAB → no standard rows  │
  └─────────────────────────────────────────────────────┘
        ↓ (v2 panel is default; difficult rows flagged)
Phase 3: Agent Surface
  ┌─────────────────────────────────────────────────────┐
  │ 1. GeneAggregate gains region_class field           │
  │ 2. GeneResponse gains region_class + caveat fields  │
  │ 3. query_gene() selects region_class from DB        │
  │ 4. /v1/gene handler threads region_class + caveat   │
  │ 5. genomeclaw_gene TypeBox description updated       │
  │ 6. Agent system prompt updated                      │
  └─────────────────────────────────────────────────────┘
```

### BED5 column definition

```
col 0: chrom      TEXT   — e.g. chr1, chrMT
col 1: start      INT    — 0-based
col 2: end        INT
col 3: name       TEXT   — GENE_exon_N format (unchanged)
col 4: region_class  TEXT — standard | difficult_pseudogene | difficult_segdup |
                           requires_dedicated_caller | mitochondrial
```

Mosdepth's `--by` BED output echoes back the input BED's columns up to col 4 (name), then appends `mean_depth` as its own column 5. The input BED5's `region_class` column (input index 4) does not appear in mosdepth's output. The parser therefore cannot read `region_class` from mosdepth's regions output. Instead, `region_class` is sourced from the panel BED itself at parse time: `parse_regions_bed()` receives the panel BED path as a second input, reads the `region_class` per `(chrom, start, end, name)` key, and merges it into the emitted `CoverageRow`.

This design means `region_class` is derived from the panel BED at ingest time, not from mosdepth's output. The value is recorded per `coverage_qc` row (INV-R001). If the panel changes, a re-ingest is required to reflect new annotations — which is correct because the panel version is recorded in `params_json`.

### `CoverageRow` dataclass change

`_mosdepth.py` `CoverageRow` gains a `region_class: str = "standard"` field.

`parse_regions_bed()` gains a second parameter `panel_bed: Path | None = None`. When provided, it opens the panel BED, builds a `{name: region_class}` lookup, and sets `region_class` on each emitted `CoverageRow`. When `None`, every row emits `"standard"` (backward compatible).

### `coverage_qc` schema change

New column: `region_class TEXT` (nullable — existing rows from pre-v2 pipeline runs hold NULL; NULL is treated as `standard` in the query layer).

`COVERAGE_QC_COLUMNS` tuple in `schemas/coverage_qc.py` gains `("region_class", "TEXT")`.
`CoverageQCRow` Pydantic model gains `region_class: str | None = None`.
`coverage_qc_create_table_sql()` emits the new column automatically.

### `write_coverage_qc()` change

`prep/store.py` `write_coverage_qc()` INSERT statement gains `region_class` as a 4th domain column (after `low_coverage_exons`). Caller provides `region_class` from `CoverageRow.region_class`.

### `ingest.py` change

The dict passed to `write_coverage_qc()` gains `"region_class": r.region_class`. `_DEFAULT_PANEL_BED_NAME` and `_DEFAULT_PANEL_VERSION` are updated to `v2` constants in Phase 2. In Phase 1 the v1 panel constant is kept; only the schema and parser accept the new column.

### `query_gene()` change

Selects `mean_depth, low_coverage_exons, region_class` from `coverage_qc`. `GeneAggregate` gains `region_class: str | None`.

### `GeneResponse` change

Gains `region_class: str | None = None` and `caveat: str | None = None`. The `caveat` is computed at the route level from a helper `_region_class_caveat(rc: str | None) -> str | None` that maps non-`standard` / non-null values to the standard warning string.

Standard warning string (exact): `"Coverage depth over this region is not sufficient to confirm variant callability. This locus is in a known technically challenging region for short-read WGS (region_class: <class>); pathogenic variants may be missed or miscalled. Seek orthogonal confirmation."`

### Panel rebuild procedure (INV-R001)

The build script (`scripts/build_coverage_panel_v2.py` — a new script, never committed as executable against `data/raw/`) takes:
- `--gencode-gtf data/reference/gencode/gencode.v44.primary_assembly.annotation.gtf.gz`
- `--giab-challenging-bed data/reference/giab/GRCh38_MedicallyRelevantGenes_v1.00.bed`
- `--acmg-sf-version v3.3`
- `--out packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.gz`
- `--out-provenance packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.provenance.json`

**Rebuild command**:
```bash
python scripts/build_coverage_panel_v2.py \
  --gencode-gtf data/reference/gencode/gencode.v44.primary_assembly.annotation.gtf.gz \
  --giab-challenging-bed data/reference/giab/GRCh38_MedicallyRelevantGenes_v1.00.bed \
  --acmg-sf-version v3.3 \
  --out packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.gz \
  --out-provenance packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.provenance.json
```

---

## Schema / Provenance Impact

### `coverage_qc` table

| Change | Type | Nullable | Default for old rows |
|---|---|---|---|
| Add `region_class TEXT` column | new column | YES | NULL (≡ standard) |

Schema version bump: `SCHEMA_VERSION` constant in `genomeclaw_toolkit/schemas/__init__.py` is bumped (coordinate with `vep-mane-plus-clinical` plan which also bumps in Stage 2 — the two plans must agree on the final bumped value).

### Panel provenance JSON

New file: `coverage_panel_default_v2.bed.provenance.json`. Records:
- `version: "v2"`
- `created_at`
- `source.gene_list[0].source: "ACMG_SF_v3.3"` (bumped from v3.2)
- `source.gene_list[0].url: "https://doi.org/10.1016/j.gim.2025.101454"`
- New `source.gene_list[n]` entries for lifestyle anchors and MT
- `source.difficult_region_annotations.source: "GIAB_MRG_v1.00"` with download URL
- `source.exon_coordinates` (unchanged: GENCODE v44)
- `schema_version: "bed5_v1"` (the BED format schema version, distinct from the DuckDB schema)
- `region_class_values` enumeration with definitions

### `ingest.py` provenance in `coverage_qc.params_json`

When v2 panel is default: `params_json` gains `"panel_schema": "bed5_v1"` to allow downstream consumers to know the BED schema used for this run.

---

## Phase Overview

| Phase | Focus | Key deliverable | Est. days |
|---|---|---|---|
| Phase 1 | BED5 schema + `region_class` in schema, parser, store, service | All infrastructure accepts BED5; v1 panel still default | 3 |
| Phase 2 | Panel content rebuild (ACMG SF v3.3, lifestyle, MT, difficult regions) | `coverage_panel_default_v2.bed.gz`; INV-D009 test green | 3 |
| Phase 3 | Agent surface: `region_class` + `caveat` in HTTP + plugin + sysprompt | `genomeclaw_gene` carries caveat for non-standard regions | 2 |

---

## Testing Strategy

### Unit tests (all phases)

- `test_parse_regions_bed_reads_region_class` — BED5 fixture → `CoverageRow.region_class` populated.
- `test_parse_regions_bed_defaults_standard_on_missing_col` — BED4 fixture (no col 5) → `region_class = "standard"`.
- `test_coverage_qc_ddl_has_region_class` — `COVERAGE_QC_COLUMNS` contains `region_class`.
- `test_coverage_qc_model_has_region_class` — `CoverageQCRow` has `region_class` field.
- `test_write_coverage_qc_persists_region_class` — round-trip: write rows with `region_class="difficult_pseudogene"`, read back from DuckDB, assert value preserved.
- `test_query_gene_returns_region_class` — fixture store with non-standard row → `GeneAggregate.region_class` non-null.
- `test_gene_response_caveat_non_null_for_difficult` — `GeneResponse` with `region_class="difficult_pseudogene"` → `caveat` is non-null and contains "challenging".
- `test_gene_response_caveat_null_for_standard` — `region_class="standard"` → `caveat` is null.

### Provenance tests

- `test_invR001_coverage_qc_region_class_populated_on_ingest` — ingest with BED5 panel → every `coverage_qc` row has non-null `region_class`.
- `test_invR001_panel_v2_provenance_json_fields` — `coverage_panel_default_v2.bed.provenance.json` has required keys: `version`, `source.difficult_region_annotations`, `schema_version`.

### Invariant tests

- `test_invD009_panel_giab_intersection_no_standard_rows` — intersect `coverage_panel_default_v2.bed.gz` against the GIAB challenging-MRG BED; assert every row in the intersection has `region_class != "standard"`.
- `test_invE001_region_class_is_structural_not_annotational` — `CoverageQCRow.region_class` is a column in `COVERAGE_QC_COLUMNS`, not a comment or free-text field.
- `test_invC001_difficult_region_gene_response_has_caveat` — for each gene in the known-difficult list (PMS2, SMN1, HBA1, CYP21A2, GBA1, STRC, NCF1, NEB, CYP2D6), a fixture `GeneResponse` with the appropriate `region_class` carries a non-null `caveat`.

### Determinism tests

- `test_panel_build_is_deterministic` — run the build script twice against the same inputs; assert byte-equivalent output BED.

### Real-data smoke (GREEN gate for Phase 2)

Run `genomeclaw pipeline run` against the project owner's genome with the v2 panel. Verify:
- `coverage_qc` rows for PMS2, SMN1, CYP2D6, HBA1 carry the expected `region_class`.
- `GET /v1/gene/PMS2` returns `region_class = "difficult_pseudogene"` and a non-null `caveat`.
- Total row count plausible (≥ 180 genes * avg ~10 exons).

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](../bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan's final phase is not Complete until the following real-data smoke is green:

**Command**:
```bash
genomeclaw pipeline ingest
```
Run against the project owner's CRAM (mosdepth stage runs with the v2 panel).

**Pass criteria**:
- `coverage_qc.region_class` populated in the resulting store.
- PMS2, SMN1, HBA1, and similar difficult-region genes show a non-`standard` `region_class`.
- `GET /v1/gene/PMS2` returns `caveat` non-null.

**Why this smoke**: the `region_class` annotation depends on the GIAB BED intersection logic, which only produces meaningful non-`standard` values when real gene coordinates are tested against the real GIAB challenging-regions BED — synthetic fixtures cannot substitute for this spatial correctness check.

The smoke result is recorded in `work-notes.md` as part of the final phase's Completion block before the plan moves to `docs/plans/completed/`.

---

## Documentation Updates Required

- `docs/reference/INVARIANTS.md` — promote INV-D009 after Phase 2 test merges.
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.provenance.json` — new file.
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — Phase 3 update.
- Phase completion blocks in `work-notes.md`.

---

## Phase Status

| Phase | Status | Started | Completed |
|---|---|---|---|
| Phase 1 | **Complete** | 2026-05-25 | 2026-05-25 |
| Phase 2 | **Complete** | 2026-05-25 | 2026-05-25 |
| Phase 3 | **Complete (code); awaits real-data smoke** | 2026-05-25 | 2026-05-25 |

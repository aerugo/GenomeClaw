# Phase 1: BED5 Schema Bump + `region_class` Column Infrastructure

**Status**: Not started
**Estimated effort**: 3 days

---

## Objective

Extend the pipeline to accept BED5 panels and persist `region_class` end-to-end: parser → `CoverageRow` → `write_coverage_qc` → DuckDB → `query_gene` → `GeneAggregate`. The v1 panel remains the default; all emitted rows have `region_class = "standard"`. Phase 2 flips the default to v2. Phase 3 surfaces `region_class` in the HTTP + plugin layer.

At the end of Phase 1:
- A BED5 panel passed to mosdepth at ingest time produces `coverage_qc` rows with a populated `region_class` column.
- The existing BED4 panel (v1) continues to work; all rows emit `region_class = "standard"`.
- All existing toolkit tests remain green.

---

## Invariants Enforced in This Phase

- **INV-D001** — `coverage_panel_default_v1.bed.gz` is never modified. Phase 1 adds new constants alongside it; the v1 file is untouched.
- **INV-R001** — `coverage_qc` provenance: the `params_json` gains a `panel_schema` key when a BED5 panel is used, so a downstream reader knows the schema under which the row was written.
- **INV-E001** — `region_class` is a column in `COVERAGE_QC_COLUMNS` and `CoverageQCRow`, making it structural provenance. This phase lays the structural foundation; INV-D009 is fully verified in Phase 2 after the v2 panel is built.

---

## Step 1.1 — RED: Write Failing Tests

Write these tests **before any implementation**. Run the suite; confirm these tests fail for the intended reasons (missing fields / columns / parse support).

### Test file: `packages/toolkit/tests/unit/test_mosdepth_region_class.py`

```
test_coveragerow_has_region_class_field
    CoverageRow(gene="BRCA1", mean_depth=30.0, low_coverage_exons=[])
    → should have .region_class attribute; currently AttributeError (or missing field)

test_parse_regions_bed_reads_region_class_from_panel
    Fixture: a 3-row BED5 panel with region_class values
    Fixture: a mosdepth regions output (5 cols: chrom start end name mean_depth)
    Call parse_regions_bed(regions_bed, panel_bed=<fixture_path>)
    → each CoverageRow.region_class matches the panel BED fixture value

test_parse_regions_bed_defaults_standard_when_no_panel_bed
    Fixture: a 3-row mosdepth regions output (5 cols)
    Call parse_regions_bed(regions_bed, panel_bed=None)
    → each CoverageRow.region_class == "standard"

test_parse_regions_bed_defaults_standard_for_bed4_panel
    Fixture: a 3-row BED4 panel (no col 5)
    Fixture: matching mosdepth output
    Call parse_regions_bed(regions_bed, panel_bed=<bed4_fixture_path>)
    → each CoverageRow.region_class == "standard"
```

### Test file: `packages/toolkit/tests/unit/test_coverage_qc_schema.py`

```
test_coverage_qc_columns_has_region_class
    assert ("region_class", "TEXT") in COVERAGE_QC_COLUMNS

test_coverage_qc_row_has_region_class_field
    row = CoverageQCRow(gene="BRCA1", mean_depth=30.0, ...)
    row.region_class is None or == "standard"
    → currently fails (field missing)

test_coverage_qc_ddl_contains_region_class_column
    sql = coverage_qc_create_table_sql()
    assert "region_class" in sql
```

### Test file: `packages/toolkit/tests/integration/test_write_coverage_qc_region_class.py`

```
test_write_coverage_qc_persists_region_class
    Create an in-memory DuckDB store
    Write three rows: one standard, one difficult_pseudogene, one requires_dedicated_caller
    Read back; assert region_class values match

test_write_coverage_qc_null_region_class_allowed
    Write a row with region_class=None; read back; assert NULL in DB
```

### Test file: `packages/toolkit/tests/integration/test_query_gene_region_class.py`

```
test_query_gene_returns_region_class
    Fixture store with a coverage_qc row where region_class = "difficult_pseudogene"
    aggregate = query_gene(run_dir=..., symbol="PMS2")
    assert aggregate.region_class == "difficult_pseudogene"

test_query_gene_returns_none_region_class_when_absent
    Fixture store with a coverage_qc row where region_class = NULL
    aggregate = query_gene(run_dir=..., symbol="BRCA1")
    assert aggregate.region_class is None
```

### Test file: `packages/toolkit/tests/provenance/test_invR001_coverage_qc_v2.py`

```
test_invR001_coverage_qc_region_class_in_schema_columns
    # INV-R001: structural provenance — region_class must be a named column,
    # not a free-text annotation.
    assert any(name == "region_class" for name, _ in COVERAGE_QC_COLUMNS)

test_invR001_ingest_with_bed5_panel_persists_region_class
    # Full integration: ingest fixture VCF + fixture BAM + BED5 panel fixture
    # Result: coverage_qc row has non-null region_class matching the panel
    (integration test — requires genomeclaw_layout fixture)
```

Run all new tests. Confirm they fail with:
- `AttributeError: 'CoverageRow' object has no attribute 'region_class'`
- `AssertionError` on missing schema column
- etc.

---

## Step 1.2 — GREEN: Minimal Implementation

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/_mosdepth.py`

Changes:
1. `CoverageRow` dataclass: add `region_class: str = "standard"`.
2. `parse_regions_bed()`: add `panel_bed: Path | None = None` parameter.
   - When `panel_bed` is not None, open it with `gzip.open` if `.gz`, else plain open; read tab-separated rows; build `{name: region_class}` dict from col 3 → col 4 (where col 4 exists; else `"standard"`).
   - When assembling `CoverageRow`, look up each gene's exon names in the dict; set `region_class` to the first non-`standard` value found among the gene's exons (or `"standard"` if all are standard or gene not in dict).
3. Update `__all__`.

### File: `packages/toolkit/src/genomeclaw_toolkit/schemas/coverage_qc.py`

Changes:
1. `COVERAGE_QC_COLUMNS` tuple: append `("region_class", "TEXT")` after `low_coverage_exons`.
2. `CoverageQCRow` model: add `region_class: str | None = None`.

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/store.py`

Changes to `write_coverage_qc()`:
1. INSERT statement: add `region_class` as 4th domain column (after `low_coverage_exons`).
2. `params.append(...)` tuple: add `row.get("region_class", None)` as 4th domain value.

### File: `packages/toolkit/src/genomeclaw_toolkit/service/store.py`

Changes to `query_gene()`:
1. SELECT adds `region_class` to the `coverage_qc` fetch: `SELECT mean_depth, low_coverage_exons, region_class FROM coverage_qc WHERE gene = ?`.
2. `GeneAggregate` dataclass: add `region_class: str | None = None`.
3. Constructor call: pass `region_class=str(cov_row[2]) if cov_row[2] is not None else None`.

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py`

Changes:
1. `parse_regions_bed()` call at line ~432: pass `panel_bed=bed` so `region_class` is read from the panel BED.
2. Dict passed to `write_coverage_qc()` generator at lines ~476-481: add `"region_class": r.region_class`.
3. When `_panel_is_default` is True and panel v2 is active (Phase 2), add `"panel_schema": "bed5_v1"` to `coverage_params`. In Phase 1 this key is optional; add it only for BED5 panels (detect by checking if the panel BED has 5 columns in its first non-comment row).

### Schema version

`packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py` — bump `SCHEMA_VERSION`. The exact new value must be coordinated with the `vep-mane-plus-clinical` plan (both Stage 2). Until coordination is complete, mark this as **TODO: coordinate** in a comment and use a provisional value.

---

## Step 1.3 — REFACTOR

- Add inline comment to `parse_regions_bed()` explaining why `region_class` is read from the panel BED (not from mosdepth output) — mosdepth echoes back only col 3 (name) from the input BED; additional BED columns are not forwarded.
- Add docstring note to `CoverageRow` describing `region_class` as `"standard"` when not explicitly set.
- `COVERAGE_QC_COLUMNS` comment: note that `region_class` is nullable so pre-v2 pipeline runs (rows without the column populated) have NULL and are treated as `"standard"` by the service layer.

---

## Files Modified in Phase 1

| Action | File |
|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_mosdepth.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/schemas/coverage_qc.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/service/store.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py` (schema version bump — coordinate) |
| CREATE | `packages/toolkit/tests/unit/test_mosdepth_region_class.py` |
| CREATE | `packages/toolkit/tests/unit/test_coverage_qc_schema.py` |
| CREATE | `packages/toolkit/tests/integration/test_write_coverage_qc_region_class.py` |
| CREATE | `packages/toolkit/tests/integration/test_query_gene_region_class.py` |
| CREATE | `packages/toolkit/tests/provenance/test_invR001_coverage_qc_v2.py` |

---

## Verification

```bash
# From the toolkit package root:
uv run pytest packages/toolkit/tests/unit/test_mosdepth_region_class.py -v
uv run pytest packages/toolkit/tests/unit/test_coverage_qc_schema.py -v
uv run pytest packages/toolkit/tests/integration/test_write_coverage_qc_region_class.py -v
uv run pytest packages/toolkit/tests/integration/test_query_gene_region_class.py -v
uv run pytest packages/toolkit/tests/provenance/test_invR001_coverage_qc_v2.py -v
# Full suite — no regressions:
uv run pytest packages/toolkit/tests/ -v
```

---

## Completion Criteria

- [ ] All Phase 1 new tests green (RED → GREEN cycle visible).
- [ ] Full existing toolkit test suite green (zero regressions).
- [ ] `CoverageRow.region_class` field exists and defaults to `"standard"`.
- [ ] `parse_regions_bed()` accepts `panel_bed=` and reads `region_class` from BED5.
- [ ] `COVERAGE_QC_COLUMNS` includes `("region_class", "TEXT")`.
- [ ] `write_coverage_qc()` persists `region_class`.
- [ ] `query_gene()` returns `region_class` in `GeneAggregate`.
- [ ] Schema version bump note added (coordination with `vep-mane-plus-clinical` required before merge).
- [ ] `work-notes.md` updated with Phase 1 completion block.
- [ ] Phase 1 status updated in `development-plan.md`.

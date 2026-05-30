"""End-to-end `region_class` flow: schema → write → DuckDB → query (Plan 5 Phase 1).

Combines the 5 separate test files from phase-1.md into one consolidated
integration test file: schema pin, INSERT round-trip, NULL handling,
query helper round-trip, and INV-R001 structural-provenance gate.

Per coverage-panel-v2/phases/phase-1.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb


def _make_tag():
    """Construct a `ProvenanceTag` for synthetic test rows."""
    from genomeclaw_toolkit.prep.store import ProvenanceTag

    return ProvenanceTag(
        source_path="/dummy/sample.bam",
        source_sha256="a" * 64,
        tool="mosdepth",
        tool_version="0.3.10",
        params_json="{}",
        schema_version="v0.3",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Schema pin
# ---------------------------------------------------------------------------


def test_coverage_qc_columns_has_region_class() -> None:
    """`COVERAGE_QC_COLUMNS` declares `("region_class", "TEXT")` after `low_coverage_exons`."""
    from genomeclaw_toolkit.schemas.coverage_qc import COVERAGE_QC_COLUMNS

    names = [name for name, _ddl in COVERAGE_QC_COLUMNS]
    assert "region_class" in names
    assert names.index("region_class") > names.index("low_coverage_exons"), (
        "`region_class` must appear after the existing domain columns"
    )


def test_coverage_qc_row_accepts_region_class_field() -> None:
    """`CoverageQCRow` (Pydantic) accepts `region_class` as a nullable string."""
    from genomeclaw_toolkit.schemas.coverage_qc import CoverageQCRow

    row = CoverageQCRow(
        gene="PMS2",
        mean_depth=30.0,
        low_coverage_exons=[],
        region_class="difficult_pseudogene",
        source_path="/dummy/sample.bam",
        source_sha256="a" * 64,
        tool="mosdepth",
        tool_version="0.3.10",
        params_json="{}",
        schema_version="v0.3",
        created_at=datetime.now(UTC),
    )
    assert row.region_class == "difficult_pseudogene"


def test_coverage_qc_row_region_class_optional() -> None:
    """`region_class` is optional → defaults to None; pre-Phase-1 rows still valid."""
    from genomeclaw_toolkit.schemas.coverage_qc import CoverageQCRow

    row = CoverageQCRow(
        gene="BRCA1",
        mean_depth=30.0,
        low_coverage_exons=[],
        source_path="/dummy/sample.bam",
        source_sha256="a" * 64,
        tool="mosdepth",
        tool_version="0.3.10",
        params_json="{}",
        schema_version="v0.3",
        created_at=datetime.now(UTC),
    )
    assert row.region_class is None


def test_coverage_qc_ddl_contains_region_class_column() -> None:
    """`coverage_qc_create_table_sql()` includes `region_class` in the CREATE TABLE."""
    from genomeclaw_toolkit.schemas.coverage_qc import coverage_qc_create_table_sql

    sql = coverage_qc_create_table_sql()
    assert "region_class" in sql


# ---------------------------------------------------------------------------
# write_coverage_qc INSERT round-trip
# ---------------------------------------------------------------------------


def test_write_coverage_qc_persists_region_class(tmp_path: Path) -> None:
    """`write_coverage_qc` INSERTs `region_class` into DuckDB; reads back exactly."""
    from genomeclaw_toolkit.prep.store import create_store, write_coverage_qc

    db = tmp_path / "variants.duckdb"
    create_store(db)
    rows = [
        {"gene": "BRCA1", "mean_depth": 30.0, "low_coverage_exons": [], "region_class": "standard"},
        {
            "gene": "PMS2",
            "mean_depth": 28.0,
            "low_coverage_exons": ["PMS2_exon_11"],
            "region_class": "difficult_pseudogene",
        },
        {
            "gene": "SMN1",
            "mean_depth": 22.0,
            "low_coverage_exons": [],
            "region_class": "requires_dedicated_caller",
        },
    ]
    write_coverage_qc(db, rows, tag=_make_tag())

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT gene, region_class FROM coverage_qc ORDER BY gene"
            ).fetchall()
        }
    finally:
        conn.close()

    assert result == {
        "BRCA1": "standard",
        "PMS2": "difficult_pseudogene",
        "SMN1": "requires_dedicated_caller",
    }


def test_write_coverage_qc_null_region_class_allowed(tmp_path: Path) -> None:
    """A row without `region_class` writes NULL; reads back as None."""
    from genomeclaw_toolkit.prep.store import create_store, write_coverage_qc

    db = tmp_path / "variants.duckdb"
    create_store(db)
    write_coverage_qc(
        db,
        [{"gene": "BRCA1", "mean_depth": 30.0, "low_coverage_exons": []}],
        tag=_make_tag(),
    )

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT region_class FROM coverage_qc WHERE gene = 'BRCA1'"
        ).fetchone()
    finally:
        conn.close()
    assert result == (None,)


# ---------------------------------------------------------------------------
# query_gene / GeneAggregate
# ---------------------------------------------------------------------------


def test_query_gene_returns_region_class(tmp_path: Path) -> None:
    """`GeneAggregate.region_class` reflects the coverage_qc row's value."""
    from genomeclaw_toolkit.prep.store import create_store, write_coverage_qc
    from genomeclaw_toolkit.service.store import query_gene

    db = tmp_path / "variants.duckdb"
    create_store(db)
    write_coverage_qc(
        db,
        [
            {
                "gene": "PMS2",
                "mean_depth": 28.0,
                "low_coverage_exons": ["PMS2_exon_11"],
                "region_class": "difficult_pseudogene",
            }
        ],
        tag=_make_tag(),
    )

    aggregate = query_gene(run_dir=tmp_path, symbol="PMS2")
    assert aggregate is not None
    assert aggregate.region_class == "difficult_pseudogene"


def test_query_gene_returns_none_region_class_when_absent(tmp_path: Path) -> None:
    """A coverage_qc row with NULL `region_class` → `GeneAggregate.region_class is None`."""
    from genomeclaw_toolkit.prep.store import create_store, write_coverage_qc
    from genomeclaw_toolkit.service.store import query_gene

    db = tmp_path / "variants.duckdb"
    create_store(db)
    write_coverage_qc(
        db,
        [{"gene": "BRCA1", "mean_depth": 30.0, "low_coverage_exons": []}],
        tag=_make_tag(),
    )

    aggregate = query_gene(run_dir=tmp_path, symbol="BRCA1")
    assert aggregate is not None
    assert aggregate.region_class is None


# ---------------------------------------------------------------------------
# INV-R001 structural-provenance gate
# ---------------------------------------------------------------------------


def test_invR001_coverage_qc_region_class_in_schema_columns() -> None:
    """INV-R001: `region_class` is a named column, not a free-text annotation.

    The structural-provenance contract: the panel-derived class info is
    a typed schema field that survives every write/read; cannot be lost
    in a future refactor that consolidates the row dict.
    """
    from genomeclaw_toolkit.schemas.coverage_qc import COVERAGE_QC_COLUMNS

    assert any(name == "region_class" for name, _ddl in COVERAGE_QC_COLUMNS)


def test_invR001_coverage_qc_ddl_columns_match_pydantic_model() -> None:
    """INV-R001: the Pydantic `CoverageQCRow` field set equals the DDL column set.

    Mirrors `test_coverage_qc_table_ddl_lists_all_columns` in
    `test_invR001_schemas.py`; widening here re-confirms the contract
    after the `region_class` addition.
    """
    from genomeclaw_toolkit.schemas.coverage_qc import (
        COVERAGE_QC_COLUMNS,
        CoverageQCRow,
    )

    model_fields = set(CoverageQCRow.model_fields.keys())
    ddl_columns = {name for name, _ddl in COVERAGE_QC_COLUMNS}
    assert model_fields == ddl_columns

"""Pydantic model + DuckDB DDL for the ``coverage_qc`` table (spec Q7).

`mosdepth` runs at ingest against the BAM/CRAM, emits per-gene mean
coverage, and the result is materialised into ``coverage_qc`` inside the
derived store. Every row carries the seven canonical provenance columns
(`INV-R001`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CoverageQCRow(BaseModel):
    """One row of the ``coverage_qc`` table — one gene's mosdepth summary."""

    model_config = ConfigDict(extra="forbid")

    # Domain columns
    gene: str
    mean_depth: float = Field(ge=0)
    low_coverage_exons: list[str] = Field(default_factory=list)
    region_class: str | None = None
    """Per coverage-panel-v2: the gene's coverage-reliability class
    (`"standard"` / `"difficult_pseudogene"` / `"difficult_segdup"` /
    `"requires_dedicated_caller"` / `"mitochondrial"`). Nullable so
    pre-v2 rows (written before the panel BED carried column 5) decode
    as NULL — the service layer treats NULL as `"standard"`."""

    # Canonical provenance columns (the seven; INV-R001).
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool: str
    tool_version: str
    params_json: str
    schema_version: str
    created_at: datetime


COVERAGE_QC_COLUMNS: tuple[tuple[str, str], ...] = (
    # Domain
    ("gene", "TEXT NOT NULL"),
    ("mean_depth", "REAL NOT NULL"),
    ("low_coverage_exons", "TEXT[]"),
    # coverage-panel-v2 Phase 1: per-gene coverage-reliability class.
    # Nullable so pre-v2 rows (written before the panel BED carried
    # column 5) decode as NULL → service layer treats NULL as `"standard"`.
    ("region_class", "TEXT"),
    # Provenance (the seven; INV-R001)
    ("source_path", "TEXT NOT NULL"),
    ("source_sha256", "TEXT NOT NULL"),
    ("tool", "TEXT NOT NULL"),
    ("tool_version", "TEXT NOT NULL"),
    ("params_json", "TEXT NOT NULL"),
    ("schema_version", "TEXT NOT NULL"),
    ("created_at", "TIMESTAMP NOT NULL"),
)
"""DuckDB column definitions for the ``coverage_qc`` table.

The Pydantic model and this DDL must list the same columns; the
``test_coverage_qc_table_ddl_lists_all_columns`` test enforces it.
"""


def coverage_qc_create_table_sql() -> str:
    """Return the ``CREATE TABLE`` DDL for the ``coverage_qc`` table."""
    cols = ",\n    ".join(f"{name} {decl}" for name, decl in COVERAGE_QC_COLUMNS)
    return f"CREATE TABLE coverage_qc (\n    {cols}\n);"


__all__ = ["COVERAGE_QC_COLUMNS", "CoverageQCRow", "coverage_qc_create_table_sql"]

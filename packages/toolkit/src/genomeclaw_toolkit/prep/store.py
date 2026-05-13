"""DuckDB derived-store creation + provenance-column stamping.

The store at ``derived/<run-id>/variants.duckdb`` carries three tables:

- ``variants`` — VCF rows + the seven canonical provenance columns
  (`INV-R001`). Multi-allelic rows are stored as-is in v0.1; Phase 3
  splits them with ``bcftools norm``.
- ``coverage_qc`` — per-gene mean coverage from `mosdepth` (Phase 2C
  populates this; the table is created up-front so subsequent steps just
  insert into it).
- ``schema_meta`` — single-row metadata (``schema_version='v0.1'``).
  Subsequent phases bump to ``v0.2`` when annotation columns land.

A single ``ProvenanceTag`` instance flows through ``write_variants``;
splitting tags across rows is forbidden by the function signature so the
``DISTINCT (source_path, source_sha256, ...)`` count is always 1 per
write.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS, SCHEMA_VERSION
from genomeclaw_toolkit.schemas.coverage_qc import coverage_qc_create_table_sql

_VARIANT_DOMAIN_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    # (name, ddl_type, nullable)
    # Core VCF row data (v0.1).
    ("chrom", "TEXT", False),
    ("pos", "INTEGER", False),
    ("id", "TEXT", True),
    ("ref", "TEXT", False),
    ("alt", "TEXT", False),
    ("qual", "REAL", True),
    ("filter", "TEXT", True),
    ("sample_id", "TEXT", False),
    ("genotype", "TEXT", False),
    # Annotation columns (v0.2). Nullable so rows materialised before
    # annotate runs land with NULLs; rows materialised post-annotate get
    # populated values from the annotated VCF's INFO field.
    ("clinvar_id", "TEXT", True),
    ("clinvar_classification", "TEXT", True),
    ("clinvar_review_status", "TEXT", True),
    # vcfanno overlay outputs (Phase 4E / 4C.4 closure). dbSNP's RS is
    # an integer rsid in the source (e.g. ``1261322339``); stored as
    # TEXT so downstream consumers can format with the conventional
    # ``rs`` prefix without losing leading-zero / future-format
    # flexibility. gnomAD allele frequencies are REAL in [0.0, 1.0];
    # gnomad_af_popmax_pop is the population label that owns the
    # popmax value (``afr``, ``amr``, ``eas``, ``nfe``, ``sas``).
    ("dbsnp_rsid", "TEXT", True),
    ("gnomad_af_popmax", "REAL", True),
    ("gnomad_af_popmax_pop", "TEXT", True),
    ("gnomad_af_afr", "REAL", True),
    ("gnomad_af_amr", "REAL", True),
    ("gnomad_af_eas", "REAL", True),
    ("gnomad_af_nfe", "REAL", True),
    ("gnomad_af_sas", "REAL", True),
)

_VARIANTS_DDL = """
CREATE TABLE variants (
    chrom         TEXT NOT NULL,
    pos           INTEGER NOT NULL,
    id            TEXT,
    ref           TEXT NOT NULL,
    alt           TEXT NOT NULL,
    qual          REAL,
    filter        TEXT,
    sample_id     TEXT NOT NULL,
    genotype      TEXT NOT NULL,
    -- Annotation columns (v0.2; nullable, populated post-annotate)
    clinvar_id              TEXT,
    clinvar_classification  TEXT,
    clinvar_review_status   TEXT,
    -- vcfanno overlay outputs (Phase 4E / 4C.4 closure)
    dbsnp_rsid              TEXT,
    gnomad_af_popmax        REAL,
    gnomad_af_popmax_pop    TEXT,
    gnomad_af_afr           REAL,
    gnomad_af_amr           REAL,
    gnomad_af_eas           REAL,
    gnomad_af_nfe           REAL,
    gnomad_af_sas           REAL,
    -- Provenance (the canonical seven; INV-R001)
    source_path     TEXT NOT NULL,
    source_sha256   TEXT NOT NULL,
    tool            TEXT NOT NULL,
    tool_version    TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    schema_version  TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL
);
"""

_SCHEMA_META_DDL = """
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ProvenanceTag:
    """The seven canonical provenance values stamped onto every row of a write.

    A single tag per ``write_variants`` call enforces `INV-R001`'s
    structural promise: every row attributes itself to the same source
    artifact, tool invocation, and parameters.
    """

    source_path: str
    source_sha256: str
    tool: str
    tool_version: str
    params_json: str
    schema_version: str
    created_at: datetime


def create_store(path: Path) -> None:
    """Initialise an empty DuckDB derived store at ``path``.

    Creates the three canonical v0.1 tables (``variants``,
    ``coverage_qc``, ``schema_meta``) and writes the
    ``schema_version='v0.1'`` row into ``schema_meta``.

    Raises:
        FileExistsError: if ``path`` already exists. Never overwrites.
    """
    if path.exists():
        raise FileExistsError(
            f"{path} already exists; remove it deliberately if you intend "
            "to start a new run (INV-R001)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(path))
    try:
        conn.execute(_VARIANTS_DDL)
        conn.execute(coverage_qc_create_table_sql())
        conn.execute(_SCHEMA_META_DDL)
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ["schema_version", SCHEMA_VERSION],
        )
    finally:
        conn.close()


def _coerce_variant_row(row: dict[str, Any]) -> tuple[Any, ...]:
    """Project a row dict onto the domain-column tuple, validating NOT NULLs.

    Nullable columns may be omitted from the row dict entirely
    (coerced to ``None``); NOT NULL columns must be present and
    non-None. The schema-v0.2 annotation columns (``clinvar_*``) are
    nullable, so callers that haven't run ``annotate`` yet can pass
    rows without those keys.
    """
    out: list[Any] = []
    for name, _ddl, nullable in _VARIANT_DOMAIN_COLUMNS:
        if name not in row:
            if nullable:
                out.append(None)
                continue
            raise ValueError(f"missing required variant column: {name!r}")
        value = row[name]
        if value is None and not nullable:
            raise ValueError(f"variant column {name!r} is NOT NULL but received None")
        out.append(value)
    return tuple(out)


_BATCH_SIZE = 50_000
"""Rows per CSV staging batch.

Real-data ingest of the project owner's 4.8M-variant Nebula VCF surfaced
a write corruption symptom (mid-row NUL truncation) when the staging CSV
grew to ~1 GB on the USB-attached / virtiofs-mounted ``work/`` volume.
Batching to ~50k rows keeps each staging file ~10 MB — well within the
size band where exFAT / virtiofs writes complete cleanly. The COPY-per-batch
overhead is amortised; on a 100k synthetic VCF the batched path completes
in ~1.5s vs ~1.0s for a single 100k batch — a tax the larger workload
strictly needs.
"""


def write_variants(
    store_path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    tag: ProvenanceTag,
    work_dir: Path,
) -> None:
    """Stream ``rows`` into ``variants`` in batches, stamping ``tag`` on each row.

    Implementation: rows are written to a CSV staging file in batches of
    ``_BATCH_SIZE``; each full batch is closed, ``fsync``'d, bulk-loaded
    via DuckDB's ``COPY ... FROM '<csv>' (FORMAT CSV)``, then deleted.
    This is ~200× faster than the previous ``executemany`` path on real
    workloads (see
    [docs/plans/active/ingest-performance/](../../../../../../docs/plans/active/ingest-performance/))
    and stays within the per-write size band that virtiofs + exFAT
    handle reliably.

    The same `INV-R001` discipline holds: every row carries the seven
    canonical provenance columns; a single ``ProvenanceTag`` per call
    enforces uniform attribution.

    Args:
        store_path: existing DuckDB store created by ``create_store``.
        rows: streaming iterable of domain rows. Each must have all
            keys from ``_VARIANT_DOMAIN_COLUMNS``; nullable columns
            (``id``, ``qual``, ``filter``) may be ``None``. The iterable
            is consumed once.
        tag: provenance values stamped onto every row in this call.
        work_dir: writable scratch directory; staging CSVs live under
            ``<work_dir>/duckdb/`` and are deleted as each batch lands.
            DuckDB's ``temp_directory`` PRAGMA is also pointed here so
            any sort/hash spill stays on the same volume. Aligns with
            the canonical four-mount layout from
            ``docs/plans/active/storage-scratch-layout/``.
    """
    import os

    staging_dir = work_dir / "duckdb"
    staging_dir.mkdir(parents=True, exist_ok=True)

    provenance_values: tuple[Any, ...] = (
        tag.source_path,
        tag.source_sha256,
        tag.tool,
        tag.tool_version,
        tag.params_json,
        tag.schema_version,
        # ISO-like UTC string; DuckDB's CSV reader parses this into TIMESTAMP.
        tag.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )

    domain_names = [name for name, _ddl, _null in _VARIANT_DOMAIN_COLUMNS]
    columns_sql = ", ".join(domain_names + list(PROVENANCE_COLUMNS))

    conn = duckdb.connect(str(store_path))
    try:
        # Pin DuckDB's spill directory to the work mount so any sort /
        # hash overflow stays out of the container's writable layer
        # (storage-scratch-layout plan).
        conn.execute(f"PRAGMA temp_directory='{staging_dir}'")

        def _flush(batch_rows: list[tuple[Any, ...]], batch_index: int) -> None:
            staging_csv = staging_dir / f"variants-{store_path.stem}-{batch_index:06d}.csv"
            try:
                with staging_csv.open("w", newline="") as fh:
                    writer = csv.writer(fh, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
                    for full_row in batch_rows:
                        writer.writerow(["" if v is None else v for v in full_row])
                    fh.flush()
                    # fsync so the COPY below sees fully-flushed bytes —
                    # virtiofs + exFAT had write-cache issues without this.
                    os.fsync(fh.fileno())
                conn.execute(
                    f"COPY variants ({columns_sql}) FROM '{staging_csv}' "
                    "(FORMAT CSV, HEADER FALSE, NULL '', QUOTE '\"', ESCAPE '\"')"
                )
            finally:
                staging_csv.unlink(missing_ok=True)

        batch: list[tuple[Any, ...]] = []
        batch_index = 0
        for row in rows:
            domain = _coerce_variant_row(dict(row))
            batch.append((*domain, *provenance_values))
            if len(batch) >= _BATCH_SIZE:
                _flush(batch, batch_index)
                batch = []
                batch_index += 1

        if batch:
            _flush(batch, batch_index)
    finally:
        conn.close()


def write_coverage_qc(
    store_path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    tag: ProvenanceTag,
) -> None:
    """Insert ``coverage_qc`` rows, stamping ``tag`` on each row.

    Phase 2 produces ~100s of gene-level rows from `mosdepth` — well
    below the executemany cliff that motivated the variants-table COPY
    refactor. We use ``executemany`` here for simplicity. Future phases
    that emit per-exon coverage at WGS scale (10⁵+ rows) should switch
    to the CSV-staging pattern from ``write_variants``.

    Args:
        store_path: existing DuckDB store created by ``create_store``.
        rows: iterable of dicts with keys ``gene``, ``mean_depth``,
            ``low_coverage_exons``.
        tag: provenance values stamped onto every row in this call.
    """
    rows_list = list(rows)
    if not rows_list:
        return

    provenance_values: tuple[Any, ...] = (
        tag.source_path,
        tag.source_sha256,
        tag.tool,
        tag.tool_version,
        tag.params_json,
        tag.schema_version,
        tag.created_at,
    )

    sql = (
        "INSERT INTO coverage_qc ("
        "gene, mean_depth, low_coverage_exons, "
        "source_path, source_sha256, tool, tool_version, params_json, "
        "schema_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    params: list[tuple[Any, ...]] = []
    for row in rows_list:
        if "gene" not in row or "mean_depth" not in row:
            raise ValueError("coverage_qc row requires keys 'gene' and 'mean_depth'")
        params.append(
            (
                row["gene"],
                row["mean_depth"],
                row.get("low_coverage_exons", []),
                *provenance_values,
            )
        )

    conn = duckdb.connect(str(store_path))
    try:
        conn.executemany(sql, params)
    finally:
        conn.close()


__all__ = ["ProvenanceTag", "create_store", "write_coverage_qc", "write_variants"]

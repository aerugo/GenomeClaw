"""gnomAD constraint v4.1 → ``variants.gene_loeuf`` join helpers.

The constraint metrics TSV (``gnomad.v4.1.constraint_metrics.tsv``,
~1.2 MB) is the source the ``gene_loeuf`` column is populated from at
materialize time. Layout per [phase-4.md Sub-phase 4E
schema](../../../../docs/plans/active/mvp/phases/phase-4.md):

    reference/gnomad-constraint/<release>/gnomad.v4.1.constraint_metrics.tsv

The TSV has one row per (gene, transcript) pair. The canonical LOEUF
value gnomAD's browser surfaces for a gene is the row whose
``mane_select`` flag is ``true`` — that's the row this module picks.

Two functions:

- :func:`resolve_constraint_tsv` mirrors the
  ``_resolve_newest_release`` pattern in :mod:`annotate_vcfanno`: returns
  the on-disk TSV path + the release tag, or ``None`` when no constraint
  source is staged.
- :func:`join_gene_loeuf` runs a single DuckDB ``UPDATE variants SET
  gene_loeuf = ...`` against the staged TSV. The join key on the
  variants side is ``gene_symbol`` (the VEP SYMBOL column);
  on the constraint side is ``gene`` filtered to ``mane_select = true``.

`INV-D001`: the constraint TSV is read-only (``read_csv`` opens it for
reading). `INV-R001`: the caller (``materialize``) hashes the TSV and
records its path + sha256 + release tag in the materialize step's
provenance, so a rerun against the same constraint bytes reproduces the
same ``gene_loeuf`` values byte-for-byte.

The constraint TSV's column with the LOEUF value is ``lof.oe_ci.upper``
(verified 2026-05-13 against the on-disk gnomAD v4.1 file's header;
column 23 of 50+). ``mane_select`` lives at column 5; ``gene`` at
column 1. Other columns are not consulted by the join.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)


_CONSTRAINT_FILENAME = "gnomad.v4.1.constraint_metrics.tsv"


def resolve_constraint_tsv(
    reference_dir: Path, release: str | None = None
) -> tuple[Path, str] | None:
    """Resolve the gnomAD constraint TSV under ``reference_dir/gnomad-constraint/``.

    Args:
        reference_dir: toolkit reference root.
        release: optional release tag (e.g. ``"v4.1"``). When ``None``,
            picks the lexicographically-largest dir under
            ``<reference_dir>/gnomad-constraint/``.

    Returns:
        ``(tsv_path, release_tag)`` when a constraint source is on disk,
        ``None`` when ``reference_dir/gnomad-constraint/`` is absent or
        empty or doesn't contain the expected filename. The ``None``
        return is the "graceful skip" signal for the caller — the
        ``gene_loeuf`` column stays NULL on every variants row in that
        case, mirroring the same shape ``annotate_vep`` uses when no
        VEP cache is staged.
    """
    source_root = reference_dir / "gnomad-constraint"
    if not source_root.exists():
        return None

    if release is not None:
        candidate = source_root / release / _CONSTRAINT_FILENAME
        if candidate.exists():
            return candidate, release
        return None

    releases = sorted(p.name for p in source_root.iterdir() if p.is_dir())
    if not releases:
        return None
    chosen = releases[-1]
    candidate = source_root / chosen / _CONSTRAINT_FILENAME
    if candidate.exists():
        return candidate, chosen
    return None


def join_gene_loeuf(store_path: Path, tsv_path: Path) -> int:
    """Run ``UPDATE variants SET gene_loeuf = ...`` from the constraint TSV.

    The join filters the constraint TSV to MANE Select transcript rows
    only (the canonical LOEUF value per gene) and matches on the
    variants table's ``gene_symbol`` column (populated by VEP via the
    CSQ ``SYMBOL`` field).

    Args:
        store_path: ``variants.duckdb`` to update.
        tsv_path: path to the staged ``gnomad.v4.1.constraint_metrics.tsv``.

    Returns:
        Number of variants rows whose ``gene_loeuf`` was updated (i.e.
        rows whose ``gene_symbol`` matched a MANE Select gene in the
        constraint TSV). Useful for sanity-check logging.

    Notes:
        - The TSV has mixed types (booleans-as-strings, numerics-with-NA);
          we read ``all_varchar=true`` and cast inside the query to
          dodge DuckDB's auto-type-detection getting confused by the
          handful of "NA" cells in the otherwise-numeric columns.
        - ``GROUP BY gene`` belt-and-suspenders: defends against (very
          unlikely) duplicate MANE Select rows for the same gene by
          taking the first row's value. The real gnomAD data has at
          most one MANE Select transcript per gene.
    """
    conn = duckdb.connect(str(store_path))
    try:
        # Build the LOEUF map as a temp table so the UPDATE-FROM has a
        # cleanly-typed source. ``read_csv(?)`` accepts the path as a
        # bound parameter so the SQL is injection-safe.
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE _gene_loeuf AS
            SELECT
                gene,
                ANY_VALUE(TRY_CAST("lof.oe_ci.upper" AS DOUBLE)) AS loeuf
            FROM read_csv(
                ?,
                delim='\t',
                header=true,
                nullstr=['NA', ''],
                all_varchar=true
            )
            WHERE mane_select = 'true'
            GROUP BY gene
            """,
            [str(tsv_path)],
        )
        # Count rows about to be updated so the caller can surface it.
        count_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM variants v
            JOIN _gene_loeuf c ON v.gene_symbol = c.gene
            WHERE c.loeuf IS NOT NULL
            """
        ).fetchone()
        update_count = int(count_row[0]) if count_row else 0

        conn.execute(
            """
            UPDATE variants
            SET gene_loeuf = c.loeuf
            FROM _gene_loeuf c
            WHERE c.gene = variants.gene_symbol
            """
        )
    finally:
        conn.close()

    log.info("gene_loeuf join: %d variant rows updated from %s", update_count, tsv_path)
    return update_count


__all__ = [
    "resolve_constraint_tsv",
    "join_gene_loeuf",
]

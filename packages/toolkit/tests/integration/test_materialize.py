"""Phase 3 — ``genomeclaw pipeline materialize`` orchestrator tests.

``materialize(run_dir, ...)`` rewrites the variants table in
``run_dir/variants.duckdb`` from the normalized VCF produced by
``normalize``. Multi-allelic rows that ingest stored as-is are now split
into single-alt rows.

Coverage_qc + schema_meta tables are preserved (materialize only
touches ``variants``).
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest


@pytest.mark.needs_bio
def test_materialize_splits_multiallelic_rows_in_variants_table(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """After materialize, the chr17 multi-allelic row → two single-alt rows."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="mat-001",
    )

    # Before normalize+materialize: variants table has the multi-allelic row.
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        before = conn.execute(
            "SELECT chrom, pos, alt FROM variants ORDER BY chrom, pos, alt"
        ).fetchall()
    finally:
        conn.close()
    multi_row = next((r for r in before if r[2] == "C,G"), None)
    assert multi_row is not None, "fixture should have a multi-allelic row pre-normalize"

    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    # After: 6 single-alt rows, no comma-separated alt fields.
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        after = conn.execute(
            "SELECT chrom, pos, alt FROM variants ORDER BY chrom, pos, alt"
        ).fetchall()
    finally:
        conn.close()
    assert len(after) == 6
    for _chrom, _pos, alt in after:
        assert "," not in alt


@pytest.mark.needs_bio
def test_invR001_materialize_provenance_columns_populated(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Every row after materialize carries the seven canonical provenance columns."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize
    from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="mat-001",
    )
    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    cols_sql = ", ".join(PROVENANCE_COLUMNS)
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute(f"SELECT {cols_sql} FROM variants").fetchall()
    finally:
        conn.close()

    assert len(rows) == 6
    for row in rows:
        for value in row:
            assert value is not None


@pytest.mark.needs_bio
def test_materialize_uses_source_vcf_as_per_row_provenance(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``source_path`` / ``source_sha256`` on materialised rows point at the **source** VCF.

    The intermediate ``normalized.vcf.gz`` is non-byte-stable across
    runs (bcftools embeds the wall-clock date in its header), so per-row
    provenance attributes to the canonical genome file instead. The
    chain to the normalize step is recorded in ``provenance.json``.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="mat-001",
    )
    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        sources = conn.execute(
            "SELECT DISTINCT source_path, source_sha256 FROM variants"
        ).fetchall()
    finally:
        conn.close()
    assert len(sources) == 1
    src_path, src_sha = sources[0]
    assert src_path == str(tiny_vcf_gz)
    # SHA256 of the source VCF, deterministic.
    import hashlib

    assert src_sha == hashlib.sha256(tiny_vcf_gz.read_bytes()).hexdigest()


@pytest.mark.needs_bio
def test_materialize_appends_step_to_provenance(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``provenance.json`` gains a ``materialize`` step with normalized-VCF input identity."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="mat-001",
    )
    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    provenance = json.loads((run_dir / "provenance.json").read_text())
    step_names = [s["step"] for s in provenance["steps"]]
    assert step_names == ["ingest", "bcftools-stats", "normalize", "materialize"]


@pytest.mark.needs_bio
def test_materialize_preserves_coverage_qc_table(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    tiny_genes_bed: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """Materialize touches only ``variants``; ``coverage_qc`` rows from ingest survive."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="mat-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
    )
    # Coverage_qc populated by ingest's mosdepth step.
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        before = conn.execute("SELECT gene FROM coverage_qc ORDER BY gene").fetchall()
    finally:
        conn.close()
    assert {r[0] for r in before} == {"BRCA1", "BRCA2", "CYP2D6"}

    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        after = conn.execute("SELECT gene FROM coverage_qc ORDER BY gene").fetchall()
        schema_v = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()
    assert before == after
    assert schema_v is not None
    assert schema_v[0] == SCHEMA_VERSION


@pytest.mark.needs_bio
def test_materialize_refuses_when_normalized_vcf_missing(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``materialize`` requires ``normalize`` to have run first."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="mat-001",
    )
    with pytest.raises(FileNotFoundError, match="normalized"):
        materialize(run_dir=run_dir)

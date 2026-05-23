"""Phase 2 — ingest with BAM (mosdepth + bcftools stats integration).

Covers Phase-2 cases 19 (manifest's ``qc.bcftools_stats`` populated),
20 (``coverage_qc`` table populated from mosdepth), and 21 (BAM SHA256
unchanged after mosdepth runs). Also covers case 8 (determinism scaffold
— two ingests with the same input + same fixed clock produce row-equivalent
DuckDB stores).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_current(derived: Path) -> Path:
    target = os.readlink(derived / "CURRENT")
    return (derived / target).resolve()


# ---------------------------------------------------------------------------
# Cases 19, 20, 21 — happy path with BAM
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_invR001_ingest_writes_qc_bcftools_stats_to_manifest(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    tiny_genes_bed: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """Case 19: ``manifest.qc.bcftools_stats`` has ``ts_tv_ratio`` / ``n_snps`` / ``n_indels``."""
    from genomeclaw_toolkit.prep.ingest import ingest

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
    )

    manifest = json.loads((run_dir / "manifest.json").read_text())
    qc = manifest["qc"]["bcftools_stats"]
    assert "ts_tv_ratio" in qc
    assert "n_snps" in qc
    assert "n_indels" in qc
    assert qc["n_snps"] >= 0
    assert qc["n_indels"] >= 0
    assert qc["ts_tv_ratio"] >= 0


@pytest.mark.needs_bio
def test_coverage_qc_table_populated_from_mosdepth(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    tiny_genes_bed: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """Case 20: one ``coverage_qc`` row per BED gene; provenance columns populated."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT gene, mean_depth FROM coverage_qc ORDER BY gene").fetchall()
        cols_sql = ", ".join(PROVENANCE_COLUMNS)
        prov = conn.execute(f"SELECT {cols_sql} FROM coverage_qc").fetchall()
    finally:
        conn.close()

    gene_names = {r[0] for r in rows}
    assert {"BRCA1", "BRCA2", "CYP2D6"} == gene_names
    for _gene, mean_depth in rows:
        assert mean_depth >= 0.0
    # INV-R001: every coverage_qc row carries the seven canonical provenance columns.
    assert len(prov) == 3
    for row in prov:
        for value in row:
            assert value is not None


@pytest.mark.needs_bio
def test_invD001_bam_unchanged_after_ingest(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    tiny_genes_bed: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """Case 21: BAM SHA256 unchanged after ingest (mosdepth must not mutate input)."""
    from genomeclaw_toolkit.prep.ingest import ingest

    bam_sha_before = _sha256(tiny_bam)
    bai_path = tiny_bam.with_suffix(tiny_bam.suffix + ".bai")
    bai_sha_before = _sha256(bai_path) if bai_path.exists() else None

    ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
    )

    assert _sha256(tiny_bam) == bam_sha_before
    if bai_sha_before is not None:
        assert _sha256(bai_path) == bai_sha_before


@pytest.mark.needs_bio
def test_provenance_json_records_bcftools_stats_and_mosdepth_steps(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    tiny_genes_bed: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """Provenance trail has 3 steps when BAM is provided.

    Steps: ``ingest``, ``bcftools-stats``, ``mosdepth-coverage``.
    """
    from genomeclaw_toolkit.prep.ingest import ingest

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
    )

    provenance = json.loads((run_dir / "provenance.json").read_text())
    step_names = [s["step"] for s in provenance["steps"]]
    assert step_names == ["ingest", "bcftools-stats", "mosdepth-coverage"]


@pytest.mark.needs_bio
def test_ingest_bam_without_bed_auto_engages_default_panel(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """``bam`` without ``bed`` auto-engages the bundled default coverage panel.

    Pre-Phase-2 behaviour raised ValueError("bed is required"). Phase-2
    changed the contract: the default panel BED is used automatically and
    the ingest succeeds; ``coverage_qc`` is populated from mosdepth output.
    """
    from genomeclaw_toolkit.prep.ingest import ingest

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
        bam=tiny_bam,
        # No bed= — should auto-engage the default panel
    )

    # A derived store must have been written.
    import duckdb

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row_count = conn.execute("SELECT COUNT(*) FROM coverage_qc").fetchone()
    finally:
        conn.close()

    # The default panel has ~160 genes × 8 placeholder exons = 1280 BED rows;
    # mosdepth emits one output row per BED row. We just assert it's non-zero.
    assert row_count is not None and row_count[0] > 0, (
        "Expected coverage_qc rows from auto-engaged default panel; got 0"
    )


# ---------------------------------------------------------------------------
# Case 8 — determinism scaffold
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_ingest_byte_equivalent_on_rerun_with_fixed_clock(
    tiny_vcf_gz: Path,
    tiny_bam: Path,
    tiny_genes_bed: Path,
    tmp_path: Path,
) -> None:
    """Case 8 (scaffold): two ingests with the same inputs + fixed clock produce
    matching variant + coverage row sets.

    The DuckDB file's bytes may differ at internal-block boundaries
    (DuckDB writes per-segment compression headers that aren't byte-stable
    across runs even with identical inputs). The plan calls this out as
    "modulo declared non-determinism"; for Phase 2 we assert
    *row-equivalence* rather than file-byte-equivalence. Phase 3
    promotes this to byte-equivalence once the normalize step lands.
    """
    from genomeclaw_toolkit.prep.ingest import ingest

    fixed_clock = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)

    derived_a = tmp_path / "derived-a"
    derived_b = tmp_path / "derived-b"
    derived_a.mkdir()
    derived_b.mkdir()

    run_a = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=tmp_path,
        derived_root=derived_a,
        sample_id="det-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
        started_at=fixed_clock,
    )
    run_b = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=tmp_path,
        derived_root=derived_b,
        sample_id="det-001",
        bam=tiny_bam,
        bed=tiny_genes_bed,
        started_at=fixed_clock,
    )

    # Same fixed clock + same input → identical run-id.
    assert run_a.name == run_b.name

    # variants table: same row count + same domain values.
    def _variants(path: Path) -> list[tuple]:
        conn = duckdb.connect(str(path / "variants.duckdb"), read_only=True)
        try:
            return conn.execute(
                "SELECT chrom, pos, id, ref, alt, qual, filter, sample_id, genotype "
                "FROM variants ORDER BY chrom, pos, alt"
            ).fetchall()
        finally:
            conn.close()

    assert _variants(run_a) == _variants(run_b)

    # coverage_qc: same row set.
    def _coverage(path: Path) -> list[tuple]:
        conn = duckdb.connect(str(path / "variants.duckdb"), read_only=True)
        try:
            return conn.execute("SELECT gene, mean_depth FROM coverage_qc ORDER BY gene").fetchall()
        finally:
            conn.close()

    assert _coverage(run_a) == _coverage(run_b)

    # manifest.created_at + run_id agree byte-for-byte (timestamp-stable).
    manifest_a = json.loads((run_a / "manifest.json").read_text())
    manifest_b = json.loads((run_b / "manifest.json").read_text())
    assert manifest_a["created_at"] == manifest_b["created_at"]
    assert manifest_a["run_id"] == manifest_b["run_id"]

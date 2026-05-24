"""Phase 2 — ``mosdepth`` wrapper + per-region BED parser tests.

Covers Phase-2 cases 20 (`coverage_qc` table populated with one row per
gene in the BED) and 21 (BAM + .bai SHA256 unchanged after `mosdepth`).
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Real ``mosdepth --no-per-base --by genes.bed`` output, produced inside
# the toolkit image against a synthetic 4-read BAM.
_REGIONS_BED_TEXT = (
    "chr17\t43044294\t43125483\tBRCA1\t0.00\n"
    "chr13\t32315473\t32400266\tBRCA2\t0.00\n"
    "chr22\t42126498\t42130810\tCYP2D6\t0.02\n"
)


def test_parse_regions_bed_yields_gene_rows(tmp_path: Path) -> None:
    """Pure parser: ``regions.bed.gz`` → ``CoverageRow``s in BED order."""
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    bed = tmp_path / "mos.regions.bed.gz"
    bed.write_bytes(gzip.compress(_REGIONS_BED_TEXT.encode()))

    rows = list(parse_regions_bed(bed))

    assert len(rows) == 3
    assert rows[0].gene == "BRCA1"
    assert rows[0].mean_depth == pytest.approx(0.0)
    assert rows[0].low_coverage_exons == []
    assert rows[2].gene == "CYP2D6"
    assert rows[2].mean_depth == pytest.approx(0.02)


def test_parse_regions_bed_handles_empty_bed(tmp_path: Path) -> None:
    """An empty input is allowed (returns empty list, not an error)."""
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    bed = tmp_path / "empty.regions.bed.gz"
    bed.write_bytes(gzip.compress(b""))

    assert list(parse_regions_bed(bed)) == []


def test_parse_regions_bed_aggregates_per_exon_labels_into_gene_rows(tmp_path: Path) -> None:
    """Per-exon BED labels ("GENE_exon_N") collapse to one row per gene.

    Mean depth is the un-weighted average across the gene's exons;
    `low_coverage_exons` is the sorted list of per-exon labels whose
    depth falls below the configured threshold (default 20×).
    """
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    bed_text = (
        "chr1\t100\t200\tBRCA1_exon_1\t30.0\n"
        "chr1\t300\t400\tBRCA1_exon_2\t10.0\n"  # below threshold
        "chr1\t500\t600\tBRCA1_exon_3\t40.0\n"
        "chr2\t100\t200\tAPOE_exon_1\t25.0\n"
        "chr3\t100\t200\tRARE_exon_1\t5.0\n"   # below threshold
    )
    bed = tmp_path / "mos.regions.bed.gz"
    bed.write_bytes(gzip.compress(bed_text.encode()))

    rows = list(parse_regions_bed(bed, low_coverage_threshold=20.0))

    assert len(rows) == 3  # 3 distinct genes
    by_gene = {r.gene: r for r in rows}
    assert "BRCA1" in by_gene
    assert by_gene["BRCA1"].mean_depth == pytest.approx((30.0 + 10.0 + 40.0) / 3)
    assert by_gene["BRCA1"].low_coverage_exons == ["BRCA1_exon_2"]
    assert by_gene["APOE"].mean_depth == pytest.approx(25.0)
    assert by_gene["APOE"].low_coverage_exons == []  # >= threshold
    assert by_gene["RARE"].mean_depth == pytest.approx(5.0)
    assert by_gene["RARE"].low_coverage_exons == ["RARE_exon_1"]


def test_parse_regions_bed_rejects_malformed_row(tmp_path: Path) -> None:
    """A row with fewer than 5 tab-separated columns is a hard error."""
    from genomeclaw_toolkit.prep._mosdepth import (
        MosdepthParseError,
        parse_regions_bed,
    )

    bed = tmp_path / "bad.regions.bed.gz"
    bed.write_bytes(gzip.compress(b"chr1\t100\t200\tFOO\n"))  # missing depth

    with pytest.raises(MosdepthParseError):
        list(parse_regions_bed(bed))


@pytest.mark.needs_bio
def test_run_mosdepth_writes_regions_bed_and_summary(
    tiny_bam: Path, tiny_genes_bed: Path, tmp_path: Path
) -> None:
    """End-to-end: ``run_mosdepth`` produces the expected output files."""
    from genomeclaw_toolkit.prep._mosdepth import run_mosdepth

    out_prefix = tmp_path / "mos"
    result = run_mosdepth(
        bam=tiny_bam,
        bed=tiny_genes_bed,
        out_prefix=out_prefix,
    )

    assert result.regions_bed.exists()
    assert result.regions_bed.name == "mos.regions.bed.gz"
    assert result.summary.exists()


@pytest.mark.needs_bio
def test_run_mosdepth_rows_match_bed_genes(
    tiny_bam: Path, tiny_genes_bed: Path, tmp_path: Path
) -> None:
    """Case 20 (structural): one ``coverage_qc``-shaped row per BED gene."""
    from genomeclaw_toolkit.prep._mosdepth import (
        parse_regions_bed,
        run_mosdepth,
    )

    out_prefix = tmp_path / "mos"
    result = run_mosdepth(bam=tiny_bam, bed=tiny_genes_bed, out_prefix=out_prefix)

    rows = list(parse_regions_bed(result.regions_bed))
    gene_names = {r.gene for r in rows}
    assert {"BRCA1", "BRCA2", "CYP2D6"} <= gene_names

    for r in rows:
        assert r.mean_depth >= 0.0
        # Phase-2 gene-level BEDs don't compute exon-level coverage; this
        # field is reserved for Phase 4 when exon BEDs land.
        assert r.low_coverage_exons == []


@pytest.mark.needs_bio
def test_invD001_bam_unchanged_after_mosdepth(
    tiny_bam: Path, tiny_genes_bed: Path, tmp_path: Path
) -> None:
    """Case 21 (`INV-D001`): BAM + .bai SHA256 unchanged after mosdepth runs."""
    from genomeclaw_toolkit.prep._mosdepth import run_mosdepth

    bam_sha_before = _sha256(tiny_bam)
    bai_path = tiny_bam.with_suffix(tiny_bam.suffix + ".bai")
    bai_sha_before = _sha256(bai_path) if bai_path.exists() else None

    run_mosdepth(bam=tiny_bam, bed=tiny_genes_bed, out_prefix=tmp_path / "mos")

    assert _sha256(tiny_bam) == bam_sha_before
    if bai_sha_before is not None:
        assert _sha256(bai_path) == bai_sha_before

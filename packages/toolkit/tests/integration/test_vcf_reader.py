"""Phase 2 — minimal VCF reader (header + variant rows).

Sub-phase 2C-B-1 scope: enough VCF parsing to feed the reference-build
sniffer (already in 2A) and the Phase-2 store writer (in 2C-A) — i.e.
``read_contigs(path)`` + ``iter_variant_rows(path)``. No multi-sample
support, no fancy INFO/FORMAT field handling beyond pulling out
``GT``; Phase 3's ``bcftools norm`` step is where the real VCF
processing happens.

These tests are pure-Python: they use ``gzip.compress`` for the
test fixtures. The reader treats vanilla gzip and bgzip identically for
sequential reads (the bgzip multi-block layout is gzip-compatible). A
needs_bio integration test in sub-phase 2C-B-2 will exercise the reader
against a real bgzipped fixture written by ``bcftools view -Oz``.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

_TINY_VCF = """\
##fileformat=VCFv4.2
##contig=<ID=chr1,length=248956422>
##contig=<ID=chr17,length=83257441>
##INFO=<ID=DP,Number=1,Type=Integer,Description="depth">
##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ttest-001
chr1\t1000\trs1\tA\tG\t60\tPASS\t.\tGT\t0/1
chr1\t2000\t.\tC\tT\t.\tPASS\t.\tGT\t1/1
chr17\t43044295\trs28897672\tG\tA\t100\tPASS\t.\tGT\t0/1
chr17\t43044300\t.\tT\tC,G\t50\tPASS\t.\tGT\t1/2
chr17\t43094000\trs28897696\tA\tG\t75\tPASS\t.\tGT\t0/1
"""

_AMBIGUOUS_VCF = """\
##fileformat=VCFv4.2
##contig=<ID=chr1,length=1>
##contig=<ID=chr2,length=2>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
chr1\t1\trs1\tA\tG\t.\tPASS\t.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_vcf_path(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.vcf"
    p.write_text(_TINY_VCF)
    return p


@pytest.fixture
def tiny_vcf_gz_path(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.vcf.gz"
    p.write_bytes(gzip.compress(_TINY_VCF.encode()))
    return p


@pytest.fixture
def ambiguous_vcf_gz_path(tmp_path: Path) -> Path:
    p = tmp_path / "ambig.vcf.gz"
    p.write_bytes(gzip.compress(_AMBIGUOUS_VCF.encode()))
    return p


# ---------------------------------------------------------------------------
# read_contigs
# ---------------------------------------------------------------------------


def test_read_contigs_extracts_id_and_length_from_grch38_vcf_gz(
    tiny_vcf_gz_path: Path,
) -> None:
    from genomeclaw_toolkit.prep._vcf import read_contigs

    contigs = read_contigs(tiny_vcf_gz_path)
    assert contigs == [("chr1", 248956422), ("chr17", 83257441)]


def test_read_contigs_works_on_uncompressed_vcf(tiny_vcf_path: Path) -> None:
    """The reader transparently handles plain ``.vcf`` files too."""
    from genomeclaw_toolkit.prep._vcf import read_contigs

    contigs = read_contigs(tiny_vcf_path)
    assert contigs == [("chr1", 248956422), ("chr17", 83257441)]


def test_read_contigs_pairs_with_reference_build_sniffer(
    tiny_vcf_gz_path: Path,
) -> None:
    """End-to-end: contigs from the reader feed the reference-build sniffer."""
    from genomeclaw_toolkit.prep._vcf import read_contigs
    from genomeclaw_toolkit.prep.reference_build import sniff_reference_build

    assert sniff_reference_build(read_contigs(tiny_vcf_gz_path)) == "grch38"


def test_read_contigs_returns_empty_when_header_lacks_contig_lines(
    tmp_path: Path,
) -> None:
    """A header-only VCF with no ``##contig=`` lines returns ``[]`` (not an error)."""
    from genomeclaw_toolkit.prep._vcf import read_contigs

    p = tmp_path / "no-contig.vcf"
    p.write_text("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
    assert read_contigs(p) == []


def test_read_contigs_ignores_malformed_contig_lines(tmp_path: Path) -> None:
    """A ``##contig=`` line missing ``length=`` is silently skipped (not raised)."""
    from genomeclaw_toolkit.prep._vcf import read_contigs

    p = tmp_path / "weird.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "##contig=<ID=chrJUNK>\n"  # no length
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    assert read_contigs(p) == [("chr1", 248956422)]


# ---------------------------------------------------------------------------
# iter_variant_rows
# ---------------------------------------------------------------------------


def test_iter_variant_rows_yields_one_dict_per_data_line(
    tiny_vcf_gz_path: Path,
) -> None:
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    rows = list(iter_variant_rows(tiny_vcf_gz_path))
    assert len(rows) == 5

    first = rows[0]
    assert first["chrom"] == "chr1"
    assert first["pos"] == 1000
    assert first["id"] == "rs1"
    assert first["ref"] == "A"
    assert first["alt"] == "G"
    assert first["qual"] == 60.0
    assert first["filter"] == "PASS"
    assert first["sample_id"] == "test-001"
    assert first["genotype"] == "0/1"


def test_iter_variant_rows_normalises_dot_id_and_dot_qual_to_none(
    tiny_vcf_gz_path: Path,
) -> None:
    """The VCF spec uses ``.`` for missing values; the reader yields ``None``."""
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    rows = list(iter_variant_rows(tiny_vcf_gz_path))
    # Row 2 in the fixture: chr1\t2000\t.\tC\tT\t.\tPASS...
    second = rows[1]
    assert second["id"] is None
    assert second["qual"] is None


def test_iter_variant_rows_preserves_multiallelic_alt_as_is(
    tiny_vcf_gz_path: Path,
) -> None:
    """Phase 2 stores multi-allelic rows as-is (Phase 3 ``norm`` splits them)."""
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    rows = list(iter_variant_rows(tiny_vcf_gz_path))
    # Row 4: chr17\t43044300\t.\tT\tC,G\t50\tPASS...\tGT\t1/2
    multi = rows[3]
    assert multi["alt"] == "C,G"
    assert multi["genotype"] == "1/2"


def test_iter_variant_rows_extracts_gt_from_format_column_in_any_position(
    tmp_path: Path,
) -> None:
    """``GT`` may not be the first FORMAT field; the reader finds it by name."""
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    p = tmp_path / "gt-second.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ts1\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\tDP:GT\t30:0/1\n"
    )
    rows = list(iter_variant_rows(p))
    assert rows == [
        {
            "chrom": "chr1",
            "pos": 100,
            "id": None,
            "ref": "A",
            "alt": "G",
            "qual": None,
            "filter": "PASS",
            "sample_id": "s1",
            "genotype": "0/1",
        }
    ]


def test_iter_variant_rows_rejects_multisample_vcf_for_phase_2(
    tmp_path: Path,
) -> None:
    """Phase 2 is single-sample. Multi-sample VCFs raise a clear error."""
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    p = tmp_path / "multi.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ts1\ts2\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\t1/1\n"
    )
    with pytest.raises(ValueError, match="single-sample"):
        list(iter_variant_rows(p))


def test_iter_variant_rows_handles_zero_data_rows(tmp_path: Path) -> None:
    """A header-only VCF yields no rows (and is not an error)."""
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    p = tmp_path / "header-only.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    assert list(iter_variant_rows(p)) == []


def test_iter_variant_rows_handles_no_format_column(tmp_path: Path) -> None:
    """Sites-only VCFs (no FORMAT/sample columns) yield rows with ``genotype=None``.

    Such VCFs come up in annotation-only workflows; Phase 2's ingest will
    refuse them at the ingest layer (single-sample required), but the
    *reader* itself doesn't have to.
    """
    from genomeclaw_toolkit.prep._vcf import iter_variant_rows

    p = tmp_path / "sites-only.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\n"
    )
    rows = list(iter_variant_rows(p))
    assert len(rows) == 1
    assert rows[0]["sample_id"] is None
    assert rows[0]["genotype"] is None

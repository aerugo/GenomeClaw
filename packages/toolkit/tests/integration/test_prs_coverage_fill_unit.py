"""Phase 1 RED — pure-unit tests for ``coverage_fill`` primitives.

No subprocess, no docker. These tests exercise the deterministic, side-effect-
free helpers that the Tier 1 + Tier 2 orchestrators are built from:

- ``_parse_prune_in_to_alleles`` — plink2 prune-in lines (``CHROM:POS:REF:ALT``)
  → bcftools alleles-tsv rows (``chrCHROM\\tPOS\\tREF,ALT``) with the
  panel→CRAM chromosome-prefix rewrite the chr22 prove-out proved necessary.
- ``_summarize_tier1_qc`` — single-pass VCF walk emitting the QC-summary
  dict with the keys ``INV-R001`` requires on ``tier1.qc.json``.
- ``_tier1_cache_path`` — deterministic cache path keyed by
  (sample_id, panel_version).

Each test maps to one acceptance check in
[phase-1.md](../../../../docs/plans/active/prs-input-coverage-fill/phases/phase-1.md).
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest


def test_parse_prune_in_to_alleles_rewrites_chrom_prefix() -> None:
    """Each ``N:POS:REF:ALT`` line becomes ``chrN\\tPOS\\tREF,ALT`` (panel→CRAM rewrite).

    Verified upstream layout (chr22 prove-out, 2026-05-18): HGDP+1kGP panel
    uses ``1,2,…,22,X,Y`` chromosome naming; user CRAM + GRCh38 FASTA use
    ``chr1,chr2,…,chr22,chrX,chrY,chrM``. The TSV emitted for bcftools
    ``--regions-file`` and ``--targets-file`` must carry the CRAM prefix.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _parse_prune_in_to_alleles

    lines = ["22:10664069:T:A", "22:10685063:G:T", "1:1000:A:G"]

    rows = _parse_prune_in_to_alleles(lines)

    assert rows == [
        ("chr22", 10664069, "T", "A"),
        ("chr22", 10685063, "G", "T"),
        ("chr1", 1000, "A", "G"),
    ]


def test_parse_prune_in_skips_malformed_lines() -> None:
    """Lines that don't split into 4 colon-separated fields are skipped, not raised.

    plink2's prune-in format is well-defined for the HGDP+1kGP panel (the
    chr22 prove-out had zero malformed IDs across 6,812 records). Defensive
    skip keeps the materialize step resilient if a future panel ships a
    variant ID with a colon embedded in REF/ALT.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _parse_prune_in_to_alleles

    lines = [
        "22:10664069:T:A",  # ok
        "",  # empty
        "22:not_an_id",  # too few fields
        "22:10685063:G:T",  # ok
        "22:10:G:T:weird:extra",  # too many fields
    ]

    rows = _parse_prune_in_to_alleles(lines)

    # Only the two well-formed lines survive.
    assert rows == [("chr22", 10664069, "T", "A"), ("chr22", 10685063, "G", "T")]


def test_summarize_tier1_qc_counts_gt_classes(tmp_path: Path) -> None:
    """Walk a tiny synthetic VCF, return correct REF/REF + het + hom-alt + missing counts.

    Mirrors the chr22 prove-out distribution shape: 84.5% REF/REF, 9.5% het,
    5.1% hom-alt, 0.9% missing. The function reads gzipped VCFs (the canonical
    ``tier1.vcf.gz`` shape).
    """
    from genomeclaw_toolkit.prep.coverage_fill import _summarize_tier1_qc

    vcf_path = tmp_path / "tier1.vcf.gz"
    vcf_text = (
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr22,length=50818468>\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"genotype\">\n"
        "##FORMAT=<ID=DP,Number=1,Type=Integer,Description=\"depth\">\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tMPNRGLQ2K\n"
        # 5 REF/REF, 2 het, 1 hom-alt, 1 missing — matches chr22 ratios on a small scale.
        "chr22\t10001\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/0:30\n"
        "chr22\t10002\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/0:25\n"
        "chr22\t10003\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/0:28\n"
        "chr22\t10004\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/0:32\n"
        "chr22\t10005\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/0:29\n"
        "chr22\t10006\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:27\n"
        "chr22\t10007\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:31\n"
        "chr22\t10008\t.\tA\tG\t.\tPASS\t.\tGT:DP\t1/1:26\n"
        "chr22\t10009\t.\tA\tG\t.\tPASS\t.\tGT:DP\t./.:0\n"
    )
    with gzip.open(vcf_path, "wt") as fh:
        fh.write(vcf_text)

    summary = _summarize_tier1_qc(vcf_path)

    assert summary["total_records"] == 9
    assert summary["gt_distribution"]["0/0"] == 5
    assert summary["gt_distribution"]["0/1"] == 2
    assert summary["gt_distribution"]["1/1"] == 1
    assert summary["gt_distribution"]["./."] == 1
    # missing_rate is 1/9 ≈ 0.111
    assert summary["missing_rate"] == pytest.approx(1 / 9, abs=1e-6)
    # mean DP across 8 callable records is (30+25+28+32+29+27+31+26)/8 = 28.5
    assert summary["mean_dp"] == pytest.approx(28.5, abs=1e-2)
    # per-chrom counts populate
    assert summary["per_chrom_record_counts"]["chr22"] == 9


def test_summarize_tier1_qc_handles_empty_vcf(tmp_path: Path) -> None:
    """An empty VCF returns all counts at 0, no ZeroDivisionError on mean_dp."""
    from genomeclaw_toolkit.prep.coverage_fill import _summarize_tier1_qc

    vcf_path = tmp_path / "empty.vcf.gz"
    with gzip.open(vcf_path, "wt") as fh:
        fh.write(
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=chr22,length=50818468>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ts\n"
        )

    summary = _summarize_tier1_qc(vcf_path)

    assert summary["total_records"] == 0
    assert summary["gt_distribution"] == {"0/0": 0, "0/1": 0, "1/1": 0, "./.": 0}
    assert summary["missing_rate"] == 0.0
    assert summary["mean_dp"] == 0.0
    assert summary["per_chrom_record_counts"] == {}


def test_tier1_cache_path_is_byte_stable(tmp_path: Path) -> None:
    """``_tier1_cache_path`` is a pure function of (derived_root, sample_id, panel_version).

    Same inputs → same path. The deterministic layout is the contract the
    cache-hit logic in Phase 2's ``prs compute`` relies on.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _tier1_cache_path

    derived = tmp_path / "derived"
    p1 = _tier1_cache_path(derived_root=derived, sample_id="MPNRGLQ2K", panel_version="v1")
    p2 = _tier1_cache_path(derived_root=derived, sample_id="MPNRGLQ2K", panel_version="v1")
    p_alt_panel = _tier1_cache_path(
        derived_root=derived, sample_id="MPNRGLQ2K", panel_version="v2"
    )
    p_alt_sample = _tier1_cache_path(
        derived_root=derived, sample_id="OTHER", panel_version="v1"
    )

    assert p1 == p2
    assert p1 != p_alt_panel
    assert p1 != p_alt_sample
    # The path layout is the contract the doctor probe + cache-lookup logic
    # both rely on; keep it explicit so a future rename surfaces here.
    assert p1 == derived / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"

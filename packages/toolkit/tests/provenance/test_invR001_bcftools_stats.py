"""Phase 2 — ``bcftools stats`` wrapper tests.

Covers Phase-2 case 19 (`manifest.qc.bcftools_stats` populated with
``ts_tv_ratio``, ``n_snps``, ``n_indels``).

The parser is pure Python (host venv). The actual subprocess invocation
runs against ``tiny_vcf_gz`` inside the toolkit image (`needs_bio`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Real ``bcftools stats`` output captured inside the toolkit image
# (bcftools 1.21 + htslib 1.21) on the 100k synthetic perf-fixture.
# Trimmed to the SN + TSTV sections that the parser cares about.
_STATS_OUTPUT = b"""\
# This file was produced by bcftools stats.
# SN	[2]id	[3]key	[4]value
SN\t0\tnumber of samples:\t1
SN\t0\tnumber of records:\t100000
SN\t0\tnumber of no-ALTs:\t0
SN\t0\tnumber of SNPs:\t99750
SN\t0\tnumber of MNPs:\t0
SN\t0\tnumber of indels:\t250
SN\t0\tnumber of others:\t0
SN\t0\tnumber of multiallelic sites:\t0
SN\t0\tnumber of multiallelic SNP sites:\t0
# TSTV	[2]id	[3]ts	[4]tv	[5]ts/tv	[6]ts (1st ALT)	[7]tv (1st ALT)	[8]ts/tv (1st ALT)
TSTV\t0\t68420\t31330\t2.18\t68000\t31000\t2.19
"""


def test_parse_stats_extracts_n_snps_n_indels_ts_tv() -> None:
    from genomeclaw_toolkit.prep._bcftools_stats import parse_stats_output

    result = parse_stats_output(_STATS_OUTPUT)
    assert result.n_snps == 99_750
    assert result.n_indels == 250
    assert result.ts_tv_ratio == pytest.approx(2.18)


def test_parse_stats_handles_missing_keys_gracefully() -> None:
    """A `bcftools stats` output that omits the SN section raises a clear error."""
    from genomeclaw_toolkit.prep._bcftools_stats import (
        BcftoolsStatsParseError,
        parse_stats_output,
    )

    with pytest.raises(BcftoolsStatsParseError, match="number of SNPs"):
        parse_stats_output(b"# This file was produced by bcftools stats.\n")


def test_parse_stats_treats_dot_ts_tv_as_zero() -> None:
    """When `bcftools stats` reports ts/tv = '.' (no SNPs at all), parse to 0.0."""
    from genomeclaw_toolkit.prep._bcftools_stats import parse_stats_output

    output = b"""\
SN\t0\tnumber of records:\t10
SN\t0\tnumber of SNPs:\t0
SN\t0\tnumber of indels:\t10
TSTV\t0\t0\t0\t.\t0\t0\t.
"""
    result = parse_stats_output(output)
    assert result.n_snps == 0
    assert result.n_indels == 10
    assert result.ts_tv_ratio == pytest.approx(0.0)


@pytest.mark.needs_bio
def test_bcftools_stats_runs_against_synthetic_vcf(tiny_vcf_gz: Path) -> None:
    """End-to-end: `bcftools_stats(vcf)` returns sensible values for the 5-variant fixture."""
    from genomeclaw_toolkit.prep._bcftools_stats import bcftools_stats

    result = bcftools_stats(tiny_vcf_gz)
    # The fixture has 5 variants — exact split of SNPs/indels depends on
    # the synthetic content (tiny.vcf has 4 SNPs + 1 multi-allelic).
    assert result.n_snps + result.n_indels >= 1
    assert result.ts_tv_ratio >= 0

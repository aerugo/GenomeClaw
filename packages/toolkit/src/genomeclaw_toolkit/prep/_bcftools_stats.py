"""``bcftools stats`` subprocess wrapper + SN/TSTV section parser.

Phase 2 / case 19: ``manifest.json`` carries a ``qc.bcftools_stats``
block with ``ts_tv_ratio``, ``n_snps``, ``n_indels``. This module runs
``bcftools stats <vcf>`` and parses the relevant entries out of the
SN (Summary numbers) + TSTV (transitions/transversions) sections.

The parser ignores everything else in the stats output. Future phases
that want richer QC (e.g. per-chromosome variant counts, indel length
distribution, hethom ratio) can extend the dataclass or live in a
sibling module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from genomeclaw_toolkit.prep._bcftools import bcftools_run


@dataclass(frozen=True)
class BcftoolsStatsResult:
    """Phase-2 SN + TSTV summary fields from ``bcftools stats``."""

    n_snps: int
    n_indels: int
    ts_tv_ratio: float


class BcftoolsStatsParseError(ValueError):
    """The ``bcftools stats`` output didn't contain the keys we need."""


def parse_stats_output(stdout: bytes) -> BcftoolsStatsResult:
    """Extract ``n_snps`` / ``n_indels`` / ``ts_tv_ratio`` from ``bcftools stats`` stdout.

    Format (tab-separated):

    ::

        SN	0	number of SNPs:	99750
        SN	0	number of indels:	250
        TSTV	0	<ts>	<tv>	<ts/tv>	<ts(1st ALT)>	<tv(1st ALT)>	<ts/tv(1st ALT)>

    Raises:
        BcftoolsStatsParseError: a required line was missing.
    """
    text = stdout.decode("utf-8", errors="replace")

    n_snps: int | None = None
    n_indels: int | None = None
    ts_tv: float | None = None

    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        section = parts[0]
        if section == "SN" and len(parts) >= 4:
            key = parts[2]
            value = parts[3]
            if key == "number of SNPs:":
                n_snps = int(value)
            elif key == "number of indels:":
                n_indels = int(value)
        elif section == "TSTV" and len(parts) >= 5 and ts_tv is None:
            raw = parts[4]
            ts_tv = 0.0 if raw == "." else float(raw)

    if n_snps is None:
        raise BcftoolsStatsParseError(
            "bcftools stats output missing 'number of SNPs' in the SN section"
        )
    if n_indels is None:
        raise BcftoolsStatsParseError(
            "bcftools stats output missing 'number of indels' in the SN section"
        )
    if ts_tv is None:
        raise BcftoolsStatsParseError("bcftools stats output missing the TSTV section")

    return BcftoolsStatsResult(n_snps=n_snps, n_indels=n_indels, ts_tv_ratio=ts_tv)


def bcftools_stats(vcf: Path) -> BcftoolsStatsResult:
    """Run ``bcftools stats <vcf>`` and parse the summary fields.

    Phase 2 calls this once per ingest, against the source VCF, and
    writes the result into ``manifest.json`` under ``qc.bcftools_stats``.
    """
    proc = bcftools_run(["stats", str(vcf)])
    return parse_stats_output(proc.stdout)


__all__ = [
    "BcftoolsStatsParseError",
    "BcftoolsStatsResult",
    "bcftools_stats",
    "parse_stats_output",
]

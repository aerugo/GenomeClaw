"""Per-site `genotype_source` classifier + sidecar TSV writer.

Per force-genotype-callable-mask Phase 2 + proposed `INV-C002`:

The Tier-1/Tier-2 force-genotyping primitive in `coverage_fill.py`
runs `bcftools mpileup --min-BQ 20 --min-MQ 20 | bcftools call
--constrain alleles` at every PGS scoring site that the Nebula
variant-only VCF doesn't already contain. Without further
classification, every produced row is treated identically downstream
— a REF/REF dosage from sparse pileup outside any externally-validated
callable mask inflates the PGS match-rate denominator with an
unconfident dosage.

This module classifies each site as one of:

- `nebula_called`: the site was present in the source VCF (the variant
  caller emitted a row, either ALT or REF). Highest trust.
- `force_genotyped_high_conf`: the site was force-genotyped from the
  CRAM AND falls inside a GIAB high-confidence interval AND has
  ≥ 10 supporting reads (per BQ/MQ-filtered mpileup).
- `force_genotyped_low_conf`: force-genotyped with adequate depth but
  outside the GIAB high-confidence mask (or the mask wasn't fetched).
- `uncallable`: force-genotyped with depth below the threshold. Per
  proposed `INV-C002`, these sites are excluded from PGS match-rate
  numerator AND denominator by `_pgsc_calc_match.py` (Phase 3).

The GIAB intervals are read from the BED registered by Phase 1's
`giab_high_confidence` fetch source.
"""

from __future__ import annotations

import bisect
import gzip
from pathlib import Path
from typing import Literal

GenotypeSource = Literal[
    "nebula_called",
    "force_genotyped_high_conf",
    "force_genotyped_low_conf",
    "uncallable",
]
"""The four trust tiers a force-genotyped site can occupy.

Used as the value of the `genotype_source` column in the per-site
sidecar TSV (`forced_genotype_provenance.tsv[.zst]`) emitted alongside
each forced VCF. The PGS overlap calculator excludes `uncallable`
sites from both numerator and denominator (proposed `INV-C002`).
"""


_MIN_CALLABLE_DEPTH: int = 10
"""Minimum supporting-read depth for a force-genotyped site to be
considered callable. Below this, the site is classified `uncallable`
regardless of GIAB intersection — pileup with fewer than 10 reads
at BQ/MQ ≥ 20 doesn't support a confident REF/REF call.

Pinned here rather than passed at call time so the threshold is a
single source of truth across the Phase 2 classifier and the Phase 3
PGS-overlap-exclude logic. A future relaxation (e.g. 8 reads on
exome-scale data) is a single-line change tracked in `params_json`."""


def load_giab_high_conf_intervals(bed_path: Path) -> dict[str, list[tuple[int, int]]]:
    """Parse a GIAB high-confidence regions BED into `{chrom: [(start, end), ...]}`.

    Accepts BED3+ (only cols 1-3 read), gzipped or plain. Intervals are
    sorted by start coordinate within each chrom for `bisect`-based
    point lookup in :func:`classify_site`. Comment lines (starting
    `#`) and blank lines are skipped.

    A typical GIAB BED (e.g. `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz`,
    ~3M lines) loads into memory as a list of tuples; the per-chrom
    sorted-list shape supports O(log n) site classification at PGS
    smoke time without external tools.
    """
    intervals: dict[str, list[tuple[int, int]]] = {}
    opener = gzip.open if bed_path.suffix == ".gz" else open
    with opener(bed_path, "rt", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            chrom = parts[0]
            try:
                start = int(parts[1])
                end = int(parts[2])
            except ValueError:
                continue
            intervals.setdefault(chrom, []).append((start, end))

    for chrom in intervals:
        intervals[chrom].sort(key=lambda iv: iv[0])
    return intervals


def _point_in_intervals(pos: int, intervals: list[tuple[int, int]]) -> bool:
    """Binary-search for `pos` in a sorted list of half-open `[start, end)` intervals.

    BED convention: start inclusive, end exclusive.
    """
    if not intervals:
        return False
    # Find the rightmost interval whose start <= pos.
    starts = [iv[0] for iv in intervals]
    idx = bisect.bisect_right(starts, pos) - 1
    if idx < 0:
        return False
    start, end = intervals[idx]
    return start <= pos < end


def classify_site(
    *,
    chrom: str,
    pos: int,
    depth: int,
    nebula_called: bool,
    giab_intervals: dict[str, list[tuple[int, int]]],
    min_callable_depth: int = _MIN_CALLABLE_DEPTH,
) -> GenotypeSource:
    """Return the trust tier for one site.

    Precedence:
    1. If the site was in the source VCF → `"nebula_called"` (wins
       unconditionally).
    2. Else if `depth < min_callable_depth` → `"uncallable"`.
    3. Else if the site falls inside a GIAB high-confidence interval
       → `"force_genotyped_high_conf"`.
    4. Else (adequate depth, outside GIAB OR no GIAB BED loaded) →
       `"force_genotyped_low_conf"`.

    The GIAB BED carries autosomal + X intervals only; sites on chrY
    or chrM with no entries in `giab_intervals` resolve to either
    `force_genotyped_low_conf` (adequate depth) or `uncallable` (low
    depth), per case 4 / case 2. This is the conservative default —
    we don't pretend chrY sites are high-confidence just because the
    GIAB benchmark doesn't enumerate them.
    """
    if nebula_called:
        return "nebula_called"
    if depth < min_callable_depth:
        return "uncallable"
    chrom_intervals = giab_intervals.get(chrom, [])
    if _point_in_intervals(pos, chrom_intervals):
        return "force_genotyped_high_conf"
    return "force_genotyped_low_conf"


def write_genotype_source_sidecar(
    rows: list[tuple[str, int, str, str, GenotypeSource]],
    sidecar_path: Path,
) -> Path:
    """Write the per-site genotype-source sidecar TSV.

    Format: 5 tab-separated columns with a single header line:
    ``chrom\\tpos\\tref\\talt\\tgenotype_source``.

    The sidecar lives next to the forced VCF in the same Tier-1/Tier-2
    cache directory. The PGS overlap calculator reads it at score time
    to exclude `uncallable` sites from the match-rate calculation.

    Empty rows → header-only TSV (truthful representation: every Tier
    output carries the schema even if no force-genotyping happened).
    """
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    with sidecar_path.open("w", encoding="utf-8") as fh:
        fh.write("chrom\tpos\tref\talt\tgenotype_source\n")
        for chrom, pos, ref, alt, source in rows:
            fh.write(f"{chrom}\t{pos}\t{ref}\t{alt}\t{source}\n")
    return sidecar_path


__all__ = [
    "GenotypeSource",
    "classify_site",
    "load_giab_high_conf_intervals",
    "write_genotype_source_sidecar",
]

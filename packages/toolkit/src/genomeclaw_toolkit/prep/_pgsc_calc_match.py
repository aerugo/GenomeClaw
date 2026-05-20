"""Parse pgsc_calc's per-variant match log for the calibration classifier.

pgsc_calc v2.2.0 emits ``<work_dir>/<nextflow_hash>/<sampleset>_log.csv.gz``
with a per-row ``match_status`` column. The four observed values:

- ``matched``: scoring-file variant successfully matched into a user dosage.
- ``unmatched``: scoring-file variant absent from the user's input — the
  variant-only-VCF problem this whole plan exists to solve.
- ``not_best`` / ``excluded``: duplicate-handling artefacts (the same
  underlying variant also appears under ``matched`` or ``unmatched``).
  Counting them double-counts the variants they describe.

The match rate is ``matched / (matched + unmatched)`` per PGS accession,
mirroring the 2026-05-17 smoke's reported 28.37% on PGS000018:

    matched   = 495,434
    unmatched = 1,249,188
    → match_rate = 0.2839
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatchStats:
    """Per-PGS-accession match statistics from a pgsc_calc log CSV."""

    pgs_accession: str
    matched: int
    unmatched: int

    @property
    def match_rate(self) -> float:
        """``matched / (matched + unmatched)``; ``0.0`` when both are zero.

        The empty-denominator guard is defensive — :func:`parse_match_stats`
        returns ``None`` rather than zero-count stats, so callers shouldn't
        hit this path in practice. Kept for completeness.
        """
        total = self.matched + self.unmatched
        return self.matched / total if total else 0.0


# Status values that count toward the matched/unmatched totals. Other
# values (``not_best``, ``excluded``, future pgsc_calc additions) are
# silently skipped — they represent duplicate-handling buckets, not
# distinct scoring variants.
_MATCHED = "matched"
_UNMATCHED = "unmatched"


def parse_match_stats(
    log_csv_gz: Path,
    *,
    pgs_accession: str,
) -> MatchStats | None:
    """Walk a gzipped pgsc_calc log CSV; return per-accession match stats.

    Args:
        log_csv_gz: Path to ``<sampleset>_log.csv.gz`` inside a pgsc_calc
            Nextflow work-dir hash directory.
        pgs_accession: The PGS Catalog accession the user is computing
            (e.g. ``"PGS000018_hmPOS_GRCh38"``) — note the suffix matches
            pgsc_calc's internal naming.

    Returns:
        :class:`MatchStats` with the counts for that accession, or
        ``None`` when the accession isn't present or the log is empty.
        ``None`` signals to the orchestrator to skip classification
        rather than fabricating a zero-match-rate decline.
    """
    matched = 0
    unmatched = 0

    with gzip.open(log_csv_gz, "rt") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "match_status" not in reader.fieldnames:
            return None
        for row in reader:
            if row.get("accession") != pgs_accession:
                continue
            status = row.get("match_status")
            if status == _MATCHED:
                matched += 1
            elif status == _UNMATCHED:
                unmatched += 1
            # Other status values (``not_best`` / ``excluded`` / future
            # values) are intentionally not counted — see module docstring.

    if matched == 0 and unmatched == 0:
        return None
    return MatchStats(pgs_accession=pgs_accession, matched=matched, unmatched=unmatched)


def find_pgsc_calc_log_csv(work_dir: Path, *, sampleset: str) -> Path | None:
    """Recursively glob ``<work_dir>`` for ``<sampleset>_log.csv.gz``.

    pgsc_calc's Nextflow work-dir has the shape
    ``<work>/<two_hex>/<long_hex>/<sampleset>_log.csv.gz``. The orchestrator
    doesn't know the hash names ahead of time, so the parser uses a glob.

    Returns the first matching path (there's exactly one per run; if a
    future pgsc_calc version emits multiple sample logs the caller has to
    disambiguate explicitly). ``None`` when no match is found — the
    orchestrator then skips classification.
    """
    candidates = sorted(work_dir.rglob(f"{sampleset}_log.csv.gz"))
    return candidates[0] if candidates else None


__all__ = [
    "MatchStats",
    "find_pgsc_calc_log_csv",
    "parse_match_stats",
]

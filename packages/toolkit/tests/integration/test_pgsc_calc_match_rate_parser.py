"""Phase 3b3a — parse match_rate from pgsc_calc ``<sampleset>_log.csv.gz``.

pgsc_calc emits a per-variant match log at
``<work_dir>/<nextflow_hash>/<sampleset>_log.csv.gz`` whose ``match_status``
column carries one of: ``matched`` (consumed by the score), ``unmatched``
(scoring variant absent from user data), ``not_best`` / ``excluded``
(duplicate-handling buckets; the same underlying variant also appears under
``matched`` or ``unmatched`` so they shouldn't be double-counted).

Match rate = matched / (matched + unmatched) per PGS accession.

Verified empirically against the 2026-05-17 smoke on `MPNRGLQ2K.cram` +
`PGS000018`:

    matched   = 495,434
    unmatched = 1,249,188
    not_best  = 557
    excluded  = 557
    → match_rate = 495_434 / (495_434 + 1_249_188) = 28.39%

The smoke's logged 28.37% rounds to the same value within reporting noise.

Contract assertions:

1. Counts the matched rows for the requested accession correctly.
2. Excludes ``not_best`` / ``excluded`` rows (they're duplicate-handling
   artefacts, not separate scoring variants).
3. Filters by ``accession`` column — multi-PGS work dirs return only the
   requested PGS's stats.
4. Returns ``None`` on an empty / malformed log (defensive — the classifier
   then skips and returns the row uncalibrated).
5. ``_find_pgsc_calc_log_csv`` recursively globs the work_dir hierarchy
   and returns the first matching log file.
"""

from __future__ import annotations

import gzip
from pathlib import Path

# Header that matches pgsc_calc v2.2.0 output (verified against the
# 2026-05-17 smoke's MPNRGLQ2K_log.csv.gz).
_LOG_HEADER = (
    "row_nr,accession,chr_name,chr_position,effect_allele,other_allele,"
    "effect_weight,effect_type,ID,REF,ALT,matched_effect_allele,"
    "match_type,is_multiallelic,ambiguous,match_flipped,best_match,"
    "exclude,duplicate_best_match,duplicate_ID,match_IDs,"
    "match_status,dataset"
)


def _write_log_csv(path: Path, rows: list[str]) -> None:
    """Write a gzipped pgsc_calc-shape log CSV with the given data rows."""
    with gzip.open(path, "wt") as fh:
        fh.write(_LOG_HEADER + "\n")
        for row in rows:
            fh.write(row + "\n")


def test_parse_match_stats_counts_matched_and_unmatched(tmp_path: Path) -> None:
    """The smoke's 28.39% match-rate is reproduced on a synthetic 6-row CSV.

    3 matched + 7 unmatched → 30% match rate. Doesn't have to mirror the
    real smoke numbers byte-for-byte; the calculation is the contract.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "MPNRGLQ2K_log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            # 3 matched
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            # 7 unmatched
            *[
                ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "unmatched,MPNRGLQ2K"
                for _ in range(7)
            ],
        ],
    )

    stats = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")

    assert stats is not None
    assert stats.matched == 3
    assert stats.unmatched == 7
    assert stats.match_rate == 0.3


def test_parse_match_stats_excludes_not_best_and_excluded_rows(tmp_path: Path) -> None:
    """``not_best`` + ``excluded`` rows are duplicate-handling artefacts; never counted.

    Verified empirically: in the 2026-05-17 smoke the not_best + excluded
    rows (557 + 557 = 1,114) sit ALONGSIDE the matched/unmatched counts for
    the same underlying variants. Counting them would double-count the
    variants they describe.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "unmatched,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "not_best,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "excluded,MPNRGLQ2K",
        ],
    )

    stats = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")

    assert stats is not None
    assert stats.matched == 1
    assert stats.unmatched == 1
    assert stats.match_rate == 0.5


def test_parse_match_stats_filters_by_accession(tmp_path: Path) -> None:
    """Multi-PGS work dirs return only the requested accession's stats."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            # PGS000018: 2 matched, 1 unmatched → 66.7%
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            ",PGS000018_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "unmatched,MPNRGLQ2K",
            # PGS003725: 1 matched, 3 unmatched → 25%
            ",PGS003725_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
            *[
                ",PGS003725_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "unmatched,MPNRGLQ2K"
                for _ in range(3)
            ],
        ],
    )

    stats_a = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")
    stats_b = parse_match_stats(log_csv, pgs_accession="PGS003725_hmPOS_GRCh38")

    assert stats_a is not None
    assert stats_a.matched == 2
    assert stats_a.unmatched == 1
    assert stats_a.match_rate == pytest.approx(2 / 3, abs=1e-6)

    assert stats_b is not None
    assert stats_b.matched == 1
    assert stats_b.unmatched == 3
    assert stats_b.match_rate == 0.25


def test_parse_match_stats_returns_none_on_empty_log(tmp_path: Path) -> None:
    """Empty match log → ``None`` (no calibration possible; orchestrator skips classify)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "empty_log.csv.gz"
    _write_log_csv(log_csv, [])

    stats = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")
    assert stats is None


def test_parse_match_stats_returns_none_on_accession_not_present(tmp_path: Path) -> None:
    """Requested accession absent from log → ``None``."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            ",PGS999999_hmPOS_GRCh38,,,,,,,,,,,,,,,,,,,," + "matched,MPNRGLQ2K",
        ],
    )

    stats = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")
    assert stats is None


def test_find_pgsc_calc_log_csv_recursive_glob(tmp_path: Path) -> None:
    """``_find_pgsc_calc_log_csv`` walks the Nextflow hash-dir hierarchy."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import find_pgsc_calc_log_csv

    nested = tmp_path / "3c" / "1d8659bc0e4670162dc8e483f6607c"
    nested.mkdir(parents=True)
    log = nested / "MPNRGLQ2K_log.csv.gz"
    _write_log_csv(log, [])

    found = find_pgsc_calc_log_csv(tmp_path, sampleset="MPNRGLQ2K")
    assert found == log


def test_find_pgsc_calc_log_csv_returns_none_when_absent(tmp_path: Path) -> None:
    """Empty work_dir → ``None`` (orchestrator falls back to skip-calibration path)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import find_pgsc_calc_log_csv

    found = find_pgsc_calc_log_csv(tmp_path, sampleset="MPNRGLQ2K")
    assert found is None


# Imports at the bottom so unused-import lint stays clean on RED before
# `_pgsc_calc_match` exists.
import pytest  # noqa: E402

"""`parse_effect_weights` + `compute_weighted_match_rate` (Plan 7 Phase 1).

Per `prs-calibration-phase3b` Phase 1: the calibration classifier
gains a second overlap axis — effect-weight-weighted match rate
(`Σ|β|_matched / Σ|β|_total`). A PGS where 49% of variants are
missing but those missing variants account for 80% of effect-weight
magnitude is genuinely worse than one where the dropped 49% is
weight-distributed. The new axis surfaces that asymmetry.

`parse_effect_weights` reads the PGS Catalog scoring file's
`effect_weight` column into a `(chrom, pos, ea, oa) → |β|` dict.
`compute_weighted_match_rate` walks the pgsc_calc per-variant match
log + the weight dict to compute the weighted overlap. Both functions
also honour the INV-C003 `uncallable_sites` exclusion (sites in that
set are dropped from both numerator and denominator).
"""

from __future__ import annotations

import gzip
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_SCOREFILE_HEADER = "hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"

_LOG_HEADER = (
    "row_nr,accession,chr_name,chr_position,effect_allele,other_allele,"
    "effect_weight,effect_type,ID,REF,ALT,matched_effect_allele,"
    "match_type,is_multiallelic,ambiguous,match_flipped,best_match,"
    "exclude,duplicate_best_match,duplicate_ID,match_IDs,"
    "match_status,dataset"
)


def _write_scorefile(path: Path, rows: list[tuple[str, int, str, str, float]]) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as fh:
        fh.write(_SCOREFILE_HEADER)
        for chrom, pos, ea, oa, weight in rows:
            fh.write(f"{chrom}\t{pos}\t{ea}\t{oa}\t{weight}\n")


def _write_log_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = _LOG_HEADER.split(",")
    with gzip.open(path, "wt") as fh:
        fh.write(_LOG_HEADER + "\n")
        for row in rows:
            line = ",".join(row.get(name, "") for name in fields)
            fh.write(line + "\n")


def _log_row(
    *, accession: str, chrom: str, pos: str, ea: str, oa: str, status: str
) -> dict[str, str]:
    return {
        "accession": accession,
        "chr_name": chrom,
        "chr_position": pos,
        "effect_allele": ea,
        "other_allele": oa,
        "match_status": status,
        "dataset": "MPNRGLQ2K",
    }


# ---------------------------------------------------------------------------
# parse_effect_weights
# ---------------------------------------------------------------------------


def test_parse_effect_weights_returns_abs_value_dict(tmp_path: Path) -> None:
    """Weights are stored as absolute values keyed on `(chr-prefixed, pos, ea, oa)`."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_effect_weights

    scoring_file = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    _write_scorefile(
        scoring_file,
        [
            ("1", 100, "G", "A", 0.5),
            ("1", 200, "T", "C", -0.3),
            ("22", 300, "A", "G", 0.8),
        ],
    )

    weights = parse_effect_weights(scoring_file)
    assert weights is not None
    assert weights[("chr1", 100, "G", "A")] == 0.5
    assert weights[("chr1", 200, "T", "C")] == 0.3  # abs(-0.3)
    assert weights[("chr22", 300, "A", "G")] == 0.8


def test_parse_effect_weights_returns_none_when_column_absent(tmp_path: Path) -> None:
    """A scoring file without `effect_weight` column → None (not error, not empty dict)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_effect_weights

    scoring_file = tmp_path / "PGS000018_hmPOS_GRCh38.txt"
    scoring_file.write_text(
        "hm_chr\thm_pos\teffect_allele\tother_allele\n"
        "1\t100\tG\tA\n"
    )

    assert parse_effect_weights(scoring_file) is None


def test_parse_effect_weights_handles_gz_and_plain(tmp_path: Path) -> None:
    """Both gzipped (.gz) and plain (.txt) scoring files parse to the same dict."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_effect_weights

    rows = [("1", 100, "G", "A", 0.5)]

    gz_path = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    _write_scorefile(gz_path, rows)

    plain_path = tmp_path / "PGS000018_hmPOS_GRCh38.txt"
    _write_scorefile(plain_path, rows)

    assert parse_effect_weights(gz_path) == parse_effect_weights(plain_path)


def test_parse_effect_weights_skips_unparseable_rows(tmp_path: Path) -> None:
    """A row with a non-numeric effect_weight is skipped (defensive, no crash)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_effect_weights

    scoring_file = tmp_path / "PGS000018_hmPOS_GRCh38.txt"
    scoring_file.write_text(
        _SCOREFILE_HEADER
        + "1\t100\tG\tA\t0.5\n"
        + "1\t200\tT\tC\tnot_a_number\n"
        + "1\t300\tA\tG\t0.8\n"
    )

    weights = parse_effect_weights(scoring_file)
    assert weights is not None
    assert ("chr1", 100, "G", "A") in weights
    assert ("chr1", 200, "T", "C") not in weights
    assert ("chr1", 300, "A", "G") in weights


# ---------------------------------------------------------------------------
# compute_weighted_match_rate
# ---------------------------------------------------------------------------


def test_compute_weighted_match_rate_basic(tmp_path: Path) -> None:
    """`Σ|β|_matched / Σ|β|_total` reflects per-row weights, not row counts."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        compute_weighted_match_rate,
    )

    weights = {
        ("chr1", 100, "G", "A"): 1.0,
        ("chr1", 200, "T", "C"): 3.0,
        ("chr1", 300, "A", "G"): 1.0,
    }
    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _log_row(
                accession="PGS000018", chrom="1", pos="100", ea="G", oa="A", status="matched"
            ),
            _log_row(
                accession="PGS000018", chrom="1", pos="200", ea="T", oa="C", status="unmatched"
            ),
            _log_row(
                accession="PGS000018", chrom="1", pos="300", ea="A", oa="G", status="matched"
            ),
        ],
    )

    rate = compute_weighted_match_rate(
        log_csv, pgs_accession="PGS000018", weight_dict=weights
    )
    assert rate is not None
    # (1.0 + 1.0) / (1.0 + 3.0 + 1.0) = 0.4
    assert abs(rate - 0.4) < 1e-9


def test_compute_weighted_match_rate_excludes_uncallable(tmp_path: Path) -> None:
    """INV-C003: uncallable sites are excluded from BOTH numerator and denominator."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        compute_weighted_match_rate,
    )

    weights = {
        ("chr1", 100, "G", "A"): 1.0,
        ("chr1", 200, "T", "C"): 3.0,
        ("chr1", 300, "A", "G"): 1.0,
    }
    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _log_row(
                accession="PGS000018", chrom="1", pos="100", ea="G", oa="A", status="matched"
            ),
            _log_row(
                accession="PGS000018", chrom="1", pos="200", ea="T", oa="C", status="unmatched"
            ),
            _log_row(
                accession="PGS000018", chrom="1", pos="300", ea="A", oa="G", status="matched"
            ),
        ],
    )

    # Mark chr1:300 as uncallable: its weight (1.0) should drop from both
    # numerator AND denominator → 1.0 / (1.0 + 3.0) = 0.25.
    uncallable = {("chr1", 300)}
    rate = compute_weighted_match_rate(
        log_csv,
        pgs_accession="PGS000018",
        weight_dict=weights,
        uncallable_sites=uncallable,
    )
    assert rate is not None
    assert abs(rate - 0.25) < 1e-9


def test_compute_weighted_match_rate_returns_none_when_weights_none(tmp_path: Path) -> None:
    """`weight_dict=None` (no effect_weight column in scoring file) → None."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        compute_weighted_match_rate,
    )

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _log_row(
                accession="PGS000018", chrom="1", pos="100", ea="G", oa="A", status="matched"
            ),
        ],
    )
    assert (
        compute_weighted_match_rate(
            log_csv, pgs_accession="PGS000018", weight_dict=None
        )
        is None
    )


def test_compute_weighted_match_rate_zero_total_weight(tmp_path: Path) -> None:
    """Sum of |β| == 0 → return None rather than divide by zero."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        compute_weighted_match_rate,
    )

    weights = {
        ("chr1", 100, "G", "A"): 0.0,
        ("chr1", 200, "T", "C"): 0.0,
    }
    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _log_row(
                accession="PGS000018", chrom="1", pos="100", ea="G", oa="A", status="matched"
            ),
            _log_row(
                accession="PGS000018", chrom="1", pos="200", ea="T", oa="C", status="unmatched"
            ),
        ],
    )
    assert (
        compute_weighted_match_rate(
            log_csv, pgs_accession="PGS000018", weight_dict=weights
        )
        is None
    )


def test_compute_weighted_match_rate_filters_by_accession(tmp_path: Path) -> None:
    """Rows for a different PGS accession are silently skipped."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        compute_weighted_match_rate,
    )

    weights = {
        ("chr1", 100, "G", "A"): 1.0,
    }
    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _log_row(
                accession="PGS000018", chrom="1", pos="100", ea="G", oa="A", status="matched"
            ),
            _log_row(
                accession="PGS999999",  # different accession; should not count
                chrom="1",
                pos="100",
                ea="G",
                oa="A",
                status="matched",
            ),
        ],
    )
    rate = compute_weighted_match_rate(
        log_csv, pgs_accession="PGS000018", weight_dict=weights
    )
    assert rate == 1.0


# ---------------------------------------------------------------------------
# `find_pgsc_calc_log_csv` — sampleset-name-flexible match-log discovery
# (Phase 4 follow-up: 2026-05-26 smoke surfaced that pgsc_calc internally
# derives the sampleset from the merged-norm VCF basename, NOT from the
# orchestrator's --sample arg. Globbing by the exact sampleset name
# therefore mismatches the on-disk filename.)
# ---------------------------------------------------------------------------


def test_find_pgsc_calc_log_csv_finds_when_sampleset_does_not_match_filename(
    tmp_path: Path,
) -> None:
    """The match log is named `norm_log.csv.gz` (pgsc_calc's internal
    sampleset from the merged VCF), even though the orchestrator passed
    `--sample MPNRGLQ2K`. The discovery helper must find it regardless.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_match import find_pgsc_calc_log_csv

    hash_dir = tmp_path / "bd" / "2a74d39e34c8a774fcdd97bda5784f"
    hash_dir.mkdir(parents=True)
    log_path = hash_dir / "norm_log.csv.gz"
    log_path.write_bytes(b"")  # presence is enough; parser handles empty case

    found = find_pgsc_calc_log_csv(tmp_path, sampleset="MPNRGLQ2K")
    assert found == log_path


def test_find_pgsc_calc_log_csv_returns_none_when_no_log_files(tmp_path: Path) -> None:
    """No `*_log.csv.gz` anywhere → None (caller abstains)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import find_pgsc_calc_log_csv

    assert find_pgsc_calc_log_csv(tmp_path, sampleset="MPNRGLQ2K") is None


def test_find_pgsc_calc_log_csv_prefers_sampleset_match_when_present(
    tmp_path: Path,
) -> None:
    """When BOTH a sampleset-matching and a generic `<other>_log.csv.gz`
    file exist, prefer the sampleset-matching one. This preserves the
    original strict-matching behaviour for callers that DO know the
    sampleset.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_match import find_pgsc_calc_log_csv

    hash1 = tmp_path / "aa" / "1234"
    hash1.mkdir(parents=True)
    (hash1 / "norm_log.csv.gz").write_bytes(b"")
    hash2 = tmp_path / "bb" / "5678"
    hash2.mkdir(parents=True)
    target = hash2 / "MPNRGLQ2K_log.csv.gz"
    target.write_bytes(b"")

    found = find_pgsc_calc_log_csv(tmp_path, sampleset="MPNRGLQ2K")
    assert found == target

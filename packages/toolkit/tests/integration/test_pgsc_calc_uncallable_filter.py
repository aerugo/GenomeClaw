"""`parse_match_stats(uncallable_sites=...)` excludes uncallable sites (Plan 6 Phase 3).

Per proposed `INV-C002`: sites classified `uncallable` by the
force-genotype callable-region mask (Phase 2) must not inflate the
PGS match-rate denominator OR appear in the numerator. The pgsc_calc
log walker accepts an optional set of (chrom, pos) tuples and skips
any row whose coordinates appear in that set, regardless of its
`match_status`.

`load_uncallable_sites_from_sidecar` reads the sidecar TSV emitted
by `_genotype_source.write_genotype_source_sidecar` and returns the
filter set.

Per force-genotype-callable-mask/phases/phase-3.md (and the INV-C002
verification stub in the proposed-invariant block).
"""

from __future__ import annotations

import gzip
from pathlib import Path


_LOG_HEADER = (
    "row_nr,accession,chr_name,chr_position,effect_allele,other_allele,"
    "effect_weight,effect_type,ID,REF,ALT,matched_effect_allele,"
    "match_type,is_multiallelic,ambiguous,match_flipped,best_match,"
    "exclude,duplicate_best_match,duplicate_ID,match_IDs,"
    "match_status,dataset"
)


def _write_log_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a gzipped pgsc_calc-shape log CSV with chr_name + chr_position populated."""
    fields = _LOG_HEADER.split(",")
    with gzip.open(path, "wt") as fh:
        fh.write(_LOG_HEADER + "\n")
        for row in rows:
            line = ",".join(row.get(name, "") for name in fields)
            fh.write(line + "\n")


def _row(
    *,
    accession: str,
    chrom: str,
    pos: str,
    status: str,
) -> dict[str, str]:
    return {
        "accession": accession,
        "chr_name": chrom,
        "chr_position": pos,
        "match_status": status,
        "dataset": "MPNRGLQ2K",
    }


def test_parse_match_stats_baseline_without_filter(tmp_path: Path) -> None:
    """Without `uncallable_sites`, all matched/unmatched rows count (pre-Phase-3 behaviour)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="100", status="matched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="200", status="matched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="300", status="unmatched"),
        ],
    )

    stats = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")
    assert stats is not None
    assert stats.matched == 2
    assert stats.unmatched == 1


def test_parse_match_stats_excludes_uncallable_sites(tmp_path: Path) -> None:
    """INV-C002: uncallable sites are excluded from BOTH matched and unmatched."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="100", status="matched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="200", status="matched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="300", status="unmatched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="400", status="unmatched"),
        ],
    )
    # Both an uncallable matched site (chr1:200) AND an uncallable unmatched
    # site (chr1:400) — verify both are excluded from BOTH numerator and
    # denominator.
    uncallable = {("chr1", 200), ("chr1", 400)}

    stats = parse_match_stats(
        log_csv,
        pgs_accession="PGS000018_hmPOS_GRCh38",
        uncallable_sites=uncallable,
    )
    assert stats is not None
    assert stats.matched == 1, "uncallable matched site must not count toward numerator"
    assert stats.unmatched == 1, "uncallable unmatched site must not count toward denominator"
    assert stats.uncallable_excluded == 2


def test_parse_match_stats_uncallable_filter_normalises_chr_prefix(tmp_path: Path) -> None:
    """Sidecar uses `chr1` style; pgsc_calc emits `1`; normalisation handles both."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="100", status="matched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="200", status="matched"),
        ],
    )

    # Sidecar uses chr-prefixed names; pgsc_calc emits bare-chrom.
    uncallable = {("chr1", 200)}

    stats = parse_match_stats(
        log_csv,
        pgs_accession="PGS000018_hmPOS_GRCh38",
        uncallable_sites=uncallable,
    )
    assert stats is not None
    assert stats.matched == 1, (
        "chr-prefix normalisation should let chr1:200 (sidecar) match 1:200 (pgsc_calc log)"
    )


def test_parse_match_stats_uncallable_none_is_baseline_behaviour(tmp_path: Path) -> None:
    """Explicitly passing `uncallable_sites=None` is equivalent to omitting it."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import parse_match_stats

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="100", status="matched"),
        ],
    )

    stats = parse_match_stats(
        log_csv,
        pgs_accession="PGS000018_hmPOS_GRCh38",
        uncallable_sites=None,
    )
    assert stats is not None
    assert stats.matched == 1
    assert stats.uncallable_excluded == 0


# ---------------------------------------------------------------------------
# load_uncallable_sites_from_sidecar
# ---------------------------------------------------------------------------


def test_load_uncallable_sites_from_sidecar_returns_only_uncallable(tmp_path: Path) -> None:
    """The helper reads the sidecar TSV + returns only `uncallable` rows."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        load_uncallable_sites_from_sidecar,
    )

    sidecar = tmp_path / "forced_genotype_provenance.tsv"
    sidecar.write_text(
        "chrom\tpos\tref\talt\tgenotype_source\n"
        "chr1\t100\tA\tG\tnebula_called\n"
        "chr1\t200\tA\tT\tforce_genotyped_high_conf\n"
        "chr1\t300\tC\tT\tuncallable\n"
        "chr2\t500\tG\tA\tuncallable\n"
        "chr1\t400\tA\tG\tforce_genotyped_low_conf\n"
    )

    sites = load_uncallable_sites_from_sidecar(sidecar)
    assert sites == {("chr1", 300), ("chr2", 500)}


def test_load_uncallable_sites_handles_missing_sidecar(tmp_path: Path) -> None:
    """Missing sidecar → empty set (the pipeline didn't write one; no filter)."""
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        load_uncallable_sites_from_sidecar,
    )

    sites = load_uncallable_sites_from_sidecar(tmp_path / "missing.tsv")
    assert sites == set()


# ---------------------------------------------------------------------------
# INV-C002 enforcement
# ---------------------------------------------------------------------------


def test_invC002_uncallable_sites_excluded_from_match_rate(tmp_path: Path) -> None:
    """INV-C002 end-to-end: sidecar → set → filter → corrected match_rate.

    Without the filter, 1 matched + 3 unmatched → match_rate = 0.25 (with
    an uncallable site inflating the denominator). With the filter, that
    uncallable site is excluded → 1 matched + 2 unmatched → match_rate = 0.333.
    The bigger the uncallable count, the more this matters.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        load_uncallable_sites_from_sidecar,
        parse_match_stats,
    )

    sidecar = tmp_path / "forced_genotype_provenance.tsv"
    sidecar.write_text(
        "chrom\tpos\tref\talt\tgenotype_source\n"
        "chr1\t300\tA\tG\tuncallable\n"
    )

    log_csv = tmp_path / "log.csv.gz"
    _write_log_csv(
        log_csv,
        [
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="100", status="matched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="200", status="unmatched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="300", status="unmatched"),
            _row(accession="PGS000018_hmPOS_GRCh38", chrom="1", pos="400", status="unmatched"),
        ],
    )

    # Baseline (no filter): 1/4 = 0.25.
    baseline = parse_match_stats(log_csv, pgs_accession="PGS000018_hmPOS_GRCh38")
    assert baseline is not None
    assert baseline.match_rate == 0.25

    # With INV-C002 filter: chr1:300 dropped → 1/3 ≈ 0.333.
    uncallable = load_uncallable_sites_from_sidecar(sidecar)
    filtered = parse_match_stats(
        log_csv,
        pgs_accession="PGS000018_hmPOS_GRCh38",
        uncallable_sites=uncallable,
    )
    assert filtered is not None
    assert filtered.matched == 1
    assert filtered.unmatched == 2
    assert abs(filtered.match_rate - (1 / 3)) < 1e-9
    assert filtered.uncallable_excluded == 1, (
        "INV-C002: filtered MatchStats must report how many sites were excluded "
        "so the provenance trail is auditable downstream"
    )

"""`classify_site` + `load_giab_high_conf_intervals` (Plan 6 Phase 2).

Pure-function unit tests for the per-site `genotype_source` classifier.
No real bcftools / CRAM dependency.

`GenotypeSource` ∈ {`nebula_called`, `force_genotyped_high_conf`,
`force_genotyped_low_conf`, `uncallable`}.

Per force-genotype-callable-mask Phase 2 (proposed `INV-C002`).
"""

from __future__ import annotations

import gzip
from pathlib import Path


# ---------------------------------------------------------------------------
# Interval-loader tests
# ---------------------------------------------------------------------------


def test_load_giab_intervals_parses_bed_gz(tmp_path: Path) -> None:
    """`load_giab_high_conf_intervals` parses a synthetic gzipped BED."""
    from genomeclaw_toolkit.prep._genotype_source import (
        load_giab_high_conf_intervals,
    )

    bed = tmp_path / "giab.bed.gz"
    with gzip.open(bed, "wt") as fh:
        fh.write("chr1\t100\t200\n")
        fh.write("chr1\t500\t1000\n")
        fh.write("chr22\t10000\t20000\n")

    intervals = load_giab_high_conf_intervals(bed)
    assert "chr1" in intervals
    assert intervals["chr1"] == [(100, 200), (500, 1000)]
    assert intervals["chr22"] == [(10000, 20000)]


def test_load_giab_intervals_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    """Robust to BED comments + blank lines."""
    from genomeclaw_toolkit.prep._genotype_source import (
        load_giab_high_conf_intervals,
    )

    bed = tmp_path / "giab.bed"
    bed.write_text(
        "#track name=giab\n"
        "\n"
        "chr1\t100\t200\n"
        "chr1\t300\t400\n"
    )
    intervals = load_giab_high_conf_intervals(bed)
    assert intervals["chr1"] == [(100, 200), (300, 400)]


def test_load_giab_intervals_sorts_within_chrom(tmp_path: Path) -> None:
    """Intervals are sorted by start coordinate per chrom (enables bisect lookup)."""
    from genomeclaw_toolkit.prep._genotype_source import (
        load_giab_high_conf_intervals,
    )

    bed = tmp_path / "giab.bed.gz"
    with gzip.open(bed, "wt") as fh:
        fh.write("chr1\t500\t600\n")
        fh.write("chr1\t100\t200\n")
        fh.write("chr1\t300\t400\n")

    intervals = load_giab_high_conf_intervals(bed)
    assert intervals["chr1"] == [(100, 200), (300, 400), (500, 600)]


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

_INTERVALS = {
    "chr1": [(100, 200), (500, 1000)],
    "chr22": [(10000, 20000)],
}


def test_classify_site_nebula_called_takes_precedence() -> None:
    """A site already in the source VCF wins over every other rule.

    The `nebula_called` source is the trust anchor — if the variant
    caller emitted a row, the force-genotype tier didn't synthesise
    anything for that site.
    """
    from genomeclaw_toolkit.prep._genotype_source import classify_site

    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=30,
            nebula_called=True,
            giab_intervals=_INTERVALS,
        )
        == "nebula_called"
    )
    # Even outside GIAB high-conf, the source VCF wins.
    assert (
        classify_site(
            chrom="chr1",
            pos=99999,
            depth=30,
            nebula_called=True,
            giab_intervals=_INTERVALS,
        )
        == "nebula_called"
    )
    # Even with low depth.
    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=2,
            nebula_called=True,
            giab_intervals=_INTERVALS,
        )
        == "nebula_called"
    )


def test_classify_site_force_genotyped_high_conf_in_giab() -> None:
    """A force-genotyped site inside a GIAB high-conf interval with adequate depth."""
    from genomeclaw_toolkit.prep._genotype_source import classify_site

    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=30,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "force_genotyped_high_conf"
    )
    # Boundary check: start is inclusive (BED convention).
    assert (
        classify_site(
            chrom="chr1",
            pos=100,
            depth=15,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "force_genotyped_high_conf"
    )


def test_classify_site_force_genotyped_low_conf_outside_giab() -> None:
    """A force-genotyped site OUTSIDE GIAB high-conf with adequate depth."""
    from genomeclaw_toolkit.prep._genotype_source import classify_site

    assert (
        classify_site(
            chrom="chr1",
            pos=350,
            depth=30,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "force_genotyped_low_conf"
    )
    # Boundary check: end is exclusive (BED convention).
    assert (
        classify_site(
            chrom="chr1",
            pos=200,
            depth=30,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "force_genotyped_low_conf"
    )


def test_classify_site_uncallable_when_depth_below_threshold() -> None:
    """A force-genotyped site with depth < 10 reads → uncallable, regardless of GIAB."""
    from genomeclaw_toolkit.prep._genotype_source import classify_site

    # Inside GIAB but depth too low.
    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=5,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "uncallable"
    )
    # Outside GIAB and depth too low.
    assert (
        classify_site(
            chrom="chr1",
            pos=350,
            depth=5,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "uncallable"
    )
    # Zero depth.
    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=0,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "uncallable"
    )


def test_classify_site_uncallable_when_no_intervals_for_chrom() -> None:
    """A site on a chrom not in GIAB intervals → low_conf if depth adequate, uncallable otherwise.

    This is the "no GIAB intervals for this chrom" path (e.g., the GIAB
    BED covers autosomes + X; a chrY site would have no intervals).
    Adequate depth → low_conf (we still have the pileup); inadequate →
    uncallable.
    """
    from genomeclaw_toolkit.prep._genotype_source import classify_site

    assert (
        classify_site(
            chrom="chrY",
            pos=150,
            depth=30,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "force_genotyped_low_conf"
    )
    assert (
        classify_site(
            chrom="chrY",
            pos=150,
            depth=5,
            nebula_called=False,
            giab_intervals=_INTERVALS,
        )
        == "uncallable"
    )


def test_classify_site_uncallable_when_giab_intervals_none() -> None:
    """When the GIAB intervals dict is empty (BED not fetched), all force-genotyped
    sites with adequate depth fall to `force_genotyped_low_conf`.

    The plan's fallback policy: don't block the pipeline if the user hasn't
    fetched GIAB; demote every force-genotyped site to low_conf so the agent
    sees the lower confidence but still gets a score.
    """
    from genomeclaw_toolkit.prep._genotype_source import classify_site

    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=30,
            nebula_called=False,
            giab_intervals={},
        )
        == "force_genotyped_low_conf"
    )
    assert (
        classify_site(
            chrom="chr1",
            pos=150,
            depth=2,
            nebula_called=False,
            giab_intervals={},
        )
        == "uncallable"
    )


# ---------------------------------------------------------------------------
# Sidecar TSV writer
# ---------------------------------------------------------------------------


def test_write_genotype_source_sidecar_round_trip(tmp_path: Path) -> None:
    """`write_genotype_source_sidecar` emits the documented TSV header + rows."""
    from genomeclaw_toolkit.prep._genotype_source import (
        write_genotype_source_sidecar,
    )

    sidecar = tmp_path / "forced_genotype_provenance.tsv"
    rows = [
        ("chr1", 150, "A", "G", "nebula_called"),
        ("chr1", 350, "C", "T", "force_genotyped_low_conf"),
        ("chr1", 150_001, "A", "T", "uncallable"),
        ("chr22", 15_000, "G", "C", "force_genotyped_high_conf"),
    ]
    written = write_genotype_source_sidecar(rows, sidecar)
    assert written == sidecar

    lines = sidecar.read_text().splitlines()
    assert lines[0] == "chrom\tpos\tref\talt\tgenotype_source"
    assert lines[1] == "chr1\t150\tA\tG\tnebula_called"
    assert lines[-1] == "chr22\t15000\tG\tC\tforce_genotyped_high_conf"
    assert len(lines) == 5  # 1 header + 4 rows


def test_write_genotype_source_sidecar_empty_rows_writes_header_only(tmp_path: Path) -> None:
    """Empty input produces a header-only TSV (truthful representation)."""
    from genomeclaw_toolkit.prep._genotype_source import (
        write_genotype_source_sidecar,
    )

    sidecar = tmp_path / "empty.tsv"
    write_genotype_source_sidecar([], sidecar)
    assert sidecar.read_text() == "chrom\tpos\tref\talt\tgenotype_source\n"

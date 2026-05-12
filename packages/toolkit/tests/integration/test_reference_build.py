"""Phase 2 — VCF-header reference-build sniffer (cases 11, 12).

The sniffer parses ``##contig=<ID=...,length=...>`` lines and matches them
against a small built-in lookup of (build, contig, length). All-match
returns the build; any contig/length mismatch returns *ambiguous* (the
caller raises a clear error with no derived store written).

These tests pass a list of contig metadata directly into the sniffer so
the test layer never has to write a real VCF; the bcftools-driven
end-to-end ingest path lands in sub-phase 2C with the synthetic-VCF
fixtures.
"""

from __future__ import annotations

import pytest


def test_invR001_sniffs_grch38_from_canonical_contigs() -> None:
    """Case 11: GRCh38 contigs in the header → sniffer returns ``"grch38"``."""
    from genomeclaw_toolkit.prep.reference_build import sniff_reference_build

    # A handful of canonical GRCh38 chromosome lengths.
    contigs = [
        ("chr1", 248956422),
        ("chr2", 242193529),
        ("chr17", 83257441),
        ("chrX", 156040895),
    ]
    assert sniff_reference_build(contigs) == "grch38"


def test_sniffs_grch37_from_canonical_contigs() -> None:
    """Symmetry: GRCh37 contigs round-trip cleanly too (forward-compatibility)."""
    from genomeclaw_toolkit.prep.reference_build import sniff_reference_build

    contigs = [
        ("1", 249250621),
        ("2", 243199373),
        ("17", 81195210),
        ("X", 155270560),
    ]
    assert sniff_reference_build(contigs) == "grch37"


def test_refuses_ambiguous_reference_build() -> None:
    """Case 12: hand-edited contigs that match neither build → ``AmbiguousReferenceBuild``."""
    from genomeclaw_toolkit.prep.reference_build import (
        AmbiguousReferenceBuild,
        sniff_reference_build,
    )

    bad_contigs = [
        ("chr1", 1),  # length doesn't match GRCh38 (248956422) or GRCh37 (249250621)
        ("chr2", 2),
    ]
    with pytest.raises(AmbiguousReferenceBuild):
        sniff_reference_build(bad_contigs)


def test_refuses_when_some_contigs_match_one_build_and_some_another() -> None:
    """Mixed-build contigs (a real-world copy-paste mistake) are also ambiguous."""
    from genomeclaw_toolkit.prep.reference_build import (
        AmbiguousReferenceBuild,
        sniff_reference_build,
    )

    mixed = [
        ("chr1", 248956422),  # grch38
        ("2", 243199373),  # grch37
    ]
    with pytest.raises(AmbiguousReferenceBuild):
        sniff_reference_build(mixed)


def test_refuses_when_no_contigs_provided() -> None:
    """An empty contig list is ambiguous, not a default."""
    from genomeclaw_toolkit.prep.reference_build import (
        AmbiguousReferenceBuild,
        sniff_reference_build,
    )

    with pytest.raises(AmbiguousReferenceBuild):
        sniff_reference_build([])


def test_unknown_contigs_outside_canonical_set_are_ignored() -> None:
    """A handful of GL/decoy contigs alongside canonical ones still sniff cleanly.

    Real VCFs from short-read pipelines often carry ``chrEBV``,
    ``HLA-*``, ``GL000*``, etc. The sniffer should match on the canonical
    chromosomes and not bail out because of a non-canonical entry.
    """
    from genomeclaw_toolkit.prep.reference_build import sniff_reference_build

    contigs = [
        ("chr1", 248956422),
        ("chr17", 83257441),
        ("HLA-A*01:01:01:01", 3503),
        ("chrEBV", 171823),
    ]
    assert sniff_reference_build(contigs) == "grch38"


# ---------------------------------------------------------------------------
# autodetect_reference_dir — pick the single build subdir under reference_root
# ---------------------------------------------------------------------------


def test_autodetect_reference_returns_single_build_subdir(tmp_path):
    """``reference_root`` with one build dir + assorted annotation dirs → that build dir."""
    from genomeclaw_toolkit.prep.reference_build import autodetect_reference_dir

    ref = tmp_path / "reference"
    (ref / "grch38" / "ncbi-2014").mkdir(parents=True)
    (ref / "clinvar" / "2026-05-09").mkdir(parents=True)
    (ref / "dbsnp" / "b157").mkdir(parents=True)

    assert autodetect_reference_dir(ref) == ref / "grch38"


def test_autodetect_reference_refuses_when_root_missing(tmp_path):
    from genomeclaw_toolkit.prep.reference_build import autodetect_reference_dir

    with pytest.raises(ValueError, match="reference root not found"):
        autodetect_reference_dir(tmp_path / "nope")


def test_autodetect_reference_refuses_when_no_build_dirs(tmp_path):
    """``reference_root`` with only annotation dirs (no build subdir) errors."""
    from genomeclaw_toolkit.prep.reference_build import autodetect_reference_dir

    ref = tmp_path / "reference"
    (ref / "clinvar").mkdir(parents=True)

    with pytest.raises(ValueError, match="no build subdirectories"):
        autodetect_reference_dir(ref)


def test_autodetect_reference_refuses_when_multiple_build_dirs(tmp_path):
    from genomeclaw_toolkit.prep.reference_build import autodetect_reference_dir

    ref = tmp_path / "reference"
    (ref / "grch37").mkdir(parents=True)
    (ref / "grch38").mkdir(parents=True)

    with pytest.raises(ValueError, match="multiple build subdirectories"):
        autodetect_reference_dir(ref)


# ---------------------------------------------------------------------------
# validate_reference_build_match — soft cross-check of path vs inferred build
# ---------------------------------------------------------------------------


def test_validate_passes_when_build_appears_in_reference_path(tmp_path):
    """Reference dir whose path contains the inferred build → silently OK."""
    from genomeclaw_toolkit.prep.reference_build import validate_reference_build_match

    ref = tmp_path / "reference" / "grch38" / "ncbi-2014"
    ref.mkdir(parents=True)
    validate_reference_build_match(ref, "grch38")  # does not raise


def test_validate_passes_when_path_has_no_build_signal(tmp_path):
    """No known build name in the path → no signal, validation skips."""
    from genomeclaw_toolkit.prep.reference_build import validate_reference_build_match

    ref = tmp_path / "reference"
    ref.mkdir()
    validate_reference_build_match(ref, "grch38")  # does not raise


def test_validate_refuses_when_path_contradicts_inferred_build(tmp_path):
    """Reference path says grch37, VCF infers grch38 → ReferenceBuildMismatch."""
    from genomeclaw_toolkit.prep.reference_build import (
        ReferenceBuildMismatch,
        validate_reference_build_match,
    )

    ref = tmp_path / "reference" / "grch37" / "b37"
    ref.mkdir(parents=True)
    with pytest.raises(ReferenceBuildMismatch, match="grch37"):
        validate_reference_build_match(ref, "grch38")

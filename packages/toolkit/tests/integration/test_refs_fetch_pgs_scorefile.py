"""Phase 5a — ``refs fetch --source pgs_scorefile`` first-class fetch source.

The user expectation (correct): every reference artefact the PRS pipeline
consumes must be reachable via the canonical ``host setup --fetch-all`` /
``refs fetch`` path. Phase 5's smoke pre-flight surfaced that PGS Catalog
scoring files were the one piece still missing from that envelope.

Phase 5a adds ``pgs_scorefile`` to ``_LAYOUTS``, parameterised by the
PGS Catalog ID (using the existing ``{release_n}`` substitution machinery
— the PGS ID becomes the "release" string), with PGS000018 wired into
the default release set so a from-scratch ``host setup --fetch-all``
stages it automatically.

Contract assertions (6 tests; phase-5a.md Step 5a.1):

1. ``_LAYOUTS["pgs_scorefile"]`` declared + relpath carries ``{release_n}``.
2. Default base URL points at the PGS Catalog FTP.
3. Happy path — fetch downloads to ``reference/pgs_scorefiles/<PGS_ID>_hmPOS_GRCh38.txt.gz``.
4. INV-D001 skip-detection — second fetch raises ``VersionAlreadyExists``.
5. ``release_sets/default.toml`` lists PGS000018 as a ``pgs_scorefile`` entry.

(Test 6 — doctor probe — lives in ``test_doctor.py`` alongside the other
doctor sections.)

Real-fetch verification (post-GREEN): ``curl -I`` against the live PGS
Catalog FTP returns 200 for ``https://ftp.ebi.ac.uk/pub/databases/spot/
pgs/scores/PGS000018/ScoringFiles/Harmonized/PGS000018_hmPOS_GRCh38.txt.gz``
— confirmed before writing this test file.
"""

from __future__ import annotations

from pathlib import Path

from pytest_httpserver import HTTPServer

_PGS_ID = "PGS000018"
_PGS_SCOREFILE_RELPATH = (
    f"/pub/databases/spot/pgs/scores/{_PGS_ID}/"
    f"ScoringFiles/Harmonized/{_PGS_ID}_hmPOS_GRCh38.txt.gz"
)
_SYNTHETIC_PAYLOAD = (
    b"###PGS CATALOG SCORING FILE\n"
    b"#format_version=2.0\n"
    b"#pgs_id=PGS000018\n"
    b"#pgs_name=metaGRS_CAD\n"
    b"#genome_build=GRCh38\n"
    b"hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
    b"22\t20001\tG\tA\t0.0123\n"
)


# ---------------------------------------------------------------------------
# Test 1 — layout declaration
# ---------------------------------------------------------------------------


def test_pgs_scorefile_layout_declared() -> None:
    """`_LAYOUTS["pgs_scorefile"]` exists; relpath carries `{release_n}` substitution."""
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    layout = _LAYOUTS["pgs_scorefile"]
    assert len(layout.files) == 1, (
        f"pgs_scorefile layout must have exactly one file template; got {layout.files!r}"
    )
    f = layout.files[0]
    assert "{release_n}" in f.relpath, (
        f"pgs_scorefile relpath must template the PGS ID via {{release_n}}; got {f.relpath!r}"
    )
    assert "{release_n}" in f.output_filename
    # The harmonised-position suffix is what pgsc_calc expects.
    assert "hmPOS_GRCh38" in f.relpath
    assert "hmPOS_GRCh38" in f.output_filename
    # Lands under reference/pgs_scorefiles/
    # Canonical layout follows reference/<source>/<release>/<file>; no extra
    # output_subdir needed (the per-source + per-release nesting is enough).
    assert layout.output_subdir == ""


# ---------------------------------------------------------------------------
# Test 2 — default base URL
# ---------------------------------------------------------------------------


def test_pgs_scorefile_default_base_url_is_pgs_catalog_ftp() -> None:
    """`_DEFAULT_BASE_URLS["pgs_scorefile"]` points at ftp.ebi.ac.uk."""
    from genomeclaw_toolkit.prep.fetch import _DEFAULT_BASE_URLS

    assert _DEFAULT_BASE_URLS["pgs_scorefile"] == "https://ftp.ebi.ac.uk"


# ---------------------------------------------------------------------------
# Test 3 — happy path fetch
# ---------------------------------------------------------------------------


def test_pgs_scorefile_fetch_happy_path(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Fetch downloads to the canonical `reference/pgs_scorefiles/<PGS_ID>_hmPOS_GRCh38.txt.gz` path."""
    from genomeclaw_toolkit.prep.fetch import fetch

    httpserver.expect_request(_PGS_SCOREFILE_RELPATH).respond_with_data(
        _SYNTHETIC_PAYLOAD,
        content_type="application/gzip",
    )
    base_url = httpserver.url_for("").rstrip("/")

    fetch(
        source="pgs_scorefile",
        reference_root=tmp_path,
        release=_PGS_ID,
        base_url=base_url,
    )

    # Canonical landing: reference/pgs_scorefile/<PGS_ID>/<PGS_ID>_hmPOS_GRCh38.txt.gz
    # (mirrors grch38's per-source / per-release nesting).
    target = (
        tmp_path / "pgs_scorefile" / _PGS_ID / f"{_PGS_ID}_hmPOS_GRCh38.txt.gz"
    )
    assert target.exists(), f"scorefile missing: {target}"
    assert target.read_bytes() == _SYNTHETIC_PAYLOAD


# ---------------------------------------------------------------------------
# Test 4 — INV-D001 skip-detection
# ---------------------------------------------------------------------------


def test_pgs_scorefile_skip_detection_invD001(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Second fetch against the same release raises ``VersionAlreadyExists``.

    INV-D001: avoid redundant downloads of an already-staged scorefile.
    The output file's existence is the durable signal (no post-fetch hook
    deletes it, so no `presence_relpath` is required).
    """
    import pytest

    from genomeclaw_toolkit.prep.fetch import VersionAlreadyExists, fetch

    httpserver.expect_request(_PGS_SCOREFILE_RELPATH).respond_with_data(
        _SYNTHETIC_PAYLOAD,
        content_type="application/gzip",
    )
    base_url = httpserver.url_for("").rstrip("/")

    fetch(
        source="pgs_scorefile",
        reference_root=tmp_path,
        release=_PGS_ID,
        base_url=base_url,
    )
    with pytest.raises(VersionAlreadyExists):
        fetch(
            source="pgs_scorefile",
            reference_root=tmp_path,
            release=_PGS_ID,
            base_url=base_url,
        )


# ---------------------------------------------------------------------------
# Test 5 — release-set wiring
# ---------------------------------------------------------------------------


def test_pgs000018_in_default_release_set() -> None:
    """`release_sets/default.toml` lists PGS000018 as a `pgs_scorefile` entry.

    ``host setup --fetch-all`` iterates the default release set; the
    smoke baseline (PGS000018) is staged automatically as part of the
    canonical from-scratch setup path.
    """
    from genomeclaw_toolkit.prep.release_sets import load_release_set

    release_set = load_release_set()
    pgs_scorefile_entries = [
        s for s in release_set.sources if s.source == "pgs_scorefile"
    ]
    assert pgs_scorefile_entries, (
        "release_sets/default.toml must list at least one pgs_scorefile entry; "
        "PGS000018 is the smoke baseline"
    )
    releases = {entry.release for entry in pgs_scorefile_entries}
    assert _PGS_ID in releases, (
        f"PGS000018 missing from default release set's pgs_scorefile entries; "
        f"got {sorted(releases)}"
    )

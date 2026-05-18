"""Phase 1 of prs-reference-bootstrap — `genomeclaw refs fetch --source pgs_catalog_ancestry`.

Closes the phantom-CLI gap left open by Slice E v2: the install hint in
`prep/pgs.py:_check_ancestry_reference` pointed at a source that didn't
exist in `_LAYOUTS` or `release_sets/default.toml`.

Six contract assertions:

1. Happy path — fetch downloads `pgsc_HGDP+1kGP_<release>.tar.zst` from the
   PGS Catalog FTP mirror, extracts it via streaming zstandard + tarfile
   into ``reference/pgs_catalog_ancestry/<release>/{1000g,hgdp}/``, and
   deletes the bundle.
2. INV-D001 skip-detection — a second `fetch` against the same release
   raises `VersionAlreadyExists` without re-downloading the bundle (via
   the same `presence_relpath` mechanism vep_cache uses).
3. Layout shape — `_LAYOUTS["pgs_catalog_ancestry"]` declares a
   `presence_relpath` (required because the post-fetch hook deletes the
   canonical artifact, same constraint as vep_cache).
4. Release-set wiring — the new source is listed in
   `release_sets/default.toml` so `genomeclaw refs fetch --all` and
   `genomeclaw host setup --fetch-all` pick it up.
5. `_check_ancestry_reference` resolves the canonical materialised layout
   (`reference/pgs_catalog_ancestry/<release>/{1000g,hgdp}/`), not the
   Slice E v2 placeholder (`reference/ancestry/{1000g,hgdp}/`).
6. Install hint — when the reference is missing, the error message
   contains the literal `genomeclaw refs fetch --source pgs_catalog_ancestry`
   (matches the real subcommand that this phase makes work).
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

_PGS_ANCESTRY_RELEASE = "v1"
_PGS_ANCESTRY_RELPATH = (
    f"/pub/databases/spot/pgs/resources/pgsc_HGDP+1kGP_{_PGS_ANCESTRY_RELEASE}.tar.zst"
)

# Canonical filenames the bundle is expected to contain post-extraction.
# Verified upstream layout (2026-05-17 real-data smoke against PGS Catalog
# v1 bundle): gnomAD-merged 1000G + HGDP callset extracts FLAT, NO per-
# population subdirs. Combined files keyed by reference build.
_CANONICAL_BUNDLE_FILES: tuple[str, ...] = (
    "GRCh38_HGDP+1kGP_ALL.pgen",
    "GRCh38_HGDP+1kGP_ALL.pvar.zst",
    "GRCh38_HGDP+1kGP_ALL.psam",
)


def _build_synthetic_ancestry_bundle_zst() -> bytes:
    """Build a tiny synthetic `.tar.zst` whose layout matches the real bundle.

    Each entry is a 4-byte placeholder — tests never parse the payload, only
    assert path layout after the fetcher's streaming-zstandard +
    streaming-tarfile post-fetch hook completes.
    """
    import zstandard  # toolkit dep added in GREEN step

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        for name in _CANONICAL_BUNDLE_FILES:
            info = tarfile.TarInfo(name=name)
            info.size = 4
            tf.addfile(info, io.BytesIO(b"data"))
    tar_buf.seek(0)
    return zstandard.ZstdCompressor().compress(tar_buf.read())


def _stage_pgs_ancestry_response(httpserver: HTTPServer) -> str:
    """Wire the PGS Catalog FTP endpoint with the synthetic `.tar.zst` payload."""
    httpserver.expect_request(_PGS_ANCESTRY_RELPATH).respond_with_data(
        _build_synthetic_ancestry_bundle_zst(),
        content_type="application/zstd",
    )
    return httpserver.url_for("").rstrip("/")


# ---------------------------------------------------------------------------
# Test 1: happy path — fetch + extract + cleanup
# ---------------------------------------------------------------------------


def test_fetch_pgs_catalog_ancestry_happy_path(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Fetch writes the bundle, extracts via streaming zstd+tar, and deletes the .tar.zst."""
    pytest.importorskip("zstandard")
    from genomeclaw_toolkit.prep.fetch import fetch

    base_url = _stage_pgs_ancestry_response(httpserver)
    fetch(
        source="pgs_catalog_ancestry",
        reference_root=tmp_path,
        release=_PGS_ANCESTRY_RELEASE,
        base_url=base_url,
    )

    release_dir = tmp_path / "pgs_catalog_ancestry" / _PGS_ANCESTRY_RELEASE
    # Every canonical file landed under the expected relative path.
    for relpath in _CANONICAL_BUNDLE_FILES:
        target = release_dir / relpath
        assert target.exists(), f"missing extracted file: {target}"
        assert target.read_bytes() == b"data"

    # The .tar.zst bundle is gone after extraction (reclaim disk).
    leftover_bundle = release_dir / "pgs_catalog_ancestry.tar.zst"
    assert not leftover_bundle.exists(), "post-fetch hook must delete the bundle after extraction"


# ---------------------------------------------------------------------------
# Test 2: INV-D001 skip-detection via presence_relpath
# ---------------------------------------------------------------------------


def test_fetch_pgs_catalog_ancestry_skip_detection_invD001(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """A second fetch against the same release raises VersionAlreadyExists (INV-D001).

    The post-fetch hook deletes the canonical .tar.zst, so the default
    "any canonical file exists" check would let `fetch --all` redownload
    the entire ~5-7 GB bundle every time. The `presence_relpath` marker
    (analogous to vep_cache's `homo_sapiens/<N>_GRCh38/info.txt`) is the
    durable signal that catches the skip.
    """
    pytest.importorskip("zstandard")
    from genomeclaw_toolkit.prep.fetch import VersionAlreadyExists, fetch

    base_url = _stage_pgs_ancestry_response(httpserver)
    fetch(
        source="pgs_catalog_ancestry",
        reference_root=tmp_path,
        release=_PGS_ANCESTRY_RELEASE,
        base_url=base_url,
    )

    with pytest.raises(VersionAlreadyExists):
        fetch(
            source="pgs_catalog_ancestry",
            reference_root=tmp_path,
            release=_PGS_ANCESTRY_RELEASE,
            base_url=base_url,
        )


# ---------------------------------------------------------------------------
# Test 3: layout declares presence_relpath
# ---------------------------------------------------------------------------


def test_pgs_catalog_ancestry_layout_declares_presence_marker() -> None:
    """`pgs_catalog_ancestry` must declare a `presence_relpath` — same structural
    reason as vep_cache: the post-fetch hook intentionally deletes the canonical
    .tar.zst, so the default existence-check would re-download on every invocation.
    """
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    layout = _LAYOUTS["pgs_catalog_ancestry"]
    assert layout.presence_relpath is not None, (
        "pgs_catalog_ancestry needs presence_relpath; the .tar.zst is deleted post-extract"
    )
    # The marker must point at one of the canonical extracted files (the
    # GRCh38 combined callset; verified upstream layout 2026-05-17) so the
    # doctor's structural check matches the presence-marker probe.
    assert "GRCh38_HGDP+1kGP_ALL" in layout.presence_relpath, (
        f"presence_relpath must point at extracted ancestry data, got {layout.presence_relpath!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: release-set wiring
# ---------------------------------------------------------------------------


def test_pgs_catalog_ancestry_in_default_release_set() -> None:
    """`pgs_catalog_ancestry` is listed in `release_sets/default.toml` so that
    `genomeclaw refs fetch --all` and `host setup --fetch-all` pick it up.
    """
    from genomeclaw_toolkit.prep.release_sets import load_release_set

    release_set = load_release_set()
    source_names = {entry.source for entry in release_set.sources}
    assert "pgs_catalog_ancestry" in source_names, (
        f"pgs_catalog_ancestry missing from default release set; have {sorted(source_names)}"
    )


# ---------------------------------------------------------------------------
# Test 5: _check_ancestry_reference resolves the canonical layout
# ---------------------------------------------------------------------------


def test_check_ancestry_reference_resolves_canonical_layout(tmp_path: Path) -> None:
    """`_check_ancestry_reference` accepts the canonical post-fetch layout.

    Verified upstream layout (2026-05-17): bundle extracts FLAT into
    `reference/pgs_catalog_ancestry/<release>/` — no per-population
    subdirs. Combined ``GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}`` files
    are what pgsc_calc reads.
    """
    from genomeclaw_toolkit.prep.pgs import _check_ancestry_reference

    ref = tmp_path / "reference"
    canonical_root = ref / "pgs_catalog_ancestry" / _PGS_ANCESTRY_RELEASE
    canonical_root.mkdir(parents=True)
    for relpath in _CANONICAL_BUNDLE_FILES:
        (canonical_root / relpath).write_bytes(b"data")

    # No raise expected — the canonical layout satisfies the check.
    _check_ancestry_reference(ref)


# ---------------------------------------------------------------------------
# Test 6: install hint points at the real subcommand
# ---------------------------------------------------------------------------


def test_check_ancestry_reference_install_hint_points_at_real_subcommand(
    tmp_path: Path,
) -> None:
    """When the reference is missing, the error message contains the literal
    `genomeclaw refs fetch --source pgs_catalog_ancestry` so the hint maps to
    a subcommand the user can actually run (no more phantom CLI).
    """
    from genomeclaw_toolkit.prep.pgs import PgsReferenceMissingError, _check_ancestry_reference

    ref = tmp_path / "reference"
    ref.mkdir()  # exists but ancestry data not staged

    with pytest.raises(PgsReferenceMissingError) as excinfo:
        _check_ancestry_reference(ref)

    msg = str(excinfo.value)
    assert "genomeclaw refs fetch --source pgs_catalog_ancestry" in msg, (
        f"install hint must match real subcommand; got: {msg!r}"
    )

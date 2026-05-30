"""`genomeclaw refs fetch --source giab_high_confidence` against a mocked HTTP backend.

Phase 1 of force-genotype-callable-mask. Adds the GIAB Personal Genomes
Benchmark NA12878/HG001 v4.2.1 high-confidence regions BED as a
fetchable reference source. The downloaded BED is the canonical truth
source for "regions where short-read WGS variant calling is reliable"
and is consumed by Phase 2's per-site `genotype_source` classifier
in `coverage_fill.py`.

NCBI FTP base: https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/
NA12878_HG001/NISTv4.2.1/GRCh38/. The `.bed.gz` carries an `.md5`
sidecar (Mode 1, same as `clinvar` and `dbsnp`); the `.tbi` has no
MD5 (structural integrity verified at first tabix query).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer


_TINY_BED_BYTES = b"chr1\t10000\t100000\nchr2\t10000\t100000\n"
_TINY_BED_MD5 = hashlib.md5(_TINY_BED_BYTES).hexdigest()
_TINY_TBI_BYTES = b"giab-tbi-mock"

_BASE = (
    "/giab/ftp/release/NA12878_HG001/NISTv4.2.1/GRCh38"
)
_BED_NAME = "HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz"


def _stage_giab_response(
    httpserver: HTTPServer, *, md5_override: str | None = None
) -> str:
    """Wire mocked NCBI endpoints for the GIAB BED + .md5 + .tbi files."""
    md5_to_serve = md5_override or _TINY_BED_MD5
    httpserver.expect_request(f"{_BASE}/{_BED_NAME}").respond_with_data(
        _TINY_BED_BYTES, content_type="application/gzip"
    )
    httpserver.expect_request(f"{_BASE}/{_BED_NAME}.md5").respond_with_data(
        f"{md5_to_serve}  {_BED_NAME}\n".encode(),
        content_type="text/plain",
    )
    httpserver.expect_request(f"{_BASE}/{_BED_NAME}.tbi").respond_with_data(
        _TINY_TBI_BYTES, content_type="application/octet-stream"
    )
    return httpserver.url_for("").rstrip("/")


def test_giab_layout_registered() -> None:
    """`giab_high_confidence` is a recognised source with the documented file shape."""
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    assert "giab_high_confidence" in _LAYOUTS
    layout = _LAYOUTS["giab_high_confidence"]
    assert layout.files, "giab_high_confidence layout has no static files"
    assert len(layout.files) == 2, (
        f"expected 2 files (bed.gz + tbi); got {len(layout.files)}"
    )
    names = {f.output_filename for f in layout.files}
    assert names == {_BED_NAME, f"{_BED_NAME}.tbi"}, f"unexpected file names: {names!r}"


def test_giab_layout_bed_has_md5_sidecar() -> None:
    """The .bed.gz entry carries Mode-1 MD5 (per-file sidecar, not directory checksums.txt)."""
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    layout = _LAYOUTS["giab_high_confidence"]
    bed_entry = next(f for f in layout.files if f.output_filename == _BED_NAME)
    assert bed_entry.md5_relpath is not None, "GIAB .bed.gz must have an md5_relpath"
    assert bed_entry.md5_checksums_relpath is None, (
        "GIAB uses Mode 1 (per-file sidecar), not Mode 2 (directory checksums)"
    )


def test_giab_layout_tbi_has_no_md5() -> None:
    """The .tbi entry has no MD5 (NCBI doesn't publish one; structural verify at query time)."""
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    layout = _LAYOUTS["giab_high_confidence"]
    tbi_entry = next(
        f for f in layout.files if f.output_filename == f"{_BED_NAME}.tbi"
    )
    assert tbi_entry.md5_relpath is None
    assert tbi_entry.md5_checksums_relpath is None


def test_giab_fetch_downloads_and_verifies_mocked(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Happy path: fetch writes the BED + .tbi + per-file MD5 sidecar under reference root."""
    from genomeclaw_toolkit.prep.fetch import fetch

    base_url = _stage_giab_response(httpserver)
    written = fetch(
        source="giab_high_confidence",
        reference_root=tmp_path,
        release="v4.2.1-hg001",
        base_url=base_url,
    )

    target_dir = tmp_path / "giab_high_confidence" / "v4.2.1-hg001"
    expected = target_dir / _BED_NAME
    assert written == expected
    assert expected.read_bytes() == _TINY_BED_BYTES
    assert (target_dir / f"{_BED_NAME}.tbi").read_bytes() == _TINY_TBI_BYTES
    assert _TINY_BED_MD5 in (target_dir / f"{_BED_NAME}.md5").read_text()


def test_giab_fetch_rejects_checksum_mismatch_mocked(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Wrong BED checksum → ChecksumMismatch; no canonical file written."""
    from genomeclaw_toolkit.prep.fetch import ChecksumMismatch, fetch

    base_url = _stage_giab_response(httpserver, md5_override="0" * 32)
    with pytest.raises(ChecksumMismatch):
        fetch(
            source="giab_high_confidence",
            reference_root=tmp_path,
            release="v4.2.1-hg001",
            base_url=base_url,
        )

    target_dir = tmp_path / "giab_high_confidence" / "v4.2.1-hg001"
    assert not (target_dir / _BED_NAME).exists(), (
        "ChecksumMismatch must not leave a partial file on disk"
    )


def test_giab_invR001_release_in_path(tmp_path: Path, httpserver: HTTPServer) -> None:
    """INV-R001: the release string is structurally encoded in the target directory path.

    Rebuildability requires that a given BED file's release is recoverable from disk
    layout alone (no hidden manifest lookup). The target dir for release `v4.2.1-hg001`
    must be `<reference_root>/giab_high_confidence/v4.2.1-hg001/`.
    """
    from genomeclaw_toolkit.prep.fetch import fetch

    base_url = _stage_giab_response(httpserver)
    written = fetch(
        source="giab_high_confidence",
        reference_root=tmp_path,
        release="v4.2.1-hg001",
        base_url=base_url,
    )
    assert written.parent == tmp_path / "giab_high_confidence" / "v4.2.1-hg001"


def test_giab_invD001_no_raw_mutation(tmp_path: Path, httpserver: HTTPServer) -> None:
    """INV-D001: fetch writes under reference_root only; no `data/raw/` mutation possible.

    A guard test confirming the fetch destination resolves to the supplied
    reference_root tree and nothing else.
    """
    from genomeclaw_toolkit.prep.fetch import fetch

    base_url = _stage_giab_response(httpserver)
    raw_root = tmp_path / "raw_should_not_change"
    raw_root.mkdir()
    sentinel = raw_root / "marker.txt"
    sentinel.write_text("untouched")

    fetch(
        source="giab_high_confidence",
        reference_root=tmp_path / "reference",
        release="v4.2.1-hg001",
        base_url=base_url,
    )

    assert sentinel.read_text() == "untouched"
    assert (tmp_path / "reference" / "giab_high_confidence" / "v4.2.1-hg001" / _BED_NAME).exists()

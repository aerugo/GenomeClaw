"""Unit tests for :mod:`genomeclaw_toolkit.prep._bgzip`.

Covers the four cases the helper must distinguish:

* A clean bgzipped file (ends with the canonical 28-byte BGZF EOF marker).
* A truncated bgzipped file (valid header, junk tail).
* A plain-gzip file (no BGZF framing at all).
* A missing path (raise, don't silently return False).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER, verify_bgzip_eof_marker


def _write_clean_bgzip(path: Path) -> None:
    """Write a minimal bgzipped file: one empty data block + the EOF marker.

    For the integrity check we don't need a real payload — just that
    the trailing 28 bytes match. We include the marker twice (once as
    a "body" block, once as the EOF) to mimic htslib's output style.
    """
    path.write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)


def _write_truncated_bgzip(path: Path) -> None:
    """Write a bgzipped-looking file with arbitrary trailing bytes."""
    path.write_bytes(BGZF_EOF_MARKER + b"junk-bytes-this-is-truncated-content")


def _write_plain_gzip(path: Path) -> None:
    """Write a plain-gzip file (different magic; no BGZF EOF block)."""
    # Plain gzip: 1f 8b 08 00 ... — note the 0x00 vs bgzip's 0x04.
    path.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 24 + b"trailing-junk")


def test_verify_returns_true_for_clean_bgzip(tmp_path: Path) -> None:
    p = tmp_path / "clean.vcf.gz"
    _write_clean_bgzip(p)
    assert verify_bgzip_eof_marker(p) is True


def test_verify_returns_false_for_truncated_bgzip(tmp_path: Path) -> None:
    p = tmp_path / "truncated.vcf.gz"
    _write_truncated_bgzip(p)
    assert verify_bgzip_eof_marker(p) is False


def test_verify_returns_false_for_plain_gzip(tmp_path: Path) -> None:
    p = tmp_path / "plain.gz"
    _write_plain_gzip(p)
    assert verify_bgzip_eof_marker(p) is False


def test_verify_raises_for_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_bgzip_eof_marker(tmp_path / "does-not-exist")


def test_verify_does_not_mutate_source(tmp_path: Path) -> None:
    """`INV-D001`: the verifier must not modify the file it inspects."""
    p = tmp_path / "clean.vcf.gz"
    _write_clean_bgzip(p)
    before = p.read_bytes()
    verify_bgzip_eof_marker(p)
    after = p.read_bytes()
    assert before == after

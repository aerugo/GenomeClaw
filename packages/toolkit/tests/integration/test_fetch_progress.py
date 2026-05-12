"""Progress output + streaming behavior for ``genomeclaw refs fetch``.

The streaming rewrite (1 MiB chunks, periodic progress lines, in-stream
MD5 hashing) replaced an earlier in-memory ``urlopen().read()`` path
that both kept multi-GB payloads resident in Python and produced zero
output during a 10-minute download. These tests pin:

- Per-file ``↓ <filename>`` announcement.
- Per-file ``✓ <bytes> in <s>s`` completion line.
- The byte-formatter handles 0 / sub-KB / GB-scale numbers.
- The downloaded file matches the served payload byte-for-byte (memory-
  free streaming hasn't broken correctness).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pytest_httpserver import HTTPServer


def _stage_clinvar(httpserver: HTTPServer, payload: bytes) -> str:
    """Wire a mocked ClinVar VCF + matching MD5 sidecar + .tbi; return base URL."""
    md5 = hashlib.md5(payload).hexdigest()
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz").respond_with_data(
        payload, content_type="application/gzip"
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.md5").respond_with_data(
        f"{md5}  clinvar.vcf.gz\n".encode(),
        content_type="text/plain",
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.tbi").respond_with_data(
        b"clinvar-tbi-mock-bytes", content_type="application/octet-stream"
    )
    return httpserver.url_for("").rstrip("/")


def test_fetch_prints_per_file_announce_and_completion(
    httpserver: HTTPServer, tmp_path: Path, capsys
) -> None:
    """A successful fetch emits ``↓ <file>`` then ``✓ <bytes> in <s>s``."""
    from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER
    from genomeclaw_toolkit.prep.fetch import fetch

    payload = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\n" * 100 + BGZF_EOF_MARKER
    base_url = _stage_clinvar(httpserver, payload)

    fetch(source="clinvar", reference_root=tmp_path, release="t1", base_url=base_url)

    out = capsys.readouterr().out
    assert "↓ clinvar.vcf.gz" in out
    # The completion line carries elapsed time + throughput; match the
    # invariant prefix without pinning the timing numbers.
    assert "✓" in out and " in " in out and "/s)" in out


def test_fetch_streams_full_payload_byte_for_byte(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Streaming write + on-disk content == served bytes, exact match."""
    from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER
    from genomeclaw_toolkit.prep.fetch import fetch

    # A few MiB of pseudo-random bytes — large enough that a 1 MiB chunk
    # loop has to iterate, but small enough not to slow the suite.
    payload = b"".join((b"%d" % i) * 1024 for i in range(2048)) + BGZF_EOF_MARKER
    base_url = _stage_clinvar(httpserver, payload)

    written = fetch(source="clinvar", reference_root=tmp_path, release="t2", base_url=base_url)

    assert written.read_bytes() == payload


def test_human_bytes_handles_zero_kb_mb_gb_boundaries() -> None:
    from genomeclaw_toolkit.prep.fetch import _human_bytes

    assert _human_bytes(0) == "0 B"
    assert _human_bytes(512) == "512 B"
    assert _human_bytes(1024) == "1.0 KB"
    assert _human_bytes(1_500_000) == "1.4 MB"
    assert _human_bytes(2.5 * 1024**3) == "2.5 GB"
    assert _human_bytes(3.2 * 1024**4) == "3.2 TB"


def test_parse_md5_from_checksums_matches_correct_line() -> None:
    """Pick the right line from a multi-file ``md5checksums.txt``."""
    from genomeclaw_toolkit.prep.fetch import _parse_md5_from_checksums

    blob = (
        b"deadbeef00000000000000000000dead  ./some_other.fna.gz\n"
        b"5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8  ./target.fna.gz\n"
        b"1111111111111111111111111111aaaa  ./yet_another.fna.gz\n"
    )
    assert (
        _parse_md5_from_checksums(blob, key="./target.fna.gz")
        == "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
    )


def test_parse_md5_from_checksums_raises_when_key_absent() -> None:
    """A missing key surfaces ChecksumMismatch — the upstream layout shifted."""
    import pytest

    from genomeclaw_toolkit.prep.fetch import ChecksumMismatch, _parse_md5_from_checksums

    blob = b"deadbeef00000000000000000000dead  ./some_other.fna.gz\n"
    with pytest.raises(ChecksumMismatch, match="no entry"):
        _parse_md5_from_checksums(blob, key="./missing.fna.gz")

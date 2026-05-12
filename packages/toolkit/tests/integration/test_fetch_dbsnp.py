"""Phase 4C.1 — ``genomeclaw refs fetch --source dbsnp`` against a mocked HTTP backend.

dbSNP ships at ``https://ftp.ncbi.nlm.nih.gov/snp/latest_release/VCF/``
as one bgzipped VCF per RefSeq assembly accession. The GRCh38 file is
``GCF_000001405.40.gz``; the matching ``.tbi`` ships alongside, both
with their own ``.md5`` sidecars in the standard NCBI convention.
(The older aggregate ``00-All.vcf.gz`` was retired after b156; relying
on it 404s.) These tests gate the URL pattern + the two-file layout;
the existing ClinVar tests cover the shared fetcher logic (checksum
verification, atomic-rename, scratch cleanup on failure).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER  # noqa: E402

_TINY_VCF_BYTES = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\trsid\n" + BGZF_EOF_MARKER
_TINY_VCF_MD5 = hashlib.md5(_TINY_VCF_BYTES).hexdigest()
_TINY_TBI_BYTES = b"tbi-mock-bytes"
_TINY_TBI_MD5 = hashlib.md5(_TINY_TBI_BYTES).hexdigest()


def _stage_dbsnp_response(httpserver: HTTPServer, *, md5_override: str | None = None) -> str:
    """Wire mocked NCBI endpoints for dbSNP: GCF_000001405.40 VCF + .tbi + .md5 sidecars."""
    vcf_md5_to_serve = md5_override or _TINY_VCF_MD5
    base = "/snp/latest_release/VCF"
    httpserver.expect_request(f"{base}/GCF_000001405.40.gz").respond_with_data(
        _TINY_VCF_BYTES, content_type="application/gzip"
    )
    httpserver.expect_request(f"{base}/GCF_000001405.40.gz.md5").respond_with_data(
        f"{vcf_md5_to_serve}  GCF_000001405.40.gz\n".encode(),
        content_type="text/plain",
    )
    httpserver.expect_request(f"{base}/GCF_000001405.40.gz.tbi").respond_with_data(
        _TINY_TBI_BYTES, content_type="application/octet-stream"
    )
    httpserver.expect_request(f"{base}/GCF_000001405.40.gz.tbi.md5").respond_with_data(
        f"{_TINY_TBI_MD5}  GCF_000001405.40.gz.tbi\n".encode(),
        content_type="text/plain",
    )
    return httpserver.url_for("").rstrip("/")


def test_fetch_dbsnp_writes_versioned_path_mocked(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Case 9: fetch writes both ``dbsnp.vcf.gz`` + its tabix index + per-file MD5 sidecars."""
    from genomeclaw_toolkit.prep.fetch import fetch

    base_url = _stage_dbsnp_response(httpserver)
    written = fetch(
        source="dbsnp",
        reference_root=tmp_path,
        release="b157",
        base_url=base_url,
    )

    target_dir = tmp_path / "dbsnp" / "b157"
    expected = target_dir / "dbsnp.vcf.gz"
    assert written == expected
    assert expected.exists()
    assert expected.read_bytes() == _TINY_VCF_BYTES

    tbi = target_dir / "dbsnp.vcf.gz.tbi"
    assert tbi.exists()
    assert tbi.read_bytes() == _TINY_TBI_BYTES

    assert (target_dir / "dbsnp.vcf.gz.md5").exists()
    assert _TINY_VCF_MD5 in (target_dir / "dbsnp.vcf.gz.md5").read_text()
    assert (target_dir / "dbsnp.vcf.gz.tbi.md5").exists()
    assert _TINY_TBI_MD5 in (target_dir / "dbsnp.vcf.gz.tbi.md5").read_text()


def test_fetch_dbsnp_rejects_checksum_mismatch_mocked(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Parity with ClinVar: wrong VCF checksum → ChecksumMismatch; no canonical file written."""
    from genomeclaw_toolkit.prep.fetch import ChecksumMismatch, fetch

    base_url = _stage_dbsnp_response(httpserver, md5_override="0" * 32)

    with pytest.raises(ChecksumMismatch):
        fetch(
            source="dbsnp",
            reference_root=tmp_path,
            release="b157",
            base_url=base_url,
        )

    canonical = tmp_path / "dbsnp" / "b157" / "dbsnp.vcf.gz"
    assert not canonical.exists()

"""Phase 2 — ``genomeclaw refs fetch`` against a mocked HTTP backend.

Covers test cases 14, 15 from
``docs/plans/active/mvp/phases/phase-2.md`` Step 2.1 and case 3 (the
INV-D001 "fetch never overwrites an existing version" test).

Real ClinVar / gnomAD / dbSNP downloads are deliberate user-initiated
HTTPS calls; for tests we redirect via ``base_url`` to a
``pytest-httpserver`` instance so CI never reaches outside the runner.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

# A tiny synthetic "VCF" payload — the test never parses it. Includes
# the canonical 28-byte BGZF EOF marker so the fetcher's post-download
# integrity gate passes (Phase 3 wires it for every `.vcf.gz` file).
from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER  # noqa: E402

_TINY_VCF_BYTES = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\n" + BGZF_EOF_MARKER
_TINY_VCF_MD5 = hashlib.md5(_TINY_VCF_BYTES).hexdigest()
_TINY_TBI_BYTES = b"clinvar-tbi-mock-bytes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stage_clinvar_response(httpserver: HTTPServer, *, md5_override: str | None = None) -> str:
    """Wire a mocked NCBI-style endpoint trio: VCF + .tbi + per-file MD5 sidecar.

    Returns the base URL the toolkit's ``fetch`` should be pointed at.
    """
    md5_to_serve = md5_override or _TINY_VCF_MD5
    # ClinVar's real layout publishes:
    #   <root>/vcf_GRCh38/clinvar.vcf.gz
    #   <root>/vcf_GRCh38/clinvar.vcf.gz.md5
    #   <root>/vcf_GRCh38/clinvar.vcf.gz.tbi   (no matching .tbi.md5)
    # The .md5 file is `<hex> <space> <filename>` (NCBI convention).
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz").respond_with_data(
        _TINY_VCF_BYTES, content_type="application/gzip"
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.md5").respond_with_data(
        f"{md5_to_serve}  clinvar.vcf.gz\n".encode(),
        content_type="text/plain",
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.tbi").respond_with_data(
        _TINY_TBI_BYTES, content_type="application/octet-stream"
    )
    return httpserver.url_for("").rstrip("/")


# ---------------------------------------------------------------------------
# Test cases 14, 15, 3
# ---------------------------------------------------------------------------


def test_fetch_clinvar_writes_versioned_path_mocked(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Case 14: fetch writes to ``reference/clinvar/<release>/clinvar.vcf.gz`` and verifies MD5."""
    from genomeclaw_toolkit.prep.fetch import fetch

    base_url = _stage_clinvar_response(httpserver)
    written = fetch(
        source="clinvar",
        reference_root=tmp_path,
        release="2026-04",
        base_url=base_url,
    )

    expected = tmp_path / "clinvar" / "2026-04" / "clinvar.vcf.gz"
    assert written == expected
    assert expected.exists()
    assert expected.read_bytes() == _TINY_VCF_BYTES

    # The MD5 sidecar lands alongside the VCF so the user (and a future
    # offline reanalysis) can confirm what was downloaded.
    md5_sidecar = tmp_path / "clinvar" / "2026-04" / "clinvar.vcf.gz.md5"
    assert md5_sidecar.exists()
    assert _TINY_VCF_MD5 in md5_sidecar.read_text()

    # Tabix index lands alongside the VCF — annotate_vcfanno needs it.
    tbi = tmp_path / "clinvar" / "2026-04" / "clinvar.vcf.gz.tbi"
    assert tbi.exists()
    assert tbi.read_bytes() == _TINY_TBI_BYTES


def test_fetch_rejects_checksum_mismatch_mocked(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Case 15: server returns content with a wrong checksum → fetch errors; no output written."""
    from genomeclaw_toolkit.prep.fetch import ChecksumMismatch, fetch

    base_url = _stage_clinvar_response(
        httpserver,
        md5_override="0" * 32,  # never the real hash
    )

    with pytest.raises(ChecksumMismatch):
        fetch(
            source="clinvar",
            reference_root=tmp_path,
            release="2026-04",
            base_url=base_url,
        )

    # No partial output left behind. The version directory may exist as a
    # scratch parent, but the canonical filename must not be present.
    canonical = tmp_path / "clinvar" / "2026-04" / "clinvar.vcf.gz"
    assert not canonical.exists()


def test_invD001_fetch_does_not_overwrite_existing_version(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Case 3 (INV-D001): a previously-fetched version is **not** overwritten by a re-run."""
    from genomeclaw_toolkit.prep.fetch import VersionAlreadyExists, fetch

    base_url = _stage_clinvar_response(httpserver)

    # Pre-populate the target dir with a previous fetch's content.
    prior = tmp_path / "clinvar" / "2026-04" / "clinvar.vcf.gz"
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b"PRIOR-FETCH-CONTENTS")
    prior_sha256 = hashlib.sha256(prior.read_bytes()).hexdigest()

    with pytest.raises(VersionAlreadyExists):
        fetch(
            source="clinvar",
            reference_root=tmp_path,
            release="2026-04",
            base_url=base_url,
        )

    # The previous version's bytes are unchanged.
    assert prior.exists()
    assert hashlib.sha256(prior.read_bytes()).hexdigest() == prior_sha256


def test_fetch_rejects_unknown_source(tmp_path: Path) -> None:
    """An unsupported source name fails fast, before any network call."""
    from genomeclaw_toolkit.prep.fetch import fetch

    with pytest.raises(ValueError, match="unknown source"):
        fetch(
            source="not-a-real-source",
            reference_root=tmp_path,
            release="2026-04",
            base_url="http://localhost:1",
        )


def test_fetch_requires_release(tmp_path: Path) -> None:
    """Phase 2 ships without a remote-resolved "latest" — release is mandatory."""
    from genomeclaw_toolkit.prep.fetch import fetch

    with pytest.raises(TypeError):
        # Missing release= keyword.
        fetch(  # type: ignore[call-arg]
            source="clinvar",
            reference_root=tmp_path,
            base_url="http://localhost:1",
        )

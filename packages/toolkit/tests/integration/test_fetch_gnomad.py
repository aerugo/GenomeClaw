"""Phase 4C.1 — ``genomeclaw refs fetch --source gnomad-exomes`` against a mocked HTTP backend.

gnomAD v4.1 exomes ships as 24 per-chromosome bgzipped sites VCFs (one
per chr1–22 + X + Y) at ~200 GB total, hosted at
``gs://gcp-public-data--gnomad/release/4.1/vcf/exomes/``. The fetcher
downloads each ``.vcf.bgz`` + its ``.tbi`` sidecar under
``reference/gnomad-exomes/<release>/by_chrom/``.

Differences from ClinVar / GRCh38:
- Multi-file source (24 .bgz + 24 .tbi = 48 files).
- No per-file MD5 sidecar (NCBI convention); GCS exposes md5 via the
  Object metadata JSON API, but for v0 the fetcher verifies via
  ``Content-Length`` size only. The pre-indexed ``.tbi`` lands alongside
  the ``.vcf.bgz`` so a corrupt download is caught structurally by
  ``bcftools view``'s tabix lookup at the next pipeline step.

For tests we redirect via ``base_url`` to a ``pytest-httpserver``
instance and use the ``chroms`` filter kwarg to stage only a subset
(per-chrom mocking 24 endpoints is verbose; 2 chroms prove the
URL pattern + path layout + size verification gates).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

# Tiny synthetic "bgz" payload — the fetcher never parses it. The size
# is the verification gate (bucket-reported Content-Length must match).
# Phase 3 also asserts the canonical BGZF EOF marker is present on
# every ``.vcf.bgz`` so the body includes it.
from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER  # noqa: E402

_TINY_BGZ_BYTES = b"\x1f\x8b" + b"x" * 100 + BGZF_EOF_MARKER  # plausibly bgz-shaped
_TINY_TBI_BYTES = b"TBI\x01" + b"y" * 50


def _stage_gnomad_chrom_response(
    httpserver: HTTPServer,
    chrom: str,
    *,
    bgz_bytes: bytes = _TINY_BGZ_BYTES,
    tbi_bytes: bytes = _TINY_TBI_BYTES,
) -> None:
    """Wire mocked GCS-style endpoints for one chrom: .vcf.bgz + .tbi."""
    bgz_relpath = f"/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr{chrom}.vcf.bgz"
    tbi_relpath = bgz_relpath + ".tbi"
    httpserver.expect_request(bgz_relpath).respond_with_data(
        bgz_bytes,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(bgz_bytes))},
    )
    httpserver.expect_request(tbi_relpath).respond_with_data(
        tbi_bytes,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(tbi_bytes))},
    )


def test_fetch_gnomad_exomes_writes_per_chrom_paths_mocked(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Case 7: fetch writes each .vcf.bgz + .tbi under the version's ``by_chrom/`` subdir."""
    from genomeclaw_toolkit.prep.fetch import fetch

    _stage_gnomad_chrom_response(httpserver, "22")
    _stage_gnomad_chrom_response(httpserver, "Y")
    base_url = httpserver.url_for("").rstrip("/")

    written = fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=base_url,
        chroms=("22", "Y"),
    )

    # Multi-file sources return the version directory, not a single file.
    expected_dir = tmp_path / "gnomad-exomes" / "v4.1"
    assert written == expected_dir
    assert expected_dir.is_dir()

    for chrom in ("22", "Y"):
        bgz = expected_dir / "by_chrom" / f"chr{chrom}.vcf.bgz"
        tbi = expected_dir / "by_chrom" / f"chr{chrom}.vcf.bgz.tbi"
        assert bgz.exists(), f"expected {bgz}"
        assert tbi.exists(), f"expected {tbi}"
        # Content matches the served bytes (size-verification gate).
        assert bgz.read_bytes() == _TINY_BGZ_BYTES
        assert tbi.read_bytes() == _TINY_TBI_BYTES


def test_invD001_fetch_gnomad_does_not_overwrite_existing_release(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """`INV-D001`: previously-fetched release dir is not overwritten by a re-run."""
    from genomeclaw_toolkit.prep.fetch import VersionAlreadyExists, fetch

    _stage_gnomad_chrom_response(httpserver, "22")
    base_url = httpserver.url_for("").rstrip("/")

    # Pre-populate the target dir with a previous fetch's content.
    prior_dir = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom"
    prior_dir.mkdir(parents=True)
    prior = prior_dir / "chr22.vcf.bgz"
    prior.write_bytes(b"PRIOR-FETCH-CONTENTS")
    prior_sha = hashlib.sha256(prior.read_bytes()).hexdigest()

    with pytest.raises(VersionAlreadyExists):
        fetch(
            source="gnomad-exomes",
            reference_root=tmp_path,
            release="v4.1",
            base_url=base_url,
            chroms=("22",),
        )

    # The previous version's bytes are unchanged.
    assert prior.exists()
    assert hashlib.sha256(prior.read_bytes()).hexdigest() == prior_sha


def test_fetch_gnomad_with_chroms_filter_downloads_only_requested(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """``chroms`` kwarg limits the fetch to the requested subset (test injection + opt-in
    partial-fetch). The mocked server is staged with chr22 only; passing
    ``chroms=("22",)`` succeeds; passing ``chroms=("22", "Y")`` would hit the
    un-staged Y endpoint and fail with a 500."""
    from genomeclaw_toolkit.prep.fetch import fetch

    _stage_gnomad_chrom_response(httpserver, "22")
    base_url = httpserver.url_for("").rstrip("/")

    fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=base_url,
        chroms=("22",),
    )

    expected_dir = tmp_path / "gnomad-exomes" / "v4.1"
    assert (expected_dir / "by_chrom" / "chr22.vcf.bgz").exists()
    # chrY was not requested → not downloaded → no file.
    assert not (expected_dir / "by_chrom" / "chrY.vcf.bgz").exists()

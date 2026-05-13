"""Phase 4D — ``genomeclaw refs fetch --source vep_cache`` against a mocked HTTP backend.

Real Ensembl VEP-cache downloads are ~21 GB tarballs; tests stand up
a tiny synthetic tarball + serve it via pytest-httpserver so the
fetch + extract round-trip is exercisable without real upstream
traffic. The cache layout uses ``{release_n}`` substitution in the
URL path; this also gets exercised here.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from pytest_httpserver import HTTPServer


def _build_synthetic_vep_cache_tarball() -> bytes:
    """Return a tiny in-memory .tar.gz mimicking Ensembl's VEP cache shape.

    The real cache contains ``homo_sapiens/<N>_GRCh38/*`` subdirs with
    indexed cache files. The synthetic version has the same outer
    layout but with one trivial placeholder file inside so the post-
    extract assertions can validate the tree structure landed.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # Add a marker file at homo_sapiens/114_GRCh38/info.txt — the
        # fetch's post-hook extracts the whole tree relative to its
        # output dir, so this should land at
        # <target>/homo_sapiens/114_GRCh38/info.txt.
        info_bytes = b"synthetic VEP cache fixture\n"
        member = tarfile.TarInfo(name="homo_sapiens/114_GRCh38/info.txt")
        member.size = len(info_bytes)
        tf.addfile(member, io.BytesIO(info_bytes))
    return buf.getvalue()


def test_fetch_vep_cache_writes_versioned_path_and_extracts_tarball(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Happy path: fetch downloads tarball, extracts, deletes the archive.

    Asserts:
      - URL templating substituted ``{release_n}`` → ``114`` correctly
        (the GET request hit ``/pub/release-114/.../homo_sapiens_vep_114_GRCh38.tar.gz``).
      - The target dir was created at ``reference/vep_cache/114/``.
      - The tarball was extracted in place (the synthetic marker file
        landed at the expected path).
      - The .tar.gz itself is removed post-extraction (the post-fetch
        hook reclaims ~21 GB of disk).
    """
    from genomeclaw_toolkit.prep.fetch import fetch

    tarball_bytes = _build_synthetic_vep_cache_tarball()
    httpserver.expect_request(
        "/pub/release-114/variation/indexed_vep_cache/homo_sapiens_vep_114_GRCh38.tar.gz"
    ).respond_with_data(tarball_bytes, content_type="application/gzip")
    base_url = httpserver.url_for("").rstrip("/")

    written = fetch(
        source="vep_cache",
        reference_root=tmp_path,
        release="114",
        base_url=base_url,
    )

    # ``fetch`` returns the canonical data-file path for single-file
    # sources; for vep_cache the canonical file is the tarball that
    # got extracted. The post-hook removes the tarball, so the file at
    # the returned path doesn't exist anymore — but the EXTRACTED
    # contents do.
    target_dir = tmp_path / "vep_cache" / "114"
    assert written == target_dir / "vep_cache.tar.gz"

    # Tarball was deleted by the post-hook.
    assert not (target_dir / "vep_cache.tar.gz").exists()

    # Extracted layout landed under the target dir.
    extracted_marker = target_dir / "homo_sapiens" / "114_GRCh38" / "info.txt"
    assert extracted_marker.exists()
    assert extracted_marker.read_bytes() == b"synthetic VEP cache fixture\n"


def test_fetch_vep_cache_release_substitution_threads_to_url(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """A different release tag substitutes through to the URL + target dir.

    Regression guard: ``{release_n}`` appears twice in the layout's
    URL (``release-{N}/.../homo_sapiens_vep_{N}_GRCh38.tar.gz``); both
    occurrences need to substitute identically. We use release ``"113"``
    here to verify the substitution isn't accidentally pinned to 114.
    """
    from genomeclaw_toolkit.prep.fetch import fetch

    tarball_bytes = _build_synthetic_vep_cache_tarball()
    httpserver.expect_request(
        "/pub/release-113/variation/indexed_vep_cache/homo_sapiens_vep_113_GRCh38.tar.gz"
    ).respond_with_data(tarball_bytes, content_type="application/gzip")

    written = fetch(
        source="vep_cache",
        reference_root=tmp_path,
        release="113",
        base_url=httpserver.url_for("").rstrip("/"),
    )

    target_dir = tmp_path / "vep_cache" / "113"
    assert written == target_dir / "vep_cache.tar.gz"
    assert (target_dir / "homo_sapiens" / "114_GRCh38" / "info.txt").exists()

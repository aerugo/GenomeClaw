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


def test_per_file_url_override_routes_to_alternate_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """In production (no ``base_url=`` injection), a file's ``url_override``
    determines the wire URL; sibling files in the same source still use
    the default ``base_url``.

    Regression coverage for the LOFTEE GERP routing: the BigWig lives
    on Ensembl FTP while the rest of LOFTEE's data stays on Broad's
    personal mirror. The fix splits the fetch traffic across two hosts
    inside one source.
    """
    from genomeclaw_toolkit.prep import fetch as fetch_mod
    from genomeclaw_toolkit.prep.fetch import _FetchFile, _SourceLayout, fetch

    base_calls: list[str] = []
    override_calls: list[str] = []

    def fake_stream(url: str, dest_path: Path, **_: object) -> tuple[str, int, int | None]:
        target = override_calls if "/override/" in url else base_calls
        target.append(url)
        dest_path.write_bytes(b"")
        return ("d41d8cd98f00b204e9800998ecf8427e", 0, 0)

    monkeypatch.setattr(fetch_mod, "_stream_to_file", fake_stream)
    monkeypatch.setitem(
        fetch_mod._LAYOUTS,
        "_synthetic_override",
        _SourceLayout(
            files=(
                _FetchFile(
                    relpath="/regular.bin",
                    output_filename="regular.bin",
                ),
                _FetchFile(
                    relpath="/unused.bin",
                    output_filename="overridden.bin",
                    url_override="https://override.example.com/override/data.bin",
                ),
            ),
        ),
    )
    monkeypatch.setitem(
        fetch_mod._DEFAULT_BASE_URLS,
        "_synthetic_override",
        "https://base.example.com",
    )

    fetch(
        source="_synthetic_override",
        reference_root=tmp_path,
        release="v1",
    )

    assert base_calls == ["https://base.example.com/regular.bin"]
    assert override_calls == ["https://override.example.com/override/data.bin"]


def test_per_file_url_override_suppressed_when_base_url_injected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When a caller passes ``base_url=`` (test injection), the per-file
    override is suppressed so the mocked HTTP server sees every request.
    Without this, integration tests would silently hit the real Ensembl
    host configured in a file's ``url_override``.
    """
    from genomeclaw_toolkit.prep import fetch as fetch_mod
    from genomeclaw_toolkit.prep.fetch import _FetchFile, _SourceLayout, fetch

    seen: list[str] = []

    def fake_stream(url: str, dest_path: Path, **_: object) -> tuple[str, int, int | None]:
        seen.append(url)
        dest_path.write_bytes(b"")
        return ("d41d8cd98f00b204e9800998ecf8427e", 0, 0)

    monkeypatch.setattr(fetch_mod, "_stream_to_file", fake_stream)
    monkeypatch.setitem(
        fetch_mod._LAYOUTS,
        "_synthetic_override",
        _SourceLayout(
            files=(
                _FetchFile(
                    relpath="/regular.bin",
                    output_filename="regular.bin",
                    url_override="https://elsewhere.example.com/should-not-be-hit",
                ),
            ),
        ),
    )

    fetch(
        source="_synthetic_override",
        reference_root=tmp_path,
        release="v1",
        base_url="https://test.local",
    )

    assert seen == ["https://test.local/regular.bin"]


def test_presence_marker_skips_refetch_when_canonical_deleted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A layout with ``presence_relpath`` skips re-fetch when the marker
    exists, even when the canonical output file has been deleted by a
    post-fetch hook.

    Regression coverage for the vep_cache case: the post-fetch hook
    extracts + deletes the 21 GB tarball. Before the marker was added,
    ``fetch --all`` saw no ``vep_cache.tar.gz`` and re-downloaded the
    whole source on every invocation.
    """
    from genomeclaw_toolkit.prep import fetch as fetch_mod
    from genomeclaw_toolkit.prep.fetch import (
        VersionAlreadyExists,
        _FetchFile,
        _SourceLayout,
        fetch,
    )

    monkeypatch.setitem(
        fetch_mod._LAYOUTS,
        "_synthetic_marker",
        _SourceLayout(
            files=(
                _FetchFile(
                    relpath="/cache_{release_n}.tar.gz",
                    output_filename="cache.tar.gz",
                ),
            ),
            presence_relpath="extracted/{release_n}/info.txt",
        ),
    )
    monkeypatch.setitem(
        fetch_mod._DEFAULT_BASE_URLS,
        "_synthetic_marker",
        "https://base.example.com",
    )

    # Stage the post-fetch state: canonical tarball absent, marker present.
    marker = tmp_path / "_synthetic_marker" / "v9" / "extracted" / "v9" / "info.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("vep release info\n")

    with pytest.raises(VersionAlreadyExists, match="post-fetch marker"):
        fetch(
            source="_synthetic_marker",
            reference_root=tmp_path,
            release="v9",
        )


def test_presence_marker_substitutes_release_placeholders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``presence_relpath`` honors ``{release_n}`` and ``{release}``
    substitution, matching the templating already used by ``relpath`` /
    ``output_filename`` / ``url_override``.

    Without this, the vep_cache marker (which embeds the Ensembl release
    in its on-disk path) would be statically wrong across releases.
    """
    from genomeclaw_toolkit.prep import fetch as fetch_mod
    from genomeclaw_toolkit.prep.fetch import (
        VersionAlreadyExists,
        _FetchFile,
        _SourceLayout,
        fetch,
    )

    monkeypatch.setitem(
        fetch_mod._LAYOUTS,
        "_synthetic_marker_tmpl",
        _SourceLayout(
            files=(
                _FetchFile(relpath="/x", output_filename="x.bin"),
            ),
            presence_relpath="release-{release_n}/marker",
        ),
    )
    monkeypatch.setitem(
        fetch_mod._DEFAULT_BASE_URLS,
        "_synthetic_marker_tmpl",
        "https://example.com",
    )

    marker = tmp_path / "_synthetic_marker_tmpl" / "42" / "release-42" / "marker"
    marker.parent.mkdir(parents=True)
    marker.touch()

    with pytest.raises(VersionAlreadyExists):
        fetch(
            source="_synthetic_marker_tmpl",
            reference_root=tmp_path,
            release="42",
        )


def test_vep_cache_layout_declares_presence_marker() -> None:
    """``vep_cache`` must declare a ``presence_relpath`` — its post-fetch
    hook intentionally deletes the canonical tarball, so the default
    existence check is structurally insufficient for this source.
    """
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    vep = _LAYOUTS["vep_cache"]
    assert vep.presence_relpath is not None
    assert "{release_n}" in vep.presence_relpath
    assert "homo_sapiens" in vep.presence_relpath


def test_loftee_layout_routes_gerp_to_ensembl() -> None:
    """The LOFTEE source's GERP BigWig must carry an Ensembl-FTP override.

    The four other files (human_ancestor trio + loftee.sql.gz) stay on
    the default Broad personal mirror — only the 12.6 GB BigWig is
    rerouted to bypass Broad's per-IP throttle.
    """
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    by_name = {f.output_filename: f for f in _LAYOUTS["loftee"].files}

    gerp = by_name["gerp_conservation_scores.homo_sapiens.GRCh38.bw"]
    assert gerp.url_override is not None
    assert gerp.url_override.startswith("https://ftp.ensembl.org/")
    assert "92_mammals.gerp_conservation_score" in gerp.url_override

    for name in (
        "human_ancestor.fa.gz",
        "human_ancestor.fa.gz.fai",
        "human_ancestor.fa.gz.gzi",
        "loftee.sql.gz",
    ):
        assert by_name[name].url_override is None, (
            f"{name} should fall through to Broad personal mirror"
        )

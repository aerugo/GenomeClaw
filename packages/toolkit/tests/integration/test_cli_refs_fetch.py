"""Phase 4 — ``refs fetch`` rich progress + NDJSON event stream.

These tests exercise the full event path: the underlying fetcher
emits ``ProgressEvent`` objects via the ``progress_callback`` hook
(plumbed in Phase 3); Phase 4's CLI layer translates them into either
a rich ``Progress`` panel (rich mode) or NDJSON lines on stdout (JSON
mode), with a first-line schema-version envelope.

All tests use :mod:`pytest_httpserver` so the suite never reaches
outside the runner.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer


# A synthetic "bgz" payload that ends with the canonical EOF marker so
# the post-fetch integrity check passes on the happy path.
_HAPPY_BGZ = b"\x1f\x8b\x08\x04" + b"x" * 64 + BGZF_EOF_MARKER
_HAPPY_BGZ_MD5 = hashlib.md5(_HAPPY_BGZ).hexdigest()
_HAPPY_VCF_BODY = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\n" + BGZF_EOF_MARKER
_HAPPY_VCF_MD5 = hashlib.md5(_HAPPY_VCF_BODY).hexdigest()


def _stage_clinvar(httpserver: HTTPServer) -> str:
    """Wire mock ClinVar endpoints; return the base URL."""
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz").respond_with_data(
        _HAPPY_VCF_BODY,
        content_type="application/gzip",
        headers={"Content-Length": str(len(_HAPPY_VCF_BODY))},
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.md5").respond_with_data(
        f"{_HAPPY_VCF_MD5}  clinvar.vcf.gz\n".encode(),
        content_type="text/plain",
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.tbi").respond_with_data(
        b"tbi-mock-bytes",
        content_type="application/octet-stream",
    )
    return httpserver.url_for("").rstrip("/")


def _stage_gnomad_chrom(httpserver: HTTPServer, chrom: str) -> None:
    """Wire mock gnomAD per-chrom endpoints."""
    bgz_relpath = f"/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr{chrom}.vcf.bgz"
    httpserver.expect_request(bgz_relpath).respond_with_data(
        _HAPPY_BGZ,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(_HAPPY_BGZ))},
    )
    httpserver.expect_request(bgz_relpath + ".tbi").respond_with_data(
        b"tbi-mock",
        content_type="application/octet-stream",
    )


# ---------------------------------------------------------------------------
# JSON-mode NDJSON event stream tests
# ---------------------------------------------------------------------------


def test_refs_fetch_json_emits_ndjson_event_stream(
    invoke_cli, httpserver: HTTPServer, tmp_path: Path
) -> None:
    """`--json refs fetch` emits an NDJSON stream: envelope line + event lines."""
    base_url = _stage_clinvar(httpserver)

    result = invoke_cli(
        [
            "--json",
            "refs",
            "fetch",
            "--source",
            "clinvar",
            "--release",
            "2026-05-12",
            "--reference-root",
            str(tmp_path),
            "--base-url",
            base_url,
        ]
    )
    assert result.exit_code == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) >= 2, "expected envelope + at least one event line"

    # First line: schema-version envelope.
    envelope = json.loads(lines[0])
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "refs.fetch"
    assert envelope.get("stream") is True

    # Subsequent lines: raw events.
    events = [json.loads(line) for line in lines[1:]]
    event_types = {e["event"] for e in events}
    assert "file_start" in event_types
    assert "file_complete" in event_types

    # Each event line must be valid JSON without embedded newlines.
    for line in lines[1:]:
        assert "\n" not in line


def test_refs_fetch_json_emits_file_failed_on_integrity_error(
    invoke_cli, httpserver: HTTPServer, tmp_path: Path
) -> None:
    """A failed fetch surfaces a ``file_failed`` event with the reason code."""
    # Synthetic body lacks the canonical EOF marker → IncompleteBgzip.
    truncated_body = b"\x1f\x8b\x08\x04" + b"x" * 64
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_data(
        truncated_body,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(truncated_body))},
    )
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", content_type="application/octet-stream")

    result = invoke_cli(
        [
            "--json",
            "refs",
            "fetch",
            "--source",
            "gnomad-exomes",
            "--release",
            "v4.1",
            "--chroms",
            "22",
            "--reference-root",
            str(tmp_path),
            "--base-url",
            httpserver.url_for("").rstrip("/"),
        ]
    )

    # Data-integrity exit (4) per the error-envelope contract.
    assert result.exit_code == 4, (
        f"expected exit 4, got {result.exit_code} (stderr: {result.stderr})"
    )

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines[1:]]
    failed = [e for e in events if e["event"] == "file_failed"]
    assert failed, f"expected at least one file_failed event; got {events!r}"
    assert failed[0]["reason"] == "incomplete_bgzip"


# ---------------------------------------------------------------------------
# Rich-mode tests
# ---------------------------------------------------------------------------


def test_refs_fetch_rich_renders_progress_for_each_file(
    invoke_cli, httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Rich mode renders per-file progress info to stderr."""
    base_url = _stage_clinvar(httpserver)

    result = invoke_cli(
        [
            "refs",
            "fetch",
            "--source",
            "clinvar",
            "--release",
            "2026-05-12",
            "--reference-root",
            str(tmp_path),
            "--base-url",
            base_url,
        ]
    )
    assert result.exit_code == 0, result.stderr

    # The renderer should surface each file name in the rich output. The
    # exact ANSI shape varies; we just assert the data files are referenced.
    assert "clinvar.vcf.gz" in result.stderr


def test_refs_fetch_all_renders_overall_progress(
    invoke_cli, httpserver: HTTPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--all` surfaces an overall counter spanning every fetched source."""
    # Stage a tiny synthetic release set with 2 sources so the overall
    # bar advances 1/2 → 2/2.
    from genomeclaw_toolkit.prep.release_sets import ReleaseSet, ReleaseSetEntry

    base_url = _stage_clinvar(httpserver)
    _stage_gnomad_chrom(httpserver, "22")

    rs = ReleaseSet(
        name="phase4-smoke",
        description="Synthetic 2-source set",
        sources=(
            ReleaseSetEntry(source="clinvar", release="2026-05-12", chroms=None),
            ReleaseSetEntry(source="gnomad-exomes", release="v4.1", chroms=("22",)),
        ),
    )
    monkeypatch.setattr(
        "genomeclaw_toolkit.prep.release_sets.load_release_set",
        lambda _name="default": rs,
    )

    result = invoke_cli(
        [
            "refs",
            "fetch",
            "--all",
            "--reference-root",
            str(tmp_path),
            "--base-url",
            base_url,
        ]
    )
    assert result.exit_code == 0, result.stderr

    # The overall bar should mention both sources by name.
    assert "clinvar" in result.stderr
    assert "gnomad-exomes" in result.stderr


# ---------------------------------------------------------------------------
# INV-P001: refs fetch only egresses to the configured mock URL
# ---------------------------------------------------------------------------


def test_invP001_refs_fetch_only_egresses_to_configured_url(
    invoke_cli, httpserver: HTTPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every HTTP call from `refs fetch` targets the mock URL, none elsewhere.

    Wraps ``urllib.request.urlopen`` to record every URL touched; the
    test asserts every URL is rooted at the mock server.
    """
    import urllib.request

    seen: list[str] = []
    original = urllib.request.urlopen

    def recording_urlopen(req, *args, **kwargs):  # type: ignore[no-untyped-def]
        url = req if isinstance(req, str) else req.full_url
        seen.append(url)
        return original(req, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", recording_urlopen)

    base_url = _stage_clinvar(httpserver)
    result = invoke_cli(
        [
            "refs",
            "fetch",
            "--source",
            "clinvar",
            "--release",
            "2026-05-12",
            "--reference-root",
            str(tmp_path),
            "--base-url",
            base_url,
        ]
    )
    assert result.exit_code == 0, result.stderr
    assert seen, "expected at least one HTTP call (test setup error?)"
    for url in seen:
        assert url.startswith(base_url), (
            f"INV-P001 violation: refs fetch egressed to {url!r} (not the configured mock {base_url!r})"
        )

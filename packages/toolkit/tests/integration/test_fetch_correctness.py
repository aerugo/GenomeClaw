"""Phase 3 — fetcher correctness tests.

The handlers below use ``direct_passthrough=True`` so werkzeug ships
the body bytes verbatim without recomputing ``Content-Length``. That's
exactly what we need to simulate a server that promises N bytes but
delivers M.



These are the tests that catch the bugs that motivated this phase:

* **Content-Length verification** post-download — a server that
  promises N bytes but closes the connection after M is the original
  silent-truncation bug behind the 5 unusable gnomAD chrom files.
* **Bgzip EOF marker check** — even when the byte count matches (some
  CDNs lie about ``Content-Length``), the canonical 28-byte BGZF EOF
  block is the definitive last-mile integrity check.
* **Resume on stall** via HTTP ``Range:`` requests with bounded
  retries, plus the **HTTP-200-on-Range fallback** for misbehaving
  servers that ignore the header.
* **MD5 preserved across resumes** — the incremental hash is re-seeded
  from the on-disk bytes when reconnecting; the final hash must match
  what a one-shot fetch would have produced.

All tests use :mod:`pytest_httpserver` so the suite never reaches
outside the runner.

`INV-D-fetch-integrity` (provisional, from the rich-cli plan's
absorbed 4C.4 work).
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer
    from werkzeug.wrappers import Request, Response


# A synthetic "bgz" payload that ends with the canonical EOF marker so
# the post-fetch EOF check passes on the happy path.
_BGZ_BODY = b"\x1f\x8b\x08\x04\x00\x00\x00\x00\x00\xffsome-bgzip-framing-payload-bytes"
_HAPPY_BGZ_BYTES = _BGZ_BODY + BGZF_EOF_MARKER
_HAPPY_BGZ_MD5 = hashlib.md5(_HAPPY_BGZ_BYTES).hexdigest()


# ---------------------------------------------------------------------------
# Content-Length verification
# ---------------------------------------------------------------------------


def _lying_response(body: bytes, claimed_length: int, *, status: int = 200) -> Response:
    """werkzeug Response that ships ``body`` while advertising ``claimed_length``.

    ``direct_passthrough=True`` bypasses werkzeug's auto-Content-Length
    recompute — without it, the server "helpfully" rewrites the header
    to match the actual body length, which defeats the whole truncation
    test.
    """
    from werkzeug.wrappers import Response

    return Response(
        response=[body],
        status=status,
        content_type="application/octet-stream",
        headers={"Content-Length": str(claimed_length)},
        direct_passthrough=True,
    )


def test_fetch_raises_truncated_download_when_content_length_mismatch(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Server promises 100 bytes but only ships 80 → ``TruncatedDownload``."""
    from genomeclaw_toolkit.prep.fetch import TruncatedDownload, fetch

    full = _HAPPY_BGZ_BYTES
    truncated = full[: len(full) - 28]  # also strips the EOF marker

    def _truncating(_request: Request) -> Response:
        return _lying_response(truncated, claimed_length=len(full))

    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_handler(_truncating)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi")

    with pytest.raises((TruncatedDownload, Exception)) as exc_info:
        fetch(
            source="gnomad-exomes",
            reference_root=tmp_path,
            release="v4.1",
            base_url=httpserver.url_for("").rstrip("/"),
            chroms=("22",),
            max_resume_attempts=1,  # don't waste time retrying a truncation
            retry_backoff_initial_sec=0.0,
        )
    # urllib may surface this as an IncompleteRead before we get to verify
    # Content-Length — either is acceptable for "short read" detection.
    from http.client import IncompleteRead

    from genomeclaw_toolkit.prep.fetch import DownloadStalled

    assert isinstance(exc_info.value, (TruncatedDownload, DownloadStalled, IncompleteRead))

    partial = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr22.vcf.bgz"
    assert not partial.exists(), "partial file must be cleaned up"


def test_fetch_succeeds_when_content_length_matches(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Happy path: server's ``Content-Length`` matches the byte count."""
    from genomeclaw_toolkit.prep.fetch import fetch

    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_data(
        _HAPPY_BGZ_BYTES,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(_HAPPY_BGZ_BYTES))},
    )
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", headers={"Content-Length": "3"})

    fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=httpserver.url_for("").rstrip("/"),
        chroms=("22",),
    )

    out = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr22.vcf.bgz"
    assert out.exists()
    assert out.read_bytes() == _HAPPY_BGZ_BYTES


# ---------------------------------------------------------------------------
# Bgzip EOF marker check
# ---------------------------------------------------------------------------


def test_fetch_raises_incomplete_bgzip_when_eof_marker_missing(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Bytes match ``Content-Length`` but the file lacks the EOF marker → ``IncompleteBgzip``."""
    from genomeclaw_toolkit.prep._bgzip import IncompleteBgzip
    from genomeclaw_toolkit.prep.fetch import fetch

    # Same byte count as a valid bgz, but no canonical EOF marker.
    body = b"\x1f\x8b\x08\x04" + b"x" * (len(_HAPPY_BGZ_BYTES) - 4)
    assert len(body) == len(_HAPPY_BGZ_BYTES)
    assert not body.endswith(BGZF_EOF_MARKER)

    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_data(
        body,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(body))},
    )
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", headers={"Content-Length": "3"})

    with pytest.raises(IncompleteBgzip):
        fetch(
            source="gnomad-exomes",
            reference_root=tmp_path,
            release="v4.1",
            base_url=httpserver.url_for("").rstrip("/"),
            chroms=("22",),
        )

    partial = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr22.vcf.bgz"
    assert not partial.exists(), "partial file must be cleaned up"


def test_fetch_skips_eof_check_for_non_bgzip_files(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Sidecars like ``.tbi`` / ``.md5`` are not bgzip; EOF check is skipped."""
    from genomeclaw_toolkit.prep.fetch import fetch

    # ``.tbi`` doesn't end with the BGZF EOF marker — it's a tabix index,
    # not bgzip. Without the suffix-filter, this would falsely raise.
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_data(
        _HAPPY_BGZ_BYTES,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(_HAPPY_BGZ_BYTES))},
    )
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(
        b"TBI-not-bgzip-bytes",
        headers={"Content-Length": "19"},
    )

    fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=httpserver.url_for("").rstrip("/"),
        chroms=("22",),
    )

    tbi = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr22.vcf.bgz.tbi"
    assert tbi.read_bytes() == b"TBI-not-bgzip-bytes"


# ---------------------------------------------------------------------------
# Resume on stall via Range header
# ---------------------------------------------------------------------------


class _StallingThenResumingHandler:
    """Stateful handler: serves first half of the body, hangs the connection,
    then on a ``Range:`` retry serves the rest as ``206 Partial Content``.
    """

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.attempts: list[tuple[str, int]] = []  # (range-header, bytes-served)
        self._lock = threading.Lock()
        self._first = True

    def __call__(self, request: Request) -> Response:
        from werkzeug.wrappers import Response

        with self._lock:
            range_header = request.headers.get("Range", "")
            if self._first:
                self._first = False
                half = len(self.body) // 2
                self.attempts.append((range_header, half))
                # Liar: ship half the bytes but advertise the full length.
                return Response(
                    response=[self.body[:half]],
                    status=200,
                    content_type="application/octet-stream",
                    headers={"Content-Length": str(len(self.body))},
                    direct_passthrough=True,
                )
            # Subsequent attempt — expect a Range header.
            assert range_header.startswith("bytes="), f"expected Range header, got {range_header!r}"
            offset_str = range_header[len("bytes=") :].split("-")[0]
            offset = int(offset_str)
            remaining = self.body[offset:]
            self.attempts.append((range_header, len(remaining)))
            return Response(
                response=[remaining],
                status=206,
                content_type="application/octet-stream",
                headers={
                    "Content-Length": str(len(remaining)),
                    "Content-Range": f"bytes {offset}-{len(self.body) - 1}/{len(self.body)}",
                },
                direct_passthrough=True,
            )


def test_fetch_resumes_via_range_header_after_stall(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Server closes mid-stream; fetcher reconnects with ``Range:`` + completes."""
    from genomeclaw_toolkit.prep.fetch import fetch

    handler = _StallingThenResumingHandler(_HAPPY_BGZ_BYTES)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_handler(handler)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", headers={"Content-Length": "3"})

    fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=httpserver.url_for("").rstrip("/"),
        chroms=("22",),
        retry_backoff_initial_sec=0.0,
    )

    out = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr22.vcf.bgz"
    assert out.read_bytes() == _HAPPY_BGZ_BYTES
    # First attempt had no Range; resume attempt did.
    assert len(handler.attempts) >= 2
    assert handler.attempts[0][0] == ""
    assert handler.attempts[1][0].startswith("bytes=")


def test_fetch_md5_preserved_across_resume(httpserver: HTTPServer, tmp_path: Path) -> None:
    """The fetcher's MD5 of the final file matches the one-shot MD5."""
    from genomeclaw_toolkit.prep.fetch import fetch

    body = b"\x1f\x8b\x08\x04" + b"\x00" * (1024 - 32) + BGZF_EOF_MARKER
    expected_md5 = hashlib.md5(body).hexdigest()
    handler = _StallingThenResumingHandler(body)
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz").respond_with_handler(
        handler
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.md5").respond_with_data(
        f"{expected_md5}  clinvar.vcf.gz\n".encode(),
        content_type="text/plain",
    )
    httpserver.expect_request("/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.tbi").respond_with_data(
        b"tbi", headers={"Content-Length": "3"}
    )

    written = fetch(
        source="clinvar",
        reference_root=tmp_path,
        release="2026-05-12",
        base_url=httpserver.url_for("").rstrip("/"),
        retry_backoff_initial_sec=0.0,
    )

    assert written.read_bytes() == body
    on_disk_md5_path = tmp_path / "clinvar" / "2026-05-12" / "clinvar.vcf.gz.md5"
    on_disk_md5 = on_disk_md5_path.read_text().split()[0]
    assert on_disk_md5 == expected_md5


def test_fetch_falls_back_to_full_restart_when_server_ignores_range(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Server returns 200 + full body on ``Range:`` request; fetcher restarts from byte 0."""
    from genomeclaw_toolkit.prep.fetch import fetch

    class _IgnoresRangeHandler:
        def __init__(self, body: bytes) -> None:
            self.body = body
            self.attempts: list[str] = []
            self._first = True
            self._lock = threading.Lock()

        def __call__(self, request: Request) -> Response:
            from werkzeug.wrappers import Response

            with self._lock:
                self.attempts.append(request.headers.get("Range", ""))
                if self._first:
                    self._first = False
                    # Serve only half, claim full length, then stop.
                    half = len(self.body) // 2
                    return Response(
                        response=[self.body[:half]],
                        status=200,
                        content_type="application/octet-stream",
                        headers={"Content-Length": str(len(self.body))},
                        direct_passthrough=True,
                    )
                # On retry: ignore Range — return 200 + full body.
                return Response(
                    response=[self.body],
                    status=200,
                    content_type="application/octet-stream",
                    headers={"Content-Length": str(len(self.body))},
                    direct_passthrough=True,
                )

    handler = _IgnoresRangeHandler(_HAPPY_BGZ_BYTES)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_handler(handler)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", headers={"Content-Length": "3"})

    fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=httpserver.url_for("").rstrip("/"),
        chroms=("22",),
        retry_backoff_initial_sec=0.0,
    )

    out = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr22.vcf.bgz"
    assert out.read_bytes() == _HAPPY_BGZ_BYTES


def test_fetch_raises_download_stalled_after_max_retries(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Always-truncating server → ``DownloadStalled`` after the retry budget."""
    from genomeclaw_toolkit.prep.fetch import DownloadStalled, fetch

    class _AlwaysShortHandler:
        def __init__(self, body: bytes) -> None:
            self.body = body
            self.calls = 0
            self._lock = threading.Lock()

        def __call__(self, request: Request) -> Response:
            from werkzeug.wrappers import Response

            with self._lock:
                self.calls += 1
            # Always serve only the first chunk.
            chunk = self.body[:32]
            return Response(
                response=[chunk],
                status=200,
                content_type="application/octet-stream",
                headers={"Content-Length": str(len(self.body))},
                direct_passthrough=True,
            )

    handler = _AlwaysShortHandler(_HAPPY_BGZ_BYTES)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_handler(handler)
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", headers={"Content-Length": "3"})

    with pytest.raises(DownloadStalled):
        fetch(
            source="gnomad-exomes",
            reference_root=tmp_path,
            release="v4.1",
            base_url=httpserver.url_for("").rstrip("/"),
            chroms=("22",),
            max_resume_attempts=3,
            retry_backoff_initial_sec=0.0,
        )

    # Original attempt + 3 retries = 4 calls.
    assert handler.calls == 4


# ---------------------------------------------------------------------------
# progress_callback hook
# ---------------------------------------------------------------------------


def test_fetch_invokes_progress_callback_with_file_events(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """The fetcher's optional callback receives FileStart + FileComplete events."""
    from genomeclaw_toolkit.prep._events import FileComplete, FileStart
    from genomeclaw_toolkit.prep.fetch import fetch

    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz"
    ).respond_with_data(
        _HAPPY_BGZ_BYTES,
        content_type="application/octet-stream",
        headers={"Content-Length": str(len(_HAPPY_BGZ_BYTES))},
    )
    httpserver.expect_request(
        "/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz.tbi"
    ).respond_with_data(b"tbi", headers={"Content-Length": "3"})

    events: list[object] = []
    fetch(
        source="gnomad-exomes",
        reference_root=tmp_path,
        release="v4.1",
        base_url=httpserver.url_for("").rstrip("/"),
        chroms=("22",),
        progress_callback=events.append,
    )

    # Each of the 2 files (bgz + tbi) should fire start + complete.
    starts = [e for e in events if isinstance(e, FileStart)]
    completes = [e for e in events if isinstance(e, FileComplete)]
    assert len(starts) == 2
    assert len(completes) == 2
    # FileComplete carries the final byte count + sha (here md5).
    for c in completes:
        assert c.bytes_written > 0
        assert c.duration_sec >= 0.0

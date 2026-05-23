"""Phase 2 — worker-self-sufficient-compute: inline auto-fetch scorefile tests.

When ``_real_compute_fn`` encounters a missing scorefile, ``_ensure_scorefile_staged``
auto-fetches it from PGS Catalog (subject to the kill-switch). This file covers:

1. Cache hit — no HTTP request fired.
2. Cache miss, happy path — fetch fires + file lands at canonical layout.
3. Cache miss + kill-switch off — ``PgsScorefileMissingError`` propagates, no HTTP.
4. Cache miss + 404 from PGS Catalog — ``PgsScorefileUnfetchableError(pgs_id, "404")``.
5. Cache miss + transient 5xx, succeeds on 3rd attempt — 3 requests to server.
6. Cache miss + persistent 5xx, all retries exhausted — ``PgsScorefileUnfetchableError(pgs_id, "server_unreachable")``.
7. INV-P001: kill-switch off propagates ``PgsScorefileMissingError`` without touching network.
8. Log lines on fetch — INFO records ``transition=auto_fetch_scorefile_started`` + ``transition=auto_fetch_scorefile_done``.

Uses ``pytest_httpserver`` for fake PGS Catalog endpoints and patches
``time.sleep`` in ``genomeclaw_toolkit.prep.fetch`` to avoid ~21 s real waits
on retry tests.

Plan: docs/plans/active/worker-self-sufficient-compute/phases/phase-2.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_httpserver import HTTPServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PGS_ID = "PGS000999"
_SCOREFILE_RELPATH = (
    f"/pub/databases/spot/pgs/scores/{_PGS_ID}/"
    f"ScoringFiles/Harmonized/{_PGS_ID}_hmPOS_GRCh38.txt.gz"
)
_SYNTHETIC_PAYLOAD = (
    b"###PGS CATALOG SCORING FILE\n"
    b"#format_version=2.0\n"
    b"#pgs_id=PGS000999\n"
    b"hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
    b"1\t100\tA\tG\t0.5\n"
)


def _canonical_path(scorefile_root: Path) -> Path:
    return scorefile_root / _PGS_ID / f"{_PGS_ID}_hmPOS_GRCh38.txt.gz"


def _run_async(coro):
    """Run a coroutine synchronously for the test body."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Test 1 — cache hit: no fetch attempted
# ---------------------------------------------------------------------------


def test_cache_hit_no_fetch_attempted(tmp_path: Path, httpserver: HTTPServer) -> None:
    """Scorefile already at canonical layout → ``_ensure_scorefile_staged`` returns
    without firing any HTTP request.

    The httpserver is bound but has no handlers registered — any request
    would cause ``pytest_httpserver`` to raise an unexpected-request error.
    """
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _ensure_scorefile_staged

    scorefile_root = tmp_path / "scorefiles"
    target = _canonical_path(scorefile_root)
    target.parent.mkdir(parents=True)
    target.write_bytes(_SYNTHETIC_PAYLOAD)

    result = _run_async(
        _ensure_scorefile_staged(
            scorefile_root,
            _PGS_ID,
            compute_enabled_fn=lambda: True,
        )
    )

    assert result == target
    # No requests should have been made — httpserver's default behavior
    # raises if any unexpected requests arrive.
    assert httpserver.log == []


# ---------------------------------------------------------------------------
# Test 2 — cache miss, happy path: fetch fires + file lands
# ---------------------------------------------------------------------------


def test_cache_miss_happy_path_fetches_and_caches(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    """Cache miss → fetch fires → file lands at canonical layout → path returned."""
    from genomeclaw_toolkit.prep.fetch import fetch_pgs_scorefile
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _ensure_scorefile_staged

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    httpserver.expect_request(_SCOREFILE_RELPATH).respond_with_data(
        _SYNTHETIC_PAYLOAD,
        content_type="application/gzip",
    )
    base_url = httpserver.url_for("").rstrip("/")

    # Patch fetch_pgs_scorefile to use the test httpserver.
    with patch(
        "genomeclaw_toolkit.service.pgs_compute_orchestrator.fetch_pgs_scorefile",
        side_effect=lambda pgs_id, root: fetch_pgs_scorefile(
            pgs_id, root, base_url=base_url
        ),
    ):
        result = _run_async(
            _ensure_scorefile_staged(
                scorefile_root,
                _PGS_ID,
                compute_enabled_fn=lambda: True,
            )
        )

    canonical = _canonical_path(scorefile_root)
    assert result == canonical
    assert canonical.exists()
    assert canonical.read_bytes() == _SYNTHETIC_PAYLOAD


# ---------------------------------------------------------------------------
# Test 3 — cache miss + kill-switch off: PgsScorefileMissingError propagates
# ---------------------------------------------------------------------------


def test_cache_miss_kill_switch_off_propagates_missing_error(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    """Scorefile absent + kill-switch off → ``PgsScorefileMissingError`` propagates;
    no HTTP request fired (INV-P001 — no PGS Catalog egress under kill-switch).
    """
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
        PgsScorefileMissingError,
        _ensure_scorefile_staged,
    )

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    with pytest.raises(PgsScorefileMissingError) as exc_info:
        _run_async(
            _ensure_scorefile_staged(
                scorefile_root,
                _PGS_ID,
                compute_enabled_fn=lambda: False,  # kill-switch off
            )
        )

    assert exc_info.value.pgs_id == _PGS_ID
    # No requests should have reached the server.
    assert httpserver.log == []


# ---------------------------------------------------------------------------
# Test 4 — cache miss + PGS Catalog 404: PgsScorefileUnfetchableError("404")
# ---------------------------------------------------------------------------


def test_cache_miss_pgs_catalog_404_maps_to_unfetchable(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    """PGS Catalog returns 404 → ``PgsScorefileUnfetchableError(pgs_id, "404")``."""
    from genomeclaw_toolkit.prep.fetch import PgsScorefileUnfetchableError, fetch_pgs_scorefile
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _ensure_scorefile_staged

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    httpserver.expect_request(_SCOREFILE_RELPATH).respond_with_data(
        "not found",
        status=404,
    )
    base_url = httpserver.url_for("").rstrip("/")

    with patch(
        "genomeclaw_toolkit.service.pgs_compute_orchestrator.fetch_pgs_scorefile",
        side_effect=lambda pgs_id, root: fetch_pgs_scorefile(
            pgs_id, root, base_url=base_url
        ),
    ):
        with pytest.raises(PgsScorefileUnfetchableError) as exc_info:
            _run_async(
                _ensure_scorefile_staged(
                    scorefile_root,
                    _PGS_ID,
                    compute_enabled_fn=lambda: True,
                )
            )

    assert exc_info.value.pgs_id == _PGS_ID
    assert exc_info.value.reason == "404"


# ---------------------------------------------------------------------------
# Test 5 — transient 5xx: retries then succeeds
# ---------------------------------------------------------------------------


def test_cache_miss_transient_5xx_retries_then_succeeds(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    """Fake server returns 503 twice, 200 on 3rd attempt.

    Verifies: 3 requests were served; ``time.sleep`` called twice (backoff
    between attempts 1→2 and 2→3); file lands at canonical layout.
    """
    from genomeclaw_toolkit.prep.fetch import fetch_pgs_scorefile
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _ensure_scorefile_staged

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    call_count = {"n": 0}

    def _handler(request):
        from werkzeug.wrappers import Response

        call_count["n"] += 1
        if call_count["n"] < 3:
            return Response("server error", status=503)
        return Response(
            _SYNTHETIC_PAYLOAD,
            status=200,
            content_type="application/gzip",
        )

    httpserver.expect_request(_SCOREFILE_RELPATH).respond_with_handler(_handler)
    base_url = httpserver.url_for("").rstrip("/")

    sleep_calls: list[float] = []

    def fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    with patch("genomeclaw_toolkit.prep.fetch.time.sleep", fake_sleep):
        with patch(
            "genomeclaw_toolkit.service.pgs_compute_orchestrator.fetch_pgs_scorefile",
            side_effect=lambda pgs_id, root: fetch_pgs_scorefile(
                pgs_id, root, base_url=base_url
            ),
        ):
            result = _run_async(
                _ensure_scorefile_staged(
                    scorefile_root,
                    _PGS_ID,
                    compute_enabled_fn=lambda: True,
                )
            )

    assert call_count["n"] == 3
    # Two sleeps between 3 attempts: 4^0=1s, 4^1=4s.
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(1.0)
    assert sleep_calls[1] == pytest.approx(4.0)
    assert result == _canonical_path(scorefile_root)
    assert result.read_bytes() == _SYNTHETIC_PAYLOAD


# ---------------------------------------------------------------------------
# Test 6 — persistent 5xx: all retries exhausted → server_unreachable
# ---------------------------------------------------------------------------


def test_cache_miss_persistent_5xx_exhausts_retries(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    """Fake server always returns 503 → all 3 attempts fail →
    ``PgsScorefileUnfetchableError(pgs_id, "server_unreachable")``.
    """
    from genomeclaw_toolkit.prep.fetch import PgsScorefileUnfetchableError, fetch_pgs_scorefile
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _ensure_scorefile_staged

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    call_count = {"n": 0}

    def _handler(request):
        from werkzeug.wrappers import Response

        call_count["n"] += 1
        return Response("server error", status=503)

    httpserver.expect_request(_SCOREFILE_RELPATH).respond_with_handler(_handler)
    base_url = httpserver.url_for("").rstrip("/")

    sleep_calls: list[float] = []

    def fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    with patch("genomeclaw_toolkit.prep.fetch.time.sleep", fake_sleep):
        with patch(
            "genomeclaw_toolkit.service.pgs_compute_orchestrator.fetch_pgs_scorefile",
            side_effect=lambda pgs_id, root: fetch_pgs_scorefile(
                pgs_id, root, base_url=base_url
            ),
        ):
            with pytest.raises(PgsScorefileUnfetchableError) as exc_info:
                _run_async(
                    _ensure_scorefile_staged(
                        scorefile_root,
                        _PGS_ID,
                        compute_enabled_fn=lambda: True,
                    )
                )

    assert exc_info.value.pgs_id == _PGS_ID
    assert exc_info.value.reason == "server_unreachable"
    # All 3 attempts exhausted.
    assert call_count["n"] == 3
    # Two sleeps: 1 s and 4 s (between attempt 1→2 and 2→3).
    assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# Test 7 — INV-P001: no egress under kill-switch
# ---------------------------------------------------------------------------


def test_invP001_no_egress_under_kill_switch(tmp_path: Path) -> None:
    """INV-P001: when the kill-switch is off, ``_ensure_scorefile_staged`` must
    raise ``PgsScorefileMissingError`` without touching the network.

    This test patches ``_http_get`` to fail immediately on any call,
    confirming the kill-switch gates the fetch before any network contact.
    """
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
        PgsScorefileMissingError,
        _ensure_scorefile_staged,
    )

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    network_contact_attempts = []

    def _fail_on_http(url: str) -> bytes:
        network_contact_attempts.append(url)
        raise AssertionError(f"INV-P001 violation: HTTP request fired under kill-switch: {url}")

    with patch("genomeclaw_toolkit.prep.fetch._http_get", _fail_on_http):
        with pytest.raises(PgsScorefileMissingError):
            _run_async(
                _ensure_scorefile_staged(
                    scorefile_root,
                    _PGS_ID,
                    compute_enabled_fn=lambda: False,  # kill-switch off
                )
            )

    assert network_contact_attempts == [], (
        "INV-P001: HTTP contact occurred under kill-switch"
    )


# ---------------------------------------------------------------------------
# Test 8 — log lines on fetch
# ---------------------------------------------------------------------------


def test_log_lines_on_fetch(
    tmp_path: Path, httpserver: HTTPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """On a successful fetch, INFO logs carry structured ``transition`` fields.

    Asserts:
    - ``transition=auto_fetch_scorefile_started`` with ``pgs_id=<PGS_ID>``.
    - ``transition=auto_fetch_scorefile_done`` with ``pgs_id=<PGS_ID>``
      and ``bytes=<positive int>``.
    """
    import logging

    from genomeclaw_toolkit.prep.fetch import fetch_pgs_scorefile
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _ensure_scorefile_staged

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()

    httpserver.expect_request(_SCOREFILE_RELPATH).respond_with_data(
        _SYNTHETIC_PAYLOAD,
        content_type="application/gzip",
    )
    base_url = httpserver.url_for("").rstrip("/")

    with caplog.at_level(logging.INFO, logger="genomeclaw_toolkit.service.pgs_compute_orchestrator"):
        with patch(
            "genomeclaw_toolkit.service.pgs_compute_orchestrator.fetch_pgs_scorefile",
            side_effect=lambda pgs_id, root: fetch_pgs_scorefile(
                pgs_id, root, base_url=base_url
            ),
        ):
            _run_async(
                _ensure_scorefile_staged(
                    scorefile_root,
                    _PGS_ID,
                    compute_enabled_fn=lambda: True,
                )
            )

    # Python's logging module merges ``extra=`` kwargs directly into the
    # LogRecord as top-level attributes (not a sub-dict). Collect by the
    # ``transition`` attribute.
    transitions = {
        getattr(r, "transition", None): r
        for r in caplog.records
        if getattr(r, "pgs_id", None) == _PGS_ID
    }

    assert "auto_fetch_scorefile_started" in transitions, (
        f"Expected 'auto_fetch_scorefile_started' transition in log; got: {list(transitions)}"
    )
    assert "auto_fetch_scorefile_done" in transitions, (
        f"Expected 'auto_fetch_scorefile_done' transition in log; got: {list(transitions)}"
    )

    done_record = transitions["auto_fetch_scorefile_done"]
    assert getattr(done_record, "bytes", 0) > 0, (
        f"Expected positive bytes attribute in done log record; got: {vars(done_record)}"
    )

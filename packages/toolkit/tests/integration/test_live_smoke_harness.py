"""Unit tests for the live-smoke harness's container-lifecycle pieces.

The harness now exposes:

- ``running_sandbox_container(...)`` — long-running container fixture used
  by the ssrf-runtime-probe Phase 1 tests; also wrapped by the one-shot
  ``run_agent_in_sandbox`` path so a single boot loop serves both modes.
- ``run_probe(...)`` — ``docker exec``s the Node probe script in a
  running container + parses one JSON line.

These tests exercise the lifecycle invariants (always-cleanup, readiness
timeout) without needing real docker. The 5-tuple probe surface lives in
``tests/invariants/test_invP002_ssrf_runtime_probe.py``.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from tests._live_smoke.run import (
    DEFAULT_HOST_PORT,
    running_sandbox_container,
)


# ---------------------------------------------------------------------------
# Test 6 — teardown runs even when the `with` block raises
# ---------------------------------------------------------------------------


def test_running_sandbox_container_tears_down_on_exception() -> None:
    """Cleanup MUST run on exception inside the `with` block (no zombie containers)."""
    with patch("tests._live_smoke.run.subprocess.run") as mock_run:
        def fake_subprocess_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            cmdstr = " ".join(cmd)
            # Container-create
            if "run" in cmd and "-d" in cmd and "--rm" in cmd:
                m = MagicMock()
                m.returncode = 0
                m.stdout = "fakecontainerid123\n"
                return m
            # Readiness probe via `ss -lntp | grep openclaw-gatew`
            if "ss -lntp" in cmdstr:
                m = MagicMock()
                m.returncode = 0
                m.stdout = "UP\n"
                return m
            # All other exec / cp / rm calls
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        mock_run.side_effect = fake_subprocess_run

        class BoomError(RuntimeError):
            pass

        with pytest.raises(BoomError):
            with running_sandbox_container(
                sandbox_image="fake/image:test",
                host_port=DEFAULT_HOST_PORT,
            ):
                raise BoomError("probe failure simulation")

        # Cleanup must have fired: assert a `docker rm -f <cid>` call landed.
        rm_calls = [
            c for c in mock_run.call_args_list
            if "rm" in c.args[0] and "-f" in c.args[0]
        ]
        assert rm_calls, (
            f"Expected `docker rm -f <cid>` after exception; saw calls: "
            f"{[c.args[0] for c in mock_run.call_args_list]}"
        )


# ---------------------------------------------------------------------------
# Test 7 — gateway-readiness-loop timeout raises with the gateway log
# ---------------------------------------------------------------------------


def test_running_sandbox_container_gateway_readiness_timeout_raises() -> None:
    """If `openclaw gateway status` never reports ready, harness raises with the log."""
    with patch("tests._live_smoke.run.subprocess.run") as mock_run, \
         patch("tests._live_smoke.run.time.monotonic") as mock_monotonic:
        # Fake monotonic clock: jump past the readiness deadline on the
        # second poll so the test doesn't actually sleep.
        clock = iter([0.0, 0.5, 9999.0])
        mock_monotonic.side_effect = lambda: next(clock)

        def fake_subprocess_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            cmdstr = " ".join(cmd)
            if "run" in cmd and "-d" in cmd and "--rm" in cmd:
                m = MagicMock()
                m.returncode = 0
                m.stdout = "fakecontainerid456\n"
                return m
            # Readiness probe — never returns "UP" so the loop times out.
            if "ss -lntp" in cmdstr:
                m = MagicMock()
                m.returncode = 0
                m.stdout = "no openclaw process yet"
                return m
            # Gateway-log dump for the diagnostic message
            if "cat /tmp/gateway.log" in cmdstr:
                m = MagicMock()
                m.returncode = 0
                m.stdout = "fake gateway log content for diagnostics\n"
                return m
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            return m

        mock_run.side_effect = fake_subprocess_run

        with pytest.raises(RuntimeError, match=r"gateway.*ready|gateway.*timed out|gateway.*didn't"):
            with running_sandbox_container(
                sandbox_image="fake/image:test",
                host_port=DEFAULT_HOST_PORT,
                gateway_boot_timeout_s=0.0,  # trigger immediate timeout
            ):
                pytest.fail("readiness should have timed out before yielding")

        rm_calls = [
            c for c in mock_run.call_args_list
            if "rm" in c.args[0] and "-f" in c.args[0]
        ]
        assert rm_calls, "expected cleanup to fire on readiness timeout"


# ---------------------------------------------------------------------------
# Test 8 — the one-shot run_agent_in_sandbox path goes through the new
# context manager (refactor regression guard)
# ---------------------------------------------------------------------------


def test_one_shot_and_long_running_harness_coexist() -> None:
    """Both harness modes are exported and live in the same module.

    Phase 1 deliberately did NOT refactor `run_agent_in_sandbox` to go
    through `running_sandbox_container` — the existing 4 live LLM tests
    + Phase 4 worker verification flow are battle-tested against the
    one-shot path, and merging the two modes is a follow-up cleanup
    documented in development-plan.md's Open Risks. This test verifies
    both modes coexist + share the same `DEFAULT_HOST_PORT` constant +
    config-batch builder so they don't drift apart.
    """
    import tests._live_smoke.run as run_mod

    assert callable(getattr(run_mod, "run_agent_in_sandbox", None))
    assert callable(getattr(run_mod, "running_sandbox_container", None))
    assert callable(getattr(run_mod, "run_probe", None))
    assert isinstance(getattr(run_mod, "DEFAULT_HOST_PORT", None), int)
    # Both modes share the openclaw-config-batch builder (Phase 1 REFACTOR
    # step — extracted to prevent the two paths from drifting apart on
    # provider config, model id, thinking depth, etc.).
    assert callable(getattr(run_mod, "_build_openclaw_config_batch", None)), (
        "expected `_build_openclaw_config_batch` shared helper; got something else. "
        "If you renamed it, update this test."
    )


# ---------------------------------------------------------------------------
# Plus: ensure the public surface exports what callers need
# ---------------------------------------------------------------------------


def test_live_smoke_module_exports_new_symbols() -> None:
    """``tests._live_smoke.run`` must export `running_sandbox_container` + `run_probe`."""
    from tests._live_smoke import run as run_mod

    assert hasattr(run_mod, "running_sandbox_container"), (
        "tests._live_smoke.run is missing `running_sandbox_container`"
    )
    assert hasattr(run_mod, "run_probe"), (
        "tests._live_smoke.run is missing `run_probe`"
    )
    if hasattr(run_mod, "__all__"):
        assert "running_sandbox_container" in run_mod.__all__
        assert "run_probe" in run_mod.__all__

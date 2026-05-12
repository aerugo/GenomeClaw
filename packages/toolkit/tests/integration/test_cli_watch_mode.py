"""Phase 2 — ``--watch`` mode tests.

The ``--watch`` flag wraps a command's read-only payload-build path
in rich's ``Live`` driver. We don't drive a real terminal here —
instead we patch :func:`genomeclaw_toolkit._cli.watch.watch_loop` to
record the calls + raise after one iteration, which is enough to
verify the wiring without depending on terminal timing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def _capture_watch_loop(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace ``watch_loop`` with a recorder that runs the renderer once + returns."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd
    import genomeclaw_toolkit._cli.commands.runs as runs_cmd

    call_log: list[int] = []

    def fake_watch_loop(render, **_kwargs):
        # Invoke the renderer once so its construction path runs (any
        # exception in the renderable build surfaces immediately).
        renderable = render()
        call_log.append(1 if renderable is not None else 0)

    monkeypatch.setattr(host_cmd, "watch_loop", fake_watch_loop, raising=False)
    monkeypatch.setattr(runs_cmd, "watch_loop", fake_watch_loop, raising=False)
    return call_log


def _stage_run(derived: Path, run_id: str) -> Path:
    """Create a minimal valid derived-run dir."""
    run = derived / run_id
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "sample_id": "s", "created_at": "2026-05-12T00:00:00Z"})
    )
    return run


def test_runs_list_watch_invokes_watch_loop(
    invoke_cli, tmp_path: Path, _capture_watch_loop: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`runs list --watch` routes through the ``watch_loop`` driver."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "live-run")

    # Patch at the import site since runs.py imports lazily.

    def fake_watch_loop(render, **_kw):
        renderable = render()
        _capture_watch_loop.append(1 if renderable is not None else 0)

    monkeypatch.setattr("genomeclaw_toolkit._cli.watch.watch_loop", fake_watch_loop, raising=True)

    result = invoke_cli(["runs", "list", "--watch", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    assert _capture_watch_loop == [1]


def test_runs_list_watch_suppressed_under_json(
    invoke_cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--watch` is ignored in ``--json`` mode (single envelope emitted instead)."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "lr")

    watch_called: list[bool] = []
    monkeypatch.setattr(
        "genomeclaw_toolkit._cli.watch.watch_loop",
        lambda *_a, **_kw: watch_called.append(True),
    )

    result = invoke_cli(["--json", "runs", "list", "--watch", "--derived-root", str(derived)])
    assert result.exit_code == 0
    assert watch_called == []  # JSON mode bypasses watch
    payload = json.loads(result.stdout)
    assert payload["command"] == "runs.list"
    assert len(payload["payload"]["runs"]) == 1


def test_host_doctor_watch_invokes_watch_loop(invoke_cli, monkeypatch: pytest.MonkeyPatch) -> None:
    """`host doctor --watch` routes through ``watch_loop`` (rich mode)."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    # Provide a clean doctor report.
    def fake_doctor() -> tuple[int, dict[str, object]]:
        return (
            0,
            {
                "checks": [],
                "setup_log": {"found": False},
                "colima": {"installed": False},
                "paths": {},
                "references": {"release_set": None, "sources": []},
                "raw_sample": {"staged": False},
                "derived_runs": [],
            },
        )

    monkeypatch.setattr(host_cmd, "doctor_impl", fake_doctor)

    call_count: list[int] = []

    def fake_watch_loop(render, **_kw):
        renderable = render()
        call_count.append(1 if renderable is not None else 0)

    monkeypatch.setattr("genomeclaw_toolkit._cli.watch.watch_loop", fake_watch_loop, raising=True)

    result = invoke_cli(["host", "doctor", "--watch"])
    assert result.exit_code == 0, result.stderr
    assert call_count == [1]


def test_watch_loop_max_iterations_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``watch_loop`` helper exits cleanly after ``max_iterations``."""
    from rich.text import Text

    from genomeclaw_toolkit._cli.watch import watch_loop

    monkeypatch.setattr("time.sleep", lambda _t: None)
    calls: list[int] = []

    def render() -> Text:
        calls.append(1)
        return Text("frame")

    watch_loop(render, refresh_interval_sec=0.0, max_iterations=2)
    # First call inside Live's enter; ≥2 calls during the loop iterations.
    assert len(calls) >= 2

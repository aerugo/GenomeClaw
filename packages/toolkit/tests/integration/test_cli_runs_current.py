"""Phase 2 — ``runs current`` command tests."""

from __future__ import annotations

import json
from pathlib import Path


def _stage_run_and_current(derived: Path, run_id: str, *, with_provenance: bool = True) -> Path:
    """Create a run dir + point CURRENT at it. Returns the run path."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    run = derived / run_id
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "sample_id": "TestSample",
                "schema_version": "v0.2",
                "created_at": "2026-05-12T00:00:00Z",
            }
        )
    )
    if with_provenance:
        (run / "provenance.json").write_text(
            json.dumps({"steps": [{"step": "ingest"}, {"step": "normalize"}]})
        )
    update_current_symlink(derived, run_id)
    return run


def test_runs_current_resolves_symlink_and_returns_detail(invoke_cli, tmp_path: Path) -> None:
    """`runs current` resolves CURRENT and emits the same payload as ``runs show``."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run_and_current(derived, "live-run")

    result = invoke_cli(["--json", "runs", "current", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "runs.current"
    assert payload["payload"]["detail"]["run_id"] == "live-run"
    assert payload["payload"]["detail"]["stage"] == "normalized"


def test_runs_current_refuses_when_no_symlink_exists(invoke_cli, tmp_path: Path) -> None:
    """No CURRENT → exit 3 (precondition) with a clear hint."""
    derived = tmp_path / "derived"
    derived.mkdir()

    result = invoke_cli(["runs", "current", "--derived-root", str(derived)])
    assert result.exit_code == 3, result.stderr
    assert "CURRENT" in result.stderr


def test_runs_current_rich_renders_summary_panel(invoke_cli, tmp_path: Path) -> None:
    """Rich mode for ``runs current`` produces the summary panel."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run_and_current(derived, "shown-live")

    result = invoke_cli(["runs", "current", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    assert "shown-live" in result.stderr

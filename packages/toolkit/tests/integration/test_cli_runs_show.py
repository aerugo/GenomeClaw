"""Phase 2 — ``runs show <run-id>`` command tests."""

from __future__ import annotations

import json
from pathlib import Path


def _stage_run(
    derived: Path,
    run_id: str,
    *,
    sample_id: str = "test-sample",
    steps: list[dict] | None = None,
) -> Path:
    """Create a derived-run dir with manifest + (optionally) provenance."""
    run = derived / run_id
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "sample_id": sample_id,
                "schema_version": "v0.2",
                "created_at": "2026-05-12T00:00:00Z",
            }
        )
    )
    if steps is not None:
        (run / "provenance.json").write_text(json.dumps({"steps": steps}))
    return run


def test_runs_show_returns_manifest_and_steps(invoke_cli, tmp_path: Path) -> None:
    """`runs show` populates payload.detail with manifest + provenance steps."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(
        derived,
        "myrun",
        steps=[
            {"step": "ingest", "tool": "genomeclaw-prep", "tool_version": "0.0.1"},
            {"step": "normalize", "tool": "bcftools", "tool_version": "1.21"},
        ],
    )

    result = invoke_cli(["--json", "runs", "show", "myrun", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    detail = json.loads(result.stdout)["payload"]["detail"]
    assert detail["run_id"] == "myrun"
    assert detail["sample_id"] == "test-sample"
    assert detail["schema_version"] == "v0.2"
    assert detail["stage"] == "normalized"
    assert [s["step"] for s in detail["steps"]] == ["ingest", "normalize"]
    assert detail["steps"][1]["tool_version"] == "1.21"


def test_runs_show_handles_missing_provenance(invoke_cli, tmp_path: Path) -> None:
    """No ``provenance.json`` → stage falls back to 'unknown'; manifest still populates."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "halfrun", steps=None)

    result = invoke_cli(["--json", "runs", "show", "halfrun", "--derived-root", str(derived)])
    assert result.exit_code == 0
    detail = json.loads(result.stdout)["payload"]["detail"]
    assert detail["stage"] == "unknown"
    assert detail["steps"] == []
    assert detail["sample_id"] == "test-sample"  # manifest still read


def test_runs_show_refuses_unknown_run_with_precondition_exit(invoke_cli, tmp_path: Path) -> None:
    """Unknown run-id → exit 3 (precondition error)."""
    derived = tmp_path / "derived"
    derived.mkdir()
    result = invoke_cli(["runs", "show", "no-such-run", "--derived-root", str(derived)])
    assert result.exit_code == 3, result.stderr
    assert "no-such-run" in result.stderr


def test_runs_show_rich_renders_summary_panel_and_step_table(invoke_cli, tmp_path: Path) -> None:
    """Rich mode produces both the summary panel and the step table."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "shown", steps=[{"step": "ingest"}])

    result = invoke_cli(["runs", "show", "shown", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    assert "shown" in result.stderr  # in the summary panel
    assert "ingest" in result.stderr  # in the step table


def test_runs_show_argument_required(invoke_cli, tmp_path: Path) -> None:
    """`runs show` without a run-id argument is a usage error (exit 2)."""
    derived = tmp_path / "derived"
    derived.mkdir()
    result = invoke_cli(["runs", "show", "--derived-root", str(derived)])
    assert result.exit_code == 2

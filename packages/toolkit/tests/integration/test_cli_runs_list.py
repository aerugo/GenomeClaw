"""Phase 2 — ``runs list`` command tests."""

from __future__ import annotations

import json
from pathlib import Path


def _stage_run(
    derived: Path,
    run_id: str,
    *,
    sample_id: str = "test-sample",
    created_at: str = "2026-05-12T00:00:00Z",
    steps: list[str] | None = None,
) -> Path:
    """Create a minimal valid derived-run directory layout."""
    run = derived / run_id
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "sample_id": sample_id, "created_at": created_at})
    )
    if steps is not None:
        (run / "provenance.json").write_text(json.dumps({"steps": [{"step": s} for s in steps]}))
    return run


def test_runs_list_empty_derived_returns_zero_rows(invoke_cli, tmp_path: Path) -> None:
    """An empty derived root → 0 runs (success, not error)."""
    derived = tmp_path / "derived"
    derived.mkdir()
    result = invoke_cli(["--json", "runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "runs.list"
    assert payload["payload"]["runs"] == []


def test_runs_list_orders_newest_first(invoke_cli, tmp_path: Path) -> None:
    """`runs list` orders rows by ``created_at`` descending."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "older", created_at="2026-05-10T00:00:00Z", steps=["ingest"])
    _stage_run(derived, "newer", created_at="2026-05-12T00:00:00Z", steps=["ingest"])
    result = invoke_cli(["--json", "runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0
    runs = json.loads(result.stdout)["payload"]["runs"]
    assert [r["run_id"] for r in runs] == ["newer", "older"]


def test_runs_list_classifies_stage_from_provenance_trail(invoke_cli, tmp_path: Path) -> None:
    """`runs list` reads ``provenance.json`` to classify pipeline stage."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "r1", steps=["ingest"])
    _stage_run(derived, "r2", steps=["ingest", "normalize"])
    _stage_run(derived, "r3", steps=["ingest", "normalize", "vcfanno"])
    _stage_run(derived, "r4", steps=["ingest", "normalize", "vcfanno", "materialize"])

    result = invoke_cli(["--json", "runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0
    runs = {r["run_id"]: r for r in json.loads(result.stdout)["payload"]["runs"]}
    assert runs["r1"]["stage"] == "ingested"
    assert runs["r2"]["stage"] == "normalized"
    assert runs["r3"]["stage"] == "annotated"
    assert runs["r4"]["stage"] == "materialized"


def test_runs_list_filters_current_symlink(invoke_cli, tmp_path: Path) -> None:
    """A ``CURRENT`` symlink to a real run dir is not listed as a separate row."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "real-run", steps=["ingest"])
    update_current_symlink(derived, "real-run")

    result = invoke_cli(["--json", "runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0
    runs = json.loads(result.stdout)["payload"]["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "real-run"


def test_runs_list_rich_renders_status_table(invoke_cli, tmp_path: Path) -> None:
    """Rich mode renders the runs as a table (stderr; default output sink)."""
    derived = tmp_path / "derived"
    derived.mkdir()
    _stage_run(derived, "abc123", steps=["ingest"])

    result = invoke_cli(["runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr
    assert "abc123" in result.stderr
    assert "ingested" in result.stderr
    assert result.stdout == ""


def test_runs_list_schema_version_present(invoke_cli, tmp_path: Path) -> None:
    """`INV-C-cli-output-stability`: every JSON payload carries the schema version."""
    derived = tmp_path / "derived"
    derived.mkdir()
    result = invoke_cli(["--json", "runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["cli_output_schema_version"] == "1.0"

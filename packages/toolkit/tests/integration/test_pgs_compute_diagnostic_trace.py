"""Phase 2 of agent-synthesis-over-rich-tool-data — diagnostic-trace on PGS compute failures.

The `PgsComputeTaskResponse` returned by `POST /v1/pgs/compute` and
`GET /v1/pgs/compute/{task_id}` carries a `diagnostic: ToolDiagnosticTrace | None`
field populated on failure paths. The diagnostic is derived at response-build
time from the persisted structured error code (no SQLite schema migration);
this test pins both the derivation logic + the route-layer integration.

Per the Phase 1 audit, this is the AC8 muscle-question scenario's load-bearing
gap: the agent currently sees only the short error code (e.g., `"scorefile_missing:PGS000018"`)
and has nothing rich to translate into a user-facing explanation. The diagnostic
trace surfaces `stage`, `upstream_cause`, `suggested_fix`, `related_paths` — enough
for the agent to give the user a real explanation + an actionable next step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.schemas.pgs import (
    PgsComputeTaskResponse,
    ToolDiagnosticTrace,
)
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
    derive_diagnostic_from_error_code,
)

_RUN_ID = "2026-05-28T00-00-00Z-diagnostic-trace"
_SAMPLE = "diagnostic-trace-fixture"


def _stage_run(tmp_path: Path) -> Path:
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": _SAMPLE})
    )
    create_store(run_dir / "variants.duckdb")
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


# ---------------------------------------------------------------------------
# Pydantic model + derivation function shape tests
# ---------------------------------------------------------------------------


def test_PgsComputeTaskResponse_accepts_optional_diagnostic_field() -> None:
    """The response model accepts + serializes the new `diagnostic` field."""
    diagnostic = ToolDiagnosticTrace(
        stage="scorefile_staging",
        upstream_cause="scorefile_missing",
        suggested_fix="run `genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS000018`",
        related_paths=["/refs/PGS000018/PGS000018_hmPOS_GRCh38.txt.gz"],
        partial_log_tail=None,
    )
    resp = PgsComputeTaskResponse(
        task_id="t-1",
        pgs_id="PGS000018",
        status="failed",
        error="scorefile_missing:PGS000018",
        diagnostic=diagnostic,
    )
    dumped = resp.model_dump()
    assert dumped["diagnostic"]["stage"] == "scorefile_staging"
    assert dumped["diagnostic"]["upstream_cause"] == "scorefile_missing"
    assert "refs fetch" in dumped["diagnostic"]["suggested_fix"]


def test_PgsComputeTaskResponse_diagnostic_defaults_to_None() -> None:
    """`diagnostic` is optional — omit it for queued/running/done tasks."""
    resp = PgsComputeTaskResponse(
        task_id="t-1",
        pgs_id="PGS000018",
        status="queued",
        error=None,
    )
    assert resp.diagnostic is None
    assert resp.model_dump()["diagnostic"] is None


# ---------------------------------------------------------------------------
# Derivation function: error code → diagnostic trace
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error_code", "expected_stage", "expected_upstream"),
    [
        ("prs_compute_config_missing", "config_load", "prs_compute_config_missing"),
        ("scorefile_missing:PGS000018", "scorefile_staging", "scorefile_missing"),
        ("pgsc_calc_failed:rc=1", "pgsc_calc_invocation", "pgsc_calc_failed"),
        ("compute_path_disabled", "compute_gate", "compute_path_disabled"),
        ("worker_restart:stale_running", "worker_loop", "worker_restart"),
        ("dood_path_error:cannot bind /Volumes/...", "docker_out_of_docker_setup", "dood_path_error"),
        ("degenerate_result:0 variants matched", "match_rate_parse", "degenerate_result"),
        ("prs_decline:ancestry_calibration_uncertain", "calibration_check", "prs_decline"),
    ],
)
def test_derive_diagnostic_from_known_error_codes(
    error_code: str, expected_stage: str, expected_upstream: str
) -> None:
    """Each documented error-code shape maps to a structured diagnostic."""
    diag = derive_diagnostic_from_error_code(error_code)
    assert diag is not None, f"derivation returned None for known error {error_code!r}"
    assert diag.stage == expected_stage
    assert diag.upstream_cause == expected_upstream


def test_derive_diagnostic_for_scorefile_missing_extracts_pgs_id_into_related_paths() -> None:
    """`scorefile_missing:<pgs_id>` derivation surfaces the actual PGS ID in
    `related_paths` (the path the worker expected). Lets the agent name the
    missing scorefile in plain language."""
    diag = derive_diagnostic_from_error_code("scorefile_missing:PGS000018")
    assert diag is not None
    assert any("PGS000018" in p for p in diag.related_paths)
    assert diag.suggested_fix is not None
    assert "PGS000018" in diag.suggested_fix
    assert "refs fetch" in diag.suggested_fix


def test_derive_diagnostic_for_pgsc_calc_failed_carries_returncode_in_upstream() -> None:
    """`pgsc_calc_failed:rc=<n>` derivation preserves the rc in some form so
    the agent can mention it."""
    diag = derive_diagnostic_from_error_code("pgsc_calc_failed:rc=2")
    assert diag is not None
    assert diag.stage == "pgsc_calc_invocation"
    # The rc may appear in upstream_cause OR partial_log_tail; either is acceptable
    surfaced = (diag.upstream_cause or "") + (diag.partial_log_tail or "")
    assert "rc=2" in surfaced or "returncode 2" in surfaced


def test_derive_diagnostic_for_unknown_error_returns_minimal_diagnostic() -> None:
    """Unknown error codes (worker_unexpected_error:<Class>) produce a minimal
    diagnostic — not None — so the agent at least sees stage=worker_loop and
    upstream_cause=the_class_name. The suggested_fix is None for unknown errors."""
    diag = derive_diagnostic_from_error_code("worker_unexpected_error:ValueError")
    assert diag is not None
    assert diag.stage == "worker_loop"
    assert diag.upstream_cause == "worker_unexpected_error"
    assert diag.suggested_fix is None


def test_derive_diagnostic_for_none_or_empty_returns_None() -> None:
    """No error → no diagnostic. `derive_diagnostic_from_error_code(None)`
    + `derive_diagnostic_from_error_code("")` both return None."""
    assert derive_diagnostic_from_error_code(None) is None
    assert derive_diagnostic_from_error_code("") is None


# ---------------------------------------------------------------------------
# Route-layer integration
# ---------------------------------------------------------------------------


def test_compute_status_route_returns_diagnostic_for_failed_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET /v1/pgs/compute/{task_id}` on a failed task includes the derived
    diagnostic in the JSON body — the route layer reads the persisted error
    code + computes the diagnostic before serializing."""
    monkeypatch.setenv("GENOMECLAW_DERIVED_ROOT", str(tmp_path / "derived"))
    run_dir = _stage_run(tmp_path)

    # Manually insert a failed task into the SQLite DB (simulating a worker
    # failure path; no actual compute_fn invocation needed for this route test).
    import sqlite3
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC).isoformat()
    with sqlite3.connect(str(run_dir / "pgs_compute_tasks.sqlite")) as conn:
        conn.execute(
            """
            INSERT INTO pgs_compute_tasks
                (task_id, pgs_id, trait_label, rationale, requested_for_question,
                 status, error, requested_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?)
            """,
            [
                "diag-test-task",
                "PGS000018",
                "CAD",
                "diagnostic-trace integration test",
                "n/a",
                "scorefile_missing:PGS000018",
                now, now, now,
            ],
        )
        conn.commit()

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        r = client.get("/v1/pgs/compute/diag-test-task")
        assert r.status_code == 200, (r.status_code, r.text)
        body = r.json()
        assert body["status"] == "failed"
        assert body["error"] == "scorefile_missing:PGS000018"
        assert body["diagnostic"] is not None
        assert body["diagnostic"]["stage"] == "scorefile_staging"
        assert body["diagnostic"]["upstream_cause"] == "scorefile_missing"
        assert "PGS000018" in body["diagnostic"]["suggested_fix"]


def test_compute_status_route_returns_no_diagnostic_for_running_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET /v1/pgs/compute/{task_id}` for a running task returns
    `diagnostic: null` — diagnostic is only meaningful for failed paths."""
    monkeypatch.setenv("GENOMECLAW_DERIVED_ROOT", str(tmp_path / "derived"))
    run_dir = _stage_run(tmp_path)

    import sqlite3
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC).isoformat()
    with sqlite3.connect(str(run_dir / "pgs_compute_tasks.sqlite")) as conn:
        conn.execute(
            """
            INSERT INTO pgs_compute_tasks
                (task_id, pgs_id, trait_label, rationale, requested_for_question,
                 status, error, requested_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, 'running', NULL, ?, ?, NULL)
            """,
            [
                "diag-running-task",
                "PGS000018",
                "CAD",
                "diagnostic-trace running test",
                "n/a",
                now, now,
            ],
        )
        conn.commit()

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        r = client.get("/v1/pgs/compute/diag-running-task")
        body = r.json()
        assert body["status"] == "running"
        assert body["diagnostic"] is None

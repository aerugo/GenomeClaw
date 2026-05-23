"""Phase 5 RED — crash recovery + observability for the E.3 worker.

Two surfaces:

1. **Stale-running cleanup at startup**. If the host service is killed
   mid-compute, the in-flight task is left at ``status='running'``
   indefinitely (Phase 4 acknowledged this gap). Phase 5 adds a
   startup-time cleanup that transitions any row in ``running`` for
   longer than ``GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S`` (default 3600)
   to ``failed:worker_restart:stale_running``.

2. **INFO-level structured log lines**. Every status transition the
   worker drives (claim, done, failed, kill-switch reject, stale-running
   cleanup) emits a log record with structured ``extra={"task_id":...,
   "pgs_id":..., "transition":...}`` fields so an operator's ``tail -f``
   on the host service log shows exactly when each task moves.

Plan: [docs/plans/active/agent-prs-compute-fix/phases/phase-5.md](../../../../docs/plans/active/agent-prs-compute-fix/phases/phase-5.md)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    cleanup_stale_running_tasks,
    create_pgs_compute_tasks_db_if_missing,
    query_pgs_compute_task_status,
)

_ORCHESTRATOR_LOGGER = "genomeclaw_toolkit.service.pgs_compute_orchestrator"
_RUN_ID = "2026-05-23T00-00-00Z-phase5"
_SAMPLE = "phase5-fixture"


def _stage_run(tmp_path: Path) -> tuple[Path, Path]:
    """Stage a derived/<run-id>/ with manifest + tasks DB. Returns (derived_root, run_dir)."""
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
    return derived_root, run_dir


def _seed_running_row(
    db_path: Path, *, task_id: str, started_at: datetime, pgs_id: str = "PGS_X"
) -> None:
    """Insert a row directly with ``status='running'`` + the given ``started_at``."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO pgs_compute_tasks
        (task_id, pgs_id, trait_label, rationale, requested_for_question,
         status, error, requested_at, started_at, completed_at)
        VALUES (?, ?, 'r', 'phase-5 unit test rationale', 'q', 'running', NULL,
                ?, ?, NULL)
        """,
        [task_id, pgs_id, started_at.isoformat(), started_at.isoformat()],
    )
    conn.commit()
    conn.close()


def _enqueue(client, *, pgs_id="PGS_TEST", rationale="phase-5 worker recovery test"):
    return client.post(
        "/v1/pgs/compute",
        json={
            "pgs_id": pgs_id,
            "trait_label": "test trait",
            "rationale": rationale,
            "requested_for_question": "phase-5 test question",
        },
    )


def _wait_for_terminal(client, task_id, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/v1/pgs/compute/{task_id}")
        body = r.json()
        if body.get("status") in ("done", "failed"):
            return body
        time.sleep(0.05)
    return r.json()


# -----------------------------------------------------------------------------
# Stale-running cleanup — unit tests on cleanup_stale_running_tasks
# -----------------------------------------------------------------------------


def test_stale_running_cleanup_transitions_old_rows_to_failed(tmp_path: Path) -> None:
    """A running row older than the window transitions to ``failed:worker_restart:stale_running``."""
    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    stale_started_at = datetime.now(tz=UTC) - timedelta(hours=2)
    _seed_running_row(db_path, task_id="t-stale", started_at=stale_started_at)

    cleaned = cleanup_stale_running_tasks(db_path, window_s=3600)

    assert cleaned == ["t-stale"]
    row = query_pgs_compute_task_status(db_path, task_id="t-stale")
    assert row is not None
    assert row.status == "failed"
    assert row.error == "worker_restart:stale_running"


def test_stale_running_cleanup_leaves_recent_rows_alone(tmp_path: Path) -> None:
    """A row that started 5 minutes ago is well within the 1-h window; cleanup ignores it."""
    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    recent_started_at = datetime.now(tz=UTC) - timedelta(minutes=5)
    _seed_running_row(db_path, task_id="t-recent", started_at=recent_started_at)

    cleaned = cleanup_stale_running_tasks(db_path, window_s=3600)

    assert cleaned == []
    row = query_pgs_compute_task_status(db_path, task_id="t-recent")
    assert row is not None
    assert row.status == "running"  # unchanged


def test_stale_running_cleanup_returns_empty_on_clean_db(tmp_path: Path) -> None:
    """Empty DB → cleanup returns empty list + doesn't raise."""
    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    assert cleanup_stale_running_tasks(db_path, window_s=3600) == []


def test_stale_running_window_configurable_via_env(tmp_path: Path, monkeypatch) -> None:
    """``GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S=10`` shrinks the window."""
    monkeypatch.setenv("GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S", "10")

    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    # 15s ago — within shrunk window:
    fifteen_s_ago = datetime.now(tz=UTC) - timedelta(seconds=15)
    _seed_running_row(db_path, task_id="t-fifteen", started_at=fifteen_s_ago)

    # 5s ago — outside shrunk window:
    five_s_ago = datetime.now(tz=UTC) - timedelta(seconds=5)
    _seed_running_row(db_path, task_id="t-five", started_at=five_s_ago, pgs_id="PGS_Y")

    cleaned = cleanup_stale_running_tasks(db_path)  # window from env

    assert cleaned == ["t-fifteen"]
    assert query_pgs_compute_task_status(db_path, task_id="t-fifteen").status == "failed"
    assert query_pgs_compute_task_status(db_path, task_id="t-five").status == "running"


# -----------------------------------------------------------------------------
# Stale-running cleanup — runs at app startup
# -----------------------------------------------------------------------------


def test_stale_running_cleanup_runs_at_app_startup(tmp_path: Path, monkeypatch) -> None:
    """Building the app + entering TestClient transitions any stale rows."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    derived_root, run_dir = _stage_run(tmp_path)
    db_path = run_dir / "pgs_compute_tasks.sqlite"

    # Pre-seed a stale row BEFORE building the app.
    stale_started_at = datetime.now(tz=UTC) - timedelta(hours=2)
    _seed_running_row(db_path, task_id="t-prestart", started_at=stale_started_at)

    app = build_app(derived_root=derived_root)
    with TestClient(app):
        pass  # entering the context runs the lifespan startup hook

    row = query_pgs_compute_task_status(db_path, task_id="t-prestart")
    assert row is not None
    assert row.status == "failed"
    assert row.error == "worker_restart:stale_running"


# -----------------------------------------------------------------------------
# Observability — structured log lines on every status transition
# -----------------------------------------------------------------------------


def test_log_line_on_task_claim(tmp_path: Path, monkeypatch, caplog) -> None:
    """Worker emits ``transition='queued_to_running'`` INFO on claim."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    derived_root, _ = _stage_run(tmp_path)

    app = build_app(derived_root=derived_root)
    with caplog.at_level(logging.INFO, logger=_ORCHESTRATOR_LOGGER):
        with TestClient(app) as client:
            resp = _enqueue(client)
            _wait_for_terminal(client, resp.json()["task_id"])

    claim_records = [
        r for r in caplog.records if getattr(r, "transition", None) == "queued_to_running"
    ]
    assert claim_records, [r.message for r in caplog.records]
    assert all(getattr(r, "task_id", None) for r in claim_records)
    assert all(getattr(r, "pgs_id", None) for r in claim_records)


def test_log_line_on_task_done(tmp_path: Path, monkeypatch, caplog) -> None:
    """Worker emits ``transition='running_to_done'`` INFO on success."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    derived_root, _ = _stage_run(tmp_path)

    app = build_app(derived_root=derived_root)
    with caplog.at_level(logging.INFO, logger=_ORCHESTRATOR_LOGGER):
        with TestClient(app) as client:
            resp = _enqueue(client)
            _wait_for_terminal(client, resp.json()["task_id"])

    done_records = [
        r for r in caplog.records if getattr(r, "transition", None) == "running_to_done"
    ]
    assert done_records


def test_log_line_on_task_failed(tmp_path: Path, monkeypatch, caplog) -> None:
    """Worker emits ``transition='running_to_failed'`` INFO + structured ``error`` on failure."""
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    # Stub the no-op so the kill-switch-off path doesn't fire; instead the
    # worker invokes a compute_fn that raises a known structured error.
    async def failing_compute(_task):
        raise RuntimeError("induced phase-5 test failure")

    monkeypatch.setattr(pgs_compute_orchestrator, "_noop_compute_fn", failing_compute)

    derived_root, _ = _stage_run(tmp_path)
    app = build_app(derived_root=derived_root)
    with caplog.at_level(logging.INFO, logger=_ORCHESTRATOR_LOGGER):
        with TestClient(app) as client:
            resp = _enqueue(client)
            _wait_for_terminal(client, resp.json()["task_id"])

    fail_records = [
        r for r in caplog.records if getattr(r, "transition", None) == "running_to_failed"
    ]
    assert fail_records
    rec = fail_records[0]
    assert getattr(rec, "error", None) is not None
    assert "worker_unexpected_error" in rec.error or "RuntimeError" in rec.error


def test_log_line_on_kill_switch_reject(tmp_path: Path, monkeypatch, caplog) -> None:
    """Worker emits ``transition='queued_to_failed_compute_path_disabled'`` INFO on kill-switch reject."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    monkeypatch.setenv("GENOMECLAW_PGS_COMPUTE_ENABLED", "false")

    derived_root, _ = _stage_run(tmp_path)
    app = build_app(derived_root=derived_root)
    with caplog.at_level(logging.INFO, logger=_ORCHESTRATOR_LOGGER):
        with TestClient(app) as client:
            resp = _enqueue(client)
            _wait_for_terminal(client, resp.json()["task_id"])

    kill_records = [
        r
        for r in caplog.records
        if getattr(r, "transition", None) == "queued_to_failed_compute_path_disabled"
    ]
    assert kill_records


def test_log_line_on_stale_running_cleanup(tmp_path: Path, monkeypatch, caplog) -> None:
    """Stale-running cleanup emits WARNING ``transition='stale_running_to_failed'`` per row."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    derived_root, run_dir = _stage_run(tmp_path)
    db_path = run_dir / "pgs_compute_tasks.sqlite"
    stale_started_at = datetime.now(tz=UTC) - timedelta(hours=2)
    _seed_running_row(db_path, task_id="t-stale", started_at=stale_started_at)

    app = build_app(derived_root=derived_root)
    with caplog.at_level(logging.WARNING, logger=_ORCHESTRATOR_LOGGER):
        with TestClient(app):
            pass

    cleanup_records = [
        r
        for r in caplog.records
        if getattr(r, "transition", None) == "stale_running_to_failed"
    ]
    assert cleanup_records
    assert cleanup_records[0].levelno == logging.WARNING
    assert getattr(cleanup_records[0], "task_id", None) == "t-stale"

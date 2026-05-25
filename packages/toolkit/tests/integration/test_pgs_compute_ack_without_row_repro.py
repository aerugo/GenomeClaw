"""Reproduce the ack-without-row failure mode for genomeclaw_pgs_compute.

Five independent reproductions across three demo sessions (Rounds 1-3
of docs/reports/genomeclaw-demo-questions-2026-05-{24,25}*.md) show
that genomeclaw_pgs_compute tasks reach status=done but the
corresponding pgs_scores row is never written. The operator's actual
pgs_compute_tasks.sqlite for run 2026-05-24T12-52-11Z-f2dae2 carries
11 such rows — all completed in <2s (impossible for a real LDpred
compute) — and the active variants.duckdb has 0 rows in pgs_scores.

Phase 1 diagnosis pinned the root cause: when prs_compute_config.json
is missing from the active run-dir, the app lifespan
(packages/toolkit/src/genomeclaw_toolkit/service/app.py:207-243) logs a
WARNING and leaves compute_fn=None. The worker lifespan then falls
through to _dispatch_compute → _noop_compute_fn, which is literally
`await asyncio.sleep(0)`. The worker loop calls _mark_done(...)
unconditionally after compute_fn returns without raising — so every
task lands at done with no row written.

This is structurally the same shape as INV-R002 (Never Cache a
Degenerate Result): a task tracker reports success without the
authoritative store being updated. The fix (Phase 2) will make the
missing-config path mark the task `failed:prs_compute_config_missing`
the same way the kill-switch path already marks
`failed:compute_path_disabled` at orchestrator line 595.

Pairs with `test_pgs_compute_worker_integration.py` which exercises
the happy-path with prs_compute_config.json present; this test
exercises the production-realistic without-config path which the
existing test suite never covered.

Tracks the investigate-pgs-compute-ack-without-row plan
(docs/plans/active/investigate-pgs-compute-ack-without-row/).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)

_RUN_ID = "2026-05-25T00-00-00Z-ackwithoutrow"
_SAMPLE = "ack-without-row-fixture"


def _stage_run_WITHOUT_config(tmp_path: Path) -> Path:
    """Stage a derived run dir + tables but DELIBERATELY omit prs_compute_config.json.

    This is the operator's actual state for run
    2026-05-24T12-52-11Z-f2dae2 (the affected real-data run): valid
    manifest + variants.duckdb + pgs_compute_tasks.sqlite, but no
    sidecar config. The app lifespan accepts this state with a WARNING
    and runs the worker in the noop-compute path.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": _SAMPLE})
    )
    create_store(run_dir / "variants.duckdb")
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    # No prs_compute_config.json — this is the load-bearing omission.
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def _enqueue(client: TestClient, *, pgs_id: str = "PGS000014") -> str:
    """POST /v1/pgs/compute; return task_id."""
    r = client.post(
        "/v1/pgs/compute",
        json={
            "pgs_id": pgs_id,
            "trait_label": "T2D",
            "rationale": "ack-without-row reproduction",
            "requested_for_question": "Based on my DNA, am I more or less likely to develop type-2 diabetes?",
        },
    )
    assert r.status_code == 202, (r.status_code, r.text)
    return r.json()["task_id"]


def _wait_for_terminal(client: TestClient, task_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/v1/pgs/compute/{task_id}")
        body = r.json()
        if body.get("status") in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not reach terminal status within {timeout_s}s")


def test_invR002_pgs_compute_without_config_does_not_silently_mark_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INV-R002: with prs_compute_config.json absent, a compute task MUST NOT
    reach status=done without a matching pgs_scores row.

    RED today (pre-fix): the worker noops the compute and marks the task
    done; pgs_scores stays empty. The current behaviour is the exact
    ack-without-row failure mode the operator hit 5 times.

    GREEN after Phase 2's fix: the worker either (a) marks the task
    failed with a structured error_class='prs_compute_config_missing',
    OR (b) writes a real row (only possible if the missing-config path
    is replaced with an actual compute — out of scope for this fix).
    The test asserts either terminal-status-with-row-OR-structured-failure;
    it does NOT prescribe which fix shape.
    """
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    run_dir = _stage_run_WITHOUT_config(tmp_path)

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        task_id = _enqueue(client, pgs_id="PGS000014")
        final = _wait_for_terminal(client, task_id)

    pgs_row_count: int
    with duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True) as conn:
        pgs_row_count = conn.execute(
            "SELECT COUNT(*) FROM pgs_scores WHERE pgs_id = 'PGS000014'"
        ).fetchone()[0]

    if final["status"] == "done":
        # The dangerous state — done without a row is the bug.
        assert pgs_row_count >= 1, (
            "INV-R002 violation: pgs_compute_tasks marked status=done for "
            "PGS000014, but pgs_scores has 0 matching rows. The orchestrator "
            "is treating the no-op compute path (no prs_compute_config.json) "
            "as success — the agent then sees `done` and queries pgs_get, "
            "which returns no row. See "
            "docs/plans/active/investigate-pgs-compute-ack-without-row/ "
            "for the diagnosis."
        )
    else:
        # Acceptable: the worker correctly recognised the missing-config
        # state and marked the task failed with structured error. The
        # error must carry an actionable signal so the agent can surface
        # the right operator-facing reason.
        assert final["status"] == "failed", final
        err = final.get("error") or ""
        assert "config" in err.lower() or "compute_path" in err.lower() or "prs_compute" in err.lower(), (
            f"task failed but error is not actionable: {err!r}. "
            "Expected something like 'prs_compute_config_missing' so the "
            "agent can paraphrase 'PRS compute is offline; operator hasn't "
            "staged prs_compute_config.json'."
        )

"""Phase 3 RED — pin the worker-skeleton queue-management contract.

The E.3 worker doesn't exist on current main (Phase 1's discovery). Phase 3
adds the bones: a FastAPI ``lifespan`` hook that spawns an in-process
``asyncio`` task; the task polls ``pgs_compute_tasks.sqlite``, atomically
claims one queued row at a time, transitions it through ``running → done``
(or ``failed`` when the kill-switch is off), and respects a single
in-flight concurrency cap. The "compute" itself is a no-op
``await asyncio.sleep(0)`` in this phase — real
``compute_prs_with_coverage_fill(...)`` integration lands in Phase 4.

Test taxonomy:

- **Unit tests on ``_atomic_claim_one``** — the SQL-level contract, no
  FastAPI. Cheaper + more precise than driving via TestClient.
- **Integration tests via TestClient** — confirm the lifespan hook spawns
  the worker + the drain path works end-to-end via the HTTP routes.
- **Invariant tests** — INV-A003 (rationale + requested_for_question
  threaded through to the worker) + INV-P001 (no networking imports in
  the orchestrator).

Plan: [docs/plans/active/agent-prs-compute-fix/phases/phase-3.md](../../../../docs/plans/active/agent-prs-compute-fix/phases/phase-3.md)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock

from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)

_RUN_ID = "2026-05-23T00-00-00Z-phase3"


def _stage_run(derived_root: Path) -> Path:
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": "phase3-fixture"}
        )
    )
    create_store(run_dir / "variants.duckdb")
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def _enqueue(client, *, pgs_id="PGS_TEST", rationale="phase-3 test rationale"):
    return client.post(
        "/v1/pgs/compute",
        json={
            "pgs_id": pgs_id,
            "trait_label": "test trait",
            "rationale": rationale,
            "requested_for_question": "test question",
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
# Unit tests on _atomic_claim_one — the SQL-level atomicity contract.
# -----------------------------------------------------------------------------


def test_atomic_claim_returns_none_on_empty_queue(tmp_path):
    """No queued rows → ``_atomic_claim_one`` returns None."""
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import _atomic_claim_one

    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)
    assert _atomic_claim_one(db_path) is None


def test_atomic_claim_picks_one_row_at_a_time_in_FIFO_order(tmp_path):
    """Three queued rows → three successful claims in FIFO order; fourth returns None.

    Pins the FIFO ordering (oldest ``requested_at`` first) + the atomicity
    that each claim transitions exactly one row to running.
    """
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
        _atomic_claim_one,
        enqueue_pgs_compute_task,
    )

    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    for i in range(3):
        enqueue_pgs_compute_task(
            db_path,
            pgs_id=f"PGS_{i}",
            trait_label=f"trait_{i}",
            rationale="phase-3 unit test rationale",
            requested_for_question="phase-3 unit test",
        )
        time.sleep(0.001)  # ensure distinct ISO timestamps for FIFO ordering

    claims = []
    while True:
        c = _atomic_claim_one(db_path)
        if c is None:
            break
        claims.append(c)

    assert len(claims) == 3
    pgs_ids = [c.pgs_id for c in claims]
    assert pgs_ids == ["PGS_0", "PGS_1", "PGS_2"]

    # All rows are now in running state.
    conn = sqlite3.connect(str(db_path))
    try:
        statuses = [r[0] for r in conn.execute("SELECT status FROM pgs_compute_tasks")]
    finally:
        conn.close()
    assert set(statuses) == {"running"}


def test_atomic_claim_skips_already_running_rows(tmp_path):
    """Pre-existing running row + one queued → claim picks only the queued row."""
    from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
        _atomic_claim_one,
        enqueue_pgs_compute_task,
    )

    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    # Pre-seed a running row directly.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO pgs_compute_tasks
        (task_id, pgs_id, trait_label, rationale, requested_for_question,
         status, error, requested_at, started_at, completed_at)
        VALUES ('t-running', 'PGS_R', 'r', 'phase-3 unit test rationale', 'q',
                'running', NULL, '2026-05-23T00:00:00+00:00',
                '2026-05-23T00:00:00+00:00', NULL)
        """,
    )
    conn.commit()
    conn.close()

    enqueue_pgs_compute_task(
        db_path,
        pgs_id="PGS_Q",
        trait_label="q",
        rationale="phase-3 unit test rationale",
        requested_for_question="q",
    )

    claimed = _atomic_claim_one(db_path)
    assert claimed is not None
    assert claimed.pgs_id == "PGS_Q"
    # No further claims possible.
    assert _atomic_claim_one(db_path) is None


# -----------------------------------------------------------------------------
# Integration tests via TestClient — full lifespan + worker loop wired.
# -----------------------------------------------------------------------------


def test_worker_drains_queued_task_to_done(tmp_path, monkeypatch):
    """Happy path: a queued task transitions to ``done`` via the worker."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = _enqueue(client)
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        final = _wait_for_terminal(client, task_id)
        assert final["status"] == "done", final


def test_worker_concurrency_cap_one_in_flight(tmp_path, monkeypatch):
    """Three queued tasks → no two run concurrently (asyncio.Lock cap=1).

    Instrumented compute_fn records max concurrent invocations via a
    thread-safe counter. The cap is enforced by a module-level
    asyncio.Lock; this test pins that invariant.
    """
    import asyncio

    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    counter = {"in_flight": 0, "max": 0}
    lock = Lock()

    async def slow_compute(_task):
        with lock:
            counter["in_flight"] += 1
            counter["max"] = max(counter["max"], counter["in_flight"])
        try:
            await asyncio.sleep(0.05)  # hold the slot
        finally:
            with lock:
                counter["in_flight"] -= 1

    monkeypatch.setattr(pgs_compute_orchestrator, "_noop_compute_fn", slow_compute)

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        task_ids = [_enqueue(client, pgs_id=f"PGS_{i}").json()["task_id"] for i in range(3)]
        for tid in task_ids:
            final = _wait_for_terminal(client, tid, timeout_s=10.0)
            assert final["status"] == "done", final

    assert counter["max"] == 1, f"expected at most 1 in-flight; saw {counter['max']}"


def test_worker_respects_kill_switch_at_startup(tmp_path, monkeypatch):
    """Kill-switch off → worker claims the row then fails with ``compute_path_disabled``.

    "Claim-then-fail" (not "skip") so the agent's polling surfaces the
    rejection promptly rather than the row sitting at ``queued`` forever.
    """
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    monkeypatch.setenv("GENOMECLAW_PGS_COMPUTE_ENABLED", "false")

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = _enqueue(client)
        task_id = resp.json()["task_id"]
        final = _wait_for_terminal(client, task_id)

    assert final["status"] == "failed", final
    assert final["error"] == "compute_path_disabled", final


def test_worker_respects_kill_switch_flipped_to_off_mid_run(tmp_path, monkeypatch):
    """Flip kill-switch on → off between enqueues; the second enqueue fails.

    The worker re-resolves ``compute_enabled`` on every tick so a config
    flip takes effect immediately.
    """
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    monkeypatch.setenv("GENOMECLAW_PGS_COMPUTE_ENABLED", "true")

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        first = _enqueue(client, pgs_id="PGS_A").json()["task_id"]
        first_final = _wait_for_terminal(client, first)
        assert first_final["status"] == "done", first_final

        # Flip the switch off.
        monkeypatch.setenv("GENOMECLAW_PGS_COMPUTE_ENABLED", "false")

        second = _enqueue(client, pgs_id="PGS_B").json()["task_id"]
        second_final = _wait_for_terminal(client, second)

    assert second_final["status"] == "failed", second_final
    assert second_final["error"] == "compute_path_disabled", second_final


def test_invA003_worker_reads_rationale_and_requested_for_question(tmp_path, monkeypatch):
    """INV-A003: the worker sees both ``rationale`` + ``requested_for_question`` on claim.

    Pins the plumbing that Phase 4 threads through to ``pgs_scores`` row
    persistence. If the worker's claimed-row dataclass were to drop either
    field, this test catches it before Phase 4's persistence layer does.
    """
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    captured: list[dict] = []

    async def capturing_compute(task):
        captured.append(
            {
                "task_id": task.task_id,
                "pgs_id": task.pgs_id,
                "rationale": task.rationale,
                "requested_for_question": task.requested_for_question,
            }
        )

    monkeypatch.setattr(pgs_compute_orchestrator, "_noop_compute_fn", capturing_compute)

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    distinctive_rationale = (
        "Canonical AMD PRS test rationale — INV-A003 plumbing assertion."
    )
    distinctive_question = "do I have any increased risk of losing eye sight when I age?"

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": distinctive_rationale,
                "requested_for_question": distinctive_question,
            },
        )
        task_id = resp.json()["task_id"]
        _wait_for_terminal(client, task_id)

    assert len(captured) == 1
    assert captured[0]["rationale"] == distinctive_rationale
    assert captured[0]["requested_for_question"] == distinctive_question


def test_invP001_orchestrator_imports_no_networking_modules():
    """INV-P001: the worker's orchestrator module imports nothing that opens an outbound socket.

    A defensive static check: the worker is local-only; if a future widening
    adds ``httpx`` / ``urllib`` / ``socket`` to the orchestrator's imports,
    this test catches it. Phase 4's real compute also stays network-free
    (it shells out to local subprocesses); a network import here would
    signal a regression.
    """
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    src = Path(pgs_compute_orchestrator.__file__).read_text()
    forbidden = ["httpx", "urllib", "requests", "aiohttp", "socket.socket", "ssl"]
    found = [name for name in forbidden if name in src]
    assert not found, (
        f"PGS compute orchestrator must remain network-free; "
        f"found forbidden imports/usages: {found}"
    )


def test_worker_cleans_up_on_app_shutdown(tmp_path, monkeypatch):
    """Exiting the TestClient context cancels the worker without hanging or warnings."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    # Use a generous timeout — if shutdown hangs, the test fails by timeout.
    start = time.monotonic()
    with TestClient(app) as client:
        _enqueue(client)
        # Don't wait for terminal; the worker may be mid-tick on shutdown.
    elapsed = time.monotonic() - start
    # Shutdown should be fast (≤2s); a hang means the cancel didn't propagate.
    assert elapsed < 3.0, f"app shutdown took {elapsed:.2f}s; worker likely hung"

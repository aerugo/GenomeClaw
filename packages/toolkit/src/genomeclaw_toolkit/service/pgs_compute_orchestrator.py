"""Async orchestrator for agent-triggered PRS compute (Phase 6 Slice E v2).

The task DB lives at `derived/<run-id>/pgs_compute_tasks.sqlite` (sibling
of `variants.duckdb`) rather than as a table inside `variants.duckdb`
because the lifecycle is different: `pgs_scores` is authoritative + lives
with the run; the task DB is operational + may want to be cleared without
touching the run's derived store. Status enum per the v2 slice plan:
``queued | running | done | failed``. The `failed` status carries an
``error`` column; one specific failure mode is ``compute_path_disabled``
(kill-switch on).

Phase 3 (agent-prs-compute-fix) adds the **E.3 worker skeleton**:
:func:`pgs_compute_worker_loop` polls the queue, atomically claims one
row at a time via :func:`_atomic_claim_one`, transitions it through
``running → done`` (or ``failed`` when the kill-switch is off), and runs
its ``compute_fn`` callback under an :class:`asyncio.Lock` (concurrency
cap = 1 in-flight). Phase 3's ``compute_fn`` is a no-op
(:func:`_noop_compute_fn`); Phase 4 swaps in
``compute_prs_with_coverage_fill(...)``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path

_LOG = logging.getLogger(__name__)

PgsTaskStatus = Literal["queued", "running", "done", "failed"]


_PGS_COMPUTE_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS pgs_compute_tasks (
    task_id                 TEXT NOT NULL PRIMARY KEY,
    pgs_id                  TEXT NOT NULL,
    trait_label             TEXT NOT NULL,
    rationale               TEXT NOT NULL,
    requested_for_question  TEXT NOT NULL,
    status                  TEXT NOT NULL,
    error                   TEXT,
    requested_at            TEXT NOT NULL,
    started_at              TEXT,
    completed_at            TEXT
);
"""


def create_pgs_compute_tasks_db_if_missing(db_path: Path) -> None:
    """Initialise the `pgs_compute_tasks` SQLite DB if it doesn't already exist.

    Idempotent. The orchestrator (E.3) calls this on startup + on every
    `enqueue` so the DB exists by the time a row is inserted.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_PGS_COMPUTE_TASKS_DDL)
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class PgsComputeTaskRow:
    """One row of `pgs_compute_tasks`. Returned by the status query."""

    task_id: str
    pgs_id: str
    trait_label: str
    status: PgsTaskStatus
    error: str | None


def enqueue_pgs_compute_task(
    db_path: Path,
    *,
    pgs_id: str,
    trait_label: str,
    rationale: str,
    requested_for_question: str,
) -> PgsComputeTaskRow:
    """Insert a new `pgs_compute_tasks` row with `status=queued`; return the row.

    E.1 stubs the worker; the row sits at `queued` indefinitely until the
    E.3 background loop drains it. Tests against the stubbed flow assert
    on the enqueued-row shape, not on the eventual `done` outcome.
    """
    create_pgs_compute_tasks_db_if_missing(db_path)
    task_id = str(uuid.uuid4())
    requested_at = datetime.now(tz=UTC).isoformat()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO pgs_compute_tasks
                (task_id, pgs_id, trait_label, rationale, requested_for_question,
                 status, error, requested_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, 'queued', NULL, ?, NULL, NULL)
            """,
            [task_id, pgs_id, trait_label, rationale, requested_for_question, requested_at],
        )
        conn.commit()
    finally:
        conn.close()
    return PgsComputeTaskRow(
        task_id=task_id,
        pgs_id=pgs_id,
        trait_label=trait_label,
        status="queued",
        error=None,
    )


def query_pgs_compute_task_status(db_path: Path, *, task_id: str) -> PgsComputeTaskRow | None:
    """Fetch a single task row by `task_id`; returns None if not found."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT task_id, pgs_id, trait_label, status, error
            FROM pgs_compute_tasks
            WHERE task_id = ?
            """,
            [task_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return PgsComputeTaskRow(
        task_id=row[0],
        pgs_id=row[1],
        trait_label=row[2],
        status=row[3],
        error=row[4],
    )


# ---------------------------------------------------------------------------
# E.3 worker — Phase 3 (agent-prs-compute-fix)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PgsComputeTaskFullRow:
    """The columns the worker reads when it claims a task.

    Distinct from :class:`PgsComputeTaskRow` (the status-query projection)
    because the worker needs ``rationale`` + ``requested_for_question`` for
    INV-A003 plumbing; the status query intentionally omits them to keep
    the agent's polling response minimal-sufficient.
    """

    task_id: str
    pgs_id: str
    trait_label: str
    rationale: str
    requested_for_question: str


def _poll_interval_s() -> float:
    """Worker poll interval in seconds; defaults 1.0, overridable for tests."""
    return float(os.environ.get("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "1.0"))


def _resolve_compute_enabled() -> bool:
    """Read the kill-switch from the environment.

    Phase 3 surface: a single env var controls the worker's compute gate.
    Phase 4 swaps this for a ``prs_compute_config.json`` sidecar read so
    the operator can flip the switch without restarting the service. The
    default is ``True`` — existing deployments that don't set the env var
    keep the compute path on.
    """
    raw = os.environ.get("GENOMECLAW_PGS_COMPUTE_ENABLED", "true").strip().lower()
    return raw not in ("false", "0", "no", "off")


def _atomic_claim_one(db_path: Path) -> PgsComputeTaskFullRow | None:
    """Atomically transition the oldest queued row to running; return it, or None.

    Uses SQLite ``UPDATE ... RETURNING`` (3.35+). The inner SELECT picks
    the oldest queued row by ``requested_at``; the outer UPDATE's WHERE
    clause includes ``status='queued'`` so a concurrent claimant can't
    win a row that's already running.
    """
    started_at = datetime.now(tz=UTC).isoformat()
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        row = conn.execute(
            """
            UPDATE pgs_compute_tasks
            SET status = 'running', started_at = ?
            WHERE task_id = (
                SELECT task_id FROM pgs_compute_tasks
                WHERE status = 'queued'
                ORDER BY requested_at ASC
                LIMIT 1
            )
            AND status = 'queued'
            RETURNING task_id, pgs_id, trait_label, rationale, requested_for_question
            """,
            [started_at],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return PgsComputeTaskFullRow(
        task_id=row[0],
        pgs_id=row[1],
        trait_label=row[2],
        rationale=row[3],
        requested_for_question=row[4],
    )


def _mark_done(db_path: Path, task_id: str) -> None:
    """Transition a running row to done with ``completed_at`` stamped."""
    completed_at = datetime.now(tz=UTC).isoformat()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE pgs_compute_tasks SET status='done', completed_at=? WHERE task_id=?",
            [completed_at, task_id],
        )
        conn.commit()
    finally:
        conn.close()


def _mark_failed(db_path: Path, task_id: str, error: str) -> None:
    """Transition a row to failed with ``error`` + ``completed_at`` stamped."""
    completed_at = datetime.now(tz=UTC).isoformat()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE pgs_compute_tasks SET status='failed', error=?, completed_at=? WHERE task_id=?",
            [error, completed_at, task_id],
        )
        conn.commit()
    finally:
        conn.close()


async def _noop_compute_fn(_task: PgsComputeTaskFullRow) -> None:
    """Phase 3 stub. Phase 4 replaces with ``compute_prs_with_coverage_fill(...)``."""
    await asyncio.sleep(0)


async def _dispatch_compute(task: PgsComputeTaskFullRow) -> None:
    """Indirection so :func:`monkeypatch.setattr` on ``_noop_compute_fn`` takes effect.

    The lifespan binds the worker's ``compute_fn`` to this dispatcher; the
    dispatcher re-resolves ``_noop_compute_fn`` from module globals on each
    call. Without this indirection, the worker would capture the function
    object at task-spawn time and tests couldn't swap in a stub after the
    app is built.
    """
    await _noop_compute_fn(task)


async def pgs_compute_worker_loop(
    db_path: Path,
    *,
    compute_enabled_fn: Callable[[], bool] = _resolve_compute_enabled,
    compute_fn: Callable[[PgsComputeTaskFullRow], Awaitable[None]] = _dispatch_compute,
    poll_interval_s: float | None = None,
) -> None:
    """Background worker loop. Polls + drains the queue, one task at a time.

    Args:
        db_path: pgs_compute_tasks.sqlite location.
        compute_enabled_fn: re-evaluated on each tick so kill-switch flips
            take effect immediately.
        compute_fn: per-task compute callable. Phase 3 ships
            :func:`_dispatch_compute` (which calls :func:`_noop_compute_fn`);
            Phase 4 binds the real compute via the lifespan.
        poll_interval_s: tick interval. None → read from env via
            :func:`_poll_interval_s`.

    Concurrency cap = 1 in-flight via a per-loop :class:`asyncio.Lock`.
    The lock is created here (not module-level) so each app's loop binds
    cleanly to its own event loop — module-level locks across multiple
    TestClient sessions would bind to a stale loop after the first test.
    """
    if poll_interval_s is None:
        poll_interval_s = _poll_interval_s()
    lock = asyncio.Lock()

    while True:
        try:
            async with lock:
                if not compute_enabled_fn():
                    # Kill-switch off: claim-then-fail so the agent's
                    # polling surfaces the rejection promptly instead of
                    # the row sitting at `queued` forever.
                    claimed = _atomic_claim_one(db_path)
                    if claimed is not None:
                        _mark_failed(db_path, claimed.task_id, "compute_path_disabled")
                else:
                    claimed = _atomic_claim_one(db_path)
                    if claimed is not None:
                        try:
                            await compute_fn(claimed)
                            _mark_done(db_path, claimed.task_id)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _mark_failed(
                                db_path,
                                claimed.task_id,
                                f"worker_unexpected_error:{type(exc).__name__}",
                            )
                            _LOG.exception(
                                "PGS compute worker failed task %s",
                                claimed.task_id,
                            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let the loop die — log + retry on the next tick.
            _LOG.exception("PGS compute worker loop tick raised")
        await asyncio.sleep(poll_interval_s)


@contextlib.asynccontextmanager
async def pgs_compute_worker_lifespan(
    db_path: Path,
) -> AsyncIterator[asyncio.Task[None]]:
    """Spawn the worker for the duration of the context, cancel on exit.

    Used by the host service's FastAPI lifespan hook. Tests construct the
    app via :class:`TestClient` whose ``__enter__`` runs the lifespan
    startup + ``__exit__`` runs the shutdown.
    """
    worker_task = asyncio.create_task(
        pgs_compute_worker_loop(db_path), name="pgs_compute_worker"
    )
    try:
        yield worker_task
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


__all__ = [
    "PgsComputeTaskFullRow",
    "PgsComputeTaskRow",
    "PgsTaskStatus",
    "create_pgs_compute_tasks_db_if_missing",
    "enqueue_pgs_compute_task",
    "pgs_compute_worker_lifespan",
    "pgs_compute_worker_loop",
    "query_pgs_compute_task_status",
]

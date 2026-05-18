"""Async orchestrator for agent-triggered PRS compute (Phase 6 Slice E v2).

E.1 ships the stubbed pieces: the `pgs_compute_tasks.sqlite` schema +
`enqueue_pgs_compute_task` + `query_pgs_compute_task_status`. Sub-slice E.3
fills in the background worker loop, the concurrency cap enforcement, and
the kill-switch.

The task DB lives at `derived/<run-id>/pgs_compute_tasks.sqlite` (sibling
of `variants.duckdb`) rather than as a table inside `variants.duckdb`
because the lifecycle is different: `pgs_scores` is authoritative + lives
with the run; the task DB is operational + may want to be cleared without
touching the run's derived store. Status enum per the v2 slice plan:
``queued | running | done | failed``. The `failed` status carries an
``error`` column; one specific failure mode is ``compute_path_disabled``
(kill-switch on).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

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


__all__ = [
    "PgsComputeTaskRow",
    "PgsTaskStatus",
    "create_pgs_compute_tasks_db_if_missing",
    "enqueue_pgs_compute_task",
    "query_pgs_compute_task_status",
]

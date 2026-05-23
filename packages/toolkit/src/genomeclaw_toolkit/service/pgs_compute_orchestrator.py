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
import functools
import logging
import os
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from genomeclaw_toolkit.prep._paths import DooDPathError, as_sibling_mountable
from genomeclaw_toolkit.prep._pgs_qc import PRSDeclineError
from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill
from genomeclaw_toolkit.prep.fetch import PgsScorefileUnfetchableError, fetch_pgs_scorefile
from genomeclaw_toolkit.prep.pgs import (
    PgsReferenceMissingError,
    PgsRow,
    compute_pgs,  # noqa: F401 -- re-export shape for symmetry with worker imports
    stamp_pgs_row,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path

    from genomeclaw_toolkit.service.pgs_compute_config import PrsComputeConfig

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


def _stale_running_window_s() -> int:
    """Window (seconds) past which a ``running`` row is considered stale.

    Default 1 hour. A warm-cache PRS compute completes in ≤30 min; a
    cold-cache compute can take ≤2 h. The 1 h default sits above the
    warm-cache budget + below the cold-cache budget. Operators staging
    a fresh deployment may want to bump to 4 h (14400 s) for the first
    cold-cache compute.
    """
    return int(os.environ.get("GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S", "3600"))


def cleanup_stale_running_tasks(
    db_path: Path, *, window_s: int | None = None
) -> list[str]:
    """Transition every ``running`` row older than the window to ``failed``.

    Runs once at app startup before the worker loop spawns. The error
    string is ``worker_restart:stale_running`` so the agent's
    ``/v1/pgs/compute/{task_id}`` polling surfaces a clear next step
    rather than the row sitting at ``running`` indefinitely after an
    unclean shutdown.

    Returns the list of cleaned ``task_id`` strings (for logging at the
    caller side; the function emits WARNING records itself for each
    transitioned row so an operator's log tail sees them).
    """
    if window_s is None:
        window_s = _stale_running_window_s()
    cutoff = (datetime.now(tz=UTC) - timedelta(seconds=window_s)).isoformat()
    completed_at = datetime.now(tz=UTC).isoformat()

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        rows = conn.execute(
            """
            UPDATE pgs_compute_tasks
            SET status = 'failed',
                error = 'worker_restart:stale_running',
                completed_at = ?
            WHERE status = 'running' AND started_at < ?
            RETURNING task_id, pgs_id
            """,
            [completed_at, cutoff],
        ).fetchall()
    finally:
        conn.close()

    for task_id, pgs_id in rows:
        _LOG.warning(
            "PGS compute worker found stale running task; transitioning to failed",
            extra={
                "task_id": task_id,
                "pgs_id": pgs_id,
                "transition": "stale_running_to_failed",
            },
        )
    return [r[0] for r in rows]


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
    """Phase 3 stub. Phase 4 wires the real path through :func:`_real_compute_fn`."""
    await asyncio.sleep(0)


async def _dispatch_compute(task: PgsComputeTaskFullRow) -> None:
    """Indirection so :func:`monkeypatch.setattr` on ``_noop_compute_fn`` takes effect.

    The Phase 3 lifespan binds the worker's ``compute_fn`` to this
    dispatcher when no PRS config is available; Phase 4's lifespan binds
    :func:`_real_compute_fn` instead. The dispatcher re-resolves
    ``_noop_compute_fn`` from module globals on each call so tests can
    swap in a stub after the app is built.
    """
    await _noop_compute_fn(task)


class PgsScorefileMissingError(FileNotFoundError):
    """The requested PGS Catalog scorefile isn't pre-staged.

    Phase 4 surface. The worker fails the task with
    ``scorefile_missing:<pgs_id>`` so the agent's polling surfaces a clear
    next step (operator should run
    ``genomeclaw refs fetch --source pgs_scorefile --pgs-id <pgs_id>``).

    Phase 2 (worker-self-sufficient-compute): :func:`_ensure_scorefile_staged`
    catches this error and auto-fetches the scorefile before re-raising or
    returning the path. If the kill-switch is off, it propagates directly
    without touching the network (INV-P001).
    """

    def __init__(self, pgs_id: str) -> None:
        """Build the error with the missing PGS Catalog ID attached for error mapping."""
        super().__init__(f"scorefile for {pgs_id} not pre-staged")
        self.pgs_id = pgs_id


class DegenerateResultError(RuntimeError):
    """INV-R002 guard: refuse to cache a degenerate PRS result.

    A row with ``percentile_in_user_ancestry is None`` AND ``raw_score is None``
    has no usable signal; persisting it would mislead the agent into
    treating an empty cell as an authoritative result.
    """

    def __init__(self, detail: str) -> None:
        """Build the error with the detail string for ``failed:degenerate_result:<detail>``."""
        super().__init__(detail)
        self.detail = detail


def _is_degenerate(row: PgsRow) -> bool:
    """INV-R002 predicate: True when the row carries no usable signal."""
    return row.percentile_in_user_ancestry is None and row.raw_score is None


def _structured_error(exc: Exception) -> str:
    """Map a compute exception to the ``failed:<class>:<detail>`` shape.

    Known failure modes return a stable, parseable string the agent can
    branch on. Unknown exceptions fall through to
    ``worker_unexpected_error:<ExceptionClass>``.
    """
    if isinstance(exc, PgsScorefileMissingError):
        return f"scorefile_missing:{exc.pgs_id}"
    if isinstance(exc, PgsScorefileUnfetchableError):
        return f"scorefile_unfetchable:{exc.pgs_id}:{exc.reason}"
    if isinstance(exc, subprocess.CalledProcessError):
        return f"pgsc_calc_failed:rc={exc.returncode}"
    if isinstance(exc, DooDPathError):
        # Surface a short detail rather than the full multi-line hint message.
        first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return f"dood_path_error:{first_line}"
    if isinstance(exc, PRSDeclineError):
        return f"prs_decline:{exc.reason.value}"
    if isinstance(exc, DegenerateResultError):
        return f"degenerate_result:{exc.detail}"
    if isinstance(exc, PgsReferenceMissingError):
        return f"pgs_reference_missing:{exc!s}"
    return f"worker_unexpected_error:{type(exc).__name__}"


def _resolve_scorefile_path(scorefile_root: Path, pgs_id: str) -> Path:
    """Resolve the pre-staged scorefile path; raise if absent.

    The canonical PGS-Catalog scorefile layout (per :mod:`prep.fetch`,
    :mod:`prep.doctor`, and ``bin/genomeclaw-prs-smoke``) is:

        ``<scorefile_root>/<pgs_id>/<pgs_id>_hmPOS_GRCh38.txt.gz``

    The harmonised-positions (``_hmPOS_``) GRCh38 build is what
    ``compute_prs_with_coverage_fill`` expects. The earlier flat-layout
    fallback (``<scorefile_root>/<pgs_id>.txt.gz``) is also accepted for
    backwards-compat with operators who staged scorefiles by hand against
    an older convention.
    """
    canonical = scorefile_root / pgs_id / f"{pgs_id}_hmPOS_GRCh38.txt.gz"
    if canonical.exists():
        return canonical
    flat_fallback = scorefile_root / f"{pgs_id}.txt.gz"
    if flat_fallback.exists():
        return flat_fallback
    raise PgsScorefileMissingError(pgs_id)


async def _ensure_scorefile_staged(
    scorefile_root: Path,
    pgs_id: str,
    *,
    compute_enabled_fn: Callable[[], bool],
) -> Path:
    """Resolve the scorefile path, auto-fetching from PGS Catalog if absent.

    If the canonical-layout file already exists, returns immediately (no
    network call). If it's missing and the kill-switch is on, catches the
    :class:`PgsScorefileMissingError` and auto-fetches from PGS Catalog via
    :func:`~genomeclaw_toolkit.prep.fetch.fetch_pgs_scorefile` (run on the
    default :class:`~concurrent.futures.ThreadPoolExecutor` since the fetch
    is synchronous + I/O-bound).

    Kill-switch gate (INV-P001): when ``compute_enabled_fn()`` returns
    ``False``, propagates :class:`PgsScorefileMissingError` without touching
    the network. No PGS Catalog egress occurs under the kill-switch.

    Args:
        scorefile_root: Parent directory containing the canonical
            ``<pgs_id>/<pgs_id>_hmPOS_GRCh38.txt.gz`` layout.
        pgs_id: PGS Catalog ID to resolve.
        compute_enabled_fn: Kill-switch predicate; re-evaluated at
            fetch-decision time so mid-run kill-switch changes are honoured.

    Returns:
        Absolute :class:`~pathlib.Path` to the staged scorefile.

    Raises:
        PgsScorefileMissingError: Kill-switch is off AND the file is missing.
        PgsScorefileUnfetchableError: Fetch attempted but PGS Catalog
            returned 404 or exhausted retries on 5xx.
    """
    try:
        return _resolve_scorefile_path(scorefile_root, pgs_id)
    except PgsScorefileMissingError:
        if not compute_enabled_fn():
            # Kill-switch off — propagate without egress (INV-P001).
            raise
        _LOG.info(
            "Auto-fetching PGS scorefile from PGS Catalog",
            extra={"transition": "auto_fetch_scorefile_started", "pgs_id": pgs_id},
        )
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(
            None,
            functools.partial(fetch_pgs_scorefile, pgs_id, scorefile_root),
        )
        _LOG.info(
            "Auto-fetched PGS scorefile",
            extra={
                "transition": "auto_fetch_scorefile_done",
                "pgs_id": pgs_id,
                "bytes": path.stat().st_size,
            },
        )
        return path


async def _real_compute_fn(
    task: PgsComputeTaskFullRow,
    *,
    config: PrsComputeConfig,
    run_dir: Path,
    compute_enabled_fn: Callable[[], bool] = _resolve_compute_enabled,
) -> None:
    """Run the real PRS compute + persist the result row.

    The blocking compute runs via :meth:`asyncio.AbstractEventLoop.run_in_executor`
    on the default ThreadPoolExecutor — the concurrency cap of 1 (held in
    the worker loop's :class:`asyncio.Lock`) means the ThreadPool's size
    is irrelevant for correctness. Errors propagate as exceptions; the
    worker loop maps them to ``failed:<class>:<detail>`` via
    :func:`_structured_error`.

    Phase 2 (worker-self-sufficient-compute): :func:`_ensure_scorefile_staged`
    catches missing scorefiles and auto-fetches from PGS Catalog when the
    kill-switch is on. The ``compute_enabled_fn`` kwarg is bound via
    :func:`functools.partial` in ``app.py``'s lifespan so the kill-switch
    re-evaluation works in the real service path.
    """
    scorefile_path = await _ensure_scorefile_staged(
        config.scorefile_root,
        task.pgs_id,
        compute_enabled_fn=compute_enabled_fn,
    )

    loop = asyncio.get_running_loop()
    pgs_row: PgsRow = await loop.run_in_executor(
        None,
        functools.partial(
            compute_prs_with_coverage_fill,
            sample_id=config.sample_id,
            cram_path=config.cram_path,
            sites_tsv=config.sites_tsv,
            alleles_tsv=config.alleles_tsv,
            scorefile_path=scorefile_path,
            fasta=config.fasta,
            panel_version=config.panel_version,
            reference_root=as_sibling_mountable(config.reference_root),
            output_root=run_dir,
            work_dir=as_sibling_mountable(config.work_dir_root),
            agent_choice_rationale=task.rationale,
            requested_for_question=task.requested_for_question,
            trait_label=task.trait_label,
        ),
    )

    if _is_degenerate(pgs_row):
        raise DegenerateResultError(
            f"zero_overlap:percentile=None,raw_score=None for {task.pgs_id}"
        )

    # The persistence step runs on the event loop; it's a single DuckDB
    # write that returns in milliseconds. No executor offload needed.
    stamp_pgs_row(run_dir, pgs_row, vcf=config.cram_path)


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
                        _LOG.info(
                            "PGS compute task rejected: kill-switch off",
                            extra={
                                "task_id": claimed.task_id,
                                "pgs_id": claimed.pgs_id,
                                "transition": "queued_to_failed_compute_path_disabled",
                            },
                        )
                else:
                    claimed = _atomic_claim_one(db_path)
                    if claimed is not None:
                        _LOG.info(
                            "PGS compute task claimed",
                            extra={
                                "task_id": claimed.task_id,
                                "pgs_id": claimed.pgs_id,
                                "transition": "queued_to_running",
                            },
                        )
                        try:
                            await compute_fn(claimed)
                            _mark_done(db_path, claimed.task_id)
                            _LOG.info(
                                "PGS compute task completed",
                                extra={
                                    "task_id": claimed.task_id,
                                    "pgs_id": claimed.pgs_id,
                                    "transition": "running_to_done",
                                },
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            err = _structured_error(exc)
                            _mark_failed(db_path, claimed.task_id, err)
                            _LOG.info(
                                "PGS compute task failed",
                                extra={
                                    "task_id": claimed.task_id,
                                    "pgs_id": claimed.pgs_id,
                                    "transition": "running_to_failed",
                                    "error": err,
                                },
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
    *,
    compute_fn: Callable[[PgsComputeTaskFullRow], Awaitable[None]] | None = None,
) -> AsyncIterator[asyncio.Task[None]]:
    """Spawn the worker for the duration of the context, cancel on exit.

    Used by the host service's FastAPI lifespan hook. Tests construct the
    app via :class:`TestClient` whose ``__enter__`` runs the lifespan
    startup + ``__exit__`` runs the shutdown.

    ``compute_fn`` defaults to :func:`_dispatch_compute` (the Phase 3
    no-op indirection) when the caller hasn't supplied a real compute
    binding. Phase 4's app lifespan binds ``functools.partial(_real_compute_fn,
    config=..., run_dir=...)`` when the sidecar resolves cleanly.
    """
    if compute_fn is None:
        compute_fn = _dispatch_compute
    worker_task = asyncio.create_task(
        pgs_compute_worker_loop(db_path, compute_fn=compute_fn),
        name="pgs_compute_worker",
    )
    try:
        yield worker_task
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


__all__ = [
    "DegenerateResultError",
    "PgsComputeTaskFullRow",
    "PgsComputeTaskRow",
    "PgsScorefileMissingError",
    "PgsTaskStatus",
    "cleanup_stale_running_tasks",
    "create_pgs_compute_tasks_db_if_missing",
    "enqueue_pgs_compute_task",
    "pgs_compute_worker_lifespan",
    "pgs_compute_worker_loop",
    "query_pgs_compute_task_status",
]

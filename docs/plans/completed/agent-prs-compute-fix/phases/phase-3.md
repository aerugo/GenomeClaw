# Phase 3 — Worker skeleton + queue management

**Status**: **Complete**
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Stand up the E.3 background worker as an in-process asyncio task spawned at FastAPI startup. This phase delivers the **bones** of the worker: it polls the `pgs_compute_tasks.sqlite` queue, atomically claims one `queued` row at a time, transitions it through `running → done` (or `failed`), and respects the `pgs.compute_enabled` kill-switch. The "compute" itself is a no-op `await asyncio.sleep(0)` in this phase — real `compute_prs_with_coverage_fill(...)` integration lands in Phase 4. The split is deliberate: queue management is concurrency-sensitive code that benefits from being verified in isolation before the heavy compute path is layered on top.

## Scope Boundaries

- **In scope**:
  - FastAPI `lifespan` hook that spawns + cancels the worker task.
  - Polling loop (configurable interval; default 1s — short so tests don't hang on a sleeper).
  - Atomic `queued → running` claim via SQLite `UPDATE ... RETURNING`.
  - Concurrency cap = 1 in-flight, enforced via a module-level `asyncio.Lock`.
  - Kill-switch check (`pgs.compute_enabled`) at three points: app startup, before each claim, and at the start of each task's execution.
  - No-op compute that transitions `running → done` after `await asyncio.sleep(0)`.
  - Tests asserting all of the above without touching `compute_prs_with_coverage_fill`.
- **Out of scope** (deferred to later phases):
  - Real compute via `compute_prs_with_coverage_fill(...)` — Phase 4.
  - `pgs_scores` + `findings` persistence — Phase 4.
  - INV-R002 degenerate-result guard — Phase 4.
  - Structured error mapping (`scorefile_missing:PGS004606`, `pgsc_calc_failed:rc=1`, etc.) — Phase 4.
  - Stale-running cleanup at startup + INFO logging — Phase 5.
  - End-to-end agent live test — Phase 6.

## Invariants Enforced in This Phase

- **INV-A003** (Agent-Curated Compute Provenance) — the worker carries `rationale` + `requested_for_question` from the task row through to the result-stamping step. Phase 3's no-op compute doesn't stamp a row yet, but the field plumbing is wired + a test asserts that the worker reads both columns from the task row when it claims a task.
- **INV-P001** (Privacy Default) — Phase 3's worker performs zero network I/O. A test runs the full claim → no-op compute → done cycle with `monkeypatch` that fails the test if any outbound socket call happens.
- **No INV-T001 risk** — Phase 3 doesn't invoke pgsc_calc; the tool-conventions surface is untouched until Phase 4.

---

## TDD Steps

### Step 3.1 — RED: Write failing tests

New file: [packages/toolkit/tests/integration/test_pgs_compute_worker_skeleton.py](../../../packages/toolkit/tests/integration/test_pgs_compute_worker_skeleton.py).

All tests use `pytest.mark.asyncio` + a `TestClient`-spawned app instance so the worker actually runs. The polling interval is overridden to ~50 ms via a module-level `_WORKER_POLL_INTERVAL_S` constant or an env var (`GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S`) so tests don't hang on a real 1 s sleep.

**Test cases**:

1. `test_worker_drains_queued_task_to_done` — enqueue one `queued` row via the host route → wait ≤2 s → assert the row transitions through `running` to `done` with `started_at` + `completed_at` populated.
2. `test_worker_atomic_claim_prevents_double_processing` — manually launch the worker loop **twice** (two `asyncio.create_task` invocations against the same DB), enqueue a single row, wait for completion. Assert exactly one of the two workers claimed it (the other saw `status='running'` and skipped). Verifies the `UPDATE ... WHERE status='queued' RETURNING ...` semantics.
3. `test_worker_concurrency_cap_one_in_flight` — enqueue 3 rows; instrument the no-op compute to record `(start_time, end_time)` per row + a global `max_concurrent` gauge. Wait for all 3 to complete. Assert `max_concurrent == 1` (the asyncio.Lock serialises tasks).
4. `test_worker_respects_kill_switch_at_startup` — start the app with `pgs.compute_enabled=false` in config → enqueue → assert task transitions to `status='failed'` with `error='compute_path_disabled'` instead of `done`. Worker should claim + immediately fail (not silently leave the row at `queued`, so the agent's polling surfaces the error promptly).
5. `test_worker_respects_kill_switch_flip_mid_run` — start with `pgs.compute_enabled=true`, enqueue → flip config to `false` via `cache.reload(...)` (SIGHUP path) → enqueue a second row → assert second row fails with `compute_path_disabled` while the first row (already in flight) is unaffected.
6. `test_invA003_worker_reads_rationale_and_requested_for_question` — enqueue with distinctive rationale + question text; capture the worker's claimed-task dict (via a test hook or by reading the row mid-running with a slowed-down no-op compute). Assert both fields are visible to the worker as it processes the task.
7. `test_invP001_worker_makes_no_outbound_calls` — patch `socket.socket` to raise on `.connect()` → enqueue 2 rows → wait for both `done` → assert no exception raised (i.e. the worker made zero outbound socket calls).
8. `test_worker_cleans_up_on_app_shutdown` — spin up app, enqueue 1 row, immediately shut the app down (exit the `TestClient` context manager). Assert the worker task was cancelled cleanly (no warnings, no leaked thread); the in-flight task row state is left in whatever state it was in (Phase 5 handles the stale-running cleanup; Phase 3 just asserts no crash on shutdown).

**Sketch**:

```python
import asyncio
import pytest
from fastapi.testclient import TestClient
from genomeclaw_toolkit.service.app import create_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    enqueue_pgs_compute_task,
    query_pgs_compute_task_status,
)

@pytest.mark.asyncio
async def test_worker_drains_queued_task_to_done(tmp_path, monkeypatch):
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.05")
    # Arrange: a derived_root with CURRENT pointing at a run-dir with
    # a minimal variants.duckdb (Phase 4 cares about CRAM/refs; Phase 3
    # only needs the SQLite task DB).
    derived_root = _make_minimal_derived_root(tmp_path)
    app = create_app(derived_root=derived_root)

    with TestClient(app) as client:
        # Enqueue via the host route — exercises the full path.
        resp = client.post("/v1/pgs/compute", json={
            "pgs_id": "PGS_TEST",
            "trait_label": "test",
            "rationale": "phase-3 no-op test",
            "requested_for_question": "phase-3 test",
        })
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # Wait up to 2s for the worker to drain it.
        async def _drained():
            for _ in range(40):
                r = client.get(f"/v1/pgs/compute/{task_id}")
                if r.json()["status"] in ("done", "failed"):
                    return r.json()
                await asyncio.sleep(0.05)
            return r.json()

        final = await _drained()
        assert final["status"] == "done"
        assert final["error"] is None
```

After authoring, run the suite — **all 8 tests should fail for the right reason** (no worker exists yet; tasks stay at `queued`). Paste the failure output into `work-notes.md`.

### Step 3.2 — GREEN: Minimal implementation

Implementation lands in [packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py](../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py) (extending the existing module) + a small surface on [packages/toolkit/src/genomeclaw_toolkit/service/app.py](../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) (the lifespan hook).

**Module-level additions to `pgs_compute_orchestrator.py`**:

```python
import asyncio
import os
import logging
from collections.abc import Awaitable, Callable

_LOG = logging.getLogger(__name__)
_WORKER_LOCK = asyncio.Lock()  # Concurrency cap = 1 in-flight.

def _poll_interval_s() -> float:
    return float(os.environ.get("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "1.0"))

def _atomic_claim_one(db_path: Path) -> PgsComputeTaskFullRow | None:
    """Atomically transition one queued row to running; return it, or None.

    Uses SQLite UPDATE ... RETURNING (3.35+). The WHERE clause includes
    `status='queued'` so concurrent claims see at most one winner.
    """
    started_at = datetime.now(tz=UTC).isoformat()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.isolation_level = None  # autocommit; RETURNING semantics need it
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
    """Transition running → done with completed_at."""
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
    """Transition running → failed with error message + completed_at."""
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

async def pgs_compute_worker_loop(
    db_path: Path,
    *,
    compute_enabled_fn: Callable[[], bool],
    compute_fn: Callable[[PgsComputeTaskFullRow], Awaitable[None]],
) -> None:
    """Background worker loop. Polls + drains the queue, one task at a time.

    Args:
        db_path: pgs_compute_tasks.sqlite location.
        compute_enabled_fn: re-evaluated on each loop tick so kill-switch
            flips take effect immediately.
        compute_fn: the per-task compute call. Phase 3 passes a no-op;
            Phase 4 wires the real compute_prs_with_coverage_fill(...).
    """
    while True:
        try:
            async with _WORKER_LOCK:
                if not compute_enabled_fn():
                    # Kill-switch is off; claim any queued row + fail it
                    # immediately so the agent's polling sees the rejection.
                    claimed = _atomic_claim_one(db_path)
                    if claimed is not None:
                        _mark_failed(db_path, claimed.task_id, "compute_path_disabled")
                else:
                    claimed = _atomic_claim_one(db_path)
                    if claimed is not None:
                        try:
                            await compute_fn(claimed)
                            _mark_done(db_path, claimed.task_id)
                        except Exception as exc:  # Phase 4 maps to structured errors
                            _mark_failed(db_path, claimed.task_id, f"worker_unexpected_error:{type(exc).__name__}")
                            _LOG.exception("PGS compute worker failed task %s", claimed.task_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # Defensive — never let the loop die.
            _LOG.exception("PGS compute worker loop tick raised")
        await asyncio.sleep(_poll_interval_s())

async def _noop_compute_fn(_task: PgsComputeTaskFullRow) -> None:
    """Phase 3 stub. Phase 4 replaces with the real compute."""
    await asyncio.sleep(0)
```

**`PgsComputeTaskFullRow` dataclass** — new dataclass that carries the columns the worker reads (vs the existing `PgsComputeTaskRow` which is the status-query projection). Two distinct shapes is cleaner than one inflating dataclass.

**FastAPI lifespan hook in `app.py`**:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app: FastAPI):
    worker_task: asyncio.Task[None] | None = None
    if cache.active is not None:
        db_path = cache.active.run_dir / "pgs_compute_tasks.sqlite"
        create_pgs_compute_tasks_db_if_missing(db_path)
        worker_task = asyncio.create_task(
            pgs_compute_worker_loop(
                db_path,
                compute_enabled_fn=lambda: _resolve_compute_enabled(cache),
                compute_fn=_noop_compute_fn,  # Phase 4 swaps this
            ),
            name="pgs_compute_worker",
        )
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

app = FastAPI(..., lifespan=_lifespan)
```

**Kill-switch resolution**: `_resolve_compute_enabled(cache)` reads the active run's `config.json` (or env override). For Phase 3, recommend a thin helper that reads `cache.active.config.get("pgs.compute_enabled", True)` — defaults true so existing test fixtures don't break. Phase 4 may refine.

### Step 3.3 — REFACTOR

With tests green:

- Extract the three SQL helpers (`_atomic_claim_one` / `_mark_done` / `_mark_failed`) into a `_PgsTaskDao` if the rule of three triggers (Phase 4 + Phase 5 add `mark_failed_with_structured_error` + `cleanup_stale_running`, so this is likely).
- Tighten the `compute_fn` callable signature once Phase 4 lands; for Phase 3, keep `Callable[[PgsComputeTaskFullRow], Awaitable[None]]` minimal.
- Add a one-line docstring on the kill-switch loop branch explaining *why* it claims-then-fails rather than skipping (so the agent's `/v1/pgs/compute/{task_id}` polling surfaces the rejection promptly — not just `queued` forever).
- No comments on the SQL — `UPDATE ... RETURNING` is the only non-obvious bit and the docstring on `_atomic_claim_one` covers it.

---

## Implementation Details

### Worker process model

In-process asyncio task spawned by FastAPI's `lifespan` context manager. The task is `cancel()`'d on app shutdown. No external worker process; no IPC.

### Polling interval

Default 1 s; overridable via `GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S` env var. Tests use 50 ms so the suite doesn't hang on a sleeper. A 1 s default in production is plenty — PRS computes take minutes, so a 1 s polling jitter on `queued → running` is invisible to the agent.

### Atomicity

SQLite's `UPDATE ... RETURNING` (3.35+) makes the claim atomic against concurrent workers. The single-row LIMIT + `status='queued'` WHERE clause ensures at most one winner. Python 3.11 ships SQLite ≥3.40 on macOS + Linux wheels; no version guard needed.

### Schema / Provenance Impact

No schema changes. The existing `pgs_compute_tasks` table has all the columns needed (`status`, `error`, `started_at`, `completed_at`).

### Edge Cases to Handle

- **Empty queue**: `_atomic_claim_one` returns `None`; the loop falls through to the sleep.
- **No active run on app startup**: the lifespan hook skips spawning the worker (`cache.active is None`). The host service still serves `/v1/health` with the 503 "no active run" response.
- **Worker crash mid-task**: caught by the `except Exception` in the loop; task is marked `failed:worker_unexpected_error:<ExceptionClass>`. Phase 4 refines the error-mapping.
- **App shutdown mid-task**: the in-flight task remains at `status='running'` until the next worker startup. Phase 5 adds the stale-running cleanup that transitions it to `failed:worker_restart`.

### Error Handling

- Phase 3 marks unexpected exceptions as `failed:worker_unexpected_error:<ExceptionClass>`. Phase 4 refines this into structured `failed:<class>:<message>` shapes for known compute errors (`scorefile_missing`, `pgsc_calc_failed`, `zero_overlap`).
- The outer `except Exception` in the loop tick is defensive — even if `_atomic_claim_one` raises (e.g. transient SQLite lock), the loop survives + retries on the next tick.

### Privacy / Egress Notes

- Worker performs zero outbound I/O. Phase 3's `_noop_compute_fn` is `await asyncio.sleep(0)`; no network calls.
- Test #7 (`test_invP001_worker_makes_no_outbound_calls`) patches `socket.socket.connect` to raise; any attempted outbound call would fail the test.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | MODIFY | Add `pgs_compute_worker_loop`, `PgsComputeTaskFullRow`, `_atomic_claim_one`, `_mark_done`, `_mark_failed`, `_noop_compute_fn` |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Add `lifespan` context manager that spawns + cancels the worker task |
| `packages/toolkit/tests/integration/test_pgs_compute_worker_skeleton.py` | CREATE | The 8 test cases listed in Step 3.1 |

No plugin / sandbox changes — the worker is host-side only; the plugin tools (`genomeclaw_pgs_compute*`) already work against the routes Phase 3 leaves unchanged.

---

## Verification

```bash
cd packages/toolkit

# Phase 3's new test file
uv run pytest tests/integration/test_pgs_compute_worker_skeleton.py -v
# Expect: 8/8 PASS (all RED at start of phase; GREEN after Step 3.2)

# Regression sweep on the host service tests
uv run pytest tests/integration/test_service_pgs.py tests/integration/test_pgs_compute_request_validation.py -v
# Expect: still GREEN (Phase 2's validation tests + the existing E.1 route tests).

# Full toolkit suite
uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: no regression.

# Type-check (mypy on touched files)
uv run mypy src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py src/genomeclaw_toolkit/service/app.py

# Lint
uv run ruff check \
    src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
    src/genomeclaw_toolkit/service/app.py \
    tests/integration/test_pgs_compute_worker_skeleton.py
```

---

## Completion Criteria

- [ ] All 8 listed test cases pass.
- [ ] `test_invA003_worker_reads_rationale_and_requested_for_question` cites INV-A003 in its name + docstring.
- [ ] `test_invP001_worker_makes_no_outbound_calls` cites INV-P001 in its name + docstring.
- [ ] The full toolkit suite (`tests/{unit,integration,invariants,provenance,privacy}`) stays green.
- [ ] mypy clean on `pgs_compute_orchestrator.py` + `app.py`.
- [ ] ruff clean on touched files.
- [ ] Worker task is cancelled cleanly on app shutdown (no leaked-task warnings under `pytest -W error::pytest.PytestUnraisableExceptionWarning`).
- [ ] `work-notes.md` updated with RED output, the design choice of "claim-then-fail" vs "skip" for kill-switch-off, and a note on the SQLite `RETURNING` availability check.
- [ ] Phase status updated in `development-plan.md`.

## Next

[Phase 4 — Worker compute integration](phase-4.md).

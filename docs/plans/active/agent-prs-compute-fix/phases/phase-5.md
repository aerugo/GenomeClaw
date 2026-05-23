# Phase 5 — Crash recovery + observability

**Status**: **Complete**
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Make the worker **robust enough to run unattended on a personal-host deployment**. Two surfaces:

1. **Crash recovery** — if the host service is killed (Ctrl+C, OS reboot, OOM) mid-compute, the in-flight task is left at `status='running'` indefinitely. Phase 5 adds a startup-time cleanup that transitions any stale-running row (older than a configurable window, default 1 hour) to `failed:worker_restart:stale_running`. This ensures the agent's polling surfaces the failure promptly rather than hanging forever.
2. **Observability** — INFO-level structured log lines on every status transition (`queued → running`, `running → done`, `running → failed`) include `task_id`, `pgs_id`, and the transition. The operator can `tail -f` the host service log + see exactly when compute starts + finishes + which row is in flight.

Phase 5 is the *hardening* phase. No new compute capability; just making the existing one safe to leave running.

## Scope Boundaries

- **In scope**:
  - `cleanup_stale_running_tasks(db_path, window_s)` function that runs once at FastAPI startup (before the worker loop starts polling) + transitions stale rows to `failed:worker_restart:stale_running`.
  - Configurable window via env var (`GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S`, default 3600).
  - INFO-level `logging.getLogger("genomeclaw_toolkit.service.pgs_compute_orchestrator")` lines on: claim, completion, failure, kill-switch reject, stale-running cleanup.
  - Log lines are structured (`extra={"task_id": ..., "pgs_id": ..., "transition": ...}`) so log aggregators can parse them.
  - Tests assert: stale-running cleanup transitions the right rows + leaves recent `running` rows alone; INFO log lines appear at the right transitions.
- **Out of scope** (deferred):
  - DEBUG-level per-tick polling logs (would be noisy at 1 s).
  - Prometheus / structured-metrics export — orthogonal; out of plan scope.
  - End-to-end agent live test — Phase 6.
  - Operator-facing CLI to inspect the task DB (`genomeclaw pgs tasks ls`) — nice-to-have, not in this plan.

## Invariants Enforced in This Phase

- **No new INV-xxx** introduced. Phase 5 hardens existing surfaces; the invariants Phase 4 added (INV-A003 / R001 / R002 plumbing) stay green.
- **INV-A003** indirectly preserved: stale-running cleanup writes `error='worker_restart:stale_running'` but does NOT touch `agent_choice_rationale` / `requested_for_question` (those were stamped at enqueue + travel with the row regardless of how it terminates).

---

## TDD Steps

### Step 5.1 — RED: Write failing tests

New file: `packages/toolkit/tests/integration/test_pgs_compute_worker_recovery.py`.

**Test cases**:

1. `test_stale_running_cleanup_transitions_old_rows_to_failed` — pre-seed the task DB with a `status='running'` row whose `started_at` is 2 hours ago (older than the default 1 h window) → call `cleanup_stale_running_tasks` directly → assert the row is now `status='failed'` with `error='worker_restart:stale_running'` + `completed_at` populated.
2. `test_stale_running_cleanup_leaves_recent_rows_alone` — pre-seed with a `running` row whose `started_at` is 5 minutes ago → cleanup → assert row stays at `running`. Guards against an over-aggressive cleanup window.
3. `test_stale_running_cleanup_runs_at_app_startup` — pre-seed a stale row → `TestClient(create_app(...))` enters → assert the row transitions to `failed:worker_restart:stale_running` before any new enqueue. Verifies the lifespan hook calls the cleanup before spawning the worker.
4. `test_stale_running_window_configurable_via_env` — set `GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S=10` → pre-seed a row whose `started_at` is 15 s ago → cleanup transitions it. Same row at 5 s ago → cleanup leaves it.
5. `test_log_line_on_task_claim` — capture logs via `caplog` → enqueue + drain → assert at least one INFO record matches `transition='queued_to_running'` with `task_id` + `pgs_id` in the structured fields.
6. `test_log_line_on_task_done` — assert one INFO record with `transition='running_to_done'`.
7. `test_log_line_on_task_failed` — stub compute raises → assert INFO record with `transition='running_to_failed'` AND `error=<structured_error_string>`.
8. `test_log_line_on_kill_switch_reject` — kill-switch off → enqueue → assert log record `transition='queued_to_failed_compute_path_disabled'`.
9. `test_log_line_on_stale_running_cleanup` — pre-seed stale row → startup → assert WARNING record `transition='stale_running_to_failed'` (WARN level because this indicates an unclean prior shutdown — operator might want to know).

**Sketch**:

```python
def test_stale_running_cleanup_transitions_old_rows_to_failed(tmp_path):
    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)

    # Pre-seed: a running row from 2 hours ago.
    stale_started_at = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO pgs_compute_tasks
        (task_id, pgs_id, trait_label, rationale, requested_for_question,
         status, error, requested_at, started_at, completed_at)
        VALUES ('t1', 'PGS_X', 'amd', 'r', 'q', 'running', NULL, ?, ?, NULL)
        """,
        [stale_started_at, stale_started_at],
    )
    conn.commit()
    conn.close()

    cleaned = cleanup_stale_running_tasks(db_path, window_s=3600)

    assert cleaned == ["t1"]
    row = query_pgs_compute_task_status(db_path, task_id="t1")
    assert row.status == "failed"
    assert row.error == "worker_restart:stale_running"
```

### Step 5.2 — GREEN: Minimal implementation

**`pgs_compute_orchestrator.py`** (MODIFY):

```python
def _stale_running_window_s() -> int:
    return int(os.environ.get("GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S", "3600"))


def cleanup_stale_running_tasks(db_path: Path, *, window_s: int | None = None) -> list[str]:
    """Transition any `running` row older than the window to `failed:worker_restart:stale_running`.

    Returns the list of cleaned task_ids (so the caller can log them).
    Run once at app startup, before the worker loop spawns. A row is
    "stale" if `started_at` is older than `window_s` (default 1 hour,
    overridable via GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S).
    """
    if window_s is None:
        window_s = _stale_running_window_s()
    cutoff = (datetime.now(tz=UTC) - timedelta(seconds=window_s)).isoformat()
    completed_at = datetime.now(tz=UTC).isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.isolation_level = None
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
```

**Update the worker loop's claim / done / failed paths** to emit INFO logs:

```python
async def pgs_compute_worker_loop(...):
    while True:
        try:
            async with _WORKER_LOCK:
                if not compute_enabled_fn():
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
        ...
```

**Update the lifespan hook in `app.py`** to call cleanup before spawning the worker:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI):
    worker_task = None
    if cache.active is not None:
        db_path = cache.active.run_dir / "pgs_compute_tasks.sqlite"
        create_pgs_compute_tasks_db_if_missing(db_path)
        cleaned = cleanup_stale_running_tasks(db_path)
        if cleaned:
            _LOG.warning(
                "Cleaned %d stale-running PGS compute task(s) on startup",
                len(cleaned),
                extra={"stale_task_ids": cleaned},
            )
        # ... then spawn worker as in Phase 4
```

### Step 5.3 — REFACTOR

- The five log-line emission points share a pattern (`_LOG.info("...", extra={"task_id":..., "pgs_id":..., "transition":...})`). After the rule-of-three triggers, extract `_log_transition(level, task, transition, *, **extra_fields)` helper.
- The SQL DAO helpers (`_atomic_claim_one`, `_mark_done`, `_mark_failed`, `cleanup_stale_running_tasks`) now total four. If the Phase 3 refactor deferred the `_PgsTaskDao` class, this is the phase to do it — moves all sqlite3 calls behind a single class.
- No comments added to log emission points; the `transition=` field is self-documenting.

---

## Implementation Details

### Stale-running detection algorithm

```sql
UPDATE pgs_compute_tasks
SET status='failed', error='worker_restart:stale_running', completed_at=NOW()
WHERE status='running' AND started_at < (NOW() - window_s seconds)
RETURNING task_id, pgs_id
```

Single SQL statement; atomic; returns the affected rows for logging. The `RETURNING` clause requires SQLite 3.35+ (available in Python 3.11+ shipped wheels — same as Phase 3's `_atomic_claim_one`).

### Window default — why 1 hour

Smoke v23 measured a full PRS compute (Tier 1 force-genotype + Tier 2 force-genotype + merge + pgsc_calc) at ~4h26m wall on the canonical sample for the most expensive scorefile. **But that includes the cold-cache Tier 1 build**; subsequent computes against the same sample are warm-cache + complete in ~5-20 min. Practical wall budget for a compute against a warm-cache sample is ≤30 min; against a cold-cache sample is ≤2 h.

The 1-hour default balances:
- **Too short** → kills legitimately-long warm-cache computes that hit a transient slowdown.
- **Too long** → user waits forever for the agent's polling to surface the failure after a crash.

1 hour is well above the warm-cache wall budget + below the cold-cache wall budget. The first cold-cache compute on a fresh deployment may legitimately need the env override (`GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S=14400` for 4 h) — documented in the operator notes appended in Phase 5.

### Logging surface

- Logger name: `genomeclaw_toolkit.service.pgs_compute_orchestrator`.
- Levels: INFO for all task transitions; WARNING for stale-running cleanup (signals an unclean prior shutdown).
- Structured fields via `extra={...}`: `task_id`, `pgs_id`, `transition`, `error` (when applicable).
- The host service's existing logging config (`uvicorn`'s default + any user-configured `LOG_FORMAT`) handles formatting; Phase 5 doesn't touch the logging config itself.

### Edge Cases to Handle

- **Stale row count = 0**: `cleanup_stale_running_tasks` returns `[]`; the lifespan hook's `if cleaned:` branch is skipped. No spurious "cleaned 0 tasks" log line.
- **Window = 0 or negative**: env-var parser falls back to default; defensive.
- **DB doesn't exist yet**: `cleanup_stale_running_tasks` is called after `create_pgs_compute_tasks_db_if_missing` in the lifespan hook, so the DB always exists when cleanup runs.
- **Worker crashes mid-cleanup**: cleanup is a single atomic SQL UPDATE; either all stale rows are cleaned, or none are. No partial state.
- **Long-running compute coincides with restart window**: a compute that legitimately takes >1 h gets killed mid-flight on restart. Operator notes call out the env-var override.

### Error Handling

No new error classes. The existing `worker_unexpected_error:<class>` (Phase 3) + structured-error mapping (Phase 4) covers everything; Phase 5 only adds the `worker_restart:stale_running` shape.

### Privacy / Egress Notes

No new boundaries. Log lines carry `task_id`, `pgs_id`, `transition` — none of which are sensitive (`pgs_id` is a public PGS Catalog ID; `task_id` is a UUID). No phenotype-linked content, no variant data, no sample ID in log lines (the sample ID is per-deployment + already known to the operator; surfacing it in log lines doesn't add a new boundary, but Phase 5 doesn't include it).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | MODIFY | Add `cleanup_stale_running_tasks` + INFO/WARNING log emission at all transitions |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Lifespan hook calls cleanup before spawning the worker |
| `packages/toolkit/tests/integration/test_pgs_compute_worker_recovery.py` | CREATE | 9 tests for stale-running cleanup + logging |
| `docs/reference/architecture.md` | MODIFY (light) | One-paragraph note on `prs_compute_config.json` sidecar + stale-running window env var (operator-facing) |

---

## Verification

```bash
cd packages/toolkit

uv run pytest tests/integration/test_pgs_compute_worker_recovery.py -v
# Expect: 9/9 PASS

uv run pytest tests/integration/test_pgs_compute_worker_skeleton.py tests/integration/test_pgs_compute_worker_integration.py -v
# Expect: Phases 3+4 tests still green (no regression).

uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: no regression.

uv run mypy \
  src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
  src/genomeclaw_toolkit/service/app.py

uv run ruff check \
  src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
  src/genomeclaw_toolkit/service/app.py \
  tests/integration/test_pgs_compute_worker_recovery.py
```

---

## Completion Criteria

- [ ] All 9 listed test cases pass.
- [ ] Phase 3 + Phase 4 tests stay green.
- [ ] Log lines visible during a manual host-service smoke (operator runs the service, enqueues via `curl`, observes INFO lines).
- [ ] `docs/reference/architecture.md` carries a one-paragraph operator note on the sidecar + env vars.
- [ ] mypy + ruff clean on touched files.
- [ ] Full toolkit suite green.
- [ ] `work-notes.md` updated with: window-default rationale (1 h vs alternatives), log-level rationale (INFO for normal transitions, WARNING for stale-running cleanup), and a sample log-output excerpt from the manual smoke.
- [ ] Phase status updated in `development-plan.md`.

## Next

[Phase 6 — End-to-end verification](phase-6.md).

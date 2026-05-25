# RCA: `genomeclaw_pgs_compute` ack-without-row

**Date**: 2026-05-25
**Plan**: [investigate-pgs-compute-ack-without-row](../plans/active/investigate-pgs-compute-ack-without-row/)
**Source reports**: [demo-questions-2026-05-24](genomeclaw-demo-questions-2026-05-24.md), [demo-questions-2026-05-25-verification](genomeclaw-demo-questions-2026-05-25-verification.md)

---

## Symptom

The agent's `genomeclaw_pgs_compute` tool reported `status=done` on every PRS compute attempt, but the corresponding `pgs_scores` row was never retrievable via `genomeclaw_pgs_get`. The agent's calibration discipline (`INV-A001`) correctly refused to call user risk up/down without a percentile — *"I cannot determine above- vs below-average T2D risk until the PRS result is retrievable"* — but users got a non-answer instead of a usable PRS or a usable failure explanation.

Five independent reproductions across three demo sessions (Rounds 1-3) confirmed the pattern is consistent across two scorefiles (PGS000014 LDpred T2D, PGS000334 Alzheimer's).

## Reproduction

`packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py` — deterministic, no LLM, runs in <1s. Stages a derived run **without** `prs_compute_config.json` (the operator's actual state on the affected `2026-05-24T12-52-11Z-f2dae2` run), POSTs a compute task, waits for terminal status, asserts that `status=done` is accompanied by a real `pgs_scores` row.

Pre-fix: FAIL with `assert 0 >= 1` — 0 rows in `pgs_scores` despite `done` task.
Post-fix: PASS — task transitions to `failed:prs_compute_config_missing` with a structured error the agent can paraphrase as "PRS compute is offline; the operator hasn't staged prs_compute_config.json".

## Root cause

**Hypothesis #4 confirmed**: compute genuinely didn't run, and the worker treated the no-op return as success.

Concrete chain ([orchestrator code citations are post-fix; the bug-bearing layout is on the parent commit](../../packages/toolkit/src/genomeclaw_toolkit/)):

1. **App startup** ([app.py:209-221](../../packages/toolkit/src/genomeclaw_toolkit/service/app.py)) attempts `load_prs_compute_config(run_dir)`. The operator's affected runs were ingest-only — `prs_compute_config.json` was never staged.
2. **Missing-config handler** catches `PrsComputeConfigMissingError`, logs a WARNING (*"prs_compute_config.json missing; PGS compute worker will queue + ack tasks but cannot run real compute"*), and **leaves `compute_fn = None`**.
3. `pgs_compute_worker_lifespan(db_path, compute_fn=None)` falls through to its default ([orchestrator.py:669-670](../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py)): `compute_fn = _dispatch_compute`.
4. `_dispatch_compute` ([orchestrator.py:339-348](../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py)) is `await _noop_compute_fn(task)`.
5. `_noop_compute_fn` ([orchestrator.py:334-336](../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py)) is `await asyncio.sleep(0); return`.
6. **Worker loop** ([orchestrator.py:615-625](../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py)): `await compute_fn(claimed); _mark_done(db_path, claimed.task_id)`. The `_mark_done` runs unconditionally after `compute_fn` returns without raising — so every task lands at `done` with no row written.

The kill-switch path on the adjacent branch ([orchestrator.py:589-603](../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py)) **does the right thing**: when `compute_enabled_fn() == False` it claims-then-marks-failed with `error="compute_path_disabled"`. The missing-config path lacked the equivalent gate.

### Direct evidence from the affected run

```text
Run: /Volumes/Genome_Work/genomeclaw/derived/2026-05-24T12-52-11Z-f2dae2

$ sqlite3 pgs_compute_tasks.sqlite "SELECT task_id, pgs_id, status, started_at, completed_at FROM pgs_compute_tasks"
... 11 rows, all status='done', each with completed_at within 2 SECONDS of started_at
    (a real LDpred compute for PGS000014's 6.9M variants cannot finish in 2 seconds)

$ duckdb variants.duckdb "SELECT COUNT(*) FROM pgs_scores"
0
```

11 tasks marked done, 0 rows in `pgs_scores`. The compute didn't run; the no-op was treated as success.

## Why the existing tests didn't catch it

The pre-fix test suite (`tests/integration/test_pgs_compute_worker_*.py`) covered three classes of test:

1. **Happy path**: tests that stage `prs_compute_config.json` AND monkeypatch `compute_prs_with_coverage_fill` to return a fake row. These exercise the real-compute path and pass cleanly. They do NOT exercise the missing-config path because they always stage the config.
2. **Skeleton-scaffolding tests**: tests that DON'T stage a config, relying on the noop-fallback path to verify queue/claim/mark mechanics. These pass because they treat the noop as expected scaffolding behaviour, not as a missing-config error.
3. **Recovery tests**: same — they relied on the noop fallback for happy-path setup.

So the missing-config path was never asserted to produce a `failed` status. The fix updates the skeleton + recovery tests to stage the sidecar AND monkeypatch the real compute path (`app._real_compute_fn`) instead of `_noop_compute_fn`. After the fix, the noop path is no longer reachable from production runs — the missing-config state is structurally a failure, not a no-op.

## Fix

### Diff summary

- **`packages/toolkit/src/genomeclaw_toolkit/service/app.py`** (lifespan, ~17 lines): when `PrsComputeConfigMissingError` or `PrsComputeConfigMalformedError` is caught, instead of leaving `compute_fn = None`, bind it to a closure that raises the same error. The worker's existing exception handler maps the raised error through `_structured_error()` and transitions the task to `failed` with a stable, agent-parseable `error` value.
- **`packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py::_structured_error`** (~9 lines): add mappings for `PrsComputeConfigMissingError → "prs_compute_config_missing"` and `PrsComputeConfigMalformedError → "prs_compute_config_malformed:<detail>"`. Local import to avoid a circular dependency between the orchestrator and `pgs_compute_config`.
- **`packages/toolkit/tests/integration/test_pgs_compute_worker_skeleton.py`** + **`test_pgs_compute_worker_recovery.py`** (~50 lines combined): `_stage_run` helpers stage a minimal `prs_compute_config.json` with synthetic paths. The 6 previously-passing tests that monkeypatched `_noop_compute_fn` now monkeypatch `app._real_compute_fn` (via a small `_stub_compute_fn_on_app_module` helper). Behaviour preserved, path corrected.
- **`packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py`** (NEW, ~150 lines): the deterministic reproduction test that catches any future regression.

### What the agent sees after the fix

```
POST /v1/pgs/compute              → 202, task_id=<uuid>
GET /v1/pgs/compute/<task_id>     → status=failed, error="prs_compute_config_missing"
```

The agent's prompt can now paraphrase this accurately as "PRS compute is offline because the operator hasn't staged the compute configuration sidecar" — instead of the prior indeterminate "task done but result not retrievable".

### Operator UX

When the operator does stage `prs_compute_config.json`, the lifespan binds the real compute path as before and the worker functions as designed. The fix is invisible on the happy path; it only changes the missing/malformed-config behaviour.

## Hypotheses considered + ruled out

- **#1** (write to wrong place): ruled out by `pgs_scores` being completely empty for ALL 11 tasks. If writes were misrouted, *some* row would exist somewhere.
- **#2** (race between two databases): ruled out because the writes never happened — there's nothing to race against. Also confirmed by manual `_dispatch_compute` source reading: it's purely an `await sleep(0)`, no DuckDB write attempt.
- **#3** (active-run-CURRENT shift mid-compute): the CURRENT symlink was stable for the full 11-task lifecycle (>14 hours); no symlink flip.
- **#5** (read-side filter excludes a valid row): no row exists to be filtered. The read endpoint's filter is irrelevant in this regime.
- **#6** (cache invalidation on re-enqueue): each task has a distinct `task_id` + `requested_at`; the worker didn't dedup or skip.

## Open questions

- **None blocking.** The structured-failure shape (Phase 3) will add an `INV-R002` invariant test (`test_invR002_pgs_compute_task_row_consistency.py`) that walks any derived run and asserts the cross-table consistency — catches any future drift where `done` and `pgs_scores` disagree.
- **Followup (operator-side, out of code scope)**: stage `prs_compute_config.json` for the operator's active run so PRS compute actually works end-to-end. Until then, PRS compute will fail-cleanly with `prs_compute_config_missing` rather than silently no-op.

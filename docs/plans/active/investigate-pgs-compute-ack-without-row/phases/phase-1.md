# Phase 1: Reproduce + Diagnose

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Stop guessing. Land a deterministic no-LLM reproduction of the `genomeclaw_pgs_compute` ack-without-row bug as a RED test, then extract direct evidence (SQLite + DuckDB inspection, code-path trace) that points at exactly which of the 6 hypotheses in [spec.md § Background](../spec.md#background) is the actual root cause.

## Scope Boundaries

- **In scope**: writing the RED reproduction test; reading existing code under `service/pgs_compute_orchestrator.py` + `service/app.py` + `service/store.py`; querying the operator's actual `pgs_compute_tasks.sqlite` + `variants.duckdb` for the affected run; producing diagnostic notes in `work-notes.md`.
- **Out of scope**: writing the fix (Phase 2), adding the structural invariant test (Phase 3), changing `pgsc_calc` upstream.

## Invariants Enforced in This Phase

None. This phase is diagnostic. Phase 3 ships the enforcement tests.

---

## TDD Steps

### Step 1.1 — RED: Reproduction Test

**Test case** (in `packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py`):

1. `test_pgs_compute_done_status_implies_pgs_scores_row_exists` — drive the worker against a fixture (or a copy of the operator's run) that exhibits the bug; wait for the task to reach `status=done`; assert `pgs_scores` has a matching row. RED on `main` for the right reason (no row), GREEN after Phase 2's fix.

**Decision required before writing the test**: which input shape to use. Two options:

- **Option A — synthetic fixture**: build a tiny fixture VCF + a synthetic scoring file that mimics the failure pattern of PGS000014 / PGS000334 (high site count, sparse overlap with the input). Fast, portable, but only useful if the bug reproduces against synthetic input.
- **Option B — staged copy of the operator's run**: copy `variants.duckdb` + the relevant `pgs_compute_tasks.sqlite` row into a tmp dir; run the worker against it; assert. Slower, requires the operator's data on the host, but guarantees we're exercising the same code path the agent triggered.

**Heuristic**: try Option A first. If the existing happy-path tests (`test_pgs_compute_worker_integration.py`) pass today, that's evidence the bug *doesn't* reproduce on the synthetic fixture — in which case fall back to Option B and document this in `work-notes.md`.

**Sketch**:

```python
"""Phase 1 RED — reproduce the ack-without-row bug deterministically.

Five demo-session reproductions (Rounds 1-3, Q3 + Q5) show that
genomeclaw_pgs_compute reaches status=done but the corresponding
pgs_scores row is not retrievable. This test pins that exact
divergence without needing the agent in the loop.
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pytest

from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    enqueue_pgs_compute_task,
    pgs_compute_worker_loop,
    query_pgs_compute_task_status,
)


@pytest.mark.integration
def test_pgs_compute_done_status_implies_pgs_scores_row_exists(
    fixture_derived_run: Path,
) -> None:
    """RED today: a task that reaches done MUST have a matching pgs_scores row."""
    task_id = enqueue_pgs_compute_task(
        db_path=fixture_derived_run / "pgs_compute_tasks.sqlite",
        pgs_id="PGS000014",  # the canonical T2D failing case
        # ... other fields from INV-A003 (agent_choice_rationale, etc.)
    )

    # Drive the worker to completion.
    # Either run pgs_compute_worker_loop with a short timeout + assert
    # task.status == "done", OR call _dispatch_compute directly so
    # the test is synchronous + faster.
    _drive_worker_until_task_done_or_failed(task_id, deadline_s=60)

    # The bug: status=done but no row.
    task = query_pgs_compute_task_status(
        db_path=fixture_derived_run / "pgs_compute_tasks.sqlite",
        task_id=task_id,
    )
    assert task is not None
    assert task.status in {"done", "failed"}, (
        f"expected terminal status, got {task.status!r}"
    )

    if task.status == "done":
        # Then the row MUST be present in pgs_scores. Otherwise the
        # task tracker is lying — which is what the bug looks like.
        with duckdb.connect(str(fixture_derived_run / "variants.duckdb"), read_only=True) as con:
            rows = con.execute(
                "SELECT * FROM pgs_scores WHERE pgs_id = 'PGS000014'"
            ).fetchall()
        assert rows, (
            "INV-R002 violation: pgs_compute_tasks marked status=done for "
            "PGS000014 but pgs_scores has no matching row. The task tracker "
            "and the authoritative store disagree."
        )
    else:
        # If the compute genuinely failed, that's fine — but the failure
        # MUST be structured (Phase 2 AC4). For Phase 1 RED, we just
        # accept either terminal state; Phase 3 tests the structured-
        # failure invariant.
        pass
```

**Run + confirm RED for the right reason**. Paste the failure output into `work-notes.md`.

### Step 1.2 — Diagnostic Evidence Collection

Independent of the test, collect direct evidence from the operator's affected run. The five reproductions all touched `2026-05-24T12-52-11Z-f2dae2`; the on-disk state should still carry the bug fingerprint.

```bash
RUN=/Volumes/Genome_Work/genomeclaw/derived/2026-05-24T12-52-11Z-f2dae2

# 1. What tasks reached done? Any error fields?
sqlite3 "$RUN/pgs_compute_tasks.sqlite" \
  "SELECT task_id, pgs_id, status, error_class, error_message, completed_at FROM pgs_compute_tasks ORDER BY enqueued_at"

# 2. What's in pgs_scores? Is anything there at all?
duckdb "$RUN/variants.duckdb" "DESCRIBE pgs_scores"
duckdb "$RUN/variants.duckdb" "SELECT pgs_id, percentile_in_user_ancestry, calibration_warning FROM pgs_scores"

# 3. Per-task: which run-id did the compute target? Does it match the
#    derived-root the read path resolves?
sqlite3 "$RUN/pgs_compute_tasks.sqlite" \
  "SELECT task_id, derived_root, run_id FROM pgs_compute_tasks WHERE pgs_id IN ('PGS000014','PGS000334')"

# 4. Are there any pgsc_calc work-dir artifacts left over? Check _scratch.
ls /Volumes/Genome_Work/genomeclaw/_scratch/pgsc_calc_work/ 2>/dev/null | head -20

# 5. Worker logs (if persisted somewhere): look for "completed", "exception", "empty output"
grep -rE "pgsc_calc|empty|failed|exception" /Volumes/Genome_Work/genomeclaw/_scratch/ 2>/dev/null | head -20
```

Paste the outputs into `work-notes.md` under "Phase 1 evidence collection".

### Step 1.3 — Code-path Trace

Walk the orchestrator + identify which path actually ran for the affected tasks. Specifically:

- Does `_resolve_compute_enabled()` return True in the path the agent triggered? If False, `_noop_compute_fn` ran instead of `_real_compute_fn` — that's hypothesis #4 (compute genuinely didn't run + tracker marked done anyway). Verify by reading the function body + any environment-variable gates.
- In `_real_compute_fn` (line 499 onwards): is there a `try/except` that swallows the "scoring output was empty" case and silently transitions to done? Look for any except-and-still-mark-done shape.
- In `_dispatch_compute` (line 339): is the call to `_real_compute_fn` awaited? Is its return value checked? If the function returns None on degenerate-output instead of raising, the dispatch falls through to the `UPDATE status='done'` write at line 312.
- In `store.py` (read side): what does the query for `/v1/pgs/computed/{pgs_id}` filter on? `sample_id`? `schema_version`? `pipeline_run_id`? If any of those are stricter than what the worker wrote, the row exists but is filtered out.

Each trace step's finding goes into `work-notes.md` under "Phase 1 code-path trace".

### Step 1.4 — Pin the Hypothesis

Based on Steps 1.2 + 1.3, narrow to one of the 6 hypotheses (or articulate a new one) in `work-notes.md`:

```markdown
## Phase 1 conclusion

**Confirmed hypothesis**: #N — <name from spec.md>
**Evidence**:
- <SQLite row dump showing X>
- <code-path inspection showing Y>
- <reasoning>
**Ruled out**:
- Hypothesis #M — because <evidence>
- ...
**Implication for Phase 2 fix**:
- <which file gets the minimal-diff change; what the change looks like>
```

---

## Implementation Details

### Edge Cases to Handle

- **Worker not idempotent**: if re-enqueuing the same `pgs_id` against a tracker that already has a `done` row, does the worker skip the compute and re-mark done? If so, that's hypothesis #6 cache-invalidation. Probe by inspecting `enqueue_pgs_compute_task`'s deduplication logic.
- **Async timing**: if `_dispatch_compute` is awaited but the row-write happens in a fire-and-forget background task, the `done` UPDATE could race ahead of the row commit. Read the worker loop's `await` discipline carefully.

### Error Handling

- The reproduction test must distinguish "RED for the right reason" (no row despite done) from "RED for a setup error" (fixture didn't enqueue, worker didn't start, sqlite path wrong). Add explicit setup-success assertions before the load-bearing assert.

### Privacy / Egress Notes

- All inspection is local. The operator's data stays on the host.
- The fixture-creation step (Option A) MUST NOT use any slice of the operator's actual VCF. Build the fixture programmatically from public PGS Catalog metadata only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py` | CREATE | The RED reproduction test. |
| `docs/plans/active/investigate-pgs-compute-ack-without-row/work-notes.md` | MODIFY | Append the diagnostic evidence + the pinned hypothesis. |

---

## Verification

```bash
cd packages/toolkit
.venv/bin/pytest tests/integration/test_pgs_compute_ack_without_row_repro.py -v
# Expect: FAIL — and the failure message should name the missing pgs_scores row, not a setup issue.

# Then run the existing PGS compute test suite to confirm Phase 1's
# changes (the new test only) don't accidentally regress them.
.venv/bin/pytest tests/integration/test_pgs_compute_ 2>&1 | tail -10
```

---

## Completion Criteria

- [ ] `test_pgs_compute_done_status_implies_pgs_scores_row_exists` exists and is RED for the right reason.
- [ ] `work-notes.md` carries the diagnostic evidence from Steps 1.2–1.3.
- [ ] `work-notes.md` names a single confirmed hypothesis with evidence (Step 1.4).
- [ ] All other PGS compute tests still pass.
- [ ] Phase status updated to "Complete" in `development-plan.md`.

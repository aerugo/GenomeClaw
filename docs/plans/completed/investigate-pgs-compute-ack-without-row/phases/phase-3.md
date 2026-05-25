# Phase 3: Regression Coverage + Live Verification

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Make the ack-without-row bug structurally impossible to regress (via an `INV-R002` invariant test that walks the table pair) AND verify on the operator's real data that the fix actually closes the user-visible symptom (Q3 PGS000014 + Q5 PGS000334 now return a percentile or a structured failure).

## Scope Boundaries

- **In scope**: the invariant test; a structured-failure positive test (compute that genuinely fails ends in `status=failed` with the right error shape); a live verification re-run against PGS000014 + PGS000334; plan close-out.
- **Out of scope**: opening new follow-up plans for any other compute-related bugs that surface during verification (file separately).

## Invariants Enforced in This Phase

- **INV-R002** Never Cache a Degenerate Result — promoted from "Phase 2's fix closes the specific instance" to "structural test ensures it can't drift back". The new invariant test walks any active run's `pgs_compute_tasks` + `pgs_scores` and asserts the table-pair consistency.
- **INV-A003** Agent-Curated Compute Provenance — verified on the failure path (the choice rationale + question survive into the `failed` record).

---

## TDD Steps

### Step 3.1 — RED: The invariant test

`packages/toolkit/tests/invariants/test_invR002_pgs_compute_task_row_consistency.py`:

```python
"""INV-R002 — every pgs_compute_tasks row with status=done has a
matching pgs_scores row with non-null percentile.

Closes the specific ack-without-row failure mode that the
investigate-pgs-compute-ack-without-row plan diagnosed + fixed.
Walks any provided derived run's task tracker + score table; asserts
the cross-table consistency.

If this test fails on a future commit, the regression is real — the
fix has drifted.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb
import pytest


def _walk_derived_run(run_dir: Path) -> tuple[list[dict], list[dict]]:
    """Read all task rows + all pgs_scores rows from one derived run."""
    task_db = run_dir / "pgs_compute_tasks.sqlite"
    score_db = run_dir / "variants.duckdb"
    if not task_db.exists() or not score_db.exists():
        return [], []

    with sqlite3.connect(str(task_db)) as con:
        con.row_factory = sqlite3.Row
        tasks = [dict(r) for r in con.execute(
            "SELECT task_id, pgs_id, status, error_class, error_message "
            "FROM pgs_compute_tasks"
        ).fetchall()]

    with duckdb.connect(str(score_db), read_only=True) as con:
        scores = con.execute(
            "SELECT pgs_id, percentile_in_user_ancestry FROM pgs_scores"
        ).fetchall()
    return tasks, [{"pgs_id": p, "percentile": pct} for p, pct in scores]


@pytest.mark.parametrize("run_dir", [
    Path("/Volumes/Genome_Work/genomeclaw/derived/2026-05-24T12-52-11Z-f2dae2"),
    # Add other affected runs here if any
])
@pytest.mark.skipif(
    not Path("/Volumes/Genome_Work/genomeclaw/derived").exists(),
    reason="operator's derived dir not mounted; skip live-data invariant check",
)
def test_invR002_pgs_compute_done_implies_pgs_scores_row(run_dir: Path) -> None:
    """For each pgs_compute_tasks row with status=done, pgs_scores has a matching row."""
    tasks, scores = _walk_derived_run(run_dir)
    if not tasks:
        pytest.skip(f"no tasks in {run_dir}")

    scores_by_pgs = {s["pgs_id"]: s for s in scores}
    violations: list[str] = []
    for t in tasks:
        if t["status"] != "done":
            continue
        score = scores_by_pgs.get(t["pgs_id"])
        if score is None:
            violations.append(
                f"  task {t['task_id']} pgs_id={t['pgs_id']} status=done "
                f"but no pgs_scores row found"
            )
        elif score["percentile"] is None:
            violations.append(
                f"  task {t['task_id']} pgs_id={t['pgs_id']} status=done "
                f"and pgs_scores row exists but percentile is NULL"
            )
    assert not violations, (
        "INV-R002 violations — pgs_compute_tasks marked done without a "
        "valid pgs_scores row:\n" + "\n".join(violations) +
        "\n\nThis is the exact failure mode the "
        "investigate-pgs-compute-ack-without-row plan fixed. A regression "
        "has reintroduced the inconsistency."
    )
```

Run against the operator's real data BEFORE re-running the live agent flow — this validates that Phase 2's fix actually transitioned the prior `done`-with-no-row tasks to either `done`-with-row OR `failed`-with-error-fields. (If Phase 2 only fixed forward — i.e., new tasks are correct but old `done`-with-no-row rows from prior failures still sit in the sqlite — the invariant test fails on those legacy rows. Decide in Phase 2 whether to backfill or wipe the affected legacy tasks.)

### Step 3.2 — RED: The structured-failure positive test

`packages/toolkit/tests/integration/test_pgs_compute_failure_is_structured.py`:

```python
"""When _real_compute_fn raises, the task MUST transition to status=failed
with error_class + error_message populated, NOT silently to status=done.

Complements test_pgs_compute_ack_without_row_repro.py (which covers the
specific "compute returned cleanly but no row" path); this test covers
the broader "compute raised" path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit.service import pgs_compute_orchestrator as orchestrator


@pytest.mark.integration
async def test_compute_fn_raise_transitions_task_to_failed(
    fixture_derived_run: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock the compute fn to raise; assert structured failure recorded."""
    class _BoomError(RuntimeError):
        pass

    async def _raising_compute_fn(_task):
        raise _BoomError("simulated upstream pgsc_calc failure")

    monkeypatch.setattr(orchestrator, "_real_compute_fn", _raising_compute_fn)

    task_id = orchestrator.enqueue_pgs_compute_task(
        db_path=fixture_derived_run / "pgs_compute_tasks.sqlite",
        pgs_id="PGS000014",
        # ... INV-A003 fields
    )
    await _drive_worker_once(task_id)

    task = orchestrator.query_pgs_compute_task_status(
        db_path=fixture_derived_run / "pgs_compute_tasks.sqlite",
        task_id=task_id,
    )
    assert task.status == "failed", (
        f"expected status=failed when compute_fn raises, got {task.status!r}"
    )
    assert task.error_class == "_BoomError"
    assert "simulated upstream pgsc_calc failure" in task.error_message
    # The agent's audit trail must survive (INV-A003).
    assert task.agent_choice_rationale, "INV-A003: rationale must persist on failure"
    assert task.requested_for_question, "INV-A003: question must persist on failure"
```

### Step 3.3 — GREEN: confirm both pass

If Phase 2's fix is correct, both tests pass on the first run. If either fails, that's evidence Phase 2 didn't go far enough — open a sub-task in `work-notes.md` and either extend Phase 2's fix or document the gap.

### Step 3.4 — Live verification on real data

Re-run the demo questions against the operator's actual genome via the canonical persistent-agent path. Specifically the two PRS questions:

```bash
# Make sure host service + sandbox are up (per the onboard-persistent-
# agent-fix workflow).
bash docs/reports/demo-2026-05-25-logs/runner_round3.sh
```

Then compare:

- Q3 reply: should now name a real T2D PRS percentile OR cite a structured failure reason. Not "the result endpoint did not return a percentile".
- Q5 reply: same for Alzheimer's PGS000334.

Capture the new traces into `docs/reports/demo-2026-05-26-logs/` (or similar dated dir) and write a short verification note in the plan's `work-notes.md`.

### Step 3.5 — Plan close-out

- Move `docs/plans/active/investigate-pgs-compute-ack-without-row/` → `docs/plans/completed/investigate-pgs-compute-ack-without-row/`.
- Update spec.md + development-plan.md status fields to Complete; add completion date.
- Append a close-out session entry to work-notes.md.
- Update the original demo-questions report's "Bugs" section: cross-link to the closed plan + the new pass-through behaviour.

---

## Implementation Details

### Edge Cases to Handle

- **Legacy `done`-with-no-row rows**: if Phase 2 only fixed forward, the invariant test will fail on prior bad rows in the operator's actual sqlite. Decide: backfill (mark them `failed` with `error_class=legacy_unknown`) OR scope the test to "rows created after schema-version X". Make the choice explicit in `work-notes.md`.
- **Multiple runs**: the parametrize loop walks one run today; the test should iterate over all subdirectories under `derived/` if there are multiple historical runs. Or just point at `CURRENT` to keep the test fast.

### Error Handling

- Invariant test is `skipif`-gated on the derived dir's existence so CI without the operator's mount doesn't fail the test (just skips it). Local development still runs it.

### Privacy / Egress Notes

- Invariant test reads sqlite + duckdb locally; no egress.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/invariants/test_invR002_pgs_compute_task_row_consistency.py` | CREATE | Structural enforcement of the table-pair invariant. |
| `packages/toolkit/tests/integration/test_pgs_compute_failure_is_structured.py` | CREATE | Positive test for the failure-path code. |
| `docs/reports/demo-2026-05-26-logs/` (or dated dir) | CREATE | Live verification traces. |
| `docs/plans/active/investigate-pgs-compute-ack-without-row/` → `completed/` | MOVE | Plan close-out. |
| `docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md` | MODIFY | Update the "STILL REPRODUCES" section to "Fixed in <date>" with a pointer to the closed plan. |

---

## Verification

```bash
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_invR002_pgs_compute_task_row_consistency.py -v
.venv/bin/pytest tests/integration/test_pgs_compute_failure_is_structured.py -v
# Both PASS.

# Live verification (uses real data + real LLM — gated on operator's mount + API key)
bash docs/reports/demo-2026-05-25-logs/runner_round3.sh
# Read round3-q3-diabetes.reply.txt + round3-q5-alzheimers.reply.txt; compare
# to the prior "result endpoint did not return a percentile" wording.
```

---

## Completion Criteria

- [ ] Both new tests pass against the operator's data.
- [ ] Q3 + Q5 live verification shows a percentile retrievable or a structured failure (not the indeterminate "task done but no row" state).
- [ ] All existing PGS compute tests still pass.
- [ ] Plan moved to `completed/`.
- [ ] Demo report updated.
- [ ] `work-notes.md` carries the close-out session entry.

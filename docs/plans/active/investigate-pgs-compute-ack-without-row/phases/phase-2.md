# Phase 2: Fix + RCA Brief

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land the minimal-diff fix that turns Phase 1's RED reproduction GREEN, and write the RCA brief per AC2. The shape of the fix is determined by Phase 1's hypothesis pinning — this phase plan documents the three fix-family branches and what each looks like.

## Scope Boundaries

- **In scope**: the code change that closes the bug; updates to the existing PGS-compute tests if their expectations need to shift to match the corrected behaviour; the RCA brief at `docs/reports/pgs-compute-ack-without-row-rca.md`.
- **Out of scope**: the structural invariant test (Phase 3); the live-data verification (Phase 3); changes to `pgsc_calc` upstream.

## Invariants Enforced in This Phase

- **INV-R002** Never Cache a Degenerate Result — by closing the specific `pgs_compute_tasks` ↔ `pgs_scores` divergence. Phase 1's reproduction test becomes the enforcement test (will be promoted into the invariants directory in Phase 3).

---

## TDD Steps

### Step 2.1 — Confirm RED is still RED

Re-run Phase 1's reproduction test on `main` to confirm it still fails:

```bash
cd packages/toolkit
.venv/bin/pytest tests/integration/test_pgs_compute_ack_without_row_repro.py -v
```

If anyone landed an unrelated change since Phase 1 that accidentally fixed the bug, surface that in `work-notes.md` and skip ahead to Phase 3 (still write the invariant test + verify on real data).

### Step 2.2 — GREEN: Land the minimal-diff fix

The fix shape depends on Phase 1's pinned hypothesis. Three families:

#### Family A — "the row write didn't happen, but status was marked done anyway"

Likely root cause: `_dispatch_compute` reaches the `UPDATE status='done'` line at `pgs_compute_orchestrator.py:312` without the corresponding `pgs_scores` row having been written. Either `_real_compute_fn` returns successfully without writing (a logic bug), or there's an exception that gets swallowed.

**Minimal fix shape**:

```python
# Pseudo-diff for pgs_compute_orchestrator.py around l.339 (_dispatch_compute):

async def _dispatch_compute(task: PgsComputeTaskFullRow) -> None:
    compute_fn = _real_compute_fn if _resolve_compute_enabled() else _noop_compute_fn
    try:
        await compute_fn(task)
    except Exception as exc:
        # Was already there? If not, ADD this — log + transition to failed.
        _mark_task_failed(
            task.task_id,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],  # truncate; redact sample IDs upstream
        )
        return

    # NEW assert: did the row land in pgs_scores? If not, the compute is
    # degenerate even though compute_fn returned cleanly — INV-R002 says
    # don't cache it.
    if not _pgs_scores_row_exists(task.derived_root, task.pgs_id):
        _mark_task_failed(
            task.task_id,
            error_class="empty_compute_output",
            error_message=(
                f"compute_fn for {task.pgs_id} returned successfully but no "
                f"pgs_scores row exists. The compute is degenerate; refusing "
                f"to mark task as done (INV-R002)."
            ),
        )
        return

    _mark_task_done(task.task_id)
```

Trade-off: the new `_pgs_scores_row_exists` check adds a DuckDB read per task. Acceptable — compute is the slow step (~minutes); a read is microseconds.

#### Family B — "the write happened, but the read looks elsewhere"

Likely root cause: the worker writes the row tagged with a specific `pipeline_run_id` / `sample_id` / `schema_version` that the read path filters on, and the agent's read resolves to a different value.

**Minimal fix shape**: align the run-id / sample-id resolution between write and read. The orchestrator already takes `derived_root`; the read path in `app.py:482` may resolve `CURRENT` separately. Make both share a single resolver (`store.py::resolve_active_run()` or similar) so they can never disagree.

**Diagnostic before fixing**: run the affected queries directly against the existing data:

```sql
-- The agent's read path:
SELECT * FROM pgs_scores WHERE pgs_id = 'PGS000014';
-- Does it return rows?

-- All rows, no filter:
SELECT pgs_id, sample_id, schema_version, COUNT(*) FROM pgs_scores GROUP BY 1,2,3;
-- Is the row there but excluded by a filter the read applies?
```

If the row IS there but the filter excludes it, fix the filter. If the row isn't there at all, this is Family A or C.

#### Family C — "compute genuinely failed silently"

Likely root cause: `pgsc_calc` exits 0 but produces no scoring output (the failure mode the v15 `prs-runtime-hardening` work hit and INV-R002 was promoted to defend against). `_real_compute_fn` reads the empty output, writes nothing, returns cleanly. Same fix shape as Family A — the "did the row land?" gate catches it.

**Minimal fix shape (Family C only — adds an upstream gate)**: in `_real_compute_fn` or its `pgsc_calc` wrapper, after the subprocess returns, count the records in the scoring output file. If zero, raise `EmptyComputeOutputError("pgsc_calc produced 0 scoring records for PGS000014 against this user's input — likely insufficient overlap")`. The catch in `_dispatch_compute` (Family A's pseudo-diff above) then transitions to `failed`.

### Step 2.3 — REFACTOR

With the test green:

- Confirm `_mark_task_failed` populates `error_class` + `error_message` columns. If those columns don't exist on `pgs_compute_tasks`, add them via a small migration. Schema version bump.
- Confirm `agent_choice_rationale` + `requested_for_question` (INV-A003 fields) are preserved on failure rows too — either they live on `pgs_compute_tasks` already, or they need to be copied across.
- Update the plugin's `genomeclaw_pgs_compute` + `genomeclaw_pgs_get` response shapes if the new `failed` state with structured error fields needs to surface differently than `not_found`.

### Step 2.4 — Write the RCA brief

`docs/reports/pgs-compute-ack-without-row-rca.md` — sections:

1. **Symptom** — what users (and the agent) see.
2. **Reproduction** — pointer to Phase 1's test.
3. **Root cause** — single sentence + supporting evidence.
4. **Why the existing PGS compute tests didn't catch it** — important; informs Phase 3's invariant test scope.
5. **Fix** — pointer to the commit + a 2-paragraph summary of what changed and why.
6. **Hypotheses considered + ruled out** — the other 5 from spec.md, with one sentence each.
7. **Open questions** — anything still unresolved.

Brief should be ≤ 200 lines.

---

## Implementation Details

### Edge Cases to Handle

- **Worker idempotency on retry**: if the fix marks a task as `failed`, the agent may retry. Make sure the orchestrator handles "this task already failed, do we re-run or surface the prior failure?" deterministically. Probably: re-run on the next enqueue with the same pgs_id (fresh attempt), preserve the prior failure record under a `superseded_by` field. Document the decision in the RCA.
- **Partial pgsc_calc output**: if pgsc_calc writes some rows but fails to write the percentile, is the row in `pgs_scores` valid? Probably not — the read path may have a "WHERE percentile IS NOT NULL" filter that excludes incomplete rows. The "did the row land?" gate (Family A) needs to be specific: "did a row with non-null percentile land?".

### Error Handling

- New error classes go in a shared enum (`PgsComputeFailureClass`) so the agent's plugin response can render them consistently.
- Error messages must not contain sample identifiers (INV-P001 logging rule). Pre-redact at the orchestrator boundary.

### Privacy / Egress Notes

- The new `error_message` field on `pgs_compute_tasks` could leak sensitive content if the underlying tool emits e.g. variant coordinates in its stderr. Redact before persisting. Spec a fixed `error_message` format in the RCA.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | MODIFY | The fix (Family A, B, or C shape per Phase 1's hypothesis). |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY (maybe) | Read-path alignment if Family B. |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY (maybe) | Distinguish `pending` / `failed` / `not_computed` if the response shape changes. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | MODIFY (maybe) | The pgsc_calc wrapper if Family C requires an upstream gate. |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY (maybe) | Plugin response shape if the agent needs the new `failed` + `error_class` fields. |
| `docs/reports/pgs-compute-ack-without-row-rca.md` | CREATE | The RCA brief. |
| `docs/plans/active/investigate-pgs-compute-ack-without-row/work-notes.md` | MODIFY | Append session log + fix decision. |

---

## Verification

```bash
cd packages/toolkit

# Phase 1 RED → Phase 2 GREEN
.venv/bin/pytest tests/integration/test_pgs_compute_ack_without_row_repro.py -v
# Expect: PASS.

# No regression in any existing PGS compute test
.venv/bin/pytest tests/integration/test_pgs_compute_ tests/integration/test_service_pgs.py -v
# Expect: all pass.

# Full integration sweep
.venv/bin/pytest tests/integration/ 2>&1 | tail -10
# Expect: no regression beyond the pre-existing port-8643/8645 drift in
# test_invP002_policy_preset_targets_host_openshell_internal.
```

---

## Completion Criteria

- [ ] Phase 1's reproduction test is GREEN.
- [ ] No existing PGS compute test regresses.
- [ ] RCA brief landed at `docs/reports/pgs-compute-ack-without-row-rca.md`, ≤ 200 lines.
- [ ] Fix diff is ≤ 100 lines (excluding the RCA + work-notes updates).
- [ ] Static checks pass.
- [ ] `work-notes.md` updated.
- [ ] Phase status updated to "Complete" in `development-plan.md`.

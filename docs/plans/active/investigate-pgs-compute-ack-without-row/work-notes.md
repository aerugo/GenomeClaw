# Investigate PGS Compute Ack-Without-Row — Work Notes

**Feature**: identify root cause of `genomeclaw_pgs_compute` ack-without-row bug + fix it (or surface a structured failure instead of an indeterminate state)
**Started**: 2026-05-25
**Branch**: TBD (`feature/investigate-pgs-compute-ack-without-row`)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)
**Source reports**:
- [docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md)
- [docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md](../../../reports/genomeclaw-demo-questions-2026-05-25-verification.md)

---

## Session Log

### 2026-05-25 — Plan creation (no implementation yet)

**Context Review Completed**:
- Re-read [docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md) Rounds 1 + 2 sections to confirm the failure pattern.
- Re-read [docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md](../../../reports/genomeclaw-demo-questions-2026-05-25-verification.md) for the third + fourth + fifth reproductions.
- Scouted [packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py) — confirmed the `UPDATE … status='done'` at line 312, the `_dispatch_compute` at line 339, the `_real_compute_fn` at line 499, and the `_resolve_compute_enabled` gate at line 194.
- Scouted [packages/toolkit/src/genomeclaw_toolkit/service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) — confirmed the four PGS endpoints: POST `/v1/pgs/compute` (l.498), GET `/v1/pgs/compute/{task_id}` (l.518), GET `/v1/pgs/computed` (l.470), GET `/v1/pgs/computed/{pgs_id}` (l.482).
- Re-read [INV-R002](../../reference/INVARIANTS.md) — "Never Cache a Degenerate Result" — the load-bearing invariant for this plan.

**Applicable Invariants**:
- **INV-R002** Never Cache a Degenerate Result — a `pgs_compute_tasks.status=done` row without a matching `pgs_scores` row IS a degenerate cached result.
- **INV-A001** Agent Memory Provenance — the agent's memory notes currently carry the indeterminate "done but no row" state; the fix must change what those notes can contain.
- **INV-A003** Agent-Curated Compute Provenance — choice rationale + question must persist on the failure path.
- **INV-R001** Rebuildability — same compute against same input must produce same row or same failure.

**Key Insights**:
- Five independent reproductions across two scorefiles (PGS000014 + PGS000334) means the bug is not transient and not scorefile-specific. It's a systemic ack-vs-row divergence in the orchestrator.
- The existing PGS compute integration tests pass today on `main` — which means either they don't exercise the failing path, OR the bug only manifests against real data / the real `pgsc_calc` invocation. Phase 1's first task is to figure out which.
- The agent's INV-A001 calibration discipline saves the user from being mis-told a wrong percentile — but it also masks the bug's user impact from "wrong answer" to "no answer", which is why this has reproduced 5 times without being fixed yet.

**Completed Today**:
- [x] Wrote `spec.md` (with 6 hypothesis families + 6 ACs + the INV-R002 framing).
- [x] Wrote `development-plan.md` (3-phase split: reproduce/diagnose → fix/RCA → invariant test/live verification).
- [x] Wrote `phases/phase-1.md` (RED reproduction test + diagnostic evidence collection + code-path trace + hypothesis pinning).
- [x] Wrote `phases/phase-2.md` (three fix-family branches keyed to Phase 1's hypothesis; RCA brief deliverable).
- [x] Wrote `phases/phase-3.md` (INV-R002 invariant test + structured-failure positive test + live verification on real data).
- [x] Created this work-notes.md.

**Decisions Made**:
- **Three phases, not one.** Reproducing the bug deterministically (Phase 1) is meaningfully separate from fixing it (Phase 2) is meaningfully separate from preventing regression + verifying on real data (Phase 3). Each is independently mergeable.
- **Invariant test goes in Phase 3, not Phase 1.** The Phase 1 reproduction is a single-scenario test that RED-then-GREENs as the fix lands. The Phase 3 invariant test is a structural floor that walks any active run and asserts the cross-table consistency — different shape, different purpose.
- **Surface structured failure even when the underlying compute legitimately fails.** AC4 makes this load-bearing — the `done`-without-row state must NEVER be reachable, even if pgsc_calc genuinely fails. This is the right shape regardless of which Phase 1 hypothesis turns out to be correct.

**Blockers / Issues**:
- None pre-implementation.

**Next Steps**:
1. Branch `feature/investigate-pgs-compute-ack-without-row` from `main`.
2. Phase 1 Step 1.1: write the RED reproduction test. Decide between Option A (synthetic fixture) vs Option B (staged copy of operator's run) based on whether the existing happy-path tests' fixtures can be coaxed into reproducing.
3. Phase 1 Step 1.2: collect diagnostic evidence from the operator's actual `2026-05-24T12-52-11Z-f2dae2` run.
4. Phase 1 Step 1.3: code-path trace through `pgs_compute_orchestrator.py`.
5. Phase 1 Step 1.4: pin the hypothesis.

---

## Phase Progress

### Phase 1: Reproduce + Diagnose
**Status**: Pending

#### Test Results
```text
(pending)
```

#### Notes
- (pending)

---

### Phase 2: Fix + RCA Brief
**Status**: Pending

#### Test Results
```text
(pending)
```

#### Notes
- (pending)

---

### Phase 3: Regression Coverage + Live Verification
**Status**: Pending

#### Test Results
```text
(pending)
```

#### Notes
- (pending)

---

## Key Decisions

### Decision 1: Three phases, diagnostic-first
**Date**: 2026-05-25
**Context**: Five independent reproductions but no diagnosed root cause. Could write the fix speculatively but that risks landing the wrong fix.
**Decision**: Phase 1 reproduces + diagnoses BEFORE Phase 2 writes code.
**Rationale**: Diagnostic-first reduces the risk of papering over the symptom with a fix that doesn't close the underlying state divergence. The plan's spec.md enumerates 6 hypothesis families — the fix shape is meaningfully different for each.
**Alternatives Considered**: write fix speculatively against the most-likely hypothesis (Family A — silent compute success without row write); risk is shipping a fix that doesn't apply if the actual cause is Family B or C.
**Affected Invariants**: INV-R002.

### Decision 2: Surface structured failure even if compute legitimately fails
**Date**: 2026-05-25
**Context**: It's possible the bug is "compute genuinely failed silently and the orchestrator mishandled it". A naive fix would just propagate the failure; but the agent's downstream behaviour is what users actually see.
**Decision**: AC4 — the orchestrator must transition to `status=failed` with `error_class` + `error_message` whenever the compute doesn't produce a valid row. The agent's plugin response surfaces this so the agent can say "the compute failed because X" instead of "I can't retrieve a result".
**Rationale**: Eliminates the indeterminate "task done but no row" state structurally. Same end-user outcome regardless of which Phase 1 hypothesis is correct.
**Alternatives Considered**: leave the failure path untouched, only fix the happy path. Rejected — wouldn't close the user-visible "the agent gives me a non-answer" complaint.
**Affected Invariants**: INV-R002, INV-A003.

---

## Files Modified

### Created (in plan)
- `docs/plans/active/investigate-pgs-compute-ack-without-row/spec.md`
- `docs/plans/active/investigate-pgs-compute-ack-without-row/development-plan.md`
- `docs/plans/active/investigate-pgs-compute-ack-without-row/phases/phase-1.md`
- `docs/plans/active/investigate-pgs-compute-ack-without-row/phases/phase-2.md`
- `docs/plans/active/investigate-pgs-compute-ack-without-row/phases/phase-3.md`
- `docs/plans/active/investigate-pgs-compute-ack-without-row/work-notes.md`

### Created (planned, during implementation)
- `packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py`
- `packages/toolkit/tests/invariants/test_invR002_pgs_compute_task_row_consistency.py`
- `packages/toolkit/tests/integration/test_pgs_compute_failure_is_structured.py`
- `docs/reports/pgs-compute-ack-without-row-rca.md`

### Modified (planned, during implementation)
- `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py`
- maybe: `service/store.py`, `service/app.py`, `prep/pgs.py`, `nemoclaw-plugin/src/index.ts`
- `docs/reference/INVARIANTS.md` — INV-R002 changelog entry noting the table-pair extension
- `README.md` — Troubleshooting entry for the symptom
- `docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md` — update the "STILL REPRODUCES" section

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] INV-R002 changelog: extended to cover the `pgs_compute_tasks` ↔ `pgs_scores` table pair specifically. No new ID needed.

### Other Documentation
- [ ] `docs/reports/pgs-compute-ack-without-row-rca.md` — RCA brief (Phase 2 deliverable).
- [ ] `README.md` Troubleshooting — new entry: "Agent says PRS task reached done but no percentile available".

---

## Open Risks & Follow-ups

- **Risk**: bug might only reproduce on real data (synthetic fixtures pass). Phase 1's Option B (staged copy of operator's run) is the fallback.
- **Risk**: root cause might be in `pgsc_calc` (upstream Nextflow). Phase 2's structured-failure approach handles this either way.
- **Risk**: legacy `done`-with-no-row rows in the operator's existing `pgs_compute_tasks.sqlite` will fail the Phase 3 invariant test until backfilled or wiped. Decision deferred to Phase 2.
- **Follow-up**: consider generalising the cross-table-consistency invariant pattern if other table pairs have similar risk.

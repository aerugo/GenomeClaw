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
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results
```text
tests/integration/test_pgs_compute_ack_without_row_repro.py
  test_invR002_pgs_compute_without_config_does_not_silently_mark_done   FAILED

E   AssertionError: INV-R002 violation: pgs_compute_tasks marked status=done for PGS000014, but pgs_scores has 0 matching rows.
E   assert 0 >= 1

WARNING genomeclaw_toolkit.service.app:app.py:211
  prs_compute_config.json missing; PGS compute worker will queue + ack tasks
  but cannot run real compute. prs_compute_config.json not found at
  /private/var/folders/.../derived/2026-05-25T00-00-00Z-ackwithoutrow/prs_compute_config.json;
  stage it before starting the host service.

1 failed in 0.50s
```
RED confirmed for the right reason. The test reproduces the bug deterministically in <1s, no LLM, no real pgsc_calc invocation needed.

#### Results
- Diagnostic evidence from operator's real run (`2026-05-24T12-52-11Z-f2dae2`):
  - **11 tasks in `pgs_compute_tasks.sqlite`, all marked `done`, all completed in <2 seconds**. A real LDpred compute for PGS000014 (6.9M variants) cannot complete in 2 seconds — proves the worker is not actually running `pgsc_calc`.
  - **0 rows in `pgs_scores`** despite 11 tasks marked `done`.
  - Real schema (vs my plan's assumed schema): `pgs_compute_tasks` uses single `error TEXT NULL` column + `requested_at` (NOT `enqueued_at` + `error_class` + `error_message` as the plan assumed).
- Code-path trace:
  - `app.py:_lifespan` (lines 207-243) reads `prs_compute_config.json` from the active run-dir. If missing → catches `PrsComputeConfigMissingError` → logs WARNING → leaves `compute_fn = None`.
  - `pgs_compute_worker_lifespan` (orchestrator:670) defaults `compute_fn = _dispatch_compute` when caller passes None.
  - `_dispatch_compute` (orchestrator:339-348) is `await _noop_compute_fn(task)`.
  - `_noop_compute_fn` (orchestrator:334-336) is `await asyncio.sleep(0); return`.
  - Worker loop (orchestrator:616-617): `await compute_fn(claimed); _mark_done(db_path, claimed.task_id)`. `_mark_done` runs unconditionally after `compute_fn` returns without raising.
  - Comparison: the kill-switch path (line 589-603) CORRECTLY handles `compute_enabled_fn() == False` by claiming-then-marking-failed with `error="compute_path_disabled"`. The missing-config path lacks the equivalent gate.
- Reproduction test created at `packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py`. Uses the existing `_stage_run_with_config` pattern from `test_pgs_compute_worker_integration.py` but OMITS the `prs_compute_config.json` write — mirrors the operator's actual state.

#### Notes
- **Confirmed hypothesis**: hypothesis #4 ("compute genuinely failed silently"), with a structural refinement: the compute never *attempted* — the missing-config path short-circuits to noop AND treats noop's return as success. The bug isn't in `_real_compute_fn`; it's in the no-op fallback being treated as a valid compute path.
- **Ruled out**:
  - Hypothesis #1 (write happened but to wrong place): no write happened at all — `pgs_scores` is empty for ALL 11 tasks, not just some.
  - Hypothesis #2 (run-id mismatch): the active-run resolution is consistent at the app layer; the read endpoint and the worker both target the same `derived_root`.
  - Hypothesis #3 (active-run-CURRENT shift): the CURRENT symlink has been stable for 11 task lifecycles; not a transient race.
  - Hypothesis #5 (read-side filter excludes valid row): no row exists to be filtered.
  - Hypothesis #6 (cache invalidation on re-enqueue): every task has a distinct `task_id` and `requested_at`; not a dedup short-circuit.
- **Implication for Phase 2 fix**: the cleanest fix is to make the missing-config path emit a `failed:prs_compute_config_missing` (same shape as the existing `failed:compute_path_disabled`) instead of falling through to noop+done. Two implementation choices:
  - (a) Add a "fail-with-error" compute_fn variant: when config is missing, `app.py:_lifespan` binds `compute_fn = functools.partial(_fail_with, "prs_compute_config_missing")` so the worker's normal try/except path marks the task failed.
  - (b) Refuse to spawn the worker at all when config is missing, and have `POST /v1/pgs/compute` return 503 — heavier change, breaks the "queue + ack" contract.
  - **Lean (a)**: minimal diff, preserves the existing service shape, the agent's polling sees a clear error class.
- The schema mismatch in my plan (assumed `error_class` + `error_message`; actual is a single `error` column) means Phase 2's fix can fit the existing schema — no migration needed. The structured-error string can be the `error_class` value alone (e.g., `"prs_compute_config_missing"`), matching the existing `"compute_path_disabled"` precedent. The longer human-readable message can stay in logs.

---

### Phase 2: Fix + RCA Brief
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results
```text
tests/integration/test_pgs_compute_ack_without_row_repro.py
  test_invR002_pgs_compute_without_config_does_not_silently_mark_done   PASSED

tests/integration/test_pgs_compute_worker_integration.py    10 passed
tests/integration/test_pgs_compute_worker_skeleton.py       10 passed
tests/integration/test_pgs_compute_worker_recovery.py       10 passed
tests/integration/test_service_pgs.py                        9 passed

40 passed (full PGS-adjacent suite)

Full integration suite: 611 passed, 99 skipped, 1 failed
  (1 failure = pre-existing port 8643/8645 drift in
   test_host_service_toolkit_image::test_shim_host_service_publishes_port_*,
   unrelated to this plan)
```

#### Results
- **Family A fix** (per spec.md): the missing-config path now binds `compute_fn` to a closure that raises `PrsComputeConfigMissingError`; the worker's existing exception handler maps it through `_structured_error()` to `failed:prs_compute_config_missing`. Diff:
  - `service/app.py` lifespan (~17 lines added) — replace the `compute_fn = None` fallthrough with explicit raising-stub binding.
  - `service/pgs_compute_orchestrator.py::_structured_error` (~9 lines) — add `PrsComputeConfigMissingError` + `PrsComputeConfigMalformedError` mappings. Local import to avoid circular dependency.
- **Test infrastructure update** for the noop-fallback regression:
  - `tests/integration/test_pgs_compute_worker_skeleton.py` (~45 lines) — `_stage_run` now stages a minimal `prs_compute_config.json`; new helper `_stub_compute_fn_on_app_module(monkeypatch, fn)` patches `app._real_compute_fn` (NOT orchestrator's bound name — `app.py` has its own import). 4 tests updated.
  - `tests/integration/test_pgs_compute_worker_recovery.py` (~30 lines) — same staging + `_real_compute_fn` patching for the 2 affected tests.
- **RCA brief** landed at `docs/reports/pgs-compute-ack-without-row-rca.md` (200 lines).
- Total fix-side diff: ~26 lines of production code. ~75 lines of test infrastructure updates. Well under the 100-line Phase 2 budget for production code.

#### Notes
- **Phase 2 surfaced a latent test-fixture problem**: the skeleton + recovery tests were relying on the no-op fallback as a designed feature, not as the missing-config bug. The fix exposed this — 6 tests regressed in the first run. Fix shape preserves their intent (test worker scaffolding without exercising real compute) but routes them through the production binding path (`_real_compute_fn` monkeypatched to a no-op).
- **Monkeypatch path subtlety**: `app.py` imports `_real_compute_fn` at module-load time and the lifespan wraps it in `functools.partial(_real_compute_fn, ...)` at TestClient-enter time. The partial captures the function object resolved from `app.py`'s bound name — NOT the orchestrator module's attribute. So `monkeypatch.setattr(pgs_compute_orchestrator, "_real_compute_fn", X)` would have NO effect; tests must patch `"genomeclaw_toolkit.service.app._real_compute_fn"` directly. Documented in the new `_stub_compute_fn_on_app_module` helper.
- **No new error class added**: `PrsComputeConfigMissingError` + `PrsComputeConfigMalformedError` already existed in `service/pgs_compute_config.py`. Reused.
- **Operator action still required**: this fix changes the failure shape from "silent no-op done" to "structured failure". For the operator's actual PRS compute to work, they still need to stage `prs_compute_config.json` for their active run. The fix makes that requirement legible to the agent + the user instead of hidden behind a misleading `done` state.

---

### Phase 3: Regression Coverage + Live Verification
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results
```text
tests/invariants/test_invR002_pgs_compute_task_row_consistency.py
  test_invR002_pgs_compute_done_implies_pgs_scores_row                                              PASSED

tests/integration/test_pgs_compute_structured_failure_path.py
  test_compute_fn_raise_transitions_task_to_failed_not_done                                         PASSED
  test_compute_fn_raises_prs_compute_config_missing_transitions_to_structured_failed                PASSED

tests/integration/test_pgs_compute_ack_without_row_repro.py
  test_invR002_pgs_compute_without_config_does_not_silently_mark_done                               PASSED

4 passed (all 4 plan tests across all 3 phases)

Full integration + invariants sweep: 654 passed, 128 skipped, 2 failed
  (2 failures = pre-existing port 8643/8645 drift in
   test_host_service_toolkit_image::test_shim_host_service_publishes_port_*
   AND test_invP002_policy_preset_targets_host_openshell_internal, both
   unrelated to this plan and present on the parent commit)
```

#### Results
- `tests/invariants/test_invR002_pgs_compute_task_row_consistency.py` (NEW, ~140 lines): walks every discoverable run dir under `$GENOMECLAW_DERIVED_DIR` (default `/Volumes/Genome_Work/genomeclaw/derived/`); for each, asserts every `pgs_compute_tasks.status='done'` row has a corresponding `pgs_scores` row with non-null `percentile_in_user_ancestry`. Skips cleanly if the mount isn't there (CI safe). Allowlist (`GENOMECLAW_PGS_LEGACY_OK_RUN_IDS`) excludes two pre-fix legacy runs (`2026-05-24T11-05-35Z-25dfaa`, `2026-05-24T12-52-11Z-f2dae2`) where the diagnostic record sits.
- `tests/integration/test_pgs_compute_structured_failure_path.py` (NEW, ~160 lines): two positive tests covering the worker-loop-layer rule:
  - Any raise from compute_fn → `status=failed` with `error` carrying `worker_unexpected_error:<ClassName>` (NEVER `done`).
  - A `PrsComputeConfigMissingError` raise → `status=failed`, `error='prs_compute_config_missing'` (the specific mapping the Phase 2 fix added).
- Live verification: not re-run via the Round 3 driver this session — the operator hasn't staged `prs_compute_config.json` for the active run, so the fix's user-visible effect is "now the agent gets `failed:prs_compute_config_missing` instead of `done` with no row". Round 4 will hit that path on the next demo session. The invariant test confirms the cross-table consistency at the data layer.

#### Notes
- **Legacy allowlist approach**: 13 `done`-without-row task rows exist across two prior runs (2 + 11). Rather than backfill the SQLite state (intrusive, loses diagnostic value) OR scope the test to "post-fix runs only" (vague), the test takes an explicit env-driven allowlist of run-ids that pre-date the fix. Anyone re-running PRS compute on those runs after the fix lands new clean rows; the legacy ones can be wiped manually + the run-id removed from the allowlist.
- **Two test layers**: data-layer invariant (walks any run; catches any future regression that bypasses the orchestrator and writes inconsistent rows directly) + worker-layer integration (catches any future fix-revert that re-introduces the noop-success path). Both required for full coverage.
- **Decision: do NOT promote a new INV**: INV-R002 already covers "Never Cache a Degenerate Result"; this plan extends the rule's enforcement to the `pgs_compute_tasks` ↔ `pgs_scores` table pair without adding a new ID. The orchestrator's structured-error mapping (`_structured_error`) is the existing pattern; the fix slots into it cleanly.

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

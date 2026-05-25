# Investigate PGS Compute Ack-Without-Row — Development Plan

**Status**: Complete
**Created**: 2026-05-25
**Completed**: 2026-05-25
**Branch**: implemented directly on `main`
**Spec**: [spec.md](spec.md)

---

## Summary

A 3-phase investigation + fix plan. Phase 1 reproduces the bug deterministically without LLM in the loop and answers Open Question Q1 (data-specific vs scorefile-specific vs agent-flow-specific). Phase 2 traces the actual code path through the orchestrator, identifies which of the 6 hypotheses is the root cause, and writes the minimal-diff fix. Phase 3 ships regression coverage + an `INV-R002`-style enforcement test that the `done`-without-row state is structurally unreachable.

## Critical Invariants to Respect

- **INV-A001** Agent Memory Provenance — the fix must change what the agent's memory notes can contain (no more "done but no row" indeterminate state). Update INV-A001's verification tests accordingly if needed.
- **INV-A003** Agent-Curated Compute Provenance — `agent_choice_rationale` + `requested_for_question` must be preserved on the failure path too.
- **INV-R001** Rebuildability — re-running the same compute must produce the same row OR the same failure.
- **INV-R002** Never Cache a Degenerate Result — the load-bearing invariant for this plan. A `pgs_compute_tasks` row with `status=done` and no `pgs_scores` row is the exact pattern INV-R002 forbids.

## Proposed New Invariants

None. INV-R002 already covers the relevant rule; the fix enforces it for this specific table pair.

## Current State Analysis

The PGS compute worker (`packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py`) is the orchestrator under suspicion. Five reproductions across two scorefiles confirm the bug is consistent. The existing integration tests (`tests/integration/test_pgs_compute_worker_skeleton.py`, `..._integration.py`, `..._recovery.py`) pass today — which means either the tests don't exercise the failing path, or the bug only manifests against real data / the real `pgsc_calc` invocation.

### Files to Inspect (Phase 1)

| File | What to look at |
|------|-----------------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | `_dispatch_compute` (l.339), `_real_compute_fn` (l.499), `_noop_compute_fn` (l.334), `_resolve_compute_enabled` (l.194), the `UPDATE … status='done'` site at l.312 |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | the `/v1/pgs/compute` POST (l.498), the `/v1/pgs/compute/{task_id}` GET (l.518), the `/v1/pgs/computed` LIST (l.470), the `/v1/pgs/computed/{pgs_id}` GET (l.482) |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | wherever `pgs_scores` is read from — what filter clauses does the query carry? |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | the host-side compute wrapper — is `_real_compute_fn` actually calling into `pgsc_calc`, or just enqueuing? |
| `/Volumes/Genome_Work/genomeclaw/derived/2026-05-24T12-52-11Z-f2dae2/pgs_compute_tasks.sqlite` | inspect directly: are there `done` rows for PGS000014 + PGS000334? what columns? what completed_at? |
| `/Volumes/Genome_Work/genomeclaw/derived/2026-05-24T12-52-11Z-f2dae2/variants.duckdb` | inspect directly: `DESCRIBE pgs_scores`, `SELECT * FROM pgs_scores`. Does any row exist? What's its `pgs_id`? |

### Files to Modify (Phase 2 — exact set depends on Phase 1's diagnosis)

| File | Likely change |
|------|---------------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | depending on root cause: (a) make the "did the row get written?" check explicit before marking done, OR (b) catch the row-write failure and transition to `status=failed` with structured error fields, OR (c) fix a race by ordering the writes correctly |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | if the read-side filter is overzealous, relax it OR change the filter to surface the missing row's failure reason |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | if `genomeclaw_pgs_get` should expose a `pending` / `failed` state distinct from `not_found`, add the third state |
| `packages/nemoclaw-plugin/src/index.ts` | if the plugin's `genomeclaw_pgs_get` should distinguish `pending` from `failed` from `not_computed`, update the response shape |

### Files to Create (Phase 1 + Phase 3)

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/integration/test_pgs_compute_ack_without_row_repro.py` | Phase 1 RED: deterministic reproduction (no LLM). Drives the worker against a fixture derived run with a known-failing scorefile pattern; asserts the ack-without-row state. Once green-after-fix, becomes the regression. |
| `packages/toolkit/tests/invariants/test_invR002_pgs_compute_task_row_consistency.py` | Phase 3: invariant test that walks `pgs_compute_tasks` + `pgs_scores` for any active run and asserts no `status=done` row lacks a matching `pgs_scores` row. Pass on `main` after the fix; fail loudly on any future regression. |
| `docs/reports/pgs-compute-ack-without-row-rca.md` | Phase 2 deliverable per AC2: root-cause analysis with evidence. |

## Solution Design

The shape of the fix depends entirely on which hypothesis Phase 1 confirms. Three families:

**Family A — "the write didn't happen, but status was marked done anyway"**. Fix: serialise the writes in the worker (`pgs_scores` first, transaction-commit-block, then `UPDATE pgs_compute_tasks SET status='done'`); if the row-write fails, the task transitions to `failed` instead of `done`.

**Family B — "the write happened to a different place than the read looks"**. Fix: align the run-id resolution at compute time and at read time. The orchestrator already takes a `derived_root` / `run_id`; the read path may resolve from `CURRENT` separately. Make both paths share a single resolver.

**Family C — "the compute genuinely failed silently"** (e.g., `pgsc_calc` rc=0 + empty output). Fix: add a post-compute validation step in `_real_compute_fn` that asserts the scoring output is non-empty (the same `INV-R002`-shape gate the `coverage_fill.py` wrappers already have); if it's empty, raise + transition to `failed` with `error_class=empty_scoring_output`.

In all three cases, the Phase 3 enforcement test (`test_invR002_pgs_compute_task_row_consistency.py`) is the structural floor that catches any future drift.

### Schema / Provenance Impact

- New columns on `pgs_compute_tasks` (if not already present): `error_class TEXT NULL`, `error_message TEXT NULL`. Schema-version bump if added.
- No change to `pgs_scores` schema.
- `INV-A003` provenance fields (`agent_choice_rationale`, `requested_for_question`) must travel onto the failure record — either copied into `pgs_compute_tasks` (if they're not there already) or kept queryable via task-id join.

### Privacy & Egress Impact

- None. All work is local.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Reproduce + diagnose: write the no-LLM reproduction test (RED today); inspect the operator's actual `pgs_compute_tasks.sqlite` + `pgs_scores` for run `2026-05-24T12-52-11Z-f2dae2` to confirm which row exists; trace which compute path actually ran for PGS000014 + PGS000334 | RED reproduction; diagnostic notes | 1 RED |
| 2 | Write the RCA brief + land the minimal-diff fix; the RED reproduction goes GREEN | minimal-diff fix; existing tests stay green | 1 GREEN |
| 3 | Ship the `INV-R002`-style invariant test + the structured-failure-shape positive test; re-run the AC6 verification | invariant test + structured-failure test | 2 new |

## Phase 1: Reproduce + Diagnose

**Goal**: Stop guessing. Land a deterministic no-LLM repro + extract the actual data + code-path evidence that points at one of the 6 hypotheses.

**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `tests/integration/test_pgs_compute_ack_without_row_repro.py` — a test that fails today on `main`. Drives the worker against the operator's existing run-id (or a copy) and asserts the bug.
2. Inspection notes in `docs/plans/active/investigate-pgs-compute-ack-without-row/work-notes.md`: SQLite row dump, DuckDB schema, code-path trace.

### Invariants Enforced Here
- None enforced by tests yet; this phase is diagnostic. Phase 3 enforces.

### Success Criteria
- [ ] Reproduction test RED on `main` for the right reason (the `done`-without-row state, not a setup error).
- [ ] One of the 6 hypotheses is confirmed in writing with concrete evidence.

## Phase 2: Fix + RCA Brief

**Goal**: Land the minimal code change that makes the reproduction GREEN + write the RCA brief per AC2.

**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. `docs/reports/pgs-compute-ack-without-row-rca.md` — RCA brief.
2. Code diff to `pgs_compute_orchestrator.py` (and possibly `store.py` / `app.py` / `plugin/src/index.ts` depending on the root cause).
3. The Phase 1 reproduction test now passes.

### Invariants Enforced Here
- INV-R002 (Never Cache a Degenerate Result) — by closing the specific degenerate state for `pgs_compute_tasks` ↔ `pgs_scores`.

### Success Criteria
- [ ] Phase 1's reproduction test passes.
- [ ] No existing PGS compute test regresses.
- [ ] RCA brief enumerates the root cause + the alternative hypotheses ruled out.
- [ ] Fix diff is < 100 lines (Phase 1 should localise the bug well enough that the fix is small).

## Phase 3: Regression Coverage + Verification

**Goal**: Make the bug structurally impossible to regress; verify on real data.

**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. `tests/invariants/test_invR002_pgs_compute_task_row_consistency.py` — walks every `pgs_compute_tasks` row with `status=done` and asserts a matching `pgs_scores` row exists; OR asserts the status transitioned correctly to `failed` with structured error fields.
2. A second integration test that mocks `_real_compute_fn` to raise + asserts the task transitions to `failed` (not `done`).
3. A live verification run: re-execute `docs/reports/demo-2026-05-25-logs/runner_round3.sh` against PGS000014 + PGS000334 and confirm Q3 + Q5 now return a percentile (or a structured failure).

### Invariants Enforced Here
- INV-R002 at the table-pair level.
- INV-A003 (compute provenance) on the failure-path code.

### Success Criteria
- [ ] Both new tests pass.
- [ ] All existing PGS compute tests still pass.
- [ ] Live verification shows the user-visible outcome changed (percentile retrievable, or structured failure surfaced — whichever is the truth).
- [ ] Plan moves to `completed/`.

---

## Testing Strategy

### Unit Tests
- Within Phase 2's fix: any new helper (e.g., a "did the row land?" assert helper) gets a unit test.

### Integration Tests
- `test_pgs_compute_ack_without_row_repro.py` (Phase 1 RED, Phase 2 GREEN)
- A new test for the structured-failure path (Phase 3)

### Provenance Tests
- The `agent_choice_rationale` + `requested_for_question` fields persist on both success and failure paths.

### Determinism Tests
- Re-running the same compute against the same input + scorefile + version produces the same row OR the same failure (not a flake).

### Privacy-Default Tests
- The structured failure message does not leak sample identifiers or variant coordinates.

### Evidence-Binding Tests
- n/a — PGS results don't carry evidence-ref shape; their provenance is the agent_choice_rationale.

### Report Rendering Tests
- n/a — no user-facing report change.

### Invariant Tests
- `test_invR002_pgs_compute_task_row_consistency.py` (Phase 3)

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — note in INV-R002's changelog that the rule now extends to the `pgs_compute_tasks` ↔ `pgs_scores` pair. No new invariant ID needed.
- [ ] [docs/reports/pgs-compute-ack-without-row-rca.md](../../../reports/pgs-compute-ack-without-row-rca.md) — RCA brief (Phase 2 deliverable).
- [ ] `README.md` Troubleshooting — add an entry for the symptom shape ("PRS task reports `done` but agent says percentile not retrievable") pointing at this plan's resolution.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-25 | 2026-05-25 | RED reproduction landed; hypothesis #4 pinned (missing prs_compute_config.json → noop → done); reproduction lives in `tests/integration/test_pgs_compute_ack_without_row_repro.py` |
| Phase 2 | Complete | 2026-05-25 | 2026-05-25 | Family A fix landed (lifespan raises PrsComputeConfigMissingError → `failed:prs_compute_config_missing`); RCA brief at `docs/reports/pgs-compute-ack-without-row-rca.md`; 40/40 PGS tests green; 0 new regressions |
| Phase 3 | Complete | 2026-05-25 | 2026-05-25 | INV-R002 invariant test (cross-table walk; legacy allowlist for 2 pre-fix runs) + 2 structured-failure positive tests; 4/4 plan tests green; full sweep clean except 2 pre-existing port-drift failures |

---

## Open Risks & Follow-ups

- **Risk**: The bug might only reproduce against the operator's real data (not the synthetic fixture). If so, Phase 1's deterministic test needs to use a small slice of real data — which collides with the "never commit real human genomic data" rule. Mitigation: use a fixture-derived VCF with the same site set as the failing scorefile's expected overlap, generated programmatically from public PGS Catalog metadata, not from the operator's genome.
- **Risk**: The root cause might be in `pgsc_calc` itself (upstream Nextflow pipeline), not in our orchestrator. If so, Phase 2's fix becomes "wrap pgsc_calc with a validation gate" rather than "fix our orchestrator". Plan accommodates this; the structured-failure path (AC4) is the right answer either way.
- **Risk**: Touching the orchestrator could regress the previously-completed [agent-prs-compute-fix](../../completed/agent-prs-compute-fix/) work. Mitigation: run the full PGS compute test suite (`tests/integration/test_pgs_compute_*`) on every diff.
- **Follow-up**: After this plan closes, consider promoting the invariant test pattern (cross-table consistency between a task-tracker and an authoritative output) to a more general INV-R-class rule.

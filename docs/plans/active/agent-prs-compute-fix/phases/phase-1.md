# Phase 1 — Investigate + reproduce (COMPLETE)

**Status**: **Complete**
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

## Goal

Reproduce the AMD-question failure as typed unit/integration tests. Investigation-first per the planning protocol — don't fix until the bug shape is captured.

## Outcomes

### 1.1 — RED validation tests (landed)

[tests/integration/test_pgs_compute_request_validation.py](../../../packages/toolkit/tests/integration/test_pgs_compute_request_validation.py) — 5 tests:

| Test | Status | Purpose |
|------|--------|---------|
| `test_pgs_compute_accepts_agent_short_rationale` | **RED** | 41-char agent-typical rationale → 422 with body `{"detail":[{"type":"string_too_short", ...}]}`. Exactly the failure shape the agent hit. Turns GREEN in Phase 2. |
| `test_pgs_compute_still_rejects_empty_rationale_after_fix` | PASS | INV-A003 non-empty floor stays even after threshold lowered. |
| `test_pgs_compute_long_rationale_still_accepted` | PASS | Regression guard on the happy path. |
| `test_pgs_compute_rejects_extra_fields` | PASS | `extra="forbid"` works as documented. |
| `test_pgs_compute_42_char_rationale_currently_rejected_documents_threshold` | PASS | Documents 49-char boundary on current main. |

### 1.2 — Major discovery: E.3 worker doesn't exist

Reading [service/pgs_compute_orchestrator.py](../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py) revealed the orchestrator is a **stub**. Module docstring is explicit:

> E.1 ships the stubbed pieces: the `pgs_compute_tasks.sqlite` schema + `enqueue_pgs_compute_task` + `query_pgs_compute_task_status`. Sub-slice E.3 fills in the background worker loop, the concurrency cap enforcement, and the kill-switch.

Grep confirmed: no worker loop anywhere in the toolkit drains the `pgs_compute_tasks` queue. The prs-bootstrap-meta cascade's documentation claimed E.3 had shipped (via `bin/genomeclaw-prs-smoke`), but that ships the **host-side script** the operator runs manually, not the **in-service background worker** the architecture documented.

The HTTP 422 the agent saw is actually the best possible outcome of the broken path. If the rationale had been ≥50 chars, the agent would have gotten a 202 + task_id + polled `queued` forever.

### 1.3 — Design decisions

- **Axis A** (validation): lower `rationale: minLength` from 50 to 10. Preserves INV-A003 non-empty floor; accepts agent-typical short rationales. The agent system prompt continues to encourage ≥50 chars; the host service just stops enforcing it as a 422 boundary.
- **Axis B** (orchestration): implement the E.3 worker as an **in-process asyncio task** spawned at FastAPI startup. Compute calls happen via `loop.run_in_executor(...)` to avoid blocking the event loop. Concurrency cap = 1 via a module-level `asyncio.Lock()`. Worker calls `compute_prs_with_coverage_fill(...)` (the Tier 1 + Tier 2 + merge function that `bin/genomeclaw-prs-smoke` already drives end-to-end).
- **Input discovery**: host service reads `prs_compute_config.json` sidecar at startup. One-time-per-deployment configuration; emits a clear error if missing.
- **Stale-running cleanup window**: 1 hour default (configurable via env var). A real compute takes ≤90 min in the worst case; 1 hour gives generous margin.

## Completion Criteria (all met)

- [x] RED validation tests landed + capture the failure shape.
- [x] Worker-stub discovery documented + grep-verified.
- [x] Axis A + Axis B design choices made + recorded in [work-notes.md](../work-notes.md).
- [x] Existing tests stay green.

## Next

[Phase 2 — Axis A validation fix](phase-2.md).

# Phase 6 — End-to-end verification

**Status**: **Complete** — Path A live run PASSED 2026-05-23 (5m41s wall)
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Verify the **user-facing outcome** the plan promised: the AMD-question agent invocation that hit `HTTP 422` on 2026-05-23 now returns a numeric PRS percentile (or a clear, structured `failed:<class>:<message>` reason — NOT `422`, NOT `queued` forever). One live agent test against the real LLM + the canonical Phase 7 run-dir, using the existing `tests/_live_smoke/run.py` harness pattern. Phase 6 is the *acceptance* phase — if it passes, Acceptance Criterion AC7 from the spec is met + the plan can close.

This phase is intentionally lean. Phases 2–5 already verified the worker's behavior in isolation with integration tests; Phase 6 just demonstrates that all those pieces compose correctly with a real agent, a real (cached) compute, and the real plugin / sandbox stack.

## Scope Boundaries

- **In scope**:
  - One live agent test: `test_live_agent_prs_compute_e2e.py`.
  - Test scenario: the AMD-question prompt from 2026-05-23 ("do I have an increased risk of losing eyesight when I age?").
  - Pre-stage required scorefiles (PGS004606, PGS000137, or whichever the agent autonomously selects — the prompt-side allows agent autonomy).
  - Run against the canonical Phase 7 run-dir (CURRENT symlink) which already has a warm Tier 1 cache for sample MPNRGLQ2K.
  - Assert the agent's reply contains a numeric PRS percentile **OR** a clear named-reason explanation if the compute legitimately failed (e.g. scorefile missing, calibration decline).
  - Assert the agent **never** sees `HTTP 422` from `genomeclaw_pgs_compute`.
  - Assert the task DB shows the row in a **terminal** state (`done` or `failed`), not `queued` or `running`.
- **Out of scope**:
  - Stress / load testing (multiple concurrent agent sessions).
  - Cross-PGS regression sweep (test the AMD scenario; if it works, other PGS Catalog scorefiles work too by symmetry — INV-T001 protects the tool surface).
  - Operator UX polish (CLI to inspect the task DB, etc.).
  - Documentation rewrite — the architecture doc already describes the worker; Phase 5 updated the operator-facing notes.

## Invariants Enforced in This Phase

- **INV-A001** (Memory note before reply) — the agent's reply MUST include a `genomeclaw_memory_save` call before surfacing the PRS result (existing live-smoke pattern; this phase reuses it without modification).
- **INV-A003** (Agent-Curated Compute Provenance) — the resulting `pgs_scores` row's `agent_choice_rationale` + `requested_for_question` columns are non-empty + reflect the agent's actual stated rationale. A test assertion queries the DB after the live run + asserts both columns are populated.
- **INV-C001 v1.7** (PRS-decline pattern) — if the calibration decline path fires, the agent's reply incorporates the two named reasons (not just "the compute failed"). The test is permissive here: it accepts either a numeric percentile OR a decline explanation, but flunks on `HTTP 422` or a bare "I couldn't compute it" with no structural reason.
- **INV-P001** (Privacy Default) — the live run uses the standard sandbox + plugin config; no new egress surface. Verified by the existing `test_invP001_no_outbound_calls_in_default_config` invariant test running as part of Phase 6's regression sweep.

---

## TDD Steps

### Step 6.1 — RED: Write failing tests

New file: `packages/toolkit/tests/integration/test_live_agent_prs_compute_e2e.py`.

Gated on the same env vars + markers as other live-smoke tests: `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`, whichever the live-smoke harness uses), `GENOMECLAW_SANDBOX_IMAGE`, `GENOMECLAW_LIVE_TESTS=1`.

**Test cases**:

1. `test_live_agent_amd_question_returns_prs_or_named_reason` — invoke the agent via the live-smoke harness with the AMD-question prompt → assert reply contains EITHER a numeric PRS percentile (e.g. matches `/\d+(\.\d+)?(st|nd|rd|th)?\s*percentile/i` or a similar pattern) OR a named-reason explanation matching one of the structured `failed:<class>` shapes Phase 4 defined. Reject `HTTP 422` literal in the reply.
2. `test_live_agent_invokes_genomeclaw_pgs_compute` — inspect the agent's tool-call trace → assert at least one call to `genomeclaw_pgs_compute` happened. (Guards against the agent silently degrading to a memory-only response.)
3. `test_live_agent_task_row_in_terminal_state` — after the live run completes, query the task DB → assert the task row is in `done` or `failed` (NOT `queued` or `running`). Verifies the worker actually drained the queue end-to-end.
4. `test_invA003_pgs_scores_row_carries_agent_rationale` — if the live run produced a `pgs_scores` row (i.e. compute succeeded) → query the DB → assert `agent_choice_rationale` + `requested_for_question` are non-empty + reflect what the agent actually said. (Permissive on the exact string; just non-empty + plausible.)

**Sketch**:

```python
import pytest
from tests._live_smoke.run import run_live_agent_session

@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GENOMECLAW_LIVE_TESTS") == "1",
    reason="live-smoke gated on GENOMECLAW_LIVE_TESTS=1",
)
def test_live_agent_amd_question_returns_prs_or_named_reason(canonical_run_dir):
    prompt = "Do I have an increased risk of losing eyesight when I age?"

    session = run_live_agent_session(
        prompt=prompt,
        run_dir=canonical_run_dir,
        timeout_s=600,  # 10 min — agent may poll the compute task for minutes
    )

    reply = session.reply_text.lower()
    tool_calls = session.tool_call_trace

    assert "http 422" not in reply, (
        f"Agent's reply contains HTTP 422 — the validation gate fix didn't land. "
        f"Reply: {session.reply_text[:500]}"
    )

    has_percentile = bool(re.search(r"\d+(\.\d+)?\s*(st|nd|rd|th)?\s*percentile", reply))
    has_named_reason = any(
        marker in reply
        for marker in [
            "scorefile_missing", "scorefile not", "calibration",
            "decline", "low match", "no overlap",
        ]
    )
    assert has_percentile or has_named_reason, (
        f"Agent reply has neither a PRS percentile nor a structured named reason. "
        f"Reply: {session.reply_text[:500]}"
    )
```

### Step 6.2 — GREEN: Wire the test

No new production code in Phase 6. The test is the entire deliverable. Phases 2–5 already produced the implementation that makes the test pass.

**Operational steps before running the test**:

1. Confirm the canonical Phase 7 run-dir has a valid `prs_compute_config.json` sidecar (per Phase 4). If absent, stage it from the operator-notes template.
2. Confirm PGS004606 (AMD) + PGS000137 (glaucoma) scorefiles are pre-staged under `reference_root/pgs_scorefile/`. If absent, run `genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS004606` + `PGS000137`.
3. Run the test once with the live-smoke env vars set. Confirm pass.

The first run hits the warm Tier 1 cache from smoke v23, so compute wall is ~5-20 min per PGS. Total test budget: 10 min (with `timeout_s=600`); if the agent invokes both PGS in series we may need to bump to 30 min.

### Step 6.3 — REFACTOR

No refactor pass for Phase 6 — there's no production code to clean up. If the agent's reply matching heuristic in test #1 ends up being flaky (PRS percentile regex too permissive / too restrictive), tighten it after the first GREEN run.

---

## Implementation Details

### Live-smoke harness contract

Phase 6 reuses the existing `tests/_live_smoke/run.py` pattern. The harness:
- Stands up the host service (host-side Uvicorn).
- Stands up the sandbox container with the plugin loaded.
- Invokes the agent with the given prompt.
- Captures the agent's reply + tool-call trace.
- Tears down both.

Phase 6's test calls `run_live_agent_session(prompt, run_dir, timeout_s)` + asserts on the returned `LiveAgentSession` (with `reply_text`, `tool_call_trace`, etc.).

### Test wall-clock budget

- Warm Tier 1 cache (post-smoke-v23): ~5-20 min per PGS.
- Cold Tier 2 (PGS-specific force-genotype + pgsc_calc): the dominant cost. Typically 3-15 min.
- Agent polling overhead: 5-30 s per poll; total polling ~1 min if the worker drains in 5 min.
- Network latency to LLM: ~5-10 s per turn.

**Default `timeout_s=600` (10 min)**. If the agent invokes both PGS004606 + PGS000137 in series, the test may genuinely need 20-30 min — Phase 6 will measure on first run + adjust.

### Test gating

- `pytest.mark.live` (marker, registered in `conftest.py` if not already).
- Skip unless `GENOMECLAW_LIVE_TESTS=1` (matches existing live-smoke pattern).
- Skip unless `OPENAI_API_KEY` (or the harness's required API key) present.
- Skip unless `GENOMECLAW_SANDBOX_IMAGE` present.
- NOT run in CI by default. Operator runs it manually after staging the sidecar + scorefiles.

### What "pass" means

The test passes if **all four assertions hold**. The bar is **the agent reaches a terminal state with a structurally-named outcome** — not necessarily a successful percentile compute. A `failed:scorefile_missing:PGS004606` result is a valid pass IF:
- The agent's reply explains what happened ("the scorefile isn't staged; ask the operator to fetch it").
- The reply does NOT contain `HTTP 422` literal.
- The task row is in `failed` (NOT `queued`).

This is the right bar because Phase 6 verifies the **plumbing**, not the operator's reference-staging readiness. If the operator hasn't fetched PGS004606, that's their action item — but Phase 6 still passes because the failure mode is structured + visible to the agent.

### Edge Cases to Handle

- **Agent doesn't invoke `genomeclaw_pgs_compute`** (e.g. it decides to decline PRS for AMD per INV-C001 v1.7 literature-immaturity): test #2 fails. Phase 6 then has to decide whether the agent's decline is the right behavior — if so, the test prompt should be adjusted to push toward compute (e.g. "compute the PRS percentile" rather than the more open-ended "do I have risk"). The 2026-05-23 trace shows the agent DID invoke compute on the open-ended prompt, so this should be stable.
- **Compute exceeds timeout**: tighten `timeout_s` in test #1, or accept the test will be slow + run rarely.
- **LLM hallucinates a percentile without invoking compute**: test #2 (tool-call trace assertion) catches this — if no `genomeclaw_pgs_compute` call happened, the percentile in the reply is fabrication + the test fails on assertion #2.

### Error Handling

No new error handling. Phase 6 surfaces existing failure modes through the agent's reply.

### Privacy / Egress Notes

Phase 6 uses the standard live-smoke configuration. The plugin egress surface is `OPENAI_API_KEY` → `api.openai.com` (or `ANTHROPIC_API_KEY` → `api.anthropic.com`); this is the named, user-configured agent egress that INV-P002 governs. No new boundary.

The privacy-safety-reviewer agent should NOT be invoked for Phase 6 specifically — it's a pure verification phase, no new egress, no new report wording.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/integration/test_live_agent_prs_compute_e2e.py` | CREATE | The 4 live-agent test cases |
| `docs/plans/active/agent-prs-compute-fix/work-notes.md` | MODIFY (final block) | Phase 6 completion + first live-run output excerpt |
| `docs/plans/completed/agent-prs-compute-fix/` | CREATE | Move the entire plan dir to `completed/` once Phase 6 is GREEN |
| `docs/reference/INVARIANTS.md` | UNCHANGED | No new invariants promoted by this plan (per the dev plan's "Proposed New Invariants" section: None) |

---

## Verification

```bash
# Pre-conditions (operator action — one-time per deployment)
genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS004606
genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS000137
ls "$(genomeclaw pipeline current-run)/prs_compute_config.json"  # must exist; staged per Phase 4 ops notes

# Run the live test
cd packages/toolkit
GENOMECLAW_LIVE_TESTS=1 \
  uv run pytest tests/integration/test_live_agent_prs_compute_e2e.py -v -s --timeout=1800
# Expect: 4/4 PASS

# Final full sweep (unit + integration + invariant + provenance + privacy)
GENOMECLAW_LIVE_TESTS=0 \
  uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: no regression.

# Plugin rebuild + tests (defensive — should already be green from Phase 2)
cd ../nemoclaw-plugin
npm run build && npm test
```

---

## Completion Criteria

- [ ] All 4 listed live-agent test cases pass against the canonical Phase 7 run-dir.
- [ ] The full toolkit suite (Phases 1–5 plus the new E2E test) is green.
- [ ] Plugin TS strict-mode build + 21/21 vitest still green.
- [ ] `work-notes.md` carries a final block with: the LLM's reply text, the tool-call trace excerpt, the resulting `pgs_compute_tasks` row's terminal state, the resulting `pgs_scores` row (if compute succeeded).
- [ ] Plan moved from `docs/plans/active/` to `docs/plans/completed/`.
- [ ] `development-plan.md` reflects the final implemented design (any divergences from the original plan documented in work-notes + the dev plan's Progress Tracking table).
- [ ] No `INVARIANTS.md` update needed (none proposed; verified in the dev plan).
- [ ] Open follow-ups explicitly listed in the final work-notes block:
  - Scorefile auto-fetch at compute time (out of scope).
  - Multi-sample compute (out of scope).
  - Operator CLI for the task DB (`genomeclaw pgs tasks ls`) (post-MVP).
  - AC8 coverage_qc / gene-list BED (orthogonal; tracked separately).

## Acceptance Criteria mapping (spec → phase)

| Spec AC | Phase | Status (when Phase 6 closes) |
|---------|-------|------------------------------|
| AC1: Phase 1's RED → GREEN; INV-A003 preserved | 2 | ✓ |
| AC2: Worker drains automatically; concurrency cap = 1 | 3 | ✓ |
| AC3: Worker invokes `compute_prs_with_coverage_fill(...)` | 4 | ✓ |
| AC4: `pgs_scores` + `findings` persistence | 4 | ✓ |
| AC5: Kill-switch (startup + per-task) | 3 (startup), 3+5 (per-task + log) | ✓ |
| AC6: Crash recovery + stale-running cleanup | 5 | ✓ |
| AC7: End-to-end agent live test | 6 | ✓ |

All 7 ACs met; plan closes.

## Next

Nothing — this is the terminal phase. After Phase 6 GREEN:

1. Move `docs/plans/active/agent-prs-compute-fix/` → `docs/plans/completed/agent-prs-compute-fix/`.
2. Append a closing note to `work-notes.md`.
3. Commit + push.

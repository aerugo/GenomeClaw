# Phase 3: Manual AC8 Verification Gate (automated replay harness deferred)

**Status**: Scope-reduced; awaiting manual verification
**Started**: 2026-05-28
**Completed**: <YYYY-MM-DD — populated when manual gate is run>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Verify the Phase 1 + Phase 2 prompt edits against the real rebuilt sandbox by re-running the verbatim muscle question that exposed Bug 1 + Bug 2 on 2026-05-27. The automated `tests/agent_replay/` harness originally scoped for this phase is **deferred to a follow-up plan**; the manual real-data gate is the highest-fidelity verification of the agent's prompt-following discipline and closes the loop on this plan.

## Scope Decision (2026-05-28)

The original Phase 3 plan called for a new `packages/toolkit/tests/agent_replay/` test surface with mocked tool-result envelopes + real `gpt-5.5` LLM calls + three scenario tests. After the Phase 2 RED → GREEN session, the implementation cost vs. value was reconsidered:

- **Cost**: ~200+ lines of new infrastructure (conftest + LLM driver + tool-schema translation + 3 fixture sets); real `gpt-5.5` API calls per test run (cost per CI invocation); model-nondeterminism flakiness risk; a brand-new test category to maintain.
- **Value vs. what already ships**:
  - Phase 1's prompt-contract test pins the Step 3 capability-claim bullet.
  - Phase 2's prompt-contract test pins the §INV-A005 catalogue + decompose rule.
  - Phase 2's trace-walker test catches forbidden-phrase confabulation in any future captured trace.
  - The actual reported bugs (1 + 2) were filed against the *prompt* discipline; the prompt-level tests close the loop.

**Conclusion**: an automated replay harness is valuable but premature without a clear regression-detection need beyond the existing surface. Deferred to:

- [agent-replay-harness-for-prompt-regression](../agent-replay-harness-for-prompt-regression.md) (follow-up plan stub filed 2026-05-28).

Phase 3 reduces to the manual real-data gate (AC8 of the spec).

## In Scope

- Re-run the verbatim muscle question against the rebuilt sandbox after Phase 1 + Phase 2 ship.
- Capture the trace + reply text in this plan's `work-notes.md`.
- Verify three behavioral assertions match expected post-fix behavior.
- Update [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md)'s `INV-A005` **How to verify** section to point at the new tests.

## Out of Scope

- Automated agent-replay tests under `packages/toolkit/tests/agent_replay/` — deferred to the follow-up plan above.
- Synthetic tool-result envelope mocking — deferred.
- Per-scenario LLM-driven assertions — deferred.

---

## Manual AC8 Gate — Verbatim Muscle Question

### Setup checklist

- [ ] Host service is running: `bin/genomeclaw host service` returns HTTP 200 on `/v1/health`.
- [ ] Sandbox image is built from the current branch (the prompt with Phase 1 + Phase 2 edits must be baked into the image).
- [ ] `OPENAI_API_KEY` is exported and the sandbox config points at `gpt-5.5` with max thinking depth (per `_live_smoke/run.py`'s pinned model).

### Verbatim user prompt

Send exactly this message to the agent (no edits, no abbreviation):

> Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet.

### Expected behavioral assertions

Capture the agent's reply trace under [docs/reports/](../../../../reports/) following the existing `*.trace.json` convention, then verify:

1. **No stale-capability citation if live tools work.** Reply does NOT contain phrases like *"GenomeClaw is currently unavailable"* or *"PGS000027 not computable"* when `genomeclaw_status` returns HTTP 200 in the same turn. If `_pgs_list` returns PGS000018 (or any PRS the agent has a stale memory note about), reply MUST cite the live percentile instead of the stale claim.

2. **Failure phrases match the catalogue.** Any failure narrative in the reply must match its required structural signal from the §INV-A005 catalogue at [agent-system-prompt.md:170–204](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L170):
   - "argument-shape guard fired" → only if `rejectIfPlaceholder` prose (`placeholder string`) is in this turn's tool-result text.
   - "host returned status=failed" → only if `wrapHostResponse` prose is present.
   - "HTTP connection refused" / "network unreachable" → only if `Failed to connect` / `fetch failed` / `genomeclaw-service ... -> HTTP 5xx` is in the tool-result text.
   - "TypeBox rejected the parameters" → only if a TypeBox validator error appears in the tool-result text.

3. **Per-tool decomposition.** If multiple tool calls fail in the same turn, reply names each failure mode separately based on its specific tool-result text. No homogenized *"all my GenomeClaw calls failed"* framing into a single guess.

### Capture

Save the trace as `docs/reports/manual-ac8-muscle-question-<YYYY-MM-DD>.trace.json` and append a summary to this plan's [work-notes.md](../work-notes.md) under the "Manual AC8 Gate" section.

### Trace-walker re-run

After the trace is captured (dated ≥ 2026-05-28 — past the `INV-A005` binding date), re-run the trace-walker:

```bash
cd packages/toolkit
uv run pytest tests/invariants/test_invA005_no_serialization_bug_confabulation.py -xvs
```

The captured trace should be parametrized over and pass — no forbidden catalogue phrase should appear without its matching structural signal.

---

## Invariants Verified by the Manual Gate

- **INV-A005** Tool-Failure Narratives Match Trace Evidence (v1.21) — behavioral check against a real captured trace.
- **INV-A002** Synthesis Reasoning Floor v1.8 bullet 3 — behavioral check that the Step 3 capability-claim bullet fires correctly when the agent has a stale memory note that contradicts live tool output.

The Phase 1 + Phase 2 *content* tests (prompt-contract + trace-walker) provide the regression coverage; the manual gate provides the end-to-end live-LLM verification.

---

## Documentation Updates (post-gate)

- [ ] [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) — update `INV-A005` **How to verify** section to add references to:
  - `test_invA005_system_prompt_carries_failure_phrase_catalogue` (Phase 2 catalogue contract)
  - `test_invA005_system_prompt_carries_decompose_per_tool_rule` (Phase 2 decompose rule contract)
  - `test_invA005_trace_walker_flags_argument_shape_guard_without_signal` (Phase 2 synthetic trace)
  - `test_invA005_trace_walker_recognizes_safecall_catchblock_prose_as_real_failure` (Phase 2 signal predicate)
  - `test_invA002_step3_memory_validation_special_cases_capability_claims` (Phase 1 Step 3 bullet)

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/reports/manual-ac8-muscle-question-<YYYY-MM-DD>.trace.json` | CREATE | Captured manual-gate trace. |
| [docs/plans/completed/agent-stale-memory-and-failure-mode-confabulation/work-notes.md](../work-notes.md) | MODIFY | Append "Manual AC8 Gate" summary section. |
| [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) | MODIFY | Update `INV-A005` **How to verify** with Phase 1 + Phase 2 test references. |
| [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../../agent-replay-harness-for-prompt-regression.md) | CREATE | Follow-up plan stub for the deferred automated harness. |

---

## Completion Criteria

- [ ] Manual gate executed against the rebuilt sandbox; verbatim muscle question sent.
- [ ] Captured trace saved under `docs/reports/`.
- [ ] All three behavioral assertions verified.
- [ ] Trace-walker re-run passes on the new trace.
- [ ] `work-notes.md` populated with the trace excerpt + assertions check.
- [ ] `INV-A005` **How to verify** updated in `INVARIANTS.md`.
- [ ] Follow-up plan stub filed for the deferred automated harness.
- [ ] Plan moved from `docs/plans/active/` to `docs/plans/completed/`.

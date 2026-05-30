# Agent-Replay Harness for Prompt Regression — Single-File Plan (stub) — **SUPERSEDED**

**Status**: **Superseded 2026-05-28** by [inv-a005-structural-faithfulness](inv-a005-structural-faithfulness/). This stub proposed a scenario-test harness built on top of `_FORBIDDEN_PHRASES` enumeration. The user's 2026-05-28 rule ("never rely on enumeration of 'forbidden phrases'") makes the approach non-viable. The replacement architecture (structural envelopes from the plugin + quote-verbatim prompt discipline + structural trace inspection + optional LLM-judge) is in the sister plan's Phases 1–4. **This file is kept for historical context only — do NOT implement it as-is.** Move to `completed/` once `inv-a005-structural-faithfulness` Phase 3 lands.

**Created**: 2026-05-28
**Parent**: deferred from Phase 3 of [agent-stale-memory-and-failure-mode-confabulation](../completed/agent-stale-memory-and-failure-mode-confabulation/) (Phases 1+2 shipped; Phase 3 reduced to a manual AC8 gate; this stub originally tracked the deferred automated harness — now superseded).

---

## Motivation

The parent plan's Phase 1 + Phase 2 shipped prompt-content guardrails (Step 3 capability-claim bullet + §INV-A005 failure-phrase catalogue) and content-gate tests (prompt-contract + trace-walker). What they do NOT provide is **automated behavioral regression coverage** — a test that exercises the agent under the prompt against captured tool-result scenarios and asserts the reply text obeys the catalogue + Step 3 rules.

Without this, behavioral regressions in the agent's prompt-following are only caught when:

1. A captured trace makes it into `docs/reports/` and trips the trace-walker — relies on someone running the agent against the right scenario.
2. The manual muscle-question gate is re-run during a sweep — relies on operator discipline.

An automated replay harness would catch these regressions in CI without operator effort. It is **valuable but not load-bearing** for the original bug fix — hence deferred from the parent plan rather than dropped.

## What this plan would build

A new test surface under `packages/toolkit/tests/agent_replay/`:

- **Conftest**: skip-when-`GENOMECLAW_REPLAY_LLM`-not-set guard (preserves `INV-P001` default-no-egress); LLM-client fixture pinned to `gpt-5.5` (GenomeClaw's standard model — no cheaper substitutes).
- **Driver** (~150 lines): loads [agent-system-prompt.md](../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md), composes messages, dispatches mocked tool calls against canned envelopes, captures the final assistant text. Implementation candidates:
  - **Option A**: `httpx` against the OpenAI Chat Completions API directly (`httpx>=0.27` is already a toolkit dep). Self-contained, no SDK install. Translates a small set of plugin tools (the ones the scenarios exercise) into OpenAI tool-call schemas.
  - **Option B**: extend [tests/_live_smoke/run.py](../../../packages/toolkit/tests/_live_smoke/run.py) with a derived-store variant + extra_workspace_files pre-staging for scenarios 1+2; defer scenario 3 (synthetic `rejectIfPlaceholder`) as awkward-to-engineer.
- **Three scenario tests** matching the parent plan's original AC6:
  1. `test_agent_supersedes_stale_capability_memory_when_live_tool_contradicts` — stale memory note + `_pgs_list` returning the PRS the note said was missing. Asserts: reply cites the live percentile; does NOT cite the stale "unavailable" claim as ongoing.
  2. `test_agent_describes_network_failures_correctly_not_as_guard_rejection` — every `genomeclaw_*` tool returns `safeCall` catch-block prose. Asserts: reply uses catalogue Row 3 phrasing ("HTTP connection refused" / "network unreachable"); does NOT reach for Row 1 ("argument-shape guard fired").
  3. `test_agent_decomposes_mixed_outcome_failures_per_tool` — gene calls succeed; `genomeclaw_pgs_compute` returns `rejectIfPlaceholder` prose. Asserts: reply names FTO's variant count; scopes the rejection to the one PRS call.

## Acceptance Criteria (sketch)

- [ ] Default `pytest tests/agent_replay/` emits `SKIPPED` only (no egress under default config).
- [ ] With `GENOMECLAW_REPLAY_LLM=gpt-5.5` and `OPENAI_API_KEY` set, all three scenarios pass against the production prompt.
- [ ] Each test cites its enforced `INV-xxx` (INV-A005 / INV-A002 / INV-P001) in name or docstring.
- [ ] Pinned model is `gpt-5.5` — do not substitute cheaper models (project rule).

## Out of scope

- Adding the OpenAI SDK as a toolkit dep — use `httpx` instead.
- Substituting `gpt-5.5` with a cheaper model "for testing" — explicitly rejected by the user 2026-05-28.
- Reproducing every scenario the original parent plan listed — Options A or B may force scenario 3 to remain manual.

## Open questions

- [ ] **Q1**: Option A (`httpx` → OpenAI directly) vs. Option B (extend `_live_smoke/`). Trade-off: A is lighter but duplicates harness mechanics; B is heavier but reuses the canonical pattern.
- [ ] **Q2**: How does the harness avoid leaking real LLM cost in CI? `GENOMECLAW_REPLAY_LLM` env-var gate is the obvious mechanism; needs CI-policy decision before enabling.
- [ ] **Q3**: Per-scenario flake budget — at `temperature=0` + a pinned seed where supported, `gpt-5.5` is mostly deterministic but not fully. What flake rate is acceptable and how does the harness surface a flake vs. a real regression?

## Trigger for prioritization

This plan should be prioritized when **any** of the following lands:

- A regression in agent prompt-following surfaces in production (captured trace tripping the trace-walker, or operator-observed confabulation) — proves the prompt-content tests aren't sufficient.
- Phase 1 + Phase 2 prompt edits need to evolve (catalogue grows, Step 3 changes structurally) — adding behavioral coverage before the change reduces regression risk.
- A separate plan introduces a NEW agent-cognition invariant (`INV-A006`, etc.) that's hard to enforce at the prompt-content layer — the replay harness becomes the natural home for it.

Until one of those fires, the parent plan's content-gate tests + the manual muscle-question gate are the canonical verification.

## Related plans

- [agent-stale-memory-and-failure-mode-confabulation](../completed/agent-stale-memory-and-failure-mode-confabulation/) — parent plan; phases 1+2 shipped, Phase 3 manually verified.

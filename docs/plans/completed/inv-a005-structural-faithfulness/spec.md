# Feature: INV-A005 Structural Faithfulness (replaces phrase-list enforcement)

**Status**: Draft
**Created**: 2026-05-28
**Owner**: aerugo
**Related Plans**:
- [agent-stale-memory-and-failure-mode-confabulation (completed)](../../completed/agent-stale-memory-and-failure-mode-confabulation/) — Phases 1+2 shipped a `_FORBIDDEN_PHRASES` tuple + §INV-A005 prompt catalogue. The AC8 manual gate (2026-05-28) showed the agent invented a paraphrase ("object-shape serialization error") not on the list; both the test and the prompt rule are unable to cover the agent's full paraphrase-space.
- [eliminate-forbidden-phrase-enumeration](../eliminate-forbidden-phrase-enumeration/) — sister plan filed at the same time; generalizes this work into a project-wide rule and audits other phrase-enumeration sites.
- [agent-replay-harness-for-prompt-regression (stub)](../agent-replay-harness-for-prompt-regression.md) — earlier follow-up stub; **superseded by this plan** (its proposed scenario-test scaffolding becomes irrelevant once `_FORBIDDEN_PHRASES` is gone). Mark obsolete on Phase 3 completion.

---

## Goal

Replace the `INV-A005` enforcement mechanism — currently a substring/regex match against a hard-coded `_FORBIDDEN_PHRASES` tuple + a §INV-A005 prompt-catalogue table — with a **structural** and **semantic** mechanism: the plugin returns structured error envelopes; the agent reasons over raw structured fields across multiple turns; verification is by structural trace inspection and/or LLM-judge evaluation, not by enumerating banned wording.

## Background

The 2026-05-27 muscle-question regression sweep filed two bugs (stale-memory bias + failure-mode confabulation). The follow-up plan (`agent-stale-memory-and-failure-mode-confabulation`) shipped Phases 1+2 in 2026-05-28: a §INV-A005 catalogue table in the agent prompt + a `_FORBIDDEN_PHRASES` tuple in the trace-walker test.

The AC8 manual gate against the rebuilt sandbox produced three findings the prior plan documents:

1. **Catalogue incomplete**: the agent invented **"object-shape serialization error"** for a network-failure cluster — same confabulation class, paraphrase not on the list. Enumeration is whack-a-mole.
2. **Decompose rule half-honored**: the agent decomposed the first failure cluster correctly but homogenized the second — discipline didn't transfer across clusters within one reply.
3. **Trace-walker structurally circular**: `openclaw agent --json` only emits the agent's reply as a payload; per-tool-call envelopes aren't surfaced; the predicate that's supposed to license forbidden phrases ends up reading the agent's own reply to decide whether the reply is allowed.

User verdict (2026-05-28): *"this phrase matching methodology seems useless"* + *"never rely on enumeration of 'forbidden phrases'"* + *"rely on the OpenClaw agent to receive raw returns and evaluate multi-turn on a loop, calling more tools as it needs more info."*

This plan implements that pivot for `INV-A005`.

## Acceptance Criteria

- [ ] **AC1**: The plugin's three failure-path helpers return **structured error envelopes**, not prose paraphrases. `rejectIfPlaceholder` returns `{status: "failed", error_type: "placeholder_rejected", arg_name, value, advisory}` (advisory is a human-readable string, not load-bearing). `wrapHostResponse` returns `{status: "failed", error_type: "host_failure", http_path, host_status, host_error, advisory}` for status=failed envelopes. `safeCall`/`safePost` catch-blocks return `{status: "failed", error_type: "network_error" | "http_error", details: {...}, advisory}`.
- [ ] **AC2**: The agent system prompt's §INV-A005 section **no longer carries the failure-phrase catalogue table**. Replaced with rule-based guidance: "When a tool call fails, identify the structured `error_type` field, quote the relevant structured field values verbatim in your reply before paraphrasing, and call additional tools if you need more context."
- [ ] **AC3**: The §INV-A005 section explicitly authorizes (in fact, encourages) the multi-turn investigation loop: if the agent encounters an unfamiliar failure shape, it should call additional diagnostic tools (`genomeclaw_status`, retry, fetch logs) rather than guess at the cause from prior context.
- [ ] **AC4**: `_FORBIDDEN_PHRASES`, `_STRUCTURAL_FAILURE_SIGNALS`, `_GENOMECLAW_HTTP_ERROR_PATTERN`, and `_CATALOGUE_ROWS` are **deleted** from the toolkit's test code. The `test_invA005_*` parametrized tests using them are deleted.
- [ ] **AC5**: Replacement verification: a **structural trace-walker** asserts that for every failure-narrative paragraph in the agent's reply, the trace's per-tool-call records carry a matching `error_type` field. (Depends on a prerequisite — see Open Q1.)
- [ ] **AC6**: Optional / scope-pending LLM-judge harness: a second-model evaluator passes `(trace, reply)` to `gpt-5.5` and asks "is the reply consistent with the tool calls in the trace?" — replaces the catalogue contract test as the semantic correctness gate. Skip-by-default per `INV-P001` (gated by env var; consistent with the deferred-replay-harness pattern).
- [ ] **AC7**: `INV-A005` rule text is rewritten in `docs/reference/INVARIANTS.md` to reflect the new mechanism: *"Tool-failure narratives must trace to a structured `error_type` field in this turn's tool-result records, and must quote at least one field verbatim. Verified by structural trace inspection + LLM-judge."* Old prose-paraphrase phrasing removed.
- [ ] **AC8**: Re-run the AC8 manual gate (muscle question with host service down) and verify the agent quotes the `error_type` field verbatim per `error_type`, decomposes per tool, and does NOT homogenize across clusters. No substring check on banned phrases — instead, inspect the trace's tool-call records (now structured) for `error_type` consistency with the reply text.

## Applicable Invariants

- **INV-A005** Tool-Failure Narratives Match Trace Evidence — this plan rewrites the rule's enforcement mechanism. Rule text shifts from "specific banned phrases require specific signal strings" to "agent's failure narrative must trace to a structured `error_type` field + quote at least one field verbatim." Invariant ID stays at A005; version bumps to v1.22.
- **INV-A002** Synthesis Reasoning Floor (v1.8 bullet 3) — the capability-claim Step 3 bullet from Phase 1 of the prior plan stays. It's structural (asks the agent to re-test capability in-turn before citing stale memory), not phrase-based.
- **INV-A001** Agent Memory Provenance — unchanged.
- **INV-P001** Privacy Default — the optional LLM-judge harness in Phase 4 calls `gpt-5.5` per project pinning. Default-skip when env var unset; matches the existing `_live_smoke/` egress pattern.

## Proposed New Invariants

- **NEW INV-A006 (proposed)**: *Plugin Tool-Result Returns Structured Envelopes, Not Prose Paraphrases.* The agent must receive structured failure data (`error_type` + structured details) so it can reason without substring-matching prose. Rationale: this is the architectural counterpart of the AC1 plugin change; promoting it to an invariant prevents future tool wrappers from regressing back to prose-only returns. Defer the invariant promotion to Phase 1 + 2 landing; promote in Phase 3 (rule + discovery test).

## Technical Requirements

### Source Data Inputs

- Agent system prompt: [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) §INV-A005 (lines 170–204 of current).
- Plugin source: [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) — `rejectIfPlaceholder` (lines 297–333), `wrapHostResponse` (lines 220–244), `safeCall` / `safePost` (lines 185–197, 254–266).
- Tests to delete or rewrite:
  - [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — full rewrite (structural walker, no `_FORBIDDEN_PHRASES`).
  - [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — remove `_CATALOGUE_ROWS` + `test_invA005_system_prompt_carries_failure_phrase_catalogue`. Keep INV-A005 marker-presence test as a backstop.

### Derived Outputs

- Updated plugin source returning structured envelopes.
- Updated agent system prompt with new §INV-A005 guidance + multi-turn investigation rule.
- New structural trace-walker test.
- Optional LLM-judge harness (Phase 4; may defer).
- Updated `INVARIANTS.md` (rule text v1.22 + optional `INV-A006`).

### Schema / Migration Impact

- **None for derived stores.** Plugin tool-result schema changes (from prose to structured), but tool-result envelopes are ephemeral request/response payloads, not persisted derived data.
- Plugin's TypeScript types change: introduce `ToolFailureEnvelope` interface; update return types of `rejectIfPlaceholder` / `wrapHostResponse` / `failedTextResult`.

### Pipeline / Workflow Impact

- **None.** Host service / pipeline unchanged. Plugin tool-result format changes are agent-facing only.

### Agent / UX Impact

- Agent prompt's §INV-A005 section grows or stays similar in size but shifts from enumeration to rule-based. The catalogue table is removed; replaced with: structured-envelope contract + "quote at least one field verbatim" rule + multi-turn investigation guidance.

### External Dependencies

- None for Phases 1–3. Phase 4 (LLM-judge harness) depends on the existing `gpt-5.5` egress allowlist.

## Privacy & Safety Considerations

- **Boundary scan**: no new egress in Phases 1–3. The plugin's tool returns change shape but the same data flows to the same agent. Phase 4's optional LLM-judge harness uses the existing OpenAI provider (already authorized).
- **Default-off remote calls**: LLM-judge gated behind `GENOMECLAW_REPLAY_LLM=gpt-5.5` env var; default `pytest` runs do not emit egress.
- **Redaction surface**: the structured envelope carries the same data as the prose paraphrase did — no new sensitive fields exposed. `arg_name` / `value` in `rejectIfPlaceholder` envelopes might carry user-genomic data (a gene symbol the agent was about to query); the existing prose did too. No new redaction needed.
- **Clinical escalation**: indirect — better failure narratives mean better operator-visible signals when a tool genuinely fails on a clinical-escalation finding. No new escalation marker.

## Out of Scope

- **Eliminating phrase-enumeration project-wide** — that's the sister plan [eliminate-forbidden-phrase-enumeration](../eliminate-forbidden-phrase-enumeration/). This plan is the INV-A005 pilot case.
- **Restructuring success returns from the plugin** — only failure-path returns change. Success returns (HTTP 200 bodies) are already structured.
- **Surfacing per-tool-call records in `openclaw agent --json` output** — that's a prerequisite for AC5's structural trace-walker. If upstream openclaw doesn't expose this, the structural test relies on the `meta.toolSummary` aggregate or a custom trace-capture path. **Open Question Q1 below.**
- **Auto-write of superseding memory notes** — out of scope (was Q2 in the parent plan; default block-only stays).

## Dependencies

- Parent plan's Phase 1 (Step 3 capability-claim bullet) stays in the prompt; this plan builds on it.
- The §INV-A005 catalogue removed here is the same one the parent plan added in Phase 2. The catalogue's worked examples (anti-pattern / target pattern) get rewritten, not removed entirely — they shift from "don't use phrase X" to "quote `error_type` verbatim."

## Open Questions

- [ ] **Q1 — Per-tool-call records in trace**: does `openclaw agent --json` expose per-call records (tool name, args, result envelope)? Current evidence (manual AC8 trace) suggests **no** — only final reply + `meta.toolSummary` aggregate. If correct, AC5's structural walker can't fire unless we either (a) use the embedded-fallback runner's trace capture path (which may differ), (b) get upstream openclaw to surface tool-call records in `--json` mode, or (c) capture the trace via a different harness (`_live_smoke/`-style with WebSocket interception). Resolve before starting Phase 3.
- [ ] **Q2 — LLM-judge harness scope**: include in this plan (Phase 4), or file as a separate follow-up? Argument for including: closes the loop on AC6 directly. Argument for separating: large new test surface (~200 lines + real LLM cost per CI run). Default for this plan: **include as Phase 4 but mark scope-reducible** — if the structural walker in Phase 3 turns out to be sufficient, Phase 4 can be deferred without breaking the rest.
- [ ] **Q3 — `INV-A006` promotion**: do we add a new invariant for "plugin returns structured envelopes" or extend `INV-A005` to cover both the agent-side and plugin-side discipline? Default: **propose `INV-A006`** because the rules apply at different layers (one to the agent, one to the plugin) and conflating them weakens both. Promote in Phase 3.
- [ ] **Q4 — Backwards compat for the `failedTextResult` helper**: existing tests in [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts) may assert on the prose strings. Will need updating in Phase 1. Audit + update during Phase 1 RED.

# Feature: Agent Synthesizes Rich Tool-Result Data (Replaces Verbatim-Quoting)

**Status**: Draft
**Created**: 2026-05-28
**Owner**: aerugo (user-driven correction)
**Related Plans**:
- [inv-a005-structural-faithfulness (completed)](../../completed/inv-a005-structural-faithfulness/) — the v1.22 work this plan **corrects**. Phases 1 (plugin envelopes) + 3 (`INV-A006` discovery test) stay; Phase 2 (verbatim-quoting prompt rewrite) + Phase 3's structural walker (literal `error_type` token check) **revert** in favor of analyze-and-present discipline + LLM-judge.
- [eliminate-forbidden-phrase-enumeration (completed)](../../completed/eliminate-forbidden-phrase-enumeration/) — `INV-V001` stays. LLM-judge is one of its three sanctioned alternatives.
- [agent-replay-harness-for-prompt-regression (completed/superseded)](../../completed/agent-replay-harness-for-prompt-regression.md) — was superseded by `inv-a005-structural-faithfulness`. This plan **un-defers + un-supersedes** the LLM-judge half of that work as a load-bearing component.
- [agent-stale-memory-and-failure-mode-confabulation (completed)](../../completed/agent-stale-memory-and-failure-mode-confabulation/) — original bug origin (AC8 muscle-question regression). `INV-A002` Step 3 capability-claim bullet (Phase 1) stays unchanged.

---

## Goal

Correct the architectural mistake baked into `INV-A005` v1.22: the prompt forced the agent to **quote structured fields verbatim** (e.g., `` `error_type: network_error` ``) and the trace-walker tested for literal `error_type` token presence. That's mechanical transcription, not synthesis. The intended architecture is:

1. **Host service + plugin return RICH, COMPLETE structured data** — full trace, full query results, full analysis output, full diagnostic context. The agent sees what the tool actually did, not a pre-summarized envelope.
2. **Agent reasons over the rich data and INTERPRETS it for the user** in plain, understandable language. Translation, not transcription. Synthesis, not quotation.
3. **Verification is semantic (LLM-judge) or behavioral (multi-turn discipline)** — never "did the reply contain literal token X."

## Background

User correction 2026-05-28, after running the Stage-2 AC8 gate of `inv-a005-structural-faithfulness` and seeing the result:

> "The Host tool should return the whole trace to the agent as well as all results of analysis and queries etc. But the agent should definately analyze and present those to the user in an understandable manner, not just repeat verbatim."

What I shipped in `INV-A005` v1.22:
- Prompt: *"Your reply MUST contain at least one backtick-quoted excerpt of the actual `error_type` value or a structured detail field value"*
- Trace-walker: asserts every `error_type` value that fired in the trajectory appears literally in the reply text.

The AC8 gate "passed" with the agent saying *"`error_type: network_error` with `raw_error: fetch failed`"* — robotically quoting envelope fields. The user reads this as transcription, not synthesis. A genome interpretation system that talks like a JSON dump is not the design.

What the user wants instead: the agent should have ALL the diagnostic data (trace, query results, analysis), and synthesize a user-facing answer. If GenomeClaw is unreachable, the agent says "I couldn't reach the host service this turn — here's what I can offer from general guidance" in plain language, NOT "tool call returned `error_type: network_error` with `raw_error: fetch failed`."

This plan corrects the architecture while preserving what's still right:

**Kept (don't undo)**:
- `INV-A006` — plugin returns structured envelopes. The agent benefits from typed discriminators even when not quoting them.
- `INV-V001` — project-wide rule against phrase enumeration. LLM-judge is one of its three sanctioned alternatives.
- `INV-A002` Step 3 capability-claim bullet — structural, not quote-based.
- `scripts/sandbox-up.sh` + sandbox-rebuild flow.
- Trajectory-file capture convention.

**Corrected (this plan rewrites)**:
- `INV-A005` v1.22 → v1.23: drop the verbatim-quoting mechanism; new rule is *"agent synthesizes a faithful, understandable presentation"* verified by LLM-judge.
- `§INV-A005` prompt section: rewrite from "quote structured fields verbatim" to "analyze the rich data and present it understandably."
- `test_invA005_v122_reply_quotes_error_type_for_every_failure`: delete the literal-token check; replace with LLM-judge.
- `test_invA005_v122_system_prompt_teaches_quote_verbatim_discipline`: rewrite — the prompt should NOT teach verbatim quoting.

**Extended (this plan adds)**:
- Host service tool responses to carry RICHER diagnostic data (trace, command logs, intermediate results) so the agent has more to synthesize. Today's responses are often minimal.
- LLM-judge harness (formerly Phase 4 of `inv-a005-structural-faithfulness`, deferred at Stage 5). Un-defer; it's load-bearing here.

## Acceptance Criteria

- [ ] **AC1**: Host service tool responses carry **rich diagnostic data** for both success and failure paths. For `genomeclaw_pgs_compute` failures, the response includes the nextflow command, partial trace, stage at which it failed, etc. — not just `{"status":"failed","error":"<code>"}`. For success paths, the response includes computation metadata (effective row count, matched variants, etc.) — not just the final percentile. (Per-tool detail in Phase 1 + 2 plans.)
- [ ] **AC2**: Plugin's tool wrappers forward host responses without truncation. `safeCall`'s `jsonResult(payload)` path is verified to pass the full payload; failure-path envelopes carry the full diagnostic detail in structured fields (extending `ToolFailureEnvelope`).
- [ ] **AC3**: Agent system prompt's §INV-A005 section is rewritten to teach: *"You have rich tool-result data. Analyze it. Present clear, natural-language findings to the user. Structured fields are for YOUR reasoning, not for verbatim insertion into your reply."* The verbatim-quoting requirement is **removed**.
- [ ] **AC4**: `test_invA005_v122_reply_quotes_error_type_for_every_failure` is **deleted**. Replaced with `test_invA005_v123_reply_is_faithful_to_trajectory` — LLM-judge-based: given `(trajectory, reply)`, the judge confirms the reply is faithful and understandable.
- [ ] **AC5**: `test_invA005_v122_system_prompt_teaches_quote_verbatim_discipline` is **deleted**. Replaced with `test_invA005_v123_system_prompt_teaches_analyze_and_present_discipline` — asserts the prompt teaches analyze-and-present (positive: mentions "analyze" / "present" / "interpret" / "understandable" / "plain language" / etc.) and does NOT mandate verbatim quoting (negative: no "MUST contain backtick-quoted excerpt" or equivalent).
- [ ] **AC6**: LLM-judge harness lives under `packages/toolkit/tests/agent_replay/` with the same env-gated default-skip pattern as the live-smoke harness (`GENOMECLAW_REPLAY_LLM=gpt-5.5` to enable). Calls `gpt-5.5` to judge `(trajectory, reply)` pairs.
- [ ] **AC7**: `INV-A005` is rewritten to v1.23 in `INVARIANTS.md`. New rule: *"Agent reply that describes tool-call outcomes MUST be a faithful, understandable interpretation of the rich tool-result data. Verified by LLM-judge against the trajectory file."* The v1.22 verbatim-quoting language is removed.
- [ ] **AC8**: Re-run the AC8 muscle-question gate against the post-fix sandbox. The agent's reply uses **natural language** to describe what happened — NOT mechanical "error_type: network_error" transcription. LLM-judge confirms the reply is faithful + understandable. Capture the new trace alongside the prior (verbatim-era) trace for side-by-side comparison.
- [ ] **AC9**: All existing tests still pass (`INV-A006` discovery, `INV-V001` discovery, plugin envelope tests, prompt-contract tests for unrelated invariants).

## Applicable Invariants

- **INV-A005** v1.23 (this plan's promotion) — rewrites v1.22's mechanism. Faithful synthesis verified semantically, not by literal-token checks.
- **INV-A006** Plugin Tool-Result Returns Structured Envelopes — **unchanged**. The envelope shape stays right. This plan only extends the envelopes with richer detail fields.
- **INV-V001** Verification Mechanisms Must Not Enumerate Forbidden Phrases — **honored**. LLM-judge is one of the three sanctioned alternatives. The new test is explicitly NOT phrase enumeration.
- **INV-A002** Synthesis Reasoning Floor v1.8 bullet 3 — **unchanged**. Step 3 capability-claim bullet is structural (about validating memory notes against live data), not about quote-verbatim.
- **INV-P001** Privacy Default — LLM-judge calls `gpt-5.5` (already in the configured-egress allowlist). Default-skip when env var unset.

## Proposed New Invariants

**Potentially** `INV-D010` (Tool-Result Richness): tool wrappers in any GenomeClaw plugin MUST return the full diagnostic context the host service produced (trace, command, partial logs, stage) rather than a pre-summarized minimal payload. The agent decides what's relevant; the wrapper doesn't pre-filter.

Decide during Phase 3 — if the host-service + plugin changes feel like a single-plan scope, promote `INV-D010`. If they're naturally a follow-up (multi-plugin discipline question), defer the invariant.

## Technical Requirements

### Source Data Inputs

- Host service Python source under `packages/toolkit/src/genomeclaw_toolkit/service/` (routes, response models).
- Plugin TypeScript at [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) — current `ToolFailureEnvelope` shape + success-path `jsonResult` pass-through.
- Agent system prompt at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — current §INV-A005 v1.22 section.
- Test files:
  - [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — delete the literal-token test.
  - [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — rewrite the quote-verbatim test.

### Derived Outputs

- Extended host-service response models (richer detail fields).
- Extended plugin `ToolFailureEnvelope` variants (more detail in each).
- Rewritten §INV-A005 prompt section.
- New `packages/toolkit/tests/agent_replay/` directory with LLM-judge driver + scenario tests.
- Updated `INVARIANTS.md` v1.24 (INV-A005 v1.23 rewrite + optional INV-D010 promotion).

### Schema / Migration Impact

- **Host-service response shape**: extension only (additive fields). Existing clients keep working; new fields surface for the agent.
- **Plugin envelope shape**: extension only (more fields inside the discriminated-union arms). Existing tests + the `INV-A006` discovery test stay green.
- **No derived-store schema changes.**

### Pipeline / Workflow Impact

- **None.** Tool-result envelopes are ephemeral. Host service code changes are response-shape changes only.

### Agent / UX Impact

- **Substantial.** The agent's reply style changes: from robotic JSON-field transcription to natural-language synthesis. Operator-facing logs (the `advisory` field) become less load-bearing — they're for human spot-checking, not for the agent's reply construction.

### External Dependencies

- LLM-judge calls `gpt-5.5` (already in egress allowlist; same model as the agent).

## Privacy & Safety Considerations

- **Boundary scan**: LLM-judge calls `gpt-5.5` with `(trajectory, reply)` as input. The trajectory may carry genomic context (gene symbols, PRS IDs, query results). These are the same payloads the agent already sees + reasons over; the judge is a second pass over the same data with the same egress destination. No new sensitive-data surface.
- **Default-off remote calls**: LLM-judge gated by `GENOMECLAW_REPLAY_LLM=gpt-5.5` env var. Default `pytest` runs make no LLM calls.
- **Redaction surface**: n/a — same payloads as the live-smoke harness.
- **Clinical escalation**: indirect — better tool-result richness gives the agent more context for clinically-careful presentation. No new escalation marker.

## Out of Scope

- **Replacing INV-A006** — the structured-envelope contract stays. This plan extends the envelopes; doesn't replace them.
- **Replacing INV-V001** — methodology rule stays. LLM-judge IS a sanctioned alternative under V001.
- **Removing the trajectory-file capture convention** — still useful (LLM-judge reads it).
- **Refactoring the live-agent snapshot tests** (`test_live_story9_*`, `test_live_story10_*`) annotated as `INV-V001-backstop` — separate follow-up plan if they become regression burdens.
- **Building behavioural tool-call replay harness with mocked envelopes** — the LLM-judge variant we're un-deferring is the simpler version (judge over real captured trace). Mocked-envelope scenario tests stay deferred.

## Dependencies

- `INV-A006` already shipped (plugin envelopes). This plan extends.
- `INV-V001` already shipped (project rule). This plan honors.
- `gpt-5.5` egress allowlist (already in place via `_live_smoke/`).

## Open Questions

- [ ] **Q1 — Host-service response richness scope**: which tool responses need extension? `genomeclaw_pgs_compute` failures clearly do (need nextflow trace + command). What about `genomeclaw_pgs_compute_status`, `genomeclaw_gene`, `genomeclaw_findings`? Need a per-tool audit (Phase 1).
- [ ] **Q2 — LLM-judge prompt design**: what exactly does the judge evaluate? "Faithful + understandable" needs operational criteria. Draft the judging prompt + iterate on the AC8 captured traces (pre-fix + post-fix) as ground truth.
- [ ] **Q3 — INV-D010 promotion**: invariant or just a discipline note in this plan? Default: defer to Phase 3 review.
- [ ] **Q4 — Judge nondeterminism budget**: how much flake from `gpt-5.5` (even at `temperature=0`) is acceptable? Probably need to assert on pass/fail with retry-once-on-marginal logic. Resolve during Phase 4.

# INV-A005 Structural Faithfulness — Work Notes

**Feature**: Replace `INV-A005`'s phrase-list enforcement with structural envelopes + LLM-judge verification (per user's 2026-05-28 rule: no forbidden-phrase enumeration as a primary verification mechanism).
**Started**: 2026-05-28
**Branch**: `feature/inv-a005-structural-faithfulness`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-28 — Plan filed; pivot from phrase-list to structural

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) `INV-A005` v1.21.1 — old rule mentions forbidden phrases.
- Re-read [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) §INV-A005 (lines 156–204) — 5-row catalogue + decompose rule + 3 worked examples.
- Re-read [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — `_FORBIDDEN_PHRASES` (11 entries) + `_STRUCTURAL_FAILURE_SIGNALS` (8 entries) + `_GENOMECLAW_HTTP_ERROR_PATTERN` regex + walker logic.
- Re-read [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) — three failure-path helpers: `rejectIfPlaceholder` (lines 297–333), `wrapHostResponse` (lines 220–244), `safeCall`/`safePost` catch blocks (lines 185–197, 254–266). All return prose strings.
- Re-read parent plan's [work-notes.md § Manual AC8 Gate](../../completed/agent-stale-memory-and-failure-mode-confabulation/work-notes.md) — captured the agent's "object-shape serialization error" confabulation that wasn't on the forbidden-phrase list.
- Ran Explore agent over the repo for all phrase-enumeration sites (audit summarized in [eliminate-forbidden-phrase-enumeration](../eliminate-forbidden-phrase-enumeration/work-notes.md)).

**Applicable Invariants**:
- `INV-A005` — rule mechanism changing (v1.21.1 → v1.22).
- `INV-A002` v1.8 bullet 3 — Step 3 capability-claim override stays unchanged (already structural).
- `INV-A001` — Agent Memory Provenance — untouched.
- `INV-P001` — Privacy Default — Phase 4 optional LLM-judge gated by env var.

**Key Insights**:
- Architectural root cause of the AC8 failure: **plugin returns prose, not structured data.** Tests + prompts then can't avoid enumerating prose patterns. Fix the plugin and the downstream tests + prompt rules simplify naturally.
- User's preferred verification architecture (2026-05-28): *"rely on the OpenClaw agent to receive raw returns and evaluate multi-turn on a loop, calling more tools as it needs more info."* The structured-envelope shape directly supports this — agent reasons over `error_type` discriminator + raw structured fields rather than substring-matching paraphrased prose. Multi-turn investigation rule explicitly added to §INV-A005 rewrite.
- This plan **supersedes** the earlier follow-up stub at [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md). That stub proposed a behavioral replay harness with mocked envelopes + scenario tests; with structured envelopes + structural walker in place, the per-scenario phrase-list verification it proposed becomes obsolete. Will move to `completed/` with a supersession note during Phase 3.

**Completed Today**:
- [x] Filed this plan: spec.md, development-plan.md, phases/phase-1.md, phases/phase-2.md, phases/phase-3.md, phases/phase-4.md, work-notes.md.
- [x] Sister plan filed at [docs/plans/completed/eliminate-forbidden-phrase-enumeration/](../eliminate-forbidden-phrase-enumeration/) — generalizes this work into a project-wide rule + audits other phrase-enumeration sites.
- [x] Saved feedback memory at `~/.claude/projects/-Users-hugi-GitRepos-GenomeClaw/memory/feedback_no_phrase_enumeration.md` documenting the project-wide rule.

**Decisions Made**:
- **Pivot from phrase-list to structural** (user-confirmed 2026-05-28). The catalogue table in the prompt is removed in Phase 2; `_FORBIDDEN_PHRASES` tuple in the test is deleted in Phase 3.
- **Plugin returns structured envelopes** (`ToolFailureEnvelope` discriminated union with `error_type` discriminator). Prose stays as an `advisory` field for human-readable logs but is NOT load-bearing.
- **Multi-turn investigation rule baked into §INV-A005 rewrite** — explicitly authorize the agent to call additional diagnostic tools when failure shapes are unfamiliar, rather than guess from prior context.
- **`INV-A006` proposed but promoted in Phase 3, not Phase 1** — Phase 1 lands the type shape; Phase 3 promotes the invariant + adds the discovery test. Delays the invariant promotion until the shape is stable.
- **Phase 4 (LLM-judge) is scope-reducible** — defer to a follow-up plan if Phases 1–3 prove sufficient on the AC8 re-run gate. Documented trigger conditions in [phases/phase-4.md](phases/phase-4.md).
- **Open Question Q1 (per-tool-call records in trace) is a Phase 3 prerequisite** — three resolution paths documented; default fallback is `toolSummary.failures > 0` aggregate (coarser than ideal, still better than phrase enumeration). Phase 4's LLM-judge fills the per-tool-record gap semantically.

**Blockers / Issues**:
- None for plan filing. Q1 resolution needed before Phase 3 RED.

**Next Steps**:
1. **Review the plan + sister plan with the user.** Both are substantial; user may want to scope-trim or sequence differently.
2. If approved: begin Phase 1 RED — write the three new `ToolFailureEnvelope`-shape tests in `index.test.ts`.

---

### 2026-05-28 — Stage 0: Q1 resolved (per-tool-call records source)

**Investigation**:
- Inspected `openclaw agent --json` output with `--verbose on` — same `result.meta.toolSummary` aggregate; no per-call records in JSON.
- Verbose mode emits per-call log lines (`embedded run tool start: tool=X toolCallId=Y`) to **stderr** — useful for live diagnostics, not parseable as structured data.
- Discovered `/sandbox/.openclaw/agents/genomeclaw/sessions/<run-id>.trajectory.jsonl` — written by openclaw on every agent run. Contains 7 record types per session: `session.started`, `trace.metadata`, `context.compiled`, `prompt.submitted`, `model.completed`, `trace.artifacts`, `session.ended`.
- **The gold field**: each `model.completed` record's `data.messagesSnapshot` is a list of full message objects, including every `toolResult` with structured fields: `{role: "toolResult", toolCallId, toolName, content: [{type: "text", text: <raw tool output>}], isError: <bool>, timestamp}`. Sample inspection on the 2026-05-28 smoke trace: 37 toolResult + 24 assistant + 7 user messages — every tool call accounted for.

**Q1 Decision**: structural walker reads the trajectory file. After `docker exec ... openclaw agent ...` returns, `docker cp <CID>:/sandbox/.openclaw/agents/genomeclaw/sessions/<run-id>.trajectory.jsonl` to host, parse `messagesSnapshot` from the last `model.completed` record. No upstream openclaw change needed. Strictly better than the meta-plan's default fallback (`toolSummary.failures > 0` only) — provides per-tool-call granularity.

**Implications for Plan A.3**:
- Structural walker becomes a meaningful per-tool check: for every assistant claim about a tool call, find the matching `toolResult` record by `toolCallId` and verify the agent's narrative reads the structured `error_type` field correctly.
- No need to escalate Q1's "path 1" (upstream openclaw issue) or "path 2" (WebSocket interception). Path 0 (trajectory file) was hiding in plain sight.
- The `scripts/sandbox-up.sh` flow stays the canonical agent-invocation; tests add a trajectory-capture step after `docker exec ... openclaw agent`.

**Implications for sister plan**:
- B.1 audit findings unchanged. Annotation discipline still applies.

**Implications for meta-plan**:
- Stage 3 risk R2 ("plan A.Q1 unresolvable") downgraded — trajectory source is canonical + always-available. R2 closed.

**Files investigated** (read-only, no changes):
- `openclaw agent --help` output inside the sandbox
- `/sandbox/.openclaw/agents/genomeclaw/sessions/66168e70-3109-4338-9286-4c5b13b40390.trajectory.jsonl` — sample 49-record trajectory from the 2026-05-28 smoke + verbose probe runs.

---

### 2026-05-28 — Stage 1 / Phase 1 RED → GREEN → REFACTOR

**Context Review Completed**:
- Re-read [phase-1.md](phases/phase-1.md) and the relevant source: `safeCall` (185-197), `wrapHostResponse` (220-244), `safePost` (254-266), `rejectIfPlaceholder` (297-333).
- Re-read [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts) to understand the existing test style + identified 6 prose-substring assertions to rewrite during GREEN (4 in "host-side structured failure detection (Plan 2)" + 2 in "error handling").
- Confirmed `failedTextResult(text, details)` envelope shape via [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts:35) — `content[0].text` is the agent-visible field; my plan: stringify `ToolFailureEnvelope` into the `text` field.

**RED step output**: 4 new tests in `INV-A006 structured failure envelopes (Plan A.1)` describe block; all failed with `SyntaxError: Unexpected token` because current helpers emit prose, not JSON. Right reason. 27 pre-existing tests still passed (some unchanged, some accidentally passing because the prose substrings happened to overlap with envelope content).

**GREEN step**:
- Added inline `ToolFailureEnvelope` discriminated-union type with 4 `error_type` arms.
- Added `failureEnvelopeResult(envelope)` helper wrapping `failedTextResult(JSON.stringify(envelope, null, 2), envelope)`.
- Added `parseHttpStatusFromError(msg)` regex helper to classify network_error vs http_error from the `callHostService` thrown message.
- Rewrote `safeCall` catch + `safePost` catch + `wrapHostResponse` + all 3 branches of `rejectIfPlaceholder` to emit envelopes via `failureEnvelopeResult`.
- Hoisted `parseFailureEnvelope` + `FailureEnvelope` interface to module-level in `index.test.ts` (used across multiple describe blocks).
- Rewrote 6 pre-existing prose-substring assertions to use `parseFailureEnvelope` + structured field checks. **No `*.toContain("status=failed")` style assertions remain in the plugin tests.**

**REFACTOR step**:
- `npm run typecheck` clean.
- `npm run build` clean (TypeScript discriminated-union types compile correctly).
- `npm test` — **31 / 31 passing** (4 new INV-A006 + 27 existing).
- Sanity-check: synthetic envelope JSON renders cleanly + parses cleanly.
- Single `index.ts` net diff: +88 lines (envelope type + 2 helpers + 4 rewired callsites + comment block).
- Single `index.test.ts` net diff: +80 lines (1 helper hoisted to top + 4 new tests + 6 reworked existing tests).

**Completed Today**:
- [x] Plan A Q1 resolved: trajectory file at `/sandbox/.openclaw/agents/genomeclaw/sessions/<run-id>.trajectory.jsonl` contains per-tool-call `messagesSnapshot` with `{toolName, content, isError, toolCallId}`. Documented as a separate session note above.
- [x] Plan B.1 audit findings filed at [eliminate-forbidden-phrase-enumeration/phases/phase-1-audit-findings.md](../eliminate-forbidden-phrase-enumeration/phases/phase-1-audit-findings.md). 4 primary load-bearing sites (all sister-plan scope) + ~22 backstops in 1 file + 1 structural site + 1 superseded plan stub.
- [x] Plan A.1 RED → GREEN → REFACTOR complete.

**Decisions Made**:
- **Single inline `ToolFailureEnvelope` type in `index.ts`**, not a new `types.ts` file. Rationale: the plugin is a single-file plugin (852 lines + 88 new = 940); extracting types into a new file is premature. Re-evaluate if plugin grows past 1500 lines.
- **`advisory` field is human-readable and explicitly non-load-bearing per `INV-A006`** — operator-facing flavor text only. Agent must read structured fields (`error_type`, `arg_name`, `host_error`, etc.) per Plan A.2's prompt rewrite.
- **HTTP-status classification via regex on the thrown message** rather than restructuring `callHostService` to throw structured Errors. Less invasive — leaves the existing throw site (line 171) and its callers unchanged; the catch-block classifier handles the structured shape upstream.

**Blockers / Issues**:
- None.

**Next Steps**:
1. Stage 1 closes here. Per meta-plan, proceed to Stage 2: **Plan A.2 prompt §INV-A005 rewrite**.
2. After A.2 lands: rebuild sandbox (`./scripts/sandbox-up.sh --rebuild`) + re-run AC8 manual gate. Pass criteria documented in [meta-plan.md § Stage 2 GATE](../structural-verification-meta/meta-plan.md).

---

## Phase Progress

### Phase 1: Plugin Source — Structured Failure Envelopes
**Status**: **Complete** (2026-05-28)
**Tests**: 31 / 31 passing. Typecheck clean. Build clean.

### Phase 2: Agent Prompt §INV-A005 Rewrite
**Status**: **Complete + Stage 2 GATE PASSED** (2026-05-28)

**Phase 2 details**:
- Deleted `_CATALOGUE_ROWS` constant + `test_invA005_system_prompt_carries_failure_phrase_catalogue` (parametrized) + `test_invA005_system_prompt_carries_decompose_per_tool_rule` + `test_invA005_system_prompt_forbids_confabulated_serialization_bug_narrative` from `test_agent_system_prompt_contract.py`.
- Added three new rule-form contract tests: `test_invA005_v122_system_prompt_teaches_structured_error_type_rule`, `..._teaches_quote_verbatim_discipline`, `..._teaches_multi_turn_investigation`.
- Rewrote §INV-A005 in the agent system prompt (lines 156–204 of pre-Phase-2; now ~30 lines): removed catalogue table, decompose-rule's enumeration form, all three worked examples that referenced phrases. Added rule-based guidance: read `error_type`, name + describe the four enum values literally, quote structured fields verbatim, multi-turn investigation under unfamiliar shapes. Kept per-tool scoping rule. Added two new worked examples (host-down + mixed-outcome) — both anchored to `error_type` values, not phrases.
- 20/20 prompt-contract tests pass. Lint clean.

**Stage 2 GATE — AC8 re-run trace**: [docs/reports/demo-2026-05-28-logs/stage2-gate-muscle-question.trace.json](../../../../docs/reports/demo-2026-05-28-logs/stage2-gate-muscle-question.trace.json).

41 tool calls; `toolSummary.failures: 0` (host service still down by design — exercises the network-failure path). Reply excerpt:

> "`genomeclaw_status`, `genomeclaw_findings`, and `genomeclaw_pgs_list` all returned `error_type: network_error` with `raw_error: fetch failed`. The gene-panel calls returned `error_type: placeholder_rejected`; the tool reported it received a call-id string instead of a JSON object. A PRS compute attempt also returned `error_type: placeholder_rejected`."

**All four meta-plan pass criteria met:**

1. ✅ Reply contains `error_type:` literally (3 occurrences across all 4 enum values).
2. ✅ Quotes structured fields verbatim in backticks (`error_type:`, `raw_error:`).
3. ✅ Decomposes per-tool: three distinct failure clusters named separately, each anchored to its own `error_type`.
4. ✅ No invented paraphrase: zero occurrences of v1.21 catalogue-banned phrases ("object-shape serialization error", "argument-shape guard fired", "argument-serialization bug", etc.). All failure language traces to envelope fields.

**Bonus discovery**: the gene-panel calls hitting `placeholder_rejected` reveal the upstream openclaw Q-001 quirk (call-id string passed instead of JSON object). The agent correctly identifies this as `placeholder_rejected` rather than inventing a new failure narrative.

**Stage 5 preliminary decision**: with the gate passing this cleanly, Plan A.4 (LLM-judge harness) is a strong candidate for deferral. Revisit formally at Stage 5.

### Phase 3: Structural Trace-Walker + Promote INV-A006
**Status**: Pending — Q1 resolved (trajectory file). Stage 3 of meta-plan.

### Phase 4: LLM-Judge Harness
**Status**: Pending — scope-reducible at Stage 5 decision point

---

## Key Decisions

### Decision 1: Eliminate the catalogue, return structured envelopes from the plugin
**Date**: 2026-05-28
**Context**: AC8 manual gate showed phrase enumeration can't cover the agent's paraphrase-space. User rule: never enumerate forbidden phrases.
**Decision**: Replace the §INV-A005 catalogue + `_FORBIDDEN_PHRASES` tuple with a structural mechanism — plugin returns `{error_type, ...}` envelopes; agent quotes fields verbatim; tests inspect structure.
**Rationale**: Solves the root cause (plugin returns prose) rather than the symptom (test/prompt patches against specific paraphrases).
**Alternatives Considered**: (a) keep the catalogue + iteratively add paraphrases — rejected as whack-a-mole. (b) LLM-judge only without plugin change — rejected as expensive (every CI run pays for an LLM call) and doesn't fix the architecture.
**Affected Invariants**: `INV-A005` (rule rewrite), new `INV-A006` (proposed).

### Decision 2: Multi-turn investigation as the failure-mode response
**Date**: 2026-05-28
**Context**: User's stated preferred architecture: *"rely on the OpenClaw agent to receive raw returns and evaluate multi-turn on a loop, calling more tools as it needs more info."*
**Decision**: The §INV-A005 rewrite explicitly tells the agent to **call additional tools** (`genomeclaw_status`, retry, fetch logs) when encountering unfamiliar failure shapes, rather than paraphrase from prior context or memory notes.
**Rationale**: Shifts discipline from "don't say X" to "investigate before claiming." Lines up with the LLM's strengths (iterative reasoning over structured data) instead of fighting them (suppressing specific outputs).
**Alternatives Considered**: keep the prior plan's decompose-per-tool rule as the only discipline — rejected as too brittle (doesn't transfer across clusters within one reply, per AC8 finding 2).
**Affected Invariants**: `INV-A005` (rule rewrite includes the multi-turn discipline).

### Decision 3: Phase 4 is scope-reducible
**Date**: 2026-05-28
**Context**: The prior plan's Phase 3 was originally scoped as a heavy automated replay harness; was scope-reduced to a manual AC8 gate. Want to avoid the same trap here.
**Decision**: Phase 4 (LLM-judge) ships only if Phase 3's structural walker is insufficient. Documented trigger conditions in `phase-4.md`.
**Rationale**: Phases 1–3 deliver the architectural fix + the prompt rewrite + the structural verification. LLM-judge is defense-in-depth, not load-bearing.
**Alternatives Considered**: ship Phase 4 always — rejected as scope-creep that didn't work last time.

---

## Files Modified

### Created
- [spec.md](spec.md)
- [development-plan.md](development-plan.md)
- [phases/phase-1.md](phases/phase-1.md)
- [phases/phase-2.md](phases/phase-2.md)
- [phases/phase-3.md](phases/phase-3.md)
- [phases/phase-4.md](phases/phase-4.md)
- This file.

### Modified
*(populated as implementation proceeds)*

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] `INV-A005` v1.22 rule rewrite (Phase 3).
- [ ] New `INV-A006` (proposed) — Plugin Tool-Result Returns Structured Envelopes (Phase 3).
- [ ] Version bump + Invariant Index update.

### Other Documentation
- [ ] [agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md) — move to `completed/` with supersession note (Phase 3).
- [ ] [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) — note the new verification mechanism (structural + LLM-judge, not phrase-list). Light edit (Phase 3).

---

## Open Risks & Follow-ups

- **R1** Q1 dependency — Phase 3 structural walker depends on per-call records; current trace format may not surface them. Three resolution paths in `phase-3.md`.
- **R2** Backward compat — plugin return shape change is breaking for any prose-substring consumer. Audit before merging.
- **R3** Sister plan coordination — [eliminate-forbidden-phrase-enumeration](../eliminate-forbidden-phrase-enumeration/) tracks the project-wide cleanup. Plan 1 (this one) is its INV-A005 pilot.
- **R4** Worked-example drift — Phase 2 rewrites need to be concrete enough that the agent learns the structural discipline from them. Light ad-hoc verification during Phase 2 implementation.

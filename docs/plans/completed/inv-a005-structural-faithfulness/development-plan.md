# INV-A005 Structural Faithfulness — Development Plan

**Status**: Draft
**Created**: 2026-05-28
**Branch**: `feature/inv-a005-structural-faithfulness`
**Spec**: [spec.md](spec.md)

---

## Summary

Replace `INV-A005`'s phrase-list enforcement (which the AC8 manual gate showed cannot cover the agent's paraphrase-space) with a structural mechanism: plugin returns structured failure envelopes; agent quotes structured fields verbatim; verification is by trace-record inspection and (optionally) LLM-judge — not substring matching.

## Critical Invariants to Respect

- **INV-A005** v1.21.1 → v1.22 rewrite. Old rule: forbidden phrases require licensing signals. New rule: failure narratives must trace to a structured `error_type` field + quote at least one structured field verbatim. **Verification mechanism changes** but the underlying property (agent's narrative matches the trace) is preserved.
- **INV-A002** v1.8 bullet 3 (Step 3 capability-claim override) — stays. Was structural already (asks the agent to re-test capability in-turn).
- **INV-A001** Agent Memory Provenance — unchanged.
- **INV-P001** Privacy Default — Phase 4's optional LLM-judge harness gated by env var; default `pytest` runs do not emit egress.

## Proposed New Invariants

- **NEW `INV-A006`** (proposed) — *Plugin Tool-Result Returns Structured Envelopes, Not Prose Paraphrases.* Promoted in Phase 3 once Phase 1 lands the structured-envelope shape. Rule + verification:
  - Rule: any tool wrapper in the plugin that signals failure to the agent MUST return a structured envelope with an explicit `error_type` enum field. Prose paraphrases (e.g., "argument 'X' is the placeholder string '…'") may appear as an `advisory` field but MUST NOT be the only signal of error class.
  - Verification: a discovery test walks the plugin's exported tool-list + asserts every tool wrapper's failure-path return type contains an `error_type` field. (TypeScript types let us check this structurally — no runtime probe needed.)

## Current State Analysis

After the parent plan's Phases 1+2 landed 2026-05-28, the enforcement surface is:

- **Prompt** ([agent-system-prompt.md:170–204](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L170)): 5-row catalogue + decompose rule + 3 worked examples.
- **Trace-walker test** ([test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py)): `_FORBIDDEN_PHRASES` (11 entries) + `_STRUCTURAL_FAILURE_SIGNALS` (8 entries) + `_GENOMECLAW_HTTP_ERROR_PATTERN` regex.
- **Prompt-contract test** ([test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)): `_CATALOGUE_ROWS` (5 rows) parametrized over the §INV-A005 prompt section. Plus `_extract_invA005_section` helper.
- **Plugin source** ([index.ts](../../../../packages/nemoclaw-plugin/src/index.ts)):
  - `rejectIfPlaceholder` (lines 297–333) → returns prose `"argument 'X' is the placeholder string '...' — this usually means..."`
  - `wrapHostResponse` (lines 220–244) → returns prose `"host returned status=failed for /v1/<path>: <code>. This is a host-side structured failure..."`
  - `safeCall` / `safePost` catch blocks (lines 185–197, 254–266) → return `failedTextResult(msg, ...)` where `msg` is the raw catch-block error message (`"Failed to connect..."`, `"fetch failed"`, etc.)

The AC8 gate showed all three layers can be routed around by the agent inventing new paraphrases. Architectural root cause: the plugin returns prose where it should return structured data. Plan addresses root cause + downstream tests.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) | Three failure-path helpers return prose strings | Phase 1: return `{status, error_type, ...details, advisory}` structured envelopes. Old prose becomes the `advisory` field — preserved for backward-compatible reading by older sandbox images during transition. |
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | §INV-A005 has 5-row catalogue + decompose rule + 3 worked examples | Phase 2: remove the catalogue table; replace with rule-based guidance (read `error_type` field; quote structured field values verbatim; call additional tools multi-turn if context insufficient). Keep the decompose-per-tool intent + worked examples but rewrite examples to reference `error_type` fields, not phrases. |
| [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | Trace-walker with `_FORBIDDEN_PHRASES` + `_STRUCTURAL_FAILURE_SIGNALS` | Phase 3: rewrite. Delete tuples. New walker: parse trace's per-tool-call records (or fall back to `toolSummary.failures`), assert reply quotes `error_type` field for any failure narrative. **Open Question Q1**: depends on per-call records being surfaced in trace. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | `_CATALOGUE_ROWS` + parametrized catalogue contract test + decompose-rule contract | Phase 2: delete `_CATALOGUE_ROWS` + the parametrized catalogue test + the decompose-rule contract. Replace with a structural-rule test (asserts prompt mentions `error_type` field + multi-turn investigation guidance). |
| [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts) | Tests likely assert on the prose return strings | Phase 1: update to assert on structured envelope shape (`error_type` field present, correct enum value). |
| [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) | `INV-A005` v1.21.1 rule mentions forbidden phrases | Phase 4 / wrap-up: rewrite rule text to v1.22 (structural / quote-verbatim mechanism). Add `INV-A006` per Q3. |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/nemoclaw-plugin/src/types.ts` (or extend existing types) | `ToolFailureEnvelope` TypeScript interface — discriminated union over `error_type`. |
| `packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py` *(if `INV-A006` is promoted)* | Discovery test: walks the plugin's exported tool list, asserts every failure-path return shape carries `error_type`. |
| `packages/toolkit/tests/agent_replay/test_inv_a005_llm_judge.py` *(Phase 4, scope-reducible)* | LLM-judge harness: `(trace, reply) → gpt-5.5` → "is the reply consistent with the tool calls?" — replaces the catalogue contract test as the semantic correctness gate. |

## Solution Design

```text
                ┌──────────────────────────────────┐
                │ packages/nemoclaw-plugin/src/    │
                │ index.ts (plugin failure paths)  │
                │ ┌──────────────────────────────┐ │
   Phase 1 ───→ │ │ rejectIfPlaceholder() →      │ │
                │ │ ToolFailureEnvelope {        │ │
                │ │   status: "failed",          │ │
                │ │   error_type: "placeholder_  │ │
                │ │     rejected",               │ │
                │ │   arg_name, value, advisory  │ │
                │ │ }                            │ │
                │ │ wrapHostResponse() →         │ │
                │ │   error_type: "host_failure" │ │
                │ │ safeCall/safePost catch →    │ │
                │ │   error_type: "network_error"│ │
                │ │   / "http_error"             │ │
                │ └──────────────────────────────┘ │
                └─────────────┬────────────────────┘
                              │
                              │ structured envelope (not prose)
                              ▼
                ┌──────────────────────────────────┐
                │ agent-system-prompt.md §INV-A005 │
                │ ┌──────────────────────────────┐ │
   Phase 2 ───→ │ │ Old: 5-row catalogue table   │ │
                │ │ New: read error_type field;  │ │
                │ │   quote structured fields    │ │
                │ │   verbatim; call more tools  │ │
                │ │   multi-turn if context      │ │
                │ │   insufficient.              │ │
                │ └──────────────────────────────┘ │
                └─────────────┬────────────────────┘
                              │
                              │ agent reasons multi-turn over structured data
                              ▼
                ┌──────────────────────────────────┐
                │ Verification:                    │
                │ ┌──────────────────────────────┐ │
   Phase 3 ───→ │ │ Structural trace-walker:     │ │
                │ │   for each failure-narrative │ │
                │ │   paragraph in reply, assert │ │
                │ │   per-call record's          │ │
                │ │   error_type appears literal │ │
                │ │   in the reply.              │ │
                │ └──────────────────────────────┘ │
                │ ┌──────────────────────────────┐ │
   Phase 4 ───→ │ │ LLM-judge (gpt-5.5,          │ │
   (deferrable) │ │   env-gated): (trace,reply)  │ │
                │ │   → "consistent?" yes/no.    │ │
                │ │ Skip-by-default for INV-P001 │ │
                │ └──────────────────────────────┘ │
                └──────────────────────────────────┘
```

### Key Design Decisions

1. **Structured envelopes are the architectural fix.** The phrase-list approach is a symptom of the plugin returning prose. By changing the plugin to return structured `{error_type, …}` data, the agent has unambiguous fields to quote — no paraphrase ambiguity. This is also the user's stated preferred architecture (raw returns + multi-turn reasoning).
2. **The prose stays, but as an `advisory` field, not the load-bearing signal.** Backward-compat — older sandbox images that haven't been rebuilt still see human-readable text. New rule: `error_type` is the source of truth; `advisory` is operator-facing flavor text.
3. **Multi-turn investigation is the failure-mode response, not better prompt rules.** When the agent encounters something unfamiliar, the §INV-A005 rewrite tells it to **call more tools** (`genomeclaw_status`, retry, fetch logs) rather than guess. This shifts discipline from "don't say X" to "investigate before claiming."
4. **Quote-verbatim is a structural check, not enumeration.** The replacement walker asserts every failure-narrative paragraph contains a backtick-quoted excerpt of a structured field value or `error_type`. The substring check is uniform across all failure modes — no per-failure-mode enumeration.
5. **`INV-A006` (proposed) prevents future regressions.** Without it, a contributor could ship a new tool wrapper that returns prose-only, and we'd silently slide back to the symptom. The proposed invariant makes the discipline structural at the type-system layer.

### Schema / Provenance Impact

- **None for derived stores.** Tool-result envelopes are ephemeral, not persisted.
- TypeScript type changes (introduce `ToolFailureEnvelope`, update return types). Tests in [packages/nemoclaw-plugin/tests/](../../../../packages/nemoclaw-plugin/tests/) update accordingly.

### Privacy & Egress Impact

- No new egress in Phases 1–3.
- Phase 4 (LLM-judge) reuses the existing OpenAI provider; gated by env var (`GENOMECLAW_REPLAY_LLM=gpt-5.5`); default-skip when unset.
- No new sensitive fields exposed; structured envelopes carry the same data the prose did.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests | Scope |
|-------|-------------|-----------|------------|-------|
| 1 | Plugin source: structured envelopes | TypeScript type tests + updated `index.test.ts` assertions | ~5 changed | Required |
| 2 | Agent prompt §INV-A005 rewrite | Prompt-contract test for new rule shape | 2 (replaces ~6 existing) | Required |
| 3 | Replace trace-walker with structural walker + delete forbidden-phrase tuples; promote `INV-A006` | Structural test + INV-A006 discovery test | ~3 | Required (gated by Q1) |
| 4 | LLM-judge harness | 1 scenario (semantic correctness gate) | 1 | **Scope-reducible** — defer if Phase 3 is sufficient |

## Phase 1: Plugin Source — Structured Envelopes

**Goal**: Change three failure-path helpers in `index.ts` to return structured envelopes. Update plugin-side tests.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

1. `ToolFailureEnvelope` discriminated-union TypeScript type.
2. Updated `rejectIfPlaceholder`, `wrapHostResponse`, `safeCall`, `safePost` return shapes.
3. Updated [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts) assertions.

### Invariants Enforced Here

- **NEW INV-A006** (proposed; promoted in Phase 3) — the type changes here become the source of truth for the proposed invariant.

### Success Criteria

- [ ] `npm run typecheck` + `npm run build` pass in `packages/nemoclaw-plugin/`.
- [ ] `npm test` passes with updated assertions.
- [ ] No callsite in `index.ts` still returns a bare prose string from a failure path.

## Phase 2: Agent Prompt §INV-A005 Rewrite

**Goal**: Remove the 5-row catalogue + decompose rule's enumeration form; replace with structural rule referencing `error_type` field + multi-turn investigation guidance.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables

1. Rewritten §INV-A005 prompt section (~30 lines, replacing ~35 current lines).
2. Updated `test_agent_system_prompt_contract.py` assertions: remove `_CATALOGUE_ROWS` + catalogue-presence test + decompose-rule contract test; replace with a single rule-form contract test (`error_type`-mention + multi-turn-investigation guidance present).

### Invariants Enforced Here

- **INV-A005** v1.22 rule text (the rewritten enforcement mechanism).
- Indirect: `INV-A002` v1.8 bullet 3 stays unchanged — Phase 1 of the parent plan's Step 3 capability-claim bullet is structural already, untouched.

### Success Criteria

- [ ] New §INV-A005 section present in prompt + reads cleanly.
- [ ] New rule-form contract test passes.
- [ ] Old `test_invA005_system_prompt_carries_failure_phrase_catalogue` + `test_invA005_system_prompt_carries_decompose_per_tool_rule` are **deleted** (not skipped).
- [ ] `_CATALOGUE_ROWS` + `_extract_invA005_section` removed from the test file.

## Phase 3: Replace Trace-Walker + Promote INV-A006

**Goal**: Delete `_FORBIDDEN_PHRASES` / `_STRUCTURAL_FAILURE_SIGNALS` / `_GENOMECLAW_HTTP_ERROR_PATTERN`. Replace the trace-walker with a structural walker that asserts every failure narrative quotes an `error_type`. Promote `INV-A006`.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables

1. Rewritten `test_invA005_no_serialization_bug_confabulation.py` — structural walker, no phrase enumeration.
2. New `test_invA006_plugin_returns_structured_envelopes.py` — discovery test asserts every failure-path return type has `error_type`.
3. Updated [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — `INV-A005` rule text v1.22 + new `INV-A006` entry + bumped version.

### Invariants Enforced Here

- **INV-A005** v1.22 (new structural rule).
- **NEW INV-A006** (promoted from Phase 1).

### Success Criteria

- [ ] No `_FORBIDDEN_PHRASES` / `_CATALOGUE_ROWS` / `_STRUCTURAL_FAILURE_SIGNALS` tokens remain in `tests/invariants/`.
- [ ] Structural walker runs cleanly on the existing trace corpus (most should skip via the existing date-binding logic — or be updated to pass under the new mechanism).
- [ ] `INV-A006` discovery test passes against the current plugin source.
- [ ] `INVARIANTS.md` v1.22 + `INV-A006` entry; index table updated.

## Phase 4: LLM-Judge Harness (Scope-Reducible)

**Goal**: Optional behavioral test using `gpt-5.5` as a judge over `(trace, reply)`. Replaces the prior catalogue contract test as the semantic correctness gate.
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables

1. Conftest in `packages/toolkit/tests/agent_replay/` with `GENOMECLAW_REPLAY_LLM` env gate.
2. Single judge-based scenario test (re-runs the AC8 muscle question, sends `(trace, reply)` to `gpt-5.5` for evaluation).

### Invariants Enforced Here

- **INV-A005** v1.22 (semantic / behavioral half).

### Success Criteria

- [ ] Default `pytest tests/agent_replay/` skips cleanly (no egress).
- [ ] With `GENOMECLAW_REPLAY_LLM=gpt-5.5` set, judge correctly flags the 2026-05-28 AC8 trace as **inconsistent** ("object-shape serialization error" doesn't match any tool's `error_type`).
- [ ] With the same env var set + a corrected post-Phase-1-2-3 trace, judge passes the reply.

### Phase 4 Scope-Reducibility

If after Phase 3 the structural walker provides sufficient signal (e.g., quote-verbatim discipline holds on real traces), Phase 4 may be deferred to a separate follow-up plan. The structural walker + the new prompt rule + the plugin's structured envelopes together close the loop on Phase 1's reported bugs; the LLM-judge adds defense-in-depth.

---

## Testing Strategy

### Unit Tests

- Plugin-side TypeScript unit tests on the structured envelope shape (Phase 1, in [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts)).

### Integration Tests

- The AC8 muscle-question re-run (Phase 3 manual gate + Phase 4 automated gate).

### Provenance Tests

- **n/a** — no derived stores affected.

### Determinism Tests

- **n/a** — LLM-judge is inherently non-deterministic; assertions are on flag/pass shape, not on exact text.

### Privacy-Default Tests

- Phase 4 conftest gates LLM calls behind `GENOMECLAW_REPLAY_LLM=gpt-5.5`; default `pytest` runs make no real LLM calls.

### Evidence-Binding Tests

- **n/a** — this plan is about agent self-reporting discipline, not finding-citation discipline.

### Report Rendering Tests

- **n/a** — no report templates touched.

### Tool-Contract Tests

- Phase 3's `INV-A006` discovery test is a tool-contract test in the spirit of `INV-T001` — it pins the plugin's failure-envelope shape at the type-system layer.

### Invariant Tests

- Phase 3: `test_invA005_*` rewritten as structural; `test_invA006_*` newly created.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — `INV-A005` v1.22 rule rewrite + `INV-A006` new entry + Invariant Index update + version bump.
- [ ] Root [CLAUDE.md](../../../../CLAUDE.md) — no change (top-level invariant text unchanged in spirit).
- [ ] `.claude/agents/*.md` — `test-engineer.md` may need a note about the new verification mechanism (structural + LLM-judge, not phrase-list). Light edit.
- [ ] Mark [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md) **superseded**; move to `completed/` with a note pointing here.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — Plugin structured envelopes | **Complete** | 2026-05-28 | 2026-05-28 | RED → GREEN → REFACTOR in one session. 4 new envelope-shape tests; 6 pre-existing tests rewired to envelope parsing. 31/31 plugin tests pass; typecheck + build clean. `ToolFailureEnvelope` discriminated union landed inline in `index.ts`. |
| Phase 2 — Prompt §INV-A005 rewrite | **Complete** | 2026-05-28 | 2026-05-28 | 4 v1.21 catalogue tests deleted; 3 new rule-form tests pass. Stage-2 GATE: 4/4 pass criteria met on AC8 re-run trace. |
| Phase 3 — Trace-walker rewrite + INV-A006 promotion | **Complete** | 2026-05-28 | 2026-05-28 | Structural walker reads trajectory file; `INV-A006` discovery test (3 cases) green; `INVARIANTS.md` v1.22 bumped; INV-A005 rule rewritten + INV-A006 added + Invariant Index updated. |
| Phase 4 — LLM-judge harness | **DEFERRED** | 2026-05-28 | n/a | Stage 5 decision: AC8 gate passed cleanly → defer to follow-up plan. Trigger conditions documented. |

---

## Open Risks & Follow-ups

- **R1 — Q1 dependency**: Phase 3's structural walker depends on per-call records being surfaced in the trace. If `openclaw agent --json` doesn't expose them and upstream openclaw won't, the walker falls back to `toolSummary.failures` only — less strict than the design wants, but still better than phrase enumeration. Resolve Q1 before starting Phase 3.
- **R2 — Phase 1 backward compat**: structural envelopes are a breaking change for any consumer that substring-matches the prose. The only known consumer is the agent itself (mediated by the prompt + tests we're already updating in Phase 2 and Phase 3). External tool integrations or operator scripts that read tool-result envelopes might break — audit before merging.
- **R3 — LLM-judge cost**: Phase 4 calls `gpt-5.5` once per CI run; cost scales with how often CI fires. Default-skip env gate mitigates; full opt-in for the maintainer running gates manually.
- **R4 — Catalogue worked-examples drift**: Phase 2 rewrites the worked examples (anti-pattern + target pattern) from "don't use phrase X" to "quote `error_type` verbatim." The new examples need to be concrete enough that the agent learns the discipline — light-touch ad-hoc verification during Phase 2 implementation.
- **R5 — Sister plan coordination**: [eliminate-forbidden-phrase-enumeration](../eliminate-forbidden-phrase-enumeration/) tracks the project-wide methodology cleanup. Plan 1 is its INV-A005 pilot; sequencing matters (Plan 1 ships first, Plan 2 audits the rest).

# Agent Stale-Memory + Failure-Mode Confabulation — Development Plan

**Status**: Draft
**Created**: 2026-05-27 (promoted to phased layout 2026-05-28)
**Branch**: `feature/agent-stale-memory-and-failure-mode-confabulation`
**Spec**: [spec.md](spec.md)

---

## Summary

Two prompt-layer strengthenings + a new automated replay-test surface to prevent the agent from (a) citing stale memory notes about repaired tool capabilities and (b) homogenizing distinct in-turn tool failures into whichever failure phrase is most rehearsed.

## Critical Invariants to Respect

- **INV-A005** Tool-Failure Narratives Match Trace Evidence — this implementation **extends the prompt + tests that enforce it** while leaving the invariant text at v1.21 unchanged. New forbidden phrases ("argument-shape guard fired", "host returned status=failed", "HTTP connection refused", "TypeBox rejected the parameters") become catalogue entries with explicit structural-signal requirements; the trace-walker and prompt-contract tests grow to cover them.
- **INV-A002** Synthesis Reasoning Floor — the v1.8 memory-validation requirement is already in force; Phase 1 closes the *capability-claim* loophole by adding a fourth check to Step 3 that bypasses the freshness-date rule when the cited note describes a tool failure.
- **INV-A001** Agent Memory Provenance — adjacent. The fix is at the *use-site* (Step 3 cite-validation), not the *write-site*. The agent continues to write memory notes the same way; it just learns to supersede capability claims when the live trace contradicts them.
- **INV-P001** Privacy Default — pure prompt + local-test edits. No new egress, no new tool surface, no new sensitive-payload boundary. The replay harness mocks tool-result envelopes; it does not call real `genomeclaw_*` tools. The LLM endpoint used by the harness is either the existing local endpoint or a model already in the configured-egress allowlist (resolved per Open Question Q1 in Phase 3).

## Proposed New Invariants

**None.** Both fixes fit inside the existing `INV-A005` + `INV-A002` envelope.

## Current State Analysis

The 2026-05-26 `INV-A005` prompt strengthening (filed under [investigate-genomeclaw-gene-tool-bug](../../completed/investigate-genomeclaw-gene-tool-bug/)) covered the *mixed-outcome* turn: one tool call rejected by `rejectIfPlaceholder`, others succeeded, and the agent must not characterize the successful empty-but-valid responses as failures. The strengthening:

- Added a positive rule binding tool-failure phrasing to actual error evidence ([agent-system-prompt.md:156](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L156)).
- Forbade the phrase **"argument-serialization bug"** (and paraphrases) unless `rejectIfPlaceholder` prose was observed in this turn's output ([agent-system-prompt.md:172](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L172)).
- Taught positive paraphrasing of the two valid-but-empty response shapes (`region_class: null`; `n_variants_in_gene: 0`).
- Enforced via `test_invA005_no_serialization_bug_confabulation.py` (trace-walker over `docs/reports/*.trace.json`) and `test_agent_system_prompt_contract.py::test_invA005_*` (prompt content gate).

Two gaps were not closed:

1. **Stale capability-claim citation.** Step 3 (Memory validation) at [agent-system-prompt.md:177](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L177) has a freshness bullet at [line 183](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L183) framed as "is the note past its recorded freshness date." That's the wrong check for capability claims: a fix can have landed an hour ago, so the relevant signal is "did this turn's structured trace contradict the note?" not "is the topic stale by calendar." Bug 1 is exactly this: a 2026-05-26 memory note saying *"PGS000027 not computable"* was cited verbatim 30 minutes after Plan 1 had repaired the sidecar and `_pgs_list` was returning PGS000018 with a real percentile.

2. **All-failed-same-reason confabulation.** The 2026-05-26 worked example covered the mixed-outcome turn; it did not address the case where *every* `genomeclaw_*` call fails for the *same* reason (e.g., network unreachable). Bug 2 is exactly this: all calls returned HTTP connection-refused, the agent reached for the most-rehearsed failure framing ("argument-shape guard fired"), and conflated network unreachability with a TypeBox-shape rejection.

Both bugs are agent-cognition discipline issues, not plugin or service bugs. The plugin's failure shapes (`rejectIfPlaceholder`, `wrapHostResponse`, `safeCall` catch-block prose) are individually distinguishable in tool-result text; the agent just needs prompt-level discipline to read them.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | Step 3 (line 177) has 3 validation bullets ending in freshness (line 183). §INV-A005 (line 156–175) bans one phrase ("argument-serialization bug") + teaches two valid-empty paraphrases. | Phase 1 adds a 4th bullet under Step 3 ("Capability claims") that overrides the freshness check for tool-failure / "X is unavailable" notes. Phase 2 replaces the single forbidden phrase with a catalogue table of phrase ↔ structural-signal pairs, adds the "decompose per-tool" rule, and adds the over-trusted-memory anti-pattern worked example. |
| [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | `_FORBIDDEN_PHRASES` is a 5-tuple at lines 50–56 ("argument-serialization bug" + four paraphrases). `_trace_has_real_failure` predicate checks `toolSummary.failures > 0` OR text contains `"tool_failure"` / `"status=tool_failure"`. | Phase 2 extends `_FORBIDDEN_PHRASES` with the new catalogue's banned phrases ("argument-shape guard fired", "TypeBox rejected the parameters" without their respective structural signals). `_trace_has_real_failure` may grow a network-failure predicate (`text contains "Failed to connect"` ↔ `"connection refused"` ↔ etc.) so the trace-walker can distinguish "agent claimed network failure without one" from valid use. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | `test_invA005_*` asserts prompt contains `inv-a005` marker + `"argument-serialization bug"` + `region_class` + `n_variants_in_gene`. | Phase 2 adds a new assertion: each catalogue-table row's phrase + structural-signal text appears in the prompt. Phase 1 adds a sibling test that the Step 3 capability-claim bullet is present (`test_step3_memory_validation_special_cases_capability_claims`). |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/agent_replay/__init__.py` | Marker. |
| `packages/toolkit/tests/agent_replay/conftest.py` | Mock-envelope loader fixture + LLM-client fixture (resolved per Open Question Q1). |
| `packages/toolkit/tests/agent_replay/fixtures/stale_capability_memory/` | Synthetic memory note (claims `PGS000027 not computable`) + `_pgs_list` envelope returning that PGS as computed. |
| `packages/toolkit/tests/agent_replay/fixtures/all_network_failure/` | Connection-refused envelopes for every `genomeclaw_*` call in the muscle-question turn. |
| `packages/toolkit/tests/agent_replay/fixtures/mixed_outcome/` | Re-encoding of the 2026-05-26 muscle-question scenario (gene calls succeed, `_pgs_compute` rejected by `rejectIfPlaceholder`). |
| `packages/toolkit/tests/agent_replay/test_stale_capability_supersession.py` | AC6 scenario 1. |
| `packages/toolkit/tests/agent_replay/test_network_failure_phrasing.py` | AC6 scenario 2. |
| `packages/toolkit/tests/agent_replay/test_mixed_outcome_decomposition.py` | AC6 scenario 3. |

## Solution Design

```text
              ┌──────────────────────────┐
              │  agent-system-prompt.md  │
              │  ┌────────────────────┐  │
   Phase 1 ─→ │  │ Step 3 +bullet 4   │  │      (capability-claim override)
              │  │ "Capability claims"│  │
              │  └────────────────────┘  │
              │  ┌────────────────────┐  │
   Phase 2 ─→ │  │ §INV-A005 catalogue│  │      (5 phrase↔signal pairs + decompose rule)
              │  │ + anti-pattern WE  │  │
              │  └────────────────────┘  │
              └────────┬─────────────────┘
                       │
                       │ verified by
                       ▼
              ┌──────────────────────────┐
              │ prompt-contract tests    │  (extend existing INV-A005 contract test)
              │ trace-walker test        │  (extend _FORBIDDEN_PHRASES)
              └────────┬─────────────────┘
                       │
                       │ regression-tested by
                       ▼
              ┌──────────────────────────┐
   Phase 3 ─→ │ agent_replay/ harness    │  (NEW)
              │  - mocked envelopes      │
              │  - real LLM call         │  (model TBD by Q1)
              │  - 3 scenarios           │
              └──────────────────────────┘
```

### Key Design Decisions

1. **Pure prompt edits, not a plugin-side guard.** The plugin already returns distinguishable failure prose for each failure mode (`rejectIfPlaceholder`, `wrapHostResponse`, `safeCall` catch-blocks). The agent's job is to read them; the fix is a prompt discipline rule, not new plugin code. Rationale: minimal blast radius, no `INV-P001` egress impact, no new tool surface.
2. **Inline catalogue, not external fixture (Open Question Q3 default).** The catalogue starts inline in the prompt and is asserted via the contract test. If the catalogue churns past ~6 entries or the plugin team needs to register new failure phrases independently of the prompt edit cycle, promote to a `packages/nemoclaw-plugin/sandbox/failure-phrases.md` fixture that both prompt and tests read. Defer for now.
3. **Block-only memory-supersession, not auto-write (Open Question Q2 default).** When Step 3 detects a stale capability claim, the agent stops citing it; it does not auto-write a superseding memory note. Rationale: the agent's writes should stay scoped to deliberate synthesis turns. A follow-up plan can add auto-write if the memory store accumulates too many stale capability notes.
4. **Automated replay harness deferred (2026-05-28 decision).** Phase 3 originally scoped a new `tests/agent_replay/` surface with mocked tool-result envelopes + real `gpt-5.5` LLM calls + three scenario tests. After Phases 1+2 landed, the cost/value was reconsidered: the prompt-contract + trace-walker tests already pin the prompt content and catch confabulation in any future captured trace, and a behavioral replay suite would add ~200+ lines of infrastructure + real `gpt-5.5` cost per CI run for marginal additional coverage. Deferred to a follow-up plan (filed as a stub at [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md)). Phase 3 reduces to the manual AC8 muscle-question gate (the highest-fidelity verification — same scenario that surfaced both bugs).
5. **Catalogue rows are tested for prompt presence, not for round-trip behavior.** The prompt-contract test asserts every catalogue row's phrase + structural-signal text appears verbatim in the prompt. Round-trip behavior (agent reads catalogue → emits correct phrase under each scenario) is the job of the agent-replay tests in Phase 3.

### Schema / Provenance Impact

- New / changed schemas: **none**.
- Schema version bumps: **none**.
- Provenance columns added: **none**.
- Rebuild procedure: **n/a** — no derived stores touched.

### Privacy & Egress Impact

- New network egress points: **none for the production runtime**. The replay harness in Phase 3 calls a model that is already in the configured-egress allowlist; no new destination is introduced. If Open Question Q1 selects a model that isn't already authorized, the harness call is gated behind an explicit `GENOMECLAW_REPLAY_LLM=<model>` env var and the test skips by default — same pattern as `_live_smoke/`.
- New secret-handling surfaces: **none**.
- Redaction added: **n/a** — replay fixtures use synthetic memory notes + synthetic tool-result envelopes; no real genome data is embedded.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Step 3 capability-claim amendment | Prompt-contract test asserts new bullet present; behavior tested in Phase 3 scenario 1 | 1 (contract) + (1 deferred to Phase 3) |
| 2 | §INV-A005 catalogue extension | Prompt-contract test asserts each catalogue row present; trace-walker extends `_FORBIDDEN_PHRASES`; behavior tested in Phase 3 scenarios 2 + 3 | 2 (contract + trace-walker) + (2 deferred to Phase 3) |
| 3 | Agent-replay harness | 3 scenario tests with mocked envelopes + real LLM call; assert reply contains required text + does not contain forbidden phrases without structural signals | 3 (one per scenario) |

## Phase 1: Step 3 Capability-Claim Amendment

**Goal**: Close the freshness-date loophole that let the agent cite stale tool-capability claims (Bug 1).
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

1. [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — Step 3 grows a 4th validation bullet ("Capability claims") that overrides freshness for tool-failure / "X is unavailable" notes.
2. [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — new test `test_step3_memory_validation_special_cases_capability_claims` asserts the new bullet's text is present + names the three example signals (live `_pgs_list` contradicts memory, live `genomeclaw_status` HTTP 200 contradicts memory, live `genomeclaw_gene` returns variant counts).
3. One worked example added to Step 3 (anti-pattern citation vs. correct supersession).

### Invariants Enforced Here

- **INV-A002** (memory-validation requirement on every `memory:<id>` citation, v1.8 bullet 3): the new bullet closes the capability-claim case that the freshness-date framing didn't catch. The new contract test verifies the prompt teaches the rule; the Phase 3 agent-replay test verifies the agent obeys it.

### Success Criteria

- [ ] `test_step3_memory_validation_special_cases_capability_claims` passes (RED → GREEN visible in history).
- [ ] All existing `test_agent_system_prompt_contract.py` tests still pass.
- [ ] Static checks pass.
- [ ] At least one test references `INV-A002`.

## Phase 2: §INV-A005 Catalogue Extension

**Goal**: Replace the single-forbidden-phrase rule with a catalogue of phrase ↔ structural-signal pairs + a "decompose per-tool" rule, so the agent can name *each* tool's failure mode separately (Bug 2).
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables

1. [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — §INV-A005 grows a catalogue table of 5 phrase ↔ structural-signal pairs + the "decompose per-tool" rule + an over-trusted memory anti-pattern worked example.
2. [test_agent_system_prompt_contract.py::test_invA005_*](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — extended to assert each catalogue row's phrase + structural-signal text is present in the prompt.
3. [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — `_FORBIDDEN_PHRASES` extended with the new banned-without-signal phrases; `_trace_has_real_failure` grows a network-failure predicate.

### Catalogue Draft (final wording resolved during Phase 2 RED)

| Phrase the agent might use | Required structural signal in this turn |
|----------------------------|------------------------------------------|
| "argument-shape guard fired" / "rejectIfPlaceholder rejected" / "argument-serialization bug" | The literal `rejectIfPlaceholder` prose (`argument 'X' is the placeholder string "undefined" — this usually means the agent's tool-call argument resolution lost track of the real value upstream`) in this turn's tool-result text. |
| "host returned status=failed" / "host-side structured failure" | The `wrapHostResponse` prose (`host returned status=failed for /v1/<path>: <code>. This is a host-side structured failure...`) in this turn's tool-result text. |
| "HTTP connection refused" / "network unreachable" / "GenomeClaw wasn't reachable" | A `safeCall` / `safePost` catch-block message (`Failed to connect to ...`, `fetch failed`, `genomeclaw-service <path> -> HTTP 5xx`, etc.) in this turn's tool-result text. **NOT interchangeable with "argument-shape guard fired."** |
| "TypeBox rejected the parameters" | A TypeBox validator error message (`Expected <type>, received <type>`, etc.) in this turn's tool-result text. |
| "tool returned empty / null data" | `n_variants_in_gene: 0` OR `region_class: null` in a body that otherwise returned HTTP 200. **NOT a failure.** |

Plus the explicit rule: **if multiple tool calls fail in the same turn, report each one's failure mode separately based on its specific tool-result text. Do NOT homogenize "all my GenomeClaw calls failed" into a single guess at the cause.**

### Invariants Enforced Here

- **INV-A005** Tool-Failure Narratives Match Trace Evidence — the catalogue + decompose rule extend the surface that already enforces the v1.21 invariant. New trace-walker phrases catch the all-failed-same-reason confabulation; new contract assertions catch prompt drift.

### Success Criteria

- [ ] Catalogue table present in prompt with all 5 rows + decompose rule.
- [ ] `test_invA005_*` contract assertions pass with new per-row checks.
- [ ] `test_invA005_no_serialization_bug_confabulation.py` passes with extended `_FORBIDDEN_PHRASES` against the existing `docs/reports/*.trace.json` corpus.
- [ ] Existing contract assertions (`inv-a005`, `argument-serialization bug`, `region_class`, `n_variants_in_gene`) still pass.

## Phase 3: Agent-Replay Harness

**Goal**: Lock in Phase 1 + Phase 2 behavior via automated agent-replay tests; promote the existing manual muscle-question smoke to a repeatable fixture-driven test.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables

1. `packages/toolkit/tests/agent_replay/conftest.py` — envelope-loader fixture + LLM-client fixture.
2. `packages/toolkit/tests/agent_replay/fixtures/{stale_capability_memory,all_network_failure,mixed_outcome}/` — three synthetic fixture sets.
3. Three scenario tests (one per AC6 bullet) that mock the plugin's tool-result envelopes for each scenario, run the agent prompt against a real LLM, and assert the reply text obeys the catalogue + the Step 3 capability-claim rule.

### Invariants Enforced Here

- **INV-A005** (round-trip): the agent obeys the catalogue under each failure scenario.
- **INV-A002** (round-trip): the agent obeys Step 3's capability-claim bullet under the stale-memory scenario.
- **INV-P001** (no new egress): conftest gates LLM calls behind an explicit env var; default-config test runs skip if the var isn't set.

### Success Criteria

- [ ] All three scenarios pass (RED → GREEN → REFACTOR visible in history).
- [ ] Each scenario asserts both presence-of-correct-text AND absence-of-forbidden-text.
- [ ] Test default is skip-when-LLM-env-not-set so the suite stays runnable in CI without leaking egress.
- [ ] Manual real-data muscle-question gate (AC8) re-run against the rebuilt sandbox; result captured in `work-notes.md`.

---

## Testing Strategy

### Unit Tests

- **n/a** — pure prompt + test surface; nothing pure-functional to test under `tests/unit/`.

### Integration Tests

- `packages/toolkit/tests/agent_replay/test_*.py` (Phase 3) — these are the integration tests for the agent's prompt-following behavior under mocked tool-result envelopes.

### Provenance Tests

- **n/a** — no derived rows produced.

### Determinism Tests

- **n/a** — no pipeline reruns; LLM calls are inherently non-deterministic. The replay tests assert on the *presence/absence* of specific phrases, not on byte-equivalent outputs. If a scenario test flakes under model-temperature variation, the LLM-client fixture pins `temperature=0` and `seed=<fixed>`.

### Privacy-Default Tests

- `tests/agent_replay/conftest.py` gates real LLM calls behind `GENOMECLAW_REPLAY_LLM=<model>`. Default `pytest .` does not make a real LLM call; scenarios skip cleanly. This matches the `_live_smoke/` pattern.

### Evidence-Binding Tests

- **n/a** — this plan is about agent cognition discipline, not finding-citation discipline.

### Report Rendering Tests

- **n/a** — no report templates touched.

### Tool-Contract Tests

- **n/a** — no external bioinformatics tool conventions touched.

### Invariant Tests

- [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — extended in Phase 2 (forbidden-phrase list + network-failure predicate).
- [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — extended in Phase 1 (Step 3 capability-claim assertion) + Phase 2 (per-catalogue-row assertions).

---

## Documentation Updates

After implementation is complete:

- [x] [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — bumped to v1.21.1; updated `INV-A005` **How to verify** with Phase 1 + Phase 2 test references; cross-linked the Step 3 capability-claim test under `INV-A002`'s **How to verify**. No rule-text change; only enforcement-surface extension.
- [x] [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — primary surface; Phases 1 + 2 edit it directly.
- [x] Root [CLAUDE.md](../../../../CLAUDE.md) — no change (no top-level invariant or domain term shifts).
- [x] `.claude/agents/*.md` — no change.
- [x] [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md) — follow-up plan stub filed 2026-05-28 to track the deferred automated harness.
- [~] ~~Optional: add `docs/reference/agent-failure-phrase-catalogue.md` if Open Question Q3 resolves toward Option A (external fixture).~~ Deferred per Q3 default (inline catalogue, Phase 2 decision).

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — Step 3 capability-claim amendment | **Complete** | 2026-05-28 | 2026-05-28 | RED → GREEN → REFACTOR in one session. 1 new contract test (`test_invA002_step3_memory_validation_special_cases_capability_claims`). 14/14 contract tests pass. |
| Phase 2 — §INV-A005 catalogue extension | **Complete** | 2026-05-28 | 2026-05-28 | RED → GREEN → REFACTOR in one session. 4 new tests (2 contract + 2 trace-walker); 6 new `_FORBIDDEN_PHRASES`; signal predicate extended. 26/26 contract + walker tests pass. |
| Phase 3 — ~~Agent-replay harness~~ Manual AC8 gate | **Scope-reduced** (2026-05-28) | 2026-05-28 | *(pending operator manual gate)* | Automated replay harness deferred to follow-up plan [agent-replay-harness-for-prompt-regression](../agent-replay-harness-for-prompt-regression.md). Phase 3 reduces to the manual AC8 muscle-question gate against the rebuilt sandbox. |

---

## Open Risks & Follow-ups

- **R1**: Replay tests may be flaky under model-temperature variation even with `temperature=0` if the chosen model isn't fully deterministic. Mitigation: assert on *phrase presence/absence*, not on exact wording; pin model + seed where supported; document any observed flake in `work-notes.md`.
- **R2**: The catalogue may need entries for failure shapes the plugin grows in the future. Mitigation: if the catalogue churns past 6 entries or the plugin team needs to register phrases independently, promote to an external fixture (Open Question Q3 Option A) and add a small invariant.
- **R3**: Auto-write of superseding memory notes (Open Question Q2 deferred) may become desirable if the memory store accumulates stale capability claims faster than synthesis turns clean them up. File a follow-up plan if observed.
- **R4**: The host-service restart fragility that originally exposed Bug 2 is *out of scope* here. If it isn't fixed separately, expect occasional all-failed-same-reason turns; the catalogue ensures the agent describes them correctly, but doesn't prevent the underlying infrastructure failure.

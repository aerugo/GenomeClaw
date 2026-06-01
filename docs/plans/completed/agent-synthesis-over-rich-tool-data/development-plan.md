# Agent Synthesis Over Rich Tool Data — Development Plan

**Status**: Complete (2026-06-01) — all 6 phases done; `INV-A005` v1.23 promoted (`INVARIANTS.md` v1.24). Phase 6 closed at architecture-level pass; the 2 agent-reply-fidelity bugs the LLM-judge caught are handed to the follow-up plan `agent-reply-fidelity-confabulation-and-failure-mode`.
**Created**: 2026-05-28
**Branch**: `feature/agent-synthesis-over-rich-tool-data`
**Spec**: [spec.md](spec.md)

---

## Summary

Correct the `INV-A005` v1.22 architecture: the prompt forced the agent to mechanically quote `error_type` fields verbatim. The intended design is **rich raw data from the tools + interpretive synthesis by the agent + LLM-judge verification**. This plan extends tool-result shapes with richer diagnostic data, rewrites the §INV-A005 prompt rule from "quote verbatim" to "analyze and present," and replaces the structural literal-token walker with an LLM-judge harness.

## Critical Invariants to Respect

- **INV-A005** v1.22 → v1.23 (this plan promotes the rewrite). Mechanism shifts from "literal `error_type` token in reply" to "faithful + understandable synthesis verified by LLM-judge."
- **INV-A006** Plugin Tool-Result Returns Structured Envelopes — **unchanged**. This plan extends each envelope variant's detail fields but keeps the discriminated-union shape + `error_type` discriminator.
- **INV-V001** Verification Mechanisms Must Not Enumerate Forbidden Phrases — **honored**. LLM-judge is the sanctioned alternative (per V001's enumerated options: structural / quote-verbatim / semantic). This plan picks "semantic" and shows it doesn't reduce to enumeration.
- **INV-A002** Synthesis Reasoning Floor v1.8 bullet 3 — **unchanged**. Step 3 capability-claim bullet is structural; this plan doesn't touch it.
- **INV-P001** Privacy Default — LLM-judge calls `gpt-5.5` via the existing egress allowlist; default-skip when env var unset.

## Proposed New Invariants

- **NEW INV-D010 (proposed)** *Tool-Result Richness*: tool wrappers in any GenomeClaw plugin MUST forward the host service's full diagnostic context (trace, command, partial logs, stage at which failure occurred) — they must NOT pre-summarize to a minimal payload. The agent decides what's relevant; the wrapper is a transparent forwarder. **Decide during Phase 3 review** — promote if the host-service + plugin work feels coherent enough to anchor a project-wide rule.

## Current State Analysis

The 2026-05-28 `INV-A005` v1.22 rewrite (sister plan, just completed) shipped three coupled changes:

1. **Plugin returns structured envelopes** (`INV-A006`) — ✅ keep.
2. **Prompt teaches "quote `error_type` verbatim"** — ❌ revert. This is mechanical transcription, not synthesis.
3. **Trace-walker asserts literal `error_type` tokens in reply** — ❌ revert. Same mistake at the test layer.

The Stage-2 AC8 gate "passed" with the agent saying `` `error_type: network_error` with `raw_error: fetch failed` `` — robotic JSON-field transcription. The user reads this as "a genome interpretation system that talks like a JSON dump." Not the design.

### What's right (keep)

- `ToolFailureEnvelope` discriminated union with 4 `error_type` arms. The agent benefits from the typed discriminator for reasoning; the user just doesn't see it.
- `INV-A006` discovery test (plugin returns structured envelopes).
- `INV-V001` discovery test (no phrase enumeration).
- Trajectory file capture convention.
- The §INV-A005 multi-turn investigation guidance.
- Step 3 capability-claim bullet (INV-A002 v1.8 bullet 3).

### What's wrong (correct)

| Surface | What's there now | Fix |
|---------|------------------|-----|
| [agent-system-prompt.md §INV-A005](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | *"Your reply MUST contain at least one backtick-quoted excerpt of the actual `error_type` value or a structured detail field value"* | Replace with *"You have rich structured tool-result data. Analyze it. Present your findings in clear, natural language."* The `error_type` and structured fields are for the agent's reasoning, not for verbatim insertion. |
| [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | Asserts every `error_type` value in the trajectory appears literally in the reply. | Delete. Replace with LLM-judge over (trajectory, reply). |
| [test_agent_system_prompt_contract.py::test_invA005_v122_*_teaches_quote_verbatim_discipline](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | Asserts the prompt teaches the quote-verbatim rule. | Rewrite: assert the prompt teaches analyze-and-present (positive markers) + does NOT mandate verbatim quoting (negative markers). |
| `INV-A005` rule text in `INVARIANTS.md` | v1.22 specifies literal-token verification. | Rewrite to v1.23: semantic verification via LLM-judge. |

### What's missing (add)

| Surface | Gap | Add |
|---------|-----|-----|
| Host service response models (`packages/toolkit/src/genomeclaw_toolkit/service/`) | Minimal failure responses (`{status, error}`); no nextflow trace, no command, no stage. | Extend with diagnostic detail fields. Phase 1 audits per-tool; Phase 2 implements per-tool extensions. |
| Plugin `ToolFailureEnvelope` arms | Only have minimal detail fields (e.g., `host_failure` has `host_error` string only). | Extend each arm with optional rich-detail fields that mirror the host service's new diagnostic data. |
| LLM-judge harness | Doesn't exist (was deferred at the sister plan's Stage 5). | Add `packages/toolkit/tests/agent_replay/` with conftest + judge driver + scenario tests. |

### Files to Modify

| File | Planned Changes |
|------|-----------------|
| `packages/toolkit/src/genomeclaw_toolkit/service/<routes>.py` (Phase 1 audit identifies which) | Extend response models with richer diagnostic fields (trace excerpts, command logs, stage info). Additive — existing fields kept. |
| [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) | Extend `ToolFailureEnvelope` variants with optional rich-detail fields. Update `wrapHostResponse` + `safeCall` catches to forward the richer payload data. |
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) §INV-A005 | Rewrite from verbatim-quoting to analyze-and-present. Keep multi-turn investigation rule; keep per-tool decomposition; keep cross-link to INV-A002 Step 3 bullet 4. |
| [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | **DELETE** the literal-token walker. The file becomes a skip-by-default stub OR is deleted entirely (decide in Phase 4). |
| [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | Rewrite the three v1.22 contract tests: drop quote-verbatim, add analyze-and-present positive markers + verbatim-absent negative assertions. |
| [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) | INV-A005 rule rewrite v1.22 → v1.23. Optionally promote INV-D010. Version bump. |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/agent_replay/__init__.py` | Test package marker. |
| `packages/toolkit/tests/agent_replay/conftest.py` | Env-gated LLM-client fixture (skip when `GENOMECLAW_REPLAY_LLM` unset). |
| `packages/toolkit/tests/agent_replay/_judge.py` | LLM-judge driver: takes `(trajectory_path, reply_text)`, sends to `gpt-5.5`, parses structured yes/no + reason. |
| `packages/toolkit/tests/agent_replay/test_invA005_v123_reply_is_faithful_to_trajectory.py` | Parametrized over captured traces (with sibling trajectory files); calls judge; asserts faithful + understandable. |

## Solution Design

```text
                       ┌──────────────────────────────────────┐
                       │ Host service (Python/FastAPI)        │
                       │ ┌──────────────────────────────────┐ │
   Phase 1 ──→ AUDIT ──│ │ Audit current response shapes:   │ │
                       │ │ - pgs_compute failure body       │ │
                       │ │ - gene/variant/findings success  │ │
                       │ │ - status, evidence, pgs_list/get │ │
                       │ │ Identify diagnostic gaps         │ │
                       │ └──────────────────────────────────┘ │
                       │ ┌──────────────────────────────────┐ │
   Phase 2 ──→ EXTEND ─│ │ Add rich-detail fields to        │ │
                       │ │ response models (additive):      │ │
                       │ │ - failure: trace, command, stage │ │
                       │ │ - success: row counts, partials  │ │
                       │ └──────────────────────────────────┘ │
                       └─────────────────┬────────────────────┘
                                         │
                                         │ rich JSON envelope
                                         ▼
                       ┌──────────────────────────────────────┐
                       │ Plugin (TypeScript)                  │
                       │ ┌──────────────────────────────────┐ │
   Phase 3 ──→ FORWARD │ │ Extend ToolFailureEnvelope arms  │ │
                       │ │ with optional rich-detail fields.│ │
                       │ │ Forward host data verbatim       │ │
                       │ │ (no truncation, no pre-summary). │ │
                       │ │ Update INV-A006 discovery test   │ │
                       │ │ to require detail-field presence │ │
                       │ │ where appropriate.               │ │
                       │ └──────────────────────────────────┘ │
                       └─────────────────┬────────────────────┘
                                         │
                                         │ rich envelope to agent
                                         ▼
                       ┌──────────────────────────────────────┐
                       │ Agent system prompt §INV-A005        │
                       │ ┌──────────────────────────────────┐ │
   Phase 4 ──→ REWRITE │ │ DROP: "quote verbatim" rule.     │ │
                       │ │ ADD: "analyze, interpret, present│ │
                       │ │   in clear language."            │ │
                       │ │ KEEP: multi-turn investigation,  │ │
                       │ │   per-tool decomposition,        │ │
                       │ │   cross-link to Step 3 bullet 4. │ │
                       │ └──────────────────────────────────┘ │
                       │ ┌──────────────────────────────────┐ │
                       │ │ Update prompt-contract tests:    │ │
                       │ │ - delete quote-verbatim test     │ │
                       │ │ - add analyze-and-present test   │ │
                       │ │ - add negative (no "MUST quote") │ │
                       │ └──────────────────────────────────┘ │
                       └─────────────────┬────────────────────┘
                                         │
                                         │ agent reply (natural language)
                                         ▼
                       ┌──────────────────────────────────────┐
                       │ Verification (LLM-judge)             │
                       │ ┌──────────────────────────────────┐ │
   Phase 5 ──→ BUILD ──│ │ packages/toolkit/tests/agent_    │ │
                       │ │   replay/ harness:               │ │
                       │ │ - conftest: env-gated client     │ │
                       │ │ - _judge.py: gpt-5.5 driver      │ │
                       │ │ - scenario tests parametrized    │ │
                       │ │   over (trace, trajectory) pairs │ │
                       │ │ - DELETE the literal-token walker│ │
                       │ │ - INV-A005 v1.23 rule rewrite    │ │
                       │ │   in INVARIANTS.md               │ │
                       │ └──────────────────────────────────┘ │
                       └─────────────────┬────────────────────┘
                                         │
                                         │ verified
                                         ▼
                       ┌──────────────────────────────────────┐
   Phase 6 ──→ AC8 ────│ Rebuild sandbox + re-run muscle      │
                       │ question. Verify: reply is plain     │
                       │ language; LLM-judge passes; no       │
                       │ literal "error_type:" transcription. │
                       └──────────────────────────────────────┘
```

### Key Design Decisions

1. **Plugin envelopes stay structured (INV-A006); only their PROSE-FACING ROLE for the agent changes.** The agent still gets typed discriminators (`error_type` enum) for reasoning. It just doesn't quote them verbatim. The structural shape is a reasoning aid, not a transcription template.

2. **Host service extension is the foundational change.** Before the agent can "synthesize rich data," there has to BE rich data. Today's failure responses are skeletal (e.g., `{"status":"failed","error":"prs_compute_config_missing"}`). The agent has nothing to synthesize from — no command run, no nextflow trace, no stage info. Phase 1 + 2 fix this. Without it, the prompt rewrite is asking the agent to synthesize what isn't there.

3. **LLM-judge is the semantic verification.** Per `INV-V001`, three alternatives are sanctioned: structural / quote-verbatim / semantic. v1.22 picked quote-verbatim (now invalidated). v1.23 picks semantic (LLM-judge). The trajectory file is still the canonical input; the judge reads it instead of a substring walker.

4. **Default-skip LLM-judge** (env-gated via `GENOMECLAW_REPLAY_LLM=gpt-5.5`). Matches `_live_smoke/`'s pattern. CI runs make no LLM calls by default; operator-driven gates opt in.

5. **The four `error_type` enum values stay** (`placeholder_rejected`, `host_failure`, `network_error`, `http_error`). Useful for the agent's reasoning + INV-A006 discovery test. The agent just doesn't have to quote them.

6. **Multi-turn investigation rule stays.** The user's stated architecture preference (raw returns + multi-turn loop) is independent of the verbatim-quoting question. The agent should still call diagnostic tools under unfamiliar failures. Just describe what it finds in natural language.

### Schema / Provenance Impact

- **None for derived stores.**
- Host-service response models: extend with optional fields (no breaking changes).
- Plugin envelope variants: extend with optional fields (additive).

### Privacy & Egress Impact

- **None new.** LLM-judge uses `gpt-5.5` via the existing OpenAI allowlist. Default-skip preserves `INV-P001`.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests | Scope |
|-------|-------------|-----------|------------|-------|
| 1 | Audit host-service tool-result shapes | Documentation; no code yet | 0 | Audit-only |
| 2 | Extend host-service responses with rich diagnostic data | Response-model unit tests + integration smoke | ~5 | Required |
| 3 | Plugin envelope extensions; update INV-A006 discovery if needed | Plugin envelope tests + INV-A006 discovery update | ~3 | Required |
| 4 | Prompt §INV-A005 rewrite (drop verbatim, add analyze-and-present) | Prompt-contract tests rewritten | 3 (replaces 3 v1.22) | Required |
| 5 | LLM-judge harness + delete literal-token walker | Scenario tests with skip-by-default | ~2 | Required |
| 6 | AC8 re-run gate (semantic, not literal) | Manual gate + LLM-judge auto-check | 1 manual + 1 auto | Required |

## Phase 1: Audit Host-Service Response Shapes

**Goal**: Per-tool inventory of current vs. desired response richness.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

- `phases/phase-1-host-service-audit.md` — table of (tool name, current response shape, gap, proposed extension).

## Phase 2: Host-Service Response Extensions

**Goal**: Implement rich-detail extensions to response models per Phase 1 audit.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables

- Updated service-side response models (additive fields).
- Updated route handlers that populate the new fields.
- Unit + integration tests for the new fields.

## Phase 3: Plugin Envelope Extensions

**Goal**: Extend `ToolFailureEnvelope` arms + ensure plugin forwards rich data without truncation.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables

- Extended TypeScript types (additive fields).
- Updated plugin-side unit tests (envelope shape).
- Updated `INV-A006` discovery test (require rich-detail fields where applicable).
- Optionally: promote `INV-D010` (Tool-Result Richness) if scope feels coherent.

## Phase 4: Prompt §INV-A005 Rewrite

**Goal**: Drop verbatim-quoting; add analyze-and-present discipline.
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables

- Rewritten §INV-A005 prompt section.
- Three rewritten prompt-contract tests:
  - `test_invA005_v123_system_prompt_teaches_analyze_and_present_discipline` (positive)
  - `test_invA005_v123_system_prompt_does_not_mandate_verbatim_quoting` (negative)
  - `test_invA005_v123_system_prompt_teaches_multi_turn_investigation` (unchanged from v1.22)
- Deleted: `test_invA005_v122_system_prompt_teaches_quote_verbatim_discipline`.

## Phase 5: LLM-Judge Harness + Delete Literal-Token Walker

**Goal**: Build the semantic verification mechanism; delete the v1.22 walker.
**Detailed Plan**: [phases/phase-5.md](phases/phase-5.md)

### Deliverables

- `packages/toolkit/tests/agent_replay/conftest.py` (env-gated LLM-client fixture).
- `packages/toolkit/tests/agent_replay/_judge.py` (gpt-5.5 driver).
- `packages/toolkit/tests/agent_replay/test_invA005_v123_reply_is_faithful_to_trajectory.py` (parametrized scenario).
- **DELETED**: `test_invA005_v122_reply_quotes_error_type_for_every_failure` from the walker test file.
- Updated `INVARIANTS.md` v1.23: INV-A005 rule rewrite + (optional) INV-D010 promotion + Invariant Index + version bump.

## Phase 6: AC8 Re-Run Gate (Semantic Verification)

**Goal**: Rebuild sandbox + re-run muscle question + verify the reply is plain-language synthesis, not JSON transcription.
**Detailed Plan**: [phases/phase-6.md](phases/phase-6.md)

### Deliverables

- New captured trace under `docs/reports/demo-2026-05-28-logs/post-v123-muscle-question.{trace.json,trajectory.jsonl}` (or 2026-05-29-logs if work spans the date).
- LLM-judge result for the captured trace (pass/fail + reasoning).
- Side-by-side comparison vs. the v1.22 trace at [stage2-gate-muscle-question.trace.json](../../../../docs/reports/demo-2026-05-28-logs/stage2-gate-muscle-question.trace.json) — documented in work-notes.
- Plan moved to `completed/` on AC8 pass.

---

## Testing Strategy

### Unit Tests

- Host-service response model unit tests (Phase 2).
- Plugin envelope-shape unit tests (Phase 3).
- Prompt-contract tests for §INV-A005 v1.23 (Phase 4).

### Integration Tests

- Host-service integration tests for the new diagnostic fields (Phase 2).
- LLM-judge scenario tests (Phase 5).

### Provenance Tests

- **n/a** — no derived-store impact.

### Determinism Tests

- LLM-judge is inherently non-deterministic. Pin `temperature=0` + accept pass/fail on majority of N=3 runs if needed. Resolve during Phase 5.

### Privacy-Default Tests

- LLM-judge conftest gates on `GENOMECLAW_REPLAY_LLM` env var; default `pytest` runs skip.

### Evidence-Binding Tests

- **n/a** — agent reply faithfulness is the target, not citation-completeness.

### Report Rendering Tests

- **n/a** — no report templates touched.

### Invariant Tests

- INV-A005 v1.23: judge-based, no literal-token check.
- INV-A006: discovery test possibly tightened in Phase 3.
- INV-V001 discovery test: unchanged; LLM-judge is a sanctioned alternative under V001.

---

## Documentation Updates

After implementation:

- [ ] `INVARIANTS.md` v1.24: INV-A005 v1.23 rewrite + (optional) INV-D010 entry + Invariant Index update.
- [ ] `docs/plans/CLAUDE.md` Planning Standards section G (INV-V001 paragraph) — add a note that semantic verification (LLM-judge) is the preferred sister to structural verification when the property is meaning-bound. Current text already mentions LLM-judge as an option; verify wording.
- [ ] `.claude/agents/test-engineer.md` — note that LLM-judge harnesses live under `tests/agent_replay/` and gate on `GENOMECLAW_REPLAY_LLM`.
- [ ] Root `CLAUDE.md` — no change.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — Audit | **Complete** | 2026-05-28 | 2026-05-28 | 7 of 9 tools already rich; 2 need extension (pgs_compute + pgs_compute_status). |
| Phase 2 — Host-service extensions | **Complete** | 2026-05-28 | 2026-05-28 | 16 tests pass. `ToolDiagnosticTrace` model + `derive_diagnostic_from_error_code` covers 12 error-code shapes. No SQLite migration. |
| Phase 3 — Plugin envelope extensions | **Complete** | 2026-05-28 | 2026-05-28 | 33 plugin tests pass; typecheck clean. `host_failure` arm forwards `diagnostic`. |
| Phase 4 — Prompt rewrite (drop verbatim) | **Complete** | 2026-05-28 | 2026-05-28 | 21 prompt-contract tests pass. §INV-A005 rewritten: analyze-and-present + 5 worked examples + 2 new tests (positive + negative gate). |
| Phase 5 — LLM-judge harness + delete walker | **Complete** | 2026-05-28 | 2026-05-28 | `tests/agent_replay/` shipped (default-skip). v1.22 walker deleted. `INVARIANTS.md` v1.24 + `INV-A005` v1.23. |
| Phase 6 — AC8 re-run gate | **Complete (architecture-level pass)** | 2026-05-29 | 2026-06-01 | Reply is unambiguously plain language (no JSON transcription). Judge correctly identified 2 real fidelity bugs v1.21/v1.22 couldn't reach — the mechanism working. 2 bugs handed to follow-up plan `agent-reply-fidelity-confabulation-and-failure-mode`; plan closed + moved to completed/. |

---

## Open Risks & Follow-ups

- **R1 — Host-service refactor scope creep**: extending response models touches potentially many service routes. Phase 1's audit must be thorough so Phase 2 doesn't sprawl. If scope balloons, descope to the highest-value targets (`pgs_compute` failure, `gene` success) for this plan and follow up.
- **R2 — Judge calibration**: the LLM-judge has to be tuned. Bad prompts → flaky verdicts. Need ground-truth trace pairs (the v1.22 captured trace + a hand-written "good" reply) to calibrate. Phase 5 includes this.
- **R3 — Judge cost**: each judge run is one `gpt-5.5` call per scenario. Default-skip mitigates; operator opts in. Not a CI-budget issue unless we add many scenarios.
- **R4 — Reverting v1.22 in mid-stream**: the v1.22 prompt + walker are CURRENTLY shipped. Until Phase 4 + 5 land, the agent is operating under the verbatim-quoting rule. Stage the change so the prompt rewrite + walker deletion land together with the sandbox rebuild — don't run sandboxes with the v1.22 prompt + the v1.23 walker (or vice versa) mid-stream.
- **R5 — Cross-link to INV-A002 Step 3 bullet 4**: the §INV-A005 rewrite must preserve the cross-link to "stale capability claims are superseded by live data." The rewrite text mentions this; verify during Phase 4 RED.

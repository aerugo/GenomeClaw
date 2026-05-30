# Eliminate Forbidden-Phrase Enumeration Project-Wide — Development Plan

**Status**: Draft
**Created**: 2026-05-28
**Branch**: `feature/eliminate-forbidden-phrase-enumeration`
**Spec**: [spec.md](spec.md)

---

## Summary

Audit + clean up all load-bearing substring/regex enumeration of forbidden phrases in the GenomeClaw repo. Promote `INV-V001` as the project-wide rule. Add a discovery test that prevents future regressions. Sister to [inv-a005-structural-faithfulness](../inv-a005-structural-faithfulness/) — that plan is the INV-A005 pilot; this plan generalizes the methodology.

## Critical Invariants to Respect

- **NEW `INV-V001`** (proposed) — *Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output*. Promoted in Phase 2.
- **INV-A005** v1.22 — sister plan ships this. This plan respects it as already-rewritten by Phase 1.
- **INV-A006** (sister plan's proposal) — Plugin Tool-Result Returns Structured Envelopes. Same lineage — both invariants are about *structural verification mechanisms over paraphrased prose*.
- **INV-T001** External-Tool Conventions Captured as Typed Wrappers — adjacent precedent.

## Proposed New Invariants

- **NEW `INV-V001`** Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output.
  - **Rule**: Any test or content gate that verifies properties of agent-generated output (reply text, memory notes, tool-call planning text) MUST use structural inspection (typed envelopes, schema fields, AST walks), LLM-judge evaluation, or quote-verbatim discipline. Substring-list enumeration of banned or required phrases is forbidden for load-bearing correctness gates.
  - **Why**: LLM paraphrase-space is effectively infinite. Substring enumeration is whack-a-mole — every new paraphrase requires a new entry, and the agent always finds new wording. The AC8 manual gate of the parent plan demonstrated this empirically (agent invented "object-shape serialization error" — same confabulation class, paraphrase not on our list).
  - **Requirements**:
    - Tests under `packages/toolkit/tests/invariants/` and `packages/toolkit/tests/integration/` MUST NOT use module-level string tuples/lists as the primary verification of agent reply content. Backstop substring checks (regression pinning, sanity smoke) MAY exist but MUST carry an inline `# INV-V001-backstop:` comment.
    - Agent prompt files (`*-system-prompt.md`) MUST NOT include enumerated "do not say X / Y / Z" rule tables. Discipline must be rule-based (quote structural fields verbatim, multi-turn investigation, etc.).
    - Plugin tool wrappers MUST return structured envelopes per `INV-A006` (the architectural underpinning).
  - **Where it applies**:
    - `packages/toolkit/tests/invariants/`
    - `packages/toolkit/tests/integration/`
    - `packages/*-plugin/sandbox/*-system-prompt.md`
    - Any future plugin's tool wrappers under `packages/*-plugin/src/`.
  - **How to verify**:
    - **`tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py`** — discovery test (Phase 3 of this plan). Walks test files + prompt files for string-tuple literals + agent-output checks. Each site must carry either `# INV-V001-backstop:` (declared non-load-bearing) or `# INV-V001-allow:` (explicitly waived with rationale comment). Anything else fails.

## Current State Analysis

Per the 2026-05-28 Explore-agent audit:

**Load-bearing primary gates** (eliminated by sister plan):
- `_FORBIDDEN_PHRASES` (11 entries) + `_STRUCTURAL_FAILURE_SIGNALS` (8 entries) + `_GENOMECLAW_HTTP_ERROR_PATTERN` in [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py)
- `_CATALOGUE_ROWS` (5 entries) in [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)
- §INV-A005 catalogue table in [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)
- Prose returns in [index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) (`rejectIfPlaceholder`, `wrapHostResponse`, `safeCall`/`safePost`)

→ **Sister plan eliminates all of these.** This plan verifies the elimination + generalizes the rule.

**Backstop / non-load-bearing sites** (review + annotate, keep):
- Prompt-content gates throughout `test_agent_system_prompt_contract.py` (`assert "X" in text` for prompt-concept presence — INV-A001 / INV-A002 / INV-C001 / etc.). Most check the prompt teaches required concepts; agent could rephrase + still be correct. Annotate inline.
- Integration tests with substring smoke checks (`"HTTP 422" not in reply`). Regression pins, not agent-behaviour gates. Annotate inline.
- `_FORBIDDEN_ARGV_PATTERNS` in [test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py) — regex for argv-shape anti-patterns (structural, not paraphrase). Different class. Document the distinction; keep.

**Future-work plans containing phrase-enumeration proposals**:
- [agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md) — sister plan supersedes this stub.

### Files to Modify (Phase 2)

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | Many `assert "X" in text` checks, mostly non-load-bearing | Annotate each `assert "X" in text` block with `# INV-V001-backstop:` + 1-line justification (what real property is checked). |
| [test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py) | `_FORBIDDEN_ARGV_PATTERNS` regex tuple (structural) | Annotate with `# INV-V001-allow:` + 1-line rationale (regex for argv structural anti-patterns, not paraphrase enumeration). |
| `packages/toolkit/tests/integration/**.py` | Various `"X" not in reply` regression-pin substring checks | Audit + annotate each as `# INV-V001-backstop:`. |

### Files to Create (Phase 3)

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py` | Discovery test enforcing `INV-V001`. Walks test files + prompt files; requires inline annotation on every string-tuple literal touching agent output. |

### Files to Update (Phase 4)

| File | Purpose |
|------|---------|
| [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) | New `INV-V001` entry + new `INV-V*` category section + Invariant Index update + version bump. |
| [docs/plans/CLAUDE.md](../CLAUDE.md) | Add a paragraph in Planning Standards about `INV-V001`: planners must not propose phrase-enumeration as a primary verification mechanism. |
| [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) | Add a Test-Priorities entry teaching the three preferred alternatives (structural, semantic/LLM-judge, quote-verbatim) + a `# INV-V001-backstop:` annotation requirement for any substring backstop. |

## Solution Design

```text
       ┌─────────────────────────────────────────────────┐
       │ Sister plan (inv-a005-structural-faithfulness)  │
       │ — eliminates the INV-A005 phrase-list site      │
       │ — establishes the structural-envelope precedent │
       │ — promotes INV-A006                             │
       └────────────────────┬────────────────────────────┘
                            │  Phase 1 audit runs in parallel
                            ▼
       ┌─────────────────────────────────────────────────┐
       │ This plan, Phase 1: AUDIT                       │
       │ — confirm sister plan's sites are eliminated    │
       │ — catalogue remaining string-tuple sites        │
       │ — categorize: load-bearing? backstop?           │
       │   structural?                                   │
       └────────────────────┬────────────────────────────┘
                            │
                            ▼
       ┌─────────────────────────────────────────────────┐
       │ Phase 2: CLEANUP                                │
       │ — annotate each backstop with                   │
       │   # INV-V001-backstop: comment                  │
       │ — annotate each structural site with            │
       │   # INV-V001-allow: comment                     │
       │ — promote any remaining load-bearing sites to   │
       │   structural / semantic replacements            │
       └────────────────────┬────────────────────────────┘
                            │
                            ▼
       ┌─────────────────────────────────────────────────┐
       │ Phase 3: META-DISCOVERY TEST                    │
       │ — test_invV001_no_phrase_enumeration_in_agent_  │
       │   output_gates.py                               │
       │ — fails if a string-tuple literal in            │
       │   tests/invariants/ or tests/integration/ isn't │
       │   annotated with INV-V001-backstop or           │
       │   INV-V001-allow                                │
       └────────────────────┬────────────────────────────┘
                            │
                            ▼
       ┌─────────────────────────────────────────────────┐
       │ Phase 4: PROMOTE INV-V001 + DOCS                │
       │ — INVARIANTS.md entry (new INV-V* category)     │
       │ — docs/plans/CLAUDE.md planning-standards note  │
       │ — .claude/agents/test-engineer.md skill update  │
       └─────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Annotation-driven enforcement, not source-code prohibition.** The discovery test doesn't ban string tuples — it requires each one touching agent output to declare *why it's allowed*. This makes the rule visible at every site + lets backstop / structural-pattern sites stay (with rationale).
2. **Two annotation tokens**:
   - `# INV-V001-backstop: <one-line rationale>` — non-load-bearing sanity / regression-pin substring check.
   - `# INV-V001-allow: <one-line rationale>` — explicitly waived (e.g., structural regex like INV-P003's argv-shape patterns).
   - No annotation → discovery test fails the file.
3. **Sister plan is the pilot.** This plan generalizes once the sister plan's structural-envelope pattern is in place. Sequencing: sister plan Phase 1–3 → this plan Phase 1–2 → both plans Phase 3+ in parallel.
4. **`INV-V*` is a new top-level invariant category** for verification-methodology rules. Future invariants in this space (e.g., `INV-V002` for LLM-judge-cost-budget discipline) get a natural home.
5. **The meta-discovery test's pattern detection is annotation-based, not AST-based.** Simpler, more transparent, easier to debug. Trade-off: requires discipline to add the annotation when introducing a new substring tuple. Phase 4's planning-protocol update covers this.

### Schema / Provenance Impact

- **None.** Tests + invariants + planning docs only.

### Privacy & Egress Impact

- **None.**

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Audit (catalog sites, categorize) | Documentation; no code yet | 0 |
| 2 | Cleanup — annotate each non-load-bearing site; replace any remaining load-bearing site | Each annotated site verified by re-running existing tests | 0 (no new) |
| 3 | Meta-discovery test (`test_invV001_*`) | Discovery test fails for un-annotated sites; passes after Phase 2's annotations land | 1 |
| 4 | Promote `INV-V001` + docs | Invariants doc test passes; planning protocol updated | 1 (lightweight) |

## Phase 1: Audit

**Goal**: Comprehensive site list of every substring/regex enumeration of agent-output-related patterns in the repo, categorized as primary / backstop / structural.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

1. `phases/phase-1-audit-findings.md` — file-by-file inventory with category + recommended action.
2. Update [work-notes.md](work-notes.md) with the audit summary.

### Invariants Enforced Here

- None (audit phase; no enforcement until Phase 2+3).

### Success Criteria

- [ ] Every site touching agent output (reply text, memory notes, planning text) with a string-tuple or substring check is in the audit report.
- [ ] Each site categorized: **primary** (must be replaced), **backstop** (annotate + keep), **structural** (annotate + keep), or **future-plan** (will be filed correctly per `INV-V001`).
- [ ] No new "primary" sites discovered beyond what the sister plan already addresses (if any are found, log as Phase 2 prerequisites).

## Phase 2: Cleanup — Annotate or Replace

**Goal**: For every audited site, either add the appropriate `# INV-V001-{backstop,allow}:` annotation OR replace with a structural / semantic alternative (sister plan handles INV-A005; this plan handles the rest).
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables

1. Annotated test + prompt files per Phase 1 audit recommendations.
2. Any remaining load-bearing sites replaced (expectation: minimal — sister plan covered the main ones).

### Invariants Enforced Here

- **NEW `INV-V001`** (provisional; formal promotion in Phase 4).

### Success Criteria

- [ ] Every string-tuple literal in `tests/invariants/` + `tests/integration/` touching agent output carries an `INV-V001-{backstop,allow}:` annotation.
- [ ] All existing tests still pass after annotation (annotations are comments — no behavioural change).

## Phase 3: Meta-Discovery Test

**Goal**: Discovery test `test_invV001_no_phrase_enumeration_in_agent_output_gates.py` enforces the annotation discipline going forward.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables

1. New discovery test under `packages/toolkit/tests/invariants/`.
2. Test parses test files via simple grep (or AST walk) for string-tuple/list literals; for each, requires an annotation comment within N lines.

### Invariants Enforced Here

- **NEW `INV-V001`** (Phase 4 promotes; this phase pre-implements the verification).

### Success Criteria

- [ ] Discovery test passes after Phase 2's annotations are in place.
- [ ] Discovery test fails if a new un-annotated string-tuple is introduced (verified by temporarily adding one + asserting failure, then reverting).

## Phase 4: Promote INV-V001 + Update Docs

**Goal**: Formal `INV-V001` entry in `INVARIANTS.md`; updates to planning protocol + test-engineer skill so future plans don't propose phrase enumeration.
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables

1. `INVARIANTS.md` updated with new `INV-V*` category section + `INV-V001` entry + Invariant Index update + version bump.
2. `docs/plans/CLAUDE.md` updated with a planning-standards paragraph teaching the rule.
3. `.claude/agents/test-engineer.md` updated with the three preferred alternatives + annotation discipline.

### Invariants Enforced Here

- **NEW `INV-V001`** (formally promoted).

### Success Criteria

- [ ] `INV-V001` lands in `INVARIANTS.md` with all template sections (Rule / Why / Requirements / Where it applies / How to verify / Related plans).
- [ ] Planning protocol + test-engineer skill carry the rule.
- [ ] Discovery test (Phase 3) continues to pass.

---

## Testing Strategy

### Unit Tests

- **n/a** — methodology cleanup; nothing pure-functional.

### Integration Tests

- The discovery test in Phase 3 IS the integration check that the methodology holds.

### Provenance / Determinism / Privacy-Default / Evidence-Binding / Report-Rendering Tests

- **n/a** — no derived stores, no pipelines, no reports affected.

### Invariant Tests

- **Phase 3's discovery test** is the cross-cutting `INV-V001` enforcement.

---

## Documentation Updates

- [ ] [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — new `INV-V*` category + `INV-V001` entry + version bump (Phase 4).
- [ ] [docs/plans/CLAUDE.md](../CLAUDE.md) — Planning Standards paragraph on `INV-V001` (Phase 4).
- [ ] [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) — Test Priorities + Anti-Patterns entries (Phase 4).
- [ ] Each touched test file — inline annotation comments (Phase 2).

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — Audit | **Complete** | 2026-05-28 | 2026-05-28 | Findings at [phases/phase-1-audit-findings.md](phases/phase-1-audit-findings.md). Headline: 4 primary (sister-plan scope) + ~22 backstops + 1 structural + 1 superseded. |
| Phase 2 — Cleanup / Annotate | **Complete** | 2026-05-28 | 2026-05-28 | 3 sites annotated: file-level `INV-V001-backstop-file:` in `test_agent_system_prompt_contract.py` (covers ~22 substring assertions); per-site `INV-V001-allow:` for `_FORBIDDEN_ARGV_PATTERNS` in `test_invP003_*`; per-site `INV-V001-backstop:` for `_STRUCTURED_FAILURE_PATTERNS` in `test_live_agent_prs_compute_e2e.py` + the `HTTP 422` regression-pin assertion. |
| Phase 3 — Meta-discovery test | **Complete** | 2026-05-28 | 2026-05-28 | `test_invV001_no_phrase_enumeration_in_agent_output_gates.py`: 4 test cases (primary + 3 confidence checks) all pass. Annotation-based discovery walks suspect tuples (FORBIDDEN_PHRASE / BANNED / FAILURE_PATTERN / ERROR_PATTERN / CATALOGUE_ROWS / STRUCTURAL_FAILURE_SIGNALS / FORBIDDEN_ARGV name patterns) + agent-output assertions (against `reply`/`agent_reply`/`finalAssistantVisibleText`); 15-line per-site lookback or file-level header. |
| Phase 4 — Promote INV-V001 + Docs | **Complete** | 2026-05-28 | 2026-05-28 | `INV-V001` landed in `INVARIANTS.md` v1.23 under new `INV-V*` (Verification Methodology) category. `docs/plans/CLAUDE.md` Planning Standards section G added. `.claude/agents/test-engineer.md` Test Priorities + Anti-Patterns entries added. |

---

## Open Risks & Follow-ups

- **R1 — Annotation drift over time**: developers may add new string-tuples without annotating, and the discovery test catches them — but only at PR time. Mitigation: planning-protocol update + test-engineer skill update teach the rule upfront.
- **R2 — Annotation discipline boundary**: some substring checks may be ambiguously primary vs. backstop. Phase 1 audit needs to land a clear categorization heuristic; Phase 2 may need to revisit borderline cases.
- **R3 — Sister-plan sequencing**: if the sister plan stalls, this plan can still ship Phase 1 (audit) + Phase 4 (docs) — but Phases 2–3's discovery test depends on the sister plan having removed the load-bearing INV-A005 sites. Sequence carefully.
- **R4 — Future plugins**: if other plugins are added (devrelclaw-plugin, etc.) outside `packages/nemoclaw-plugin/`, the rule extends to them. Phase 4's planning-protocol note must reference the general principle, not just nemoclaw's specifics.

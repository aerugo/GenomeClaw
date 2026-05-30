# Feature: Eliminate Forbidden-Phrase Enumeration Project-Wide

**Status**: Draft
**Created**: 2026-05-28
**Owner**: aerugo
**Related Plans**:
- [inv-a005-structural-faithfulness](../inv-a005-structural-faithfulness/) — sister plan; the pilot case for replacing phrase-list enforcement with structural + LLM-judge mechanisms. Sequence this plan AFTER (or interleaved with) the sister plan: the sister plan's structural-envelope pattern is the template this plan generalizes.
- [agent-stale-memory-and-failure-mode-confabulation (completed)](../../completed/agent-stale-memory-and-failure-mode-confabulation/) — the plan whose Phase 2 introduced the `_FORBIDDEN_PHRASES` / `_CATALOGUE_ROWS` patterns this plan removes.

---

## Goal

Eliminate substring/regex enumeration of forbidden phrases from every load-bearing correctness gate in the GenomeClaw repo. Replace each site with a structural, semantic, or LLM-judge mechanism. Add a project-wide invariant + meta-test that prevents future regressions back to phrase enumeration.

## Background

The user's 2026-05-28 rule: **"never rely on enumeration of 'forbidden phrases'."** The triggering failure was the AC8 manual gate of the `agent-stale-memory-and-failure-mode-confabulation` plan — the agent invented "object-shape serialization error" (a paraphrase not on our list), and the trace-walker's licensing-signal predicate turned out to be structurally circular. The pattern is general: LLM paraphrase-space is infinite; substring enumeration is whack-a-mole.

The audit (Explore-agent report, 2026-05-28) identified these sites:

**Load-bearing primary gates** (must be eliminated):
- `_FORBIDDEN_PHRASES` + `_STRUCTURAL_FAILURE_SIGNALS` in [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py). **Covered by sister plan.**
- `_CATALOGUE_ROWS` + parametrized catalogue test in [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py). **Covered by sister plan.**
- §INV-A005 failure-phrase catalogue in [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md). **Covered by sister plan.**

**Architectural root cause** (sister plan addresses):
- Prose-string returns from `rejectIfPlaceholder`, `wrapHostResponse`, `safeCall`/`safePost` in [index.ts](../../../../packages/nemoclaw-plugin/src/index.ts).

**Backstop / not-primary gates** (review during this plan's audit; replace if load-bearing, keep if non-load-bearing):
- Prompt-content gates throughout `test_agent_system_prompt_contract.py` (the `assert "X" in text` pattern for protocol-concept presence). Most are documentation backstops, not agent-behavior gates — keep but audit for load-bearing slips.
- `_FORBIDDEN_ARGV_PATTERNS` in [test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py). **Structural regex for argv-shape anti-patterns** (not paraphrase enumeration of agent output). Keep — different class.
- Integration-test smoke checks (`"HTTP 422" not in reply`) — backstops on pipeline regressions, not agent behaviour. Keep.

**Future-work plans**:
- The earlier [agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md) stub proposed phrase-list-based scenario tests. **Supersede in the sister plan.**

This plan does the project-wide cleanup pass after the sister plan ships the INV-A005 pilot. It generalizes the pattern, audits remaining sites, and adds a meta-invariant to prevent regression.

## Acceptance Criteria

- [ ] **AC1**: Repo-wide grep for the patterns (`_FORBIDDEN_*`, `_CATALOGUE_*`, parameterized `forbidden.*phrase` lists, `assert .* in reply` checks against enumerated tuples) under `packages/` produces only:
  - Non-load-bearing prompt-content backstops in `test_agent_system_prompt_contract.py` (documented as such).
  - Structural regex sites in `test_invP003_*` (different class; explicitly out of scope for this plan).
  - No other load-bearing site enumerates forbidden phrases.
- [ ] **AC2**: A new project-wide invariant **`INV-V001`** (proposed) — *Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output.* Rule: any test or content gate that verifies properties of agent-generated output must use structural inspection (typed envelopes, schema fields, AST), LLM-judge evaluation, or quote-verbatim discipline — never substring-list enumeration of banned/required phrases. Substring checks may appear ONLY as non-load-bearing sanity backstops (clearly labelled).
- [ ] **AC3**: A meta-invariant **discovery test** at `tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py`. The test walks `packages/toolkit/tests/invariants/` + `packages/toolkit/tests/integration/` + the agent prompt file, identifies any module-level tuple/list literal of >3 string entries that's used as a load-bearing check against agent output, and fails if it finds one not on a documented allowlist (the allowlist is small + each entry is annotated).
- [ ] **AC4**: For each backstop site identified during audit, an in-file `# INV-V001-backstop:` comment explicitly documents why the substring check is non-load-bearing + what the real correctness gate is. This makes the project-wide rule visible at every site.
- [ ] **AC5**: [INVARIANTS.md](../../../reference/INVARIANTS.md) updated with `INV-V001`. New invariant category `INV-V*` (Verification Methodology) introduced — or `INV-V001` slotted under an existing category if it fits.
- [ ] **AC6**: [docs/plans/CLAUDE.md](../CLAUDE.md) and `.claude/agents/test-engineer.md` updated to teach the rule + the three preferred alternatives (structural, semantic/LLM-judge, quote-verbatim). New tests proposing phrase enumeration get caught in plan review.
- [ ] **AC7**: After Plan 1 + Plan 2 land, **no substring `if "phrase" in agent_reply` check is the primary verification of any test** under `tests/invariants/`.

## Applicable Invariants

- **NEW `INV-V001`** Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output — proposed by this plan (Phase 2; discovery test in Phase 3).
- **INV-A005** v1.22 — already rewritten in the sister plan. This plan extends the same discipline project-wide.
- **INV-T001** External-Tool Conventions Captured as Typed Wrappers — adjacent precedent. INV-V001 is "INV-T001 for verification methodologies."

## Proposed New Invariants

- **NEW `INV-V001`**: Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output.
  - Rule + Why + Requirements + Where it applies + How to verify, per the existing INVARIANTS.md template.
  - Promoted in Phase 2 (after the audit + cleanup is mostly complete; the rule needs a clean state to be enforceable).

## Technical Requirements

### Source Data Inputs

- The audit report (already gathered in [work-notes.md](work-notes.md) — see "Phase 1 Audit Findings").
- Each test/prompt file identified as a load-bearing phrase-enumeration site.

### Derived Outputs

- Cleanup PRs for each site (or rolled into Phase 2 of this plan as in-place edits).
- New invariant `INV-V001` in `INVARIANTS.md`.
- New discovery test under `tests/invariants/`.
- Updated planning protocol + test-engineer agent skill.

### Schema / Migration Impact

- **None for derived stores.**
- New TypeScript types may be introduced for any plugin wrapper not yet using structured envelopes (Phase 1 audit finds these; the sister plan covers the known ones).

### Pipeline / Workflow Impact

- **None.** Tests + prompts + invariants only.

### Agent / UX Impact

- Stronger guard on the agent prompt: when Phase 2 lands `INV-V001`, no future plan can propose phrase enumeration as a verification mechanism without explicit waiver.

### External Dependencies

- None.

## Privacy & Safety Considerations

- **Boundary scan**: this plan's tests + prompt edits do not introduce egress. The substring-check elimination doesn't affect privacy posture.
- **Default-off remote calls**: any new LLM-judge mechanism introduced as a *replacement* for a phrase-list inherits the same env-gated default-skip pattern from the sister plan.
- **Redaction surface**: n/a.
- **Clinical escalation**: n/a.

## Out of Scope

- **Replacing the prompt-content gates that document concept presence** (most of `test_agent_system_prompt_contract.py`). These check that the prompt teaches required concepts; they're non-load-bearing for agent behaviour and may stay. Phase 1's audit categorizes each one + documents the category inline.
- **Eliminating regex-based structural pattern detection** (`test_invP003_*`'s argv-leak detection). That's structural anti-pattern detection, not paraphrase enumeration — different class. Stays.
- **Eliminating substring checks in integration tests** for pipeline-regression backstops (e.g., `"HTTP 422" not in reply` for a fix-pinning gate). These detect specific bug reintroductions, not paraphrase classes. Stays. Audit documents the distinction.
- **Restructuring tool wrappers in any plugin not yet returning structured envelopes** — sister plan covers the known nemoclaw-plugin case. Other plugins, if any, get audited here but restructured under follow-up plans tagged for `INV-A006` compliance.

## Dependencies

- [inv-a005-structural-faithfulness](../inv-a005-structural-faithfulness/) — sister plan; Phase 3 of that plan establishes the structural-envelope precedent + the `INV-A006` invariant. This plan generalizes the methodology + adds `INV-V001` as the project-wide rule.

## Open Questions

- [ ] **Q1 — Sequence with sister plan**: ship sister plan first, then this plan as a follow-up? Or interleave (Phase 1 audit of this plan in parallel with sister plan's Phases 1–2, then this plan's Phase 2 cleanup after sister plan's Phase 3)? Default: **interleave**; the audit work is independent of the INV-A005 fix and surfaces useful info during the sister plan's implementation.
- [ ] **Q2 — Invariant category for `INV-V001`**: introduce a new `INV-V*` category for verification-methodology rules, or slot under the existing `INV-T*` (Tool Integration)? Default: **new `INV-V*` category** — verification methodology is conceptually distinct from tool integration; cleaner top-level home.
- [ ] **Q3 — Discovery test mechanism**: how does AC3's meta-discovery test detect "module-level tuple of >3 strings used against agent output"? Options: (a) AST walker over Python test files, (b) regex grep + manual annotation, (c) require explicit `# INV-V001:` comments on every substring tuple and check those. Default: **(c) — annotation-based** — simpler + makes the rule visible at every site. The discovery test becomes: grep for tuple/list literals of strings in `tests/invariants/`; for each, require either an `# INV-V001-backstop:` comment (declared non-load-bearing) or an `# INV-V001-allow:` comment (explicitly waived with rationale). Anything else fails the test.

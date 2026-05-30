# Phase 4: Promote INV-V001 + Update Planning Docs

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land `INV-V001` formally in [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) with a new `INV-V*` (Verification Methodology) category. Update the planning protocol + test-engineer agent skill so future plans/tests don't propose phrase enumeration.

## Scope Boundaries

- **In scope**:
  - `INVARIANTS.md` — new category + new entry + version bump + Invariant Index update.
  - [docs/plans/CLAUDE.md](../../../CLAUDE.md) — Planning Standards paragraph.
  - [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) — Test Priorities + Anti-Patterns entries.
- **Out of scope**:
  - Re-running Phase 3's discovery test (already green by this phase).
  - Re-auditing (Phase 1 already done).

## Invariants Enforced in This Phase

- **NEW `INV-V001`** Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output — formally promoted here.

---

## Steps

### Step 4.1 — Write the `INV-V001` entry in INVARIANTS.md

Following the existing template (Rule / Why / Requirements / Where it applies / How to verify / Related plans):

```markdown
## INV-V001: Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output

**Rule** *(v1.23, per [eliminate-forbidden-phrase-enumeration](../plans/completed/eliminate-forbidden-phrase-enumeration/) — companion to [inv-a005-structural-faithfulness](../plans/completed/inv-a005-structural-faithfulness/))*: Any test or content gate that verifies properties of agent-generated output (reply text, memory notes, tool-call planning text) MUST use structural inspection (typed envelopes, schema fields, AST), LLM-judge evaluation, or quote-verbatim discipline. Substring-list enumeration of banned or required phrases is forbidden as a load-bearing correctness gate; it may appear ONLY as a non-load-bearing sanity backstop, clearly annotated.

**Why this exists** — LLM paraphrase-space is effectively infinite. Substring enumeration is whack-a-mole — every new paraphrase requires a new entry, and the agent always finds new wording. Demonstrated empirically by the 2026-05-28 AC8 manual gate: a `_FORBIDDEN_PHRASES` tuple shipped 2026-05-28 morning was already worked around by the agent inventing "object-shape serialization error" by afternoon. Enumeration also creates a false sense of coverage — a passing test doesn't mean the agent is faithful, only that this run's phrasing isn't on the list.

**Requirements**:
- Tests under `packages/toolkit/tests/invariants/` and `packages/toolkit/tests/integration/` MUST NOT use module-level string tuples/lists as the primary verification of agent reply content.
- Non-load-bearing substring checks (regression pinning, sanity smoke) MAY exist but MUST carry an inline `# INV-V001-backstop: <rationale>` comment within 3 lines preceding the literal/assertion.
- Structural anti-pattern detection (e.g., regex for argv-shape leaks per `INV-P003`) MAY use enumeration; MUST carry an inline `# INV-V001-allow: <rationale>` comment explicitly noting the structural-vs-paraphrase distinction.
- Agent prompt files MUST NOT include enumerated "do not say X / Y / Z" rule tables. Discipline must be rule-based (quote structural fields verbatim, multi-turn investigation, structural-envelope inspection).
- Plugin tool wrappers MUST return structured envelopes per `INV-A006` (the architectural underpinning of `INV-V001`).
- New plans proposing new verification mechanisms MUST justify their approach as one of the three preferred alternatives (structural / semantic / quote-verbatim), or document an explicit waiver.

**Where it applies**:
- `packages/toolkit/tests/invariants/`
- `packages/toolkit/tests/integration/`
- `packages/*-plugin/tests/`
- `packages/*-plugin/sandbox/*-system-prompt.md`
- `docs/plans/*/spec.md` and `docs/plans/*/development-plan.md` (planning-time)

**How to verify**:
- [packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py](../../packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py) — discovery test walks test/prompt files for string-tuple/list literals + agent-output substring assertions; requires `# INV-V001-{backstop,allow}:` annotation on every site. Fails if any unannotated site is found.

**Related plans**:
- [inv-a005-structural-faithfulness](../plans/completed/inv-a005-structural-faithfulness/) — sister plan; replaces the canonical case (INV-A005 phrase-list) with structural envelopes + LLM-judge.
- [eliminate-forbidden-phrase-enumeration](../plans/completed/eliminate-forbidden-phrase-enumeration/) — promotes this invariant + audits + cleans up the rest of the repo.
```

### Step 4.2 — Add new `INV-V*` category to INVARIANTS.md

The `INV-V*` namespace is new. Add a category section above (or near) `INV-T*` (since both are about discipline rather than runtime behaviour):

```markdown
---

# Category: Verification Methodology (INV-V*)

Rules about HOW the project verifies correctness — what kinds of tests + gates are acceptable. Distinct from runtime invariants (which govern what the code does); these govern how we check what the code does.

[Then INV-V001 entry follows.]

---
```

### Step 4.3 — Update the Invariant Index table

Append:

```markdown
| INV-V001 | Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output | Verification Methodology |
```

Bump top-of-file version: v1.22 → v1.23.

Add dated changelog entry at the top:

```markdown
**v1.23 (YYYY-MM-DD)** — **adds new `INV-V*` category (Verification Methodology) and `INV-V001`** (No Forbidden-Phrase Enumeration for Agent Output). Promoted from the [eliminate-forbidden-phrase-enumeration](../plans/completed/eliminate-forbidden-phrase-enumeration/) plan. Companion to [inv-a005-structural-faithfulness](../plans/completed/inv-a005-structural-faithfulness/) which delivered the canonical pilot case. The rule's discovery test ([test_invV001_no_phrase_enumeration_in_agent_output_gates.py](../../packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py)) requires every agent-output verification gate to declare itself as structural, semantic/LLM-judge, quote-verbatim, or explicitly-annotated-backstop.
```

### Step 4.4 — Update `docs/plans/CLAUDE.md` planning protocol

Add a paragraph under `Planning Standards` (around section G or as a new section):

```markdown
### G. Verification methodology: never enumerate forbidden phrases for agent output

When proposing test gates or content rules over agent-generated output (reply text, memory notes, tool-call planning text), do NOT propose substring-list enumeration of banned or required phrases as the primary verification mechanism. Per `INV-V001`:

- **Structural** — typed envelopes, schema fields, AST inspection (preferred when the property is shape-checkable).
- **Semantic / LLM-judge** — a second model evaluates `(trace, reply)` for consistency (preferred when the property is meaning-bound).
- **Quote-verbatim** — require the agent to quote structured field values verbatim before paraphrasing; the test then checks for the presence of backticked excerpts (preferred when both shape and meaning matter).

Non-load-bearing substring backstops (regression pinning) are allowed but MUST be inline-annotated with `# INV-V001-backstop:` in the test code. See `INV-V001` for the full rule + the discovery test that enforces it.
```

### Step 4.5 — Update `.claude/agents/test-engineer.md`

Under Test Priorities add an entry:

```markdown
### Verification mechanism rule (INV-V001)

Never propose substring-list enumeration of banned/required phrases as the primary verification of agent output. Use structural inspection, LLM-judge, or quote-verbatim discipline. Backstop substring checks must carry an inline `# INV-V001-backstop:` annotation. Structural regex patterns (e.g., argv-leak detection) use `# INV-V001-allow:`. See `INV-V001` for the full rule + discovery test.
```

Under Anti-Patterns add:

```markdown
- **Phrase enumeration as primary verification.** A tuple of forbidden/required phrases checked via substring `in` against agent output. INV-V001 forbids this; the LLM paraphrase-space is infinite and the test becomes whack-a-mole. Use structural / semantic / quote-verbatim verification instead.
```

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) | MODIFY | New `INV-V*` category + `INV-V001` entry + Invariant Index + version bump + changelog. |
| [docs/plans/CLAUDE.md](../../../CLAUDE.md) | MODIFY | New Planning Standards section G. |
| [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) | MODIFY | Test Priorities + Anti-Patterns entries. |

---

## Verification

```bash
# Phase 3 discovery test still passes (the rule's enforcement):
cd packages/toolkit
uv run pytest tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py -xvs

# Sanity-check the INVARIANTS.md edit:
grep -n "INV-V001" docs/reference/INVARIANTS.md  # should show entry + index + changelog
grep -nE "^# Category: Verification Methodology" docs/reference/INVARIANTS.md  # new category present
```

---

## Completion Criteria

- [ ] `INV-V001` entry present in `INVARIANTS.md` with all template sections.
- [ ] New `INV-V*` category section.
- [ ] Invariant Index table updated.
- [ ] Version bump v1.22 → v1.23 + dated changelog entry.
- [ ] Planning protocol's new section G present.
- [ ] Test-engineer skill updated.
- [ ] Phase 3 discovery test continues to pass.
- [ ] `work-notes.md` updated.
- [ ] Phase 4 row in `development-plan.md` progress table set to **Complete**.
- [ ] Plan moved from `docs/plans/active/` to `docs/plans/completed/`.

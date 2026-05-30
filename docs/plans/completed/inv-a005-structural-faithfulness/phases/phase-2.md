# Phase 2: Agent Prompt §INV-A005 Rewrite

**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28
**Parent Plan**: [development-plan.md](../development-plan.md)
**Stage-2 GATE result**: ✅ PASS. Trace at [docs/reports/demo-2026-05-28-logs/stage2-gate-muscle-question.trace.json](../../../../../docs/reports/demo-2026-05-28-logs/stage2-gate-muscle-question.trace.json).

---

## Objective

Remove the §INV-A005 failure-phrase catalogue from the agent system prompt. Replace with a rule-based section that:

1. Teaches the agent to read the structured `error_type` field (introduced in Phase 1) as the source of truth for failure classification.
2. Requires the agent to **quote at least one structured field verbatim** when reporting a tool failure in its reply.
3. Explicitly authorizes (and encourages) the **multi-turn investigation loop**: when an unfamiliar failure shape appears, call additional diagnostic tools instead of guessing.

## Scope Boundaries

- **In scope**:
  - §INV-A005 section of [agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) (lines 156–204 of current).
  - Removal of `_CATALOGUE_ROWS` + parametrized contract test + decompose-rule contract test from [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py).
  - New rule-form contract test (asserts `error_type` mention + multi-turn investigation guidance + quote-verbatim discipline).
- **Out of scope**:
  - Step 3 capability-claim bullet from the parent plan's Phase 1 — stays unchanged (already structural).
  - The §INV-A005 forbidden-narrative *positive rule* at the top of the section (line 156) — kept but rephrased; the agent still must not invent failure narratives, the verification mechanism just changes.
  - Trace-walker test rewrite (Phase 3).
  - Plugin source changes (Phase 1; prerequisite).

## Invariants Enforced in This Phase

- **INV-A005** v1.22 (new structural rule; rule text rewrite lands in Phase 3 alongside the INVARIANTS.md update).
- Indirect: **INV-A002** Step 3 v1.8 bullet 3 — Phase 1 of parent plan stays. New §INV-A005's cross-link to Step 3 bullet 4 updates to reference the structural mechanism (memory note's stale capability claim is superseded if a live tool's `error_type === "..."` contradicts it, not by phrase comparison).

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases** (in [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)):

1. `test_invA005_system_prompt_teaches_structured_error_type_rule` — asserts the §INV-A005 section mentions `error_type` literally + names at least 2 enum values (`placeholder_rejected`, `host_failure`, `network_error`, `http_error`).
2. `test_invA005_system_prompt_teaches_quote_verbatim_discipline` — asserts the section contains language teaching the rule: "quote the structured field value verbatim before paraphrasing" (or equivalent — accept several phrasings via OR).
3. `test_invA005_system_prompt_teaches_multi_turn_investigation` — asserts the section authorizes calling additional diagnostic tools when the failure shape is unfamiliar (look for `multi-turn`, `call additional`, `investigate`, etc.).

Run all three before any prompt edit. Expect:
- Test 1 fails: prompt doesn't currently mention `error_type` (the catalogue uses different vocabulary).
- Test 2 fails: prompt doesn't currently teach quote-verbatim as a positive rule.
- Test 3 fails: prompt doesn't currently authorize multi-turn investigation explicitly.

**Also**: write a deletion-confirmation test (or assertion) that confirms `_CATALOGUE_ROWS` is no longer imported/used. (Can be a comment-anchored grep test or just rely on the import being gone after the rewrite.)

### Step 2.2 — GREEN: Edit the Prompt

Rewrite §INV-A005 (lines 156–204 of current prompt). Target structure:

```markdown
**Tool-failure narratives must match trace evidence (INV-A005)**: only describe a tool call as having failed when this turn's tool-result envelope carries `status: "failed"` with a structured `error_type` field. The plugin returns one of these `error_type` values: `placeholder_rejected`, `host_failure`, `network_error`, `http_error`. (Future tool wrappers may add new enum values; describe them by their `error_type` field, not by paraphrase.)

**Quote at least one structured field verbatim.** When your reply describes a tool failure, quote the actual `error_type` value, the relevant detail field (`arg_name`, `http_path`, `host_status`, `raw_error`, etc.), or the `advisory` text — backtick-quoted, so the operator can correlate your description with the trace. Don't paraphrase the failure category from prior context.

**Per-tool scoping is absolute.** Each tool call has its own `error_type`. Walk each call separately when composing the reply; do not homogenize across calls. Two calls with the same `error_type` may still merit per-tool description if their structured detail fields differ.

**Multi-turn investigation is the right response to unfamiliar failures.** If you see an `error_type` you don't recognize, or a structured field whose value is surprising, **call another tool** — `genomeclaw_status` to check the host service's overall state, retry the failed call, or fetch logs — before composing a final reply. Do NOT guess at the underlying cause from prior context or memory notes.

**Worked example — host service down**: every `genomeclaw_*` call returns `error_type: "network_error"` with `raw_error: "Failed to connect to host.openshell.internal port 8645: Connection refused"`. Reply:
> "Four GenomeClaw calls returned `error_type: network_error` with `raw_error: \"Failed to connect to host.openshell.internal port 8645\"` — the host service was unreachable for this entire turn."

**Worked example — placeholder rejection**: `genomeclaw_pgs_compute` returns `error_type: "placeholder_rejected"` with `arg_name: "rationale"` and `value: "undefined"`. Reply scopes to that one call:
> "The `genomeclaw_pgs_compute` call returned `error_type: placeholder_rejected` for `arg_name: rationale` — I attempted to pass an `undefined` placeholder. Retrying with the actual rationale text."

**Stale capability-claim cross-link (INV-A002 Step 3 bullet 4)**: when memory notes about a tool failure conflict with this turn's `error_type` field, the live `error_type` field wins. If `_pgs_list` returns `error_type: "ok"` (success), a memory note saying "PRS not computable" is superseded — do not cite the note.
```

(Estimated ~30 lines, replacing ~50 current lines.)

### Step 2.3 — REFACTOR

- Re-run the three new tests + the rest of `test_agent_system_prompt_contract.py` → all green.
- Verify no prompt-content gate test now references catalogue phrases. Remove `_CATALOGUE_ROWS` definition + the two parametrized tests it powered.
- Tighten worked-example wording: the `error_type` values must match what Phase 1's TypeScript types defined verbatim.
- Confirm the cross-link to Step 3 bullet 4 is bidirectional (the Step 3 bullet should reference §INV-A005's new mechanism; light edit of the parent plan's Step 3 bullet may be warranted).

---

## Implementation Details

### Worked-Example Pairs

The new §INV-A005 keeps the worked-example pattern from the parent plan's Phase 2 (anti-pattern + target-pattern) but rewrites the examples to reference structured fields instead of phrases. The anti-pattern stays useful (homogenizing distinct failures), but the wrong-version is now phrase-based ("argument-shape guard fired") and the right-version quotes the `error_type` + structured detail field.

### Edge Cases

- **Mixed-outcome turns** — some calls succeed, some fail with different `error_type`. The "per-tool scoping is absolute" rule handles this. Worked example may include this case if the section length allows.
- **An `error_type` the prompt doesn't enumerate** — multi-turn investigation rule covers it. The agent should NOT paraphrase by analogy to known enum values; should call diagnostic tools and report what it observes.

### Privacy / Egress Notes

- None. Prompt edits only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | MODIFY | Rewrite §INV-A005 from catalogue table to rule-based form. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | MODIFY | Remove `_CATALOGUE_ROWS` + the parametrized catalogue test + decompose-rule contract; add 3 new rule-form contract tests. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/invariants/test_agent_system_prompt_contract.py -xvs
uv run ruff check tests/invariants/test_agent_system_prompt_contract.py
```

Visual check: `grep -A 30 "INV-A005" packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` to read the new section.

---

## Completion Criteria

- [ ] Three new rule-form contract tests pass (RED → GREEN visible in commit history).
- [ ] Old `test_invA005_system_prompt_carries_failure_phrase_catalogue` + `test_invA005_system_prompt_carries_decompose_per_tool_rule` are **deleted** (not skipped).
- [ ] `_CATALOGUE_ROWS` definition removed from the test file.
- [ ] `_extract_invA005_section` may stay (used by the new tests) or be deleted if unused. (Decide during refactor.)
- [ ] No `forbidden phrase` / `catalogue` substring remains in the §INV-A005 prompt section.
- [ ] `work-notes.md` updated.
- [ ] Phase 2 row in `development-plan.md` progress table set to **Complete**.

# Phase 1 — Audit Findings: Forbidden-Phrase Enumeration Sites

**Date**: 2026-05-28
**Status**: Complete
**Source**: Initial repo-wide scan conducted by an Explore agent + verified by direct file reads during plan filing.

This document is the inventory referenced by [phases/phase-2.md](phase-2.md) — every site listed here has either an action ("**REPLACE**" by sister plan, "**ANNOTATE-backstop**" by Phase 2, "**ANNOTATE-allow**" by Phase 2) or is **OUT OF SCOPE** with rationale.

---

## Headline numbers

| Category | Count | Where addressed |
|----------|-------|-----------------|
| **Primary load-bearing** | 4 sites | All within sister plan ([inv-a005-structural-faithfulness](../../inv-a005-structural-faithfulness/)) scope. No new primary sites surfaced. |
| **Backstop (non-load-bearing)** | ~22 sites in 1 file | Phase 2 annotates with `# INV-V001-backstop:`. |
| **Structural (different class)** | 1 site | Phase 2 annotates with `# INV-V001-allow:`. |
| **Integration-smoke regression-pin** | ~3 sites | Phase 2 annotates with `# INV-V001-backstop:`. |
| **Future-plan / superseded** | 1 doc | Sister plan has already prepended a supersession header. Move to `completed/` in Stage 6. |

**Total sites requiring Phase 2 action**: ~26.

---

## Primary load-bearing sites (sister plan REPLACES)

### 1. `_FORBIDDEN_PHRASES` + `_STRUCTURAL_FAILURE_SIGNALS` + `_GENOMECLAW_HTTP_ERROR_PATTERN`

**File**: [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py)
**Lines**: 56–69 (`_FORBIDDEN_PHRASES`), 93–112 (`_STRUCTURAL_FAILURE_SIGNALS` + regex), 217+ (trace-walker logic).
**Phase 2 action**: **REPLACE** — sister plan's Phase 3 deletes all three tuples and replaces the walker with structural inspection of the trajectory file's per-tool-call records.

### 2. `_CATALOGUE_ROWS` + parametrized catalogue + decompose-rule contract tests

**File**: [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)
**Lines**: 540–546 (`_CATALOGUE_ROWS`), 549–569 (parametrized catalogue test), `test_invA005_system_prompt_carries_decompose_per_tool_rule`.
**Phase 2 action**: **REPLACE** — sister plan's Phase 2 deletes `_CATALOGUE_ROWS` + both parametrized tests; replaces with three rule-form contract tests (error_type-mention + quote-verbatim + multi-turn-investigation).

### 3. §INV-A005 failure-phrase catalogue (prompt section)

**File**: [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)
**Lines**: 170–204 (5-row catalogue table + decompose rule + 3 worked examples).
**Phase 2 action**: **REPLACE** — sister plan's Phase 2 rewrites the section to rule-form (reads `error_type`, quote-verbatim, multi-turn investigation).

### 4. Prose-string returns in plugin source

**File**: [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts)
**Lines**: 297–333 (`rejectIfPlaceholder`), 220–244 (`wrapHostResponse`), 185–197 (`safeCall` catch), 254–266 (`safePost` catch).
**Phase 2 action**: **REPLACE** — sister plan's Phase 1 changes return shape from prose-string `failedTextResult(reason, ...)` to JSON-encoded `ToolFailureEnvelope` (with `error_type` discriminator + structured detail fields).

These four sites are the architectural and load-bearing root of the methodology. Sister plan's Phases 1–3 eliminate them entirely. **This plan (Phase 2) does not touch them.**

---

## Backstop sites (Phase 2 ANNOTATES with `# INV-V001-backstop:`)

### Prompt-content gates in `test_agent_system_prompt_contract.py`

**File**: [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)

The file carries ~22 `assert "X" in text` style substring checks across many test functions. These check that the prompt **documents required concepts** (e.g., "must teach the memory-validation protocol," "must name PER3 in decline pattern"). They are **non-load-bearing for agent behaviour** — if the prompt rephrases the same concept, the test breaks but the agent could still be correct. They serve as documentation-presence guards.

**Functions to annotate** (each has 2–5 substring assertions; one annotation per function block is sufficient, placed above the first assertion):

- `test_system_prompt_documents_all_five_genomeclaw_tools` (line ~46) — checks each tool name is mentioned.
- `test_invA002_system_prompt_teaches_synthesis_reasoning_floor` (line ~59).
- `test_invA001_system_prompt_documents_memory_note_schema` (line ~79).
- `test_invA001_system_prompt_documents_primary_source_requirement` (line ~100).
- `test_invA001_system_prompt_documents_supersession_mechanism` (line ~117).
- `test_invC001_system_prompt_documents_memory_validation_protocol` (line ~136).
- `test_invA002_step3_memory_validation_special_cases_capability_claims` (line ~171; Phase 1 of parent plan).
- `test_invC001_system_prompt_documents_lifestyle_direct_guidance_rule` (line ~250 — after parent plan edit).
- `test_invP001_system_prompt_documents_web_search_privacy_contract`
- `test_invP001_system_prompt_teaches_native_vs_managed_web_search`
- `test_invP001_system_prompt_documents_web_fetch_disabled_default`
- `test_system_prompt_documents_hard_genes_decline_pattern`
- `test_system_prompt_documents_prs_decline_pattern_with_five_named_reasons`
- `test_system_prompt_teaches_machine_readable_decline_status`
- `test_system_prompt_teaches_cyp2d6_indeterminate_handling`
- `test_system_prompt_documents_research_and_synthesis_steps_in_order` — checks Step 1–7 ordering; structural, not phrase-enumeration. **Note**: actually `INV-V001-allow` candidate (structural). Audit at Phase 2.

**Phase 2 action**: place a single `# INV-V001-backstop: <one-line rationale>` comment above each test function's body, explaining what real correctness gate it backs up. Format:

```python
def test_invA001_system_prompt_documents_memory_note_schema() -> None:
    """..."""
    # INV-V001-backstop: documents that the prompt teaches the INV-A001 schema fields;
    # real correctness gate is `INV-A001`'s behavioural memory-note validation.
    text = _read_prompt()
    ...
```

**Estimated effort**: ~22 single-line comments. ~30 min of careful annotation, deciding on each rationale.

### Integration-smoke regression-pin substring checks

**Files**: various under `packages/toolkit/tests/integration/`.

The audit identified ~3 occurrences of `"X" not in reply` style checks in integration tests (specific lines were not fully enumerated by the Explore audit). These are regression pins ("the 422-fix landed; don't reintroduce that error code") — not agent-behaviour gates.

**Phase 2 action**: grep `packages/toolkit/tests/integration/` for `" in reply\|" not in reply\|" in text\|" not in text`. Annotate each occurrence with `# INV-V001-backstop: regression pin for <bug>` and a 1-line rationale.

**Estimated effort**: ~10 min once Phase 2 starts; precise count surfaces during the grep.

---

## Structural sites (Phase 2 ANNOTATES with `# INV-V001-allow:`)

### `_FORBIDDEN_ARGV_PATTERNS` regex tuple in `test_invP003_*.py`

**File**: [packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py)
**Lines**: 38–57.
**Category**: Structural anti-pattern detection — the regex patterns match **shapes of argv leaks** (python -c with b64decode, bash -c with secret env vars, --key/--secret/--token flags). The check is over the structural form of a shell invocation, not over any LLM-generated content.
**Why `INV-V001-allow`, not -backstop**: this is the canonical correctness gate for `INV-P003` (the only enforcement of it); it's not a backup for something else. It's allowed under `INV-V001` because **the target is structural input shape, not agent paraphrase**.

**Phase 2 action**: prepend `# INV-V001-allow:` annotation:

```python
# INV-V001-allow: regex matches shell-argv anti-patterns for INV-P003 (structural
# detection of secret leaks in argv shape, not enumeration of LLM-generated paraphrases).
# Different class than agent-output forbidden-phrase enumeration — see INV-V001 rule text.
_FORBIDDEN_ARGV_PATTERNS = (
    r"python3?\s+-c\s+.*b64decode",
    ...
)
```

**Estimated effort**: 1 multi-line comment block.

### Possibly: `test_system_prompt_documents_research_and_synthesis_steps_in_order`

**File**: [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)
**Lines**: ~484-501 (parses `### Step N` heading order via regex).
**Category**: Structural — checks heading order, not phrase enumeration. Re-categorize at Phase 2.

---

## Future-plan / superseded

### `agent-replay-harness-for-prompt-regression.md`

**File**: [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../../agent-replay-harness-for-prompt-regression.md)
**Status**: **SUPERSEDED** — header prepended 2026-05-28 pointing at sister plan. The original stub proposed `_FORBIDDEN_PHRASES`-based scenario tests.
**Phase 2 action**: none (header already in place); **Stage 6 close-out** moves to `completed/`.

---

## OUT OF SCOPE — not phrase-enumeration over agent output

Sites that initial pattern scans surfaced but are NOT actually substring enumeration of LLM-generated content. Documented here so future audits don't re-flag them.

1. **TypeBox literal-string unions** in [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) (e.g., `Type.Literal("clinical-actionable") | ...` for the `FindingsCategory` enum at line 341+). These define the **TYPE** of valid agent-supplied arg values — the agent must call the tool with one of these, the TypeBox validator enforces it. Different category: structural API-shape definition, not output paraphrase enumeration. No annotation needed.

2. **Python `Literal[...]` types** in [packages/toolkit/src/genomeclaw_toolkit/](../../../../packages/toolkit/src/genomeclaw_toolkit/) (e.g., `CalibrationStatus = Literal["clean", "warning", "decline"]`). Same category as above — schema/API definition, not paraphrase enumeration.

3. **Test fixtures with hard-coded gene names** (e.g., `("ACTN3", "FTO", "AMPD1")` in fitness-question tests). These define **test inputs**, not assertions over agent output. No annotation needed.

4. **`docs/reference/` prose** that lists "the four enum values are X, Y, Z, W." That's reference documentation, not enforcement.

---

## Recommended Phase 2 work order

1. Annotate `_FORBIDDEN_ARGV_PATTERNS` in `test_invP003_*.py` first (single site, `INV-V001-allow`). Quickest.
2. Annotate the ~22 prompt-content gates in `test_agent_system_prompt_contract.py` (uniform `INV-V001-backstop` pattern; ~30 min).
3. Grep `packages/toolkit/tests/integration/` for the regression-pin sites; annotate each (`INV-V001-backstop` with bug rationale; ~10 min once enumerated).
4. Run the full test suite; confirm no behavioural change (annotations are comments).
5. Re-read this file to confirm every "ANNOTATE" item has been actioned.

After Phase 2: the discovery test (Phase 3) walks the same files + verifies every site has the appropriate annotation.

---

## Open observations from the audit

- The bulk of substring assertions in the repo are in **one file** (`test_agent_system_prompt_contract.py`), and almost all are non-load-bearing prompt-documentation backstops. The discipline is mostly **already** structural at the test-design level — the visible substring count overstates the actual phrase-enumeration risk.
- The **load-bearing** phrase-enumeration is concentrated in the four sister-plan sites. Once those are gone, the meta-rule `INV-V001` is mostly an annotation + discovery-test enforcement layer, not a sweeping rewrite.
- One site (`research_and_synthesis_steps_in_order`) bridges backstop and structural categories. Decide during Phase 2 implementation; default to whichever annotation reads more honestly.

# Phase 1: Step 3 Capability-Claim Amendment

**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Close the freshness-date loophole in Step 3 (Memory validation) that let the agent cite a 2026-05-26 memory note saying "PGS000027 not computable" *thirty minutes after* the sidecar was repaired and `_pgs_list` was returning PGS000018 with a real percentile. The current freshness bullet at [agent-system-prompt.md:183](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L183) asks the wrong question for capability claims ("is the calendar date old?"); this phase adds a fourth bullet that asks the right one ("did this turn's structured trace contradict the note?").

## Scope Boundaries

- **In scope**:
  - Edit Step 3 in [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) to add a 4th validation bullet ("Capability claims") + one worked-example pair.
  - Add a prompt-contract test that asserts the new bullet's text + the three example signals (live `_pgs_list` contradicts memory, live `genomeclaw_status` HTTP 200 contradicts memory, live `genomeclaw_gene` returns variant counts).
- **Out of scope**:
  - Behavioral test that the agent *obeys* the rule under a real LLM call — deferred to Phase 3 (`test_agent_supersedes_stale_capability_memory_when_live_tool_contradicts`).
  - Catalogue of failure phrases — deferred to Phase 2.
  - Auto-write of a superseding memory note when supersession fires — explicitly deferred per Open Question Q2 default.

## Invariants Enforced in This Phase

- **INV-A002** Synthesis Reasoning Floor (v1.8 bullet 3: memory-validation requirement on every `memory:<id>` citation) — the new bullet closes the capability-claim case that the freshness-date framing didn't catch. The prompt-contract test verifies the prompt teaches the rule. The Phase 3 replay test verifies the agent obeys it.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases**:

1. `test_invA002_step3_memory_validation_special_cases_capability_claims` in [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — asserts the Step 3 section of the prompt contains:
   - A bullet (or sub-heading) whose text includes either `"Capability claims"` or `"capability claim"`.
   - Language linking the bullet to the override semantics: must contain `"freshness"` AND (`"irrelevant"` OR `"override"` OR `"bypass"` OR `"superseded"`).
   - The three example signals: `"_pgs_list"`, `"genomeclaw_status"`, AND `"genomeclaw_gene"` all appear within the Step 3 section.
   - An anti-pattern / target-pattern worked-example pair: must contain a snippet labelled as the incorrect citation behavior + a snippet labelled as the correct supersession behavior.

**Sketch**:

```python
def test_invA002_step3_memory_validation_special_cases_capability_claims():
    """INV-A002 v1.8 bullet 3: Step 3 must special-case tool-capability claims so a
    stale 'X is unavailable' note is superseded by a live tool result in the same turn,
    overriding the calendar-freshness rule.
    """
    prompt = _load_agent_system_prompt()
    step3 = _extract_section(prompt, heading="Step 3 — Memory validation")
    text = step3.lower()

    assert "capability claim" in text or "capability claims" in text, (
        "Step 3 must carry a dedicated capability-claim validation bullet."
    )
    assert "freshness" in text and any(
        marker in text for marker in ("irrelevant", "override", "bypass", "superseded")
    ), (
        "The capability-claim bullet must explicitly override the freshness-date rule."
    )
    for signal in ("_pgs_list", "genomeclaw_status", "genomeclaw_gene"):
        assert signal in step3, (
            f"Step 3 capability-claim bullet must name {signal} as an example contradiction signal."
        )
    assert "supersede" in text or "superseded" in text, (
        "Step 3 must teach the 'supersede the stale note' resolution."
    )
```

Run the test before editing the prompt and confirm it fails for the right reason ("Step 3 capability-claim bullet missing"). Paste output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

Edit [agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) Step 3 (anchor near line 177). After the existing freshness bullet (line 183), insert:

```markdown
4. **Capability claims** — does the note describe a tool failure, a missing data path,
   or "X is currently unavailable"? If yes, **the freshness date is irrelevant**:
   a fix could have landed an hour ago. Re-test the underlying capability in *this*
   turn before citing the note.

   Supersede the stale note when **any** of these signals fires in this turn:
   - `_pgs_list` returns a PRS the note said was missing or not computable
   - `genomeclaw_status` returns HTTP 200 when the note said the service was down
   - `genomeclaw_gene` returns variant counts the note said couldn't be retrieved

   When superseded, **do NOT cite the stale capability claim** as ongoing. Cite the
   live result instead.

   *Anti-pattern* (do NOT do this):
   > "Memory note from 2026-05-26 says PGS000027 is not computable because of a
   > `prs_compute_config_missing` failure, so I cannot report a percentile."

   *Target pattern* (do this when `_pgs_list` returns PGS000018 with a percentile
   in the same turn):
   > "Live `_pgs_list` returned PGS000018 at percentile 14.54 (`memory:<id>`'s
   > earlier capability-failure note from 2026-05-26 is superseded by this turn's
   > result)."
```

### Step 1.3 — REFACTOR

- Re-run the contract test → green.
- Re-run the full `tests/invariants/` suite → confirm no existing assertion regressed.
- Tighten any wording in the new bullet that overlaps with §INV-A005 vocabulary (e.g., avoid implying a tool *failure* when the capability claim is actually about a *missing data path*).
- Leave `INV-A005` alone for this phase; the catalogue extension is Phase 2.

---

## Implementation Details

### Edge Cases to Handle

- **Memory note describes a *data* claim, not a *capability* claim**: e.g., "this user's APOE genotype is ε3/ε3." The new bullet should NOT apply — that's a finding, not a capability. The bullet text must explicitly scope itself to "tool failure / missing data path / X is unavailable" claims.
- **Live tool returns an *empty* but valid response**: e.g., `_pgs_list` returns `[]`. This should NOT trigger supersession of a "PRS X not computable" note — empty is consistent with the note, not contradictory. The bullet language uses "returns the PRS the note said was missing," not "returns successfully."
- **Memory note and live tool agree on the failure**: e.g., note says "service unavailable," `genomeclaw_status` returns connection-refused. No supersession; the note is corroborated. The bullet does not require supersession when signals *agree*.

### Error Handling

- If the prompt regex doesn't find a "Step 3" heading, the contract test fails with a clear message (`"Step 3 — Memory validation" section not found in prompt`). This catches accidental section renames.

### Privacy / Egress Notes

- None. Prompt edits only. No tool surface, no egress.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | MODIFY | Add 4th validation bullet under Step 3 + anti-pattern / target-pattern worked example. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | MODIFY | Add `test_invA002_step3_memory_validation_special_cases_capability_claims`. |

---

## Verification

```bash
# Run this phase's new test
cd packages/toolkit
uv run pytest tests/invariants/test_agent_system_prompt_contract.py::test_invA002_step3_memory_validation_special_cases_capability_claims -xvs

# Run all prompt-contract tests to confirm no regression
uv run pytest tests/invariants/test_agent_system_prompt_contract.py -xvs

# Run the full invariants suite
uv run pytest tests/invariants/ -x

# Static checks (mirror existing toolkit conventions)
uv run ruff check src tests
uv run mypy src
```

For the prompt itself, manually verify the rendered section is well-formed:

```bash
# Sanity-grep the new bullet exists in the prompt
grep -n "Capability claims" packages/nemoclaw-plugin/sandbox/agent-system-prompt.md
```

---

## Completion Criteria

- [x] `test_invA002_step3_memory_validation_special_cases_capability_claims` passes.
- [x] All previously-passing tests in `tests/invariants/test_agent_system_prompt_contract.py` still pass (14/14).
- [x] Static checks pass (`ruff check` clean).
- [x] Test name + docstring cite `INV-A002`.
- [x] No raw genomic data, secrets, or sample IDs added to fixtures or repo.
- [x] `work-notes.md` updated with RED output, decisions, and final state.
- [x] Phase 1 row in `development-plan.md` progress table set to **Complete** with date.

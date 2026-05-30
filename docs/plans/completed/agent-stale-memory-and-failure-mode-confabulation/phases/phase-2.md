# Phase 2: §INV-A005 Catalogue Extension

**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Replace the single-forbidden-phrase rule in §INV-A005 ("argument-serialization bug" requires `rejectIfPlaceholder` prose) with a **catalogue** of 5 phrase ↔ structural-signal pairs that covers every failure shape the plugin can return today, plus an explicit "decompose per-tool" rule so the agent reports each tool's failure mode separately instead of homogenizing them (Bug 2).

## Scope Boundaries

- **In scope**:
  - §INV-A005 section in [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) (lines 156–175).
  - Catalogue table with 5 rows + "decompose per-tool" rule + over-trusted-memory anti-pattern worked example.
  - Prompt-contract test assertions for each catalogue row.
  - Trace-walker extension: `_FORBIDDEN_PHRASES` grows; `_trace_has_real_failure` gains a network-failure predicate.
- **Out of scope**:
  - Behavioral tests that the agent obeys the catalogue under each scenario — deferred to Phase 3.
  - External fixture file at `packages/nemoclaw-plugin/sandbox/failure-phrases.md` — deferred per Open Question Q3 default.
  - Changes to the plugin's failure-shape prose itself — those texts (`rejectIfPlaceholder`, `wrapHostResponse`, `safeCall` catch-blocks) are stable; the catalogue *describes* them, it doesn't change them.

## Invariants Enforced in This Phase

- **INV-A005** Tool-Failure Narratives Match Trace Evidence (v1.21) — the catalogue + decompose rule extend the surface enforcing this invariant. The prompt-contract test asserts the catalogue rows are present in the prompt; the trace-walker test asserts no trace under `docs/reports/` violates the extended forbidden-phrase list.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases**:

1. `test_invA005_system_prompt_carries_failure_phrase_catalogue` in [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — asserts each catalogue row's phrase + its required structural-signal text appears in the prompt:
   - Row 1 (`rejectIfPlaceholder`): `"argument-shape guard"` AND `"placeholder string"` both present.
   - Row 2 (`wrapHostResponse`): `"host returned status=failed"` AND `"host-side structured failure"` both present.
   - Row 3 (network): `"connection refused"` AND `"Failed to connect"` both present.
   - Row 4 (TypeBox): `"TypeBox"` AND `"Expected"` both present.
   - Row 5 (valid-but-empty): `"n_variants_in_gene"` AND `"region_class"` both present (the existing assertion still holds; the catalogue absorbs it).
2. `test_invA005_system_prompt_carries_decompose_per_tool_rule` in [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — asserts the §INV-A005 section contains:
   - The literal substring `"decompose"` OR `"separately"` AND `"per-tool"` OR `"per tool"`.
   - Language warning against homogenization: `"homogeniz"` OR `"single guess"` OR `"all my GenomeClaw calls failed"`.
3. `test_invA005_trace_walker_catches_argument_shape_guard_without_signal` in [test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — synthetic trace fixture: reply text contains `"argument-shape guard fired"`, payloads contain only HTTP-200 bodies. Test asserts the trace-walker flags this as a forbidden-phrase violation.
4. `test_invA005_trace_walker_accepts_network_failure_phrasing_when_signal_present` — synthetic trace fixture: reply text contains `"HTTP connection refused"`, payloads contain `"Failed to connect to host.openshell.internal port 8645"`. Test asserts the trace-walker does NOT flag this (the signal corroborates the phrase).

**Sketch for the catalogue contract test**:

```python
CATALOGUE_ROWS = (
    # (phrase, structural-signal substring)
    ("argument-shape guard", "placeholder string"),
    ("host returned status=failed", "host-side structured failure"),
    ("connection refused", "Failed to connect"),
    ("TypeBox", "Expected"),
    ("n_variants_in_gene", "region_class"),
)


def test_invA005_system_prompt_carries_failure_phrase_catalogue():
    """INV-A005: every failure phrase the agent might reach for must be paired with
    the literal tool-result text shape that licenses it. The catalogue lives in the
    §INV-A005 section of the agent system prompt; this test asserts each row is present.
    """
    prompt = _load_agent_system_prompt()
    section = _extract_section(prompt, heading_marker="INV-A005")

    for phrase, signal in CATALOGUE_ROWS:
        assert phrase in section, f"Catalogue is missing phrase: {phrase}"
        assert signal in section, f"Catalogue is missing structural-signal text: {signal}"
```

**Sketch for the trace-walker extension**:

```python
# In test_invA005_no_serialization_bug_confabulation.py

_FORBIDDEN_PHRASES = (
    "argument-serialization bug",
    "serialization bug",
    "q-001 fired",
    "args serializer dropped",
    "args serializer lost",
    # NEW catalogue entries (Phase 2):
    "argument-shape guard fired",
    "rejectifplaceholder rejected",
    "typebox rejected the parameters",
)

_NETWORK_FAILURE_SIGNAL_SUBSTRINGS = (
    "Failed to connect",
    "fetch failed",
    "connection refused",
    "-> HTTP 5",
)


def _trace_has_network_failure_signal(trace: Mapping[str, Any]) -> bool:
    """Return True iff any payload's text contains a documented network-failure marker."""
    payloads = _trace_payload_texts(trace)
    return any(
        signal in text
        for text in payloads
        for signal in _NETWORK_FAILURE_SIGNAL_SUBSTRINGS
    )
```

Run all four tests before editing the prompt. Confirm:
- Tests 1 + 2 fail with "catalogue row missing" / "decompose rule missing."
- Tests 3 + 4 require new fixture files (`tests/invariants/fixtures/trace_argument_shape_guard_no_signal.trace.json` and `trace_network_failure_with_signal.trace.json`) — create those at the same time, minimal synthetic JSON.

Paste output into `work-notes.md`.

### Step 2.2 — GREEN: Minimal Implementation

**Prompt edit** at [agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) §INV-A005 (around line 172). Replace the single "argument-serialization bug" sentence with the catalogue + decompose rule:

```markdown
**Failure-phrase catalogue.** Every failure phrase you use in a reply must trace
back to a specific shape in this turn's tool-result text. Use the phrase only when
its required structural signal appears in this turn's output.

| Phrase you might use | Required structural signal in this turn's tool-result text |
|----------------------|-----------------------------------------------------------|
| "argument-shape guard fired" / "rejectIfPlaceholder rejected" / "argument-serialization bug" | The literal `rejectIfPlaceholder` prose: `argument 'X' is the placeholder string "..." — this usually means the agent's tool-call argument resolution lost track of the real value upstream` |
| "host returned status=failed" / "host-side structured failure" | The `wrapHostResponse` prose: `host returned status=failed for /v1/<path>: <code>. This is a host-side structured failure (not an HTTP error, not a plugin guard rejection)` |
| "HTTP connection refused" / "network unreachable" / "GenomeClaw wasn't reachable" | A `safeCall` / `safePost` catch-block message: `Failed to connect to ...`, `fetch failed`, or `genomeclaw-service <path> -> HTTP 5xx`. **Not interchangeable with "argument-shape guard fired."** |
| "TypeBox rejected the parameters" | A TypeBox validator error in tool-result text: `Expected <type>, received <type>` |
| "tool returned empty / null data" | `n_variants_in_gene: 0` OR `region_class: null` in a body that otherwise returned HTTP 200. **This is not a failure** — describe it as a valid empty response. |

**Decompose per-tool.** If multiple tool calls fail in the same turn, report each
one's failure mode separately based on its specific tool-result text. Do NOT
homogenize "all my GenomeClaw calls failed" into a single guess at the cause.
A network-unreachable turn and a guard-rejection turn look different in the tool
trace; describe them separately, even when every call in the turn fails.

*Anti-pattern* (do NOT do this — homogenizing distinct failures):
> "`status`, findings, and PRS list returned fetch failures, and gene/PRS calls
> hit the argument-shape guard."
>
> (Wrong because: the trace shows the same `Failed to connect` for *every* call.
> There is no `rejectIfPlaceholder` prose anywhere in this turn.)

*Target pattern* (decomposed per-tool):
> "All four tool calls returned `Failed to connect to host.openshell.internal port
> 8645` — the host service was unreachable for this entire turn. No argument-shape
> guard fired; this is a network failure, not a guard rejection."
```

**Test extensions**:

- Extend `_FORBIDDEN_PHRASES` in [test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) with the three new entries.
- Add `_trace_has_network_failure_signal` helper.
- Add the two synthetic-trace fixture files under `packages/toolkit/tests/invariants/fixtures/` (tiny JSON, no real genome data).
- In [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py), add the two new contract tests parametrized over `CATALOGUE_ROWS`.

### Step 2.3 — REFACTOR

- Re-run all four new tests + the full `tests/invariants/` suite → green.
- Re-run the trace-walker against the existing `docs/reports/*.trace.json` corpus → confirm no historical trace newly trips the extended `_FORBIDDEN_PHRASES` (if one does, that's a real `INV-A005` violation to investigate; do not relax the rule).
- Tighten the catalogue table wording: signals should quote the plugin's actual prose verbatim where stable; deduplicate any phrase already named in the Step 3 capability-claim bullet.
- Confirm the `region_class` + `n_variants_in_gene` worked-example pair from the 2026-05-26 strengthening is still present (it's now absorbed into Row 5 of the catalogue).

---

## Implementation Details

### Catalogue Wording — Source of Truth

Each row's *required structural signal* must quote the plugin's actual failure prose. Verbatim sources:

- Row 1 (`rejectIfPlaceholder`, [index.ts:297–333](../../../../../packages/nemoclaw-plugin/src/index.ts#L297)): `argument '<argName>' is the placeholder string "<value>" — this usually means the agent's tool-call argument resolution lost track of the real value upstream. Re-emit the tool call with the actual <argName>.`
- Row 2 (`wrapHostResponse`, [index.ts:220–244](../../../../../packages/nemoclaw-plugin/src/index.ts#L220)): `host returned status=failed for <path>: <errMsg>. This is a host-side structured failure (not an HTTP error, not a plugin guard rejection). Surface the error code to the user and do NOT generalize this rejection to other tool calls in the same turn.`
- Row 3 (`safeCall` / `safePost` catch, [index.ts:185–197, 254–266](../../../../../packages/nemoclaw-plugin/src/index.ts#L185)): the catch wraps the raw Error message, including `Failed to connect to ...`, `fetch failed`, and `genomeclaw-service <path> -> HTTP <status>` (from `callHostService` [line 171](../../../../../packages/nemoclaw-plugin/src/index.ts#L171)).
- Row 4 (TypeBox): TypeBox validator errors are emitted by the plugin's argument validators; canonical form is `Expected <type>, received <type>`. Source-grounded against the TypeBox library convention; verify by reading existing TypeBox usage in [index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts).
- Row 5 (valid-but-empty): the existing `region_class: null` (off-curated-panel) and `n_variants_in_gene: 0` (in-panel, no called variants) cases from the 2026-05-26 strengthening.

### Edge Cases to Handle

- **Two distinct failure modes in one turn**: e.g., `_pgs_compute` returns `rejectIfPlaceholder` prose AND `genomeclaw_status` returns HTTP 500. The decompose rule means the agent reports each separately, using the matching catalogue phrase for each.
- **Failure with no catalogue match**: e.g., the plugin grows a new failure shape we haven't catalogued yet. The agent should describe the actual tool-result text verbatim and flag the unfamiliar shape, not reach for the closest catalogue phrase. Add a fallback bullet to the §INV-A005 section: "*if the failure prose doesn't match any catalogue row, quote it verbatim and call it 'an unfamiliar failure shape' — do not paraphrase to fit the catalogue.*"
- **Existing `docs/reports/*.trace.json` corpus tripping new phrases**: if any historical trace contains "argument-shape guard fired" or "TypeBox rejected" without the matching signal, that's a real INV-A005 violation. Investigate before relaxing the rule. The 2026-05-26 cutoff date in `test_invA005_no_serialization_bug_confabulation.py` (line ~135) already excludes pre-fix traces; the new phrases get the same cutoff treatment.

### Error Handling

- Synthetic fixture JSON files use the minimal trace envelope shape: `{"meta": {"toolSummary": {...}}, "payloads": [{"text": "..."}]}`. Match the existing fixture format used by the trace-walker.
- If a fixture is malformed, the test fails with the existing trace-walker's parse-error path; no new error handling needed.

### Privacy / Egress Notes

- None. Prompt + test edits only. Fixture JSON files contain only synthetic strings.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | MODIFY | Replace single forbidden-phrase rule with catalogue table + decompose rule + anti-pattern / target-pattern worked example. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | MODIFY | Add `test_invA005_system_prompt_carries_failure_phrase_catalogue` (parametrized over `CATALOGUE_ROWS`) + `test_invA005_system_prompt_carries_decompose_per_tool_rule`. |
| [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | MODIFY | Extend `_FORBIDDEN_PHRASES` (+6 phrases); add `_STRUCTURAL_FAILURE_SIGNALS` + `_GENOMECLAW_HTTP_ERROR_PATTERN`; rewrite `_trace_has_real_failure` to walk both; add `_trace_walker_flags` helper + 2 new synthetic-trace tests inline (no file fixtures). |

**Deviation from initial plan**: Phase-2 originally planned two JSON fixture files (`trace_argument_shape_guard_no_signal.trace.json` + `trace_network_failure_with_signal.trace.json`). Instead, used **inline synthetic trace dicts** inside the new tests. Rationale: the existing parametrized trace-walker iterates `docs/reports/*.trace.json`; adding fixture JSON files anywhere on that tree would either pollute the production trace corpus or require excluding them via path filtering — added complexity for no gain. Inline dicts are smaller, self-documenting, and live next to the test that uses them.

---

## Verification

```bash
cd packages/toolkit

# Run this phase's new tests
uv run pytest tests/invariants/test_agent_system_prompt_contract.py::test_invA005_system_prompt_carries_failure_phrase_catalogue -xvs
uv run pytest tests/invariants/test_agent_system_prompt_contract.py::test_invA005_system_prompt_carries_decompose_per_tool_rule -xvs
uv run pytest tests/invariants/test_invA005_no_serialization_bug_confabulation.py::test_invA005_trace_walker_catches_argument_shape_guard_without_signal -xvs
uv run pytest tests/invariants/test_invA005_no_serialization_bug_confabulation.py::test_invA005_trace_walker_accepts_network_failure_phrasing_when_signal_present -xvs

# Re-run the trace-walker against the full docs/reports corpus
uv run pytest tests/invariants/test_invA005_no_serialization_bug_confabulation.py -xvs

# Confirm the existing INV-A005 contract test still passes (it absorbs into Row 5)
uv run pytest tests/invariants/test_agent_system_prompt_contract.py::test_invA005_system_prompt_forbids_confabulated_serialization_bug_narrative -xvs

# Full invariant suite
uv run pytest tests/invariants/ -x

# Static checks
uv run ruff check src tests
uv run mypy src
```

---

## Completion Criteria

- [x] All four new tests pass (RED → GREEN visible in commit history).
- [x] Existing `test_invA005_system_prompt_forbids_confabulated_serialization_bug_narrative` still passes.
- [x] Trace-walker re-runs cleanly against `docs/reports/*.trace.json` with extended `_FORBIDDEN_PHRASES` (14 skips, all dated pre-2026-05-26 binding date — expected).
- [x] Catalogue table present in prompt with all 5 rows.
- [x] Decompose-per-tool rule present in prompt.
- [x] Anti-pattern + target-pattern worked example present (plus a third: stale-memory anti-pattern cross-linking to Step 3 bullet 4).
- [x] Each new test cites `INV-A005` in name or docstring.
- [x] No fixture JSON files added — used inline synthetic trace dicts instead (decision logged in work-notes); no risk of polluting `docs/reports/` corpus.
- [x] Static checks pass (`ruff check` clean on the two touched files).
- [x] `work-notes.md` updated.
- [x] Phase 2 row in `development-plan.md` progress table set to **Complete** with date.

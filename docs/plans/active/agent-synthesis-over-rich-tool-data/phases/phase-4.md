# Phase 4: Prompt §INV-A005 Rewrite — Drop Verbatim-Quoting, Add Analyze-and-Present

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Rewrite the agent system prompt's §INV-A005 section to **drop the verbatim-quoting requirement** (the v1.22 mistake) and **add an analyze-and-present discipline**: the agent reasons over rich structured data and presents findings to the user in clear, natural language. Structured fields (`error_type`, `diagnostic_trace.stage`, etc.) are for the agent's reasoning, not for verbatim insertion into the reply.

## Scope Boundaries

- **In scope**:
  - §INV-A005 section of [agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md).
  - Three prompt-contract tests in [test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py):
    - **DELETE** `test_invA005_v122_system_prompt_teaches_quote_verbatim_discipline`.
    - **ADD** `test_invA005_v123_system_prompt_teaches_analyze_and_present_discipline` (positive).
    - **ADD** `test_invA005_v123_system_prompt_does_not_mandate_verbatim_quoting` (negative).
    - **KEEP** `test_invA005_v122_system_prompt_teaches_structured_error_type_rule` — rename to `..._v123_...`; the agent still reads `error_type` for reasoning (just doesn't quote it). Update wording from "mention literally" to "name as a known enum value the agent recognizes."
    - **KEEP** `test_invA005_v122_system_prompt_teaches_multi_turn_investigation` — rename to `..._v123_...`; rule unchanged.
- **Out of scope**:
  - The structural walker deletion (Phase 5).
  - LLM-judge harness (Phase 5).
  - Plugin-side changes (Phases 1–3).

## Invariants Enforced in This Phase

- **INV-A005** v1.23 (the mechanism this phase corrects). Rule rewrite lands in Phase 5's INVARIANTS.md update.
- **INV-V001** — honored. The new test teaches positive synthesis discipline; no phrase enumeration.
- **INV-A002** Step 3 capability-claim bullet — unchanged. Cross-link in §INV-A005 is preserved.

---

## TDD Steps

### Step 4.1 — RED: Write Failing Tests

**Test cases**:

1. `test_invA005_v123_system_prompt_teaches_analyze_and_present_discipline` — asserts the §INV-A005 section contains at least 2 of these positive markers: `"analyze"`, `"present"`, `"interpret"`, `"understandable"`, `"plain language"`, `"natural language"`, `"synthesize"`, `"summarize"`. AND mentions that structured fields are for the agent's reasoning, not for verbatim insertion (look for: `"reasoning"` AND any of `"not for quoting"` / `"do not quote"` / `"not insert"` / `"not transcribe"` / `"not repeat verbatim"`).

2. `test_invA005_v123_system_prompt_does_not_mandate_verbatim_quoting` — asserts the §INV-A005 section does NOT contain the v1.22 verbatim-quoting language. Look for absence of: `"backtick-quoted excerpt"`, `"quote verbatim"`, `"MUST contain at least one backtick"`, etc. This is the negative gate — ensures we didn't leave the mistake in place.

3. `test_invA005_v123_system_prompt_teaches_structured_error_type_rule` (renamed from v1.22) — assert §INV-A005 mentions `error_type` literally + names at least 2 of the four enum values. (Still useful for agent reasoning; just no longer about reply transcription.)

4. `test_invA005_v123_system_prompt_teaches_multi_turn_investigation` (renamed from v1.22) — unchanged content; verify multi-turn investigation rule is still present.

Run RED. Expect:
- (1) fails: prompt teaches verbatim quoting, not analyze-and-present.
- (2) fails: prompt currently mandates verbatim quoting.
- (3) passes (the v1.22 test is similar; rename only).
- (4) passes (rule unchanged).

### Step 4.2 — GREEN: Rewrite §INV-A005 Prompt Section

Edit [agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) §INV-A005 (currently lines ~170–204 of the v1.22 version):

```markdown
**Tool-failure narratives must match trace evidence (INV-A005 v1.23)**: every tool you call returns rich structured data. For failures, the plugin returns a `ToolFailureEnvelope` JSON with a `status: "failed"` field, an `error_type` discriminator (one of `placeholder_rejected`, `host_failure`, `network_error`, `http_error`), structured detail fields appropriate to the failure (e.g., `diagnostic_trace.stage`, `host_error`, `http_status`), and an operator-readable `advisory`. For successes, the plugin returns the host's full response payload — query results, analysis output, computation metadata, ancestry context, etc.

**Your job: ANALYZE this rich data and PRESENT your findings to the user in clear, natural language.** The structured fields exist for YOUR reasoning — they are NOT for verbatim insertion into your reply. The user is not reading JSON; they're reading the synthesis you produce.

Concrete rules:

- **Read the structured data as a reasoning aid.** `error_type` tells you what class of failure happened. `diagnostic_trace.stage` tells you where in the pipeline it failed. `host_error` is a machine-readable code. Use this to construct your understanding.
- **Present findings in plain language.** Translate, don't transcribe. "I couldn't reach the GenomeClaw host service this turn — the call timed out at the network layer, before the analysis pipeline started" is good. "`error_type: network_error` with `raw_error: fetch failed`" is robotic transcription, NOT what the user needs.
- **Be specific about WHAT happened and what the user can do about it.** Map the structured cause to actionable framing. If a PRS compute hit `host_failure` at the `scorefile_staging` stage, the user-facing summary is: "I couldn't compute the PRS because the scorefile wasn't pre-staged — running `genomeclaw refs fetch <PGS-ID>` first will fix it."
- **Decompose per-tool when multiple calls fail with different causes.** Each tool call has its own envelope. Walk each one separately; don't homogenize. Two `network_error`s may share a root cause; a `network_error` + a `host_failure` describe different events that warrant different framing.
- **Investigate multi-turn under unfamiliar shapes.** If you see an `error_type` you don't recognize, or a `diagnostic_trace` field with a surprising value, call additional diagnostic tools (`genomeclaw_status`, retry, inspect logs) before composing your final reply. Do NOT guess from prior context or memory notes.

*Good reply — host service unreachable (all calls fail with `error_type: network_error`):*

> "I couldn't reach the GenomeClaw host service this turn, so I don't have your live genomic data to work from. From general guidelines: for muscle-building you'll want progressive overload, 3–5 lifting sessions per week, and protein at 1.4–2.0 g/kg/day; specific gene-informed personalization (ACTN3/ACE for power vs endurance, FTO/MC4R for appetite, CYP1A2/ADORA2A for caffeine) is what I'd add once GenomeClaw is reachable again."

*Bad reply (v1.22-style robotic transcription) — don't do this:*

> "`genomeclaw_status`, `genomeclaw_findings`, and `genomeclaw_pgs_list` all returned `error_type: network_error` with `raw_error: fetch failed`. The gene-panel calls returned `error_type: placeholder_rejected`; the tool reported it received a call-id string instead of a JSON object."

*Bad reply — homogenization, confabulated cause:*

> "All GenomeClaw calls failed — the argument-shape guard fired across all of them."

(False: the trace shows network_error, not placeholder_rejected. Same problem the v1.22 catalogue tried to fix at a phrase level. The fix is structural: read the actual `error_type` for each call.)

**Stale capability-claim cross-link (INV-A002 Step 3 bullet 4)**: when memory notes about a tool failure conflict with this turn's actual trace, the live trace wins. If a memory note says "PRS not computable" but `_pgs_list` returned a valid percentile in this turn, the memory note is superseded — do not cite it.
```

(Length similar to v1.22; replacement keeps cross-links + multi-turn rule + per-tool decomposition.)

### Step 4.3 — REFACTOR

- Re-run the four contract tests + the broader prompt-contract suite → green.
- Visual read-through of the §INV-A005 section in context — does it flow with surrounding sections?
- Confirm the cross-link to Step 3 bullet 4 still points at the right rule.
- Tighten worked-example wording — keep examples concrete + grounded in real tool names.

---

## Implementation Details

### Why Keep `error_type` Discriminator Awareness?

The agent benefits from typed reasoning even without verbatim quoting. Knowing the failure CLASS (`network_error` vs `placeholder_rejected`) lets the agent reason correctly about what to do next:

- `network_error` → maybe retry, check host status, fall back to general advice.
- `placeholder_rejected` → re-emit the call with the actual argument.
- `host_failure` → surface the structured cause + user-actionable next step.
- `http_error` → likely transient or a host-service bug; report + don't generalize.

The prompt still teaches these classes. It just doesn't make the agent insert `error_type: <value>` into the reply text.

### Worked Example Quality

The two worked examples (good / bad) are load-bearing — they're what the model uses as soft reference. Iterate during Phase 4 implementation if the AC8 reply still leans toward transcription:

- Pull the v1.22 captured trace ([stage2-gate-muscle-question.trace.json](../../../../../docs/reports/demo-2026-05-28-logs/stage2-gate-muscle-question.trace.json)) and use it as the explicit "bad" example.
- Hand-write the "good" reply for the same scenario, anchoring it in the v1.23 rewrite.
- Tune until the worked examples cover the failure modes Phase 6's AC8 gate will exercise.

### Edge Cases

- **Single-call failure** — straightforward; quote the relevant cause in plain language.
- **Mixed-outcome turn** — per-tool decomposition rule handles it.
- **All calls succeed** — no failure narrative to construct; agent presents the genomic interpretation directly.
- **Memory-note conflicts with live data** — Step 3 bullet 4 takes priority (already taught).

### Privacy / Egress Notes

- None. Prompt edits only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) §INV-A005 | MODIFY | Rewrite from verbatim-quoting to analyze-and-present. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | MODIFY | Delete v1.22 quote-verbatim test; add v1.23 analyze-and-present test + negative-verbatim test; rename the other two v1.22 tests to v1.23. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/invariants/test_agent_system_prompt_contract.py -xvs
uv run ruff check tests/invariants/test_agent_system_prompt_contract.py
```

Visual check:

```bash
grep -nA 40 "INV-A005 v1.23" packages/nemoclaw-plugin/sandbox/agent-system-prompt.md
```

---

## Completion Criteria

- [ ] §INV-A005 section rewritten end-to-end.
- [ ] Worked-example pair (good / bad) included.
- [ ] `test_invA005_v123_system_prompt_teaches_analyze_and_present_discipline` passes.
- [ ] `test_invA005_v123_system_prompt_does_not_mandate_verbatim_quoting` passes.
- [ ] `test_invA005_v122_*_teaches_quote_verbatim_discipline` is DELETED.
- [ ] Two other v1.22 tests renamed to v1.23 + still pass (`teaches_structured_error_type_rule`, `teaches_multi_turn_investigation`).
- [ ] Existing prompt-content backstop tests still pass.
- [ ] Lint clean.
- [ ] `work-notes.md` updated.
- [ ] Phase 4 row in `development-plan.md` progress table set to **Complete**.

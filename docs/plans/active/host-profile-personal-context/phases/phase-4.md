# Phase 4: Agent System Prompt + Behavioural Enforcement

**Status**: Complete — offline gates + privacy review + **live gates** all green (sandbox rebuilt; live_llm gap-framing PASSED; trace-walk engaged on a real post-prompt trace)
**Started**: 2026-05-31
**Completed**: 2026-05-31
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Update the agent system prompt so `genomeclaw_host_profile` retrieval becomes mandatory before any genome-informable reply, teach the profile-gap framing pattern, and land the prompt-content + behavioural gates that enforce INV-C004. The invariant itself is promoted to `INVARIANTS.md` only after these tests are stable (Phase 5).

This phase carries the highest agent-cognition risk in the plan. The privacy-safety-reviewer agent gets a blocking pass on the prompt diff.

## Scope Boundaries

- **In scope**:
  - `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` updates to § 1, § 4, § 6, § 7, § 8, § 9, § 10.
  - Prompt-content gates in `tests/invariants/test_agent_system_prompt_contract.py`.
  - Trace-walk gate (`test_invC004_trace_walk_host_profile_called.py`) — initially RED for pre-prompt traces; goes GREEN after the canonical demo battery is re-run.
  - One `live_llm` behavioural test exercising the profile-gap framing pattern.
- **Out of scope**:
  - Promotion of INV-C004 to `INVARIANTS.md` — Phase 5.
  - Documentation updates beyond the prompt — Phase 5.

## Invariants Enforced in This Phase

- **NEW INV-C004**: tests RED before prompt change, GREEN after. The tests get **promoted** to a real invariant in Phase 5 once they've been stable through at least one demo-battery re-run.
- **INV-A005** Tool-Failure Narratives Match Trace Evidence — prompt teaches that `200 + missing: true` is a structured signal, NOT a tool failure.
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — prompt § 7 adds the new `host_profile:<section>#<field>` citation form.
- **INV-A001** Agent Memory Provenance — prompt § 5 reminder: profile-grounded memory notes record the tool-call + section keys, never verbatim freetext.

---

## TDD Steps

### Step 4.1 — RED: Write Failing Tests

**Test cases**:

Prompt-content gates (`tests/invariants/test_agent_system_prompt_contract.py` — extend existing):

1. `test_invC004_system_prompt_lists_host_profile_tool_in_section_1` — § 1's GenomeClaw tool table includes `genomeclaw_host_profile` with a one-line purpose summary.
2. `test_invC004_system_prompt_section_4_includes_step_1_5_host_profile_context` — § 4 contains a heading `### Step 1.5 — Host profile context` between Step 1 and Step 2.
3. `test_invC004_system_prompt_step_1_5_marks_call_mandatory_for_genome_informable_turns` — the Step 1.5 paragraph contains the literal binding language `"MUST"` and names `genome-informable` turn explicitly.
4. `test_invC004_system_prompt_teaches_profile_gap_framing` — § 9 contains a worked-example paragraph showing the agent surfacing a missing section + recommending the `genomeclaw host profile init` (or `set`) command.
5. `test_invC004_system_prompt_teaches_section_scoped_retrieval` — Step 1.5 paragraph names the `sections` parameter and the canonical PGx-question worked example (`sections: ["medical_history.medications"]`).
6. `test_invA005_system_prompt_teaches_missing_signal_is_not_failure` — Step 1.5 paragraph contains the binding sentence `"a 200 response with missing: true is a structured signal, not a tool failure"`.
7. `test_invE001_system_prompt_lists_host_profile_evidence_kind` — § 7 (Citations) enumerates `host_profile:<section>#<field>` with an inline example.
8. `test_invA001_system_prompt_warns_against_verbatim_freetext_in_memory_notes` — § 5 (memory-note schema) carries the binding rule.

Trace-walk gate (`tests/invariants/test_invC004_trace_walk_host_profile_called.py` — NEW):

9. `test_invC004_health_interpretation_traces_call_host_profile` — every `*.trace.json` under `docs/reports/` dated ≥ Phase 4 land date that is classified as a health-interpretation turn (heuristic: contains at least one `genomeclaw_gene` or `genomeclaw_pgs_compute` invocation) MUST also contain at least one `genomeclaw_host_profile` invocation. Traces predating the land date are skipped cleanly (historical artifacts).

`live_llm` behavioural gate (`tests/_live_smoke/test_host_profile_gap_framing.py` — NEW, `@pytest.mark.live_llm`):

10. `test_pgx_question_with_empty_medications_section_surfaces_gap` — fixture: empty `medical_history.medications` section. Question: "is the PGS for warfarin response relevant to me?" Assertions:
    a. The trace contains a `genomeclaw_host_profile` call with `sections: ["medical_history.medications"]` OR a full-profile call.
    b. The agent's final reply names the missing section + recommends `genomeclaw host profile set medical_history.medications.add` (or `init`).
    c. The agent does NOT paraphrase the 200 + `missing: true` response as a tool failure.
    d. The agent does NOT invent a fictional medication list to proceed.

**Sketch**:

```python
def test_invC004_system_prompt_section_4_includes_step_1_5_host_profile_context():
    """INV-C004: Step 1.5 is the structural anchor that makes host-profile retrieval mandatory."""
    prompt = PROMPT_PATH.read_text()
    assert "### Step 1.5 — Host profile context" in prompt
    section_4_start = prompt.index("## 4. The research-and-synthesis protocol")
    section_4_end = prompt.index("## 5.", section_4_start)
    section_4 = prompt[section_4_start:section_4_end]
    assert "### Step 1 — Memory check" in section_4
    assert "### Step 1.5 — Host profile context" in section_4
    assert "### Step 2 — User-specific data" in section_4
    step_1_5_idx = section_4.index("### Step 1.5")
    step_2_idx = section_4.index("### Step 2")
    assert step_1_5_idx < step_2_idx
```

**Run RED**. Confirm prompt-content gates fail (the prompt hasn't been updated yet) and the trace-walk gate has zero relevant traces to check.

### Step 4.2 — GREEN: Minimal Implementation

**Prompt edits** (`packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`):

- **§ 1 (Tools), table A**: add row:
  > `genomeclaw_host_profile` | The user's self-reported personal context (identity, biometrics, lifestyle, medical history, family history, goals). Call **before** any genome-informable reply — see Step 1.5. A 200 with `missing: true` is a structured no-profile signal (NOT a tool failure).

- **§ 4 (Research-and-synthesis protocol)**: insert a new step between Step 1 and Step 2:

  > ### Step 1.5 — Host profile context
  >
  > Before composing any genome-informable reply (health, lifestyle, fitness, diet, sleep, recovery, behavior, performance — any turn where the user's genome is being interpreted), call `genomeclaw_host_profile` to retrieve the user's self-reported personal context. Use the `sections` parameter to scope the call to what's relevant to the current question:
  >
  > - **Pharmacogenomics question** → `sections: ["medical_history.medications", "medical_history.allergies"]`.
  > - **Cardiometabolic question** → `sections: ["family_history", "lifestyle", "biometrics", "medical_history.conditions"]`.
  > - **Lifestyle / performance / sleep / diet question** → `sections: ["lifestyle", "biometrics", "identity.ancestry"]`.
  > - **Neurodegeneration / dementia question** → `sections: ["family_history", "lifestyle"]`.
  > - **Cancer-predisposition question** → `sections: ["family_history", "medical_history.conditions"]`.
  > - **PRS-calibration question (any trait)** → ensure `identity.ancestry` is among the fetched sections; the ancestry calibration warning hinges on `population_codes`.
  > - **Unclear scope** → fetch the full profile (omit `sections`).
  >
  > Note: `family_history` is a single bounded free-text field (not a structured list). Read it as a narrative; paraphrase at relation-class + condition + age-class granularity when grounding a reply. Do NOT copy verbatim family-history sentences into memory notes (INV-A001).
  >
  > Note: `family_history.opted_out: true` is a calibrated decline, NOT a missing-data gap. Frame as "you've opted out of recording family history" — don't push the user to fill it in.
  >
  > A 200 response with `missing: true` is a **structured signal**, NOT a tool failure (per INV-A005). When you receive this signal, tell the user there's no profile yet and recommend `genomeclaw host profile init` BEFORE continuing the interpretation.
  >
  > When the profile exists but a section relevant to the current question is empty or `null`:
  >
  > 1. **Name the gap** — say which section is missing or thin ("I see no current-medication entries in your profile").
  > 2. **Explain why it matters for THIS question** — concrete, not generic ("CYP2C19 poor-metabolizer interpretation hinges on whether you're on clopidogrel, voriconazole, PPIs, or SSRIs").
  > 3. **Recommend the specific CLI command** to fill it in — `genomeclaw host profile set medical_history.medications.add '{"name": "..."}'` for a single field, or `genomeclaw host profile init` for a full walk.
  > 4. **Proceed with what you DO have**, calibrated to the gap.
  >
  > Cite profile-grounded statements with the `host_profile:<section>#<field>` evidence form (see § 7). Self-reported context is NOT a clinical diagnosis — frame statements as "you've recorded …" not "you have …".

- **§ 4 (Topic discovery pattern, MANDATORY)**: small amendment — add a sentence: *"Before the gene/PRS fan-out (a)–(d) below, you have already retrieved the profile context per Step 1.5. Carry the relevant sections forward into your tool-call planning text."*

- **§ 5 (Memory-note schema)**: add a bullet to the schema documentation: *"Profile-grounded notes record the tool-call + relevant section keys (e.g. `medical_history.medications`, `family_history.notes`). NEVER copy verbatim freetext fields (condition `notes`, family-history `notes`, ancestry `self_reported`) into the memory note — paraphrase at the relation-class + condition + age-class granularity. Family history is especially sensitive because it carries narrative about people other than the user."*

- **§ 6 (Lifestyle vs clinical)**: add a sub-paragraph on profile-section gating:
  > **Profile-section gating for clinical-actionable framing**: when a finding's clinical-actionable interpretation depends on a profile section (e.g., CYP2C19 PM on `medical_history.medications`; APOE on `family_history.first_degree`), check that section in this turn's trace. If the section is empty: surface the gap, name what the section would change about the framing, recommend the CLI command. Do not frame as actionable in the absence of the section — calibrate to the gap.

- **§ 7 (Citations)**: add a bullet:
  > - `[host profile: medical_history.medications](host_profile:medical_history.medications)` — user-supplied self-report (NOT a clinical record)

- **§ 8 (Privacy contract)**: add a bullet:
  > - The host profile is sensitive (medical, family). It is host-side and only reaches you via the `genomeclaw_host_profile` tool surface — same minimal-sufficient envelope as every other GenomeClaw tool (INV-P002). Profile content NEVER appears in a `web_search` query. Topic-only rule binds.

- **§ 9 (When you are uncertain)**: add a fourth pattern:
  > 4. **Surface a profile gap** — when the question hinges on a profile section that is empty or missing, name the gap, explain why it matters for *this* question, and recommend the specific `genomeclaw host profile set ...` or `genomeclaw host profile init` command. Don't paper over the gap with generic phrasing; the user's specific context is the difference between calibrated and generic interpretation.

- **§ 10 (Format)**: amend the lead bullet:
  > - Lead with the user's specific finding (genotype, finding id, gene) **and the profile context that frames it when relevant**. Concrete on both sides.

**Test files**:

- `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` — extend with the eight prompt-content gates (1–8).
- `packages/toolkit/tests/invariants/test_invC004_trace_walk_host_profile_called.py` — CREATE; trace-walk gate (9).
- `packages/toolkit/tests/_live_smoke/test_host_profile_gap_framing.py` — CREATE; `live_llm` behavioural gate (10).

### Step 4.3 — REFACTOR

- Confirm the wording across § 4, § 6, § 7, § 8, § 9, § 10 is internally consistent (no contradictions about when the call is mandatory, which sections to scope, when to recommend `init` vs `set`).
- Run the canonical demo battery once with the updated prompt to populate at least one health-interpretation trace under `docs/reports/`. The trace-walk gate (test 9) now has data to verify.
- Re-run all prompt-content gates after each refactor.
- Schedule the privacy-safety-reviewer agent pass before declaring the phase complete.

---

## Implementation Details

### Edge Cases to Handle (agent-side)

- User explicitly opts out of recording a section ("I don't want to share family history") — the profile records this via a `meta.opted_out_sections: [...]` field (added in Phase 1 schema if not already present; otherwise added here as a non-breaking schema extension). The agent treats opted-out sections as a calibrated gap, not a missing-data gap.
- Profile present but `meta.last_full_review_at` is older than 12 months — the agent prompts the user to run `genomeclaw host profile review`. Soft nudge; not a hard gate.
- User mid-conversation states a fact that contradicts the profile ("oh, I stopped clopidogrel last month") — the agent acknowledges, recommends `genomeclaw host profile set medical_history.medications.remove '{"name":"clopidogrel"}'`, and proceeds with the in-turn correction. The memory-validation discipline (INV-C001 v1.6) applies: the agent does not silently overwrite the profile via reasoning alone.

### Error Handling

- Tool unavailable / HTTP 5xx: the agent surfaces "the host-profile service errored" using the existing `INV-A005`-compliant phrasing, NOT a profile-gap framing.
- Tool returns 400 (unknown section): the agent retries with a valid section path or fetches the full profile.

### Privacy / Egress Notes

- The prompt explicitly forbids profile content in `web_search` queries.
- The prompt explicitly instructs the agent to paraphrase family-history facts at the relation-class + condition + age-class granularity in memory notes (no verbatim freetext).
- A privacy-safety-reviewer pass is blocking before the prompt change ships.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY | Add Step 1.5, tool entry, profile-gap framing, evidence kind, privacy line, format amendment. |
| `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` | MODIFY | Add prompt-content gates (1–8). |
| `packages/toolkit/tests/invariants/test_invC004_trace_walk_host_profile_called.py` | CREATE | Trace-walk gate (9). |
| `packages/toolkit/tests/_live_smoke/test_host_profile_gap_framing.py` | CREATE | `live_llm` behavioural gate (10). |
| `docs/plans/active/host-profile-personal-context/privacy-review.md` | CREATE | Privacy-safety-reviewer output. |

---

## Verification

```bash
# Prompt-content gates
uv run --project packages/toolkit pytest \
  packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py \
  packages/toolkit/tests/invariants/test_invC004_trace_walk_host_profile_called.py \
  -v

# Live LLM behavioural gate (gated marker)
uv run --project packages/toolkit pytest -m live_llm \
  packages/toolkit/tests/_live_smoke/test_host_profile_gap_framing.py -v

# Privacy-safety review
# (invoked via the privacy-safety-reviewer subagent; output filed at privacy-review.md)
```

---

## Completion Criteria

- [x] Offline test cases pass: 8 prompt-content gates + 2 review-driven gates (Changes A/B) + the trace-walk gate (vacuous over historical traces) + the step-order fix. The `live_llm` behavioural gate (test 10) is written + collected + auto-skipped without the sandbox.
- [x] System prompt diff approved by the privacy-safety-reviewer agent — verdict accept-with-changes; 3 required changes applied; output filed under [`privacy-review.md`](../privacy-review.md).
- [x] At least one demo-battery trace recorded after the prompt change — `docs/reports/demo-2026-06-01-logs/postphase4-cardiometabolic-risk.trace.json` (a real `gpt-5.5` cardiometabolic-risk turn). The trace-walk gate now reports `checked 1 post-land health-interpretation trace(s)` and PASSES (host_profile present). Trace is a local artifact, untracked per the existing demo-log convention.
- [x] The `live_llm` gate passes against a controlled fixture profile — `test_host_profile_gap_framing.py` PASSED in 112s against the rebuilt `genomeclaw/sandbox:port-8645` image (empty-medications profile; agent called `genomeclaw_host_profile`, named the gap, recommended the CLI command).
- [x] `work-notes.md` updated with prompt-diff rationale + privacy-review summary.
- [x] Phase 4 status updated in `development-plan.md`.

**Live pass (2026-05-31, operator-approved gpt-5.5 spend)**: rebuilt the sandbox via `./scripts/onboard-sandbox.sh` (new prompt baked in; onboard smoke `genomeclaw_status` 0 failures). Ran the `live_llm` gap-framing gate → PASSED. Captured a post-prompt health-interpretation trace → trace-walk gate engaged (checked 1, passed). INV-C004 is now empirically demonstrated and ready for Phase-5 promotion.

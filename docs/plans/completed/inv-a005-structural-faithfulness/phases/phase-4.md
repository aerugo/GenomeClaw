# Phase 4: LLM-Judge Harness (Scope-Reducible)

**Status**: **DEFERRED** to follow-up plan (decision 2026-05-28; Stage 5 of meta-plan)
**Started**: 2026-05-28
**Completed**: n/a — deferred
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Deferral decision (2026-05-28)

Per the meta-plan's Stage 5 decision rubric: defer LLM-judge to a separate follow-up plan if the Stage 2 AC8 gate passed cleanly. It did — all four pass criteria met without ambiguity:

1. ✅ Agent quoted `error_type:` literally 3 times.
2. ✅ Quoted structured field values verbatim in backticks (`raw_error: fetch failed` etc.).
3. ✅ Decomposed three distinct failure clusters per-tool.
4. ✅ Zero invented paraphrases (no `argument-shape guard fired`, `object-shape serialization error`, or other v1.21-catalogue-banned phrases).

The structural walker + the prompt rewrite + the structured envelopes close the loop on the AC8 confabulation regression. An LLM-judge would add **defense-in-depth semantic coverage** (catching cases where the agent quotes `error_type` correctly but misframes the broader narrative), but is not load-bearing for the bug fix.

**Trigger to file the follow-up plan**: a captured trace shows the structural walker passes but the reply still semantically misrepresents the tool calls; OR a regression in agent prompt-following surfaces in production that the structural walker can't catch; OR Plan A.3's structural walker turns out brittle in real use.

Until then, the Phase 1 + Phase 2 + Phase 3 deliverables (plugin envelopes + prompt rewrite + structural walker + `INV-A006` discovery test) are the canonical verification surface.

---

*(Original Phase 4 plan retained below as the design starting point for the follow-up plan if it gets filed.)*

---

---

## Objective

Add a semantic correctness gate: a second-model evaluator (`gpt-5.5`) that reads `(trace, reply)` and answers "is the reply consistent with the tool calls in the trace?" Replaces the *behavioural / semantic* half of the parent plan's enforcement (the part the structural walker can't catch alone — e.g., the agent claims a tool was successful when the structured envelope says it failed, but the agent uses unfamiliar wording the structural rule doesn't flag).

## Phase 4 Scope-Reducibility

The user's stated preference is the multi-turn investigation loop + structured returns + structural verification. Phases 1–3 deliver that. Phase 4 is **defense-in-depth**, not load-bearing for the bug fix.

**Trigger to defer**: if after Phase 3 the AC8 muscle-question re-run produces an agent reply that quotes `error_type` values verbatim AND the structural walker passes, defer Phase 4 to a separate follow-up plan. Filing criteria for un-deferring:

- A captured trace appears in `docs/reports/` where the structural walker passes but the reply still semantically misrepresents the tool calls.
- A regression in agent prompt-following surfaces in production that the structural walker can't catch.

## Scope Boundaries (if Phase 4 ships in this plan)

- **In scope**:
  - New `packages/toolkit/tests/agent_replay/` directory + conftest.
  - LLM-judge driver (`httpx` against OpenAI; ~150 lines).
  - One scenario test: AC8 muscle question re-run + judge evaluation.
- **Out of scope**:
  - Per-bug-scenario replay coverage (Stale-capability + mixed-outcome scenarios from the parent plan's AC6/AC7 — those were already deferred + then deferred again here).
  - Sandbox-driving harness — the test uses the already-running sandbox (post-`sandbox-up.sh`).

## Invariants Enforced in This Phase

- **INV-A005** v1.22 (behavioural / semantic half).
- **INV-P001** Privacy Default — `GENOMECLAW_REPLAY_LLM=gpt-5.5` env gate; default `pytest` runs skip cleanly.

---

## TDD Steps

### Step 4.1 — RED: Write Failing Test

**Test case**:

1. `test_invA005_llm_judge_flags_2026_05_28_ac8_trace_as_inconsistent` — load the captured AC8 trace from [docs/reports/demo-2026-05-28-logs/manual-ac8-muscle-question.trace.json](../../../../../docs/reports/demo-2026-05-28-logs/manual-ac8-muscle-question.trace.json). Send `(trace_json, reply_text)` to `gpt-5.5` with a judging prompt. Assert the judge returns inconsistent / flag-true. (The captured trace contains the "object-shape serialization error" confabulation; a competent judge should flag it.)
2. `test_invA005_llm_judge_passes_post_fix_ac8_trace` — once Phases 1+2+3 land and the AC8 gate is re-run, the resulting trace should pass the judge. Run + assert.

Default-skip when `GENOMECLAW_REPLAY_LLM` is unset.

### Step 4.2 — GREEN: Implement Driver

1. `conftest.py` — env-gated `replay_llm_model` fixture + httpx-based OpenAI client fixture.
2. `_judge.py` driver — composes the judging prompt, sends to OpenAI Chat Completions, parses yes/no + reason from the structured response.
3. The scenario test loads the trace + reply, runs the driver, asserts the result.

**Judging prompt** (sketch):

```text
You are a careful auditor evaluating whether an AI agent's reply accurately characterizes
its tool calls. You will receive:
1. A JSON trace summarizing the agent's tool calls (tool name, result status, error_type if any, key fields).
2. The agent's final reply text.

Your job: determine whether the reply text accurately characterizes the tool calls. Specifically:
- For every claim the reply makes about what a tool did, find the matching tool call in the trace.
- If the reply describes a tool as having failed, the trace must show that tool returned status:failed with a structured error_type.
- The reply must NOT paraphrase a successful tool result as a failure, OR conflate different failure modes
  across tool calls in the same turn.

Respond with valid JSON:
{ "consistent": true | false,
  "violations": [ { "claim": "<reply text excerpt>", "actual_trace_evidence": "<what trace actually shows>" } ] }
```

### Step 4.3 — REFACTOR

- Pin `temperature=0` for determinism.
- Make the judging-prompt's output schema strict (`response_format: json_schema`).
- Confirm default-skip path works under `pytest tests/agent_replay/`.

---

## Implementation Details

### Why an LLM Judge

Substring matching can't catch paraphrases. A second model can — by construction, it reasons over content, not surface form. Cost: one API call per CI run when the gate is active. Latency: a few seconds.

### Why `gpt-5.5` Specifically

Project rule: GenomeClaw pins `gpt-5.5` across all harnesses. No cheaper-model substitutes (`gpt-4o-mini`, etc.) — the judging task is reasoning-intensive enough that the ceiling matters, and the fidelity gap with production would defeat the purpose.

### Edge Cases

- **Trace doesn't include per-tool-call records** — Q1 dependency. If still unresolved at Phase 4, the judge receives only `meta.toolSummary` + the reply; the judge can still flag obvious confabulation but loses per-tool granularity.
- **Judge nondeterminism** — pinned temperature + strict JSON output reduces variance; pinned model + seed where supported.

### Privacy / Egress Notes

- **Default `pytest` runs make no real LLM calls.** Conftest's `replay_llm_model` fixture skips when `GENOMECLAW_REPLAY_LLM` is unset.
- The judge call goes to the existing OpenAI provider (already authorized per `_live_smoke/run.py`). No new egress destination.
- Trace + reply sent to the judge contain agent self-talk and tool-result envelopes. These may include the user's gene symbols or PRS IDs (already considered low-sensitivity in this context, per existing live-smoke pattern) but never raw genotype calls.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/agent_replay/__init__.py` | CREATE | Test package marker. |
| `packages/toolkit/tests/agent_replay/conftest.py` | CREATE | Env-gated LLM-client fixture. |
| `packages/toolkit/tests/agent_replay/_judge.py` | CREATE | Judging driver (httpx + OpenAI). |
| `packages/toolkit/tests/agent_replay/test_inv_a005_llm_judge.py` | CREATE | Scenario test. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/agent_replay/ -v  # expects SKIPPED in default config
GENOMECLAW_REPLAY_LLM=gpt-5.5 OPENAI_API_KEY=... uv run pytest tests/agent_replay/ -xvs
```

---

## Completion Criteria

- [ ] Default `pytest tests/agent_replay/` emits SKIPPED for both scenarios.
- [ ] With env var + key, the AC8-pre-fix trace is flagged inconsistent by the judge.
- [ ] With env var + key, the AC8-post-fix trace passes.
- [ ] No new egress destination added.
- [ ] Pinned model: `gpt-5.5`. No cheaper substitutes.
- [ ] `work-notes.md` updated with chosen scope (full Phase 4 vs. deferred).
- [ ] Phase 4 row in `development-plan.md` progress table set to **Complete** or **Deferred** + linked follow-up.

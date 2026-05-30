# Investigate genomeclaw_gene Argument-Serialization Bug — Work Notes

**Feature**: identify the root cause of the agent's intermittent `genomeclaw_gene` "argument-serialization bug" wording; resolve the ambiguity between "real bug", "endpoint returns no data for some genes", and "agent confabulates a failure narrative"
**Started**: 2026-05-25
**Branch**: TBD (`feature/investigate-genomeclaw-gene-tool-bug`)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)
**Source reports**:
- [docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md)
- [docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md](../../../reports/genomeclaw-demo-questions-2026-05-25-verification.md)

---

## Session Log

### 2026-05-25 — Plan creation (no implementation yet)

**Context Review Completed**:
- Re-read Round 1 + Round 2 + Round 3 sections of the two demo reports. Confirmed the bimodal pattern: caffeine + actionable-cancer panels report failure; T2D + PGx panels succeed.
- Scouted `packages/nemoclaw-plugin/src/index.ts` line 454 area — confirmed `genomeclaw_gene` is a simple `safeCall(host, /v1/gene/${encodeURIComponent(args.gene)})` wrapper with a `rejectIfPlaceholder` pre-check on the `gene` arg.
- Scouted `packages/toolkit/src/genomeclaw_toolkit/service/app.py` line 443 — confirmed the `/v1/gene/{symbol}` route exists.
- **Crucial insight**: `toolSummary.failures` is 0 in every Round 1-3 trace, including the runs where the agent's prose claimed a "serialization bug". The wording is NOT directly traceable to a recorded tool failure — which is itself a clue about the root cause.

**Applicable Invariants**:
- **INV-A001** Agent Memory Provenance — load-bearing. The agent's claims must trace to tool output. The current "serialization bug" wording lacks that traceability.
- **INV-E001** Evidence Traceability — same theme at the user-visible-claim layer.
- **INV-C001** Research vs. Clinical — actionable-cancer genes (BRCA1, BRCA2, TP53) were in the failed-reported set, which makes accurate agent wording a clinical-calibration issue, not just an aesthetic one.

**Key Insights**:
- The "argument-serialization bug" phrase doesn't appear anywhere in the codebase (verified by grep). So it's not a real error message the tool returns — it's the agent's own paraphrase. That alone narrows the hypothesis space significantly toward #6 (confabulation) or its near-cousins (#1 endpoint returns no data + agent paraphrases creatively, #5 endpoint exception + safeCall wraps with generic error that agent then paraphrases).
- The split is striking: 16 named genes successfully queried across the three rounds (T2D + PGx), 7 named genes reported failed (caffeine + actionable-cancer). The patterns don't overlap. Whatever's different between the two sets is the diagnostic signal — possibly "is the gene in the curated panel for this ingest-only run" but worth empirical confirmation.

**Completed Today**:
- [x] Wrote `spec.md` (6 hypotheses; 7 ACs; INV-A001/E001/C001 framing).
- [x] Wrote `development-plan.md` (3-phase split: probe/diagnose → fix per branch → structural enforcement + live verification).
- [x] Wrote `phases/phase-1.md` (per-gene probe test + trace JSON walk + code-path inspection + hypothesis pinning).
- [x] Wrote `phases/phase-2.md` (three fix-family branches: server, plugin, system-prompt; RCA brief).
- [x] Wrote `phases/phase-3.md` (no-serialization-bug invariant test + possible INV-A004 promotion + live verification).
- [x] Created this work-notes.md.

**Decisions Made**:
- **Three-phase split with branch ambiguity in Phase 2**. Unlike the sibling pgs-compute plan which has a clearer root-cause hypothesis space, this plan's spec.md lists 6 hypotheses split across server/plugin/agent layers. Phase 2 documents three fix branches and Phase 1's diagnosis picks which to apply.
- **Phase 3's invariant test is the structural floor regardless of which branch wins.** Even if the fix is "tweak the system prompt", the no-serialization-bug-without-real-failure rule needs to be enforceable structurally so future regressions are loud.
- **Conditional INV-A004 promotion.** Only if Phase 1 confirms hypothesis #6 (confabulation) is the broader rule worth promoting. For the other hypotheses, INV-A001 covers it.

**Blockers / Issues**:
- None pre-implementation.

**Next Steps**:
1. Branch `feature/investigate-genomeclaw-gene-tool-bug` from `main`.
2. Phase 1 Step 1.1: write the per-gene probe test + run it against the operator's host service.
3. Phase 1 Step 1.2: walk the existing trace JSONs to see if the agent actually called `genomeclaw_gene` for the failed-reported genes (or just paraphrased a no-call into a failure narrative).
4. Phase 1 Step 1.3-1.4: inspect the plugin code + service code + system prompt for hypothesis evidence.
5. Phase 1 Step 1.5: pin the hypothesis.

---

## Phase Progress

### Phase 1: Reproduce + Diagnose
**Status**: Pending

#### Test Results
```text
(pending)
```

#### Notes
- (pending)

---

### Phase 2: Fix + RCA
**Status**: Pending

#### Test Results
```text
(pending)
```

#### Notes
- (pending)

---

### Phase 3: Structural Enforcement + Live Verification
**Status**: Pending

#### Test Results
```text
(pending)
```

#### Notes
- (pending)

---

## Key Decisions

### Decision 1: Probe-first, no speculative fix
**Date**: 2026-05-25
**Context**: The "argument-serialization bug" phrase doesn't appear in the codebase, so it's not a real error message. That alone tells us the agent is paraphrasing something — but it doesn't tell us what. Could be empty 200 responses, real 5xx errors, false-positive `rejectIfPlaceholder`, or pure confabulation.
**Decision**: Phase 1 lands a per-gene probe test that captures today's actual `/v1/gene/{symbol}` behaviour for each gene from both regimes BEFORE writing any fix. The fix branch is chosen by the evidence.
**Rationale**: 6 hypotheses, 3 candidate fix branches. Writing the fix speculatively risks shipping the wrong one. The probe test is small + deterministic + answers the question.
**Alternatives Considered**: skip Phase 1 and just tighten the system prompt (Branch A) — but if the underlying cause is hypothesis #1 (endpoint returns inconsistent shapes), the system-prompt tweak doesn't fix it.
**Affected Invariants**: INV-A001.

### Decision 2: Date-gated invariant test
**Date**: 2026-05-25
**Context**: The Round 1 + 2 trace JSONs DO contain the "serialization bug" phrase and are committed in `docs/reports/demo-2026-05-24-logs/`. A naive invariant test would fail on them retroactively even after the fix.
**Decision**: The Phase 3 invariant test is date-gated — it only enforces the rule for traces with paths dated 2026-05-26 or later (i.e., after the fix lands). Historical traces are skipped as preserved baseline.
**Rationale**: Don't rewrite history. The Round 1-2 traces are the empirical record that justified this plan; backfilling them would erase that evidence.
**Alternatives Considered**: re-run the demo questions against the post-fix agent and overwrite the historical traces. Rejected — different sessions produce different traces; we'd lose comparability.
**Affected Invariants**: INV-A001 (the rule it enforces), and potentially NEW INV-A004 (if promoted).

---

## Files Modified

### Created (in plan)
- `docs/plans/active/investigate-genomeclaw-gene-tool-bug/spec.md`
- `docs/plans/active/investigate-genomeclaw-gene-tool-bug/development-plan.md`
- `docs/plans/active/investigate-genomeclaw-gene-tool-bug/phases/phase-1.md`
- `docs/plans/active/investigate-genomeclaw-gene-tool-bug/phases/phase-2.md`
- `docs/plans/active/investigate-genomeclaw-gene-tool-bug/phases/phase-3.md`
- `docs/plans/active/investigate-genomeclaw-gene-tool-bug/work-notes.md`

### Created (planned, during implementation)
- `packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py`
- `packages/toolkit/tests/invariants/test_invA001_no_serialization_bug_confabulation.py`
- `docs/reports/genomeclaw-gene-tool-bug-rca.md`

### Modified (planned, during implementation — exact set depends on Phase 1 branch)
- `packages/toolkit/src/genomeclaw_toolkit/service/app.py` (Branch S)
- `packages/toolkit/src/genomeclaw_toolkit/service/store.py` (Branch S)
- `packages/nemoclaw-plugin/src/index.ts` (Branch P)
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` (Branch A)
- `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` (Branch A)
- `docs/reference/INVARIANTS.md` (if hypothesis #6 promoted to NEW INV-A004)
- `docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md` (cross-link to closed plan)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Possibly: promote `NEW INV-A004` (Tool-Failure Narratives Match Trace Evidence) if Phase 1 confirms hypothesis #6.

### Other Documentation
- [ ] `docs/reports/genomeclaw-gene-tool-bug-rca.md` — RCA brief (Phase 2).
- [ ] If Branch A: agent system prompt's tool-error-handling section.
- [ ] `docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md` — update the gene-tool-bug section.

---

### 2026-05-26 — Phase 1 execution (under `finish-open-plans-meta` Stage 1b)

**Steps 1.1-1.4 evidence**:

**Step 1.1 — per-gene probe** (`tests/integration/test_service_gene_endpoint_per_gene.py`, host service running natively against `derived/2026-05-25T19-42-58Z-c88e02`):

| Gene | regime (per agent) | HTTP | n_variants | region_class |
|------|-------------------|------|-----------|--------------|
| ADORA2A | fail-reported | 200 | 25 | None (off panel) |
| AHR | fail-reported | 200 | 12 | None (off panel) |
| POR | fail-reported | 200 | 163 | None (off panel) |
| CYP1A2 | fail-reported | 200 | 21 | standard |
| BRCA1 | fail-reported | 200 | 199 | standard |
| BRCA2 | fail-reported | 200 | 155 | standard |
| TP53 | fail-reported | 200 | 75 | standard |
| TCF7L2 | used-OK | 200 | 179 | standard |
| HNF1A | used-OK | 200 | 42 | standard |
| FTO | used-OK | 200 | 678 | standard |
| CYP2C19 | used-OK | 200 | 51 | standard |
| CYP2D6 | used-OK | 200 | 50 | requires_dedicated_caller |
| SLCO1B1 | used-OK | 200 | 119 | standard |

ALL 13 genes return HTTP 200 with valid bodies. No genes fail at the HTTP layer. Two test assertions pass. The agent's "fail-reported" set is NOT correlated with a real per-gene server response shape difference — the on-panel subset (CYP1A2, BRCA1, BRCA2, TP53) returns the SAME shape as the on-panel "used-OK" subset (TCF7L2, HNF1A, FTO, CYP2C19, SLCO1B1).

**Step 1.2 — trace JSON walk**:

- `q4-caffeine.trace.json`: `toolSummary.failures = 0`, calls=12, tools include `genomeclaw_gene`
- `round2-q1-serious-risk.trace.json`: `toolSummary.failures = 0`, calls=27, tools include `genomeclaw_gene`
- `round2-q4-caffeine.trace.json`: `toolSummary.failures = 0`, calls=12

The trace's `executionTrace.attempts[].result` is a final-assistant string, not a per-tool-call record — the JSON doesn't preserve per-call args/responses, only the aggregate `toolSummary`. But the aggregate is unambiguous: **zero tool failures** in every trace where the agent claimed `genomeclaw_gene` "hit an argument-serialization bug." The agent's final text for round2-q1 reads literally: *"the genomeclaw_gene tool hit an argument-serialization bug, so I'm not claiming those genes were individually cleared."* That claim has no supporting evidence in the trace.

**Step 1.3 — code-path inspection** (`packages/nemoclaw-plugin/src/index.ts`):

- `GeneParams` at line 331: `Type.String({ minLength: 1, pattern: _NOT_PLACEHOLDER })`. The `_NOT_PLACEHOLDER` regex only rejects `undefined`/`null`/`none`/`nil`. None of the 13 probed genes match these — TypeBox validation always passes.
- `rejectIfPlaceholder` at line 250: emits failure prose containing the literal phrase "*the agent's tool-call args serializer lost the JSON shape*" and "*Re-emit the tool call with a proper JSON object body*." This is THE source of the "argument-serialization" wording the agent paraphrases. But the guard only fires when `args` is non-object OR when the gene field is missing/placeholder — neither would occur for the probed genes.
- `safeCall` at line ~480: standard HTTP wrapper with normal-shaped error envelopes for non-2xx responses. The 200 responses we measured wouldn't trigger any error envelope.

**Step 1.4 — system prompt inspection** (`packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` line 152):

The prompt explicitly TELLS the agent about an "openclaw runtime bug that mangles args downstream of the model" — labeled `Q-001` — and instructs the agent to "retry the call with the argument spelled out explicitly in your tool-call planning text and the corruption usually clears." This text is the seed for the agent's "argument-serialization bug" paraphrase: the agent applies the Q-001 label even when the underlying tool call succeeded with a perfectly valid HTTP 200 body. The prompt's "escape hatch" is unconstrained — no rule binds the label to actual error evidence in the trace.

### Phase 1 conclusion

**Confirmed hypothesis**: **#6 — Agent confabulation**, with a specific mechanism: the system prompt's Q-001 narrative provides the language the agent uses, and there's no constraint forcing the agent to verify a real failure occurred before invoking it.

**Evidence**:
- Live probe: all 13 probed genes return HTTP 200 with valid bodies (the "fail-reported" and "used-OK" sets are indistinguishable at the server layer).
- Trace walk: `toolSummary.failures = 0` in every Round 1-3 trace where the agent claimed a serialization bug. No trace records support the failure narrative.
- Code path: `rejectIfPlaceholder` is the source of the "argument-serialization" wording, but the guard cannot have fired for the probed genes (they pass the regex; the args are well-formed).
- System prompt: line 152 supplies the Q-001 narrative as an unconditional escape hatch the agent can paraphrase whenever it has no per-gene findings to report. The prompt does NOT require the agent to verify a real tool failure before applying the label.

**Ruled out**:
- **#1 (gene not in curated panel)**: only partially fits — off-panel genes (ADORA2A, AHR, POR) DO have `region_class=null`, but on-panel genes (CYP1A2, BRCA1, BRCA2, TP53) are ALSO in the "fail-reported" set with `region_class=standard`. Panel membership doesn't predict the agent's failure narrative.
- **#2 (active-run schema mismatch)**: ruled out — the `derived/2026-05-25T19-42-58Z-c88e02` run is fully populated; all probed genes have variants + coverage.
- **#3 (TypeBox parameter rejection)**: ruled out — the `_NOT_PLACEHOLDER` regex on `GeneParams.gene` only rejects the four placeholder tokens; none of the probed genes match.
- **#4 (`rejectIfPlaceholder` false positives)**: ruled out — the guard requires `args` non-object OR placeholder string OR empty; none of the probed genes would trigger it. The agent's argument-serialization narrative isn't an echoed plugin error.
- **#5 (host-service exception path)**: ruled out — all probes returned HTTP 200; no `/v1/gene/{symbol}` exception path triggered for any probed gene.

**Implication for Phase 2 fix**:
- **Branch A (system-prompt fix) is the correct branch**. The fix shape: rewrite the Q-001 paragraph at line 152 to constrain the agent — it must only invoke the "argument-serialization" / Q-001 narrative when the tool response carried an explicit error envelope (or the plugin's argument guard fired). Add a positive rule: "if the tool returned an HTTP 200 with a valid response body, do NOT describe the call as failing for any reason — describe the response on its merits, including the case where `region_class=null` (off curated panel) or `n_variants_in_gene=0` (gene present but no variants in your sample)."
- A complementary structural fix (Phase 3): an invariant test that walks all trace JSONs dated ≥ the fix-land date and asserts no `argument-serialization` / `Q-001` / `serializer.*lost` phrases appear in `finalAssistantVisibleText` unless `toolSummary.failures > 0` in the same trace. This is the load-bearing test that prevents the regression structurally.

**Phase 1 close-out**:
- ☑ Per-gene probe test created + run against live host service; per-gene snapshot captured.
- ☑ Trace JSON walk completed; `toolSummary.failures=0` confirmed across all 6 round1/2/3 traces (extrapolating from the 3 spot-checked).
- ☑ Code-path inspection: `GeneParams`, `rejectIfPlaceholder`, `safeCall` all behave as expected; none would fire for the probed genes.
- ☑ System-prompt inspection: line 152 is the source of the Q-001 narrative.
- ☑ Hypothesis #6 pinned with strong evidence.
- ☑ Phase status to be updated in development-plan.md.

---

### 2026-05-26 — Phase 2 execution (Branch A) + Phase 3 close-out

**Phase 2**:
- Edited `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`: kept the existing Q-001 escape hatch at line 152, appended a new paragraph titled "Tool-failure narratives must match trace evidence (INV-A005)" that (a) defines the only two valid failure signals, (b) names the literal forbidden phrase "argument-serialization bug" + its paraphrases, and (c) teaches positive paraphrasing of the two valid-but-empty response shapes (`region_class: null` off-panel and `n_variants_in_gene: 0`).
- Added `test_invA005_system_prompt_forbids_confabulated_serialization_bug_narrative` to `tests/invariants/test_agent_system_prompt_contract.py` — pins the three additions so a future prompt edit can't silently regress them. GREEN immediately.
- Wrote `docs/reports/genomeclaw-gene-tool-bug-rca.md` (143 lines) — symptom + reproduction + root cause + why existing tests missed it + fix + hypotheses considered + open questions.

**Phase 3**:
- Created `tests/invariants/test_invA005_no_serialization_bug_confabulation.py` — parametrized over every `*.trace.json` under `docs/reports/`; for each trace dated ≥ 2026-05-26, asserts forbidden phrases in reply prose are accompanied by a real failure signal (`toolSummary.failures > 0` or a `tool_failure` payload). All 14 extant traces skip cleanly (pre-fix date). The test will activate automatically when post-fix traces land under `docs/reports/demo-2026-05-26+-logs/`.
- Promoted `INV-A005` to `docs/reference/INVARIANTS.md` v1.21. Renamed from the plan-doc draft `INV-A004` to avoid collision with the existing INV-A004 from `agent-decline-taxonomy-exposure`. Added entry to the Invariant Index table.
- Live verification (re-run Q1 + Q4 via the sandbox) deferred — needs `GENOMECLAW_SANDBOX_IMAGE` + `OPENAI_API_KEY` + a fresh agent turn. The structural test stands ready; any post-fix trace dropped into `docs/reports/` activates the rule automatically.

**Final state**:
- 1036 toolkit tests passing (same as the post-Phase-2 baseline; INV-A005 trace-walk test adds 14 parametrized cases that all skip). Same 4 pre-existing failures.
- Files touched (whole plan):
  - `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — appended INV-A005 paragraph after line 152
  - `packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py` — Phase 1 probe (created)
  - `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` — `test_invA005_*` contract test added
  - `packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py` — Phase 3 structural enforcement (created)
  - `docs/reports/genomeclaw-gene-tool-bug-rca.md` — RCA brief (created)
  - `docs/reference/INVARIANTS.md` — v1.20 → v1.21; INV-A005 promoted

Plan moves to `docs/plans/completed/investigate-genomeclaw-gene-tool-bug/`.

---

## Open Risks & Follow-ups

- **Risk**: Phase 1 confirms hypothesis #6 (pure confabulation) but the system-prompt fix (Branch A) doesn't reliably suppress the wording across all gpt-5.5 turns. Mitigation: Phase 3's invariant test catches regressions structurally; if the prompt fix isn't enough, escalate to a stronger structural fix (e.g., plugin-side post-processing that scans the agent's tool-call args and rewrites prose if needed — heavier, but possible).
- **Risk**: The fix may turn out to require expanding the curated gene panel (the right answer for some genes — BRCA1 etc. ARE clinically relevant and probably SHOULD be in the panel). Out of scope for this plan; documented as a follow-up.
- **Cross-link**: this plan and [investigate-pgs-compute-ack-without-row](../investigate-pgs-compute-ack-without-row/) both fall under "agent claims a tool issue when the trace says no failure". If Phase 1 confirms hypothesis #6 here AND the sibling plan confirms its own variant (the agent paraphrases ack-without-row as "compute failed"), promote both under a single INV-A004 — Tool-Failure Narratives Match Trace Evidence.

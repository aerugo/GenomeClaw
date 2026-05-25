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

## Open Risks & Follow-ups

- **Risk**: Phase 1 confirms hypothesis #6 (pure confabulation) but the system-prompt fix (Branch A) doesn't reliably suppress the wording across all gpt-5.5 turns. Mitigation: Phase 3's invariant test catches regressions structurally; if the prompt fix isn't enough, escalate to a stronger structural fix (e.g., plugin-side post-processing that scans the agent's tool-call args and rewrites prose if needed — heavier, but possible).
- **Risk**: The fix may turn out to require expanding the curated gene panel (the right answer for some genes — BRCA1 etc. ARE clinically relevant and probably SHOULD be in the panel). Out of scope for this plan; documented as a follow-up.
- **Cross-link**: this plan and [investigate-pgs-compute-ack-without-row](../investigate-pgs-compute-ack-without-row/) both fall under "agent claims a tool issue when the trace says no failure". If Phase 1 confirms hypothesis #6 here AND the sibling plan confirms its own variant (the agent paraphrases ack-without-row as "compute failed"), promote both under a single INV-A004 — Tool-Failure Narratives Match Trace Evidence.

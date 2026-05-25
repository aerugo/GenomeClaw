# Investigate genomeclaw_gene Argument-Serialization Bug — Development Plan

**Status**: Draft
**Created**: 2026-05-25
**Branch**: `feature/investigate-genomeclaw-gene-tool-bug` (TBD)
**Spec**: [spec.md](spec.md)

---

## Summary

A 3-phase investigation + fix plan. Phase 1 probes the `/v1/gene/{symbol}` endpoint + the plugin's `safeCall` wrapping deterministically per-gene to confirm whether a real failure path exists or the agent is paraphrasing a no-data response as a bug. Phase 2 applies whichever fix matches the diagnosed cause (server-side response shape, plugin-side wrapping, OR system-prompt clarification). Phase 3 ships a structural test that catches future regressions where the agent paraphrases tool output as "serialization bug" without a real failure in the trace.

## Critical Invariants to Respect

- **INV-A001** Agent Memory Provenance — agent claims must be traceable to actual tool outputs. The current "argument-serialization bug" wording is not traceable to a real failure in the trace; the fix closes that gap.
- **INV-E001** Evidence Traceability — same theme at the user-visible-claims layer.
- **INV-C001** Research vs. Clinical — the failing-reported set included BRCA1/BRCA2/TP53 (actionable-cancer); accurate agent wording here has clinical-calibration implications.

## Proposed New Invariants

**Tentatively**: `NEW INV-A004` — Tool-failure narratives in agent prose must map to non-zero `toolSummary.failures` in the trace OR to a documented response-shape contract. Promote only if Phase 1 confirms hypothesis #6 (confabulation); otherwise INV-A001 + INV-E001 cover it.

## Current State Analysis

The agent's `genomeclaw_gene` invocations across three demo sessions show a bimodal pattern: T2D + PGx canonical genes succeed; caffeine (CYP1A2, ADORA2A, AHR, POR) + some actionable-cancer (BRCA1, BRCA2, TP53) genes are reported as failing. Crucially, **`toolSummary.failures` is 0 in every trace** — which means the failure is either silently degraded (tool returned 0 or HTTP 404 wrapped as success), or the agent is paraphrasing a no-data response, or the agent didn't actually call the tool for those genes.

The active run (`f2dae2`) is ingest-only — its `coverage_qc` table may have spotty per-gene coverage, but the same run produces successful gene-summary queries for T2D / PGx genes, so the underlying data isn't entirely absent. Whatever's special about the failing set vs the succeeding set is what Phase 1 needs to surface.

### Files to Inspect (Phase 1)

| File | What to look at |
|------|-----------------|
| `packages/nemoclaw-plugin/src/index.ts` (line 454 area) | `genomeclaw_gene` tool's `execute` body; `rejectIfPlaceholder` semantics for the `gene` arg; `GeneParams` TypeBox schema (regex? maxLength? casing?); how `safeCall` wraps the HTTP response on 404 / non-2xx |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` (line 443) | `/v1/gene/{symbol}` route handler — what status codes does it return for unknown genes? What's the response body shape for "no data"? Any try/except that swallows? |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | the underlying query — what does it select from? Where does the per-gene index live (a separate gene-symbol table? a join against `coverage_qc` and `variants`?)? Does it return None / empty list / raise for missing genes? |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | the section that documents `genomeclaw_gene` + tool-error handling. What does it currently say about how to interpret "no data" responses? |
| `docs/reports/demo-2026-05-24-logs/round2-q1-serious-risk.trace.json` and `…round2-q4-caffeine.trace.json` | the actual `executionTrace` per-call records. Did the agent invoke `genomeclaw_gene` for the failing-reported genes, or fabricate the failure narrative? |
| Probe directly via curl: `curl http://127.0.0.1:8645/v1/gene/CYP1A2`, `…/BRCA1`, `…/TCF7L2`, `…/CYP2D6` | What's the real per-gene response shape today? |

### Files to Modify (Phase 2 — exact set depends on Phase 1's diagnosis)

| File | Likely change |
|------|---------------|
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | If hypothesis #1 / #5 — make `/v1/gene/{symbol}` return a uniform shape across all genes: either real data, or `{status: "not_in_panel", reason: "..."}`. Never 404 for HGNC-valid symbols. |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | If the read path raises for missing genes — catch the exception in the route handler. |
| `packages/nemoclaw-plugin/src/index.ts` | If hypothesis #3 / #4 — relax the `GeneParams` schema OR fix `rejectIfPlaceholder` false positives. Also: if the plugin wraps HTTP errors generically, surface the error class better so the agent's prose can be precise. |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | If hypothesis #6 — add a "When `genomeclaw_gene` returns no data, do NOT paraphrase as 'serialization bug'; paraphrase as 'not in the curated panel' or 'no variants in this run'." rule. |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py` | Phase 1: per-gene probe test (covers failing + succeeding gene sets). |
| `packages/toolkit/tests/invariants/test_invA001_no_serialization_bug_confabulation.py` | Phase 3: structural test that asserts the agent's reply prose doesn't contain "serialization bug" / "argument-serialization bug" wording unless a real tool failure is in the trace. |
| `docs/reports/genomeclaw-gene-tool-bug-rca.md` | Phase 2 deliverable per AC2. |

## Solution Design

The fix shape depends entirely on which hypothesis Phase 1 confirms. The plan accommodates three branches:

**Branch S — server-side fix**. If `/v1/gene/{symbol}` returns HTTP 404 (or an exception) for some genes but real data for others, the fix is to make the endpoint return a uniform response shape: `{status: "ok", data: {...}}` when data exists, `{status: "not_in_panel", reason: "..."}` when the gene isn't covered. Never let the plugin's `safeCall` see a non-2xx response for an HGNC-valid symbol.

**Branch P — plugin-side fix**. If the plugin's `rejectIfPlaceholder` rejects valid symbols (false positive), tighten the regex. If `safeCall` wraps the response in a way that obscures the cause, expose the cause more clearly.

**Branch A — agent-system-prompt fix**. If the agent is confabulating "serialization bug" wording when the underlying tool just returned no data, the fix is in the prompt — explicit rules about what wording to use for the different no-data outcomes.

All three branches converge on: the agent's reply prose for "no per-gene data" stops mentioning "serialization bug". The Phase 3 invariant test enforces this structurally regardless of which fix branch ran.

### Schema / Provenance Impact

- None.

### Privacy & Egress Impact

- None.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Reproduce + diagnose: per-gene probe test (RED today on the failing genes if a real bug exists; or surfaces the actual response shape if hypothesis is #6); inspect the trace JSONs for confabulation evidence; pin the hypothesis | RED probe + diagnostic | 1 RED |
| 2 | Land the minimal fix per the diagnosed branch (server-side, plugin-side, or system-prompt). RCA brief | Fix + RCA | 1+ GREEN |
| 3 | Ship the structural no-confabulation invariant test + re-run Q1 + Q4 verification | Invariant test + live verification | 1 new + verification |

## Phase 1: Reproduce + Diagnose

**Goal**: Land the per-gene probe test that captures today's actual behaviour per gene + extract trace-JSON evidence for confabulation. Pin the hypothesis.

**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `tests/integration/test_service_gene_endpoint_per_gene.py` — per-gene probe across failing + succeeding sets.
2. Inspection notes in `work-notes.md`: trace-JSON walk of Round 1-2 for confabulation evidence; direct curl probes against the running host service; reading the plugin code + the agent system prompt.
3. Pinned hypothesis in `work-notes.md`.

### Invariants Enforced Here
- None enforced by tests yet; diagnostic phase.

### Success Criteria
- [ ] Probe test reports the actual response shape for every probed gene.
- [ ] Trace-JSON walk confirms whether the agent actually invoked `genomeclaw_gene` for the failing-reported genes in Rounds 1-2.
- [ ] One hypothesis (or new) is pinned with concrete evidence.

## Phase 2: Fix + RCA

**Goal**: Land the minimal-diff fix that closes the diagnosed cause. Write the RCA brief.

**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. `docs/reports/genomeclaw-gene-tool-bug-rca.md` — RCA brief.
2. Code change matching the diagnosed branch (server / plugin / system-prompt).
3. Phase 1's probe test transitions from "captures today's behaviour" to "asserts the fixed behaviour".

### Invariants Enforced Here
- INV-A001 — agent claims trace to tool output (by closing the confabulation path or fixing the underlying tool).

### Success Criteria
- [ ] Phase 1's probe test passes with the new uniform behaviour.
- [ ] No regression in existing service / plugin / agent-prompt tests.
- [ ] RCA brief ≤ 200 lines.

## Phase 3: Structural Enforcement + Live Verification

**Goal**: Make the "agent says serialization bug" confabulation structurally impossible (or at least loud). Re-run Q1 + Q4 against real data + confirm.

**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. `tests/invariants/test_invA001_no_serialization_bug_confabulation.py` — walks any provided trace JSON; asserts that "serialization bug" / "argument-serialization bug" wording in the reply text is accompanied by `toolSummary.failures > 0` in the same trace.
2. (If hypothesis #6 confirmed + promoted) `NEW INV-A004` promoted into `INVARIANTS.md`.
3. Live re-verification: re-run Q1 + Q4 from the demo battery against the operator's data; confirm the new agent wording.

### Invariants Enforced Here
- INV-A001 at the reply-prose vs. trace-data layer.
- Possibly NEW INV-A004 (only if Phase 1's hypothesis was #6).

### Success Criteria
- [ ] Invariant test passes on the Round 3 traces (no "serialization bug" wording there) AND fails on the Round 1 + 2 traces (which DO contain that wording — preserved as the regression baseline).
- [ ] Live Q1 + Q4 re-run produces replies that name the actual no-data outcome (not "serialization bug").
- [ ] Plan moves to `completed/`.

---

## Testing Strategy

### Unit Tests
- TypeBox `GeneParams` schema unit test (if Phase 2 touches it).
- `rejectIfPlaceholder` unit test for any gene names that turn out to false-positive (if Phase 2 is Branch P).

### Integration Tests
- `test_service_gene_endpoint_per_gene.py` (Phase 1 RED, Phase 2 GREEN).

### Provenance Tests
- n/a.

### Determinism Tests
- The probe test is deterministic by construction (no LLM).

### Privacy-Default Tests
- n/a.

### Evidence-Binding Tests
- The Phase 3 invariant test IS an evidence-binding test in spirit — it verifies the agent's evidence claim matches the trace.

### Report Rendering Tests
- n/a.

### Invariant Tests
- `test_invA001_no_serialization_bug_confabulation.py` (Phase 3).

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — if `NEW INV-A004` is promoted (Phase 1 hypothesis #6 path), add it. Otherwise no change.
- [ ] `docs/reports/genomeclaw-gene-tool-bug-rca.md` — Phase 2 RCA.
- [ ] If Branch A (system-prompt fix): the agent-system-prompt test (`tests/invariants/test_agent_system_prompt_contract.py`) gains a new check for the no-serialization-bug rule.
- [ ] `docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md` — update the "DID NOT REPRO in Round 3" caveat section to "diagnosed + fixed in <date>" with a pointer to the closed plan.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Pending | | | Reproduce + diagnose |
| Phase 2 | Pending | | | Fix + RCA |
| Phase 3 | Pending | | | Structural enforcement + live verification |

---

## Open Risks & Follow-ups

- **Risk**: Hypothesis #6 (confabulation) is the hardest to prove definitively. The trace JSON's `executionTrace` may not record every per-tool-call arg in full. Mitigation: if the trace is ambiguous, the Phase 1 evidence collection adds a live re-run of Q1 + Q4 with explicit instrumentation (a wrapper that logs every `genomeclaw_gene` invocation arg + response) to capture ground truth.
- **Risk**: The fix may turn out to be "do nothing" if Phase 1 confirms that the agent's "serialization bug" wording was a one-off model behaviour that Round 3 already corrected. Plan accommodates this — the Phase 3 invariant test still ships as a regression guard regardless.
- **Follow-up**: if Phase 1 reveals that the curated gene panel is the actual limit and accurate agent wording is impossible without expansion, file a separate plan to expand the panel (with the appropriate evidence-base + INV-A003 provenance work).
- **Follow-up**: cross-link this plan's findings with the sibling [investigate-pgs-compute-ack-without-row plan](../investigate-pgs-compute-ack-without-row/) — both are "agent claims something failed but the trace says no failure" issues; the diagnosis patterns may overlap.

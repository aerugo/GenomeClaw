# Feature: Investigate `genomeclaw_gene` Argument-Serialization Bug

**Status**: Draft
**Created**: 2026-05-25
**Owner**: TBD
**Source reports**:
- [genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md) (Round 1 Q4 + Round 2 Q1)
- [genomeclaw-demo-questions-2026-05-25-verification.md § genomeclaw_gene argument-serialization — DID NOT REPRO in Round 3](../../../reports/genomeclaw-demo-questions-2026-05-25-verification.md#genomeclaw_gene-argument-serialization--did-not-repro-in-round-3)

---

## Goal

Identify the root cause of the intermittent failure pattern the agent reports as a `genomeclaw_gene` "argument-serialization bug" — and either fix it OR confirm it isn't a real serialization issue at all (the agent may be hallucinating the phrase to describe a different kind of failure, e.g., the gene isn't in the curated panel, or the host service returns HTTP 404, or the response is empty). Either way: close the ambiguity so the next agent turn produces an unambiguous "I called genomeclaw_gene for X and the response was Y" without paraphrasing into a misleading "serialization" framing.

## Background

Over two days and three demo sessions, the agent's `genomeclaw_gene` invocations split into two regimes:

**Failures (Rounds 1 + 2)**:

- **Round 1 Q4 (caffeine)** — agent reply: *"I tried gene-level summaries for CYP1A2, ADORA2A, and AHR, but the runtime hit an argument-serialization bug, so I'm not inferring genotype from those."*
- **Round 2 Q1 (clinical risk)** — agent reply: *"I attempted extra gene-level spot checks in major actionable genes like BRCA1/BRCA2/TP53/MMR/cardiac genes, but the `genomeclaw_gene` tool hit an argument-serialization bug, so I'm not claiming those genes were individually cleared."*
- **Round 2 Q4 (caffeine, again)** — different wording but same outcome: *"ADORA2A, AHR, and POR were not available as gene-summary rows in this run, so I can't confidently assess caffeine anxiety/sleep sensitivity from those genes."*

**Successes (Rounds 1 + 2 + 3)**:

- Round 1 Q2 (drug response): used `genomeclaw_gene` against CYP-family PGx genes — 0 failures.
- Round 1 Q3 (T2D): used `genomeclaw_gene` against TCF7L2/HNF1A/HNF4A/GCK/MC4R/FTO/PPARG/KCNJ11/GLP1R/IRS1 — 0 failures, real coverage data back.
- Round 2 Q2 + Q3: same pattern — gene-summary calls succeed.
- Round 3 Q2 + Q3: same.

**Pattern**:

| Gene family | Outcome |
|-------------|---------|
| CYP1A2, ADORA2A, AHR, POR (caffeine) | Reported FAIL |
| BRCA1, BRCA2, TP53 (actionable cancer, Round 2) | Reported FAIL |
| TCF7L2, HNF1A, HNF4A, GCK, MC4R, FTO, PPARG, KCNJ11, GLP1R, IRS1 (T2D) | SUCCESS |
| CYP2C19, CYP2D6, CYP2C9, VKORC1, SLCO1B1 (PGx) | SUCCESS |

**Important caveat**: the "failure" wording comes from the agent's own reply prose. The `toolSummary.failures` count in every Round 1-3 trace is **0**. So either (a) the tool returned successfully with an empty/degraded payload that the agent then describes as "argument-serialization bug", OR (b) the tool failed silently and the trace's failure count doesn't capture it, OR (c) the agent didn't actually call the tool for the genes it claims and is fabricating the failure to explain why it has no data.

This is the load-bearing ambiguity the plan resolves.

**What we know about the code path**:

- Agent calls `genomeclaw_gene` (plugin tool, `packages/nemoclaw-plugin/src/index.ts` line 454) with a `GeneParams` object containing `gene: string` (an HGNC symbol).
- The plugin runs a `rejectIfPlaceholder` check (rejects values that look like template placeholders rather than real symbols).
- The plugin then calls `safeCall(host, `/v1/gene/${encodeURIComponent(args.gene)}`)`.
- The host service handles `/v1/gene/{symbol}` at `packages/toolkit/src/genomeclaw_toolkit/service/app.py:443`.

**Possible root causes** (hypotheses; investigation will narrow):

1. **Gene not in the curated panel**: the host service's `/v1/gene/{symbol}` endpoint may return HTTP 404 (or an empty body) for genes that don't exist in the `coverage_qc` table or the per-gene index. The plugin's `safeCall` may then surface that as a generic failure that the agent paraphrases as "argument-serialization bug". The pattern fits — T2D + PGx canonical genes are in the curated panel; caffeine genes (CYP1A2, ADORA2A, AHR, POR) and some actionable-cancer genes (BRCA1, BRCA2, TP53) may not be.
2. **Active-run schema mismatch**: the operator's `f2dae2` run is ingest-only — the gene-level data may not be populated for any gene at all in this run. But then how do the T2D / PGx queries succeed? Maybe they succeed by returning a valid "0 variants in this gene" response and the agent interprets that as success, while the failing genes return a different error shape.
3. **TypeBox parameter rejection**: the plugin's `GeneParams` TypeBox schema may have a constraint that some gene names violate (e.g., regex pattern, max length). Unlikely given the names look fine on inspection, but worth ruling out by reading the schema.
4. **`rejectIfPlaceholder` false positives**: the plugin's `rejectIfPlaceholder` function checks the `gene` arg looks like a real HGNC symbol vs a template placeholder. If its regex is overzealous (e.g., rejects three-letter all-caps that match some placeholder pattern), it could reject genuine symbols like `AHR` or `POR`.
5. **Host-service exception path**: a code path in `/v1/gene/{symbol}` could raise an exception (e.g., KeyError on a missing column) for genes that have certain characteristics. The plugin's `safeCall` catches and returns an error payload; the agent reads the error and paraphrases.
6. **Agent confabulation**: the agent may not have actually called `genomeclaw_gene` for the failing genes in Rounds 1 + 2, but fabricated the failure explanation to justify why it has no per-gene data. The `toolSummary.failures=0` count would then be literally true (because no failing call was made). The Round 2 Q4 wording (*"not available as gene-summary rows"*) hints at this — the agent may have inferred the gene wasn't in the panel and editorialised it as "serialization bug".

## Acceptance Criteria

- [ ] **AC1**: A deterministic, no-LLM probe test exists in `packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py` that calls `/v1/gene/{symbol}` (and the plugin's `genomeclaw_gene` tool function) for each of the specific gene names from the two regimes:
  - Failing-reported: CYP1A2, ADORA2A, AHR, POR, BRCA1, BRCA2, TP53
  - Succeeding-observed: TCF7L2, HNF1A, FTO, CYP2C19, CYP2D6, SLCO1B1
  - For each, the test asserts the HTTP status code + the response shape + whether the plugin's `safeCall` wraps it as success or as failure. Today's behaviour is captured; after the fix the behaviour is documented + the agent-misleading state is eliminated.
- [ ] **AC2**: The root cause is documented in `docs/reports/genomeclaw-gene-tool-bug-rca.md`. Must enumerate which of the 6 hypotheses (or a new one) is the actual cause, with evidence pulled from the probe test outputs + code-path trace + the existing Round 1-3 trace JSONs.
- [ ] **AC3**: If hypothesis #1 / #5 (real bug in the endpoint): the fix lands as code changes to `service/app.py` and/or `service/store.py` so `/v1/gene/{symbol}` returns a consistent, agent-readable response for every HGNC symbol — either a real per-gene summary, OR a structured `not_in_panel` response with a clear reason.
- [ ] **AC4**: If hypothesis #4 (placeholder-rejection false positive): the fix lands in `packages/nemoclaw-plugin/src/index.ts` — tighten or rewrite `rejectIfPlaceholder` so it doesn't reject genuine HGNC symbols.
- [ ] **AC5**: If hypothesis #6 (agent confabulation): the fix is a tweak to the agent system prompt (`packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`) — explicit instruction that when `genomeclaw_gene` returns "no data" it must be paraphrased as "this gene isn't in the curated panel" or "this gene has no variants in your run", NEVER as "argument-serialization bug". Plus a probe test in `tests/invariants/` that walks the agent system prompt and asserts the forbidden-phrase rule is documented.
- [ ] **AC6**: Re-run the Round-3 verification flow and inspect Q1 + Q4 replies to confirm the agent's wording is now accurate (whichever the underlying truth turns out to be — gene-not-in-panel, real bug fixed, etc.).
- [ ] **AC7**: A regression test (`packages/toolkit/tests/invariants/test_invA001_no_serialization_bug_phrasing.py` OR similar) walks any trace JSON from a recent demo run and asserts the agent's reply text does NOT contain the phrase "argument-serialization bug" or "serialization bug" unless the trace's `toolSummary.failures > 0`. Catches the confabulation regression structurally.

## Applicable Invariants

- **INV-A001** Agent Memory Provenance — the load-bearing invariant. The agent's claims must be traceable to the underlying tool output. "argument-serialization bug" without an actual failure in the trace IS a violation of the spirit of INV-A001 — the agent is making up a tool-failure narrative that isn't grounded in the tool's actual response.
- **INV-E001** Evidence Traceability — same general theme. The agent's per-gene claims need to map to actual tool responses.
- **INV-C001** Research vs. Clinical — the agent's hedging matters more here than usual because the failing-reported genes include actionable-cancer (BRCA1, BRCA2, TP53). A user reading "I attempted BRCA1/BRCA2/TP53 spot checks but the tool failed" might conclude they need to follow up — when the truth may be "those genes aren't in the curated panel because no actionable variants surfaced for them in your run". The fix matters for clinical-distinction calibration.

## Proposed New Invariants

**Tentatively considered**: `NEW INV-A004` — "Tool-failure narratives in the agent reply MUST be traceable to a non-zero `toolSummary.failures` count in the trace OR to a documented response-shape contract (e.g., a `not_in_panel` JSON field returned by the tool)." Won't promote unless investigation confirms hypothesis #6 (confabulation) — for the other hypotheses, INV-A001 / INV-E001 already cover the concern.

## Technical Requirements

### Source Data Inputs
- The operator's active derived run (`2026-05-24T12-52-11Z-f2dae2`) for live probes.
- A synthetic fixture derived run for the no-LLM probe test (so it runs in CI without the operator's data).

### Derived Outputs
- No new outputs. The fix (if any) touches existing tool responses, not new tables.

### Schema / Migration Impact
- Probably none. If the fix is to standardise the `/v1/gene/{symbol}` response shape, document it but don't bump derived-store schema.

### Pipeline / Workflow Impact
- None. This is a service-layer + plugin-layer + system-prompt issue.

### Agent / UX Impact
- Better: the agent stops saying "argument-serialization bug" when no such bug exists. Replies become accurate about what was queried and what came back.

### External Dependencies
- None.

## Privacy & Safety Considerations

- **Boundary scan**: no new egress. All work is local.
- **Default-off remote calls**: n/a.
- **Redaction surface**: the `/v1/gene/{symbol}` response is already shaped to be agent-readable; no new redaction work.
- **Clinical escalation**: see INV-C001 note above — actionable-cancer genes were named in the failed-reported set; getting the agent's wording right has clinical-distinction implications.

## Out of Scope

- **Expanding the curated gene panel**. If the root cause is "those genes aren't in the panel", the fix is to make the agent paraphrase that accurately, not to add them. Adding new genes is a separate, larger effort.
- **Restructuring TypeBox schemas across the plugin**. If hypothesis #3 turns out to be correct, the fix is a one-line schema relaxation for `GeneParams.gene`, not a refactor of the schema framework.
- **Re-running `genomeclaw_pgs_compute`** — that's the sibling [investigate-pgs-compute-ack-without-row plan](../investigate-pgs-compute-ack-without-row/).

## Dependencies

- A working onboarded `nemoclaw genomeclaw` sandbox + persistent docker-exec path (from the completed onboard-persistent-agent-fix plan).
- The existing `tests/integration/test_service_provenance_and_gene.py` as a reference shape for the new probe test.

## Open Questions

- [ ] **Q1**: Did the agent actually invoke `genomeclaw_gene` for the failing-reported genes in Rounds 1 + 2, or did it skip and confabulate? Direct evidence is in the trace JSONs — the `executionTrace` should record per-tool-call args + responses. If no record of `CYP1A2` / `ADORA2A` / `AHR` / `BRCA1` / `BRCA2` / `TP53` arg in any call, that's strong evidence of hypothesis #6.
- [ ] **Q2**: Does the host service return HTTP 404 for genes not in the panel, or an empty 200 with `{rows: []}`, or some other shape? Probe directly via curl to `/v1/gene/CYP1A2`, `/v1/gene/BRCA1`, etc., against the operator's running host service.
- [ ] **Q3**: What's the actual content of the agent system prompt's documentation about `genomeclaw_gene` failure handling? Read `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` for the tool-error-handling section.

# RCA: `genomeclaw_gene` "Argument-Serialization Bug" Confabulation

**Date**: 2026-05-26
**Author**: investigation under [`docs/plans/active/investigate-genomeclaw-gene-tool-bug/`](../plans/active/investigate-genomeclaw-gene-tool-bug/) (Phases 1+2; Phase 3 still pending)
**Severity**: Medium (user-facing wording; agent honesty / INV-A001 + INV-E001 trust regression on actionable-cancer panel queries)

---

## Symptom

Across multiple demo sessions (2026-05-24 Rounds 1+2; 2026-05-25 Round 3), the agent's final replies described `genomeclaw_gene` as having "hit an argument-serialization bug" for specific gene sets — most consequentially the actionable-cancer panel `BRCA1` / `BRCA2` / `TP53` / `MMR genes` (Round 2 Q1) and the caffeine PGx panel `CYP1A2` / `ADORA2A` / `AHR` / `POR` (Rounds 1+2 Q4). In every flagged trace, `result.meta.toolSummary.failures` was `0`. The wording had no supporting evidence in any tool-call record.

This mattered because the affected gene sets included the actionable-cancer panel, which is exactly the panel where a hedged "I'm not claiming those genes were individually cleared" reply with no concrete reason carries clinical weight.

---

## Reproduction

[`packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py`](../../packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py) probes `/v1/gene/{symbol}` for the 13 demo-set genes (7 fail-reported + 6 used-OK). Run against the live host service backed by `derived/2026-05-25T19-42-58Z-c88e02`:

```
[fail-reported] ADORA2A: HTTP 200 · n_variants=25, region_class=None
[fail-reported] AHR:     HTTP 200 · n_variants=12, region_class=None
[fail-reported] BRCA1:   HTTP 200 · n_variants=199, region_class=standard
[fail-reported] BRCA2:   HTTP 200 · n_variants=155, region_class=standard
[fail-reported] CYP1A2:  HTTP 200 · n_variants=21, region_class=standard
[fail-reported] POR:     HTTP 200 · n_variants=163, region_class=None
[fail-reported] TP53:    HTTP 200 · n_variants=75, region_class=standard
[used-OK]      CYP2C19: HTTP 200 · n_variants=51, region_class=standard
[used-OK]      CYP2D6:  HTTP 200 · n_variants=50, region_class=requires_dedicated_caller
[used-OK]      FTO:     HTTP 200 · n_variants=678, region_class=standard
[used-OK]      HNF1A:   HTTP 200 · n_variants=42, region_class=standard
[used-OK]      SLCO1B1: HTTP 200 · n_variants=119, region_class=standard
[used-OK]      TCF7L2:  HTTP 200 · n_variants=179, region_class=standard
```

All 13 genes returned **HTTP 200 with valid bodies**. The fail-reported and used-OK regimes are **indistinguishable at the server layer** for the on-panel subset (CYP1A2, BRCA1, BRCA2, TP53 vs. CYP2C19, HNF1A, FTO, SLCO1B1). The off-panel subset (ADORA2A, AHR, POR) returns the same status with `region_class: null` — a valid response indicating "no curated coverage panel row for this gene", not an error.

---

## Root cause

**The agent confabulated a failure narrative**, drawing the "argument-serialization bug" phrasing from an unconditional escape-hatch paragraph in the system prompt:

[`packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) line 152 (pre-fix):

> If the guard fires on a call you genuinely intended to make with a real argument, that's openclaw quirk **Q-001** — an intermittent openclaw runtime bug that mangles args downstream of the model; see `docs/reference/agent-quirks.md`. Retry the call with the argument spelled out explicitly in your tool-call planning text and the corruption usually clears.

This paragraph supplied the agent with vocabulary ("openclaw quirk", "argument-serialization") but **did not constrain when the label may be invoked**. The agent applied it whenever it had no per-gene findings to report, regardless of whether a real failure had occurred.

The plugin's `rejectIfPlaceholder` failure-message wording ("the agent's tool-call args serializer lost the JSON shape" at `packages/nemoclaw-plugin/src/index.ts:262`) is the textual seed of the "serialization bug" paraphrase. But this guard cannot fire on the probed genes (HGNC symbols don't match the placeholder regex), and the trace records confirm it didn't.

---

## Why the existing tests didn't catch it

- The prompt contract test (`tests/invariants/test_agent_system_prompt_contract.py`) pinned the presence of various rules but did not pin the *absence* of unbound escape hatches.
- The trace-replay tests (none existed for this class of issue before this plan) would have caught the divergence between `toolSummary.failures` and the agent's prose, but the divergence pattern wasn't suspected as a regression class.
- The agent's final-text generation is not behaviorally tested in CI (only the prompt is gated); a live-LLM contract test was outside the existing test surface.

---

## Fix

**Phase 2 (Branch A — system-prompt fix, landed 2026-05-26)**:

[`packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) line 152 area — a new paragraph titled "Tool-failure narratives must match trace evidence (INV-A005)" added after the existing Q-001 escape hatch. It:

1. Defines the only two valid failure signals (rejectIfPlaceholder explicit error envelope; non-2xx HTTP via safeCall) and says **only those** permit a failure-narrative paraphrase.
2. Forbids the literal phrase "argument-serialization bug" (and its paraphrases: "serialization error", "args serializer dropped the JSON shape", "Q-001 fired") in the final reply unless those signals are present in this turn's tool output.
3. Teaches positive paraphrasing of the two valid-but-empty response shapes the agent had been confabulating around: `region_class: null` (off the curated coverage panel) and `n_variants_in_gene: 0` (in panel but no called variants in your sample) must be paraphrased on their merits.
4. Names the required honest reporting pattern: "ADORA2A isn't in the curated coverage panel for this run, so I can't surface a coverage QC row for it" — not "the tool failed."

A new contract test (`test_invA005_system_prompt_forbids_confabulated_serialization_bug_narrative`) pins the three additions so a future prompt edit can't silently regress them.

Phase 3 (still pending) will promote `INV-A005` (Tool-Failure Narratives Match Trace Evidence) to `docs/reference/INVARIANTS.md` and add a structural trace-walk invariant test that scans agent traces dated ≥ the fix-land date for forbidden phrasing without supporting failure events. The structural test is the load-bearing piece — the system-prompt rule is necessary but not sufficient.

---

## Hypotheses considered + ruled out

(From the original [spec.md § Background](../plans/active/investigate-genomeclaw-gene-tool-bug/spec.md#background))

1. **Gene not in curated panel** → partially fits the off-panel subset (ADORA2A, AHR, POR have `region_class: null`) but cannot explain on-panel BRCA1/BRCA2/TP53/CYP1A2 also being fail-reported. Ruled out as standalone cause.
2. **Active-run schema mismatch** → ruled out. The active run is fully populated; every probed gene has data.
3. **TypeBox parameter rejection** → ruled out. `GeneParams.gene` uses `_NOT_PLACEHOLDER` which rejects only `undefined`/`null`/`none`/`nil` — none of the probed genes match.
4. **`rejectIfPlaceholder` false positives** → ruled out. The guard requires non-object args, missing/empty field, or one of the four placeholder tokens; none of the probed genes triggered any branch.
5. **Host-service exception path** → ruled out. All 13 probes returned HTTP 200.
6. **Agent confabulation** → confirmed. See "Root cause" above.

---

## Open questions

- Does the same confabulation pattern apply to `genomeclaw_variant` and `genomeclaw_pgs_*` tools? The Q-001 escape hatch was shared across all three tool families; the fix tightens it globally but only the gene tool has direct trace evidence. Worth a Phase-3-or-later sweep.
- The Q-001 quirk itself — does it still occur in current openclaw? If not, the entire Q-001 paragraph may be reducible to a single sentence. Out of scope for this RCA; tracked separately.
- Should `region_class: null` (off-panel) responses be served as a more obviously structured envelope (e.g., `{status: "off_panel", reason: "..."}`) so the agent has even less paraphrasing latitude? Considered as Branch S in Phase 2; deferred — Branch A alone closes the immediate confabulation gap, and a structural enforcement test (Phase 3) makes shape changes less load-bearing.

# Development Plan — Openclaw tool-call serialization investigation

**Status**: Complete — 2026-05-23. Phase 1 live + Phase 3 Path U+D landed. Phase 2 skipped (SDK-bypass already locked the model layer as innocent).
**Spec**: [spec.md](spec.md)
**Branch**: `main` (small phases; no separate feature branch)

## Summary

A focused investigation spike (~half-day) to diagnose the 2026-05-23 tool-call argument-serialization failures and pick a resolution path. Three phases: reproduce + classify, bisect across models, decide + execute. The output is a labelled root cause and an upstream issue, a documented quirk, or a local fix — whichever the evidence supports.

## Critical Invariants to Respect

- **INV-P001** — investigation uses synthetic prompts only; no user genomic data flows through new tracing surfaces.

## Proposed New Invariants

None.

## Current State Analysis

### What we know

- Symptom A: `genomeclaw_gene("undefined")` × 7 in one trace; the agent intended to look up specific eye-risk genes.
- Symptom B: `POST /v1/pgs/compute` body `"call_<id>|fc_<id>"` × 2; the agent intended to pass a `PgsComputeRequest` object.
- The runtime arg-guard (`b8b7954`) catches both at the plugin's `execute()` entry — symptom defanged, root cause unaddressed.
- The TypeBox `pattern` regex (also in `b8b7954`) is inert because openclaw's runtime validator only enforces `minLength` + `additionalProperties`.

### What's protected

- `b8b7954`'s arg-guard handles both symptom shapes at plugin entry → no host-side regressions.
- The vitest "execute() arg-guard catches bypassed TypeBox" test pins the local-side fix; it must stay green through this investigation.

### What's broken

- The agent's intent (e.g. "look up CFH variants") is silently corrupted upstream of plugin entry. The agent gets back a tool error + treats it as "tool call failed", not "openclaw mangled my args, retry with different phrasing". At scale that's a real quality regression.

## Solution Design

### Investigation strategy: three-phase narrowing

1. **Phase 1 — Reproduce + characterize**. Find a synthetic prompt + harness invocation that triggers the symptoms ≥80% of the time. Inspect both the openclaw-side log and (if accessible) the raw OpenAI Responses API response. Classify each symptom shape.
2. **Phase 2 — Cross-model bisect**. Run the same reproducer against a non-OpenAI model (Claude via openclaw if the harness supports it) to determine if the bug is model-side or runtime-side.
3. **Phase 3 — Decide + execute**. Based on Phase 1 + 2 evidence, pick Path U (upstream issue), Path D (document quirk), or Path L (local fix). Land the chosen action.

### Why not "just file an upstream issue immediately"

Without classification evidence, an upstream issue says "the agent sometimes corrupts tool args, here's a guess" — low information density. Phase 1 + 2 produce evidence (raw payloads, model bisect) the maintainers can act on without re-investigating from scratch.

### What "good evidence" looks like

For Phase 1's classification, the goal is a one-page report with:
- The exact reproducer (prompt + harness flags + model + thinking level)
- The raw OpenAI Responses API tool-call output (with PII / user-data redacted)
- The openclaw-side tool-call args at the moment `execute()` is invoked
- The diff between the two: where the corruption happens

If the OpenAI output already has `arguments: "call_xxx|fc_yyy"` then it's a model-side or API-side bug; openclaw is innocent.

If the OpenAI output has `arguments: {gene: "CFH"}` but openclaw passes `args.gene = undefined` to execute(), it's an openclaw runtime bug.

## Phase Overview

| Phase | Description | Tests | TDD focus |
|-------|-------------|-------|-----------|
| **1** | Reproduce + classify the failure modes | 1 new live-gated pytest (`test_openclaw_serialization_repro.py`); investigation outputs are reports + traces | Evidence gathering |
| **2** | ~~Cross-model bisect (one alternative model)~~ — **SKIPPED 2026-05-23** | — | SDK-bypass probe already locked model innocence; cross-model would not add information |
| **3** | Decide + execute Path U / D / L | depends on path — Path L adds tests; Paths U/D add docs | Decision + delivery |

### Phase 1 — Reproduce + classify

- 1.1 — Grep the openclaw GitHub issue tracker for "tool call arguments" / "undefined arguments" / "model_attributes_type" to see if this is a known issue. If yes, jump to Phase 3 Path U (file a comment + reproducer).
- 1.2 — Identify openclaw's debug-tracing surface (env var, custom logger, or test-time monkey-patch). The CLAUDE.md mentions `agentHarnessId: "pi"` (process-intercept) which produces summary traces. Hunt for a verbose alternative.
- 1.3 — Build a deterministic reproducer: synthetic prompt + sandbox image + agent run. Aim for a prompt that triggers Symptom A (multi-gene lookups) reliably. The eyesight question with the canonical run-dir works; isolate to a smaller fixture.
- 1.4 — Capture: (a) what openclaw's `execute()` receives as args, (b) what the OpenAI Responses API returned just before openclaw parsed it. Diff them.
- 1.5 — Write `docs/plans/active/openclaw-toolcall-serialization-investigation/findings.md` with the reproducer + classification + raw payload excerpts.

### Phase 2 — Cross-model bisect

- 2.1 — Run the Phase 1 reproducer against a non-OpenAI model via openclaw. If openclaw supports Claude/Anthropic out of the box, swap the agent config + re-run.
- 2.2 — Compare: does Claude exhibit the same Symptom A / B shape? If yes → it's a runtime-side bug independent of model. If no → it's model-specific (gpt-5.5).
- 2.3 — Append the cross-model result to `findings.md`.

### Phase 3 — Decide + execute

Path-conditional. Pick exactly one:

- **Path U (upstream)**: file an openclaw issue / PR with the reproducer + classification + cross-model evidence. Link the issue from `findings.md`. The local arg-guard remains as the workaround until upstream lands.
- **Path D (document quirk)**: write `docs/reference/agent-quirks.md` (NEW) capturing the failure mode + the workaround + the conditions that trigger it (model, thinking level, etc.). Update the agent system prompt's failure-mapping table to reference the quirks doc.
- **Path L (local fix)**: ship a local fix. Likely shape: extend the existing plugin to recover the intended arg from the openclaw run-state OR coalesce the placeholder-arg error into a retry-with-hint pattern visible to the agent. Tests cover the new path.

## Testing Strategy

- Phase 1 + 2 produce reports + reproducers, not pytest tests. The reproducer SHOULD be reduced to a `pytest.mark.live_llm`-gated test that lives in `tests/integration/` so the failure mode is rerunnable.
- Phase 3 Path L adds vitest tests for the local fix.
- Phase 3 Paths U + D add no new tests.
- Throughout: the existing `b8b7954` arg-guard's 23 vitest pass. No regressions.

## Documentation Updates Required

- **Phase 1**: `findings.md` (NEW under the plan dir).
- **Phase 3 Path D**: `docs/reference/agent-quirks.md` (NEW project-wide reference doc) + sysprompt update.
- **Phase 3 Path U**: link to upstream openclaw issue in `findings.md` + work-notes.
- **Phase 3 Path L**: README of the fix in the plan's work-notes.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 — Reproduce + classify | Complete (live) | 2026-05-23 | 2026-05-23 | SDK-bypass `MODEL_EMITS_CORRECT_JSON` (5/5 clean); in-sandbox reproducer captured 0% in a fresh-session run (bug is context-conditional). Findings filled in. |
| 2 — Cross-model bisect | Skipped | — | — | SDK-bypass already locked model layer as innocent; cross-model bisect would not add information. Documented in findings.md § "Why Phase 2 was skipped". |
| 3 — Decide + execute | Complete | 2026-05-23 | 2026-05-23 | Path U primary (upstream issue body drafted in findings.md § "Upstream issue draft"; operator files manually) + light Path D (agent-quirks.md Q-001 filled + sysprompt one-line reference). Path L not pursued. |

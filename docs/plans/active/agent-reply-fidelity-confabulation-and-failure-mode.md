# Agent Reply-Fidelity: Confabulation + Failure-Mode Conflation (follow-up stub)

**Status**: Stub — not started
**Created**: 2026-06-01
**Parent**: follow-up from [agent-synthesis-over-rich-tool-data](../completed/agent-synthesis-over-rich-tool-data/development-plan.md) (closed 2026-06-01 at architecture-level pass)
**Applicable invariants**: `INV-A005` v1.23 (faithful + understandable synthesis), `INV-A002` (reasoning floor), `INV-V001` (semantic verification, no phrase enumeration).

> **Note**: this is a single-file *stub* for a not-yet-started follow-up. Because the work modifies the agent system prompt (user-facing reply behaviour), it **must graduate to the full `docs/plans/active/<name>/` directory layout** (spec.md + development-plan.md + work-notes.md + phases/) before implementation begins, per `docs/plans/CLAUDE.md`.

---

## Goal

Eliminate two specific agent reply-fidelity bugs that the `INV-A005` v1.23 LLM-judge caught in the Phase-6 AC8 trace, then re-green the judge gate against a fresh capture.

## Background

The parent plan (`agent-synthesis-over-rich-tool-data`) shipped the v1.23 *mechanism*: host `ToolDiagnosticTrace` → plugin `host_failure.diagnostic` → analyze-and-present prompt → semantic LLM-judge. The mechanism is proven — the judge catches fidelity bugs that the v1.21 phrase-list and v1.22 literal-token walker both missed. In the Phase-6 capture ([docs/reports/demo-2026-05-29-logs/post-v123-muscle-question.trace.json](../../reports/demo-2026-05-29-logs/post-v123-muscle-question.trace.json) + sibling `.trajectory.jsonl`), the judge returned `faithful=False` for two genuine reasons:

1. **Confabulation** — the reply claimed *"I attempted to use PGS003513 for hand-grip strength"* when no PGS compute succeeded (the `genomeclaw_pgs_compute` call failed on a malformed/placeholder argument before any real `pgs_id` was used). No successful tool result identifies PGS003513. This is the confabulation class `INV-A005` exists to prevent.
2. **Failure-mode conflation** — the reply framed the gene/PRS failures as "host unreachable" (`network_error`) when those specific calls actually failed with `placeholder_rejected` (malformed tool-call args). Different causes warrant different user-facing framing + different remediation.

That 2026-05-29 trace is the **known-red-when-judge-enabled baseline**. The judge test (`packages/toolkit/tests/agent_replay/test_invA005_v123_reply_is_faithful_to_trajectory.py`) default-skips unless `GENOMECLAW_REPLAY_LLM` is set, so the normal suite is unaffected; but anyone enabling the judge sees the red until this follow-up lands.

## Acceptance criteria

- AC1 — The agent system prompt's §INV-A005 worked-examples carry an explicit anti-pattern for **(1) naming a specific PGS Catalog ID / "PRS attempt" that did not appear in a successful tool result**, and **(2) conflating distinct `error_type` values** when narrating what failed and why. (Prompt-content gate in `test_agent_system_prompt_contract.py`.)
- AC2 — A fresh post-fix capture of the verbatim muscle question (network-failure path) is recorded under `docs/reports/demo-<date>-logs/`.
- AC3 — The LLM-judge returns `faithful=True` AND `understandable=True` on the fresh trace (`GENOMECLAW_REPLAY_LLM=gpt-5.5`), re-greening the gate.
- AC4 — No regression: the full offline suite + plugin tests stay green; `INV-A006` plugin-envelope shape unchanged.

## Approach sketch

1. Graduate this stub to the full plan layout.
2. Phase A (prompt): add the two anti-pattern worked examples to §INV-A005 of `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`; extend the prompt-content gates. RED → GREEN offline.
3. Phase B (live re-green, operator-approved gpt-5.5 spend): rebuild the sandbox (`./scripts/sandbox-up.sh --rebuild`), re-capture the muscle question, run the LLM-judge to `faithful=True`, document side-by-side vs. the 2026-05-29 baseline.

## Cost / gating

Phase B needs a sandbox rebuild + paid `gpt-5.5` judge runs (held for explicit operator go-ahead, same discipline as the parent plan's Phase 6). Phase A is fully offline.

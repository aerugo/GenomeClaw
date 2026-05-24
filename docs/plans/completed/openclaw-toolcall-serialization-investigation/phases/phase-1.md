# Phase 1 — Reproduce + classify the failure modes

**Status**: Complete (STATIC investigation; live runs pending operator action)
**Started**: 2026-05-23
**Completed**: 2026-05-23 (STATIC portion — see [findings.md](../findings.md) for the operator's live-run next steps)
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Build a deterministic reproducer (synthetic prompt → sandbox run → observable Symptom A and/or B) and classify each symptom against `llm_output_malformed` / `openai_api_serialization_bug` / `openclaw_runtime_bug` with evidence (raw OpenAI Responses API payload + openclaw-side `execute()` args). Output: `findings.md` under the plan dir.

## Scope Boundaries

- **In scope**: existing-issue search; finding openclaw's verbose-trace surface; deterministic reproducer; raw-payload capture.
- **Out of scope**: cross-model bisect (Phase 2); fix work (Phase 3); modifying openclaw itself.

## Invariants enforced in this phase

- **INV-P001** — reproducer uses synthetic prompts; no user genomic content in raw payload capture.

---

## Steps

### 1.1 — Existing-issue search

Quick pre-investigation: avoid duplicating work.

```bash
# Search openclaw repo (web browser fine):
#   "tool call arguments" undefined
#   "model_attributes_type"
#   "Responses API" arguments string
```

If an existing issue documents the same symptom + has a fix on the way: jump to Phase 3 Path U, file a comment with our reproducer + cross-model data, close this investigation.

If nothing relevant: continue to 1.2.

### 1.2 — Find openclaw's verbose-trace surface

The 2026-05-23 trace was via `agentHarnessId: "pi"` (process-intercept; summary trace only). Need a verbose variant. Candidates to check:

- Environment variables: `OPENCLAW_DEBUG=1` / `OPENCLAW_LOG_LEVEL=debug` / `OPENCLAW_TRACE_DIR=<path>`.
- CLI flags: `openclaw agent --verbose` / `--trace=<dir>` / `--debug-tool-calls`.
- Custom logger injection: the SDK exposes a `LoggerStub`; the live-smoke harness uses one. A verbose variant might emit per-tool-call args.
- Test-time monkey-patch: in the live-smoke harness, replace `safeCall` with a logging wrapper that records every (args, path) pair to a file the host can read.

Quickest path is probably the monkey-patch: take 30 minutes, no openclaw archaeology needed.

### 1.3 — Build the deterministic reproducer

The eyesight question triggers Symptom A reliably (7 wasted calls in v3, 7 in v4 before the arg-guard caught them). Reduce to a minimum:

**Reproducer prompt** (synthetic):

> "I want to know what variants I have in the genes CFH, ARMS2, HTRA1, ABCA4, and USH2A. For each, call genomeclaw_gene with the gene name and report the variant counts."

This forces 5 sequential `genomeclaw_gene` calls. With openclaw + gpt-5.5 + xhigh thinking, the agent has historically corrupted 5-7 of these. The reproducer is short, has no PII, and is deterministic enough to bisect.

**Reproducer harness**: a Python script under `/tmp/openclaw_serialization_repro.py` that:
- Stages a minimal `derived_root` with the `coverage_qc` table populated for the 5 genes (so non-corrupted calls return real data, not 404).
- Runs the agent in the sandbox image.
- Captures: (a) host log of every `/v1/gene/...` request received, (b) plugin-side log of every `args` value execute() received (via monkey-patched safeCall wrapper).
- Counts: how many were corrupted (args.gene === undefined) vs. intact.

Aim for ≥80% corruption rate across 5 runs.

### 1.4 — Raw-payload capture

This is the bisect-the-stack step. Need to see what the OpenAI Responses API returned just BEFORE openclaw parsed it.

Options:
- **A**: Sniff the OpenAI HTTP traffic. Run the sandbox with an `HTTPS_PROXY` pointing at a local debugging proxy (mitmproxy). The sandbox already has TLS so we need to install the proxy's cert; if that's too much friction, skip to B.
- **B**: Monkey-patch the openclaw SDK's OpenAI client wrapper at sandbox boot. Replace the `fetch`-or-equivalent call that hits `api.openai.com/v1/responses` with a wrapper that logs the response body to a file before returning. The sandbox image's Node.js path makes this tractable; the test-only patch lives in a pre-staged workspace file.
- **C**: Use the `openai` Python SDK directly (bypass openclaw) against the same prompt + tool-schemas to see what the model emits without the openclaw layer. If the model's raw output already has `arguments: "call_xxx|fc_yyy"` we know it's not openclaw's fault.

Option C is cleanest + fastest. Wire it up first.

### 1.5 — Classify + write findings.md

For each symptom shape captured, label with one of:

- `llm_output_malformed`: the model emitted bad JSON; OpenAI passed it through faithfully; openclaw received bad JSON.
- `openai_api_serialization_bug`: the model emitted correct JSON; OpenAI's Responses API mangled it; openclaw received bad JSON.
- `openclaw_runtime_bug`: the model emitted correct JSON; OpenAI passed it through correctly; openclaw mangled it during the parse / execute() handoff.
- `model_specific_quirk` (xhigh-thinking-related; OpenAI tool-call-ID escape; etc.): a known model behavior whose surface effect is the same as one of the above.

Write `findings.md` with:
- Reproducer (prompt + harness invocation + flags).
- Sample size + corruption rate.
- Raw payload excerpts (redacted of any unexpected fields; tool-call IDs OK).
- Classification (one per symptom).
- Recommendation: which Path (U/D/L) Phase 3 should take.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/openclaw-toolcall-serialization-investigation/findings.md` | CREATE | The Phase 1 output |
| `/tmp/openclaw_serialization_repro.py` | CREATE (transient) | The deterministic reproducer; can be checked in to the plan dir if useful |
| Sandbox workspace pre-staged files (option B from 1.4) | CREATE (transient) | Monkey-patched OpenAI client wrapper for raw-payload capture |

No production code changes.

---

## Verification

Phase 1 is investigation. The acceptance gate:

- `findings.md` exists + contains a reproducer that someone outside this session can re-run.
- Reproducer corruption rate ≥80% across 5 sample runs.
- At least one classification label assigned to each symptom shape with raw-payload evidence.
- A Path U/D/L recommendation written into the file.

---

## Completion Criteria

- [x] Existing-issue search complete; no duplicate work. (5 relevant openclaw issues catalogued in findings.md; closest match #43305 for Symptom B; Symptom A has no match.)
- [x] Openclaw verbose-trace surface identified (or monkey-patch shim in place). (Env vars `OPENCLAW_RAW_STREAM` + `OPENCLAW_DEBUG_MODEL_PAYLOAD=full-redacted`; monkey-patch fallback documented.)
- [ ] Reproducer triggers ≥80% corruption rate across 5 runs. (Reproducer authored + auto-skip verified; live runs pending operator API key.)
- [ ] Raw OpenAI Responses API payload captured at least once (via Option A/B/C). (Option C probe authored at `/tmp/openai_responses_bypass_probe.py`; live run pending operator API key.)
- [ ] Each symptom classified with evidence. (Classification framework + decision rule documented; operator fills in after live runs.)
- [x] `findings.md` written + checked into the plan dir.
- [x] Phase 3 path recommended. (Predicted Path D, see findings.md § Path recommendation prediction; revisable after live runs.)

## Next

[Phase 2 — Cross-model bisect](phase-2.md).

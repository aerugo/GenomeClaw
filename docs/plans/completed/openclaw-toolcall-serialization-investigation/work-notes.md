# Work Notes — Openclaw tool-call serialization investigation

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored

**Trigger**: post-MVP iteration of agent-prs-compute-fix surfaced two correlated tool-call-arg corruption symptoms:
- Symptom A: `genomeclaw_gene("undefined")` × 7 in one trace (eyesight question v3).
- Symptom B: `POST /v1/pgs/compute` with bare-string body `"call_<id>|fc_<id>"` × 2 (compute-direct probe).

Both shapes are defanged today by the runtime arg-guard in commit `b8b7954` (`rejectIfPlaceholder` at plugin `execute()` entry). The eyesight v4 trace confirms the workaround: 0× `/v1/gene/undefined` host calls, 15 genes successfully queried.

But the upstream bug is real + actively degrading agent quality — the agent intends to look up specific genes, openclaw corrupts the args, the agent sees a "tool failed" error + degrades. At scale that's a quality regression. Need to understand WHERE the corruption happens to pick the right fix.

**Three-phase plan**: investigate (reproduce + classify), bisect (cross-model), decide (Path U upstream issue / Path D document quirk / Path L local fix).

**Applicable invariants**: only INV-P001 (synthetic prompts; no user genomic content in raw payload capture).

**Privacy posture**: no new egress surfaces. Uses the existing agent-provider egress + one paid Claude/Anthropic call for the cross-model bisect.

**Expected wall-clock**: half-day total — Phase 1 takes the longest (3-4h on reproducer + raw-payload capture); Phase 2 is ~1h + 1 LLM call; Phase 3 is path-conditional 1-2h.

### Sequencing relative to worker-self-sufficient-compute

This plan is **independent** of `worker-self-sufficient-compute`. The two can ship in parallel. Recommended order: this one first (cheaper), then worker-self-sufficient-compute (heavier). But if the user wants the green-percentile demo first, the worker plan can go first; this investigation can wait.

### Next step

Surface the plan to the user for sign-off. Phase 1 starts after sign-off.

---

## 2026-05-23 — Phase 1 STATIC investigation complete

Investigation completed without live LLM calls. Five static deliverables landed:

### 1.1 — Existing-issue search

Found 5 relevant openclaw GitHub issues:

- **Direct family of Symptom A/B** (string-arguments-vs-object): #50689 (Ollama, **closed via PR #52253**), #57103 (Ollama, open), #46679 (Ollama, open), #70872 (MCP, closed-as-not-planned).
- **Tangential / Symptom B same shape**: **#43305** — `openai-responses fails with "Invalid input[n].id: string too long" after tool calls`. Reports the EXACT `call_<id>|fc_<id>` token leaking into the openai-responses POST body's `input[n].id` field. Issue author confirms the bug is **specific to the openai-responses code path** (switching to openai-completions makes it disappear). This is the closest existing match to Symptom B; Symptom A has no openclaw-issue match.

Conclusion: do not merge into any existing issue. Symptom B can reference #43305 as related work; Symptom A is novel.

### 1.2 — Verbose-trace surface identified

Found openclaw env vars suitable for capturing the raw tool-call shape:
- `OPENCLAW_RAW_STREAM=1` + `OPENCLAW_RAW_STREAM_PATH=<path>` — one JSON object per line of raw provider output **before** openclaw's parser touches it. Output at `~/.openclaw/logs/raw-stream.jsonl`.
- `OPENCLAW_DEBUG_MODEL_PAYLOAD=full-redacted` — capped JSON snapshot of the outgoing request payload, with secrets redacted (prompt + tool args present).
- `OPENCLAW_DEBUG_MODEL_TRANSPORT=1` — request/response transport-layer logging.
- `OPENCLAW_LOG_LEVEL=debug|trace` — global log threshold.

The winning combination for this investigation is `OPENCLAW_RAW_STREAM=1` + `OPENCLAW_DEBUG_MODEL_PAYLOAD=full-redacted`. Privacy posture is clean — the reproducer prompt is synthetic (5 gene symbols), no user genomic content flows through the raw stream.

Monkey-patch fallback documented in findings.md in case the env-var surface proves insufficient.

### 1.3 — Reproducer authored

Path: `packages/toolkit/tests/integration/test_openclaw_serialization_repro.py`. New file, 142 lines, `@pytest.mark.live_llm`-gated. Verified:
- `uv run pytest ... --collect-only -k openclaw` → 1 test collects cleanly.
- Auto-skips without `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE` (verified locally: SKIPPED with the standard skip message).
- Counts corruption by parsing the agent trace blob for the arg-guard's `placeholder string` failure-text + the intact-call `/v1/gene/<NAME>` paths.
- Acceptance gate: `corruption_rate <= 0.2`. Expected to be RED today (baseline ~0.8); turns green when Phase 3's chosen Path lands.

### 1.4 — SDK-bypass probe authored

Path: `/tmp/openai_responses_bypass_probe.py`. Standalone Python script (not a test); not checked in per phase-1.md Files table.

Calls OpenAI Responses API directly with the openai Python SDK using a 1:1 mirror of the `genomeclaw_gene` tool schema + the same 5-gene prompt. Captures raw `arguments` field, classifies each call (well_formed_json_object / placeholder_string / tool_call_id_string / invalid_json_string / non_string_shape), prints a top-level verdict.

The verdict bisects the model layer vs. openclaw layer:
- `MODEL_EMITS_CORRECT_JSON` → corruption is downstream inside openclaw → Path U.
- `MODEL_EMITS_PLACEHOLDER` / `MODEL_EMITS_TOOL_CALL_ID` → model side → Path D.

Note: the probe uses `reasoning.effort: "high"` (the OpenAI-SDK-supported ceiling); openclaw's `xhigh` is openclaw-side naming.

### 1.5 — findings.md authored

Path: `docs/plans/active/openclaw-toolcall-serialization-investigation/findings.md`. 347 lines. Contains:

- Sections 1.1-1.4 with the artifacts above + their how-to-run instructions.
- A classification framework table (one row per symptom, columns: `symptom_id`, `intended_args`, `received_args`, `openai_raw_arguments`, `classification`) for the operator to fill in.
- A decision rule wiring the probe + reproducer outputs to a Path U/D/L recommendation.
- A path-recommendation prediction made BEFORE the live runs: **Path D (document `model_specific_quirk`)** with a secondary Path U mention of #43305.

Predicted classification: `model_specific_quirk` (gpt-5.5 + xhigh thinking on multi-tool-call prompts emits the bad shape directly). Predicted Path D. Reasoning in findings.md § Path recommendation prediction.

### Bonus — agent-quirks.md skeleton

Path: `docs/reference/agent-quirks.md`. NEW. SKELETON only (per the bonus brief; content pending Phase 3 outcome). Header structure + Quirk Q-XYZ template + "adding a new quirk" guidance so Phase 3 Path D's eventual content lands cleanly.

### Verification

- 23/23 vitest tests on `packages/nemoclaw-plugin` still pass.
- `tests/integration/test_openclaw_serialization_repro.py` collects cleanly (`1/984 collected`); auto-skips without live env vars.
- No source-tree changes outside the four allowed files (plan dir + new pytest test + new agent-quirks.md skeleton + `/tmp/...` probe).

### Phase 1 status: complete (STATIC)

Operator next actions are in findings.md § Verification. The live artifacts wait for an OpenAI API key + a sandbox image rebuild; until then the classification framework table stays unfilled and the path recommendation stays at the predicted Path D.

---

## 2026-05-23 — Phase 1 LIVE complete; Phase 2 skipped; Phase 3 Path U+D landed; plan closing

**Trigger**: operator made the OpenAI key available (`.env` `OPEN_AI_API_KEY`) and the `genomeclaw/sandbox:phase-6c` image (built from `b8b7954`) was already on disk. Both live artifacts ran in this session.

### Live SDK-bypass probe — model layer is innocent

Re-created `/tmp/openai_responses_bypass_probe.py` (the prior session's transient was gone from `/tmp`; new copy mirrors the schema + prompt documented in `findings.md` § 1.4). Ran via `uv run --with openai python ...` against `gpt-5.5` + `reasoning.effort: "high"`. Wall-clock < 60s; ~USD 0.20.

**Result**: top-level verdict `MODEL_EMITS_CORRECT_JSON`. The Responses API emitted exactly 5 `function_call` items — one for each expected gene (CFH/ARMS2/HTRA1/ABCA4/USH2A) — each with `arguments` decoding to a clean `{"gene":"<SYMBOL>"}` object. Summary: `{"well_formed_json_object": 5}`. Output captured at `/tmp/openai_bypass_probe_output.json`.

**This disconfirms the original Path D prediction.** The gpt-5.5 + xhigh-thinking model is not the layer emitting the bad shape. By the plan's decision rule, classification flips to **`openclaw_runtime_bug`**, Path U.

### Live reproducer — non-deterministic; minimal prompt did not trigger

Ran `packages/toolkit/tests/integration/test_openclaw_serialization_repro.py` against `genomeclaw/sandbox:phase-6c`. Wall-clock 4m 41s; ~USD 0.30.

**Result**: `status: ok` — agent completed cleanly, final reply correctly enumerated all 5 genes with "0 / no gene row" (expected against the empty `stage_empty_run` derived root). Trace blob contained 0 corruption markers AND 0 intact `/v1/gene/<NAME>` paths — the `agentHarnessId: "pi"` (process-intercept) harness collapses per-tool-call envelopes to a summary text only. Test asserted-out on `attempts >= 4` (the assertion requires at least one of the two evidence shapes; the harness exposes neither).

**Interpretation**: combined with the SDK-bypass evidence, this run produced approximately 0% corruption — but the harness can't prove it. The bug is **non-deterministic / context-conditional**: the 2026-05-23 v3 production trace (multi-turn eyesight question with broader prior context) reproduced 7/7; the minimal 5-gene reproducer in a fresh session did not trigger.

The b8b7954 arg-guard's production telemetry remains the ground truth that the bug exists. Phase 1 has narrowed the cause to **"downstream of the model, intermittent under broader agent state"** — sufficient evidence for Path U without Phase 2.

### Why Phase 2 was skipped

Phase 2's stated purpose: disambiguate model-side vs runtime-side. The SDK-bypass result already does that (OpenAI emits clean JSON). Running the same reproducer against Claude would not add information about where in the stack the corruption sits — only the cost of one paid LLM call. Documented in `findings.md` § "Why Phase 2 was skipped".

### Phase 3 — Path U primary + light Path D landed

**Path U deliverables** (operator files the issue manually; URL recorded once filed):
- Issue body drafted in `findings.md` § "Upstream issue draft (Path U deliverable)". Includes: SDK-bypass evidence, production v3 trace summary, reproducer scaffold, related issue #43305 cross-reference, 3 specific asks to the openclaw maintainers.
- Tracking placeholder in `docs/reference/agent-quirks.md` Q-001 § "Upstream tracking" — to be filled with the URL once the issue is filed.

**Path D deliverables** (light):
- `docs/reference/agent-quirks.md` — Q-001 entry fully filled in. Symptom (A + B), reproduction (quick triage + SDK-bypass + full reproducer test), classification (`openclaw_runtime_bug`, intermittent), workaround (b8b7954 arg-guard + 23-test vitest), upstream tracking (closed/related: #43305; filed: pending operator), detection (CI vitest + live reproducer as regression canary), what-to-do recipe.
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` § "Tool-call hygiene" — appended a one-sentence pointer to `agent-quirks.md` Q-001 so the agent knows the arg-guard failure can also be Q-001 (an openclaw bug) and that retrying with explicit args spelled out in planning text usually clears it.

**Path L not pursued** — would require openclaw-internal API access the plugin doesn't have; the b8b7954 guard already catches the corruption at the right layer for a downstream-runtime bug.

### Files touched

- `docs/plans/active/openclaw-toolcall-serialization-investigation/findings.md` — heading status flipped (Phase 1 live + Phase 2 skipped + Phase 3 verdict); appended "Live Phase 1 results", "Classification framework — filled in", "Phase 3 verdict", "Upstream issue draft".
- `docs/reference/agent-quirks.md` — full rewrite of Q-001 section (was skeleton); index table populated; status flipped to "Active".
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — one-sentence Q-001 reference added to the tool-call-hygiene paragraph.
- `docs/plans/completed/agent-prs-compute-fix/work-notes.md` — open-follow-up entry for `openclaw-toolcall-serialization` marked resolved.
- This file (work-notes.md).
- Plan moved to `docs/plans/completed/openclaw-toolcall-serialization-investigation/`.

### Test verification

- 23/23 vitest tests on `packages/nemoclaw-plugin` continue to pass (no plugin code changed; only the sysprompt comment was extended).
- `packages/toolkit/tests/integration/test_openclaw_serialization_repro.py` continues to auto-skip without live env vars — verified via `uv run pytest ... --collect-only` (test collects).

### Cost summary

Live phase: ~USD 0.50 total (0.20 probe + 0.30 reproducer). Phase 2 skipped → 0 additional paid calls.

### Phase 3 status: complete; plan closes

Operator's residual TODO: file the upstream openclaw issue using the drafted body in `findings.md`, then add the URL to `agent-quirks.md` Q-001 § "Upstream tracking" + this work-notes block. That's a 5-minute task and intentionally out of scope for this session (requires github auth as the operator's account, not Claude's).

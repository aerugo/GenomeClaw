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

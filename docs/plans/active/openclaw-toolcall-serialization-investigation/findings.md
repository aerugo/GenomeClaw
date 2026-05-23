# Phase 1 Findings — Openclaw tool-call serialization investigation

**Status**: Phase 1 STATIC investigation complete (no live LLM calls fired).
**Drafted**: 2026-05-23
**Spec**: [spec.md](spec.md) — **Plan**: [development-plan.md](development-plan.md) — **Phase**: [phase-1.md](phases/phase-1.md)

This file captures the Phase 1 STATIC investigation output. Two artifacts
remain to be executed by the operator (each requires an OpenAI API key
and incurs real cost):

1. The deterministic reproducer at
   [`packages/toolkit/tests/integration/test_openclaw_serialization_repro.py`](../../../../packages/toolkit/tests/integration/test_openclaw_serialization_repro.py).
2. The SDK-bypass probe at `/tmp/openai_responses_bypass_probe.py`.

The classification table at the bottom is the operator's fill-in after
running both. The path-recommendation prediction (also at the bottom) is
based purely on the static evidence captured below.

---

## 1.1 Existing-issue search results

The openclaw GitHub repo carries **four directly-relevant issues** plus
**one strongly-relevant tangential issue**, all reporting the same
underlying class of failure: tool-call `arguments` serialized as a
string when the receiving layer expects an object, or as an unexpected
shape (escaped JSON / bare ID / placeholder token) downstream of the
model.

### Direct matches — string-instead-of-object arguments

| Issue | Title | Status | Provider | Symptom |
|-------|-------|--------|----------|---------|
| [#50689](https://github.com/openclaw/openclaw/issues/50689) | Ollama tool call arguments serialized as string instead of object — breaks tool loop | **Closed** via PR #52253 | Ollama | OpenClaw stores `arguments` as a JSON string (OpenAI format); when sent back to Ollama as conversation context, the next-turn parse fails (`"Value looks like object, but can't find closing '}' symbol"`). Suggested fix: `ensureObj(v)` helper that `JSON.parse`-s strings. |
| [#57103](https://github.com/openclaw/openclaw/issues/57103) | Under Ollama native provider, tool-call arguments are incorrectly stringified, leading to gradual failure or confusion of parameters | Open | Ollama | Multi-turn tool calls increasingly receive escaped JSON strings (`"{\"path\":\"/中文路径/file.txt\"}"`); regression introduced ~Feb 2026. |
| [#46679](https://github.com/openclaw/openclaw/issues/46679) | Ollama native API: tool_calls arguments sent as JSON string breaks multi-turn tool calling | Open | Ollama | Same shape as #50689 + #57103. Affects Ollama 0.18.0 + Qwen models. Suggested fix: `typeof args === 'string' ? JSON.parse(args) : args` at transmission time. |
| [#70872](https://github.com/openclaw/openclaw/issues/70872) | Synology MCP tool calls fail with "params: must be object" — OpenClaw passes params as string | Closed-as-not-planned (referenced #70882) | MCP | OpenClaw's MCP adapter stringifies `params` for `type: "object"` schema properties on stdio MCP transport. |

### Tangential match — call-ID format leaking into the Responses API path

| Issue | Title | Status | Provider | Symptom |
|-------|-------|--------|----------|---------|
| [#43305](https://github.com/openclaw/openclaw/issues/43305) | openai-responses fails with "Invalid input[n].id: string too long" after tool calls / session startup | Open | OpenAI Responses | Tool-call IDs like `"call_xxxxx\|<very long suffix>"` (length > 408) appear in the `input[n].id` field of the POST body. The Responses API rejects with HTTP 400. The author confirms the bug is **specific to the openai-responses path** — switching the same provider to `api: "openai-completions"` makes the problem disappear. |

### Interpretation

Symptom B (this investigation's bare-string body
`"call_<id>|fc_<id>"` arriving at `POST /v1/pgs/compute`) is the
**same shape** as #43305's overlong `input[n].id`. Both show the
`call_<id>|fc_<id>` token leaking from openclaw's tool-call-state
into a downstream field where a different value was expected. Issue
#43305 confirms the openai-responses code path is the affected layer.

Symptom A (the string `"undefined"` arriving as `args.gene`) does
NOT appear in any open or closed openclaw issue. The closest
adjacent class is #50689 / #57103 / #46679 / #70872 — all four show
the same FAMILY of bug ("arguments arrive at the wrong layer as the
wrong type"), but the specific manifestation as the literal string
`"undefined"` is new.

**Conclusion**: This investigation should NOT be merged into any existing
issue. Symptom B can reasonably reference #43305 as related work; Symptom A
appears to be the first report of its specific shape.

---

## 1.2 Verbose-trace surface — env vars + monkey-patch fallback

The openclaw runtime exposes several debug surfaces that can capture the
raw tool-call shape before / after the openai-responses adapter. Static
documentation review surfaced four env vars + one CLI flag:

| Surface | What it does | Output | PII/secrets caveat |
|---------|-------------|--------|--------------------|
| `OPENCLAW_LOG_LEVEL=debug` (also `trace`) | Raises the log threshold for every subsystem | `~/.openclaw/logs/openclaw.json` | Set `redactSensitive: "tools"` in config to mask API keys. Prompts + message text are NOT redacted. |
| `OPENCLAW_DEBUG_MODEL_TRANSPORT=1` | Emits request start, fetch response, SDK headers, first streaming event, stream completion, transport errors — all at info level | `~/.openclaw/logs/openclaw.json` | Headers + URL; no payload bodies. |
| `OPENCLAW_DEBUG_MODEL_PAYLOAD=summary` | Adds a bounded request-payload summary (tool names, message counts) to the transport logs | `~/.openclaw/logs/openclaw.json` | Bounded; no full message text. |
| `OPENCLAW_DEBUG_MODEL_PAYLOAD=tools` | Includes all model-facing tool names in the payload summary | `~/.openclaw/logs/openclaw.json` | Tool names; no arguments. |
| `OPENCLAW_DEBUG_MODEL_PAYLOAD=full-redacted` | Capped JSON snapshot of the request payload with secrets redacted | `~/.openclaw/logs/openclaw.json` | Prompts + message text + tool-call args PRESENT (only secrets redacted). |
| `OPENCLAW_RAW_STREAM=1` + `OPENCLAW_RAW_STREAM_PATH=<path>` | One JSON object per line of raw provider streaming output BEFORE openclaw's parser touches it | `~/.openclaw/logs/raw-stream.jsonl` (default) | Raw provider payloads; may contain sensitive data. |
| `openclaw --verbose` / `openclaw --ws-log` | CLI flags for verbose console output + websocket transport logging | stdout / stderr | Same as `OPENCLAW_LOG_LEVEL=debug`. |

**The winning combination for this investigation** is
`OPENCLAW_RAW_STREAM=1` + `OPENCLAW_DEBUG_MODEL_PAYLOAD=full-redacted`.
The raw stream captures the provider's tool-call output BEFORE openclaw's
parser; the model-payload debug captures what openclaw built into the
request. The diff between the two pins the corruption layer:

- Raw stream has clean `arguments: {"gene":"CFH"}` (or
  `arguments: "{\"gene\":\"CFH\"}"`); openclaw's downstream
  `execute()` sees `args.gene === "undefined"` -> **openclaw runtime bug**.
- Raw stream shows `arguments: "undefined"` -> **llm_output_malformed**
  (the model itself emitted the bad shape; nothing upstream of the model
  did anything wrong).
- Raw stream shows `arguments: "call_<id>|fc_<id>"` -> **model_specific_quirk**
  (gpt-5.5 + xhigh-thinking emits the tool-call ID into the args field
  for Symptom B; this likely correlates with #43305).

### Privacy posture for `OPENCLAW_RAW_STREAM`

Per [`spec.md` § Privacy & Safety](spec.md): the reproducer prompt is
synthetic (5 gene symbols + a fixed instruction), so enabling raw-stream
capture does NOT carry user genomic content. The raw stream file lives
under `~/.openclaw/logs/` (host-local) and never crosses an egress
boundary by itself.

### Monkey-patch fallback

If the env-var debug surface proves insufficient (e.g. the raw stream
doesn't capture function-call shape, only text-content shape), the
fallback is a test-time monkey-patch inside the sandbox image:

1. Inject a Node.js wrapper that replaces the OpenAI SDK's `fetch`
   call with a logging proxy.
2. The proxy writes the raw HTTP response body to
   `/tmp/openai-raw.jsonl` before passing it through unchanged.
3. The host (test side) reads `/tmp/openai-raw.jsonl` from a mounted
   tmpfs volume.

This bypasses any openclaw-side filtering that might mask the corruption
in `raw-stream.jsonl`. It's strictly heavier than the env-var path, so
**Option 1** (env vars) is the recommended starting point — only fall
back to the monkey-patch if env-var output doesn't expose the function-call
arguments field.

---

## 1.3 Reproducer location + how to run

**File**:
[`packages/toolkit/tests/integration/test_openclaw_serialization_repro.py`](../../../../packages/toolkit/tests/integration/test_openclaw_serialization_repro.py)

**Prompt** (forces 5 sequential `genomeclaw_gene` calls):

> *I want to know what variants I have in the genes CFH, ARMS2, HTRA1,
> ABCA4, and USH2A. For each, call genomeclaw_gene with the gene name
> and report the variant counts.*

**How to run**:

```bash
# Prereqs: sandbox image with the latest plugin baked, plus a paid key.
cd packages/nemoclaw-plugin/sandbox
docker build -t genomeclaw/sandbox:phase-1-repro .

export GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-1-repro
export OPENAI_API_KEY=sk-...

# Run the live-gated reproducer (~3-5 min, ~USD 0.30-0.60).
cd packages/toolkit
uv run pytest tests/integration/test_openclaw_serialization_repro.py -v
```

**What it counts**:

- `corrupted` = number of trace-blob occurrences of
  `genomeclaw_gene: argument \`gene\` is the placeholder string` (the
  arg-guard's failure message in [`packages/nemoclaw-plugin/src/index.ts`](../../../../packages/nemoclaw-plugin/src/index.ts)).
- `intact` = number of expected gene symbols (`CFH`, `ARMS2`,
  `HTRA1`, `ABCA4`, `USH2A`) appearing as `/v1/gene/<NAME>`
  paths in the trace blob.
- `corruption_rate = corrupted / (corrupted + intact)`.

**Acceptance gate**: `corruption_rate <= 0.2`.

The Phase 1 + Phase 3 combined bar; today's baseline is ~0.80 (7/7 in the
2026-05-23 v3 trace). The test is **expected to be RED** until Phase 3
lands a chosen Path. That's the design — the test pins the bug; the
fix turns it green.

**Auto-skip behavior**: `tests/conftest.py` already auto-skips
`live_llm` markers when `OPENAI_API_KEY` or
`GENOMECLAW_SANDBOX_IMAGE` is absent. So the new test never collects
in default CI.

---

## 1.4 SDK-bypass probe location + how to run

**File**: `/tmp/openai_responses_bypass_probe.py` (standalone Python
script; not checked in to the plan dir per the phase-1.md Files table).

**Purpose**: Bypass openclaw entirely. Call the OpenAI Responses API
directly with the openai Python SDK using a 1:1 mirror of the
`genomeclaw_gene` tool schema + the same 5-gene prompt. Capture the
raw `arguments` field as the SDK exposes it. Classify each call.

**How to run**:

```bash
pip install openai
export OPENAI_API_KEY=sk-...
python /tmp/openai_responses_bypass_probe.py > /tmp/openai_bypass_probe_output.json
```

Cost: ~1 OpenAI Responses API call against gpt-5.5 with high thinking,
~USD 0.10-0.30. (Note: the SDK accepts `effort: "high"`;
`"xhigh"` is openclaw-side language; OpenAI's published levels are
`low | medium | high`. The probe uses `high` as the conservative
ceiling.)

**Output shape** (per call):

```json
{
  "call_id": "call_xxx",
  "name": "genomeclaw_gene",
  "arguments_raw_type": "str",
  "arguments_raw_value": "{\"gene\":\"CFH\"}",
  "classification": "well_formed_json_object"
}
```

**Classification labels** the probe emits:

- `well_formed_json_object` — `arguments` is a JSON-encoded string
  whose decoded value is a dict containing the expected fields.
  Evidence the **model is innocent**; corruption (if any) is downstream
  inside openclaw.
- `placeholder_string` — `arguments` is either the literal
  `'"undefined"'` or decodes to `"undefined"`. Evidence the **model
  is emitting Symptom A directly** (or the API is mangling it before the
  SDK sees it).
- `tool_call_id_string` — `arguments` is the bare
  `call_<id>|fc_<id>` token. Evidence the **model is emitting Symptom B
  directly**.
- `invalid_json_string` — `arguments` is a string that doesn't parse
  as JSON. Catch-all for new failure shapes.
- `non_string_shape(<type>)` — the SDK exposed `arguments` as
  something other than `str` (the Responses API contract says it
  SHOULD be a string; deviation is itself a finding).

**Verdict line**: The probe prints a top-level `verdict` field that
summarises the classifications into one of: `MODEL_EMITS_CORRECT_JSON`
(corruption is downstream of the model), `MODEL_EMITS_PLACEHOLDER`
(model side), `MODEL_EMITS_TOOL_CALL_ID` (model side), `MIXED`, or
`no_function_calls_emitted`.

---

## Classification framework (operator fills in after running the artifacts)

Run order: reproducer first (establishes baseline corruption rate at the
openclaw layer); then SDK-bypass probe (establishes whether the model
emits the bad shape on its own). Then fill in one row per observed
symptom shape:

| symptom_id | intended_args (what the agent was trying to send) | received_args (what the plugin's `execute()` saw — from the reproducer's trace) | openai_raw_arguments (what the SDK-bypass probe captured directly from OpenAI) | classification |
|------------|---------------------------------------------------|-----------------------------------------------------------------------|---------------------------------------------------------------------|----------------|
| Symptom A — placeholder string in `args.gene` | `{"gene": "CFH"}` (one row per gene from the prompt) | _(fill in: `args.gene === "undefined"` if corrupted; `args.gene === "CFH"` if intact)_ | _(fill in: the raw `arguments` field from the probe's `calls[i]`)_ | _(fill in: one of `llm_output_malformed` / `openai_api_serialization_bug` / `openclaw_runtime_bug` / `model_specific_quirk`)_ |
| Symptom B — bare string body in POST | `{"pgs_id": "PGS000018", "rationale": "...", ...}` | _(fill in: the bare-string body or the `expected an object of arguments but received string` arg-guard message)_ | _(fill in: probe doesn't cover the compute tool; would need a separate probe run with the `genomeclaw_pgs_compute` schema)_ | _(fill in)_ |

### Decision rule

- If the SDK-bypass probe shows the **model emits `well_formed_json_object`
  every time**, and the reproducer shows `corruption_rate >= 0.5` at the
  plugin layer, **classification is `openclaw_runtime_bug`** -> Path U.
- If the SDK-bypass probe shows the **model emits `placeholder_string`
  or `tool_call_id_string` on its own**, **classification is
  `llm_output_malformed` or `model_specific_quirk`** -> Path D (document
  the quirk; the existing arg-guard is the right response shape).
- If the SDK-bypass probe shows **mixed shapes**, **classification is
  ambiguous**; Phase 2's cross-model bisect (Claude) disambiguates.

---

## Path recommendation prediction (BEFORE running the live artifacts)

**Predicted classification**: `model_specific_quirk` (gpt-5.5 + xhigh
thinking on multi-tool-call prompts emits the bad shape directly).

**Predicted Path**: **Path D — document the quirk** + keep the runtime
arg-guard at [`packages/nemoclaw-plugin/src/index.ts`](../../../../packages/nemoclaw-plugin/src/index.ts)
as the workaround. With a secondary Path U mention of issue
[#43305](https://github.com/openclaw/openclaw/issues/43305) (Symptom B
is highly likely the same root cause).

### Why this prediction

Three pieces of static evidence point at the model layer rather than
openclaw:

1. **Issue #43305 isolates Symptom B to the openai-responses path** —
   the same provider on the openai-completions path is fine. That
   pattern is consistent with a per-API-mode quirk, not a generic
   serialization bug. Symptom B's `call_<id>|fc_<id>` token shape is
   the EXACT shape #43305 reports leaking into a different field.
   Likely upstream cause for both: gpt-5.5 emits the tool-call ID into a
   field that should carry actual args under specific conditions
   (multi-tool-call + high thinking + Responses API).
2. **Symptom A has no openclaw-issue match** — every closely-related
   openclaw issue (#50689, #57103, #46679, #70872) is about
   string-vs-object marshalling of well-formed-JSON content, not about
   the literal token `"undefined"` appearing where a real value should
   live. The JS-coercion footgun (a missing `arguments.gene` field
   being coerced to the string `"undefined"` via
   `String(undefined)`) is a model-side artifact: it's only possible
   if the model emits the key with no value, or omits the key entirely
   and openclaw's downstream interpolation produces `"undefined"` via
   template-string coercion. Both possibilities locate the bug at the
   "model didn't fill in the args field" layer, not at the "openclaw
   mangled args between model output and plugin entry" layer.
3. **The 2026-05-23 v3 trace shows the agent INTENDED specific genes**
   (CFH/ARMS2/HTRA1 visible in the agent's pre-tool-call planning
   text), but the tool-call emission lost the value. That fits a model
   quirk where the function-call output is generated separately from
   the reasoning trace and the args field is the one that drops.

If the SDK-bypass probe disconfirms — i.e. the model DOES emit clean
`well_formed_json_object` arguments in isolation — then the prediction
flips to Path U (openclaw runtime is mangling something downstream).

### Why not Path L (local fix beyond the existing arg-guard)

The existing arg-guard already catches both symptom shapes at plugin
entry. A "more local" fix would have to recover the INTENDED args from
elsewhere in the openclaw run-state, which (a) requires openclaw API
access the plugin doesn't have, and (b) is the exact wrong layer for a
model-side quirk (the plugin would silently paper over a real model
problem instead of surfacing it). Path D's documented quirk + the
existing guard is the right shape if the model is the root cause.

---

## Verification

The Phase 1 STATIC investigation outputs are:

- This file (`findings.md`).
- The reproducer pytest test at
  [`packages/toolkit/tests/integration/test_openclaw_serialization_repro.py`](../../../../packages/toolkit/tests/integration/test_openclaw_serialization_repro.py)
  — auto-skips without `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE`.
- The SDK-bypass probe at `/tmp/openai_responses_bypass_probe.py`.
- The Phase 3 Path D skeleton at
  [`docs/reference/agent-quirks.md`](../../../reference/agent-quirks.md).

Operator next actions:

1. Run `uv run pytest tests/integration/test_openclaw_serialization_repro.py`
   with the live env vars set. Capture the corruption rate.
2. Run `python /tmp/openai_responses_bypass_probe.py > /tmp/openai_bypass_probe_output.json`.
   Capture the classification table.
3. Fill in the classification framework table above with both artifacts'
   outputs.
4. Confirm or revise the path-recommendation prediction.
5. Proceed to Phase 2 (cross-model bisect) if classification is ambiguous;
   otherwise jump straight to Phase 3 with the chosen Path.

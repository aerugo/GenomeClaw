# Agent Quirks

**Status**: Active — first quirk (Q-001) landed 2026-05-23 from
[openclaw-toolcall-serialization-investigation](../plans/completed/openclaw-toolcall-serialization-investigation/).

This document catalogues observed agent / openclaw runtime / LLM-provider
quirks that affect how GenomeClaw's nemoclaw plugin and host service
interact with the agent. Each entry is a labelled, reproducible, defanged
failure mode — not a bug-tracker substitute and not a workaround manifest;
the goal is institutional memory so future contributors recognise a
quirk on sight instead of spending hours rediscovering it.

Entries land here under three conditions:

1. The quirk is observed across at least two independent agent runs.
2. The runtime mitigation (a guard, a retry, a documented workaround) is
   stable and tested.
3. The classification (model-side / provider-side / runtime-side) is
   evidence-supported, not speculative.

---

## Quirk Index

| ID  | Title | Observed | Status | Classification |
|-----|-------|----------|--------|----------------|
| [Q-001](#quirk-q-001--openclaw-tool-call-argument-serialization-corruption) | openclaw tool-call argument-serialization corruption | 2026-05-23 (≥3 runs across two probes) | Workaround live; upstream issue drafted | `openclaw_runtime_bug` — intermittent / context-conditional |

---

## Quirk Q-001 — openclaw tool-call argument-serialization corruption

### Symptom

Under the **openai-responses** API path with **gpt-5 / gpt-5.5** + high
reasoning effort + multi-turn agent context, the plugin's `execute()`
intermittently receives corrupted tool-call arguments. Two shapes:

- **Symptom A**: required string fields arrive as the literal JavaScript
  string `"undefined"`. Observed 7/7 times for `genomeclaw_gene` lookups
  in the 2026-05-23 v3 eyesight-question trace. The agent intended specific
  HGNC symbols (CFH, ARMS2, HTRA1, …); the plugin received `args.gene === "undefined"`.
- **Symptom B**: entire `arguments` body arrives as the bare openclaw
  tool-call-ID token `"call_<id>|fc_<id>"` (a string, not an object).
  Observed 2× against `genomeclaw_pgs_compute` in the 2026-05-23
  compute-direct probe. Highly likely the same root cause as
  openclaw issue
  [#43305](https://github.com/openclaw/openclaw/issues/43305), which
  reports the same token leaking into `input[n].id` on subsequent
  Responses-API POST bodies.

### Reproduction

**Quick triage** (deterministic; no LLM cost): the b8b7954 runtime
arg-guard at [`packages/nemoclaw-plugin/src/index.ts`](../../packages/nemoclaw-plugin/src/index.ts)
emits `failedTextResult` whose text contains `placeholder string` for
Symptom A and `expected an object of arguments but received string` for
Symptom B. If you see either string in an agent trace, you've hit Q-001.

**SDK-bypass probe** (live; ~USD 0.10–0.30):

```bash
export OPENAI_API_KEY=sk-...
python /tmp/openai_responses_bypass_probe.py > /tmp/openai_bypass_probe_output.json
# Source: docs/plans/completed/openclaw-toolcall-serialization-investigation/findings.md § 1.4
```

The probe calls the OpenAI Responses API directly with a 1:1 mirror of the
`genomeclaw_gene` schema and the 5-gene reproducer prompt. **Expected
verdict**: `MODEL_EMITS_CORRECT_JSON` (5/5 well-formed
`{"gene":"<SYMBOL>"}` objects). This run is what locks the model layer
as innocent.

**Full reproducer test** (live; ~USD 0.30, ~5 min; non-deterministic):
[`packages/toolkit/tests/integration/test_openclaw_serialization_repro.py`](../../packages/toolkit/tests/integration/test_openclaw_serialization_repro.py).
Gated by `@pytest.mark.live_llm`; auto-skips without `OPENAI_API_KEY` +
`GENOMECLAW_SANDBOX_IMAGE`. Asserts the corruption rate at the openclaw
layer is ≤ 20%. Caveat: minimal-prompt + fresh-session runs **may not
reproduce** even when the bug is active in production multi-turn flows —
the bug is context-conditional.

### Classification

`openclaw_runtime_bug` — intermittent / context-conditional.

The SDK-bypass probe proves the OpenAI Responses API returns clean
well-formed JSON arguments. Anything that converts those arguments to
`"undefined"` or the call-ID token sits **inside the openclaw runtime**,
downstream of the model. The intermittence (~0% in a fresh minimal
session vs ~100% in the 2026-05-23 v3 multi-turn trace) points at
**broader-agent-state-conditional** behaviour rather than a deterministic
parser bug; the exact trigger has not been isolated.

### Workaround in place

[`packages/nemoclaw-plugin/src/index.ts`](../../packages/nemoclaw-plugin/src/index.ts)
ships `rejectIfPlaceholder()` at every plugin tool's `execute()` entry
(commit `b8b7954`). It catches both symptom shapes before any host
HTTP call goes out, returns a `failedTextResult` with a clear error
message + the offending value, and lets the agent retry with explicit
args.

The 23-test vitest suite at
[`packages/nemoclaw-plugin/tests/`](../../packages/nemoclaw-plugin/tests/)
pins the guard's behaviour for both symptom shapes; any plugin change
that breaks the guard turns those tests RED.

### Upstream tracking

- **Related closed**: openclaw
  [#43305](https://github.com/openclaw/openclaw/issues/43305) — call-ID
  token leaks into `input[n].id` on the openai-responses path. Same
  token shape; the author confirmed it's specific to the
  openai-responses code path (switching to openai-completions makes it
  disappear).
- **Filed (Symptom A + B): TBD** — operator to file using the draft body
  in
  [findings.md § Upstream issue draft](../plans/completed/openclaw-toolcall-serialization-investigation/findings.md#upstream-issue-draft-path-u-deliverable).
  Once filed, link the URL here and in the plan's work-notes.

### Detection

Two layers:

1. **Static (always-on)**: the 23-test vitest suite on
   [`packages/nemoclaw-plugin/tests/`](../../packages/nemoclaw-plugin/tests/)
   guards the `rejectIfPlaceholder` workaround. Runs in CI on every
   plugin change.
2. **Live (gated)**: the reproducer test at
   [`packages/toolkit/tests/integration/test_openclaw_serialization_repro.py`](../../packages/toolkit/tests/integration/test_openclaw_serialization_repro.py)
   exercises the full agent loop. RED today only when corruption rate
   exceeds the 20% ceiling — useful as a regression canary once the
   upstream fix lands and openclaw is bumped.

### What to do when this surfaces again

1. Don't panic — the b8b7954 guard means the host service is not
   receiving corrupted args. The agent reply will reference a "tool
   failed" message; the agent will typically retry with explicit args.
2. Capture the trace excerpt (PII-clean — gene symbols are public) and
   add it to the upstream issue thread.
3. If the corruption rate appears to spike (e.g. multiple production
   traces showing the guard catching it in a row), re-run the SDK-bypass
   probe + the reproducer test to check whether the openclaw runtime
   has regressed further OR whether a model-side change has begun
   emitting the bad shape directly (which would flip the classification).

---

## Adding a new quirk

When a future investigation closes with a Path D outcome (document the
quirk), add a new section using the Q-XYZ heading shape above. Each
quirk gets:

- An `INV-xxx` reference IF the workaround is enforced by a project
  invariant; otherwise the test path is the enforcement surface.
- A pointer to the live-gated reproducer + the static unit test that
  pins the workaround.
- The upstream issue link (Path U) OR the local-fix commit SHA (Path L).
- A clear "what to do when this surfaces again" recipe for future
  agents — concrete steps, not vague advice.

Out of scope for this doc:

- Bugs that are fixed upstream and no longer reproduce.
- Speculation about quirks that haven't been observed twice.
- Workarounds that don't have test coverage.

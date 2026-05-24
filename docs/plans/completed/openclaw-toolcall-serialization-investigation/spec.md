# Spec — Openclaw tool-call argument-serialization investigation

**Status**: Active — drafted 2026-05-23
**Created**: 2026-05-23

---

## Goal

Determine the root cause of the tool-call argument-serialization failures observed in the 2026-05-23 eyesight-question agent run (7× `genomeclaw_gene(gene="undefined")` + 2× `POST /v1/pgs/compute` with a literal `"call_xxx|fc_yyy"` string as the body), classify the failure modes, and pick a resolution path: upstream openclaw fix vs documented gpt-5.5 quirk vs further local hardening.

## Background

The agent-prs-compute-fix iteration on 2026-05-23 surfaced two correlated symptoms in the host service logs against the canonical run-dir:

### Symptom A — placeholder string arrives at tool entry

```
GET /v1/gene/undefined HTTP/1.1  404 Not Found       (×7 in one run)
GET /v1/variants/undefined HTTP/1.1  400 Bad Request  (×5 in another)
```

The agent's plugin tool `genomeclaw_gene(gene: string)` is invoked with `args.gene` arriving as the literal JavaScript value `undefined`. `encodeURIComponent(undefined)` returns the string `"undefined"`; the URL gets built that way; the host receives a request for the non-existent gene "undefined" and returns 404. The TypeBox schema declares `gene: Type.String({minLength: 1, pattern: ...})` — but the agent runtime ignores `pattern` (only enforces `minLength` + `additionalProperties`).

### Symptom B — bare-string body arrives at POST endpoint

```
POST /v1/pgs/compute  422 Unprocessable Content
req_body = "call_NPXm5cpDMDrnBR6F0JaDqfCT|fc_05bc5c3bf7af3325006a11a72eebbc81a194bec3cb499056be"
resp_body = {"detail":[{"type":"model_attributes_type","loc":["body"],...}]}
```

The agent's plugin tool `genomeclaw_pgs_compute(args: object)` calls `safePost(host, "/v1/pgs/compute", args)`. The body arrives at the host service as a literal string in the OpenAI tool-call-ID format (`call_<id>|fc_<id>`). Pydantic rejects with `model_attributes_type` (expected dict; got string).

### Why this matters

Today the symptoms are defanged by the runtime arg-guard in commit `b8b7954` — every `genomeclaw_gene("undefined")` call returns a `failedTextResult` locally before hitting the host; the agent sees a tool error + can retry. The eyesight question v4 reply demonstrates the workaround works: 15 genes queried successfully + 0 wasted `/v1/gene/undefined` calls in the v4 host log.

But the underlying bug is still there. It's burning agent turns + masking the agent's intent. In the eyesight v3 trace the agent CALLED 7 different genes for lookup; the openclaw runtime mangled all 7 args to `undefined`. The agent has no observability into "I asked for CFH, the plugin says it got undefined" — it just sees 7 failed tool calls + degrades. At scale, this is a significant quality regression.

### What we don't know

Three open questions a focused investigation can answer:

1. **Where does the corruption happen?** Three candidates:
   - The LLM (gpt-5.5) emits malformed tool-call args.
   - OpenAI's Responses API serialization mangles them between LLM output + the openclaw runtime.
   - openclaw's tool-arg unpacker (between the Responses API response + the plugin's `execute()`) loses the JSON object shape.
2. **Is it model-specific?** Does Claude / Anthropic via openclaw exhibit the same pattern, or is it gpt-5.5-specific?
3. **Is there a workaround that fully fixes it (vs. defangs)?** The current runtime arg-guard catches the symptom; can we ALSO recover the intended arg (e.g. by parsing the tool-call ID + looking up the original args from elsewhere in the run-state)?

## Acceptance Criteria

- [ ] **AC1**: Reproducible test case. A documented sequence (specific prompt + agent harness invocation) that triggers Symptom A and/or B reliably (≥80% of runs).
- [ ] **AC2**: Failure mode classified. The investigation labels each symptom against one of: `llm_output_malformed`, `openai_api_serialization_bug`, `openclaw_runtime_bug`, `model_specific_quirk`. With evidence (e.g. raw OpenAI Responses API response payload, openclaw internal log dump).
- [ ] **AC3**: Cross-model bisect. The reproducer is run against at least ONE non-OpenAI model (Claude via openclaw if the test harness supports it) to determine whether it's model-side or runtime-side.
- [ ] **AC4**: Decision recorded. Based on the classification, the plan picks ONE of three paths:
  - **Path U (upstream)**: file an openclaw GitHub issue / PR with the reproducer + classification.
  - **Path D (document + harden)**: it's a model-specific quirk gpt-5.5 has at this prompt-shape; document in `docs/reference/agent-quirks.md` + (optionally) tighten the existing arg-guard's error message to hint at the upstream cause so the agent can recover.
  - **Path L (local fix)**: openclaw exposes an injection point or workaround we can use without upstream change; ship the local fix.
- [ ] **AC5**: No regressions to the runtime arg-guard (commit `b8b7954`) — its 23 vitest + 5 tool-types coverage stays green.
- [ ] **AC6**: Investigation outcome documented in `docs/reference/agent-quirks.md` (Path D) OR linked to an upstream issue URL (Path U) OR shipped as a local fix with new tests (Path L).

## Applicable Invariants

- **INV-P001** (Privacy Default) — the investigation MUST NOT send user genomic data through any added tracing surface. Use the synthetic-fixture eyesight prompt or similar; the canonical run-dir's CURRENT can be repointed at a fresh empty-store fixture for safety.
- **INV-A001 / A002 / A003** — orthogonal; this is plumbing investigation, not agent-behavior change.

## Proposed New Invariants

None. This is investigation; the eventual fix (Path U/D/L) determines if any code-level invariant is added (probably not — it's an external-system reliability problem, not a GenomeClaw constraint).

## Out of Scope

- **Broad openclaw runtime refactor** — even if Path U is right, this plan files an issue / PR; it doesn't replace openclaw.
- **Multi-LLM-provider matrix bisect** — Path C tests against one alternative provider (Claude). Going wider (Gemini, local models) is overkill for the spike.
- **Fundamentally new arg-passing protocol** — Path L's "local fix" must be additive (cheap workaround), not a rewrite of how plugins receive args.
- **Sandbox image rebuild for the eventual fix** — the local fix or hardening drops into the existing plugin; image rebuild happens in the natural commit cycle.

## Privacy & Safety Considerations

### What the investigation touches

- **Verbose openclaw tracing**: capturing raw LLM tool-call output for the reproducer. The reproducer prompt is synthetic (no user data); the trace doesn't carry user genomic content.
- **OpenAI API observability**: if we use the Responses API directly to inspect what OpenAI sends back (bypassing openclaw's parser), the API call IS the existing agent-provider egress. Same destination, transport, payload as the regular agent run.
- **Cross-model test**: a single Claude/Anthropic call via openclaw against the same synthetic reproducer. Costs ~$0.50; same egress class as existing live tests.

### Net privacy posture

No new egress surfaces, no new user-data flow. The investigation runs against synthetic prompts; the canonical run-dir is read-only.

### `privacy-safety-reviewer`

Not required for this plan (no egress surface change). If the investigation surfaces something unexpected (e.g. openclaw is logging tool-call args to a path we didn't know about), trigger a review at that point.

## Open Questions

1. **Where does openclaw expose its tool-arg unpacker so we can instrument it?** Phase 1 design pass investigates. Likely candidates: a debug env var, a custom logger sink, or patching the SDK module at test time.
2. **Does gpt-5.5's "xhigh" thinking mode change the tool-call output shape vs. low thinking?** Worth testing; high-thinking mode might be doing something different with arg serialization.
3. **Is this a known issue in the openclaw GitHub issue tracker?** Phase 1 step 1.1 should grep the openclaw repo for "tool call arguments" / "undefined" / "serialization" before investing in original reproduction work.

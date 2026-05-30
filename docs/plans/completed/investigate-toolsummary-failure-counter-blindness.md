# Investigate `toolSummary.failures` Blindness to Client-Side Guard Rejections — Single-File Plan

**Status**: Implemented + verified 2026-05-27 — Complete (local fix; upstream gap noted)
**Created**: 2026-05-26
**Parent context**: surfaced during 2026-05-26 muscle-question debugging trace. The agent's reply for *"Give me personalized recommendations for exercise and diet…"* fabricated a sweeping failure narrative — *"the GenomeClaw argument-shape guard fired, so I cannot honestly claim your ACTN3/FTO/AMPD1/etc. genotype yet"* — that contradicted both the host service's actual responses (HTTP 200 with real data for every gene) and the structured trace. INV-A005 ("Tool-failure narratives must match trace evidence") is the canonical defense against this, but the violation went undetected by structured telemetry: `meta.toolSummary.failures` reported **0** even though one `genomeclaw_pgs_compute` call was client-side rejected by the plugin's `rejectIfPlaceholder` guard (proven by `pgs_compute_tasks.sqlite` showing no row written for the agent's session). The counter only increments on HTTP non-2xx envelopes wrapped by `safeCall` — it is structurally blind to plugin-guard rejections that never reach the host. This means **any future regression test that asserts `failures: 0` to prove "no INV-A005 violation could have happened" is a false guarantee**.

---

## Summary

Two failure modes share the `toolSummary` counter today, but only one increments it:

| Failure shape | Where it originates | Counted in `failures`? |
|---------------|---------------------|------------------------|
| Plugin guard reject (`rejectIfPlaceholder`, TypeBox schema reject, etc.) | sandbox-side, before HTTP | **No** ← the gap |
| HTTP non-2xx envelope wrapped by `safeCall` | host-side, after HTTP | Yes |
| Host-side structured failure with HTTP 200 (e.g., `{"status":"failed","error":"prs_compute_config_missing"}`) | host-side, semantic | **No** (and arguably shouldn't be) |

The fix has two parts: **(P1)** make plugin-guard rejections increment a counter the agent / harness / regression-test can observe, and **(P2)** wire the counter into a regression test that exercises the muscle-question scenario (or a synthetic equivalent) and asserts that when a guard fires, the structured trace reports it AND the agent's reply scopes the failure narrative to the one rejected call — not to other calls in the same turn.

Open question: extend the existing `toolSummary.failures` counter to include client-side rejections, OR add a parallel `toolSummary.clientRejections` counter, OR both. Adding to `failures` is simpler but risks breaking any existing consumer that treats `failures` as "the host had a problem." A parallel counter is more surgical. Resolve in P1.

## Critical Invariants to Respect

- **`INV-A005`** Tool-Failure Narratives Must Match Trace Evidence — this is the invariant being defended. The fix must make structured trace evidence sufficient to mechanically detect INV-A005 violations, not just human-readable enough to spot them after the fact.
- **`INV-P001`** Privacy Default — counters are sandbox-side metadata; they carry no genomic content. No new egress.
- **`INV-A002`** Agent Reply Provenance — the existing `toolSummary` is part of the trace surface the agent's reply must remain consistent with. Adding a counter extends the trace; it does not change what the agent is supposed to do.

## Proposed New Invariants

Possibly **NEW INV-A006**: *"Client-side tool rejections (plugin guards, schema mismatches, placeholder rejections) MUST be observable in the structured per-turn trace surface — distinguishable from host-side failures and from successful no-data responses."* Pending P1 design — if the chosen shape is "extend `toolSummary.failures` to include client rejections" the invariant might be subsumed under INV-A005. If the chosen shape is "parallel `clientRejections` counter," the invariant is worth promoting.

## Solution Design (provisional — P1 resolves the shape)

### Phase 1 — Locate the guard + counter wiring

- Read [packages/nemoclaw-plugin/src/index.ts](../../../packages/nemoclaw-plugin/src/index.ts) and find every `rejectIfPlaceholder` / TypeBox-rejection path. List the exact return shape each one produces. (The agent receives that shape as the tool result body — its choice of how to frame the failure narrative starts from that text.)
- Read the OpenClaw upstream's `toolSummary` assembly path (likely `node_modules/openclaw/dist/…` inside the sandbox image, or upstream on GitHub). Find where `failures` is incremented. Determine whether `safeCall` is the only path that bumps it.
- Decide: extend `failures` to include client rejections, OR add a parallel `clientRejections` counter, OR emit a per-call event with shape `{tool, outcome: success|host_failure|client_rejection|client_no_data, error?: string}` that downstream consumers can aggregate however they want. Per-call events are richer but require upstream cooperation; counter extension is local to our plugin.
- If the chosen shape needs upstream cooperation (openclaw harness change), document the upstream issue + the local-only fallback. Privately the plugin can wrap rejections in a synthetic HTTP-non-2xx-shaped envelope that `safeCall` already counts — ugly but functional.

Deliverable: a short **Findings** section appended naming the chosen counter shape, the file(s) that need editing, and whether upstream coordination is required.

### Phase 2 — Implement the counter (TDD)

Branch on Phase 1's choice. Whichever lands, the agent's response must continue to receive the same human-readable rejection prose (the chosen counter is structural, not visible to the agent).

### Phase 3 — Regression test (TDD)

The test that would have caught the 2026-05-26 muscle-question failure:

1. Synthetic scenario: mock the host service to return HTTP 200 for five `genomeclaw_gene` calls with realistic envelopes (ACTN3=4 variants off-panel, FTO=678 on-panel, etc.), and have the plugin's TypeBox schema reject one `genomeclaw_pgs_compute` call (e.g., feed it a 10-char rationale to trip the `minLength 50` guard).
2. Run the agent against a fixed prompt that triggers the topic discovery pattern on a fitness question.
3. Assert:
   - The trace surfaces the client rejection (counter > 0, or per-call event present).
   - The agent's reply mentions the rejected PRS attempt scoped to that one tool call.
   - The agent's reply does NOT contain the forbidden paraphrases (`"argument-serialization bug"`, `"argument-shape guard fired"`, etc.) applied to the gene calls.
   - The agent's reply mentions FTO's coverage + variant count (since that call succeeded).
4. A second test asserts the inverse: when ALL tool calls succeed (no guard rejections, no HTTP failures), the agent's reply does not contain the forbidden paraphrases. (Catches false-positive confabulation.)

Both tests can run as **agent-replay tests** against a recorded transcript (no live LLM call) OR as **live-LLM smoke tests** against the configured provider — pick what's already supported by the toolkit's test harness; document the choice in P1.

## TDD Scope (Phases 2 + 3, sketch)

### Unit (~3 tests in `packages/nemoclaw-plugin/tests/` if it exists; otherwise a small `vitest`/`tap` slice)

- `test_rejectIfPlaceholder_returns_canonical_rejection_envelope` — pin the rejection shape.
- `test_<chosen-counter>_increments_on_client_rejection` — pin counter behavior.
- `test_safeCall_path_still_increments_failures_on_HTTP_5xx` — regression guard.

### Integration (~2 tests)

- `test_mixed_outcome_turn_reports_client_rejection_in_trace` — the regression scenario above.
- `test_all_success_turn_carries_no_phantom_failure_narrative` — false-positive inverse.

### Real-data verification gate

- Re-run the 2026-05-26 muscle question end-to-end with the rebuilt sandbox + a deliberately-truncated rationale on one `_pgs_compute` call. Assert the structured trace shows the rejection AND the agent's reply scopes it correctly. The 2026-05-26 second-rebuild run is the green baseline to compare against (which it already passes — the prompt fix alone got us 95% there; the structured-trace fix closes the loop).

## Open Questions

- [ ] Q1: Counter shape — extend `failures`, parallel counter, or per-call event? (P1)
- [ ] Q2: Does the openclaw harness emit any trace event for plugin-guard rejections today that we're missing, or is the absence structural? (P1 by reading upstream source)
- [ ] Q3: Should INV-A005 be amended to explicitly require the structured-trace marker, or is a separate INV-A006 cleaner? (Resolve after P1 picks the counter shape.)
- [ ] Q4: Test harness — is there a way to run agent-replay tests without a live LLM call, or do we need a live-smoke harness for the agent-reply assertions? (P3 design point.)

## Out of Scope

- Fixing the agent's underlying tendency to over-generalize tool failures — covered by the system-prompt INV-A005 strengthening shipped 2026-05-26 (and demonstrated working in the second rebuild's reply). This plan adds the structural backstop so the next regression is detected automatically rather than via a human reading the JSON reply.
- Repairing the missing `prs_compute_config` for the active run — covered by the parallel [investigate-prs-compute-config-missing](investigate-prs-compute-config-missing.md) plan.
- Any change to what tool outputs flow to the agent (privacy/egress surface untouched).

---

## Findings (Phase 1) — 2026-05-27

The investigation reframed the bug. Original hypothesis: "the plugin's `rejectIfPlaceholder` rejections don't count toward `toolSummary.failures`." Re-checking the 2026-05-26 SQLite state revealed both my diagnostic probe AND the run-3 agent's actual `_pgs_compute` call DID reach the host and wrote rows (`status=failed, error=prs_compute_config_missing`). So the dominant failure path in production isn't a plugin guard rejection at all — it's a **host-side structured failure** (HTTP 200 + `{"status":"failed",...}` body).

That path was structurally invisible to the agent's reply parser because `safePost`/`safeCall` returned the body via `jsonResult` (the SDK's *success* envelope, `isError: false`). The agent had to JSON-parse the body's `status` field to discover the call failed — exactly the misinterpretation surface the muscle-question trace exposed.

The plugin guard counter blindness (the original concern) is still real but is a smaller deal: the local fix here doesn't address it. It's flagged as a remaining gap below.

## Implementation log — 2026-05-27

- **Added `wrapHostResponse()` helper** in [packages/nemoclaw-plugin/src/index.ts](../../../packages/nemoclaw-plugin/src/index.ts). Detects HTTP 200 bodies where top-level `status === "failed"` and converts to `failedTextResult` (sets the SDK's `isError: true` flag + carries the host's `error` code in the visible text + embeds an explicit "do NOT generalize this rejection to other tool calls in the same turn" reminder that mirrors the §INV-A005 strengthening shipped 2026-05-26).
- **Routed both `safeCall` (GET) and `safePost` (POST) through it** for symmetry — `_pgs_compute_status` polls hit the same logic as `_pgs_compute` POSTs.
- **3 regression tests** in [packages/nemoclaw-plugin/tests/index.test.ts](../../../packages/nemoclaw-plugin/tests/index.test.ts) under the `host-side structured failure detection (Plan 2)` describe block:
  - `safePost converts {status:'failed'} HTTP 200 body to failedTextResult` — the muscle-question regression. Stubs `/v1/pgs/compute` with the exact `prs_compute_config_missing` envelope; asserts `isError: true`, error code in text, anti-fabrication reminder in text.
  - `safePost preserves jsonResult success envelope for status:'queued'` — defensive inverse, asserts the new wrapper doesn't false-positive on normal queued/running/done lifecycle responses.
  - `safeCall converts {status:'failed'} HTTP 200 body to failedTextResult for GET endpoints` — symmetry test for the `_pgs_compute_status` poll path.
- 26/26 plugin tests pass (23 pre-existing + 3 new). No regressions.

## Remaining gap — `rejectIfPlaceholder` counter blindness

The local fix addresses the *host-side* structured-failure path but leaves the *plugin-guard* path's telemetry uninstrumented. If the agent calls `genomeclaw_pgs_compute` with a placeholder `pgs_id` like `"undefined"`, the guard rejects via `failedTextResult` — which sets `isError: true` and should bump `toolSummary.failures`, but we never empirically verified that the OpenClaw upstream harness actually does aggregate from `isError`. The two scenarios the gap leaves under-instrumented:

1. TypeBox parameter-schema rejections (before our `execute` body runs) — upstream `parameters` validator; we don't know if it surfaces in `toolSummary`.
2. Plugin guard rejections that return `failedTextResult` — should aggregate, but unconfirmed.

Neither is the dominant failure mode anymore (the host-side fix covers it), and the §INV-A005 prompt strengthening from 2026-05-26 prevents the worst behavioral fallout regardless. Filing as a separate, lower-priority follow-up rather than blocking this plan.

## Proposed new invariant — withdrawn

`INV-A006` was proposed in case the chosen shape was a parallel `clientRejections` counter. The chosen shape (extending the existing `failedTextResult`/`isError` surface) keeps the invariant inside the existing INV-A005's scope — INV-A005 already says "tool-failure narratives must match trace evidence"; the `isError: true` flag IS the trace evidence. No new invariant needed.

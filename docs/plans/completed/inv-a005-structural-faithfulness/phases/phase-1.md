# Phase 1: Plugin Source — Structured Failure Envelopes

**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Change three failure-path helpers in [packages/nemoclaw-plugin/src/index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts) to return **structured envelopes** with an `error_type` discriminator instead of prose strings. The prose moves to an `advisory` field. Update the plugin's TypeScript unit tests accordingly.

## Scope Boundaries

- **In scope**:
  - `rejectIfPlaceholder` (lines 297–333) → returns `ToolFailureEnvelope` with `error_type: "placeholder_rejected"`.
  - `wrapHostResponse` (lines 220–244) → returns `ToolFailureEnvelope` with `error_type: "host_failure"` when wrapping a status=failed envelope.
  - `safeCall` / `safePost` catch blocks (lines 185–197, 254–266) → return `ToolFailureEnvelope` with `error_type: "network_error"` or `"http_error"` depending on whether the caught Error message matches the HTTP-error pattern.
  - New `ToolFailureEnvelope` discriminated-union type.
  - Updated [packages/nemoclaw-plugin/tests/index.test.ts](../../../../../packages/nemoclaw-plugin/tests/index.test.ts) assertions.
- **Out of scope**:
  - Agent prompt edits (Phase 2).
  - Toolkit-Python-side test rewrites (Phase 3).
  - LLM-judge harness (Phase 4).
  - Success-path envelopes (already structured).

## Invariants Enforced in This Phase

- **NEW INV-A006** (proposed, formally promoted in Phase 3): the type-system shape of the structured envelope IS the invariant's source of truth. Phase 1 lands the shape; Phase 3 promotes the rule + adds the discovery test.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases** (TypeScript, under [packages/nemoclaw-plugin/tests/index.test.ts](../../../../../packages/nemoclaw-plugin/tests/index.test.ts)):

1. `test_rejectIfPlaceholder_returns_structured_envelope` — assert the return value has `status === "failed"`, `error_type === "placeholder_rejected"`, plus structured `arg_name` and `value` fields. Verify `advisory` carries the human-readable text.
2. `test_wrapHostResponse_returns_host_failure_envelope` — when wrapping a `status: "failed"` host envelope, assert the return has `error_type === "host_failure"`, plus `http_path`, `host_status`, `host_error` fields.
3. `test_safeCall_catch_returns_network_error_or_http_error` — feed a `safeCall` invocation that triggers `Failed to connect`; assert `error_type === "network_error"`. Feed one that triggers `genomeclaw-service ... -> HTTP 503`; assert `error_type === "http_error"` with structured `http_status` field.

Run the tests; expect failures because the current functions return bare prose strings, not structured envelopes.

### Step 1.2 — GREEN: Minimal Implementation

1. Add `ToolFailureEnvelope` type:
   ```typescript
   type ToolFailureEnvelope =
     | { status: "failed"; error_type: "placeholder_rejected"; arg_name: string; value: string; advisory: string }
     | { status: "failed"; error_type: "host_failure"; http_path: string; host_status: string; host_error: string; advisory: string }
     | { status: "failed"; error_type: "network_error"; raw_error: string; advisory: string }
     | { status: "failed"; error_type: "http_error"; http_path: string; http_status: number; raw_error: string; advisory: string };
   ```
2. Update `rejectIfPlaceholder` to construct + return the `placeholder_rejected` envelope; preserve the existing prose as the `advisory` value.
3. Update `wrapHostResponse` to detect `status: "failed"` host envelopes and return the `host_failure` envelope; pass-through success envelopes unchanged.
4. Update `safeCall` / `safePost` catch blocks: classify caught error message into `network_error` vs `http_error` (regex: `genomeclaw-service .* -> HTTP \d{3}` → http_error else network_error), construct envelope accordingly. `failedTextResult` helper signature stays compatible — internally now wraps the envelope.

### Step 1.3 — REFACTOR

- Tighten the discriminated-union types (use `as const` on enum strings).
- Audit any other callsite in `index.ts` that returns failure prose without going through the three helpers; route through the envelope shape.
- Re-run `npm run typecheck` + `npm run build` + `npm test`. All green.

---

## Implementation Details

### `error_type` Enum Values

- `"placeholder_rejected"` — `rejectIfPlaceholder` fired (placeholder string in argument)
- `"host_failure"` — `wrapHostResponse` saw `status: "failed"` from the host
- `"network_error"` — `safeCall` / `safePost` caught a network failure (`Failed to connect`, `fetch failed`)
- `"http_error"` — `safeCall` / `safePost` caught a non-2xx HTTP response

Future tool wrappers add new enum values; Phase 3's `INV-A006` discovery test asserts every wrapper's failure path uses one of these (or a documented new enum value).

### Backward Compatibility

- The `advisory` field carries the same human-readable text the agent saw under the old prose-return contract. Sandbox images built from the parent plan's Phase 1+2 (with the old prompt + tests) can still read the `advisory` field and behave as before.
- New sandbox images (Phase 2 onwards) read `error_type` as the source of truth.

### Edge Cases

- **`status: "ok"` host responses** — pass-through unchanged.
- **Unknown error types** — keep the catch-block fallback that emits `error_type: "unknown"` (or omit and let TypeScript narrow refuse to compile) — design choice to make during RED.
- **Existing tests that substring-match the prose** — update to check `error_type` instead.

### Privacy / Egress Notes

- No new egress. Same payloads cross the same boundaries; just shape changes.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/src/index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts) | MODIFY | Add `ToolFailureEnvelope` type + rewrite three failure-path helpers. |
| [packages/nemoclaw-plugin/tests/index.test.ts](../../../../../packages/nemoclaw-plugin/tests/index.test.ts) | MODIFY | Update assertions from prose substrings to `error_type` field checks. |

---

## Verification

```bash
cd packages/nemoclaw-plugin
npm run typecheck
npm run build
npm test
```

For end-to-end verification (Phase 3+):

```bash
./scripts/sandbox-up.sh --rebuild  # rebuild image with new plugin
# Send the AC8 muscle question via the docker-exec pattern in CLAUDE.md.
# Inspect captured trace's tool-result envelopes — should now carry `error_type` not prose-only.
```

---

## Completion Criteria

- [x] All four new envelope tests pass (RED → GREEN visible — RED step recorded in work-notes).
- [x] All previously-passing `index.test.ts` tests still pass under updated assertions (27 pre-existing tests, 6 of which were rewritten to use `parseFailureEnvelope`).
- [x] `npm run typecheck` clean.
- [x] `npm run build` clean.
- [x] No callsite in `index.ts` returns a bare prose failure string outside the envelope shape. All three failure paths (`rejectIfPlaceholder` × 3 branches, `wrapHostResponse`, `safeCall`/`safePost` catches) go through `failureEnvelopeResult`.
- [x] `work-notes.md` updated with RED output, decisions, and final state.
- [x] Phase 1 row in `development-plan.md` progress table set to **Complete** (next edit).

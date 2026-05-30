# Phase 3: Extend Plugin Envelopes + Update INV-A006 Discovery

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Extend the plugin's `ToolFailureEnvelope` discriminated-union arms (and the success-path `jsonResult` payload pass-through) so the agent receives the rich diagnostic data Phase 2 added to the host-service responses. Verify the plugin doesn't truncate or pre-summarize. Update the `INV-A006` discovery test to require the new fields where Phase 2 made them mandatory. Decide on `INV-D010` promotion.

## Scope Boundaries

- **In scope**:
  - `ToolFailureEnvelope` TypeScript types in [packages/nemoclaw-plugin/src/index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts).
  - `wrapHostResponse` + `safeCall`/`safePost` catch handlers — verify they forward rich fields.
  - Plugin-side unit tests in [packages/nemoclaw-plugin/tests/index.test.ts](../../../../../packages/nemoclaw-plugin/tests/index.test.ts).
  - `INV-A006` discovery test extension at [packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py](../../../../../packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py).
- **Out of scope**:
  - Prompt edits (Phase 4).
  - LLM-judge harness (Phase 5).
  - Removing the v1.22 walker (Phase 5).

## Invariants Enforced in This Phase

- **INV-A006** Plugin Tool-Result Returns Structured Envelopes — extended.
- **NEW INV-D010** (provisional, formally promoted in this phase if scope is coherent): Tool wrappers forward host diagnostic context without truncation.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

**Test cases**:

1. `host_failure envelope carries diagnostic_trace` — feed `wrapHostResponse` a host response with `status: "failed"` AND `diagnostic_trace: {stage: "...", command: "...", ...}`; assert the resulting envelope's `host_failure` arm has a `diagnostic_trace` field populated.
2. `success path jsonResult preserves full host payload` — feed `wrapHostResponse` a success body with new metadata fields (`match_rate`, `compute_metadata`, etc.); assert the envelope's `text` field carries them all (parseable JSON, full data).
3. `network_error / http_error envelopes preserve all caught error context` — for catches, the envelope's existing fields (`raw_error`, `http_path`) are unchanged; just verify nothing's truncated.
4. `INV-A006 discovery test extension` — assert the `ToolFailureEnvelope` discriminated union now includes optional `diagnostic_trace: ToolDiagnosticTrace` field on the `host_failure` arm.

Run RED. Confirm tests fail because:
- The envelope arms don't carry `diagnostic_trace` yet.
- The discovery test's new assertion doesn't find the field declaration.

### Step 3.2 — GREEN: Extend Types + Forwarding Code

1. Extend the `ToolFailureEnvelope` discriminated-union in `index.ts`:

```typescript
type ToolDiagnosticTrace = {
  stage: string;
  command?: string;
  partial_log?: string;
  upstream_cause?: string;
  related_paths?: string[];
};

type ToolFailureEnvelope =
  | { status: "failed"; error_type: "placeholder_rejected"; tool_name: string; arg_name: string; value: unknown; advisory: string }
  | { status: "failed"; error_type: "host_failure"; http_path: string; host_status: string; host_error: string; diagnostic_trace?: ToolDiagnosticTrace; advisory: string }
  | { status: "failed"; error_type: "network_error"; http_path: string; raw_error: string; advisory: string }
  | { status: "failed"; error_type: "http_error"; http_path: string; http_status: number; raw_error: string; advisory: string };
```

(Adapt per actual Phase-2 deliverables — fields may differ.)

2. Update `wrapHostResponse` to forward the host's `diagnostic_trace` field into the `host_failure` envelope.

3. Update success-path `jsonResult(payload)` — already forwards the full payload via `JSON.stringify`, but verify no truncation has crept in.

4. Re-run RED → GREEN.

### Step 3.3 — REFACTOR

- Tighten TypeScript types (use `as const` discriminators, narrow optionals).
- Re-run plugin-side unit tests + the Python-side `INV-A006` discovery test.
- Sanity-check `INV-A005`'s structural walker is still passing (it parses envelopes by `status: "failed"` + `error_type`; nothing in this phase breaks it).

### Step 3.4 — Decide on INV-D010 promotion

If the host-service + plugin discipline feels coherent enough as a project-wide rule:

- Write `INV-D010` rule text: *"Tool wrappers MUST forward host service diagnostic context to the agent without truncation or pre-summarization. The agent decides what's relevant."*
- Add an entry to `INVARIANTS.md` under the `INV-D*` (Data) category (or `INV-A*` if more cognition-adjacent).
- Reference Phase 2's host-service shape as the source-of-truth + Phase 3's plugin types as the forwarder.
- Update Invariant Index + version bump.

If scope feels too narrow (only `pgs_compute` got extended; other tools didn't change):

- Defer promotion to a follow-up plan once more tools have rich-detail extensions.

---

## Implementation Details

### Backward Compatibility

- All new envelope fields are `optional` (`?` in TS). Older host-service deployments that don't populate them produce envelopes with the field absent — agent sees no `diagnostic_trace`, falls back to the high-level error.

### Plugin-side Unit Test Updates

- Existing `INV-A006` envelope-shape tests (in `index.test.ts`) check the four discriminator arms. Add new assertions for the extended fields where applicable.
- Use `parseFailureEnvelope` helper already in the test file — extend its `FailureEnvelope` interface to include the new optional fields.

### Edge Cases

- **Host returns `diagnostic_trace: null`** (no rich context captured) — envelope's `diagnostic_trace` is `undefined`; agent reads as "no rich context, use high-level error."
- **Host service older than Phase 2** — produces minimal envelopes; plugin still forwards correctly (no rich fields = no rich fields downstream).

### Privacy / Egress Notes

- No new egress. Same agent destination; just more data in the envelope.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/src/index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts) | MODIFY | Extend `ToolFailureEnvelope`; verify forwarding. |
| [packages/nemoclaw-plugin/tests/index.test.ts](../../../../../packages/nemoclaw-plugin/tests/index.test.ts) | MODIFY | Add envelope-shape tests for new fields. |
| [packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py](../../../../../packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py) | MODIFY | Extend discovery test if scope warrants. |
| [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) | MODIFY (conditional) | Promote `INV-D010` if Phase 3 review decides scope is coherent. |

---

## Verification

```bash
cd packages/nemoclaw-plugin
npm run typecheck
npm run build
npm test

cd ../toolkit
uv run pytest tests/invariants/test_invA006_plugin_returns_structured_envelopes.py -xvs
uv run pytest tests/invariants/ -x  # full suite check
```

---

## Completion Criteria

- [ ] `ToolFailureEnvelope` arms extended with optional rich-detail fields (per Phase 2 audit).
- [ ] New plugin-side envelope-shape tests pass.
- [ ] `INV-A006` discovery test still passes (and tightened if Phase 3 scope warrants).
- [ ] `npm run typecheck` + `npm run build` + `npm test` all clean.
- [ ] `INV-D010` promotion decided (promoted to INVARIANTS.md OR explicitly deferred to follow-up).
- [ ] `work-notes.md` updated.
- [ ] Phase 3 row in `development-plan.md` progress table set to **Complete**.

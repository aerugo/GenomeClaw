# Phase 2: TypeBox Schema Update

**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Mirror the new Pydantic fields (`calibration_status`, `decline_reason`) in the nemoclaw-plugin's TypeBox schemas so the agent has machine-readable knowledge of the decline taxonomy. Phase 1 left two INV-A004 cross-language diff tests in a designed-RED state; this phase turns them GREEN.

## Scope Boundaries

- **In scope**: `packages/nemoclaw-plugin/src/index.ts` TypeBox additions + tool description updates for `genomeclaw_pgs_list` and `genomeclaw_pgs_get`; TypeScript build + typecheck pass.
- **Out of scope**: Agent system-prompt amendment (Phase 3); changes to host-side Pydantic models (Phase 1 territory); changes to the plugin's parameter (input) schemas — these continue to mirror only request bodies.

## Invariants Enforced in This Phase

- **NEW INV-A004**: `test_invA004_decline_taxonomy_traverse_calibration_status` and `test_invA004_decline_taxonomy_traverse_decline_reason` (already written in Phase 1) turn GREEN once `calibration_status: Type.Union([...])` and `decline_reason: Type.Union([...])` appear in `index.ts` with the full set of enum literals.

---

## Design

The plugin currently declares **parameter** (input) schemas only — responses are forwarded verbatim via `jsonResult(payload)`. To satisfy the cross-language diff test and to give the agent's model a concrete view of the response shape, this phase adds two response-shape TypeBox schemas as documentation artefacts:

- `PgsListRowResponseSchema` — mirrors the Pydantic `PgsListRow` (7 fields including the two new ones).
- `PgsRowResponseSchema` — mirrors the Pydantic `PgsRowResponse` (12 fields including the two new ones).

The schemas are exported but not consumed by the runtime — they exist so the TypeScript compiler validates the shape across edits and so the cross-language diff test finds the literal sets. A follow-up plan can adopt them for runtime validation if the team wants to type-check incoming HTTP responses; that is not in scope here.

### TypeBox unions for the new fields

```typescript
const CalibrationStatus = Type.Union([
  Type.Literal("clean"),
  Type.Literal("warning"),
  Type.Literal("decline"),
]);

const DeclineReason = Type.Union([
  Type.Literal("population_transferability_insufficient"),
  Type.Literal("pgs_catalog_tier_insufficient"),
  Type.Literal("phenotype_heterogeneous"),
  Type.Literal("variant_overlap_insufficient"),
  Type.Literal("ancestry_calibration_uncertain"),
]);
```

Inside both response schemas, the fields are declared:

```typescript
calibration_status: Type.Union([
  Type.Literal("clean"),
  Type.Literal("warning"),
  Type.Literal("decline"),
  Type.Null(),
]),
decline_reason: Type.Union([
  Type.Literal("population_transferability_insufficient"),
  ... // four more
  Type.Null(),
]),
```

The Phase 1 invariant test's `_extract_typebox_literals_for_field` regex matches the property assignment + extracts the string literals from the union; `Type.Null()` arms are ignored. The Python side compares only the string-literal values, which match Python's enum `.value`s exactly.

### Tool description updates

The agent's LLM sees the tool descriptions; updating them tells the agent what to expect:

- `genomeclaw_pgs_list` — append: `"calibration_status (one of 'clean' | 'warning' | 'decline' | null)"` and `"decline_reason (snake_case structural reason or null)"`.
- `genomeclaw_pgs_get` — same additions, plus a mandatory sentence: `"If calibration_status is 'decline', do NOT present this PGS as a finding — surface the decline_reason instead."`

The mandatory sentence on `pgs_get` is the agent-facing reinforcement; the system-prompt § 6 amendment in Phase 3 is the broader binding rule.

---

## TDD Steps

### Step 2.1 — RED: Confirm existing failures

The two Phase 1 invariant tests already exist and are RED. Run them once before implementation to confirm:

```bash
cd packages/toolkit && uv run pytest tests/invariants/test_invA004_decline_taxonomy_traverse.py -v
```

Expected output (verbatim from Phase 1's RED state):
```
INV-A004 violation for `calibration_status`:
  Python enum values: ['clean', 'decline', 'warning']
  TypeBox literals:   []
```

No new tests to write in Phase 2. The Phase 1 contract is the entire Phase 2 contract.

### Step 2.2 — GREEN: Add TypeBox schemas + description updates

**Files affected**:

- `packages/nemoclaw-plugin/src/index.ts` — add `CalibrationStatus` and `DeclineReason` TypeBox unions; add `PgsListRowResponseSchema` and `PgsRowResponseSchema` TypeBox objects; amend `genomeclaw_pgs_list` and `genomeclaw_pgs_get` tool descriptions.

After the changes:
- `uv run pytest packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py -v` returns 2 PASSED.
- `cd packages/nemoclaw-plugin && npm run typecheck` returns no errors.
- `cd packages/nemoclaw-plugin && npm run test` passes (no plugin-test regressions).

### Step 2.3 — REFACTOR

- Verify the TypeBox schemas are exported (or marked as intentional-internal documentation) and the file still type-checks.
- Verify the description amendments read naturally — the agent will parse them as English text, not structured data.
- Re-run the toolkit full-suite + plugin test suite to catch any cross-package regression.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | Add TypeBox enums + response schemas; amend two tool descriptions |

---

## Verification

```bash
# INV-A004 tests should turn GREEN
cd /Users/hugi/GitRepos/GenomeClaw/packages/toolkit
uv run pytest tests/invariants/test_invA004_decline_taxonomy_traverse.py -v

# Plugin typecheck + tests
cd /Users/hugi/GitRepos/GenomeClaw/packages/nemoclaw-plugin
npm run typecheck
npm run test

# Cross-package regression
cd /Users/hugi/GitRepos/GenomeClaw/packages/toolkit
uv run pytest tests/ -q
```

---

## Completion Criteria

- [ ] Both INV-A004 invariant tests pass
- [ ] `npm run typecheck` in `packages/nemoclaw-plugin` returns no new errors
- [ ] `npm run test` in `packages/nemoclaw-plugin` passes
- [ ] Tool descriptions for `genomeclaw_pgs_list` and `genomeclaw_pgs_get` mention `calibration_status` and `decline_reason`
- [ ] `work-notes.md` updated with the GREEN test output and any cross-language schema decisions
- [ ] Phase 2 status updated to "Complete" in `development-plan.md`
- [ ] _(Forward note — applies to final phase, phase-3.md)_ Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

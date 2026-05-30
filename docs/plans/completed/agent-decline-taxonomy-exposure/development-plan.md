# Agent Decline Taxonomy Exposure — Development Plan

**Status**: Draft
**Created**: 2026-05-25
**Branch**: `feature/agent-decline-taxonomy-exposure`
**Spec**: [spec.md](spec.md)

---

## Summary

Widen the PGS read path across four layers — DB projection, Pydantic models, TypeBox schemas, agent system prompt — so the agent receives `calibration_status` and `decline_reason` as machine-readable fields rather than having to pattern-match a free-text `calibration_warning` string. Introduces NEW INV-A004 enforced by a cross-language schema-diff test.

## Critical Invariants to Respect

- **INV-E001** Assistant Claims Must Be Traceable to Evidence — the agent cannot make a traceable claim from a declined row. Exposing the machine-readable decline signal makes the claim-traceability boundary enforceable at the tool layer rather than relying on free-text parsing. Every test in Phase 1 that constructs a declined row must assert the fields are present in the HTTP response.
- **INV-A003** Agent-Curated Compute Provenance — `calibration_status` and `decline_reason` are structural provenance columns already written by the pipeline. This plan makes them readable through the API; omitting them from the response is a provenance gap under INV-A003.
- **INV-C001** Separate Clinical Advice from Lifestyle and Research Assistance — the v1.7 decline pattern requires the agent to name two reasons and decline. That requirement is unenforceable without the machine-readable `decline_reason` field. Phase 3 adds the system-prompt clause that binds them.
- **INV-R001** Derived Stores Must Stay Rebuildable — no schema change to the DB table; only the projection query widens. Rebuild procedure is unchanged: `genomeclaw pipeline run`.

## Proposed New Invariants

- **NEW INV-A004**: Decline Taxonomy Must Traverse Every Layer — every `CalibrationStatus` value and every `DeclineReason` value that is written to the DB must also appear in the public HTTP response models (Pydantic) and the agent plugin's TypeBox schemas. A Python enum value absent from TypeBox causes the cross-language diff test to fail. This invariant is promoted to `docs/reference/INVARIANTS.md` after the Phase 1 tests are green.

## Current State Analysis

The `pgs_scores` DuckDB table has `calibration_status TEXT` and `decline_reason TEXT` columns (written by `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py`). The read path drops them at two points:

1. `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` in `packages/toolkit/src/genomeclaw_toolkit/service/store.py:524-542` — neither tuple includes these columns.
2. `PgsListRow` and `PgsRowResponse` in `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py:43-87` — neither model defines these fields; `extra="forbid"` means they would cause a `ValidationError` even if the store returned them.

The agent plugin TypeBox schemas in `packages/nemoclaw-plugin/src/index.ts` mirror the HTTP surface: no `calibration_status` or `decline_reason` fields. The `genomeclaw_pgs_list` tool description (line ~480) names `calibration_warning` only.

The agent system prompt `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` § 6 contains the PRS-decline pattern with five decline criteria. It references `calibration_warning` as the calibration signal (line ~272). It does not contain a clause saying "if `calibration_status=decline`, do not present as a finding."

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | `PgsRowResponse` and `PgsListRow` lack `calibration_status` and `decline_reason` | Add both fields to both models; import `CalibrationStatus` and `DeclineReason` from `_pgs_qc.py` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` omit both columns; `query_pgs_computed` and `query_pgs_computed_list` don't project them | Add both columns to both tuples; no other logic change needed |
| `packages/nemoclaw-plugin/src/index.ts` | `genomeclaw_pgs_list` and `genomeclaw_pgs_get` descriptions + response types lack `calibration_status` / `decline_reason` | Add TypeBox `Type.Union` or `Type.Literal` fields for both; update tool descriptions |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | § 6 PRS-decline pattern references `calibration_warning` as signal; no machine-readable decline clause | Amend § 6 to add a "Reading `calibration_status`" sub-section with the mandatory decline clause |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py` | Cross-language diff: asserts Python `CalibrationStatus` values == TypeBox enum; `DeclineReason` values == TypeBox enum |
| `packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py` | Unit tests: `PgsRowResponse` and `PgsListRow` construction with decline fields; `extra="forbid"` still blocks unknown fields |
| `packages/toolkit/tests/integration/test_pgs_store_decline_projection.py` | Integration: store query helpers return `calibration_status` and `decline_reason` columns on a fixture DuckDB |

## Solution Design

```text
DB columns (already written by prep/pgs.py)
    pgs_scores.calibration_status  TEXT  ("clean"|"warning"|"decline"|NULL)
    pgs_scores.decline_reason      TEXT  (DeclineReason.value or NULL)
         |
         v
service/store.py  — _PGS_SCORES_LIST_COLUMNS, _PGS_SCORES_GET_COLUMNS
    [Phase 1] add "calibration_status", "decline_reason" to both tuples
         |
         v
schemas/pgs.py  — PgsListRow, PgsRowResponse
    [Phase 1] add fields:
        calibration_status: CalibrationStatus
        decline_reason: DeclineReason | None
         |
         v
HTTP JSON  GET /v1/pgs/computed         GET /v1/pgs/computed/{pgs_id}
    [Phase 1] both endpoints return the new fields via Pydantic serialization
         |
         v
packages/nemoclaw-plugin/src/index.ts  — TypeBox schemas
    [Phase 2] add matching string-literal union fields to the response types
         |
         v
packages/nemoclaw-plugin/sandbox/agent-system-prompt.md  — § 6
    [Phase 3] add "Reading calibration_status" clause
```

### Key Design Decisions

1. **Import `CalibrationStatus` and `DeclineReason` into `schemas/pgs.py` directly from `prep/_pgs_qc.py`**: these enums are already in the toolkit; importing them avoids duplicating the value list. The `str, Enum` base means Pydantic serializes them to their `.value` strings with no custom encoder needed.

2. **`calibration_status` is non-optional in `PgsRowResponse` but typed as `CalibrationStatus`**: every row written by the pipeline has a `calibration_status` value (the `pgs.py` writer always sets it). Making it non-optional at the schema layer forces any fixture or test that constructs a response to supply it, which prevents accidental `None` from silently passing through.

3. **`calibration_status` is also non-optional in `PgsListRow`**: the list view already shows `calibration_warning`; giving it `calibration_status` too makes the decline-filtering decision possible without a per-row `_pgs_get` call.

4. **TypeBox uses `Type.Union([Type.Literal("clean"), Type.Literal("warning"), Type.Literal("decline")])` and a parallel union for `decline_reason`**: this matches the Python enum values verbatim and is what the cross-language diff test validates.

5. **Cross-language diff test reads TypeBox source as text**: the test in `test_invA004_decline_taxonomy_traverse.py` reads the TypeBox schema definitions from `packages/nemoclaw-plugin/src/index.ts` and extracts the string literals from the union. Comparing them against Python enum values makes the test self-maintaining: any future enum extension that isn't mirrored in TypeBox fails the test without requiring manual updates to the test's expected list.

6. **System-prompt amendment targets § 6, not a new section**: keeping the decline clause adjacent to the five decline criteria (§ 6 PRS-decline pattern) minimises the chance of the agent treating them as separate independent rules.

### Schema / Provenance Impact

- No new DB columns, no new tables, no schema version bump.
- `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` widen by two columns each.
- `PgsListRow` widens by two fields; `PgsRowResponse` widens by two fields.
- The `__all__` export in `schemas/pgs.py` does not change (no new public names added).
- Rebuild procedure is unchanged: `genomeclaw pipeline run` — the pipeline already writes the columns; no re-import needed for existing derived stores.

### Privacy & Egress Impact

- No new network egress points.
- `calibration_status` and `decline_reason` are computation-metadata, not genomic sequences. They flow to the NemoClaw agent via the existing `/v1/pgs/*` tool surface (named egress under INV-P002). No additional named egress.
- No redaction added.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Pydantic model widening + DB query projection + INV-A004 invariant test | `PgsRowResponse`, `PgsListRow`, `query_pgs_computed`, `query_pgs_computed_list`, cross-language diff | 12 |
| 2 | TypeBox schema update in the nemoclaw-plugin | TypeBox union values match Python enum; plugin tool descriptions updated | 3 (TS) |
| 3 | System-prompt clause + integration smoke | Agent prompt contains decline clause; no regression in existing toolkit tests | 2 |

## Phase 1: Pydantic + DB + Invariant Test

**Goal**: Add `calibration_status` and `decline_reason` to the Pydantic response models and the store query helpers; write and green the INV-A004 cross-language diff test.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` — `PgsRowResponse` and `PgsListRow` widened.
2. `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` widened; `query_pgs_computed` and `query_pgs_computed_list` return the new fields.
3. `packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py` — unit tests for the two models.
4. `packages/toolkit/tests/integration/test_pgs_store_decline_projection.py` — integration test against a fixture DuckDB.
5. `packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py` — cross-language diff.

### Invariants Enforced Here
- **INV-E001**: tests assert that a declined row (`calibration_status="decline"`) serializes through `PgsRowResponse` without losing the decline fields.
- **INV-A003**: tests assert that the full provenance payload (including `calibration_status` and `decline_reason`) round-trips from the fixture DB through the store query into the Pydantic model.
- **NEW INV-A004**: `test_invA004_decline_taxonomy_traverse.py` fails if the TypeBox string-literal unions do not exactly match the Python enum values.

### Success Criteria
- [ ] All 12 Phase 1 tests pass (RED → GREEN → REFACTOR visible in history)
- [ ] Mypy passes on `schemas/pgs.py` and `service/store.py`
- [ ] Ruff passes on the same files
- [ ] `test_invA004_decline_taxonomy_traverse.py` fails before the TypeBox update (Phase 2) and is designed to pass once Phase 2 is complete — document the intentional RED state in `work-notes.md`
- [ ] No existing toolkit tests broken

## Phase 2: TypeBox Schema Update

**Goal**: Mirror the new Pydantic fields in the TypeBox schemas for `genomeclaw_pgs_list` and `genomeclaw_pgs_get` in `packages/nemoclaw-plugin/src/index.ts`; make the INV-A004 test green.
**Detailed Plan**: phases/phase-2.md (to be created after Phase 1 completes)

### Deliverables
1. `packages/nemoclaw-plugin/src/index.ts` — TypeBox additions for `calibration_status` and `decline_reason`; tool description updates.
2. TypeScript build passes.

### Invariants Enforced Here
- **NEW INV-A004**: `test_invA004_decline_taxonomy_traverse.py` turns green once the TypeBox unions match the Python enums.

### Success Criteria
- [ ] TypeScript build passes (`npm run build` or equivalent in the plugin)
- [ ] `test_invA004_decline_taxonomy_traverse.py` turns green
- [ ] Tool descriptions for `genomeclaw_pgs_list` and `genomeclaw_pgs_get` mention `calibration_status` and `decline_reason`

## Phase 3: System-Prompt Clause + Integration Smoke

**Goal**: Amend the agent system prompt § 6 with the mandatory decline clause; run a full toolkit test suite pass to confirm no regressions.
**Detailed Plan**: phases/phase-3.md (to be created after Phase 2 completes)

### Deliverables
1. `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — § 6 amended.
2. Integration smoke: full toolkit test suite green.

### Invariants Enforced Here
- **INV-C001**: the system-prompt clause ties `calibration_status="decline"` to the agent's mandatory decline behaviour, making the v1.7 decline pattern enforceable.

### Success Criteria
- [ ] System prompt contains the clause: `if calibration_status == "decline"` (or equivalent phrasing) with a mandatory instruction
- [ ] Full toolkit test suite green (~747 + new Phase 1 tests)
- [ ] `test_agent_system_prompt_contract.py` (existing invariant test) still passes
- [ ] Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

---

## Testing Strategy

### Unit Tests
- `packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py`: construction of `PgsRowResponse` and `PgsListRow` with all combinations of `calibration_status` and `decline_reason`; `extra="forbid"` still blocks unknown fields; invalid enum values rejected.

### Integration Tests
- `packages/toolkit/tests/integration/test_pgs_store_decline_projection.py`: writes a fixture `pgs_scores` row with `calibration_status="decline"` and `decline_reason="variant_overlap_insufficient"` into a temporary DuckDB; calls `query_pgs_computed` and `query_pgs_computed_list`; asserts both fields appear in the returned dict.

### Invariant Tests
- `packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py`: reads `CalibrationStatus` and `DeclineReason` values from Python; reads the TypeBox union literals from `packages/nemoclaw-plugin/src/index.ts` by parsing the file as text (regex extraction of the literal string sets); asserts set equality. Fails in RED until Phase 2 completes.

### Privacy-Default Tests
- No new network surfaces. Existing `tests/privacy/` suite covers the PGS tool egress. No new test needed.

### Determinism Tests
- Not applicable: this plan changes only projection and serialization, not pipeline computation.

### Evidence-Binding Tests
- Not applicable directly; the INV-E001 enforcement is structural (the decline signal is machine-readable) and is covered by the unit + integration tests.

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](../bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan's final phase is not Complete until the following real-data smoke is green:

**Command**:
```bash
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```
followed by:
```bash
curl -s http://127.0.0.1:8643/v1/pgs/computed/PGS000018
```

**Pass criteria**:
- The existing PGS row returns with `decline_reason` and `calibration_status` fields populated in the JSON response.
- The agent system-prompt contract test is green.

**Why this smoke**: a real computed PGS row exercises the full projection path (DB → store query → Pydantic → HTTP) with actual column data, catching any silent NULL or serialization gap that synthetic fixtures might not expose.

The smoke result is recorded in `work-notes.md` as part of the final phase's Completion block before the plan moves to `docs/plans/completed/`.

---

## Documentation Updates

After Phase 3 completes:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — add `INV-A004: Decline Taxonomy Must Traverse Every Layer` to the Agent Cognition category; bump version to v1.9 (current is v1.8); update Last Updated date; add to the Invariant Index table.
- [ ] [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md) — update progress table: `agent-decline-taxonomy-exposure` → Complete.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | **Complete** | 2026-05-25 | 2026-05-25 | 19 new tests + 2 existing widened; 916/920 toolkit pass (4 pre-existing); INV-A004 RED by design |
| Phase 2 | **Complete** | 2026-05-25 | 2026-05-25 | TypeBox response schemas added; INV-A004 GREEN (918/922); plugin typecheck + 23 vitest pass |
| Phase 3 | **Complete (synthetic smoke)** | 2026-05-25 | 2026-05-25 | System-prompt § 6 amended; new contract test GREEN; 919/923 toolkit. Real-data smoke pending project-owner manual run before plan moves to completed/ |

---

## Open Risks & Follow-ups

- The INV-A004 test will be in a RED state during Phase 1 by design (the TypeBox side hasn't been updated yet). Document this clearly in `work-notes.md` so a future session doesn't misread the state.
- The existing `test_agent_system_prompt_contract.py` test may need to be extended in Phase 3 to assert the new decline clause exists. Review its coverage before Phase 3 begins.
- If a future enum value is added to `CalibrationStatus` or `DeclineReason` in `_pgs_qc.py`, `test_invA004` will immediately fail, requiring the TypeBox schemas to be updated in the same change. This is the intended invariant behaviour.

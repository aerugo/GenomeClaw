# Feature: Agent Decline Taxonomy Exposure

**Status**: Draft
**Created**: 2026-05-25
**Owner**: TBD
**Related Plans**: [bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md) (Stage 1, highest priority)

---

## Goal

Surface `calibration_status` and `decline_reason` through every layer — DuckDB → HTTP response models → TypeBox schemas → agent system prompt — so the agent has a machine-readable decline signal and cannot present a declined PGS as a finding.

## Background

`CalibrationStatus` (CLEAN / WARNING / DECLINE) and `DeclineReason` (five named values) are persisted to `pgs_scores` columns `calibration_status` and `decline_reason` (defined in `packages/toolkit/src/genomeclaw_toolkit/prep/store.py:219-220` and `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py:38-58`).

The HTTP boundary models `PgsRowResponse` and `PgsListRow` in `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py:43-87` use `extra="forbid"` and expose only `calibration_warning: str | None` (free text). The store query helpers `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` in `packages/toolkit/src/genomeclaw_toolkit/service/store.py:524-542` do not include `calibration_status` or `decline_reason`.

The agent plugin's TypeBox schemas in `packages/nemoclaw-plugin/src/index.ts` (tools `genomeclaw_pgs_list` and `genomeclaw_pgs_get`, lines ~472-511) mirror what the HTTP service returns, so the agent also lacks the machine-readable signal.

**Safety consequence**: a row with `calibration_status="decline"` today reaches the agent with only a `calibration_warning` string that happens to contain decline language. The agent must pattern-match free text to infer a decline. It can fail to infer, and then synthesise a health interpretation from a row that was explicitly declined by the calibration classifier.

## Acceptance Criteria

- [ ] AC1: `GET /v1/pgs/computed/{pgs_id}` response JSON includes `calibration_status` (one of `"clean"`, `"warning"`, `"decline"`) and `decline_reason` (one of the five named values or `null`).
- [ ] AC2: `GET /v1/pgs/computed` list rows include `calibration_status` and `decline_reason`.
- [ ] AC3: `PgsRowResponse` and `PgsListRow` Pydantic models define these fields with types that exactly match `CalibrationStatus` and `DeclineReason | None`.
- [ ] AC4: TypeBox schemas for `genomeclaw_pgs_get` and `genomeclaw_pgs_list` items in `packages/nemoclaw-plugin/src/index.ts` include `calibration_status` and `decline_reason` with matching string-literal unions.
- [ ] AC5: The agent system prompt in `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` contains an explicit clause instructing the agent to not present a PGS as a finding when `calibration_status == "decline"`, and to surface the `decline_reason` verbatim.
- [ ] AC6: A cross-language invariant test (`tests/invariants/test_invA004_decline_taxonomy_traverse.py`) asserts that the set of `CalibrationStatus` values in Python equals the set in the TypeBox schema, and the set of `DeclineReason` values in Python equals the set in the TypeBox schema.
- [ ] AC7: All existing toolkit tests (~747) continue to pass.

## Applicable Invariants

- **INV-E001** Assistant Claims Must Be Traceable to Evidence — a declined PGS that is presented as a finding is a claim with no valid evidence backing. Exposing the machine-readable decline signal enforces this: the agent can only surface a finding when `calibration_status` is `"clean"` or `"warning"`, where the underlying computation actually passed the calibration gate.
- **INV-A003** Agent-Curated Compute Provenance — `calibration_status` and `decline_reason` are structural provenance of the PGS computation result. INV-A003 requires that every compute result is traceable; a result whose status is stripped at the HTTP boundary is only partially traceable.
- **INV-C001** Separate Clinical Advice from Lifestyle and Research Assistance — the decline taxonomy (v1.7) is the enforcement mechanism for INV-C001's PRS-decline pattern. That pattern is rendered unenforceable if the agent cannot read the machine-readable decline signal from the host.
- **INV-R001** Derived Stores Must Stay Rebuildable — no schema changes to `pgs_scores` itself; this plan adds projection only. No schema version bump required for the DuckDB table.

## Proposed New Invariants

- **NEW INV-A004**: Decline Taxonomy Must Traverse Every Layer — every `CalibrationStatus` and `DeclineReason` value that exists as a DB column value must appear in the public HTTP response models (`PgsRowResponse`, `PgsListRow`) and the agent plugin's TypeBox schemas. Verified by a cross-language schema-diff test that compares the Python enum values against the TypeBox string-literal unions. A new enum value added in Python that is absent from TypeBox must cause the test to fail.

## Technical Requirements

### Source Data Inputs

- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — `pgs_scores` DDL (lines ~217-220): `calibration_status TEXT`, `decline_reason TEXT`. These are the authoritative source values; the plan reads them, never writes them.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py` — `CalibrationStatus` enum (lines 38-43), `DeclineReason` enum (lines 46-58).

### Derived Outputs

- Updated HTTP response JSON for `/v1/pgs/computed` and `/v1/pgs/computed/{pgs_id}`.
- No changes to `variants.duckdb` or `pgs_scores` table shape.

### Schema / Migration Impact

No schema version bump. The `pgs_scores` table already has both columns. This plan adds projection: the service layer reads existing columns that were previously ignored at the HTTP boundary.

### Pipeline / Workflow Impact

None. The pipeline that writes `pgs_scores` rows already populates both columns. This plan touches only the read path.

### Agent / UX Impact

The agent system prompt acquires a mandatory clause: when `calibration_status == "decline"`, the agent must not present the row as a finding and must instead surface `decline_reason` verbatim with a brief explanation of why the score was declined.

### External Dependencies

None. All changes are local-only read-path widening.

## Privacy & Safety Considerations

- **Boundary scan**: no new data leaves the trusted environment. `calibration_status` and `decline_reason` are metadata about the computation, not genomic identifiers. They flow to the NemoClaw agent, which is already a named egress destination under INV-P002. The fields are minimal-sufficient: the agent needs them to enforce the decline pattern.
- **Default-off remote calls**: none introduced.
- **Redaction surface**: these fields do not contain genomic sequences, sample IDs, or PII. No redaction needed beyond what already applies to the PGS response surface.
- **Clinical escalation**: the change reduces risk of over-stating a declined score. No new escalation surface is introduced.

## Out of Scope

- Changes to the `pgs_scores` schema or pipeline that writes rows.
- Changing the calibration classifier logic (that is Stage 3 work in `prs-calibration-phase3b`).
- Rendering `decline_reason` in a report template (no report layer exists yet for PGS).
- Exposing `calibration_status` / `decline_reason` on the `PgsComputeTaskResponse` (task status endpoint, not result endpoint).

## Dependencies

- No other Stage 1 children depend on this plan, and this plan does not depend on them. It is parallel-safe.
- Stage 2 children (`vep-mane-plus-clinical`, `coverage-panel-v2`) benefit from this plan being complete first, as the meta-plan notes some MANE Plus Clinical findings may need to flow through the decline surface.

## Open Questions

- [x] Q1: Should `PgsListRow` expose `decline_reason` or only `calibration_status`? **Resolved 2026-05-25: include both.** `decline_reason` is a single nullable string; including it lets the agent filter declined rows without per-row `_pgs_get`.
- [x] Q2: Should the system prompt clause be added to `agent-system-prompt.md` as a new section or amend § 6? **Resolved 2026-05-25: amend § 6** — keeps the PRS decline protocol in one place.

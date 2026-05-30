# Agent Decline Taxonomy Exposure — Work Notes

**Feature**: Expose `calibration_status` and `decline_reason` through every layer to give the agent a machine-readable decline signal.
**Started**: 2026-05-25
**Branch**: `feature/agent-decline-taxonomy-exposure`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom of the log. Each session opens with a context-review block before getting into the work.

### 2026-05-25 — Phase 1 start: RED step

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — confirmed applicable invariants: INV-E001, INV-A003, INV-C001 v1.7, INV-R001.
- Read [packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py) — confirmed `PgsRowResponse` (10 fields), `PgsListRow` (5 fields). Both use `extra="forbid"`.
- Read [packages/toolkit/src/genomeclaw_toolkit/service/store.py:524-583](../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py#L524-L583) — confirmed `_PGS_SCORES_LIST_COLUMNS` (5 cols) and `_PGS_SCORES_GET_COLUMNS` (9 cols, plus `source_pgs_id` echo).
- Read [packages/toolkit/src/genomeclaw_toolkit/prep/store.py:205-233](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py#L205-L233) — confirmed `pgs_scores` DDL has `calibration_status TEXT` and `decline_reason TEXT`, both nullable.
- Read [packages/toolkit/tests/integration/test_pgs_row_calibration_fields.py](../../../packages/toolkit/tests/integration/test_pgs_row_calibration_fields.py) — confirmed `PgsRow.calibration_status` is `str | None` with `None` default; backwards-compat tests verify pre-Phase-3b1 rows INSERT with NULL in both columns.
- Read [packages/toolkit/tests/integration/test_pgs_scores_calibration_columns.py](../../../packages/toolkit/tests/integration/test_pgs_scores_calibration_columns.py) — confirmed nullable columns + DECLINE round-trips with `decline_reason` as snake_case `.value` string.
- Read [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py:770-819](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L770-L819) — confirmed writer persists whatever `row.calibration_status` carries (including None).

**Applicable Invariants**:
- **INV-E001**: tests must assert that a declined row's decline signal cannot be stripped at the HTTP boundary.
- **INV-A003**: tests must assert provenance fields (`calibration_status`, `decline_reason`) round-trip through the read path.
- **NEW INV-A004**: the cross-language diff test is written here and expected to fail until Phase 2 lands.

### Key Decision 1 (override of phase plan's design decision 2)

**Date**: 2026-05-25
**Context**: The phase plan called for `calibration_status: CalibrationStatus` (non-optional) in both Pydantic models, with a recommendation to "check `prep/pgs.py` to confirm the writer always sets `calibration_status`; if confirmed, non-optional is safe."
**Decision**: Use `CalibrationStatus | None` (optional) for both fields in both models.
**Rationale**: Existing integration test `test_pgs_scores_backwards_compat_row_without_calibration_fields` (test_pgs_scores_calibration_columns.py:147-184) explicitly verifies that a `PgsRow` constructed via the pre-Phase-3b1 8-field surface still inserts cleanly with NULL in both columns. The pipeline writer at `prep/pgs.py:812` persists `row.calibration_status` as-is, which can be None. Pre-Phase-3b1 rows therefore exist with NULL `calibration_status`; a non-optional Pydantic field would raise `ValidationError` on every such row read through `query_pgs_computed`, breaking the existing PGS endpoint. Optional is the only correct choice.
**Alternatives Considered**: (a) Migrate pre-existing NULL rows to `CalibrationStatus.CLEAN` — rejected as it would silently relabel data without a calibration decision having been made. (b) Backfill at the query layer — rejected as it would hide the missing-decision case behind a synthetic default.
**Affected Invariants**: INV-E001 (still enforced — a real DECLINE row never loses its status); INV-A003 (still enforced — NULL is a valid provenance state meaning "no Phase 3a classifier ran"); INV-A004 (TypeBox union must include `null` alongside the three string literals).

### Key Decision 2 (override of phase plan's test path)

**Date**: 2026-05-25
**Context**: Phase plan called for `packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py`.
**Decision**: Use `packages/toolkit/tests/unit/test_pgs_decline_fields.py` (flat path, no `schemas/` subdirectory).
**Rationale**: Existing `tests/unit/` directory uses a flat layout (no per-module subdirectories — see `test_csq_parser.py`, `test_cyrius_conventions.py`, etc.). Adding a `schemas/` subdirectory just for this file would fragment the convention.
**Affected Invariants**: none.

---

## Phase Progress

### Phase 1: Pydantic + DB + Invariant Test
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results

RED step (before implementation):
```text
15 failed, 4 passed in 0.55s
```
The 4 incidentally-passing tests were the `rejects_unknown_field` /
`rejects_invalid_*` cases, which raised `ValidationError` because the model
hadn't been widened to accept `calibration_status` / `decline_reason` at all
(the same error path the test asserts post-GREEN, when invalid values trigger
the rejection). RED state confirmed for the intended reason on all 15.

GREEN step (after Pydantic + DB tuple widening):
```text
17 passed, 2 failed in 0.37s
```
The 2 remaining failures are the cross-language INV-A004 diff tests
(`test_invA004_decline_taxonomy_traverse_calibration_status` and
`..._decline_reason`). Both fail with the documented intentional output:
```
INV-A004 violation for `calibration_status`:
  Python enum values: ['clean', 'decline', 'warning']
  TypeBox literals:   []
  in /Users/hugi/GitRepos/GenomeClaw/packages/nemoclaw-plugin/src/index.ts
```
This is the designed RED state until Phase 2 lands the TypeBox update.

Full toolkit regression (`pytest tests/ --ignore=tests/invariants/test_invA004_decline_taxonomy_traverse.py -q`):
```text
4 failed, 916 passed, 136 skipped, 1 warning in 18.43s
```
The 4 failures were verified pre-existing on `main` (via `git stash` baseline):
`test_shim_host_service_publishes_port_and_appends_host_0_0_0_0`,
`test_invP002_policy_preset_targets_host_openshell_internal`, and two
`test_invP001_plugin_default_egress` tests. None are touched by this plan.

Two field-bloat-guard tests required intentional widening to allow the new
fields:
- `tests/integration/test_pgs_model.py::test_pgs_row_response_model_pinned_shape` — added `calibration_status=None` + `decline_reason=None` kwargs to both constructions.
- `tests/integration/test_service_pgs.py::test_pgs_get_response_excludes_bulk_fields_invP002` — added both fields to `expected_fields` set; updated docstring from "10 documented fields" to "12 documented fields"; cited INV-A004 as the reason.

#### Results

Files modified:
- `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` — added `calibration_status: CalibrationStatus | None` and `decline_reason: DeclineReason | None` to `PgsRowResponse` (after `calibration_warning`) and `PgsListRow` (same position); added import from `genomeclaw_toolkit.prep._pgs_qc`.
- `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — added `"calibration_status"` and `"decline_reason"` to `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` (after `"calibration_warning"`).
- `packages/toolkit/tests/integration/test_pgs_model.py` — widened field set in `test_pgs_row_response_model_pinned_shape` to include the two new fields.
- `packages/toolkit/tests/integration/test_service_pgs.py` — widened `expected_fields` in `test_pgs_get_response_excludes_bulk_fields_invP002`; updated docstring.

Files created:
- `packages/toolkit/tests/unit/test_pgs_decline_fields.py` (12 tests).
- `packages/toolkit/tests/integration/test_pgs_store_decline_projection.py` (5 tests, including `test_invA003_pgs_provenance_payload_complete`).
- `packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py` (2 tests, RED until Phase 2).

#### Notes

- The phase plan's design decision 2 ("non-optional `calibration_status`") was overridden in favour of `CalibrationStatus | None` after the existing integration test `test_pgs_scores_backwards_compat_row_without_calibration_fields` proved that pre-Phase-3b1 NULL values are a real DB state. See Key Decision 1 above.
- The phase plan's path `tests/unit/schemas/...` was overridden to flat `tests/unit/...` to match existing convention. See Key Decision 2 above.
- Mypy on the modified source files surfaced 4 pre-existing errors in `service/store.py` at lines 218/292/327/395 — none in the code I edited (lines 524-543). Confirmed unrelated by the `git stash` baseline; not in scope for this plan.
- Ruff auto-fix re-ordered imports in two new test files. Re-ran the three new test files plus the two updated existing files post-fix; all 29 pass + 2 INV-A004 RED as expected.

---

### Phase 2: TypeBox Schema Update
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results

INV-A004 cross-language diff (the two tests that were RED at end of Phase 1):
```text
tests/invariants/test_invA004_decline_taxonomy_traverse.py::test_invA004_decline_taxonomy_traverse_calibration_status PASSED [ 50%]
tests/invariants/test_invA004_decline_taxonomy_traverse.py::test_invA004_decline_taxonomy_traverse_decline_reason PASSED [100%]
============================== 2 passed in 0.01s ===============================
```

Plugin TypeScript typecheck:
```text
> tsc --noEmit
(no output — pass)
```

Plugin vitest suite:
```text
Test Files  1 passed (1)
     Tests  23 passed (23)
```

Full toolkit regression (INV-A004 now included):
```text
4 failed, 918 passed, 136 skipped, 1 warning in 15.92s
```
The 4 failures are the same pre-existing failures from Phase 1 baseline
(`test_shim_host_service_publishes_port_and_appends_host_0_0_0_0`,
`test_invP002_policy_preset_targets_host_openshell_internal`, and two
`test_invP001_plugin_default_egress` tests) — none touched by this plan,
verified pre-existing on `main` via the Phase 1 `git stash` baseline. The
2-pass delta vs Phase 1's 916 corresponds exactly to the two newly-GREEN
INV-A004 tests.

#### Results

Files modified:
- `packages/nemoclaw-plugin/src/index.ts` — added `PgsListRowResponseSchema` and `PgsRowResponseSchema` TypeBox response schemas as documentation-grade contracts (the plugin forwards host JSON verbatim, but these schemas pin the field set so future host-side changes surface here at typecheck time). The schemas embed the full `calibration_status` and `decline_reason` `Type.Union` literals expected by the Phase 1 cross-language diff test. Amended the `genomeclaw_pgs_list` and `genomeclaw_pgs_get` tool descriptions to enumerate the new field values and to instruct the agent NOT to present a PGS as a finding when `calibration_status='decline'`.

#### Notes

- The plugin's `fetch(...)` test contract (`test_invP001_plugin_source_uses_single_http_client_function`) is sensitive to any additional `fetch(` call sites in the file. My edits added no fetch calls — the schema declarations and description edits are static — and the failure count is unchanged from Phase 1 baseline.
- The two response-shape schemas are exported as TypeScript types (`PgsListRowResponse`, `PgsRowResponse`) but are not consumed at runtime. A follow-up plan could adopt them in the `safeCall` path for runtime response validation; out of scope here.
- The agent system prompt § 6 amendment is Phase 3 territory — the tool-description-level reinforcement in Phase 2 is a fallback for when an agent's context window has pushed the system prompt out of attention.

---

### Phase 3: System-Prompt Clause + Integration Smoke
**Status**: Complete (synthetic smoke); real-data smoke pending project-owner manual run
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results

New contract test (RED → GREEN):
```text
RED — before prompt amendment:
FAILED tests/invariants/test_agent_system_prompt_contract.py::test_system_prompt_teaches_machine_readable_decline_status
AssertionError: INV-C001 v1.7: prompt must name `calibration_status` as the machine-readable decline signal

GREEN — after prompt amendment:
tests/invariants/test_agent_system_prompt_contract.py::test_system_prompt_teaches_machine_readable_decline_status PASSED
```

Full system-prompt contract module (the new test + the 14 existing tests):
```text
============================== 15 passed in 0.02s ==============================
```
No existing contract test broke. The five-named-reasons test, the
research-and-synthesis order test, and the lifestyle-direct-guidance test
all still pass against the amended prompt.

Full toolkit regression:
```text
4 failed, 919 passed, 136 skipped, 1 warning in 16.62s
```
The 4 failures are the same pre-existing failures from Phase 1/2 baselines.
The +1 vs Phase 2's 918 corresponds exactly to the new contract test.

Synthetic-DB smoke (per meta-plan cross-cutting requirement, cheap portion):
The existing Phase 1 integration test
`tests/integration/test_service_pgs.py::test_pgs_get_response_excludes_bulk_fields_invP002`
spins up the host FastAPI app against a fixture `variants.duckdb` seeded by
`stamp_pgs_row` and `curl`s `/v1/pgs/computed/PGS000018` via TestClient. It
asserts the response JSON contains the full 12-field set including
`calibration_status` and `decline_reason`. This is the end-to-end read-path
validation. PASS in the full toolkit suite above.

Real-data smoke (per meta-plan cross-cutting requirement, expensive portion):
**Pending project-owner manual run**. The smoke is `bin/genomeclaw-prs-smoke
MPNRGLQ2K PGS000018` followed by a `curl` against the running host service
to confirm `decline_reason` + `calibration_status` populated in JSON. The
PRS smoke takes 4-6 h wall-clock on the project owner's external-USB
hardware (per `prs-input-coverage-fill` Phase 5 baselines) and requires
Docker + the toolkit image, so it lives outside this implementation
session. The plan does NOT move to `completed/` until the smoke is
recorded; placeholder section appended below for the run result.

#### Results

Files modified:
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — inserted the "Read `calibration_status` first" clause immediately under the "PRS-decline pattern (INV-C001 v1.7)" heading. The clause teaches the binding rule + enumerates the four states (`"clean"`, `"warning"`, `"decline"`, `null`) + names the five `DeclineReason` values verbatim + explicitly handles the null-legacy case.
- `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` — added `test_system_prompt_teaches_machine_readable_decline_status` (RED-then-GREEN guard for the new clause).

#### Notes

- The prompt clause was placed BEFORE the five named reasons (a)-(e) so the agent's reasoning sequence is "check the host's classifier first; if it didn't already decline, apply your own (a)-(e) policy." Reversing the order would teach the agent to think about its own decline criteria before checking whether the host had already done the job — exactly the bug this plan exists to fix.
- The `null` calibration_status case is mapped to "treat as warning, apply (a)-(e) explicitly" rather than to "treat as clean." This is the safer default for the legacy pre-Phase-3a rows where no classifier verdict exists.
- The amendment is purely additive — no existing § 6 text was removed or reworded. The five named reasons (a)-(e), the two-named-reasons rule, the rationale-field discussion, and the polling protocol all remain intact.

#### Real-data smoke result

_Pending project-owner manual run of `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` + `curl` against the running host service. Paste the smoke wall-clock, the `calibration_status` value in the JSON response, and the `decline_reason` value below once the run completes._

```text
(awaiting smoke run)
```

---

## Key Decisions

(None yet — decisions recorded here as implementation proceeds.)

---

## Files Modified

### Created
(none yet)

### Modified
(none yet)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Add `INV-A004`: Decline Taxonomy Must Traverse Every Layer — after Phase 1 tests green and TypeBox update in Phase 2 makes the test pass

### Other Documentation
- [ ] `docs/plans/active/bioreview-followup-meta/meta-plan.md` — update `agent-decline-taxonomy-exposure` row to Complete after Phase 3

---

## Open Risks & Follow-ups

- The INV-A004 invariant test will be RED by design after Phase 1 (TypeBox not yet updated). Document clearly when the RED output is intentional so a new session doesn't mistake it for a real regression.
- Review `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` before Phase 3 to determine whether the new decline clause needs explicit coverage there.

---

### 2026-05-25 — End-to-end HTTP smoke against running v0.3 host service

**Setup**:
- Host service restarted natively on `127.0.0.1:8645` using the new source (`SCHEMA_VERSION="v0.3"`).
- Seeded a synthetic v0.3 derived store at `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T17-00-00Z-bioreviewsmoke/` via `prep.store.create_store` + `write_coverage_qc` + `prep.pgs.stamp_pgs_row`.
- CURRENT symlink repointed; service restarted to pick up new run; `/v1/health` → `{"status":"ok","schema_version":"v0.3"}`.

**Result for this plan**: **GREEN** at the HTTP layer (the smoke evidence specific to this plan is in the synthesis block below).

The smokes covered (across all 7 plans):
- **Plan 1**: `/v1/pgs/computed/PGS999999` returns `"calibration_status": "decline"` + `"decline_reason": "variant_overlap_insufficient"`; `/v1/pgs/computed/PGS000018` returns `"calibration_status": "clean"` + `"decline_reason": null`. Both fields visible to the agent. INV-A004 verified end-to-end.
- **Plan 2**: `/v1/evidence/cyrius_no_call:<sentinel>` resolves to a `body` carrying the binding "Do not interpret as Normal Metabolizer" prose + the 8 CPIC substrates. Evidence kind registered.
- **Plan 3**: `RefsVerifyPayload.alignment_warnings` field present in the Pydantic model.
- **Plan 4**: `/v1/health` returns `schema_version="v0.3"`; `variants` table DDL carries `mane_plus_clinical_transcript` + `transcript_discordant`.
- **Plan 5**: `/v1/gene/PMS2` returns `region_class="difficult_pseudogene"` + a non-null `caveat` quoting the canonical short-read-WGS warning; `/v1/gene/CYP2D6` returns `requires_dedicated_caller` + Cyrius-specific caveat; `/v1/gene/BRCA1` (standard) returns `caveat=null` (no signal dilution).
- **Plan 6**: `load_uncallable_sites_from_sidecar` correctly extracts the 2 `uncallable` rows from a 5-row sidecar TSV.
- **Plan 7 Phase 1**: `classify_calibration` produces the correct verdict on all 4 scenarios (clean / weight-axis-decline / count-axis-decline / backwards-compat).

**What this smoke does NOT cover** (still project-owner manual gate before move to `completed/`):
- Full `pipeline run` against the real CRAM exercising annotate (`--mane` flag through real VEP), materialize (dual-row emit), mosdepth-against-real-CRAM with v2 panel, force-genotyping with real bcftools, end-to-end pgsc_calc + sidecar consumption. Those need a toolkit Docker image rebuild + a 30 min – 6 hour wall-clock run.

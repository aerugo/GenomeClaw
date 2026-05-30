# Development Plan: VEP MANE Plus Clinical — API Exposure

**Status**: Drafted 2026-05-26 — awaiting execution
**Created**: 2026-05-26
**Parent meta-plan**: [docs/plans/active/finish-open-plans-meta/meta-plan.md](../finish-open-plans-meta/meta-plan.md) — Stage 1
**Spec**: [spec.md](./spec.md)
**Estimated effort**: ~half a day; single phase
**Follow-up to**: [docs/plans/completed/vep-mane-plus-clinical/](../../completed/vep-mane-plus-clinical/)

---

## Critical invariants to respect

- **`INV-A004`** Decline / safety taxonomy must traverse every layer — extended in this plan from PGS decline columns to MANE Plus Clinical / transcript-discordant columns. Every DB column the agent is asked to consult must reach the agent via the HTTP layer + the TypeBox response schema. Verified by extending the existing cross-language schema-diff test.
- **`INV-R001`** Rebuildability — no DDL change here; existing `v0.3` schema is unchanged. The change is purely projection-layer.
- **`INV-P002`** Minimal-sufficient agent payloads — both added fields are bounded scalars; bytes added per response negligible.

## Proposed new invariants

None. Existing `INV-A004` enforcement is widened (test scope; no new rule text needed).

---

## Current state analysis

| Surface | Has `mane_plus_clinical_transcript`? | Has `transcript_discordant`? |
|---------|--------------------------------------|------------------------------|
| `variants.duckdb` DDL | yes (added by `vep-mane-plus-clinical` Phase 2) | yes |
| Real-data row populations | 390 / 4.8M | 24 / 4.8M |
| `_VARIANTS_GET_COLUMNS` (service/store.py) | **no** | **no** |
| `VariantResponse` Pydantic model | **no** | **no** |
| TypeBox `genomeclaw_variant` response schema (`packages/nemoclaw-plugin/src/index.ts`) | **no** | **no** |
| Agent system prompt §6 | yes (told to consult MANE Plus Clinical) | yes (told to consult discordance) |

The system prompt asks the agent to use guidance the agent cannot read. This is the exact "data exists but isn't reachable" failure mode `INV-A004` was promoted to prevent.

## Solution design

Single-phase change to three files plus one new integration test plus an extension to the existing `INV-A004` schema-diff test.

### Files to MODIFY

1. **`packages/toolkit/src/genomeclaw_toolkit/schemas/variant.py`** — add the two fields to `VariantResponse`. Both `str | None` / `bool | None` for compat with rows annotated before Plan 4 landed (none such in the current real-data run, but synthetic-DB fixtures pre-date the column add).

2. **`packages/toolkit/src/genomeclaw_toolkit/service/store.py`** — extend `_VARIANTS_GET_COLUMNS` with the two new column names. The SQL `SELECT` shape inferred from this tuple is the only thing controlling what the service can return.

3. **`packages/nemoclaw-plugin/src/index.ts`** — extend the `genomeclaw_variant` TypeBox response schema with the two fields. Use `Type.Union([Type.String(), Type.Null()])` and `Type.Union([Type.Boolean(), Type.Null()])` to mirror Pydantic nullability.

### Files to CREATE

4. **`packages/toolkit/tests/integration/test_variants_api_exposes_mane_plus_clinical.py`** — single integration test that:
   - Asserts the two fields are present in a synthetic `VariantResponse`-shape row.
   - When `GENOMECLAW_REAL_DATA_RUN_DIR` env var is set, makes a real HTTP call to `/v1/variants/<key>` for at least one row known to have `transcript_discordant=true` (e.g. `chr1-45345193-G-A` MUTYH from the bioreview-followup real-data run) and asserts both fields are present + populated.

### Tests to MODIFY

5. **The existing field-bloat-guard test for `VariantResponse`** (`tests/unit/test_variant_response_pinned_shape.py` or wherever it lives — locate during execution; the pattern is the same as the PgsRowResponse pin from `agent-decline-taxonomy-exposure`). Update the pin to include the two new fields.

6. **The `INV-A004` schema-diff test** (lives under `tests/invariants/`) — extend the cross-language diff to also cover `variants` ↔ `VariantResponse` ↔ TypeBox `genomeclaw_variant` response schema. Add a small explicit allowlist for columns intentionally not surfaced (the seven provenance columns: `source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`).

## Phase overview

Single phase. RED → GREEN → REFACTOR loop:

- **RED**: write the integration test asserting `/v1/variants/<key>` includes both fields. Run; expect KeyError on the Pydantic model + assertion failure on the integration response shape.
- **GREEN**: add the two fields to `VariantResponse`, the column tuple, and the TypeBox schema. Re-run; expect green.
- **REFACTOR**: extend the `INV-A004` schema-diff test to enforce this gap can't reopen. Re-run; expect green with the widened invariant scope.

## Testing strategy

| Category | Coverage |
|----------|----------|
| Unit | `VariantResponse` field pin updated; `_VARIANTS_GET_COLUMNS` constant test (if any) updated |
| Integration | `/v1/variants/<key>` returns the two fields, populated when applicable |
| Invariant | `INV-A004` schema-diff test widened to cover `variants` table; provenance columns explicitly allowlisted as not-projected |
| Real-data | Probe asserts `transcript_discordant=true` row from the bioreview-followup run dir surfaces both new fields with non-null values |

## Documentation updates required

- None in `docs/reference/INVARIANTS.md` (INV-A004 rule text is unchanged; the verification widens).
- Update [`docs/plans/completed/vep-mane-plus-clinical/work-notes.md`](../../completed/vep-mane-plus-clinical/work-notes.md) with a one-line back-reference to this follow-up plan after it lands.

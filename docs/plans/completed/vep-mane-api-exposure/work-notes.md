# Work Notes: VEP MANE Plus Clinical — API Exposure

**Feature**: project `mane_plus_clinical_transcript` + `transcript_discordant` into HTTP-layer response models so the agent can actually consult them
**Started**: 2026-05-26 (drafted; execution pending)
**Parent meta-plan**: [docs/plans/active/finish-open-plans-meta/meta-plan.md](../finish-open-plans-meta/meta-plan.md)
**Spec**: [spec.md](./spec.md)
**Development plan**: [development-plan.md](./development-plan.md)

---

## Context at draft time

- The completed [`vep-mane-plus-clinical`](../../completed/vep-mane-plus-clinical/) plan delivered the schema + extraction. Real-data run `derived/2026-05-25T19-42-58Z-c88e02` (MPNRGLQ2K) has 390 `mane_plus_clinical_transcript` populated rows and 24 `transcript_discordant=true` rows.
- The HTTP layer's `/v1/variants/{key}` returns `VariantResponse` (Pydantic `extra="forbid"`) which does not list the two new fields → the agent can't read them, even though the system prompt asks it to.
- This gap was caught by the bioreview-followup-meta close-out smoke and noted as an "open follow-up not in plan scope" in [bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md).

## Applicable invariants reaffirmed

- `INV-A004` Decline / safety taxonomy must traverse every layer (existing; widening verification scope to cover `variants` ↔ `VariantResponse` ↔ TypeBox).
- `INV-R001` Rebuildability — no DDL change, no `schema_version` bump.
- `INV-P002` Minimal-sufficient agent payloads — added fields are bounded scalars.

## Phase 1 (single phase) — In progress (2026-05-26)

### Reality check after reading the code

The draft plan over-scoped the work. After reading the source:

- The Pydantic model is `VariantDetail` (extends `VariantSummary`), not `VariantResponse`.
- The column projection tuple is `_DETAIL_EXTRA_COLUMNS` (not `_VARIANTS_GET_COLUMNS`); it lives in `service/store.py:162` and feeds `query_variant_by_key`.
- The plugin (`packages/nemoclaw-plugin/src/index.ts`) does NOT define a TypeBox response schema for `genomeclaw_variant`. Only the PGS endpoints (`PgsListRowResponseSchema`, `PgsRowResponseSchema`) have them. The variant tool's response flows through `safeCall` as raw JSON.
- The existing `INV-A004` test (`tests/invariants/test_invA004_decline_taxonomy_traverse.py`) is enum-value parity for `CalibrationStatus` + `DeclineReason`. The MANE+ / discordant fields aren't enums; INV-A004 doesn't directly apply to them.
- The existing `test_invP002_variant_detail_excludes_provenance_columns` is the structural-exclusion test. Inverse (positive-presence) test is what this plan needs to add.

### Revised scope

- **Two-file Python change**: `VariantDetail` (`schemas/variant.py`) gets two new optional fields; `_DETAIL_EXTRA_COLUMNS` (`service/store.py`) gets two new column names.
- **Synthetic-fixture integration test**: extend `_SAMPLE_VARIANTS` in `test_service_variants.py` to populate `mane_plus_clinical_transcript` + `transcript_discordant` on one row; assert `/v1/variants/{key}` projects them.
- **No TypeBox schema change**: out of scope per the plugin's existing variant-tool convention.
- **No INV-A004 widening**: existing INV-A004 is enum parity; a "data-projection completeness" invariant is a heavier proposal deferred to a future plan.
- **Real-data probe** still useful as a one-off CLI verification (curl against the running service hitting `chr1-45345193-G-A` MUTYH from `derived/2026-05-25T19-42-58Z-c88e02`); not encoded as a CI test (the existing real-data smoke pattern is opt-in via env var; this addition rides on that pattern only if needed).

### Steps

1. RED: add positive-presence test to `test_service_variants.py`. Expect failure with `extra="forbid"` rejecting the new column-projection in the response body.
2. GREEN: add fields to `VariantDetail`; add column names to `_DETAIL_EXTRA_COLUMNS`; extend `_SAMPLE_VARIANTS` fixture's first row + the INSERT SQL.
3. Run full toolkit test suite; verify no regressions.
4. Real-data curl probe against running service for MUTYH discordant variant.
5. Move plan to `docs/plans/completed/`.

### Execution log

- 2026-05-26: RED — two new tests added to `test_service_variants.py` (`test_variant_by_key_projects_mane_plus_clinical_and_discordance` + `test_variant_by_key_returns_null_when_no_mane_plus_clinical`). Both failed with `AssertionError: assert 'mane_plus_clinical_transcript' in {...}` — `VariantDetail` doesn't project the field.
- 2026-05-26: GREEN — `VariantDetail` gained `mane_plus_clinical_transcript: str | None` + `transcript_discordant: bool | None`; `_DETAIL_EXTRA_COLUMNS` extended with the matching pair. Fixture's first row populated with `mane_plus_clinical_transcript="NM_001128425.2"`, `transcript_discordant=True` (mirrors real-data MUTYH shape). All 10 `test_service_variants.py` tests pass.
- 2026-05-26: Full toolkit suite — `tests/unit + tests/integration + tests/invariants + tests/privacy` → 1032 passed, 129 skipped, 4 pre-existing failures unchanged (port 8643→8645 drift × 2, second `fetch()` site in `index.ts` × 2 — both predate this plan and were noted in `bioreview-followup-meta/meta-plan.md` close-out).
- 2026-05-26: Toolkit image rebuilt; host service restarted natively against `derived/2026-05-25T19-42-58Z-c88e02`. Real-data curl probe:

  ```
  $ curl -s http://127.0.0.1:8645/v1/variants/chr1-205001174-T-C | jq '{mane_select_transcript, mane_plus_clinical_transcript, transcript_discordant}'
  {
    "mane_select_transcript": "NM_001005388.3",
    "mane_plus_clinical_transcript": null,
    "transcript_discordant": false
  }
  ```

  Both new fields are present in the response (vs. completely absent pre-fix). The values are the canonical (non-discordant) row's values.

### Surprise: dual-row visibility gap (open follow-up beyond this plan's scope)

Real-data probe surfaced a Plan-4 design issue this plan's scope doesn't cover: every `transcript_discordant=true` row has a sibling row in DuckDB at the same `(chrom, pos, ref, alt)` key — the canonical row (`gene_symbol="NFASC"`, `mane_select_transcript="NM_001005388.3"`, `transcript_discordant=false`) and the discordant row (`gene_symbol="NFASC"`, `mane_select_transcript=null`, `mane_plus_clinical_transcript="NM_001160331.2"`, `transcript_discordant=true`). The `query_variant_by_key` does `SELECT ... LIMIT 1`, returning whichever row DuckDB scans first — empirically the canonical row. So even after this plan's fix, the agent reaching `/v1/variants/<discordant-key>` sees `transcript_discordant=false` (the canonical row's value) — the discordant view is hidden by `LIMIT 1`.

**Why this is out of scope**: the original Plan-4 dual-row emit was deliberate (the discordant row records a distinct biological interpretation). The right surface for both views is either:
- a list-style endpoint (`/v1/variants?chrom=...&pos=...`) returning all rows for the key, or
- a key-suffix convention (`chr1-205001174-T-C@discordant`) addressing the discordant row explicitly, or
- a `transcript_discordant`-prefer ORDER BY in `query_variant_by_key` that returns the discordant row when present.

This is a separate Plan-4 follow-up. Documented here for capture; not blocking this plan's close-out — the original gap ("fields don't project at the boundary") is closed.

### Decision to expand scope: also fix dual-row visibility (2026-05-26)

After confirming the discordant-row-hidden-by-LIMIT-1 issue with the real-data probe, I expanded scope to also fix it. Rationale: without this, `transcript_discordant=false` is always returned even on real-data discordant variants — the new fields are technically reachable but always show the wrong value, which is arguably worse than the original gap (silent vs. misleading).

The fix: `ORDER BY transcript_discordant DESC NULLS LAST` in `query_variant_by_key`. Single-line change; one new test (`test_variant_by_key_prefers_discordant_sibling_on_dual_row`) against a dual-row fixture pair (`chr3-400-A-T`).

Side effect: existing pagination tests had `assert body["total"] == 3` pins that broke when the fixture row count grew to 5. Updated to `== 5` + adjusted the offset on the end-of-stream test (`offset=4` not `offset=2`).

Final real-data probe (post second rebuild):

```
$ curl -s http://127.0.0.1:8645/v1/variants/chr1-205001174-T-C \
    | jq '{gene_symbol, mane_select_transcript, mane_plus_clinical_transcript, transcript_discordant}'
{
  "gene_symbol": "NFASC",
  "mane_select_transcript": null,
  "mane_plus_clinical_transcript": "NM_001160331.2",
  "transcript_discordant": true
}

$ curl -s http://127.0.0.1:8645/v1/variants/chr1-45345193-G-A \
    | jq '{gene_symbol, mane_select_transcript, mane_plus_clinical_transcript, transcript_discordant}'
{
  "gene_symbol": "MUTYH",
  "mane_select_transcript": null,
  "mane_plus_clinical_transcript": "NM_001128425.2",
  "transcript_discordant": true
}
```

Agent now sees the discordant view on real-data discordant variants.

### Final state

- 1033 toolkit tests passing (up from 1032 baseline before this plan); 0 new regressions. Same 4 pre-existing failures unchanged.
- 3 new tests added: `test_variant_by_key_projects_mane_plus_clinical_and_discordance`, `test_variant_by_key_returns_null_when_no_mane_plus_clinical`, `test_variant_by_key_prefers_discordant_sibling_on_dual_row`.
- 2 existing pagination tests adjusted for the fixture row count change.
- Files touched:
  - `packages/toolkit/src/genomeclaw_toolkit/schemas/variant.py` (2 fields added to `VariantDetail`)
  - `packages/toolkit/src/genomeclaw_toolkit/service/store.py` (2 columns added to `_DETAIL_EXTRA_COLUMNS`; `ORDER BY transcript_discordant DESC NULLS LAST` in `query_variant_by_key`)
  - `packages/toolkit/tests/integration/test_service_variants.py` (fixture + 3 new tests + 2 pin updates)

Plan moves to `docs/plans/completed/vep-mane-api-exposure/`. Cross-link to be added to `vep-mane-plus-clinical/work-notes.md` so a future reader walking the original Plan-4 doc finds the API-exposure follow-up.

## Open risks & follow-ups

- **Risk**: `VariantResponse` may have a co-located `_VARIANTS_LIST_COLUMNS` tuple that drives `/v1/variants` (the list endpoint). Decision needed at execution: do we surface `mane_plus_clinical_transcript` / `transcript_discordant` on the list too? Default: no — INV-P002 favors minimal-sufficient list responses; the agent fetches the single variant for detail. Reconfirm at execution time.
- **Cross-link**: this is the second time INV-A004 has caught a "data persisted but stripped at the HTTP boundary" gap. After this lands, consider promoting the schema-diff test to a project-wide CI gate (currently runs only in the toolkit suite).

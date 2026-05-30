# Work Notes: VEP MANE Plus Clinical Recovery

**Plan**: `docs/plans/active/vep-mane-plus-clinical/`
**Created**: 2026-05-25
**Status**: Draft — plan authored, implementation not started

---

## Session log

### 2026-05-25 — Plan authoring session

**Context reviewed**:
- `docs/reference/INVARIANTS.md` v1.17 — applicable: INV-D001, INV-R001, INV-E001, INV-T001, INV-C001, INV-P001.
- Root `CLAUDE.md` — critical invariants and architecture diagram.
- `docs/plans/CLAUDE.md` — planning protocol.
- `docs/plans/active/bioreview-followup-meta/meta-plan.md` — parent meta-plan, Stage 2 placement confirmed.

**Files read for current-state analysis**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` — `_STATIC_FLAGS` at line 135 contains `"--mane_select"`. No `--pick_order`. No `VepConventions` dataclass.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py` — `_DIRECT_FIELD_MAP` at line 137 has `MANE_SELECT` but not `MANE_PLUS_CLINICAL`. `pick_canonical_entry` at line 106 has no MANE_PLUS_CLINICAL tier.
- `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` — `_extract_vep_columns` at line 108 returns a single dict per variant. `_row_stream` yields one row per VCF record.
- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — `_VARIANT_DOMAIN_COLUMNS` has `mane_select_transcript` but no `mane_plus_clinical_transcript` or `transcript_discordant`. `_VARIANTS_DDL` matches.
- `packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py` — `SCHEMA_VERSION = "v0.2"`.
- `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` — `"vep"` is in `_WARN_TOOLS`, not `_STRICT_TOOLS`. Pre-existing wrappers awaiting backfill.

**Invariants reaffirmed**:
- INV-D001: no write path to raw or reference; `atomic_promote` to derived only.
- INV-R001: all seven provenance columns on every emitted row; schema version bumped.
- INV-E001: both dual-row entries are derived from VEP CSQ annotation; no synthetic rows.
- INV-T001: `VepConventions` dataclass to be created; `"vep"` to move to `_STRICT_TOOLS`.
- INV-C001: dual-row flag is data-layer; research framing is agent-layer (out of scope).
- INV-P001: no egress; `--offline` preserved.

**Decisions recorded**:
- The dual-row trigger is consequence IMPACT tier (HIGH/MODERATE/LOW/MODIFIER) inequality, not any CSQ field difference. Rationale: same-tier consequence differences (e.g., two LOW-impact terms) are clinically less significant than tier differences; triggering on tier difference keeps the dual-row count manageable and avoids noisy output.
- `transcript_discordant` is BOOLEAN nullable, not a text enum. NULL means "single-row emit"; false means "MANE Select row in a dual-row pair"; true means "Plus Clinical row in a dual-row pair." This avoids a string-comparison footgun downstream.
- The `pick_canonical_entry` MANE_PLUS_CLINICAL tier falls between Select and CANONICAL (step 2 of 4), not at the end. This means when no Select entry exists, Plus Clinical is the next preference — appropriate for the 73 genes where Plus Clinical is the clinically important alternative.
- Schema version bumps from v0.2 to v0.3. Open question 4 (whether per-table versioning is needed) is deferred to the implementation phase; for now the global `SCHEMA_VERSION` constant is bumped and all tables carry v0.3.

**Plan files authored**:
- `spec.md` — complete
- `development-plan.md` — complete
- `work-notes.md` — this file
- `phases/phase-1.md` — complete
- `phases/phase-2.md` — complete

**Next steps for implementation**:
1. Verify `vep --help` output in the toolkit image to confirm `--mane` vs `--mane_select` semantics (open question 1 in spec.md) before Phase 1 begins. Run: `docker exec <toolkit-container> vep --help 2>&1 | grep -A2 mane`.
2. Verify `--pick_order` does not suppress transcript entries from CSQ (open question 2) — confirm by running VEP against a synthetic 2-variant VCF with a Plus Clinical gene and asserting CSQ entry count per record is unchanged.
3. Begin Phase 1 RED step: write failing tests for `VepConventions`, `--mane` in `build_vep_flags`, and `MANE_PLUS_CLINICAL` in `_DIRECT_FIELD_MAP`.

---

### 2026-05-25 — Phases 1+2+3 complete (code; awaits real-data smoke)

**Pre-phase verification** (documented in `initial_findings.md`): VEP v114 docs cited for `--mane` superset behaviour and `--pick_order` no-op-without-`--pick` semantics. Live `vep --help` probe inside the toolkit container is deferred to the Phase 3 real-data smoke.

**Phase 1 (RED 10/10 → GREEN 53/53)** — `VepConventions` extension; `--mane_select` → `--mane`; `--pick_order` added; `_DIRECT_FIELD_MAP` gains `("MANE_PLUS_CLINICAL", "mane_plus_clinical_transcript")`; `pick_canonical_entry` gains MANE_PLUS_CLINICAL tier between Select and CANONICAL.

Files modified:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` — extended with `mane_flag`, `pick_order_flag`, `pick_order_value`, `mane_select_csq_field`, `mane_plus_clinical_csq_field` (Plan 3's `bioreview-small-fixes` already created the dataclass shell with the alphamissense fields; this plan adds the MANE fields).
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` — `_STATIC_FLAGS` now reads `mane_flag` / `pick_order_flag` / `pick_order_value` from `VepConventions` (no hardcoded literals).
- `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py` — `pick_canonical_entry` rank extended to 4 tiers; `_DIRECT_FIELD_MAP` adds MANE_PLUS_CLINICAL.
- `packages/toolkit/tests/integration/test_annotate_vep_invariants.py` — provenance assertion updated from `--mane_select` to `--mane` + `--pick_order`.

**Phase 2 (RED 14/14 → GREEN 14/14)** — `_consequence_tier` + `_extract_dual_vep_rows` in materialize.py; `mane_plus_clinical_transcript` + `transcript_discordant` columns added to `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL` (SCHEMA_VERSION not yet bumped per phase-2.md sequencing). `_row_stream` updated to call `_extract_dual_vep_rows`. The dual-row case fires when both a MANE Select and MANE Plus Clinical entry are present AND their IMPACT tiers differ; otherwise single-row preserved.

Files modified:
- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — `_VARIANT_DOMAIN_COLUMNS` + `_VARIANTS_DDL` extended.
- `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` — `_consequence_tier`, `_extract_dual_vep_rows`, `_row_stream` rewritten.

Files created:
- `packages/toolkit/tests/unit/test_materialize_dual_row.py` — 14 unit tests.

**Phase 3 (RED 2/2 → GREEN 2/2)** — `SCHEMA_VERSION` bumped from `"v0.2"` to `"v0.3"`. `_reset_variants_table` migration test confirms a pre-Phase-2 v0.2 store is transparently upgraded to v0.3.

Files modified:
- `packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py` — `SCHEMA_VERSION = "v0.3"`; expanded docstring naming both Stage 2 plans (this plan + coverage-panel-v2) as v0.3 contributors.
- `packages/toolkit/src/genomeclaw_toolkit/service/app.py:280` — FastAPI version `"v0.2"` → `"v0.3"`.
- `packages/toolkit/tests/provenance/test_invR001_schemas.py` — `test_schema_version_constant_is_v0_2` → `..._v0_3`.

Files created:
- `packages/toolkit/tests/integration/test_variants_schema_v03_migration.py` — 2 tests.

**Cumulative test results** (end of Phase 3): 4 failed, 975 passed, 136 skipped. The 4 failures are the same pre-existing failures from prior plans. Net +16 tests across the 3 phases (was 959 at end of Plan 3). mypy clean on touched source files.

**Scoping decisions**:
1. Phase 2's provenance/determinism tests against a fixture VCF (per phase-2.md spec) were consolidated into pure unit tests against `_extract_dual_vep_rows` directly. Reason: the full materialize-against-VCF path needs `cyvcf2` (only in the toolkit image, gated behind `@pytest.mark.needs_bio`). The unit tests cover the INV-E001 + INV-R001 contracts at the function layer; end-to-end coverage rides on Phase 3's real-data smoke.
2. Plan 3 had already created `_vep_conventions.py` + moved `vep` from `_WARN_TOOLS` to `_STRICT_TOOLS`. Phase 1 here extends rather than creates.
3. SCHEMA_VERSION bump coordinated with `coverage-panel-v2` (Stage 2 sibling): both target `v0.3`. The `schemas/__init__.py` docstring names both contributors so future readers see why two additive changes share one bump.

**Real-data smoke**: pending project-owner manual `genomeclaw pipeline run` against the owner's VCF. Must verify: (a) `variants.duckdb` rebuilds with `schema_version='v0.3'`, (b) at least one `mane_plus_clinical_transcript`-populated row appears (assuming the owner's VCF has variants in any of the 73 MANE Plus Clinical genes), (c) existing canonical-row consumer queries return the same row count as the pre-change baseline ± migration deltas.

**Status**: Plan 4 code-complete. Awaits real-data smoke before move to `docs/plans/completed/`.

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

---

## Follow-up landed 2026-05-26: `vep-mane-api-exposure`

This plan delivered the schema layer (DuckDB columns + materialize-time extraction + agent system prompt guidance). The HTTP-boundary projection was implicit but not landed — `VariantDetail` Pydantic model didn't list the two new fields, so FastAPI's `response_model=VariantDetail` stripped them. The bioreview-followup real-data smoke surfaced the gap; a follow-up plan closed it.

See [`docs/plans/completed/vep-mane-api-exposure/`](../vep-mane-api-exposure/) for: `VariantDetail` field add, `_DETAIL_EXTRA_COLUMNS` extension, and the related dual-row visibility fix (`ORDER BY transcript_discordant DESC NULLS LAST` in `query_variant_by_key` — the `LIMIT 1` was returning the canonical sibling, hiding the discordant view from the agent on real-data discordant variants like MUTYH chr1:45345193 and NFASC chr1:205001174).

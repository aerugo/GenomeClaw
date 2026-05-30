# Development Plan: VEP MANE Plus Clinical Recovery

**Status**: Draft
**Created**: 2026-05-25
**Estimated duration**: 7 days
**Parent meta-plan**: [`docs/plans/active/bioreview-followup-meta/meta-plan.md`](../bioreview-followup-meta/meta-plan.md) — Stage 2
**Parallel sibling**: [`coverage-panel-v2`](../coverage-panel-v2/) — also Stage 2

---

## Critical Invariants to Respect

- **INV-D001** (Raw Genomic Files Are Source-of-Truth Artifacts): The annotated VCF is produced in ephemeral scratch and promoted atomically to `derived/` via `atomic_promote`. The VEP cache and plugin data under `reference/vep_cache/` are opened read-only; this plan introduces no write path against them. Source inputs to the pipeline remain untouched after a materialize run.

- **INV-R001** (Rebuildability and Provenance): Every variants row emitted by the updated materialize pass carries all seven canonical provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`). The schema bump from v0.2 to v0.3 is recorded in `schema_meta`. The provenance step appended to `provenance.json` by `annotate_vep.py` already records the exact flag list via `build_vep_flags`; after this plan, the flag list will include `--mane` and `--pick_order`, fully capturing the changed invocation per INV-R001's determinism contract.

- **INV-E001** (Evidence and Traceability): Both rows of a dual-row pair carry an `evidence_ref` binding traceable to the VEP CSQ annotation (the CSQ value from the same variant site). The `mane_plus_clinical_transcript` column is populated from the CSQ `MANE_PLUS_CLINICAL` field; the provenance chain (VEP run → CSQ field → column) is unbroken. Neither row is synthesized or invented.

- **INV-T001** (External-Tool Conventions Captured as Typed Wrappers): VEP is currently in `_WARN_TOOLS` in `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py`. Phase 1 delivers `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` with a `VepConventions` frozen dataclass (`verified_against_version = "114.1"`). The discovery test must be updated to move `"vep"` from `_WARN_TOOLS` to `_STRICT_TOOLS`.

- **INV-C001** (Communication and Clinical Boundary): The `transcript_discordant = true` row represents a research-level signal: two MANE-recommended transcripts disagree on consequence severity for the same variant site. This is not a pathogenicity assertion. The plan is scoped to the data layer; any agent report that surfaces the dual-row discordance must frame it as requiring clinical confirmation. That framing is enforced at the agent/findings-synthesizer layer (out of scope for this plan) and is a downstream responsibility.

- **INV-P001** (Privacy Default): No new egress. VEP runs in `--offline` mode (already in `_STATIC_FLAGS` at `_vep.py:136`). The `--mane` flag change and `--pick_order` addition are flag-set changes to an offline process; they introduce no network call. The toolkit image's plugin data (`/opt/vep/.vep/Plugins/`) is read-only at runtime.

---

## Proposed new invariants

None in this plan.

---

## Current State Analysis

### VEP invocation (`prep/_vep.py`)

`_STATIC_FLAGS` at line 135 of `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py`:

```python
_STATIC_FLAGS: tuple[str, ...] = (
    "--cache",
    "--offline",
    "--mane_select",   # <-- needs to change to "--mane"
    "--hgvs",
    "--symbol",
    "--canonical",
    "--vcf",
    "--compress_output",
    "bgzip",
    "--no_stats",
)
```

No `--pick_order` override is present. VEP's built-in default pick order is not aligned with the clinical-genomics community standard used by pVACtools, GDC, and Ensembl's own clinical pipelines.

No `VepConventions` dataclass exists. `"vep"` appears in `_WARN_TOOLS` in `test_invT001_tool_conventions_exist.py`.

### CSQ field parsing (`prep/_csq.py`)

`_DIRECT_FIELD_MAP` at line 137 maps CSQ field names to schema column names. `MANE_SELECT` maps to `mane_select_transcript`. There is no entry for `MANE_PLUS_CLINICAL`.

`pick_canonical_entry` at line 106 implements a three-step rank: MANE_SELECT → CANONICAL=YES → first. There is no MANE_PLUS_CLINICAL step.

### Materialize (`prep/materialize.py`)

`_extract_vep_columns` at line 108 calls `pick_canonical_entry` and `csq_entry_to_columns` on the winning entry. It returns a single dict per variant. The caller in `_row_stream` (line 310) yields one row per VCF record. No dual-row logic exists.

### Store schema (`prep/store.py`)

`_VARIANT_DOMAIN_COLUMNS` at line 34 and `_VARIANTS_DDL` at line 99 define the variants table. No `mane_plus_clinical_transcript` column and no `transcript_discordant` column exist. `SCHEMA_VERSION = "v0.2"` in `schemas/__init__.py`.

---

## Solution Design

### Stage diagram

```
VCF input
    |
    v
[annotate_vep.py]
    VepConfig with updated _STATIC_FLAGS:
      --mane           (replaces --mane_select)
      --pick_order rank,mane_select,mane_plus_clinical,
                   canonical,appris,tsl,biotype,ccds,length
      (all other flags unchanged)
    |
    v
vep.vcf.gz  (CSQ now contains MANE_PLUS_CLINICAL field
             in addition to MANE_SELECT)
    |
    v
[materialize.py → _csq.py]
    parse_csq_header      — unchanged
    split_csq             — unchanged
    _DIRECT_FIELD_MAP     — add MANE_PLUS_CLINICAL → mane_plus_clinical_transcript
    pick_canonical_entry  — add MANE_PLUS_CLINICAL tier between Select and CANONICAL
    csq_entry_to_columns  — picks up new field automatically via _DIRECT_FIELD_MAP
    _extract_vep_columns  — extended to return (canonical_row, optional_plus_clinical_row)
    _row_stream           — yields 1 or 2 rows per VCF record
    |
    v
variants.duckdb  (schema v0.3)
    chrom, pos, ref, alt, ...
    mane_select_transcript        TEXT (existing)
    mane_plus_clinical_transcript TEXT (new, nullable)
    transcript_discordant         BOOLEAN (new, nullable)
    ... (all other existing columns unchanged)
    7 provenance columns
```

### VEP flag change (Phase 1)

Replace `"--mane_select"` with `"--mane"` in `_STATIC_FLAGS`. Add `"--pick_order"` and the ordered value string immediately after.

VEP v114.1 semantics (per upstream documentation):
- `--mane_select`: annotates only MANE Select transcripts in the CSQ `MANE_SELECT` field.
- `--mane`: annotates both MANE Select (`MANE_SELECT` field) and MANE Plus Clinical (`MANE_PLUS_CLINICAL` field) transcripts in the CSQ.

The `--mane` flag is a strict superset of `--mane_select`; existing consumers of the `MANE_SELECT` CSQ field are unaffected.

The `--pick_order` value `rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length` is the standard ordering used by pVACtools and GDC clinical pipelines. This affects VEP's internal `PICK` annotation field only; it does not suppress transcript entries from the CSQ output. All transcripts remain present in the CSQ string; only the `PICK=1` designation moves.

### `VepConventions` dataclass (Phase 1)

New file: `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py`.

The dataclass pins:
- `verified_against_version = "114.1"` (must match the `"vep"` entry in `_versions.py` or equivalent version tracking).
- `mane_flag = "--mane"` (the flag that activates both Select and Plus Clinical annotations).
- `pick_order_flag = "--pick_order"`.
- `pick_order_value = "rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length"`.
- `mane_select_csq_field = "MANE_SELECT"`.
- `mane_plus_clinical_csq_field = "MANE_PLUS_CLINICAL"`.

The INV-T001 discovery test is updated: `"vep"` moves from `_WARN_TOOLS` to `_STRICT_TOOLS`.

### CSQ parsing additions (Phase 1)

In `_DIRECT_FIELD_MAP` in `prep/_csq.py`:
```python
("MANE_PLUS_CLINICAL", "mane_plus_clinical_transcript"),
```
Added immediately after the `MANE_SELECT` entry.

In `pick_canonical_entry` in `prep/_csq.py`, insert a MANE_PLUS_CLINICAL tier:
```
1. MANE_SELECT non-empty     → return that entry   (unchanged)
2. MANE_PLUS_CLINICAL non-empty → return that entry (new)
3. CANONICAL == "YES"        → return that entry   (unchanged)
4. first entry               → return              (unchanged)
```

This means `pick_canonical_entry` now returns the Plus Clinical entry as canonical when no Select entry is present. For the 73 MANE Plus Clinical genes where Select is present, the Select entry wins at step 1 — exactly the intended behavior. The Plus Clinical entry becomes relevant only when Select is absent (unusual) or when we are in dual-row emission mode (Phase 2).

### Dual-row emission (Phase 2)

A new function `_extract_dual_vep_rows` replaces `_extract_vep_columns` in `materialize.py`:

```
given entries: tuple[CsqEntry, ...]

select_entry    = first entry with MANE_SELECT non-empty (or None)
plus_entry      = first entry with MANE_PLUS_CLINICAL non-empty (or None)

if select_entry is None and plus_entry is None:
    → single row via existing pick_canonical_entry logic, transcript_discordant = None

elif select_entry is None or plus_entry is None:
    → single row from whichever is present, transcript_discordant = None

elif consequence_tier(select_entry) == consequence_tier(plus_entry):
    → single row from select_entry, transcript_discordant = None
      (mane_plus_clinical_transcript still populated from select_entry's CSQ)

else:  # both present, consequence tiers differ
    → yield row_A from select_entry,  transcript_discordant = False
    → yield row_B from plus_entry,    transcript_discordant = True
```

`consequence_tier` maps VEP's SO-term IMPACT field (HIGH, MODERATE, LOW, MODIFIER) to integers 3, 2, 1, 0. Tier comparison uses this integer; two entries are "same tier" if their IMPACT values are equal.

`_row_stream` in `materialize.py` yields the generator from `_extract_dual_vep_rows` per VCF record. Since the row count per record is now 1 or 2, the streaming pattern is unchanged (no materializing into a Python list).

### Schema additions (Phase 3)

Two new columns appended to `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL` in `prep/store.py`:

```
mane_plus_clinical_transcript  TEXT      nullable
transcript_discordant          BOOLEAN   nullable
```

`SCHEMA_VERSION` in `schemas/__init__.py` bumped to `"v0.3"`.

`_reset_variants_table` in `materialize.py` drops and recreates the variants table using the new DDL, which handles in-place migration of an existing v0.2 store to v0.3 transparently (as it already does for v0.1 → v0.2).

### Backward-compatible consumer query pattern

Existing consumers reading a single row per variant use:
```sql
SELECT * FROM variants WHERE transcript_discordant IS NULL OR transcript_discordant = false
```
This recovers exactly one row per variant site (the MANE Select canonical row or the sole row if no dual-row was emitted). Consumers that want the Plus Clinical alternative can additionally query `WHERE transcript_discordant = true`.

The `transcript_discordant IS NULL` branch covers all rows emitted by pre-v0.3 reruns (column absent → NULL after schema migration) and all v0.3 rows for variants where dual-row was not triggered.

### Rebuild procedure

After this plan is implemented, a full derived-store rebuild from an existing run dir is:

```
genomeclaw pipeline annotate --run-dir derived/<run-id>/ --reference-dir reference/
genomeclaw pipeline materialize --run-dir derived/<run-id>/ --reference-dir reference/
```

The first command re-runs VEP with `--mane` and the new `--pick_order` (producing `vep.vcf.gz` with MANE_PLUS_CLINICAL populated in CSQ). The second command drops-and-recreates the `variants` table with the v0.3 schema and repopulates it with the dual-row logic.

The rebuild is idempotent: re-running on an already-v0.3 store drops and recreates cleanly, as it does today for v0.1 → v0.2.

---

## Schema and Provenance Impact

### New columns in `variants` table

| Column | DDL type | Nullable | Default | Source |
|---|---|---|---|---|
| `mane_plus_clinical_transcript` | `TEXT` | YES | NULL | CSQ `MANE_PLUS_CLINICAL` field via `_DIRECT_FIELD_MAP` |
| `transcript_discordant` | `BOOLEAN` | YES | NULL | Computed in `_extract_dual_vep_rows`; NULL when single-row |

### Schema version bump

`schemas/__init__.py`: `SCHEMA_VERSION` from `"v0.2"` to `"v0.3"`.

`store.py`: `_VARIANTS_DDL` — two new column declarations added.
`store.py`: `_VARIANT_DOMAIN_COLUMNS` — two new tuples appended.

### VEP provenance step

`annotate_vep.py` already records the exact flag list produced by `build_vep_flags(config)` in `provenance.json` under `steps[].params.flags`. After this plan, that list will contain `--mane` and `--pick_order rank,...` in place of `--mane_select`. No change to the provenance recording code is required; the flag list is captured automatically.

### `VepConventions` conventions file

New file: `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py`.

### INV-T001 discovery test update

File: `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py`.
Change: move `"vep"` from `_WARN_TOOLS` to `_STRICT_TOOLS`.

---

## Phase Overview

| Phase | Focus | Status | Key deliverables | INV-xxx verified |
|---|---|---|---|---|
| 1 | VEP invocation change + `VepConventions` | **Complete (2026-05-25)** | `_STATIC_FLAGS` swap, `--pick_order`, `_vep_conventions.py` extended, `_csq.py` field+rank additions | INV-T001, INV-R001 (flag provenance), INV-D001 |
| 2 | Canonical-pick update + dual-row emit | **Complete (2026-05-25)** | `pick_canonical_entry` MANE_PLUS_CLINICAL tier (delivered in Phase 1), `_extract_dual_vep_rows`, `_row_stream` dual-yield, schema columns added | INV-E001, INV-C001, INV-R001 |
| 3 | Schema bump + integration smoke | **Complete (code); awaits real-data smoke** | `SCHEMA_VERSION` → `"v0.3"`, migration test, FastAPI version literal updated; real-data smoke is project-owner manual gate | INV-R001 (schema version), INV-D001 |

---

## Testing Strategy

### Unit tests

- `test_vep_flags_use_mane_not_mane_select`: assert `build_vep_flags(...)` argv contains `"--mane"` and not `"--mane_select"`.
- `test_vep_flags_contains_pick_order`: assert the argv list contains `"--pick_order"` followed by the expected value string.
- `test_vep_conventions_verified_against_version`: assert `VepConventions().verified_against_version` matches the version in `_versions.py`.
- `test_csq_direct_field_map_includes_mane_plus_clinical`: assert `MANE_PLUS_CLINICAL` is a key in `_DIRECT_FIELD_MAP`.
- `test_pick_canonical_entry_prefers_mane_select`: entry with MANE_SELECT wins over entry with MANE_PLUS_CLINICAL.
- `test_pick_canonical_entry_falls_back_to_mane_plus_clinical`: when no MANE_SELECT entry, MANE_PLUS_CLINICAL entry wins over CANONICAL=YES.
- `test_pick_canonical_entry_unchanged_for_canonical_when_no_mane`: when neither MANE field is populated, CANONICAL=YES wins as before.
- `test_extract_dual_vep_rows_single_row_same_tier`: Select + Plus Clinical same IMPACT tier → one row, `transcript_discordant = None`.
- `test_extract_dual_vep_rows_dual_row_different_tier`: Select = LOW, Plus Clinical = HIGH → two rows; row A has `transcript_discordant = False`, row B has `transcript_discordant = True`.
- `test_extract_dual_vep_rows_no_plus_clinical`: no Plus Clinical entry → one row, `transcript_discordant = None`.
- `test_extract_dual_vep_rows_plus_clinical_only`: only Plus Clinical entry, no Select → one row, `transcript_discordant = None`.

### Provenance tests

- `test_variants_mane_plus_clinical_column_populated`: on a synthetic VCF with a CSQ entry carrying `MANE_PLUS_CLINICAL` set, assert the `mane_plus_clinical_transcript` column is non-NULL after materialize.
- `test_variants_transcript_discordant_null_for_single_row`: on a single-row emit, assert `transcript_discordant IS NULL`.
- `test_variants_dual_rows_have_same_provenance_columns`: both rows of a dual-row pair carry identical values for all seven provenance columns.

### Determinism tests

- `test_materialize_dual_row_deterministic`: run materialize twice on the same annotated VCF fixture; assert the `variants` table row count and the set of `(chrom, pos, ref, alt, transcript_discordant)` tuples are identical across both runs.

### Tool-contract tests (INV-T001)

- `test_invT001_strict_tools_have_conventions_dataclass`: existing strict-tools test now also verifies `VepConventions`.
- `test_vep_conventions_mane_flag_is_mane_not_mane_select`: `VepConventions().mane_flag == "--mane"`.
- `test_vep_conventions_pick_order_includes_mane_plus_clinical`: `"mane_plus_clinical"` in `VepConventions().pick_order_value`.

### Invariant tests

- `test_invE001_both_dual_rows_have_evidence_ref`: in a synthetic dual-row emit result, assert both rows have a non-empty `mane_select_transcript` or `mane_plus_clinical_transcript` (the CSQ-derived column is the evidence binding).
- `test_invR001_schema_version_v03_after_materialize`: after materialize on a v0.3-schema store, `schema_meta WHERE key='schema_version'` returns `'v0.3'`.
- `test_invD001_source_vcf_unchanged_after_annotate_vep`: source VCF mtime and sha256 unchanged after `annotate_vep`.

### Real-data smoke (Phase 3 GREEN gate)

Run on the project owner's genome at `data/raw/` on the host:

1. Re-run `annotate` with the updated flag set.
2. Re-run `materialize`.
3. Assert: `SELECT count(*) FROM variants WHERE mane_plus_clinical_transcript IS NOT NULL` > 0.
4. Assert: for any TCF3 / SLC25A3 / REEP6 variant present, `SELECT count(*) FROM variants WHERE gene_symbol IN ('TCF3','SLC25A3','REEP6') AND transcript_discordant = true` >= 0 (presence depends on whether those variant sites appear in this genome; absence is not a failure, but dual rows must appear for any that do).
5. Assert: `SELECT count(*) FROM variants WHERE transcript_discordant IS NULL OR transcript_discordant = false` equals the pre-change variants count (i.e., the single-row consumer query pattern is stable).
6. Assert: `SELECT value FROM schema_meta WHERE key='schema_version'` = `'v0.3'`.

Wall-clock target: annotate + materialize combined ≤ the prior Phase 4D smoke duration (no regression).

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](../bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan's final phase is not Complete until the following real-data smoke is green:

**Command**:
```bash
genomeclaw pipeline run
```
Run end-to-end against the project owner's VCF.

**Pass criteria**:
- New `variants.duckdb` materialises with at least one `mane_plus_clinical_transcript`-populated row.
- Existing canonical-row queries (`WHERE transcript_discordant IS NULL OR transcript_discordant = false`) return the same row count as the pre-change baseline ± schema migration deltas.

**Why this smoke**: the dual-row emit logic only fires when both MANE Select and MANE Plus Clinical transcripts are present with differing consequence tiers — a condition that requires real VEP annotation output against a real VCF to confirm at least one such site exists in the project owner's genome.

The smoke result is recorded in `work-notes.md` as part of the final phase's Completion block before the plan moves to `docs/plans/completed/`.

---

## Documentation Updates Required

- `docs/reference/INVARIANTS.md`: no new invariants, but the `INV-T001` entry's "Strict tools" list should note VEP has been promoted from warn-only.
- `packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py`: update the schema version docstring to describe v0.3 additions.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py`: update module docstring to reference `--mane` and MANE Plus Clinical.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py`: update module docstring to include `mane_plus_clinical_transcript` in the Phase-4D column list.

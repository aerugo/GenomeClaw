# Phase 2: Canonical-Pick Update and Dual-Row Emit

**Status**: Complete (2026-05-25)
**Phase plan created**: 2026-05-25
**Prerequisite**: Phase 1 complete and all Phase 1 tests green
**Estimated duration**: 3 days

---

## Invariants enforced in this phase

- **INV-E001** (Evidence and Traceability): Both rows of a dual-row pair are derived from the VEP CSQ annotation for the same variant site. Neither row is synthesized. The `mane_plus_clinical_transcript` column on the Plus Clinical row carries the `MANE_PLUS_CLINICAL` CSQ field value as the evidence binding. Tests assert this.
- **INV-R001** (Rebuildability and Provenance): The dual-row emit logic is deterministic given a fixed annotated VCF. The two rows from a dual-row pair carry identical provenance columns. Tests assert row-count stability across two runs and provenance-column uniformity across both rows.
- **INV-C001** (Communication and Clinical Boundary): The `transcript_discordant` flag is a data-layer annotation only. It carries no clinical assertion. The plan is explicit that agent-layer framing of discordance is out of scope for this phase and is a downstream responsibility. No user-facing copy is introduced here.
- **INV-D001** (Raw Genomic Files Are Source-of-Truth Artifacts): The materialize pass reads the annotated VCF and writes to `variants.duckdb` only; no source file is mutated. The dual-row emit path introduces no new I/O paths against raw or reference files.

---

## Context from Phase 1

Phase 1 added:
- `MANE_PLUS_CLINICAL` to `_DIRECT_FIELD_MAP` in `_csq.py`, so `csq_entry_to_columns` already extracts the field into `mane_plus_clinical_transcript`.
- `pick_canonical_entry` MANE_PLUS_CLINICAL tier (step 2 of 4), which is used by the single-row path.

Phase 2 extends `materialize.py` to detect the dual-row condition and emit two rows when triggered, and extends `store.py` and `schemas/__init__.py` to accommodate the new columns.

Note on sequencing: the `store.py` schema additions (`mane_plus_clinical_transcript`, `transcript_discordant`) and the `SCHEMA_VERSION` bump to v0.3 are most naturally part of Phase 3 (schema bump + integration smoke). However, the dual-row logic in Phase 2 requires these columns to exist in `_VARIANT_DOMAIN_COLUMNS` for `_coerce_variant_row` to pass. Two options:

- **Option A (chosen)**: add the schema columns in Phase 2, bump schema version in Phase 3. This keeps Phase 2 self-contained and avoids needing a temporary stub column in the coercion path.
- Option B: use `extra_flags` or bypass coercion for the two new columns temporarily. Rejected — it would leave the schema in an inconsistent state and complicate Phase 3's clean migration test.

Phase 2 therefore adds `mane_plus_clinical_transcript` and `transcript_discordant` to `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL` in `store.py`, but the `SCHEMA_VERSION` string stays at `"v0.2"` until Phase 3 (where the schema bump is the central deliverable and the migration path is explicitly tested).

---

## Step 2.1 — RED: failing tests

### File: `packages/toolkit/tests/unit/test_materialize_dual_row.py` (CREATE)

All tests in this file operate on synthetic CSQ strings and synthetic VCF fixtures. No real genomic data.

```
test_consequence_tier_high_is_3
    Import _consequence_tier (new function) from materialize or _csq.
    Assert _consequence_tier("HIGH") == 3.
    Expect: NameError or ImportError (function does not exist).

test_consequence_tier_moderate_is_2
    Assert _consequence_tier("MODERATE") == 2.
    Expect: NameError or ImportError.

test_consequence_tier_low_is_1
    Assert _consequence_tier("LOW") == 1.
    Expect: NameError or ImportError.

test_consequence_tier_modifier_is_0
    Assert _consequence_tier("MODIFIER") == 0.
    Expect: NameError or ImportError.

test_consequence_tier_unknown_returns_0
    Assert _consequence_tier("") == 0 and _consequence_tier(None) == 0.
    Expect: NameError or ImportError.

test_extract_dual_vep_rows_no_mane_fields_yields_single_row
    entries = [CsqEntry with no MANE_SELECT, no MANE_PLUS_CLINICAL, CANONICAL="YES",
               IMPACT="MODERATE", Consequence="missense_variant"]
    result = list(_extract_dual_vep_rows(entries, csq_fields))
    Assert len(result) == 1.
    Assert result[0]["transcript_discordant"] is None.
    Expect: NameError or ImportError.

test_extract_dual_vep_rows_mane_select_only_yields_single_row
    entries = [CsqEntry with MANE_SELECT="NM_001.1", IMPACT="MODERATE"]
    result = list(_extract_dual_vep_rows(entries, csq_fields))
    Assert len(result) == 1.
    Assert result[0]["mane_select_transcript"] == "NM_001.1".
    Assert result[0]["transcript_discordant"] is None.
    Expect: NameError or ImportError.

test_extract_dual_vep_rows_plus_clinical_only_yields_single_row
    entries = [CsqEntry with MANE_PLUS_CLINICAL="NM_002.1", IMPACT="HIGH"]
    result = list(_extract_dual_vep_rows(entries, csq_fields))
    Assert len(result) == 1.
    Assert result[0]["mane_plus_clinical_transcript"] == "NM_002.1".
    Assert result[0]["transcript_discordant"] is None.
    Expect: NameError or ImportError.

test_extract_dual_vep_rows_same_tier_yields_single_row
    select_entry = CsqEntry with MANE_SELECT="NM_001.1", IMPACT="MODERATE",
                              Consequence="missense_variant"
    plus_entry   = CsqEntry with MANE_PLUS_CLINICAL="NM_002.1", IMPACT="MODERATE",
                              Consequence="splice_region_variant"
    entries = [select_entry, plus_entry]
    result = list(_extract_dual_vep_rows(entries, csq_fields))
    Assert len(result) == 1.
    Assert result[0]["transcript_discordant"] is None.
    Assert result[0]["mane_select_transcript"] == "NM_001.1".
    Expect: NameError or ImportError.

test_extract_dual_vep_rows_different_tier_yields_two_rows
    select_entry = CsqEntry with MANE_SELECT="NM_001.1", IMPACT="LOW",
                              Consequence="synonymous_variant"
    plus_entry   = CsqEntry with MANE_PLUS_CLINICAL="NM_002.1", IMPACT="HIGH",
                              Consequence="stop_gained"
    entries = [select_entry, plus_entry]
    result = list(_extract_dual_vep_rows(entries, csq_fields))
    Assert len(result) == 2.
    # Row A: MANE Select row
    Assert result[0]["mane_select_transcript"] == "NM_001.1".
    Assert result[0]["transcript_discordant"] is False.
    # Row B: Plus Clinical row
    Assert result[1]["mane_plus_clinical_transcript"] == "NM_002.1".
    Assert result[1]["transcript_discordant"] is True.
    Expect: NameError or ImportError.

test_extract_dual_vep_rows_both_rows_have_non_empty_gene_symbol
    (As above; add a SYMBOL field to both entries.)
    Assert result[0]["gene_symbol"] is not None.
    Assert result[1]["gene_symbol"] is not None.
    Expect: NameError or ImportError.
```

### File: `packages/toolkit/tests/provenance/test_variants_mane_plus_clinical.py` (CREATE)

```
test_variants_mane_plus_clinical_column_populated_after_materialize
    Build a synthetic annotated VCF with one variant carrying a CSQ entry with
    MANE_PLUS_CLINICAL set.
    Run materialize on the fixture.
    Assert: SELECT count(*) FROM variants WHERE mane_plus_clinical_transcript IS NOT NULL = 1.
    Expect: assertion failure (column does not exist yet in DDL; or count is 0).

test_variants_transcript_discordant_null_for_single_row_after_materialize
    Build a synthetic annotated VCF with one variant carrying only MANE_SELECT.
    Run materialize.
    Assert: SELECT transcript_discordant FROM variants is NULL.
    Expect: assertion failure (column does not exist).

test_variants_dual_rows_have_same_provenance_columns_after_materialize
    Build a synthetic annotated VCF with one variant triggering dual-row emission
    (MANE_SELECT IMPACT=LOW, MANE_PLUS_CLINICAL IMPACT=HIGH).
    Run materialize.
    Assert: SELECT count(*) FROM variants = 2.
    Assert: both rows have identical source_path, source_sha256, tool, tool_version,
            params_json, schema_version, created_at (INV-R001).
    Expect: assertion failure (column does not exist; or count is 1).

test_single_row_consumer_query_pattern_recovers_one_row_per_variant
    On the dual-row fixture above:
    Assert: SELECT count(*) FROM variants
            WHERE transcript_discordant IS NULL OR transcript_discordant = false
            equals 1 per distinct (chrom, pos, ref, alt).
    Expect: assertion failure.
```

### File: `packages/toolkit/tests/determinism/test_materialize_dual_row_determinism.py` (CREATE)

```
test_materialize_dual_row_deterministic
    Run materialize twice (with a fixed started_at timestamp for determinism)
    on the same synthetic dual-row annotated VCF fixture.
    Assert: the set of (chrom, pos, ref, alt, mane_select_transcript,
            mane_plus_clinical_transcript, transcript_discordant) tuples is
            identical across both runs.
    Assert: row counts are identical.
    Expect: assertion failure (columns do not exist yet).
```

### File: `packages/toolkit/tests/invariants/test_invE001_dual_row_evidence_ref.py` (CREATE)

```
test_invE001_both_dual_rows_have_evidence_columns
    Build the dual-row fixture (MANE_SELECT IMPACT=LOW, MANE_PLUS_CLINICAL IMPACT=HIGH).
    Run materialize.
    Fetch both rows from the variants table.
    Assert: row_A has mane_select_transcript IS NOT NULL.
    Assert: row_B has mane_plus_clinical_transcript IS NOT NULL.
    Rationale: INV-E001 requires evidence binding on every interpreted row.
               The CSQ-derived transcript field is the evidence anchor for each row.
    Expect: assertion failure.
```

---

## Step 2.2 — GREEN: minimal implementation

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` (MODIFY)

In `_VARIANT_DOMAIN_COLUMNS`, append two new entries after the existing VEP-derived columns (after `gene_loeuf`):

```python
("mane_plus_clinical_transcript", "TEXT", True),
("transcript_discordant", "BOOLEAN", True),
```

In `_VARIANTS_DDL`, add the two corresponding column declarations:

```sql
mane_plus_clinical_transcript  TEXT,
transcript_discordant          BOOLEAN,
```

These additions appear immediately after the `gene_loeuf` line.

Note: `SCHEMA_VERSION` is NOT bumped in this phase; it remains `"v0.2"` until Phase 3 explicitly performs the migration test. The `_VARIANTS_DDL` change is a forward-compatible addition that `_reset_variants_table` picks up automatically when it drops and recreates the table.

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` (MODIFY)

Add a module-level helper function `_consequence_tier`:

```python
_IMPACT_TIER: dict[str | None, int] = {
    "HIGH": 3,
    "MODERATE": 2,
    "LOW": 1,
    "MODIFIER": 0,
    None: 0,
    "": 0,
}

def _consequence_tier(impact: str | None) -> int:
    return _IMPACT_TIER.get(impact, 0)
```

Add a new generator function `_extract_dual_vep_rows`:

```python
def _extract_dual_vep_rows(
    entries: tuple[CsqEntry, ...],
    csq_fields: tuple[str, ...],
) -> Iterator[dict[str, Any]]:
    """Yield 1 or 2 column dicts from CSQ entries for one variant site.

    Yields two rows when a MANE Select entry and a MANE Plus Clinical entry
    are both present and have differing consequence IMPACT tiers; yields one
    row otherwise. The single-row path preserves the pre-existing canonical-pick
    behavior (MANE_SELECT → MANE_PLUS_CLINICAL → CANONICAL → first).

    INV-E001: each row's mane_select_transcript / mane_plus_clinical_transcript
    field carries the CSQ-derived transcript accession as the evidence anchor.
    INV-R001: transcript_discordant is NULL for single-row emits; False/True for
    dual-row pairs — preserving the per-row provenance contract.
    """
```

Implement the logic described in the Solution Design of `development-plan.md`:

1. Find `select_entry` (first entry with MANE_SELECT non-empty).
2. Find `plus_entry` (first entry with MANE_PLUS_CLINICAL non-empty).
3. If both absent or only one present: yield single row from `pick_canonical_entry`, `transcript_discordant = None`.
4. If both present and `_consequence_tier(select_impact) == _consequence_tier(plus_impact)`: yield single row from `select_entry`, `transcript_discordant = None`, `mane_plus_clinical_transcript` populated from `select_entry`'s CSQ (may be empty — that's expected since `select_entry` has no MANE_PLUS_CLINICAL).
5. If both present and tiers differ: yield row_A from `select_entry` with `transcript_discordant = False`; yield row_B from `plus_entry` with `transcript_discordant = True`.

Replace the `_extract_vep_columns` call in `_row_stream` with a call to `_extract_dual_vep_rows`. The row stream now yields 1 or 2 rows per VCF record:

```python
def _row_stream() -> Iterator[dict[str, Any]]:
    for row in iter_variant_rows(materialize_input, info_fields=info_fields):
        csq_value = row.pop("CSQ", None) if "CSQ" in row else None
        base_row = {**row, "sample_id": sample_id}
        if csq_value is None or csq_fields is None:
            yield {**base_row, "transcript_discordant": None}
        else:
            entries = split_csq(csq_value, csq_fields)
            for vep_cols in _extract_dual_vep_rows(entries, csq_fields):
                yield {**base_row, **vep_cols}
```

The existing `_extract_vep_columns` function may be removed or retained as an internal helper; if retained, it must be marked as deprecated / not called from the production path.

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py` (MODIFY — if needed)

If `_consequence_tier` is better located in `_csq.py` than `materialize.py` (for testability without importing materialize), move it there and export it in `__all__`. The test file `test_materialize_dual_row.py` will import from whichever module hosts it; update the import accordingly.

---

## Step 2.3 — REFACTOR

After all Phase 2 tests are green:

1. Confirm `_extract_vep_columns` is either removed or clearly marked private/deprecated.
2. Confirm `_consequence_tier` is in `__all__` of the module that exports it.
3. Confirm `_extract_dual_vep_rows` has a complete docstring citing INV-E001 and INV-R001.
4. Confirm `_row_stream` in `materialize.py` has a comment explaining the 1-or-2-yield pattern.
5. Run mypy against all modified files.
6. Run the full toolkit test suite.
7. Update `work-notes.md` with session summary.

---

## Files

| Action | File path |
|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` |
| MODIFY (optional) | `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py` |
| CREATE | `packages/toolkit/tests/unit/test_materialize_dual_row.py` |
| CREATE | `packages/toolkit/tests/provenance/test_variants_mane_plus_clinical.py` |
| CREATE | `packages/toolkit/tests/determinism/test_materialize_dual_row_determinism.py` |
| CREATE | `packages/toolkit/tests/invariants/test_invE001_dual_row_evidence_ref.py` |

---

## Verification

```
# Phase 2 unit tests
pytest packages/toolkit/tests/unit/test_materialize_dual_row.py -v

# Provenance tests
pytest packages/toolkit/tests/provenance/test_variants_mane_plus_clinical.py -v

# Determinism tests
pytest packages/toolkit/tests/determinism/test_materialize_dual_row_determinism.py -v

# INV-E001 invariant test
pytest packages/toolkit/tests/invariants/test_invE001_dual_row_evidence_ref.py -v

# Full toolkit suite (no regressions, including all Phase 1 tests)
pytest packages/toolkit/tests/ -v
```

---

## Completion criteria

- [ ] `_consequence_tier` function exists and all tier-mapping tests pass.
- [ ] `_extract_dual_vep_rows` yields 2 rows when MANE Select and MANE Plus Clinical are both present with differing IMPACT tiers.
- [ ] `_extract_dual_vep_rows` yields 1 row in all other cases.
- [ ] `transcript_discordant` column exists in `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL`.
- [ ] `mane_plus_clinical_transcript` column exists in `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL`.
- [ ] Single-row consumer query (`WHERE transcript_discordant IS NULL OR transcript_discordant = false`) returns exactly one row per variant site in all provenance test fixtures.
- [ ] Both rows of a dual-row pair carry identical provenance column values (INV-R001).
- [ ] Both rows of a dual-row pair carry non-NULL `mane_select_transcript` or `mane_plus_clinical_transcript` (INV-E001).
- [ ] Determinism test passes: two materialize runs on the same fixture produce identical row sets.
- [ ] Full toolkit test suite passes with no regressions from Phases 1 and 2.
- [ ] `work-notes.md` updated.
- [ ] _(Forward note — applies to final phase, phase-3.md, when written)_ Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

---

## Handoff note to Phase 3

Phase 3 begins with `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL` already containing the two new columns (added here). Phase 3's job is to:
1. Bump `SCHEMA_VERSION` to `"v0.3"` and test the migration path (`_reset_variants_table` on a pre-existing v0.2 store).
2. Run the real-data smoke against the project owner's genome.
3. Verify the smoke produces at least one non-NULL `mane_plus_clinical_transcript` row.

Phase 3's plan is not written until Phase 2 is complete, per the planning protocol. The Phase 3 scope is described in `development-plan.md` Section "Phase Overview" row 3.

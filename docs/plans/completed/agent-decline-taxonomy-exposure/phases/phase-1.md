# Phase 1: Pydantic + DB + Invariant Test

**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Add `calibration_status` and `decline_reason` to `PgsRowResponse` and `PgsListRow` (Pydantic), widen the store query column tuples so the DB values flow through, and write the INV-A004 cross-language diff test that will go RED here (TypeBox not yet updated) and GREEN in Phase 2. All existing toolkit tests must stay green.

## Scope Boundaries

- **In scope**: `schemas/pgs.py`, `service/store.py`, unit tests for the models, integration test against a fixture DuckDB, INV-A004 invariant test (written here; expected to fail until Phase 2).
- **Out of scope**: TypeBox update in `index.ts` (Phase 2), system-prompt amendment (Phase 3), any change to the pipeline that writes `pgs_scores` rows, any schema version bump.

## Invariants Enforced in This Phase

- **INV-E001**: Tests assert that a declined row round-trips through `PgsRowResponse` without losing `calibration_status="decline"` and `decline_reason` — the agent cannot be served a row where the decline signal is stripped.
- **INV-A003**: Integration test asserts the full provenance payload (including both new fields) is returned by `query_pgs_computed` and `query_pgs_computed_list` from a fixture DB that has these columns populated.
- **NEW INV-A004** (RED state): `test_invA004_decline_taxonomy_traverse.py` is written and run; it fails because the TypeBox unions in `index.ts` do not yet list `calibration_status` / `decline_reason`. The test's RED output is expected and is pasted into `work-notes.md` to document the intentional state.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases**:

1. `test_pgs_row_response_includes_calibration_status_clean` — constructs `PgsRowResponse` with `calibration_status=CalibrationStatus.CLEAN` and `decline_reason=None`; asserts serialization includes `"calibration_status": "clean"` and `"decline_reason": null`.
2. `test_pgs_row_response_includes_calibration_status_decline` — constructs `PgsRowResponse` with `calibration_status=CalibrationStatus.DECLINE` and `decline_reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT`; asserts both fields serialize correctly.
3. `test_pgs_row_response_rejects_unknown_field` — constructs `PgsRowResponse` with an extra `rogue_field="x"` kwarg; asserts `ValidationError` is raised (confirms `extra="forbid"` still active after widening).
4. `test_pgs_list_row_includes_calibration_status` — constructs `PgsListRow` with `calibration_status=CalibrationStatus.WARNING` and `decline_reason=None`; asserts serialization includes the field.
5. `test_pgs_list_row_includes_decline_reason` — constructs `PgsListRow` with `calibration_status=CalibrationStatus.DECLINE` and `decline_reason=DeclineReason.POPULATION_TRANSFERABILITY_INSUFFICIENT`; asserts `decline_reason` serializes to `"population_transferability_insufficient"`.
6. `test_pgs_list_row_rejects_unknown_field` — same extra-field check as test 3 but for `PgsListRow`.
7. `test_invE001_pgs_decline_row_fields_not_stripped` — constructs a `PgsRowResponse` with `calibration_status=CalibrationStatus.DECLINE`; asserts `model.calibration_status == CalibrationStatus.DECLINE` (guards against accidental strip by a future serializer change). Named to enforce INV-E001.
8. `test_pgs_store_query_returns_calibration_status` (integration) — writes a fixture `pgs_scores` row with `calibration_status="decline"` and `decline_reason="variant_overlap_insufficient"` into a temp DuckDB; calls `query_pgs_computed(run_dir=..., pgs_id="PGS000099")`; asserts the returned dict contains `calibration_status="decline"` and `decline_reason="variant_overlap_insufficient"`.
9. `test_pgs_store_list_returns_calibration_status` (integration) — same fixture; calls `query_pgs_computed_list(run_dir=...)`; asserts the first row dict contains both fields.
10. `test_invA003_pgs_computed_provenance_complete` (integration) — asserts that `query_pgs_computed` returns a dict whose key set is exactly `set(PgsRowResponse.model_fields) | {"source_pgs_id"}` — no provenance field is absent. Named to enforce INV-A003.
11. `test_invA004_decline_taxonomy_traverse_calibration_status` (invariant) — reads `CalibrationStatus` Python enum values; reads `packages/nemoclaw-plugin/src/index.ts` as text; extracts the string literals from the `calibration_status` TypeBox union via regex; asserts set equality. **Expected to FAIL in Phase 1 because TypeBox is not yet updated.**
12. `test_invA004_decline_taxonomy_traverse_decline_reason` (invariant) — same as above for `DeclineReason`. **Expected to FAIL in Phase 1.**

**Sketch**:

```text
# packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py

from genomeclaw_toolkit.schemas.pgs import PgsRowResponse, PgsListRow
from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, DeclineReason
import pytest

MINIMUM_ROW_KWARGS = {
    "pgs_id": "PGS000099",
    "trait_label": "test trait",
    "percentile_in_user_ancestry": 55.0,
    "raw_score": 0.123,
    "source_pgs_id": "PGS000099",
    "study_population": "European",
    "calibration_warning": None,
    "agent_choice_rationale": "Testing purposes only, not a real analysis.",
    "requested_for_question": "test question",
    "superseded_by": None,
}

def test_pgs_row_response_includes_calibration_status_clean():
    row = PgsRowResponse(
        **MINIMUM_ROW_KWARGS,
        calibration_status=CalibrationStatus.CLEAN,
        decline_reason=None,
    )
    data = row.model_dump()
    assert data["calibration_status"] == "clean"
    assert data["decline_reason"] is None

def test_pgs_row_response_includes_calibration_status_decline():
    row = PgsRowResponse(
        **MINIMUM_ROW_KWARGS,
        calibration_status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
    )
    data = row.model_dump()
    assert data["calibration_status"] == "decline"
    assert data["decline_reason"] == "variant_overlap_insufficient"

# ... etc.
```

```text
# packages/toolkit/tests/integration/test_pgs_store_decline_projection.py

import duckdb, json
from pathlib import Path
from genomeclaw_toolkit.service.store import query_pgs_computed, query_pgs_computed_list

def _build_fixture_db(tmp_path: Path) -> Path:
    # Create the minimum pgs_scores table + one declined row.
    # Use the actual DDL column set from prep/store.py to avoid drift.
    db_path = tmp_path / "variants.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE pgs_scores (
            pgs_id TEXT,
            trait_label TEXT,
            percentile_in_user_ancestry DOUBLE,
            raw_score DOUBLE,
            study_population TEXT,
            calibration_warning TEXT,
            calibration_status TEXT,
            decline_reason TEXT,
            agent_choice_rationale TEXT,
            requested_for_question TEXT,
            superseded_by TEXT,
            ...  -- other columns per actual DDL
        )
    """)
    conn.execute("""
        INSERT INTO pgs_scores VALUES (
            'PGS000099', 'test trait', NULL, NULL, 'EUR',
            'Variant overlap too low for reliable score',
            'decline', 'variant_overlap_insufficient',
            'testing rationale', 'test question', NULL,
            ...
        )
    """)
    conn.close()
    return tmp_path

def test_pgs_store_query_returns_calibration_status(tmp_path):
    run_dir = _build_fixture_db(tmp_path)
    result = query_pgs_computed(run_dir=run_dir, pgs_id="PGS000099")
    assert result is not None
    assert result["calibration_status"] == "decline"
    assert result["decline_reason"] == "variant_overlap_insufficient"
```

```text
# packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py

import re
from pathlib import Path
from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, DeclineReason

_PLUGIN_PATH = Path(__file__).parents[5] / "packages/nemoclaw-plugin/src/index.ts"

def _extract_typebox_literals(source: str, field_name: str) -> set[str]:
    # Regex: find the Type.Union block for `field_name` and extract literals.
    # The exact pattern depends on how Phase 2 structures the TypeBox union.
    # Written to match the expected Phase 2 shape; fails cleanly if absent.
    pattern = rf'{re.escape(field_name)}.*?Type\.Union\(\[(.*?)\]\)'
    match = re.search(pattern, source, re.DOTALL)
    if not match:
        return set()
    literal_block = match.group(1)
    return set(re.findall(r'Type\.Literal\("([^"]+)"\)', literal_block))

def test_invA004_decline_taxonomy_traverse_calibration_status():
    """INV-A004: CalibrationStatus values must match TypeBox literals in index.ts."""
    source = _PLUGIN_PATH.read_text()
    python_values = {s.value for s in CalibrationStatus}
    typebox_values = _extract_typebox_literals(source, "calibration_status")
    assert python_values == typebox_values, (
        f"INV-A004 violation: Python CalibrationStatus values {python_values} "
        f"!= TypeBox literals {typebox_values} in {_PLUGIN_PATH}"
    )

def test_invA004_decline_taxonomy_traverse_decline_reason():
    """INV-A004: DeclineReason values must match TypeBox literals in index.ts."""
    source = _PLUGIN_PATH.read_text()
    python_values = {r.value for r in DeclineReason}
    typebox_values = _extract_typebox_literals(source, "decline_reason")
    assert python_values == typebox_values, (
        f"INV-A004 violation: Python DeclineReason values {python_values} "
        f"!= TypeBox literals {typebox_values} in {_PLUGIN_PATH}"
    )
```

After writing these tests, run them with `pytest packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py packages/toolkit/tests/integration/test_pgs_store_decline_projection.py packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py -v` and confirm:
- Tests 1-10 fail because the Pydantic models and store tuples don't have the fields yet.
- Tests 11-12 fail because the TypeBox unions don't exist yet.
Paste the full failing output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

**Files affected**:

- `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py`:
  - Add import: `from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, DeclineReason`
  - Add to `PgsRowResponse` (after `calibration_warning`): `calibration_status: CalibrationStatus` and `decline_reason: DeclineReason | None`
  - Add to `PgsListRow` (after `calibration_warning`): same two fields
  - Update the module docstring line that counts domain fields (currently says "6 domain fields")

- `packages/toolkit/src/genomeclaw_toolkit/service/store.py`:
  - `_PGS_SCORES_LIST_COLUMNS`: add `"calibration_status"` and `"decline_reason"` to the tuple (after `"calibration_warning"`)
  - `_PGS_SCORES_GET_COLUMNS`: same addition
  - No logic changes to `query_pgs_computed` or `query_pgs_computed_list` — they build dicts from the column tuples, so widening the tuples is sufficient

**Note on test 11 and 12 (INV-A004)**: after the Pydantic and store changes, tests 1-10 should turn GREEN. Tests 11-12 remain RED because Phase 2 has not updated TypeBox yet. This is expected. Record the RED output in `work-notes.md` and note it is intentional.

### Step 1.3 — REFACTOR

With tests 1-10 green and 11-12 intentionally red:

- Tighten the `_build_fixture_db` helper in the integration test: use the actual DDL from `prep/store.py` rather than a hand-rolled approximation. If the DDL helper in `store.py` is importable, import it.
- Verify the `_extract_typebox_literals` regex in the invariant test is robust against formatting variations in `index.ts` (single-line vs multi-line unions). Adjust if needed.
- Add a one-line comment above the INV-A004 tests noting they are intentionally RED until Phase 2.
- Re-run all toolkit tests to confirm no regressions.

---

## Implementation Details

### Field placement in PgsRowResponse

Insert the two new fields **after** `calibration_warning` and **before** `agent_choice_rationale`:

```python
calibration_warning: str | None
calibration_status: CalibrationStatus
decline_reason: DeclineReason | None
agent_choice_rationale: str = Field(min_length=1)
```

This grouping puts all calibration-related fields together. The `calibration_warning` free-text and the `calibration_status` machine-readable field sit adjacent.

### Field placement in PgsListRow

Insert after `calibration_warning`:

```python
calibration_warning: str | None
calibration_status: CalibrationStatus
decline_reason: DeclineReason | None
superseded_by: str | None
```

### Column ordering in store tuples

`_PGS_SCORES_LIST_COLUMNS`:
```python
_PGS_SCORES_LIST_COLUMNS: tuple[str, ...] = (
    "pgs_id",
    "trait_label",
    "percentile_in_user_ancestry",
    "calibration_warning",
    "calibration_status",
    "decline_reason",
    "superseded_by",
)
```

`_PGS_SCORES_GET_COLUMNS` — add `"calibration_status"` and `"decline_reason"` after `"calibration_warning"`.

### Fixture DuckDB construction

The integration test fixture must match the actual `pgs_scores` DDL in `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` (around line 200-240). Check that DDL before writing the fixture to avoid column-count mismatch in `zip(..., strict=True)`. The dict-build in `query_pgs_computed` uses `dict(zip(_PGS_SCORES_GET_COLUMNS, row, strict=True))` — column count must match exactly.

### Edge Cases to Handle

- A legacy row in the DB where `calibration_status` is NULL (from before Phase 3a): `CalibrationStatus` is a non-optional field in the Pydantic model. The Pydantic model will raise a `ValidationError` if the DB returns NULL. Resolution: the route handler in `app.py` that calls `PgsRowResponse(**row)` will surface this as a 500. Add a note in `work-notes.md`: the team should decide whether to make `calibration_status` optional with a `None` default or to accept that pre-Phase-3a rows will fail. Recommendation: check `prep/pgs.py` to confirm the writer always sets `calibration_status`; if confirmed, non-optional is safe.
- `decline_reason` being NULL when `calibration_status` is not "decline": this is correct and expected — the Pydantic `DeclineReason | None` type handles it.

### Error Handling

- `ValidationError` on NULL `calibration_status`: surface in the `pgs_computed_get` route as a 500 with a log message indicating a schema invariant violation. Do not silently return a partial response.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | MODIFY | Add `calibration_status` and `decline_reason` to `PgsRowResponse` and `PgsListRow` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | Add both columns to `_PGS_SCORES_LIST_COLUMNS` and `_PGS_SCORES_GET_COLUMNS` |
| `packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py` | CREATE | Unit tests for model construction + serialization |
| `packages/toolkit/tests/integration/test_pgs_store_decline_projection.py` | CREATE | Integration test: fixture DuckDB → store query → dict includes both fields |
| `packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py` | CREATE | Cross-language diff: Python enums vs TypeBox literals; RED until Phase 2 |

---

## Verification

```bash
# Phase 1 new tests — run from the repo root
cd /Users/hugi/GitRepos/GenomeClaw
uv run pytest packages/toolkit/tests/unit/schemas/test_pgs_decline_fields.py -v

uv run pytest packages/toolkit/tests/integration/test_pgs_store_decline_projection.py -v

# INV-A004 invariant tests — expected RED until Phase 2
uv run pytest packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py -v

# Full toolkit suite — must stay green (excluding the intentionally-RED INV-A004 tests)
uv run pytest packages/toolkit/tests/ --ignore=packages/toolkit/tests/invariants/test_invA004_decline_taxonomy_traverse.py -v

# Type check
uv run mypy packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py packages/toolkit/src/genomeclaw_toolkit/service/store.py

# Lint
uv run ruff check packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py packages/toolkit/src/genomeclaw_toolkit/service/store.py
```

---

## Completion Criteria

- [ ] Tests 1-10 pass (RED → GREEN → REFACTOR cycle visible in commits)
- [ ] Tests 11-12 fail with a clear assertion error naming the missing TypeBox fields (intentional RED; output pasted into `work-notes.md`)
- [ ] Mypy passes on the two modified source files
- [ ] Ruff passes on the two modified source files
- [ ] Full toolkit test suite (minus the intentionally-RED INV-A004 tests) passes
- [ ] No raw genomic data, secrets, or sample IDs in fixture files
- [ ] `work-notes.md` updated with RED step output, GREEN decisions, and note on intentional INV-A004 RED state
- [ ] Phase 1 status updated to "Complete" in `development-plan.md`
- [ ] _(Forward note — applies to final phase, phase-3.md, when written)_ Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

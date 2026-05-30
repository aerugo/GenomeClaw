# Phase 1: Project MANE Plus Clinical + Transcript Discordance Through the HTTP Layer

**Status**: Pending
**Plan**: [../development-plan.md](../development-plan.md)
**Parent meta-plan**: [../../finish-open-plans-meta/meta-plan.md](../../finish-open-plans-meta/meta-plan.md)

## Objective

Add `mane_plus_clinical_transcript` (`str | None`) + `transcript_discordant` (`bool | None`) to:

1. `VariantResponse` Pydantic model
2. `_VARIANTS_GET_COLUMNS` projection tuple
3. TypeBox `genomeclaw_variant` response schema

…and widen the `INV-A004` schema-diff test so this class of gap can't reopen on a different column.

## Invariants enforced in this phase

- **`INV-A004`** Decline / safety taxonomy must traverse every layer — widened verification: covers `variants` ↔ `VariantResponse` ↔ TypeBox with explicit allowlist for the seven provenance columns.
- **`INV-P002`** Minimal-sufficient agent payloads — bounded-scalar additions only.

## TDD Steps

### Step 1.1 — RED: write failing integration + invariant tests

#### `tests/integration/test_variants_api_exposes_mane_plus_clinical.py` (new)

```python
def test_variants_api_returns_mane_plus_clinical_field(real_data_client) -> None:
    """The /v1/variants/<key> endpoint MUST project mane_plus_clinical_transcript.

    Real-data row from derived/2026-05-25T19-42-58Z-c88e02: chr1-45345193-G-A is
    a transcript_discordant=true MUTYH variant (mane_plus_clinical_transcript=
    NM_001128425.2 in the variants table). The agent system prompt asks for this
    field; the HTTP layer must surface it.
    """
    resp = real_data_client.get("/v1/variants/chr1-45345193-G-A")
    assert resp.status_code == 200
    body = resp.json()
    assert "mane_plus_clinical_transcript" in body
    assert body["mane_plus_clinical_transcript"] == "NM_001128425.2"
    assert "transcript_discordant" in body
    assert body["transcript_discordant"] is True


def test_variants_api_returns_null_when_no_mane_plus_clinical(real_data_client) -> None:
    """For a variant without a MANE Plus Clinical transcript, the field is null (not omitted)."""
    # chr1:12901 (DDX11L1) — no MANE+ transcript in real data.
    resp = real_data_client.get("/v1/variants/chr1-12901-G-A")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mane_plus_clinical_transcript"] is None
    assert body["transcript_discordant"] is False
```

The `real_data_client` fixture lives in `tests/conftest.py` (existing pattern from `test_phase5_smoke_artifacts.py`); skips when `GENOMECLAW_REAL_DATA_RUN_DIR` is unset.

#### Extend the `INV-A004` schema-diff test (modify)

Locate the existing test (likely `tests/invariants/test_invA004_decline_taxonomy_traverses_layers.py` or similar — discover at execution). Add a parametrized case for the `variants` table covering the two new columns, plus the provenance-columns allowlist.

#### Update the `VariantResponse` field-bloat-guard test (modify)

Pattern from `test_pgs_decline_fields.py::test_pgs_row_response_model_pinned_shape` — pin the new fields explicitly so a future field add must update the test deliberately.

### Step 1.2 — GREEN: minimal implementation

1. **`packages/toolkit/src/genomeclaw_toolkit/schemas/variant.py`**:

   ```python
   class VariantResponse(BaseModel):
       model_config = ConfigDict(extra="forbid")
       # ... existing fields ...
       mane_select_transcript: str | None = None
       mane_plus_clinical_transcript: str | None = None  # NEW
       transcript_discordant: bool | None = None  # NEW
       # ... rest ...
   ```

2. **`packages/toolkit/src/genomeclaw_toolkit/service/store.py`** — `_VARIANTS_GET_COLUMNS`:

   ```python
   _VARIANTS_GET_COLUMNS = (
       # ... existing ...
       "mane_select_transcript",
       "mane_plus_clinical_transcript",  # NEW
       "transcript_discordant",  # NEW
       # ... rest ...
   )
   ```

3. **`packages/nemoclaw-plugin/src/index.ts`** — extend the `genomeclaw_variant` response schema:

   ```ts
   const VariantResponseSchema = Type.Object({
     // ... existing fields ...
     mane_select_transcript: Type.Union([Type.String(), Type.Null()]),
     mane_plus_clinical_transcript: Type.Union([Type.String(), Type.Null()]),  // NEW
     transcript_discordant: Type.Union([Type.Boolean(), Type.Null()]),  // NEW
     // ... rest ...
   });
   ```

### Step 1.3 — REFACTOR

- Verify the schema-diff invariant test now passes against both the widened scope (`variants` table) and the original (`pgs_scores` table).
- Ensure the provenance-columns allowlist is captured as a named constant, not inlined.
- Add a comment at the top of `_VARIANTS_GET_COLUMNS` pointing at INV-A004 so a future author understands why the projection tuple is the load-bearing piece.

## Files

| File | Action | Notes |
|------|--------|-------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/variant.py` | MODIFY | Add two `Field`s to `VariantResponse` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | Extend `_VARIANTS_GET_COLUMNS` |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | Extend TypeBox schema for `genomeclaw_variant` |
| `tests/integration/test_variants_api_exposes_mane_plus_clinical.py` | CREATE | Real-data + null-case probes |
| (existing) `test_pgs_decline_fields.py` analogue for `VariantResponse` | MODIFY | Update field pin |
| (existing) `tests/invariants/test_invA004_*` | MODIFY | Widen schema-diff scope |

## Verification

```bash
# Host venv (most tests run here)
cd packages/toolkit
uv run pytest tests/unit -k variant_response -v
uv run pytest tests/invariants -k invA004 -v

# Real-data integration probe (host service must be up against the bioreview-followup run)
GENOMECLAW_REAL_DATA_RUN_DIR=/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T19-42-58Z-c88e02 \
  uv run pytest tests/integration/test_variants_api_exposes_mane_plus_clinical.py -v

# Plugin tests
cd packages/nemoclaw-plugin
bun test src/index.test.ts
```

## Completion criteria

- [ ] New integration test passes against the real-data run.
- [ ] Existing `VariantResponse` field pin updated and passes.
- [ ] `INV-A004` schema-diff test now covers `variants` ↔ `VariantResponse` ↔ TypeBox.
- [ ] Plugin TypeBox schema declares both new fields.
- [ ] `/v1/variants/<discordant-key>` curl shows both fields populated.
- [ ] Plan moved from `active/` to `completed/`; back-reference added to `vep-mane-plus-clinical/work-notes.md`.

# Phase 3: Agent Surface — `region_class` + `caveat` in HTTP + Plugin + System Prompt

**Status**: Not started
**Estimated effort**: 2 days
**Prerequisite**: Phase 2 complete and merged.

---

## Objective

Surface `region_class` and a `caveat` string in the `GET /v1/gene/{symbol}` response and in the `genomeclaw_gene` plugin tool. Update the agent system prompt with an explicit instruction for non-standard `region_class` values. After Phase 3 the agent cannot see a mosdepth coverage number over PMS2 or SMN1 without also seeing a machine-readable signal that the number is not clinically informative.

---

## Invariants Enforced in This Phase

- **INV-E001** — The `region_class` flag and `caveat` string are the agent-facing evidence that a locus is not reliably callable. Exposing numeric coverage without these fields on a difficult region is an INV-E001 violation (the evidence does not support the implicit claim).
- **INV-C001** v1.7 — The `caveat` string is the structural mitigation against false reassurance. It must appear whenever `region_class != standard`; it must never appear for `standard` regions (that would dilute the signal).
- **INV-P002** — `caveat` is derived from `region_class`, which is a static per-class string, not from user variant data. It is safe to include in the agent-facing response.

---

## Step 3.1 — RED: Write Failing Tests

### Test file: `packages/toolkit/tests/unit/test_gene_response_caveat.py`

```
test_gene_response_has_region_class_field
    GeneResponse(gene="PMS2", n_variants_in_gene=0, mean_depth=30.0,
                 low_coverage_exons=[], schema_version="v0.2")
    → should have .region_class attribute; currently missing (extra="forbid" raises)

test_gene_response_caveat_non_null_for_difficult_pseudogene
    resp = GeneResponse(..., region_class="difficult_pseudogene", caveat=<computed>)
    assert resp.caveat is not None
    assert "challenging" in resp.caveat.lower()

test_gene_response_caveat_non_null_for_requires_dedicated_caller
    resp = GeneResponse(..., region_class="requires_dedicated_caller", ...)
    assert resp.caveat is not None

test_gene_response_caveat_non_null_for_mitochondrial
    resp = GeneResponse(..., region_class="mitochondrial", ...)
    assert resp.caveat is not None

test_gene_response_caveat_null_for_standard
    resp = GeneResponse(..., region_class="standard", caveat=None)
    assert resp.caveat is None

test_gene_response_caveat_null_for_none_region_class
    resp = GeneResponse(..., region_class=None, caveat=None)
    assert resp.caveat is None
```

### Test file: `packages/toolkit/tests/integration/test_gene_endpoint_region_class.py`

```
test_get_gene_endpoint_includes_region_class_and_caveat
    # Fixture: a store with a coverage_qc row where region_class = "difficult_pseudogene"
    # for gene "PMS2"
    client = TestClient(build_app(derived_root=...))
    resp = client.get("/v1/gene/PMS2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["region_class"] == "difficult_pseudogene"
    assert body["caveat"] is not None
    assert "challenging" in body["caveat"].lower()

test_get_gene_endpoint_no_caveat_for_standard_gene
    # Fixture: store with coverage_qc row where region_class = "standard" for "BRCA1"
    resp = client.get("/v1/gene/BRCA1")
    body = resp.json()
    assert body["region_class"] in ("standard", None)
    assert body["caveat"] is None
```

### Test file: `packages/toolkit/tests/invariants/test_invC001_region_class_caveat.py`

```
test_invC001_known_difficult_genes_have_caveat
    # INV-C001 v1.7: false reassurance on difficult regions is explicitly mitigated.
    # For each known difficult gene, construct a GeneResponse with the expected
    # region_class and assert caveat is non-null.
    difficult_genes = {
        "PMS2": "difficult_pseudogene",
        "SMN1": "requires_dedicated_caller",
        "HBA1": "difficult_segdup",
        "CYP21A2": "difficult_pseudogene",
        "GBA1": "difficult_pseudogene",
        "CYP2D6": "requires_dedicated_caller",
        "MT-RNR1": "mitochondrial",
    }
    for gene, rc in difficult_genes.items():
        resp = GeneResponse(gene=gene, n_variants_in_gene=0, mean_depth=30.0,
                           low_coverage_exons=[], schema_version="v0.2",
                           region_class=rc, caveat=_region_class_caveat(rc))
        assert resp.caveat is not None, f"{gene}: caveat should be non-null for {rc}"
```

### Test file: `packages/toolkit/tests/invariants/test_invP002_gene_caveat_no_user_data.py`

```
test_invP002_caveat_string_does_not_contain_user_data_markers
    # INV-P002: caveat is a static string; it must not contain rsid, genotype,
    # sample_id, or other user-derived fields.
    for rc in ["difficult_pseudogene", "difficult_segdup", "requires_dedicated_caller",
               "mitochondrial"]:
        caveat = _region_class_caveat(rc)
        assert caveat is not None
        # Should not look like it could contain variant data
        assert not re.search(r'rs\d+', caveat)
        assert not re.search(r'[ACGT]{2,}/[ACGT]{2,}', caveat)
```

---

## Step 3.2 — GREEN: Minimal Implementation

### File: `packages/toolkit/src/genomeclaw_toolkit/schemas/gene.py`

1. Add helper function:
   ```python
   def _region_class_caveat(region_class: str | None) -> str | None:
       """Map region_class to a standard caveat string, or None for standard/null."""
       _STANDARD = {"standard", None}
       if region_class in _STANDARD:
           return None
       _CAVEAT = (
           "Coverage depth over this region is not sufficient to confirm variant "
           "callability. This locus is in a known technically challenging region for "
           f"short-read WGS (region_class: {region_class}); pathogenic variants may be "
           "missed or miscalled. Seek orthogonal confirmation (e.g. long-read sequencing, "
           "gene-specific assay, or a dedicated caller such as Cyrius for CYP2D6)."
       )
       return _CAVEAT
   ```

2. `GeneResponse` model:
   - Add `region_class: str | None = None`
   - Add `caveat: str | None = None`

### File: `packages/toolkit/src/genomeclaw_toolkit/service/store.py`

`GeneAggregate` already gained `region_class` in Phase 1. No further changes needed here.

### File: `packages/toolkit/src/genomeclaw_toolkit/service/app.py`

In the `/v1/gene/{symbol}` handler (line ~469), update `GeneResponse` construction:

```python
from genomeclaw_toolkit.schemas.gene import GeneResponse, GeneErrorResponse, _region_class_caveat

payload = GeneResponse(
    gene=aggregate.canonical_symbol,
    n_variants_in_gene=aggregate.n_variants_in_gene,
    mean_depth=aggregate.mean_depth,
    low_coverage_exons=aggregate.low_coverage_exons,
    schema_version=active.schema_version,
    region_class=aggregate.region_class,
    caveat=_region_class_caveat(aggregate.region_class),
)
```

### File: `packages/nemoclaw-plugin/src/index.ts`

Update `genomeclaw_gene` tool description to mention `region_class` and `caveat`:

```typescript
description:
  "Aggregate per-gene summary for an HGNC symbol: variant count, mean coverage depth, " +
  "list of exons below the low-coverage threshold, and (for the curated subset) " +
  "region_class and caveat. When region_class is not 'standard' or is present, " +
  "the caveat field contains an explicit warning that coverage depth is not sufficient " +
  "to confirm variant callability for this locus. Always surface the caveat to the user " +
  "when it is non-null. Resolves case-insensitively.",
```

### File: `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`

Add a new clause in the tool-guidance section, after the `genomeclaw_gene` bullet in the tools table. Insert before or after the existing "blind-spot gene" clause at lines 259-263:

```markdown
**Coverage reliability for technically challenging genes**

When `genomeclaw_gene` returns a non-null `caveat` field (present whenever `region_class`
is not `standard`), the coverage report **must** explicitly include the caveat verbatim
or paraphrase it. Do not interpret `mean_depth` as confirmation of variant callability
for these loci. The canonical disclaimer: "this region is technically uncallable /
unreliable by short-read WGS — a normal coverage depth does not confirm that pathogenic
variants would have been detected."

The existing prose warning for blind-spot genes (PMS2, SMN1, CYP21A2, HLA region, etc.)
remains in effect and is now reinforced by the machine-readable `region_class` signal.
```

---

## Step 3.3 — REFACTOR

- Export `_region_class_caveat` from `schemas/gene.py` `__all__` (it is used in tests and in `app.py`; making it semi-public with a leading underscore convention is fine for internal use).
- Add a comment in `GeneResponse` explaining that `caveat` is derived from `region_class` at the route layer and is never stored in the DB.
- Ensure `GeneResponse` snapshot tests (if any) are updated to include the new fields.

---

## Files Modified in Phase 3

| Action | File |
|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/schemas/gene.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/service/app.py` |
| MODIFY | `packages/nemoclaw-plugin/src/index.ts` |
| MODIFY | `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` |
| CREATE | `packages/toolkit/tests/unit/test_gene_response_caveat.py` |
| CREATE | `packages/toolkit/tests/integration/test_gene_endpoint_region_class.py` |
| CREATE | `packages/toolkit/tests/invariants/test_invC001_region_class_caveat.py` |
| CREATE | `packages/toolkit/tests/invariants/test_invP002_gene_caveat_no_user_data.py` |

---

## Verification

```bash
# Unit + integration:
uv run pytest packages/toolkit/tests/unit/test_gene_response_caveat.py -v
uv run pytest packages/toolkit/tests/integration/test_gene_endpoint_region_class.py -v

# Invariant tests:
uv run pytest packages/toolkit/tests/invariants/test_invC001_region_class_caveat.py -v
uv run pytest packages/toolkit/tests/invariants/test_invP002_gene_caveat_no_user_data.py -v

# Full suite — no regressions:
uv run pytest packages/toolkit/tests/ -v

# TypeScript build check (nemoclaw-plugin):
cd packages/nemoclaw-plugin && npm run build
```

---

## Completion Criteria

- [ ] `GeneResponse` has `region_class` and `caveat` fields.
- [ ] `_region_class_caveat()` helper maps each non-standard `region_class` to a non-null string containing "challenging".
- [ ] `_region_class_caveat("standard")` and `_region_class_caveat(None)` return `None`.
- [ ] `/v1/gene/{symbol}` returns `region_class` and `caveat` in JSON.
- [ ] `genomeclaw_gene` tool description updated.
- [ ] Agent system prompt updated with `region_class`/`caveat` instruction.
- [ ] All Phase 3 tests green.
- [ ] Full toolkit test suite green (zero regressions).
- [ ] TypeScript build clean.
- [ ] `work-notes.md` updated with Phase 3 completion block.
- [ ] Phase 3 status updated in `development-plan.md`.
- [ ] Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

---

## Stage 2 Exit Gate (after Phase 3 merges)

Per the meta-plan Stage 2 exit gate (`bioreview-followup-meta/meta-plan.md` line 123-126):

1. Coverage panel v2 BED contains all 84 ACMG SF v3.3 genes. [Phase 2]
2. PMS2 / SMN1 / HBA1 / CYP21A2 / GBA1 / STRC / NCF1 / NEB / HLA carry `region_class ∈ {difficult_pseudogene, difficult_segdup, requires_dedicated_caller}`. [Phase 2]
3. `genomeclaw_gene` tool response surfaces `region_class` and an explanatory `caveat` string when non-null. [Phase 3 — this phase]
4. Real-data host smoke against the project owner's genome: rebuilds `variants.duckdb` end-to-end on the new coverage panel; manifest records new schema version. [Phase 2 smoke + Phase 3 smoke reconfirmation]

Move plan to `docs/plans/completed/coverage-panel-v2/` after all four criteria are met and the meta-plan progress table is updated.

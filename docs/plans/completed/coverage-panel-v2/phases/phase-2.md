# Phase 2: Panel Content v2 Rebuild

**Status**: Not started
**Estimated effort**: 3 days
**Prerequisite**: Phase 1 complete and merged.

---

## Objective

Build `coverage_panel_default_v2.bed.gz` and its provenance JSON. Update `ingest.py` constants to point to v2 as the default panel. Promote INV-D009 by writing and verifying the GIAB intersection test.

At the end of Phase 2:
- `coverage_panel_default_v2.bed.gz` is the bundled default panel.
- The v2 panel includes all 84 ACMG SF v3.3 genes, lifestyle anchors, MT contig rows, and `region_class` annotations for all known difficult-region genes.
- `coverage_panel_default_v1.bed.gz` remains on disk as a reference; it is not deleted.
- INV-D009 test passes: no row in the panel BED that intersects the GIAB challenging-MRG BED has `region_class = "standard"`.
- The real-data smoke GREEN gate is met (see below).

---

## Invariants Enforced in This Phase

- **INV-D001** — `data/reference/` and `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz` are not modified. The GIAB BED is fetched into `data/reference/giab/`; the v2 panel is written to `data/` (package asset).
- **INV-R001** — `coverage_panel_default_v2.bed.provenance.json` records: ACMG SF version, GENCODE version, GIAB BED version + URL + checksum, build script path, build date, column definitions, schema version token. Rebuild command is documented in `development-plan.md`.
- **INV-P001** — No user data egress. GIAB BED is a public reference; it is fetched via `genomeclaw refs fetch` or the `scripts/build_coverage_panel_v2.py` build step (one-time, operator-side, no user variant data in the request).
- **INV-D009 (proposed)** — verified here for the first time. Promoted into `docs/reference/INVARIANTS.md` after this phase's test merges.

---

## Step 2.0 — Pre-flight: GIAB BED Acquisition

Before writing tests, confirm:

1. **GIAB challenging-MRG BED canonical URL**: `https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/genome-stratifications/v3.3/GRCh38@all/Challenges/GRCh38_MedicallyRelevantGenes_v1.00.bed.gz` (Wagner et al., *Nat Biotechnol* 2022; NCBI public domain).

2. **Add to `fetch.py _LAYOUTS`**: new entry `"giab_mrg"` with the above URL. This enables `genomeclaw refs fetch giab_mrg` as the operator-facing fetch command, consistent with how `clinvar`, `gnomad`, and `grch38` are fetched.

3. **Confirm the BED is in `data/reference/giab/`** before running Phase 2 tests that use it. The Phase 2 integration test that enforces INV-D009 requires the GIAB BED to be present; mark the test with `@pytest.mark.requires_giab_mrg_bed` and gate it in CI accordingly (similar to how real-data smokes are gated). In local development the operator runs `genomeclaw refs fetch giab_mrg` once.

---

## Step 2.1 — RED: Write Failing Tests

### Test file: `packages/toolkit/tests/invariants/test_invD009_panel_giab_intersection.py`

```
@pytest.mark.requires_giab_mrg_bed
test_invD009_panel_v2_giab_intersection_no_standard_rows
    # INV-D009: any panel gene that intersects GIAB challenging-MRG must
    # carry region_class != "standard".
    #
    # Intersection method: read both BEDs into memory; for each panel row,
    # check if (chrom, start, end) overlaps any GIAB row; collect all
    # panel rows that overlap. Assert none have region_class == "standard".
    panel = read_bed5("packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.gz")
    giab = read_bed_intervals("data/reference/giab/GRCh38_MedicallyRelevantGenes_v1.00.bed.gz")
    overlapping = [r for r in panel if overlaps_any(r.chrom, r.start, r.end, giab)]
    assert all(r.region_class != "standard" for r in overlapping), \
        f"Panel rows overlapping GIAB challenging-MRG with region_class=standard: " \
        f"{[r.name for r in overlapping if r.region_class == 'standard']}"
```

### Test file: `packages/toolkit/tests/unit/test_panel_v2_content.py`

```
test_panel_v2_has_acmg_sf_v33_genes
    panel_genes = read_panel_genes("coverage_panel_default_v2.bed.gz")
    for gene in ["ABCD1", "CYP27A1", "PLN"]:
        assert gene in panel_genes, f"ACMG SF v3.3 gene {gene} missing from v2 panel"

test_panel_v2_has_lifestyle_anchors
    for gene in ["MC1R", "MCM6", "HFE", "FUT2"]:
        assert gene in panel_genes, f"Lifestyle anchor {gene} missing from v2 panel"

test_panel_v2_has_mt_rows
    mt_rows = [r for r in read_bed5("coverage_panel_default_v2.bed.gz") if r.chrom in ("chrMT", "MT")]
    assert len(mt_rows) > 0, "No mitochondrial rows in v2 panel"
    assert all(r.region_class == "mitochondrial" for r in mt_rows)

test_panel_v2_difficult_regions_annotated
    panel = read_bed5("coverage_panel_default_v2.bed.gz")
    checks = {
        "PMS2": "difficult_pseudogene",
        "SMN1": "requires_dedicated_caller",
        "HBA1": "difficult_segdup",
        "CYP21A2": "difficult_pseudogene",
        "GBA1": "difficult_pseudogene",
        "STRC": "difficult_pseudogene",
        "NCF1": "difficult_pseudogene",
        "NEB": "difficult_segdup",
        "CYP2D6": "requires_dedicated_caller",
    }
    by_gene = group_by_gene(panel)
    for gene, expected_class in checks.items():
        if gene in by_gene:
            actual = {r.region_class for r in by_gene[gene]}
            # All exons of a difficult gene must carry the flag; no mixing with standard
            assert expected_class in actual, f"{gene}: expected region_class {expected_class}, got {actual}"

test_panel_v2_provenance_json_fields
    prov = read_json("coverage_panel_default_v2.bed.provenance.json")
    assert prov["version"] == "v2"
    assert "difficult_region_annotations" in prov["source"]
    assert prov["source"]["difficult_region_annotations"]["source"] == "GIAB_MRG_v1.00"
    assert "schema_version" in prov  # e.g. "bed5_v1"
    assert "gene_count" in prov
    assert prov["gene_count"] >= 170  # v1 was 160; v2 adds ~15 new genes
```

### Test file: `packages/toolkit/tests/determinism/test_panel_v2_deterministic.py`

```
test_panel_build_is_deterministic
    # Run build script twice; diff the two output BEDs byte-for-byte.
    # Gated: @pytest.mark.requires_reference_data (needs GENCODE GTF + GIAB BED)
    run_build_script(out1)
    run_build_script(out2)
    assert file_sha256(out1) == file_sha256(out2)
```

---

## Step 2.2 — GREEN: Build the v2 Panel

### 2.2a — Fetch GIAB BED

Add `"giab_mrg"` to `_LAYOUTS` in `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py`:

```python
"giab_mrg": _SourceLayout(
    files=[
        _FileSpec(
            relpath="GRCh38_MedicallyRelevantGenes_v1.00.bed.gz",
            url="https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/"
                "genome-stratifications/v3.3/GRCh38@all/Challenges/"
                "GRCh38_MedicallyRelevantGenes_v1.00.bed.gz",
        )
    ],
    target_subdir="giab",
),
```

Run `genomeclaw refs fetch giab_mrg --reference-dir data/reference/`.

### 2.2b — Build script: `scripts/build_coverage_panel_v2.py`

New script (not committed to pipeline code; it is a reference-data build script analogous to the v1 BED build script). It:

1. Reads GENCODE v44 GTF (same source as v1: `gencode.v44.primary_assembly.annotation.gtf.gz`).
2. Resolves MANE Select transcripts for all target genes (same logic as v1 build script, per provenance JSON `extraction.tool`).
3. Target gene list (union, deduplicated):
   - All genes from `coverage_panel_default_v1.bed.provenance.json` (160 genes)
   - New ACMG SF v3.3 additions: ABCD1, CYP27A1, PLN
   - Lifestyle anchors: MC1R, MCM6 (covers LCT regulatory region), HFE, FUT2
   - HLA panel: HLA-A, HLA-B, HLA-C, HLA-DRB1 (flagged `requires_dedicated_caller`)
   - SMN1, SMN2 (if not already present; flagged `requires_dedicated_caller`)
4. MT contig: include full MT contig as a single region `(chrMT, 0, 16569, chrMT_full)` with `region_class = mitochondrial`, OR enumerate known MT gene exons from GENCODE v44. Recommendation: use GENCODE MT gene annotations to produce per-gene rows (MT-RNR1, MT-ND1, MT-CO1, etc.) with `region_class = mitochondrial`.
5. For each exon row, assign `region_class`:
   - Default: `standard`
   - Intersect with GIAB challenging-MRG BED: any row overlapping a GIAB interval gets the GIAB-derived class (mapped from the GIAB BED's 4th column or gene name to the five allowed values via a hardcoded classification table in the build script).
   - Explicit overrides for known classes not fully covered by GIAB overlap (e.g., NEB VNTR may not be in GIAB MRG BED for all exons).
6. Sort output: `chrom` (lexicographic, chrM/chrMT at end), then `start` (numeric).
7. bgzip + tabix index the output BED.
8. Write `coverage_panel_default_v2.bed.provenance.json` with all required fields.

### 2.2c — Manual verification checklist before committing the BED

After running the build script, verify:
- [ ] `zcat coverage_panel_default_v2.bed.gz | cut -f4 | sort -u | grep "^PMS2"` shows exon rows
- [ ] `zcat coverage_panel_default_v2.bed.gz | awk '$5 == "standard" && $4 ~ /^PMS2/' | wc -l` == 0 (PMS2 exons 11-15 not standard)
- [ ] `zcat coverage_panel_default_v2.bed.gz | awk '$1 == "chrMT"' | head -5` shows MT rows
- [ ] `zcat coverage_panel_default_v2.bed.gz | awk '$5 == "mitochondrial"' | wc -l` > 0
- [ ] Gene count ≥ 170 (v1: 160; adds ~15 new genes)
- [ ] `zcat coverage_panel_default_v2.bed.gz | awk 'NF != 5' | wc -l` == 0 (every row is BED5)

### 2.2d — Update `ingest.py` constants

```python
_DEFAULT_PANEL_BED_NAME = "coverage_panel_default_v2.bed.gz"
_DEFAULT_PANEL_VERSION = "v2"
```

---

## Step 2.3 — REFACTOR

- Add `_GIAB_MRG_DIFFICULT_CLASS_MAP` table in the build script mapping GIAB gene names to `region_class` values, with a comment citing Wagner et al. 2022.
- Add a docstring to the build script describing the rebuild command.
- Update `COVERAGE_QC_COLUMNS` comment in `schemas/coverage_qc.py` to note that `region_class` values come from the panel BED at ingest time.

---

## Post-Phase-2: Promote INV-D009

After the `test_invD009_panel_v2_giab_intersection_no_standard_rows` test merges and is green in CI:

1. Update `docs/reference/INVARIANTS.md`:
   - Add `INV-D009` under the `INV-D` category.
   - Rule text as proposed in `spec.md`.
   - `Version` and `Last Updated` bumped.
   - Invariant Index table appended.
2. Note promotion in `work-notes.md`.

---

## Real-Data Smoke Gate (GREEN gate for Phase 2)

Run `genomeclaw pipeline run` against the project owner's genome with the v2 panel. Target: ≤30 min wall-clock.

Pass criteria:
1. `coverage_qc` rows for PMS2 carry `region_class = "difficult_pseudogene"`.
2. `coverage_qc` rows for SMN1 carry `region_class = "requires_dedicated_caller"`.
3. `coverage_qc` rows for CYP2D6 carry `region_class = "requires_dedicated_caller"`.
4. MT contig rows present with `region_class = "mitochondrial"`.
5. Total `coverage_qc` row count ≥ 1500 (v1 had 2798 exon rows; v2 should have more).
6. `manifest.json` records `panel_version = "v2"`.
7. `provenance.json` mosdepth step records `panel_path = "coverage_panel_default_v2.bed.gz"`.

---

## Files Created / Modified in Phase 2

| Action | File |
|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` (add `giab_mrg` layout) |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` (bump `_DEFAULT_PANEL_BED_NAME` + `_DEFAULT_PANEL_VERSION`) |
| CREATE | `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.gz` |
| CREATE | `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.provenance.json` |
| CREATE | `scripts/build_coverage_panel_v2.py` |
| MODIFY | `docs/reference/INVARIANTS.md` (promote INV-D009) |
| CREATE | `packages/toolkit/tests/invariants/test_invD009_panel_giab_intersection.py` |
| CREATE | `packages/toolkit/tests/unit/test_panel_v2_content.py` |
| CREATE | `packages/toolkit/tests/determinism/test_panel_v2_deterministic.py` |

---

## Verification

```bash
# Content tests (no reference data needed):
uv run pytest packages/toolkit/tests/unit/test_panel_v2_content.py -v

# INV-D009 test (requires GIAB BED in data/reference/giab/):
uv run pytest packages/toolkit/tests/invariants/test_invD009_panel_giab_intersection.py \
  -v -m requires_giab_mrg_bed

# Determinism test (requires full reference data):
uv run pytest packages/toolkit/tests/determinism/test_panel_v2_deterministic.py \
  -v -m requires_reference_data

# Full suite regression check:
uv run pytest packages/toolkit/tests/ -v
```

---

## Completion Criteria

- [ ] `coverage_panel_default_v2.bed.gz` committed to package data directory.
- [ ] `coverage_panel_default_v2.bed.provenance.json` committed.
- [ ] `scripts/build_coverage_panel_v2.py` committed with rebuild command in docstring.
- [ ] `fetch.py` `_LAYOUTS` has `"giab_mrg"` entry.
- [ ] `ingest.py` defaults updated to `v2`.
- [ ] All Phase 2 unit and content tests green.
- [ ] `test_invD009_panel_v2_giab_intersection_no_standard_rows` green with GIAB BED present.
- [ ] INV-D009 promoted into `docs/reference/INVARIANTS.md`.
- [ ] Real-data smoke passes (all 7 criteria above).
- [ ] Full toolkit test suite green (zero regressions).
- [ ] `work-notes.md` updated with Phase 2 completion block.
- [ ] Phase 2 status updated in `development-plan.md`.

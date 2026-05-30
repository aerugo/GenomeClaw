# Spec: Coverage Panel v2 + Difficult-Region Annotations

**Status**: Draft
**Created**: 2026-05-25
**Plan dir**: `docs/plans/active/coverage-panel-v2/`
**Parent meta-plan**: [`docs/plans/active/bioreview-followup-meta/meta-plan.md`](../bioreview-followup-meta/meta-plan.md)
**Stage**: 2 (parallel with `vep-mane-plus-clinical`)
**Estimated effort**: 8 days

---

## Goal

Extend the bundled coverage panel from BED4 to BED5 with a `region_class` column; upgrade panel content to ACMG SF v3.3, add lifestyle-anchor genes, add mitochondrial coverage, and annotate known difficult-to-call regions so the agent and user are never falsely reassured by a numeric depth value over a clinically uncallable locus.

---

## Background

A bioinformatics expert reviewed GenomeClaw on 2026-05-25 and identified four coverage-panel gaps:

1. **ACMG SF v3.2 → v3.3**. The current panel pins ACMG SF v3.2 (`coverage_panel_default_v1.bed.provenance.json` line 7). ACMG SF v3.3 (Lee et al., *Genetics in Medicine* 27(8):101454, 2025-07-09) adds ABCD1, CYP27A1, PLN — total now 84 genes.

2. **Missing lifestyle / population-genetics anchors**. APOE is present but MC1R, LCT/MCM6, HFE, FUT2 are not — the most-asked-about genes in consumer personal-genomics contexts.

3. **No difficult-region flags**. The current BED4 (`chrom, start, end, GENE_exon_N`) gives mosdepth a numeric `mean_depth` over loci like PMS2 exons 11-15 that are clinically uncallable from short-read WGS due to the PMS2CL pseudogene. Without explicit flags the user gets falsely reassured. GIAB "challenging medically relevant genes" benchmark (Wagner et al., *Nat Biotechnol* 2022) is the authoritative reference.

4. **Missing mitochondrial coverage**. MT-RNR1 is a CPIC actionable gene (aminoglycoside ototoxicity); the current panel has no MT contig rows.

The agent's system prompt today lists PMS2, CYP21A2, SMN1, HLA, and related genes in a "systematic-blind-spot" clause but the disclaimer lives only in prose — there is no machine-readable signal that allows the tool response itself to carry the caveat. A user who asks only `genomeclaw_gene(gene="PMS2")` gets a numeric mean depth and no warning.

---

## Acceptance Criteria

1. **BED format is BED5** after Phase 1. Column 5 is `region_class` ∈ `{standard, difficult_pseudogene, difficult_segdup, requires_dedicated_caller, mitochondrial}`. All existing rows default to `standard`.

2. **`coverage_qc` schema has a `region_class` column** after Phase 1. Type `TEXT`, nullable (NULL ≡ `standard` for any pre-v2 rows that may exist in a loaded store).

3. **Panel v2 BED content** after Phase 2:
   - All 84 ACMG SF v3.3 genes present (adds ABCD1, CYP27A1, PLN over v3.2).
   - Lifestyle anchors present: MC1R, LCT (via MCM6 regulatory region), HFE, FUT2.
   - MT-RNR1 present with `region_class = mitochondrial`. At minimum the MT-RNR1 exons; consider the full MT contig (16.6 kb).
   - All known difficult regions annotated:
     - PMS2 exons 11-15 → `difficult_pseudogene`
     - SMN1, SMN2 → `requires_dedicated_caller`
     - HBA1, HBA2 → `difficult_segdup`
     - CYP21A2 → `difficult_pseudogene`
     - GBA1 → `difficult_pseudogene`
     - STRC → `difficult_pseudogene`
     - NCF1 → `difficult_pseudogene`
     - NEB → `difficult_segdup` (VNTR)
     - HLA region genes (HLA-A, HLA-B, HLA-C, HLA-DRB1, etc.) → `requires_dedicated_caller`
     - CYP2D6 → `requires_dedicated_caller` (already handled by Cyrius, but flagged in coverage)

4. **INV-D009 test green** after Phase 2: intersect the v2 panel BED against the GIAB challenging-MRG BED and assert every intersection carries a non-`standard` `region_class`.

5. **`/v1/gene/{symbol}` response** after Phase 3 includes `region_class` and a non-null `caveat` string when `region_class` is not `standard`. Specifically: `"This region is technically uncallable or unreliable by short-read WGS — do not interpret coverage_qc mean_depth as adequate confirmation of variant callability."` (exact wording may be refined in implementation, but must convey the non-callability explicitly).

6. **Agent system prompt** updated after Phase 3 to instruct the agent: "if `region_class != standard`, the coverage report must explicitly say this region is technically uncallable / unreliable by short-read WGS — do not interpret coverage_qc as adequate."

7. **Schema version bumped** in `coverage_qc` and the panel provenance JSON.

8. **Panel is rebuilable from scratch** with a documented build command (INV-R001).

9. **All existing toolkit tests remain green** after each phase.

---

## Applicable Invariants

- **INV-D001** — Raw genomic files are source-of-truth artifacts. The new panel BED lives in `packages/toolkit/src/genomeclaw_toolkit/data/` as a bundled package asset. The GIAB challenging-MRG BED lives in `data/reference/`. Neither is a derived artifact. `coverage_panel_default_v1.bed.gz` is never overwritten; the new file is `coverage_panel_default_v2.bed.gz`.

- **INV-E001** — Evidence & traceability. The `region_class` column is provenance for "this is not a callable region." When the agent surfaces a coverage value over a difficult-region locus without a `region_class` flag, the evidence is materially misleading. This invariant makes the flag structural, not annotational.

- **INV-R001** — Rebuildability. The panel BED is a versioned derived artifact of the build script + source gene lists + GENCODE v44 coordinates. The `coverage_panel_default_v2.bed.provenance.json` must record: source gene lists, ACMG SF version, GENCODE version, build script path, build date, GIAB challenging-MRG BED version used for annotation, schema version, and column definitions.

- **INV-C001** v1.7 — Research/clinical boundary. False reassurance on PMS2 exons 11-15 (or any other difficult-region gene) is a clinical-impact risk. The `region_class` flag + `caveat` string in the tool response is the structural mitigation. This plan directly reduces the false-reassurance risk identified by the reviewer.

- **INV-P001** — Privacy default. No new egress. The GIAB BED is a public reference dataset; if not already in `data/reference/`, it is fetched via `genomeclaw refs fetch` (the existing reference-data fetch path) and never sends user data out.

---

## Proposed New Invariant

**INV-D009** — Coverage Panel Difficult-Region Annotations.

_Rule_: Any gene or region in the coverage panel that intersects a GIAB challenging medically relevant gene (MRG) region must carry a non-null `region_class` value that is not `standard`. Verified by a CI test that downloads (or reads from cache) the GIAB challenging-MRG BED, intersects it against the panel BED, and asserts every intersection row has `region_class ∈ {difficult_pseudogene, difficult_segdup, requires_dedicated_caller, mitochondrial}`.

_Rationale_: Numeric coverage depth over a GIAB-annotated challenging region is not clinically informative and may actively mislead. The structural annotation removes the false-reassurance pathway without suppressing the number (the agent and user can still see the depth — they are simply told it does not confirm callability).

---

## Out of Scope

- Switching mosdepth to per-base mode (Phase 4B territory; not in this plan).
- Adding new annotation sources (ClinVar, gnomAD, etc.) to the coverage panel — this is an enrichment of the BED geometry and region classification, not a variant annotation pipeline.
- Fetching or caching external per-gene coverage databases (e.g., gnomAD coverage files) — deferred.
- Auto-updating the panel from ACMG on a schedule — out of scope for this plan; a future `genomeclaw refs check` command would own that.
- Force-genotyping (that is Stage 3, `force-genotype-callable-mask`).
- SMN1/SMN2 dedicated-caller integration — only flagging `requires_dedicated_caller`; the caller itself is out of scope.

---

## Privacy & Safety Considerations

- No user genomic data is transmitted. The GIAB BED is a public reference. All processing is local.
- The `region_class` flag and `caveat` string flow from the host service to the agent. Under INV-P002 (minimal-sufficient) the `caveat` is non-null only when `region_class` is non-standard — this is the minimum needed for the agent to avoid false reassurance.
- The `caveat` string must not contain user-derived data (it is a static per-region-class string from the schema layer, not from the variants table).

---

## Open Questions

1. **Full MT contig vs. MT-RNR1 only**: The MT contig is 16.6 kb; including all exons adds ~100 rows. Recommendation is the full MT contig with `region_class = mitochondrial` on all MT rows — the overhead is negligible and excludes nothing. To be confirmed in Phase 2 design.

2. **GIAB BED availability**: The GIAB challenging-MRG BED (Wagner et al., 2022) is not currently in `data/reference/`. It needs to be added to `fetch.py`'s `_LAYOUTS`. The canonical URL is the NCBI FTP (public domain). Confirm this in Phase 2.

3. **Schema version**: Adding `region_class` to `coverage_qc` is a schema change. The current `SCHEMA_VERSION` should be bumped. Confirm the bump strategy (new constant vs. in-place change) with the VEP-MANE-Plus-Clinical plan team, since both plans bump schema version in Stage 2 and should not conflict.

4. **HLA gene list**: The HLA region contains dozens of named genes. The v1 panel (via the `neurodegeneration` sysprompt panel) does not include HLA genes. For v2 we need to decide: include HLA-A, HLA-B, HLA-C, HLA-DRB1 (the four clinically most relevant) and flag all as `requires_dedicated_caller`? Recommendation: yes, include the four above. To be confirmed.

5. **`caveat` string location**: Phase 3 proposes generating the `caveat` string from `region_class` at the service layer (`service/store.py` → `GeneAggregate`) or the Pydantic schema layer (`schemas/gene.py`). Keeping it at the schema layer as a class method mapping `region_class → caveat_str` is cleaner. Decision deferred to Phase 3.

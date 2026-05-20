# PGS Site Allele Orientation Against Reference Fasta

**Status**: Active
**Created**: 2026-05-20
**Owner**: hugi
**Lineage**: F7 of [prs-runtime-hardening](../../completed/prs-runtime-hardening/) — the actual root cause smoke v17's empty-cache guard surfaced.

---

## Goal

Fix the Tier 2 forced-genotyping wrapper so `bcftools call --constrain alleles` accepts the wrapper's emitted alleles file: orient each PGS site's REF/ALT against the actual reference base in the GRCh38 fasta (per-site lookup), not against the PGS Catalog "convention" the current code assumes.

## Background

The PRS pipeline's Tier 2 step force-genotypes the user's CRAM at every site in the PGS scoring file. The wrapper currently extracts `(chrom, pos, other_allele, effect_allele)` from the scoring file and assigns `REF = other_allele, ALT = effect_allele` based on the PGS Catalog convention that `other_allele` is the reference allele.

This convention is **partly true** — PGS Catalog `hmPOS_GRCh38` scorefiles are harmonised to the GRCh38 forward strand for COORDINATES, but the `effect_allele` / `other_allele` orientation relative to the reference base is **not guaranteed**. For variants where:
- The effect is on the **reverse strand** (some scorefiles), `effect_allele` is the complement of what's on the GRCh38 forward strand.
- The original scorefile had `effect_allele = REF` (perfectly valid for "this allele increases risk" semantics), the convention's assumed roles are reversed.
- `hm_inferOtherAllele` is populated, the other_allele was inferred and may be wrong.

When the wrapper hands `bcftools call --constrain alleles --targets-file alleles.tsv` a row like `chr1\t21806025\tA,G` but the actual GRCh38 reference at that position is `G`, bcftools rejects the row with the note "The reference alleles are not compatible at chr1:21806025 .. A vs G" and emits no genotype call. Phase 7 smoke v17 (2026-05-20) surfaced this — Tier 2's bcftools pipe produced 0 records over 1.7M PGS sites.

The empty-cache guard from [prs-runtime-hardening](../../completed/prs-runtime-hardening/) (`INV-R002`) caught this at smoke-time + refused to cache the empty result. The next blocker is the actual root cause: the wrapper needs to look up the real reference base per-site and assign REF/ALT correctly.

## Acceptance Criteria

1. **Orientation helper exists and is correct**: a new `_orient_pgs_sites_against_fasta(rows, fasta_path)` function consults the GRCh38 fasta for each (chrom, pos) and emits `(chrom, pos, ref_actual, alt_actual)` tuples where `ref_actual` is the actual reference base and `alt_actual` is whichever allele (effect or other) is NOT the reference.
2. **Sites where neither allele matches the reference are skipped + counted**: tri-allelic, wrong-build, and strand-issue sites surface as a structural counter in `tier2.qc.json` (e.g., `orientation_skipped: 42`) — NOT as silent drops.
3. **Bulk reference lookup**: the helper uses `samtools faidx <fasta> -r <regions_file>` in a single subprocess call (not 1.7M individual calls). Wall-clock target: < 30 s for 1.7M sites.
4. **Tier 2 wrapper wired to orient before writing the alleles TSV**: `_force_genotype_tier2` calls the orientation step; the alleles TSV reflects the corrected orientation; bcftools accepts every emitted site.
5. **Tests**: unit coverage for the orientation helper's three cases (keep-orientation, swap-orientation, skip-incompatible) + the batch faidx parser + integration coverage of the wired Tier 2 path.
6. **Smoke v18 produces a real `pgs_scores` row**: Tier 2 produces ~1.7M records (modulo orientation-skipped + no-coverage); pgsc_calc's match rate is > 75% (the default `min_overlap`); the cli envelope is a success envelope with non-null `percentile_in_user_ancestry`.

## Applicable Invariants

| ID | How it constrains this plan |
|----|------------------------------|
| `INV-D001` | The reference fasta is read read-only (samtools faidx queries don't mutate). |
| `INV-D003` | Orientation step runs in the existing `shard_scratch` dir; no new persisted artifacts. |
| `INV-R001` | The orientation result is captured in `tier2.qc.json` so the cache key + provenance reflect the correction. |
| `INV-R002` *(v1.14)* | The wrapper's empty-cache guard from prs-runtime-hardening stays in place; if the orientation step ALSO produces 0 oriented rows (e.g., fasta-CRAM build mismatch), the guard fires + diagnoses. |
| `INV-T001` | `_get_reference_bases` consumes samtools' `faidx -r` output format; if samtools changes that format, the orientation parser would break — covered by unit tests using a recorded fixture. |

## Out of Scope

- **Reverse-strand handling**: PGS Catalog scorefiles claim to be harmonised to forward strand for coordinates, so we won't try to complement `effect_allele` against possible reverse-strand sources. Sites where neither raw allele matches the reference are skipped (counted, not silently dropped). If the skipped count is high for a particular scorefile, that's a separate `report-low-orientation-coverage` follow-up — out of scope here.
- **Indels**: the wrapper already filters to SNP-only in `_extract_pgs_sites_from_scorefile`. This plan preserves that scope.
- **Tier 1 orientation**: the PCA panel sites come from `_materialize_pca_sites` which uses panel-derived REF/ALT — those are already correctly oriented (panel files use forward-strand reference bases by construction). No fix needed for Tier 1.
- **Caching the oriented rows**: each Tier 2 invocation re-orients (fast); the result is implicit in the cached `tier2.vcf.gz`. Cache key remains `scorefile_sha256` + `panel_version` + `sample_id`.

## Privacy & Safety Considerations

No new egress. The samtools faidx call is host-local against the user's existing fasta. No new sensitive data flows.

The orientation fix improves PRS correctness — currently the wrapper silently produces a 0-record Tier 2, which (without `INV-R002`) would have silently produced a wrong PRS percentile from incomplete data. The fix surfaces accuracy (not just liveness) of the pipeline.

## Open Questions

1. **Should orientation-skipped sites be logged at INFO level (not just counted in QC json)?** Recommendation: count silently in QC json. The user reviews the QC json post-run; logging 100k+ skipped rows would spam stderr. If the count exceeds a threshold (e.g., > 5% of input sites), log a single summary warning.
2. **What if the user's CRAM is on a different reference build than the fasta passed?** Out of scope — that's a setup error covered by `genomeclaw host doctor`'s future reference-build-check (F-list).
3. **Multi-allelic input rows from the scorefile**: extract-time SNP filter already drops these. Confirm by spot-checking the extractor's `len(effect) != 1 or len(other) != 1` filter still applies after the orientation step.

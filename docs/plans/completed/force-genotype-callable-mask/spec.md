# Spec: Force-Genotype Callable-Region Mask

**Status**: Drafted — not yet approved  
**Created**: 2026-05-25  
**Parent meta-plan**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md)  
**Stage**: 3 of the bioreview follow-up sequence (must land before `prs-calibration-phase3b`)  
**Estimated duration**: 7 days

---

## Goal

Intersect Tier-1/Tier-2 force-genotyping with a GIAB high-confidence regions BED to produce a
per-site `genotype_source` annotation; exclude sites classified as `uncallable` from both the
numerator and denominator of the PGS match-rate calculation.

---

## Background

`coverage_fill.py`'s force-genotyping primitive (`_BCFTOOLS_PIPE_TEMPLATE`, line 378–396) runs
`bcftools mpileup --min-BQ 20 --min-MQ 20 | bcftools call --constrain alleles` against the
user's CRAM at every PGS scoring site that the Nebula variant-only VCF does not contain. The
intent is to recover REF/REF dosages at high-quality sites where the variant caller simply had
no ALT to report.

The gap identified in the 2026-05-25 bioinformatics review:

1. The `mpileup` filters (MQ ≥ 20, BQ ≥ 20) exclude low-quality *reads*, but do not enforce a
   minimum *site coverage depth*, and do not intersect with any externally validated callable
   regions mask. A site inside a GIAB-flagged low-confidence region (e.g., near a tandem
   repeat, segmental duplication, or centromeric region) may receive a `bcftools call` REF/REF
   assignment from sparse, borderline-quality pileup — a confident-looking dosage that is
   bioinformatically unsupported.

2. Every row produced by the current force-genotype pipe is treated identically downstream. The
   VCF output and the `tier1.qc.json` / `tier2.qc.json` provenance blobs carry no per-site
   distinction between:
   - a site that was present in the original Nebula VCF (high-confidence by source),
   - a site force-genotyped from the CRAM with ≥ 10 supporting reads in a GIAB high-confidence
     region (supportable inferred REF/REF),
   - a site force-genotyped from the CRAM with ≥ 10 reads but outside GIAB high-confidence
     (lower-confidence inferred REF/REF), or
   - a site where the pileup returned fewer than 10 reads (or zero), making any call
     unreliable.

3. In `_pgsc_calc_match.py`, `parse_match_stats` counts `matched` and `unmatched` sites from
   the pgsc_calc log CSV. An `uncallable` site that the current pipe injects as a spurious
   REF/REF dosage may appear in the `matched` bucket, inflating both raw score and match-rate
   denominator with an unconfident dosage.

The fix involves three cooperating pieces: registering GIAB high-confidence regions as a
fetchable reference dataset, emitting a per-site provenance sidecar during force-genotyping,
and consuming that sidecar to exclude `uncallable` sites from the PGS overlap calculation.

---

## Acceptance Criteria

1. `genomeclaw refs fetch --source giab_high_confidence` downloads and MD5-verifies the GIAB
   NA12878/HG001 v4.2.1 high-confidence regions BED from NCBI FTP into
   `reference/giab_high_confidence/<release>/`.

2. After force-genotyping runs (Tier 1 or Tier 2), a sidecar file
   `<derived>/prs_coverage/<sample>/<panel>/forced_genotype_provenance.tsv.zst` exists
   alongside the cached VCF. It has exactly four tab-delimited columns: `chrom`, `pos`, `ref`,
   `alt`, `genotype_source`.

3. The `genotype_source` column takes exactly four values:
   - `nebula_called` — site was present in the source Nebula VCF (ALT or explicit REF call);
     no force-genotyping was performed.
   - `force_genotyped_high_conf` — site was force-genotyped AND the position intersects the
     GIAB high-confidence BED.
   - `force_genotyped_low_conf` — site was force-genotyped, does NOT intersect the GIAB BED,
     but the pileup returned ≥ 10 reads at MQ ≥ 20, BQ ≥ 20.
   - `uncallable` — site was force-genotyped, the pileup returned fewer than 10 reads (or no
     reads at all), OR the pileup returned reads exclusively below the MQ/BQ thresholds.

4. The `forced_genotype_provenance.tsv.zst` sidecar is produced atomically (via
   `atomic_promote`) alongside the cached VCF. If the VCF cache-hits, the sidecar is also
   present (invariant: one is never present without the other after a completed run).

5. The `parse_match_stats` path (or its caller) loads the sidecar and subtracts `uncallable`
   sites from both `matched` and `unmatched` counts before computing `match_rate`. The count
   subtracted is persisted to a new column `uncallable_sites_excluded` on the `pgs_scores`
   table row.

6. The agent can read `uncallable_sites_excluded` from the `GET /v1/pgs/computed/{pgs_id}`
   response and surface a human-readable note when the count is non-zero (e.g., "12 sites in
   this PGS were uncallable in your genome and were excluded from scoring").

7. A synthetic test constructs a mock PGS with some sites marked `uncallable` in the sidecar
   TSV, calls the match-rate function, and asserts those sites appear in neither the `matched`
   nor the `unmatched` count (INV-C002 gate test).

8. Real-data smoke: rerunning PGS000018 CAD on the project owner's genome with the mask
   produces (a) a `forced_genotype_provenance.tsv.zst` sidecar, (b) a non-null
   `uncallable_sites_excluded` value on the `pgs_scores` row, (c) a `match_rate` within ±5%
   of the pre-mask baseline (the exclusions should be a small fraction of total sites for a
   high-quality 30x CRAM in well-characterized PGS regions).

---

## Applicable Invariants

### INV-D001 — Raw Genomic Files Are Source-of-Truth Artifacts

The CRAM and Nebula VCF are opened read-only. The GIAB BED is fetched under `data/reference/`,
never under `data/raw/`. Force-genotyping outputs land under `data/derived/`. No source file is
mutated.

### INV-R001 — Rebuildability + Provenance

The `forced_genotype_provenance.tsv.zst` sidecar is a provenance artifact: it must not be
emitted without recording the tool version, GIAB BED release, coverage threshold, and
timestamp that produced it. The `tier1.qc.json` / `tier2.qc.json` blobs will be extended with
a `giab_bed_release` field and a `min_callable_depth` field so the sidecar is fully
reproducible from source inputs + tool pins alone.

### INV-E001 — Evidence & Traceability

The per-site `genotype_source` annotation is part of the evidence chain for any PGS
interpretation. A PGS row that references sites missing from this chain would violate the
traceability requirement. The sidecar must be co-located with the forced VCF and referenced in
the `params_json` column of the `pgs_scores` row.

### INV-P001 — Privacy Default / No Undeclared Egress

The GIAB BED fetch is a one-time user-initiated `refs fetch` command, not a background
pipeline dependency. The fetch path uses the existing `fetch.py` HTTPS pattern (with
`VersionAlreadyExists` idempotency). No new runtime egress is introduced. The force-genotyping
and overlap-correction steps are purely local.

### INV-C001 v1.7 — Research/Clinical Boundary + PRS Decline Pattern

If the `uncallable_sites_excluded` count for a given PGS is large relative to the scorefile
size (e.g., > 20% of the original scorefile), this is one of the named criteria under the
PRS-decline pattern. The calibration classifier (to be wired in `prs-calibration-phase3b`)
will consume this count. This plan does not implement the decline logic — it only exposes the
count. The semantic gate is the responsibility of `prs-calibration-phase3b`.

### INV-C002 (Proposed New) — Uncallable Sites Must Not Inflate PGS Denominator

**Rule**: A site with `genotype_source = uncallable` must not appear in the `matched` count,
the `unmatched` count, or the denominator of any PGS match-rate or overlap calculation.

**Rationale**: Including an uncallable site in the denominator implies a dosage was validly
observed (or validly missed) at that position. For a site where the CRAM had insufficient
coverage, neither outcome is meaningful. Inflating the denominator with uncallable sites
produces a misleadingly high or low match-rate depending on whether the inserted spurious
REF/REF dosage happened to match the scoring file allele.

**Verification**: A dedicated test (`test_invC002_uncallable_excluded_from_pgs_denominator`)
constructs a synthetic sidecar with a known count of uncallable sites and asserts post-
filtering match stats contain neither those sites as matched nor as unmatched.

This invariant is proposed here and will be promoted to `docs/reference/INVARIANTS.md` after
the Phase 3 tests are merged and green.

---

## Out of Scope

- Clinical-grade calling of novel variants in GIAB low-confidence regions. This plan only tags
  sites as `uncallable` to prevent spurious REF/REF dosages from entering PGS calculations; it
  does not attempt to improve coverage at those sites.
- Local zero-dosage imputation at GIAB low-confidence sites. That is a separate research
  direction and is not part of this plan.
- Changing the `bcftools mpileup` command structure or replacing it with GATK
  `HaplotypeCaller -ERC GVCF`. The existing pipe is retained; this plan adds a post-pipe
  classification step.
- Applying the `uncallable` mask to the main `variants.duckdb` table. This plan's scope is the
  PRS coverage path (`prs_coverage/`) only. A future plan may extend the mask to the broader
  variant calling pipeline.
- Integrating GIAB Tier-2 confident regions or alternative truth sets (HG002/HG003). Only
  NA12878/HG001 v4.2.1 is in scope here.

---

## Privacy and Safety Considerations

The GIAB NA12878/HG001 v4.2.1 BED is a public-domain reference dataset (NIST/NCBI). Fetching
it introduces no privacy concern. The sidecar TSV contains genomic positions and inferred
genotype-source labels for the user's sample. It is a derived artifact subject to the same
data-locality rules as the forced VCF — it stays under `data/derived/` and is not transmitted
to any remote service. No new egress surface is introduced.

The `uncallable_sites_excluded` count that surfaces to the agent (via the HTTP tool response)
is an aggregate integer, not a genomic position list. It does not identify which specific sites
are uncallable, so it meets the minimum-sufficient principle of INV-P002.

---

## Open Questions

1. **GIAB BED release pin**: the plan pins NA12878/HG001 v4.2.1. Should a newer release (if
   one is published before the plan lands) be used instead? Recommended: pin to v4.2.1 for
   reproducibility; the plan notes the current release date (2021) and the NCBI FTP path.

2. **Minimum depth threshold**: the plan proposes ≥ 10 reads as the `force_genotyped_low_conf`
   / `uncallable` boundary. This is consistent with GATK's minimum callable depth convention.
   Should it be configurable? Recommended: hardcode 10 for the initial implementation;
   persist the value in `tier1.qc.json` via `min_callable_depth` so it is auditable; make it
   configurable in a follow-up if needed.

3. **Sidecar format**: the plan specifies `.tsv.zst` (Zstandard-compressed TSV). An
   alternative is `.tsv.gz` for broader toolchain compatibility. The rest of the pipeline uses
   `.vcf.gz` (bgzip). Recommendation: `.tsv.zst` aligns with the provenance store pattern in
   `_pgsc_calc_match.py` (which uses gzip-compressed CSV). Either is acceptable; decision
   should be made before Phase 2 starts.

4. **Cache invalidation**: does adding the sidecar invalidate existing Tier 1 / Tier 2 caches?
   Recommended: yes — bump `SCHEMA_VERSION` in `coverage_fill.py` from `"2"` to `"3"` so
   existing caches (which lack the sidecar) are rebuilt. The cache-hit check in
   `prepare_coverage_tier1` already compares `schema_version`; the new value triggers a
   rebuild. This is a one-time cost for existing users.

5. **Sidecar atomicity on cache-hit**: if the VCF is already cached (from a schema-v2 run)
   and the user upgrades to schema-v3, the VCF exists but the sidecar does not. The cache-hit
   logic must treat "VCF present but sidecar absent" as a cache miss, not a hit. Confirm this
   is the behaviour implemented in Phase 2.

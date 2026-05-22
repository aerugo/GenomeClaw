# Feature: PRS Input Coverage Fill — Two-Tier Forced-Genotyping Cache

**Status**: Draft
**Created**: 2026-05-18
**Owner**: aerugo + engineering assistant
**Related Plans**:
- [docs/plans/active/prs-bootstrap-meta.md](../prs-bootstrap-meta.md) (Stage 1 + 2; this plan is the natural Stage 5 follow-up)
- [docs/plans/active/prs-reference-bootstrap/](../prs-reference-bootstrap/) (delivered the HGDP+1kGP panel layout this plan reuses)
- [docs/plans/active/prs-runtime-bootstrap/](../prs-runtime-bootstrap/) (delivered the `genomeclaw/toolkit:prs-phase1` image this plan extends)
- [docs/reports/prs-real-data-smoke-research-brief.md](../../../reports/prs-real-data-smoke-research-brief.md) (the brief that surfaced the failure)
- [docs/reports/prs-real-data-smoke-recommendation.md](../../../reports/prs-real-data-smoke-recommendation.md) (the recommendation this plan implements; **TBD** — to be written from the agent recommendation document, see `work-notes.md`)

---

## Goal

Make `pgsc_calc --run_ancestry` produce ancestry-calibrated PRS percentiles against the user's Nebula-style variant-only WGS by inserting an on-device forced-genotyping bridge between the user's CRAM and pgsc_calc.

## Background

The May 2026 real-data smoke proved that pgsc_calc v2.2.0 cannot ancestry-calibrate a PRS from a variant-only VCF. The user's Nebula deliverable records only sites where the sample differs from GRCh38 (~4.7M variants); pgsc_calc's PCA-projection sub-workflow requires `0/0` (REF/REF) calls at the LD-thinned HGDP+1kGP PCA-eligible site set, and the variant-only VCF has near-zero overlap with that set. The Nextflow `INTERSECT_THINNED` channel joins to `n:0` and the pipeline aborts.

Symptom (recorded 2026-05-17, full log in [prs-bootstrap-meta.md Stage 3](../prs-bootstrap-meta.md)):

```
MATCH_VARIANTS:     28.37% of PGS000018 scoring weights match (default threshold: 75%)
INTERSECT_VARIANTS: 4,218,855 / 4,509,070 = 93.56% target↔reference match
FILTER_VARIANTS:    1,139,835 PCA-eligible reference variants after LD-thin
INTERSECT_THINNED:  n:0  ← join mismatch, pipeline aborts
```

Forcing `--min_overlap 0.0` bypasses the first gate but propagates the same root cause downstream: effect alleles at unobserved REF/REF sites are treated as missing rather than as genuinely-REF dosages, so the raw `SUM` is systematically biased and the post-hoc Z-normalization is meaningless. This violates **INV-C001 v1.7** which requires PRS findings to be either ancestry-calibrated or declined.

The accepted fix (per the agent recommendation document, 2026-05-18) is a two-tier targeted forced-genotyping cache built from the user's CRAM with `bcftools mpileup -T sites | bcftools call -C alleles -T alleles | bcftools norm`. The chr22 prove-out (2026-05-18) measured 99s wall-clock and 127 MiB peak RAM for chr22 (6,812 PCA-eligible sites, 84.5% REF/REF, mean DP 27.98×), confirming the approach is privacy-preserving, RAM-cheap, and tractable on the 2-CPU Colima ceiling.

## Acceptance Criteria

Each criterion is testable. One AC maps to one or more tests.

- [ ] **AC1**: A Tier 1 PCA-site cache builder, invoked from `genomeclaw refs materialize --target prs_pca_sites`, derives the LD-pruned HGDP+1kGP PCA-eligible site list from the panel `pvar.zst` using plink2 with `--maf 0.01 --hwe 1e-6 --geno 0.05 --indep-pairwise 1000 50 0.05` and writes deterministic `pca_alleles.tsv.gz` + `pca_sites.tsv.gz` (with `.tbi`) under `reference/prs_pca_sites/<panel_version>/`. Rebuilding the same panel produces byte-identical output.
- [ ] **AC2**: A Tier 1 per-sample force-genotyper, invoked from `genomeclaw prs prepare-coverage --sample <id>`, runs the streaming `bcftools mpileup→call→norm` pipe against the user's CRAM and writes `derived/prs_coverage/<sample_id>/<panel_version>/tier1.vcf.gz` (+ `.tbi`) with one record per PCA-eligible site, mean DP recorded as a per-sample QC stat. Default config: zero outbound network calls (`INV-P001`).
- [ ] **AC3**: A Tier 2 per-PGS force-genotyper, invoked transparently from `genomeclaw prs compute` on cache miss, runs the same pipe restricted to the requested PGS scoring-file site list and writes `derived/prs_coverage/<sample_id>/<panel_version>/pgs/<PGS_ID>-<scorefile_sha256_short>/tier2.vcf.gz`. Cache key = (sample id, PGS id, scoring-file SHA256, panel version, tool versions).
- [ ] **AC4**: `genomeclaw prs compute --pgs-id <PGS_ID>` concats Tier 1 + Tier 2 into a single sorted VCF, hands it to `pgsc_calc -r v2.2.0 -profile docker --run_ancestry`, and returns a successful run with non-empty `INTERSECT_THINNED`, a populated `Z_norm2` continuous-PC percentile, and a `pgs_scores` row with full provenance.
- [ ] **AC5**: A pre-flight QC gate runs against the merged Tier 1 + Tier 2 VCF before pgsc_calc launch. The gate enforces the per-PGS-variant-count threshold table (see `development-plan.md`) and either declines with one of the five named reasons (`INV-C001` v1.7) or proceeds with a `calibration_warning` annotation.
- [ ] **AC6**: Re-running the same PGS against the same sample after Tier 1 + Tier 2 caches are warm completes in `pgsc_calc-wall-clock + cache-lookup-time` (no re-genotyping of the CRAM).
- [ ] **AC7**: The `pgs_scores` row records: pgs_id, scoring-file SHA256, panel version, bcftools/pgsc_calc/plink2/fraposa versions, match rate, PCA-eligible overlap count, Z_norm2 percentile, decline reason (or null), calibration_status enum, and (when applicable) the agent's choice rationale + two-alternatives note per `INV-A003`.
- [ ] **AC8**: A privacy-default test exercises the full prepare-coverage + compute flow and asserts zero outbound calls leave the host (no PGS scoring file refetch, no panel download, no telemetry — the panel and scoring files must already be on disk via `refs fetch`).

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the user's CRAM at `data/raw/<sample>/...` is opened read-only by bcftools mpileup; the pipe never writes back to the raw tree. The HGDP+1kGP panel under `reference/pgs_catalog_ancestry/v1/` is similarly read-only; the PCA-site derivative lands under `reference/prs_pca_sites/`.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — bcftools, samtools, plink2 stay in the toolkit image; the OpenShell sandbox sees only the `pgs_scores` rows the host service exposes.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — the per-PGS Nextflow work directory lives under `_scratch/pgsc_calc_work/`; final Tier 1/Tier 2 caches land under `derived/prs_coverage/` via `atomic_promote`.
- **INV-P001** Privacy Is the Default Operating Mode — every byte of the user's CRAM stays on the device; no remote imputation, no cloud genotyping, no `web_fetch` to PGS Catalog at runtime. Panel + scoring-file fetches are deliberate, named, pre-staged steps gated by `refs fetch`.
- **INV-R001** Derived Stores Must Stay Rebuildable — every cache file records source CRAM SHA256, panel version, scoring-file SHA256, tool versions (`bcftools --version`, `plink2 --version`, `pgsc_calc` revision), parameter JSON. Rebuild = wipe `derived/prs_coverage/<sample_id>/` + re-run; same input + same tool versions = byte-identical output.
- **INV-C001 v1.7** Separate Clinical from Research Assistance — every PRS finding is either ancestry-calibrated against HGDP+1kGP OR declined with one of five named reasons. The decline taxonomy is wired into `genomeclaw prs compute`'s typed exception layer, not patched in at the report-rendering surface.
- **INV-A003** Agent-Curated Compute Provenance — when a PGS computation is agent-triggered, the choice rationale + two alternatives considered are stored on the `pgs_scores` row AND as a memory note. Decline notes carry the two named reasons per the existing INV-C001 pattern.

## Proposed New Invariants

None new. This plan exercises the existing PRS-decline pattern under `INV-C001` v1.7 and the agent-provenance pattern under `INV-A003`. If implementation surfaces a structural rule (e.g., "any user-genome-derived intermediate must declare its source CRAM SHA256"), it will be proposed in `development-plan.md` and promoted only after tests exist.

## Technical Requirements

### Source Data Inputs

- User CRAM at `data/raw/<sample_id>/*.cram` + `.crai`
- HGDP+1kGP panel at `reference/pgs_catalog_ancestry/v1/GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}` (already fetched per [prs-reference-bootstrap](../prs-reference-bootstrap/))
- GRCh38 reference FASTA at `reference/grch38/ncbi-2014/grch38.fa.gz` (+ `.fai` + `.gzi`)
- PGS Catalog scoring files at `reference/pgs_scorefiles/<PGS_ID>_hmPOS_GRCh38.txt.gz` (fetched on-demand by `refs fetch --source pgs_scorefile --pgs-id <id>`)

### Derived Outputs

- `reference/prs_pca_sites/<panel_version>/pca_alleles.tsv.gz{,.tbi}` — Tier 1 input (one-time per panel release; not user-specific)
- `reference/prs_pca_sites/<panel_version>/pca_sites.tsv.gz{,.tbi}` — Tier 1 input
- `derived/prs_coverage/<sample_id>/<panel_version>/tier1.vcf.gz{,.tbi}` — Tier 1 cache (one-time per sample)
- `derived/prs_coverage/<sample_id>/<panel_version>/tier1.qc.json` — per-sample QC stats (mean DP, missing rate, indel rate)
- `derived/prs_coverage/<sample_id>/<panel_version>/pgs/<PGS_ID>-<sha8>/tier2.vcf.gz{,.tbi}` — Tier 2 cache
- `derived/prs_coverage/<sample_id>/<panel_version>/pgs/<PGS_ID>-<sha8>/result.json` — pgsc_calc output + provenance
- `derived/duckdb/pgs_scores` table — agent-facing summary (one row per (sample, pgs_id, run))

### Schema / Migration Impact

- New `pgs_scores` table (or extension of existing — to confirm in dev plan). Columns: `sample_id`, `pgs_id`, `pgs_name`, `scoring_file_sha256`, `panel_version`, `bcftools_version`, `plink2_version`, `pgsc_calc_revision`, `fraposa_version`, `match_rate`, `pca_overlap_count`, `sum`, `z_norm1`, `z_norm2`, `percentile_nearest_pop`, `percentile_continuous`, `bootstrap_ci_lo`, `bootstrap_ci_hi`, `calibration_status` (enum: `clean | warning | decline`), `decline_reason` (enum or null, see below), `agent_rationale_json` (nullable), `created_at`, `schema_version`.
- `decline_reason` enum values (per `INV-C001` v1.7): `POPULATION_TRANSFERABILITY_INSUFFICIENT | PGS_CATALOG_TIER_INSUFFICIENT | PHENOTYPE_HETEROGENEOUS | VARIANT_OVERLAP_INSUFFICIENT | ANCESTRY_CALIBRATION_UNCERTAIN`.

### Pipeline / Workflow Impact

- New module `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` — orchestrates Tier 1 build, Tier 2 build, cache lookup, merge.
- Extension to `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` — `_build_pgsc_calc_argv` switches from `-profile conda` to `-profile docker` (proven via smoke), accepts `--input` as the merged Tier 1+Tier 2 VCF, drops the pre-extraction step (pgsc_calc wants the panel `.tar.zst` directly).
- New `refs materialize` target `prs_pca_sites` for the one-time plink2 LD-prune step.
- New CLI: `genomeclaw prs prepare-coverage --sample <id>` (Tier 1 only) and `genomeclaw prs compute --pgs-id <id> --sample <id>` (Tier 2 + pgsc_calc; on cache miss triggers Tier 1 first if absent).

### Agent / UX Impact

- The agent's `genomeclaw_pgs_compute` tool surface is preserved — the Tier 1+2 logic is invisible to the agent. The status tool gains two informational fields: `tier1_cache_status: ready|missing|building` and `tier2_cache_status: hit|miss|building`.
- The decline-reason enum is surfaced to the agent verbatim so its system prompt can render the two-named-reasons explanation per `INV-A003`.

### External Dependencies

- bcftools 1.21+ (already in `genomeclaw/toolkit:prs-phase1`)
- plink2 2.00a5.10 — currently NOT in the toolkit image; needs to be added (or pulled via `ghcr.io/pgscatalog/plink2:2.00a5.10` and invoked via Docker-out-of-Docker, like pgsc_calc itself)
- pgsc_calc v2.2.0 — already pre-warmed in the image
- fraposa_pgsc — pulled by pgsc_calc

## Privacy & Safety Considerations

- **Boundary scan**: every step is on-device. The pipe `bcftools mpileup → call → norm` reads the CRAM, the FASTA, the targets file; writes a local VCF. plink2 reads the panel, writes the prune-in list. pgsc_calc reads the merged VCF + panel + scoring file, writes a results dir. No network egress is opened by this plan; the existing `refs fetch` is the only legitimate egress destination and is unaffected.
- **Default-off remote calls**: none added.
- **Redaction surface**: when the agent surfaces a `pgs_scores` row, the host service applies the existing `INV-P002` minimum-sufficient-payload contract — agent sees PGS id, percentile, calibration status, decline reason; never the raw CRAM path, never per-variant genotypes, never per-PCA-site DP.
- **Clinical escalation**: `INV-C001` v1.7 classifies PRS findings as `clinical-non-actionable`; the escalation marker stays false. The ACMG 2023 ancestry-portability caveat ships in the report template alongside every PRS percentile.

## Out of Scope

- **Local imputation** (Beagle/Minimac4/Eagle) — RAM ceiling violation on 12 GB Colima. Revisit if the host gains ≥32 GB.
- **Cloud imputation** (TOPMed, Michigan) — `INV-P001` violation, hard rejected.
- **GATK HaplotypeCaller-based GVCF reconstruction** — overengineered vs. `bcftools -C alleles`, adds JVM dependency, rejected.
- **Indel-heavy scoring files** at Tier 2 first release — restrict initial Tier 2 site lists to SNPs until indel concordance is empirically verified against GATK HC (see Open Question Q2).
- **Multi-sample / family PRS** — single-sample only for MVP.
- **Non-EUR-specific PGS defaults** (caPRS, BridgePRS) — track but don't ship; defer until caPRS receives a PGS Catalog ID.
- **Switching to pgsc_calc v3** — track its WGS-native trajectory; deprecate this shim only when v3 ships native CRAM/VCF ingestion.

## Dependencies

- [prs-reference-bootstrap](../prs-reference-bootstrap/) — completed; provides the panel
- [prs-runtime-bootstrap](../prs-runtime-bootstrap/) — completed; provides the toolkit image
- `genomeclaw refs fetch --source pgs_scorefile` — must be implemented or extended in this plan; the current `refs fetch` does not yet handle per-PGS-id scoring-file mirroring

## Open Questions

- [ ] **Q1**: What is the full-autosome Tier 1 wall-clock on the project owner's M-series host? chr22 prove-out (2026-05-18) measured **99s** for 6,812 PCA-eligible sites @ 127 MiB peak RAM, single-threaded. Linear extrapolation to the projected ~400–500k autosome PCA-eligible sites (chr22 is ~1.5% of autosome variant mass after filters): **~98–122 min single-threaded; ~50–60 min with the current 2-CPU Colima parallel-by-chrom; ~12–15 min with 8 CPUs**. Resolution: measure on the full autosomes in Phase 1 GREEN step. Do not promise the agent an SLA tighter than the measured value.
- [ ] **Q2**: Does `bcftools call -m -A -C alleles` produce reliable REF/REF calls on indels? SNPs are well-trodden; indels are not. Resolution: spot-check 10K loci against GATK HaplotypeCaller in Phase 2 if Tier 2 indel-heavy PGS scores land. For MVP, restrict Tier 2 site lists to SNPs.
- [ ] **Q3**: Does the chr22-extrapolated 84.5% REF/REF / 9.5% het / 5.1% hom-alt / 0.9% missing distribution hold on the full autosomes, or do larger chromosomes show different missing-rates (e.g., due to segmental duplications, HLA, KIR)? Resolution: per-chromosome QC summary as part of Tier 1 QC JSON.
- [ ] **Q4**: How aggressive should the LD-prune be? `--indep-pairwise 1000 50 0.05` (chr22 prove-out) yields 6,812 sites for chr22 (~0.54% of panel variants); the agent recommendation document expected ~1.14M total (consistent with `r²<0.1` or `r²<0.2`). The denser the prune-in set, the better the PCA projection for users near reference-cloud edges, but the longer Tier 1 takes. Resolution: stick with `r²<0.05` for the MVP — it matches what pgsc_calc's `FILTER_VARIANTS` does internally; revisit if FRAPOSA's Mahalanobis distance is structurally too noisy.
- [ ] **Q5**: Should plink2 ship inside the toolkit image, or be invoked via Docker-out-of-Docker against `ghcr.io/pgscatalog/plink2:2.00a5.10`? The chr22 prove-out used DooD because plink2 is not yet in the image and the linux/arm64 conda-forge channel doesn't carry plink2 2.00a5.10. Resolution: DooD is acceptable for one-time Tier 1 build; consider baking plink2 into the toolkit image if Tier 2 ends up calling plink2 routinely (it doesn't — only bcftools).

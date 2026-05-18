# Research Brief — Polygenic Score Computation on a Single-Sample Nebula VCF

**Audience**: Post-doc, bioinformatics (preferably with PRS / pgsc_calc / plink2 experience)
**Author**: GenomeClaw project owner + engineering assistant
**Date**: 2026-05-18
**Status**: Need review + recommendations
**Project repo**: [GenomeClaw](https://github.com/aerugo/GenomeClaw)

---

## Executive Summary

We're building a privacy-first personal-genomics assistant ("GenomeClaw") that runs entirely on the user's hardware. One component is an **agent-triggered PRS computation pipeline** that picks a PGS Catalog ID per user question, runs `pgsc_calc` against the user's WGS data, and returns an ancestry-calibrated percentile.

Over the past day we built the toolchain (Docker image bundling Nextflow + JRE 17 + mamba + pre-warmed `pgsc_calc` v2.2.0) and got it to produce **a real raw PRS score** against the project owner's actual Nebula Genomics 30× WGS data (sample `MPNRGLQ2K`, PGS000018 — the canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS).

But we're stuck on the **ancestry-calibration step**. The empirical match rate between PGS000018's scoring weights and the Nebula sample's variant-only VCF is **28.37%**. When we engage `pgsc_calc --run_ancestry` (which performs PCA against the gnomAD-merged HGDP+1kGP reference panel), the LD-thinned PCA-eligible variant subset has ~zero overlap with our 28% — the pipeline's join produces `n:0` and the entire ancestry calibration aborts.

**Root cause hypothesis**: Nebula's variant-only VCF lists only sites where the sample differs from GRCh38, and excludes called-reference (REF/REF) sites. PGS scoring assumes a genotype call (including REF/REF) at every scoring weight position. So we get a high apparent variant count (4.7M) but a structurally-low overlap with PGS Catalog's expected-everywhere-called sites.

We're asking you to **review, suggest fixes, and propose the best canonical path** for ancestry-calibrated PRS on a single-sample Nebula 30× WGS dataset, given strict on-device-only privacy constraints.

---

## 1. Project Context

### 1.1 GenomeClaw at a glance

- **Single user, single host, on-device by default.** No cloud data egress for genomic content. The user (one of the engineers writing this) runs the system on macOS Sequoia / Apple Silicon (M-series, 16 GB RAM) with Colima providing the Docker daemon. Reference data lives on an external 2 TB drive at `/Volumes/Genome_Work/genomeclaw/`.
- **Data sources**: the user's Nebula Genomics 30× WGS deliverable contains a CRAM (~50 GB, aligned to GRCh38_no_alt) + a small variant VCF (`*.mm2.sortdup.bqsr.hc.vcf.gz`, ~1 GB, from `bcftools call`/HaplotypeCaller equivalent — only variant sites, no GVCF blocks).
- **Architecture**: a host-side `genomeclaw/toolkit` Docker image bundles bioinformatics binaries (bcftools, samtools, htslib, vcfanno, VEP+plugins) plus a per-question agent-triggered PRS path that invokes `pgsc_calc`. Reference data (ClinVar, gnomAD, VEP cache, AlphaMissense, LOFTEE, PGS Catalog HGDP+1kGP ancestry panel) is bind-mounted from the external drive.
- **Why on-device?** Personal genomic data is durable, identifying, and difficult to revoke once exposed. Cloud imputation services (TOPMed, Sanger, etc.) — even though they're well-validated — are off-limits by project policy: no genomic data leaves the device.

### 1.2 The PRS workflow we're building

The user converses with an LLM agent (running on a frontier model — Claude Opus, GPT-5.x, etc.). When the conversation triggers a PRS-relevant question ("my dad had a heart attack at 58, is there anything in my genome about CAD risk?"), the agent:

1. Reasons about which PGS Catalog ID to use (e.g. PGS000018 for CAD, PGS000007 for breast cancer, …)
2. Sends a "rationale + question + PGS ID" payload to a host service running on the user's machine
3. The service kicks off `pgsc_calc` against the user's genome
4. ~30 min later the agent re-checks status, receives an **ancestry-calibrated percentile** (e.g. "87th percentile in your continuous-ancestry estimate"), surfaces a clinically-framed paragraph to the user
5. Agent declines if the score has low confidence (high `calibration_warning`, low variant overlap, sparse population evidence — our `INV-C001 v1.7` PRS-decline pattern)

The **ancestry calibration is the whole point** — a raw PRS sum like "9.476" is meaningless without knowing the user's continuous-ancestry context. PGS Catalog's recommended approach is `pgsc_calc --run_ancestry` against the HGDP+1kGP combined panel; this performs PCA + projects the user's ancestry vector + reports a percentile in the most-similar reference population.

---

## 2. What We've Built

### 2.1 The toolkit Docker image

Image: `genomeclaw/toolkit:prs-phase1` (linux/arm64, built locally on Apple Silicon).

Stages:
- `bio` — bcftools / mosdepth / samtools / htslib / vcfanno via bioconda
- `vep` — Ensembl VEP 114.1 in an isolated micromamba env
- `vep-plugins` — LOFTEE + Ensembl VEP_plugins
- `prs-runtime` (NEW) — OpenJDK 17 + mamba in `/opt/conda-prs/`; Nextflow 24.10.0 CLI installed via the official installer; `pgsc_calc v2.2.0` pipeline pre-warmed via `nextflow pull pgscatalog/pgsc_calc -r v2.2.0` into `/opt/nextflow/{framework,assets}/` and copied to `/opt/pgsc_calc/`
- `pybuild` — the GenomeClaw Python toolkit installed via uv
- `runtime` — final composed image, +Docker CLI added for Docker-out-of-Docker (DooD)

Final image: 5.54 GB. Runs as user `genomeclaw` (uid 1000) by default, but for the PRS path we override to `--user 0:0` so it can access the bind-mounted Docker socket.

### 2.2 The reference data layout

- `reference/grch38/...` — NCBI's no_alt analysis-set fasta + .fai
- `reference/pgs_catalog_ancestry/v1/` — extracted PGS Catalog ancestry bundle (`pgsc_HGDP+1kGP_v1.tar.zst`, 16 GB compressed → 28 GB extracted), containing the gnomAD-merged 1000G+HGDP callset:
  - `GRCh38_HGDP+1kGP_ALL.pgen` (12 GB, plink2 genotype matrix)
  - `GRCh38_HGDP+1kGP_ALL.pvar.zst` (1.8 GB, variant metadata)
  - `GRCh38_HGDP+1kGP_ALL.psam` (120 KB, sample metadata)
  - `meta.txt` (`v0.1` version stamp)
  - Plus `king.cutoff.out.id` (related-sample exclusion list) and the GRCh37-build counterparts
- Other reference data: VEP cache 114, AlphaMissense v1.0, LOFTEE GRCh38, gnomAD constraint v4.1, etc. — all relevant but not directly part of this PRS-compute flow.

### 2.3 The pgsc_calc invocation

We worked out (after 17 iterations) that the only profile that works on Apple Silicon arm64 is `-profile docker` via Docker-out-of-Docker. The conda/mamba profiles fail because `pgsc_calc v2.2.0`'s `environments/plink2/environment.yml` pins `plink2 ==2.0a5.10` which conda-forge ships only for `linux-64`, not `linux-aarch64`. The `pgscatalog/*` GHCR images ARE multi-arch.

The actual invocation:

```bash
docker run --rm --user 0:0 \
    -e NXF_HOME=/Volumes/Genome_Work/genomeclaw/_scratch/nextflow-home \
    -e HOME=/Volumes/Genome_Work/genomeclaw/_scratch/nextflow-home \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /Volumes/Genome_Work/genomeclaw/raw:/Volumes/Genome_Work/genomeclaw/raw:ro \
    -v /Volumes/Genome_Work/genomeclaw/reference:/Volumes/Genome_Work/genomeclaw/reference:ro \
    -v /Volumes/Genome_Work/genomeclaw/_scratch:/Volumes/Genome_Work/genomeclaw/_scratch \
    -w /Volumes/Genome_Work/genomeclaw/_scratch/nextflow-home \
    genomeclaw/toolkit:prs-phase1 \
    nextflow run pgscatalog/pgsc_calc -r v2.2.0 -profile docker \
        --input /Volumes/.../samplesheet.csv \
        --target_build GRCh38 \
        --pgs_id PGS000018 \
        --run_ancestry /Volumes/.../pgs_catalog_ancestry/v1/pgs_catalog_ancestry.tar.zst \
        --max_memory '10.GB'
```

Where the samplesheet is:

```csv
sampleset,path_prefix,chrom,format,vcf_genotype_field
MPNRGLQ2K,/Volumes/.../MPNRGLQ2K.autosomes,,vcf,GT
```

`MPNRGLQ2K.autosomes.vcf.gz` is the original Nebula VCF pre-processed by:

```bash
bcftools view -r chr1,chr2,...,chr22 input.vcf.gz -Oz -o autosomes.vcf.gz
bcftools view -h autosomes.vcf.gz | grep -vE '##contig=<ID=chr(X|Y|M)' > new_header.txt
bcftools reheader -h new_header.txt autosomes.vcf.gz > autosomes-clean.vcf.gz
bcftools index --tbi autosomes-clean.vcf.gz
```

This was forced on us because plink2 refuses to read a VCF whose **header** declares chrX/chrY/chrM contigs unless we provide sex info (the `--vcf: ... --update-sex may also be appropriate` error). Stripping non-autosome contigs from both the data AND the header gets us past this; CAD is autosomal anyway.

---

## 3. What We Validated Empirically

The pipeline gets all the way through these stages:

| Stage | Outcome |
|---|---|
| pgsc_calc pipeline pull from GitHub | ✅ `v2.2.0` (`abb5b5ebed`) |
| `nf-schema` + `nf-prov` Nextflow plugin downloads | ✅ |
| `EXTRACT_DATABASE` (untar the ancestry bundle inside the container) | ✅ |
| Scoring file download for `PGS000018_hmPOS_GRCh38` | ✅ |
| `FORMAT_SCOREFILES` (normalise variant IDs to `chrom:pos:ref:alt`) | ✅ |
| `PLINK2_VCF` (target genome → pgen) on autosomes-only VCF | ✅ 4,584,153 variants |
| `MAKE_COMPATIBLE:PLINK2_RELABELBIM/RELABELPVAR` | ✅ |
| `MATCH_VARIANTS` (target ↔ scoring file) | ✅ at **28.37%** with `--min_overlap 0.0` (the 75% default rejects) |
| `MATCH_COMBINE` | ✅ |
| `APPLY_SCORE:RELABEL_SCOREFILES + RELABEL_AFREQ + PLINK2_SCORE` | ✅ |
| `SCORE_AGGREGATE` | ✅ |
| `SCORE_REPORT` | ✅ — produced an HTML report and the aggregated_scores TSV |

The final `aggregated_scores.txt.gz`:

```
sampleset    FID         IID         PGS                          SUM       DENOM    AVG
MPNRGLQ2K    MPNRGLQ2K   MPNRGLQ2K   PGS000018_hmPOS_GRCh38       9.47603   990868   9.563362627514462e-06
```

**This is a real PRS score for a real person against PGS000018.** But it's a **raw sum without an ancestry-calibrated percentile**, which is what the agent flow actually needs.

When we re-enable `--run_ancestry`:

| Stage | Outcome |
|---|---|
| `EXTRACT_DATABASE` (same as above) | ✅ |
| `MAKE_COMPATIBLE` (same as above) | ✅ |
| `ANCESTRY_PROJECT:EXTRACT_DATABASE` | ✅ |
| `ANCESTRY_PROJECT:INTERSECT_VARIANTS` (target ↔ reference panel) | ✅ — `4218855/4509070 (93.56%)` of target variants match the reference; `2935421/4218855 (69.58%)` are PCA-eligible (i.e. survive frequency / call-rate / HWE / LD-prune filters) |
| `ANCESTRY_PROJECT:FILTER_VARIANTS` (LD-thin via plink2 `--indep-pairwise 1000 50 0.05 --exclude range high-LD-regions-hg38-GRCh38.txt`) | ✅ 1,139,835 variants in the thinned reference set |
| `MATCH_VARIANTS` against PGS scoring file | ✅ 28.37% |
| `INTERSECT_THINNED` (intersect thinned-PCA variants × matched-scoring variants) | ❌ — produces `n:0`, JOIN fails with `Join mismatch for the following entries: key=[chrom:ALL, n:0, effect_type:additive] values=[]` |

So at the ancestry-calibration step: of the 4.5M variants in our autosomes Nebula VCF, **93.56% match the HGDP+1kGP reference panel**, and 69.58% of those are PCA-eligible. But the intersection of this PCA-eligible set with our **28% PGS-scoring-weight match** is empty — meaning the user has near-zero of the PGS Catalog scoring weights at sites that pgsc_calc considers PCA-eligible.

---

## 4. The Core Hypothesis

Nebula's VCF is a **variant-only call set**, not a GVCF. It lists only positions where the sample is non-reference. For PGS scoring weights at sites where the user is REF/REF, **the site is absent from the VCF**, not encoded as `0/0`.

PGS Catalog's scoring weights are concentrated at common variants (high MAF in EUR populations because that's where most discovery GWAS were done). For a typical 30× WGS user, many of these sites should call as REF/REF; the variant-only VCF just doesn't record those calls. The 28% match rate is consistent with this: only the user's actually-variant sites that happen to overlap PGS Catalog weights get counted.

The downstream consequence: when pgsc_calc tries to build the PCA matrix, it needs the user's genotype at every LD-thinned reference site. The Nebula VCF's absence at REF/REF sites means those rows are missing → the join with matched-PGS-variants is empty → the percentile cannot be calculated.

The CAD score itself (the raw 9.476 SUM) is also under-estimated because the user is being implicitly scored as REF/REF at the 72% of PGS sites that are missing from the input VCF, which means their effect alleles aren't being counted.

---

## 5. What We Need From You

### Question 1 — Approach review

Is "use `pgsc_calc -profile docker --run_ancestry pgsc_HGDP+1kGP_v1.tar.zst`" the right canonical approach for on-device, single-sample, ancestry-calibrated PRS in 2026?

Specifically:

- Are there newer / better-supported tools we should consider? (`plink2 --score` directly with custom ancestry calibration? `BPC` / `BridgePRS`? Something out of FinnGen / UKBB pipelines?)
- Is the HGDP+1kGP merged panel the right reference for continuous-ancestry projection in 2026, or are there better panels we should be using (e.g. the new gnomAD v4 sample-level releases when they land, the All-Of-Us reference)?
- Are there issues with PGS000018 specifically (vs newer harmonized CAD PRS like PGS003725, PGS003900, …) that we should account for?
- We default to `PGS000018_hmPOS_GRCh38` (the harmonized-position remap to GRCh38). Is that the right choice for a GRCh38-aligned Nebula sample, or should we be using a re-derived/-trained model with native GRCh38 weights?

### Question 2 — Fix the ancestry-calibration blocker

Given the privacy constraint (no genomic data leaves the device) — what's the canonical bioinformatics-recipe to bridge a variant-only VCF + the user's CRAM into a calling set that `pgsc_calc --run_ancestry` will accept?

We see three plausible approaches; please rate / refine / replace them:

**Option A — Re-genotype at PGS-relevant + ancestry-thinned sites, from the CRAM:**
- Extract the union of (PGS Catalog scoring weight positions for the relevant PGS IDs) + (HGDP+1kGP LD-thinned PCA-eligible sites)
- Run `bcftools mpileup --regions-file <sites.bed> --fasta-ref GRCh38.fa MPNRGLQ2K.cram | bcftools call -m -Oz` against that site list, producing a VCF with calls at every relevant position
- Merge this with the original Nebula VCF, prefer the Nebula call where present
- Concerns: depth-of-coverage at low-MAF sites; false-positive REF calls in regions with high alignment ambiguity; CPU + I/O cost (CRAM is 50 GB) per question

**Option B — GVCF reconstruction:**
- Re-run a variant caller in GVCF mode against the user's CRAM (GATK HaplotypeCaller `-ERC GVCF` or `bcftools call --gvcf 0`)
- Use the GVCF as input to `pgsc_calc` (does pgsc_calc accept GVCFs?)
- Concerns: full-genome GVCF is ~10× the size of the variant VCF; do we need a per-question GVCF or can we precompute once?

**Option C — Sparse PRS-only re-genotyping cache:**
- Maintain a per-CRAM cache of called genotypes at the union of all PGS Catalog scoring sites that any user might ever ask about (~few hundred K positions across all PGS IDs)
- Build this cache once after Nebula data lands; reuse forever
- Each agent-triggered question filters the cache to the relevant PGS ID's sites + runs scoring directly
- Concerns: which calling tool gives the most-accurate genotype at PGS Catalog sites? Recurrent PGS Catalog updates would expand the site list

**Option D — Imputation:**
- The "industry standard" approach: pre-phase + impute the user's variant VCF against a reference panel (TOPMed Imputation Server, Sanger Imputation Server, …) producing a dense imputed VCF with ~50M sites at high info-score
- The reference-panel-based imputation IS doable on-device with `eagle` (phasing) + `minimac4` (imputation) given the reference panel locally — but the reference panel is ~hundreds of GB and the imputation runtime per chromosome is significant (~hours)
- Concerns: latency per question (way more than the 30 min target); reference-panel disk space; whether the project owner wants to maintain a local imputation reference panel

Which approach do you recommend, and what does the canonical command sequence look like? Bonus points for any pre-existing nf-core / snakemake module that already does this.

### Question 3 — Best-path recommendation

If you were designing this from scratch — single-user 30× WGS + privacy-first + per-question agent-driven PRS with ancestry-calibrated percentiles — what would the pipeline look like?

Some specific dimensions we care about:

- **Latency**: ideally each agent-triggered question completes in ≤30 min wall-clock. Currently `pgsc_calc` (when we skip ancestry calibration) takes ~3 min. With imputation it'd be way longer. Where's the right trade-off?
- **Storage**: the user's external drive is 2 TB. We've already committed ~400 GB (raw + reference). What's a reasonable budget for ancestry-calibration infrastructure?
- **Accuracy**: an "honest" percentile matters more than a "high-precision" one. We'd rather report `INV-C001` v1.7's `calibration_warning` + decline than mis-calibrate. What QC thresholds should we enforce per PGS ID?
- **Coverage**: should we restrict to a curated subset of PGS Catalog IDs that have been validated for low-coverage variant-only-VCF input? Or invest in the per-question full-coverage solution?
- **Provenance**: every score the agent reports needs to record the tool version, scoring weight file SHA256, reference panel version, the user's actually-used variant count / match rate / calibration_warning. We do this already for the chain above; please flag anything that should also be captured for clinical defensibility (this is a research / education assistant, not a clinical tool, but the project owner may show the report to their clinician).

---

## 6. Appendix

### 6.1 Files + paths the researcher can verify against

- Source code (private project repo): `/Users/hugi/GitRepos/GenomeClaw/`
- Key code paths:
  - `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` — wrapper that subprocess-invokes pgsc_calc
  - `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — `_LAYOUTS["pgs_catalog_ancestry"]` entry + `_extract_pgs_catalog_ancestry_bundle` post-hook
  - `packages/toolkit/Dockerfile` — image build with `prs-runtime` stage
- Real-data smoke logs: `/tmp/genomeclaw-prs-nextflow.log` (last run)
- Nebula data: `/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/` (CRAM + VCF; not committed; SHA256s recorded in pipeline manifests)
- pgsc_calc work-dir state (failed ancestry-calibration run): `/Volumes/Genome_Work/genomeclaw/_scratch/pgsc_calc_work/2026-05-17T15-12-03Z-prs-smoke01/`
- Iteration log: [docs/plans/active/prs-bootstrap-meta.md § Stage 3](../plans/active/prs-bootstrap-meta.md) Real-Data Smoke Results

### 6.2 Reproducibility minimum

The full chain runs from a fresh clone of the GenomeClaw repo via:

```bash
# 1) Setup (one-time, ~30 min, downloads ~16 GB ancestry bundle)
bin/genomeclaw host setup
bin/genomeclaw refs fetch --source pgs_catalog_ancestry --release v1

# 2) Build the toolkit image (~10 min)
docker build -t genomeclaw/toolkit:prs-phase1 packages/toolkit/

# 3) Pre-process the VCF to autosomes-only with clean header (~30 sec)
# (commands in section 2.3)

# 4) Run pgsc_calc (the actual research question)
# (full command in section 2.3)
```

### 6.3 Empirical numbers worth knowing

- **Target VCF**: 4,703,655 variants (full); 4,584,153 after chrX/Y/M autosome-filter
- **Reference panel**: HGDP+1kGP gnomAD v3.1.2-merged callset, 3,942 samples (1,860 F, 2,082 M), 12 GB pgen
- **Filtered reference (post-MAF/HWE/LD-thin)**: 1,139,835 variants
- **Target ↔ reference variant overlap (raw)**: 4,218,855 / 4,509,070 = **93.56%** (target variants matching reference)
- **PCA-eligible subset within overlap**: 2,935,421 / 4,218,855 = **69.58%**
- **PGS000018 scoring weights matched in target**: 28.37% (with `--min_overlap 0.0`); fails 75% default threshold
- **Compute time**: ~3 min for the chain without `--run_ancestry`; ~25-40 min with calibration (when it doesn't crash)
- **Memory**: pgsc_calc requests `8.GB` for `process_high` labeled tasks; `10.GB` Colima allocation works; `8.GB` is right at the cliff

### 6.4 Iteration list — what broke + how we fixed it

Each line is a real failure we hit before getting to the eventual raw-score result:

1. Colima yaml had `mounts: []` after a config drift — external drive was not shared into the VM at all. Fixed via `bin/genomeclaw host setup`.
2. CLI rejected `pgs_catalog_ancestry` — hardcoded `_VALID_FETCH_SOURCES` tuple in `refs.py:66` never updated past Phase 2. Fixed by deriving from `_LAYOUTS`.
3. Upstream URL was wrong (`pgsc_calc/` phantom subdir in the FTP path). Fixed by validating against `curl -I`.
4. Bundle layout assumption wrong — I'd assumed `1000g/` + `hgdp/` subdirs; the actual bundle is flat with combined `GRCh38_HGDP+1kGP_ALL.*` files. Fixed `_LAYOUTS` + `_check_ancestry_reference` + tests.
5. Bundle size 16 GB / 28 GB extracted (not 5-7 / 50-60 GB as estimated).
6. Pre-extraction was wrong — pgsc_calc expects `--run_ancestry` to point at the `.tar.zst` directly, NOT at a pre-extracted dir. Re-archived in-place.
7. `-profile standard` doesn't exist in pgsc_calc.
8. `-profile mamba` failed because `plink2 2.0a5.10` unavailable on `linux-aarch64`.
9. Image lacked `docker` CLI for DooD. Added `docker-ce-cli` to the runtime stage.
10. Container's default user (uid 1000) couldn't access the bind-mounted Docker socket. Switched to `--user 0:0`.
11. DooD path translation — sibling containers see host paths, not container paths. Fixed by mounting at identical paths inside-and-outside the toolkit container.
12. Colima default 8 GB RAM precheck failed (`req: 8 GB; avail: 7.7 GB`). Bumped to 12 GB.
13. chrX/chrY in Nebula VCF — plink2 demands sex info; filtered VCF to autosomes-only.
14. chrX/chrY/chrM contigs still in **header** after `bcftools view -r` — plink2 fails on header-level contig declaration even with no variants. Stripped via `bcftools reheader`.
15. NXF_HOME at `/root/.nextflow` (container-local) — asset symlinks broke inside DooD sibling containers. Moved to bind-mounted volume.
16. `--max_memory 6.GB` — plink2's FILTER_VARIANTS step ran OOM on 3,942-sample HGDP+1kGP panel. Bumped to 10 GB.
17. Two concurrent runs racing on the same work dir. Killed both, started one clean.

Then the MATCH-rate / ancestry-join issue surfaced — which is the actual research question.

---

## 7. Acknowledgements + Caveats

- The project owner is not a bioinformatician by training; the engineering assistant has read the pgsc_calc + plink2 docs but is not a domain expert. We may be making wrong choices that are obvious to you — please push back on assumptions.
- Privacy is THE non-negotiable constraint. Cloud imputation services are not acceptable. Local-only solutions only.
- We can spend per-question compute time (up to 30 min wall clock) and significant external-drive disk (up to 1-2 TB additional). We cannot spend more host RAM than 12 GB (16 GB total host, macOS needs ~4).
- The project's `INV-C001 v1.7` policy says: PRS findings without ancestry calibration MUST surface a `calibration_warning` to the user and the agent MUST decline or heavily caveat the result. So "raw score without ancestry" is not a viable user-facing output; we need the percentile or we decline.

We appreciate your time. Please return your recommendations as comments / annotations on this document, or as a separate response — whichever is more natural. We're particularly interested in **citations to canonical pipelines / papers** so we can avoid re-inventing wheels.

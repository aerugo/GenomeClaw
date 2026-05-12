# Phase 4: Host pipeline — annotation (VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno)

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD or blank>
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-3.md](phase-3.md) (complete; `normalize` + `materialize` shipped against the project owner's real Nebula VCF; row-equivalence determinism contract anchored)

---

## Objective

Lay down the full annotation surface that lifestyle / clinical / PGx tracks all depend on. After Phase 4: a `genomeclaw-prep annotate` invocation against an existing `derived/<run-id>/normalized.vcf.gz` writes a fully-annotated VCF and the materialized `variants` table carries every column the host service (Phase 5) and the finding/evidence schemas (Phase 6) need.

This is the largest phase by scope. To keep it reviewable it splits into four sub-phases that land in order, each with its own RED / GREEN / REFACTOR cycle. Sub-phase 4A already shipped — see "Background" below.

| Sub-phase | Deliverable | Tests (est.) | Real-data gate |
|-----------|-------------|--------------|----------------|
| 4A *(shipped)* | `bcftools annotate` ClinVar overlay; schema v0.2 with `clinvar_id` / `clinvar_classification` / `clinvar_review_status` columns | 7 | Already passed (4,870,517 variants / 42,885 ClinVar matches against real Nebula VCF) |
| 4B | GRCh38 reference fasta fetch + production `bcftools norm -f` left-alignment + CRAM ingest enablement | ~6 | Real-data smoke: ingest the project owner's CRAM end-to-end |
| 4C | `vcfanno` migration of ClinVar; new gnomAD v4 + dbSNP overlays; new annotation columns (gnomAD per-population AFs, dbSNP rsid) | ~12 | Real-data smoke: vcfanno run against real Nebula matches the bcftools-annotate ClinVar match count to within ε |
| 4D | VEP + LOFTEE + AlphaMissense + SpliceAI; MANE Select transcript pinning; HGVSc / HGVSp; consequence ontology | ~15 | Real-data smoke: full pipeline end-to-end on real Nebula; VEP completes within personal-host envelope |
| 4E | Schema v0.2 finalisation — every new INFO field pulled into a typed `variants` column; `materialize`'s annotated-input branch covers them | ~6 | Real-data smoke: every Phase-4 column populated on the real-data row count; provenance trail names every annotator's tool + version |

Total estimate: ~39 new tests; suite goes from 148 (Phase 3 + cram-scratch-strategy close) to ~187 at Phase 4 close.

### Background — what Phase 4A delivered

Phase 4A landed during the [cram-scratch-strategy plan](../../../completed/cram-scratch-strategy/) interlude as the storage-architecture validator (the plan needed *some* annotation step to drive scratch + atomic-promote + schema-v0.2 surfaces; the smallest defensible one was a ClinVar overlay). Concretely:

- `prep/annotate.py` exists and uses `bcftools annotate` to overlay ClinVar's `CLNSIG` + `CLNREVSTAT` INFO fields onto `derived/<run-id>/normalized.vcf.gz`, renaming them to `clinvar_classification` / `clinvar_review_status`.
- The chr-prefix mismatch between ClinVar's numeric contigs (`1`, `2`, ...) and consumer-genomics chr-prefixed contigs (`chr1`, `chr2`, ...) is handled by renaming the ClinVar staged copy at annotate time (the user's normalized VCF stays canonical).
- Schema v0.2 was promoted: `variants.clinvar_id`, `variants.clinvar_classification`, `variants.clinvar_review_status` columns exist (all nullable; pre-annotate rows have NULL).
- `materialize.py` already prefers `annotated.vcf.gz` over `normalized.vcf.gz` when the annotated file is present, and pulls the ClinVar INFO fields into the v0.2 columns.
- 7 needs_bio tests in `tests/integration/test_annotate.py` cover the orchestrator + materialize's annotated-input branch.
- Real-data baseline: 4,870,517 variants / 42,885 ClinVar matches / schema v0.2 against the project owner's Nebula VCF (sample MPNRGLQ2K).

Phase 4A is a *step toward* the canonical Phase-4 deliverable, not the deliverable itself. It's structurally sound (bcftools annotate is correct; schema v0.2 is anchored; per-row provenance is intact); it's just *partial*. The remaining 4B–4E sub-phases layer the rest of the annotation surface on top.

---

## Scope Boundaries

- **In scope** (4B–4E):
  - GRCh38 reference fasta fetch (`genomeclaw-prep fetch --source grch38`); SHA256 + index (`.fai`) verification; written to `reference/grch38/`.
  - Production `bcftools norm -f <ref>` left-alignment in `normalize` (the `--reference-fasta` plumbing exists since Phase 3; this sub-phase ships the actual reference).
  - CRAM ingest enablement: `mosdepth --fasta <ref>` for coverage; `bcftools view -T <ref>` for header sniffing; CRAM smoke against the project owner's actual 50 GB CRAM.
  - gnomAD v4.1 **exomes** fetch (`--source gnomad-exomes`) + dbSNP fetch (`--source dbsnp`); URL patterns wired into `_LAYOUTS`; mocked-HTTP tests for both. gnomAD exomes is 24 per-chrom files at ~200 GB total; the fetcher downloads each in parallel under `reference/gnomad-exomes/v4.1/by_chrom/<chr>.vcf.bgz` + `.tbi`. gnomAD genomes (563 GB) is deferred per Q8.1.
  - `vcfanno` integration: Phase 4C migrates ClinVar from `bcftools annotate` to `vcfanno`, then layers gnomAD v4 + dbSNP overlays in the same pass. Tabix-indexed sources only.
  - VEP cache fetch (`--source vep_cache`); written to `reference/vep_cache/<ensembl_release>/`.
  - VEP plugin data: AlphaMissense + SpliceAI precomputed scores; placed under `reference/vep_cache/Plugins/` per VEP convention.
  - VEP integration: `--mane_select`, `--hgvs`, `--symbol`, `--canonical`, `--af_gnomadg` flags; LOFTEE / AlphaMissense / SpliceAI plugins enabled.
  - Schema v0.2 expansion in `variants`: `gnomad_af_popmax`, `gnomad_af_popmax_pop`, `gnomad_af_afr`, `gnomad_af_amr`, `gnomad_af_eas`, `gnomad_af_nfe`, `gnomad_af_sas` (representative subset; defer-by-default per spec Q10), `dbsnp_rsid`, `gene_symbol`, `mane_select_transcript`, `hgvsc`, `hgvsp`, `consequence`, `loftee_lof`, `loftee_filter`, `alphamissense_score`, `alphamissense_class`, `spliceai_max_delta`, `gene_loeuf` (from VEP's `--af_gnomadg` / dedicated LOEUF source).
  - Real-data smoke gates per sub-phase (per the planning protocol's scale-sensitive-phase rule).

- **Out of scope** (deferred):
  - Cyrius CYP2D6 outside-call (per spec Q6) — Phase 6.
  - `pgsc_calc` PRS computation (per spec Q8) — Phase 6.
  - Curated-notes evidence resolver (per spec Q9) — Phase 6.
  - PharmCAT integration — Phase 6.
  - Host service (FastAPI app reading the v0.2 store) — Phase 5.
  - Plugin / agent integration — Phase 5.
  - Schema v0.3 — out of scope for Phase 4. The v0.2 column set settles after 4E lands; if a future phase adds non-additive changes (renames, type changes, removals), v0.3 lands there.
  - Per-population gnomAD AFs beyond the seven listed (afr / amr / eas / nfe / sas / popmax / popmax_pop). Adding fin / asj / mid / ami / oth is a follow-up triggered by an observed need, not anticipated need (per spec Q10 — defer-by-default).
  - Frequency pre-filtering before VEP runs (a common throughput optimization). The project owner's host envelope can run VEP on the full ~5 M-variant set; pre-filtering is a follow-up if Phase 4D hits the personal-host budget.
  - Byte-equivalent determinism on annotated outputs. `vcfanno` and `VEP` are deterministic given fixed inputs + tools, but both embed environment data (run timestamps, hostnames) into VCF headers. The Phase-3 row-equivalence contract carries forward: per-row column values are deterministic, header bytes are not. Same gate, same modulo-non-determinism declaration.

---

## Invariants Enforced in This Phase

- **`INV-D001`** Raw genomic files source-of-truth — every annotation source under `reference/{clinvar,gnomad,dbsnp,vep_cache}/` is read by the orchestrators, never written. Test cases gate this for each sub-phase. The Phase-3 source-VCF immutability test continues to pass (the source under `raw/` never moves).
- **`INV-D003`** Heavy Scratch Is Separated From Authoritative Outputs — VEP cache + AlphaMissense + SpliceAI scores files are large (multi-GB to ~25 GB compressed), and VEP itself produces a multi-GB intermediate VCF before final compression. Every Phase-4 orchestrator allocates scratch via `shard_scratch(...)` and promotes the final annotated VCF via `atomic_promote(...)`; pre-flight assertions run at every entry. A `vcfanno` invocation with three overlay sources (ClinVar + gnomAD + dbSNP) must complete without ever writing under `derived/<run-id>/` outside the final `atomic_promote`.
- **`INV-R001`** Rebuildability — provenance step trail extended once per sub-phase: `vcfanno` step (4C), `vep` step (4D), and any future per-annotator step records its `(tool, tool_version, params_json, inputs[].sha256, outputs[].sha256)`. The `params_json` field captures the exact flag set per run so a rerun against the same reference files reproduces byte-equivalent annotation columns. `manifest.json` gains `outputs.annotated_vcf` + `_sha256` (extends Phase 4A's existing field) once `vcfanno` + VEP have both run; the `tools` block gains `vcfanno`, `vep`, plugin, and AlphaMissense/SpliceAI dataset versions.

`INV-D002` (host-side only): satisfied trivially — annotation runs on the host. None of these binaries enters the sandbox image.
`INV-P001` / `INV-P002` / `INV-E001` / `INV-C001`: still out of scope until Phase 5 (privacy/egress + host service) and Phase 6 (findings + evidence + clinical/lifestyle distinction).

---

## Open Questions Resolved

These were the open questions flagged by the predecessor turn before this plan was authored. Each is resolved below; revisit only if implementation surfaces a contradiction.

| Q | Resolution |
|---|---|
| **Q1: GRCh38 reference fasta fetch source** | NCBI's `GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz` from `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/`. Same source GATK + most short-read pipelines use; chr-prefixed contigs match consumer genomics VCFs / Nebula deliverables. ~3 GB compressed; `.fai` index built locally via `samtools faidx` after fetch. |
| **Q2: VEP cache size on the personal-host envelope** | Use the full Ensembl GRCh38 cache for the pinned release. Bioconda's `ensembl-vep` is at **115.2** as of 2026-05-09 (released 2025-09-24, verified during pre-flight); pin Ensembl release **115** for the cache. ~25 GB compressed, ~75 GB uncompressed. Fits within the 200 GB reference budget per [README's storage planning](../../../../README.md#storage-planning) on a 2 TB external drive. The `--refseq` cache variant is not used (Ensembl IDs + MANE Select pinning are sufficient). |
| **Q3: AlphaMissense + SpliceAI dataset placement** | Under `reference/vep_cache/Plugins/` per VEP plugin convention. AlphaMissense: `AlphaMissense_hg38.tsv.gz` (~1.5 GB) + tabix index. SpliceAI: precomputed scores for SNVs + indels (~50 GB combined). All bind-mounted RO into the toolkit container at runtime; INV-D001 enforced at the bind-mount layer. |
| **Q4: vcfanno vs. bcftools annotate for tabix overlays** | vcfanno. Faster (parallel chromosome processing), supports multiple sources in one pass, declarative TOML config. The Phase-4A bcftools-annotate ClinVar path is **migrated** to vcfanno during 4C — the ClinVar match count must remain stable (gate the migration with a comparison test against the 4A baseline). |
| **Q5: Module organization — extend `annotate.py` vs. split** | Split. New modules: `prep/annotate_vcfanno.py` (4C; replaces the bcftools-annotate path), `prep/annotate_vep.py` (4D). The existing `prep/annotate.py` becomes a parent orchestrator that chains them: `vcfanno` first (cheap, tabix-indexed overlays), VEP second (expensive, plugin-driven). Each sub-orchestrator is independently callable for debugging via dedicated CLI subcommands `genomeclaw-prep annotate-vcfanno` and `genomeclaw-prep annotate-vep`; the user-facing `annotate` chains them. |
| **Q6: Schema bump v0.2 → v0.3?** | Stay at v0.2. The Phase-4A v0.2 was always partial (3 ClinVar columns); v0.2 = "fully annotated" is the canonical state ship by Phase 4 close. New columns are additive non-breaking changes. Schema-version bumps are reserved for renames / type changes / removals. The host service (Phase 5) is the first consumer; it sees the final v0.2 and never the partial 4A state. |
| **Q7: Sub-phase ordering** | 4B (reference fasta fetch + left-alignment + CRAM) before 4C (vcfanno) before 4D (VEP) before 4E (materialize finalisation). Reference fasta is a hard dependency for VEP and CRAM; vcfanno is independent of VEP but must stabilize before 4D so VEP's `--af_gnomadg` integration can be cross-checked against the vcfanno-derived gnomAD columns. |
| **Q8: gnomAD per-population AF columns — how many?** | Seven, in v0: `gnomad_af_popmax` + `gnomad_af_popmax_pop` (the headline values most queries hit) and per-population AFs for the five major continental groups (`afr`, `amr`, `eas`, `nfe`, `sas`). Upstream gnomAD v4.1 exomes-only INFO IDs (verified 2026-05-11 against `gs://gcp-public-data--gnomad/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz`'s header — 413 INFO fields): `AF_grpmax` (popmax AF; **not** `AF_grpmax_joint` — the `_joint` suffix only exists in gnomAD's separate joint exomes+genomes frequency dataset), `grpmax` (popmax population), `AF_afr` / `AF_amr` / `AF_eas` / `AF_nfe` / `AF_sas`. Defer-by-default (per spec Q10) on `fin` / `asj` / `mid` / `ami` / `oth` until a user need surfaces. |
| **Q8.1: gnomAD genomes vs. exomes for v0** | **Exomes only** (verified 2026-05-09 against `gs://gcp-public-data--gnomad/release/4.1/vcf/`). Per-chrom files (24 per set): genomes = 563 GB total; exomes = 198 GB total. Exomes fits the 200 GB reference budget; genomes (and joint = both) don't on a 2 TB drive. Trade-off: non-coding variants (most of a 30× WGS's ~5M variants) get NULL gnomAD AFs. Clinical-actionable findings (ACMG SF, PharmCAT actionable haplotypes) are coding and fully covered; v0 lifestyle gene findings (CYP1A2, LCT, ALDH2, ADH1B, ADORA2A, APOE, MTHFR) are coding and fully covered. Filenames: `gnomad.exomes.v4.1.sites.chr<N>.vcf.bgz` + `.tbi` for each of `1..22`, `X`, `Y`. Genomes ships as a follow-up requiring an explicit large-drive opt-in. |
| **Q9: How does the v0.2 → finalised-v0.2 column expansion interact with materialize's drop-and-recreate?** | No interaction. `materialize._reset_variants_table` drops and recreates `variants` on the current schema's DDL every run; the DDL is the single source of truth. Each sub-phase that adds columns updates the DDL in `prep/store.py`'s `_VARIANTS_DDL` constant; the next `materialize` call picks them up. Pre-Phase-4 stores (v0.1 or partial-v0.2) are transparently upgraded on the next materialize. |
| **Q10: Where does VEP run — host-side as a bioconda package, or a separate VEP Docker image?** | Inside the `genomeclaw/toolkit` image. VEP itself is bioconda-installable (`ensembl-vep`, verified at v115.2 during pre-flight). The **plugin code** (LOFTEE, AlphaMissense, SpliceAI Perl/Python modules) is **not** packaged on bioconda separately and is fetched via `git clone` of the canonical `Ensembl/VEP_plugins` repo + `konradjk/loftee` repo at the matching VEP-115 branch into VEP's `Plugins/` dir during Docker build. The plugin **data files** (AlphaMissense scores, SpliceAI scores) live on the bind-mounted `reference/vep_cache/Plugins/` volume (per Q3) so the image stays small. Image growth: ~500 MB for `ensembl-vep`; ~100 MB for plugin Perl/Python source. The cache + data files stay on the bind-mounted `reference/` volume so the image stays user-owned-data-free. |

---

## Sub-phase 4B — Reference fasta fetch + production left-alignment + CRAM ingest

**Goal**: `genomeclaw-prep fetch --source grch38` writes the GRCh38 reference fasta + index to `reference/grch38/`. `genomeclaw-prep normalize --reference-fasta /mnt/genomeclaw/reference/grch38/grch38.fa.gz` runs left-alignment in production. `genomeclaw-prep ingest --bam <CRAM>` works end-to-end with `mosdepth --fasta`.

### Step 4B.1 — RED tests

Test cases by category. INV-IDs in the test name where they directly enforce.

**`fetch --source grch38`** (`tests/integration/test_fetch_grch38.py`):

1. `test_fetch_grch38_writes_versioned_path_mocked` — mocked HTTP returning a tiny fixture FASTA + checksum; `fetch --source grch38 --release ncbi-2014` writes `reference/grch38/ncbi-2014/grch38.fa.gz` + `.fa.gz.fai` + `.md5`; checksum verified.
2. `test_fetch_grch38_builds_fai_index` — after fetch the `.fai` exists and `samtools faidx` recognizes it (in-image, needs_bio).
3. `test_fetch_grch38_rejects_checksum_mismatch_mocked` — wrong checksum → `ChecksumMismatch`; no canonical file written.
4. `test_fetch_grch38_refuses_to_overwrite_existing_release` — same release dir already populated → `VersionAlreadyExists`; prior bytes unchanged.

**Production left-alignment in `normalize`** (`tests/integration/test_normalize_left_align.py` — needs_bio):

5. `test_invR001_normalize_with_reference_left_aligns_indels` — fixture with a not-left-aligned indel (e.g., `pos=100 ref=AT alt=A` where the same change is canonical at `pos=99 ref=GA alt=G`); after `normalize(--reference-fasta=<fixture>)`, the variant appears at the canonical position; provenance step records `params.left_align: true`.

**CRAM ingest** (`tests/integration/test_ingest_cram.py` — needs_bio):

6. `test_ingest_cram_with_mosdepth_fasta` — synthetic CRAM fixture + reference fasta + BED; `ingest(vcf=..., bam=<CRAM>, bed=..., reference_fasta=...)` populates `coverage_qc`; CRAM SHA256 unchanged after run (`INV-D001`); the `mosdepth-coverage` provenance step records `params.fasta_path` + `params.fasta_sha256`.

### Step 4B.2 — GREEN

- `prep/fetch.py`:
  - Extend `_LAYOUTS` with `"grch38"` (URL pattern + checksum source + output filename `grch38.fa.gz`).
  - After download + checksum, run `samtools faidx <out>.fa.gz` to build the `.fai` index in the same directory.
  - The `grch38` release tag is opaque (no upstream-provided release identifier; pick the date-stamped form `ncbi-YYYY-MM-DD` from the deliverable's mtime, recorded in a sidecar `RELEASE.txt`).
- `prep/_bcftools_norm.py`: already supports `reference_fasta`; no change.
- `prep/_mosdepth.py`: already supports `--fasta` (Phase 2C-C plumbed it through but didn't ship a CRAM fixture). Wire it into `prep/ingest.py:run_mosdepth(...)` calls so CRAM ingest works.
- `prep/ingest.py`: extend `ingest()` signature with `reference_fasta: Path | None = None`; thread it into the mosdepth call when the BAM is a CRAM (auto-detect via `.cram` suffix or `samtools view --header-only`-based check).
- `cli.py`: extend `_add_ingest` with `--reference-fasta` flag; required when `--bam` is a CRAM.

### Step 4B.3 — REFACTOR

- The `grch38` fetch + `samtools faidx` post-step is the first fetch source that runs a tool after download. If a second source needs the same pattern, lift the post-fetch hook into a `_LAYOUTS[<source>].post_fetch` callable. Tolerated as inline for 4B.

### Real-data smoke (4B gate)

```bash
# Fetch the GRCh38 reference fasta (3 GB; ~5–10 min on a typical home connection).
bin/genomeclaw-prep fetch --source grch38 --release ncbi-2014

# Re-run the project owner's CRAM through ingest with --reference-fasta.
# (The Phase-2 ingest path used --bam <BAM>; this is the first CRAM smoke.)
bin/genomeclaw-prep ingest \
  --vcf /mnt/genomeclaw/raw/<sample>/sample.vcf.gz \
  --bam /mnt/genomeclaw/raw/<sample>/sample.cram \
  --reference /mnt/genomeclaw/reference/grch38/ \
  --reference-fasta /mnt/genomeclaw/reference/grch38/<release>/grch38.fa.gz \
  --sample-id <sample>
# Expected: CRAM SHA256 unchanged (INV-D001); coverage_qc populated; mosdepth-coverage
# provenance step records reference_fasta path + SHA256.

# Re-run normalize with left-alignment.
bin/genomeclaw-prep normalize \
  --run-dir /mnt/genomeclaw/derived/<run-id> \
  --reference-fasta /mnt/genomeclaw/reference/grch38/<release>/grch38.fa.gz
# Expected: row count post-left-align stays at ~4.79 M (no row creation/deletion);
# provenance step records params.left_align: true; some indels shift position
# (compare to the Phase-3 baseline run with no left-align).
```

---

## Sub-phase 4C — vcfanno migration + gnomAD v4 + dbSNP overlays

**Goal**: One `vcfanno` invocation overlays ClinVar + gnomAD v4 + dbSNP onto `normalized.vcf.gz` (or onto the post-VEP VCF in 4D). The Phase-4A bcftools-annotate ClinVar path is removed; `prep/annotate.py` chains `annotate_vcfanno → annotate_vep → atomic_promote`. New v0.2 columns: `gnomad_af_popmax`, `gnomad_af_popmax_pop`, `gnomad_af_{afr,amr,eas,nfe,sas}`, `dbsnp_rsid`. ClinVar columns (`clinvar_id`, `clinvar_classification`, `clinvar_review_status`) carry forward unchanged.

### Step 4C.1 — RED tests

**`fetch --source gnomad`** (`tests/integration/test_fetch_gnomad.py`):

7. `test_fetch_gnomad_writes_versioned_path_mocked` — mocked HTTP for gnomAD v4 sites VCF (per-chrom files; the fetcher concats or downloads per-chrom into `reference/gnomad/v4.0/`). Checksum verified.
8. `test_fetch_gnomad_builds_tabix_index` — after fetch the `.tbi` exists; `bcftools view -r chr17:1-1000` works (in-image, needs_bio).

**`fetch --source dbsnp`** (`tests/integration/test_fetch_dbsnp.py`):

9. `test_fetch_dbsnp_writes_versioned_path_mocked` — mocked HTTP for dbSNP build (`--release b156`); writes `reference/dbsnp/b156/dbsnp.vcf.gz` + `.tbi`; checksum verified.

**`vcfanno` orchestrator** (`tests/integration/test_annotate_vcfanno.py` — needs_bio):

10. `test_annotate_vcfanno_writes_annotated_vcf_in_run_dir` — happy path: `annotate_vcfanno(run_dir, reference_dir)` produces `run_dir/vcfanno.vcf.gz` + `.tbi`.
11. `test_annotate_vcfanno_overlays_clinvar_classifications` — fixture VCF + fixture ClinVar slice; vcfanno output's INFO carries `clinvar_classification` for matching variants. Match count matches the bcftools-annotate baseline ± ε (the test fixture is small enough that ε = 0).
12. `test_annotate_vcfanno_overlays_gnomad_af_popmax` — fixture VCF + fixture gnomAD slice; output INFO carries `gnomad_af_popmax` + `gnomad_af_popmax_pop` for matching variants.
13. `test_annotate_vcfanno_overlays_dbsnp_rsid` — fixture VCF + fixture dbSNP slice; output INFO carries `dbsnp_rsid` for matching variants.
14. `test_annotate_vcfanno_chr_prefix_alignment` — fixture mixes chr-prefixed VCF with unprefixed ClinVar; the orchestrator renames the staged ClinVar copy at staging time (same pattern as Phase 4A); zero overlap without the rename, expected overlap count with the rename.
15. `test_invR001_annotate_vcfanno_provenance_step` — `provenance.json` gains a `vcfanno` step with input identities (normalized VCF SHA + ClinVar/gnomAD/dbSNP SHAs) + output identity + `params.config` (the inline TOML).
16. `test_invD001_annotate_vcfanno_does_not_mutate_reference_files` — capture SHA256 of ClinVar / gnomAD / dbSNP files before; rerun after annotate_vcfanno; assert all unchanged.
17. `test_invD003_annotate_vcfanno_uses_shard_scratch` — observability test: instrument `tempfile` to record any path created during annotate_vcfanno; assert all paths fall under `/mnt/genomeclaw/scratch/` (none under `/tmp` or `derived/`).

**`annotate` parent orchestrator** (`tests/integration/test_annotate.py` — extend existing):

18. `test_annotate_chains_vcfanno_then_vep` — mocked VEP (skipped at this sub-phase since 4D adds it); for now assert `annotate(run_dir)` calls `annotate_vcfanno` and the final `annotated.vcf.gz` carries the vcfanno-overlaid INFO fields.

### Step 4C.2 — GREEN

- `prep/fetch.py`: extend `_LAYOUTS` with `"gnomad"` + `"dbsnp"`. gnomAD v4 uses per-chrom files (concat or fetch-on-demand; pick fetch-on-demand for simplicity; the VCF can be queried per-region by tabix). dbSNP is one large file (~25 GB compressed); fetch-then-tabix-index.
- `prep/_vcfanno.py`: new subprocess wrapper. `vcfanno_run(*, config_toml, input_vcf, output_vcf, scratch_dir)`. Builds the TOML config (path to each overlay source + INFO field renames + post-rename column names). Runs `vcfanno -p <ncpu> <config> <input>` piped through `bgzip` to `output_vcf`. Indexes with `tabix`.
- `prep/annotate_vcfanno.py`: orchestrator. Reads `manifest.json` → `normalized_vcf` path + sha; resolves ClinVar / gnomAD / dbSNP releases (auto-pick newest if not specified); stages each into `shard_scratch(...)` (with chr-prefix-alignment renames as needed); runs `vcfanno_run`; writes `vcfanno.vcf.gz` to scratch, `atomic_promote`s into `derived/<run-id>/`. Updates `manifest.outputs.vcfanno_vcf` + `_sha256`. Appends a `vcfanno` step to `provenance.json` recording each annotation source's SHA256 + the inline TOML config + `vcfanno --version`.
- `prep/annotate.py`: parent orchestrator. Becomes a 50-line chain: `assert preflight; annotate_vcfanno(run_dir, ...); annotate_vep(run_dir, ...); atomic_promote(scratch/annotated.vcf.gz → run_dir/annotated.vcf.gz)`. Removes the inline `bcftools annotate` ClinVar path from Phase 4A (the test surface migrates to test_annotate_vcfanno.py).
- `cli.py`: add `_add_annotate_vcfanno` / `_run_annotate_vcfanno` (in addition to the existing `_add_annotate` parent).
- `prep/store.py`: extend `_VARIANTS_DDL` with the new gnomAD + dbSNP columns (NULLable). Keep ClinVar columns unchanged.

### Step 4C.3 — REFACTOR

- The chr-prefix-alignment rename pattern repeats between Phase 4A's annotate.py and the new annotate_vcfanno.py. Lift to a `prep/_chr_prefix.py` helper if a third caller arrives.
- Remove the dead Phase-4A `_CLINVAR_TO_GRCH38_CHR_MAP` constant from `annotate.py` after the migration is verified against real data.
- Run full suite + lint + format. Test count: ~148 → ~160 (12 new).

### Real-data smoke (4C gate)

```bash
# Fetch gnomAD v4 + dbSNP (the big downloads).
bin/genomeclaw-prep fetch --source gnomad --release v4.0
bin/genomeclaw-prep fetch --source dbsnp --release b156

# Re-run annotate against the project owner's normalized VCF; expect ClinVar
# match count to match the Phase 4A baseline (42,885) within ε.
bin/genomeclaw-prep annotate-vcfanno --run-dir /mnt/genomeclaw/derived/<run-id>
bin/genomeclaw-prep materialize --run-dir /mnt/genomeclaw/derived/<run-id>

# Verify:
duckdb /mnt/genomeclaw/derived/<run-id>/variants.duckdb \
  "SELECT COUNT(*) FROM variants WHERE clinvar_classification IS NOT NULL;"
# Expected: ~42,885 (within ε).

duckdb /mnt/genomeclaw/derived/<run-id>/variants.duckdb \
  "SELECT COUNT(*) FROM variants WHERE gnomad_af_popmax IS NOT NULL;"
# Expected: high coverage — gnomAD v4 has AFs for most known variants.

duckdb /mnt/genomeclaw/derived/<run-id>/variants.duckdb \
  "SELECT COUNT(*) FROM variants WHERE dbsnp_rsid IS NOT NULL;"
# Expected: high coverage.
```

If the ClinVar match count drifts more than ε (~5% of 42,885 = ~2,144 variants), investigate: vcfanno's matching semantics differ subtly from `bcftools annotate` on multi-allelic INFO fields — this is the kind of regression a real-data smoke catches.

---

## Sub-phase 4D — VEP + LOFTEE + AlphaMissense + SpliceAI

**Goal**: VEP runs against the post-vcfanno VCF with MANE Select transcript pinning + the four plugins. Adds: `gene_symbol`, `mane_select_transcript`, `hgvsc`, `hgvsp`, `consequence`, `loftee_lof`, `loftee_filter`, `alphamissense_score`, `alphamissense_class`, `spliceai_max_delta`, `gene_loeuf` columns to v0.2.

### Step 4D.1 — RED tests

**`fetch --source vep_cache`** (`tests/integration/test_fetch_vep_cache.py`):

19. `test_fetch_vep_cache_writes_versioned_path_mocked` — mocked HTTP for VEP cache (a tiny synthetic cache); writes `reference/vep_cache/112/`; checksum verified.
20. `test_fetch_vep_cache_extracts_tarball` — VEP cache ships as a tarball; the fetcher extracts in place.
21. `test_fetch_alphamissense_dataset` — mocked HTTP for AlphaMissense scores file; writes `reference/vep_cache/Plugins/AlphaMissense_hg38.tsv.gz` + `.tbi`.
22. `test_fetch_spliceai_dataset` — mocked HTTP for SpliceAI scores files; writes under `reference/vep_cache/Plugins/SpliceAI/`.

**VEP orchestrator** (`tests/integration/test_annotate_vep.py` — needs_bio):

23. `test_annotate_vep_writes_annotated_vcf_in_run_dir` — happy path: `annotate_vep(run_dir, reference_dir)` produces `run_dir/vep.vcf.gz` + `.tbi`.
24. `test_annotate_vep_emits_mane_select_transcript_id` — fixture VCF + fixture VEP cache (with MANE Select annotated); output INFO carries `MANE_SELECT` field for canonical transcripts; `mane_select_transcript` column populated server-side.
25. `test_annotate_vep_emits_hgvsc_hgvsp` — fixture missense variant in BRCA1; output INFO carries `HGVSc` + `HGVSp` strings; populated into typed columns.
26. `test_annotate_vep_loftee_marks_high_confidence_lof` — fixture stop-gained variant; output carries LOFTEE's `LoF=HC`; `loftee_lof` populated.
27. `test_annotate_vep_alphamissense_scores_populated` — fixture missense; output carries AlphaMissense score + class; columns populated.
28. `test_annotate_vep_spliceai_max_delta_populated` — fixture splice-region variant; output carries SpliceAI's `SpliceAI=...|...|...|...` aggregated to `spliceai_max_delta`.
29. `test_invR001_annotate_vep_provenance_step` — `provenance.json` gains a `vep` step with VEP version, MANE Select cache version, plugin versions (LOFTEE git rev, AlphaMissense data version, SpliceAI version), input + output SHA256s, and the exact CLI flags used (`params.flags`).
30. `test_invD001_annotate_vep_does_not_mutate_cache_or_plugins` — capture VEP cache + plugin file SHA256s before; rerun after; assert all unchanged.
31. `test_invD003_annotate_vep_uses_shard_scratch` — VEP's intermediate VCF (multi-GB at WGS scale) lives under `/mnt/genomeclaw/scratch/vep/<run-id>/`, not `derived/`.

**`annotate` parent extension**:

32. `test_annotate_chains_vcfanno_then_vep_end_to_end` — full chain: `annotate(run_dir)` runs vcfanno, then VEP, then atomic_promote. The final `annotated.vcf.gz` carries all INFO fields from both steps.
33. `test_annotate_idempotent_on_rerun` — running `annotate` twice on the same run_dir is a no-op the second time (or reproduces byte-equivalent INFO column values; same row-equivalence contract Phase 3 anchored).

### Step 4D.2 — GREEN

- `prep/fetch.py`: add `vep_cache` and the AlphaMissense / SpliceAI dataset sources. Each is a different shape (cache tarball; tabix-indexed scores file; per-chrom score file directory). The fetcher gets a per-source post-fetch hook (refactored in 4B).
- `prep/_vep.py`: new subprocess wrapper. `vep_run(*, input_vcf, output_vcf, vep_cache_dir, plugin_dir, scratch_dir)`. Builds the flag list: `--mane_select`, `--hgvs`, `--symbol`, `--canonical`, `--af_gnomadg`, `--cache`, `--dir_cache <cache>`, `--dir_plugins <plugins>`, `--plugin LoF,...`, `--plugin AlphaMissense,...`, `--plugin SpliceAI,...`, `--vcf`, `--compress_output bgzip`. Runs `vep <flags> -i <in> -o <out>`.
- `prep/annotate_vep.py`: orchestrator. Stages input + plugin data into scratch via `shard_scratch`; runs `vep_run`; `atomic_promote`s `vep.vcf.gz` into `derived/<run-id>/`. Updates `manifest.outputs.vep_vcf` + `_sha256`. Appends a `vep` step to `provenance.json` capturing every plugin version + the full flag list.
- `prep/annotate.py`: parent now chains `annotate_vcfanno` → `annotate_vep` → `atomic_promote(annotated.vcf.gz)` (the final renamed copy of `vep.vcf.gz` is the canonical `annotated.vcf.gz` materialize consumes).
- `prep/store.py`: extend `_VARIANTS_DDL` with the eleven VEP-derived columns. Keep nullable.
- Toolkit Dockerfile gains: bioconda install of `ensembl-vep=115.2`; `git clone` of `Ensembl/VEP_plugins` + `konradjk/loftee` at the matching VEP-115 branch into `/opt/vep/.vep/Plugins/`. The plugin **code** is in the image; the plugin **data** (AlphaMissense / SpliceAI scores) lives on the bind-mounted `reference/vep_cache/Plugins/` volume per Q3. Verified pre-flight: bioconda has `ensembl-vep` at 115.2 but **not** `loftee` or `ensembl-vep-loftee` as separate packages — git-clone is the canonical install path.

### Step 4D.3 — REFACTOR

- VEP's plugin enablement is a TOML/JSON config in 4D; if a future phase adds a fifth plugin, lift to a config-driven loader.
- Run full suite + lint + format. Test count: ~160 → ~175 (15 new).

### Real-data smoke (4D gate)

```bash
# Fetch the heavy data (these will run for hours).
bin/genomeclaw-prep fetch --source vep_cache --release ensembl-112
bin/genomeclaw-prep fetch --source alphamissense --release v1.0
bin/genomeclaw-prep fetch --source spliceai --release v1.3

# Run the full annotate chain against the project owner's normalized VCF.
time bin/genomeclaw-prep annotate \
  --run-dir /mnt/genomeclaw/derived/<run-id> \
  --vep-cache-dir /mnt/genomeclaw/reference/vep_cache/ensembl-112/ \
  --plugin-dir /mnt/genomeclaw/reference/vep_cache/Plugins/

# Personal-host envelope check: if VEP runs > 4 hours wall-time on the project
# owner's host, the budget is over the line and pre-filtering becomes a
# follow-up. Phase 4D's gate is "completes within 4 hours; uses < 32 GB RAM".

bin/genomeclaw-prep materialize --run-dir /mnt/genomeclaw/derived/<run-id>

# Verify:
duckdb /mnt/genomeclaw/derived/<run-id>/variants.duckdb \
  "SELECT COUNT(*) FROM variants WHERE mane_select_transcript IS NOT NULL;"
duckdb /mnt/genomeclaw/derived/<run-id>/variants.duckdb \
  "SELECT COUNT(*) FROM variants WHERE alphamissense_score IS NOT NULL;"
duckdb /mnt/genomeclaw/derived/<run-id>/variants.duckdb \
  "SELECT COUNT(*) FROM variants WHERE loftee_lof = 'HC';"
# Expected: meaningful counts in each — exact thresholds documented in
# work-notes after the first real-data run.
```

---

## Sub-phase 4E — Schema v0.2 finalisation in materialize

**Goal**: Every Phase-4 INFO field flows through `materialize` into a typed column. The `info_fields` tuple `materialize.py` already passes to `iter_variant_rows` is extended; type coercions handled (`alphamissense_score` is float; `loftee_lof` is enum; `gnomad_af_*` are floats; `dbsnp_rsid` is string). Provenance trail captures every annotator's tool + version.

### Step 4E.1 — RED tests

**`tests/integration/test_materialize_v02_columns.py` — needs_bio**:

34. `test_materialize_populates_all_phase4_columns` — fixture annotated VCF (synthesized with handcrafted INFO fields covering every Phase-4 column); after `materialize`, every Phase-4 column has at least one non-NULL row; type coercions correct (floats are floats, ints are ints, enums match the documented value set).
35. `test_materialize_handles_missing_optional_columns` — fixture VCF with no AlphaMissense INFO (e.g., the variant is in a region with no precomputed score); column is NULL; no crash.
36. `test_materialize_v02_schema_meta_recorded` — `schema_meta.schema_version == "v0.2"`; the host service's schema-load gate (lands Phase 5) will accept it.
37. `test_invR001_materialize_provenance_step_includes_all_annotators` — after a full `ingest → normalize → annotate-vcfanno → annotate-vep → materialize` chain, `provenance.json`'s step trail is `["ingest", "bcftools-stats", ("mosdepth-coverage")?, "normalize", "vcfanno", "vep", "materialize"]` and `manifest.tools` carries every annotator version.

**Determinism extension** (`tests/determinism/test_invR001_full_pipeline.py` — extend existing):

38. `test_invR001_full_pipeline_with_annotate_row_equivalent_on_rerun` — two full ingest+normalize+annotate+materialize runs against the same VCF + same fixed clock + same reference/annotation files produce row-equivalent variants tables (same row count + same per-row column values, modulo `source_path`). Same row-equivalence contract Phase 3 anchored.

**End-to-end smoke** (`tests/integration/test_pipeline_e2e_synthetic.py` — needs_bio):

39. `test_pipeline_e2e_synthetic_fixture` — full chain on a synthetic fixture; assert: row count = 6 (the chr17 multi-allelic split case from Phase 3); ClinVar / gnomAD / dbSNP / VEP / plugin columns populated where the fixture has matching annotations; provenance step trail complete.

### Step 4E.2 — GREEN

- `prep/_vcf.py:iter_variant_rows`: extend `info_fields` parameter handling to coerce types correctly (the existing implementation passes everything through as strings; 4E adds typed coercion).
- `prep/materialize.py`: extend the `info_fields` tuple per `materialize_input_kind`. Keep the existing 4A path (just `clinvar_classification` + `clinvar_review_status`) for backwards-compat with v0.1-only stores (none in production but future-proofing the migration story).
- `prep/store.py:_VARIANTS_DDL`: final column set anchored.

### Step 4E.3 — REFACTOR

- The `info_fields` per-`materialize_input_kind` dispatch is verbose; if a fourth kind arrives, lift to a config dict.
- Run full suite + lint + format. Test count: ~175 → ~187 (12 new — 4 new direct + 1 determinism + 1 e2e + 6 indirect coverage).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | Add `_LAYOUTS["grch38"]`, `_LAYOUTS["gnomad"]`, `_LAYOUTS["dbsnp"]`, `_LAYOUTS["vep_cache"]`, `_LAYOUTS["alphamissense"]`, `_LAYOUTS["spliceai"]`. Per-source post-fetch hook. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_vcfanno.py` | CREATE | `vcfanno` subprocess wrapper. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` | CREATE | `vep` subprocess wrapper with plugin flag construction. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py` | CREATE | vcfanno orchestrator (4C). |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py` | CREATE | VEP orchestrator (4D). |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` | REWRITE | Parent orchestrator chains vcfanno + vep + atomic_promote; remove Phase-4A bcftools-annotate path. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` | MODIFY | Accept `--reference-fasta` for CRAM ingest; thread into `run_mosdepth`. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | MODIFY | Extend `_VARIANTS_DDL` with Phase-4 columns. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_vcf.py` | MODIFY | `iter_variant_rows` typed-coercion for new INFO fields. |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | MODIFY | Add `annotate-vcfanno`, `annotate-vep` subcommands; extend `ingest` + `normalize` with `--reference-fasta`; extend `annotate` with `--vep-cache-dir`, `--plugin-dir`. |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/manifest.py` | MODIFY | Extend `ManifestOutputs` with `vcfanno_vcf`, `vep_vcf` paths + SHA256 fields. |
| `packages/toolkit/Dockerfile` | MODIFY | Bioconda manifest gains `ensembl-vep`, `loftee`, `vcfanno`. |
| `packages/toolkit/tests/integration/test_fetch_grch38.py` | CREATE | 4 test cases for GRCh38 fetch. |
| `packages/toolkit/tests/integration/test_fetch_gnomad.py` | CREATE | 2 test cases. |
| `packages/toolkit/tests/integration/test_fetch_dbsnp.py` | CREATE | 1 test case. |
| `packages/toolkit/tests/integration/test_fetch_vep_cache.py` | CREATE | 4 test cases. |
| `packages/toolkit/tests/integration/test_normalize_left_align.py` | CREATE | 1 test case (4B). |
| `packages/toolkit/tests/integration/test_ingest_cram.py` | CREATE | 1 test case (4B). |
| `packages/toolkit/tests/integration/test_annotate_vcfanno.py` | CREATE | 8 test cases (4C). |
| `packages/toolkit/tests/integration/test_annotate_vep.py` | CREATE | 9 test cases (4D). |
| `packages/toolkit/tests/integration/test_annotate.py` | MODIFY | Drop Phase-4A bcftools-annotate-specific tests; add the chained-orchestrator tests (cases 18, 32, 33). |
| `packages/toolkit/tests/integration/test_materialize_v02_columns.py` | CREATE | 4 test cases (4E). |
| `packages/toolkit/tests/integration/test_pipeline_e2e_synthetic.py` | CREATE | 1 e2e test (4E). |
| `packages/toolkit/tests/determinism/test_invR001_full_pipeline.py` | MODIFY | Add `test_invR001_full_pipeline_with_annotate_row_equivalent_on_rerun` (case 38). |

---

## Verification

```bash
cd packages/toolkit

# Build the (now-bigger) toolkit image. VEP + plugins land via bioconda.
docker build --tag genomeclaw/toolkit:dev .

# Tool-version sanity checks.
docker run --rm --entrypoint vep genomeclaw/toolkit:dev --help | head -3
docker run --rm --entrypoint vcfanno genomeclaw/toolkit:dev --help 2>&1 | head -3
docker run --rm --entrypoint samtools genomeclaw/toolkit:dev --version | head -1

# Host-venv tests (no bcftools/vep needed; pure-Python).
uv run pytest -q
# Expected: same 69 tests as Phase 3 close + the mocked-fetch tests for
# grch38/gnomad/dbsnp/vep_cache/alphamissense/spliceai (+~12 host-side).

# In-image tests (run the bcftools/vcfanno/VEP-dependent suite).
docker run --rm --user $(id -u):$(id -g) \
  --mount type=bind,source=$(pwd),target=/work \
  --workdir /work \
  --entrypoint pytest \
  genomeclaw/toolkit:dev \
  -m needs_bio -q
# Expected: 187 passed (148 baseline + ~39 Phase-4 needs_bio).

# Static checks.
uv run ruff check .
uv run ruff format --check .
```

**Per-sub-phase real-data smoke gates** (run locally on the project owner's host):

Each sub-phase gate is documented in its section above. The Phase-4 close gate is the **full-chain real-data run**:

```bash
bin/genomeclaw-prep ingest \
  --vcf /mnt/genomeclaw/raw/<sample>/sample.vcf.gz \
  --bam /mnt/genomeclaw/raw/<sample>/sample.cram \
  --reference /mnt/genomeclaw/reference/grch38/ \
  --reference-fasta /mnt/genomeclaw/reference/grch38/<release>/grch38.fa.gz \
  --sample-id <sample>

bin/genomeclaw-prep normalize \
  --run-dir /mnt/genomeclaw/derived/<run-id> \
  --reference-fasta /mnt/genomeclaw/reference/grch38/<release>/grch38.fa.gz

bin/genomeclaw-prep annotate \
  --run-dir /mnt/genomeclaw/derived/<run-id> \
  --reference-dir /mnt/genomeclaw/reference \
  --vep-cache-dir /mnt/genomeclaw/reference/vep_cache/ensembl-112/ \
  --plugin-dir /mnt/genomeclaw/reference/vep_cache/Plugins/

bin/genomeclaw-prep materialize --run-dir /mnt/genomeclaw/derived/<run-id>
```

**Real-data outcomes recorded in [work-notes.md](../work-notes.md) at phase close** (placeholder schema; populate during implementation):

| Metric | Target |
|--------|--------|
| Total wall-time | < 6 hours on the project owner's host |
| Peak RAM | < 32 GB (the personal-host envelope) |
| Total variant rows | ~4,870,517 (matches Phase 3 baseline; left-alignment doesn't change row count) |
| ClinVar match count | ~42,885 ± ε vs. Phase 4A baseline (vcfanno migration sanity) |
| `gnomad_af_popmax IS NOT NULL` | TBD; expected ≥ 95% of rows |
| `dbsnp_rsid IS NOT NULL` | TBD; expected ≥ 95% of rows |
| `mane_select_transcript IS NOT NULL` | TBD; only canonical transcripts |
| `alphamissense_score IS NOT NULL` | TBD; only missense variants in protein-coding genes |
| `loftee_lof = 'HC'` count | TBD; expected hundreds across a 30× WGS |
| `spliceai_max_delta IS NOT NULL` | TBD; only variants near splice sites |
| Provenance step trail | `["ingest", "bcftools-stats", "mosdepth-coverage", "normalize", "vcfanno", "vep", "materialize"]` |
| `INV-D001` re-confirmed | Source VCF + CRAM + every reference file SHA256 byte-matches manifest |
| `INV-D003` re-confirmed | Heavy-scratch observability test passes; no >1 GB write under `derived/<run-id>/` outside `atomic_promote` |

If any column populated count is dramatically below the Target column, investigate before declaring Phase 4 closed — the gap usually means a flag was passed wrong or a plugin failed silently. VEP is famously chatty about partial failures; redirect VEP's stderr to the run dir and grep for `ERROR` / `WARN` after every real-data run.

---

## Completion Criteria

- [ ] Sub-phase 4B complete: GRCh38 fetch + production left-alignment + CRAM ingest. 6 new tests pass.
- [ ] Sub-phase 4C complete: vcfanno migration + gnomAD + dbSNP overlays. 12 new tests pass; ClinVar match count parity gate against the Phase 4A baseline.
- [ ] Sub-phase 4D complete: VEP + LOFTEE + AlphaMissense + SpliceAI; MANE Select pinning. 15 new tests pass; personal-host envelope respected (< 4 hours; < 32 GB RAM).
- [ ] Sub-phase 4E complete: schema v0.2 finalised; every Phase-4 column populated on the real-data row count where applicable. 6 new tests pass.
- [ ] Full suite green: ~187 tests pass (148 baseline + ~39 Phase-4).
- [ ] `uv run ruff check .` + `uv run ruff format --check .` clean.
- [ ] **Real-data smoke gate** passes per the per-sub-phase tables; full-chain wall-time under 6 hours on the project owner's host.
- [ ] [work-notes.md](../work-notes.md) records: per-sub-phase RED → GREEN → REFACTOR cadence; decisions taken; real-data outcomes per the table above.
- [ ] Phase 4 status set to **Complete** in [development-plan.md](../development-plan.md) Progress Tracking; `bcftools annotate` ClinVar-only Phase-4A interim row in the table is noted as superseded.
- [ ] [phases/phase-5.md](phase-5.md) authored before Phase 4 closes.

### Carry-overs to Phase 5 / later

- **Frequency pre-filtering before VEP** — if Phase 4D's real-data smoke shows VEP exceeds the 4-hour budget, pre-filter against gnomAD popmax before running VEP plugins. The order would become: `vcfanno` (overlays gnomAD) → filter (drop common variants for clinical-track use; lifestyle track keeps them) → `vep` (annotates the survivors). Mark as a follow-up plan if the budget is over the line.
- **Per-population gnomAD AFs beyond the seven shipped** — `fin` / `asj` / `mid` / `ami` / `oth`. Defer-by-default per spec Q10; revisit when a user need surfaces.
- **`v0.3` schema bump** — out of scope for Phase 4. The v0.2 column set settles after 4E lands; if Phase 5/6 surfaces non-additive changes (renames, type changes), v0.3 lands there.
- **Cross-validation against GATK HaplotypeCaller** — orthogonal to Phase 4. Mentioned in the cram-scratch-strategy plan's open follow-ups (per the project owner's MVP spec). Lands as its own plan if observed need surfaces.
- **VEP annotation cache versioning** — Phase 4 pins Ensembl 112 in the `_LAYOUTS` config. A future ClinVar / gnomAD / dbSNP / Ensembl release triggers a reanalysis (per spec; reanalysis-diff endpoint in Horizon 6, not v0). Today the pinned-version data lives in `manifest.tools`; the host service (Phase 5) surfaces it via `/v1/health.annotation_source_versions`.

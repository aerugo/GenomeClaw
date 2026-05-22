# Phase 1: Tier 1 PCA-Site Materialize + Per-Sample Force-Genotype

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Deliver a deterministic, on-device, fully provenanced Tier 1 PCA-site cache: one `tier1.vcf.gz` per (sample, panel_version) carrying ~400–500k records (one per LD-pruned PCA-eligible HGDP+1kGP site), built by `bcftools mpileup → call → norm` from the user's CRAM. Resolution of Open Question Q1 (full-autosome wall-clock) is deferred to Phase 5; this phase establishes the primitive and its CI-tractable synthetic-fixture tests.

## Scope Boundaries

- **In scope**:
  - `_materialize_pca_sites(panel_root, output_root)` — plink2 LD-prune via DooD; prune-in → tabix-indexed `pca_sites.tsv.gz` + `pca_alleles.tsv.gz`.
  - `_force_genotype_tier1(cram, sites_tsv, alleles_tsv, fasta, output_vcf)` — streaming bcftools pipe.
  - `_summarize_tier1_qc(tier1_vcf) → dict` — mean DP, GT-class counts, missing rate, per-chrom record counts.
  - `tier1.qc.json` provenance: source CRAM SHA256, panel version, tool versions, prune-in checksum.
  - `materialize.py` registration of `prs_pca_sites` target.
  - CLI `genomeclaw prs prepare-coverage --sample <id>` (Tier 1 only).
  - Doctor section `_collect_prs_coverage_ready` (informational).
- **Out of scope** (deferred to later phases):
  - Tier 2 per-PGS site lists (Phase 2).
  - QC threshold table / decline classifier (Phase 3).
  - `_build_pgsc_calc_argv` `-profile conda → docker` switch (Phase 4).
  - Removal of `pgs_catalog_ancestry` post-fetch extraction hook (Phase 4).
  - End-to-end PGS computation (Phase 4/5).

## Invariants Enforced in This Phase

- **INV-D001** Raw Genomic Files Are Source-of-Truth — tests assert the user CRAM mtime + content SHA256 are unchanged after a Tier 1 run.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — Tier 1 VCF is written to `_scratch/prs_coverage_work/<run_id>/` first and `atomic_promote`-d to `derived/prs_coverage/<sample_id>/<panel_version>/tier1.vcf.gz`. Test asserts the destination directory under `derived/` never observes a partial write.
- **INV-R001** Derived Stores Must Stay Rebuildable — `tier1.qc.json` records source CRAM SHA256, panel version, bcftools version, plink2 version, parameter JSON; rerunning with same inputs + same tool versions produces byte-equivalent uncompressed VCF content.
- **INV-P001** Privacy Default — privacy-default test asserts zero outbound calls during `prepare-coverage` with default config.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases**:

1. `test_materialize_pca_sites_emits_indexed_tsvs` — Given a tiny synthetic panel (chr22-only, 100 panel variants), `_materialize_pca_sites` produces `pca_sites.tsv.gz`, `pca_sites.tsv.gz.tbi`, `pca_alleles.tsv.gz`, `pca_alleles.tsv.gz.tbi`. The TSV chromosome column carries the `chr` prefix.
2. `test_materialize_pca_sites_is_byte_deterministic` — Rebuilding from the same panel produces identical uncompressed TSV content. (Bgzip block boundaries may vary; assert on uncompressed bytes.)
3. `test_invR001_materialize_pca_sites_records_provenance` — A sidecar `pca_sites.provenance.json` records panel SHA256, plink2 version, prune parameters.
4. `test_force_genotype_tier1_against_synthetic_cram_produces_expected_gt_distribution` — Given a small synthetic CRAM with planted variants at 100 sites (50 REF/REF, 30 het, 15 hom-alt, 5 low-coverage), `_force_genotype_tier1` emits a VCF whose GT distribution matches plant within ±2 records.
5. `test_force_genotype_tier1_writes_to_scratch_first_then_promotes` — A spy on `atomic_promote` records the source path; assert it's under `_scratch/`, the destination is under `derived/`.
6. `test_invD001_tier1_does_not_mutate_cram` — Captures CRAM SHA256 before + after; equal.
7. `test_invR001_tier1_qc_json_has_required_fields` — Required keys: `source_cram_sha256`, `panel_version`, `bcftools_version`, `tool_command`, `prune_in_sha256`, `total_records`, `gt_distribution`, `mean_dp`, `missing_rate`, `per_chrom_record_counts`, `created_at`, `schema_version`.
8. `test_summarize_tier1_qc_handles_empty_vcf` — `_summarize_tier1_qc` on a zero-record VCF returns all counts at 0, no division-by-zero.
9. `test_prepare_coverage_cli_happy_path` — `genomeclaw prs prepare-coverage --sample MPNRGLQ2K` against a small synthetic CRAM lands `tier1.vcf.gz` + `.tbi` + `tier1.qc.json` under `derived/prs_coverage/MPNRGLQ2K/v1/`.
10. `test_prepare_coverage_cli_is_idempotent` — Second invocation against same sample with cached tier1 returns "cache hit" without rebuilding.
11. `test_doctor_collect_prs_coverage_ready_reports_states` — Doctor reports `ready | partial | missing` for a sample's tier1 cache.
12. `test_privacy_prepare_coverage_zero_egress` — Full prepare-coverage flow with default config opens zero outbound sockets (assertion via host service network policy or a mock socket factory).

**Sketch** (Python / pytest, illustrative only):

```python
def test_invD001_tier1_does_not_mutate_cram(tmp_path, synthetic_cram, synthetic_panel):
    """INV-D001: tier1 force-genotyping reads CRAM but never writes back."""
    cram_sha_before = sha256_of(synthetic_cram)
    cram_mtime_before = synthetic_cram.stat().st_mtime

    _force_genotype_tier1(
        cram_path=synthetic_cram,
        sites_tsv=synthetic_panel.sites_tsv,
        alleles_tsv=synthetic_panel.alleles_tsv,
        fasta=synthetic_panel.fasta,
        output_vcf=tmp_path / "tier1.vcf.gz",
    )

    assert sha256_of(synthetic_cram) == cram_sha_before
    assert synthetic_cram.stat().st_mtime == cram_mtime_before


def test_force_genotype_tier1_against_synthetic_cram_produces_expected_gt_distribution(
    tmp_path, synthetic_cram_with_planted_variants, synthetic_panel,
):
    """Force-genotyping recovers planted REF/REF + het + hom-alt + missing within tolerance."""
    _force_genotype_tier1(
        cram_path=synthetic_cram_with_planted_variants.path,
        sites_tsv=synthetic_panel.sites_tsv,
        alleles_tsv=synthetic_panel.alleles_tsv,
        fasta=synthetic_panel.fasta,
        output_vcf=tmp_path / "tier1.vcf.gz",
    )

    counts = _gt_class_counts(tmp_path / "tier1.vcf.gz")
    planted = synthetic_cram_with_planted_variants.expected_gt_counts
    assert abs(counts["0/0"] - planted["0/0"]) <= 2
    assert abs(counts["0/1"] - planted["0/1"]) <= 2
    assert abs(counts["1/1"] - planted["1/1"]) <= 2
    assert abs(counts["./."] - planted["./."]) <= 2
```

After writing the tests, run them and confirm they fail because `coverage_fill.py` doesn't exist yet (12 ImportError tracebacks). Paste the failing output into `work-notes.md` under a `**RED step output**` block.

### Step 1.2 — GREEN: Minimal Implementation

Write the smallest implementation that turns all 12 tests green. Do not pre-empt Phase 2 (Tier 2) or Phase 3 (QC classifier) abstractions.

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` — CREATE.
- `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` — MODIFY (register `prs_pca_sites` target; dispatch to `coverage_fill._materialize_pca_sites`).
- `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` — MODIFY (add `_collect_prs_coverage_ready`).
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pgs.py` (or new file) — MODIFY/CREATE `prepare-coverage` subcommand.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` — MODIFY (extend `PRS_RUNTIME_VERSIONS` with bcftools/plink2 if not already pinned there).
- `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py` — unchanged (use existing `shard_scratch` + `atomic_promote`).

Internal API sketch (illustrative):

```python
# coverage_fill.py
def _materialize_pca_sites(
    panel_root: Path,
    output_root: Path,
    *,
    panel_build: str = "GRCh38",
    threads: int = 4,
    memory_mb: int = 8000,
) -> PcaSiteArtifacts:
    """Run plink2 LD-prune via DooD; emit tabix-indexed sites + alleles TSVs.

    Output layout:
      output_root/<panel_version>/pca_sites.tsv.gz{,.tbi}
      output_root/<panel_version>/pca_alleles.tsv.gz{,.tbi}
      output_root/<panel_version>/pca_sites.provenance.json
    """
    ...


def _force_genotype_tier1(
    cram_path: Path,
    sites_tsv: Path,
    alleles_tsv: Path,
    fasta: Path,
    output_vcf: Path,
    *,
    max_depth: int = 250,
    min_bq: int = 20,
    min_mq: int = 20,
) -> Tier1Artifacts:
    """Run bcftools mpileup → call → norm in the toolkit image.

    Writes to a scratch dir first; atomic_promote to output_vcf on success.
    """
    ...


def _summarize_tier1_qc(tier1_vcf: Path) -> Tier1QcSummary:
    """Walk the VCF once, return GT-class counts, mean DP, per-chrom counts."""
    ...
```

Use the existing `genomeclaw_toolkit._docker` helpers (or equivalent) for the DooD invocation; don't re-implement Docker control.

### Step 1.3 — REFACTOR

With all 12 tests green:

- Tighten `Tier1Artifacts` / `PcaSiteArtifacts` typed return shapes.
- Extract `_run_in_toolkit_image(cmd, *, mounts, work_dir)` helper if duplicated more than twice (rule of three).
- Add comments only where a non-obvious why exists — e.g., note the chromosome-prefix rewrite for the targets file, note why `--threads` doesn't help mpileup compute.
- Run all tests after each refactor step.

---

## Implementation Details

### bcftools pipe invariants

- `mpileup --regions-file sites.tsv.gz`: uses the CRAM index (`.crai`) to seek to target sites. `-T sites.tsv.gz` (targets-file) would scan all reads — slower.
- `mpileup --annotate FORMAT/DP,FORMAT/AD`: needed for the QC summary's mean DP and for downstream confidence assessment.
- `call --multiallelic-caller --keep-alts --constrain alleles --targets-file alleles.tsv.gz`: constrains the Bayesian genotype-likelihood evaluation to the supplied alleles; emits confident REF/REF when pileup supports it, missing (`./.`) when coverage is insufficient.
- `norm --multiallelics -any --fasta-ref`: splits multi-allelic records, re-aligns indels to the reference. Chr22 prove-out realigned 204/6,796 records (3.0%).
- Output: `--output-type z` for bgzipped VCF; tabix index built immediately after via `bcftools index -t`.

### Chromosome-prefix rewrite

The panel pvar uses `1, 2, …, 22, X, Y` (no prefix); the user CRAM + FASTA use `chr1, chr2, …, chr22, chrX, chrY, chrM`. The plink2 prune-in IDs are in the panel naming. When parsing prune-in to TSV, rewrite `^N:` → `chrN\t...`:

```text
prune-in line:  22:10664069:T:A
TSV row:        chr22\t10664069\tT,A
```

### Provenance JSON schema

`pca_sites.provenance.json`:
```json
{
  "panel_root": "/Volumes/.../reference/pgs_catalog_ancestry/v1",
  "panel_version": "v1",
  "panel_pvar_sha256": "...",
  "plink2_version": "2.00a5.10",
  "plink2_image": "ghcr.io/pgscatalog/plink2@sha256:...",
  "prune_params": {"maf": 0.01, "hwe": 1e-6, "geno": 0.05, "window_kb": 1000, "step": 50, "r2": 0.05},
  "prune_in_count": 436123,
  "prune_in_sha256": "...",
  "created_at": "2026-05-18T15:54:21Z",
  "schema_version": "1"
}
```

`tier1.qc.json`:
```json
{
  "sample_id": "MPNRGLQ2K",
  "source_cram_path": "/Volumes/.../raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram",
  "source_cram_sha256": "...",
  "panel_version": "v1",
  "prune_in_sha256": "...",
  "bcftools_version": "1.21",
  "bcftools_command": "bcftools mpileup -R ... | bcftools call ... | bcftools norm ...",
  "total_records": 6796,
  "gt_distribution": {"0/0": 5744, "0/1": 644, "1/1": 347, "./.": 61},
  "mean_dp": 27.98,
  "missing_rate": 0.0090,
  "per_chrom_record_counts": {"chr22": 6796, "...": "..."},
  "created_at": "2026-05-18T15:58:00Z",
  "schema_version": "1"
}
```

### Edge Cases to Handle

- **Empty prune-in for a chromosome**: rare but possible if a chromosome is small (e.g., a synthetic panel chr1 with 10 variants where all are LD-pruned). `_materialize_pca_sites` should still emit a valid (empty) TSV with the header so `tabix` can index it.
- **CRAM missing index**: `_force_genotype_tier1` should fail fast with a typed `MissingIndexError` and a hint to run `samtools index`.
- **Panel `pvar.zst` decompression**: stream via the `zstandard` Python library (already in toolkit deps).
- **Plink2 emits prune-in IDs that don't parse as `chrom:pos:ref:alt`**: emit a `BAD_ID:` line to stderr and abort. (Chr22 prove-out had zero such lines; the format is reliable for the HGDP+1kGP panel.)
- **`atomic_promote` on a same-filesystem `_scratch` → `derived` boundary**: handled by existing `scratch.py` helpers.

### Error Handling

- `MissingPanelError`: `panel_root/<build>_HGDP+1kGP_ALL.pvar.zst` not found. Hint: `genomeclaw refs fetch --source pgs_catalog_ancestry`.
- `MissingCramIndexError`: CRAM has no sibling `.crai`. Hint: `samtools index`.
- `MissingFastaError`: reference FASTA missing or unindexed. Hint: `genomeclaw refs fetch --source grch38`.
- `Plink2ExitError`: non-zero exit; preserve plink2 log in `_scratch/.../plink2.log` and surface path.
- `BcftoolsExitError`: non-zero exit at mpileup, call, or norm stage; preserve per-stage stderr.

### Privacy / Egress Notes

- All commands run in the toolkit image (or DooD sibling). Container network mode is the default; the toolkit image already exposes no inbound ports. No outbound calls are needed once the panel + FASTA are on disk. The privacy-default test confirms this by hooking the host service's network policy.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` | CREATE | Tier 1 orchestration (PCA-site materialize + force-genotype + QC summarize) |
| `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` | MODIFY | Register `prs_pca_sites` target |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | MODIFY | Add `_collect_prs_coverage_ready` informational section |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pgs.py` | MODIFY/CREATE | `prepare-coverage` subcommand |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` | MODIFY | Extend `PRS_RUNTIME_VERSIONS` with bcftools + plink2 pins |
| `packages/toolkit/tests/integration/test_prs_pca_sites_materialize.py` | CREATE | Tests 1–3 |
| `packages/toolkit/tests/integration/test_prs_coverage_tier1.py` | CREATE | Tests 4–8 |
| `packages/toolkit/tests/integration/test_prs_prepare_coverage_cli.py` | CREATE | Tests 9–10 |
| `packages/toolkit/tests/integration/test_doctor_prs_coverage.py` | CREATE | Test 11 |
| `packages/toolkit/tests/privacy/test_prs_prepare_coverage_zero_egress.py` | CREATE | Test 12 |
| `packages/toolkit/tests/conftest.py` | MODIFY | Add fixtures: `synthetic_panel`, `synthetic_cram_with_planted_variants` |

---

## Verification

```bash
# Run this phase's tests
cd packages/toolkit
uv run pytest tests/integration/test_prs_pca_sites_materialize.py \
              tests/integration/test_prs_coverage_tier1.py \
              tests/integration/test_prs_prepare_coverage_cli.py \
              tests/integration/test_doctor_prs_coverage.py \
              tests/privacy/test_prs_prepare_coverage_zero_egress.py -v

# Run all tests (full toolkit suite)
uv run pytest

# Type check
uv run mypy packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py

# Lint
uv run ruff check packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py
```

For real-data spot-check (gated on `needs_prs_runtime`):

```bash
# Build / use the toolkit:prs-phase1 image
export GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:prs-phase1

# Materialize PCA sites against the real panel (one-time per panel release)
genomeclaw refs materialize --target prs_pca_sites --build GRCh38

# Build the Tier 1 cache for the user
genomeclaw prs prepare-coverage --sample MPNRGLQ2K

# Inspect the QC summary
jq . /Volumes/Genome_Work/genomeclaw/derived/prs_coverage/MPNRGLQ2K/v1/tier1.qc.json
```

---

## Completion Criteria

- [ ] All 12 listed test cases pass (RED → GREEN → REFACTOR cycle visible in commits)
- [ ] `mypy` and `ruff` clean on `coverage_fill.py`
- [ ] Each enforced `INV-xxx` (D001, D003, R001, P001) is verified by at least one test in this phase
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures or repo (use synthetic CRAM + synthetic panel only)
- [ ] `work-notes.md` updated with RED output, decisions, and final state
- [ ] Phase status updated in `development-plan.md`
- [ ] (Spot-check, not gated on green) On `MPNRGLQ2K.cram` + HGDP+1kGP v1 panel, real-data run lands a `tier1.qc.json` with mean DP ∈ [20×, 35×], REF/REF rate ∈ [75%, 92%], missing rate < 5%. Record measurements in `work-notes.md` Phase 1 block.

# PRS Input Coverage Fill — Development Plan

**Status**: Draft
**Created**: 2026-05-18
**Branch**: TBD (suggest `feature/prs-input-coverage-fill`)
**Spec**: [spec.md](spec.md)

---

## Summary

Insert a two-tier targeted forced-genotyping cache between the user's CRAM and pgsc_calc so ancestry-calibrated PRS percentiles become computable from Nebula-style variant-only WGS without imputation, without cloud, without GATK, and without violating any GenomeClaw invariant. The bridge is a streaming `bcftools mpileup -T sites | bcftools call -C alleles -T alleles | bcftools norm` pipe — measured on chr22 at **99s wall-clock, 127 MiB peak RAM** for 6,812 PCA-eligible sites, mean DP 27.98×, 84.5% REF/REF.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the user's CRAM and the HGDP+1kGP panel are opened read-only. Tier 1/Tier 2 caches write under `derived/prs_coverage/`, never back to `raw/` or `reference/`. The PCA-site derivative writes under `reference/prs_pca_sites/<panel_version>/` to colocate with the panel it derives from but is reproducible from `pvar.zst` alone.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — bcftools/plink2/pgsc_calc run inside the toolkit image (or sibling DooD containers), never inside the OpenShell sandbox. The agent sees `pgs_scores` table rows only, via the host service's `INV-P002` minimal-sufficient API.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — pgsc_calc Nextflow work dir lives at `_scratch/pgsc_calc_work/<run_id>/`. Tier 1/Tier 2 VCFs are written first to scratch and `atomic_promote`-d to `derived/prs_coverage/`. The Tier 1 VCF for HGDP+1kGP-scale (~400–500k sites) is sub-50 MB and would fit anywhere, but the discipline matters.
- **INV-P001** Privacy Default — zero new network egress. Every step is on-device. The privacy-default test exercises the full `prepare-coverage` + `compute` flow with default config and asserts zero outbound calls.
- **INV-R001** Rebuildability — every artifact records source SHA256, tool versions, parameter JSON. Rebuild path: wipe `derived/prs_coverage/<sample_id>/` → re-run `genomeclaw prs prepare-coverage --sample <id>` → byte-identical output.
- **INV-C001 v1.7** PRS-decline pattern — five named reasons, two of them required on every decline. Wired into a typed exception layer in `coverage_fill.py`, not bolted onto the report template.
- **INV-A003** Agent-Curated Compute Provenance — when the agent triggers a PGS computation, its rationale + two alternatives considered are persisted on the `pgs_scores` row AND as a memory note.

## Proposed New Invariants

**None**. All rules in scope are already in [INVARIANTS.md](../../reference/INVARIANTS.md).

## Current State Analysis

The May 2026 real-data smoke produced an uncalibrated `SUM=9.476` for PGS000018 on sample MPNRGLQ2K — pgsc_calc completed only after `--min_overlap 0.0` bypassed the 75% match-rate gate and `--run_ancestry` was dropped entirely. The `pgs_scores` row produced is unusable per `INV-C001` v1.7. The root cause is upstream of pgsc_calc: the input VCF lacks REF/REF calls at PCA-eligible reference sites.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) | `_build_pgsc_calc_argv` emits `-profile conda`; `_check_ancestry_reference` probes the flat panel layout | Switch to `-profile docker` (proven via smoke); accept the merged Tier 1+Tier 2 VCF as `--input`; drop pre-extraction since pgsc_calc reads `.tar.zst` directly; emit the new `pgs_scores` provenance schema |
| [packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py) | Has `pgs_catalog_ancestry` layout; no per-PGS scoring file source | Add `pgs_scorefile` source that fetches `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/<PGS_ID>/ScoringFiles/Harmonized/<PGS_ID>_hmPOS_GRCh38.txt.gz`, presence-marker keyed by SHA256 |
| [packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py) | No `prs_pca_sites` target | Add `prs_pca_sites` target that runs plink2 LD-prune against the panel and emits tabix-indexed sites + alleles TSVs |
| [packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py) | Probes ancestry-ready, prs-runtime-ready | Add `_collect_prs_coverage_ready(reference_root, sample_id)` informational section that reports Tier 1 cache status + per-PGS Tier 2 cache hits |
| [packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pgs.py) (or similar) | Has `compute` subcommand (or close to it) | Add `prepare-coverage` subcommand; make `compute` cache-aware |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` | Tier 1/Tier 2 orchestration: prune-in → TSV materialization → bcftools pipe → cache lookup → merge |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py` | QC threshold table + decline classifier (the five-named-reasons taxonomy from `INV-C001` v1.7) |
| `packages/toolkit/tests/integration/test_prs_pca_sites_materialize.py` | Tier 1 plink2 LD-prune (chr22-only subset for CI; full autosome gated on `needs_prs_runtime`) |
| `packages/toolkit/tests/integration/test_prs_coverage_tier1.py` | Tier 1 force-genotyping against a synthetic CRAM at ~50 chr22 sites; asserts GT distribution + DP + provenance |
| `packages/toolkit/tests/integration/test_prs_coverage_tier2.py` | Tier 2 cache hit/miss; cache-key invariance under (sample, pgs_id, scorefile_sha256) |
| `packages/toolkit/tests/integration/test_prs_compute_with_coverage_fill.py` | End-to-end: prepare-coverage → compute against a small synthetic PGS scoring file; asserts non-empty `INTERSECT_THINNED`, populated `Z_norm2` |
| `packages/toolkit/tests/integration/test_prs_decline_taxonomy.py` | Each of the five `decline_reason` values can be triggered and persisted |
| `packages/toolkit/tests/privacy/test_prs_compute_zero_egress.py` | Privacy-default — full compute flow asserts zero outbound calls |
| `packages/toolkit/tests/invariants/test_invC001_prs_calibration_gate.py` | `INV-C001` v1.7 enforcement: no `pgs_scores` row with `calibration_status=clean` survives if match rate is below the per-tier threshold |
| `packages/toolkit/tests/invariants/test_invR001_prs_provenance.py` | `INV-R001`: every `pgs_scores` row carries all required provenance columns |

## Solution Design

```text
                  one-time per panel release         per-sample one-time         per-PGS one-time
                  ┌──────────────────────────┐      ┌─────────────────────┐      ┌──────────────────┐
panel.pvar.zst ──▶│ refs materialize         │      │                     │      │                  │
                  │   --target prs_pca_sites │      │                     │      │                  │
                  │ plink2 --indep-pairwise  │      │                     │      │                  │
                  │                          │──┐   │                     │      │                  │
                  │ → pca_alleles.tsv.gz     │  │   │                     │      │                  │
                  │ → pca_sites.tsv.gz       │  │   │                     │      │                  │
                  └──────────────────────────┘  │   │                     │      │                  │
                                                ▼   ▼                     │      │                  │
sample.cram ──────────────────────────────────▶ ┌─────────────────────┐   │      │                  │
                                                │ prs prepare-coverage│   │      │                  │
                                                │ bcftools mpileup    │   │      │                  │
                                                │   --regions-file    │   │      │                  │
                                                │ │ bcftools call     │   │      │                  │
                                                │   --constrain alleles│  │      │                  │
                                                │ │ bcftools norm     │   │      │                  │
                                                │ → tier1.vcf.gz      │───┼─────▶│ prs compute      │
                                                │ → tier1.qc.json     │   │      │ (cache hit:      │
                                                └─────────────────────┘   │      │  concat tier1    │
                                                                          │      │  + tier2)        │
PGS_xxx_hmPOS_GRCh38.txt.gz ──▶ extract sites ──▶ ┌──────────────────────┴┐     │ │ pgsc_calc       │
                                                  │ tier2 force-genotype │     │   -profile docker │
                                                  │ (same bcftools pipe)  │     │   --run_ancestry │
                                                  │ → tier2.vcf.gz       │─────▶│ │ FRAPOSA PCA     │
                                                  └──────────────────────┘      │ │ Z_norm2         │
                                                                                 │ → pgs_scores row │
                                                                                 │   (INV-A003 prov)│
                                                                                 └──────────────────┘
                                                                                          │
                                                                       ┌──────────────────┴──────────────────┐
                                                                       ▼                                     ▼
                                                              QC gate: match-rate                   decline?
                                                              vs. variant-count tier               5 named reasons
                                                              (INV-C001 v1.7)                      (INV-C001 v1.7)
```

### Key Design Decisions

1. **bcftools, not GATK**. `bcftools call -C alleles -T alleles.tsv` is the textbook primitive for forced genotyping at known alleles. It skips local reassembly (which HaplotypeCaller does and is wasted work when the alleles are already known), avoids the JVM dependency, and produced a clean 84.5% REF/REF distribution at 127 MiB peak RAM in the chr22 prove-out. GATK GVCF reconstruction is rejected.
2. **Two-tier cache, not one-tier**. The PCA-eligible site set is fixed by the reference panel and doesn't depend on the agent's PGS choice. Building it once per sample (Tier 1) and incrementally caching per-PGS Tier 2 results means subsequent questions hit cache for the PCA layer and amortize the Tier 2 cost across (variant count) × (re-questions).
3. **Per-sample cache, keyed by panel version**. The Tier 1 cache directory is `derived/prs_coverage/<sample_id>/<panel_version>/`. If the panel updates (e.g., HGDP+1kGP v2 ships), Tier 1 rebuilds cleanly without invalidating per-sample raw CRAM provenance.
4. **Per-PGS cache, keyed by scoring-file SHA256**. PGS Catalog scoring files are versioned by file (no monotonic semver). The cache key includes the scoring-file SHA256 so a silent upstream re-harmonization doesn't return stale Tier 2 output.
5. **`-profile docker`, not `-profile conda`**. The May 2026 smoke proved `-profile conda` fails on linux/arm64 because plink2 2.0a5.10 is unavailable on conda-forge for aarch64. `-profile docker` works via DooD against the pre-pulled pgsc_calc images. (This switches the `_build_pgsc_calc_argv` default; tests are added under `test_pgsc_calc_wrapper.py`.)
6. **Keep the pre-extraction post-fetch hook** (corrected from the initial draft of this plan). Investigation during Phase 4 confirmed pgsc_calc's `--run_ancestry` requires a *directory* containing the panel files (`GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}`), not the `.tar.zst` tarball. The existing hook in `fetch.py:_extract_pgs_catalog_ancestry_bundle` streams the tarball through `zstandard` + `tarfile` into the extracted layout and deletes the bundle; this is correct and stays. The `presence_relpath="GRCh38_HGDP+1kGP_ALL.pgen"` marker survives the bundle deletion for skip-detection. The initial draft's "pgsc_calc reads .tar.zst directly" claim was based on a misread of the 2026-05-17 smoke logs and has been retracted.
7. **Variant-count-tier QC table** (per agent recommendation, Section 5.1):

| PGS variant count | Decline if match rate < | Warn if match rate in | Clean if ≥ |
|---|---|---|---|
| ≤10k | 75% | 75–90% | 90% |
| 10k–500k | 60% | 60–80% | 80% |
| >500k | 40% | 40–75% | 75% (pgsc_calc default) |

8. **Decline-reason enum is structural, not advisory**. `decline_reason` is a typed column on `pgs_scores`, not free text. The agent-facing report formatter uses the enum to render the explanation, so the wording stays consistent across questions and the agent's two-named-reasons output per `INV-A003` always picks from the same set.
9. **plink2 via DooD against `ghcr.io/pgscatalog/plink2:2.00a5.10`**. The chr22 prove-out used DooD because linux/arm64 conda-forge doesn't carry plink2 2.0a5.10. We don't bake plink2 into the toolkit image because Tier 1 calls plink2 once per panel release (one-time per sample), and the DooD path is already exercised for `-profile docker`.

### Schema / Provenance Impact

- New table `pgs_scores` (or extension of existing). Columns enumerated in `spec.md` AC7. Required for every row: `sample_id`, `pgs_id`, `scoring_file_sha256`, `panel_version`, `bcftools_version`, `plink2_version`, `pgsc_calc_revision`, `fraposa_version`, `match_rate`, `pca_overlap_count`, `calibration_status`, `decline_reason`, `created_at`, `schema_version`.
- Schema version bump: TBD (depends on current `derived/duckdb/` schema state; check before Phase 1).
- Provenance columns added: see above. Tool versions are read from the toolkit image at run-time (the image itself records pinned versions in `_versions.py`).
- Rebuild procedure: `rm -rf derived/prs_coverage/<sample_id>/ && genomeclaw prs prepare-coverage --sample <id> && genomeclaw prs compute --pgs-id <id> --sample <id>`.

### Privacy & Egress Impact

- **New network egress points**: none. `refs fetch --source pgs_scorefile` adds a named fetch destination for PGS Catalog scoring files (already a deliberate egress via the existing `refs fetch` machinery). No runtime egress; the compute flow operates entirely on pre-staged artifacts.
- **New secret-handling surfaces**: none.
- **Redaction added**: when the agent retrieves `pgs_scores` rows via the host HTTP service, only the schema columns are exposed — never raw CRAM paths, never per-variant `FORMAT/DP`, never per-PC vectors beyond what the report needs.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Tier 1 PCA-site materialize + per-sample force-genotype + QC JSON | `refs materialize --target prs_pca_sites` rebuild determinism; `prs prepare-coverage` produces tier1.vcf.gz with expected GT/DP distribution; `INV-R001` provenance on tier1.qc.json | ~12 |
| 2 | Tier 2 per-PGS force-genotype + merge + cache-key invariance | Cache hit on repeated invocation; cache miss on changed scoring-file SHA256; merged VCF passes pgsc_calc `INTERSECT_THINNED` non-empty | ~10 |
| 3 | QC threshold table + decline taxonomy + `INV-C001 v1.7` typed exceptions | All five decline reasons can be triggered; warning vs. clean vs. decline is deterministic per variant-count tier; agent-rationale persistence per `INV-A003` | ~14 |
| 4 | `_build_pgsc_calc_argv` switch to `-profile docker`; drop pre-extraction post-fetch hook; doctor coverage section; CLI surface polish | Integration regression: end-to-end PGS000018 + PGS003725 produce ancestry-calibrated `Z_norm2`; doctor reports cache state | ~8 |
| 5 | Real-data smoke: re-run PGS000018 + PGS003725 against MPNRGLQ2K with full Tier 1+2 cache; measure full-autosome wall-clock (Q1 resolution); record measured GT distribution; promote SLA estimate from "hopeful 15–25 min/Q" to "measured X min/Q" | Smoke gate per [docs/plans/CLAUDE.md](../../CLAUDE.md) "Real-data smoke as a phase-completion gate" | ~3 |

## Phase 1: Tier 1 PCA-site Materialize + Per-Sample Force-Genotype

**Goal**: One command — `genomeclaw refs materialize --target prs_pca_sites` followed by `genomeclaw prs prepare-coverage --sample <id>` — produces a `tier1.vcf.gz` with one record per LD-pruned PCA-eligible site, with healthy GT/DP/missing distribution and full `INV-R001` provenance.

**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

1. `coverage_fill.py:_materialize_pca_sites(panel_root, output_root, threads, memory_mb)` — runs plink2 LD-prune via DooD, parses prune-in IDs, emits bgzip+tabix sites/alleles TSVs.
2. `coverage_fill.py:_force_genotype_tier1(cram_path, sites_tsv, alleles_tsv, fasta, output_vcf)` — runs the bcftools pipe inside the toolkit image; writes `tier1.vcf.gz` + `tier1.vcf.gz.tbi`.
3. `coverage_fill.py:_summarize_tier1_qc(tier1_vcf) → dict` — emits `tier1.qc.json` with mean DP, REF/REF rate, het rate, hom-alt rate, missing rate, indel rate, per-chromosome record counts.
4. `materialize.py` plumbing: register `prs_pca_sites` as a known materialize target.
5. CLI: `genomeclaw prs prepare-coverage --sample <id>` and (optional) `genomeclaw refs materialize --target prs_pca_sites`.
6. Tests for each (see Phase 1 doc).

### Invariants Enforced Here

- **INV-R001**: every emitted file carries source SHA256 + tool versions in its sibling provenance JSON; rebuild produces byte-identical output.
- **INV-D001**: the user CRAM mtime + content hash are unchanged after a Tier 1 run.
- **INV-D003**: tier1.vcf.gz is written to `_scratch/` first and `atomic_promote`-d to `derived/prs_coverage/`.

### Success Criteria

- [ ] All Phase 1 tests pass (RED → GREEN → REFACTOR visible in commits)
- [ ] `mypy` / linters clean on `coverage_fill.py`
- [ ] At least one test per enforced `INV-xxx`
- [ ] On `MPNRGLQ2K.cram` + HGDP+1kGP v1 panel, Tier 1 completes within the measured per-sample budget recorded in Phase 1 GREEN; tier1.qc.json mean DP within [20×, 35×]; REF/REF rate within [75%, 92%]; missing rate <5%.

## Phase 2: Tier 2 Per-PGS Force-Genotype + Cache + Merge

**Goal**: `genomeclaw prs compute --pgs-id <id> --sample <id>` on cache miss runs Tier 2 against the scoring-file site list, merges with Tier 1, hands to pgsc_calc; on cache hit, skips bcftools entirely.

**Detailed Plan**: phases/phase-2.md (TBD; created when Phase 1 lands)

### Deliverables

1. `coverage_fill.py:_force_genotype_tier2(cram_path, pgs_scorefile, fasta, output_vcf)` — same pipe, sites derived from scoring file.
2. `coverage_fill.py:_merge_tier1_tier2(tier1, tier2) → merged.vcf.gz` — bcftools concat + sort + tabix.
3. `coverage_fill.py:_cache_key(sample_id, pgs_id, scorefile_path, panel_version) → Path` — deterministic cache path.
4. Cache hit/miss detection wired into `prs compute`.
5. New `fetch.py` source `pgs_scorefile` with SHA256-keyed presence marker.

### Invariants Enforced Here

- **INV-R001**: cache key includes scoring-file SHA256; same key → same byte output.
- **INV-D003**: tier2 work happens in scratch; final tier2.vcf.gz `atomic_promote`-d.
- **INV-P001**: no network calls during `prs compute` (the `refs fetch --source pgs_scorefile` is the only egress path and is a deliberate, separate step).

## Phase 3: QC Threshold Table + Decline Taxonomy + `INV-C001 v1.7`

**Goal**: A `pgs_scores` row is emitted with `calibration_status` ∈ {`clean`, `warning`, `decline`} and (if decline) a `decline_reason` from the five-named-reasons enum. The decline path is exercised by tests for each reason.

**Detailed Plan**: phases/phase-3.md (TBD)

### Deliverables

1. `_pgs_qc.py:classify_calibration(match_rate, pgs_variant_count, pca_overlap_count, mahalanobis_distance, gwas_ancestry, user_super_pop, pgs_tier) → CalibrationDecision`.
2. Typed exceptions: `PRSDeclineError(reason: DeclineReason, two_named_reasons: tuple[str, str], ...)`.
3. Agent-rationale persistence: when the agent calls `prs compute` with `--rationale` / `--alternative-1` / `--alternative-2`, those land on the `pgs_scores` row per `INV-A003`.
4. Memory-note emission on decline per `INV-A003`.

### Invariants Enforced Here

- **INV-C001 v1.7**: no clean row with low match rate; no missing decline reason on declined row.
- **INV-A003**: agent rationale present when (and only when) the trigger is agent-attributed; decline-note schema matches `INV-A001`.

## Phase 4: `-profile docker` switch, post-fetch hook cleanup, doctor section, CLI polish

**Goal**: The smoke-proven runtime path becomes the default. The pre-extraction post-fetch hook for `pgs_catalog_ancestry` is removed (pgsc_calc reads the `.tar.zst` directly). The doctor command reports Tier 1 + Tier 2 cache state. CLI surface is consistent with the existing `pgs.py` style.

**Detailed Plan**: phases/phase-4.md (TBD)

### Deliverables

1. `_build_pgsc_calc_argv` emits `-profile docker` (test added under existing `test_pgsc_calc_wrapper.py`).
2. ~~`fetch.py:_extract_pgs_catalog_ancestry_bundle` post-fetch hook removed~~ — **dropped from Phase 4 scope.** Investigation showed pgsc_calc's `--run_ancestry` requires a directory of extracted panel files; the existing hook is correct. See Solution Design Decision 6.
3. `doctor.py:_collect_prs_coverage_ready` informational section.
4. CLI cleanup: `genomeclaw prs prepare-coverage`, `genomeclaw prs compute`, `genomeclaw prs status`.

### Invariants Enforced Here

- **INV-R001**: post-fetch-hook removal does not break re-fetch idempotency (presence marker still keys to a deterministic file).

## Phase 5: Real-data smoke gate

**Goal**: Resolve Open Questions Q1 (Tier 1 full-autosome wall-clock) and Q3 (per-chromosome GT distribution) by running the full pipeline against `MPNRGLQ2K.cram`. Promote the SLA from "hopeful 15–25 min/Q" to a measured number the agent surface can rely on.

**Detailed Plan**: phases/phase-5.md (TBD)

### Deliverables

1. Measured `tier1.qc.json` recorded in `work-notes.md`.
2. Real PGS000018 and PGS003725 results with `Z_norm2` percentile + Mahalanobis distance + decline=null.
3. Updated SLA in `spec.md` Q1.
4. `docs/reference/prs-pipeline.md` (or equivalent) writes up the architecture for future contributors.

### Invariants Enforced Here

- **Real-data smoke gate** per [docs/plans/CLAUDE.md](../../CLAUDE.md): synthetic fixtures alone are insufficient for scale-sensitive surfaces. Phase 5 closes the synthetic→real gap.

---

## Testing Strategy

### Unit Tests
- `tests/unit/test_pgs_qc_classifier.py` — `_pgs_qc.classify_calibration` truth table across variant-count tiers + all five decline reasons.
- `tests/unit/test_cache_key_invariance.py` — `_cache_key` is byte-stable under (sample, pgs_id, scorefile_sha256, panel_version).

### Integration Tests
- `tests/integration/test_prs_pca_sites_materialize.py` — small synthetic panel (chr22 only); plink2 LD-prune produces deterministic prune-in.
- `tests/integration/test_prs_coverage_tier1.py` — synthetic CRAM + synthetic panel; tier1.vcf.gz GT distribution within expected bounds.
- `tests/integration/test_prs_coverage_tier2.py` — Tier 2 cache hit/miss; cache-key invariance.
- `tests/integration/test_prs_compute_with_coverage_fill.py` — end-to-end synthetic PGS; pgsc_calc completes with non-empty `INTERSECT_THINNED`.
- `tests/integration/test_prs_decline_taxonomy.py` — each of five decline reasons triggerable.

### Provenance Tests
- `tests/provenance/test_pgs_scores_columns.py` — every emitted `pgs_scores` row has all required columns; tool-version columns are non-null and match `_versions.PRS_RUNTIME_VERSIONS`.

### Determinism Tests
- `tests/determinism/test_tier1_byte_equivalent.py` — running `prs prepare-coverage` twice on the same CRAM with the same panel version produces byte-equivalent tier1.vcf.gz (modulo bgzip block size variance — assert on uncompressed content).

### Privacy-Default Tests
- `tests/privacy/test_prs_compute_zero_egress.py` — full compute flow with default config; assert zero outbound calls via the host service network policy.

### Evidence-Binding Tests
- `tests/evidence/test_pgs_scores_citation_present.py` — every clean PGS finding carries `pgs_publication_doi`, `pmid`, and `pgs_catalog_tier` columns.

### Report Rendering Tests
- `tests/reports/test_pgs_finding_renders_calibration.py` — clean / warning / decline render distinct user-facing copy with the ACMG ancestry-portability caveat.

### Invariant Tests
- `tests/invariants/test_invC001_prs_calibration_gate.py` — `INV-C001` v1.7 enforcement.
- `tests/invariants/test_invR001_prs_provenance.py` — `INV-R001` cross-cutting check on `pgs_scores`.
- `tests/invariants/test_invA003_agent_rationale_persistence.py` — `INV-A003` rationale + two-alternatives on agent-triggered rows.

### Perf Tests
- `tests/perf/test_tier1_chr22_under_budget.py` — chr22 Tier 1 force-genotype on synthetic CRAM completes within 3× the measured 99s baseline (i.e., regression guard set generously).

---

## Documentation Updates

After implementation:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — only if a new invariant is promoted (none proposed today).
- [ ] `docs/reference/prs-pipeline.md` (new or update) — architecture diagram + cache semantics + decline taxonomy.
- [ ] [docs/reference/grand-plan.md](../../reference/grand-plan.md) — Theme G PRS surface update.
- [ ] [docs/plans/active/prs-bootstrap-meta.md](../prs-bootstrap-meta.md) — link this plan as the Stage 5 follow-up.
- [ ] User-facing example: a sample report excerpt for a clean clean PGS finding, a warning case, a decline case.
- [ ] CLI: `genomeclaw prs --help` and per-subcommand help text.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1a | Complete | 2026-05-18 | 2026-05-18 | Tier 1 primitives + orchestrator (11 tests GREEN: parse_prune_in, summarize_qc, cache_path, force_genotype_tier1, prepare_coverage_tier1, MissingCramIndexError) |
| Phase 1b | Complete | 2026-05-18 | 2026-05-18 | `_materialize_pca_sites` (plink2 via DooD), doctor `prs_coverage_ready`, CLI `prs-prepare-coverage`, privacy zero-egress, real-bcftools smoke (10 new tests; 1 `needs_bio` skip) |
| Phase 2  | Complete | 2026-05-18 | 2026-05-18 | Tier 2 force-genotype + scorefile parsing + cache (sha8-keyed) + `_merge_tier1_tier2` + `prepare_coverage_tier2` (9 new tests) |
| Phase 3a | Complete | 2026-05-18 | 2026-05-18 | QC classifier (`_pgs_qc.py`) + 5-named-reasons enum + `PRSDeclineError` typed exception (14 tests). Variant-overlap axis only; ancestry-driven branches deferred to 3b. |
| Phase 3b1 | Complete | 2026-05-18 | 2026-05-18 | Extend `PgsRow` with `calibration_status` + `decline_reason` optional fields + `apply_calibration_decision` helper (6 tests) |
| Phase 3b2 | Complete | 2026-05-18 | 2026-05-18 | Wire classifier into `compute_prs_with_coverage_fill` with explicit `match_rate` + `pgs_variant_count` params; raises `PRSDeclineError` on DECLINE (4 tests) |
| Phase 3b3a | Complete | 2026-05-18 | 2026-05-18 | `_pgsc_calc_match.py` parser (verified against real 2026-05-17 smoke log) + orchestrator auto-discovery (10 tests) |
| Phase 3b3b | Complete | 2026-05-18 | 2026-05-18 | Migrated `pgs_scores` DDL (nullable `calibration_status` + `decline_reason`) + extended `_stamp_pgs_row` INSERT; CLI `prs-compute` catches `PRSDeclineError` → typed decline payload + exit 0 (8 tests) |
| Phase 4  | Complete | 2026-05-18 | 2026-05-18 | `-profile docker` switch; `compute_prs_with_coverage_fill` orchestrator; `pipeline prs-compute` CLI (6 new + 1 flipped test). 4b retracted: pgsc_calc needs an extracted directory, not the .tar.zst. |
| Phase 5  | In Progress | 2026-05-18 | | Driver + 10 verification gates landed (auto-skip cleanly on bare host); awaits user invocation of `bin/genomeclaw-prs-smoke` against real CRAM (~50–60 min). [phases/phase-5.md](phases/phase-5.md) |
| Phase 2 | Pending | | | Tier 2 + cache + merge |
| Phase 3 | Pending | | | QC + decline taxonomy + INV-C001/INV-A003 wiring |
| Phase 4 | Pending | | | `-profile docker` switch, post-fetch hook cleanup, doctor + CLI |
| Phase 5 | Pending | | | Real-data smoke; SLA resolution |

---

## Open Risks & Follow-ups

- **plink2 packaging**. Linux/arm64 conda-forge doesn't carry plink2 2.00a5.10; we depend on `ghcr.io/pgscatalog/plink2:2.00a5.10` via DooD. If pgsc_calc updates its plink2 version, the materialize step needs version-aware pinning. Track via `_versions.PRS_RUNTIME_VERSIONS`.
- **Tier 1 SLA on full autosomes**. Q1 in spec — extrapolated to **50–60 min on the 2-CPU Colima**, **12–15 min if Colima bumped to 8 CPUs**. The user's grand-plan host is 16 GB / ~8 cores, so bumping Colima is feasible if the SLA matters. Decision deferred to Phase 5 where the number is measured.
- **Indel handling at Tier 2**. Restrict initial Tier 2 site lists to SNPs; revisit if a PGS catalog ID emerges that is heavily indel-dependent. (Most PGS scores are SNP-only; indel-heavy is rare.)
- **pgsc_calc v3 trajectory**. v3-alpha (Dec 2025) restructures the backend for native WGS ingestion but does not yet ship WGS support. Track via the GitHub releases feed; if v3 ships native CRAM/VCF ingestion before Phase 5, consider whether to skip this plan's Tier 2 caching and use v3 directly.
- **caPRS for non-EUR users**. Not in MVP scope; PGS003725 is the current CAD default. If/when caPRS gets a PGS Catalog ID, add as the default for users whose `Z_norm2` super-pop call is non-EUR.
- **PGS Catalog scoring-file mirror refresh cadence**. Plan a quarterly refresh of the local mirror; the scoring files have versioned filenames but no monotonic semver, so the cache key includes SHA256 (not version string).

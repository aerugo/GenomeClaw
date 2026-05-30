# Development Plan: Force-Genotype Callable-Region Mask

**Status**: Drafted — not yet approved  
**Created**: 2026-05-25  
**Parent meta-plan**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md)  
**Spec**: [spec.md](./spec.md)

| Phase | Title | Status |
|---|---|---|
| 1 | GIAB reference data registration | Not started |
| 2 | Per-site genotype-source annotation | Not started |
| 3 | PGS overlap correction | Not started |
| 4 | Real-data smoke | Not started |

---

## Critical Invariants to Respect

- **INV-D001** — The CRAM and Nebula VCF are opened read-only throughout. The GIAB BED is
  fetched under `data/reference/`; force-genotyping outputs and the sidecar TSV land under
  `data/derived/`. No source file is mutated.

- **INV-R001** — Every emitted sidecar row records its source identity. The `tier1.qc.json`
  and `tier2.qc.json` blobs gain two new fields: `giab_bed_release` (the release string used,
  e.g. `"v4.2.1-hg001"`) and `min_callable_depth` (the threshold integer, e.g. `10`). The
  sidecar itself carries a provenance header block (commented TSV header lines with tool
  version, bed release, threshold, timestamp). A rebuild command is specified at the end of
  this document.

- **INV-E001** — The `genotype_source` annotation is part of the evidence chain for PGS
  calls. The `pgs_scores.params_json` column is extended to reference the sidecar path so an
  audit can trace from a PGS score back to which sites were included or excluded.

- **INV-P001** — The GIAB BED fetch is a user-initiated `refs fetch` invocation. No new
  runtime egress is introduced. Force-genotyping and overlap correction run entirely locally.

- **INV-C001 v1.7** — The `uncallable_sites_excluded` count is an input to the
  `prs-calibration-phase3b` classifier's decline decision. This plan exposes the count; the
  decline logic is out of scope here.

---

## Proposed New Invariants

### INV-C002 — Uncallable Sites Must Not Inflate PGS Denominator

**Rule**: A site classified as `genotype_source = uncallable` must be excluded from both the
`matched` count and the `unmatched` count in any PGS match-rate or overlap computation. It
must never appear in the denominator of a reported match-rate.

**Requirements**:
- The `parse_match_stats` caller (in `pgs.py` or a new wrapper function in
  `_pgsc_calc_match.py`) intersects the pgsc_calc log with the `forced_genotype_provenance.tsv.zst`
  sidecar before returning `MatchStats`.
- `uncallable` sites are subtracted from both `matched` and `unmatched` counts after the
  pgsc_calc log walk, not before (the log reflects pgsc_calc's view of the world; the sidecar
  correction is applied on top).
- The exclusion count is persisted to `pgs_scores.uncallable_sites_excluded` (new column,
  nullable integer — null means "sidecar was not available for this run", distinct from 0
  which means "sidecar was available and zero sites were uncallable").
- A test named `test_invC002_uncallable_excluded_from_pgs_denominator` verifies this
  property on a synthetic fixture.

**Where it applies**: `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py`,
`packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py`, `packages/toolkit/src/genomeclaw_toolkit/prep/store.py`.

**How to verify**: The dedicated test above. Also, any integration test that runs
`compute_pgs` with a sidecar containing `uncallable` entries must assert that the returned
`PgsRow` shows a lower total site count than the raw pgsc_calc log.

This invariant will be promoted to `docs/reference/INVARIANTS.md` after Phase 3 tests are
merged and green.

---

## Current State Analysis

### What exists

- `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` — Tier-1 and Tier-2
  force-genotyping via `_BCFTOOLS_PIPE_TEMPLATE` (line 378–396). Runs `bcftools mpileup
  --min-BQ 20 --min-MQ 20 --regions-file ... | bcftools call --constrain alleles ...
  | bcftools norm`. Produces a bgzipped VCF + `.tbi` sidecar. Validates non-zero record count
  (`_count_vcf_records`, line 399). Writes `tier1.qc.json` with CRAM SHA256, bcftools
  version, tool command, GT distribution, mean DP, schema version. `SCHEMA_VERSION = "2"`
  (line 68).

- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py` — `parse_match_stats`
  walks the pgsc_calc `*_log.csv.gz` and counts `matched` / `unmatched` rows per accession.
  Returns `MatchStats(pgs_accession, matched, unmatched)`. No sidecar integration.

- `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` — `compute_pgs` orchestrates
  pgsc_calc. `PgsRow` dataclass carries domain + provenance fields. No `uncallable_sites_excluded`
  field.

- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — `pgs_scores` DDL (line 205–233).
  No `uncallable_sites_excluded` column.

- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — `_LAYOUTS` dict (line 550+)
  registers `clinvar`, `grch38`, `gnomad-exomes`, `dbsnp`, `vep_cache`, `alphamissense`,
  `loftee`, `pgs_catalog_ancestry`. No `giab_high_confidence` entry.

### What is missing

1. A `giab_high_confidence` entry in `_LAYOUTS` in `fetch.py`.
2. A per-site `genotype_source` classification step in `coverage_fill.py` that intersects the
   force-genotype output with the GIAB BED and with the pileup depth.
3. A `forced_genotype_provenance.tsv.zst` sidecar emitted alongside the forced VCF.
4. An `uncallable`-aware adjustment in `_pgsc_calc_match.py` / `pgs.py`.
5. A new `uncallable_sites_excluded` column in `pgs_scores`.
6. A schema version bump in `coverage_fill.py` (`SCHEMA_VERSION` from `"2"` to `"3"`).

---

## Solution Design

### Stage diagram

```
[GIAB BED on disk]  [Nebula VCF]  [CRAM]
        |                |           |
        |         [coverage_fill.py] |
        |           Tier-1/Tier-2    |
        |         force-genotype     |
        |                |           |
        |         [forced.vcf.gz]    |
        |                            |
        +---[genotype_source         |
             classifier]             |
                  |         [mpileup DP per site]
                  |                  |
        [forced_genotype_provenance.tsv.zst]
                  |
                  v
        [_pgsc_calc_match.py]
         parse_match_stats +
         uncallable filter
                  |
        [MatchStats with uncallable_sites_excluded]
                  |
        [pgs_scores row]
         uncallable_sites_excluded col
```

### Genotype-source classification logic

After the `bcftools mpileup | call | norm` pipe completes and the forced VCF is staged, a
classification pass runs over the forced VCF rows:

1. For each site in the forced VCF:
   a. Check whether the site's (chrom, pos) is present in the source Nebula VCF's position
      set. If yes: `genotype_source = nebula_called`.
   b. Otherwise: query the pileup depth at this site (extracted from the `FORMAT/DP` field in
      the forced VCF output, which the `--annotate FORMAT/DP` flag already emits).
      - If `DP < 10`: `genotype_source = uncallable`.
      - Else if the site intersects the GIAB high-confidence BED: `genotype_source = force_genotyped_high_conf`.
      - Else: `genotype_source = force_genotyped_low_conf`.

2. The GIAB BED intersection is a sorted-coordinate query (read the BED into an interval set
   once at classification time; query per site in O(log n) using `bisect`). No external tool
   call is required for the intersection — Python's `bisect` module is sufficient at 1–2M
   sites.

3. The sidecar TSV has columns: `chrom`, `pos`, `ref`, `alt`, `genotype_source`. Written as a
   streaming generator → `zstandard.ZstdCompressor` writer to avoid materialising the full
   site list in memory (anti-pattern: `[{**row} for row in ...]` over millions of records).

### Sidecar provenance header

The first five lines of the sidecar (before the column header) are TSV comment lines prefixed
with `#`:

```
# genomeclaw_forced_genotype_provenance
# schema_version=3
# giab_bed_release=<release string from tier1.qc.json>
# min_callable_depth=10
# created_at=<ISO 8601 UTC timestamp>
```

### PGS overlap correction

`_pgsc_calc_match.py` gains a new function `apply_uncallable_filter(stats, sidecar_path,
pgs_accession)` that:
1. Loads the sidecar TSV (streaming, not materialised).
2. Builds a set of `(chrom, pos)` positions where `genotype_source = uncallable`.
3. Re-walks the pgsc_calc log CSV for the given accession; skips rows whose `(chrom, pos)`
   appears in the uncallable set.
4. Returns a new `MatchStats` with adjusted `matched`, `unmatched`, and an additional
   `uncallable_excluded` count.

`MatchStats` gains an `uncallable_excluded: int = 0` field (default 0 for backwards
compatibility with callers that do not supply a sidecar).

### Schema / Provenance Impact

**`coverage_fill.py`**:
- `SCHEMA_VERSION` bumped from `"2"` to `"3"`.
- `tier1.qc.json` gains two new fields: `giab_bed_release` (str) and `min_callable_depth`
  (int).
- A new function `_classify_genotype_sources(...)` emits the sidecar TSV after force-
  genotyping completes.
- `prepare_coverage_tier1` (and the equivalent Tier-2 function) extended: cache-hit check
  requires BOTH the VCF and the sidecar to be present; if either is missing, a rebuild is
  triggered.

**`_pgsc_calc_match.py`**:
- `MatchStats` gains `uncallable_excluded: int = 0`.
- New public function `apply_uncallable_filter(stats, sidecar_path, pgs_accession) ->
  MatchStats`.

**`pgs.py`**:
- `PgsRow` gains `uncallable_sites_excluded: int | None = None`.
- `compute_pgs` extended to accept an optional `sidecar_path: Path | None` argument; when
  provided it calls `apply_uncallable_filter` after `parse_match_stats`.

**`store.py`**:
- `pgs_scores` DDL gains `uncallable_sites_excluded INTEGER` (nullable).
- `_PGS_SCORES_DDL` updated; `SCHEMA_VERSION` in `schemas/__init__.py` bumped.

**`fetch.py`**:
- `_LAYOUTS` gains `"giab_high_confidence"` entry (see Phase 1 plan for the exact FTP paths
  and MD5 mode).

### Idempotency story

- **GIAB BED fetch**: guarded by `VersionAlreadyExists` (existing `fetch.py` convention). A
  second `refs fetch --source giab_high_confidence --release v4.2.1-hg001` raises
  `VersionAlreadyExists` without re-downloading.
- **Force-genotype + sidecar**: the cache-hit check in `prepare_coverage_tier1` is extended
  to require both VCF and sidecar present AND `schema_version == "3"`. An existing v2 cache
  (VCF present, sidecar absent, or `schema_version == "2"`) is treated as a cache miss and
  rebuilt. This is a one-time cost.
- **PGS overlap correction**: `compute_pgs` is idempotent — rerunning with the same inputs
  produces the same `PgsRow`. The sidecar path is passed as a parameter and is deterministic
  given the run-id.

### Rebuild command

To rebuild a Tier-1 coverage cache with the new sidecar from scratch:

```bash
# Remove the stale v2 cache (the schema-version check will not do this automatically).
rm -rf data/derived/prs_coverage/<sample_id>/<panel_version>/

# Re-run coverage fill — the absence of the cache triggers a full rebuild.
genomeclaw prs coverage-fill \
  --cram data/raw/<sample>.cram \
  --vcf data/raw/<sample>.vcf.gz \
  --panel-version <panel_version> \
  --giab-bed data/reference/giab_high_confidence/v4.2.1-hg001/HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz \
  --derived-root data/derived/
```

The resulting `data/derived/prs_coverage/<sample_id>/<panel_version>/tier1.vcf.gz` and
`forced_genotype_provenance.tsv.zst` together constitute the rebuildable derived artifact for
Tier-1 coverage.

---

## Phase Overview

### Phase 1 — GIAB reference data registration (~1 day)

Register `giab_high_confidence` in `_LAYOUTS` in `fetch.py`. Pin to the NA12878/HG001 v4.2.1
BED at NCBI FTP. Add MD5 verification (NCBI publishes per-file `.md5` sidecars for GIAB
release files). Add a `refs list` entry. Tests: unit test for `_LAYOUTS["giab_high_confidence"]`
presence, `fetch()` mock-HTTP test verifying download + MD5 check + `VersionAlreadyExists`
idempotency.

Invariants verified in this phase: **INV-D001**, **INV-R001**, **INV-P001**.

### Phase 2 — Per-site genotype-source annotation (~2.5 days)

Add the `_classify_genotype_sources` function in `coverage_fill.py`. Extend `prepare_coverage_tier1`
(and Tier-2 equivalent) to emit the sidecar. Bump `SCHEMA_VERSION` to `"3"`. Extend cache-hit
check to require sidecar presence. Update `tier1.qc.json` schema with `giab_bed_release` and
`min_callable_depth`. Tests: unit tests for each `genotype_source` value, cache-miss
behaviour when sidecar is absent, sidecar atomicity, provenance header content.

Invariants verified in this phase: **INV-D001**, **INV-R001**, **INV-E001**.

### Phase 3 — PGS overlap correction (~1.5 days)

Extend `MatchStats` with `uncallable_excluded`. Add `apply_uncallable_filter`. Extend
`compute_pgs` with optional `sidecar_path`. Add `uncallable_sites_excluded` to `PgsRow` and
`pgs_scores` DDL. Bump schema version. Tests: INV-C002 gate test (synthetic uncallable sites
disappear from match-rate denominator), zero-sidecar path (existing behaviour unchanged),
persistence test (`uncallable_sites_excluded` lands in DuckDB).

Invariants verified in this phase: **INV-E001**, **INV-C001**, **INV-C002** (proposed).

### Phase 4 — Real-data smoke (~1 day)

Rerun PGS000018 CAD on the project owner's genome. Compare match rate, raw score, and
percentile to the pre-mask baseline. Document findings in `work-notes.md`. Expected: sidecar
present, `uncallable_sites_excluded` count small (< 5% of scorefile size for a 30x CRAM),
match rate within ±5% of baseline.

Invariants verified in this phase: **INV-R001** (provenance intact on real data), **INV-C002**
(non-null `uncallable_sites_excluded` on real-data row).

**Completion gate**: Regression smoke green per the [Regression Smoke section](development-plan.md#regression-smoke) of this development plan; smoke result pasted into `work-notes.md`.

---

## Testing Strategy

| Category | What is tested |
|---|---|
| Unit | `_classify_genotype_sources` logic — each of the four `genotype_source` values; boundary at depth=10; GIAB BED boundary (site at edge of confident region); site present in source VCF |
| Unit | `apply_uncallable_filter` — synthetic sidecar with mix of source values; asserts matched+unmatched counts do not include uncallable sites |
| Unit | `MatchStats.match_rate` with `uncallable_excluded > 0` — denominator excludes uncallable sites |
| Integration | `prepare_coverage_tier1` end-to-end with mocked bcftools and mocked GIAB BED — emits sidecar; cache-hit with both VCF+sidecar present; cache-miss when sidecar absent |
| Integration | `compute_pgs` with sidecar path — `PgsRow.uncallable_sites_excluded` populated |
| Provenance | `tier1.qc.json` contains `giab_bed_release` and `min_callable_depth` after a build |
| Provenance | Sidecar header block contains all five required fields |
| Invariant | `test_invC002_uncallable_excluded_from_pgs_denominator` — synthetic fixture, asserts uncallable sites absent from both counts |
| Schema | `pgs_scores` DDL contains `uncallable_sites_excluded INTEGER` |
| Determinism | Two force-genotype runs on the same inputs produce byte-equivalent sidecars |
| Real-data smoke | PGS000018 CAD rerun on project owner's genome; sidecar present; uncallable count documented |

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](../bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan's final phase is not Complete until the following real-data smoke is green:

**Command**:
```bash
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```

**Pass criteria**:
- Sidecar `forced_genotype_provenance.tsv.zst` produced alongside the forced VCF.
- `pgs_scores.uncallable_sites_excluded` populated (non-null) in the resulting row.
- Raw score is within rounding of the pre-change baseline: if excluded sites carry zero effect weight, score is unchanged; any documented delta is recorded in `work-notes.md`.

**Why this smoke**: the `genotype_source` classification depends on the real GIAB BED intersection against the project owner's actual forced sites — only a real-data run confirms the sidecar is written, the provenance columns are populated, and the PGS score arithmetic is correct end-to-end.

The smoke result is recorded in `work-notes.md` as part of the final phase's Completion block before the plan moves to `docs/plans/completed/`.

---

## Documentation Updates Required

- `docs/reference/INVARIANTS.md` — promote `INV-C002` after Phase 3 tests are merged and
  green. Assign `INV-C002` (next available in the `INV-C` series, currently at `INV-C001`).
  Increment `Version` to 1.18 and update `Last Updated`.
- `docs/plans/active/bioreview-followup-meta/meta-plan.md` — update `force-genotype-callable-mask`
  status row from `Drafted` to `Complete` when all phases are done.
- `work-notes.md` in this plan — updated continuously.

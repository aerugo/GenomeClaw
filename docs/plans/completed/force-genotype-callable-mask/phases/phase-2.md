# Phase 2: Per-Site Genotype-Source Annotation

**Plan**: [development-plan.md](../development-plan.md)  
**Status**: Not started  
**Prerequisite**: Phase 1 complete (GIAB BED registered and fetchable)  
**Estimated duration**: ~2.5 days

---

## Objective

After Tier-1 or Tier-2 force-genotyping completes, emit a sidecar file
`forced_genotype_provenance.tsv.zst` co-located with the forced VCF that classifies every
forced site as one of four `genotype_source` values. Extend the `tier1.qc.json` schema with
`giab_bed_release` and `min_callable_depth`. Bump `SCHEMA_VERSION` to `"3"`. Update the
cache-hit check to require both VCF and sidecar.

---

## Invariants Enforced in This Phase

- **INV-D001** — The CRAM and Nebula VCF are opened read-only. The sidecar is a new derived
  artifact written under `data/derived/`, never to `data/raw/`. Tests assert the source VCF
  and CRAM are not modified after a classification run.

- **INV-R001** — The `tier1.qc.json` blob gains `giab_bed_release` and `min_callable_depth`.
  The sidecar TSV itself has a five-line comment header with schema version, GIAB BED release,
  threshold, and timestamp. Tests assert both are present after a successful build.

- **INV-E001** — The `genotype_source` value on each row is the structural evidence linkage
  connecting a PGS score to the quality of its dosage support. Tests assert that every row in
  the sidecar carries a non-null `genotype_source` value from the allowed set.

---

## Sidecar Specification

**Path**: `<derived>/prs_coverage/<sample_id>/<panel_version>/forced_genotype_provenance.tsv.zst`

**Format**: Zstandard-compressed TSV (`.tsv.zst`). UTF-8. Written as a streaming generator
with batch sizes of ~50k rows per `zstandard` write call to avoid materialising millions of
rows in memory (anti-pattern guard from the pipeline agent spec).

**Comment header** (five lines, each starting with `#`):
```
# genomeclaw_forced_genotype_provenance
# schema_version=3
# giab_bed_release=<e.g. v4.2.1-hg001>
# min_callable_depth=10
# created_at=<ISO 8601 UTC, e.g. 2026-05-25T14:30:00Z>
```

**Column header** (line 6, tab-delimited):
```
chrom	pos	ref	alt	genotype_source
```

**Data rows**: one row per site in the forced VCF. `pos` is 1-based (VCF convention).

**`genotype_source` values**:
| Value | Condition |
|---|---|
| `nebula_called` | `(chrom, pos)` is present in the source Nebula VCF position set |
| `force_genotyped_high_conf` | Force-genotyped, pileup DP ≥ 10, AND site intersects GIAB BED |
| `force_genotyped_low_conf` | Force-genotyped, pileup DP ≥ 10, AND site does NOT intersect GIAB BED |
| `uncallable` | Force-genotyped, pileup DP < 10 (includes DP = 0 / missing) |

**Note on DP source**: the `FORMAT/DP` field is already emitted by the existing
`_BCFTOOLS_PIPE_TEMPLATE` via `--annotate FORMAT/DP,FORMAT/AD` (line 383 in
`coverage_fill.py`). The classifier reads this field from the forced VCF output; no second
pileup pass is required.

---

## Step 2.1 — RED: Write Failing Tests

### Test files

`packages/toolkit/tests/unit/prep/test_coverage_fill_genotype_source.py`  
`packages/toolkit/tests/unit/prep/test_coverage_fill_cache_v3.py`

### Unit tests for `_classify_genotype_sources`

**`test_nebula_called_site`**
- Site present in `nebula_vcf_positions` set → `genotype_source = "nebula_called"`, regardless
  of DP value.

**`test_uncallable_zero_depth`**
- Site absent from `nebula_vcf_positions`; DP = 0 → `genotype_source = "uncallable"`.

**`test_uncallable_low_depth`**
- Site absent from `nebula_vcf_positions`; DP = 9 → `genotype_source = "uncallable"`.

**`test_force_genotyped_high_conf_at_boundary`**
- DP = 10 (at threshold); site inside GIAB BED interval → `genotype_source = "force_genotyped_high_conf"`.

**`test_force_genotyped_low_conf`**
- DP = 25; site outside GIAB BED → `genotype_source = "force_genotyped_low_conf"`.

**`test_force_genotyped_high_conf`**
- DP = 30; site inside GIAB BED → `genotype_source = "force_genotyped_high_conf"`.

**`test_giab_bed_boundary_just_inside`**
- Site at exact start coordinate of a GIAB interval (0-based half-open: `[start, end)`) →
  `force_genotyped_high_conf`.

**`test_giab_bed_boundary_just_outside`**
- Site one base before the start of a GIAB interval → `force_genotyped_low_conf`.

**`test_missing_dp_treated_as_uncallable`**
- Site absent from `nebula_vcf_positions`; DP field is `.` or missing in the VCF FORMAT
  column → `genotype_source = "uncallable"` (treat missing DP as depth=0).

**`test_invE001_all_rows_have_genotype_source`**
- Build a small synthetic forced VCF (5 rows). Run classifier. Assert every row in the
  sidecar has a non-null `genotype_source` in the allowed set.

### Unit tests for sidecar I/O

**`test_sidecar_header_contains_required_fields`**
- Reads back a sidecar TSV.zst and asserts the five-line comment header contains
  `schema_version=3`, `giab_bed_release=`, `min_callable_depth=`, `created_at=`.

**`test_sidecar_columns`**
- Asserts the column header line (line 6) is exactly `chrom\tpos\tref\talt\tgenotype_source`.

**`test_sidecar_streaming_no_materialise`**
- Runs classifier over 200k synthetic rows. Asserts peak memory during classification is
  below 200 MB (guards against the `[{**row} for row in ...]` anti-pattern).
  Uses `tracemalloc`.

### Unit tests for `tier1.qc.json` extension

**`test_tier1_qc_contains_giab_bed_release`**
- After `prepare_coverage_tier1` completes on a mocked run, reads `tier1.qc.json` and asserts
  `"giab_bed_release"` key is present with the expected release string.

**`test_tier1_qc_contains_min_callable_depth`**
- After `prepare_coverage_tier1` completes, reads `tier1.qc.json` and asserts
  `"min_callable_depth": 10`.

**`test_invR001_schema_version_is_3`**
- After `prepare_coverage_tier1` completes, reads `tier1.qc.json` and asserts
  `"schema_version": "3"`.

### Unit tests for cache-hit behaviour

**`test_cache_hit_requires_both_vcf_and_sidecar`**
- Scenario: VCF present, sidecar absent. Asserts `prepare_coverage_tier1` triggers a rebuild
  (calls `_force_genotype_tier1` and `_classify_genotype_sources`).

**`test_cache_hit_with_both_present_and_v3`**
- Scenario: VCF present, sidecar present, `tier1.qc.json` has `schema_version=3`, CRAM SHA
  matches. Asserts `prepare_coverage_tier1` returns cached VCF path WITHOUT calling
  `_force_genotype_tier1`.

**`test_cache_miss_on_v2_schema`**
- Scenario: VCF present, but `tier1.qc.json` has `schema_version=2` (legacy cache). Asserts
  `prepare_coverage_tier1` triggers a rebuild.

### Atomicity test

**`test_sidecar_atomic_promote`**
- Asserts the sidecar is written to a shard scratch path first, then `atomic_promote`d to the
  final location alongside the VCF. Tests this by checking that a partial write (simulated by
  a mock that raises mid-write) leaves no partial file at the final path.

Run: `uv run pytest packages/toolkit/tests/unit/prep/test_coverage_fill_genotype_source.py packages/toolkit/tests/unit/prep/test_coverage_fill_cache_v3.py -v`

All tests must fail (classifier and sidecar functions do not yet exist).

---

## Step 2.2 — GREEN: Minimal Implementation

### File to modify

`packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py`

### Changes (in order of dependency)

**1. SCHEMA_VERSION bump**

Change line 68:
```
SCHEMA_VERSION = "2"  # v2 (pgs-allele-orientation): tier2.qc.json adds orientation_* counts
```
to:
```
SCHEMA_VERSION = "3"  # v3 (force-genotype-callable-mask): adds forced_genotype_provenance
                      # sidecar + giab_bed_release + min_callable_depth in tier*.qc.json
```

**2. `_MIN_CALLABLE_DEPTH` constant**

Add after `SCHEMA_VERSION`:
```python
_MIN_CALLABLE_DEPTH: Final[int] = 10
"""Minimum pileup depth (FORMAT/DP) for a force-genotyped site to be considered callable.

Sites with DP < 10 are classified as ``uncallable`` and excluded from PGS match-rate
calculations (INV-C002). Value 10 mirrors GATK's historic callable-depth convention and is
persisted in tier*.qc.json as ``min_callable_depth`` for rebuildability (INV-R001).
"""
```

**3. `_load_giab_intervals(bed_gz_path)` helper**

A new private function that:
- Opens the bgzipped BED with `gzip.open` (BED files compressed with bgzip are valid gzip
  streams; tabix-aware parsing is not required for a simple interval query).
- Reads `chrom`, `start` (0-based), `end` (0-based, exclusive) columns.
- Returns `dict[str, list[tuple[int, int]]]` mapping chrom → sorted list of (start, end)
  intervals (sorted by start for `bisect` queries).
- Skips comment lines (`#`). Skips non-autosomal / non-standard contigs silently.
- Memory cost: ~1.5 GB for the full NA12878 v4.2.1 BED loaded as Python tuples; acceptable
  for a one-time load per force-genotype run.

**4. `_site_in_giab(chrom, pos_1based, intervals_by_chrom)` helper**

- Converts `pos_1based` to 0-based (subtract 1).
- Uses `bisect.bisect_right(starts, pos_0based) - 1` to find the candidate interval.
- Returns `True` iff the candidate interval's end > pos_0based.

**5. `_parse_nebula_vcf_positions(vcf_path)` helper**

- Streams the Nebula VCF (bgzipped) with `gzip.open`.
- Returns `frozenset[tuple[str, int]]` of `(chrom, pos_1based)` for all non-header records.
- Called once before the classification loop.

**6. `_parse_dp_from_format(format_str, sample_str)` helper**

- Parses a VCF FORMAT field string (e.g. `"GT:DP:AD"`) and sample field string (e.g.
  `"0/0:25:25,0"`) to extract the integer DP value.
- Returns `0` if DP is absent, `.`, or unparseable.

**7. `_classify_genotype_sources(...)` main function**

Signature:
```python
def _classify_genotype_sources(
    *,
    forced_vcf: Path,
    nebula_vcf_positions: frozenset[tuple[str, int]],
    giab_intervals: dict[str, list[tuple[int, int]]],
    output_sidecar: Path,
    giab_bed_release: str,
    min_callable_depth: int = _MIN_CALLABLE_DEPTH,
) -> int:
    """Classify each site in ``forced_vcf`` into one of four genotype_source values.

    Writes a Zstandard-compressed TSV sidecar at ``output_sidecar`` atomically via
    :func:`atomic_promote`. Returns the count of ``uncallable`` sites.

    INV-R001: the sidecar header records schema_version, giab_bed_release,
    min_callable_depth, and created_at.
    INV-E001: every site receives a non-null genotype_source from the allowed set.
    INV-D001: ``forced_vcf`` is opened read-only; ``output_sidecar`` is the only new file.
    """
```

Implementation outline:
1. Open `forced_vcf` with `gzip.open` for streaming reads.
2. Allocate a scratch path under `shard_scratch(step="classify_sources", ...)` using
   `ephemeral_scratch_base()`.
3. Open the scratch `.tsv.zst` for streaming Zstandard writes.
4. Write the five-line comment header.
5. Write the column header line.
6. For each data row in the forced VCF:
   - Parse `chrom`, `pos`, `ref`, `alt`, `FORMAT`, `sample` columns.
   - Determine `genotype_source` using the classification logic.
   - Write a row to the sidecar in batches of 50k rows (flush per batch; `os.fsync` between
     batches if writing to a bind-mounted external drive — see the pipeline agent's virtiofs
     cliff note).
7. `atomic_promote(scratch_sidecar, output_sidecar)`.
8. Return the `uncallable` count.

**8. Extend `prepare_coverage_tier1`**

The function at line 541 of `coverage_fill.py` is modified to:

- Accept two new keyword arguments: `giab_bed_path: Path | None` and `nebula_vcf_path: Path | None`.
- After `_force_genotype_tier1` completes, call `_classify_genotype_sources(...)`.
- Extend the cache-hit check: a hit now requires `cache_vcf.exists()` AND
  `cache_sidecar.exists()` AND `qc_existing.get("schema_version") == SCHEMA_VERSION`.
  Any condition false → cache miss → full rebuild.
- The `tier1.qc.json` blob is extended with:
  ```python
  "giab_bed_release": giab_bed_release,  # or "not_provided" if giab_bed_path is None
  "min_callable_depth": min_callable_depth,
  ```
- When `giab_bed_path` is `None` (GIAB BED not yet fetched), all sites receive
  `force_genotyped_low_conf` (the conservative fallback — no site can be promoted to
  `force_genotyped_high_conf` without the BED). A log warning is emitted. The sidecar is
  still written (no `uncallable` sites without depth information available, but all force-
  genotyped sites are classified as `low_conf`). This ensures the sidecar is always present
  after a successful run, even for users who have not yet fetched the GIAB BED.

  The `giab_bed_release` field in `tier1.qc.json` is set to `"not_provided"` in this case.

Run: `uv run pytest packages/toolkit/tests/unit/prep/test_coverage_fill_genotype_source.py packages/toolkit/tests/unit/prep/test_coverage_fill_cache_v3.py -v`

All tests must pass.

---

## Step 2.3 — REFACTOR

- Add module-level docstring update to `coverage_fill.py` to mention the Phase 3 sidecar
  and the `INV-R001`, `INV-E001` compliance of the new output.
- Ensure `_classify_genotype_sources` docstring cites INV-R001 and INV-E001 by ID.
- Ensure `_load_giab_intervals` includes a note that BED intervals are 0-based half-open and
  the conversion from 1-based VCF `pos` is explicit in `_site_in_giab`.
- Ensure `_MIN_CALLABLE_DEPTH` docstring cites INV-C002 by name (proposed) and GATK source.
- Re-run full toolkit test suite: `uv run pytest packages/toolkit/tests/ -v --tb=short`.

---

## Files Changed in Phase 2

| Operation | File |
|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` |
| CREATE | `packages/toolkit/tests/unit/prep/test_coverage_fill_genotype_source.py` |
| CREATE | `packages/toolkit/tests/unit/prep/test_coverage_fill_cache_v3.py` |

---

## Verification

```bash
# Phase 2 unit tests
uv run pytest packages/toolkit/tests/unit/prep/test_coverage_fill_genotype_source.py \
              packages/toolkit/tests/unit/prep/test_coverage_fill_cache_v3.py -v

# Full toolkit test suite — no regressions
uv run pytest packages/toolkit/tests/ -v --tb=short
```

### Manual smoke (optional before Phase 3)

If the project owner's GIAB BED has been fetched:
```bash
genomeclaw prs coverage-fill \
  --cram data/raw/<sample>.cram \
  --vcf data/raw/<sample>.vcf.gz \
  --panel-version <panel_version> \
  --giab-bed data/reference/giab_high_confidence/v4.2.1-hg001/HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz \
  --derived-root data/derived/
```
Check `data/derived/prs_coverage/<sample>/<panel>/`:
- `forced_genotype_provenance.tsv.zst` exists.
- `tier1.qc.json` contains `giab_bed_release` and `min_callable_depth`.
- Inspect sidecar header: `zstdcat forced_genotype_provenance.tsv.zst | head -6`.

---

## Completion Criteria

- [ ] All Phase-2 unit tests pass (RED → GREEN cycle visible in commits).
- [ ] `SCHEMA_VERSION` in `coverage_fill.py` is `"3"`.
- [ ] `_MIN_CALLABLE_DEPTH = 10` constant present.
- [ ] `_classify_genotype_sources` emits the sidecar atomically via `atomic_promote`.
- [ ] `test_cache_hit_requires_both_vcf_and_sidecar` — sidecar-absent triggers rebuild.
- [ ] `test_cache_miss_on_v2_schema` — legacy v2 cache triggers rebuild.
- [ ] `test_invR001_schema_version_is_3` passes — `tier1.qc.json` has `schema_version=3`.
- [ ] `test_invE001_all_rows_have_genotype_source` passes — all rows classified.
- [ ] `test_sidecar_streaming_no_materialise` passes — peak memory < 200 MB on 200k rows.
- [ ] Full toolkit test suite green (no regressions from SCHEMA_VERSION bump).
- [ ] `work-notes.md` updated with Phase 2 complete block.
- [ ] Phase status updated in `development-plan.md` to "Complete".
- [ ] _(Forward note — applies to final phase, phase-4.md, when written)_ Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

---

## Handoff Notes for Phase 3

Phase 3 (`_pgsc_calc_match.py` correction) depends on:
- The sidecar path convention: `<derived>/prs_coverage/<sample_id>/<panel_version>/forced_genotype_provenance.tsv.zst`.
- The column schema: `chrom`, `pos`, `ref`, `alt`, `genotype_source`.
- The allowed `genotype_source` values (the four-value enum above).
- The `MatchStats` dataclass in `_pgsc_calc_match.py` needs a new `uncallable_excluded: int = 0` field.

These are the only contracts Phase 3 consumes from Phase 2. Phase 3 does not re-read the GIAB
BED or the forced VCF directly.

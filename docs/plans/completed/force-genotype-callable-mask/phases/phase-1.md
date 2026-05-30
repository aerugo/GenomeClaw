# Phase 1: GIAB Reference Data Registration

**Plan**: [development-plan.md](../development-plan.md)  
**Status**: Not started  
**Estimated duration**: ~1 day

---

## Objective

Register `giab_high_confidence` as a fetchable source in `fetch.py`'s `_LAYOUTS` dict so
that `genomeclaw refs fetch --source giab_high_confidence` downloads, MD5-verifies, and
atomically places the GIAB NA12878/HG001 v4.2.1 high-confidence regions BED into
`data/reference/giab_high_confidence/<release>/`.

---

## Invariants Enforced in This Phase

- **INV-D001** — The downloaded BED is placed under `data/reference/`, never under
  `data/raw/`. Re-fetching the same release raises `VersionAlreadyExists` without overwriting
  the existing file. Tests assert the pre-fetch file content is unchanged when `VersionAlreadyExists`
  is raised.

- **INV-R001** — The fetch completes only when the MD5 checksum matches the NCBI-published
  sidecar. The target directory path (`reference/giab_high_confidence/<release>/`) encodes the
  release string. Tests assert the exact file layout.

- **INV-P001** — The fetch is a user-initiated CLI command, not an automatic background
  download. No egress occurs outside `refs fetch`. Tests use the `base_url=` override to mock
  HTTP so no real network call is made in CI.

---

## Source Artifact Details

**Dataset**: GIAB Personal Genomes Benchmark — NA12878 / HG001, v4.2.1  
**Publisher**: NIST / NCBI Genome-In-A-Bottle Consortium  
**Licence**: Public domain (NIST work product, explicitly not copyrighted)  
**NCBI FTP base**: `https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/NA12878_HG001/NISTv4.2.1/GRCh38/`

Files to fetch:

| File | Purpose | MD5 sidecar |
|---|---|---|
| `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz` | High-confidence regions BED (bgzipped) | `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz.md5` |
| `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz.tbi` | Tabix index (required for `bcftools view -R`) | No MD5 published; structural integrity verified at first intersection query |

The `.md5` file at NCBI uses the standard `<hex>  <filename>` format (two spaces), which is
the same format parsed by the existing `_download_and_verify_md5_sidecar` path in `fetch.py`.
The MD5 mode for these files is Mode 1 (`md5_relpath` set, `md5_checksums_relpath` unset) —
the same mode used by `clinvar` and `dbsnp`.

**Release string**: `v4.2.1-hg001` — encodes both the GIAB versioned-release (`v4.2.1`) and
the sample (`HG001`). This is the value stored in `tier1.qc.json` as `giab_bed_release` in
Phase 2.

**Target layout after fetch**:
```
data/reference/giab_high_confidence/v4.2.1-hg001/
    HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz
    HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz.tbi
```

---

## Step 1.1 — RED: Write Failing Tests

### Test file

`packages/toolkit/tests/unit/prep/test_fetch_giab.py`

### Test cases

**`test_giab_layout_registered`**
- Asserts `"giab_high_confidence" in fetch._LAYOUTS`.
- Asserts the layout has exactly two `files` entries and no `chrom_files`.
- Asserts `output_filename` values are `"HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz"` and
  `"HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz.tbi"`.

**`test_giab_layout_has_md5_for_bed_file`**
- Asserts the first `_FetchFile` (the `.bed.gz`) has `md5_relpath` set to the expected
  NCBI FTP sidecar path.
- Asserts `md5_checksums_relpath` is `None` (Mode 1, not Mode 2).

**`test_giab_layout_tbi_has_no_md5`**
- Asserts the second `_FetchFile` (the `.tbi`) has both `md5_relpath` and
  `md5_checksums_relpath` as `None`. Structural integrity is verified at query time, not at
  fetch time (consistent with the existing `clinvar.vcf.gz.tbi` pattern).

**`test_giab_fetch_downloads_and_verifies` (mock-HTTP)**
- Uses the `base_url=` override to point `fetch()` at a local HTTP test fixture server
  (pattern from existing `test_fetch_clinvar.py` etc.).
- Serves the `.bed.gz` with a known content + the matching `.md5` sidecar.
- Serves the `.tbi` with a known content.
- Calls `fetch("giab_high_confidence", release="v4.2.1-hg001", ...)`.
- Asserts both output files exist under `target_dir/`.
- Asserts the `.bed.gz` on disk matches the served content byte-for-byte.

**`test_giab_fetch_idempotent` (mock-HTTP)**
- After a successful first fetch, calls `fetch(...)` again with the same release.
- Asserts `VersionAlreadyExists` is raised.
- Asserts the existing file content is unchanged.

**`test_giab_fetch_checksum_mismatch` (mock-HTTP)**
- Serves a `.bed.gz` whose content does not match the `.md5` sidecar.
- Asserts `ChecksumMismatch` is raised.
- Asserts no partial file remains on disk after the exception.

**`test_giab_fetch_invD001_no_raw_mutation`**
- Creates a dummy file under a fake `reference_root`.
- Runs a fetch.
- Asserts no file was written outside `target_dir`.

**`test_giab_invR001_release_in_path`**
- Asserts the computed target directory for release `"v4.2.1-hg001"` is
  `<reference_root>/giab_high_confidence/v4.2.1-hg001/`.

Run: `uv run pytest packages/toolkit/tests/unit/prep/test_fetch_giab.py -v`

All tests must fail (the layout entry does not yet exist).

---

## Step 1.2 — GREEN: Minimal Implementation

### File to modify

`packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py`

### Change

Add a `"giab_high_confidence"` entry to `_LAYOUTS` immediately after the `"loftee"` entry
(around line 810+, after the existing registrations). The entry uses `_SourceLayout` with two
`_FetchFile` entries (Mode 1 MD5 for the `.bed.gz`; no MD5 for the `.tbi`).

The `base_url` for `fetch()` resolves the full URL as `base_url + relpath`. The canonical
`base_url` for GIAB is:
```
https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/NA12878_HG001/NISTv4.2.1/GRCh38/
```

Both files live flat in that directory:
- `.bed.gz` relpath: `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz`
- `.bed.gz.md5` relpath: `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz.md5`
- `.tbi` relpath: `HG001_GRCh38_1_22_v4.2.1_benchmark.bed.gz.tbi`

No `post_fetch` hook is required (the `.tbi` is pre-built by NCBI alongside the BED).
No `output_subdir` is required (both files land directly under `target_dir/`).
No `presence_relpath` is required (the `.bed.gz` file itself is the canonical presence check
and is not deleted post-fetch).

The `Source` type alias in `fetch.py` (line 93) extends to include `"giab_high_confidence"`.

### No other files change in Phase 1.

Run: `uv run pytest packages/toolkit/tests/unit/prep/test_fetch_giab.py -v`

All six tests must pass.

---

## Step 1.3 — REFACTOR

- Add a comment block above the `"giab_high_confidence"` layout entry (matching the style of
  the `"dbsnp"`, `"loftee"`, and `"pgs_catalog_ancestry"` entries) that records:
  - Dataset name, sample, release, publication date.
  - NCBI FTP base URL.
  - Licence (public domain, NIST).
  - Note that the `.tbi` has no MD5 sidecar (NCBI doesn't publish one).
  - Note that this BED covers autosomes + chrX + chrY for GRCh38 only.
- Confirm `Source` type alias comment is updated.
- Re-run full unit test suite: `uv run pytest packages/toolkit/tests/ -v --tb=short`

---

## Files Changed in Phase 1

| Operation | File |
|---|---|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` |
| CREATE | `packages/toolkit/tests/unit/prep/test_fetch_giab.py` |

---

## Verification

```bash
# Unit tests — Phase 1 only
uv run pytest packages/toolkit/tests/unit/prep/test_fetch_giab.py -v

# Full toolkit test suite — no regressions
uv run pytest packages/toolkit/tests/ -v --tb=short
```

---

## Completion Criteria

- [ ] All six Phase-1 tests pass (RED → GREEN cycle visible in commits).
- [ ] `"giab_high_confidence"` entry present in `_LAYOUTS` with correct file list, MD5 mode,
  and URL structure.
- [ ] `Source` type alias includes `"giab_high_confidence"`.
- [ ] `test_giab_invD001_no_raw_mutation` and `test_giab_invR001_release_in_path` reference
  `INV-D001` and `INV-R001` respectively in their docstrings.
- [ ] Full toolkit test suite green (no regressions).
- [ ] `work-notes.md` updated with Phase 1 complete block.
- [ ] Phase status updated in `development-plan.md` to "Complete".

# Phase 4C.4 — annotation correctness + reference data integrity tactical sub-plan

**Status**: 🟢 **Closed 2026-05-15** as part of the MVP Phase 4 close-paperwork sweep. W1–W4 + W7 all ✅ shipped; W5 + W6 marked non-blocking residual items and explicitly accepted as deferred at Phase 4 closure. The 2026-05-13 second-pass investigation confirmed W4 (dbSNP rename) + W7 (real-data ClinVar parity at **42,885 / 42,885, +0.00%**) both shipped in commit 1f58aeb, in one session. W5 (pre-flight validator) didn't ship — kept as a future guard, not blocking. W6 (vcfanno stderr discipline) didn't ship — likely obsolete after the per-chrom shard pattern landed in 1f58aeb; verify before any future revisit.
**Created**: 2026-05-12
**Paused**: 2026-05-12
**Partially resumed**: 2026-05-13 (after [rich-cli plan](rich-cli/) closed)
**W4 + W7 closed**: 2026-05-13 (commit 1f58aeb)
**Plan closed + moved to completed/**: 2026-05-15
**Parent**: [docs/plans/active/mvp/phases/phase-4.md](../active/mvp/phases/phase-4.md)
**Predecessor**: Sub-phase 4C.3 closed ([work-notes 2026-05-11](../active/mvp/work-notes.md#L753)); W3 parent-orchestrator rewrite shipped 218/0 in-image.
**Successor**: superseded by [docs/plans/active/mvp/phases/phase-4-completion.md § W4](../active/mvp/phases/phase-4-completion.md) (ClinVar parity check — passed 2026-05-13).
**Scope**: diagnose and fix the faults that surfaced when the W4 real-data parity check ran against the project owner's Nebula VCF + full reference layout for the first time. Restore W4 to a passable state.

---

## Status update — 2026-05-13 (second-pass investigation)

The [rich-cli plan](../../../completed/rich-cli/) closed, which absorbed W1 and W1.5 of this plan into its Phase 3. Commit 1f58aeb later that day shipped W4 + W7 together at exact real-data parity. As of 2026-05-13 end-of-day:

| W# | Item | Status |
|----|------|--------|
| W1 | Fetcher Content-Length + bgzip EOF verification | ✅ shipped in rich-cli Phase 3 |
| W1.5 | Smarter download: stall detection + Range-resume + bounded retries | ✅ shipped in rich-cli Phase 3 |
| W2 | Doctor-side integrity sweep across staged references | ✅ shipped as `genomeclaw refs verify` (rich-cli Phase 4) |
| W3 | Re-fetch the 5 truncated gnomAD chrom files | ✅ effectively done — `genomeclaw refs verify` confirms all 26 bgzipped reference files intact as of 2026-05-13 |
| **W4** | **dbSNP RefSeq → UCSC chr-rename** | ✅ **shipped in commit 1f58aeb** — `_DBSNP_REFSEQ_TO_UCSC_MAP` (25 contigs) + `_stage_dbsnp_with_cache` + generalised `_stage_with_chr_rename` + 3 covering tests in `test_annotate_vcfanno.py` |
| W5 | Pre-flight annotation schema validator | ⏸ **Pending but non-blocking** — W7 passed without it. Kept open as a future guard against overlay-source regressions. |
| W6 | Vcfanno stderr noise filter + redirect-to-file | ⏸ **Pending but likely obsolete** — the per-chrom shard pattern shipped in 1f58aeb eliminated the bix.go noise structurally. The old `Popen + readline + sys.stderr.write + flush` pattern is still in `_vcfanno.py:136-150` but the 1h59m real-data wall on 4.87M variants suggests the 50% stderr-overhead concern is gone. Verify before closing 4C.4. |
| **W7** | **Resume the ClinVar parity check** | ✅ **passed in commit 1f58aeb** at **42,885 / 42,885 ClinVar matches (+0.00% delta vs. Phase-4A baseline)** on the project owner's Nebula VCF, 1h59m end-to-end wall on consumer hardware |

CLI commands throughout this doc are updated to the post-rich-cli `genomeclaw <group> <verb>` form.

---

---

## Why this plan exists

W4 (the Phase-4 closure gate — ClinVar match-count parity vs the Phase-4A baseline of 42,885) was attempted on 2026-05-12 and failed. The pipeline survived ingest + normalize and reached `annotate-vcfanno`, where vcfanno exited mid-stream after processing ~22% of the input VCF.

Initial hypothesis was a vcfanno bug. **The actual root cause turned out to be upstream of vcfanno entirely** — a fetcher correctness gap that lets silently truncated downloads pass as "complete". Three distinct issues surfaced during diagnosis (one critical, two cosmetic), plus a `dbsnp_rsid` regression that's unrelated to the immediate crash but blocks W4 by itself.

---

## Diagnostic timeline (2026-05-12)

1. **Initial failure**: `annotate-vcfanno` died at chr4:~13Mb in the original pipeline run; `VcfannoError(rc=2)`. Our wrapper's deque-buffered error message truncated, so the actual fatal line was unknown.
2. **V1 diagnostic**: re-ran vcfanno via `bash -c '... 2> file.log'` (shell-redirect, no Python pipe). Result: vcfanno ran **30+ minutes**, processed **1,933,909 records** (well past the original crash point), then died with the fatal line **`parallel.go:151: bix: error creating chunked reader from /mnt/genomeclaw/reference/gnomad-exomes/v4.1/by_chrom/chr6.vcf.bgz: EOF`**. Exit code 1.
3. **V1b forensics — bgzip EOF marker sweep across all 24 gnomAD chrom files**:

   | File | Trailing 28 bytes | Status |
   |---|---|---|
   | chr1, chr2, chr3, chr4, chr5, chr8, chr12–22, chrX, chrY | canonical bgzip EOF block | OK ✓ |
   | **chr6** (8.32 GB) | `42 19 32 c2 …` | **TRUNCATED** |
   | **chr7** (3.94 GB, expected ~7.8 GB) | `ff 0e bc b7 …` | **TRUNCATED** |
   | **chr9** (3.46 GB, expected ~6.6 GB) | non-marker | **TRUNCATED** |
   | **chr10** (1.08 GB, expected ~7.0 GB) | non-marker | **TRUNCATED** |
   | **chr11** (4.16 GB, expected ~8.5 GB) | non-marker | **TRUNCATED** |
   | ClinVar (191 MB), dbSNP b157 (29.5 GB) | canonical bgzip EOF block | OK ✓ |

   **5 of 24 gnomAD-exomes per-chrom files are silently truncated.** They have valid bgzip framing at the start (so `htsfile` and `bcftools view -h` succeed) and tabix `.tbi` sidecars (so position queries succeed). But reading past the truncation point dies with EOF — exactly what vcfanno hit.

4. **Fetcher review** — [prep/fetch.py:413-457](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py#L413-L457) downloads chunks until `urllib`'s `read()` returns empty, then declares success. It captures `Content-Length` and computes MD5 of the stream, but **never compares `bytes_so_far` against `Content-Length`** and never validates the bgzip EOF marker. If the upstream HTTP connection drops cleanly mid-stream (no exception raised), urllib returns the truncated bytes; the fetcher writes them; the on-disk file is left as a silently-incomplete bgzip.

5. **Independent regression discovered**: dbSNP b157 uses **NCBI RefSeq accessions** (`NC_000001.11`, `NC_000002.12`, …) on contigs — neither numeric nor chr-prefixed. We rename ClinVar but not dbSNP. Result: **zero** `dbsnp_rsid` annotations on the survived `annotated.vcf` (verified via `grep -c`).

## Confirmed root cause

> **The fetcher accepts truncated downloads as complete.** Five gnomAD chrom files were silently truncated on first fetch. vcfanno's chunked-reader fails as soon as it reaches the truncation point in any one of them. The original chr4-position failure was a quirk of where in the input stream the read first hit a truncated file — the underlying cause has always been the corrupted reference data.

This is exactly the class of issue the [cram-scratch-strategy](../../../completed/cram-scratch-strategy/) plan flagged in its **Phase 4+ tripwires** ("vcfanno-class deadlock, sustained throughput < 100 MB/s, EIO under load") — but here the upstream miss is at fetch time, not run time. The fix lives in the fetcher.

## Cosmetic / non-blocking findings

- vcfanno's per-chrom-block layout emits ~24 `bix.go:251: chromosome chrN not found in chrM.vcf.bgz` warnings per input record. With ~5M input records this is ~120M warning lines (we saw 10,596 in the V1 diagnostic — heavily down-sampled by vcfanno's own dedup). They drowned the actual error in our deque-truncated wrapper output. Worth filtering; not blocking.
- Our wrapper's `Popen + sys.stderr.write per line + flush` stderr-streaming pattern adds ~50% wall-time overhead vs `2> file` shell redirect. Worth fixing alongside the noise filter; not blocking.
- W2 (gnomAD INFO field-name verification) was [explicitly scoped](phase-4-completion.md#w2--gnomad-info-field-name-pre-flight-verification-15-min) and deferred. The 4C.4 diagnostic retroactively confirms the names are correct (`AF_grpmax`, `grpmax`, `AF_afr`, `AF_amr`, `AF_eas`, `AF_nfe`, `AF_sas` — all present in the chr22 header). No code change needed. **But the principle was wrong**: one-shot manual verification can lapse silently. Pre-flight validation belongs in code.

---

## Critical invariants to respect

- **INV-D001** Raw genomic files source-of-truth — the staged ClinVar / dbSNP copies in scratch are the only mutations; source files under `reference/{clinvar,dbsnp}/` are read-only. The new dbSNP rename must follow the same pattern.
- **INV-D003** Heavy scratch separated from authoritative outputs — staged files + vcfanno's intermediate output live under `_scratch/annotate-vcfanno-<run-id>/` via `shard_scratch(...)`. The W3 parent-orchestrator already enforces this.
- **INV-R001** Rebuildability — the per-source rename step + post-download integrity check + the vcfanno step each record their tool versions + params in `provenance.json`. The new dbSNP rename must extend `provenance.json` accordingly.

## Proposed new invariants (provisional, promote at 4C.4 close)

- **INV-D-fetch-integrity** *(provisional)*: *Every reference file downloaded by `genomeclaw-prep fetch` is verified to be complete before the fetcher reports success.* "Complete" means: (a) the byte count matches the upstream `Content-Length` when one is provided, AND (b) for bgzipped files, the canonical 28-byte EOF marker is present at the tail. A failed check fails the fetch loudly and removes the partial file. The current 4C.4 diagnostic empirically demonstrates the need; promotion gated on the fetcher fix landing without regressions.
- **INV-R-pre-flight** *(provisional)*: *Annotation runs validate the declared fields + contigs against each overlay source's header before invoking the annotator.* Rationale: pipelines fail in <1s with a clear per-source error rather than crashing partway through after 30+ min. Promotion gated on the validator landing in V3 + on 4D (VEP) benefiting from the same pattern.

---

## Work items

### W1 — Fetcher post-download integrity verification *(critical, ~2 hours)*

**Status**: ✅ **Shipped via rich-cli Phase 3** (2026-05-12 / 2026-05-13). See [completed/rich-cli/](../../../completed/rich-cli/).

**Goal**: Make `_stream_to_file` fail loudly when (a) the downloaded byte count doesn't match `Content-Length`, or (b) the downloaded file is bgzipped and lacks the canonical 28-byte EOF marker. Failed verification removes the partial file and raises a clear exception. (The smarter download strategy that wraps this with resume-on-stall lives in W1.5.)

**TDD steps**:

- **RED**: in `tests/integration/test_fetch.py` (host-runnable; uses pytest-httpserver):
  - `test_fetch_refuses_when_content_length_mismatch` — httpserver advertises `Content-Length: 100`, sends 50 bytes, closes cleanly. Fetcher must raise `TruncatedDownload` and remove the partial file.
  - `test_fetch_refuses_when_bgzip_eof_marker_missing` — httpserver streams a `.vcf.bgz`-named file that's missing the 28-byte tail. Fetcher must raise `IncompleteBgzip` and remove the partial file.
  - `test_fetch_accepts_clean_bgzip_with_eof_marker` — happy path with the canonical 28-byte tail; succeeds, file present.
  - `test_fetch_skips_eof_check_for_non_bgzip` — `.txt` or `.md5` files don't get the bgzip check (we'd false-fail otherwise); only `.vcf.bgz` / `.vcf.gz` / `.bcf` extensions trigger it.
- **GREEN**: in `prep/fetch.py`:
  - Capture `bytes_so_far` and `Content-Length` in `_stream_to_file`'s return path (currently throws away `total`).
  - After the read loop, if `total is not None and bytes_so_far != total`: delete `dest_path`, raise `TruncatedDownload(url, expected=total, got=bytes_so_far)`.
  - For files matching `(*.vcf.bgz, *.vcf.gz, *.bcf)` suffix, after the size check, read the trailing 28 bytes and compare against the canonical bgzip EOF marker. Mismatch → delete + raise `IncompleteBgzip(path)`.
  - Both exceptions defined in `prep/fetch.py`; surfaced through `cli.py`'s existing fetch error path.
- **REFACTOR**: extract the EOF-marker constant + check into a small `_verify_bgzip_eof_marker(path)` helper for reuse by the doctor's integrity sweep (W2).

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY.
- `packages/toolkit/tests/integration/test_fetch.py` — MODIFY (4 new tests).

**Gate**: 4 new tests pass on host venv; existing fetch tests still pass.

**Dependencies**: none.

---

### W1.5 — Smarter download: stall detection + Range-based resume + bounded retries *(critical, ~3 hours)*

**Status**: ✅ **Shipped via rich-cli Phase 3** (2026-05-12 / 2026-05-13). See [completed/rich-cli/](../../../completed/rich-cli/).

**Goal**: Wrap `_stream_to_file` (now integrity-verified by W1) with a retry-and-resume layer. A stalled connection no longer nukes a multi-hour download; an interrupted transfer picks up at the offset where it left off via HTTP `Range: bytes=<offset>-`. Each successful resume terminates in W1's integrity verification — incomplete bytes never reach the consumer.

The W3 re-fetch is ~38 GB across 5 files over home broadband; even a single transient blip mid-transfer currently means starting over from byte 0. With this, blips are recoverable.

**Design**:

- **Stall detection**: per-chunk socket read timeout via `urllib.request.urlopen(req, timeout=N)`. Default `N = 30s` (a normal home-broadband stall is sub-second; 30s is "the connection is dead, not slow").
- **Resume semantics**: on stall / connection error, the loop captures `bytes_so_far`, sleeps for `min(2 ** attempt, 30)` seconds (exponential backoff capped at 30s), then issues a new `urllib.request.Request(url, headers={"Range": f"bytes={bytes_so_far}-"})`. Opens the local file in append mode and continues writing.
- **HTTP-200-on-Range fallback**: if the server returns HTTP 200 instead of 206 (Partial Content) on a Range request, the server doesn't support resume. Truncate the local file, restart from byte 0. Count it as a retry.
- **Bounded retries**: `max_retries = 5` per file. After 5 failed attempts, raise `DownloadStalled(url, bytes_so_far, last_error)` and remove the partial file. (5 × 30s backoff caps stalled-recovery time at ~150s wall before giving up.)
- **Integrity gate on success**: after the read loop exits cleanly on the final attempt, run W1's `_verify_bgzip_eof_marker` + Content-Length check. If they fail post-resume, that's *integrity*, not *transport* — raise immediately without further retries (a server feeding wrong bytes won't fix itself).
- **MD5 across resumes**: the incremental MD5 in `_stream_to_file` *must not* be reset on resume — it has to hash the existing on-disk bytes when restarting an in-progress download. Refactor MD5 into a "compute over the final on-disk file" helper rather than accumulate-during-stream, or seed the accumulator from the on-disk partial file before re-entering the loop. (Decided at GREEN time; the second approach is cheaper.)

**TDD steps**:

- **RED**: in `tests/integration/test_fetch.py` (extending W1's pytest-httpserver suite):
  - `test_fetch_resumes_after_mid_stream_stall` — httpserver advertises 1000 bytes, sends 500, holds the connection open without writing. Wrapper should time out, reconnect with `Range: bytes=500-`, receive the remaining 500 bytes (the server's next handler returns 206 + tail), pass integrity. Final file is 1000 bytes; reconnect was visible in httpserver logs.
  - `test_fetch_restarts_when_server_ignores_range` — httpserver always returns HTTP 200 (ignores Range). After first stall + retry, the wrapper detects HTTP 200 on a Range request, truncates the local file, and restarts from byte 0. Single retry consumed from budget.
  - `test_fetch_gives_up_after_max_retries` — httpserver stalls forever. Wrapper retries `max_retries` times with backoff, then raises `DownloadStalled`. Partial file removed.
  - `test_fetch_resume_preserves_md5_across_attempts` — partial-then-resumed download produces the same MD5 as a clean one-shot download of the same bytes. (Catches the "MD5 was reset on resume" regression class.)
  - `test_fetch_resume_runs_integrity_on_final_success` — happy-path resume completes; the post-resume bytes are short relative to `Content-Length`; wrapper raises `TruncatedDownload`, not "success". (Defends the principle that integrity is the success criterion, not the read-loop exit.)
- **GREEN**: in `prep/fetch.py`:
  - Extract the current chunked-read loop into a private `_attempt_stream(url, dest_path, *, byte_offset, md5_accumulator, timeout, progress_callback) -> bytes_so_far` helper.
  - New public wrapper `_stream_to_file_with_resume(...)` that wraps `_attempt_stream` in the retry loop. The existing `_stream_to_file` becomes a thin shim that calls the resume-capable version with `max_retries=0` for back-compat in the MD5-sidecar path (sub-MB files don't need resume).
  - New exception `DownloadStalled` in `prep/fetch.py`'s `__all__`.
  - On entry, if `dest_path` exists with a partial size, seed `md5_accumulator` by re-hashing the on-disk bytes, then resume from the existing size. Only do this if the caller opted in (a new `resume_partial: bool = False` kwarg, defaulting to False to preserve `INV-D001`'s no-silent-overwrite contract). The `--all` / large-file path opts in.
- **REFACTOR**: factor the backoff-sleep helper out for unit testing; default 30s timeout configurable via `GENOMECLAW_FETCH_TIMEOUT` env var (handy for the integration tests).

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY.
- `packages/toolkit/tests/integration/test_fetch.py` — MODIFY (5 new tests).

**Gate**: 5 new tests pass on host venv; W1's tests still pass (resume layer doesn't break the non-resume case); ruff clean.

**Dependencies**: W1 done (resume depends on integrity verification being the success criterion).

---

### W2 — Doctor-side integrity sweep across staged references *(complement to W1, ~1 hour)*

**Status**: ✅ **Shipped as `genomeclaw refs verify`** during the rich-cli migration. The command runs the bgzip EOF-marker check across every staged reference file; the user's 2026-05-13 run reports `All 26 bgzipped files intact.` Note this landed as a `refs` subcommand rather than as a `doctor` extension — the rich-cli structure made the `refs` group the natural home for reference-integrity verification.

**Goal**: Extend integrity-verification surface to run the bgzip EOF-marker check across every staged reference file. Reports per-file status alongside the existing "reference present" check. Catches truncation that pre-dated the W1 fix (i.e. the project owner's current layout) and reports it as a partial-reference fault.

**TDD steps**:

- **RED**: extend `tests/integration/test_doctor.py`:
  - `test_doctor_reports_truncated_reference_file` — stage a fake `clinvar.vcf.gz` missing the EOF marker under `tmp_path/reference/...`; doctor exits non-zero; report contains an `integrity` entry listing the offending file with status `truncated`.
- **GREEN**: in `prep/doctor.py`, after the existing reference-present check, walk each reference file's tail-28-bytes and classify. Add the result to the doctor's JSON output structure under `reference_integrity` (one row per file). Render as `✓ ... OK` / `✗ ... TRUNCATED` in the text report.
- **REFACTOR**: reuse `_verify_bgzip_eof_marker` from W1.

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` — MODIFY.
- `packages/toolkit/tests/integration/test_doctor.py` — MODIFY (1 new test).

**Gate**: ✅ — running `bin/genomeclaw refs verify` against the project owner's current layout reports `All 26 bgzipped files intact.` as of 2026-05-13.

**Dependencies**: W1 done (provides the `_verify_bgzip_eof_marker` helper).

---

### W3 — Re-fetch the 5 truncated gnomAD chrom files *(unblocks W4, ~3–6 hours wall time)*

**Status**: ✅ **Effectively done 2026-05-13** — `bin/genomeclaw refs verify` confirms all 26 bgzipped reference files intact (the truncated chr6/7/9/10/11 were re-fetched implicitly as part of the resumable-fetcher rich-cli landing).

**Goal**: Replace the 5 truncated gnomAD-exomes chrom files with clean downloads using the now-correct fetcher (W1).

**Procedure**:
1. With W1 + W2 landed, run `bin/genomeclaw refs verify` to confirm the 5 truncated files are flagged.
2. For each of chr6, chr7, chr9, chr10, chr11: invoke `bin/genomeclaw refs fetch --source gnomad-exomes --release v4.1 --chroms <one>`.
3. Re-run `bin/genomeclaw refs verify` — all 24 gnomad-exomes chrom files (and the other 2 bgzipped reference sources) should now report OK.

**Sizes to expect** (from upstream gnomAD v4.1 docs): chr6 ≈ 8.32 GB, chr7 ≈ 7.8 GB, chr9 ≈ 6.6 GB, chr10 ≈ 7.0 GB, chr11 ≈ 8.5 GB. Total re-download ≈ 38 GB. At typical home-network speeds (~50 MB/s), wall time is ~13 minutes for chr6 alone — could be 1–2 hours total, dominated by network throughput.

**Gate**: ✅ `refs verify` reports 26/26 OK (2026-05-13).

**Dependencies**: W1 + W2 done.

---

### W4 — dbSNP RefSeq → UCSC chr-rename *(unrelated bug, blocks parity check anyway, ~1 hour)*

**Status**: ✅ **Shipped 2026-05-13** in commit 1f58aeb. `_DBSNP_REFSEQ_TO_UCSC_MAP` (25 contigs: chr1–22 + X + Y + M) + `_stage_dbsnp_with_cache` (persistent cache keyed on source_sha + rename_map_text; one-time ~30 min rename amortises across runs) + generalised `_stage_with_chr_rename` (parameterised over (source, rename_map)) all in [annotate_vcfanno.py:115-141, 649-751](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py). Test coverage in [test_annotate_vcfanno.py](../../../../packages/toolkit/tests/integration/test_annotate_vcfanno.py): `test_annotate_vcfanno_overlays_all_three_sources` (asserts `dbsnp_rsid=rs1` in output INFO), `test_invD001_annotate_vcfanno_does_not_mutate_reference_files` (verifies dbSNP source SHA256 unchanged), `test_annotate_vcfanno_caches_renamed_dbsnp_across_runs` (verifies persistent caching).

**Goal**: Wire a dbSNP-specific contig rename at staging time, mirroring the ClinVar one. Without this, 0 `dbsnp_rsid` annotations are produced.

**TDD steps**:

- **RED**: in `tests/integration/test_annotate_vcfanno.py`:
  - `test_annotate_vcfanno_renames_dbsnp_refseq_to_ucsc` — synthetic dbSNP fixture with `NC_000001.11` contigs gets staged with `chr1` contigs; the resulting `annotated.vcf` has at least one `dbsnp_rsid=` annotation against a synthetic input record at chr1.
  - `test_annotate_vcfanno_dbsnp_source_unchanged_after_rename` — `INV-D001`: SHA256 of the dbSNP source file is identical before and after the run.
- **GREEN**: extract `_stage_clinvar_with_chr_rename` into parameterised `_stage_with_chr_rename(source, scratch, *, rename_map)`. Apply with two maps:
  - ClinVar map: existing `1 → chr1` etc.
  - dbSNP map: `NC_000001.11 → chr1`, `NC_000002.12 → chr2`, …, `NC_000022.11 → chr22`, `NC_000023.11 → chrX`, `NC_000024.10 → chrY`, `NC_012920.1 → chrM`.
- **REFACTOR**: `_CLINVAR_TO_GRCH38_CHR_MAP` constant becomes `_CHR_RENAME_MAPS = {"clinvar": ..., "dbsnp": ...}`. Per-source staging selects the right map.

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py` — MODIFY.
- `packages/toolkit/tests/integration/test_annotate_vcfanno.py` — MODIFY (add 2 tests).

**Gate**: 2 new tests pass in-image; existing 7 tests still pass; ruff clean.

**Dependencies**: independent of W1/W2/W3. Can ship in parallel.

---

### W5 — Pre-flight annotation schema validator *(defence-in-depth, ~2 hours)*

**Status**: ⏸ **Pending but non-blocking**. W7 (the parity check W5 was meant to defend) passed without it on 2026-05-13. The validator remains valuable as a future guard against overlay-source regressions (new dbSNP release with different contig naming, gnomAD INFO field renames, etc.) — exactly the class of issue that caused the 2026-05-12 W4 attempted-failure. The provisional `INV-R-pre-flight` invariant is deliberately held for a separate later promotion pass (per the 2026-05-13 thorough revision direction).

**Goal**: Before any vcfanno invocation, walk each overlay source's VCF header and assert: (a) every declared `field` in our config is present in `##INFO=<ID=...>` lines, AND (b) at least one contig in the input VCF is reachable in the source's tabix index. Fail in <1s with a clear per-source error rather than after 30+ min of vcfanno chewing.

**TDD steps**:

- **RED**: new `tests/integration/test_annotate_preflight.py`:
  - `test_preflight_passes_when_all_fields_present`
  - `test_preflight_refuses_missing_info_field` — synthetic source missing one declared field → `AnnotationSchemaMismatch(source, missing_fields)`
  - `test_preflight_refuses_unreachable_contigs` — input contigs are UCSC, source contigs are RefSeq, no rename configured → `AnnotationContigMismatch(source)`
  - `test_preflight_runs_before_run_vcfanno` — invariant: monkey-patched `run_vcfanno` call count is 0 when pre-flight raises
- **GREEN**: new `prep/annotate_preflight.py` exposing `validate_annotation_sources(configs, input_vcf)`. Called from `annotate_vcfanno()` immediately after `build_vcfanno_toml(configs)` and before `run_vcfanno(...)`.
- **REFACTOR**: extract exception classes (`AnnotationSchemaMismatch`, `AnnotationContigMismatch`) into `prep/annotate_preflight.py`'s `__all__`.

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_preflight.py` — CREATE.
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py` — MODIFY (call validator).
- `packages/toolkit/tests/integration/test_annotate_preflight.py` — CREATE.

**Gate**: 4 new tests pass; integration with `annotate_vcfanno` doesn't regress its existing tests.

**Dependencies**: W4 done (so the validator can verify both rename paths).

---

### W6a — Adopt `rich` for inline CLI progress + tabular output *(quality-of-life, ~3 hours)*

**Status**: ✅ **Shipped via rich-cli plan** (2026-05-12 / 2026-05-13) — at much larger scope than this work item originally contemplated. The full CLI was migrated to Typer + rich + structured NDJSON; `genomeclaw <group> <verb>` is the canonical form. See [completed/rich-cli/](../../../completed/rich-cli/).

**Goal**: Replace per-line `print(f"  {bytes_so_far}/{total} @ rate")` updates with inline-redrawn progress bars in the fetcher. Render `doctor`'s output as a `rich.table.Table`. Render `pipeline`'s phase banners as `rich.panel.Panel`s. The `--fetch-all` run goes from "hundreds of newline-flooded progress lines" to "one bar per file that updates in place + an overall progress bar". The `doctor` output goes from plain text to a structured table. Non-TTY contexts (CI logs, piped stdout) degrade gracefully to periodic frame updates without ANSI escapes — rich's `Console` handles this automatically.

**Scope boundary (deliberate)**:
- ✅ Fetcher progress bars (single-file + overall when running `--fetch-all`)
- ✅ Doctor's text-rendered output → `rich.table` (the JSON output via `--json` stays unchanged — that's machine-readable contract)
- ✅ Pipeline's `=== pipeline: <phase> ===` banners → `rich.panel`
- ❌ NOT converting `logging.basicConfig` to `RichHandler` — the orchestrators' `log.info` lines stay on the existing stderr handler so test capture (`caplog`) stays simple
- ❌ NOT touching the stable `print(f"wrote {path}")` contract output that shells / other tools may parse — those stay as plain `print`
- ❌ NOT rendering error / warning messages with rich — they stay as `print(..., file=sys.stderr)` so they remain greppable

**Design**:

- New `prep/_console.py` exposing a module-level `Console` instance from `rich.console.Console()` (auto-detects TTY). All rich-rendered output goes through this single console — never construct `Console()` ad hoc.
- Fetcher uses `rich.progress.Progress` with two columns: per-file bar (one row per source) + overall bar (total bytes across all files in the release set). The existing `_PROGRESS_INTERVAL_SEC` (currently 2s line-per-line updates) becomes the bar's refresh interval — rich already throttles at 10 Hz by default, so we can remove our own throttle and let rich handle it.
- A `progress_callback: Callable[[int, int | None], None]` parameter on `_stream_to_file_with_resume` (from W1.5) lets the fetcher push byte updates to rich's `Progress.update(...)` without `prep/fetch.py` knowing about rich directly. (Loose coupling; testable; the fetcher's pure-stream logic stays library-quality.)
- `doctor.py:render_text` produces a `rich.table.Table` printed via the module console instead of joining lines.
- `cli.py:_run_pipeline`'s `log.info("=== pipeline: <phase> ===")` becomes `console.print(Panel(f"phase {N}/{total}: <phase>", border_style="cyan"))` between phases (still also logs via `log.info` for the timestamped record).

**Dependency**: add `rich>=13.0` to `[project.dependencies]` in `packages/toolkit/pyproject.toml`. uv resolves; existing CI workflow re-syncs.

**TDD steps**:

- **RED**: in a new `tests/integration/test_console_rendering.py`:
  - `test_console_singleton_is_tty_aware` — module-level `Console` reports `is_terminal=True` under `force_terminal=True` and `is_terminal=False` when output is captured. (Defends "rich degrades correctly off-TTY".)
  - `test_doctor_text_render_includes_table_for_reference_block` — running `doctor()` with a populated layout and rendering via the new `render_text` produces output containing the expected source / release / status columns. Assert by row count + cell content, not by exact ANSI byte layout (which is unstable).
- **RED**: in `tests/integration/test_fetch.py` (extending W1's suite):
  - `test_fetch_progress_callback_receives_byte_updates` — pass a recording callback into `_stream_to_file_with_resume(..., progress_callback=cb)`; assert it was called multiple times with monotonically-increasing `bytes_so_far`.
  - `test_fetch_can_run_without_progress_callback` — same call with `progress_callback=None`; succeeds; no `AttributeError`.
- **GREEN**:
  - New `prep/_console.py` with the singleton `Console` instance.
  - `prep/fetch.py:_stream_to_file_with_resume` gains the `progress_callback` kwarg (Optional[Callable]). On chunk write, calls `callback(bytes_so_far, total)` if non-None.
  - `prep/fetch.py:fetch` wraps the per-file loop in a `with Progress(...) as progress:` block. Passes a `progress.update(task_id, completed=bytes_so_far)`-shaped callback per file.
  - `prep/doctor.py:render_text` re-implemented around `rich.table.Table`. The JSON output via `--json` is untouched.
  - `cli.py:_run_pipeline` adds the panel banners alongside the existing `log.info` calls.
  - Add `rich>=13.0` to `pyproject.toml`; regenerate `uv.lock`.
- **REFACTOR**: nothing structural; the new `_console` module is the seam for all future rich integration (so when 4D-and-later want a tree-rendered annotation summary, the entry point already exists).

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_console.py` — CREATE.
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY (callback hook + Progress block).
- `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` — MODIFY (`render_text` → rich.table).
- `packages/toolkit/src/genomeclaw_toolkit/cli.py` — MODIFY (pipeline panel banners).
- `packages/toolkit/pyproject.toml` — MODIFY (add `rich>=13.0`).
- `packages/toolkit/uv.lock` — MODIFY (resolved).
- `packages/toolkit/tests/integration/test_console_rendering.py` — CREATE (2 tests).
- `packages/toolkit/tests/integration/test_fetch.py` — MODIFY (2 new callback tests).
- `packages/toolkit/tests/integration/test_doctor.py` — MODIFY (text-render structure assertions; the JSON-mode tests stay unchanged).

**Gate**: ✅ — running `bin/genomeclaw refs fetch --all` shows inline progress bars (one per file + overall); `bin/genomeclaw refs verify` / `bin/genomeclaw host doctor` show rich-rendered tables. Final implementation (rich-cli plan) is broader than the W6a scope (full CLI rewrite to Typer + structured NDJSON output).

**Dependencies**: W1.5 done (provides the `progress_callback` hook in the resume-capable streamer).

---

### W6 — Vcfanno stderr noise filter + redirect-to-file *(cosmetic, ~1 hour)*

**Status**: ⏸ **Pending but likely obsolete**. The original W6 motivation was 120M `bix.go:251: chromosome chrN not found in chrM.vcf.bgz` warnings drowning real errors, plus 50% wall-time overhead from the per-line `sys.stderr.write+flush` pattern. The 1f58aeb per-chrom shard pattern eliminated the bix.go noise structurally — each shard's vcfanno only queries the matching gnomAD-exomes file, so the cross-chrom not-found warnings drop to ~zero. The 1h59m real-data wall on 4.87M variants suggests the stderr overhead is also no longer material. The old `Popen + readline + sys.stderr.write + flush` pattern is still in [_vcfanno.py:136-150](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_vcfanno.py#L136-L150) but isn't causing observed harm. Verify (run the project owner's pipeline + count stderr lines + measure wall time) before deciding whether to close W6 as obsolete or to ship the planned filter.

**Goal**: Stop draining vcfanno's stderr through the Python wrapper's `Popen + per-line sys.stderr.write + flush` pattern (~50% overhead + drowns real errors in noise). Replace with: subprocess-level redirect to a file in the scratch dir, plus a tailing thread that classifies lines into (noise, signal) and forwards only signal lines to the parent stderr. Surface a one-line summary count of suppressed noise. The full unfiltered log lives on disk for forensics.

**TDD steps**:

- **RED**: in `tests/integration/test_vcfanno.py`:
  - `test_run_vcfanno_writes_full_stderr_to_file` — shim writes mixed lines; assert the full file contains all of them.
  - `test_run_vcfanno_filters_chromosome_not_found_noise_from_parent_stderr` — shim writes 30 `bix.go:251: chromosome chr1 not found in chr10.vcf.bgz` lines + one `Error: real error`; parent stderr captures `Error:` + a `[vcfanno noise suppressed: 30 chromosome-not-found lines]` summary; assert the bix.go noise does NOT appear on parent stderr.
- **GREEN**: refactor `_vcfanno.py:run_vcfanno`:
  - subprocess stderr → file (`stderr=open(stderr_path, "w")` in scratch).
  - separate tail thread reads the file in real time, classifies each line, forwards signal lines to `sys.stderr`, accumulates noise counts.
  - on subprocess exit, drain remaining tail + write summary.
  - on non-zero exit, read last N lines of the file for the `VcfannoError` message.
- **REFACTOR**: line-classifier helper for future filters.

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vcfanno.py` — MODIFY.
- `packages/toolkit/tests/integration/test_vcfanno.py` — MODIFY (add 2 tests).

**Gate**: 2 new tests pass; existing 5 tests still pass; the W7 real-data run produces clean parent-stderr output dominated by signal.

**Dependencies**: none.

---

### W7 — Resume W4 (ClinVar parity check)

**Status**: ✅ **Passed 2026-05-13 in commit 1f58aeb**. Real-data outcome: **42,885 / 42,885 ClinVar matches (+0.00% delta vs. Phase-4A baseline)** on the project owner's Nebula VCF (4.87M variants, 1h59m end-to-end wall on consumer hardware). The original "± 1% of 42,885" gate (later softened to "documented and explainable") was met exactly. Notably this passed **without W5 (pre-flight validator) or W6 (stderr discipline) shipping** — W4 (dbSNP rename) + the per-chrom shard pattern were sufficient.

**Procedure used**: full pipeline ingest → normalize → annotate (with W4-shipped dbSNP rename + per-chrom shards) → materialize on the project owner's Nebula CRAM + VCF.

**Gate**: ✅ count is documented and explainable.

**Dependencies (historical)**: W1, W1.5, W2, W3, W4 ✅ shipped.

---

## Dependency graph (2026-05-13 update)

```
W1 ✅ ──→ W1.5 ✅ ──→ W2 ✅ ──→ W3 ✅ ──┐                  (reference-data thread; closed via rich-cli)
                                        │
                       W6a ✅ ──────────┤                  (UX thread; closed via rich-cli)
                                        │
W4 (dbSNP rename) ──→ W5 (pre-flight) ──┼──→ W7 (parity)   (active)
                                        │
W6 (vcfanno stderr) ────────────────────┘                  (active)
```

- **Reference-data thread**: ✅ closed via rich-cli Phase 3 + `refs verify`. All 26 bgzipped reference files intact as of 2026-05-13.
- **UX thread**: ✅ closed via rich-cli — at much larger scope than W6a originally contemplated.
- **Annotation-correctness thread**: W4 → W5 → W7 ⏳ active.
- **Stderr-discipline thread**: W6 stands alone ⏳ active.

## Suggested session breakdown — remaining work

| Session | Items | Est. wall time | Notes |
|---------|-------|----------------|-------|
| ~~1~~ | ~~W1 + W1.5 + W2~~ | ✅ shipped via rich-cli |
| ~~3~~ | ~~W6a~~ | ✅ shipped via rich-cli (broader scope) |
| ~~4~~ | ~~W3~~ | ✅ effectively done — `refs verify` confirms 26/26 OK |
| 2 | W4 + W6 | ~2 hours | dbSNP rename (in-image, needs_bio) + vcfanno stderr discipline (host-runnable). Independent — could split. |
| 5 | W5 | ~2 hours | Pre-flight annotation schema validator. Promotion of `INV-R-pre-flight` is **deliberately deferred** out of the 2026-05-13 revision pass; the validator still ships but the invariant promotion is a separate later edit. |
| 6 | W7 | ~1 hour | Real-data parity check on project owner's Nebula VCF; gate softened to "documented and explainable" per the 2026-05-13 revision. |

**Total remaining active time**: ~5 hours; wall time dominated by session 6's pipeline run (~30 min active + ~1.5 h compute).

---

## Open questions (resolved at 4C.4 close)

1. **Should we keep the 24-blocks-per-chrom gnomAD vcfanno config or shard by input chromosome?** Defer until W3 + W7 land. If W7 completes cleanly with the current config, leave it; if W7 still has performance / correctness issues, shard. (The original chr4-position failure was attributed to chr6 truncation upstream — if W7 also fails, the per-chrom layout is the next suspect.)
2. **Promote the two provisional invariants?** `INV-D-fetch-integrity` is well-supported by 4C.4's empirical findings — propose at close. `INV-R-pre-flight` is more speculative — let 4D (VEP) demonstrate it before promoting.
3. **Backfill the colima/virtiofs tripwire note in cram-scratch-strategy's work-notes?** Worth doing once 4C.4 closes — record that the chr6 EOF surfaced after heavy I/O against an externally-fetched gnomAD layout, and that the fix is fetcher integrity rather than scratch architecture.

---

## Completion criteria

- [x] W1 — fetcher Content-Length + bgzip EOF verification ✅ shipped via rich-cli Phase 3.
- [x] W1.5 — fetcher resume-on-stall via Range requests + bounded retries ✅ shipped via rich-cli Phase 3.
- [x] W2 — `refs verify` integrity sweep ✅ shipped via rich-cli Phase 4; flags truncated files. Note: landed under the `refs` command group rather than `doctor`.
- [x] W3 — chr6/chr7/chr9/chr10/chr11 re-fetched; `refs verify` reports 26/26 OK as of 2026-05-13.
- [x] W4 — dbSNP RefSeq-accession contigs renamed; 3 covering tests pass in `test_annotate_vcfanno.py`. ✅ 2026-05-13 (1f58aeb).
- [ ] W5 — pre-flight validator. **Non-blocking** — W7 passed without it; still valuable as a future guard.
- [ ] W6 — vcfanno stderr filtered + full log on disk. **Likely obsolete** — per-chrom shard pattern resolved the noise; verify before closing.
- [x] W6a — `rich` integration ✅ shipped via the rich-cli plan (broader scope than W6a originally contemplated).
- [x] W7 — ClinVar match-count parity check passed: **42,885 / 42,885 (+0.00%)** on the project owner's Nebula VCF. ✅ 2026-05-13 (1f58aeb).
- [ ] [phase-4-completion.md](phase-4-completion.md) updated to reflect 1f58aeb-shipped state.
- [ ] `INV-D-fetch-integrity` promotion to [INVARIANTS.md](../../../reference/INVARIANTS.md) — **deliberately deferred** out of the 2026-05-13 revision pass (held for a separate later promotion alongside `INV-R-pre-flight`).
- [ ] This sub-plan retired (moved into Phase-4 work-notes or deleted).

---

## What happens after 4C.4 closes

The 4C.4 gate (W7 ClinVar parity) ✅ passed 2026-05-13. The path forward inside Phase 4 is **the remaining 4D/4E tail**: needs_bio integration tests for the already-implemented `annotate_vep.py` orchestrator (the [phase-4-completion W5 tests](phase-4-completion.md#w5--sub-phase-4d-vep--loftee--alphamissense-implementation-12-sessions)); the first real-data VEP smoke under the 4-hour budget; and the small `gene_loeuf` materialize-time join. After Phase 4 closes, the next major phase is **Phase 5 — host service + plugin migration to `registerTool` + sandbox image**.

The 4C.4 hardening (fetcher integrity check via `refs verify` + bgzip EOF marker enforcement + generalised chr-rename + persistent caching) carries forward — 4D's reference fetches already use the same fetcher. The `INV-D-fetch-integrity` promotion (when it lands in a later revision pass) will mean 4D's VEP cache fetches inherit the same correctness guarantee retroactively.

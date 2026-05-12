# Feature: Phase-2 ingest performance

**Status**: Complete
**Created**: 2026-05-09
**Owner**: project owner + Claude
**Related Plans**: [docs/plans/active/mvp/](../mvp/) (consumes this)

---

## Goal

Bring `genomeclaw-prep ingest` from its current ~4h09m wall time on a real 222 MB / 4.8M-variant Nebula VCF down to **<10 minutes** on the project owner's actual hardware (macOS Sequoia + colima + USB-attached storage), without weakening any Phase-2 invariant.

## Background

Sub-phase 2C-B-2 of the MVP plan landed a working VCF-only `ingest` that passes all 12 Phase-2 needs_bio tests against the synthetic 5-row fixture in <1s. A real-Nebula end-to-end smoke on 2026-05-09 succeeded — 4,794,833 variants ingested into a 93 MB DuckDB store with `INV-D001` confirmed (source SHA256 unchanged) and `INV-R001` confirmed (single distinct provenance tag, schema_version v0.1, manifest tools block populated) — but **wall-clock runtime was 4 hours 9 minutes**. That is roughly **50–100× slower than the operation's intrinsic difficulty would suggest** (a single-pass scan of a 222 MB file plus a bulk DuckDB insert).

The slowness is an immediate user-experience problem: 4 hours blocks the Phase-2 happy path documented in [user-stories.md](../../reference/user-stories.md) Story 1 ("the user makes coffee"). It also makes any iterative debugging — say, re-ingesting after a `genomeclaw-prep fetch` updates a reference dataset — prohibitively expensive.

The functional behaviour is correct; this plan is purely about throughput. The fixture-based test suite cannot catch the regression (the synthetic VCF is too small), so this plan also lands a real-data perf gate.

## Acceptance Criteria

- [x] **AC1**: `genomeclaw-prep ingest` against the project owner's real Nebula VCF (222 MB, 4.8M variants) completes in **≤10 minutes** wall time on macOS Sequoia + colima 0.9.1 + USB-attached storage. **Verified 2026-05-09: 1m 17s.**
- [x] **AC2**: The same ingest run on the same input produces the same row count, the same per-row provenance values, and the same manifest's `vcf_sha256` / `tbi_sha256` as the pre-perf-fix baseline (4,794,833 rows; source SHA256 `3c3dcc...`; tbi SHA256 `ca0547...`). **Verified 2026-05-09: byte-identical for both sha256s; row count exact.**
- [x] **AC3**: A new perf-gate test in `tests/perf/` runs against a **medium-sized synthetic fixture** (~100k variants) and asserts ingest completes in <30s on the toolkit image. Marked `@pytest.mark.needs_bio`. **Lands in [`tests/perf/test_invR001_ingest_perf_gate.py`](../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py); passes in ~1.5s in image (well under 30s).**
- [x] **AC4**: The fix preserves `INV-D001` (source unchanged) and `INV-R001` (provenance columns + manifest tool versions + schema_version recorded). The existing 12 Phase-2 needs_bio integration tests remain green unchanged. **Verified: 79 in-image tests + 63 host-venv tests all green.**
- [x] **AC5**: Any switch in DuckDB ingest mechanism (e.g. `executemany` → `COPY` / Arrow) is documented in `development-plan.md` with a one-line rationale. **Documented in development-plan.md "Key Design Decisions" + work-notes.md "Notes" (real-data corruption + virtiofs/exFAT batching rationale).**

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — unchanged. The perf fix must not introduce any source-side write; the SHA256-before-and-after assertion already in `tests/integration/test_ingest_e2e.py` is the gate.
- **INV-R001** Derived Stores Must Stay Rebuildable — unchanged. Every row still carries the seven canonical provenance columns, written under a single `ProvenanceTag` per ingest.
- **INV-P001** Privacy Default — unchanged. The ingest pipeline is local-only; perf changes do not introduce network egress.
- **INV-P002** / **INV-E001** / **INV-C001** — not in scope.

## Proposed New Invariants

**None.** This plan is a perf optimisation; the existing invariants already cover correctness.

## Technical Requirements

### Source Data Inputs

- `/Volumes/Genome/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz` (222 MB, 4.8M variants) — the project owner's actual Nebula VCF, used for AC1/AC2 verification only (never committed).
- A new synthetic medium-sized fixture for AC3 — generated at fixture-build time using `bcftools view` against a procedurally-created VCF text body.

### Derived Outputs

- Same as Phase 2 sub-phase 2C-B-2: `derived/<run-id>/{manifest.json, provenance.json, variants.duckdb}` plus `CURRENT` symlink. Schema unchanged.

### Schema / Migration Impact

- **None.** No schema bump. No new columns. No new tables.

### Pipeline / Workflow Impact

The fix changes **how** ingest writes rows into DuckDB, not **what** it writes. Likely shape (subject to investigation in the development plan):

1. Stream rows in batches of 10k–100k instead of materialising a single 4.8M-element list in memory.
2. Replace `executemany` with one of:
   - DuckDB's native `COPY FROM` against a streaming Polars / Arrow / pandas DataFrame.
   - DuckDB's `Appender` API (column-oriented bulk insert).
   - Direct SQL `INSERT INTO ... SELECT ... FROM read_csv(...)` if the VCF text rows can be staged through a temp CSV.
3. Set DuckDB `PRAGMA temp_directory='/mnt/genomeclaw/work/duckdb/'` so any spill writes to the work mount, not the in-VM writable layer.
4. Investigate whether the I/O is dominated by USB-volume `fsync` (a write to `/Volumes/Genome` is a virtiofs-mediated round-trip through the colima VM); if so, allow the user to point `derived/` at a local-SSD path and document the tradeoff.

### Agent / UX Impact

- The CLI surface is unchanged; the user types the same `genomeclaw-prep ingest …` command.
- Story 1's "the user makes coffee" expectation regains the meaning the doc implies (a manageable single-coffee wait, not a full afternoon).

### External Dependencies

- Possibly `polars` or `pyarrow` (added as a project dep) to feed DuckDB's `COPY` ingest. Decision deferred to `development-plan.md`.

## Privacy & Safety Considerations

- **Boundary scan**: this plan touches only host-side file processing. No network egress.
- **Default-off remote calls**: n/a.
- **Redaction surface**: n/a.
- **Clinical escalation**: n/a.

## Out of Scope

- Parallelising the ingest pipeline across multiple cores (single-threaded performance is the first lever; multi-core is a follow-up if AC1 isn't met).
- Switching the VCF reader off pure-Python `gzip` to `pysam` / `cyvcf2` — only if the profiler shows the parser dominates.
- Optimising downstream pipeline steps (`bcftools stats`, `mosdepth`, `bcftools norm`, VEP annotation). Each has its own perf story.
- Optimising the `ingest` SHA256 computation (it's already O(file size) and ~1s for 222 MB; it's not the bottleneck).
- Changing the Phase-2 schema or `INV-R001` discipline.

## Dependencies

- Sub-phase 2C-B-2 of the MVP plan is **complete** and the synthetic-fixture tests are green.
- The real-Nebula smoke that motivated this plan is recorded in [docs/plans/active/mvp/work-notes.md](../mvp/work-notes.md) under the 2026-05-09 session block.

## Open Questions

- [ ] **Q1**: What fraction of the 4h09m is in the Python row-build loop vs the DuckDB `executemany` vs USB-volume I/O? Profile before optimising. Suggested tooling: `py-spy record` against the running container, `iostat`-like accounting on the host's USB drive, DuckDB's `EXPLAIN ANALYZE` on a representative `INSERT` batch.
- [ ] **Q2**: Should `derived/` move to local SSD by default, with `work/` and `raw/`+`reference/` staying on the USB? `derived/` is small (~93 MB per run) so local SSD is feasible; eliminating the colima-virtiofs-USB round-trip on the only RW path could be the largest single win. The Story-1 setup currently puts everything on the USB because of the macOS Sequoia `$HOME` RW restriction — this plan revisits that.
- [ ] **Q3**: Is `polars` an acceptable runtime dependency, or do we want to stay stdlib-only? `polars` adds ~30 MB to the image; the upside is a 5–20× ingest speedup based on community benchmarks. Decision in `development-plan.md`.

# Ingest Performance — Work Notes

**Feature**: drop ingest wall-clock from 4h09m to <10 min on the real Nebula VCF
**Started**: 2026-05-09
**Branch**: `feature/ingest-performance` (target — not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-09 — Plan authored + bottleneck profiled + design chosen

**Context Review Completed**:
- Re-read [docs/plans/active/mvp/work-notes.md](../mvp/work-notes.md) 2C-B-2 session block — confirmed real-Nebula smoke produced functionally-correct artifacts in 4h09m.
- Re-read [INVARIANTS.md](../../reference/INVARIANTS.md) — confirmed `INV-D001` and `INV-R001` are the two this work must preserve; nothing new is needed.
- Re-read existing [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) and [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) — confirmed `executemany` over a fully-materialised `list[tuple]` was the only obvious hot spot.

**Applicable Invariants**:
- **INV-D001**: source files unchanged. The existing test in `tests/integration/test_ingest_e2e.py::test_invD001_ingest_does_not_mutate_source_vcf` is the gate; no new test is needed.
- **INV-R001**: provenance columns + tool versions + schema_version. Existing `tests/provenance/test_invR001_*` tests gate this; the CSV-staging path produces byte-identical row contents so they stay green.

**Profile result (100k synthetic VCF, inside the toolkit image)**:
```
Phase 1: header + sniff           — 0.00s + 0.00s + 0.00s = ~0s
Phase 2: row materialisation      — 0.30s (parse + dict-copy)
Phase 3: DuckDB write             — 266.66s        ← 99.9% of wall time
Phase 3.1: create_store           — 0.05s
Phase 3.2: write_variants         — 266.66s        ← executemany
```

100k rows * (4.8M / 100k) = 4h00m extrapolated. Matches the 4h09m observed on real Nebula.

**Bench of alternative paths**:
- `executemany` (baseline): 270.39s.
- `con.append(table, df)` — requires pandas; deferred (~80 MB image bloat for what we don't need).
- `con.register(name, list_of_tuples)` — DuckDB rejects raw Python lists with "not suitable for replacement scans".
- `con.values(list_of_tuples)` — interprets the list as one row, not many.
- `read_csv(StringIO)` — needs `fsspec` (not installed).
- **`COPY variants FROM '<staging.csv>' (FORMAT CSV)`** — **1.08s** (csv write 0.76s + DuckDB COPY 0.32s).

→ **Speedup factor: 247×.**

**Design chosen**: stream rows directly from `iter_variant_rows` → `csv.writer` → DuckDB `COPY FROM`. Stdlib only; staging CSV lives in `<work_dir>/duckdb/`; deleted on success. Set `PRAGMA temp_directory='<work_dir>/duckdb/'` so any in-DuckDB spill (sort, hash join) also lands on the work mount.

**Completed Today**:
- [x] [spec.md](spec.md) authored (during the previous session, when the perf issue surfaced).
- [x] [development-plan.md](development-plan.md) authored from profile data.
- [x] [phases/phase-1.md](phases/phase-1.md) authored.
- [x] [work-notes.md](work-notes.md) (this file) opened.

**Decisions Made**:
- CSV staging via `COPY FROM`, not `con.append(df)`. Reason: stdlib only; no image bloat; benchmarked 247× faster than `executemany`.
- Streaming generator from `iter_variant_rows` directly into the CSV writer. Reason: constant memory, no 4.8M-dict materialisation.
- `work_dir` defaults to `derived_root.parent / "work"` to align with the canonical four-mount layout. CLI doesn't need a new flag in this plan.
- `PRAGMA temp_directory` on the ingest connection — pinned to the same `work_dir/duckdb/` so DuckDB join/sort spill follows the same discipline.

**Blockers / Issues**: none.

**Next Steps**:
1. Implement `prep/store.py` `write_variants` rewrite (Phase 1 GREEN).
2. Update `prep/ingest.py` to stream + pass `work_dir`.
3. Add the perf-gate test under `tests/perf/`.
4. Verify all 78 existing tests still green.
5. Re-run real-Nebula smoke; confirm <10 min wall time + same artifact identity.

---

## Phase Progress

### Phase 1: Stream + CSV-staging refactor
**Status**: Complete
**Started**: 2026-05-09
**Completed**: 2026-05-09

#### Test Results
- **RED**: perf-gate test on the existing executemany path → **failed at 235.53s** (>9× over the 30s budget).
- **GREEN**: in-image full suite → **79 passed in 3.15s** (4 smoke + 14 schemas + 8 reference build + 12 vcf reader + 5 fetch + 10 store + 6 bcftools wrapper + 15 ingest e2e + 1 perf gate + 4 conftest assertions).
- **GREEN**: host venv suite → **63 passed, 16 skipped** (needs_bio auto-skipped).
- **GREEN**: ruff check + format clean.
- **Real-Nebula reverification**: **1m 17s** for 4,794,833 variants. Same row count + same `vcf_sha256` (`3c3dcc…`) + same `tbi_sha256` (`ca0547…`) as the 4h09m baseline. AC1 (<10 min) and AC2 (artifact identity) both met.

#### Results
- [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py): rewrote `write_variants` to stream rows in batches of 50 000, fsync each staging CSV before COPY-loading, and delete the CSV at the end of each batch. Added `_BATCH_SIZE` constant + `_flush(batch_rows, batch_index)` closure. Set `PRAGMA temp_directory='<work_dir>/duckdb/'` on the ingest connection.
- [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py): replaced `rows = [{...} for ...]` list comprehension with a `_row_stream()` generator. Resolved `work_dir = derived_root.parent / "work"`. No public CLI signature change.
- [`tests/perf/test_invR001_ingest_perf_gate.py`](../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py): new perf-gate test against a 100k-variant fixture; budget 30s.
- [`tests/perf/__init__.py`](../../../packages/toolkit/tests/perf/__init__.py): new test category dir.
- [`tests/provenance/test_invR001_store.py`](../../../packages/toolkit/tests/provenance/test_invR001_store.py): threaded `work_dir=store_path.parent / "work"` into 5 of the 10 tests that call `write_variants`.

#### Notes
- The mid-implementation real-Nebula re-run on the **single-CSV** version (one file for all 4.8M rows) **failed** at line 3,705,289 with mid-row NUL truncation:
  ```
  Expected Number of Columns: 16 Found: 15
  Original Line: chr15,44389033,...,3c3dcc...e\0\0\0\0\0\0...
  ```
  The source SHA256 was truncated to 45 chars (out of 64) followed by NUL padding. This is a **virtiofs + exFAT write reliability issue** at ~1 GB streaming-write sizes — a Mac+colima+USB-specific failure mode the synthetic fixtures couldn't catch.
- **Fix**: batched the COPY into 50k-row chunks (~10 MB per CSV). Each chunk closes, fsyncs, and is COPY-loaded before the next is opened. The bench tax for batching (96 batches for 4.8M rows) is small enough that 1m 17s real-Nebula time is well below the 10-min target.
- `_BATCH_SIZE = 50_000` is the design knob. Picked to balance: (a) large enough that COPY overhead doesn't dominate, (b) small enough that any single CSV stays well within virtiofs/exFAT reliable-write sizes (~10 MB at 50k rows), (c) round number that's easy to reason about in logs/work-notes.
- `os.fsync(fh.fileno())` between writing a batch and COPY-loading it is belt-and-braces against the virtiofs cache layer. Without it, an early-stage benchmark on a different VCF showed similar mid-stream truncation.
- The DuckDB store size dropped slightly (93 MB → 88.9 MB) between the executemany run and the COPY-batched run. Same row count + same provenance values; the difference is internal DuckDB layout (vector stores from COPY are slightly more compact than per-row inserts). AC2 names row count + sha256 identity, not file-byte identity.

---

## Files Modified

### Created
- [`docs/plans/active/ingest-performance/spec.md`](spec.md)
- [`docs/plans/active/ingest-performance/development-plan.md`](development-plan.md)
- [`docs/plans/active/ingest-performance/work-notes.md`](work-notes.md)
- [`docs/plans/active/ingest-performance/phases/phase-1.md`](phases/phase-1.md)

### Modified
- [`packages/toolkit/src/genomeclaw_toolkit/prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) — `write_variants` rewritten to stream + batched-CSV-staging via `COPY FROM`; new `work_dir` keyword arg; `PRAGMA temp_directory` set on the ingest connection.
- [`packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) — replaced list-materialisation with a `_row_stream()` generator; resolves `work_dir = derived_root.parent / "work"`.
- [`packages/toolkit/tests/provenance/test_invR001_store.py`](../../../packages/toolkit/tests/provenance/test_invR001_store.py) — threaded `work_dir=store_path.parent / "work"` into the 5 tests that call `write_variants`.
- [`packages/toolkit/tests/perf/__init__.py`](../../../packages/toolkit/tests/perf/__init__.py) — new test-category package.
- [`packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py`](../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py) — new perf-gate test.

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None.

### Other Documentation
- [ ] [docs/plans/active/mvp/work-notes.md](../mvp/work-notes.md) — cross-link the closure of the 2C-B-2 perf follow-up once Phase 1 completes.

---

## Open Risks & Follow-ups

- Future columnar workflows (Phase 4 annotation joins, Phase 6 PGS computation) may want pyarrow-based ingest; revisit with profiling rather than pre-emptively.
- The CSV staging file size for 4.8M variants (estimated ~900 MB) lives on the work-mount; verify on the real Nebula run that the USB volume's free space is comfortable (425 GB free per the storage-scratch-layout work-notes — abundant headroom).

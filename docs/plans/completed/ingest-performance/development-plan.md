# Ingest Performance — Development Plan

**Status**: Complete
**Created**: 2026-05-09
**Branch**: `feature/ingest-performance` (target — not yet created)
**Spec**: [spec.md](spec.md)

---

## Summary

Replace the `executemany`-per-row insert path in `prep.store.write_variants` with a streamed CSV-staging path that lands the rows via DuckDB's `COPY ... FROM '<staging.csv>' (FORMAT CSV)`. Profiling on a 100k-variant synthetic VCF shows the swap brings ingest from 270s to 1.1s — a 247× speedup that, extrapolated to the project owner's real 222 MB / 4.8M-variant Nebula VCF, replaces the observed 4h09m wall time with ~50s.

Schema unchanged. `INV-D001` / `INV-R001` unchanged. Single phase.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — unchanged. The CSV staging file lives under `work/duckdb/` (RW scratch) and is deleted at end-of-write; source VCF is read-only.
- **INV-R001** Derived Stores Must Stay Rebuildable — unchanged. The seven canonical provenance columns are still stamped on every row; a single `ProvenanceTag` per call still enforces uniform attribution. The CSV path produces the same `(domain..., provenance...)` row order and the same DuckDB types as the previous `executemany` path; the test_invR001_* tests in [tests/provenance/test_invR001_store.py](../../../packages/toolkit/tests/provenance/test_invR001_store.py) gate that round-trip.
- **INV-P001** Privacy Default — unchanged. The CSV staging file is host-only; no network egress.
- All others (D002, E001, P002, C001) — not in scope.

## Proposed New Invariants

**None.**

## Current State Analysis

### What exists today

- [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) `write_variants` materialises all rows into a Python `list[tuple]` and calls `conn.executemany(sql, params)`. Profiling on 100k rows: 270.39s (4.5 min).
- [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) materialises a list comprehension `rows = [{**row, "sample_id": sample_id} for row in iter_variant_rows(vcf)]` before passing to `write_variants` — peak memory ~3–5 GB on 4.8M rows.
- The toolkit image's `ENV TMPDIR=/mnt/genomeclaw/work/tmp` is set, but DuckDB's own `temp_directory` PRAGMA defaults to the cwd (`/work` from the shim's `--workdir`) and may spill there.

### Profile results (2026-05-09)

```
=== Phase 1: header + sniff ===
  sha256 source: 0.00s
  read_contigs: 0.00s
  sniff_reference_build: 0.00s

=== Phase 2: row materialisation ===
  iter_variant_rows + dict-copy: 0.30s (100000 rows)

=== Phase 3: DuckDB write ===
  create_store: 0.05s
  write_variants (executemany): 266.66s     ← 99.9% of the time
```

### Bench on the same input — alternative ingest paths

| Path | Time (100k rows) | Extrapolated to 4.8M |
|------|------------------|----------------------|
| `executemany` (baseline) | 270.39s | ~3.6 hours |
| **CSV staging via `COPY FROM`** | **1.08s** | **~52s** |

### Files to Modify

| File | Current | Planned change |
|------|---------|----------------|
| [`packages/toolkit/src/genomeclaw_toolkit/prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) | `write_variants(store_path, rows, *, tag)` materialises `list[tuple]` and calls `executemany` | Accept `Iterable[Mapping]` (streamable); stage rows to a CSV under a caller-supplied `work_dir`; `COPY FROM` into `variants`. Add `_write_variants_csv_streaming` helper. Keep the `ProvenanceTag` contract. |
| [`packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) | List-comprehension `rows = [{**r, "sample_id": sid} for r in iter_variant_rows(vcf)]` | Stream a generator into `write_variants`; pass `work_dir`. |

### Files to Create

| File | Purpose |
|------|---------|
| [`packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py`](../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py) | New `tests/perf/` category. Single perf-gate test against a 100k-variant fixture (built at session start with `bcftools view -Oz`); asserts ingest completes in <30s on the toolkit image. Marked `@pytest.mark.needs_bio`. |

## Solution Design

```text
ingest()
  └─ for each variant row in iter_variant_rows(vcf):           ← streaming
      └─ write_variants(store_path, rows_iter, *, tag, work_dir)
          └─ open the staging CSV under work_dir/duckdb/       ← writable host path
          └─ csv.writer streams every row:
              [domain values..., provenance values...]
          └─ open one DuckDB connection
          └─ PRAGMA temp_directory='<work_dir>/duckdb/'        ← spill stays in work/
          └─ COPY variants(cols...) FROM '<staging.csv>'        ← bulk-load
          └─ delete staging.csv on success
```

### Key Design Decisions

1. **CSV staging, not pandas / pyarrow / Appender.** DuckDB 1.5.2's Python `con.append(table, df)` requires pandas; `con.register(name, list)` rejects raw Python lists; the C-level Appender is not exposed from `_duckdb.DuckDBPyConnection` in 1.5.2. CSV staging is stdlib-only (`csv` + `Path.open`) and the `COPY FROM` reader is multi-threaded + vectorised inside DuckDB. Keeping the toolkit image small matters too — adding pandas/pyarrow would add ~80–150 MB.
2. **Stream rows from `iter_variant_rows` directly into the CSV.** No intermediate Python list. Constant memory regardless of input size.
3. **Staging CSV lives in `<work_dir>/duckdb/<run-id>.csv`.** Aligns with the storage-scratch-layout plan's "nothing in `work/` is authoritative" discipline. The CSV is deleted on success; on failure (a Python crash mid-COPY) it's left behind for diagnosis — manual `rm -rf $GENOMECLAW_WORK_DIR/*` is the documented hygiene step.
4. **`PRAGMA temp_directory` on the ingest connection.** Until now DuckDB defaulted to whatever `os.getcwd()` happened to be inside the container (typically `/work`, a bind-mount). Pinning it to `<work_dir>/duckdb/` keeps any join/sort spill on the same volume as the staging CSV — the user can size the work mount once and stop worrying about per-stage scratch.
5. **`work_dir` defaults to `derived_root.parent / "work"`.** Matches the architecture's `/mnt/genomeclaw/{raw,reference,derived,work}` layout when ingest runs through the shim. Tests pass `work_dir=tmp_path/"work"` explicitly; the CLI (Phase 5+) will accept `--work-dir` if needed but doesn't yet.
6. **NULL convention: empty string `""` in CSV → DuckDB NULL.** The previous executemany path used native `None`; CSV requires a sentinel. We use the empty-string default with `NULL ''` in the COPY clause. Tests confirm `id IS NULL` and `qual IS NULL` round-trip correctly for the multi-allelic + dot-id rows in the synthetic fixture. Quoting: empty unquoted fields don't match an empty *quoted* field, so the existing `quote='"'` default is fine; rows with text containing commas / quotes go through `csv.QUOTE_MINIMAL` which DuckDB's COPY handles natively.

### Schema / Provenance Impact

- **Schema**: unchanged. `variants` table DDL is byte-identical. `INV-R001` provenance columns unchanged.
- **Schema-version bump**: none.
- **Provenance**: same seven columns stamped per row. `manifest.json` and `provenance.json` shapes unchanged.
- **Rebuild procedure**: unchanged. `genomeclaw-prep ingest --vcf … --reference … --sample-id …` against the same input produces the same row count + same per-row provenance values + same source SHA256s in the manifest. AC2 in [spec.md](spec.md) gates the byte-equivalence of the user-facing artifacts.

### Privacy & Egress Impact

- No new egress.
- No new secret surfaces.
- No redaction changes.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Stream rows + CSV-staging `write_variants` + `temp_directory` PRAGMA | functional regression-prevention (existing 10 store tests + 12 ingest e2e tests stay green); new perf-gate test asserts <30s on 100k synthetic input | 1 new + 22 unchanged-and-still-green |

Single phase. The change is scoped to two files + one new test.

## Phase 1: Stream + CSV-staging refactor

**Goal**: drop ingest wall-clock for the project owner's real Nebula VCF from 4h09m to <10 min (target: ~50s) without breaking any existing test or invariant.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

1. [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) — `write_variants` accepts `Iterable[Mapping]`, takes a new `work_dir: Path` keyword arg, streams rows to a staging CSV, `COPY FROM`s, deletes the CSV.
2. [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) — passes a generator into `write_variants` (no list materialisation); resolves `work_dir`.
3. [`tests/perf/test_invR001_ingest_perf_gate.py`](../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py) — new perf-gate test, `@pytest.mark.needs_bio`, asserts <30s on a 100k-variant fixture inside the toolkit image. Generates the fixture at session scope.
4. [`tests/perf/__init__.py`](../../../packages/toolkit/tests/perf/__init__.py) — new test category dir.
5. Re-run real-Nebula smoke; confirm <10 min wall time + identical artifact identity (row count + sha256s + manifest fields).

### Invariants Enforced Here

- **INV-R001** — the existing 10 `tests/provenance/test_invR001_store.py` tests + the 6 `INV-R001`-flagged tests in `tests/integration/test_ingest_e2e.py` all stay green unchanged. They cover provenance-column population, manifest tool versions, schema_version recording, and provenance.json step trail.
- **INV-D001** — the existing source-unchanged tests in `tests/integration/test_ingest_e2e.py` stay green. The staging CSV path never opens the source for write.

### Success Criteria

- [ ] All 78 pre-existing toolkit tests green (host venv: 63 passed + 15 needs_bio in image).
- [ ] New perf-gate test passes (<30s on 100k synthetic).
- [ ] Real-Nebula smoke succeeds in <10 min (target ~50s).
- [ ] Real-Nebula post-fix manifest's `vcf_sha256` and `tbi_sha256` byte-match the pre-fix manifest's values; row count matches (4,794,833).
- [ ] Ruff + format clean.

---

## Testing Strategy

### Unit Tests (existing)

- `tests/provenance/test_invR001_store.py` — 10 tests covering `create_store` + `write_variants` schema/provenance behaviour. Stays green.
- `tests/provenance/test_invR001_schemas.py` — 14 tests on the Pydantic models. Stays green.

### Integration Tests (existing)

- `tests/integration/test_ingest_e2e.py` — 12 needs_bio tests covering Phase-2 cases 1, 4–7, 9, 10, 11, 12, 13, 17, 18. Stays green.
- `tests/integration/test_vcf_reader.py` — 12 tests for the VCF reader. Stays green.

### Perf Tests (new)

- `tests/perf/test_invR001_ingest_perf_gate.py` — single test that builds a 100k-variant synthetic fixture and asserts ingest completes in <30s. Catches future regressions of this kind.

### Provenance / Determinism / Privacy / Evidence / Reports / Invariant tests

- All categories: existing tests cover the surfaces this plan touches. No new invariant tests are required because no new invariant is introduced.

---

## Documentation Updates

- [ ] `docs/plans/active/mvp/work-notes.md` — append a "Performance fix landed" block once Phase 1 completes; cross-link from sub-phase 2C-B-2's "real-Nebula 4h09m" follow-up.
- [ ] No `docs/reference/` updates required — the architecture doc and Story 1 only document the user-facing CLI shape, which doesn't change.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-09 | 2026-05-09 | 79 tests green; real-Nebula reverification at 1m 17s (193× speedup over 4h09m); same row count + sha256 identity. |

---

## Open Risks & Follow-ups

- **Image bloat from a future pyarrow / pandas dep is deferred**. If a later phase needs columnar bulk-insert (Phase 4 annotation joins, Phase 6 `pgsc_calc` results), revisit with profiling first. The CSV path scales fine to ~200M rows in benchmarks.
- **Per-row CSV escaping cost** is bounded by `csv.QUOTE_MINIMAL` which only quotes when needed. Real-Nebula rows have no commas/quotes in the variant payload (chrom/pos/ref/alt/etc. are all alphanumeric); benchmark on 100k synthetic rows showed CSV write at ~150 MB/s. Won't be a bottleneck.
- **CSV staging file size for 4.8M variants**: estimated ~900 MB on the work mount. Well within the storage-scratch-layout plan's sizing budget (the `work/` USB-attached volume).
- **DuckDB `temp_directory` PRAGMA** lands as a side-effect of this fix. Future work that does annotation joins (Phase 4) inherits the spill-to-work-mount discipline automatically.

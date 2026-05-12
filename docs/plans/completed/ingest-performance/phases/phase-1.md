# Phase 1: Stream + CSV-staging refactor

**Status**: In Progress
**Started**: 2026-05-09
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Replace the `executemany`-per-row insert path in `prep.store.write_variants` with a streamed CSV-staging path that lands rows via DuckDB's `COPY ... FROM '<staging.csv>' (FORMAT CSV)`. After this phase, ingest of the project owner's real 222 MB / 4.8M-variant Nebula VCF completes in <10 min wall time (target ~50s), with all existing tests green and the same artifact identity (row count + sha256s + manifest fields).

## Scope Boundaries

- **In scope**:
  - Rewrite [`prep/store.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) `write_variants` to stream from `Iterable[Mapping]`, stage to a CSV under `work_dir/duckdb/`, and `COPY FROM` it.
  - Set `PRAGMA temp_directory='<work_dir>/duckdb/'` on the ingest connection so DuckDB join/sort spill stays on the work mount.
  - Update [`prep/ingest.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) to pass a generator (not a list) into `write_variants`; resolve `work_dir` (default `derived_root.parent / "work"`).
  - Add [`tests/perf/test_invR001_ingest_perf_gate.py`](../../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py) — a perf-gate test against a session-scoped 100k-variant fixture, asserting <30s on the toolkit image. `@pytest.mark.needs_bio`.
  - Verify all 78 existing tests stay green.
  - Re-run real-Nebula smoke.

- **Out of scope**:
  - Adding pandas / pyarrow dependencies (deferred until profiling shows a future workflow needs them).
  - Multi-threading / parallelising the row stream (single-threaded should beat the perf target by 10×).
  - A `--work-dir` CLI flag (the default-via-derived-root works for the shim flow today; explicit flag can land later if needed).
  - The `bcftools_stats` / `mosdepth` integration (sub-phase 2C-C of the MVP plan).

## Invariants Enforced in This Phase

No new invariants. The phase **must keep** the following test gates green:

- **INV-D001** — `tests/integration/test_ingest_e2e.py::test_invD001_ingest_does_not_mutate_source_vcf` and `…_does_not_mutate_source_index` and `test_invD001_fetch_does_not_overwrite_existing_version` (already green; CSV-staging path doesn't open the source for write).
- **INV-R001** — the 10 tests in `tests/provenance/test_invR001_store.py` (provenance column population, schema_version, single-tag-per-write enforcement); the 6 `INV-R001`-flagged tests in `tests/integration/test_ingest_e2e.py` (manifest tool versions, provenance.json step trail, schema_version recorded).

The new perf-gate test in `tests/perf/` is structural (asserts a wall-clock budget), not invariant-flagged.

---

## TDD Steps

### Step 1.1 — RED: write the perf-gate test

Add [`tests/perf/test_invR001_ingest_perf_gate.py`](../../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py):

**Test cases**:

1. `test_ingest_100k_variants_completes_under_30s` — build a 100k-variant synthetic VCF at session scope (using `bcftools view -Oz` + `bcftools index --tbi`), run `ingest()` against it, assert wall time < 30s. Marked `@pytest.mark.needs_bio`.

This will currently fail because the existing `executemany` path takes ~270s on the same workload (>9× over budget).

After writing the test, **run it inside the image** and confirm it fails for the intended reason. Capture the output in [work-notes.md](../work-notes.md).

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,source=$(pwd)/packages/toolkit,target=/work \
  --workdir /work \
  --entrypoint pytest \
  -e GENOMECLAW_HAS_BIO=1 \
  genomeclaw/toolkit:dev \
  tests/perf/ -q
```

### Step 1.2 — GREEN: implement the CSV-staging refactor

**File 1 — [`prep/store.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py)**:

```python
def write_variants(
    store_path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    tag: ProvenanceTag,
    work_dir: Path,
) -> None:
    """Stream rows into the variants table via a CSV staging file + COPY FROM."""
    staging_dir = work_dir / "duckdb"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging = staging_dir / f"variants-{store_path.stem}.csv"
    provenance = (
        tag.source_path, tag.source_sha256, tag.tool, tag.tool_version,
        tag.params_json, tag.schema_version,
        tag.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )

    n_written = 0
    with staging.open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            try:
                domain = _coerce_variant_row(row)
            except ValueError:
                # Tear down the staging file so a partial CSV doesn't linger.
                fh.close()
                staging.unlink(missing_ok=True)
                raise
            w.writerow([
                "" if v is None else v for v in (*domain, *provenance)
            ])
            n_written += 1

    if n_written == 0:
        staging.unlink(missing_ok=True)
        return

    cols_sql = ", ".join(_DOMAIN_NAMES + list(PROVENANCE_COLUMNS))
    conn = duckdb.connect(str(store_path))
    try:
        conn.execute(f"PRAGMA temp_directory='{staging_dir}'")
        conn.execute(
            f"COPY variants ({cols_sql}) FROM '{staging}' "
            "(FORMAT CSV, HEADER FALSE, NULL '', QUOTE '\"', ESCAPE '\"')"
        )
    finally:
        conn.close()
        staging.unlink(missing_ok=True)
```

The signature change (`rows: Iterable[Mapping]` and the new `work_dir` keyword arg) is a **breaking change** to the existing 10 store tests in `tests/provenance/test_invR001_store.py`. They each call `write_variants(store_path, rows, tag=tag)` without `work_dir`. Adapt them to pass `work_dir=tmp_path / "work"` (the test conftest already sets up a tmp_path).

**File 2 — [`prep/ingest.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py)**:

```python
# Stream — no list materialisation.
def _row_stream():
    for row in iter_variant_rows(vcf):
        yield {**row, "sample_id": sample_id}

# Default work_dir to <derived_root.parent>/work — aligns with the
# canonical four-mount layout from the storage-scratch-layout plan.
work_dir = derived_root.parent / "work"
work_dir.mkdir(parents=True, exist_ok=True)

write_variants(store_path, _row_stream(), tag=tag, work_dir=work_dir)
```

The existing `ingest` signature does not change. The `work_dir` is resolved internally; tests don't need updating.

### Step 1.3 — REFACTOR

With everything green:

- Tighten `csv.writer` config — confirm `QUOTE_MINIMAL` is right for our rowshapes (the variant `id`/`ref`/`alt` fields are alphanumeric; `genotype` is `0/1`-ish; nothing should require escape).
- Add a docstring to `write_variants` that names the staging discipline.
- Re-run lint (`ruff check`, `ruff format --check`).
- Re-run the full host-venv suite + the in-image needs_bio sweep.

---

## Implementation Details

### Existing file changes — surface area

- `prep/store.py`: `write_variants` signature and body change. The `_VARIANT_DOMAIN_COLUMNS` tuple stays (it's the source of truth for the CSV column order). The `_coerce_variant_row` helper stays.
- `prep/ingest.py`: removes the list-comprehension materialisation; adds `work_dir` resolution.
- `tests/provenance/test_invR001_store.py`: 8 of the 10 tests need a `work_dir=tmp_path / "work"` keyword arg added to their `write_variants` calls. The store_path fixture stays.
- `tests/perf/__init__.py`: new (empty) package marker.
- `tests/perf/test_invR001_ingest_perf_gate.py`: new file with the single perf-gate test.

### CSV format / NULL convention

- Empty unquoted field → DuckDB NULL via `NULL ''`.
- Quoting: `csv.QUOTE_MINIMAL` (only quotes when the value contains a delimiter, quote, or newline). DuckDB's COPY default `QUOTE '"'` and `ESCAPE '"'` match.
- Line terminator: `\n` (lf-only). Cross-platform fine inside Linux containers.

### `temp_directory` PRAGMA scope

- Set on the same connection that runs `COPY FROM`. DuckDB applies it to all temp scratch needs of that connection (sort buffers, hash-join overflows, etc.). It does **not** affect the `variants.duckdb` file itself, which lives at `store_path` regardless.

### Edge Cases to Handle

- Empty `rows` (header-only VCF): no-op. The staging CSV is created and immediately deleted; no `COPY FROM` runs (which would otherwise error on an empty file).
- Mid-iteration `_coerce_variant_row` failure (a row missing a NOT NULL): close the file handle, delete the staging CSV, propagate the `ValueError`. The DuckDB store stays empty + valid. (This matches the existing `write_variants` behaviour where `_coerce_variant_row` raises before any DB write happens.)
- Staging path collision: name includes `store_path.stem` so concurrent ingests against different store files don't clobber each other's staging CSVs.

### Error Handling

- `bcftools_run` failures during indexing: unchanged.
- DuckDB COPY error: closes the connection, deletes the staging CSV, propagates the duckdb exception. The partial DuckDB file under `derived/<run-id>/` is left in place (the user can `rm -rf` the run dir if desired). Future plan can add a `--clean-on-failure` flag.

### Privacy / Egress Notes

- No new egress points.
- Staging CSV is host-only; same trust boundary as the `derived/` mount.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [`packages/toolkit/src/genomeclaw_toolkit/prep/store.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) | MODIFY | rewrite `write_variants` to use CSV staging + `COPY FROM`; new `work_dir` kwarg |
| [`packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) | MODIFY | stream into `write_variants`; resolve `work_dir` |
| [`packages/toolkit/tests/provenance/test_invR001_store.py`](../../../../packages/toolkit/tests/provenance/test_invR001_store.py) | MODIFY | thread `work_dir=tmp_path/"work"` into the 8 tests that call `write_variants` |
| [`packages/toolkit/tests/perf/__init__.py`](../../../../packages/toolkit/tests/perf/__init__.py) | CREATE | new test category package |
| [`packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py`](../../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py) | CREATE | perf-gate against 100k synthetic VCF |

---

## Verification

```bash
cd packages/toolkit

# Host venv (existing tests; needs_bio skipped)
uv run pytest -q
# Expect: 63+ passed, 16+ skipped (1 new perf-gate test joins the skip set on host)

# Inside the image (full suite, including perf-gate)
docker build --tag genomeclaw/toolkit:dev .
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,source=$(pwd),target=/work \
  --workdir /work \
  --entrypoint pytest \
  -e GENOMECLAW_HAS_BIO=1 \
  genomeclaw/toolkit:dev -q
# Expect: 79 passed (78 existing + 1 new perf-gate); perf-gate <30s

# Real-Nebula smoke (project owner's hardware)
bin/genomeclaw-prep ingest \
  --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
  --reference /mnt/genomeclaw/reference \
  --derived-root /mnt/genomeclaw/derived \
  --sample-id MPNRGLQ2K
# Expect: <10 min wall time; same row count + same vcf_sha256 as the pre-fix run.
```

---

## Completion Criteria

- [ ] `prep/store.py` `write_variants` rewritten to stream + CSV-stage + `COPY FROM`.
- [ ] `prep/ingest.py` updated to pass a generator + resolve `work_dir`.
- [ ] All 10 `tests/provenance/test_invR001_store.py` tests still pass after threading `work_dir`.
- [ ] All 12 `tests/integration/test_ingest_e2e.py` needs_bio tests still pass.
- [ ] New perf-gate test passes in <30s.
- [ ] Real-Nebula smoke completes in <10 min.
- [ ] Real-Nebula post-fix manifest matches pre-fix `vcf_sha256`, `tbi_sha256`, and row count.
- [ ] `ruff check` + `ruff format --check` clean.
- [ ] [work-notes.md](../work-notes.md) updated with RED/GREEN output + final verification result.
- [ ] Phase 1 status set to **Complete** in [development-plan.md](../development-plan.md).
- [ ] No follow-on phase needed (single-phase plan).

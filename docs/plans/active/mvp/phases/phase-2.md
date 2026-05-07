# Phase 2: Host CLI — ingest + reference fetch + minimal derived store

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Implement the first real pipeline operations: a `fetch` subcommand for downloading versioned reference and annotation data, and an `ingest` subcommand that takes a Nebula VCF, runs integrity checks, indexes it if needed, sniffs the reference build, and creates a minimal DuckDB derived store with full provenance metadata. Establish the `CURRENT` symlink convention that the host service (Phase 5) will use to resolve the active run.

After Phase 2: `genomeclaw-prep ingest` end-to-end works on a fixture VCF; `genomeclaw-prep fetch --source clinvar|gnomad|dbsnp` writes versioned reference data to `/mnt/genomeclaw/reference/`; `INV-D001` (source files unchanged) and the structural part of `INV-R001` (provenance columns + manifest tool versions) are enforced by tests. Normalization, annotation, and determinism-across-the-pipeline land in Phases 3–4; the test infrastructure for those is staged here so subsequent phases just drop tests in.

## Scope Boundaries

- **In scope**:
  - `genomeclaw-prep fetch --source clinvar|gnomad|dbsnp` — versioned downloads with checksum verification, written to `/mnt/genomeclaw/reference/<source>/<version>/`. Tests use a mocked HTTP backend; no real network in CI.
  - `genomeclaw-prep ingest --vcf <path> --reference <path> --sample-id <id>` — integrity checks (SHA256 verification), indexing if `.tbi` is missing (writing the index to `derived/`, **not** next to the source), reference-build sniffing from the VCF header, derived store creation.
  - DuckDB schema **v0.1**: a single `variants` table with the seven canonical provenance columns plus the VCF row data.
  - `manifest.json` per run: run identity, schema version, sample id, input identity (path + sha256), reference build, tool versions pinned.
  - `provenance.json` per run: append-only step-by-step trail (Phase 2 produces one step: `ingest`).
  - `CURRENT` symlink under `/mnt/genomeclaw/derived/`, atomically updated to point at the new run after `ingest` completes.
  - `INV-D001` and the structural part of `INV-R001` enforcement.
- **Out of scope**:
  - VCF normalization (left-align, split multi-allelics, canonical representation) — Phase 3.
  - Annotation against ClinVar / gnomAD / dbSNP via SnpEff + SnpSift — Phase 4.
  - PharmCAT haplotype calling — Phase 4.
  - The host service (FastAPI app reading the derived store) — Phase 5.
  - The plugin or any agent integration — Phase 5.
  - Findings, evidence, report tools — Phase 6.
  - Full pipeline-determinism test (will be added in Phase 3 once normalize is in place; Phase 2 only needs the test scaffolding).

## Invariants Enforced in This Phase

The two we can land structurally now. Others come online in later phases.

- **`INV-D001`** Raw genomic files source-of-truth — pipeline tests assert input VCF SHA256 + mtime are unchanged after `ingest`. The bcftools indexer is invoked with explicit `--output` pointing at `derived/<run-id>/` (never alongside the source). Reference and annotation downloads from `fetch` write to `reference/<source>/<version>/` paths and never touch a previously-versioned directory.
- **`INV-R001`** Rebuildability — every row in the derived `variants` table carries the seven canonical provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`). `manifest.json` pins `bcftools`, `python`, `duckdb`, and `genomeclaw-toolkit` versions. A determinism test stub asserts byte-equivalent output across two `ingest` runs on the same fixture (full determinism story extends through Phase 3 once normalize is part of the pipeline).

`INV-D002` (host-side only) is satisfied by the fact that this is a host CLI — it doesn't touch the sandbox image. `INV-P001` is satisfied because `fetch` is the only network egress in this phase, it's user-initiated, and it's deliberately scoped (no telemetry, no other outbound calls). `INV-E001` / `INV-P002` / `INV-C001` come online in Phases 5 and 6.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

Test cases by category, with the `INV-xxx` they enforce in the test name where applicable.

**Source-integrity tests** (`tests/invariants/`):

1. `test_invD001_ingest_does_not_mutate_source_vcf` — capture SHA256 of input VCF before `ingest`; rerun SHA256 after; assert equal.
2. `test_invD001_ingest_does_not_mutate_source_index` — same for the input `.tbi` if one exists.
3. `test_invD001_fetch_does_not_overwrite_existing_version` — populate `reference/clinvar/2026-04/`; running `fetch --source clinvar` for the same release version is a no-op (or refuses), never overwrites.

**Provenance tests** (`tests/provenance/`):

4. `test_invR001_variants_table_has_provenance_columns` — every row in `variants.duckdb` has all seven canonical columns populated (no NULLs).
5. `test_invR001_manifest_records_tool_versions` — `manifest.json` has `bcftools`, `python`, `duckdb`, `genomeclaw-toolkit` keys with non-empty version strings matching `^[0-9]+\.[0-9]+(\.[0-9]+)?` or similar.
6. `test_invR001_provenance_json_step_trail` — `provenance.json` has at least one step entry with `tool="genomeclaw-prep"`, `subcommand="ingest"`, input/output identities populated.
7. `test_invR001_schema_version_recorded` — `manifest.json` has `schema_version: "v0.1"`; the DuckDB store has a `schema_version` table or pragma matching.

**Determinism scaffolding** (`tests/determinism/`):

8. `test_ingest_byte_equivalent_on_rerun` — run `ingest` twice on the same fixture (clean derived dir between); the two `variants.duckdb` files compare byte-equivalent **modulo** declared non-determinism (we'll declare and document `created_at` as the only timestamp field; the test substitutes a fixed timestamp via env var or fixture). This is the scaffold; Phase 3 extends it.

**Integration tests** (`tests/integration/`):

9. `test_ingest_end_to_end_fixture` — given a tiny fixture VCF, `ingest` produces `derived/<run-id>/{manifest.json, provenance.json, variants.duckdb}` and updates `CURRENT`.
10. `test_ingest_indexes_unindexed_vcf_under_derived` — fixture VCF without `.tbi`; after `ingest`, the new `.tbi` is in `derived/<run-id>/` (not alongside the source).
11. `test_ingest_sniffs_grch38_reference_build` — fixture with GRCh38 contigs → manifest `reference_build_inferred = "grch38"`.
12. `test_ingest_refuses_ambiguous_reference_build` — fixture with mixed/unknown contigs → ingest errors with a clear message; no derived store written; `CURRENT` unchanged.
13. `test_ingest_refuses_when_raw_dir_missing` — clear error if `/mnt/genomeclaw/raw/` doesn't exist; no partial state.
14. `test_fetch_clinvar_writes_versioned_path_mocked` — mocked HTTP returning a tiny VCF + checksum; `fetch --source clinvar` writes to `reference/clinvar/<release>/clinvar.vcf.gz`; checksum verified.
15. `test_fetch_rejects_checksum_mismatch_mocked` — mocked HTTP returns content + wrong checksum; `fetch` errors; output path is not created.

**Run-ID + CURRENT symlink tests** (`tests/integration/`):

16. `test_run_id_format_iso_plus_hash` — generated run-id matches `^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[0-9a-f]{6}$`.
17. `test_current_symlink_atomic_update` — `CURRENT` points at the new run after a successful `ingest`; if `ingest` errors mid-run, `CURRENT` still points at the previous run (use a fixture that fails partway through; CURRENT must not be updated).
18. `test_current_symlink_initial_creation` — first `ingest` on an empty derived dir creates `CURRENT` correctly.

After writing the tests, **run them and confirm they fail for the intended reason**. Paste the failing output into [work-notes.md](../work-notes.md).

### Step 2.2 — GREEN: Minimal Implementation

Land the smallest set of code that turns the tests green.

**New module layout under `packages/toolkit/src/genomeclaw_toolkit/`:**

```text
prep/
├── __init__.py
├── fetch.py              # fetch subcommand: per-source download with checksum verification
├── ingest.py             # ingest subcommand: integrity check + index + sniff + materialize
├── store.py              # DuckDB derived-store creation + provenance-column writer
├── run_id.py             # run-id generation, CURRENT symlink atomic update
├── reference_build.py    # VCF-header-based reference build sniffer
└── _bcftools.py          # thin subprocess wrapper around bcftools (with version capture)

schemas/
├── __init__.py
├── manifest.py           # Pydantic model for manifest.json
└── provenance.py         # Pydantic model for provenance.json + provenance-column names
```

`cli.py` gets the `fetch` and `ingest` subparsers wired up to these modules. The Phase 1 placeholder subcommands become real.

**Key implementation choices**:

- **Run-ID format**: `{ISO 8601 UTC second}-{6-char hex}`, e.g., `2026-05-06T08-12-34Z-abc123`. Hex is the first 6 chars of SHA256(input_vcf_sha256 + ingest_start_timestamp_ns); deterministic given the same input + clock, but uniqueness across simultaneous runs is preserved by the timestamp.
- **CURRENT symlink atomic update**: `os.symlink(target, "CURRENT.tmp"); os.replace("CURRENT.tmp", "CURRENT")`. `os.replace` is atomic on POSIX same-filesystem renames. On error mid-run, `CURRENT.tmp` is cleaned up but `CURRENT` is untouched.
- **Reference-build sniffer**: parse `##contig=<...>` headers; compare contig names + lengths against a small built-in lookup (`{"grch38": {"chr1": 248956422, ...}}`). All-match → return build; partial match → ambiguous → fail. Lookup table is in `reference_build.py` with ~24 entries (autosomes + X/Y/MT) per build.
- **Provenance columns**: written by `store.write_variants(...)` which takes a Pydantic `ProvenanceTag` and stamps every row.
- **bcftools wrapper**: captures `bcftools --version` output once at startup and stores it in the manifest. Subprocess errors are surfaced with full stderr.
- **Fetch checksum verification**: each source has a known checksum file URL pattern. ClinVar publishes `clinvar.vcf.gz.md5` next to the VCF. We download both, verify, then move-into-place atomically.

### Step 2.3 — REFACTOR

With tests green:

- Tighten Pydantic models (`exact_optional_property_types=True` semantics; reject unknown fields on input).
- Replace any `print` calls with structured logging via `logging.getLogger(__name__)`.
- Confirm the bcftools subprocess wrapper's error path doesn't leak partial output paths into derived/ — clean up on failure.
- Run `ruff check` and `ruff format`. Re-run pytest after each change.

---

## Implementation Details

### Run-ID generation

```python
# packages/toolkit/src/genomeclaw_toolkit/prep/run_id.py
def generate_run_id(input_sha256: str, started_at: datetime) -> str:
    iso = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    h = hashlib.sha256(f"{input_sha256}:{started_at.timestamp_ns()}".encode()).hexdigest()[:6]
    return f"{iso}-{h}"
```

### CURRENT symlink atomic update

```python
def update_current_symlink(derived_root: Path, run_id: str) -> None:
    target = Path(run_id)  # relative; symlink resolves inside derived_root
    tmp = derived_root / "CURRENT.tmp"
    final = derived_root / "CURRENT"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, final)  # atomic on POSIX, same filesystem
```

### Provenance columns (DuckDB schema v0.1)

```sql
CREATE TABLE variants (
    -- VCF row data
    chrom         TEXT NOT NULL,
    pos           INTEGER NOT NULL,
    id            TEXT,
    ref           TEXT NOT NULL,
    alt           TEXT NOT NULL,
    qual          REAL,
    filter        TEXT,
    sample_id     TEXT NOT NULL,
    genotype      TEXT NOT NULL,    -- "0/0", "0/1", "1/1", "0|1", etc.
    -- Provenance (the canonical seven; INV-R001)
    source_path     TEXT NOT NULL,
    source_sha256   TEXT NOT NULL,
    tool            TEXT NOT NULL,
    tool_version    TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    schema_version  TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL
);

CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO schema_meta VALUES ('schema_version', 'v0.1');
```

For Phase 2 (pre-normalization), multi-allelic rows are stored as-is (one VCF row → one DuckDB row, possibly with comma-separated `alt`). Phase 3 splits them.

### `manifest.json` shape

```json
{
  "run_id": "2026-05-06T08-12-34Z-abc123",
  "schema_version": "v0.1",
  "sample_id": "<sample-id>",
  "input": {
    "vcf_path": "/mnt/genomeclaw/raw/<sample>/sample.vcf.gz",
    "vcf_sha256": "<64 hex>",
    "tbi_path": "/mnt/genomeclaw/raw/<sample>/sample.vcf.gz.tbi",
    "tbi_sha256": "<64 hex>",
    "reference_path": "/mnt/genomeclaw/reference/grch38/",
    "reference_build_inferred": "grch38"
  },
  "tools": {
    "bcftools": "1.20",
    "python": "3.11.x",
    "duckdb": "1.0.x",
    "genomeclaw-toolkit": "0.0.1"
  },
  "params": {},
  "outputs": {
    "derived_dir": "/mnt/genomeclaw/derived/2026-05-06T08-12-34Z-abc123/",
    "variants_table": "variants.duckdb"
  },
  "created_at": "2026-05-06T08:12:34Z"
}
```

### `provenance.json` shape

```json
{
  "run_id": "2026-05-06T08-12-34Z-abc123",
  "schema_version": "v0.1",
  "steps": [
    {
      "step": "ingest",
      "tool": "genomeclaw-prep",
      "tool_version": "0.0.1",
      "started_at": "2026-05-06T08:12:34Z",
      "completed_at": "2026-05-06T08:13:02Z",
      "inputs": [
        {"path": "/mnt/genomeclaw/raw/<sample>/sample.vcf.gz", "sha256": "<64 hex>"}
      ],
      "outputs": [
        {"path": "variants.duckdb", "sha256": "<64 hex>"}
      ],
      "params": {"sample_id": "<sample-id>"}
    }
  ]
}
```

Phases 3, 4 append additional steps (`normalize`, `annotate`, etc.) to this trail.

### Fixture VCFs

Tiny synthetic VCFs under `packages/toolkit/tests/fixtures/`. Three fixtures cover Phase 2:

- `tiny.vcf.gz` — 5 variants on chr1/chr17, GRCh38 contigs in header, indexed.
- `tiny-unindexed.vcf.gz` — same content, no `.tbi`. For the indexing test.
- `tiny-ambiguous.vcf.gz` — VCF with hand-edited contigs that match neither GRCh37 nor GRCh38 cleanly. For the refuse-ambiguous-build test.

**No real human genomic data in fixtures.** Synthetic only.

### Edge cases to handle

- Source `.vcf.gz` exists but is corrupted → bcftools error → ingest fails cleanly, no derived dir written, `CURRENT` unchanged.
- Source `.vcf` (uncompressed) → ingest fails with a clear message asking for bgzipped input. (Don't auto-bgzip; that would mutate the source.)
- Disk full mid-write → partial files cleaned up; `CURRENT` unchanged.
- `CURRENT.tmp` exists from a crashed prior run → replaced cleanly (it's our own scratch path).
- Run-id collision (extremely unlikely) → fail with a clear message; the user picks a different sample id or waits one second.

### Privacy / egress notes

- `ingest` is local-only. No network access of any kind.
- `fetch` makes HTTP/HTTPS requests to:
  - `ftp.ncbi.nlm.nih.gov` (ClinVar, dbSNP)
  - `storage.googleapis.com` (gnomAD, requester-pays-aware)
- Each fetch is a deliberate user invocation (a CLI flag, not a background task). Phase 2 does **not** add any automatic-update behavior.
- Tests use a mocked HTTP fixture (`pytest-httpserver` or similar) — no real network in CI.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | MODIFY | wire `fetch` and `ingest` subparsers to module entrypoints |
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | CREATE | per-source fetch implementation |
| `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` | CREATE | ingest pipeline orchestration |
| `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | CREATE | DuckDB derived-store creation; provenance-column stamping |
| `packages/toolkit/src/genomeclaw_toolkit/prep/run_id.py` | CREATE | run-id generation, CURRENT symlink update |
| `packages/toolkit/src/genomeclaw_toolkit/prep/reference_build.py` | CREATE | VCF-header reference-build sniffer |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py` | CREATE | thin subprocess wrapper around bcftools |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/manifest.py` | CREATE | Pydantic model for `manifest.json` |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/provenance.py` | CREATE | Pydantic model for `provenance.json`; provenance-column constants |
| `packages/toolkit/tests/integration/test_ingest_e2e.py` | CREATE | end-to-end ingest tests (cases 9–13, 17, 18) |
| `packages/toolkit/tests/integration/test_fetch_mocked.py` | CREATE | mocked fetch tests (cases 14, 15) |
| `packages/toolkit/tests/integration/test_run_id.py` | CREATE | run-id format test (case 16) |
| `packages/toolkit/tests/provenance/test_invR001_provenance_columns.py` | CREATE | provenance column enforcement (cases 4, 7) |
| `packages/toolkit/tests/provenance/test_invR001_manifest_versions.py` | CREATE | manifest tool-version test (case 5) |
| `packages/toolkit/tests/provenance/test_invR001_provenance_json.py` | CREATE | provenance.json step-trail test (case 6) |
| `packages/toolkit/tests/invariants/test_invD001_source_unchanged.py` | CREATE | source-immutability tests (cases 1, 2, 3) |
| `packages/toolkit/tests/determinism/test_ingest_byte_equivalent.py` | CREATE | determinism scaffolding (case 8) |
| `packages/toolkit/tests/fixtures/tiny.vcf.gz` | CREATE | tiny synthetic indexed VCF |
| `packages/toolkit/tests/fixtures/tiny.vcf.gz.tbi` | CREATE | tiny VCF index |
| `packages/toolkit/tests/fixtures/tiny-unindexed.vcf.gz` | CREATE | tiny VCF without index |
| `packages/toolkit/tests/fixtures/tiny-ambiguous.vcf.gz` | CREATE | tiny VCF with ambiguous reference build |
| `packages/toolkit/tests/conftest.py` | CREATE / MODIFY | shared test fixtures: `tmp_derived_root`, `tmp_raw_root`, `frozen_clock` |

---

## Verification

```bash
cd packages/toolkit

# Run Phase 2 tests
uv run pytest tests/integration/ tests/provenance/ tests/invariants/ tests/determinism/ -v

# Smoke run on the tiny fixture
uv run genomeclaw-prep ingest \
  --vcf tests/fixtures/tiny.vcf.gz \
  --reference /tmp/genomeclaw-test/reference/grch38/ \
  --sample-id test-sample-001

# Inspect the derived store
ls -la /tmp/genomeclaw-test/derived/CURRENT
cat /tmp/genomeclaw-test/derived/CURRENT/manifest.json
cat /tmp/genomeclaw-test/derived/CURRENT/provenance.json
duckdb /tmp/genomeclaw-test/derived/CURRENT/variants.duckdb \
  "SELECT chrom, pos, ref, alt, source_sha256, schema_version FROM variants LIMIT 5;"

# Mocked fetch (uses pytest-httpserver under the hood)
uv run pytest tests/integration/test_fetch_mocked.py -v

# Static checks
uv run ruff check .
uv run ruff format --check .

# Full toolkit suite (smoke + Phase 2)
uv run pytest -q
```

Expected outcomes:

- All 18 test cases above pass.
- `genomeclaw-prep ingest` produces a `CURRENT` symlink pointing at a new run-id with `manifest.json`, `provenance.json`, and `variants.duckdb`.
- `manifest.json` has all four tool versions populated; `provenance.json` has at least one `step: "ingest"` entry.
- `ruff check` passes.
- CI workflow runs green on a feature branch.

---

## Completion Criteria

- [ ] All 18 Phase 2 test cases pass (`tests/integration/`, `tests/provenance/`, `tests/invariants/test_invD001_*`, `tests/invariants/test_invR001_*` for the structural part, `tests/determinism/test_ingest_byte_equivalent.py`).
- [ ] `genomeclaw-prep ingest` works end-to-end on `tests/fixtures/tiny.vcf.gz` and updates `CURRENT` atomically.
- [ ] `genomeclaw-prep fetch --source clinvar|gnomad|dbsnp` works against a mocked HTTP backend; integration test confirms checksum-verified writes to `reference/<source>/<version>/`.
- [ ] `INV-D001` invariant tests (cases 1–3) verify source files (and previously-fetched reference dirs) are unchanged after pipeline runs.
- [ ] `INV-R001` invariant tests (cases 4–7) verify all seven provenance columns populated, manifest tool versions pinned, provenance.json step-trail present, schema-version recorded.
- [ ] Determinism scaffolding test (case 8) is in place — passes for `ingest`. Phase 3 will extend it through `normalize`.
- [ ] Static checks pass (`ruff check`, `ruff format --check`).
- [ ] No raw genomic data, secrets, or sample identifiers added to fixtures or repo (synthetic VCFs only).
- [ ] [work-notes.md](../work-notes.md) updated with the RED failing output, the GREEN diff summary, and the final test results.
- [ ] Phase 2 status set to **Complete** in [development-plan.md](../development-plan.md).
- [ ] [phases/phase-3.md](phase-3.md) authored before Phase 2 closes.

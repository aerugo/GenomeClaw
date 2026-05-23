# Phase 2: Host CLI — ingest + reference fetch + minimal derived store

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-09
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Implement the first real pipeline operations: a `fetch` subcommand for downloading versioned reference and annotation data, and an `ingest` subcommand that takes a Nebula VCF + BAM/CRAM, runs integrity checks, indexes the VCF if needed, sniffs the reference build, runs `bcftools stats` (writing the summary into `manifest.json`) and **`mosdepth`** (per-gene mean coverage materialized into a `coverage_qc` table; per [spec.md](../spec.md) Q7), and creates a minimal DuckDB derived store with full provenance metadata. Establish the `CURRENT` symlink convention that the host service (Phase 5) will use to resolve the active run.

After Phase 2: `genomeclaw-prep ingest` end-to-end works on a fixture VCF + BAM; `genomeclaw-prep fetch --source clinvar|gnomad|dbsnp` writes versioned reference data to `/mnt/genomeclaw/reference/`; `INV-D001` (source files unchanged, **including BAM/CRAM unchanged after `mosdepth`**) and the structural part of `INV-R001` (provenance columns + manifest tool versions including `bcftools stats` and `mosdepth` versions, plus `coverage_qc` provenance columns) are enforced by tests. Normalization, annotation, and determinism-across-the-pipeline land in Phases 3–4; the test infrastructure for those is staged here so subsequent phases just drop tests in.

## Scope Boundaries

- **In scope**:
  - `genomeclaw-prep fetch --source clinvar|gnomad|dbsnp` — versioned downloads with checksum verification, written to `/mnt/genomeclaw/reference/<source>/<version>/`. Tests use a mocked HTTP backend; no real network in CI.
  - `genomeclaw-prep ingest --vcf <path> --bam <path> --reference <path> --sample-id <id>` — integrity checks (SHA256 verification), indexing if `.tbi` is missing (writing the index to `derived/`, **not** next to the source), reference-build sniffing from the VCF header, derived store creation, **`bcftools stats` summary** written into `manifest.json`, **`mosdepth` per-gene mean coverage** materialized into the `coverage_qc` table.
  - DuckDB schema **v0.1**: a `variants` table with the seven canonical provenance columns plus the VCF row data, plus a new **`coverage_qc` table** (per Q7) with the seven canonical provenance columns.
  - `manifest.json` per run: run identity, schema version, sample id, input identity (path + sha256 for VCF and BAM), reference build, tool versions pinned (`bcftools`, `mosdepth`, `python`, `duckdb`, `genomeclaw-toolkit`), and a `qc.bcftools_stats` block.
  - `provenance.json` per run: append-only step-by-step trail (Phase 2 produces three steps: `ingest`, `bcftools-stats`, `mosdepth-coverage`).
  - `CURRENT` symlink under `/mnt/genomeclaw/derived/`, atomically updated to point at the new run after `ingest` completes.
  - `INV-D001` (now including BAM-immutability after `mosdepth`) and the structural part of `INV-R001` enforcement.
- **Out of scope**:
  - VCF normalization (left-align, split multi-allelics, canonical representation) — Phase 3.
  - Annotation via **VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno** — Phase 4 (per spec Q5; supersedes the original Q1 SnpEff plan).
  - Cyrius CYP2D6 outside-call (per spec Q6) — Phase 6.
  - `pgsc_calc` PRS computation (per spec Q8) — Phase 6.
  - Curated-notes (per spec Q9) — Phase 6.
  - PharmCAT haplotype calling — Phase 6.
  - The host service (FastAPI app reading the derived store) — Phase 5.
  - The plugin or any agent integration — Phase 5.
  - Findings, evidence tools — Phase 6.
  - Full pipeline-determinism test (will be added in Phase 3 once normalize is in place; Phase 2 only needs the test scaffolding).

## Invariants Enforced in This Phase

The two we can land structurally now, with their scope expanded by Q5/Q7 deliverables. Others come online in later phases.

- **`INV-D001`** Raw genomic files source-of-truth — pipeline tests assert input VCF SHA256 + mtime are unchanged after `ingest` (cases 1, 2). The bcftools indexer is invoked with explicit `--output` pointing at `derived/<run-id>/` (never alongside the source). Reference and annotation downloads from `fetch` write to `reference/<source>/<version>/` paths and never touch a previously-versioned directory (case 3). **`mosdepth` is invoked with read-only access to the BAM/CRAM** *(per spec Q7 + new test case 21)*: BAM and `.bai` SHA256 captured pre- and post-`ingest` and asserted equal.
- **`INV-R001`** Rebuildability — every row in the derived `variants` table carries the seven canonical provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`); the new `coverage_qc` table inherits the same seven columns *(test case 20)*. `manifest.json` pins `bcftools`, `mosdepth`, `python`, `duckdb`, and `genomeclaw-toolkit` versions, and includes a `qc.bcftools_stats` block with `ts_tv_ratio`, `n_snps`, `n_indels` *(test case 19)*. A determinism test stub asserts byte-equivalent output across two `ingest` runs on the same fixture (full determinism story extends through Phase 3 once normalize is part of the pipeline).

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

**Coverage + QC tests** *(per spec Q5 / Q7; added by [POC pipeline recommendations Phase 4](../../completed/poc-pipeline-recommendations/phases/phase-4.md))*:

19. `test_invR001_bcftools_stats_in_manifest` — `manifest.json` has a `qc.bcftools_stats` block with `ts_tv_ratio`, `n_snps`, `n_indels` keys; values are within sane ranges for the fixture (Ts/Tv ~2.0–2.1 genome-wide and ~3.0 in coding regions for a real WGS — the synthetic fixture's expected ranges are documented inline next to the assertion). Tests in `tests/provenance/test_invR001_bcftools_stats.py`.
20. `test_coverage_qc_table_populated` — after `ingest`, the `coverage_qc` table has **one row per gene in the BED that `mosdepth` was run against** (mosdepth emits a row per BED region whether covered or not). In the fixture, the BED is a small synthetic gene list (e.g., `BRCA1`, `BRCA2`, `CYP2D6`, plus a few others) so the fixture's `coverage_qc` table is small; **in production the BED is comprehensive (e.g., MANE Select) and the table is uncurated** per AC8 in [spec.md](../spec.md). Test assertions: `mean_depth` is a non-negative real on every row (uncovered fixture regions read 0); rows for genes the fixture's BAM actually covers have non-zero `mean_depth`; the seven canonical provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`) are populated on every row (`INV-R001`). Tests in `tests/integration/test_coverage_qc.py`.
21. `test_invD001_bam_unchanged_after_mosdepth` — capture BAM SHA256 before `ingest`; rerun SHA256 after; assert equal. Same for the BAM index (`.bai`) if present. The `mosdepth` invocation must use read-only access (`mosdepth -t 1 --no-per-base ...`); the test catches any accidental write. (`INV-D001`.) Tests in `tests/invariants/test_invD001_bam_unchanged.py`.

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
| `packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py` | CREATE | thin subprocess wrapper around bcftools (incl. `bcftools stats`) |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools_stats.py` | CREATE | runs `bcftools stats`, parses Ts/Tv + counts, writes `qc.bcftools_stats` block into `manifest.json` *(per spec Q5 / case 19)* |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_mosdepth.py` | CREATE | thin subprocess wrapper around `mosdepth`; per-gene mean coverage + low-coverage exon list; writes the `coverage_qc` table *(per spec Q7 / cases 20, 21)* |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/manifest.py` | CREATE | Pydantic model for `manifest.json` (incl. `qc.bcftools_stats` block) |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/coverage_qc.py` | CREATE | Pydantic model + DuckDB schema for the `coverage_qc` table |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/provenance.py` | CREATE | Pydantic model for `provenance.json`; provenance-column constants |
| `packages/toolkit/tests/integration/test_ingest_e2e.py` | CREATE | end-to-end ingest tests (cases 9–13, 17, 18) |
| `packages/toolkit/tests/integration/test_fetch_mocked.py` | CREATE | mocked fetch tests (cases 14, 15) |
| `packages/toolkit/tests/integration/test_run_id.py` | CREATE | run-id format test (case 16) |
| `packages/toolkit/tests/provenance/test_invR001_provenance_columns.py` | CREATE | provenance column enforcement (cases 4, 7) |
| `packages/toolkit/tests/provenance/test_invR001_manifest_versions.py` | CREATE | manifest tool-version test (case 5) |
| `packages/toolkit/tests/provenance/test_invR001_provenance_json.py` | CREATE | provenance.json step-trail test (case 6) |
| `packages/toolkit/tests/invariants/test_invD001_source_unchanged.py` | CREATE | source-immutability tests (cases 1, 2, 3) |
| `packages/toolkit/tests/invariants/test_invD001_bam_unchanged.py` | CREATE | BAM/`.bai` immutability after `mosdepth` (case 21) |
| `packages/toolkit/tests/integration/test_coverage_qc.py` | CREATE | `coverage_qc` table populated test (case 20) |
| `packages/toolkit/tests/provenance/test_invR001_bcftools_stats.py` | CREATE | `manifest.qc.bcftools_stats` test (case 19) |
| `packages/toolkit/tests/determinism/test_ingest_byte_equivalent.py` | CREATE | determinism scaffolding (case 8) |
| `packages/toolkit/tests/fixtures/tiny.vcf.gz` | CREATE | tiny synthetic indexed VCF |
| `packages/toolkit/tests/fixtures/tiny.vcf.gz.tbi` | CREATE | tiny VCF index |
| `packages/toolkit/tests/fixtures/tiny-unindexed.vcf.gz` | CREATE | tiny VCF without index |
| `packages/toolkit/tests/fixtures/tiny-ambiguous.vcf.gz` | CREATE | tiny VCF with ambiguous reference build |
| `packages/toolkit/tests/fixtures/tiny.bam` | CREATE | tiny synthetic BAM aligned to GRCh38; covers a few exons of `BRCA1`, `BRCA2`, `CYP2D6` so the `coverage_qc` test (case 20) has rows. **Synthetic only** — no real human reads. |
| `packages/toolkit/tests/fixtures/tiny.bam.bai` | CREATE | BAM index |
| `packages/toolkit/tests/conftest.py` | CREATE / MODIFY | shared test fixtures: `tmp_derived_root`, `tmp_raw_root`, `frozen_clock`, `tiny_bam_path` |
| `packages/toolkit/Dockerfile` | EXISTS (Phase-1.5 amendment) | multi-stage `genomeclaw/toolkit` image; bio binaries via bioconda + uv-installed Python toolkit |
| `packages/toolkit/.dockerignore` | EXISTS (Phase-1.5 amendment) | trims build context |
| `bin/genomeclaw-prep` | EXISTS (Phase-1.5 amendment) | host shim wrapping `docker run` against `genomeclaw/toolkit:dev`; falls back to `GENOMECLAW_NATIVE=1` for inner-loop dev |
| `.github/workflows/test.yml` | MODIFY | second job: `docker build` the toolkit image and run `pytest -m needs_bio` inside it |

---

## Verification

Per the development-plan.md "Toolkit + bioinformatics binaries packaged as a single Docker image" Decision Taken (2026-05-08): the bioinformatics binaries (`bcftools`, `mosdepth`, `samtools`) live inside the `genomeclaw/toolkit` image, not on the host's PATH. Phase 2 verification therefore builds the image once and runs the pipeline through it (or via the `bin/genomeclaw-prep` host shim).

```bash
cd packages/toolkit

# Build the toolkit image (used by everything below).
docker build --tag genomeclaw/toolkit:dev .

# Tool version sanity inside the image (per spec Q5/Q7).
docker run --rm --entrypoint bcftools genomeclaw/toolkit:dev --version | head -1   # expected ≥ 1.20
docker run --rm --entrypoint mosdepth genomeclaw/toolkit:dev --version              # expected ≥ 0.3.x

# Toolkit-side unit + integration tests (no bio binaries needed for unit /
# mocked-HTTP tests; they run against the host venv).
uv sync
uv run pytest tests/integration/ tests/provenance/ tests/invariants/ tests/determinism/ -v

# Pipeline smoke run via the host shim. Note all four canonical bind-mount
# env vars including GENOMECLAW_SCRATCH_DIR (per the cram-scratch-strategy
# plan, which superseded the original storage-scratch-layout plan and
# renamed work/→_scratch/ + GENOMECLAW_WORK_DIR→GENOMECLAW_SCRATCH_DIR) —
# bcftools sort -T, DuckDB temp_directory, and $TMPDIR all flow through
# _scratch/, never through the container's writable layer.
#
# All four host paths must be visible to the engine VM. Under the default
# colima profile that means under $HOME or under a path passed to
# `colima start --mount`. Paths under /tmp or /var/folders are NOT visible
# from a default colima profile — bind-mount errors there are the symptom.
mkdir -p ~/.genomeclaw-test/{reference/grch38,derived,_scratch}
GENOMECLAW_IMAGE=genomeclaw/toolkit:dev \
GENOMECLAW_RAW_DIR=$(pwd)/tests/fixtures \
GENOMECLAW_REF_DIR=~/.genomeclaw-test/reference \
GENOMECLAW_DERIVED_DIR=~/.genomeclaw-test/derived \
GENOMECLAW_SCRATCH_DIR=~/.genomeclaw-test/_scratch \
  ../../bin/genomeclaw-prep ingest \
    --vcf /mnt/genomeclaw/raw/tiny.vcf.gz \
    --bam /mnt/genomeclaw/raw/tiny.bam \
    --reference /mnt/genomeclaw/reference/grch38/ \
    --sample-id test-sample-001

# Inspect the derived store.
ls -la ~/.genomeclaw-test/derived/CURRENT
cat ~/.genomeclaw-test/derived/CURRENT/manifest.json | jq '.qc.bcftools_stats'
cat ~/.genomeclaw-test/derived/CURRENT/provenance.json
duckdb ~/.genomeclaw-test/derived/CURRENT/variants.duckdb \
  "SELECT chrom, pos, ref, alt, source_sha256, schema_version FROM variants LIMIT 5;"
duckdb ~/.genomeclaw-test/derived/CURRENT/variants.duckdb \
  "SELECT gene, mean_depth, source_sha256, tool, tool_version FROM coverage_qc LIMIT 10;"

# Mocked fetch (uses pytest-httpserver under the hood; pure-Python, runs
# against the host venv).
uv run pytest tests/integration/test_fetch_mocked.py -v

# Image-resident integration tests (the ones that need real bcftools /
# mosdepth) run inside the image with the test tree mounted in.
docker run --rm --user $(id -u):$(id -g) \
  --mount type=bind,source=$(pwd),target=/work \
  --workdir /work \
  --entrypoint pytest \
  genomeclaw/toolkit:dev \
  -m needs_bio -q

# Static checks (host venv).
uv run ruff check .
uv run ruff format --check .

# Full toolkit suite (smoke + Phase 2 host-runnable).
uv run pytest -q
```

**Tests that need real `bcftools` / `mosdepth`** are marked with the
`@pytest.mark.needs_bio` marker and are skipped on the host venv. They run
inside the `genomeclaw/toolkit` image and in CI's image-build job. Tests
that exercise pure-Python code paths (run-id, reference-build sniffer,
schemas, mocked fetch, manifest/provenance shape) run in either place.

**Scratch / temp routing** (per the now-completed [storage-scratch-layout plan](../../../completed/storage-scratch-layout/) and its successor the [cram-scratch-strategy plan](../../../completed/cram-scratch-strategy/) — which renamed `work/`→`_scratch/` and `GENOMECLAW_WORK_DIR`→`GENOMECLAW_SCRATCH_DIR`, and added the `shard_scratch(...)` / `atomic_promote(...)` primitives that Phase-4+ orchestrators inherit): the Phase-2 wrappers route all transient I/O through `/mnt/genomeclaw/scratch/` so a 30× WGS run never fills the engine VM's writable layer:

- `bcftools` subprocess wrappers pass `-T /mnt/genomeclaw/scratch/bcftools/sort.XXXX`
  (lazily `mkdir -p`'d on first call).
- DuckDB connections set `PRAGMA temp_directory='/mnt/genomeclaw/scratch/duckdb/'`
  on open so any annotation-join spill lands on the user's `_scratch/` volume.
- Anything that respects `$TMPDIR` (VEP, mosdepth, generic Python `tempfile`)
  picks up the image's `ENV TMPDIR=/mnt/genomeclaw/scratch/tmp` automatically.

Phase 4+ orchestrators allocate per-step shards via `shard_scratch(step, run_id, ...)` (a context manager, cleanup on `__exit__`, including on exception) and promote final artifacts via `atomic_promote(src, dst)` (copy + fsync + within-FS rename + fsync parent dir). Phase 6 extends the pattern to `pgsc_calc -work-dir /mnt/genomeclaw/scratch/pgsc_calc/<run-id>/`.

Expected outcomes:

- All 21 test cases above pass.
- `genomeclaw-prep ingest` produces a `CURRENT` symlink pointing at a new run-id with `manifest.json`, `provenance.json`, `variants.duckdb` (containing both `variants` and `coverage_qc` tables).
- `manifest.json` has all five tool versions populated (`bcftools`, `mosdepth`, `python`, `duckdb`, `genomeclaw-toolkit`); `qc.bcftools_stats` block carries `ts_tv_ratio`, `n_snps`, `n_indels`; `provenance.json` has `step: "ingest"`, `step: "bcftools-stats"`, and `step: "mosdepth-coverage"` entries.
- `coverage_qc` table populated with one row per gene in the fixture's gene list.
- BAM SHA256 unchanged after `mosdepth` (case 21).
- `ruff check` passes.
- CI workflow runs green on a feature branch.

---

## Completion Criteria

- [ ] All 21 Phase 2 test cases pass (`tests/integration/`, `tests/provenance/`, `tests/invariants/test_invD001_*`, `tests/invariants/test_invR001_*` for the structural part, `tests/determinism/test_ingest_byte_equivalent.py`, `tests/integration/test_coverage_qc.py`, `tests/provenance/test_invR001_bcftools_stats.py`, `tests/invariants/test_invD001_bam_unchanged.py`).
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

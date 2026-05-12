# Phase 3: Host pipeline — `normalize` + `materialize`

**Status**: Complete
**Started**: 2026-05-09
**Completed**: 2026-05-09
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-2.md](phase-2.md) (complete; ingest + reference fetch + minimal derived store; coverage_qc table; `INV-D001` + structural part of `INV-R001`)
**Authored**: Retroactively on 2026-05-09 from the implementation, tests, and [work-notes session block](../work-notes.md) of the same date. Phase 2's plan promised a "Phase 3 phase plan authored before Phase 2 closes" deliverable that was not produced at the time; this document closes that audit-trail gap.

---

## Objective

Layer two new orchestrators onto the Phase-2 derived store:

1. `genomeclaw-prep normalize <run-dir>` — wrap `bcftools norm` against the source VCF recorded in a Phase-2 `manifest.json`. Default behaviour is `bcftools norm -m-` (split multi-allelic rows into single-allelic rows). Optional `--reference-fasta <path>` enables left-alignment via `bcftools norm -f <ref>`; opt-in because the reference fasta is not part of the canonical Phase-2 reference dir (it lands with VEP in Phase 4). Writes `derived/<run-id>/normalized.vcf.gz` + `.tbi`. Updates `manifest.outputs.normalized_vcf` + `_sha256` + `_tbi_sha256`. Appends a `normalize` step to `provenance.json`.

2. `genomeclaw-prep materialize <run-dir>` — drop and recreate the `variants` table in `derived/<run-id>/variants.duckdb` from the normalized VCF (or from `annotated.vcf.gz` if Phase 4's annotate has run). The `coverage_qc` and `schema_meta` tables are preserved. Per-row `source_path` / `source_sha256` attribute to the **source-of-truth VCF** (recorded in `manifest.input`), not the intermediate `normalized.vcf.gz` — see [Decision 1](#decisions-taken) for the rationale. Appends a `materialize` step to `provenance.json`.

After Phase 3: the host pipeline runs end-to-end as `fetch → ingest → normalize → materialize`, with byte-stable per-row provenance and a row-equivalence determinism contract (see [Decision 3](#decisions-taken)).

The normalized VCF on disk is the canonical hand-off to downstream annotators (Phase 4 VEP / `bcftools annotate`); the variants-table refresh is a separate focused step that can be re-run alongside annotation updates without re-normalising.

## Scope Boundaries

- **In scope**:
  - `prep/_bcftools_norm.py` — thin subprocess wrapper around `bcftools norm`, mirroring the shape of the existing `_bcftools.py` / `_bcftools_stats.py` wrappers.
  - `prep/normalize.py` — orchestrator described above.
  - `prep/materialize.py` — orchestrator described above; uses `prep/store.py:write_variants` (extended in Phase 2 with CSV-staging for million-row scale) with a `work_dir` override so DuckDB's CSV staging lands on `_scratch/`, not `/tmp`. (At the time of original implementation `materialize` used `tempfile.TemporaryDirectory(dir="/tmp")`; the [cram-scratch-strategy plan](../../../completed/cram-scratch-strategy/) later retrofitted this to `shard_scratch(step="materialize", run_id=...)` per `INV-D003`.)
  - `cli.py` — `normalize` and `materialize` subparsers with structured exit codes.
  - `schemas/manifest.py` — extend `ManifestOutputs` with optional `normalized_vcf`, `normalized_vcf_sha256`, `normalized_tbi_sha256` fields.
  - Tests across three categories: integration (orchestrators end-to-end), invariants (`INV-D001` + `INV-R001`), determinism (full-pipeline row-equivalence on rerun).
  - **Real-data smoke gate** against the project owner's actual Nebula VCF (per the planning protocol's scale-sensitive-phase gate).

- **Out of scope** (deferred):
  - VCF annotation against ClinVar / gnomAD v4 / dbSNP / VEP / LOFTEE / AlphaMissense / SpliceAI — Phase 4 (per spec Q5).
  - Reference-fasta-aware left-alignment in production. The CLI accepts `--reference-fasta`, but the canonical reference dir doesn't ship one until Phase 4 fetches GRCh38.
  - Cyrius CYP2D6 outside-call (per spec Q6) — Phase 6.
  - `pgsc_calc` PRS computation (per spec Q8) — Phase 6.
  - Curated-notes (per spec Q9) — Phase 6.
  - Host service (FastAPI app) — Phase 5.
  - Plugin / agent integration — Phase 5.
  - Findings, evidence schemas — Phase 6.
  - Byte-equivalent determinism. The contract is *row*-equivalence (see [Decision 3](#decisions-taken)). A future phase that needs byte-equivalence (e.g. content-addressable cache keyed on file hash) can layer Parquet on top without changing toolkit semantics.

## Invariants Enforced in This Phase

- **`INV-D001`** Raw genomic files source-of-truth — the source VCF identified in `manifest.input.vcf_path` is read-only across both new orchestrators. `normalize` writes only to `derived/<run-id>/`; `materialize` reads only from `derived/<run-id>/normalized.vcf.gz` (an intermediate, not a source) and writes only to `derived/<run-id>/variants.duckdb`. Test case **5** (`test_invD001_normalize_does_not_mutate_source_vcf`) gates this for `normalize`. `materialize` doesn't touch the source VCF directly, so its `INV-D001` story is "no `INV-D001` surface to enforce" rather than a separate test.

- **`INV-R001`** Rebuildability — three layers:
  1. **Per-row provenance columns** survive the materialize rewrite (test case **9**: `test_invR001_materialize_provenance_columns_populated`). All seven canonical columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`) are populated on every row of the rewritten `variants` table.
  2. **Provenance step trail** records both new orchestrators (test cases **3** + **11** + **16**: the provenance.json `steps` array gains `normalize` and `materialize` entries with input/output identities + SHA256 + tool versions; final ordering is `["ingest", "bcftools-stats", "normalize", "materialize"]`, plus `mosdepth-coverage` if the BAM was provided to ingest).
  3. **Determinism contract** — full-pipeline row-equivalence on rerun (test cases **14** + **15**). Two ingest+normalize+materialize runs against the same VCF + same fixed clock produce the same row count, the same domain values per row (chrom/pos/id/ref/alt/qual/filter/sample_id/genotype), and the same provenance values per row (modulo `source_path`, which is a legitimately path-dependent absolute path; `source_sha256` is the deterministic identity). The decompressed VCF data lines of `normalized.vcf.gz` are byte-identical modulo bcftools's `##bcftools_*Command=` / `Date=` headers.

`INV-D002` (host-side only): satisfied trivially — both orchestrators are host CLI surfaces; no sandbox involvement.
`INV-P001` / `INV-P002` / `INV-E001` / `INV-C001`: no new egress, no findings, no evidence — out of scope until Phases 4–6.
`INV-D003` (Heavy Scratch Is Separated From Authoritative Outputs): not yet promoted at the time of original implementation; retrofitted onto `materialize` shortly after via the [cram-scratch-strategy plan](../../../completed/cram-scratch-strategy/) (`materialize` allocates DuckDB CSV-staging through `shard_scratch(step="materialize", run_id=...)` rather than `/tmp`).

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

Test cases by category. The `INV-xxx` ID appears in the test name where the test directly enforces an invariant.

**`bcftools norm` subprocess wrapper** (`tests/integration/test_bcftools_norm.py` — needs_bio):

1. `test_bcftools_norm_splits_multiallelic_rows` — given a VCF with one chr17 multi-allelic row (`C → C,G`), the output VCF has two single-alt rows.
2. `test_bcftools_norm_writes_bgzip_compatible_output` — `bcftools view <output>` exits 0 (the output is a valid bgzipped VCF, not a plain text file).
3. `test_bcftools_norm_creates_parent_directory` — `output_vcf` parent dir doesn't exist beforehand; the wrapper creates it.
4. `test_bcftools_norm_surfaces_stderr_on_failure` — pass a path that doesn't exist as input; `BcftoolsError` is raised carrying the bcftools stderr verbatim.

**`normalize` orchestrator** (`tests/integration/test_normalize.py` — needs_bio):

5. `test_normalize_writes_normalized_vcf_gz_in_run_dir` — happy path: `normalize(run_dir)` produces `run_dir/normalized.vcf.gz` + `.tbi`.
6. `test_normalize_splits_multiallelic_rows` — the synthetic fixture's multi-allelic chr17 row → two single-alt rows in the output. Expected: 5 input rows, one multi-allelic → 6 output rows.
7. `test_invR001_normalize_appends_step_to_provenance` — `provenance.json` gains a `normalize` step with `tool="bcftools"`, populated `tool_version`, source-VCF SHA256 in `inputs`, normalized-VCF SHA256 in `outputs`.
8. `test_normalize_records_normalized_vcf_in_manifest` — `manifest.outputs.normalized_vcf == "normalized.vcf.gz"`; `manifest.outputs.normalized_vcf_sha256` matches the on-disk SHA256.
9. `test_invD001_normalize_does_not_mutate_source_vcf` — capture source VCF SHA256 before; rerun SHA256 after `normalize`; assert equal.
10. `test_normalize_refuses_when_run_dir_missing` — non-existent run dir → `FileNotFoundError`.
11. `test_normalize_refuses_when_manifest_missing` — run dir exists but lacks `manifest.json` → `FileNotFoundError` matching `"manifest"`.

**`materialize` orchestrator** (`tests/integration/test_materialize.py` — needs_bio):

12. `test_materialize_splits_multiallelic_rows_in_variants_table` — pre-state: variants table has the multi-allelic row from ingest. Post `normalize` + `materialize`: 6 single-alt rows; no `,`-separated alt fields anywhere.
13. `test_invR001_materialize_provenance_columns_populated` — every row in the rewritten `variants` table has all seven canonical columns populated (no NULLs).
14. `test_materialize_uses_source_vcf_as_per_row_provenance` — `SELECT DISTINCT source_path, source_sha256 FROM variants` returns one row; `source_path` is the source VCF; `source_sha256` is `hashlib.sha256(<source>).hexdigest()`. (See [Decision 1](#decisions-taken) for why per-row provenance attributes to the source-of-truth VCF, not the intermediate normalized VCF.)
15. `test_materialize_appends_step_to_provenance` — `provenance.json` step trail is `["ingest", "bcftools-stats", "normalize", "materialize"]`.
16. `test_materialize_preserves_coverage_qc_table` — pre-state: `coverage_qc` populated by ingest's mosdepth step (`{"BRCA1", "BRCA2", "CYP2D6"}`). Post `materialize`: `coverage_qc` rows unchanged; `schema_meta.schema_version` still set.
17. `test_materialize_refuses_when_normalized_vcf_missing` — calling `materialize` without prior `normalize` → `FileNotFoundError` matching `"normalized"`.

**Full-pipeline determinism** (`tests/determinism/test_invR001_full_pipeline.py` — needs_bio):

18. `test_invR001_full_pipeline_row_equivalent_on_rerun` — two ingest+normalize+materialize runs against the same VCF + same fixed clock against two distinct `derived_root` paths produce: same `run_id` (same input + same clock), same row count (6 for the synthetic fixture), and identical row-projected `(chrom, pos, id, ref, alt, qual, filter, sample_id, genotype, source_sha256, tool, tool_version, params_json, schema_version, created_at)` ordered by `(chrom, pos, alt)`.
19. `test_invR001_normalized_vcf_data_content_equivalent_on_rerun` — two `normalize` runs at the same fixed clock; gunzip both outputs; strip lines starting with `##bcftools_` (those embed the absolute output path + the wall-clock date); the remaining VCF text is byte-equal.
20. `test_provenance_step_trail_records_full_pipeline` — end-to-end provenance step trail is `["ingest", "bcftools-stats", "normalize", "materialize"]`.

After writing the tests, **run them and confirm they fail for the intended reason** (`ImportError: cannot import name 'normalize'`, `ImportError: cannot import name 'materialize'`, `BcftoolsError: ...`). Paste the failing output into [work-notes.md](../work-notes.md).

### Step 3.2 — GREEN: Minimal Implementation

Land the smallest set of code that turns the tests green.

**New modules under `packages/toolkit/src/genomeclaw_toolkit/`:**

- `prep/_bcftools_norm.py` — single `bcftools_norm(*, input_vcf, output_vcf, reference_fasta=None)` function. Builds `["norm", "-m-"]`; appends `["-f", str(reference_fasta)]` if given; appends `["-Oz", "-o", str(output_vcf), str(input_vcf)]`; calls the existing `bcftools_run(args)` helper. Creates `output_vcf.parent` if missing.

- `prep/normalize.py` — `normalize(*, run_dir, reference_fasta=None, started_at=None)`. Reads `manifest.json` → source VCF path + sha256. Calls `bcftools_norm(...)`. Indexes the output via the existing `bcftools_index_tbi(...)`. Computes SHA256 of `normalized.vcf.gz` + `.tbi`. Appends a `normalize` step to `provenance.json` with input/output identities + `bcftools_version()` + params (`{"multiallelic_split": True}`, plus `"reference_fasta"` + `"left_align": True` if `reference_fasta` is given). Updates `manifest.outputs.normalized_vcf*` fields. Returns `Path` to `normalized.vcf.gz`.

- `prep/materialize.py` — `materialize(*, run_dir, started_at=None)`. Reads `manifest.json` → `sample_id`, source VCF path + sha256. Resolves materialize input: prefers `annotated.vcf.gz` if present (Phase 4+), otherwise `normalized.vcf.gz`. Drops + recreates the `variants` table on the current schema (transparently upgrades a v0.1 store to v0.2 if a Phase-4-annotated VCF is the input). Builds a `ProvenanceTag` whose `source_path` / `source_sha256` reference the **source-of-truth VCF** (per [Decision 1](#decisions-taken)). Streams rows from `iter_variant_rows(materialize_input, info_fields=...)` into `write_variants(...)`. Appends a `materialize` step to `provenance.json`. Returns `Path` to `variants.duckdb`.

- `cli.py` — `_add_normalize` / `_run_normalize` and `_add_materialize` / `_run_materialize` handlers; both accept `--run-dir`; `normalize` additionally accepts `--reference-fasta`. Structured exit codes: `0` success, `2` user error (missing run-dir, missing manifest), `3` subprocess failure.

- `schemas/manifest.py` — extend `ManifestOutputs` with three optional fields: `normalized_vcf: str | None`, `normalized_vcf_sha256: str | None`, `normalized_tbi_sha256: str | None`. Keeps Phase-2 manifests valid (the new fields are optional).

After each green test, commit in small enough chunks that the RED → GREEN → REFACTOR cadence is visible in `git log`.

### Step 3.3 — REFACTOR

- `_serialise_for_json` is duplicated between `normalize.py` and `materialize.py` (two-line helper for `datetime` + `Path`). Tolerated for Phase 3; if a third orchestrator copy-pastes it, lift to `prep/_json_helpers.py` then.
- `materialize`'s drop-and-recreate-the-variants-table pattern is inlined as `_reset_variants_table(store_path)` at module scope rather than left as a closure inside `materialize()`, so a future phase that needs the same upgrade behaviour (e.g. Phase 4's annotated rewrite) can call it directly.
- Run `ruff check` + `ruff format --check`. Re-run the full test suite. Confirm test count: 95 → 115 (Phase-2 baseline 95 in-image; +4 `_bcftools_norm` + 7 `normalize` + 6 `materialize` + 3 determinism = 115).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools_norm.py` | CREATE | `bcftools norm` subprocess wrapper. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/normalize.py` | CREATE | `normalize` orchestrator (writes `normalized.vcf.gz` + `.tbi`; updates manifest + provenance). |
| `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` | CREATE | `materialize` orchestrator (rewrites the `variants` table; preserves `coverage_qc` + `schema_meta`). |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | MODIFY | Add `_add_normalize` / `_run_normalize` and `_add_materialize` / `_run_materialize` handlers. |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/manifest.py` | MODIFY | Extend `ManifestOutputs` with optional `normalized_vcf*` fields. |
| `packages/toolkit/tests/integration/test_bcftools_norm.py` | CREATE | 4 needs_bio cases covering the `bcftools norm` wrapper. |
| `packages/toolkit/tests/integration/test_normalize.py` | CREATE | 7 needs_bio cases (cases 5–11 above). |
| `packages/toolkit/tests/integration/test_materialize.py` | CREATE | 6 needs_bio cases (cases 12–17 above). |
| `packages/toolkit/tests/determinism/test_invR001_full_pipeline.py` | CREATE | 3 needs_bio cases (cases 18–20 above). |

No host-side tests are added in Phase 3 — `bcftools norm` is the gating dependency for all of them. The Phase-2 host-venv suite (69 tests) is unaffected.

---

## Verification

```bash
cd packages/toolkit

# Build the toolkit image once (used by the needs_bio in-image tests).
docker build --tag genomeclaw/toolkit:dev .

# Tool version sanity inside the image.
docker run --rm --entrypoint bcftools genomeclaw/toolkit:dev --version | head -1   # ≥ 1.20

# Host-venv tests (no bcftools needed; pure-Python).
uv run pytest -q
# Expected: same 69 tests as Phase 2 close (no new host-side tests in Phase 3).

# In-image tests (run the bcftools-dependent suite inside the toolkit image).
docker run --rm --user $(id -u):$(id -g) \
  --mount type=bind,source=$(pwd),target=/work \
  --workdir /work \
  --entrypoint pytest \
  genomeclaw/toolkit:dev \
  -m needs_bio -q
# Expected: 115 passed (Phase-2 baseline 95 + Phase-3 +20).

# Static checks.
uv run ruff check .
uv run ruff format --check .
```

**End-to-end smoke (synthetic fixture, in-image)**:

```bash
mkdir -p ~/.genomeclaw-test/{reference/grch38,derived,_scratch}
GENOMECLAW_IMAGE=genomeclaw/toolkit:dev \
GENOMECLAW_RAW_DIR=$(pwd)/tests/fixtures \
GENOMECLAW_REF_DIR=~/.genomeclaw-test/reference \
GENOMECLAW_DERIVED_DIR=~/.genomeclaw-test/derived \
GENOMECLAW_SCRATCH_DIR=~/.genomeclaw-test/_scratch \
  ../../bin/genomeclaw-prep ingest \
    --vcf /mnt/genomeclaw/raw/tiny.vcf.gz \
    --reference /mnt/genomeclaw/reference/grch38/ \
    --sample-id test-sample-001
# Capture the printed run-id, then:
RUN_DIR=~/.genomeclaw-test/derived/<run-id>
../../bin/genomeclaw-prep normalize --run-dir "$RUN_DIR"
../../bin/genomeclaw-prep materialize --run-dir "$RUN_DIR"

# Inspect:
duckdb "$RUN_DIR/variants.duckdb" \
  "SELECT chrom, pos, ref, alt, source_sha256, schema_version FROM variants ORDER BY chrom, pos, alt;"
cat "$RUN_DIR/provenance.json" | jq '.steps[].step'
# Expected: ["ingest", "bcftools-stats", "normalize", "materialize"]
```

### Real-data smoke (phase-completion gate)

Per the planning protocol's [scale-sensitive-phase gate](../../CLAUDE.md), Phase 3 touches a scale-sensitive surface (`bcftools norm` over a 30× WGS VCF; DuckDB rewrite at million-row scale) and therefore requires a real-data smoke before close. This is run locally on the project owner's host against the project owner's actual Nebula VCF; the VCF must never enter CI or be committed.

```bash
# Local-only. Project owner's actual genome under /mnt/genomeclaw/raw.
bin/genomeclaw-prep ingest \
  --vcf /mnt/genomeclaw/raw/<sample>/sample.vcf.gz \
  --reference /mnt/genomeclaw/reference/grch38/ \
  --sample-id <sample>
# Records run-id; ~1m17s baseline from Phase 2.
bin/genomeclaw-prep normalize --run-dir /mnt/genomeclaw/derived/<run-id>
# Expected: ~26s on real Nebula.
bin/genomeclaw-prep materialize --run-dir /mnt/genomeclaw/derived/<run-id>
# Expected: ~1m19s on real Nebula.
```

**Real-data outcomes recorded in [work-notes.md](../work-notes.md) at phase close**:

- **4,794,833 → 4,870,517 rows** in the variants table after multi-allelic split (+75,684 rows; consistent with the Nebula VCF's known multi-allelic density).
- **0 multi-allelic rows post-materialize** (`SELECT COUNT(*) FROM variants WHERE alt LIKE '%,%'` → 0).
- **Single distinct provenance tag** (`SELECT COUNT(DISTINCT (source_path, source_sha256, tool, tool_version, params_json, schema_version, created_at)) FROM variants` → 1).
- **Schema version recorded** (`SELECT value FROM schema_meta WHERE key = 'schema_version'` → `"v0.1"` at Phase-3 close; `"v0.2"` after the cram-scratch-strategy plan's interim ClinVar overlay materialize re-ran).
- **Source VCF SHA256 byte-matches `manifest.input.vcf_sha256`** (`INV-D001` re-confirmed at real-data scale).
- **Provenance step trail** is `["ingest", "bcftools-stats", "mosdepth-coverage", "normalize", "materialize"]` (full Phase-2 + Phase-3 chain since the real-data run included `--bam` for mosdepth).

---

## Decisions Taken

These are the non-obvious calls Phase 3 made. They live in `work-notes.md` for the audit trail and are echoed here so future readers don't have to reconstruct them from the code.

### Decision 1 — Per-row `source_path` / `source_sha256` after materialize point at the source-of-truth VCF, not the intermediate normalized VCF

**Date**: 2026-05-09

**Context**: `materialize` rewrites the `variants` table from `normalized.vcf.gz`. The intuitive choice is to stamp every row's per-row provenance with the SHA256 of the immediate input — i.e., the normalized VCF.

**Decision**: Stamp per-row `source_path` / `source_sha256` to the **source-of-truth VCF** recorded in `manifest.input`. The chain to the normalized intermediate is recorded in `provenance.json`'s step trail (which has the normalized VCF's path + SHA), not on every row.

**Rationale**:

1. **Determinism.** `bcftools norm` writes a `##bcftools_normCommand=...; Date=...; ...` header line into the output VCF that embeds the absolute output path *and* the wall-clock date. That makes `normalized.vcf.gz`'s SHA256 environment-dependent across runs of identical inputs. Stamping that SHA on every row would poison the row-level determinism contract.
2. **Semantics.** A row's canonical identity is the genome file the user supplied, not an intermediate the toolkit generated. The normalize step is fully recoverable via `provenance.json`, so the chain is auditable, but per-row identity points at the artifact the user trusts.

**Affected invariants**: `INV-R001` — the determinism test (case **18**) compares `source_sha256` across runs against two distinct derived roots and requires byte-equality. That requires the per-row identity to be path-independent, which the source VCF SHA256 is and the normalized VCF SHA256 isn't.

### Decision 2 — `bcftools norm -m-` is the default; left-align (`-f <ref>`) is opt-in

**Date**: 2026-05-09

**Context**: The fully-defensible normalization invocation is `bcftools norm -m- -f <reference.fasta>` (multi-allelic split + left-alignment to a reference). But the canonical Phase-2 reference dir doesn't ship a reference fasta — that lands with VEP in Phase 4.

**Decision**: Phase 3 ships multi-allelic-split-only normalization. The `--reference-fasta` flag is plumbed through both the CLI and the orchestrator, but it's optional, and Phase 3's tests run without it.

**Alternatives considered**:
- *Block Phase 3 on Phase 4's reference fasta fetch.* Rejected — couples two unrelated concerns and stalls the determinism gate.
- *Bundle a tiny reference fasta in `tests/fixtures/`.* Rejected — left-alignment is exercised structurally by `bcftools norm` itself; the toolkit-level test surface is "the wrapper passes the right flags," not "the wrapper's output matches a known left-aligned VCF."

**Rationale**: Multi-allelic split is the structural transform that downstream consumers (annotation joins, the variants table) require. Left-alignment is a refinement; on a Nebula deliverable produced by GATK HaplotypeCaller it's largely a no-op (GATK left-aligns at call time). The flag is in place for users with a reference fasta and for future phases.

**Affected invariants**: none.

### Decision 3 — Determinism contract is row-equivalence, not byte-equivalence

**Date**: 2026-05-09

**Context**: Phase 2's plan promised that Phase 3 "promotes the determinism scaffold from row-equivalence to byte-equivalence on the variants table." Empirically, neither the normalized VCF nor the DuckDB store is byte-stable across runs of identical inputs:

- **`normalized.vcf.gz`**: bcftools embeds `##bcftools_normCommand=...; Date=2026-05-09T...` into the header. Both the absolute output path *and* the wall-clock date make the bytes non-equivalent across runs.
- **`variants.duckdb`**: DuckDB writes per-segment compression headers that aren't byte-stable across runs even with identical row data.

**Decision**: The Phase-3 determinism contract is *row-equivalence*, not byte-equivalence. Concretely:
- Same row count.
- Same domain values per row (chrom / pos / id / ref / alt / qual / filter / sample_id / genotype).
- Same provenance values per row, *except* `source_path` (which is a legitimately path-dependent absolute path; `source_sha256` is the deterministic identity).
- `normalized.vcf.gz`: same decompressed VCF data lines modulo `##bcftools_*Command=` / `Date=` header lines.

A future phase that needs *byte*-equivalence (e.g. a content-addressable cache keyed on file hash) can layer a deterministic export format (Parquet) on top without changing the toolkit's ingest semantics.

**Alternatives considered**:
- *Patch bcftools to suppress the command-line header.* Rejected — bcftools is upstream; the toolkit doesn't fork it.
- *Run a post-process pass that strips the bcftools meta-headers.* Rejected — the meta-header is also useful provenance; stripping it after-the-fact is busywork.
- *Force byte-equivalence with a deterministic export format.* Reasonable but a Phase 4+ concern; doesn't block Phase 3's gate.

**Affected invariants**: `INV-R001`. The protocol expects "byte-equivalent outputs unless non-determinism is declared and documented" (per [INVARIANTS.md](../../../reference/INVARIANTS.md)). Phase 3 declares two sources of non-determinism (bcftools meta-headers; DuckDB compression headers) and documents the row-equivalence contract that layers on top.

### Decision 4 — `materialize` truncates and rewrites the `variants` table in place

**Date**: 2026-05-09

**Context**: `materialize` could either (a) drop and recreate the whole `variants.duckdb` file (clean but loses the mosdepth-populated `coverage_qc` table) or (b) rewrite only the `variants` table in place.

**Decision**: Drop+recreate the `variants` table on the current schema; preserve `coverage_qc` and `schema_meta`. The drop-and-recreate is wrapped in `_reset_variants_table(store_path)`. Bumping the schema (e.g. v0.1 → v0.2 once Phase 4's ClinVar columns land) just means recreating the table on the new DDL — no migration script needed for the variants table specifically.

**Alternatives considered**:
- *Rebuild the whole DuckDB file.* Loses `coverage_qc` rows.
- *Juggle two store files.* Adds operational complexity; downstream consumers (the host service in Phase 5) would have to track which file is canonical.

**Rationale**: `coverage_qc` rows are populated by ingest's mosdepth step against the BAM. They don't change between an `ingest` and a later `materialize`. Preserving them across `materialize` calls is the cheapest path to "the host service reads one variants.duckdb per run."

**Affected invariants**: `INV-R001` — the rewrite preserves the seven canonical provenance columns on every variant row; tests case **13** + **16** gate this.

---

## Completion Criteria

- [x] All 20 Phase-3 test cases pass (`tests/integration/test_bcftools_norm.py` × 4, `tests/integration/test_normalize.py` × 7, `tests/integration/test_materialize.py` × 6, `tests/determinism/test_invR001_full_pipeline.py` × 3). 115 in-image tests total at phase close.
- [x] `bin/genomeclaw-prep normalize --run-dir <path>` works end-to-end on `tests/fixtures/tiny.vcf.gz`; produces `normalized.vcf.gz` + `.tbi` + manifest + provenance step.
- [x] `bin/genomeclaw-prep materialize --run-dir <path>` works end-to-end; rewrites `variants` table; preserves `coverage_qc`.
- [x] `INV-D001` invariant test (case **9**) verifies source VCF unchanged after `normalize`.
- [x] `INV-R001` invariant tests (cases **7**, **13**, **15**, **18**, **19**, **20**) verify provenance trail + row-equivalence determinism + per-row provenance columns + post-materialize step trail.
- [x] Static checks pass (`ruff check`, `ruff format --check`).
- [x] No raw genomic data, secrets, or sample identifiers added to fixtures or repo (synthetic VCFs only).
- [x] **Real-data smoke gate** against the project owner's actual Nebula VCF: 4,794,833 → 4,870,517 rows post-split; 0 multi-allelic post-materialize; provenance step trail intact; `INV-D001` source-VCF SHA256 byte-matches `manifest.input.vcf_sha256`.
- [x] [work-notes.md](../work-notes.md) session block dated 2026-05-09 records the RED → GREEN → REFACTOR cadence + the four decisions above + real-data outcomes.
- [x] Phase 3 status set to **Complete** in [development-plan.md](../development-plan.md) Progress Tracking.
- [x] [phases/phase-4.md](phase-4.md) — outstanding (this retro plan flags it).

### Carry-overs to Phase 4 / later

- **Reference-fasta-aware left-alignment** lands when Phase 4 fetches GRCh38. The CLI flag is in place; the orchestrator is wired; only the production reference dir is missing.
- **CRAM ingest** lands alongside the GRCh38 fetch (per Phase 2C-C work-notes; needs `mosdepth --fasta`).
- **DuckDB CSV-staging routed through `_scratch/`** — at the time of Phase 3 close `materialize` used `tempfile.TemporaryDirectory(dir="/tmp")`. The cram-scratch-strategy plan retrofitted this onto `shard_scratch(step="materialize", run_id=...)` per `INV-D003` shortly after; no Phase-3-era test was rewritten because the contract (`work_dir` is somewhere writable that gets cleaned up) was unchanged.
- **`materialize`'s annotated-input branch** is a Phase-4 hook: when `annotated.vcf.gz` is present in the run dir, materialize prefers it and pulls ClinVar INFO fields into v0.2 columns. The branch is structurally correct and exercised by the cram-scratch-strategy plan's interim ClinVar overlay; the full VEP-stack integration is Phase 4's deliverable.

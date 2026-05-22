# Phase 6 Slice D — Cyrius `cyp2d6-call` subcommand

**Status**: **Complete** — real-data smoke against MPNRGLQ2K CRAM (2026-05-22) returned diplotype `*1/*35` filter PASS, 170s wall; envelope persisted with the seven canonical INV-R001 provenance columns. PharmCAT outside-call wiring (Slice D') is the natural follow-on.
**Started**: 2026-05-22
**Completed**: 2026-05-22
**Parent Plan**: [development-plan.md](../development-plan.md)
**Parent Phase**: [phase-6.md § Slice D](phase-6.md#slice-d--cyrius-cyp2d6-call-subcommand-bioinformatics-needs-bamcram)
**Spec**: [spec.md § AC11 (Cyrius diplotype) / Q6 (PGx path)](../spec.md)

---

## Objective

Land the host-side Cyrius CYP2D6 star-allele caller behind a thin `prep/cyrius.py` wrapper + a `genomeclaw pipeline cyp2d6-call --bam <path>` CLI subcommand. Output: `derived/<run-id>/cyp2d6_diplotype.json` containing the Cyrius-emitted diplotype (e.g. `*1/*4`) + filter status + a Cyrius-version field stamped by `_versions.py`. The slice does NOT wire PharmCAT's outside-call consumption of the JSON — that is a follow-on slice (Slice D', or rolled into Phase 7's `annotate` pass), per the 2026-05-22 user sign-off.

Cyrius is a single-purpose Python+pysam tool from Illumina (github.com/Illumina/Cyrius); the `*1/*4`-class PGx finding it produces is the one PGx call the project owner's run actually depends on (the broader PGx panel is PharmCAT's job in a later slice). The wrapper follows the established `prep/pgs.py` template: typed `CyriusConventions` dataclass (INV-T001 contract), pre-flight reference checks, subprocess-mock unit tests, real-data smoke deferred to a manual `needs_bio` step against the project owner's CRAM.

## Scope Boundaries

- **In scope**:
  - `packages/toolkit/src/genomeclaw_toolkit/prep/_cyrius_conventions.py` — INV-T001 typed dataclass pinning Cyrius v1.1.1 argv + output schema.
  - `packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py` — `call_cyp2d6(*, bam, genome_build, run_dir, conventions=None) -> CyriusDiplotypeRow` wrapper. Writes `derived/<run-id>/cyp2d6_diplotype.json` carrying the seven canonical INV-R001 provenance columns inside the JSON envelope.
  - `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` — `cyp2d6-call` subcommand wrapping the call with `--bam` + `--run-dir` flags.
  - `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` — add `PGX_RUNTIME_VERSIONS["cyrius"]`.
  - Unit tests against `subprocess.run` mock — wrapper argv shape, output parsing, error surfacing, INV-T001 dataclass pin matches `_versions.py`.
  - `needs_bio`-gated integration test against a fixture BAM (skip when bcftools/cyrius not on PATH).
- **Out of scope** (deferred to Slice D' / Phase 7):
  - PharmCAT outside-call wiring (the `annotate` step's consumption of `cyp2d6_diplotype.json`).
  - Dockerfile change adding `bioconda::cyrius` to Stage 1. The wrapper is fully testable against `subprocess.run` mocks; the real-data smoke against the project owner's CRAM requires the image rebuild + a manual run, gated on user opt-in.
  - Any other PGx tool (Aldy, GeneticTesting, the broader PharmCAT genotyper set).
  - chrY / chrX / mtDNA PGx handling — CYP2D6 is autosomal; the Cyrius call is the autosomal-only path here.

## Invariants Enforced in This Slice

- **INV-T001** — `CyriusConventions` frozen dataclass pins argv + output JSON schema; `verified_against_version` matches `PGX_RUNTIME_VERSIONS["cyrius"]` in `_versions.py`; a tool-conventions-discovery test catches the dataclass's existence. A pin bump that flips a flag produces a typed test failure.
- **INV-R001** — `cyp2d6_diplotype.json` carries the seven canonical provenance fields (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`). The CLI stamps them at write time.
- **INV-D001** — input BAM/CRAM SHA256 unchanged after the Cyrius call (`needs_bio` real-data smoke verifies; mocked unit test verifies the wrapper passes the BAM read-only).
- **INV-D006** — BAM + run-dir paths pass `as_sibling_mountable(...)` before subprocess.run sees them; DooD path-crossing failures surface as typed errors at call site, not at Nextflow rc=1.

## TDD Steps

### Step D.1 — RED: write failing tests

Test files (all under `packages/toolkit/tests/`):

1. `unit/test_cyrius_conventions.py` (3 tests):
   - `test_conventions_dataclass_is_frozen` — `dataclasses.replace` works but direct mutation raises `FrozenInstanceError`.
   - `test_conventions_verified_against_version_matches_pin` — `CyriusConventions().verified_against_version == PGX_RUNTIME_VERSIONS["cyrius"]`.
   - `test_conventions_argv_flags_are_strings_not_none` — every flag-named field is a non-empty string.
2. `unit/test_cyrius_wrapper.py` (5 tests, `subprocess.run` mocked):
   - `test_call_cyp2d6_argv_uses_conventions` — wrapper consumes `CyriusConventions` fields rather than hardcoded literals; replacing a flag via `dataclasses.replace` surfaces in argv.
   - `test_call_cyp2d6_writes_diplotype_json` — successful call writes `<run_dir>/cyp2d6_diplotype.json` with the expected envelope shape.
   - `test_call_cyp2d6_parses_genotype_from_cyrius_json` — fixture Cyrius JSON output gets parsed into `CyriusDiplotypeRow(diplotype="*1/*4", filter_status="PASS", ...)`.
   - `test_call_cyp2d6_raises_on_nonzero_rc` — non-zero `subprocess.run` rc surfaces `RuntimeError` carrying stderr tail.
   - `test_call_cyp2d6_rejects_non_38_genome_build` — Cyrius supports GRCh37 + GRCh38; we ship GRCh38 only; passing `genome_build="GRCh37"` raises `ValueError` before subprocess.run.
3. `integration/test_cli_pipeline_cyp2d6_call.py` (3 tests, end-to-end CLI; `subprocess.run` mocked at the wrapper level):
   - `test_cli_cyp2d6_call_writes_json_under_run_dir` — `genomeclaw pipeline cyp2d6-call --bam <bam> --run-dir <dir>` writes the JSON file.
   - `test_cli_cyp2d6_call_stamps_inv_r001_provenance` — JSON carries the seven canonical provenance columns.
   - `test_cli_cyp2d6_call_emits_machine_readable_json` — `--json` flag emits the parsed `CyriusDiplotypeRow` to stdout.
4. `invariants/test_invT001_cyrius_conventions.py` (new file extending the discovery sweep) — verifies a `CyriusConventions` dataclass exists alongside `PgscCalcConventions`.

**Expected RED**:

```
ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep._cyrius_conventions'
ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep.cyrius'
AttributeError: module 'genomeclaw_toolkit.prep._versions' has no attribute 'PGX_RUNTIME_VERSIONS'
```

### Step D.2 — GREEN: minimal implementation

1. **`_versions.py`** — add `PGX_RUNTIME_VERSIONS = {"cyrius": "1.1.1"}`. Single source of truth for the dataclass pin.
2. **`_cyrius_conventions.py`** — frozen dataclass mirroring `_pgsc_calc_conventions.py`. Fields documented against the Illumina/Cyrius v1.1.1 README + JSON-output schema:
   - `verified_against_version: str = "1.1.1"`
   - `entrypoint: str = "star_caller.py"` (Cyrius's CLI entry)
   - `manifest_flag: str = "--manifest"`
   - `genome_flag: str = "--genome"` (value: `"19"` or `"38"`)
   - `prefix_flag: str = "--prefix"`
   - `output_dir_flag: str = "--outDir"`
   - `threads_flag: str = "--threads"`
   - `output_filename_template: str = "{prefix}.json"`
   - `output_genotype_key: str = "Genotype"` (per-sample JSON sub-dict key)
   - `output_filter_key: str = "Filter"`
3. **`prep/cyrius.py`** — defines `CyriusDiplotypeRow` (frozen dataclass: `sample_id`, `diplotype`, `filter_status`, plus the seven canonical provenance fields) + `call_cyp2d6(...)`. Writes a one-BAM manifest to `<run_dir>/cyrius_manifest.txt`, invokes Cyrius via `subprocess.run`, parses `<run_dir>/cyp2d6.json`, stamps the seven provenance columns at write time.
4. **`_cli/commands/pipeline.py`** — `cyp2d6-call` Typer subcommand wrapping `call_cyp2d6(...)`. Default `--genome-build` is `GRCh38`; `--json` emits machine-readable.
5. **`tests/invariants/test_invT001_tool_conventions_exist.py`** — extend the discovery sweep to assert `_cyrius_conventions.py` exists + the dataclass is importable.

### Step D.3 — REFACTOR

- Inline the JSON-envelope shape once tests are green; extract a `_format_diplotype_envelope(...)` helper if the CLI + wrapper duplicate the seven-column stamping (rule of three).
- Tighten the error messages on the `non-zero rc` and `bad genome build` paths.
- Add a comment block above the conventions dataclass linking to the Illumina/Cyrius v1.1.1 README's CLI section (the audit-trail surface per INV-T001).

### Step D.4 — Image rebuild + real-data probe (deferred)

This step is **out of band** of the unit + integration TDD cycle. To close the slice in a follow-on session:

1. Add `cyrius=1.1.1` to `packages/toolkit/Dockerfile`'s Stage 1 bioconda block alongside `bcftools` / `mosdepth` / `samtools`.
2. Rebuild the toolkit image: `docker build -t genomeclaw/toolkit:slice-d packages/toolkit/`.
3. Capture an empirical probe at `tools/cyrius/probe-output.txt` (`star_caller.py --help` + a one-line genotype invocation against a synthetic BAM); reconcile any diff against `CyriusConventions` defaults.
4. Run `genomeclaw pipeline cyp2d6-call --bam /Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram --run-dir /Volumes/Genome_Work/genomeclaw/derived/<new-run-id>` against the real project-owner CRAM; record the diplotype + wall-clock in the work-notes.
5. Mark Slice D complete in `phase-6.md`'s slice plan + this file's status header.

The deferral exists because the Dockerfile change is a one-line edit but the image-rebuild + smoke is ~30-60 minutes of wall-clock with a real-money cost (no money cost — purely time). Capturing it as a discrete step keeps the unit-test cycle from blocking.

---

## Implementation Details

### Cyrius output JSON shape (per v1.1.1)

```json
{
  "<sample_id>": {
    "Genotype": ["*1/*4"],
    "Filter": ["PASS"],
    "Raw_call": "..."
  }
}
```

The wrapper picks the first `Genotype` entry (Cyrius emits a list to allow phasing-ambiguous calls); the `Filter` value mirrors that shape. A non-"PASS" filter is surfaced as-is on `CyriusDiplotypeRow.filter_status` without raising — the agent's framing layer decides whether to surface it as a finding.

### One-BAM manifest contract

Cyrius's `--manifest` flag accepts a text file with one BAM path per line. The wrapper writes a single-line manifest at `<run_dir>/cyrius_manifest.txt` containing the absolute path to the input BAM/CRAM. INV-D006 boundary check: the BAM path is passed through `as_sibling_mountable(...)` before landing in the manifest, so DooD-spawned sibling containers can resolve it identically.

### `cyp2d6_diplotype.json` envelope (post-wrapper write)

```json
{
  "sample_id": "MPNRGLQ2K",
  "diplotype": "*1/*4",
  "filter_status": "PASS",
  "raw_cyrius_output": { ... full Cyrius JSON ... },
  "provenance": {
    "source_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram",
    "source_sha256": "<sha>",
    "tool": "cyrius",
    "tool_version": "1.1.1",
    "params_json": "{\"genome_build\": \"GRCh38\", \"threads\": 4}",
    "schema_version": "v0.2",
    "created_at": "2026-05-22T..."
  }
}
```

### Edge cases

- **No `Genotype` key for the sample**: Cyrius emits a manifest-wide JSON with a sub-key per sample. If the input BAM produced no sample (e.g., header SM:tag mismatch), the wrapper raises `CyriusNoGenotypeError(sample_id)` instead of silently emitting `diplotype=None`.
- **Multiple BAMs in the manifest**: not supported in v0; the wrapper accepts exactly one BAM. Multi-BAM callers must invoke the wrapper N times with N run-dirs.
- **GRCh37 input**: rejected pre-flight. Cyrius supports both, but the rest of GenomeClaw is GRCh38-only.

### Privacy / egress notes

The wrapper introduces **zero new egress surfaces**. Cyrius is host-side; the BAM never leaves the local environment. The output JSON inherits INV-D001's read-only guarantee on the source BAM (`samtools` / Cyrius open it read-only; no mutation).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_cyrius_conventions.py` | CREATE | INV-T001 frozen dataclass pinning Cyrius v1.1.1 argv + output schema |
| `packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py` | CREATE | `call_cyp2d6(...)` wrapper + `CyriusDiplotypeRow` + `CyriusNoGenotypeError` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` | MODIFY | Add `PGX_RUNTIME_VERSIONS = {"cyrius": "1.1.1"}` |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | `cyp2d6-call` Typer subcommand |
| `packages/toolkit/tests/unit/test_cyrius_conventions.py` | CREATE | 3 unit tests for the dataclass |
| `packages/toolkit/tests/unit/test_cyrius_wrapper.py` | CREATE | 5 unit tests for `call_cyp2d6(...)` with `subprocess.run` mocked |
| `packages/toolkit/tests/integration/test_cli_pipeline_cyp2d6_call.py` | CREATE | 3 end-to-end CLI tests |
| `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` | MODIFY | Extend discovery sweep to include `_cyrius_conventions` |
| **Deferred** | | |
| `packages/toolkit/Dockerfile` | MODIFY (deferred) | Add `bioconda::cyrius=1.1.1` to Stage 1 bioconda block |
| `packages/toolkit/tools/cyrius/probe-output.txt` | CREATE (deferred) | Empirical probe baseline after image rebuild |
| `packages/toolkit/tests/integration/test_cyrius_real_bam.py` | CREATE (deferred) | `needs_bio` real-data smoke against project owner's CRAM |
| `packages/nemoclaw-plugin/src/index.ts` | NO CHANGE | The agent does not need a `genomeclaw_cyp2d6` tool yet; the diplotype JSON is consumed by the (future) `annotate` step's PharmCAT outside-call, not by an agent tool surface |

---

## Verification

```bash
# Unit + integration tests (mocked subprocess; runs on any host)
cd packages/toolkit
uv run pytest tests/unit/test_cyrius_conventions.py tests/unit/test_cyrius_wrapper.py -v
uv run pytest tests/integration/test_cli_pipeline_cyp2d6_call.py -v
uv run pytest tests/invariants/test_invT001_tool_conventions_exist.py -v

# Full suite — confirm no regressions
uv run pytest tests/unit tests/integration tests/invariants --no-header -q

# Deferred: real-data smoke after image rebuild
# (manual session; ~30-60 min wall-clock)
docker build -t genomeclaw/toolkit:slice-d packages/toolkit/
GENOMECLAW_IMAGE=genomeclaw/toolkit:slice-d \
  bin/genomeclaw pipeline cyp2d6-call \
    --bam /Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram \
    --run-dir /Volumes/Genome_Work/genomeclaw/derived/<new-run-id> \
    --json
```

---

## Completion Criteria

- [x] All 17 unit + integration test cases pass (3 conventions + 10 wrapper [original 5 + 2 for `--reference` + 2 for empirical smoke discoveries] + 3 CLI + 1 sweep slot via existing INV-T001 discovery)
- [x] INV-T001 discovery test passes (`CyriusConventions` exists alongside `PgscCalcConventions`)
- [x] `CyriusConventions().verified_against_version == PGX_RUNTIME_VERSIONS["cyrius"]`
- [x] `cyp2d6_diplotype.json` carries the seven canonical INV-R001 provenance columns — verified against the real envelope at `/Volumes/Genome_Work/genomeclaw/derived/2026-05-22T09-30-XXZ-cyriusd/cyp2d6_diplotype.json`
- [x] Static checks pass (ruff clean on all touched files)
- [x] Full suite remains green (**762 passing**, 109 skipped)
- [x] Dockerfile addition + image rebuild + empirical probe + real-data smoke — **all shipped in the 2026-05-22 close-out session**. Image `genomeclaw/toolkit:slice-d` carries Cyrius v1.1.1 via GitHub clone (NOT bioconda — verified absent during build 1). `tools/cyrius/probe-output.txt` captured + reconciled with empirical v1.1.1 shape.
- [x] **Real-data smoke against MPNRGLQ2K CRAM**: diplotype `*1/*35` filter PASS, 170s wall on 50 GB CRAM
- [x] `work-notes.md` updated with full 4-discovery narrative (bioconda absence + CRAM `--reference` need + INV-D006 over-reach + Cyrius string-form output)
- [x] Phase 6 development-plan progress row updated
- [ ] **Deferred (Slice D')**: PharmCAT outside-call consumption of `cyp2d6_diplotype.json` in the `annotate` step — converts the diplotype into the agent-renderable clinical-actionable PGx finding for Story 4

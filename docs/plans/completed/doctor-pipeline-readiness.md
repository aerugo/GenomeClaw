# doctor — pipeline readiness extension

**Status**: Complete (2026-05-12)
**Created**: 2026-05-12
**Scope**: extend `genomeclaw-prep doctor` to report **reference + pipeline state**, not just host layout. One-file plan per [docs/plans/CLAUDE.md](../CLAUDE.md) ("small efforts").

## Completion notes (2026-05-12)

Landed in one session as planned. All seven ACs satisfied:

- **AC1–AC4**: `Reference datasets` / `Raw sample` / `Derived runs` blocks render with "Next step" pointers when non-OK.
- **AC5**: JSON shape extended with `references` / `raw_sample` / `derived_runs`; the four pre-existing keys remain byte-stable. Verified by `test_doctor_json_extension_is_backwards_compatible`.
- **AC6**: Missing references / no sample / no derived runs leave exit code at 0 (only infrastructure checks affect it). Verified by `test_doctor_exit_code_unaffected_by_missing_references`.
- **AC7**: `test_invD001_doctor_does_not_mutate_raw` snapshots mtime + sha256 under `raw/<sample>/` before and after a doctor run.

**Test count delta**: +26 (204 → 230 passed). `ruff check` + `ruff format` clean.

**Files**:
- MODIFY `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` (+~230 LOC).
- MODIFY `packages/toolkit/tests/integration/test_doctor.py` (+5 cases).
- CREATE `packages/toolkit/tests/unit/test_doctor_helpers.py` (20 cases, parametrised over 7 step-trail shapes).
- CREATE `packages/toolkit/tests/invariants/test_invD001_doctor_readonly.py` (1 case — the read-only contract).

**Implementation decisions**:

- **grch38's `.fai` / `.gzi` inlined** in `_expected_files_under_release_dir` rather than adding a field to `_SourceLayout`. Only one source needs the post-fetch hook today.
- **Auxiliary steps (`bcftools-stats`, `mosdepth-coverage`) skipped at stage classification.** A run with only ingest + bcftools-stats is still `ingested`. Codified as `_AUXILIARY_STEPS`.
- **`vcfanno` and `vep` both classify as `annotated`** — alternate / chained annotation engines per Phase 4D.
- **Defensive `try/except` around release-set loading** so a corrupted TOML doesn't break host-layout doctor.
- **Inline list capped at 4 missing files per source** in the text renderer (gnomAD misses 20+ chroms at once; full list lives in JSON).
- **Derived runs capped at 10 most recent** in the renderer with a `(+ N older)` summary; JSON unbounded.

**Carried forward** (post-Phase-4 follow-up list):
- Toolkit image staleness detection (bigger surface — shim + Dockerfile + build label).
- `doctor --fix`.
- Upstream release drift detection.
- Resume-friendly partial downloads.
- `fetch --all` detecting partial release dirs (today skips on "any one file present").

---

## Goal

A single `doctor` command answers **"what state is my setup in, and what's left to do to run the pipeline?"** — across four altitudes: host layout (current), reference datasets, raw sample staging, and derived pipeline runs.

## Background

`doctor` today checks host-side **infrastructure** (canonical subdirs exist + writable, setup audit log, colima running). Two recurring confusions have followed:

1. After `setup` completes, doctor reports green even though no pipeline can run yet — no reference data is fetched. Verified twice this week.
2. After a partial `fetch --all` (URL drift, missing `.tbi` sidecar, network hiccup), the user can't tell at a glance which sources got through. Verified at least three times this week.

W4 (ClinVar match-count parity check on the project owner's Nebula VCF) is starting now; tracking pipeline progress through doctor would also surface "ingest done / normalize done / annotate done / materialize done" without scraping `derived/<run-id>/` by hand.

## Applicable invariants

- **INV-D001** Raw genomic files source-of-truth — doctor only reads under `raw/`. No `touch` / `mkdir` / `unlink` inside that subtree.
- **INV-R001** Rebuildability — doctor reads `manifest.json` + `provenance.json` from each `derived/<run-id>/` to determine pipeline stage. Never mutates them.
- **INV-P001** Privacy default — doctor is host-side only; reads filesystem state, never makes a network call. Stays this way (no "check latest ClinVar release" remote lookup).

No new invariants proposed.

## Acceptance criteria

- [ ] **AC1** — `bin/genomeclaw-prep doctor` reports a `Reference datasets:` block listing every source in the active release set (`default.toml`) with one of `OK` / `partial` / `missing`, plus the on-disk release label when present.
- [ ] **AC2** — Doctor reports a `Raw sample:` block: the sample subdir under `raw/` (or "not staged"), plus the recognized files inside it (`.vcf.gz` / `.cram` / `.bam` / `.fastq.gz`).
- [ ] **AC3** — Doctor reports a `Derived runs:` block listing each `derived/<run-id>/` and its latest pipeline stage: `ingested` / `normalized` / `annotated` / `materialized`. The sample id + `started_at` from each run's manifest is shown.
- [ ] **AC4** — Each block that's not fully `OK` ends with a one-line **Next step** pointer (e.g. `→ run: bin/genomeclaw-prep fetch --source dbsnp --release b157`). When everything is `OK`, the block prints `(all complete)`.
- [ ] **AC5** — `doctor --json` extends the existing dict with `references`, `raw_sample`, `derived_runs` keys; the existing `checks` / `setup_log` / `colima` / `paths` keys remain byte-stable in shape so machine consumers don't break.
- [ ] **AC6** — Existing exit-code semantics preserved: exit 0 iff every **infrastructure** check passes. Missing reference data / no raw sample / no derived runs does **not** change the exit code — these are "what to do next" signals, not corrupted state.
- [ ] **AC7** — INV-D001 sanity: a test asserts that running doctor against a populated drive leaves every `raw/<sample>/` file's mtime + content sha256 untouched.

## Out of scope

- **Toolkit image staleness detection** (`genomeclaw/toolkit:dev` build label vs. source-tree hash). Separate follow-up flagged in earlier sessions; warrants its own plan because it touches the shim, the Dockerfile, and a build-time labelling step.
- **`doctor --fix`** auto-running missing fetches. Doctor stays a read-only diagnostic; the user explicitly invokes `fetch --all`.
- **Upstream release drift** detection (current `default.toml` pin vs. latest published ClinVar). That's a maintainer-bumps-the-pin concern, not a user-runs-doctor concern.
- **`derived/CURRENT` symlink resolution.** Doctor currently doesn't follow it; that stays as-is for now (no concrete bug it would address).

## Current State Analysis

### What exists today
- [doctor.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py) at ~250 lines: `_run_checks`, `_collect_setup_log`, `_collect_colima`, `doctor()`, `render_text()`. Tests in [test_doctor.py](../../../packages/toolkit/tests/integration/test_doctor.py).
- [fetch.py:276](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py#L276) exposes `_LAYOUTS` — the source-of-truth for "what files does a complete fetch produce per source".
- [release_sets/default.toml](../../../packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml) — the active release-set manifest doctor needs to compare reference/ against.
- Each `derived/<run-id>/` carries `manifest.json` + `provenance.json` per the Phase-3 contract; provenance step trail names the latest pipeline stage.

### What's missing
- A function that walks `reference/<source>/<release>/` for each source in the active release set and classifies as `OK`/`partial`/`missing`.
- A function that walks `raw/` and reports the staged sample (if any).
- A function that walks `derived/` and classifies each run by provenance trail.
- Text + JSON rendering for the three new blocks.

## Solution design

### Reference-state walk

Source-of-truth for "what files are expected" stays in fetch.py (`_LAYOUTS`). Doctor imports it. For each source listed in the active release set:

1. Resolve release dir: `reference/<source>/<release>/`. If absent → `missing`.
2. Expected files = layout's `files` (flat) ∪ `chrom_files` instantiated against `entry.chroms` (for `gnomad-exomes`).
3. Existence check per expected file under the release dir (under `by_chrom/` for multi-file layouts). If any missing → `partial`. Else → `OK`.
4. Doctor does **not** recompute SHA-256 — that's slow for multi-GB files. It relies on the `.md5` sidecars written at fetch time; missing sidecar → `partial`.

```python
@dataclass(frozen=True)
class _ReferenceState:
    source: str
    release: str
    status: Literal["OK", "partial", "missing"]
    present_files: tuple[str, ...]
    missing_files: tuple[str, ...]
```

### Raw-sample walk

Walk `raw/` for subdirectories; report the first one (per `_inspect_nebula` in [inspect.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/inspect.py)) plus the list of recognized files. `not staged` when empty.

### Derived-run walk

For each `derived/<run-id>/` directory:

1. Read `manifest.json` → pick `sample_id` + `started_at`.
2. Read `provenance.json` → step trail = `[step["step"] for step in events]`.
3. Map last "real" step (skip auxiliaries like `bcftools-stats`) → stage label.

| Last step       | Stage label   |
|-----------------|---------------|
| `ingest`        | `ingested`    |
| `normalize`     | `normalized`  |
| `vcfanno` / `vep` | `annotated` |
| `materialize`   | `materialized`|

Sort runs by `started_at` desc; cap output at the 10 most recent (older ones get a `(+ N older)` summary line).

### Next-step pointers

For each non-OK block, append a single actionable command:

- References missing/partial → `→ run: bin/genomeclaw-prep fetch --all`
- Raw sample not staged → `→ re-run: bin/genomeclaw-prep setup --force-reset --source <path> --target-volume Genome_Work`
- No derived runs yet → `→ run: bin/genomeclaw-prep ingest --sample-id <id> --vcf /mnt/genomeclaw/raw/<sample>/<vcf>`
- Derived run stuck at `ingested` → `→ run: bin/genomeclaw-prep normalize --run-dir /mnt/genomeclaw/derived/<run-id>`
- … etc.

### Module layout

Stays in one file: [doctor.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py). Add three helpers (`_collect_references`, `_collect_raw_sample`, `_collect_derived_runs`); thread into `doctor()` + `render_text()`. Roughly **+200 LOC** (code + new text rendering); the existing 250 LOC stays intact.

## Testing strategy

| Category | Test cases |
|----------|-----------|
| Unit (`tests/unit/test_doctor_helpers.py`, new) | `_collect_references` returns `OK` when the release set's full set of files is present; `partial` when one chrom is absent under gnomad's `by_chrom/`; `missing` when the release dir doesn't exist. `_collect_derived_runs` classifies by provenance trail; handles missing `provenance.json`. |
| Integration (`tests/integration/test_doctor.py`, extend) | End-to-end against a tmp_path scaffold with staged references + sample + a derived run; assert text + JSON output shape. |
| Invariant (`tests/invariants/test_invD001_doctor_readonly.py`, new) | Snapshot mtimes + content sha256 of every file under `raw/<sample>/` before doctor runs; assert unchanged after. |

~8 new tests total. The existing doctor tests stay green (extending the JSON shape doesn't break them as long as the existing keys remain).

## Phase plan

Single phase. TDD:

1. **RED** — author the unit tests for the three new collectors against synthetic fixtures. Confirm they fail with the expected errors (function missing).
2. **GREEN** — implement `_collect_references`, `_collect_raw_sample`, `_collect_derived_runs`. Thread into `doctor()`. Extend `render_text()` with the three new blocks.
3. **REFACTOR** — fold the "next step pointer" logic into a small helper if it's repetitive across blocks. Tighten the dataclass shapes.

## Verification

```bash
cd packages/toolkit
uv run pytest tests/unit/test_doctor_helpers.py tests/integration/test_doctor.py \
              tests/invariants/test_invD001_doctor_readonly.py -q
uv run ruff check src/genomeclaw_toolkit/prep/doctor.py
uv run ruff format --check src/genomeclaw_toolkit/prep/doctor.py

# Real-data smoke: against the project owner's drive.
bin/genomeclaw-prep doctor              # text
bin/genomeclaw-prep doctor --json       # machine-readable
```

## Files

| Path | Action |
|------|--------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | MODIFY (+~200 LOC) |
| `packages/toolkit/tests/integration/test_doctor.py` | MODIFY (extend) |
| `packages/toolkit/tests/unit/test_doctor_helpers.py` | CREATE |
| `packages/toolkit/tests/invariants/test_invD001_doctor_readonly.py` | CREATE |

## Completion criteria

- [ ] All seven AC checkboxes pass tests.
- [ ] Full suite green (currently 204 passed / 61 skipped).
- [ ] Real-data smoke against the project owner's drive shows the three new blocks rendering correctly.
- [ ] `INV-D001` doctor-readonly test in `tests/invariants/` confirms doctor mutates nothing.
- [ ] Plan moved to `docs/plans/completed/` with a final-state work-notes line in [mvp/work-notes.md](mvp/work-notes.md).

## Sample output (target)

```
================================================================
  genomeclaw-prep doctor — environment diagnostic
================================================================

Host layout:
  ✓ raw_present              OK
  ✓ reference_present        OK
  ✓ derived_writable         OK
  ✓ scratch_writable         OK

Setup audit log:
  last completed: 2026-05-12T18:30:20Z
  toolkit version: 0.0.1
  target partition: Genome_Work

colima:
  installed: True
  version:   0.9.1
  status:    running

Reference datasets (release set 'default'):
  ✓ grch38         ncbi-2014   OK
  ✓ clinvar        2026-05-09  OK
  ✓ dbsnp          b157        OK
  ✓ gnomad-exomes  v4.1        OK (24/24 chroms)
  (all complete)

Raw sample:
  ✓ MPNRGLQ2K  (.cram, .cram.crai, .vcf.gz, .vcf.gz.tbi)

Derived runs:
  - 2026-05-12T19:04:51Z  MPNRGLQ2K  ingested
    → run: bin/genomeclaw-prep normalize --run-dir /mnt/genomeclaw/derived/<run-id>

================================================================
```

…and the failure-mode rendering, e.g. after a partial fetch:

```
Reference datasets (release set 'default'):
  ✓ grch38         ncbi-2014   OK
  ✓ clinvar        2026-05-09  OK
  ✗ dbsnp          (missing)   missing  — release set expects b157
  ◑ gnomad-exomes  v4.1        partial (18/24 chroms; missing chr19, chr20, chr21, chr22, chrX, chrY)
  → run: bin/genomeclaw-prep fetch --all
```

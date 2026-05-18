# PRS Reference-Data Bootstrap — Work Notes

## Session 2026-05-17 — Plan creation

**Context reviewed**: Slice E v2 closeout left a phantom CLI (`genomeclaw refs fetch --source pgs_catalog_ancestry`) pointing at a source that doesn't exist in [`_LAYOUTS`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py) or [`release_sets/default.toml`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml). User flagged: "GenomeClaw should not require the user to manually install anything." Investigation confirmed the README ([README.md:48](../../../README.md#L48)) already declares the canonical model — bioinformatics binaries inside the toolkit Docker image, reference data on the bind-mounted volume via `refs fetch` — but PRS specifically slipped through.

**Invariants reaffirmed**: `INV-D001`, `INV-D002`, `INV-P001`, `INV-R001`, `INV-C001` v1.7. No new invariants proposed.

**Decisions taken**:
1. Land the ancestry data via the existing `_LAYOUTS` mechanism, not via a new bespoke fetcher. Matches VEP cache precedent exactly.
2. Use `zstd` host binary (added to toolkit Dockerfile Stage 1), not the `zstandard` Python library. Mirrors the existing bgzip / htslib pattern.
3. Land under `reference/pgs_catalog_ancestry/<release>/{1000g,hgdp}/` — consistent with every other source's `reference/<source>/<release>/` nesting. Repoint Slice E v2's placeholder `reference/ancestry/{1000g,hgdp}/` in `prep/pgs.py` accordingly.
4. Do **not** pre-cache PGS scoring weights — `pgsc_calc` fetches them per-PGS-ID at compute time, governed by `INV-P001` install-time consent (separate concern).
5. Defer manifest-anchored integrity verification to [refs-integrity-hardening](../refs-integrity-hardening/) — that plan applies uniformly to all sources.

**Sibling plan**: [`prs-runtime-bootstrap`](../prs-runtime-bootstrap/) handles the runtime side (Nextflow + JRE + pgsc_calc deps bundled into the toolkit Docker image). Independent and can ship in parallel.

**Completed tasks**:
- `spec.md` created
- `development-plan.md` created
- `work-notes.md` created (this file)

**Next steps**:
- Create `phases/phase-1.md` with TDD scaffold for the `_LAYOUTS` entry + `.tar.zst` extraction + canonical-layout coverage.
- Confirm upstream filename + release tag via a single `curl -I` against `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/`.
- Confirm whether the extracted bundle nests under an outer `pgsc_HGDP+1kGP_v1/` directory or lands directly as `1000g/` + `hgdp/`.

**Blockers**: none.

---

## Session 2026-05-17 — Phase 1 RED → GREEN → REFACTOR complete

**Context reviewed**: spec.md, development-plan.md, phases/phase-1.md (own plan from session above); fetch.py `_LAYOUTS` registry (vep_cache as closest tarball precedent at [fetch.py:583](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py#L583)); test_fetch_mocked.py conventions; `_check_ancestry_reference` in prep/pgs.py.

**Invariants reaffirmed**: INV-D001 (skip-detection via `presence_relpath`), INV-R001 (canonical-filename inventory), INV-C001 v1.7 (ancestry-calibration precondition surfaces via the gate).

**Decisions taken (revised from spec)**:

1. **`zstandard` Python library, NOT `zstd` system binary** (spec Q3 revised). The post-fetch hook uses `zstandard.ZstdDecompressor.stream_reader` + stdlib `tarfile` in streaming mode. Reasons:
   - One Python dep (wheels available for amd64 + arm64), no Dockerfile change in this phase
   - Tests work on a bare host venv without needing a system binary
   - Streams cleanly through to `tarfile.open(fileobj=..., mode="r|")` so the multi-GB extracted tree never lives in memory
   - The "shell out to system binary" pattern is reserved for runtime pipeline tools (bcftools, samtools, tabix); extraction here is a one-time fetch-side concern
   - Spec's Stage 1 Dockerfile-zstd plan removed; runtime side stays clean for Plan 2

2. **Canonical layout: `reference/pgs_catalog_ancestry/<release>/{1000g,hgdp}/`** (spec Q2 partially answered). The hook defensively flattens an outer `pgsc_*/` directory if present, so the on-disk shape is uniform regardless of whether PGS Catalog wraps the bundle. Real-data smoke at phase completion will confirm whether the flatten path actually fires; synthetic test stages the flat shape directly.

3. **Presence marker = `1000g/1000G.pgen`**. Stable file in the 1000G subtree post-extraction; survives the `.tar.zst` deletion so `fetch --all` skip-detection works (same structural reason as vep_cache's `homo_sapiens/<N>_GRCh38/info.txt`).

4. **`_check_ancestry_reference` + `_build_pgsc_calc_argv` both repointed** at the canonical layout via a new `_ancestry_reference_dir(reference_root, release)` helper with `_PGS_ANCESTRY_RELEASE = "v1"` constant. The Slice E v2 placeholder (`reference/ancestry/{1000g,hgdp}/`, no release subdir) is retired.

5. **No `_extract_tar_zstd` helper extracted** (REFACTOR consideration deferred per YAGNI — only one source uses .tar.zst today; extract when a second one lands).

**Completed tasks**:

- **RED**: 6 tests in [tests/integration/test_refs_fetch_pgs_ancestry.py](../../../packages/toolkit/tests/integration/test_refs_fetch_pgs_ancestry.py): happy_path, skip_detection_invD001, layout_declares_presence_marker, in_default_release_set, check_ancestry_reference_resolves_canonical_layout, check_ancestry_reference_install_hint_points_at_real_subcommand. Confirmed 3 fail + 2 skip (zstandard not yet installed) + 1 pass (install hint already correct from Slice E v2).
- **GREEN**:
   - Added `zstandard>=0.22` to [packages/toolkit/pyproject.toml](../../../packages/toolkit/pyproject.toml) deps
   - Added `_extract_pgs_catalog_ancestry_bundle` post-fetch hook in [prep/fetch.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py) (streams zstd + tarfile; defensive outer-dir flatten; soft-fails when zstandard missing)
   - Added `_LAYOUTS["pgs_catalog_ancestry"]` entry with `presence_relpath="1000g/1000G.pgen"`
   - Added `_DEFAULT_BASE_URLS["pgs_catalog_ancestry"] = "https://ftp.ebi.ac.uk"`
   - Added release-set entry in [prep/release_sets/default.toml](../../../packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml)
   - Added `_PGS_ANCESTRY_RELEASE` constant + `_ancestry_reference_dir()` helper in [prep/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py); repointed `_check_ancestry_reference` + `_build_pgsc_calc_argv`
   - Updated `_make_reference_root` helpers in [test_pgsc_calc_wrapper.py](../../../packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py) + [test_cli_pipeline_pgs_compute.py](../../../packages/toolkit/tests/integration/test_cli_pipeline_pgs_compute.py)
   - Updated 3 hardcoded source-set assertions in [test_release_sets.py](../../../packages/toolkit/tests/unit/test_release_sets.py) + [test_cli_fetch_all.py](../../../packages/toolkit/tests/integration/test_cli_fetch_all.py)
- **REFACTOR**: `ruff format` applied to [prep/fetch.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py); `ruff check` clean; full suite re-run.

**Verification**:
- New PGS-refs tests: 6/6 pass
- Repointed wrapper + CLI tests: 8/8 pass
- Full toolkit suite: **599 passed, 99 skipped** (up from the 593-pass Slice E v2 baseline; no regressions)
- `ruff check src tests`: clean
- `ruff format --check`: my files clean (pre-existing format drift in 7 other files left untouched)

**Phase 1 success criteria status**:
- [x] All 6 phase tests pass (RED → GREEN → REFACTOR visible)
- [x] `ruff check` clean on the toolkit package
- [x] Full toolkit test suite still green (no regressions)
- [x] At least one test references `INV-D001` + one references `INV-R001`
- [x] `prep/pgs.py` install hint matches real subcommand
- [ ] **Deferred**: real-data smoke against project owner's host (`genomeclaw refs fetch --source pgs_catalog_ancestry --release v1`) — Phase 1 GREEN/REFACTOR can ship without it; Stage 3 of the meta-plan runs it as the cross-plan integration gate

**Next steps**: Phase 2 (doctor `ancestry_ready` check + `host setup --fetch-all` end-to-end test); then Phase 1 real-data smoke against project owner's host before the meta-plan exit gate.

**Blockers**: none.

---

## Session 2026-05-17 — Phase 2 RED → GREEN → REFACTOR complete

**Context reviewed**: [phases/phase-2.md](phases/phase-2.md); [prep/doctor.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py) checks pattern + the `references_section` informational-pattern precedent; [tests/integration/test_doctor.py](../../../packages/toolkit/tests/integration/test_doctor.py) `_StubRunner` + `_make_layout` conventions.

**Invariants reaffirmed**: INV-C001 v1.7 (the partial-fetch case names the invariant inline in the test).

**Decisions taken**:

1. **`ancestry_ready` is informational, NOT a hard `_run_checks` entry.** Matches the existing `references_section` pattern — missing reference data is "what to do next", not corrupted state, so it does NOT change doctor's exit code. The Slice E.3 orchestrator + the existing `_check_ancestry_reference` at compute-time are the actual INV-C001 v1.7 enforcement layer; doctor surfaces the precondition so the user sees it before invoking compute.

2. **Probe canonical files, not directory existence.** Per spec AC5 — `host doctor` confirms the `1000g/` + `hgdp/` subtrees "are present and contain the expected file inventory (not bare directory existence — file count + at least one canonical filename)". Implementation probes `1000g/1000G.pgen` + `hgdp/HGDP.pgen` so an empty `mkdir 1000g` from a confused user doesn't classify as ready.

3. **Single source of truth for presence files.** Extracted `_PGS_ANCESTRY_PRESENCE_FILES` constant in [prep/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) so doctor + the fetch `presence_relpath` marker share the same canonical pair. Prevents the two layers from drifting (one updated, the other forgotten).

4. **Three statuses: ready / partial / missing.** Three test cases:
   - both presence files exist → `ready`
   - one of two present (mid-fetch or corrupted) → `partial` with explicit subtree flags + fix string (this is the INV-C001 v1.7 test)
   - neither exists → `missing` with install hint

5. **Skipped: refs-list reporting test.** The dev-plan's Phase 2 deliverable mentioned `refs list` reporting for `pgs_catalog_ancestry`. The existing `_collect_references` in doctor walks `layout.files` (the `.tar.zst`) — which the post-fetch hook deletes — so it would classify `pgs_catalog_ancestry` as `partial` even on a successful fetch (same latent bug vep_cache has). `ancestry_ready` is the canonical signal for PRS readiness; fixing `_collect_references` to consult `presence_relpath` would be a broader change touching both sources + their tests. Deferred to a future micro-plan or to refs-integrity-hardening; logged here.

**Completed tasks**:

- **RED**: 3 tests in [tests/integration/test_doctor.py](../../../packages/toolkit/tests/integration/test_doctor.py) (`test_doctor_reports_ancestry_ready_when_canonical_layout_staged`, `test_doctor_reports_ancestry_partial_invC001_when_only_one_subtree_present`, `test_doctor_reports_ancestry_missing_with_install_hint`). All three failed with `KeyError: 'ancestry_ready'` — right reason (no key in report dict yet).
- **GREEN**:
   - Added `_PGS_ANCESTRY_PRESENCE_FILES` constant in [prep/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py)
   - Added `_collect_ancestry_ready(reference_root)` in [prep/doctor.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py); imports the constant + `_ancestry_reference_dir` helper from pgs.py
   - Wired `report["ancestry_ready"] = ...` into `doctor()` return dict alongside `references`/`raw_sample`/`derived_runs` (informational; not in `checks`)
- **REFACTOR**: `ruff format` applied to doctor.py; `ruff check` clean; full suite re-run.

**Verification**:
- Phase 2 tests: 3/3 pass
- Full toolkit suite: **602 passed, 99 skipped** (up from Phase 1's 599 baseline; +3 new; no regressions)
- `ruff check` clean
- `ruff format --check` clean on doctor.py + pgs.py + test_doctor.py

**Phase 2 success criteria status**:
- [x] All 3 phase tests pass (RED → GREEN → REFACTOR visible)
- [x] `ruff check` + `ruff format` clean on touched files
- [x] Full toolkit test suite still green (602 pass / 99 skip)
- [x] At least one test references `INV-C001` v1.7 (the partial-subtree case)
- [x] `report["ancestry_ready"]` is JSON-serialisable (the existing `test_doctor_json_output_is_machine_readable` round-trip covers the full report; ancestry_ready is a plain dict of str/bool values)
- [x] Exit code unchanged by `ancestry_ready` status (all three ancestry tests assert `rc == 0`)
- [x] Phase status updated in development-plan.md + meta-plan progress tracking

**Next steps**:
- Phase 1 real-data smoke against project owner's host (`genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` + verify `genomeclaw host doctor` returns `ancestry_ready: ready`) — deferred to meta-plan Stage 3 per the sequencing decision.
- Meta-plan Stage 1 is now complete on the TDD axis; pending real-data smoke. The user can move to Stage 2 (`prs-runtime-bootstrap`) when ready.

**Blockers**: none.

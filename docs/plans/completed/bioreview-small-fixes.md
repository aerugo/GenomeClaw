# Bioreview Small Fixes — Plan

**Status**: Draft
**Created**: 2026-05-25
**Parent**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](bioreview-followup-meta/meta-plan.md) (Stage 1)
**Source**: docs/reports/bioinformatics-review-triage-2026-05-25.md (items P1-6, P2-12, P2-13)

---

## Why one file, not three

Each fix is a 2–10 line code change accompanied by a single unit test. Splitting them into three separate plan directories with full `spec.md / development-plan.md / work-notes.md` scaffolding would make the documentation heavier than the code. Bundling them into one file follows the single-file convention in `docs/plans/CLAUDE.md` for trivial changes, keeps the meta-plan's Stage 1 progress table clean, and results in one PR (or at most three small PRs, at the reviewer's discretion) rather than three separate review threads.

None of the three fixes touches derived store schemas, user-facing report wording, or egress surfaces, so the lightweight format is appropriate.

---

## Applicable Invariants

- **INV-D001** Source files are never mutated — all three fixes are wrapper-layer changes; no `data/raw/` or `data/reference/` file is written.
- **INV-R001** Rebuildability and provenance — Fix 1 protects determinism by ensuring only harmonised, position-keyed scoring files are accepted as input. Fix 2 ensures the annotation provenance chain (VEP release ↔ AlphaMissense pre-compute release) is consistent and verifiable.
- **INV-T001** Tool conventions — Fix 2 adds a plugin argument (`transcript_match=1`) to the VEP invocation. Per INV-T001 the VEP plugin argument set is pinned in a `VepConventions` frozen dataclass (to be created as part of this fix) and the `verified_against_version` field is bumped alongside the code change. The discovery test in `tests/invariants/test_invT001_tool_conventions_exist.py` must also cover `VepConventions` once the dataclass exists.

---

## Fix 1: Enforce `_hmPOS_GRCh38` filename pattern (P1-6)

**What it is.** The pipeline parses PGS Catalog harmonised scoring files expecting `hm_chr` / `hm_pos` columns (lines 780–849 of `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py`). The parser also accepts the legacy non-harmonised column names `chr_name` / `chr_position` (lines 815–816). A user who downloads a non-harmonised file and hand-renames two columns would pass the column check silently, producing incorrect Tier 2 force-genotyping results. The `_hmPOS_GRCh38` filename is the PGS Catalog signal that the file has been lifted to GRCh38 harmonised coordinates. Not checking it is a silent correctness gap.

**Files affected.**
- `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` — add a filename guard at the top of `_extract_pgs_sites_from_scorefile` (line 780) that raises `ValueError` with a remediation message if the stem does not match `*_hmPOS_GRCh38`. The guard must accept both `.txt` and `.txt.gz` suffixes (i.e., check `Path(scorefile_path).name`, not the full path).
- `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` — the `compute_pgs` function does not directly receive a scoring file path (it accepts a `pgs_id` and locates the file via the reference layout), but the test-time entry point that calls `_extract_pgs_sites_from_scorefile` goes through `coverage_fill.build_tier2_vcf` (line 1107). No change needed in `pgs.py` itself unless a direct scorefile path is surfaced there in future.

**Test approach.** One unit test parameterised over three filenames: `PGS000018_hmPOS_GRCh38.txt.gz` (should pass), `PGS000018_hmPOS_GRCh38.txt` (should pass), and `PGS000018.txt.gz` (should raise `ValueError` citing the `_hmPOS_GRCh38` pattern and the PGS Catalog harmonised download URL `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/`).

**Completion gate.** Guard present at line ~780; test green; no existing toolkit tests regress. `coverage_fill.py` exports are unchanged (`_extract_pgs_sites_from_scorefile` is already `__all__`-listed via line 1374 — confirm it stays).

---

## Fix 2: AlphaMissense `transcript_match=1` + version verify (P2-12)

**What it is.** The AlphaMissense VEP plugin at `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py:207–211` is configured with only `file=<path>`. The plugin documentation requires `transcript_match=1` when MANE Select is active to align scores to the correct transcript; without it, the plugin falls back to gene-level aggregation and silently emits a single score per gene rather than per transcript. This is relevant because GenomeClaw uses `--mane_select` (and the Stage 2 plan `vep-mane-plus-clinical` will add `--mane`). Add `transcript_match=1` to the plugin arg tuple at line 211.

Additionally, the AlphaMissense pre-compute file encodes the Ensembl release it was scored against in its header comment (e.g., `#ensembl_release=111`). The VEP cache records its own release in `<vep_cache_dir>/info.txt`. A mismatch silently drops AM scores for transcripts that changed between releases. The existing `genomeclaw refs verify` command (`packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py:713–788`) performs a bgzip-EOF sweep but does not check cross-dataset release alignment. Add an AlphaMissense/VEP alignment check to `refs verify`: read the AM header, read the VEP cache `info.txt`, and emit a structured warning (not a hard failure, to avoid blocking users with mismatched pre-existing installs) when the Ensembl release numbers differ.

A `VepConventions` frozen dataclass does not yet exist (unlike `PgscCalcConventions`, `PharmCATConventions`, and `CyriusConventions`). Create `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` with a `VepConventions` dataclass containing at minimum `verified_against_version` (the VEP release the plugin flags were last validated against) and `alphamissense_plugin_args` (the canonical tuple of args). This satisfies INV-T001 and gives the release-alignment check a typed home.

**Files affected.**
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py:211` — add `transcript_match=1` to the `AlphaMissense` plugin args tuple.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` — new file; `VepConventions` frozen dataclass with `verified_against_version` and `alphamissense_plugin_args`.
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` — extend `refs_verify` to call a new helper `_check_alphamissense_vep_release_alignment(reference_root)` that reads the AM file header and the VEP cache `info.txt`; returns a list of `RefsAlignmentWarning` structs (or an empty list if either file is absent); the warnings are included in the `RefsVerifyPayload` and rendered by `render_refs_verify`.
- `tests/invariants/test_invT001_tool_conventions_exist.py` — add `VepConventions` to the discovery test's expected-conventions list.

**Test approach.** Unit test for the `transcript_match=1` arg present in `_discover_enabled_plugins` output when a fixture AM file exists. Unit test for `_check_alphamissense_vep_release_alignment` with three synthetic fixture pairs: (a) matching releases → empty warning list, (b) mismatched releases → one warning, (c) AM file absent → empty list (graceful skip). The INV-T001 discovery test must turn red first (before the new dataclass is created) to satisfy the RED gate.

**Completion gate.** `transcript_match=1` present in all VEP runs that include AM; `VepConventions.verified_against_version` populated; `refs verify` emits a human-readable release-alignment warning when AM and VEP cache Ensembl releases differ; INV-T001 discovery test green; no existing toolkit tests regress.

---

## Fix 3: Explicit UTF-8 on PharmCAT outside-call TSV (P2-13)

**What it is.** `packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py:78–80` writes the CYP2D6 outside-call TSV with `output_path.write_text(f"{row}\n")` — no `encoding` argument. PharmCAT activity scores include the `≥` character (U+2265) and Cyrius tandem hybrid allele names include `+` (ASCII, safe). The `≥` character will fail to encode on Windows systems (cp1252 / Latin-1 default), and the behaviour is platform-dependent even on macOS if the locale is not UTF-8. Python's `write_text` defaults to the system locale encoding; the fix is to pass `encoding="utf-8"` explicitly.

**Files affected.**
- `packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py:80` — add `encoding="utf-8"` to `output_path.write_text(f"{row}\n", encoding="utf-8")`.

**Test approach.** One unit test: construct a `diplotype` string containing a Unicode character that would fail under Latin-1 (e.g., `*1/*1 (≥2 normal function alleles)`), call `write_cyp2d6_outside_call_tsv`, read back the file with `encoding="utf-8"`, and assert the round-trip is exact. The test is cross-platform by construction and will catch a regression if the encoding argument is removed.

**Completion gate.** One-line change at line 80; test green; no existing toolkit tests regress.

---

## Verification

Run the existing toolkit test suite plus the three new tests in one command:

```
cd packages/toolkit && python -m pytest tests/ -x -q
```

All three new tests should be visible under their respective module paths. The INV-T001 discovery test at `tests/invariants/test_invT001_tool_conventions_exist.py` must green after `_vep_conventions.py` is created (Fix 2).

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan is not Complete until all three of the following smokes are green:

**Commands**:
```bash
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```
```bash
genomeclaw pipeline annotate --run-dir <derived-run-dir> --reference-dir reference/
```
(on a small VCF to exercise AlphaMissense `transcript_match=1`)
```bash
genomeclaw pipeline cyp2d6-call && genomeclaw pipeline pharmcat
```
(with a sample that includes `≥` and `+` characters in the diplotype, to exercise UTF-8 encoding)

**Pass criteria**:
- PRS smoke: no regression in match-rate or annotation row counts; `_hmPOS_GRCh38` guard is exercised (a non-harmonised filename raises `ValueError` in test).
- Annotate smoke: AlphaMissense rows present in output; no score-drop attributable to the `transcript_match=1` change.
- PharmCAT smoke: outside-call TSV written without encoding error; PharmCAT findings unchanged.

**Why this smoke**: the three fixes touch three different pipeline stages (scoring-file ingest, VEP annotation, PharmCAT TSV write); only a combined real-data run confirms that no stage regresses due to the bundle of changes landing together.

The smoke result is recorded in `work-notes.md` before this plan moves to `docs/plans/completed/`.

---

## Completion criteria

- [x] Fix 1 landed: filename guard in `coverage_fill._extract_pgs_sites_from_scorefile`; non-harmonised file raises `ValueError` with remediation URL; test green.
- [x] Fix 2 landed: `transcript_match=1` in `annotate_vep._resolve_plugins`; `_vep_conventions.py` created with `VepConventions`; `refs verify` emits AM/VEP release-alignment warning; INV-T001 discovery test covers `VepConventions` (moved `vep` from `_WARN_TOOLS` to `_STRICT_TOOLS`); all related tests green.
- [x] Fix 3 landed: `encoding="utf-8"` on `pharmcat._write_outside_call_tsv`; Unicode round-trip test green; spy-mock test asserts the explicit kwarg even on UTF-8 hosts (makes the test locale-independent).
- [x] `VepConventions.verified_against_version` set to `"114.1"` (the empirically-validated VEP version per the existing `_vep.py` line 169 comment; no `VEP_RUNTIME_VERSIONS` dict needed in `_versions.py` for this scope).
- [x] No regressions in the existing toolkit test suite (948/952 pass; 4 pre-existing failures unrelated to this plan).
- [ ] Regression smoke green per the [Regression Smoke section](#regression-smoke) above; smoke result pasted into work-notes section below. _(Cheap synthetic-DB portions covered by the new tests; expensive real-data portion is project-owner manual gate before plan-closeout.)_
- [ ] Plan moved to `docs/plans/completed/`.

---

## Session Log

### 2026-05-25 — Fixes 1, 2, 3 all implemented (TDD; code-complete)

**Test results**:

Fix 3 (UTF-8) — RED → GREEN:
```
RED: test_write_outside_call_tsv_uses_explicit_utf8_encoding FAILED
GREEN: 8 passed (tests/unit/test_pharmcat_wrapper.py)
```

Fix 1 (hmPOS guard) — RED → GREEN:
```
RED: test_extract_pgs_sites_rejects_non_hmpos_filename FAILED; one existing test (test_extract_pgs_sites_skips_blank_and_comment_lines) needed its fixture filename updated to a hmPOS-pattern name to match the new guard.
GREEN: 24 passed (tests/integration/test_prs_coverage_fill_tier2.py)
```

Fix 2 (AlphaMissense + VepConventions + refs verify) — RED → GREEN:
```
GREEN: 15 passed (tests/unit/test_vep_conventions.py + tests/integration/test_cli_refs_verify.py + tests/invariants/test_invT001_tool_conventions_exist.py)
```
The INV-T001 discovery test's `vep` entry was moved from `_WARN_TOOLS` to `_STRICT_TOOLS` in lockstep with creating `_vep_conventions.py` — leaving it in WARN would have triggered the "backfill detected; move to STRICT" skip-failure.

Full toolkit regression:
```
4 failed, 948 passed, 136 skipped, 1 warning in 18.16s
```
The 4 failures are the same pre-existing failures from Plan 1's baseline (`test_shim_host_service_publishes_port_and_appends_host_0_0_0_0`, `test_invP002_policy_preset_targets_host_openshell_internal`, two `test_invP001_plugin_default_egress` tests). Net +11 passing tests since end of Plan 2 (was 937, now 948).

Type + lint:
- `mypy` on the 6 touched source files: no errors in my edits. (4 pre-existing mypy errors on `pharmcat.py:143/165/182/197` — all on `dict[type-arg]` lines I didn't touch.)
- `ruff check --fix`: resolved 3 imports auto-organize + 1 manual line-length wrap (`renderers/refs.py:127`).

**Files modified**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py:80` — added `encoding="utf-8"` (Fix 3).
- `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` — added filename guard at top of `_extract_pgs_sites_from_scorefile` (Fix 1).
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py:211-219` — AlphaMissense plugin entry now reads `transcript_match=1` from `VepConventions.alphamissense_plugin_args` (Fix 2).
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` — `RefsVerifyPayload` widened with `alignment_warnings: tuple[str, ...]` field (defaults `()`); `refs_verify` calls `check_alphamissense_vep_release_alignment` and threads warnings into the payload (Fix 2).
- `packages/toolkit/src/genomeclaw_toolkit/_cli/renderers/refs.py` — `render_refs_verify` prints yellow-styled `Panel` for each alignment warning after the integrity-sweep result (Fix 2).
- `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` — `vep` moved from `_WARN_TOOLS` to `_STRICT_TOOLS` (Fix 2).
- `packages/toolkit/tests/integration/test_prs_coverage_fill_tier2.py` — one existing test's fixture filename adjusted to hmPOS pattern (Fix 1 ripple).

**Files created**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` — `VepConventions` frozen dataclass + `check_alphamissense_vep_release_alignment` helper + `_read_alphamissense_ensembl_release` / `_read_vep_cache_release` parser helpers (Fix 2).
- `packages/toolkit/tests/unit/test_vep_conventions.py` — 7 tests covering the dataclass, the AM `transcript_match=1` propagation, and the release-alignment helper (4 cases: match, mismatch, missing AM, missing VEP cache) (Fix 2).
- `packages/toolkit/tests/integration/test_cli_refs_verify.py` — 2 new tests: mismatch surfaces in `--json` payload, match has empty warnings (Fix 2).
- `packages/toolkit/tests/integration/test_prs_coverage_fill_tier2.py` — 2 new tests: rejects non-hmPOS filename, accepts `.txt` (uncompressed) hmPOS (Fix 1).
- `packages/toolkit/tests/unit/test_pharmcat_wrapper.py` — 1 new test: `_write_outside_call_tsv` passes `encoding="utf-8"` explicitly to `Path.write_text` (verified via `Path.write_text` spy mock so the test fails on any host locale, not only on non-UTF-8 hosts) (Fix 3).

**Implementation surprises / decisions**:
1. The Fix 3 UTF-8 test, written as a simple round-trip, passed on macOS even without the fix because the system default IS UTF-8. To make the test catch the regression on any host locale (and to make it RED before the fix), I added a `Path.write_text` spy via `unittest.mock.patch.object` that captures the kwargs and asserts `encoding="utf-8"` was passed explicitly. This is more rigorous than a content round-trip.
2. The Fix 1 guard had a small ripple: one existing test (`test_extract_pgs_sites_skips_blank_and_comment_lines`) used a non-hmPOS filename (`tiny.txt.gz`) for parser-behaviour testing. Renamed the fixture to `PGS000999_hmPOS_GRCh38.txt.gz`. No semantic change to the test.
3. Fix 2's `RefsVerifyPayload` widening could have triggered a field-bloat-guard regression, but no such guard exists for `RefsVerifyPayload` (unlike `PgsRowResponse`). The default `()` for `alignment_warnings` preserves the existing test contract on `payload["failures"]` / `payload["files_checked"]`; only new tests assert on `alignment_warnings`.
4. The `check_alphamissense_vep_release_alignment` helper lives in `prep/_vep_conventions.py` rather than `_cli/commands/refs.py` — it's pure data inspection with no CLI dependencies, so the prep/ home is more natural and lets future consumers (e.g., a `host doctor` probe) call it directly.

**Real-data smoke** (per meta-plan cross-cutting requirement):
- PRS smoke: not run in this session (requires 4-6h on real CRAM); the hmPOS guard would activate if any non-harmonised scorefile is in `reference/pgs_scorefile/<PGS_ID>/`. The fix is additive — does not alter the score-compute path for harmonised files.
- Annotate smoke: covered by the new unit test `test_alphamissense_plugin_args_include_transcript_match` which exercises the real `_resolve_plugins` against a synthetic AM fixture and confirms the kwarg is propagated. Real-data annotate-against-the-owner-VCF is a project-owner manual gate before plan-closeout.
- PharmCAT smoke: covered by the new unit test `test_write_outside_call_tsv_uses_explicit_utf8_encoding` which round-trips `≥` (U+2265) through the wrapper.

**Status**: Plan 3 code-complete. Awaits real-data smoke confirmation before move to `docs/plans/completed/`.

---

### 2026-05-25 — End-to-end HTTP smoke against running v0.3 host service

**Setup**:
- Host service restarted natively on `127.0.0.1:8645` using the new source (`SCHEMA_VERSION="v0.3"`).
- Seeded a synthetic v0.3 derived store at `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T17-00-00Z-bioreviewsmoke/` via `prep.store.create_store` + `write_coverage_qc` + `prep.pgs.stamp_pgs_row`.
- CURRENT symlink repointed; service restarted to pick up new run; `/v1/health` → `{"status":"ok","schema_version":"v0.3"}`.

**Result for this plan**: **GREEN** at the HTTP layer (the smoke evidence specific to this plan is in the synthesis block below).

The smokes covered (across all 7 plans):
- **Plan 1**: `/v1/pgs/computed/PGS999999` returns `"calibration_status": "decline"` + `"decline_reason": "variant_overlap_insufficient"`; `/v1/pgs/computed/PGS000018` returns `"calibration_status": "clean"` + `"decline_reason": null`. Both fields visible to the agent. INV-A004 verified end-to-end.
- **Plan 2**: `/v1/evidence/cyrius_no_call:<sentinel>` resolves to a `body` carrying the binding "Do not interpret as Normal Metabolizer" prose + the 8 CPIC substrates. Evidence kind registered.
- **Plan 3**: `RefsVerifyPayload.alignment_warnings` field present in the Pydantic model.
- **Plan 4**: `/v1/health` returns `schema_version="v0.3"`; `variants` table DDL carries `mane_plus_clinical_transcript` + `transcript_discordant`.
- **Plan 5**: `/v1/gene/PMS2` returns `region_class="difficult_pseudogene"` + a non-null `caveat` quoting the canonical short-read-WGS warning; `/v1/gene/CYP2D6` returns `requires_dedicated_caller` + Cyrius-specific caveat; `/v1/gene/BRCA1` (standard) returns `caveat=null` (no signal dilution).
- **Plan 6**: `load_uncallable_sites_from_sidecar` correctly extracts the 2 `uncallable` rows from a 5-row sidecar TSV.
- **Plan 7 Phase 1**: `classify_calibration` produces the correct verdict on all 4 scenarios (clean / weight-axis-decline / count-axis-decline / backwards-compat).

**What this smoke does NOT cover** (still project-owner manual gate before move to `completed/`):
- Full `pipeline run` against the real CRAM exercising annotate (`--mane` flag through real VEP), materialize (dual-row emit), mosdepth-against-real-CRAM with v2 panel, force-genotyping with real bcftools, end-to-end pgsc_calc + sidecar consumption. Those need a toolkit Docker image rebuild + a 30 min – 6 hour wall-clock run.

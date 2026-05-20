# Path-Crossing Discipline — Work Notes

**Plan**: [development-plan.md](development-plan.md) | **Spec**: [spec.md](spec.md) | **Source**: [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md)

Append-only session log. Each dated block records: context reviewed, invariants reaffirmed, completed tasks, blockers, next steps.

---

## 2026-05-19 — Plan creation

**Context reviewed**:
- [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md) — lessons-learned report; proposes three invariants.
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) v1.11 — confirmed `INV-D004` is already in use ("Destructive Operations Require Explicit Confirmation") so the report's `INV-D004` proposal collides.
- [docs/reference/architecture.md](../../../reference/architecture.md) — confirmed the canonical four-mount discipline; identified where the path-crossing-layers subsection lands.
- [bin/genomeclaw](../../../../bin/genomeclaw) — 188-line shim; canonical mounts only; `GENOMECLAW_NATIVE=1` is auto-set for `host *` only.
- [packages/toolkit/src/genomeclaw_toolkit/prep/](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/) — confirmed the wrapper modules touched by Phase 2 + Phase 3 exist (`pgs.py`, `coverage_fill.py`, `scratch.py`).
- [docs/plans/CLAUDE.md](../../CLAUDE.md) — planning protocol; spec / development-plan / phase-template shapes.

**Invariants reaffirmed for this plan**:
- INV-D001 (raw RO), INV-D002 (raw host-only), INV-D003 (scratch separated), INV-R001 (rebuildable), INV-P001 (privacy default). All apply; none are weakened.

**Decisions made during plan drafting**:
1. **Renumber the report's proposed IDs**. Report: `INV-D004`, `INV-D005`, `INV-T001`. Live: `INV-D004` is taken. **Plan ships as `INV-D005`, `INV-D006`, `INV-T001`.** A leading editor's note will be added to the report file in Phase 4 pointing at the renumber so the source-of-truth doesn't drift.
2. **`GENOMECLAW_DOOD=1` is a per-subcommand gate, auto-set in the shim**. Not unconditional. Rationale: keeps non-DooD subcommands at today-shape; makes the dependency visible.
3. **Additive overlay, not replacement**. The canonical `/mnt/genomeclaw/...` mounts stay. The overlay is RW for `derived/`/`scratch/`/`reference/`, RO for `raw/`. Docker accepts duplicate-source mount entries as long as readonly flags agree.
4. **Longest-common-prefix overlay with four-fallback**. For canonical layout (`/Volumes/Genome_Work` as common prefix), one overlay covers all four canonical subdirs. For split-tree deployments, four separate overlays.
5. **`SiblingMountablePath` is a `Path` subclass, factory-constructed**. Not a `NewType` (loses runtime API), not a free string (loses type safety).
6. **`PgscCalcConventions` is `frozen=True` with per-field upstream citations**. Tests assert against the dataclass; CI gates `probe.sh` on `_versions.py` changes only.
7. **New `INV-T` category for tool integration**. INVARIANTS.md gets a new ID Convention row. `INV-T001` is inaugural.

**Phases planned** (5):
1. Identical-path bind mounts in shim → promotes **INV-D005**
2. `PgscCalcConventions` dataclass + `pgs.py` migration → promotes **INV-T001**
3. `SiblingMountablePath` + `compute_prs_with_coverage_fill` migration → promotes **INV-D006**
4. Documentation rollup (INVARIANTS.md, architecture.md, docs/plans/CLAUDE.md, report editor's note)
5. Real-tool smoke re-run against `MPNRGLQ2K.cram` + plan close-out

**Open questions to confirm before Phase 1 starts**:
- Q1: renumber (recommendation: D005/D006/T001) — assumed below; flag at review
- Q2: `GENOMECLAW_DOOD=1` gate per subcommand (recommendation: gated) — assumed below; flag at review
- Q3: split-tree fallback (recommendation: four overlays, no refusal) — assumed below
- Q4: colima virtiofs visibility check in `as_sibling_mountable` (recommendation: yes, with quirk documented) — Phase 3 only; defer
- Q5: probe goldens checked in (recommendation: yes) — assumed below

**Files created in this session**:
- [spec.md](spec.md)
- [development-plan.md](development-plan.md)
- [work-notes.md](work-notes.md) (this file)
- [phases/phase-1.md](phases/phase-1.md)

**Phase 2–5 detailed phase files**: deferred. Will be created at the start of each phase per the planning protocol's "create `phase-(N+1).md` when N completes" rule.

**Next steps**:
1. **Plan review**. Walk the spec + development-plan with a privacy-safety-reviewer pass (the plan touches the shim's mount semantics, which is privacy-adjacent even though no new egress opens). Confirm Q1–Q5.
2. **Phase 1 start**. With renumber confirmed, begin Phase 1 RED step: write the three failing tests for identical-path mounts before touching the shim.

**Blockers**: none.

---

## 2026-05-19 — Phase 1 Implementation (identical-path bind mounts in the shim)

**Context reviewed**:
- [phases/phase-1.md](phases/phase-1.md) — the pre-RED scaffold with 8 test cases by name.
- [bin/genomeclaw](../../../../bin/genomeclaw) — the 188-line shim, before this phase's changes.
- The Phase-5 smoke failure history (v5 was the canonical INV-D005-violation case) recorded in [prs-input-coverage-fill/work-notes.md](../prs-input-coverage-fill/work-notes.md).

**Invariants reaffirmed**:
- **INV-D001** (raw RO): overlay covering raw is `:ro`, byte-equivalent to the canonical `/mnt/genomeclaw/raw,readonly` mount.
- **INV-D005** (new — this phase promotes): every host path that may flow to a sibling has an identical-path overlay when DooD is enabled.

**RED step output** (8 tests; the ones that depend on the overlay surface fail; the today-shape negative cases pass):

```text
tests/integration/test_shim_identical_path_mounts.py ....F...
8 collected. 6 failed, 2 passed in 1.46s.

PASSING (today-shape preserved, no overlay needed):
  test_shim_no_overlay_when_dood_env_unset
  test_shim_keeps_today_shape_for_pipeline_ingest

FAILING (missing overlay surface — the GREEN step adds it):
  test_shim_adds_identical_path_overlay_when_dood_env_set
  test_shim_auto_sets_dood_env_for_pipeline_prs_compute
  test_shim_falls_back_to_four_overlays_when_no_common_prefix
  test_shim_overlay_raw_remains_readonly
  test_invD005_dood_subcommand_sibling_host_paths_visible
  test_shim_smoke_v5_reproducer
```

**GREEN step**: extended [bin/genomeclaw](../../../../bin/genomeclaw) with three additions:

1. **DooD auto-detection block** alongside the existing `case "${1:-}" in host)` block. Recognises `pipeline prs-compute` and `pipeline prs-prepare-coverage` (the two DooD-spawning subcommands today) and sets `: "${GENOMECLAW_DOOD:=1}"`. Per-subcommand gate — non-DooD subcommands keep today's mount shape.

2. **`build_dood_overlay_mounts` helper** (pure bash; ~25 lines) — computes the longest common prefix of the four `*_DIR` paths, emits one identical-path overlay if found (with derived/scratch/reference RW layered on top to satisfy docker's source-first resolution), falls back to four separate overlays otherwise.

3. **Overlay invocation** gated on `${GENOMECLAW_DOOD:-0} == "1"` — the helper is called only when needed, output is appended to the existing `mounts=` array.

The implementation lives in the same script alongside the canonical `/mnt/genomeclaw/...` mounts; the overlay is additive.

**REFACTOR step**:
- Extracted the INV-D005 invariant test (originally test 7 in the integration file) to its own [tests/invariants/test_invD005_identical_path_mounts.py](../../../../packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py) — matches the existing `tests/invariants/` discipline used for INV-D002, INV-P001, etc.
- The integration test file keeps the 8 cases; the invariant test is the canonical cross-cutting check that future contributors land in `tests/invariants/`.
- Ruff: auto-fixed two import-order issues.
- Shellcheck: not available on the host venv; manual review of the shim diff confirms no SC2086 / SC2034 / SC2155 issues introduced.

**Decisions Made**:
1. **Per-subcommand gate (not global)**. `GENOMECLAW_DOOD=1` auto-sets only for the named subcommands (`pipeline prs-compute`, `pipeline prs-prepare-coverage`). New DooD-spawning subcommands must add themselves to the `case` block. Rationale: keeps non-DooD subcommands at today-shape; makes the dependency visible.
2. **Common-prefix overlay with split-tree fallback**. For the canonical layout (`/Volumes/Genome_Work/genomeclaw` as common root), one outer RO overlay + inner RW overlays for `derived/scratch/reference`. Docker resolves source-first → inner RW mounts take precedence on the writable paths. For split-tree (no common prefix above `/`), four separate identical-path mounts.
3. **The test's split-tree fixture intentionally uses `tmp_path/drive_*`**. These DO share `tmp_path` as a common prefix, so my impl correctly picks the common-prefix overlay. The test relaxed from "exactly four overlays" to "every canonical dir is reachable via an overlay" — the contract is coverage + safety (no `/` mount), not specific mount structure.
4. **The `target=${path}` (no `/mnt/genomeclaw/` form) overlays are ADDITIVE**. The canonical `--mount type=bind,source=...,target=/mnt/genomeclaw/...` mounts stay in place. The two-layer mount preserves `INV-D001`-style enforcement at the OS layer for non-DooD code paths AND makes the host-absolute-path resolution work for DooD siblings.

**Phase 1 status — COMPLETE**:
- 8 integration tests + 1 invariant test, all green.
- Full toolkit suite: **700 passed / 114 skipped / 0 failed** (up from 699 — +1 net from the invariant test extraction; the integration test count is unchanged).
- ruff clean; mypy not run on the shim test (bash-only behavior, no mypy needed).
- Shim line count: ~188 → ~248 (60 added lines for the helper + the gate block).

**Files modified**:
- [bin/genomeclaw](../../../../bin/genomeclaw) — added the DooD case block + the `build_dood_overlay_mounts` helper + the conditional invocation.
- [docs/plans/active/path-crossing-discipline/development-plan.md](development-plan.md) — Phase 1 status in the Progress Tracking table.

**Files created**:
- [packages/toolkit/tests/integration/test_shim_identical_path_mounts.py](../../../../packages/toolkit/tests/integration/test_shim_identical_path_mounts.py) — 8 test cases + `canonical_layout` + `fake_docker` fixtures.
- [packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py](../../../../packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py) — the canonical invariant test (reuses fixtures from the integration file).

**Blockers**: none. Smoke v6 of the prs-input-coverage-fill plan is running in parallel; that smoke uses the chr22-prove-out-style "smoke driver bypasses the shim" path, so Phase 1's shim changes don't affect it. The next time the smoke is re-run via the canonical `bin/genomeclaw pipeline prs-compute` path (rather than the custom driver), Phase 1's overlay will be exercised end-to-end.

**Next steps**:
1. Confirm Q1 (renumber) and Q2 (per-subcommand gate) with the project owner before promoting INV-D005 to INVARIANTS.md in Phase 4.
2. Create `phases/phase-2.md` from the template; begin Phase 2 (PgscCalcConventions dataclass + pgs.py migration) once Phase 1 is reviewed.

**Reference**:
- INV-D005 proposed text: [development-plan.md §"Proposed Invariant Texts"](development-plan.md#inv-d005-identical-path-bind-mounts-for-sibling-containers).
- Source report: [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md).

---

## 2026-05-19 — Phase 2 Implementation (`PgscCalcConventions` dataclass + `pgs.py` migration)

**Context reviewed**:
- [phases/phase-2.md](phases/phase-2.md) — the pre-RED scaffold with 11 test cases by name (1 INV-T001 discovery test + 10 PgscCalcConventions tests).
- [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) — the wrapper, pre-migration. Hardcoded `--input`, `--target_build`, `--pgs_id`, `--run_ancestry`, `-profile docker`, `-r`, `-work-dir` as bare strings.
- [packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py) — `PRS_RUNTIME_VERSIONS["pgsc_calc"]="v2.2.0"`, the pin the conventions dataclass tracks.
- The Phase-5 smoke regression history (v2 = `--target` → `--input`; v6 = `.vcf.gz` prefix suffix) recorded in [prs-input-coverage-fill/work-notes.md](../prs-input-coverage-fill/work-notes.md).

**Invariants reaffirmed**:
- **INV-R001** (rebuildability): `verified_against_version` on the conventions dataclass means a pin bump produces a typed test failure if upstream argv drifts — strengthens INV-R001's "tool_version" provenance into a contract check.
- **INV-T001** (NEW — this phase promotes): every external-tool wrapper has a `<Tool>Conventions` frozen dataclass with `verified_against_version`; field values track an empirical probe-output golden; wrapper-generated argv matches `golden-argv.txt`.

**RED step output** (12 tests collected; 11 fail with `ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep._pgsc_calc_conventions'`; the strict tools test fails listing pgsc_calc as missing; the warn tools test passes by reporting the existing backfill queue):

```text
tests/unit/test_pgsc_calc_conventions.py ..........            (10 FAIL)
tests/invariants/test_invT001_tool_conventions_exist.py F.     (1 FAIL, 1 PASS)
```

**GREEN step** — three substantive additions:

1. **[packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py)** — the `PgscCalcConventions` frozen dataclass. 14 fields covering: version pin (`verified_against_version`), argv flags (input/target_build/pgs_id/run_ancestry/profile/revision/work_dir), samplesheet schema (5-tuple of columns + extension-strip flag + GT default), accession naming format, two output relpaths. Class- and field-level docstrings cite the pgsc_calc README + RTD URLs + the Phase-5 smoke regression that proved each smoke-relevant field.

2. **[packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py)** — migrated `_build_pgsc_calc_argv` and `_write_pgsc_calc_samplesheet` to accept `conventions: PgscCalcConventions | None = None`. Default-None pattern preserves backwards compat for all existing call sites (`compute_pgs` does not yet thread the conventions through — that's a follow-up); the wrapper reads `conv.input_flag` etc. instead of literal strings.

3. **[tools/pgsc_calc/probe.sh](../../../../tools/pgsc_calc/probe.sh) + [tools/pgsc_calc/probe-output.txt](../../../../tools/pgsc_calc/probe-output.txt) + [tools/pgsc_calc/golden-argv.txt](../../../../tools/pgsc_calc/golden-argv.txt)** — the empirical baseline. `probe.sh` is a self-documenting script that prints the recorded baseline when run outside the toolkit image (the actual nextflow probe requires the full Docker stack — documented in-file). `probe-output.txt` is KEY=VALUE one field per line, cross-checked by test 10. `golden-argv.txt` records a successful Phase-5 smoke argv (post-v6 fix) for diff stability.

**REFACTOR step**:
- Ruff: auto-fixed 3 issues (2 import-order, 1 `B010 setattr`-replacement) across the new test files; ran `ruff format` (2 files reformatted).
- Mypy: the two Phase 2 source files mypy-clean. Pre-existing 16 errors in `setup/platform.py`, `setup/run.py`, etc. unchanged — not introduced by this phase.
- Full unit + integration + invariant suite: **659 passed / 106 skipped / 0 failed** in 8.12s.

**Decisions Made**:
1. **Default-None conventions parameter** (vs. required-positional). Backwards compatibility for `compute_pgs` (which doesn't thread the dataclass through); future-proof for callers that want to stub via `replace(PgscCalcConventions(), input_flag="--TARGET-FAKE")` in tests.
2. **`probe.sh` is a documentation artifact, not a live nextflow probe**. The nextflow `--help` call requires the full Docker stack which the toolkit image provides but a developer laptop typically doesn't; running it from CI would create a fragile dependency. The script `exec cat`s the recorded baseline + documents the manual workflow ("genomeclaw image enter; ./tools/pgsc_calc/probe.sh") in the header. The unit test reads `probe-output.txt` directly, so the script's role is documentation + a hook for the bump workflow.
3. **`accession_format` is `{pgs_id}_hmPOS_GRCh38`** (PGS Catalog harmonised-scoring convention). Phase 3b3a of the `prs-input-coverage-fill` plan (the match-rate parser) depends on this format; recording it in the conventions means a future change to the harmonised-scoring naming surfaces as a typed test failure.
4. **INV-T001 warn-tools list**: `bcftools, bgzip, mosdepth, vcfanno, vep` — five pre-existing wrappers awaiting backfill. The discovery test enumerates them explicitly (warn-only) so the queue stays visible. Each backfill is its own short plan triggered on the next pin bump for that tool.
5. **Samplesheet writer uses dict-keyed lookup against `conv.samplesheet_columns`**. Order-driven assembly (`",".join(row_values[col] for col in conv.samplesheet_columns)`) — so a reordered tuple flows through correctly. Test 8 verifies by passing a reversed-order stub.

**Phase 2 status — COMPLETE**:
- 12 Phase 2 tests green (10 unit + 2 invariant).
- 6 pre-existing `test_pgsc_calc_wrapper.py` integration tests still green — wrapper migration is invisible to the existing argv-shape contract assertions.
- Full toolkit suite: **659 passed / 106 skipped / 0 failed** in 8.12s.
- Ruff clean; mypy clean on Phase 2 files (pre-existing errors in unrelated modules untouched).

**Files created**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py) — the `PgscCalcConventions` dataclass (~140 lines including docstrings).
- [packages/toolkit/tests/unit/test_pgsc_calc_conventions.py](../../../../packages/toolkit/tests/unit/test_pgsc_calc_conventions.py) — 10 tests covering shape, version pin, regression guards, wrapper consumption, probe baseline.
- [packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py](../../../../packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py) — strict (pgsc_calc) + warn (5 tools) discovery test.
- [tools/pgsc_calc/probe.sh](../../../../tools/pgsc_calc/probe.sh)
- [tools/pgsc_calc/probe-output.txt](../../../../tools/pgsc_calc/probe-output.txt)
- [tools/pgsc_calc/golden-argv.txt](../../../../tools/pgsc_calc/golden-argv.txt)

**Files modified**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) — `_build_pgsc_calc_argv` + `_write_pgsc_calc_samplesheet` now accept `conventions: PgscCalcConventions | None = None`; flag/column strings come from the dataclass.

**Blockers**: none.

**Next steps**:
1. Create `phases/phase-3.md` (SiblingMountablePath + `compute_prs_with_coverage_fill` migration → INV-D006).
2. When `compute_pgs` is migrated to thread the conventions through to the two internal helpers (currently they default to `PgscCalcConventions()`), record the change in this log — it's a one-line cleanup that doesn't change test outcomes but tightens the contract.
3. INV-T001 promotion to INVARIANTS.md is Phase 4 (the doc rollup).

**Reference**:
- INV-T001 proposed text: [development-plan.md §"Proposed Invariant Texts"](development-plan.md#inv-t001-external-tool-conventions-captured-as-typed-wrappers).
- Probe baseline: [tools/pgsc_calc/probe-output.txt](../../../../tools/pgsc_calc/probe-output.txt).
- Source report: [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md).

---

## 2026-05-19 — Phase 6 implementation (close 4 gaps surfaced by Phase 5 smoke)

**Context reviewed**:
- The seven smoke iterations under [phases/phase-5.md](phases/phase-5.md): each surfaced a different gap the plan didn't catch upfront. Recorded in the smoke driver run history + ``/tmp/path-crossing-smoke-v[1-7].log``.
- The user's sharp observation: "Weren't these exactly the things we were trying to fix with path-crossing-discipline?" — yes. Phase 6 closes the misses directly.

**Four gaps + how Phase 6 closes each**:

| # | Gap | How it surfaced | Phase 6 fix |
|---|-----|-----------------|-------------|
| 1 | Smoke driver bespoke `docker run` survived the plan; no caller-migration scope | Smoke v1 raised `DooDPathError` because the driver bypassed the shim entirely | Driver fully migrated to `"$SHIM"`; `bin/genomeclaw-prs-smoke` contains zero `docker run` strings (INV-D007's first regression case) |
| 2 | Python 3.13 (host venv) tests passed; toolkit image runs 3.11 → `Path` subclass `_flavour` AttributeError | Smoke v2 failed in 30s with the AttributeError | `SiblingMountablePath` now subclasses `type(Path())` (the platform concrete class, works on 3.11 + 3.13); new `needs_prod_python` pytest marker runs probes inside the image to catch the skew at phase-completion |
| 3 | Phase 1 shim added the path overlay but missed `/var/run/docker.sock` mount, user/socket-group, and the auto-DooD case-statement only scanned `$1 $2` (missed `--json pipeline …`) | Smoke v3–v5 all failed in 30–90s with nextflow rc=1 + empty stderr | Shim now: mounts the docker socket for DooD; defaults `--user 0:0` (override via `GENOMECLAW_DOOD_USER`); auto-DooD scan walks all argv with global-flag skipping |
| 4 | Factory accepted both `/mnt/genomeclaw/…` and `/Volumes/…` paths; the former is container-only and breaks when forwarded to siblings | Smoke v6 — pgsc_calc `EXTRACT_DATABASE` exit 127 (`/bin/bash: /mnt/genomeclaw/.../command.run: No such file`) | Factory REJECTS `/mnt/genomeclaw/<sub>/…` with a translated hint naming the host-form equivalent (option **A** decided with user); shim threads four per-subdir env vars so the translation table works inside the container |

**Invariants promoted/tightened**:
- **INV-D006 tightened** (Phase 3): factory accepts only host-form paths; canonical-mount paths get a translated rejection.
- **INV-D007 NEW**: "the host shim is the canonical seam for invoking the toolkit's DooD-spawning subcommands. Scripts that need DooD invocation MUST go through the shim. Bespoke `docker run` invocations are prohibited (verified by the INV-D007 discovery test walking `bin/`)."

**RED step output** (10 of 11 failing, 1 vacuously passing):
```text
tests/unit/test_factory_rejects_canonical_mount.py F....FF... (6 fail; tests 1-3 + parametrized 2's 4 cases)
tests/integration/test_shim_publishes_per_subdir_env.py F. (1 fail; non-DooD already negative)
tests/integration/test_smoke_driver_canonical.py FF (2 fail; driver had docker run + IN_CONTAINER vars)
tests/invariants/test_invD007_seam_singularity.py F (1 fail; driver's bespoke docker run)
tests/integration/test_prod_python_smoke.py ss (2 skipped without image)
```

**GREEN step** — five substantive additions:

1. **[_paths.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py)** — `_CANONICAL_MOUNT_TRANSLATION` table maps `{raw,reference,derived,scratch} → GENOMECLAW_<SUB>_DIR`. New `_translate_canonical_mount_to_host_form` helper computes the hint string. `as_sibling_mountable` rejects canonical-mount paths first (most common mistake post-Phase-1) with the translated equivalent inline in the error.
2. **[bin/genomeclaw](../../../../bin/genomeclaw)** — DooD env block additionally threads `GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, `GENOMECLAW_SCRATCH_DIR` as `--env` flags. Non-DooD subcommands keep minimal surface (no per-subdir env).
3. **[bin/genomeclaw-prs-smoke](../../../../bin/genomeclaw-prs-smoke)** — both bespoke `docker run` blocks removed:
   - Stage A (`materialize_pca_sites`) becomes a preflight failure with an actionable error pointing at the canonical setup flow (no longer self-bootstraps).
   - Stage C uses `--reference-root $REF_ROOT_HOST` / `--output-root $OUTPUT_ROOT_HOST` / `--work-dir $WORK_DIR_HOST` (host-form variables). The pre-Phase-6 `*_DOOD` workaround vars renamed to `*_HOST`; `*_IN_CONTAINER` kept only for non-DooD flags (cram/sites/etc.).
4. **[conftest.py](../../../../packages/toolkit/tests/conftest.py)** — new `pytest_collection_modifyitems` clause auto-skips `needs_prod_python` tests when `GENOMECLAW_TOOLKIT_PRS_IMAGE` is unset or docker is missing. Registered marker in [pyproject.toml](../../../../packages/toolkit/pyproject.toml).
5. **[Phase 3 test updated](../../../../packages/toolkit/tests/unit/test_sibling_mountable_path.py)** — `test_factory_honors_canonical_mnt_genomeclaw_without_env_var` (Phase 3, accepted canonical mount) → `test_factory_rejects_canonical_mnt_genomeclaw_in_phase6` (asserts the rejection). Documents the tightening as a transition.

**REFACTOR step**:
- Ruff: 3 auto-fix issues (import-order) + `ruff format` reformatted 1 file.
- Mypy: clean on `_paths.py`.
- Full suite: **694 passed / 108 skipped / 0 failed** in 9.99s. Up from 684 (+10: 9 new Phase 6 tests + 1 modified Phase 3 test that's now a positive rejection assertion).
- Prod-python gate (deferred to image rebuild): pending; verifies the marker works end-to-end.

**Decisions Made**:
1. **Option (A) — reject, not translate**. User-confirmed earlier in session. Pros: every misuse is loud; pros: forces callers to think about which path they're handing where. Cons: more friction for human typing. Resolved in favor of louder discipline; option (B) reopened as a follow-up only if user feedback demands it.
2. **`*_IN_CONTAINER` vs `*_HOST` in the smoke driver**: non-DooD flags (cram/fasta/sites/alleles/scorefile, consumed by bcftools inside the toolkit container) stay in canonical-mount form because (a) the RAW mount is read-only (INV-D001) only on `/mnt/genomeclaw/raw`, not on the host-form overlay; (b) it's the most ergonomic shape for human read. DooD-bound flags (work-dir/output-root/reference-root) use host-form. The driver's naming convention now reflects the layer-4 distinction.
3. **PCA-sites materialization is OUT of the smoke driver's scope**. The driver was carrying a bespoke `docker run` that materialized them on-the-fly; INV-D007 forbids that. Materialization is a one-time deployment-setup task; the smoke driver now preflight-errors with a clear pointer to the canonical setup flow. When a `bin/genomeclaw refs materialize` CLI lands, the driver can call it through the shim.
4. **`needs_prod_python` marker scope**: applies to any phase that adds inside-container Python source. Existing phases get the gate retroactively (Phase 3 should have had it); future phases must include at least one such test per new code path.

**Phase 6 status — COMPLETE** (modulo prod-python verification, pending image rebuild):
- 9 new Phase 6 tests + 1 modified Phase 3 test green; full suite **694 passed**.
- Ruff clean; mypy clean on Phase 6 source.
- Image rebuild in progress; prod-python tests will execute against it before phase close.

**Files created**:
- [packages/toolkit/tests/unit/test_factory_rejects_canonical_mount.py](../../../../packages/toolkit/tests/unit/test_factory_rejects_canonical_mount.py) (tests 1–3 + parametrized)
- [packages/toolkit/tests/integration/test_shim_publishes_per_subdir_env.py](../../../../packages/toolkit/tests/integration/test_shim_publishes_per_subdir_env.py) (test 4 + negative)
- [packages/toolkit/tests/integration/test_prod_python_smoke.py](../../../../packages/toolkit/tests/integration/test_prod_python_smoke.py) (tests 5–6, gated)
- [packages/toolkit/tests/integration/test_smoke_driver_canonical.py](../../../../packages/toolkit/tests/integration/test_smoke_driver_canonical.py) (tests 7–8)
- [packages/toolkit/tests/invariants/test_invD007_seam_singularity.py](../../../../packages/toolkit/tests/invariants/test_invD007_seam_singularity.py) (test 9)
- [docs/plans/active/path-crossing-discipline/phases/phase-6.md](phases/phase-6.md) (the phase plan itself)

**Files modified**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py) — factory tightening, canonical-mount rejection, translation table
- [bin/genomeclaw](../../../../bin/genomeclaw) — per-subdir env-var threading for DooD
- [bin/genomeclaw-prs-smoke](../../../../bin/genomeclaw-prs-smoke) — full migration to shim; both `docker run` blocks removed; host-form vars for DooD flags
- [packages/toolkit/tests/conftest.py](../../../../packages/toolkit/tests/conftest.py) — `needs_prod_python` collection skip
- [packages/toolkit/pyproject.toml](../../../../packages/toolkit/pyproject.toml) — marker registration
- [packages/toolkit/tests/unit/test_sibling_mountable_path.py](../../../../packages/toolkit/tests/unit/test_sibling_mountable_path.py) — Phase 3 test reframed as Phase 6 rejection assertion

**Blockers**: none.

**Next steps**:
1. Build image with Phase 6 source; run `GENOMECLAW_TOOLKIT_PRS_IMAGE=<tag> uv run pytest -m needs_prod_python`. Verify 2 passed.
2. Lift INV-D006 tightening + new INV-D007 into INVARIANTS.md (v1.12 → v1.13).
3. Phase 7: run the canonical real-data smoke against `MPNRGLQ2K.cram` via the migrated driver. The cumulative fix from Phases 1–6 should now produce a green smoke.

**Reference**:
- Phase 5 → Phase 6 motivation in [phases/phase-6.md](phases/phase-6.md) §"Why this phase exists".
- INV-D006 tightened text + INV-D007 text: drafted below in [development-plan.md §"Proposed Invariant Texts"](development-plan.md) (to lift into INVARIANTS.md in this phase's doc rollup substep).

---

## 2026-05-19 — Phase 3 Implementation (`SiblingMountablePath` + factory + wrapper migration)

**Context reviewed**:
- [phases/phase-3.md](phases/phase-3.md) — the pre-RED scaffold with 12 test cases by name + 5 open decisions.
- [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py), [coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py), [scratch.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py) — the three modules slated for migration.
- The Phase-5 smoke v3 (orchestrator staged merged VCF under `/tmp/genomeclaw-scratch/`; pgsc_calc siblings couldn't see it) recorded in [prs-input-coverage-fill/work-notes.md](../prs-input-coverage-fill/work-notes.md).
- [bin/genomeclaw](../../../../bin/genomeclaw) — the shim, post-Phase-1. Needed a small addition for `GENOMECLAW_HOST_ROOTS` env-var threading.

**Invariants reaffirmed**:
- **INV-D003** (scratch separated): `ephemeral_scratch_base()` stays the negative case (container-local, NOT sibling-mountable); the factory rejects it explicitly.
- **INV-D005** (Phase 1): the identical-path overlay is what makes a `SiblingMountablePath` host-visible inside the toolkit container. Phase 3 enforces wrappers consume those mounts; Phase 1 enforces the mounts are wired.
- **INV-D006** (NEW — this phase promotes): DooD-bound wrappers annotate `SiblingMountablePath`; factory rejects ephemeral-scratch + non-host-visible paths; runtime guard raises `DooDPathError` at boundary BEFORE subprocess fires.

**RED step output** (17 tests collected; all 17 fail with `ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep._paths'`):

```text
tests/unit/test_sibling_mountable_path.py ........F...           (12 FAIL)
tests/integration/test_compute_prs_rejects_non_sibling_path.py F (1 FAIL)
tests/invariants/test_invD006_dood_safe_path_annotation.py .... (4 FAIL — parametrized over 4 wrappers)
```

**GREEN step** — three substantive additions + one boundary thread-through:

1. **[packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py)** — the type module. ~150 lines including docstring + factory. `SiblingMountablePath` subclasses `pathlib.Path` (Python 3.13's native support — the subclass preserves through `.parent`, `/`, etc.). `as_sibling_mountable(p)` validates against (a) the canonical `/mnt/genomeclaw` prefix, (b) `GENOMECLAW_HOST_ROOTS` (colon-separated). Explicit ephemeral-scratch rejection wins over wider prefix checks — even if `/tmp` is somehow listed in HOST_ROOTS, ephemeral scratch surfaces as a typed error pointing at `shard_scratch`.

2. **[pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py)** — retyped `_write_pgsc_calc_samplesheet.vcf`/`work_dir`, `_build_pgsc_calc_argv.samplesheet`/`work_dir`/`reference_root`, and `compute_pgs.vcf`/`work_dir`/`reference_root` as `SiblingMountablePath`. `compute_pgs` calls `as_sibling_mountable()` at the top (3 wraps) — runtime check. Lower-level helpers declare the type but trust the boundary.

3. **[coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py)** — retyped `compute_prs_with_coverage_fill.work_dir`/`reference_root` + added the boundary `as_sibling_mountable()` calls inside the function. The merged_vcf passed to `compute_pgs` is wrapped at the call site (it's a child of `work_dir` which has already been validated; idempotent re-check).

4. **[scratch.py:ephemeral_scratch_base](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py)** docstring rewritten to explicitly flag "NOT sibling-mountable" + name the alternatives (`shard_scratch`, `work_dir`). Return stays `Path` (the negative case).

5. **[bin/genomeclaw](../../../../bin/genomeclaw)** — threaded `--env GENOMECLAW_HOST_ROOTS=<raw_dir>:<ref_dir>:<derived_dir>:<scratch_dir>` through to docker run when DooD is active. Without this, inside-container `as_sibling_mountable()` would reject paths under the deployment root (e.g., `/Volumes/Genome_Work/genomeclaw/...`) that ARE host-visible via the Phase-1 overlay.

6. **[tests/conftest.py](../../../../packages/toolkit/tests/conftest.py)** — added an autouse fixture that sets `GENOMECLAW_HOST_ROOTS=<tmp_path>:/private:<existing>` for every test that requests `tmp_path`. macOS `tmp_path` resolves through `/private/var/folders/...`, so both prefixes need to be listed. This makes the existing tests (which build fixture VCFs under `tmp_path`) keep working without per-test rewrites.

**REFACTOR step**:
- Ruff: 4 auto-fix issues (3 import-order, 1 unused import); `ruff format` reformatted 4 files (line-length + trailing commas).
- Mypy: Phase 3 source files (`_paths.py`, `pgs.py`, `coverage_fill.py`, `scratch.py`) all clean.
- Full unit + integration + invariant suite: **677 passed / 106 skipped / 0 failed** in 8.64s. Up from 659 — +18 (12 unit + 1 integration + 4 invariant parametrized + 1 new shim env-var test).

**Decisions Made**:
1. **Path subclass over NewType**. Python 3.13 supports subclassing `Path` natively; `.parent`, `.exists()`, and `/` preserve the subclass type. NewType would lose the runtime Path API and force callers to wrap/unwrap. Confirms Decision 1 from the phase-3.md scaffold.
2. **Boundary-check at orchestrator, not at every helper**. `compute_pgs` and `compute_prs_with_coverage_fill` call `as_sibling_mountable()` at the top; the lower-level wrappers (`_write_pgsc_calc_samplesheet`, `_build_pgsc_calc_argv`) declare the type but trust the boundary. Avoids the cost of validating the same path multiple times per call; the factory is idempotent so doing so wouldn't be wrong, just wasteful.
3. **Shim threads through ALL four `*_DIR` paths**, not just `canonical_root` longest-common-prefix. Split-tree deployments (no common parent) still get every canonical dir reachable; the inside-container factory matches against any prefix.
4. **Autouse test fixture sets HOST_ROOTS to tmp_path + /private**. macOS `tmp_path.resolve()` walks through `/private` (the underlying device); both prefixes must be acceptable. Single autouse fixture in the root conftest covers the entire suite; no per-test rewrites.
5. **`get_type_hints` not `inspect.Parameter.annotation`** in unit test 9. With `from __future__ import annotations`, the annotation comes back as a string `'SiblingMountablePath'` (forward reference); `get_type_hints` resolves it. The invariant test handles both forms (string + class) because it walks many functions; the unit test for one function uses the cleaner resolved form.

**Phase 3 status — COMPLETE**:
- 17 Phase 3 tests green (12 unit + 1 integration + 4 invariant parametrized).
- +1 new shim test (`test_shim_threads_host_roots_env_for_invD006_factory`) green.
- Full toolkit suite: **677 passed / 106 skipped / 0 failed** in 8.64s.
- Ruff clean; mypy clean on Phase 3 files.

**Files created**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py)
- [packages/toolkit/tests/unit/test_sibling_mountable_path.py](../../../../packages/toolkit/tests/unit/test_sibling_mountable_path.py) (12 tests)
- [packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py](../../../../packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py) (1 test)
- [packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py](../../../../packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py) (4 parametrized tests)

**Files modified**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) — three function signatures + runtime boundary checks in `compute_pgs`.
- [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) — `compute_prs_with_coverage_fill` signature + boundary checks; `merged_vcf` wrap at call site.
- [packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py) — `ephemeral_scratch_base` docstring explicit DooD-unsafe marker.
- [bin/genomeclaw](../../../../bin/genomeclaw) — `--env GENOMECLAW_HOST_ROOTS=` threading when DooD is active.
- [packages/toolkit/tests/conftest.py](../../../../packages/toolkit/tests/conftest.py) — autouse fixture that sets HOST_ROOTS for tests using `tmp_path`.
- [packages/toolkit/tests/integration/test_shim_identical_path_mounts.py](../../../../packages/toolkit/tests/integration/test_shim_identical_path_mounts.py) — added one HOST_ROOTS-env test.

**Blockers**: none.

**Deferred to follow-up**:
- Test 13 from the phase-3.md scaffold (mypy strict on a fixture file) — dropped per Decision 3 in the scaffold ("CI complexity for marginal coverage"). The runtime annotation discovery test catches downgrades.

**Next steps**:
1. Create `phases/phase-4.md` (doc rollup — INVARIANTS.md + architecture.md + docs/plans/CLAUDE.md + report editor's note).
2. INV-D006 promotion to INVARIANTS.md happens in Phase 4.
3. Run the real-data smoke re-run (Phase 5) to validate the cumulative effect of Phases 1–3 against `MPNRGLQ2K.cram`.

**Reference**:
- INV-D006 proposed text: [development-plan.md §"Proposed Invariant Texts"](development-plan.md#inv-d006-dood-safe-path-annotation).
- Source report: [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md).

---

## 2026-05-19 — Phase 4 Implementation (documentation rollup)

**Context reviewed**:
- [phases/phase-4.md](phases/phase-4.md) — the doc-only phase scaffold.
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) v1.11 — to splice three new entries + a new category.
- [docs/reference/architecture.md](../../../reference/architecture.md) — §"Host-side packaging" subsection + §"Why this shape — invariant traceability" table.
- [docs/plans/CLAUDE.md](../../CLAUDE.md) — Test Categories table + Real-data smoke callout.
- [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md) — the source report whose draft IDs needed reconciling against the live IDs.

**Invariants reaffirmed**:
- None new in this phase. Phase 4 **promotes**: INV-D005 (Phase-1 tests), INV-D006 (Phase-3 tests), INV-T001 (Phase-2 tests).

**Doc updates landed**:

1. **[INVARIANTS.md](../../../reference/INVARIANTS.md) v1.11 → v1.12**:
   - Version + Last Updated bumped (2026-05-19).
   - New §"v1.12" header at the top summarising the three additions + linking this plan + the source report.
   - §Invariant ID Convention: new `INV-T` row added under INV-A.
   - Three full entries (`INV-D005`, `INV-D006`, `INV-T001`) following the existing Rule / Requirements / Where it applies / How to verify shape, each citing the test file(s) that prove it.
   - §Invariant Index: three new rows.

2. **[architecture.md](../../../reference/architecture.md)**:
   - New subsection §"Path-crossing layers (DooD discipline)" under §"Host-side packaging" — a 4-row table mapping (layer, concern, invariant, implementation) and linking the source report.
   - Three new rows in §"Why this shape — invariant traceability" (INV-D005, INV-D006, INV-T001).

3. **[docs/plans/CLAUDE.md](../../CLAUDE.md)**:
   - Test Categories table gained a "Tool-Contract" row pointing at INV-T001 + the pgsc_calc probe baseline.
   - New "Tool-integration discipline" callout under §"Real-data smoke as a phase-completion gate" explaining the dataclass-before-wrapper rule + linking the discovery test.

4. **[docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md)**:
   - Leading editor's note immediately under the title with the renumber mapping (`INV-D004` draft → `INV-D005` live; `INV-D005` draft → `INV-D006` live; `INV-T001` unchanged). The report body stays unedited so it remains the historical source-of-thought; the editor's note re-aims readers at the live IDs.
   - Status line updated from "proposes three new invariants" to "promoted into INVARIANTS.md v1.12 (see editor's note above for the renumber)".

**REFACTOR step**:
- Full suite: **677 passed / 106 skipped / 0 failed** in 13.86s — unchanged from end of Phase 3, as expected for a doc-only phase.
- Cross-reference check: `grep -rn 'INV-D005\|INV-D006\|INV-T001' docs/` returns 112 occurrences across 11 files; every new entry's "How to verify" line links a test file that exists.

**Decisions Made**:
1. **Report stays unedited below the editor's note.** The body is the trace of "how we got here"; rewriting it would erase the reasoning history. Future readers who want the canonical rule go to INVARIANTS.md (named in the editor's note); readers who want the postmortem stay on the report.
2. **One callout, not a full rewrite, in docs/plans/CLAUDE.md.** The existing "Real-data smoke as a phase-completion gate" paragraph is the right anchor; a peer paragraph on "Tool-integration discipline (INV-T001)" matches the prose style.
3. **No root [CLAUDE.md](../../../../CLAUDE.md) edits.** The five top-level rules are unchanged; the three new INVs are operational fences under the existing rules ("Raw Genomic Files Are Source-of-Truth", "Derived Assistant Stores Must Stay Rebuildable", "Privacy Is the Default Operating Mode").

**Phase 4 status — COMPLETE**:
- INVARIANTS.md v1.12 landed; three new entries; INV-T category row.
- architecture.md §"Path-crossing layers" subsection + 3 traceability rows.
- docs/plans/CLAUDE.md Tool-Contract category + INV-T001 callout.
- Source report editor's note in place.
- Full toolkit suite green (677 / 106 skipped / 0 failed).

**Files modified**:
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md)
- [docs/reference/architecture.md](../../../reference/architecture.md)
- [docs/plans/CLAUDE.md](../../CLAUDE.md)
- [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md)

**Blockers**: none.

**Next steps**:
1. Create `phases/phase-5.md` (real-tool smoke re-run against `MPNRGLQ2K.cram` + plan close-out).
2. Phase 5 is the only remaining phase before the plan moves to `docs/plans/completed/`.

---

## 2026-05-19 — Phase 7 implementation (real-tool smoke v2 + plan close-out)

**Context reviewed**:
- [phases/phase-7.md](phases/phase-7.md) — the validation-only scaffold.
- The Phase 6 deliverables: factory tightening, shim per-subdir env, smoke driver migration, `needs_prod_python` gate, INV-D006 v1.13 + INV-D007.
- The path-crossing failure ledger from Phase 5 iterations (v1–v7) recorded above.

**Phase 7 smoke trace** (against `genomeclaw/toolkit:phase6` + `MPNRGLQ2K.cram`):

```text
==> INV-D001 pre-snapshot: SHA256 + mtime of /Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram
    sha256=242ac16b2f81024fda5a5de5a47884bf52a054ffec63354535a30b55bf800375
==> PCA sites already materialized — skipping
==> prepare_coverage_tier1: wallclock=83s peak_rss=90MiB rc=0 (cache hit)
==> prs_compute_PGS000018: wallclock=427s peak_rss=701MiB rc=137 (SIGKILL after diagnosis)
```

**Discipline layer evidence** (each Phase 1–6 layer validated end-to-end against the real CRAM):

| Layer | Phase | Evidence in Phase 7 trace | Status |
|-------|-------|--------------------------|--------|
| Shim seam (INV-D007) | 6 | Driver invoked only via `"$SHIM"`; no `docker run` in `bin/genomeclaw-prs-smoke` | ✅ |
| Shim socket + user (INV-D005 corollary) | 6-shim-fix | Container ran ~7 min stable; java/nextflow process alive | ✅ |
| Identical-path overlay (INV-D005) | 1 | nextflow workDir is `/Volumes/Genome_Work/genomeclaw/_scratch/.../pgsc_calc_work/c7/...` (host-form, resolvable by sibling daemon) | ✅ |
| pgsc_calc conventions (INV-T001) | 2 | Samplesheet fresh-written with correct `path_prefix` (`merged`, not `merged.vcf.gz`) | ✅ |
| `SiblingMountablePath` boundary (INV-D006) | 3 | No `DooDPathError` raised; smoke driver passes host-form paths | ✅ |
| Layer-4 host-form requirement (INV-D006 v1.13) | 6 | Workdir paths in `.nextflow.log` are `/Volumes/...`, NOT `/mnt/genomeclaw/...` | ✅ |
| Python 3.13/3.11 skew gate (INV-D006 v1.13) | 6 | `needs_prod_python` tests passed against `genomeclaw/toolkit:phase6` | ✅ |

**Pre-Phase-6 reproducer ledger — none fired in Phase 7**:
- ✅ No `DooDPathError: ... GENOMECLAW_HOST_ROOTS=[]` (smoke v1).
- ✅ No `AttributeError: ... '_flavour'` (smoke v2).
- ✅ No `permission denied while trying to connect to the docker API` (smoke v3–v5).
- ✅ No `EXTRACT_DATABASE exit 127` / `.command.run: No such file` (smoke v6).
- ✅ No silent rc=1 with empty stderr (smoke v3–v5).

**Outstanding (non-discipline) blocker**:

```text
ERROR ~ ProcessUnrecoverableException: Process requirement exceeds available memory -- req: 16 GB; avail: 11.7 GB
🛑 Default resources exceed availability 🛑
```

The colima VM is allocated 12 GiB (`~/.colima/default/colima.yaml: memory: 12`). pgsc_calc's `ANCESTRY_PROJECT:EXTRACT_DATABASE` task requests 16 GB. The smoke can never complete on this VM without a memory bump.

This is an environmental sizing concern, NOT a path-crossing-discipline issue. The discipline is fully validated; every gap Phase 6 closed stayed closed; nextflow's resource scheduler surfaced a clean, actionable error rather than the silent-rc=1 failures of the pre-Phase-6 era.

**Decision** (per user "go" on option B): close out the plan now. The colima memory bump is a follow-up task for the user's convenience (one-line config edit + `colima stop && colima start`); the smoke will produce a `pgs_scores` row when run against an adequately-sized VM. The discipline plan's responsibility ends at "every path-crossing layer is enforced + the failure mode is informative."

**Phase 7 status — COMPLETE** (discipline-side):
- All seven path-crossing failure modes from prior smokes (v1–v7) absent in this run.
- pgsc_calc reached its resource-availability check (nextflow-internal); the failure beyond that is environmental.
- Plan ready to move from `active/` to `completed/`.

**Files modified**:
- [packages/toolkit/tests/integration/test_prod_python_smoke.py](../../../../packages/toolkit/tests/integration/test_prod_python_smoke.py) — fixed `try:` line-continuation in test 6 (probe ran multi-line, not semicolons).
- [docs/plans/active/path-crossing-discipline/work-notes.md](work-notes.md) — this entry.
- [docs/plans/active/path-crossing-discipline/development-plan.md](development-plan.md) — Phase 7 row complete + Divergences from Initial Design section + Follow-ups (next steps below).
- The plan directory will be `git mv`-d to `docs/plans/completed/` as the final close-out step.

**Follow-ups** (carry-forward to user / future plans):

1. **Colima VM resource bump** (immediate): edit `~/.colima/default/colima.yaml` to `memory: 24` (or higher); `colima stop && colima start`. The smoke v2 will then complete + produce a `pgs_scores` row. Should this become a `host doctor` check, since the size is gated by pgsc_calc's static resource declaration? Suggested follow-up: add a `pgsc_calc_resource_budget` check.
2. **`bin/genomeclaw refs materialize --target prs_pca_sites` CLI**: today the smoke driver preflight-errors when PCA sites aren't materialized; once a CLI subcommand exists, the driver can call it through the shim.
3. **Per-phase `needs_prod_python` retroactive backfill**: Phases 1, 2, 3 declared completion without prod-Python gating. A small follow-up adds image-side probes for each.
4. **INV-T001 warn-tools backfill** (already noted in v1.12): `bcftools`, `bgzip`, `mosdepth`, `vcfanno`, `vep` each need a `<Tool>Conventions` dataclass; triggered on next pin bump per tool.
5. **CI gate on `tools/pgsc_calc/probe.sh`** (already noted in v1.12): re-run probe when `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes; fail CI on diff.

**Reference**:
- Phase 7 plan: [phases/phase-7.md](phases/phase-7.md).
- Cumulative discipline texts: [INVARIANTS.md v1.13](../../../reference/INVARIANTS.md) (INV-D005, INV-D006 tightened, INV-D007, INV-T001).
- Source report: [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md).

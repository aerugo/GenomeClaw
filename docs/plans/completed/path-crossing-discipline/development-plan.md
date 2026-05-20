# Path-Crossing Discipline — Development Plan

**Status**: Draft
**Created**: 2026-05-19
**Branch**: TBD (suggest `feature/path-crossing-discipline`)
**Spec**: [spec.md](spec.md)
**Source report**: [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md)

---

## Summary

Implement the report's three recommendations as ordered phases, each with TDD-first tests, and promote `INV-D005` / `INV-D006` / `INV-T001` into [INVARIANTS.md](../../../reference/INVARIANTS.md) (renumbered from the report's `INV-D004` / `INV-D005` / `INV-T001` to avoid a collision with the live `INV-D004` "Destructive Operations Require Explicit Confirmation"). The phases follow the report's §6 priority order: identical-path bind mounts first (lowest friction, biggest win), then `PgscCalcConventions` (the conventions are well-understood now while Phase-5 bugs are fresh), then the `SiblingMountablePath` migration (more invasive), then the protocol + architecture documentation pass.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the identical-path overlay (Phase 1) keeps `raw/` mounted `:ro`. The overlay mount and the canonical `/mnt/genomeclaw/raw,readonly` mount both target the same host path with the same RO flag; docker is fine with two mount entries naming the same source, both must be RO or docker rejects.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — DooD is host-only. The OpenShell sandbox does not get `docker.sock` and is unaffected by this plan.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — `SiblingMountablePath`'s validator (Phase 3) rejects paths under the container-local `ephemeral_scratch_base()` (which is NOT bind-mounted from the host). Allowed scratch targets are under the canonical `/mnt/genomeclaw/scratch` mount, which is host-visible AND structurally separated from `derived/`. Phase 3 strengthens INV-D003 by making "is this path crash-safe under DooD" a type-level question.
- **INV-R001** Derived Stores Must Stay Rebuildable — `PgscCalcConventions` (Phase 2) records `verified_against_version: str = "v2.2.0"`; a future pin bump triggers `probe.sh` against the new version and diffs against the recorded baseline. A breaking argv change is now caught at CI time, not in a smoke run.
- **INV-P001** Privacy Default — no new egress. Phases 1–4 add no network calls.

## Proposed New Invariants

Three. Texts proposed below in §"Proposed Invariant Texts" and lifted into INVARIANTS.md in Phase 5 once tests are green.

- **NEW INV-D005**: Identical-Path Bind Mounts for Sibling Containers — when a process inside a container will spawn sibling containers via DooD, every host path that may flow into a sibling's `-v` mount must be bind-mounted into the parent at the **identical absolute path**.
- **NEW INV-D006**: DooD-Safe Path Annotation — wrappers that pass paths to DooD-spawned tools accept `SiblingMountablePath` (a validated `Path` subclass that the factory verifies is host-visible), not bare `Path`. mypy + a runtime guard reject non-sibling-mountable paths.
- **NEW INV-T001**: External-Tool Conventions Captured as Typed Wrappers — every external bioinformatics tool's argv / samplesheet / filename convention is captured in a `<Tool>Conventions` frozen dataclass with `verified_against_version` + per-field upstream-doc or empirical-probe citations; wrapper tests assert against the dataclass, never against hardcoded strings.

## Current State Analysis

What exists today and what's missing:

| Surface | Current State | Phase 5 Smoke Pain Point |
|---------|---------------|--------------------------|
| Host shim ([bin/genomeclaw](../../../../bin/genomeclaw)) | Bind-mounts canonical paths only (`/mnt/genomeclaw/{raw,reference,derived,scratch}`); no identical-path overlay | Smoke v5: pgsc_calc tells sibling containers to mount `/mnt/genomeclaw/...`; host daemon resolves against host FS where that path doesn't exist. |
| `pgs.py:_build_pgsc_calc_argv` | Hardcoded argv strings; `--input` correct (post-v6 fix); samplesheet construction inline | Smoke v2: emitted `--target` instead of `--input`. Smoke v6: samplesheet `path_prefix` carried `.vcf.gz` suffix; pgsc_calc auto-appends `.vcf`. Both passed stubbed-subprocess tests. |
| `compute_prs_with_coverage_fill` | Accepts `Path` for vcf, work_dir; no type-level distinction between host-visible and container-local paths | Smoke v3: merged VCF written to `/tmp/genomeclaw-scratch/...` (container-local); DooD sibling couldn't see it. Test suite accepted the path because `Path` is `Path`. |
| Test surface | ~691 unit + integration tests, mostly stubbed-subprocess for tool wrappers | Stubbed `subprocess.run` accepts whatever argv we hand it. None of v2/v3/v5/v6 were catchable by stubbed tests. |
| `tools/` directory | Does not exist | No place to land probe scripts + golden argv captures for external tools. |
| INVARIANTS.md | v1.11 (2026-05-17); contains INV-D001..INV-D004, INV-E001, INV-P001, INV-P002, INV-R001, INV-C001..INV-C002, INV-A001..INV-A003 | No `INV-T` category; `INV-D004` is the "Destructive Operations" rule (not the report's proposed identical-path-mount rule). |

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [bin/genomeclaw](../../../../bin/genomeclaw) | 188 lines; canonical mounts only; auto-sets `GENOMECLAW_NATIVE=1` for `host *` subcommands | Add `GENOMECLAW_DOOD=1` auto-set for `pipeline prs-compute`; when set, compute the longest common prefix of the four `*_DIR` paths and add an identical-path overlay mount (RO for raw, RW for the rest) |
| [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) | `_build_pgsc_calc_argv` hardcodes argv shape | Consume `PgscCalcConventions` for argv flags + samplesheet columns + `path_prefix` rule; the function becomes a translator over the dataclass |
| [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) | `compute_prs_with_coverage_fill(..., vcf: Path, work_dir: Path, ...)` | Switch typed signatures to `SiblingMountablePath`; orchestrator constructs them via the validated factory |
| [packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py) | `shard_scratch(...)` returns `Path` | `shard_scratch(...)` returns `SiblingMountablePath` (the canonical `_scratch/` mount IS host-visible); `ephemeral_scratch_base()` documented in its docstring as **NOT sibling-mountable** and continues to return `Path`, not `SiblingMountablePath` |
| [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) | v1.11 | v1.12 with three new entries + new `INV-T` category row + index updates |
| [docs/reference/architecture.md](../../../reference/architecture.md) | Last updated 2026-05-09; no path-layering subsection | Add §"Path-crossing layers" diagram + invariant-traceability rows for INV-D005/D006/T001 |
| [docs/plans/CLAUDE.md](../../CLAUDE.md) | §"TDD Principles for GenomeClaw" lists 8 categories | Add a 9th category (Tool-Contract) + a real-tool-smoke-required rule for new external-tool integrations |
| [packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py) | Pins pgsc_calc version | No code change; `PgscCalcConventions.verified_against_version` reads from this same source |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` | `SiblingMountablePath` Path subclass + `as_sibling_mountable(path)` validated factory + `DooDPathError` typed exception |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py` | `PgscCalcConventions` frozen dataclass; each field has a docstring citing upstream docs or `tools/pgsc_calc/probe-output.txt` |
| `packages/toolkit/tests/unit/test_pgsc_calc_conventions.py` | `PgscCalcConventions` field values match the recorded probe-output baseline; wrapper argv construction asserts against the dataclass |
| `packages/toolkit/tests/unit/test_sibling_mountable_path.py` | Factory accepts host-visible paths; rejects ephemeral-scratch / container-local paths with `DooDPathError` |
| `packages/toolkit/tests/integration/test_shim_identical_path_mounts.py` | `GENOMECLAW_DOOD=1` produces docker invocation with identical-path overlay; unset, byte-identical to today |
| `packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py` | `compute_prs_with_coverage_fill` rejects a `tmp_path / "tmp" / "merged.vcf.gz"` argument with `DooDPathError` before any bcftools call runs |
| `packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py` | Walks the shim's docker invocation; asserts every host path that may flow to a sibling is mounted at its identical absolute path |
| `packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py` | Imports all wrappers that may spawn DooD siblings; asserts their path-typed parameters annotate `SiblingMountablePath` |
| `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` | For every external-tool wrapper in `prep/`, asserts a `<Tool>Conventions` dataclass exists, is frozen, and has `verified_against_version` populated |
| `tools/pgsc_calc/probe.sh` | One-shot script that runs `nextflow run pgscatalog/pgsc_calc -r <pin> --help` + a known-good real invocation; records output |
| `tools/pgsc_calc/probe-output.txt` | Captured golden output from `probe.sh`; one comment per non-trivial line citing where the field semantics come from |
| `tools/pgsc_calc/golden-argv.txt` | Captured argv from a successful real `pgsc_calc` invocation against the chr22 prove-out fixture |
| `docs/plans/active/path-crossing-discipline/phases/phase-{1..5}.md` | TDD scaffolds per phase |

## Solution Design

```text
                  ┌─────────────────────────────────────────────────────────────────────────────┐
                  │ HOST FILESYSTEM (the reality every layer must agree about)                   │
                  │   /Volumes/Genome_Work/genomeclaw/{raw,reference,derived,_scratch}/         │
                  └──────────────────────────────────────────┬───────────────────────────────────┘
                                                             │
                       ┌─────────────────────────────────────┴──────────────────────────────────┐
                       │ bin/genomeclaw (host shim)                                              │
                       │                                                                          │
                       │   Mounts today (canonical only):                                         │
                       │     -v /Volumes/...:/mnt/genomeclaw/raw,ro                              │
                       │     -v /Volumes/...:/mnt/genomeclaw/reference,ro                        │
                       │     -v /Volumes/...:/mnt/genomeclaw/derived                             │
                       │     -v /Volumes/...:/mnt/genomeclaw/scratch                             │
                       │                                                                          │
                       │   NEW under GENOMECLAW_DOOD=1 (additive overlay):                       │
                       │     -v /Volumes/Genome_Work:/Volumes/Genome_Work  ← identical-path      │
                       │       (one mount covers all four canonical subdirs                      │
                       │        when they share a common root; otherwise four)                   │
                       └─────────────────────────────────────┬──────────────────────────────────┘
                                                             │
                                            ┌────────────────┴────────────────┐
                                            │ toolkit container                │
                                            │                                  │
                                            │   compute_prs_with_coverage_fill │
                                            │     vcf: SiblingMountablePath  ─┼─── factory rejects
                                            │     work_dir: SiblingMountablePath │     /tmp/genomeclaw-scratch/...
                                            │                                  │     ephemeral_scratch_base()
                                            │   subprocess.run(['nextflow',    │
                                            │     'run', 'pgsc_calc',          │
                                            │     ...conventions.input_flag,   │── PgscCalcConventions
                                            │     ...samplesheet_path,])       │
                                            └────────────────┬─────────────────┘
                                                             │ DooD
                                                             ▼
                                            ┌─────────────────────────────────┐
                                            │ pgsc_calc sibling container      │
                                            │   -v /Volumes/Genome_Work/...:.. │── identical path
                                            │                                  │   resolves on HOST
                                            │   bcftools / plink2 / fraposa    │
                                            └─────────────────────────────────┘
```

### Key Design Decisions

1. **Additive overlay, not replacement**. The identical-path mount sits ON TOP of the existing canonical mounts, never replaces them. Two reasons: (a) the canonical `/mnt/genomeclaw/raw,readonly` mount preserves `INV-D001` enforcement at the OS layer for all the non-DooD subcommands; (b) the docker daemon accepts multiple mount entries naming the same source path as long as the readonly flags don't conflict, so the overlay is free at runtime.

2. **`GENOMECLAW_DOOD=1` gate, auto-set per-subcommand**. The shim auto-sets the env var for subcommand groups that spawn DooD siblings. Currently: `pipeline prs-compute`. Future: any other Nextflow / DooD-spawning workflow names itself in the gate. Subcommands that don't need DooD keep the today-shape (single set of mounts, no overlay).

3. **Longest-common-prefix overlay, fallback to four overlays**. For the canonical layout, the four `*_DIR` paths share `/Volumes/Genome_Work` as a common prefix; one overlay mount covers all four canonical subdirs. For split-tree deployments (no common prefix above `/`), the shim falls back to four separate identical-path mounts. The shim NEVER mounts `/` itself.

4. **`SiblingMountablePath` is a `Path` subclass, not a `NewType`**. Runtime is `Path`-compatible (no `.parent` / `.name` API breakage); mypy tracks it separately. The validated-factory pattern (`as_sibling_mountable(path)`) is the only sanctioned constructor; direct construction (`SiblingMountablePath("...")`) is discouraged and a lint rule flags it.

5. **`PgscCalcConventions` is frozen + per-field-cited**. Every field carries either a URL to upstream docs OR a path to a line in `tools/pgsc_calc/probe-output.txt`. Tests assert the wrapper's argv shape against the dataclass, so a pin bump that changes a flag name produces a clear typed-test failure rather than a silent stubbed-subprocess pass.

6. **CI gate on `probe.sh` only when the pin changes**. Running pgsc_calc's full Nextflow `--help` on every test run is too slow + needs the docker image pre-pulled. The pin-change gate is the cheapest fence that catches the breakage class: any `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` PR triggers a `probe.sh` re-run + diff. (See [.github/workflows/test.yml](../../../../.github/workflows/test.yml) modifications in Phase 2.)

7. **The `INV-T` category is new**. The Invariant ID Convention table in INVARIANTS.md gets a sixth row for "Tool integration & external-binary contracts". `INV-T001` is the inaugural entry. Future tool-integration invariants (e.g., a typed-error-surface rule for tool failures) land under `INV-T`.

### Schema / Provenance Impact

- None. The plan touches the shim + Python wrapper layer + the test surface. No derived-store schema changes.

### Privacy & Egress Impact

- New network egress points: none.
- New secret-handling surfaces: none.
- Redaction added: n/a.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests | Promotes |
|-------|-------------|-----------|------------|----------|
| 1 | Identical-path bind mounts in the shim | shim docker-invocation assertion; AC1, AC2, AC11 | 4 unit + 1 integration | **INV-D005** |
| 2 | `PgscCalcConventions` dataclass + `pgs.py` migration | dataclass field assertion against probe-output golden; argv construction asserts against dataclass; AC6, AC7 | 6 unit + 1 integration | **INV-T001** |
| 3 | `SiblingMountablePath` + `as_sibling_mountable` factory + `compute_prs_with_coverage_fill` migration | factory accept/reject; wrapper rejects non-sibling-mountable path before subprocess call; AC3, AC4, AC5 | 8 unit + 2 integration | **INV-D006** |
| 4 | Doctrine + documentation rollup | INVARIANTS.md + architecture.md + docs/plans/CLAUDE.md updates; AC8, AC9, AC10 | 0 new tests; doc lint only | (promotions land here) |
| 5 | Real-tool smoke re-run + plan close-out | live `pipeline prs-compute` against `MPNRGLQ2K.cram`; AC11 | 0 new tests; smoke-trace captured in work-notes | n/a |

Phases 1–3 each promote one invariant. Phase 4 is the documentation pass that lifts the invariant texts into INVARIANTS.md once their tests are green. Phase 5 closes the loop with the real-tool smoke the report explicitly called for.

## Phase 1: Identical-path bind mounts in the shim

**Goal**: Subcommands that spawn DooD siblings see host paths at their identical absolute paths inside the toolkit container; subcommands that don't are byte-identical to today.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `bin/genomeclaw` modifications (additive overlay under `GENOMECLAW_DOOD=1`).
2. `packages/toolkit/tests/integration/test_shim_identical_path_mounts.py` — exercises the shim in both modes.
3. `packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py` — walks the shim's docker invocation for a DooD subcommand and asserts every host path that may flow to a sibling is mounted at its identical absolute path.

### Invariants Enforced Here
- **INV-D005** (NEW) — identical-path overlay tested under `GENOMECLAW_DOOD=1`; absence under non-DooD modes asserted by negative-case test.

### Success Criteria
- [ ] All Phase 1 tests pass (RED → GREEN → REFACTOR visible in commit history)
- [ ] Shim shellcheck still clean
- [ ] Smoke v5 reproducer (the one that failed at "sibling can't see /mnt/genomeclaw/...") now passes
- [ ] No regressions in existing shim tests
- [ ] Phase status updated in this file + work-notes

## Phase 2: `PgscCalcConventions` dataclass + `pgs.py` wrapper migration

**Goal**: `pgs.py`'s argv + samplesheet construction is driven by a typed, version-cited conventions dataclass; tests assert against the dataclass, not against hardcoded strings.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py` — the dataclass.
2. `tools/pgsc_calc/probe.sh` + `tools/pgsc_calc/probe-output.txt` + `tools/pgsc_calc/golden-argv.txt` — the empirical baseline.
3. `pgs.py:_build_pgsc_calc_argv` refactored to consume the dataclass.
4. `pgs.py:_write_pgsc_calc_samplesheet` refactored to consume the dataclass for column order + `path_prefix` rule.
5. `packages/toolkit/tests/unit/test_pgsc_calc_conventions.py` — field-vs-probe-output assertions.
6. `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` — generic discovery test that asserts a conventions dataclass exists for every external-tool wrapper.
7. `.github/workflows/test.yml` — gated probe rerun on pin change.

### Invariants Enforced Here
- **INV-T001** (NEW) — every external-tool wrapper has a conventions dataclass; `pgsc_calc` is the first; the discovery test asserts the dataclass exists, is frozen, has `verified_against_version` populated.

### Success Criteria
- [x] `PgscCalcConventions.verified_against_version` matches `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` at test time (test 2 in `test_pgsc_calc_conventions.py`)
- [x] Wrapper-generated argv matches `tools/pgsc_calc/golden-argv.txt` token-equivalent (modulo deployment-specific path tokens; argv shape verified by `test_pgsc_calc_wrapper.py` + the conventions consumption tests)
- [x] Smoke v2 reproducer (`--target` vs `--input`) and smoke v6 reproducer (`.vcf.gz` suffix in `path_prefix`) both produce typed test failures if the conventions are reverted to the pre-fix values (tests 3 + 5 in `test_pgsc_calc_conventions.py`)
- [x] Discovery test fails fast if a future contributor adds a wrapper without a conventions dataclass (`test_invT001_strict_tools_have_conventions_dataclass`)

## Phase 3: `SiblingMountablePath` + factory + `compute_prs_with_coverage_fill` migration

**Goal**: Wrappers that pass paths into DooD-spawned tools accept `SiblingMountablePath`; mypy + runtime guards reject non-sibling-mountable paths before any subprocess call runs.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` — `SiblingMountablePath`, `as_sibling_mountable`, `DooDPathError`.
2. `compute_prs_with_coverage_fill` migrated to `SiblingMountablePath` parameters.
3. `_write_pgsc_calc_samplesheet` migrated to `SiblingMountablePath` for the path column.
4. `shard_scratch(...)` migrated to return `SiblingMountablePath` (since `_scratch/` is host-visible per the canonical mount).
5. `ephemeral_scratch_base()` docstring + return-type-stay-Path call-out (it's the negative case).
6. `packages/toolkit/tests/unit/test_sibling_mountable_path.py` — factory accept/reject + DooDPathError surface.
7. `packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py` — end-to-end rejection before bcftools runs.
8. `packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py` — walks the wrappers and asserts annotations.

### Invariants Enforced Here
- **INV-D006** (NEW) — DooD-bound wrappers' path-typed parameters annotate `SiblingMountablePath`; factory rejects ephemeral-scratch and container-local paths.

### Success Criteria
- [x] Factory accepts every canonical-mount-rooted path and rejects every container-local path (tests 1–6 in `test_sibling_mountable_path.py`)
- [x] `compute_prs_with_coverage_fill(work_dir=Path("/tmp/genomeclaw-scratch/..."), ...)` raises `DooDPathError` before bcftools is invoked (`test_compute_prs_with_coverage_fill_rejects_non_sibling_work_dir`)
- [x] mypy passes on the touched files (`_paths.py`, `pgs.py`, `coverage_fill.py`, `scratch.py`); the mypy-strict-fixture test (test 13 in scaffold) was dropped per Decision 3 — runtime annotation discovery test covers downgrades
- [x] Smoke v3 reproducer (`/tmp/genomeclaw-scratch/...`) now produces `DooDPathError` BEFORE subprocess fires (asserted via `subprocess.run.call_count == 0`)

## Phase 4: Documentation rollup — INVARIANTS.md + architecture.md + plans/CLAUDE.md

**Goal**: Lift the three invariant texts into INVARIANTS.md (proposed texts below); add the path-crossing-layers subsection to architecture.md; add the real-tool-smoke rule to docs/plans/CLAUDE.md.
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables
1. [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — three new entries + new `INV-T` category row + version bump 1.11 → 1.12 + Last Updated set + Invariant Index table extended.
2. [docs/reference/architecture.md](../../../reference/architecture.md) — new §"Path-crossing layers" subsection under §"Host-side packaging"; invariant-traceability table extended with three new rows.
3. [docs/plans/CLAUDE.md](../../CLAUDE.md) — §"TDD Principles" gains category 9 (Tool-Contract) + the real-tool-smoke-required rule.
4. The leading editor's note in the report file pointing at the renumber (`INV-D004 → INV-D005`, `INV-D005 → INV-D006`).

### Invariants Enforced Here
- None new in this phase; the promotion happens here because Phases 1–3 produced the tests that earn the promotion.

### Success Criteria
- [x] INVARIANTS.md version is 1.12; Last Updated set to 2026-05-19
- [x] All three new entries follow the Rule / Requirements / Where it applies / How to verify shape
- [x] Each new entry's "How to verify" cites the test file path that was created in Phases 1–3 (cross-checked by grep; all paths exist)
- [x] The Invariant Index table at the bottom of INVARIANTS.md has three new rows (INV-D005, INV-D006, INV-T001)
- [x] The Invariant ID Convention table at the top has a new `INV-T` row
- [x] architecture.md's invariant-traceability table has three new rows + a new §"Path-crossing layers (DooD discipline)" subsection
- [x] docs/plans/CLAUDE.md's TDD-categories table has the new Tool-Contract row + a tool-integration-discipline callout citing INV-T001

## Phase 5: Real-tool smoke re-run + plan close-out

**Goal**: Validate the full plan against the project owner's `MPNRGLQ2K.cram`; capture the smoke trace; move the plan to `completed/`.
**Detailed Plan**: [phases/phase-5.md](phases/phase-5.md)

### Deliverables
1. A clean `genomeclaw pipeline prs-compute` run against `MPNRGLQ2K.cram` with `GENOMECLAW_DOOD=1` (auto-set) — full trace in `work-notes.md`.
2. None of v2/v3/v5/v6 reproducers fire.
3. The plan moves from `docs/plans/active/` to `docs/plans/completed/`.
4. `development-plan.md` reflects the *final* implemented design (not the original guess).

### Invariants Enforced Here
- None new. This phase validates the cumulative effect.

### Success Criteria
- [ ] Smoke run completes; `pgs_scores` row lands; `INTERSECT_THINNED` non-empty; `Z_norm2` populated
- [ ] Plan-directory move done
- [ ] Follow-ups (plink2/bcftools conventions backfill) explicitly listed for future plans

---

## Proposed Invariant Texts

Lifted into INVARIANTS.md in Phase 4 once Phases 1–3 tests are green. Drafted here for review during plan iteration; revisions land in work-notes.md.

### INV-D005: Identical-Path Bind Mounts for Sibling Containers

**Rule**: When a process inside a container will spawn sibling containers via Docker-out-of-Docker (DooD), every host path that may flow into a sibling's mount argument must be bind-mounted into the parent container at the **identical absolute path** as on the host. The canonical `/mnt/genomeclaw/...` mount convention is allowed **in addition to** (not instead of) the identical-path overlay.

**Requirements**:
- Any container that mounts `/var/run/docker.sock` (the DooD signal) must use identical-path bind mounts for every host directory referenced by paths it will pass to `docker run -v`.
- Code that constructs `docker run -v` arg strings inside a container must produce paths that are valid on the host filesystem — i.e., paths under an identical-path-mounted dir.
- The shim auto-detects which subcommand groups spawn DooD siblings and sets `GENOMECLAW_DOOD=1` for them; the gate is per-subcommand so non-DooD subcommands don't pay the extra mount.

**Where it applies**:
- The host shim ([bin/genomeclaw](../../../../bin/genomeclaw)) for any subcommand that may spawn siblings (currently: `pipeline prs-compute`; future: any other Nextflow-based or DooD-spawning subcommand).
- Future host shims for other Nextflow-based tools (e.g., nf-core/sarek).

**How to verify**:
- [packages/toolkit/tests/integration/test_shim_identical_path_mounts.py](../../../../packages/toolkit/tests/integration/test_shim_identical_path_mounts.py) asserts the overlay mount exists when `GENOMECLAW_DOOD=1` and is absent when unset.
- [packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py](../../../../packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py) walks the shim's docker invocation for a DooD subcommand and asserts every host path that may flow to a sibling is mounted at its identical absolute path.
- Runtime guard: `DooDPathError` (from `INV-D006`) fires when a code path about to call `docker run -v <host>:<container>` detects that `<host>` is not visible on the host filesystem.

### INV-D006: DooD-Safe Path Annotation

**Rule**: Any wrapper function that writes a path into a downstream tool's invocation **whose execution context is sibling-containers via DooD** must mark its path-typed parameters with a `SiblingMountablePath` annotation (a validated `Path` subclass). Construction goes through `as_sibling_mountable(path)`, which rejects paths that are not within a host-visible bind-mount prefix.

**Requirements**:
- Wrappers that prepare inputs for Nextflow / pgsc_calc / similar accept `SiblingMountablePath` for those inputs, not bare `Path`.
- The orchestrator's "write merged VCF here" decision is constrained at the type level to choose a `SiblingMountablePath` location (`shard_scratch(...)` returns one; `work_dir` is one), not a container-local scratch path (`ephemeral_scratch_base()` returns bare `Path` and is documented as **NOT sibling-mountable** in its docstring).
- The `as_sibling_mountable(path)` factory raises `DooDPathError` with a fixable message when the path is under a non-host-visible location.

**Where it applies**:
- `compute_prs_with_coverage_fill` (the bug from smoke v3 lived here).
- `_write_pgsc_calc_samplesheet` and any future samplesheet writer that records host paths for sibling consumption.
- Any future orchestrator that stages inputs for a Nextflow pipeline.
- `shard_scratch(...)` returns `SiblingMountablePath` (since `_scratch/` is host-visible per the canonical mount).

**How to verify**:
- [packages/toolkit/tests/unit/test_sibling_mountable_path.py](../../../../packages/toolkit/tests/unit/test_sibling_mountable_path.py) covers factory accept/reject + `DooDPathError` surface.
- [packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py](../../../../packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py) asserts the orchestrator raises before any bcftools step runs.
- [packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py](../../../../packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py) walks the DooD-bound wrappers and asserts annotations.
- mypy enforcement: a fixture file that hands a bare `Path` where `SiblingMountablePath` is expected fails mypy in CI.

### INV-T001: External-Tool Conventions Captured as Typed Wrappers

**Rule**: When GenomeClaw integrates an external bioinformatics tool (pgsc_calc, plink2, bcftools, VEP, etc.), the tool's path / argv / samplesheet / file-format conventions are captured in a typed `<Tool>Conventions` frozen dataclass at the wrapper layer. Each field's value is cited to upstream documentation OR to an empirical probe against the tool's actual binary; wrapper tests assert against the captured conventions, never against hand-rolled hardcoded strings.

**Requirements**:
- One `<Tool>Conventions` dataclass per integrated tool, located alongside the wrapper (`packages/toolkit/src/genomeclaw_toolkit/prep/_<tool>_conventions.py`).
- The dataclass is `frozen=True` and carries `verified_against_version: str` matching the pin in `_versions.py`.
- Each field has a docstring with a citation: either a URL to upstream docs OR a path to a captured `tools/<tool>/probe-output.txt` file showing the empirical behaviour.
- Wrapper tests construct the tool's argv using the conventions dataclass and assert the resulting argv against a golden file (`tools/<tool>/golden-argv.txt`) captured from a successful real invocation.
- New tool integrations: write the conventions dataclass FIRST, then the wrapper.
- Existing wrappers: backfill the conventions dataclass during the next breaking change to the tool (e.g., when bumping the tool's pin in `_versions.py`).

**Where it applies**:
- Every external-tool wrapper in [packages/toolkit/src/genomeclaw_toolkit/prep/](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/) (`_bcftools.py`, `_bcftools_norm.py`, `_bcftools_stats.py`, `_bgzip.py`, `_mosdepth.py`, `_pgsc_calc_match.py`, `_vcfanno.py`, `_vep.py`, plus the orchestrator-facing wrappers).
- The `INV-T` category is created for this rule; future tool-integration invariants land under this prefix.

**How to verify**:
- [packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py](../../../../packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py) — for every wrapper in `prep/`, asserts a `<Tool>Conventions` dataclass exists, is frozen, and has `verified_against_version` populated.
- [packages/toolkit/tests/unit/test_pgsc_calc_conventions.py](../../../../packages/toolkit/tests/unit/test_pgsc_calc_conventions.py) — `pgsc_calc`'s dataclass field values match the recorded `tools/pgsc_calc/probe-output.txt` baseline; wrapper-generated argv matches `tools/pgsc_calc/golden-argv.txt`.
- CI gate: any PR touching `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` triggers `tools/pgsc_calc/probe.sh`; output is diffed against the recorded golden; mismatch fails the build.

---

## Testing Strategy

### Unit Tests
- `tests/unit/test_pgsc_calc_conventions.py`: every dataclass field value tracks `tools/pgsc_calc/probe-output.txt`
- `tests/unit/test_sibling_mountable_path.py`: factory accept/reject sweep with parametrized fixtures

### Integration Tests
- `tests/integration/test_shim_identical_path_mounts.py`: shim docker-invocation assertions in both DooD-on and DooD-off modes
- `tests/integration/test_compute_prs_rejects_non_sibling_path.py`: end-to-end rejection before bcftools runs

### Provenance Tests
- None new. `INV-R001`'s existing tests cover `pgs_scores` provenance; this plan strengthens `INV-R001` indirectly via `verified_against_version` in the conventions dataclass.

### Determinism Tests
- None new.

### Privacy-Default Tests
- None new. The plan adds no new egress.

### Evidence-Binding Tests
- None new.

### Report Rendering Tests
- None new.

### Invariant Tests
- `tests/invariants/test_invD005_identical_path_mounts.py`
- `tests/invariants/test_invD006_dood_safe_path_annotation.py`
- `tests/invariants/test_invT001_tool_conventions_exist.py`

### Real-tool smoke (Phase 5)
- Full `pipeline prs-compute` against `MPNRGLQ2K.cram`. Captured in `work-notes.md`. **Phase-completion gate** per `docs/plans/CLAUDE.md` §"Real-data smoke as a phase-completion gate".

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — three new entries + new INV-T category row + version 1.11 → 1.12
- [ ] [docs/reference/architecture.md](../../../reference/architecture.md) — new path-crossing-layers subsection + invariant-traceability rows
- [ ] [docs/plans/CLAUDE.md](../../CLAUDE.md) — new TDD category (Tool-Contract) + real-tool-smoke rule
- [ ] [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md) — leading editor's note pointing at the `INV-D004 → INV-D005` / `INV-D005 → INV-D006` renumber
- [ ] Root [CLAUDE.md](../../../../CLAUDE.md) — no change; the five top-level rules don't shift

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1: identical-path mounts | Complete | 2026-05-19 | 2026-05-19 | Shim auto-detects DooD subcommands + adds identical-path overlay; 8 integration tests + 1 invariant test green. Suite at 700 passed. |
| Phase 2: PgscCalcConventions | Complete | 2026-05-19 | 2026-05-19 | Dataclass + 10 unit tests + 2 invariant tests + probe baseline; 6 existing wrapper tests still green. Suite at 659 passed. |
| Phase 3: SiblingMountablePath | Complete | 2026-05-19 | 2026-05-19 | _paths.py + factory + 17 tests; pgs.py + coverage_fill.py + scratch.py migrated; shim threads HOST_ROOTS. Suite at 677 passed. |
| Phase 4: doc rollup | Complete | 2026-05-19 | 2026-05-19 | INVARIANTS.md v1.12 (3 new entries + INV-T category); architecture.md path-crossing-layers subsection + 3 traceability rows; plans/CLAUDE.md Tool-Contract category + INV-T001 callout; report editor's note. Suite still 677 passed. |
| Phase 5: real-tool smoke (v1) | Surface-revealing | 2026-05-19 | 2026-05-19 | Seven smoke iterations against `MPNRGLQ2K.cram` surfaced 4 discipline gaps not in original scope. Each iteration captured + diagnosed in [work-notes.md](work-notes.md). Was meant as a validation gate; functioned as a debug gate. |
| Phase 6: close 4 gaps (driver migration / Py 3.11/3.13 / shim socket+user+scan / canonical-mount rejection) | Complete | 2026-05-19 | 2026-05-19 | Factory tightened (REJECTS `/mnt/genomeclaw/...`); shim publishes per-subdir env vars; smoke driver migrated (zero `docker run`); `needs_prod_python` marker + image-gated tests; INV-D006 tightened + INV-D007 NEW (Shim Seam Singularity). Suite at 694 passed + 2 prod-python passed against image. |
| Phase 7: real-tool smoke (v2) — final validation + close-out | Complete | 2026-05-19 | 2026-05-19 | Smoke against `MPNRGLQ2K.cram` via the migrated driver validated all 7 discipline layers end-to-end (host-form workDir, no DooDPathError, no `_flavour`, no permission-denied, no EXTRACT_DATABASE-127, no silent rc=1, prod-Python gate passed). Pre-Phase-6 reproducers v1–v6 all absent. Smoke stopped at colima VM memory ceiling (req 16 GB / avail 11.7 GB) — clean nextflow-internal error, NOT a discipline failure. Follow-up: bump `~/.colima/default/colima.yaml: memory:` and re-run for the actual pgs_scores row.

---

## Divergences from Initial Design

The plan was drafted in March-May 2026 with a **three-layer model** (shim overlay / wrapper boundary / tool conventions) and three new invariants (`INV-D005`, `INV-D006`, `INV-T001`). The Phase 5 real-data smoke surfaced that the discipline was **four layers**, not three, and that the original Phase 1 / Phase 3 scopes were each too narrow. Phase 6 closed the gaps; Phase 7 validated the closure end-to-end. This section reconciles the originally-shipped design with what actually landed.

### What changed vs. the original spec

1. **Fourth layer: host-form-only DooD-bound paths (Phase 6 → INV-D006 v1.13).** The original `as_sibling_mountable` accepted both `/mnt/genomeclaw/…` (canonical container view) and `/Volumes/…` (host view). The host daemon spawning DooD siblings can only resolve the host view; passing the canonical view silently produced `EXTRACT_DATABASE` exit-127 inside the sibling. The factory now REJECTS canonical-mount paths with a translated hint pointing at the host-form equivalent. The shim publishes four per-subdir env vars (`GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, `GENOMECLAW_SCRATCH_DIR`) so the translation works inside the toolkit container.

2. **Shim seam singularity (Phase 6 → new INV-D007).** The original plan listed wrappers as migration targets but not scripts/drivers. The `bin/genomeclaw-prs-smoke` driver had a pre-Phase-1 bespoke `docker run` block that silently duplicated shim logic; it drifted from the shim after Phases 1 + 3 and started producing the path-crossing failures Phase 5 surfaced. `INV-D007` promotes "the shim is the canonical seam" with a discovery test forbidding `docker run` in `bin/` (allow-list empty by design).

3. **Phase 1 was scoped to "identical-path mounts" but DooD needs more.** Phase 1 added the overlay correctly; it did NOT mount `/var/run/docker.sock`, did NOT adjust `--user` for socket access (default `${uid}:${gid}` has no socket group membership), and only scanned `$1 $2` for the auto-DooD case (missed `--json pipeline …` invocations). All three are now in the shim with regression tests. The "Phase 1" deliverable label is preserved; the actual delivered scope is described in [phases/phase-1.md](phases/phase-1.md) + the Phase 6 work-notes entry.

4. **Production-Python gate (Phase 6 → new `needs_prod_python` marker).** Phase 3 declared completion based on host-venv (Python 3.13) tests; the toolkit image runs Python 3.11; the `class SiblingMountablePath(Path)` form fails on 3.11 with `_flavour AttributeError`. Fixed by subclassing `type(Path())` (works on both versions) + adding the `needs_prod_python` marker so future phases gate on the prod-Python at completion time.

### Final invariant set

| ID | Status | Promoted in |
|----|--------|-------------|
| INV-D005 | Stable | Phase 1 |
| INV-D006 | Tightened (v1.13) | Phase 3 → Phase 6 |
| INV-D007 | NEW | Phase 6 |
| INV-T001 | Stable | Phase 2 |

[INVARIANTS.md v1.13](../../../reference/INVARIANTS.md) carries all four.

### Process improvements adopted mid-flight

- **Real-tool smoke as a phase-completion gate** is documented in [docs/plans/CLAUDE.md](../../CLAUDE.md). Phase 6 added the prod-Python variant of the same rule.
- **Driver/script migration is now in-scope by default** for any plan that changes the shim contract. Documented in this Divergences section + carried into INV-D007's "Where it applies."

---

## Open Risks & Follow-ups

- **R1 — docker mount-source duplication semantics**. Two `--mount` entries with the same source path is accepted by docker as long as the readonly flags agree. The shim's overlay mount of `${canonical_root}` may overlap the canonical `${raw_dir}` mount; both must be `readonly`. Phase 1 RED tests cover the conflicting-flag case explicitly.
- **R2 — mypy `Path` subclass quirks**. Some mypy versions don't propagate subclass narrowing through library calls like `path.parent`. Phase 3 RED tests pin the behaviour we depend on; if mypy fails to enforce, the runtime guard in `as_sibling_mountable` is still load-bearing.
- **R3 — `tools/pgsc_calc/probe.sh` requires the `pgsc_calc` docker image pre-pulled**. CI runs the probe only on `_versions.py` changes; gating the probe behind a CI-only marker (`@pytest.mark.needs_prs_runtime`) keeps local test runs fast.
- **R4 — Backfilling `Plink2Conventions`, `BcftoolsConventions`, `MosdepthConventions`, etc.** is explicitly out of scope here. The `INV-T001` rule covers backfill expectations (do it on next breaking change to the tool's pin). Each backfill is its own short plan.
- **R5 — `INV-D006` adoption is invasive**. Migrating all DooD-touching wrappers in one phase is the cleanest; partial adoption leaks the type guarantee. Phase 3 must complete the migration before declaring done; a half-migrated state is worse than not adopting.
- **F1 — Backfill plan for `Plink2Conventions` + `BcftoolsConventions` + `MosdepthConventions` + `BgzipConventions` + `VcfannoConventions` + `VepConventions`**. File on the next breaking-change to any of those tools (INV-T001 warn-list).
- **F2 — Consider whether to remove the canonical `/mnt/genomeclaw/...` mounts entirely** once `GENOMECLAW_DOOD=1` is the default. Probably not — they preserve `INV-D001` enforcement at the OS layer, which is independent of DooD. Document the rationale and close.
- **F3 — Colima VM memory budget vs. pgsc_calc default resource ask.** pgsc_calc's `ANCESTRY_PROJECT:EXTRACT_DATABASE` task statically requests 16 GB; default colima allocation is 12 GiB. The Phase 7 smoke surfaced this as a clean `ProcessUnrecoverableException`. Add a `pgsc_calc_resource_budget` check to `genomeclaw host doctor` so the user is warned at setup time + offered the right `colima start --memory` value. Until that lands, document the requirement in [docs/reference/architecture.md](../../../reference/architecture.md) §"Storage planning" alongside the existing storage sizing notes.
- **F4 — `bin/genomeclaw refs materialize --target prs_pca_sites` CLI subcommand.** Today the smoke driver preflight-errors if PCA sites are missing (INV-D007 forbade the prior bespoke `docker run` materialization). Wiring a proper CLI subcommand lets the smoke driver self-materialize via the shim.
- **F5 — Retroactive `needs_prod_python` backfill for Phases 1, 2, 3.** Those phases declared completion without prod-Python image-side gating; the dev/prod skew was caught only because Phase 6 surfaced it from the smoke. Add one image-side probe per phase's new code.
- **F6 — CI gate on `tools/pgsc_calc/probe.sh` re-run** when `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes. Deferred Phase 2 follow-up.

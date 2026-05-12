# rich-cli — Work Notes

**Feature**: migrate CLI toolchain to Typer + rich; ship `--json` mode for AI agents and inline progress UX for humans
**Started**: <YYYY-MM-DD — fill at Phase 1 kickoff>
**Branch**: `feature/rich-cli` (target — not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom. Each session opens with a context-review block before getting into the work.

### 2026-05-12 — Plan authored

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) v1.6 — confirmed applicable invariants: `INV-D001`, `INV-D002`, `INV-D003`, `INV-P001`, `INV-P002`, `INV-R001`. The plan touches the CLI presentation layer only; orchestrator-level invariants are preserved by leaving orchestrator function signatures unchanged.
- Re-read [docs/reference/architecture.md](../../reference/architecture.md) — confirmed the host-side / sandbox split. CLI runs host-side; nothing about this plan crosses that boundary.
- Re-read [docs/plans/CLAUDE.md](../../CLAUDE.md) — confirmed the planning protocol: full-directory layout for multi-subsystem features; TDD inside every phase; invariants enforced by tests; plan-before-mutate.
- Surveyed existing CLI: [packages/toolkit/src/genomeclaw_toolkit/cli.py](../../../../packages/toolkit/src/genomeclaw_toolkit/cli.py) (~800 lines, argparse-based, 8 subcommands).
- Reviewed [docs/plans/active/mvp/phases/phase-4c4-annotation-correctness.md § W6a](../mvp/phases/phase-4c4-annotation-correctness.md) — narrow rich adoption scoped there. This plan supersedes that scope if approved.
- Surveyed Typer + rich docs to confirm fit: Typer's nested-app abstraction handles subgroups cleanly; rich's `Console(record=True, force_terminal=...)` supports testable rendering.

**Applicable Invariants for the plan as a whole**:
- **INV-P001** Privacy default — zero new egress points (asserted by every phase's privacy-default test).
- **INV-P002** Agent egress minimal-sufficient — the `--json` schema is the agent-facing surface; minimal-sufficient discipline applied to every command's documented schema.
- **NEW provisional `INV-C-cli-output-stability`** — versioned JSON output schema; rendered/structured separation across stdout/stderr.

**Key Insights**:
- The biggest design decision is **framework choice** (Typer vs Click vs argparse + rich). Typer wins on type-hint integration + nested-app abstraction; the cost is one new dep (already accepting `rich` for human UX). Recorded as Decided.
- **Subcommand groups via aliases (not migration)** lets every existing command keep working through the entire migration. The cost is two minor releases of overlap before removal. Worth it; breaking changes for end-users / agents / tests is the larger pain.
- The provisional `INV-C-cli-output-stability` would protect agents from CLI output drift. Promotion gated on Phase 6 close so we don't over-commit before the schemas are stable.
- The user explicitly named "AI agents and humans both" as the audience. This shapes Q4 (single global schema version) + Q5 (NDJSON for streaming) + AC10 (event streams) more than any other decision.

**Completed Today**:
- [x] [spec.md](spec.md) authored — 10 acceptance criteria, 8 open questions, full privacy + safety analysis, scope boundaries.
- [x] [development-plan.md](development-plan.md) authored — 6 phases, ~105 tests, ~13 days; key design decisions resolved; coordination note with Phase 4C.4 W6a; testing strategy across every category.
- [x] [phases/phase-1.md](phases/phase-1.md) authored — 19 tests across cross-cutting + doctor-specific; deliverables listed; verification commands provided.
- [x] This work-notes skeleton seeded.

**Decisions Made** (recorded in development-plan.md § Key Design Decisions):
1. Framework: **Typer + rich** (Q1).
2. Tool name: **`genomeclaw` canonical + `genomeclaw-prep` deprecation alias** (Q2).
3. Subcommand groups: **add as aliases; flat names deprecated later** (Q3).
4. Schema versioning: **single global `cli_output_schema_version`** (Q4).
5. Streaming output: **NDJSON** (Q5).
6. Test rich output: **`Console(record=True)` capture; structural assertions** (Q6).
7. `--debug` mode: **present; structured traceback in JSON; pretty traceback in rich** (Q7).
8. 4C.4 W6a coordination: **recommend subsume; user decision pending** (Q8).

**Blockers / Issues**:
- **User decision pending on Q8 (4C.4 W6a coordination)**. The plan recommends dropping W6a from 4C.4 and having Phase 1 of this plan absorb its scope. Awaiting confirmation before any code lands.

**Next Steps**:
1. User reviews spec.md + development-plan.md + phase-1.md. Approves overall direction or asks for changes.
2. On approval: confirm Q8 (W6a coordination). Update 4C.4's plan if W6a is dropped.
3. Begin Phase 1 implementation: RED tests first, then GREEN.

---

### 2026-05-12 — Open questions Q1–Q8 resolved by project owner

**Context Review**: User walked through all 8 open questions in the spec and made decisions. Recording resolutions here so the rationale isn't lost in chat history.

**Decisions taken**:

| Q | Decision | Notes |
|---|---|---|
| Q1 | **Typer** | Matches my recommendation. Type-hint integration + Click underneath. |
| Q2 | **`genomeclaw` only; drop `genomeclaw-prep` entirely** | Harder cut than I proposed. Phase 1 ships `genomeclaw-prep` as a deprecation-warning shim; Phase 6 deletes it outright. No long deprecation cycle. |
| Q3 | **Hierarchical canonical; flat names deprecate-immediate** | Flat names like `genomeclaw ingest` emit deprecation warnings from Phase 1; removed at Phase 6. Vocabulary (`refs`, `runs`, `pipeline`, `host`) accepted as-is — no rename. |
| Q4 | **Global single `cli_output_schema_version`** | Matches my recommendation. |
| Q5 | **NDJSON** | Matches my recommendation. |
| Q6 | **`Console(record=True)` + structural assertions** | Matches my recommendation. |
| Q7 | **`--debug` mode present** | Matches my recommendation. |
| Q8 | **rich-cli ships completely first; MVP plan paused** | Phase 4C.4 goes on hold. Fetcher correctness fixes from 4C.4 W1 + W1.5 (Content-Length, bgzip-EOF, resume-on-stall) **shipped in rich-cli Phase 3** (2026-05-12). The remaining 4C.4 work (W2 doctor sweep, W3 re-fetch, W4 dbSNP, W5 pre-flight, W6 vcfanno stderr, W7 parity check) waits for MVP resume after rich-cli Phase 8 closes — W3 can resume after Phase 4 ships, since the re-fetch operation becomes observable enough to run with confidence at that point. |

**What this changes in the plan**:

1. **spec.md AC3**: flat names → deprecation-warning → removed at Phase 6 (not "kept indefinitely as aliases").
2. **development-plan.md Phase 6**: now a clean removal of `genomeclaw-prep` + flat aliases + old `cli.py`. Includes a full repo grep-replace to migrate every reference (tests, docs, `.claude/agents/`, MVP plans, `CLAUDE.md`).
3. **development-plan.md Phase 3**: now absorbs fetcher correctness fixes from 4C.4 W1 + W1.5 (~10 extra tests; expected days bump from 3 → 4).
4. **phase-1.md scope**: `_cli/legacy_aliases.py` ships in Phase 1 as a deprecation-warning shim. `genomeclaw-prep` becomes a shim entry point. Bootstrapping wart documented (Phase 1's `legacy_aliases.py` only handles `doctor` for flat-form; other flat-form invocations still route through the old argparse `cli.py` until each phase migrates them).
5. **phase-1.md tests**: 3 new tests added (deprecation-warning emission for `genomeclaw doctor`, `genomeclaw-prep doctor`, and the JSON-mode-+-deprecation-warning interaction).
6. **MVP plan** ([phase-4c4-annotation-correctness.md](../mvp/phases/phase-4c4-annotation-correctness.md)): status changes from Active → On Hold. Note added that W1 + W1.5 shipped in rich-cli Phase 3 (2026-05-12); remaining work resumes after rich-cli Phase 8 closes (with W3 resumable after Phase 4).

**Implications I want to flag**:

- **MVP delivery timeline shifts** by ~13 days (the rich-cli active-work estimate). User has accepted this trade.
- **Truncated reference files** (chr6 / chr7 / chr9 / chr10 / chr11) stay truncated through the rich-cli migration. They get re-fetched in rich-cli Phase 3 (as part of the W1 + W1.5 absorption) — but the W3 re-fetch step itself doesn't run until then. The user's W7 parity check is on hold for ~13 days.
- **Phase 1's legacy-alias bootstrapping wart** is the price of the deprecate-immediate model. We can't migrate every command in Phase 1; un-migrated flat-form commands route through the old argparse `cli.py` until they're migrated. That's a documented edge case, not a defect — but worth flagging.
- **`INV-Cxxx` promotion** moves from "after Phase 6 close + privacy-safety-reviewer pass" (unchanged). The promotion is the final atomic step of the migration.

**Status updates**:
- spec.md → Approved
- development-plan.md → Approved
- phase-1.md → updated; ready to start Phase 1 implementation
- MVP plan-4c4 → On Hold (to be marked in its own work-notes block)

**Next Steps**:
1. Mark [phase-4c4-annotation-correctness.md](../mvp/phases/phase-4c4-annotation-correctness.md) as On Hold; note absorption of W1 + W1.5 into rich-cli Phase 3.
2. Mark [mvp/work-notes.md](../mvp/work-notes.md) with a paused-state session block.
3. On user signal, begin rich-cli Phase 1 implementation: RED tests first, then GREEN.

---

## Phase Progress

### Phase 1: Foundation
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Test Results

```text
=== pytest ===
285 passed, 61 skipped in 2.37s

=== ruff check (strict rule set: E,F,I,UP,B,N,D,RET,SIM,ARG,PTH,TC,PERF,RUF,C4,PIE,PT,S,ANN) ===
All checks passed!

=== ruff format --check ===
121 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 16 source files

=== smoke test ===
- genomeclaw --version → emits schema-v1.0 envelope
- genomeclaw host doctor → rich-rendered Panel + Tables against real layout
- genomeclaw --json host doctor → parseable JSON envelope, 4 checks, 3 derived runs
- genomeclaw --help cold-start → 0.18s user / 0.23s total (well under the 1.0s gate)
```

#### Results

**Files created** (new `_cli/` package + tests + docs):
- `src/genomeclaw_toolkit/_cli/__init__.py` — top-level Typer app, global flag callback, central exception boundary, `main()` entry point
- `src/genomeclaw_toolkit/_cli/context.py` — `AppContext` dataclass
- `src/genomeclaw_toolkit/_cli/console.py` — singleton rich Console + colour-policy configuration
- `src/genomeclaw_toolkit/_cli/output.py` — `OutputMode`/`Verbosity` StrEnums + `emit()` dispatcher
- `src/genomeclaw_toolkit/_cli/errors.py` — `CliError` envelope + 4 subclasses + exit-code contract constants
- `src/genomeclaw_toolkit/_cli/tool.py` — `ToolRunner` Protocol + `SubprocessToolRunner` default + factory
- `src/genomeclaw_toolkit/_cli/version.py` — `--version` payload assembly (toolkit + image digest + git)
- `src/genomeclaw_toolkit/_cli/types/__init__.py` + `types/envelope.py` — `CliEnvelope`, `ErrorDetail`, `CLI_OUTPUT_SCHEMA_VERSION`
- `src/genomeclaw_toolkit/_cli/commands/__init__.py` + `commands/host.py` + `commands/refs.py` + `commands/pipeline.py` + `commands/_resolve.py`
- `src/genomeclaw_toolkit/_cli/renderers/__init__.py` + `renderers/host.py` (doctor rich rendering)
- `bin/genomeclaw` — new host shim (replaces `bin/genomeclaw-prep`)
- `docs/reference/cli-output-schemas.md` — versioned JSON schema doc
- `tests/integration/test_cli_framework.py` — 9 cross-cutting tests
- `tests/integration/test_cli_host_doctor.py` — 5 doctor-specific tests
- `tests/privacy/test_invP001_cli_no_egress.py` — 4 privacy-default tests
- `tests/conftest.py` — added `cli_runner` and `invoke_cli` fixtures with `CliResult` dataclass

**Files deleted** (clean-slate cutover, no back-compat):
- `src/genomeclaw_toolkit/cli.py` — legacy argparse-based dispatcher
- `bin/genomeclaw-prep` — legacy shim
- `prep/doctor.py:render_text` + its helpers (moved into `_cli/renderers/host.py`)

**Files migrated** (tests + tooling):
- `pyproject.toml` — added `typer >= 0.15`, `rich >= 13`, `click < 8.3` (typer 0.15 needs older click), `mypy >= 1.10`; dropped `genomeclaw-prep` entry point; added `genomeclaw` entry point; tightened ruff rule set to the strict set; added `[tool.mypy]` strict config scoped to `_cli/`
- `tests/integration/test_cli_pipeline.py` — flat `["pipeline", ...]` → hierarchical `["pipeline", "run", ...]`; monkey-patch target → `_cli.commands.pipeline.*_impl`
- `tests/integration/test_cli_ingest_autodetect.py` — flat `["ingest", ...]` → `["pipeline", "ingest", ...]`; exit-code expectations updated (precondition errors now exit 3, usage errors stay 2)
- `tests/integration/test_cli_run_dir_autodetect.py` — flat `["normalize"/"annotate"/"materialize", ...]` → `["pipeline", "normalize/annotate/materialize", ...]`; missing CURRENT now exits 3 (precondition) not 2
- `tests/integration/test_cli_fetch_all.py` — flat `["fetch", ...]` → `["refs", "fetch", ...]`; monkey-patch → `_cli.commands.refs.fetch_impl`; usage errors still exit 2; rich-escape the literal `[skip]` markup
- `tests/integration/test_cli_setup_force_reset.py` + `test_cli_setup_fetch_all.py` — flat `["setup", ...]` → `["host", "setup", ...]`; non-zero from `run_interactive` now maps to `RuntimeFailure` (exit 1) for "did not complete cleanly" + `UsageError` (exit 2) for validation failures
- `tests/integration/test_setup_dryrun.py` — same migrations; the 4 INV-level tests preserved verbatim
- `tests/integration/test_doctor.py` — two `render_text`-based tests removed (the rich renderer is covered by `test_cli_host_doctor.py`); `_render_text` is no longer in `prep/`
- `tests/test_smoke.py` — uses canonical `genomeclaw` entry point + new subpackage names

**Files updated** (legacy code touched for cleanup):
- `prep/doctor.py` — removed `render_text` + its 5 helper functions and the `_STATUS_MARKERS` constant
- `src/genomeclaw_toolkit/__init__.py` — package docstring references `genomeclaw` (not `genomeclaw-prep`)

#### Notes

**Architecture decisions ratified during implementation**:

1. **Typer entry point uses `standalone_mode=False`** in `main()` so we can wrap all of Click's control-flow exceptions (`Exit`, `Abort`, `UsageError`, `BadParameter`) at the exception boundary. Without this, `--help`'s `click.exceptions.Exit(0)` bubbles up as an unhandled exception.
2. **`invoke_cli` test fixture routes through real `main()`** (not via `CliRunner.invoke`) so the exception boundary + rich/JSON dispatch + `SystemExit` contract are all exercised exactly as in production. Uses `contextlib.redirect_stdout/stderr` + `reset_console()` per call to force fresh consoles into the captured streams.
3. **`Path` stays as a runtime import** in `_cli/commands/host.py` (with `# noqa: TC003`) because Typer reads option defaults at decoration time, so `Path("/mnt/...")` defaults need the symbol present at module load.
4. **`bin/genomeclaw` keeps the same bind-mount + scratch-safety discipline** as the deleted `bin/genomeclaw-prep` — only the binary name and the "host-side subcommand groups" allowlist (now `host`, not `setup|eject|doctor`) change.
5. **Click pinned to `< 8.3`** because Typer 0.15 doesn't yet support Click's new `Parameter.make_metavar(ctx)` signature. Flagged as a follow-up to revisit when Typer 0.16+ ships.

**Quality bar mechanics**:

- `ruff` strict rule set enabled in `pyproject.toml` per the [Quality Bar section](../development-plan.md#quality-bar-enforced-from-phase-1) of the dev plan.
- `mypy --strict` scoped to `src/genomeclaw_toolkit/_cli` via `[tool.mypy] files = [...]`; legacy `prep/` modules not yet under strict typing.
- Per-file-ignores keep legacy `prep/` + tests off the new strict bars. As each future phase touches a `prep/` module, that module gets removed from the ignore list.
- Every public class / function / method in `_cli/` has a Google-style docstring. No `Any` in public signatures.

**Carrying forward to Phase 2**:

- The `refs` subgroup currently exposes only `refs fetch` (thin wrapper); `refs list`, `refs verify`, `refs info` are Phase 2 deliverables. The Typer subapp is registered already so each lands as a single-file addition.
- The `runs` subgroup is entirely empty in Phase 1 — no module exists yet; first work item of Phase 2 is to land `commands/runs.py`.
- The `progress_callback` hook described in the architecture is *defined* in Phase 1 (`ToolRunner` protocol) but not yet *consumed* anywhere — that's Phase 3's job when the `fetch` command moves from thin wrapper to full rich-rendered progress.

---

---

### Phase 2: Read-only commands
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Test Results

```text
=== pytest ===
325 passed, 61 skipped in 2.98s     (+40 new tests vs Phase 1)

=== ruff check (strict rule set: E,F,I,UP,B,N,D,RET,SIM,ARG,PTH,TC,PERF,RUF,C4,PIE,PT,S,ANN) ===
All checks passed!

=== ruff format --check ===
136 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 20 source files
```

#### Results

**Files created** (`prep/` orchestrators + `_cli/` plumbing + renderers + tests):
- `src/genomeclaw_toolkit/prep/_bgzip.py` — public `verify_bgzip_eof_marker(path)` + canonical 28-byte EOF-marker constant
- `src/genomeclaw_toolkit/prep/references.py` — `describe_release_set` / `describe_source` / `verify_release_set_integrity` + Pydantic status models
- `src/genomeclaw_toolkit/prep/runs.py` — `list_derived_runs` / `read_run_detail` + `DerivedRunSummary` / `RunDetail` / `ProvenanceStep` Pydantic models
- `src/genomeclaw_toolkit/_cli/commands/runs.py` — `runs list` / `runs show` / `runs current` with `--watch` on `list`
- `src/genomeclaw_toolkit/_cli/renderers/refs.py` — `render_refs_list` / `render_refs_verify` / `render_refs_info` + `_human_bytes` formatter
- `src/genomeclaw_toolkit/_cli/renderers/runs.py` — `render_runs_list` / `render_run_detail` + `_STAGE_STYLE` map
- `src/genomeclaw_toolkit/_cli/watch.py` — `watch_loop(render, *, refresh_interval_sec=2.0, max_iterations=None)` rich `Live` wrapper
- `tests/integration/test_bgzip_verify.py` — 5 unit tests for the EOF helper
- `tests/integration/test_cli_refs_list.py` — 4 tests (rich table + JSON, status classification)
- `tests/integration/test_cli_refs_verify.py` — 5 tests (clean + truncated fixtures, INV-D001 read-only check, exit-4 contract)
- `tests/integration/test_cli_refs_info.py` — 4 tests (rich panel, JSON detail, bgzip_ok flag, unknown-source UsageError)
- `tests/integration/test_cli_runs_list.py` — 6 tests (empty/populated, newest-first ordering, stage classification, CURRENT symlink filter, rich + JSON, schema-version assertion)
- `tests/integration/test_cli_runs_show.py` — 5 tests
- `tests/integration/test_cli_runs_current.py` — 3 tests (symlink resolution, missing-CURRENT precondition, rich panel)
- `tests/integration/test_cli_watch_mode.py` — 4 tests (`runs list --watch`, `host doctor --watch`, JSON-mode suppression, max-iterations termination)

**Files modified**:
- `src/genomeclaw_toolkit/_cli/commands/refs.py` — added `refs list` / `refs verify` / `refs info`; `refs verify` raises `DataIntegrityError` (exit 4); `refs info` raises `UsageError` (exit 2) for unknown source
- `src/genomeclaw_toolkit/_cli/commands/host.py` — added `--watch` flag to `host doctor`; mapped setup `rc=2` to `UsageError`
- `src/genomeclaw_toolkit/_cli/__init__.py` — registered the `runs` subapp via side-effect import
- `src/genomeclaw_toolkit/_cli/output.py` — made `emit()` generic with `TypeVar("_PayloadT", bound=BaseModel)` so renderer typing flows through cleanly
- `pyproject.toml` — per-file-ignores carve-outs for new strict modules under `prep/` (`_bgzip.py`, `runs.py`, `references.py`)
- `tests/privacy/test_invP001_cli_no_egress.py` — extended with 4 no-egress cases for the new commands
- `docs/reference/cli-output-schemas.md` — added 6 schemas: `refs.list`, `refs.verify`, `refs.info`, `runs.list`, `runs.show`, `runs.current`

#### Notes

**Bug found during real-layout smoke test**: the canonical BGZF EOF marker constant initially had an extra trailing `0x00` byte (29 bytes instead of 28). `refs verify` flagged *all 26* reference files as truncated against the real `/Volumes/Genome_Work/genomeclaw/reference/` layout — clearly wrong. Fixed by reading the actual tail of a known-clean `clinvar.vcf.gz` and correcting the hex to `1f8b08040000000000ff0600424302001b0003000000000000000000`. After the fix, `refs verify` correctly identifies exactly the 5 known-truncated gnomAD chrom files (chr6, chr7, chr9, chr10, chr11) — confirming the diagnostic surface that motivated Phase 3's fetcher-correctness work.

**CURRENT symlink filtering**: `pathlib.Path.iterdir()` returns the `CURRENT` symlink with `is_dir()=True`, which double-counted the live run. Fixed in `list_derived_runs` by adding `or entry.is_symlink()` to the skip-condition.

**Generic `emit()` discovery**: mypy --strict rejected passing `Callable[[SpecificPayload], None]` to a parameter typed `Callable[[BaseModel], None]` (contravariance). Made `emit` generic via `TypeVar("_PayloadT", bound=BaseModel)` — clean fix, lets per-command renderers stay typed against their concrete payload models.

**Architecture seam holding firm**: `prep/` modules (`_bgzip.py`, `references.py`, `runs.py`) never import from `_cli/`; `_cli/commands/*.py` lazy-imports orchestrators inline. The seam is doing its job — cold-start `--help` time unchanged from Phase 1's 0.18s baseline.

**Test-fixture lesson**: a `refs list` test initially expected `status == "OK"` but only staged the `.vcf.gz` file. ClinVar's complete fetch produces `.vcf.gz + .vcf.gz.md5 + .vcf.gz.tbi`; dbSNP additionally produces `.vcf.gz.tbi.md5`. Fixtures must mirror the orchestrator's expectation exactly — there's no fuzzy "partial-OK" tier. Captured in the test fixtures going forward.

**Carrying forward to Phase 3**:
- `verify_bgzip_eof_marker` ships as a public helper, ready to be invoked from inside the fetcher (Phase 3 task: call it post-download + raise `IncompleteBgzip` on failure, remove partial file).
- `_BGZIP_SUFFIXES` lives in `prep/references.py`; Phase 3 should consider whether it belongs in `prep/_bgzip.py` alongside the marker constant + verify helper.
- `--watch` infrastructure is generic — Phase 3's `pipeline run` progress display can layer on the same `watch_loop` if a polling renderer fits better than a `rich.progress.Progress` panel.

---



### Phase 4: `refs fetch` rich UX
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Test Results

```text
=== pytest ===
346 passed, 61 skipped in 3.67s     (+5 new tests over Phase 3)

=== ruff check (strict rule set) ===
All checks passed!

=== ruff format --check ===
140 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 20 source files

=== Real-layout smoke ===
genomeclaw --json refs fetch --source clinvar --release 2026-05-09 \
    --reference-root /Volumes/Genome_Work/genomeclaw/reference
# Line 1: {"cli_output_schema_version":"1.0","command":"refs.fetch","stream":true}
# Line 2: {"cli_output_schema_version":"1.0","command":"error","error":{...}}  (precondition: already present)
# Exit: 3 (precondition_error)
```

#### Results

**Files created**:
- `tests/integration/test_cli_refs_fetch.py` — 5 tests covering: NDJSON event stream + first-line envelope + `file_start` / `file_complete` events; `file_failed` event + exit-4 on integrity error; rich-mode per-file rendering; `--all` rendering of multiple sources; INV-P001 mock-URL-only egress.

**Files modified**:
- `src/genomeclaw_toolkit/_cli/renderers/refs.py` — added `make_fetch_progress()` factory + `make_fetch_rich_renderer(progress)` (translates `ProgressEvent`s to `rich.progress.Progress` task updates) + `make_fetch_ndjson_emitter(sink)` (compact one-event-per-line JSON writer).
- `src/genomeclaw_toolkit/_cli/commands/refs.py`:
  - `refs fetch` command body fleshed out — new `_execute_single_fetch()` helper picks the right callback (rich `Progress` or NDJSON emitter) based on `ctx.output_mode` and threads it through `prep.fetch.fetch(progress_callback=...)`.
  - JSON mode writes the first-line envelope (`{"cli_output_schema_version": "1.0", "command": "refs.fetch", "stream": true}`) before delegating to the fetcher.
  - Updated `_do_fetch_one` to catch `IncompleteBgzip` / `TruncatedDownload` / `DownloadStalled` alongside `ChecksumMismatch` → `DataIntegrityError` (exit 4); the per-file `FileFailed` event has already been emitted by the fetcher before re-raising.
- `src/genomeclaw_toolkit/prep/fetch.py`:
  - `_fetch_one_file` wraps its body with `try/except (IncompleteBgzip, TruncatedDownload, DownloadStalled, ChecksumMismatch)` and emits a `FileFailed` event (with the right `reason` discriminator) before propagating.
  - Suppress legacy stdout prints (`fetching N files`, `↓ {label}`, periodic progress lines, `✓ {bytes}`, post-fetch hook noise, "source complete" summary) when a `progress_callback` is provided. Without this gate the prints would pollute the JSON-mode stdout NDJSON stream.
  - `_stream_to_file` gates its `↓` / `✓` / periodic-progress prints on `on_progress is None` rather than always emitting.
  - `_fetch_one_file` only forwards an `on_progress` closure to `_stream_to_file` when a real outer `progress_callback` was provided — without this, the inner closure existed unconditionally and `_stream_to_file` would suppress its legacy prints even when no caller wired up rich/NDJSON.
- `docs/reference/cli-output-schemas.md` — pinned the first-line envelope shape + worked happy-path and failure-path `refs.fetch` examples.

#### Notes

**Stdout-pollution lesson**: the first GREEN attempt left `_stream_to_file`'s legacy stdout prints in place. The NDJSON tests caught the resulting pollution (`JSONDecodeError: Expecting value: line 1 column 3 (char 2)` — the `↓ ` arrow character broke parsing). Fix: route the "is anyone consuming events?" decision through to every print site. The gating is now: `quiet_stdout = progress_callback is not None` in `fetch()` and `_fetch_one_file`; `_stream_to_file` gates separately on `on_progress is not None`. The two gates are necessary because `_stream_to_file` doesn't see the outer `progress_callback` directly.

**Subtle bug from over-eager closure**: the second iteration broke `test_fetch_prints_per_file_announce_and_completion` (a legacy test asserting the `↓ clinvar.vcf.gz` line appears when calling `fetch()` without a callback). Root cause: `_fetch_one_file` always built an `_on_progress` closure and passed it to `_stream_to_file`, so `_stream_to_file` always saw a non-None hook and always suppressed its prints — even when no outer callback existed. Fix: only build + pass the closure when `progress_callback is not None`. This keeps the inner/outer state in sync.

**Werkzeug auto-Content-Length carry-over**: Phase 3's `_lying_response` helper (using `direct_passthrough=True`) made it into Phase 4's failure-mode test. Phase 4 itself only needs a server that ships the bytes it has staged — no need for the `direct_passthrough` trick since the body's length matches.

**Carrying forward to Phase 5**:
- `make_fetch_progress()` + `make_fetch_rich_renderer()` shape will be a template for `_cli/renderers/pipeline.py`'s rich panels — a `make_pipeline_progress()` factory + per-phase Panel decorator.
- The NDJSON envelope shape (`stream: true` discriminator + one event per line) is now pinned. Phase 5's `pipeline run` follows the same shape with event types `phase_start` / `phase_complete` / `phase_failed` / `pipeline_complete`.
- The "suppress legacy stdout prints when a callback exists" pattern will likely apply when wiring `progress_callback` into the 4 `prep/` orchestrators (`ingest`, `normalize`, `annotate_vcfanno`, `materialize`).

---



---

### Phase 5: Pipeline UX + per-orchestrator callbacks + strict-typing graduation
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Strict-typing graduation surprise

Initially planned to defer the 4-module strict-typing graduation to Phase 6, expecting non-trivial `D` (pydocstyle) + `ANN` (annotation) backlogs in each legacy orchestrator. Ran `uv run ruff check src/genomeclaw_toolkit/prep/{ingest,normalize,annotate,materialize}.py --select D,ANN,ARG,PERF,SIM,N,PT,PTH,TC,RUF,S,PIE,UP,E501,RET` against the rules the `per-file-ignores` carve-out currently masks: **all checks passed**. The legacy code was written modern-style from the start — Google-style docstrings, type annotations, no security-sensitive patterns. The carve-out was precautionary, not load-bearing. Lifted all 4 carve-outs with zero code changes; **360/0 pytest after the lift**.

This means Phase 5 ships its originally-planned 3 workstreams (a) callbacks + (b) UX migration + (c) strict-typing graduation cleanly. Phase 6 no longer carries the graduation as a precursor task.

#### Test Results

```text
=== pytest ===
360 passed, 61 skipped in 3.33s     (+19 over Phase 4: 9 pipeline-events + 5 privacy + 5 from un-carve-out)

=== ruff check (strict rule set, including 4 newly graduated prep/ modules) ===
All checks passed!

=== ruff format --check ===
141 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 21 source files

=== Real-layout smoke ===
genomeclaw --json pipeline ingest --raw-root /Volumes/Genome_Work/genomeclaw/raw \
    --reference-root /Volumes/Genome_Work/genomeclaw/reference \
    --derived-root /tmp/smoke-derived
# Line 1: {"cli_output_schema_version":"1.0","command":"pipeline.ingest","stream":true}
# Line 2: {"cli_output_schema_version":"1.0","command":"error","error":{...}}  (preflight refused: /mnt/genomeclaw/raw not found on host)
# Exit: 1
```

(Full end-to-end smoke requires the toolkit Docker image; planned alongside the user re-fetching the 5 truncated gnomAD files.)

#### Results

**Files created**:
- `src/genomeclaw_toolkit/_cli/renderers/pipeline.py` — `make_pipeline_rich_renderer()` renders one rich `Panel` per `PhaseStart`/`PhaseComplete`/`PhaseFailed`/`PipelineComplete` event; `make_pipeline_ndjson_emitter(sink)` writes compact one-event-per-line JSON. `_PHASE_STYLE` maps phase to colour (`cyan`/`magenta`/`green`/`yellow`). `_format_duration()` produces short `1.2s` / `1m23s` / `1h02m05s` strings.
- `tests/integration/test_cli_pipeline_events.py` — 9 tests covering: pipeline_run NDJSON envelope + 4×phase events + pipeline_complete; phase_failed on normalize error; rich-mode panel ordering; single-stage NDJSON per command (parametrized 4 ways); no stdout pollution; INV-D001 source path-threading.

**Files modified**:
- `src/genomeclaw_toolkit/prep/ingest.py` — added `progress_callback: Callable[[_ProgressEvent], None] | None = None` parameter; emits `PhaseStart(phase="ingest")` at function entry, `PhaseComplete(phase="ingest", duration_sec=..., run_dir=...)` at success exit.
- `src/genomeclaw_toolkit/prep/normalize.py` — same pattern (`phase="normalize"`).
- `src/genomeclaw_toolkit/prep/annotate.py` — same pattern (`phase="annotate"`).
- `src/genomeclaw_toolkit/prep/materialize.py` — same pattern (`phase="materialize"`).
- `src/genomeclaw_toolkit/_cli/commands/pipeline.py` — full rewrite:
  - `_build_callback(ctx, command)` dispatches on output mode: JSON → writes first-line envelope to stdout + returns NDJSON emitter; rich + not-quiet → returns rich renderer; rich + quiet → returns `None`.
  - `_emit_phase_failed(callback, phase, error_type, message)` pushes a `PhaseFailed` event before re-raising as `CliError`.
  - `_begin_ndjson_stream(command)` writes the canonical envelope shape (`{"cli_output_schema_version":"1.0", "command":..., "stream":true}`).
  - Each command (ingest / normalize / annotate / materialize / run) wires the callback through `progress_callback=...` to its orchestrator.
  - `pipeline run` aggregates events across all 4 stages and emits the terminal `PipelineComplete(run_dir, duration_sec)`.
- `tests/privacy/test_invP001_cli_no_egress.py` — extended with 5 cases (`pipeline ingest` / `normalize` / `annotate` / `materialize` / `run`), each asserting zero outbound HTTP under stubbed orchestrators.
- `docs/reference/cli-output-schemas.md` — added worked `pipeline run` NDJSON example.

#### Notes

**Callback emission seam**: each orchestrator emits at function entry (after preflight checks pass) and at success exit (just before `return`). On exception, no `PhaseComplete` fires — the CLI wrapper emits `PhaseFailed` instead via the same callback. This keeps the orchestrator's emission logic minimal and matches the natural "I started ... I finished" lifecycle.

**`_RunDirPayload` only on rich-mode tail**: in NDJSON mode, the stream is the canonical output — the legacy `_RunDirPayload` "wrote X" envelope would be a duplicate trailing envelope after the per-event lines. Each command now gates the `_emit_run_dir(...)` call on `not ctx.is_json`, so JSON-mode consumers see only the stream.

**JSON-mode stderr behavior on phase failure**: when an orchestrator raises mid-pipeline, the CLI emits the `PhaseFailed` event to stdout (continuing the NDJSON stream) and then propagates the exception, which the top-level boundary turns into a standard `CliError` envelope written to **stderr**. Net behavior: stdout gets a complete event stream (closed with phase_failed), stderr gets the structured error envelope, exit code reflects the error class (1/2/3/4 per the contract).

**Carrying forward to Phase 6**:
- The phase-6 plan (destructive commands — `host setup` / `host eject`) — author the standalone `phases/phase-6.md` at the start of Phase 6 work (the Development Plan's per-phase narrative is sufficient until then).
- Real-VCF end-to-end smoke once the 5 truncated gnomAD files are re-fetched.
- Strict-typing graduation already complete (see surprise above) — Phase 6 starts clean without a hygiene precursor.

---



---

### Phase 6: Destructive commands
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Test Results

```text
=== pytest ===
375 passed, 61 skipped in 3.86s     (+15 over Phase 5: 13 confirmation + 2 privacy)

=== ruff check (strict rule set) ===
All checks passed!

=== ruff format --check ===
145 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 22 source files

=== Real-CLI smoke ===
genomeclaw host setup --force-reset --dry-run < /dev/null
# Error (usage_error): Refusing to reformat the GenomeClaw drive without confirmation.
# Pass --yes (scripted) or run on an interactive terminal.
# Exit: 2
```

#### Results

**Files created**:
- `src/genomeclaw_toolkit/_cli/confirm.py` — `require_destructive_confirmation(ctx, expected_phrase, operation_description, suggested_actions=...)` helper. Three branches: `--yes` short-circuits; non-TTY without `--yes` → `UsageError` exit 2; interactive TTY prompts on stderr + reads stdin + checks exact-string match (case-sensitive, whitespace-stripped).
- `tests/integration/test_cli_host_setup_confirmation.py` — 6 tests covering: non-TTY refusal, wrong-phrase refusal, `--yes` accept, typed-phrase accept, non-destructive path doesn't prompt, JSON plan + result envelopes.
- `tests/integration/test_cli_host_eject_confirmation.py` — 7 tests covering: non-TTY refusal, `--yes` accept, typed-basename accept, wrong-basename refusal, `--force` doesn't imply confirmation, `--yes --force` combo, JSON envelope.

**Files modified**:
- `src/genomeclaw_toolkit/_cli/commands/host.py`:
  - `host_setup`: added `_HostSetupPlanPayload` + `_HostSetupResultPayload` + `_emit_host_setup_envelope()` helper; the `--force-reset` branch now invokes `require_destructive_confirmation()` with the canonical phrase `REFORMAT GENOMECLAW DRIVE`; JSON mode writes a plan envelope before orchestrator call + a result envelope after.
  - `host_eject`: added `_HostEjectPayload`; gates entry with `require_destructive_confirmation()` using the drive's mount-point basename as the expected phrase; emits a single result envelope on success via the existing `emit()` plumbing.
  - `--force` doc string clarified: does NOT skip confirmation; use `--yes` for that.
- `tests/integration/test_cli_setup_force_reset.py` — 3 tests updated to add `--yes` to their invocations (the Phase-1 contract where `--force-reset` alone auto-confirmed is gone).
- `tests/integration/test_setup_dryrun.py` — 1 test updated likewise.
- `tests/privacy/test_invP001_cli_no_egress.py` — extended with `test_invP001_no_egress_during_host_setup_dry_run_yes` + `test_invP001_no_egress_during_host_eject_yes`.
- `docs/reference/cli-output-schemas.md` — replaced the Phase-1 "thin wrapper, no schema yet" stub for `host setup` / `host eject` with full payload-shape docs + worked examples.

#### Notes

**TTY-detection test pattern**: the first GREEN attempt monkey-patched `sys.stdin.isatty` then replaced `sys.stdin` with a `StringIO`. That broke because replacing `sys.stdin` discarded the prior monkey-patch AND `StringIO.isatty()` defaults to `False`. Fixed with a tiny `_FakeTTYStdin(io.StringIO)` subclass that overrides `isatty()` to return `True`. Pattern shared between the setup and eject test files; could be hoisted to `conftest.py` if a third command needs it.

**Contract change**: Phase 1's thin wrapper made `--force-reset` self-confirming. Phase 6 separated the two concerns — the flag picks the destructive code path; `--yes` (or the phrase) is the consent. Four legacy tests broke; all updated to pass `--yes`. This is the deliberate behavior change that the [development-plan.md § Phase 6](../development-plan.md#phase-6-destructive-commands) calls out.

**Why typed-phrases instead of y/n prompts**: muscle-memory. A user who has just typed `y` to several other prompts (`brew install`, `apt upgrade`, etc.) hits `y` again on autopilot. Typing `REFORMAT GENOMECLAW DRIVE` requires deliberate intent — the user has to read what they're about to do. The drive-basename pattern for eject (typing `Genome_Work`) is shorter but still specific enough to break the autopilot.

**`--force` semantics preserved separately from `--yes`**: `--force` was always documented as "bypass the in-flight-pipeline safety check", not "skip confirmation". Phase 6 keeps that semantic — passing `--force` alone on a non-TTY still refuses with exit 2 because the consent gate is independent. The user must pass `--yes --force` together to eject during a pipeline run unattended.

**Carrying forward to Phase 7** (Polish):
- `phases/phase-7.md` skeleton — author at the start of Phase 7. The development-plan narrative covers: tab completion (bash/zsh/fish), "did you mean" misspelling suggestions, `--version` enrichment (toolkit version + image digest + git commit), performance audit (lazy imports for heavy deps), structured `--debug` flag.
- `INV-S-confirmation-required` provisional invariant: monitor whether the pattern holds across Phase 7 polish work (no new `host`-prefixed commands planned that would need it, but worth keeping in mind).

---



---

### Phase 7: Polish + agent ergonomics
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Test Results

```text
=== pytest ===
388 passed, 61 skipped in 4.21s     (+13 over Phase 6: 4 suggest + 2 completion + 3 did-you-mean + 1 perf + 1 privacy + 2 retro-fixes)

=== ruff check (strict rule set) ===
All checks passed!

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 24 source files

=== Real-CLI smoke ===
genomeclaw completion bash | head -5    # bash completion script starts with _genomeclaw_completion()
genomeclaw doctr                         # → exit 2 + "Did you mean: host doctor?"
time genomeclaw --help > /dev/null       # → 0.24s wall-time (well under 1.0s budget)
```

#### Results

**Files created**:
- `src/genomeclaw_toolkit/_cli/suggest.py` — `suggest_closest(user_input, candidates, *, cutoff=0.6, max_results=3)` using `difflib.get_close_matches` (stdlib; zero new deps).
- `src/genomeclaw_toolkit/_cli/commands/completion.py` — `completion <shell>` Typer command. Reaches into `click.shell_completion.{BashComplete, ZshComplete, FishComplete}` to render per-shell scripts. Scripts go to stdout; CLI never auto-modifies user shell configs.
- `tests/integration/test_cli_suggest.py` — 4 unit tests for the helper.
- `tests/integration/test_cli_completion.py` — 2 parametrized tests (3 shells × 1 supported + 1 unknown-shell refusal = 4 effective).
- `tests/integration/test_cli_did_you_mean.py` — 3 end-to-end tests (subcommand typo, distant input, JSON mode envelope).
- `tests/perf/test_cli_cold_start.py` — 1 cold-start budget test; uses the installed `genomeclaw` entrypoint via `Path(sys.executable).parent / "genomeclaw"` to avoid the `python -m genomeclaw_toolkit` "no `__main__`" trap.

**Files modified**:
- `src/genomeclaw_toolkit/_cli/__init__.py` — wires the completion subapp; adds `_registered_subcommand_names()` + `_walk_command_paths()` to enumerate the full command tree (so `doctr` → `host doctor` rather than nothing); adds `_did_you_mean_actions(usage_message)` to extract the bad name from Click's "No such command 'X'." pattern and emit `["Did you mean: a, b?"]` suggestions; threads `effective_argv` through `_emit_error` so JSON-mode tests work.
- `src/genomeclaw_toolkit/_cli/output.py` — added `stdout_already_consumed` module sentinel + `mark_stdout_consumed()` / `reset_stdout_state()` helpers. `emit()` calls `mark_stdout_consumed()` whenever it writes a JSON envelope.
- `src/genomeclaw_toolkit/_cli/commands/pipeline.py` — `_begin_ndjson_stream()` marks stdout consumed.
- `src/genomeclaw_toolkit/_cli/commands/refs.py` — both stdout-writing paths (`_emit_release_sets` + `_execute_single_fetch`'s envelope writer) mark stdout consumed.
- `src/genomeclaw_toolkit/_cli/commands/host.py` — `_emit_host_setup_envelope()` marks stdout consumed.
- `tests/privacy/test_invP001_cli_no_egress.py` — extended with `test_invP001_no_egress_during_completion_bash`.

#### Notes

**Subcommand-tree enumeration for "Did you mean"**: the user typing `genomeclaw doctr` likely meant `host doctor`, not just `doctor`. The post-Phase-1-cutover CLI has *no* top-level `doctor` — it's always `host doctor`. The first GREEN attempt enumerated only top-level command names (`completion`, `host`, `pipeline`, `refs`, `runs`) and `suggest_closest("doctr", that_list)` returned `[]`. Fixed by walking the Click command tree recursively and exposing space-joined paths (`host doctor`, `pipeline run`, `refs verify`, …). Now the closest match to `doctr` is `host doctor` at similarity ≈ 0.67, well above the 0.6 cutoff.

**Two latent JSON-mode error-path bugs caught**:

1. **argv detection**: `_is_json_mode()` and `_is_debug_mode()` were both reading `sys.argv[1:]` directly. Under `invoke_cli(["--json", "doctr"])` (tests) the argv list isn't propagated to `sys.argv`, so the helpers returned `False` and the error envelope went to stderr in rich format — masking the bug because tests historically asserted on stdout being JSON ONLY for the happy path. Phase 7's `test_did_you_mean_json_mode_carries_suggestions_in_envelope` exercised the error path under JSON mode and exposed it. Fixed by computing `effective_argv = list(argv) if argv is not None else sys.argv[1:]` at `main()` entry and threading it through.

2. **Double-emission to stdout**: the documented contract in `cli-output-schemas.md` said "error envelope goes to stderr when an NDJSON stream is active". Implementation was: `_emit_error` always wrote to stdout in JSON mode, regardless of whether a stream envelope was already there. Production behavior: `genomeclaw --json refs fetch ...` on integrity failure emitted **two** envelopes on stdout (the stream envelope + the trailing error envelope) → broke any agent assuming the stream is the only stdout content. Fixed via the `stdout_already_consumed` module sentinel. After a payload or stream envelope has been written, subsequent error envelopes go to stderr. Caught by the broader test suite (3 tests failed after the argv fix; the failures pointed at this latent issue).

**Why `difflib.get_close_matches` over a custom Damerau-Levenshtein**: stdlib; zero new deps; performs identically for typical CLI-command typos. The cutoff (0.6 similarity) catches single-character edits on short command names without firing on distant inputs. Falsely-positive matches were not observed during smoke testing.

**Completion script generation**: Typer's `--install-completion` and `--show-completion` are global flags that auto-register on every Typer app. They work but conflict with the "CLI never silently modifies user shell config" discipline (spec Q1 resolution). Phase 7 ships a first-class `completion <shell>` command that writes the script to stdout; the user pipes it into their shell config deliberately.

**Carrying forward to Phase 8** (Final cleanup + invariant promotion):
- Author `phases/phase-8.md` at start of Phase 8 work.
- Repo grep-clean for any lingering `genomeclaw-prep` / flat-name references in docs / plans / agent files (Phase 1's clean-slate cutover deleted the code; cleanup is the doc surface only).
- `INV-Cxxx` (CLI output stability) → canonical in INVARIANTS.md after privacy-safety-reviewer pass.
- `INV-S-confirmation-required` (provisional in Phase 6) — consider promoting alongside `INV-Cxxx` if it holds across Phase 7's polish.
- Plan move: `docs/plans/active/rich-cli/` → `docs/plans/completed/rich-cli/`.

---

### Phase 8: Final cleanup + invariant promotion
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Test Results

```text
=== pytest ===
391 passed, 61 skipped in 4.31s     (+3 over Phase 7: regression-guard tests)

=== ruff check (strict rule set) ===
All checks passed!

=== ruff format --check ===
152 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 24 source files

=== Privacy-safety-reviewer pass ===
Verdict: Accept with one required change (resolved).
- Egress surface: green (no new endpoints; fetcher tightened existing surface).
- Agent-facing data flow: green (paths + IDs + counts; no variant data).
- INV-C002 category placement: green (Communication, not Clinical Boundary — cosmetic tension acknowledged).
- INV-D004 typed-confirmation: green.
- Cleanup completeness: yellow → fixed. Schema doc's `tool: "genomeclaw-prep"` example needed an annotation; added.
- Provenance literal preservation: green (right call for INV-R001 rebuildability).
```

#### Results

**Files created**:
- `tests/integration/test_no_legacy_cli_references.py` — 3 regression-guard tests: (1) user-facing docs have no `genomeclaw-prep` references (with `cli-output-schemas.md` carved out, documented in the test's docstring); (2) INV-C002 is in INVARIANTS.md; (3) INV-D004 is in INVARIANTS.md.

**Files modified** — doc cleanup pass (verb-aware rewrite: `genomeclaw-prep <verb>` → `genomeclaw <group> <verb>`, with group mapping `ingest|normalize|annotate|materialize → pipeline`, `fetch → refs`, `setup|eject|doctor → host`, bare `pipeline → pipeline run`):
- `README.md`
- `docs/reference/architecture.md`
- `docs/reference/user-stories.md`
- `docs/reference/INVARIANTS.md` — body cleanup + 2 new invariant sections + index rows + version 1.6 → 1.7
- `docs/reference/grand-plan.md`
- `docs/reference/cli-output-schemas.md` — added annotation explaining the legacy `"tool": "genomeclaw-prep"` provenance literal (per privacy-safety-reviewer)
- `docs/reports/open-source-tool-alignment.md`

**Files modified** — source-code sweep (provenance `tool="genomeclaw-prep"` literal **deliberately preserved** for back-compat with existing `manifest.json` files; everything else swept):
- All 14 `packages/toolkit/src/genomeclaw_toolkit/prep/**/*.py` modules — docstring headers, error messages, setup-output instructions, doctor-failure hints, release-set comments
- `packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml`

**Files modified** — test cleanup (`pytest.raises(... match="...")` regex strings + provenance assertion strings):
- 17 test files across `tests/integration/`, `tests/invariants/`, `tests/provenance/`, `tests/test_smoke.py`

**Invariants promoted to canonical**:
- **INV-C002 — CLI Output Contract Stability** (Communication & Clinical Boundary category, second invariant in the category). Pins the `--json` schema versioning, NDJSON event-stream shape with `"stream": true` discriminator, stdout-vs-stderr split, and the `stdout_already_consumed` sentinel for routing trailing error envelopes to stderr after a payload has been emitted.
- **INV-D004 — Destructive Operations Require Explicit Confirmation** (Data Integrity category, fourth invariant in the category). Pins the typed-confirmation pattern (operation-specific phrase or `--yes`), the non-TTY refusal, the independence from `--force` (pipeline-safety bypass).

#### Notes

**Verb-aware cleanup**: a simple `sed s/genomeclaw-prep/genomeclaw/g` would have produced wrong commands (`genomeclaw fetch` doesn't exist; it's `genomeclaw refs fetch`). Wrote a Python rewrite pass with the verb → group mapping in `GROUPS`. Three-pass approach: (1) match `genomeclaw-prep pipeline` → `genomeclaw pipeline run` first (the special case); (2) match `genomeclaw-prep <verb>` and substitute via the mapping; (3) catch the bare `genomeclaw-prep` (binary name, entry-point references) as the final fallback. The provenance `tool` literal was protected with a temporary sentinel string to survive the bare-name rewrite.

**Privacy-safety-reviewer yellow item**: the `runs show` schema example in `cli-output-schemas.md` showed `"tool": "genomeclaw-prep"` without explaining why. An agent reading the schema doc would encode `"genomeclaw-prep"` as a hard contract value and then mis-validate when new runs carry `"genomeclaw"`. Fixed with a one-paragraph note in the schema doc explaining that the field carries the value recorded at run time, that existing runs carry the legacy value (preserved for `INV-R001` rebuildability), and that agents should accept either string without branching. The fix is documentation-only; the source-code literal stays preserved.

**Why preserve the provenance literal at all**: `manifest.json` and `provenance.json` files are stable artifacts on disk that agents read for rebuildability + audit. Silently changing the literal would break the contract that the same pipeline-version code reproduces the same provenance entries from the same inputs. The right migration path for the literal is a schema version bump, not a silent rename. That migration is left as a future task gated behind an INV-R001 review.

#### Carry-out

- **MVP plan still on hold**. `docs/plans/active/mvp/` is untouched by Phase 8 (deliberately out of scope). The MVP plan resumes after the user re-fetches the 5 truncated gnomAD files (which Phase 4's `refs fetch` UX now makes observable) and the 4C.4 W2+ work can proceed.
- **Provenance literal migration** is a follow-up task. When ready, it lands as a schema-version bump with a deprecation cycle (new runs write `"tool": "genomeclaw"`; manifest parsers accept either).
- **Real-pipeline end-to-end smoke** against the project owner's VCF inside the toolkit Docker image — pending; tracked under MVP 4C.4 W4 resume.

---

## Plan moved to `docs/plans/completed/rich-cli/`

This work-notes file is the historical record. New work doesn't extend this plan; new work opens a new plan in `docs/plans/active/<feature>/`.

---

(Phase 8 stub moved up — see entry above for current state.)

---

### 2026-05-12 — Plan restructure: split fat Phase 4 into Phases 4 + 5; remap downstream

**Trigger**: project owner reviewed the Phase-3-closure-drafted Phase 4 and flagged it as too large — three mostly-independent workstreams (refs fetch UX + pipeline UX + per-orchestrator callbacks + strict-typing graduation of 5 prep/ modules) stacked into one phase.

**Decision**: 8-phase plan (was 7). Splits + remaps:

- **Phase 4** (new shape): `refs fetch` rich UX only. Small (~5 tests, ~1 session). Self-contained — uses Phase 3's already-plumbed `progress_callback` hook in `prep/fetch.py`; no orchestrator changes. Establishes the rich Progress driver + NDJSON first-line-envelope convention.
- **Phase 5** (new): pipeline UX + per-orchestrator callbacks + graduate-as-you-go strict typing. The 4 `prep/` orchestrators (`ingest`, `normalize`, `annotate_vcfanno`, `materialize`) each grow a `progress_callback` parameter AND graduate to `mypy --strict` simultaneously — touching the module twice (once for callbacks, once for hygiene) would be wasteful. ~20 tests, ~2 sessions.
- **Phase 6** (was 5): destructive commands. Unchanged scope.
- **Phase 7** (was 6): polish (tab completion, "did you mean", `--version` enrichment, cold-start audit). Unchanged scope.
- **Phase 8** (was 7): final cleanup + `INV-Cxxx` promotion. Shrunk because Phase 1's clean-slate cutover already deleted what the old "Removal" phase was supposed to remove.

**Why a separate strict-typing phase was rejected**: each module touched in Phase 5 for the callback parameter is the same module that needs to graduate. Doing both in the same diff amortises the context-load cost. A standalone hygiene phase would require re-entering each module without the why-am-I-here context the callback work provides.

**Why removal/cleanup stays a separate phase (Phase 8)**: the `INV-Cxxx` promotion needs a ceremonial close (privacy-safety-reviewer pass, plan move from `active/` to `completed/`, INVARIANTS.md version bump). Distinct enough from Phase 7's user-facing-ergonomics work that bundling would muddy the closure narrative.

**Estimated impact**: total test count grows ~105 → ~116; total days ~13 → ~14.

**Files updated**:
- `phases/phase-4.md` — rewritten (slim refs-fetch-UX scope).
- `phases/phase-5.md` — created (pipeline UX + callbacks + graduate-as-you-go).
- `development-plan.md` — Phase Overview table + per-phase narratives + Progress Tracking renumbered for the 8-phase shape.

---

### Phase 3: Fetcher correctness (scoped slice)
**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12

#### Scope-down decision

Original Phase 3 combined four substantial workstreams (fetcher correctness + per-orchestrator callbacks + NDJSON event stream + strict-typing graduation of 5 prep modules). Sized against a single focused session and the project owner's actual blocker (the 5 truncated gnomAD chrom files preventing MVP 4C.4 W2+), only **fetcher correctness** was on the critical path. The other three workstreams are valuable but not blocking — they shift to Phase 4. The rich-cli plan accordingly grows from 6 to 7 phases.

This avoids the trap of "Phase 3 is X% done" status updates. Either fetcher correctness ships cleanly + unblocks MVP resume, or it doesn't. Bundling UX migration would have stretched the diff to multiple sessions and risked landing a partial migration alongside a correctness fix.

#### Test Results

```text
=== pytest ===
341 passed, 61 skipped in 2.95s     (+16 over Phase 2: 7 events + 9 fetcher correctness)

=== ruff check (strict rule set) ===
All checks passed!

=== ruff format --check ===
139 files already formatted

=== mypy --strict src/genomeclaw_toolkit/_cli ===
Success: no issues found in 20 source files
```

#### Results

**Files created**:
- `src/genomeclaw_toolkit/prep/_events.py` — `ProgressEvent` frozen-dataclass hierarchy (8 event types: `FileStart`, `FileProgress`, `FileComplete`, `FileFailed`, `PhaseStart`, `PhaseComplete`, `PhaseFailed`, `PipelineComplete`). `to_json_dict()` emits the NDJSON discriminator-first shape. Lives in `prep/` not `_cli/` to respect the strict-boundary rule (`prep/` can't import from `_cli/`).
- `tests/integration/test_progress_event.py` — 7 dataclass + serialisation tests.
- `tests/integration/test_fetch_correctness.py` — 9 fetcher tests (Content-Length verification, bgzip-EOF check, resume-on-stall, server-ignores-Range fallback, MD5 across resume, retry exhaustion, progress callback emission).

**Files modified**:
- `src/genomeclaw_toolkit/prep/_bgzip.py` — added `IncompleteBgzip` exception, `BGZIP_SUFFIXES` constant, `is_bgzip_target()` helper.
- `src/genomeclaw_toolkit/prep/fetch.py`:
  - New exceptions: `TruncatedDownload`, `DownloadStalled`.
  - Rewrote `_stream_to_file` with: per-attempt loop, `Range:` reconnects, exponential backoff (capped at 30s), MD5 re-seeded from on-disk bytes on resume, HTTP-200-on-Range fallback detection (`status == 200 and bytes_so_far > 0` → restart from byte 0), final Content-Length verification.
  - `_fetch_one_file` gates `verify_bgzip_eof_marker()` for bgzip targets after the download, before sidecar fetch; emits `FileStart` / `FileProgress` / `FileComplete` events via optional `progress_callback`.
  - `fetch()` gains: `progress_callback`, `max_resume_attempts`, `retry_backoff_initial_sec`, `retry_backoff_cap_sec`.
- Existing fetch tests (`test_fetch_mocked.py`, `test_fetch_dbsnp.py`, `test_fetch_gnomad.py`, `test_fetch_progress.py`) updated to append `BGZF_EOF_MARKER` to their synthetic payloads — required now that the bgzip-EOF gate fires on every `.vcf.gz` / `.vcf.bgz` / `.bcf`.

#### Notes

**Werkzeug auto-Content-Length lesson**: the initial fetcher-correctness tests passed individually but were silently wrong. werkzeug's default `Response(body, ...)` constructor recomputes `Content-Length` from the actual body length, so a handler "promising 78 bytes but shipping 32" actually shipped `Content-Length: 32`, and the fetcher saw a successful download. Fix: every test handler uses `Response(response=[body], direct_passthrough=True, headers={"Content-Length": ...})` to bypass the auto-recompute. Captured as a `_lying_response` helper in the test module.

**Module boundary catch**: first GREEN attempt put `events.py` in `_cli/` (per the original plan). That broke the strict boundary `prep/ → _cli/`: importing `_cli.events` triggers `_cli/__init__.py` which imports the command modules, which import back from `prep/fetch.py` → circular. Moved events to `prep/_events.py` (the orchestrator side, where the events originate). The CLI renderers will consume `from genomeclaw_toolkit.prep._events import ...` when Phase 4 wires the rich/JSON output.

**Resume math**: the retry budget is `1 + max_resume_attempts` total HTTP calls. Default `max_resume_attempts=5` → up to 6 attempts. `DownloadStalled` fires only after the budget is exhausted; `TruncatedDownload` fires when the final on-disk count is still short of `Content-Length` (typically when retries are disabled or the server-ignores-Range path bounces back to a fresh attempt). The test `test_fetch_raises_download_stalled_after_max_retries` exercises the budget exhaustion path with `max_resume_attempts=3` → expects 4 HTTP calls.

**Carrying forward to Phase 4**:
- Per-orchestrator callback plumbing: `prep/ingest.py`, `prep/normalize.py`, `prep/annotate_vcfanno.py`, `prep/materialize.py` each gain a `progress_callback: Callable[[ProgressEvent], None] | None = None` param; emit `PhaseStart` / `PhaseComplete` at appropriate seams.
- `pipeline run --json` NDJSON: the CLI wrapper aggregates per-stage events, writes one `{"event": ..., ...}` line to stdout per emission, keeps rich progress on stderr in non-JSON mode.
- `refs fetch` rich progress: the existing fetcher's `progress_callback` carries `FileProgress` events; Phase 4's rich renderer drives a `rich.progress.Progress` panel (one bar per file + overall on `--all`).
- Strict-typing graduation: each `prep/` module that grows a callback parameter graduates simultaneously — its per-file-ignore in `pyproject.toml` comes off and `mypy --strict` must pass on it.

---

## Key Decisions

### Decision 1: Framework — Typer (not Click, not argparse + rich)
**Date**: 2026-05-12
**Context**: We need a coherent CLI framework that supports subcommand groups, type-hint-driven flag definitions, tab completion, and structured output. Continuing with argparse + adding rich would mean hand-rolling every nice-to-have.
**Decision**: **Typer >= 0.12** (built on Click, uses Python type hints, supports nested apps, ships tab-completion plumbing).
**Rationale**: Type-hint-native API fits the codebase style. Nested apps (`app.add_typer(refs_app, name="refs")`) handle subgroups cleanly. Tab completion is a one-liner. Maintained by tiangolo (FastAPI). Apache 2.0.
**Alternatives Considered**:
- **Click directly**: more mature, more verbose, less type-hint-friendly. Rejected: incremental gain over Typer not worth the decorator burden.
- **argparse + rich**: zero new deps for the framework. Rejected: means hand-rolling subgroups, completion, "did you mean", --json mode, etc. The time we'd save on the dep is consumed twice over by hand-rolled glue.
- **Cyclopts**: newer, Pydantic-native. Rejected: not enough adoption to bet on for an MVP foundation.
**Affected Invariants**: indirectly enforces `INV-Cxxx` (provisional CLI output stability) by giving us the framework primitives.

### Decision 2: Subcommand grouping via aliases (not migration)
**Date**: 2026-05-12
**Context**: Today every command is at the flat top level. Best-practice CLI design groups by noun (`refs fetch`, `runs list`). But every existing test + doc + agent invocation uses the flat names.
**Decision**: Introduce the noun-grouped commands as the canonical form; keep flat names working as aliases for two minor releases; deprecation warnings start in Phase 6.
**Rationale**: Breaking-change for end-users + agents + tests has a high cost. Aliases let us evolve without breaking anyone.
**Alternatives Considered**:
- **Hard migration**: rename and break. Rejected.
- **Stay flat forever**: never get the gcloud-style ergonomics. Rejected as a design ceiling.
**Affected Invariants**: none directly; sets up the migration path.

### Decision 3: 4C.4 W6a coordination (pending user confirmation)
**Date**: 2026-05-12
**Context**: Phase 4C.4 W6a scopes a small (~3h) rich adoption for fetch + doctor + pipeline. This plan covers the same surfaces plus everything else. Doing both means rich-integrating twice.
**Decision (proposed)**: Drop W6a from 4C.4; absorb its scope into this plan's Phase 1. 4C.4 W7 (the ClinVar parity check) runs with the new CLI from day one.
**Rationale**: Avoid duplicate work; one coherent rich-integration story.
**Alternatives Considered**:
- **Ship W6a now, full migration later**: W6a is small enough to ship in a session; the gain is immediate UX for W7. But the work gets thrown away when this plan starts. Rejected unless user explicitly wants the immediate UX gain.
**Affected Invariants**: none directly.

---

## Files Modified

*(filled during implementation)*

### Created
- `docs/plans/active/rich-cli/spec.md` — 2026-05-12 (this session)
- `docs/plans/active/rich-cli/development-plan.md` — 2026-05-12
- `docs/plans/active/rich-cli/phases/phase-1.md` — 2026-05-12
- `docs/plans/active/rich-cli/work-notes.md` — 2026-05-12

### Modified
*(none yet)*

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Add `INV-Cxxx`: CLI Output Contract Stability — after Phase 6 close, gated on privacy-safety-reviewer pass.

### Other Documentation
- [ ] `docs/reference/cli-output-schemas.md` — created in Phase 1 (skeleton + `doctor` schema); populated incrementally each subsequent phase.
- [ ] [README.md](../../../README.md) — Getting Started + examples migrated to canonical names. Phase 6.
- [ ] [docs/reference/architecture.md](../../reference/architecture.md) — host-side-packaging section. Phase 6.
- [ ] [`CLAUDE.md`](../../../CLAUDE.md) (root) — example commands updated. Phase 6.
- [ ] [`.claude/agents/bioinformatics-pipeline.md`](../../../.claude/agents/bioinformatics-pipeline.md), `.claude/agents/report-generator.md` — CLI references audit. Phase 6.
- [ ] `docs/plans/active/mvp/phases/phase-4-completion.md` + `phase-4c4-annotation-correctness.md` — procedure-block CLI commands updated. Done in passing as 4C.4 work lands using the new CLI.

---

## Open Risks & Follow-ups

- **Typer's `--install-completion` writes to user shell config** — convenience feature, but at odds with our principle of "the CLI doesn't modify state outside its bind-mounts unless explicitly asked." Resolution: Phase 5 ships `genomeclaw completion <shell>` that *emits* the script to stdout; user pipes it manually. No `--install-completion` flag that writes to `~/.bashrc` automatically.
- **`progress_callback` hook ergonomics across orchestrators** — three orchestrators (`fetch`, `ingest`, `annotate_vcfanno`) need to accept the callback. Each has its own progress-reporting style today. Phase 3 may surface that a common `ProgressEvent` dataclass needs more fields than we predicted. Iterate via an `initial_findings.md` in Phase 3 if it gets complex.
- **CI runtime increase** — adding ~105 tests will slow CI from ~1.4s to ~3–5s. Acceptable; not blocking.
- **Typer + rich version drift** — pin `typer ~= 0.12` and `rich ~= 13` in pyproject.toml; bump deliberately, not via uv-resolved-latest.
- **Subcommand-group renaming friction in Phase 6** — existing tests + docs + the shim reference flat names. Phase 6 cleanup may take longer than estimated. Mitigation: do the grep-replace early in Phase 6.

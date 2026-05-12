# Phase 1: Foundation — Typer + rich + doctor as reference command

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Stand up the Typer + rich infrastructure for the entire CLI migration. Establish every cross-cutting convention (output modes, exit codes, schema versioning, structured errors, TTY detection, `--version` reporting). Migrate one reference command — `doctor` — fully through the new framework as the canonical pattern that Phase 2+ replicates for every remaining command.

Phase 1's success criterion is straightforward: `genomeclaw doctor` produces identical exit codes + identical JSON-mode output as today's `genomeclaw-prep doctor`, but with rich-rendered tables on TTY and an established framework underneath that Phase 2 can extend without further design work.

## Scope Boundaries

**In scope** (clean-slate cutover; no back-compat):
- New `_cli/` Python package per the [development-plan § module architecture](../development-plan.md): `__init__.py`, `context.py`, `console.py`, `output.py`, `errors.py`, `tool.py`, `version.py`, `commands/`, `renderers/`, `types/`.
- Top-level Typer app registered as the `genomeclaw` entry point in `pyproject.toml`. **`genomeclaw-prep` entry point deleted.** **`bin/genomeclaw-prep` deleted** and replaced by `bin/genomeclaw`.
- The old [`packages/toolkit/src/genomeclaw_toolkit/cli.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/cli.py) is **deleted entirely**. Its argparse-based dispatcher is replaced by the new Typer app.
- **`host doctor` fully migrated**: rich-rendered Table on TTY, structured JSON on `--json`. The orchestrator `prep/doctor.py:doctor()` is unchanged; only the dispatch + rendering layer changes. `prep/doctor.py:render_text` is deleted (moved to `_cli/renderers/host.py`).
- **All other commands (`refs fetch`, `pipeline ingest`, `pipeline normalize`, `pipeline annotate`, `pipeline materialize`, `pipeline run`, `host setup`, `host eject`) ship as thin Typer wrappers** under `_cli/commands/` from Phase 1. They route directly to the existing orchestrators in `prep/`. They use the new error envelope + new `AppContext` but **do NOT yet render rich progress bars or emit `--json` payloads** — those upgrades land in their owning phase (2 / 3 / 4). This is what keeps the test suite green through the cutover.
- `--version` flag + `version` subcommand reporting toolkit version + image digest.
- `docs/reference/cli-output-schemas.md` skeleton + `doctor` schema documented.
- **Every existing test that imports `from genomeclaw_toolkit.cli import main`** is migrated to import from `genomeclaw_toolkit._cli` and uses the new hierarchical command paths (`main(["host", "doctor"])`, `main(["refs", "fetch", ...])`, `main(["pipeline", "ingest", ...])`, etc.). The argparse-based `cli.py` is gone; tests can no longer reference it.
- New tests: `tests/integration/test_cli_framework.py`, `tests/integration/test_cli_host_doctor.py`, `tests/privacy/test_invP001_cli_no_egress.py`.
- **Strict quality bars enabled from Phase 1**: `mypy --strict` on `_cli/`; ruff strict rule set per the [Quality Bar section](../development-plan.md#quality-bar-enforced-from-phase-1); pristine docstrings on every public surface.

**Out of scope** (deferred to later phases):
- Rich progress bars + `--json` mode for `refs fetch`, `pipeline {ingest,normalize,annotate,materialize,run}`, `host {setup,eject}` (Phase 2 / 3 / 4). Phase 1 ships them as functional thin wrappers; their owning phase upgrades them.
- `refs` informational commands (`refs list`, `refs verify`, `refs info`) — Phase 2.
- `runs` subgroup entirely — Phase 2.
- Tab completion (Phase 5).
- Fetcher correctness fixes (Phase 3 — absorbed from 4C.4 W1 + W1.5).
- Streaming NDJSON events (Phase 3).
- Confirmation prompts for destructive ops (Phase 4).
- "Did you mean" Damerau-Levenshtein matcher (Phase 5).

## Invariants Enforced in This Phase

- **INV-P001** Privacy Is the Default Operating Mode — `test_invP001_cli_no_egress_doctor` exercises the full `doctor` command (both rich + JSON modes) under a mocked `urllib.request.urlopen` that fails on any call. Asserts call count remains 0. Phase 2+ extend the same test file to cover more commands.
- **NEW provisional `INV-C-cli-output-stability`** — every test that exercises `--json` mode asserts the top-level `cli_output_schema_version` field is present, populated, and parseable as semver. Tests cite the provisional ID in their docstring. Promotion to the canonical INVARIANTS.md happens at Phase 6 close (assumes a privacy-safety-reviewer pass).

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Cross-cutting tests** (`tests/integration/test_cli_framework.py`):

1. `test_genomeclaw_entry_point_exists` — `genomeclaw --help` exits 0; output contains the program name. Fails today because the entry point doesn't exist yet.
2. `test_genomeclaw_help_cold_start_under_200ms` — measures wall time of `genomeclaw --help` via subprocess; asserts < 0.20s. (Pinned to the project owner's host; CI may want a more lenient threshold — flag for review.)
3. `test_global_json_flag_emits_structured_payload` — `genomeclaw host doctor --json` stdout parses as JSON; contains `cli_output_schema_version`. Fails because `doctor` isn't migrated yet.
4. `test_global_json_flag_progress_to_stderr` — `genomeclaw host doctor --json` keeps progress/log output on stderr; stdout is JSON-only.
5. `test_global_quiet_suppresses_log_info` — `genomeclaw host doctor --quiet` produces no `[INFO]` lines on stderr; only errors + final status.
6. `test_global_no_color_disables_ansi` — `genomeclaw host doctor --no-color` (TTY-mocked-true) emits no ANSI escape codes.
7. `test_global_force_color_enables_ansi_off_tty` — `genomeclaw host doctor --force-color` (TTY-mocked-false) emits ANSI escapes anyway.
8. `test_exit_code_2_on_invalid_flag_combo` — `genomeclaw host doctor --bogus-flag` exits 2 before reaching the handler.
9. `test_exit_code_3_on_missing_precondition` — `genomeclaw host doctor` with `GENOMECLAW_*_DIR` env unset and no canonical layout returns exit 3 with a clear error message (today this exits 2; the contract change is part of Phase 1).
10. `test_version_flag_reports_toolkit_version_and_image_digest` — `genomeclaw --version` output (both rich + JSON) contains `toolkit_version` + `image_digest` fields.
11. `test_invP001_no_egress_during_doctor_both_modes` — uses an autouse fixture that monkey-patches `urllib.request.urlopen` to raise; runs `genomeclaw host doctor` and `genomeclaw host doctor --json`; asserts the patched call count remains 0 for the duration.
12. `test_legacy_flat_doctor_emits_deprecation_warning` — `genomeclaw doctor` (flat form) still works but emits `DeprecationWarning: 'genomeclaw doctor' is deprecated; use 'genomeclaw host doctor' instead.` on stderr. Exit code 0 (the warning is a warning, not an error).
13. `test_legacy_genomeclaw_prep_emits_deprecation_warning` — `genomeclaw-prep doctor` (old entry point) still works but emits `DeprecationWarning: 'genomeclaw-prep' is deprecated; use 'genomeclaw' instead.` on stderr.
14. `test_legacy_deprecation_warning_in_json_mode_goes_to_stderr` — `genomeclaw doctor --json` (flat form) emits the structured JSON to stdout AND the deprecation warning to stderr. Stdout is parseable JSON; stderr has the warning. Agents see both.

**Per-command tests** (`tests/integration/test_cli_doctor.py`):

12. `test_doctor_rich_mode_renders_reference_table_on_tty` — uses `Console(record=True, force_terminal=True)`; runs `doctor`; assertion is on captured cell content (e.g. row count matches reference-source count, every source has a status cell).
13. `test_doctor_rich_mode_renders_plain_text_off_tty` — same but `force_terminal=False`; asserts no ANSI bytes in captured output.
14. `test_doctor_json_mode_schema_v1_0` — `doctor --json` payload validates against the schema in `cli-output-schemas.md § doctor`. Asserts `cli_output_schema_version == "1.0"`.
15. `test_doctor_json_mode_idempotent_with_prep_doctor` — `doctor --json` output equals (modulo `cli_output_schema_version`) the existing `genomeclaw-prep doctor --json` output for the same layout. Catches accidental schema drift during the migration.
16. `test_doctor_exit_code_zero_on_clean_layout` — happy path; returns 0; report contains no error envelopes.
17. `test_doctor_exit_code_3_on_missing_reference_root` — precondition error; returns 3; JSON output contains `error_type: "precondition_error"`.
18. `test_doctor_debug_flag_includes_traceback_in_json_envelope` — `doctor --json --debug` against an injected exception; payload's `error` field includes a `traceback` array.
19. `test_doctor_rich_mode_error_renders_panel_with_suggested_actions` — Rich-mode error against an injected exception; captured output contains the suggested-actions text.

**RED step expected output**:

```text
$ uv run pytest tests/integration/test_cli_framework.py tests/integration/test_cli_doctor.py -q
ImportError: cannot import name 'app' from 'genomeclaw_toolkit._cli'
========================
19 errors / failures (collection failed for missing _cli/ package; or individual tests fail with appropriate AssertionError once the package exists in skeleton form)
```

Paste the actual RED output into `work-notes.md` before proceeding to GREEN.

### Step 1.2 — GREEN: Minimal Implementation

Build out the `_cli/` package and the `doctor` migration. Each module listed below has a one-paragraph implementation note for the implementer; the goal is "smallest implementation that turns the tests green," not "complete framework."

**`packages/toolkit/src/genomeclaw_toolkit/_cli/__init__.py`** — instantiate a top-level `typer.Typer(name="genomeclaw", ...)` named `app`. Define the global flags (`--json`, `--quiet`, `--verbose`, `--debug`, `--no-color`, `--force-color`, `--version`, `--yes`) via Typer's callback mechanism. The callback resolves an `OutputMode` (rich vs json) + a `Verbosity` enum and stuffs them into the Typer `Context.obj` for downstream commands. Register the four (initially empty) subgroups: `refs`, `runs`, `pipeline`, `host`. Register `doctor` as a top-level alias (will move to `host doctor` in Phase 2's continued migration but stays as a top-level command for back-compat).

**`packages/toolkit/src/genomeclaw_toolkit/_cli/console.py`** — module-level `Console` singleton. Constructed lazily on first access so test fixtures can inject a `Console(record=True, file=StringIO(), force_terminal=...)` override. Helper `get_console()` returns the active console.

**`packages/toolkit/src/genomeclaw_toolkit/_cli/output.py`** — defines `OutputMode = Enum("rich", "json")`, `Verbosity = Enum("quiet", "normal", "verbose", "debug")`, and a small `OutputContext` dataclass holding both. Helper `emit(payload: dict, *, schema_version: str = "1.0")` does the right thing per mode: rich renders via templates; JSON serializes to stdout with the schema-version key prepended.

**`packages/toolkit/src/genomeclaw_toolkit/_cli/errors.py`** — `CliError(Exception)` base class with `error_type: str`, `message: str`, `details: dict`, `suggested_actions: list[str]`, `exit_code: int`. Renderers for both modes. Wrapper around Typer's `UsageError` so usage errors get the same envelope structure (still exit code 2 per the contract).

**`packages/toolkit/src/genomeclaw_toolkit/_cli/version.py`** — assembles the version string from `genomeclaw_toolkit.__version__` + `os.environ.get("GENOMECLAW_IMAGE_DIGEST")` + best-effort git commit (only when running from a checkout, not from an installed wheel). Used by `--version` and `version` subcommand.

**`packages/toolkit/src/genomeclaw_toolkit/_cli/doctor.py`** — migrated `doctor` command. Calls the existing `prep.doctor.doctor()` orchestrator (unchanged), then renders the result via `_cli.output.emit()` selecting either a rich `Table` (per-source rows; colored status cells) or the existing JSON payload (with `cli_output_schema_version: "1.0"` added at the top level).

**`packages/toolkit/src/genomeclaw_toolkit/_cli/legacy_aliases.py`** — defines the deprecation-warning shims:
- `genomeclaw_prep_main()` — entry-point function pointed at by the old `genomeclaw-prep` script. Prints `DeprecationWarning: 'genomeclaw-prep' is deprecated; use 'genomeclaw' instead. This entry point will be removed at Phase 6 close.` to stderr, then delegates to the new `genomeclaw` main.
- One typer command per flat-form alias (`doctor`, `fetch`, `ingest`, `normalize`, `annotate`, `materialize`, `pipeline`, `setup`, `eject`), each registering at the top-level app. Each emits its own deprecation warning naming the canonical hierarchical replacement, then delegates to the canonical command's handler. Phase 1 only implements the `doctor` alias's full behaviour (since `doctor` is the only migrated command in this phase); the rest emit a "not yet migrated; use `genomeclaw-prep doctor` for now" error until Phase 2+ migrates them. (Yes, that's a bootstrapping wart — see Edge Cases below.)

**`packages/toolkit/pyproject.toml`** — add:
```toml
[project]
dependencies = [
    ...,
    "typer >= 0.12, < 0.13",
    "rich >= 13.0, < 14",
]

[project.scripts]
genomeclaw = "genomeclaw_toolkit._cli:main"                                # new canonical
genomeclaw-prep = "genomeclaw_toolkit._cli.legacy_aliases:genomeclaw_prep_main"  # deprecation shim; removed Phase 6
```

**`packages/toolkit/uv.lock`** — regenerated via `uv sync`.

**`bin/genomeclaw`** — new shim. Near-copy of `bin/genomeclaw-prep` but with the canonical name. Reuse the docker-bind-mount machinery.

**`bin/genomeclaw-prep`** — kept; invokes the legacy entry point inside the container. The deprecation warning fires from inside the container. Removed entirely at Phase 6.

**`docs/reference/cli-output-schemas.md`** — new doc. Top-level intro explains the contract (`cli_output_schema_version`, stdout-only for JSON, stderr for progress, etc.). First section documents the `doctor` schema:

```json
{
  "cli_output_schema_version": "1.0",
  "command": "doctor",
  "report": {
    "host_layout": { ... },
    "setup_log": { ... },
    "colima": { ... },
    "references": [ ... ],
    "raw_sample": { ... },
    "derived_runs": [ ... ]
  }
}
```

### Step 1.3 — REFACTOR

With tests green:

- Extract `_render_doctor_report_as_table()` from `_cli/doctor.py` if duplication has actually appeared (it shouldn't, since `doctor` is the only command using it in Phase 1).
- Tighten types: every public function in `_cli/` should have a complete type signature; private helpers may use inference.
- Add comments only at places where the *why* is non-obvious (e.g. why `Console` is lazily constructed; why `Verbosity` is an enum and not a string).
- Re-run tests after each refactor step.

---

## Implementation Details

### Output mode resolution

At CLI entry, the global callback resolves the mode as follows:

1. If `--json` is set → `OutputMode.JSON`.
2. Else if `--force-color` is set → `OutputMode.RICH` (with color forced).
3. Else if stdout is not a TTY → `OutputMode.RICH` (with color disabled; rich detects this automatically).
4. Else → `OutputMode.RICH` (with color).

`--quiet` and `--verbose` are independent of mode and affect only what gets emitted, not how it's rendered.

### Exit-code mapping in `_cli/errors.py`

Each `CliError` subclass defines its own `exit_code`:

```python
class RuntimeError(CliError): exit_code = 1
class UsageError(CliError): exit_code = 2          # Typer's UsageError wrapped
class PreconditionError(CliError): exit_code = 3
class DataIntegrityError(CliError): exit_code = 4
```

The top-level Typer callback catches `CliError` and renders the envelope (rich or JSON), then exits with the correct code. `KeyboardInterrupt` is caught and exits 130.

### Doctor JSON schema details (v1.0)

The existing `doctor()` orchestrator returns `(exit_code, report_dict)`. The migration is mostly:

```python
exit_code, report = doctor_impl()  # unchanged
payload = {
    "cli_output_schema_version": "1.0",
    "command": "doctor",
    "report": report,
}
emit(payload, mode=ctx.obj.output_mode)
raise typer.Exit(exit_code)
```

The `report` dict structure is what the existing `doctor()` already returns. The migration **does not** change field names or nesting — that's a separate effort. We just stamp `cli_output_schema_version` on top.

### Edge Cases to Handle

- **Missing canonical layout** — today's `doctor` runs anyway and reports missing pieces. The migration preserves this; the JSON output includes the partial state. Exit code is `3` (precondition error) only when *no* canonical paths resolve; otherwise `0` with status fields populated.
- **`--json` + `--quiet` combination** — JSON to stdout; everything else (including the final "success" rich-rendered summary) suppressed. Exit code conveys success/failure.
- **TTY mocked in tests** — use `Console(force_terminal=True, file=StringIO(record=True))`; assertions on cell content, not byte bytes.
- **`--version` with `--json`** — emits a structured payload (`{"toolkit_version": "...", "image_digest": "...", "git_commit": "..."}`) instead of a human string.
- **Flat-form aliases for not-yet-migrated commands** — Phase 1 only fully migrates `doctor`. The other 8 flat names (`fetch`, `ingest`, `normalize`, `annotate`, `materialize`, `pipeline`, `setup`, `eject`) need to keep working through Phases 2–5 because the old `cli.py` is what implements them. Resolution: Phase 1's `legacy_aliases.py` only registers a wrapper for the migrated commands (just `doctor` in Phase 1). Flat-form invocations of un-migrated commands route through to the original argparse-based `cli.py` (kept alive until Phase 6). The argparse-based `cli.py` keeps its current behaviour for the duration of the migration — it's the deprecation-warning shim's fallback. Cleaner than I'd like, but the alternative (full big-bang rewrite in Phase 1) is much worse.
- **Deprecation warning in test capture** — tests that assert no warnings on the canonical-form invocation must scope their stderr check to exclude the legacy-form deprecation warning. Use Python's `warnings.catch_warnings()` to scope warning capture.

### Error Handling

- **Unexpected exception** in a command handler → caught at the top-level callback, wrapped in `CliError(error_type="internal_error", message=str(exc), exit_code=1)`. In `--debug` mode the traceback is included.
- **Typer's own `UsageError`** → wrapped to match our envelope shape; exit code 2.
- **`KeyboardInterrupt`** → caught; prints `Interrupted.` to stderr; exits 130.

### Privacy / Egress Notes

- Phase 1's privacy-default test (`test_invP001_no_egress_during_doctor_both_modes`) uses an autouse fixture that monkey-patches `urllib.request.urlopen` to raise `RuntimeError("Unexpected outbound HTTP call")`. If `doctor` ever tries to fetch anything remote, the test blows up.
- No `--telemetry` / `--update-check` / etc. flags introduced. Hard line.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/__init__.py` | CREATE | Top-level Typer app + global flag callback |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/console.py` | CREATE | Rich Console singleton |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/output.py` | CREATE | OutputMode + Verbosity + `emit()` helper |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/errors.py` | CREATE | Structured error envelope + exit-code mapping |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/version.py` | CREATE | `--version` flag + `version` subcommand |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/doctor.py` | CREATE | Migrated `doctor` command |
| `packages/toolkit/pyproject.toml` | MODIFY | Add typer + rich deps; add `genomeclaw` entry point |
| `packages/toolkit/uv.lock` | MODIFY | Regenerated by `uv sync` |
| `bin/genomeclaw` | CREATE | Sibling shim alongside `bin/genomeclaw-prep` |
| `docs/reference/cli-output-schemas.md` | CREATE | Schema doc; `doctor` schema as the first entry |
| `tests/integration/test_cli_framework.py` | CREATE | 11 cross-cutting tests |
| `tests/integration/test_cli_doctor.py` | CREATE | 8 doctor-specific tests |
| `tests/privacy/test_invP001_cli_no_egress.py` | CREATE | Phase 1 contributes `test_invP001_no_egress_during_doctor_both_modes` |
| `docs/plans/active/rich-cli/work-notes.md` | APPEND | RED output, GREEN session log, decisions made |
| `docs/plans/active/rich-cli/phases/phase-2.md` | CREATE (at Phase 1 close) | Next phase's plan |

---

## Verification

```bash
# Run this phase's tests
cd packages/toolkit
uv run pytest tests/integration/test_cli_framework.py tests/integration/test_cli_doctor.py tests/privacy/test_invP001_cli_no_egress.py -v

# Run the full host suite (catch regressions in unrelated code paths)
uv run pytest -q

# Static checks
uv run ruff check .
uv run ruff format --check .

# Smoke-test the new CLI (canonical form)
uv run genomeclaw --help
uv run genomeclaw --version
uv run genomeclaw host doctor
uv run genomeclaw host doctor --json
uv run genomeclaw host doctor --quiet
uv run genomeclaw host doctor --debug

# Smoke-test deprecation warnings (legacy forms still work but warn)
uv run genomeclaw doctor                  # → deprecation warning to stderr + result
uv run genomeclaw-prep doctor             # → deprecation warning to stderr + result
uv run genomeclaw doctor --json 2>/dev/null | jq .   # stdout still valid JSON

# Compare new vs old contract: should be schema-additive only
uv run genomeclaw host doctor --json | jq 'del(.cli_output_schema_version)' > /tmp/new.json
uv run genomeclaw-prep doctor --json 2>/dev/null > /tmp/old.json
diff /tmp/old.json /tmp/new.json  # should be empty

# Cold-start timing (target: ≤ 200 ms)
time uv run genomeclaw --help > /dev/null

# Image-level smoke (rebuild required after pyproject.toml change)
docker build --tag genomeclaw/toolkit:dev packages/toolkit
bin/genomeclaw host doctor
bin/genomeclaw host doctor --json
```

---

## Completion Criteria

- [ ] All 22 listed test cases pass (14 framework + 8 doctor).
- [ ] Privacy-default test passes (`test_invP001_no_egress_during_doctor_both_modes`).
- [ ] Static checks pass (`ruff check`, `ruff format --check`).
- [ ] `genomeclaw host doctor --json` output diff against `genomeclaw-prep doctor --json` is exactly the `cli_output_schema_version` field addition.
- [ ] Cold-start `genomeclaw --help` ≤ 200 ms on the project owner's host.
- [ ] `docs/reference/cli-output-schemas.md` exists with the contract intro + `doctor` schema documented.
- [ ] No new outbound HTTP calls (asserted by the privacy test).
- [ ] Legacy forms (`genomeclaw doctor`, `genomeclaw-prep doctor`) work + emit deprecation warnings; structured-JSON output still valid in both forms.
- [ ] `work-notes.md` updated with RED output, design decisions taken, and final session state.
- [ ] Phase status updated in `development-plan.md` (Phase 1 → Complete).
- [ ] `phases/phase-2.md` drafted (per the planning protocol's "next-phase plan authored before current-phase closes" expectation).

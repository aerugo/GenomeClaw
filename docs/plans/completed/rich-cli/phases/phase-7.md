# Phase 7: Polish + agent ergonomics

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-6.md](phase-6.md) — destructive commands shipped with typed-confirmation prompts.
**Successor**: [phase-8.md](phase-8.md) — final cleanup + `INV-Cxxx` promotion.

---

## Objective

Add the last layer of CLI polish that distinguishes a tool that's *usable* from a tool that's *delightful to use*. Specifically:

1. **Tab completion** — `completion bash|zsh|fish` subcommand emits a shell-specific completion script the user pipes into their shell config. Typer ships the completion plumbing via Click; Phase 7 exposes it under a stable command name + pins the contract that the script writes to stdout (never auto-modifies user shell configs).
2. **"Did you mean" suggestions** — when the user mistypes a subcommand (`genomeclaw doctr`, `genomeclaw pipline run`), the error message surfaces the closest matches by Damerau-Levenshtein distance. Typer/Click doesn't ship this; implement as a wrapper around the `click.UsageError` handler in `_cli/__init__.py`.
3. **Cold-start performance gate** — pin a perf test asserting `genomeclaw --help` runs under a documented wall-clock budget. The realistic target is **≤ 1.0 s** on the project owner's host (M-series Mac); the aspirational target from the original plan was 200 ms but that pre-dated the Typer + Pydantic + rich dependency footprint. Test guards against regressions, not against an absolute number.

**Out of scope** (covered elsewhere or already done):

- `--version` flag — already shipped in Phase 1 (`_cli/version.py`).
- `--debug` flag — already shipped in Phase 1 (`_emit_error()` includes the traceback when set).
- Lazy-import discipline — already enforced by the strict `prep/ → _cli/` boundary from Phase 1; no new work needed. The perf gate verifies it's holding.
- Flat-command removal + `INV-Cxxx` promotion — Phase 8.

## Scope Boundaries

**In scope**:

- New `_cli/commands/completion.py` module with a `completion <shell>` Typer command. Shells supported: `bash`, `zsh`, `fish` (Typer's built-in set).
- The completion script is **emitted to stdout**, never auto-installed. The doc string + `--help` for the command explain how to pipe it into the user's shell config.
- New `_cli/suggest.py` helper with `suggest_closest(user_input, candidates, *, max_distance=3) -> list[str]` — pure Damerau-Levenshtein over the candidate list. Used by the top-level usage-error handler when a Typer subcommand parse fails.
- `_cli/__init__.py:main()` — when Typer raises a `UsageError` whose message looks like "No such command 'X'", the handler enumerates registered commands, runs `suggest_closest`, and rewrites the error envelope's `suggested_actions` to include "Did you mean: …" hints.
- New `tests/perf/test_cli_cold_start.py` — measures `genomeclaw --help` wall time; asserts it's under 1.0 s; failure mode is regression-detection, not absolute timing.
- Privacy-default test extended with one `completion` case (the command should be entirely local — emits a script to stdout, no network).

**Out of scope** (deferred):

- Flag-level completion (vs subcommand-level only). Typer's completion script handles flags by default; we don't add custom completer functions for path arguments etc.
- "Did you mean" for misspelled **flags**. Click already does a decent job at flag-suggestion; we only wrap the subcommand surface.
- Auto-install via `--install-completion`. Decided in the spec Q1 resolution — the CLI never writes to user shell config without explicit opt-in. Future enhancement only if requested.

## Invariants Enforced in This Phase

- **INV-P001** Privacy default — extended with a `completion` no-egress case.
- **AC7 (cold-start)** — perf test pins the budget.
- **AC8 ("did you mean")** — explicit test covers the suggestion engine.

---

## TDD Steps

### Step 7.1 — RED

`tests/integration/test_cli_completion.py` (CREATE):

1. `test_completion_bash_emits_script_to_stdout` — invoke `genomeclaw completion bash`; assert exit 0; assert stdout starts with a bash-completion-script marker.
2. `test_completion_zsh_emits_script_to_stdout` — same for zsh.
3. `test_completion_fish_emits_script_to_stdout` — same for fish.
4. `test_completion_unknown_shell_errors` — `genomeclaw completion ksh` → exit 2 (usage error).

`tests/integration/test_cli_suggest.py` (CREATE):

5. `test_suggest_closest_finds_single_match` — `suggest_closest("doctr", ["doctor", "version"])` → `["doctor"]`.
6. `test_suggest_closest_ignores_distant_candidates` — `suggest_closest("xyz", ["doctor", "fetch"])` → `[]`.
7. `test_suggest_closest_handles_empty_candidates` — `suggest_closest("doctor", [])` → `[]`.
8. `test_suggest_closest_returns_sorted_by_distance` — multiple within threshold → sorted closest first.

`tests/integration/test_cli_did_you_mean.py` (CREATE):

9. `test_did_you_mean_subcommand_misspelling` — `genomeclaw doctr` → exit 2; error envelope's `suggested_actions` includes "Did you mean: doctor" (or `host doctor`).
10. `test_did_you_mean_no_suggestion_when_too_far` — `genomeclaw xyzzy` → exit 2; no "Did you mean" hint (too far for any candidate).
11. `test_did_you_mean_json_mode_carries_suggestions_in_envelope` — `--json genomeclaw doctr` → exit 2; JSON envelope's `error.suggested_actions` includes the hint.

`tests/perf/test_cli_cold_start.py` (CREATE):

12. `test_genomeclaw_help_cold_start_under_one_second` — subprocess `uv run genomeclaw --help`; assert wall time < 1.0 s.

Privacy:

13. `tests/privacy/test_invP001_cli_no_egress.py` — extend with `test_invP001_no_egress_during_completion_bash`.

### Step 7.2 — GREEN

**New source files**:

- `src/genomeclaw_toolkit/_cli/suggest.py` — `suggest_closest()` helper using `difflib.get_close_matches` (already in the stdlib; equivalent to Damerau-Levenshtein for typical typo distances and zero new deps).
- `src/genomeclaw_toolkit/_cli/commands/completion.py` — Typer command that calls `click.shell_completion.shell_complete` (or equivalent) to print the per-shell script.

**Modified source files**:

- `src/genomeclaw_toolkit/_cli/__init__.py` — wrap the `click.UsageError` branch in `main()` to detect "No such command" messages, enumerate registered commands, and rewrite `suggested_actions` with the "Did you mean: …" hints.
- `src/genomeclaw_toolkit/_cli/commands/__init__.py` — import the new completion submodule for its side-effect `app.add_typer(...)` registration.

### Step 7.3 — REFACTOR

- Move the registered-commands enumeration into a single helper so both the JSON-mode and rich-mode paths render the same suggestions.
- Confirm Google-style docstrings everywhere.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/genomeclaw_toolkit/_cli/suggest.py` | CREATE | `suggest_closest()` Damerau-Levenshtein helper |
| `src/genomeclaw_toolkit/_cli/commands/completion.py` | CREATE | `completion <shell>` Typer command |
| `src/genomeclaw_toolkit/_cli/__init__.py` | MODIFY | Wire "Did you mean" into the usage-error handler; register completion subapp |
| `tests/integration/test_cli_completion.py` | CREATE | 4 completion tests |
| `tests/integration/test_cli_suggest.py` | CREATE | 4 helper unit tests |
| `tests/integration/test_cli_did_you_mean.py` | CREATE | 3 end-to-end "did you mean" tests |
| `tests/perf/test_cli_cold_start.py` | CREATE | 1 cold-start budget test |
| `tests/privacy/test_invP001_cli_no_egress.py` | MODIFY | 1 new no-egress case for completion |

---

## Verification

```bash
cd packages/toolkit

# Phase's tests
uv run pytest tests/integration/test_cli_completion.py \
              tests/integration/test_cli_suggest.py \
              tests/integration/test_cli_did_you_mean.py \
              tests/perf/test_cli_cold_start.py \
              tests/privacy/test_invP001_cli_no_egress.py -v

# Full suite
uv run pytest -q

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli

# Smoke
uv run genomeclaw completion bash | head -5    # bash completion script
uv run genomeclaw doctr                         # typo → "Did you mean ..." hint
uv run genomeclaw xyzzy                         # no close candidate → no hint
time uv run genomeclaw --help > /dev/null       # cold-start under 1.0 s
```

---

## Completion Criteria

- [x] All listed tests pass (4 suggest + 2 completion + 3 did-you-mean + 1 perf + 1 privacy = 11 net; **388 passed, 61 skipped** — +13 over Phase 6).
- [x] Static checks pass: `ruff check` + `ruff format --check` + `mypy --strict` on `_cli/`.
- [x] `genomeclaw completion bash` emits a working shell-completion script to stdout (real-CLI smoke confirmed; starts with `_genomeclaw_completion()` bash function definition).
- [x] `genomeclaw doctr` exits with code 2 and surfaces `Did you mean: host doctor?` (real-CLI smoke confirmed).
- [x] `genomeclaw --help` cold start: **0.24s** wall-time on the project owner's host (well under the 1.0s budget).
- [x] Each enforced `INV-xxx` verified: INV-P001 covered by `test_invP001_no_egress_during_completion_bash`.
- [x] No raw genomic data committed.
- [x] `work-notes.md` updated.
- [x] Phase status updated in `development-plan.md` (Phase 7 → Complete).
- [ ] `phases/phase-8.md` drafted — covered by the existing development-plan narrative (`§ Phase 8`); standalone file will be authored at start of Phase 8 work (per planning protocol).

## Latent-bug carry-out from Phase 7

Wiring "Did you mean" exposed two correctness bugs in the error path:

1. **`_is_json_mode()` / `_is_debug_mode()` read `sys.argv`** even when the CLI was invoked via `main(argv=[...])` — broke JSON-mode error rendering in tests. Fixed by threading `effective_argv = argv or sys.argv[1:]` through every error-path helper.

2. **Trailing error envelopes double-emitted to stdout** in JSON mode when a command had already written a payload or stream envelope. Production behavior was: stream + final error envelope both on stdout → broke downstream JSON parsers. Documented contract was "error envelope goes to stderr when a stream is active" — newly enforced via the `stdout_already_consumed` module sentinel in `_cli.output`. Helpers that write to JSON-mode stdout (`emit()`, `_begin_ndjson_stream()` in pipeline/refs, `_emit_host_setup_envelope()`, `_emit_release_sets()`) all call `mark_stdout_consumed()`. The exception boundary checks the sentinel before routing the error envelope. Reset at every `main()` entry to keep per-invocation isolation under the test-fixture's repeated in-process invocations.

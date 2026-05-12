# Phase 4: `refs fetch` rich UX

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-3.md](phase-3.md) — fetcher correctness shipped; `ProgressEvent` dataclass hierarchy public in `prep/_events.py`; `progress_callback` hook plumbed through `prep/fetch.py` (already invoked with `FileStart` / `FileProgress` / `FileComplete` events).
**Successor**: [phase-5.md](phase-5.md) — pipeline-stage UX + per-orchestrator callbacks + graduate-as-you-go strict typing.

---

## Objective

Replace the thin Phase-1 `refs fetch` wrapper with the full rich-progress UX, consuming the `progress_callback` hook that Phase 3 already plumbed through the fetcher. One rich `Progress` panel per file + an overall bar under `--all`; NDJSON file events one-per-line under `--json`.

The user value: the next time you (or anyone) re-fetches one of the 5 truncated gnomAD files, the operation is observable — bytes downloaded, ETA, throughput, success/failure surfaced at the same level of detail as the underlying integrity checks.

**Why this is its own phase**: small (~5 tests), self-contained (no orchestrator changes), high immediate user value (you'll exercise it as soon as you re-fetch the truncated files). Splitting it from the larger pipeline UX work in Phase 5 keeps both diffs reviewable.

## Scope Boundaries

**In scope**:

- `_cli/commands/refs.py` — `refs fetch` command body fleshed out: construct an `AppContext`-aware callback that either drives a rich `Progress` or writes NDJSON to stdout, depending on `output_mode`.
- `_cli/renderers/refs.py` extended with:
  - `make_fetch_rich_renderer(progress: Progress) -> Callable[[ProgressEvent], None]` — translates `FileStart`/`FileProgress`/`FileComplete`/`FileFailed` into `progress.add_task` / `progress.update` / `progress.remove_task` calls.
  - `make_fetch_ndjson_emitter(sink: TextIO) -> Callable[[ProgressEvent], None]` — writes one JSON object per line to `sink` (stdout in `--json` mode).
- NDJSON envelope convention: **first line** is the schema-version envelope `{"cli_output_schema_version": "1.0", "command": "refs.fetch", "stream": true}`; **subsequent lines** are raw events `{"event": "file_start", ...}`. Pinned in `cli-output-schemas.md § events.*`.
- `--all` mode: when fetching multiple sources, add an overall progress bar that increments once per file complete.
- Tests: `tests/integration/test_cli_refs_fetch.py` (~5 tests).
- Privacy-default: extend `test_invP001_cli_no_egress.py` with one `refs fetch` case using the mock-server fixture (assert all egress targets the mock URL, none anywhere else).
- `cli-output-schemas.md § events.*` updated with the confirmed wire shape (event lines + first-line envelope).

**Out of scope** (deferred):

- Pipeline-stage UX (`pipeline run` panels + per-orchestrator callbacks) — **Phase 5**.
- Strict-typing graduation of `prep/` orchestrator modules — **Phase 5** (graduate-as-you-go).
- Destructive commands — Phase 6.
- Polish / tab completion / "did you mean" — Phase 7.

## Invariants Enforced in This Phase

- **INV-P001** Privacy default — `refs fetch` is the one command in this phase that makes outbound HTTP. The mock-server fixture asserts every egress targets the configured URL.
- **Provisional `INV-C-cli-output-stability`** — NDJSON output validates against the documented event schema; first-line envelope present; one event per line; `\n` is never embedded inside an event payload.

---

## TDD Steps

### Step 4.1 — RED

`tests/integration/test_cli_refs_fetch.py`:

1. `test_refs_fetch_rich_renders_progress_panel` — rich mode against a synthetic source; capture the `Console(record=True)` output; assert a Progress-style render block exists with the file name + percentage.
2. `test_refs_fetch_json_emits_ndjson_event_stream` — `--json` mode against a synthetic source; assert stdout parses as NDJSON (first line is envelope, subsequent lines are events); at least one `file_start` + one `file_complete` event; `cli_output_schema_version` on the envelope line.
3. `test_refs_fetch_json_emits_file_failed_on_integrity_error` — synthetic source returning truncated bytes; assert a `file_failed` event with `reason: "incomplete_bgzip"` + a final exit code of 4.
4. `test_refs_fetch_all_renders_overall_bar` — `--all` mode covering two sources; rich output mentions both source names + the overall counter advances `1/N`, `2/N`.
5. `test_invP001_refs_fetch_only_egresses_to_configured_url` — privacy-default with mock-server fixture; assert every HTTP call targets the mock URL.

### Step 4.2 — GREEN

Minimal implementation:

1. Add `make_fetch_ndjson_emitter` + `make_fetch_rich_renderer` to `_cli/renderers/refs.py`.
2. Rewrite `_cli/commands/refs.py:fetch` body: construct the callback based on `ctx.output_mode`, pass it as `progress_callback=` to `prep.fetch.fetch()`.
3. In JSON mode, emit the first-line envelope before delegating to the fetcher.

### Step 4.3 — REFACTOR

- Extract a `_drive_rich_progress` helper into `_cli/renderers/_progress.py` if the rich Progress wiring grows. **Hold for Phase 5** unless duplication is already real.
- Confirm Google-style docstrings on every public symbol in the new renderer functions.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/genomeclaw_toolkit/_cli/renderers/refs.py` | MODIFY | Add `make_fetch_rich_renderer` + `make_fetch_ndjson_emitter` |
| `src/genomeclaw_toolkit/_cli/commands/refs.py` | MODIFY | Replace thin-wrapper `refs fetch` body with progress-driven impl |
| `docs/reference/cli-output-schemas.md` | MODIFY | Pin event-stream wire shape with worked `refs.fetch` example |
| `tests/integration/test_cli_refs_fetch.py` | CREATE | 5 rich + JSON + event-stream tests |
| `tests/privacy/test_invP001_cli_no_egress.py` | MODIFY | One new case for `refs fetch` (mock-server fixture) |

---

## Verification

```bash
cd packages/toolkit

# Phase's tests
uv run pytest tests/integration/test_cli_refs_fetch.py \
              tests/privacy/test_invP001_cli_no_egress.py -v

# Full suite
uv run pytest -q

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli

# Real-layout smoke — re-fetch one of the truncated gnomAD chrom files
# This exercises the Phase-3 fetcher correctness + Phase-4 UX in one shot.
uv run genomeclaw refs fetch --source gnomad-exomes --release v4.1 --chrom chr6
uv run genomeclaw --json refs fetch --source clinvar --release 2026-05-09 > events.ndjson
head -1 events.ndjson | jq .  # envelope line
tail -n +2 events.ndjson | jq -c '.event' | sort -u  # event-type histogram
```

---

## Completion Criteria

- [x] All 5 listed tests pass (346 / 0 / 61 skipped — +5 over Phase 3).
- [x] Static checks pass: `ruff check` + `ruff format --check` + `mypy --strict` on `_cli/`.
- [x] `refs fetch --json` smoke against the real `/Volumes/Genome_Work/genomeclaw/reference/` layout emits the documented envelope-first NDJSON shape (`{"cli_output_schema_version":"1.0","command":"refs.fetch","stream":true}` as line 1, structured error envelope as line 2 on the precondition path) with exit code 3.
- [x] `refs fetch` (rich mode) renders an inline `rich.progress.Progress` panel driven by the fetcher's `progress_callback` events.
- [ ] **Re-fetching the 5 truncated gnomAD files**: deferred — re-fetching ~30 GB of gnomAD over the live network is the user's call, not a smoke test. The wire path is fully exercised by the test suite via `pytest-httpserver`; the user can now run `genomeclaw refs fetch --source gnomad-exomes --release v4.1 --chroms 6,7,9,10,11` whenever they're ready and watch the progress live.
- [x] `docs/reference/cli-output-schemas.md` event-stream section pins the wire shape with `refs.fetch` worked examples (happy path + failure path).
- [x] Each enforced `INV-xxx` is verified by at least one test in this phase (INV-P001 covered by `test_invP001_refs_fetch_only_egresses_to_configured_url`).
- [x] No raw genomic data committed; fixtures use synthetic `BGZF_EOF_MARKER`-tailed bytes.
- [x] `work-notes.md` updated.
- [x] Phase status updated in `development-plan.md` (Phase 4 → Complete).
- [x] `phases/phase-5.md` already drafted (was drafted alongside this Phase-4 split).

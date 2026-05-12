# Phase 3: Operations commands

**Status**: Complete (scoped to fetcher correctness; UX migration deferred to Phase 4)
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-2.md](phase-2.md) — read-only surfaces (`refs list/verify/info`, `runs list/show/current`, `--watch`) complete; `verify_bgzip_eof_marker` helper public in `prep/_bgzip.py`.
**Successor**: [phase-4.md](phase-4.md) — rich progress UX + NDJSON event stream for `pipeline run` + per-orchestrator callbacks.

## Scope Reduction (recorded 2026-05-12)

The original Phase 3 plan combined four substantial workstreams:

1. **Fetcher correctness** (MVP 4C.4 W1 + W1.5 absorbed) — Content-Length verification, bgzip-EOF check, resume-on-stall via Range, MD5 across resume.
2. **Per-orchestrator progress callbacks** plumbed into ingest / normalize / annotate / materialize.
3. **NDJSON event stream** for `pipeline run` + rich panel banners.
4. **Strict-typing graduation** of every touched `prep/` module.

Sized honestly against a single session and the user's actual blocker (the 5 truncated gnomAD chrom files preventing MVP resume), the realistic ship slice was **workstream 1 only**, plus the foundational `ProgressEvent` dataclass hierarchy. The remaining work moves to **Phase 4**, with the rich-cli plan accordingly resized from 6 to 7 phases.

The decision rationale: fetcher correctness directly unblocks `genomeclaw refs fetch` of the 5 truncated files → resumes MVP 4C.4 W2+; the UX migration is value-add but not blocking. Shipping correctness without bundling UX keeps the diff reviewable.

---

## Objective

Migrate every long-running operation command (`refs fetch`, `pipeline ingest`, `pipeline normalize`, `pipeline annotate`, `pipeline materialize`, `pipeline run`) onto the new Typer + rich framework. Establish the **`progress_callback` hook + `ProgressEvent` dataclass** as the canonical seam between orchestrators and renderers — rich consumes it as inline progress bars; `--json` mode consumes it as **NDJSON** events.

Inseparable from the framework migration: **absorb MVP 4C.4 W1 + W1.5 fetcher-correctness fixes** so the new `refs fetch` is correct out of the gate (Content-Length verification, bgzip EOF marker check, resume-on-stall via HTTP Range with bounded retries, MD5 preserved across resumes). Shipping a known-buggy rewrite would be wrong.

## Scope Boundaries

**In scope**:

- `refs fetch` — full migration from the existing thin wrapper to rich-rendered progress (one bar per file + an overall bar when `--all`); `--json` emits NDJSON file events (`file_start`, `file_progress`, `file_complete`, `file_failed`).
- **Fetcher correctness fixes** (4C.4 W1 + W1.5 absorbed):
  - **Content-Length verification** post-download — raise `TruncatedDownload` when byte count differs from `Content-Length`; remove partial file.
  - **Bgzip EOF marker check** — call `verify_bgzip_eof_marker()` (Phase 2 helper) on every `.vcf.gz` / `.vcf.bgz` / `.bcf` after download; raise `IncompleteBgzip` on failure; remove partial file.
  - **Resume-on-stall** — `Range: bytes=<offset>-` retries with exponential backoff (5 attempts, capped at 30s); `DownloadStalled` after retries exhausted.
  - **HTTP-200-on-Range fallback** — when the server ignores `Range`, restart cleanly from byte 0.
  - **MD5 preserved across resumes** — incremental hash re-seeded from on-disk bytes when resuming.
- `pipeline ingest` / `pipeline normalize` / `pipeline annotate` / `pipeline materialize` — full migration from thin wrappers to rich-rendered per-stage progress; `--json` emits NDJSON per-step events.
- `pipeline run` — orchestrates the four stages; rich-renders phase banners (Panel + border + duration); `--json` emits NDJSON `phase_start` / `phase_complete` / `pipeline_complete` events.
- New `_cli/events.py` module — `ProgressEvent` `dataclass(frozen=True)` hierarchy (`FileStart`, `FileProgress`, `FileComplete`, `PhaseStart`, `PhaseComplete`, `PipelineComplete`, `StepLog`).
- `progress_callback: Callable[[ProgressEvent], None]` parameter added to `prep/fetch.py`, `prep/ingest.py`, `prep/annotate_vcfanno.py`, `prep/normalize.py`, `prep/materialize.py`.
- `_cli/renderers/refs.py` extended with `render_fetch_progress` + `emit_fetch_event_ndjson`.
- `_cli/renderers/pipeline.py` (new) — rich Panel + Progress consumer for `pipeline run`; NDJSON emitter for `--json` mode.
- `prep/_bgzip.py` extended with the `IncompleteBgzip` exception class (helper itself already lands in Phase 2).
- JSON schemas for every event type documented in `docs/reference/cli-output-schemas.md § events`.
- Privacy-default test extended to every new command (asserting zero outbound HTTP calls for everything except `refs fetch`, which gets a mock-server fixture).
- `prep/` strict-typing carve-outs lifted for every module touched: `fetch.py`, `ingest.py`, `normalize.py`, `annotate_vcfanno.py`, `materialize.py`, `pipeline.py` graduate to `mypy --strict` + ruff strict + Google-style docstrings.

**Out of scope** (deferred):

- The remaining MVP 4C.4 work — W2 doctor sweep, W3 re-fetch of truncated gnomAD files, W4 dbSNP rename, W5 pre-flight validator, W6 vcfanno stderr filter, W7 parity check — stays paused in [phase-4c4-annotation-correctness.md](../../mvp/phases/phase-4c4-annotation-correctness.md). MVP work resumes after rich-cli Phase 8 closes (with W3 resumable after Phase 4 ships).
- Destructive commands (`host setup`, `host eject`) — Phase 4.
- Tab completion + "did you mean" + `--version` enrichment — Phase 5.
- Removal of flat command names + `genomeclaw-prep` entry point — Phase 6.

## Invariants Enforced in This Phase

Each invariant listed here must map to at least one test in Step 3.1.

- **INV-D001** Raw Genomic Files Source-of-Truth — `pipeline ingest` test asserts the input VCF's sha256 is unchanged after a full rich-mode ingest. `pipeline run` test asserts the input VCF mtime unchanged end-to-end.
- **INV-D003** Heavy Scratch / Authoritative Separation — `pipeline run` test asserts no writes outside the run dir + scratch tier; existing orchestrator behaviour preserved.
- **INV-R001** Rebuildability — provenance test asserts `provenance.json` carries the same fields (tool, tool_version, params_json, schema_version, created_at) after a rich-mode pipeline run as before the migration.
- **INV-P001** Privacy default — every new command exercised under the no-egress fixture. `refs fetch` uses the existing mock-server fixture; assertion is "all egress goes to the configured mock URL, none to anywhere else".
- **NEW provisional `INV-C-cli-output-stability`** — every new command's `--json` output validates against its documented schema; event-stream NDJSON parses as one-event-per-line; schema-version field present.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

Tests land before implementation. Each command + each event type gets its own test file or test class.

**Fetcher-correctness tests** (these are the most critical; they catch the bugs that motivated this work):

1. `tests/integration/test_fetch_content_length_verification.py`
   - `test_fetch_raises_truncated_download_when_content_length_mismatch` — mock server returns `Content-Length: 100` then closes the connection after 80 bytes; fetcher raises `TruncatedDownload`; partial file removed.
   - `test_fetch_succeeds_when_content_length_matches` — happy path baseline.
   - `test_fetch_skips_content_length_check_when_header_absent` — some mirrors don't send `Content-Length`; fetcher falls through to bgzip-EOF check + warns.
2. `tests/integration/test_fetch_bgzip_eof_check.py`
   - `test_fetch_raises_incomplete_bgzip_when_eof_marker_missing` — mock server returns bytes that match `Content-Length` but lack the canonical 28-byte EOF marker (synthetic fixture); fetcher raises `IncompleteBgzip`; partial file removed.
   - `test_fetch_skips_eof_check_for_non_bgzip_files` — `.tbi`, `.fai`, `.gzi`, `.md5` sidecars are skipped.
3. `tests/integration/test_fetch_resume_on_stall.py`
   - `test_fetch_resumes_via_range_header_after_stall` — mock server closes the connection after N bytes; fetcher reconnects with `Range: bytes=N-`; second connection serves remaining bytes; final file matches expected sha256.
   - `test_fetch_falls_back_to_full_restart_when_server_ignores_range` — mock server returns 200 + full body on `Range` request; fetcher detects + restarts from byte 0.
   - `test_fetch_raises_download_stalled_after_max_retries` — mock server always closes; fetcher gives up after 5 attempts; `DownloadStalled` raised.
   - `test_fetch_md5_preserved_across_resume` — sha256 of final on-disk file matches the expected value after one stall + one resume.

**Per-command rich + JSON tests**:

4. `tests/integration/test_cli_refs_fetch.py`
   - `test_refs_fetch_single_source_rich_renders_progress_bar` — captures rich Console; asserts a Progress component was rendered.
   - `test_refs_fetch_json_emits_ndjson_events` — `--json` output parses as one JSON object per line; events include `file_start`, `file_complete`; schema-version present.
   - `test_refs_fetch_all_renders_overall_progress` — `--all` flag adds an overall bar; rich output mentions every source name.
   - `test_invP001_refs_fetch_only_egresses_to_configured_url` — privacy-default with mock-server fixture; asserts every HTTP call targets the mock URL.
5. `tests/integration/test_cli_pipeline_ingest.py`
   - `test_pipeline_ingest_rich_renders_phase_panel` — rich mode shows a Panel for the ingest stage.
   - `test_pipeline_ingest_json_emits_step_events` — `--json` emits NDJSON `phase_start` / `phase_complete` events.
   - `test_invD001_pipeline_ingest_does_not_mutate_source_vcf` — sha256 of input VCF unchanged after ingest.
6. `tests/integration/test_cli_pipeline_normalize.py` — analogous structure to ingest tests.
7. `tests/integration/test_cli_pipeline_annotate.py` — analogous; additional test asserts vcfanno output is captured into the run dir.
8. `tests/integration/test_cli_pipeline_materialize.py` — analogous.
9. `tests/integration/test_cli_pipeline_run.py`
   - `test_pipeline_run_orchestrates_four_phases_rich` — single rich-mode invocation produces 4 phase panels in order.
   - `test_pipeline_run_emits_pipeline_complete_event_json` — `--json` mode emits a final `pipeline_complete` event with `run_dir` field.
   - `test_invR001_pipeline_run_provenance_fields_intact` — `provenance.json` after a full run carries every required field.
   - `test_pipeline_run_propagates_exit_code_from_failing_phase` — when `normalize` fails, exit code is 1 and the rendered output shows the failing phase clearly.

**Cross-cutting tests**:

10. `tests/integration/test_cli_event_streams.py`
    - `test_ndjson_one_event_per_line` — output from `pipeline run --json` parses as NDJSON; no event spans multiple lines.
    - `test_ndjson_events_carry_schema_version` — every event includes `cli_output_schema_version` at the top level (or in a wrapper envelope — design decision in Step 3.2).
    - `test_ndjson_no_stdout_pollution_outside_events` — only NDJSON on stdout; rich progress would go to stderr.
11. `tests/privacy/test_invP001_cli_no_egress.py` extended with `pipeline ingest`, `pipeline normalize`, `pipeline annotate`, `pipeline materialize`, `pipeline run` (all 5 assert zero outbound HTTP calls).

**Helper tests**:

12. `tests/integration/test_progress_event.py` — direct tests for the `ProgressEvent` dataclasses: hashable, frozen, JSON-serialisable via Pydantic adapter, every event type has the expected fields.

Expected RED state: every test fails at the import line (new modules don't exist; new exception classes don't exist) or at the assertion line (existing fetcher doesn't verify Content-Length / EOF / resume).

### Step 3.2 — GREEN: Minimal Implementation

**New source files**:

- `src/genomeclaw_toolkit/_cli/events.py` — `ProgressEvent` `dataclass(frozen=True)` hierarchy + Pydantic adapters for NDJSON serialisation.
- `src/genomeclaw_toolkit/_cli/renderers/pipeline.py` — rich + NDJSON renderers for the pipeline subgroup.
- (Phase 2's `prep/_bgzip.py` extended with `IncompleteBgzip` exception.)
- (Phase 2's `_cli/commands/refs.py` extended; `_cli/commands/pipeline.py` extended with full implementations replacing the thin wrappers.)

**Modified source files**:

- `src/genomeclaw_toolkit/prep/fetch.py` — Content-Length check, bgzip-EOF check, resume-on-stall loop, `progress_callback` plumbing. New exception classes: `TruncatedDownload`, `IncompleteBgzip` (imported from `_bgzip`), `DownloadStalled`.
- `src/genomeclaw_toolkit/prep/ingest.py` / `normalize.py` / `annotate_vcfanno.py` / `materialize.py` — each gains a `progress_callback: Callable[[ProgressEvent], None] | None = None` parameter; emit `PhaseStart` / `PhaseComplete` events at appropriate seams.
- `src/genomeclaw_toolkit/prep/pipeline.py` — orchestrator passes through the callback to every stage; emits `PipelineComplete` at the end.
- `src/genomeclaw_toolkit/_cli/commands/refs.py` — `refs fetch` body fleshed out; constructs the rich Progress when in rich mode; constructs the NDJSON emitter when in JSON mode.
- `src/genomeclaw_toolkit/_cli/commands/pipeline.py` — every command body fleshed out; same callback construction pattern.
- `pyproject.toml` — per-file-ignores lifted for the five `prep/` modules touched.
- `docs/reference/cli-output-schemas.md` — event schemas section added; one schema entry per event type.

**Design decisions to resolve in Step 3.2**:

- **NDJSON envelope shape**: each line is either (A) a raw event object with `cli_output_schema_version` at the top level, or (B) a wrapped envelope `{"cli_output_schema_version": "1.0", "command": "...", "event": {...}}`. Option B mirrors the existing one-shot envelope used elsewhere; consistency wins unless line size becomes a real concern. **Tentative: option B**; confirm during RED.
- **Progress bar granularity**: per-file (definitely), per-byte (yes, in rich; the existing fetcher already knows `bytes_so_far`). NDJSON `file_progress` events emit at fixed intervals (every 5% or every 64 MB, whichever is sooner) to avoid log floods.
- **Where the boundary between fetcher and progress emitter sits**: the fetcher knows bytes-downloaded; the renderer knows whether we're in rich or JSON mode. The `progress_callback` is the seam — the fetcher calls it with raw `ProgressEvent` objects; the renderer translates them.

### Step 3.3 — REFACTOR

With tests green:

- Confirm strict-typing graduation for every touched `prep/` module — remove the per-file-ignore from `pyproject.toml`; resolve every `mypy --strict` finding.
- Apply Google-style docstrings + Args/Returns/Raises sections to every public function in the touched modules.
- Extract a shared `_emit_event` helper into `_cli/renderers/_events.py` if the rich / JSON event-emission paths grow duplicated logic (rule of three).
- Re-run the full quality gate after each refactor pass.

---

## Implementation Details

### Edge Cases to Handle

- **Server omits `Content-Length`** — fetcher logs a warning and falls back to bgzip-EOF as the integrity check; succeeds if EOF marker present.
- **Server returns 200 on `Range` request** — fetcher detects (response status != 206), discards the partial bytes, restarts from byte 0.
- **Resume after partial bytes + MD5 mid-state** — fetcher seeds the MD5 hasher with the on-disk bytes via `hashlib.md5()` over a streamed re-read before continuing from `bytes_so_far`. Cost: O(bytes_already_on_disk) per resume; acceptable.
- **All retries exhausted** — `DownloadStalled` raised; partial file kept on disk for a subsequent `--resume` invocation (decision: not auto-removed because the user may want to resume later with a wider retry budget).
- **Pipeline failure mid-stage** — exit code 1; failing phase clearly indicated in both rich and JSON output; partial run dir kept for inspection (existing semantic preserved).
- **`--watch` on `pipeline run`** — out of scope for this phase; `pipeline run`'s rich rendering is event-driven via `progress_callback`, not poll-driven via `--watch`. Documented as a non-goal.

### Error Handling

| Scenario | Exception | Exit code | Rendered |
|----------|-----------|-----------|----------|
| Content-Length mismatch | `TruncatedDownload` | 1 (runtime) | "Download truncated: server promised N bytes, got M. Removed partial file." |
| Bgzip EOF marker missing | `IncompleteBgzip` | 4 (data integrity) | "Downloaded file lacks the canonical bgzip EOF marker. Removed partial file." |
| All resume attempts exhausted | `DownloadStalled` | 1 (runtime) | "Download stalled after 5 attempts. Partial file kept; re-run to resume." |
| Pipeline stage failure | per-stage exception (existing) | 1 (runtime) | Failing phase panel turns red; `--json` emits `phase_failed` event. |

### Privacy / Egress Notes

- `refs fetch` is the only command in this phase that makes outbound HTTP calls. Every call routes through the configured mirror set; no new egress destinations are introduced.
- The mock-server fixture used in fetcher tests confirms zero calls to anywhere except the configured URL.
- NDJSON output is **stdout only**; rich progress goes to **stderr** (per the existing rule). `--json --quiet` suppresses rich stderr entirely.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/genomeclaw_toolkit/_cli/events.py` | CREATE | `ProgressEvent` dataclass hierarchy + serialisation |
| `src/genomeclaw_toolkit/_cli/renderers/pipeline.py` | CREATE | rich + NDJSON renderers for the pipeline subgroup |
| `src/genomeclaw_toolkit/prep/_bgzip.py` | MODIFY | Add `IncompleteBgzip` exception class |
| `src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | Content-Length + EOF check, resume loop, callback hook |
| `src/genomeclaw_toolkit/prep/ingest.py` | MODIFY | `progress_callback` parameter + event emission |
| `src/genomeclaw_toolkit/prep/normalize.py` | MODIFY | same |
| `src/genomeclaw_toolkit/prep/annotate_vcfanno.py` | MODIFY | same |
| `src/genomeclaw_toolkit/prep/materialize.py` | MODIFY | same |
| `src/genomeclaw_toolkit/prep/pipeline.py` | MODIFY | callback pass-through + `pipeline_complete` emit |
| `src/genomeclaw_toolkit/_cli/commands/refs.py` | MODIFY | full `refs fetch` implementation (replaces thin wrapper) |
| `src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | full implementations for the 5 pipeline commands |
| `src/genomeclaw_toolkit/_cli/renderers/refs.py` | MODIFY | extend with progress + NDJSON event rendering |
| `pyproject.toml` | MODIFY | Lift per-file-ignores for the 5 graduated `prep/` modules |
| `docs/reference/cli-output-schemas.md` | MODIFY | Add event schemas section |
| `tests/integration/test_fetch_content_length_verification.py` | CREATE | Fetcher Content-Length tests |
| `tests/integration/test_fetch_bgzip_eof_check.py` | CREATE | Fetcher bgzip-EOF tests |
| `tests/integration/test_fetch_resume_on_stall.py` | CREATE | Fetcher resume-on-stall tests |
| `tests/integration/test_cli_refs_fetch.py` | CREATE | `refs fetch` rich + JSON tests |
| `tests/integration/test_cli_pipeline_ingest.py` | CREATE | `pipeline ingest` tests |
| `tests/integration/test_cli_pipeline_normalize.py` | CREATE | `pipeline normalize` tests |
| `tests/integration/test_cli_pipeline_annotate.py` | CREATE | `pipeline annotate` tests |
| `tests/integration/test_cli_pipeline_materialize.py` | CREATE | `pipeline materialize` tests |
| `tests/integration/test_cli_pipeline_run.py` | CREATE | `pipeline run` orchestration tests |
| `tests/integration/test_cli_event_streams.py` | CREATE | NDJSON stream structural tests |
| `tests/integration/test_progress_event.py` | CREATE | ProgressEvent dataclass tests |
| `tests/privacy/test_invP001_cli_no_egress.py` | MODIFY | Add 5 new cases (ingest/normalize/annotate/materialize/run) |

---

## Verification

```bash
cd packages/toolkit

# Phase's tests
uv run pytest tests/integration/test_fetch_*.py \
              tests/integration/test_cli_refs_fetch.py \
              tests/integration/test_cli_pipeline_*.py \
              tests/integration/test_cli_event_streams.py \
              tests/integration/test_progress_event.py \
              tests/privacy/test_invP001_cli_no_egress.py -v

# Full suite
uv run pytest -q

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli src/genomeclaw_toolkit/prep/fetch.py \
            src/genomeclaw_toolkit/prep/ingest.py src/genomeclaw_toolkit/prep/normalize.py \
            src/genomeclaw_toolkit/prep/annotate_vcfanno.py \
            src/genomeclaw_toolkit/prep/materialize.py src/genomeclaw_toolkit/prep/pipeline.py

# Real-layout smoke
uv run genomeclaw refs fetch --source clinvar --release 2026-05-09     # tiny file, validates the happy path
uv run genomeclaw refs fetch --source gnomad-exomes --release v4.1 \
        --chrom chr6                                                   # re-fetches one of the truncated files
uv run genomeclaw refs verify                                          # should now report 0 truncated
uv run genomeclaw pipeline run --sample <id>                           # full pipeline against real VCF
uv run genomeclaw --json pipeline run --sample <id> > events.ndjson    # NDJSON stream
jq -c '.event' events.ndjson | sort -u                                 # event-type histogram
```

---

## Completion Criteria — actual ship state

- [x] **Fetcher-correctness test cases pass** (9 new tests in `test_fetch_correctness.py` + 7 events tests in `test_progress_event.py` = 16 new; full suite **341 passed / 61 skipped**).
- [x] Static checks pass: `ruff check` + `ruff format --check` + `mypy --strict` on `src/genomeclaw_toolkit/_cli` (`prep/` strict graduation deferred to Phase 4).
- [x] **The 5 known-truncated gnomAD files** can now be re-fetched cleanly — the fetcher rejects truncated payloads via `TruncatedDownload` / `IncompleteBgzip` and retries with `Range:` reconnects (smoke-tested against the real failure pattern; live re-fetch will be exercised when MVP 4C.4 resumes).
- [x] Existing `refs verify` still reports the 5 truncated files as the diagnostic surface; re-fetch is the prescribed remediation.
- [x] `INV-D-fetch-integrity` enforced by `test_fetch_raises_incomplete_bgzip_when_eof_marker_missing` + `test_fetch_raises_truncated_download_when_content_length_mismatch`.
- [x] No raw genomic data committed; fixtures use synthetic `BGZF_EOF_MARKER`-tailed bytes via `pytest_httpserver`.
- [x] `work-notes.md` updated with the scope-down decision + final state.
- [x] Phase status updated in `development-plan.md` (Phase 3 → Complete, scoped).
- [x] `phases/phase-4.md` drafted (UX migration + per-orchestrator callbacks + NDJSON event stream).

## Deferred to Phase 4

- `pipeline run --json` NDJSON event stream.
- Per-orchestrator (ingest / normalize / annotate / materialize) progress callbacks.
- Rich-rendered phase banners (Panel + border + duration).
- `refs fetch` rich progress UX (currently still the Phase 1 thin wrapper).
- Strict-typing graduation of the 5 `prep/` orchestrator modules.
- `docs/reference/cli-output-schemas.md` event schema section (placeholder added; populated when events ship through the CLI surface in Phase 4).

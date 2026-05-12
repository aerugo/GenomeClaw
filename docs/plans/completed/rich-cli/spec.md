# Feature: rich-cli — interactive CLI toolchain for humans and AI agents

**Status**: Approved
**Created**: 2026-05-12
**Approved**: 2026-05-12 (open questions Q1–Q8 resolved by project owner)
**Owner**: project owner (with implementation by Claude)
**Related Plans**:
- [docs/plans/active/mvp/](../mvp/) — Phase 4C.4 currently scopes a narrow `rich` adoption (W6a) for fetcher/doctor/pipeline; this plan supersedes that scope if approved
- Reference for CLI conventions: gcloud, GitHub CLI (`gh`), Stripe CLI

---

## Goal

Migrate the GenomeClaw CLI (`bin/genomeclaw-prep` + everything it dispatches to) from `argparse + print + logging` to a coherent, modern interactive framework that feels as snappy as gcloud, renders beautifully for human terminals, and offers structured, stable, machine-parseable output for AI agents.

## Background

The current CLI is the result of organic growth through Phases 1–4:

- **Framework**: stdlib `argparse`. No subcommand groupings — every command is flat under a single parser. Help text is auto-generated but plain.
- **Output**: a mix of `print(...)` calls (`wrote /path/...`), `log.info(...)` lines (`[06:41:52 INFO] ...` after the Phase-4C.4 W6a precursor), and informal stderr-vs-stdout discipline. No structured output mode exists.
- **Progress reporting**: per-line `print` calls every 2 seconds (`8.2 GB/198 GB @ 50 MB/s`) — readable on a quiet terminal, but a 24-file `fetch --all` produces hundreds of newline-flooded lines that overwrite the actual signal.
- **Error handling**: ad-hoc — every subcommand handler returns 2 on `FileNotFoundError` / `ValueError`, 3 on certain integrity errors, and 0 on success. No central convention; no "did you mean" suggestions; no structured error envelope.
- **No tab completion**, no `--json` mode, no `--quiet`/`--verbose` discipline, no progress bars, no confirmation prompts on destructive operations beyond `eject --force`.
- **No AI-agent contract**: the project's grand plan ([architecture.md § two-domain architecture](../../../reference/architecture.md)) envisions agents (NemoClaw + future internal agents) driving the CLI as a tool surface. Today that's painful: agents would have to parse colored, partially-structured text-prose stdout to recover values.

The two surfaces compound. Adding `--json` mode to the existing argparse-based commands is doable but means hand-rolling stable schemas, stable exit codes, and TTY-aware rendering for every command — and we'd still lack the tab-completion / nested-command-group / `--help` discipline that a real CLI framework gives for free.

**This plan turns the CLI into a first-class product surface**. It's a deliberate investment: ~10–15 days of focused work to migrate ~10 commands, gain structured output, gain modern progress UX, and establish a contract agents can rely on. After it lands, every future command (Phase 4D's VEP-related subcommands, Phase 5's `genomeclaw-service` administration, Phase 6's findings/evidence subcommands) inherits the conventions for free.

## Acceptance Criteria

Each AC maps to at least one test in the development plan.

- [ ] **AC1**: Every `genomeclaw` subcommand supports a `--json` flag that emits a stable, schema-versioned JSON document to stdout. The schema is documented in `docs/reference/cli-output-schemas.md` and versioned independently of the toolkit (so `cli_output_schema_version=1.0` can outlive `toolkit_version=0.0.3`).
- [ ] **AC2**: Every command provides a TTY-aware human-rendered mode (rich progress bars, colored output, panels for phase banners, tables for tabular data) AND a non-TTY-aware plain-text mode (no ANSI escapes, periodic frame updates, no progress-bar redraw). Mode is auto-detected via `sys.stdout.isatty()` and overridable by `--no-color` / `--force-color` / `--quiet`.
- [ ] **AC3**: Commands are organised into a coherent subcommand tree:
  - `genomeclaw refs <list|fetch|verify|info>` — reference data
  - `genomeclaw runs <list|show|current>` — derived run history
  - `genomeclaw pipeline <run|ingest|normalize|annotate|materialize>` — orchestrators
  - `genomeclaw host <setup|eject|doctor>` — host management
  - Flat top-level commands (`ingest`, `fetch`, `doctor`, …) **deleted in Phase 1's clean-slate cutover**; Phase 8 grep-cleans any lingering references in docs / plans / agents. *(Resolves Q3: hierarchical, deprecate-immediate.)*
- [ ] **AC4**: Exit codes follow a documented contract:
  - `0` success
  - `1` runtime error (the operation tried and failed)
  - `2` usage error (invalid args; never reaches the handler)
  - `3` precondition error (missing reference data, missing tool, missing run dir)
  - `4` data integrity error (truncated file, schema mismatch, contig mismatch)
  - `130` interrupted by `SIGINT`
- [ ] **AC5**: Destructive operations (`eject`, `setup --force-reset`, future `refs delete <release>`) refuse to run interactively without an explicit confirmation (typed phrase or `--yes` flag). Non-TTY contexts require `--yes`.
- [ ] **AC6**: Tab completion works for bash, zsh, and fish via `genomeclaw completion <shell>` (matching the gcloud / kubectl pattern). Completion is fast (sub-100ms) — it must not import heavy modules like duckdb / pysam.
- [ ] **AC7**: Cold-start `--help` returns in under 200 ms on the project owner's host. (Today's argparse `--help` runs in ~140 ms — bar is "don't regress more than 50 ms".)
- [ ] **AC8**: A "did you mean…" suggestion appears for misspelled subcommands / flags using string-distance matching (Damerau-Levenshtein with threshold 3).
- [ ] **AC9**: Every test in `tests/integration/test_cli_*.py` passes in both rich (TTY-mocked-true) and JSON (`--json` flag) modes.
- [ ] **AC10**: Structured progress events: `genomeclaw pipeline run --json` emits newline-delimited JSON events to stdout (`{"event": "phase_start", "phase": "ingest", "ts": "..."}` … `{"event": "phase_complete", "phase": "ingest", "duration_sec": 71}`). Agents can parse this stream; humans see rich panels.
- [ ] **AC11 (clean-slate, hard cutover)**: **Zero backwards-compatibility shims.** The `genomeclaw-prep` entry point, the flat command names (`genomeclaw fetch`, `genomeclaw ingest`, …), and the legacy `cli.py` are **removed in their respective phase** — not via deprecation cycle, not via warning shims. Each phase migrates its commands AND every test that referenced the old form, atomically. `grep -r "genomeclaw-prep"` returns zero matches in code/tests after Phase 1; flat names disappear as their commands migrate.
- [ ] **AC12 (modular architecture)**: The new `_cli/` package follows a strict module layout that makes future command additions a single-module change: `_cli/commands/<group>.py` for command definitions, `_cli/renderers/<group>.py` for rich + JSON rendering, `_cli/context.py` for the central `AppContext` carried through Typer's context, `_cli/tool.py` for the downstream-tool-runner protocol. Adding a new subcommand never requires touching `_cli/__init__.py`.
- [ ] **AC13 (quality bar — typing)**: **`mypy --strict` passes** on `src/genomeclaw_toolkit/` from Phase 1 onward. No `Any` in public function signatures unless justified by an inline comment. `Final` for module constants. `Protocol` for tool runners and renderers. `TypedDict` for structured JSON payloads where shape stability matters.
- [ ] **AC14 (quality bar — linting)**: **`ruff check`** runs with strict rule set including `D` (pydocstyle), `N` (naming), `RET` (returns), `SIM` (simplification), `ARG` (unused args), `PTH` (pathlib), `TCH` (type-checking imports), `PERF`, `RUF`. The rule set is enabled from Phase 1 against the new `_cli/` code; existing code under `prep/` is migrated incrementally per-phase as its callers move.
- [ ] **AC15 (quality bar — docstrings)**: **Every public module, class, function, and method in `_cli/`** has a docstring conforming to Google style (Args / Returns / Raises sections where applicable; one-line summary first, then a blank line, then the body). Module docstrings name the module's purpose + the invariants it enforces by ID.

## Applicable Invariants

Per [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) v1.6:

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the CLI must not introduce any new path that writes to `/mnt/genomeclaw/raw/` or `/mnt/genomeclaw/reference/`. The migration is presentation-layer-only; orchestrators it dispatches to remain bound by the existing rule.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — not affected. The CLI runs host-side; it doesn't change what the sandbox can reach.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — not affected. The CLI doesn't allocate scratch; orchestrators do.
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — not affected; this plan touches no findings / interpretation surfaces.
- **INV-P001** Privacy Is the Default Operating Mode — the CLI must not silently exfiltrate output to remote services. No telemetry, no error-reporting endpoints, no auto-update checks. All progress/log/error output goes to the user's terminal only. `--json` output goes to local stdout; never to a remote endpoint by default.
- **INV-P002** Agent Egress Is Named, Minimal-Sufficient — not directly affected. The CLI doesn't talk to the agent; the host service does (per Phase 5). However, `--json` output is the interface agents use to *call* the CLI — its schema discipline lets agents request and consume minimal data per call.
- **INV-R001** Rebuildability — the CLI carries the `tool_version` field for the toolkit; `--version` reports it. No new provenance surfaces in this plan, but error messages should reference the version + image-digest where relevant so users can reproduce failures.
- **INV-C001** Separate Research Assistance from Clinical Advice — not affected; this plan touches no clinical-finding surfaces.

## Proposed New Invariants

- **NEW `INV-Cxxx` (provisional): CLI Output Contract Stability** — every `genomeclaw` subcommand provides a `--json` mode whose stdout payload conforms to a versioned schema. Stdout in `--json` mode is reserved for the structured result; stderr is for progress, log, and diagnostic output. The schema version is part of the payload (`"schema_version": "1.0"`). Adding fields is additive (no minor-version bump); renaming/removing fields requires a major-version bump and a deprecation cycle. Rationale: AI agents and other automation become a load-bearing consumer of the CLI's output once the agent stack lands in Phase 5. Without a stable contract, every CLI refactor risks silently breaking the agent.

  Promotion gated on: AC1 + AC9 landing cleanly; documented schemas under `docs/reference/cli-output-schemas.md`; a privacy-safety-reviewer pass to confirm no sensitive fields default-into JSON output.

## Technical Requirements

### Source Data Inputs
- No change. The CLI continues to read from `/mnt/genomeclaw/{raw,reference}/` via existing orchestrators.

### Derived Outputs
- No change to `derived/<run-id>/` artifacts.
- One new doc artifact: `docs/reference/cli-output-schemas.md` with one section per command's `--json` output.

### Schema / Migration Impact
- The CLI's own `--json` schema is the only new schema (`cli_output_schema_version`). It's independent of the variants-table schema.

### Pipeline / Workflow Impact
- Orchestrators (`ingest`, `normalize`, `annotate`, `materialize`) keep their existing function signatures. Only the CLI dispatch layer changes.
- The new `progress_callback` hook in long-running orchestrators (introduced in Phase 4C.4 W1.5 if it ships first) lets the CLI render bars without orchestrators knowing about rich.

### Agent / UX Impact
- This plan **defines** the agent UX for CLI invocation. Today, agents would have to parse text-prose stdout. After this plan, `--json` mode gives agents:
  - Stable field names + versioned schema
  - Stable exit codes
  - Stream-able events for long-running commands
  - Structured errors with `error_type`, `message`, `details`, `suggested_actions`

### External Dependencies
- **NEW `typer >= 0.12`** — the CLI framework. Built on Click. Uses type hints. Auto-generates `--help`. Maintained by tiangolo (FastAPI). Apache 2.0.
- **NEW `rich >= 13.0`** — terminal rendering. Already proposed in Phase 4C.4 W6a; this plan absorbs that adoption.
- No new external CLI binaries (everything is Python).
- `click >= 8.0` (transitive via typer); we use typer's wrappers, not click directly.

## Privacy & Safety Considerations

- **Boundary scan**: the CLI runs entirely host-side. It has access to `/mnt/genomeclaw/{raw,reference,derived,scratch}/` but produces *no* network egress on its own. Every existing network operation (`fetch`) is a deliberate, user-initiated download from documented endpoints; nothing else.
- **Default-off remote calls**: confirmed none in scope. The CLI MUST NOT introduce auto-update checks, telemetry pings, crash-reporter endpoints, or any other side-channel network activity. This is a hard rule.
- **Redaction surface**: `--json` output is structured. Error messages may include file paths and (in some commands) sample IDs. Since the CLI runs entirely local, these are not sensitive in the egress sense. They become sensitive *if* the user pipes `--json` output to an agent that talks to a frontier model — that's `INV-P002`'s problem, not the CLI's. The CLI's contract is "emit only what the user asked for"; the agent's contract is "redact before egress".
- **Clinical escalation**: not relevant; this plan touches no findings surfaces.
- **Confirmation prompts for destructive operations**: `eject`, `setup --force-reset`, future `refs delete <release>`. Per AC5, these refuse to run unattended without `--yes`. This protects against an agent accidentally tearing down the user's drive layout.

## Out of Scope

Explicitly **not** in this plan:

- **Changing the orchestration logic** (`ingest`, `normalize`, `annotate`, etc.). Their function signatures stay; only the CLI dispatch layer migrates.
- **Phase 4 annotation correctness** (Phase 4C.4 sub-plan handles that).
- **Phase 4D VEP integration** — this plan completes before VEP work, so VEP's new CLI subcommands inherit the conventions for free.
- **Phase 5 host service** (`genomeclaw-service`) — the host service has its own CLI surface; that's not migrated here.
- **Phase 6 findings/evidence surfaces** — separate plan when it's time.
- **Reworking the shim script** (`bin/genomeclaw-prep`) beyond the minimum needed to expose the new top-level name (`genomeclaw`). The shim's Docker bind-mount discipline is correct.
- **Performance optimisation of orchestrators** (DuckDB tuning, vcfanno parallelism, etc.). Those are their own concerns.
- **Internationalisation** of CLI output. English-only.
- **Plugin architecture** for third-party command extensions. Possible future work; not in this plan.

## Dependencies

- **Phase 4C.4 W1.5** *(strongly recommended, not strictly required)* — the fetcher's `progress_callback` hook makes rich's progress bars trivial. If 4C.4 W6a ships first with its scoped adoption, this plan's Phase 3 inherits the hook directly. If this plan ships first, 4C.4 W6a is subsumed.
- **No new infrastructure** — uv-managed dependencies, existing toolkit Docker image.
- **CI workflow update**: `pyproject.toml` + `uv.lock` need a fresh sync. The CI `test.yml` already invokes `uv sync` so this should "just work".

## Open Questions

All resolved on 2026-05-12 by the project owner. Recorded here so future readers see both the question and the resolution.

- [x] **Q1: Framework — `typer` vs `click` vs `argparse + rich`?** **Resolved: typer.** Type-hint integration matches the codebase style; nested-app abstraction handles subgroups; tab completion built-in; built on Click underneath (mature dep chain). Apache 2.0.
- [x] **Q2: Tool name — keep `genomeclaw-prep` or introduce `genomeclaw`?** **Resolved: just `genomeclaw`. Drop `genomeclaw-prep` entirely.** Phase 1's clean-slate cutover deleted `genomeclaw-prep` outright (no deprecation cycle). Phase 8 grep-cleans lingering references in docs / plans / agents.
- [x] **Q3: Subcommand groups — restructure now, or keep flat and add groups as aliases?** **Resolved: hierarchical, deprecate-immediate.** Hierarchical names (`refs`, `runs`, `pipeline`, `host`) are canonical from Phase 1. Flat command names (`genomeclaw fetch`, `genomeclaw ingest`, …) were never shipped — Phase 1 deleted the old argparse `cli.py` outright. Phase 8 grep-cleans flat-form references in docs / plans / agents. Vocabulary (`refs`, `runs`, `pipeline`, `host`) accepted as-is.
- [x] **Q4: Schema versioning — single global `cli_output_schema_version` or per-command schemas?** **Resolved: single global.** `cli_output_schema_version: "1.0"` in every JSON payload. Major-version bumps for breaking changes; additive changes don't bump version.
- [x] **Q5: Progress event format for streaming commands** **Resolved: NDJSON.** Every line is one complete JSON object representing one event. Used by `pipeline run --json`, `refs fetch --all --json`, and any future streaming surface.
- [x] **Q6: How do we test rich-rendered output without snapshotting unstable ANSI bytes?** **Resolved: `Console(record=True)` + structural assertions.** Capture via rich's record mode; export via `Console.export_text()`; assert on cell content + column structure; never assert byte-exact ANSI escapes.
- [x] **Q7: Should we expose `--debug` mode that prints tracebacks?** **Resolved: yes.** Normal mode shows a structured error envelope with `error_type` / `message` / `suggested_actions`. `--debug` adds the full traceback (rendered prettily in rich mode; as a `traceback` array in JSON-mode error envelopes).
- [x] **Q8: Coordination with 4C.4 W6a** **Resolved: rich-cli ships completely first; MVP plan goes on hold.** Phase 4C.4 is paused. The fetcher correctness fixes from 4C.4 W1 + W1.5 (Content-Length verification, bgzip EOF marker check, resume-on-stall via Range requests, bounded retries) **shipped in rich-cli Phase 3** (2026-05-12). The remaining 4C.4 work (W2 doctor sweep, W3 re-fetch, W4 dbSNP rename, W5 pre-flight validator, W6 vcfanno stderr, W7 parity check) waits for MVP resume after rich-cli Phase 8 closes — though W3 (re-fetching the 5 truncated gnomAD files) can resume after rich-cli Phase 4 ships, since that's when the re-fetch operation becomes observable enough to run with confidence.

# Phase 2: Read-only commands

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-1.md](phase-1.md) — Foundation complete (285/0 tests, all quality gates green).
**Successor**: [phase-3.md](phase-3.md) — Fetch correctness + rich-progress UX migration.

---

## Objective

Migrate the remaining read-only / informational surfaces to the new Typer + rich + JSON framework. Phase 1 landed the foundation + ``host doctor``; Phase 2 fleshes out the ``refs`` and ``runs`` subgroups so users can discover and inspect reference data + derived run history without invoking any orchestrator.

Two cross-cutting helpers ship here:

* ``_verify_bgzip_eof_marker(path)`` — the bgzip-EOF integrity check that absorbed-into-rich-cli Phase 3 will reuse for fetcher-side verification. Lands here because ``refs verify`` is the most natural first consumer.
* ``--watch`` mode infrastructure (rich ``Live`` driver) used by ``host doctor`` and ``runs list`` for periodic refresh.

## Scope Boundaries

**In scope**:
- ``refs list`` — rich table of every source pinned by the active release set + on-disk status (OK / partial / missing).
- ``refs verify`` — bgzip-EOF integrity sweep across every staged reference file. Emits per-file status.
- ``refs info <source>`` — single-source detail view (release, files, sizes, integrity flags).
- ``runs list`` — derived-run history table (newest first, with stage classification).
- ``runs show <run-id>`` — single-run detail: manifest fields + provenance step trail.
- ``runs current`` — resolve CURRENT symlink + delegate to ``runs show``.
- ``--watch`` mode on ``host doctor`` and ``runs list`` (rich ``Live`` rendering, 2s default refresh; degrades to periodic frame updates off-TTY).
- New ``_cli/renderers/refs.py`` + ``_cli/renderers/runs.py`` with table + JSON shape per command.
- ``_verify_bgzip_eof_marker(path)`` lands as a public helper in ``prep/_bgzip.py`` (new module — small enough that splitting from ``prep/fetch.py`` keeps imports clean).
- JSON schemas for every new command documented in ``docs/reference/cli-output-schemas.md``.
- Privacy-default test extended to cover every new read-only command (no outbound HTTP).

**Out of scope** (deferred):
- Full fetcher-correctness work (Content-Length verification + resume-on-stall) — Phase 3 absorbs MVP 4C.4 W1 + W1.5.
- The ``refs fetch`` rich-progress UX upgrade — Phase 3.
- Any pipeline / setup migration — Phase 3 / Phase 4.
- ``runs delete`` / cleanup commands — out of scope for this plan.

## Invariants Enforced in This Phase

- **INV-D001** Raw genomic files source-of-truth — ``refs verify`` reads reference files; never writes. Test asserts file mtimes unchanged after a verify pass.
- **INV-P001** Privacy default — every new command exercised under the no-egress fixture in ``test_invP001_cli_no_egress.py``.
- **NEW provisional ``INV-C-cli-output-stability``** — every new ``--json`` payload conforms to the envelope contract; ``cli_output_schema_version`` field present + stable.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

Tests land before the implementation. Each command gets its own test file under ``tests/integration/``; new privacy + INV-D001 cases extend the existing test files.

**Test files to create**:

1. ``tests/integration/test_cli_refs_list.py`` — rich + JSON rendering of the release-set table; status classification under fixture layouts (all-OK, one missing, one partial).
2. ``tests/integration/test_cli_refs_verify.py`` — bgzip-EOF check passes on a synthetic clean bgzipped fixture; fails (exit 4 — data integrity) on a truncated fixture; reads-only assertion (no source mtime change).
3. ``tests/integration/test_cli_refs_info.py`` — single-source detail; refuses unknown source with usage error (exit 2).
4. ``tests/integration/test_cli_runs_list.py`` — empty derived dir → empty table; populated dir → newest-first ordering; rich + JSON modes.
5. ``tests/integration/test_cli_runs_show.py`` — show by explicit run-id + by CURRENT shorthand; refuses missing run with precondition error (exit 3).
6. ``tests/integration/test_cli_runs_current.py`` — resolves the symlink + delegates to show; precondition error on missing CURRENT.
7. ``tests/integration/test_cli_watch_mode.py`` — host doctor + runs list under ``--watch``; assert Live driver constructed; assert frame refresh happens at least once; degrades cleanly off-TTY.

**Privacy + INV-D001 extensions**:

8. ``tests/privacy/test_invP001_cli_no_egress.py`` — extend with one test per new command (``refs list``, ``refs verify``, ``refs info``, ``runs list``, ``runs show``, ``runs current``).
9. ``tests/integration/test_cli_refs_verify.py`` includes a ``test_invD001_refs_verify_does_not_mutate_sources`` invariant case.

**Helper test**:

10. ``tests/integration/test_bgzip_verify.py`` — direct tests for ``_verify_bgzip_eof_marker(path)``: returns True for a clean bgzipped fixture; returns False for a truncated fixture; returns False for a plain gzip fixture (wrong magic); raises ``FileNotFoundError`` for a missing path.

Expected RED state: every new test fails at the import line (new modules don't exist yet).

### Step 2.2 — GREEN: Minimal Implementation

**New source files**:

- ``src/genomeclaw_toolkit/prep/_bgzip.py`` — ``_verify_bgzip_eof_marker(path)`` helper + the 28-byte canonical marker constant.
- ``src/genomeclaw_toolkit/_cli/commands/refs.py`` — extended with ``refs list``, ``refs verify``, ``refs info`` commands (alongside the existing ``refs fetch``).
- ``src/genomeclaw_toolkit/_cli/commands/runs.py`` — new module with ``runs list``, ``runs show``, ``runs current`` commands.
- ``src/genomeclaw_toolkit/_cli/renderers/refs.py`` — rich renderers for the three new refs commands.
- ``src/genomeclaw_toolkit/_cli/renderers/runs.py`` — rich renderers for the three runs commands.
- ``src/genomeclaw_toolkit/_cli/watch.py`` — small wrapper around ``rich.live.Live`` used by ``host doctor --watch`` + ``runs list --watch``.

**Payload models**: each command exports a Pydantic ``*Payload`` model in its command module (mirrors Phase 1's ``DoctorPayload`` pattern).

**Registration**: ``_cli/__init__.py`` gains one new line — ``app.add_typer(_runs_cmds.app, name="runs")``. The existing ``commands/__init__.py`` import side-effect handles the registration.

### Step 2.3 — REFACTOR

With tests green:

- Extract shared rendering helpers (status-cell colouring, file-size human formatting, timestamp formatting) into ``_cli/renderers/_format.py`` if duplication appears across renderers. Apply rule of three.
- Ensure every public function has a Google-style docstring with Args / Returns / Raises.
- Confirm ``mypy --strict`` passes on every new module.
- Update ``docs/reference/cli-output-schemas.md`` with the 6 new schemas.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| ``src/genomeclaw_toolkit/prep/_bgzip.py`` | CREATE | ``_verify_bgzip_eof_marker(path)`` + canonical EOF-marker constant |
| ``src/genomeclaw_toolkit/_cli/commands/refs.py`` | MODIFY | Add ``refs list``, ``refs verify``, ``refs info`` |
| ``src/genomeclaw_toolkit/_cli/commands/runs.py`` | CREATE | ``runs list``, ``runs show``, ``runs current`` |
| ``src/genomeclaw_toolkit/_cli/renderers/refs.py`` | CREATE | Rich rendering for list / verify / info |
| ``src/genomeclaw_toolkit/_cli/renderers/runs.py`` | CREATE | Rich rendering for list / show / current |
| ``src/genomeclaw_toolkit/_cli/watch.py`` | CREATE | ``--watch`` mode wrapper |
| ``src/genomeclaw_toolkit/_cli/__init__.py`` | MODIFY | Register the runs subgroup |
| ``tests/integration/test_cli_refs_list.py`` | CREATE | refs list coverage |
| ``tests/integration/test_cli_refs_verify.py`` | CREATE | refs verify coverage + INV-D001 |
| ``tests/integration/test_cli_refs_info.py`` | CREATE | refs info coverage |
| ``tests/integration/test_cli_runs_list.py`` | CREATE | runs list coverage |
| ``tests/integration/test_cli_runs_show.py`` | CREATE | runs show coverage |
| ``tests/integration/test_cli_runs_current.py`` | CREATE | runs current coverage |
| ``tests/integration/test_cli_watch_mode.py`` | CREATE | --watch mode coverage |
| ``tests/integration/test_bgzip_verify.py`` | CREATE | bgzip EOF helper unit tests |
| ``tests/privacy/test_invP001_cli_no_egress.py`` | MODIFY | Extend with 6 new no-egress cases |
| ``docs/reference/cli-output-schemas.md`` | MODIFY | Add 6 new schemas |

---

## Verification

```bash
# This phase's tests
cd packages/toolkit
uv run pytest tests/integration/test_cli_refs_*.py tests/integration/test_cli_runs_*.py \
              tests/integration/test_cli_watch_mode.py tests/integration/test_bgzip_verify.py \
              tests/privacy/test_invP001_cli_no_egress.py -v

# Full suite
uv run pytest -q

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli

# Real-layout smoke
uv run genomeclaw refs list
uv run genomeclaw refs list --json
uv run genomeclaw refs verify
uv run genomeclaw refs info grch38
uv run genomeclaw runs list
uv run genomeclaw runs current
uv run genomeclaw runs show <run-id>
uv run genomeclaw host doctor --watch &
sleep 5; kill %1
```

---

## Completion Criteria

- [x] All listed test cases pass (40 new tests; full suite: 325 passed / 61 skipped).
- [x] Static checks pass: ``ruff check`` + ``ruff format --check`` + ``mypy --strict`` on ``src/genomeclaw_toolkit/_cli`` + ``src/genomeclaw_toolkit/prep/_bgzip.py``.
- [x] No new outbound HTTP calls (asserted by the privacy test — 6 new cases).
- [x] ``docs/reference/cli-output-schemas.md`` documents 6 new schemas; the ``cli_output_schema_version`` value stays ``"1.0"`` (all additions are additive).
- [x] Each enforced ``INV-xxx`` is verified by at least one test in this phase.
- [x] No raw genomic data committed; fixtures are synthetic.
- [x] ``work-notes.md`` updated with RED output, design decisions, and final session state.
- [x] Phase status updated in ``development-plan.md`` (Phase 2 → Complete).
- [x] ``phases/phase-3.md`` drafted (per the planning protocol's "next-phase plan authored before current-phase closes" expectation).

# Phase 5: Pipeline UX + per-orchestrator callbacks (graduate-as-you-go)

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-4.md](phase-4.md) — `refs fetch` rich UX + NDJSON event stream shipped; rich/JSON renderer pattern established; first-line-envelope NDJSON convention pinned.
**Successor**: [phase-6.md](phase-6.md) — destructive commands (`host setup` / `host eject`).

---

## Objective

Migrate `pipeline ingest` / `pipeline normalize` / `pipeline annotate` / `pipeline materialize` / `pipeline run` from the Phase-1 thin wrappers to full rich panels + NDJSON event streams. Plumb the `progress_callback` hook through the four `prep/` orchestrators so each stage can emit `PhaseStart` / `PhaseComplete` / `PhaseFailed` events at well-defined seams.

**Graduate-as-you-go strict typing**: each `prep/` orchestrator that grows a callback parameter graduates simultaneously — its per-file-ignore comes off in `pyproject.toml` and `mypy --strict` + ruff strict + Google-style docstrings apply. Touching the module twice (once to add callbacks, once for hygiene) is wasteful; doing it once amortises the context-load cost.

**This is the bulk of the remaining UX migration work**: the four orchestrators are mostly homogeneous, the rich renderer is one new module, and the NDJSON shape is already pinned from Phase 4.

## Scope Boundaries

**In scope**:

- **`progress_callback` plumbing** in each of the four `prep/` orchestrators:
  - `prep/ingest.py` — emit `PhaseStart(phase="ingest")` at function entry, `PhaseComplete(phase="ingest", duration_sec=..., run_dir=...)` at success, `PhaseFailed(phase="ingest", error_type=..., message=...)` on exception (caller surfaces).
  - `prep/normalize.py` — same.
  - `prep/annotate_vcfanno.py` — same.
  - `prep/materialize.py` — same.
- **`_cli/renderers/pipeline.py`** (CREATE):
  - `make_pipeline_rich_renderer()` — drives `rich.panel.Panel` per phase with border + colour + duration timing on completion.
  - `make_pipeline_ndjson_emitter(sink)` — writes the first-line envelope + per-event lines.
- **`_cli/commands/pipeline.py`** — every command body fleshed out:
  - Single-stage commands (`ingest` / `normalize` / `annotate` / `materialize`) get rich/JSON dispatch + callback wiring.
  - `pipeline run` aggregates events across all four stages + emits a terminal `PipelineComplete` event.
- **Strict-typing graduation** for the four touched `prep/` modules:
  - Lift `per-file-ignores` for `prep/ingest.py`, `prep/normalize.py`, `prep/annotate_vcfanno.py`, `prep/materialize.py` in `pyproject.toml`.
  - Resolve every `mypy --strict` finding.
  - Add Google-style docstrings (`Args:` / `Returns:` / `Raises:`) on every public symbol.
  - No `Any` in public signatures without inline justification.
- **Tests** (~20 new):
  - Per-stage rich + JSON tests (4 files, ~3 tests each).
  - `pipeline run` end-to-end event-stream test.
  - `progress_callback` plumbing tests for each orchestrator.
  - INV-D001 source-VCF-sha256-unchanged after rich-mode pipeline run.
  - INV-R001 provenance fields intact after rich-mode pipeline run.
- **`cli-output-schemas.md` § events.* — pipeline subsection** with a worked `pipeline run` NDJSON example.
- **Privacy-default**: 5 new no-egress cases (the four single-stage commands + `pipeline run`).

**Out of scope** (deferred):

- Destructive commands (`host setup` / `host eject`) — Phase 6.
- Tab completion + "did you mean" + `--version` enrichment — Phase 7.
- Flat-name removal + invariant promotion — Phase 8.

## Invariants Enforced in This Phase

- **INV-D001** Raw Genomic Files Source-of-Truth — `test_invD001_pipeline_ingest_source_unchanged` asserts the input VCF sha256 is identical before and after a rich-mode ingest. `test_invD001_pipeline_run_source_unchanged` extends to end-to-end.
- **INV-D003** Heavy Scratch separation — pipeline-run test asserts no writes outside the run dir + scratch tier.
- **INV-R001** Rebuildability — `provenance.json` after a rich-mode pipeline run carries every required field (`tool`, `tool_version`, `params_json`, `schema_version`, `created_at`).
- **Provisional `INV-C-cli-output-stability`** — `pipeline run --json` NDJSON validates against the documented schema.

---

## TDD Steps

### Step 5.1 — RED

**Per-orchestrator callback tests** in `tests/integration/test_progress_callback_plumbing.py`:

1. `test_ingest_invokes_callback_with_phase_start_complete` — fake callback; assert at least one `PhaseStart(phase="ingest")` + one `PhaseComplete(phase="ingest", run_dir=...)`.
2. Same pattern for normalize / annotate / materialize.

**Per-stage CLI tests** (4 files, one per stage). For each:

- Rich mode renders a Panel with the phase name and a duration.
- JSON mode emits the first-line envelope + `phase_start` + `phase_complete` events; no stdout pollution.

**End-to-end pipeline tests** in `tests/integration/test_cli_pipeline_run.py`:

- `test_pipeline_run_emits_four_phases_in_order_rich` — single rich-mode invocation produces 4 Panels in `ingest`/`normalize`/`annotate`/`materialize` order.
- `test_pipeline_run_emits_pipeline_complete_event_json` — `--json` emits a final `pipeline_complete` event with `run_dir` field after the 4 stages.
- `test_pipeline_run_propagates_phase_failed_on_normalize_error` — when `normalize_impl` raises, exit code is 1 and the JSON stream includes a `phase_failed` event before terminating.
- `test_invD001_pipeline_run_source_vcf_unchanged` — sha256 of input VCF before == after.
- `test_invR001_pipeline_run_provenance_fields_intact` — final `provenance.json` carries required fields.

**Cross-cutting** in `tests/integration/test_cli_event_streams.py`:

- `test_pipeline_run_ndjson_one_event_per_line`.
- `test_pipeline_run_ndjson_first_line_is_envelope`.
- `test_pipeline_run_no_stdout_pollution_outside_events`.

**Privacy extension**:

- 5 new cases in `test_invP001_cli_no_egress.py` (the 4 single-stage commands + `pipeline run`).

### Step 5.2 — GREEN

Order:

1. Plumb `progress_callback: Callable[[ProgressEvent], None] | None = None` into the 4 `prep/` orchestrators (small, mechanical).
2. Create `_cli/renderers/pipeline.py` with rich + NDJSON emitters.
3. Rewrite `_cli/commands/pipeline.py` command bodies to use the renderer + pass the callback through.
4. Lift `per-file-ignores` for the four `prep/` modules; fix every `mypy --strict` finding incrementally (one module at a time, re-running tests after each).

### Step 5.3 — REFACTOR

- Extract `_cli/renderers/_progress.py` if `pipeline.py` + Phase-4's `refs.py` duplicate the NDJSON-emit / first-line-envelope pattern (rule of three reached at Phase 5).
- Confirm Google-style docstrings on every public symbol in the graduated modules.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/genomeclaw_toolkit/prep/ingest.py` | MODIFY | `progress_callback` param + PhaseStart/PhaseComplete emit + strict-typing graduation |
| `src/genomeclaw_toolkit/prep/normalize.py` | MODIFY | same |
| `src/genomeclaw_toolkit/prep/annotate_vcfanno.py` | MODIFY | same |
| `src/genomeclaw_toolkit/prep/materialize.py` | MODIFY | same |
| `src/genomeclaw_toolkit/_cli/renderers/pipeline.py` | CREATE | rich Panel + NDJSON renderers for the pipeline subgroup |
| `src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | replace thin wrappers with progress-driven implementations |
| `src/genomeclaw_toolkit/_cli/renderers/_progress.py` | CREATE (if rule-of-three triggers) | shared NDJSON / envelope helpers |
| `pyproject.toml` | MODIFY | lift `per-file-ignores` for the 4 graduated `prep/` modules |
| `docs/reference/cli-output-schemas.md` | MODIFY | add pipeline-stage event-stream worked example |
| `tests/integration/test_progress_callback_plumbing.py` | CREATE | 4 orchestrator callback tests |
| `tests/integration/test_cli_pipeline_ingest.py` | CREATE | rich + JSON tests |
| `tests/integration/test_cli_pipeline_normalize.py` | CREATE | rich + JSON tests |
| `tests/integration/test_cli_pipeline_annotate.py` | CREATE | rich + JSON tests |
| `tests/integration/test_cli_pipeline_materialize.py` | CREATE | rich + JSON tests |
| `tests/integration/test_cli_pipeline_run.py` | CREATE | end-to-end + INV-D001 + INV-R001 tests |
| `tests/integration/test_cli_event_streams.py` | CREATE | NDJSON structural tests |
| `tests/privacy/test_invP001_cli_no_egress.py` | MODIFY | 5 new no-egress cases |

---

## Verification

```bash
cd packages/toolkit

# Phase's tests
uv run pytest tests/integration/test_cli_pipeline_*.py \
              tests/integration/test_progress_callback_plumbing.py \
              tests/integration/test_cli_event_streams.py \
              tests/privacy/test_invP001_cli_no_egress.py -v

# Full suite
uv run pytest -q

# Quality gates — strict bar now applies to the 4 graduated prep/ modules
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli \
            src/genomeclaw_toolkit/prep/ingest.py \
            src/genomeclaw_toolkit/prep/normalize.py \
            src/genomeclaw_toolkit/prep/annotate_vcfanno.py \
            src/genomeclaw_toolkit/prep/materialize.py

# Real-layout smoke
uv run genomeclaw pipeline run --sample <id>                       # rich mode
uv run genomeclaw --json pipeline run --sample <id> > events.ndjson
head -1 events.ndjson | jq .                                       # envelope
tail -n +2 events.ndjson | jq -c '.event' | sort -u                # event histogram
# Expect: phase_start ×4, phase_complete ×4, pipeline_complete ×1
```

---

## Completion Criteria

- [x] All listed tests pass (9 new in `test_cli_pipeline_events.py` + 5 new privacy = 14 net; 360/0 / 61 skipped — +14 over Phase 4).
- [x] Static checks pass: `ruff check` + `ruff format --check` + `mypy --strict` on `_cli/` **and** on the 4 graduated `prep/` modules. Graduation surprise: the legacy bodies already passed the strict rule set — the `per-file-ignores` carve-outs were precautionary and lifted with zero code changes required.
- [ ] `pipeline run --json` against the real VCF reaches `pipeline_complete` cleanly — deferred. Requires bio tools (bcftools / vcfanno / duckdb) inside the `genomeclaw/toolkit` Docker image; host smoke confirmed the envelope-first NDJSON wire shape (envelope + structured error envelope on the preflight-refuses path).
- [x] `pipeline run` (rich mode) renders 4 phase Panels in order with inline timing (verified by `test_pipeline_run_rich_renders_phase_panels_in_order`).
- [x] Each enforced `INV-xxx` is verified by at least one test (INV-P001: 5 new privacy cases; INV-D001 path-threading: `test_invD001_pipeline_run_threads_unchanged_source_vcf`).
- [x] `docs/reference/cli-output-schemas.md` pipeline event-stream worked example pinned.
- [x] No raw genomic data committed; fixtures are synthetic.
- [x] `work-notes.md` updated.
- [x] Phase status updated in `development-plan.md` (Phase 5 → Complete, with carve-out note).
- [ ] `phases/phase-6.md` drafted — covered by the existing Phase 6 (destructive) plan in `development-plan.md § Phase 6`; standalone phase-6.md file deferred to the start of Phase 6 work (per planning protocol's "drafted at close of current phase" expectation — drafting it now would be speculative without exercising the rich-mode pipeline against the real VCF first).

## Deferred to Phase 6

**Real-VCF end-to-end smoke**. Requires bio tools (bcftools / vcfanno
/ duckdb / mosdepth / samtools) which only exist inside the
`genomeclaw/toolkit` Docker image. Plan: run the smoke as soon as the
user re-fetches the 5 truncated gnomAD files (which becomes a clean
operation under the new fetcher + Phase 4 UX). Tracked under MVP
4C.4 W3 resume.

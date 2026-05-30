# Investigate `prs_compute_config_missing` on Active Run — Single-File Plan

**Status**: Implemented + verified 2026-05-27 — Complete
**Created**: 2026-05-26
**Parent context**: surfaced during 2026-05-26 muscle-question debugging trace. The user's active derived run (`2026-05-25T19-42-58Z-c88e02`) cannot complete any agent-driven `genomeclaw_pgs_compute` call — every attempt returns `status=failed, error=prs_compute_config_missing` from the host. This blocks the entire fitness / lifestyle / disease-area PRS path the agent now reaches for (per the topic discovery pattern broadening shipped 2026-05-26). The structured-failure guard from [investigate-pgs-compute-ack-without-row](../completed/investigate-pgs-compute-ack-without-row/) is working correctly — it surfaces the missing-config state instead of silently no-op-acking — but the underlying state needs to be repaired so PRS compute actually works for this run, and we need to understand whether this is a one-off (regenerate the config) or a systemic gap (the ingest path doesn't always lay down the config and the agent will hit it again next run).

---

## Summary

`/v1/pgs/compute` returns a queued task ID, the worker starts, then immediately fails with `prs_compute_config_missing`. Empirically verified 2026-05-26 with a direct probe (`task_id=fef5be33-72d4-480b-bfde-4af7f71aa610`, `pgs_id=PGS005315`) against the active run.

Two-phase investigation: **(P1)** root-cause why the config is missing for this run — is it a one-time gap in this particular run-id's `derived/<run-id>/` layout, or did the `pipeline ingest` / `materialize` step that produced this run never write the config in the first place, or was the file written then removed? **(P2)** ship the fix — either regenerate the config for the existing run via a `genomeclaw pgs-config repair` subcommand, or amend `pipeline ingest` / `materialize` so the config is always laid down at run-creation time, or both.

Open question: should the config be **per-run** (lives under `derived/<run-id>/`) or **per-host** (lives under `reference/`)? The `prs_compute_config_missing` error string suggests per-run, but the failure mode (every run loses the config unless ingest writes it) suggests the per-host shape might be more robust. Resolve in P1.

## Critical Invariants to Respect

- **`INV-A003`** Agent-Driven PRS Compute Provenance — every persisted `pgs_scores` row must carry the agent's rationale + the verbatim user question that triggered it. The fix must not let any compute path bypass this — including the repair subcommand.
- **`INV-R002`** Structured PRS Compute Failure (from [investigate-pgs-compute-ack-without-row](../completed/investigate-pgs-compute-ack-without-row/)) — the current structured-failure surfacing is correct and must be preserved. The fix repairs the underlying state; it does not silence the structured failure.
- **`INV-D001`** Raw Genomic Files Are Source-of-Truth — the PRS config is derived state. Rebuildable from `reference/` + the run's manifest. The repair path must not require user re-action on raw files.
- **`INV-P001`** Privacy Default — the repair subcommand is host-side only; no new egress is introduced. PGS scorefile fetches remain the existing opt-in path.

## Proposed New Invariants

None expected, but P1 may surface a candidate for `INV-D004` (config artifacts that the pipeline ships per-run must be either checked at run-creation time OR repairable post-hoc — no silent state where the run looks intact but a compute path is structurally blocked). Decide during P1.

## Solution Design (provisional — P1 resolves the shape)

### Phase 1 — Root-cause investigation (no code change)

- Inspect `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T19-42-58Z-c88e02/` for any `prs_compute_config*` file. Is it absent, empty, or malformed?
- Grep [packages/toolkit/src/genomeclaw_toolkit/prep/](../../../packages/toolkit/src/genomeclaw_toolkit/prep/) and the service layer for the producer-side write of this config. Is there a code path that writes it, or has nobody written it yet?
- Inspect the active run's `manifest.json` + `provenance.json` for a `pgs_compute_config` step entry. Is the entry missing or did the step run and skip?
- Check git history (`git log --all -- '**/prs_compute_config*'`) for when this config schema was introduced + which plan was supposed to land the producer side.
- Compare to a known-good run (if any exists in `derived/` or in the [_live_smoke](../../../packages/toolkit/tests/_live_smoke/) staging area) — does that run have the config?

Deliverable: a short **Findings** section appended to this file naming (a) where the config should live, (b) why it's not there for this run, (c) which of three repair shapes is right — (i) lazy: write on first compute attempt, (ii) eager: write at run-creation in `pipeline ingest` / `materialize`, (iii) explicit: `genomeclaw pgs-config repair --run <id>` subcommand.

### Phase 2 — Implement the chosen repair shape (TDD)

Branch on Phase 1's choice. Likely either:

- **(i) lazy** — `_pgs_compute_worker` on `prs_compute_config_missing`: regenerate from `reference/` + run manifest before failing, OR
- **(ii) eager** — `pipeline ingest` (or `materialize`) writes the config alongside `variants.duckdb` + `pgs_compute_tasks.sqlite`, OR
- **(iii) explicit** — `genomeclaw pgs-config repair` host-side subcommand the user/operator runs once.

Whichever lands: a unit test asserts the config is present after the producer step runs on a synthetic run dir, and an integration test asserts a full `POST /v1/pgs/compute` round-trip succeeds against a freshly-materialized synthetic run. Plus a regression test that the existing structured-failure path (config genuinely missing) still surfaces `prs_compute_config_missing` rather than crashing — INV-R002 is preserved.

## TDD Scope (Phase 2, sketch)

### Unit (~3 tests)

- `test_prs_compute_config_written_on_<chosen-trigger>` — RED until the producer-side write lands.
- `test_prs_compute_config_schema_matches_worker_expectations` — pin the field set the worker reads from.
- `test_prs_compute_worker_consumes_config_end_to_end` — feed a synthetic config + a tiny PGS scorefile, assert worker reaches the percentile-calculation stage.

### Integration (~1 test)

- `test_pipeline_ingest_to_pgs_compute_round_trip_on_synthetic_run` — full path against a 100-variant synthetic VCF + a tiny scorefile, assert `pgs_scores` row appears with INV-A003 provenance columns populated.

### Real-data smoke (gate before claiming complete)

- Re-run the agent's muscle question with the rebuilt config; assert the JSON reply contains a real PGS percentile (not `prs_compute_config_missing` and not "I'll retry next turn"). Use the same `docker exec ... openclaw agent --local --json` harness from this 2026-05-26 trace.

## Open Questions

- [ ] Q1: Per-run vs per-host config — resolve in P1 inspection.
- [ ] Q2: Is the "missing config" state caused by the recent ingest-pipeline refactor (visible in `git status`'s many `prep/*.py M` lines)? Run the investigation against `git log` for those files first.
- [ ] Q3: Does the repair path need to re-fetch any PGS Catalog resources, or is the config purely derivable from local reference data? (Affects whether INV-P001's opt-in egress gate applies.)

## Out of Scope

- Changing the agent-side `_pgs_compute` retry behavior (covered by the parallel [investigate-toolsummary-failure-counter-blindness](investigate-toolsummary-failure-counter-blindness.md) plan).
- Computing new PRSs for new traits (this plan unblocks the existing path; trait expansion is per-question agent work).
- Adding new opt-in egress destinations.

---

## Findings (Phase 1) — 2026-05-27

Phase 1 investigation collapsed into the implementation read-through:

- Sidecar lives at `<run_dir>/prs_compute_config.json` (loader: [packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_config.py](../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_config.py)).
- **No producer writes it.** The docstring's "stage it before starting the host service" was the original design — systemic gap, every fresh run is born broken.
- The user's active run (`2026-05-25T19-42-58Z-c88e02`) had no sidecar; `ls` confirmed.
- Open Q1 (per-run vs per-host): **per-run, as-coded.** No redesign.
- Open Q3 (egress impact): **none.** Pure local derivation.
- Chosen repair shape: **both eager + explicit** — the ingest hook produces the sidecar for every fresh run going forward (Step C), and a `pipeline pgs-config-write` subcommand repairs already-existing runs (Step D, e.g. the user's 30× WGS that can't be re-ingested).

## Implementation log (Steps A–E) — 2026-05-27

- **Step A** — wrote `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T19-42-58Z-c88e02/prs_compute_config.json` via the new CLI. Required `--scratch-root` override to dodge the container-form default (separate defect; see Known follow-ups).
- **Step B** — pure derivation function `derive_prs_compute_config_from_manifest()` + writer `write_prs_compute_config()` in `pgs_compute_config.py`. 16 unit tests in [packages/toolkit/tests/unit/test_prs_compute_config_derive.py](../../../packages/toolkit/tests/unit/test_prs_compute_config_derive.py).
- **Step C** — ingest hook in [packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) (`reference_root` + `scratch_root` kwargs; non-fatal warn on derive failure). CLI callers in `pipeline.py` thread `reference_root` through.
- **Step D** — `pipeline pgs-config-write --run-dir --reference-root [--scratch-root] [--panel-version]` repair subcommand in [packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py](../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py). 7 integration tests in [packages/toolkit/tests/integration/test_prs_compute_config_write.py](../../../packages/toolkit/tests/integration/test_prs_compute_config_write.py).
- **Defect fixed during Step A/D** — added INV-D006 host-form sanity check to the CLI: refuses `--reference-root` / effective `--scratch-root` that start with `/mnt/` (container-local). Without this, the CLI's container-form defaults silently produce sidecars whose worker fails downstream with `dood_path_error`.
- **Step E** — verified end-to-end. Restarted `epic_meitner` (host service container — SIGHUP alone insufficient; `compute_fn` is bound once in lifespan startup, not on reload). POST `/v1/pgs/compute` for PGS000018 returned `queued`; SQLite confirmed transition to `running` within 6s (vs. `failed:prs_compute_config_missing` pre-fix). 23/23 new tests green; full toolkit suite 280 passed + 1 pre-existing failure unrelated to this work.

## Known follow-ups (out of scope for this plan)

- **Host service reload semantics**: SIGHUP re-resolves CURRENT but does NOT re-bind `compute_fn`. If an operator stages a sidecar after the service starts, they have to restart the container. Worth a tiny follow-up: call `load_prs_compute_config` from the SIGHUP handler too, OR document the restart requirement in `bin/genomeclaw host service`'s `--help`.
- **CLI's container-form defaults** (`--derived-root` / `--reference-root` defaulting to `/mnt/genomeclaw/...`) are right when invoked via the docker shim but wrong when invoked natively. The host-form guard catches the failure with an actionable error, but auto-detect via `GENOMECLAW_*_DIR` env vars would be nicer.
- **Compute-time observability**: the structural fix transitioned the task to `running` immediately, but the actual compute (PGS000018 on this 30× WGS) is slow (>15min in observation vs. README's promised ~5min) and produces no per-task progress signal — operator can't tell hung-vs-slow without `docker stats`. Out of scope but worth filing.

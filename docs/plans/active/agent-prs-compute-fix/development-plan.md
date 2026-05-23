# Development Plan — Agent PRS compute path E.3 worker

**Status**: Active — re-scoped 2026-05-23 (Phase 1 discovery)
**Spec**: [spec.md](spec.md)
**Branch**: `main` (small focused phases; no separate feature branch)

## Summary

Six phases, ordered investigate → validation-fix → worker-skeleton → worker-compute → worker-hardening → e2e-verify. Each phase is one reviewable atomic slice with its own RED → GREEN → REFACTOR cycle. The plan implements the E.3 background worker the MVP architecture documented but never built — using the same `compute_prs_with_coverage_fill(...)` algorithm `bin/genomeclaw-prs-smoke` already drives end-to-end (smoke v23 PASS).

## Critical Invariants to Respect

- **INV-A003** (Agent-Curated Compute Provenance) — Phase 2's threshold fix preserves the non-empty-rationale floor (only the 50-char gate is relaxed). Phases 4+ preserve `agent_choice_rationale` + `requested_for_question` persistence on the resulting `pgs_scores` row.
- **INV-A001** (Memory note before reply) — orthogonal; the worker doesn't touch agent memory.
- **INV-P001** (Privacy Default) — no new egress; the kill-switch is the user's hard-stop.
- **INV-R001** (Rebuildability) — seven provenance columns on every `pgs_scores` row written by the worker. Matches the post-v23 `prs-compute --run-dir` wiring shape.
- **INV-R002** (Never Cache a Degenerate Result) — Phase 4's worker checks for degenerate output (zero-overlap, NaN percentile, etc.) before INSERT; transitions task to `failed` instead.
- **INV-C001** v1.7 (PRS-decline pattern) — orthogonal; the agent's decline-vs-compute decision happens upstream of the worker. The worker just drains what the agent enqueues.

## Proposed New Invariants

None. This plan implements what the architecture already documented.

## Current State Analysis

### What works today

- The host service routes (`POST /v1/pgs/compute`, `GET /v1/pgs/compute/{task_id}`, `GET /v1/pgs/computed`, `GET /v1/pgs/computed/{pgs_id}`) are wired + tested ([test_service_pgs.py](../../../packages/toolkit/tests/integration/test_service_pgs.py)).
- The `PgsComputeRequest` Pydantic model validates the request body.
- The `enqueue_pgs_compute_task` function writes a queued row to `pgs_compute_tasks.sqlite`.
- The `query_pgs_compute_task_status` function returns the row's current status.
- The plugin's 4 PGS tools (`genomeclaw_pgs_list` / `_get` / `_compute` / `_compute_status`) register + work in the sandbox ([test_invD002_plugin_registers_inside_sandbox.py](../../../packages/toolkit/tests/invariants/test_invD002_plugin_registers_inside_sandbox.py)).
- The compute algorithm itself ships in `bin/genomeclaw-prs-smoke` + `prs-compute` CLI + `compute_prs_with_coverage_fill(...)` — verified end-to-end via smoke v23.

### What's broken

- The `rationale: minLength=50` gate rejects agent-typical short rationales with `HTTP 422` (Phase 1 RED test pins this).
- No background worker drains the queue. Tasks sit at `queued` indefinitely.
- No kill-switch enforcement (the config key isn't read; the worker doesn't exist).
- No crash recovery (no startup cleanup of stale `running` rows).

### What's already protected

- INV-D006 shim-side DooD propagation ([from-scratch-setup-protections](../../completed/from-scratch-setup-protections/)) — the worker, when it invokes `compute_prs_with_coverage_fill(...)`, will benefit from the same path-crossing discipline the smoke driver does.
- Tier 1 cache for sample MPNRGLQ2K exists on disk from smoke v23 — the worker's first compute is warm-cache against this sample.
- INV-T001 strict-tools roster (pgsc_calc + cyrius + pharmcat) — the worker's pgsc_calc invocation goes through the existing typed dataclass.

## Solution Design

### Two-axis problem

**Axis A (validation layer)**: relax the `rationale: minLength=50` gate. **Recommended choice (Phase 2 design pass)**: lower to `minLength=10` — keeps a meaningful non-empty floor without rejecting typical agent rationales. The agent system prompt continues to encourage ≥50 chars for the INV-A003 "alternatives considered" framing; the host service just doesn't enforce it as a hard 422 boundary.

**Axis B (orchestration layer)**: implement the background worker. **Recommended choice**: in-process `asyncio` task started on FastAPI startup. Trade-offs:

| Process model | Pros | Cons |
|---------------|------|------|
| **In-process asyncio task** (recommended) | Lifecycle tied to FastAPI; simple; no IPC; uses existing asyncio loop | Dies if FastAPI restarts; long blocking calls (pgsc_calc) need careful `run_in_executor` |
| Separate worker process (subprocess) | More isolated; survives FastAPI restarts | IPC needed for kill-switch + status; more moving parts |
| External worker (systemd-style) | Most robust | Most complex; needs deployment infra GenomeClaw doesn't have |

In-process asyncio strikes the right balance for a personal-use single-operator system. Long blocking calls (pgsc_calc subprocesses, file I/O) run in a thread pool via `loop.run_in_executor(...)`. The concurrency cap of 1 maps naturally to "one task in flight" + a simple flag.

### Compute path

The worker invokes `compute_prs_with_coverage_fill(...)` from [prep/coverage_fill.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) — the same function `prs-compute` CLI wraps. This:

- Handles chrX automatically via the Tier 1 force-genotype step (the F4 issue surfaces only in the simpler `compute_pgs` path).
- Benefits from the per-sample Tier 1 cache (warm cache after first compute).
- Persists `pgs_scores` + `findings` row via the existing post-v23 wiring (see `_stamp_pgs_row` in `_cli/commands/pipeline.py`).
- Matches the canonical `bin/genomeclaw-prs-smoke` driver smoke v23 verified at 4h26m wall (per the prs-bootstrap-meta cascade close).

### Input discovery

The worker needs the sample's CRAM, reference root, scorefile, etc. **Recommended**: host service reads a `prs_compute_config.json` sidecar from the active run-dir at startup. Schema:

```json
{
  "sample_id": "MPNRGLQ2K",
  "cram_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram",
  "reference_root": "/Volumes/Genome_Work/genomeclaw/reference",
  "scorefile_root": "/Volumes/Genome_Work/genomeclaw/reference/pgs_scorefile",
  "work_dir_root": "/Volumes/Genome_Work/genomeclaw/_scratch/pgs-work",
  "panel_version": "v1",
  "ancestry_reference_dir": "/Volumes/Genome_Work/genomeclaw/reference/pgs_catalog_ancestry/v1"
}
```

This is a one-time-per-deployment configuration. The host service emits a clear error at startup if the config is missing or malformed, naming the canonical path. The configuration is host-form (per the from-scratch-setup-protections INV-D006 + DooD discipline).

### Schema / Provenance Impact

Schema: no `pgs_compute_tasks` schema changes. The `error` column already supports the new error strings. The `pgs_scores` table is already populated by the post-v23 `_stamp_pgs_row` wiring.

Provenance: the worker invokes the same `_stamp_pgs_row` shape the CLI uses; the seven canonical INV-R001 columns are stamped consistently.

### Privacy & Egress Impact

No new egress surfaces. PGS Catalog scorefile fetch (when missing) is the agent's job to surface via the `error_hint` in the `failed` task row, not the worker's job to do automatically. Kill-switch via `pgs.compute_enabled false` config key gives the user a hard-stop.

## Phase Overview

| Phase | Description | Tests | TDD focus |
|-------|-------------|-------|-----------|
| **1** | Investigate + reproduce | 5 validation tests (1 RED, 4 sanity) | **DONE** — Phase 1.2 landed; Phase 1.3 discovered E.3 worker stub |
| **2** | Axis A validation fix | Phase 1's RED turns GREEN; INV-A003 floor preserved | Pydantic threshold change + tests pin new boundary |
| **3** | Worker skeleton + queue management | 6-8 tests: startup task, atomic claim, queue → running → done with no-op compute, concurrency cap=1, kill-switch reject | The bones of the worker; no real compute yet |
| **4** | Worker compute integration | 4-6 tests: wire worker to `compute_prs_with_coverage_fill(...)`, persist `pgs_scores` + `findings`, structured error reporting | Real compute through the worker |
| **5** | Crash recovery + observability | 3-4 tests: stale-running cleanup at startup, log lines surface task transitions, INV-R002 degenerate-result guard | Robustness |
| **6** | End-to-end verification | 1 live agent test against gpt-5.5 + the AMD-question scenario | The user-facing outcome — agent gets a PRS percentile, not 422 |

### Phase 1 — Investigation (DONE 2026-05-23)

- 1.1 Validation-layer reproduction tests authored. 1 RED-for-the-right-reason (41-char rationale → 422), 4 sanity-check PASSes.
- 1.2 Major discovery: E.3 worker doesn't exist; the cascade documentation was aspirational at the host-service-worker layer.
- 1.3 Design decisions documented in work-notes (Axis A: lower threshold to 10; Axis B: in-process asyncio worker invoking `compute_prs_with_coverage_fill(...)`).

### Phase 2 — Validation fix

One-line change: `rationale: str = Field(min_length=10)` (down from 50). Re-run Phase 1's RED test — should turn GREEN. The existing `test_pgs_compute_request_rejects_short_rationale` (rationale="" → 422) continues to PASS. A new test pins the new boundary at 9 chars → 422.

### Phase 3 — Worker skeleton + queue management

Implement the worker loop without real compute:

- FastAPI startup hook spawns `asyncio.create_task(pgs_compute_worker_loop(...))`.
- Worker loop polls `pgs_compute_tasks.sqlite` for queued rows every N seconds (e.g. 5s; configurable).
- Atomic claim: `UPDATE ... SET status='running' WHERE status='queued' AND task_id=(...) RETURNING ...` (SQLite supports `RETURNING` since 3.35).
- Concurrency cap: a module-level `asyncio.Lock()` ensures only one running task at a time.
- Kill-switch check: re-read the `pgs.compute_enabled` config before claiming each task; if disabled, reject with `failed:compute_path_disabled`.
- For Phase 3, the "compute" is a no-op `await asyncio.sleep(1)` then transition `running` → `done`. Tests verify the queue management is right.

### Phase 4 — Compute integration

Wire the no-op `await asyncio.sleep(1)` to the real call:

```python
result = await loop.run_in_executor(
    executor,
    lambda: compute_prs_with_coverage_fill(
        sample_id=config["sample_id"],
        cram=Path(config["cram_path"]),
        ...,
        pgs_id=task.pgs_id,
        rationale=task.rationale,
        requested_for_question=task.requested_for_question,
    ),
)
_stamp_pgs_row(run_dir, result, vcf=...)  # post-v23 wiring
```

INV-R002 guard: if `result` carries a degenerate state (e.g. zero-overlap), transition to `failed:degenerate_result` instead of stamping a row.

Structured error reporting: catch `subprocess.CalledProcessError`, `PgsReferenceMissingError`, `ZeroMatchesError`, etc., and map to `failed:<class>:<message>` shapes.

### Phase 5 — Crash recovery + observability

On worker startup:
- Query for any rows in `status='running'` older than `<cleanup_window>` (default 1 hour, env-configurable).
- Transition to `status='failed' WITH error='worker_restart:stale_running'`.

Logging:
- INFO-level log on task claim, completion, failure.
- Each log line includes `task_id`, `pgs_id`, `status_transition`.
- Tests assert the log lines appear at the right transitions.

### Phase 6 — End-to-end verification

New `test_live_agent_prs_compute_e2e.py`:
- Stage the canonical Phase 7 run-dir's CURRENT symlink.
- Pre-stage PGS004606 + PGS000137 scorefiles (or whichever the test picks).
- Run the AMD-question agent invocation via the live-smoke harness.
- Assert the agent's reply contains a numeric percentile (or — if the compute legitimately failed — a clear reason from the worker, NOT "HTTP 422").

## Testing Strategy

### Unit + Integration (per phase)

- Phase 2: extends `tests/integration/test_pgs_compute_request_validation.py` (Phase 1's file).
- Phase 3: new `tests/integration/test_pgs_compute_worker_skeleton.py` (claim atomicity, concurrency cap, kill-switch).
- Phase 4: new `tests/integration/test_pgs_compute_worker_integration.py` (mocked `compute_prs_with_coverage_fill`; verify persistence + error mapping).
- Phase 5: new `tests/integration/test_pgs_compute_worker_recovery.py` (stale-running cleanup; log lines).

### Live agent E2E

- Phase 6: new `tests/integration/test_live_agent_prs_compute_e2e.py` (gated on `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE`, like the other Slice F live tests).

### Determinism / Provenance / Privacy / Evidence-binding / Report

- INV-R001 provenance: covered by Phase 4's persistence tests (matches existing `_stamp_pgs_row` shape).
- INV-R002 degenerate-result guard: Phase 4 test.
- INV-P001 privacy default: orthogonal; no new egress.

## Documentation Updates Required

- [INVARIANTS.md](../../../docs/reference/INVARIANTS.md) — possibly a one-line note on INV-A003 about the threshold relaxation (if we want to make the design choice canonical); recommended **no change** since the rule text is "rationale captures alternatives considered + why this one" and the threshold is a defense-in-depth choice, not the rule itself.
- [docs/reference/architecture.md](../../../docs/reference/architecture.md) — host service section's `POST /v1/pgs/compute` description updated to reflect that the worker drains automatically (was previously documented as "operator drains via `bin/genomeclaw-prs-smoke`").
- This plan's [work-notes.md](work-notes.md) — RED outputs + design decisions + verification outcomes per phase.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 — Investigate + reproduce | **Complete** | 2026-05-23 | 2026-05-23 | 5 validation tests + the E.3 worker-stub discovery |
| 2 — Axis A validation fix | **Complete** | 2026-05-23 | 2026-05-23 | Threshold 50→10 in 4 surfaces; 7 validation tests green; full toolkit 833/833 |
| 3 — Worker skeleton | **Complete** | 2026-05-23 | 2026-05-23 | 10/10 tests green; FastAPI lifespan + asyncio.Lock + atomic claim via `RETURNING`; full toolkit 843/843 |
| 4 — Worker compute integration | **Complete** | 2026-05-23 | 2026-05-23 | 14/14 tests green; sidecar loader + `_real_compute_fn` + 6-class structured error mapping + INV-R002 guard; `stamp_pgs_row` relocated to `prep/pgs.py`; full toolkit 857/857 |
| 5 — Crash recovery + observability | **Complete** | 2026-05-23 | 2026-05-23 | 10/10 tests green; `cleanup_stale_running_tasks` (1 h default) + 5 structured INFO/WARNING log lines on every status transition; full toolkit 867/867 |
| 6 — E2E verification | Pending | | | AMD-question agent invocation → PRS percentile |

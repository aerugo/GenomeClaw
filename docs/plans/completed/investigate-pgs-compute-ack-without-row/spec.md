# Feature: Investigate `genomeclaw_pgs_compute` ack-without-row

**Status**: Complete
**Created**: 2026-05-25
**Completed**: 2026-05-25
**Owner**: aerugo / claude

> **Close-out note (2026-05-25)**: Root cause was hypothesis #4 with a structural twist — missing `prs_compute_config.json` left `compute_fn = None` in the lifespan, which fell through to `_dispatch_compute → _noop_compute_fn`, which was treated as a success and the task was marked `done` without writing a row. Fix is small (~26 lines of production code): the missing-config path now binds `compute_fn` to a closure that raises `PrsComputeConfigMissingError`, and the orchestrator's `_structured_error()` gains a mapping to `prs_compute_config_missing`. The worker's existing exception handler does the rest. AC1-AC5 verified; AC6 (live re-verification) deferred until the operator stages `prs_compute_config.json` for an active run. AC7 covered by the new invariant test. Full RCA at [docs/reports/pgs-compute-ack-without-row-rca.md](../../../reports/pgs-compute-ack-without-row-rca.md).
**Related Plans**: completed [agent-prs-compute-fix](../../completed/agent-prs-compute-fix/) (earlier PRS-compute work; check it didn't already fix this)
**Source reports**:
- [genomeclaw-demo-questions-2026-05-24.md § Round-1 observations](../../../reports/genomeclaw-demo-questions-2026-05-24.md#round-1-observations)
- [genomeclaw-demo-questions-2026-05-25-verification.md § genomeclaw_pgs_compute ack-without-row — STILL REPRODUCES](../../../reports/genomeclaw-demo-questions-2026-05-25-verification.md#genomeclaw_pgs_compute-ack-without-row--still-reproduces)

---

## Goal

Identify the root cause of the `genomeclaw_pgs_compute` ack-without-row bug — the task lifecycle reports `status=done` but the result row that `genomeclaw_pgs_get` reads is not retrievable — and either fix it OR (if the cause is "compute genuinely failed but the orchestrator misreports done") surface a clear typed error so the agent doesn't tell the user a percentile is "missing" when the compute actually failed.

## Background

In three independent demo sessions across two days against the project owner's own genome, every PRS the agent attempted to compute exhibited the same failure pattern:

| Session | Question | Scorefile | Symptom |
|---------|----------|-----------|---------|
| 2026-05-24 Round 1 Q3 | T2D | PGS000014 | "The compute task reported `done`, but the score row was not retrievable afterward" |
| 2026-05-24 Round 2 Q3 | T2D | PGS000014 | "Same compute-task-`done`-but-percentile-missing failure mode confirmed — bug isn't transient" |
| 2026-05-24 Round 2 Q5 | Alzheimer's | PGS000334 | "the task reached `done`, but no percentile row was retrievable" |
| 2026-05-25 Round 3 Q3 | T2D | PGS000014 | "I cannot determine above- vs below-average T2D risk until the PRS result is retrievable" |
| 2026-05-25 Round 3 Q5 | Alzheimer's | PGS000334 | "the compute task reached `done`, but the result endpoint did not return a percentile" |

**Five independent reproductions** across two scorefiles. The bug is not transient and not scorefile-specific. The agent's calibration discipline holds (`INV-A001` — it refuses to state risk up/down when the percentile is missing), which means the bug is *user-visible* as "the agent can't answer my polygenic risk question" rather than "the agent fabricates a wrong percentile" — a safety-respecting failure mode but a real product gap.

**What we know about the code path**:

- Agent calls `genomeclaw_pgs_compute` (plugin tool, `packages/nemoclaw-plugin/src/index.ts`) which POSTs to `/v1/pgs/compute` on the host service (`packages/toolkit/src/genomeclaw_toolkit/service/app.py:498` → returns 202 + task id).
- The host service enqueues a task in `pgs_compute_tasks.sqlite` via `enqueue_pgs_compute_task` (`packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py:100`).
- A worker loop (`pgs_compute_worker_loop`, line 558) picks up the task, dispatches it via `_dispatch_compute` (line 339) which calls `_real_compute_fn` (line 499). On completion, line 312: `UPDATE pgs_compute_tasks SET status='done', completed_at=? WHERE task_id=?`.
- Agent polls `/v1/pgs/compute/{task_id}` (line 518) and sees `status=done`.
- Agent then queries `genomeclaw_pgs_get` → `/v1/pgs/computed/{pgs_id}` (line 482) which reads from the `pgs_scores` table (DuckDB, via `service/store.py`).
- The bug: the read returns no row.

**Possible root causes** (hypotheses; investigation will narrow):

1. **Worker writes `done` to `pgs_compute_tasks` but doesn't write the row to `pgs_scores`.** `_real_compute_fn` either short-circuits on a recoverable error, OR the row-write step is decoupled from the dispatch and silently fails.
2. **Race**: worker writes the `pgs_scores` row, then writes `done`, but the writes are to different databases (`pgs_compute_tasks.sqlite` vs `variants.duckdb`) with no shared transaction. If the duckdb write is uncommitted/unfsynced when the sqlite UPDATE lands, the agent's subsequent read could miss it. Unlikely given DuckDB's default WAL behaviour but worth ruling out.
3. **Active-run mismatch**: worker writes to one run's `pgs_scores`, query reads from a different run's `pgs_scores`. Could happen if the `CURRENT` symlink shifts between compute and query, OR if the worker resolves the run-id differently from the query path.
4. **Compute genuinely failed silently**: `pgsc_calc` exits 0 but emits no scoring output; the worker catches no exception and marks `done` without writing a row. The compute happened, the row write didn't, the task status is wrong.
5. **Schema-version filter**: `/v1/pgs/computed/{pgs_id}` filters by some criterion (sample_id, schema_version, ancestry-calibration status) that the worker's written row doesn't satisfy. Row exists but query excludes it.
6. **Cache invalidation between sessions**: the row WAS written for a prior run-id and the active run changed; agent re-triggers compute but the task tracker recognises the prior compute, marks `done` without re-running, and the agent reads against the new run-id which has no row.

## Acceptance Criteria

- [ ] **AC1**: A deterministic, no-LLM reproduction test exists in `packages/toolkit/tests/integration/` that triggers a `genomeclaw_pgs_compute` against a fixture derived run, waits for `status=done`, then queries `/v1/pgs/computed/{pgs_id}` and asserts the row IS present. RED on `main` today, GREEN after the fix.
- [ ] **AC2**: The root cause is documented in a `docs/reports/pgs-compute-ack-without-row-rca.md` brief. Must enumerate which of the 6 hypotheses (or a new one) is the actual cause, with evidence pulled from logs / SQLite + DuckDB inspection / a stack trace.
- [ ] **AC3**: The fix lands as code changes to `pgs_compute_orchestrator.py` and/or the read path in `app.py` / `store.py` / `_real_compute_fn`. Diff is minimal — touches only the divergence point identified in AC2.
- [ ] **AC4**: When the underlying compute fails for an unrecoverable reason (e.g., `pgsc_calc` rc != 0, zero scoring output, ancestry-calibration failure), the task status becomes `failed` with a structured `error_class` + `error_message` (NOT silently `done`-with-no-row). The plugin's `genomeclaw_pgs_compute` response surfaces this so the agent can tell the user "the compute failed because X" instead of "the compute reported done but I can't retrieve a result". (This is the safety-net side of AC2/AC3 — even if we fix the row-write issue, the `done`-without-row state should NEVER be reachable.)
- [ ] **AC5**: Two regression tests in `tests/integration/test_pgs_compute_*` cover: (a) the happy-path compute-then-retrieve round-trip (AC1's positive case); (b) a compute that genuinely fails (mock `_real_compute_fn` to raise) ends in `status=failed` with the right error fields, not `done`.
- [ ] **AC6**: Run the Round-3 verification flow (`docs/reports/demo-2026-05-25-logs/runner_round3.sh`) and confirm both Q3 (T2D PGS000014) and Q5 (Alzheimer's PGS000334) now return a retrievable percentile (or a structured failure message — whichever is the actual truth for those PGSes against the operator's data).

## Applicable Invariants

- **INV-A001** Agent Memory Provenance — the agent currently writes memory notes like "PGS000014 attempted; task done; row not retrievable; risk unknown". After the fix, those notes should carry an actual percentile OR a structured failure reason — never the indeterminate middle state.
- **INV-A003** Agent-Curated Compute Provenance — every `pgs_scores` row carries the agent's `agent_choice_rationale` + `requested_for_question`. If the worker writes a row, those fields must be populated. If the worker doesn't write a row (genuine failure), the failure record must still preserve the rationale + question — the operator audit trail must not be broken by the failure path.
- **INV-R001** Derived Stores Must Stay Rebuildable — a re-run of `pgsc_calc` on the same input + scorefile + version must produce the same `pgs_scores` row (modulo declared non-determinism). If non-determinism exists in the compute, document it.
- **INV-R002** Never Cache a Degenerate Result — a `pgs_compute_tasks` row with `status=done` but no corresponding `pgs_scores` row IS a degenerate cached result. The fix MUST close this state.

## Proposed New Invariants

None expected — `INV-R002` already covers the "degenerate cache" concern; the fix just needs to enforce it for this specific table pair. If during investigation a broader pattern surfaces (e.g., other tables have the same ack-without-row risk), promote a stricter form of `INV-R002` then.

## Technical Requirements

### Source Data Inputs
- A real `pgs_scorefile/` reference layout (already on the operator's drive at `/Volumes/Genome_Work/genomeclaw/reference/pgs_scorefile/`).
- Either the real Nebula VCF (for a true end-to-end reproduction) OR a small synthetic fixture VCF for the unit-test layer. The deterministic reproduction (AC1) should use the synthetic fixture so the test is fast + portable; the AC6 verification uses the real data.

### Derived Outputs
- `pgs_scores` table in `variants.duckdb` — must contain the result row after a successful compute. Schema fields: see `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs_scores.py` (or equivalent).
- `pgs_compute_tasks.sqlite` — task tracker. Must transition `pending → running → {done | failed}` consistently with the actual outcome.

### Schema / Migration Impact
- If the fix requires new columns on `pgs_compute_tasks` (e.g., `error_class`, `error_message`), bump the table's schema version and ship a migration. If columns already exist but aren't populated, no migration needed.

### Pipeline / Workflow Impact
- `pgs_compute_worker_loop` and `_dispatch_compute` / `_real_compute_fn` may need behaviour changes — exact shape depends on the root cause.

### Agent / UX Impact
- Better: the agent gets either a percentile or a structured failure reason. Eliminates the "task done but no result" indeterminate state that's currently confusing both the agent and the user reading the agent's reply.

### External Dependencies
- `pgsc_calc` (Nextflow pipeline) — already pinned. Investigation should NOT require bumping its version.

## Privacy & Safety Considerations

- **Boundary scan**: no new egress. Investigation reads SQLite + DuckDB locally; fix touches the same local pipeline.
- **Default-off remote calls**: n/a.
- **Redaction surface**: the structured failure message must NOT leak sample identifiers or variant coordinates (the existing logs-discipline rule under `INV-P001`).
- **Clinical escalation**: PRS results are framed as research-grade — see `INV-C001` v1.7's PRS-decline pattern. The fix here doesn't change how PRS results are framed, just whether they're retrievable at all.

## Out of Scope

- **Imputation**. `INV-P001` prohibits cloud imputation; the fix must not silently route through one. If the underlying compute legitimately fails because the user's input is too sparse (the `--min_overlap 0.5` floor from `prs-real-data-smoke-research-findings.md`), the failure status should surface that as the error reason, not paper over with imputation.
- **Adding new PGS scorefiles to the catalog**. The two confirmed-failing scorefiles are PGS000014 (T2D, LDpred) and PGS000334 (Alzheimer's). Investigation focuses on the orchestrator, not the catalog.
- **Changing the agent's PRS-selection heuristics**. `INV-A003` covers the agent's choice rationale; not in scope to change what the agent picks, only to make sure when it picks something, it gets a real answer or a real failure.

## Dependencies

- Existing PGS compute worker scaffolding (`packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py`).
- Existing PGS compute integration tests (`tests/integration/test_pgs_compute_worker_*.py` — these exist and pass today, so they don't catch the ack-without-row bug; AC1's new test must reproduce specifically the lifecycle gap they miss).
- A working onboarded `nemoclaw genomeclaw` sandbox + persistent docker-exec path (from the now-completed onboard-persistent-agent-fix plan).

## Open Questions

- [ ] **Q1**: Does the bug reproduce on the synthetic fixture (existing test infra) or only on the operator's real data? The 5 confirmed reproductions are all on real data. If the synthetic-fixture round-trip tests in `test_pgs_compute_worker_integration.py` pass today (they do — those tests are green on `main`), the bug is either (a) data-specific to the real Nebula VCF, (b) scorefile-specific to PGS000014/PGS000334, or (c) reproduces only when the full agent-driven flow runs (not when tests drive the worker directly). Phase 1's first task is to figure out which.
- [ ] **Q2**: Is `_real_compute_fn` actually being called for these computes, or does the orchestrator short-circuit somewhere earlier? Check the `_resolve_compute_enabled()` gate at line 194 — if it returns False in some path, `_noop_compute_fn` runs instead and marks done without writing a row.
- [ ] **Q3**: Does the active run's `pgs_scores` table even have the schema columns the read path expects? Check `variants.duckdb` schema in run `2026-05-24T12-52-11Z-f2dae2` directly: `duckdb /Volumes/Genome_Work/genomeclaw/derived/2026-05-24T12-52-11Z-f2dae2/variants.duckdb "DESCRIBE pgs_scores"`.

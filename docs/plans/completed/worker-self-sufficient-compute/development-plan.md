# Development Plan — Worker self-sufficient compute

**Status**: Active — drafted 2026-05-23
**Spec**: [spec.md](spec.md)
**Branch**: `main` (small focused phases; no separate feature branch)

## Summary

Four phases, ordered design → fetch → containerise → verify. Each phase is one reviewable atomic slice with its own RED → GREEN → REFACTOR cycle. The plan closes the two real-data blockers the post-MVP iteration of agent-prs-compute-fix surfaced: (a) the worker has no access to bcftools/samtools/etc. when the host service runs natively (Phase 3), (b) the agent has no way to trigger scorefile fetches autonomously (Phase 2). Together they enable a real green-percentile compute end-to-end without operator intervention.

## Critical Invariants to Respect

- **INV-D001** — worker reads the user's CRAM read-only; no modification.
- **INV-D002** — sandbox stays bio-binary-free; the toolkit image is where bio binaries live; Phase 3 extends that boundary to the worker.
- **INV-D006** — Phase 3's containerised compute respects `as_sibling_mountable`'s host-form-path checks. The auto-published `GENOMECLAW_HOST_ROOTS` (commit `fa822b3`) keeps working.
- **INV-R001** — `stamp_pgs_row`'s seven-column shape is preserved through any runtime path change.
- **INV-R002** — `_is_degenerate` guard continues to fire before persistence.
- **INV-P001** — PGS Catalog egress is the existing one-time-at-install consent surface; Phase 2's auto-fetch transitively rides that consent. Kill-switch retains hard-stop.
- **INV-A003** — `agent_choice_rationale` + `requested_for_question` continue to land on `pgs_scores` rows regardless of runtime path.

## Proposed New Invariants

None. This plan implements an architectural fix; no new project-wide rules.

## Current State Analysis

### What works today

- Phase 4 worker enqueues + drains tasks correctly. Verified live: tasks reach terminal state in `pgs_compute_tasks.sqlite`.
- The `_real_compute_fn` injection point — `compute_fn` is bound via `functools.partial(_real_compute_fn, config=..., run_dir=...)` at lifespan startup. Phase 3 swaps in a containerised variant without changing the worker loop.
- The `_resolve_scorefile_path` helper (post-fix `d0f9c4e`) checks the canonical `<root>/<pgs>/<pgs>_hmPOS_GRCh38.txt.gz` layout. Phase 2 catches the `PgsScorefileMissingError` it raises.
- The structured error mapper (`_structured_error`) names 6 known failure classes + agent system prompt has the framing table. Phase 2 + Phase 3 add new error classes (`scorefile_unfetchable`, `compute_container_failed`) that slot into the same shape.
- The kill-switch (`GENOMECLAW_PGS_COMPUTE_ENABLED`) gates the worker's claim path. Phase 2 + Phase 3 respect it.
- `bin/genomeclaw-prs-smoke` is the verified-working end-to-end driver: it runs the compute inside the toolkit container against the user's real CRAM. The smoke v23 PASS (4h26m wall) is the proof point that the COMPUTE itself works; the only question is how to invoke it from the host service.

### What's broken

- `_real_compute_fn` calls `compute_prs_with_coverage_fill(...)` from the host service process. That process runs **natively** (via `bin/genomeclaw host)` forcing `GENOMECLAW_NATIVE=1`) — bcftools/samtools/etc. are not on PATH. Every compute fails with `BcftoolsError`.
- The worker has no path to fetch a missing scorefile. The agent can only surface the operator-action command in its reply; the user has to break out of conversation to run a CLI.

### What's already protected

- The agent-side polling pattern (system prompt + structured-failure framing table from commit `7d084e7`) means the agent surfaces ANY new structured error from Phase 2/3 cleanly. We don't have to teach the agent new failure classes — the existing framing covers `compute_container_failed`, `scorefile_unfetchable`, etc.
- INV-D006 + the host-roots auto-publication (commit `fa822b3`) means Phase 3's DooD-spawn path (Option B) doesn't need a separate path-validation refactor.
- The `_dispatch_compute` indirection (Phase 3 of agent-prs-compute-fix) means tests can swap in any compute_fn; Phase 3 of THIS plan ships a new compute_fn (containerised) without disturbing the dispatch shape.

## Solution Design

### Two-layer split

| Layer | Concern | Phase |
|-------|---------|-------|
| **Layer A** — scorefile availability | When compute_fn hits `scorefile_missing`, fetch + retry inline | Phase 2 |
| **Layer B** — runtime tools availability | When compute_fn runs `bcftools/pgsc_calc/etc`, it needs the toolkit image | Phase 3 |

Layer A is composable on top of Layer B (or independently against the existing direct-subprocess path for tests). Layer B is the architectural fix.

### Phase 2 design — inline auto-fetch

`_real_compute_fn` is restructured into a two-step resolve:

```python
async def _real_compute_fn(task, *, config, run_dir):
    scorefile_path = await _ensure_scorefile_staged(
        config.scorefile_root,
        task.pgs_id,
        compute_enabled_fn=...,  # for kill-switch gating of the fetch
    )
    # ... existing path: run_in_executor → compute_prs_with_coverage_fill → stamp_pgs_row
```

Where `_ensure_scorefile_staged` is:

```python
async def _ensure_scorefile_staged(scorefile_root, pgs_id, *, compute_enabled_fn):
    try:
        return _resolve_scorefile_path(scorefile_root, pgs_id)
    except PgsScorefileMissingError:
        if not compute_enabled_fn():
            raise  # kill-switch gates the fetch too
        # Auto-fetch via the existing prep/fetch.py machinery.
        # Synchronous + bounded — wrap in run_in_executor.
        await loop.run_in_executor(None, fetch_pgs_scorefile, pgs_id, scorefile_root)
        return _resolve_scorefile_path(scorefile_root, pgs_id)  # retry
```

The fetch function reuses `prep/fetch.py`'s existing `_http_get` + `_SourceLayout` machinery (the same code the operator's `genomeclaw refs fetch` runs). One new public function: `prep/fetch.py::fetch_pgs_scorefile(pgs_id, scorefile_root)`. Refactored from the existing CLI machinery.

New error classes:
- `PgsScorefileUnfetchableError(pgs_id, reason)` → `failed:scorefile_unfetchable:<pgs_id>:<reason>`

### Phase 3 design — containerised compute (Option A: host service inside the toolkit image)

**Phase 1 decision (2026-05-23)**: Option A — run the host service INSIDE the toolkit image.

The host service's Uvicorn process runs inside `genomeclaw/toolkit:<tag>`. `bin/genomeclaw host service` (currently the `host)` case in `bin/genomeclaw`, which forces `GENOMECLAW_NATIVE=1`) is reworked to issue a `docker run -p 8643:8643 -v <mounts> genomeclaw/toolkit:<tag> uvicorn ...` invocation instead. The `GENOMECLAW_NATIVE=1` override becomes obsolete for the host service path.

**Rationale**: Zero refactor of `compute_prs_with_coverage_fill` — it runs in the environment it was designed for, with bcftools/samtools/pgsc_calc on PATH. The smoke driver (`bin/genomeclaw-prs-smoke`) is already the living proof that the toolkit image can run the Python package end-to-end against real inputs. No new orchestration plumbing is required.

**Dropped alternatives**:
- **Option B (per-compute DooD-spawn)**: per-task docker-run overhead (~2-5s), JSON-envelope plumbing, bind-mount lifecycle complexity — all novel code surfaces on the critical path. Dropped.
- **Option C (persistent container + docker exec)**: persistent container lifecycle management adds failure modes (what if container crashes mid-task?) and more moving parts than A. Dropped.

**Static analysis confirming Option A**:
- `bin/genomeclaw-prs-smoke` already invokes `docker run ... genomeclaw/toolkit:prs-phase5a python -m genomeclaw_toolkit._cli pipeline prs-compute ...` — Option A's pattern is proven.
- Port binding `-p 8643:8643` maps the container's port to the host bridge; sandbox reaches `host.openshell.internal:8643` identically.
- `_publish_host_roots_from_config` in `app.py` sets `GENOMECLAW_HOST_ROOTS` from the sidecar at lifespan startup; covers the DooD path the shim normally handles via `GENOMECLAW_DOOD=1`.

### Phase 3 contract (independent of Option choice)

Whichever option Phase 1 picks, the contract `_real_compute_fn` exposes to the worker loop is unchanged:

```python
async def _real_compute_fn(
    task: PgsComputeTaskFullRow,
    *, config: PrsComputeConfig, run_dir: Path,
) -> None:
    """Runs the compute (via whichever runtime Phase 3 picked) + stamps the row."""
```

The internals shift; the contract stays. This lets Phase 4's live verification be a single AC-driven gate independent of Phase 3's implementation choice.

### Schema / Provenance Impact

- No `pgs_compute_tasks` schema changes.
- No `pgs_scores` schema changes. `stamp_pgs_row` continues to be the persistence shim.
- Phase 2's auto-fetch leaves files at the canonical layout (`<root>/<pgs>/<pgs>_hmPOS_GRCh38.txt.gz`) — same shape `refs fetch` produces.

### Privacy & Egress Impact

- **Phase 2 auto-fetch**: same egress destination, transport, payload as the existing operator-driven `refs fetch`. INV-P001-consented; kill-switch-gated.
- **Phase 3 Option A**: no new egress; the host service binds the same port + same path on `host.openshell.internal`.
- **Phase 3 Option B**: per-compute DooD-spawn opens a new docker-host-socket invocation surface. The shim already mounts `/var/run/docker.sock` for DooD; the host service running natively would need the same. INV-D005 (DooD path identical-bind-mounts) applies.

## Phase Overview

| Phase | Description | Tests | TDD focus |
|-------|-------------|-------|-----------|
| **1** | Investigation + design pass: pick Option A vs B vs C | 0 new tests; just spec.md + design narrative | Documented choice, not code |
| **2** | Inline auto-fetch scorefile + kill-switch gating | 4-6: happy-path fetch + cache-hit no-op + kill-switch gates + retry on transient 5xx + unfetchable maps to structured error | Layer A, no architectural change |
| **3** | Containerised compute (whichever option Phase 1 picked) | 3-5: compute runs against fixture inputs end-to-end + structured-error propagation through the runtime boundary + INV-R001/R002/A003 preservation | Layer B, the architectural fix |
| **4** | End-to-end verification — eyesight question produces a real percentile | 1 live agent test: AMD-question prompt against the canonical run-dir; assert percentile in reply + pgs_scores row stamped | The user-facing outcome |

### Phase 1 — Design pass (no code)

Brief design exploration. Output: a `design-decision.md` (or appendix in dev-plan) recording the picked option + the rejected alternatives with reasoning. Estimated 1-2 hours.

### Phase 2 — Inline auto-fetch

Extract `fetch_pgs_scorefile(pgs_id, scorefile_root) -> Path` into `prep/fetch.py` (public function refactored from the existing CLI's `refs_fetch` handler). Wrap with `_ensure_scorefile_staged(...)` in the worker.

New tests:
- Cache-hit happy path: scorefile already at canonical layout → no fetch attempted.
- Cache-miss happy path: PGS Catalog responds 200 → file lands → second `_resolve_scorefile_path` call succeeds.
- Cache-miss + kill-switch off → `PgsScorefileMissingError` propagates (no fetch attempted).
- Cache-miss + PGS Catalog 404 → `PgsScorefileUnfetchableError` → mapped to `failed:scorefile_unfetchable:<pgs_id>:404`.
- Cache-miss + transient 5xx → retry exponential backoff → success on 3rd attempt.
- Cache-miss + persistent 5xx → exhaust retries → `scorefile_unfetchable:server_unreachable`.

### Phase 3 — Containerised compute

Implementation depends on Phase 1's choice. Common surface:

- `_real_compute_fn` body is restructured to delegate to a new `_runtime_compute(task, config, run_dir)` helper that EITHER:
  - **Option A**: just calls `compute_prs_with_coverage_fill(...)` (the host service is now inside the toolkit image; bcftools is on PATH; nothing to refactor).
  - **Option B**: builds + spawns a `docker run --rm genomeclaw/toolkit:<tag> ...` invocation that runs `prs-compute --json`; parses the JSON envelope into a `PgsRow`.
  - **Option C**: ensures the persistent container is up + runs `docker exec <container> ...` per task.
- `_structured_error` learns to recognise `compute_container_failed:<rc>` for Option B/C.
- The compute_fn signature is unchanged; the worker loop is unchanged.

New tests:
- End-to-end compute against a synthetic minimal input (small CRAM, tiny scorefile) → `PgsRow` returned + degenerate-guard preserved.
- Container exit-non-zero → `compute_container_failed:rc=<N>` structured error.
- (Option B only) work-dir cleanup on `done`; persistence on `failed`.
- INV-A003 plumbing: `rationale` + `requested_for_question` survive the container boundary.
- INV-R001 7 provenance columns: persistence shape unchanged from Phase 4 baseline.

### Phase 4 — Live verification

One new live test: `test_live_agent_eyesight_question_produces_percentile` (or extend the existing `test_live_agent_prs_compute_e2e.py`).

- Stages the canonical Phase 7 run-dir.
- Stages `prs_compute_config.json` sidecar (already in place from agent-prs-compute-fix iteration).
- Does NOT pre-stage PGS000137 glaucoma scorefile (tests the auto-fetch path).
- DOES pre-stage PGS004606 AMD scorefile (tests the no-auto-fetch happy path for one compute).
- Runs the agent against `"Do I have any risk factors for loss of eyesight?"`.
- Asserts:
  - Reply contains a numeric percentile (`/\d+(?:\.\d+)?\s*(?:st|nd|rd|th|%)?\s*percentile/i`)
  - Reply does NOT contain `scorefile_missing` or `BcftoolsError` or `HTTP 422`
  - `pgs_scores` table has at least one new row with non-null `percentile_in_user_ancestry`
  - The row carries the seven INV-R001 columns + INV-A003 rationale

Wall time: 30-60 min (real pgsc_calc + PGS Catalog fetch). Gated on the existing `live_llm` marker.

## Testing Strategy

### Unit + Integration (per phase)

- **Phase 2**: `tests/integration/test_pgs_compute_scorefile_autofetch.py` — 6 tests.
- **Phase 3 (Option A)**: `tests/integration/test_host_service_toolkit_image.py` — 3-4 tests verifying the containerised host service still serves all routes + the worker runs `bcftools --version` successfully via the in-image PATH.
- **Phase 3 (Option B)**: `tests/integration/test_worker_dood_spawn.py` — 5 tests covering the docker-run invocation shape + JSON-envelope parsing + structured-error mapping.
- **Phase 4**: extends `test_live_agent_prs_compute_e2e.py`.

### Determinism / Provenance / Privacy / Evidence-binding / Report

- INV-R001 provenance: Phase 3 verification asserts the persisted row carries all seven columns regardless of runtime path.
- INV-R002 degenerate-result guard: covered by Phase 3's degenerate-fixture test.
- INV-P001 privacy default: Phase 2 kill-switch test confirms no PGS Catalog egress under kill-switch.

### Real-data smoke (Phase 4)

Same as the existing Phase 4 of agent-prs-compute-fix's spec: a live `live_llm`-marked test against the canonical run-dir. Gated on `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE` + (new) `GENOMECLAW_TOOLKIT_IMAGE`.

## Documentation Updates Required

- `docs/reference/architecture.md` — host service section's diagram + narrative updated to reflect the Phase 3 runtime choice.
- `docs/reference/INVARIANTS.md` — possibly a one-line note on INV-D002 if Phase 3 lands Option A (the host service now runs inside the toolkit image, which is an in-scope clarification).
- This plan's `work-notes.md` — design-pass outcome, per-phase implementation notes, Phase 4 live-run outcome.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 — Design pass | Complete | 2026-05-23 | 2026-05-23 | Option A chosen; work-notes.md carries the rationale |
| 2 — Inline auto-fetch | Complete | 2026-05-23 | 2026-05-23 | 8 tests; fetch_pgs_scorefile + _ensure_scorefile_staged |
| 3 — Containerised compute | **Complete** | 2026-05-23 | 2026-05-23 | Option A shipped: `bin/genomeclaw host service` wraps in `docker run -p 8643:8643 --host 0.0.0.0`; toolkit image rebuilt as `worker-self-sufficient`; bcftools verified on PATH; PGS004606 compute reached `running` live against canonical CRAM. 5/5 Phase 3 tests pass (3 host-runnable + 2 image-gated). |
| 4 — Live verification | Pending | | | The user-facing AC1 gate |

# Work Notes — Worker self-sufficient compute

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored

**Trigger**: 2026-05-23 post-iteration on agent-prs-compute-fix surfaced two real blockers preventing a green-percentile compute against the canonical run-dir:

1. `worker_unexpected_error:BcftoolsError` — the host service's worker runs in a process where bcftools isn't on PATH. The shim's `host)` case forces `GENOMECLAW_NATIVE=1` so the host service is native (no toolkit container), but bcftools/samtools/htslib lives ONLY in the toolkit image.
2. The agent's reply has to surface "operator should run `genomeclaw refs fetch --source pgs_scorefile --release PGS<id>`" because the worker has no path to auto-fetch missing scorefiles.

**User direction (2026-05-23)**:
- *"GenomeClaw agent should be authorized to do this without operator intervention"* — re scorefile fetch.
- *"Please first check if [DooD-managed toolkit container] is not already done"* — verified NOT done; the prep/ subprocess calls invoke bcftools directly with no docker wrapper.
- *"Consolidate this and bcftools-on-host-or-dood into one or many new phased follow-up plans"* — bundled into ONE plan (`worker-self-sufficient-compute`) because Layer A (auto-fetch) alone has zero observable value without Layer B (runtime tools available).

**Applicable Invariants** (per spec):
- INV-D001, D002, D006, R001, R002, P001, A003, C001 v1.7.
- No new INV-xxx proposed.

**Plan structure**: 4 phases.
1. Design pass — pick runtime architecture (Option A / B / C).
2. Inline auto-fetch missing scorefiles + kill-switch gating (~6-8 tests).
3. Containerised compute (whichever option Phase 1 picked) (~5 tests).
4. Live verification — eyesight question produces real percentile.

**Default recommendation for Phase 1**: Option A (host service inside the toolkit image) because:
- It's how the architecture doc already frames the toolkit image (the bio-tools integration point per `architecture.md:282`).
- The `bin/genomeclaw-prs-smoke` smoke v23 PASS proves the compute works in that environment.
- Zero refactor of `compute_prs_with_coverage_fill` — it runs in the environment it's designed for.
- Simplest dependency story.

Trade-off: heavyweight (6.4 GB image holds the host service too). Acceptable for the personal-host envelope.

**Next step**: surface the plan to the user for sign-off. Phase 1 starts after sign-off — it's a brief design exploration with at most one smoke-test invocation; output is a documented decision in this work-notes file.

---

## 2026-05-23 — Phase 1 design pass

**Context reviewed**: spec.md, development-plan.md, phase-1.md, phase-2.md, bin/genomeclaw-prs-smoke, bin/genomeclaw (host) case), packages/toolkit/src/genomeclaw_toolkit/service/app.py, packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py.

**Static analysis findings**:

1. `bin/genomeclaw-prs-smoke` proves Option A pattern: it invokes `docker run ... genomeclaw/toolkit:prs-phase5a python -m genomeclaw_toolkit._cli pipeline prs-compute ...`. The toolkit image already knows how to run the Python package; the host service is just `uvicorn` + the same package. Option A is plumbing-proven.

2. `GENOMECLAW_NATIVE=1` grep across the codebase: set in `bin/genomeclaw host)` case (read-only shim, not modified here), referenced in `docs/reference/architecture.md`, `docs/plans/completed/` (historical notes), and this plan's work-notes. Option A renders the `host)` case's `GENOMECLAW_NATIVE=1` override obsolete — the Phase 3 shim rework will swap it for a `docker run -p 8643:8643 ...` invocation. No other active code-path depends on it being native; confirmed by grep.

3. Port-exposure: `docker run -p 8643:8643` maps the toolkit container's port to the host bridge. The sandbox reaches `host.openshell.internal:8643` the same way it does today. No change to AC6.

4. `_publish_host_roots_from_config` in `app.py` sets `GENOMECLAW_HOST_ROOTS` from the sidecar. Inside the toolkit image, the shim's `GENOMECLAW_DOOD=1` path normally does this; running the service inside the image, this same `app.py` helper fires at lifespan startup and covers the same need. The DooD path is already tested independently.

5. Cost of rebuilds: Phase 3 bakes the host service into the toolkit image. A service patch needs an image rebuild. Acceptable for a personal-host envelope — image rebuilds are already the norm for toolkit changes. The smoke driver is the rebuild trigger.

6. Options B and C were not smoke-tested (the task instructions explicitly restrict docker smoke tests for Phase 1). The static analysis is sufficient to confirm A.

**Decision**: **Option A — run the host service INSIDE the toolkit image.**

Rationale (3 sentences): Zero refactor of `compute_prs_with_coverage_fill` — the function runs in the environment it was designed for, with bcftools/samtools/pgsc_calc on PATH. The smoke driver (`bin/genomeclaw-prs-smoke`) is already the living proof that the toolkit image can run the Python package end-to-end against real inputs. No new code surface is required: Phase 3 is a shim rework, not a new orchestration layer.

Dropped alternatives:
- **Option B (per-compute DooD-spawn)**: adds per-task docker-run invocation overhead (~2-5s cold-start per compute), JSON-envelope plumbing between host and container, and bind-mount lifecycle complexity — all novel code surfaces on the critical path. Dropped.
- **Option C (persistent container + docker exec)**: same docker dependency as B plus persistent container lifecycle management (what happens if the container crashes mid-task?). More moving parts than A or B. Dropped.

**Phase 2 work**: begun in this same session (see below).

---

## 2026-05-23 — Phase 2 implementation

**Objective**: inline auto-fetch missing scorefiles + kill-switch gating + 8 tests.

**Applicable Invariants**: INV-P001 (kill-switch gates the fetch; no PGS Catalog egress under kill-switch), INV-D006 (fetched scorefile lands at canonical layout).

**Design decisions**:
- `fetch_pgs_scorefile` reuses `_http_get` + the URL template from `_LAYOUTS["pgs_scorefile"]` directly (no call to the heavyweight `fetch()` orchestrator, which requires a writable reference root + the `preflight.assert_reference_writable()` guard and raises `VersionAlreadyExists` on a cache hit rather than returning the path). The new function does its own idempotency check + streaming.
- `PgsScorefileUnfetchableError` added to `pgs_compute_orchestrator.py` alongside the existing `PgsScorefileMissingError`. The two are sister errors: `Missing` = "not in cache yet"; `Unfetchable` = "tried to fetch, couldn't".
- Retry policy: 3 attempts, exponential backoff (1s, 4s, 16s), matching the spec's recommendation. `time.sleep` is the sleep surface — tests mock it to avoid actual wall-clock waits.
- `_ensure_scorefile_staged` catches `PgsScorefileMissingError`, gates on the kill-switch, fires `fetch_pgs_scorefile` via `loop.run_in_executor(None, ...)`, then retries `_resolve_scorefile_path`. Logs structured INFO records on fetch start/done.
- `app.py` lifespan: `compute_enabled_fn` threaded through via `functools.partial` binding — the function re-reads the kill-switch at decision time (not at startup).
- Agent system prompt: new row for `scorefile_unfetchable:<pgs_id>:<reason>` added to the failure-mapping table.

**Files modified**: `prep/fetch.py`, `service/pgs_compute_orchestrator.py`, `service/app.py`, `nemoclaw-plugin/sandbox/agent-system-prompt.md`.
**New file**: `tests/integration/test_pgs_compute_scorefile_autofetch.py` (8 tests).

---

## Open follow-ups deferred to OTHER plans (not in scope here)

- **`openclaw-toolcall-serialization`** — the agent occasionally POSTs `call_xxx|fc_yyy` as a bare-string body instead of a JSON args object. The plugin's runtime arg-guard (commit `b8b7954`) catches this locally + returns a clean error, but the upstream openclaw runtime serializer is the real fix. Out of scope; file separately if it persists.
- **AC8 coverage_qc / gene-list BED** — orthogonal MVP Phase 7 carry-forward.
- **Scoring-weight version awareness / cache invalidation** — Phase 2's auto-fetch doesn't re-fetch on a cache hit even if PGS Catalog updated the scoring weights. Future plan.
- **Multi-sample / concurrency cap > 1** — out of scope; current 1-in-flight cap holds.

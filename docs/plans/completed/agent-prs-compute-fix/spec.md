# Spec — Agent PRS compute path end-to-end (E.3 worker implementation)

**Status**: Active — re-scoped 2026-05-23 (Phase 1 discovery surfaced that the E.3 worker doesn't exist)
**Created**: 2026-05-23 (post-MVP)
**Companion to**: [docs/plans/completed/prs-bootstrap-meta.md](../../completed/prs-bootstrap-meta.md), [docs/plans/completed/mvp/phases/phase-7.md](../../completed/mvp/phases/phase-7.md)

---

## Goal

Implement the **end-to-end agent-driven PRS compute path** the MVP architecture documented but never actually built. The agent invokes `genomeclaw_pgs_compute` → host service validates + enqueues → background worker drains the queue → `pgsc_calc` runs → result persists to `pgs_scores` + `findings` → agent polls + sees the result. No operator intervention.

## Background

The 2026-05-23 AMD-question agent invocation against the canonical Phase 7 run-dir hit ``HTTP 422`` on `POST /v1/pgs/compute`. Phase 1's RED test reproduced the failure: a 41-char agent-typical rationale gets rejected by the host service's Pydantic `rationale: minLength=50` gate. That's the surface bug.

Phase 1.3 surfaced a much deeper issue: **the host service's PGS compute orchestrator is a stub**. The module's own docstring is explicit ("E.1 stubs the worker; the row sits at `queued` indefinitely until the E.3 background loop drains it"); a grep confirmed there's no worker loop anywhere in the toolkit that drains the `pgs_compute_tasks` SQLite queue. The actual failure flow:

```
agent.genomeclaw_pgs_compute → POST /v1/pgs/compute
   if Pydantic FAIL (today)    : 422 (clear error, agent degrades cleanly)
   if Pydantic PASS (post-fix) : enqueue queued task → 202 → ??? → queued forever
```

The HTTP 422 was actually the **best possible outcome of the broken path** — a clear error the agent could degrade on. If the rationale had been ≥50 chars, the agent would have polled `genomeclaw_pgs_compute_status` indefinitely.

The prs-bootstrap-meta cascade's `bin/genomeclaw-prs-smoke` driver DOES work end-to-end (smoke v23 PASS verified that). It's a host-side shell script that drives `prs-compute` (Tier 1 + Tier 2 + merge + pgsc_calc). The fix is to embed that same algorithm in a proper background worker loop inside the host service so the agent sees results in the same conversation without operator intervention.

The MVP's promised "agent-driven, host-computed, memory-cached" architecture per Q8 v1.6 + the [agent-driven PRS report](../../../reports/agent-driven-prs-computation.md) requires this worker. Without it, the agent's PRS surface is non-functional.

## Acceptance Criteria

- [ ] **AC1**: Phase 1's RED test (`test_pgs_compute_accepts_agent_short_rationale`) turns GREEN — agent-typical short rationales (10-49 chars) are accepted by the host service. INV-A003's non-empty-rationale floor is preserved (empty string still 422'd).
- [ ] **AC2**: A background worker drains `pgs_compute_tasks.sqlite` automatically when the host service is running. Tasks transition `queued → running → done | failed` without operator intervention. Concurrency cap = 1 in-flight (per the Q8 v1.6 design).
- [ ] **AC3**: The worker invokes the same Tier 1 + Tier 2 + merge + pgsc_calc algorithm that `bin/genomeclaw-prs-smoke` uses, OR the equivalent `compute_prs_with_coverage_fill(...)` function, against the active run's CRAM. F4 chrX-needs-sex is handled by the Tier 1/Tier 2 force-genotype upstream filter (not a chrX-strip post-hoc patch).
- [ ] **AC4**: On compute success the worker persists a `pgs_scores` row + matching `clinical-non-actionable` `findings` row (per the post-v23 `prs-compute --run-dir` wiring), with INV-A003 `agent_choice_rationale` + `requested_for_question` columns + the seven INV-R001 provenance columns.
- [ ] **AC5**: Kill-switch (`pgs.compute_enabled false`) immediately rejects new compute requests with `status=failed` + `error=compute_path_disabled`. Worker also re-checks the kill-switch at the start of each task it claims.
- [ ] **AC6**: Crash recovery — if the host service restarts while a task is in `running` status, that task transitions to `failed` with `error=worker_restart` (or similar) on the next worker startup. Stale-running cleanup window is configurable; default 1 hour.
- [ ] **AC7**: End-to-end agent live test — `test_live_agent_prs_compute_e2e.py` runs the AMD-question scenario against the canonical run-dir; the agent invokes `genomeclaw_pgs_compute`, polls `_status` until done, fetches via `_get`, and surfaces a PRS percentile in the reply. No HTTP 422; no infinite `queued`.

## Applicable Invariants

- **INV-A003** (Agent-Curated Compute Provenance) — preserved through Phase 2's threshold fix. The non-empty-rationale floor stays; only the 50-char gate is relaxed.
- **INV-A001** (Memory note before reply) — the worker doesn't touch agent memory directly; the agent writes the memory note after polling the result.
- **INV-P001** (Privacy Default) — no new egress surfaces. PGS Catalog scoring-weights fetch is already opt-in + happens at `refs fetch` time, not at compute time. The kill-switch gives the user a hard-stop.
- **INV-R001** (Rebuildability) — `pgs_scores` rows carry the seven canonical provenance columns. The worker invokes the same compute path as `bin/genomeclaw-prs-smoke`, so determinism semantics match smoke v23.
- **INV-R002** (Never Cache a Degenerate Result) — the worker must not write a `pgs_scores` row for a degenerate compute (e.g. zero-overlap between user variants + scorefile). It should transition the task to `failed` with a clear error.
- **INV-C001** v1.7 (PRS-decline pattern) — the worker doesn't override the agent's decline pattern. The agent decides whether to enqueue at all; the worker just drains. If the agent decides the literature is immature, no compute request is sent.

## Proposed New Invariants

None expected. The plan implements what the architecture already documented; no new project-wide rules.

## Out of Scope

- **Multi-sample compute** — the worker handles one sample at a time (the canonical run's active sample per the `CURRENT` symlink). Multi-sample support is a follow-up.
- **Scorefile auto-fetch at compute time** — if the requested PGS ID isn't pre-staged, the worker fails with `error=scorefile_missing` + `error_hint=<refs fetch command>`. Auto-fetch is a follow-up convenience.
- **Larger agent system-prompt changes** beyond a possible "rationale below 50 chars is now accepted but still recommended to be ≥50 chars for INV-A003 alternatives-considered framing" reminder.
- **AC8 coverage_qc / gene-list BED** — orthogonal; tracked as a separate Phase 7 carry-forward.
- **Full Landlock+seccomp+netns SSRF probe** — orthogonal.
- **Concurrency cap > 1** — the design pins 1-in-flight per Q8 v1.6 + the kill-switch + the personal-host envelope. Multi-worker is a post-MVP feature.

## Privacy & Safety Considerations

**Egress**: no new surfaces. PGS Catalog scoring-weights are fetched via the existing `refs fetch --source pgs_scorefile` opt-in path, not by the worker. The worker reads pre-staged scoring weights from disk.

**Kill-switch**: the user retains the hard-stop via `pgs.compute_enabled false`. With the kill-switch on, the host service rejects new requests + the worker skips draining. AC5 covers the contract.

**Resource consumption**: each PRS compute takes ~10-90 min wall + significant CPU + I/O. The 1-in-flight concurrency cap prevents resource exhaustion. The worker's start/finish events should be observable (logged) so the operator can confirm the worker isn't running away.

**No phenotype-linked content** crosses any new boundary. The worker reads the user's VCF (local), uses pre-staged reference data (local), writes results to the local derived store.

No `privacy-safety-reviewer` agent invocation strictly required by this scope, but a light review of the AC5 kill-switch + AC6 crash-recovery error surface is good practice. Will request review after Phase 5 lands.

## Open Questions

1. **Worker process model** — Phase 3 design pass. Recommended: in-process `asyncio` task started on FastAPI startup. Trade-offs vs separate-worker-process documented in Phase 3.
2. **Compute path** — Phase 3 design pass. Recommended: invoke `compute_prs_with_coverage_fill(...)` (the Tier 1 + Tier 2 + merge function that `prs-compute` CLI + smoke driver both wrap). Handles chrX automatically via Tier 1 force-genotype; benefits from Tier 1 cache.
3. **Discovery of compute inputs** — the worker needs the sample's CRAM path, reference root, scorefile path, etc. These are baked into `bin/genomeclaw-prs-smoke` as env vars; the host service would need either a config file in the run-dir OR config-via-env at startup OR config-via-API. Phase 3 design pass picks a shape.
4. **Stale-running cleanup window** — Phase 5 design pass. Recommended: 1 hour default (a real compute takes ≤90 min in the worst case + 1 hour gives the worker a generous safety margin), configurable via env var.
5. **Worker error reporting** — what error string goes in the `pgs_compute_tasks.error` column? Recommended: structured `<error_class>:<short_description>` (e.g. `scorefile_missing:PGS004606`, `pgsc_calc_failed:rc=1`, `worker_restart:stale_running`).

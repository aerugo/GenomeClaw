# Work Notes — Agent PRS compute path fix

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored

**Trigger**: AMD-question agent invocation (run via the live-smoke harness against the canonical Phase 7 run-dir, 4m16s wall, status=ok). The agent invoked `genomeclaw_pgs_compute` twice — once for PGS004606 (AMD) + once for PGS000137 (glaucoma). Both returned `HTTP 422`. Agent gracefully degraded ("the PRS compute attempts failed with HTTP 422, so I don't have a percentile for you yet"), correct calibration on the agent side but broken capability on the host side.

**Applicable Invariants**:
- INV-A003 (agent-curated compute provenance — preserved through the fix)
- INV-P001 (no new egress)
- INV-R001 (seven provenance columns)
- INV-C001 v1.7 (PRS-decline pattern intact)

**Two stacked hypotheses for the 422**:
1. **Validation rejection** — host service's `PgsComputeRequest` Pydantic model has `rationale: minLength=50`. Agent's auto-generated rationale may be shorter; would land as 422 before any subprocess.
2. **Orchestrator-level F4 chrX-needs-sex** — the host service's PGS compute orchestrator calls `compute_pgs(...)` (which doesn't strip chrX from the input). The canonical agent path uses `prs-compute` (Tier 1/Tier 2 force-genotype + merge) which handles chrX. If the orchestrator uses the simpler path, every PGS Catalog scorefile that includes chrX (PGS000018, PGS004606, PGS000137, etc.) will fail.

**Investigation-first**: Phase 1 reproduces each failure mode as a typed test BEFORE any fix lands. The plan is RED-heavy in Phase 1 because there are multiple plausible root causes stacked + we don't want to fix the wrong one.

**Next Step**: User sign-off on the plan structure (or counter-proposal), then Phase 1.1 starts by parsing the 2026-05-23 trace blob for the actual agent rationale + error body shape.

---

## 2026-05-23 — Phase 1.2 RED + a critical discovery

### Step 1.2 RED test landed

[`test_pgs_compute_request_validation.py`](../../../packages/toolkit/tests/integration/test_pgs_compute_request_validation.py) — 5 tests, 1 RED-for-the-right-reason + 4 sanity-check PASSes:

- `test_pgs_compute_accepts_agent_short_rationale` — **RED**: a 41-char agent-typical rationale gets 422 with body `{"detail":[{"type":"string_too_short","loc":["body","rationale"],"msg":"String should have at least 50 characters","input":"Canonical AMD PRS; smoker-relevant trait.","ctx":{"min_length":50}}]}`. This is the exact failure shape the 2026-05-23 AMD-question agent invocation hit.
- `test_pgs_compute_still_rejects_empty_rationale_after_fix` — PASS (rationale="" still rejected; INV-A003 non-empty floor preserved).
- `test_pgs_compute_long_rationale_still_accepted` — PASS (regression guard on the happy path).
- `test_pgs_compute_rejects_extra_fields` — PASS (`extra="forbid"` works).
- `test_pgs_compute_42_char_rationale_currently_rejected_documents_threshold` — PASS (49 chars → 422; documents the boundary).

Axis A confirmed: lowering the threshold (or swapping to soft-warn) is sufficient to address the rationale gate.

### Major discovery — the orchestrator's background worker doesn't exist

Reading [service/pgs_compute_orchestrator.py](../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py) reveals the orchestrator is a **stub**, not the full E.3 worker the prs-bootstrap-meta cascade documentation claimed had shipped. The module's own docstring is explicit:

> E.1 ships the stubbed pieces: the `pgs_compute_tasks.sqlite` schema + `enqueue_pgs_compute_task` + `query_pgs_compute_task_status`. Sub-slice E.3 fills in the background worker loop, the concurrency cap enforcement, and the kill-switch.

And inside `enqueue_pgs_compute_task`:

> E.1 stubs the worker; the row sits at `queued` indefinitely until the E.3 background loop drains it.

**Confirmation via grep**: there is NO worker loop that drains the `pgs_compute_tasks` SQLite queue anywhere in the toolkit. `queued` → `running` → `done` transitions never happen.

So the actual failure flow for the agent's compute request:

```
agent.genomeclaw_pgs_compute → plugin.safePost → POST /v1/pgs/compute
                                                  ↓
                                Pydantic validates `rationale ≥ 50 chars`
                                                  ↓
                                  if FAIL (today) → 422 (clear error)
                                  if PASS (future) → enqueue queued task → 202
                                                  ↓
                                            (then what?)
                                                  ↓
                                      NOTHING — no worker drains the queue
                                                  ↓
                                  agent polls genomeclaw_pgs_compute_status
                                                  ↓
                                  status=queued FOREVER, eventually agent times out
```

The 422 we observed is actually the **best possible outcome of the broken path** — it's a clear error the agent can degrade on. If the rationale had been ≥50 chars, the agent would have gotten a 202 + task_id + then watched it stay at `queued` indefinitely.

### Implications for the plan

The original plan was scoped around two axes (validation + chrX handling). The real fix is significantly larger:

1. **Axis A (validation)** — lower `rationale` minLength threshold OR swap to soft-warn. ✓ already scoped.
2. **NEW: Background worker** — implement what E.3 was supposed to deliver. The worker has to:
   - Poll `pgs_compute_tasks.sqlite` for `queued` rows
   - Transition queued → running atomically (avoid double-processing under concurrent workers)
   - Enforce concurrency cap (1 in-flight per the design)
   - Call the actual compute (likely `prs-compute`-style Tier 1/Tier 2 force-genotype + pgsc_calc OR `compute_pgs`-style simpler path)
   - Persist the result row to `pgs_scores` + matching `findings` row
   - Transition running → done | failed with appropriate error string
   - Respect the kill-switch (`pgs.compute_enabled false` → reject with `compute_path_disabled`)
3. **Axis B (chrX handling)** — folded into the worker's compute-path choice. If the worker uses `prs-compute`'s Tier 1/Tier 2 path, chrX is automatically handled by the force-genotype step. If it uses `compute_pgs`, we need to add an explicit chrX-strip pre-flight.

### Operational question for user

The prs-bootstrap-meta cascade's smoke driver `bin/genomeclaw-prs-smoke` exists + actually works end-to-end (smoke v23 PASS). It's a host-side shell script that drives `prs-compute` against a sample/PGS combination. One legitimate design path is:

> **The host service's `POST /v1/pgs/compute` enqueues but doesn't drain. The operator (the project owner) drains queued requests by running `bin/genomeclaw-prs-smoke <SAMPLE> <PGS>` manually. The agent polls + sees the result once the operator has run the driver.**

This is the "documented two-step" interpretation — the agent triggers, the operator drains. It matches what the cascade actually shipped + minimizes additional code.

The alternative interpretation:

> **The host service must drain queued requests automatically. The compute happens in-service; the agent gets a result without operator intervention.**

This is the "agent-driven end-to-end" interpretation that the MVP architecture's prose described but the code never implemented.

The two interpretations have very different fix sizes:

- **Two-step**: ~2 hours of work. Lower the validation threshold; document the operator-drain step in the agent system prompt ("when you enqueue a compute, tell the user 'I've requested a PRS compute; ask the operator to run `bin/genomeclaw-prs-smoke MPNRGLQ2K <PGS_ID>` to process it'"). Add a test that verifies the documented flow works.
- **End-to-end worker**: ~1-2 days of work. Implement the E.3 background worker properly (concurrency cap + kill-switch + Tier 1/Tier 2 + result persistence + error handling). This is a substantial new feature, not a bug fix.

The plan I authored 30 min ago assumed Axis B was a small chrX-strip patch. The reality is Axis B is "implement the background worker that was never built". That's a different scope conversation.

**Pausing for user direction**: which interpretation should we pursue?

- (a) **Two-step** — lower the validation threshold + update the agent system prompt to tell the user about the manual drain step. Cheap, honest about the architecture's current shape.
- (b) **End-to-end worker** — implement E.3 properly. Substantial new work, matches the MVP's promised architecture.
- (c) **Hybrid** — lower the validation threshold + add a synchronous fallback handler that runs `compute_pgs` inline when the request comes in (no worker, just direct invocation). Trades async semantics for working capability. Some-where in between.

---

## 2026-05-23 — User chose Option B; full design pass complete

### Decision recorded

User: **"B. Plan it carefully accordiong to planning protocols"** → implement the E.3 background worker properly per the MVP's promised architecture. Two-step (a) is rejected because it leaves the agent dependent on operator intervention every PRS query, defeating the agent-driven design. Hybrid (c) is rejected because the inline-`compute_pgs` path doesn't handle chrX (F4) + can't enforce the concurrency cap + blocks the FastAPI event loop for ~10-90 min per compute.

### Plan re-structured per protocol

Per [docs/plans/CLAUDE.md](../../CLAUDE.md), a substantive plan needs spec + dev-plan + phase plans + work-notes. The plan now has all six surfaces:

- [spec.md](spec.md) — re-scoped 2026-05-23 to E.3 worker implementation. 7 ACs (AC1: validation fix; AC2: drain automatically; AC3: real compute via `compute_prs_with_coverage_fill`; AC4: persist `pgs_scores` + `findings`; AC5: kill-switch; AC6: crash recovery; AC7: live agent E2E).
- [development-plan.md](development-plan.md) — 6-phase structure, ordered investigate → validation-fix → worker-skeleton → worker-compute → worker-hardening → e2e-verify. Each phase is one reviewable atomic slice.
- [phases/phase-1.md](phases/phase-1.md) — marked **Complete** (this session's RED + discovery work).
- [phases/phase-2.md](phases/phase-2.md) — authored (one-line `min_length=10` change + plugin TypeBox sync + boundary tests).
- [phases/phase-3.md](phases/phase-3.md) — authored (worker skeleton: 8 tests around atomic claim, concurrency cap, kill-switch; no real compute yet).
- [phases/phase-4.md](phases/phase-4.md) — authored (compute integration: 13 tests around `compute_prs_with_coverage_fill` plumbing, `pgs_scores` + `findings` persistence, INV-R001 / R002 / A003, structured error mapping, sidecar config loader).
- [phases/phase-5.md](phases/phase-5.md) — authored (crash recovery + observability: 9 tests around stale-running cleanup + INFO/WARNING log lines).
- [phases/phase-6.md](phases/phase-6.md) — authored (E2E verification: 4 live-agent test cases against the AMD-question prompt; gated on `GENOMECLAW_LIVE_TESTS=1`).

### Key design decisions (recorded for future contributors)

1. **Worker process model**: in-process `asyncio.create_task` spawned in FastAPI's `lifespan` context manager. Rejected alternatives: separate subprocess (IPC overhead, more moving parts), systemd-style external worker (no deployment infra). Personal-host envelope + 1-in-flight concurrency cap make in-process the right shape.
2. **Compute path**: `compute_prs_with_coverage_fill(...)` — the same Tier 1 + Tier 2 + merge + pgsc_calc function `prs-compute` CLI wraps + `bin/genomeclaw-prs-smoke` drove to smoke v23 PASS. Handles chrX (F4) automatically via Tier 1 force-genotype; benefits from per-sample Tier 1 cache. Rejected: the simpler `compute_pgs` path would need an explicit chrX-strip patch + miss the warm-cache benefit.
3. **Blocking-call handling**: `loop.run_in_executor(None, lambda: ...)` offloads the blocking compute to the default ThreadPoolExecutor. Concurrency cap = 1 (via module-level `asyncio.Lock`) means the ThreadPool size is irrelevant for correctness.
4. **Atomic claim**: `UPDATE pgs_compute_tasks SET status='running' WHERE task_id=(...) AND status='queued' RETURNING ...`. Single-row LIMIT + RETURNING clause (SQLite 3.35+, ships with Python 3.11+). Guards against concurrent-worker double-claims even though the module-level lock makes this scenario impossible in normal operation; defense-in-depth.
5. **Input discovery**: `prs_compute_config.json` sidecar in the active run-dir. One-time-per-deployment configuration. Rejected alternatives: env vars (operator-error-prone for the ~10 required paths), API-driven config (adds a new route + state). The sidecar is host-form (per from-scratch-setup-protections INV-D006 discipline).
6. **Stale-running window**: 1 hour default, env-configurable via `GENOMECLAW_PGS_STALE_RUNNING_WINDOW_S`. Wall-clock rationale: warm-cache compute ≤30 min; cold-cache ≤2 h. 1 h is above warm-cache budget + below cold-cache budget. First cold compute on a fresh deployment needs the env override (`14400` for 4 h).
7. **Kill-switch claim-then-fail vs skip**: with `pgs.compute_enabled=false`, the worker still atomically *claims* the queued row + immediately fails it with `compute_path_disabled`. Reason: a skipped row would sit at `queued` forever; the agent's polling would never surface the rejection. Claim-then-fail makes the kill-switch *observable*.
8. **Error mapping**: structured `failed:<class>:<message>` shapes for the five known failure modes (`scorefile_missing`, `pgsc_calc_failed`, `dood_path_error`, `prs_decline`, `degenerate_result`), plus a `worker_unexpected_error:<ExceptionClass>` catch-all. The agent's `error_hint` per-class gives the user the right next-step.
9. **INV-R002 guard**: `pgs_variant_count == 0` OR `score is None` → no `pgs_scores` row stamped; task is `failed:degenerate_result:<detail>`. Prevents caching a zero-overlap compute as a "result" the agent might later treat as authoritative.
10. **No new invariants promoted**. The plan implements what `INVARIANTS.md` already specifies (INV-A003, R001, R002 plumbing). No `INVARIANTS.md` edit required.

### Test count summary across phases

| Phase | New tests | File |
|-------|-----------|------|
| 1 | 5 (validation) | `test_pgs_compute_request_validation.py` (DONE) |
| 2 | +2 boundary tests (9 chars, 10 chars) | extends Phase 1's file |
| 3 | 8 (worker skeleton) | `test_pgs_compute_worker_skeleton.py` |
| 4 | 9 (compute integration) + 4 (config loader) | `test_pgs_compute_worker_integration.py` + `test_pgs_compute_config_loader.py` |
| 5 | 9 (recovery + observability) | `test_pgs_compute_worker_recovery.py` |
| 6 | 4 (live agent E2E) | `test_live_agent_prs_compute_e2e.py` |
| **Total new** | **~41** | |

### What stays unchanged

- `INVARIANTS.md` — no new invariants.
- The plugin's 4 PGS tools (`genomeclaw_pgs_list` / `_get` / `_compute` / `_compute_status`) — already work; only the rationale minLength changes in `index.ts` (Phase 2 Step 2.3).
- The CLI compute path (`genomeclaw pipeline prs-compute --run-dir ...`) — untouched; the worker calls the same underlying `compute_prs_with_coverage_fill(...)` function.
- `bin/genomeclaw-prs-smoke` driver — untouched; the operator can still drive computes manually if they prefer (e.g. for batch runs).

### Out-of-scope items deferred

Tracked here so they don't get lost:

- Scorefile auto-fetch at compute time (worker surfaces `scorefile_missing:PGS<id>` + the operator runs `genomeclaw refs fetch`).
- Multi-sample compute (worker handles one CURRENT-symlink sample at a time).
- Operator CLI for inspecting the task DB (`genomeclaw pgs tasks ls`).
- AC8 coverage_qc / gene-list BED (orthogonal; tracked as Phase 7 carry-forward in the MVP-closed plan).
- Larger agent system-prompt changes beyond the optional Phase 2 Step 2.4 reminder.

### Next step

**Surface the plan to the user for sign-off before any Phase 2 code lands.** The protocol's #1 non-negotiable is "Plan before you mutate" — Phase 1 reproduced the bug, but the actual fix (Phases 2-6) needs user agreement on the scope before implementation starts. Once signed off, Phase 2 is a quick win (~20 min: one-line change + two boundary tests + plugin TypeBox sync + verification sweep). Phases 3-5 are the substantive work (~1-2 days). Phase 6 is the acceptance gate.

---

## 2026-05-23 — Phase 2 complete (validation fix shipped)

User signed off the 6-phase plan with "Go"; Phase 2 ran in one short session.

### What landed

| Surface | Change |
|---------|--------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | `rationale: Field(min_length=10)` (was 50). Module + class docstrings updated. |
| `packages/toolkit/tests/integration/test_pgs_compute_request_validation.py` | Phase 1's RED test (`test_pgs_compute_accepts_agent_short_rationale`) flipped GREEN. Renamed + flipped `test_pgs_compute_42_char_rationale_currently_rejected_documents_threshold` → `test_pgs_compute_49_char_rationale_accepted_post_fix` (assertion 422→202). Added `test_pgs_compute_9_char_rationale_rejected_post_fix` (pins new floor reject side) + `test_pgs_compute_10_char_rationale_accepted_post_fix` (pins new floor accept side). Removed unused imports (ruff). |
| `packages/toolkit/tests/integration/test_pgs_model.py` | `test_pgs_compute_request_requires_long_rationale` renamed → `..._requires_non_empty_rationale`; updated assertions: still rejects empty + 9-char, but now ACCEPTS the previously-rejected "canonical CAD PRS" (17 chars) — the regression guard for the 2026-05-23 incident. |
| `packages/nemoclaw-plugin/src/index.ts` | `PgsComputeParams.rationale: Type.String({ minLength: 10 })` (was 50). Comment block above the params updated to explain the new threshold + the incident context. |
| `packages/nemoclaw-plugin/policy-preset.yaml` | Comment on `/v1/pgs/compute` allow rule updated `minLength 50 → 10`. |
| `packages/nemoclaw-plugin/tests/index.test.ts` | Vitest title + comment updated to "shorter than 10 chars". Rationale `"too short"` (9 chars) replaced with `"short"` (5 chars) — still rejected, still validates the TypeBox gate. |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | Appended a paragraph to the PRS-decline section explaining "host accepts ≥10 chars, but aim for ≥50 chars" with an example rationale. Optional per Phase 2 Step 2.4; landed because the guidance is cheap to write + makes the audit-trail concern visible to future agent sessions. |

### Verification gates passed

- Validation tests: 7/7 PASS (`test_pgs_compute_request_validation.py`).
- Touched legacy test: PASS (`test_pgs_compute_request_requires_non_empty_rationale`).
- Full toolkit suite: **833 passed, 114 skipped** (skips are env-gated bio-tool + sandbox-image tests, unchanged from baseline).
- Plugin TS strict-mode `tsc`: clean.
- Plugin vitest: **21/21 PASS**.
- `ruff check` on touched files: clean.
- `mypy` on `schemas/pgs.py`: clean.

### Acceptance criteria

- ✅ Phase 1's RED test (`test_pgs_compute_accepts_agent_short_rationale`) is GREEN.
- ✅ Existing empty-rationale rejection stays GREEN (INV-A003 floor preserved).
- ✅ New boundary tests at 9 chars (rejected) + 10 chars (accepted) pin the new boundary on both Python + TypeScript surfaces.
- ✅ Plugin TypeBox + Pydantic threshold in sync (both at 10).
- ✅ Plugin build + vitest green.
- ✅ Full toolkit suite green.
- ✅ ruff + mypy clean on touched files.

### Sandbox-image rebuild — deferred

The plugin's compiled output changed (`packages/nemoclaw-plugin/dist/index.js` was regenerated by `tsc`). For the change to reach the agent at runtime, the sandbox image needs rebuilding. Phase 6's E2E test runs against the rebuilt sandbox image; the rebuild is the natural action item at the start of Phase 6, not now. The host-service side of the fix is live immediately — operators driving via `curl` or via the bin shim see the new threshold today.

### What didn't change

- `bin/genomeclaw-prs-smoke` driver — untouched.
- `INVARIANTS.md` — untouched (no new invariant; INV-A003's rule is "alternatives considered + why this one", not "exactly 50 chars").
- `compute_prs_with_coverage_fill(...)` + `_stamp_pgs_row(...)` — untouched. Phase 4 wires the worker to them.
- Sandbox image — needs rebuild before Phase 6 E2E (noted above).

### Next step

**Phase 3** — worker skeleton. The bones of the E.3 worker: FastAPI `lifespan` hook, polling loop, atomic claim via `UPDATE...RETURNING`, concurrency cap, kill-switch. 8 tests, no real compute yet (no-op `await asyncio.sleep(0)`). Estimated 3-4 hours of focused work.


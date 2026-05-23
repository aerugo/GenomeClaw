# Phase 3 — Containerised compute (architecture)

**Status**: Pending (gated on Phase 1's design pass)
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Make `compute_prs_with_coverage_fill(...)` (and the bcftools/samtools/pgsc_calc subprocesses it spawns) actually executable from the host service's worker, by running it in an environment where those binaries exist. The user-facing outcome: a real PRS percentile lands on a `pgs_scores` row after a `genomeclaw_pgs_compute` invocation, no `BcftoolsError`.

**This phase's implementation depends on Phase 1's choice (Option A / B / C).** The contract `_real_compute_fn` exposes to the worker loop is unchanged regardless of which option; only the internals differ.

## Scope Boundaries

- **In scope**:
  - Whichever runtime architecture Phase 1 picked, wired into `_real_compute_fn` (or its successor).
  - Structured error mapping for the new failure class (e.g. `compute_container_failed:rc=<N>` or `host_service_image_unavailable`).
  - INV-R001/R002/A003 preservation across the runtime boundary.
  - Test coverage for the new runtime path.
- **Out of scope**:
  - Refactoring `compute_prs_with_coverage_fill`'s internals.
  - Multi-architecture / multi-arch toolkit-image builds.
  - Per-task work-dir cleanup beyond what Phase 3 needs for correctness (a follow-up plan can cover GC).
  - Phase 2's scorefile auto-fetch (independent layer).

## Invariants enforced in this phase

- **INV-D002** — sandbox stays bio-binary-free. The toolkit image is the boundary; this phase preserves that.
- **INV-D006** — host-form paths flowing into any docker invocation respect `as_sibling_mountable`. The auto-published `GENOMECLAW_HOST_ROOTS` keeps doing its job.
- **INV-R001** — the persisted `pgs_scores` row carries the seven provenance columns regardless of the runtime path.
- **INV-R002** — `_is_degenerate` guard continues to fire before persistence (or its equivalent inside the toolkit-container path).
- **INV-A003** — `agent_choice_rationale` + `requested_for_question` survive the runtime boundary.

---

## TDD Steps

### Step 3.1 — RED: write failing tests

Implementation-specific. Each option's test file:

**If Phase 1 picked Option A** (host service inside toolkit image):
- New file: `tests/integration/test_host_service_toolkit_image.py`.
- Tests:
  1. `test_host_service_starts_in_toolkit_image` — `docker run` the toolkit image with the host service entrypoint; `curl /v1/health` returns 200. Gated on `GENOMECLAW_TOOLKIT_IMAGE` env var.
  2. `test_worker_has_bcftools_in_image` — start the host service inside the image; the worker probes `bcftools --version` via subprocess; succeeds.
  3. `test_compute_request_runs_real_compute_fn` — enqueue a compute against a synthetic minimal CRAM (or stub the inner subprocess); assert the worker reaches `_stamp_pgs_row` cleanly.

**If Phase 1 picked Option B** (per-compute DooD-spawn):
- New file: `tests/integration/test_worker_dood_spawn.py`.
- Tests:
  1. `test_dood_spawn_argv_shape` — `_real_compute_fn` builds the docker-run argv correctly: image tag, mount args, env vars, command line `prs-compute --json --pgs=... ...`.
  2. `test_dood_spawn_parses_json_envelope` — mock the docker subprocess to return a known JSON envelope on stdout; `_real_compute_fn` parses it into a `PgsRow`.
  3. `test_dood_spawn_non_zero_rc_maps_to_structured_error` — mock the docker subprocess to return rc=1 + stderr; `_structured_error` maps to `compute_container_failed:rc=1`.
  4. `test_dood_spawn_invD006_host_form_paths` — verify the `-v` mount args use host-form paths from the sidecar (not canonical-mount paths).
  5. `test_dood_spawn_invR001_provenance_preserved` — end-to-end (stub docker subprocess) returns a `PgsRow`; `stamp_pgs_row` writes seven-column shape.

**If Phase 1 picked Option C** (persistent + exec):
- Similar shape to Option B, plus:
  1. `test_persistent_container_starts_at_lifespan` — TestClient context spawns the container.
  2. `test_persistent_container_cleaned_on_shutdown` — TestClient exit `docker stop`s the container.

After authoring, run the suite — **all should fail for the right reason** (the new runtime path isn't wired).

### Step 3.2 — GREEN: minimal implementation

Option-dependent. High-level shape:

**Option A (host service in toolkit image)**:
- Update `bin/genomeclaw` shim's `host)` case: remove the `GENOMECLAW_NATIVE=1` override; wrap in `docker run -p 8643:8643 -v <bind-mounts> -v /var/run/docker.sock:/var/run/docker.sock genomeclaw/toolkit:<tag> ...`.
- Update `bin/genomeclaw host service` entry to invoke the same `python -m genomeclaw_toolkit._cli host service ...` but now inside the container.
- The toolkit image needs a Phase 6c/d rebuild that includes the latest `genomeclaw_toolkit` package (current builds are at slice-d-prime; older than the recent Phase 4-5 work). Rebuild as `genomeclaw/toolkit:worker-self-sufficient`.
- Bind-mounts: raw RO, reference RO, derived RW, scratch RW, docker.sock RW (for pgsc_calc's DooD).
- INV-D006: the `bin/genomeclaw` shim already publishes `GENOMECLAW_RAW_DIR` etc. + `GENOMECLAW_HOST_ROOTS`; need to pass these through to the container OR have the lifespan auto-publish them from the sidecar (already does so post-`fa822b3`).

**Option B (per-compute DooD-spawn)**:
- New module `service/_compute_container.py` with `spawn_compute_container(task, config, run_dir) -> PgsRow`.
- Builds `docker run --rm -v ... genomeclaw/toolkit:<tag> python -m genomeclaw_toolkit._cli pipeline prs-compute --json ...` argv.
- Captures stdout; parses the JSON envelope into a `PgsRow`.
- Maps non-zero rc + stderr into `ComputeContainerError` → structured `compute_container_failed:rc=<N>`.
- `_real_compute_fn` calls `spawn_compute_container` instead of `compute_prs_with_coverage_fill`.

**Option C (persistent + exec)**:
- New module `service/_persistent_compute_container.py` with lifespan-managed container lifecycle.
- Per-task `docker exec` invocations; same JSON-envelope parsing as Option B.

### Step 3.3 — REFACTOR

- Extract any docker-argv building common to Options B/C into a helper.
- Update the agent system prompt's failure-mapping table to include the new failure class.
- Make sure the worker's `transition=` log lines pick up the new runtime metadata (image tag, container ID, etc.).

---

## Implementation Details

### Toolkit image rebuild requirement

Whichever option Phase 1 picked, the **toolkit image needs rebuilding** to include the post-2026-05-23 changes (Phase 4-5 of agent-prs-compute-fix + iteration commits `d0f9c4e` + `fa822b3` + `b8b7954` + `d7a9ff3`). The current `genomeclaw/toolkit:slice-d-prime` predates these. New tag: `genomeclaw/toolkit:worker-self-sufficient`.

### Schema / Provenance Impact

- `pgs_scores`/`findings` row shapes unchanged.
- Provenance columns continue to land via `stamp_pgs_row` regardless of runtime path.
- If Option B/C: the in-container compute writes `task_id` + a JSON envelope on stdout; the worker parses + persists. The persistence happens HOST-SIDE so no schema concerns about cross-container DB access.

### Edge Cases to Handle

- **Toolkit image missing locally** — Option A: host service fails to start (clear failure mode). Option B/C: per-task `compute_container_failed:image_unavailable`. Both surface a clean operator-actionable message.
- **Docker daemon down** — Option A: shim fails fast at `docker run`. Option B/C: `compute_container_failed:docker_daemon_unreachable`.
- **Pgsc_calc DooD-spawn from inside the toolkit container** — this is the existing path the smoke driver uses; INV-D005 (identical-path bind-mounts) applies. Phase 3 doesn't change this; it just makes sure the OUTER container has the right docker.sock + bind-mounts so the inner pgsc_calc DooD-spawn works.
- **Long-running compute + container crash** — if the toolkit container crashes mid-task, the host-side worker's `await loop.run_in_executor(...)` raises; `_structured_error` maps to `compute_container_failed:<rc>` or `worker_unexpected_error:<class>`; Phase 5's stale-running cleanup handles the task DB state.

### Privacy / Egress Notes

- No new egress surfaces relative to the existing toolkit image's behavior.
- Per-compute DooD-spawn (B/C) inherits the same docker socket access the smoke driver already uses.
- INV-P001 default-off behavior preserved: no outbound calls under kill-switch.

---

## Files

Option-dependent. Common shape:

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | MODIFY | Restructure `_real_compute_fn` for the chosen runtime path |
| `bin/genomeclaw` (if Option A) | MODIFY | Swap `GENOMECLAW_NATIVE=1` for `docker run` invocation |
| `packages/toolkit/src/genomeclaw_toolkit/service/_compute_container.py` (if Option B/C) | CREATE | Docker invocation shape + JSON envelope parsing |
| `packages/toolkit/tests/integration/test_<option-specific>.py` | CREATE | Tests for the new runtime path |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY | Failure-mapping table picks up `compute_container_failed:<rc>` |
| `docs/reference/architecture.md` | MODIFY | Diagram + narrative reflect the chosen runtime architecture |

---

## Verification

```bash
cd packages/toolkit

# Option-specific test file
uv run pytest tests/integration/test_<option-specific>.py -v
# Expect: all PASS

# Worker integration tests still pass (the _real_compute_fn contract is preserved)
uv run pytest tests/integration/test_pgs_compute_worker_integration.py -v
# Expect: 14/14 STILL PASS

# Full sweep
uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: no regressions.

# Manual smoke against the canonical run-dir + real PGS004606
GENOMECLAW_TOOLKIT_IMAGE=genomeclaw/toolkit:worker-self-sufficient \
  bin/genomeclaw host service --derived-root /Volumes/Genome_Work/genomeclaw/derived &
# In another shell:
curl -X POST http://localhost:8643/v1/pgs/compute \
  -H 'Content-Type: application/json' \
  -d '{"pgs_id":"PGS004606","trait_label":"AMD","rationale":"Phase 3 smoke test against canonical run-dir","requested_for_question":"smoke test"}'
# Should return 202 + task_id; poll _compute_status; should reach `done` with a real percentile in pgs_scores.
```

---

## Completion Criteria

- [ ] All option-specific tests pass.
- [ ] Phase 4 worker integration tests still pass.
- [ ] Full toolkit suite stays green.
- [ ] mypy + ruff clean on touched files.
- [ ] A manual smoke against the canonical run-dir produces a real PRS percentile in `pgs_scores`.
- [ ] Agent system prompt failure-mapping table updated.
- [ ] `architecture.md` reflects the new runtime architecture.
- [ ] Toolkit image rebuilt + tagged `genomeclaw/toolkit:worker-self-sufficient`.
- [ ] `work-notes.md` updated with implementation outcomes + smoke wall-clock numbers.

## Next

[Phase 4 — Live agent verification](phase-4.md).

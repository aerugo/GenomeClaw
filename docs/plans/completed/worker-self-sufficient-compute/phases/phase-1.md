# Phase 1 — Design pass: pick the runtime architecture

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Pick the Phase 3 runtime architecture (Option A vs B vs C from spec.md), record the choice + reasoning in this plan's `work-notes.md`, and update the spec/dev-plan to reflect the final shape. **No code changes in this phase** — output is a documented decision.

## Scope Boundaries

- **In scope**: brief design exploration of the three options; pick one; record decision + dropped alternatives.
- **Out of scope**: any code; any test changes; any sandbox/toolkit-image rebuilds.

## Invariants enforced in this phase

- None directly. Phase 1 is design narrative; Phase 2/3 carry the invariants.

---

## Steps

### 1.1 — Validate the three options against the real environment

For each option, answer concretely:

| Question | Option A (host service in toolkit) | Option B (per-compute DooD) | Option C (persistent + exec) |
|----------|-----------------------------------|-----------------------------|------------------------------|
| How does the sandbox reach `host.openshell.internal:8643`? | `docker run -p 8643:8643 ...` exposes the port from the toolkit container to the host bridge. | Host service stays on host; binding unchanged. | Host service stays on host; binding unchanged. |
| Where does bcftools come from? | On `$PATH` inside the toolkit image. | Inside the `docker run --rm ...` toolkit container spawned per compute. | Inside the persistent `docker exec` target. |
| What does the worker code look like? | `_real_compute_fn` is unchanged (compute_prs_with_coverage_fill runs in the same process where bcftools lives). | New: docker-run argv builder + JSON-envelope parser + bind-mount plumbing. | Container lifecycle hooks at lifespan start/stop + per-task `docker exec`. |
| Restart cost? | Image pull on first run (~5 min cold; cached subsequent restarts). | Per-task ~2-5 s container start. | One image pull + cheap exec per task. |
| Shim impact? | The `host)` case forcing `GENOMECLAW_NATIVE=1` becomes obsolete; rework into a `docker run` invocation. | The shim is untouched. | Shim untouched; worker grows lifecycle code. |
| Test footprint? | New: docker-based integration tests; the in-process TestClient pattern no longer covers the runtime path. | Tests mock the docker invocation (already a pattern in the codebase via pgsc_calc's DooD tests). | More mocking surface (lifecycle + exec). |
| Failure modes? | Toolkit image missing → host service can't start (good — operator notices fast). | Toolkit image missing OR docker daemon down → per-task `compute_container_failed`. | Same as B plus persistent-container-crashed mid-lifecycle. |

### 1.2 — Smoke-test the running-host-service-inside-toolkit pattern

Quickest validation of Option A: try to run the existing host service code inside `genomeclaw/toolkit:slice-d-prime` for ~30 minutes.

```bash
docker run --rm \
  -p 8643:8643 \
  -v /Volumes/Genome_Work/genomeclaw/derived:/mnt/genomeclaw/derived \
  -v /Volumes/Genome_Work/genomeclaw/reference:/mnt/genomeclaw/reference \
  -v /Volumes/Genome_Work/genomeclaw/raw:/mnt/genomeclaw/raw:ro \
  -v /Volumes/Genome_Work/genomeclaw/_scratch:/mnt/genomeclaw/_scratch \
  -v /var/run/docker.sock:/var/run/docker.sock \
  genomeclaw/toolkit:slice-d-prime \
  python -m genomeclaw_toolkit._cli host service --derived-root /mnt/genomeclaw/derived --port 8643
```

If `curl http://localhost:8643/v1/health` returns 200 + the worker boots without errors, Option A is plumbing-clear. If the toolkit image's Python venv can't import the latest `genomeclaw_toolkit` package (because the image was built at slice-d-prime), the image needs rebuilding — straightforward but not free.

### 1.3 — Smoke-test the DooD-spawn-per-compute pattern

Quickest validation of Option B: spawn a toolkit container manually that runs `prs-compute --json` against the canonical inputs, capture stdout JSON, verify a real percentile lands.

```bash
docker run --rm \
  -v /Volumes/Genome_Work/genomeclaw/raw:/mnt/genomeclaw/raw:ro \
  -v /Volumes/Genome_Work/genomeclaw/reference:/mnt/genomeclaw/reference \
  -v /Volumes/Genome_Work/genomeclaw/_scratch:/mnt/genomeclaw/_scratch \
  -v /Volumes/Genome_Work/genomeclaw/derived:/mnt/genomeclaw/derived \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e GENOMECLAW_DOOD=1 \
  -e GENOMECLAW_HOST_ROOTS=/Volumes/Genome_Work/genomeclaw \
  genomeclaw/toolkit:slice-d-prime \
  python -m genomeclaw_toolkit._cli pipeline prs-compute \
    --pgs PGS004606 \
    --vcf /mnt/genomeclaw/derived/CURRENT/normalized.vcf.gz \
    --reference-root /mnt/genomeclaw/reference \
    --work-dir /mnt/genomeclaw/_scratch/pgs-work \
    --rationale "phase-1 design smoke" \
    --question "Do I have any risk factors for loss of eyesight?" \
    --json
```

If a JSON envelope with a percentile prints to stdout, Option B is plumbing-clear. If the inside-container `prs-compute` errors at the same `BcftoolsError` (which would be surprising — the toolkit image is where bcftools lives), Option B has a deeper plumbing issue worth flagging early.

### 1.4 — Decide

After 1.1-1.3, pick one option. Default recommendation (subject to the design pass): **Option A** — it minimizes code surface, the toolkit image is already the bio-tools integration point, and the existing `bin/genomeclaw-prs-smoke` proof point demonstrates the compute works in that environment.

Record the decision in `work-notes.md`:
- Picked option + 2-3 sentence rationale.
- Dropped options + 1 sentence each on why.
- Any surprises from the smoke tests (e.g. "the toolkit image needs rebuilding to include the new orchestrator code").

Update `development-plan.md`'s Phase 3 section to remove the "three options" framing + restate the chosen design as the canonical Phase 3 shape.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/worker-self-sufficient-compute/work-notes.md` | MODIFY | Append the design-pass outcome |
| `docs/plans/active/worker-self-sufficient-compute/development-plan.md` | MODIFY | Lock in the chosen option as Phase 3's canonical shape |
| `docs/plans/active/worker-self-sufficient-compute/spec.md` | MODIFY (light) | Update Open Question 1 to "resolved: Option X" |

No code changes.

---

## Verification

Phase 1 has no automated tests. The acceptance gate is:
- A documented decision in `work-notes.md` with reasoning that someone outside this session can audit.
- Either a Phase 3 smoke test that demonstrated the picked option works, OR a clear note on what couldn't be tested + why (e.g. "Option A smoke deferred because the toolkit image needs rebuilding first — Phase 3 absorbs that work").

---

## Completion Criteria

- [ ] Phase 3 runtime architecture picked (A, B, or C).
- [ ] Dropped alternatives documented with reasoning.
- [ ] At least one of the design-validation smoke tests run + result recorded.
- [ ] `development-plan.md` Phase 3 section locked to the chosen design.
- [ ] `spec.md` Open Question 1 resolved.
- [ ] `work-notes.md` carries the design-pass block.

## Next

[Phase 2 — Inline auto-fetch](phase-2.md) (independent of Phase 1's choice; can be sequenced in parallel or after).

# Spec — Worker self-sufficient compute (end-to-end agent-driven PRS)

**Status**: Active — drafted 2026-05-23 post-agent-prs-compute-fix iteration.
**Created**: 2026-05-23
**Companion to**: [docs/plans/completed/agent-prs-compute-fix/](../../completed/agent-prs-compute-fix/)

---

## Goal

Make the host service's PGS compute worker run a real compute end-to-end **without operator intervention**: the agent invokes `genomeclaw_pgs_compute`, the worker fetches the scorefile if absent, runs the actual `bcftools` + `pgsc_calc` pipeline against a sibling toolkit container (or otherwise resolves the runtime-tools gap), persists the `pgs_scores` + `findings` row, and the agent surfaces a real numeric percentile to the user.

## Background

The 2026-05-23 post-iteration of the agent-prs-compute-fix plan surfaced two real blockers preventing the user-facing compute path from producing a green percentile:

### Blocker 1 — bcftools not on host PATH

The Phase 4 worker calls `compute_prs_with_coverage_fill(...)` from the host service process via `loop.run_in_executor(...)`. That function invokes `bcftools mpileup → call → norm → index` via `subprocess.run(["bcftools", ...])`. The shim's `host)` subcommand forces `GENOMECLAW_NATIVE=1` so the host service runs natively (on macOS, no toolkit container) — but bcftools/samtools/htslib/mosdepth are NOT installed on the macOS host. Every compute fails with `worker_unexpected_error:BcftoolsError`.

Verified live 2026-05-23: a `genomeclaw_pgs_compute(PGS004606)` invocation transitions from `queued → running → failed:worker_unexpected_error:BcftoolsError` because the host process has no bcftools. The architecture documents the toolkit image as the integration point for bio tools (see `architecture.md:282`), but Phase 4 never resolved how the worker — running outside the toolkit image — gets access to them.

### Blocker 2 — scorefiles must be operator-fetched

The Phase 4 `_real_compute_fn` raises `PgsScorefileMissingError` when `<scorefile_root>/<pgs_id>/<pgs_id>_hmPOS_GRCh38.txt.gz` is absent. The agent's reply surfaces an actionable operator command (`genomeclaw refs fetch --source pgs_scorefile --release PGS<id>`) — but **the agent has no path to actually trigger the fetch itself**. So even after the agent decides a compute is warranted, the operator has to break out of the conversation to run a CLI command.

The user's explicit ask (2026-05-23): *"GenomeClaw agent should be authorized to do this without operator intervention"*. The PGS Catalog fetch egress is already documented as a one-time-at-install consent surface (`architecture.md:405`); agent-triggered transitive fetches are within scope of existing consent.

### Why these two consolidate into one plan

Both blockers prevent the same user-facing outcome (real percentile in the agent's reply). Blocker 1 fixed alone produces no observable improvement when scorefiles are missing. Blocker 2 fixed alone still fails at bcftools. They share the same artifact surface (`_real_compute_fn` + worker lifecycle) and resolving them in one coherent plan ships a usable end-to-end path.

## Acceptance Criteria

- [ ] **AC1**: The agent asks the eyesight question (`"Do I have any risk factors for loss of eyesight?"`). The reply contains a numeric AMD PRS percentile (or a clean two-named-reasons INV-C001 v1.7 decline citing the actual literature-immaturity case). No `worker_unexpected_error:BcftoolsError`, no `scorefile_missing:<pgs_id>` in the reply.
- [ ] **AC2**: A live `genomeclaw_pgs_compute(pgs_id="PGS004606", ...)` invocation transitions `queued → running → done`. The `pgs_scores` table has one new row carrying the seven INV-R001 provenance columns + INV-A003 `agent_choice_rationale` + `requested_for_question` + a non-null `percentile_in_user_ancestry`.
- [ ] **AC3**: A live compute against a PGS ID whose scorefile is NOT pre-staged (e.g. PGS000137 glaucoma) succeeds end-to-end: the worker auto-fetches the scorefile from PGS Catalog inline, then runs the compute, then stamps the row. No operator action required.
- [ ] **AC4**: The kill-switch (`pgs.compute_enabled false`) still rejects new compute requests immediately with `failed:compute_path_disabled`, AND prevents the auto-fetch (no PGS Catalog egress under kill-switch).
- [ ] **AC5**: A live compute against a PGS ID that's NOT in the PGS Catalog (e.g. the made-up ID `PGS999999`) fails with a clean structured error (`scorefile_unfetchable:404` or similar) — distinguishable from `scorefile_missing` (the local-only check).
- [ ] **AC6**: The host service's `/v1/health` continues to bind on `host.openshell.internal:8643` (the canonical sandbox-side egress destination) regardless of which runtime architecture Phase 3 picks (A: host service inside toolkit image; B: per-compute DooD-spawn sibling; C: persistent docker exec).
- [ ] **AC7**: No regressions in the 867-passed toolkit suite. New Phase 2 + Phase 3 tests cover the new surfaces. Existing Phase 4 worker integration tests continue to pass (the `_real_compute_fn` injection point + the structured-error mapping shape stay stable).

## Applicable Invariants

- **INV-D001** (Raw Genomic Files Are Source-of-Truth): the worker invokes compute against the user's CRAM (read-only); no modification.
- **INV-D002** (sandbox has no bio binaries): the toolkit image is where bio binaries live; this plan extends that boundary to cover the worker too. The sandbox-side plugin is unchanged.
- **INV-D006** (host-form paths for DooD siblings): if Phase 3 picks Option B (per-compute DooD-spawn) the new sibling containers must respect `as_sibling_mountable`'s checks. The host-roots auto-publication shipped in `fa822b3` should keep working.
- **INV-R001** (Rebuildability): the resulting `pgs_scores` row carries the seven canonical provenance columns. Phase 3's containerised compute must preserve `stamp_pgs_row`'s row shape.
- **INV-R002** (Never Cache a Degenerate Result): the existing `_is_degenerate` guard fires before persistence; Phase 3 preserves this.
- **INV-P001** (Privacy Default): PGS Catalog egress is already documented as consented at install per `architecture.md:405`; Phase 2's auto-fetch transitively rides that consent. The kill-switch retains the user's hard-stop (AC4).
- **INV-A003** (Agent-Curated Compute Provenance): `agent_choice_rationale` + `requested_for_question` continue to land on the `pgs_scores` row regardless of which runtime path the compute took.
- **INV-C001 v1.7** (PRS-decline pattern): orthogonal; the worker's runtime fix doesn't change the agent's decline-vs-compute decision.

## Proposed New Invariants

**None expected.** This plan implements an architectural fix to an existing system; it doesn't introduce a new project-wide rule. If Phase 1's design pass surfaces a need (e.g. "Worker subprocess invocations must go through `with toolkit_container():`"), the proposal lands in `development-plan.md` and gets promoted in the standard way.

## Out of Scope

- **Multi-sample compute** — worker still handles one CURRENT-symlink sample at a time.
- **Concurrency cap > 1** — Phase 3's containerised compute keeps the existing 1-in-flight cap.
- **Operator CLI for the task DB** (`genomeclaw pgs tasks ls`) — separate UX plan.
- **Refactoring `compute_prs_with_coverage_fill`'s internals** — Phase 3 wraps the function; it doesn't restructure it.
- **Per-compute pgsc_calc version overrides** — the toolkit image's pinned pgsc_calc version is what runs.
- **AC8 coverage_qc / gene-list BED** — orthogonal Phase 7 MVP carry-forward.

## Privacy & Safety Considerations

### Existing egress surface (no new boundary)

PGS Catalog scoring weights fetch from `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/...` is **already documented** as a one-time-at-install consent surface (`architecture.md:405`, `INV-P001`). The user has implicitly consented to this destination by completing `genomeclaw host setup --fetch-all` OR by previously running `genomeclaw refs fetch --source pgs_scorefile` (e.g. PGS000018 + PGS001229 + PGS004606 are already on the user's disk from prior operator action).

Phase 2's inline auto-fetch is a transitive use of that same consent: the agent decides which PGS Catalog ID to compute → the worker fetches its scorefile inline → result lands on `pgs_scores`. The egress destination, transport (HTTPS), and content (scoring weights, no user data) are all identical to the manual `refs fetch` path.

**No user genomic data leaves the host on the auto-fetch path.** Scoring weights flow inbound; user variants stay local.

### Kill-switch (`pgs.compute_enabled false`)

The existing kill-switch must continue to:
- Reject new `genomeclaw_pgs_compute` requests with `failed:compute_path_disabled`
- Prevent the worker from auto-fetching scorefiles (no PGS Catalog egress under kill-switch)
- Prevent the worker from spawning toolkit containers (no docker invocations under kill-switch)

AC4 covers this.

### Audit trail

Every auto-fetched scorefile + every containerised compute MUST land in the host log with structured metadata:
- INFO `transition=auto_fetch_scorefile pgs_id=<id> bytes=<n> duration=<s>`
- INFO `transition=compute_container_started image=<image>:<tag> task_id=<id>`
- INFO `transition=compute_container_exited rc=<n> duration=<s>`

These extend the Phase 5 observability shape; they're a natural fit.

### `privacy-safety-reviewer` agent invocation

Phase 2's auto-fetch + Phase 3's containerised compute affect documented egress + introduce a new docker-spawn surface. **The `privacy-safety-reviewer` agent should review the Phase 2 + Phase 3 diffs before they land.** Tracked in the plan's verification gate.

## Open Questions

1. **Phase 3 runtime architecture** — three options on the table:
   - **A**: Run the WHOLE host service inside the toolkit image (Uvicorn lives there too). Simplest; bcftools is on PATH; sandbox reaches it via host bridge with `-p 8643:8643`. Downside: heavyweight (6.4 GB image holds the host service too).
   - **B**: Per-compute DooD-spawn — worker stays on host; for each compute task it `docker run`s a toolkit container that runs the compute, then exits. Bind-mounts the sidecar-declared paths + the task SQLite DB. Higher per-task overhead but cleanest separation.
   - **C**: Persistent toolkit container at lifespan startup + `docker exec <container> ...` per task. Hybrid of A and B.
   - **Phase 1 design pass picks one.** Recommendation pending the design exploration; gut feel says A is simplest + lowest-novelty.
2. **Scorefile fetch retry policy** — how many retries on transient PGS Catalog 5xx? **Recommendation**: 3 retries with exponential backoff (1s, 4s, 16s), then `scorefile_unfetchable:<reason>`. Matches the existing `refs fetch` behavior.
3. **Per-compute work-dir lifecycle** — should the toolkit container's work-dir be cleaned up after success? **Recommendation**: Yes, on `done`. Failed tasks keep the work-dir for debugging (operator can grep). Phase 3 design pass picks the cleanup window.
4. **Auto-fetch vs explicit-tool design** — should the agent ALSO have a separate `genomeclaw_pgs_scorefile_fetch` tool to pre-stage on demand? **Recommendation**: NO. The agent's role is to call `_pgs_compute`; the worker handles fetching as part of the compute. A separate tool surface is unnecessary plumbing.
5. **Scorefile freshness** — should the worker re-fetch on a cache hit if the PGS Catalog version has updated? **Recommendation**: NO for now (the current `refs fetch` doesn't either). A future scoring-weights-versioning plan can add this.

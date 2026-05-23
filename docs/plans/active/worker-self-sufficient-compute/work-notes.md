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

## Open follow-ups deferred to OTHER plans (not in scope here)

- **`openclaw-toolcall-serialization`** — the agent occasionally POSTs `call_xxx|fc_yyy` as a bare-string body instead of a JSON args object. The plugin's runtime arg-guard (commit `b8b7954`) catches this locally + returns a clean error, but the upstream openclaw runtime serializer is the real fix. Out of scope; file separately if it persists.
- **AC8 coverage_qc / gene-list BED** — orthogonal MVP Phase 7 carry-forward.
- **Scoring-weight version awareness / cache invalidation** — Phase 2's auto-fetch doesn't re-fetch on a cache hit even if PGS Catalog updated the scoring weights. Future plan.
- **Multi-sample / concurrency cap > 1** — out of scope; current 1-in-flight cap holds.

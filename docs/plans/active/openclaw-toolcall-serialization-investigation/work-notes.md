# Work Notes — Openclaw tool-call serialization investigation

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored

**Trigger**: post-MVP iteration of agent-prs-compute-fix surfaced two correlated tool-call-arg corruption symptoms:
- Symptom A: `genomeclaw_gene("undefined")` × 7 in one trace (eyesight question v3).
- Symptom B: `POST /v1/pgs/compute` with bare-string body `"call_<id>|fc_<id>"` × 2 (compute-direct probe).

Both shapes are defanged today by the runtime arg-guard in commit `b8b7954` (`rejectIfPlaceholder` at plugin `execute()` entry). The eyesight v4 trace confirms the workaround: 0× `/v1/gene/undefined` host calls, 15 genes successfully queried.

But the upstream bug is real + actively degrading agent quality — the agent intends to look up specific genes, openclaw corrupts the args, the agent sees a "tool failed" error + degrades. At scale that's a quality regression. Need to understand WHERE the corruption happens to pick the right fix.

**Three-phase plan**: investigate (reproduce + classify), bisect (cross-model), decide (Path U upstream issue / Path D document quirk / Path L local fix).

**Applicable invariants**: only INV-P001 (synthetic prompts; no user genomic content in raw payload capture).

**Privacy posture**: no new egress surfaces. Uses the existing agent-provider egress + one paid Claude/Anthropic call for the cross-model bisect.

**Expected wall-clock**: half-day total — Phase 1 takes the longest (3-4h on reproducer + raw-payload capture); Phase 2 is ~1h + 1 LLM call; Phase 3 is path-conditional 1-2h.

### Sequencing relative to worker-self-sufficient-compute

This plan is **independent** of `worker-self-sufficient-compute`. The two can ship in parallel. Recommended order: this one first (cheaper), then worker-self-sufficient-compute (heavier). But if the user wants the green-percentile demo first, the worker plan can go first; this investigation can wait.

### Next step

Surface the plan to the user for sign-off. Phase 1 starts after sign-off.

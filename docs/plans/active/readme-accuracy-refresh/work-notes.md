# README Accuracy Refresh — Work Notes

**Feature**: Repair `README.md` to match the shipped CLI / host-service / plugin / invariants surface + add a code-derived consistency gate.
**Started**: 2026-06-01
**Branch**: `docs/readme-accuracy-refresh` (create at implementation start)
**Spec**: [spec.md](spec.md) · **Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest at the bottom. Each session opens with a context-review block.

### 2026-06-01 — Plan authoring

**Context reviewed**:
- Read root `CLAUDE.md` + `docs/plans/CLAUDE.md` (planning protocol; TDD-inside-every-phase; full-layout required for user-facing-doc changes).
- Audited `README.md` against ground truth derived from code on `main` @ `c789b58`.

**Ground truth captured (2026-06-01, from code)**:
- CLI groups: `host` (`doctor/setup/eject/service` + `profile {init,show,set,review,edit}`), `refs` (`fetch/list/verify/info`), `runs` (`list/show/current`), `pipeline` (`ingest/normalize/annotate/materialize/run/pgs-compute/prs-prepare-coverage/prs-compute/pharmcat/cyp2d6-call/pgs-config-write`), `completion`.
- Host service port **8645**; routes incl. `/v1/host/profile`(+`/completeness`) + agent-driven PRS endpoints; `/v1/pgs/{trait}` retired.
- 10 plugin tools (`openclaw.plugin.json` `contracts.tools`).
- `SCHEMA_VERSION = v0.4`; `INVARIANTS.md` Version **1.26**.

**README drift found** (full table in spec.md § Background): "six tools" (→10), port 8643 (→8645, README self-contradicts), stale endpoint list (`/v1/pgs/{trait}`), no `host profile`, "INVARIANTS v1.6" (→v1.26), Status frozen at "Phases 1–3, Phase 4 next".

**Decisions made**:
- Code-derived consistency test (not hardcoded facts) as the durable guard.
- Curated command subset in the test (groups + host-profile + pipeline + `refs fetch` placement), not every leaf — avoid brittleness.
- Phase the rewrite by README section.
- Blocking privacy-safety-reviewer pass (README describes the privacy model).

**Completed today**:
- [x] `spec.md`, `development-plan.md`, `work-notes.md`, `phases/phase-{1,2,3,4}.md` drafted.

**Open questions to resolve in Phase 1**:
- Q1 — version-pin the invariants link or keep version-less? (leaning version-less)
- Q2 — full command tree or curated subset in the test? (leaning curated subset)

**Next steps**:
1. Create branch `docs/readme-accuracy-refresh`.
2. Phase 1 RED: write `test_readme_accuracy.py`; confirm it fails on the current README for the right reasons.

**Blockers**: none.

---

## Phase Progress

### Phase 1: Audit lock-in + consistency-test harness
**Status**: Pending

### Phase 2: CLI surface section rewrite
**Status**: Pending

### Phase 3: Agent-integration section rewrite
**Status**: Pending

### Phase 4: Freshness + cross-links + final verify
**Status**: Pending

---

## Files Modified

### Created
- `docs/plans/active/readme-accuracy-refresh/{spec,development-plan,work-notes}.md` + `phases/phase-{1,2,3,4}.md`.

### To create / modify (during implementation)
- CREATE `packages/toolkit/tests/invariants/test_readme_accuracy.py`.
- MODIFY `README.md`.

---

## Open Risks & Follow-ups
- Over-pinning prose in the gate (mitigated by curated-subset).
- Sweep ALL port references (README self-contradicts on 8643/8645).
- Other `docs/reference/*` drift → separate follow-up if surfaced.

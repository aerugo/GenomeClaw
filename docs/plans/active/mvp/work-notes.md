# MVP — Work Notes

**Feature**: end-to-end genome → agent loop
**Started**: 2026-05-06
**Branch**: `feature/mvp` (target — not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom. Each session opens with a context-review block.

### 2026-05-06 — Plan authored

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) v1.4 — confirmed seven invariants and their post-lifestyle-update shape.
- Re-read [docs/reference/architecture.md](../../reference/architecture.md) — confirmed verified deployment topology and endpoint sketch.
- Re-read [docs/reference/grand-plan.md](../../reference/grand-plan.md) — confirmed Horizons 1–3 (and a slice of Horizon 6 for lifestyle) are the MVP scope.
- Re-read [docs/reference/user-stories.md](../../reference/user-stories.md) — Stories 1, 2, 4, 6, 9 are the user journeys the MVP must deliver.

**Applicable Invariants for the plan as a whole**: all seven (`INV-D001`, `INV-D002`, `INV-E001`, `INV-P001`, `INV-P002`, `INV-R001`, `INV-C001`).

**Key Insights**:
- The plugin scaffolding under `packages/nemoclaw-plugin/` is ready; the host-side toolkit is the bulk of the MVP work.
- Live-testing the OpenClaw plugin SDK's tool-return shape (Q2) is gated on Phase 5; until then the v0 `GENOMECLAW_JSON:` text-encoding is the default.
- One lifestyle finding (*CYP1A2* / caffeine) is enough to prove the lifestyle track end-to-end; broader lifestyle work is Horizon 6.

**Completed Today**:
- [x] [spec.md](spec.md) authored
- [x] [development-plan.md](development-plan.md) authored — 7 phases, all invariants mapped to phases
- [x] [phases/phase-1.md](phases/phase-1.md) authored

**Decisions Made**:
- 7 phases (not 9). Tight enough to deliver, loose enough that each phase has a single clear theme.
- Phase 1 is just scaffolding — no genome work, no invariant assertions beyond "the test infrastructure runs."
- Phase 6 ships *one* lifestyle finding (*CYP1A2*); broader lifestyle catalog is post-MVP.

**Blockers / Issues**: none yet.

**Next Steps**:
1. Land Phase 1: scaffold `packages/toolkit/`, write the smoke test, confirm `uv run pytest` passes on a fresh clone.
2. Set up CI workflow.
3. Confirm with project owner that the chosen Python toolchain (`uv`) and test runner (`pytest`) are acceptable before implementation.

---

## Phase Progress

### Phase 1: Repo scaffolding & test infrastructure
**Status**: Pending
**Started**:
**Completed**:

#### Test Results
_(populated when phase begins)_

#### Results
_(populated when phase begins)_

#### Notes
_(populated when phase begins)_

---

## Key Decisions

_(decisions land here as phases run)_

---

## Files Modified

### Created
_(populated as phases run)_

### Modified
_(populated as phases run)_

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None expected. If Phase 7's sweep surfaces a needed invariant, propose it then.

### Other Documentation
- [ ] [architecture.md](../../reference/architecture.md) — update any drift discovered during implementation
- [ ] [grand-plan.md](../../reference/grand-plan.md) — advance Horizon 1–3 to "delivered" after Phase 7
- [ ] [README.md](../../../README.md) — replace placeholder "Getting Started" with the real commands
- [ ] [user-stories.md](../../reference/user-stories.md) — mark resolved gap-analysis items

---

## Open Risks & Follow-ups

- Plugin tool-return shape (Q2) is unresolved until Phase 5.
- Annotator choice (Q1) is locked to SnpEff unless Phase 4 fixture performance forces a switch.
- Sandbox image size is unmeasured; check in Phase 5.
- Real-genome end-to-end run is Phase 7 only; the project owner's VCF must never enter CI.

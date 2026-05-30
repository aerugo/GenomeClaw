# Eliminate Forbidden-Phrase Enumeration — Work Notes

**Feature**: Eliminate substring/regex enumeration of forbidden phrases project-wide; replace with structural / semantic / quote-verbatim mechanisms; promote `INV-V001` + meta-discovery test.
**Started**: 2026-05-28
**Branch**: `feature/eliminate-forbidden-phrase-enumeration`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-28 — Plan filed alongside sister plan

**Context Review Completed**:
- Ran Explore-agent audit of phrase-enumeration sites repo-wide (results summarized below + drive Phase 1's inventory).
- Re-read parent plan ([agent-stale-memory-and-failure-mode-confabulation/work-notes.md](../../completed/agent-stale-memory-and-failure-mode-confabulation/work-notes.md)) AC8 manual gate findings — the empirical evidence that motivates `INV-V001`.
- Read user's stated rule (2026-05-28): *"never rely on enumeration of 'forbidden phrases'."*
- Confirmed sister plan ([inv-a005-structural-faithfulness](../inv-a005-structural-faithfulness/)) addresses the canonical INV-A005 case; this plan generalizes.

**Audit headline numbers** (Explore-agent report, 2026-05-28):

| Category | Count | Sites |
|----------|-------|-------|
| **Primary load-bearing** | 4 | `_FORBIDDEN_PHRASES` + `_STRUCTURAL_FAILURE_SIGNALS` + `_GENOMECLAW_HTTP_ERROR_PATTERN` in test_invA005_*; `_CATALOGUE_ROWS` in test_agent_system_prompt_contract; §INV-A005 catalogue in agent prompt; prose returns in nemoclaw-plugin/src/index.ts |
| **Backstop (non-load-bearing)** | Many (~20-30) | Prompt-content gates in test_agent_system_prompt_contract.py (mostly assert "X" in text for protocol-concept presence) |
| **Structural (different class)** | 1 | `_FORBIDDEN_ARGV_PATTERNS` in test_invP003_*.py |
| **Future-plan** | 1 | agent-replay-harness-for-prompt-regression.md stub (superseded by sister plan) |
| **Integration smoke checks** | Some | `"HTTP 422" not in reply` style — backstop, not agent-behaviour gates |

→ **All 4 primary sites are within sister plan's scope.** This plan's Phase 1 audit verifies, Phase 2 annotates the backstop/structural sites, Phase 3 enforces, Phase 4 promotes.

**Applicable Invariants**:
- `INV-V001` (proposed) — promoted in Phase 4.
- `INV-A005` v1.22 — sister plan's deliverable; this plan respects it.
- `INV-A006` (sister plan's proposal) — same lineage; architectural counterpart.
- `INV-T001` — adjacent precedent (verification-discipline for external tools).

**Key Insights**:
- The audit report makes clear that **the sister plan's structural fix is the high-leverage move.** Once the four primary sites are eliminated, the rest of the cleanup is annotation discipline + a discovery test — not new mechanisms.
- **`INV-V*` as a new category** is the right home: verification methodology is a distinct concern from runtime invariants (D / E / P / R / C) or agent-cognition invariants (A) or tool-integration invariants (T). Future verification-discipline rules get a natural slot here.
- The user's preferred architectural pattern (multi-turn raw-returns reasoning) is the sister plan's responsibility; THIS plan's responsibility is the *meta-rule* (no phrase enumeration in any verification mechanism).
- Sequencing: sister plan Phase 1–3 must land before this plan's Phase 3 (the discovery test can't pass while the primary sites still exist).

**Completed Today**:
- [x] Filed this plan: spec.md, development-plan.md, phases/phase-1.md, phases/phase-2.md, phases/phase-3.md, phases/phase-4.md, work-notes.md.
- [x] Audit summary captured (above).
- [x] Sister plan cross-references in place.

**Decisions Made**:
- **Annotation-driven enforcement** (not source-code prohibition). Each site that's allowed (backstop or structural) carries an explicit `# INV-V001-{backstop,allow}:` annotation. Discovery test reads annotations, not source semantics. Simpler + more transparent. Documented in `phase-3.md`.
- **New `INV-V*` category** introduced for verification-methodology rules. Cleaner than slotting under `INV-T*`.
- **Sequence: sister plan first, this plan after.** Phase 1 audit can interleave with sister plan's work; Phase 2 cleanup must wait until sister plan's Phase 1-3 lands (so the primary sites are eliminated before annotation cleanup runs). Phase 3 + 4 sequence after.
- **Plan-protocol + test-engineer-skill updates ship in Phase 4** alongside the formal invariant promotion. Single landing of all the docs that teach the rule.

**Blockers / Issues**:
- None for plan filing. Sequencing-coupled with sister plan; coordinate during implementation.

**Next Steps**:
1. **User review** of both plans (this one + sister plan).
2. If approved: begin sister plan's Phase 1 (plugin structured envelopes) — this plan's Phase 1 audit interleaves.

---

## Phase Progress

### Phase 1: Audit
**Status**: **Complete** (2026-05-28). Findings at [phases/phase-1-audit-findings.md](phases/phase-1-audit-findings.md). 4 primary sites (all sister-plan scope), ~22 backstops in 1 file, 1 structural site, 1 superseded plan stub.

### Phase 2: Cleanup — Annotate or Replace
**Status**: Pending (sequenced after sister plan Phases 1–3)

### Phase 3: Meta-Discovery Test
**Status**: Pending

### Phase 4: Promote INV-V001 + Update Planning Docs
**Status**: Pending

---

## Key Decisions

### Decision 1: Annotation-driven enforcement
**Date**: 2026-05-28
**Context**: How does the discovery test in Phase 3 distinguish "load-bearing forbidden-phrase enumeration" from "non-load-bearing sanity backstop" from "structural regex (different class)"?
**Decision**: Require inline annotation comments at every string-tuple / `assert "X" in text` site. Two tokens: `# INV-V001-backstop:` (sanity / regression pin) + `# INV-V001-allow:` (structural, explicitly waived). Discovery test fails any unannotated site.
**Rationale**: Simpler than AST analysis. More transparent — the rule's rationale is visible at every site. Forces a moment-of-pause when introducing a new substring tuple ("do I need this? can it be structural?").
**Alternatives Considered**: AST walker that detects semantic intent. Rejected as heavier + harder to debug. May escalate if false-positive rate becomes painful.
**Affected Invariants**: `INV-V001` (proposed).

### Decision 2: New `INV-V*` category
**Date**: 2026-05-28
**Context**: Where does `INV-V001` live in the invariants taxonomy?
**Decision**: Introduce new `INV-V*` (Verification Methodology) category, distinct from `INV-T*` (Tool Integration).
**Rationale**: Verification methodology is a discipline-of-discipline — how we check correctness, not what the code does. Different from `INV-T*` which pins external-tool conventions. Cleaner top-level home.
**Alternatives Considered**: slot under `INV-T*`. Rejected; conflates two distinct concerns.

### Decision 3: Sequencing with sister plan
**Date**: 2026-05-28
**Context**: Both plans share scope; should they be one plan?
**Decision**: Two plans. Sister plan ships the canonical fix (INV-A005); this plan generalizes + adds the meta-discovery test. Phase 1 audit of this plan can interleave with sister plan's work; Phase 2 cleanup sequences after sister plan's Phases 1–3.
**Rationale**: Each plan has a coherent scope. Conflating would make a 7-phase mega-plan + harder to review. The hand-off (sister plan eliminates the primary sites; this plan annotates remaining sites + adds enforcement) is clean.

---

## Files Modified

### Created
- [spec.md](spec.md)
- [development-plan.md](development-plan.md)
- [phases/phase-1.md](phases/phase-1.md)
- [phases/phase-2.md](phases/phase-2.md)
- [phases/phase-3.md](phases/phase-3.md)
- [phases/phase-4.md](phases/phase-4.md)
- This file.

### Modified
*(populated as implementation proceeds)*

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] New `INV-V*` category section (Phase 4).
- [ ] New `INV-V001` entry (Phase 4).
- [ ] Invariant Index update (Phase 4).
- [ ] Version bump + changelog (Phase 4).

### Other Documentation
- [ ] [docs/plans/CLAUDE.md](../../CLAUDE.md) — Planning Standards section G (Phase 4).
- [ ] [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) — Test Priorities + Anti-Patterns (Phase 4).

---

## Open Risks & Follow-ups

- **R1 Annotation drift** — developers may add new string-tuples without annotating, only caught at PR time. Mitigation: Phase 4's planning-protocol + test-engineer-skill updates teach the rule upfront.
- **R2 Annotation boundary cases** — borderline backstop-vs-primary calls. Phase 1 audit needs to land a clear categorization heuristic; Phase 2 may revisit.
- **R3 Sister-plan sequencing** — if sister plan stalls, this plan ships Phase 1 (audit) + Phase 4 (docs) only. Phase 2 + 3 wait.
- **R4 Future plugins** — rule extends to any plugin's tool-output verification. Phase 4 wording is generic; no plugin-specific assumptions.

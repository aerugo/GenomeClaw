# Phase 4: Documentation rollup — INVARIANTS.md + architecture.md + plans/CLAUDE.md

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Lift the three new invariants (INV-D005, INV-D006, INV-T001) into the canonical reference documents. Phases 1–3 produced the tests that earn the promotion; Phase 4 makes the rules discoverable + cited by future plans. Add a leading editor's note to the source report pointing at the renumber (`INV-D004 → INV-D005`, `INV-D005 → INV-D006`) so the report's history-of-thought stays linked but readers know the live IDs.

Phase 4 introduces **no new tests** — the promotion is text-only. The verification is "everything still passes + the docs are internally consistent."

## Scope Boundaries

- **In scope**:
  - [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md): three new entries + new `INV-T` category row in ID Convention + Invariant Index appended + Version bumped 1.11 → 1.12 + Last Updated set.
  - [docs/reference/architecture.md](../../../../reference/architecture.md): new §"Path-crossing layers" subsection under §"Host-side packaging"; invariant-traceability table extended with three new rows.
  - [docs/plans/CLAUDE.md](../../../CLAUDE.md): §"TDD Principles" gains a new "Tool-Contract" test category + the real-tool-smoke rule for tool integrations.
  - [docs/reports/path-crossing-discipline.md](../../../../reports/path-crossing-discipline.md): leading editor's note re-aiming reader from the report's draft IDs (`INV-D004`, `INV-D005`) to the live IDs (`INV-D005`, `INV-D006`).
- **Out of scope**:
  - The root [CLAUDE.md](../../../../../CLAUDE.md) — the five top-level rules don't shift (path-crossing is a derivative of the existing "raw files are source-of-truth", "privacy is default", "derived stores must stay rebuildable" rules; the new INVs are operational fences under those).
  - CI gate on `probe.sh` (deferred to Phase-2 follow-up; not part of this plan).
  - Real-tool smoke — Phase 5 owns it.

## Invariants Enforced in This Phase

None new. The phase **promotes** the texts of:
- **INV-D005** (Identical-Path Bind Mounts for Sibling Containers) — proven by Phase 1 tests.
- **INV-D006** (DooD-Safe Path Annotation) — proven by Phase 3 tests.
- **INV-T001** (External-Tool Conventions Captured as Typed Wrappers) — proven by Phase 2 tests.

---

## TDD Steps

### Step 4.1 — No RED (this phase is doc-only)

There are no new behaviours to test. The verification is two-pronged:

1. **Cross-reference consistency** — every "How to verify" line in the new INVARIANTS.md entries names a test file that already exists (Phases 1–3 produced them). A spot-check script reads each new entry's "How to verify" and `Glob` confirms the named test file exists. Optional; recorded in work-notes.md.
2. **Suite re-run** — the full test suite remains green. INVARIANTS.md edits don't touch code, so any failure indicates an unrelated regression.

### Step 4.2 — GREEN: Documentation Updates

**Files modified**:
- [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md):
  - Bump **Version** 1.11 → 1.12; set **Last Updated** to the merge date.
  - Add a top-of-file note ("v1.12 …") summarising the rollup and citing this plan.
  - **§Invariant ID Convention** — add row `| INV-T | Tool Integration | External-tool wrapper conventions, version pinning, contract probes |`.
  - **§INV-D005**, **§INV-D006**, **§INV-T001** — three full entries following the Rule / Requirements / Where it applies / How to verify shape used by the existing entries.
  - **§Invariant Index** — three new rows.
- [docs/reference/architecture.md](../../../../reference/architecture.md):
  - New §"Path-crossing layers" under §"Host-side packaging" explaining the four layers (shim → toolkit → DooD-sibling → DooD-grandchild) and naming which INV polices each.
  - Invariant-traceability table extended with rows for INV-D005, INV-D006, INV-T001.
- [docs/plans/CLAUDE.md](../../../CLAUDE.md):
  - The "Test Categories" table gains a "Tool-Contract" row (purpose: external-tool conventions are pinned at version + probe; example: `tools/pgsc_calc/probe-output.txt`).
  - Append a one-line callout under §"Real-data smoke as a phase-completion gate": "new tool integrations require a `<Tool>Conventions` dataclass + probe-output golden BEFORE the wrapper ships (INV-T001)".
- [docs/reports/path-crossing-discipline.md](../../../../reports/path-crossing-discipline.md):
  - Insert a leading editor's note above the existing TL;DR explaining the renumber: the report drafted `INV-D004 / INV-D005 / INV-T001`; the live IDs are `INV-D005 / INV-D006 / INV-T001` because INV-D004 was already taken (Destructive Operations Require Explicit Confirmation). The report stays readable as historical context; the live INVs are the source of truth.

### Step 4.3 — REFACTOR: Verify cross-references

After the edits land:
- Run `grep -n "INV-D005\|INV-D006\|INV-T001"` across [docs/](../../../../) to confirm every cross-reference points at the live IDs (no lingering draft IDs except in the report's history-of-thought paragraphs).
- Run the full test suite one last time. Suite count should be **unchanged** from end-of-Phase-3 (677 passed).

---

## Files

| Action | Path | Purpose |
| --- | --- | --- |
| MODIFY | [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) | Add three new entries + new INV-T category row + bump version |
| MODIFY | [docs/reference/architecture.md](../../../../reference/architecture.md) | Add §Path-crossing layers + traceability rows |
| MODIFY | [docs/plans/CLAUDE.md](../../../CLAUDE.md) | Add Tool-Contract category + INV-T001 callout |
| MODIFY | [docs/reports/path-crossing-discipline.md](../../../../reports/path-crossing-discipline.md) | Leading editor's note on renumber |

## Verification

```bash
# From packages/toolkit/:
uv run pytest tests/unit tests/integration tests/invariants --no-header
# Expected: 677 passed (unchanged from end-of-Phase-3).
```

Manual checks (record in [work-notes.md](../work-notes.md)):
- [ ] `docs/reference/INVARIANTS.md` Version line is 1.12; Last Updated set.
- [ ] Each new entry's "How to verify" points at a test file that exists.
- [ ] No grep hits for the draft IDs (`INV-D004` proposal, `INV-D005` proposal) outside the report's history-of-thought paragraphs.
- [ ] The Invariant Index table has three new rows; the ID Convention table has the new INV-T row.

## Completion Criteria

- [ ] INVARIANTS.md v1.12 landed; three new entries + INV-T category row + Invariant Index updated.
- [ ] architecture.md has the new §Path-crossing layers subsection + traceability rows.
- [ ] docs/plans/CLAUDE.md has the new Tool-Contract category + INV-T001 callout.
- [ ] The report file carries the editor's note.
- [ ] Full test suite green (677 passed expected).
- [ ] [work-notes.md](../work-notes.md) Phase 4 entry written.
- [ ] `development-plan.md` Progress Tracking + Success Criteria updated.
- [ ] `phases/phase-5.md` scaffold created (Phase 5 = real-tool smoke).

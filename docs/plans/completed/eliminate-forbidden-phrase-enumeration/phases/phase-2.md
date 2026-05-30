# Phase 2: Cleanup — Annotate or Replace

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

For every site in Phase 1's audit, perform the documented action: **annotate** non-load-bearing sites with the `# INV-V001-{backstop,allow}:` comment, or **replace** any remaining load-bearing site with a structural / semantic alternative. Sister plan's Phase 1–3 should have eliminated the known load-bearing INV-A005 sites; this phase verifies and handles any others Phase 1 surfaced.

## Scope Boundaries

- **In scope**:
  - All sites listed in `phases/phase-1-audit-findings.md`.
  - Inline comment annotations at each substring-tuple / `assert "X" in ...` block.
  - Replacing any newly-discovered "primary" sites (expectation: none beyond sister plan's coverage).
- **Out of scope**:
  - The discovery test (Phase 3).
  - `INV-V001` formal promotion (Phase 4).

## Invariants Enforced in This Phase

- **NEW `INV-V001`** (provisional — formal promotion in Phase 4). Phase 2's annotations are the data the discovery test reads in Phase 3.

---

## Steps

### Step 2.1 — Annotate backstop sites

For every site Phase 1 categorized as **backstop**, add an inline comment:

```python
# INV-V001-backstop: <one-line rationale — what real correctness gate this backs up>
_SOME_TUPLE = (
    "...",
    "...",
)
```

OR for inline `assert "X" in text` patterns:

```python
# INV-V001-backstop: documents that prompt teaches concept X; agent rephrasings still pass real behaviour checks
assert "concept-marker" in text, "prompt must name concept-marker"
```

The annotation comment must be on the line immediately above the literal/assertion, OR within 3 lines preceding it.

### Step 2.2 — Annotate structural sites

For sites categorized as **structural** (e.g., regex patterns in `test_invP003_*`):

```python
# INV-V001-allow: regex matches argv-shape anti-patterns (structural, not paraphrase enumeration)
_FORBIDDEN_ARGV_PATTERNS = (
    r"python3?\s+-c\s+.*b64decode",
    ...
)
```

### Step 2.3 — Replace any remaining primary sites

If Phase 1 found primary sites NOT covered by the sister plan:

- File a follow-up plan immediately if the replacement is substantive.
- For lighter cases, do the replacement in-line under this phase: structural envelope (per INV-A006), schema-field check, or LLM-judge.

### Step 2.4 — Retract / amend future-plan proposals

For each plan in `docs/plans/active/` proposing phrase enumeration:

- If the plan is the sister plan's now-superseded replay-harness stub: move to `completed/` with the supersession note (this is the sister plan's Phase 3 action; verify it's done).
- Otherwise: amend the plan's spec/development-plan to align with `INV-V001` + reference this plan.

### Step 2.5 — Verify existing tests still pass

The annotations are comments — no behavioural change. Run the full test suite to confirm no regression:

```bash
cd packages/toolkit
uv run pytest tests/invariants/ tests/integration/ -x
```

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| Each site identified in Phase 1 audit | MODIFY | Add inline annotation comment. |
| Future-plan files identified in audit | MODIFY / MOVE | Retract or amend. |

---

## Verification

```bash
# After annotations, the discovery test (Phase 3) will pass.
# For now, verify each annotation is correctly placed:
grep -rn "INV-V001-backstop\|INV-V001-allow" packages/toolkit/tests/ packages/nemoclaw-plugin/tests/

# Existing tests still green:
cd packages/toolkit
uv run pytest tests/invariants/ tests/integration/ -x
```

---

## Completion Criteria

- [ ] Every site from Phase 1's audit has the appropriate annotation OR has been replaced.
- [ ] All previously-passing tests still pass.
- [ ] No newly-discovered "primary" site remains unhandled (replaced inline OR follow-up plan filed).
- [ ] Future-plan retractions / amendments are done.
- [ ] `work-notes.md` updated with summary of changes.
- [ ] Phase 2 row in `development-plan.md` progress table set to **Complete**.

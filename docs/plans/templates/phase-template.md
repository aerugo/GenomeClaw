# Phase X: <Name>

**Status**: Pending | In Progress | Complete
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD or blank>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

<What this phase accomplishes. One paragraph.>

## Scope Boundaries

- **In scope**: <list>
- **Out of scope**: <list — explicitly defer to later phases>

## Invariants Enforced in This Phase

List the `INV-xxx` IDs whose **tests are written or extended in this phase**. Each must map to at least one test in Step X.1.

- **INV-xxx**: <how this phase's tests verify it>
- **INV-xxx**: <how this phase's tests verify it>

---

## TDD Steps

### Step X.1 — RED: Write Failing Tests

For each test, give a name and one-line intent. Tests cite the `INV-xxx` they enforce in their name or docstring where applicable.

**Test cases**:

1. `test_<behavior>` — <what it verifies>
2. `test_<behavior>` — <what it verifies>
3. `test_invXxxx_<behavior>` — <which invariant this enforces>

**Sketch** (language-appropriate, illustrative only):

```text
describe("<unit under test>"):
    test_<behavior>:
        # Arrange
        # Act
        # Assert
```

After writing the tests, run them and **confirm they fail for the intended reason**. Paste the failing output into `work-notes.md`.

### Step X.2 — GREEN: Minimal Implementation

Write the smallest implementation that turns the tests green. Do not pre-emptively add fields, branches, or abstractions that no test exercises.

**Files affected**:
- `<path>`: <what is created/modified>

### Step X.3 — REFACTOR

With tests green:

- Tighten types and names.
- Extract helpers if duplication has actually appeared (rule of three).
- Add comments only where the *why* is non-obvious.
- Re-run tests after each refactor step.

---

## Implementation Details

<Specific technical points relevant to this phase: schema impact, provenance columns, pipeline ordering, redaction logic, etc.>

### Edge Cases to Handle

- <edge case>
- <edge case>

### Error Handling

- <error scenario>: <how to handle, where errors are surfaced>

### Privacy / Egress Notes (if applicable)

- <new boundary, redaction, default-off behavior>

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `<path>` | CREATE | <purpose> |
| `<path>` | MODIFY | <what changes> |
| `<test path>` | CREATE | <what it tests> |

---

## Verification

Exact commands. Replace placeholders with the project's chosen tooling.

```bash
# Run this phase's tests
<test-runner> <path>

# Run all tests
<test-runner>

# Type check
<type-checker>

# Lint
<linter>
```

For pipeline phases, also include:

```bash
# Run the pipeline against the fixture
<pipeline-cmd> --input fixtures/<...> --out data/derived/<run-id>/

# Determinism check
<pipeline-cmd> --input fixtures/<...> --out data/derived/<run-id-2>/
diff -r data/derived/<run-id>/ data/derived/<run-id-2>/
```

---

## Completion Criteria

- [ ] All listed test cases pass
- [ ] Static checks pass (type, lint)
- [ ] Each enforced `INV-xxx` is verified by at least one test in this phase
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures or repo
- [ ] `work-notes.md` updated with RED output, decisions, and final state
- [ ] Phase status updated in `development-plan.md`

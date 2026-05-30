# Phase 3: Meta-Discovery Test for INV-V001

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Implement the discovery test `test_invV001_no_phrase_enumeration_in_agent_output_gates.py` that enforces the `INV-V001` rule going forward. The test walks the relevant test + prompt files, finds string-tuple / list literals touching agent output, and fails if any lacks the required annotation comment.

## Scope Boundaries

- **In scope**:
  - New discovery test file under `packages/toolkit/tests/invariants/`.
  - Detection pattern: module-level `_FOO = ( "x", "y", ... )` literals OR `assert "x" in {reply,text,...}` calls.
  - Annotation parsing: `# INV-V001-backstop:` OR `# INV-V001-allow:` within 3 lines preceding the literal/assertion.
- **Out of scope**:
  - `INV-V001` formal promotion (Phase 4).
  - Detecting patterns OUTSIDE test files (e.g., in plugin source — covered by sister plan's `INV-A006`).
  - AST-level analysis — keep it grep-style for simplicity. False positives can be quieted via explicit allow annotation.

## Invariants Enforced in This Phase

- **NEW `INV-V001`** (provisionally enforced via this discovery test; formally promoted in Phase 4).

---

## TDD Steps

### Step 3.1 — RED: Write the discovery test

The test:

1. Walks file roots: `packages/toolkit/tests/invariants/`, `packages/toolkit/tests/integration/`, `packages/nemoclaw-plugin/tests/`, `packages/nemoclaw-plugin/sandbox/*.md`.
2. For each file, scans for **suspect patterns**:
   - Module-level string-tuple / list literals (regex match for `^_[A-Z_]+:?\s*[:=]\s*(\(|\[)\s*["'].*`).
   - Inline `assert "..." in <agent_output_var>` where the var name suggests agent output (`reply`, `text`, `content`, `response`, `message`, `final_assistant_visible_text`, etc.).
3. For each suspect location, checks if an `INV-V001-backstop:` or `INV-V001-allow:` annotation appears within 3 lines preceding it.
4. Fails the test if any unannotated suspect location remains.

**Test cases**:

- `test_invV001_no_unannotated_phrase_enumeration_in_test_files` — primary. Runs the walker; expects empty list of unannotated sites.
- `test_invV001_discovery_test_detects_synthetic_violation` — confidence check: temporarily inject an un-annotated tuple into a fixture file, run the walker, assert it's flagged, then revert. (Fixture-based; doesn't actually mutate the real test files.)
- `test_invV001_discovery_test_accepts_correctly_annotated_site` — confidence check inverse: annotated site passes.

Run RED: Test 1 should pass after Phase 2's annotations are in place. Tests 2 + 3 are confidence checks.

### Step 3.2 — GREEN: Implement the walker

Simple Python implementation, ~80–120 lines:

```python
# packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]

_SCAN_ROOTS = [
    _REPO_ROOT / "packages" / "toolkit" / "tests" / "invariants",
    _REPO_ROOT / "packages" / "toolkit" / "tests" / "integration",
    _REPO_ROOT / "packages" / "nemoclaw-plugin" / "tests",
]

_SUSPECT_TUPLE = re.compile(r'^_[A-Z][A-Z0-9_]*\s*[:=]\s*[\(\[]\s*["\']', re.MULTILINE)
_SUSPECT_ASSERT = re.compile(
    r'assert\s+["\'][^"\']*["\']\s+in\s+\b(reply|text|content|response|message|finalAssistantVisibleText)\b'
)

_BACKSTOP = "INV-V001-backstop:"
_ALLOW = "INV-V001-allow:"


def _find_unannotated_sites(file_path: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, snippet) for each suspect pattern without annotation."""
    text = file_path.read_text()
    lines = text.splitlines()
    findings = []
    for i, line in enumerate(lines):
        if _SUSPECT_TUPLE.match(line.strip()) or _SUSPECT_ASSERT.search(line):
            # Look back 3 lines for the annotation.
            preceding = "\n".join(lines[max(0, i - 3) : i])
            if _BACKSTOP not in preceding and _ALLOW not in preceding:
                findings.append((i + 1, line.strip()))
    return findings


def test_invV001_no_unannotated_phrase_enumeration_in_test_files() -> None:
    """INV-V001: agent-output verification gates must not enumerate forbidden phrases.

    Every string-tuple/list literal or inline substring-in-reply assertion under
    scan roots must carry an INV-V001-{backstop,allow}: annotation comment.
    """
    violations: dict[str, list[tuple[int, str]]] = {}
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            findings = _find_unannotated_sites(path)
            if findings:
                violations[str(path.relative_to(_REPO_ROOT))] = findings

    assert not violations, (
        "INV-V001 violation: un-annotated phrase enumeration found:\n"
        + "\n".join(
            f"  {fp}:\n    "
            + "\n    ".join(f"line {ln}: {snip}" for ln, snip in finds)
            for fp, finds in violations.items()
        )
    )
```

(Plus the two confidence-check tests; ~30 more lines.)

### Step 3.3 — REFACTOR

- Tune the suspect-pattern regexes if false positives surface in tests/invariants/ that aren't actually agent-output gates.
- Add per-file ignore tokens if needed (e.g., `# INV-V001-skip-file: <rationale>` at the file top, for a file that legitimately contains string tuples for unrelated purposes — though this should be rare).
- Confirm the test runs in <1s.

---

## Implementation Details

### Annotation Placement

Per Phase 2, annotations sit on the line immediately above OR within 3 lines preceding the literal/assertion. The discovery test mirrors this 3-line lookback.

### Why grep-style not AST

AST gives more precise detection (e.g., knowing whether a tuple is actually used as test input, not just defined). But it's heavier and harder to debug. Grep + 3-line annotation lookback is simpler and the user-facing failure message points exactly at the line. If false positives become a problem, escalate to AST in a follow-up.

### Edge Cases

- **String tuples used for non-test purposes** (e.g., configuration in conftest): if these aren't being checked against agent output, they shouldn't trigger. The suspect-pattern regex requires the leading underscore + ALL-CAPS convention to limit false positives. Tune as needed.
- **Multi-line tuple definitions**: the suspect pattern matches the opening line; the lookback covers it.
- **Assertions outside `tests/`**: not scanned. Agent-output gates only live in test files.

### Privacy / Egress Notes

- None.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py` | CREATE | Discovery test. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py -xvs
uv run ruff check tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py

# Confidence-check inverse: temporarily inject a violation, confirm test fails, revert.
```

---

## Completion Criteria

- [ ] Primary discovery test passes against the post-Phase-2 state.
- [ ] Two confidence-check tests pass (synthetic violation flagged; annotated site accepted).
- [ ] Test runs in <1s.
- [ ] `work-notes.md` updated.
- [ ] Phase 3 row in `development-plan.md` progress table set to **Complete**.

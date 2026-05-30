# Phase 3: Structural Enforcement + Live Verification

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Ship the structural test that makes the "agent paraphrases no-data as serialization bug" failure mode loud on any future trace, and verify on the operator's actual data that Q1 + Q4 replies are now accurate.

## Scope Boundaries

- **In scope**: the new invariant test walking trace JSONs for the forbidden paraphrasing pattern; (if Phase 1 confirmed hypothesis #6) promotion of `NEW INV-A004`; live verification by re-running Q1 + Q4 from the demo battery; plan close-out.
- **Out of scope**: catching every possible agent-confabulation pattern beyond this specific phrasing; cleanup of historical trace JSONs.

## Invariants Enforced in This Phase

- **INV-A001** Agent Memory Provenance — the new test enforces it at the reply-prose-vs-trace layer for the specific "serialization bug" phrasing.
- Possibly **NEW INV-A004** — Tool-failure narratives must map to non-zero `toolSummary.failures` OR documented response shapes. Promoted only if Phase 1 confirmed hypothesis #6.

---

## TDD Steps

### Step 3.1 — RED: The confabulation invariant test

`packages/toolkit/tests/invariants/test_invA001_no_serialization_bug_confabulation.py`:

```python
"""INV-A001 — agent reply prose must not claim a 'serialization bug'
unless the trace's toolSummary.failures > 0 OR the response carries
a documented tool_failure shape.

Closes the confabulation failure mode the investigate-genomeclaw-gene-
tool-bug plan diagnosed: in Rounds 1 + 2 of the 2026-05-24 demo, the
agent's reply paraphrased no-data gene-summary responses as
'argument-serialization bug' even though no actual failure was recorded
in the trace.

Walks any trace JSON file under docs/reports/ and asserts the phrase
'serialization bug' / 'argument-serialization bug' in reply text is
accompanied by a real failure signal in the same trace.

The Round 1 + 2 traces are baseline reference for what NOT to produce
— they MAY contain the phrase (preserved as historical artifact). The
test only enforces this for traces dated 2026-05-26 or later (i.e.,
after the fix lands) so we don't have to backfill the historical record.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
REPORTS_DIR = REPO_ROOT / "docs" / "reports"

# Date after which the rule binds. Set to the day Phase 2 lands the fix.
_RULE_BINDS_FROM = date(2026, 5, 26)

# Phrases the agent must not use unless a real failure is in the trace.
_FORBIDDEN_PHRASES = (
    "argument-serialization bug",
    "serialization bug",
)


def _trace_date(path: Path) -> date | None:
    """Extract the date from a demo-logs path like
    docs/reports/demo-2026-05-26-logs/round3-q1-…trace.json
    or demo-2026-05-25-logs/...
    """
    m = re.search(r"demo-(\d{4})-(\d{2})-(\d{2})-logs", str(path))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _trace_has_real_failure(trace: dict) -> bool:
    """A real tool failure means toolSummary.failures > 0 OR any payload
    carries a tool_failure status field.
    """
    result = trace.get("result") or trace
    meta = result.get("meta", {})
    ts = meta.get("toolSummary", {})
    if ts.get("failures", 0) > 0:
        return True
    for p in result.get("payloads", []):
        if isinstance(p, dict):
            text = p.get("text", "")
            if "tool_failure" in text or "status=tool_failure" in text:
                return True
    return False


@pytest.mark.parametrize("trace_path", sorted(REPORTS_DIR.rglob("*.trace.json")))
def test_invA001_no_serialization_bug_phrasing_without_real_failure(
    trace_path: Path,
) -> None:
    """If a reply names a serialization bug, the trace must have a real failure."""
    trace_date = _trace_date(trace_path)
    if trace_date is None or trace_date < _RULE_BINDS_FROM:
        pytest.skip(
            f"{trace_path.relative_to(REPO_ROOT)} predates the rule's binding "
            f"date {_RULE_BINDS_FROM.isoformat()}"
        )

    trace = json.loads(trace_path.read_text())
    result = trace.get("result") or trace
    reply_text = " ".join(
        p.get("text", "") for p in result.get("payloads", []) if isinstance(p, dict)
    ).lower()

    for phrase in _FORBIDDEN_PHRASES:
        if phrase in reply_text:
            if not _trace_has_real_failure(trace):
                pytest.fail(
                    f"INV-A001 violation in {trace_path.relative_to(REPO_ROOT)}: "
                    f"reply text contains forbidden phrase {phrase!r} but the "
                    f"trace's toolSummary.failures is 0 and no tool_failure "
                    f"payload exists. The agent is paraphrasing a no-data "
                    f"response as a bug — see "
                    f"docs/plans/completed/investigate-genomeclaw-gene-tool-bug/."
                )
```

Today this test passes (no traces past 2026-05-26 exist yet). After Phase 2's fix lands and Phase 3 re-runs the demo questions producing 2026-05-26+ traces, the test enforces the rule on the new traces. If a future regression reintroduces the confabulation, the test fails loudly.

### Step 3.2 — (If hypothesis #6) Promote `NEW INV-A004`

Add to `docs/reference/INVARIANTS.md` between INV-A003 and INV-C001:

```markdown
## INV-A004: Tool-Failure Narratives Match Trace Evidence

**Rule** *(v1.18, 2026-05-XX)*: Agent reply prose that claims a tool
failed (or paraphrases a tool failure with terms like "bug", "error",
"failure", "broken", "couldn't get") MUST be traceable to either
(a) `toolSummary.failures > 0` in the same trace, OR (b) a documented
tool-response shape that carries a structured failure field
(`status: "tool_failure"` or similar).

**Rationale**: agent paraphrasing of no-data responses as "tool failure"
is its own class of confabulation — distinct from INV-A001's evidence-
ref discipline because the failure narrative isn't about a biomedical
claim, it's about the agent's own tooling. Without this rule, users
reading agent replies can't tell whether "the tool failed for X" means
"the tool genuinely failed" or "the agent decided to characterise an
empty response that way".

The 2026-05-24 onboard-persistent-agent-fix demo session surfaced the
canonical example: `genomeclaw_gene` returned no-data for some genes;
the agent paraphrased the empty response as "argument-serialization
bug" even though `toolSummary.failures` was 0.

**Requirements**:
- Where the agent reply contains tool-failure phrasing about a specific
  tool, the trace's `executionTrace` MUST record at least one invocation
  of that tool that returned a failure (HTTP 5xx, raised exception, OR
  a documented `tool_failure` response shape).
- Tools MUST return uniform response shapes: success / no-data /
  failure are three distinct response shapes, not one shape the agent
  has to disambiguate from natural language.
- The agent system prompt MUST document how to paraphrase each shape.

**Where it applies**:
- Agent reply text (in trace JSON `result.payloads[].text`).
- Plugin tool response shapes (`packages/nemoclaw-plugin/src/index.ts`).
- The agent system prompt's tool-error-handling section.

**How to verify**:
- `packages/toolkit/tests/invariants/test_invA001_no_serialization_bug_confabulation.py`
  walks trace JSONs + asserts the rule for the specific "serialization
  bug" phrasing.
- Future extensions may add per-tool variants of the same shape.
```

Update INVARIANTS.md's Version + Last Updated + Invariant Index + changelog.

### Step 3.3 — Live verification

Re-run Q1 + Q4 from the demo battery:

```bash
# (after starting host service + sandbox per onboard-persistent-agent-fix)
docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY="$OPENAI_API_KEY" --user sandbox \
  "$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)" \
  bash -c 'openclaw agent --local --json --agent genomeclaw \
    --message "Is there anything serious in my DNA I should know about — something I should bring up with a doctor?"' \
  > /tmp/q1-post-fix.trace.json

# Similarly for Q4 (caffeine).
```

Read the replies. Assertions:

- No occurrence of "serialization bug" or "argument-serialization bug" in the reply.
- Specific gene names the agent attempted should be named with their actual no-data outcome ("not in the curated panel for this run", or actual coverage data).

Capture into `docs/reports/demo-2026-05-26-logs/` (or whatever date) and write a short verification note in `work-notes.md`.

### Step 3.4 — Plan close-out

- Move `docs/plans/active/investigate-genomeclaw-gene-tool-bug/` → `docs/plans/completed/investigate-genomeclaw-gene-tool-bug/`.
- Update status fields to Complete; add completion date.
- Append close-out session entry to work-notes.md.
- Update the original demo-questions report's "Bugs" section: cross-link to the closed plan + the new accurate behaviour.

---

## Implementation Details

### Edge Cases to Handle

- **Trace JSONs with no payloads / partial parse failures**: the invariant test should skip gracefully (not error) on malformed traces.
- **Future traces from sub-agents** (via `sessions_spawn`): the per-trace walk needs to cover sub-agent traces too; check the trace schema for nested traces.

### Error Handling

- Test failures point at the specific trace path + the forbidden phrase + the proposed fix (link to the closed plan).

### Privacy / Egress Notes

- Test reads local trace JSONs only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/invariants/test_invA001_no_serialization_bug_confabulation.py` | CREATE | Structural enforcement of the no-paraphrasing-no-data-as-bug rule. |
| `docs/reference/INVARIANTS.md` | MODIFY (if hypothesis #6 confirmed) | Promote NEW INV-A004; bump version; add changelog entry. |
| `docs/reports/demo-2026-05-26-logs/` (or similar dated dir) | CREATE | Live re-verification traces for Q1 + Q4. |
| `docs/plans/active/investigate-genomeclaw-gene-tool-bug/` → `completed/` | MOVE | Plan close-out. |
| `docs/reports/genomeclaw-demo-questions-2026-05-25-verification.md` | MODIFY | Update the gene-tool-bug section: link to the closed plan + the new accurate behaviour. |

---

## Verification

```bash
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_invA001_no_serialization_bug_confabulation.py -v
# All traces dated < 2026-05-26 SKIP cleanly; any 2026-05-26+ traces PASS.

# Live verification — capture new traces
# (commands per Step 3.3)

# Re-run the invariant test against the new traces
.venv/bin/pytest tests/invariants/test_invA001_no_serialization_bug_confabulation.py -v
# New traces PASS — no forbidden phrasing in the post-fix agent prose.
```

---

## Completion Criteria

- [ ] Invariant test exists + passes on all extant traces.
- [ ] Live Q1 + Q4 re-run produces replies free of "serialization bug" phrasing.
- [ ] (If hypothesis #6 confirmed) NEW INV-A004 promoted into INVARIANTS.md.
- [ ] All existing tests still pass.
- [ ] Plan moved to `completed/`.
- [ ] Demo report cross-link updated.
- [ ] `work-notes.md` carries the close-out session entry.

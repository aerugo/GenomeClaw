# Phase 5: LLM-Judge Harness + Delete the Literal-Token Walker

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Replace the v1.22 literal-`error_type`-token walker with a **semantic LLM-judge harness**. Given a captured `(trace.json, trajectory.jsonl)` pair, the judge calls `gpt-5.5` to evaluate whether the agent's reply is a **faithful + understandable** interpretation of the tool-result data. Update `INVARIANTS.md` to v1.24 with the `INV-A005` v1.23 rule rewrite.

## Scope Boundaries

- **In scope**:
  - New `packages/toolkit/tests/agent_replay/` directory: conftest, judge driver, scenario test.
  - **DELETION** of `test_invA005_v122_reply_quotes_error_type_for_every_failure` from [test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py).
  - INVARIANTS.md `INV-A005` rule rewrite v1.22 → v1.23.
  - Conditional: `INV-D010` promotion if Phase 3 decided to.
- **Out of scope**:
  - Scenario tests with mocked envelopes (the parent plan deferred those; this one only does the judge over real captured traces).
  - Multiple judge prompts — single prompt that asks the meta-question "faithful + understandable."
  - Re-running the AC8 gate (Phase 6).

## Invariants Enforced in This Phase

- **INV-A005** v1.23 (formally promoted here via INVARIANTS.md update).
- **INV-V001** — honored. LLM-judge IS the sanctioned semantic alternative.
- **INV-P001** Privacy Default — judge calls gated by `GENOMECLAW_REPLAY_LLM=gpt-5.5` env var.

---

## TDD Steps

### Step 5.1 — RED: Write the Failing Scenario Test

**Test**:

`test_invA005_v123_reply_is_faithful_to_trajectory` (parametrized over captured trace files with sibling trajectory files):

1. Load `(trace_path, trajectory_path)` pair.
2. Extract the agent's final reply text from the trace.
3. Extract per-tool-call records from the trajectory's last `model.completed`'s `messagesSnapshot`.
4. Pass `(trajectory_summary, reply_text)` to the LLM-judge.
5. Assert the judge returns `faithful=True` AND `understandable=True`.

Default-skip when `GENOMECLAW_REPLAY_LLM` is unset.

Run RED. With the env var set, expect the test to fail because:
- The judge driver doesn't exist yet.
- The test references files that don't exist.

### Step 5.2 — GREEN: Implement the Judge + Run Against Two Known Traces

**Conftest** (`tests/agent_replay/conftest.py`):

```python
import os
import pytest


@pytest.fixture(scope="session")
def replay_llm_model() -> str:
    model = os.environ.get("GENOMECLAW_REPLAY_LLM")
    if not model:
        pytest.skip("GENOMECLAW_REPLAY_LLM not set; INV-A005 v1.23 LLM-judge skipped")
    return model


@pytest.fixture(scope="session")
def openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not set; cannot reach gpt-5.5 for judge calls")
    return key
```

**Judge driver** (`tests/agent_replay/_judge.py`):

```python
import json
import httpx
from typing import TypedDict


class JudgeVerdict(TypedDict):
    faithful: bool
    understandable: bool
    violations: list[str]


_SYSTEM_PROMPT = """You are an independent auditor evaluating whether an AI agent's reply to a user
faithfully reflects the data it received from its tools.

You will be given:
1. A summary of the tool calls the agent made + the result envelopes they returned (per-tool: tool name, success/failure status, key fields).
2. The agent's final reply text to the user.

Your evaluation has two axes:
- **faithful**: every claim the reply makes about the tool calls (succeeded/failed, what was found, what error happened, what the cause was) is consistent with the tool-result data. The reply does NOT invent failures that didn't happen, claim successes that did fail, conflate different failure modes, or misattribute causes. Quoting tool-result data verbatim is NOT required; the rule is meaning-faithfulness, not transcription.
- **understandable**: the reply uses natural language a user can act on. It translates structured data (error_type enums, diagnostic_trace fields, etc.) into plain explanations. Robotic JSON-field transcription is NOT understandable.

Return STRICT JSON: `{"faithful": <bool>, "understandable": <bool>, "violations": [<string>, ...]}`.
- `violations` is the list of specific issues found (cite the reply text excerpt + what's wrong with it).
- An empty violations list with both `true` flags is a clean pass.
"""


def evaluate(
    trajectory_summary: str,
    reply_text: str,
    api_key: str,
    model: str = "gpt-5.5",
) -> JudgeVerdict:
    user = f"=== TRAJECTORY SUMMARY ===\n{trajectory_summary}\n\n=== AGENT REPLY ===\n{reply_text}"
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)
```

(Sketch — adapt to OpenAI's actual chat completions schema.)

**Trajectory summarizer** (helper): condenses `messagesSnapshot` into a compact per-tool list with key fields. Avoids dumping the entire raw trajectory (cost + judge attention).

**Scenario test**:

```python
@pytest.mark.parametrize("trace_path", _TRACE_PATHS_WITH_TRAJECTORY)
def test_invA005_v123_reply_is_faithful_to_trajectory(
    trace_path, replay_llm_model, openai_api_key
):
    trajectory_path = trace_path.with_name(...)
    summary = _summarize_trajectory(trajectory_path)
    reply = _final_reply_text(trace_path)

    verdict = evaluate(summary, reply, openai_api_key, model=replay_llm_model)

    assert verdict["faithful"], f"reply not faithful: {verdict['violations']}"
    assert verdict["understandable"], f"reply not understandable: {verdict['violations']}"
```

Run the test against both:
- The v1.22 captured trace (`stage2-gate-muscle-question.trace.json`) — judge should likely flag it as "not understandable" (robotic transcription).
- The Phase 6 post-fix trace (when it lands) — judge should pass.

### Step 5.3 — DELETE the Literal-Token Walker

Remove `test_invA005_v123_reply_quotes_error_type_for_every_failure` (and the v1.22 name if not yet renamed) from `test_invA005_no_serialization_bug_confabulation.py`. The trajectory-walking helpers (`_trajectory_failures`, `_final_assistant_text`) MAY be kept and reused by the judge driver, OR deleted if the judge has its own summarization path. Decide during implementation.

If the entire file becomes empty after the deletion: delete the file. Document in `work-notes.md`.

### Step 5.4 — Update INVARIANTS.md to v1.24

- **Version bump** v1.23 → v1.24.
- **Changelog entry** for v1.24 explaining the `INV-A005` rule rewrite: v1.22's verbatim-quoting mechanism was the wrong fix; v1.23's semantic verification (LLM-judge) is the correct mechanism. Cite this plan.
- **Rewrite the `INV-A005` rule section**:
  - Drop the v1.22 mechanism (literal `error_type` quoting).
  - Add the v1.23 mechanism: faithful + understandable synthesis, verified by LLM-judge over the trajectory file.
  - Keep the four `error_type` enum values + structural type discipline (still relevant for agent reasoning).
  - Cross-link to `INV-V001` (LLM-judge as a sanctioned alternative).
- **Optional: promote `INV-D010`** if Phase 3 decided to.

### Step 5.5 — REFACTOR

- Run the full invariants suite + plugin tests to confirm nothing else broke.
- Tune the judge's system prompt if the v1.22 trace verdict isn't intuitive (e.g., judge marks robotic transcription as "faithful" — adjust the rubric).
- Confirm default-skip works (`pytest tests/agent_replay/` with no env var skips cleanly).

---

## Implementation Details

### Judge Prompt Calibration

The system prompt distinguishes:
- **Faithful**: meaning-consistent with tool data. False claims, invented causes, conflated failures → not faithful.
- **Understandable**: natural language, user-actionable. Robotic JSON transcription → not understandable.

If real-world traces produce inconsistent judge verdicts, iterate on the system prompt. Key calibration question: does the judge flag the v1.22 captured trace? It SHOULD — that's the textbook robotic transcription the v1.23 work corrects.

### Trajectory Summarization

The raw `messagesSnapshot` is huge (~50 messages × ~1KB each). Summarize before sending to the judge:

```python
def _summarize_trajectory(trajectory_path: Path) -> str:
    """Produce a compact per-tool-call summary suitable for judge input."""
    # Read trajectory; pick the latest model.completed's messagesSnapshot.
    # For each toolResult message: extract toolName, status (parsed from envelope JSON), key fields.
    # For each assistant message with tool_calls: extract tool names + arg summaries.
    # Output as a structured markdown-like document.
    ...
```

The summary is the load-bearing input. Bad summary = bad judge verdict.

### Edge Cases

- **No tool calls in trajectory**: no failures to evaluate. Test skips.
- **Reply is empty / refusal**: judge probably flags both axes as false. Acceptable as long as the rubric is honest.
- **Trace pre-dates v1.23**: skip cleanly per the date-binding (set `_RULE_BINDS_FROM` to the day Phase 4 + 5 ship).

### Cost / Flakiness

- Each judge call: one `gpt-5.5` invocation. Cost ~$0.05 per scenario.
- Default-skip preserves CI budget.
- Determinism: `temperature=0` + `response_format=json_object`. Marginal flake possible; if observed, add retry-once logic.

### Privacy / Egress Notes

- Same egress destination (`api.openai.com` via existing allowlist).
- Trajectory contents may include genomic context (gene symbols, PRS IDs) — same as what the agent already sees + sends to OpenAI.
- No new sensitive-data surface.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/agent_replay/__init__.py` | CREATE | Test package marker. |
| `packages/toolkit/tests/agent_replay/conftest.py` | CREATE | Env-gated LLM client + skip-when-unset. |
| `packages/toolkit/tests/agent_replay/_judge.py` | CREATE | Judge driver: httpx → OpenAI Chat Completions API. |
| `packages/toolkit/tests/agent_replay/_summarize.py` | CREATE | Trajectory-to-summary helper. |
| `packages/toolkit/tests/agent_replay/test_invA005_v123_reply_is_faithful_to_trajectory.py` | CREATE | Parametrized scenario test calling the judge. |
| [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | MODIFY/DELETE | Remove the literal-token walker; possibly delete the whole file. |
| [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) | MODIFY | Version bump v1.24; `INV-A005` rule rewrite; (optional) `INV-D010` promotion. |

---

## Verification

```bash
cd packages/toolkit

# Default skip
uv run pytest tests/agent_replay/ -v
# expect: SKIPPED (GENOMECLAW_REPLAY_LLM not set)

# Active judge run
GENOMECLAW_REPLAY_LLM=gpt-5.5 OPENAI_API_KEY=... uv run pytest tests/agent_replay/ -xvs

# Confirm literal-token walker is gone
grep -rn "v122_reply_quotes_error_type" tests/  # should return nothing
grep -rn "v123_reply_quotes_error_type" tests/  # should ALSO return nothing — the v1.23 mechanism is judge-based

# Full invariants suite
uv run pytest tests/invariants/ -x
```

---

## Completion Criteria

- [ ] `tests/agent_replay/` directory created with conftest, judge driver, summarizer, scenario test.
- [ ] Default `pytest tests/agent_replay/` emits SKIPPED.
- [ ] With env var set: judge runs against the v1.22 captured trace + flags it (proof the judge catches transcription).
- [ ] With env var set: judge runs against the Phase 6 post-fix trace + passes (proof the rubric accepts good synthesis).
- [ ] `test_invA005_v122_reply_quotes_error_type_for_every_failure` DELETED.
- [ ] `INVARIANTS.md` v1.24 with `INV-A005` v1.23 rule rewrite.
- [ ] Existing tests still pass.
- [ ] `work-notes.md` updated with judge prompt iterations + final calibration notes.
- [ ] Phase 5 row in `development-plan.md` progress table set to **Complete**.

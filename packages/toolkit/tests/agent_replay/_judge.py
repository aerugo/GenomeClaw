"""LLM-judge driver for INV-A005 v1.23 semantic verification.

Sends `(trajectory_summary, reply_text)` to `gpt-5.5` via the OpenAI Chat
Completions API; parses a strict JSON verdict with `faithful` and
`understandable` booleans plus a `violations` list.

Per INV-A005 v1.23:
- **faithful**: every claim the reply makes about tool calls is consistent
  with the tool-result data. No invented failures; no claimed successes
  that actually failed; no conflated failure modes; no misattributed causes.
  Quoting verbatim is NOT required — the rule is meaning-faithfulness.
- **understandable**: the reply uses natural language a user can act on.
  Robotic JSON-field transcription is NOT understandable.

Default-skip preserved at the conftest level — the judge driver itself
is pure; the env-gating is in [conftest.py](conftest.py).
"""

from __future__ import annotations

import json
from typing import TypedDict

import httpx


class JudgeVerdict(TypedDict):
    faithful: bool
    understandable: bool
    violations: list[str]


_JUDGE_SYSTEM_PROMPT = """You are an independent auditor evaluating whether an AI agent's reply to a user
faithfully reflects the data it received from its tools, AND whether it
presents that data in a way a non-technical user can act on.

You will be given:
1. A summary of the tool calls the agent made + the result envelopes they returned
   (per-tool: tool name, success/failure status with error_type, key structured fields).
2. The agent's final reply text to the user.

You evaluate on TWO axes:

**faithful**: every claim the reply makes about the tool calls (succeeded /
failed, what was found, what error happened, what the cause was) is consistent
with the tool-result data. The reply does NOT invent failures that didn't
happen, claim successes that did fail, conflate different failure modes,
or misattribute causes. Quoting tool-result data verbatim is NOT required;
the rule is meaning-faithfulness, not transcription. Reasonable paraphrase
+ correct synthesis is faithful.

**understandable**: the reply uses natural language a non-technical user
can act on. It translates structured fields (error_type enums,
diagnostic.stage, http_path, etc.) into plain explanations. **Robotic
JSON-field transcription** (e.g., `"error_type: network_error"` quoted
verbatim in the user-facing reply) is NOT understandable — that's
transcription, not synthesis. A reply that READS LIKE a JSON dump fails
this axis even if it's technically accurate.

Return STRICT JSON with no additional commentary:
  {"faithful": <bool>, "understandable": <bool>, "violations": [<string>, ...]}

`violations` is the list of specific issues found — each item should
quote a short snippet of the reply text and explain what's wrong with it.
Empty `violations` with both `true` flags = clean pass.
"""


def evaluate(
    trajectory_summary: str,
    reply_text: str,
    api_key: str,
    model: str = "gpt-5.5",
    timeout_s: float = 90.0,
) -> JudgeVerdict:
    """Send `(trajectory_summary, reply_text)` to the LLM-judge; return verdict.

    Uses OpenAI Chat Completions API with `response_format=json_object` for
    strict JSON output + `temperature=0` for determinism. Raises
    `httpx.HTTPStatusError` on API failures (let pytest surface real
    failures rather than swallow them).
    """
    user_msg = (
        f"=== TRAJECTORY SUMMARY ===\n{trajectory_summary}\n\n"
        f"=== AGENT REPLY ===\n{reply_text}"
    )

    # Note: gpt-5.x reasoning models reject `temperature=0` (only the default
    # is supported). We omit temperature; the model's default + reasoning
    # discipline produces sufficiently consistent verdicts. If post-deploy
    # flakiness arises, switch to majority-vote of N=3 evaluations.
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=timeout_s,
    )
    resp.raise_for_status()
    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    # Guard against the judge returning unexpected shapes.
    return {
        "faithful": bool(parsed.get("faithful", False)),
        "understandable": bool(parsed.get("understandable", False)),
        "violations": list(parsed.get("violations", [])),
    }

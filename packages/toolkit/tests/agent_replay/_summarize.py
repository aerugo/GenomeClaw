"""Trajectory-to-summary helper for the LLM-judge harness.

The raw `<run-id>.trajectory.jsonl` carries ~50 messages × ~1KB each. The
judge doesn't need that volume — it needs a compact per-tool-call view
showing tool name, status (success/failure with error_type), and key
fields. This module produces that summary.

Used by [test_invA005_v123_reply_is_faithful_to_trajectory](
test_invA005_v123_reply_is_faithful_to_trajectory.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def summarize_trajectory(trajectory_path: Path, max_text_chars: int = 800) -> str:
    """Read a `.trajectory.jsonl` file; return a compact human-readable
    summary of the tool calls in the latest `model.completed` record.

    Format:
        ## Tool calls in this turn (<count>)

        ### Call 1: <tool_name> (<status>)
        <key fields, truncated to max_text_chars>

        ### Call 2: ...

    `max_text_chars` caps per-call text size to keep the summary digestible.
    """
    records: list[dict[str, Any]] = []
    with trajectory_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    model_completed = [r for r in records if r.get("type") == "model.completed"]
    if not model_completed:
        return "## Tool calls in this turn (0)\n\n(no model.completed records found)"

    snapshot = model_completed[-1].get("data", {}).get("messagesSnapshot", [])
    if not isinstance(snapshot, list):
        return "## Tool calls in this turn (0)\n\n(empty messagesSnapshot)"

    tool_results: list[tuple[str, dict[str, Any]]] = []
    for msg in snapshot:
        if not isinstance(msg, dict) or msg.get("role") != "toolResult":
            continue
        tool_name = str(msg.get("toolName", "?"))
        content = msg.get("content", [])
        text = ""
        if isinstance(content, list) and content:
            first = content[0] if isinstance(content[0], dict) else {}
            text = str(first.get("text", ""))
        # Try to parse envelope JSON
        envelope: dict[str, Any] = {}
        if text.strip().startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    envelope = parsed
            except json.JSONDecodeError:
                pass
        tool_results.append((tool_name, {"text": text, "envelope": envelope}))

    if not tool_results:
        return "## Tool calls in this turn (0)\n\n(no toolResult records found)"

    parts: list[str] = [f"## Tool calls in this turn ({len(tool_results)})"]
    for i, (tool_name, payload) in enumerate(tool_results, start=1):
        env = payload["envelope"]
        status: str
        if env.get("status") == "failed":
            status = f"FAILED ({env.get('error_type', 'unknown')})"
        elif env:
            status = "OK"
        else:
            status = "OK (raw)"

        section = [f"\n### Call {i}: {tool_name} ({status})"]

        if env and env.get("status") == "failed":
            # Failure envelope: surface the structured fields.
            for key in (
                "error_type",
                "host_error",
                "http_status",
                "raw_error",
                "arg_name",
                "value",
                "tool_name",
                "advisory",
            ):
                if key in env:
                    val = env[key]
                    val_str = json.dumps(val) if not isinstance(val, str) else val
                    section.append(f"- `{key}`: {val_str[:max_text_chars]}")
            if "diagnostic" in env and env["diagnostic"] is not None:
                diag = env["diagnostic"]
                section.append("- `diagnostic`:")
                for dk, dv in diag.items():
                    if dv is None or dv == [] or dv == "":
                        continue
                    dv_str = json.dumps(dv) if not isinstance(dv, str) else dv
                    section.append(f"  - `{dk}`: {dv_str[:max_text_chars]}")
        elif env:
            # Success envelope: summarize key fields.
            for key in list(env.keys())[:12]:
                val = env[key]
                if isinstance(val, (dict, list)):
                    val_str = json.dumps(val)
                else:
                    val_str = str(val)
                section.append(f"- `{key}`: {val_str[:max_text_chars]}")
        else:
            # Non-JSON raw text (rare).
            section.append(f"raw text: {payload['text'][:max_text_chars]}")

        parts.append("\n".join(section))

    return "\n".join(parts)


def extract_final_reply(trace_path: Path) -> str:
    """Read a `.trace.json` file (with the typical 6-line log prefix);
    return `meta.finalAssistantVisibleText`."""
    text = trace_path.read_text()
    json_start = text.find("\n{")
    cleaned = text[json_start + 1 :] if json_start >= 0 else text
    trace = json.loads(cleaned)
    result = trace.get("result", trace)
    meta = result.get("meta", {})
    visible = meta.get("finalAssistantVisibleText", "")
    return str(visible) if visible else ""

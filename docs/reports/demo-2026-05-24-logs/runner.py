"""One-shot demo runner — asks 5 layman questions of the GenomeClaw agent.

Uses the live-smoke harness (`tests/_live_smoke/run.py`) to spawn an
ephemeral sandbox container per question, against the operator's real
derived run. Captures each agent JSON trace + plain-text reply to
disk under `docs/reports/demo-2026-05-24-logs/`.

Run from repo root:

    cd packages/toolkit
    OPEN_AI_API_KEY=... GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:port-8645 \\
      DEMO_DERIVED_ROOT=/Volumes/Genome_Work/genomeclaw/derived \\
      .venv/bin/python ../../docs/reports/demo-2026-05-24-logs/runner.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# Make the test harness importable.
HERE = Path(__file__).resolve().parent
TOOLKIT = HERE.parents[2] / "packages" / "toolkit"
sys.path.insert(0, str(TOOLKIT))
sys.path.insert(0, str(TOOLKIT / "src"))

from tests._live_smoke.run import run_agent_in_sandbox  # noqa: E402

QUESTIONS: list[tuple[str, str]] = [
    (
        "q1-serious-risk",
        "Is there anything serious in my DNA I should know about — "
        "something I should bring up with a doctor?",
    ),
    (
        "q2-drug-response",
        "Are there any common medications I'd react to differently than "
        "most people, based on my genes?",
    ),
    (
        "q3-diabetes",
        "Based on my DNA, am I more or less likely than average to "
        "develop type-2 diabetes?",
    ),
    (
        "q4-caffeine",
        "How well do I handle caffeine? Should I cut off coffee earlier "
        "in the day?",
    ),
    (
        "q5-alzheimers",
        "Is my risk of getting Alzheimer's disease higher or lower than "
        "most people's?",
    ),
]


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY (or OPEN_AI_API_KEY) not set", file=sys.stderr)
        return 1

    sandbox_image = os.environ.get(
        "GENOMECLAW_SANDBOX_IMAGE", "genomeclaw/sandbox:port-8645"
    )
    derived_root = Path(
        os.environ.get(
            "DEMO_DERIVED_ROOT", "/Volumes/Genome_Work/genomeclaw/derived"
        )
    )
    if not (derived_root / "CURRENT").exists():
        print(
            f"ERROR: {derived_root}/CURRENT missing — point DEMO_DERIVED_ROOT "
            "at the directory containing derived runs",
            file=sys.stderr,
        )
        return 2

    log_dir = HERE
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log = log_dir / "01-runner.log"

    summary: list[dict] = []
    with run_log.open("w") as logf:

        def log(msg: str) -> None:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            line = f"[{stamp}] {msg}"
            print(line, flush=True)
            logf.write(line + "\n")
            logf.flush()

        log(f"sandbox_image={sandbox_image}")
        log(f"derived_root={derived_root}")
        log(f"CURRENT -> {(derived_root / 'CURRENT').resolve().name}")
        log(f"question count: {len(QUESTIONS)}")

        for slug, question in QUESTIONS:
            log(f"--- {slug} START ---")
            log(f"Q: {question}")
            t0 = time.monotonic()
            trace_path = log_dir / f"{slug}.trace.json"
            reply_path = log_dir / f"{slug}.reply.txt"
            err_path = log_dir / f"{slug}.error.txt"
            entry: dict = {
                "slug": slug,
                "question": question,
                "trace_path": trace_path.name,
                "reply_path": reply_path.name,
            }
            try:
                trace = run_agent_in_sandbox(
                    question,
                    derived_root=derived_root,
                    sandbox_image=sandbox_image,
                    openai_api_key=api_key,
                    timeout_s=360,
                )
            except Exception as exc:
                elapsed = time.monotonic() - t0
                err_path.write_text(
                    f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
                )
                log(f"{slug} FAILED after {elapsed:.1f}s: {exc!r}")
                entry["status"] = "error"
                entry["error_path"] = err_path.name
                entry["elapsed_s"] = round(elapsed, 1)
                summary.append(entry)
                continue

            elapsed = time.monotonic() - t0
            trace_path.write_text(json.dumps(trace, indent=2, sort_keys=False))
            reply_text = _extract_reply_text(trace)
            reply_path.write_text(reply_text)
            tool_calls = _extract_tool_calls(trace)
            log(
                f"{slug} OK in {elapsed:.1f}s: status={trace.get('status')!r}, "
                f"reply chars={len(reply_text)}, tool calls={len(tool_calls)}"
            )
            for tc in tool_calls:
                log(f"    tool: {tc}")
            entry["status"] = trace.get("status")
            entry["elapsed_s"] = round(elapsed, 1)
            entry["reply_chars"] = len(reply_text)
            entry["tool_calls"] = tool_calls
            summary.append(entry)

        (log_dir / "02-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=False)
        )
        log("--- done ---")

    return 0


def _extract_reply_text(trace: dict) -> str:
    """Pull the final assistant-visible reply out of the agent JSON trace."""
    result = trace.get("result") or {}
    payloads = result.get("payloads") or []
    chunks: list[str] = []
    for p in payloads:
        if not isinstance(p, dict):
            continue
        ptype = p.get("type") or p.get("kind")
        # Common shapes openclaw emits.
        if ptype in {"text", "assistant_text", "message"}:
            text = p.get("text") or p.get("content") or ""
            if isinstance(text, list):
                # Some shapes wrap text in [{type:text, text:"..."}].
                for sub in text:
                    if isinstance(sub, dict) and "text" in sub:
                        chunks.append(sub["text"])
            elif isinstance(text, str):
                chunks.append(text)
        elif "text" in p and isinstance(p["text"], str):
            chunks.append(p["text"])
    if chunks:
        return "\n\n".join(c for c in chunks if c).strip()
    # Fallback: dump everything.
    return json.dumps(result, indent=2)


def _extract_tool_calls(trace: dict) -> list[str]:
    """Pull tool-call names from the trace meta block (best-effort)."""
    result = trace.get("result") or {}
    meta = result.get("meta") or {}
    calls = meta.get("tool_calls") or meta.get("toolCalls") or []
    names: list[str] = []
    for c in calls:
        if isinstance(c, dict):
            n = c.get("name") or c.get("tool") or c.get("toolName")
            if n:
                names.append(str(n))
    # Also try to find tool-result payloads.
    for p in (result.get("payloads") or []):
        if isinstance(p, dict):
            ptype = p.get("type") or p.get("kind") or ""
            if "tool" in str(ptype).lower():
                n = p.get("name") or p.get("tool") or p.get("toolName")
                if n:
                    names.append(str(n))
    return names


if __name__ == "__main__":
    sys.exit(main())

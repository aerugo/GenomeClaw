"""INV-A005 v1.23 — Agent reply must be faithful + understandable synthesis
of the rich tool-result data in this turn's trajectory.

The semantic verification mechanism that replaces v1.22's literal-
`error_type`-token walker. Per `INV-V001`, LLM-judge IS a sanctioned
alternative to phrase enumeration.

Parametrized over `docs/reports/**/*.trace.json` pairs that have a sibling
`*.trajectory.jsonl`. For each, the judge reads the structured per-tool-call
records from the trajectory + the agent's reply from the trace and returns
a verdict on whether the reply is:

- **faithful**: meaning-consistent with the tool results (no invented
  failures, no claimed successes that actually failed, no conflated
  causes). Quoting verbatim NOT required.
- **understandable**: natural language a user can act on. Robotic
  JSON-field transcription fails this axis.

Default-skip when `GENOMECLAW_REPLAY_LLM` env var is unset (preserves
`INV-P001`).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from tests.agent_replay._judge import evaluate
from tests.agent_replay._summarize import extract_final_reply, summarize_trajectory

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORTS_DIR = _REPO_ROOT / "docs" / "reports"

# v1.23 binding date — when the analyze-and-present prompt + this judge ship.
# Earlier traces are historical artifacts (ran against v1.22's verbatim-quoting
# prompt; reply style was robotic transcription by design). Skip cleanly.
_RULE_BINDS_FROM = date(2026, 5, 29)


def _trace_date(path: Path) -> date | None:
    m = re.search(r"demo-(\d{4})-(\d{2})-(\d{2})-logs", str(path))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _trajectory_for(trace_path: Path) -> Path | None:
    sib = trace_path.with_name(
        trace_path.name.replace(".trace.json", ".trajectory.jsonl")
    )
    return sib if sib.exists() else None


def _discover_pairs() -> list[Path]:
    if not _REPORTS_DIR.exists():
        return []
    return sorted(_REPORTS_DIR.rglob("*.trace.json"))


_TRACE_PATHS = _discover_pairs()

if not _TRACE_PATHS:
    pytest.skip(
        f"no *.trace.json under {_REPORTS_DIR.relative_to(_REPO_ROOT)}; "
        "LLM-judge requires captured traces to evaluate",
        allow_module_level=True,
    )


@pytest.mark.parametrize("trace_path", _TRACE_PATHS, ids=lambda p: str(p.name))
def test_invA005_v123_reply_is_faithful_to_trajectory(
    trace_path: Path,
    replay_llm_model: str,
    openai_api_key: str,
) -> None:
    """For each captured trace dated >= v1.23 binding with a sibling
    trajectory file, the LLM-judge verifies the agent's reply is both
    faithful (meaning-consistent with tool results) AND understandable
    (natural language, not robotic JSON transcription).

    Default-skip via conftest's env-gate; opt in by exporting
    `GENOMECLAW_REPLAY_LLM=gpt-5.5` + `OPENAI_API_KEY`.
    """
    trace_d = _trace_date(trace_path)
    if trace_d is None:
        pytest.skip(
            f"{trace_path.relative_to(_REPO_ROOT)} has no dated-logs path "
            "prefix; v1.23 binds by capture-date convention"
        )
    if trace_d < _RULE_BINDS_FROM:
        pytest.skip(
            f"{trace_path.relative_to(_REPO_ROOT)} predates v1.23 binding date "
            f"{_RULE_BINDS_FROM.isoformat()}; was captured under the v1.22 "
            "verbatim-quoting prompt — reply style is by-design transcription"
        )

    trajectory_path = _trajectory_for(trace_path)
    if trajectory_path is None:
        pytest.skip(
            f"{trace_path.relative_to(_REPO_ROOT)} has no sibling "
            ".trajectory.jsonl — v1.23 judge requires per-tool-call records"
        )

    summary = summarize_trajectory(trajectory_path)
    reply = extract_final_reply(trace_path)
    if not reply:
        pytest.fail(
            f"{trace_path.relative_to(_REPO_ROOT)} has no "
            "finalAssistantVisibleText — cannot evaluate"
        )

    verdict = evaluate(
        trajectory_summary=summary,
        reply_text=reply,
        api_key=openai_api_key,
        model=replay_llm_model,
    )

    if not verdict["faithful"]:
        pytest.fail(
            f"INV-A005 v1.23: LLM-judge flagged reply as NOT faithful.\n"
            f"trace: {trace_path.relative_to(_REPO_ROOT)}\n"
            f"violations: {verdict['violations']!r}"
        )
    if not verdict["understandable"]:
        pytest.fail(
            f"INV-A005 v1.23: LLM-judge flagged reply as NOT understandable "
            "(reads like JSON transcription, not natural-language synthesis).\n"
            f"trace: {trace_path.relative_to(_REPO_ROOT)}\n"
            f"violations: {verdict['violations']!r}"
        )

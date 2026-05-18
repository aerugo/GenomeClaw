"""Phase 3 slice 1 — Story 9 caffeine live snapshot.

Pins the **behavioural** contract of the agent's research-and-synthesis
protocol against gpt-5.5 + a real (synthetic) derived store. Phase 2 +
2b shipped the static contracts (prompt content gates, baked-config
gates, validator); this test verifies the agent actually executes the
protocol correctly when its tool calls succeed end-to-end.

This is a single `live_llm`-marked test; its prerequisites are:
- `OPENAI_API_KEY` set (auto-skip via [tests/conftest.py](../conftest.py))
- `GENOMECLAW_SANDBOX_IMAGE` set (auto-skip via the same conftest hook)
- `docker` on PATH

The test stages a Story-9 CYP1A2 caffeine slow-metabolizer finding +
runs one agent turn. Structural snapshot assertions:

- HTTP rc == 0 from `openclaw agent --json`
- The reply text is non-empty + mentions CYP1A2 / rs762551 / caffeine.
- The trace contains `web_search` (the agent invoked native search
  per `INV-P001` v1.7 + AC8b).
- The reply cites at least one primary source (URL / PubMed ID /
  variant-keyed evidence ref).
- The trace has no `HTTP 500` markers (regression check — Phase 2a's
  smoke saw this when the staged store was manifest-only).

Cost: each run fires one real OpenAI call (~$0.10 - $0.50 depending on
the response length). Use sparingly; prefer the static gates for
regression coverage.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import STORY9_CYP1A2_FINDINGS, stage_run_with_findings

STORY9_QUESTION = (
    "Quick research question. Looking at my genome the system says I have CYP1A2 "
    "*1F/*1F (rs762551 A/A). What does current literature say about this genotype "
    "and chronic-late-caffeine effects on sleep onset latency? Cite specific PubMed "
    "IDs or URLs from your search; if you can't find current sources, say so explicitly."
)

# Substrings that, if any one appears in the reply, mean the agent
# engaged with the question on its actual subject (rather than punting,
# answering the bootstrap protocol, or going off-topic).
_TOPIC_TOKENS: tuple[str, ...] = ("CYP1A2", "rs762551", "caffeine")

# Patterns that count as a primary-source citation in the reply.
_PRIMARY_SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://\S+"),
    re.compile(r"\bPMID[:\s]+\d+", re.IGNORECASE),
    re.compile(r"\bpubmed\.ncbi\.nlm\.nih\.gov/\d+", re.IGNORECASE),
    re.compile(r"\b(?:RCV|VCV)\d{4,}", re.IGNORECASE),
    re.compile(r"\bclinvar:\S+", re.IGNORECASE),
    re.compile(r"\bpharmgkb:\S+", re.IGNORECASE),
    re.compile(r"\bpgs_catalog:\S+", re.IGNORECASE),
)


@pytest.mark.live_llm
def test_invA001_invA002_invP001_story9_caffeine_live(tmp_path: Path) -> None:
    """One Story-9 turn against gpt-5.5; structural shape of the trace.

    Pins three invariants behaviourally:
    - INV-P001 v1.7 (AC8b): the agent invokes native OpenAI `web_search`
      because the v1.7 default has it on + no managed provider pinned.
    - INV-A001 (behavioural surface): the agent's reply cites at least
      one primary source — the validator's primary-source-required rule
      bound at the *prose layer* this time, not the memory-note layer.
    - INV-A002 (operational floor): the agent answers a genuine
      health-interpretation turn rather than punting to the bootstrap
      protocol or fabricating without sources.
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root = tmp_path / "derived"

    stage_run_with_findings(derived_root, STORY9_CYP1A2_FINDINGS)

    trace = run_agent_in_sandbox(
        STORY9_QUESTION,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=240,
    )

    # 1. Top-level shape: status ok + at least one payload.
    assert trace.get("status") == "ok", (
        f"agent run did not complete cleanly: status={trace.get('status')!r}, "
        f"summary={trace.get('summary')!r}"
    )
    payloads = trace.get("result", {}).get("payloads", [])
    assert payloads, "agent produced no user-facing reply payload"
    reply = payloads[0].get("text", "")
    assert reply, "agent's first payload has empty text"

    # 2. The reply engages with the actual topic (not bootstrap, not generic).
    assert any(token.lower() in reply.lower() for token in _TOPIC_TOKENS), (
        f"agent's reply did not name any of the Story-9 topic tokens "
        f"{list(_TOPIC_TOKENS)!r}; reply prefix: {reply[:300]!r}"
    )

    # 3. INV-P001 v1.7 (AC8b): native web_search was invoked. The trace
    # blob is the canonical place to look — the JSON envelope serialises
    # tool-call structure under a few different keys depending on the
    # gateway-vs-embedded path; substring-search across the whole blob
    # is robust to that variance.
    trace_blob = json.dumps(trace)
    assert "web_search" in trace_blob, (
        "INV-P001 v1.7 / AC8b: trace contains no `web_search` reference; the agent "
        "did not invoke native OpenAI search despite the v1.7 default config "
        "(tools.web.search.enabled: true, no managed provider pinned). "
        f"trace prefix: {trace_blob[:1000]!r}"
    )

    # 4. INV-A001 + INV-E001 prose-layer: at least one primary-source
    # citation in the reply. URL / PMID / variant-keyed ref all qualify.
    has_primary = any(p.search(reply) for p in _PRIMARY_SOURCE_PATTERNS)
    assert has_primary, (
        "INV-A001 prose-surface: agent's reply cites no primary source "
        "(URL / PMID / clinvar: / pharmgkb: / pgs_catalog: ref). "
        f"reply prefix: {reply[:500]!r}"
    )

    # 5. Regression check: no HTTP 500 markers. Phase 2a's smoke had
    # /v1/findings returning 500 because the staged store was manifest-
    # only; this slice's staging step builds a real findings table, so
    # the trace must NOT carry any 500 markers from genomeclaw tool calls.
    assert "HTTP 500" not in trace_blob and '"status_code": 500' not in trace_blob, (
        "regression: trace contains an HTTP 500 marker — the genomeclaw "
        "host service tool calls failed mid-protocol. Slice 1's staging step "
        "should have provided a real findings table.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

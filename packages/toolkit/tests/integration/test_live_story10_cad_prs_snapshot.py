"""Phase 3 slice 2 — Story 10 CAD polygenic risk score live snapshot.

Mirrors the
[user-stories.md Story 10](../../../../docs/reference/user-stories.md)
exchange: a user with a family history of premature CAD asks the agent
whether their genome says anything about CAD risk. The staged finding
is a `clinical-non-actionable` PGS (PGS Catalog `PGS000018`, 87th
percentile in the user's ancestry-matched reference population).

Structural assertions:
- HTTP rc == 0 + non-empty reply.
- Reply names CAD / coronary + the percentile / risk band.
- Reply surfaces calibration framing (population estimate, not a
  pathogenic call; ancestry-matched; modifiable risk levers; etc.) —
  the v1.6 INV-C001 lifestyle/non-actionable contract requires the
  agent NOT to over-elevate this into clinical-actionable territory.
- `web_search` appears in the trace (native search invoked).
- Reply cites at least one primary source.
- Regression: no `HTTP 500` markers.

Cost: one real OpenAI call (~USD $0.20-0.50, ~4 min wall-clock).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import STORY10_CAD_PRS_FINDINGS, stage_run_with_findings

STORY10_QUESTION = (
    "My dad had a heart attack at 58. Is there anything in my genome about "
    "coronary artery disease (CAD) risk? Look at the genomeclaw findings, "
    "then research current literature on PRS interpretation, calibration "
    "across ancestries, and how to frame what a population-level percentile "
    "actually means. Cite specific PubMed IDs or PGS Catalog entries."
)

# Topic match: CAD / coronary mention.
_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bCAD\b"),
    re.compile(r"coronary\s+artery", re.IGNORECASE),
    re.compile(r"coronary\s+disease", re.IGNORECASE),
)

# Percentile / risk-band: the agent must surface the staged "87th
# percentile" OR an equivalent risk-band phrasing (top decile, etc.).
_PERCENTILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b87(?:th|%|st)?\s*(?:percentile|%)", re.IGNORECASE),
    re.compile(r"top\s+decile", re.IGNORECASE),
    re.compile(r"upper\s+decile", re.IGNORECASE),
    re.compile(r"above[- ]average", re.IGNORECASE),
    re.compile(r"\bhigh\s*(?:er)?\s*(?:than\s+average|risk)", re.IGNORECASE),
)

# Calibration / non-actionable framing: at least one of these phrasings
# must appear so the user reads PRS as a population estimate, not a
# clinical call. INV-C001 v1.6 contract.
_CALIBRATION_FRAMING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"population[- ]level", re.IGNORECASE),
    re.compile(r"not\s+a\s+(?:pathogenic|clinical|diagnostic)", re.IGNORECASE),
    re.compile(r"ancestry[- ]matched", re.IGNORECASE),
    re.compile(r"calibrat", re.IGNORECASE),
    re.compile(r"modifiable\s+risk", re.IGNORECASE),
    re.compile(r"lifetime\s+risk", re.IGNORECASE),
    re.compile(r"prior\s+is\s+shifted", re.IGNORECASE),
    re.compile(r"shifted\s+prior", re.IGNORECASE),
    re.compile(r"NOT\s+(?:destiny|fate|determinative)", re.IGNORECASE),
    re.compile(r"context", re.IGNORECASE),  # broad fallback
)

# Primary-source citation patterns — same as Story 4 / Story 9.
_PRIMARY_SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://\S+"),
    re.compile(r"\bPMID[:\s]+\d+", re.IGNORECASE),
    re.compile(r"\bpubmed\.ncbi\.nlm\.nih\.gov/\d+", re.IGNORECASE),
    re.compile(r"\b(?:RCV|VCV)\d{4,}", re.IGNORECASE),
    re.compile(r"\bPGS\d+", re.IGNORECASE),
    re.compile(r"\bclinvar:\S+", re.IGNORECASE),
    re.compile(r"\bpharmgkb:\S+", re.IGNORECASE),
    re.compile(r"\bpgs_catalog:\S+", re.IGNORECASE),
)


@pytest.mark.live_llm
def test_invC001_invP001_story10_cad_prs_live(tmp_path: Path) -> None:
    """Story 10 PRS — CAD polygenic risk score, calibrated framing.

    Pins:
    - `INV-C001` v1.6: PRS findings get calibrated framing (population
      estimate; ancestry-matched; modifiable risk overlap), not
      clinical-actionable language.
    - `INV-P001` v1.7 / AC8b: native OpenAI `web_search` invoked.
    - `INV-A001` (prose surface): reply cites at least one primary source.
    - `INV-E001` (behavioural): reply names CAD + the staged percentile/band.
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root = tmp_path / "derived"

    stage_run_with_findings(derived_root, STORY10_CAD_PRS_FINDINGS)

    trace = run_agent_in_sandbox(
        STORY10_QUESTION,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=240,
    )

    # 1. Top-level shape.
    assert trace.get("status") == "ok", (
        f"agent run did not complete cleanly: status={trace.get('status')!r}"
    )
    payloads = trace.get("result", {}).get("payloads", [])
    assert payloads, "agent produced no user-facing reply payload"
    reply = payloads[0].get("text", "")
    assert reply, "agent's first payload has empty text"

    # 2. Topic match: CAD / coronary.
    assert any(p.search(reply) for p in _TOPIC_PATTERNS), (
        f"agent's reply did not name CAD / coronary; reply prefix: {reply[:300]!r}"
    )

    # 3. Percentile / risk-band surfaced.
    assert any(p.search(reply) for p in _PERCENTILE_PATTERNS), (
        "agent's reply did not surface the percentile or risk-band (87th "
        "percentile, top decile, etc.). The staged finding's percentile is "
        "the key user-facing number; it must appear in the reply.\n"
        f"reply prefix: {reply[:600]!r}"
    )

    # 4. INV-C001 v1.6: calibration framing (PRS as population estimate).
    assert any(p.search(reply) for p in _CALIBRATION_FRAMING_PATTERNS), (
        "INV-C001 v1.6: agent's reply does not include calibration framing "
        "for the PRS (population-level estimate, ancestry-matched, "
        "modifiable risk, etc.). PRS without framing risks being read as a "
        "clinical-actionable call.\n"
        f"reply prefix: {reply[:800]!r}"
    )

    # 5. INV-P001 v1.7 / AC8b: native web_search invoked.
    trace_blob = json.dumps(trace)
    assert "web_search" in trace_blob, (
        "INV-P001 v1.7 / AC8b: trace has no `web_search` reference; the "
        "agent did not invoke native OpenAI search despite the v1.7 default. "
        f"trace prefix: {trace_blob[:1000]!r}"
    )

    # 6. Primary-source citation in reply.
    assert any(p.search(reply) for p in _PRIMARY_SOURCE_PATTERNS), (
        f"INV-A001 prose surface: reply cites no primary source. reply prefix: {reply[:600]!r}"
    )

    # 7. Regression: no HTTP 500 markers.
    assert "HTTP 500" not in trace_blob and '"status_code": 500' not in trace_blob, (
        "regression: trace contains an HTTP 500 marker — a genomeclaw tool "
        "call failed mid-protocol.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

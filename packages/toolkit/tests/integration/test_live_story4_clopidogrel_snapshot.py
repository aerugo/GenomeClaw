"""Phase 3 slice 2 — Story 4 clopidogrel/CYP2C19 PGx live snapshot.

Mirrors the
[user-stories.md Story 4](../../../../docs/reference/user-stories.md)
exchange: a user has just been prescribed clopidogrel and asks the
agent whether their genome has anything pharmacogenomically relevant
before the first dose. The staged finding is `CYP2C19 *1/*2`
(intermediate metabolizer phenotype, `clinical-actionable` per
`INV-C001` v1.5 with a `confirm_with_provider` escalation marker).

Structural assertions (per Phase 3 plan):
- HTTP rc == 0 + non-empty reply.
- Reply mentions CYP2C19 + the intermediate-metabolizer phenotype
  (looser than byte-match: "*1/*2" OR "intermediate metabolizer" OR
  the gene + drug combo).
- Reply names at least one alternative antiplatelet (prasugrel /
  ticagrelor) OR explicitly cites the CPIC clopidogrel guideline.
- `web_search` appears in the trace blob (native search invoked per
  `INV-P001` v1.7).
- Reply cites at least one primary source (URL / PMID / variant-keyed
  ref).
- Reply carries clinical-escalation framing (some phrase in the family
  of "discuss with", "confirm with", "mention to your prescriber",
  "before changing therapy"). The agent must not silently strip the
  `clinical_escalation` marker the staged finding declares.
- Regression: no `HTTP 500` markers in the trace.

Cost: one real OpenAI call (~USD $0.20-0.50, ~4 min wall-clock).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import STORY4_CYP2C19_FINDINGS, stage_run_with_findings

STORY4_QUESTION = (
    "GP just prescribed clopidogrel (Plavix) for me today after a TIA. Anything "
    "in my genome I should know before the first dose? Look at the genomeclaw "
    "findings, then research current guidelines for clopidogrel pharmacogenomics. "
    "Cite specific PubMed IDs, CPIC guideline URLs, or PharmGKB references."
)

# Reply must mention CYP2C19 + an indicator of the intermediate-metabolizer
# phenotype (the genotype OR the phenotype string).
_TOPIC_PATTERNS_TOPIC: tuple[re.Pattern[str], ...] = (re.compile(r"CYP2C19", re.IGNORECASE),)
_TOPIC_PATTERNS_PHENOTYPE: tuple[re.Pattern[str], ...] = (
    re.compile(r"\*1\s*/\s*\*2"),
    re.compile(r"intermediate\s*metaboliz", re.IGNORECASE),
)

# At least one of: an alternative antiplatelet OR a CPIC guideline cite.
_ALTERNATIVE_OR_GUIDELINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"prasugrel", re.IGNORECASE),
    re.compile(r"ticagrelor", re.IGNORECASE),
    re.compile(r"CPIC", re.IGNORECASE),
    re.compile(r"cpicpgx\.org", re.IGNORECASE),
)

# Clinical-escalation framing: any of these phrasings count. The
# staged finding carries `clinical_escalation: confirm_with_provider`;
# the agent must surface that intent in prose.
_ESCALATION_PHRASE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"discuss\s+with", re.IGNORECASE),
    re.compile(r"confirm\s+with", re.IGNORECASE),
    re.compile(
        r"mention\s+(?:this\s+)?to\s+(?:your\s+)?(?:gp|doctor|prescriber|cardiologist)",
        re.IGNORECASE,
    ),
    re.compile(r"clinical\s+confirmation", re.IGNORECASE),
    re.compile(r"before\s+(?:changing|adjusting|stopping)\s+therapy", re.IGNORECASE),
    re.compile(r"escalat", re.IGNORECASE),
    re.compile(r"raise\s+(?:this\s+)?with\s+(?:your\s+)?(?:gp|doctor|prescriber)", re.IGNORECASE),
)

# Primary-source citation patterns (mirrors the Story 9 test).
_PRIMARY_SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://\S+"),
    re.compile(r"\bPMID[:\s]+\d+", re.IGNORECASE),
    re.compile(r"\bpubmed\.ncbi\.nlm\.nih\.gov/\d+", re.IGNORECASE),
    re.compile(r"\b(?:RCV|VCV)\d{4,}", re.IGNORECASE),
    re.compile(r"\bPA\d+", re.IGNORECASE),  # PharmGKB
    re.compile(r"\bclinvar:\S+", re.IGNORECASE),
    re.compile(r"\bpharmgkb:\S+", re.IGNORECASE),
)


@pytest.mark.live_llm
def test_invC001_invP001_story4_clopidogrel_live(tmp_path: Path) -> None:
    """Story 4 PGx — clopidogrel/CYP2C19 intermediate metabolizer.

    Pins:
    - `INV-C001` v1.5 (prose surface): clinical-actionable finding's
      escalation marker becomes user-facing escalation language.
    - `INV-P001` v1.7 / AC8b: native OpenAI `web_search` invoked.
    - `INV-A001` (prose surface): reply cites at least one primary source.
    - `INV-E001` (behavioural): reply mentions the gene + phenotype
      from the staged finding rather than fabricating a different one.
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root = tmp_path / "derived"

    stage_run_with_findings(derived_root, STORY4_CYP2C19_FINDINGS)

    trace = run_agent_in_sandbox(
        STORY4_QUESTION,
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

    # 2. Topic match: CYP2C19 + intermediate-metabolizer phenotype.
    assert any(p.search(reply) for p in _TOPIC_PATTERNS_TOPIC), (
        f"agent's reply did not name CYP2C19; reply prefix: {reply[:300]!r}"
    )
    assert any(p.search(reply) for p in _TOPIC_PATTERNS_PHENOTYPE), (
        f"agent's reply did not name the *1/*2 OR intermediate-metabolizer "
        f"phenotype; reply prefix: {reply[:500]!r}"
    )

    # 3. Alternative antiplatelet OR CPIC guideline reference.
    assert any(p.search(reply) for p in _ALTERNATIVE_OR_GUIDELINE_PATTERNS), (
        "agent's reply did not name an alternative antiplatelet (prasugrel / "
        "ticagrelor) and did not cite the CPIC clopidogrel guideline. The "
        "Story-4 contract requires the agent to surface at least one of these "
        "as the actionable PGx context for the user.\n"
        f"reply prefix: {reply[:600]!r}"
    )

    # 4. INV-C001 v1.5 (prose surface): escalation framing.
    assert any(p.search(reply) for p in _ESCALATION_PHRASE_PATTERNS), (
        "INV-C001 v1.5: the staged finding carries "
        "`clinical_escalation: confirm_with_provider`; the agent's reply "
        "must surface this in prose (e.g. 'discuss with your prescriber', "
        "'confirm with your GP', 'before changing therapy'). The agent "
        "appears to have stripped the escalation marker.\n"
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
        "call failed mid-protocol despite the real staged store.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

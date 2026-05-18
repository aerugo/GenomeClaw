"""Phase 3 slice 3 — INV-C001 v1.6 validation-driven supersession (AC4b).

Pre-stages a deliberately-weak prior memory note about Story 9's CYP1A2
caffeine topic + asks the same Story-9 question. The agent's protocol
Step 3 (memory validation) should:

1. Retrieve the prior note (it lives at workspace `MEMORY.md`).
2. Validate it against current literature at the synthesis-turn floor
   (`INV-A002`).
3. Detect the gap: the prior note's "clearly causes large effects"
   conclusion overreaches the literature (the slice-1 live snapshot
   already verified that current evidence does NOT support a
   CYP1A2-specific magnitude effect on chronic-late-caffeine + SOL).
   The note also cites only a `memory:` ref (violates the INV-A001
   primary-source-required rule).
4. Run fresh research (Step 4).
5. Compose a corrected synthesis at max reasoning (Step 5).
6. Write a `Supersedes:` note before reply (Step 6 + INV-A001
   supersession schema).
7. Reply citing the corrected synthesis (NOT propagating the bad claim).

This test is the load-bearing check on the **memory-as-trust-boundary**
behaviour. Memory-of-memory chains compound hallucinations; the
validation step is what stops them.

Structural assertions (prose-layer; SQLite memory-write inspection is
out of scope for slice 3 — see slice-3 work-notes):

- HTTP rc == 0 + non-empty reply.
- Reply mentions CYP1A2 + caffeine + sleep (topic still on track).
- `web_search` invoked (the agent re-researched after validation
  failed — Step 4).
- Reply demonstrates the agent recognised the prior note's overreach.
  Match phrases in the family of: "earlier note", "previous
  synthesis", "prior", "outdated", "revise", "supersede", "update",
  "correct", "overreach", "stronger than the evidence supports", etc.
- Reply does NOT propagate the bad claim ("clearly causes large
  effects", "≥30 minutes additional sleep onset latency", or "strict
  caffeine cutoff at 12 PM is essentially required").
- Reply cites at least one primary source (URL / PMID / variant-keyed
  ref) — the corrected synthesis must be evidence-bound.
- Regression: no `HTTP 500` markers.

Cost: one real OpenAI call (~USD $0.20-0.50, ~3-5 min wall-clock).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import (
    STORY9_CYP1A2_FINDINGS,
    STORY9_WEAK_MEMORY_NOTE,
    stage_run_with_findings,
)

# We re-use the slice-1 question — the topic must overlap with the
# weak memory note's topic so memory_search retrieves it. The agent
# also has the same Story-9 finding in the staged derived store.
SUPERSESSION_QUESTION = (
    "I want to revisit caffeine and sleep. Looking at my CYP1A2 *1F/*1F "
    "(rs762551 A/A) genotype: what does current evidence actually say about "
    "how chronic-late-caffeine affects sleep onset latency for someone with "
    "this genotype specifically? Pull current literature and reason carefully "
    "about effect-size magnitude — don't accept earlier syntheses uncritically. "
    "Cite specific PubMed IDs or URLs."
)

_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"CYP1A2", re.IGNORECASE),
    re.compile(r"rs762551", re.IGNORECASE),
    re.compile(r"caffeine", re.IGNORECASE),
)

# At least one phrase from the gap-recognition family must appear so we
# can verify the agent didn't blindly recite the prior note. Broad set;
# the agent has many ways to phrase "the prior note overreached".
_GAP_RECOGNITION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"earlier\s+(?:note|synthesis|memory)", re.IGNORECASE),
    re.compile(r"previous\s+(?:note|synthesis|memory|research)", re.IGNORECASE),
    re.compile(r"prior\s+(?:note|synthesis|memory|research|claim|conclusion)", re.IGNORECASE),
    re.compile(r"\boutdated\b", re.IGNORECASE),
    re.compile(r"\brevise\b|\brevised\b|\brevising\b", re.IGNORECASE),
    re.compile(r"supersede", re.IGNORECASE),
    re.compile(r"\bupdate(?:d|s)?\s+(?:the|my)\s+(?:note|synthesis)", re.IGNORECASE),
    re.compile(r"\bcorrect(?:ion|ed|ing)\b", re.IGNORECASE),
    re.compile(r"overreach(?:ed|es|ing)?", re.IGNORECASE),
    re.compile(r"stronger\s+than\s+(?:the\s+)?evidence\s+supports", re.IGNORECASE),
    re.compile(r"weaker\s+than\s+(?:the\s+)?prior", re.IGNORECASE),
    re.compile(r"not\s+well\s+supported\s+by\s+(?:current\s+)?evidence", re.IGNORECASE),
    re.compile(
        r"does\s+not\s+match\s+(?:the\s+)?(?:current\s+)?(?:literature|evidence)", re.IGNORECASE
    ),
    re.compile(r"more\s+heterogen", re.IGNORECASE),
    re.compile(r"reclassif", re.IGNORECASE),
    re.compile(r"downgrad", re.IGNORECASE),
)

# Phrases the agent must NOT propagate verbatim (or near-verbatim) from
# the staged weak note. If any of these appear, the agent uncritically
# echoed the prior overreach rather than validating it.
_BAD_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"clearly\s+causes\s+large\s+effects?\s+on\s+sleep", re.IGNORECASE),
    re.compile(r"≥\s*30\s*(?:minutes|min)\s+additional\s+sleep\s+onset\s+latency", re.IGNORECASE),
    re.compile(r"essentially\s+required", re.IGNORECASE),
    re.compile(r"much\s+larger\s+than\s+in\s+faster[- ]metabolizer", re.IGNORECASE),
)

_PRIMARY_SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://\S+"),
    re.compile(r"\bPMID[:\s]+\d+", re.IGNORECASE),
    re.compile(r"\bpubmed\.ncbi\.nlm\.nih\.gov/\d+", re.IGNORECASE),
    re.compile(r"\b(?:RCV|VCV)\d{4,}", re.IGNORECASE),
    re.compile(r"\bclinvar:\S+", re.IGNORECASE),
    re.compile(r"\bpharmgkb:\S+", re.IGNORECASE),
)


@pytest.mark.live_llm
def test_invC001_v16_memory_validation_supersedes_overreaching_note_live(tmp_path: Path) -> None:
    """`INV-C001` v1.6 + `INV-A001` supersession — the load-bearing memory check.

    Stages a weak prior memory note about CYP1A2 caffeine that violates
    both (a) the conclusion-↔-source grounding check (claim overreaches
    cited evidence) and (b) the primary-source-required rule (memory-only
    citations). Asks a Story-9 question on the same topic. Verifies the
    agent recognised the gap, ran fresh research, and replied with a
    corrected synthesis citing primary sources — without echoing the bad
    claim.

    What slice 3 does NOT verify (deferred to slice 3b or later):
    - That the agent actually wrote a `Supersedes:` note to the SQLite
      memory backend (requires inspecting `/sandbox/.openclaw/memory/
      genomeclaw.sqlite` after the run; the schema isn't documented).
    - That `memory_search` was specifically called (vs the workspace
      MEMORY.md being auto-injected into the system-prompt context;
      either path satisfies the contract because the agent saw the
      note + responded to it).
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root = tmp_path / "derived"

    stage_run_with_findings(derived_root, STORY9_CYP1A2_FINDINGS)

    trace = run_agent_in_sandbox(
        SUPERSESSION_QUESTION,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=240,
        extra_workspace_files={"MEMORY.md": STORY9_WEAK_MEMORY_NOTE},
    )

    # 1. Top-level shape (orchestrator normalises both gateway-wrapped
    # and embedded-direct envelopes into the wrapped form).
    assert trace.get("status") == "ok", (
        f"agent run did not complete cleanly: status={trace.get('status')!r}"
    )
    payloads = trace.get("result", {}).get("payloads", [])
    assert payloads, "agent produced no user-facing reply payload"
    reply = payloads[0].get("text", "")
    assert reply, "agent's first payload has empty text"

    # 2. Topic on track.
    assert all(p.search(reply) for p in _TOPIC_PATTERNS), (
        f"reply doesn't cover all of CYP1A2 + rs762551 + caffeine; reply prefix: {reply[:300]!r}"
    )

    # 3. Native web_search invoked — the agent re-researched after
    # validation failed (protocol Step 4).
    trace_blob = json.dumps(trace)
    assert "web_search" in trace_blob, (
        "INV-C001 v1.6 + INV-P001 v1.7: trace has no `web_search` reference. "
        "When the prior memory note's validation fails (overreach + memory-only "
        "citations), the agent's protocol Step 4 says 'run fresh research'. The "
        "absence of any web_search call means the agent either (a) accepted "
        "the prior note uncritically or (b) declined to validate at all.\n"
        f"trace prefix: {trace_blob[:1000]!r}"
    )

    # 4. Gap recognition — the agent surfaces that the prior note was
    # weak/wrong/incomplete. This is the load-bearing prose-surface
    # check that the validation step actually fired.
    gap_matches = [p.pattern for p in _GAP_RECOGNITION_PATTERNS if p.search(reply)]
    assert gap_matches, (
        "INV-C001 v1.6 / INV-A001 supersession: reply does NOT surface that "
        "the prior memory note was overreaching, outdated, or weak. The "
        "memory-validation step (protocol Step 3) requires the agent to "
        "name the gap when it supersedes a note. Possible failure modes: "
        "(a) the agent echoed the prior note's bad claim uncritically, "
        "(b) the agent didn't load the workspace MEMORY.md at all, "
        "(c) the agent ran fresh research but didn't acknowledge the prior.\n"
        f"reply prefix: {reply[:1000]!r}"
    )

    # 5. NO propagation of the bad claim. The whole point of validation
    # is that the corrected synthesis doesn't echo the overreach.
    bad_matches = [p.pattern for p in _BAD_CLAIM_PATTERNS if p.search(reply)]
    assert not bad_matches, (
        "INV-C001 v1.6: agent's corrected reply still propagates the prior "
        f"note's overreaching claims: {bad_matches!r}. The whole point of the "
        "validation step is that the agent's reply reflects the *corrected* "
        "synthesis, not the bad memory-cached one.\n"
        f"reply prefix: {reply[:1500]!r}"
    )

    # 6. Primary source in the corrected reply.
    assert any(p.search(reply) for p in _PRIMARY_SOURCE_PATTERNS), (
        "INV-A001 prose surface: corrected synthesis cites no primary source. "
        f"reply prefix: {reply[:600]!r}"
    )

    # 7. Regression check.
    assert "HTTP 500" not in trace_blob and '"status_code": 500' not in trace_blob, (
        f"regression: trace contains an HTTP 500 marker.\ntrace prefix: {trace_blob[:1500]!r}"
    )

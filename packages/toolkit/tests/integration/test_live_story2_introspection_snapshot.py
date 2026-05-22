"""Phase 6 Slice F Story 2 — "what do you know about me?" live snapshot.

Per [user-stories.md Story 2](../../../../docs/reference/user-stories.md):
the first-conversation meta-introspection question. The agent's right
move is to call `genomeclaw_status` and surface what it actually knows
(run-id, schema version, annotation source versions, privacy framing)
rather than fabricate findings or pretend to know more than the data
warrants.

This is the closing live-LLM test for Phase 6 — Stories 4/9/10 shipped
via the agent-research-and-synthesis companion plan; Story 2 stayed open
because it tests a different protocol path (introspection / framing,
not research + synthesis).

Structural snapshot assertions:

- HTTP rc == 0 + non-empty reply.
- `genomeclaw_status` appears in the trace blob (the agent grounded
  itself in actual store metadata before answering).
- Reply names at least one of: the run-id, the schema version, or an
  annotation source — i.e. the agent re-shaped the status payload into
  prose rather than describing what it would do.
- Reply does NOT fabricate findings: no `clinvar:` / `pharmgkb:` /
  `pgs_catalog:` references appear (the staged store has zero findings,
  so any such citation is invented). This is the over-claim guardrail.
- Regression: no HTTP 500 markers (the host service must respond
  cleanly even against an empty findings table).

Cost: one real OpenAI call (~USD $0.20-0.50, ~3-4 min wall-clock).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import stage_empty_run

STORY2_QUESTION = (
    "ok let's try this. what do you actually know about me? Start with what's "
    "in the active genomeclaw store — run-id, schema version, annotation sources "
    "— before pulling any specific findings."
)

# Patterns that count as "the agent re-shaped genomeclaw_status into prose".
# Any one match is enough; the agent might mention the run-id by date, the
# schema version, OR an annotation source — different valid framings.
_STATUS_SHAPING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"run[-_\s]?id", re.IGNORECASE),
    re.compile(r"schema\s*(?:version|v?\d+\.\d+)", re.IGNORECASE),
    re.compile(r"\bv\d+\.\d+\b"),
    re.compile(r"\b202\d-\d{2}-\d{2}", re.IGNORECASE),  # ISO-style run-id date
    re.compile(r"clinvar", re.IGNORECASE),
    re.compile(r"gnomad", re.IGNORECASE),
    re.compile(r"dbsnp", re.IGNORECASE),
    re.compile(r"derived\s+store", re.IGNORECASE),
)

# Meta-awareness language — the agent acknowledges it hasn't yet pulled
# specific findings + lists what it actually has access to. THIS is the
# hard Story 2 contract: the agent must not overstate what it knows.
#
# **Privacy framing intentionally NOT checked here.** The agent system
# prompt (Section 10 / Format) explicitly says: "Avoid medical disclaimer
# boilerplate. The plugin tool descriptions + this prompt are the contract;
# you don't need to re-disclaim every reply." Empirical 2026-05-22 live
# sweep confirmed gpt-5.5 follows this — answers the literal status
# question precisely without volunteering disclaimers, which is the
# correct behavior per the prompt. The user-stories.md Story 2 ideal was
# written before live conversations + over-prescribed first-turn
# disclaimers; the documented behavior here supersedes that ideal.
# Disclaimers surface naturally on clinical-actionable findings (Story 4 / 6)
# via the prompt's Section 9 "Recommend clinical confirmation" pattern —
# which IS where the research-vs-clinical line belongs.
_META_AWARENESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Past-tense "haven't" / "have not" forms.
    re.compile(r"haven['\u2019]t\s+(?:queried|pulled|retrieved|fetched)", re.IGNORECASE),
    re.compile(r"have\s+not\s+(?:queried|pulled|retrieved|fetched)", re.IGNORECASE),
    re.compile(r"not\s+(?:queried|pulled).*(?:specific|any)\s+findings?", re.IGNORECASE),
    # "No findings yet" / "no findings so far" forms.
    re.compile(r"no\s+(?:specific\s+)?findings?\s+(?:yet|so\s+far)", re.IGNORECASE),
    # Forward-looking "before pulling / before querying" forms.
    re.compile(r"\bbefore\s+(?:pulling|querying|fetching|retrieving)\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+(?:pulling|querying|fetching|retrieving)\b", re.IGNORECASE),
    # "Only the metadata / only the status" framing.
    re.compile(r"only\s+(?:the\s+)?metadata", re.IGNORECASE),
    re.compile(r"only\s+(?:the\s+)?(?:run|schema|identifier|status)", re.IGNORECASE),
    # "Don't yet / don't currently" framing.
    re.compile(r"don['\u2019]t\s+(?:yet|currently)\s+(?:see|have|know)", re.IGNORECASE),
    # "Available metadata" / "from that tool" — bounding what it knows.
    re.compile(r"available\s+metadata\s+(?:from|in)", re.IGNORECASE),
    re.compile(r"(?:metadata|details)\s+(?:from|exposed\s+in)\s+(?:that\s+)?tool", re.IGNORECASE),
)

# Evidence-ref kinds the agent must NOT cite (the staged findings table
# is empty; any such citation is fabricated). The host service evidence
# resolver accepts these three variant-keyed kinds per spec AC10.
_FABRICATED_EVIDENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclinvar:\s*\w+", re.IGNORECASE),
    re.compile(r"\bpharmgkb:\s*\w+", re.IGNORECASE),
    re.compile(r"\bpgs_catalog:\s*\w+", re.IGNORECASE),
)


@pytest.mark.live_llm
def test_story2_introspection_live(tmp_path: Path) -> None:
    """One Story-2 turn against gpt-5.5; structural shape of the trace.

    Pins:
    - Behavioural surface for the host service's `/v1/health` /
      `genomeclaw_status` path: the agent re-shapes the structured
      payload into prose containing at least one ground-truth marker
      from the store (run-id, schema version, annotation source).
    - Hard meta-awareness contract: the agent must explicitly limit its
      claim to what `genomeclaw_status` returned (e.g. "haven't pulled
      any specific findings yet") rather than overstating what it knows.
    - Over-claim guardrail: with an empty findings table, the agent
      MUST NOT cite a `clinvar:` / `pharmgkb:` / `pgs_catalog:` evidence
      ref — those would be fabricated.
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root = tmp_path / "derived"
    stage_empty_run(derived_root)

    trace = run_agent_in_sandbox(
        STORY2_QUESTION,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=240,
    )

    # 1. Top-level shape.
    assert trace.get("status") == "ok", (
        f"agent run did not complete cleanly: status={trace.get('status')!r}, "
        f"summary={trace.get('summary')!r}"
    )
    payloads = trace.get("result", {}).get("payloads", [])
    assert payloads, "agent produced no user-facing reply payload"
    reply = payloads[0].get("text", "")
    assert reply, "agent's first payload has empty text"

    trace_blob = json.dumps(trace)

    # 2. Behavioural surface: the agent invoked genomeclaw_status to
    # ground itself in actual store metadata. Substring-search across
    # the whole trace blob is robust to tool-call structure variance
    # between gateway-vs-embedded paths.
    assert "genomeclaw_status" in trace_blob, (
        "agent did not invoke `genomeclaw_status` for the meta-introspection "
        "turn. Story 2's contract is that the agent grounds itself in real "
        "store metadata before answering 'what do you know about me?'.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

    # 3. The reply re-shapes the status payload into prose. At least one
    # of: run-id, schema version, or an annotation source name appears
    # in the reply text.
    assert any(p.search(reply) for p in _STATUS_SHAPING_PATTERNS), (
        "agent invoked `genomeclaw_status` but the reply does not surface any "
        "concrete metadata from the result (run-id / schema version / annotation "
        "source). The agent appears to have called the tool ceremonially without "
        "using its output.\n"
        f"reply prefix: {reply[:800]!r}"
    )

    # 4. Hard contract: meta-awareness. The agent must acknowledge what
    # it does NOT know — it has only queried `genomeclaw_status`, so it
    # should NOT claim to have findings yet. The phrasing is loose;
    # multiple acceptable forms qualify.
    assert any(p.search(reply) for p in _META_AWARENESS_PATTERNS), (
        "Story 2 hard contract: agent's reply does not acknowledge that it has "
        "NOT yet queried specific findings. With an empty findings table, the "
        "agent must explicitly limit its claim to what `genomeclaw_status` "
        "returned (meta-awareness), not gloss the gap.\n"
        f"reply prefix: {reply[:1000]!r}"
    )

    # 5. Over-claim guardrail: the staged findings table is empty, so any
    # `clinvar:` / `pharmgkb:` / `pgs_catalog:` ref in the reply is
    # fabricated. The agent must surface "I haven't queried specific
    # findings yet" framing without inventing evidence refs.
    fabricated = [p.pattern for p in _FABRICATED_EVIDENCE_PATTERNS if p.search(reply)]
    assert not fabricated, (
        "over-claim guardrail: agent cited an evidence ref despite the staged "
        f"findings table being empty. Fabricated patterns matched: {fabricated!r}.\n"
        f"reply prefix: {reply[:1000]!r}"
    )

    # 6. Regression: no HTTP 500 markers. An empty findings table must
    # not cause the host service to crash; /v1/findings should return
    # an empty list rather than 500.
    assert "HTTP 500" not in trace_blob and '"status_code": 500' not in trace_blob, (
        "regression: trace contains an HTTP 500 marker — the host service "
        "failed against the empty-findings-table staging. /v1/findings should "
        "return an empty list, not 500.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

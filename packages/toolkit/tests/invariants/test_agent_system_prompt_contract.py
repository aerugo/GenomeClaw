"""Phase 2 — pins the agent system prompt's content contract.

The prompt at
[packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](
../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)
is the operating-protocol document the agent reads at every session start.
It teaches the research-and-synthesis protocol + memory-validation +
turn-classification per the v1.6/v1.8 INVARIANTS revision.

The tests here are **content gates** on the prompt — not on the agent's
behaviour under it. They guard the prompt against regression edits that
silently drop a protocol step:

- INV-A001: the memory-note schema (skeleton) is documented.
- INV-A002: the synthesis reasoning floor is documented for
  health-interpretation turns.
- INV-C001 v1.6: lifestyle-track direct-guidance rule is documented;
  memory-validation three-check protocol is documented.
- INV-P001: web search payload privacy contract is documented.
- All five v0 GenomeClaw plugin tools are documented.

Behavioural tests over the agent (under this prompt) are live-LLM
snapshots and live separately under `tests/integration/` once Phase 2
ships the sandbox image with the prompt baked in.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROMPT_PATH = _REPO_ROOT / "packages" / "nemoclaw-plugin" / "sandbox" / "agent-system-prompt.md"


def _read_prompt() -> str:
    """Read the system prompt once; tests share the loaded content."""
    return _PROMPT_PATH.read_text()


def test_system_prompt_exists() -> None:
    """Trivial smoke — the file is in the build context where the Dockerfile expects it."""
    assert _PROMPT_PATH.is_file(), f"missing system prompt at {_PROMPT_PATH}"


def test_system_prompt_documents_all_five_genomeclaw_tools() -> None:
    """All 5 v0 plugin tools must be named in the prompt's tool catalog."""
    text = _read_prompt()
    for tool in (
        "genomeclaw_status",
        "genomeclaw_findings",
        "genomeclaw_variant",
        "genomeclaw_evidence",
        "genomeclaw_gene",
    ):
        assert tool in text, f"system prompt missing tool reference: {tool!r}"


def test_invA002_system_prompt_teaches_synthesis_reasoning_floor() -> None:
    """``INV-A002``: prompt teaches max reasoning for health-interpretation turns.

    Three structural assertions: the term "health-interpretation turn" appears;
    the words "maximum" and "reasoning" appear together; the conversational
    exemption appears.
    """
    text = _read_prompt()
    assert "health-interpretation turn" in text.lower(), (
        "INV-A002 verification: prompt must name the 'health-interpretation turn' concept"
    )
    assert re.search(r"maximum.*reasoning|reasoning.*max", text, re.IGNORECASE), (
        "INV-A002: prompt must teach maximum-reasoning rule for health-interpretation turns"
    )
    assert "conversational" in text.lower(), (
        "INV-A002 exemption: prompt must document the conversational-turn exception so the "
        "floor doesn't over-apply"
    )


def test_invA001_system_prompt_documents_memory_note_schema() -> None:
    """``INV-A001``: prompt's memory-note schema is the agent's writing contract.

    Asserts the seven required fields appear in the schema section:
    Question, Tool calls, Sources retrieved, Synthesis, Calibration,
    Recommendation framing, Freshness.
    """
    text = _read_prompt()
    required_fields = (
        "Question",
        "Tool calls",
        "Sources retrieved",
        "Synthesis",
        "Calibration",
        "Recommendation framing",
        "Freshness",
    )
    for field in required_fields:
        assert field in text, f"INV-A001 schema verification: missing field {field!r}"


def test_invA001_system_prompt_documents_primary_source_requirement() -> None:
    """``INV-A001``: prompt must teach the "at least one primary source" rule.

    Memory notes citing only other memory notes are malformed — the writer
    rejects them. The prompt must teach this so the agent doesn't try to
    write such notes in the first place.
    """
    text = _read_prompt().lower()
    assert "primary source" in text, (
        "INV-A001 primary-source requirement: prompt must teach the rule"
    )
    assert "memory-only" in text or "only other memory" in text, (
        "INV-A001 primary-source requirement: prompt must teach the rejection "
        "of memory-only citations"
    )


def test_invA001_system_prompt_documents_supersession_mechanism() -> None:
    """``INV-A001``: prompt teaches the supersession schema.

    A superseding note records `supersedes: <prior-anchor>` + the specific
    gap found. The prior note stays on disk.
    """
    text = _read_prompt()
    assert "supersede" in text.lower() or "supersession" in text.lower(), (
        "INV-A001 supersession: prompt must teach the supersession mechanism"
    )
    assert "Supersedes" in text or "supersedes:" in text.lower(), (
        "INV-A001 supersession: prompt must document the `Supersedes:` field"
    )
    assert "stay on disk" in text.lower() or "stays on disk" in text.lower(), (
        "INV-A001 supersession: prompt must document that the prior note remains "
        "on disk for the audit trail"
    )


def test_invC001_system_prompt_documents_memory_validation_protocol() -> None:
    """``INV-C001`` v1.6: prompt teaches the three-check memory-validation protocol.

    The three checks: conclusion-↔-source grounding, source quality, freshness.
    Each must be teachable from the prompt's content (the agent has to know
    when to fail validation and supersede).
    """
    text = _read_prompt().lower()
    # The three checks — text varies but the concepts must be present.
    assert "conclusion" in text and "source" in text, (
        "INV-C001 v1.6: prompt must teach the conclusion-↔-source grounding check"
    )
    assert "source quality" in text or "peer-reviewed" in text, (
        "INV-C001 v1.6: prompt must teach the source-quality check"
    )
    assert "freshness" in text, "INV-C001 v1.6: prompt must teach the freshness check"


def test_invC001_system_prompt_documents_lifestyle_direct_guidance_rule() -> None:
    """``INV-C001`` v1.6: lifestyle findings get direct guidance, not clinician-deferral.

    The prompt must teach the lifestyle-vs-clinical separation explicitly so the
    agent doesn't over-defer on lifestyle topics (one of the documented v1.6
    failure modes).
    """
    text = _read_prompt().lower()
    assert "lifestyle" in text, "INV-C001: prompt must name the lifestyle track"
    assert "direct" in text and "guidance" in text, (
        "INV-C001 v1.6: prompt must teach direct lifestyle guidance"
    )
    assert "over-deferral" in text or "over-defer" in text, (
        "INV-C001 v1.6: prompt must explicitly name over-deferral as a failure mode"
    )


def test_invP001_system_prompt_documents_web_search_privacy_contract() -> None:
    """``INV-P001`` v1.7: prompt teaches the web_search payload contract.

    The agent must never include user-identifying genomic data in a
    `web_search` query payload — only topic-term strings.
    """
    text = _read_prompt().lower()
    assert "web_search" in text, "INV-P001: prompt must name web_search as a tool"
    # The prompt must teach the "topic-terms only" rule, however phrased
    assert "topic-only" in text or "topic-term" in text, (
        "INV-P001 v1.7: prompt must teach the topic-terms-only web_search rule"
    )
    # And explicitly mention what NOT to put in queries
    assert "rsid" in text or "genotype" in text or "sample" in text, (
        "INV-P001 v1.7: prompt must name what must NOT appear in web_search payloads "
        "(rsids, genotype strings, sample identifiers)"
    )


def test_invP001_system_prompt_teaches_native_vs_managed_web_search() -> None:
    """``INV-P001`` v1.7: prompt teaches the native-vs-managed distinction.

    Native OpenAI `web_search` flows through the agent-provider's egress
    envelope and is enabled by default (the user already consented to OpenAI
    egress when they configured the OpenAI provider). Managed providers
    (Brave / Tavily / Perplexity / etc.) are a separate, opt-in egress
    destination and require the user to set `tools.web.search.provider`.

    The prompt must teach this so the agent (a) uses native search when
    available without claiming search is "unavailable", and (b) recognises
    the distinction between the two paths when reasoning about its tools.
    """
    text = _read_prompt()
    text_lower = text.lower()
    # Must name "native" search in the context of the OpenAI provider
    assert "native" in text_lower and "openai" in text_lower, (
        "INV-P001 v1.7: prompt must name native OpenAI web_search so the agent knows "
        "it has search access via the agent provider's API even when no managed "
        "provider is pinned"
    )
    # Must name "managed" providers as the opt-in egress class
    assert "managed" in text_lower, (
        "INV-P001 v1.7: prompt must name the 'managed' provider class to distinguish "
        "it from the native OpenAI path"
    )
    # Must teach that managed providers are an opt-in egress destination
    assert (
        "opt-in" in text_lower or "explicitly enable" in text_lower or ("opt in" in text_lower)
    ), (
        "INV-P001 v1.7: prompt must teach that managed web_search providers are an "
        "opt-in egress destination separate from the agent provider"
    )


def test_invP001_system_prompt_documents_web_fetch_disabled_default() -> None:
    """``INV-P001`` v1.7: prompt teaches that `web_fetch` is off by default.

    `web_fetch` issues outbound HTTP from the sandbox to arbitrary URLs and
    is NOT part of the OpenAI Responses API contract. It is a third named
    egress destination and the sandbox image ships with it disabled. The
    prompt must teach the agent that `web_fetch` may be unavailable so it
    doesn't claim a URL was fetched when the tool is gated off.
    """
    text = _read_prompt().lower()
    assert "web_fetch" in text, "prompt must mention web_fetch as a tool"
    # Find the prompt sentence(s) that specifically discuss web_fetch's
    # availability state — the load-bearing language must be local to
    # web_fetch, not borrowed from web_search's discussion.
    web_fetch_section = re.search(
        r"`?web_fetch`?[^.\n]*(?:\.[^.\n]*){0,3}",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    assert web_fetch_section is not None, "prompt has no sentence about web_fetch"
    nearby = web_fetch_section.group(0).lower()
    assert (
        "off by default" in nearby
        or "may be unavailable" in nearby
        or "disabled" in nearby
        or "opt-in" in nearby
        or "opt in" in nearby
    ), (
        f"INV-P001 v1.7: the prompt's web_fetch sentence must teach that web_fetch "
        "may be off in the default sandbox config (it is a gated third egress "
        "destination, not part of the OpenAI Responses API contract). "
        f"Found near-web_fetch text: {nearby[:200]!r}"
    )


def test_system_prompt_documents_hard_genes_decline_pattern() -> None:
    """Prompt teaches graceful decline on hard-genes (PER3, CLOCK, ACTN3, etc.).

    Replaces the v1.5 `topic:hard-genes` curated note (retired in v1.6). The
    decline reasoning lives in the agent's training + the prompt's named
    decline-pattern guidance.
    """
    text = _read_prompt()
    assert "PER3" in text, "prompt must name PER3 in the decline-pattern list"
    assert "VNTR" in text or "repeat" in text.lower(), (
        "prompt must name VNTRs (variable-number tandem repeats) as a "
        "short-read-WGS genotyping limitation"
    )
    assert "non-replication" in text or "replication" in text.lower(), (
        "prompt must teach the repeated-non-replication reason for declining"
    )


def test_system_prompt_documents_research_and_synthesis_steps_in_order() -> None:
    """The 7-step research-and-synthesis protocol must appear in order.

    Memory → user data → validation → research → synthesis → memory note → reply.
    Matches section headings only (`### Step N`), not in-body forward
    references like "see Step 6 below".
    """
    text = _read_prompt()
    # Match `### Step N` at a heading anchor so forward-references in
    # earlier section bodies don't trip the order check.
    step_pattern = re.compile(r"^#+\s+Step\s+(\d+)\b", re.MULTILINE)
    matches = list(step_pattern.finditer(text))
    step_numbers_in_order = [int(m.group(1)) for m in matches]
    assert step_numbers_in_order == [1, 2, 3, 4, 5, 6, 7], (
        f"7-step protocol headings out of order or missing; found heading numbers "
        f"{step_numbers_in_order}, expected [1, 2, 3, 4, 5, 6, 7]"
    )

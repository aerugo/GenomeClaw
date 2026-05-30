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

# INV-V001-backstop-file:
#
# Every substring assertion in this file is a **prompt-content backstop** — a
# check that the agent system prompt teaches a required concept (memory-note
# schema, lifestyle-vs-clinical, decline patterns, error_type vocabulary,
# etc.). These assertions are NOT load-bearing for agent behaviour: the
# prompt could rephrase the same concept and the agent would still be correct;
# the test would just need updating. The load-bearing correctness gates live
# elsewhere (live-LLM smokes, structural trace inspection under INV-A005 v1.22,
# etc.).
#
# Per INV-V001 (no forbidden-phrase enumeration as primary verification),
# substring backstops are allowed when declared as such. This file-level
# annotation covers every test function below.

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


def _extract_step3_section(prompt: str) -> str:
    """Return the Step 3 section text (between `### Step 3` and `### Step 4`).

    Used by the capability-claim test (and any future Step-3 contract test) so
    assertions can be section-scoped — checking ``"genomeclaw_status" in text``
    against the whole prompt would always pass (the tool catalog names it
    too), which is the wrong contract.
    """
    pattern = re.compile(
        r"^###\s+Step\s+3\b.*?(?=^###\s+Step\s+4\b)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(prompt)
    assert match is not None, "Step 3 section not found in prompt"
    return match.group(0)


def test_invA002_step3_memory_validation_special_cases_capability_claims() -> None:
    """``INV-A002`` v1.8 bullet 3 + Phase 1 of agent-stale-memory-and-failure-mode-confabulation:
    Step 3 must special-case **tool-capability claims** so a stale "X is unavailable"
    note is superseded by a live tool result in the same turn, overriding the
    calendar-freshness rule.

    Bug 1 (2026-05-27 muscle-question regression sweep run 4): the agent cited a
    2026-05-26 memory note saying "PGS000027 not computable / GenomeClaw refresh
    is currently unavailable" 30 minutes after Plan 1's sidecar repair landed and
    `_pgs_list` was returning PGS000018 at percentile 14.54. The Step 3 freshness
    bullet (line 183 of the prompt at the time of writing) asked the wrong
    question ("is the calendar date old?") for capability claims, where the right
    question is "did this turn's structured trace contradict the note?"

    This test pins the 4th validation bullet so future prompt edits don't silently
    drop the capability-claim override.
    """
    text = _read_prompt()
    step3 = _extract_step3_section(text)
    step3_lower = step3.lower()

    # Marker 1: a dedicated capability-claim validation bullet exists.
    assert "capability claim" in step3_lower or "capability claims" in step3_lower, (
        "INV-A002 v1.8 bullet 3: Step 3 must carry a dedicated capability-claim "
        "validation bullet that special-cases tool-failure / 'X is unavailable' "
        "memory notes"
    )

    # Marker 2: the bullet explicitly overrides the freshness-date rule. Generic
    # supersession language (line 185 of the prompt) is not enough — the bullet
    # must teach that freshness DOES NOT apply to capability claims.
    assert "freshness" in step3_lower, (
        "INV-A002: capability-claim bullet must reference the freshness rule "
        "it overrides"
    )
    override_markers = ("irrelevant", "override", "bypass", "does not apply", "doesn't apply")
    assert any(marker in step3_lower for marker in override_markers), (
        "INV-A002: capability-claim bullet must explicitly override the "
        f"freshness-date rule (looked for any of {override_markers})"
    )

    # Marker 3: the three example contradiction signals are named in Step 3.
    # Section-scoped assertion — the prompt's tool catalog (elsewhere) names
    # these tools too, but Step 3 must teach them specifically as
    # supersession-triggering signals.
    for signal in ("_pgs_list", "genomeclaw_status", "genomeclaw_gene"):
        assert signal in step3, (
            f"INV-A002: Step 3 capability-claim bullet must name {signal!r} as "
            "an example signal that contradicts a stale capability-failure memory note"
        )

    # Marker 4: the bullet teaches the "supersede the stale note" resolution.
    # Generic 'supersede' language already lives in Step 3 (line 185) for the
    # three-check protocol; the capability-claim bullet adds its own supersession
    # signal so the rule's resolution path is unambiguous.
    assert "supersede" in step3_lower, (
        "INV-A002: Step 3 capability-claim bullet must teach the 'supersede the "
        "stale note' resolution"
    )


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


def test_system_prompt_documents_prs_decline_pattern_with_five_named_reasons() -> None:
    """INV-C001 v1.7 + prs-non-imputed-wgs Phase 3: the prompt enumerates
    five named reasons under which the agent should decline a PRS compute
    request.

    The first four lifted from INV-C001 v1.7 (top-decile RR < ~1.5×,
    no independent replication, ancestry-calibration failure, no
    biologically-grounded polygenic basis). The fifth — added by
    prs-non-imputed-wgs Phase 3 — is: only an imputation-dependent
    scorefile available for the trait, where the user's input is
    non-imputed single-sample WGS and no HapMap3+ / C+T alternative
    exists. (Computing against an imputation-dependent scorefile on
    non-imputed single-sample WGS caps the match rate at the 45-65%
    empirical ceiling documented in
    docs/reports/prs-real-data-smoke-research-findings.md — better to
    decline with named reasons than persist a degraded score.)

    The pattern lives next to the existing hard-genes decline pattern
    (Section 6) — both are reasoned-decline patterns the agent applies
    after research, not hardcoded refusals.
    """
    text = _read_prompt()

    # Section anchor — the PRS-decline pattern must live somewhere
    # discoverable, not buried in a paragraph.
    assert "PRS-decline" in text or "PRS decline" in text, (
        "prompt must have a PRS-decline section anchor so the agent can "
        "navigate to it under reasoning load"
    )

    # The five named reasons. Each is a phrase the prompt must include
    # verbatim (or as a clearly-recognisable variant) so the prompt-content
    # gate is robust against paraphrase drift.
    reason_a_terms = ["top-decile", "1.5", "discriminative"]
    assert any(t in text for t in reason_a_terms), (
        f"reason (a) — top-decile RR < ~1.5× — must be in the prompt; "
        f"looked for any of {reason_a_terms}"
    )

    reason_b_terms = ["independent replication", "no replication", "fail.*replicate"]
    assert any(re.search(t, text) for t in reason_b_terms), (
        f"reason (b) — no independent replication — must be in the prompt; "
        f"looked for any of {reason_b_terms}"
    )

    text_lower = text.lower()
    assert "ancestry-calibration" in text_lower or "ancestry calibration" in text_lower, (
        "reason (c) — ancestry-calibration failure — must be in the prompt"
    )

    reason_d_terms = ["biologically-grounded", "biologically grounded", "heritability-only"]
    assert any(t in text for t in reason_d_terms), (
        f"reason (d) — no biologically-grounded polygenic basis — must be "
        f"in the prompt; looked for any of {reason_d_terms}"
    )

    # The new fifth reason — the Phase 3 addition. The match-rate ceiling
    # context is what motivates it; the prompt should name imputation-
    # dependence explicitly so the agent's decline naming is precise.
    reason_e_terms = [
        "imputation-dependent",
        "imputation dependent",
        "HapMap3",
        "HapMap3+",
        "C+T",
        "snpnet",
    ]
    assert any(t in text for t in reason_e_terms), (
        f"reason (e) — only imputation-dependent scorefile available — "
        f"must be in the prompt (prs-non-imputed-wgs Phase 3); looked for "
        f"any of {reason_e_terms}"
    )

    # The two-named-reasons rule must still apply when the agent declines.
    assert "two" in text.lower() and ("named reasons" in text or "specific reasons" in text), (
        "prompt must preserve the 'two named reasons' decline-pattern rule "
        "(the agent names two specific reasons when declining, not a generic refusal)"
    )


def test_system_prompt_teaches_machine_readable_decline_status() -> None:
    """INV-C001 v1.7 + agent-decline-taxonomy-exposure Phase 3: the prompt
    teaches the machine-readable decline-status rule.

    Every PGS row returned by `genomeclaw_pgs_list` and `genomeclaw_pgs_get`
    carries a `calibration_status` field. The host's calibration classifier
    has the first word: when `calibration_status='decline'`, the agent must
    surface `decline_reason` verbatim and refuse to present the row as a
    finding regardless of its own (a)-(e) reasoning.

    Asserts: field name appears; all three string values + the null-legacy
    case are documented; the binding `do NOT present` rule is explicit.
    """
    text = _read_prompt()
    # The field name + decline_reason companion must both appear.
    assert "calibration_status" in text, (
        "INV-C001 v1.7: prompt must name `calibration_status` as the "
        "machine-readable decline signal"
    )
    assert "decline_reason" in text, (
        "INV-C001 v1.7: prompt must name `decline_reason` as the structural "
        "decline-reason field the agent surfaces verbatim"
    )
    # All three string values must be enumerated.
    for value in ('"clean"', '"warning"', '"decline"'):
        assert value in text, (
            f"INV-C001 v1.7: prompt must enumerate calibration_status value {value}"
        )
    # The null-legacy case must be explicit (pre-Phase-3a rows).
    text_lower = text.lower()
    assert "null" in text_lower and (
        "pre-phase-3a" in text_lower or "legacy" in text_lower or "classifier shipped" in text_lower
    ), (
        "INV-C001 v1.7: prompt must teach the null-status (legacy / pre-classifier) case"
    )
    # The binding rule must be explicit, not implied.
    assert "do NOT present" in text or "do not present" in text_lower, (
        "INV-C001 v1.7: prompt must explicitly forbid presenting a declined row "
        "as a finding"
    )


def test_system_prompt_teaches_cyp2d6_indeterminate_handling() -> None:
    """INV-C001 v1.7 + cyp2d6-no-call-finding Phase 2: prompt teaches the
    CYP2D6 indeterminate rule.

    The host's Cyrius caller can fail to resolve CYP2D6 (low coverage at
    the CYP2D6/CYP2D7 locus, structural variant interference, BAM SM-tag
    mismatch). When that happens, the pipeline inserts an indeterminate
    `findings` row with `evidence_ref` starting with `cyrius_no_call:`.

    The agent's prompt MUST teach this case explicitly so the agent
    cannot silently infer "Normal Metabolizer" from the absence of a
    diplotype. Asserts: the prompt names CYP2D6 + indeterminate; the
    "do not interpret as Normal Metabolizer" rule is explicit; the
    `cyrius_no_call:` evidence-ref prefix is documented so the agent
    knows what marker to look for.
    """
    text = _read_prompt()
    text_lower = text.lower()
    assert "cyp2d6" in text_lower, "prompt must name CYP2D6"
    assert "indeterminate" in text_lower, (
        "INV-C001 v1.7: prompt must teach the 'indeterminate' CYP2D6 case"
    )
    assert (
        "do not interpret" in text_lower
        and "normal metabolizer" in text_lower
    ), (
        "INV-C001 v1.7: prompt must explicitly forbid the 'Normal Metabolizer' "
        "inference on the indeterminate path"
    )
    assert "cyrius_no_call" in text, (
        "prompt must document the `cyrius_no_call:` evidence-ref prefix so the "
        "agent recognises the indeterminate-row marker"
    )


def _extract_invA005_section(prompt: str) -> str:
    """Return the §INV-A005 section text: from the anchor paragraph containing the
    invariant ID until the next ``### Step N`` heading.

    Section-scoping matters here because catalogue signal substrings
    (``"Failed to connect"``, ``"placeholder string"``, ``"Expected"``) would
    otherwise collide with English-usage occurrences elsewhere in the prompt.
    """
    pattern = re.compile(
        r"\*\*Tool-failure narratives.*?(?=^###\s+Step\s+\d)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(prompt)
    assert match is not None, "§INV-A005 anchor paragraph not found in prompt"
    return match.group(0)


# INV-A005 v1.22 (Plan A.2 of inv-a005-structural-faithfulness) — the §INV-A005
# enforcement mechanism is structural, not phrase-list. The plugin returns
# `ToolFailureEnvelope` discriminated-union envelopes with an `error_type` field
# (Plan A.1, INV-A006). The prompt's job is to teach the agent to (a) read
# `error_type` as the source of truth, (b) quote structured fields verbatim
# before paraphrasing, and (c) call additional tools multi-turn when the
# failure shape is unfamiliar — not enumerate banned phrases.
#
# These three tests pin the new rule's content; they replace the prior
# `_CATALOGUE_ROWS` parametrized catalogue test + decompose-rule contract test
# + serialization-bug forbidden-phrase test that the v1.21 prompt carried.

# The four `error_type` enum values emitted by the plugin per INV-A006. The
# prompt MUST name at least two so the agent has concrete vocabulary to read.
_ERROR_TYPE_ENUM_VALUES = (
    "placeholder_rejected",
    "host_failure",
    "network_error",
    "http_error",
)


def test_invA005_v123_system_prompt_teaches_structured_error_type_rule() -> None:
    """INV-A005 v1.23 (Phase 4 of agent-synthesis-over-rich-tool-data): the
    prompt's §INV-A005 section must teach the agent that the plugin returns
    structured envelopes with an `error_type` discriminator the agent reads
    for reasoning — NOT for verbatim transcription into the reply.

    The structural-envelope shape (per INV-A006) is the agent's source of
    truth for classifying failures. The four enum values give the agent
    concrete vocabulary to *reason with*. v1.23 dropped the verbatim-quoting
    requirement — the agent translates the structured fields into plain-
    language synthesis for the user.
    """
    section = _extract_invA005_section(_read_prompt())

    # The rule must name `error_type` literally — it's the schema's discriminator.
    assert "error_type" in section, (
        "INV-A005 v1.23: §INV-A005 must teach the agent that the plugin "
        "returns an `error_type` field on failures. Did the rewrite drop "
        "the structured-envelope reference?"
    )

    # The rule must name at least two of the four `error_type` enum values
    # so the agent has concrete vocabulary for its reasoning.
    named = [v for v in _ERROR_TYPE_ENUM_VALUES if v in section]
    assert len(named) >= 2, (
        f"INV-A005 v1.23: §INV-A005 must name at least 2 of the four error_type "
        f"enum values (placeholder_rejected / host_failure / network_error / "
        f"http_error) for the agent's reasoning vocabulary. Found: {named}"
    )


def test_invA005_v123_system_prompt_teaches_analyze_and_present_discipline() -> None:
    """INV-A005 v1.23 (Phase 4 of agent-synthesis-over-rich-tool-data): the
    §INV-A005 section MUST teach the agent to ANALYZE the rich tool-result
    data and PRESENT findings to the user in plain, natural language —
    translation, not transcription; synthesis, not quotation.

    User correction (2026-05-28): the v1.22 mechanism forced the agent into
    robotic JSON-field transcription. The corrected design is: host returns
    rich data; agent interprets it; user reads natural language.
    """
    section_lower = _extract_invA005_section(_read_prompt()).lower()

    # Positive markers: at least 2 of these synthesis-oriented words must appear.
    synthesis_markers = (
        "analyze",
        "analyse",
        "present",
        "interpret",
        "understandable",
        "plain language",
        "natural language",
        "synthesize",
        "synthesise",
        "summarize",
        "summarise",
        "translate",
    )
    matched_synthesis = [m for m in synthesis_markers if m in section_lower]
    assert len(matched_synthesis) >= 2, (
        f"INV-A005 v1.23: §INV-A005 must teach analyze-and-present discipline "
        f"(must mention at least 2 of {synthesis_markers}). Found: {matched_synthesis}"
    )

    # The rule must also teach that structured fields are for REASONING, not
    # for verbatim insertion into the reply.
    assert "reasoning" in section_lower or "reason" in section_lower, (
        "INV-A005 v1.23: §INV-A005 must teach that structured fields exist "
        "for the agent's REASONING (not for verbatim insertion). "
        "The word 'reasoning' or 'reason' must appear."
    )
    anti_transcription_markers = (
        "not for verbatim",
        "not for quoting",
        "do not quote",
        "not insert",
        "not transcribe",
        "not repeat verbatim",
        "do not just",
        "not just quote",
        "translation, not transcription",
        "synthesis, not quotation",
    )
    matched_anti = [m for m in anti_transcription_markers if m in section_lower]
    assert len(matched_anti) >= 1, (
        f"INV-A005 v1.23: §INV-A005 must explicitly warn against verbatim "
        f"transcription of structured fields (must mention at least 1 of "
        f"{anti_transcription_markers}). Found: {matched_anti}"
    )


def test_invA005_v123_system_prompt_does_not_mandate_verbatim_quoting() -> None:
    """INV-A005 v1.23 (Phase 4 of agent-synthesis-over-rich-tool-data,
    negative gate): the §INV-A005 section MUST NOT carry the v1.22
    verbatim-quoting language. Specifically, it must NOT contain phrasings
    like 'MUST contain at least one backtick-quoted excerpt' or
    'quote verbatim before paraphrasing' — those are the v1.22 mistake.

    This gate protects against an accidental revert.
    """
    section_lower = _extract_invA005_section(_read_prompt()).lower()

    # Phrases that, if present, indicate the v1.22 verbatim-quoting mandate
    # has crept back in. Each is a specific construction from the v1.22 prompt.
    forbidden_v122_phrasings = (
        "must contain at least one backtick",
        "must contain a backtick",
        "backtick-quoted excerpt",
        "quote verbatim before paraphrasing",
        "quote the actual `error_type`",
        "quote the actual error_type",
        "verbatim before paraphrasing",
        "reply must quote",
        "your reply must contain",
        "must quote at least one",
    )
    present = [p for p in forbidden_v122_phrasings if p in section_lower]
    assert not present, (
        "INV-A005 v1.23 negative gate: §INV-A005 must NOT mandate verbatim "
        f"quoting of structured fields. Found v1.22-era phrasings: {present}. "
        "The corrected rule is analyze-and-present, not transcribe-verbatim. "
        "See [docs/plans/active/agent-synthesis-over-rich-tool-data/] for the "
        "rewrite rationale."
    )


def test_invA005_v123_system_prompt_teaches_multi_turn_investigation() -> None:
    """INV-A005 v1.23 (renamed from v1.22 — content unchanged): when the agent
    encounters an `error_type` it doesn't recognise, or a structured field
    whose value is surprising, the §INV-A005 section MUST authorize calling
    additional diagnostic tools (`genomeclaw_status`, retry, fetch logs) —
    rather than paraphrase from prior context or guess from memory notes.

    User's stated architecture preference (2026-05-28): *"rely on the OpenClaw
    agent to receive raw returns and evaluate multi-turn on a loop, calling
    more tools as it needs more info."*
    """
    section_lower = _extract_invA005_section(_read_prompt()).lower()

    # The rule must authorize multi-turn investigation, expressed in any of
    # these forms.
    investigation_markers = (
        "multi-turn",
        "multi turn",
        "call another tool",
        "call additional",
        "investigate",
        "retry",
    )
    matched = [m for m in investigation_markers if m in section_lower]
    assert len(matched) >= 2, (
        f"INV-A005 v1.23: §INV-A005 must authorize multi-turn investigation "
        f"under unfamiliar failure shapes (must mention at least 2 of "
        f"{investigation_markers} in §INV-A005). Found: {matched}"
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

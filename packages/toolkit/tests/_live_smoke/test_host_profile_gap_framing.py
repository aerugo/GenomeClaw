"""INV-C004 / INV-A005 — live behavioural gate: profile-gap framing.

Fixture: a host profile whose ``medical_history.medications`` section is
empty. Question: whether a warfarin-response PGS is relevant to the user
(a pharmacogenomics question — its interpretation hinges on current
medications). The agent should:

1. Retrieve the host profile (Step 1.5) — ideally scoped to
   ``medical_history.medications``.
2. See the empty section, surface the gap, and recommend the
   ``genomeclaw host profile set medical_history.medications.add`` (or
   ``init``) command.
3. NOT paraphrase the 200 + ``missing``/empty response as a tool failure
   (INV-A005).
4. NOT invent a fictional medication list to proceed.

INV-V001 discipline: the **primary** load-bearing assertion is structural
— the trace contains a ``genomeclaw_host_profile`` tool call. The
reply-content checks (gap named, command recommended, no invented meds)
are explicitly-annotated backstops, not the primary gate; the structural
trace-walk gate (``test_invC004_trace_walk_host_profile_called.py``) is the
durable enforcement.

Cost: one real OpenAI call against the rebuilt sandbox image. Auto-skipped
unless ``OPENAI_API_KEY`` + ``GENOMECLAW_SANDBOX_IMAGE`` are set (see the
``live_llm`` collection gate in ``tests/conftest.py``).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from genomeclaw_toolkit.host_profile.store import write_profile_atomic
from genomeclaw_toolkit.schemas.host_profile import HostProfile
from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import stage_empty_run

_QUESTION = (
    "Is a polygenic score for warfarin dose / response relevant to me right now? "
    "Check my genome and my recorded medications before you answer."
)

# Profile with an explicitly-empty medications section (the gap under test).
_PROFILE_NO_MEDS = {
    "schema_version": "host_profile/1.0",
    "meta": {"created_at": "2026-05-31T00:00:00Z", "updated_at": "2026-05-31T00:00:00Z"},
    "identity": {"sex_assigned_at_birth": "male", "ancestry": {"groups": ["european"]}},
    "medical_history": {"medications": []},
}

# INV-V001-backstop: meaning-bound reply checks. NOT the primary gate (the
# structural trace assertion below + the trace-walk gate are). Annotated per
# INV-V001 — these confirm the gap-framing reached the user-facing surface.
_GAP_NAMED = re.compile(r"medication", re.IGNORECASE)
_COMMAND_RECOMMENDED = re.compile(r"genomeclaw host profile (set|init)", re.IGNORECASE)


@pytest.mark.live_llm
def test_pgx_question_with_empty_medications_section_surfaces_gap(tmp_path: Path) -> None:
    """The agent retrieves the profile, surfaces the empty-medications gap, recommends the CLI."""
    derived_root = tmp_path / "derived"
    stage_empty_run(derived_root)
    write_profile_atomic(derived_root, HostProfile.model_validate(_PROFILE_NO_MEDS))

    trace = run_agent_in_sandbox(
        _QUESTION,
        derived_root=derived_root,
        sandbox_image=os.environ["GENOMECLAW_SANDBOX_IMAGE"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )

    assert trace.get("status") == "ok", f"agent run did not complete: {trace.get('status')!r}"
    trace_blob = json.dumps(trace)

    # PRIMARY (structural, INV-V001-allowed — target is the tool-call record):
    # the agent retrieved the host profile this turn.
    assert "genomeclaw_host_profile" in trace_blob, (
        "INV-C004: the agent did not call genomeclaw_host_profile on a "
        "genome-informable PGx turn (Step 1.5 not honoured)."
    )

    payloads = trace.get("result", {}).get("payloads", [])
    assert payloads and payloads[0].get("text"), "agent produced no user-facing reply"
    reply = payloads[0]["text"]

    # Backstops (INV-V001-backstop): the gap-framing reached the reply.
    assert _GAP_NAMED.search(reply), (
        f"reply did not name the medications gap; prefix: {reply[:400]!r}"
    )
    assert _COMMAND_RECOMMENDED.search(reply), (
        "reply did not recommend a `genomeclaw host profile set/init` command to "
        f"fill the gap; prefix: {reply[:600]!r}"
    )
    # INV-A005 regression backstop: the empty-section signal must not be
    # narrated as a host/tool failure.
    assert "HTTP 500" not in trace_blob, "host-profile read should not 500 on an empty section"

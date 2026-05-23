"""Phase 1 reproducer for the openclaw tool-call serialization investigation.

Plan: [docs/plans/active/openclaw-toolcall-serialization-investigation/](
    ../../../../docs/plans/active/openclaw-toolcall-serialization-investigation/)
Phase: [phase-1.md](
    ../../../../docs/plans/active/openclaw-toolcall-serialization-investigation/phases/phase-1.md)

Background
----------

The 2026-05-23 agent-prs-compute-fix iteration surfaced two correlated
tool-call argument-serialization symptoms (see ``spec.md``):

- Symptom A: ``genomeclaw_gene(gene="undefined")`` x7 in one run. The
  agent intended specific gene lookups (CFH/ARMS2/HTRA1 in the v3
  trace); openclaw delivered the literal string ``"undefined"`` to the
  plugin's ``execute()``.
- Symptom B: ``POST /v1/pgs/compute`` with a bare-string body
  ``"call_<id>|fc_<id>"`` x2 (a tool-call ID), instead of the expected
  ``PgsComputeRequest`` JSON object.

Both shapes are defanged today by the runtime arg-guard in commit
``b8b7954`` (``rejectIfPlaceholder`` at plugin ``execute()`` entry), but
the upstream cause is unknown. This test is the deterministic reproducer
the plan calls for: a synthetic prompt that forces 5 sequential
``genomeclaw_gene`` calls, against a minimal empty derived-root, so
corrupted ``args.gene === "undefined"`` requests vs. intact ones can be
counted.

Why count via the trace blob (and not the host log)
---------------------------------------------------

The arg-guard at ``b8b7954`` catches corrupted calls BEFORE they hit the
host service, so the host log doesn't see the corruption: a corrupted
call now produces ``failedTextResult`` text containing ``placeholder
string`` (the guard's error message). Intact calls produce ``GET /v1/gene/<NAME>``
host log entries (visible at uvicorn's stdout — not currently surfaced
back through the harness; would require a follow-up patch to
``host_service_running`` to expose them).

For Phase 1's purpose (does the symptom still trigger? at what rate?)
the trace blob is sufficient: every corruption produces a tool-result
text containing ``placeholder string`` and every intact call produces a
tool-result containing the gene name. Counting both is enough to
compute a corruption rate.

Operator setup
--------------

Same prerequisites as ``test_live_agent_prs_compute_e2e.py``:

1. Rebuild the sandbox image so the agent picks up the latest plugin:
   ``cd packages/nemoclaw-plugin/sandbox && docker build -t genomeclaw/sandbox:phase-1-repro .``
2. Export ``GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-1-repro``
   and ``OPENAI_API_KEY=sk-...``.

The test is ``@pytest.mark.live_llm`` gated; ``tests/conftest.py``
auto-skips collection when those env vars are absent.

Cost: one real OpenAI call (~USD 0.30-0.60, 3-5 min wall-clock).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import stage_empty_run

# The 5-gene reproducer prompt the plan specifies. The eyesight question
# from the 2026-05-23 v3 trace triggered Symptom A 7/7 times for the
# CFH/ARMS2/HTRA1 lookups; this is the reduced synthetic restatement.
# Reduced to 5 genes for a tighter signal + a clean denominator.
REPRO_PROMPT = (
    "I want to know what variants I have in the genes CFH, ARMS2, HTRA1, "
    "ABCA4, and USH2A. For each, call genomeclaw_gene with the gene name "
    "and report the variant counts."
)

# The five genes the agent should look up. Every corrupted call costs
# the agent a turn + appears in the trace as a ``placeholder string``
# arg-guard failure; every intact call appears as either a real gene
# payload (empty store -> 404 from /v1/gene/<NAME>) or a 404 surfaced
# back to the agent. The DENOMINATOR is the number of tool-call attempts
# the agent makes against ``genomeclaw_gene``.
EXPECTED_GENES = ("CFH", "ARMS2", "HTRA1", "ABCA4", "USH2A")

# Phase 1 target: baseline corruption rate observed at 2026-05-23 was
# ~80% (7/7 in v3 with the un-guarded plugin; the v4 fix defanged the
# host-side impact but the underlying corruption rate is unchanged).
# Phase 1+2 want to understand the rate, not improve it; Phase 3 may
# drive it to 0% via Path U / D / L. The 0.2 ceiling on this assertion
# is the "we successfully picked a low rate path" gate — if corruption
# stays above 0.2 after Phase 3's fix, the fix didn't land.
PHASE_1_2_CORRUPTION_CEILING = 0.2


def _count_corruption_in_trace(trace_blob: str) -> tuple[int, int, list[str]]:
    """Count corrupted vs. intact ``genomeclaw_gene`` tool calls in the trace.

    The arg-guard at ``packages/nemoclaw-plugin/src/index.ts`` emits a
    ``failedTextResult`` whose ``content[].text`` starts with
    ``genomeclaw_gene: argument `gene` is the placeholder string``. Every
    corruption produces one such entry. Intact calls either produce a
    payload row (if the store has data for the gene) or a 404 wrapped in
    ``genomeclaw-service ... -> HTTP 404`` (from ``safeCall``'s catch
    block).

    Returns ``(corrupted_count, intact_count, intact_gene_names)``.
    """
    corrupted = len(
        re.findall(
            r"genomeclaw_gene:\s+argument\s+`gene`\s+is\s+the\s+placeholder\s+string",
            trace_blob,
        )
    )
    # Intact-call evidence: either the host service returned a real
    # payload, or the plugin's safeCall captured a non-placeholder HTTP
    # error against the real gene path. Both leave the gene name
    # somewhere in the trace text (in a tool-result text body OR in the
    # error envelope's path field).
    intact_genes: list[str] = []
    for gene in EXPECTED_GENES:
        # ``/v1/gene/CFH`` appears in the safeCall error envelope's
        # ``path`` field on a 404; the same path is also in the success
        # payload's URL provenance. Either way, an intact call produces
        # the path. The negative-lookbehind on ``undefined`` is to avoid
        # double-counting if the trace happens to include the literal
        # word in plain prose; the ``/v1/gene/`` prefix keeps the regex
        # tight enough.
        if re.search(rf"/v1/gene/{re.escape(gene)}\b", trace_blob):
            intact_genes.append(gene)
    return corrupted, len(intact_genes), intact_genes


@pytest.mark.live_llm
def test_openclaw_tool_call_args_corruption_rate(tmp_path: Path) -> None:
    """Phase 1 deterministic reproducer for the tool-call arg-serialization bug.

    Stages an empty derived run (no findings data — the genes will all
    404 even on intact calls; that's intentional, we're measuring
    serialization, not store contents), prompts the agent to call
    ``genomeclaw_gene`` five times in sequence, and counts how many of
    those calls arrived at the plugin with ``args.gene === "undefined"``
    vs. with the intended gene symbol.

    Acceptance bar (Phase 1 + Phase 3 combined):
    - The agent attempted ``>= 4`` of the 5 gene lookups (i.e. it didn't
      just decline; it tried to call the tool).
    - ``corruption_rate <= 0.2``.

    Today (with only the b8b7954 runtime arg-guard in place upstream of
    a fix), the baseline expectation is ~0.8. The test is RED until
    Phase 3's chosen Path lands; that's the design.
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root = tmp_path / "derived"
    stage_empty_run(derived_root)

    trace = run_agent_in_sandbox(
        REPRO_PROMPT,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        # 5 gene lookups + the per-call thinking-mode budget; 8 min is
        # generous but leaves headroom for the cross-model bisect in
        # Phase 2 to reuse this harness shape.
        timeout_s=480,
    )

    assert trace.get("status") == "ok", (
        f"agent run did not complete cleanly: status={trace.get('status')!r}\n"
        f"trace prefix: {json.dumps(trace)[:1000]!r}"
    )

    trace_blob = json.dumps(trace)
    corrupted, intact_count, intact_genes = _count_corruption_in_trace(trace_blob)
    attempts = corrupted + intact_count

    assert attempts >= 4, (
        "agent did not attempt enough genomeclaw_gene tool calls to measure a "
        f"corruption rate (saw {attempts} attempts: {corrupted} corrupted + "
        f"{intact_count} intact). Re-check the prompt + sandbox image.\n"
        f"intact genes seen: {intact_genes!r}\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

    corruption_rate = corrupted / attempts if attempts else 0.0
    assert corruption_rate <= PHASE_1_2_CORRUPTION_CEILING, (
        "openclaw tool-call argument-serialization corruption rate exceeds the "
        f"Phase 1+2 ceiling ({PHASE_1_2_CORRUPTION_CEILING:.0%}). "
        f"Observed: {corrupted}/{attempts} corrupted ({corruption_rate:.0%}). "
        "This is the Phase 1 baseline that motivated the investigation; the "
        "test is RED until Phase 3's chosen Path (U/D/L) lands.\n"
        f"intact genes seen: {intact_genes!r}\n"
        f"trace prefix: {trace_blob[:2000]!r}"
    )

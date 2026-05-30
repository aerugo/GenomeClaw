"""Phase 6 RED — live agent end-to-end PRS compute test.

Closes [docs/plans/active/agent-prs-compute-fix/](../../../../docs/plans/active/agent-prs-compute-fix/).
Verifies the user-facing outcome the plan promised: the AMD-question
agent invocation that hit ``HTTP 422`` on 2026-05-23 now reaches a
terminal state (``done`` OR a structurally-named ``failed:<class>``) —
NOT ``HTTP 422``, NOT ``queued`` forever.

**Phase 6 acceptance bar** (per the spec + phase plan): the agent must
reach a terminal state with a structurally-named outcome. A successful
percentile compute is the happy path; a clean
``failed:scorefile_missing:PGS<id>`` (or similar structured error) is
also a valid pass as long as the agent's reply explains the situation
clearly. The bar is **plumbing works end-to-end**, not "every PGS
Catalog scorefile is pre-staged on the operator's deployment".

**Operator setup before running this test live**:

1. Rebuild the sandbox image so the agent picks up the Phase 2 plugin
   TypeBox change (rationale minLength 50 → 10):
   ``cd packages/nemoclaw-plugin/sandbox && docker build -t genomeclaw/sandbox:phase-6 .``
2. Export ``GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-6`` +
   ``OPENAI_API_KEY=sk-...``.
3. For real-compute verification (slow, OPTIONAL): set
   ``GENOMECLAW_PGS_E2E_REAL_RUN_DIR=<path>`` to the canonical Phase 7
   run-dir containing a real ``prs_compute_config.json`` sidecar +
   pre-staged scorefiles. Without this env var, the test stages a
   minimal fixture pointing at non-existent scorefiles — the worker
   maps the missing scorefile to a structured failure + the agent
   reaches a terminal state without firing pgsc_calc.

Plan: [docs/plans/active/agent-prs-compute-fix/phases/phase-6.md](../../../../docs/plans/active/agent-prs-compute-fix/phases/phase-6.md)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

import pytest

from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)
from tests._live_smoke.run import run_agent_in_sandbox
from tests._live_smoke.staging import stage_empty_run

# The AMD-question prompt from the 2026-05-23 trace that triggered the
# original HTTP 422. Phrased to invite — not require — a PRS compute, so
# the agent's behaviour mirrors the real-user discovery path.
AMD_QUESTION = (
    "Do I have any increased risk of losing eyesight when I age? Look at the "
    "genomeclaw findings, research the relevant polygenic risk literature for "
    "age-related macular degeneration (AMD), and if you find a canonical AMD "
    "PGS Catalog scorefile, compute it for me. Cite the PGS Catalog ID and "
    "explain what the percentile means in plain language."
)

# Terminal-state markers in the agent's reply that satisfy the
# "agent surfaced a clear outcome" requirement.
_PERCENTILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d+(?:\.\d+)?\s*(?:st|nd|rd|th|%)?\s*percentile", re.IGNORECASE),
    re.compile(r"top\s+(?:decile|quartile|quintile)", re.IGNORECASE),
    re.compile(r"\b(?:upper|lower)\s+decile", re.IGNORECASE),
    re.compile(r"above[- ]average", re.IGNORECASE),
)

# INV-V001-backstop: regression pin for the worker's structured-error vocabulary.
# The first half of this tuple matches the host service's machine-readable error
# codes (`scorefile_missing`, `pgsc_calc_failed`, etc.); the second half attempts
# to enumerate the agent's natural-language rephrasings — the latter is exactly
# the phrase-enumeration class INV-V001 forbids as primary verification. Real
# load-bearing correctness lives in INV-A005 v1.22's structural walker, which
# checks the agent quoted `error_type` literally. TODO(inv-a005-structural-
# faithfulness post-merge): remove the plain-language patterns; the structured
# walker subsumes them.
# Structured-failure markers the worker emits via _structured_error.
# Each maps to a clean operator-actionable next step in the agent reply.
_STRUCTURED_FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"scorefile[_ ]missing", re.IGNORECASE),
    re.compile(r"scorefile\s+not\s+(?:staged|found|fetched)", re.IGNORECASE),
    re.compile(r"pgsc[_ ]calc[_ ]failed", re.IGNORECASE),
    re.compile(r"dood[_ ]path[_ ]error", re.IGNORECASE),
    re.compile(r"prs[_ ]decline", re.IGNORECASE),
    re.compile(r"degenerate[_ ]result", re.IGNORECASE),
    re.compile(r"worker[_ ]restart", re.IGNORECASE),
    re.compile(r"compute[_ ]path[_ ]disabled", re.IGNORECASE),
    # Plain-language equivalents the agent may rephrase to:
    re.compile(r"scorefile.*not.*pre[- ]staged", re.IGNORECASE),
    re.compile(r"could\s+not\s+(?:compute|complete).*PRS", re.IGNORECASE),
    re.compile(r"(?:refs|reference).*fetch", re.IGNORECASE),
    re.compile(r"PRS\s+(?:could\s+not|failed|unavailable)", re.IGNORECASE),
)


def _stage_fixture_run_with_sidecar(tmp_path: Path) -> Path:
    """Stage a minimal derived/<run-id>/ + a sidecar pointing at non-existent paths.

    The worker tries ``_resolve_scorefile_path`` → ``PgsScorefileMissingError`` →
    the task transitions to ``failed:scorefile_missing:<pgs_id>``. That's
    the structured terminal state Phase 6 verifies the agent surfaces
    without an HTTP 422 / hung-queued failure.
    """
    derived_root = tmp_path / "derived"
    run_dir = stage_empty_run(derived_root)
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")

    # Sidecar pointing at non-existent paths — the worker will fail the
    # compute with scorefile_missing BEFORE pgsc_calc fires. This is the
    # right shape for an E2E plumbing test: we verify the agent surface
    # without paying the real-compute cost.
    (run_dir / "prs_compute_config.json").write_text(
        json.dumps(
            {
                "sample_id": "phase6-fixture",
                "cram_path": str(tmp_path / "nonexistent.cram"),
                "reference_root": str(tmp_path / "reference"),
                "scorefile_root": str(tmp_path / "scorefiles"),  # empty dir, no files
                "work_dir_root": str(tmp_path / "work"),
                "panel_version": "v1",
                "sites_tsv": str(tmp_path / "reference" / "sites.tsv"),
                "alleles_tsv": str(tmp_path / "reference" / "alleles.tsv"),
                "fasta": str(tmp_path / "reference" / "genome.fa"),
            }
        )
    )
    return derived_root


def _resolve_derived_root(tmp_path: Path) -> tuple[Path, bool]:
    """Pick the derived root: env override → real run-dir; else → tmp fixture.

    Returns (derived_root, is_real_run_dir).
    """
    real_run_dir = os.environ.get("GENOMECLAW_PGS_E2E_REAL_RUN_DIR")
    if real_run_dir:
        run_dir = Path(real_run_dir)
        if not (run_dir / "prs_compute_config.json").exists():
            raise RuntimeError(
                f"GENOMECLAW_PGS_E2E_REAL_RUN_DIR={real_run_dir} has no "
                "prs_compute_config.json sidecar. Stage it before running the "
                "real-compute path."
            )
        # The harness wants a derived root with CURRENT → run_dir/.
        # The real run-dir's parent IS the derived root + CURRENT must
        # already be set by the operator's prior `genomeclaw pipeline run`.
        return run_dir.parent, True
    return _stage_fixture_run_with_sidecar(tmp_path), False


def _read_task_db_states(derived_root: Path) -> list[tuple[str, str, str | None]]:
    """Read all pgs_compute_tasks rows: returns [(task_id, status, error), ...]."""
    current = derived_root / "CURRENT"
    if not current.exists():
        return []
    run_dir = current.resolve()
    db_path = run_dir / "pgs_compute_tasks.sqlite"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT task_id, status, error FROM pgs_compute_tasks").fetchall()
    finally:
        conn.close()


@pytest.mark.live_llm
def test_live_agent_amd_question_reaches_terminal_state(tmp_path: Path) -> None:
    """The agent reaches a terminal state — NOT HTTP 422, NOT queued forever.

    Acceptance criteria from spec.md AC7:
    - Reply does NOT contain "HTTP 422" (the validation fix from Phase 2 holds).
    - The agent invoked ``genomeclaw_pgs_compute`` at least once
      (guards against silent degradation to memory-only responses).
    - Task DB shows the task in a terminal state (``done`` or ``failed``),
      NOT ``queued`` or ``running``.
    - Reply contains EITHER a numeric percentile OR a structured
      named-reason explanation (one of the 6 failure modes from Phase 4
      _structured_error mapping, rephrased into plain language by the agent).
    """
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root, is_real_run = _resolve_derived_root(tmp_path)
    # 30 min for real pgsc_calc; 10 min for fixture (the AMD-question prompt
    # asks for web research + citations + a multi-step async compute flow —
    # the 2026-05-23 first live run measured 5 min and timed out at the
    # default 240+60 s harness cap).
    timeout_s = 1800 if is_real_run else 600

    trace = run_agent_in_sandbox(
        AMD_QUESTION,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=timeout_s,
    )

    # 1. Top-level shape (sandbox-side success).
    assert trace.get("status") == "ok", (
        f"agent run did not complete cleanly: status={trace.get('status')!r}\n"
        f"trace prefix: {json.dumps(trace)[:1000]!r}"
    )
    payloads = trace.get("result", {}).get("payloads", [])
    assert payloads, "agent produced no user-facing reply payload"
    reply = payloads[0].get("text", "")
    assert reply, "agent's first payload has empty text"

    # INV-V001-backstop: regression pin for the prs-input-coverage-fill Phase 2
    # 422 validation fix. The substring check guards against a specific bug
    # being reintroduced (HTTP 422 with `string_too_short` from a too-short
    # rationale arg). Load-bearing correctness for agent reply faithfulness
    # lives elsewhere (INV-A005 v1.22 structural walker).
    # 2. HTTP 422 guard — the Phase 2 fix must hold.
    trace_blob = json.dumps(trace)
    assert "HTTP 422" not in reply, (
        "agent's reply contains 'HTTP 422' — the Phase 2 validation fix did "
        "not reach the sandbox image. Rebuild the sandbox + retry.\n"
        f"reply prefix: {reply[:600]!r}"
    )
    assert "string_too_short" not in trace_blob, (
        "trace shows a Pydantic 'string_too_short' validation rejection — "
        "the host service is still on the pre-Phase-2 50-char threshold.\n"
        f"trace prefix: {trace_blob[:1200]!r}"
    )

    # 3. Agent invoked genomeclaw_pgs_compute (guards against silent
    # degradation to memory-only / non-tool replies).
    assert "genomeclaw_pgs_compute" in trace_blob, (
        "agent did not invoke genomeclaw_pgs_compute despite the prompt "
        "inviting a PRS compute. Either the agent declined (acceptable per "
        "INV-C001 v1.7) or the tool didn't register — inspect the trace.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )

    # 4. Task DB shows terminal state (done OR failed); NOT queued / running.
    task_rows = _read_task_db_states(derived_root)
    assert task_rows, (
        "no rows in pgs_compute_tasks.sqlite — either the agent's POST didn't "
        "land on the host service, or the route 422'd before enqueue."
    )
    terminal = [r for r in task_rows if r[1] in ("done", "failed")]
    pending = [r for r in task_rows if r[1] in ("queued", "running")]
    assert not pending, (
        "at least one task is stuck in queued/running — worker didn't drain.\n"
        f"pending rows: {pending!r}"
    )
    assert terminal, f"no terminal task rows: {task_rows!r}"

    # 5. Reply surfaces EITHER a percentile OR a structured named reason.
    has_percentile = any(p.search(reply) for p in _PERCENTILE_PATTERNS)
    has_named_reason = any(p.search(reply) for p in _STRUCTURED_FAILURE_PATTERNS)
    assert has_percentile or has_named_reason, (
        "agent's reply surfaces neither a PRS percentile nor a structured "
        "named-reason explanation. Per Phase 6 acceptance criteria, a clean "
        "structured-failure outcome (e.g. scorefile_missing) is acceptable as "
        "long as the agent surfaces it to the user; a silent degradation "
        "without an outcome is not.\n"
        f"task rows: {task_rows!r}\n"
        f"reply prefix: {reply[:1000]!r}"
    )

    # 6. Regression: no HTTP 500 markers (orthogonal to the 422 guard;
    # catches a different class of host-side breakage).
    assert "HTTP 500" not in trace_blob and '"status_code": 500' not in trace_blob, (
        "regression: trace contains an HTTP 500 marker — a genomeclaw tool "
        "call failed mid-protocol.\n"
        f"trace prefix: {trace_blob[:1500]!r}"
    )


@pytest.mark.live_llm
def test_invA003_pgs_scores_row_carries_agent_rationale_when_compute_succeeds(
    tmp_path: Path,
) -> None:
    """If the agent's compute SUCCEEDED, the pgs_scores row carries the agent's rationale.

    Only meaningful in the real-run-dir path (``GENOMECLAW_PGS_E2E_REAL_RUN_DIR``
    set + scorefile pre-staged + compute returns a numeric percentile). On
    the synthetic fixture path the compute fails with ``scorefile_missing``
    and no ``pgs_scores`` row is stamped — INV-R002 guard fires.

    The test is a soft check: if no ``pgs_scores`` row exists in the
    real-run-dir variant, the test SKIPS (legitimately — compute didn't
    succeed). If a row exists, INV-A003's two columns must be populated.
    """
    real_run_dir = os.environ.get("GENOMECLAW_PGS_E2E_REAL_RUN_DIR")
    if not real_run_dir:
        pytest.skip(
            "INV-A003 row-stamp assertion requires the real-run-dir path "
            "(set GENOMECLAW_PGS_E2E_REAL_RUN_DIR + pre-stage scorefiles)"
        )

    # The synthetic-fixture path never stamps a row (scorefile_missing
    # always fires); we only run this assertion when the real-compute path
    # might have produced a row.
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    derived_root, _ = _resolve_derived_root(tmp_path)

    run_agent_in_sandbox(
        AMD_QUESTION,
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=1800,
    )

    # Read pgs_scores from the real run-dir's variants.duckdb.
    current = derived_root / "CURRENT"
    run_dir = current.resolve()
    import duckdb

    conn = duckdb.connect(str(run_dir / "variants.duckdb"))
    try:
        rows = conn.execute(
            "SELECT pgs_id, agent_choice_rationale, requested_for_question "
            "FROM pgs_scores ORDER BY created_at DESC LIMIT 1"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        pytest.skip(
            "agent's compute didn't produce a pgs_scores row — likely failed "
            "with a structured terminal error (which is a valid Phase 6 outcome "
            "per the AMD-question acceptance bar; this INV-A003 assertion only "
            "fires when the compute succeeds)"
        )

    pgs_id, rationale, question = rows[0]
    assert rationale and rationale.strip(), (
        f"INV-A003: agent_choice_rationale is empty for {pgs_id!r}; "
        "the row should never persist without a non-empty rationale."
    )
    assert question and question.strip(), (
        f"INV-A003: requested_for_question is empty for {pgs_id!r}; "
        "the row should never persist without the originating question."
    )

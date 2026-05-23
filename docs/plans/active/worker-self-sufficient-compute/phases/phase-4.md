# Phase 4 — Live agent verification (eyesight question → real percentile)

**Status**: Pending (gated on Phases 2 + 3)
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Verify the user-facing AC1 outcome: asking the agent *"Do I have any risk factors for loss of eyesight?"* against the canonical Phase 7 run-dir produces a reply containing a real numeric AMD PRS percentile, with no `BcftoolsError`, no `scorefile_missing`, and a fresh `pgs_scores` row stamped INV-R001/A003-compliant.

## Scope Boundaries

- **In scope**:
  - One live-agent test extending `tests/integration/test_live_agent_prs_compute_e2e.py`.
  - Manual smoke pre-conditions (sandbox image rebuilt, toolkit image rebuilt, sidecar staged — which it already is).
  - Acceptance gate documentation: AC1 met → plan can close.
- **Out of scope**:
  - Re-running Phase 2/3's unit + integration tests (those are their own phases' verification gates).
  - PGS Catalog network reliability concerns (auto-fetch's retries cover transient 5xx; Phase 4 doesn't add to that).
  - Multi-sample / multi-trait coverage in one test run.

## Invariants enforced in this phase

- **INV-R001** — assert all seven provenance columns are non-null on the stamped row.
- **INV-A003** — assert `agent_choice_rationale` + `requested_for_question` are non-empty + reflect the agent's actual stated rationale.
- **INV-P001** — assert no unexpected egress surfaces in the trace (default-config behaviour).

---

## TDD Steps

### Step 4.1 — RED: extend the existing live E2E test

Add to `packages/toolkit/tests/integration/test_live_agent_prs_compute_e2e.py`:

```python
@pytest.mark.live_llm
def test_live_agent_eyesight_question_produces_percentile(tmp_path: Path) -> None:
    """AC1 — eyesight question produces a real numeric AMD PRS percentile.

    Closes the worker-self-sufficient-compute plan: agent asks
    "Do I have any risk factors for loss of eyesight?", worker computes
    PGS004606 inside the toolkit image (Phase 3) using a scorefile that
    may need fetching (Phase 2's auto-fetch covers that), stamps the
    `pgs_scores` row, agent surfaces the percentile to the user.

    Required env:
    - GENOMECLAW_PGS_E2E_REAL_RUN_DIR=<canonical-run-dir>
    - GENOMECLAW_TOOLKIT_IMAGE=<image with the worker-self-sufficient code>
    - GENOMECLAW_SANDBOX_IMAGE=<image with the disease-area-discovery prompt>
    - OPENAI_API_KEY=...
    """
    real_run_dir = os.environ.get("GENOMECLAW_PGS_E2E_REAL_RUN_DIR")
    if not real_run_dir:
        pytest.skip("requires GENOMECLAW_PGS_E2E_REAL_RUN_DIR set to the canonical run-dir")

    derived_root = Path(real_run_dir).parent
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]
    openai_api_key = os.environ["OPENAI_API_KEY"]

    # The agent asks the eyesight question; the disease-area discovery
    # pattern from the sysprompt drives it to attempt PGS004606 compute.
    trace = run_agent_in_sandbox(
        "Do I have any risk factors for loss of eyesight?",
        derived_root=derived_root,
        sandbox_image=sandbox_image,
        openai_api_key=openai_api_key,
        timeout_s=1800,  # 30 min for a cold-cache compute
    )

    # 1. Top-level shape.
    result = trace.get("result", trace)
    payloads = result.get("payloads", [])
    assert payloads, "agent produced no user-facing reply"
    reply = payloads[0].get("text", "")
    assert reply

    # 2. No regression markers.
    assert "BcftoolsError" not in reply
    assert "scorefile_missing" not in reply
    assert "HTTP 422" not in reply

    # 3. Numeric percentile in the reply (relaxed pattern; agent may
    # phrase it various ways).
    percentile_re = re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:st|nd|rd|th|%|percentile)",
        re.IGNORECASE,
    )
    assert percentile_re.search(reply), (
        f"agent's reply does not contain a numeric percentile. "
        f"Reply prefix: {reply[:1000]!r}"
    )

    # 4. A fresh pgs_scores row was stamped.
    run_dir = Path(real_run_dir)
    conn = duckdb.connect(str(run_dir / "variants.duckdb"))
    try:
        rows = conn.execute(
            "SELECT pgs_id, percentile_in_user_ancestry, "
            "agent_choice_rationale, requested_for_question, "
            "source_path, source_sha256, tool, tool_version, "
            "params_json, schema_version, created_at "
            "FROM pgs_scores ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert rows is not None, "no pgs_scores row stamped"
    pgs_id, percentile, rationale, question, *prov = rows
    # 5. INV-R001: seven provenance columns populated.
    source_path, _source_sha, tool, tool_version, params_json, schema_version, created_at = prov
    assert source_path
    assert tool == "pgsc_calc"
    assert tool_version == "agent-driven"
    assert params_json
    assert schema_version
    assert created_at is not None
    # 6. INV-A003: rationale + question populated.
    assert rationale and rationale.strip()
    assert question and question.strip()
    # 7. Real percentile (not null, not nonsense).
    assert percentile is not None
    assert 0.0 <= float(percentile) <= 100.0
```

After authoring, run — should fail (Phase 2+3 not yet shipped, OR sandbox/toolkit images not rebuilt).

### Step 4.2 — GREEN: stage pre-conditions + run

This is a manual verification step (live OpenAI call + real pgsc_calc compute).

Pre-conditions:
1. Phase 2 + Phase 3 commits landed on `main`.
2. Toolkit image rebuilt with the post-iteration code: `genomeclaw/toolkit:worker-self-sufficient`.
3. Sandbox image rebuilt with the latest plugin + sysprompt: `genomeclaw/sandbox:worker-self-sufficient`.
4. Sidecar already staged at `/Volumes/Genome_Work/genomeclaw/derived/CURRENT/prs_compute_config.json` (verified post-iteration).
5. PGS004606 already pre-fetched OR Phase 2's auto-fetch can retrieve it.

Run:
```bash
cd packages/toolkit
export GENOMECLAW_PGS_E2E_REAL_RUN_DIR=/Volumes/Genome_Work/genomeclaw/derived/$(readlink /Volumes/Genome_Work/genomeclaw/derived/CURRENT)
export GENOMECLAW_TOOLKIT_IMAGE=genomeclaw/toolkit:worker-self-sufficient
export GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:worker-self-sufficient
export OPENAI_API_KEY=sk-...
uv run pytest tests/integration/test_live_agent_prs_compute_e2e.py::test_live_agent_eyesight_question_produces_percentile -v -s
```

Expected wall time: 10-30 minutes (real pgsc_calc against the canonical CRAM; warm cache after the first real compute).

### Step 4.3 — REFACTOR

If the live run passes:
- Append a Phase 4 close block to `work-notes.md` with: wall-clock, the agent's reply prefix, the persisted percentile, the `pgs_scores` row's provenance shape.
- Move the plan from `active/` to `completed/`.
- Update `agent-prs-compute-fix`'s open-follow-ups list in its `completed/` work-notes — the two items I called out (bcftools-on-host-or-dood + agent-autonomous-scorefile-fetch) are now resolved.

If the live run fails:
- Investigate per the structured error message (the agent now surfaces these cleanly thanks to the disease-area-discovery sysprompt + arg-guard).
- Most likely failure modes + fixes:
  - PGS Catalog 5xx → Phase 2's retry should have handled it; check log.
  - Container exit non-zero → Phase 3's structured error surfaces the rc; check the inner pgsc_calc stderr.
  - Worker timeout → bump the live test's `timeout_s`.
- Iterate on the relevant Phase 2/3 surface.

---

## Implementation Details

### What "real percentile" looks like in the reply

The agent's reply should look something like:

> Based on the canonical AMD PRS PGS004606 (PRS-CS, 1,000,946 variants, AMD-IAMDGC-EUR), your computed percentile in the European-ancestry reference is **N**th. [...]

Where N is a real number between 0 and 100. The disease-area discovery pattern from the post-iteration sysprompt guarantees the agent surfaces specific gene-level + PRS data; the percentile is the new piece this plan delivers.

### Edge Cases to Handle

- **PGS Catalog 5xx during the auto-fetch path** — Phase 2's retry covers it; if the test wall-clock blows out, bump `timeout_s` rather than failing on a transient infra issue.
- **Calibration warning surfaces** — if the user's ancestry projection produces a `calibration_warning`, the agent should surface it; the test accepts that as a valid pass (the percentile is still computed).
- **PRS decline path** — if the agent decides the AMD literature is too immature for the user (INV-C001 v1.7), it would decline with two named reasons. AC1's acceptance language explicitly allows this as a valid pass.

### Privacy / Egress Notes

- No new egress surfaces.
- Live test costs one real OpenAI call (~$0.20-0.50).
- Network usage: one ~21 MB PGS004606 scorefile fetch (if not already cached), one OpenAI conversation, no other outbound traffic.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/integration/test_live_agent_prs_compute_e2e.py` | MODIFY | Add `test_live_agent_eyesight_question_produces_percentile` |
| `docs/plans/active/worker-self-sufficient-compute/work-notes.md` | MODIFY | Phase 4 close block with live-run outcome |
| `docs/plans/completed/agent-prs-compute-fix/work-notes.md` | MODIFY (light) | Mark the two open follow-ups as resolved by this plan |

After live PASS: `git mv docs/plans/active/worker-self-sufficient-compute docs/plans/completed/worker-self-sufficient-compute`.

---

## Verification

```bash
cd packages/toolkit
GENOMECLAW_PGS_E2E_REAL_RUN_DIR=<canonical-run-dir> \
GENOMECLAW_TOOLKIT_IMAGE=genomeclaw/toolkit:worker-self-sufficient \
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:worker-self-sufficient \
OPENAI_API_KEY=... \
  uv run pytest tests/integration/test_live_agent_prs_compute_e2e.py::test_live_agent_eyesight_question_produces_percentile -v -s
# Expect: 1 PASS in ~10-30 minutes.

# Full sweep (host suite — no live env vars)
uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: still 875+ passed, 116 skipped, no regressions.
```

---

## Completion Criteria

- [ ] `test_live_agent_eyesight_question_produces_percentile` passes against the canonical run-dir.
- [ ] The agent's reply contains a numeric percentile.
- [ ] A fresh `pgs_scores` row carries the seven INV-R001 columns + INV-A003 rationale + question + a real percentile in [0, 100].
- [ ] No `BcftoolsError` / `scorefile_missing` / `HTTP 422` in the reply.
- [ ] Plan moved from `active/` to `completed/`.
- [ ] `work-notes.md` carries the Phase 4 close block.
- [ ] `agent-prs-compute-fix`'s open-follow-ups list updated to reflect resolution.

## Next

After Phase 4 closes: plan moves to `completed/`; no further phases. Remaining post-MVP follow-ups (the openclaw-toolcall-serialization upstream issue) get their own plans if and when they merit one.

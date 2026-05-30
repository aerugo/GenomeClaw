# Phase 2: Agent Surface + System-Prompt Clause

**Status**: Complete (synthetic smoke); real-data smoke pending project-owner
**Started**: 2026-05-25
**Completed**: 2026-05-25
**Plan**: [development-plan.md](../development-plan.md)
**Spec**: [spec.md](../spec.md)

---

## Objective

Make the indeterminate CYP2D6 finding **fully observable to the agent**: the row is already in `findings.duckdb` after Phase 1, but the agent's read path needs three things added before it can surface the row correctly:

1. The `cyrius_no_call:` evidence-ref prefix must resolve via `/v1/evidence/{ref}` rather than 404 (otherwise the agent's `genomeclaw_evidence` tool gives a dead link).
2. The agent system prompt must teach the agent to suppress "Normal Metabolizer" language when CYP2D6 is indeterminate — current § 6 (clinical-actionable framing) doesn't name this case explicitly.
3. An integration test confirms the row flows end-to-end: `cyp2d6-call` on a no-call → `/v1/findings?genes=CYP2D6` returns it → `/v1/evidence/cyrius_no_call:<path>` resolves it.

## Invariants Enforced in This Phase

- **INV-E001** — `evidence_ref` is machine-resolvable; the agent's `genomeclaw_evidence` tool returns a real record (not 404) when given the no-call ref. Verified by `test_evidence_resolver_handles_cyrius_no_call_ref`.

- **INV-C001 v1.7** — The system prompt teaches the "suppress Normal Metabolizer" rule for the CYP2D6 indeterminate case explicitly. Verified by `test_system_prompt_teaches_cyp2d6_indeterminate_handling`.

- **INV-P002** — The `cyrius_no_call` evidence record is summary-class (no raw genomic sequence; minimal-sufficient fields only). Verified by the resolver returning a small dict with only the audit-relevant fields (sample_id, filter_status, provenance summary). The raw Cyrius output is NOT included in the response.

---

## Files

| Action | File | Notes |
|--------|------|-------|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py` | Add `"cyrius_no_call"` to `EvidenceKind` Literal |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | Add `"cyrius_no_call"` to `_SUPPORTED_EVIDENCE_KINDS`; add `_resolve_cyrius_no_call` function |
| MODIFY | `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | Add CYP2D6 indeterminate clause under § 6 |
| CREATE | `packages/toolkit/tests/integration/test_evidence_cyrius_no_call.py` | Integration: HTTP `/v1/evidence/cyrius_no_call:<path>` round-trip |
| MODIFY | `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` | Add `test_system_prompt_teaches_cyp2d6_indeterminate_handling` |
| MODIFY | `packages/toolkit/tests/integration/test_cli_pipeline_cyp2d6_no_call.py` | Add `test_indeterminate_finding_reaches_findings_api` integration test |

---

## Step 2.1 — RED: Failing tests

**test_evidence_resolver_handles_cyrius_no_call_ref** (new integration test)

Write a fixture sentinel file at `<tmp>/run/cyp2d6_no_call_envelope.json`; call `resolve_evidence(run_dir=..., ref="cyrius_no_call:<absolute_path>")`; assert the returned dict carries:
- `kind == "cyrius_no_call"`
- `id == <sentinel_path>` (the absolute path is the identifier)
- A summary block containing `sample_id`, `filter_status`, and `tool_version` (NOT `raw_cyrius_output` — that's the on-disk evidence, not the response payload per INV-P002).

Expected RED: `resolve_evidence` raises `UnknownEvidenceKindError` because `cyrius_no_call` is not in `_SUPPORTED_EVIDENCE_KINDS`.

**test_indeterminate_finding_reaches_findings_api** (new integration test in test_cli_pipeline_cyp2d6_no_call.py)

After running `cyp2d6-call` on a no-call fixture (same setup as the Phase 1 integration test), spin up the host FastAPI app via TestClient and call `GET /v1/findings?genes=CYP2D6`. Assert:
- response is 200
- exactly one finding row appears
- the row has `category="clinical-actionable"`, `evidence_ref` starting with `"cyrius_no_call:"`, and `summary` containing "do not interpret as Normal Metabolizer" (case-insensitive)

Expected RED: works in Phase 1 already? Likely passes immediately since the row is already inserted. Run it to confirm and document. If it passes, this is a regression-pin test rather than a RED test (acceptable per the planning protocol).

**test_system_prompt_teaches_cyp2d6_indeterminate_handling** (new contract test)

Assert the system prompt contains:
- The string `CYP2D6` (the gene name)
- The phrase `indeterminate` (case-insensitive)
- A "do not interpret as Normal Metabolizer" rule somewhere in the prompt

Expected RED: the prompt does not currently teach this case.

---

## Step 2.2 — GREEN: Minimal implementation

**Order**:

1. **Schema extension**: Add `"cyrius_no_call"` to the `EvidenceKind` Literal in `schemas/evidence.py`. Bumps the documented kind table.

2. **Service resolver**: Add `_resolve_cyrius_no_call(run_dir, ident)` to `service/store.py` that:
   - Treats `ident` as the absolute path to the sentinel file (relative paths rejected as invalid).
   - Reads the JSON; extracts `sample_id`, `filter_status`, and `provenance.tool_version`.
   - Returns a dict matching the `EvidenceRecord` shape: `{"kind": "cyrius_no_call", "id": ident, "summary": "CYP2D6 could not be called from this sample's coverage at the CYP2D6/CYP2D7 locus.", "classification": "indeterminate", "review_status": "tool-emitted", "url": None}`.
   - Returns `None` if the sentinel doesn't exist (route turns into 404).
   - Per INV-P002, does NOT include the raw Cyrius output, nor the BAM SHA256 (the agent doesn't need either to render the indeterminate framing).
   - Add `"cyrius_no_call"` to `_SUPPORTED_EVIDENCE_KINDS` and to the dispatch chain in `resolve_evidence`.

3. **System prompt amendment**: Add a paragraph under § 6 (Lifestyle vs clinical) explicitly naming the CYP2D6 indeterminate case:

   ```
   **CYP2D6 indeterminate (no-call)**: When the `findings` table contains a
   row with `evidence_ref` starting with `cyrius_no_call:`, the host's Cyrius
   caller could not resolve CYP2D6 for this sample (typically low coverage
   at the CYP2D6/CYP2D7 locus, structural variant interference, or a BAM
   SM-tag mismatch). The row is `clinical-actionable` with
   `clinical_escalation='confirm_with_provider'`. **You MUST NOT** present
   the user as a "Normal Metabolizer" or any other inferred phenotype on
   that basis — the call failed, the metaboliser status is unknown. Surface
   the indeterminate status and recommend the user confirm with their
   provider before any codeine, tramadol, oxycodone, tamoxifen, fluoxetine,
   or other CYP2D6-substrate medication decisions. The eight substrates are
   listed in the finding's `drugs` array for direct reference.
   ```

4. **System prompt contract test**: Add `test_system_prompt_teaches_cyp2d6_indeterminate_handling` to `test_agent_system_prompt_contract.py` asserting the new prose appears.

---

## Step 2.3 — REFACTOR

- Verify the resolver's summary text matches the system-prompt phrasing — drift here would confuse the agent.
- The `_resolve_cyrius_no_call` helper has a similar shape to `_resolve_clinvar`; consider whether they share enough structure to factor out a `_resolve_from_local_artifact` helper. Likely not — the input shapes (one DB lookup vs. one JSON read) are different enough that a shared helper would be premature.

---

## Verification

```bash
# Phase 2 new tests
cd packages/toolkit && uv run pytest \
  tests/integration/test_evidence_cyrius_no_call.py \
  tests/integration/test_cli_pipeline_cyp2d6_no_call.py::test_indeterminate_finding_reaches_findings_api \
  tests/invariants/test_agent_system_prompt_contract.py::test_system_prompt_teaches_cyp2d6_indeterminate_handling \
  -v

# Full toolkit regression
cd packages/toolkit && uv run pytest tests/ -q

# Plugin typecheck (no plugin changes expected; just confirm no drift)
cd packages/nemoclaw-plugin && npm run typecheck

# Type check
cd packages/toolkit && uv run mypy src/genomeclaw_toolkit/service/store.py src/genomeclaw_toolkit/schemas/evidence.py
```

---

## Completion Criteria

- [ ] `_SUPPORTED_EVIDENCE_KINDS` includes `cyrius_no_call`
- [ ] `EvidenceKind` Literal includes `cyrius_no_call`
- [ ] `_resolve_cyrius_no_call` returns a summary-class dict (no raw Cyrius output)
- [ ] `GET /v1/evidence/cyrius_no_call:<path>` returns 200 with the summary record
- [ ] `GET /v1/findings?genes=CYP2D6` returns the indeterminate row after a no-call run
- [ ] System prompt § 6 names the CYP2D6 indeterminate case with the "MUST NOT present as Normal Metabolizer" rule
- [ ] New contract test `test_system_prompt_teaches_cyp2d6_indeterminate_handling` passes
- [ ] Full toolkit suite passes (modulo the 4 pre-existing unrelated failures)
- [ ] `work-notes.md` updated with Phase 2 GREEN block + smoke result
- [ ] Phase 2 status in `development-plan.md` set to Complete
- [ ] Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke); smoke result pasted into `work-notes.md` (cheap synthetic-DB portion runs in this session; expensive real-data portion is project-owner manual gate before plan-closeout)

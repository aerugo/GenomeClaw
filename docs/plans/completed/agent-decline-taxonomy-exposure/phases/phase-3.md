# Phase 3: System-Prompt Clause + Integration Smoke

**Status**: Complete (synthetic smoke); real-data smoke pending project-owner
**Started**: 2026-05-25
**Completed**: 2026-05-25
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Amend § 6 of the agent system prompt to teach the agent that `calibration_status='decline'` is a binding, machine-readable signal that overrides its own reasoning about whether to present a PGS as a finding. Add a contract test that pins this new clause. Run the regression smoke per the meta-plan's cross-cutting requirement.

## Scope Boundaries

- **In scope**: `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` § 6 amendment; new contract test in `tests/invariants/test_agent_system_prompt_contract.py`; meta-plan regression smoke.
- **Out of scope**: Schema or service code changes (those landed in Phase 1/2); promotion of NEW INV-A004 into `INVARIANTS.md` (closeout step, after Phase 3 GREEN).

## Invariants Enforced in This Phase

- **INV-C001 v1.7**: the system prompt's PRS-decline pattern teaches the machine-readable decline-status rule binding the agent's behaviour. A new contract test (`test_system_prompt_teaches_machine_readable_decline_status`) asserts the prompt names `calibration_status`, the value `"decline"`, and the rule "do NOT present this row as a finding."

---

## Design

### Where to insert the new clause

§ 6 currently sequences (line numbers per HEAD):
1. Lifestyle vs clinical category framing (lines 250-257).
2. Hard-genes graceful decline (lines 259-263).
3. **PRS-decline pattern (INV-C001 v1.7)** (lines 265-275).
4. The `rationale` field discussion (line 277).
5. `_compute_status` polling discussion (line 279+).

The new clause goes **immediately under the "PRS-decline pattern" heading**, before the five named reasons (a)-(e). The rationale: the host's calibration classifier is the *first* gate; the agent's own (a)-(e) decline reasoning applies only when the host returned a CLEAN or WARNING row. Reversing this ordering would teach the agent to think about its own decline criteria before checking whether the host has already declined the row — which is precisely the bug this plan exists to fix.

### Exact insertion text

```markdown
**Read `calibration_status` first.** Every row returned by `genomeclaw_pgs_list`
and `genomeclaw_pgs_get` carries a `calibration_status` field with one of
`"clean"`, `"warning"`, `"decline"`, or `null`. If the value is `"decline"`,
the host's calibration classifier has already declined this PGS — surface the
`decline_reason` verbatim (one of five snake_case structural reasons; see
`DeclineReason` in the host's `_pgs_qc.py` for the canonical list) and do NOT
present this row as a finding under any framing. Your own decline reasoning
(a)-(e) below applies only when the host returned a `"clean"` or `"warning"`
row that you judge insufficient on policy grounds beyond the host's automated
classifier. A `null` `calibration_status` marks a pre-Phase-3a row that the
host wrote before the classifier shipped — treat these as `"warning"`
(uncalibrated) and apply your own (a)-(e) reasoning explicitly.
```

This text:
- Names `calibration_status` and its three string values + `null` so the prompt-content gate (the new contract test) can assert each appears.
- Names `decline_reason` and points at the canonical `DeclineReason` enum location.
- Teaches the binding rule: do NOT present a declined row as a finding.
- Resolves the `null`-status case (legacy rows) explicitly so the agent doesn't silently swallow them.

### New contract test

```python
def test_system_prompt_teaches_machine_readable_decline_status() -> None:
    """INV-C001 v1.7 + agent-decline-taxonomy-exposure: prompt teaches the
    machine-readable decline-status rule."""
    text = _read_prompt()
    # The field name + three string values + null state must all be present.
    assert "calibration_status" in text
    for value in ('"clean"', '"warning"', '"decline"'):
        assert value in text, (
            f"INV-C001 v1.7: prompt must enumerate calibration_status value {value}"
        )
    assert '"null"' in text or "null `calibration_status`" in text or "`null`" in text, (
        "INV-C001 v1.7: prompt must teach the null-status (legacy row) case"
    )
    assert "decline_reason" in text
    # The binding rule must be explicit, not implied.
    assert "do NOT present" in text or "do not present" in text.lower(), (
        "INV-C001 v1.7: prompt must explicitly forbid presenting a declined row "
        "as a finding"
    )
```

This goes in `tests/invariants/test_agent_system_prompt_contract.py` next to the existing `test_system_prompt_documents_prs_decline_pattern_with_five_named_reasons` (~line 278).

---

## TDD Steps

### Step 3.1 — RED: Write the failing contract test

Add `test_system_prompt_teaches_machine_readable_decline_status` to the contract test file. Run:

```bash
cd packages/toolkit && uv run pytest tests/invariants/test_agent_system_prompt_contract.py::test_system_prompt_teaches_machine_readable_decline_status -v
```

Expected: fails on the first `assert "calibration_status" in text` — the prompt does not yet mention the field.

### Step 3.2 — GREEN: Amend the system prompt

Insert the clause described above immediately under the "PRS-decline pattern (INV-C001 v1.7)" heading. Re-run the new contract test; expect PASS. Re-run the full `test_agent_system_prompt_contract.py` module to confirm no other contract test broke (the existing tests assert the five named reasons + the two-named-reasons rule; these are unchanged).

### Step 3.3 — REFACTOR

- Verify the new clause flows naturally with the surrounding paragraphs (the agent reads § 6 as English prose).
- Verify the `null`-status case is explicit (avoid silent swallowing).
- Run the full toolkit suite once more to catch cross-cutting drift.

### Step 3.4 — Regression smoke (per meta-plan cross-cutting requirement)

The meta-plan smoke command for this plan is:
```bash
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```
followed by:
```bash
curl -s http://127.0.0.1:8643/v1/pgs/computed/PGS000018 | jq '.calibration_status, .decline_reason'
```

In practice the smoke decomposes into:
- **Synthetic-DB smoke (cheap; runnable in this session)**: spin up the host FastAPI service against a fixture `variants.duckdb` seeded by `stamp_pgs_row` (the same pattern used in the Phase 1 integration test); curl `/v1/pgs/computed/{pgs_id}` and confirm `calibration_status` + `decline_reason` appear in the JSON response. This validates the read path end-to-end.
- **Real-data smoke (expensive; project-owner manual)**: rerun the full `bin/genomeclaw-prs-smoke` against the owner's actual CRAM. This re-validates the full PRS compute path with the new schema projection, taking 4-6 h wall-clock. Document the smoke result in `work-notes.md` once the owner has run it. The plan moves to `docs/plans/completed/` only after the real-data smoke is recorded.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY | Insert machine-readable decline-status clause under § 6 PRS-decline heading |
| `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` | MODIFY | Add `test_system_prompt_teaches_machine_readable_decline_status` |

---

## Verification

```bash
# New contract test (RED before, GREEN after the prompt amendment)
cd /Users/hugi/GitRepos/GenomeClaw/packages/toolkit
uv run pytest tests/invariants/test_agent_system_prompt_contract.py::test_system_prompt_teaches_machine_readable_decline_status -v

# Full prompt-contract module
uv run pytest tests/invariants/test_agent_system_prompt_contract.py -v

# Full toolkit suite — confirm no regression
uv run pytest tests/ -q
```

For the synthetic-DB smoke, the existing integration test `test_pgs_get_response_excludes_bulk_fields_invP002` already exercises `/v1/pgs/computed/{pgs_id}` end-to-end with the new field set (the Phase 1 widening already passes through this test). No additional smoke harness needed for the cheap path.

---

## Completion Criteria

- [ ] `test_system_prompt_teaches_machine_readable_decline_status` is added, RED before the amendment, GREEN after.
- [ ] Full `test_agent_system_prompt_contract.py` module passes (existing contract tests still green).
- [ ] Full toolkit test suite passes (modulo the 4 pre-existing unrelated failures documented in Phase 1 work-notes).
- [ ] The synthetic-DB smoke (Phase 1 integration test) confirms `calibration_status` + `decline_reason` flow through `/v1/pgs/computed/{pgs_id}` JSON.
- [ ] Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`. The cheap synthetic-DB portion runs in this session; the expensive real-data portion is documented as a project-owner manual gate before plan-closeout.
- [ ] `work-notes.md` updated with the RED step output, the prompt-amendment diff summary, and the smoke result.
- [ ] Phase 3 status updated to "Complete" in `development-plan.md`.
- [ ] **Closeout** (post-Phase 3): NEW INV-A004 promoted into `docs/reference/INVARIANTS.md`; the meta-plan progress table updated; the plan directory moved from `active/` to `completed/`.

# Phase 2 — Axis A validation fix

**Status**: **Complete**
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

## Goal

Lower the `PgsComputeRequest.rationale` minLength from 50 to 10 so agent-typical short rationales aren't 422'd. Preserve INV-A003's non-empty-rationale floor.

## Invariants enforced in this phase

- **INV-A003** — rationale stays required + non-empty (the rule is "alternatives considered + why this one", not "exactly 50 chars"). The 50-char threshold was defense-in-depth; relaxing to 10 keeps the meaningful floor.

## TDD Steps

### Step 2.1 — RED → GREEN: lower the host service threshold

Phase 1's `test_pgs_compute_accepts_agent_short_rationale` is the RED-on-current-main test. The GREEN fix:

`packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py`:

```python
class PgsComputeRequest(BaseModel):
    ...
    rationale: str = Field(min_length=10)  # was: min_length=50
    ...
```

Verify Phase 1's test now passes. The existing `test_pgs_compute_request_rejects_short_rationale` (rationale="" → 422) must continue to pass — `min_length=10` still rejects empty strings.

### Step 2.2 — Pin the new boundary

Add to `test_pgs_compute_request_validation.py`:

```python
def test_pgs_compute_9_char_rationale_rejected_post_fix(tmp_path):
    """9 chars below the new threshold → 422. Pins the new boundary."""
    # ...

def test_pgs_compute_10_char_rationale_accepted_post_fix(tmp_path):
    """10 chars at the new threshold → 202. Pins the new boundary."""
    # ...
```

Update `test_pgs_compute_42_char_rationale_currently_rejected_documents_threshold` — the 49-char test currently RED-pins the OLD 50-char threshold; after the fix, it would change behavior. Rename to `test_pgs_compute_49_char_rationale_accepted_post_fix` + flip the assertion to 202.

### Step 2.3 — Plugin-side TypeBox

The plugin's TypeBox at [packages/nemoclaw-plugin/src/index.ts:265](../../../packages/nemoclaw-plugin/src/index.ts#L265) has `rationale: Type.String({ minLength: 50 })` mirroring the Pydantic gate (defense-in-depth). Lower it to `minLength: 10` to match.

Re-build the plugin: `cd packages/nemoclaw-plugin && npm run build && npm test` — expect 21/21 vitest pass.

The sandbox image needs rebuilding to pick up the new plugin code; Phase 6's E2E test runs against the rebuilt sandbox image.

### Step 2.4 — Agent system prompt note (optional)

`packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — find the `genomeclaw_pgs_compute` tool description block + add a sentence: *"Aim for ≥50 chars of rationale (the canonical INV-A003 'alternatives considered + why this one' shape); the host service accepts ≥10 chars but the longer form is what makes the result row auditable."*

Optional — the prompt change is encouragement, not enforcement.

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | MODIFY | Lower `rationale.min_length` 50 → 10 |
| `packages/toolkit/tests/integration/test_pgs_compute_request_validation.py` | MODIFY | Pin new boundary; flip the 49-char test's expected status |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | Lower TypeBox `minLength: 50 → 10` |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY (optional) | Encourage ≥50 char rationale without enforcing it |

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_pgs_compute_request_validation.py -v
# Expect: all PASS (Phase 1 RED test flipped + new boundary tests landed).

uv run pytest tests/unit tests/integration tests/invariants --no-header -q
# Expect: no regression.

# Plugin rebuild + tests
cd ../nemoclaw-plugin
npm run build  # TS strict-mode build must pass
npm test       # 21/21 vitest pass

# ruff
cd ../toolkit
uv run ruff check src/genomeclaw_toolkit/schemas/pgs.py \
                  tests/integration/test_pgs_compute_request_validation.py
```

## Completion Criteria

- [ ] Phase 1's RED test (`test_pgs_compute_accepts_agent_short_rationale`) turns GREEN.
- [ ] Existing `test_pgs_compute_request_rejects_short_rationale` (rationale="") stays GREEN.
- [ ] New boundary tests at 9 chars (rejected) + 10 chars (accepted) added.
- [ ] Plugin TypeBox + Pydantic threshold in sync (both at 10).
- [ ] Plugin TS strict-mode build passes; 21/21 vitest green.
- [ ] Full toolkit suite remains green.
- [ ] ruff clean on touched files.

## Next

[Phase 3 — Worker skeleton + queue management](phase-3.md).

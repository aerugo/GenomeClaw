# Phase 2: Extend Host-Service Responses with Rich Diagnostic Data

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Implement the **high-value** Phase 1 audit recommendations: extend each affected host-service response model with the diagnostic detail fields the agent needs to synthesize a meaningful user-facing answer. Additive only — existing fields stay, new fields surface for both success and failure paths as Phase 1 documented.

## Scope Boundaries

- **In scope**:
  - High-value tools per Phase 1 audit (likely: `pgs_compute`, `pgs_compute_status`, possibly `gene`).
  - Pydantic response-model field additions.
  - Handler updates to populate the new fields.
  - Unit + integration tests for the new fields.
- **Out of scope**:
  - Plugin-side type extensions (Phase 3).
  - Medium-value extensions if scope grows — defer to follow-up plan.
  - Prompt edits (Phase 4).

## Invariants Enforced in This Phase

- **NEW INV-D010** (proposed; promoted at Phase 3 review): host service forwards full diagnostic context to the plugin. Phase 2 lays the data foundation; Phase 3's INV-A006 discovery test may grow to enforce the plugin doesn't drop the data.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests for Each Extended Response

For each high-value tool from Phase 1:

1. **Failure-path richness test**: probe the host endpoint with a fixture that triggers the documented failure path; assert the response carries the new diagnostic fields (e.g., `diagnostic_trace.stage`, `diagnostic_trace.command`, `diagnostic_trace.partial_log` for `pgs_compute`).
2. **Success-path metadata test**: probe a happy-path response; assert the new metadata fields are populated.
3. **Schema test**: assert the Pydantic model accepts + validates the new fields with sensible types.

Run the new tests RED before any handler edit. Confirm each fails with "field not present" / "schema rejects unknown field" / etc.

### Step 2.2 — GREEN: Extend Response Models + Populate Fields

For each high-value tool:

1. Extend the Pydantic response model with the new optional fields (additive — `field: Type | None = None` to preserve backward compat).
2. Update the handler to construct + populate the new fields. For failure paths, this typically means capturing context BEFORE the failure propagates (nextflow command, current stage, partial log).
3. Re-run the tests → green.

### Step 2.3 — REFACTOR

- Verify no existing tests broke.
- Tighten field types where the audit allowed flexibility.
- Document the new fields in the response-model docstring (operator-readable).
- Confirm OpenAPI / inline schema still validates cleanly.

---

## Implementation Details

### Diagnostic-Trace Field Shape (Proposal)

A reusable shape for failure-path diagnostic data:

```python
class ToolDiagnosticTrace(BaseModel):
    """Rich diagnostic context for a failed tool invocation.

    Surfaced through the host-service response so the plugin's failure
    envelope carries enough for the agent to give the user a real
    explanation rather than just a status code.
    """
    stage: str  # human-readable name of the step that failed
    command: str | None = None  # full command executed, if applicable
    partial_log: str | None = None  # tail of stdout/stderr (truncate to ~2KB)
    upstream_cause: str | None = None  # higher-level cause (e.g., "scorefile_missing")
    related_paths: list[str] = []  # files mentioned in the failure context
```

This is a sketch — Phase 1's audit may surface tool-specific variations. Keep the field set small + composable.

### Success-Path Metadata Shape (Per-Tool)

Each tool has its own metadata shape. Examples:

```python
class PgsComputeMetadata(BaseModel):
    match_rate: float | None = None
    effective_rate: float | None = None
    matched_variants: int | None = None
    ancestry_label: str | None = None
    calibration_status: Literal["clean", "warning", "decline"] | None = None
```

Phase 1 specifies the per-tool field set.

### Edge Cases

- **Empty diagnostic** (failure with no captured context): `diagnostic_trace: null` is acceptable; the agent treats it as "no rich context available, fall back to the high-level error."
- **Large partial_log**: truncate aggressively (~2KB tail). The agent doesn't need the full log; it needs enough context to summarize what happened.
- **Secrets in trace**: ensure no API keys / paths-with-secrets land in `partial_log`. Redact at capture time. (Coordinate with `INV-P003`.)

### Privacy / Egress Notes

- Diagnostic data crosses the host → plugin → agent boundary. The agent is already a configured-egress destination (`INV-P001`). The new fields contain operational data (commands, paths, error codes) — not raw genomic data. Verify nothing sensitive leaks via `partial_log`.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/<routes>.py` (per Phase 1) | MODIFY | Extend response models + populate new fields in handlers. |
| `packages/toolkit/tests/service/<test>.py` | MODIFY/CREATE | Unit + integration tests for new fields. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/service/ -xvs
uv run pytest tests/integration/test_service_*.py -xvs
uv run ruff check src tests
uv run mypy src
```

For the agent integration smoke (optional, before Phase 4):

```bash
# Probe the host endpoint directly + inspect the richer response.
curl -sf http://127.0.0.1:8645/v1/pgs/compute/<task_id> | python3 -m json.tool
# Confirm `diagnostic_trace` field is populated for a failed task.
```

---

## Completion Criteria

- [ ] Each high-value tool from Phase 1 has its proposed extensions landed.
- [ ] New tests pass (RED → GREEN in commit history).
- [ ] All existing service + integration tests still pass.
- [ ] Static checks (ruff, mypy) clean.
- [ ] `partial_log` redaction confirmed (no secrets in output).
- [ ] `work-notes.md` updated.
- [ ] Phase 2 row in `development-plan.md` progress table set to **Complete**.

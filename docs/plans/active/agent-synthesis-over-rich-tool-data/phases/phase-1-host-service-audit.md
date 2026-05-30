# Phase 1 Audit — Host-Service Tool-Result Shapes

**Date**: 2026-05-28
**Audit method**: read [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) for tool registrations + endpoints, [packages/toolkit/src/genomeclaw_toolkit/service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) for route handlers, [packages/toolkit/src/genomeclaw_toolkit/schemas/](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/) for response models, [packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py) for the task orchestrator.

## Headline

The architectural pattern across all 9 plugin tools is the same: Pydantic response models with `extra="forbid"`, minimal fields, no diagnostic context surfaced under failure. **Per `INV-P002` "minimal-sufficient JSON" the response models are deliberately narrow** — fewer fields = less leak surface. This is correct privacy posture, but it leaves a synthesis gap: when a tool fails the agent has only a short error code to work with, and even on success there's no command/trace/intermediate metadata for the agent to surface to the user.

The **single high-value gap** is the `genomeclaw_pgs_compute` + `genomeclaw_pgs_compute_status` failure path. Other tools either don't have the failure mode (read-only DuckDB lookups; failure means "no active run" or HTTP 5xx, which is already structurally surfaced) or have well-contained envelopes already (the GeneResponse `caveat` field is good).

## Per-tool audit

### 1. `genomeclaw_status` → `GET /v1/health`

**Response model**: `HealthResponse` (3 fields: `schema_version`, `current_run_id`, `sample_id`) + `HealthErrorResponse` (2 fields: `status` enum, `detail` string).

**Current shape — success**: `{status: "ok", schema_version, current_run_id, sample_id}`. Enough for the agent.

**Current shape — failure (503)**: `{status: "no_active_run" | "schema_version_mismatch", detail}`. The `detail` already contains a recovery command (e.g., *"run `genomeclaw pipeline run` first"*). Reasonably rich for what it needs to say.

**Gap**: **None** (low priority). The 503 detail string is already operator-actionable + agent-synthesizable.

**Phase 2 action**: **no change.**

---

### 2. `genomeclaw_findings` → `GET /v1/findings`

**Response model**: `FindingsListResponse` (rows + pagination).

**Current shape**: list of `Finding` objects with category, gene, drugs, evidence ref, etc. Per-row data is structured + complete.

**Gap**: **Low**. The list endpoint returns row data; failures are "no active run" (handled at `_require_active_run`) or HTTP errors from the DuckDB layer (which already throw informatively).

**Phase 2 action**: **no change.**

---

### 3. `genomeclaw_variant` → `GET /v1/variants/{key}`

**Response model**: `VariantDetail` (~20 fields: identity + gene context + clinvar + dbsnp + VEP + loftee + alphamissense + LOEUF).

**Current shape**: rich already — every clinically-useful field per variant. `mane_select_transcript`, `mane_plus_clinical_transcript`, `transcript_discordant`, `loftee_filter`, `alphamissense_class`, etc.

**Gap**: **None**. This is the canonical example of "rich structured data the agent reasons over."

**Phase 2 action**: **no change.**

---

### 4. `genomeclaw_evidence` → `GET /v1/evidence/{ref}`

**Response model**: evidence-specific structured data (ClinVar / Cyrius / etc.) keyed by ref.

**Current shape**: per-kind structured fields. ClinVar entries include review status + variant ID + classification.

**Gap**: **Low**. The evidence layer's job is reference look-up; the response IS the reference data.

**Phase 2 action**: **no change.**

---

### 5. `genomeclaw_gene` → `GET /v1/gene/{symbol}`

**Response model**: `GeneResponse` — `gene`, `n_variants_in_gene`, `mean_depth`, `low_coverage_exons`, `schema_version`, `region_class`, `caveat`.

**Current shape**: rich already. The `caveat` field carries verbatim per-region-class guidance (PMS2/SMN1/etc. difficulty markers). `region_class` discriminator + `caveat` text together give the agent everything to synthesize a careful answer.

**Gap**: **None**. This is the second canonical example of well-shaped rich data — the `INV-D009` coverage-panel-v2 work already addressed it.

**Phase 2 action**: **no change.**

---

### 6. `genomeclaw_pgs_list` → `GET /v1/pgs/computed`

**Response model**: `PgsListResponse` (rows of `PgsListRow` + total count).

**Current shape — success**: each `PgsListRow` has `pgs_id`, `trait_label`, `percentile_in_user_ancestry`, `calibration_warning`, `calibration_status`, `decline_reason`, `superseded_by`. The decline taxonomy + calibration status give the agent the structured signal needed for plain-language synthesis ("I see X computed, but this one has a `decline_reason: ancestry_calibration_uncertain` — meaning the calibration confidence isn't strong enough for me to report a percentile").

**Gap**: **None**. The list view's slimness is deliberate (`agent_choice_rationale` omitted to keep the list small); the agent fetches `genomeclaw_pgs_get` for the full body.

**Phase 2 action**: **no change.**

---

### 7. `genomeclaw_pgs_get` → `GET /v1/pgs/computed/{pgs_id}`

**Response model**: `PgsRowResponse` — 12 fields including `agent_choice_rationale`, `requested_for_question`, calibration status, decline reason, percentile, raw score, source PGS, study population.

**Current shape**: rich. INV-A003-compliant; INV-A004-compliant.

**Gap**: **None.**

**Phase 2 action**: **no change.**

---

### 8. `genomeclaw_pgs_compute` → `POST /v1/pgs/compute`

**Response model**: `PgsComputeTaskResponse` — **4 fields**: `task_id`, `pgs_id`, `status` (enum: queued|running|done|failed), `error` (str | null).

**Current shape — success (queued)**: 4 fields. Sufficient for "compute kicked off, poll the status endpoint."

**Current shape — failure**: same 4 fields with `status="failed"` and `error="<code>"`. **The `error` field is a short token** — e.g., `"prs_compute_config_missing"`, `"scorefile_missing"`, `"worker_restart:stale_running"`, `"compute_path_disabled"`.

**🎯 GAP — HIGH VALUE 🎯**:

When `genomeclaw_pgs_compute` fails, the agent gets only the short error code. There's NO surface for:
- The pgsc_calc / nextflow command that was about to run (or did run partially).
- The stage at which the worker stopped (config-load? scorefile-staging? pgsc_calc-invocation? match-rate-parse?).
- Any partial log output (nextflow trace, stderr tail).
- The upstream cause (e.g., for `scorefile_missing`: WHICH scorefile is missing; what's the path the worker expected).
- The fix (e.g., for `scorefile_missing`: the operator can run `genomeclaw refs fetch <PGS-ID>`).

**This is the AC8 muscle-question failure scenario.** With the host service down, the agent sees `status="failed", error="<code>"` and has nothing rich to translate into a user-facing explanation.

**Phase 2 action**: **EXTEND `PgsComputeTaskResponse`** with optional fields:

```python
class ToolDiagnosticTrace(BaseModel):
    """Rich diagnostic context for a failed/in-flight tool invocation."""
    model_config = ConfigDict(extra="forbid")
    stage: str | None = None                      # e.g., "config_load", "scorefile_staging", "pgsc_calc_invocation"
    upstream_cause: str | None = None             # higher-level cause code (mirrors error but more verbose)
    suggested_fix: str | None = None              # user-actionable next step (e.g., "run `genomeclaw refs fetch PGS000018`")
    related_paths: list[str] = []                 # files mentioned in the failure context
    partial_log_tail: str | None = None           # last ~2KB of worker stderr/stdout if available


class PgsComputeTaskResponse(BaseModel):
    """Response body for `POST /v1/pgs/compute` + `GET /v1/pgs/compute/{task_id}`."""
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1)
    pgs_id: str = Field(min_length=1)
    status: PgsComputeStatus
    error: str | None = None
    diagnostic: ToolDiagnosticTrace | None = None  # NEW — populated on `status="failed"` paths
```

**Priority**: **High**. This is the AC8 scenario's load-bearing gap.

---

### 9. `genomeclaw_pgs_compute_status` → `GET /v1/pgs/compute/{task_id}`

Same model as `genomeclaw_pgs_compute` (both use `PgsComputeTaskResponse`).

**Phase 2 action**: same extension — `diagnostic` field surfaces on failed status polls.

**Priority**: **High** (same scenario; the polling endpoint is where the agent sees long-running failures).

---

## Summary

| Tool | Current shape | Gap | Phase 2 action |
|---|---|---|---|
| `genomeclaw_status` | rich (3 success / 2 error) | none | no change |
| `genomeclaw_findings` | rich | none | no change |
| `genomeclaw_variant` | rich (~20 fields) | none | no change |
| `genomeclaw_evidence` | rich (per-kind) | none | no change |
| `genomeclaw_gene` | rich (region_class + caveat) | none | no change |
| `genomeclaw_pgs_list` | rich (calibration_status + decline_reason) | none | no change |
| `genomeclaw_pgs_get` | rich (12 fields incl. provenance) | none | no change |
| `genomeclaw_pgs_compute` | **MINIMAL on failure** | **🎯 HIGH** | extend with `ToolDiagnosticTrace` |
| `genomeclaw_pgs_compute_status` | **MINIMAL on failure** | **🎯 HIGH** | extend with `ToolDiagnosticTrace` |

**Phase 2 scope is narrow**: one new Pydantic model (`ToolDiagnosticTrace`) + one field added to `PgsComputeTaskResponse` + handler-side population logic in the orchestrator's failure paths.

Other tools' responses are already rich enough — the `INV-P002` minimal-sufficient discipline holds; the gap is specifically at the async-compute failure surface where the worker holds context the response model doesn't expose.

## Observations relevant to later phases

- **Phase 3 plugin envelope extension**: only `wrapHostResponse`'s `host_failure` arm needs the `diagnostic` field (mirroring `ToolDiagnosticTrace`). The other three envelope arms (`placeholder_rejected`, `network_error`, `http_error`) don't have host-side diagnostic context to forward.
- **Phase 4 prompt rewrite**: the worked examples should distinguish *"sparse failure"* (e.g., network error — agent says "I couldn't reach the host service this turn") from *"rich failure with diagnostic"* (e.g., compute failed with `stage="scorefile_staging"`, `suggested_fix=<...>` — agent says "the scorefile wasn't pre-staged; run X to fix").
- **Phase 5 judge prompt**: the judge should accept replies that omit `error_type` *enum values* when the failure is sparse, and require richer synthesis when the diagnostic IS populated.

## Decision: INV-D010 promotion

Given Phase 2 affects only 2 tools (both compute-related), the "Tool-Result Richness" discipline is **scoped, not project-wide**. Defer `INV-D010` promotion. If future plans add diagnostic-trace fields to other tools (e.g., a future `genomeclaw_force_genotype` async wrapper), revisit then.

## Phase 2 RED test plan (preview)

For Phase 2's TDD step:

1. `test_PgsComputeTaskResponse_accepts_optional_diagnostic_field` — Pydantic model accepts + serializes the new `diagnostic: ToolDiagnosticTrace | None = None` field.
2. `test_orchestrator_populates_diagnostic_on_scorefile_missing_failure` — when the worker fails with `error="scorefile_missing"`, the task row gets `diagnostic={stage: "scorefile_staging", upstream_cause: "scorefile_missing", suggested_fix: "run `genomeclaw refs fetch <pgs_id>`", related_paths: [<expected scorefile path>]}`.
3. `test_orchestrator_populates_diagnostic_on_prs_compute_config_missing` — same shape, different stage (`config_load`).
4. `test_orchestrator_populates_diagnostic_on_pgsc_calc_failure` — populates `partial_log_tail` (truncated to ~2KB).
5. `test_get_compute_status_returns_diagnostic_field` — integration: HTTP GET `/v1/pgs/compute/{task_id}` for a failed task returns the diagnostic field in the body.

Implementation strategy: pick the 2-3 most common failure modes the orchestrator can already classify (config_load, scorefile_staging, compute_path_disabled) and add the per-mode diagnostic population. Other modes default to `diagnostic=None` (acceptable).

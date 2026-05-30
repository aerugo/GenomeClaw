"""Pydantic models for the agent-driven PRS layer (Phase 6 Slice E v2; Q8 v1.6).

Five models cover the four `/v1/pgs/*` endpoints + the agent-triggered compute
request body. All models are strict (`extra="forbid"`) so a future widening
that adds e.g. the raw PGS variant list to a response shape surfaces at
construction time per `INV-P002`.

Architectural choices (per [docs/reports/agent-driven-prs-computation.md](
../../../../../docs/reports/agent-driven-prs-computation.md)):

- **PGS Catalog ID is the canonical key**, not curator-named trait. The
  table + every response is keyed by `pgs_id` (e.g. `PGS000018`).
- **`agent_choice_rationale` + `requested_for_question` are first-class
  per-row provenance** under `INV-A003`. The compute-request body requires
  them; the response body returns them; the wrapper stamps them into the
  `pgs_scores` row.
- **`rationale` must be non-empty** at the request layer (≥ 10 chars) —
  defence-in-depth with the plugin's TypeBox `minLength: 10` gate. The
  INV-A003 rule is "alternatives considered + why this one"; the 10-char
  floor stops trivially-empty rationales without rejecting agent-typical
  brevity. The 50-char threshold the earlier slice enforced rejected
  agent-generated rationales under reasoning pressure (2026-05-23 AMD-
  question incident); the agent system prompt continues to encourage
  ≥50-char "alternatives considered" framing without the host service
  enforcing it as a 422 boundary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, DeclineReason

# Status enum for the compute-task lifecycle. Per the v2 slice plan:
# - `queued`: enqueued, orchestrator hasn't picked it up yet.
# - `running`: orchestrator is in-flight with this compute.
# - `done`: compute finished; result is fetchable via `/v1/pgs/computed/{pgs_id}`.
# - `failed`: compute aborted; `error` field on the response carries the message.
#   One specific failure-mode is `compute_path_disabled` (kill-switch on).
PgsComputeStatus = Literal["queued", "running", "done", "failed"]


class PgsRowResponse(BaseModel):
    """Single PRS row returned from `GET /v1/pgs/computed/{pgs_id}`.

    Carries the 6 domain fields + 2 `INV-A003` provenance fields + 1 audit-trail
    field + the `source_pgs_id` echo (kept for output-shape consistency with
    the v1.5 `/v1/pgs/{trait}` response, since downstream agents may have
    been written against that shape — both `pgs_id` and `source_pgs_id` are
    identical PGS Catalog IDs).
    """

    model_config = ConfigDict(extra="forbid")

    pgs_id: str = Field(min_length=1)
    trait_label: str = Field(min_length=1)
    percentile_in_user_ancestry: float | None
    raw_score: float | None
    source_pgs_id: str = Field(min_length=1)
    study_population: str = Field(min_length=1)
    calibration_warning: str | None
    calibration_status: CalibrationStatus | None
    """Per `INV-C001` v1.7 + `INV-A004`: machine-readable classifier outcome.
    `None` on pre-Phase-3a rows that predate the calibration classifier."""

    decline_reason: DeclineReason | None
    """Per `INV-C001` v1.7 + `INV-A004`: structural decline reason when
    `calibration_status == "decline"`; `None` otherwise."""

    agent_choice_rationale: str = Field(min_length=1)
    """Per `INV-A003`: agent's reasoning for picking this PGS + alternatives considered."""

    requested_for_question: str = Field(min_length=1)
    """Per `INV-A003`: verbatim user question that triggered the compute."""

    superseded_by: str | None
    """PGS Catalog ID of the row that replaced this one when a recomputed PGS lands;
    NULL for current rows. Mirrors `INV-A001`'s "prior note stays on disk" trail."""


class PgsListRow(BaseModel):
    """Slim per-row shape returned in the `/v1/pgs/computed` list.

    The full `agent_choice_rationale` is omitted from the list view to keep the
    payload small; the agent calls `genomeclaw_pgs_get` for the full body when
    it wants to surface the rationale to the user.
    """

    model_config = ConfigDict(extra="forbid")

    pgs_id: str = Field(min_length=1)
    trait_label: str = Field(min_length=1)
    percentile_in_user_ancestry: float | None
    calibration_warning: str | None
    calibration_status: CalibrationStatus | None
    decline_reason: DeclineReason | None
    superseded_by: str | None


class PgsListResponse(BaseModel):
    """Top-level body for `GET /v1/pgs/computed`."""

    model_config = ConfigDict(extra="forbid")

    rows: list[PgsListRow]
    total: int


class PgsComputeRequest(BaseModel):
    """Request body for `POST /v1/pgs/compute`.

    The 10-char minimum on `rationale` stops trivially-empty rationales
    while accepting agent-typical brevity (2026-05-23 AMD-question incident:
    the earlier 50-char gate rejected `"Canonical AMD PRS; smoker-relevant trait."`
    at 41 chars). The INV-A003 rule is "alternatives considered + why this one";
    the agent system prompt continues to encourage that framing without the
    host service enforcing a specific char threshold.
    """

    model_config = ConfigDict(extra="forbid")

    pgs_id: str = Field(min_length=1)
    trait_label: str = Field(min_length=1)
    rationale: str = Field(min_length=10)
    requested_for_question: str = Field(min_length=1)


class ToolDiagnosticTrace(BaseModel):
    """Rich diagnostic context for a failed (or in-flight) tool invocation.

    Phase 2 of agent-synthesis-over-rich-tool-data — extends the agent's
    visibility into compute-path failures so it can give the user a real
    explanation + actionable next step, not just a short error code.

    The diagnostic is derived at response-build time from the persisted
    structured error code (see
    :func:`genomeclaw_toolkit.service.pgs_compute_orchestrator.derive_diagnostic_from_error_code`).
    No SQLite schema migration required — backward-compatible with rows
    written before the diagnostic existed.

    All fields are optional. The worker may not have captured every facet
    of every failure mode; the agent treats absent fields as "no additional
    context available" and is expected to synthesize honestly from what's
    present, not invent missing detail.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str | None = None
    """Pipeline stage at which the failure occurred. Examples: ``config_load``,
    ``scorefile_staging``, ``pgsc_calc_invocation``, ``match_rate_parse``,
    ``calibration_check``, ``compute_gate``, ``worker_loop``,
    ``docker_out_of_docker_setup``."""

    upstream_cause: str | None = None
    """The higher-level cause class. Mirrors the structured-error code prefix
    (e.g., ``"scorefile_missing"``, ``"prs_compute_config_missing"``,
    ``"pgsc_calc_failed"``) so the agent can branch reasoning on the class
    without parsing the full error string."""

    suggested_fix: str | None = None
    """User-actionable next step in plain language. For ``scorefile_missing``:
    ``"run `genomeclaw refs fetch --source pgs_scorefile --pgs-id <pgs_id>`"``.
    None for unknown errors (the agent acknowledges honestly rather than
    inventing a fix)."""

    related_paths: list[str] = []
    """Filesystem paths or PGS IDs mentioned in the failure context.
    Lets the agent name specific artifacts the user can inspect."""

    partial_log_tail: str | None = None
    """Last ~2 KB of worker stderr / stdout if the worker captured it.
    Currently sparse; reserved for future enrichment without a schema change."""


class PgsComputeTaskResponse(BaseModel):
    """Response body for `POST /v1/pgs/compute` + `GET /v1/pgs/compute/{task_id}`.

    Phase 2 (2026-05-28) extends this with the optional ``diagnostic`` field
    populated on ``status="failed"`` paths. The derivation is pure-functional
    over the persisted ``error`` code (see
    :func:`derive_diagnostic_from_error_code` in the orchestrator module).
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    pgs_id: str = Field(min_length=1)
    status: PgsComputeStatus
    error: str | None = None
    diagnostic: ToolDiagnosticTrace | None = None
    """Rich failure context for the agent. Populated on ``status="failed"``;
    None for queued / running / done."""


class PgsErrorResponse(BaseModel):
    """`/v1/pgs/*` 404 / 422 body."""

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = [
    "PgsComputeRequest",
    "PgsComputeStatus",
    "PgsComputeTaskResponse",
    "PgsErrorResponse",
    "PgsListResponse",
    "PgsListRow",
    "PgsRowResponse",
    "ToolDiagnosticTrace",
]

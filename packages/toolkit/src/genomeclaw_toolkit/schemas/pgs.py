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
- **`rationale` must be ≥ 50 chars** at the request layer — defence-in-depth
  with the plugin's TypeBox `minLength: 50` gate. Together they enforce the
  "alternatives considered + why this one" contract; an agent that supplies
  a one-word rationale gets rejected before any compute starts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    superseded_by: str | None


class PgsListResponse(BaseModel):
    """Top-level body for `GET /v1/pgs/computed`."""

    model_config = ConfigDict(extra="forbid")

    rows: list[PgsListRow]
    total: int


class PgsComputeRequest(BaseModel):
    """Request body for `POST /v1/pgs/compute`.

    The 50-char minimum on `rationale` forces the agent to write more than a
    one-word answer + enforces the `INV-A003` "alternatives considered" contract
    at the host-service layer (defence-in-depth with the plugin's TypeBox
    `minLength: 50`).
    """

    model_config = ConfigDict(extra="forbid")

    pgs_id: str = Field(min_length=1)
    trait_label: str = Field(min_length=1)
    rationale: str = Field(min_length=50)
    requested_for_question: str = Field(min_length=1)


class PgsComputeTaskResponse(BaseModel):
    """Response body for `POST /v1/pgs/compute` + `GET /v1/pgs/compute/{task_id}`."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    pgs_id: str = Field(min_length=1)
    status: PgsComputeStatus
    error: str | None = None


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
]

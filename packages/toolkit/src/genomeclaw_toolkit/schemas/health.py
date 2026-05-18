"""Pydantic response model for ``/v1/health``.

Phase 5 Slice A — the smallest read-only response surface the host
service exposes. The plugin's ``genomeclaw_status`` tool consumes this
to advertise the active run + schema version to the agent.

`INV-P002`: this response is the canonical example of "minimal-sufficient
JSON". Three fields plus a status enum — enough for the agent to know
"there is an active run, and it's at the schema version I understand"
without leaking host paths, full manifest blobs, or provenance trails.
A future regression that "helpfully" widens the response to ease
debugging would surface in
``test_invP002_health_response_excludes_bulk_or_path_fields``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """``/v1/health`` happy-path payload.

    Status is always ``"ok"`` for this model; degraded states (no active
    run, schema-version mismatch) surface as 503 with a separate
    :class:`HealthErrorResponse` body.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    schema_version: str
    current_run_id: str
    sample_id: str


class HealthErrorResponse(BaseModel):
    r"""``/v1/health`` 503 payload — degraded service state.

    Two states are represented: ``"no_active_run"`` (CURRENT symlink
    absent — fresh derived root or eject mid-flight) and
    ``"schema_version_mismatch"`` (the manifest's schema_version isn't
    one this build of the toolkit can serve).

    The ``detail`` field carries the human-readable next action — e.g.,
    ``"run \`genomeclaw pipeline run\` first"``. Tests assert the
    recovery command appears in the message.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["no_active_run", "schema_version_mismatch"]
    detail: str


__all__ = ["HealthErrorResponse", "HealthResponse"]

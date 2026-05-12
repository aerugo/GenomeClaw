"""Pydantic model for ``provenance.json``.

Every pipeline subcommand that mutates the derived store appends a step
to this trail. Phase 2 produces three steps: ``ingest``,
``bcftools-stats``, ``mosdepth-coverage``. Subsequent phases append
``normalize`` (Phase 3), ``annotate`` (Phase 4), ``cyp2d6-call`` (Phase
6), ``pgs-compute`` (Phase 6).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StepArtifact(BaseModel):
    """An input or output of a pipeline step. Path + SHA256 identity."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Step(BaseModel):
    """One pipeline step's append-only entry in ``provenance.json``."""

    model_config = ConfigDict(extra="forbid")

    step: str
    """Short identifier — ``ingest``, ``bcftools-stats``, ``mosdepth-coverage``,
    ``normalize``, ``annotate``, ``cyp2d6-call``, ``pgs-compute``."""

    tool: str
    tool_version: str
    started_at: datetime
    completed_at: datetime
    inputs: list[StepArtifact] = Field(min_length=1)
    outputs: list[StepArtifact] = Field(default_factory=list)
    params: dict[str, object] = Field(default_factory=dict)


class Provenance(BaseModel):
    """Top-level model for ``provenance.json``."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    schema_version: str
    steps: list[Step] = Field(default_factory=list)


__all__ = ["Provenance", "Step", "StepArtifact"]

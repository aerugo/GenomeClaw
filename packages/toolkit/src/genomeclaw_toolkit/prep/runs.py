"""Derived-run introspection — public helpers for the ``runs`` CLI group.

Two surfaces:

* :func:`list_derived_runs` returns a typed summary of every run dir
  under ``derived/`` (sample-id, started-at, pipeline-stage
  classification). Backed by the same logic
  :func:`genomeclaw_toolkit.prep.doctor.doctor` uses for its derived-runs
  block — exposed here so ``runs list`` can read it without spinning up
  the full doctor.
* :func:`read_run_detail` returns the manifest + provenance trail for
  a single run. Used by ``runs show`` to render per-step provenance.

Both functions are read-only (`INV-D001`): they touch ``manifest.json``
+ ``provenance.json`` inside each run dir, never raw / reference data.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path

RunStage = Literal["ingested", "normalized", "annotated", "materialized", "unknown"]


# Same precedence as ``doctor._classify_run_stage`` — kept in sync.
# The duplication is small + the alternative (importing a private
# name from ``doctor.py``) would couple the surfaces. Promote to a
# shared constants module if a third caller appears.
_STEP_PRECEDENCE: tuple[tuple[str, RunStage], ...] = (
    ("materialize", "materialized"),
    ("vep", "annotated"),
    ("vcfanno", "annotated"),
    ("normalize", "normalized"),
    ("ingest", "ingested"),
)
_AUXILIARY_STEPS: frozenset[str] = frozenset(("bcftools-stats", "mosdepth-coverage"))


def _classify_stage(step_names: list[str]) -> RunStage:
    """Pick the highest-precedence step in the trail; skip QC auxiliaries."""
    seen = {s for s in step_names if s not in _AUXILIARY_STEPS}
    for step_name, label in _STEP_PRECEDENCE:
        if step_name in seen:
            return label
    return "unknown"


class DerivedRunSummary(BaseModel):
    """One row in ``runs list`` — minimal classification of a run dir."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    sample_id: str | None = None
    started_at: str | None = None
    stage: RunStage


class ProvenanceStep(BaseModel):
    """One pipeline step recorded in ``provenance.json``.

    Field set mirrors the shape the orchestrators write today; new
    fields added by future orchestrators (e.g. vep) flow through the
    ``extras`` catch-all without bumping the CLI schema version.
    """

    model_config = ConfigDict(extra="allow")

    step: str
    tool: str | None = None
    tool_version: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RunDetail(BaseModel):
    """Full ``runs show`` payload — manifest + provenance trail."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_dir: str
    sample_id: str | None = None
    schema_version: str | None = None
    created_at: str | None = None
    stage: RunStage
    manifest: dict[str, Any] = Field(default_factory=dict)
    steps: tuple[ProvenanceStep, ...] = ()


def list_derived_runs(*, derived_root: Path) -> list[DerivedRunSummary]:
    """Walk ``derived/`` and classify each run.

    Args:
        derived_root: The ``derived/`` directory containing one
            subdirectory per run plus the ``CURRENT`` symlink.

    Returns:
        Newest-first list of :class:`DerivedRunSummary`. Returns an
        empty list when ``derived_root`` doesn't exist or contains
        no run subdirectories.
    """
    if not derived_root.is_dir():
        return []

    summaries: list[DerivedRunSummary] = []
    for entry in derived_root.iterdir():
        # Skip symlinks so the CURRENT pointer doesn't show up as a
        # duplicate of the run it resolves to. We only enumerate real
        # run directories here.
        if not entry.is_dir() or entry.is_symlink():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            # Stray scratch dir / CURRENT-symlink target / unrelated
            # folder — skip rather than mislabel.
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        stage: RunStage = "unknown"
        provenance_path = entry / "provenance.json"
        if provenance_path.is_file():
            try:
                provenance = json.loads(provenance_path.read_text())
                step_names = [s.get("step", "") for s in provenance.get("steps", [])]
                stage = _classify_stage(step_names)
            except (json.JSONDecodeError, OSError):
                stage = "unknown"

        summaries.append(
            DerivedRunSummary(
                run_id=entry.name,
                sample_id=manifest.get("sample_id"),
                started_at=manifest.get("created_at"),
                stage=stage,
            )
        )

    summaries.sort(key=lambda r: r.started_at or "", reverse=True)
    return summaries


def read_run_detail(*, run_dir: Path) -> RunDetail:
    """Read manifest + provenance for one run dir.

    Args:
        run_dir: A path to ``derived/<run-id>/`` containing
            ``manifest.json`` + ``provenance.json``.

    Returns:
        A populated :class:`RunDetail`. When ``provenance.json`` is
        missing or unreadable, ``steps`` is empty and ``stage`` falls
        back to ``"unknown"`` — the manifest fields still populate.

    Raises:
        FileNotFoundError: ``run_dir`` does not exist OR
            ``manifest.json`` is missing inside it.
        ValueError: ``manifest.json`` is present but unreadable / not
            valid JSON.
    """
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json not found in {run_dir}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"manifest.json in {run_dir} is unreadable: {exc}") from exc

    steps: tuple[ProvenanceStep, ...] = ()
    stage: RunStage = "unknown"
    provenance_path = run_dir / "provenance.json"
    if provenance_path.is_file():
        try:
            provenance = json.loads(provenance_path.read_text())
            raw_steps = provenance.get("steps", [])
            steps = tuple(ProvenanceStep.model_validate(s) for s in raw_steps)
            stage = _classify_stage([s.step for s in steps])
        except (json.JSONDecodeError, OSError):
            steps = ()
            stage = "unknown"

    return RunDetail(
        run_id=manifest.get("run_id", run_dir.name),
        run_dir=str(run_dir),
        sample_id=manifest.get("sample_id"),
        schema_version=manifest.get("schema_version"),
        created_at=manifest.get("created_at"),
        stage=stage,
        manifest=manifest,
        steps=steps,
    )


__all__ = [
    "DerivedRunSummary",
    "ProvenanceStep",
    "RunDetail",
    "RunStage",
    "list_derived_runs",
    "read_run_detail",
]

"""Smart-setup — state inspection.

``inspect_system(platform=...)`` reads the current system state and
returns a frozen ``SystemState`` snapshot. Pure side-effects (read-only
stat + subprocess capture via ``Platform``); two consecutive calls
return the same state unless something external changed.

The smart-setup dispatcher (``decide_action``) maps ``SystemState`` to
one of seven actions. Inspection + dispatch are decoupled so the
mapping logic stays testable as a pure function.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from genomeclaw_toolkit.prep.setup.platform import Platform

_CANONICAL_PARTITION = "Genome_Work"
_CANONICAL_SUBDIRS: tuple[str, ...] = ("raw", "reference", "derived", "_scratch")
_MIN_COLIMA_MEMORY_GB = 4


@dataclass(frozen=True)
class SystemState:
    """Read-only snapshot of the on-disk + runtime state setup observes.

    Attributes
    ----------
    partition_present
        True iff a volume named ``Genome_Work`` is mounted on the host.
    partition_format
        The volume's filesystem (``"apfs"`` / ``"exfat"`` / etc.) or
        ``None`` when the partition isn't present.
    partition_mountpoint
        Path to the volume's mount point (typically
        ``/Volumes/Genome_Work``) or ``None`` when absent.
    layout_present
        True iff all four canonical subdirs (``raw``, ``reference``,
        ``derived``, ``_scratch``) exist under
        ``<partition>/genomeclaw/``.
    layout_missing_subdirs
        Names of the canonical subdirs that aren't present; empty tuple
        when ``layout_present`` is True.
    nebula_present
        True iff at least one sample subdir (e.g. ``raw/<sample-id>/``)
        exists with at least one file in it.
    nebula_sample_id
        Discovered sample-id name (the single subdir name under
        ``raw/``) or ``None`` when ``nebula_present`` is False.
    colima_yaml_canonical
        True iff ``~/.colima/default/colima.yaml`` has the partition
        mount-point listed under ``mounts:`` and ``memory:`` is at least
        ``_MIN_COLIMA_MEMORY_GB``.
    colima_yaml_drift
        Short tokens describing each drift dimension (e.g.
        ``"mounts_missing_genome_work"``, ``"memory_too_low"``). Empty
        tuple when ``colima_yaml_canonical`` is True.
    colima_running
        True iff ``Platform.colima_status()`` returns ``"running"``.
    """

    partition_present: bool
    partition_format: str | None = None
    partition_mountpoint: Path | None = None
    layout_present: bool = False
    layout_missing_subdirs: tuple[str, ...] = ()
    nebula_present: bool = False
    nebula_sample_id: str | None = None
    colima_yaml_canonical: bool = False
    colima_yaml_drift: tuple[str, ...] = ()
    colima_running: bool = False


def _find_canonical_volume(volumes: list[Any], canonical_partition: str) -> Any | None:
    for v in volumes:
        if v.name == canonical_partition:
            return v
    return None


def _inspect_layout(partition_mountpoint: Path) -> tuple[bool, tuple[str, ...]]:
    """Return (layout_present, missing_subdirs)."""
    root = partition_mountpoint / "genomeclaw"
    missing = tuple(sub for sub in _CANONICAL_SUBDIRS if not (root / sub).is_dir())
    return (not missing, missing)


def _inspect_nebula(partition_mountpoint: Path) -> tuple[bool, str | None]:
    """Return (nebula_present, sample_id).

    Considers Nebula present iff exactly one sample directory exists
    under ``raw/`` and it contains at least one file. Multiple sample
    dirs is unusual; we surface the first by sort order.
    """
    raw_dir = partition_mountpoint / "genomeclaw" / "raw"
    if not raw_dir.is_dir():
        return False, None
    sample_dirs = sorted(p for p in raw_dir.iterdir() if p.is_dir())
    if not sample_dirs:
        return False, None
    first = sample_dirs[0]
    has_files = any(p.is_file() for p in first.iterdir())
    if not has_files:
        return False, None
    return True, first.name


def _inspect_colima_yaml(
    partition_mountpoint: Path | None,
) -> tuple[bool, tuple[str, ...]]:
    """Read ``~/.colima/default/colima.yaml``; report drift vs canonical.

    Canonical = (a) ``mounts:`` lists the partition mount-point AND
    (b) ``memory:`` is ≥ 4 GB. Either gap surfaces a short drift token.
    Missing colima.yaml entirely is treated as ``("mounts_missing", "memory_too_low")``.
    """
    yaml_path = Path.home() / ".colima" / "default" / "colima.yaml"
    if not yaml_path.exists():
        return False, ("colima_yaml_missing",)

    try:
        data = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError:
        return False, ("colima_yaml_malformed",)

    if not isinstance(data, dict):
        return False, ("colima_yaml_malformed",)

    drift: list[str] = []

    # Mounts check: the partition mount-point must be in mounts: (only
    # relevant when the partition exists).
    mounts = data.get("mounts") or []
    if partition_mountpoint is not None:
        target = str(partition_mountpoint).rstrip("/") or "/"
        mount_locations = [
            (m.get("location", "") if isinstance(m, dict) else "").rstrip("/") or "/"
            for m in mounts
        ]
        if target not in mount_locations:
            drift.append("mounts_missing_genome_work")

    # Memory check: ≥ 4 GB. lima accepts either int (GB) or string like "8GiB".
    mem_raw = data.get("memory", 0)
    try:
        mem_gb = int(mem_raw) if isinstance(mem_raw, int) else int(str(mem_raw).rstrip("GgIiBb"))
    except (TypeError, ValueError):
        mem_gb = 0
    if mem_gb < _MIN_COLIMA_MEMORY_GB:
        drift.append("memory_too_low")

    return not drift, tuple(drift)


def inspect_system(
    *,
    platform: Platform,
    canonical_partition: str = _CANONICAL_PARTITION,
) -> SystemState:
    """Read current system state; return a ``SystemState`` snapshot.

    Pure read-only: stats the filesystem; runs ``platform.list_volumes`` +
    ``platform.colima_status``; reads ``~/.colima/default/colima.yaml``.
    No mutations.
    """
    volumes = platform.list_volumes()
    canonical = _find_canonical_volume(volumes, canonical_partition)

    if canonical is None:
        return SystemState(partition_present=False)

    partition_mountpoint = Path(canonical.mount_point)
    partition_format = canonical.filesystem

    if partition_format != "apfs":
        # Wrong-format partition: don't bother inspecting layout / Nebula /
        # colima — the full destructive path is going to wipe it.
        return SystemState(
            partition_present=True,
            partition_format=partition_format,
            partition_mountpoint=partition_mountpoint,
        )

    layout_present, missing_subdirs = _inspect_layout(partition_mountpoint)
    nebula_present, sample_id = _inspect_nebula(partition_mountpoint)
    colima_canonical, colima_drift = _inspect_colima_yaml(partition_mountpoint)

    colima_running = platform.colima_status() == "running"

    return SystemState(
        partition_present=True,
        partition_format=partition_format,
        partition_mountpoint=partition_mountpoint,
        layout_present=layout_present,
        layout_missing_subdirs=missing_subdirs,
        nebula_present=nebula_present,
        nebula_sample_id=sample_id,
        colima_yaml_canonical=colima_canonical,
        colima_yaml_drift=colima_drift,
        colima_running=colima_running,
    )


__all__ = ["SystemState", "inspect_system"]

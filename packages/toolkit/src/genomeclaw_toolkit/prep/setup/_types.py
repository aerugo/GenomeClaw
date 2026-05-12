"""Dataclasses for the ``setup`` flow — `Volume`, `DriveIdentity`,
`NebulaDeliverable`, `SpaceBudget`, `SetupPlan`. Frozen + JSON-serialisable.

Phase 1 ships the data shapes; Phase 2's executor consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Volume:
    """A mounted host volume as observed from outside the VM.

    ``parent_disk`` is the canonical key for same-disk detection — two
    partitions on the same physical drive share a parent (e.g. both
    sit under ``/dev/disk4``). Path comparison is *not* sufficient.
    """

    name: str
    mount_point: str
    size_bytes: int
    parent_disk: str
    filesystem: str
    is_system_disk: bool


@dataclass(frozen=True)
class DriveIdentity:
    """Hardware identity for a target drive.

    Read once via ``read_drive_identity(volume)``; used by the firmware-safety
    gate (`assert_firmware_safe`) and surfaced verbatim in the dry-run preview.
    """

    model: str
    firmware: str
    capacity_gb: int
    parent_disk: str
    bus_type: str  # e.g. "USB", "Thunderbolt", "Internal"


@dataclass(frozen=True)
class NebulaDeliverable:
    """The user's Nebula source data, as walked from a candidate directory."""

    source_path: Path
    sample_id: str
    has_cram: bool
    has_bam: bool
    has_fastq: bool
    has_vcf: bool
    has_vcf_index: bool
    header_check_ok: bool
    total_bytes: int
    files: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class SpaceBudget:
    """The four components of the runtime free-space pre-flight (spec § AC3)."""

    raw_bytes: int
    reference_bytes: int
    scratch_bytes: int
    margin_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.raw_bytes + self.reference_bytes + self.scratch_bytes + self.margin_bytes


@dataclass(frozen=True)
class SetupPlan:
    """The complete, computed-but-not-executed plan for ``setup``.

    Phase 1 builds + renders this; Phase 2's executor consumes it after
    the typed-confirmation gate.
    """

    nebula: NebulaDeliverable
    target_volume: Volume
    target_identity: DriveIdentity
    budget: SpaceBudget
    target_free_bytes: int
    confirmation_phrase: str  # e.g. "WIPE /Volumes/<name>"


__all__ = [
    "DriveIdentity",
    "NebulaDeliverable",
    "SetupPlan",
    "SpaceBudget",
    "Volume",
]

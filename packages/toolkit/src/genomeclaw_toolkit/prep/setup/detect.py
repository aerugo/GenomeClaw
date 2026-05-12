"""Detection + validation for ``genomeclaw host setup``.

Phase 1 surface (non-destructive):

- :func:`list_volumes` — host volume enumeration via the platform layer.
- :func:`validate_nebula` — walk a Nebula deliverable directory and confirm shape.
- :func:`assert_different_physical_disk` — same-disk safeguard via parent-disk identity.
- :func:`read_drive_identity` — model + firmware + capacity for the target drive.
- :func:`assert_firmware_safe` — gate against the maintained known-bad list.
- :func:`assert_sufficient_space` — runtime free-space pre-flight (spec § AC3).
- :func:`build_plan` — composes everything above into a :class:`SetupPlan`.

Tests inject a fake ``Platform``; production calls :func:`default_platform`.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from genomeclaw_toolkit.prep.setup._types import (
    DriveIdentity,
    NebulaDeliverable,
    SetupPlan,
    SpaceBudget,
    Volume,
)
from genomeclaw_toolkit.prep.setup.platform import (
    Platform,
    default_platform,
)

# Re-export so callers don't need a second import for the production platform.
__all__ = [
    "InsufficientSpaceError",
    "KnownBadFirmwareError",
    "NebulaDeliverableError",
    "SameDiskError",
    "SetupError",
    "SpaceBudget",
    "assert_different_physical_disk",
    "assert_firmware_safe",
    "assert_sufficient_space",
    "build_plan",
    "default_platform",
    "list_volumes",
    "read_drive_identity",
    "validate_nebula",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SetupError(Exception):
    """Base for every fixable setup failure."""


class NebulaDeliverableError(SetupError):
    """The candidate Nebula directory failed validation."""


class SameDiskError(SetupError):
    """Source and destination resolve to the same physical disk."""


class KnownBadFirmwareError(SetupError):
    """Target drive's (model, firmware) appears in the known-bad list."""


class InsufficientSpaceError(SetupError):
    """Computed free-space need exceeds the target drive's available bytes."""


# ---------------------------------------------------------------------------
# Volume listing
# ---------------------------------------------------------------------------


def list_volumes(platform: Platform | None = None) -> list[Volume]:
    """Return externally-mounted volumes (system disk excluded)."""
    plat = platform or default_platform()
    return [v for v in plat.list_volumes() if not v.is_system_disk]


# ---------------------------------------------------------------------------
# Nebula deliverable validation
# ---------------------------------------------------------------------------


def validate_nebula(path: Path, platform: Platform | None = None) -> NebulaDeliverable:
    """Validate that ``path`` looks like a Nebula deliverable; bail with
    a fixable error message on each failure mode.
    """
    plat = platform or default_platform()
    if not path.exists():
        raise NebulaDeliverableError(f"Nebula deliverable directory not found: {path}")
    if not path.is_dir():
        raise NebulaDeliverableError(f"Nebula deliverable path is not a directory: {path}")

    files: list[tuple[str, int]] = []
    has_cram = has_bam = has_fastq = has_vcf = has_vcf_idx = False
    vcf_path: Path | None = None
    total = 0
    for child in sorted(path.iterdir()):
        if not child.is_file():
            continue
        size = child.stat().st_size
        files.append((child.name, size))
        total += size
        n = child.name.lower()
        if n.endswith(".cram"):
            has_cram = True
        elif n.endswith(".bam"):
            has_bam = True
        elif n.endswith(".fastq.gz") or n.endswith(".fq.gz"):
            has_fastq = True
        elif n.endswith(".vcf.gz"):
            has_vcf = True
            vcf_path = child
        elif n.endswith(".vcf.gz.tbi"):
            has_vcf_idx = True

    if not (has_cram or has_bam or has_fastq or has_vcf):
        raise NebulaDeliverableError(
            f"no recognizable genomic files in {path} — "
            f"expected one of *.cram, *.bam, *.fastq.gz, *.vcf.gz"
        )

    header_check_ok = True
    if vcf_path is not None:
        status, stderr = plat.bcftools_view_header(vcf_path)
        if status == "fail":
            stripped = stderr.strip() or "unknown error"
            raise NebulaDeliverableError(f"bcftools view -h on {vcf_path.name} failed:\n{stripped}")
        if status == "unavailable":
            # The check couldn't run (no host bcftools + no reachable
            # docker daemon, or toolkit image not pulled). Setup itself
            # is what brings the docker runtime up, so this is expected
            # during initial onboarding. Skip with a non-fatal warning
            # rather than blocking — the actual ingest pipeline reruns
            # bcftools with a real runtime and will catch any bad VCF.
            reason = stderr.strip() or "tool unavailable"
            print(
                f"warning: skipping VCF header check on {vcf_path.name} — {reason}",
                file=sys.stderr,
            )
            header_check_ok = False
        else:
            header_check_ok = True

    return NebulaDeliverable(
        source_path=path,
        sample_id=path.name,
        has_cram=has_cram,
        has_bam=has_bam,
        has_fastq=has_fastq,
        has_vcf=has_vcf,
        has_vcf_index=has_vcf_idx,
        header_check_ok=header_check_ok,
        total_bytes=total,
        files=files,
    )


# ---------------------------------------------------------------------------
# Same-disk safeguard
# ---------------------------------------------------------------------------


def assert_different_physical_disk(src: Volume, dst: Volume) -> None:
    """Reject when ``src`` and ``dst`` share a parent disk identifier."""
    if src.parent_disk == dst.parent_disk:
        raise SameDiskError(
            f"source ({src.mount_point}) and target ({dst.mount_point}) "
            f"resolve to the same physical disk: {src.parent_disk}"
        )


# ---------------------------------------------------------------------------
# Drive identity + firmware safety
# ---------------------------------------------------------------------------


def read_drive_identity(target: Volume, platform: Platform | None = None) -> DriveIdentity:
    plat = platform or default_platform()
    return plat.read_drive_identity(target)


def _default_known_bad_path() -> Path:
    return Path(__file__).parent / "known_bad_firmware.toml"


def assert_firmware_safe(
    identity: DriveIdentity,
    *,
    known_bad_path: Path | None = None,
) -> None:
    """Refuse if ``(identity.model, identity.firmware)`` matches a known-bad entry."""
    path = known_bad_path or _default_known_bad_path()
    if not path.exists():
        return  # absent file = empty list = nothing to do
    data = tomllib.loads(path.read_text())
    for entry in data.get("entry", []):
        if entry.get("model") == identity.model and entry.get("firmware") == identity.firmware:
            url = entry.get("advisory_url", "")
            raise KnownBadFirmwareError(
                f"target drive {identity.model!r} firmware {identity.firmware!r} "
                f"is on the known-bad list — refusing to proceed. "
                f"Advisory: {url}"
            )


# ---------------------------------------------------------------------------
# Free-space pre-flight
# ---------------------------------------------------------------------------


def _gb(n_bytes: int) -> str:
    return f"{n_bytes / 1000**3:.1f} GB"


def assert_sufficient_space(free_bytes: int, budget: SpaceBudget) -> None:
    """Raise if ``free_bytes`` cannot cover ``budget.total_bytes``."""
    need = budget.total_bytes
    if free_bytes >= need:
        return
    shortfall = need - free_bytes
    raise InsufficientSpaceError(
        "insufficient free space on target — "
        f"need {_gb(need)} (raw {_gb(budget.raw_bytes)} + reference "
        f"{_gb(budget.reference_bytes)} + scratch {_gb(budget.scratch_bytes)} + "
        f"margin {_gb(budget.margin_bytes)}), free {_gb(free_bytes)}, "
        f"shortfall {_gb(shortfall)}"
    )


# ---------------------------------------------------------------------------
# Plan composition
# ---------------------------------------------------------------------------


_DEFAULT_REFERENCE_BYTES = 5 * 1000**3  # Phase-4A floor (ClinVar + GRCh38)
_DEFAULT_SCRATCH_BYTES = 300 * 1000**3
_DEFAULT_MARGIN_BYTES = 50 * 1000**3


def build_plan(
    *,
    nebula_dir: Path,
    target_mount: str,
    platform: Platform | None = None,
    reference_bytes: int = _DEFAULT_REFERENCE_BYTES,
    scratch_bytes: int = _DEFAULT_SCRATCH_BYTES,
    margin_bytes: int = _DEFAULT_MARGIN_BYTES,
) -> SetupPlan:
    """Run the full Phase-1 detection + validation pipeline; return a SetupPlan.

    Side-effect-free: no filesystem mutation under either the source or
    target drive. Raises one of the ``SetupError`` subclasses on any
    failure mode; the caller (CLI / interactive) decides how to surface.
    """
    plat = platform or default_platform()

    # 1. Detect host volumes; identify source and target.
    # Source is allowed on the system disk (typical workflow: Nebula
    # deliverable on the user's internal SSD, target on an external
    # drive). Target is restricted to the filtered external list.
    # The same-disk safeguard below catches the dangerous case.
    all_volumes = plat.list_volumes()
    external_volumes = [v for v in all_volumes if not v.is_system_disk]
    src_volume = _resolve_source_volume(all_volumes, nebula_dir)
    dst_volume = _resolve_target_volume(external_volumes, target_mount)

    # 2. Same-disk safeguard.
    assert_different_physical_disk(src_volume, dst_volume)

    # 3. Validate the Nebula deliverable.
    nebula = validate_nebula(nebula_dir, plat)

    # 4. Drive identity + firmware safety.
    identity = read_drive_identity(dst_volume, plat)
    assert_firmware_safe(identity)

    # 5. Free-space pre-flight.
    budget = SpaceBudget(
        raw_bytes=nebula.total_bytes,
        reference_bytes=reference_bytes,
        scratch_bytes=scratch_bytes,
        margin_bytes=margin_bytes,
    )
    free_bytes = dst_volume.size_bytes  # Phase 1: assume size_bytes == free
    assert_sufficient_space(free_bytes, budget)

    return SetupPlan(
        nebula=nebula,
        target_volume=dst_volume,
        target_identity=identity,
        budget=budget,
        target_free_bytes=free_bytes,
        confirmation_phrase=f"WIPE {dst_volume.mount_point}",
    )


def _resolve_source_volume(all_volumes: list[Volume], nebula_dir: Path) -> Volume:
    """Return the volume that contains ``nebula_dir``.

    Searches *all* volumes — including the system disk — because the
    typical workflow has the Nebula deliverable on the internal SSD
    (system disk) and the target on an external drive. The same-disk
    safeguard in ``assert_different_physical_disk`` still rejects the
    dangerous case where source and target resolve to the same parent
    disk.
    """
    nstr = str(nebula_dir.resolve()) if nebula_dir.exists() else str(nebula_dir)
    candidates = [
        v
        for v in all_volumes
        if nstr == v.mount_point or nstr.startswith(v.mount_point.rstrip("/") + "/")
    ]
    if not candidates:
        raise NebulaDeliverableError(
            f"Nebula deliverable {nebula_dir} is not on any detected external volume"
        )
    # Pick the deepest mount point (handles nested-mount edge cases).
    candidates.sort(key=lambda v: len(v.mount_point), reverse=True)
    return candidates[0]


def _resolve_target_volume(volumes: list[Volume], target_mount: str) -> Volume:
    """Return the volume whose name or mount_point matches ``target_mount``."""
    for v in volumes:
        if v.name == target_mount or v.mount_point == target_mount:
            return v
    raise SetupError(
        f"target volume {target_mount!r} not found among detected volumes: "
        f"{[v.name for v in volumes]}"
    )


# ---------------------------------------------------------------------------
# Interactive flow
# ---------------------------------------------------------------------------


def run_interactive(
    platform: Platform | None = None,
    *,
    execute_destructive: bool = True,
    nebula_dir: Path | None = None,
    target_mount: str | None = None,
    auto_confirm: bool = False,
) -> int:
    """Top-level entry for ``genomeclaw host setup``.

    Walks the user through detection + validation, renders a dry-run
    preview, prompts for the typed-confirmation phrase, and then (when
    ``execute_destructive`` is True) runs the Phase-2 destructive
    executor. Setting ``execute_destructive=False`` reverts to Phase-1
    behavior — preview only, no prompt — useful when callers want a
    pure dry-run.

    Three optional inputs allow the same code path to drive a fully
    unattended (scripted) destructive setup:

    - ``nebula_dir`` skips the ``Path to Nebula deliverable directory:``
      prompt.
    - ``target_mount`` skips the ``Target volume name:`` prompt.
    - ``auto_confirm`` skips the typed ``WIPE /Volumes/<name>``
      confirmation. The act of passing this flag through the CLI
      (``--force-reset``) is itself the deliberate confirmation —
      mirroring how the typed phrase serves as the gate in the
      interactive path. A loud one-line announcement is printed so the
      bypass is visible in the audit log + terminal scroll-back.

    Returns a process-style exit code (0 on success, 2 on any
    ``SetupError``).

    Reads user input via ``builtins.input``; writes to ``sys.stdout`` /
    ``sys.stderr`` resolved at call time. Tests monkey-patch
    ``builtins.input`` directly and use ``capsys`` to read stdout/stderr.
    """
    import builtins

    from genomeclaw_toolkit.prep.setup.dryrun import render
    from genomeclaw_toolkit.prep.setup.execute import (
        ConfirmationMismatchError,
        DestructiveStepError,
        execute,
    )

    plat = platform or default_platform()

    # Friendly volume listing so the user sees what they have.
    volumes = list_volumes(plat)
    print("Detected external volumes:", file=sys.stdout)
    for v in volumes:
        size_gb = v.size_bytes / 1000**3
        print(
            f"  - {v.name}  ({v.mount_point}, {size_gb:.0f} GB, {v.filesystem})",
            file=sys.stdout,
        )
    print("", file=sys.stdout)

    if nebula_dir is None:
        nebula_input = builtins.input("Path to Nebula deliverable directory: ").strip()
        nebula_dir = Path(nebula_input)
    else:
        print(f"Path to Nebula deliverable directory: {nebula_dir}", file=sys.stdout)
    if target_mount is None:
        target_mount = builtins.input("Target volume name (from list above): ").strip()
    else:
        print(f"Target volume name: {target_mount}", file=sys.stdout)

    try:
        plan = build_plan(
            nebula_dir=nebula_dir,
            target_mount=target_mount,
            platform=plat,
        )
    except SetupError as exc:
        print(f"genomeclaw host setup: {exc}", file=sys.stderr)
        return 2

    print(render(plan), file=sys.stdout)

    if not execute_destructive:
        return 0

    print("", file=sys.stdout)
    if auto_confirm:
        print(
            f"[!] --force-reset: auto-confirming '{plan.confirmation_phrase}' "
            "(no prompt; supplied via flag)",
            file=sys.stdout,
        )
        typed = plan.confirmation_phrase
    else:
        print(
            f"To proceed, type the confirmation phrase exactly: {plan.confirmation_phrase}",
            file=sys.stdout,
        )
        typed = builtins.input("> ").strip()

    audit_log_dir = Path.home() / ".genomeclaw"
    try:
        execute(
            plan,
            plat,
            confirmation_phrase=typed,
            audit_log_dir=audit_log_dir,
        )
    except ConfirmationMismatchError as exc:
        print(f"genomeclaw host setup: {exc}", file=sys.stderr)
        return 2
    except (DestructiveStepError, SetupError) as exc:
        print(f"genomeclaw host setup: {exc}", file=sys.stderr)
        return 3

    # ``execute(verbose=True)`` already prints the full completion summary
    # (what was done, where everything landed, next-step commands). The
    # CLI doesn't need to add anything here — duplicating "setup: ok"
    # would be noise.
    return 0

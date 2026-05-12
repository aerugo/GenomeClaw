"""Host-platform abstraction for ``setup``.

The setup flow does three things that touch the host OS specifically:

1. Enumerate mounted volumes (``diskutil list -plist`` on macOS).
2. Read drive model + firmware revision (``diskutil info -plist`` on macOS).
3. Validate a Nebula VCF header (``bcftools view -h``, shelled out either to
   the host's bcftools if present or to the toolkit container).

Tests inject a fake ``Platform``; production uses ``MacOSPlatform`` (Phase
1 only ships macOS — Linux is a follow-up plan).
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Literal, Protocol

from genomeclaw_toolkit.prep.setup._types import DriveIdentity, Volume

BcftoolsViewHeaderStatus = Literal["ok", "fail", "unavailable"]


class Platform(Protocol):
    """The host-platform interface ``detect`` and ``execute`` call into."""

    # ---- Phase 1 (non-destructive) -------------------------------------

    def list_volumes(self) -> list[Volume]: ...

    def read_drive_identity(self, volume: Volume) -> DriveIdentity: ...

    def bcftools_view_header(self, vcf: Path) -> tuple[BcftoolsViewHeaderStatus, str]:
        """Run ``bcftools view -h <vcf>``; return ``(status, stderr_text)``.

        ``status`` is one of:

        - ``"ok"`` — bcftools parsed the header successfully.
        - ``"fail"`` — bcftools ran but rejected the file (corrupt /
          non-VCF). Callers should treat this as a real validation
          failure.
        - ``"unavailable"`` — neither a host ``bcftools`` nor a working
          docker daemon was reachable. The check did not run; callers
          should skip with a warning rather than hard-failing, since
          the setup flow itself is what brings the docker runtime up.
        """
        ...

    # ---- Phase 2 (destructive) — each raises DestructiveStepError on failure

    def colima_status(self) -> str:
        """Return ``"running"`` / ``"stopped"`` / ``"not_installed"``."""
        ...

    def colima_stop(self) -> None: ...

    def colima_start(self) -> None: ...

    def unmount_disk(self, parent_disk: str) -> None: ...

    def partition_disk_apfs(self, parent_disk: str, label: str) -> Path:
        """Repartition ``parent_disk`` as a single APFS partition named
        ``label``; return the post-partition mount point (e.g. ``/Volumes/<label>``)."""
        ...

    def verify_mounts_via_shim(self, target_root: Path) -> None:
        """One-shot ``docker run`` that bind-mounts ``raw`` / ``reference``
        / ``derived`` / ``_scratch`` from ``target_root`` with the same
        flags the production shim uses, and asserts each comes up with
        the expected ``ro`` / ``rw`` flag. Raises ``MountFlagError`` on
        mismatch.

        This is the Option-A replacement for the original cram-scratch
        report's "block-attached ext4 scratch + mount in VM" path —
        colima 0.9.1 doesn't support ``additionalDisks`` passthrough,
        so per-subdir RO/RW lives at the docker bind-mount layer.
        """
        ...

    def copy_file_with_sha(self, src: Path, dst: Path) -> tuple[str, str]:
        """Copy ``src`` to ``dst`` (cross-fs OK); return (src_sha256, dst_sha256)."""
        ...


# ---------------------------------------------------------------------------
# macOS implementation
# ---------------------------------------------------------------------------


class MacOSPlatform:
    """Real-host macOS implementation backed by ``diskutil`` and a docker
    fallback for ``bcftools``.
    """

    def __init__(self, *, image: str = "genomeclaw/toolkit:dev") -> None:
        self._image = image

    def list_volumes(self) -> list[Volume]:
        proc = subprocess.run(
            ["diskutil", "list", "-plist"],
            capture_output=True,
            check=True,
        )
        info = plistlib.loads(proc.stdout)
        out: list[Volume] = []
        seen: set[str] = set()
        for entry in info.get("AllDisksAndPartitions", []):
            parent = entry.get("DeviceIdentifier", "")
            # macOS APFS containers expose their mountable volumes under
            # ``APFSVolumes`` rather than ``Partitions``; iterate both so
            # the synthesized system volumes (Macintosh HD, Data, Preboot,
            # ...) show up alongside plain GPT/MBR partitions.
            entries = list(entry.get("Partitions", [])) + list(entry.get("APFSVolumes", []))
            if not entries:
                entries = [entry]
            for part in entries:
                ident = part.get("DeviceIdentifier")
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                # Per-partition info to get mount point + size + filesystem.
                sub = subprocess.run(
                    ["diskutil", "info", "-plist", ident],
                    capture_output=True,
                    check=False,
                )
                if sub.returncode != 0:
                    continue
                pinfo = plistlib.loads(sub.stdout)
                mount_point = pinfo.get("MountPoint", "")
                if not mount_point:
                    continue
                # For APFS volumes ``ParentWholeDisk`` points to the
                # *synthesized* APFS container disk (e.g. ``disk5``) — not
                # the underlying physical disk hosting the Physical Store
                # (e.g. ``disk4``). Whole-disk verbs we run later
                # (``diskutil eraseDisk``) require the physical disk; the
                # synthesized container disk is guarded by APFS and
                # rejects whole-disk format ops. Resolve through
                # ``APFSPhysicalStores`` whenever it's present.
                vol_parent = self._resolve_physical_whole_disk(pinfo, fallback=parent)
                # Treat any volume mounted at / or under /System/ or
                # /private/ as a system volume. macOS Sequoia spreads its
                # protected partitions across multiple synthesized APFS
                # containers (iSCPreboot/xART/Hardware on disk1,
                # Recovery on disk2, the user-facing volumes on disk3),
                # so a single ParentWholeDisk match isn't enough; the
                # mount-point heuristic is robust and matches the actual
                # "is this part of the OS install" question we care about.
                mp = mount_point.rstrip("/")
                is_sys = (
                    mp == ""  # mount_point == "/"
                    or mp.startswith("/System/")
                    or mp.startswith("/private/")
                    or mp == "/nix"  # nix store is system-managed
                )
                # USB/Thunderbolt drives are never system disks regardless of mount path.
                bus = str(pinfo.get("BusProtocol", "")).lower()
                if bus in ("usb", "thunderbolt", "fibrechannel"):
                    is_sys = False
                out.append(
                    Volume(
                        name=pinfo.get("VolumeName", "") or ident,
                        mount_point=mount_point,
                        size_bytes=int(pinfo.get("TotalSize", 0)),
                        parent_disk=vol_parent,
                        filesystem=str(
                            pinfo.get("FilesystemType") or pinfo.get("FilesystemName", "")
                        ).lower(),
                        is_system_disk=is_sys,
                    )
                )
        return out

    def _resolve_physical_whole_disk(self, pinfo: dict, *, fallback: str) -> str:
        """Resolve an APFS volume's ``parent_disk`` to the physical whole disk.

        Non-APFS volumes (or volumes missing the field) return
        ``pinfo["ParentWholeDisk"]`` (falling back to ``fallback``). APFS
        volumes follow ``APFSPhysicalStores[0].APFSPhysicalStore`` (the
        partition like ``disk4s2``) up to that partition's own
        ``ParentWholeDisk`` (the physical disk like ``disk4``).
        """
        parent_whole_disk = pinfo.get("ParentWholeDisk", fallback)
        stores = pinfo.get("APFSPhysicalStores")
        if not stores:
            return parent_whole_disk
        ps_ident = stores[0].get("APFSPhysicalStore", "") if isinstance(stores[0], dict) else ""
        if not ps_ident:
            return parent_whole_disk
        ps_proc = subprocess.run(
            ["diskutil", "info", "-plist", ps_ident],
            capture_output=True,
            check=False,
        )
        if ps_proc.returncode != 0:
            return parent_whole_disk
        try:
            ps_pinfo = plistlib.loads(ps_proc.stdout)
        except plistlib.InvalidFileException:
            return parent_whole_disk
        return ps_pinfo.get("ParentWholeDisk") or parent_whole_disk

    def read_drive_identity(self, volume: Volume) -> DriveIdentity:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", volume.parent_disk],
            capture_output=True,
            check=True,
        )
        info = plistlib.loads(proc.stdout)
        capacity_bytes = int(info.get("Size", 0))
        bus = str(info.get("BusProtocol", "USB"))
        return DriveIdentity(
            model=str(info.get("MediaName", "Unknown")),
            firmware=str(info.get("DeviceTreePath", "") or info.get("IORegistryEntryName", "")),
            capacity_gb=int(round(capacity_bytes / 1000**3)),
            parent_disk=volume.parent_disk,
            bus_type=bus,
        )

    def bcftools_view_header(self, vcf: Path) -> tuple[BcftoolsViewHeaderStatus, str]:
        # Prefer host bcftools if present; otherwise shell into the toolkit image.
        if shutil.which("bcftools"):
            proc = subprocess.run(
                ["bcftools", "view", "-h", str(vcf)],
                capture_output=True,
                check=False,
            )
            stderr = proc.stderr.decode("utf-8", errors="replace")
            return ("ok" if proc.returncode == 0 else "fail"), stderr

        if not shutil.which("docker"):
            return "unavailable", "neither bcftools nor docker available on host"

        # Probe the daemon before shelling out — `docker run` on a stopped
        # daemon (e.g. colima stopped, common during setup pre-flight)
        # returns rc=1 with a giant multi-line stderr whose last line is
        # the generic "Run 'docker run --help' for more information",
        # which buries the actual cause. A `docker info` probe is cheap
        # and lets us distinguish "daemon down" from "VCF rejected".
        info = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False,
        )
        if info.returncode != 0:
            stderr = info.stderr.decode("utf-8", errors="replace").strip()
            return "unavailable", f"docker daemon not reachable: {stderr}"

        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--mount",
                f"type=bind,source={vcf.parent},target=/tmp/v,readonly",
                "--entrypoint",
                "bcftools",
                self._image,
                "view",
                "-h",
                f"/tmp/v/{vcf.name}",
            ],
            capture_output=True,
            check=False,
        )
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if proc.returncode == 0:
            return "ok", stderr
        # The image might not be pulled / built yet during initial setup;
        # treat "no such image" as unavailable rather than a VCF failure.
        if "Unable to find image" in stderr or "pull access denied" in stderr:
            return "unavailable", f"toolkit image not available: {stderr.strip()}"
        return "fail", stderr

    # ---- Phase 2 destructive surface -----------------------------------

    def _run_destructive(
        self,
        step: str,
        args: list[str],
        *,
        check_cmd: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        from genomeclaw_toolkit.prep.setup.execute import DestructiveStepError

        if check_cmd and not shutil.which(args[0]):
            raise DestructiveStepError(
                step_name=step,
                return_code=127,
                stderr=f"{args[0]} not on PATH",
            )
        proc = subprocess.run(args, capture_output=True, check=False)
        if proc.returncode != 0:
            raise DestructiveStepError(
                step_name=step,
                return_code=proc.returncode,
                stderr=proc.stderr.decode("utf-8", errors="replace").strip(),
            )
        return proc

    def colima_status(self) -> str:
        if not shutil.which("colima"):
            return "not_installed"
        proc = subprocess.run(["colima", "status"], capture_output=True, check=False)
        out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").lower()
        # Substring "is running" only appears when colima is up; "is not
        # running" does not contain "is running" as a contiguous substring.
        if "is running" in out:
            return "running"
        return "stopped"

    def colima_stop(self) -> None:
        # `colima stop` exits 0 even if already stopped, so this is safely idempotent.
        self._run_destructive("colima_stop", ["colima", "stop"])

    def colima_start(self) -> None:
        self._run_destructive("colima_start", ["colima", "start"])

    def unmount_disk(self, parent_disk: str) -> None:
        device = parent_disk if parent_disk.startswith("/dev/") else f"/dev/{parent_disk}"
        # ``force`` overrides Spotlight's mds_stores dissent and similar
        # "volume held by daemon" lockups. The user has already typed the
        # WIPE confirmation phrase by the time we get here, so a forced
        # unmount is consistent with their intent.
        self._run_destructive("unmount_disk", ["diskutil", "unmountDisk", "force", device])

    def partition_disk_apfs(self, parent_disk: str, label: str) -> Path:
        device = parent_disk if parent_disk.startswith("/dev/") else f"/dev/{parent_disk}"
        # diskutil's whole-disk verbs (``partitionDisk`` / ``eraseDisk``)
        # both refuse to run on a disk that hosts an APFS Container —
        # macOS treats the volume hierarchy as managed by APFS and guards
        # the underlying device. The fix is to tear down the APFS
        # Container first, which releases the guard and leaves the GPT
        # slot as Free Space; ``eraseDisk`` then rewrites the GPT and
        # creates a single APFS volume filling the disk. On a non-APFS
        # disk (fresh / exFAT / NTFS) ``_find_apfs_container_partitions``
        # returns nothing and we go straight to ``eraseDisk``.
        for apfs_partition in self._find_apfs_container_partitions(parent_disk):
            self._run_destructive(
                "partition_disk_apfs",
                ["diskutil", "apfs", "deleteContainer", apfs_partition],
            )
        self._run_destructive(
            "partition_disk_apfs",
            ["diskutil", "eraseDisk", "APFS", label, device],
        )
        return Path(f"/Volumes/{label}")

    def _find_apfs_container_partitions(self, parent_disk: str) -> list[str]:
        """Return ``/dev/diskNsM`` identifiers of every Apple_APFS partition
        under ``parent_disk``. Empty list when the disk is missing or hosts
        no APFS containers. Read-only — pure ``diskutil list`` capture.
        """
        device = parent_disk if parent_disk.startswith("/dev/") else f"/dev/{parent_disk}"
        proc = subprocess.run(
            ["diskutil", "list", "-plist", device],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        try:
            info = plistlib.loads(proc.stdout)
        except plistlib.InvalidFileException:
            return []
        found: list[str] = []
        for entry in info.get("AllDisksAndPartitions", []):
            for part in entry.get("Partitions", []):
                if part.get("Content") == "Apple_APFS":
                    ident = part.get("DeviceIdentifier")
                    if ident:
                        found.append(f"/dev/{ident}")
        return found

    def verify_mounts_via_shim(self, target_root: Path) -> None:
        """Spin a one-shot container with the same ``--mount`` flags the
        production shim uses; assert each subdir's RO/RW matches.
        """
        from genomeclaw_toolkit.prep.setup.execute import MountFlagError

        script = (
            "set -e\n"
            "mount | grep ' /mnt/genomeclaw/' || true\n"
            "for ro_path in /mnt/genomeclaw/raw /mnt/genomeclaw/reference; do\n"
            "  if touch $ro_path/.probe 2>/dev/null; then\n"
            "    echo FAIL_RO_$ro_path\n"
            "    rm -f $ro_path/.probe\n"
            "    exit 2\n"
            "  fi\n"
            "done\n"
            "for rw_path in /mnt/genomeclaw/derived /mnt/genomeclaw/_scratch; do\n"
            "  if ! touch $rw_path/.probe 2>/dev/null; then\n"
            "    echo FAIL_RW_$rw_path\n"
            "    exit 3\n"
            "  fi\n"
            "  rm -f $rw_path/.probe\n"
            "done\n"
            "echo OK\n"
        )
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--mount",
                f"type=bind,source={target_root}/raw,target=/mnt/genomeclaw/raw,readonly",
                "--mount",
                f"type=bind,source={target_root}/reference,"
                "target=/mnt/genomeclaw/reference,readonly",
                "--mount",
                f"type=bind,source={target_root}/derived,target=/mnt/genomeclaw/derived",
                "--mount",
                f"type=bind,source={target_root}/_scratch,target=/mnt/genomeclaw/_scratch",
                "--entrypoint",
                "sh",
                self._image,
                "-c",
                script,
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise MountFlagError(
                f"shim mount verification failed (rc={proc.returncode}): "
                f"{proc.stderr.decode('utf-8', errors='replace').strip()} | "
                f"stdout: {proc.stdout.decode('utf-8', errors='replace').strip()}"
            )

    def copy_file_with_sha(self, src: Path, dst: Path) -> tuple[str, str]:
        import hashlib

        dst.parent.mkdir(parents=True, exist_ok=True)
        h_src = hashlib.sha256()
        h_dst = hashlib.sha256()
        with src.open("rb") as r, dst.open("wb") as w:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h_src.update(chunk)
                w.write(chunk)
        # Hash the destination by re-reading (catches in-flight corruption).
        with dst.open("rb") as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h_dst.update(chunk)
        return h_src.hexdigest(), h_dst.hexdigest()


def default_platform() -> Platform:
    """Return the production platform implementation. Tests monkey-patch
    ``detect.default_platform`` rather than calling this directly.
    """
    return MacOSPlatform()


__all__ = ["MacOSPlatform", "Platform", "default_platform"]

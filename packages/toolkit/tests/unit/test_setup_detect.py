"""Phase 1 — unit tests for ``prep/setup/detect.py``.

Targets the parsing/validation helpers in isolation, with a fake
``Platform`` so no real ``diskutil`` / ``bcftools`` calls happen.
End-to-end interactive flow is tested in
``tests/integration/test_setup_dryrun.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fake platform helpers — keep here so unit tests stay self-contained.
# ---------------------------------------------------------------------------


class _FakePlatform:
    """A test double for ``prep.setup.platform.Platform`` covering the
    Phase-1 interaction surface: list volumes, identify a drive, run
    ``bcftools view -h`` on a candidate VCF.
    """

    def __init__(
        self,
        *,
        volumes: list[dict] | None = None,
        identities: dict[str, dict] | None = None,
        bcftools_ok: bool = True,
        bcftools_stderr: str = "",
        bcftools_status: str | None = None,
    ) -> None:
        self.volumes = volumes or []
        self.identities = identities or {}
        # Back-compat shorthand: tests written before the tri-state set
        # ``bcftools_ok=True/False``; new tests can set ``bcftools_status``
        # directly to exercise the "unavailable" branch.
        self.bcftools_status = bcftools_status or ("ok" if bcftools_ok else "fail")
        self.bcftools_stderr = bcftools_stderr

    def list_volumes(self):  # noqa: D401 — matches Protocol
        from genomeclaw_toolkit.prep.setup._types import Volume

        return [Volume(**v) for v in self.volumes]

    def read_drive_identity(self, volume):
        from genomeclaw_toolkit.prep.setup._types import DriveIdentity

        ident = self.identities.get(volume.parent_disk)
        if ident is None:
            raise FileNotFoundError(f"no identity for {volume.parent_disk}")
        return DriveIdentity(**ident)

    def bcftools_view_header(self, vcf: Path) -> tuple[str, str]:
        return self.bcftools_status, self.bcftools_stderr


def _v(**kw):
    """Shorthand for a Volume-shaped dict with sensible defaults."""
    base = {
        "name": "TestVol",
        "mount_point": "/Volumes/TestVol",
        "size_bytes": 500 * 1000**3,
        "parent_disk": "disk4",
        "filesystem": "exfat",
        "is_system_disk": False,
    }
    base.update(kw)
    return base


def _id(**kw):
    base = {
        "model": "Generic External SSD",
        "firmware": "1.0",
        "capacity_gb": 500,
        "parent_disk": "disk4",
        "bus_type": "USB",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 1. Volume listing
# ---------------------------------------------------------------------------


def test_detect_lists_external_volumes_and_skips_system_disk() -> None:
    """``list_volumes`` returns externals and excludes the system disk."""
    from genomeclaw_toolkit.prep.setup.detect import list_volumes

    plat = _FakePlatform(
        volumes=[
            _v(
                name="MacintoshHD",
                mount_point="/",
                parent_disk="disk1",
                filesystem="apfs",
                is_system_disk=True,
            ),
            _v(name="Genome", mount_point="/Volumes/Genome", parent_disk="disk4"),
            _v(name="Kingston", mount_point="/Volumes/Kingston", parent_disk="disk5"),
        ]
    )
    vols = list_volumes(plat)
    names = {v.name for v in vols}
    assert "MacintoshHD" not in names
    assert names == {"Genome", "Kingston"}


# ---------------------------------------------------------------------------
# 2-4. Nebula-deliverable validation
# ---------------------------------------------------------------------------


def test_detect_validates_nebula_deliverable_happy_path(tmp_path: Path) -> None:
    """A directory with a CRAM + indexed VCF validates."""
    from genomeclaw_toolkit.prep.setup.detect import validate_nebula

    nebula = tmp_path / "MPNRGLQ2K"
    nebula.mkdir()
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"x" * 1024)
    (nebula / "MPNRGLQ2K.cram.crai").write_bytes(b"x")
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04")  # bgzip-ish header bytes
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"x")

    plat = _FakePlatform(bcftools_ok=True)
    deliverable = validate_nebula(nebula, plat)

    assert deliverable.sample_id == "MPNRGLQ2K"
    assert deliverable.has_cram is True
    assert deliverable.has_vcf is True
    assert deliverable.header_check_ok is True
    assert deliverable.total_bytes == 1024 + 1 + 4 + 1


def test_detect_rejects_nebula_dir_with_no_recognizable_files(tmp_path: Path) -> None:
    """An empty / unrecognized directory raises ``NebulaDeliverableError``."""
    from genomeclaw_toolkit.prep.setup.detect import (
        NebulaDeliverableError,
        validate_nebula,
    )

    empty = tmp_path / "nothing-here"
    empty.mkdir()
    plat = _FakePlatform()
    with pytest.raises(NebulaDeliverableError, match="nothing-here"):
        validate_nebula(empty, plat)


def test_detect_rejects_nebula_vcf_with_corrupt_header(tmp_path: Path) -> None:
    """``bcftools view -h`` non-zero → ``NebulaDeliverableError`` carrying its stderr."""
    from genomeclaw_toolkit.prep.setup.detect import (
        NebulaDeliverableError,
        validate_nebula,
    )

    nebula = tmp_path / "BADHDR"
    nebula.mkdir()
    (nebula / "BADHDR.vcf.gz").write_bytes(b"not a real bgzip")
    (nebula / "BADHDR.vcf.gz.tbi").write_bytes(b"x")

    plat = _FakePlatform(bcftools_ok=False, bcftools_stderr="not a BGZF file")
    with pytest.raises(NebulaDeliverableError, match="BGZF"):
        validate_nebula(nebula, plat)


def test_detect_skips_vcf_header_check_when_tool_unavailable(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """``bcftools_view_header`` returning ``"unavailable"`` → skip with warning, don't raise.

    Setup pre-flight runs before colima is reliably up; the docker
    daemon may not be reachable yet. Treating that as a hard failure
    creates a chicken-and-egg problem since setup is what brings the
    runtime up. The skip path writes a warning to stderr and marks
    ``header_check_ok=False`` so callers can surface it later.
    """
    from genomeclaw_toolkit.prep.setup.detect import validate_nebula

    nebula = tmp_path / "MPNRGLQ2K"
    nebula.mkdir()
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"x")
    (nebula / "MPNRGLQ2K.cram.crai").write_bytes(b"x")
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04")
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"x")

    plat = _FakePlatform(
        bcftools_status="unavailable",
        bcftools_stderr="docker daemon not reachable",
    )
    deliverable = validate_nebula(nebula, plat)

    assert deliverable.header_check_ok is False
    captured = capsys.readouterr()
    assert "skipping VCF header check" in captured.err
    assert "docker daemon not reachable" in captured.err


# ---------------------------------------------------------------------------
# 5-6. Same-disk detection
# ---------------------------------------------------------------------------


def test_detect_parent_disk_identity_same_disk_rejected(tmp_path: Path) -> None:
    """Two paths resolving to the same parent disk → ``SameDiskError``."""
    from genomeclaw_toolkit.prep.setup._types import Volume
    from genomeclaw_toolkit.prep.setup.detect import (
        SameDiskError,
        assert_different_physical_disk,
    )

    src_vol = Volume(
        name="A",
        mount_point=str(tmp_path / "A"),
        size_bytes=10**9,
        parent_disk="disk4",
        filesystem="exfat",
        is_system_disk=False,
    )
    dst_vol = Volume(
        name="B",
        mount_point=str(tmp_path / "B"),
        size_bytes=10**9,
        parent_disk="disk4",  # same parent
        filesystem="apfs",
        is_system_disk=False,
    )

    with pytest.raises(SameDiskError, match="disk4"):
        assert_different_physical_disk(src_vol, dst_vol)


def test_detect_parent_disk_identity_different_disks_accepted() -> None:
    """Different parent disks → no error."""
    from genomeclaw_toolkit.prep.setup._types import Volume
    from genomeclaw_toolkit.prep.setup.detect import assert_different_physical_disk

    src_vol = Volume(
        name="A",
        mount_point="/Volumes/A",
        size_bytes=10**9,
        parent_disk="disk4",
        filesystem="exfat",
        is_system_disk=False,
    )
    dst_vol = Volume(
        name="B",
        mount_point="/Volumes/B",
        size_bytes=10**9,
        parent_disk="disk5",
        filesystem="apfs",
        is_system_disk=False,
    )
    assert_different_physical_disk(src_vol, dst_vol)


# ---------------------------------------------------------------------------
# 13-14. Drive identity + firmware check
# ---------------------------------------------------------------------------


def test_detect_reads_drive_model_and_firmware() -> None:
    """``read_drive_identity`` returns model + firmware + capacity for the target."""
    from genomeclaw_toolkit.prep.setup._types import Volume
    from genomeclaw_toolkit.prep.setup.detect import read_drive_identity

    target = Volume(
        name="Genome",
        mount_point="/Volumes/Genome",
        size_bytes=2 * 1000**4,
        parent_disk="disk4",
        filesystem="apfs",
        is_system_disk=False,
    )
    plat = _FakePlatform(
        identities={
            "disk4": _id(
                model="Samsung Portable SSD T7 Shield",
                firmware="GBD8M3",
                capacity_gb=2000,
                bus_type="USB",
            )
        }
    )
    ident = read_drive_identity(target, plat)
    assert ident.model == "Samsung Portable SSD T7 Shield"
    assert ident.firmware == "GBD8M3"
    assert ident.capacity_gb == 2000
    assert ident.bus_type == "USB"


def test_detect_rejects_known_bad_firmware(tmp_path: Path) -> None:
    """Mechanism test: a (model, firmware) in the known-bad list raises;
    a non-listed Samsung T7 Shield firmware passes the gate.
    """
    from genomeclaw_toolkit.prep.setup._types import DriveIdentity
    from genomeclaw_toolkit.prep.setup.detect import (
        KnownBadFirmwareError,
        assert_firmware_safe,
    )

    # Synthetic known-bad data file so this test doesn't depend on real-world advisory state.
    bad_list = tmp_path / "known_bad_firmware.toml"
    bad_list.write_text(
        "[[entry]]\n"
        'model = "Test Vendor Bad Drive"\n'
        'firmware = "BAD-001"\n'
        'advisory_url = "https://example.test/advisory"\n'
    )

    bad = DriveIdentity(
        model="Test Vendor Bad Drive",
        firmware="BAD-001",
        capacity_gb=2000,
        parent_disk="disk4",
        bus_type="USB",
    )
    with pytest.raises(KnownBadFirmwareError, match="BAD-001"):
        assert_firmware_safe(bad, known_bad_path=bad_list)

    samsung_ok = DriveIdentity(
        model="Samsung Portable SSD T7 Shield",
        firmware="GBD8M3",
        capacity_gb=2000,
        parent_disk="disk4",
        bus_type="USB",
    )
    assert_firmware_safe(samsung_ok, known_bad_path=bad_list)


# ---------------------------------------------------------------------------
# 15. Computed-need pre-flight space check
# ---------------------------------------------------------------------------


def test_detect_rejects_insufficient_space_with_breakdown() -> None:
    """Target free space < computed need → InsufficientSpaceError carrying the breakdown."""
    from genomeclaw_toolkit.prep.setup.detect import (
        InsufficientSpaceError,
        SpaceBudget,
        assert_sufficient_space,
    )

    budget = SpaceBudget(
        raw_bytes=55 * 1000**3,
        reference_bytes=140 * 1000**3,
        scratch_bytes=300 * 1000**3,
        margin_bytes=50 * 1000**3,
    )
    # 100 GB free vs ~545 GB needed.
    free_bytes = 100 * 1000**3
    with pytest.raises(InsufficientSpaceError) as exc:
        assert_sufficient_space(free_bytes, budget)
    msg = str(exc.value)
    assert "raw" in msg.lower()
    assert "reference" in msg.lower()
    assert "scratch" in msg.lower()
    assert "margin" in msg.lower()
    assert "shortfall" in msg.lower()


def test_detect_accepts_sufficient_space() -> None:
    """Free space >= computed need → no error."""
    from genomeclaw_toolkit.prep.setup.detect import (
        SpaceBudget,
        assert_sufficient_space,
    )

    budget = SpaceBudget(
        raw_bytes=55 * 1000**3,
        reference_bytes=5 * 1000**3,
        scratch_bytes=300 * 1000**3,
        margin_bytes=50 * 1000**3,
    )
    free_bytes = 500 * 1000**3
    assert_sufficient_space(free_bytes, budget)


# ---------------------------------------------------------------------------
# Phase 2 — source-resolver loosening
# ---------------------------------------------------------------------------


def test_resolve_source_volume_accepts_internal_disk(tmp_path: Path) -> None:
    """Phase 2: a Nebula path on a system disk + external target is allowed.

    The same-disk safeguard still rejects the dangerous case (separate test below).
    """
    from genomeclaw_toolkit.prep.setup.detect import build_plan

    # Stage a real Nebula deliverable on the "internal" path.
    nebula = tmp_path / "internal" / "data" / "raw" / "MPNRGLQ2K"
    nebula.mkdir(parents=True)
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"x" * 256)
    (nebula / "MPNRGLQ2K.cram.crai").write_bytes(b"x")
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04stub")
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"x")
    external = tmp_path / "external"
    external.mkdir()

    plat = _FakePlatform(
        volumes=[
            _v(
                name="Macintosh HD",
                mount_point=str(tmp_path / "internal"),
                parent_disk="disk3",
                filesystem="apfs",
                is_system_disk=True,
                size_bytes=500 * 1000**3,
            ),
            _v(
                name="Genome",
                mount_point=str(external),
                parent_disk="disk4",
                filesystem="exfat",
                is_system_disk=False,
                size_bytes=500 * 1000**3,
            ),
        ],
        identities={
            "disk3": _id(model="APPLE SSD", parent_disk="disk3", bus_type="Internal"),
            "disk4": _id(
                model="Samsung Portable SSD T7 Shield",
                parent_disk="disk4",
                bus_type="USB",
            ),
        },
        bcftools_ok=True,
    )
    plan = build_plan(nebula_dir=nebula, target_mount="Genome", platform=plat)
    assert plan.target_volume.parent_disk == "disk4"
    assert plan.nebula.sample_id == "MPNRGLQ2K"


def test_resolve_source_volume_still_rejects_same_disk(tmp_path: Path) -> None:
    """Phase 2: source on disk4 + target on disk4 → SameDiskError (Phase 1 invariant intact)."""
    from genomeclaw_toolkit.prep.setup.detect import SameDiskError, build_plan

    # Both src and dst on the SAME parent_disk identifier.
    shared = tmp_path / "shared"
    shared.mkdir()
    nebula = shared / "src" / "MPNRGLQ2K"
    nebula.mkdir(parents=True)
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"x" * 256)
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04stub")
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"x")
    (shared / "dst").mkdir()

    plat = _FakePlatform(
        volumes=[
            _v(
                name="SharedSrc",
                mount_point=str(shared / "src"),
                parent_disk="disk4",
                is_system_disk=False,
            ),
            _v(
                name="SharedDst",
                mount_point=str(shared / "dst"),
                parent_disk="disk4",  # SAME parent
                is_system_disk=False,
            ),
        ],
        identities={"disk4": _id(parent_disk="disk4")},
        bcftools_ok=True,
    )
    with pytest.raises(SameDiskError, match="disk4"):
        build_plan(nebula_dir=nebula, target_mount="SharedDst", platform=plat)

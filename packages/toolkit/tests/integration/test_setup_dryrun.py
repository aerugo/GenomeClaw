"""Phase 1 — end-to-end integration tests for ``genomeclaw host setup`` dry-run.

Phase 1 is **non-destructive**: setup walks detection + validation, builds
a ``SetupPlan``, renders a preview, and exits without mutating either the
source or target drive. The destructive runner lands in Phase 2.

Tests use a fake ``Platform`` so no real ``diskutil`` / ``bcftools`` calls
fire.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakePlatform:
    def __init__(
        self,
        *,
        volumes: list[dict],
        identities: dict[str, dict],
        bcftools_ok: bool = True,
        bcftools_stderr: str = "",
    ) -> None:
        self.volumes = volumes
        self.identities = identities
        self.bcftools_ok = bcftools_ok
        self.bcftools_stderr = bcftools_stderr

    def list_volumes(self):
        from genomeclaw_toolkit.prep.setup._types import Volume

        return [Volume(**v) for v in self.volumes]

    def read_drive_identity(self, volume):
        from genomeclaw_toolkit.prep.setup._types import DriveIdentity

        return DriveIdentity(**self.identities[volume.parent_disk])

    def bcftools_view_header(self, vcf: Path):
        return ("ok" if self.bcftools_ok else "fail"), self.bcftools_stderr


@pytest.fixture
def two_disk_fixture(tmp_path: Path):
    """Two distinct fake "drives" laid out as tmp_path subdirs."""
    src_drive = tmp_path / "src_drive"
    dst_drive = tmp_path / "dst_drive"
    src_drive.mkdir()
    dst_drive.mkdir()

    # Stage a Nebula-shaped deliverable on the source drive.
    nebula = src_drive / "MPNRGLQ2K"
    nebula.mkdir()
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"x" * 4096)
    (nebula / "MPNRGLQ2K.cram.crai").write_bytes(b"x")
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04bgzipish")
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"x")

    # The destination drive starts empty.
    plat = _FakePlatform(
        volumes=[
            dict(
                name="SrcDrive",
                mount_point=str(src_drive),
                size_bytes=500 * 1000**3,
                parent_disk="disk4",
                filesystem="exfat",
                is_system_disk=False,
            ),
            dict(
                name="DstDrive",
                mount_point=str(dst_drive),
                size_bytes=2 * 1000**4,
                parent_disk="disk5",
                filesystem="exfat",
                is_system_disk=False,
            ),
        ],
        identities={
            "disk4": dict(
                model="Generic Source Drive",
                firmware="0",
                capacity_gb=500,
                parent_disk="disk4",
                bus_type="USB",
            ),
            "disk5": dict(
                model="Samsung Portable SSD T7 Shield",
                firmware="GBD8M3",
                capacity_gb=2000,
                parent_disk="disk5",
                bus_type="USB",
            ),
        },
        bcftools_ok=True,
    )

    class _Fixture:
        nebula_dir = nebula
        target_volume_path = dst_drive
        platform = plat

        def snapshot_all_hashes(self) -> dict[str, str]:
            out: dict[str, str] = {}
            for d in (src_drive, dst_drive):
                for p in sorted(d.rglob("*")):
                    if p.is_file():
                        out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
            return out

    return _Fixture()


@pytest.fixture
def same_disk_fixture(tmp_path: Path):
    """Both src and dst on the same parent_disk identifier (the danger case)."""
    drv = tmp_path / "shared_drive"
    drv.mkdir()
    (drv / "src").mkdir()
    (drv / "dst").mkdir()

    plat = _FakePlatform(
        volumes=[
            dict(
                name="SharedSrc",
                mount_point=str(drv / "src"),
                size_bytes=500 * 1000**3,
                parent_disk="disk4",
                filesystem="exfat",
                is_system_disk=False,
            ),
            dict(
                name="SharedDst",
                mount_point=str(drv / "dst"),
                size_bytes=500 * 1000**3,
                parent_disk="disk4",  # same!
                filesystem="exfat",
                is_system_disk=False,
            ),
        ],
        identities={
            "disk4": dict(
                model="Generic Drive",
                firmware="0",
                capacity_gb=500,
                parent_disk="disk4",
                bus_type="USB",
            ),
        },
    )

    class _Fixture:
        src_path = drv / "src"
        dst_path = drv / "dst"
        platform = plat

    return _Fixture()


# ---------------------------------------------------------------------------
# 7-8. Dry-run rendering + invariant
# ---------------------------------------------------------------------------


def test_dryrun_renders_complete_preview(two_disk_fixture) -> None:
    """``render(plan)`` includes partition diff, moves, creates, YAML diffs, and the WIPE phrase."""
    from genomeclaw_toolkit.prep.setup.detect import build_plan
    from genomeclaw_toolkit.prep.setup.dryrun import render

    plan = build_plan(
        nebula_dir=two_disk_fixture.nebula_dir,
        target_mount=str(two_disk_fixture.target_volume_path),
        platform=two_disk_fixture.platform,
    )
    output = render(plan)
    # Section markers we expect:
    assert "Partition" in output
    assert "Move" in output or "move" in output
    assert "scratch.raw" in output
    assert "colima" in output.lower()
    # The typed-confirmation phrase appears so the user can preview what they'd type:
    assert "WIPE " in output


def test_invD001_dryrun_does_not_mutate_source_or_target(two_disk_fixture) -> None:
    """INV-D001: dry-run must be side-effect-free across both drives."""
    from genomeclaw_toolkit.prep.setup.detect import build_plan
    from genomeclaw_toolkit.prep.setup.dryrun import render

    before = two_disk_fixture.snapshot_all_hashes()
    plan = build_plan(
        nebula_dir=two_disk_fixture.nebula_dir,
        target_mount=str(two_disk_fixture.target_volume_path),
        platform=two_disk_fixture.platform,
    )
    _ = render(plan)
    after = two_disk_fixture.snapshot_all_hashes()
    assert before == after, "dry-run mutated the filesystem"


# ---------------------------------------------------------------------------
# 9-10. CLI plumbing — interactive flow + invalid-path exit code
# ---------------------------------------------------------------------------


def test_setup_cli_with_no_args_starts_interactive_flow(
    monkeypatch: pytest.MonkeyPatch,
    two_disk_fixture,
    invoke_cli,
) -> None:
    """``genomeclaw host setup`` walks interactive prompts; emits preview; exits 0."""
    from genomeclaw_toolkit.prep.setup import detect

    monkeypatch.setattr(detect, "default_platform", lambda: two_disk_fixture.platform)

    inputs = iter([str(two_disk_fixture.nebula_dir), "DstDrive"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))

    result = invoke_cli(["host", "setup", "--dry-run"])
    assert result.exit_code == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "WIPE " in combined
    assert "scratch.raw" in combined


def test_setup_cli_force_reset_with_source_and_target_runs_unattended(
    monkeypatch: pytest.MonkeyPatch,
    two_disk_fixture,
    invoke_cli,
) -> None:
    """``host setup --force-reset --source X --target-volume Y --dry-run`` is fully unattended.

    Drives the real ``run_interactive`` end-to-end (no stubs) so this
    is a true integration check: the CLI flags propagate, the prompts
    that would normally read stdin never fire, and the destructive
    runner is gated by --dry-run so no actual diskutil call lands.
    """
    from genomeclaw_toolkit.prep.setup import detect

    monkeypatch.setattr(detect, "default_platform", lambda: two_disk_fixture.platform)

    def _no_input(*_a, **_kw):
        raise AssertionError("builtins.input must not be called under --force-reset + flags")

    monkeypatch.setattr("builtins.input", _no_input)

    result = invoke_cli(
        [
            "--yes",  # Phase 6: required for --force-reset on non-TTY (incl. pytest invoke_cli).
            "host",
            "setup",
            "--force-reset",
            "--dry-run",
            "--source",
            str(two_disk_fixture.nebula_dir),
            "--target-volume",
            "DstDrive",
        ]
    )

    assert result.exit_code == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "WIPE " in combined


def test_setup_cli_with_invalid_nebula_path_exits_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    two_disk_fixture,
    tmp_path: Path,
    invoke_cli,
) -> None:
    """Invalid Nebula path → exit 2 (usage error) with validation error on stderr."""
    from genomeclaw_toolkit.prep.setup import detect

    monkeypatch.setattr(detect, "default_platform", lambda: two_disk_fixture.platform)

    bogus = tmp_path / "does-not-exist"
    inputs = iter([str(bogus), "DstDrive"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))

    result = invoke_cli(["host", "setup", "--dry-run"])
    assert result.exit_code == 2, result.stderr
    combined = result.stdout + result.stderr
    assert "does-not-exist" in combined or "not found" in combined.lower()


# ---------------------------------------------------------------------------
# Cross-cutting invariants
# ---------------------------------------------------------------------------


def test_invD001_setup_invocation_does_not_mutate_source_or_target(
    monkeypatch: pytest.MonkeyPatch,
    two_disk_fixture,
    invoke_cli,
) -> None:
    """INV-D001 (CLI level): a full ``host setup --dry-run`` interactive pass is side-effect-free."""
    from genomeclaw_toolkit.prep.setup import detect

    monkeypatch.setattr(detect, "default_platform", lambda: two_disk_fixture.platform)
    inputs = iter([str(two_disk_fixture.nebula_dir), "DstDrive"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))

    before = two_disk_fixture.snapshot_all_hashes()
    result = invoke_cli(["host", "setup", "--dry-run"])
    after = two_disk_fixture.snapshot_all_hashes()
    assert result.exit_code == 0, result.stderr
    assert before == after, "CLI setup mutated the filesystem"


def test_invP001_setup_makes_zero_outbound_calls(
    monkeypatch: pytest.MonkeyPatch,
    two_disk_fixture,
    httpserver,
    invoke_cli,
) -> None:
    """INV-P001: full setup interactive flow makes zero HTTP calls."""
    from genomeclaw_toolkit.prep.setup import detect

    monkeypatch.setattr(detect, "default_platform", lambda: two_disk_fixture.platform)
    inputs = iter([str(two_disk_fixture.nebula_dir), "DstDrive"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))

    result = invoke_cli(["host", "setup", "--dry-run"])
    assert result.exit_code == 0, result.stderr
    assert len(httpserver.log) == 0


def test_setup_cli_rejects_same_disk_source_and_target(
    monkeypatch: pytest.MonkeyPatch,
    same_disk_fixture,
    invoke_cli,
) -> None:
    """Source and target on the same parent_disk → CLI exits 2 with same-disk error."""
    from genomeclaw_toolkit.prep.setup import detect

    nebula = same_disk_fixture.src_path / "MPNRGLQ2K"
    nebula.mkdir()
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"x" * 1024)
    (nebula / "MPNRGLQ2K.cram.crai").write_bytes(b"x")
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04bgz")
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"x")

    monkeypatch.setattr(detect, "default_platform", lambda: same_disk_fixture.platform)
    inputs = iter([str(nebula), "SharedDst"])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))

    result = invoke_cli(["host", "setup", "--dry-run"])
    assert result.exit_code == 2, result.stderr
    combined = result.stdout + result.stderr
    assert "disk4" in combined or "same" in combined.lower()

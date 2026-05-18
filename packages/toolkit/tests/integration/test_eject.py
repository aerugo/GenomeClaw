"""Phase 5 — ``genomeclaw host eject`` subcommand tests.

Eject sequence: refuse if a pipeline is running, then ``colima stop``,
then remove the drive's colima.yaml mount entry (Slice 2 of
host-mount-lifecycle), then ``diskutil eject /Volumes/Genome_Work``.
Tests inject a fake subprocess runner so no real ``colima`` /
``diskutil`` shellouts fire.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


class _FakeRunner:
    """Records each subprocess invocation; injects per-call return codes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[tuple[str, ...], tuple[int, str, str]] = {}
        self.docker_ps_running: bool = False

    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        key = tuple(cmd)
        self.calls.append(key)
        # Synthesised default for `docker ps`:
        if cmd[:2] == ["docker", "ps"]:
            stdout = "CONTAINER_ID\nfake-container\n" if self.docker_ps_running else ""
            return 0, stdout, ""
        return self.responses.get(key, (0, "", ""))


def test_eject_refuses_when_pipeline_running() -> None:
    """Pipeline still running → ``PipelineRunningError``; no destructive op."""
    from genomeclaw_toolkit.prep.eject import PipelineRunningError, eject

    runner = _FakeRunner()
    runner.docker_ps_running = True

    with pytest.raises(PipelineRunningError, match="container"):
        eject(runner=runner)

    # Only `docker ps` was called — no colima stop, no diskutil eject.
    assert all(call[0] == "docker" for call in runner.calls)
    assert not any("colima" in call[0] for call in runner.calls)
    assert not any("diskutil" in call[0] for call in runner.calls)


def test_eject_stops_colima_then_ejects_drive() -> None:
    """No pipeline running → ``colima stop`` → ``diskutil eject`` in order."""
    from genomeclaw_toolkit.prep.eject import eject

    runner = _FakeRunner()
    rc = eject(runner=runner, drive="/Volumes/Genome_Work")
    assert rc == 0

    # Find the ordered commands in the call log.
    commands = [call[0] + (" " + call[1] if len(call) > 1 else "") for call in runner.calls]
    # Expect: docker ps (the check), colima stop, diskutil eject.
    assert any(c.startswith("docker ps") for c in commands)
    colima_idx = next(i for i, c in enumerate(commands) if c.startswith("colima stop"))
    eject_idx = next(i for i, c in enumerate(commands) if c.startswith("diskutil eject"))
    assert colima_idx < eject_idx, f"colima_stop must come before diskutil_eject: {commands}"


def test_eject_surfaces_diskutil_error_clearly() -> None:
    """``diskutil eject`` returns non-zero → typed ``EjectError`` with stderr captured."""
    from genomeclaw_toolkit.prep.eject import EjectError, eject

    runner = _FakeRunner()
    runner.responses[("diskutil", "eject", "/Volumes/Genome_Work")] = (
        1,
        "",
        "diskutil: drive not mounted",
    )

    with pytest.raises(EjectError, match="drive not mounted"):
        eject(runner=runner, drive="/Volumes/Genome_Work")


def test_eject_with_force_skips_pipeline_check() -> None:
    """``force=True`` bypasses the running-pipeline guard.

    Useful when a pipeline crashed and left a zombie container the
    user wants to push past. Documented as a deliberate footgun.
    """
    from genomeclaw_toolkit.prep.eject import eject

    runner = _FakeRunner()
    runner.docker_ps_running = True

    rc = eject(runner=runner, drive="/Volumes/Genome_Work", force=True)
    assert rc == 0
    assert any("colima" in call[0] for call in runner.calls)
    assert any("diskutil" in call[0] for call in runner.calls)


# ---------------------------------------------------------------------------
# Slice 2 of host-mount-lifecycle — eject also removes the colima mount.
# ---------------------------------------------------------------------------


def _write_colima_yaml(path: Path, mounts: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"mounts": mounts}, sort_keys=False))


def test_eject_removes_drive_from_colima_yaml(tmp_path: Path) -> None:
    """After eject, the drive's entry is gone from colima.yaml.

    Without this, the next ``colima start`` hits the
    ``mkdir /Volumes/<drive>: permission denied`` failure that bit the
    project owner on 2026-05-14.
    """
    from genomeclaw_toolkit.prep.eject import eject

    cfg = tmp_path / "colima.yaml"
    _write_colima_yaml(
        cfg,
        [
            {"location": "/Volumes/Genome_Work", "writable": True},
            {"location": "/Users/hugi/GitRepos", "writable": True},
        ],
    )
    runner = _FakeRunner()

    rc = eject(
        runner=runner,
        drive="/Volumes/Genome_Work",
        colima_config_path=cfg,
    )
    assert rc == 0

    data = yaml.safe_load(cfg.read_text())
    locations = [m["location"] for m in data["mounts"]]
    assert "/Volumes/Genome_Work" not in locations
    assert "/Users/hugi/GitRepos" in locations, (
        "eject must remove only the target drive, not other user mounts"
    )


def test_eject_skips_colima_yaml_edit_when_config_missing(tmp_path: Path) -> None:
    """No colima.yaml on disk → eject still succeeds (no-op on the edit step).

    Fresh user who runs eject without ever having run setup shouldn't
    see a crash. The diskutil + colima-stop steps still fire.
    """
    from genomeclaw_toolkit.prep.eject import eject

    cfg = tmp_path / "nonexistent" / "colima.yaml"
    runner = _FakeRunner()

    rc = eject(
        runner=runner,
        drive="/Volumes/Genome_Work",
        colima_config_path=cfg,
    )
    assert rc == 0
    assert not cfg.exists()


def test_eject_mount_removal_idempotent_on_retry(tmp_path: Path) -> None:
    """Running eject twice in a row against the same drive is a no-op the
    second time (the drive's mount is already gone after the first call).
    """
    from genomeclaw_toolkit.prep.eject import eject

    cfg = tmp_path / "colima.yaml"
    _write_colima_yaml(
        cfg,
        [
            {"location": "/Volumes/Genome_Work", "writable": True},
            {"location": "/Volumes/Other_Drive", "writable": True},
        ],
    )
    runner = _FakeRunner()

    # First call: removes the entry.
    eject(runner=runner, drive="/Volumes/Genome_Work", colima_config_path=cfg)

    # Second call: entry is already gone; no error.
    runner2 = _FakeRunner()
    rc = eject(runner=runner2, drive="/Volumes/Genome_Work", colima_config_path=cfg)
    assert rc == 0

    data = yaml.safe_load(cfg.read_text())
    locations = [m["location"] for m in data["mounts"]]
    assert "/Volumes/Genome_Work" not in locations
    assert "/Volumes/Other_Drive" in locations

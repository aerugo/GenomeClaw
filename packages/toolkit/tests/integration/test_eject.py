"""Phase 5 — ``genomeclaw host eject`` subcommand tests.

Eject sequence: refuse if a pipeline is running, then ``colima stop``,
then ``diskutil eject /Volumes/Genome_Work``. Tests inject a fake
subprocess runner so no real ``colima`` / ``diskutil`` shellouts fire.
"""

from __future__ import annotations

import pytest


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

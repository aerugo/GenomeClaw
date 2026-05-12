"""``genomeclaw host eject`` — stop colima + diskutil eject the drive.

Refuses if a pipeline is still running (a toolkit container is up). The
``force=True`` escape hatch is for the rare case where a crashed
orchestrator left a zombie container the user wants to push past.

Tests inject a fake subprocess runner; production uses the default
``_SubprocessRunner`` that shells out to the real ``docker`` /
``colima`` / ``diskutil`` binaries.
"""

from __future__ import annotations

import subprocess
from typing import Protocol


class EjectError(Exception):
    """Base for eject-related failures."""


class PipelineRunningError(EjectError):
    """A toolkit container is up; refuse to eject without ``force=True``."""


class _Runner(Protocol):
    def run(self, cmd: list[str]) -> tuple[int, str, str]: ...


class _SubprocessRunner:
    """Default runner: real ``subprocess.run``."""

    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(cmd, capture_output=True, check=False)
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        return proc.returncode, stdout, stderr


def eject(
    *,
    drive: str = "/Volumes/Genome_Work",
    force: bool = False,
    runner: _Runner | None = None,
) -> int:
    """Stop colima + diskutil eject ``drive``.

    Returns CLI-style exit code (0 success). Raises ``PipelineRunningError``
    if a toolkit container is up (and ``force=False``); raises ``EjectError``
    on any subprocess failure.
    """
    runner = runner or _SubprocessRunner()

    if not force:
        rc, stdout, _ = runner.run(
            ["docker", "ps", "--filter", "ancestor=genomeclaw/toolkit:dev", "--format", "{{.ID}}"]
        )
        if rc == 0 and stdout.strip():
            running_ids = [ln for ln in stdout.splitlines() if ln.strip()]
            raise PipelineRunningError(
                f"pipeline still running in container(s) {', '.join(running_ids)}; "
                "wait for it to finish or `docker kill <id>` deliberately, "
                "then retry. (Use `eject --force` to bypass — at the cost of "
                "interrupting any in-flight run.)"
            )

    rc, _stdout, stderr = runner.run(["colima", "stop"])
    # `colima stop` exits 0 when stopping or already-stopped; non-zero is
    # a real failure (e.g., colima not installed). Surface it.
    if rc != 0 and "not running" not in stderr.lower():
        raise EjectError(f"colima stop failed (rc={rc}): {stderr.strip()}")

    rc, _stdout, stderr = runner.run(["diskutil", "eject", drive])
    if rc != 0:
        raise EjectError(f"diskutil eject failed (rc={rc}): {stderr.strip()}")

    return 0


__all__ = ["EjectError", "PipelineRunningError", "eject"]

"""Downstream-tool runner protocol — the seam for chaining external CLIs.

GenomeClaw's pipeline orchestrates bcftools, vcfanno, vep, mosdepth,
samtools, and other binaries. Today each wrapper in
``packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py`` etc.
hand-rolls its own ``subprocess.run`` invocation, stderr handling, and
version capture. That's fine for the orchestrator layer but fragile
when the CLI needs to inject test doubles or capture streaming output.

This module defines ``ToolRunner`` as the Protocol that future
orchestrator-side wrappers can adopt. The default
``SubprocessToolRunner`` is the thin ``subprocess.run`` wrapper that
matches today's behaviour. Tests inject a ``FakeToolRunner`` via
``AppContext.tool_runner`` to assert "this command invoked ``vcfanno``
with these args" without spawning a real process.

Phase 1 lands the Protocol + default; refactoring the existing
``prep/_*.py`` wrappers to adopt the Protocol is a follow-up plan, not
this one's scope. The Protocol exists here so the seam is established
from day one — the future refactor is a clean drop-in.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of a single tool invocation.

    Attributes:
        returncode: The process exit status (0 = success).
        stdout: The process's stdout bytes, decoded UTF-8 with
            replacement for malformed sequences.
        stderr: The process's stderr bytes, decoded similarly.
    """

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Return ``True`` iff the process exited zero."""
        return self.returncode == 0


@runtime_checkable
class ToolRunner(Protocol):
    """Pluggable subprocess invoker for downstream binaries.

    Implementations must be deterministic for the same ``(argv, cwd,
    env)`` triple — that's what makes test fakes meaningful.
    """

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ToolResult:
        """Invoke ``argv[0]`` with ``argv[1:]`` and capture its result.

        Args:
            argv: The command and its arguments. ``argv[0]`` is
                resolved via ``$PATH``.
            cwd: Optional working directory. ``None`` inherits the
                parent's CWD.
            env: Optional environment overrides. When ``None``, the
                parent's environment is inherited unchanged.

        Returns:
            A ``ToolResult`` capturing the exit code + decoded stdout
            + decoded stderr.
        """
        ...


class SubprocessToolRunner:
    """Default ``ToolRunner`` backed by ``subprocess.run``.

    No streaming, no resume, no fancy error handling — just "run the
    binary, capture both streams, return the result." Orchestrators
    that need streaming stderr (vcfanno, for example) layer that on
    top via their own ``Popen`` calls; ``ToolRunner`` is the contract
    for the simple capture-and-return case.
    """

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ToolResult:
        """Run ``argv`` via ``subprocess.run`` and capture both streams."""
        proc = subprocess.run(
            list(argv),
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
        )
        return ToolResult(
            returncode=proc.returncode,
            stdout=proc.stdout.decode("utf-8", errors="replace"),
            stderr=proc.stderr.decode("utf-8", errors="replace"),
        )


def default_tool_runner() -> ToolRunner:
    """Return the default ``ToolRunner`` instance used in production.

    Factory function so tests can monkey-patch this single seam to
    inject a fake without reaching into ``AppContext`` construction.
    """
    return SubprocessToolRunner()


__all__ = [
    "SubprocessToolRunner",
    "ToolResult",
    "ToolRunner",
    "default_tool_runner",
]

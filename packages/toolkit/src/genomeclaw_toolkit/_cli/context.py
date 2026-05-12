"""Application context carried through Typer's ``Context.obj``.

Every command receives the same ``AppContext`` instance via Typer's
context-injection mechanism. The context is the single source of truth
for "what mode is this command running in?" — output format, verbosity,
TTY assumptions, the tool-runner to use for downstream binaries.

Centralising mode resolution here means commands never look at
``sys.stdout.isatty()`` directly, never read environment variables
for behaviour, and never instantiate ``rich.console.Console`` ad hoc.
That discipline is what keeps the migration from sprawling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from genomeclaw_toolkit._cli.output import OutputMode, Verbosity

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.tool import ToolRunner


@dataclass(slots=True)
class AppContext:
    """Per-invocation CLI state shared across every command.

    Attributes:
        output_mode: ``rich`` for human-rendered output (auto-detected
            from TTY) or ``json`` when the user passed ``--json``.
        verbosity: Suppresses (``quiet``) or amplifies (``debug``)
            log output. Independent of ``output_mode``.
        assume_yes: When ``True``, destructive operations skip their
            confirmation prompt. Required for non-TTY invocation of
            ``host setup`` / ``host eject``.
        debug: When ``True``, errors include their Python traceback;
            in JSON mode the traceback lands in ``ErrorDetail.traceback``.
        tool_runner: The runner used for downstream-binary invocation.
            Default is ``SubprocessToolRunner``; tests inject fakes.
    """

    output_mode: OutputMode = OutputMode.RICH
    verbosity: Verbosity = Verbosity.NORMAL
    assume_yes: bool = False
    debug: bool = False
    tool_runner: ToolRunner | None = field(default=None)

    @property
    def is_json(self) -> bool:
        """Return ``True`` iff the caller requested JSON output."""
        return self.output_mode is OutputMode.JSON

    @property
    def is_quiet(self) -> bool:
        """Return ``True`` iff non-essential output should be suppressed."""
        return self.verbosity is Verbosity.QUIET


__all__ = ["AppContext"]

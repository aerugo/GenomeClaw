"""Shared ``rich.console.Console`` factory.

Every rich-rendered output in the CLI flows through the singleton
returned by ``get_console``. The singleton is constructed lazily on
first access so tests can override it before any command runs — that
override path is what makes deterministic rich-output testing
possible without mocking ANSI bytes.

The console writes to ``stderr`` by default, NOT ``stdout``. In JSON
output mode, ``stdout`` is reserved for the structured envelope;
everything else (progress, log, status, errors) goes to ``stderr``.
Rich rendering follows the same discipline so a rich-mode run can be
piped to a JSON-consumer without polluting the JSON.

Color and TTY detection are delegated to rich's built-in heuristics
(``Console.is_terminal``). The ``--no-color`` / ``--force-color`` CLI
flags toggle the explicit overrides; otherwise rich detects whatever
the underlying stream supports.
"""

from __future__ import annotations

import sys
from typing import Literal

from rich.console import Console

_CONSOLE: Console | None = None


def get_console() -> Console:
    """Return the process-wide ``Console`` singleton, constructing on first call.

    The default console writes to ``stderr`` and lets rich auto-detect
    TTY + colour support. Tests inject a recording console via
    ``set_console`` before invoking the CLI.
    """
    global _CONSOLE
    if _CONSOLE is None:
        _CONSOLE = Console(stderr=True)
    return _CONSOLE


def set_console(console: Console) -> None:
    """Replace the process-wide ``Console`` (tests + explicit colour overrides).

    Args:
        console: The replacement instance. Subsequent ``get_console``
            calls return this until another ``set_console`` (or
            ``reset_console``) lands.
    """
    global _CONSOLE
    _CONSOLE = console


def reset_console() -> None:
    """Drop the cached console so the next ``get_console`` reconstructs from scratch."""
    global _CONSOLE
    _CONSOLE = None


def configure_console(
    *,
    color: Literal["auto", "always", "never"] = "auto",
) -> Console:
    """Build and install the process-wide console with the requested colour policy.

    Called once from the top-level Typer callback after ``--no-color``
    / ``--force-color`` are parsed.

    Args:
        color: ``"auto"`` to let rich detect TTY; ``"always"`` for
            ``--force-color``; ``"never"`` for ``--no-color``.

    Returns:
        The newly-installed console (same as a subsequent ``get_console`` call).
    """
    force_terminal: bool | None
    no_color: bool
    if color == "always":
        force_terminal = True
        no_color = False
    elif color == "never":
        force_terminal = None
        no_color = True
    else:
        force_terminal = None
        no_color = False
    console = Console(
        stderr=True,
        force_terminal=force_terminal,
        no_color=no_color,
        # ``soft_wrap=True`` avoids rich's hard line-wrap which fights
        # with terminal resize. Rich still wraps logical content within
        # tables / panels; this just disables wrapping of plain text.
        soft_wrap=True,
    )
    set_console(console)
    return console


def stdout_is_tty() -> bool:
    """Return ``True`` iff stdout is a real terminal.

    Used by the top-level callback to default ``OutputMode`` to ``RICH``
    on TTY and ``JSON`` is never automatic — agents must opt in with
    ``--json``. See the rich-cli development plan's "Output mode matrix"
    section under ``docs/plans/active/rich-cli/`` for the full table.
    """
    return sys.stdout.isatty()


__all__ = [
    "configure_console",
    "get_console",
    "reset_console",
    "set_console",
    "stdout_is_tty",
]

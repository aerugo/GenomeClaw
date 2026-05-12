"""``--watch`` mode wrapper around rich's ``Live`` display.

Used by ``host doctor --watch`` and ``runs list --watch`` for periodic
refresh of read-only views. Non-TTY contexts (CI logs, piped output)
degrade gracefully to occasional frame updates via rich's built-in
``transient=False`` semantics.

The wrapper is deliberately small — it accepts a "render once" callable
that returns a rich-renderable, plus a refresh interval, and drives the
display loop. Commands stay clean of ``Live`` plumbing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.live import Live

from genomeclaw_toolkit._cli.console import get_console

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import RenderableType


def watch_loop(
    render: Callable[[], RenderableType],
    *,
    refresh_interval_sec: float = 2.0,
    max_iterations: int | None = None,
) -> None:
    """Drive a rich ``Live`` loop, refreshing ``render()`` periodically.

    Args:
        render: Callable producing a fresh renderable every iteration.
            Called immediately for the first frame, then once per
            ``refresh_interval_sec``.
        refresh_interval_sec: Seconds between refreshes.
        max_iterations: Optional cap (used by tests). ``None`` runs
            indefinitely until ``KeyboardInterrupt``; the caller's
            top-level exception boundary converts the signal to a
            clean exit (code 130).

    Raises:
        KeyboardInterrupt: Bubbled up to the caller so the top-level
            CLI exception boundary handles the SIGINT exit code.
    """
    console = get_console()
    iterations = 0
    with Live(render(), console=console, refresh_per_second=4, transient=False) as live:
        while max_iterations is None or iterations < max_iterations:
            time.sleep(refresh_interval_sec)
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                # One last update before exit so tests see the final frame.
                live.update(render())
                return
            live.update(render())


__all__ = ["watch_loop"]

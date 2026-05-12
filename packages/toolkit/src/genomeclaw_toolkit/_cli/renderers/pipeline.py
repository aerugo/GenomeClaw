r"""Renderers for the ``pipeline`` command group.

Two factories — :func:`make_pipeline_rich_renderer` and
:func:`make_pipeline_ndjson_emitter` — return event-consumer callables
that the command hands to each orchestrator's ``progress_callback``.

Rich mode renders one :class:`rich.panel.Panel` per phase boundary;
JSON mode writes compact NDJSON to a sink. Both consume the same
:class:`~genomeclaw_toolkit.prep._events._ProgressEvent` stream — the
factory you pick determines the surface, not the contract.

The NDJSON envelope convention pinned in Phase 4 carries over: the
caller writes a first-line ``{"cli_output_schema_version": ...,
"command": ..., "stream": true}`` line *before* invoking the
orchestrator; every subsequent line is a raw event written by the
emitter returned here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.text import Text

from genomeclaw_toolkit._cli.console import get_console
from genomeclaw_toolkit.prep._events import (
    PhaseComplete,
    PhaseFailed,
    PhaseStart,
    PipelineComplete,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

    from genomeclaw_toolkit.prep._events import _ProgressEvent


_PHASE_STYLE: dict[str, str] = {
    "ingest": "cyan",
    "normalize": "magenta",
    "annotate": "green",
    "materialize": "yellow",
}


def _format_duration(seconds: float) -> str:
    """Format a wall-clock duration as a short ``hh:mm:ss`` / ``m:ss`` / ``s.s`` string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_int = int(seconds % 60)
    return f"{hours}h{minutes:02d}m{seconds_int:02d}s"


def make_pipeline_rich_renderer() -> Callable[[_ProgressEvent], None]:
    """Build a ``progress_callback`` that renders rich Panels per phase.

    Each :class:`PhaseStart` emits a header-style Panel; each
    :class:`PhaseComplete` emits a completion Panel with duration;
    :class:`PhaseFailed` flips the colour to red. :class:`PipelineComplete`
    closes with a summary footer.

    Returns:
        A callable accepting any :class:`_ProgressEvent` subclass. Events
        outside the pipeline-stage hierarchy are silently ignored — this
        renderer is scoped to phase + pipeline events.
    """
    console = get_console()

    def _on_event(event: _ProgressEvent) -> None:
        if isinstance(event, PhaseStart):
            style = _PHASE_STYLE.get(event.phase, "white")
            console.print(
                Panel(
                    Text(f"▶ {event.phase}", style=f"bold {style}"),
                    title_align="left",
                    border_style=style,
                    expand=False,
                )
            )
            return
        if isinstance(event, PhaseComplete):
            style = _PHASE_STYLE.get(event.phase, "white")
            console.print(
                Panel(
                    Text(
                        f"✓ {event.phase} — {_format_duration(event.duration_sec)}",
                        style=f"bold {style}",
                    ),
                    title_align="left",
                    border_style=style,
                    expand=False,
                )
            )
            return
        if isinstance(event, PhaseFailed):
            console.print(
                Panel(
                    Text(
                        f"✗ {event.phase} — {event.error_type}: {event.message}",
                        style="bold red",
                    ),
                    title_align="left",
                    border_style="red",
                    expand=False,
                )
            )
            return
        if isinstance(event, PipelineComplete):
            console.print(
                Panel(
                    Text(
                        f"pipeline complete · {_format_duration(event.duration_sec)} · "
                        f"{event.run_dir}",
                        style="bold green",
                    ),
                    title_align="left",
                    border_style="green",
                    expand=False,
                )
            )
            return

    return _on_event


def make_pipeline_ndjson_emitter(sink: TextIO) -> Callable[[_ProgressEvent], None]:
    """Build a ``progress_callback`` that writes one NDJSON line per event.

    Args:
        sink: Writable text stream (typically ``sys.stdout``).

    Returns:
        A callable accepting any :class:`_ProgressEvent` subclass.
    """

    def _on_event(event: _ProgressEvent) -> None:
        sink.write(json.dumps(event.to_json_dict(), separators=(",", ":"), ensure_ascii=False))
        sink.write("\n")
        sink.flush()

    return _on_event


__all__ = [
    "make_pipeline_ndjson_emitter",
    "make_pipeline_rich_renderer",
]

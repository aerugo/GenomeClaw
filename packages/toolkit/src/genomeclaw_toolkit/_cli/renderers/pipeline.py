r"""Renderers for the ``pipeline`` command group.

Two factories — :func:`make_pipeline_rich_renderer` and
:func:`make_pipeline_ndjson_emitter` — return event-consumer callables
that the command hands to each orchestrator's ``progress_callback``.

Rich mode renders a live :class:`rich.progress.Progress` instance with
one indeterminate task per phase: each phase gets a spinner + colored
name + an elapsed-time counter that updates while the orchestrator
runs. When the phase finishes the task converts to a "✓ done in X" row
and the next phase's task spins up below it. ``PipelineComplete`` adds
a final footer Panel.

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
import threading
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

from genomeclaw_toolkit._cli.console import get_console
from genomeclaw_toolkit.prep._events import (
    PhaseComplete,
    PhaseFailed,
    PhaseMessage,
    PhaseStart,
    PipelineComplete,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

    from rich.progress import TaskID

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


def make_pipeline_progress() -> Progress:
    """Construct the rich :class:`Progress` used by pipeline commands.

    One task per phase, all indeterminate (no total — the orchestrators
    don't expose row counts at this layer). The spinner + elapsed
    counter give the user continuous "still alive" feedback even when
    the orchestrator is between events (e.g. the multi-minute sha256
    of a multi-GB source VCF during ingest, or the vcfanno run during
    annotate).
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}[/bold]"),
        TimeElapsedColumn(),
        console=get_console(),
        transient=False,
        expand=False,
    )


def make_pipeline_rich_renderer(
    progress: Progress,
) -> Callable[[_ProgressEvent], None]:
    """Build a ``progress_callback`` that drives a live ``Progress`` panel.

    ``PhaseStart`` adds an indeterminate task (spinner + elapsed timer)
    that keeps animating while the orchestrator works. ``PhaseComplete``
    flips that row to ``✓ {phase} — Xm Ys`` and stops the spinner.
    ``PhaseFailed`` flips it red. ``PipelineComplete`` emits a final
    summary Panel below the progress region.

    Args:
        progress: An active :class:`Progress` (already entered via
            ``with progress:``).

    Returns:
        A callable accepting any :class:`_ProgressEvent` subclass.
        Events outside the pipeline-stage hierarchy are silently
        ignored — this renderer is scoped to phase + pipeline events.
    """
    console = get_console()
    task_ids: dict[str, TaskID] = {}

    def _on_event(event: _ProgressEvent) -> None:
        if isinstance(event, PhaseStart):
            style = _PHASE_STYLE.get(event.phase, "white")
            task_id = progress.add_task(
                f"[{style}]▶ {event.phase}[/{style}]",
                total=None,  # indeterminate — spinner + elapsed only
            )
            task_ids[event.phase] = task_id
            return
        if isinstance(event, PhaseMessage):
            # Beat messages from inside a running phase. Print above the
            # live progress region via the Progress's own console — rich
            # serialises this so the spinner stays smooth and the beat
            # line scrolls in beneath previously-emitted output. Style
            # the prefix in the same per-phase colour as the task row so
            # the user can scan-link beats to their owning phase even
            # when phases overlap in the future.
            style = _PHASE_STYLE.get(event.phase, "white")
            progress.console.print(
                f"  [dim {style}]\u21b3 {event.phase}:[/dim {style}] {event.message}",
                highlight=False,
            )
            return
        if isinstance(event, PhaseComplete):
            style = _PHASE_STYLE.get(event.phase, "white")
            tid = task_ids.get(event.phase)
            if tid is not None:
                progress.update(
                    tid,
                    description=(
                        f"[{style}]✓ {event.phase}"
                        f"[/{style}] · {_format_duration(event.duration_sec)}"
                    ),
                    completed=1,
                    total=1,
                )
                progress.stop_task(tid)
            return
        if isinstance(event, PhaseFailed):
            tid = task_ids.get(event.phase)
            if tid is not None:
                progress.update(
                    tid,
                    description=(
                        f"[red]✗ {event.phase}[/red] · "
                        f"{event.error_type}: {event.message}"
                    ),
                )
                progress.stop_task(tid)
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

    Thread safety: annotate-vcfanno runs per-chrom vcfanno shards in
    parallel via a :class:`~concurrent.futures.ThreadPoolExecutor`, so
    ``emit_beat`` may be called concurrently from multiple worker
    threads. The lock here guarantees one event lands as one whole line
    on the sink; without it, two writers could interleave bytes mid-
    object and corrupt the NDJSON stream.
    """
    write_lock = threading.Lock()

    def _on_event(event: _ProgressEvent) -> None:
        line = json.dumps(event.to_json_dict(), separators=(",", ":"), ensure_ascii=False) + "\n"
        with write_lock:
            sink.write(line)
            sink.flush()

    return _on_event


__all__ = [
    "make_pipeline_ndjson_emitter",
    "make_pipeline_progress",
    "make_pipeline_rich_renderer",
]

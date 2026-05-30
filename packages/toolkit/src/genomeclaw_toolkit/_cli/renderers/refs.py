r"""Rich renderers for the ``refs`` command group.

* :func:`render_refs_list` — release-set classification table.
* :func:`render_refs_verify` — bgzip-EOF integrity sweep result.
* :func:`render_refs_info` — single-source detail with per-file rows.
* :func:`make_fetch_rich_renderer` — translate ``ProgressEvent``\ s into
  ``rich.progress.Progress`` task updates for ``refs fetch``.
* :func:`make_fetch_ndjson_emitter` — write one JSON object per line to
  a stream for ``refs fetch --json``.

All three view renderers write through the shared
:func:`genomeclaw_toolkit._cli.console.get_console`; the two
``make_*`` factories return event-consumer callables that the command
hands to the orchestrator's ``progress_callback`` hook.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from genomeclaw_toolkit._cli.console import get_console
from genomeclaw_toolkit.prep._events import (
    FileComplete,
    FileFailed,
    FileProgress,
    FileStart,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

    from genomeclaw_toolkit._cli.commands.refs import (
        RefsInfoPayload,
        RefsListPayload,
        RefsVerifyPayload,
    )
    from genomeclaw_toolkit.prep._events import _ProgressEvent


_STATUS_STYLE: dict[str, str] = {
    "OK": "green",
    "partial": "yellow",
    "missing": "red",
}

# Threshold for "show in MB vs GB" in human-readable byte formatting.
_BYTES_PER_GB = 1_073_741_824
_BYTES_PER_MB = 1_048_576
_BYTES_PER_KB = 1024


def _human_bytes(n: int | None) -> str:
    """Format a byte count as a short human-readable string."""
    if n is None:
        return "—"
    if n >= _BYTES_PER_GB:
        return f"{n / _BYTES_PER_GB:.1f} GB"
    if n >= _BYTES_PER_MB:
        return f"{n / _BYTES_PER_MB:.1f} MB"
    if n >= _BYTES_PER_KB:
        return f"{n / _BYTES_PER_KB:.1f} KB"
    return f"{n} B"


def render_refs_list(payload: RefsListPayload) -> None:
    """Render the release-set classification table."""
    console = get_console()
    title = f"Reference datasets (release set '{payload.release_set}')"
    if not payload.sources:
        console.print(
            Panel(Text("(none configured)", style="dim"), title=title, title_align="left")
        )
        return
    table = Table(
        title=title,
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Source")
    table.add_column("Release")
    table.add_column("Status")
    table.add_column("Files", justify="right")
    table.add_column("Notes", overflow="fold")
    for src in payload.sources:
        present_n = len(src.present_files)
        missing_n = len(src.missing_files)
        total = present_n + missing_n
        notes: list[str] = []
        if missing_n:
            notes.append(f"{missing_n} missing")
        if src.on_disk_release and src.on_disk_release != src.expected_release:
            notes.append(f"on disk: {src.on_disk_release}")
        table.add_row(
            src.source,
            src.expected_release,
            Text(src.status, style=_STATUS_STYLE.get(src.status, "")),
            f"{present_n}/{total}",
            ", ".join(notes),
        )
    console.print(table)


def render_refs_verify(payload: RefsVerifyPayload) -> None:
    """Render the bgzip-EOF integrity sweep result + cross-dataset warnings."""
    console = get_console()
    title = f"Bgzip integrity sweep (release set '{payload.release_set}')"
    if payload.failures:
        n_failures = len(payload.failures)
        table = Table(
            title=f"{title} — {n_failures} failure(s) of {payload.files_checked} checked",
            title_style="bold",
            title_justify="left",
            show_header=True,
            header_style="bold",
            expand=False,
        )
        table.add_column("Source")
        table.add_column("File", overflow="fold")
        table.add_column("Reason")
        for f in payload.failures:
            table.add_row(f.source, f.relpath, Text(f.reason, style="red"))
        console.print(table)
    else:
        console.print(
            Panel(
                Text(f"All {payload.files_checked} bgzipped files intact.", style="green"),
                title=title,
                title_align="left",
            )
        )

    # Cross-dataset alignment warnings (bioreview-small-fixes Fix 2).
    # Informational only — they do not affect exit code.
    if payload.alignment_warnings:
        for warning in payload.alignment_warnings:
            console.print(
                Panel(
                    Text(warning, style="yellow"),
                    title="Cross-dataset alignment warning",
                    title_align="left",
                )
            )


def render_refs_info(payload: RefsInfoPayload) -> None:
    """Render a single source's per-file detail view."""
    console = get_console()
    detail = payload.detail
    summary_lines = [
        f"source:           {detail.source}",
        f"expected release: {detail.expected_release}",
        f"on disk release:  {detail.on_disk_release or '<missing>'}",
        f"status:           {detail.status}",
        f"files:            {len(detail.present_files)} present, "
        f"{len(detail.missing_files)} missing",
    ]
    console.print(
        Panel(
            Text("\n".join(summary_lines), style=_STATUS_STYLE.get(detail.status, "")),
            title=f"Reference source — {detail.source}",
            title_align="left",
        )
    )

    if not detail.files:
        return

    table = Table(
        title="Files",
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Path", overflow="fold")
    table.add_column("Size", justify="right")
    table.add_column("Present")
    table.add_column("BGZF OK")
    for f in detail.files:
        present_cell = Text("yes", style="green") if f.present else Text("no", style="red")
        if f.bgzip_ok is None:
            bgzip_cell = Text("—", style="dim")
        elif f.bgzip_ok:
            bgzip_cell = Text("yes", style="green")
        else:
            bgzip_cell = Text("no", style="red")
        table.add_row(f.relpath, _human_bytes(f.size_bytes), present_cell, bgzip_cell)
    console.print(table)


def make_fetch_progress() -> Progress:
    """Construct the rich ``Progress`` used by ``refs fetch`` rich mode.

    The shape (columns + bar style) is centralised here so the
    rendering stays consistent across single-source and ``--all``
    invocations. The caller owns the ``Progress`` lifecycle via
    ``with progress: ...``; this factory only builds the object.
    """
    return Progress(
        TextColumn("[bold]{task.fields[source]}[/bold] · {task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=get_console(),
        transient=False,
        expand=True,
    )


def make_fetch_rich_renderer(
    progress: Progress,
) -> Callable[[_ProgressEvent], None]:
    """Build a ``progress_callback`` that drives a rich ``Progress`` instance.

    The returned callable owns a mapping from ``relpath`` → task id so
    repeated ``FileProgress`` events update the right row. ``FileStart``
    creates the task; ``FileProgress`` advances it; ``FileComplete``
    marks it 100 %; ``FileFailed`` re-styles the description in red.

    Args:
        progress: An active :class:`rich.progress.Progress` (already
            entered via ``with``).

    Returns:
        A callable accepting any :class:`_ProgressEvent` subclass. Non-
        file events are silently ignored — this renderer is scoped to
        file-level events only.
    """
    from rich.progress import TaskID

    task_ids: dict[str, TaskID] = {}

    def _on_event(event: _ProgressEvent) -> None:
        if isinstance(event, FileStart):
            new_id = progress.add_task(
                description=event.relpath,
                source=event.source,
                total=event.total_bytes,
            )
            task_ids[event.relpath] = new_id
            return
        if isinstance(event, FileProgress):
            existing = task_ids.get(event.relpath)
            if existing is None:
                # Tolerant: a progress event without a prior start —
                # treat it as start+progress in one shot.
                existing = progress.add_task(
                    description=event.relpath,
                    source=event.source,
                    total=event.total_bytes,
                )
                task_ids[event.relpath] = existing
            progress.update(existing, completed=event.bytes_so_far, total=event.total_bytes)
            return
        if isinstance(event, FileComplete):
            existing = task_ids.get(event.relpath)
            if existing is not None:
                progress.update(
                    existing,
                    completed=event.bytes_written,
                    total=event.bytes_written,
                )
            return
        if isinstance(event, FileFailed):
            existing = task_ids.get(event.relpath)
            if existing is not None:
                progress.update(
                    existing,
                    description=f"[red]{event.relpath} — {event.reason}[/red]",
                )
            return

    return _on_event


def make_fetch_ndjson_emitter(sink: TextIO) -> Callable[[_ProgressEvent], None]:
    r"""Build a ``progress_callback`` that writes NDJSON to ``sink``.

    Each event becomes one line of compact JSON terminated by ``\n``.
    The caller is responsible for emitting the first-line schema-version
    envelope before invoking the fetcher; this emitter writes only the
    raw event lines.

    Args:
        sink: Writable text stream (typically ``sys.stdout``).

    Returns:
        A callable accepting any :class:`_ProgressEvent` subclass.
    """

    def _on_event(event: _ProgressEvent) -> None:
        # ``separators=(",", ":")`` keeps every line compact; ``ensure_ascii=False``
        # lets non-ASCII paths and identifiers round-trip through agent parsers.
        sink.write(json.dumps(event.to_json_dict(), separators=(",", ":"), ensure_ascii=False))
        sink.write("\n")
        sink.flush()

    return _on_event


__all__ = [
    "make_fetch_ndjson_emitter",
    "make_fetch_progress",
    "make_fetch_rich_renderer",
    "render_refs_info",
    "render_refs_list",
    "render_refs_verify",
]

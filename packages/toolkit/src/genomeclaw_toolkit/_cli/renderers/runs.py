"""Rich renderers for the ``runs`` command group.

* :func:`render_runs_list` — one row per derived run; newest first.
* :func:`render_run_detail` — single-run view with manifest summary +
  provenance step table.

Both write through the shared :func:`genomeclaw_toolkit._cli.console.get_console`.
The JSON path bypasses renderers entirely (see
:func:`genomeclaw_toolkit._cli.output.emit`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from genomeclaw_toolkit._cli.console import get_console

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.commands.runs import RunDetailPayload, RunsListPayload


_STAGE_STYLE: dict[str, str] = {
    "ingested": "yellow",
    "normalized": "yellow",
    "annotated": "cyan",
    "materialized": "green",
    "unknown": "red",
}


def render_runs_list(payload: RunsListPayload) -> None:
    """Render the derived-run history as a rich table."""
    console = get_console()
    if not payload.runs:
        console.print(
            Panel(
                Text(
                    "(no derived runs — run `genomeclaw pipeline ingest` to create one)",
                    style="dim",
                ),
                title="Derived runs",
                title_align="left",
            )
        )
        return

    table = Table(
        title=f"Derived runs ({len(payload.runs)} total)",
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Run ID")
    table.add_column("Sample")
    table.add_column("Started")
    table.add_column("Stage")
    for run in payload.runs:
        style = _STAGE_STYLE.get(run.stage, "")
        table.add_row(
            run.run_id,
            run.sample_id or "—",
            run.started_at or "—",
            Text(run.stage, style=style),
        )
    console.print(table)


def render_run_detail(payload: RunDetailPayload) -> None:
    """Render a single run's manifest summary + provenance step trail."""
    console = get_console()
    detail = payload.detail

    summary_lines = [
        f"run_id:        {detail.run_id}",
        f"run_dir:       {detail.run_dir}",
        f"sample_id:     {detail.sample_id or '<none>'}",
        f"schema:        {detail.schema_version or '<unknown>'}",
        f"created_at:    {detail.created_at or '<unknown>'}",
        f"stage:         {detail.stage}",
    ]
    console.print(
        Panel(
            Text("\n".join(summary_lines)),
            title=f"Run summary — {detail.run_id}",
            title_align="left",
        )
    )

    if not detail.steps:
        console.print(
            Panel(
                Text("(provenance.json missing or unreadable)", style="dim"),
                title="Provenance step trail",
                title_align="left",
            )
        )
        return

    table = Table(
        title="Provenance step trail",
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Step")
    table.add_column("Tool")
    table.add_column("Version")
    table.add_column("Completed")
    for idx, step in enumerate(detail.steps, start=1):
        table.add_row(
            str(idx),
            step.step,
            step.tool or "—",
            step.tool_version or "—",
            step.completed_at or "—",
        )
    console.print(table)


__all__ = ["render_run_detail", "render_runs_list"]

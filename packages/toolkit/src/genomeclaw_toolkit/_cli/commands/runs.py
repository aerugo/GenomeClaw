"""``runs`` command group — derived-run history + per-run detail.

Phase 2 ships three read-only commands:

* ``runs list`` — every run under ``<derived-root>/`` (newest first).
* ``runs show <run-id>`` — manifest summary + provenance step trail.
* ``runs current`` — resolve the ``CURRENT`` symlink + delegate to ``show``.

All three read ``manifest.json`` + ``provenance.json`` inside the run
directory. No orchestrator invocation; no scratch use; no egress.

The introspection logic lives in :mod:`genomeclaw_toolkit.prep.runs`;
this module is the thin CLI dispatch + rendering wrapper.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import BaseModel, ConfigDict

from genomeclaw_toolkit._cli.errors import PreconditionError
from genomeclaw_toolkit._cli.output import emit
from genomeclaw_toolkit._cli.renderers.runs import render_run_detail, render_runs_list
from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir
from genomeclaw_toolkit.prep.runs import (
    DerivedRunSummary,
    RunDetail,
    list_derived_runs,
    read_run_detail,
)

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.context import AppContext


# ---------------------------------------------------------------------------
# Payloads (the ``runs`` ``--json`` schemas)
# ---------------------------------------------------------------------------


class RunsListPayload(BaseModel):
    """``runs list`` — every derived run with its classified stage."""

    model_config = ConfigDict(extra="forbid")

    derived_root: str
    runs: tuple[DerivedRunSummary, ...]


class RunDetailPayload(BaseModel):
    """``runs show`` / ``runs current`` — single-run detail view."""

    model_config = ConfigDict(extra="forbid")

    detail: RunDetail


# ---------------------------------------------------------------------------
# Typer app + commands
# ---------------------------------------------------------------------------


app = typer.Typer(
    name="runs",
    help="Inspect derived-run history: list / show / current.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command("list")
def runs_list(
    typer_ctx: typer.Context,
    derived_root: Annotated[
        Path,
        typer.Option(
            "--derived-root",
            help="Derived root (default: /mnt/genomeclaw/derived).",
        ),
    ] = Path("/mnt/genomeclaw/derived"),
    watch: Annotated[
        bool,
        typer.Option(
            "--watch",
            help="Refresh the table every 2 seconds until interrupted.",
        ),
    ] = False,
) -> None:
    """List every derived run under ``--derived-root`` (newest first)."""
    ctx: AppContext = typer_ctx.obj

    def _build_payload() -> RunsListPayload:
        return RunsListPayload(
            derived_root=str(derived_root),
            runs=tuple(list_derived_runs(derived_root=derived_root)),
        )

    if watch and not ctx.is_json:
        # ``--watch`` is a human-mode convenience; ``--json`` mode
        # emits a single envelope (callers wanting periodic snapshots
        # invoke the CLI on a timer themselves).
        from rich.console import Group, RenderableType
        from rich.table import Table
        from rich.text import Text

        from genomeclaw_toolkit._cli.watch import watch_loop

        def _renderable() -> RenderableType:
            # ``render_runs_list`` writes to the console directly,
            # which doesn't fit Live's "return a renderable" contract.
            # Wrap by building a Group of the payload's renderables.
            snap = _build_payload()
            if not snap.runs:
                return Text("(no derived runs)", style="dim")
            table = Table(
                title=f"Derived runs ({len(snap.runs)} total)",
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
            for run in snap.runs:
                table.add_row(
                    run.run_id,
                    run.sample_id or "—",
                    run.started_at or "—",
                    run.stage,
                )
            return Group(table)

        watch_loop(_renderable)
        return

    emit(
        ctx=ctx,
        command="runs.list",
        payload=_build_payload(),
        rich_renderer=render_runs_list,
    )


@app.command("show")
def runs_show(
    typer_ctx: typer.Context,
    run_id: Annotated[
        str,
        typer.Argument(
            help="Run ID (the directory name under <derived-root>/).",
        ),
    ],
    derived_root: Annotated[
        Path,
        typer.Option(
            "--derived-root",
            help="Derived root (default: /mnt/genomeclaw/derived).",
        ),
    ] = Path("/mnt/genomeclaw/derived"),
) -> None:
    """Show manifest summary + provenance step trail for a specific run."""
    ctx: AppContext = typer_ctx.obj
    run_dir = derived_root / run_id
    try:
        detail = read_run_detail(run_dir=run_dir)
    except FileNotFoundError as exc:
        raise PreconditionError(
            f"Run {run_id!r} not found under {derived_root}.",
            details={"run_id": run_id, "derived_root": str(derived_root)},
            suggested_actions=[
                "Run `genomeclaw runs list` to see available runs.",
                "Or `genomeclaw pipeline ingest` to create a new one.",
            ],
        ) from exc
    payload = RunDetailPayload(detail=detail)
    emit(
        ctx=ctx,
        command="runs.show",
        payload=payload,
        rich_renderer=render_run_detail,
    )


@app.command("current")
def runs_current(
    typer_ctx: typer.Context,
    derived_root: Annotated[
        Path,
        typer.Option(
            "--derived-root",
            help="Derived root (default: /mnt/genomeclaw/derived).",
        ),
    ] = Path("/mnt/genomeclaw/derived"),
) -> None:
    """Resolve ``<derived-root>/CURRENT`` and show the run it points at."""
    ctx: AppContext = typer_ctx.obj
    try:
        run_dir = resolve_current_run_dir(derived_root)
    except ValueError as exc:
        raise PreconditionError(
            str(exc),
            suggested_actions=[
                "Run `genomeclaw pipeline ingest` to create a derived run.",
                "Or `genomeclaw runs list` to see existing runs (without CURRENT).",
            ],
        ) from exc
    try:
        detail = read_run_detail(run_dir=run_dir)
    except FileNotFoundError as exc:
        raise PreconditionError(
            f"CURRENT symlink resolved to {run_dir}, but no manifest is present.",
            details={"derived_root": str(derived_root), "resolved": str(run_dir)},
        ) from exc
    payload = RunDetailPayload(detail=detail)
    emit(
        ctx=ctx,
        command="runs.current",
        payload=payload,
        rich_renderer=render_run_detail,
    )


__all__ = ["RunDetailPayload", "RunsListPayload", "app"]

"""Top-level Typer app + global flags + central exception boundary.

This module is the only place that catches ``CliError``, the only place
that exits the process with a non-zero code, and the only place that
constructs the per-invocation ``AppContext``. Command modules raise
``CliError`` subclasses and trust this layer to render the envelope.

Importing this module triggers registration of every command group via
side-effect import — that's the seam that lets ``commands/<group>.py``
self-register without anyone editing this file when a new group lands.
"""

from __future__ import annotations

import json
import sys
import traceback as _traceback
from typing import Annotated, NoReturn

import typer

from genomeclaw_toolkit._cli import output as _output_state
from genomeclaw_toolkit._cli.commands import completion as _completion_cmds
from genomeclaw_toolkit._cli.commands import host as _host_cmds
from genomeclaw_toolkit._cli.commands import pipeline as _pipeline_cmds
from genomeclaw_toolkit._cli.commands import refs as _refs_cmds
from genomeclaw_toolkit._cli.commands import runs as _runs_cmds
from genomeclaw_toolkit._cli.console import configure_console, get_console
from genomeclaw_toolkit._cli.context import AppContext
from genomeclaw_toolkit._cli.errors import (
    EXIT_INTERRUPTED,
    EXIT_RUNTIME_ERROR,
    EXIT_USAGE_ERROR,
    CliError,
    UsageError,
)
from genomeclaw_toolkit._cli.output import OutputMode, Verbosity
from genomeclaw_toolkit._cli.tool import default_tool_runner
from genomeclaw_toolkit._cli.types.envelope import CLI_OUTPUT_SCHEMA_VERSION, CliEnvelope
from genomeclaw_toolkit._cli.version import collect_version

# ---------------------------------------------------------------------------
# Top-level Typer app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="genomeclaw",
    help=(
        "GenomeClaw host-side toolkit. Manage references, drive the ingest → "
        "normalize → annotate → materialize pipeline, and diagnose the host "
        "environment."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(_host_cmds.app, name="host")
app.add_typer(_refs_cmds.app, name="refs")
app.add_typer(_runs_cmds.app, name="runs")
app.add_typer(_pipeline_cmds.app, name="pipeline")
app.add_typer(_completion_cmds.app, name="completion")


# ---------------------------------------------------------------------------
# Global callback — resolves AppContext from flags BEFORE any command runs
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    """Print the ``--version`` payload and exit when the flag is set.

    Args:
        value: Typer passes ``True`` when the user supplied ``--version``.

    Raises:
        typer.Exit: Always when ``value`` is ``True`` (Typer's normal
            "callback short-circuit" pattern).
    """
    if not value:
        return
    payload = collect_version()
    # ``--version`` runs before the global callback, so we don't have
    # an ``AppContext`` yet. Use the simple TTY heuristic to choose
    # between rich and JSON. ``--json`` precedence is handled at the
    # callback layer in normal command flow.
    if sys.stdout.isatty():
        console = get_console()
        console.print(f"[bold]genomeclaw[/bold] {payload.toolkit_version}")
        if payload.image_digest:
            console.print(f"  image digest: {payload.image_digest}")
        if payload.git_commit:
            console.print(f"  git commit:   {payload.git_commit}")
    else:
        envelope: CliEnvelope[object] = CliEnvelope(command="version", payload=payload)
        sys.stdout.write(envelope.model_dump_json(exclude_none=True))
        sys.stdout.write("\n")
    raise typer.Exit(0)


@app.callback()
def _main_callback(
    typer_ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a structured JSON envelope to stdout instead of rich-rendered output.",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-essential output."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Emit additional progress / status output."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Include Python tracebacks on error envelopes.",
        ),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable ANSI colour even on a TTY."),
    ] = False,
    force_color: Annotated[
        bool,
        typer.Option("--force-color", help="Force ANSI colour even off a TTY."),
    ] = False,
    assume_yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompts for destructive operations.",
        ),
    ] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print version (toolkit + image digest + git commit) and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Resolve the per-invocation ``AppContext`` and stash it on the Typer context.

    Every command inherits ``typer_ctx.obj == AppContext(...)``. The
    callback runs *before* any command handler, so output mode is
    settled by the time a command starts executing.
    """
    if no_color and force_color:
        raise UsageError("--no-color and --force-color are mutually exclusive.")

    if quiet and verbose:
        raise UsageError("--quiet and --verbose are mutually exclusive.")

    if no_color:
        color: str = "never"
    elif force_color:
        color = "always"
    else:
        color = "auto"
    configure_console(color=color)  # type: ignore[arg-type]

    verbosity = Verbosity.NORMAL
    if quiet:
        verbosity = Verbosity.QUIET
    elif debug:
        verbosity = Verbosity.DEBUG
    elif verbose:
        verbosity = Verbosity.VERBOSE

    output_mode = OutputMode.JSON if json_output else OutputMode.RICH

    typer_ctx.obj = AppContext(
        output_mode=output_mode,
        verbosity=verbosity,
        assume_yes=assume_yes,
        debug=debug,
        tool_runner=default_tool_runner(),
    )


# ---------------------------------------------------------------------------
# main() — the console-script entry point with the exception boundary
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> NoReturn:
    """Console-script entry point.

    Args:
        argv: Optional explicit argv (tests pass this; production
            relies on Typer reading ``sys.argv``).

    Raises:
        SystemExit: Always — this function never returns. The exit
            status follows the contract in
            :mod:`genomeclaw_toolkit._cli.errors`.
    """
    import click

    # The mode detectors (``_is_json_mode`` / ``_is_debug_mode``) run
    # in the exception path *before* the global callback has resolved
    # ``AppContext``. They need to see the right argv even when tests
    # call ``main(["--json", ...])`` without touching ``sys.argv``.
    effective_argv: list[str] = list(argv) if argv is not None else sys.argv[1:]

    # Reset the "stdout already consumed" sentinel so a trailing error
    # envelope from the previous invocation (under repeated in-process
    # ``main()`` calls in tests) doesn't accidentally redirect this
    # invocation's error envelope to stderr.
    _output_state.reset_stdout_state()

    try:
        app(args=argv, standalone_mode=False)
    except CliError as exc:
        _emit_error(exc, debug=_is_debug_mode(effective_argv), argv=effective_argv)
        raise SystemExit(exc.exit_code) from exc
    except KeyboardInterrupt:
        get_console().print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(EXIT_INTERRUPTED) from None
    except (click.exceptions.Exit, typer.Exit) as exc:
        # Normal exit from ``--help`` / ``--version`` callbacks etc.
        raise SystemExit(getattr(exc, "exit_code", 0)) from exc
    except click.exceptions.Abort:
        # User-initiated abort (Ctrl-C during a prompt, etc.).
        raise SystemExit(EXIT_INTERRUPTED) from None
    except (click.UsageError, typer.BadParameter) as exc:
        # Typer/Click parameter / usage failures. Render via the
        # envelope contract so JSON-mode callers see structure. When
        # the failure was "no such command <X>", surface a "Did you
        # mean: …" hint in suggested_actions.
        msg = exc.format_message() if hasattr(exc, "format_message") else str(exc)
        # Typer's ``no_args_is_help=True`` raises an empty-message
        # UsageError after printing the help text — we'd render that
        # as a vacuous ``Error (usage_error):`` line under the help.
        # Skip the envelope rendering on empty messages; the help is
        # already on stderr and exit code 2 still signals the failure.
        if msg.strip():
            suggestions = _did_you_mean_actions(msg)
            cli_exc = (
                UsageError(msg, suggested_actions=suggestions)
                if suggestions
                else UsageError(msg)
            )
            _emit_error(cli_exc, debug=_is_debug_mode(effective_argv), argv=effective_argv)
        raise SystemExit(EXIT_USAGE_ERROR) from exc
    except Exception as exc:
        # Anything not converted to a CliError reaches here. Surface
        # as a generic runtime failure with the message; include the
        # traceback when --debug was set.
        wrapped = type(
            "InternalError",
            (CliError,),
            {"exit_code": EXIT_RUNTIME_ERROR, "error_type": "internal_error"},
        )(str(exc) or exc.__class__.__name__)
        _emit_error(wrapped, debug=_is_debug_mode(effective_argv), argv=effective_argv)
        raise SystemExit(EXIT_RUNTIME_ERROR) from exc
    raise SystemExit(0)


def _registered_subcommand_names() -> list[str]:
    """Enumerate every reachable command path under ``app``.

    Returns:
        Alphabetically sorted list of command paths. Top-level
        subgroups appear as bare names (``host``, ``refs``, ...);
        nested commands appear as space-joined paths
        (``host doctor``, ``pipeline run``, ...). The space-joined form
        is what the user actually types, so the suggestion engine
        can recommend ``host doctor`` for an unprefixed typo like
        ``doctr``. Empty when Click hasn't materialised the command
        tree yet (shouldn't happen at error-handler time, but the
        helper is defensive).
    """
    import typer.main

    try:
        click_cmd = typer.main.get_command(app)
    except Exception:
        return []
    return sorted(_walk_command_paths(click_cmd))


def _walk_command_paths(click_cmd: object, prefix: str = "") -> list[str]:
    """Recursively flatten the Click command tree into space-joined paths."""
    paths: list[str] = []
    commands = getattr(click_cmd, "commands", None)
    if not isinstance(commands, dict):
        return paths
    for name, child in commands.items():
        full = f"{prefix} {name}".strip()
        paths.append(full)
        # Recurse into subgroups (their .commands dict is populated).
        paths.extend(_walk_command_paths(child, full))
    return paths


def _did_you_mean_actions(usage_message: str) -> list[str]:
    """Build a ``suggested_actions`` list from a ``No such command`` message.

    Args:
        usage_message: The raw Click/Typer usage-error message text.
            Expected shape for the "Did you mean" path:
            ``"No such command '<name>'."`` (Click's standard wording).

    Returns:
        A single-entry list ``["Did you mean: a, b, c"]`` when at least
        one close candidate clears the suggestion threshold; otherwise
        an empty list. The empty-list case lets the caller skip
        attaching ``suggested_actions`` when there's nothing useful to
        say.
    """
    import re

    from genomeclaw_toolkit._cli.suggest import suggest_closest

    match = re.search(r"No such command ['\"]([^'\"]+)['\"]", usage_message)
    if not match:
        return []

    bad_name = match.group(1)
    candidates = _registered_subcommand_names()
    closest = suggest_closest(bad_name, candidates)
    if not closest:
        return []
    return [f"Did you mean: {', '.join(closest)}?"]


def _is_debug_mode(argv: list[str]) -> bool:
    """Detect ``--debug`` from raw argv without forcing a Typer parse.

    Used by the top-level exception handler when callback parsing
    failed before ``AppContext`` was built (e.g. an unknown flag).
    """
    return "--debug" in argv


def _is_json_mode(argv: list[str]) -> bool:
    """Detect ``--json`` from raw argv for the pre-callback error path."""
    return "--json" in argv


def _emit_error(exc: CliError, *, debug: bool, argv: list[str]) -> None:
    """Render a ``CliError`` envelope in the active output mode.

    Args:
        exc: The error to render.
        debug: When ``True``, include the Python traceback in the
            envelope (``ErrorDetail.traceback``) and the rich panel.
        argv: The effective argv for this invocation (carried through
            so the JSON-mode detector sees flags passed to
            ``main(argv=...)`` in tests rather than the process's
            ``sys.argv``).
    """
    tb_lines: list[str] | None = None
    if debug and exc.__cause__ is not None:
        tb_lines = _traceback.format_exception(
            type(exc.__cause__),
            exc.__cause__,
            exc.__cause__.__traceback__,
        )
    elif debug:
        tb_lines = _traceback.format_exception(type(exc), exc, exc.__traceback__)

    if _is_json_mode(argv):
        envelope: CliEnvelope[object] = CliEnvelope(
            cli_output_schema_version=CLI_OUTPUT_SCHEMA_VERSION,
            command="error",
            error=exc.to_envelope(traceback=tb_lines),
        )
        # If a command has already written to stdout (a payload envelope
        # from ``emit`` or a stream first-line envelope from
        # ``_begin_ndjson_stream``), route the error envelope to stderr
        # to keep stdout parseable as one logical unit. Otherwise route
        # to stdout so JSON-mode callers see the error structurally.
        sink = sys.stderr if _output_state.stdout_already_consumed else sys.stdout
        sink.write(envelope.model_dump_json(exclude_none=True))
        sink.write("\n")
        sink.flush()
        return

    # Rich mode error rendering.
    console = get_console()
    console.print(f"[bold red]Error ({exc.error_type}):[/bold red] {exc.message}")
    if exc.details:
        # ``model_dump_json`` would be overkill for a small dict.
        console.print(f"  details: {json.dumps(exc.details, default=str)}")
    if exc.suggested_actions:
        console.print("[dim]Suggested actions:[/dim]")
        for action in exc.suggested_actions:
            console.print(f"  • {action}")
    if tb_lines:
        console.print("[dim]" + "".join(tb_lines) + "[/dim]")


__all__ = ["app", "main"]

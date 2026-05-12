"""``completion <shell>`` — emit a shell-completion script to stdout.

The script is **printed, never auto-installed**. The user pipes it
into their shell config — that discipline keeps the CLI from quietly
modifying ``~/.bashrc`` / ``~/.zshrc`` / ``~/.config/fish/`` without
explicit opt-in.

Typer doesn't expose its underlying Click-completion plumbing as a
first-class command. We reach into ``click.shell_completion``
directly to render the per-shell script.

Usage example::

    genomeclaw completion bash >> ~/.bashrc
    genomeclaw completion zsh >> ~/.zshrc
    genomeclaw completion fish > ~/.config/fish/completions/genomeclaw.fish

After sourcing, ``genomeclaw <TAB>`` will offer subcommand + flag
suggestions.
"""

from __future__ import annotations

import sys
from typing import Annotated, Final

import typer
from click.shell_completion import BashComplete, FishComplete, ZshComplete

from genomeclaw_toolkit._cli.errors import UsageError

_SHELL_CLASSES: Final = {
    "bash": BashComplete,
    "zsh": ZshComplete,
    "fish": FishComplete,
}

_PROG_NAME: Final[str] = "genomeclaw"
_COMPLETE_VAR: Final[str] = "_GENOMECLAW_COMPLETE"


app = typer.Typer(
    name="completion",
    help="Emit a shell-completion script to stdout (pipe into your shell config).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def completion(
    typer_ctx: typer.Context,
    shell: Annotated[
        str | None,
        typer.Argument(
            help=f"Target shell. One of: {', '.join(_SHELL_CLASSES)}.",
        ),
    ] = None,
) -> None:
    """Print the completion script for ``shell`` to stdout.

    Args:
        typer_ctx: Typer context (used only for the bare-invocation
            help-text fallback when ``shell`` is omitted).
        shell: One of ``bash``, ``zsh``, ``fish``. The set is the
            intersection of Click's built-in support and the shells
            most genomics-pipeline users actually run.
    """
    if shell is None:
        # No subcommand and no positional → show help (Typer's
        # ``no_args_is_help=True`` handles the bare-invocation case
        # but only when the callback itself receives no args).
        typer.echo(typer_ctx.get_help())
        raise typer.Exit(0)

    shell_cls = _SHELL_CLASSES.get(shell)
    if shell_cls is None:
        raise UsageError(
            f"Unsupported shell {shell!r}. Supported: {sorted(_SHELL_CLASSES)}.",
            suggested_actions=[
                f"Pass one of: {', '.join(sorted(_SHELL_CLASSES))}.",
            ],
        )

    # Lazy import the top-level Typer app — importing it at module load
    # time would create a circular import (this module is registered
    # into that same app). Importing here is fine because the command
    # only runs when actually invoked.
    from genomeclaw_toolkit._cli import app as root_app

    click_cmd = typer.main.get_command(root_app)
    completer = shell_cls(
        cli=click_cmd,
        ctx_args={},
        prog_name=_PROG_NAME,
        complete_var=_COMPLETE_VAR,
    )
    sys.stdout.write(completer.source())
    sys.stdout.write("\n")


__all__ = ["app"]

r"""Typed-confirmation prompts for destructive CLI operations.

GenomeClaw's destructive commands (``host setup --force-reset``,
``host eject``) require one of two deliberate consents before they
proceed:

1. **Interactive TTY** — the user types a specific operation-named
   phrase at the prompt (e.g. ``REFORMAT GENOMECLAW DRIVE`` for
   reformat; the drive's mount-point basename for eject). The
   typed-phrase pattern is preferred over yes/no prompts because it
   prevents thoughtless ``y\n`` muscle-memory.
2. **Scripted** — the user passes ``--yes`` on the command line
   (lands on :attr:`AppContext.assume_yes`). Required for non-TTY
   invocation (CI / agent / piped scripts) where no interactive prompt
   is possible.

Without either, the command refuses with exit code 2 (usage error)
and an error envelope naming both routes forward.

`INV-S-confirmation-required` (provisional): any command that mutates
host state outside ``derived/`` enforces this gate.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from genomeclaw_toolkit._cli.errors import UsageError

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.context import AppContext


def require_destructive_confirmation(
    *,
    ctx: AppContext,
    expected_phrase: str,
    operation_description: str,
    suggested_actions: list[str] | None = None,
) -> None:
    """Gate a destructive operation behind ``--yes`` or a typed phrase.

    Args:
        ctx: Active :class:`AppContext`; the ``--yes`` flag short-circuits
            the prompt when ``ctx.assume_yes`` is ``True``.
        expected_phrase: The exact string the user must type at the
            interactive prompt (case-sensitive, whitespace-stripped).
        operation_description: Short imperative describing the
            destructive action (e.g. ``"reformat the GenomeClaw drive"``).
            Surfaced in the prompt + error messages.
        suggested_actions: Optional remediation steps to attach to the
            error envelope when the gate refuses. Defaults to the
            canonical two-route guidance.

    Raises:
        UsageError: When neither ``--yes`` nor a correct typed phrase
            was provided. Exit code 2. ``details`` includes the
            ``operation`` field; ``suggested_actions`` names both
            routes forward.
    """
    if ctx.assume_yes:
        return

    routes = suggested_actions or [
        f"Pass --yes on the command line to {operation_description} unattended.",
        f'Or run interactively + type "{expected_phrase}" at the confirmation prompt.',
    ]

    if not sys.stdin.isatty():
        raise UsageError(
            f"Refusing to {operation_description} without confirmation. "
            f"Pass --yes (scripted) or run on an interactive terminal.",
            details={"operation": expected_phrase, "tty_detected": False},
            suggested_actions=routes,
        )

    # Interactive path. The prompt itself goes to stderr so it doesn't
    # corrupt any stdout consumer; ``input()`` reads from stdin.
    print(
        f"Type {expected_phrase!r} to {operation_description}: ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    typed = sys.stdin.readline().strip()
    if typed != expected_phrase:
        raise UsageError(
            f"Confirmation phrase did not match; aborting. "
            f"(expected {expected_phrase!r}, got {typed!r})",
            details={"operation": expected_phrase, "tty_detected": True},
            suggested_actions=routes,
        )


__all__ = ["require_destructive_confirmation"]

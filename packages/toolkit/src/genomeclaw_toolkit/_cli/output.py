"""Output-mode enums + the central ``emit`` dispatcher.

The CLI runs in one of two output modes for every command: ``rich``
(human-rendered: tables, panels, colour, progress bars) or ``json``
(stable structured payload to stdout, progress/log to stderr).
``Verbosity`` is an orthogonal axis controlling how much is emitted at
all — ``quiet`` suppresses non-essential output entirely; ``debug``
amplifies it.

The ``emit`` helper is the single dispatch point: command handlers
build a Pydantic payload model + pass it to ``emit``, which routes to
the right renderer based on the active ``AppContext``. Commands never
call ``console.print(...)`` or ``json.dumps(...)`` directly — that
discipline keeps mode-switching consistent.

The ``stdout_already_consumed`` module flag tracks whether anything
has already been written to JSON-mode stdout in this invocation. The
exception boundary (:mod:`._cli.__init__`) consults the flag to
decide where to write trailing error envelopes — if a payload (or
stream-envelope) already went to stdout, the error envelope goes to
stderr instead, so the stdout stream stays parseable as one logical
unit.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from genomeclaw_toolkit._cli.types.envelope import CliEnvelope

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit._cli.context import AppContext

# Generic payload type used by ``emit`` so each command's renderer
# can be typed to its specific Pydantic payload model rather than the
# bare ``BaseModel``.
_PayloadT = TypeVar("_PayloadT", bound=BaseModel)

# Module-level "have we written to JSON-mode stdout this invocation?"
# sentinel. Set by ``emit`` + by the stream-envelope helpers in the
# pipeline / refs commands; read by the exception boundary to decide
# whether a trailing error envelope goes to stdout or stderr.
# ``reset_stdout_state`` is called at every ``main()`` invocation to
# guarantee per-invocation isolation (matters for the test fixture
# that calls ``main()`` repeatedly in one Python process).
stdout_already_consumed: bool = False


def mark_stdout_consumed() -> None:
    """Record that something has been written to JSON-mode stdout."""
    global stdout_already_consumed
    stdout_already_consumed = True


def reset_stdout_state() -> None:
    """Reset the stdout-consumed sentinel between top-level invocations."""
    global stdout_already_consumed
    stdout_already_consumed = False


class OutputMode(StrEnum):
    """How command output is presented to the caller.

    ``RICH`` renders tables / panels / progress bars suitable for a
    human terminal (auto-detects non-TTY contexts and degrades to
    plain text without ANSI escapes). ``JSON`` emits a stable
    ``CliEnvelope``-shaped payload to stdout and keeps all
    progress/log output on stderr.
    """

    RICH = "rich"
    JSON = "json"


class Verbosity(StrEnum):
    """How much non-essential output a command emits.

    Orthogonal to ``OutputMode`` — a JSON-mode command can also be
    ``QUIET`` (suppress progress events) or ``DEBUG`` (include
    tracebacks on error envelopes).
    """

    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"
    DEBUG = "debug"


def emit(
    *,
    ctx: AppContext,
    command: str,
    payload: _PayloadT,
    rich_renderer: Callable[[_PayloadT], None],
) -> None:
    """Dispatch a command's structured payload to the active output sink.

    Args:
        ctx: The active ``AppContext`` resolved from global CLI flags.
        command: Dotted-form command name (``"host.doctor"``,
            ``"refs.list"``) — stamped onto the JSON envelope.
        payload: A Pydantic model representing the structured result.
            Must round-trip through ``model_dump_json`` for the JSON
            path to work.
        rich_renderer: Callable that receives ``payload`` and writes
            human-readable output via the shared ``Console``. Only
            invoked when ``ctx.output_mode is OutputMode.RICH``.
    """
    if ctx.is_json:
        envelope: CliEnvelope[Any] = CliEnvelope(command=command, payload=payload)
        # Use ``ensure_ascii=False`` so non-ASCII paths and identifiers
        # round-trip cleanly through agent JSON parsers.
        sys.stdout.write(envelope.model_dump_json(exclude_none=True))
        sys.stdout.write("\n")
        sys.stdout.flush()
        mark_stdout_consumed()
        return
    rich_renderer(payload)


__all__ = [
    "OutputMode",
    "Verbosity",
    "emit",
    "mark_stdout_consumed",
    "reset_stdout_state",
    "stdout_already_consumed",
]

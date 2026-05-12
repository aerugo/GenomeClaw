"""Close-match suggestions for mistyped CLI subcommands.

The CLI's usage-error handler calls :func:`suggest_closest` with the
mistyped subcommand + the list of registered top-level commands. The
result feeds the ``"Did you mean: …"`` hint in the error envelope's
``suggested_actions`` field — same hint, same place, in both rich
and JSON modes.

Uses :func:`difflib.get_close_matches` (stdlib) under the hood —
equivalent to Damerau-Levenshtein for typical typo distances and adds
zero new dependencies.
"""

from __future__ import annotations

import difflib
from typing import Final

# difflib's cutoff is a similarity ratio in [0, 1]; 0.6 corresponds
# roughly to "no more than ~40 % of the characters differ", which
# catches single-character typos on short command names but rejects
# distant matches (``xyzzy`` vs ``doctor``).
_DEFAULT_CUTOFF: Final[float] = 0.6
_DEFAULT_MAX_RESULTS: Final[int] = 3


def suggest_closest(
    user_input: str,
    candidates: list[str],
    *,
    cutoff: float = _DEFAULT_CUTOFF,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> list[str]:
    """Return the closest candidate strings to ``user_input``.

    Args:
        user_input: The mistyped string the user typed.
        candidates: Known-good options (e.g. registered subcommand
            names). Order doesn't matter — the result is sorted by
            similarity descending.
        cutoff: Minimum similarity ratio in ``[0, 1]``; candidates with
            a lower ratio are dropped. Default 0.6 catches single-
            character typos while rejecting distant inputs.
        max_results: Hard cap on the number of suggestions returned.
            Default 3 — enough to surface alternatives without spamming.

    Returns:
        A list of candidate strings sorted closest-first. Empty when no
        candidate clears the ``cutoff`` threshold.
    """
    if not candidates:
        return []
    return difflib.get_close_matches(
        user_input,
        candidates,
        n=max_results,
        cutoff=cutoff,
    )


__all__ = ["suggest_closest"]

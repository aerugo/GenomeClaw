"""Phase 7 — ``suggest_closest`` unit tests.

The helper drives the "Did you mean…" hint in the CLI's usage-error
handler. It's a tiny wrapper around :func:`difflib.get_close_matches`,
sorted closest-first with a max-distance cutoff.
"""

from __future__ import annotations


def test_suggest_closest_finds_single_match() -> None:
    """A clear typo against a known command returns the obvious fix."""
    from genomeclaw_toolkit._cli.suggest import suggest_closest

    out = suggest_closest("doctr", ["doctor", "version", "fetch"])
    assert out == ["doctor"]


def test_suggest_closest_ignores_distant_candidates() -> None:
    """An input nothing like any candidate returns no suggestions."""
    from genomeclaw_toolkit._cli.suggest import suggest_closest

    assert suggest_closest("xyzzy", ["doctor", "fetch"]) == []


def test_suggest_closest_handles_empty_candidates() -> None:
    """No candidates → no suggestions, never raises."""
    from genomeclaw_toolkit._cli.suggest import suggest_closest

    assert suggest_closest("doctor", []) == []


def test_suggest_closest_returns_sorted_by_similarity() -> None:
    """Multiple matches within the cutoff are sorted closest first."""
    from genomeclaw_toolkit._cli.suggest import suggest_closest

    # ``ingst`` is closer to ``ingest`` than to ``annotate`` / ``materialize``.
    out = suggest_closest("ingst", ["ingest", "annotate", "materialize"])
    assert out
    assert out[0] == "ingest"

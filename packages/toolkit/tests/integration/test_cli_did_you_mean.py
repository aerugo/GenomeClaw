"""Phase 7 — "Did you mean" suggestions for mistyped subcommands.

When the user invokes a subcommand that doesn't exist, the CLI surfaces
the closest-match candidates (subcommand-level only — flag-level is
Click's job). The hint appears in both rich and JSON modes via the
standard ``suggested_actions`` field.
"""

from __future__ import annotations

import json


def test_did_you_mean_subcommand_misspelling(invoke_cli) -> None:
    """A close typo at the top level surfaces a "Did you mean …" hint."""
    result = invoke_cli(["doctr"])
    assert result.exit_code == 2, result.stderr
    # The hint mentions "doctor" or "host" (both are plausible suggestions).
    combined = result.stderr + result.stdout
    assert "did you mean" in combined.lower()
    assert "doctor" in combined.lower() or "host" in combined.lower()


def test_did_you_mean_no_suggestion_when_too_far(invoke_cli) -> None:
    """An input nothing like any subcommand does not emit a hint."""
    result = invoke_cli(["xyzzy"])
    assert result.exit_code == 2, result.stderr
    # No "Did you mean" line — input is too distant.
    assert "did you mean" not in result.stderr.lower()


def test_did_you_mean_json_mode_carries_suggestions_in_envelope(invoke_cli) -> None:
    """`--json` mode surfaces "Did you mean" via the error envelope."""
    result = invoke_cli(["--json", "doctr"])
    assert result.exit_code == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "error"
    actions = payload["error"]["suggested_actions"]
    assert any("did you mean" in a.lower() for a in actions), (
        f"expected a Did-you-mean action; got {actions!r}"
    )

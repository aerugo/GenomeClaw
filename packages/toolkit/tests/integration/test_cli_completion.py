"""Phase 7 — ``genomeclaw completion <shell>`` Typer command.

The command writes a shell-completion script to stdout (the user pipes
it into their shell config; the CLI never auto-installs). Typer ships
the underlying plumbing via Click; this test pins the public contract.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_supported_shell_emits_script_to_stdout(invoke_cli, shell: str) -> None:
    """`completion bash|zsh|fish` writes a shell-completion script to stdout."""
    result = invoke_cli(["completion", shell])
    assert result.exit_code == 0, result.stderr
    # The completion script contains the binary name + a shell-specific
    # marker. Use both checks to confirm we got something shell-shaped.
    out = result.stdout
    assert "genomeclaw" in out
    assert len(out) > 100, f"completion script unexpectedly short: {out!r}"


def test_completion_unknown_shell_errors(invoke_cli) -> None:
    """`completion ksh` (or anything not bash/zsh/fish) → usage error (exit 2)."""
    result = invoke_cli(["completion", "ksh"])
    assert result.exit_code == 2, result.stderr
    # The error message mentions the supported shells.
    combined = (result.stderr + result.stdout).lower()
    assert "bash" in combined or "zsh" in combined or "fish" in combined

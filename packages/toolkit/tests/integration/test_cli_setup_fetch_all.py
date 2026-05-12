"""``host setup --fetch-all`` integration — after smart-setup resolves to
NO_OP, the CLI hands off to the shim path so the fetch runs through the
toolkit image (where samtools is available for the grch38 faidx hook).

These tests stub the smart-setup runner and the ``subprocess.run`` exec
so no real diskutil / docker / network calls happen.

Phase 1 thin wrapper; the rich-rendered host setup flow is Phase 4.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_setup_fetch_all_execs_shim_after_smart_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``host setup --fetch-all`` after smart-NOOP invokes the shim with ``refs fetch --all``."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd
    import genomeclaw_toolkit._cli.commands.refs as refs_cmd

    monkeypatch.setattr(host_cmd, "setup_run_smart", lambda: 0)

    shim_path = tmp_path / "genomeclaw"
    shim_path.write_text("#!/bin/sh\nexit 0\n")
    shim_path.chmod(0o755)
    monkeypatch.setenv("GENOMECLAW_SHIM_PATH", str(shim_path))

    recorded: list[list[str]] = []

    class FakeCompleted:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def fake_run(cmd, **_kw):
        recorded.append(list(cmd))
        return FakeCompleted(0)

    monkeypatch.setattr(refs_cmd.subprocess, "run", fake_run)

    result = invoke_cli(["host", "setup", "--fetch-all"])

    assert result.exit_code == 0, result.stderr
    assert recorded == [[str(shim_path), "refs", "fetch", "--all"]]


def test_setup_fetch_all_skipped_on_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """A dry-run setup never actually wrote anything to fetch into; skip the hook."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd
    import genomeclaw_toolkit._cli.commands.refs as refs_cmd

    monkeypatch.setattr(host_cmd, "setup_run_smart", lambda: 0)

    shim_path = tmp_path / "genomeclaw"
    shim_path.write_text("#!/bin/sh\nexit 0\n")
    shim_path.chmod(0o755)
    monkeypatch.setenv("GENOMECLAW_SHIM_PATH", str(shim_path))

    recorded: list[list[str]] = []

    def fake_run(cmd, **_kw):
        recorded.append(list(cmd))

        class C:
            returncode = 0

        return C()

    monkeypatch.setattr(refs_cmd.subprocess, "run", fake_run)

    result = invoke_cli(["host", "setup", "--dry-run", "--fetch-all"])

    assert result.exit_code == 0, result.stderr
    assert recorded == []


def test_setup_without_fetch_all_does_not_invoke_fetch(
    monkeypatch: pytest.MonkeyPatch, invoke_cli
) -> None:
    """Plain ``host setup`` keeps the prior behaviour — no fetch side effect."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd
    import genomeclaw_toolkit._cli.commands.refs as refs_cmd

    monkeypatch.setattr(host_cmd, "setup_run_smart", lambda: 0)

    recorded: list[list[str]] = []

    def fake_run(cmd, **_kw):
        recorded.append(list(cmd))

        class C:
            returncode = 0

        return C()

    monkeypatch.setattr(refs_cmd.subprocess, "run", fake_run)

    result = invoke_cli(["host", "setup"])

    assert result.exit_code == 0, result.stderr
    assert recorded == []

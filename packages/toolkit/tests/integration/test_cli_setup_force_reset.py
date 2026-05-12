"""CLI coverage for the scriptable ``host setup --force-reset`` flow.

Three flags together — ``--force-reset``, ``--source``, ``--target-volume``
— let setup run unattended (the flag combo itself is the deliberate
confirmation, mirroring the typed ``WIPE /Volumes/<name>`` phrase in the
interactive path).

These tests stub the smart-dispatch + ``run_interactive`` callables so
the real diskutil / docker / colima paths never fire. They assert on
the arguments handed to ``run_interactive`` since that's the seam where
the CLI's intent gets translated into behaviour.

Phase 1 ``host setup`` is a thin wrapper; Phase 4 adds rich-rendered
interactive flow + confirmation prompts. The tests here lock the thin-
wrapper contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _stub_run_interactive(monkeypatch: pytest.MonkeyPatch, captured: list[dict]) -> None:
    """Record every ``setup_run_interactive`` invocation."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    def fake(*, execute_destructive, nebula_dir, target_mount, auto_confirm):
        captured.append(
            {
                "execute_destructive": execute_destructive,
                "nebula_dir": nebula_dir,
                "target_mount": target_mount,
                "auto_confirm": auto_confirm,
            }
        )
        return 0

    monkeypatch.setattr(host_cmd, "setup_run_interactive", fake)


def test_setup_force_reset_skips_smart_dispatch(
    monkeypatch: pytest.MonkeyPatch, invoke_cli
) -> None:
    """``--force-reset`` bypasses ``run_smart`` and goes straight to the destructive flow."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    smart_called: list[bool] = []

    def fake_run_smart():
        smart_called.append(True)
        return 0

    monkeypatch.setattr(host_cmd, "setup_run_smart", fake_run_smart)

    captured: list[dict] = []
    _stub_run_interactive(monkeypatch, captured)

    result = invoke_cli(
        [
            "--yes",  # Phase 6: --force-reset now requires --yes or TTY confirmation.
            "host",
            "setup",
            "--force-reset",
            "--source",
            "/some/nebula/dir",
            "--target-volume",
            "Genome_Work",
        ]
    )

    assert result.exit_code == 0, result.stderr
    # run_smart must NOT be called when --force-reset is set.
    assert smart_called == []
    assert len(captured) == 1
    call = captured[0]
    assert call["nebula_dir"] == Path("/some/nebula/dir")
    assert call["target_mount"] == "Genome_Work"
    assert call["auto_confirm"] is True
    assert call["execute_destructive"] is True


def test_setup_force_reset_dry_run_skips_destructive(
    monkeypatch: pytest.MonkeyPatch, invoke_cli
) -> None:
    """``--force-reset --dry-run`` plans without running the destructive executor."""
    captured: list[dict] = []
    _stub_run_interactive(monkeypatch, captured)

    result = invoke_cli(
        [
            "--yes",  # Phase 6: required for --force-reset.
            "host",
            "setup",
            "--force-reset",
            "--dry-run",
            "--source",
            "/x",
            "--target-volume",
            "Genome_Work",
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert captured[0]["execute_destructive"] is False
    assert captured[0]["auto_confirm"] is True


def test_setup_force_reset_propagates_run_interactive_failure(
    monkeypatch: pytest.MonkeyPatch, invoke_cli
) -> None:
    """If the destructive flow exits non-zero, the CLI surfaces it."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    monkeypatch.setattr(host_cmd, "setup_run_interactive", lambda **_kw: 3)

    result = invoke_cli(
        [
            "--yes",  # Phase 6: required for --force-reset.
            "host",
            "setup",
            "--force-reset",
            "--source",
            "/x",
            "--target-volume",
            "Genome_Work",
        ]
    )

    # Non-zero from the destructive flow → RuntimeFailure → exit 1.
    assert result.exit_code == 1, result.stderr
    assert "Setup did not complete cleanly" in result.stderr

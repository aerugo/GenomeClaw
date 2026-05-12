"""Phase 6 — ``host eject`` typed-confirmation + ``--yes`` + JSON envelope.

``host eject`` is destructive in a different sense than ``host setup``:
it doesn't wipe data, but it stops colima + unmounts the drive, which
will fail in flight any pipeline mid-run. Phase 6 gates the eject
behind one of two consents:

1. **Interactive TTY**: the user types the drive's mount-point
   basename (e.g. ``Genome_Work`` for ``/Volumes/Genome_Work``).
2. **Scripted**: ``--yes`` on the command line.

``--force`` is a separate gate that bypasses the existing in-flight-
pipeline safety check; it does **not** imply confirmation.
"""

from __future__ import annotations

import io
import json
import sys

import pytest


def _stub_eject_impl(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stub ``eject_impl``; return per-invocation argument log."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    captured: list[dict] = []

    def fake(*, drive, force):
        captured.append({"drive": drive, "force": force})
        return 0

    monkeypatch.setattr(host_cmd, "eject_impl", fake)
    return captured


class _FakeTTYStdin(io.StringIO):
    """StringIO that reports as a TTY so the confirm helper takes the prompt path."""

    def isatty(self) -> bool:  # type: ignore[override]
        return True


def _patch_tty_stdin(monkeypatch: pytest.MonkeyPatch, typed: str) -> None:
    """Replace ``sys.stdin`` with a TTY-reporting buffer pre-loaded with ``typed``."""
    fake_stdin = _FakeTTYStdin(typed if typed.endswith("\n") else typed + "\n")
    monkeypatch.setattr(sys, "stdin", fake_stdin)


# ---------------------------------------------------------------------------
# Refusal + accept paths
# ---------------------------------------------------------------------------


def test_host_eject_refuses_non_tty_without_yes_or_force(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-TTY + no ``--yes`` → exit 2; orchestrator untouched."""
    captured = _stub_eject_impl(monkeypatch)

    result = invoke_cli(["host", "eject", "--drive", "/Volumes/Genome_Work"])
    assert result.exit_code == 2, result.stderr
    assert captured == []
    assert "--yes" in result.stderr


def test_host_eject_accepts_yes_flag(invoke_cli, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--yes`` skips the prompt; orchestrator runs."""
    captured = _stub_eject_impl(monkeypatch)

    result = invoke_cli(["--yes", "host", "eject", "--drive", "/Volumes/Genome_Work"])
    assert result.exit_code == 0, result.stderr
    assert captured == [{"drive": "/Volumes/Genome_Work", "force": False}]


def test_host_eject_accepts_typed_drive_basename_on_tty(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY stdin types the drive basename → orchestrator runs."""
    captured = _stub_eject_impl(monkeypatch)
    _patch_tty_stdin(monkeypatch, "Genome_Work")

    result = invoke_cli(["host", "eject", "--drive", "/Volumes/Genome_Work"])
    assert result.exit_code == 0, result.stderr
    assert captured == [{"drive": "/Volumes/Genome_Work", "force": False}]


def test_host_eject_rejects_wrong_basename_on_tty(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY stdin types the wrong basename → exit 2; orchestrator untouched."""
    captured = _stub_eject_impl(monkeypatch)
    _patch_tty_stdin(monkeypatch, "nope")

    result = invoke_cli(["host", "eject", "--drive", "/Volumes/Genome_Work"])
    assert result.exit_code == 2, result.stderr
    assert captured == []


def test_host_eject_preserves_force_flag_separately_from_yes(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--force`` is independent of ``--yes``: still requires confirmation."""
    captured = _stub_eject_impl(monkeypatch)

    # --force without --yes: should still refuse on non-TTY because
    # --force only bypasses the pipeline-running check, not the
    # confirmation gate.
    result = invoke_cli(["host", "eject", "--drive", "/Volumes/Genome_Work", "--force"])
    assert result.exit_code == 2, result.stderr
    assert captured == []


def test_host_eject_force_with_yes_passes_force_to_orchestrator(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--yes --force`` runs the orchestrator with ``force=True``."""
    captured = _stub_eject_impl(monkeypatch)

    result = invoke_cli(["--yes", "host", "eject", "--drive", "/Volumes/Genome_Work", "--force"])
    assert result.exit_code == 0, result.stderr
    assert captured == [{"drive": "/Volumes/Genome_Work", "force": True}]


# ---------------------------------------------------------------------------
# JSON-mode envelope
# ---------------------------------------------------------------------------


def test_host_eject_json_emits_result_envelope(invoke_cli, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--json --yes host eject`` emits a single result envelope."""
    _stub_eject_impl(monkeypatch)

    result = invoke_cli(["--json", "--yes", "host", "eject", "--drive", "/Volumes/Genome_Work"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cli_output_schema_version"] == "1.0"
    assert payload["command"] == "host.eject"
    assert payload["payload"]["drive"] == "/Volumes/Genome_Work"
    assert payload["payload"]["force_used"] is False
    assert payload["payload"]["exit_code"] == 0

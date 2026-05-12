"""Phase 6 — ``host setup`` typed-confirmation + ``--yes`` + JSON envelopes.

`host setup --force-reset` runs a destructive reformat of the
external drive. Phase 6 gates the destructive path behind one of two
deliberate consents:

1. **Interactive TTY**: the user types the exact phrase
   ``REFORMAT GENOMECLAW DRIVE`` at the prompt.
2. **Scripted**: the user passes ``--yes`` on the command line.

Neither available (non-TTY without ``--yes``) → exit 2 (usage error)
with both ways forward in ``suggested_actions``.

These tests stub ``setup_run_interactive`` so the real disk operations
never fire.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_PHRASE = "REFORMAT GENOMECLAW DRIVE"


def _stub_setup_runners(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stub ``setup_run_interactive`` + ``setup_run_smart``; return interactive log."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    captured: list[dict] = []

    def fake_interactive(*, execute_destructive, nebula_dir, target_mount, auto_confirm):
        captured.append(
            {
                "execute_destructive": execute_destructive,
                "nebula_dir": nebula_dir,
                "target_mount": target_mount,
                "auto_confirm": auto_confirm,
            }
        )
        return 0

    def fake_smart():
        return 0

    monkeypatch.setattr(host_cmd, "setup_run_interactive", fake_interactive)
    monkeypatch.setattr(host_cmd, "setup_run_smart", fake_smart)
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
# Refusal paths
# ---------------------------------------------------------------------------


def test_host_setup_force_reset_refuses_non_tty_without_yes(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-TTY + no ``--yes`` + ``--force-reset`` → exit 2 with both routes named."""
    captured = _stub_setup_runners(monkeypatch)

    result = invoke_cli(
        [
            "host",
            "setup",
            "--force-reset",
            "--source",
            "/some/nebula/dir",
            "--target-volume",
            "Genome_Work",
        ]
    )
    assert result.exit_code == 2, result.stderr
    # Both remediation routes named.
    assert "--yes" in result.stderr
    assert _PHRASE in result.stderr or "confirmation" in result.stderr.lower()
    # Orchestrator must NOT have been called.
    assert captured == []


def test_host_setup_force_reset_rejects_wrong_phrase_on_tty(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY stdin returns the wrong phrase → exit 2; orchestrator untouched."""
    captured = _stub_setup_runners(monkeypatch)
    _patch_tty_stdin(monkeypatch, "nope")

    result = invoke_cli(
        [
            "host",
            "setup",
            "--force-reset",
            "--source",
            "/some/nebula/dir",
            "--target-volume",
            "Genome_Work",
        ]
    )
    assert result.exit_code == 2, result.stderr
    assert captured == []


# ---------------------------------------------------------------------------
# Accept paths
# ---------------------------------------------------------------------------


def test_host_setup_force_reset_accepts_yes_flag_on_non_tty(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--yes`` on non-TTY → orchestrator called with ``auto_confirm=True``."""
    captured = _stub_setup_runners(monkeypatch)

    result = invoke_cli(
        [
            "--yes",
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
    assert len(captured) == 1
    assert captured[0]["auto_confirm"] is True


def test_host_setup_force_reset_accepts_typed_phrase_on_tty(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY stdin types the exact phrase → orchestrator runs."""
    captured = _stub_setup_runners(monkeypatch)
    _patch_tty_stdin(monkeypatch, _PHRASE)

    result = invoke_cli(
        [
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
    assert len(captured) == 1


def test_host_setup_non_destructive_path_skips_confirmation(
    invoke_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``host setup`` (no ``--force-reset``) doesn't prompt; smart-dispatch handles it."""
    _stub_setup_runners(monkeypatch)
    # Non-TTY, no --yes. Should still succeed because smart-dispatch is
    # the non-destructive resolver.
    result = invoke_cli(["host", "setup"])
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# JSON-mode payloads
# ---------------------------------------------------------------------------


def test_host_setup_json_emits_plan_and_result_envelopes(
    invoke_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--json host setup --dry-run --yes --force-reset`` emits plan + result envelopes."""
    _stub_setup_runners(monkeypatch)

    result = invoke_cli(
        [
            "--json",
            "--yes",
            "host",
            "setup",
            "--force-reset",
            "--dry-run",
            "--source",
            str(tmp_path),
            "--target-volume",
            "Genome_Work",
        ]
    )
    assert result.exit_code == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2, f"expected 2 envelopes, got {len(lines)}: {lines!r}"

    plan = json.loads(lines[0])
    assert plan["cli_output_schema_version"] == "1.0"
    assert plan["command"] == "host.setup"
    assert plan["payload"]["phase"] == "plan"
    assert plan["payload"]["dry_run"] is True
    assert plan["payload"]["force_reset"] is True

    result_env = json.loads(lines[1])
    assert result_env["command"] == "host.setup"
    assert result_env["payload"]["phase"] == "result"
    assert result_env["payload"]["exit_code"] == 0

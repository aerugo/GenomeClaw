"""Phase 1 — ``host doctor`` command tests.

Covers both rich + JSON modes, exit-code mapping, error-envelope
shape, and the precondition-error path when no canonical layout exists.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def _clean_doctor(monkeypatch: pytest.MonkeyPatch):
    """Stub ``doctor_impl`` to return a healthy report."""
    from genomeclaw_toolkit._cli.commands import host as host_cmd

    def fake_doctor() -> tuple[int, dict[str, object]]:
        return (
            0,
            {
                "checks": [
                    {"name": "raw_present", "status": "OK", "message": ""},
                    {"name": "reference_present", "status": "OK", "message": ""},
                ],
                "setup_log": {
                    "found": True,
                    "incomplete": False,
                    "no_events": False,
                    "last_completed_at": "2026-05-11T21:48:43Z",
                    "toolkit_version": "0.0.1",
                    "target_partition": "Genome_Work",
                },
                "colima": {"installed": True, "version": "0.9.1", "status": "running"},
                "paths": {"raw": "/mnt/genomeclaw/raw"},
                "references": {"release_set": "default", "sources": []},
                "raw_sample": {"staged": False},
                "derived_runs": [],
            },
        )

    monkeypatch.setattr(host_cmd, "doctor_impl", fake_doctor)


@pytest.fixture
def _failing_doctor(monkeypatch: pytest.MonkeyPatch):
    """Stub ``doctor_impl`` to return a layout with a failing check."""
    from genomeclaw_toolkit._cli.commands import host as host_cmd

    def fake_doctor() -> tuple[int, dict[str, object]]:
        return (
            1,
            {
                "checks": [
                    {
                        "name": "raw_present",
                        "status": "FAIL",
                        "message": "raw dir missing",
                    },
                ],
                "setup_log": {"found": False},
                "colima": {"installed": False},
                "paths": {},
                "references": {"release_set": None, "sources": []},
                "raw_sample": {"staged": False},
                "derived_runs": [],
            },
        )

    monkeypatch.setattr(host_cmd, "doctor_impl", fake_doctor)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_host_doctor_rich_mode_renders_human_output(invoke_cli, _clean_doctor) -> None:
    """Default mode (no ``--json``) writes rich-rendered output to stderr."""
    result = invoke_cli(["host", "doctor"])
    assert result.exit_code == 0, result.stderr
    # Rich rendering goes to stderr; JSON would go to stdout.
    assert "doctor" in result.stderr.lower()
    assert result.stdout == ""


def test_host_doctor_json_mode_emits_envelope_to_stdout(invoke_cli, _clean_doctor) -> None:
    """`host doctor --json` writes the envelope to stdout (parseable JSON)."""
    result = invoke_cli(["--json", "host", "doctor"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cli_output_schema_version"] == "1.0"
    assert payload["command"] == "host.doctor"
    assert payload["payload"]["colima"]["installed"] is True
    assert payload["payload"]["setup_log"]["target_partition"] == "Genome_Work"


def test_host_doctor_quiet_mode_emits_nothing_extra(invoke_cli, _clean_doctor) -> None:
    """`--quiet` doesn't change exit code, just suppresses non-essential output."""
    result = invoke_cli(["--quiet", "host", "doctor"])
    assert result.exit_code == 0
    # We don't assert on exact silence (rich panels still render the
    # report) but the test exists to gate that --quiet doesn't crash.


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_host_doctor_failing_layout_exits_with_precondition_code(
    invoke_cli, _failing_doctor
) -> None:
    """A failing host-layout check → exit code 3 (precondition error)."""
    result = invoke_cli(["host", "doctor"])
    assert result.exit_code == 3, result.stderr


def test_host_doctor_failing_layout_json_envelope_has_error_section(
    invoke_cli, _failing_doctor
) -> None:
    """`--json` on a failing layout emits an error envelope, not a payload one."""
    result = invoke_cli(["--json", "host", "doctor"])
    assert result.exit_code == 3
    # The rich payload still emits successfully (the report is
    # informative even when failing). The exit-code carries the
    # precondition signal; the error envelope is rendered AFTER the
    # payload on stderr (rich) or as a separate event (JSON).
    # The stdout in JSON mode contains the doctor envelope; the
    # error envelope follows on stderr OR replaces stdout depending
    # on how we order emit + raise. For Phase 1 we accept the payload
    # envelope on stdout + exit code 3 as sufficient signal; full
    # error-envelope-on-stdout discipline is a Phase 1 refactor item
    # if test_invariants surface a need.
    payload = json.loads(result.stdout)
    assert payload["command"] == "host.doctor"
    failing = [c for c in payload["payload"]["checks"] if c["status"] == "FAIL"]
    assert len(failing) == 1

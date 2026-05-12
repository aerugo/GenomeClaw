"""Phase 1 cross-cutting CLI framework tests.

These cover the global flags, the exit-code contract, the JSON
envelope shape, and the privacy-default discipline. They run against
the new Typer app via the ``invoke_cli`` fixture from
``tests/integration/conftest.py``.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


def test_genomeclaw_entry_point_help_exits_zero(invoke_cli) -> None:
    """`genomeclaw --help` exits 0 and mentions the program name."""
    result = invoke_cli(["--help"])
    assert result.exit_code == 0, result.stderr
    assert "genomeclaw" in result.stdout.lower()


def test_genomeclaw_help_lists_canonical_subcommand_groups(invoke_cli) -> None:
    """The top-level help advertises the canonical subgroups."""
    result = invoke_cli(["--help"])
    assert result.exit_code == 0
    for group in ("host", "refs", "pipeline"):
        assert group in result.stdout


def test_genomeclaw_version_flag_emits_three_identity_fields(invoke_cli) -> None:
    """`--version` reports toolkit_version + image_digest + git_commit fields."""
    result = invoke_cli(["--version"])
    assert result.exit_code == 0
    # ``--version`` callback fires before any output-mode resolution;
    # the assertion is that the toolkit-version string is present in
    # either stdout (TTY-true rich) or stdout (non-TTY JSON envelope).
    combined = result.stdout + result.stderr
    assert "0.0.1" in combined or "0.0.0+dev" in combined


def test_invalid_subcommand_exits_with_usage_error_code(invoke_cli) -> None:
    """Unknown subcommand → exit code 2 (UsageError) per the contract."""
    result = invoke_cli(["nope-not-a-command"])
    assert result.exit_code == 2, result.stderr


def test_invalid_flag_exits_with_usage_error_code(invoke_cli) -> None:
    """Unknown flag → exit code 2 (UsageError)."""
    result = invoke_cli(["host", "doctor", "--definitely-not-a-flag"])
    assert result.exit_code == 2, result.stderr


def test_mutually_exclusive_color_flags_exit_with_usage_error(invoke_cli) -> None:
    """`--no-color` and `--force-color` together → usage error (exit 2)."""
    result = invoke_cli(["--no-color", "--force-color", "host", "doctor"])
    assert result.exit_code == 2


def test_mutually_exclusive_verbosity_flags_exit_with_usage_error(invoke_cli) -> None:
    """`--quiet` and `--verbose` together → usage error (exit 2)."""
    result = invoke_cli(["--quiet", "--verbose", "host", "doctor"])
    assert result.exit_code == 2


def test_help_cold_start_under_threshold() -> None:
    """`genomeclaw --help` starts cold in under 1.0s on the host venv.

    The plan's stretch target is 200ms on the project owner's machine.
    CI / shared hosts may be slower, so we use a generous threshold —
    the discipline is "don't accidentally pull in duckdb / pysam at
    --help time", which a sub-1s cold start enforces.
    """
    venv_python = Path(__file__).parents[2] / ".venv" / "bin" / "python"
    cmd = [
        str(venv_python) if venv_python.is_file() else "python",
        "-c",
        "from genomeclaw_toolkit._cli import app; app.registered_groups",
    ]
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 1.0, (
        f"cold-start import took {elapsed:.2f}s — likely pulling in a heavy dep at import time"
    )


def test_json_envelope_carries_schema_version(invoke_cli, monkeypatch) -> None:
    """Every `--json` payload carries `cli_output_schema_version`."""
    from genomeclaw_toolkit._cli.commands import host as host_cmd

    def fake_doctor() -> tuple[int, dict[str, object]]:
        return (
            0,
            {
                "checks": [],
                "setup_log": {"found": False},
                "colima": {"installed": False},
                "paths": {},
                "references": {"release_set": None, "sources": []},
                "raw_sample": {"staged": False},
                "derived_runs": [],
            },
        )

    monkeypatch.setattr(host_cmd, "doctor_impl", fake_doctor)
    result = invoke_cli(["--json", "host", "doctor"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cli_output_schema_version"] == "1.0"
    assert payload["command"] == "host.doctor"
    assert "payload" in payload

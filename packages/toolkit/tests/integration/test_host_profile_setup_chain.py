"""Phase 2 (host-profile-personal-context) — `host setup` profile-init chain.

A fresh `host setup` ends by chaining a profile-init step: either an
interactive walk (TTY) or, on a non-TTY / `--skip-profile`, an explicit
recorded skip. The heavy drive/colima orchestrators are stubbed to return
success so the test exercises only the chain wiring + the derived-root
guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit._cli.commands import host as host_cmd
from genomeclaw_toolkit.host_profile import interactive
from genomeclaw_toolkit.host_profile.store import read_profile


@pytest.fixture
def _stub_setup(monkeypatch):
    """Stub the drive/colima orchestrators so setup reaches the profile stage."""
    monkeypatch.setattr(host_cmd, "setup_run_smart", lambda: 0)
    monkeypatch.setattr(
        host_cmd, "setup_run_interactive", lambda **_kwargs: 0
    )


def _derived(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "derived"
    root.mkdir()
    monkeypatch.setenv("GENOMECLAW_DERIVED_ROOT", str(root))
    return root


def test_host_profile_setup_chain_runs_profile_init_at_end(
    tmp_path, invoke_cli, monkeypatch, _stub_setup
) -> None:
    """On a TTY, `host setup` ends by writing a populated profile via the walk."""
    root = _derived(tmp_path, monkeypatch)
    # Pretend interactive + inject a scripted prompter so the walk runs headless.
    monkeypatch.setattr(host_cmd, "stdout_is_tty", lambda: True)
    monkeypatch.setattr(
        interactive,
        "default_prompter",
        lambda: interactive.ScriptedPrompter({"identity.sex_assigned_at_birth": "male"}),
    )

    result = invoke_cli(["host", "setup"])

    assert result.exit_code == 0, result.stderr
    profile = read_profile(root)
    assert profile is not None
    assert profile.meta.skipped_init_at is None  # populated, not skipped
    assert profile.identity.sex_assigned_at_birth == "male"


def test_host_profile_setup_chain_skip_profile_records_meta_skipped_init_at(
    tmp_path, invoke_cli, monkeypatch, _stub_setup
) -> None:
    """`host setup --skip-profile` records the explicit skip."""
    root = _derived(tmp_path, monkeypatch)
    result = invoke_cli(["host", "setup", "--skip-profile"])

    assert result.exit_code == 0, result.stderr
    profile = read_profile(root)
    assert profile is not None
    assert profile.meta.skipped_init_at is not None

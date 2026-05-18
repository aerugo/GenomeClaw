"""Slice 1 of host-mount-lifecycle — required-tools precondition check.

``genomeclaw host setup`` assumes ``colima``, ``docker``, and (on macOS)
``diskutil`` are on PATH. Without an explicit pre-check the user gets a
deep traceback when one is missing; with it they get a one-line message
pointing at the right install command.

These tests cover the pure-Python helper that both ``setup`` and
``doctor`` can reuse. No subprocesses; ``shutil.which`` is monkey-patched
per test.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# check_required_tools — pure detection
# ---------------------------------------------------------------------------


def test_check_required_tools_all_present_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All required binaries on PATH → empty missing list."""
    from genomeclaw_toolkit.prep.setup import _preconditions

    monkeypatch.setattr(
        _preconditions.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}",
    )

    missing = _preconditions.check_required_tools(platform="darwin")
    assert missing == []


def test_check_required_tools_colima_missing_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """colima missing on macOS → reports ``colima`` with brew install hint."""
    from genomeclaw_toolkit.prep.setup import _preconditions

    def _fake_which(name: str) -> str | None:
        return None if name == "colima" else f"/usr/local/bin/{name}"

    monkeypatch.setattr(_preconditions.shutil, "which", _fake_which)

    missing = _preconditions.check_required_tools(platform="darwin")
    assert len(missing) == 1
    tool = missing[0]
    assert tool.name == "colima"
    assert "brew install" in tool.install_hint
    assert "colima" in tool.install_hint


def test_check_required_tools_docker_missing_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docker missing on macOS → reports ``docker`` with brew install hint."""
    from genomeclaw_toolkit.prep.setup import _preconditions

    def _fake_which(name: str) -> str | None:
        return None if name == "docker" else f"/usr/local/bin/{name}"

    monkeypatch.setattr(_preconditions.shutil, "which", _fake_which)

    missing = _preconditions.check_required_tools(platform="darwin")
    assert len(missing) == 1
    assert missing[0].name == "docker"
    assert "brew install" in missing[0].install_hint


def test_check_required_tools_both_missing_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both binaries missing → both reported, hints surfaced once each."""
    from genomeclaw_toolkit.prep.setup import _preconditions

    monkeypatch.setattr(_preconditions.shutil, "which", lambda name: None)

    missing = _preconditions.check_required_tools(platform="darwin")
    missing_names = {t.name for t in missing}
    # On macOS we check at least colima + docker + diskutil. All three
    # missing here; we don't pin the exact count to avoid coupling to a
    # future "samtools required for setup" addition, but each canonical
    # tool must surface.
    assert "colima" in missing_names
    assert "docker" in missing_names


def test_check_required_tools_linux_skips_colima(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Linux, native docker is the install target — colima is irrelevant.

    Linux users run docker directly without a colima VM; the precondition
    check shouldn't flag colima as missing there.
    """
    from genomeclaw_toolkit.prep.setup import _preconditions

    monkeypatch.setattr(_preconditions.shutil, "which", lambda name: None)

    missing = _preconditions.check_required_tools(platform="linux")
    missing_names = {t.name for t in missing}
    assert "colima" not in missing_names
    assert "docker" in missing_names


def test_check_required_tools_linux_emits_apt_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux missing docker → apt/yum-style install hint, not brew."""
    from genomeclaw_toolkit.prep.setup import _preconditions

    monkeypatch.setattr(_preconditions.shutil, "which", lambda name: None)

    missing = _preconditions.check_required_tools(platform="linux")
    docker_entry = next(t for t in missing if t.name == "docker")
    assert "brew" not in docker_entry.install_hint
    # Either apt-get or apt or dnf — accept any of the common variants.
    assert any(s in docker_entry.install_hint for s in ("apt", "dnf", "yum"))


# ---------------------------------------------------------------------------
# format_precondition_error — user-facing message shape
# ---------------------------------------------------------------------------


def test_format_precondition_error_lists_each_tool_with_hint() -> None:
    """The rendered error groups missing tools + their install commands."""
    from genomeclaw_toolkit.prep.setup._preconditions import (
        MissingTool,
        format_precondition_error,
    )

    msg = format_precondition_error(
        [
            MissingTool(name="colima", install_hint="brew install colima"),
            MissingTool(name="docker", install_hint="brew install docker"),
        ]
    )
    assert "colima" in msg
    assert "brew install colima" in msg
    assert "docker" in msg
    assert "brew install docker" in msg


def test_format_precondition_error_empty_returns_empty_string() -> None:
    """No missing tools → empty message (caller treats as no error)."""
    from genomeclaw_toolkit.prep.setup._preconditions import format_precondition_error

    assert format_precondition_error([]) == ""


# ---------------------------------------------------------------------------
# raise_if_missing — integration with setup's error contract
# ---------------------------------------------------------------------------


def test_raise_if_missing_raises_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``raise_if_missing`` (the convenience wrapper for setup's entry path)
    raises a typed error with the user-facing message when tools are missing.
    """
    from genomeclaw_toolkit.prep.setup import _preconditions

    monkeypatch.setattr(_preconditions.shutil, "which", lambda name: None)

    with pytest.raises(_preconditions.MissingRequiredToolsError) as exc_info:
        _preconditions.raise_if_missing(platform="darwin")

    msg = str(exc_info.value)
    assert "colima" in msg or "docker" in msg
    assert "brew install" in msg


def test_raise_if_missing_no_op_when_all_tools_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No missing tools → no exception; caller proceeds to setup."""
    from genomeclaw_toolkit.prep.setup import _preconditions

    monkeypatch.setattr(_preconditions.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    _preconditions.raise_if_missing(platform="darwin")  # must not raise

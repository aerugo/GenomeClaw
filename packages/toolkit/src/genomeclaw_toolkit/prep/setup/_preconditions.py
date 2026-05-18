"""Required-host-tool preconditions for ``genomeclaw host setup``.

Slice 1 of the [host-mount-lifecycle plan](../../../../../docs/plans/active/host-mount-lifecycle/development-plan.md).

Setup assumes ``colima`` (macOS only), ``docker``, and ``diskutil``
(macOS only) are on PATH. Without an explicit precondition check the
user gets a deep traceback when one is missing. This module emits a
typed error with platform-aware install hints so the message is
actionable.

Pure-Python, host-runnable, no I/O beyond ``shutil.which``. Setup's
entry path calls :func:`raise_if_missing` before any destructive step;
doctor can call :func:`check_required_tools` to surface the same
information in its read-only report.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class MissingTool:
    """One host tool that's expected on PATH but isn't.

    Attributes:
        name: Binary name (``"colima"``, ``"docker"``, etc.).
        install_hint: A one-line command the user can run to install it.
            Platform-aware (``brew install ...`` on macOS;
            ``apt-get install ...`` on Linux).
    """

    name: str
    install_hint: str


class MissingRequiredToolsError(RuntimeError):
    """One or more host tools required by ``host setup`` are not on PATH."""


# Per-platform required tool sets. Each entry maps to the install hint
# that gets surfaced when the tool is missing. The hints are deliberately
# one-liners — verbose troubleshooting belongs in the README, not in a
# preflight error.
_DARWIN_REQUIRED: tuple[tuple[str, str], ...] = (
    ("colima", "brew install colima"),
    ("docker", "brew install docker"),
    ("diskutil", "macOS built-in; missing diskutil is unusual — check your shell PATH."),
)
_LINUX_REQUIRED: tuple[tuple[str, str], ...] = (
    # Linux users run docker natively; no colima VM needed. ``apt-get``
    # is the most common; users on dnf / yum / pacman distros will
    # already know how to adapt.
    ("docker", "apt-get install docker.io  (or: dnf install docker, yum install docker)"),
)


def _required_tools_for(platform: str) -> tuple[tuple[str, str], ...]:
    """Pick the platform-specific required-tool list."""
    if platform == "darwin":
        return _DARWIN_REQUIRED
    return _LINUX_REQUIRED


def check_required_tools(*, platform: str | None = None) -> list[MissingTool]:
    """Return the list of required host tools that aren't on PATH.

    Args:
        platform: ``"darwin"`` or ``"linux"``. Defaults to
            :data:`sys.platform`. Tests pass an explicit value.

    Returns:
        A possibly-empty list of :class:`MissingTool` for tools that
        ``shutil.which`` failed to locate.
    """
    if platform is None:
        platform = sys.platform
    missing: list[MissingTool] = []
    for name, hint in _required_tools_for(platform):
        if shutil.which(name) is None:
            missing.append(MissingTool(name=name, install_hint=hint))
    return missing


def format_precondition_error(missing: list[MissingTool]) -> str:
    """Render the user-facing error string for a list of missing tools.

    Empty input → empty string (caller treats as no error). Non-empty
    input → multi-line message: a one-line header, one bullet per tool
    with its install hint, and a closing line that points at the README.
    """
    if not missing:
        return ""
    lines = ["Required host tools missing from PATH:"]
    for tool in missing:
        lines.append(f"  • {tool.name} — install with: {tool.install_hint}")
    lines.append(
        "After installing, re-run `bin/genomeclaw host setup`. "
        "See the README's 'First-time setup' section for the full flow."
    )
    return "\n".join(lines)


def raise_if_missing(*, platform: str | None = None) -> None:
    """Probe PATH; raise :class:`MissingRequiredToolsError` if anything's missing.

    Convenience wrapper for ``setup``'s entry path. No-op when every
    required tool is on PATH.
    """
    missing = check_required_tools(platform=platform)
    if not missing:
        return
    raise MissingRequiredToolsError(format_precondition_error(missing))


__all__ = [
    "MissingRequiredToolsError",
    "MissingTool",
    "check_required_tools",
    "format_precondition_error",
    "raise_if_missing",
]

"""``--version`` flag + ``version`` subcommand assembly.

Reports three identity fields:

* ``toolkit_version`` — the installed ``genomeclaw-toolkit`` package
  version (sourced from ``importlib.metadata`` so it tracks pyproject).
* ``image_digest`` — sha256 of the toolkit Docker image when running
  inside the container (set by the shim via ``GENOMECLAW_IMAGE_DIGEST``).
  ``None`` when running host-native (dev) or in tests.
* ``git_commit`` — best-effort commit hash when running from a git
  checkout. ``None`` when running from an installed wheel.

These three together are what a user (or agent) needs to reproduce a
run: pin the toolkit version + image digest, and the git commit
explains how that version was built.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from genomeclaw_toolkit import __version__ as _toolkit_version

_GIT_HEAD_LOOKUP_TIMEOUT_SEC: Final[float] = 0.5


class VersionPayload(BaseModel):
    """Structured ``--version`` output.

    Same shape in rich and JSON modes — rich just renders the table
    instead of emitting JSON.
    """

    model_config = ConfigDict(extra="forbid")

    toolkit_version: str = Field(description="Installed package version.")
    image_digest: str | None = Field(
        default=None,
        description="sha256 of the Docker image when running in-container; else None.",
    )
    git_commit: str | None = Field(
        default=None,
        description="git HEAD commit when running from a checkout; else None.",
    )


def collect_version() -> VersionPayload:
    """Assemble the version payload from runtime + environment + git.

    Pure read-only — no side effects, no network, no mutation. Safe to
    call from anywhere.

    Returns:
        A populated ``VersionPayload`` with whichever fields are
        resolvable in the current environment.
    """
    return VersionPayload(
        toolkit_version=_toolkit_version,
        image_digest=os.environ.get("GENOMECLAW_IMAGE_DIGEST"),
        git_commit=_resolve_git_commit(),
    )


def _resolve_git_commit() -> str | None:
    """Best-effort lookup of the current git HEAD short SHA.

    Returns ``None`` (without raising) when:
    * git is not on PATH
    * the working tree is not a git checkout
    * the lookup times out (``_GIT_HEAD_LOOKUP_TIMEOUT_SEC``)

    This is a developer-convenience feature — installed wheels won't
    have git context and shouldn't pretend to.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path.cwd(),
            capture_output=True,
            timeout=_GIT_HEAD_LOOKUP_TIMEOUT_SEC,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.decode("utf-8", errors="replace").strip()
    return commit or None


__all__ = ["VersionPayload", "collect_version"]

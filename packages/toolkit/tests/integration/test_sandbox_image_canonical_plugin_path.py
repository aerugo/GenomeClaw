"""Sandbox image carries the plugin inside the Landlock RW baseline.

Phase 2 of the nemoclaw-canonical-integration plan: the GenomeClaw plugin
must live at `/sandbox/build/genomeclaw/` (inside the OpenShell Landlock
RW baseline, but OUTSIDE the auto-scanned extensions tree — `openclaw
plugins install --link` refuses a source path already in the scan tree).
The prior layout under `/opt/genomeclaw/` was outside the Landlock
baseline and produced EACCES on every NemoClaw-managed surface
(dashboard, `nemoclaw connect`, TUI). Structural checks here lock the
new path in place.

Gated on `GENOMECLAW_SANDBOX_IMAGE` per the rest of the sandbox-image
test suite — skips cleanly without a built image. Per `INV-V001`,
verification is structural (`docker run … test -f …`, `openclaw plugins
list` table parsing), not log-grep.

Tracks docs/plans/active/nemoclaw-canonical-integration/.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

CANONICAL_PLUGIN_DIR = "/sandbox/build/genomeclaw"
LEGACY_PLUGIN_DIR = "/opt/genomeclaw"


@pytest.fixture(scope="module")
def sandbox_image() -> str:
    tag = os.environ.get("GENOMECLAW_SANDBOX_IMAGE")
    if not tag:
        pytest.skip(
            "GENOMECLAW_SANDBOX_IMAGE not set; "
            "build packages/nemoclaw-plugin/sandbox/Dockerfile and set the env var."
        )
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not on PATH.")
    proc = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"sandbox image {tag!r} not available locally.")
    return tag


def _docker_run(image: str, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "--user", "sandbox",
            "-e", "HOME=/sandbox",
            "--entrypoint", cmd[0],
            image,
            *cmd[1:],
        ],
        capture_output=True, text=True, check=False,
    )


@pytest.mark.needs_sandbox
def test_plugin_lives_at_canonical_path(sandbox_image: str) -> None:
    """`/sandbox/.openclaw/extensions/genomeclaw/package.json` exists + is readable."""
    proc = _docker_run(sandbox_image, ["test", "-f", f"{CANONICAL_PLUGIN_DIR}/package.json"])
    assert proc.returncode == 0, (
        f"plugin package.json missing at canonical path {CANONICAL_PLUGIN_DIR}/package.json "
        f"in image {sandbox_image!r}. Phase 2 of nemoclaw-canonical-integration "
        f"requires the plugin tree to live under the canonical NemoClaw extensions "
        f"path inside the Landlock baseline. stderr={proc.stderr!r}"
    )


@pytest.mark.needs_sandbox
def test_plugin_dist_index_at_canonical_path(sandbox_image: str) -> None:
    """The compiled entrypoint is at `<canonical>/dist/index.js`."""
    proc = _docker_run(sandbox_image, ["test", "-f", f"{CANONICAL_PLUGIN_DIR}/dist/index.js"])
    assert proc.returncode == 0, (
        f"plugin dist/index.js missing at {CANONICAL_PLUGIN_DIR}/dist/index.js in "
        f"image {sandbox_image!r}. The Dockerfile should build the TypeScript into "
        f"this location, not under /opt/genomeclaw. stderr={proc.stderr!r}"
    )


@pytest.mark.needs_sandbox
def test_plugin_absent_from_legacy_opt_path(sandbox_image: str) -> None:
    """The legacy `/opt/genomeclaw/` directory must NOT exist."""
    proc = _docker_run(sandbox_image, ["test", "!", "-e", LEGACY_PLUGIN_DIR])
    assert proc.returncode == 0, (
        f"legacy plugin path {LEGACY_PLUGIN_DIR} still exists in image {sandbox_image!r}. "
        f"Phase 2 of nemoclaw-canonical-integration migrates the plugin off /opt/ "
        f"because that path is outside the OpenShell Landlock baseline. stderr={proc.stderr!r}"
    )


@pytest.mark.needs_sandbox
def test_plugin_discoverable_by_openclaw_plugins_list(sandbox_image: str) -> None:
    """`openclaw plugins list` reports the `genomeclaw` extension as enabled.

    Structural verification: the table includes a `genomeclaw` row with
    `enabled` status. `openclaw plugins list` renders the source path with
    `~/` (the sandbox user's home), so we don't assert on a literal
    `/sandbox/` substring — the enabled-status presence is the real
    correctness signal.
    """
    proc = _docker_run(sandbox_image, ["openclaw", "plugins", "list"])
    assert proc.returncode == 0, (
        f"openclaw plugins list failed: rc={proc.returncode}; stderr={proc.stderr!r}"
    )
    output = proc.stdout
    assert "genomeclaw" in output, (
        "openclaw plugins list output does not contain 'genomeclaw'. "
        "The plugin must be registered via `openclaw plugins install --link` "
        f"during the image build. Output:\n{output}"
    )
    has_enabled_genomeclaw = any(
        "enabled" in line and "genomeclaw" in line.lower()
        for line in output.splitlines()
    )
    assert has_enabled_genomeclaw, (
        "openclaw plugins list does not show a `genomeclaw` row with "
        f"`enabled` status. The plugin was registered but is not active. "
        f"Output:\n{output}"
    )

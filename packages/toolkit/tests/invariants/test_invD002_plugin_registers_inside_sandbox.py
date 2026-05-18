"""`INV-D002` corollary: the compiled plugin actually loads + registers inside the sandbox.

The Slice D rewrite gave the plugin a runtime dependency on
``@sinclair/typebox`` (the TypeBox schemas for each tool's parameters).
The original Dockerfile copied only ``dist/`` into the extension dir;
that worked for the v0 plugin because its imports were type-only, but
the v1 plugin fails to load with ``ERR_MODULE_NOT_FOUND: Cannot find
package '@sinclair/typebox'`` unless ``node_modules/`` is also copied.

The 2026-05-15 Slice E live sweep discovered this gap empirically and
fixed the Dockerfile (it now ``cp -a node_modules``). This test pins
the fix: a future Dockerfile change that drops ``node_modules`` will
surface here in milliseconds, not as a silent plugin-load failure
during a NemoClaw deploy.

The harness uses Node's ESM loader hooks to mock ``openclaw/plugin-sdk``
in place; the rest of the test exercises the real compiled
``dist/index.js`` against the real Node runtime in the sandbox image.

Gated by ``GENOMECLAW_SANDBOX_IMAGE`` per the rest of the sandbox-image
invariant suite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS_PATH = Path(__file__).resolve().parent / "fixtures" / "sandbox_plugin_harness.mjs"


@pytest.fixture(scope="module")
def sandbox_image() -> str:
    """Resolve the sandbox image tag from env + verify it's locally available."""
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
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"sandbox image {tag!r} not available locally.")
    return tag


@pytest.mark.needs_sandbox
def test_compiled_plugin_registers_five_tools_inside_sandbox(sandbox_image: str) -> None:
    """The compiled plugin loads + registers exactly 5 tools inside the sandbox image.

    Pipes [fixtures/sandbox_plugin_harness.mjs](fixtures/sandbox_plugin_harness.mjs)
    into the sandbox via stdin, runs it with Node, and asserts the
    harness emits the ``PASS:`` line. The harness exits non-zero on
    contract violation (wrong tool count, missing ``outputClass``,
    missing parameters/execute).

    Why pipe-via-stdin rather than ``-v``-mount: colima's bind-mount
    layer is sometimes unreliable for small files; stdin is universal +
    matches how CI would inject the harness.
    """
    harness = _HARNESS_PATH.read_text()
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--entrypoint",
            "bash",
            sandbox_image,
            "-c",
            "cat > /tmp/harness.mjs && node /tmp/harness.mjs",
        ],
        input=harness,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"plugin failed to load inside sandbox image (rc={proc.returncode}):\n{output}"
    )
    assert "tools registered: 5" in output, f"expected 5 tools registered, got output:\n{output}"
    assert "PASS: 5 tools registered with summary outputClass" in output, (
        f"plugin loaded but contract check didn't pass:\n{output}"
    )

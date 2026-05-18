"""Sandbox-image gate: workspace bootstrap files are baked at build time.

Pairs with the slice-4 Dockerfile change (agent-research-and-synthesis Phase
3 slice 4, 2026-05-15): the OpenClaw `pi` agent harness's bootstrap flow
intercepts the user's first turn when IDENTITY.md / USER.md are blank
templates and BOOTSTRAP.md is present. Phase 2a + 2b live smokes saw this
behaviour reproducibly. The slice-4 fix bakes non-blank defaults at build
time so the bootstrap flow is already complete on first user contact.

This test is the **deployment gate**: a future Dockerfile change that
drops the `COPY` of `sandbox/workspace/IDENTITY.md` + `USER.md` (or that
forgets to `rm BOOTSTRAP.md`) gets caught here on the next sandbox-image
rebuild + `needs_sandbox` sweep, rather than silently regressing real
users back into the bootstrap-intercept failure mode.

Gated on `GENOMECLAW_SANDBOX_IMAGE` per the rest of the sandbox-image
invariant suite.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


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


def _read_workspace_file(image: str, name: str) -> tuple[int, str]:
    """`docker run cat /sandbox/.openclaw/workspace/<name>`; returns (rc, stdout)."""
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "cat",
            image,
            f"/sandbox/.openclaw/workspace/{name}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


@pytest.mark.needs_sandbox
def test_baked_identity_md_is_non_empty(sandbox_image: str) -> None:
    """`IDENTITY.md` exists in the baked image + carries non-blank content.

    The pi-harness bootstrap flow triggers when this file is a blank
    template; the slice-4 bake replaces the blank template with a
    GenomeClaw-specific identity so first-run users skip the bootstrap.
    """
    rc, body = _read_workspace_file(sandbox_image, "IDENTITY.md")
    assert rc == 0, (
        f"IDENTITY.md missing from baked image {sandbox_image!r}; the slice-4 "
        f"COPY step in the Dockerfile may have been removed (rc={rc})."
    )
    # Must carry actual content (not just whitespace) and reference the
    # GenomeClaw assistant by name so the agent's identity surfaces
    # consistently to the pi harness.
    assert body.strip(), f"baked IDENTITY.md is whitespace-only: {body!r}"
    assert "GenomeClaw" in body, (
        f"baked IDENTITY.md does not name the GenomeClaw assistant; "
        f"the workspace defaults under packages/nemoclaw-plugin/sandbox/workspace/ "
        f"may have been overwritten by the pi-harness's blank-template defaults. "
        f"Got body prefix: {body[:200]!r}"
    )


@pytest.mark.needs_sandbox
def test_baked_user_md_is_non_empty(sandbox_image: str) -> None:
    """`USER.md` exists in the baked image + carries non-blank content."""
    rc, body = _read_workspace_file(sandbox_image, "USER.md")
    assert rc == 0, (
        f"USER.md missing from baked image {sandbox_image!r}; the slice-4 "
        f"COPY step in the Dockerfile may have been removed (rc={rc})."
    )
    assert body.strip(), f"baked USER.md is whitespace-only: {body!r}"
    # Smoke-check that the file documents the GenomeClaw context (so the
    # agent reads it and recognises the user as a GenomeClaw owner, not
    # a generic OpenClaw account).
    assert "GenomeClaw" in body or "genomeclaw" in body.lower(), (
        f"baked USER.md does not reference the GenomeClaw context; "
        f"the workspace defaults may have been overwritten. "
        f"Got body prefix: {body[:200]!r}"
    )


@pytest.mark.needs_sandbox
def test_baked_image_has_no_bootstrap_md_trigger(sandbox_image: str) -> None:
    """`BOOTSTRAP.md` is absent in the baked image.

    The pi-harness uses BOOTSTRAP.md as the trigger flag for its identity
    setup flow. Even with populated IDENTITY.md / USER.md, a leftover
    BOOTSTRAP.md may re-trigger the intercept. The slice-4 Dockerfile
    runs `rm -f BOOTSTRAP.md` after copying the workspace defaults so
    the trigger is gone too.
    """
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "test",
            sandbox_image,
            "-e",
            "/sandbox/.openclaw/workspace/BOOTSTRAP.md",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # `test -e` returns 0 when the file exists; we want non-zero (absent).
    assert proc.returncode != 0, (
        f"BOOTSTRAP.md is present in baked image {sandbox_image!r}; the slice-4 "
        f"`RUN rm -f /sandbox/.openclaw/workspace/BOOTSTRAP.md` Dockerfile step "
        f"may have been removed. The pi-harness will intercept the user's "
        f"first turn with the identity-bootstrap flow."
    )

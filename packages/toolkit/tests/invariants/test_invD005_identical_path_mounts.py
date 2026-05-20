"""INV-D005 — Identical-Path Bind Mounts for Sibling Containers.

Promotes from Phase 1 of the path-crossing-discipline plan once the
companion integration tests are green.

The cross-cutting invariant: every host path that may flow into a DooD
sibling container's mount argument must be bind-mounted into the parent
toolkit container at its identical absolute path. Without this, the
host docker daemon — which spawns the sibling — cannot resolve the
``-v <host>:<container>`` argument the parent container constructs.

Plan: [docs/plans/active/path-crossing-discipline/](../../../../docs/plans/active/path-crossing-discipline/)
Phase 1: [phases/phase-1.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-1.md)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Reuse fixtures + parser from the integration test file (one source of truth).
from tests.integration.test_shim_identical_path_mounts import (  # type: ignore[import-untyped]
    _parse_mount_args,
    canonical_layout,  # noqa: F401
    fake_docker,  # noqa: F401
)


def test_invD005_pipeline_prs_compute_every_canonical_dir_has_identical_path_mount(
    canonical_layout,  # noqa: F811
    fake_docker,  # noqa: F811
) -> None:
    """INV-D005: for the DooD-spawning ``pipeline prs-compute`` subcommand,
    every host path that may flow into a DooD sibling's ``-v`` mount has
    an identical-path overlay mount in the toolkit container.

    Walks the shim's docker invocation for the subcommand, collects every
    overlay mount where ``source == target``, asserts each of the four
    canonical ``*_DIR`` paths is covered (either as a direct overlay
    source or transitively via a parent common-prefix overlay).
    """
    full_env = dict(os.environ)
    full_env.update(
        {
            "GENOMECLAW_RAW_DIR": str(canonical_layout / "raw"),
            "GENOMECLAW_REF_DIR": str(canonical_layout / "reference"),
            "GENOMECLAW_DERIVED_DIR": str(canonical_layout / "derived"),
            "GENOMECLAW_SCRATCH_DIR": str(canonical_layout / "_scratch"),
        }
    )
    shim = Path(__file__).resolve().parents[4] / "bin" / "genomeclaw"
    result = subprocess.run(
        [str(shim), "pipeline", "prs-compute", "--help"],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]

    for path_dir in [canonical_layout / d for d in ("raw", "reference", "derived", "_scratch")]:
        path_str = str(path_dir)
        covered = any(
            path_str == m.source or path_str.startswith(m.source + "/")
            for m in overlay_mounts
        )
        assert covered, (
            f"INV-D005: no identical-path mount covering {path_dir}; "
            f"overlays: {[m.raw for m in overlay_mounts]}"
        )

    # Negative invariant: the shim must never mount `/` itself.
    assert all(m.source != "/" for m in overlay_mounts), (
        "INV-D005: the shim must never mount `/` itself"
    )

"""Phase 6 — shim publishes per-subdir canonical-mount env vars for DooD.

The factory's translation logic (Phase 6 INV-D006 tightening) needs to map
``/mnt/genomeclaw/<subdir>/...`` → ``<host_form>/...`` in error messages.
The host-form prefix per subdir comes from four env vars the shim already
knows: ``GENOMECLAW_RAW_DIR``, ``GENOMECLAW_REF_DIR``, ``GENOMECLAW_DERIVED_DIR``,
``GENOMECLAW_SCRATCH_DIR``.

Phase 6 extends the shim's DooD ``--env`` block (which already threads
``GENOMECLAW_HOST_ROOTS``) to also thread these four per-subdir variables.
Non-DooD subcommands do NOT receive them — minimal attack surface for
container env (the canonical mounts already cover non-DooD I/O).

Phase plan: [phases/phase-6.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-6.md)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def canonical_layout(tmp_path: Path) -> Path:
    """Mirror the Phase 1 shim-test fixture: canonical four subdirs."""
    root = tmp_path / "Genome_Work" / "genomeclaw"
    root.mkdir(parents=True)
    for sub in ("raw", "reference", "derived", "_scratch"):
        (root / sub).mkdir()
    return root


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same docker-binary stub as the Phase 1 tests use."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "docker_argv.txt"
    fake_docker_bin = fake_bin / "docker"
    fake_docker_bin.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{argv_log}"\nexit 0\n')
    fake_docker_bin.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")

    class _FakeDocker:
        @property
        def recorded_argv(self) -> list[str]:
            return argv_log.read_text().splitlines() if argv_log.exists() else []

    return _FakeDocker()


def _run_shim(
    canonical_root: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    full_env.update(
        {
            "GENOMECLAW_RAW_DIR": str(canonical_root / "raw"),
            "GENOMECLAW_REF_DIR": str(canonical_root / "reference"),
            "GENOMECLAW_DERIVED_DIR": str(canonical_root / "derived"),
            "GENOMECLAW_SCRATCH_DIR": str(canonical_root / "_scratch"),
        }
    )
    if env:
        full_env.update(env)
    shim = Path(__file__).resolve().parents[4] / "bin" / "genomeclaw"
    return subprocess.run(
        [str(shim), *args],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _extract_env_args(argv: list[str]) -> dict[str, str]:
    """Pull ``--env KEY=VAL`` pairs out of a docker argv into a dict."""
    out: dict[str, str] = {}
    for i, tok in enumerate(argv):
        if tok in ("-e", "--env") and i + 1 < len(argv):
            kv = argv[i + 1]
            if "=" in kv:
                k, _, v = kv.partition("=")
                out[k] = v
    return out


# ---------------------------------------------------------------------------
# Test 4 (DooD subcommand path) — per-subdir env vars threaded
# ---------------------------------------------------------------------------


def test_shim_publishes_per_subdir_env_vars_for_dood(canonical_layout: Path, fake_docker) -> None:
    """The shim's DooD env block threads all four canonical ``*_DIR`` env vars.

    The factory's error-translation logic depends on these to render a
    fixable hint when a caller passes ``/mnt/genomeclaw/scratch/foo``."""
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr

    env_args = _extract_env_args(fake_docker.recorded_argv)
    assert env_args.get("GENOMECLAW_RAW_DIR") == str(canonical_layout / "raw"), env_args
    assert env_args.get("GENOMECLAW_REF_DIR") == str(canonical_layout / "reference"), env_args
    assert env_args.get("GENOMECLAW_DERIVED_DIR") == str(canonical_layout / "derived"), env_args
    assert env_args.get("GENOMECLAW_SCRATCH_DIR") == str(canonical_layout / "_scratch"), env_args


# ---------------------------------------------------------------------------
# Test 4b (non-DooD subcommand) — per-subdir env vars NOT threaded
# ---------------------------------------------------------------------------


def test_shim_does_not_publish_per_subdir_env_for_non_dood_subcommand(
    canonical_layout: Path, fake_docker
) -> None:
    """Non-DooD subcommands don't carry the four ``*_DIR`` env vars.

    The canonical mounts already cover their I/O; threading the host paths
    would expose them to non-DooD code with no benefit + a small surface
    cost."""
    result = _run_shim(canonical_layout, "pipeline", "ingest", "--help")
    assert result.returncode == 0, result.stderr

    env_args = _extract_env_args(fake_docker.recorded_argv)
    for key in (
        "GENOMECLAW_RAW_DIR",
        "GENOMECLAW_REF_DIR",
        "GENOMECLAW_DERIVED_DIR",
        "GENOMECLAW_SCRATCH_DIR",
    ):
        assert key not in env_args, (
            f"non-DooD subcommand must NOT thread {key}; got env_args={env_args}"
        )

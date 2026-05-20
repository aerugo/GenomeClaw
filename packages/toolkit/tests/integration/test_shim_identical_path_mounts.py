"""Phase 1 — identical-path bind mounts in the host shim.

The shim ([bin/genomeclaw](../../../../../bin/genomeclaw)) must add an
identical-path overlay mount for ``${canonical_root}`` whenever a
subcommand may spawn DooD sibling containers. Without the overlay, a
sibling container told to mount ``/mnt/genomeclaw/...`` fails because
the host daemon resolves the path against the host filesystem (where
``/mnt/genomeclaw/`` doesn't exist).

These tests don't invoke real docker. They stub the ``docker`` binary
on PATH so the shim's argv is recorded + inspected.

Phase plan: [phases/phase-1.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-1.md)

Promotes: ``INV-D005`` (Identical-Path Bind Mounts for Sibling Containers).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def canonical_layout(tmp_path: Path) -> Path:
    """A temp dir with the canonical four subdirs the shim refuses to start without."""
    root = tmp_path / "Genome_Work" / "genomeclaw"
    root.mkdir(parents=True)
    for sub in ("raw", "reference", "derived", "_scratch"):
        (root / sub).mkdir()
    return root


@dataclass(frozen=True)
class _MountEntry:
    """One parsed ``--mount`` argument."""

    raw: str
    source: str
    target: str
    readonly: bool


def _parse_mount_args(argv: list[str]) -> list[_MountEntry]:
    """Walk an argv list, return parsed ``--mount type=bind,...`` entries."""
    mounts: list[_MountEntry] = []
    for i, tok in enumerate(argv):
        if tok != "--mount":
            continue
        if i + 1 >= len(argv):
            continue
        spec = argv[i + 1]
        kv = dict(part.split("=", 1) for part in spec.split(",") if "=" in part)
        mounts.append(
            _MountEntry(
                raw=spec,
                source=kv.get("source", ""),
                target=kv.get("target", ""),
                # The ``readonly`` token has no value; check key membership too.
                readonly=("readonly" in spec.split(",")),
            )
        )
    return mounts


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Stub the ``docker`` binary; record argv to a file the test can inspect."""

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "docker_argv.txt"
    fake_docker_bin = fake_bin / "docker"
    # Write each arg on its own line to keep parsing simple even when args
    # contain spaces (none of ours do, but defensive).
    fake_docker_bin.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" > "{argv_log}"\n'
        # Exit 0; the shim only execs us, doesn't read output.
        "exit 0\n"
    )
    fake_docker_bin.chmod(0o755)

    # Prepend fake-bin to PATH so the shim's `command -v docker` resolves here.
    # macOS ships its own /usr/bin/docker shim; we override it for this test.
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")

    class _FakeDocker:
        @property
        def recorded_argv(self) -> list[str]:
            if not argv_log.exists():
                return []
            return argv_log.read_text().splitlines()

    return _FakeDocker()


def _run_shim(
    canonical_root: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``bin/genomeclaw <args>`` with the canonical-root env vars set."""
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


# ---------------------------------------------------------------------------
# Test 1 — today-shape preserved when GENOMECLAW_DOOD unset (and non-DooD cmd)
# ---------------------------------------------------------------------------


def test_shim_no_overlay_when_dood_env_unset(canonical_layout: Path, fake_docker) -> None:
    """Without ``GENOMECLAW_DOOD=1`` + non-DooD subcommand: today-shape mounts only.

    The canonical four mounts target ``/mnt/genomeclaw/{raw,reference,derived,
    scratch}``. No identical-path overlay where source == target.
    """
    result = _run_shim(canonical_layout, "pipeline", "ingest", "--help")
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]
    assert overlay_mounts == [], (
        f"non-DooD subcommand should not add identical-path overlay; got: {overlay_mounts}"
    )


# ---------------------------------------------------------------------------
# Test 2 — overlay appears when GENOMECLAW_DOOD=1 is set explicitly
# ---------------------------------------------------------------------------


def test_shim_adds_identical_path_overlay_when_dood_env_set(
    canonical_layout: Path, fake_docker
) -> None:
    """With ``GENOMECLAW_DOOD=1``: an identical-path overlay covering the canonical root.

    For the canonical layout, the four ``*_DIR`` paths share
    ``canonical_layout`` as a common prefix. A single overlay covers all four.
    """
    result = _run_shim(
        canonical_layout, "pipeline", "ingest", "--help", env={"GENOMECLAW_DOOD": "1"}
    )
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    # Exclude /var/run/docker.sock — that's the DooD socket mount, also
    # identical-path but unrelated to the canonical-root overlay this test
    # is verifying.
    overlay_mounts = [
        m for m in mounts if m.source == m.target and m.source != "/var/run/docker.sock"
    ]
    assert overlay_mounts, f"expected at least one identical-path overlay mount; got: {mounts}"
    # The overlay source must be the canonical root (or one of the four subdirs
    # in the fall-back case). Either way, the source must be under
    # canonical_layout AND target == source.
    for m in overlay_mounts:
        assert str(m.source).startswith(str(canonical_layout)), (
            f"overlay source must be under canonical layout; got: {m.source}"
        )
        assert m.target == m.source


# ---------------------------------------------------------------------------
# Test 3 — auto-set for `pipeline prs-compute` (the DooD-spawning subcommand)
# ---------------------------------------------------------------------------


def test_shim_auto_sets_dood_env_for_pipeline_prs_compute(
    canonical_layout: Path, fake_docker
) -> None:
    """``pipeline prs-compute`` triggers the overlay even without ``GENOMECLAW_DOOD=1``.

    The shim auto-sets the env for the subset of subcommands that spawn DooD
    siblings. Currently: ``pipeline prs-compute``. Tests for other DooD
    subcommands (e.g., ``prs-prepare-coverage``) land alongside their
    integration work.
    """
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]
    assert overlay_mounts, (
        f"`pipeline prs-compute` must auto-set GENOMECLAW_DOOD=1; got mounts: {mounts}"
    )


# ---------------------------------------------------------------------------
# Test 4 — today-shape preserved for non-DooD subcommand `pipeline ingest`
# ---------------------------------------------------------------------------


def test_shim_keeps_today_shape_for_pipeline_ingest(canonical_layout: Path, fake_docker) -> None:
    """``pipeline ingest`` does NOT spawn DooD siblings → no overlay even with the gate.

    Mirrors test 1 but explicitly names the subcommand to lock the per-
    subcommand gate behavior.
    """
    result = _run_shim(canonical_layout, "pipeline", "ingest", "--help")
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]
    assert overlay_mounts == [], (
        f"`pipeline ingest` is non-DooD; should not add overlay. Got: {overlay_mounts}"
    )


# ---------------------------------------------------------------------------
# Test 5 — split-tree deployments → four separate identical-path overlays
# ---------------------------------------------------------------------------


def test_shim_falls_back_to_four_overlays_when_no_common_prefix(
    tmp_path: Path, fake_docker
) -> None:
    """Split-tree deployments don't break — each ``*_DIR`` is reachable via an overlay.

    Some users have split storage trees (e.g., ``raw`` on one drive,
    ``derived`` on another). The shim must NOT refuse to start; every
    canonical ``*_DIR`` must be reachable inside the container at its
    identical absolute path — either as a direct overlay source OR
    transitively via a parent-directory common-prefix overlay.

    Asserts coverage, not specific mount structure — the impl is free to
    pick a common-prefix overlay or four separate overlays as long as
    every canonical path is covered. The shim must also NEVER mount ``/``.
    """
    # Four roots with shallow nesting; the common prefix may end up being the
    # tmp_path itself, which is fine — what matters is coverage + safety.
    raw_dir = tmp_path / "drive_a" / "raw"
    ref_dir = tmp_path / "drive_b" / "reference"
    derived_dir = tmp_path / "drive_c" / "derived"
    scratch_dir = tmp_path / "drive_d" / "_scratch"
    for d in (raw_dir, ref_dir, derived_dir, scratch_dir):
        d.mkdir(parents=True)

    full_env = dict(os.environ)
    full_env.update(
        {
            "GENOMECLAW_RAW_DIR": str(raw_dir),
            "GENOMECLAW_REF_DIR": str(ref_dir),
            "GENOMECLAW_DERIVED_DIR": str(derived_dir),
            "GENOMECLAW_SCRATCH_DIR": str(scratch_dir),
            "GENOMECLAW_DOOD": "1",
        }
    )
    shim = Path(__file__).resolve().parents[4] / "bin" / "genomeclaw"
    result = subprocess.run(
        [str(shim), "pipeline", "ingest", "--help"],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]

    # Coverage: every canonical *_DIR is reachable via at least one overlay
    # (either source==target match, or transitively via a parent overlay).
    overlay_sources = {m.source for m in overlay_mounts}
    for d in (raw_dir, ref_dir, derived_dir, scratch_dir):
        d_str = str(d)
        covered = any(d_str == src or d_str.startswith(src + "/") for src in overlay_sources)
        assert covered, (
            f"split-tree: {d} must be reachable via an overlay. Overlays: {sorted(overlay_sources)}"
        )
    # Safety: never mount / itself.
    assert "/" not in overlay_sources


# ---------------------------------------------------------------------------
# Test 6 — overlay covering raw/ must be readonly (INV-D001 preservation)
# ---------------------------------------------------------------------------


def test_shim_overlay_raw_remains_readonly(canonical_layout: Path, fake_docker) -> None:
    """Overlay covering ``raw/`` is ``:ro``. INV-D001 holds at the OS layer.

    If the overlay is a common-prefix mount that covers raw/, it must be RO
    so docker accepts it alongside the canonical ``/mnt/genomeclaw/raw,readonly``
    mount (conflicting flags → docker rejects the run).

    If the overlay is a split-tree set of four, the one covering raw/ is RO.
    """
    result = _run_shim(
        canonical_layout, "pipeline", "ingest", "--help", env={"GENOMECLAW_DOOD": "1"}
    )
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]
    # Identify the overlay(s) covering raw/. For canonical layout: one common-
    # prefix overlay (under canonical_layout). For split: a specific overlay
    # whose source is canonical_layout/raw.
    raw_path = str(canonical_layout / "raw")
    covers_raw = [
        m for m in overlay_mounts if raw_path == m.source or raw_path.startswith(m.source + "/")
    ]
    assert covers_raw, (
        f"no overlay covers raw/={raw_path!r}; overlays: {[m.raw for m in overlay_mounts]}"
    )
    for m in covers_raw:
        assert m.readonly, f"overlay covering raw/ must be readonly (INV-D001); got: {m.raw}"


# ---------------------------------------------------------------------------
# Test 7 — invariant test: every host path that may flow to a sibling is visible
# ---------------------------------------------------------------------------


def test_invD005_dood_subcommand_sibling_host_paths_visible(
    canonical_layout: Path, fake_docker
) -> None:
    """INV-D005: every host path that may flow to a DooD sibling has an identical-path mount.

    Walks the shim's docker invocation for ``pipeline prs-compute`` (a DooD
    subcommand), collects every host path that downstream code may pass to a
    ``docker run -v`` sibling, asserts each is bind-mounted at its identical
    absolute path.
    """
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    overlay_mounts = [m for m in mounts if m.source == m.target]

    # Every canonical *_DIR must be reachable at its host absolute path —
    # either directly (split-tree fallback) or via a common-prefix overlay.
    for path_dir in [canonical_layout / d for d in ("raw", "reference", "derived", "_scratch")]:
        covered = any(
            (m.source == str(path_dir)) or (str(path_dir).startswith(m.source + "/"))
            for m in overlay_mounts
        )
        assert covered, (
            f"INV-D005: no identical-path mount covering {path_dir}; "
            f"overlays: {[m.raw for m in overlay_mounts]}"
        )


# ---------------------------------------------------------------------------
# Test 8 — smoke v5 reproducer: the exact failure shape is now impossible
# ---------------------------------------------------------------------------


def test_shim_smoke_v5_reproducer(canonical_layout: Path, fake_docker) -> None:
    """Smoke v5 reproducer — sibling container needs to see ``${scratch_dir}/...``.

    In smoke v5, pgsc_calc spawned sibling containers via DooD with mount
    arguments referencing ``/mnt/genomeclaw/scratch/...``. The host daemon
    resolved those against the host FS where ``/mnt/genomeclaw/`` doesn't
    exist → failure. With Phase 1 in place, the shim has mounted ``scratch_dir``
    at its identical absolute path, so the sibling-spawn path that uses
    the host-path form resolves.
    """
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr

    mounts = _parse_mount_args(fake_docker.recorded_argv)
    # The scratch_dir must be visible at its host absolute path.
    scratch_path = str(canonical_layout / "_scratch")
    overlay_covers_scratch = [
        m
        for m in mounts
        if m.source == m.target
        and (m.source == scratch_path or scratch_path.startswith(m.source + "/"))
    ]
    assert overlay_covers_scratch, (
        f"smoke-v5 reproducer: scratch_dir {scratch_path} must be visible at "
        f"its identical absolute path in the toolkit container. Without this "
        f"mount, pgsc_calc's DooD siblings cannot find merged.vcf.gz when it "
        f"is staged under scratch_dir. Mounts: {[m.raw for m in mounts]}"
    )


# ---------------------------------------------------------------------------
# Test 9 — shim threads GENOMECLAW_HOST_ROOTS through for INV-D006 factory
# ---------------------------------------------------------------------------


def test_shim_threads_host_roots_env_for_invD006_factory(
    canonical_layout: Path, fake_docker
) -> None:
    """The DooD subcommand sets ``--env GENOMECLAW_HOST_ROOTS=<roots>`` on docker run.

    Inside the container, :func:`as_sibling_mountable` (INV-D006) needs to know
    which host-absolute prefixes are visible via the Phase-1 overlay. The shim
    publishes the four canonical ``*_DIR`` paths as a colon-separated list.
    Without this thread-through, a path under ``${canonical_layout}/...`` is
    rejected by the factory even though it's host-visible.
    """
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr

    argv = fake_docker.recorded_argv
    env_args = [
        argv[i + 1] for i, tok in enumerate(argv) if tok in ("-e", "--env") and i + 1 < len(argv)
    ]
    host_roots_entries = [e for e in env_args if e.startswith("GENOMECLAW_HOST_ROOTS=")]
    assert host_roots_entries, (
        f"DooD subcommand must thread GENOMECLAW_HOST_ROOTS through; argv env: {env_args}"
    )
    # The published roots must cover every canonical *_DIR path.
    published = host_roots_entries[0].split("=", 1)[1].split(":")
    for sub in ("raw", "reference", "derived", "_scratch"):
        expected = str(canonical_layout / sub)
        assert expected in published, (
            f"GENOMECLAW_HOST_ROOTS must include {expected!r}; got {published}"
        )


# ---------------------------------------------------------------------------
# Test 10 — shim mounts /var/run/docker.sock for DooD subcommands
# ---------------------------------------------------------------------------


def test_shim_mounts_docker_socket_for_dood_subcommand(
    canonical_layout: Path, fake_docker
) -> None:
    """DooD subcommands MUST bind-mount the host docker socket.

    Without ``/var/run/docker.sock`` mounted, the inside-container nextflow
    / pgsc_calc orchestrator cannot reach the host daemon to spawn sibling
    containers. The pre-discipline smoke driver bypassed the shim with its
    own ``-v /var/run/docker.sock:...`` for this reason; Phase 1 added the
    path overlay but left the socket gap — surfaced by the 2026-05-19 Phase
    5 smoke (nextflow exited rc=1 in 86s with only the version banner on
    stderr because it had no docker daemon to talk to).

    Non-DooD subcommands MUST NOT mount the socket (minimal-attack-surface).
    """
    # DooD subcommand → socket mounted.
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr
    mounts = _parse_mount_args(fake_docker.recorded_argv)
    socket_mounts = [
        m for m in mounts if m.source == "/var/run/docker.sock"
    ]
    assert socket_mounts, (
        f"DooD subcommand must bind-mount /var/run/docker.sock; got: {[m.raw for m in mounts]}"
    )
    assert socket_mounts[0].target == "/var/run/docker.sock", (
        f"socket must target /var/run/docker.sock; got: {socket_mounts[0]}"
    )


def test_shim_does_not_mount_docker_socket_for_non_dood_subcommand(
    canonical_layout: Path, fake_docker
) -> None:
    """Non-DooD subcommands MUST NOT mount the docker socket.

    The socket is a powerful capability; minimal-attack-surface dictates the
    shim only exposes it for the subcommands that actually need DooD."""
    result = _run_shim(canonical_layout, "pipeline", "ingest", "--help")
    assert result.returncode == 0, result.stderr
    mounts = _parse_mount_args(fake_docker.recorded_argv)
    socket_mounts = [m for m in mounts if m.source == "/var/run/docker.sock"]
    assert not socket_mounts, (
        f"non-DooD subcommand must NOT mount the docker socket; got: {socket_mounts}"
    )


# ---------------------------------------------------------------------------
# Test 11 — GENOMECLAW_DOOD_USER override for strict-permission Linux daemons
# ---------------------------------------------------------------------------


def test_shim_defaults_dood_user_to_root_for_socket_access(
    canonical_layout: Path, fake_docker
) -> None:
    """DooD subcommands default to ``--user 0:0`` (root inside the container).

    The docker socket inside the toolkit container is group-owned by an
    engine-VM-specific GID (e.g., 991 on colima); the host user typically
    isn't in that group. Running as root sidesteps the group-membership
    matrix at the cost of host-side root ownership on `_scratch/` and
    `derived/`. Phase 5 smoke 2026-05-19 surfaced the original
    `${uid}:${gid}` default silently failing with `permission denied` on
    the socket; the empty stderr made the cause undiagnosable from outside.
    """
    result = _run_shim(canonical_layout, "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr
    argv = fake_docker.recorded_argv
    user_idx = argv.index("--user") if "--user" in argv else -1
    assert user_idx >= 0 and argv[user_idx + 1] == "0:0", (
        f"DooD subcommands must default to --user 0:0; argv near --user: "
        f"{argv[max(0, user_idx-1):user_idx+3] if user_idx >= 0 else argv[:5]}"
    )


def test_shim_honors_dood_user_override(canonical_layout: Path, fake_docker) -> None:
    """``GENOMECLAW_DOOD_USER`` overrides the default ``0:0`` when set.

    Power users on strict-permission environments who've ensured docker-
    group membership for their host UID can override to keep host-side
    file ownership.
    """
    result = _run_shim(
        canonical_layout,
        "pipeline",
        "prs-compute",
        "--help",
        env={"GENOMECLAW_DOOD_USER": "501:20"},
    )
    assert result.returncode == 0, result.stderr
    argv = fake_docker.recorded_argv
    user_idx = argv.index("--user") if "--user" in argv else -1
    assert user_idx >= 0 and argv[user_idx + 1] == "501:20", (
        f"GENOMECLAW_DOOD_USER override must propagate to --user; argv: {argv}"
    )


def test_shim_auto_dood_detects_pipeline_subcommand_after_global_flags(
    canonical_layout: Path, fake_docker
) -> None:
    """The auto-DooD scan recognises ``pipeline prs-compute`` even when
    preceded by global flags like ``--json`` (the Phase 5 smoke driver style).

    Originally the scan looked only at ``$1 $2``; ``genomeclaw --json pipeline
    prs-compute`` was ``$1=--json $2=pipeline`` and the pattern missed. The
    smoke v3–v5 silently skipped auto-DooD: no socket mount, no HOST_ROOTS
    env var, nextflow exited rc=1 with the version banner the only stderr.
    """
    result = _run_shim(canonical_layout, "--json", "pipeline", "prs-compute", "--help")
    assert result.returncode == 0, result.stderr

    argv = fake_docker.recorded_argv
    # Auto-DooD must have fired: socket mounted + HOST_ROOTS env set + --user 0:0.
    mounts = _parse_mount_args(argv)
    assert any(m.source == "/var/run/docker.sock" for m in mounts), (
        f"auto-DooD with --json prefix must mount docker socket; argv: {argv[:30]}"
    )
    env_args = [
        argv[i + 1] for i, tok in enumerate(argv) if tok in ("-e", "--env") and i + 1 < len(argv)
    ]
    assert any(e.startswith("GENOMECLAW_HOST_ROOTS=") for e in env_args), (
        f"auto-DooD with --json prefix must thread HOST_ROOTS; envs: {env_args}"
    )
    user_idx = argv.index("--user")
    assert argv[user_idx + 1] == "0:0", (
        f"auto-DooD with --json prefix must default --user 0:0; got: {argv[user_idx + 1]}"
    )


def test_shim_keeps_host_user_for_non_dood_subcommand(
    canonical_layout: Path, fake_docker
) -> None:
    """Non-DooD subcommands run as ``${uid}:${gid}`` (host user) so derived
    artifacts land with proper host ownership."""
    result = _run_shim(canonical_layout, "pipeline", "ingest", "--help")
    assert result.returncode == 0, result.stderr
    argv = fake_docker.recorded_argv
    user_idx = argv.index("--user") if "--user" in argv else -1
    assert user_idx >= 0, f"shim must always pass --user; argv: {argv}"
    user_value = argv[user_idx + 1]
    # Whatever the running host user is, NOT 0:0.
    assert user_value != "0:0", (
        f"non-DooD subcommands must keep host UID:GID (not root); got: {user_value}"
    )

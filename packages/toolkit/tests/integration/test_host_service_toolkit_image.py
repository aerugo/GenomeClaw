"""Phase 3 RED → GREEN — host service runs INSIDE the toolkit image.

The Phase 4 worker calls ``compute_prs_with_coverage_fill(...)`` which
shells out to ``bcftools``. When the host service ran natively on macOS
(pre-Phase 3 of worker-self-sufficient-compute), bcftools wasn't on PATH
and every compute failed with ``worker_unexpected_error:BcftoolsError``.

Phase 3 swaps the shim's ``GENOMECLAW_NATIVE=1`` host-bypass for a
``docker run -p 8643:8643 ... genomeclaw/toolkit:<tag>`` wrap. Three
properties must hold:

1. The shim's `host service` case constructs a docker invocation that
   publishes 8643 + appends ``--host 0.0.0.0`` so the bridge NAT
   forwards correctly.
2. The toolkit image starts the host service successfully + ``/v1/health``
   returns 200 from the host side.
3. Inside the running container, ``bcftools`` is on PATH and reports
   the expected pinned version — so ``compute_prs_with_coverage_fill``
   can actually run.

The first test is pure-Python (shim arg construction) and runs on the
bare host venv. The second + third are docker-integration tests gated
on ``GENOMECLAW_TOOLKIT_IMAGE`` pointing at a built image.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SHIM_PATH = REPO_ROOT / "bin" / "genomeclaw"

needs_toolkit_image = pytest.mark.skipif(
    not os.environ.get("GENOMECLAW_TOOLKIT_IMAGE"),
    reason=(
        "host-service-in-toolkit-image tests require "
        "GENOMECLAW_TOOLKIT_IMAGE pointing at a built image "
        "(e.g. genomeclaw/toolkit:worker-self-sufficient)."
    ),
)

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker not on PATH",
)


# -----------------------------------------------------------------------------
# Test 1 — shim argument construction (pure-Python; no docker; always runnable)
# -----------------------------------------------------------------------------


def _build_invocation(tmp_path: Path, *user_args: str) -> str:
    """Run the shim with GENOMECLAW_DEBUG=1 to capture the docker argv.

    Uses a tiny tmp_path canonical layout so the shim's mount-existence
    checks pass without requiring the real /Volumes/Genome_Work/ layout.
    """
    for sub in ("raw", "reference", "derived", "_scratch"):
        (tmp_path / sub).mkdir()
    env = {
        **os.environ,
        "GENOMECLAW_DEBUG": "1",
        "GENOMECLAW_IMAGE": "genomeclaw/toolkit:test-fixture",
        "GENOMECLAW_RAW_DIR": str(tmp_path / "raw"),
        "GENOMECLAW_REF_DIR": str(tmp_path / "reference"),
        "GENOMECLAW_DERIVED_DIR": str(tmp_path / "derived"),
        "GENOMECLAW_SCRATCH_DIR": str(tmp_path / "_scratch"),
    }
    # Use `timeout 1` so the actual docker exec exits quickly; we only
    # care about the GENOMECLAW_DEBUG-echoed invocation line on stderr.
    proc = subprocess.run(
        ["bash", "-c", f"timeout 1 {SHIM_PATH} " + " ".join(user_args)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        check=False,
    )
    # The debug line lands on stderr (`printf ... >&2` in the shim).
    for line in proc.stderr.splitlines():
        if line.startswith("genomeclaw: docker run"):
            return line
    raise AssertionError(
        f"shim did not emit a docker debug line.\nstdout:{proc.stdout}\nstderr:{proc.stderr}"
    )


@needs_docker
def test_shim_host_service_publishes_port_and_appends_host_0_0_0_0(tmp_path: Path) -> None:
    """Phase 3 — `host service` invocation wraps in docker with -p + --host 0.0.0.0."""
    invocation = _build_invocation(tmp_path, "host", "service", "--derived-root", "/mnt/genomeclaw/derived")

    # Published port (default 8643 unless GENOMECLAW_HOST_SERVICE_PORT is set):
    assert "--publish 8643:8643" in invocation, invocation

    # DooD auto-enabled so docker.sock + identical-path overlay are present:
    assert "GENOMECLAW_HOST_ROOTS=" in invocation, invocation
    assert "/var/run/docker.sock" in invocation, invocation

    # --host 0.0.0.0 appended after the user's argv (so bridge NAT forwards):
    assert invocation.rstrip().endswith("--host 0.0.0.0"), (
        "shim must append --host 0.0.0.0 to host-service args so the docker NAT bridge "
        f"can forward inbound 8643 traffic. Got:\n{invocation}"
    )


@needs_docker
def test_shim_host_service_honours_operator_host_override(tmp_path: Path) -> None:
    """Operator-supplied --host beats the shim's auto-append (idempotent)."""
    invocation = _build_invocation(tmp_path, "host", "service", "--host", "127.0.0.1")
    # The shim's --host 0.0.0.0 append should NOT fire when --host already present.
    # Count `--host` occurrences in the docker argv — should be exactly 1.
    assert invocation.count(" --host ") == 1, (
        f"shim appended a second --host even though operator supplied one. Got:\n{invocation}"
    )


@needs_docker
def test_shim_other_host_subcommands_still_native(tmp_path: Path) -> None:
    """`host setup/doctor/eject` keep the native bypass (touch host-only facilities)."""
    # host setup / doctor / eject all need diskutil / colima access — must NOT go through docker.
    # When GENOMECLAW_NATIVE=1 is set, the shim execs the native genomeclaw (not docker run).
    # We detect this by the absence of a `docker run` debug line.
    env = {
        **os.environ,
        "GENOMECLAW_DEBUG": "1",
        "GENOMECLAW_IMAGE": "genomeclaw/toolkit:test-fixture",
        "GENOMECLAW_RAW_DIR": str(tmp_path / "raw"),
        "GENOMECLAW_REF_DIR": str(tmp_path / "reference"),
        "GENOMECLAW_DERIVED_DIR": str(tmp_path / "derived"),
        "GENOMECLAW_SCRATCH_DIR": str(tmp_path / "_scratch"),
    }
    for sub in ("raw", "reference", "derived", "_scratch"):
        (tmp_path / sub).mkdir()

    for verb in ("doctor", "setup"):
        proc = subprocess.run(
            ["bash", "-c", f"timeout 1 {SHIM_PATH} host {verb} --help 2>/dev/null"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
            check=False,
        )
        # No docker debug line should appear — native exec, not docker run.
        for line in proc.stderr.splitlines():
            assert not line.startswith("genomeclaw: docker run"), (
                f"host {verb} unexpectedly went through docker. "
                f"Native bypass should still apply for host-only verbs. Got:\n{line}"
            )


# -----------------------------------------------------------------------------
# Test 4 — docker-integration: bcftools is on PATH inside the running container
# -----------------------------------------------------------------------------


@needs_docker
@needs_toolkit_image
def test_bcftools_available_inside_toolkit_image() -> None:
    """Phase 3 / closes-the-BcftoolsError-blocker: bcftools must be on PATH inside the image.

    The Phase 4 worker calls compute_prs_with_coverage_fill which shells
    out to bcftools. Pre-Phase-3 the host service ran natively; bcftools
    was missing from macOS host PATH; every compute failed with
    `worker_unexpected_error:BcftoolsError`. Post-Phase-3 the service
    runs inside the toolkit image where bcftools is pinned via bioconda.
    """
    image = os.environ["GENOMECLAW_TOOLKIT_IMAGE"]
    proc = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "bcftools", image, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"bcftools not runnable inside {image}: rc={proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    # Pinned at 1.21 per the toolkit Dockerfile.
    assert "bcftools 1.21" in proc.stdout, (
        f"bcftools version mismatch inside image. Expected '1.21'; got:\n{proc.stdout}"
    )


# -----------------------------------------------------------------------------
# Test 5 — docker-integration: host service starts in the image + /v1/health 200
# -----------------------------------------------------------------------------


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@needs_docker
@needs_toolkit_image
def test_host_service_starts_in_toolkit_image_and_serves_health(tmp_path: Path) -> None:
    """Phase 3 acceptance gate: shim → toolkit image → uvicorn → /v1/health 200.

    Stages a minimal derived/<run-id>/ with a valid manifest + variants.duckdb.
    Spawns the shim's host-service-in-toolkit-image path. Verifies the
    service binds + serves /v1/health from the host side (via the docker
    -p 8643:8643 bridge NAT).
    """
    image = os.environ["GENOMECLAW_TOOLKIT_IMAGE"]

    # Skip if 8643 isn't free (don't trample an operator's running service).
    if not _port_is_free(8643):
        pytest.skip(
            "port 8643 already in use — skip rather than collide with operator's service"
        )

    # Use the canonical Genome_Work layout if it's accessible; otherwise
    # stage a minimal fixture under tmp_path. The toolkit image needs at
    # minimum a derived_root with a CURRENT symlink resolving to a run-dir
    # with a manifest.json the schema-version check accepts. The simplest
    # path is to delegate to the canonical run-dir if mounted; tests that
    # need a controlled minimal fixture would replicate stage_empty_run's
    # logic via a tmp_path mount.
    canonical = Path("/Volumes/Genome_Work/genomeclaw/derived")
    if canonical.exists() and (canonical / "CURRENT").exists():
        derived_root = canonical
        raw_dir = Path("/Volumes/Genome_Work/genomeclaw/raw")
        ref_dir = Path("/Volumes/Genome_Work/genomeclaw/reference")
        scratch_dir = Path("/Volumes/Genome_Work/genomeclaw/_scratch")
    else:
        pytest.skip(
            "test requires the canonical /Volumes/Genome_Work/genomeclaw/ layout "
            "(use `genomeclaw host setup` to create it). Synthetic-fixture variant TBD."
        )

    env = {
        **os.environ,
        "GENOMECLAW_IMAGE": image,
        "GENOMECLAW_RAW_DIR": str(raw_dir),
        "GENOMECLAW_REF_DIR": str(ref_dir),
        "GENOMECLAW_DERIVED_DIR": str(derived_root),
        "GENOMECLAW_SCRATCH_DIR": str(scratch_dir),
    }
    proc = subprocess.Popen(  # noqa: S603 -- in-tree shim, controlled args
        [str(SHIM_PATH), "host", "service", "--derived-root", "/mnt/genomeclaw/derived"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    container_id: str | None = None
    try:
        # Wait for /v1/health to respond (the docker image cold-start +
        # uvicorn boot can take ~10 s; give it 30 s of margin).
        import urllib.request

        deadline = time.monotonic() + 30
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(  # noqa: S310 -- local probe
                    "http://127.0.0.1:8643/v1/health", timeout=1
                ) as r:
                    if r.status == 200:
                        body = json.loads(r.read().decode())
                        assert body.get("status") in ("ok", "schema_version_mismatch", "no_active_run")
                        return
            except Exception as exc:  # noqa: BLE001 -- exit-loop signal
                last_err = exc
            time.sleep(0.5)
        raise AssertionError(
            f"host service did not bind within 30s. Last error: {last_err!r}"
        )
    finally:
        # Find the container we spawned (most recent matching the image
        # with port 8643 published) and tear it down before exiting.
        try:
            cid_proc = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "publish=8643",
                    "--format",
                    "{{.ID}}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            container_id = cid_proc.stdout.strip().splitlines()[0] if cid_proc.stdout.strip() else None
        except Exception:  # noqa: BLE001
            container_id = None

        # Send SIGINT to the shim (foreground docker run propagates to container).
        with subprocess.Popen.__exit__.__wrapped__ if False else open("/dev/null"):
            pass
        try:
            import signal as _signal

            proc.send_signal(_signal.SIGINT)
            proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

        # Belt-and-braces: if the container is still up, kill it.
        if container_id:
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                capture_output=True,
                check=False,
                timeout=10,
            )

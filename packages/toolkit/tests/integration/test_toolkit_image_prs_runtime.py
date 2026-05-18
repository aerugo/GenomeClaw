"""PRS Runtime Bootstrap Phase 1 — toolkit image carries the PRS runtime stack.

Image-level smoke verifying the new Stage 1c additions land + are reachable
on the in-container PATH:

1. Nextflow ≥ 23.10.0 (pgsc_calc's documented minimum)
2. JRE 17+ (Nextflow's current minimum)
3. mamba (required by `pgsc_calc -profile conda` for per-process env
   materialisation at first run)
4. Pre-warmed `pgsc_calc` pipeline source at `/opt/pgsc_calc/main.nf` so
   first user invocation is offline + deterministic from the image hash

All four tests are gated on `needs_prs_runtime`: skipped unless the project
owner has built the toolkit image with the PRS runtime stage and exported
`GENOMECLAW_TOOLKIT_PRS_IMAGE` pointing at the tag. See the conftest auto-
skip in `packages/toolkit/tests/conftest.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


@pytest.fixture(scope="module")
def toolkit_prs_image() -> str:
    """Resolve the toolkit-with-PRS-runtime image tag from env + verify locally.

    Mirrors the gate pattern from
    [test_invD002_sandbox_image_no_bio_binaries.py](../invariants/test_invD002_sandbox_image_no_bio_binaries.py).
    Three-step skip: env var → docker on PATH → image present locally
    (no implicit pull during a test run).
    """
    tag = os.environ.get("GENOMECLAW_TOOLKIT_PRS_IMAGE")
    if not tag:
        pytest.skip(
            "GENOMECLAW_TOOLKIT_PRS_IMAGE not set; build the toolkit image with the "
            "prs-runtime stage and set the env var (see prs-runtime-bootstrap plan)."
        )
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not on PATH; install Docker or run inside CI's docker image.")
    proc = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(
            f"toolkit image {tag!r} not available locally "
            f"(`docker image inspect` returned {proc.returncode}); build it first."
        )
    return tag


def _docker_run(image: str, *cmd: str) -> subprocess.CompletedProcess[str]:
    """Run ``docker run --rm <image> <cmd>`` and capture output."""
    return subprocess.run(
        ["docker", "run", "--rm", image, *cmd],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.needs_prs_runtime
def test_toolkit_image_carries_nextflow_at_minimum_version(toolkit_prs_image: str) -> None:
    """`docker run --rm <image> nextflow -version` exits 0 + reports ≥ 23.10.0.

    pgsc_calc's nextflow.config documents `nextflowVersion = '>=23.10.0'`; a
    pre-23.10 Nextflow refuses to run the pipeline.
    """
    proc = _docker_run(toolkit_prs_image, "nextflow", "-version")
    assert proc.returncode == 0, (
        f"nextflow -version failed (rc={proc.returncode}):\n"
        f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    )
    combined = proc.stdout + proc.stderr
    # Nextflow's version banner: "version 24.10.0 build 5928" on line 2.
    # Permissive check: just confirm a major version ≥ 23 is reported.
    import re

    match = re.search(r"version\s+(\d+)\.(\d+)\.(\d+)", combined)
    assert match, f"could not parse nextflow version from:\n{combined}"
    major, minor = int(match.group(1)), int(match.group(2))
    assert (major, minor) >= (23, 10), (
        f"nextflow {major}.{minor}.{match.group(3)} < 23.10.0 (pgsc_calc minimum)"
    )


@pytest.mark.needs_prs_runtime
def test_toolkit_image_carries_jre_17_or_later(toolkit_prs_image: str) -> None:
    """`docker run --rm <image> java -version` exits 0 + reports JRE 17+.

    Nextflow's current releases require Java 17+. ``java -version`` writes to
    stderr by JVM convention.
    """
    proc = _docker_run(toolkit_prs_image, "java", "-version")
    assert proc.returncode == 0, (
        f"java -version failed (rc={proc.returncode}):\n"
        f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    )
    combined = proc.stdout + proc.stderr
    import re

    # Match either "17.0.10" or "17" forms in the version banner.
    match = re.search(r'(?:openjdk|java)\s+version\s+"(\d+)', combined, re.IGNORECASE)
    assert match, f"could not parse java major version from:\n{combined}"
    major = int(match.group(1))
    assert major >= 17, f"java {major} < 17 (Nextflow minimum)"


@pytest.mark.needs_prs_runtime
def test_toolkit_image_carries_mamba_on_path(toolkit_prs_image: str) -> None:
    """`docker run --rm <image> mamba --version` exits 0 + reports a version.

    Required by ``pgsc_calc -profile conda`` to shell out for per-process env
    materialisation at first run. Without mamba on PATH the first PGS compute
    fails opaquely deep inside Nextflow.

    mamba 2.x emits only a bare version number (no "mamba" banner prefix);
    rc==0 + a parseable major.minor in the output is the proof of presence.
    """
    import re

    proc = _docker_run(toolkit_prs_image, "mamba", "--version")
    assert proc.returncode == 0, (
        f"mamba --version failed (rc={proc.returncode}):\n"
        f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    )
    combined = proc.stdout + proc.stderr
    match = re.search(r"(\d+)\.(\d+)", combined)
    assert match, f"could not parse mamba version from:\n{combined}"


@pytest.mark.needs_prs_runtime
def test_toolkit_image_pgsc_calc_pipeline_prewarmed(toolkit_prs_image: str) -> None:
    """`/opt/pgsc_calc/main.nf` exists in the image — pipeline source pre-warmed.

    Confirms ``nextflow pull pgscatalog/pgsc_calc -r <pin>`` ran successfully
    at image-build time. First user invocation does NOT pay a 30-60s GitHub
    pull tax + the image is deterministic from its hash (the pipeline source
    version is locked to the pinned release tag in ``_versions.py``).
    """
    proc = _docker_run(toolkit_prs_image, "test", "-f", "/opt/pgsc_calc/main.nf")
    assert proc.returncode == 0, (
        f"pre-warmed pgsc_calc/main.nf missing from image:\n"
        f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}\n"
        "The Stage 1c `nextflow pull pgscatalog/pgsc_calc -r ...` step must have failed."
    )

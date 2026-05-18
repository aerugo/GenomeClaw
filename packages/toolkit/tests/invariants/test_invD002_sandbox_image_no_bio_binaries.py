"""`INV-D002` — the nemoclaw-plugin sandbox image contains no bioinformatics binaries.

Per [INVARIANTS.md § INV-D002](../../../../../docs/reference/INVARIANTS.md):

> Raw genomic artifacts (FASTQ, BAM/CRAM, VCF, gVCF) and the bioinformatics
> binaries that process them are host-side only. The sandbox image must
> never gain `samtools`, `bcftools`, `bgzip`, `mosdepth`, `vcfanno`, VEP,
> Cyrius, or `pgsc_calc` on PATH — those tools live in the *host* image
> (`genomeclaw/toolkit`), accessed only by the host service.

The check shells out to ``docker run --rm <image> sh -c 'command -v <bin>'``
for each forbidden binary; any successful exit means the binary leaked into
the sandbox + the test fails. Gated on the ``needs_sandbox`` marker:

- Skipped when the ``GENOMECLAW_SANDBOX_IMAGE`` env var is unset.
- Skipped when the Docker CLI isn't available.
- Skipped when the named image isn't locally available (avoids implicit
  network pull during a test run).

Production CI builds the sandbox image and points ``GENOMECLAW_SANDBOX_IMAGE``
at the build tag before running this test.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

# Binaries that must NOT appear in the sandbox image. Drawn from the
# host-side toolkit's installed binary set + every plugin / tool that
# Phase 4 / Phase 6 will land. A future addition to the host toolkit
# (e.g. a new annotator) extends this set + the check stays correct.
_FORBIDDEN_BIO_BINARIES: tuple[str, ...] = (
    # Phase 2/3 — VCF + alignment manipulation
    "samtools",
    "bcftools",
    "bgzip",
    "tabix",
    # Phase 2 — coverage QC
    "mosdepth",
    # Phase 4C — vcfanno overlays
    "vcfanno",
    # Phase 4D — VEP + plugins
    "vep",
    # Phase 6 — Cyrius (CYP2D6 diplotype) + PharmCAT
    "cyrius",
    "pharmcat",
    # Phase 6 — PRS via PGS Catalog
    "pgsc_calc",
    "nextflow",  # pgsc_calc is a Nextflow workflow
)


@pytest.fixture(scope="module")
def sandbox_image() -> str:
    """Resolve the sandbox image tag from env + verify it's locally available.

    Three-step gate; each unmet condition skips the test rather than failing:
    1. ``GENOMECLAW_SANDBOX_IMAGE`` env var must be set.
    2. ``docker`` must be on PATH.
    3. The named image must be present locally (``docker image inspect``
       returns 0 — no implicit pull).
    """
    tag = os.environ.get("GENOMECLAW_SANDBOX_IMAGE")
    if not tag:
        pytest.skip(
            "GENOMECLAW_SANDBOX_IMAGE not set; "
            "build packages/nemoclaw-plugin/sandbox/Dockerfile and set the env var."
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
            f"sandbox image {tag!r} not available locally "
            f"(`docker image inspect` returned {proc.returncode}); "
            "build it first or pull explicitly."
        )
    return tag


@pytest.mark.needs_sandbox
@pytest.mark.parametrize("binary", _FORBIDDEN_BIO_BINARIES)
def test_invD002_sandbox_image_does_not_carry_binary(sandbox_image: str, binary: str) -> None:
    """``docker run --rm <image> command -v <binary>`` must exit non-zero.

    ``command -v`` is POSIX-portable + returns 0 only when the name
    resolves to a runnable executable on PATH (binary, shell function,
    or alias). The sandbox image's ``sh`` is the base image's default
    shell.
    """
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            sandbox_image,
            "-c",
            f"command -v {binary}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, (
        f"INV-D002 violation: sandbox image {sandbox_image!r} carries {binary!r} on PATH "
        f"(stdout={proc.stdout!r}). Bio binaries must live host-side only."
    )

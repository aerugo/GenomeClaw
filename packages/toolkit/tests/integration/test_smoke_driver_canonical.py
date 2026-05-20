"""Phase 6 — smoke driver canonicalisation.

The Phase 5 smoke surfaced ``bin/genomeclaw-prs-smoke`` as a caller that
bypassed the shim with its own ``docker run`` + identical-path overlay.
This was a pre-Phase-1 workaround; Phase 1 made the shim handle the
overlay; the bypass became dead code. The discipline plan didn't include
scripts/drivers as migration targets, so the bypass survived and
silently re-implemented the shim's logic (badly: it didn't pick up the
post-Phase-3 ``GENOMECLAW_HOST_ROOTS`` env-var threading).

Phase 6 ratifies the migration by forbidding ``docker run`` strings in
the smoke driver. Future drivers MUST use the shim (which is the seam
established by INV-D007, the new invariant Phase 6 promotes).

Phase plan: [phases/phase-6.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-6.md)
"""

from __future__ import annotations

from pathlib import Path

# tests/integration/test_X.py → parents[4] is the repo root.
_SMOKE_DRIVER = Path(__file__).resolve().parents[4] / "bin" / "genomeclaw-prs-smoke"


# ---------------------------------------------------------------------------
# Test 7 — driver contains zero `docker run` invocations
# ---------------------------------------------------------------------------


def test_smoke_driver_has_no_bespoke_docker_run() -> None:
    """``bin/genomeclaw-prs-smoke`` contains zero ``docker run`` strings.

    The driver invokes the toolkit only through ``$SHIM`` (= ``bin/genomeclaw``).
    Future scripts inherit the same rule via INV-D007's discovery test
    walking ``bin/``."""
    assert _SMOKE_DRIVER.exists(), f"smoke driver missing: {_SMOKE_DRIVER}"
    text = _SMOKE_DRIVER.read_text()
    # The driver must not invoke `docker run` directly.
    lines_with_docker_run = [
        (i, line)
        for i, line in enumerate(text.splitlines(), start=1)
        # Match only actual invocations: `docker run` as a command, not in comments.
        if "docker run" in line and not line.lstrip().startswith("#")
    ]
    assert not lines_with_docker_run, (
        f"smoke driver must not invoke `docker run` directly (use the shim); "
        f"found at lines: {[i for i, _ in lines_with_docker_run]}"
    )


# ---------------------------------------------------------------------------
# Test 8 — driver passes HOST-form paths (or canonical /mnt/...) consistently
# ---------------------------------------------------------------------------


def test_smoke_driver_passes_host_form_to_dood_flags() -> None:
    """The driver's DooD-bound CLI flags (``--work-dir``, ``--output-root``,
    ``--reference-root``) reference HOST-form path variables, not
    ``*_IN_CONTAINER`` (canonical-mount) ones.

    Static parse of the script. Phase 6's factory tightening (reject
    ``/mnt/genomeclaw/...``) would surface a non-host-form path at smoke
    time, but catching it at static-parse time is faster + clearer."""
    text = _SMOKE_DRIVER.read_text()
    # Lines passing one of the three DooD-bound flags must NOT pass a
    # *_IN_CONTAINER variable as the value.
    dood_flags = ("--work-dir", "--output-root", "--reference-root")
    failures: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for flag in dood_flags:
            if flag in line and "IN_CONTAINER" in line:
                failures.append((i, line.strip()))
    assert not failures, (
        f"DooD-bound flags must reference host-form vars, not *_IN_CONTAINER; "
        f"failing lines: {failures}"
    )

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


def test_shim_adds_genomeclaw_smoke_label_when_run_id_env_set() -> None:
    """prs-smoke-resilience Phase 2.2: when the smoke driver invokes the
    shim, the shim adds ``--label genomeclaw-smoke=<run-id>`` so the
    spawned toolkit container can be tracked + cleaned up after the
    smoke.

    Smoke driver exports ``GENOMECLAW_SMOKE_RUN_ID=<utc-iso>`` before
    invoking the shim; the shim reads that env var and threads it into
    the docker run args. Cleanup pass (smoke driver EXIT trap) calls
    ``docker stop $(docker ps -q --filter label=genomeclaw-smoke=<id>)``
    to kill any leftover sibling containers from the run.
    """
    _SHIM = Path(__file__).resolve().parents[4] / "bin" / "genomeclaw"
    assert _SHIM.exists(), f"shim missing: {_SHIM}"
    text = _SHIM.read_text()
    # The shim must reference GENOMECLAW_SMOKE_RUN_ID and emit a --label
    # flag using its value.
    assert "GENOMECLAW_SMOKE_RUN_ID" in text, (
        "shim must read GENOMECLAW_SMOKE_RUN_ID env var to thread the "
        "smoke-run label through to docker run"
    )
    assert "--label" in text and "genomeclaw-smoke" in text, (
        "shim must add `--label genomeclaw-smoke=<run-id>` to the docker "
        "run args when GENOMECLAW_SMOKE_RUN_ID is set"
    )


def test_smoke_driver_stages_canary_file_for_watchdog() -> None:
    """prs-smoke-resilience Phase 4.2: the smoke driver stages a tiny
    canary file at ``<raw>/.canary`` so the in-flight watchdog can probe
    the bind-mount every 60s. Mount-loss detection in ≤60s vs. the
    25-90 min cost of waiting for the next pgsc_calc task to crash on
    the stale FD (v22g/v22j class)."""
    assert _SMOKE_DRIVER.exists(), f"smoke driver missing: {_SMOKE_DRIVER}"
    text = _SMOKE_DRIVER.read_text()
    assert ".canary" in text, (
        "smoke driver must stage a canary file the watchdog probes"
    )


def test_smoke_driver_runs_watchdog_during_pgsc_calc() -> None:
    """prs-smoke-resilience Phase 4.2: the smoke driver runs a background
    watchdog (probing the canary every 60s) while pgsc_calc is in
    flight. On probe failure, the watchdog signals recovery + kills
    the toolkit container to break the SIGTERM cascade cleanly."""
    assert _SMOKE_DRIVER.exists(), f"smoke driver missing: {_SMOKE_DRIVER}"
    text = _SMOKE_DRIVER.read_text()
    # The watchdog function must exist + reference the canary read-test.
    assert "watchdog" in text.lower(), "smoke driver must define a watchdog function"
    assert "recovery_needed" in text or "RECOVERY_NEEDED" in text, (
        "watchdog must signal recovery via a flag the recovery loop reads"
    )


def test_smoke_driver_recovery_loop_with_bounded_retries() -> None:
    """prs-smoke-resilience Phase 4.3: the smoke driver wraps the
    pgsc_calc invocation in a bounded recovery loop. On mid-run drive
    disconnect (watchdog signals .recovery_needed), the loop kills the
    toolkit container, waits for the drive to stably reconnect, runs
    ``colima stop && colima start`` to refresh the mount, then
    re-invokes pgsc_calc (with `-resume` from Phase 4.1 picking up
    cached work). Bounded to ``--max-recovery-attempts`` (default 3);
    past that, smoke fails with a documented diagnostic."""
    assert _SMOKE_DRIVER.exists(), f"smoke driver missing: {_SMOKE_DRIVER}"
    text = _SMOKE_DRIVER.read_text()
    # Recovery loop terminology must be present.
    assert "max_recovery_attempts" in text.lower() or "MAX_RECOVERY" in text, (
        "smoke driver must implement a bounded recovery loop"
    )
    # The loop runs `colima stop` + `colima start` to refresh the mount.
    assert "colima stop" in text, (
        "recovery loop must `colima stop` before re-mounting"
    )
    assert "colima start" in text, (
        "recovery loop must `colima start` to refresh the bind-mount"
    )


def test_smoke_driver_traps_exit_to_clean_up_labeled_containers() -> None:
    """prs-smoke-resilience Phase 2.2: the smoke driver installs a trap
    on EXIT (and INT/TERM) that cleans up containers labeled with the
    current smoke's run-id. Catches the v22e + v22g zombie pattern
    (pgsc_calc / Nextflow siblings outliving the parent toolkit
    container)."""
    assert _SMOKE_DRIVER.exists(), f"smoke driver missing: {_SMOKE_DRIVER}"
    text = _SMOKE_DRIVER.read_text()
    # Export GENOMECLAW_SMOKE_RUN_ID so the shim picks it up.
    assert "GENOMECLAW_SMOKE_RUN_ID" in text, (
        "smoke driver must export GENOMECLAW_SMOKE_RUN_ID so the shim's "
        "labels carry through"
    )
    # Install an EXIT trap that performs cleanup.
    assert "trap" in text, "smoke driver must install a cleanup trap"
    assert "label=genomeclaw-smoke" in text, (
        "smoke driver's cleanup pass must filter by label=genomeclaw-smoke"
    )


def test_smoke_driver_has_no_bespoke_docker_run() -> None:
    """``bin/genomeclaw-prs-smoke`` contains no ``docker run`` strings
    that invoke the toolkit / pgsc_calc / sibling images.

    The driver invokes the toolkit only through ``$SHIM`` (= ``bin/genomeclaw``).
    Future scripts inherit the same rule via INV-D007's discovery test
    walking ``bin/``.

    **Exception (added 2026-05-21 per prs-smoke-resilience Phase 1)**: a
    pre-flight probe MAY invoke ``docker run --rm ... alpine test -d
    /probe`` to verify Colima's bind-mount visibility BEFORE invoking the
    shim. Chicken-and-egg justification: if Colima's mount is broken,
    the shim can't run, so the probe can't go through the shim. Probe
    runs Alpine (not the genomeclaw image), reads nothing, writes
    nothing, exists only to fail-fast with an actionable diagnostic.
    INV-D007's allow-list discipline applies (see
    ``test_invD007_seam_singularity.py``)."""
    assert _SMOKE_DRIVER.exists(), f"smoke driver missing: {_SMOKE_DRIVER}"
    text = _SMOKE_DRIVER.read_text()
    # The driver must not invoke `docker run` directly EXCEPT for the
    # documented Alpine pre-flight probe.
    lines_with_docker_run = [
        (i, line)
        for i, line in enumerate(text.splitlines(), start=1)
        # Match only actual invocations: `docker run` as a command, not in comments.
        if "docker run" in line and not line.lstrip().startswith("#")
        # Exempt the documented Alpine bind-mount probe (Phase 1 readiness gate).
        and not ("alpine" in line and "test -d /probe" in line)
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

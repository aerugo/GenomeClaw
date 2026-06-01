"""``host`` command group — environment setup, doctor, eject.

Phase 1 fully migrates ``host doctor``: rich-rendered tables on TTY,
structured JSON envelope on ``--json``. ``host setup`` and
``host eject`` ship as thin Typer wrappers delegating to existing
orchestrators — they upgrade to interactive flows + confirmation
prompts in Phase 4.

The orchestrator (:mod:`genomeclaw_toolkit.prep.doctor`) is untouched
by this migration; only the dispatch + rendering layer moves. That
discipline means the existing ``doctor()`` tests stay valid.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal

import typer
from pydantic import BaseModel, ConfigDict, Field

from genomeclaw_toolkit._cli.confirm import require_destructive_confirmation
from genomeclaw_toolkit._cli.console import stdout_is_tty
from genomeclaw_toolkit._cli.errors import (
    DataIntegrityError,
    PreconditionError,
    RuntimeFailure,
    UsageError,
)
from genomeclaw_toolkit._cli.output import emit, mark_stdout_consumed
from genomeclaw_toolkit._cli.renderers.host import (
    render_doctor,
    render_profile,
)
from genomeclaw_toolkit.host_profile.mutate import HostProfileFieldError, apply_set
from genomeclaw_toolkit.host_profile.store import (
    HostProfileCorruptedError,
    HostProfileSchemaUnknownError,
    compute_completeness,
    read_profile,
    write_profile_atomic,
)
from genomeclaw_toolkit.prep.doctor import doctor as doctor_impl
from genomeclaw_toolkit.prep.eject import EjectError, PipelineRunningError
from genomeclaw_toolkit.prep.eject import eject as eject_impl
from genomeclaw_toolkit.prep.setup import (
    run_interactive as setup_run_interactive,
)
from genomeclaw_toolkit.prep.setup import (
    run_smart as setup_run_smart,
)
from genomeclaw_toolkit.schemas.host_profile import HostProfile

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.context import AppContext

# GenomeClaw's canonical host-service port. 8645 (not 8643) because
# DevRelClaw's drg-service occupies 8643; both projects coexist on one
# host by binding distinct ports. See
# docs/reports/genomeclaw-devrelclaw-coexistence-2026-05-24.md.
# Operator override via env var; CLI --port still wins.
_DEFAULT_HOST_SERVICE_PORT: Final[int] = int(
    os.environ.get("GENOMECLAW_HOST_SERVICE_PORT", "8645")
)

# Sentinel return values from the setup orchestrators. ``run_smart``
# returns 2 to signal "needs escalation to the destructive flow";
# ``run_interactive`` returns 2 to signal "validation failed — user
# input is bad". These collide numerically; context disambiguates.
_SMART_DISPATCH_ESCALATION: Final[int] = 2
_SETUP_VALIDATION_EXIT: Final[int] = 2

# ---------------------------------------------------------------------------
# Payload models (the ``host doctor`` JSON schema)
# ---------------------------------------------------------------------------


class _HostCheck(BaseModel):
    """One row of the host-layout check block."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["OK", "FAIL"]
    message: str = ""


class _SetupLog(BaseModel):
    """Setup-audit-log summary."""

    model_config = ConfigDict(extra="forbid")

    found: bool = False
    incomplete: bool = False
    no_events: bool = False
    last_started_at: str | None = None
    last_completed_at: str | None = None
    toolkit_version: str | None = None
    target_partition: str | None = None


class _Colima(BaseModel):
    """colima/lima status block."""

    model_config = ConfigDict(extra="forbid")

    installed: bool = False
    version: str | None = None
    status: str | None = None


class _ReferenceSource(BaseModel):
    """One reference source's classification vs. the active release set."""

    model_config = ConfigDict(extra="forbid")

    source: str
    expected_release: str
    on_disk_release: str | None = None
    status: Literal["OK", "partial", "missing"]
    present_files: tuple[str, ...] = ()
    missing_files: tuple[str, ...] = ()


class _References(BaseModel):
    """The reference-datasets section of the report."""

    model_config = ConfigDict(extra="forbid")

    release_set: str | None = None
    sources: tuple[_ReferenceSource, ...] = ()
    error: str | None = None


class _RawSample(BaseModel):
    """The staged-sample summary."""

    model_config = ConfigDict(extra="forbid")

    staged: bool = False
    sample_id: str | None = None
    files: tuple[str, ...] = ()


class _DerivedRun(BaseModel):
    """One derived run's classification."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    sample_id: str | None = None
    started_at: str | None = None
    stage: Literal["ingested", "normalized", "annotated", "materialized", "unknown"]


class DoctorPayload(BaseModel):
    """Structured ``host doctor`` output.

    Mirrors the existing :func:`genomeclaw_toolkit.prep.doctor.doctor`
    return shape, but with Pydantic field discipline so the JSON
    envelope is schema-validated on construction.
    """

    model_config = ConfigDict(extra="forbid")

    checks: tuple[_HostCheck, ...]
    setup_log: _SetupLog
    colima: _Colima
    paths: dict[str, str] = Field(default_factory=dict)
    references: _References
    raw_sample: _RawSample
    derived_runs: tuple[_DerivedRun, ...] = ()


def _coerce_report(report: dict[str, Any]) -> DoctorPayload:
    """Translate the orchestrator's loosely-typed dict into a typed payload.

    Args:
        report: The ``report_dict`` returned by
            :func:`genomeclaw_toolkit.prep.doctor.doctor`. Field names
            and shapes are stable contracts inside the orchestrator,
            so this is essentially a re-validation pass.

    Returns:
        A fully-validated ``DoctorPayload``.
    """
    return DoctorPayload.model_validate(report)


# ---------------------------------------------------------------------------
# Typer app + commands
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="host",
    help="Manage the host environment: setup, doctor, eject.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command("doctor")
def host_doctor(
    typer_ctx: typer.Context,
    watch: Annotated[
        bool,
        typer.Option(
            "--watch",
            help="Refresh the diagnostic every 2 seconds until interrupted.",
        ),
    ] = False,
) -> None:
    """Diagnose the host's GenomeClaw layout, colima, and on-disk references.

    Read-only. Exits 0 when the host layout is well-formed, exits 3
    when a precondition fails (no canonical layout — run setup first).
    Missing reference data / no staged sample / no derived runs are
    reported but do not change the exit code.

    Also surfaces **stale colima mounts** — entries in ``~/.colima/default/colima.yaml``
    that point at drives not currently plugged in. These cause
    ``colima start`` to fail with ``mkdir … permission denied``; doctor
    warns before that happens and includes a one-line fix (plug in the
    drive, or run ``genomeclaw host eject <drive>`` to remove the entry).

    ``--watch`` refreshes the rendered diagnostic every 2 seconds.
    Suppressed in ``--json`` mode (agents poll the one-shot form on
    their own cadence).
    """
    ctx: AppContext = typer_ctx.obj

    def _snapshot() -> tuple[int, DoctorPayload]:
        exit_code, report = doctor_impl()
        return exit_code, _coerce_report(report)

    if watch and not ctx.is_json:
        from rich.console import Group, RenderableType
        from rich.text import Text

        from genomeclaw_toolkit._cli.watch import watch_loop

        def _renderable() -> RenderableType:
            # Live's contract is "return a renderable"; render_doctor
            # writes to the console directly. Compose a simple Group
            # of the same blocks render_doctor builds.
            _, snap_payload = _snapshot()
            return Group(
                Text(
                    f"checks: {len(snap_payload.checks)} (live refresh every 2s)",
                )
            )

        watch_loop(_renderable)
        return

    exit_code, payload = _snapshot()

    emit(
        ctx=ctx,
        command="host.doctor",
        payload=payload,
        rich_renderer=render_doctor,
    )

    if exit_code != 0:
        raise PreconditionError(
            "Host layout has one or more failing checks; see report above.",
            details={"failing_checks": [c.name for c in payload.checks if c.status == "FAIL"]},
            suggested_actions=["Run `genomeclaw host setup` to create the canonical layout."],
        )


# ---------------------------------------------------------------------------
# Phase-1 thin wrappers (full migration in Phase 4)
# ---------------------------------------------------------------------------


_SETUP_REFORMAT_PHRASE: Final[str] = "REFORMAT GENOMECLAW DRIVE"


class _HostSetupPlanPayload(BaseModel):
    """Stage-1 ``host setup`` envelope: what the command is about to do."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal["plan"] = "plan"
    dry_run: bool
    force_reset: bool
    fetch_all: bool
    source: str | None
    target_volume: str | None


class _HostSetupResultPayload(BaseModel):
    """Stage-2 ``host setup`` envelope: what happened."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal["result"] = "result"
    exit_code: int


def _emit_host_setup_envelope(payload: BaseModel) -> None:
    """Write one JSON envelope (plan or result) for the ``host setup`` stream."""
    import json
    import sys

    envelope = {
        "cli_output_schema_version": "1.0",
        "command": "host.setup",
        "payload": payload.model_dump(exclude_none=True),
    }
    sys.stdout.write(json.dumps(envelope, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()
    mark_stdout_consumed()


@app.command("setup")
def host_setup(
    typer_ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview the planned actions without executing them.",
        ),
    ] = False,
    fetch_all: Annotated[
        bool,
        typer.Option(
            "--fetch-all",
            help="After setup completes, fetch every source in the default release set.",
        ),
    ] = False,
    force_reset: Annotated[
        bool,
        typer.Option(
            "--force-reset",
            help="DESTRUCTIVE: skip smart dispatch and go straight to reformat.",
        ),
    ] = False,
    source: Annotated[
        Path | None,
        typer.Option(
            "--source",
            help="Path to the Nebula deliverable directory.",
        ),
    ] = None,
    target_volume: Annotated[
        str | None,
        typer.Option(
            "--target-volume",
            help="Target volume name or mount point.",
        ),
    ] = None,
    skip_profile: Annotated[
        bool,
        typer.Option(
            "--skip-profile",
            help="Skip the personal-context profile prompt (records meta.skipped_init_at).",
        ),
    ] = False,
    thorough_profile: Annotated[
        bool,
        typer.Option(
            "--thorough-profile",
            help="Run the full profile walk (not just identity) at the end of setup.",
        ),
    ] = False,
) -> None:
    """Lay out the external drive + colima/lima for CRAM-scale pipelines.

    ``--force-reset`` is destructive: it reformats the target drive. The
    command refuses to proceed without one of:

    * ``--yes`` on the command line (scripted/CI use).
    * An interactive TTY where the user types ``REFORMAT GENOMECLAW DRIVE``
      verbatim at the prompt.

    Without either, the command exits with code 2 and an error envelope
    naming both ways forward. The non-destructive smart-dispatch path
    (``host setup`` without ``--force-reset``) is unchanged: the resolver
    refuses to reformat without explicit opt-in, so no extra prompt is
    needed there.
    """
    ctx: AppContext = typer_ctx.obj

    # JSON-mode "plan" envelope (one of two stdout objects in this mode).
    if ctx.is_json:
        _emit_host_setup_envelope(
            _HostSetupPlanPayload(
                dry_run=dry_run,
                force_reset=force_reset,
                fetch_all=fetch_all,
                source=str(source) if source is not None else None,
                target_volume=target_volume,
            )
        )

    if force_reset:
        # Destructive path: require either --yes or the typed phrase.
        require_destructive_confirmation(
            ctx=ctx,
            expected_phrase=_SETUP_REFORMAT_PHRASE,
            operation_description="reformat the GenomeClaw drive",
        )
        rc = setup_run_interactive(
            execute_destructive=not dry_run,
            nebula_dir=source,
            target_mount=target_volume,
            auto_confirm=True,
        )
    else:
        rc = setup_run_smart()
        if rc == _SMART_DISPATCH_ESCALATION:
            rc = setup_run_interactive(
                execute_destructive=not dry_run,
                nebula_dir=source,
                target_mount=target_volume,
                auto_confirm=False,
            )

    if rc != 0:
        # The setup runner uses rc=2 specifically for user-correctable
        # validation errors (invalid Nebula path, same-source-and-target
        # disk, etc.). Map it to ``UsageError`` so the user sees exit
        # code 2 and a clear "fix-your-input" framing. Any other
        # non-zero is treated as a runtime failure.
        if rc == _SETUP_VALIDATION_EXIT:
            raise UsageError(
                "Setup validation failed; see preview above for the offending input.",
                details={"exit_code": rc},
            )
        raise RuntimeFailure(
            "Setup did not complete cleanly.",
            details={"exit_code": rc},
        )

    if fetch_all and not dry_run:
        # Phase-1 thin wrapper: delegate to refs fetch via in-process
        # call. The full ``--fetch-all`` rich-rendered flow lands in
        # Phase 3 when ``refs fetch`` itself migrates.
        from genomeclaw_toolkit._cli.commands.refs import _legacy_fetch_all

        _legacy_fetch_all()

    if not dry_run:
        _run_setup_profile_stage(skip_profile=skip_profile, thorough=thorough_profile)

    if ctx.is_json:
        _emit_host_setup_envelope(_HostSetupResultPayload(exit_code=rc))


class _HostEjectPayload(BaseModel):
    """``host eject`` result envelope."""

    model_config = ConfigDict(extra="forbid")

    drive: str
    force_used: bool
    exit_code: int


@app.command("eject")
def host_eject(
    typer_ctx: typer.Context,
    drive: Annotated[
        str,
        typer.Option(
            "--drive",
            help="Mount point of the drive to eject.",
        ),
    ] = "/Volumes/Genome_Work",
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help=(
                "Bypass the running-pipeline check (does NOT skip "
                "confirmation; use --yes for that)."
            ),
        ),
    ] = False,
) -> None:
    """Stop colima, remove the drive's colima mount entry, and ``diskutil eject``.

    Three steps in order:

    1. ``colima stop`` so no container is reading the drive.
    2. Remove the drive's entry from ``~/.colima/default/colima.yaml``
       (with a timestamped backup). Without this, the next ``colima
       start`` after the drive is unplugged fails with
       ``mkdir /Volumes/<drive>: permission denied``.
    3. ``diskutil eject`` the drive.

    The eject prompt asks the user to type the drive's mount-point
    basename (e.g. ``Genome_Work`` for ``/Volumes/Genome_Work``) — short
    enough to be unobtrusive but specific enough to prevent muscle-
    memory ejection. ``--yes`` bypasses the prompt for scripted use.

    ``--force`` is a separate gate: it bypasses the in-flight-pipeline
    safety check (so you can eject even when a run is mid-flight).
    Passing ``--force`` does **not** imply confirmation.
    """
    ctx: AppContext = typer_ctx.obj
    drive_basename = drive.rstrip("/").rsplit("/", 1)[-1]
    require_destructive_confirmation(
        ctx=ctx,
        expected_phrase=drive_basename,
        operation_description=f"eject {drive}",
    )

    try:
        rc = eject_impl(drive=drive, force=force)
    except PipelineRunningError as exc:
        raise PreconditionError(
            str(exc),
            suggested_actions=["Wait for the in-flight run to finish, or pass --force."],
        ) from exc
    except EjectError as exc:
        raise RuntimeFailure(str(exc)) from exc

    if rc != 0:
        raise RuntimeFailure(f"eject returned non-zero exit code {rc}.")

    emit(
        ctx=ctx,
        command="host.eject",
        payload=_HostEjectPayload(drive=drive, force_used=force, exit_code=rc),
        rich_renderer=lambda _p: None,  # eject_impl already prints its summary
    )


@app.command("service")
def host_service(
    typer_ctx: typer.Context,  # noqa: ARG001 — kept for ctx parity with other commands.
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root containing the CURRENT symlink."),
    ] = Path("/mnt/genomeclaw/derived"),
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help=(
                "Bind address. Defaults to loopback so the service is only "
                "reachable from the host (Phase 5 sandbox reaches it via "
                "OpenShell's L7 proxy on host.openshell.internal)."
            ),
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help=(
                "Bind port. Defaults to the GENOMECLAW_HOST_SERVICE_PORT env "
                "var if set, else 8645 (the GenomeClaw-canonical port; "
                "DevRelClaw uses 8643). Keep the two distinct so both "
                "projects coexist on one host."
            ),
        ),
    ] = _DEFAULT_HOST_SERVICE_PORT,
) -> None:
    """Launch the read-only host service over the active derived run.

    Binds to ``127.0.0.1:8645`` by default (operator-configurable via
    ``GENOMECLAW_HOST_SERVICE_PORT`` env var or ``--port``). See
    ``docs/reports/genomeclaw-devrelclaw-coexistence-2026-05-24.md``
    for the coexistence rationale.
    The service reads ``<derived-root>/CURRENT`` at startup; send the
    process ``SIGHUP`` to re-resolve after a new pipeline run completes.

    The service is read-only: every endpoint is a GET. ``INV-D002`` keeps
    raw genomic artifacts host-side; the sandbox reaches this surface via
    OpenShell's L7 proxy with a policy preset that allows only the
    documented v0 endpoints.

    The earlier ``--reference-dir`` flag (Phase 6 Slice B) was removed in
    agent-research-and-synthesis Phase 1 — the host service no longer
    resolves curated-notes evidence kinds. Lifestyle calibration moved to
    the agent's research-and-synthesis pattern (memory + reasoned
    research at max reasoning per ``INV-A002``).
    """
    import uvicorn

    from genomeclaw_toolkit.service.app import build_app

    uvicorn.run(build_app(derived_root=derived_root), host=host, port=port)


# ---------------------------------------------------------------------------
# host profile — personal-context profile subgroup
# (host-profile-personal-context Phase 2)
# ---------------------------------------------------------------------------

_DEFAULT_DERIVED_ROOT: Final[str] = "/mnt/genomeclaw/derived"
_PROFILE_INIT_COMMAND: Final[str] = "genomeclaw host profile init"


def _resolve_profile_derived_root(derived_root: Path | None) -> Path:
    """Resolve the derived root for profile commands.

    Precedence: explicit ``--derived-root`` > ``GENOMECLAW_DERIVED_ROOT``
    env var > the canonical ``/mnt/genomeclaw/derived`` default. The env
    var is read at call time (not import) so tests can monkeypatch it.
    """
    if derived_root is not None:
        return derived_root
    return Path(os.environ.get("GENOMECLAW_DERIVED_ROOT", _DEFAULT_DERIVED_ROOT))


def _completeness_str_map(profile: HostProfile) -> dict[str, str]:
    """Return the completeness map as a plain ``dict[str, str]`` for payloads."""
    completeness = compute_completeness(profile) or {}
    return {section: str(status) for section, status in completeness.items()}


def _read_profile_or_raise(derived_root: Path) -> HostProfile | None:
    """Read the profile, mapping the typed store errors to CLI errors."""
    try:
        return read_profile(derived_root)
    except (HostProfileCorruptedError, HostProfileSchemaUnknownError) as exc:
        raise DataIntegrityError(
            "host_profile.json is present but could not be read.",
            suggested_actions=[f"Re-author it with `{_PROFILE_INIT_COMMAND}`."],
        ) from exc


def _run_setup_profile_stage(*, skip_profile: bool, thorough: bool) -> None:
    """Chain a profile-init step onto ``host setup`` (side-effect only, best-effort).

    Runs only when setup actually created a derived root, and never
    clobbers an existing populated profile. On a non-TTY (scripted / CI /
    agent) or with ``--skip-profile``, records an explicit
    ``meta.skipped_init_at`` rather than blocking on a prompt — matching
    the existing non-interactive setup discipline.
    """
    root = _resolve_profile_derived_root(None)
    if not root.exists():
        return
    try:
        existing = read_profile(root)
    except (HostProfileCorruptedError, HostProfileSchemaUnknownError):
        existing = None
    if existing is not None and existing.meta.skipped_init_at is None:
        return  # a real profile already exists; setup must never overwrite it

    now = datetime.now(UTC)
    if skip_profile or not stdout_is_tty():
        write_profile_atomic(
            root,
            HostProfile.model_validate(
                {
                    "schema_version": "host_profile/1.0",
                    "meta": {
                        "created_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                        "skipped_init_at": now.isoformat(),
                    },
                    "identity": {},
                }
            ),
        )
        return

    from genomeclaw_toolkit.host_profile import interactive

    write_profile_atomic(root, interactive.build_profile_interactive(now=now, quick=not thorough))


class _ProfileShowPayload(BaseModel):
    """``host profile show`` envelope payload."""

    model_config = ConfigDict(extra="forbid")

    profile: HostProfile | None
    missing: bool
    completeness: dict[str, str] | None = None
    init_command: str | None = None


class _ProfileCompletenessPayload(BaseModel):
    """Per-section completeness payload (rendered by ``render_profile_completeness``)."""

    model_config = ConfigDict(extra="forbid")

    sections: dict[str, str] | None
    missing: bool


class _ProfileSetPayload(BaseModel):
    """``host profile set`` envelope payload — the path written + the new profile."""

    model_config = ConfigDict(extra="forbid")

    path: str
    profile: HostProfile


class _ProfileReviewPayload(BaseModel):
    """``host profile review`` envelope payload."""

    model_config = ConfigDict(extra="forbid")

    profile: HostProfile
    last_full_review_at: str
    completeness: dict[str, str]


class _ProfileInitPayload(BaseModel):
    """``host profile init`` envelope payload."""

    model_config = ConfigDict(extra="forbid")

    profile: HostProfile
    skipped: bool = False


profile_app = typer.Typer(
    name="profile",
    help="View and edit the host personal-context profile (self-reported).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(profile_app, name="profile")


_DERIVED_ROOT_OPTION = typer.Option(
    "--derived-root",
    help=(
        "Derived root holding host_profile.json. Defaults to "
        "$GENOMECLAW_DERIVED_ROOT or /mnt/genomeclaw/derived."
    ),
)


@profile_app.command("show")
def host_profile_show(
    typer_ctx: typer.Context,
    derived_root: Annotated[Path | None, _DERIVED_ROOT_OPTION] = None,
) -> None:
    """Render the current host profile, or a missing-signal panel if none exists."""
    ctx: AppContext = typer_ctx.obj
    root = _resolve_profile_derived_root(derived_root)
    profile = _read_profile_or_raise(root)

    if profile is None:
        payload = _ProfileShowPayload(
            profile=None, missing=True, completeness=None, init_command=_PROFILE_INIT_COMMAND
        )
    else:
        payload = _ProfileShowPayload(
            profile=profile,
            missing=False,
            completeness=_completeness_str_map(profile),
            init_command=None,
        )
    emit(ctx=ctx, command="host.profile.show", payload=payload, rich_renderer=render_profile)


@profile_app.command("set")
def host_profile_set(
    typer_ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Dotted field path, e.g. lifestyle.smoking_status.")],
    value: Annotated[
        str,
        typer.Argument(
            help="New value (bare string / JSON scalar), or a JSON object for `<list>.add`."
        ),
    ],
    derived_root: Annotated[Path | None, _DERIVED_ROOT_OPTION] = None,
) -> None:
    """Set one field (or append one list element) by dotted path."""
    ctx: AppContext = typer_ctx.obj
    root = _resolve_profile_derived_root(derived_root)
    profile = _read_profile_or_raise(root)
    if profile is None:
        raise PreconditionError(
            "No host profile to edit yet.",
            suggested_actions=[f"Create one with `{_PROFILE_INIT_COMMAND}`."],
        )

    try:
        updated = apply_set(profile, path, value)
    except HostProfileFieldError as exc:
        raise UsageError(str(exc), details={"path": path}) from exc

    updated.meta.updated_at = datetime.now(UTC)
    write_profile_atomic(root, updated)

    emit(
        ctx=ctx,
        command="host.profile.set",
        payload=_ProfileSetPayload(path=path, profile=updated),
        rich_renderer=lambda p: render_profile(
            _ProfileShowPayload(
                profile=p.profile,
                missing=False,
                completeness=_completeness_str_map(p.profile),
                init_command=None,
            )
        ),
    )


@profile_app.command("review")
def host_profile_review(
    typer_ctx: typer.Context,
    derived_root: Annotated[Path | None, _DERIVED_ROOT_OPTION] = None,
) -> None:
    """Walk the profile in show-only mode, then stamp ``meta.last_full_review_at``."""
    ctx: AppContext = typer_ctx.obj
    root = _resolve_profile_derived_root(derived_root)
    profile = _read_profile_or_raise(root)
    if profile is None:
        raise PreconditionError(
            "No host profile to review yet.",
            suggested_actions=[f"Create one with `{_PROFILE_INIT_COMMAND}`."],
        )

    now = datetime.now(UTC)
    profile.meta.last_full_review_at = now
    profile.meta.updated_at = now
    write_profile_atomic(root, profile)

    emit(
        ctx=ctx,
        command="host.profile.review",
        payload=_ProfileReviewPayload(
            profile=profile,
            last_full_review_at=now.isoformat(),
            completeness=_completeness_str_map(profile),
        ),
        rich_renderer=lambda p: render_profile(
            _ProfileShowPayload(
                profile=p.profile,
                missing=False,
                completeness=p.completeness,
                init_command=None,
            )
        ),
    )


def _emit_profile_write(
    ctx: AppContext, command: str, payload: BaseModel, profile: HostProfile
) -> None:
    """Emit a write-command envelope, rendering the full profile in rich mode."""
    emit(
        ctx=ctx,
        command=command,
        payload=payload,
        rich_renderer=lambda _p: render_profile(
            _ProfileShowPayload(
                profile=profile,
                missing=False,
                completeness=_completeness_str_map(profile),
                init_command=None,
            )
        ),
    )


@profile_app.command("init")
def host_profile_init(
    typer_ctx: typer.Context,
    quick: Annotated[
        bool, typer.Option("--quick", help="Capture identity (incl. ancestry) only.")
    ] = False,
    skip: Annotated[
        bool,
        typer.Option("--skip", help="Record meta.skipped_init_at and exit without prompting."),
    ] = False,
    derived_root: Annotated[Path | None, _DERIVED_ROOT_OPTION] = None,
) -> None:
    """Author the host profile via an interactive walk (or record an explicit skip)."""
    ctx: AppContext = typer_ctx.obj
    root = _resolve_profile_derived_root(derived_root)
    now = datetime.now(UTC)

    if skip:
        profile = HostProfile.model_validate(
            {
                "schema_version": "host_profile/1.0",
                "meta": {
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "skipped_init_at": now.isoformat(),
                },
                "identity": {},
            }
        )
        write_profile_atomic(root, profile)
        _emit_profile_write(
            ctx, "host.profile.init", _ProfileInitPayload(profile=profile, skipped=True), profile
        )
        return

    # Import lazily so the interactive backend (questionary) is only loaded
    # when an interactive walk actually runs. Tests monkeypatch
    # ``interactive.default_prompter`` to inject a ScriptedPrompter.
    from genomeclaw_toolkit.host_profile import interactive

    profile = interactive.build_profile_interactive(now=now, quick=quick)
    write_profile_atomic(root, profile)
    _emit_profile_write(
        ctx, "host.profile.init", _ProfileInitPayload(profile=profile, skipped=False), profile
    )


def _detect_field_drops(before: HostProfile, after: HostProfile) -> list[str]:
    """Return dotted paths whose previously-set value was removed/nulled by an edit.

    A "drop" is a leaf that had a meaningful value before and is now
    ``None`` / absent. Additive edits (new values) are not drops and skip
    the confirmation gate (INV-D004 — confirm only destructive diffs).
    """
    from genomeclaw_toolkit.host_profile.audit import flatten_dump

    before_flat = flatten_dump(before.model_dump(mode="json"))
    after_flat = flatten_dump(after.model_dump(mode="json"))
    dropped: list[str] = []
    for path, value in before_flat.items():
        if value in (None, "", [], {}):
            continue
        if after_flat.get(path) in (None, "", [], {}):
            dropped.append(path)
    return sorted(dropped)


@profile_app.command("edit")
def host_profile_edit(
    typer_ctx: typer.Context,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the field-drop confirmation gate.")
    ] = False,
    derived_root: Annotated[Path | None, _DERIVED_ROOT_OPTION] = None,
) -> None:
    """Open the profile in ``$EDITOR``, re-validate, and confirm any field drops."""
    import json

    ctx: AppContext = typer_ctx.obj
    root = _resolve_profile_derived_root(derived_root)
    profile = _read_profile_or_raise(root)
    if profile is None:
        raise PreconditionError(
            "No host profile to edit yet.",
            suggested_actions=[f"Create one with `{_PROFILE_INIT_COMMAND}`."],
        )

    from genomeclaw_toolkit.host_profile import interactive

    scaffold = json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True)
    edited = interactive.default_prompter().editor(key="profile.edit", scaffold=scaffold)
    if edited is None or edited.strip() == scaffold.strip():
        # No change (editor aborted or saved unchanged).
        _emit_profile_write(
            ctx, "host.profile.edit", _ProfileInitPayload(profile=profile, skipped=False), profile
        )
        return

    try:
        new_profile = HostProfile.model_validate(json.loads(edited))
    except (json.JSONDecodeError, ValueError) as exc:
        raise UsageError(
            "Edited profile is not valid JSON / does not match the schema.",
            details={"error": str(exc)[:200]},
        ) from exc

    dropped = _detect_field_drops(profile, new_profile)
    if dropped and not (yes or ctx.assume_yes):
        raise PreconditionError(
            "This edit removes previously-recorded values.",
            details={"dropped_paths": dropped},
            suggested_actions=[
                "Re-run `genomeclaw host profile edit --yes` to confirm the removals."
            ],
        )

    new_profile.meta.updated_at = datetime.now(UTC)
    write_profile_atomic(root, new_profile)
    _emit_profile_write(
        ctx,
        "host.profile.edit",
        _ProfileInitPayload(profile=new_profile, skipped=False),
        new_profile,
    )


__all__ = ["DoctorPayload", "app"]

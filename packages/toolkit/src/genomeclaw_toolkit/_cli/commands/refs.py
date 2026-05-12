"""``refs`` command group — reference data: list, fetch, verify, info.

Phase 1 ships ``refs fetch`` as a thin Typer wrapper around the
existing :func:`genomeclaw_toolkit.prep.fetch.fetch` orchestrator. Same
flag shape, same defaults, same behaviour — only the dispatch + error
envelope move.

``refs list``, ``refs verify``, ``refs info`` land in Phase 2.
The fetcher-correctness upgrade (Content-Length + bgzip-EOF check +
resume-on-stall, absorbed from MVP Phase 4C.4 W1 + W1.5) lands in
Phase 3 of this plan.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import BaseModel, ConfigDict

from genomeclaw_toolkit._cli.console import get_console
from genomeclaw_toolkit._cli.errors import (
    DataIntegrityError,
    PreconditionError,
    RuntimeFailure,
    UsageError,
)
from genomeclaw_toolkit._cli.output import emit, mark_stdout_consumed
from genomeclaw_toolkit._cli.renderers.refs import (
    make_fetch_ndjson_emitter,
    make_fetch_progress,
    make_fetch_rich_renderer,
    render_refs_info,
    render_refs_list,
    render_refs_verify,
)
from genomeclaw_toolkit.prep._bgzip import IncompleteBgzip
from genomeclaw_toolkit.prep.fetch import (
    ChecksumMismatch,
    DownloadStalled,
    TruncatedDownload,
    VersionAlreadyExists,
)
from genomeclaw_toolkit.prep.fetch import (
    fetch as fetch_impl,
)
from genomeclaw_toolkit.prep.references import (
    IntegrityFailure,
    ReferenceSourceDetail,
    ReferenceSourceStatus,
    describe_release_set,
    describe_source,
    verify_release_set_integrity,
)

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.context import AppContext

_VALID_FETCH_SOURCES = ("clinvar", "grch38", "gnomad-exomes", "dbsnp")


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class _FetchOnePayload(BaseModel):
    """``refs fetch --source X --release Y`` result."""

    model_config = ConfigDict(extra="forbid")

    source: str
    release: str
    path: str


class _FetchAllPayload(BaseModel):
    """``refs fetch --all`` aggregate result."""

    model_config = ConfigDict(extra="forbid")

    release_set: str
    sources_fetched: tuple[str, ...]


class RefsListPayload(BaseModel):
    """``refs list`` — release-set classification table."""

    model_config = ConfigDict(extra="forbid")

    release_set: str
    reference_root: str
    sources: tuple[ReferenceSourceStatus, ...]


class RefsVerifyPayload(BaseModel):
    """``refs verify`` — bgzip-EOF integrity sweep result."""

    model_config = ConfigDict(extra="forbid")

    release_set: str
    reference_root: str
    files_checked: int
    failures: tuple[IntegrityFailure, ...]


class RefsInfoPayload(BaseModel):
    """``refs info <source>`` — single-source detail."""

    model_config = ConfigDict(extra="forbid")

    reference_root: str
    detail: ReferenceSourceDetail


# ---------------------------------------------------------------------------
# Typer app + commands
# ---------------------------------------------------------------------------


app = typer.Typer(
    name="refs",
    help="Manage reference data: list, fetch, verify, info.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command("fetch")
def refs_fetch(
    typer_ctx: typer.Context,
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            help="Annotation / reference source to fetch.",
        ),
    ] = None,
    release: Annotated[
        str | None,
        typer.Option(
            "--release",
            help="Release / version label (e.g. '2026-04').",
        ),
    ] = None,
    all_sources: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Fetch every source pinned by the active release set.",
        ),
    ] = False,
    release_set: Annotated[
        str | None,
        typer.Option(
            "--release-set",
            help="Named release-set bundled with the toolkit (default: 'default').",
        ),
    ] = None,
    list_release_sets: Annotated[
        bool,
        typer.Option(
            "--list-release-sets",
            help="Print the available release-set names and exit.",
        ),
    ] = False,
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root (default: /mnt/genomeclaw/reference).",
        ),
    ] = Path("/mnt/genomeclaw/reference"),
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="Override the source's canonical published host."),
    ] = None,
    chroms: Annotated[
        str | None,
        typer.Option(
            "--chroms",
            help="Comma-separated chromosome filter for per-chromosome sources.",
        ),
    ] = None,
) -> None:
    """Download reference / annotation data into ``reference/<source>/<release>/``.

    Rich mode renders an inline ``rich.progress.Progress`` panel
    per file (with byte counters, throughput, and ETA). ``--json``
    mode emits an NDJSON event stream to stdout: a first-line schema-
    version envelope (``{"cli_output_schema_version": "1.0", "command":
    "refs.fetch", "stream": true}``) followed by one
    ``{"event": ..., ...}`` line per fetch event (``file_start`` /
    ``file_progress`` / ``file_complete`` / ``file_failed``).

    Integrity failures (Content-Length mismatch, missing BGZF EOF
    marker, exhausted resume budget, MD5 mismatch) surface a
    ``file_failed`` event before the command exits with code 4
    (data-integrity error).
    """
    ctx: AppContext = typer_ctx.obj

    if list_release_sets:
        _emit_release_sets(ctx)
        return

    if all_sources:
        if source is not None or release is not None:
            raise UsageError(
                "--all is mutually exclusive with --source / --release.",
            )
        _fetch_release_set(
            ctx,
            release_set=release_set,
            reference_root=reference_root,
            base_url=base_url,
        )
        return

    if source is None or release is None:
        raise UsageError(
            "--source and --release are required (or pass --all for the curated bundle).",
        )

    if source not in _VALID_FETCH_SOURCES:
        raise UsageError(
            f"Unknown source {source!r}; must be one of {list(_VALID_FETCH_SOURCES)}.",
        )

    chrom_tuple: tuple[str, ...] | None = None
    if chroms is not None:
        chrom_tuple = tuple(c.strip() for c in chroms.split(","))

    _execute_single_fetch(
        ctx,
        source=source,
        release=release,
        reference_root=reference_root,
        base_url=base_url,
        chroms=chrom_tuple,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _emit_release_sets(ctx: AppContext) -> None:
    """Print bundled release-set names + their pins."""
    from genomeclaw_toolkit.prep.release_sets import list_release_sets, load_release_set

    console = get_console()
    names = list_release_sets()
    if not names:
        console.print("[yellow](no release sets bundled with this toolkit)[/yellow]")
        return

    if ctx.is_json:
        # Phase 1 minimal-payload shape; full rich-rendered table for
        # `refs list` is a Phase 2 deliverable.
        import json as _json

        payload = {
            "cli_output_schema_version": "1.0",
            "command": "refs.list_release_sets",
            "payload": {
                "release_sets": [
                    {
                        "name": load_release_set(n).name,
                        "description": load_release_set(n).description,
                        "sources": [
                            {
                                "source": e.source,
                                "release": e.release,
                                "chroms": list(e.chroms) if e.chroms else None,
                            }
                            for e in load_release_set(n).sources
                        ],
                    }
                    for n in names
                ],
            },
        }
        sys.stdout.write(_json.dumps(payload))
        sys.stdout.write("\n")
        sys.stdout.flush()
        mark_stdout_consumed()
        return

    for name in names:
        rs = load_release_set(name)
        console.print(f"[bold]{rs.name}[/bold]  —  {rs.description}")
        for entry in rs.sources:
            suffix = f" (chroms: {len(entry.chroms)})" if entry.chroms else ""
            console.print(f"    {entry.source:<15} {entry.release}{suffix}")


def _do_fetch_one(
    *,
    source: str,
    release: str,
    reference_root: Path,
    base_url: str | None,
    chroms: tuple[str, ...] | None,
    progress_callback: object | None = None,
) -> Path:
    """Invoke the orchestrator's per-source fetch + map exceptions.

    Args:
        source: Source key (``"clinvar"``, ``"grch38"``, …).
        release: Release / version tag (e.g. ``"2026-05-12"``).
        reference_root: Reference root directory.
        base_url: Optional base URL override (test injection).
        chroms: Optional per-chromosome filter for multi-file sources.
        progress_callback: Optional event consumer passed through to the
            fetcher. Rich + NDJSON callers build their own; bulk fetch
            (``--all``) currently passes ``None`` (per-file rich /
            NDJSON across multiple sources is a follow-up).
    """
    try:
        return fetch_impl(
            source=source,
            reference_root=reference_root,
            release=release,
            base_url=base_url,
            chroms=chroms,
            progress_callback=progress_callback,  # type: ignore[arg-type]
        )
    except VersionAlreadyExists as exc:
        raise PreconditionError(
            f"Refusing to overwrite: {exc}",
            suggested_actions=[
                "Remove the prior release dir deliberately if you want to re-fetch.",
            ],
        ) from exc
    except (ChecksumMismatch, IncompleteBgzip, TruncatedDownload, DownloadStalled) as exc:
        # Fetcher integrity exceptions surface as exit-4 (data integrity).
        # The FileFailed event has already been emitted to the callback
        # by ``_fetch_one_file`` before re-raising.
        raise DataIntegrityError(str(exc)) from exc
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def _execute_single_fetch(
    ctx: AppContext,
    *,
    source: str,
    release: str,
    reference_root: Path,
    base_url: str | None,
    chroms: tuple[str, ...] | None,
) -> None:
    """Drive a single-source fetch with mode-appropriate progress output.

    JSON mode: emit a first-line ``cli_output_schema_version`` envelope
    to stdout, then stream NDJSON events as the fetcher emits them. The
    terminal payload-shape stays ``refs.fetch`` so agent parsers can
    correlate the stream with the command.

    Rich mode: drive a :class:`rich.progress.Progress` instance against
    the fetcher's events; print a final "wrote X" line on success.
    """
    if ctx.is_json:
        envelope = {
            "cli_output_schema_version": "1.0",
            "command": "refs.fetch",
            "stream": True,
        }
        sys.stdout.write(json.dumps(envelope, separators=(",", ":")))
        sys.stdout.write("\n")
        sys.stdout.flush()
        mark_stdout_consumed()

        callback = make_fetch_ndjson_emitter(sys.stdout)
        _do_fetch_one(
            source=source,
            release=release,
            reference_root=reference_root,
            base_url=base_url,
            chroms=chroms,
            progress_callback=callback,
        )
        return

    # Rich mode — wrap the fetch in a Progress context manager.
    progress = make_fetch_progress()
    with progress:
        callback = make_fetch_rich_renderer(progress)
        out = _do_fetch_one(
            source=source,
            release=release,
            reference_root=reference_root,
            base_url=base_url,
            chroms=chroms,
            progress_callback=callback,
        )
    if not ctx.is_quiet:
        get_console().print(f"wrote {out}")


def _fetch_release_set(
    ctx: AppContext,
    *,
    release_set: str | None,
    reference_root: Path,
    base_url: str | None,
) -> None:
    """Fetch every source in the named (or default) release set."""
    from genomeclaw_toolkit.prep.release_sets import (
        DEFAULT_RELEASE_SET,
        ReleaseSetNotFound,
        load_release_set,
    )

    try:
        rs = load_release_set(release_set or DEFAULT_RELEASE_SET)
    except ReleaseSetNotFound as exc:
        raise UsageError(str(exc)) from exc

    console = get_console()
    if not ctx.is_quiet and not ctx.is_json:
        console.print(f"fetching release set '{rs.name}' ({len(rs.sources)} source(s))")

    fetched: list[str] = []
    for entry in rs.sources:
        if not ctx.is_quiet and not ctx.is_json:
            console.print(f"--- {entry.source} @ {entry.release} ---")
        try:
            _do_fetch_one(
                source=entry.source,
                release=entry.release,
                reference_root=reference_root,
                base_url=base_url,
                chroms=entry.chroms,
            )
        except PreconditionError:
            # Already-present treated as skip in bulk mode.
            if not ctx.is_quiet and not ctx.is_json:
                # Escape the literal '[skip]' so rich doesn't interpret it as markup.
                console.print(rf"[dim]\[skip] {entry.source}/{entry.release} already present[/dim]")
            continue
        fetched.append(entry.source)

    emit(
        ctx=ctx,
        command="refs.fetch_all",
        payload=_FetchAllPayload(release_set=rs.name, sources_fetched=tuple(fetched)),
        rich_renderer=lambda _p: console.print(f"release set '{rs.name}' fetched"),
    )


def _legacy_fetch_all() -> None:
    """Internal hook for ``host setup --fetch-all``.

    Mirrors the historical behaviour: after ``setup`` finishes, fetch
    the default release set via the shim. This stays around in Phase 1
    because ``host setup`` is still a thin wrapper. Phase 4's full
    setup migration absorbs this directly.
    """
    console = get_console()
    shim_path = os.environ.get("GENOMECLAW_SHIM_PATH")
    if shim_path and Path(shim_path).is_file():
        console.print("\n--- fetching release set 'default' via toolkit image ---")
        proc = subprocess.run(
            [shim_path, "refs", "fetch", "--all"],
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeFailure(
                "refs fetch --all returned non-zero.",
                details={"exit_code": proc.returncode},
            )
        return

    console.print(
        "\n[yellow]warning: GENOMECLAW_SHIM_PATH not set; "
        "skipping post-setup fetch.[/yellow]\n"
        f"run `{sys.executable} -m genomeclaw_toolkit refs fetch --all` "
        "manually to populate references."
    )


@app.command("list")
def refs_list(
    typer_ctx: typer.Context,
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root (default: /mnt/genomeclaw/reference).",
        ),
    ] = Path("/mnt/genomeclaw/reference"),
    release_set: Annotated[
        str | None,
        typer.Option(
            "--release-set",
            help="Named release-set bundled with the toolkit (default: 'default').",
        ),
    ] = None,
) -> None:
    """List every source pinned by the active release set + on-disk status."""
    ctx: AppContext = typer_ctx.obj
    from genomeclaw_toolkit.prep.release_sets import (
        DEFAULT_RELEASE_SET,
        ReleaseSetNotFound,
        load_release_set,
    )

    try:
        rs = load_release_set(release_set or DEFAULT_RELEASE_SET)
    except ReleaseSetNotFound as exc:
        raise UsageError(str(exc)) from exc

    rs_name, statuses = describe_release_set(
        reference_root=reference_root,
        release_set=rs,
    )
    payload = RefsListPayload(
        release_set=rs_name,
        reference_root=str(reference_root),
        sources=tuple(statuses),
    )
    emit(
        ctx=ctx,
        command="refs.list",
        payload=payload,
        rich_renderer=render_refs_list,
    )


@app.command("verify")
def refs_verify(
    typer_ctx: typer.Context,
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root (default: /mnt/genomeclaw/reference).",
        ),
    ] = Path("/mnt/genomeclaw/reference"),
    release_set: Annotated[
        str | None,
        typer.Option(
            "--release-set",
            help="Named release-set bundled with the toolkit (default: 'default').",
        ),
    ] = None,
) -> None:
    """Run a bgzip-EOF integrity sweep across every staged reference file.

    Exits ``0`` when every checked file is intact; exits ``4`` (data
    integrity error) when one or more files fail the EOF-marker check.
    """
    ctx: AppContext = typer_ctx.obj
    from genomeclaw_toolkit.prep.release_sets import (
        DEFAULT_RELEASE_SET,
        ReleaseSetNotFound,
        load_release_set,
    )

    try:
        rs = load_release_set(release_set or DEFAULT_RELEASE_SET)
    except ReleaseSetNotFound as exc:
        raise UsageError(str(exc)) from exc

    rs_name, failures = verify_release_set_integrity(
        reference_root=reference_root,
        release_set=rs,
    )

    # Count expected bgzip files for the "X of Y checked" summary.
    _, statuses = describe_release_set(reference_root=reference_root, release_set=rs)
    bgzip_suffixes = (".vcf.gz", ".vcf.bgz", ".bcf")
    files_checked = sum(
        1
        for s in statuses
        for f in (*s.present_files, *s.missing_files)
        if any(f.endswith(suf) for suf in bgzip_suffixes)
    )

    payload = RefsVerifyPayload(
        release_set=rs_name,
        reference_root=str(reference_root),
        files_checked=files_checked,
        failures=tuple(failures),
    )
    emit(
        ctx=ctx,
        command="refs.verify",
        payload=payload,
        rich_renderer=render_refs_verify,
    )

    if failures:
        raise DataIntegrityError(
            f"{len(failures)} reference file(s) failed the bgzip-EOF integrity check.",
            details={
                "release_set": rs_name,
                "failure_count": len(failures),
                "first_failure": failures[0].relpath,
            },
            suggested_actions=[
                "Re-fetch the affected source(s) via "
                "`genomeclaw refs fetch --source <name> --release <tag>`.",
            ],
        )


@app.command("info")
def refs_info(
    typer_ctx: typer.Context,
    source: Annotated[
        str,
        typer.Argument(
            help="Source name (clinvar / grch38 / gnomad-exomes / dbsnp).",
        ),
    ],
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root (default: /mnt/genomeclaw/reference).",
        ),
    ] = Path("/mnt/genomeclaw/reference"),
    release_set: Annotated[
        str | None,
        typer.Option(
            "--release-set",
            help="Named release-set bundled with the toolkit (default: 'default').",
        ),
    ] = None,
) -> None:
    """Show details for one reference source: release, files, sizes, integrity."""
    ctx: AppContext = typer_ctx.obj
    from genomeclaw_toolkit.prep.release_sets import (
        DEFAULT_RELEASE_SET,
        ReleaseSetNotFound,
        load_release_set,
    )

    try:
        rs = load_release_set(release_set or DEFAULT_RELEASE_SET)
    except ReleaseSetNotFound as exc:
        raise UsageError(str(exc)) from exc

    try:
        detail = describe_source(
            reference_root=reference_root,
            source=source,
            release_set=rs,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc

    payload = RefsInfoPayload(
        reference_root=str(reference_root),
        detail=detail,
    )
    emit(
        ctx=ctx,
        command="refs.info",
        payload=payload,
        rich_renderer=render_refs_info,
    )


__all__ = ["RefsInfoPayload", "RefsListPayload", "RefsVerifyPayload", "app"]

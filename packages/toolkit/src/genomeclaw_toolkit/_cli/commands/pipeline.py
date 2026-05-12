"""``pipeline`` command group — orchestrator wrappers with rich + NDJSON UX.

Phase 5 replaces the Phase-1 thin wrappers with progress-driven
implementations. Each command picks a callback shape based on
``ctx.output_mode``:

* **Rich mode**: ``make_pipeline_rich_renderer()`` returns a callback
  that renders one :class:`rich.panel.Panel` per ``PhaseStart`` /
  ``PhaseComplete`` event.
* **JSON mode**: the command writes a first-line schema-version
  envelope to stdout, then hands :func:`make_pipeline_ndjson_emitter`
  the rest of the stream.

The orchestrators (``ingest`` / ``normalize`` / ``annotate`` /
``materialize``) each emit ``PhaseStart`` at function entry and
``PhaseComplete`` at success. ``pipeline run`` aggregates them across
the four stages and emits a terminal :class:`PipelineComplete`.

`INV-D001`: orchestrators preserve source files. `INV-R001`:
provenance trail is unchanged from pre-migration. `INV-C-cli-output-stability`:
NDJSON output matches the documented schema in
``docs/reference/cli-output-schemas.md``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import BaseModel, ConfigDict

from genomeclaw_toolkit._cli.commands._resolve import (
    AUTODETECT_SENTINEL,
    resolve_ingest_inputs,
    resolve_run_dir,
)
from genomeclaw_toolkit._cli.console import get_console
from genomeclaw_toolkit._cli.errors import PreconditionError, RuntimeFailure, UsageError
from genomeclaw_toolkit._cli.output import emit, mark_stdout_consumed
from genomeclaw_toolkit._cli.renderers.pipeline import (
    make_pipeline_ndjson_emitter,
    make_pipeline_rich_renderer,
)
from genomeclaw_toolkit.prep._events import PhaseFailed, PipelineComplete
from genomeclaw_toolkit.prep.annotate import annotate as annotate_impl
from genomeclaw_toolkit.prep.ingest import ingest as ingest_impl
from genomeclaw_toolkit.prep.materialize import materialize as materialize_impl
from genomeclaw_toolkit.prep.normalize import normalize as normalize_impl
from genomeclaw_toolkit.prep.reference_build import AmbiguousReferenceBuild

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit._cli.context import AppContext
    from genomeclaw_toolkit.prep._events import _ProgressEvent


# ---------------------------------------------------------------------------
# Payloads + helpers
# ---------------------------------------------------------------------------


class _RunDirPayload(BaseModel):
    """Minimal "we wrote here" payload for rich-mode summaries.

    NDJSON mode emits per-event lines instead; this payload only
    surfaces on the rich-mode final summary line.
    """

    model_config = ConfigDict(extra="forbid")

    run_dir: str


def _emit_run_dir(ctx: AppContext, *, command: str, run_dir: Path) -> None:
    """Emit the "wrote X" summary on the rich-mode tail of a pipeline command."""
    emit(
        ctx=ctx,
        command=command,
        payload=_RunDirPayload(run_dir=str(run_dir)),
        rich_renderer=lambda _p: get_console().print(f"wrote {run_dir}"),
    )


def _begin_ndjson_stream(*, command: str) -> None:
    """Write the first-line schema-version envelope for an NDJSON stream."""
    envelope = {
        "cli_output_schema_version": "1.0",
        "command": command,
        "stream": True,
    }
    sys.stdout.write(json.dumps(envelope, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()
    mark_stdout_consumed()


def _build_callback(ctx: AppContext, *, command: str) -> Callable[[_ProgressEvent], None] | None:
    """Pick the right ``progress_callback`` for this output mode.

    In JSON mode, also writes the first-line envelope to stdout before
    returning the per-event emitter.

    Returns:
        A callback consumer, or ``None`` when the command is fully
        quiet (``--quiet`` + rich mode → suppress progress output).
    """
    if ctx.is_json:
        _begin_ndjson_stream(command=command)
        return make_pipeline_ndjson_emitter(sys.stdout)
    if ctx.is_quiet:
        return None
    return make_pipeline_rich_renderer()


def _emit_phase_failed(
    callback: Callable[[_ProgressEvent], None] | None,
    *,
    phase: str,
    error_type: str,
    message: str,
) -> None:
    """Push a ``PhaseFailed`` event through the active callback (if any)."""
    if callback is not None:
        callback(PhaseFailed(phase=phase, error_type=error_type, message=message))


# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------


app = typer.Typer(
    name="pipeline",
    help="Orchestrators: ingest → normalize → annotate → materialize.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


_VCF_HELP = (
    "Path to a bgzipped VCF under raw/. Pass without a value to "
    "autodetect from --raw-root (requires exactly one sample subdirectory)."
)
_REFERENCE_HELP = (
    "Reference directory (e.g. /mnt/genomeclaw/reference/grch38/). Pass "
    "without a value to autodetect the single build dir under --reference-root."
)


@app.command("ingest")
def pipeline_ingest(
    typer_ctx: typer.Context,
    vcf: Annotated[str | None, typer.Option("--vcf", help=_VCF_HELP)] = None,
    reference: Annotated[
        str | None,
        typer.Option("--reference", help=_REFERENCE_HELP),
    ] = None,
    sample_id: Annotated[
        str | None,
        typer.Option(
            "--sample-id",
            help="Short identifier recorded on every variants row.",
        ),
    ] = None,
    raw_root: Annotated[
        Path,
        typer.Option("--raw-root", help="Raw root for --vcf autodetect."),
    ] = Path("/mnt/genomeclaw/raw"),
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root for --reference autodetect.",
        ),
    ] = Path("/mnt/genomeclaw/reference"),
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root."),
    ] = Path("/mnt/genomeclaw/derived"),
    bam: Annotated[
        Path | None,
        typer.Option("--bam", help="Optional source BAM/CRAM for mosdepth coverage."),
    ] = None,
    bed: Annotated[
        Path | None,
        typer.Option("--bed", help="Gene-list BED (required when --bam given)."),
    ] = None,
    reference_fasta: Annotated[
        Path | None,
        typer.Option("--reference-fasta", help="Bgzipped reference fasta (CRAM + left-align)."),
    ] = None,
) -> None:
    """Ingest a VCF into ``derived/<run-id>/`` with full provenance."""
    ctx: AppContext = typer_ctx.obj
    resolved_sample_id, vcf_path, reference_dir = resolve_ingest_inputs(
        vcf=vcf,
        reference=reference,
        sample_id=sample_id,
        raw_root=raw_root,
        reference_root=reference_root,
    )
    callback = _build_callback(ctx, command="pipeline.ingest")
    try:
        run_dir = ingest_impl(
            vcf=vcf_path,
            reference_dir=reference_dir,
            derived_root=derived_root,
            sample_id=resolved_sample_id,
            bam=bam,
            bed=bed,
            reference_fasta=reference_fasta,
            progress_callback=callback,
        )
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="ingest", error_type="precondition_error", message=str(exc)
        )
        raise PreconditionError(str(exc)) from exc
    except (AmbiguousReferenceBuild, ValueError) as exc:
        _emit_phase_failed(callback, phase="ingest", error_type="usage_error", message=str(exc))
        raise UsageError(str(exc)) from exc

    if not ctx.is_json:
        _emit_run_dir(ctx, command="pipeline.ingest", run_dir=run_dir)


@app.command("normalize")
def pipeline_normalize(
    typer_ctx: typer.Context,
    run_dir: Annotated[
        str | None,
        typer.Option(
            "--run-dir",
            help="Path to a derived/<run-id>/ from a prior ingest. "
            "Omit (or pass without a value) to use the CURRENT symlink.",
        ),
    ] = None,
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root for CURRENT autodetect."),
    ] = Path("/mnt/genomeclaw/derived"),
    reference_fasta: Annotated[
        Path | None,
        typer.Option(
            "--reference-fasta",
            help="Bgzipped reference fasta; enables bcftools norm -f left-align.",
        ),
    ] = None,
) -> None:
    """Run bcftools norm; produce ``normalized.vcf.gz`` in the run dir."""
    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)
    callback = _build_callback(ctx, command="pipeline.normalize")
    try:
        out = normalize_impl(
            run_dir=resolved_dir,
            reference_fasta=reference_fasta,
            progress_callback=callback,
        )
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="normalize", error_type="precondition_error", message=str(exc)
        )
        raise PreconditionError(str(exc)) from exc

    if not ctx.is_json:
        _emit_run_dir(ctx, command="pipeline.normalize", run_dir=out)


@app.command("annotate")
def pipeline_annotate(
    typer_ctx: typer.Context,
    run_dir: Annotated[
        str | None,
        typer.Option("--run-dir", help="Derived run dir (or CURRENT autodetect)."),
    ] = None,
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root for CURRENT autodetect."),
    ] = Path("/mnt/genomeclaw/derived"),
    reference_dir: Annotated[
        Path,
        typer.Option("--reference-dir", help="Reference root."),
    ] = Path("/mnt/genomeclaw/reference"),
    clinvar_release: Annotated[
        str | None,
        typer.Option(
            "--clinvar-release",
            help="ClinVar release tag (default: newest under <reference-dir>/clinvar/).",
        ),
    ] = None,
) -> None:
    """Annotate ``normalized.vcf.gz`` via the chained annotation parent."""
    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)
    callback = _build_callback(ctx, command="pipeline.annotate")
    try:
        out = annotate_impl(
            run_dir=resolved_dir,
            reference_dir=reference_dir,
            clinvar_release=clinvar_release,
            progress_callback=callback,
        )
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="annotate", error_type="precondition_error", message=str(exc)
        )
        raise PreconditionError(str(exc)) from exc

    if not ctx.is_json:
        _emit_run_dir(ctx, command="pipeline.annotate", run_dir=out)


@app.command("materialize")
def pipeline_materialize(
    typer_ctx: typer.Context,
    run_dir: Annotated[
        str | None,
        typer.Option("--run-dir", help="Derived run dir (or CURRENT autodetect)."),
    ] = None,
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root for CURRENT autodetect."),
    ] = Path("/mnt/genomeclaw/derived"),
) -> None:
    """Rewrite the variants table from ``normalized.vcf.gz``."""
    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)
    callback = _build_callback(ctx, command="pipeline.materialize")
    try:
        out = materialize_impl(run_dir=resolved_dir, progress_callback=callback)
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="materialize", error_type="precondition_error", message=str(exc)
        )
        raise PreconditionError(str(exc)) from exc

    if not ctx.is_json:
        _emit_run_dir(ctx, command="pipeline.materialize", run_dir=out)


@app.command("run")
def pipeline_run(
    typer_ctx: typer.Context,
    vcf: Annotated[str | None, typer.Option("--vcf", help=_VCF_HELP)] = None,
    reference: Annotated[
        str | None,
        typer.Option("--reference", help=_REFERENCE_HELP),
    ] = None,
    sample_id: Annotated[
        str | None,
        typer.Option("--sample-id", help="Short identifier (autodetected from raw/ otherwise)."),
    ] = None,
    raw_root: Annotated[
        Path,
        typer.Option("--raw-root", help="Raw root for --vcf autodetect."),
    ] = Path("/mnt/genomeclaw/raw"),
    reference_root: Annotated[
        Path,
        typer.Option("--reference-root", help="Reference root for --reference autodetect."),
    ] = Path("/mnt/genomeclaw/reference"),
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root."),
    ] = Path("/mnt/genomeclaw/derived"),
    bam: Annotated[
        Path | None,
        typer.Option("--bam", help="Optional source BAM/CRAM for mosdepth coverage."),
    ] = None,
    bed: Annotated[
        Path | None,
        typer.Option("--bed", help="Gene-list BED (required when --bam given)."),
    ] = None,
    reference_fasta: Annotated[
        Path | None,
        typer.Option("--reference-fasta", help="Bgzipped reference fasta."),
    ] = None,
    clinvar_release: Annotated[
        str | None,
        typer.Option("--clinvar-release", help="ClinVar release tag."),
    ] = None,
) -> None:
    """Chain ingest → normalize → annotate → materialize in one invocation."""
    ctx: AppContext = typer_ctx.obj
    resolved_sample_id, vcf_path, reference_dir = resolve_ingest_inputs(
        vcf=vcf,
        reference=reference,
        sample_id=sample_id,
        raw_root=raw_root,
        reference_root=reference_root,
    )
    callback = _build_callback(ctx, command="pipeline.run")
    pipeline_start = time.monotonic()

    try:
        run_dir_path = ingest_impl(
            vcf=vcf_path,
            reference_dir=reference_dir,
            derived_root=derived_root,
            sample_id=resolved_sample_id,
            bam=bam,
            bed=bed,
            reference_fasta=reference_fasta,
            progress_callback=callback,
        )
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="ingest", error_type="precondition_error", message=str(exc)
        )
        raise PreconditionError(f"ingest failed: {exc}") from exc
    except (AmbiguousReferenceBuild, ValueError) as exc:
        _emit_phase_failed(callback, phase="ingest", error_type="usage_error", message=str(exc))
        raise UsageError(f"ingest failed: {exc}") from exc

    try:
        normalize_impl(
            run_dir=run_dir_path,
            reference_fasta=reference_fasta,
            progress_callback=callback,
        )
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="normalize", error_type="runtime_error", message=str(exc)
        )
        raise RuntimeFailure(f"normalize failed: {exc}") from exc

    try:
        annotate_impl(
            run_dir=run_dir_path,
            reference_dir=reference_root,
            clinvar_release=clinvar_release,
            progress_callback=callback,
        )
    except FileNotFoundError as exc:
        _emit_phase_failed(callback, phase="annotate", error_type="runtime_error", message=str(exc))
        raise RuntimeFailure(f"annotate failed: {exc}") from exc

    try:
        materialize_impl(run_dir=run_dir_path, progress_callback=callback)
    except FileNotFoundError as exc:
        _emit_phase_failed(
            callback, phase="materialize", error_type="runtime_error", message=str(exc)
        )
        raise RuntimeFailure(f"materialize failed: {exc}") from exc

    if callback is not None:
        callback(
            PipelineComplete(
                run_dir=str(run_dir_path),
                duration_sec=time.monotonic() - pipeline_start,
            )
        )

    if not ctx.is_json:
        _emit_run_dir(ctx, command="pipeline.run", run_dir=run_dir_path)


__all__ = ["AUTODETECT_SENTINEL", "app"]

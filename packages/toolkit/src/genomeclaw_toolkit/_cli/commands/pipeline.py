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

import contextlib
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
    make_pipeline_progress,
    make_pipeline_rich_renderer,
)
from genomeclaw_toolkit.prep._events import PhaseFailed, PipelineComplete
from genomeclaw_toolkit.prep._paths import as_sibling_mountable
from genomeclaw_toolkit.prep.annotate import annotate as annotate_impl
from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill
from genomeclaw_toolkit.prep.ingest import ingest as ingest_impl
from genomeclaw_toolkit.prep.materialize import materialize as materialize_impl
from genomeclaw_toolkit.prep.normalize import normalize as normalize_impl
from genomeclaw_toolkit.prep.pgs import (
    PgsReferenceMissingError,
    PgsRow,
)
from genomeclaw_toolkit.prep.pgs import (
    compute_pgs as compute_pgs_impl,
)
from genomeclaw_toolkit.prep.reference_build import AmbiguousReferenceBuild
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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


@contextlib.contextmanager
def _build_callback(
    ctx: AppContext, *, command: str
) -> Iterator[Callable[[_ProgressEvent], None] | None]:
    """Pick the right ``progress_callback`` for this output mode.

    Returned as a context manager so the rich-mode caller can wrap the
    orchestrator call in a ``with`` block — that's what keeps the
    :class:`rich.progress.Progress` Live region animating while the
    orchestrator runs (spinner + elapsed counter). Without the context
    manager wrapping, the Live thread never starts and the user sees a
    bare ``▶ ingest`` Panel with no movement.

    In JSON mode the context manager is a no-op (no Live to manage)
    but writes the first-line envelope to stdout on entry.

    Yields:
        A callback consumer, or ``None`` when the command is fully
        quiet (``--quiet`` + rich mode → suppress progress output).
    """
    if ctx.is_json:
        _begin_ndjson_stream(command=command)
        yield make_pipeline_ndjson_emitter(sys.stdout)
        return
    if ctx.is_quiet:
        yield None
        return
    progress = make_pipeline_progress()
    with progress:
        yield make_pipeline_rich_renderer(progress)


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
    with _build_callback(ctx, command="pipeline.ingest") as callback:
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
    with _build_callback(ctx, command="pipeline.normalize") as callback:
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
    with _build_callback(ctx, command="pipeline.annotate") as callback:
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
    reference_dir: Annotated[
        Path,
        typer.Option(
            "--reference-dir",
            help=(
                "Reference root. When a gnomAD constraint TSV is staged under "
                "<reference-dir>/gnomad-constraint/<release>/, materialize joins it "
                "to populate gene_loeuf on the variants table; otherwise gene_loeuf "
                "stays NULL."
            ),
        ),
    ] = Path("/mnt/genomeclaw/reference"),
    gnomad_constraint_release: Annotated[
        str | None,
        typer.Option(
            "--gnomad-constraint-release",
            help=(
                "gnomAD constraint release tag (default: newest under "
                "<reference-dir>/gnomad-constraint/)."
            ),
        ),
    ] = None,
) -> None:
    """Rewrite the variants table from ``normalized.vcf.gz``."""
    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)
    with _build_callback(ctx, command="pipeline.materialize") as callback:
        try:
            out = materialize_impl(
                run_dir=resolved_dir,
                reference_dir=reference_dir,
                gnomad_constraint_release=gnomad_constraint_release,
                progress_callback=callback,
            )
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
    gnomad_constraint_release: Annotated[
        str | None,
        typer.Option(
            "--gnomad-constraint-release",
            help=(
                "gnomAD constraint release tag for the materialize-time gene_loeuf "
                "join (default: newest under <reference-root>/gnomad-constraint/)."
            ),
        ),
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
    pipeline_start = time.monotonic()

    with _build_callback(ctx, command="pipeline.run") as callback:
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
            _emit_phase_failed(
                callback, phase="annotate", error_type="runtime_error", message=str(exc)
            )
            raise RuntimeFailure(f"annotate failed: {exc}") from exc

        try:
            materialize_impl(
                run_dir=run_dir_path,
                reference_dir=reference_root,
                gnomad_constraint_release=gnomad_constraint_release,
                progress_callback=callback,
            )
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


# ---------------------------------------------------------------------------
# Phase 6 Slice E v2 — pgs-compute subcommand (manual invocation path).
#
# The agent-driven path (E.3 async orchestrator) calls `compute_pgs` directly
# via the host service's `POST /v1/pgs/compute`. This CLI subcommand wraps
# the same function for users who want to trigger a compute outside the
# agent path — useful for the project owner's real-data smoke + for seeding
# `pgs_scores` rows before E.3 lands.
#
# On a successful compute, the subcommand also INSERTs a matching
# `clinical-non-actionable` finding row into `findings` so the agent's
# `genomeclaw_findings` filter surfaces the new PRS without a second
# materialize step.
# ---------------------------------------------------------------------------


class _PgsComputePayload(BaseModel):
    """`--json` payload for `pipeline pgs-compute` per INV-C002."""

    model_config = ConfigDict(extra="forbid")

    run_dir: str
    pgs_id: str
    trait_label: str
    percentile_in_user_ancestry: float | None
    raw_score: float | None
    calibration_warning: str | None


def _stamp_pgs_row(
    run_dir: Path,
    row: PgsRow,
    *,
    vcf: Path,
    min_overlap_used: float | None = None,
    keep_ambiguous_used: bool | None = None,
) -> None:
    """INSERT the `PgsRow` into `pgs_scores` with INV-R001 provenance + matching finding row.

    Provenance: `source_path` is the VCF; `source_sha256` is unset for the
    manual CLI path (the wrapper doesn't re-hash the VCF — for the real-data
    smoke, the ingest's manifest carries the canonical hash). `tool` is
    "pgsc_calc"; `tool_version` is "agent-driven" (the precise pgsc_calc
    version is captured in the work-dir manifest by Nextflow itself; for
    INV-R001 the canonical record is the run's manifest.json).

    ``min_overlap_used`` + ``keep_ambiguous_used`` are persisted into
    ``params_json`` so a future debugger / report reader can tell, from the
    stored row alone, what threshold pgsc_calc was invoked against. Both
    are optional for backwards compat with prior callers; the CLI's
    ``pipeline_pgs_compute`` resolves them once via
    :func:`genomeclaw_toolkit.prep.pgs._resolve_min_overlap` and threads
    the value through.
    """
    import json as _json
    from datetime import UTC, datetime
    from uuid import uuid4

    import duckdb

    from genomeclaw_toolkit.prep.store import create_store

    store_path = run_dir / "variants.duckdb"
    # Bootstrap an empty store if one doesn't exist yet — lets `prs-compute`
    # land its row in a fresh smoke dir without a preceding `host setup`/init
    # step. Existing stores are left untouched (create_store raises on existing
    # path; we catch that to keep this idempotent).
    if not store_path.exists():
        create_store(store_path)
    now = datetime.now(tz=UTC)
    params_dict: dict[str, object] = {"pgs_id": row.pgs_id, "vcf": str(vcf)}
    if min_overlap_used is not None:
        params_dict["min_overlap_used"] = min_overlap_used
    if keep_ambiguous_used is not None:
        params_dict["keep_ambiguous_used"] = keep_ambiguous_used
    params = _json.dumps(params_dict)

    conn = duckdb.connect(str(store_path))
    try:
        conn.execute(
            """
            INSERT INTO pgs_scores (
                pgs_id, trait_label, percentile_in_user_ancestry, raw_score,
                study_population, calibration_warning,
                agent_choice_rationale, requested_for_question,
                calibration_status, decline_reason, superseded_by,
                source_path, source_sha256, tool, tool_version,
                params_json, schema_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                      ?, '', 'pgsc_calc', 'agent-driven',
                      ?, ?, ?)
            """,
            [
                row.pgs_id,
                row.trait_label,
                row.percentile_in_user_ancestry,
                row.raw_score,
                row.study_population,
                row.calibration_warning,
                row.agent_choice_rationale,
                row.requested_for_question,
                row.calibration_status,
                row.decline_reason,
                str(vcf),
                params,
                SCHEMA_VERSION,
                now,
            ],
        )
        # Matching clinical-non-actionable finding row per Q8 v1.6 + INV-E001.
        finding_id = f"fnd-pgs-{row.pgs_id}-{uuid4().hex[:8]}"
        summary = (
            f"{row.trait_label}: {row.percentile_in_user_ancestry}th percentile "
            "in your ancestry-matched reference population "
            "(PRS — population-level estimate, not a pathogenic variant call)."
            if row.percentile_in_user_ancestry is not None
            else f"{row.trait_label}: PRS percentile unavailable; see calibration_warning."
        )
        conn.execute(
            """
            INSERT INTO findings (
                id, category, title, summary,
                evidence_ref, evidence_quality,
                gene_symbols, drugs, clinical_escalation,
                source_path, source_sha256, tool, tool_version,
                params_json, schema_version, created_at
            ) VALUES (?, 'clinical-non-actionable', ?, ?, ?, 'moderate',
                      [], NULL, NULL,
                      ?, '', 'pgsc_calc', 'agent-driven',
                      ?, ?, ?)
            """,
            [
                finding_id,
                f"{row.trait_label} — PRS",
                summary,
                f"pgs_catalog:{row.pgs_id}",
                str(vcf),
                params,
                SCHEMA_VERSION,
                now,
            ],
        )
    finally:
        conn.close()


@app.command("pgs-compute")
def pipeline_pgs_compute(
    typer_ctx: typer.Context,
    pgs_id: Annotated[
        str,
        typer.Option(
            "--pgs",
            help="PGS Catalog ID to compute (e.g. PGS000018).",
        ),
    ],
    vcf: Annotated[
        Path,
        typer.Option(
            "--vcf",
            help="Source VCF (read-only). pgsc_calc reads it host-side; "
            "no genomic data crosses any network boundary.",
        ),
    ],
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root. Must contain ancestry/{1000g,hgdp}/ for "
            "continuous-ancestry calibration; install with "
            "`genomeclaw refs fetch --source pgs_catalog_ancestry`.",
        ),
    ],
    rationale: Annotated[
        str,
        typer.Option(
            "--rationale",
            help="Agent's reasoning for picking this PGS (alternatives considered + "
            "why this one). Persisted to the pgs_scores row per INV-A003. "
            "Required >= 50 chars.",
        ),
    ],
    question: Annotated[
        str,
        typer.Option(
            "--question",
            help="Verbatim user question that triggered the compute. "
            "Persisted to the pgs_scores row per INV-A003.",
        ),
    ],
    work_dir: Annotated[
        Path,
        typer.Option(
            "--work-dir",
            help="Nextflow work directory for heavy intermediates.",
        ),
    ],
    trait_label: Annotated[
        str | None,
        typer.Option(
            "--trait-label",
            help="Human-readable trait label (e.g. 'coronary artery disease'). "
            "Defaults to `PGS Catalog <id>`.",
        ),
    ] = None,
    run_dir: Annotated[
        str | None,
        typer.Option("--run-dir", help="Derived run dir (or CURRENT autodetect)."),
    ] = None,
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root for CURRENT autodetect."),
    ] = Path("/mnt/genomeclaw/derived"),
) -> None:
    """Compute a PRS for one PGS Catalog ID; write a `pgs_scores` + matching `findings` row.

    Manual-invocation path for the agent-driven PRS architecture (Q8 v1.6).
    The agent's async path (E.3 orchestrator) calls `compute_pgs` via the
    host service's `POST /v1/pgs/compute`; this CLI subcommand wraps the
    same function for users who want to trigger a compute outside the
    agent path. Always populate `--rationale` carefully — it persists as
    a column on the result row + is the user's audit surface per INV-A003.
    """
    if len(rationale) < 50:
        raise UsageError(
            f"--rationale must be >= 50 chars (per INV-A003); got {len(rationale)}. "
            "Include the alternative PGS scorefiles you considered + why this one."
        )

    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)

    # INV-D006: validate every path that may flow into a DooD sibling at
    # the orchestrator boundary BEFORE the wrapper subprocess fires.
    # Typer parses CLI args as plain ``Path``; `as_sibling_mountable(p)`
    # promotes them to ``SiblingMountablePath`` (the validated subtype
    # the wrapper annotates), raising ``DooDPathError`` on container-
    # local paths (`/tmp/genomeclaw-scratch/...`) instead of letting a
    # non-host-visible path reach pgsc_calc.
    vcf_smp = as_sibling_mountable(vcf)
    reference_root_smp = as_sibling_mountable(reference_root)
    work_dir_smp = as_sibling_mountable(work_dir)

    # Resolve the input-class-appropriate --min_overlap once at the top so
    # the value threaded into pgsc_calc (via compute_pgs_impl →
    # _build_pgsc_calc_argv → _resolve_min_overlap) matches the value
    # persisted to pgs_scores.params_json (INV-R001 rebuildability).
    # `keep_ambiguous_used` is False — load-bearing per the research
    # findings doc; flipping it to True would recover ~15% match rate at
    # the cost of systematic strand-error on ~half of recovered weights.
    from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

    min_overlap_used = _resolve_min_overlap()
    keep_ambiguous_used = False

    try:
        row = compute_pgs_impl(
            vcf=vcf_smp,
            pgs_id=pgs_id,
            reference_root=reference_root_smp,
            work_dir=work_dir_smp,
            agent_choice_rationale=rationale,
            requested_for_question=question,
            trait_label=trait_label,
        )
    except PgsReferenceMissingError as exc:
        raise PreconditionError(str(exc)) from exc

    _stamp_pgs_row(
        resolved_dir,
        row,
        vcf=vcf,
        min_overlap_used=min_overlap_used,
        keep_ambiguous_used=keep_ambiguous_used,
    )

    payload = _PgsComputePayload(
        run_dir=str(resolved_dir),
        pgs_id=row.pgs_id,
        trait_label=row.trait_label,
        percentile_in_user_ancestry=row.percentile_in_user_ancestry,
        raw_score=row.raw_score,
        calibration_warning=row.calibration_warning,
    )
    emit(
        ctx=ctx,
        command="pipeline.pgs-compute",
        payload=payload,
        rich_renderer=lambda p: get_console().print(
            f"computed {p.pgs_id} ({p.trait_label}): {p.percentile_in_user_ancestry}th percentile"
        ),
    )


# ---------------------------------------------------------------------------
# Phase 1b — `prs-prepare-coverage` subcommand
# ---------------------------------------------------------------------------
#
# Builds (or returns cached) the Tier 1 PCA-eligible force-genotyped VCF for
# one sample, using the streaming `bcftools mpileup → call → norm` pipe
# documented in :mod:`genomeclaw_toolkit.prep.coverage_fill`. The agent's
# Phase 2 `prs-compute` orchestrator calls this transitively on cache miss;
# this CLI surface is also the manual-invocation path for users who want to
# warm the cache outside the agent path (or to seed a re-aligned CRAM's
# fresh tier1 before any PRS question lands).
# ---------------------------------------------------------------------------


class _PrsPrepareCoveragePayload(BaseModel):
    """`--json` payload for `pipeline prs-prepare-coverage` per INV-C002."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    panel_version: str
    tier1_vcf: str
    tier1_qc_json: str
    cache_status: str  # "built" | "hit"


@app.command("prs-prepare-coverage")
def pipeline_prs_prepare_coverage(
    typer_ctx: typer.Context,
    sample_id: Annotated[
        str,
        typer.Option(
            "--sample",
            help="Sample identifier; used as the per-sample cache key + the "
            "directory name under derived/prs_coverage/.",
        ),
    ],
    cram: Annotated[
        Path,
        typer.Option(
            "--cram",
            help="User CRAM (read-only). Must have a sibling `.crai` index; "
            "the bcftools pipe seeks via the index to each target site.",
        ),
    ],
    sites: Annotated[
        Path,
        typer.Option(
            "--sites",
            help="PCA-eligible sites TSV (chrom, pos). Produced by "
            "`refs materialize --target prs_pca_sites`; consumed by "
            "`bcftools mpileup --regions-file`.",
        ),
    ],
    alleles: Annotated[
        Path,
        typer.Option(
            "--alleles",
            help="PCA-eligible alleles TSV (chrom, pos, ref,alt). "
            "Consumed by `bcftools call --constrain alleles --targets-file`.",
        ),
    ],
    fasta: Annotated[
        Path,
        typer.Option(
            "--fasta",
            help="GRCh38 reference FASTA (bgzipped, with .fai + .gzi sidecars). "
            "Used by `bcftools mpileup --fasta-ref` to decode CRAM.",
        ),
    ],
    panel_version: Annotated[
        str,
        typer.Option(
            "--panel-version",
            help="HGDP+1kGP panel release tag (matches the directory name "
            "under reference/pgs_catalog_ancestry/). Becomes part of the "
            "cache key so a panel re-release re-builds cleanly.",
        ),
    ],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            help="Derived root. The Tier 1 cache lands at "
            "`<root>/prs_coverage/<sample>/<panel>/tier1.{vcf.gz,qc.json}`.",
        ),
    ] = Path("/mnt/genomeclaw/derived"),
) -> None:
    """Build (or return cached) the Tier 1 PCA-eligible force-genotyped VCF for one sample.

    Streams the user CRAM through `bcftools mpileup → call --constrain alleles
    → norm`, emitting one record per PCA-eligible HGDP+1kGP site. The output
    lands under `derived/prs_coverage/<sample>/<panel>/tier1.vcf.gz` with a
    sidecar `tier1.qc.json` recording the source CRAM SHA256, panel version,
    bcftools version, GT distribution, mean DP, and per-chrom record counts
    (INV-R001).

    Re-invocations against the same (sample, panel_version, CRAM SHA256)
    hit cache: zero subprocess calls, fast return.
    """
    from genomeclaw_toolkit.prep.coverage_fill import (
        MissingCramIndexError,
        MissingPanelError,
        _tier1_cache_path,
        prepare_coverage_tier1,
    )

    ctx: AppContext = typer_ctx.obj

    cache_vcf = _tier1_cache_path(
        derived_root=output_root, sample_id=sample_id, panel_version=panel_version
    )
    was_cached = cache_vcf.exists() and (cache_vcf.parent / "tier1.qc.json").exists()

    try:
        prepare_coverage_tier1(
            sample_id=sample_id,
            cram_path=cram,
            sites_tsv=sites,
            alleles_tsv=alleles,
            fasta=fasta,
            panel_version=panel_version,
            output_root=output_root,
        )
    except (MissingCramIndexError, MissingPanelError) as exc:
        raise PreconditionError(str(exc)) from exc

    cache_qc = cache_vcf.parent / "tier1.qc.json"
    # If the cache was warm AND we didn't write anything new, the second
    # mtime check confirms "hit"; otherwise we built fresh.
    cache_status = "hit" if was_cached else "built"

    payload = _PrsPrepareCoveragePayload(
        sample_id=sample_id,
        panel_version=panel_version,
        tier1_vcf=str(cache_vcf),
        tier1_qc_json=str(cache_qc),
        cache_status=cache_status,
    )
    emit(
        ctx=ctx,
        command="pipeline.prs-prepare-coverage",
        payload=payload,
        rich_renderer=lambda p: get_console().print(
            f"{p.cache_status} tier1 cache: {p.tier1_vcf}"
        ),
    )


# ---------------------------------------------------------------------------
# Phase 4c — `prs-compute` end-to-end orchestrator subcommand
# ---------------------------------------------------------------------------
#
# Single CLI entry point for the agent's compute path: chains Tier 1 + Tier 2
# + merge + pgsc_calc into one call. Cache-aware — warm Tier 1/Tier 2 caches
# skip the bcftools work entirely, so subsequent agent questions against the
# same PGS run only pgsc_calc (~10-15 min) instead of the full ~50-60 min
# Tier 1 build.
# ---------------------------------------------------------------------------


class _PrsComputeDeclineBlock(BaseModel):
    """Decline-payload nested block (INV-C001 v1.7 + INV-A003).

    Populated only when the orchestrator's calibration step raised
    :class:`PRSDeclineError`; ``None`` on the clean/warning path.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str  # snake_case ``DeclineReason.value``
    two_named_reasons: tuple[str, str]


class _PrsComputePayload(BaseModel):
    """`--json` payload for `pipeline prs-compute` per INV-C002.

    Phase 3b3b2: extended with ``calibration_status`` + ``decline``. The
    decline block is populated on the ``calibration_status="decline"``
    branch; the clean/warning branches leave ``decline=None`` and
    surface the score normally.
    """

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    pgs_id: str
    trait_label: str
    percentile_in_user_ancestry: float | None
    raw_score: float | None
    calibration_warning: str | None
    calibration_status: str | None = None
    decline: _PrsComputeDeclineBlock | None = None


@app.command("prs-compute")
def pipeline_prs_compute(
    typer_ctx: typer.Context,
    sample_id: Annotated[
        str,
        typer.Option(
            "--sample",
            help="Sample identifier; used as the Tier 1 + Tier 2 cache key.",
        ),
    ],
    cram: Annotated[
        Path,
        typer.Option(
            "--cram",
            help="User CRAM (read-only). Must have a sibling .crai index.",
        ),
    ],
    sites: Annotated[
        Path,
        typer.Option(
            "--sites",
            help="PCA-eligible sites TSV (chrom, pos) from "
            "`refs materialize --target prs_pca_sites`.",
        ),
    ],
    alleles: Annotated[
        Path,
        typer.Option(
            "--alleles",
            help="PCA-eligible alleles TSV (chrom, pos, ref,alt).",
        ),
    ],
    scorefile: Annotated[
        Path,
        typer.Option(
            "--scorefile",
            help="PGS Catalog hmPOS_GRCh38 scoring file (gzipped). "
            "The wrapper extracts the PGS ID + per-row sites from this; "
            "the SHA256 keys the Tier 2 cache.",
        ),
    ],
    fasta: Annotated[
        Path,
        typer.Option(
            "--fasta",
            help="GRCh38 reference FASTA (bgzipped, with .fai + .gzi sidecars).",
        ),
    ],
    panel_version: Annotated[
        str,
        typer.Option(
            "--panel-version",
            help="HGDP+1kGP panel release tag (e.g. `v1`).",
        ),
    ],
    reference_root: Annotated[
        Path,
        typer.Option(
            "--reference-root",
            help="Reference root containing pgs_catalog_ancestry/<panel>/ — "
            "consumed by pgsc_calc --run_ancestry.",
        ),
    ],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            help="Derived root for Tier 1 + Tier 2 caches.",
        ),
    ],
    work_dir: Annotated[
        Path,
        typer.Option(
            "--work-dir",
            help="Nextflow work directory for pgsc_calc heavy intermediates.",
        ),
    ],
    rationale: Annotated[
        str,
        typer.Option(
            "--rationale",
            help="Agent's reasoning for picking this PGS (alternatives + why). "
            "Persisted to the result row per INV-A003. Required >= 50 chars.",
        ),
    ],
    question: Annotated[
        str,
        typer.Option(
            "--question",
            help="Verbatim user question that triggered the compute (INV-A003).",
        ),
    ],
    trait_label: Annotated[
        str | None,
        typer.Option(
            "--trait-label",
            help="Optional human-readable trait label. Defaults to "
            "`PGS Catalog <id>`.",
        ),
    ] = None,
    run_dir: Annotated[
        Path | None,
        typer.Option(
            "--run-dir",
            help="Derived run dir containing variants.duckdb. When supplied, "
            "the computed PgsRow lands as a `pgs_scores` row + matching "
            "`findings` row (AC4 + AC5 of prs-bootstrap-meta). Omit for "
            "envelope-only mode.",
        ),
    ] = None,
) -> None:
    """End-to-end PRS compute: Tier 1 + Tier 2 + merge + pgsc_calc.

    Single entry point for the agent's compute path. Warm caches turn this
    into a ~10-15 min pgsc_calc-only run; cold caches add the per-sample
    Tier 1 (~50-60 min on 2-CPU Colima) and the per-PGS Tier 2 (~5-10 min
    for a typical scoring file).

    When ``--run-dir`` is supplied, the computed :class:`PgsRow` is INSERTed
    into ``<run-dir>/variants.duckdb`` as a ``pgs_scores`` row + matching
    ``findings`` row, carrying the INV-A003 rationale/question + INV-R001
    provenance. Without ``--run-dir``, the CLI emits the envelope only.
    """
    if len(rationale) < 50:
        raise UsageError(
            f"--rationale must be >= 50 chars (per INV-A003); got {len(rationale)}. "
            "Include the alternative PGS scorefiles you considered + why this one."
        )

    ctx: AppContext = typer_ctx.obj

    # INV-D006: validate sibling-mountable paths at the CLI boundary
    # before any DooD-spawning wrapper runs. Mirrors `pipeline_pgs_compute`.
    reference_root_smp = as_sibling_mountable(reference_root)
    work_dir_smp = as_sibling_mountable(work_dir)

    from genomeclaw_toolkit.prep._pgs_qc import PRSDeclineError
    from genomeclaw_toolkit.prep.coverage_fill import _extract_pgs_id_from_scorefile

    try:
        row = compute_prs_with_coverage_fill(
            sample_id=sample_id,
            cram_path=cram,
            sites_tsv=sites,
            alleles_tsv=alleles,
            scorefile_path=scorefile,
            fasta=fasta,
            panel_version=panel_version,
            reference_root=reference_root_smp,
            output_root=output_root,
            work_dir=work_dir_smp,
            agent_choice_rationale=rationale,
            requested_for_question=question,
            trait_label=trait_label,
        )
    except PgsReferenceMissingError as exc:
        raise PreconditionError(str(exc)) from exc
    except PRSDeclineError as exc:
        # INV-C001 v1.7: decline is a legitimate outcome, not a failure.
        # Emit a typed decline payload + exit 0 so the agent layer can
        # render the two-named-reasons explanation to the user.
        pgs_id_resolved = _extract_pgs_id_from_scorefile(scorefile)
        decline_payload = _PrsComputePayload(
            sample_id=sample_id,
            pgs_id=pgs_id_resolved,
            trait_label=trait_label or f"PGS Catalog {pgs_id_resolved}",
            percentile_in_user_ancestry=None,
            raw_score=None,
            calibration_warning=None,
            calibration_status="decline",
            decline=_PrsComputeDeclineBlock(
                reason=exc.reason.value,
                two_named_reasons=exc.two_named_reasons,
            ),
        )
        emit(
            ctx=ctx,
            command="pipeline.prs-compute",
            payload=decline_payload,
            rich_renderer=lambda p: get_console().print(
                f"declined {p.pgs_id} ({p.decline.reason}): "
                f"{p.decline.two_named_reasons[0]}"
                if p.decline is not None
                else f"declined {p.pgs_id}"
            ),
        )
        return

    if run_dir is not None:
        # AC4 + AC5 — persist the computed row + matching finding row into the
        # run's variants.duckdb. Min-overlap + keep-ambiguous flow into
        # params_json via _stamp_pgs_row so the stored row records the
        # threshold pgsc_calc was actually invoked against. Smoke v23
        # (2026-05-22) exposed that prs-compute was envelope-only; this
        # branch closes that gap.
        from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

        min_overlap_used = _resolve_min_overlap()
        keep_ambiguous_used = False
        _stamp_pgs_row(
            run_dir,
            row,
            vcf=cram,
            min_overlap_used=min_overlap_used,
            keep_ambiguous_used=keep_ambiguous_used,
        )

    payload = _PrsComputePayload(
        sample_id=sample_id,
        pgs_id=row.pgs_id,
        trait_label=row.trait_label,
        percentile_in_user_ancestry=row.percentile_in_user_ancestry,
        raw_score=row.raw_score,
        calibration_warning=row.calibration_warning,
        calibration_status=row.calibration_status,
    )
    emit(
        ctx=ctx,
        command="pipeline.prs-compute",
        payload=payload,
        rich_renderer=lambda p: get_console().print(
            f"computed {p.pgs_id}: {p.percentile_in_user_ancestry}th percentile"
        ),
    )


# ---------------------------------------------------------------------------
# Phase 6 Slice D' — `pharmcat` subcommand (PharmCAT PGx pipeline)
# ---------------------------------------------------------------------------


class _PharmcatPayload(BaseModel):
    """`--json` payload for `pipeline pharmcat` per INV-C002."""

    model_config = ConfigDict(extra="forbid")
    run_dir: str
    findings_inserted: int


def _stamp_pharmcat_findings(
    run_dir: Path,
    findings: list,
    *,
    vcf: Path,
    cyp2d6_diplotype_json: Path | None,
) -> int:
    """INSERT one `findings` row per `PharmCATFinding` with INV-R001 provenance.

    Each row: category='clinical-actionable' (per INV-C001 v1.5),
    clinical_escalation='confirm_with_provider', evidence_ref='pharmgkb:<id>',
    gene_symbols=[gene], drugs=[drugs from the recommendation],
    tool='pharmcat', tool_version per `_versions.PGX_RUNTIME_VERSIONS["pharmcat"]`.

    The VCF's SHA256 is computed once and stamped onto every finding row;
    avoids the pgs-compute pattern of empty-string-defer-to-manifest since
    PharmCAT's input contract is the VCF itself (the manifest may not
    exist for ad-hoc invocations).

    Returns the count inserted.
    """
    import hashlib
    import json as _json
    from datetime import UTC, datetime
    from uuid import uuid4

    import duckdb

    from genomeclaw_toolkit.prep._versions import PGX_RUNTIME_VERSIONS
    from genomeclaw_toolkit.prep.store import create_store

    store_path = run_dir / "variants.duckdb"
    if not store_path.exists():
        create_store(store_path)
    now = datetime.now(tz=UTC)
    params = _json.dumps(
        {
            "vcf": str(vcf),
            "cyp2d6_diplotype_json": (
                str(cyp2d6_diplotype_json) if cyp2d6_diplotype_json is not None else None
            ),
        },
        sort_keys=True,
    )

    # Compute the VCF SHA256 once and stamp it onto every finding row.
    digest = hashlib.sha256()
    with vcf.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    vcf_sha256 = digest.hexdigest()

    inserted = 0
    conn = duckdb.connect(str(store_path))
    try:
        for f in findings:
            finding_id = f"fnd-pharmcat-{f.gene}-{uuid4().hex[:8]}"
            drugs_label = ", ".join(f.drugs) if f.drugs else "—"
            title = f"{f.gene} {f.diplotype} — {f.phenotype} (re {drugs_label})"
            conn.execute(
                """
                INSERT INTO findings (
                    id, category, title, summary,
                    evidence_ref, evidence_quality,
                    gene_symbols, drugs, clinical_escalation,
                    source_path, source_sha256, tool, tool_version,
                    params_json, schema_version, created_at
                ) VALUES (?, 'clinical-actionable', ?, ?, ?, 'high',
                          ?, ?, 'confirm_with_provider',
                          ?, ?, 'pharmcat', ?,
                          ?, ?, ?)
                """,
                [
                    finding_id,
                    title,
                    f.recommendation_summary,
                    f"pharmgkb:{f.pharmgkb_id}",
                    [f.gene],
                    list(f.drugs) if f.drugs else None,
                    str(vcf),
                    vcf_sha256,
                    PGX_RUNTIME_VERSIONS["pharmcat"],
                    params,
                    SCHEMA_VERSION,
                    now,
                ],
            )
            inserted += 1
    finally:
        conn.close()
    return inserted


@app.command("pharmcat")
def pipeline_pharmcat(
    typer_ctx: typer.Context,
    vcf: Annotated[
        Path,
        typer.Option(
            "--vcf",
            help="Source VCF (read-only). PharmCAT's preprocessor opens it "
            "host-side; no genomic data crosses any network boundary (INV-D001).",
        ),
    ],
    cyp2d6_diplotype_json: Annotated[
        Path | None,
        typer.Option(
            "--cyp2d6-diplotype-json",
            help="Path to Slice D's `cyp2d6_diplotype.json` envelope. Converted "
            "into PharmCAT's outside-call TSV format for the CYP2D6 row.",
        ),
    ] = None,
    reference_fasta: Annotated[
        Path | None,
        typer.Option(
            "--reference-fasta",
            help="GRCh38 reference fasta. Essentially required: without it, "
            "PharmCAT's preprocessor tries to download a copy from Zenodo into "
            "the read-only image install dir + fails. Threaded via -refFna.",
        ),
    ] = None,
    run_dir: Annotated[
        str | None,
        typer.Option("--run-dir", help="Derived run dir (or CURRENT autodetect)."),
    ] = None,
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root for CURRENT autodetect."),
    ] = Path("/mnt/genomeclaw/derived"),
) -> None:
    """Run PharmCAT against `vcf`; INSERT a `findings` row per recommendation.

    Wraps PharmGKB's PharmCAT v3 pipeline. Each emitted finding carries
    `evidence_ref=pharmgkb:<id>` (INV-E001), `category=clinical-actionable`
    + `clinical_escalation=confirm_with_provider` (INV-C001 v1.5), and the
    seven canonical INV-R001 provenance columns. The CYP2D6 outside-call
    from Slice D's `cyp2d6_diplotype.json` is threaded in via PharmCAT's
    `--outside-call-file` flag.
    """
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)

    findings = run_pharmcat(
        vcf=vcf,
        run_dir=resolved_dir,
        cyp2d6_diplotype_json=cyp2d6_diplotype_json,
        reference_fasta=reference_fasta,
    )
    inserted = _stamp_pharmcat_findings(
        resolved_dir,
        findings,
        vcf=vcf,
        cyp2d6_diplotype_json=cyp2d6_diplotype_json,
    )

    payload = _PharmcatPayload(
        run_dir=str(resolved_dir),
        findings_inserted=inserted,
    )
    emit(
        ctx=ctx,
        command="pipeline.pharmcat",
        payload=payload,
        rich_renderer=lambda p: get_console().print(
            f"PharmCAT: inserted {p.findings_inserted} PGx finding(s) for {p.run_dir}",
            markup=False,
        ),
    )


# ---------------------------------------------------------------------------
# Phase 6 Slice D — `cyp2d6-call` subcommand (Cyrius CYP2D6 star-allele caller)
# ---------------------------------------------------------------------------


class _Cyp2d6CallPayload(BaseModel):
    """`--json` payload for `pipeline cyp2d6-call` per INV-C002."""

    model_config = ConfigDict(extra="forbid")
    run_dir: str
    sample_id: str
    diplotype: str
    filter_status: str


@app.command("cyp2d6-call")
def pipeline_cyp2d6_call(
    typer_ctx: typer.Context,
    bam: Annotated[
        Path,
        typer.Option(
            "--bam",
            help="Source BAM/CRAM (read-only). Cyrius opens it host-side; "
            "no genomic data crosses any network boundary (INV-D001).",
        ),
    ],
    sample_id: Annotated[
        str,
        typer.Option(
            "--sample-id",
            help="Sample identifier Cyrius keys its output JSON sub-dict under. "
            "Typically the BAM header's SM-tag value.",
        ),
    ],
    run_dir: Annotated[
        str | None,
        typer.Option("--run-dir", help="Derived run dir (or CURRENT autodetect)."),
    ] = None,
    derived_root: Annotated[
        Path,
        typer.Option("--derived-root", help="Derived root for CURRENT autodetect."),
    ] = Path("/mnt/genomeclaw/derived"),
    genome_build: Annotated[
        str,
        typer.Option(
            "--genome-build",
            help="Reference build. GRCh38 only in v0.",
        ),
    ] = "GRCh38",
    threads: Annotated[
        int | None,
        typer.Option("--threads", help="Cyrius worker thread count (optional)."),
    ] = None,
    reference_fasta: Annotated[
        Path | None,
        typer.Option(
            "--reference-fasta",
            help="Reference fasta path. REQUIRED for CRAM input (pysam needs "
            "it to decompress CRAM blocks); optional for BAM.",
        ),
    ] = None,
) -> None:
    """Run Cyrius against `bam`; write `cyp2d6_diplotype.json` under the run dir.

    Wraps Illumina's Cyrius CYP2D6 star-allele caller. The resulting
    diplotype (e.g. `*1/*4`) feeds PharmCAT's outside-call interface for
    the `*1/*4`-class PGx finding the project owner's run depends on
    (per spec Q6 / AC11). The output envelope carries the seven
    canonical INV-R001 provenance columns inside its `provenance` block.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    ctx: AppContext = typer_ctx.obj
    resolved_dir = resolve_run_dir(run_dir=run_dir, derived_root=derived_root)

    # INV-D006 boundary check happens inside call_cyp2d6 via
    # as_sibling_mountable; the CLI layer just passes the Paths through.
    row = call_cyp2d6(
        bam=bam,
        genome_build=genome_build,
        run_dir=resolved_dir,
        sample_id=sample_id,
        threads=threads,
        reference_fasta=reference_fasta,
    )

    payload = _Cyp2d6CallPayload(
        run_dir=str(resolved_dir),
        sample_id=row.sample_id,
        diplotype=row.diplotype,
        filter_status=row.filter_status,
    )
    emit(
        ctx=ctx,
        command="pipeline.cyp2d6-call",
        payload=payload,
        rich_renderer=lambda p: get_console().print(
            f"CYP2D6 diplotype for {p.sample_id}: {p.diplotype} ({p.filter_status})",
            markup=False,
        ),
    )


__all__ = ["AUTODETECT_SENTINEL", "app"]

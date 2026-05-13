"""``genomeclaw pipeline annotate`` parent orchestrator (Phase 4C.3+).

Chains the sub-orchestrators that together produce the v0.2 annotated
VCF a Phase-4 ``materialize`` consumes:

1. ``annotate_vcfanno`` — tabix-indexed overlay sources (ClinVar +
   gnomAD-exomes + dbSNP) merged onto ``run_dir/normalized.vcf.gz`` via
   vcfanno. Writes ``run_dir/vcfanno.vcf.gz`` + ``.tbi`` and appends a
   ``vcfanno`` step to ``provenance.json``.
2. ``annotate_vep`` *(Phase 4D, currently a no-op)* — VEP +
   LOFTEE + AlphaMissense + SpliceAI cache-driven annotations. Will read
   ``run_dir/vcfanno.vcf.gz`` and write a VEP-annotated VCF that
   replaces ``annotated.vcf.gz``. Until 4D ships, the parent simply
   promotes ``vcfanno.vcf.gz`` → ``annotated.vcf.gz`` so the existing
   v0.2 ``materialize`` contract (read from ``annotated.vcf.gz``)
   continues to work.

The Phase-4A in-line ``bcftools annotate`` + ClinVar-only path is
**removed**; its behaviours (ClinVar release resolution, chr-prefix
alignment, source-immutability) are now in
``prep/annotate_vcfanno.py``.

`INV-D001`: source files (normalized.vcf.gz, overlay sources) are
read-only — both sub-orchestrators enforce this. `INV-R001`: every
sub-orchestrator records its own provenance step (``vcfanno`` from
4C.2; ``vep`` from 4D). The parent doesn't add a step of its own — it
is a coordinator, and the sub-step trail is the authoritative record.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart
from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit.prep._events import _ProgressEvent

log = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialise_for_json(value: object) -> object:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unserialisable: {value!r}")


def annotate(
    *,
    run_dir: Path,
    reference_dir: Path,
    clinvar_release: str | None = None,
    gnomad_exomes_release: str | None = None,
    dbsnp_release: str | None = None,
    started_at: datetime | None = None,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path:
    """Run the chained annotation pipeline against the run's normalized VCF.

    Args:
        run_dir: an existing ``derived/<run-id>/`` from a prior
            ``ingest`` + ``normalize``. Must contain ``normalized.vcf.gz``.
        reference_dir: the toolkit's reference root.
        clinvar_release / gnomad_exomes_release / dbsnp_release: optional
            release tags passed through to ``annotate_vcfanno``. When
            None, each sub-orchestrator picks the lex-largest release
            dir under its respective source root.
        started_at: optional fixed UTC timestamp threaded into
            ``annotate_vcfanno``'s provenance step.

    Returns:
        Path to the freshly-written ``run_dir/annotated.vcf.gz`` (a
        copy of ``run_dir/vcfanno.vcf.gz`` until 4D's VEP stage replaces
        it).
    """
    preflight.assert_raw_readonly()
    preflight.assert_reference_readonly()
    preflight.assert_derived_writable()
    preflight.assert_scratch_writable()

    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in run dir: {run_dir}")

    log.info("annotate (parent chain) starting: run_dir=%s", run_dir)

    phase_start_mono = time.monotonic()
    if progress_callback is not None:
        progress_callback(PhaseStart(phase="annotate"))

    # Sub-orchestrator 1: vcfanno overlays. Writes vcfanno.vcf.gz +
    # .tbi into run_dir; appends a ``vcfanno`` step to provenance.json.
    # The progress_callback flows through so annotate-vcfanno can emit
    # beat-by-beat PhaseMessage events ("staging clinvar", "[3/24] chr3
    # vcfanno running", …) — the parent's PhaseStart/PhaseComplete pair
    # frames the sub-orchestrator's per-step beats in the renderer.
    annotate_vcfanno(
        run_dir=run_dir,
        reference_dir=reference_dir,
        clinvar_release=clinvar_release,
        gnomad_exomes_release=gnomad_exomes_release,
        dbsnp_release=dbsnp_release,
        started_at=started_at,
        progress_callback=progress_callback,
    )

    # Sub-orchestrator 2: VEP (Phase 4D placeholder). When 4D ships,
    # ``annotate_vep`` reads vcfanno.vcf.gz, runs VEP + LOFTEE +
    # AlphaMissense + SpliceAI, and writes a VEP-annotated VCF to
    # ``run_dir/annotated.vcf.gz`` (replacing the copy this stub
    # produces). The vcfanno.vcf.gz intermediate stays on disk for
    # inspection / debugging.

    # 4C.3 stub: annotated.vcf.gz is a copy of vcfanno.vcf.gz so the
    # existing materialize contract (read from annotated.vcf.gz) keeps
    # working. Within-FS within ``derived/<run-id>/``; cheap.
    vcfanno_vcf = run_dir / "vcfanno.vcf.gz"
    vcfanno_tbi = run_dir / "vcfanno.vcf.gz.tbi"
    annotated_vcf = run_dir / "annotated.vcf.gz"
    annotated_tbi = run_dir / "annotated.vcf.gz.tbi"
    shutil.copyfile(vcfanno_vcf, annotated_vcf)
    shutil.copyfile(vcfanno_tbi, annotated_tbi)

    annotated_sha = _sha256_file(annotated_vcf)
    annotated_tbi_sha = _sha256_file(annotated_tbi)

    # Update manifest.outputs with the final annotated identity. The
    # provenance step trail's ``vcfanno`` step already records the
    # vcfanno output identity; the manifest's ``annotated_vcf`` field
    # is the materialize-facing entry point.
    manifest = json.loads(manifest_path.read_text())
    manifest["outputs"]["annotated_vcf"] = "annotated.vcf.gz"
    manifest["outputs"]["annotated_vcf_sha256"] = annotated_sha
    manifest["outputs"]["annotated_tbi_sha256"] = annotated_tbi_sha
    manifest_path.write_text(json.dumps(manifest, indent=2, default=_serialise_for_json) + "\n")

    log.info("annotate (parent chain) complete: out=%s", annotated_vcf)
    if progress_callback is not None:
        progress_callback(
            PhaseComplete(
                phase="annotate",
                duration_sec=time.monotonic() - phase_start_mono,
                run_dir=str(run_dir),
            )
        )
    return annotated_vcf


__all__ = ["annotate"]

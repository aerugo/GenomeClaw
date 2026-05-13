"""``genomeclaw pipeline normalize`` orchestration.

Operates on an existing ``derived/<run-id>/`` directory from a prior
``ingest``:

1. Reads ``manifest.json`` to find the source VCF + its sha256.
2. Runs ``bcftools norm -m-`` on the source → ``run_dir/normalized.vcf.gz``.
3. Indexes the normalized VCF (``.tbi``).
4. Updates ``manifest.json``: ``outputs.normalized_vcf`` +
   ``outputs.normalized_vcf_sha256`` + ``outputs.normalized_tbi_sha256``.
5. Appends a ``normalize`` step to ``provenance.json``.

The variants table is **not** updated by ``normalize`` — that's
``materialize``'s job. Splitting concerns this way means: (a) the
normalized VCF on disk is the canonical hand-off to downstream
annotators (Phase 4 VEP / bcftools annotate), independent of the DuckDB store,
and (b) the variants-table refresh is one focused step that can be
re-run alongside annotation updates without re-normalising.

`INV-D001`: source VCF read-only. `INV-R001`: provenance trail records
both the source-VCF identity and the normalized-VCF identity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._bcftools import bcftools_index_tbi, bcftools_version
from genomeclaw_toolkit.prep._bcftools_norm import bcftools_norm
from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart, emit_beat

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


def normalize(
    *,
    run_dir: Path,
    reference_fasta: Path | None = None,
    started_at: datetime | None = None,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path:
    """Run ``bcftools norm`` on the run's source VCF; write outputs into ``run_dir``.

    Args:
        run_dir: an existing ``derived/<run-id>/`` directory containing
            ``manifest.json`` from a prior ``ingest``.
        reference_fasta: optional reference; when given, enables
            left-alignment via ``bcftools norm -f <ref>``. Without it,
            the step performs multi-allelic splitting only (the most
            common Phase-3 case until Phase 4 fetches a reference fasta).
        started_at: optional fixed UTC timestamp; defaults to
            ``datetime.now(tz=UTC)``. Tests pass a fixed value to drive
            determinism.

    Returns:
        Path to the freshly-written ``run_dir/normalized.vcf.gz``.
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

    if started_at is None:
        started_at = datetime.now(tz=UTC)
    log.info("normalize starting: run_dir=%s", run_dir)

    phase_start_mono = time.monotonic()
    if progress_callback is not None:
        progress_callback(PhaseStart(phase="normalize"))

    manifest = json.loads(manifest_path.read_text())
    src_vcf = Path(manifest["input"]["vcf_path"])
    src_vcf_sha = manifest["input"]["vcf_sha256"]

    if not src_vcf.exists():
        raise FileNotFoundError(f"source vcf in manifest no longer exists: {src_vcf}")

    norm_vcf = run_dir / "normalized.vcf.gz"
    emit_beat(
        progress_callback,
        phase="normalize",
        message=(
            "running bcftools norm -m- "
            + ("(with reference fasta · left-align)" if reference_fasta else "(split multi-allelics)")
        ),
        logger=log,
    )
    bcftools_norm(
        input_vcf=src_vcf,
        output_vcf=norm_vcf,
        reference_fasta=reference_fasta,
    )
    emit_beat(progress_callback, phase="normalize", message="hashing normalized VCF", logger=log)
    norm_vcf_sha = _sha256_file(norm_vcf)

    emit_beat(progress_callback, phase="normalize", message="building tabix index", logger=log)
    norm_tbi = bcftools_index_tbi(vcf=norm_vcf, derived_dir=run_dir)
    norm_tbi_sha = _sha256_file(norm_tbi)

    completed_at = datetime.now(tz=UTC)

    # Append step to provenance.json.
    provenance_path = run_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    bcftools_info = bcftools_version()
    norm_params: dict[str, Any] = {"multiallelic_split": True}
    if reference_fasta is not None:
        norm_params["reference_fasta"] = str(reference_fasta)
        norm_params["left_align"] = True
    provenance["steps"].append(
        {
            "step": "normalize",
            "tool": "bcftools",
            "tool_version": bcftools_info.version,
            "started_at": started_at,
            "completed_at": completed_at,
            "inputs": [{"path": str(src_vcf), "sha256": src_vcf_sha}],
            "outputs": [
                {"path": "normalized.vcf.gz", "sha256": norm_vcf_sha},
                {"path": "normalized.vcf.gz.tbi", "sha256": norm_tbi_sha},
            ],
            "params": norm_params,
        }
    )
    provenance_path.write_text(json.dumps(provenance, indent=2, default=_serialise_for_json) + "\n")

    # Update manifest.json with the normalized VCF identity.
    manifest["outputs"]["normalized_vcf"] = "normalized.vcf.gz"
    manifest["outputs"]["normalized_vcf_sha256"] = norm_vcf_sha
    manifest["outputs"]["normalized_tbi_sha256"] = norm_tbi_sha
    manifest_path.write_text(json.dumps(manifest, indent=2, default=_serialise_for_json) + "\n")

    log.info("normalize complete: out=%s", norm_vcf)
    if progress_callback is not None:
        progress_callback(
            PhaseComplete(
                phase="normalize",
                duration_sec=time.monotonic() - phase_start_mono,
                run_dir=str(run_dir),
            )
        )
    return norm_vcf


__all__ = ["normalize"]

"""``genomeclaw pipeline ingest`` orchestration.

Composes the Phase-2 primitives into a single happy-path pipeline:

```
    validate inputs
        └→ compute SHA256 of source VCF
            └→ read contigs from header
                └→ sniff reference build (raises AmbiguousReferenceBuild)
                    └→ generate run-id
                        └→ create derived/<run-id>/
                            └→ index VCF if .tbi missing (under derived/)
                                └→ create DuckDB store + write variants
                                    └→ write manifest.json + provenance.json
                                        └→ atomically swing CURRENT
```

Sub-phase 2C-B-2 ships the VCF-only path. Sub-phase 2C-C adds BAM /
mosdepth / bcftools-stats steps; the orchestrator's shape is designed
to absorb them as appended provenance steps + manifest fields.

`INV-D001`: source files are read but never written. The optional ``.tbi``
build target is always under ``derived/<run-id>/``.

`INV-R001`: every variants row carries the seven canonical provenance
columns; the manifest pins tool versions; the run-id + image digest
identify the producing environment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from genomeclaw_toolkit import __version__ as TOOLKIT_VERSION
from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._bcftools import bcftools_index_tbi
from genomeclaw_toolkit.prep._bcftools_stats import bcftools_stats
from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart, emit_beat
from genomeclaw_toolkit.prep._mosdepth import (
    mosdepth_version,
    parse_regions_bed,
    run_mosdepth,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit.prep._events import _ProgressEvent
from genomeclaw_toolkit.prep._vcf import iter_variant_rows, read_contigs
from genomeclaw_toolkit.prep._versions import collect_tool_versions, image_digest
from genomeclaw_toolkit.prep.reference_build import (
    sniff_reference_build,
    validate_reference_build_match,
)
from genomeclaw_toolkit.prep.run_id import generate_run_id, update_current_symlink
from genomeclaw_toolkit.prep.store import (
    ProvenanceTag,
    create_store,
    write_coverage_qc,
    write_variants,
)
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default coverage-QC panel (AC2 — auto-engage when bam given, no bed).
# ---------------------------------------------------------------------------

_DEFAULT_PANEL_BED_NAME = "coverage_panel_default_v1.bed.gz"
"""Filename of the bundled default gene-panel BED (shipped inside the package)."""

_DEFAULT_PANEL_VERSION = "v1"
"""Version token recorded in coverage_qc.params_json (INV-R001)."""

_DEFAULT_LOW_COVERAGE_THRESHOLD = "20x"
"""Low-coverage threshold recorded in coverage_qc.params_json (INV-R001)."""


def _default_panel_bed_path() -> Path | None:
    """Resolve the bundled default-panel BED path, or None if not staged.

    Resolves to ``<package_root>/data/<_DEFAULT_PANEL_BED_NAME>``.
    Returns ``None`` when the file is absent so callers can emit a WARNING
    and skip the coverage_qc step gracefully.
    """
    candidate = Path(__file__).parent.parent / "data" / _DEFAULT_PANEL_BED_NAME
    return candidate if candidate.exists() else None


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


# VCF suffixes we treat as the source variant call set for autodetect.
# Order matters only for the error message — every match is reported.
_VCF_SUFFIXES = (".vcf.gz", ".vcf.bgz")


def autodetect_sample_inputs(raw_root: Path) -> tuple[str, Path]:
    """Resolve ``(sample_id, vcf_path)`` from a raw root containing one sample.

    Walks ``raw_root`` and requires exactly one subdirectory. That
    subdirectory's name becomes the sample id; the unique ``*.vcf.gz`` /
    ``*.vcf.bgz`` inside it becomes the VCF path. Any other shape (zero
    sample dirs, multiple sample dirs, zero VCFs, multiple VCFs) raises
    ``ValueError`` with a message that names the offending paths so the
    caller can surface a useful CLI error.

    Tabix indexes are ignored — autodetect only resolves the bgzipped
    VCF itself; ``ingest`` either reuses the source ``.tbi`` or rebuilds
    one under ``derived/``.
    """
    if not raw_root.is_dir():
        raise ValueError(f"raw root not found: {raw_root}")

    sample_dirs = sorted(p for p in raw_root.iterdir() if p.is_dir())
    if not sample_dirs:
        raise ValueError(
            f"raw root {raw_root} has no sample subdirectories; "
            "stage a sample under raw/<sample-id>/ or pass --vcf <path> --sample-id <id>"
        )
    if len(sample_dirs) > 1:
        names = ", ".join(p.name for p in sample_dirs)
        raise ValueError(
            f"raw root {raw_root} has multiple sample subdirectories ({names}); "
            "pass --vcf <path> --sample-id <id> to pick one"
        )

    sample_dir = sample_dirs[0]
    vcfs = sorted(p for p in sample_dir.iterdir() if p.is_file() and p.name.endswith(_VCF_SUFFIXES))
    if not vcfs:
        raise ValueError(
            f"no .vcf.gz / .vcf.bgz found under {sample_dir}; "
            "pass --vcf <path> to point at a bgzipped VCF explicitly"
        )
    if len(vcfs) > 1:
        names = ", ".join(p.name for p in vcfs)
        raise ValueError(
            f"multiple bgzipped VCFs found under {sample_dir} ({names}); "
            "pass --vcf <path> to disambiguate"
        )
    return sample_dir.name, vcfs[0]


def ingest(
    *,
    vcf: Path,
    reference_dir: Path,
    derived_root: Path,
    sample_id: str,
    bam: Path | None = None,
    bed: Path | None = None,
    no_coverage_qc: bool = False,
    reference_fasta: Path | None = None,
    started_at: datetime | None = None,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path:
    """Run the Phase-2 ingest. Returns the derived run dir.

    Args:
        vcf: source bgzipped VCF under ``raw/``.
        reference_dir: reference dir (e.g. ``reference/grch38/``); the
            existence is verified, contents are not consulted in v0.1.
        derived_root: writable root that receives ``<run-id>/`` plus
            ``CURRENT``. The shim bind-mounts ``$GENOMECLAW_DERIVED_DIR``
            here.
        sample_id: short identifier the user picks; recorded on every
            row's provenance + in the manifest.
        bam: optional source BAM or CRAM. When given, ``mosdepth`` runs
            against it and a per-gene coverage_qc table is populated.
            When ``bed`` is not given, the bundled default panel BED is
            used automatically (see ``_default_panel_bed_path()``).
            CRAM input (``.cram`` suffix) additionally requires
            ``reference_fasta``.
        bed: optional gene-list BED for ``mosdepth``'s ``--by`` flag.
            When omitted and ``bam`` is given, the bundled default panel
            BED is used. Pass an explicit path to override the default.
        no_coverage_qc: when ``True``, skip the mosdepth step entirely
            even when ``bam`` is given. Useful for quick ingests where
            coverage data is not needed. Opt-out for the default-panel
            auto-engage behaviour.
        reference_fasta: optional bgzipped reference fasta (with
            ``.fai`` + ``.gzi`` sidecars from ``samtools faidx``).
            Required when ``bam`` is a CRAM; ignored for BAM. Recorded
            on the ``mosdepth-coverage`` provenance step (`INV-R001`).
            Phase 4B addition.
        started_at: optional fixed UTC timestamp; defaults to
            ``datetime.now(tz=UTC)``. Tests pass a fixed value to drive
            the determinism scaffold (case 8).
    """
    preflight.assert_raw_readonly()
    preflight.assert_reference_readonly()
    preflight.assert_derived_writable()
    preflight.assert_scratch_writable()

    if not vcf.exists():
        raise FileNotFoundError(f"vcf not found: {vcf}")
    if not reference_dir.exists():
        raise FileNotFoundError(f"reference dir not found: {reference_dir}")
    if not derived_root.exists():
        raise FileNotFoundError(f"derived root not found: {derived_root}")
    if bam is not None and not bam.exists():
        raise FileNotFoundError(f"bam not found: {bam}")
    if bed is not None and not bed.exists():
        raise FileNotFoundError(f"bed not found: {bed}")
    if bam is not None and bam.suffix == ".cram" and reference_fasta is None:
        raise ValueError(
            "reference_fasta is required when bam is a CRAM "
            "(mosdepth + htslib need the reference for CRAM decoding)"
        )
    if reference_fasta is not None and not reference_fasta.exists():
        raise FileNotFoundError(f"reference_fasta not found: {reference_fasta}")

    # Auto-engage the default coverage-QC panel when bam is given but bed
    # is not explicitly supplied and the operator hasn't opted out.
    # INV-R001: the panel provenance (version, path, threshold) is threaded
    # into coverage_qc.params_json below, at the write step.
    _panel_is_default = False
    if bam is not None and bed is None and not no_coverage_qc:
        default_panel = _default_panel_bed_path()
        if default_panel is not None:
            log.info(
                "Auto-engaging default coverage-QC panel: %s (version=%s)",
                _DEFAULT_PANEL_BED_NAME,
                _DEFAULT_PANEL_VERSION,
            )
            bed = default_panel
            _panel_is_default = True
        else:
            log.warning(
                "Default coverage-QC panel BED not found at the canonical path; "
                "skipping the coverage_qc step. Run `genomeclaw doctor` to verify "
                "the install, or pass --bed to supply an explicit panel."
            )

    if started_at is None:
        started_at = datetime.now(tz=UTC)
    log.info("ingest starting: vcf=%s bam=%s sample_id=%s", vcf, bam, sample_id)

    phase_start_mono = time.monotonic()
    if progress_callback is not None:
        progress_callback(PhaseStart(phase="ingest"))

    emit_beat(
        progress_callback,
        phase="ingest",
        message=f"computing source VCF sha256 ({vcf.name})",
        logger=log,
    )
    vcf_sha = _sha256_file(vcf)

    # Sniff the reference build before we commit any output. An
    # AmbiguousReferenceBuild raise here leaves derived_root untouched.
    # Then soft-validate the reference dir against the sniffed build —
    # catches the typo case where the user picks the wrong build dir.
    contigs = read_contigs(vcf)
    reference_build = sniff_reference_build(contigs)
    validate_reference_build_match(reference_dir, reference_build)
    emit_beat(
        progress_callback,
        phase="ingest",
        message=f"inferred reference build {reference_build} from VCF contig headers",
        logger=log,
    )

    run_id = generate_run_id(input_sha256=vcf_sha, started_at=started_at)
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    emit_beat(
        progress_callback,
        phase="ingest",
        message=f"allocated run dir {run_dir.name}",
        logger=log,
    )

    # Index under derived/ if the source's .tbi is missing.
    src_tbi = vcf.parent / f"{vcf.name}.tbi"
    if src_tbi.exists():
        tbi_path = src_tbi
        tbi_sha: str | None = _sha256_file(src_tbi)
    else:
        emit_beat(
            progress_callback,
            phase="ingest",
            message="source VCF has no .tbi sidecar — indexing under derived/",
            logger=log,
        )
        tbi_path = bcftools_index_tbi(vcf=vcf, derived_dir=run_dir)
        tbi_sha = _sha256_file(tbi_path)

    # Create the store + stream rows.
    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    tag = ProvenanceTag(
        source_path=str(vcf),
        source_sha256=vcf_sha,
        tool="genomeclaw-prep",
        tool_version=TOOLKIT_VERSION,
        params_json=json.dumps({"sample_id": sample_id}, sort_keys=True),
        schema_version=SCHEMA_VERSION,
        created_at=started_at,
    )

    # Scratch lives as a sibling of derived_root. In production this
    # resolves to /mnt/genomeclaw/scratch (the canonical post-Phase-2
    # scratch tier on virtiofs+APFS); in tests, to <tmp>/scratch (set
    # up by the ``genomeclaw_layout`` fixture).
    scratch_dir = derived_root.parent / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    def _row_stream() -> Iterator[dict[str, Any]]:
        # Override sample_id from the CLI arg so the manifest + variants
        # table agree (the VCF's #CHROM column is informational; the
        # ingest invocation's sample_id is authoritative).
        for row in iter_variant_rows(vcf):
            yield {**row, "sample_id": sample_id}

    emit_beat(
        progress_callback,
        phase="ingest",
        message="streaming variants into duckdb (slow step on real-scale ingest)",
        logger=log,
    )
    write_variants(store_path, _row_stream(), tag=tag, work_dir=scratch_dir)
    ingest_completed_at = datetime.now(tz=UTC)
    emit_beat(
        progress_callback,
        phase="ingest",
        message=f"variants table written: {store_path.name}",
        logger=log,
    )

    steps: list[dict[str, Any]] = [
        {
            "step": "ingest",
            "tool": "genomeclaw-prep",
            "tool_version": TOOLKIT_VERSION,
            "started_at": started_at,
            "completed_at": ingest_completed_at,
            "inputs": [{"path": str(vcf), "sha256": vcf_sha}],
            "outputs": [{"path": "variants.duckdb", "sha256": _sha256_file(store_path)}],
            "params": {"sample_id": sample_id},
        }
    ]

    # bcftools stats — populate manifest's qc.bcftools_stats block (case 19).
    emit_beat(progress_callback, phase="ingest", message="running bcftools stats", logger=log)
    stats_started_at = datetime.now(tz=UTC)
    stats_result = bcftools_stats(vcf)
    emit_beat(
        progress_callback,
        phase="ingest",
        message=(
            f"bcftools stats · ts_tv={stats_result.ts_tv_ratio:.3f} "
            f"snps={stats_result.n_snps} indels={stats_result.n_indels}"
        ),
        logger=log,
    )
    qc_payload: dict[str, Any] = {
        "bcftools_stats": {
            "ts_tv_ratio": stats_result.ts_tv_ratio,
            "n_snps": stats_result.n_snps,
            "n_indels": stats_result.n_indels,
        }
    }
    steps.append(
        {
            "step": "bcftools-stats",
            "tool": "bcftools",
            "tool_version": collect_tool_versions().get("bcftools", "unknown"),
            "started_at": stats_started_at,
            "completed_at": datetime.now(tz=UTC),
            "inputs": [{"path": str(vcf), "sha256": vcf_sha}],
            "outputs": [],
            "params": {},
        }
    )

    # mosdepth — populate coverage_qc + append step (cases 20, 21).
    # Fires when: bam is given + bed is resolved (explicit or auto-engaged default)
    # + the operator hasn't opted out via no_coverage_qc=True.
    bam_path: Path | None = None
    bam_sha: str | None = None
    if bam is not None and bed is not None and not no_coverage_qc:
        emit_beat(
            progress_callback,
            phase="ingest",
            message=f"computing BAM/CRAM sha256 ({bam.name})",
            logger=log,
        )
        mosdepth_started_at = datetime.now(tz=UTC)
        bam_path = bam
        bam_sha = _sha256_file(bam)

        mos_prefix = scratch_dir / "mosdepth" / run_id
        mos_prefix.parent.mkdir(parents=True, exist_ok=True)
        emit_beat(
            progress_callback,
            phase="ingest",
            message=f"running mosdepth coverage against {bam.name}",
            logger=log,
        )
        mosdepth_result = run_mosdepth(
            bam=bam,
            bed=bed,
            out_prefix=mos_prefix,
            reference_fasta=reference_fasta,
        )
        # Strip the "x" suffix from the canonical "20x" form to get a float
        # threshold for the per-exon < threshold check.
        threshold_float = float(_DEFAULT_LOW_COVERAGE_THRESHOLD.rstrip("x"))
        coverage_rows = parse_regions_bed(
            mosdepth_result.regions_bed,
            low_coverage_threshold=threshold_float,
        )

        # INV-R001: params_json records the panel BED path + version + threshold.
        # When the default panel was auto-engaged, record the canonical panel
        # metadata so the row is self-describing.  For operator-supplied custom
        # BEDs, record "custom" as the version.
        if _panel_is_default:
            coverage_params: dict[str, Any] = {
                "panel_version": _DEFAULT_PANEL_VERSION,
                "panel_path": _DEFAULT_PANEL_BED_NAME,
                "low_coverage_threshold": _DEFAULT_LOW_COVERAGE_THRESHOLD,
            }
        else:
            coverage_params = {
                "panel_version": "custom",
                "panel_path": str(bed),
            }
        mosdepth_step_params: dict[str, Any] = {}
        mosdepth_step_inputs: list[dict[str, Any]] = [
            {"path": str(bam), "sha256": bam_sha},
            {"path": str(bed), "sha256": _sha256_file(bed)},
        ]
        if reference_fasta is not None:
            ref_fasta_sha = _sha256_file(reference_fasta)
            coverage_params["reference_fasta"] = str(reference_fasta)
            mosdepth_step_params["fasta_path"] = str(reference_fasta)
            mosdepth_step_params["fasta_sha256"] = ref_fasta_sha
            mosdepth_step_inputs.append({"path": str(reference_fasta), "sha256": ref_fasta_sha})

        coverage_tag = ProvenanceTag(
            source_path=str(bam),
            source_sha256=bam_sha,
            tool="mosdepth",
            tool_version=mosdepth_version(),
            params_json=json.dumps(coverage_params, sort_keys=True),
            schema_version=SCHEMA_VERSION,
            created_at=started_at,
        )
        write_coverage_qc(
            store_path,
            (
                {
                    "gene": r.gene,
                    "mean_depth": r.mean_depth,
                    "low_coverage_exons": r.low_coverage_exons,
                }
                for r in coverage_rows
            ),
            tag=coverage_tag,
        )
        steps.append(
            {
                "step": "mosdepth-coverage",
                "tool": "mosdepth",
                "tool_version": mosdepth_version(),
                "started_at": mosdepth_started_at,
                "completed_at": datetime.now(tz=UTC),
                "inputs": mosdepth_step_inputs,
                "outputs": [],
                "params": mosdepth_step_params,
            }
        )

    # Manifest.
    manifest_payload: dict[str, Any] = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "input": {
            "vcf_path": str(vcf),
            "vcf_sha256": vcf_sha,
            "tbi_path": str(tbi_path),
            "tbi_sha256": tbi_sha,
            "reference_path": str(reference_dir),
            "reference_build_inferred": reference_build,
        },
        "tools": collect_tool_versions(),
        "params": {"sample_id": sample_id},
        "outputs": {
            "derived_dir": str(run_dir),
            "variants_table": "variants.duckdb",
        },
        "qc": qc_payload,
        "created_at": started_at,
    }
    if bam_path is not None and bam_sha is not None:
        manifest_payload["input"]["bam_path"] = str(bam_path)
        manifest_payload["input"]["bam_sha256"] = bam_sha
    digest = image_digest()
    if digest is not None:
        manifest_payload["image_digest"] = digest
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, default=_serialise_for_json) + "\n"
    )

    # Provenance.
    provenance_payload = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "steps": steps,
    }
    (run_dir / "provenance.json").write_text(
        json.dumps(provenance_payload, indent=2, default=_serialise_for_json) + "\n"
    )

    # Atomic CURRENT swing.
    update_current_symlink(derived_root, run_id)
    log.info("ingest complete: run_id=%s", run_id)

    if progress_callback is not None:
        progress_callback(
            PhaseComplete(
                phase="ingest",
                duration_sec=time.monotonic() - phase_start_mono,
                run_dir=str(run_dir),
            )
        )
    return run_dir


__all__ = [
    "autodetect_sample_inputs",
    "ingest",
    "_DEFAULT_PANEL_BED_NAME",
    "_DEFAULT_PANEL_VERSION",
    "_DEFAULT_LOW_COVERAGE_THRESHOLD",
    "_default_panel_bed_path",
]

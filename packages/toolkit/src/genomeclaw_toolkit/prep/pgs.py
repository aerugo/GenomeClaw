"""`pgsc_calc` wrapper for agent-triggered PRS computation (Phase 6 Slice E v2).

Drives the PGS Catalog Calculator (Nextflow pipeline) against a single user
VCF + one PGS Catalog ID. Applies continuous-ancestry calibration via
`--run_ancestry` so the returned percentile is honest for non-European
ancestries (the calibration_warning fires when the user's ancestry estimate
falls outside the training distribution; per `INV-C001` v1.7 this surfaces
structurally rather than being silently dropped).

Threading INV-A003 provenance: the agent's `agent_choice_rationale` +
`requested_for_question` are inputs to this wrapper, persist into the
returned :class:`PgsRow`, and land as columns on the `pgs_scores` row via
the CLI subcommand. The whole chain — request → wrapper → row → memory note
— carries the agent's reasoning alongside the score so an audit can
reconstruct *why* this PGS was chosen for *this* question.

`pgsc_calc` is a Nextflow pipeline + therefore a heavy host-side dependency.
The wrapper subprocess-invokes it; tests stub `subprocess.run` and provide
fixture output files. Real-data verification runs as a manual smoke against
the project owner's host install.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PgsRow:
    """The agent-triggered compute output, ready for INSERT into `pgs_scores`.

    Carries the 6 domain fields + 2 INV-A003 provenance fields. The 7
    canonical INV-R001 provenance columns (source_path, source_sha256,
    tool, tool_version, params_json, schema_version, created_at) are
    stamped by the CLI subcommand at INSERT time, not by the wrapper.
    """

    pgs_id: str
    trait_label: str
    percentile_in_user_ancestry: float | None
    raw_score: float | None
    study_population: str
    calibration_warning: str | None
    agent_choice_rationale: str
    requested_for_question: str


class PgsReferenceMissingError(RuntimeError):
    """The 1000G / HGDP continuous-ancestry reference data is missing.

    Surfaces as a clean install hint rather than a raw Nextflow stack
    trace, so the user (or the agent surfacing this to the user) gets a
    single actionable line.
    """


# Canonical release tag for the PGS Catalog continuous-ancestry reference
# bundle. Mirrors the pin in ``prep/release_sets/default.toml``; bump both
# when PGS Catalog re-cuts the bundle. Surfaces in install hints so the
# user can re-fetch the exact pinned release.
_PGS_ANCESTRY_RELEASE = "v1"


# Canonical presence files inside the extracted ancestry tree (verified
# upstream layout 2026-05-17 against real-data smoke). PGS Catalog ships
# the gnomAD-merged 1000G + HGDP callset as combined files keyed by
# reference build — NOT per-population subdirs as initially assumed.
# ``host doctor`` (PRS Reference Bootstrap Phase 2) probes these three
# files to classify ``ancestry_ready`` as ``ready``/``partial``/``missing``;
# the fetch ``presence_relpath`` marker uses just the .pgen as its single
# skip-detection anchor. Keeping the triple here is the single source of
# truth so the two layers don't drift.
_PGS_ANCESTRY_PRESENCE_FILES: tuple[str, ...] = (
    "GRCh38_HGDP+1kGP_ALL.pgen",
    "GRCh38_HGDP+1kGP_ALL.pvar.zst",
    "GRCh38_HGDP+1kGP_ALL.psam",
)


def _ancestry_reference_dir(reference_root: Path, release: str = _PGS_ANCESTRY_RELEASE) -> Path:
    """Resolve the canonical post-fetch ancestry-reference layout root.

    ``genomeclaw refs fetch --source pgs_catalog_ancestry --release <X>``
    lands the extracted 1000G + HGDP panels under
    ``reference/pgs_catalog_ancestry/<X>/{1000g,hgdp}/``. The directory
    returned here is the path ``pgsc_calc --run_ancestry`` consumes.
    """
    return reference_root / "pgs_catalog_ancestry" / release


def _check_ancestry_reference(reference_root: Path) -> None:
    """Verify the gnomAD-merged 1000G + HGDP ancestry reference data is staged.

    Verified upstream layout (2026-05-17): the PGS Catalog bundle extracts
    FLAT (no per-population subdirs) into the release directory; pgsc_calc
    consumes the combined ``GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}``
    files for continuous-ancestry calibration.

    Raises:
        PgsReferenceMissingError: when any required file is absent. Names
            the canonical ``genomeclaw refs fetch`` install hint, with the
            release tag pinned in ``prep/release_sets/default.toml``.
    """
    ancestry_root = _ancestry_reference_dir(reference_root)
    needed = [ancestry_root / relpath for relpath in _PGS_ANCESTRY_PRESENCE_FILES]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        raise PgsReferenceMissingError(
            "PGS Catalog continuous-ancestry reference data (gnomAD-merged "
            "1000G + HGDP, GRCh38) is required for pgsc_calc --run_ancestry "
            f"but the following files are missing: {missing}. Install with: "
            f"genomeclaw refs fetch --source pgs_catalog_ancestry "
            f"--release {_PGS_ANCESTRY_RELEASE}"
        )


def _build_pgsc_calc_argv(
    *,
    vcf: Path,
    pgs_id: str,
    work_dir: Path,
    reference_root: Path,
) -> list[str]:
    """Build the `nextflow run pgscatalog/pgsc_calc` invocation argv.

    Uses ``--target_build GRCh38`` (canonical reference build per
    architecture.md) + ``--run_ancestry`` (mandatory per ``INV-C001`` v1.7
    ancestry calibration) + ``--pgs_id <id>`` (single-PGS run) +
    ``-profile conda`` (the only profile that stays inside GenomeClaw's
    image-or-volume boundary; per PRS Runtime Bootstrap Phase 1).

    Per-process scoring deps (plink2/plink/R/Bioconductor) are materialised
    by Nextflow into ``$NXF_CONDA_CACHEDIR`` on first run; the caller's
    environment must set:

        NXF_HOME=/mnt/genomeclaw/reference/nextflow-cache
        NXF_CONDA_CACHEDIR=/mnt/genomeclaw/reference/nextflow-cache/conda

    so the materialised envs persist on the bind-mounted reference volume
    across container restarts (``INV-D003``: heavy scratch separated from
    authoritative outputs; conda envs are reference-data-like and live in
    ``reference/``, not ``_scratch/``).

    The pipeline revision (``-r v2.2.0``) is pinned to the value in
    ``_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`` so the wrapper's
    ``pgs_scores.params_json`` provenance trail records exactly which
    pgsc_calc release scored the user's variants.

    The samplesheet is implicit in the v0 wrapper — pgsc_calc's ``--target``
    accepts a single VCF directly when no samplesheet is supplied, which
    keeps the wrapper interface narrow. A future multi-sample / multi-trait
    variant can build the samplesheet CSV explicitly.
    """
    from genomeclaw_toolkit.prep._versions import PRS_RUNTIME_VERSIONS

    return [
        "nextflow",
        "run",
        "pgscatalog/pgsc_calc",
        "-r",
        PRS_RUNTIME_VERSIONS["pgsc_calc"],
        "-profile",
        "conda",
        "--target",
        str(vcf),
        "--target_build",
        "GRCh38",
        "--pgs_id",
        pgs_id,
        "--run_ancestry",
        str(_ancestry_reference_dir(reference_root)),
        "-work-dir",
        str(work_dir),
    ]


def _parse_aggregated_scores(work_dir: Path, pgs_id: str) -> tuple[float | None, str]:
    """Parse `<work_dir>/score/aggregated_scores.txt`. Returns (raw_score, study_pop).

    pgsc_calc's output schema: `sampleset\\tIID\\tPGS\\tSUM\\tDENOM\\tAVG`.
    The `AVG` column is the raw score; the wrapper returns this + a
    canonical study-population string (the v0 wrapper hard-codes
    "PGS Catalog scoring weights" until a richer parser ships).
    """
    score_path = work_dir / "score" / "aggregated_scores.txt"
    if not score_path.exists():
        return (None, "PGS Catalog scoring weights")
    raw_score: float | None = None
    with score_path.open() as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            cells = line.rstrip("\n").split("\t")
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells, strict=True))
            if row.get("PGS") != pgs_id:
                continue
            try:
                raw_score = float(row.get("AVG", ""))
            except ValueError:
                raw_score = None
            break
    return (raw_score, "PGS Catalog scoring weights")


def _parse_aggregated_scores_norm(work_dir: Path, pgs_id: str) -> tuple[float | None, str | None]:
    """Parse `<work_dir>/ancestry/aggregated_scores_norm.txt`. Returns (percentile, warning).

    pgsc_calc's continuous-ancestry output schema:
    `sampleset\\tIID\\tPGS\\tpercentile_MostSimilarPop\\tcalibration_warning`.
    An empty `calibration_warning` cell normalizes to `None`.
    """
    norm_path = work_dir / "ancestry" / "aggregated_scores_norm.txt"
    if not norm_path.exists():
        return (None, None)
    percentile: float | None = None
    warning: str | None = None
    with norm_path.open() as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            cells = line.rstrip("\n").split("\t")
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells, strict=True))
            if row.get("PGS") != pgs_id:
                continue
            try:
                percentile = float(row.get("percentile_MostSimilarPop", ""))
            except ValueError:
                percentile = None
            warning_raw = row.get("calibration_warning", "").strip()
            warning = warning_raw if warning_raw else None
            break
    return (percentile, warning)


def compute_pgs(
    *,
    vcf: Path,
    pgs_id: str,
    reference_root: Path,
    work_dir: Path,
    agent_choice_rationale: str,
    requested_for_question: str,
    trait_label: str | None = None,
) -> PgsRow:
    """Run `pgsc_calc` against `vcf` for one `pgs_id`; return a typed :class:`PgsRow`.

    Args:
        vcf: source VCF (read-only). `pgsc_calc` reads it host-side; no
            genomic data crosses any network boundary (`INV-D001`).
        pgs_id: PGS Catalog ID (e.g. `PGS000018`). The wrapper passes
            this to `pgsc_calc --pgs_id`.
        reference_root: root dir under which `ancestry/{1000g,hgdp}/`
            + `pgs_catalog/` live. Required for ancestry calibration.
        work_dir: Nextflow work directory (heavy intermediates land
            here; safe to delete after the wrapper returns).
        agent_choice_rationale: the agent's reasoning for picking this
            PGS + alternatives considered (`INV-A003` provenance;
            threads into the returned row + persists as a column on
            `pgs_scores`).
        requested_for_question: verbatim user question that triggered
            the compute (`INV-A003` provenance).
        trait_label: optional human-readable label for the trait. When
            omitted, the v0 wrapper synthesises ``"PGS Catalog
            <pgs_id>"`` so the row carries a non-empty label.

    Returns:
        A :class:`PgsRow` ready for INSERT into `pgs_scores`. The seven
        canonical INV-R001 provenance columns are stamped at INSERT
        time by the CLI subcommand, not by this wrapper.

    Raises:
        PgsReferenceMissingError: when the ancestry reference data is
            missing (clean install hint instead of a Nextflow trace).
        subprocess.CalledProcessError: when `pgsc_calc` exits non-zero.
    """
    _check_ancestry_reference(reference_root)
    work_dir.mkdir(parents=True, exist_ok=True)

    argv = _build_pgsc_calc_argv(
        vcf=vcf, pgs_id=pgs_id, work_dir=work_dir, reference_root=reference_root
    )
    proc = subprocess.run(argv, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"pgsc_calc failed (rc={proc.returncode}):\n{stderr_text}")

    raw_score, study_population = _parse_aggregated_scores(work_dir, pgs_id)
    percentile, calibration_warning = _parse_aggregated_scores_norm(work_dir, pgs_id)

    return PgsRow(
        pgs_id=pgs_id,
        trait_label=trait_label or f"PGS Catalog {pgs_id}",
        percentile_in_user_ancestry=percentile,
        raw_score=raw_score,
        study_population=study_population,
        calibration_warning=calibration_warning,
        agent_choice_rationale=agent_choice_rationale,
        requested_for_question=requested_for_question,
    )


__all__ = [
    "PgsReferenceMissingError",
    "PgsRow",
    "compute_pgs",
]

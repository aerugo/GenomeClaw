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

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from genomeclaw_toolkit.prep._paths import SiblingMountablePath, as_sibling_mountable
from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions


@dataclass(frozen=True)
class PgsRow:
    """The agent-triggered compute output, ready for INSERT into `pgs_scores`.

    Carries the 6 domain fields + 2 INV-A003 provenance fields + 2
    optional INV-C001 v1.7 calibration fields. The 7 canonical INV-R001
    provenance columns (source_path, source_sha256, tool, tool_version,
    params_json, schema_version, created_at) are stamped by the CLI
    subcommand at INSERT time, not by the wrapper.

    The calibration fields default to ``None`` for backwards compatibility
    with existing callers; the Phase 3a classifier in
    :mod:`genomeclaw_toolkit.prep._pgs_qc` produces a
    :class:`CalibrationDecision` that :func:`apply_calibration_decision`
    attaches to a row.
    """

    pgs_id: str
    trait_label: str
    percentile_in_user_ancestry: float | None
    raw_score: float | None
    study_population: str
    calibration_warning: str | None
    agent_choice_rationale: str
    requested_for_question: str
    calibration_status: str | None = None  # "clean" | "warning" | "decline" | None
    decline_reason: str | None = None  # DeclineReason.value when status == "decline"


def apply_calibration_decision(row: "PgsRow", decision: object) -> "PgsRow":
    """Return a new :class:`PgsRow` with the calibration decision attached.

    Pure function — never mutates ``row``; returns a new frozen instance via
    :func:`dataclasses.replace`. The decline-reason is stamped as the enum's
    ``.value`` (snake_case string) so the future DuckDB column type stays
    `TEXT` rather than requiring a custom enum.

    Args:
        row: The base :class:`PgsRow` (typically from :func:`compute_pgs`).
        decision: A :class:`CalibrationDecision` from
            :func:`_pgs_qc.classify_calibration`. Typed as ``object`` to
            avoid a circular import on the optional classifier module;
            attribute access is duck-typed.

    Raises:
        ValueError: when ``decision.status`` is ``DECLINE`` but
            ``decision.decline_reason`` is ``None`` (structural invalid
            state the classifier never produces but a buggy caller might).
    """
    import dataclasses

    status_str = decision.status.value  # type: ignore[attr-defined]
    decline_reason_value: str | None = None
    if status_str == "decline":
        if decision.decline_reason is None:  # type: ignore[attr-defined]
            raise ValueError(
                "CalibrationDecision with status=DECLINE must populate decline_reason "
                "(INV-C001 v1.7)"
            )
        decline_reason_value = decision.decline_reason.value  # type: ignore[attr-defined]

    return dataclasses.replace(
        row,
        calibration_status=status_str,
        decline_reason=decline_reason_value,
    )


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
    """Resolve the canonical post-fetch ancestry-reference directory.

    ``genomeclaw refs fetch --source pgs_catalog_ancestry --release <X>``
    lands the extracted bundle (Citation.txt, GRCh38_HGDP+1kGP_ALL.{pgen,
    pvar.zst,psam}, the tarball itself, etc.) under
    ``reference/pgs_catalog_ancestry/<X>/``. The directory returned here
    is the parent that ``_check_ancestry_reference`` walks for presence;
    pgsc_calc's ``--run_ancestry`` consumes the TARBALL inside it via
    :func:`_ancestry_reference_bundle`.
    """
    return reference_root / "pgs_catalog_ancestry" / release


def _ancestry_reference_bundle(
    reference_root: Path, release: str = _PGS_ANCESTRY_RELEASE
) -> Path:
    """Resolve the ancestry-reference TARBALL ``pgsc_calc --run_ancestry`` consumes.

    pgsc_calc's ``EXTRACT_DATABASE`` task runs ``tar -xf <path> ...`` against
    the value of ``--run_ancestry``. It expects a tar (or zstd-tar) bundle,
    not an extracted directory. Phase 7 smoke v10 (2026-05-19) surfaced this
    as ``EXTRACT_DATABASE`` exit-2 (tar refusing to read a directory as a
    tar archive).

    The canonical PGS Catalog reference bundle is named
    ``pgs_catalog_ancestry.tar.zst`` and ships inside the extracted release
    dir alongside the per-build panel files.
    """
    return _ancestry_reference_dir(reference_root, release) / "pgs_catalog_ancestry.tar.zst"


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


def _write_pgsc_calc_samplesheet(
    *,
    vcf: SiblingMountablePath,
    sample_id: str,
    work_dir: SiblingMountablePath,
    conventions: PgscCalcConventions | None = None,
) -> Path:
    """Materialise a pgsc_calc samplesheet CSV at ``work_dir/samplesheet.csv``.

    Header columns + the ``path_prefix`` suffix-stripping rule are read
    from :class:`PgscCalcConventions`, NOT hardcoded — so a future pgsc_calc
    pin bump that changes the schema is a typed-test failure rather than
    a silent ``rc=1`` against real input.

    Per the conventions (verified against pgsc_calc v2.2.0):

    * header == ``conv.samplesheet_columns`` (column order matters).
    * ``path_prefix`` is a file prefix WITHOUT the ``.vcf.gz`` / ``.vcf``
      extension when ``conv.path_prefix_strips_extension`` is True. The
      2026-05-19 smoke failed with ``No such file: merged.vcf.gz.vcf`` —
      pgsc_calc auto-appends ``.vcf`` and re-detects ``.gz``.
    * ``chrom`` is blank for the multi-chrom case.
    * ``vcf_genotype_field`` defaults to ``conv.vcf_genotype_field_default``.
    """
    conv = conventions or PgscCalcConventions()
    work_dir.mkdir(parents=True, exist_ok=True)
    samplesheet = Path(work_dir / "samplesheet.csv")

    if conv.path_prefix_strips_extension:
        path_prefix = str(vcf).removesuffix(".gz").removesuffix(".vcf")
    else:
        path_prefix = str(vcf)

    row_values: dict[str, str] = {
        "sampleset": sample_id,
        "path_prefix": path_prefix,
        "chrom": "",
        "format": "vcf",
        "vcf_genotype_field": conv.vcf_genotype_field_default,
    }
    header = ",".join(conv.samplesheet_columns)
    row = ",".join(row_values.get(col, "") for col in conv.samplesheet_columns)
    samplesheet.write_text(f"{header}\n{row}\n")
    return samplesheet


_NEXTFLOW_CONFIG_FILENAME = "nextflow.config"

# Deployment config nextflow reads at task-spawn time. Redirects each
# sibling task's TMPDIR to its bind-mounted work-dir (which lives on the
# host's 2 TB external drive). Without this, Python's tempfile module
# inside a sibling defaults to /tmp — the container's writable layer,
# which lives on the colima VM data disk (typically 98 GB). pgsc_calc's
# ``INTERSECT_VARIANTS`` task writes ~8 GB of temp data while processing
# the 82M-variant HGDP+1kGP panel; smoke v11 (2026-05-19) surfaced this
# as ``OSError: [Errno 28] No space left on device``.
#
# Single-quoted in groovy so ``${PWD}`` is NOT groovy-interpolated; it
# resolves at sibling-task time via bash, which sees each task's own
# work-dir.
_TMPDIR_REDIRECT_CONFIG = """\
// Auto-generated by genomeclaw-toolkit (pgs.py:_write_pgsc_calc_nextflow_config)
//
// Three deployment overrides for DooD-spawning pipelines like pgsc_calc:
//
// 1. TMPDIR redirect: each sibling task's Python tempfile-style writes
//    target ``${PWD}`` (the bind-mounted work-dir on the host external
//    scratch drive) rather than ``/tmp`` (the container writable layer
//    on the small colima VM data disk). Closes the smoke-v11 disk-
//    exhaustion gap (``INTERSECT_VARIANTS`` ENOSPC).
//
// 2. stageInMode = 'copy': nextflow's default 'symlink' staging breaks
//    in DooD setups — symlinks created by the parent container point at
//    parent-container-local paths (e.g., /opt/nextflow/assets/...) which
//    don't exist in the sibling's namespace. Copy-mode physically
//    materialises input files into the work-dir, which IS bind-mounted
//    to the sibling. Closes the smoke-v14 gap
//    (FILTER_VARIANTS couldn't open high-LD-regions-hg38-GRCh38.txt
//     because the symlink dereferenced to /opt/nextflow/... inside the
//     parent — invisible to the plink2 sibling).
//
// 3. scratch = false: nextflow's default ``scratch = true`` makes each
//    task create a ``$NXF_SCRATCH`` dir under ``$TMPDIR`` and ``cd`` into
//    it BEFORE the beforeScript fires. So our (1) ``TMPDIR=${PWD}``
//    redirect locks in too late — ``$NXF_SCRATCH`` is already under
//    ``/tmp`` (the toolkit container's writable layer, NOT bind-mounted).
//    Files staged into ``$NXF_SCRATCH`` are invisible to DooD-spawned
//    sibling containers, which identity-mount ``$NXF_TASK_WORKDIR``
//    against the host. ``scratch = false`` makes tasks run directly in
//    their bind-mounted hash dir, so identity-mount semantics hold.
//    Closes the smoke-v22c gap (INTERSECT_THINNED failed reading staged
//    inputs that ``nxf_stage`` had copied into ``/tmp/<random>``; the
//    plink2 sibling saw an empty mount and reported "No such file or
//    directory").
//
// 4. errorStrategy + maxRetries: bounded retry for known-transient
//    pgsc_calc task failures. v22d (2026-05-21) surfaced a
//    ``KeyError: 'CHR:POS:A0:A1'`` in ``pgscatalog-intersect`` that was
//    transient — v22e's INTERSECT_VARIANTS task ran cleanly with the
//    same code + input. Empirically the per-task transient rate is
//    <10%; 2 retries gets ~99.9% success on a healthy DAG. Without
//    this, a single transient task abort terminates the whole pipeline
//    + a 30-90 min smoke. Per prs-smoke-resilience Phase 3.
process {
    beforeScript = 'export TMPDIR="${PWD}"'
    stageInMode = 'copy'
    scratch = false
    errorStrategy = 'retry'
    maxRetries = 2
}
"""


def _write_pgsc_calc_nextflow_config(work_dir: SiblingMountablePath) -> Path:
    """Materialise the deployment-specific ``nextflow.config`` at ``work_dir/nextflow.config``.

    Picked up by nextflow via the ``-c`` flag in
    :func:`_build_pgsc_calc_argv`. The config sets ``process.beforeScript``
    to export ``TMPDIR=${PWD}`` inside every sibling task, redirecting
    Python's tempfile module from the VM-resident container writable
    layer (typically 98 GB) onto the bind-mounted external scratch drive
    (typically multi-TB).

    The work-dir mkdir is idempotent; the file is overwritten on each
    compute_pgs call so deployment changes pick up without manual cleanup.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    # mypy can't narrow ``SiblingMountablePath / str`` through the dynamic
    # ``type(Path())`` base; the result IS a Path at runtime — cast to make
    # the return-type contract explicit.
    config_path = Path(work_dir / _NEXTFLOW_CONFIG_FILENAME)
    config_path.write_text(_TMPDIR_REDIRECT_CONFIG)
    return config_path


def _resolve_min_overlap(conventions: PgscCalcConventions | None = None) -> float:
    """Resolve the ``--min_overlap`` value for pgsc_calc invocation.

    Precedence:

    1. Env var ``GENOMECLAW_PGSC_CALC_MIN_OVERLAP`` (parsed as float).
    2. ``PgscCalcConventions.min_overlap_default_for_non_imputed_wgs``
       (0.5 for the non-imputed single-sample WGS input class).

    Both the wrapper's argv emission and the CLI's ``params_json``
    persistence call this helper, so the value passed to pgsc_calc and
    the value persisted to ``pgs_scores`` are guaranteed to match
    (INV-R001 rebuildability).

    Pre-flight gate: unparseable or out-of-range values raise
    ``ValueError`` BEFORE pgsc_calc spawns. pgsc_calc would reject the
    same input downstream, but as a deep Nextflow rc=1 — the typed
    error surface beats hours of debugging.

    Args:
        conventions: optional :class:`PgscCalcConventions` instance.
            Defaults to ``PgscCalcConventions()`` (canonical defaults).
            Tests use ``dataclasses.replace`` to stub the default value;
            the env var still wins over the stub if set.

    Returns:
        The resolved ``--min_overlap`` value as a float in ``[0.0, 1.0]``.

    Raises:
        ValueError: when the env-var value is not a valid float OR is
            outside the ``[0.0, 1.0]`` range that pgsc_calc accepts.
    """
    conv = conventions or PgscCalcConventions()
    raw = os.environ.get("GENOMECLAW_PGSC_CALC_MIN_OVERLAP")
    if raw is None:
        return conv.min_overlap_default_for_non_imputed_wgs
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"GENOMECLAW_PGSC_CALC_MIN_OVERLAP={raw!r} is not a valid float; "
            "must be a number in [0.0, 1.0] per pgsc_calc --min_overlap "
            "contract."
        ) from exc
    if not (0.0 <= value <= 1.0):
        raise ValueError(
            f"GENOMECLAW_PGSC_CALC_MIN_OVERLAP={raw!r} = {value} is outside "
            "[0.0, 1.0]; pgsc_calc would reject this with a deep Nextflow "
            "rc=1. Set to a proportion (e.g. 0.5 for non-imputed single-"
            "sample WGS; 0.75 for cohort-imputed inputs)."
        )
    return value


def _build_pgsc_calc_argv(
    *,
    samplesheet: SiblingMountablePath,
    pgs_id: str,
    work_dir: SiblingMountablePath,
    reference_root: SiblingMountablePath,
    nextflow_config: Path | None = None,
    conventions: PgscCalcConventions | None = None,
) -> list[str]:
    """Build the `nextflow run pgscatalog/pgsc_calc` invocation argv.

    All flag strings come from :class:`PgscCalcConventions` — the dataclass
    is the typed contract against pgsc_calc v2.2.0. The wrapper reads
    ``conv.input_flag`` rather than hardcoding ``"--input"`` so a future
    pgsc_calc pin bump that flips the flag produces a typed-test failure
    (in :mod:`tests.unit.test_pgsc_calc_conventions`) rather than a silent
    ``rc=1`` against the real tool.

    Composition:

    * ``-r <version>`` from ``conv.revision_flag`` + ``PRS_RUNTIME_VERSIONS``
    * ``-profile docker`` from ``conv.profile_flag`` — the 2026-05-17 smoke
      proved ``-profile conda`` fails on linux/arm64 (pgsc_calc pins
      plink2 2.0a5.10, not packaged for aarch64).
    * ``--input <samplesheet>`` from ``conv.input_flag`` — pgsc_calc v2.2.0
      retired the pre-2.2 ``--target <vcf>`` shorthand (smoke v2 regression).
    * ``--target_build GRCh38`` from ``conv.target_build_flag``.
    * ``--pgs_id <id>`` from ``conv.pgs_id_flag``.
    * ``--run_ancestry <dir>`` from ``conv.run_ancestry_flag`` — INV-C001
      v1.7 mandatory for ancestry-calibrated PRS.
    * ``-work-dir <dir>`` from ``conv.work_dir_flag``.
    """
    from genomeclaw_toolkit.prep._versions import PRS_RUNTIME_VERSIONS

    conv = conventions or PgscCalcConventions()
    # Resource caps for the hardware ceiling. pgsc_calc defaults to
    # max_memory=128.GB / max_cpus=16; on a typical colima VM (12 GiB / 2 CPU
    # by default), individual processes' static memory requests (e.g.,
    # ANCESTRY_PROJECT:EXTRACT_DATABASE at 16 GB) exceed available causing
    # nextflow to refuse submission with "Default resources exceed
    # availability". The caps below shrink every request to the engine's
    # actual capacity. Read from env vars so deployments with bigger VMs
    # don't pay the cap; default to conservative values that fit a 12 GiB
    # macOS host's VZ.framework ceiling.
    import os as _os
    max_memory = _os.environ.get("GENOMECLAW_PGSC_CALC_MAX_MEMORY", "10.GB")
    max_cpus = _os.environ.get("GENOMECLAW_PGSC_CALC_MAX_CPUS", "2")
    argv = [
        "nextflow",
        "run",
        "pgscatalog/pgsc_calc",
        conv.revision_flag,
        PRS_RUNTIME_VERSIONS["pgsc_calc"],
        conv.profile_flag,
        "docker",
    ]
    # Optional deployment config (TMPDIR redirect; see
    # :func:`_write_pgsc_calc_nextflow_config`). nextflow's ``-c`` flag is
    # additive — it merges with the upstream pgsc_calc config rather than
    # replacing it. Inserted BEFORE pgsc_calc params so the params block
    # stays grouped.
    if nextflow_config is not None:
        argv += ["-c", str(nextflow_config)]
    # --min_overlap value: env var > conventions default (0.5 for non-imputed
    # single-sample WGS per docs/reports/prs-real-data-smoke-research-findings.md).
    # The same helper feeds the CLI's params_json persistence so the value
    # threaded into pgsc_calc and the value persisted to pgs_scores match.
    min_overlap = _resolve_min_overlap(conv)
    argv += [
        conv.input_flag,
        str(samplesheet),
        conv.target_build_flag,
        "GRCh38",
        conv.pgs_id_flag,
        pgs_id,
        "--max_memory",
        max_memory,
        "--max_cpus",
        max_cpus,
        "--min_overlap",
        str(min_overlap),
        conv.run_ancestry_flag,
        str(_ancestry_reference_bundle(reference_root)),
        # ``-resume`` enables Nextflow's task-output cache: on a re-invocation
        # against the same ``-work-dir``, tasks with valid ``.exitcode`` + cached
        # outputs are skipped + only post-failure tasks rerun. Safe to enable
        # unconditionally — on a fresh work_dir it's a no-op. Critical for the
        # prs-smoke-resilience Phase 4 recovery loop: when a mid-run drive
        # disconnect forces a Colima restart, the smoke driver re-invokes
        # pgsc_calc + the cached work_dir state means only the post-disconnect
        # tasks rerun (recovery overhead ~2-5 min per cycle vs. 25-90 min if
        # we started from scratch).
        "-resume",
        conv.work_dir_flag,
        str(work_dir),
    ]
    return argv


def _open_tsv(path: Path) -> "object":
    """Open ``path`` as text — transparently gunzip if it ends in ``.gz``."""
    import gzip

    if path.suffix == ".gz":
        return gzip.open(path, "rt")
    return path.open()


def _pgs_id_matches(row_pgs: str, pgs_id: str) -> bool:
    """pgsc_calc v2.2.0 writes the ``PGS`` column with the scorefile-build
    suffix (e.g. ``PGS000018_hmPOS_GRCh38``); the wrapper's pgs_id input is
    the bare accession. Match by prefix-up-to-underscore so both forms work.
    """
    if row_pgs == pgs_id:
        return True
    return row_pgs.split("_", 1)[0] == pgs_id


def _find_pgsc_calc_output(
    work_dir: Path, *, legacy_subdir: str, legacy_name: str, modern_name_gz: str
) -> Path | None:
    """Locate a pgsc_calc output file under ``work_dir``.

    Two layouts coexist:

    - **Legacy "publish-dir"** (``<work_dir>/<legacy_subdir>/<legacy_name>``):
      the idealised shape the wrapper was originally written against;
      retained for fixture tests that synthesise this layout.
    - **Modern per-task hash dirs** (``<work_dir>/<2-char>/<long-hash>/<modern_name_gz>``):
      what pgsc_calc v2.2.0 actually emits when run via Nextflow's default
      work-dir convention — no publish-dir, files stay inside the per-task
      directory; smoke v23 (2026-05-22) is the canonical reference.

    Returns the first match found (legacy first; falls back to recursive
    ``rglob`` for the modern name). ``None`` if neither exists.
    """
    legacy = work_dir / legacy_subdir / legacy_name
    if legacy.exists():
        return legacy
    matches = sorted(work_dir.rglob(modern_name_gz))
    if matches:
        return matches[0]
    return None


def _parse_aggregated_scores(work_dir: Path, pgs_id: str) -> tuple[float | None, str]:
    """Parse pgsc_calc's score-aggregation TSV. Returns ``(raw_score, study_pop)``.

    Output schema: ``sampleset\\tIID\\tPGS\\tSUM\\tDENOM\\tAVG`` (legacy) or
    ``sampleset\\tFID\\tIID\\tPGS\\tSUM\\tDENOM\\tAVG`` (v2.2.0). The ``AVG``
    column is the raw score the wrapper returns; the v0 wrapper hard-codes
    ``"PGS Catalog scoring weights"`` as the study-population string.

    File location: legacy ``<work_dir>/score/aggregated_scores.txt`` OR modern
    ``<work_dir>/<2-char>/<long-hash>/aggregated_scores.txt.gz`` (per
    :func:`_find_pgsc_calc_output`).
    """
    score_path = _find_pgsc_calc_output(
        work_dir,
        legacy_subdir="score",
        legacy_name="aggregated_scores.txt",
        modern_name_gz="aggregated_scores.txt.gz",
    )
    if score_path is None:
        return (None, "PGS Catalog scoring weights")
    raw_score: float | None = None
    with _open_tsv(score_path) as fh:  # type: ignore[union-attr]
        header = fh.readline().rstrip("\n").split("\t")  # type: ignore[union-attr]
        for line in fh:  # type: ignore[union-attr]
            cells = line.rstrip("\n").split("\t")
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells, strict=True))
            if not _pgs_id_matches(row.get("PGS", ""), pgs_id):
                continue
            try:
                raw_score = float(row.get("AVG", ""))
            except ValueError:
                raw_score = None
            break
    return (raw_score, "PGS Catalog scoring weights")


def _parse_aggregated_scores_norm(work_dir: Path, pgs_id: str) -> tuple[float | None, str | None]:
    """Parse pgsc_calc's continuous-ancestry-calibrated TSV. Returns ``(percentile, warning)``.

    pgsc_calc v2.2.0 emits ``norm_pgs.txt.gz`` with columns
    ``sampleset\\tFID\\tIID\\tPGS\\tSUM\\tZ_MostSimilarPop\\tZ_norm1\\tZ_norm2\\tpercentile_MostSimilarPop``.
    There's no longer a ``calibration_warning`` column in this file; the
    warning (if any) lives in ``log_scorefiles.json`` / ``pop_summary.csv``.
    The legacy ``aggregated_scores_norm.txt`` (with ``calibration_warning``)
    is still supported for fixture tests.

    File location: legacy ``<work_dir>/ancestry/aggregated_scores_norm.txt`` OR
    modern ``<work_dir>/<2-char>/<long-hash>/norm_pgs.txt.gz``.
    """
    norm_path = _find_pgsc_calc_output(
        work_dir,
        legacy_subdir="ancestry",
        legacy_name="aggregated_scores_norm.txt",
        modern_name_gz="norm_pgs.txt.gz",
    )
    if norm_path is None:
        return (None, None)
    percentile: float | None = None
    warning: str | None = None
    with _open_tsv(norm_path) as fh:  # type: ignore[union-attr]
        header = fh.readline().rstrip("\n").split("\t")  # type: ignore[union-attr]
        for line in fh:  # type: ignore[union-attr]
            cells = line.rstrip("\n").split("\t")
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells, strict=True))
            if not _pgs_id_matches(row.get("PGS", ""), pgs_id):
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
    vcf: SiblingMountablePath,
    pgs_id: str,
    reference_root: SiblingMountablePath,
    work_dir: SiblingMountablePath,
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
    # INV-D006 boundary check: every path that may flow into a DooD sibling
    # (pgsc_calc spawns siblings via nextflow + docker) gets validated here.
    # Passing a container-local path (e.g., `/tmp/genomeclaw-scratch/...`)
    # raises DooDPathError BEFORE any subprocess runs.
    vcf = as_sibling_mountable(vcf)
    work_dir = as_sibling_mountable(work_dir)
    reference_root = as_sibling_mountable(reference_root)

    _check_ancestry_reference(reference_root)
    work_dir.mkdir(parents=True, exist_ok=True)

    # pgsc_calc v2.2.0 requires --input <samplesheet.csv>; materialise one
    # from the single-VCF caller contract. The samplesheet lives in
    # work_dir so it's discoverable for INV-R001 audit + co-resides with
    # the Nextflow intermediates pgsc_calc generates.
    # Sampleset identifier MUST NOT contain `.` — pgsc_calc derives downstream
    # filenames as ``GRCh38_<sampleset>_<chrom>.<ext>``, and the intersect_cli
    # step parses those back by stripping a single ``_<chrom>`` suffix.
    # ``Path("merged.vcf.gz").stem == "merged.vcf"`` keeps the dot; pgsc_calc
    # then mismatches the derived filename. Strip all VCF-related suffixes
    # for a periodless sampleset. Phase 7 smoke v13 (2026-05-19) regression.
    sample_id = vcf.name.removesuffix(".gz").removesuffix(".vcf")
    samplesheet = _write_pgsc_calc_samplesheet(vcf=vcf, sample_id=sample_id, work_dir=work_dir)
    # Deployment config: redirect sibling-task TMPDIR to the external
    # scratch drive (see _write_pgsc_calc_nextflow_config). Without this,
    # pgsc_calc's INTERSECT_VARIANTS fills the colima VM data disk.
    nextflow_config = _write_pgsc_calc_nextflow_config(work_dir)
    argv = _build_pgsc_calc_argv(
        samplesheet=as_sibling_mountable(samplesheet),
        pgs_id=pgs_id,
        work_dir=work_dir,
        reference_root=reference_root,
        nextflow_config=nextflow_config,
    )
    # Pre-set TMPDIR for the nextflow child process. Nextflow's per-task
    # ``.command.run`` script creates ``NXF_SCRATCH="$(nxf_mktemp $TMPDIR)"``
    # at script-build time — BEFORE the ``process.beforeScript`` directive
    # fires. So our (``nextflow.config``) ``beforeScript`` TMPDIR redirect
    # is too late; we have to bake TMPDIR into the parent process env so
    # NXF_SCRATCH lands in a bind-mounted location from the start.
    #
    # Smoke v22c regression (2026-05-21): without this, NXF_SCRATCH lives
    # at ``/tmp/<random>`` inside the toolkit container's writable layer,
    # invisible to DooD-spawned sibling containers that identity-mount
    # ``$NXF_TASK_WORKDIR`` against the host. INTERSECT_THINNED then
    # crashed reading staged inputs that nxf_stage had "copied" into the
    # non-bind-mounted scratch dir.
    #
    # Smoke v22f regression (2026-05-21): even with ``process.scratch =
    # false`` in our nextflow.config, Nextflow's process template still
    # emits the ``NXF_SCRATCH=$(nxf_mktemp $TMPDIR)`` boilerplate — the
    # directive isn't honored by the template generator we're seeing. The
    # env-var-at-parent approach short-circuits the issue independent of
    # how Nextflow handles the directive.
    env = os.environ.copy()
    env["TMPDIR"] = str(work_dir)
    proc = subprocess.run(argv, capture_output=True, check=False, env=env)
    if proc.returncode != 0:
        # Surface BOTH stdout + stderr. Nextflow's update banner is the only
        # thing on stderr most of the time; the actual DAG-abort error lives
        # in stdout (process termination messages, work-dir hints, "use
        # -resume" tip). v22 ledger's "pgsc_calc failed (rc=1): Nextflow
        # 26.04.1 is available" message was actively misleading because the
        # real error was burried in work_dir/<hash>/.command.err. Per
        # prs-smoke-resilience Phase 2.
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        stdout_text = proc.stdout.decode("utf-8", errors="replace").strip()
        # Tail stdout to last 50 lines so the message stays readable even when
        # Nextflow streamed a long DAG progress log; the failure marker is
        # typically the last few non-empty lines.
        stdout_tail = "\n".join(stdout_text.splitlines()[-50:])
        raise RuntimeError(
            f"pgsc_calc failed (rc={proc.returncode}):\n"
            f"--- stderr ---\n{stderr_text}\n"
            f"--- stdout (last 50 lines) ---\n{stdout_tail}"
        )

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


def stamp_pgs_row(
    run_dir: "Path",
    row: PgsRow,
    *,
    vcf: "Path",
    min_overlap_used: float | None = None,
    keep_ambiguous_used: bool | None = None,
) -> None:
    """INSERT the ``PgsRow`` into ``pgs_scores`` + matching ``findings`` row.

    Stamped with the 7 INV-R001 provenance columns. ``tool`` is ``pgsc_calc``;
    ``tool_version`` is ``agent-driven`` (the precise pgsc_calc version is
    captured in the run's manifest by Nextflow). ``source_path`` is the
    VCF; ``source_sha256`` is empty for callers that don't re-hash the VCF
    (the ingest manifest carries the canonical hash for the real-data
    smoke).

    ``min_overlap_used`` + ``keep_ambiguous_used`` land in ``params_json``
    so a future debugger reading the stored row alone can tell what
    threshold pgsc_calc ran against.

    Phase 4 of agent-prs-compute-fix relocated this from
    ``_cli/commands/pipeline.py`` to remove the service→CLI dependency:
    both the CLI's ``pipeline pgs-compute`` subcommand AND the worker's
    ``_real_compute_fn`` call here.
    """
    import json as _json
    from datetime import UTC, datetime
    from uuid import uuid4

    import duckdb

    from genomeclaw_toolkit.prep.store import create_store
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    store_path = run_dir / "variants.duckdb"
    # Bootstrap an empty store if one doesn't exist yet — lets the worker
    # (or `prs-compute`) land its row in a fresh smoke dir without a
    # preceding `host setup`/init step.
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


__all__ = [
    "PgsReferenceMissingError",
    "PgsRow",
    "apply_calibration_decision",
    "compute_pgs",
    "stamp_pgs_row",
]

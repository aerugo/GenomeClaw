"""pgsc_calc v2.2.0 argv + samplesheet + filename conventions.

This dataclass is the typed contract between GenomeClaw's wrappers and
``pgscatalog/pgsc_calc``. Every field captures one convention that the
wrapper would otherwise hard-code; tests assert the wrapper consumes the
dataclass rather than literal strings, so a future pgsc_calc bump that
changes the contract produces a typed test failure (not a silent rc=1
in a real-tool smoke).

Verified against ``pgsc_calc v2.2.0`` via two sources:

1. Upstream documentation — https://pgsc-calc.readthedocs.io/ and the
   pgsc_calc GitHub README at https://github.com/PGScatalog/pgsc_calc.
2. Empirical probe — :mod:`tools.pgsc_calc.probe.sh` recorded against
   the toolkit image's bundled pgsc_calc at
   ``tools/pgsc_calc/probe-output.txt``.

When ``_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`` changes, the protocol
is: (1) re-run ``probe.sh``, (2) diff the output against the recorded
baseline, (3) for each diff, update the corresponding dataclass field
AND update ``verified_against_version`` to the new pin. The unit test
``test_pgsc_calc_conventions_verified_against_version_matches_pin``
fails if step (3)'s version bump is skipped.

This is the canonical implementation of ``INV-T001`` (External-Tool
Conventions Captured as Typed Wrappers). The class-level docstring +
per-field comments are the audit surface; the dataclass itself is the
machine-checked contract.

See [docs/plans/active/path-crossing-discipline/](../../../../docs/plans/active/path-crossing-discipline/)
for the plan that introduced this discipline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PgscCalcConventions:
    """pgsc_calc invocation + samplesheet conventions, pinned to one version.

    Constructed with defaults that mirror pgsc_calc v2.2.0; tests can
    construct stubbed instances via :func:`dataclasses.replace` to verify
    that wrappers consume the fields rather than literal strings.
    """

    # =========================================================================
    # Version pin
    # =========================================================================
    verified_against_version: str = "v2.2.0"
    """The pgsc_calc release tag this convention set was verified against.

    Must match ``_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`` at test time;
    diverging means the conventions are out-of-date relative to the pin.
    """

    # =========================================================================
    # Argv flags — main pipeline invocation
    # =========================================================================
    input_flag: str = "--input"
    """Flag for the samplesheet CSV. Smoke v2 regression (2026-05-18): the
    pre-v2.2 ``--target <vcf>`` shorthand was retired; v2.2.0 requires
    ``--input <samplesheet.csv>``. The wrapper MUST emit ``--input``."""

    input_value_pattern: str = r".*\.csv$"
    """Regex the ``--input`` flag's VALUE must match. Captures the value-
    type semantic (per `prs-runtime-hardening` plan Slice 1.C): the flag
    accepts a CSV samplesheet, not e.g. a VCF or directory. A unit test
    asserts the wrapper's emitted argv matches this pattern; a regression
    to passing the VCF directly here would surface at unit-test time."""

    target_build_flag: str = "--target_build"
    """Flag for the reference build pgsc_calc should expect from the input.
    Per pgsc_calc README §"Required parameters"."""

    pgs_id_flag: str = "--pgs_id"
    """Flag for the PGS Catalog ID to compute. Single-PGS mode."""

    run_ancestry_flag: str = "--run_ancestry"
    """Flag pointing at the PGS Catalog ancestry-reference bundle. Mandatory
    under INV-C001 v1.7 for ancestry-calibrated PRS."""

    run_ancestry_value_pattern: str = r".*\.tar\.zst$"
    """Regex the ``--run_ancestry`` flag's VALUE must match. The
    pgsc_calc internal ``EXTRACT_DATABASE`` task does ``tar -xf <value>``
    against this — it expects a TARBALL, not an extracted directory.
    Phase 7 smoke v10 surfaced this as ``EXTRACT_DATABASE exit 2`` after
    the wrapper pointed the value at the extracted dir; the fix
    (``_ancestry_reference_bundle()`` returns the ``.tar.zst`` path) is
    pinned here so a regression surfaces at unit-test time, not at
    smoke-time. INV-T001 tightening per the prs-runtime-hardening plan."""

    profile_flag: str = "-profile"
    """Nextflow profile selector. Phase 4a of the prs-input-coverage-fill
    plan settled on ``docker``; the 2026-05-17 smoke proved ``conda``
    fails on linux/arm64 (plink2 2.0a5.10 not packaged for aarch64)."""

    revision_flag: str = "-r"
    """Nextflow pipeline revision (== the pgsc_calc release tag)."""

    work_dir_flag: str = "-work-dir"
    """Nextflow work directory. The smoke driver mounts this at an
    identical-path overlay so sibling containers can resolve sub-paths."""

    # =========================================================================
    # Input-class defaults — non-imputed single-sample WGS
    # =========================================================================
    min_overlap_default_for_non_imputed_wgs: float = 0.5
    """Default value for ``--min_overlap`` on the non-imputed single-sample
    WGS input class (GenomeClaw's canonical input today: a variant-sites-
    only VCF like Nebula's Haplotype Caller output).

    pgsc_calc's upstream default is ``0.75``, calibrated by Lambert et al.
    2024 (*Nature Genetics*) on cohort-imputed data. The 45-65% empirical
    match-rate ceiling for non-imputed single-sample WGS against dense
    imputed scoring files (e.g. snpnet/LASSO models like PGS001229) makes
    0.75 a structural rejection of healthy artifacts — see
    :doc:`docs/reports/prs-real-data-smoke-research-findings.md` for the
    external research validation. 0.5 is the input-class-appropriate
    default; comparable tools (PRSice-2, LDpred2, PLINK2 ``--score``) are
    permissive on low-overlap inputs by default.

    The env var ``GENOMECLAW_PGSC_CALC_MIN_OVERLAP`` overrides this for
    ad-hoc tuning (e.g., a future imputation-using ingest path that wants
    pgsc_calc's upstream 0.75). Resolution goes through
    :func:`genomeclaw_toolkit.prep.pgs._resolve_min_overlap` so the value
    threaded into pgsc_calc argv matches the value persisted to
    ``pgs_scores.params_json`` per INV-R001.
    """

    # =========================================================================
    # Samplesheet schema
    # =========================================================================
    samplesheet_columns: tuple[str, ...] = (
        "sampleset",
        "path_prefix",
        "chrom",
        "format",
        "vcf_genotype_field",
    )
    """The CSV header row for ``--input``. Order matters; pgsc_calc parses
    by position when columns are missing or reordered upstream. Per
    pgsc_calc README §"Input samplesheet". Verified against
    ``tools/pgsc_calc/probe-output.txt``."""

    path_prefix_strips_extension: bool = True
    """Smoke v6 regression (2026-05-19): the ``path_prefix`` column is a
    file PREFIX, not a full filename. pgsc_calc auto-appends ``.vcf`` for
    format=vcf and detects ``.gz`` compression separately. So a file
    ``merged.vcf.gz`` is referenced as ``path_prefix=merged`` (no extension).

    The 2026-05-19 smoke failed with ``No such file: merged.vcf.gz.vcf``
    because the prefix carried the suffix. The wrapper now strips it iff
    this flag is True."""

    vcf_genotype_field_default: str = "GT"
    """Default value for the ``vcf_genotype_field`` column. pgsc_calc
    supports ``GT`` (hard call) or ``DS`` (dosage); we use GT throughout."""

    # =========================================================================
    # PGS Catalog accession naming
    # =========================================================================
    accession_format: str = "{pgs_id}_hmPOS_GRCh38"
    """The harmonised-scoring accession string pgsc_calc uses internally.

    Phase 3b3a of ``prs-input-coverage-fill`` (the match-rate parser)
    queries pgsc_calc's per-variant log CSV by this accession; if the
    naming convention changes upstream, the parser breaks silently. Per
    PGS Catalog hmPOS_GRCh38 convention."""

    # =========================================================================
    # Output file paths (under -work-dir)
    # =========================================================================
    aggregated_scores_relpath: str = "score/aggregated_scores.txt.gz"
    """Where pgsc_calc writes the aggregated scores under the work-dir.
    The wrapper's ``_parse_aggregated_scores`` reads this path."""

    match_log_filename_template: str = "{sampleset}_log.csv.gz"
    """Filename pattern for the per-variant match log. Located somewhere
    under the work-dir's Nextflow hash hierarchy; the parser globs for
    this filename pattern."""


__all__ = ["PgscCalcConventions"]

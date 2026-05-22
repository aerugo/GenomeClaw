"""PharmCAT v3.2.0 argv + outside-call TSV + output JSON conventions.

This dataclass is the typed contract between GenomeClaw's wrapper and
PharmCAT (github.com/PharmGKB/PharmCAT). Every field captures one
convention that the wrapper would otherwise hard-code; tests assert the
wrapper consumes the dataclass rather than literal strings, so a future
pin bump that flips a flag produces a typed test failure (not a silent
rc=1 against the real tool).

Verified against PharmCAT v3.2.0 via:

1. Empirical probe inside ``genomeclaw/toolkit:slice-d-prime`` —
   ``pharmcat_vcf_preprocessor --help`` + ``java -jar pharmcat.jar --help``
   (the actual flag set at runtime).
2. Upstream docs at
   github.com/PharmGKB/PharmCAT/blob/v3.2.0/docs/using/Outside-Call-Format.md
   (the outside-call TSV column contract).

When ``_versions.PGX_RUNTIME_VERSIONS["pharmcat"]`` changes, the
protocol is: (1) re-run the probe, (2) diff against the recorded
baseline, (3) update the corresponding dataclass field AND bump
``verified_against_version``. The unit test
``test_pharmcat_conventions_verified_against_version_matches_pin``
fails if step (3) is skipped.

Third entry in the INV-T001 strict-tools roster alongside
:class:`PgscCalcConventions` and :class:`CyriusConventions`.

**Two-subprocess architecture (verified empirically 2026-05-22):**
PharmCAT v3 ships ``pharmcat_pipeline`` (a Python wrapper that runs
preprocessor + JAR) but does NOT expose the ``-po``/outside-call flag.
For CYP2D6-via-Cyrius outside-call workflows the canonical pattern is:

1. ``pharmcat_vcf_preprocessor -vcf <input> -o <dir>`` →
   ``<base>.preprocessed.vcf.bgz``
2. ``pharmcat -vcf <preprocessed.vcf.bgz> -po <outside_calls.tsv> -o <dir>
   -reporterJson`` → ``<base>.report.json``

The conventions dataclass captures BOTH entrypoints + their flags.

Slice plan: [phases/phase-6-slice-d-prime.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d-prime.md)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PharmCATConventions:
    """PharmCAT v3.2.0 invocation + outside-call TSV + output conventions.

    Constructed with defaults that mirror PharmCAT v3.2.0; tests stub
    via :func:`dataclasses.replace` to verify the wrapper consumes the
    fields rather than literal strings.
    """

    verified_against_version: str = "3.2.0"
    """The PharmCAT release tag this convention set was verified against.

    Must match ``_versions.PGX_RUNTIME_VERSIONS["pharmcat"]`` at test time.
    """

    # ---- Preprocessor (pharmcat_vcf_preprocessor) ----

    preprocessor_entrypoint: str = "pharmcat_vcf_preprocessor"
    """The Python preprocessor's CLI entrypoint. Resolves on PATH via
    ``/opt/pharmcat`` inside the toolkit image."""

    preprocessor_vcf_flag: str = "-vcf"
    """Flag for the input VCF (preprocessor). Verified empirically against
    v3.2.0 — supports both ``-vcf`` and ``--vcf`` (argparse short+long)."""

    preprocessor_output_dir_flag: str = "-o"
    """Flag for the preprocessor's output directory. Supports both ``-o``
    and ``--output-dir`` in v3.2.0."""

    preprocessor_output_filename_template: str = "{base}.preprocessed.vcf.bgz"
    """Filename pattern of the preprocessor's output VCF. ``{base}`` is
    the input VCF's basename stem (without extensions). The wrapper
    globs ``*.preprocessed.vcf.bgz`` rather than recompute the prefix
    since the preprocessor's exact stem-derivation can change between
    minor versions."""

    preprocessor_reference_fasta_flag: str = "-refFna"
    """Flag for the GRCh38 reference fasta. Empirical 2026-05-22: without
    this flag the preprocessor attempts to download the reference from
    Zenodo + write it into ``/opt/pharmcat/`` (read-only). Threading our
    existing reference via this flag avoids both the egress + the
    permission error. Long form: ``--reference-genome``."""

    # ---- Main PharmCAT JAR (invoked via the `pharmcat` bash wrapper) ----

    entrypoint: str = "pharmcat"
    """The PharmCAT JAR's bash wrapper. Runs ``java -jar
    /opt/pharmcat/pharmcat.jar "$@"``. Resolves on PATH via
    ``/opt/pharmcat`` inside the toolkit image."""

    vcf_flag: str = "-vcf"
    """Flag for the (preprocessed) input VCF to the JAR."""

    outside_call_flag: str = "-po"
    """Flag for the outside-call TSV. Long form is
    ``--phenotyper-outside-call-file``. v3.2.0 verified empirically."""

    output_dir_flag: str = "-o"
    """Flag for the JAR's output directory."""

    reporter_json_flag: str = "-reporterJson"
    """Flag that makes the JAR emit a ``<base>.report.json`` alongside
    its default HTML reporter output. The wrapper parses this JSON."""

    # ---- Output layout ----

    output_dir_relpath: str = "pharmcat"
    """The subdirectory inside the run-dir where PharmCAT writes its
    output. The wrapper allocates ``run_dir / output_dir_relpath``."""

    preprocessor_output_dir_relpath: str = "pharmcat_preprocessed"
    """Subdirectory inside the run-dir where the preprocessor writes
    its output. Separate from PharmCAT's report dir so the two stages
    don't co-mingle artifacts."""

    outside_call_tsv_filename: str = "pharmcat_outside_calls.tsv"
    """Filename the wrapper writes the outside-call TSV under, inside
    the run-dir."""

    outside_call_tsv_columns: tuple[str, ...] = ("gene", "diplotype")
    """Outside-call TSV column order. Per
    docs/using/Outside-Call-Format.md (v3.2.0): tab-separated, no header,
    columns are (gene, diplotype, phenotype, activity_score) with the
    last two optional. v0 emits the minimal (gene, diplotype) form for
    CYP2D6 — PharmCAT derives phenotype + activity score from its lookup
    tables."""

    report_filename_template: str = "{prefix}.report.json"
    """Filename pattern for the recommendations report PharmCAT emits
    under ``output_dir_relpath``. The wrapper globs ``*.report.json``."""


__all__ = ["PharmCATConventions"]

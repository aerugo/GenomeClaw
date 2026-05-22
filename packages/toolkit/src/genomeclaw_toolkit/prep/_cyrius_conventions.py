"""Cyrius v1.1.1 argv + output JSON conventions.

This dataclass is the typed contract between GenomeClaw's wrapper and
Illumina's Cyrius CYP2D6 star-allele caller (github.com/Illumina/Cyrius).
Every field captures one convention that the wrapper would otherwise
hard-code; tests assert the wrapper consumes the dataclass rather than
literal strings, so a future pin bump that flips a flag produces a typed
test failure (not a silent rc=1 against the real tool).

Verified against Cyrius v1.1.1 via the upstream README at
https://github.com/Illumina/Cyrius/blob/master/README.md (the
``star_caller.py`` CLI section). The empirical probe at
``tools/cyrius/probe-output.txt`` is deferred to the Slice D image
rebuild step — until then the defaults below mirror the documented
v1.1.1 contract.

When ``_versions.PGX_RUNTIME_VERSIONS["cyrius"]`` changes, the protocol
is: (1) re-run the probe, (2) diff against ``probe-output.txt``,
(3) update the corresponding dataclass field AND bump
``verified_against_version``. The unit test
``test_cyrius_conventions_verified_against_version_matches_pin``
fails if step (3) is skipped.

This is the second canonical implementation of ``INV-T001`` (External-
Tool Conventions Captured as Typed Wrappers) alongside
:class:`PgscCalcConventions`. The class-level docstring + per-field
comments are the audit surface; the dataclass itself is the machine-
checked contract.

Slice plan: [phases/phase-6-slice-d.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d.md)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CyriusConventions:
    """Cyrius v1.1.1 invocation + output-JSON conventions, pinned to one version.

    Constructed with defaults that mirror Cyrius v1.1.1; tests can stub
    via :func:`dataclasses.replace` to verify the wrapper consumes the
    fields rather than literal strings.
    """

    verified_against_version: str = "1.1.1"
    """The Cyrius release tag this convention set was verified against.

    Must match ``_versions.PGX_RUNTIME_VERSIONS["cyrius"]`` at test time;
    diverging means the conventions are out-of-date relative to the pin.
    """

    entrypoint: str = "star_caller.py"
    """Cyrius's Python CLI entrypoint. Bioconda's ``cyrius`` package
    exposes this on PATH inside the toolkit image's Stage 1 env."""

    manifest_flag: str = "--manifest"
    """Flag for the one-BAM-per-line manifest file. Cyrius expects a
    text file rather than a direct BAM path on the CLI."""

    genome_flag: str = "--genome"
    """Flag for the reference build. Accepts ``19`` (GRCh37) or
    ``38`` (GRCh38). GenomeClaw is GRCh38-only — the wrapper rejects
    other values pre-subprocess."""

    prefix_flag: str = "--prefix"
    """Flag for the output filename prefix. Cyrius writes
    ``<outDir>/<prefix>.tsv`` + ``<outDir>/<prefix>.json``."""

    output_dir_flag: str = "--outDir"
    """Flag for the output directory."""

    threads_flag: str = "--threads"
    """Flag for the worker thread count. Optional; defaults documented
    upstream."""

    reference_flag: str = "--reference"
    """Flag for the reference fasta path. **Required for CRAM input**
    (Cyrius's pysam handle needs the reference to decompress CRAM
    blocks); optional for BAM input. Surfaced as an empirical probe
    finding 2026-05-22 against the slice-d image — the project owner's
    Nebula run ships a CRAM, so without this flag the smoke would have
    failed at runtime with a pysam decode error."""

    output_filename_template: str = "{prefix}.json"
    """Filename template for the Cyrius JSON output, relative to the
    ``--outDir`` value. The TSV output uses ``{prefix}.tsv`` but we
    parse the JSON form."""

    output_genotype_key: str = "Genotype"
    """Per-sample JSON sub-dict key carrying the star-allele diplotype.
    Value is a **string** in Cyrius v1.1.1 (verified empirically 2026-05-22
    against the project owner's CRAM; the README's older shape implied a
    list, but v1.1.1 emits a plain string like ``"*1/*35"``). The wrapper's
    parser also accepts the list form for backwards-compatibility."""

    output_filter_key: str = "Filter"
    """Per-sample JSON sub-dict key carrying the filter status. Value
    is a **string** in v1.1.1 (e.g. ``"PASS"``); the wrapper's parser
    also accepts the list form."""

    genome_build_grch38: str = "38"
    """The value to pass to ``--genome`` for GRCh38 input. Bound here
    so a future Cyrius release that flips this (e.g. to ``GRCh38`` or
    ``hg38``) surfaces as a typed test failure rather than a silent
    rc=1."""


__all__ = ["CyriusConventions"]

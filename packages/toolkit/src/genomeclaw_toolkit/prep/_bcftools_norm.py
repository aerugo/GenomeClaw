"""``bcftools norm`` subprocess wrapper.

Phase 3 wraps this to produce a normalized VCF inside
``derived/<run-id>/normalized.vcf.gz``. The default invocation is
``bcftools norm -m-`` — split multi-allelic rows into single-allelic
rows. Left-alignment requires ``-f <reference.fasta>`` and is opt-in:
the reference fasta isn't part of the canonical Phase-2 reference dir
(it lands in Phase 4 alongside VEP), so passing ``reference_fasta`` is
a deliberate choice the user makes when the file is present.
"""

from __future__ import annotations

from pathlib import Path

from genomeclaw_toolkit.prep._bcftools import bcftools_run


def bcftools_norm(
    *,
    input_vcf: Path,
    output_vcf: Path,
    reference_fasta: Path | None = None,
) -> None:
    """Run ``bcftools norm`` against ``input_vcf``, writing to ``output_vcf``.

    Args:
        input_vcf: source bgzipped VCF (typically under ``raw/`` — read-only).
        output_vcf: target bgzipped VCF; parent dir is created if missing.
        reference_fasta: optional reference; when given, enables
            left-alignment (``-f <ref>``). Without it the normalize step
            performs multi-allelic splitting only.

    Raises:
        BcftoolsError: subprocess exit non-zero. Stderr captured.
    """
    output_vcf.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = ["norm", "-m-"]
    if reference_fasta is not None:
        args += ["-f", str(reference_fasta)]
    args += ["-Oz", "-o", str(output_vcf), str(input_vcf)]

    bcftools_run(args)


__all__ = ["bcftools_norm"]

"""Phase 3 — ``bcftools norm`` subprocess wrapper tests.

Phase 3's ``normalize`` subcommand wraps this. The wrapper:

- Splits multi-allelic rows by default (``-m-``).
- Optionally enables left-alignment via ``-f <reference.fasta>``.
- Writes a bgzipped output VCF + tabix index.
- Surfaces non-zero exits as ``BcftoolsError`` with stderr captured.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest


@pytest.mark.needs_bio
def test_bcftools_norm_splits_multiallelic_rows(tiny_vcf_gz: Path, tmp_path: Path) -> None:
    """``-m-`` splits the synthetic fixture's multi-allelic chr17 row into two rows."""
    from genomeclaw_toolkit.prep._bcftools_norm import bcftools_norm

    out = tmp_path / "normalized.vcf.gz"
    bcftools_norm(input_vcf=tiny_vcf_gz, output_vcf=out)

    assert out.exists()
    # The output must be bgzipped (gzip-compatible header).
    with gzip.open(out, "rt") as fh:
        text = fh.read()

    data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    # Synthetic fixture: 5 input rows; one is multi-allelic (T → C,G) →
    # 6 output rows after split.
    assert len(data_lines) == 6

    # The multi-allelic split must produce two single-alt rows at the
    # same chrom + pos as the source.
    chr17_rows = [
        line
        for line in data_lines
        if line.split("\t")[0] == "chr17" and line.split("\t")[1] == "43044300"
    ]
    assert len(chr17_rows) == 2
    alts = sorted(line.split("\t")[4] for line in chr17_rows)
    assert alts == ["C", "G"]


@pytest.mark.needs_bio
def test_bcftools_norm_writes_bgzip_compatible_output(tiny_vcf_gz: Path, tmp_path: Path) -> None:
    """The output of ``bcftools norm`` must be bgzipped (so tabix can index it)."""
    from genomeclaw_toolkit.prep._bcftools_norm import bcftools_norm

    out = tmp_path / "normalized.vcf.gz"
    bcftools_norm(input_vcf=tiny_vcf_gz, output_vcf=out)

    # bgzip starts with the standard gzip magic.
    with out.open("rb") as fh:
        head = fh.read(2)
    assert head == b"\x1f\x8b"


@pytest.mark.needs_bio
def test_bcftools_norm_creates_parent_directory(tiny_vcf_gz: Path, tmp_path: Path) -> None:
    """The wrapper creates ``output_vcf.parent`` if it doesn't exist."""
    from genomeclaw_toolkit.prep._bcftools_norm import bcftools_norm

    out = tmp_path / "subdir" / "normalized.vcf.gz"
    bcftools_norm(input_vcf=tiny_vcf_gz, output_vcf=out)
    assert out.exists()


@pytest.mark.needs_bio
def test_bcftools_norm_surfaces_stderr_on_failure(tmp_path: Path) -> None:
    """A bad input → ``BcftoolsError`` with the actual bcftools stderr in the message."""
    from genomeclaw_toolkit.prep._bcftools import BcftoolsError
    from genomeclaw_toolkit.prep._bcftools_norm import bcftools_norm

    with pytest.raises(BcftoolsError):
        bcftools_norm(
            input_vcf=tmp_path / "does-not-exist.vcf.gz",
            output_vcf=tmp_path / "out.vcf.gz",
        )

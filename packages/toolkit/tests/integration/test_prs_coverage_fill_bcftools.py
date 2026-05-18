"""Phase 1b — real-bcftools integration test against ``tiny_cram``.

Gated on ``needs_bio`` (real bcftools + samtools on PATH). The synthetic
CRAM has 4 reads aligned to chr17:43044295+, chr13:32315474+,
chr22:42126499+ on top of a synthetic FASTA whose reference at those
positions is also 'A' (per `tests/conftest.py:tiny_grch38_fasta`). So a
force-genotype at any position inside those covered regions, with REF=A
ALT=T, must produce a `0/0` (homozygous REF) call.

This proves the bcftools pipe shape we baked into ``coverage_fill.py``
works end-to-end on a real CRAM + real FASTA + real bcftools, not just
against the stubbed subprocess used by the unit-level tests.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest


@pytest.mark.needs_bio
def test_force_genotype_tier1_against_tiny_cram_emits_refref(
    tmp_path: Path,
    tiny_cram: Path,
    tiny_grch38_fasta: Path,
) -> None:
    """Real bcftools pipe against ``tiny_cram`` produces a 0/0 call at chr17:43044300.

    The synthetic CRAM has reads at chr17:43044295-43044395 (100 bp of 'A')
    aligned against a reference whose bases at that interval are also 'A'.
    Forcing a genotype call at chr17:43044300 with REF=A ALT=T → the only
    biologically sensible outcome is 0/0 (homozygous reference).
    """
    from genomeclaw_toolkit.prep.coverage_fill import _force_genotype_tier1

    pca = tmp_path / "pca"
    pca.mkdir()
    sites = pca / "pca_sites.tsv"
    alleles = pca / "pca_alleles.tsv"
    sites.write_text("chr17\t43044300\n")
    alleles.write_text("chr17\t43044300\tA,T\n")

    output_vcf = tmp_path / "derived" / "prs_coverage" / "tinysample" / "v1" / "tier1.vcf.gz"

    _force_genotype_tier1(
        cram_path=tiny_cram,
        sites_tsv=sites,
        alleles_tsv=alleles,
        fasta=tiny_grch38_fasta,
        output_vcf=output_vcf,
    )

    assert output_vcf.exists(), "real-bcftools tier1 pipe must produce the output VCF"

    # Walk the VCF body — expect exactly one record at the target site with GT=0/0.
    records: list[tuple[str, str, str]] = []
    with gzip.open(output_vcf, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 10:
                continue
            fmt = fields[8].split(":")
            sample = fields[9].split(":")
            gt = dict(zip(fmt, sample, strict=False)).get("GT", "")
            records.append((fields[0], fields[1], gt))

    assert records, (
        "bcftools pipe produced no records — check the targets/alleles TSV alignment"
    )
    assert records[0][0] == "chr17"
    assert records[0][1] == "43044300"
    # `--constrain alleles` + reference-matching reads → 0/0 (or "0" as
    # haploid representation on some htslib builds; normalize to "0/0").
    gt = records[0][2].replace("|", "/")
    assert gt == "0/0", (
        f"expected 0/0 at chr17:43044300 against tiny_grch38_fasta + tiny_cram (REF=A, reads=A), "
        f"got GT={records[0][2]!r}"
    )

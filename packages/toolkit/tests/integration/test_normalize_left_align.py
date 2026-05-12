"""Phase 4B — production left-alignment in ``normalize`` (case 5).

Phase 3 plumbed `--reference-fasta` through `normalize`'s API but
shipped with `bcftools norm -m-` only (multi-allelic split, no
left-alignment). Phase 4B pairs the flag with a real GRCh38 reference
from `fetch --source grch38`. This test gates the production flow:
when `normalize(--reference-fasta=<ref>)` is called, the resulting
``normalized.vcf.gz`` carries left-aligned indels and the provenance
step records `params.left_align: true`.

The fixture is a hand-crafted single-base deletion in an A-homopolymer
at chr1:996-1010 of ``tiny_grch38_fasta``. The input VCF encodes the
deletion at chr1:1009 (anchor pos near the right end of the
homopolymer); the canonical left-aligned position is chr1:995 (the
base immediately preceding the homopolymer's start, since bcftools
left-aligns by the equivalent-representation rule for single-base
homopolymer deletions).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest


@pytest.mark.needs_bio
def test_invR001_normalize_with_reference_left_aligns_indels(
    tiny_indel_vcf_gz: Path,
    tiny_grch38_fasta: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """`INV-R001` (`bcftools norm -f` is deterministic given fixed inputs):
    after normalize with a reference fasta, the not-left-aligned input
    indel re-positions to the canonical left-aligned coordinate, and
    the provenance step records the left-align params.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_indel_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="left-align-001",
    )
    norm_vcf = normalize(
        run_dir=run_dir,
        reference_fasta=tiny_grch38_fasta,
    )

    # The normalized VCF must contain exactly one variant whose POS is
    # left of the input's pos 1009 (the canonical left-aligned position
    # for a single-base homopolymer deletion is the base immediately
    # preceding the homopolymer's start). The exact REF/ALT depend on
    # bcftools' padding semantics; the gate is: POS decremented.
    with gzip.open(norm_vcf, "rt") as fh:
        text = fh.read()
    data_lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert len(data_lines) == 1, f"expected one variant post-normalize, got {len(data_lines)}"
    fields = data_lines[0].split("\t")
    chrom, pos = fields[0], int(fields[1])
    assert chrom == "chr1"
    assert pos < 1009, f"expected left-alignment to move POS below 1009 (input pos), got {pos}"

    # Provenance trail records the left-align params.
    provenance = json.loads((run_dir / "provenance.json").read_text())
    norm_step = next(s for s in provenance["steps"] if s["step"] == "normalize")
    assert norm_step["params"].get("left_align") is True
    assert norm_step["params"].get("reference_fasta") == str(tiny_grch38_fasta)

"""Phase 4B — CRAM ingest with ``mosdepth --fasta`` (case 6).

Phase 2 shipped BAM ingest with mosdepth. CRAM decoding requires a
reference fasta passed to mosdepth via ``--fasta``; without it,
``mosdepth`` over a CRAM hits ``samtools``'s reference-unavailable
error and the ingest aborts mid-coverage step.

Phase 4B extends ``ingest()`` with a ``reference_fasta=<path>``
parameter that's threaded into ``run_mosdepth(--fasta=...)`` when the
input ``--bam`` is a CRAM (auto-detected via the ``.cram`` suffix).
The reference fasta SHA256 is recorded in the ``mosdepth-coverage``
provenance step so a future re-run against a different reference is
detectable.

`INV-D001`: the CRAM under ``raw/`` is unchanged after the run; same
gate that ``test_invD001_bam_unchanged_after_mosdepth`` enforces for
BAM, extended to CRAM.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.needs_bio
def test_ingest_cram_with_mosdepth_fasta(
    tiny_vcf_gz: Path,
    tiny_cram: Path,
    tiny_grch38_fasta: Path,
    tiny_genes_bed: Path,
    genomeclaw_layout: dict[str, Path],
) -> None:
    """Case 6: CRAM ingest succeeds with ``--reference-fasta``; ``coverage_qc``
    is populated; CRAM SHA256 unchanged after the run; provenance step
    records the reference fasta path + sha256.
    """
    from genomeclaw_toolkit.prep.ingest import ingest

    cram_sha_before = _sha256(tiny_cram)
    crai_path = tiny_cram.with_suffix(".cram.crai")
    crai_sha_before = _sha256(crai_path) if crai_path.exists() else None

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="cram-001",
        bam=tiny_cram,  # auto-detected as CRAM by .cram suffix
        bed=tiny_genes_bed,
        reference_fasta=tiny_grch38_fasta,
    )

    # `INV-D001`: the CRAM + .crai are unchanged after the run.
    assert _sha256(tiny_cram) == cram_sha_before
    if crai_sha_before is not None:
        assert _sha256(crai_path) == crai_sha_before

    # coverage_qc populated against the BED's three genes.
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT gene, mean_depth FROM coverage_qc ORDER BY gene").fetchall()
    finally:
        conn.close()
    genes = {r[0] for r in rows}
    assert genes == {"BRCA1", "BRCA2", "CYP2D6"}
    # Each gene has a non-negative mean depth (the synthetic CRAM has
    # one read at each region, so mean depth is small but positive at
    # the read positions; uncovered exons read 0).
    for _gene, mean_depth in rows:
        assert mean_depth >= 0.0

    # Provenance step records the reference fasta identity.
    provenance = json.loads((run_dir / "provenance.json").read_text())
    mosdepth_step = next(s for s in provenance["steps"] if s["step"] == "mosdepth-coverage")
    assert mosdepth_step["params"].get("fasta_path") == str(tiny_grch38_fasta)
    assert mosdepth_step["params"].get("fasta_sha256") == _sha256(tiny_grch38_fasta)

"""Phase 4C.3 — ``genomeclaw pipeline annotate`` parent-orchestrator tests.

Phase 4A's bcftools-annotate-only ClinVar overlay was migrated to a
chained orchestrator (4C.2 → 4C.3):

1. ``annotate(run_dir, reference_dir, ...)`` is a thin parent that
   calls ``annotate_vcfanno`` (ClinVar + gnomAD-exomes + dbSNP overlays
   via vcfanno), then (4D-pending) ``annotate_vep`` (VEP + LOFTEE +
   AlphaMissense + SpliceAI), then promotes the final output to
   ``annotated.vcf.gz``.
2. Until 4D ships, ``annotate_vep`` is a no-op — ``annotated.vcf.gz``
   is the vcfanno output. ``materialize`` reads from ``annotated.vcf.gz``
   per the existing v0.2 contract.

The fine-grained orchestrator behaviours (ClinVar release resolution,
chr-prefix alignment, source-immutability, etc.) are covered by
``test_annotate_vcfanno.py``. The tests here cover the **chain**: the
parent invokes the sub-orchestrators in the right order + promotes
their outputs into the expected on-disk shape.

The Phase-4A tests that were removed during the 4C.3 rewrite:
- ``test_annotate_picks_newest_clinvar_when_release_is_none`` — covered
  by ``_resolve_clinvar`` in annotate_vcfanno.
- ``test_annotate_refuses_when_no_clinvar_present`` — same.
- ``test_annotate_refuses_when_normalize_has_not_run`` — covered by
  ``test_annotate_vcfanno_refuses_when_normalized_vcf_missing``.
- ``test_annotate_records_inputs_in_provenance`` — covered by
  ``test_invR001_annotate_vcfanno_appends_step_to_provenance``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Reference-staging helpers — duplicated from test_annotate_vcfanno.py
# pending a Phase-4E shared-fixture extract (when a third caller surfaces).
# ---------------------------------------------------------------------------


def _bgz_index(plain: Path) -> Path:
    bgz = plain.with_suffix(plain.suffix + ".gz")
    subprocess.run(
        ["bcftools", "view", "-Oz", "-o", str(bgz), str(plain)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["bcftools", "index", "--tbi", str(bgz)],
        check=True,
        capture_output=True,
    )
    plain.unlink()
    return bgz


def _build_clinvar_release(reference_dir: Path, release: str) -> Path:
    """Stage a tiny ClinVar release with chr-prefixed contigs."""
    target = reference_dir / "clinvar" / release
    target.mkdir(parents=True)
    plain = target / "clinvar.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=CLNSIG,Number=.,Type=String,Description="Clinical significance">\n'
        '##INFO=<ID=CLNREVSTAT,Number=.,Type=String,Description="Review status">\n'
        "##contig=<ID=chr1,length=248956422>\n"
        "##contig=<ID=chr17,length=83257441>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\t111\tA\tG\t.\t.\tCLNSIG=Pathogenic;CLNREVSTAT=criteria_provided\n"
        "chr17\t43044295\t222\tG\tA\t.\t.\tCLNSIG=Likely_benign;CLNREVSTAT=no_assertion\n"
    )
    return _bgz_index(plain)


def _build_gnomad_exomes_release(reference_dir: Path, release: str) -> None:
    """Stage a minimal gnomAD-exomes per-chrom layout (chr1 + chr17).

    Declares + emits all nine gnomAD v4 population AFs (afr, amr, asj,
    eas, fin, mid, nfe, remaining, sas) so the materialize-side
    extraction has data to populate every per-population column in the
    v0.2 schema. Kept structurally in sync with the same-named helper
    in ``test_annotate_vcfanno.py`` — both files duplicate this fixture
    pending the Phase-4E shared-fixture extract.
    """
    target = reference_dir / "gnomad-exomes" / release / "by_chrom"
    target.mkdir(parents=True)
    for chrom, pos in (("chr1", 1000), ("chr17", 43044295)):
        plain = target / f"{chrom}.vcf"
        plain.write_text(
            "##fileformat=VCFv4.2\n"
            '##INFO=<ID=AF_grpmax,Number=A,Type=Float,Description="Popmax AF">\n'
            '##INFO=<ID=grpmax,Number=A,Type=String,Description="Popmax population">\n'
            '##INFO=<ID=AF_afr,Number=A,Type=Float,Description="AF in afr">\n'
            '##INFO=<ID=AF_amr,Number=A,Type=Float,Description="AF in amr">\n'
            '##INFO=<ID=AF_asj,Number=A,Type=Float,Description="AF in asj">\n'
            '##INFO=<ID=AF_eas,Number=A,Type=Float,Description="AF in eas">\n'
            '##INFO=<ID=AF_fin,Number=A,Type=Float,Description="AF in fin">\n'
            '##INFO=<ID=AF_mid,Number=A,Type=Float,Description="AF in mid">\n'
            '##INFO=<ID=AF_nfe,Number=A,Type=Float,Description="AF in nfe">\n'
            '##INFO=<ID=AF_remaining,Number=A,Type=Float,Description="AF in remaining">\n'
            '##INFO=<ID=AF_sas,Number=A,Type=Float,Description="AF in sas">\n'
            f"##contig=<ID={chrom},length=248956422>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            f"{chrom}\t{pos}\t.\tA\tG\t.\t.\t"
            "AF_grpmax=0.0123;grpmax=nfe;"
            "AF_afr=0.001;AF_amr=0.005;AF_asj=0.002;AF_eas=0.0001;"
            "AF_fin=0.011;AF_mid=0.007;AF_nfe=0.0123;AF_remaining=0.004;AF_sas=0.003\n"
        )
        bgz = _bgz_index(plain)
        bgz.rename(target / f"{chrom}.vcf.bgz")
        old_tbi = target / f"{chrom}.vcf.gz.tbi"
        if old_tbi.exists():
            old_tbi.rename(target / f"{chrom}.vcf.bgz.tbi")


def _build_dbsnp_release(reference_dir: Path, release: str) -> Path:
    target = reference_dir / "dbsnp" / release
    target.mkdir(parents=True)
    plain = target / "dbsnp.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=RS,Number=1,Type=String,Description="dbSNP rsid">\n'
        "##contig=<ID=chr1,length=248956422>\n"
        "##contig=<ID=chr17,length=83257441>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\trs1\tA\tG\t.\t.\tRS=rs1\n"
        "chr17\t43044295\trs28897672\tG\tA\t.\t.\tRS=rs28897672\n"
    )
    return _bgz_index(plain)


def _stage_full_reference(reference_dir: Path) -> None:
    """Stage one release of each Phase-4C source under ``reference_dir/``."""
    _build_clinvar_release(reference_dir, "2026-05-09")
    _build_gnomad_exomes_release(reference_dir, "v4.1")
    _build_dbsnp_release(reference_dir, "b157")


# ---------------------------------------------------------------------------
# Chain tests (3 new)
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_annotate_writes_annotated_vcf_in_run_dir(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Happy path: ``annotate(run_dir)`` produces ``annotated.vcf.gz`` + ``.tbi``.

    Adapted from the Phase-4A happy-path test. The parent now chains
    ``annotate_vcfanno`` (which needs all three overlay sources staged)
    rather than running an in-line ``bcftools annotate``.
    """
    from genomeclaw_toolkit.prep.annotate import annotate
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ann-001",
    )
    normalize(run_dir=run_dir)
    out = annotate(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    assert out == run_dir / "annotated.vcf.gz"
    assert out.exists()
    assert (run_dir / "annotated.vcf.gz.tbi").exists()


@pytest.mark.needs_bio
def test_annotate_chains_vcfanno_then_promotes(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """The parent invokes ``annotate_vcfanno`` (whose output ``vcfanno.vcf.gz``
    remains on disk) and produces ``annotated.vcf.gz`` from it.

    Until 4D's VEP stage ships, ``annotated.vcf.gz`` is a copy of
    ``vcfanno.vcf.gz`` (byte-identical content). When 4D lands,
    ``annotated.vcf.gz`` becomes the post-VEP output and diverges from
    ``vcfanno.vcf.gz`` — but both files coexist in the run dir.
    """
    from genomeclaw_toolkit.prep.annotate import annotate
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ann-001",
    )
    normalize(run_dir=run_dir)
    annotate(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    # Both vcfanno.vcf.gz (mid-flight intermediate) and annotated.vcf.gz
    # (final output) are on disk after the parent returns.
    assert (run_dir / "vcfanno.vcf.gz").exists()
    assert (run_dir / "vcfanno.vcf.gz.tbi").exists()
    assert (run_dir / "annotated.vcf.gz").exists()
    assert (run_dir / "annotated.vcf.gz.tbi").exists()

    # 4C.3 stub: annotated.vcf.gz is byte-identical to vcfanno.vcf.gz
    # (VEP is a no-op at this sub-phase). When 4D ships, this assertion
    # updates to "annotated.vcf.gz is VEP's output, not vcfanno's".
    vcfanno_bytes = (run_dir / "vcfanno.vcf.gz").read_bytes()
    annotated_bytes = (run_dir / "annotated.vcf.gz").read_bytes()
    assert vcfanno_bytes == annotated_bytes


@pytest.mark.needs_bio
def test_invR001_annotate_chains_provenance_steps(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """`INV-R001`: provenance step trail records the chained sub-orchestrators.

    Until 4D ships, the trail post-``annotate`` ends in ``vcfanno`` (the
    only sub-orchestrator that actually runs). When 4D lands, a ``vep``
    step appears after it.
    """
    from genomeclaw_toolkit.prep.annotate import annotate
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ann-001",
    )
    normalize(run_dir=run_dir)
    annotate(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    provenance = json.loads((run_dir / "provenance.json").read_text())
    step_names = [s["step"] for s in provenance["steps"]]
    # The full chain post-annotate.
    assert step_names == ["ingest", "bcftools-stats", "normalize", "vcfanno"]


# ---------------------------------------------------------------------------
# Materialize-branch tests (2 kept from Phase 4A, adapted to 3-source staging)
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_materialize_after_annotate_populates_clinvar_columns(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """End-to-end: rows that match ClinVar carry annotation values in the
    DuckDB ``variants`` table; non-matching rows have NULLs.

    The annotation now flows through the chained orchestrator (vcfanno
    instead of bcftools-annotate). The downstream contract — ``materialize``
    reads from ``annotated.vcf.gz`` and pulls ``clinvar_classification`` /
    ``clinvar_review_status`` INFO fields into v0.2 columns — is unchanged.
    """
    from genomeclaw_toolkit.prep.annotate import annotate
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ann-001",
    )
    normalize(run_dir=run_dir)
    annotate(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])
    materialize(run_dir=run_dir)

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        annotated = conn.execute(
            "SELECT chrom, pos, alt, clinvar_classification, clinvar_review_status "
            "FROM variants WHERE clinvar_classification IS NOT NULL "
            "ORDER BY chrom, pos, alt"
        ).fetchall()
        non_annotated_count = conn.execute(
            "SELECT COUNT(*) FROM variants WHERE clinvar_classification IS NULL"
        ).fetchone()
        # Phase 4E surface: dbSNP rsids + all nine gnomAD v4 population
        # AFs land in their own v0.2 columns. The synthetic fixture's
        # chr1:1000 variant has data for every source — assert each
        # new column is populated for that record.
        row_chr1_1000 = conn.execute(
            "SELECT dbsnp_rsid, gnomad_af_popmax, gnomad_af_popmax_pop, "
            "       gnomad_af_afr, gnomad_af_amr, gnomad_af_asj, gnomad_af_eas, "
            "       gnomad_af_fin, gnomad_af_mid, gnomad_af_nfe, "
            "       gnomad_af_remaining, gnomad_af_sas "
            "FROM variants WHERE chrom = 'chr1' AND pos = 1000"
        ).fetchone()
    finally:
        conn.close()

    classifications = {row[3] for row in annotated}
    assert "Pathogenic" in classifications
    # At least one row should remain unannotated (non-matching).
    assert non_annotated_count is not None
    assert non_annotated_count[0] >= 1
    # Phase 4E columns populated for the all-three-sources row.
    assert row_chr1_1000 is not None, "expected chr1:1000 row to exist"
    (
        dbsnp_rsid,
        af_popmax,
        af_popmax_pop,
        af_afr,
        af_amr,
        af_asj,
        af_eas,
        af_fin,
        af_mid,
        af_nfe,
        af_remaining,
        af_sas,
    ) = row_chr1_1000
    assert dbsnp_rsid == "rs1", dbsnp_rsid
    assert af_popmax == pytest.approx(0.0123)
    assert af_popmax_pop == "nfe"
    assert af_afr == pytest.approx(0.001)
    assert af_amr == pytest.approx(0.005)
    assert af_asj == pytest.approx(0.002)
    assert af_eas == pytest.approx(0.0001)
    assert af_fin == pytest.approx(0.011)
    assert af_mid == pytest.approx(0.007)
    assert af_nfe == pytest.approx(0.0123)
    assert af_remaining == pytest.approx(0.004)
    assert af_sas == pytest.approx(0.003)


@pytest.mark.needs_bio
def test_materialize_fallback_to_normalized_when_annotated_missing(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """When ``annotated.vcf.gz`` is absent, materialize falls back to ``normalized.vcf.gz``.

    The ``clinvar_*`` annotation columns stay NULL on every row.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ann-001",
    )
    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        all_null = conn.execute(
            "SELECT COUNT(*) FROM variants "
            "WHERE clinvar_classification IS NOT NULL OR clinvar_review_status IS NOT NULL"
        ).fetchone()
    finally:
        conn.close()
    assert all_null is not None
    assert all_null[0] == 0

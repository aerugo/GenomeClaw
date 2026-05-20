"""Phase 3b3a — orchestrator auto-discovers match_rate from pgsc_calc work_dir.

When the caller omits ``match_rate`` + ``pgs_variant_count``, the
orchestrator probes ``work_dir`` for ``<sampleset>_log.csv.gz`` and parses
the matched/unmatched counts. The accession is synthesised as
``<pgs_id>_hmPOS_GRCh38`` (the PGS Catalog naming convention for harmonised
scoring files).

If the log isn't found, classification is skipped silently — the row
returns with ``calibration_status=None``. The explicit kwargs always
take precedence over auto-discovery (lets tests pin specific values).

Contract assertions:

1. Auto-discovery: no kwargs → orchestrator finds the log + classifies
   from its counts.
2. Explicit override: kwargs supplied → auto-discovery skipped (the
   classifier uses the caller's numbers verbatim).
3. Log absent: no log found in work_dir → row returned uncalibrated.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from unittest.mock import patch

import pytest

from genomeclaw_toolkit.prep.pgs import PgsRow

_LOG_HEADER = (
    "row_nr,accession,chr_name,chr_position,effect_allele,other_allele,"
    "effect_weight,effect_type,ID,REF,ALT,matched_effect_allele,"
    "match_type,is_multiallelic,ambiguous,match_flipped,best_match,"
    "exclude,duplicate_best_match,duplicate_ID,match_IDs,"
    "match_status,dataset"
)


def _write_log(log_path: Path, accession: str, *, matched: int, unmatched: int) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(log_path, "wt") as fh:
        fh.write(_LOG_HEADER + "\n")
        for _ in range(matched):
            fh.write("," + accession + ",,,,,,,,,,,,,,,,,,,,matched,MPNRGLQ2K\n")
        for _ in range(unmatched):
            fh.write("," + accession + ",,,,,,,,,,,,,,,,,,,,unmatched,MPNRGLQ2K\n")


@pytest.fixture
def fixture(tmp_path: Path) -> dict[str, Path]:
    """Stage the orchestrator's required inputs + a pre-seeded pgsc_calc work_dir."""
    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"CRAM")
    (raw / "MPNRGLQ2K.cram.crai").write_bytes(b"")

    ref = tmp_path / "reference"
    grch38 = ref / "grch38"
    grch38.mkdir(parents=True)
    fasta = grch38 / "grch38.fa.gz"
    fasta.write_bytes(b"")

    pca = ref / "prs_pca_sites" / "v1"
    pca.mkdir(parents=True)
    sites = pca / "pca_sites.tsv"
    alleles = pca / "pca_alleles.tsv"
    sites.write_text("chr22\t10001\n")
    alleles.write_text("chr22\t10001\tA,G\n")

    ancestry = ref / "pgs_catalog_ancestry" / "v1"
    ancestry.mkdir(parents=True)
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"")

    scorefile = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    with gzip.open(scorefile, "wt") as fh:
        fh.write(
            "#pgs_id=PGS000018\n"
            "hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
            "22\t20001\tG\tA\t0.0123\n"
        )

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    return {
        "cram": cram,
        "fasta": fasta,
        "sites": sites,
        "alleles": alleles,
        "scorefile": scorefile,
        "reference_root": ref,
        "output_root": tmp_path / "derived",
        "work_dir": work_dir,
    }


_BASE_ROW = PgsRow(
    pgs_id="PGS000018",
    trait_label="x",
    percentile_in_user_ancestry=87.0,
    raw_score=0.42,
    study_population="x",
    calibration_warning=None,
    agent_choice_rationale="r" * 60,
    requested_for_question="q",
)


def _stub_primitives():
    return (
        lambda **_kw: Path("/fake/tier1.vcf.gz"),
        lambda **_kw: Path("/fake/tier2.vcf.gz"),
        lambda **kw: kw["output_vcf"].write_bytes(b"") or None,
        lambda **_kw: _BASE_ROW,
    )


def _kwargs(fx: dict[str, Path]) -> dict[str, object]:
    return {
        "sample_id": "MPNRGLQ2K",
        "cram_path": fx["cram"],
        "sites_tsv": fx["sites"],
        "alleles_tsv": fx["alleles"],
        "scorefile_path": fx["scorefile"],
        "fasta": fx["fasta"],
        "panel_version": "v1",
        "reference_root": fx["reference_root"],
        "output_root": fx["output_root"],
        "work_dir": fx["work_dir"],
        "agent_choice_rationale": "r" * 60,
        "requested_for_question": "q",
    }


def test_auto_discovery_reads_match_rate_from_pgsc_calc_log(fixture: dict[str, Path]) -> None:
    """No kwargs supplied → orchestrator finds the log + classifies on its counts.

    Log contains 800 matched + 200 unmatched → match_rate = 0.80. PGS has
    1 SNP variant in the scorefile → falls into the ≤10k tier → 0.80 is in
    the WARNING band (75% ≤ rate < 90%).
    """
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    _write_log(
        fixture["work_dir"] / "3c" / "abc123" / "MPNRGLQ2K_log.csv.gz",
        accession="PGS000018_hmPOS_GRCh38",
        matched=800,
        unmatched=200,
    )

    t1, t2, mg, cp = _stub_primitives()
    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=t1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=t2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=mg),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=lambda **kw: kw["output_vcf"].write_bytes(b"\x1f\x8b"),
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=cp),
    ):
        result = compute_prs_with_coverage_fill(**_kwargs(fixture))

    # 800 / (800 + 200) = 0.80 on 1-variant scorefile (≤10k tier) → WARNING.
    assert result.calibration_status == "warning"


def test_auto_discovery_skips_when_log_absent(fixture: dict[str, Path]) -> None:
    """No log in work_dir → row returned without calibration_status."""
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    # work_dir is empty — no log_csv to find.
    t1, t2, mg, cp = _stub_primitives()
    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=t1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=t2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=mg),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=lambda **kw: kw["output_vcf"].write_bytes(b"\x1f\x8b"),
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=cp),
    ):
        result = compute_prs_with_coverage_fill(**_kwargs(fixture))

    assert result.calibration_status is None


def test_explicit_kwargs_override_auto_discovery(fixture: dict[str, Path]) -> None:
    """Explicit ``match_rate`` kwarg short-circuits auto-discovery.

    Stage a log that would auto-discover to CLEAN, but pass match_rate=0.20
    explicitly (DECLINE on 1.7M tier) → orchestrator must raise. Proves the
    kwarg takes precedence.
    """
    from genomeclaw_toolkit.prep._pgs_qc import PRSDeclineError
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    # Log would auto-discover to 100% match (CLEAN).
    _write_log(
        fixture["work_dir"] / "3c" / "abc123" / "MPNRGLQ2K_log.csv.gz",
        accession="PGS000018_hmPOS_GRCh38",
        matched=1000,
        unmatched=0,
    )

    t1, t2, mg, cp = _stub_primitives()
    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=t1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=t2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=mg),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=lambda **kw: kw["output_vcf"].write_bytes(b"\x1f\x8b"),
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=cp),
        pytest.raises(PRSDeclineError),
    ):
        compute_prs_with_coverage_fill(
            **_kwargs(fixture),
            match_rate=0.20,
            pgs_variant_count=1_700_000,
        )

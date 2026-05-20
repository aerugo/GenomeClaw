"""Phase 4c — end-to-end ``compute_prs_with_coverage_fill`` orchestrator tests.

Chains Tier 1 + Tier 2 + merge + pgsc_calc into one function call so the
agent's compute path has a single entry point. Each step is already tested
individually (Phases 1a/1b/2); this layer asserts that the **sequence** is
correct and that path threading between steps works.

Contract assertions:

1. **Sequence** — `prepare_coverage_tier1` is called first, then
   `prepare_coverage_tier2`, then `_merge_tier1_tier2`, then `compute_pgs`.
2. **Path threading** — the Tier 1 + Tier 2 cache paths feed into the
   merge step; the merged VCF feeds into `compute_pgs(--vcf ...)`.
3. **Return value** — the orchestrator returns the typed `PgsRow` that
   the downstream `_stamp_pgs_row` writes into ``pgs_scores``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from genomeclaw_toolkit.prep.pgs import PgsRow


@pytest.fixture
def orchestrator_fixture(tmp_path: Path) -> dict[str, Path]:
    """Stage CRAM + scorefile + reference + panel + output roots."""
    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"CRAM-fixture")
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

    # Ancestry panel layout (needed for compute_pgs's _check_ancestry_reference).
    ancestry = ref / "pgs_catalog_ancestry" / "v1"
    ancestry.mkdir(parents=True)
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"")

    scorefile = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    import gzip as _gzip

    with _gzip.open(scorefile, "wt") as fh:
        fh.write(
            "#pgs_id=PGS000018\n"
            "hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
            "22\t20001\tG\tA\t0.0123\n"
        )

    return {
        "cram": cram,
        "fasta": fasta,
        "sites": sites,
        "alleles": alleles,
        "scorefile": scorefile,
        "reference_root": ref,
        "output_root": tmp_path / "derived",
        "work_dir": tmp_path / "work",
    }


def test_compute_prs_orchestrates_tier1_tier2_merge_pgsc_calc(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """Full pipeline call sequence: Tier 1 → Tier 2 → merge → pgsc_calc."""
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    fx = orchestrator_fixture
    tier1_vcf = fx["output_root"] / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
    tier2_vcf = (
        fx["output_root"]
        / "prs_coverage"
        / "MPNRGLQ2K"
        / "v1"
        / "pgs"
        / "PGS000018-deadbeef"
        / "tier2.vcf.gz"
    )

    expected_row = PgsRow(
        pgs_id="PGS000018",
        trait_label="PGS Catalog PGS000018",
        percentile_in_user_ancestry=87.0,
        raw_score=0.42,
        study_population="PGS Catalog scoring weights",
        calibration_warning=None,
        agent_choice_rationale="rationale",
        requested_for_question="question",
    )

    call_order: list[str] = []

    def _fake_tier1(**_kwargs):
        call_order.append("tier1")
        tier1_vcf.parent.mkdir(parents=True, exist_ok=True)
        tier1_vcf.write_bytes(b"\x1f\x8b")
        return tier1_vcf

    def _fake_tier2(**_kwargs):
        call_order.append("tier2")
        tier2_vcf.parent.mkdir(parents=True, exist_ok=True)
        tier2_vcf.write_bytes(b"\x1f\x8b")
        return tier2_vcf

    def _fake_merge(**_kwargs):
        call_order.append("merge")
        merged = _kwargs["output_vcf"]
        merged.parent.mkdir(parents=True, exist_ok=True)
        merged.write_bytes(b"\x1f\x8b")

    def _fake_compute_pgs(**_kwargs):
        call_order.append("compute_pgs")
        return expected_row

    with (
        patch(
            "genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1",
            side_effect=_fake_tier1,
        ),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2",
            side_effect=_fake_tier2,
        ),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2",
            side_effect=_fake_merge,
        ),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=lambda **kw: kw["output_vcf"].write_bytes(b"\x1f\x8b"),
        ),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill.compute_pgs",
            side_effect=_fake_compute_pgs,
        ),
    ):
        result = compute_prs_with_coverage_fill(
            sample_id="MPNRGLQ2K",
            cram_path=fx["cram"],
            sites_tsv=fx["sites"],
            alleles_tsv=fx["alleles"],
            scorefile_path=fx["scorefile"],
            fasta=fx["fasta"],
            panel_version="v1",
            reference_root=fx["reference_root"],
            output_root=fx["output_root"],
            work_dir=fx["work_dir"],
            agent_choice_rationale="rationale",
            requested_for_question="question",
        )

    # 1. Sequence
    assert call_order == ["tier1", "tier2", "merge", "compute_pgs"], (
        f"orchestrator call order wrong: {call_order}"
    )
    # 2. Return value passes through
    assert result is expected_row


def test_compute_prs_threads_merge_output_into_compute_pgs(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """The chain merge → normalize → compute_pgs threads its outputs forward.

    After prs-non-imputed-wgs Phase 2 inserted ``_normalize_for_pgsc_calc``
    between merge and compute_pgs, the path identity changed: compute_pgs
    now receives the normalized VCF (`merged.norm.vcf.gz`), not the raw
    merged VCF (`merged.vcf.gz`). The test asserts merge's output is
    normalize's input and normalize's output is compute_pgs's input —
    preserving the original "data threads forward through the chain"
    intent.
    """
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    fx = orchestrator_fixture
    tier1_vcf = fx["output_root"] / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
    tier2_vcf = (
        fx["output_root"]
        / "prs_coverage"
        / "MPNRGLQ2K"
        / "v1"
        / "pgs"
        / "PGS000018-deadbeef"
        / "tier2.vcf.gz"
    )

    def _fake_tier1(**_kwargs):
        tier1_vcf.parent.mkdir(parents=True, exist_ok=True)
        tier1_vcf.write_bytes(b"\x1f\x8b")
        return tier1_vcf

    def _fake_tier2(**_kwargs):
        tier2_vcf.parent.mkdir(parents=True, exist_ok=True)
        tier2_vcf.write_bytes(b"\x1f\x8b")
        return tier2_vcf

    merge_calls: list[dict] = []

    def _fake_merge(**kwargs):
        merge_calls.append(kwargs)
        merged = kwargs["output_vcf"]
        merged.parent.mkdir(parents=True, exist_ok=True)
        merged.write_bytes(b"\x1f\x8b")

    normalize_calls: list[dict] = []

    def _fake_normalize(**kwargs):
        normalize_calls.append(kwargs)
        out = kwargs["output_vcf"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x1f\x8b")

    compute_calls: list[dict] = []

    def _fake_compute(**kwargs):
        compute_calls.append(kwargs)
        return PgsRow(
            pgs_id="PGS000018",
            trait_label="x",
            percentile_in_user_ancestry=50.0,
            raw_score=0.0,
            study_population="x",
            calibration_warning=None,
            agent_choice_rationale="r",
            requested_for_question="q",
        )

    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=_fake_tier1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=_fake_tier2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=_fake_merge),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=_fake_normalize,
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=_fake_compute),
    ):
        compute_prs_with_coverage_fill(
            sample_id="MPNRGLQ2K",
            cram_path=fx["cram"],
            sites_tsv=fx["sites"],
            alleles_tsv=fx["alleles"],
            scorefile_path=fx["scorefile"],
            fasta=fx["fasta"],
            panel_version="v1",
            reference_root=fx["reference_root"],
            output_root=fx["output_root"],
            work_dir=fx["work_dir"],
            agent_choice_rationale="r" * 60,
            requested_for_question="q",
        )

    # Merge received Tier 1 + Tier 2; emitted to some merged path.
    assert len(merge_calls) == 1
    merge_call = merge_calls[0]
    assert merge_call["tier1"] == tier1_vcf
    assert merge_call["tier2"] == tier2_vcf
    merged_path = merge_call["output_vcf"]

    # Normalize received the merge's output as its input.
    assert len(normalize_calls) == 1
    assert normalize_calls[0]["input_vcf"] == merged_path
    normalized_path = normalize_calls[0]["output_vcf"]

    # compute_pgs received the normalized VCF (NOT the raw merged VCF) as --vcf.
    # The Phase 2 wiring inserts normalize between merge and compute_pgs.
    assert len(compute_calls) == 1
    assert Path(compute_calls[0]["vcf"]) == Path(normalized_path), (
        f"compute_pgs received {compute_calls[0]['vcf']!r}; expected the "
        f"normalize step's output {normalized_path!r}."
    )
    assert compute_calls[0]["pgs_id"] == "PGS000018"
    assert compute_calls[0]["reference_root"] == fx["reference_root"]
    assert compute_calls[0]["work_dir"] == fx["work_dir"]


def test_compute_prs_threads_invA003_provenance(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """`agent_choice_rationale` + `requested_for_question` survive through to compute_pgs.

    INV-A003: when the agent triggers compute, its rationale + the user
    question must persist on the returned PgsRow. The orchestrator is a
    pass-through for these fields.
    """
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    fx = orchestrator_fixture
    rationale = (
        "Picked PGS000018 as the canonical CAD PRS; considered PGS003725 "
        "(newer, better cross-ancestry validation) but holding off until "
        "the smoke validates the simpler one first."
    )
    question = "my dad had a heart attack at 58 — what does my genome say about cad risk?"

    captured: dict = {}

    def _fake_compute(**kwargs):
        captured.update(kwargs)
        return PgsRow(
            pgs_id="PGS000018",
            trait_label="x",
            percentile_in_user_ancestry=50.0,
            raw_score=0.0,
            study_population="x",
            calibration_warning=None,
            agent_choice_rationale=kwargs.get("agent_choice_rationale", ""),
            requested_for_question=kwargs.get("requested_for_question", ""),
        )

    def _passthrough_tier1(**_kw):
        path = fx["output_root"] / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def _passthrough_tier2(**_kw):
        path = (
            fx["output_root"] / "prs_coverage" / "MPNRGLQ2K" / "v1"
            / "pgs" / "PGS000018-deadbeef" / "tier2.vcf.gz"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def _passthrough_merge(**kw):
        merged = kw["output_vcf"]
        merged.parent.mkdir(parents=True, exist_ok=True)
        merged.write_bytes(b"")

    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=_passthrough_tier1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=_passthrough_tier2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=_passthrough_merge),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=lambda **kw: kw["output_vcf"].write_bytes(b"\x1f\x8b"),
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=_fake_compute),
    ):
        result = compute_prs_with_coverage_fill(
            sample_id="MPNRGLQ2K",
            cram_path=fx["cram"],
            sites_tsv=fx["sites"],
            alleles_tsv=fx["alleles"],
            scorefile_path=fx["scorefile"],
            fasta=fx["fasta"],
            panel_version="v1",
            reference_root=fx["reference_root"],
            output_root=fx["output_root"],
            work_dir=fx["work_dir"],
            agent_choice_rationale=rationale,
            requested_for_question=question,
        )

    assert captured["agent_choice_rationale"] == rationale
    assert captured["requested_for_question"] == question
    assert result.agent_choice_rationale == rationale
    assert result.requested_for_question == question

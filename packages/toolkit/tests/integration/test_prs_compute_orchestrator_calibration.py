"""Phase 3b2 — ``compute_prs_with_coverage_fill`` calibration integration.

Extends the Phase 4c orchestrator with optional ``match_rate`` +
``pgs_variant_count`` parameters. When both are supplied the orchestrator
runs the classifier and either:

- annotates the returned :class:`PgsRow` with ``calibration_status`` =
  ``"clean"`` | ``"warning"``, OR
- raises :class:`PRSDeclineError` carrying the structural decline reason
  + two generated default named reasons.

When either param is omitted the orchestrator skips the classifier — keeps
every existing call site backwards compatible (Phase 4c tests still pass).

Contract assertions:

1. No match_rate / variant_count → returns row unchanged (Phase 4c
   regression guard still passes via this path).
2. CLEAN match_rate → row has ``calibration_status="clean"``.
3. WARNING match_rate → row has ``calibration_status="warning"``.
4. DECLINE match_rate → raises ``PRSDeclineError`` with the structural
   reason + two named reasons; the merge + pgsc_calc steps do still run
   (we want to surface the score with the decline annotation, not skip
   the compute entirely).

The 2026-05-17 smoke's `28.37% on PGS000018 (1.7M)` is the canonical
DECLINE case the test suite mirrors.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from genomeclaw_toolkit.prep.pgs import PgsRow


@pytest.fixture
def orchestrator_fixture(tmp_path: Path) -> dict[str, Path]:
    """Same shape as the Phase 4c orchestrator fixture, factored out here."""
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

    ancestry = ref / "pgs_catalog_ancestry" / "v1"
    ancestry.mkdir(parents=True)
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"")

    import gzip as _gzip

    scorefile = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
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


def _stub_pipeline(merged_vcf_path_holder: list[Path] | None = None):
    """Build the four primitive stubs the orchestrator chains.

    Returns a tuple of context managers to apply via ``contextlib.ExitStack``.
    """

    def _fake_tier1(**_kw):
        return Path("/fake/tier1.vcf.gz")

    def _fake_tier2(**_kw):
        return Path("/fake/tier2.vcf.gz")

    def _fake_merge(**kw):
        merged = kw["output_vcf"]
        merged.parent.mkdir(parents=True, exist_ok=True)
        merged.write_bytes(b"")
        if merged_vcf_path_holder is not None:
            merged_vcf_path_holder.append(merged)

    def _fake_compute(**_kw):
        return _BASE_ROW

    return (_fake_tier1, _fake_tier2, _fake_merge, _fake_compute)


def _orchestrator_kwargs(fx: dict[str, Path]) -> dict[str, object]:
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


# ---------------------------------------------------------------------------
# 1. Backwards compatibility — no calibration params → row unchanged.
# ---------------------------------------------------------------------------


def test_orchestrator_returns_row_unchanged_when_no_match_rate(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """Omit match_rate → orchestrator returns row with calibration_status=None.

    Phase 4c regression guard: existing callers don't have to pass the new
    params. The classifier path is opt-in.
    """
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    t1, t2, mg, cp = _stub_pipeline()
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
        result = compute_prs_with_coverage_fill(**_orchestrator_kwargs(orchestrator_fixture))

    assert result.calibration_status is None
    assert result.decline_reason is None


# ---------------------------------------------------------------------------
# 2. CLEAN — high match_rate → row annotated with "clean".
# ---------------------------------------------------------------------------


def test_orchestrator_annotates_clean_status(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """match_rate=0.92, 1k variants → CLEAN annotation."""
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    t1, t2, mg, cp = _stub_pipeline()
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
        result = compute_prs_with_coverage_fill(
            **_orchestrator_kwargs(orchestrator_fixture),
            match_rate=0.92,
            pgs_variant_count=1000,
        )

    assert result.calibration_status == "clean"
    assert result.decline_reason is None


# ---------------------------------------------------------------------------
# 3. WARNING — mid match_rate → row annotated with "warning".
# ---------------------------------------------------------------------------


def test_orchestrator_annotates_warning_status(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """match_rate=0.65, 300k variants → WARNING annotation (mid-band)."""
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    t1, t2, mg, cp = _stub_pipeline()
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
        result = compute_prs_with_coverage_fill(
            **_orchestrator_kwargs(orchestrator_fixture),
            match_rate=0.65,
            pgs_variant_count=300_000,
        )

    assert result.calibration_status == "warning"
    assert result.decline_reason is None


# ---------------------------------------------------------------------------
# 4. DECLINE — low match_rate → PRSDeclineError raised with 2 named reasons.
# ---------------------------------------------------------------------------


def test_orchestrator_raises_prs_decline_error_on_low_match_rate(
    orchestrator_fixture: dict[str, Path],
) -> None:
    """The 2026-05-17 smoke case (28.37% on 1.7M variants) → PRSDeclineError raised.

    The orchestrator catches the classifier's DECLINE decision and raises
    `PRSDeclineError` with structural reason + two generated default named
    reasons. The agent layer catches this and emits a decline record.
    """
    from genomeclaw_toolkit.prep._pgs_qc import DeclineReason, PRSDeclineError
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    t1, t2, mg, cp = _stub_pipeline()
    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=t1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=t2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=mg),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=lambda **kw: kw["output_vcf"].write_bytes(b"\x1f\x8b"),
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=cp),
        pytest.raises(PRSDeclineError) as excinfo,
    ):
        compute_prs_with_coverage_fill(
            **_orchestrator_kwargs(orchestrator_fixture),
            match_rate=0.2837,
            pgs_variant_count=1_700_000,
        )

    err = excinfo.value
    assert err.reason is DeclineReason.VARIANT_OVERLAP_INSUFFICIENT
    assert len(err.two_named_reasons) == 2
    # The first reason mentions the match rate; the second mentions the variant overlap.
    joined = " | ".join(err.two_named_reasons)
    assert "28" in joined or "0.28" in joined  # match-rate appears
    assert "variant" in joined.lower() or "overlap" in joined.lower()

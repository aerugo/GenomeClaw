"""Ancestry-calibration-uncertain classifier branch (Plan 7 Phase 2).

Per `prs-calibration-phase3b` Phase 2: a new branch in
``classify_calibration`` triggers ``ANCESTRY_CALIBRATION_UNCERTAIN`` when
the FRAPOSA-derived minimum Mahalanobis distance exceeds the
``_QC_MAHAL_THRESHOLD`` (3.0) AND the PGS Catalog ``gwas_ancestry``
metadata describes exactly one superpopulation.

Evaluation priority (overlap > ancestry > AUC): when the variant-overlap
axis already triggers a decline, the overlap reason wins; the ancestry
trigger is only consulted when overlap is clean or in the warning band.
"""

from __future__ import annotations


def test_classify_calibration_declines_ancestry_distance_exceeds_threshold_single_pop() -> None:
    """INV-C001: distance > 3.0 + single-ancestry GWAS + clean overlap → ANCESTRY_CALIBRATION_UNCERTAIN."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.95,  # clean
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,  # clean
        fraposa_min_mahalanobis_distance=3.5,
        gwas_ancestry_superpop_count=1,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN


def test_classify_calibration_clean_when_distance_below_threshold() -> None:
    """Distance below 3.0 + single ancestry → CLEAN (no ancestry decline)."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=2.5,
        gwas_ancestry_superpop_count=1,
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_classify_calibration_clean_when_multi_ancestry_gwas() -> None:
    """Distance > 3.0 but the GWAS spans multiple ancestries → CLEAN (no decline).

    Multi-ancestry GWAS should be more transferable across populations; the
    ancestry decline only fires when the GWAS was discovered in a single
    population.
    """
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=4.0,
        gwas_ancestry_superpop_count=2,
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_classify_calibration_clean_when_distance_is_none() -> None:
    """Distance unavailable → abstain on ancestry axis (no decline)."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=None,
        gwas_ancestry_superpop_count=1,
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_classify_calibration_clean_when_gwas_ancestry_unknown() -> None:
    """`gwas_ancestry_superpop_count=None` → abstain on ancestry axis."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=4.0,
        gwas_ancestry_superpop_count=None,
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_classify_calibration_overlap_decline_wins_over_ancestry() -> None:
    """Overlap < decline floor AND distance > 3.0 + single ancestry → overlap reason wins.

    Evaluation priority documented in `_pgs_qc.py`:
    overlap → ancestry → AUC gate. The first matching decline branch
    governs the structural reason.
    """
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.30,  # well below medium-tier decline floor 0.60
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.30,
        fraposa_min_mahalanobis_distance=4.0,
        gwas_ancestry_superpop_count=1,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


def test_classify_calibration_warning_band_still_consults_ancestry() -> None:
    """When overlap is in the WARNING band (no decline), ancestry can still trigger DECLINE."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.70,  # warning band 0.60-0.80 for medium tier
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.70,
        fraposa_min_mahalanobis_distance=4.0,
        gwas_ancestry_superpop_count=1,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN


def test_invC001_ancestry_branch_fires_across_all_tiers() -> None:
    """INV-C001 v1.7: ancestry-decline branch enforced across all three variant-count tiers."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    for tier_count in (5_000, 50_000, 1_000_000):
        decision = classify_calibration(
            match_rate=0.95,
            pgs_variant_count=tier_count,
            effect_weight_match_rate=0.95,
            fraposa_min_mahalanobis_distance=4.0,
            gwas_ancestry_superpop_count=1,
        )
        assert decision.status == CalibrationStatus.DECLINE, (
            f"tier_count={tier_count} did not decline on ancestry axis"
        )
        assert decision.decline_reason == DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN


def test_classify_calibration_threshold_constant_is_3() -> None:
    """The Mahalanobis decline threshold is 3.0 (top ~5% of a 10-D normal)."""
    from genomeclaw_toolkit.prep._pgs_qc import _QC_MAHAL_THRESHOLD

    assert _QC_MAHAL_THRESHOLD == 3.0


def test_classify_calibration_backwards_compat_without_ancestry_args() -> None:
    """Calling without the new ancestry kwargs reproduces Phase 1 behaviour."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(match_rate=0.95, pgs_variant_count=50_000)
    assert decision.status == CalibrationStatus.CLEAN

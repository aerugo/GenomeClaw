"""PGS_CATALOG_TIER_INSUFFICIENT classifier branch (Plan 7 Phase 3).

Per `prs-calibration-phase3b` Phase 3: the classifier triggers
``PGS_CATALOG_TIER_INSUFFICIENT`` when PGS Catalog evaluation metrics
show **BOTH** AUC improvement < 0.02 over a clinical baseline AND the
top-decile OR/HR confidence-interval lower bound < 1.5. Missing
metrics abstain (no decline on missing-metadata alone per INV-P001).
"""

from __future__ import annotations


def test_decline_when_both_auc_and_top_decile_below_floor() -> None:
    """INV-C001: auc_delta<0.02 AND top_decile_ci_lower<1.5 → PGS_CATALOG_TIER_INSUFFICIENT."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=2.0,  # clean ancestry
        gwas_ancestry_superpop_count=1,
        pgs_auc_delta=0.01,  # below threshold
        pgs_top_decile_ci_lower=1.3,  # below floor
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.PGS_CATALOG_TIER_INSUFFICIENT


def test_clean_when_auc_above_threshold() -> None:
    """auc_delta >= 0.02 → no tier decline regardless of top_decile_ci_lower."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        pgs_auc_delta=0.025,  # above 0.02 threshold
        pgs_top_decile_ci_lower=1.3,  # below floor — alone is not enough
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_clean_when_top_decile_above_floor() -> None:
    """top_decile_ci_lower >= 1.5 → no tier decline regardless of AUC delta."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        pgs_auc_delta=0.01,
        pgs_top_decile_ci_lower=1.8,  # above floor — alone is not enough
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_clean_when_auc_delta_missing() -> None:
    """Missing auc_delta → abstain on AUC axis (no decline)."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        pgs_auc_delta=None,
        pgs_top_decile_ci_lower=1.3,
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_clean_when_top_decile_ci_lower_missing() -> None:
    """Missing top_decile_ci_lower → abstain on AUC axis."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        pgs_auc_delta=0.01,
        pgs_top_decile_ci_lower=None,
    )
    assert decision.status == CalibrationStatus.CLEAN


def test_overlap_decline_wins_over_pgs_catalog_tier() -> None:
    """Overlap decline branch fires first; tier branch is not reached."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.30,  # below decline floor
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.30,
        pgs_auc_delta=0.01,
        pgs_top_decile_ci_lower=1.3,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


def test_ancestry_decline_wins_over_pgs_catalog_tier() -> None:
    """Ancestry decline branch is checked before the tier branch."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.95,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=4.0,
        gwas_ancestry_superpop_count=1,
        pgs_auc_delta=0.01,
        pgs_top_decile_ci_lower=1.3,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN


def test_warning_band_overlap_still_consults_pgs_catalog_tier() -> None:
    """Warning-band overlap + both PGS tier gates triggered → tier decline fires."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.70,  # warning band
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.70,
        pgs_auc_delta=0.01,
        pgs_top_decile_ci_lower=1.3,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.PGS_CATALOG_TIER_INSUFFICIENT


def test_INV_C001_pgs_catalog_tier_threshold_constants() -> None:
    """The thresholds are the PRS-RS reporting-standard floors."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        _QC_AUC_DELTA_THRESHOLD,
        _QC_TOP_DECILE_CI_FLOOR,
    )

    assert _QC_AUC_DELTA_THRESHOLD == 0.02
    assert _QC_TOP_DECILE_CI_FLOOR == 1.5

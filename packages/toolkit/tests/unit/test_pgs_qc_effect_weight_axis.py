"""Extended `classify_calibration(effect_weight_match_rate=...)` (Plan 7 Phase 1).

Per `prs-calibration-phase3b` Phase 1: the classifier now applies the
variant-count threshold table to BOTH the raw count match rate AND
the effect-weight-weighted match rate. The worst-of-two-axes governs:
a DECLINE on EITHER axis is a DECLINE; CLEAN requires BOTH axes clean.

Backwards compatibility: `effect_weight_match_rate=None` collapses to
the pre-Phase-1 behaviour (count axis only).
"""

from __future__ import annotations

import pytest


def test_classify_calibration_declines_on_effect_weight_axis_alone() -> None:
    """Count axis clean, weight axis below decline floor → DECLINE."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.85,  # above clean floor for medium tier
        pgs_variant_count=50_000,  # medium tier (10k-500k); thresholds 0.60 / 0.80
        effect_weight_match_rate=0.55,  # below decline floor 0.60
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


def test_classify_calibration_declines_on_count_axis_alone() -> None:
    """Weight axis clean, count axis below decline floor → DECLINE (pre-Phase-1 behaviour)."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.55,  # below medium-tier decline floor 0.60
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.85,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


def test_classify_calibration_clean_when_both_axes_clean() -> None:
    """Both axes ≥ clean floor → CLEAN."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.85,
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.85,
    )
    assert decision.status == CalibrationStatus.CLEAN
    assert decision.decline_reason is None


def test_classify_calibration_warning_when_both_axes_in_warning_band() -> None:
    """Both axes in [decline_floor, clean_floor) → WARNING."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.70,  # warning band 0.60-0.80
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.72,
    )
    assert decision.status == CalibrationStatus.WARNING


def test_classify_calibration_warning_when_one_axis_warning_other_clean() -> None:
    """Worst-of-two-axes: one axis warning, other clean → WARNING."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.85,  # clean
        pgs_variant_count=50_000,
        effect_weight_match_rate=0.70,  # warning
    )
    assert decision.status == CalibrationStatus.WARNING


def test_classify_calibration_unchanged_when_effect_weight_match_rate_none() -> None:
    """Backwards-compat: `effect_weight_match_rate=None` collapses to count-axis-only behaviour."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(
        match_rate=0.55,
        pgs_variant_count=50_000,
        effect_weight_match_rate=None,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


def test_classify_calibration_unchanged_when_effect_weight_arg_omitted() -> None:
    """Default value: `classify_calibration` without the new arg = pre-Phase-1 behaviour."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.85, pgs_variant_count=50_000)
    assert decision.status == CalibrationStatus.CLEAN


@pytest.mark.parametrize(
    ("tier_count", "decline_floor"),
    [
        (5_000, 0.75),  # small
        (50_000, 0.60),  # medium
        (1_000_000, 0.40),  # large
    ],
)
@pytest.mark.parametrize("axis", ["count", "weight", "both"])
def test_invC001_classify_declines_on_either_axis(
    tier_count: int, decline_floor: float, axis: str
) -> None:
    """INV-C001 v1.7: a DECLINE on EITHER axis is a DECLINE, across all three tiers.

    Parametrized matrix: 3 tiers × 3 scenarios (count-axis low, weight-axis low,
    both low). All 9 combinations must produce DECLINE.
    """
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    below = decline_floor - 0.01
    above = decline_floor + 0.15

    if axis == "count":
        match_rate, weight_rate = below, above
    elif axis == "weight":
        match_rate, weight_rate = above, below
    else:  # both
        match_rate, weight_rate = below, below

    decision = classify_calibration(
        match_rate=match_rate,
        pgs_variant_count=tier_count,
        effect_weight_match_rate=weight_rate,
    )
    assert decision.status == CalibrationStatus.DECLINE
    assert decision.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT

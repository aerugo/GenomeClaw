"""Phase 3 — ``classify_calibration`` QC threshold table + decline taxonomy.

Per ``INV-C001`` v1.7 the PRS-decline pattern requires every finding to be
either ancestry-calibrated (CLEAN), surfaced with a warning (WARNING), or
declined with one of five named reasons (DECLINE).

The QC threshold table scales the match-rate floor with PGS variant count.
A 200-variant score loses more statistical power per missing variant than
a 1M-variant score, so the floor relaxes as N grows:

| PGS variant count | Decline if match rate < | Warn if match rate in | Clean if ≥ |
|---|---|---|---|
| ≤10k               | 75%                     | 75–90%                | 90%        |
| 10k–500k           | 60%                     | 60–80%                | 80%        |
| >500k              | 40%                     | 40–75%                | 75%        |

Phase 3a scope: implements the **variant-overlap** axis of the classifier
(``VARIANT_OVERLAP_INSUFFICIENT``). The four ancestry- and metadata-driven
reasons (``POPULATION_TRANSFERABILITY_INSUFFICIENT`` /
``PGS_CATALOG_TIER_INSUFFICIENT`` / ``PHENOTYPE_HETEROGENEOUS`` /
``ANCESTRY_CALIBRATION_UNCERTAIN``) are stub-declared in the enum so the
schema is stable; classifier branches for them land in Phase 3b when
FRAPOSA output + PGS Catalog metadata flow in.

Contract assertions:

1. Each of the three variant-count tiers × three status bands → expected
   outcome (9 tests).
2. ``PRSDeclineError`` carries the structural decline reason + two named
   reasons (INV-A003 two-named-reasons rule).
3. All five decline reasons are addressable as enum members (schema gate).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Tier 1 — ≤10k PGS variants. Strictest match-rate floor (90% clean / 75% decline).
# ---------------------------------------------------------------------------


def test_classify_clean_at_high_match_rate_small_pgs() -> None:
    """≤10k variants + match rate ≥ 90% → CLEAN."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.92, pgs_variant_count=1000)

    assert decision.status is CalibrationStatus.CLEAN
    assert decision.decline_reason is None


def test_classify_warning_at_mid_match_rate_small_pgs() -> None:
    """≤10k variants + 75% ≤ match rate < 90% → WARNING."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.85, pgs_variant_count=5000)

    assert decision.status is CalibrationStatus.WARNING
    assert decision.decline_reason is None


def test_classify_decline_at_low_match_rate_small_pgs() -> None:
    """≤10k variants + match rate < 75% → DECLINE / VARIANT_OVERLAP_INSUFFICIENT."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.50, pgs_variant_count=2000)

    assert decision.status is CalibrationStatus.DECLINE
    assert decision.decline_reason is DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


# ---------------------------------------------------------------------------
# Tier 2 — 10k–500k variants. Mid-strictness (80% clean / 60% decline).
# ---------------------------------------------------------------------------


def test_classify_clean_at_high_match_rate_medium_pgs() -> None:
    """10k–500k variants + match rate ≥ 80% → CLEAN."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.85, pgs_variant_count=100_000)

    assert decision.status is CalibrationStatus.CLEAN


def test_classify_warning_at_mid_match_rate_medium_pgs() -> None:
    """10k–500k variants + 60% ≤ match rate < 80% → WARNING."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.70, pgs_variant_count=300_000)

    assert decision.status is CalibrationStatus.WARNING


def test_classify_decline_at_low_match_rate_medium_pgs() -> None:
    """10k–500k variants + match rate < 60% → DECLINE / VARIANT_OVERLAP_INSUFFICIENT."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.40, pgs_variant_count=200_000)

    assert decision.status is CalibrationStatus.DECLINE
    assert decision.decline_reason is DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


# ---------------------------------------------------------------------------
# Tier 3 — >500k variants. Loosest match-rate floor (75% clean / 40% decline).
# ---------------------------------------------------------------------------


def test_classify_clean_at_high_match_rate_large_pgs() -> None:
    """>500k variants + match rate ≥ 75% → CLEAN."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.80, pgs_variant_count=1_300_000)

    assert decision.status is CalibrationStatus.CLEAN


def test_classify_warning_at_mid_match_rate_large_pgs() -> None:
    """>500k variants + 40% ≤ match rate < 75% → WARNING."""
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.60, pgs_variant_count=1_700_000)

    assert decision.status is CalibrationStatus.WARNING


def test_classify_decline_at_low_match_rate_large_pgs() -> None:
    """>500k variants + match rate < 40% → DECLINE / VARIANT_OVERLAP_INSUFFICIENT.

    Mirrors the 28.37% match-rate failure from the 2026-05-17 real-data smoke
    on PGS000018 (1.7M variants) — the canonical case the whole plan exists
    to solve correctly.
    """
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationStatus,
        DeclineReason,
        classify_calibration,
    )

    decision = classify_calibration(match_rate=0.2837, pgs_variant_count=1_700_000)

    assert decision.status is CalibrationStatus.DECLINE
    assert decision.decline_reason is DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


# ---------------------------------------------------------------------------
# Boundary cases — exact threshold values.
# ---------------------------------------------------------------------------


def test_classify_boundary_exact_90_pct_small_pgs_is_clean() -> None:
    """Exactly 90% on a 5k-variant score → CLEAN (the threshold is inclusive)."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(match_rate=0.90, pgs_variant_count=5000)
    assert decision.status is CalibrationStatus.CLEAN


def test_classify_boundary_exact_75_pct_small_pgs_is_warning() -> None:
    """Exactly 75% on a 5k-variant score → WARNING (decline gate is strict <)."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, classify_calibration

    decision = classify_calibration(match_rate=0.75, pgs_variant_count=5000)
    assert decision.status is CalibrationStatus.WARNING


# ---------------------------------------------------------------------------
# Decline-reason enum + PRSDeclineError shape.
# ---------------------------------------------------------------------------


def test_decline_reason_enum_carries_all_five_inv_c001_v1_7_reasons() -> None:
    """The five named decline reasons from INV-C001 v1.7 are all enum members.

    Schema gate: even if Phase 3a only implements the variant-overlap branch,
    the enum surface is stable so future phases (FRAPOSA-driven decline
    reasons, PGS Catalog metadata-driven reasons) just wire their
    classifier branches without an enum-shape migration.
    """
    from genomeclaw_toolkit.prep._pgs_qc import DeclineReason

    names = {member.name for member in DeclineReason}
    assert names == {
        "POPULATION_TRANSFERABILITY_INSUFFICIENT",
        "PGS_CATALOG_TIER_INSUFFICIENT",
        "PHENOTYPE_HETEROGENEOUS",
        "VARIANT_OVERLAP_INSUFFICIENT",
        "ANCESTRY_CALIBRATION_UNCERTAIN",
    }


def test_prs_decline_error_carries_named_reasons() -> None:
    """``PRSDeclineError`` carries (structural reason, 2 human-readable reasons).

    INV-A003 + INV-C001 v1.7 two-named-reasons rule: the agent surface
    receives the structural enum + two human-readable explanations so the
    user-facing copy is consistent across questions while the agent can
    still inject question-specific context.
    """
    from genomeclaw_toolkit.prep._pgs_qc import DeclineReason, PRSDeclineError

    err = PRSDeclineError(
        reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
        two_named_reasons=(
            "Match rate 28.37% is below the 40% floor for ≥500k-variant scores.",
            "Variant-only VCFs lack REF/REF dosages at PGS Catalog scoring sites; "
            "the Tier 1 + Tier 2 forced-genotyping bridge is the intended fix.",
        ),
        message="PRS computation declined per INV-C001 v1.7",
    )

    assert err.reason is DeclineReason.VARIANT_OVERLAP_INSUFFICIENT
    assert len(err.two_named_reasons) == 2
    assert all(isinstance(r, str) and r for r in err.two_named_reasons)
    assert "INV-C001" in str(err)


def test_prs_decline_error_rejects_fewer_than_two_named_reasons() -> None:
    """A decline with < 2 named reasons violates INV-C001 v1.7; constructor raises.

    Defensive — keeps the two-named-reasons rule mechanically enforced
    rather than relying on caller discipline.
    """
    from genomeclaw_toolkit.prep._pgs_qc import DeclineReason, PRSDeclineError

    with pytest.raises(ValueError, match=r"two named reasons"):
        PRSDeclineError(
            reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
            two_named_reasons=("only one",),  # type: ignore[arg-type]
            message="bad construction",
        )

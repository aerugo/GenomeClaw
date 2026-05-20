"""PRS calibration QC classifier + decline taxonomy per ``INV-C001`` v1.7.

Every PRS finding GenomeClaw surfaces is one of three calibration states:

- **CLEAN** — match rate meets the per-variant-count threshold; the
  percentile + Z-score are ancestry-calibrated and safe to surface.
- **WARNING** — match rate is in the mid-band; the finding ships with an
  explicit ``calibration_warning`` annotation so the agent can frame the
  uncertainty.
- **DECLINE** — match rate (or one of four other gates added in later
  phases) falls below the floor; the agent refuses the finding with a
  structural :class:`DeclineReason` and two human-readable named reasons.

The match-rate × variant-count threshold table — verified against the
2026-05-17 real-data smoke (PGS000018: 1.7M variants, 28.37% match → must
decline) and the corresponding research-brief recommendation:

============================== ==================== ==================== ===========
PGS variant count              Decline if rate <    Warn if rate in       Clean if ≥
============================== ==================== ==================== ===========
≤ 10,000                       75%                  75–90%               90%
10,000 – 500,000               60%                  60–80%               80%
> 500,000                      40%                  40–75%               75%
============================== ==================== ==================== ===========

Phase 3a scope: the variant-overlap axis (``VARIANT_OVERLAP_INSUFFICIENT``).
The four ancestry- and metadata-driven decline reasons are enum-declared
so the schema stabilises; classifier branches for them land in Phase 3b
when FRAPOSA output + PGS Catalog metadata flow through.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CalibrationStatus(str, Enum):
    """The three calibration outcomes for a PRS finding (INV-C001 v1.7)."""

    CLEAN = "clean"
    WARNING = "warning"
    DECLINE = "decline"


class DeclineReason(str, Enum):
    """The five named decline reasons (INV-C001 v1.7).

    The agent surface picks one of these as the structural decline reason
    and supplies two human-readable named reasons alongside (INV-A003
    two-named-reasons rule).
    """

    POPULATION_TRANSFERABILITY_INSUFFICIENT = "population_transferability_insufficient"
    PGS_CATALOG_TIER_INSUFFICIENT = "pgs_catalog_tier_insufficient"
    PHENOTYPE_HETEROGENEOUS = "phenotype_heterogeneous"
    VARIANT_OVERLAP_INSUFFICIENT = "variant_overlap_insufficient"
    ANCESTRY_CALIBRATION_UNCERTAIN = "ancestry_calibration_uncertain"


@dataclass(frozen=True)
class CalibrationDecision:
    """The classifier's output: structural status + (optional) decline reason."""

    status: CalibrationStatus
    decline_reason: DeclineReason | None = None


class PRSDeclineError(RuntimeError):
    """A PRS finding cannot be safely surfaced and must be declined.

    Carries the structural :class:`DeclineReason` + two named human-readable
    reasons (INV-A003 two-named-reasons rule). The constructor enforces the
    two-reasons contract mechanically — a caller can't slip a single-reason
    decline past static analysis.
    """

    def __init__(
        self,
        *,
        reason: DeclineReason,
        two_named_reasons: tuple[str, str],
        message: str,
    ) -> None:
        if not isinstance(two_named_reasons, tuple) or len(two_named_reasons) != 2:
            raise ValueError(
                "PRSDeclineError requires exactly two named reasons (INV-C001 v1.7); "
                f"got {two_named_reasons!r}"
            )
        if not all(isinstance(r, str) and r.strip() for r in two_named_reasons):
            raise ValueError(
                "PRSDeclineError named reasons must be non-empty strings; "
                f"got {two_named_reasons!r}"
            )
        super().__init__(message)
        self.reason = reason
        self.two_named_reasons = two_named_reasons


# Tier boundaries for the match-rate threshold table. Inclusive on the
# upper variant-count bound so a score with exactly 10_000 variants lands
# in the strictest tier.
_TIER_SMALL_MAX = 10_000
_TIER_MEDIUM_MAX = 500_000

# Per-tier (clean_floor, decline_floor) match-rate thresholds.
# CLEAN ⇔ rate ≥ clean_floor.
# WARNING ⇔ decline_floor ≤ rate < clean_floor.
# DECLINE ⇔ rate < decline_floor.
_THRESHOLDS: dict[str, tuple[float, float]] = {
    "small": (0.90, 0.75),
    "medium": (0.80, 0.60),
    "large": (0.75, 0.40),
}


def _resolve_tier(pgs_variant_count: int) -> str:
    if pgs_variant_count <= _TIER_SMALL_MAX:
        return "small"
    if pgs_variant_count <= _TIER_MEDIUM_MAX:
        return "medium"
    return "large"


def classify_calibration(
    *,
    match_rate: float,
    pgs_variant_count: int,
) -> CalibrationDecision:
    """Classify a PRS finding's calibration state on the variant-overlap axis.

    Args:
        match_rate: Fraction of PGS scoring weights that matched the user's
            VCF after the Tier 1 + Tier 2 forced-genotyping bridge. Range
            ``[0.0, 1.0]``.
        pgs_variant_count: Number of variants in the PGS Catalog scoring
            file (the row count after SNP-filter). Determines which tier
            of the threshold table applies.

    Returns:
        A :class:`CalibrationDecision` with :attr:`CalibrationStatus`
        populated and (when ``status is DECLINE``) the structural
        :class:`DeclineReason` set to ``VARIANT_OVERLAP_INSUFFICIENT``.

    Phase 3b will widen the signature to accept ancestry-driven inputs
    (Mahalanobis distance, FRAPOSA super-population call, GWAS ancestry
    composition) and route to the four other decline reasons.
    """
    tier = _resolve_tier(pgs_variant_count)
    clean_floor, decline_floor = _THRESHOLDS[tier]

    if match_rate >= clean_floor:
        return CalibrationDecision(status=CalibrationStatus.CLEAN)
    if match_rate >= decline_floor:
        return CalibrationDecision(status=CalibrationStatus.WARNING)
    return CalibrationDecision(
        status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
    )


__all__ = [
    "CalibrationDecision",
    "CalibrationStatus",
    "DeclineReason",
    "PRSDeclineError",
    "classify_calibration",
]

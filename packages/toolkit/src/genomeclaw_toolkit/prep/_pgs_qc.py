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

Phase 3b (`prs-calibration-phase3b`) extended the classifier with three
further branches:

- ``ANCESTRY_CALIBRATION_UNCERTAIN`` — FRAPOSA Mahalanobis distance > 3.0
  AND the PGS Catalog ``gwas_ancestry`` describes a single superpopulation.
- ``PGS_CATALOG_TIER_INSUFFICIENT`` — PGS Catalog evaluation metrics
  show AUC improvement over a clinical baseline < 0.02 AND the
  top-decile OR/HR confidence-interval lower bound < 1.5.

Two enum-declared decline reasons remain deferred to a follow-up plan
(no operational classifier branch yet): ``POPULATION_TRANSFERABILITY_INSUFFICIENT``
and ``PHENOTYPE_HETEROGENEOUS``. They require additional reference data
(multi-ancestry GWAS composition tables and phenotype-heterogeneity
mappings) not yet present in the reference-data layout.
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

# Mahalanobis-distance threshold for the ANCESTRY_CALIBRATION_UNCERTAIN
# branch. 3.0 in a 10-dimensional PCA space catches roughly the top 5%
# of a multivariate-normal training distribution — the standard "three
# sigma" multivariate-outlier convention. If FRAPOSA's published
# threshold differs in a future revision, bump here (single source of
# truth for the trigger).
_QC_MAHAL_THRESHOLD: float = 3.0

# Minimum AUC improvement over a clinical baseline below which the
# PGS_CATALOG_TIER_INSUFFICIENT decline can fire (Phase 3). 0.02 is the
# PRS-RS reporting-standard floor per Wand et al. 2021. Used in
# conjunction with the top-decile CI floor below: BOTH conditions must
# hold for the decline to fire.
_QC_AUC_DELTA_THRESHOLD: float = 0.02

# Top-decile OR/HR confidence-interval lower-bound floor (Phase 3). When
# the lower bound of the top-decile odds/hazard ratio's confidence
# interval is below this value, the discriminative power is considered
# insufficient (INV-C001 v1.7 PRS-decline criterion (a)).
_QC_TOP_DECILE_CI_FLOOR: float = 1.5


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
    effect_weight_match_rate: float | None = None,
    fraposa_min_mahalanobis_distance: float | None = None,
    gwas_ancestry_superpop_count: int | None = None,
    pgs_auc_delta: float | None = None,
    pgs_top_decile_ci_lower: float | None = None,
) -> CalibrationDecision:
    """Classify a PRS finding's calibration state.

    Evaluation priority (first matching DECLINE wins):

    1. **Variant overlap** — count-axis match_rate AND optional
       effect-weight axis (Plan 7 Phase 1, worst-of-two governs).
    2. **Ancestry calibration** — Mahalanobis distance > 3.0 AND the
       PGS GWAS was discovered in exactly one superpopulation
       (Plan 7 Phase 2 → ``ANCESTRY_CALIBRATION_UNCERTAIN``).
    3. **PGS Catalog tier / AUC gate** — AUC improvement over a
       clinical baseline < 0.02 AND top-decile OR/HR CI lower bound
       < 1.5 (Plan 7 Phase 3 → ``PGS_CATALOG_TIER_INSUFFICIENT``).

    Args:
        match_rate: Fraction of PGS scoring weights that matched the user's
            VCF after the Tier 1 + Tier 2 forced-genotyping bridge. Range
            ``[0.0, 1.0]``.
        pgs_variant_count: Number of variants in the PGS Catalog scoring
            file (the row count after SNP-filter). Determines which tier
            of the threshold table applies.
        effect_weight_match_rate: Optional second overlap axis — the
            effect-weight-weighted match rate
            (``Σ|β|_matched / Σ|β|_total``) per
            `prs-calibration-phase3b` Phase 1. When provided, the same
            per-tier threshold table applies to it; the **worst** of
            the two axes governs (decline-on-either, clean requires
            both). ``None`` collapses to the pre-Phase-1 behaviour
            (count-axis-only classification).
        fraposa_min_mahalanobis_distance: Minimum Mahalanobis distance
            from the user's PC vector to any 1kGP+HGDP superpopulation
            centroid (per
            :mod:`genomeclaw_toolkit.prep._pgs_fraposa`). ``None``
            abstains on the ancestry axis.
        gwas_ancestry_superpop_count: Number of distinct superpopulations
            covered by the PGS Catalog ``gwas_ancestry`` field for this
            scoring file. ``1`` (single-ancestry GWAS) is the only value
            that activates the ancestry decline; multi-ancestry GWAS are
            considered more transferable. ``None`` abstains.
        pgs_auc_delta: AUC improvement of this PGS over a clinical
            baseline model from PGS Catalog evaluation metrics (per
            :mod:`genomeclaw_toolkit.prep._pgs_catalog_meta`). ``None``
            abstains on the AUC axis (the missing-metadata policy from
            INV-P001: never decline on absent evaluation data alone).
        pgs_top_decile_ci_lower: Lower bound of the top-decile OR/HR
            confidence interval from PGS Catalog evaluation metrics.
            Below 1.5 indicates the top-decile risk separation is not
            distinguishable from null. ``None`` abstains.

    Returns:
        A :class:`CalibrationDecision` with :attr:`CalibrationStatus`
        populated and (when ``status is DECLINE``) the structural
        :class:`DeclineReason` set to whichever branch fired first.
    """
    tier = _resolve_tier(pgs_variant_count)
    clean_floor, decline_floor = _THRESHOLDS[tier]

    # ---- Axis 1: variant overlap (worst-of-two) ----
    # CLEAN requires BOTH axes ≥ clean_floor; DECLINE fires on EITHER axis.
    # `effect_weight_match_rate=None` collapses to pre-Phase-1 behaviour.
    if effect_weight_match_rate is None:
        effective_rate = match_rate
    else:
        effective_rate = min(match_rate, effect_weight_match_rate)

    if effective_rate < decline_floor:
        return CalibrationDecision(
            status=CalibrationStatus.DECLINE,
            decline_reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
        )

    # ---- Axis 2: ancestry calibration ----
    if (
        fraposa_min_mahalanobis_distance is not None
        and fraposa_min_mahalanobis_distance > _QC_MAHAL_THRESHOLD
        and gwas_ancestry_superpop_count is not None
        and gwas_ancestry_superpop_count == 1
    ):
        return CalibrationDecision(
            status=CalibrationStatus.DECLINE,
            decline_reason=DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN,
        )

    # ---- Axis 3: PGS Catalog evaluation-metrics tier ----
    if (
        pgs_auc_delta is not None
        and pgs_auc_delta < _QC_AUC_DELTA_THRESHOLD
        and pgs_top_decile_ci_lower is not None
        and pgs_top_decile_ci_lower < _QC_TOP_DECILE_CI_FLOOR
    ):
        return CalibrationDecision(
            status=CalibrationStatus.DECLINE,
            decline_reason=DeclineReason.PGS_CATALOG_TIER_INSUFFICIENT,
        )

    # ---- Final overlap-axis classification ----
    if effective_rate >= clean_floor:
        return CalibrationDecision(status=CalibrationStatus.CLEAN)
    return CalibrationDecision(status=CalibrationStatus.WARNING)


__all__ = [
    "CalibrationDecision",
    "CalibrationStatus",
    "DeclineReason",
    "PRSDeclineError",
    "classify_calibration",
]

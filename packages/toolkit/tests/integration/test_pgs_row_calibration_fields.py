"""Phase 3b1 — ``PgsRow`` carries optional calibration_status + decline_reason.

The classifier from Phase 3a (`_pgs_qc.classify_calibration`) produces a
:class:`CalibrationDecision`; consumers need a way to attach that decision
to the in-memory :class:`PgsRow` so the CLI's JSON envelope + the future
DuckDB persistence layer both surface the same status / decline_reason.

Contract assertions:

1. `PgsRow` accepts ``calibration_status`` + ``decline_reason`` as optional
   fields (default ``None`` — backwards compatible with every existing
   construction site).
2. `apply_calibration_decision(row, decision)` returns a new row whose
   calibration fields reflect the decision; the other 8 row fields are
   preserved byte-for-byte.
3. Each of the three calibration states (CLEAN / WARNING / DECLINE) round-
   trips correctly.
4. The decline-reason on a DECLINE row is stamped as the enum's `.value`
   (the snake_case string), not the bare member — keeps the future
   DuckDB column type stable (`TEXT`).
"""

from __future__ import annotations

import dataclasses

import pytest


def _base_row():
    """A PgsRow with all the existing 8 fields populated."""
    from genomeclaw_toolkit.prep.pgs import PgsRow

    return PgsRow(
        pgs_id="PGS000018",
        trait_label="metaGRS_CAD",
        percentile_in_user_ancestry=87.0,
        raw_score=0.42,
        study_population="PGS Catalog scoring weights",
        calibration_warning=None,
        agent_choice_rationale="r" * 60,
        requested_for_question="why?",
    )


def test_pgs_row_supports_optional_calibration_fields() -> None:
    """`PgsRow` can be constructed with or without the new calibration fields."""
    from genomeclaw_toolkit.prep.pgs import PgsRow

    # Backwards-compatible: no calibration fields supplied → both default to None.
    row_default = _base_row()
    assert row_default.calibration_status is None
    assert row_default.decline_reason is None

    # Explicit construction with the new fields works.
    row_explicit = PgsRow(
        pgs_id="PGS000018",
        trait_label="x",
        percentile_in_user_ancestry=None,
        raw_score=None,
        study_population="x",
        calibration_warning=None,
        agent_choice_rationale="r" * 60,
        requested_for_question="q",
        calibration_status="clean",
        decline_reason=None,
    )
    assert row_explicit.calibration_status == "clean"
    assert row_explicit.decline_reason is None


def test_apply_calibration_decision_clean(
) -> None:
    """A CLEAN decision attaches `calibration_status="clean"`; decline_reason stays None."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationDecision, CalibrationStatus
    from genomeclaw_toolkit.prep.pgs import apply_calibration_decision

    row = _base_row()
    decision = CalibrationDecision(status=CalibrationStatus.CLEAN)

    annotated = apply_calibration_decision(row, decision)

    assert annotated.calibration_status == "clean"
    assert annotated.decline_reason is None


def test_apply_calibration_decision_warning() -> None:
    """A WARNING decision attaches `calibration_status="warning"`; decline_reason stays None."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationDecision, CalibrationStatus
    from genomeclaw_toolkit.prep.pgs import apply_calibration_decision

    row = _base_row()
    decision = CalibrationDecision(status=CalibrationStatus.WARNING)

    annotated = apply_calibration_decision(row, decision)

    assert annotated.calibration_status == "warning"
    assert annotated.decline_reason is None


def test_apply_calibration_decision_decline() -> None:
    """A DECLINE decision attaches both calibration_status + decline_reason.

    decline_reason is stamped as the enum's `.value` (snake_case string)
    so the future DuckDB column type is `TEXT` rather than a custom enum.
    """
    from genomeclaw_toolkit.prep._pgs_qc import (
        CalibrationDecision,
        CalibrationStatus,
        DeclineReason,
    )
    from genomeclaw_toolkit.prep.pgs import apply_calibration_decision

    row = _base_row()
    decision = CalibrationDecision(
        status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
    )

    annotated = apply_calibration_decision(row, decision)

    assert annotated.calibration_status == "decline"
    assert annotated.decline_reason == "variant_overlap_insufficient"


def test_apply_calibration_decision_preserves_other_fields() -> None:
    """Only calibration_status + decline_reason change; the other 8 fields are byte-equal."""
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationDecision, CalibrationStatus
    from genomeclaw_toolkit.prep.pgs import apply_calibration_decision

    row = _base_row()
    decision = CalibrationDecision(status=CalibrationStatus.CLEAN)

    annotated = apply_calibration_decision(row, decision)

    # Compare every other field. dataclasses.replace would be the production
    # tool; we explicit-compare here so the contract is readable.
    for field in dataclasses.fields(row):
        if field.name in {"calibration_status", "decline_reason"}:
            continue
        assert getattr(row, field.name) == getattr(annotated, field.name), (
            f"field {field.name!r} changed: {getattr(row, field.name)!r} "
            f"→ {getattr(annotated, field.name)!r}"
        )


def test_apply_calibration_decision_decline_without_reason_raises() -> None:
    """A DECLINE decision missing its `decline_reason` is structurally invalid.

    Mechanical guard: the classifier's contract is that DECLINE always
    populates decline_reason. If something constructs a half-populated
    decision, `apply_calibration_decision` raises rather than silently
    persisting a no-reason decline.
    """
    from genomeclaw_toolkit.prep._pgs_qc import CalibrationDecision, CalibrationStatus
    from genomeclaw_toolkit.prep.pgs import apply_calibration_decision

    row = _base_row()
    # Construct a malformed decision (DECLINE without a reason).
    bad_decision = CalibrationDecision(
        status=CalibrationStatus.DECLINE,
        decline_reason=None,  # invalid for DECLINE
    )

    with pytest.raises(ValueError, match=r"DECLINE.*decline_reason"):
        apply_calibration_decision(row, bad_decision)

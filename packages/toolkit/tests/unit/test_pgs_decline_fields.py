"""`PgsRowResponse` + `PgsListRow` carry `calibration_status` + `decline_reason`.

The DB persists `calibration_status` and `decline_reason` columns on every
`pgs_scores` row written since Phase 3b3b1. The HTTP boundary models stripped
both fields (`extra="forbid"` would have rejected them even if the store
projected them — neither was true). The agent could only pattern-match a
free-text `calibration_warning` string to infer a decline.

These tests pin the widened model surface. Per `INV-A004` (proposed in the
agent-decline-taxonomy-exposure plan), both fields must traverse Pydantic
without loss; the cross-language diff against TypeBox lives in
`tests/invariants/test_invA004_decline_taxonomy_traverse.py`.

Both fields are typed `... | None`. Pre-Phase-3a rows have NULL
`calibration_status` (see backwards-compat test in
`test_pgs_scores_calibration_columns.py:147-184`); a non-optional Pydantic
field would 500 every legacy row read through `/v1/pgs/computed`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, DeclineReason
from genomeclaw_toolkit.schemas.pgs import PgsListRow, PgsRowResponse

_GET_KWARGS = {
    "pgs_id": "PGS000099",
    "trait_label": "test trait",
    "percentile_in_user_ancestry": 55.0,
    "raw_score": 0.123,
    "source_pgs_id": "PGS000099",
    "study_population": "European",
    "calibration_warning": None,
    "agent_choice_rationale": "Testing purposes only, not a real analysis.",
    "requested_for_question": "test question",
    "superseded_by": None,
}

_LIST_KWARGS = {
    "pgs_id": "PGS000099",
    "trait_label": "test trait",
    "percentile_in_user_ancestry": 55.0,
    "calibration_warning": None,
    "superseded_by": None,
}


def test_pgs_row_response_includes_calibration_status_clean() -> None:
    """`PgsRowResponse` accepts `calibration_status='clean'`; serializes as the string."""
    row = PgsRowResponse(
        **_GET_KWARGS,
        calibration_status=CalibrationStatus.CLEAN,
        decline_reason=None,
    )
    data = row.model_dump(mode="json")
    assert data["calibration_status"] == "clean"
    assert data["decline_reason"] is None


def test_pgs_row_response_includes_calibration_status_decline() -> None:
    """`PgsRowResponse` accepts DECLINE + a structural decline_reason; both serialize."""
    row = PgsRowResponse(
        **_GET_KWARGS,
        calibration_status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
    )
    data = row.model_dump(mode="json")
    assert data["calibration_status"] == "decline"
    assert data["decline_reason"] == "variant_overlap_insufficient"


def test_pgs_row_response_accepts_null_calibration_status() -> None:
    """Pre-Phase-3a rows have NULL calibration_status; the model must accept None.

    The pipeline writer at `prep/pgs.py:812` persists `row.calibration_status`
    as-is, which can be None for any PgsRow constructed via the pre-Phase-3b1
    8-field surface. A non-optional field would 500 every such row.
    """
    row = PgsRowResponse(
        **_GET_KWARGS,
        calibration_status=None,
        decline_reason=None,
    )
    data = row.model_dump(mode="json")
    assert data["calibration_status"] is None
    assert data["decline_reason"] is None


def test_pgs_row_response_rejects_unknown_field() -> None:
    """`extra="forbid"` still blocks unknown fields after widening (INV-P002 floor)."""
    with pytest.raises(ValidationError):
        PgsRowResponse(
            **_GET_KWARGS,
            calibration_status=CalibrationStatus.CLEAN,
            decline_reason=None,
            rogue_field="x",
        )


def test_pgs_row_response_accepts_string_values_from_db() -> None:
    """DuckDB returns column values as plain strings; Pydantic must coerce them."""
    row = PgsRowResponse(
        **_GET_KWARGS,
        calibration_status="decline",
        decline_reason="variant_overlap_insufficient",
    )
    assert row.calibration_status == CalibrationStatus.DECLINE
    assert row.decline_reason == DeclineReason.VARIANT_OVERLAP_INSUFFICIENT


def test_pgs_row_response_rejects_invalid_calibration_status_string() -> None:
    """An unknown string for calibration_status must raise — guards against typos."""
    with pytest.raises(ValidationError):
        PgsRowResponse(
            **_GET_KWARGS,
            calibration_status="declined",  # typo
            decline_reason=None,
        )


def test_pgs_row_response_rejects_invalid_decline_reason_string() -> None:
    """An unknown decline_reason value must raise."""
    with pytest.raises(ValidationError):
        PgsRowResponse(
            **_GET_KWARGS,
            calibration_status=CalibrationStatus.DECLINE,
            decline_reason="not_a_real_reason",
        )


def test_pgs_list_row_includes_calibration_status_warning() -> None:
    """`PgsListRow` carries `calibration_status` so the agent can filter without _get."""
    row = PgsListRow(
        **_LIST_KWARGS,
        calibration_status=CalibrationStatus.WARNING,
        decline_reason=None,
    )
    data = row.model_dump(mode="json")
    assert data["calibration_status"] == "warning"
    assert data["decline_reason"] is None


def test_pgs_list_row_includes_decline_reason() -> None:
    """`PgsListRow` carries `decline_reason` (resolved Q1: include both, not status-only)."""
    row = PgsListRow(
        **_LIST_KWARGS,
        calibration_status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.POPULATION_TRANSFERABILITY_INSUFFICIENT,
    )
    data = row.model_dump(mode="json")
    assert data["calibration_status"] == "decline"
    assert data["decline_reason"] == "population_transferability_insufficient"


def test_pgs_list_row_accepts_null_calibration_status() -> None:
    """Pre-Phase-3a list rows also have NULL calibration_status."""
    row = PgsListRow(
        **_LIST_KWARGS,
        calibration_status=None,
        decline_reason=None,
    )
    data = row.model_dump(mode="json")
    assert data["calibration_status"] is None


def test_pgs_list_row_rejects_unknown_field() -> None:
    """`extra="forbid"` still blocks unknown fields on the list row."""
    with pytest.raises(ValidationError):
        PgsListRow(
            **_LIST_KWARGS,
            calibration_status=CalibrationStatus.CLEAN,
            decline_reason=None,
            rogue_field="x",
        )


def test_invE001_pgs_decline_signal_not_stripped() -> None:
    """INV-E001: a DECLINE row's status survives Pydantic round-trip.

    Guards against a future serializer change that accidentally strips
    `calibration_status` and lets the agent pattern-match a free-text
    `calibration_warning` to infer a decline — which is the gap this
    plan exists to close.
    """
    row = PgsRowResponse(
        **_GET_KWARGS,
        calibration_status=CalibrationStatus.DECLINE,
        decline_reason=DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN,
    )
    assert row.calibration_status == CalibrationStatus.DECLINE
    assert row.decline_reason == DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN

    # Round-trip through serialization → re-construction (mimics HTTP → agent flow).
    payload = row.model_dump(mode="json")
    rehydrated = PgsRowResponse(**payload)
    assert rehydrated.calibration_status == CalibrationStatus.DECLINE
    assert rehydrated.decline_reason == DeclineReason.ANCESTRY_CALIBRATION_UNCERTAIN

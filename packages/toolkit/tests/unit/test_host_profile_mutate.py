"""Phase 2 (host-profile-personal-context) — dotted-path ``apply_set`` tests."""

from __future__ import annotations

import pytest

from genomeclaw_toolkit.host_profile.mutate import HostProfileFieldError, apply_set
from genomeclaw_toolkit.schemas.host_profile import HostProfile

_META = {"created_at": "2026-05-31T00:00:00Z", "updated_at": "2026-05-31T00:00:00Z"}


def _profile() -> HostProfile:
    return HostProfile.model_validate(
        {"schema_version": "host_profile/1.0", "meta": dict(_META), "identity": {}}
    )


def test_apply_set_scalar_field() -> None:
    """A scalar dotted path sets exactly that field."""
    updated = apply_set(_profile(), "lifestyle.smoking_status", "never")
    assert updated.lifestyle.smoking_status == "never"


def test_apply_set_numeric_field_coerces_json_scalar() -> None:
    """A numeric value is JSON-coerced, not stored as a string."""
    updated = apply_set(_profile(), "biometrics.height_cm", "195")
    assert updated.biometrics.height_cm == 195.0


def test_apply_set_list_add_appends_one_element() -> None:
    """A ``<list>.add`` path appends one validated element."""
    updated = apply_set(
        _profile(), "medical_history.medications.add", '{"name": "clopidogrel"}'
    )
    assert [m.name for m in updated.medical_history.medications] == ["clopidogrel"]


def test_apply_set_rejects_unknown_path() -> None:
    """An unknown dotted path raises a typed field error."""
    with pytest.raises(HostProfileFieldError):
        apply_set(_profile(), "medical_history.dragons", "x")


def test_apply_set_rejects_invalid_enum_value() -> None:
    """A value that fails schema validation raises a typed field error."""
    with pytest.raises(HostProfileFieldError):
        apply_set(_profile(), "lifestyle.smoking_status", "occasionally")


def test_apply_set_add_requires_json_object() -> None:
    """``<list>.add`` with a non-object value is rejected."""
    with pytest.raises(HostProfileFieldError):
        apply_set(_profile(), "medical_history.medications.add", "clopidogrel")

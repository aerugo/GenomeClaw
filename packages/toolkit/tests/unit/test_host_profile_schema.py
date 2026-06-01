"""Phase 1 (host-profile-personal-context) — `HostProfile` schema tests.

These pin the typed shape of the host-side personal-context profile: a
single JSON document living at ``<derived_root>/host_profile.json`` that
the agent retrieves before any genome-informable turn. The schema is the
structural backbone of three invariants:

- ``INV-R001`` — ``schema_version`` is a pinned ``Literal`` so future
  migrations are mechanical (``migrate_host_profile()`` is the seam).
- ``INV-C002`` (prep) — every model carries ``extra="forbid"`` so the
  Phase-2 CLI envelope can compose them without payload drift.
- The self-report-vs-clinical distinction (``INV-E001`` / ``INV-C001``)
  is made structural: ``meta.source`` is the literal ``"self_report"``
  and ancestry/family-history fields are bounded free-text, never a
  structured per-relative list the agent could over-read as a record.

Bare-host venv tests — no bio binaries, no network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genomeclaw_toolkit.schemas.host_profile import (
    ANCESTRY_GROUP_TO_POP1000G,
    Ancestry,
    HostProfile,
    migrate_host_profile,
)

# Minimal building blocks reused across cases. ``meta`` requires the two
# timestamps; everything else on a minimal profile defaults.
_MINIMAL_META = {
    "created_at": "2026-05-31T00:00:00Z",
    "updated_at": "2026-05-31T00:00:00Z",
}
_MINIMAL_IDENTITY: dict = {}


def _minimal_payload(**overrides) -> dict:
    payload = {
        "schema_version": "host_profile/1.0",
        "meta": dict(_MINIMAL_META),
        "identity": dict(_MINIMAL_IDENTITY),
    }
    payload.update(overrides)
    return payload


def test_host_profile_minimal_valid_payload_parses() -> None:
    """A minimal profile (identity-only + meta) parses cleanly."""
    profile = HostProfile.model_validate(_minimal_payload())
    assert profile.schema_version == "host_profile/1.0"
    assert profile.meta.source == "self_report"


def test_host_profile_rejects_unknown_top_level_field() -> None:
    """``extra="forbid"`` rejects an unmodelled top-level key."""
    with pytest.raises(ValidationError):
        HostProfile.model_validate(_minimal_payload(weight_in_pounds=180))


def test_host_profile_rejects_unknown_section_field() -> None:
    """Section sub-models also reject unknown keys."""
    payload = _minimal_payload()
    payload["biometrics"] = {"height_cm": 195.0, "favourite_colour": "blue"}
    with pytest.raises(ValidationError):
        HostProfile.model_validate(payload)


def test_invR001_host_profile_schema_version_literal() -> None:
    """INV-R001: schema_version is pinned so future migrations are mechanical."""
    with pytest.raises(ValidationError):
        HostProfile.model_validate(_minimal_payload(schema_version="host_profile/0.9"))
    # The pinned literal validates.
    HostProfile.model_validate(_minimal_payload(schema_version="host_profile/1.0"))


def test_host_profile_identity_sex_assigned_at_birth_enum() -> None:
    """Only the four enum values are accepted for ``sex_assigned_at_birth``."""
    for value in ("female", "male", "intersex", "prefer_not_to_say"):
        payload = _minimal_payload()
        payload["identity"] = {"sex_assigned_at_birth": value}
        HostProfile.model_validate(payload)
    bad = _minimal_payload()
    bad["identity"] = {"sex_assigned_at_birth": "yes"}
    with pytest.raises(ValidationError):
        HostProfile.model_validate(bad)


def test_host_profile_lifestyle_smoking_status_enum() -> None:
    """Only ``{never, former, current, prefer_not_to_say}`` for smoking."""
    for value in ("never", "former", "current", "prefer_not_to_say"):
        payload = _minimal_payload()
        payload["lifestyle"] = {"smoking_status": value}
        HostProfile.model_validate(payload)
    bad = _minimal_payload()
    bad["lifestyle"] = {"smoking_status": "occasionally"}
    with pytest.raises(ValidationError):
        HostProfile.model_validate(bad)


def test_host_profile_freetext_max_length_enforced() -> None:
    """Condition notes > 2000 chars and family-history notes > 4000 raise."""
    long_note = _minimal_payload()
    long_note["medical_history"] = {
        "conditions": [{"name": "reflux", "notes": "x" * 2001}]
    }
    with pytest.raises(ValidationError):
        HostProfile.model_validate(long_note)

    long_family = _minimal_payload()
    long_family["family_history"] = {"notes": "y" * 4001}
    with pytest.raises(ValidationError):
        HostProfile.model_validate(long_family)

    # The boundary values are accepted.
    ok = _minimal_payload()
    ok["medical_history"] = {"conditions": [{"name": "reflux", "notes": "x" * 2000}]}
    ok["family_history"] = {"notes": "y" * 4000}
    HostProfile.model_validate(ok)


def test_host_profile_ancestry_groups_validates_friendly_enum() -> None:
    """Ancestry groups accept the nine friendly values; reject raw codes / garbage."""
    friendly = [
        "european",
        "african",
        "east_asian",
        "south_asian",
        "american_indigenous_latino",
        "middle_eastern_north_african",
        "oceanian",
        "mixed_or_unsure",
        "prefer_not_to_say",
    ]
    payload = _minimal_payload()
    payload["identity"] = {"ancestry": {"groups": friendly}}
    HostProfile.model_validate(payload)

    for bad_value in ("EUR", "viking"):
        bad = _minimal_payload()
        bad["identity"] = {"ancestry": {"groups": [bad_value]}}
        with pytest.raises(ValidationError):
            HostProfile.model_validate(bad)


def test_host_profile_ancestry_group_maps_to_pop1000g() -> None:
    """``groups`` deterministically derives ``population_codes`` at validation time."""
    ancestry = Ancestry.model_validate({"groups": ["european", "east_asian"]})
    assert ancestry.population_codes == ["EUR", "EAS"]

    declined = Ancestry.model_validate({"groups": ["prefer_not_to_say"]})
    assert declined.population_codes == []

    # The exported mapping is the single source of truth for the derivation.
    assert ANCESTRY_GROUP_TO_POP1000G["european"] == "EUR"
    assert ANCESTRY_GROUP_TO_POP1000G["mixed_or_unsure"] == "ADM"
    assert ANCESTRY_GROUP_TO_POP1000G["prefer_not_to_say"] is None


def test_host_profile_ancestry_self_reported_freetext_bound() -> None:
    """``self_reported`` is bounded at 500 chars; ``None`` is valid."""
    Ancestry.model_validate({"self_reported": None})
    Ancestry.model_validate({"self_reported": "z" * 500})
    with pytest.raises(ValidationError):
        Ancestry.model_validate({"self_reported": "z" * 501})


def test_host_profile_family_history_is_freetext_not_list() -> None:
    """Family history is ``{notes, opted_out}`` — passing the old list shape raises."""
    bad = _minimal_payload()
    bad["family_history"] = [{"relation": "mother", "condition": "T2D"}]
    with pytest.raises(ValidationError):
        HostProfile.model_validate(bad)

    ok = _minimal_payload()
    ok["family_history"] = {"notes": "mother had T2D in her 50s", "opted_out": False}
    profile = HostProfile.model_validate(ok)
    assert profile.family_history.opted_out is False


def test_host_profile_no_goals_section_at_v1_0() -> None:
    """A ``goals`` section was considered and dropped; ``extra="forbid"`` rejects it."""
    with pytest.raises(ValidationError):
        HostProfile.model_validate(_minimal_payload(goals={"primary": "longevity"}))


def test_host_profile_migrate_v1_0_identity() -> None:
    """``migrate_host_profile`` returns a v1.0 dict unchanged and valid."""
    payload = _minimal_payload()
    migrated = migrate_host_profile(payload)
    assert migrated == payload
    # The migrated dict still validates.
    HostProfile.model_validate(migrated)

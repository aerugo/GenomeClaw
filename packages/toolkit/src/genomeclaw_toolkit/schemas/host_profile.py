"""Typed schema for the host-side personal-context profile.

The profile is a single JSON document at ``<derived_root>/host_profile.json``
(see development-plan Decision 1 — JSON on disk, not a DuckDB row). The
agent retrieves it before any genome-informable turn so its reasoning is
anchored to the user's self-reported identity / biometrics / lifestyle /
medical / family context.

Three structural commitments live in this module:

- ``INV-R001`` — ``schema_version`` is a pinned ``Literal`` and
  :func:`migrate_host_profile` is the migration seam, present from v1.0
  so future bumps are mechanical rather than ad-hoc.
- ``INV-C002`` (prep) — every model is ``extra="forbid"`` so a future
  CLI/tool envelope that widens a payload surfaces at construction time.
- The self-report-vs-clinical-record distinction (``INV-E001`` /
  ``INV-C001``) is structural: ``meta.source`` is the literal
  ``"self_report"``; ancestry and family history are bounded free-text,
  never a structured per-relative list the agent might over-read as a
  clinical record.

The friendly ancestry enum (user-facing groups) maps to 1000-Genomes
super-population codes for downstream PRS-calibration consumption. The
user is never asked to know what ``EUR`` / ``EAS`` mean.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: str = "host_profile/1.0"
"""The pinned host-profile schema version (``INV-R001``)."""


# ---------------------------------------------------------------------------
# Enums. Each is a ``str`` subclass so values serialize as plain strings in
# the JSON document and round-trip through the audit log without coercion.
# ---------------------------------------------------------------------------


class SexAssignedAtBirth(StrEnum):
    """Sex assigned at birth — relevant for sex-linked variant interpretation."""

    female = "female"
    male = "male"
    intersex = "intersex"
    prefer_not_to_say = "prefer_not_to_say"


class SmokingStatus(StrEnum):
    """Self-reported smoking status — a lifestyle modifier for several PRS traits."""

    never = "never"
    former = "former"
    current = "current"
    prefer_not_to_say = "prefer_not_to_say"


class AlcoholUse(StrEnum):
    """Self-reported alcohol-use frequency band."""

    none = "none"
    rarely = "rarely"
    weekly = "weekly"
    daily = "daily"
    prefer_not_to_say = "prefer_not_to_say"


class ExerciseFrequency(StrEnum):
    """Self-reported habitual physical-activity band."""

    sedentary = "sedentary"
    light = "light"
    moderate = "moderate"
    vigorous = "vigorous"
    prefer_not_to_say = "prefer_not_to_say"


class BloodType(StrEnum):
    """ABO/Rh blood type (self-reported)."""

    a_pos = "A+"
    a_neg = "A-"
    b_pos = "B+"
    b_neg = "B-"
    ab_pos = "AB+"
    ab_neg = "AB-"
    o_pos = "O+"
    o_neg = "O-"
    unknown = "unknown"


class AncestryGroup(StrEnum):
    """User-facing reference-population groups for the friendly ancestry multi-select.

    These are plain-language groupings, NOT identity / race / nationality
    labels. They exist so a non-expert user can describe their reference
    populations for PRS calibration without being asked to know 1000G
    super-population codes.
    """

    european = "european"
    african = "african"
    east_asian = "east_asian"
    south_asian = "south_asian"
    american_indigenous_latino = "american_indigenous_latino"
    middle_eastern_north_african = "middle_eastern_north_african"
    oceanian = "oceanian"
    mixed_or_unsure = "mixed_or_unsure"
    prefer_not_to_say = "prefer_not_to_say"


class Pop1000G(StrEnum):
    """1000-Genomes / HGDP super-population codes consumed by PRS calibration."""

    EUR = "EUR"
    AFR = "AFR"
    EAS = "EAS"
    SAS = "SAS"
    AMR = "AMR"
    MID = "MID"
    OCE = "OCE"
    ADM = "ADM"


ANCESTRY_GROUP_TO_POP1000G: dict[AncestryGroup, Pop1000G | None] = {
    AncestryGroup.european: Pop1000G.EUR,
    AncestryGroup.african: Pop1000G.AFR,
    AncestryGroup.east_asian: Pop1000G.EAS,
    AncestryGroup.south_asian: Pop1000G.SAS,
    AncestryGroup.american_indigenous_latino: Pop1000G.AMR,
    AncestryGroup.middle_eastern_north_african: Pop1000G.MID,
    AncestryGroup.oceanian: Pop1000G.OCE,
    AncestryGroup.mixed_or_unsure: Pop1000G.ADM,
    AncestryGroup.prefer_not_to_say: None,
}
"""Single source of truth for the friendly-group → 1000G-code derivation.

``prefer_not_to_say`` maps to ``None`` (no code persisted). The mapping is
exercised by ``test_host_profile_ancestry_group_maps_to_pop1000g``.
"""

# Dotted paths whose values are user free-text. The audit log records their
# *lengths only*, never their verbatim values (privacy floor). The store /
# audit layer reads this constant rather than re-deriving the set.
FREETEXT_PATHS: frozenset[str] = frozenset(
    {
        "identity.gender_identity",
        "identity.ancestry.self_reported",
        "lifestyle.dietary_pattern",
        "lifestyle.sleep_pattern",
        "family_history.notes",
    }
)

# A subset of FREETEXT_PATHS that may narrate identifiable family members.
# These carry the strictest privacy floor (``INV-P001`` / ``INV-C001``):
# never verbatim, and the agent paraphrases at relation-class granularity.
FAMILY_MEMBER_NARRATIVE_PATHS: frozenset[str] = frozenset({"family_history.notes"})


# ---------------------------------------------------------------------------
# Section sub-models.
# ---------------------------------------------------------------------------


class Meta(BaseModel):
    """Profile-level provenance + lifecycle timestamps.

    ``source`` is the literal ``"self_report"`` at v1.0 — the structural
    anchor for the agent's self-reported-vs-clinical-record discipline.
    """

    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    updated_at: datetime
    last_full_review_at: datetime | None = None
    skipped_init_at: datetime | None = None
    source: Literal["self_report"] = "self_report"


class Ancestry(BaseModel):
    """Two-layer ancestry capture: free-text narrative + friendly group codes.

    ``population_codes`` is *derived* from ``groups`` at validation time via
    :meth:`_derive_population_codes` and persisted for PRS-calibration
    consumption; any value supplied by the caller is recomputed, so the
    mapping in :data:`ANCESTRY_GROUP_TO_POP1000G` is the only source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    self_reported: str | None = Field(default=None, max_length=500)
    groups: list[AncestryGroup] = Field(default_factory=list)
    population_codes: list[Pop1000G] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_population_codes(self) -> Ancestry:
        """Recompute ``population_codes`` from ``groups`` (single source of truth)."""
        derived: list[Pop1000G] = []
        for group in self.groups:
            code = ANCESTRY_GROUP_TO_POP1000G.get(group)
            if code is not None and code not in derived:
                derived.append(code)
        self.population_codes = derived
        return self


class Identity(BaseModel):
    """Core identity fields informing sex-linked + ancestry-aware interpretation."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=200)
    date_of_birth: date | None = None
    sex_assigned_at_birth: SexAssignedAtBirth = SexAssignedAtBirth.prefer_not_to_say
    gender_identity: str | None = Field(default=None, max_length=200)
    ancestry: Ancestry = Field(default_factory=Ancestry)


class Biometrics(BaseModel):
    """Anthropometric measurements (self-reported)."""

    model_config = ConfigDict(extra="forbid")

    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    weight_recorded_at: datetime | None = None
    blood_type: BloodType | None = None


class Lifestyle(BaseModel):
    """Self-reported lifestyle modifiers relevant to several trait interpretations."""

    model_config = ConfigDict(extra="forbid")

    smoking_status: SmokingStatus = SmokingStatus.prefer_not_to_say
    alcohol_use: AlcoholUse = AlcoholUse.prefer_not_to_say
    exercise_frequency: ExerciseFrequency = ExerciseFrequency.prefer_not_to_say
    dietary_pattern: str | None = Field(default=None, max_length=200)
    sleep_pattern: str | None = Field(default=None, max_length=200)


class Condition(BaseModel):
    """One self-reported medical condition."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    status: Literal["active", "resolved", "unknown"] = "unknown"
    notes: str | None = Field(default=None, max_length=2000)


class Medication(BaseModel):
    """One self-reported medication.

    The sentinel ``name="none_declared"`` is how a user actively records
    "no medications" — distinct from never having answered the question
    (the completeness rule keys off this; see :data:`_COMPLETENESS_RULES`).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    dose: str | None = Field(default=None, max_length=200)
    indication: str | None = Field(default=None, max_length=200)


class Allergy(BaseModel):
    """One self-reported allergy / intolerance."""

    model_config = ConfigDict(extra="forbid")

    substance: str = Field(min_length=1, max_length=200)
    reaction: str | None = Field(default=None, max_length=200)


class Procedure(BaseModel):
    """One self-reported procedure / surgery."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=1900, le=2100)


class MedicalHistory(BaseModel):
    """Self-reported medical history as four parallel lists."""

    model_config = ConfigDict(extra="forbid")

    conditions: list[Condition] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    procedures: list[Procedure] = Field(default_factory=list)


class FamilyHistory(BaseModel):
    """Family history as a single bounded free-text field (development-plan Decision 10).

    A structured per-relative list was considered and dropped — it added
    onboarding friction and invited the agent to over-read self-report as
    a clinical pedigree. ``notes`` is a ``family_member_narrative`` field
    (see :data:`FAMILY_MEMBER_NARRATIVE_PATHS`): the audit log never stores
    it verbatim.
    """

    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=4000)
    opted_out: bool = False


class HostProfile(BaseModel):
    """The complete host-side personal-context profile (v1.0)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["host_profile/1.0"] = "host_profile/1.0"
    meta: Meta
    identity: Identity
    biometrics: Biometrics = Field(default_factory=Biometrics)
    lifestyle: Lifestyle = Field(default_factory=Lifestyle)
    medical_history: MedicalHistory = Field(default_factory=MedicalHistory)
    family_history: FamilyHistory = Field(default_factory=FamilyHistory)


# ---------------------------------------------------------------------------
# Completeness rule — table-driven, deterministic. ``complete`` / ``partial``
# / ``missing`` per section. The same rule backs both the store's
# ``compute_completeness`` and the service's completeness endpoint.
# ---------------------------------------------------------------------------

CompletenessStatus = Literal["complete", "partial", "missing"]


def _identity_completeness(p: HostProfile) -> CompletenessStatus:
    signals = [
        p.identity.sex_assigned_at_birth != SexAssignedAtBirth.prefer_not_to_say,
        p.identity.date_of_birth is not None,
        bool(p.identity.ancestry.groups),
    ]
    return _band(signals)


def _biometrics_completeness(p: HostProfile) -> CompletenessStatus:
    return _band([p.biometrics.height_cm is not None, p.biometrics.weight_kg is not None])


def _lifestyle_completeness(p: HostProfile) -> CompletenessStatus:
    signals = [
        p.lifestyle.smoking_status != SmokingStatus.prefer_not_to_say,
        p.lifestyle.alcohol_use != AlcoholUse.prefer_not_to_say,
        p.lifestyle.exercise_frequency != ExerciseFrequency.prefer_not_to_say,
    ]
    return _band(signals)


def _family_history_completeness(p: HostProfile) -> CompletenessStatus:
    # A declared opt-out or any narrative counts as actively answered.
    if p.family_history.opted_out or p.family_history.notes:
        return "complete"
    return "missing"


def _list_completeness(items: list[Any]) -> CompletenessStatus:
    # List sections are binary: a non-empty list (including the
    # ``none_declared`` sentinel) is an active answer; empty is unanswered.
    return "complete" if items else "missing"


def _band(signals: list[bool]) -> CompletenessStatus:
    """Map a set of presence-signals to complete / partial / missing."""
    present = sum(1 for s in signals if s)
    if present == 0:
        return "missing"
    if present == len(signals):
        return "complete"
    return "partial"


_COMPLETENESS_RULES: dict[str, Any] = {
    "identity": _identity_completeness,
    "biometrics": _biometrics_completeness,
    "lifestyle": _lifestyle_completeness,
    "medical_history.conditions": lambda p: _list_completeness(p.medical_history.conditions),
    "medical_history.medications": lambda p: _list_completeness(p.medical_history.medications),
    "medical_history.allergies": lambda p: _list_completeness(p.medical_history.allergies),
    "medical_history.procedures": lambda p: _list_completeness(p.medical_history.procedures),
    "family_history": _family_history_completeness,
}


def compute_completeness_map(profile: HostProfile) -> dict[str, CompletenessStatus]:
    """Return the deterministic per-section completeness map for a profile."""
    return {section: rule(profile) for section, rule in _COMPLETENESS_RULES.items()}


# ---------------------------------------------------------------------------
# Migration seam.
# ---------------------------------------------------------------------------


def migrate_host_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate a host-profile dict to the current schema version.

    At v1.0 this is an identity transform that confirms the dict is a
    known version and validates. It exists from day one (``INV-R001``) so
    a future schema bump adds a branch here rather than scattering
    migration logic across the store.

    Raises:
        ValueError: if ``schema_version`` is missing or unknown.
    """
    version = data.get("schema_version")
    if version == "host_profile/1.0":
        return data
    raise ValueError(f"unknown host_profile schema_version: {version!r}")


# ---------------------------------------------------------------------------
# Response models for the two read-only host-service routes (Phase 1).
# ---------------------------------------------------------------------------


class CompletenessMeta(BaseModel):
    """The lifecycle timestamps surfaced by the completeness endpoint."""

    model_config = ConfigDict(extra="forbid")

    updated_at: datetime
    last_full_review_at: datetime | None = None


class HostProfileResponse(BaseModel):
    """``GET /v1/host/profile`` response body.

    ``profile`` is carried as a plain dict (already validated through
    :class:`HostProfile` at read time) because the ``?sections=`` filter
    returns a *subset* of the profile shape that the full model could not
    represent. The strict typed gate is enforced upstream at parse time;
    this wrapper's own ``extra="forbid"`` guards against the response
    surface itself widening (``INV-P002``).
    """

    model_config = ConfigDict(extra="forbid")

    profile: dict[str, Any] | None
    missing: bool
    completeness: dict[str, str] | None = None
    init_command: str | None = None


class HostProfileCompletenessResponse(BaseModel):
    """``GET /v1/host/profile/completeness`` response body — the section map only."""

    model_config = ConfigDict(extra="forbid")

    sections: dict[str, str] | None
    missing: bool
    meta: CompletenessMeta | None = None


class HostProfileErrorResponse(BaseModel):
    """Structured error body for the host-profile routes (corrupt / schema-unknown)."""

    model_config = ConfigDict(extra="forbid")

    error: Literal["host_profile_corrupted", "host_profile_schema_unknown"]
    detail: str


class HostProfileUnknownSectionResponse(BaseModel):
    """400 body when ``?sections=`` names a section the schema does not define."""

    model_config = ConfigDict(extra="forbid")

    error: Literal["host_profile_unknown_section"] = "host_profile_unknown_section"
    section: str
    known_sections: list[str]


__all__ = [
    "ANCESTRY_GROUP_TO_POP1000G",
    "FAMILY_MEMBER_NARRATIVE_PATHS",
    "FREETEXT_PATHS",
    "SCHEMA_VERSION",
    "AlcoholUse",
    "Allergy",
    "Ancestry",
    "AncestryGroup",
    "Biometrics",
    "BloodType",
    "CompletenessMeta",
    "CompletenessStatus",
    "Condition",
    "ExerciseFrequency",
    "FamilyHistory",
    "HostProfile",
    "HostProfileCompletenessResponse",
    "HostProfileErrorResponse",
    "HostProfileResponse",
    "HostProfileUnknownSectionResponse",
    "Identity",
    "Lifestyle",
    "MedicalHistory",
    "Medication",
    "Meta",
    "Pop1000G",
    "Procedure",
    "SexAssignedAtBirth",
    "SmokingStatus",
    "compute_completeness_map",
    "migrate_host_profile",
]

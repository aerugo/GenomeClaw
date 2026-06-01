"""Interactive (Questionary-driven) host-profile authoring.

``host profile init`` and ``host profile edit`` walk the user through the
profile sections with arrow-key single-select, space-bar multi-select,
and validated free-text input. The prompt layer is abstracted behind the
:class:`Prompter` protocol so the walk logic is testable with a
:class:`ScriptedPrompter` (no TTY, no Questionary event loop) while
production binds :class:`QuestionaryPrompter`.

Every prompt carries a stable ``key`` (e.g. ``identity.sex_assigned_at_birth``)
so scripted tests answer by field rather than by call order — the walk
can be reordered without rewriting tests.

The ancestry sub-flow is deliberately two prompts (free-text narrative +
friendly group multi-select) to dissolve mixed-ancestry blank-page
hesitation; the group multi-select is framed around PRS calibration, not
identity. Family history is a single bounded free-text field with an
``$EDITOR`` / inline / skip / opt-out chooser (development-plan
Decisions 10 + 12).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from genomeclaw_toolkit.schemas.host_profile import (
    AlcoholUse,
    AncestryGroup,
    BloodType,
    ExerciseFrequency,
    HostProfile,
    Meta,
    SexAssignedAtBirth,
    SmokingStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

# Family-history $EDITOR scaffold. Comment lines (``#``-prefixed) prompt
# the user; they are stripped before the narrative is persisted.
FAMILY_HISTORY_SCAFFOLD = """\
# Family history — write your free-text below. Delete this whole
# scaffold and replace with your own narrative if you prefer.
# All lines starting with '#' are comments and will be removed
# before saving.
#
# Parents — any heart disease, cancer, diabetes, dementia,
# autoimmune, mental-health, or other notable conditions?
# Age at onset / age at death if known.
#
# Siblings and children — anything similar?
#
# Grandparents — what did they die of? Conditions that ran on
# either side?
#
# Aunts / uncles / cousins — anything that stuck out?
#
# Anyone with a confirmed genetic diagnosis?
#
# Lines below this point are saved into your profile.
"""

# One-line descriptions shown beside each friendly ancestry group.
_ANCESTRY_GROUP_DESCRIPTIONS: dict[AncestryGroup, str] = {
    AncestryGroup.european: "Most European countries, Iceland, Ashkenazi & N. African Jewish",
    AncestryGroup.african: "Sub-Saharan African, African-American, Afro-Caribbean",
    AncestryGroup.east_asian: "China, Korea, Japan, Mongolia, Vietnam",
    AncestryGroup.south_asian: "India, Pakistan, Bangladesh, Sri Lanka, Nepal",
    AncestryGroup.american_indigenous_latino: "Mexican, Central/South American Indigenous, Latino",
    AncestryGroup.middle_eastern_north_african: "Arabian Peninsula, Levant, Iran, Turkey, N.Africa",
    AncestryGroup.oceanian: "Pacific Islander, Aboriginal Australian, Papuan",
    AncestryGroup.mixed_or_unsure: "Significant ancestry from 3+ groups, or unknown",
    AncestryGroup.prefer_not_to_say: "Decline to specify",
}


class Prompter(Protocol):
    """Abstraction over the interactive prompt backend (Questionary in prod)."""

    def select(  # noqa: D102
        self, *, key: str, message: str, choices: Sequence[str], default: str | None = None
    ) -> str: ...

    def text(  # noqa: D102
        self, *, key: str, message: str, default: str = "", multiline: bool = False
    ) -> str: ...

    def checkbox(  # noqa: D102
        self, *, key: str, message: str, choices: Sequence[tuple[str, str]]
    ) -> list[str]: ...

    def confirm(self, *, key: str, message: str, default: bool = False) -> bool: ...  # noqa: D102

    def editor(self, *, key: str, scaffold: str) -> str | None: ...  # noqa: D102


class ScriptedPrompter:
    """A :class:`Prompter` that returns queued answers keyed by prompt ``key``.

    Unspecified keys fall back to a safe default (the prompt's ``default``
    / first choice for selects, ``""`` for text, ``[]`` for checkboxes,
    ``False`` for confirms, ``None`` for editors), so a test specifies
    only the fields it cares about and the rest of the walk runs to a
    clean, minimal profile. ``message`` / ``choices`` / ``multiline`` are
    part of the :class:`Prompter` contract but unused by the scripted
    backend (answers are addressed by ``key``).
    """

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        """Store the keyed answer map (empty → every prompt takes its default)."""
        self._answers = answers or {}

    def select(
        self, *, key: str, message: str, choices: Sequence[str], default: str | None = None
    ) -> str:
        """Return the scripted answer for ``key`` (else ``default`` / first choice)."""
        value = self._answers.get(key)
        if value is None:
            return default if default is not None else choices[0]
        return str(value)

    def text(
        self, *, key: str, message: str, default: str = "", multiline: bool = False
    ) -> str:
        """Return the scripted text answer for ``key`` (else ``default``)."""
        return str(self._answers.get(key, default))

    def checkbox(
        self, *, key: str, message: str, choices: Sequence[tuple[str, str]]
    ) -> list[str]:
        """Return the scripted multi-select answer for ``key`` (else ``[]``)."""
        return [str(v) for v in self._answers.get(key, [])]

    def confirm(self, *, key: str, message: str, default: bool = False) -> bool:
        """Return the scripted yes/no answer for ``key`` (else ``default``)."""
        return bool(self._answers.get(key, default))

    def editor(self, *, key: str, scaffold: str) -> str | None:
        """Return the scripted ``$EDITOR`` result for ``key`` (else ``None``)."""
        value = self._answers.get(key)
        return str(value) if value is not None else None


class QuestionaryPrompter:
    """Production :class:`Prompter` binding Questionary + ``click.edit``."""

    def select(
        self, *, key: str, message: str, choices: Sequence[str], default: str | None = None
    ) -> str:
        """Arrow-key single-select via Questionary."""
        import questionary

        result = questionary.select(message, choices=list(choices), default=default).ask()
        if result is None:
            return default if default is not None else choices[0]
        return str(result)

    def text(
        self, *, key: str, message: str, default: str = "", multiline: bool = False
    ) -> str:
        """Validated free-text input via Questionary."""
        import questionary

        result = questionary.text(message, default=default, multiline=multiline).ask()
        return str(result) if result else ""

    def checkbox(
        self, *, key: str, message: str, choices: Sequence[tuple[str, str]]
    ) -> list[str]:
        """Space-bar multi-select via Questionary."""
        import questionary

        rendered = [questionary.Choice(title=label, value=value) for value, label in choices]
        result = questionary.checkbox(message, choices=rendered).ask()
        return [str(v) for v in result] if result else []

    def confirm(self, *, key: str, message: str, default: bool = False) -> bool:
        """Yes/no confirm via Questionary."""
        import questionary

        result = questionary.confirm(message, default=default).ask()
        return default if result is None else bool(result)

    def editor(self, *, key: str, scaffold: str) -> str | None:
        """Open ``$EDITOR`` on ``scaffold`` via ``click.edit``."""
        import click

        return click.edit(scaffold)


def default_prompter() -> Prompter:
    """Return the production Questionary-backed prompter (monkeypatched in tests)."""
    return QuestionaryPrompter()


def strip_scaffold_comments(text: str) -> str:
    """Drop ``#``-prefixed comment lines from an ``$EDITOR`` scaffold result."""
    kept = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(kept).strip()


def _opt_text(value: str) -> str | None:
    """Map an empty interactive text answer to ``None`` (the schema's absent value)."""
    value = value.strip()
    return value or None


def _opt_float(value: str) -> float | None:
    """Parse an optional float; an unparseable/empty answer becomes ``None``."""
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _walk_identity(p: Prompter) -> dict[str, Any]:
    display_name = _opt_text(
        p.text(key="identity.display_name", message="Display name (optional)")
    )
    dob = _opt_text(
        p.text(key="identity.date_of_birth", message="Date of birth (YYYY-MM-DD, optional)")
    )
    sex = p.select(
        key="identity.sex_assigned_at_birth",
        message="Sex assigned at birth",
        choices=[e.value for e in SexAssignedAtBirth],
        default=SexAssignedAtBirth.prefer_not_to_say.value,
    )
    gender = _opt_text(
        p.text(key="identity.gender_identity", message="Gender identity (optional)")
    )

    self_reported = _opt_text(
        p.text(
            key="identity.ancestry.self_reported",
            message="Describe your ancestry in your own words (optional)",
            multiline=True,
        )
    )
    groups = p.checkbox(
        key="identity.ancestry.groups",
        message="Reference population group(s) — for PRS calibration, NOT identity",
        choices=[
            (g.value, f"{g.value} — {desc}") for g, desc in _ANCESTRY_GROUP_DESCRIPTIONS.items()
        ],
    )
    return {
        "display_name": display_name,
        "date_of_birth": dob,
        "sex_assigned_at_birth": sex,
        "gender_identity": gender,
        "ancestry": {"self_reported": self_reported, "groups": groups},
    }


def _walk_biometrics(p: Prompter) -> dict[str, Any]:
    height = _opt_float(p.text(key="biometrics.height_cm", message="Height in cm (optional)"))
    weight = _opt_float(p.text(key="biometrics.weight_kg", message="Weight in kg (optional)"))
    blood = p.select(
        key="biometrics.blood_type",
        message="Blood type",
        choices=[e.value for e in BloodType],
        default=BloodType.unknown.value,
    )
    out: dict[str, Any] = {"height_cm": height, "weight_kg": weight}
    if blood != BloodType.unknown.value:
        out["blood_type"] = blood
    return out


def _walk_lifestyle(p: Prompter) -> dict[str, Any]:
    smoking = p.select(
        key="lifestyle.smoking_status",
        message="Smoking status",
        choices=[e.value for e in SmokingStatus],
        default=SmokingStatus.prefer_not_to_say.value,
    )
    alcohol = p.select(
        key="lifestyle.alcohol_use",
        message="Alcohol use",
        choices=[e.value for e in AlcoholUse],
        default=AlcoholUse.prefer_not_to_say.value,
    )
    exercise = p.select(
        key="lifestyle.exercise_frequency",
        message="Exercise frequency",
        choices=[e.value for e in ExerciseFrequency],
        default=ExerciseFrequency.prefer_not_to_say.value,
    )
    diet = _opt_text(p.text(key="lifestyle.dietary_pattern", message="Dietary pattern (optional)"))
    sleep = _opt_text(p.text(key="lifestyle.sleep_pattern", message="Sleep pattern (optional)"))
    return {
        "smoking_status": smoking,
        "alcohol_use": alcohol,
        "exercise_frequency": exercise,
        "dietary_pattern": diet,
        "sleep_pattern": sleep,
    }


def _walk_list_section(
    p: Prompter, *, section: str, item_message: str, field: str
) -> list[dict[str, Any]]:
    """Generic add-loop: confirm "add another?" then collect one bounded text field."""
    items: list[dict[str, Any]] = []
    index = 0
    while p.confirm(key=f"{section}.add.{index}", message=f"Add {item_message}?", default=False):
        name = _opt_text(
            p.text(key=f"{section}.{index}.{field}", message=f"{item_message} {field}")
        )
        if name:
            items.append({field: name})
        index += 1
    return items


def _walk_medical(p: Prompter) -> dict[str, Any]:
    return {
        "conditions": _walk_list_section(
            p, section="medical.conditions", item_message="a condition", field="name"
        ),
        "medications": _walk_list_section(
            p, section="medical.medications", item_message="a medication", field="name"
        ),
        "allergies": _walk_list_section(
            p, section="medical.allergies", item_message="an allergy", field="substance"
        ),
        "procedures": _walk_list_section(
            p, section="medical.procedures", item_message="a procedure", field="name"
        ),
    }


def _walk_family(p: Prompter) -> dict[str, Any]:
    mode = p.select(
        key="family.entry_mode",
        message="How would you like to record family history?",
        choices=["editor", "inline", "skip", "opt_out"],
        default="skip",
    )
    if mode == "opt_out":
        return {"notes": None, "opted_out": True}
    if mode == "editor":
        edited = p.editor(key="family.notes", scaffold=FAMILY_HISTORY_SCAFFOLD)
        notes = strip_scaffold_comments(edited) if edited else None
        return {"notes": notes or None, "opted_out": False}
    if mode == "inline":
        notes = _opt_text(
            p.text(key="family.notes_inline", message="Family history", multiline=True)
        )
        return {"notes": notes, "opted_out": False}
    return {"notes": None, "opted_out": False}


def build_profile_interactive(
    *,
    now: datetime,
    quick: bool = False,
    prompter: Prompter | None = None,
) -> HostProfile:
    """Walk the profile sections interactively and return a validated profile.

    ``--quick`` captures identity (incl. ancestry) only; the full walk
    adds biometrics, lifestyle, medical history, and family history.
    There is deliberately **no** ``goals`` section (development-plan
    Decision 11). ``now`` is injected (not read from the wall clock) so
    callers control the ``meta`` timestamps.
    """
    p = prompter or default_prompter()
    payload: dict[str, Any] = {
        "schema_version": "host_profile/1.0",
        "meta": Meta(created_at=now, updated_at=now).model_dump(mode="json"),
        "identity": _walk_identity(p),
    }
    if not quick:
        payload["biometrics"] = _walk_biometrics(p)
        payload["lifestyle"] = _walk_lifestyle(p)
        payload["medical_history"] = _walk_medical(p)
        payload["family_history"] = _walk_family(p)
    return HostProfile.model_validate(payload)


__all__ = [
    "FAMILY_HISTORY_SCAFFOLD",
    "Prompter",
    "QuestionaryPrompter",
    "ScriptedPrompter",
    "build_profile_interactive",
    "default_prompter",
    "strip_scaffold_comments",
]

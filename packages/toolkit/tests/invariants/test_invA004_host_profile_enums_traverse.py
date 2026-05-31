"""INV-A004 (pattern reuse) — host-profile enums + sections traverse Python ↔ TypeScript.

The structured enums in ``schemas/host_profile.py`` (sex, smoking, alcohol,
exercise, blood type, ancestry group, 1000G code) and the section allowlist
(``KNOWN_HOST_PROFILE_SECTIONS``) are mirrored in the nemoclaw-plugin's
``index.ts`` — as named TypeBox unions and a ``HOST_PROFILE_SECTIONS``
constant respectively. A value added on one side but not the other is a
cross-language drift bug: the agent's tool would accept a section the host
rejects, or the documented response contract would omit a real enum value.

This is the same discipline as
``test_invA004_decline_taxonomy_traverse.py`` (PGS calibration enums); it
parses the TypeScript source and asserts set-equality against the Python
authority. Host-venv only — it reads two source files.
"""

from __future__ import annotations

import re
from pathlib import Path

from genomeclaw_toolkit.schemas.host_profile import (
    AlcoholUse,
    AncestryGroup,
    BloodType,
    ExerciseFrequency,
    Pop1000G,
    SexAssignedAtBirth,
    SmokingStatus,
)
from genomeclaw_toolkit.service.store import KNOWN_HOST_PROFILE_SECTIONS

_PLUGIN_INDEX = Path(__file__).resolve().parents[3] / "nemoclaw-plugin" / "src" / "index.ts"

# Python enum → the TypeBox union const name expected in index.ts.
_ENUM_TO_UNION: dict[str, tuple[type, str]] = {
    "SexAssignedAtBirth": (SexAssignedAtBirth, "HostProfileSexAssignedAtBirthUnion"),
    "SmokingStatus": (SmokingStatus, "HostProfileSmokingStatusUnion"),
    "AlcoholUse": (AlcoholUse, "HostProfileAlcoholUseUnion"),
    "ExerciseFrequency": (ExerciseFrequency, "HostProfileExerciseFrequencyUnion"),
    "BloodType": (BloodType, "HostProfileBloodTypeUnion"),
    "AncestryGroup": (AncestryGroup, "HostProfileAncestryGroupUnion"),
    "Pop1000G": (Pop1000G, "HostProfilePop1000GUnion"),
}


def _parse_named_union(source: str, union_name: str) -> set[str]:
    """Return the ``Type.Literal("...")`` values in ``const <union_name> = Type.Union([...])``."""
    pattern = rf"const\s+{re.escape(union_name)}\s*=\s*Type\.Union\(\s*\[(.*?)\]\s*\)"
    match = re.search(pattern, source, flags=re.DOTALL)
    if not match:
        return set()
    return set(re.findall(r'Type\.Literal\(\s*"([^"]+)"\s*\)', match.group(1)))


def _parse_string_array_const(source: str, const_name: str) -> set[str]:
    """Return the string members of ``const <const_name> = [ "a", "b", ... ]``."""
    pattern = rf"const\s+{re.escape(const_name)}\b[^=]*=\s*\[(.*?)\]"
    match = re.search(pattern, source, flags=re.DOTALL)
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_invA004_host_profile_enums_python_typescript_diff() -> None:
    """Every Python host-profile enum value appears in its named TypeBox union."""
    source = _PLUGIN_INDEX.read_text()
    drift: list[str] = []
    for label, (enum_cls, union_name) in _ENUM_TO_UNION.items():
        py_values = {member.value for member in enum_cls}
        ts_values = _parse_named_union(source, union_name)
        if py_values != ts_values:
            drift.append(
                f"{label} ({union_name}): py-ts={sorted(py_values - ts_values)}, "
                f"ts-py={sorted(ts_values - py_values)}"
            )
    assert not drift, "INV-A004 host-profile enum drift:\n" + "\n".join(drift)


def test_invA004_host_profile_sections_python_typescript_diff() -> None:
    """The Python section allowlist matches the plugin's HOST_PROFILE_SECTIONS mirror."""
    source = _PLUGIN_INDEX.read_text()
    py_sections = set(KNOWN_HOST_PROFILE_SECTIONS)
    ts_sections = _parse_string_array_const(source, "HOST_PROFILE_SECTIONS")
    assert py_sections == ts_sections, (
        "INV-A004 host-profile section drift:\n"
        f"  py-ts={sorted(py_sections - ts_sections)}\n"
        f"  ts-py={sorted(ts_sections - py_sections)}"
    )

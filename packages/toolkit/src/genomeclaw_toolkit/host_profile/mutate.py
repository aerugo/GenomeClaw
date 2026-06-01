"""Dotted-path mutation of a :class:`HostProfile` for ``host profile set``.

The CLI ``set`` subcommand mutates one field (or appends one list
element) by dotted path, e.g.::

    host profile set identity.display_name "Jane Doe"
    host profile set lifestyle.smoking_status never
    host profile set medical_history.medications.add '{"name": "clopidogrel"}'

Every mutation re-validates the *whole* profile through
:class:`HostProfile` so an out-of-bound free-text value or an unknown
enum surfaces as a typed error rather than a silently-bad write. The
mutation is pure: it returns a new validated ``HostProfile`` and never
touches disk (the store layer owns the atomic write + audit).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from genomeclaw_toolkit.schemas.host_profile import HostProfile

# The four list-typed sub-sections that accept a ``.add`` element append.
_LIST_SECTIONS: dict[str, str] = {
    "medical_history.conditions": "medical_history.conditions",
    "medical_history.medications": "medical_history.medications",
    "medical_history.allergies": "medical_history.allergies",
    "medical_history.procedures": "medical_history.procedures",
}


class HostProfileFieldError(ValueError):
    """A ``host profile set`` path or value is invalid (unknown path / bad value)."""


def _navigate_parent(data: dict[str, Any], parts: list[str]) -> tuple[dict[str, Any], str]:
    """Walk ``data`` to the dict holding the final key; raise on an unknown path."""
    cursor: Any = data
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise HostProfileFieldError(
                f"unknown host_profile field path: {'.'.join(parts)!r}"
            )
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        raise HostProfileFieldError(f"unknown host_profile field path: {'.'.join(parts)!r}")
    return cursor, parts[-1]


def _coerce_scalar(raw_value: str) -> Any:
    """Best-effort coercion of a CLI string into a JSON scalar.

    A value that parses as JSON (number, bool, null, quoted string,
    object) is used as-is; anything else is treated as a bare string.
    This lets ``set ... 195`` write a float and ``set ... never`` write
    the bare enum string without the user quoting every value.
    """
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, ValueError):
        return raw_value


def apply_set(profile: HostProfile, dotted_path: str, raw_value: str) -> HostProfile:
    """Return a new validated profile with ``dotted_path`` set / appended.

    A path ending in ``.add`` appends one JSON-object element to the
    named list section (e.g. ``medical_history.medications.add``). Any
    other path sets a scalar leaf. The whole profile is re-validated, so
    an invalid value raises :class:`HostProfileFieldError`.
    """
    data = profile.model_dump(mode="json")
    parts = dotted_path.split(".")

    if parts[-1] == "add":
        section = ".".join(parts[:-1])
        if section not in _LIST_SECTIONS:
            raise HostProfileFieldError(
                f"{section!r} is not a list section; `.add` is only valid for "
                f"{sorted(_LIST_SECTIONS)}"
            )
        try:
            element = json.loads(raw_value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HostProfileFieldError(
                f"`set {dotted_path}` expects a JSON object value; got {raw_value!r}"
            ) from exc
        if not isinstance(element, dict):
            raise HostProfileFieldError(
                f"`set {dotted_path}` expects a JSON object value; got {type(element).__name__}"
            )
        top, key = section.split(".")
        data[top][key].append(element)
    else:
        parent, key = _navigate_parent(data, parts)
        parent[key] = _coerce_scalar(raw_value)

    try:
        return HostProfile.model_validate(data)
    except ValidationError as exc:
        raise HostProfileFieldError(
            f"value for {dotted_path!r} does not validate against the schema: {exc}"
        ) from exc


__all__ = ["HostProfileFieldError", "apply_set"]

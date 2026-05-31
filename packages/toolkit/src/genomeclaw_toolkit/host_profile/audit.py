"""Append-only audit log for host-profile mutations.

Every profile write appends one newline-delimited JSON record capturing
*what changed* — never the values themselves for free-text fields. The
privacy floor (``INV-P001`` / ``INV-C001``): free-text values, and
especially ``family_history.notes`` (a ``family_member_narrative``
field), are recorded as lengths only. Structured (enum / numeric) fields
are identified by path name in ``changed_paths`` but their values are not
written either, so the log is safe to ``tail``/``jq`` without exposing
the profile contents.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from genomeclaw_toolkit.schemas.host_profile import FREETEXT_PATHS, HostProfile

if TYPE_CHECKING:
    from pathlib import Path


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict to dotted leaf paths.

    Lists are treated as opaque leaves (compared by equality, never
    descended into) so list element values — including condition notes —
    never become individually-pathed entries the diff might surface.

    PRIVACY INVARIANT (do not break in a future refactor): lists MUST stay
    opaque here. ``medical_history.conditions[].notes``,
    ``medical_history.medications[].indication``, and
    ``medical_history.allergies[].reaction`` are user free-text fields that
    are NOT in :data:`FREETEXT_PATHS` precisely because they are never
    individually addressable — they live inside opaque list leaves and so
    never reach the audit record (which writes only path names + integer
    lengths, never values). If anyone ever adds list-element descent here,
    every descended element field must first be classified against
    ``FREETEXT_PATHS`` (and length-only-logged) before it can be emitted, or
    the free-text privacy floor silently breaks. The regression net is
    ``test_write_profile_condition_notes_not_in_audit_log``.
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def diff_changed_paths(
    before: HostProfile | None, after: HostProfile
) -> tuple[list[str], dict[str, int]]:
    """Return ``(changed_paths, freetext_lengths)`` for a profile mutation.

    ``changed_paths`` is the sorted list of dotted leaf paths whose value
    differs from ``before`` (all populated paths when ``before`` is None).
    ``freetext_lengths`` maps each *changed* free-text path to the length
    of its new value (never the value itself).
    """
    before_flat = _flatten(before.model_dump(mode="json")) if before is not None else {}
    after_flat = _flatten(after.model_dump(mode="json"))

    changed = sorted(
        path for path, value in after_flat.items() if before_flat.get(path) != value
    )
    freetext_lengths: dict[str, int] = {}
    for path in changed:
        if path in FREETEXT_PATHS:
            value = after_flat[path]
            if value is not None:
                freetext_lengths[path] = len(str(value))
    return changed, freetext_lengths


def append_audit_record(
    before: HostProfile | None,
    after: HostProfile,
    *,
    log_path: Path,
) -> None:
    """Append one NDJSON audit record for a profile mutation.

    The record timestamp is the new profile's ``meta.updated_at`` — a
    deterministic, caller-controlled value (no wall-clock read here), so
    a rebuild from the same inputs produces the same audit line.
    """
    changed_paths, freetext_lengths = diff_changed_paths(before, after)
    timestamp = after.meta.updated_at
    record = {
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
        "changed_paths": changed_paths,
        "freetext_lengths": freetext_lengths,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


__all__ = ["append_audit_record", "diff_changed_paths"]

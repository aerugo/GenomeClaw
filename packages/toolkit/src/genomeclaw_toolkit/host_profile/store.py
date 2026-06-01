"""Atomic JSON store for the host-side personal-context profile.

The canonical file is ``<derived_root>/host_profile.json``; the audit log
is ``<derived_root>/host_profile.audit.log``. Writes are crash-safe: the
payload is written to a ``.tmp`` sibling and ``os.replace``-d onto the
canonical path, so a partially-written file can never be observed as the
profile (``os.replace`` is atomic on POSIX).

The profile is host-side only (``INV-D002``): the path is always under
``<derived_root>/`` and never inside a sandbox-image-bound directory. The
sandbox reaches it only through the host service's read-only endpoint.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from genomeclaw_toolkit.host_profile.audit import append_audit_record
from genomeclaw_toolkit.schemas.host_profile import (
    CompletenessStatus,
    HostProfile,
    compute_completeness_map,
    migrate_host_profile,
)

_LOG = logging.getLogger(__name__)

_PROFILE_FILENAME = "host_profile.json"
_AUDIT_FILENAME = "host_profile.audit.log"


class HostProfileCorruptedError(Exception):
    """The profile file exists but is not valid JSON / does not validate."""


class HostProfileSchemaUnknownError(Exception):
    """The profile file declares a ``schema_version`` this build cannot migrate."""


def host_profile_path(derived_root: Path) -> Path:
    """Return the canonical profile path under ``derived_root`` (``INV-D002``)."""
    return Path(derived_root) / _PROFILE_FILENAME


def audit_log_path(derived_root: Path) -> Path:
    """Return the append-only audit-log path under ``derived_root``."""
    return Path(derived_root) / _AUDIT_FILENAME


def read_profile(derived_root: Path) -> HostProfile | None:
    """Read + validate the profile, or ``None`` if no profile file exists.

    A missing file is the normal pre-onboarding state — it is ``None``,
    never an error. A present-but-broken file raises a typed error so the
    service can surface a structured 500 rather than leak a stack trace.
    """
    path = host_profile_path(derived_root)
    if not path.exists():
        return None
    # The profile file is user-authored and may carry the most sensitive
    # host-side content (family-history narrative, condition notes). The
    # underlying parser/validator messages can echo field values verbatim,
    # so they are logged locally at DEBUG only — never embedded in the
    # exception message that travels to the service's HTTP error body
    # (INV-P001). The caller's recovery action is the same in every case:
    # re-author via `genomeclaw host profile init`.
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        _LOG.debug("host_profile.json is not valid JSON: %s", exc)
        raise HostProfileCorruptedError(
            "host_profile.json is present but is not valid JSON"
        ) from exc
    try:
        migrated = migrate_host_profile(raw)
    except ValueError as exc:
        _LOG.debug("host_profile.json declares an unknown schema_version: %s", exc)
        raise HostProfileSchemaUnknownError(
            "host_profile.json declares a schema_version this build cannot serve"
        ) from exc
    try:
        return HostProfile.model_validate(migrated)
    except ValidationError as exc:
        _LOG.debug("host_profile.json failed schema validation: %s", exc)
        raise HostProfileCorruptedError(
            "host_profile.json is present but does not validate against the v1.0 schema"
        ) from exc


def write_profile_atomic(derived_root: Path, profile: HostProfile) -> None:
    """Atomically write the profile and append an audit record.

    The audit diff is computed against the prior on-disk profile (a
    corrupt prior file is treated as "no prior" for the diff — the
    canonical write is authoritative; the audit log is best-effort).
    """
    derived_root = Path(derived_root)
    derived_root.mkdir(parents=True, exist_ok=True)

    try:
        before = read_profile(derived_root)
    except (HostProfileCorruptedError, HostProfileSchemaUnknownError):
        before = None

    path = host_profile_path(derived_root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    # os.replace (not Path.replace) is the deliberate atomic seam: it is
    # monkeypatchable at module scope, which the atomic-write test relies
    # on to assert the tmp-then-replace contract. Both are atomic on POSIX.
    os.replace(tmp, path)  # noqa: PTH105

    append_audit_record(before, profile, log_path=audit_log_path(derived_root))


def compute_completeness(
    profile: HostProfile | None,
) -> dict[str, CompletenessStatus] | None:
    """Return the per-section completeness map, or ``None`` for a missing profile."""
    if profile is None:
        return None
    return compute_completeness_map(profile)


__all__ = [
    "HostProfileCorruptedError",
    "HostProfileSchemaUnknownError",
    "audit_log_path",
    "compute_completeness",
    "host_profile_path",
    "read_profile",
    "write_profile_atomic",
]

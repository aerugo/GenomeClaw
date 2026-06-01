"""Phase 1 (host-profile-personal-context) — atomic store + audit log tests.

The profile lives as a single JSON document at
``<derived_root>/host_profile.json`` (Decision 1 — JSON on disk, not a
DuckDB row). Writes are atomic (tmp-file + ``os.replace``) so a crashed
write never leaves a half-written canonical file. Every mutation appends
one NDJSON record to ``<derived_root>/host_profile.audit.log``.

Two invariants are exercised here:

- ``INV-D002`` — the resolved profile path is host-side, under
  ``<derived_root>/``, never under a sandbox-image-bound directory.
- The audit-log privacy floor: free-text values (and especially
  ``family_history.notes``, a ``family_member_narrative`` field) are
  recorded as *lengths only*, never verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

from genomeclaw_toolkit.host_profile import store as host_profile_store
from genomeclaw_toolkit.host_profile.store import (
    audit_log_path,
    compute_completeness,
    host_profile_path,
    read_profile,
    write_profile_atomic,
)
from genomeclaw_toolkit.schemas.host_profile import HostProfile

_META = {
    "created_at": "2026-05-31T00:00:00Z",
    "updated_at": "2026-05-31T00:00:00Z",
}


def _profile(**sections) -> HostProfile:
    payload = {
        "schema_version": "host_profile/1.0",
        "meta": dict(_META),
        "identity": {},
    }
    payload.update(sections)
    return HostProfile.model_validate(payload)


def test_read_profile_returns_none_when_missing(tmp_path: Path) -> None:
    """A fresh derived root with no profile file reads as ``None`` (not an error)."""
    assert read_profile(tmp_path) is None


def test_write_profile_atomic_writes_to_tmp_then_replaces(
    tmp_path: Path, monkeypatch
) -> None:
    """The write goes through a ``.tmp`` sibling, then ``os.replace`` onto the canonical file."""
    calls: list[tuple[str, str]] = []
    real_replace = host_profile_store.os.replace

    def _spy_replace(src, dst, *args, **kwargs):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(host_profile_store.os, "replace", _spy_replace)

    write_profile_atomic(tmp_path, _profile())

    assert len(calls) == 1, "exactly one atomic replace per write"
    src, dst = calls[0]
    assert src.endswith(".tmp"), f"source of the replace must be a .tmp file, got {src!r}"
    assert dst == str(host_profile_path(tmp_path))
    # No leftover tmp files; the canonical file is complete + valid JSON.
    assert not list(tmp_path.glob("*.tmp"))
    reloaded = read_profile(tmp_path)
    assert reloaded is not None
    assert reloaded.schema_version == "host_profile/1.0"


def test_write_profile_appends_audit_log_entry(tmp_path: Path) -> None:
    """Every mutation appends one NDJSON record with the expected keys."""
    write_profile_atomic(tmp_path, _profile())

    log = audit_log_path(tmp_path)
    assert log.exists()
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) >= {"timestamp", "changed_paths", "freetext_lengths"}
    assert isinstance(record["changed_paths"], list)
    assert record["changed_paths"], "first write records the populated paths"
    assert isinstance(record["freetext_lengths"], dict)


def test_write_profile_family_history_audit_log_records_length_only(
    tmp_path: Path,
) -> None:
    """``family_history.notes`` is logged as a length, never verbatim (privacy floor)."""
    narrative = "Maternal grandfather had early-onset Alzheimer's at 61."
    profile = _profile(family_history={"notes": narrative, "opted_out": False})
    write_profile_atomic(tmp_path, profile)

    log_text = audit_log_path(tmp_path).read_text()
    record = json.loads([ln for ln in log_text.splitlines() if ln.strip()][0])
    assert record["freetext_lengths"]["family_history.notes"] == len(narrative)
    # The verbatim narrative must NOT appear anywhere in the audit log.
    assert narrative not in log_text
    assert "Alzheimer" not in log_text


def test_write_profile_condition_notes_not_in_audit_log(tmp_path: Path) -> None:
    """Condition notes live inside an opaque list leaf — never written to the audit log.

    ``Condition.notes`` is user free-text but is NOT in ``FREETEXT_PATHS``;
    its privacy floor is the ``_flatten`` opaque-list-leaf invariant. This is
    the regression net the audit-module docstring points at: if list descent
    is ever added, this marker would leak into the log.
    """
    marker = "ZZ_SECRET_CONDITION_NARRATIVE_ZZ"
    profile = _profile(
        medical_history={"conditions": [{"name": "reflux", "notes": marker, "status": "active"}]}
    )
    write_profile_atomic(tmp_path, profile)

    log_text = audit_log_path(tmp_path).read_text()
    assert marker not in log_text
    # The section did change, so its path name is recorded — but not the value.
    record = json.loads([ln for ln in log_text.splitlines() if ln.strip()][0])
    assert "medical_history.conditions" in record["changed_paths"]


def test_compute_completeness_marks_empty_section_missing(tmp_path: Path) -> None:
    """An empty ``medical_history.medications`` reports ``missing``."""
    completeness = compute_completeness(_profile())
    assert completeness is not None
    assert completeness["medical_history.medications"] == "missing"


def test_compute_completeness_marks_partial_when_some_fields_present() -> None:
    """A half-filled section reports ``partial`` — not ``complete``."""
    profile = _profile(biometrics={"height_cm": 195.0})  # weight absent
    completeness = compute_completeness(profile)
    assert completeness is not None
    assert completeness["biometrics"] == "partial"


def test_compute_completeness_returns_none_for_missing_profile() -> None:
    """No profile → no completeness map."""
    assert compute_completeness(None) is None


def test_invD002_host_profile_path_is_host_side(tmp_path: Path) -> None:
    """INV-D002: the resolved profile path lives under the derived root, never /sandbox/."""
    path = host_profile_path(tmp_path)
    assert str(path).startswith(str(tmp_path))
    assert "/sandbox/" not in str(path)
    assert path.name == "host_profile.json"

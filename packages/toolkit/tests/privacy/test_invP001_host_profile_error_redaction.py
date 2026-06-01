"""Phase 1 (host-profile-personal-context) — INV-P001 error-body redaction.

The profile file is user-authored and carries the most sensitive
host-side content (family-history narrative, condition notes). The
parser / Pydantic-validator messages can echo offending field values
verbatim, and a corrupted / unknown-schema file's ``schema_version`` is
attacker-influenceable. Neither must reach the HTTP 500 body the agent
receives (``INV-P001``): the only host-side-only place the detail belongs
is a DEBUG log. The response carries a static, action-oriented message.

These tests write a deliberately-broken profile that fails validation /
declares an unknown schema_version with a recognisable marker embedded in
the sensitive field, then assert the marker never appears anywhere in the
endpoint's 500 response body.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from genomeclaw_toolkit.host_profile.store import host_profile_path
from genomeclaw_toolkit.service.app import build_app

_MARKER = "ZZ_PRIVATE_FAMILY_NARRATIVE_MARKER_ZZ"


def _build(tmp_path: Path) -> tuple[Path, object]:
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    return derived_root, build_app(derived_root=derived_root)


def test_invP001_validation_error_does_not_echo_field_value(tmp_path: Path) -> None:
    """A schema-invalid profile (over-long notes carrying a marker) yields a redacted 500."""
    derived_root, app = _build(tmp_path)
    # Valid JSON, invalid schema: family_history.notes exceeds max_length (4000)
    # while carrying the marker, forcing a Pydantic ValidationError on read.
    payload = {
        "schema_version": "host_profile/1.0",
        "meta": {
            "created_at": "2026-05-31T00:00:00Z",
            "updated_at": "2026-05-31T00:00:00Z",
        },
        "identity": {},
        "family_history": {"notes": _MARKER + ("y" * 4000)},
    }
    host_profile_path(derived_root).write_text(json.dumps(payload))

    with TestClient(app) as client:
        resp = client.get("/v1/host/profile")

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["error"] == "host_profile_corrupted"
    assert _MARKER not in resp.text
    assert "init" in body["detail"]  # points at the recovery action


def test_invP001_schema_unknown_does_not_echo_version_value(tmp_path: Path) -> None:
    """An unknown schema_version (carrying a marker) is not echoed into the 500 body."""
    derived_root, app = _build(tmp_path)
    payload = {
        "schema_version": "host_profile/" + _MARKER,
        "meta": {
            "created_at": "2026-05-31T00:00:00Z",
            "updated_at": "2026-05-31T00:00:00Z",
        },
        "identity": {},
    }
    host_profile_path(derived_root).write_text(json.dumps(payload))

    with TestClient(app) as client:
        resp = client.get("/v1/host/profile")

    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["error"] == "host_profile_schema_unknown"
    assert _MARKER not in resp.text

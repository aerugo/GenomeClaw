"""Phase 1 (host-profile-personal-context) — host-service endpoint contract.

Two read-only routes added to the host service:

- ``GET /v1/host/profile`` — the full (or section-filtered) profile, or a
  structured *missing* signal when no profile exists yet.
- ``GET /v1/host/profile/completeness`` — a per-section completeness map
  without the full payload.

Unlike the variant/finding routes, these do NOT require an active
pipeline run: the profile lives at the derived-root level and is readable
on a fresh GenomeClaw install before any genome is ingested. The
*missing* signal (HTTP 200 + ``missing: true``) is a structured state the
agent acts on, not a tool failure (``INV-A005``).

Bare-host venv — in-process FastAPI app, no bio binaries, no network.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from genomeclaw_toolkit.host_profile.store import write_profile_atomic
from genomeclaw_toolkit.schemas.host_profile import HostProfile
from genomeclaw_toolkit.service.app import build_app

_META = {
    "created_at": "2026-05-31T00:00:00Z",
    "updated_at": "2026-05-31T00:00:00Z",
}


def _write_full_profile(derived_root: Path) -> None:
    profile = HostProfile.model_validate(
        {
            "schema_version": "host_profile/1.0",
            "meta": dict(_META),
            "identity": {
                "sex_assigned_at_birth": "male",
                "date_of_birth": "1988-11-12",
                "ancestry": {"groups": ["european"]},
            },
            "biometrics": {"height_cm": 195.0, "weight_kg": 104.0},
            "medical_history": {
                "medications": [{"name": "none_declared"}],
                "conditions": [{"name": "acid reflux", "status": "active"}],
            },
        }
    )
    write_profile_atomic(derived_root, profile)


def test_get_host_profile_returns_missing_signal_when_no_file(tmp_path: Path) -> None:
    """A fresh derived root surfaces the structured missing signal (NOT a 404)."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.get("/v1/host/profile")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["profile"] is None
    assert body["missing"] is True
    assert body["init_command"] == "genomeclaw host profile init"


def test_get_host_profile_returns_full_payload_when_present(tmp_path: Path) -> None:
    """Happy path: profile present, full payload + completeness returned."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _write_full_profile(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.get("/v1/host/profile")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["missing"] is False
    assert body["init_command"] is None
    assert body["profile"]["identity"]["sex_assigned_at_birth"] == "male"
    assert body["profile"]["biometrics"]["height_cm"] == 195.0
    assert body["completeness"]["identity"] in {"complete", "partial"}


def test_get_host_profile_sections_query_filters_payload(tmp_path: Path) -> None:
    """``?sections=`` returns only the requested section (plus meta)."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _write_full_profile(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.get("/v1/host/profile?sections=medical_history.medications")

    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]
    assert "meta" in profile
    medications = profile["medical_history"]["medications"]
    assert [m["name"] for m in medications] == ["none_declared"]
    # Non-requested sections are filtered out.
    assert "biometrics" not in profile
    assert "identity" not in profile


def test_get_host_profile_unknown_section_returns_400(tmp_path: Path) -> None:
    """An unknown section name is a 400 with the known-section list."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _write_full_profile(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.get("/v1/host/profile?sections=horoscope")

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"] == "host_profile_unknown_section"
    assert body["section"] == "horoscope"
    assert isinstance(body["known_sections"], list)


def test_get_host_profile_completeness_returns_section_map(tmp_path: Path) -> None:
    """``/completeness`` returns the section map without the full payload."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _write_full_profile(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.get("/v1/host/profile/completeness")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["missing"] is False
    assert isinstance(body["sections"], dict)
    assert "medical_history.medications" in body["sections"]
    assert body["meta"]["updated_at"] is not None
    # The completeness endpoint must NOT echo the full profile payload.
    assert "profile" not in body
    assert "identity" not in body

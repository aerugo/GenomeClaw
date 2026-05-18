"""Phase 5 Slice A — `/v1/health` endpoint contract + INV-P002 shape pin.

Covers the smallest end-to-end skeleton for the host service: the active-run
resolver (`CURRENT` symlink → manifest), the FastAPI app's lifespan wiring,
and the `/v1/health` route's payload shape. Subsequent slices add
`/v1/variants`, `/v1/gene/{symbol}`, `/v1/provenance/{run-id}`, and the
SIGHUP-based symlink re-resolution.

These tests run on the bare host venv (no `needs_bio` marker) — they don't
exercise any bio binaries, only the in-process FastAPI app + a synthetic
manifest fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app


def _stage_minimal_run(derived_root: Path, *, run_id: str = "2026-05-15T00-00-00Z-abc123") -> Path:
    """Create a synthetic `derived/<run-id>/manifest.json` + flip CURRENT.

    The manifest shape is the minimum the health endpoint needs to introspect
    the active run: `run_id`, `schema_version`, `sample_id`. Other manifest
    fields (input, outputs, tools, qc) are absent here — the health endpoint
    must not require them.
    """
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "sample_id": "test-sample",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    update_current_symlink(derived_root, run_id)
    return run_dir


def test_health_returns_200_with_active_run_payload(tmp_path: Path) -> None:
    """`GET /v1/health` returns the active run's id + schema version when CURRENT resolves.

    Pins the happy-path contract: status 200, JSON body with the three
    fields the plugin's `genomeclaw_status` tool needs to round-trip.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_minimal_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["current_run_id"] == "2026-05-15T00-00-00Z-abc123"
    assert body["sample_id"] == "test-sample"


def test_health_returns_503_when_current_symlink_missing(tmp_path: Path) -> None:
    """`GET /v1/health` returns 503 with an actionable error when CURRENT is absent.

    A fresh derived root with no completed pipeline run is the natural
    "service has nothing to serve" state. The contract: 503 + a body
    naming the next user action (`genomeclaw pipeline run`).
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    # No CURRENT symlink staged.

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["status"] == "no_active_run"
    # The message must point the user at the recovery command.
    assert "genomeclaw pipeline" in body["detail"].lower()


def test_health_returns_503_when_schema_version_mismatch(tmp_path: Path) -> None:
    """The service refuses to serve a run whose schema_version it can't model.

    Schema-version refusal is one of the two pieces of the rebuild
    discipline: derived stores from older schema versions need to be
    rebuilt by the user against the current toolkit. The service surfaces
    this as 503 with an actionable message rather than silently returning
    rows with missing columns.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_id = "2026-05-15T00-00-00Z-old001"
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "schema_version": "v0.0", "sample_id": "old"})
    )
    update_current_symlink(derived_root, run_id)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["status"] == "schema_version_mismatch"
    assert "v0.0" in body["detail"]
    assert SCHEMA_VERSION in body["detail"]


@pytest.mark.parametrize(
    "extra_field",
    [
        "raw_paths",  # leaking host paths
        "manifest",  # full manifest dump
        "provenance",  # full provenance trail
    ],
)
def test_invP002_health_response_excludes_bulk_or_path_fields(
    tmp_path: Path, extra_field: str
) -> None:
    """``INV-P002``: `/v1/health` is a status surface — never a manifest dump.

    Pins the minimal-sufficient contract: the response must not include
    raw host paths, full manifest blobs, or full provenance trails.
    A future regression that "helpfully" widens the response to include
    the manifest for debugging would surface here as a snapshot failure.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_minimal_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/health")

    body = response.json()
    assert extra_field not in body, (
        f"INV-P002 violation: /v1/health response includes bulk-or-path field "
        f"{extra_field!r}; got body keys {sorted(body)}"
    )

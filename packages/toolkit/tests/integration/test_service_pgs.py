"""Phase 6 Slice E v2 — `/v1/pgs/*` endpoint contracts.

Four endpoints, all keyed by **PGS Catalog ID** per Q8 v1.6:

- `GET /v1/pgs/computed` — list of all PRSs the agent has computed for this user.
- `GET /v1/pgs/computed/{pgs_id}` — single PRS in full (includes
  `agent_choice_rationale` + `requested_for_question` per `INV-A003`).
- `POST /v1/pgs/compute` — agent-triggered async compute request. Returns
  `task_id` + initial status. (E.1 ships the request enqueue; E.3 ships the
  background-worker orchestration that drives queued → running → done.)
- `GET /v1/pgs/compute/{task_id}` — status polling.

These tests run against a stubbed orchestrator: enqueueing inserts into
`pgs_compute_tasks.sqlite` with `status=queued` but does not start a real
`pgsc_calc`. The E.3 sub-slice fills in the background worker.

Two failure-mode contracts pinned here:
- `POST /v1/pgs/compute` rejects a `rationale` shorter than 50 chars (422)
  — peer to the model-layer `PgsComputeRequest` test in test_pgs_model.py.
- `GET /v1/pgs/computed/{pgs_id}` response carries exactly the 10 documented
  fields, never the raw PGS variant list. `INV-P002` floor.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)

_RUN_ID = "2026-05-17T00-00-00Z-pgs001"


def _stage_run_with_pgs_scores(derived_root: Path, rows: list[dict]) -> Path:
    """Stage a derived/<run-id>/ with the manifest + populated pgs_scores rows."""
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": "pgs-fixture"}
        )
    )
    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    if rows:
        _insert_pgs_scores(store_path, rows)
    # Create the tasks DB up-front so the compute-status endpoint has a target.
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def _insert_pgs_scores(store_path: Path, rows: list[dict]) -> None:
    now = datetime.now(tz=UTC)
    fixture_sha = "f" * 64
    conn = duckdb.connect(str(store_path))
    try:
        for r in rows:
            conn.execute(
                """
                INSERT INTO pgs_scores (
                    pgs_id, trait_label, percentile_in_user_ancestry, raw_score,
                    study_population, calibration_warning,
                    agent_choice_rationale, requested_for_question, superseded_by,
                    source_path, source_sha256, tool, tool_version,
                    params_json, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'fixture-pgs', ?, 'pgsc_calc-fixture', '0.0',
                          '{}', ?, ?)
                """,
                [
                    r["pgs_id"],
                    r["trait_label"],
                    r["percentile_in_user_ancestry"],
                    r["raw_score"],
                    r["study_population"],
                    r.get("calibration_warning"),
                    r["agent_choice_rationale"],
                    r["requested_for_question"],
                    r.get("superseded_by"),
                    fixture_sha,
                    SCHEMA_VERSION,
                    now,
                ],
            )
    finally:
        conn.close()


_VALID_RATIONALE = (
    "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS with the most mature "
    "cross-ancestry calibration. Considered PGS004696 and rejected for less "
    "cross-ancestry validation."
)

_STORY10_ROW = {
    "pgs_id": "PGS000018",
    "trait_label": "coronary artery disease (CARDIoGRAMplusC4D + UK Biobank)",
    "percentile_in_user_ancestry": 87.0,
    "raw_score": 0.42,
    "study_population": "European-ancestry meta-analysis (UK Biobank + CARDIoGRAMplusC4D)",
    "calibration_warning": None,
    "agent_choice_rationale": _VALID_RATIONALE,
    "requested_for_question": "my dad had a heart attack at 58. is there anything in my genome about cad risk?",
}

_T2D_ROW = {
    "pgs_id": "PGS001838",
    "trait_label": "type 2 diabetes",
    "percentile_in_user_ancestry": 45.0,
    "raw_score": -0.13,
    "study_population": "European-ancestry meta-analysis",
    "calibration_warning": None,
    "agent_choice_rationale": "Canonical T2D PRS." * 5,  # 80 chars
    "requested_for_question": "what about my T2D risk?",
}


def test_pgs_list_returns_empty_when_no_rows(tmp_path: Path) -> None:
    """`GET /v1/pgs/computed` returns 200 + `{rows: [], total: 0}` empty."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/pgs/computed")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == []
    assert body["total"] == 0


def test_pgs_list_returns_rows_when_present(tmp_path: Path) -> None:
    """`GET /v1/pgs/computed` returns one row per computed PRS."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [_STORY10_ROW, _T2D_ROW])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/pgs/computed")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    pgs_ids = {row["pgs_id"] for row in body["rows"]}
    assert pgs_ids == {"PGS000018", "PGS001838"}


def test_pgs_get_returns_row_for_known_id(tmp_path: Path) -> None:
    """`GET /v1/pgs/computed/{pgs_id}` returns the full row."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [_STORY10_ROW])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/pgs/computed/PGS000018")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pgs_id"] == "PGS000018"
    assert body["percentile_in_user_ancestry"] == 87.0
    assert body["agent_choice_rationale"] == _VALID_RATIONALE
    assert body["requested_for_question"] == _STORY10_ROW["requested_for_question"]


def test_pgs_get_returns_404_for_unknown_id(tmp_path: Path) -> None:
    """`GET /v1/pgs/computed/PGS999999` returns 404 + typed error body."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [_STORY10_ROW])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/pgs/computed/PGS999999")

    assert response.status_code == 404, response.text
    body = response.json()
    assert "PGS999999" in body["detail"]


def test_pgs_get_response_excludes_bulk_fields_invP002(tmp_path: Path) -> None:
    """`GET /v1/pgs/computed/{pgs_id}` body has exactly the 12 documented fields.

    The raw PGS variant list (potentially thousands of weighted variants for
    this user) MUST NOT surface. `INV-P002` floor.

    The 12 fields include `calibration_status` and `decline_reason` since
    agent-decline-taxonomy-exposure Phase 1 (`INV-A004`): the agent needs
    the machine-readable decline signal alongside the free-text
    `calibration_warning`.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [_STORY10_ROW])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/pgs/computed/PGS000018")

    assert response.status_code == 200
    body = response.json()
    expected_fields = {
        "pgs_id",
        "trait_label",
        "percentile_in_user_ancestry",
        "raw_score",
        "source_pgs_id",
        "study_population",
        "calibration_warning",
        "calibration_status",
        "decline_reason",
        "agent_choice_rationale",
        "requested_for_question",
        "superseded_by",
    }
    assert set(body.keys()) == expected_fields, (
        f"INV-P002 floor: response field set drifted. Got {sorted(body.keys())}; "
        f"expected {sorted(expected_fields)}."
    )


def test_pgs_compute_request_enqueues_task(tmp_path: Path) -> None:
    """`POST /v1/pgs/compute` returns 202 + `task_id` + `status=queued`."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run_with_pgs_scores(derived_root, [])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS000018",
                "trait_label": "coronary artery disease",
                "rationale": _VALID_RATIONALE,
                "requested_for_question": "my dad had a heart attack at 58",
            },
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] in ("queued", "running")
    assert body["pgs_id"] == "PGS000018"
    assert body["task_id"]

    # Side-effect: task row landed in pgs_compute_tasks.sqlite.
    conn = sqlite3.connect(str(run_dir / "pgs_compute_tasks.sqlite"))
    try:
        rows = conn.execute("SELECT task_id, pgs_id, status FROM pgs_compute_tasks").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "PGS000018"


def test_pgs_compute_request_rejects_short_rationale(tmp_path: Path) -> None:
    """`POST /v1/pgs/compute` with `rationale=""` returns 422."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS000018",
                "trait_label": "coronary artery disease",
                "rationale": "",  # ← INV-A003 violation
                "requested_for_question": "?",
            },
        )

    assert response.status_code == 422, response.text


def test_pgs_compute_status_returns_task_state(tmp_path: Path) -> None:
    """Given a `task_id`, `GET /v1/pgs/compute/{task_id}` returns the task row."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        # Enqueue first to get a real task_id.
        enq = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS000018",
                "trait_label": "coronary artery disease",
                "rationale": _VALID_RATIONALE,
                "requested_for_question": "my dad had a heart attack at 58",
            },
        )
        assert enq.status_code == 202
        task_id = enq.json()["task_id"]

        # Now poll.
        status_resp = client.get(f"/v1/pgs/compute/{task_id}")

    assert status_resp.status_code == 200, status_resp.text
    body = status_resp.json()
    assert body["task_id"] == task_id
    assert body["status"] in ("queued", "running")
    assert body["pgs_id"] == "PGS000018"


def test_pgs_compute_status_returns_404_for_unknown_task(tmp_path: Path) -> None:
    """Unknown `task_id` → 404 + typed error body."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_pgs_scores(derived_root, [])

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/pgs/compute/task-does-not-exist")

    assert response.status_code == 404, response.text
    body = response.json()
    assert "task-does-not-exist" in body["detail"]

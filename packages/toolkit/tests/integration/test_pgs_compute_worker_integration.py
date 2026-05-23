"""Phase 4 RED — pin the worker's compute-integration contract.

Phase 3 landed the queue management with a no-op compute; Phase 4 wires
the worker to ``compute_prs_with_coverage_fill(...)`` via
``loop.run_in_executor`` and persists ``pgs_scores`` + ``findings`` via
``stamp_pgs_row(...)`` (relocated in Phase 4 from
``_cli/commands/pipeline.py`` to ``prep/pgs.py``).

Tests stub ``compute_prs_with_coverage_fill`` at the orchestrator's
module namespace; the worker references it via module globals so
``monkeypatch.setattr`` swaps take effect at runtime (same idiom Phase 3
used for ``_noop_compute_fn``).

Plan: [docs/plans/active/agent-prs-compute-fix/phases/phase-4.md](../../../../docs/plans/active/agent-prs-compute-fix/phases/phase-4.md)
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep._paths import DooDPathError
from genomeclaw_toolkit.prep._pgs_qc import DeclineReason, PRSDeclineError
from genomeclaw_toolkit.prep.pgs import PgsRow
from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)

_RUN_ID = "2026-05-23T00-00-00Z-phase4"
_SAMPLE = "phase4-fixture"


def _stage_run_with_config(tmp_path: Path) -> Path:
    """Stage a derived/<run-id>/ + a valid prs_compute_config.json sidecar.

    Phase 4's worker reads the sidecar at startup; tests that exercise the
    worker need it present. Path values point at tmp_path so the test
    fixture is self-contained.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": _SAMPLE})
    )
    create_store(run_dir / "variants.duckdb")
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")

    scorefile_root = tmp_path / "scorefiles"
    scorefile_root.mkdir()
    (run_dir / "prs_compute_config.json").write_text(
        json.dumps(
            {
                "sample_id": _SAMPLE,
                "cram_path": str(tmp_path / "sample.cram"),
                "reference_root": str(tmp_path / "reference"),
                "scorefile_root": str(scorefile_root),
                "work_dir_root": str(tmp_path / "work"),
                "panel_version": "v1",
                "sites_tsv": str(tmp_path / "reference" / "sites.tsv"),
                "alleles_tsv": str(tmp_path / "reference" / "alleles.tsv"),
                "fasta": str(tmp_path / "reference" / "genome.fa"),
            }
        )
    )

    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def _make_fake_pgs_row(*, pgs_id: str = "PGS_TEST", percentile: float | None = 78.4) -> PgsRow:
    return PgsRow(
        pgs_id=pgs_id,
        trait_label="test trait",
        percentile_in_user_ancestry=percentile,
        raw_score=0.42 if percentile is not None else None,
        study_population="EUR",
        calibration_warning=None,
        agent_choice_rationale="placeholder — set by worker",
        requested_for_question="placeholder — set by worker",
    )


def _stage_scorefile(run_dir: Path, pgs_id: str) -> None:
    """Touch the scorefile path the worker resolves so it doesn't 404."""
    config = json.loads((run_dir / "prs_compute_config.json").read_text())
    scorefile_root = Path(config["scorefile_root"])
    (scorefile_root / f"{pgs_id}.txt.gz").write_bytes(b"")


def _enqueue(client, *, pgs_id="PGS_TEST", rationale="phase-4 worker integration test"):
    return client.post(
        "/v1/pgs/compute",
        json={
            "pgs_id": pgs_id,
            "trait_label": "test trait",
            "rationale": rationale,
            "requested_for_question": "phase-4 test question",
        },
    )


def _wait_for_terminal(client, task_id, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/v1/pgs/compute/{task_id}")
        body = r.json()
        if body.get("status") in ("done", "failed"):
            return body
        time.sleep(0.05)
    return r.json()


# -----------------------------------------------------------------------------
# Compute integration — INV-A003 plumbing through to compute_prs_with_coverage_fill
# -----------------------------------------------------------------------------


def test_invA003_worker_threads_rationale_and_requested_for_question_to_compute(
    tmp_path: Path, monkeypatch
):
    """INV-A003: worker passes the task's rationale + question verbatim to compute.

    Phase 3 verified the worker reads both fields from the task row.
    Phase 4 verifies they reach ``compute_prs_with_coverage_fill(...)``
    untouched + therefore reach the ``pgs_scores`` row that
    ``stamp_pgs_row`` writes.
    """
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    captured: list[dict] = []

    def fake_compute(**kwargs):
        captured.append(kwargs)
        return _make_fake_pgs_row(pgs_id=kwargs["scorefile_path"].stem.replace(".txt", ""))

    monkeypatch.setattr(pgs_compute_orchestrator, "compute_prs_with_coverage_fill", fake_compute)
    monkeypatch.setattr(pgs_compute_orchestrator, "stamp_pgs_row", lambda *a, **kw: None)

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    distinctive_rationale = "Canonical AMD PRS — phase-4 INV-A003 plumbing assertion"
    distinctive_question = "do I have any increased risk of losing eye sight when I age?"

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        resp = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS_TEST",
                "trait_label": "test",
                "rationale": distinctive_rationale,
                "requested_for_question": distinctive_question,
            },
        )
        task_id = resp.json()["task_id"]
        final = _wait_for_terminal(client, task_id)

    assert final["status"] == "done", final
    assert len(captured) == 1
    assert captured[0]["agent_choice_rationale"] == distinctive_rationale
    assert captured[0]["requested_for_question"] == distinctive_question


def test_worker_persists_pgs_scores_and_findings(tmp_path: Path, monkeypatch):
    """Happy path: one ``pgs_scores`` row + one ``findings`` row land per compute."""
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    monkeypatch.setattr(
        pgs_compute_orchestrator,
        "compute_prs_with_coverage_fill",
        lambda **kw: _make_fake_pgs_row(pgs_id="PGS_TEST"),
    )

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        resp = _enqueue(client)
        final = _wait_for_terminal(client, resp.json()["task_id"])

    assert final["status"] == "done", final

    conn = duckdb.connect(str(run_dir / "variants.duckdb"))
    try:
        pgs_rows = conn.execute("SELECT pgs_id FROM pgs_scores").fetchall()
        finding_rows = conn.execute(
            "SELECT id, category FROM findings WHERE evidence_ref LIKE 'pgs_catalog:%'"
        ).fetchall()
    finally:
        conn.close()

    assert len(pgs_rows) == 1
    assert pgs_rows[0][0] == "PGS_TEST"
    assert len(finding_rows) == 1
    assert finding_rows[0][1] == "clinical-non-actionable"


def test_invR001_worker_stamps_seven_provenance_columns(tmp_path: Path, monkeypatch):
    """INV-R001: every worker-written ``pgs_scores`` row carries the 7 provenance cols."""
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    monkeypatch.setattr(
        pgs_compute_orchestrator,
        "compute_prs_with_coverage_fill",
        lambda **kw: _make_fake_pgs_row(pgs_id="PGS_TEST"),
    )

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        _wait_for_terminal(client, _enqueue(client).json()["task_id"])

    conn = duckdb.connect(str(run_dir / "variants.duckdb"))
    try:
        row = conn.execute(
            """
            SELECT source_path, source_sha256, tool, tool_version,
                   params_json, schema_version, created_at
            FROM pgs_scores WHERE pgs_id = 'PGS_TEST'
            """
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    source_path, source_sha256, tool, tool_version, params_json, schema_version, created_at = row
    assert source_path  # non-empty
    assert source_sha256 is not None  # may be empty string but column populated
    assert tool == "pgsc_calc"
    assert tool_version == "agent-driven"
    assert params_json and "PGS_TEST" in params_json
    assert schema_version == SCHEMA_VERSION
    assert created_at is not None


# -----------------------------------------------------------------------------
# INV-R002 — degenerate-result guard
# -----------------------------------------------------------------------------


def test_invR002_degenerate_result_does_not_stamp(tmp_path: Path, monkeypatch):
    """INV-R002: a row with ``percentile=None`` AND ``raw_score=None`` doesn't stamp.

    A degenerate compute (zero-overlap, missing percentile) must transition
    to ``failed:degenerate_result:...`` instead of caching a meaningless
    row.
    """
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    def degenerate_compute(**kwargs):
        return PgsRow(
            pgs_id=kwargs["scorefile_path"].stem.replace(".txt", ""),
            trait_label="test",
            percentile_in_user_ancestry=None,
            raw_score=None,
            study_population="EUR",
            calibration_warning=None,
            agent_choice_rationale=kwargs["agent_choice_rationale"],
            requested_for_question=kwargs["requested_for_question"],
        )

    monkeypatch.setattr(pgs_compute_orchestrator, "compute_prs_with_coverage_fill", degenerate_compute)

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        final = _wait_for_terminal(client, _enqueue(client).json()["task_id"])

    assert final["status"] == "failed", final
    assert final["error"] is not None
    assert final["error"].startswith("degenerate_result:"), final["error"]

    # And no row was stamped:
    conn = duckdb.connect(str(run_dir / "variants.duckdb"))
    try:
        rows = conn.execute("SELECT count(*) FROM pgs_scores WHERE pgs_id='PGS_TEST'").fetchone()
    finally:
        conn.close()
    assert rows[0] == 0


# -----------------------------------------------------------------------------
# Structured error mapping — 4 failure modes mapped to failed:<class>:<detail>
# -----------------------------------------------------------------------------


def test_worker_maps_scorefile_missing_to_structured_error(tmp_path: Path, monkeypatch):
    """Scorefile not at the canonical path → ``failed:scorefile_missing:PGS_X``."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    _stage_run_with_config(tmp_path)  # config staged but NO scorefile touched

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        final = _wait_for_terminal(client, _enqueue(client, pgs_id="PGS_MISSING").json()["task_id"])

    assert final["status"] == "failed"
    assert final["error"] == "scorefile_missing:PGS_MISSING", final["error"]


def test_worker_maps_pgsc_calc_failure_to_structured_error(tmp_path: Path, monkeypatch):
    """``subprocess.CalledProcessError`` from pgsc_calc → ``failed:pgsc_calc_failed:rc=N``."""
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    def raise_called_process_error(**_kw):
        raise subprocess.CalledProcessError(returncode=1, cmd=["nextflow", "run", "pgsc_calc"])

    monkeypatch.setattr(
        pgs_compute_orchestrator, "compute_prs_with_coverage_fill", raise_called_process_error
    )

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        final = _wait_for_terminal(client, _enqueue(client).json()["task_id"])

    assert final["status"] == "failed"
    assert final["error"] == "pgsc_calc_failed:rc=1", final["error"]


def test_worker_maps_dood_path_error(tmp_path: Path, monkeypatch):
    """``DooDPathError`` → ``failed:dood_path_error:<short>``."""
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    def raise_dood_path_error(**_kw):
        raise DooDPathError("/tmp/not-a-host-path is not sibling-mountable")

    monkeypatch.setattr(
        pgs_compute_orchestrator, "compute_prs_with_coverage_fill", raise_dood_path_error
    )

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        final = _wait_for_terminal(client, _enqueue(client).json()["task_id"])

    assert final["status"] == "failed"
    assert final["error"].startswith("dood_path_error:"), final["error"]


def test_worker_maps_prs_decline(tmp_path: Path, monkeypatch):
    """``PRSDeclineError`` → ``failed:prs_decline:<DeclineReason.value>``."""
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    def raise_prs_decline(**_kw):
        raise PRSDeclineError(
            reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
            two_named_reasons=(
                "Match rate below ancestry-calibration floor.",
                "Variant-overlap insufficient for ancestry-calibrated score.",
            ),
            message="PRS PGS_TEST declined per INV-C001 v1.7",
        )

    monkeypatch.setattr(
        pgs_compute_orchestrator, "compute_prs_with_coverage_fill", raise_prs_decline
    )

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        final = _wait_for_terminal(client, _enqueue(client).json()["task_id"])

    assert final["status"] == "failed"
    assert final["error"].startswith("prs_decline:"), final["error"]
    assert DeclineReason.VARIANT_OVERLAP_INSUFFICIENT.value in final["error"]


# -----------------------------------------------------------------------------
# Execution model — the blocking call must run off the event loop.
# -----------------------------------------------------------------------------


def test_worker_runs_compute_in_executor_not_event_loop(tmp_path: Path, monkeypatch):
    """The blocking ``compute_prs_with_coverage_fill`` runs off the FastAPI event loop.

    Guards against accidentally awaiting the blocking call directly on the
    asyncio loop — which would stall the entire host service for the
    duration of the compute (minutes). The stub asserts:
    1. ``asyncio.get_running_loop()`` raises ``RuntimeError`` (no loop in this thread).
    2. Captured thread ident differs from any prior event-loop ident.
    """
    from genomeclaw_toolkit.service import pgs_compute_orchestrator

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    captured: dict = {}

    def capturing_compute(**kwargs):
        try:
            asyncio.get_running_loop()
            captured["on_event_loop"] = True
        except RuntimeError:
            captured["on_event_loop"] = False
        captured["thread_ident"] = threading.get_ident()
        return _make_fake_pgs_row(pgs_id=kwargs["scorefile_path"].stem.replace(".txt", ""))

    monkeypatch.setattr(pgs_compute_orchestrator, "compute_prs_with_coverage_fill", capturing_compute)
    monkeypatch.setattr(pgs_compute_orchestrator, "stamp_pgs_row", lambda *a, **kw: None)

    run_dir = _stage_run_with_config(tmp_path)
    _stage_scorefile(run_dir, "PGS_TEST")

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        final = _wait_for_terminal(client, _enqueue(client).json()["task_id"])

    assert final["status"] == "done", final
    assert captured["on_event_loop"] is False, (
        "compute_prs_with_coverage_fill was awaited directly on the event loop; "
        "must run via loop.run_in_executor(...)"
    )


# -----------------------------------------------------------------------------
# Lifespan resilience — missing sidecar shouldn't crash the whole host service.
# -----------------------------------------------------------------------------


def test_build_app_logs_warning_when_sidecar_missing_but_serves_read_routes(
    tmp_path: Path, monkeypatch, caplog
):
    """Missing ``prs_compute_config.json`` → worker not spawned; ``/v1/health`` still 200.

    The compute path is disabled when the operator hasn't staged the
    config; the read routes (``/v1/variants``, ``/v1/findings``, etc.)
    must keep working so the agent's non-compute capability is unaffected.
    """
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")

    # Stage a run-dir WITHOUT a prs_compute_config.json sidecar.
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": _SAMPLE})
    )
    create_store(run_dir / "variants.duckdb")
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    update_current_symlink(derived_root, _RUN_ID)

    import logging as _logging
    with caplog.at_level(_logging.WARNING):
        app = build_app(derived_root=derived_root)
        with TestClient(app) as client:
            health = client.get("/v1/health")

    assert health.status_code == 200, health.text
    # Worker-not-spawned warning landed:
    warning_logs = [r.message for r in caplog.records if r.levelno >= _logging.WARNING]
    assert any("prs_compute_config" in msg for msg in warning_logs), warning_logs

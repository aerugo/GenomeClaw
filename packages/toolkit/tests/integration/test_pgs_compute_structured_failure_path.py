"""When the compute function raises, the task transitions to status=failed
with a structured error — never silently to done.

Complements `test_pgs_compute_ack_without_row_repro.py` (which covers
the specific "missing prs_compute_config.json" path the
investigate-pgs-compute-ack-without-row plan fixed); this test covers
the broader structural rule that ANY raise from the compute function
produces a `failed` status with a structured `error` value mapping to
`_structured_error()`, NOT a `done` status with no row.

The Phase 3 invariant test `test_invR002_pgs_compute_task_row_consistency.py`
enforces the cross-table consistency at the data layer. This test
enforces the same rule at the worker-loop layer: every raise transitions
to failed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)

_RUN_ID = "2026-05-25T00-00-00Z-structured-failure"
_SAMPLE = "structured-failure-fixture"


def _stage_run_with_config(tmp_path: Path) -> Path:
    """Stage a derived run + a minimal prs_compute_config.json sidecar."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": _SAMPLE})
    )
    create_store(run_dir / "variants.duckdb")
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    (run_dir / "prs_compute_config.json").write_text(
        json.dumps(
            {
                "sample_id": _SAMPLE,
                "cram_path": str(tmp_path / "sample.cram"),
                "reference_root": str(tmp_path / "reference"),
                "scorefile_root": str(tmp_path / "scorefiles"),
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


def _enqueue(client: TestClient, *, pgs_id: str = "PGS_TEST") -> str:
    r = client.post(
        "/v1/pgs/compute",
        json={
            "pgs_id": pgs_id,
            "trait_label": "test",
            "rationale": "structured-failure positive test",
            "requested_for_question": "n/a",
        },
    )
    assert r.status_code == 202, (r.status_code, r.text)
    return r.json()["task_id"]


def _wait_for_terminal(client: TestClient, task_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(f"/v1/pgs/compute/{task_id}")
        body = r.json()
        if body.get("status") in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not reach terminal status within {timeout_s}s")


def test_compute_fn_raise_transitions_task_to_failed_not_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _real_compute_fn raises, the worker MUST mark the task failed."""
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    _stage_run_with_config(tmp_path)

    class _SyntheticComputeError(RuntimeError):
        pass

    async def raising_compute(*_args, **_kwargs):
        raise _SyntheticComputeError("synthetic compute failure for positive test")

    # Patch app.py's bound _real_compute_fn (the lifespan's functools.partial
    # captures the function object resolved from app.py's import, not the
    # orchestrator module's attribute).
    monkeypatch.setattr("genomeclaw_toolkit.service.app._real_compute_fn", raising_compute)

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        task_id = _enqueue(client)
        final = _wait_for_terminal(client, task_id)

    assert final["status"] == "failed", (
        f"compute_fn raised but task ended at status={final['status']!r}; "
        "expected 'failed'. A raise from compute_fn must NEVER silently "
        "produce 'done' — that's the exact ack-without-row failure mode."
    )
    err = final.get("error") or ""
    # _structured_error maps unknown exceptions to worker_unexpected_error:<ClassName>.
    assert err, "task failed but error field is empty; expected structured error"
    assert "worker_unexpected_error" in err or "_SyntheticComputeError" in err, (
        f"error field {err!r} doesn't carry the exception class name; "
        "agent can't paraphrase the actual failure cause"
    )


def test_compute_fn_raises_prs_compute_config_missing_transitions_to_structured_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _real_compute_fn raises PrsComputeConfigMissingError, the task
    transitions to failed:prs_compute_config_missing.

    This is the specific mapping added in the
    investigate-pgs-compute-ack-without-row Phase 2 fix —
    `_structured_error` maps PrsComputeConfigMissingError to a stable
    `prs_compute_config_missing` string the agent can branch on.
    """
    from genomeclaw_toolkit.service.pgs_compute_config import (
        PrsComputeConfigMissingError,
    )

    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.02")
    _stage_run_with_config(tmp_path)

    async def raising_compute(*_args, **_kwargs):
        raise PrsComputeConfigMissingError(
            "synthetic for test: prs_compute_config.json not found at /test/path"
        )

    monkeypatch.setattr("genomeclaw_toolkit.service.app._real_compute_fn", raising_compute)

    app = build_app(derived_root=tmp_path / "derived")
    with TestClient(app) as client:
        task_id = _enqueue(client)
        final = _wait_for_terminal(client, task_id)

    assert final["status"] == "failed", final
    assert final["error"] == "prs_compute_config_missing", (
        f"expected error='prs_compute_config_missing' (the stable mapping the "
        f"investigate-pgs-compute-ack-without-row fix added to _structured_error); "
        f"got error={final['error']!r}"
    )

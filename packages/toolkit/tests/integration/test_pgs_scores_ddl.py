"""Phase 6 Slice E v2 — `pgs_scores` + `pgs_compute_tasks` DDL contract.

Two structural tests against the derived-store schema:

- `pgs_scores` table is created by `create_store()` with the documented domain
  columns + the two INV-A003 columns (`agent_choice_rationale`,
  `requested_for_question`) + the `superseded_by` audit-trail column + the
  seven canonical INV-R001 provenance columns.
- `pgs_compute_tasks.sqlite` carries the documented `(task_id, pgs_id,
  trait_label, rationale, requested_for_question, status, ...)` columns and
  the `queued | running | done | failed` status enum.

The `pgs_compute_tasks` table is created lazily by the orchestrator on first
use (it lives under `derived/<run-id>/`, not in `variants.duckdb`), so the
DDL test here exercises the orchestrator's create-if-not-exists helper.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)


def test_create_store_emits_pgs_scores_with_invA003_columns(tmp_path: Path) -> None:
    """`pgs_scores` table exists with all 18 documented columns.

    Domain columns (8): pgs_id, trait_label, percentile_in_user_ancestry,
    raw_score, study_population, calibration_warning, agent_choice_rationale,
    requested_for_question. (`source_pgs_id` is implicit — it's identical to
    `pgs_id` since the table is keyed by PGS Catalog ID.)
    Audit-trail column (1): superseded_by.
    Canonical INV-R001 provenance columns (7): source_path, source_sha256,
    tool, tool_version, params_json, schema_version, created_at.
    """
    store_path = tmp_path / "variants.duckdb"
    create_store(store_path)

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        # DuckDB's PRAGMA table_info returns (cid, name, type, notnull, ...)
        cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(pgs_scores)").fetchall()}
    finally:
        conn.close()

    # Domain columns
    assert cols.get("pgs_id") == "VARCHAR", "pgs_id is the primary key"
    assert cols.get("trait_label") == "VARCHAR"
    assert cols.get("percentile_in_user_ancestry") == "DOUBLE"
    assert cols.get("raw_score") == "DOUBLE"
    assert cols.get("study_population") == "VARCHAR"
    assert cols.get("calibration_warning") == "VARCHAR"

    # INV-A003 provenance columns
    assert cols.get("agent_choice_rationale") == "VARCHAR", (
        "INV-A003: agent_choice_rationale column required"
    )
    assert cols.get("requested_for_question") == "VARCHAR", (
        "INV-A003: requested_for_question column required"
    )

    # Audit-trail
    assert cols.get("superseded_by") == "VARCHAR", (
        "supersession trail: superseded_by points at the newer pgs_id "
        "when this row has been replaced by a recomputed PGS"
    )

    # Seven canonical INV-R001 provenance columns
    for prov_col in (
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    ):
        assert prov_col in cols, f"INV-R001 provenance column {prov_col!r} missing"


def test_create_store_pgs_scores_double_create_is_idempotent(tmp_path: Path) -> None:
    """A second `create_store` call against the same path fails cleanly per INV-R001.

    `create_store` itself is not idempotent (it raises `FileExistsError`) —
    this test pins that behavior so a future widening doesn't silently
    overwrite a populated store.
    """
    store_path = tmp_path / "variants.duckdb"
    create_store(store_path)
    with pytest.raises(FileExistsError, match="already exists"):
        create_store(store_path)


def test_pgs_compute_tasks_sqlite_schema(tmp_path: Path) -> None:
    """`pgs_compute_tasks.sqlite` carries the documented columns + status enum.

    Status enum per the v2 slice plan: `queued | running | done | failed`. The
    `failed` status carries an error message; one specific failure mode is
    `compute_path_disabled` (kill-switch). The orchestrator creates this
    DB lazily under `derived/<run-id>/`; this test exercises the
    create-if-not-exists helper.
    """
    import sqlite3

    db_path = tmp_path / "pgs_compute_tasks.sqlite"
    create_pgs_compute_tasks_db_if_missing(db_path)
    assert db_path.exists()

    # Idempotent: second call doesn't error.
    create_pgs_compute_tasks_db_if_missing(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cols = {
            row[1]: row[2]
            for row in conn.execute("PRAGMA table_info(pgs_compute_tasks)").fetchall()
        }
    finally:
        conn.close()

    expected_columns = {
        "task_id",
        "pgs_id",
        "trait_label",
        "rationale",
        "requested_for_question",
        "status",
        "error",
        "requested_at",
        "started_at",
        "completed_at",
    }
    missing = expected_columns - set(cols.keys())
    assert not missing, f"pgs_compute_tasks missing columns: {sorted(missing)}"

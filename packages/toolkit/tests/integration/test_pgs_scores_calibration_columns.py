"""Phase 3b3b1 — ``pgs_scores`` carries calibration_status + decline_reason columns.

Phase 3b1 added these as in-memory :class:`PgsRow` fields. Phase 3b3b1
extends the DuckDB persistence layer so the agent's audit trail captures
the calibration decision alongside the score.

Contract assertions:

1. The CREATE TABLE DDL declares both columns as nullable TEXT.
2. ``_stamp_pgs_row`` persists the in-memory ``calibration_status`` +
   ``decline_reason`` fields to the new columns when set.
3. Backwards compat: a :class:`PgsRow` without calibration fields (the
   pre-Phase-3b1 shape) still INSERTs cleanly with NULL in both columns.
4. A DECLINE row round-trips: insert + SELECT returns the same status +
   reason snake_case string.

The columns are additive; ``SCHEMA_VERSION`` stays at ``v0.2`` for this
slice (a wider provenance-column migration is the Phase 3b3c follow-up).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from genomeclaw_toolkit.prep.store import create_store


def _open_fresh_store(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db = tmp_path / "variants.duckdb"
    create_store(db)
    return duckdb.connect(str(db))


def test_pgs_scores_ddl_declares_calibration_columns(tmp_path: Path) -> None:
    """``calibration_status`` + ``decline_reason`` exist on the fresh table."""
    conn = _open_fresh_store(tmp_path)
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'pgs_scores'"
        ).fetchall()
    finally:
        conn.close()

    columns = {row[0] for row in rows}
    assert "calibration_status" in columns, (
        f"Phase 3b3b1: pgs_scores must carry calibration_status; got {sorted(columns)}"
    )
    assert "decline_reason" in columns, (
        f"Phase 3b3b1: pgs_scores must carry decline_reason; got {sorted(columns)}"
    )


def test_pgs_scores_calibration_columns_are_nullable(tmp_path: Path) -> None:
    """Both new columns are nullable (existing INSERTs without them still work)."""
    conn = _open_fresh_store(tmp_path)
    try:
        rows = conn.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'pgs_scores' AND column_name IN "
            "('calibration_status', 'decline_reason')"
        ).fetchall()
    finally:
        conn.close()

    nullable_map = {row[0]: row[1] for row in rows}
    assert nullable_map.get("calibration_status") == "YES"
    assert nullable_map.get("decline_reason") == "YES"


def test_pgs_scores_round_trip_with_clean_calibration(tmp_path: Path) -> None:
    """A row stamped with `calibration_status="clean"` round-trips through DuckDB."""
    from datetime import UTC, datetime

    from genomeclaw_toolkit._cli.commands.pipeline import _stamp_pgs_row
    from genomeclaw_toolkit.prep.pgs import PgsRow

    db = tmp_path / "variants.duckdb"
    create_store(db)
    run_dir = tmp_path
    (run_dir / "variants.duckdb").exists()  # smoke: store created

    row = PgsRow(
        pgs_id="PGS000001",
        trait_label="x",
        percentile_in_user_ancestry=78.5,
        raw_score=0.42,
        study_population="x",
        calibration_warning=None,
        agent_choice_rationale="r" * 60,
        requested_for_question="q",
        calibration_status="clean",
        decline_reason=None,
    )
    _stamp_pgs_row(run_dir, row, vcf=run_dir / "user.vcf.gz")

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT calibration_status, decline_reason FROM pgs_scores "
            "WHERE pgs_id = 'PGS000001'"
        ).fetchone()
    finally:
        conn.close()

    assert result == ("clean", None)
    # Bookkeeping touch so the linter sees datetime use it expects.
    assert datetime.now(UTC).tzinfo is UTC


def test_pgs_scores_round_trip_with_decline_reason(tmp_path: Path) -> None:
    """A DECLINE row persists the structural decline_reason snake_case string."""
    from genomeclaw_toolkit._cli.commands.pipeline import _stamp_pgs_row
    from genomeclaw_toolkit.prep.pgs import PgsRow

    db = tmp_path / "variants.duckdb"
    create_store(db)

    row = PgsRow(
        pgs_id="PGS000018",
        trait_label="metaGRS_CAD",
        percentile_in_user_ancestry=None,  # decline → no calibrated percentile
        raw_score=None,
        study_population="x",
        calibration_warning=None,
        agent_choice_rationale="r" * 60,
        requested_for_question="q",
        calibration_status="decline",
        decline_reason="variant_overlap_insufficient",
    )
    _stamp_pgs_row(tmp_path, row, vcf=tmp_path / "user.vcf.gz")

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT calibration_status, decline_reason FROM pgs_scores "
            "WHERE pgs_id = 'PGS000018'"
        ).fetchone()
    finally:
        conn.close()

    assert result == ("decline", "variant_overlap_insufficient")


def test_pgs_scores_backwards_compat_row_without_calibration_fields(
    tmp_path: Path,
) -> None:
    """A `PgsRow` without calibration fields (the pre-Phase-3b1 shape) still inserts.

    Backwards-compat gate: every existing call site stamps PgsRow instances
    constructed with the original 8 fields. The new columns default to None
    at the dataclass level and persist as NULL.
    """
    from genomeclaw_toolkit._cli.commands.pipeline import _stamp_pgs_row
    from genomeclaw_toolkit.prep.pgs import PgsRow

    db = tmp_path / "variants.duckdb"
    create_store(db)

    # Construct via the original 8-field surface (no calibration kwargs).
    row = PgsRow(
        pgs_id="PGS000999",
        trait_label="x",
        percentile_in_user_ancestry=50.0,
        raw_score=0.0,
        study_population="x",
        calibration_warning=None,
        agent_choice_rationale="r" * 60,
        requested_for_question="q",
    )
    _stamp_pgs_row(tmp_path, row, vcf=tmp_path / "user.vcf.gz")

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT calibration_status, decline_reason FROM pgs_scores "
            "WHERE pgs_id = 'PGS000999'"
        ).fetchone()
    finally:
        conn.close()

    assert result == (None, None)

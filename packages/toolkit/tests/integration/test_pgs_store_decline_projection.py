"""`query_pgs_computed` + `query_pgs_computed_list` project decline fields.

Phase 3b3b1 added `calibration_status` and `decline_reason` columns to
`pgs_scores`. The read path in `service/store.py` did not include them in
`_PGS_SCORES_LIST_COLUMNS` or `_PGS_SCORES_GET_COLUMNS`, so the values were
silently dropped at the HTTP boundary.

These tests build a fixture DuckDB using the production DDL (via
`create_store`) + a real INSERT through `stamp_pgs_row`, then call the
service-layer query helpers and assert both fields appear in the returned
dict. Per `INV-A003`, a provenance field that exists at the DB layer but
is absent from the read-path projection is a traceability gap.
"""

from __future__ import annotations

from pathlib import Path

from genomeclaw_toolkit.prep.pgs import PgsRow, stamp_pgs_row
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.service.store import (
    query_pgs_computed,
    query_pgs_computed_list,
)


def _seed_pgs_scores(
    run_dir: Path,
    *,
    pgs_id: str,
    calibration_status: str | None,
    decline_reason: str | None,
) -> None:
    """Materialise a single `pgs_scores` row using the production INSERT path."""
    db = run_dir / "variants.duckdb"
    if not db.exists():
        create_store(db)
    row = PgsRow(
        pgs_id=pgs_id,
        trait_label="metaGRS_CAD",
        percentile_in_user_ancestry=87.0 if calibration_status != "decline" else None,
        raw_score=0.42 if calibration_status != "decline" else None,
        study_population="European-ancestry meta-analysis",
        calibration_warning=None,
        agent_choice_rationale=(
            "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS; "
            "considered PGS004696 and PGS003725 as alternatives."
        ),
        requested_for_question="cad risk question",
        calibration_status=calibration_status,
        decline_reason=decline_reason,
    )
    stamp_pgs_row(run_dir, row, vcf=run_dir / "user.vcf.gz")


def test_pgs_store_query_returns_calibration_status_decline(tmp_path: Path) -> None:
    """A DECLINE row round-trips through `query_pgs_computed` with both fields populated."""
    _seed_pgs_scores(
        tmp_path,
        pgs_id="PGS000099",
        calibration_status="decline",
        decline_reason="variant_overlap_insufficient",
    )

    result = query_pgs_computed(run_dir=tmp_path, pgs_id="PGS000099")

    assert result is not None
    assert result["calibration_status"] == "decline"
    assert result["decline_reason"] == "variant_overlap_insufficient"


def test_pgs_store_query_returns_calibration_status_clean(tmp_path: Path) -> None:
    """A CLEAN row round-trips with `decline_reason=None`."""
    _seed_pgs_scores(
        tmp_path,
        pgs_id="PGS000018",
        calibration_status="clean",
        decline_reason=None,
    )

    result = query_pgs_computed(run_dir=tmp_path, pgs_id="PGS000018")

    assert result is not None
    assert result["calibration_status"] == "clean"
    assert result["decline_reason"] is None


def test_pgs_store_query_accepts_legacy_null_calibration(tmp_path: Path) -> None:
    """A pre-Phase-3a row (NULL calibration_status) round-trips with both fields None."""
    _seed_pgs_scores(
        tmp_path,
        pgs_id="PGS000999",
        calibration_status=None,
        decline_reason=None,
    )

    result = query_pgs_computed(run_dir=tmp_path, pgs_id="PGS000999")

    assert result is not None
    assert result["calibration_status"] is None
    assert result["decline_reason"] is None


def test_pgs_store_list_returns_calibration_status(tmp_path: Path) -> None:
    """`query_pgs_computed_list` projects both decline fields on every row."""
    _seed_pgs_scores(
        tmp_path,
        pgs_id="PGS000018",
        calibration_status="clean",
        decline_reason=None,
    )
    _seed_pgs_scores(
        tmp_path,
        pgs_id="PGS000099",
        calibration_status="decline",
        decline_reason="variant_overlap_insufficient",
    )

    rows, total = query_pgs_computed_list(run_dir=tmp_path)

    assert total == 2
    by_id = {row["pgs_id"]: row for row in rows}
    assert by_id["PGS000018"]["calibration_status"] == "clean"
    assert by_id["PGS000018"]["decline_reason"] is None
    assert by_id["PGS000099"]["calibration_status"] == "decline"
    assert by_id["PGS000099"]["decline_reason"] == "variant_overlap_insufficient"


def test_invA003_pgs_provenance_payload_complete(tmp_path: Path) -> None:
    """INV-A003: every `pgs_scores` provenance column reaches the read path.

    A field that exists in the DB but is absent from `_PGS_SCORES_GET_COLUMNS`
    is a silent traceability gap. This test asserts the returned dict carries
    the full known provenance surface (the two new fields are part of it).
    """
    _seed_pgs_scores(
        tmp_path,
        pgs_id="PGS000018",
        calibration_status="warning",
        decline_reason=None,
    )

    result = query_pgs_computed(run_dir=tmp_path, pgs_id="PGS000018")

    assert result is not None
    expected_keys = {
        "pgs_id",
        "trait_label",
        "percentile_in_user_ancestry",
        "raw_score",
        "study_population",
        "calibration_warning",
        "calibration_status",
        "decline_reason",
        "agent_choice_rationale",
        "requested_for_question",
        "superseded_by",
        "source_pgs_id",
    }
    assert expected_keys.issubset(result.keys()), (
        f"INV-A003 violation: missing keys "
        f"{expected_keys - set(result.keys())} from query_pgs_computed payload"
    )

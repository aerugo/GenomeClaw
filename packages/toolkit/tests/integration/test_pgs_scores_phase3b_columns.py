"""`stamp_pgs_row` persists Phase 3b columns on `pgs_scores` (Plan 7 Phase 2).

Per `prs-calibration-phase3b` Phases 1 + 2: a `PgsRow` instance carrying
the three new fields lands them on the `pgs_scores` row at INSERT time.
The fields are nullable; pre-Phase-3b callers that omit them produce
NULL on the row (backwards compat).
"""

from __future__ import annotations

from pathlib import Path


def test_stamp_pgs_row_persists_effect_weight_match_rate(tmp_path: Path) -> None:
    """`PgsRow.effect_weight_match_rate=0.42` → stored as 0.42 in `pgs_scores`."""
    import duckdb

    from genomeclaw_toolkit.prep.pgs import PgsRow, stamp_pgs_row

    row = PgsRow(
        pgs_id="PGS000018",
        trait_label="Test",
        percentile_in_user_ancestry=55.0,
        raw_score=0.123,
        study_population="European",
        calibration_warning=None,
        agent_choice_rationale="test",
        requested_for_question="test",
        calibration_status="clean",
        decline_reason=None,
        effect_weight_match_rate=0.42,
    )
    fake_vcf = tmp_path / "merged.vcf.gz"
    fake_vcf.touch()
    stamp_pgs_row(tmp_path, row, vcf=fake_vcf)

    conn = duckdb.connect(str(tmp_path / "variants.duckdb"), read_only=True)
    try:
        stored = conn.execute(
            "SELECT effect_weight_match_rate, "
            "fraposa_min_mahalanobis_distance, fraposa_nearest_superpop "
            "FROM pgs_scores WHERE pgs_id = ?",
            ["PGS000018"],
        ).fetchone()
    finally:
        conn.close()

    assert stored is not None
    assert stored[0] == 0.42
    assert stored[1] is None
    assert stored[2] is None


def test_stamp_pgs_row_persists_fraposa_distance_and_superpop(tmp_path: Path) -> None:
    """`PgsRow.fraposa_*` round-trip through `pgs_scores`."""
    import duckdb

    from genomeclaw_toolkit.prep.pgs import PgsRow, stamp_pgs_row

    row = PgsRow(
        pgs_id="PGS000018",
        trait_label="Test",
        percentile_in_user_ancestry=55.0,
        raw_score=0.123,
        study_population="European",
        calibration_warning=None,
        agent_choice_rationale="test",
        requested_for_question="test",
        calibration_status="clean",
        decline_reason=None,
        effect_weight_match_rate=0.95,
        fraposa_min_mahalanobis_distance=2.3,
        fraposa_nearest_superpop="EUR",
    )
    fake_vcf = tmp_path / "merged.vcf.gz"
    fake_vcf.touch()
    stamp_pgs_row(tmp_path, row, vcf=fake_vcf)

    conn = duckdb.connect(str(tmp_path / "variants.duckdb"), read_only=True)
    try:
        stored = conn.execute(
            "SELECT effect_weight_match_rate, "
            "fraposa_min_mahalanobis_distance, fraposa_nearest_superpop, "
            "schema_version "
            "FROM pgs_scores WHERE pgs_id = ?",
            ["PGS000018"],
        ).fetchone()
    finally:
        conn.close()

    assert stored is not None
    assert stored[0] == 0.95
    assert stored[1] == 2.3
    assert stored[2] == "EUR"
    assert stored[3] == "v0.4"  # INV-R001 schema_version recorded on the row


def test_stamp_pgs_row_backwards_compat_phase3b_fields_default_to_none(
    tmp_path: Path,
) -> None:
    """A PgsRow built with only the pre-Phase-3b fields lands NULLs in the new columns."""
    import duckdb

    from genomeclaw_toolkit.prep.pgs import PgsRow, stamp_pgs_row

    row = PgsRow(
        pgs_id="PGS000018",
        trait_label="Test",
        percentile_in_user_ancestry=55.0,
        raw_score=0.123,
        study_population="European",
        calibration_warning=None,
        agent_choice_rationale="test",
        requested_for_question="test",
    )
    fake_vcf = tmp_path / "merged.vcf.gz"
    fake_vcf.touch()
    stamp_pgs_row(tmp_path, row, vcf=fake_vcf)

    conn = duckdb.connect(str(tmp_path / "variants.duckdb"), read_only=True)
    try:
        stored = conn.execute(
            "SELECT effect_weight_match_rate, "
            "fraposa_min_mahalanobis_distance, fraposa_nearest_superpop "
            "FROM pgs_scores WHERE pgs_id = ?",
            ["PGS000018"],
        ).fetchone()
    finally:
        conn.close()

    assert stored is not None
    assert stored == (None, None, None)

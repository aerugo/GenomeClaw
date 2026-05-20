"""prs-non-imputed-wgs Phase 1 — ``pgs_scores.params_json`` carries
``min_overlap_used`` + ``keep_ambiguous_used`` per INV-R001.

Why the persisted ``params_json`` matters: a future debugger or report
reader must be able to tell, from the stored row alone, what
``--min_overlap`` threshold pgsc_calc was invoked with. Without these
keys the persisted percentile is uninterpretable (was 0.5 used? 0.75?
0.0?) and the row fails INV-R001 (Rebuildability).

Specifically:

* ``min_overlap_used`` — the float value passed to pgsc_calc ``--min_overlap``.
  Records the input-class-appropriate threshold for non-imputed single-
  sample WGS (0.5 default; env-var override under
  ``GENOMECLAW_PGSC_CALC_MIN_OVERLAP``).
* ``keep_ambiguous_used`` — the boolean passed to pgsc_calc
  ``--keep_ambiguous``. Currently always ``false`` (load-bearing per the
  research findings doc), but the key's presence in ``params_json`` makes
  the decision auditable.

INV-R002 (Never Cache a Degenerate Result) is preserved: the existing
0-record cache guard is unchanged. INV-R001 is strengthened: the row
now carries enough provenance to recompute against the same parameters.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from genomeclaw_toolkit.prep.store import create_store


def _make_decline_row(pgs_id: str = "PGS000018"):
    """Build a minimal :class:`PgsRow` for params_json round-trip tests."""
    from genomeclaw_toolkit.prep.pgs import PgsRow

    return PgsRow(
        pgs_id=pgs_id,
        trait_label="test trait",
        percentile_in_user_ancestry=78.5,
        raw_score=0.42,
        study_population="EUR",
        calibration_warning=None,
        agent_choice_rationale="r" * 60,
        requested_for_question="why?",
        calibration_status="clean",
        decline_reason=None,
    )


def test_stamp_pgs_row_records_min_overlap_used_in_params_json(tmp_path: Path) -> None:
    """A ``_stamp_pgs_row`` call with ``min_overlap_used=0.5`` persists that
    key in ``pgs_scores.params_json`` (INV-R001 rebuildability)."""
    from genomeclaw_toolkit._cli.commands.pipeline import _stamp_pgs_row

    db = tmp_path / "variants.duckdb"
    create_store(db)
    row = _make_decline_row("PGS000018")
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"x")

    _stamp_pgs_row(
        tmp_path, row, vcf=vcf, min_overlap_used=0.5, keep_ambiguous_used=False
    )

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT params_json FROM pgs_scores WHERE pgs_id = 'PGS000018'"
        ).fetchone()
    finally:
        conn.close()

    assert result is not None, "row failed to INSERT"
    params = json.loads(result[0])
    assert params.get("min_overlap_used") == 0.5, (
        f"params_json MUST carry min_overlap_used per INV-R001; got params={params!r}"
    )


def test_stamp_pgs_row_records_keep_ambiguous_used_false_in_params_json(
    tmp_path: Path,
) -> None:
    """``keep_ambiguous_used`` is recorded as the boolean ``false`` (not a
    string ``"false"``), so JSON consumers can reason on the type cleanly."""
    from genomeclaw_toolkit._cli.commands.pipeline import _stamp_pgs_row

    db = tmp_path / "variants.duckdb"
    create_store(db)
    row = _make_decline_row("PGS000018")
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"x")

    _stamp_pgs_row(
        tmp_path, row, vcf=vcf, min_overlap_used=0.5, keep_ambiguous_used=False
    )

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT params_json FROM pgs_scores WHERE pgs_id = 'PGS000018'"
        ).fetchone()
    finally:
        conn.close()

    assert result is not None
    params = json.loads(result[0])
    # Use ``is False`` (not ``== False``) so a stringly-written "false"
    # (truthy in Python) would fail this assertion.
    assert params.get("keep_ambiguous_used") is False, (
        f"keep_ambiguous_used MUST be the JSON boolean false (not a string); "
        f"got params={params!r}"
    )


def test_stamp_pgs_row_preserves_existing_params_json_keys(tmp_path: Path) -> None:
    """The new keys are ADDITIVE — existing ``pgs_id`` + ``vcf`` keys still land.

    A regression where the new fields replaced rather than extended the
    params_json would erase the prior provenance trail.
    """
    from genomeclaw_toolkit._cli.commands.pipeline import _stamp_pgs_row

    db = tmp_path / "variants.duckdb"
    create_store(db)
    row = _make_decline_row("PGS000018")
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"x")

    _stamp_pgs_row(
        tmp_path, row, vcf=vcf, min_overlap_used=0.5, keep_ambiguous_used=False
    )

    conn = duckdb.connect(str(db), read_only=True)
    try:
        result = conn.execute(
            "SELECT params_json FROM pgs_scores WHERE pgs_id = 'PGS000018'"
        ).fetchone()
    finally:
        conn.close()

    assert result is not None
    params = json.loads(result[0])
    assert params.get("pgs_id") == "PGS000018"
    assert params.get("vcf") == str(vcf)
    assert params.get("min_overlap_used") == 0.5
    assert params.get("keep_ambiguous_used") is False
    # Bookkeeping: keep imports/uses live so the linter doesn't strip them.
    assert datetime.now(UTC).tzinfo is UTC

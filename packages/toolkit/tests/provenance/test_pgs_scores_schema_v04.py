"""`pgs_scores` carries the v0.4 column additions (Plan 7 Phases 1 + 2).

INV-R001: every column added to `pgs_scores` is part of the v0.4 schema.
The three additions are:

- `effect_weight_match_rate` (Phase 1) — DOUBLE, nullable.
- `fraposa_min_mahalanobis_distance` (Phase 2) — DOUBLE, nullable.
- `fraposa_nearest_superpop` (Phase 2) — TEXT, nullable.

`schema_meta` records the schema_version at create time; the test
asserts the seeded value matches the SCHEMA_VERSION constant the
toolkit ships.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def test_pgs_scores_carries_phase3b_columns(tmp_path: Path) -> None:
    """v0.4 store has `effect_weight_match_rate` + the two FRAPOSA columns."""
    from genomeclaw_toolkit.prep.store import create_store

    store_path = tmp_path / "variants.duckdb"
    create_store(store_path)

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        cols = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'pgs_scores'"
            ).fetchall()
        }
    finally:
        conn.close()

    names = {name for name, _ in cols}
    assert "effect_weight_match_rate" in names
    assert "fraposa_min_mahalanobis_distance" in names
    assert "fraposa_nearest_superpop" in names

    # DuckDB reports types as upper-case literals.
    type_by_name = {name: dtype for name, dtype in cols}
    assert type_by_name["effect_weight_match_rate"] == "DOUBLE"
    assert type_by_name["fraposa_min_mahalanobis_distance"] == "DOUBLE"
    assert type_by_name["fraposa_nearest_superpop"] == "VARCHAR"  # DuckDB TEXT → VARCHAR


def test_schema_meta_records_v04_on_fresh_store(tmp_path: Path) -> None:
    """INV-R001: `schema_meta.schema_version` matches the SCHEMA_VERSION constant."""
    from genomeclaw_toolkit.prep.store import create_store
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    store_path = tmp_path / "variants.duckdb"
    create_store(store_path)

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == SCHEMA_VERSION
    assert SCHEMA_VERSION == "v0.4"

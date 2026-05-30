"""SCHEMA_VERSION v0.2 → v0.3 migration via `_reset_variants_table` (Plan 4 Phase 3).

The v0.3 bump adds two columns to `variants`:
- `mane_plus_clinical_transcript` (TEXT, nullable): captures the MANE
  Plus Clinical transcript for the 73 MANE v1.5 genes where Plus
  Clinical adds pathogenic-variant coverage beyond MANE Select.
- `transcript_discordant` (BOOLEAN, nullable): non-NULL on the two
  rows of a dual-row emit (False on Select row, True on Plus Clinical
  row); NULL on every single-row emit.

Migration path: `_reset_variants_table` drops + recreates the variants
table on the current DDL and bumps `schema_meta.schema_version` to
match. Existing `coverage_qc` + `schema_meta` rows are preserved; only
the `schema_version` value is updated.

This test stages a pre-Phase-2 v0.2 store, calls `_reset_variants_table`,
and asserts the migration leaves the table on the v0.3 schema with both
new columns present + the schema_meta row updated.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def test_reset_variants_table_picks_up_v03_columns(tmp_path: Path) -> None:
    """`_reset_variants_table` drops + recreates with the v0.3 column set."""
    from genomeclaw_toolkit.prep.materialize import _reset_variants_table
    from genomeclaw_toolkit.prep.store import create_store

    # Stage a fresh store (Phase 2 DDL now declares the v0.3 columns
    # because that's the current state of `_VARIANTS_DDL`; the migration
    # path is exercised by dropping + recreating).
    store_path = tmp_path / "variants.duckdb"
    create_store(store_path)

    # Manually drop the v0.3 columns to simulate a pre-Phase-2 v0.2 store.
    conn = duckdb.connect(str(store_path))
    try:
        conn.execute("ALTER TABLE variants DROP COLUMN mane_plus_clinical_transcript")
        conn.execute("ALTER TABLE variants DROP COLUMN transcript_discordant")
        # Set schema_meta to v0.2 to mimic a pre-migration store.
        conn.execute("DELETE FROM schema_meta WHERE key = 'schema_version'")
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ["schema_version", "v0.2"],
        )
    finally:
        conn.close()

    # Sanity-check the simulated pre-migration state.
    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'variants'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "mane_plus_clinical_transcript" not in cols, (
        "pre-migration store should not have the v0.3 columns"
    )
    assert "transcript_discordant" not in cols

    # Run the migration.
    _reset_variants_table(store_path)

    # Post-migration: both new columns exist + schema_version is bumped.
    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'variants'"
            ).fetchall()
        }
        version_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    assert "mane_plus_clinical_transcript" in cols
    assert "transcript_discordant" in cols
    assert version_row is not None
    # The migration writes the current SCHEMA_VERSION constant; after
    # `prs-calibration-phase3b` this bumped to v0.4. The variants-table
    # columns the test cares about are still produced (v0.4 is additive
    # on top of v0.3 — it only adds pgs_scores columns).
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    assert version_row[0] == SCHEMA_VERSION


def test_schema_version_constant_is_v0_4() -> None:
    """`SCHEMA_VERSION` is bumped to v0.4 by `prs-calibration-phase3b` Phase 2.

    Adds three nullable `pgs_scores` columns (``effect_weight_match_rate``,
    ``fraposa_min_mahalanobis_distance``, ``fraposa_nearest_superpop``)
    on top of the v0.3 variants-table layout. v0.4 is therefore
    additive-only over v0.3.
    """
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    assert SCHEMA_VERSION == "v0.4"

"""Phase 2 — DuckDB derived-store creation + provenance column stamping.

Sub-phase 2C-A scope: ``create_store(path)`` and ``write_variants(...)``
in [genomeclaw_toolkit.prep.store][]. These cover the **structural** side
of cases 4 (provenance columns populated on every variants row) and 7
(schema_version recorded in the store) — the populated-end-to-end side
lands in 2C-B once ingest runs against a fixture VCF.

The DuckDB schema for the ``variants`` table per
``docs/plans/active/mvp/phases/phase-2.md`` Implementation Details:

```sql
CREATE TABLE variants (
    chrom TEXT NOT NULL, pos INTEGER NOT NULL, id TEXT,
    ref TEXT NOT NULL, alt TEXT NOT NULL, qual REAL,
    filter TEXT, sample_id TEXT NOT NULL, genotype TEXT NOT NULL,
    -- The seven canonical provenance columns (INV-R001)
    source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL,
    tool TEXT NOT NULL, tool_version TEXT NOT NULL,
    params_json TEXT NOT NULL, schema_version TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);
```
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "variants.duckdb"


def _provenance_tag():
    """Return a fresh ProvenanceTag with valid values, bound late so the
    import error from RED is the only failure on the first run."""
    from genomeclaw_toolkit.prep.store import ProvenanceTag

    return ProvenanceTag(
        source_path="/mnt/genomeclaw/raw/test/sample.vcf.gz",
        source_sha256="a" * 64,
        tool="genomeclaw-prep",
        tool_version="0.0.1",
        params_json='{"sample_id": "test"}',
        schema_version="v0.1",
        created_at=datetime(2026, 5, 6, 8, 13, 2, tzinfo=UTC),
    )


def _variant_rows():
    return [
        {
            "chrom": "chr1",
            "pos": 1000,
            "id": "rs1",
            "ref": "A",
            "alt": "G",
            "qual": 100.0,
            "filter": "PASS",
            "sample_id": "test-001",
            "genotype": "0/1",
        },
        {
            "chrom": "chr17",
            "pos": 43044295,
            "id": None,  # ID is nullable
            "ref": "G",
            "alt": "T,A",  # multi-allelic stored as-is in v0.1
            "qual": None,  # QUAL is nullable
            "filter": "PASS",
            "sample_id": "test-001",
            "genotype": "1/2",
        },
    ]


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def test_create_store_creates_variants_and_schema_meta_tables(store_path: Path) -> None:
    """Fresh ``create_store`` produces a DuckDB file with the canonical tables."""
    from genomeclaw_toolkit.prep.store import create_store

    create_store(store_path)
    assert store_path.exists()

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        names = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    finally:
        conn.close()

    assert "variants" in names
    assert "schema_meta" in names
    assert "coverage_qc" in names


def test_create_store_records_schema_version(store_path: Path) -> None:
    """Case 7 (structural): schema_meta carries the active ``schema_version``.

    Phase 2/3 ran v0.1; Phase 4A bumped to v0.2 (adds ClinVar columns).
    The exact value is whatever ``genomeclaw_toolkit.schemas.SCHEMA_VERSION``
    is at the moment ``create_store`` runs.
    """
    from genomeclaw_toolkit.prep.store import create_store
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    create_store(store_path)

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    assert version is not None
    assert version[0] == SCHEMA_VERSION


def test_variants_table_has_all_canonical_provenance_columns(store_path: Path) -> None:
    """INV-R001: the ``variants`` table declares the seven canonical columns."""
    from genomeclaw_toolkit.prep.store import create_store
    from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS

    create_store(store_path)

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        cols = {row[0] for row in conn.execute("DESCRIBE variants").fetchall()}
    finally:
        conn.close()

    for col in PROVENANCE_COLUMNS:
        assert col in cols, f"missing provenance column: {col}"


def test_create_store_refuses_to_overwrite_existing_file(store_path: Path) -> None:
    """``create_store`` must not silently clobber an existing DuckDB file."""
    from genomeclaw_toolkit.prep.store import create_store

    store_path.write_bytes(b"PRIOR-CONTENTS")
    with pytest.raises(FileExistsError):
        create_store(store_path)
    assert store_path.read_bytes() == b"PRIOR-CONTENTS"


# ---------------------------------------------------------------------------
# Variant writes — provenance stamping
# ---------------------------------------------------------------------------


def test_invR001_write_variants_stamps_seven_provenance_columns(store_path: Path) -> None:
    """Case 4 (structural): every emitted row has all seven provenance columns populated."""
    from genomeclaw_toolkit.prep.store import create_store, write_variants
    from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS

    create_store(store_path)
    tag = _provenance_tag()
    write_variants(store_path, _variant_rows(), tag=tag, work_dir=store_path.parent / "work")

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        cols = ", ".join(PROVENANCE_COLUMNS)
        result = conn.execute(f"SELECT {cols} FROM variants").fetchall()
    finally:
        conn.close()

    assert len(result) == 2
    for row in result:
        for value in row:
            assert value is not None


def test_write_variants_preserves_domain_columns(store_path: Path) -> None:
    """Round-trip: writing two rows yields two rows with the right domain values."""
    from genomeclaw_toolkit.prep.store import create_store, write_variants

    create_store(store_path)
    write_variants(
        store_path, _variant_rows(), tag=_provenance_tag(), work_dir=store_path.parent / "work"
    )

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        rows = conn.execute(
            "SELECT chrom, pos, id, ref, alt, qual, filter, sample_id, genotype "
            "FROM variants ORDER BY chrom, pos"
        ).fetchall()
    finally:
        conn.close()

    # chr1 row, then chr17 row (lex order).
    assert rows[0][0] == "chr1"
    assert rows[0][1] == 1000
    assert rows[0][2] == "rs1"
    assert rows[1][0] == "chr17"
    assert rows[1][2] is None  # nullable id
    assert rows[1][4] == "T,A"  # multi-allelic preserved as-is


def test_write_variants_handles_empty_input(store_path: Path) -> None:
    """An empty rows list is allowed (and a no-op): a fixture with zero variants
    in a region produces a valid-but-empty store."""
    from genomeclaw_toolkit.prep.store import create_store, write_variants

    create_store(store_path)
    write_variants(store_path, [], tag=_provenance_tag(), work_dir=store_path.parent / "work")

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        count = conn.execute("SELECT COUNT(*) FROM variants").fetchone()
    finally:
        conn.close()

    assert count is not None
    assert count[0] == 0


def test_write_variants_rejects_missing_required_field(store_path: Path) -> None:
    """A row missing a NOT NULL domain column is refused, surfaced as a ValueError."""
    from genomeclaw_toolkit.prep.store import create_store, write_variants

    create_store(store_path)
    bad_row = {
        # Missing 'chrom' — a NOT NULL column.
        "pos": 1000,
        "id": "rs1",
        "ref": "A",
        "alt": "G",
        "qual": None,
        "filter": "PASS",
        "sample_id": "test-001",
        "genotype": "0/1",
    }
    with pytest.raises(ValueError):
        write_variants(
            store_path, [bad_row], tag=_provenance_tag(), work_dir=store_path.parent / "work"
        )


def test_write_variants_uses_same_provenance_tag_on_all_rows(store_path: Path) -> None:
    """One ``write_variants`` call stamps the same tag onto every row.

    This is the cleanest enforcement of `INV-R001`: a single call has a
    single tag, so all rows attribute themselves to the same source +
    tool + version. Splitting tags across a write is forbidden by the
    function signature, which only accepts one tag.
    """
    from genomeclaw_toolkit.prep.store import create_store, write_variants

    create_store(store_path)
    tag = _provenance_tag()
    write_variants(store_path, _variant_rows(), tag=tag, work_dir=store_path.parent / "work")

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_path, source_sha256, tool, "
            "tool_version, params_json, schema_version "
            "FROM variants"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1, "all rows must share the same provenance tag"


# ---------------------------------------------------------------------------
# Coverage QC table
# ---------------------------------------------------------------------------


def test_coverage_qc_table_columns_match_schema_module(store_path: Path) -> None:
    """The DDL columns and the Pydantic model agree (defence in depth)."""
    from genomeclaw_toolkit.prep.store import create_store
    from genomeclaw_toolkit.schemas.coverage_qc import COVERAGE_QC_COLUMNS

    create_store(store_path)

    conn = duckdb.connect(str(store_path), read_only=True)
    try:
        cols = {row[0] for row in conn.execute("DESCRIBE coverage_qc").fetchall()}
    finally:
        conn.close()

    for name, _decl in COVERAGE_QC_COLUMNS:
        assert name in cols, f"missing coverage_qc column: {name}"

"""Phase 6 Slice A — `/v1/findings` (list) + `/v1/findings/{id}` (detail) endpoints.

Endpoint contract:

- ``GET /v1/findings?category=...&genes=...&drugs=...&limit=N&offset=M`` — paginated
  list with typed-array filters (per spec Q4). The plugin's
  ``genomeclaw_findings`` tool's TypeBox schema already constrains the
  parameter shape; the host service mirrors it.
- ``GET /v1/findings/{id}`` — single finding detail by id.

`INV-E001` is enforced at the model layer (see test_finding_model.py); the
endpoint tests cover routing + filtering + the INV-P002 shape pin.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app

# Synthetic finding fixture spanning the four documented categories.
# Each finding is constructed to mirror the real-data shape: id, category,
# title, summary, evidence_ref, evidence_quality, gene_symbols, optional
# clinical_escalation, optional drugs.
_FIXTURE_FINDINGS: tuple[dict[str, object], ...] = (
    {
        "id": "fnd-brca2-001",
        "category": "clinical-actionable",
        "title": "BRCA2 pathogenic variant",
        "summary": "Pathogenic variant in BRCA2; confirm with provider.",
        "evidence_ref": "clinvar:RCV000031",
        "evidence_quality": "high",
        "gene_symbols": ["BRCA2"],
        "clinical_escalation": "confirm_with_provider",
        "drugs": None,
    },
    {
        "id": "fnd-cyp2d6-001",
        "category": "clinical-actionable",
        "title": "CYP2D6 *1/*4 — intermediate metabolizer",
        "summary": "Likely reduced CYP2D6 enzyme activity affecting codeine.",
        "evidence_ref": "pharmgkb:PA166104891",
        "evidence_quality": "high",
        "gene_symbols": ["CYP2D6"],
        "clinical_escalation": "confirm_with_provider",
        "drugs": ["codeine", "tramadol"],
    },
    {
        "id": "fnd-lct-001",
        "category": "lifestyle",
        "title": "LCT — lactase persistence (likely tolerant)",
        "summary": "Genotype consistent with lactase persistence.",
        "evidence_ref": "gene_note:LCT",
        "evidence_quality": "moderate",
        "gene_symbols": ["LCT"],
        "clinical_escalation": None,
        "drugs": None,
    },
    {
        "id": "fnd-cad-prs-001",
        "category": "clinical-non-actionable",
        "title": "CAD polygenic risk score — average",
        "summary": "Coronary artery disease PRS within the population average band.",
        "evidence_ref": "pgs_catalog:PGS003725",
        "evidence_quality": "moderate",
        "gene_symbols": [],
        "clinical_escalation": None,
        "drugs": None,
    },
)


def _insert_findings(store_path: Path) -> None:
    """Insert fixture findings into the `findings` table.

    The table is created by `create_store()` (Slice A extends the prep
    schema). Each row's `gene_symbols` + `drugs` are stored as DuckDB
    TEXT[] arrays.
    """
    now = datetime.now(tz=UTC)
    fixture_sha = "f" * 64
    conn = duckdb.connect(str(store_path))
    try:
        for f in _FIXTURE_FINDINGS:
            conn.execute(
                """
                INSERT INTO findings (
                    id, category, title, summary,
                    evidence_ref, evidence_quality,
                    gene_symbols, drugs, clinical_escalation,
                    source_path, source_sha256, tool, tool_version,
                    params_json, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'fixture', ?, 'fixture', '0.0',
                          '{}', ?, ?)
                """,
                [
                    f["id"],
                    f["category"],
                    f["title"],
                    f["summary"],
                    f["evidence_ref"],
                    f["evidence_quality"],
                    f["gene_symbols"],
                    f["drugs"],
                    f["clinical_escalation"],
                    fixture_sha,
                    SCHEMA_VERSION,
                    now,
                ],
            )
    finally:
        conn.close()


def _stage_run_with_findings(derived_root: Path) -> Path:
    """Stage a derived/<run-id>/ with manifest + populated findings table."""
    run_id = "2026-05-15T00-00-00Z-fnd001"
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": run_id, "schema_version": SCHEMA_VERSION, "sample_id": "fixture-sample"}
        )
    )

    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    _insert_findings(store_path)

    update_current_symlink(derived_root, run_id)
    return run_dir


def test_findings_list_returns_all_when_unfiltered(tmp_path: Path) -> None:
    """`GET /v1/findings` with no filters returns every finding."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["rows"], list)
    assert body["total"] == len(_FIXTURE_FINDINGS)
    ids = {row["id"] for row in body["rows"]}
    assert ids == {f["id"] for f in _FIXTURE_FINDINGS}


def test_findings_filter_by_category(tmp_path: Path) -> None:
    """`?category=clinical-actionable` returns only that subset.

    The two clinical-actionable findings (BRCA2 + CYP2D6) match; the
    lifestyle + non-actionable findings are excluded.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings", params={"category": "clinical-actionable"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    categories = {row["category"] for row in body["rows"]}
    assert categories == {"clinical-actionable"}


def test_findings_filter_by_genes_array(tmp_path: Path) -> None:
    """`?genes=BRCA2&genes=LCT` (repeated query keys) filters to matching rows.

    Mirrors spec Q4: typed array passed as repeated `genes=` query params.
    The host service's `genes: list[str] | None = Query(default=None)`
    pattern parses both.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings", params=[("genes", "BRCA2"), ("genes", "LCT")])

    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body["rows"]}
    assert ids == {"fnd-brca2-001", "fnd-lct-001"}


def test_findings_filter_by_drugs_array(tmp_path: Path) -> None:
    """`?drugs=codeine` matches the CYP2D6 finding (whose drugs include codeine)."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings", params=[("drugs", "codeine")])

    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body["rows"]}
    assert ids == {"fnd-cyp2d6-001"}


def test_findings_by_id_returns_single_finding(tmp_path: Path) -> None:
    """`GET /v1/findings/fnd-brca2-001` returns the full single-finding detail."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings/fnd-brca2-001")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == "fnd-brca2-001"
    assert body["category"] == "clinical-actionable"
    assert body["clinical_escalation"] == "confirm_with_provider"
    assert body["evidence_ref"] == "clinvar:RCV000031"
    assert body["gene_symbols"] == ["BRCA2"]


def test_findings_by_id_returns_404_for_unknown(tmp_path: Path) -> None:
    """Unknown id returns 404 with a typed error body."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings/fnd-does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "fnd-does-not-exist" in body["detail"]


def test_invP002_findings_response_excludes_provenance(tmp_path: Path) -> None:
    """``INV-P002``: findings response excludes the 7 provenance columns.

    Provenance lives at /v1/provenance/{run-id}; inlining it on every
    finding would inflate the response without adding interpretation.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_findings(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        list_response = client.get("/v1/findings")
        detail_response = client.get("/v1/findings/fnd-brca2-001")

    forbidden = {
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    }
    for row in list_response.json()["rows"]:
        leaked = forbidden & row.keys()
        assert not leaked, f"INV-P002 violation in list row: {leaked}"
    leaked = forbidden & detail_response.json().keys()
    assert not leaked, f"INV-P002 violation in detail body: {leaked}"


def test_findings_list_returns_503_when_no_active_run(tmp_path: Path) -> None:
    """The findings list inherits health's degraded-state semantics."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings")

    assert response.status_code == 503

"""`GET /v1/gene/{symbol}` surfaces `region_class` + `caveat` (Plan 5 Phase 3).

End-to-end test against the FastAPI service: seed a fixture DuckDB
with `coverage_qc` rows; spin up the host app via TestClient; assert
the JSON response includes the new fields.

Per coverage-panel-v2/phases/phase-3.md.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import (
    ProvenanceTag,
    create_store,
    write_coverage_qc,
)
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app

_RUN_ID = "2026-05-25T00-00-00Z-gene001"


def _stage_run(derived_root: Path) -> Path:
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": "cli-fixture"}
        )
    )
    create_store(run_dir / "variants.duckdb")
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def _tag():
    return ProvenanceTag(
        source_path="/dummy/sample.bam",
        source_sha256="a" * 64,
        tool="mosdepth",
        tool_version="0.3.10",
        params_json="{}",
        schema_version=SCHEMA_VERSION,
        created_at=datetime.now(UTC),
    )


def test_get_gene_endpoint_includes_region_class_and_caveat(tmp_path: Path) -> None:
    """`/v1/gene/PMS2` returns `region_class="difficult_pseudogene"` + a caveat."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    write_coverage_qc(
        run_dir / "variants.duckdb",
        [
            {
                "gene": "PMS2",
                "mean_depth": 30.0,
                "low_coverage_exons": ["PMS2_exon_11"],
                "region_class": "difficult_pseudogene",
            }
        ],
        tag=_tag(),
    )

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/PMS2")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gene"] == "PMS2"
    assert body["region_class"] == "difficult_pseudogene"
    assert body["caveat"] is not None
    # The caveat must explicitly name the class so the agent can quote it.
    assert "pseudogene" in body["caveat"].lower() or "difficult_pseudogene" in body["caveat"]


def test_get_gene_endpoint_no_caveat_for_standard_gene(tmp_path: Path) -> None:
    """`/v1/gene/BRCA1` (region_class=standard) → caveat is null."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    write_coverage_qc(
        run_dir / "variants.duckdb",
        [
            {
                "gene": "BRCA1",
                "mean_depth": 30.0,
                "low_coverage_exons": [],
                "region_class": "standard",
            }
        ],
        tag=_tag(),
    )

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/BRCA1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gene"] == "BRCA1"
    assert body["region_class"] == "standard"
    assert body["caveat"] is None


def test_get_gene_endpoint_no_caveat_for_legacy_null_region_class(tmp_path: Path) -> None:
    """Pre-v2 rows (NULL `region_class`) → response carries `region_class=None` + `caveat=None`."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    write_coverage_qc(
        run_dir / "variants.duckdb",
        [{"gene": "MYC", "mean_depth": 30.0, "low_coverage_exons": []}],
        tag=_tag(),
    )

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/MYC")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["region_class"] is None
    assert body["caveat"] is None

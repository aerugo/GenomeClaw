"""Phase 5 Slice C — `/v1/provenance/{run-id}` + `/v1/gene/{symbol}`.

Two endpoints sharing the same fixture pattern. The provenance route
returns the active run's full step trail (including the new
``vep_skipped_variants`` / ``vep_skipped_chroms`` fields shipped during
the 2026-05-15 Phase-4 close). The gene route aggregates the variants
table by ``gene_symbol`` + joins the coverage_qc row for ``mean_depth``
+ ``low_coverage_exons`` per spec AC8.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app

# Synthetic provenance trail mirroring the real shape Phase 4D produces,
# including the decoy-variant-provenance fields landed 2026-05-15.
_PROVENANCE_FIXTURE: dict[str, object] = {
    "run_id": "2026-05-15T00-00-00Z-prov01",
    "schema_version": SCHEMA_VERSION,
    "steps": [
        {
            "step": "ingest",
            "tool": "bcftools",
            "tool_version": "1.21",
            "started_at": "2026-05-15T00:00:00Z",
            "completed_at": "2026-05-15T00:01:42Z",
            "inputs": [
                {
                    "path": "/fixture/sample.vcf.gz",
                    "sha256": "0" * 64,
                }
            ],
            "outputs": [],
            "params": {},
        },
        {
            "step": "vep",
            "tool": "vep",
            "tool_version": "114.1",
            "started_at": "2026-05-15T00:30:00Z",
            "completed_at": "2026-05-15T04:30:00Z",
            "inputs": [
                {"path": "/fixture/vcfanno.vcf.gz", "sha256": "1" * 64},
                {"path": "/fixture/grch38.fa.gz", "sha256": "2" * 64},
            ],
            "outputs": [{"path": "vep.vcf.gz", "sha256": "3" * 64}],
            "params": {
                "cache_release": "114",
                "plugins": ["LoF,...", "AlphaMissense,..."],
                "flags": ["--mane_select", "--hgvs"],
                "fork": 4,
                "vep_skipped_variants": 1234,
                "vep_skipped_chroms": {
                    "chrUn_JTFH01001998v1_decoy": 6,
                    "chrUn_KI270742v1": 12,
                },
            },
        },
    ],
}


def _insert_gene_variants(store_path: Path) -> None:
    """Insert 4 variants spread across 2 genes + 1 with no gene assignment."""
    now = datetime.now(tz=UTC)
    fixture_sha = "a" * 64
    conn = duckdb.connect(str(store_path))
    try:
        rows = [
            ("chr17", 41197695, "rs1", "A", "T", "BRCA1", "missense_variant"),
            ("chr17", 41197800, "rs2", "G", "C", "BRCA1", "synonymous_variant"),
            ("chr17", 41197900, None, "T", "A", "BRCA1", "intron_variant"),
            ("chr13", 32890600, "rs3", "C", "G", "BRCA2", "stop_gained"),
            ("chrUn_xxx", 100, None, "A", "G", None, "intergenic_variant"),
        ]
        for chrom, pos, rsid, ref, alt, gene, csq in rows:
            conn.execute(
                """
                INSERT INTO variants (
                    chrom, pos, id, ref, alt, qual, filter, sample_id, genotype,
                    gene_symbol, consequence,
                    source_path, source_sha256, tool, tool_version, params_json,
                    schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, 'PASS', 'fixture-sample', '0/1',
                          ?, ?, 'fixture', ?, 'fixture', '0.0', '{}', ?, ?)
                """,
                [chrom, pos, rsid, ref, alt, gene, csq, fixture_sha, SCHEMA_VERSION, now],
            )

        conn.execute(
            """
            INSERT INTO coverage_qc (
                gene, mean_depth, low_coverage_exons,
                source_path, source_sha256, tool, tool_version, params_json,
                schema_version, created_at
            ) VALUES ('BRCA1', 32.4, ['exon-11', 'exon-13'],
                      'fixture', ?, 'mosdepth', '0.3.6', '{}', ?, ?)
            """,
            [fixture_sha, SCHEMA_VERSION, now],
        )
        conn.execute(
            """
            INSERT INTO coverage_qc (
                gene, mean_depth, low_coverage_exons,
                source_path, source_sha256, tool, tool_version, params_json,
                schema_version, created_at
            ) VALUES ('BRCA2', 28.1, [],
                      'fixture', ?, 'mosdepth', '0.3.6', '{}', ?, ?)
            """,
            [fixture_sha, SCHEMA_VERSION, now],
        )
        # GENE_NO_COV: variants exist for this gene but no coverage_qc row.
        # The /v1/gene endpoint must still answer something useful.
        conn.execute(
            """
            INSERT INTO variants (
                chrom, pos, id, ref, alt, qual, filter, sample_id, genotype,
                gene_symbol, consequence,
                source_path, source_sha256, tool, tool_version, params_json,
                schema_version, created_at
            ) VALUES ('chr1', 500, NULL, 'A', 'G', NULL, 'PASS', 'fixture-sample', '0/1',
                      'GENE_NO_COV', 'missense_variant', 'fixture', ?, 'fixture',
                      '0.0', '{}', ?, ?)
            """,
            [fixture_sha, SCHEMA_VERSION, now],
        )
    finally:
        conn.close()


def _stage_run(derived_root: Path) -> Path:
    """Stage a derived/<run-id>/ with manifest + provenance + populated variants.duckdb."""
    run_id = "2026-05-15T00-00-00Z-prov01"
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": run_id, "schema_version": SCHEMA_VERSION, "sample_id": "fixture-sample"}
        )
    )
    (run_dir / "provenance.json").write_text(json.dumps(_PROVENANCE_FIXTURE))

    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    _insert_gene_variants(store_path)

    update_current_symlink(derived_root, run_id)
    return run_dir


# ---------------------------------------------------------------------------
# /v1/provenance/{run-id}
# ---------------------------------------------------------------------------


def test_provenance_returns_full_step_trail_for_active_run(tmp_path: Path) -> None:
    """`GET /v1/provenance/{active-run-id}` returns the parsed provenance trail.

    Pins: response body has top-level `run_id` + `schema_version` + `steps`
    list; each step carries `step`, `tool`, `tool_version`, timestamps,
    `inputs`, `outputs`, `params`.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/provenance/2026-05-15T00-00-00Z-prov01")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == "2026-05-15T00-00-00Z-prov01"
    assert body["schema_version"] == SCHEMA_VERSION
    assert len(body["steps"]) == 2
    assert body["steps"][0]["step"] == "ingest"
    assert body["steps"][1]["step"] == "vep"


def test_provenance_surfaces_vep_skip_breakdown(tmp_path: Path) -> None:
    """The `vep` step's `params` carries `vep_skipped_variants` + `vep_skipped_chroms`.

    Confirms the Phase 4 close paperwork's decoy-variant-provenance work
    flows through the host service unchanged. The agent reading the
    provenance endpoint sees the exact per-chrom drop count that
    `normalize → materialize` row-count delta otherwise wouldn't explain.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/provenance/2026-05-15T00-00-00Z-prov01")

    body = response.json()
    vep_step = next(s for s in body["steps"] if s["step"] == "vep")
    params = vep_step["params"]
    assert params["vep_skipped_variants"] == 1234
    assert params["vep_skipped_chroms"] == {
        "chrUn_JTFH01001998v1_decoy": 6,
        "chrUn_KI270742v1": 12,
    }


def test_provenance_returns_404_for_wrong_run_id(tmp_path: Path) -> None:
    """A run-id that isn't the active run returns 404.

    Slice C ships single-run semantics: only the currently-active run's
    provenance is served. Historical runs require ``CURRENT`` to point at
    them or a later iteration that walks the full derived/ tree.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/provenance/2026-01-01T00-00-00Z-other1")

    assert response.status_code == 404
    body = response.json()
    assert "2026-01-01T00-00-00Z-other1" in body["detail"]


# ---------------------------------------------------------------------------
# /v1/gene/{symbol}
# ---------------------------------------------------------------------------


def test_gene_endpoint_returns_aggregated_summary_for_curated_gene(tmp_path: Path) -> None:
    """`GET /v1/gene/BRCA1` returns the gene's variant count + coverage_qc fields."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/BRCA1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gene"] == "BRCA1"
    assert body["n_variants_in_gene"] == 3  # 3 BRCA1 rows in the fixture
    assert body["mean_depth"] == pytest.approx(32.4)
    assert body["low_coverage_exons"] == ["exon-11", "exon-13"]
    assert body["schema_version"] == SCHEMA_VERSION


def test_gene_endpoint_returns_summary_without_coverage_for_uncovered_gene(
    tmp_path: Path,
) -> None:
    """Variants exist for the gene but no `coverage_qc` row — partial summary still returns.

    Per spec AC8: per-exon coverage is materialised only for the curated
    subset of clinically-relevant genes. For a gene with variants but no
    curated coverage row, the endpoint returns 200 + variant count, with
    `mean_depth=null` and `low_coverage_exons=[]`. The agent
    distinguishes "no data" (null mean_depth) from "well-covered" (a
    real number).
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/GENE_NO_COV")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gene"] == "GENE_NO_COV"
    assert body["n_variants_in_gene"] == 1
    assert body["mean_depth"] is None
    assert body["low_coverage_exons"] == []


def test_gene_endpoint_returns_404_for_unknown_symbol(tmp_path: Path) -> None:
    """A gene the active run has no row for returns 404."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/NONEXISTENT_GENE")

    assert response.status_code == 404
    body = response.json()
    assert "NONEXISTENT_GENE" in body["detail"]


def test_gene_endpoint_resolves_symbol_case_insensitively(tmp_path: Path) -> None:
    """`GET /v1/gene/brca1` (lowercase) resolves the same row as `BRCA1`.

    HGNC gene symbols are uppercase by convention but agents may pass
    them in arbitrary case. The endpoint case-folds for lookup, returning
    the canonical (DB-stored) `gene` field in the response.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/brca1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gene"] == "BRCA1"


def test_invP002_gene_response_excludes_raw_variant_rows(tmp_path: Path) -> None:
    """``INV-P002``: `/v1/gene/{symbol}` is a summary, not a variant dump.

    A regression that "helpfully" inlined the matching variant rows
    would inflate the response and conflict with the bulk-vs-summary
    distinction. The plugin's `genomeclaw_variant` browse flow is the
    documented path for per-row data; the gene endpoint surfaces
    aggregates only.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/gene/BRCA1")

    body = response.json()
    for forbidden in ("variants", "rows", "variant_list"):
        assert forbidden not in body, (
            f"INV-P002 violation: /v1/gene/{{symbol}} leaks bulk field {forbidden!r}"
        )

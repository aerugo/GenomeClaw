"""Phase 6 Slice B + Phase 1 of agent-research-and-synthesis — `/v1/evidence/{ref}` contract.

The host service evidence resolver supports **variant-keyed kinds only** as of
the v1.6 INVARIANTS revision (per [agent-research-and-synthesis spec](
../../../../docs/plans/active/agent-research-and-synthesis/spec.md) + the
retirement of `reference/curated_notes/` in INV-C001 v1.6):

| Kind          | id shape          | Resolved from                              |
|---------------|-------------------|--------------------------------------------|
| `clinvar`     | RCV / VCV id      | Variants table row joined on `clinvar_id`  |
| `pgs_catalog` | PGS Catalog id    | (Slice E) `pgs_scores` table               |
| `pharmgkb`    | PharmGKB pa-id    | (Slice D) PharmCAT outside-call output     |

The `gene_note:` and `topic:` kinds previously shipped under MVP spec Q9 are
**retired**. Phase 1 of the agent-research-and-synthesis plan removes their
resolver helpers + reduces `_SUPPORTED_EVIDENCE_KINDS` accordingly.

Lifestyle calibration moves to the agent's research-and-synthesis pattern
(`memory:` + `web:` citations on the sandbox side, not resolved by the host
service). See [INVARIANTS.md v1.8](../../../../docs/reference/INVARIANTS.md)
INV-C001 v1.6 + INV-A001 + INV-A002.
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
from genomeclaw_toolkit.service.store import _SUPPORTED_EVIDENCE_KINDS


def _insert_clinvar_variant(store_path: Path) -> None:
    """Insert one variants row with a populated clinvar_id."""
    now = datetime.now(tz=UTC)
    fixture_sha = "c" * 64
    conn = duckdb.connect(str(store_path))
    try:
        conn.execute(
            """
            INSERT INTO variants (
                chrom, pos, id, ref, alt, qual, filter, sample_id, genotype,
                clinvar_id, clinvar_classification, clinvar_review_status,
                gene_symbol, consequence,
                source_path, source_sha256, tool, tool_version, params_json,
                schema_version, created_at
            ) VALUES ('chr13', 32890600, 'rs80359550', 'C', 'G', NULL, 'PASS',
                      'fixture-sample', '0/1',
                      'RCV000031', 'Pathogenic', 'reviewed by expert panel',
                      'BRCA2', 'stop_gained',
                      'fixture', ?, 'fixture', '0.0', '{}', ?, ?)
            """,
            [fixture_sha, SCHEMA_VERSION, now],
        )
    finally:
        conn.close()


def _stage(tmp_path: Path) -> Path:
    """Stage a derived store with one ClinVar-annotated variant.

    Returns the `derived_root` Path. No `reference_dir` parameter: the
    host service no longer resolves curated-notes references, so its
    Phase-1 build_app() takes only `derived_root`.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()

    run_id = "2026-05-15T00-00-00Z-evi001"
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": run_id, "schema_version": SCHEMA_VERSION, "sample_id": "fixture-sample"}
        )
    )
    create_store(run_dir / "variants.duckdb")
    _insert_clinvar_variant(run_dir / "variants.duckdb")
    update_current_symlink(derived_root, run_id)

    return derived_root


# ---------------------------------------------------------------------------
# Variant-keyed kinds — the supported v1.6 surface
# ---------------------------------------------------------------------------


def test_evidence_resolves_clinvar_from_variants_table(tmp_path: Path) -> None:
    """`clinvar:RCV000031` looks up the variants row with `clinvar_id = 'RCV000031'`."""
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/clinvar:RCV000031")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "clinvar"
    assert body["id"] == "RCV000031"
    # The body summarises the classification; doesn't dump the full variant row.
    assert "Pathogenic" in body["body"]
    assert "BRCA2" in body["body"]
    assert body["source"].startswith("variants.duckdb")


def test_evidence_returns_404_for_unknown_clinvar_id(tmp_path: Path) -> None:
    """`clinvar:RCV999999` (no variants row with that id) returns 404."""
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/clinvar:RCV999999")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Retired curated-notes kinds — now 400 ("unknown kind")
# ---------------------------------------------------------------------------


def test_evidence_returns_400_for_retired_gene_note_kind(tmp_path: Path) -> None:
    """``gene_note:`` is retired in v1.6 — returns 400 (kind not supported).

    Lifestyle calibration moved to the agent's research-and-synthesis pattern
    (`memory:` / `web:` citations on the sandbox side). A request that still
    uses the retired kind should fail with a clear error pointing at the new
    pattern, not silently return 404.
    """
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/gene_note:CYP1A2")

    assert response.status_code == 400, response.text
    body = response.json()
    assert "gene_note" in body["detail"]


def test_evidence_returns_400_for_retired_topic_kind(tmp_path: Path) -> None:
    """``topic:`` is retired in v1.6 — returns 400 (kind not supported)."""
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/topic:hard-genes")

    assert response.status_code == 400, response.text
    body = response.json()
    assert "topic" in body["detail"]


def test_supported_evidence_kinds_pinned(tmp_path: Path) -> None:
    """``_SUPPORTED_EVIDENCE_KINDS`` is pinned to the documented kind set.

    Pins the contract so a future regression that re-adds retired kinds
    (`gene_note:` / `topic:`) surfaces here. Adding a new kind extends this
    set explicitly.

    Kinds:
    - Variant-keyed via DB lookup: `clinvar`, `pgs_catalog`, `pharmgkb`.
    - Local-artefact-keyed via file read: `cyrius_no_call` (the indeterminate
      CYP2D6 sentinel — added by cyp2d6-no-call-finding Phase 2).
    """
    assert _SUPPORTED_EVIDENCE_KINDS == frozenset(
        {"clinvar", "pgs_catalog", "pharmgkb", "cyrius_no_call"}
    )


# ---------------------------------------------------------------------------
# Other errors
# ---------------------------------------------------------------------------


def test_evidence_returns_400_for_malformed_ref(tmp_path: Path) -> None:
    """A ref without a `<kind>:<id>` shape returns 400."""
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/not-a-real-ref")

    assert response.status_code == 400
    assert "kind:id" in response.json()["detail"]


def test_evidence_returns_400_for_unknown_kind(tmp_path: Path) -> None:
    """A ref with an unknown `<kind>:` prefix returns 400 (not 404)."""
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/unknown_kind:abc")

    assert response.status_code == 400
    assert "unknown_kind" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Privacy floor
# ---------------------------------------------------------------------------


def test_invP002_evidence_response_excludes_raw_variant_dump(tmp_path: Path) -> None:
    """``INV-P002``: clinvar evidence doesn't leak the full variant row.

    The clinvar resolver returns a SUMMARY of the variant's clinical
    interpretation (classification + review status + gene symbol +
    canonical identifier), not the full row (no qual, no filter, no
    9-pop AFs, no genotype, no per-row provenance columns).
    """
    derived_root = _stage(tmp_path)
    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/evidence/clinvar:RCV000031")

    body = response.json()
    forbidden = {
        "genotype",
        "qual",
        "filter",
        "gnomad_af_afr",
        "gnomad_af_amr",
        "gnomad_af_nfe",
        "source_path",
        "source_sha256",
        "tool",
        "params_json",
        "created_at",
    }
    leaked = forbidden & body.keys()
    assert not leaked, f"INV-P002 violation: /v1/evidence leaks bulk fields: {leaked}"

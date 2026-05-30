"""Phase 5 Slice B — `/v1/variants` (list) + `/v1/variants/{key}` (single).

Covers the variant-query surface against the active run's
``variants.duckdb``. Two endpoints land here:

- ``GET /v1/variants?limit=N&offset=M`` — paginated row list with a
  bounded ``limit`` (default 25, max 100). Response carries a
  ``next_offset`` cursor when more rows exist.
- ``GET /v1/variants/{key}`` — single-variant lookup, where ``key`` is
  ``{chrom}-{pos}-{ref}-{alt}`` (e.g. ``chr1-12345-A-T``). 404 when the
  key isn't found.

`INV-P002`: response shapes are pinned. The list view drops the bulk
per-population gnomAD AFs (popmax + popmax_pop summarise them); the
single-variant detail view keeps gene-context fields but still excludes
provenance trails (those live at ``/v1/provenance/{run-id}``).
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

_SAMPLE_VARIANTS: tuple[dict[str, object], ...] = (
    {
        "chrom": "chr1",
        "pos": 100,
        "id": "rs100",
        "ref": "A",
        "alt": "T",
        "gene_symbol": "GENE1",
        "consequence": "missense_variant",
        "clinvar_classification": "Pathogenic",
        "gnomad_af_popmax": 0.001,
        "gnomad_af_popmax_pop": "nfe",
        "alphamissense_score": 0.92,
        # Plan `vep-mane-api-exposure`: the "rare-but-real" shape — Plan 4's
        # dual-row extraction emitted both a MANE Select and a MANE Plus
        # Clinical row for this position. The detail view must surface both.
        "mane_plus_clinical_transcript": "NM_001128425.2",
        "transcript_discordant": True,
    },
    {
        "chrom": "chr1",
        "pos": 200,
        "id": "rs200",
        "ref": "G",
        "alt": "C",
        "gene_symbol": "GENE1",
        "consequence": "synonymous_variant",
        "clinvar_classification": "Benign",
        "gnomad_af_popmax": 0.4,
        "gnomad_af_popmax_pop": "afr",
        "alphamissense_score": None,
        # The canonical pre-`vep-mane-plus-clinical` shape: no MANE Plus
        # Clinical transcript on file; Select and Plus-Clinical didn't
        # disagree (the typical case for ~99.99% of real variants).
        "mane_plus_clinical_transcript": None,
        "transcript_discordant": False,
    },
    {
        "chrom": "chr2",
        "pos": 300,
        "id": None,
        "ref": "C",
        "alt": "G",
        "gene_symbol": None,
        "consequence": "intergenic_variant",
        "clinvar_classification": None,
        "gnomad_af_popmax": None,
        "gnomad_af_popmax_pop": None,
        "alphamissense_score": None,
        "mane_plus_clinical_transcript": None,
        "transcript_discordant": False,
    },
    # Dual-row pair at chr3:400 A>T (canonical + discordant siblings) —
    # mirrors the real-data shape Plan 4's dual-row materialize emits.
    # First entry is the canonical row (MANE Select winner, not discordant);
    # second is the discordant sibling (MANE Plus Clinical winner). The
    # lookup endpoint MUST prefer the discordant row so the agent can see
    # the IMPACT-tier disagreement flag.
    {
        "chrom": "chr3",
        "pos": 400,
        "id": "rs400",
        "ref": "A",
        "alt": "T",
        "gene_symbol": "GENE3_CANONICAL",
        "consequence": "synonymous_variant",
        "clinvar_classification": None,
        "gnomad_af_popmax": None,
        "gnomad_af_popmax_pop": None,
        "alphamissense_score": None,
        "mane_plus_clinical_transcript": None,
        "transcript_discordant": False,
    },
    {
        "chrom": "chr3",
        "pos": 400,
        "id": "rs400",
        "ref": "A",
        "alt": "T",
        "gene_symbol": "GENE3_DISCORDANT",
        "consequence": "missense_variant",
        "clinvar_classification": "Likely_pathogenic",
        "gnomad_af_popmax": 0.0001,
        "gnomad_af_popmax_pop": "nfe",
        "alphamissense_score": 0.78,
        "mane_plus_clinical_transcript": "NM_999999.1",
        "transcript_discordant": True,
    },
)


def _insert_sample_rows(store_path: Path) -> None:
    """Insert ``_SAMPLE_VARIANTS`` into a freshly-created variants store.

    Direct SQL rather than going through ``write_variants`` — the latter
    expects a streaming CSV staging pipeline that's overkill for fixture
    setup, and ``write_variants``' batched path is already covered by
    its own tests.
    """
    now = datetime.now(tz=UTC)
    conn = duckdb.connect(str(store_path))
    try:
        for v in _SAMPLE_VARIANTS:
            conn.execute(
                """
                INSERT INTO variants (
                    chrom, pos, id, ref, alt, qual, filter,
                    sample_id, genotype,
                    clinvar_classification,
                    gnomad_af_popmax, gnomad_af_popmax_pop,
                    gene_symbol, consequence, alphamissense_score,
                    mane_plus_clinical_transcript, transcript_discordant,
                    source_path, source_sha256, tool, tool_version,
                    params_json, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, 'PASS',
                          'fixture-sample', '0/1',
                          ?, ?, ?, ?, ?, ?,
                          ?, ?,
                          'fixture',
                          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                          'fixture', '0.0',
                          '{}', ?, ?)
                """,
                [
                    v["chrom"],
                    v["pos"],
                    v["id"],
                    v["ref"],
                    v["alt"],
                    v["clinvar_classification"],
                    v["gnomad_af_popmax"],
                    v["gnomad_af_popmax_pop"],
                    v["gene_symbol"],
                    v["consequence"],
                    v["alphamissense_score"],
                    v["mane_plus_clinical_transcript"],
                    v["transcript_discordant"],
                    SCHEMA_VERSION,
                    now,
                ],
            )
    finally:
        conn.close()


def _stage_run_with_variants(derived_root: Path) -> Path:
    """Stage a derived/<run-id>/ with manifest.json + variants.duckdb populated."""
    run_id = "2026-05-15T00-00-00Z-var001"
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": run_id, "schema_version": SCHEMA_VERSION, "sample_id": "fixture-sample"}
        )
    )

    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    _insert_sample_rows(store_path)

    update_current_symlink(derived_root, run_id)
    return run_dir


def test_variants_list_returns_paginated_rows(tmp_path: Path) -> None:
    """`GET /v1/variants?limit=2` returns 2 rows + a ``next_offset`` cursor.

    Pins the pagination contract: response always carries a typed list
    of rows + a ``next_offset`` field (null when at end of stream). The
    plugin's ``genomeclaw_variant`` browse path uses this to step
    through a filtered query without bulk-shipping the full table.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants", params={"limit": 2})

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["rows"], list)
    assert len(body["rows"]) == 2
    # Five rows total (3 unique keys + 1 dual-row pair for the prefer-discordant
    # test); after page-1 of 2 there are still 3 rows → cursor is set.
    assert body["next_offset"] == 2
    assert body["limit"] == 2
    assert body["total"] == 5


def test_variants_list_pagination_terminates_with_null_cursor(tmp_path: Path) -> None:
    """At end of stream, ``next_offset`` is null and ``rows`` is empty/partial."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants", params={"limit": 2, "offset": 4})

    assert response.status_code == 200, response.text
    body = response.json()
    # Five rows total; offset=4 returns the 5th (last) row.
    assert len(body["rows"]) == 1
    assert body["next_offset"] is None


def test_variant_by_key_returns_single_row(tmp_path: Path) -> None:
    """`GET /v1/variants/chr1-100-A-T` returns the full single-variant detail body."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/chr1-100-A-T")

    assert response.status_code == 200, response.text
    body = response.json()
    # Identity fields parsed back out of the key + DB.
    assert body["chrom"] == "chr1"
    assert body["pos"] == 100
    assert body["ref"] == "A"
    assert body["alt"] == "T"
    assert body["rsid"] == "rs100"
    # Annotation fields surfaced.
    assert body["clinvar_classification"] == "Pathogenic"
    assert body["gene_symbol"] == "GENE1"
    assert body["consequence"] == "missense_variant"
    # DuckDB REAL column → single-precision float; use approx for round-trip.
    assert body["gnomad_af_popmax"] == pytest.approx(0.001)
    assert body["gnomad_af_popmax_pop"] == "nfe"
    assert body["alphamissense_score"] == pytest.approx(0.92)


def test_variant_by_key_projects_mane_plus_clinical_and_discordance(tmp_path: Path) -> None:
    """`GET /v1/variants/{key}` must project the two `vep-mane-plus-clinical` columns.

    Follow-up to the completed `vep-mane-plus-clinical` plan: the schema layer
    populated ``mane_plus_clinical_transcript`` + ``transcript_discordant`` on
    ``variants.duckdb``, the materialize-time extraction wrote them (verified at
    390 / 24 rows respectively on the real-data MPNRGLQ2K run), and the agent
    system prompt §6 asks the agent to consult MANE Plus Clinical guidance when
    relevant. But the HTTP boundary (FastAPI ``response_model=VariantDetail``)
    strips them, so the agent can't actually read what the prompt asks for.

    This is the regression test that closes that gap. ``chr1-100-A-T`` from the
    sample fixture carries ``mane_plus_clinical_transcript="NM_001128425.2"``
    and ``transcript_discordant=true``.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/chr1-100-A-T")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "mane_plus_clinical_transcript" in body, (
        "VariantDetail must project mane_plus_clinical_transcript so the agent "
        "can act on the MANE Plus Clinical guidance in system prompt §6."
    )
    assert body["mane_plus_clinical_transcript"] == "NM_001128425.2"
    assert "transcript_discordant" in body, (
        "VariantDetail must project transcript_discordant so the agent can "
        "flag IMPACT-tier disagreement between MANE Select and MANE Plus Clinical."
    )
    assert body["transcript_discordant"] is True


def test_variant_by_key_returns_null_when_no_mane_plus_clinical(tmp_path: Path) -> None:
    """When a variant has no MANE Plus Clinical transcript, the field is null (not omitted).

    The fixture's ``chr1-200-G-C`` row leaves ``mane_plus_clinical_transcript``
    as NULL in DuckDB and ``transcript_discordant`` as ``false`` (the canonical
    pre-`vep-mane-plus-clinical` shape for ~99.99% of real variants). The HTTP
    layer must still include both keys with explicit null / false values rather
    than dropping them — agents that rely on key-presence to detect missing
    annotations need a stable shape.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/chr1-200-G-C")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "mane_plus_clinical_transcript" in body
    assert body["mane_plus_clinical_transcript"] is None
    assert "transcript_discordant" in body
    assert body["transcript_discordant"] is False


def test_variant_by_key_prefers_discordant_sibling_on_dual_row(tmp_path: Path) -> None:
    """When two rows share a (chrom, pos, ref, alt), prefer the discordant view.

    Plan 4's dual-row materialize emits two rows for variants where MANE Select
    and MANE Plus Clinical disagree on IMPACT tier. ``query_variant_by_key``
    must return the discordant view (the rarer + more clinically interesting
    one) so the agent can act on the system-prompt's MANE Plus Clinical
    guidance.

    Without the ORDER BY, the LIMIT 1 returned whichever DuckDB scanned first
    (empirically the canonical row), silently hiding ``transcript_discordant``
    from the agent on real-data discordant variants.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/chr3-400-A-T")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gene_symbol"] == "GENE3_DISCORDANT", (
        "Lookup must prefer the discordant sibling so the agent can see the "
        "MANE Select / MANE Plus Clinical IMPACT-tier disagreement flag."
    )
    assert body["mane_plus_clinical_transcript"] == "NM_999999.1"
    assert body["transcript_discordant"] is True


def test_variant_by_key_returns_404_for_unknown(tmp_path: Path) -> None:
    """`GET /v1/variants/chr99-1-A-T` returns 404 with an actionable error body."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/chr99-1-A-T")

    assert response.status_code == 404
    body = response.json()
    assert "chr99-1-A-T" in body["detail"]


def test_variant_by_key_returns_400_for_malformed_key(tmp_path: Path) -> None:
    """A key that doesn't parse as ``chr-pos-ref-alt`` returns 400, not 500.

    The route validates the key shape before hitting the DB so a
    malformed user-supplied key surfaces as a usage error rather than a
    "no match" 404 (which would falsely suggest "the variant simply
    isn't in your data").
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/not-a-real-key")

    assert response.status_code == 400
    body = response.json()
    assert "key" in body["detail"].lower()


def test_invP002_variants_list_excludes_bulk_population_afs(tmp_path: Path) -> None:
    """``INV-P002``: the list response excludes the 9 individual population AFs.

    Per-population AFs are bulk-class fields — they're meaningful in
    detail-of-one-variant contexts but at list-of-many granularity they
    inflate the payload without adding interpretive value. The list
    summary surfaces ``gnomad_af_popmax`` + ``gnomad_af_popmax_pop`` so
    the agent gets the high-water-mark without the 9-way breakdown.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants", params={"limit": 10})

    body = response.json()
    forbidden_in_list = {
        "gnomad_af_afr",
        "gnomad_af_amr",
        "gnomad_af_asj",
        "gnomad_af_eas",
        "gnomad_af_fin",
        "gnomad_af_mid",
        "gnomad_af_nfe",
        "gnomad_af_remaining",
        "gnomad_af_sas",
    }
    for row in body["rows"]:
        leaked = forbidden_in_list & row.keys()
        assert not leaked, (
            f"INV-P002 violation: /v1/variants list row leaks per-population AFs: {leaked}"
        )


def test_invP002_variant_detail_excludes_provenance_columns(tmp_path: Path) -> None:
    """``INV-P002``: the single-variant detail excludes the 7 provenance columns.

    Provenance is its own surface (``/v1/provenance/{run-id}``); inlining
    it on every variant detail response would bloat every plugin call
    and duplicate state already addressable via the dedicated endpoint.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run_with_variants(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants/chr1-100-A-T")

    body = response.json()
    forbidden = {
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    }
    leaked = forbidden & body.keys()
    assert not leaked, (
        f"INV-P002 violation: /v1/variants/{{key}} leaks provenance columns: {leaked}"
    )


def test_variants_list_returns_503_when_no_active_run(tmp_path: Path) -> None:
    """The variants list inherits health's degraded-state semantics."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    # No CURRENT staged.

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/variants")

    assert response.status_code == 503

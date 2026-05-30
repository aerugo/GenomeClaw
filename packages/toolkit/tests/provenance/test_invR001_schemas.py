"""Phase 2 — schema definitions for manifest / provenance / coverage_qc.

Sub-phase 2A scope: the **shape** of the schemas (Pydantic models +
canonical column-name constants). The **populated** assertions (case 4
provenance columns, case 5 manifest tool versions, case 6 provenance.json
step trail, case 7 schema-version recorded) live in dedicated test files
once the ingest pipeline lands in sub-phase 2C.

These tests anchor INV-R001 structurally: every derived row has a fixed
shape known to the toolkit; nothing leaks through ad-hoc dict
construction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Canonical constants
# ---------------------------------------------------------------------------


def test_schema_version_constant_is_v0_4() -> None:
    """`prs-calibration-phase3b` Phase 2 bumps schema to v0.4.

    Adds `effect_weight_match_rate` + `fraposa_min_mahalanobis_distance`
    + `fraposa_nearest_superpop` to `pgs_scores`. All nullable; pre-v0.4
    rows carry NULLs. The three columns mirror the three classifier
    axes the Phase 3b extensions consult.
    """
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    assert SCHEMA_VERSION == "v0.4"


def test_provenance_columns_are_the_canonical_seven() -> None:
    """INV-R001: the seven canonical provenance column names land in one place.

    Wrappers and DuckDB writers reach for this constant tuple instead of
    re-listing the names; a typo in any one place becomes a single-source
    edit.
    """
    from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS

    assert PROVENANCE_COLUMNS == (
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    )


# ---------------------------------------------------------------------------
# Manifest model
# ---------------------------------------------------------------------------


def test_manifest_model_round_trips_a_minimal_run() -> None:
    """Pydantic Manifest accepts a minimal v0.1 run and serialises stably."""
    from genomeclaw_toolkit.schemas.manifest import Manifest

    payload = {
        "run_id": "2026-05-06T08-12-34Z-abc123",
        "schema_version": "v0.1",
        "sample_id": "test-sample-001",
        "input": {
            "vcf_path": "/mnt/genomeclaw/raw/test/sample.vcf.gz",
            "vcf_sha256": "a" * 64,
            "tbi_path": "/mnt/genomeclaw/raw/test/sample.vcf.gz.tbi",
            "tbi_sha256": "b" * 64,
            "reference_path": "/mnt/genomeclaw/reference/grch38/",
            "reference_build_inferred": "grch38",
        },
        "tools": {
            "bcftools": "1.21",
            "mosdepth": "0.3.10",
            "python": "3.11.10",
            "duckdb": "1.0.0",
            "genomeclaw-toolkit": "0.0.1",
        },
        "params": {},
        "outputs": {
            "derived_dir": "/mnt/genomeclaw/derived/2026-05-06T08-12-34Z-abc123/",
            "variants_table": "variants.duckdb",
        },
        "created_at": "2026-05-06T08:12:34Z",
    }
    m = Manifest.model_validate(payload)
    assert m.run_id == "2026-05-06T08-12-34Z-abc123"
    assert m.schema_version == "v0.1"
    assert m.tools["bcftools"] == "1.21"
    # Round-trip JSON is stable.
    again = Manifest.model_validate_json(m.model_dump_json())
    assert again == m


def test_manifest_rejects_unknown_top_level_field() -> None:
    """Strictness: unknown fields are a typo; the model refuses them."""
    from genomeclaw_toolkit.schemas.manifest import Manifest

    bad = {
        "run_id": "2026-05-06T08-12-34Z-abc123",
        "schema_version": "v0.1",
        "sample_id": "x",
        "input": {
            "vcf_path": "/p.vcf.gz",
            "vcf_sha256": "a" * 64,
            "reference_path": "/ref/",
            "reference_build_inferred": "grch38",
        },
        "tools": {"bcftools": "1.21"},
        "params": {},
        "outputs": {"derived_dir": "/d/", "variants_table": "variants.duckdb"},
        "created_at": "2026-05-06T08:12:34Z",
        "totally_unexpected": "yes",
    }
    with pytest.raises(ValueError):  # Pydantic raises ValidationError, a ValueError subclass
        Manifest.model_validate(bad)


def test_manifest_qc_bcftools_stats_optional_now_required_after_phase_2() -> None:
    """Per Phase 2 deliverable 5: ``manifest.qc.bcftools_stats`` is required when present.

    The model's ``qc`` field is ``Optional`` at the schema level (so the
    seed manifest written by the run-id step is valid before
    ``bcftools stats`` runs), but the populated v0.1 manifest written at
    end-of-ingest must include the block. Sub-phase 2C populates it; this
    test only checks the *shape* — that the field exists and has the
    expected sub-keys when supplied.
    """
    from genomeclaw_toolkit.schemas.manifest import Manifest

    payload = {
        "run_id": "2026-05-06T08-12-34Z-abc123",
        "schema_version": "v0.1",
        "sample_id": "x",
        "input": {
            "vcf_path": "/p.vcf.gz",
            "vcf_sha256": "a" * 64,
            "reference_path": "/ref/",
            "reference_build_inferred": "grch38",
        },
        "tools": {"bcftools": "1.21"},
        "params": {},
        "outputs": {"derived_dir": "/d/", "variants_table": "variants.duckdb"},
        "created_at": "2026-05-06T08:12:34Z",
        "qc": {
            "bcftools_stats": {
                "ts_tv_ratio": 2.05,
                "n_snps": 4_500_000,
                "n_indels": 800_000,
            }
        },
    }
    m = Manifest.model_validate(payload)
    assert m.qc is not None
    assert m.qc.bcftools_stats.ts_tv_ratio == pytest.approx(2.05)
    assert m.qc.bcftools_stats.n_snps == 4_500_000
    assert m.qc.bcftools_stats.n_indels == 800_000


# ---------------------------------------------------------------------------
# Provenance model
# ---------------------------------------------------------------------------


def test_provenance_model_round_trips_an_ingest_step() -> None:
    from genomeclaw_toolkit.schemas.provenance import Provenance

    payload = {
        "run_id": "2026-05-06T08-12-34Z-abc123",
        "schema_version": "v0.1",
        "steps": [
            {
                "step": "ingest",
                "tool": "genomeclaw-prep",
                "tool_version": "0.0.1",
                "started_at": "2026-05-06T08:12:34Z",
                "completed_at": "2026-05-06T08:13:02Z",
                "inputs": [
                    {
                        "path": "/mnt/genomeclaw/raw/x/sample.vcf.gz",
                        "sha256": "a" * 64,
                    }
                ],
                "outputs": [{"path": "variants.duckdb", "sha256": "b" * 64}],
                "params": {"sample_id": "x"},
            }
        ],
    }
    p = Provenance.model_validate(payload)
    assert len(p.steps) == 1
    assert p.steps[0].step == "ingest"
    assert p.steps[0].tool == "genomeclaw-prep"


def test_provenance_step_requires_at_least_one_input() -> None:
    """An ``ingest`` step with empty ``inputs`` is meaningless — refuse it."""
    from genomeclaw_toolkit.schemas.provenance import Provenance

    payload = {
        "run_id": "r",
        "schema_version": "v0.1",
        "steps": [
            {
                "step": "ingest",
                "tool": "genomeclaw-prep",
                "tool_version": "0.0.1",
                "started_at": "2026-05-06T08:12:34Z",
                "completed_at": "2026-05-06T08:13:02Z",
                "inputs": [],
                "outputs": [{"path": "x", "sha256": "a" * 64}],
                "params": {},
            }
        ],
    }
    with pytest.raises(ValueError):
        Provenance.model_validate(payload)


def test_provenance_step_inputs_require_sha256() -> None:
    from genomeclaw_toolkit.schemas.provenance import Provenance

    bad_input = {
        "run_id": "r",
        "schema_version": "v0.1",
        "steps": [
            {
                "step": "ingest",
                "tool": "genomeclaw-prep",
                "tool_version": "0.0.1",
                "started_at": "2026-05-06T08:12:34Z",
                "completed_at": "2026-05-06T08:13:02Z",
                "inputs": [{"path": "/p.vcf.gz"}],  # missing sha256
                "outputs": [{"path": "x", "sha256": "a" * 64}],
                "params": {},
            }
        ],
    }
    with pytest.raises(ValueError):
        Provenance.model_validate(bad_input)


# ---------------------------------------------------------------------------
# Coverage QC model
# ---------------------------------------------------------------------------


def test_coverage_qc_row_carries_seven_provenance_columns() -> None:
    """INV-R001 v1.5: every coverage_qc row inherits the canonical provenance columns."""
    from genomeclaw_toolkit.schemas.coverage_qc import CoverageQCRow

    row = CoverageQCRow.model_validate(
        {
            "gene": "BRCA1",
            "mean_depth": 28.4,
            "low_coverage_exons": ["NM_007294.4:exon-11"],
            "source_path": "/mnt/genomeclaw/raw/x/sample.bam",
            "source_sha256": "a" * 64,
            "tool": "mosdepth",
            "tool_version": "0.3.10",
            "params_json": "{}",
            "schema_version": "v0.1",
            "created_at": datetime(2026, 5, 6, 8, 13, 2, tzinfo=UTC),
        }
    )
    assert row.gene == "BRCA1"
    assert row.mean_depth == pytest.approx(28.4)
    # All seven canonical columns are present.
    serialised = row.model_dump()
    for col in (
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    ):
        assert col in serialised, col
        assert serialised[col] is not None, col


def test_coverage_qc_rejects_negative_mean_depth() -> None:
    """mosdepth never emits negative depth; refuse it as a sanity check."""
    from genomeclaw_toolkit.schemas.coverage_qc import CoverageQCRow

    payload = {
        "gene": "BRCA1",
        "mean_depth": -1.0,
        "low_coverage_exons": [],
        "source_path": "/p",
        "source_sha256": "a" * 64,
        "tool": "mosdepth",
        "tool_version": "0.3.10",
        "params_json": "{}",
        "schema_version": "v0.1",
        "created_at": datetime(2026, 5, 6, 8, 13, 2, tzinfo=UTC),
    }
    with pytest.raises(ValueError):
        CoverageQCRow.model_validate(payload)


def test_coverage_qc_table_ddl_lists_all_columns() -> None:
    """The DuckDB ``CREATE TABLE coverage_qc`` DDL is sourced from the same model.

    A future divergence between the Pydantic model and the DDL would
    surface as a row-validation error at write time. We anchor the
    column list once.
    """
    from genomeclaw_toolkit.schemas.coverage_qc import (
        COVERAGE_QC_COLUMNS,
        CoverageQCRow,
    )

    model_fields = set(CoverageQCRow.model_fields.keys())
    ddl_columns = {col for col, _type in COVERAGE_QC_COLUMNS}
    assert model_fields == ddl_columns

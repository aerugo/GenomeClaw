"""Stage a synthetic `derived/<run-id>/` for live-smoke tests.

The `genomeclaw` plugin tools the agent calls (`genomeclaw_findings`,
`genomeclaw_gene`, etc.) read through the host service's
`/v1/findings*` + `/v1/gene/*` endpoints, which in turn read
`derived/<run-id>/variants.duckdb`. Phase 2's smoke staged only a
manifest, so every findings/gene query came back HTTP 500. This module
materialises a real (synthetic) store so the agent's tools succeed
end-to-end.

The fixture findings are intentionally story-specific — each
`live_llm` test passes its own `findings` tuple in. There is no
"default" finding set; the test names what scenario it is exercising.

Mirrors the pattern from
[tests/integration/test_service_findings.py](
../integration/test_service_findings.py) but parameterised so multiple
live-smoke tests can stage their own scenarios without duplicating the
duckdb-create + insert dance.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

# Story 9 — CYP1A2 caffeine slow-metabolizer fixture.
#
# The rs762551 A/A genotype (CYP1A2*1F homozygous) maps to slow caffeine
# metabolism; effect-size literature is heterogeneous + body of evidence
# points at "noon caffeine cutoff" as a falsifiable lifestyle experiment
# for affected individuals. The agent should recognise the gene + variant,
# pull current literature via native `web_search`, and produce calibrated
# guidance per `INV-C001` v1.6.
#
# The evidence_ref points at a memory anchor the agent will populate; the
# host service surfaces the finding as-is, and the agent's research +
# memory-write step build the actual evidence trail. Memory-only refs
# in findings are fine at the host-service layer (Finding.evidence_ref
# is just a non-empty string per the model); the validator's
# primary-source-required rule binds at the *memory note* layer, not at
# the findings-table layer.
STORY9_CYP1A2_FINDINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "fnd-cyp1a2-001",
        "category": "lifestyle",
        "title": "CYP1A2 *1F/*1F — slow caffeine metabolizer",
        "summary": (
            "rs762551 A/A genotype (CYP1A2*1F homozygous) consistent with slower "
            "caffeine clearance. Reported associations with chronic-late-caffeine "
            "effects on sleep onset latency are heterogeneous; the canonical "
            "falsifiable experiment is two weeks of strict noon caffeine cutoff "
            "with sleep-onset-latency as the outcome."
        ),
        "evidence_ref": "memory:cyp1a2-caffeine-synthesis",
        "evidence_quality": "moderate",
        "gene_symbols": ["CYP1A2"],
        "clinical_escalation": None,
        "drugs": None,
    },
)

# Story 4 — CYP2C19 *1/*2 intermediate metabolizer for clopidogrel.
#
# Per [docs/reference/user-stories.md Story 4](
# ../../../../docs/reference/user-stories.md): the canonical PGx exchange.
# CPIC's clopidogrel + CYP2C19 IM guideline points at considering an
# alternative antiplatelet (prasugrel or ticagrelor) for ACS / PCI
# indications; that reasoning is current literature the agent should
# pull via web_search rather than a pre-baked memory note. Carries a
# `clinical_escalation: confirm_with_provider` marker per `INV-C001`
# v1.5 (the model-layer rule that clinical-actionable findings must
# declare their escalation).
STORY4_CYP2C19_FINDINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "fnd-cyp2c19-001",
        "category": "clinical-actionable",
        "title": "CYP2C19 *1/*2 — intermediate metabolizer",
        "summary": (
            "CYP2C19 haplotype *1/*2 (intermediate metabolizer phenotype). "
            "Pharmacogenomic relevance for clopidogrel (and several other drugs "
            "metabolised by CYP2C19) per CPIC. Genotyping is research-grade WGS, "
            "not a clinical PGx panel; clinical confirmation appropriate before "
            "any prescribing change."
        ),
        "evidence_ref": "pharmgkb:PA166104948",
        "evidence_quality": "high",
        "gene_symbols": ["CYP2C19"],
        "clinical_escalation": "confirm_with_provider",
        "drugs": ["clopidogrel"],
    },
)

# Story 10 — Coronary artery disease polygenic risk score.
#
# Per [docs/reference/user-stories.md Story 10](
# ../../../../docs/reference/user-stories.md): a population-percentile
# CAD PRS, not a pathogenic variant call. Carries no clinical-escalation
# marker by design (per `INV-C001` v1.6 the lifestyle-vs-clinical-actionable
# split keeps PRS out of the clinical-actionable category — it is
# `clinical-non-actionable` and the agent's framing must not over-elevate
# it). The agent should pull current PRS literature (calibration warnings,
# 2-3× lifetime risk for the top decile, modifiable-risk overlap) via
# web_search.
STORY10_CAD_PRS_FINDINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "fnd-cad-prs-001",
        "category": "clinical-non-actionable",
        "title": "CAD polygenic risk score — 87th percentile (ancestry-matched)",
        "summary": (
            "Coronary artery disease PRS at the 87th percentile in your "
            "ancestry-matched reference population (raw score 0.42; PGS Catalog "
            "PGS000018, European-ancestry training set: UK Biobank + "
            "CARDIoGRAMplusC4D meta-analysis; no calibration warning surfaced). "
            "Population-level estimate, not a clinical risk call."
        ),
        "evidence_ref": "pgs_catalog:PGS000018",
        "evidence_quality": "moderate",
        "gene_symbols": [],
        "clinical_escalation": None,
        "drugs": None,
    },
)


def stage_run_with_findings(
    derived_root: Path,
    findings: Sequence[dict[str, Any]],
    *,
    run_id: str = "2026-05-15T00-00-00Z-smoke",
    sample_id: str = "live-smoke",
    fixture_sha: str = "f" * 64,
) -> Path:
    """Stage a `derived/<run-id>/` directory carrying the supplied findings.

    Creates the manifest, the `variants.duckdb` store (with `findings`
    table), inserts each row carrying the canonical seven provenance
    columns, and updates the `CURRENT` symlink so the host service's
    run-id resolver picks this run up.

    Returns the run directory path.
    """
    if not findings:
        raise ValueError("stage_run_with_findings requires at least one finding")

    derived_root.mkdir(parents=True, exist_ok=True)
    run_dir = derived_root / run_id
    run_dir.mkdir()

    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "schema_version": SCHEMA_VERSION, "sample_id": sample_id})
    )

    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    _insert_findings(store_path, findings, fixture_sha=fixture_sha)
    update_current_symlink(derived_root, run_id)
    return run_dir


def _insert_findings(
    store_path: Path,
    findings: Sequence[dict[str, Any]],
    *,
    fixture_sha: str,
) -> None:
    """Insert `findings` into `store_path/variants.duckdb`'s `findings` table.

    Each row gets the canonical seven provenance columns stamped with a
    fixture-marker tool name + the current schema version + an UTC `now`
    timestamp. The synthetic provenance is sufficient for the host
    service's `/v1/findings*` endpoints; pipeline-grade provenance comes
    from the real ingest path, not from live-smoke stagers.
    """
    now = datetime.now(tz=UTC)
    conn = duckdb.connect(str(store_path))
    try:
        for f in findings:
            conn.execute(
                """
                INSERT INTO findings (
                    id, category, title, summary,
                    evidence_ref, evidence_quality,
                    gene_symbols, drugs, clinical_escalation,
                    source_path, source_sha256, tool, tool_version,
                    params_json, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'live-smoke-fixture', ?, 'live-smoke-fixture', '0.0',
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
                    f.get("drugs"),
                    f.get("clinical_escalation"),
                    fixture_sha,
                    SCHEMA_VERSION,
                    now,
                ],
            )
    finally:
        conn.close()


# Slice 3 fixture — a deliberately-weak prior memory note about Story 9's
# topic. The note's conclusion ("CYP1A2 *1F/*1F clearly causes large
# chronic-late-caffeine effects on sleep onset latency") **overreaches
# the literature** — the slice-1 live snapshot already verified that
# current evidence does NOT support a CYP1A2-specific effect of this
# magnitude on chronic-late-caffeine + SOL.
#
# The note also violates the INV-A001 primary-source-required rule: it
# cites only a `memory:` ref. Either of these gaps (overreach OR
# memory-only citations) should trigger the agent's INV-C001 v1.6
# memory-validation step + a `Supersedes:` write before reply.
#
# Pre-staged at `/sandbox/.openclaw/workspace/MEMORY.md` via the
# orchestrator's `extra_workspace_files` parameter. The pi-harness's
# `memory_search` retrieves notes from this file (semantic search over
# `MEMORY.md` + daily notes).
STORY9_WEAK_MEMORY_NOTE = """\
# MEMORY.md

## 2026-02-12 — CYP1A2 caffeine synthesis (cyp1a2-caffeine-synthesis)

**Question**: How does CYP1A2 *1F/*1F affect caffeine metabolism and sleep?

**Tool calls (research phase, reasoning=high)**:
- (none recorded)

**Sources retrieved**:
- memory:cyp1a2-prior-research#cyp1a2-summary

**Synthesis (reasoning=max)**:
CYP1A2 *1F/*1F (rs762551 A/A) is the slow-metabolizer genotype. The slow
clearance means caffeine consumed in the late afternoon or evening clearly
causes large effects on sleep onset latency in homozygous *1F carriers —
much larger than in faster-metabolizer genotypes. Carriers should expect
≥30 minutes additional sleep onset latency after a 200 mg dose at 4 PM.

**Calibration**:
- Effect size: large
- Evidence quality: strong-replicated
- Heterogeneity: homogeneous
- Modulators: none worth flagging

**Recommendation framing**:
Strict caffeine cutoff at 12 PM is essentially required for CYP1A2 *1F/*1F
homozygotes who want normal sleep onset latency.

**Citations surfaced to the user**:
memory:cyp1a2-prior-research#cyp1a2-summary

**Freshness**: as of 2026-02-12. Re-research in 12 months.
"""


__all__ = [
    "STORY4_CYP2C19_FINDINGS",
    "STORY9_CYP1A2_FINDINGS",
    "STORY9_WEAK_MEMORY_NOTE",
    "STORY10_CAD_PRS_FINDINGS",
    "stage_run_with_findings",
]

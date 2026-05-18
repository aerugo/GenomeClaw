"""Pydantic response model for ``/v1/gene/{symbol}``.

Phase 5 Slice C. Aggregates the variants + coverage_qc tables into a
single per-gene summary:

- ``gene`` — canonical (DB-stored, HGNC-style uppercase) gene symbol.
- ``n_variants_in_gene`` — count of ``variants`` rows whose
  ``gene_symbol`` matches the canonical form (bounded; the plugin's
  ``genomeclaw_variant`` browse flow is the documented path for the
  per-row data).
- ``mean_depth`` — mosdepth gene-level mean coverage from
  ``coverage_qc``. ``None`` when the gene has variants but no
  curated-coverage row (per spec AC8 per-exon coverage is materialised
  only for the clinically-relevant subset).
- ``low_coverage_exons`` — list of exon identifiers below the
  low-coverage threshold; empty when the gene isn't in the curated
  subset, or when every exon is well-covered.
- ``schema_version`` — pinned to the active run's schema so the agent
  can compare against `/v1/health`.

`INV-P002`: the response is an aggregate. Raw variant rows live behind
``/v1/variants`` + ``/v1/variants/{key}``; this endpoint never inlines
them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GeneResponse(BaseModel):
    """``/v1/gene/{symbol}`` happy-path body."""

    model_config = ConfigDict(extra="forbid")

    gene: str
    n_variants_in_gene: int
    mean_depth: float | None
    low_coverage_exons: list[str]
    schema_version: str


class GeneErrorResponse(BaseModel):
    """``/v1/gene/{symbol}`` 404 / 503 body."""

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = ["GeneErrorResponse", "GeneResponse"]

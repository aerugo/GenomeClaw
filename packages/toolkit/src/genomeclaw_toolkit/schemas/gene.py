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
    region_class: str | None = None
    """Per coverage-panel-v2: the gene's coverage-reliability class from
    `coverage_qc.region_class`. None for pre-v2 rows OR genes not in
    the curated coverage panel. Service-layer-derived; never stored
    in `GeneResponse` JSON when None."""

    caveat: str | None = None
    """Derived at the route layer from `region_class` via
    :func:`_region_class_caveat`. Non-null whenever `region_class` is
    in the difficult-region set; null for `"standard"` / `None`. The
    agent must surface this verbatim or paraphrase when present —
    a normal `mean_depth` over a difficult region does NOT confirm
    variant callability."""


# Per-class caveat strings (coverage-panel-v2 Phase 3). The text fires
# whenever the agent receives a `region_class` outside the `"standard"`
# set; INV-C001 v1.7 requires this be a structural mitigation against
# false-reassurance from a clean mosdepth depth number over PMS2/SMN1.
_CAVEAT_BY_REGION_CLASS: dict[str, str] = {
    "difficult_pseudogene": (
        "Coverage depth over this region is not sufficient to confirm variant "
        "callability. This locus is in a known short-read-WGS difficult_pseudogene "
        "region (a paralogous pseudogene interferes with mapping; mosdepth depth "
        "looks fine but variant calls are unreliable). Pathogenic variants may be "
        "missed or miscalled. Seek orthogonal confirmation (long-read sequencing, "
        "a gene-specific assay, or a dedicated caller)."
    ),
    "difficult_segdup": (
        "Coverage depth over this region is not sufficient to confirm variant "
        "callability. This locus is in a known short-read-WGS difficult_segdup "
        "region (segmental duplication or VNTR interferes with unique-read "
        "mapping). Pathogenic variants may be missed or miscalled. Seek orthogonal "
        "confirmation (long-read sequencing or a gene-specific assay)."
    ),
    "requires_dedicated_caller": (
        "Coverage depth over this region is not sufficient to interpret. This locus "
        "requires_dedicated_caller (short-read WGS coverage QC is structurally "
        "insufficient; a dedicated caller is the truth source — e.g. Cyrius for "
        "CYP2D6, HLA-LA / Optitype for HLA, or an SMA-specific caller for SMN1)."
    ),
    "mitochondrial": (
        "This region is on the mitochondrial contig. Heteroplasmy semantics differ "
        "from nuclear variant calling: per-position depth on the MT contig reflects "
        "the mixed mitochondrial-DNA population rather than a per-sample diploid "
        "genotype. Interpret with mitochondrial-aware tools (MT-RNR1 for "
        "aminoglycoside ototoxicity per CPIC)."
    ),
}


def _region_class_caveat(region_class: str | None) -> str | None:
    """Map a `region_class` value to its agent-facing caveat string.

    Returns:
        - ``None`` when `region_class` is ``"standard"`` or ``None`` (a
          standard region's coverage_qc number is interpretable on its own;
          the caveat would dilute the signal).
        - The canonical per-class warning string for the four difficult
          classes (`difficult_pseudogene`, `difficult_segdup`,
          `requires_dedicated_caller`, `mitochondrial`).
        - ``None`` for an unknown class (defensive: a future class added
          to the panel without an accompanying caveat does not appear at
          the agent surface; the
          `test_invC001_caveat_non_null_for_all_difficult_classes` gate
          fails-fast if a new class is added without a caveat entry).
    """
    if region_class in (None, "standard"):
        return None
    return _CAVEAT_BY_REGION_CLASS.get(region_class)


class GeneErrorResponse(BaseModel):
    """``/v1/gene/{symbol}`` 404 / 503 body."""

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = [
    "GeneErrorResponse",
    "GeneResponse",
    "_region_class_caveat",
]

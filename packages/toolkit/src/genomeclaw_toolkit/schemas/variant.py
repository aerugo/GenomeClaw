"""Pydantic response models for ``/v1/variants`` + ``/v1/variants/{key}``.

Phase 5 Slice B. Two views over the same underlying ``variants`` table:

- :class:`VariantSummary` — list-view row. Pinned to the minimal set the
  agent needs to triage a candidate variant in a multi-row response
  (identity, gene context, the single popmax frequency, one
  pathogenicity hint, one missense-impact hint). Excludes the 9
  individual gnomAD population AFs (bulk-class per ``INV-P002``).
- :class:`VariantDetail` — single-variant detail. Adds the full VEP
  consequence picture + clinvar review status + dbsnp rsid + loftee
  filter + alphamissense class + gene loeuf. Still excludes the 7
  provenance columns (those live at ``/v1/provenance/{run-id}``).

`INV-P002` runtime enforcement layer #1 (host service shaping) — every
field on these models is deliberate. Adding a new field to the table
schema does NOT automatically expose it through the service; the plugin
+ agent see only what these models declare.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class VariantSummary(BaseModel):
    """One row of ``/v1/variants?...`` (list-view).

    The list view's job is to support a "scroll through filtered
    variants" UX without inflating each row. Eight fields beyond
    identity. Per-population AFs are NOT here — the popmax summary
    represents them.
    """

    model_config = ConfigDict(extra="forbid")

    chrom: str
    pos: int
    rsid: str | None
    ref: str
    alt: str
    gene_symbol: str | None
    consequence: str | None
    clinvar_classification: str | None
    gnomad_af_popmax: float | None
    gnomad_af_popmax_pop: str | None
    alphamissense_score: float | None


class VariantDetail(VariantSummary):
    """Single-variant body for ``/v1/variants/{key}``.

    Extends :class:`VariantSummary` with the per-variant context fields
    that matter for a single-variant deep-dive: sample's genotype, the
    full VEP consequence picture (MANE Select + MANE Plus Clinical
    transcripts + HGVS), the transcript-discordance flag, the LOFTEE
    filter reason when ``loftee_lof == 'LC'``, the AlphaMissense
    interpretation class, and the gene-level LOEUF for haploinsufficiency
    triage. The 7 provenance columns are deliberately absent.
    """

    sample_id: str
    genotype: str
    qual: float | None
    filter: str | None
    clinvar_id: str | None
    clinvar_review_status: str | None
    dbsnp_rsid: str | None
    mane_select_transcript: str | None
    mane_plus_clinical_transcript: str | None
    transcript_discordant: bool | None
    hgvsc: str | None
    hgvsp: str | None
    loftee_lof: str | None
    loftee_filter: str | None
    alphamissense_class: str | None
    gene_loeuf: float | None


class VariantsListResponse(BaseModel):
    """Top-level body for ``/v1/variants?limit=N&offset=M``.

    Pagination is offset-based: ``next_offset`` is null at end-of-stream.
    The plugin's ``genomeclaw_variant`` browse flow walks this cursor.
    ``total`` is the unfiltered row count for the active run; the agent
    uses it to frame "this is page 3 of ~5000 variants" responses.
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[VariantSummary]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class VariantErrorResponse(BaseModel):
    """``/v1/variants*`` 400 / 404 / 503 body."""

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = [
    "VariantDetail",
    "VariantErrorResponse",
    "VariantSummary",
    "VariantsListResponse",
]

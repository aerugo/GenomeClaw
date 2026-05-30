"""Pydantic models + canonical column-name constants shared by the CLI and the
host service.

The schemas here anchor `INV-R001`'s structural side: every derived row
carries the seven canonical provenance columns (`source_path`,
`source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`,
`created_at`), and every per-run JSON artifact (manifest, provenance) has
a typed model with strict field validation.
"""

from __future__ import annotations

SCHEMA_VERSION: str = "v0.4"
"""Active derived-store schema version.

- v0.1 (Phases 2 + 3): variants table + coverage_qc + schema_meta. Per-row
  domain columns: chrom, pos, id, ref, alt, qual, filter, sample_id,
  genotype + the seven canonical provenance columns.
- v0.2 (Phase 4A): adds ClinVar annotation columns to variants —
  ``clinvar_id``, ``clinvar_classification``, ``clinvar_review_status``.
  All nullable; pre-annotate rows have NULLs in these columns.
  Phase-4B/C/D/E sub-phases extended with VEP / LOFTEE / AlphaMissense
  columns; those rode on v0.2 (additive non-breaking column additions).
- v0.3 (vep-mane-plus-clinical Phase 3 + coverage-panel-v2): adds
  ``mane_plus_clinical_transcript`` + ``transcript_discordant`` to
  variants (captures the 73 MANE v1.5 Plus Clinical genes and the
  dual-row emit flag); coverage-panel-v2 (the Stage 2 sibling) also
  targets v0.3 for additive coverage_qc changes. Both Stage 2 plans
  land additive changes that ride on this single bump.
- v0.4 (`prs-calibration-phase3b` Phases 1 + 2): adds three columns to
  ``pgs_scores`` — ``effect_weight_match_rate`` (Phase 1 — the
  effect-weight-weighted overlap axis, ``Σ|β|_matched / Σ|β|_total``),
  ``fraposa_min_mahalanobis_distance`` (Phase 2 — minimum top-10-PC
  Mahalanobis distance to any 1kGP+HGDP superpopulation centroid), and
  ``fraposa_nearest_superpop`` (Phase 2 — the superpop label with the
  minimum distance). All three are nullable; pre-v0.4 ``pgs_scores``
  rows carry NULLs for them."""

PROVENANCE_COLUMNS: tuple[str, ...] = (
    "source_path",
    "source_sha256",
    "tool",
    "tool_version",
    "params_json",
    "schema_version",
    "created_at",
)
"""The seven canonical provenance column names mandated by `INV-R001`.

Every derived row in every table inherits these. Wrapper code reaches for
this constant tuple instead of re-listing the names; a typo in any one
place becomes a single-source edit.
"""

__all__ = ["PROVENANCE_COLUMNS", "SCHEMA_VERSION"]

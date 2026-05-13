"""Pydantic models + canonical column-name constants shared by the CLI and the
host service.

The schemas here anchor `INV-R001`'s structural side: every derived row
carries the seven canonical provenance columns (`source_path`,
`source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`,
`created_at`), and every per-run JSON artifact (manifest, provenance) has
a typed model with strict field validation.
"""

from __future__ import annotations

SCHEMA_VERSION: str = "v0.2"
"""Active derived-store schema version.

- v0.1 (Phases 2 + 3): variants table + coverage_qc + schema_meta. Per-row
  domain columns: chrom, pos, id, ref, alt, qual, filter, sample_id,
  genotype + the seven canonical provenance columns.
- v0.2 (Phase 4A): adds ClinVar annotation columns to variants —
  ``clinvar_id``, ``clinvar_classification``, ``clinvar_review_status``.
  All nullable; pre-annotate rows have NULLs in these columns. Future
  Phase-4B/C/D/E sub-phases extend with VEP / LOFTEE / AlphaMissense
  columns; the schema-version field stays at v0.2 across those
  sub-phases (they're additive non-breaking column additions). A future
  v0.3 lands when the column set stabilises post-Phase-4."""

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

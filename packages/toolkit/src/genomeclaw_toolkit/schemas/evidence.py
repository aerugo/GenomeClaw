"""Pydantic `EvidenceRecord` model for `/v1/evidence/{ref}`.

Phase 6 Slice B shipped the resolver; agent-research-and-synthesis
Phase 1 (2026-05-15) retired the curated-notes kinds. The host service's
evidence resolver now supports **variant-keyed kinds only**, per the
v1.6 INVARIANTS revision (see the
[agent-research-and-synthesis spec][plan] and the retirement of
`reference/curated_notes/` in INV-C001 v1.6).

[plan]: ../../../../docs/plans/active/agent-research-and-synthesis/spec.md


| Kind          | id shape          | Resolved from                              |
|---------------|-------------------|--------------------------------------------|
| `clinvar`     | RCV / VCV id      | Variants table row joined on `clinvar_id`  |
| `pgs_catalog` | PGS Catalog id    | (Slice E) `pgs_scores` table               |
| `pharmgkb`    | PharmGKB pa-id    | (Slice D) PharmCAT outside-call output     |

The `gene_note:` and `topic:` kinds previously shipped under MVP spec Q9
are **retired**. Lifestyle calibration now flows through the agent's
research-and-synthesis pattern: `memory:` (prior agent synthesis) +
`web:` (current online source) citations on the sandbox side. The host
service does not resolve these — they are agent-workspace concerns.

`INV-P002`: every response is a bounded summary. The clinvar resolver
returns the classification + review status + canonical identifier,
never the full variants row.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceKind = Literal[
    "clinvar",
    "pgs_catalog",
    "pharmgkb",
]
"""The three variant-keyed evidence kinds the host service resolves.

All resolve via database lookups against the active run's `variants.duckdb`
+ (Phase 6 Slice E) `pgs_scores` + (Phase 6 Slice D) PharmCAT outside-call
output.

A future expansion (e.g. `pubmed:<pmid>` for a literature lookup) extends
this enum + the resolver dispatch table.
"""


class EvidenceRecord(BaseModel):
    """One evidence record returned from `GET /v1/evidence/{ref}`.

    The `body` field carries the rendered evidence content (curated-note
    Markdown or a synthesised summary from the variants table). The
    `source` field names the on-disk origin (path under reference_dir
    or `variants.duckdb`) so a reviewer can trace where the body came
    from.
    """

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    id: str = Field(min_length=1)
    body: str = Field(min_length=1)
    source: str = Field(min_length=1)


class EvidenceErrorResponse(BaseModel):
    """`/v1/evidence/{ref}` 400 / 404 body."""

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = [
    "EvidenceErrorResponse",
    "EvidenceKind",
    "EvidenceRecord",
]

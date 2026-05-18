"""Pydantic `Finding` + list-response models for `/v1/findings*` (Phase 6 Slice A).

Two structural invariants enforced at construction time:

- ``INV-E001`` — every finding carries a non-empty ``evidence_ref``.
  Findings with no evidence reference cannot exist; a future code path
  that tries to construct one fails at the schema layer.
- ``INV-C001`` v1.5 — ``category == "clinical-actionable"`` requires a
  ``clinical_escalation`` marker; non-actionable categories must NOT
  carry one. Mixing the two would mislead the agent into rendering
  benign-sounding prose around an urgent finding (or vice versa).

`INV-P002`: every model is strict (``extra="forbid"``). The list +
detail responses surface only the documented columns; the seven
canonical provenance columns live behind ``/v1/provenance/{run-id}``,
not inlined here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal[
    "clinical-actionable",
    "clinical-non-actionable",
    "lifestyle",
    "mixed",
]
"""The four finding categories per [spec.md AC4](../../../docs/plans/active/mvp/spec.md).

A future expansion (e.g. `research`) extends this enum + the model +
the per-category INV-C001 logic + the test in
[test_finding_model.py::test_category_enum_is_pinned](../../../tests/integration/test_finding_model.py).
"""

EvidenceQuality = Literal["high", "moderate", "low"]
"""Coarse confidence band on the evidence reference.

Pinned in v0; downstream tooling (the agent's prose calibrator)
consumes this directly to modulate hedging language.
"""

ClinicalEscalation = Literal["confirm_with_provider", "urgent_consultation"]
"""The two documented escalation markers.

``confirm_with_provider``: the finding should be discussed at a routine
visit. ``urgent_consultation``: the finding warrants prompt clinical
follow-up. Both surface as structurally-marked fields the agent must
preserve verbatim in its prose framing.
"""


class Finding(BaseModel):
    """One row of the findings table.

    Constructed from a `findings.duckdb` row or from a future pipeline
    step that materialises findings from variants + curated notes. The
    invariants encoded here are the structural floor; the prose-quality
    + framing checks live in the Slice F snapshot tests against the
    agent's natural-language output.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Category
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)

    evidence_ref: str = Field(min_length=1)
    """`<kind>:<id>` per the Slice B EvidenceResolver dispatch (e.g.
    `clinvar:RCV000031`, `gene_note:LCT`, `pgs_catalog:PGS003725`)."""

    evidence_quality: EvidenceQuality

    gene_symbols: list[str] = Field(default_factory=list)
    """HGNC gene symbols this finding cites. May be empty for
    PRS-class findings or topic-level findings that don't pin a gene."""

    drugs: list[str] | None = None
    """Drug names this finding bears on. Only meaningful for PGx
    findings (e.g. CYP2D6 → codeine, tramadol)."""

    clinical_escalation: ClinicalEscalation | None = None
    """Set on every `clinical-actionable` finding; must be `None` on
    every non-actionable finding. Enforced by `_invC001` below."""

    @model_validator(mode="after")
    def _enforce_inv_c001(self) -> Finding:
        """Enforce `INV-C001` v1.5 in the model.

        Two failure modes:
        - clinical-actionable without escalation: agent renders as
          benign-looking prose, hiding urgency.
        - non-actionable WITH escalation: falsely elevates a lifestyle
          or non-actionable finding to clinical urgency.
        """
        if self.category == "clinical-actionable":
            if self.clinical_escalation is None:
                raise ValueError(
                    "INV-C001 v1.5: clinical-actionable findings must declare a "
                    "clinical_escalation marker (confirm_with_provider | urgent_consultation)"
                )
        elif self.clinical_escalation is not None:
            raise ValueError(
                f"INV-C001 v1.5: non-actionable category {self.category!r} must NOT "
                f"carry clinical_escalation; got {self.clinical_escalation!r}"
            )
        return self


class FindingsListResponse(BaseModel):
    """Top-level body for `/v1/findings?...`.

    Pagination mirrors `/v1/variants`: offset-based with
    `next_offset == null` at end-of-stream. Filters (`category`, `genes`,
    `drugs`) live as query params; `total` counts the *filtered* result
    set so the agent can frame "page 2 of 11 findings" responses.
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[Finding]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class FindingErrorResponse(BaseModel):
    """`/v1/findings*` 404 / 503 body."""

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = [
    "Category",
    "ClinicalEscalation",
    "EvidenceQuality",
    "Finding",
    "FindingErrorResponse",
    "FindingsListResponse",
]

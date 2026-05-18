"""Phase 6 Slice A — `Finding` Pydantic model contract tests.

Two invariants enforced at the model layer:

- ``INV-E001`` — every emitted finding carries a non-empty
  ``evidence_ref``. The Pydantic model rejects construction without one.
- ``INV-C001`` v1.5 — findings with ``category == "clinical-actionable"``
  carry a ``clinical_escalation`` marker; the model enforces the
  combination at validation time.

These tests run on the bare host venv (no bio, no sandbox). They are
the structural floor; the agent-prose snapshot tests for Stories 2/4/9/10
(Slice F) sit on top and verify that the agent's natural-language
framing matches the curated-note discipline.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genomeclaw_toolkit.schemas.finding import Finding


def _minimal_finding(**overrides: object) -> dict[str, object]:
    """Build a kwargs dict for `Finding(**dict)` with defaults that pass."""
    defaults: dict[str, object] = {
        "id": "fnd-001",
        "category": "clinical-non-actionable",
        "title": "Test finding",
        "summary": "A short, agent-readable summary.",
        "evidence_ref": "clinvar:RCV000001",
        "evidence_quality": "moderate",
        "gene_symbols": ["BRCA1"],
        "clinical_escalation": None,
    }
    defaults.update(overrides)
    return defaults


def test_invE001_finding_rejects_without_evidence_ref() -> None:
    """``INV-E001``: a Finding with no evidence_ref is invalid.

    The schema's `evidence_ref` is required + non-empty; a future
    regression that introduces a code path constructing a Finding
    without one surfaces here before any prose rendering.
    """
    kwargs = _minimal_finding(evidence_ref="")
    with pytest.raises(ValidationError):
        Finding(**kwargs)  # type: ignore[arg-type]


def test_invE001_finding_rejects_when_evidence_ref_missing() -> None:
    """Same contract, different shape: omitting the field entirely fails."""
    kwargs = _minimal_finding()
    del kwargs["evidence_ref"]
    with pytest.raises(ValidationError):
        Finding(**kwargs)  # type: ignore[arg-type]


def test_invC001_clinical_actionable_requires_escalation() -> None:
    """``INV-C001`` v1.5: clinical-actionable findings carry an escalation marker.

    A `clinical-actionable` finding without a `clinical_escalation`
    marker is a structural failure — the agent would render it as
    benign-looking prose, masking the urgency.
    """
    kwargs = _minimal_finding(
        category="clinical-actionable",
        clinical_escalation=None,
    )
    with pytest.raises(ValidationError):
        Finding(**kwargs)  # type: ignore[arg-type]


def test_invC001_clinical_actionable_with_escalation_validates() -> None:
    """The same finding with a valid escalation marker validates."""
    kwargs = _minimal_finding(
        category="clinical-actionable",
        clinical_escalation="confirm_with_provider",
    )
    f = Finding(**kwargs)  # type: ignore[arg-type]
    assert f.clinical_escalation == "confirm_with_provider"


def test_invC001_non_actionable_must_omit_escalation() -> None:
    """``INV-C001`` corollary: non-actionable categories must NOT carry escalation.

    A lifestyle finding with `clinical_escalation` set would falsely
    elevate it to clinical-grade urgency. The model rejects the
    combination.
    """
    kwargs = _minimal_finding(
        category="lifestyle",
        clinical_escalation="confirm_with_provider",
    )
    with pytest.raises(ValidationError):
        Finding(**kwargs)  # type: ignore[arg-type]


def test_category_enum_is_pinned() -> None:
    """`category` is a closed enum: the four documented values + nothing else.

    A future expansion (e.g. adding `research`) must extend both the
    schema and this test, so the surface stays auditable.
    """
    for valid in ("clinical-actionable", "clinical-non-actionable", "lifestyle", "mixed"):
        # clinical-actionable needs escalation; the others must not have it.
        if valid == "clinical-actionable":
            Finding(**_minimal_finding(category=valid, clinical_escalation="confirm_with_provider"))  # type: ignore[arg-type]
        else:
            Finding(**_minimal_finding(category=valid))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Finding(**_minimal_finding(category="research"))  # type: ignore[arg-type]


def test_finding_strict_extra_forbidden() -> None:
    """``INV-P002`` floor: the model has `extra="forbid"` so accidental field
    bloat in a future change surfaces.
    """
    kwargs = _minimal_finding()
    kwargs["raw_vcf_line"] = "chr1\t100\tA\tT\t..."  # smuggled bulk field
    with pytest.raises(ValidationError):
        Finding(**kwargs)  # type: ignore[arg-type]

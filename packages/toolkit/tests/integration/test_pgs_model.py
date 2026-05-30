"""Phase 6 Slice E v2 — `PgsRowResponse` / `PgsComputeRequest` Pydantic contracts.

The PRS layer is keyed by **PGS Catalog ID** (per Q8 v1.6). These tests pin the
five Pydantic models in [schemas/pgs.py](
../../src/genomeclaw_toolkit/schemas/pgs.py): `PgsRowResponse`, `PgsListResponse`,
`PgsListRow`, `PgsComputeRequest`, `PgsComputeTaskResponse`.

Three model-layer assertions in this file:
- The full-row response shape is exactly the documented field set (no field
  bloat over time per `INV-P002`).
- `PgsComputeRequest` enforces `rationale` length ≥ 50 chars so the agent
  can't bypass `INV-A003`'s "alternatives considered + why this one" contract
  with a one-word rationale.
- The existing `Finding` model already accepts a PRS-class finding row
  (clinical-non-actionable category + no clinical-escalation marker per
  Q8 v1.6); this test pins that contract so a future widening of `Finding`
  doesn't accidentally allow clinical-actionable PRS findings.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genomeclaw_toolkit.schemas.finding import Finding
from genomeclaw_toolkit.schemas.pgs import PgsComputeRequest, PgsRowResponse


def test_pgs_row_response_model_pinned_shape() -> None:
    """`PgsRowResponse` carries exactly the documented fields; `extra="forbid"`.

    A future widening that adds e.g. the raw PGS variant list to this response
    breaks `INV-P002` (the agent would suddenly see thousands of per-variant
    weights). This test catches the field-set drift at construction time.
    """
    row = PgsRowResponse(
        pgs_id="PGS000018",
        trait_label="coronary artery disease (CARDIoGRAMplusC4D + UK Biobank)",
        percentile_in_user_ancestry=87.0,
        raw_score=0.42,
        source_pgs_id="PGS000018",
        study_population="European-ancestry meta-analysis (UK Biobank + CARDIoGRAMplusC4D)",
        calibration_warning=None,
        calibration_status=None,
        decline_reason=None,
        agent_choice_rationale=(
            "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS with the most mature "
            "cross-ancestry calibration. Considered PGS004696 (better Eu discrimination, "
            "less cross-ancestry validation) and PGS003725 (prior version)."
        ),
        requested_for_question="my dad had a heart attack at 58. is there anything in my genome about cad risk?",
        superseded_by=None,
    )
    assert row.pgs_id == "PGS000018"

    # Extra fields are forbidden — INV-P002 floor.
    with pytest.raises(ValidationError):
        PgsRowResponse(
            pgs_id="PGS000018",
            trait_label="coronary artery disease",
            percentile_in_user_ancestry=87.0,
            raw_score=0.42,
            source_pgs_id="PGS000018",
            study_population="European-ancestry meta-analysis",
            calibration_warning=None,
            calibration_status=None,
            decline_reason=None,
            agent_choice_rationale="x" * 60,
            requested_for_question="why?",
            superseded_by=None,
            raw_variant_weights=[("rs123", 0.05)],  # ← would leak per-SNP weights
        )


def test_pgs_compute_request_requires_non_empty_rationale() -> None:
    """`PgsComputeRequest` rejects `rationale` shorter than 10 chars.

    The `rationale` field is the agent's explanation of *why this PGS* —
    alternatives considered, why this one over them, calibration story.
    Phase 2 (agent-prs-compute-fix) lowered the threshold from 50 to 10
    after the 2026-05-23 AMD-question incident where reasoning-pressured
    rationales (~41 chars) were 422'd. The 10-char floor still rejects
    trivially-empty rationales; the agent system prompt continues to
    encourage ≥50-char "alternatives considered" framing.
    """
    # Happy path — long-form canonical rationale.
    valid = PgsComputeRequest(
        pgs_id="PGS000018",
        trait_label="coronary artery disease",
        rationale=(
            "Canonical CARDIoGRAMplusC4D + UK Biobank PRS; best cross-ancestry "
            "calibration. Considered PGS004696 but rejected for less validation."
        ),
        requested_for_question="my dad had a heart attack at 58",
    )
    assert valid.pgs_id == "PGS000018"

    # Reject empty.
    with pytest.raises(ValidationError):
        PgsComputeRequest(
            pgs_id="PGS000018",
            trait_label="coronary artery disease",
            rationale="",
            requested_for_question="why?",
        )

    # Reject below the new 10-char floor.
    with pytest.raises(ValidationError):
        PgsComputeRequest(
            pgs_id="PGS000018",
            trait_label="coronary artery disease",
            rationale="too short",  # 9 chars
            requested_for_question="why?",
        )

    # Accept at-or-above the 10-char floor (regression guard for the
    # 2026-05-23 agent-typical short rationale).
    short_but_valid = PgsComputeRequest(
        pgs_id="PGS000018",
        trait_label="coronary artery disease",
        rationale="canonical CAD PRS",  # 17 chars; rejected on old main, accepted now
        requested_for_question="why?",
    )
    assert short_but_valid.pgs_id == "PGS000018"


def test_finding_accepts_clinical_non_actionable_prs_row() -> None:
    """The existing `Finding` model accepts a PRS-class row per Q8 v1.6.

    PRS findings carry `category: clinical-non-actionable` and no
    `clinical_escalation` marker. The model's `_enforce_inv_c001`
    validator must not reject this shape, AND must reject the
    inconsistent shape (clinical-actionable + no escalation, or
    non-actionable + escalation set).

    Pinning this here so a future widening of `Finding` doesn't
    accidentally allow clinical-actionable PRS findings (which would
    blur INV-C001's research/clinical boundary).
    """
    # Happy path — clinical-non-actionable PRS row.
    prs_finding = Finding(
        id="fnd-cad-prs-001",
        category="clinical-non-actionable",
        title="CAD polygenic risk score — 87th percentile",
        summary="Above-average genetic risk; not a clinical call.",
        evidence_ref="pgs_catalog:PGS000018",
        evidence_quality="moderate",
        gene_symbols=[],
        clinical_escalation=None,
        drugs=None,
    )
    assert prs_finding.evidence_ref == "pgs_catalog:PGS000018"

    # Reject: clinical-actionable without escalation marker.
    with pytest.raises(ValidationError):
        Finding(
            id="fnd-bad-001",
            category="clinical-actionable",
            title="bad",
            summary="bad",
            evidence_ref="pgs_catalog:PGS000018",
            evidence_quality="high",
            gene_symbols=[],
            clinical_escalation=None,  # ← INV-C001 violation
            drugs=None,
        )

    # Reject: non-actionable with escalation marker set.
    with pytest.raises(ValidationError):
        Finding(
            id="fnd-bad-002",
            category="clinical-non-actionable",
            title="bad",
            summary="bad",
            evidence_ref="pgs_catalog:PGS000018",
            evidence_quality="moderate",
            gene_symbols=[],
            clinical_escalation="confirm_with_provider",  # ← INV-C001 violation
            drugs=None,
        )

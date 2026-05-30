"""Phase 1 of cyp2d6-no-call-finding — Cyrius wrapper's no-call path.

The pre-change behaviour was fail-fast: `call_cyp2d6` raised
`CyriusNoGenotypeError` on an empty Cyrius `Genotype` field, halting the
pipeline. That prevents the "silently default to Normal Metabolizer"
failure mode but creates a UX gap: a sample whose CYP2D6 cannot be called
produces NO findings row at all.

This module's tests pin the new behaviour: empty genotype produces a
`None` return, a `cyp2d6_no_call_envelope.json` sentinel under the run
dir (with the seven canonical INV-R001 provenance fields), and a
downstream-readable `cyp2d6_status="no_call"` marker. The CLI layer
inserts the indeterminate `findings` row from this sentinel (see
`test_cli_pipeline_cyp2d6_no_call.py` for the integration test).

Per phase-1.md Step 1.1; spec at
[docs/plans/active/cyp2d6-no-call-finding/spec.md](
../../../../docs/plans/active/cyp2d6-no-call-finding/spec.md).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch


def _fake_cyrius_no_call_json(sample_id: str = "sample") -> dict:
    """Synthetic Cyrius v1.1.1 output with an empty Genotype (no-call path).

    Cyrius v1.1.1 emits Genotype + Filter as STRINGS (empirical 2026-05-22
    smoke regression — see `test_cyrius_wrapper.py` for the discovery).
    The no-call output retains the dict shape but with an empty string for
    Genotype + a filter value of "NO_CALL".
    """
    return {
        sample_id: {
            "Genotype": "",
            "Filter": "NO_CALL",
            "Raw_call": "no call",
        }
    }


def _stub_no_call_subprocess(run_dir: Path, sample_id: str = "sample"):
    """Build a `subprocess.run` stub that writes a no-call Cyrius JSON."""
    output_path = run_dir / "cyp2d6.json"

    def _stub(argv, **_kwargs):  # noqa: ANN001 — mirrors subprocess.run signature
        output_path.write_text(json.dumps(_fake_cyrius_no_call_json(sample_id)))
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=b"", stderr=b""
        )

    return _stub


def test_call_cyp2d6_returns_none_on_empty_genotype(tmp_path: Path) -> None:
    """Empty Genotype: `call_cyp2d6` returns None (does NOT raise).

    The pre-change behaviour was to raise `CyriusNoGenotypeError`, which
    halted the pipeline. The new contract is fail-soft: the wrapper writes
    a no-call sentinel and returns None; the caller branches on the None
    to emit an indeterminate finding row.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(subprocess, "run", side_effect=_stub_no_call_subprocess(run_dir)):
        result = call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
        )

    assert result is None, (
        f"expected call_cyp2d6 to return None on empty Genotype, got {result!r}"
    )


def test_call_cyp2d6_writes_no_call_sentinel_on_empty_genotype(tmp_path: Path) -> None:
    """No-call path writes `cyp2d6_no_call_envelope.json` (NOT `cyp2d6_diplotype.json`)."""
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(subprocess, "run", side_effect=_stub_no_call_subprocess(run_dir)):
        call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
        )

    sentinel = run_dir / "cyp2d6_no_call_envelope.json"
    assert sentinel.exists(), "no-call path did not write the sentinel envelope"
    assert not (run_dir / "cyp2d6_diplotype.json").exists(), (
        "no-call path must not write the success envelope"
    )

    body = json.loads(sentinel.read_text())
    assert body["cyp2d6_status"] == "no_call"
    assert body["sample_id"] == "sample"
    assert body["filter_status"]  # non-null, either "NO_CALL" or the Cyrius filter value
    assert "provenance" in body
    # The raw Cyrius output is the audit surface — keep it in the envelope.
    assert "raw_cyrius_output" in body


def test_invR001_cyp2d6_no_call_envelope_provenance_complete(tmp_path: Path) -> None:
    """INV-R001: the sentinel envelope carries all seven canonical provenance fields."""
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(subprocess, "run", side_effect=_stub_no_call_subprocess(run_dir)):
        call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
        )

    body = json.loads((run_dir / "cyp2d6_no_call_envelope.json").read_text())
    provenance = body["provenance"]
    for required in (
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    ):
        assert required in provenance and provenance[required], (
            f"INV-R001: sentinel provenance missing or empty field {required!r}; "
            f"got {provenance!r}"
        )
    assert provenance["tool"] == "cyrius"


def test_cyp2d6_no_call_finding_validates_pydantic() -> None:
    """A `Finding` constructed with the exact indeterminate-row values is valid.

    Documents the INV-C001 v1.5 contract for the indeterminate finding:
    clinical-actionable category requires a non-null `clinical_escalation`
    marker. This test is the schema-layer pin for what the CLI helper will
    INSERT into the `findings` table.
    """
    from genomeclaw_toolkit.schemas.finding import Finding

    finding = Finding(
        id="fnd-cyp2d6-no-call-deadbeef",
        category="clinical-actionable",
        title="CYP2D6 — indeterminate (no-call)",
        summary=(
            "CYP2D6 could not be called from this sample's coverage at the "
            "CYP2D6/CYP2D7 locus. Do not interpret as Normal Metabolizer. "
            "Confirm status with your provider before any codeine, tramadol, "
            "or other CYP2D6-substrate medication decisions."
        ),
        evidence_ref="cyrius_no_call:/tmp/fake/cyp2d6_no_call_envelope.json",
        evidence_quality="low",
        gene_symbols=["CYP2D6"],
        drugs=[
            "codeine",
            "tramadol",
            "oxycodone",
            "tamoxifen",
            "fluoxetine",
            "paroxetine",
            "venlafaxine",
            "atomoxetine",
        ],
        clinical_escalation="confirm_with_provider",
    )

    assert finding.category == "clinical-actionable"
    assert finding.clinical_escalation == "confirm_with_provider"
    assert "do not interpret as Normal Metabolizer" in finding.summary.lower() or (
        "Do not interpret as Normal Metabolizer" in finding.summary
    )


def test_invC001_cyp2d6_indeterminate_finding_has_escalation() -> None:
    """INV-C001 v1.5: a clinical-actionable finding without escalation is rejected.

    Structural contract test: the indeterminate finding is
    `clinical-actionable` and must carry `clinical_escalation`.
    """
    import pytest as _pytest

    from genomeclaw_toolkit.schemas.finding import Finding

    base_kwargs: dict = {
        "id": "fnd-cyp2d6-no-call-deadbeef",
        "category": "clinical-actionable",
        "title": "CYP2D6 — indeterminate (no-call)",
        "summary": "Do not interpret as Normal Metabolizer.",
        "evidence_ref": "cyrius_no_call:/tmp/fake/sentinel.json",
        "evidence_quality": "low",
        "gene_symbols": ["CYP2D6"],
    }
    with _pytest.raises(ValueError, match="INV-C001"):
        Finding(**base_kwargs, clinical_escalation=None)

    # The intended shape passes.
    ok = Finding(**base_kwargs, clinical_escalation="confirm_with_provider")
    assert ok.clinical_escalation == "confirm_with_provider"


def test_invE001_cyp2d6_indeterminate_finding_has_evidence_ref() -> None:
    """INV-E001: indeterminate finding `evidence_ref` is non-empty and points at the sentinel.

    The sentinel JSON file IS the evidence — it carries the raw Cyrius
    output + the seven canonical provenance fields. The `evidence_ref`
    format is `cyrius_no_call:<absolute-path>` so the reference is
    machine-resolvable without any network call.
    """
    import pytest as _pytest
    from pydantic import ValidationError

    from genomeclaw_toolkit.schemas.finding import Finding

    base_kwargs: dict = {
        "id": "fnd-cyp2d6-no-call-deadbeef",
        "category": "clinical-actionable",
        "title": "CYP2D6 — indeterminate (no-call)",
        "summary": "Do not interpret as Normal Metabolizer.",
        "evidence_quality": "low",
        "gene_symbols": ["CYP2D6"],
        "clinical_escalation": "confirm_with_provider",
    }
    # Empty evidence_ref is rejected (min_length=1).
    with _pytest.raises(ValidationError):
        Finding(**base_kwargs, evidence_ref="")

    # The intended shape uses the `cyrius_no_call:` prefix.
    ok = Finding(
        **base_kwargs,
        evidence_ref="cyrius_no_call:/tmp/fake/cyp2d6_no_call_envelope.json",
    )
    assert ok.evidence_ref.startswith("cyrius_no_call:")


def test_invD001_bam_unchanged_after_cyp2d6_no_call(tmp_path: Path) -> None:
    """INV-D001: the source BAM is not mutated by the no-call path.

    Captures mtime + SHA256 before and after the call; asserts both
    unchanged. Also confirms the new fail-soft contract by asserting the
    call returns None rather than raises.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam contents")

    mtime_before = bam.stat().st_mtime
    digest_before = hashlib.sha256(bam.read_bytes()).hexdigest()

    with patch.object(subprocess, "run", side_effect=_stub_no_call_subprocess(run_dir)):
        result = call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
        )

    assert result is None, "no-call must return None, not raise"
    assert bam.stat().st_mtime == mtime_before, "INV-D001: BAM mtime changed"
    assert hashlib.sha256(bam.read_bytes()).hexdigest() == digest_before, (
        "INV-D001: BAM contents changed"
    )

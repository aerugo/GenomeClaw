"""Phase 3 — ``genomeclaw pipeline normalize`` orchestrator tests.

``normalize(run_dir, ...)`` operates on an existing ``derived/<run-id>/``
from a prior ``ingest`` call:

1. Reads ``manifest.json`` to find the source VCF + its sha256.
2. Runs ``bcftools norm -m-`` on the source → ``run_dir/normalized.vcf.gz``.
3. Indexes the normalized VCF (``.tbi``).
4. Updates ``manifest.json``: appends ``outputs.normalized_vcf`` +
   ``outputs.normalized_vcf_sha256``.
5. Appends a ``normalize`` step to ``provenance.json``.

The variants table is **not** updated by ``normalize`` — that's Phase
3's ``materialize`` step.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_current(derived: Path) -> Path:
    target = os.readlink(derived / "CURRENT")
    return (derived / target).resolve()


@pytest.mark.needs_bio
def test_normalize_writes_normalized_vcf_gz_in_run_dir(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Happy path: ``normalize`` produces ``normalized.vcf.gz`` + ``.tbi`` in the run dir."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="norm-001",
    )
    norm_vcf = normalize(run_dir=run_dir)

    assert norm_vcf == run_dir / "normalized.vcf.gz"
    assert norm_vcf.exists()
    assert (run_dir / "normalized.vcf.gz.tbi").exists()


@pytest.mark.needs_bio
def test_normalize_splits_multiallelic_rows(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """The synthetic fixture's multi-allelic chr17 row → two single-alt rows."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="norm-001",
    )
    norm_vcf = normalize(run_dir=run_dir)

    with gzip.open(norm_vcf, "rt") as fh:
        text = fh.read()
    data_lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    # 5 input rows, one multi-allelic → 6 output rows.
    assert len(data_lines) == 6


@pytest.mark.needs_bio
def test_invR001_normalize_appends_step_to_provenance(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``provenance.json`` gains a ``normalize`` step with input/output identities."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="norm-001",
    )
    norm_vcf = normalize(run_dir=run_dir)

    provenance = json.loads((run_dir / "provenance.json").read_text())
    norm_step = next((s for s in provenance["steps"] if s["step"] == "normalize"), None)
    assert norm_step is not None
    assert norm_step["tool"] == "bcftools"
    assert norm_step["tool_version"]
    # Inputs: source VCF identity (from the ingest step's recorded sha256).
    assert any(inp["sha256"] == _sha256(tiny_vcf_gz) for inp in norm_step["inputs"])
    # Outputs: normalized.vcf.gz identity.
    assert any(out["sha256"] == _sha256(norm_vcf) for out in norm_step["outputs"])


@pytest.mark.needs_bio
def test_normalize_records_normalized_vcf_in_manifest(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Manifest's ``outputs`` gains ``normalized_vcf`` + ``normalized_vcf_sha256``."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="norm-001",
    )
    norm_vcf = normalize(run_dir=run_dir)

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["outputs"]["normalized_vcf"] == "normalized.vcf.gz"
    assert manifest["outputs"]["normalized_vcf_sha256"] == _sha256(norm_vcf)


@pytest.mark.needs_bio
def test_invD001_normalize_does_not_mutate_source_vcf(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """`INV-D001`: the source VCF is unchanged after normalize."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    sha_before = _sha256(tiny_vcf_gz)
    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="norm-001",
    )
    normalize(run_dir=run_dir)
    assert _sha256(tiny_vcf_gz) == sha_before


@pytest.mark.needs_bio
def test_normalize_refuses_when_run_dir_missing(tmp_path: Path) -> None:
    """A non-existent run dir is rejected with FileNotFoundError."""
    from genomeclaw_toolkit.prep.normalize import normalize

    with pytest.raises(FileNotFoundError):
        normalize(run_dir=tmp_path / "no-such-run")


@pytest.mark.needs_bio
def test_normalize_refuses_when_manifest_missing(tmp_path: Path) -> None:
    """An ill-formed run dir (no manifest.json) is rejected with FileNotFoundError."""
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = tmp_path / "fake-run"
    run_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="manifest"):
        normalize(run_dir=run_dir)

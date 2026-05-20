"""Phase 3 — ``compute_prs_with_coverage_fill`` rejects non-sibling-mountable
paths BEFORE any bcftools / pgsc_calc subprocess fires.

The smoke v3 reproducer: the orchestrator was passing a ``work_dir`` rooted
at ``/tmp/genomeclaw-scratch/...`` (container-local) into pgsc_calc; the
sibling containers couldn't see it; pgsc_calc returned rc=1 with a confusing
``No such file`` against a path that DID exist inside the parent container.

After Phase 3, the same mistake raises :class:`DooDPathError` at the boundary,
BEFORE bcftools (or any subprocess) starts. ``subprocess.run.call_count == 0``
proves the failure happens up-front.

Phase plan: [phases/phase-3.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-3.md)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def host_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage a fake canonical root + announce it via ``GENOMECLAW_HOST_ROOTS``."""
    root = tmp_path / "canonical_root"
    for subdir in ("raw", "derived", "_scratch", "reference"):
        (root / subdir).mkdir(parents=True)
    monkeypatch.setenv("GENOMECLAW_HOST_ROOTS", str(root))
    return root


def test_compute_prs_with_coverage_fill_rejects_non_sibling_work_dir(
    host_roots: Path,
    tmp_path: Path,
) -> None:
    """The orchestrator's ``work_dir`` parameter MUST be sibling-mountable.

    When the caller passes a container-local ``/tmp/...`` path (the smoke v3
    misuse), ``compute_prs_with_coverage_fill`` raises :class:`DooDPathError`
    BEFORE any bcftools / pgsc_calc subprocess fires.
    """
    from genomeclaw_toolkit.prep._paths import DooDPathError
    from genomeclaw_toolkit.prep.coverage_fill import compute_prs_with_coverage_fill

    cram = host_roots / "raw" / "user.cram"
    cram.touch()
    sites_tsv = host_roots / "reference" / "sites.tsv"
    sites_tsv.touch()
    alleles_tsv = host_roots / "reference" / "alleles.tsv"
    alleles_tsv.touch()
    scorefile_path = host_roots / "reference" / "scorefile.txt.gz"
    scorefile_path.write_bytes(b"")
    fasta = host_roots / "reference" / "GRCh38.fa"
    fasta.touch()
    reference_root = host_roots / "reference"
    output_root = host_roots / "derived"

    # The smoke v3 misuse: work_dir under ephemeral scratch (container-local).
    bad_work_dir = Path("/tmp/genomeclaw-scratch/prs-work")

    with patch("subprocess.run") as fake_run:
        with pytest.raises(DooDPathError):
            compute_prs_with_coverage_fill(
                sample_id="user",
                cram_path=cram,
                sites_tsv=sites_tsv,
                alleles_tsv=alleles_tsv,
                scorefile_path=scorefile_path,
                fasta=fasta,
                panel_version="hgdp_1kgp_v1",
                reference_root=reference_root,
                output_root=output_root,
                work_dir=bad_work_dir,
                agent_choice_rationale="x" * 60,
                requested_for_question="why?",
            )
        # Validation happens BEFORE any subprocess fires.
        assert fake_run.call_count == 0, (
            f"compute_prs_with_coverage_fill must reject non-sibling-mountable "
            f"work_dir BEFORE subprocess.run; got {fake_run.call_count} call(s)"
        )

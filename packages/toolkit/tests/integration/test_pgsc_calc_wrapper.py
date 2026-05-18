"""Phase 6 Slice E v2 — `pgsc_calc` wrapper contract.

The wrapper invokes `pgsc_calc` (PGS Catalog Calculator, Nextflow) against a
user's VCF for a specific PGS Catalog ID + applies continuous-ancestry
calibration via `--run_ancestry`. These tests stub the actual `subprocess.run`
(`pgsc_calc` is a heavy Nextflow dependency; the real-data smoke runs against
the project owner's host install).

Five contract assertions:

1. The wrapper invokes `pgsc_calc` with the right argv shape — `--input` for
   the samplesheet, `--target_build GRCh38`, `--pgs_id <id>`, `--run_ancestry`.
2. The wrapper parses pgsc_calc's two output files (`aggregated_scores.txt` +
   `aggregated_scores_norm.txt`) into a typed `PgsRow`.
3. The wrapper surfaces a `calibration_warning` when the user's continuous-
   ancestry estimate falls outside the training distribution (per Q8 v1.6
   `INV-C001` — ancestry-calibration failures must surface structurally).
4. The wrapper raises `PgsReferenceMissingError` with a clean install hint
   when the 1000G / HGDP ancestry reference data is missing — *not* a raw
   Nextflow stack trace.
5. The returned `PgsRow` carries the `agent_choice_rationale` +
   `requested_for_question` fields from the wrapper's inputs (`INV-A003`
   provenance threads through from request to row).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from genomeclaw_toolkit.prep.pgs import PgsReferenceMissingError, PgsRow, compute_pgs


def _make_reference_root(tmp_path: Path) -> Path:
    """Stage the canonical post-fetch ancestry layout for compute_pgs tests.

    Verified upstream shape (2026-05-17 real-data smoke against the actual
    PGS Catalog v1 bundle): gnomAD-merged 1000G + HGDP callset extracts
    FLAT into ``pgs_catalog_ancestry/v1/`` — combined files keyed by build
    (no per-population subdirs). Stages the three files pgsc_calc reads
    via ``--run_ancestry``.
    """
    ref = tmp_path / "reference"
    ancestry = ref / "pgs_catalog_ancestry" / "v1"
    ancestry.mkdir(parents=True)
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"data")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"data")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"data")
    (ref / "pgs_catalog").mkdir(parents=True)
    return ref


def _make_pgsc_calc_outputs(
    work_dir: Path,
    *,
    pgs_id: str = "PGS000018",
    raw_score: float = 0.42,
    percentile: float = 87.0,
    calibration_warning: str | None = None,
) -> None:
    """Write fixture pgsc_calc output files into `<work_dir>/{score,ancestry}/`.

    pgsc_calc emits TSVs with a documented column shape; the fixtures here
    use the minimal column set the wrapper needs to parse.
    """
    score_dir = work_dir / "score"
    score_dir.mkdir(parents=True, exist_ok=True)
    # aggregated_scores.txt: sampleset\tIID\tPGS\tSUM\tDENOM\tAVG
    (score_dir / "aggregated_scores.txt").write_text(
        "sampleset\tIID\tPGS\tSUM\tDENOM\tAVG\n"
        f"user\tuser-1\t{pgs_id}\t{raw_score}\t1000\t{raw_score / 1000}\n"
    )

    ancestry_dir = work_dir / "ancestry"
    ancestry_dir.mkdir(parents=True, exist_ok=True)
    # aggregated_scores_norm.txt: sampleset\tIID\tPGS\tpercentile_MostSimilarPop\tcalibration_warning
    warning_field = calibration_warning or ""
    (ancestry_dir / "aggregated_scores_norm.txt").write_text(
        "sampleset\tIID\tPGS\tpercentile_MostSimilarPop\tcalibration_warning\n"
        f"user\tuser-1\t{pgs_id}\t{percentile}\t{warning_field}\n"
    )


def _fake_pgsc_calc_run(
    work_dir: Path,
    *,
    pgs_id: str = "PGS000018",
    percentile: float = 87.0,
    calibration_warning: str | None = None,
) -> MagicMock:
    """Build a `subprocess.run` fake that writes fixture outputs + returns rc=0.

    Used as the side-effect of the `subprocess.run` patch so the wrapper's
    output-parsing path is exercised against realistic file shapes.
    """

    def _runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        _make_pgsc_calc_outputs(
            work_dir,
            pgs_id=pgs_id,
            percentile=percentile,
            calibration_warning=calibration_warning,
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return MagicMock(side_effect=_runner)


def test_compute_pgs_invokes_pgsc_calc_with_run_ancestry(tmp_path: Path) -> None:
    """Wrapper builds the right argv: --target_build GRCh38, --pgs_id, --run_ancestry."""
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    reference_root = _make_reference_root(tmp_path)
    work_dir = tmp_path / "work"

    fake_run = _fake_pgsc_calc_run(work_dir)
    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", fake_run):
        compute_pgs(
            vcf=vcf,
            pgs_id="PGS000018",
            reference_root=reference_root,
            work_dir=work_dir,
            agent_choice_rationale="x" * 60,
            requested_for_question="why?",
        )

    # The wrapper invoked subprocess.run exactly once with the right argv shape.
    assert fake_run.call_count == 1, fake_run.call_args_list
    argv = fake_run.call_args_list[0].args[0]
    argv_str = " ".join(argv)
    assert "pgsc_calc" in argv[0] or any("pgsc_calc" in part for part in argv), argv
    assert "--target_build" in argv and argv[argv.index("--target_build") + 1] == "GRCh38"
    assert "--pgs_id" in argv and argv[argv.index("--pgs_id") + 1] == "PGS000018"
    assert "--run_ancestry" in argv_str, "INV-C001 v1.7 requires ancestry calibration"


def test_compute_pgs_parses_aggregated_scores_into_pgs_row(tmp_path: Path) -> None:
    """The two fixture output files turn into a typed `PgsRow` with the percentile."""
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    reference_root = _make_reference_root(tmp_path)
    work_dir = tmp_path / "work"

    fake_run = _fake_pgsc_calc_run(work_dir, pgs_id="PGS000018", percentile=87.0)
    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", fake_run):
        row = compute_pgs(
            vcf=vcf,
            pgs_id="PGS000018",
            reference_root=reference_root,
            work_dir=work_dir,
            agent_choice_rationale="x" * 60,
            requested_for_question="why?",
        )

    assert isinstance(row, PgsRow)
    assert row.pgs_id == "PGS000018"
    assert row.percentile_in_user_ancestry == 87.0
    assert row.raw_score is not None
    assert row.calibration_warning is None  # empty string in fixture → None


def test_compute_pgs_surfaces_calibration_warning(tmp_path: Path) -> None:
    """A non-empty calibration_warning in the output file makes it through to the PgsRow."""
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    reference_root = _make_reference_root(tmp_path)
    work_dir = tmp_path / "work"

    fake_run = _fake_pgsc_calc_run(
        work_dir,
        pgs_id="PGS000018",
        calibration_warning="ancestry estimate outside training distribution",
    )
    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", fake_run):
        row = compute_pgs(
            vcf=vcf,
            pgs_id="PGS000018",
            reference_root=reference_root,
            work_dir=work_dir,
            agent_choice_rationale="x" * 60,
            requested_for_question="why?",
        )

    assert row.calibration_warning == "ancestry estimate outside training distribution"


def test_compute_pgs_raises_pgs_reference_missing_when_ancestry_data_absent(
    tmp_path: Path,
) -> None:
    """`PgsReferenceMissingError` surfaces with a clean install hint, not a stack trace."""
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    # Reference root exists but the ancestry/{1000g,hgdp} layout is missing.
    reference_root = tmp_path / "reference"
    reference_root.mkdir()
    work_dir = tmp_path / "work"

    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run") as fake_run:
        with pytest.raises(PgsReferenceMissingError, match="ancestry"):
            compute_pgs(
                vcf=vcf,
                pgs_id="PGS000018",
                reference_root=reference_root,
                work_dir=work_dir,
                agent_choice_rationale="x" * 60,
                requested_for_question="why?",
            )
        # The wrapper bailed *before* invoking pgsc_calc.
        assert fake_run.call_count == 0


def test_compute_pgs_pins_profile_conda_and_pgsc_calc_revision_invR001(tmp_path: Path) -> None:
    """The wrapper argv records ``-profile conda`` + ``-r v2.2.0`` so the
    ``pgs_scores.params_json`` provenance trail captures exactly which
    execution mode + pipeline release scored the user's variants.

    PRS Runtime Bootstrap Phase 1 picked ``-profile conda`` (verified against
    pgsc_calc nextflow.config: no ``-profile standard`` exists; ``conda`` is
    the only profile that stays inside GenomeClaw's image-or-volume boundary
    without socket-mounting Docker into the container). The revision pin
    lives in ``_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`` — bumping it
    rebuilds the argv automatically.
    """
    from genomeclaw_toolkit.prep._versions import PRS_RUNTIME_VERSIONS

    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    reference_root = _make_reference_root(tmp_path)
    work_dir = tmp_path / "work"

    fake_run = _fake_pgsc_calc_run(work_dir)
    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", fake_run):
        compute_pgs(
            vcf=vcf,
            pgs_id="PGS000018",
            reference_root=reference_root,
            work_dir=work_dir,
            agent_choice_rationale="x" * 60,
            requested_for_question="why?",
        )

    argv = fake_run.call_args_list[0].args[0]
    assert argv[0] == "nextflow", f"argv[0] must be `nextflow`, got {argv[0]!r}"
    assert "-profile" in argv, "INV-R001: -profile pin must surface in the recorded argv"
    assert argv[argv.index("-profile") + 1] == "conda", (
        f"INV-R001: -profile must be `conda`, got {argv[argv.index('-profile') + 1]!r}"
    )
    assert "-r" in argv, "INV-R001: pgsc_calc revision pin must surface in the recorded argv"
    assert argv[argv.index("-r") + 1] == PRS_RUNTIME_VERSIONS["pgsc_calc"], (
        f"INV-R001: -r must match pin from _versions.py, got "
        f"{argv[argv.index('-r') + 1]!r} vs {PRS_RUNTIME_VERSIONS['pgsc_calc']!r}"
    )


def test_compute_pgs_threads_invA003_provenance_into_row(tmp_path: Path) -> None:
    """`agent_choice_rationale` + `requested_for_question` survive from input → PgsRow."""
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    reference_root = _make_reference_root(tmp_path)
    work_dir = tmp_path / "work"

    rationale = (
        "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS with the most mature "
        "cross-ancestry calibration. Considered PGS004696 and rejected for less "
        "cross-ancestry validation."
    )
    question = "my dad had a heart attack at 58. is there anything in my genome about cad risk?"

    fake_run = _fake_pgsc_calc_run(work_dir)
    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", fake_run):
        row = compute_pgs(
            vcf=vcf,
            pgs_id="PGS000018",
            reference_root=reference_root,
            work_dir=work_dir,
            agent_choice_rationale=rationale,
            requested_for_question=question,
        )

    assert row.agent_choice_rationale == rationale, "INV-A003: rationale must thread through"
    assert row.requested_for_question == question, (
        "INV-A003: requested_for_question must thread through"
    )

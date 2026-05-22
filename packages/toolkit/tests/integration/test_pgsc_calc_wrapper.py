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
    # Phase 5 smoke regression guard: pgsc_calc v2.2.0 retired the `--target`
    # flag in favor of `--input <samplesheet.csv>`. The 2026-05-18 smoke
    # failed silently when the wrapper still used `--target`; this assertion
    # prevents a regression to the old shape.
    assert "--input" in argv, f"pgsc_calc v2.2.0 requires --input, not --target. argv={argv}"
    assert "--target" not in argv, (
        "pgsc_calc v2.2.0 dropped --target; the smoke driver failed silently "
        "with `Please provide an input samplesheet`. Use --input <samplesheet.csv> instead."
    )
    samplesheet_path = argv[argv.index("--input") + 1]
    assert samplesheet_path.endswith(".csv")
    # Samplesheet file was materialised under work_dir.
    from pathlib import Path as _Path

    assert _Path(samplesheet_path).exists()
    csv_content = _Path(samplesheet_path).read_text()
    assert "sampleset,path_prefix,chrom,format,vcf_genotype_field" in csv_content
    assert "vcf,GT" in csv_content
    # Phase 5 smoke regression guard: pgsc_calc's path_prefix is a basename
    # PREFIX (no extension). The 2026-05-19 smoke failed with
    # `No such file: merged.vcf.gz.vcf` because the wrapper was writing the
    # full path including .vcf.gz instead of stripping it.
    for line in csv_content.splitlines()[1:]:  # skip header
        if not line.strip():
            continue
        path_prefix = line.split(",")[1]
        assert not path_prefix.endswith(".vcf.gz"), (
            f"path_prefix must NOT carry the .vcf.gz suffix (pgsc_calc auto-"
            f"appends .vcf); got {path_prefix!r}"
        )
        assert not path_prefix.endswith(".vcf"), (
            f"path_prefix must be a bare prefix; got {path_prefix!r}"
        )


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


def test_compute_pgs_pins_profile_docker_and_pgsc_calc_revision_invR001(tmp_path: Path) -> None:
    """The wrapper argv records ``-profile docker`` + ``-r v2.2.0`` so the
    ``pgs_scores.params_json`` provenance trail captures exactly which
    execution mode + pipeline release scored the user's variants.

    Phase 4a of the [prs-input-coverage-fill plan](../../../../docs/plans/active/prs-input-coverage-fill/development-plan.md)
    flipped this from ``-profile conda`` to ``-profile docker``. The
    2026-05-17 real-data smoke proved that ``-profile conda`` fails on
    linux/arm64 because plink2 2.0a5.10 isn't packaged on conda-forge for
    aarch64; ``-profile docker`` works via DooD against the pre-pulled
    pgsc_calc images. The revision pin lives in
    ``_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`` — bumping it rebuilds
    the argv automatically.
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
    assert argv[argv.index("-profile") + 1] == "docker", (
        f"INV-R001: -profile must be `docker` (smoke-proven 2026-05-17 — "
        f"-profile conda fails on arm64), got {argv[argv.index('-profile') + 1]!r}"
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


def test_compute_pgs_samplesheet_sampleset_has_no_period(tmp_path: Path) -> None:
    """The samplesheet's ``sampleset`` column MUST NOT contain a ``.``.

    pgsc_calc derives downstream filenames as ``GRCh38_<sampleset>_<chrom>.<ext>``
    and the ``intersect_cli`` step parses those by stripping ``_<chrom>``.
    ``Path("merged.vcf.gz").stem == "merged.vcf"`` keeps the dot; pgsc_calc
    then mismatches the derived filename (Phase 7 smoke v13 regression:
    ``FileNotFoundError: GRCh38_merged.afreq.gz`` because the file was actually
    named ``GRCh38_merged.vcf_ALL.afreq.gz``).

    Strip BOTH ``.gz`` and ``.vcf`` to land on a clean periodless sampleset."""
    vcf = tmp_path / "merged.vcf.gz"
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

    samplesheet_path = work_dir / "samplesheet.csv"
    content = samplesheet_path.read_text()
    # Parse the second line (data row) and inspect the sampleset column.
    data_row = content.splitlines()[1]
    sampleset = data_row.split(",")[0]
    assert "." not in sampleset, (
        f"sampleset must not contain '.' — pgsc_calc filename derivation "
        f"breaks for dotted samplesets; got: {sampleset!r}"
    )
    assert sampleset == "merged", (
        f"sampleset for merged.vcf.gz should be 'merged' (no extensions); "
        f"got: {sampleset!r}"
    )


def test_pgsc_calc_argv_includes_resume_flag(tmp_path: Path) -> None:
    """prs-smoke-resilience Phase 4.1: the wrapper's emitted argv includes
    ``-resume`` so re-invocations against the same ``work_dir`` skip
    already-completed Nextflow tasks.

    Enables the Phase 4 recovery loop: when a mid-run drive disconnect
    forces a Colima restart, the smoke driver re-invokes pgsc_calc; with
    ``-resume`` baked in, the second invocation picks up from the last
    cached task instead of starting from scratch (saving 25-90 min per
    recovery cycle).

    Safe to enable unconditionally — on a fresh ``work_dir``,
    ``-resume`` is a no-op (no cached tasks to skip).
    """
    from genomeclaw_toolkit.prep._paths import as_sibling_mountable
    from genomeclaw_toolkit.prep.pgs import _build_pgsc_calc_argv

    samplesheet = as_sibling_mountable(tmp_path / "samplesheet.csv")
    samplesheet.write_text("sampleset,path_prefix,chrom,format,vcf_genotype_field\n")
    work_dir = as_sibling_mountable(tmp_path / "work")
    work_dir.mkdir(exist_ok=True)
    reference_root = as_sibling_mountable(tmp_path / "ref")
    (reference_root / "pgs_catalog_ancestry" / "v1").mkdir(parents=True)

    argv = _build_pgsc_calc_argv(
        samplesheet=samplesheet,
        pgs_id="PGS000018",
        work_dir=work_dir,
        reference_root=reference_root,
    )

    assert "-resume" in argv, (
        f"prs-smoke-resilience Phase 4.1: pgsc_calc argv MUST include "
        f"-resume so recovery loops can pick up cached tasks; got argv={argv}"
    )


def test_tmpdir_redirect_config_includes_error_strategy_retry(tmp_path: Path) -> None:
    """prs-smoke-resilience Phase 3: ``_TMPDIR_REDIRECT_CONFIG`` baked
    into ``nextflow.config`` includes ``errorStrategy = 'retry'`` and
    ``maxRetries = 2`` so transient pgsc_calc failures (v22d's
    heapq.merge KeyError class) get bounded retries instead of aborting
    the whole DAG.

    2 retries gets ~99.9% success when the per-task transient rate is
    <10% (we observed ~5% on v22d's INTERSECT_VARIANTS step).
    """
    from genomeclaw_toolkit.prep._paths import as_sibling_mountable
    from genomeclaw_toolkit.prep.pgs import _write_pgsc_calc_nextflow_config

    work_dir = as_sibling_mountable(tmp_path / "work")
    work_dir.mkdir()
    config_path = _write_pgsc_calc_nextflow_config(work_dir)
    content = config_path.read_text()

    # The directive must be in the process block.
    assert "errorStrategy" in content, (
        f"prs-smoke-resilience Phase 3: nextflow.config must include "
        f"errorStrategy directive; got:\n{content}"
    )
    assert "'retry'" in content or '"retry"' in content, (
        f"errorStrategy value must be 'retry'; got:\n{content}"
    )
    assert "maxRetries" in content, (
        f"maxRetries directive missing; got:\n{content}"
    )
    # 2 retries is the documented bound. A future bump (e.g. to 3) would
    # be a deliberate change; this assertion catches accidental drift.
    assert "maxRetries = 2" in content or "maxRetries=2" in content, (
        f"maxRetries must be exactly 2 (per the empirical 5-10% per-task "
        f"transient rate; 3 attempts → ~99.9% success). got:\n{content}"
    )


def test_compute_pgs_error_includes_both_stdout_and_stderr(tmp_path: Path) -> None:
    """prs-smoke-resilience Phase 2: pgsc_calc rc != 0 surfaces BOTH stdout
    and stderr in the RuntimeError message, not just stderr's last line.

    The v22 ledger's pgsc_calc errors all came back as "pgsc_calc failed
    (rc=1):\\nNextflow 26.04.1 is available - Please consider updating
    your version to it" — the actual pipeline error was burried in
    Nextflow's task .command.err files. stderr's last line is the
    update banner; the real error is in stdout (Nextflow streams DAG
    progress + task failure messages there). Phase 2 surfaces both so
    the debugger doesn't have to dig into work_dir/<hash>/.command.err
    to find what failed.
    """
    import subprocess

    from genomeclaw_toolkit.prep.pgs import compute_pgs

    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    reference_root = _make_reference_root(tmp_path)
    work_dir = tmp_path / "work"

    # Simulate a pgsc_calc failure where stderr is the empty update banner
    # but stdout has the real error message (the DAG aborted at some task).
    def _failed_run(*_args: object, **_kwargs: object):
        return subprocess.CompletedProcess(
            args=["nextflow"],
            returncode=1,
            stdout=b"Pipeline execution aborted\nERROR ~ Process `INTERSECT_THINNED` terminated with rc=3\nWork dir: /work/abc/def\nTip: when invoked with -resume, you can use -dump-hashes\n",
            stderr=b"Nextflow 26.04.1 is available - Please consider updating your version to it\n",
        )

    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", side_effect=_failed_run):
        with pytest.raises(RuntimeError) as exc_info:
            compute_pgs(
                vcf=vcf,
                pgs_id="PGS000018",
                reference_root=reference_root,
                work_dir=work_dir,
                agent_choice_rationale="x" * 60,
                requested_for_question="why?",
            )

    msg = str(exc_info.value)
    # Stderr (current behaviour — keep it)
    assert "Nextflow 26.04.1 is available" in msg, (
        f"RuntimeError should include stderr; got: {msg}"
    )
    # NEW: stdout's contents must surface too.
    assert "INTERSECT_THINNED" in msg or "Pipeline execution aborted" in msg, (
        f"RuntimeError MUST include pgsc_calc stdout (which carries the real "
        f"DAG-abort error); the stderr banner is decorative. got: {msg}"
    )
    # Structural markers — make the message easy to read.
    assert "stderr" in msg.lower(), f"message should label the stderr section; got: {msg}"
    assert "stdout" in msg.lower(), f"message should label the stdout section; got: {msg}"


def test_compute_pgs_runs_nextflow_with_tmpdir_set_to_work_dir(tmp_path: Path) -> None:
    """``compute_pgs`` invokes nextflow with ``TMPDIR=<work_dir>`` in the
    subprocess env.

    Why this matters: Nextflow's per-task ``.command.run`` script creates
    ``NXF_SCRATCH="$(nxf_mktemp $TMPDIR)"`` BEFORE our ``beforeScript``
    fires. So if TMPDIR isn't set at the toolkit-container-process level
    when nextflow spawns, NXF_SCRATCH lands at ``/tmp/<random>`` (the
    toolkit container's writable layer, NOT bind-mounted to the host).
    DooD-spawned sibling containers identity-mount NXF_TASK_WORKDIR
    against the host and see an empty mount — INTERSECT_THINNED (and
    others) fail with "No such file or directory" on staged inputs.

    Smoke v22f (2026-05-21) surfaced this when ``process.scratch = false``
    in our nextflow.config turned out NOT to be honored by Nextflow's
    process template — the .command.run still set NXF_SCRATCH from
    TMPDIR. The env-var approach short-circuits the issue at the
    subprocess boundary: with TMPDIR=<work_dir> at the parent-process
    level, NXF_SCRATCH lands under <work_dir> (which IS bind-mounted
    + identity-mountable into siblings).
    """
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

    # subprocess.run was invoked with an `env` kwarg containing TMPDIR.
    assert fake_run.call_count == 1, fake_run.call_args_list
    call = fake_run.call_args_list[0]
    env = call.kwargs.get("env")
    assert env is not None, (
        f"compute_pgs MUST pass env= to subprocess.run so TMPDIR can be "
        f"set for the nextflow child; got call kwargs={list(call.kwargs)}"
    )
    assert env.get("TMPDIR") == str(work_dir), (
        f"TMPDIR in the nextflow subprocess env MUST equal the work_dir "
        f"so NXF_SCRATCH lands in a bind-mounted location; got TMPDIR="
        f"{env.get('TMPDIR')!r}, expected {str(work_dir)!r}"
    )


def test_compute_pgs_writes_nextflow_config_redirecting_tmpdir(tmp_path: Path) -> None:
    """The wrapper materialises a ``nextflow.config`` in the work_dir that
    redirects each sibling task's TMPDIR to its bind-mounted work-dir.

    Smoke v11 (2026-05-19) surfaced this as ``INTERSECT_VARIANTS`` failing
    with ``OSError: [Errno 28] No space left on device`` after Python's
    tempfile filled the colima VM data disk (the container writable layer).
    Redirecting TMPDIR to ``${PWD}`` (the sibling task's work-dir, which is
    bind-mounted from the host external scratch drive) keeps tempfiles off
    the VM data disk.

    Regression contract:
    1. ``work_dir/nextflow.config`` exists after ``compute_pgs``.
    2. Its content sets ``process.beforeScript`` to export TMPDIR=``${PWD}``.
    3. The argv passed to subprocess.run includes ``-c <config_path>``.
    """
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

    # 1. Config file materialised under work_dir.
    config_path = work_dir / "nextflow.config"
    assert config_path.exists(), f"nextflow.config must be written to work_dir; not found at {config_path}"

    # 2. Content sets process.beforeScript with TMPDIR redirect. The
    #    `${PWD}` MUST be in single-quoted groovy (so bash expands at task
    #    time, not groovy at config-load time).
    content = config_path.read_text()
    assert "process" in content, content
    assert "beforeScript" in content, content
    assert 'TMPDIR=' in content, content
    assert '${PWD}' in content, (
        f"TMPDIR redirect must use ${{PWD}} (bash-expanded at task time), "
        f"not a groovy-resolved value. content:\n{content}"
    )
    # Groovy single-quote (not double-quote) so ${PWD} reaches bash literal.
    assert "'export TMPDIR=" in content, (
        f"TMPDIR redirect must be in single-quoted groovy string. content:\n{content}"
    )
    # stageInMode = 'copy' — DooD-safe file staging. Default 'symlink'
    # creates parent-container-local symlinks that don't resolve in
    # sibling containers (Phase 7 smoke v14 surfaced this as
    # FILTER_VARIANTS failing on high-LD-regions-*.txt because the
    # symlink dereferenced to /opt/nextflow/... — invisible to siblings).
    assert "stageInMode = 'copy'" in content, (
        f"DooD-safe staging requires process.stageInMode = 'copy'; "
        f"got config:\n{content}"
    )

    # scratch = false — DooD-safe scratch placement. Default scratch=true
    # makes Nextflow create $NXF_SCRATCH under $TMPDIR. Our beforeScript
    # exports TMPDIR=${PWD}, but it fires AFTER NXF_SCRATCH is locked at
    # the toolkit container's /tmp (which is the container's writable
    # layer, NOT bind-mounted to the host). Files staged into $NXF_SCRATCH
    # then can't be seen by DooD-spawned sibling containers, which
    # identity-mount $NXF_TASK_WORKDIR against the host. Smoke v22c
    # (2026-05-21) surfaced this as INTERSECT_THINNED failing with "No
    # such file or directory" for files nxf_stage had nominally copied —
    # the cp commands succeeded inside /tmp/<random> but plink2 sibling
    # saw an empty mount. process.scratch = false makes tasks run
    # directly in their (bind-mounted) hash dir, closing the gap.
    assert "scratch = false" in content, (
        f"DooD-safe scratch placement requires process.scratch = false; "
        f"got config:\n{content}"
    )

    # 3. Argv passed to subprocess.run includes -c <config_path>.
    argv = fake_run.call_args_list[0].args[0]
    assert "-c" in argv, f"argv must include -c flag for config; got: {argv}"
    c_index = argv.index("-c")
    assert argv[c_index + 1] == str(config_path), (
        f"argv -c value must point at the materialised config; got: {argv[c_index + 1]}"
    )


# ---------------------------------------------------------------------------
# prs-non-imputed-wgs Phase 1 — INV-T001: argv consumes the conventions field
# ---------------------------------------------------------------------------


def test_invT001_pgsc_calc_argv_consumes_min_overlap_from_conventions(
    tmp_path: Path,
) -> None:
    """INV-T001: the wrapper emits ``--min_overlap <value>`` sourced from the
    conventions dataclass field, NOT from a hardcoded literal.

    Verified via ``dataclasses.replace`` — overriding the field on the
    dataclass and confirming the emitted argv carries the overridden value.
    A regression where the wrapper hardcoded ``"0.5"`` (or any literal)
    would let the conventions field drift from what's actually passed to
    pgsc_calc — defeating the typed-contract discipline.

    Mirrors the existing ``run_ancestry_value_pattern`` argv-consumption
    test pattern: pin the wrapper's behavior to the dataclass field, not
    to a literal.
    """
    import dataclasses as _dc

    from genomeclaw_toolkit.prep._paths import as_sibling_mountable
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep.pgs import _build_pgsc_calc_argv

    samplesheet = as_sibling_mountable(tmp_path / "samplesheet.csv")
    samplesheet.write_text("sampleset,path_prefix,chrom,format,vcf_genotype_field\n")
    work_dir = as_sibling_mountable(tmp_path / "work")
    work_dir.mkdir(exist_ok=True)
    reference_root = as_sibling_mountable(tmp_path / "ref")
    (reference_root / "pgs_catalog_ancestry" / "v1").mkdir(parents=True)

    # Stub the conventions field to a non-default value the wrapper would
    # NOT pick up if it was hardcoding the literal 0.5.
    stubbed_conv = _dc.replace(
        PgscCalcConventions(), min_overlap_default_for_non_imputed_wgs=0.42
    )

    argv = _build_pgsc_calc_argv(
        samplesheet=samplesheet,
        pgs_id="PGS000018",
        work_dir=work_dir,
        reference_root=reference_root,
        conventions=stubbed_conv,
    )

    # The argv MUST contain --min_overlap with the stubbed value.
    assert "--min_overlap" in argv, (
        f"--min_overlap MUST be emitted into the argv per prs-non-imputed-wgs "
        f"Phase 1 spec; got argv={argv}"
    )
    flag_idx = argv.index("--min_overlap")
    value = argv[flag_idx + 1]
    assert value == "0.42", (
        f"INV-T001: wrapper MUST consume conventions.min_overlap_default_for_"
        f"non_imputed_wgs (stubbed to 0.42 here), not a hardcoded literal; got "
        f"argv value={value!r} from argv={argv}"
    )


def test_pgsc_calc_argv_min_overlap_defaults_to_0_45_when_no_override(
    tmp_path: Path, monkeypatch
) -> None:
    """No env var, no conventions override → argv carries ``--min_overlap 0.45``.

    This is the canonical non-imputed single-sample WGS default. The
    research validation report (docs/reports/prs-real-data-smoke-research-
    findings.md) is the doctrinal source; smoke v22e (2026-05-21) measured
    PGS000018 at 49.51% empirical match rate, so the original 0.5 default
    rejected a healthy artifact. Any future contributor who wants to
    change this default must also update the report + the conventions
    docstring + this test in the same commit.
    """
    monkeypatch.delenv("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", raising=False)

    from genomeclaw_toolkit.prep._paths import as_sibling_mountable
    from genomeclaw_toolkit.prep.pgs import _build_pgsc_calc_argv

    samplesheet = as_sibling_mountable(tmp_path / "samplesheet.csv")
    samplesheet.write_text("sampleset,path_prefix,chrom,format,vcf_genotype_field\n")
    work_dir = as_sibling_mountable(tmp_path / "work")
    work_dir.mkdir(exist_ok=True)
    reference_root = as_sibling_mountable(tmp_path / "ref")
    (reference_root / "pgs_catalog_ancestry" / "v1").mkdir(parents=True)

    argv = _build_pgsc_calc_argv(
        samplesheet=samplesheet,
        pgs_id="PGS000018",
        work_dir=work_dir,
        reference_root=reference_root,
    )

    assert "--min_overlap" in argv, f"--min_overlap missing; argv={argv}"
    flag_idx = argv.index("--min_overlap")
    assert argv[flag_idx + 1] == "0.45", (
        f"non-imputed single-sample WGS default MUST be 0.45; got {argv[flag_idx + 1]!r}"
    )



# ---------------------------------------------------------------------------
# v23 regression — parsers must find the actual pgsc_calc v2.2.0 output layout
# ---------------------------------------------------------------------------


def test_parse_pgsc_calc_outputs_finds_norm_pgs_in_nextflow_hash_dirs(tmp_path: Path) -> None:
    """pgsc_calc v2.2.0 emits per-task outputs under ``<work_dir>/<2-char-hash>/<long-hash>/``
    NOT under the legacy ``<work_dir>/score/`` + ``<work_dir>/ancestry/`` publish-dir
    layout the wrapper was originally written against. Smoke v23 (2026-05-22)
    showed the wrapper returning ``percentile=None`` because the parser couldn't
    find the file at the expected legacy path.

    Two files matter:
    - ``aggregated_scores.txt.gz`` (gzipped TSV) — has SUM/DENOM/AVG
    - ``norm_pgs.txt.gz`` (gzipped TSV) — has PGS/Z_MostSimilarPop/percentile_MostSimilarPop

    The ``PGS`` column carries the full accession with suffix (e.g.
    ``PGS000018_hmPOS_GRCh38``), so prefix-match against the bare ID.

    Wrapper must recursively search the work_dir tree for these files and
    gunzip them.
    """
    import gzip

    from genomeclaw_toolkit.prep.pgs import (
        _parse_aggregated_scores,
        _parse_aggregated_scores_norm,
    )

    work_dir = tmp_path / "work"
    # Mirror v23's actual layout: per-task hash dirs at depth 2.
    task_e7 = work_dir / "e7" / "1a379cfeee5074e0a71a9c4b8506f0"
    task_e7.mkdir(parents=True)
    task_0b = work_dir / "0b" / "9e015e5e97ca81a20327b8c85ba24b"
    task_0b.mkdir(parents=True)

    # aggregated_scores.txt.gz: SUM=9.665, DENOM=1728050, AVG=5.59e-06 — v23 numbers.
    with gzip.open(task_e7 / "aggregated_scores.txt.gz", "wt") as fh:
        fh.write("sampleset\tFID\tIID\tPGS\tSUM\tDENOM\tAVG\n")
        fh.write(
            "norm\tMPNRGLQ2K\tMPNRGLQ2K\tPGS000018_hmPOS_GRCh38\t"
            "9.66498\t1728050.0\t5.59e-06\n"
        )

    # norm_pgs.txt.gz: percentile_MostSimilarPop=14.54 — the v23 calibrated number.
    with gzip.open(task_0b / "norm_pgs.txt.gz", "wt") as fh:
        fh.write(
            "sampleset\tFID\tIID\tPGS\tSUM\t"
            "Z_MostSimilarPop\tZ_norm1\tZ_norm2\tpercentile_MostSimilarPop\n"
        )
        fh.write(
            "norm\tMPNRGLQ2K\tMPNRGLQ2K\tPGS000018_hmPOS_GRCh38\t"
            "9.66498\t-1.0449871\t-1.366664\t-1.123757\t14.5427\n"
        )

    raw_score, study_pop = _parse_aggregated_scores(work_dir, "PGS000018")
    assert raw_score is not None, (
        f"expected non-None raw_score parsed from nested aggregated_scores.txt.gz; "
        f"got None"
    )
    # AVG is what _parse_aggregated_scores returns as raw_score (per docstring).
    assert raw_score == pytest.approx(5.59e-06)

    percentile, warning = _parse_aggregated_scores_norm(work_dir, "PGS000018")
    assert percentile is not None, (
        "expected non-None percentile parsed from nested norm_pgs.txt.gz; got None"
    )
    assert percentile == pytest.approx(14.5427)
    assert warning is None  # no calibration_warning column in norm_pgs.txt.gz schema

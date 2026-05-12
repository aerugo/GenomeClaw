"""CLI coverage for the ``pipeline`` subcommand group.

``genomeclaw pipeline run`` chains ``ingest`` → ``normalize`` →
``annotate`` → ``materialize`` against a single run dir. The underlying
``*_impl`` callables are stubbed so these tests lock the orchestration
shape (call order, run-dir threading, arg propagation, failure
handling) without retesting each phase.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _stage_sample(raw_root: Path, sample_id: str, *files: str) -> Path:
    sample_dir = raw_root / sample_id
    sample_dir.mkdir(parents=True)
    for name in files:
        (sample_dir / name).write_bytes(b"")
    return sample_dir


def _stub_all(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Stub every ``pipeline.*_impl`` the pipeline calls; return per-phase call logs."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    calls: dict[str, list[dict]] = {
        "ingest": [],
        "normalize": [],
        "annotate": [],
        "materialize": [],
    }

    def fake_ingest(**kwargs):
        calls["ingest"].append(kwargs)
        return Path("/fake/derived/run-id")

    def fake_normalize(**kwargs):
        calls["normalize"].append(kwargs)
        return Path("/fake/derived/run-id/normalized.vcf.gz")

    def fake_annotate(**kwargs):
        calls["annotate"].append(kwargs)
        return Path("/fake/derived/run-id/annotated.vcf.gz")

    def fake_materialize(**kwargs):
        calls["materialize"].append(kwargs)
        return Path("/fake/derived/run-id/variants.duckdb")

    monkeypatch.setattr(pipeline_cmd, "ingest_impl", fake_ingest)
    monkeypatch.setattr(pipeline_cmd, "normalize_impl", fake_normalize)
    monkeypatch.setattr(pipeline_cmd, "annotate_impl", fake_annotate)
    monkeypatch.setattr(pipeline_cmd, "materialize_impl", fake_materialize)
    return calls


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_pipeline_run_no_flags_autodetects_and_chains_all_four_phases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``pipeline run`` with no flags → full autodetect + all four phases in order."""
    raw = tmp_path / "raw"
    raw.mkdir()
    sample_dir = _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls = _stub_all(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls["ingest"]) == 1
    assert len(calls["normalize"]) == 1
    assert len(calls["annotate"]) == 1
    assert len(calls["materialize"]) == 1

    # Ingest got the autodetected inputs.
    assert calls["ingest"][0]["sample_id"] == "MPNRGLQ2K"
    assert calls["ingest"][0]["vcf"] == sample_dir / "MPNRGLQ2K.hc.vcf.gz"
    assert calls["ingest"][0]["reference_dir"] == reference_root / "grch38"
    assert calls["ingest"][0]["bam"] is None  # VCF-only by default

    # Downstream phases run on the run-dir ingest returned.
    fake_run_dir = Path("/fake/derived/run-id")
    assert calls["normalize"][0]["run_dir"] == fake_run_dir
    assert calls["annotate"][0]["run_dir"] == fake_run_dir
    assert calls["materialize"][0]["run_dir"] == fake_run_dir

    # Annotate received the reference *root* (not the autodetected build dir).
    assert calls["annotate"][0]["reference_dir"] == reference_root


def test_pipeline_run_threads_explicit_bam_and_bed_through_to_ingest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """Explicit ``--bam`` + ``--bed`` are propagated to ``ingest_impl``."""
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()
    bam = tmp_path / "S1.cram"
    bam.write_bytes(b"")
    bed = tmp_path / "genes.bed"
    bed.write_bytes(b"")

    calls = _stub_all(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--bam",
            str(bam),
            "--bed",
            str(bed),
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls["ingest"][0]["bam"] == bam
    assert calls["ingest"][0]["bed"] == bed


def test_pipeline_run_propagates_clinvar_release_to_annotate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--clinvar-release`` flows into the annotate orchestrator."""
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls = _stub_all(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--clinvar-release",
            "2026-05-09",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls["annotate"][0]["clinvar_release"] == "2026-05-09"


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_pipeline_run_aborts_on_ingest_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """An ingest ``FileNotFoundError`` raises a precondition error; later phases never run."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls = _stub_all(monkeypatch)

    def boom_ingest(**kwargs):
        raise FileNotFoundError("synthetic ingest failure")

    monkeypatch.setattr(pipeline_cmd, "ingest_impl", boom_ingest)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    # FileNotFoundError → PreconditionError → exit code 3.
    assert result.exit_code == 3, result.stderr
    assert calls["normalize"] == []
    assert calls["annotate"] == []
    assert calls["materialize"] == []
    assert "ingest failed" in result.stderr


def test_pipeline_run_aborts_on_normalize_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """A normalize failure aborts the pipeline; annotate + materialize don't run."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls = _stub_all(monkeypatch)

    def boom_normalize(**kwargs):
        raise FileNotFoundError("synthetic normalize failure")

    monkeypatch.setattr(pipeline_cmd, "normalize_impl", boom_normalize)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    # FileNotFoundError mid-pipeline → RuntimeFailure → exit code 1.
    assert result.exit_code == 1, result.stderr
    assert len(calls["ingest"]) == 1
    assert calls["annotate"] == []
    assert calls["materialize"] == []
    assert "normalize failed" in result.stderr

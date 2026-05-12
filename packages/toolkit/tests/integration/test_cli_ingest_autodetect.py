"""CLI coverage for the ``pipeline ingest`` autodetect modes.

Two surfaces:

- :func:`genomeclaw_toolkit.prep.ingest.autodetect_sample_inputs` —
  pure helper that walks ``raw/`` and returns ``(sample_id, vcf_path)``
  when exactly one sample directory with exactly one bgzipped VCF is
  staged. Direct error-shape tests live here.
- ``genomeclaw pipeline ingest`` — the CLI surface that threads the
  helper's output into ``ingest_impl``. ``ingest_impl`` is stubbed so
  these tests never touch the real Phase-2 orchestrator.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _stage_sample(raw_root: Path, sample_id: str, *files: str) -> Path:
    """Create ``raw_root/<sample_id>/`` and touch each named file inside it."""
    sample_dir = raw_root / sample_id
    sample_dir.mkdir(parents=True)
    for name in files:
        (sample_dir / name).write_bytes(b"")
    return sample_dir


# ---------------------------------------------------------------------------
# autodetect_sample_inputs — pure helper
# ---------------------------------------------------------------------------


def test_autodetect_returns_sample_and_vcf_when_single_sample_dir(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    raw = tmp_path / "raw"
    raw.mkdir()
    sample_dir = _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz", "MPNRGLQ2K.hc.vcf.gz.tbi")

    sample_id, vcf = autodetect_sample_inputs(raw)

    assert sample_id == "MPNRGLQ2K"
    assert vcf == sample_dir / "MPNRGLQ2K.hc.vcf.gz"


def test_autodetect_accepts_vcf_bgz_suffix(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    raw = tmp_path / "raw"
    raw.mkdir()
    sample_dir = _stage_sample(raw, "S1", "S1.vcf.bgz", "S1.vcf.bgz.tbi")

    sample_id, vcf = autodetect_sample_inputs(raw)

    assert sample_id == "S1"
    assert vcf == sample_dir / "S1.vcf.bgz"


def test_autodetect_refuses_when_raw_root_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    with pytest.raises(ValueError, match="raw root not found"):
        autodetect_sample_inputs(tmp_path / "nope")


def test_autodetect_refuses_when_no_sample_dirs(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    raw = tmp_path / "raw"
    raw.mkdir()

    with pytest.raises(ValueError, match="no sample subdirectories"):
        autodetect_sample_inputs(raw)


def test_autodetect_refuses_when_multiple_sample_dirs(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.vcf.gz")
    _stage_sample(raw, "S2", "S2.vcf.gz")

    with pytest.raises(ValueError, match="multiple sample subdirectories"):
        autodetect_sample_inputs(raw)


def test_autodetect_refuses_when_no_vcf_in_sample_dir(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.cram", "S1.cram.crai")

    with pytest.raises(ValueError, match="no .vcf.gz"):
        autodetect_sample_inputs(raw)


def test_autodetect_refuses_when_multiple_vcfs_in_sample_dir(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs

    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "first.vcf.gz", "second.vcf.gz")

    with pytest.raises(ValueError, match="multiple bgzipped VCFs"):
        autodetect_sample_inputs(raw)


# ---------------------------------------------------------------------------
# ``genomeclaw pipeline ingest`` — CLI dispatch
# ---------------------------------------------------------------------------


def _stub_ingest(monkeypatch: pytest.MonkeyPatch, calls: list[dict]) -> None:
    """Replace ``pipeline.ingest_impl`` with a recorder that returns a fake run dir."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    def fake_ingest(**kwargs):
        calls.append(kwargs)
        return Path("/fake/derived/run-id")

    monkeypatch.setattr(pipeline_cmd, "ingest_impl", fake_ingest)


def test_cli_no_flags_autodetects_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``pipeline ingest`` (no flags) → full autodetect path."""
    raw = tmp_path / "raw"
    raw.mkdir()
    sample_dir = _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls: list[dict] = []
    _stub_ingest(monkeypatch, calls)

    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["sample_id"] == "MPNRGLQ2K"
    assert calls[0]["vcf"] == sample_dir / "MPNRGLQ2K.hc.vcf.gz"
    assert calls[0]["reference_dir"] == reference_root / "grch38"


def test_cli_explicit_vcf_path_with_sample_id_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """The original ``--vcf <path> --sample-id <id>`` shape still works."""
    fake_vcf = tmp_path / "fake.vcf.gz"
    fake_vcf.write_bytes(b"")
    reference = tmp_path / "reference"
    reference.mkdir()

    calls: list[dict] = []
    _stub_ingest(monkeypatch, calls)

    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--vcf",
            str(fake_vcf),
            "--reference",
            str(reference),
            "--sample-id",
            "MPNRGLQ2K",
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["vcf"] == fake_vcf
    assert calls[0]["sample_id"] == "MPNRGLQ2K"


def test_cli_propagates_autodetect_error_with_precondition_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """When autodetect raises, the CLI surfaces a clear error and exits 3 (precondition)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.vcf.gz")
    _stage_sample(raw, "S2", "S2.vcf.gz")
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    reference.mkdir()
    derived.mkdir()

    calls: list[dict] = []
    _stub_ingest(monkeypatch, calls)

    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--reference",
            str(reference),
            "--raw-root",
            str(raw),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 3, result.stderr
    assert calls == []
    assert "multiple sample subdirectories" in result.stderr


def test_cli_explicit_vcf_path_still_requires_sample_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--vcf <path>`` without ``--sample-id`` is a usage error (exit 2)."""
    fake_vcf = tmp_path / "fake.vcf.gz"
    fake_vcf.write_bytes(b"")
    reference = tmp_path / "reference"
    reference.mkdir()

    calls: list[dict] = []
    _stub_ingest(monkeypatch, calls)

    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--vcf",
            str(fake_vcf),
            "--reference",
            str(reference),
        ]
    )

    assert result.exit_code == 2
    assert calls == []
    assert "--sample-id is required" in result.stderr


def test_cli_omitted_reference_autodetects_build_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--reference`` omitted entirely → autodetect."""
    reference_root = tmp_path / "reference"
    (reference_root / "grch38" / "ncbi-2014").mkdir(parents=True)
    fake_vcf = tmp_path / "fake.vcf.gz"
    fake_vcf.write_bytes(b"")
    derived = tmp_path / "derived"
    derived.mkdir()

    calls: list[dict] = []
    _stub_ingest(monkeypatch, calls)

    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--vcf",
            str(fake_vcf),
            "--sample-id",
            "S1",
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["reference_dir"] == reference_root / "grch38"


def test_cli_reference_autodetect_propagates_error_with_precondition_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """No build subdir under ``--reference-root`` → exit 3 (precondition)."""
    reference_root = tmp_path / "reference"
    (reference_root / "clinvar").mkdir(parents=True)
    fake_vcf = tmp_path / "fake.vcf.gz"
    fake_vcf.write_bytes(b"")

    calls: list[dict] = []
    _stub_ingest(monkeypatch, calls)

    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--vcf",
            str(fake_vcf),
            "--sample-id",
            "S1",
            "--reference-root",
            str(reference_root),
        ]
    )

    assert result.exit_code == 3
    assert calls == []
    assert "no build subdirectories" in result.stderr

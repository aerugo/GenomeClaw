"""Phase 6 Slice D — ``prep/cyrius.py`` wrapper unit tests.

Cyrius wraps Illumina's CYP2D6 star-allele caller. Tests mock
``subprocess.run`` so they run on any host without Cyrius installed;
the real-data smoke against the project owner's CRAM is gated as a
manual ``needs_bio`` step, run after the Dockerfile is updated to
include ``bioconda::cyrius``.

Slice plan: [phases/phase-6-slice-d.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d.md)
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _fake_cyrius_json(sample_id: str, diplotype: str = "*1/*4", filt: str = "PASS") -> dict:
    """Synthetic Cyrius v1.1.1 output JSON for the manifest-wide envelope."""
    return {
        sample_id: {
            "Genotype": [diplotype],
            "Filter": [filt],
            "Raw_call": f"{diplotype} (raw)",
        }
    }


def _stub_subprocess_run_factory(run_dir: Path, sample_id: str, *, rc: int = 0):
    """Build a ``subprocess.run`` stub that writes a synthetic Cyrius JSON.

    The real Cyrius invocation writes ``<outDir>/<prefix>.json``; the stub
    materialises a one-sample envelope at the same path so the wrapper's
    post-parse step has something real to read.
    """
    output_path = run_dir / "cyp2d6.json"

    def _stub(argv, **kwargs):  # noqa: ANN001 — mirrors subprocess.run signature
        if rc == 0:
            output_path.write_text(json.dumps(_fake_cyrius_json(sample_id)))
        completed = subprocess.CompletedProcess(
            args=argv,
            returncode=rc,
            stdout=b"",
            stderr=b"" if rc == 0 else b"cyrius failed: synthetic error",
        )
        return completed

    return _stub


def test_call_cyp2d6_argv_uses_conventions(tmp_path: Path) -> None:
    """Wrapper consumes ``CyriusConventions`` fields rather than hardcoded literals."""
    from genomeclaw_toolkit.prep._cyrius_conventions import CyriusConventions
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    custom_conv = dataclasses.replace(
        CyriusConventions(), manifest_flag="--alt-manifest", genome_flag="--alt-genome"
    )
    captured: dict = {}

    def _capture(argv, **kwargs):  # noqa: ANN001
        captured["argv"] = list(argv)
        (run_dir / "cyp2d6.json").write_text(json.dumps(_fake_cyrius_json("sample")))
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    with patch.object(subprocess, "run", side_effect=_capture):
        call_cyp2d6(
            bam=bam,
            genome_build="GRCh38",
            run_dir=run_dir,
            sample_id="sample",
            conventions=custom_conv,
        )

    assert "--alt-manifest" in captured["argv"]
    assert "--alt-genome" in captured["argv"]
    # The literal --manifest / --genome flags must NOT appear when the
    # conventions override them — defense against the wrapper hardcoding
    # them in parallel to the dataclass read.
    assert "--manifest" not in captured["argv"]
    assert "--genome" not in captured["argv"]


def test_call_cyp2d6_writes_diplotype_json(tmp_path: Path) -> None:
    """Successful call writes ``<run_dir>/cyp2d6_diplotype.json`` with the wrapper envelope."""
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(subprocess, "run", side_effect=_stub_subprocess_run_factory(run_dir, "sample")):
        call_cyp2d6(bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample")

    envelope_path = run_dir / "cyp2d6_diplotype.json"
    assert envelope_path.exists(), "wrapper did not write the diplotype envelope"
    envelope = json.loads(envelope_path.read_text())
    assert envelope["sample_id"] == "sample"
    assert envelope["diplotype"] == "*1/*4"
    assert envelope["filter_status"] == "PASS"


def test_call_cyp2d6_successful_call_stamps_cyp2d6_status_called(tmp_path: Path) -> None:
    """Successful diplotype envelopes carry `cyp2d6_status='called'`.

    Pairs with the no-call sentinel's `cyp2d6_status='no_call'` so
    downstream consumers (the CLI handler, the PharmCAT skip-detect, the
    `findings` table inspector) can distinguish the two states from a
    single field rather than inferring from file presence.

    Added by cyp2d6-no-call-finding Phase 1; regression guard for the
    success path.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(
        subprocess, "run", side_effect=_stub_subprocess_run_factory(run_dir, "sample")
    ):
        row = call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
        )

    assert row is not None, "successful call must return a CyriusDiplotypeRow, not None"
    envelope = json.loads((run_dir / "cyp2d6_diplotype.json").read_text())
    assert envelope["cyp2d6_status"] == "called", (
        f"successful diplotype envelope must carry cyp2d6_status='called'; "
        f"got envelope={envelope!r}"
    )


def test_call_cyp2d6_parses_genotype_from_cyrius_json(tmp_path: Path) -> None:
    """The wrapper returns a typed ``CyriusDiplotypeRow`` with the parsed values."""
    from genomeclaw_toolkit.prep.cyrius import CyriusDiplotypeRow, call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(
        subprocess, "run",
        side_effect=_stub_subprocess_run_factory(run_dir, "MPNRGLQ2K"),
    ):
        row = call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="MPNRGLQ2K"
        )

    assert isinstance(row, CyriusDiplotypeRow)
    assert row.sample_id == "MPNRGLQ2K"
    assert row.diplotype == "*1/*4"
    assert row.filter_status == "PASS"


def test_call_cyp2d6_parses_string_form_genotype_and_filter(tmp_path: Path) -> None:
    """Cyrius v1.1.1 emits ``Genotype`` and ``Filter`` as STRINGS (not lists).

    Empirical 2026-05-22 smoke regression: the wrapper initially treated
    them as lists per the README's older shape (``genotype_list[0]``);
    against the real CRAM that produced ``"*"`` (first char of ``"*1/*35"``)
    + ``"P"`` (first char of ``"PASS"``). The parser now accepts both
    string and list forms.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    def _runner(argv, **kwargs):  # noqa: ANN001
        # Real Cyrius v1.1.1 output shape: Genotype + Filter as strings.
        (run_dir / "cyp2d6.json").write_text(
            json.dumps({"sample": {"Genotype": "*1/*35", "Filter": "PASS"}})
        )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    with patch.object(subprocess, "run", side_effect=_runner):
        row = call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
        )

    assert row.diplotype == "*1/*35"
    assert row.filter_status == "PASS"


def test_call_cyp2d6_parses_bam_stem_keyed_output(tmp_path: Path) -> None:
    """Cyrius v1.1.1 keys output by BAM stem (not sample_id). Single-BAM
    mode picks the lone entry regardless of key.

    Empirical 2026-05-22 smoke regression: a real CRAM at
    ``MPNRGLQ2K.mm2.sortdup.bqsr.cram`` produced output keyed by
    ``MPNRGLQ2K.mm2.sortdup.bqsr``, not the wrapper-supplied
    ``sample_id=MPNRGLQ2K``. The sample_id is the wrapper's *audit*
    identity (envelope field); Cyrius's internal key is the BAM stem.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "MPNRGLQ2K.mm2.sortdup.bqsr.bam"
    bam.write_bytes(b"fake bam")

    def _runner(argv, **kwargs):  # noqa: ANN001
        # Cyrius keys output by BAM stem — NOT by sample_id.
        (run_dir / "cyp2d6.json").write_text(
            json.dumps(
                {"MPNRGLQ2K.mm2.sortdup.bqsr": {"Genotype": ["*1/*4"], "Filter": ["PASS"]}}
            )
        )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    with patch.object(subprocess, "run", side_effect=_runner):
        row = call_cyp2d6(
            bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="MPNRGLQ2K"
        )

    assert row.diplotype == "*1/*4"
    assert row.filter_status == "PASS"
    # The sample_id field carries the wrapper's audit identity, not
    # Cyrius's internal key.
    assert row.sample_id == "MPNRGLQ2K"


def test_call_cyp2d6_raises_on_nonzero_rc(tmp_path: Path) -> None:
    """Non-zero ``subprocess.run`` rc surfaces a RuntimeError carrying stderr."""
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(
        subprocess, "run",
        side_effect=_stub_subprocess_run_factory(run_dir, "sample", rc=2),
    ):
        with pytest.raises(RuntimeError) as excinfo:
            call_cyp2d6(bam=bam, genome_build="GRCh38", run_dir=run_dir, sample_id="sample")

    assert "cyrius failed" in str(excinfo.value).lower()
    assert "rc=2" in str(excinfo.value)


def test_call_cyp2d6_rejects_cram_without_reference_fasta(tmp_path: Path) -> None:
    """CRAM input without ``reference_fasta`` raises before subprocess.run.

    Cyrius's pysam handle needs the reference to decompress CRAM blocks;
    the wrapper surfaces this as a typed pre-flight ValueError rather
    than letting Cyrius fail mid-run with a pysam decode error. The
    --reference flag was surfaced as an empirical probe finding 2026-05-22.
    """
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cram = tmp_path / "sample.cram"
    cram.write_bytes(b"fake cram")

    with patch.object(subprocess, "run") as mock_run:
        with pytest.raises(ValueError) as excinfo:
            call_cyp2d6(
                bam=cram, genome_build="GRCh38", run_dir=run_dir, sample_id="sample"
            )

    assert "CRAM" in str(excinfo.value)
    assert "reference_fasta" in str(excinfo.value)
    mock_run.assert_not_called()


def test_call_cyp2d6_threads_reference_fasta_through_argv(tmp_path: Path) -> None:
    """When ``reference_fasta`` is set, the wrapper emits ``--reference <path>``."""
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cram = tmp_path / "sample.cram"
    cram.write_bytes(b"fake cram")
    ref = tmp_path / "ref.fa"
    ref.write_bytes(b"fake fasta")

    captured: dict = {}

    def _capture(argv, **kwargs):  # noqa: ANN001
        captured["argv"] = list(argv)
        (run_dir / "cyp2d6.json").write_text(json.dumps(_fake_cyrius_json("sample")))
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    with patch.object(subprocess, "run", side_effect=_capture):
        call_cyp2d6(
            bam=cram,
            genome_build="GRCh38",
            run_dir=run_dir,
            sample_id="sample",
            reference_fasta=ref,
        )

    assert "--reference" in captured["argv"]
    ref_idx = captured["argv"].index("--reference")
    assert captured["argv"][ref_idx + 1] == str(ref)


def test_call_cyp2d6_rejects_non_38_genome_build(tmp_path: Path) -> None:
    """The wrapper ships GRCh38 only; passing GRCh37 raises pre-subprocess."""
    from genomeclaw_toolkit.prep.cyrius import call_cyp2d6

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam")

    with patch.object(subprocess, "run") as mock_run:
        with pytest.raises(ValueError) as excinfo:
            call_cyp2d6(bam=bam, genome_build="GRCh37", run_dir=run_dir, sample_id="sample")

    assert "GRCh37" in str(excinfo.value)
    assert "GRCh38" in str(excinfo.value)
    # Pre-flight rejection — subprocess.run was never invoked.
    mock_run.assert_not_called()

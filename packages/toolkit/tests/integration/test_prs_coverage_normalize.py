"""prs-non-imputed-wgs Phase 2 — ``_normalize_for_pgsc_calc`` wrapper +
orchestrator wiring.

Inserts a ``bcftools norm -m -any -f <fasta>`` step between
``_merge_tier1_tier2`` and ``compute_pgs`` so multi-allelic records are
decomposed into single-ALT rows before pgsc_calc's score-matching step
sees them. Recovers the ~10% multi-allelic / complex-record share of the
structural missingness on non-imputed single-sample WGS (per
[docs/reports/prs-real-data-smoke-research-findings.md](../../../../../docs/reports/prs-real-data-smoke-research-findings.md)).

Contract assertions:

1. The wrapper's argv carries ``bcftools norm -m -any -f <fasta>`` plus
   bgzipped output + tabix index step (regression guard against accidental
   flag removal).
2. INV-R002: if bcftools exits cleanly but emits a header-only VCF, the
   helper raises ``BcftoolsError`` with the canonical multi-cause
   diagnostic + cleans up the empty file (no leaked partial state).
3. bcftools rc != 0 surfaces as ``BcftoolsError`` carrying the stderr
   (typed error beats a deep Nextflow log later).
4. ``compute_prs_with_coverage_fill`` wires the normalize step between
   the merge + ``compute_pgs`` calls so pgsc_calc receives the normalized
   VCF path, not the raw merged path.
"""

from __future__ import annotations

import gzip
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_normalize_for_pgsc_calc_runs_bcftools_norm_with_correct_args(
    tmp_path: Path,
) -> None:
    """Argv shape: ``bcftools norm -m -any -f <fasta> --output-type z
    --output <output_vcf> <input_vcf>`` + a tabix-index step. The
    ``-m -any`` flags are load-bearing — they're what decomposes multi-
    allelics. A regression that drops them would silently fail to recover
    the ~10% multi-allelic share."""
    from genomeclaw_toolkit.prep.coverage_fill import _normalize_for_pgsc_calc

    input_vcf = tmp_path / "merged.vcf.gz"
    fasta = tmp_path / "ref.fa"
    output_vcf = tmp_path / "merged.norm.vcf.gz"
    input_vcf.write_bytes(b"\x1f\x8b")
    fasta.write_text("dummy fasta")

    captured_cmds: list[list[str]] = []

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_list = list(cmd)
        captured_cmds.append(cmd_list)
        cmd_str = " ".join(str(x) for x in cmd_list)
        # Materialise a one-record output VCF so the INV-R002 guard
        # downstream is satisfied (the guard fires on 0-record outputs).
        match = re.search(r"--output\s+(\S+)", cmd_str)
        if match:
            out_path = Path(match.group(1))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(out_path, "wt") as fh:
                fh.write("##fileformat=VCFv4.2\n")
                fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
                fh.write("chr1\t100\t.\tA\tG\t.\t.\t.\n")
        return subprocess.CompletedProcess(args=cmd_list, returncode=0, stdout=b"", stderr=b"")

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        _normalize_for_pgsc_calc(
            input_vcf=input_vcf,
            fasta=fasta,
            output_vcf=output_vcf,
        )

    assert len(captured_cmds) == 1, captured_cmds
    cmd = captured_cmds[0]
    cmd_str = " ".join(str(x) for x in cmd)

    # Core decomposition flags — the regression guard. ``-m -any`` is what
    # decomposes multi-allelics into single-ALT rows.
    assert "bcftools norm" in cmd_str, f"missing 'bcftools norm'; got: {cmd_str}"
    assert "-m -any" in cmd_str or ("-m" in cmd and "-any" in cmd), (
        f"missing '-m -any' flags (the load-bearing decomposition flags); got: {cmd_str}"
    )

    # Fasta reference must be passed via -f for the normalization to be
    # build-aware (bcftools needs the fasta to verify REF alleles).
    assert f"-f {fasta}" in cmd_str, f"missing '-f <fasta>'; got: {cmd_str}"

    # Output must be bgzipped (--output-type z) + tabix-indexed.
    assert "--output-type z" in cmd_str, f"missing '--output-type z'; got: {cmd_str}"
    assert f"--output {output_vcf}" in cmd_str, (
        f"missing '--output {output_vcf}'; got: {cmd_str}"
    )
    assert "bcftools index" in cmd_str, (
        f"missing tabix-index step; got: {cmd_str}"
    )
    assert "--tbi" in cmd_str, f"missing --tbi flag for tabix index; got: {cmd_str}"


def test_normalize_for_pgsc_calc_refuses_to_promote_empty_output_invR002(
    tmp_path: Path,
) -> None:
    """INV-R002: a 0-record output VCF must raise ``BcftoolsError`` +
    NOT leave the empty file on disk. Mirrors the ``_force_genotype_tier1/2``
    guard pattern — the canonical surfacing for the silent-degenerate-cache
    failure mode."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        BcftoolsError,
        _normalize_for_pgsc_calc,
    )

    input_vcf = tmp_path / "merged.vcf.gz"
    fasta = tmp_path / "ref.fa"
    output_vcf = tmp_path / "merged.norm.vcf.gz"
    input_vcf.write_bytes(b"\x1f\x8b")
    fasta.write_text("dummy")

    def _empty_runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        match = re.search(r"--output\s+(\S+)", cmd_str)
        if match:
            out_path = Path(match.group(1))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(out_path, "wt") as fh:
                fh.write("##fileformat=VCFv4.2\n")
                fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_empty_runner),
    ):
        with pytest.raises(BcftoolsError) as exc_info:
            _normalize_for_pgsc_calc(
                input_vcf=input_vcf,
                fasta=fasta,
                output_vcf=output_vcf,
            )

    msg = str(exc_info.value)
    assert "ZERO output records" in msg, msg
    assert "NOT caching" in msg, msg
    # Diagnostic should reference at least one plausible cause so the
    # debugger isn't flying blind.
    assert "empty" in msg.lower() or "build mismatch" in msg.lower(), msg

    # The empty output VCF must NOT be left on disk; downstream consumers
    # would otherwise see a half-baked artifact.
    assert not output_vcf.exists(), (
        f"empty normalized VCF must be cleaned up; found at {output_vcf}"
    )
    # The tabix sidecar (if any) is also cleaned up.
    assert not Path(f"{output_vcf}.tbi").exists(), (
        f"orphan .tbi sidecar must be cleaned up; found at {output_vcf}.tbi"
    )


def test_normalize_for_pgsc_calc_raises_on_nonzero_rc(tmp_path: Path) -> None:
    """``bcftools norm`` rc != 0 surfaces as ``BcftoolsError`` carrying the
    captured stderr — a typed error beats a deep Nextflow log later."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        BcftoolsError,
        _normalize_for_pgsc_calc,
    )

    input_vcf = tmp_path / "merged.vcf.gz"
    fasta = tmp_path / "ref.fa"
    output_vcf = tmp_path / "merged.norm.vcf.gz"
    input_vcf.write_bytes(b"\x1f\x8b")
    fasta.write_text("dummy")

    def _failed_runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout=b"",
            stderr=b"E::norm: REF allele mismatch at chr1:100 (vcf=A vs fasta=G)\n",
        )

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_failed_runner),
    ):
        with pytest.raises(BcftoolsError) as exc_info:
            _normalize_for_pgsc_calc(
                input_vcf=input_vcf,
                fasta=fasta,
                output_vcf=output_vcf,
            )

    msg = str(exc_info.value)
    assert "rc=1" in msg, msg
    assert "REF allele mismatch" in msg, (
        f"BcftoolsError must include bcftools stderr for downstream debugging; got: {msg}"
    )


def test_compute_prs_with_coverage_fill_normalizes_before_compute_pgs(
    tmp_path: Path,
) -> None:
    """The orchestrator wires ``_normalize_for_pgsc_calc`` between the
    ``_merge_tier1_tier2`` call and ``compute_pgs`` so pgsc_calc receives
    the normalized VCF (multi-allelics decomposed), NOT the raw merged
    VCF.

    The assertion: ``compute_pgs(vcf=...)`` receives the path produced by
    ``_normalize_for_pgsc_calc(output_vcf=...)``, not by
    ``_merge_tier1_tier2(output_vcf=...)``. A regression that bypasses
    the normalize step would let pgsc_calc see multi-allelic records
    again, dropping the recovered ~10% match-rate share.
    """
    from genomeclaw_toolkit.prep.coverage_fill import (
        as_sibling_mountable,
        compute_prs_with_coverage_fill,
    )
    from genomeclaw_toolkit.prep.pgs import PgsRow

    # Synthesise the minimum-viable orchestrator fixture.
    cram = tmp_path / "user.cram"
    cram.write_bytes(b"x")
    sites = tmp_path / "sites.tsv"
    sites.write_text("")
    alleles = tmp_path / "alleles.tsv"
    alleles.write_text("")
    scorefile = tmp_path / "PGS000018.txt.gz"
    scorefile.write_bytes(b"\x1f\x8b")
    fasta = tmp_path / "ref.fa"
    fasta.write_text("")
    reference_root = tmp_path / "ref"
    output_root = tmp_path / "derived"
    work_dir = tmp_path / "work"
    reference_root.mkdir()
    output_root.mkdir()
    work_dir.mkdir()
    (reference_root / "pgs_catalog_ancestry" / "v1").mkdir(parents=True)
    (reference_root / "pgs_catalog_ancestry" / "v1" / "pgs_catalog_ancestry.tar.zst").write_bytes(
        b"x"
    )

    tier1_path = tmp_path / "tier1.vcf.gz"
    tier1_path.write_bytes(b"\x1f\x8b")
    tier2_path = tmp_path / "tier2.vcf.gz"
    tier2_path.write_bytes(b"\x1f\x8b")

    def _fake_tier1(**_kwargs):
        return tier1_path

    def _fake_tier2(**_kwargs):
        return tier2_path

    def _fake_merge(**kwargs):
        merged = kwargs["output_vcf"]
        merged.parent.mkdir(parents=True, exist_ok=True)
        merged.write_bytes(b"\x1f\x8b")

    normalize_calls: list[dict] = []

    def _fake_normalize(**kwargs):
        normalize_calls.append(kwargs)
        out = kwargs["output_vcf"]
        out.parent.mkdir(parents=True, exist_ok=True)
        # Write a non-empty bgzip so any INV-R002 guard downstream is OK.
        out.write_bytes(b"\x1f\x8b")

    compute_calls: list[dict] = []

    def _fake_compute(**kwargs):
        compute_calls.append(kwargs)
        return PgsRow(
            pgs_id="PGS000018",
            trait_label="x",
            percentile_in_user_ancestry=50.0,
            raw_score=0.0,
            study_population="x",
            calibration_warning=None,
            agent_choice_rationale="r" * 60,
            requested_for_question="q",
        )

    # Patch the scorefile-id extractor so the orchestrator can derive
    # `pgs_id` from the fixture scorefile without parsing real PGS Catalog
    # format.
    def _fake_extract(_scorefile_path):
        return "PGS000018"

    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier1", side_effect=_fake_tier1),
        patch("genomeclaw_toolkit.prep.coverage_fill.prepare_coverage_tier2", side_effect=_fake_tier2),
        patch("genomeclaw_toolkit.prep.coverage_fill._merge_tier1_tier2", side_effect=_fake_merge),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._normalize_for_pgsc_calc",
            side_effect=_fake_normalize,
        ),
        patch("genomeclaw_toolkit.prep.coverage_fill.compute_pgs", side_effect=_fake_compute),
        patch(
            "genomeclaw_toolkit.prep.coverage_fill._extract_pgs_id_from_scorefile",
            side_effect=_fake_extract,
        ),
    ):
        compute_prs_with_coverage_fill(
            sample_id="test_sample",
            cram_path=cram,
            sites_tsv=sites,
            alleles_tsv=alleles,
            scorefile_path=scorefile,
            fasta=fasta,
            panel_version="v1",
            reference_root=as_sibling_mountable(reference_root),
            output_root=output_root,
            work_dir=as_sibling_mountable(work_dir),
            agent_choice_rationale="r" * 60,
            requested_for_question="q",
        )

    # _normalize_for_pgsc_calc was called exactly once between merge + compute.
    assert len(normalize_calls) == 1, normalize_calls

    norm_call = normalize_calls[0]
    normalized_output = norm_call["output_vcf"]

    # The orchestrator passes the NORMALIZED VCF path to compute_pgs,
    # NOT the raw merged VCF.
    assert len(compute_calls) == 1, compute_calls
    compute_vcf = compute_calls[0]["vcf"]
    # `compute_pgs` may wrap the path via as_sibling_mountable; compare
    # by Path equality (SiblingMountablePath is a Path subclass).
    assert Path(compute_vcf) == Path(normalized_output), (
        f"compute_pgs received {compute_vcf!r} but should have received the "
        f"normalized VCF {normalized_output!r}. A regression here bypasses "
        f"the multi-allelic decomposition step."
    )

    # And the normalize step's input is the merged VCF.
    assert "input_vcf" in norm_call, norm_call
    assert "fasta" in norm_call and norm_call["fasta"] == fasta

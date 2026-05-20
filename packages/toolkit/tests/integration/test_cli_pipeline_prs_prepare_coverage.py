"""Phase 1b — ``genomeclaw pipeline prs-prepare-coverage`` subcommand tests.

Three contract assertions:

1. Happy path — invoking the CLI against a synthetic CRAM + panel TSVs
   produces ``derived/prs_coverage/<sample>/<panel>/tier1.vcf.gz`` and
   ``tier1.qc.json``; exit 0.
2. Cache-hit — re-invoking with the same inputs hits cache (no
   ``subprocess.run`` calls); exit 0; emits ``cache_status: "hit"``.
3. ``--json`` envelope — payload conforms to INV-C002 with
   ``cli_output_schema_version: "1.0"`` and the documented payload shape.

The bcftools binary is stubbed via the same regex-based pipe-output fake
the wrapper-level tests use; this isolates the CLI logic from the
toolchain itself.
"""

from __future__ import annotations

import gzip
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_NORM_OUTPUT_RE = re.compile(r"bcftools norm[^|&]*?--output\s+(\S+)")


def _write_synthetic_tier1_vcf(path: Path) -> None:
    """Write a tiny synthetic ``tier1.vcf.gz`` with realistic chr22 GT ratios.

    Mirrors the chr22 prove-out distribution shape (5 REF/REF, 2 het,
    1 hom-alt, 1 missing) so the QC summary the orchestrator generates is
    self-documenting.
    """
    lines = [
        "##fileformat=VCFv4.2",
        "##contig=<ID=chr22,length=50818468>",
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">',
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="depth">',
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tMPNRGLQ2K",
    ]
    rows = [
        ("0/0", 30),
        ("0/0", 25),
        ("0/0", 28),
        ("0/0", 32),
        ("0/0", 29),
        ("0/1", 27),
        ("0/1", 31),
        ("1/1", 26),
        ("./.", 0),
    ]
    for i, (gt, dp) in enumerate(rows, start=10001):
        lines.append(f"chr22\t{i}\t.\tA\tG\t.\tPASS\t.\tGT:DP\t{gt}:{dp}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    (path.parent / (path.name + ".tbi")).write_bytes(b"")


def _bcftools_run_fake() -> MagicMock:
    """``subprocess.run`` fake that materialises the staged tier1 VCF.

    Parses the ``bcftools norm --output <path>`` arg out of the shell-glued
    pipe and writes the synthetic VCF there. Decouples the test from the
    wrapper's scratch-staging logic.
    """

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        match = _NORM_OUTPUT_RE.search(cmd_str)
        if match:
            _write_synthetic_tier1_vcf(Path(match.group(1)))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return MagicMock(side_effect=_runner)


@pytest.fixture
def coverage_fixture(tmp_path: Path) -> dict[str, Path]:
    """Stage CRAM + panel TSVs + reference FASTA for the CLI happy path."""
    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"CRAM-fixture")
    (raw / "MPNRGLQ2K.cram.crai").write_bytes(b"")

    ref = tmp_path / "reference"
    grch38 = ref / "grch38"
    grch38.mkdir(parents=True)
    fasta = grch38 / "grch38.fa.gz"
    fasta.write_bytes(b"")
    (grch38 / "grch38.fa.gz.fai").write_bytes(b"")
    (grch38 / "grch38.fa.gz.gzi").write_bytes(b"")

    pca = ref / "prs_pca_sites" / "v1"
    pca.mkdir(parents=True)
    sites = pca / "pca_sites.tsv"
    alleles = pca / "pca_alleles.tsv"
    sites.write_text("chr22\t10001\nchr22\t10002\n")
    alleles.write_text("chr22\t10001\tA,G\nchr22\t10002\tA,G\n")

    derived = tmp_path / "derived"
    derived.mkdir()

    return {
        "cram": cram,
        "fasta": fasta,
        "sites": sites,
        "alleles": alleles,
        "derived": derived,
    }


def test_cli_prs_prepare_coverage_happy_path(
    invoke_cli, coverage_fixture: dict[str, Path]
) -> None:
    """Happy path: CLI invokes the wrapper, emits tier1.vcf.gz + tier1.qc.json under derived."""
    derived = coverage_fixture["derived"]
    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run", _bcftools_run_fake()
    ):
        result = invoke_cli(
            [
                "pipeline",
                "prs-prepare-coverage",
                "--sample",
                "MPNRGLQ2K",
                "--cram",
                str(coverage_fixture["cram"]),
                "--sites",
                str(coverage_fixture["sites"]),
                "--alleles",
                str(coverage_fixture["alleles"]),
                "--fasta",
                str(coverage_fixture["fasta"]),
                "--panel-version",
                "v1",
                "--output-root",
                str(derived),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    tier1_vcf = derived / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
    tier1_qc = derived / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.qc.json"
    assert tier1_vcf.exists(), "tier1.vcf.gz must land under derived/"
    assert tier1_qc.exists(), "tier1.qc.json must land under derived/"


def test_cli_prs_prepare_coverage_cache_hit(
    invoke_cli, coverage_fixture: dict[str, Path]
) -> None:
    """Second invocation against an existing cache short-circuits subprocess.run."""
    derived = coverage_fixture["derived"]

    first_fake = _bcftools_run_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", first_fake):
        first = invoke_cli(
            [
                "pipeline",
                "prs-prepare-coverage",
                "--sample",
                "MPNRGLQ2K",
                "--cram",
                str(coverage_fixture["cram"]),
                "--sites",
                str(coverage_fixture["sites"]),
                "--alleles",
                str(coverage_fixture["alleles"]),
                "--fasta",
                str(coverage_fixture["fasta"]),
                "--panel-version",
                "v1",
                "--output-root",
                str(derived),
            ]
        )
    assert first.exit_code == 0, f"first run stderr={first.stderr!r}"
    assert first_fake.call_count >= 1, "first run must shell out to bcftools"

    # Re-invocation hits cache; no subprocess calls.
    second_fake = MagicMock()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", second_fake):
        second = invoke_cli(
            [
                "pipeline",
                "prs-prepare-coverage",
                "--sample",
                "MPNRGLQ2K",
                "--cram",
                str(coverage_fixture["cram"]),
                "--sites",
                str(coverage_fixture["sites"]),
                "--alleles",
                str(coverage_fixture["alleles"]),
                "--fasta",
                str(coverage_fixture["fasta"]),
                "--panel-version",
                "v1",
                "--output-root",
                str(derived),
            ]
        )
    assert second.exit_code == 0, f"second run stderr={second.stderr!r}"
    assert second_fake.call_count == 0, (
        "cache-hit must not shell out to bcftools (got "
        f"{second_fake.call_count} calls)"
    )


def test_cli_prs_prepare_coverage_json_envelope_shape(
    invoke_cli, coverage_fixture: dict[str, Path]
) -> None:
    """`--json` mode emits the INV-C002 one-shot envelope with the documented payload."""
    derived = coverage_fixture["derived"]
    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run", _bcftools_run_fake()
    ):
        result = invoke_cli(
            [
                "--json",
                "pipeline",
                "prs-prepare-coverage",
                "--sample",
                "MPNRGLQ2K",
                "--cram",
                str(coverage_fixture["cram"]),
                "--sites",
                str(coverage_fixture["sites"]),
                "--alleles",
                str(coverage_fixture["alleles"]),
                "--fasta",
                str(coverage_fixture["fasta"]),
                "--panel-version",
                "v1",
                "--output-root",
                str(derived),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"
    envelope = result.stdout_json()
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "pipeline.prs-prepare-coverage"
    payload = envelope["payload"]
    assert payload["sample_id"] == "MPNRGLQ2K"
    assert payload["panel_version"] == "v1"
    assert payload["tier1_vcf"].endswith("tier1.vcf.gz")
    assert payload["cache_status"] in {"built", "hit"}

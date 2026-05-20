"""Phase 4c — ``genomeclaw pipeline prs-compute`` end-to-end subcommand tests.

The agent's compute path lives behind one CLI subcommand. The subcommand
calls :func:`compute_prs_with_coverage_fill` (chains Tier 1 + Tier 2 + merge
+ pgsc_calc) and emits a :class:`pgs_scores`-shaped JSON envelope.

Three contract assertions:

1. Happy path — the CLI returns exit 0 against stubbed primitives and
   emits a `PgsRow`-shaped payload.
2. `--json` envelope — payload conforms to `INV-C002` with
   ``cli_output_schema_version: "1.0"`` and ``command:
   "pipeline.prs-compute"``.
3. `--rationale` length gate — < 50 chars raises a `UsageError` per
   `INV-A003` (matches the existing `pipeline pgs-compute` discipline).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from genomeclaw_toolkit.prep.pgs import PgsRow

_EXPECTED_ROW = PgsRow(
    pgs_id="PGS000018",
    trait_label="PGS Catalog PGS000018",
    percentile_in_user_ancestry=87.0,
    raw_score=0.42,
    study_population="PGS Catalog scoring weights",
    calibration_warning=None,
    agent_choice_rationale="r" * 60,
    requested_for_question="q",
)


@pytest.fixture
def prs_compute_fixture(tmp_path: Path) -> dict[str, Path]:
    """Stage the minimum on-disk layout the CLI subcommand expects."""
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

    pca = ref / "prs_pca_sites" / "v1"
    pca.mkdir(parents=True)
    sites = pca / "pca_sites.tsv"
    alleles = pca / "pca_alleles.tsv"
    sites.write_text("chr22\t10001\n")
    alleles.write_text("chr22\t10001\tA,G\n")

    ancestry = ref / "pgs_catalog_ancestry" / "v1"
    ancestry.mkdir(parents=True)
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"")

    import gzip as _gzip

    scorefile = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    with _gzip.open(scorefile, "wt") as fh:
        fh.write(
            "#pgs_id=PGS000018\n"
            "hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
            "22\t20001\tG\tA\t0.0123\n"
        )

    return {
        "cram": cram,
        "fasta": fasta,
        "sites": sites,
        "alleles": alleles,
        "scorefile": scorefile,
        "reference_root": ref,
        "output_root": tmp_path / "derived",
        "work_dir": tmp_path / "work",
    }


def _common_argv(fx: dict[str, Path], *, rationale: str = "r" * 60) -> list[str]:
    return [
        "pipeline",
        "prs-compute",
        "--sample",
        "MPNRGLQ2K",
        "--cram",
        str(fx["cram"]),
        "--sites",
        str(fx["sites"]),
        "--alleles",
        str(fx["alleles"]),
        "--scorefile",
        str(fx["scorefile"]),
        "--fasta",
        str(fx["fasta"]),
        "--panel-version",
        "v1",
        "--reference-root",
        str(fx["reference_root"]),
        "--output-root",
        str(fx["output_root"]),
        "--work-dir",
        str(fx["work_dir"]),
        "--rationale",
        rationale,
        "--question",
        "?",
    ]


def test_cli_prs_compute_happy_path(invoke_cli, prs_compute_fixture: dict[str, Path]) -> None:
    """CLI returns exit 0 + a populated payload against a stubbed orchestrator."""
    with patch(
        "genomeclaw_toolkit._cli.commands.pipeline.compute_prs_with_coverage_fill",
        return_value=_EXPECTED_ROW,
    ):
        result = invoke_cli(_common_argv(prs_compute_fixture))

    assert result.exit_code == 0, f"stderr={result.stderr!r}"


def test_cli_prs_compute_json_envelope(invoke_cli, prs_compute_fixture: dict[str, Path]) -> None:
    """`--json` mode emits the INV-C002 envelope with the documented payload."""
    with patch(
        "genomeclaw_toolkit._cli.commands.pipeline.compute_prs_with_coverage_fill",
        return_value=_EXPECTED_ROW,
    ):
        result = invoke_cli(["--json", *_common_argv(prs_compute_fixture)])

    assert result.exit_code == 0, f"stderr={result.stderr!r}"
    envelope = result.stdout_json()
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "pipeline.prs-compute"
    payload = envelope["payload"]
    assert payload["pgs_id"] == "PGS000018"
    assert payload["percentile_in_user_ancestry"] == 87.0
    assert payload["sample_id"] == "MPNRGLQ2K"


def test_cli_prs_compute_rationale_length_gate(
    invoke_cli, prs_compute_fixture: dict[str, Path]
) -> None:
    """Short --rationale → UsageError per INV-A003 (matches pgs-compute discipline)."""
    result = invoke_cli(_common_argv(prs_compute_fixture, rationale="too short"))
    assert result.exit_code != 0
    # Match the existing pgs-compute error wording for consistency.
    assert "rationale" in (result.stderr + result.stdout).lower()

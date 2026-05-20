"""Phase 3b3b2 — ``genomeclaw pipeline prs-compute`` catches ``PRSDeclineError``.

When the orchestrator's calibration step raises ``PRSDeclineError``
(INV-C001 v1.7), the CLI doesn't propagate it as an unhandled exception.
Instead it emits a typed JSON envelope with ``payload.decline.reason`` +
``two_named_reasons`` and exits 0 — a decline is a legitimate output of
the agent's compute path, not a failure.

The clean / warning path remains as Phase 4c — exits 0 with a
:class:`_PrsComputePayload`. The decline path emits a
:class:`_PrsComputePayload` with the ``decline`` block populated.

Contract assertions:

1. ``PRSDeclineError`` raised by the orchestrator → exit 0 (decline is a
   valid outcome).
2. JSON envelope carries ``payload.decline.reason`` + ``payload.decline.
   two_named_reasons``.
3. CLI rich-mode rendering produces a user-readable line (no stack trace).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fixture(tmp_path: Path) -> dict[str, Path]:
    """Stage the same fixture the existing CLI test uses."""
    import gzip as _gzip

    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"CRAM")
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


def _common_argv(fx: dict[str, Path]) -> list[str]:
    return [
        "pipeline",
        "prs-compute",
        "--sample", "MPNRGLQ2K",
        "--cram", str(fx["cram"]),
        "--sites", str(fx["sites"]),
        "--alleles", str(fx["alleles"]),
        "--scorefile", str(fx["scorefile"]),
        "--fasta", str(fx["fasta"]),
        "--panel-version", "v1",
        "--reference-root", str(fx["reference_root"]),
        "--output-root", str(fx["output_root"]),
        "--work-dir", str(fx["work_dir"]),
        "--rationale", "r" * 60,
        "--question", "?",
    ]


def _raise_decline(*_args, **_kwargs):
    """A fake orchestrator that always raises PRSDeclineError (the 2026-05-17 smoke case)."""
    from genomeclaw_toolkit.prep._pgs_qc import DeclineReason, PRSDeclineError

    raise PRSDeclineError(
        reason=DeclineReason.VARIANT_OVERLAP_INSUFFICIENT,
        two_named_reasons=(
            "Match rate 28.40% falls below the variant-overlap threshold for a "
            "1,744,622-variant PGS scoring file.",
            "Variant-overlap insufficient: too few PGS scoring sites had genotype "
            "calls in the user's input to support an ancestry-calibrated score "
            "(INV-C001 v1.7).",
        ),
        message=(
            "PRS PGS000018 declined per INV-C001 v1.7 "
            "(match_rate=0.2840 below threshold for 1,744,622-variant tier)"
        ),
    )


def test_cli_prs_compute_decline_exits_zero(invoke_cli, fixture: dict[str, Path]) -> None:
    """Decline is a legitimate output; CLI exits 0, not a failure code."""
    with patch(
        "genomeclaw_toolkit._cli.commands.pipeline.compute_prs_with_coverage_fill",
        side_effect=_raise_decline,
    ):
        result = invoke_cli(_common_argv(fixture))

    assert result.exit_code == 0, (
        f"decline must exit 0 (it's a valid outcome, not an error); "
        f"got exit_code={result.exit_code}, stderr={result.stderr!r}"
    )


def test_cli_prs_compute_decline_json_envelope_carries_reason_and_two_reasons(
    invoke_cli, fixture: dict[str, Path]
) -> None:
    """`--json` envelope's payload.decline carries the structural reason + named reasons."""
    with patch(
        "genomeclaw_toolkit._cli.commands.pipeline.compute_prs_with_coverage_fill",
        side_effect=_raise_decline,
    ):
        result = invoke_cli(["--json", *_common_argv(fixture)])

    assert result.exit_code == 0
    envelope = result.stdout_json()
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "pipeline.prs-compute"
    payload = envelope["payload"]
    decline = payload["decline"]
    assert decline is not None
    assert decline["reason"] == "variant_overlap_insufficient"
    assert len(decline["two_named_reasons"]) == 2
    joined = " | ".join(decline["two_named_reasons"])
    assert "28" in joined  # match rate cited
    assert "variant" in joined.lower() or "overlap" in joined.lower()


def test_cli_prs_compute_decline_rich_mode_no_stack_trace(
    invoke_cli, fixture: dict[str, Path]
) -> None:
    """Rich mode renders a one-line decline message — never a Python traceback."""
    with patch(
        "genomeclaw_toolkit._cli.commands.pipeline.compute_prs_with_coverage_fill",
        side_effect=_raise_decline,
    ):
        result = invoke_cli(_common_argv(fixture))

    assert result.exit_code == 0
    combined = result.stdout + result.stderr
    # No Python traceback markers — the decline must be cleanly framed.
    assert "Traceback" not in combined
    assert "PRSDeclineError" not in combined
    # The decline reason surfaces somewhere readable.
    assert (
        "decline" in combined.lower()
        or "variant_overlap_insufficient" in combined.lower()
    )

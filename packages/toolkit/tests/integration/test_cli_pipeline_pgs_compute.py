"""Phase 6 Slice E v2 — `genomeclaw pipeline pgs-compute` subcommand.

Manual-invocation CLI path that wraps `compute_pgs(...)` for users who want
to trigger a PRS compute outside the agent path (or who want to seed a
`pgs_scores` row before the E.3 orchestrator lands the async path).

Three assertions:

1. The subcommand writes a `pgs_scores` row carrying the full INV-A003
   provenance (`agent_choice_rationale`, `requested_for_question`) +
   the seven canonical INV-R001 provenance columns.
2. The subcommand also INSERTs the matching `clinical-non-actionable`
   row into `findings` so the agent's `genomeclaw_findings category=...`
   filter surfaces the new PRS without a second materialize step.
3. The `--json` envelope shape conforms to `INV-C002` (one-shot envelope
   with `cli_output_schema_version: "1.0"`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

_RUN_ID = "2026-05-17T00-00-00Z-pgscli001"


def _stage_run(derived_root: Path) -> Path:
    """Stage a `derived/<run-id>/` with manifest + empty `variants.duckdb`."""
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": "cli-fixture"}
        )
    )
    create_store(run_dir / "variants.duckdb")
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def _make_reference_root(tmp_path: Path) -> Path:
    """Stage the canonical post-fetch ancestry layout (verified upstream).

    Real upstream layout (2026-05-17 smoke): gnomAD-merged 1000G + HGDP
    callset extracts FLAT into the release dir — combined files keyed by
    reference build, no per-population subdirs.
    """
    ref = tmp_path / "reference"
    ancestry = ref / "pgs_catalog_ancestry" / "v1"
    ancestry.mkdir(parents=True)
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"data")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"data")
    (ancestry / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"data")
    (ref / "pgs_catalog").mkdir(parents=True)
    return ref


def _fake_pgsc_calc(
    work_dir: Path,
    *,
    pgs_id: str = "PGS000018",
    percentile: float = 87.0,
) -> MagicMock:
    """Patch `subprocess.run` to write fixture output files + return rc=0."""

    def _runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        # pgsc_calc Nextflow output convention: <workdir>/{score, ancestry}/...
        score_dir = work_dir / "score"
        ancestry_dir = work_dir / "ancestry"
        score_dir.mkdir(parents=True, exist_ok=True)
        ancestry_dir.mkdir(parents=True, exist_ok=True)
        (score_dir / "aggregated_scores.txt").write_text(
            f"sampleset\tIID\tPGS\tSUM\tDENOM\tAVG\nuser\tuser-1\t{pgs_id}\t0.42\t1000\t0.00042\n"
        )
        (ancestry_dir / "aggregated_scores_norm.txt").write_text(
            "sampleset\tIID\tPGS\tpercentile_MostSimilarPop\tcalibration_warning\n"
            f"user\tuser-1\t{pgs_id}\t{percentile}\t\n"
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return MagicMock(side_effect=_runner)


def test_cli_pipeline_pgs_compute_writes_pgs_scores_row(tmp_path: Path, invoke_cli) -> None:
    """`pipeline pgs-compute` populates `pgs_scores` with INV-A003 + INV-R001 columns."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    reference_root = _make_reference_root(tmp_path)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    work_dir = tmp_path / "work"

    rationale = (
        "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS with the most mature "
        "cross-ancestry calibration story. Considered PGS004696 but went with "
        "PGS000018 for cross-ancestry validation."
    )
    question = "my dad had a heart attack at 58. is there anything in my genome about cad risk?"

    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", _fake_pgsc_calc(work_dir)):
        result = invoke_cli(
            [
                "pipeline",
                "pgs-compute",
                "--pgs",
                "PGS000018",
                "--vcf",
                str(vcf),
                "--reference-root",
                str(reference_root),
                "--rationale",
                rationale,
                "--question",
                question,
                "--work-dir",
                str(work_dir),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    # Verify the pgs_scores row exists with INV-A003 + INV-R001 provenance.
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row = conn.execute(
            """
            SELECT pgs_id, percentile_in_user_ancestry, agent_choice_rationale,
                   requested_for_question, source_path, tool, schema_version
            FROM pgs_scores WHERE pgs_id = ?
            """,
            ["PGS000018"],
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "PGS000018"
    assert row[1] == 87.0
    assert row[2] == rationale, "INV-A003: agent_choice_rationale persisted"
    assert row[3] == question, "INV-A003: requested_for_question persisted"
    assert row[4], "INV-R001: source_path populated"
    assert row[5] == "pgsc_calc", "INV-R001: tool populated"
    assert row[6] == SCHEMA_VERSION


def test_cli_pipeline_pgs_compute_inserts_matching_finding(tmp_path: Path, invoke_cli) -> None:
    """A successful compute also INSERTs the matching `clinical-non-actionable` row in findings.

    This bundles into the same CLI invocation so the user (or the agent in
    E.3's async path) doesn't have to run a second materialize step to make
    the PRS surface via `genomeclaw_findings`. Per INV-E001 the row carries
    `evidence_ref=pgs_catalog:PGS<id>`; per INV-C001 v1.7 it carries no
    `clinical_escalation` marker.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    reference_root = _make_reference_root(tmp_path)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    work_dir = tmp_path / "work"

    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", _fake_pgsc_calc(work_dir)):
        result = invoke_cli(
            [
                "pipeline",
                "pgs-compute",
                "--pgs",
                "PGS000018",
                "--vcf",
                str(vcf),
                "--reference-root",
                str(reference_root),
                "--rationale",
                "x" * 60,
                "--question",
                "my dad had a heart attack at 58",
                "--work-dir",
                str(work_dir),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row = conn.execute(
            """
            SELECT category, evidence_ref, clinical_escalation
            FROM findings WHERE evidence_ref = ?
            """,
            ["pgs_catalog:PGS000018"],
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "no findings row was inserted for the computed PRS"
    assert row[0] == "clinical-non-actionable", "INV-C001 v1.7: PRS findings are non-actionable"
    assert row[1] == "pgs_catalog:PGS000018", "INV-E001: variant-keyed evidence_ref"
    assert row[2] is None, "INV-C001: PRS findings carry NO clinical_escalation marker"


def test_cli_pipeline_pgs_compute_json_envelope_shape(tmp_path: Path, invoke_cli) -> None:
    """`--json` mode emits the documented one-shot envelope per INV-C002."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    reference_root = _make_reference_root(tmp_path)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    work_dir = tmp_path / "work"

    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", _fake_pgsc_calc(work_dir)):
        result = invoke_cli(
            [
                "--json",
                "pipeline",
                "pgs-compute",
                "--pgs",
                "PGS000018",
                "--vcf",
                str(vcf),
                "--reference-root",
                str(reference_root),
                "--rationale",
                "x" * 60,
                "--question",
                "?",
                "--work-dir",
                str(work_dir),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"
    envelope = result.stdout_json()
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "pipeline.pgs-compute"
    payload = envelope["payload"]
    assert payload["pgs_id"] == "PGS000018"
    assert payload["percentile_in_user_ancestry"] == 87.0

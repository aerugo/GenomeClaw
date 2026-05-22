"""Phase 6 Slice D' — `genomeclaw pipeline pharmcat` subcommand integration tests.

Four assertions:

1. Each emitted findings row carries `evidence_ref=pharmgkb:<id>` (INV-E001).
2. Each findings row carries the seven canonical INV-R001 provenance fields.
3. `clinical-actionable` findings carry `clinical_escalation=confirm_with_provider`
   (INV-C001 v1.5).
4. The `--json` envelope shape conforms to INV-C002 (`cli_output_schema_version: "1.0"`).

Subprocess.run is mocked at the wrapper level; the real-data smoke
runs after the Dockerfile bakes PharmCAT v3.2.0.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import duckdb

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

_RUN_ID = "2026-05-22T00-00-00Z-pharmcat001"


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


def _write_cyp2d6_diplotype_json(run_dir: Path) -> Path:
    path = run_dir / "cyp2d6_diplotype.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "MPNRGLQ2K",
                "diplotype": "*1/*35",
                "filter_status": "PASS",
                "raw_cyrius_output": {},
                "provenance": {
                    "source_path": "/dummy/sample.cram",
                    "source_sha256": "f" * 64,
                    "tool": "cyrius",
                    "tool_version": "1.1.1",
                    "params_json": "{}",
                    "schema_version": "v0.2",
                    "created_at": "2026-05-22T00:00:00+00:00",
                },
            }
        )
    )
    return path


def _fake_pharmcat_report() -> dict:
    """PharmCAT v3.2.0 shape — a user-applicable actionable clopidogrel annotation."""
    return {
        "genes": {
            "CYP2C19": {
                "recommendationDiplotypes": [
                    {
                        "phenotypes": ["Intermediate Metabolizer"],
                        "allele1": {"gene": "CYP2C19", "name": "*1"},
                        "allele2": {"gene": "CYP2C19", "name": "*2"},
                    }
                ],
            },
        },
        "drugs": {
            "CPIC Guideline Annotation": {
                "clopidogrel": {
                    "id": "PA449053",
                    "guidelines": [
                        {
                            "annotations": [
                                {
                                    "drugRecommendation": (
                                        "Avoid standard dose clopidogrel. "
                                        "Use prasugrel or ticagrelor."
                                    ),
                                    "classification": "Strong",
                                    "phenotypes": {"CYP2C19": "Intermediate Metabolizer"},
                                    "dosingInformation": False,
                                    "alternateDrugAvailable": True,
                                    "otherPrescribingGuidance": False,
                                    "genotypes": [
                                        {
                                            "diplotypes": [
                                                {
                                                    "gene": "CYP2C19",
                                                    "allele1": {"name": "*1"},
                                                    "allele2": {"name": "*2"},
                                                }
                                            ]
                                        }
                                    ],
                                },
                            ]
                        }
                    ],
                },
            },
        },
    }


def _fake_pharmcat(run_dir: Path):
    """Patch `subprocess.run` to handle both PharmCAT stages with synthetic outputs.

    The wrapper makes two subprocess calls: preprocessor + JAR. The stub
    recognises which stage is firing by inspecting argv and materialises
    the corresponding fixture file (`<base>.preprocessed.vcf.bgz` and
    `<base>.report.json` respectively).
    """

    def _runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        binary = cmd[0]
        if binary.endswith("pharmcat_vcf_preprocessor"):
            preprocessed_dir = run_dir / "pharmcat_preprocessed"
            preprocessed_dir.mkdir(parents=True, exist_ok=True)
            (preprocessed_dir / "sample.preprocessed.vcf.bgz").write_bytes(b"fake bgzf")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
        if binary.endswith("pharmcat") or "pharmcat.jar" in binary:
            report_dir = run_dir / "pharmcat"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "sample.report.json").write_text(json.dumps(_fake_pharmcat_report()))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected subprocess invocation: {cmd!r}")

    return _runner


def test_cli_pharmcat_writes_findings_with_pharmgkb_evidence_refs(
    tmp_path: Path, invoke_cli
) -> None:
    """Each emitted findings row carries `evidence_ref=pharmgkb:<id>` per INV-E001."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    cyp2d6_json = _write_cyp2d6_diplotype_json(run_dir)

    with patch("genomeclaw_toolkit.prep.pharmcat.subprocess.run", _fake_pharmcat(run_dir)):
        result = invoke_cli(
            [
                "pipeline",
                "pharmcat",
                "--vcf",
                str(vcf),
                "--cyp2d6-diplotype-json",
                str(cyp2d6_json),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute(
            "SELECT evidence_ref FROM findings WHERE tool = 'pharmcat'"
        ).fetchall()
    finally:
        conn.close()

    assert rows, "no pharmcat findings rows inserted"
    for (evidence_ref,) in rows:
        assert evidence_ref.startswith("pharmgkb:"), (
            f"INV-E001: pharmcat finding evidence_ref must start with 'pharmgkb:'; "
            f"got {evidence_ref!r}"
        )


def test_cli_pharmcat_stamps_inv_r001_provenance_on_each_finding_row(
    tmp_path: Path, invoke_cli
) -> None:
    """Each row carries the seven INV-R001 provenance fields."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    cyp2d6_json = _write_cyp2d6_diplotype_json(run_dir)

    with patch("genomeclaw_toolkit.prep.pharmcat.subprocess.run", _fake_pharmcat(run_dir)):
        result = invoke_cli(
            [
                "pipeline",
                "pharmcat",
                "--vcf",
                str(vcf),
                "--cyp2d6-diplotype-json",
                str(cyp2d6_json),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT source_path, source_sha256, tool, tool_version,
                   params_json, schema_version, created_at
            FROM findings WHERE tool = 'pharmcat'
            """
        ).fetchall()
    finally:
        conn.close()

    assert rows, "no pharmcat findings rows inserted"
    for source_path, source_sha256, tool, tool_version, params_json, schema_version, created_at in rows:
        assert source_path, "INV-R001: source_path populated"
        assert source_sha256, "INV-R001: source_sha256 populated"
        assert tool == "pharmcat"
        assert tool_version == "3.2.0"
        assert params_json, "INV-R001: params_json populated"
        assert schema_version == SCHEMA_VERSION
        assert created_at is not None


def test_cli_pharmcat_marks_actionable_findings_with_clinical_escalation(
    tmp_path: Path, invoke_cli
) -> None:
    """Each `clinical-actionable` row carries `clinical_escalation=confirm_with_provider`."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    cyp2d6_json = _write_cyp2d6_diplotype_json(run_dir)

    with patch("genomeclaw_toolkit.prep.pharmcat.subprocess.run", _fake_pharmcat(run_dir)):
        result = invoke_cli(
            [
                "pipeline",
                "pharmcat",
                "--vcf",
                str(vcf),
                "--cyp2d6-diplotype-json",
                str(cyp2d6_json),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute(
            "SELECT category, clinical_escalation FROM findings WHERE tool = 'pharmcat'"
        ).fetchall()
    finally:
        conn.close()

    assert rows, "no pharmcat findings rows inserted"
    for category, clinical_escalation in rows:
        assert category == "clinical-actionable", (
            f"INV-C001 v1.5: pharmcat findings are clinical-actionable; got {category!r}"
        )
        assert clinical_escalation == "confirm_with_provider", (
            f"INV-C001 v1.5: clinical-actionable findings must carry "
            f"clinical_escalation=confirm_with_provider; got {clinical_escalation!r}"
        )


def test_cli_pharmcat_emits_machine_readable_json(tmp_path: Path, invoke_cli) -> None:
    """`--json` mode emits the documented one-shot envelope per INV-C002."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")
    cyp2d6_json = _write_cyp2d6_diplotype_json(run_dir)

    with patch("genomeclaw_toolkit.prep.pharmcat.subprocess.run", _fake_pharmcat(run_dir)):
        result = invoke_cli(
            [
                "--json",
                "pipeline",
                "pharmcat",
                "--vcf",
                str(vcf),
                "--cyp2d6-diplotype-json",
                str(cyp2d6_json),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, "no JSON output produced"
    payload = json.loads(lines[-1])
    assert payload.get("cli_output_schema_version") == "1.0"
    assert payload.get("command") == "pipeline.pharmcat"
    # The payload's data carries the count of findings inserted.
    assert isinstance(payload.get("payload", {}).get("findings_inserted"), int)
    assert payload["payload"]["findings_inserted"] >= 1

"""`pipeline cyp2d6-call` + `pipeline pharmcat` integration on the no-call path.

End-to-end CLI tests for the cyp2d6-no-call-finding Phase 1 contract:

- `cyp2d6-call` against a sample that produces no Cyrius diplotype must
  exit 0 (not crash), write `cyp2d6_no_call_envelope.json`, and INSERT
  exactly one `clinical-actionable` `findings` row that explicitly says
  "do not interpret as Normal Metabolizer."
- `pharmcat` invoked after a no-call run must detect the sentinel,
  skip the CYP2D6 outside-call (no `-po` arg), and emit a rich-output
  warning line; the CYP2D6 finding is NOT duplicated (it was already
  inserted by `cyp2d6-call`).

The CLI conftest fixture `invoke_cli` from
`tests/integration/conftest.py` runs the CLI in-process via typer's
`CliRunner` — no subprocess overhead.
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

_RUN_ID = "2026-05-25T00-00-00Z-cyp2d6nocall001"


def _stage_run(derived_root: Path) -> Path:
    """Stage a derived/<run-id>/ with the minimum the CYP2D6 + PharmCAT commands need."""
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


def _stub_cyrius_no_call(run_dir: Path, sample_id: str = "MPNRGLQ2K"):
    """Patch `subprocess.run` in `prep.cyrius` to materialise a no-call JSON."""
    output_path = run_dir / "cyp2d6.json"

    def _stub(argv, **_kwargs):  # noqa: ANN001
        output_path.write_text(
            json.dumps(
                {
                    sample_id: {
                        "Genotype": "",
                        "Filter": "NO_CALL",
                        "Raw_call": "no call",
                    }
                }
            )
        )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    return _stub


def test_cli_cyp2d6_no_call_inserts_indeterminate_finding(
    tmp_path: Path, invoke_cli
) -> None:
    """`pipeline cyp2d6-call` on a no-call sample inserts exactly one indeterminate finding.

    Spec acceptance criteria 1a, 1c, 1d. The CLI must:
    - exit 0 (not raise)
    - write `cyp2d6_no_call_envelope.json` (not the success envelope)
    - INSERT a `clinical-actionable` row for CYP2D6 with explicit
      "do not interpret as Normal Metabolizer" prose
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam contents for cli no-call test")

    with patch(
        "genomeclaw_toolkit.prep.cyrius.subprocess.run", _stub_cyrius_no_call(run_dir)
    ):
        result = invoke_cli(
            [
                "pipeline",
                "cyp2d6-call",
                "--bam",
                str(bam),
                "--sample-id",
                "MPNRGLQ2K",
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    sentinel = run_dir / "cyp2d6_no_call_envelope.json"
    assert sentinel.exists(), "sentinel envelope not written"
    assert not (run_dir / "cyp2d6_diplotype.json").exists(), (
        "success envelope must NOT exist on the no-call path"
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT id, category, summary, evidence_ref, evidence_quality,
                   clinical_escalation, gene_symbols
            FROM findings
            WHERE 'CYP2D6' = ANY(gene_symbols)
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1, f"expected exactly one CYP2D6 finding row, got {rows!r}"
    (
        finding_id,
        category,
        summary,
        evidence_ref,
        evidence_quality,
        clinical_escalation,
        gene_symbols,
    ) = rows[0]

    assert finding_id.startswith("fnd-cyp2d6-no-call-"), (
        f"finding id should be deterministic for the no-call row; got {finding_id!r}"
    )
    assert category == "clinical-actionable"
    assert clinical_escalation == "confirm_with_provider"
    assert evidence_quality == "low"
    assert evidence_ref.startswith("cyrius_no_call:")
    assert str(sentinel) in evidence_ref, (
        f"evidence_ref should point at the sentinel file; got {evidence_ref!r}"
    )
    assert "do not interpret as normal metabolizer" in summary.lower(), (
        f"summary must explicitly forbid the Normal Metabolizer interpretation; "
        f"got {summary!r}"
    )
    assert gene_symbols == ["CYP2D6"]


def test_cli_cyp2d6_no_call_emits_cyp2d6_status_no_call_in_payload(
    tmp_path: Path, invoke_cli
) -> None:
    """The `--json` payload carries `cyp2d6_status='no_call'` + `diplotype=None`."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam contents")

    with patch(
        "genomeclaw_toolkit.prep.cyrius.subprocess.run", _stub_cyrius_no_call(run_dir)
    ):
        result = invoke_cli(
            [
                "--json",
                "pipeline",
                "cyp2d6-call",
                "--bam",
                str(bam),
                "--sample-id",
                "MPNRGLQ2K",
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"
    envelope = json.loads(result.stdout.splitlines()[-1])
    assert envelope["payload"]["cyp2d6_status"] == "no_call"
    # The CLI envelope serializes with `exclude_none=True`; the `diplotype`
    # field is None on the no-call path, so it is absent from the JSON
    # rather than set to literal null. Both shapes ("absent" and "null")
    # carry the same meaning for downstream JSON consumers.
    assert "diplotype" not in envelope["payload"] or envelope["payload"]["diplotype"] is None
    assert envelope["payload"]["filter_status"]  # non-empty (Cyrius filter or "NO_CALL")


def test_cli_pharmcat_skips_cyp2d6_outside_call_when_no_call_sentinel_present(
    tmp_path: Path, invoke_cli
) -> None:
    """`pharmcat` auto-detects the no-call sentinel + skips the outside-call.

    Spec acceptance criteria 2a, 2b, 2c. The CLI must:
    - detect `cyp2d6_no_call_envelope.json` in run_dir (no explicit flag)
    - not pass `-po` to the PharmCAT JAR (no CYP2D6 outside-call TSV)
    - continue running PharmCAT for other genes
    - not duplicate the CYP2D6 indeterminate finding (it was already inserted
      by the `cyp2d6-call` command)
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)

    # Pre-write the no-call sentinel as if `cyp2d6-call` had already run.
    (run_dir / "cyp2d6_no_call_envelope.json").write_text(
        json.dumps(
            {
                "cyp2d6_status": "no_call",
                "sample_id": "MPNRGLQ2K",
                "diplotype": None,
                "filter_status": "NO_CALL",
                "raw_cyrius_output": {"MPNRGLQ2K": {"Genotype": "", "Filter": "NO_CALL"}},
                "provenance": {
                    "source_path": "/dummy/sample.bam",
                    "source_sha256": "f" * 64,
                    "tool": "cyrius",
                    "tool_version": "1.1.1",
                    "params_json": "{}",
                    "schema_version": SCHEMA_VERSION,
                    "created_at": "2026-05-25T00:00:00+00:00",
                },
            }
        )
    )
    vcf = tmp_path / "user.vcf.gz"
    vcf.write_bytes(b"fake-vcf")

    # Capture PharmCAT argv to assert no `-po` flag.
    captured_argvs: list[list[str]] = []

    def _pharmcat_runner(cmd, **_kwargs):  # noqa: ANN001
        captured_argvs.append(list(cmd))
        binary = cmd[0]
        if binary.endswith("pharmcat_vcf_preprocessor"):
            preprocessed_dir = run_dir / "pharmcat_preprocessed"
            preprocessed_dir.mkdir(parents=True, exist_ok=True)
            (preprocessed_dir / "user.preprocessed.vcf.bgz").write_bytes(b"fake bgzf")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
        if binary.endswith("pharmcat") or "pharmcat.jar" in binary:
            report_dir = run_dir / "pharmcat"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "user.report.json").write_text(json.dumps({"genes": {}, "drugs": {}}))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected subprocess: {cmd!r}")

    with patch("genomeclaw_toolkit.prep.pharmcat.subprocess.run", _pharmcat_runner):
        result = invoke_cli(
            [
                "pipeline",
                "pharmcat",
                "--vcf",
                str(vcf),
                "--run-dir",
                str(run_dir),
            ]
        )

    assert result.exit_code == 0, f"stderr={result.stderr!r}"

    pharmcat_jar_argv = next(
        (argv for argv in captured_argvs if argv[0].endswith("pharmcat") or "pharmcat.jar" in argv[0]),
        None,
    )
    assert pharmcat_jar_argv is not None, "PharmCAT JAR was not invoked"
    assert "-po" not in pharmcat_jar_argv, (
        f"PharmCAT must NOT receive `-po` outside-call TSV when CYP2D6 is no-call; "
        f"got argv: {pharmcat_jar_argv!r}"
    )

    # The rich-output warning surfaces in stdout (or stderr — both are captured).
    combined_output = (result.stdout or "") + (result.stderr or "")
    assert "CYP2D6" in combined_output and (
        "no-call" in combined_output.lower() or "skipping" in combined_output.lower()
    ), (
        f"expected a CYP2D6-skip warning line in the CLI output; got: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_indeterminate_finding_reaches_findings_api(tmp_path: Path, invoke_cli) -> None:
    """Phase 2: the indeterminate CYP2D6 row reaches the agent via /v1/findings.

    After `cyp2d6-call` on a no-call sample, spin up the host FastAPI app
    via TestClient and call `GET /v1/findings?genes=CYP2D6`. Assert the
    indeterminate row is in the JSON response with category=
    `clinical-actionable`, the binding "do not interpret as Normal
    Metabolizer" prose, and the `cyrius_no_call:` evidence_ref.

    This pins the agent-facing observability of the indeterminate finding.
    """
    from fastapi.testclient import TestClient

    from genomeclaw_toolkit.service.app import build_app

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake bam contents for cli no-call api test")

    with patch(
        "genomeclaw_toolkit.prep.cyrius.subprocess.run", _stub_cyrius_no_call(run_dir)
    ):
        cli_result = invoke_cli(
            [
                "pipeline",
                "cyp2d6-call",
                "--bam",
                str(bam),
                "--sample-id",
                "MPNRGLQ2K",
                "--run-dir",
                str(run_dir),
            ]
        )
    assert cli_result.exit_code == 0, f"stderr={cli_result.stderr!r}"

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.get("/v1/findings", params={"genes": ["CYP2D6"]})

    assert response.status_code == 200, response.text
    body = response.json()
    rows = body["rows"]
    cyp2d6_rows = [r for r in rows if "CYP2D6" in r.get("gene_symbols", [])]
    assert len(cyp2d6_rows) == 1, (
        f"expected exactly one CYP2D6 finding in /v1/findings; got {cyp2d6_rows!r}"
    )
    row = cyp2d6_rows[0]
    assert row["category"] == "clinical-actionable"
    assert row["clinical_escalation"] == "confirm_with_provider"
    assert row["evidence_ref"].startswith("cyrius_no_call:")
    assert "do not interpret as normal metabolizer" in row["summary"].lower()

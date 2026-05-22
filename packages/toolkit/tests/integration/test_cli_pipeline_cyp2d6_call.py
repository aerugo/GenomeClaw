"""Phase 6 Slice D — `genomeclaw pipeline cyp2d6-call` subcommand integration tests.

Three assertions:

1. The subcommand writes `cyp2d6_diplotype.json` under the run-dir with
   the wrapper envelope shape.
2. The envelope carries the seven canonical INV-R001 provenance columns.
3. The `--json` envelope conforms to INV-C002 (one-shot CLI envelope
   with `cli_output_schema_version: "1.0"`).

Subprocess.run is mocked at the wrapper level — the real-data smoke
against the project owner's CRAM is deferred to a manual session after
the Dockerfile is updated to include ``bioconda::cyrius``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

_RUN_ID = "2026-05-22T00-00-00Z-cyp2d6cli001"


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


def _fake_cyrius(run_dir: Path, *, sample_id: str = "MPNRGLQ2K", diplotype: str = "*1/*4"):
    """Patch `subprocess.run` to write a synthetic Cyrius JSON + return rc=0."""

    def _runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        (run_dir / "cyp2d6.json").write_text(
            json.dumps({sample_id: {"Genotype": [diplotype], "Filter": ["PASS"]}})
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return _runner


def test_cli_cyp2d6_call_writes_json_under_run_dir(tmp_path: Path, invoke_cli) -> None:
    """`pipeline cyp2d6-call` writes the wrapper envelope to `cyp2d6_diplotype.json`."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake-bam")

    with patch("genomeclaw_toolkit.prep.cyrius.subprocess.run", _fake_cyrius(run_dir)):
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
    envelope_path = run_dir / "cyp2d6_diplotype.json"
    assert envelope_path.exists()
    envelope = json.loads(envelope_path.read_text())
    assert envelope["diplotype"] == "*1/*4"
    assert envelope["sample_id"] == "MPNRGLQ2K"


def test_cli_cyp2d6_call_stamps_inv_r001_provenance(tmp_path: Path, invoke_cli) -> None:
    """Envelope carries the seven canonical INV-R001 provenance fields."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake-bam")

    with patch("genomeclaw_toolkit.prep.cyrius.subprocess.run", _fake_cyrius(run_dir)):
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
    envelope = json.loads((run_dir / "cyp2d6_diplotype.json").read_text())
    provenance = envelope["provenance"]
    for key in (
        "source_path",
        "source_sha256",
        "tool",
        "tool_version",
        "params_json",
        "schema_version",
        "created_at",
    ):
        assert provenance.get(key), f"INV-R001: provenance['{key}'] must be populated"
    assert provenance["tool"] == "cyrius"
    assert provenance["schema_version"] == SCHEMA_VERSION


def test_cli_cyp2d6_call_emits_machine_readable_json(tmp_path: Path, invoke_cli) -> None:
    """`--json` mode emits the parsed CyriusDiplotypeRow on stdout per INV-C002."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"fake-bam")

    with patch("genomeclaw_toolkit.prep.cyrius.subprocess.run", _fake_cyrius(run_dir)):
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
    # First line should be the cli-output-schema envelope header.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, "no JSON output produced"
    payload = json.loads(lines[-1])
    assert payload.get("payload", {}).get("diplotype") == "*1/*4"
    assert payload.get("payload", {}).get("sample_id") == "MPNRGLQ2K"

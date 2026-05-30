"""Steps C and D integration tests — ingest hook + pgs-config-write CLI.

Step C: `pipeline ingest` writes prs_compute_config.json when --bam + --reference-root given.
Step D: `pipeline pgs-config-write` derives + writes sidecar for pre-existing run dirs.

Plan: docs/plans/active/investigate-prs-compute-config-missing.md
Invariants: INV-D001, INV-R001, INV-R002, INV-D006.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.service.pgs_compute_config import (
    PrsComputeConfig,
    PrsComputeConfigMissingError,
    load_prs_compute_config,
)

# A minimal valid manifest matching what ingest() writes.
# Note: reference_path points to the FASTA (as in the active run).
_MINIMAL_MANIFEST = {
    "run_id": "2026-05-25T19-42-58Z-c88e02",
    "schema_version": "v0.3",
    "sample_id": "TEST001",
    "input": {
        "vcf_path": "/tmp/test.vcf.gz",
        "vcf_sha256": "abc",
        "tbi_path": "/tmp/test.vcf.gz.tbi",
        "tbi_sha256": "def",
        "reference_path": "/Volumes/Genome_Work/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz",
        "reference_build_inferred": "grch38",
        "bam_path": "/Volumes/Genome_Work/genomeclaw/raw/TEST001/TEST001.cram",
        "bam_sha256": "bam123",
    },
    "created_at": "2026-05-25T19:42:58Z",
}


class TestPgsConfigWriteCLI:
    """Step D: `pipeline pgs-config-write` subcommand tests.

    INV-D001: only writes under run_dir/ (derived/).
    INV-R001: sidecar is loadable + has all required fields.
    INV-R002: structured-failure guard still fires when config is genuinely missing post-repair
              (tested by the existing test_pgs_compute_structured_failure_path.py).
    """

    def test_invR001_subcommand_writes_valid_sidecar(
        self, tmp_path: Path, invoke_cli
    ) -> None:
        """INV-R001: pgs-config-write writes a sidecar that load_prs_compute_config accepts."""
        run_dir = tmp_path / "run01"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps(_MINIMAL_MANIFEST))

        reference_root = tmp_path / "reference"
        reference_root.mkdir()
        scratch_root = tmp_path / "_scratch"
        scratch_root.mkdir()

        result = invoke_cli(
            [
                "--json",
                "pipeline",
                "pgs-config-write",
                "--run-dir",
                str(run_dir),
                "--reference-root",
                str(reference_root),
                "--scratch-root",
                str(scratch_root),
            ]
        )

        assert result.exit_code == 0, f"CLI failed (exit={result.exit_code}):\n{result.stderr}"

        cfg = load_prs_compute_config(run_dir)
        assert isinstance(cfg, PrsComputeConfig)
        assert cfg.sample_id == "TEST001"
        assert "prs_pca_sites" in str(cfg.sites_tsv)
        assert "prs_pca_sites" in str(cfg.alleles_tsv)
        assert str(reference_root) in str(cfg.scorefile_root)

    def test_invD001_sidecar_written_under_run_dir_not_reference(
        self, tmp_path: Path, invoke_cli
    ) -> None:
        """INV-D001: pgs-config-write writes under run_dir/ only, not reference/."""
        run_dir = tmp_path / "run02"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps(_MINIMAL_MANIFEST))

        reference_root = tmp_path / "reference"
        reference_root.mkdir()

        invoke_cli(
            [
                "pipeline",
                "pgs-config-write",
                "--run-dir",
                str(run_dir),
                "--reference-root",
                str(reference_root),
            ]
        )

        # Sidecar must be under run_dir
        assert (run_dir / "prs_compute_config.json").exists()
        # reference_root must be untouched (no writes)
        assert list(reference_root.iterdir()) == [], "reference_root must remain empty (INV-D001)"

    def test_invR002_missing_sidecar_before_repair_raises_config_missing_error(
        self, tmp_path: Path
    ) -> None:
        """INV-R002: before repair, load_prs_compute_config raises PrsComputeConfigMissingError."""
        run_dir = tmp_path / "run03"
        run_dir.mkdir()
        with pytest.raises(PrsComputeConfigMissingError):
            load_prs_compute_config(run_dir)

    def test_subcommand_fails_gracefully_when_manifest_missing(
        self, tmp_path: Path, invoke_cli
    ) -> None:
        """pgs-config-write exits nonzero with a clear message when manifest.json is absent."""
        run_dir = tmp_path / "run04"
        run_dir.mkdir()
        # No manifest.json written

        result = invoke_cli(
            [
                "pipeline",
                "pgs-config-write",
                "--run-dir",
                str(run_dir),
                "--reference-root",
                str(tmp_path / "reference"),
            ]
        )

        assert result.exit_code != 0
        # The error message should mention manifest.json
        combined = result.stdout + result.stderr
        assert "manifest.json" in combined, combined

    def test_subcommand_fails_gracefully_when_bam_path_missing_from_manifest(
        self, tmp_path: Path, invoke_cli
    ) -> None:
        """pgs-config-write exits nonzero when manifest lacks bam_path (no CRAM available)."""
        run_dir = tmp_path / "run05"
        run_dir.mkdir()
        manifest_no_bam = {
            **_MINIMAL_MANIFEST,
            "input": {
                k: v
                for k, v in _MINIMAL_MANIFEST["input"].items()
                if k != "bam_path"
            },
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest_no_bam))
        (tmp_path / "reference").mkdir()

        result = invoke_cli(
            [
                "pipeline",
                "pgs-config-write",
                "--run-dir",
                str(run_dir),
                "--reference-root",
                str(tmp_path / "reference"),
            ]
        )

        assert result.exit_code != 0
        combined = result.stdout + result.stderr
        assert "bam_path" in combined or "manifest" in combined, combined

    def test_json_output_envelope(self, tmp_path: Path, invoke_cli) -> None:
        """pgs-config-write --json emits a well-formed INV-C002 JSON envelope."""
        run_dir = tmp_path / "run06"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps(_MINIMAL_MANIFEST))
        (tmp_path / "reference").mkdir()

        result = invoke_cli(
            [
                "--json",
                "pipeline",
                "pgs-config-write",
                "--run-dir",
                str(run_dir),
                "--reference-root",
                str(tmp_path / "reference"),
            ]
        )

        assert result.exit_code == 0, result.stderr
        envelope = result.stdout_json()
        assert envelope["payload"]["sample_id"] == "TEST001"
        assert "sidecar_path" in envelope["payload"]
        assert "run_dir" in envelope["payload"]

    def test_write_is_idempotent_via_cli(self, tmp_path: Path, invoke_cli) -> None:
        """Second invocation of pgs-config-write overwrites sidecar without error (INV-R001)."""
        run_dir = tmp_path / "run07"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps(_MINIMAL_MANIFEST))
        (tmp_path / "reference").mkdir()

        for _ in range(2):
            result = invoke_cli(
                [
                    "pipeline",
                    "pgs-config-write",
                    "--run-dir",
                    str(run_dir),
                    "--reference-root",
                    str(tmp_path / "reference"),
                ]
            )
            assert result.exit_code == 0, result.stderr

        cfg = load_prs_compute_config(run_dir)
        assert cfg.sample_id == "TEST001"

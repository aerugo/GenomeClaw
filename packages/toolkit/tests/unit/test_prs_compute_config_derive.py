"""Step B (RED → GREEN) — unit tests for derive_prs_compute_config_from_manifest.

These tests cover INV-D001 (no raw/reference writes), INV-D006 (host-form paths),
and INV-R001 (every required field populated) for the pure derivation function.

Plan: docs/plans/active/investigate-prs-compute-config-missing.md (Phase 2/B)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit.service.pgs_compute_config import (
    PrsComputeConfig,
    derive_prs_compute_config_from_manifest,
    load_prs_compute_config,
    write_prs_compute_config,
)

# Minimal manifest matching the active run's manifest.json structure.
# Uses real-looking host-form paths (INV-D006) — no container-local /mnt/ paths.
_CANONICAL_MANIFEST: dict[object, object] = {
    "run_id": "2026-05-25T19-42-58Z-c88e02",
    "schema_version": "v0.3",
    "sample_id": "MPNRGLQ2K",
    "input": {
        "vcf_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz",
        "vcf_sha256": "abc123",
        "tbi_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz.tbi",
        "tbi_sha256": "def456",
        "reference_path": "/Volumes/Genome_Work/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz",
        "reference_build_inferred": "grch38",
        "bam_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram",
        "bam_sha256": "bam123",
    },
    "created_at": "2026-05-25T19:42:58Z",
}

_REFERENCE_ROOT = Path("/Volumes/Genome_Work/genomeclaw/reference")
_SCRATCH_ROOT = Path("/Volumes/Genome_Work/genomeclaw/_scratch")


class TestDeriveFromManifest:
    """INV-D001, INV-D006, INV-R001: pure function, host-form paths, all fields present."""

    def test_invR001_all_required_fields_present(self) -> None:
        """INV-R001: derivation populates every PrsComputeConfig field."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        expected_fields = {
            "sample_id", "cram_path", "reference_root", "scorefile_root",
            "work_dir_root", "panel_version", "sites_tsv", "alleles_tsv", "fasta",
        }
        assert set(result.keys()) == expected_fields, f"Missing fields: {expected_fields - set(result.keys())}"

    def test_sample_id_taken_from_manifest(self) -> None:
        """sample_id is read from manifest top-level key."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert result["sample_id"] == "MPNRGLQ2K"

    def test_cram_path_from_manifest_bam_path(self) -> None:
        """cram_path is derived from manifest.input.bam_path (host-form CRAM)."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert result["cram_path"] == str(
            Path("/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram")
        )

    def test_invD006_fasta_uses_manifest_reference_path(self) -> None:
        """INV-D006: fasta is taken verbatim from manifest.input.reference_path (host-form)."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert result["fasta"] == "/Volumes/Genome_Work/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz"

    def test_sites_tsv_uses_prs_pca_sites_layout(self) -> None:
        """sites_tsv follows the prs_pca_sites/<panel_version>/pca_sites.tsv convention."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        expected = str(_REFERENCE_ROOT / "prs_pca_sites" / "v1" / "pca_sites.tsv")
        assert result["sites_tsv"] == expected

    def test_alleles_tsv_uses_prs_pca_sites_layout(self) -> None:
        """alleles_tsv follows the prs_pca_sites/<panel_version>/pca_alleles.tsv convention."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        expected = str(_REFERENCE_ROOT / "prs_pca_sites" / "v1" / "pca_alleles.tsv")
        assert result["alleles_tsv"] == expected

    def test_scorefile_root_is_reference_pgs_scorefile(self) -> None:
        """scorefile_root is <reference_root>/pgs_scorefile."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert result["scorefile_root"] == str(_REFERENCE_ROOT / "pgs_scorefile")

    def test_work_dir_root_is_under_scratch(self) -> None:
        """work_dir_root is under scratch_root (not under derived/ or reference/)."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert result["work_dir_root"].startswith(str(_SCRATCH_ROOT))

    def test_panel_version_default_is_v1(self) -> None:
        """Default panel_version is 'v1'."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert result["panel_version"] == "v1"

    def test_panel_version_can_be_overridden(self) -> None:
        """panel_version override flows into sites_tsv + alleles_tsv paths."""
        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
            panel_version="v2",
        )
        assert result["panel_version"] == "v2"
        assert "v2" in result["sites_tsv"]
        assert "v2" in result["alleles_tsv"]

    def test_invD006_container_local_reference_path_raises(self) -> None:
        """INV-D006: container-local reference_path (/mnt/...) raises ValueError."""
        bad_manifest = {
            **_CANONICAL_MANIFEST,
            "input": {
                **_CANONICAL_MANIFEST["input"],  # type: ignore[arg-type]
                "reference_path": "/mnt/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz",
            },
        }
        with pytest.raises(ValueError, match="container-local"):
            derive_prs_compute_config_from_manifest(
                bad_manifest,
                reference_root=_REFERENCE_ROOT,
                scratch_root=_SCRATCH_ROOT,
            )

    def test_missing_bam_path_raises_key_error(self) -> None:
        """Missing bam_path in manifest raises KeyError (fail-fast, not silent None)."""
        bad_manifest = {
            **_CANONICAL_MANIFEST,
            "input": {
                k: v
                for k, v in _CANONICAL_MANIFEST["input"].items()  # type: ignore[union-attr]
                if k != "bam_path"
            },
        }
        with pytest.raises(KeyError):
            derive_prs_compute_config_from_manifest(
                bad_manifest,
                reference_root=_REFERENCE_ROOT,
                scratch_root=_SCRATCH_ROOT,
            )

    def test_result_is_loadable_by_load_prs_compute_config(self, tmp_path: Path) -> None:
        """Round-trip: derive → write → load_prs_compute_config returns a valid dataclass."""
        import json

        result = derive_prs_compute_config_from_manifest(
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        (tmp_path / "prs_compute_config.json").write_text(json.dumps(result))

        cfg = load_prs_compute_config(tmp_path)
        assert isinstance(cfg, PrsComputeConfig)
        assert cfg.sample_id == "MPNRGLQ2K"
        assert cfg.fasta == Path("/Volumes/Genome_Work/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz")
        assert cfg.sites_tsv == Path("/Volumes/Genome_Work/genomeclaw/reference/prs_pca_sites/v1/pca_sites.tsv")


class TestWritePrsComputeConfig:
    """Step B writer: write_prs_compute_config → file exists + is loadable."""

    def test_invR001_sidecar_written_and_loadable(self, tmp_path: Path) -> None:
        """INV-R001: write_prs_compute_config writes a valid sidecar to run_dir."""
        sidecar = write_prs_compute_config(
            tmp_path,
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert sidecar.exists(), f"sidecar not written at {sidecar}"
        assert sidecar.name == "prs_compute_config.json"

        cfg = load_prs_compute_config(tmp_path)
        assert isinstance(cfg, PrsComputeConfig)
        assert cfg.sample_id == "MPNRGLQ2K"

    def test_invD001_write_target_is_under_run_dir_not_raw(self, tmp_path: Path) -> None:
        """INV-D001: sidecar is written under run_dir (derived/), never under raw/."""
        sidecar = write_prs_compute_config(
            tmp_path,
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        assert sidecar.parent == tmp_path

    def test_write_is_idempotent(self, tmp_path: Path) -> None:
        """write_prs_compute_config is idempotent: second call overwrites cleanly."""
        write_prs_compute_config(
            tmp_path,
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=_SCRATCH_ROOT,
        )
        # Second call with different scratch_root to confirm overwrite.
        write_prs_compute_config(
            tmp_path,
            _CANONICAL_MANIFEST,
            reference_root=_REFERENCE_ROOT,
            scratch_root=Path("/different/scratch"),
        )
        cfg = load_prs_compute_config(tmp_path)
        assert "/different/scratch" in str(cfg.work_dir_root)

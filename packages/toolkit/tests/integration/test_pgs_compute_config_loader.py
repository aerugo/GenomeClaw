"""Phase 4 RED — pin the prs_compute_config.json sidecar contract.

The E.3 worker (Phase 3) drains the queue but has no real compute. Phase 4
wires it to ``compute_prs_with_coverage_fill(...)`` — which needs the
sample's CRAM path, reference root, scorefile root, fasta, etc. These are
host-form paths baked into ``bin/genomeclaw-prs-smoke`` as env vars in
the manual-driver path; the worker reads them from a
``prs_compute_config.json`` sidecar in the active run-dir.

The sidecar is **one-time-per-deployment** configuration. The host service
reads it at startup; if missing or malformed, the service logs a clear
warning + skips spawning the worker (Phase 4) — read routes still work.

Plan: [docs/plans/active/agent-prs-compute-fix/phases/phase-4.md](../../../../docs/plans/active/agent-prs-compute-fix/phases/phase-4.md)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.service.pgs_compute_config import (
    PrsComputeConfig,
    PrsComputeConfigMalformedError,
    PrsComputeConfigMissingError,
    load_prs_compute_config,
)

_CANONICAL_CONFIG = {
    "sample_id": "MPNRGLQ2K",
    "cram_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.cram",
    "reference_root": "/Volumes/Genome_Work/genomeclaw/reference",
    "scorefile_root": "/Volumes/Genome_Work/genomeclaw/reference/pgs_scorefile",
    "work_dir_root": "/Volumes/Genome_Work/genomeclaw/_scratch/pgs-work",
    "panel_version": "v1",
    "sites_tsv": "/Volumes/Genome_Work/genomeclaw/reference/coverage/v1/sites.tsv",
    "alleles_tsv": "/Volumes/Genome_Work/genomeclaw/reference/coverage/v1/alleles.tsv",
    "fasta": "/Volumes/Genome_Work/genomeclaw/reference/grch38/genome.fa",
}


def test_compute_config_loader_reads_canonical_sidecar(tmp_path: Path) -> None:
    """Happy path: a well-formed sidecar produces a typed ``PrsComputeConfig``."""
    (tmp_path / "prs_compute_config.json").write_text(json.dumps(_CANONICAL_CONFIG))

    cfg = load_prs_compute_config(tmp_path)

    assert isinstance(cfg, PrsComputeConfig)
    assert cfg.sample_id == "MPNRGLQ2K"
    assert cfg.cram_path == Path(_CANONICAL_CONFIG["cram_path"])
    assert cfg.reference_root == Path(_CANONICAL_CONFIG["reference_root"])
    assert cfg.scorefile_root == Path(_CANONICAL_CONFIG["scorefile_root"])
    assert cfg.work_dir_root == Path(_CANONICAL_CONFIG["work_dir_root"])
    assert cfg.panel_version == "v1"
    assert cfg.sites_tsv == Path(_CANONICAL_CONFIG["sites_tsv"])
    assert cfg.alleles_tsv == Path(_CANONICAL_CONFIG["alleles_tsv"])
    assert cfg.fasta == Path(_CANONICAL_CONFIG["fasta"])


def test_compute_config_loader_missing_file_raises_with_canonical_path(tmp_path: Path) -> None:
    """No sidecar → ``PrsComputeConfigMissingError`` whose message names the path."""
    with pytest.raises(PrsComputeConfigMissingError) as exc_info:
        load_prs_compute_config(tmp_path)

    msg = str(exc_info.value)
    assert "prs_compute_config.json" in msg, msg
    assert str(tmp_path) in msg, msg


def test_compute_config_loader_malformed_json_raises(tmp_path: Path) -> None:
    """Invalid JSON → ``PrsComputeConfigMalformedError``."""
    (tmp_path / "prs_compute_config.json").write_text("{not valid json")

    with pytest.raises(PrsComputeConfigMalformedError) as exc_info:
        load_prs_compute_config(tmp_path)

    assert "prs_compute_config.json" in str(exc_info.value)


def test_compute_config_loader_missing_required_field_raises(tmp_path: Path) -> None:
    """JSON missing ``cram_path`` → ``PrsComputeConfigMalformedError`` names the field."""
    partial = dict(_CANONICAL_CONFIG)
    del partial["cram_path"]
    (tmp_path / "prs_compute_config.json").write_text(json.dumps(partial))

    with pytest.raises(PrsComputeConfigMalformedError) as exc_info:
        load_prs_compute_config(tmp_path)

    assert "cram_path" in str(exc_info.value), str(exc_info.value)

"""Pydantic model for ``manifest.json``.

The manifest is one of two per-run JSON artifacts (the other is
``provenance.json``) the host service reads to advertise the active run's
identity, schema version, and tool versions. Per Phase 2 / spec Q5, the
manifest also carries a ``qc.bcftools_stats`` block populated at ingest.

The model is strict: unknown top-level fields are refused.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ManifestInput(BaseModel):
    """Identity of the source artifacts that produced this run."""

    model_config = ConfigDict(extra="forbid")

    vcf_path: str
    vcf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tbi_path: str | None = None
    tbi_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bam_path: str | None = None
    bam_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bai_path: str | None = None
    bai_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reference_path: str
    reference_build_inferred: str


class ManifestOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    derived_dir: str
    variants_table: str
    normalized_vcf: str | None = None
    """Filename of the normalized VCF inside the run dir; populated by
    Phase 3's ``normalize`` step (``normalized.vcf.gz``)."""
    normalized_vcf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    normalized_tbi_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    annotated_vcf: str | None = None
    """Filename of the annotated VCF inside the run dir; populated by
    Phase 4A's ``annotate`` step (``annotated.vcf.gz``)."""
    annotated_vcf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    annotated_tbi_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BcftoolsStatsSummary(BaseModel):
    """Summary fields parsed out of ``bcftools stats`` (per spec Q5 / case 19)."""

    model_config = ConfigDict(extra="forbid")

    ts_tv_ratio: float = Field(ge=0)
    n_snps: int = Field(ge=0)
    n_indels: int = Field(ge=0)


class ManifestQC(BaseModel):
    """QC summaries written into the manifest at ingest time."""

    model_config = ConfigDict(extra="forbid")

    bcftools_stats: BcftoolsStatsSummary


class Manifest(BaseModel):
    """Top-level model for ``manifest.json``."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    schema_version: str
    sample_id: str
    input: ManifestInput
    tools: dict[str, str] = Field(default_factory=dict)
    params: dict[str, object] = Field(default_factory=dict)
    outputs: ManifestOutputs
    created_at: datetime
    qc: ManifestQC | None = None
    image_digest: str | None = None
    """Optional sha256 digest of the genomeclaw/toolkit image when ingest ran
    inside Docker. ``None`` when running native (per Phase 2 follow-up #2)."""


__all__ = [
    "BcftoolsStatsSummary",
    "Manifest",
    "ManifestInput",
    "ManifestOutputs",
    "ManifestQC",
]

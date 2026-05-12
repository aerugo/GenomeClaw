"""``genomeclaw pipeline annotate-vcfanno`` orchestration (Phase 4C).

Operates on an existing ``derived/<run-id>/`` from a prior ``normalize``:

1. Reads ``manifest.json`` to find ``normalized.vcf.gz``.
2. Resolves ClinVar / gnomAD-exomes / dbSNP under ``<reference_dir>/``:
   - ClinVar: ``clinvar/<release>/clinvar.vcf.gz`` (auto-pick newest).
   - gnomAD-exomes: ``gnomad-exomes/<release>/by_chrom/chr<N>.vcf.bgz``
     for each chrom present.
   - dbSNP: ``dbsnp/<release>/dbsnp.vcf.gz`` (auto-pick newest).
3. Stages each source into the shard's scratch dir, renaming ClinVar's
   numeric contigs (``1`` / ``17``) to chr-prefixed (``chr1`` / ``chr17``)
   so they line up with the user VCF's GRCh38 chr-prefixed names.
4. Builds a vcfanno TOML config: 1 ClinVar block + 1 dbSNP block + one
   block per gnomAD-exomes per-chrom file.
5. Runs ``vcfanno`` via the wrapper; bgzips + tabix-indexes the result.
6. ``atomic_promote``s the output into ``run_dir/vcfanno.vcf.gz`` + ``.tbi``.
7. Updates ``manifest.outputs.vcfanno_vcf`` + sha256.
8. Appends a ``vcfanno`` step to ``provenance.json`` capturing each
   overlay's path + sha256 + the inline TOML config.

Phase 4C migrates the Phase-4A ``bcftools annotate`` ClinVar overlay
to vcfanno; the Phase-4A path remains in ``annotate.py`` until 4C.3's
parent-orchestrator rewrite removes it.

`INV-D001`: reference overlay files are read-only; the staged copies
in scratch are the only mutations (a chr-rename + tabix-reindex of the
ClinVar staged copy). `INV-D003`: heavy intermediates land under
``_scratch/<step>/<run_id>/``; the final ``vcfanno.vcf.gz`` is the
only thing that crosses into ``derived/``, via ``atomic_promote(...)``.
`INV-R001`: provenance step records every overlay's path + sha256 +
the full inline TOML config so a rerun against the same overlay SHAs
reproduces byte-equivalent annotation columns.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._bcftools import (
    bcftools_index_tbi,
    bcftools_run,
)
from genomeclaw_toolkit.prep._vcfanno import (
    VcfannoConfig,
    build_vcfanno_toml,
    run_vcfanno,
    vcfanno_version,
)
from genomeclaw_toolkit.prep.scratch import atomic_promote, shard_scratch

log = logging.getLogger(__name__)


# Numeric → chr-prefixed contig map for ClinVar staging. ClinVar's
# canonical GRCh38 VCF uses numeric contig names ("1", "17") while
# consumer-genomics VCFs (Nebula, 23andMe) use chr-prefixed names
# ("chr1", "chr17"). vcfanno matches contigs by exact name, so without
# renaming one side we get zero overlaps. We rename ClinVar at staging
# time rather than the user VCF: the staged copy is ephemeral, the
# user's normalized VCF stays canonical.
_CLINVAR_TO_GRCH38_CHR_MAP = (
    "\n".join([*(f"{i}\tchr{i}" for i in range(1, 23)), "X\tchrX", "Y\tchrY", "MT\tchrM"]) + "\n"
)


# gnomAD v4 INFO fields → project-canonical column names. The popmax
# fields in the exomes-only sites VCF are ``grpmax`` / ``AF_grpmax``
# (verified 2026-05-11 against ``gs://gcp-public-data--gnomad/release/
# 4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz``). The
# ``_joint`` suffix only exists in gnomAD's separate joint exomes+
# genomes frequency dataset, not in the exomes-only sites VCF we
# ship in v0 (per phase-4.md Q8.1). Per-population AFs use ``AF_<pop>``.
_GNOMAD_FIELDS: tuple[str, ...] = (
    "AF_grpmax",
    "grpmax",
    "AF_afr",
    "AF_amr",
    "AF_eas",
    "AF_nfe",
    "AF_sas",
)
_GNOMAD_NAMES: tuple[str, ...] = (
    "gnomad_af_popmax",
    "gnomad_af_popmax_pop",
    "gnomad_af_afr",
    "gnomad_af_amr",
    "gnomad_af_eas",
    "gnomad_af_nfe",
    "gnomad_af_sas",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialise_for_json(value: object) -> object:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unserialisable: {value!r}")


def _resolve_newest_release(
    reference_dir: Path, source: str, *, expected_filename: str | None = None
) -> Path:
    """Pick the lexicographically-largest release dir under ``<reference_dir>/<source>/``.

    For ``YYYY-MM`` / ``YYYY-MM-DD`` / ``vMAJOR.MINOR`` / ``b<NUM>`` release
    schemes, lex-largest is the newest. Returns the release dir; the
    caller resolves the specific file inside it.
    """
    source_root = reference_dir / source
    if not source_root.exists():
        raise FileNotFoundError(
            f"{source} reference dir not found: {source_root}; "
            f"run `genomeclaw refs fetch --source {source} --release <release>` first"
        )
    releases = sorted(p.name for p in source_root.iterdir() if p.is_dir())
    if not releases:
        raise FileNotFoundError(
            f"no {source} releases under {source_root}; "
            f"run `genomeclaw refs fetch --source {source} --release <release>` first"
        )
    return source_root / releases[-1]


def _resolve_clinvar(reference_dir: Path, release: str | None) -> Path:
    base = (
        reference_dir / "clinvar" / release
        if release is not None
        else _resolve_newest_release(reference_dir, "clinvar")
    )
    candidate = base / "clinvar.vcf.gz"
    if not candidate.exists():
        raise FileNotFoundError(f"clinvar.vcf.gz not found: {candidate}")
    return candidate


def _resolve_dbsnp(reference_dir: Path, release: str | None) -> Path:
    base = (
        reference_dir / "dbsnp" / release
        if release is not None
        else _resolve_newest_release(reference_dir, "dbsnp")
    )
    candidate = base / "dbsnp.vcf.gz"
    if not candidate.exists():
        raise FileNotFoundError(f"dbsnp.vcf.gz not found: {candidate}")
    return candidate


def _resolve_gnomad_exomes_per_chrom(reference_dir: Path, release: str | None) -> list[Path]:
    """Return the list of per-chrom gnomAD-exomes .vcf.bgz files present on disk.

    Per the cram-scratch-strategy plan's gnomAD layout (Phase 4C),
    files live under ``gnomad-exomes/<release>/by_chrom/chr<N>.vcf.bgz``.
    For test fixtures the chrom set may be a subset; the orchestrator
    annotates against whichever files are present.
    """
    base = (
        reference_dir / "gnomad-exomes" / release
        if release is not None
        else _resolve_newest_release(reference_dir, "gnomad-exomes")
    )
    by_chrom = base / "by_chrom"
    if not by_chrom.exists():
        raise FileNotFoundError(
            f"gnomad-exomes by_chrom/ dir not found: {by_chrom}; "
            "run `genomeclaw refs fetch --source gnomad-exomes --release <release>` first"
        )
    files = sorted(by_chrom.glob("chr*.vcf.bgz"))
    if not files:
        raise FileNotFoundError(f"no gnomad-exomes per-chrom files under {by_chrom}")
    return files


def _stage_clinvar_with_chr_rename(*, source: Path, scratch: Path) -> Path:
    """Stage ClinVar into scratch, renaming numeric contigs → chr-prefixed.

    Always runs the rename: ``bcftools annotate --rename-chrs`` is a no-op
    when the contigs are already chr-prefixed (the map's left column
    doesn't match), so this is safe both for the canonical NCBI shape
    and for already-renamed test fixtures.
    """
    src_tbi = source.with_suffix(source.suffix + ".tbi")
    if not src_tbi.exists():
        raise FileNotFoundError(f"clinvar tabix index missing: {src_tbi}")

    work_clinvar = scratch / "clinvar.vcf.gz"
    work_clinvar_tbi = scratch / "clinvar.vcf.gz.tbi"
    shutil.copyfile(source, work_clinvar)
    shutil.copyfile(src_tbi, work_clinvar_tbi)

    chr_map = scratch / "clinvar_chr_rename.tsv"
    chr_map.write_text(_CLINVAR_TO_GRCH38_CHR_MAP)
    renamed = scratch / "clinvar.renamed.vcf.gz"
    bcftools_run(
        [
            "annotate",
            "--rename-chrs",
            str(chr_map),
            "-O",
            "z",
            "-o",
            str(renamed),
            str(work_clinvar),
        ]
    )
    bcftools_index_tbi(vcf=renamed, derived_dir=scratch)
    return renamed


def annotate_vcfanno(
    *,
    run_dir: Path,
    reference_dir: Path,
    clinvar_release: str | None = None,
    gnomad_exomes_release: str | None = None,
    dbsnp_release: str | None = None,
    started_at: datetime | None = None,
) -> Path:
    """Annotate the run's normalized VCF via vcfanno + ClinVar / gnomAD / dbSNP.

    Args:
        run_dir: an existing ``derived/<run-id>/`` from a prior
            ``ingest`` + ``normalize``. Must contain ``normalized.vcf.gz``.
        reference_dir: the toolkit's reference root.
        clinvar_release: optional release tag (e.g. ``"2026-05-09"``).
            When None, picks the lex-largest dir under
            ``<ref>/clinvar/``.
        gnomad_exomes_release: optional release tag (e.g. ``"v4.1"``).
            When None, picks the lex-largest dir under
            ``<ref>/gnomad-exomes/``.
        dbsnp_release: optional release tag (e.g. ``"b157"``). When
            None, picks the lex-largest dir under ``<ref>/dbsnp/``.
        started_at: optional fixed UTC timestamp; defaults to
            ``datetime.now(tz=UTC)``.

    Returns:
        Path to the freshly-written ``run_dir/vcfanno.vcf.gz``.
    """
    preflight.assert_raw_readonly()
    preflight.assert_reference_readonly()
    preflight.assert_derived_writable()
    preflight.assert_scratch_writable()

    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in run dir: {run_dir}")

    norm_vcf = run_dir / "normalized.vcf.gz"
    if not norm_vcf.exists():
        raise FileNotFoundError(
            f"normalized.vcf.gz not found in {run_dir}; run `genomeclaw pipeline normalize` first"
        )

    if started_at is None:
        started_at = datetime.now(tz=UTC)
    log.info("annotate-vcfanno starting: run_dir=%s", run_dir)

    clinvar_vcf = _resolve_clinvar(reference_dir, clinvar_release)
    dbsnp_vcf = _resolve_dbsnp(reference_dir, dbsnp_release)
    gnomad_files = _resolve_gnomad_exomes_per_chrom(reference_dir, gnomad_exomes_release)
    log.info(
        "annotate-vcfanno resolved overlay sources: "
        "clinvar=%s dbsnp=%s gnomad_exomes=%d chrom files",
        clinvar_vcf.name,
        dbsnp_vcf.name,
        len(gnomad_files),
    )

    # SHA256 every overlay source for provenance. The 24 gnomAD-exomes
    # chrom files total ~200 GB, so this phase takes several minutes on
    # real-scale data — flag it explicitly so the run doesn't look
    # stalled.
    log.info(
        "annotate-vcfanno hashing %d overlay sources for provenance "
        "(can take ~5min on real-scale gnomad-exomes)",
        2 + len(gnomad_files),
    )
    clinvar_sha = _sha256_file(clinvar_vcf)
    log.info("annotate-vcfanno hashed clinvar")
    dbsnp_sha = _sha256_file(dbsnp_vcf)
    log.info("annotate-vcfanno hashed dbsnp")
    gnomad_shas: dict[Path, str] = {}
    for i, p in enumerate(gnomad_files, start=1):
        gnomad_shas[p] = _sha256_file(p)
        log.info("annotate-vcfanno hashed gnomad chrom %d/%d (%s)", i, len(gnomad_files), p.name)
    norm_vcf_sha = _sha256_file(norm_vcf)

    output_vcf = run_dir / "vcfanno.vcf.gz"
    # Scratch base: sibling of derived/, matching both production (the
    # shim bind-mounts /mnt/genomeclaw/{derived,scratch} as siblings)
    # and the test layout (the genomeclaw_layout fixture lays out
    # tmp/{derived,scratch}). Using ``run_dir.parent.parent / "scratch"``
    # rather than shard_scratch's hardcoded ``/mnt/genomeclaw/scratch``
    # default lets the same orchestrator code path serve both contexts
    # without the test harness having to fix ownership on the container's
    # ``/mnt/genomeclaw/scratch`` (which is ``chown genomeclaw`` in the
    # toolkit image and unwritable from a host-UID --user invocation).
    scratch_base = run_dir.parent.parent / "scratch"
    with shard_scratch(step="annotate-vcfanno", run_id=run_dir.name, base=scratch_base) as scratch:
        log.info("annotate-vcfanno staging inputs to %s", scratch)
        clinvar_staged = _stage_clinvar_with_chr_rename(source=clinvar_vcf, scratch=scratch)
        log.info("annotate-vcfanno staged clinvar with chr-prefix rename: %s", clinvar_staged.name)

        configs: tuple[VcfannoConfig, ...] = (
            VcfannoConfig(
                file=clinvar_staged,
                fields=("CLNSIG", "CLNREVSTAT"),
                names=("clinvar_classification", "clinvar_review_status"),
                ops=("self", "self"),
            ),
            *(
                VcfannoConfig(
                    file=p,
                    fields=_GNOMAD_FIELDS,
                    names=_GNOMAD_NAMES,
                    ops=tuple(["self"] * len(_GNOMAD_FIELDS)),
                )
                for p in gnomad_files
            ),
            VcfannoConfig(
                file=dbsnp_vcf,
                fields=("RS",),
                names=("dbsnp_rsid",),
                ops=("self",),
            ),
        )
        config_toml = build_vcfanno_toml(configs)

        work_output = scratch / "vcfanno.vcf.gz"
        log.info(
            "annotate-vcfanno running vcfanno over %d overlay sources "
            "(this is the slow step; vcfanno's own progress streams below)",
            len(configs),
        )
        run_vcfanno(
            input_vcf=norm_vcf,
            output_vcf=work_output,
            config_toml=config_toml,
            work_dir=scratch,
        )
        log.info("annotate-vcfanno vcfanno complete; indexing output")
        work_output_tbi = bcftools_index_tbi(vcf=work_output, derived_dir=scratch)

        log.info("annotate-vcfanno promoting outputs to %s", run_dir)
        atomic_promote(src=work_output, dst=output_vcf)
        atomic_promote(src=work_output_tbi, dst=run_dir / "vcfanno.vcf.gz.tbi")

    output_sha = _sha256_file(output_vcf)
    completed_at = datetime.now(tz=UTC)

    # Append step to provenance.json.
    provenance_path = run_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    vcfanno_version_str = vcfanno_version()
    inputs: list[dict[str, Any]] = [
        {"path": str(norm_vcf), "sha256": norm_vcf_sha},
        {"path": str(clinvar_vcf), "sha256": clinvar_sha},
        {"path": str(dbsnp_vcf), "sha256": dbsnp_sha},
        *({"path": str(p), "sha256": gnomad_shas[p]} for p in gnomad_files),
    ]
    provenance["steps"].append(
        {
            "step": "vcfanno",
            "tool": "vcfanno",
            "tool_version": vcfanno_version_str,
            "started_at": started_at,
            "completed_at": completed_at,
            "inputs": inputs,
            "outputs": [{"path": "vcfanno.vcf.gz", "sha256": output_sha}],
            "params": {"config": config_toml},
        }
    )
    provenance_path.write_text(json.dumps(provenance, indent=2, default=_serialise_for_json) + "\n")

    # Update manifest.json with the vcfanno output identity.
    manifest = json.loads(manifest_path.read_text())
    manifest["outputs"]["vcfanno_vcf"] = "vcfanno.vcf.gz"
    manifest["outputs"]["vcfanno_vcf_sha256"] = output_sha
    manifest_path.write_text(json.dumps(manifest, indent=2, default=_serialise_for_json) + "\n")

    log.info("annotate-vcfanno complete: out=%s", output_vcf)
    return output_vcf


__all__ = ["annotate_vcfanno"]

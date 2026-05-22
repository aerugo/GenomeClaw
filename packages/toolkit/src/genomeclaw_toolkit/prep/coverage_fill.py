"""Two-tier targeted forced-genotyping cache for PRS input coverage fill.

Bridges the gap between Nebula-style variant-only VCFs and ``pgsc_calc``'s
all-sites-VCF assumption (per the [prs-input-coverage-fill plan](../../../../docs/plans/active/prs-input-coverage-fill/development-plan.md)).

Phase 1 ships the Tier 1 primitive: derive REF/REF dosages at the LD-pruned
HGDP+1kGP PCA-eligible sites directly from the user's CRAM via a streaming
``bcftools mpileup → call --constrain alleles → bcftools norm`` pipe. Phase 2
extends the same primitive to per-PGS Tier 2 site lists; the Tier 1 cache
amortises across every subsequent PRS question.

Chr22 prove-out (2026-05-18) measured 99 s wall-clock at 127 MiB peak RAM
against the project owner's 30× CRAM for 6,812 PCA-eligible sites with an
84.5% REF/REF / 9.5% het / 5.1% hom-alt / 0.9% missing distribution at mean
DP 27.98×. Extrapolation to whole-autosome is captured in
[work-notes.md](../../../../docs/plans/active/prs-input-coverage-fill/work-notes.md).

Invariants enforced here:

- ``INV-D001`` — the CRAM is opened read-only; the wrapper writes only under
  ``derived/prs_coverage/<sample>/<panel>/`` and never back to ``raw/``.
- ``INV-D003`` — the in-flight VCF stages in :func:`shard_scratch` under
  :func:`ephemeral_scratch_base`; :func:`atomic_promote` lands it under
  ``derived/`` in a single rename.
- ``INV-R001`` — ``tier1.qc.json`` records the CRAM SHA256, panel version,
  bcftools version, tool command, GT distribution, mean DP, per-chromosome
  record counts, and the schema version, so the cache is rebuildable from
  source + tool pins alone.
- ``INV-P001`` — no network egress; everything runs against on-device
  artefacts.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genomeclaw_toolkit.prep._bcftools import BcftoolsError, bcftools_version
from genomeclaw_toolkit.prep._paths import SiblingMountablePath, as_sibling_mountable
from genomeclaw_toolkit.prep._pgs_qc import (
    CalibrationStatus,
    PRSDeclineError,
    classify_calibration,
)
from genomeclaw_toolkit.prep._pgsc_calc_match import (
    find_pgsc_calc_log_csv,
    parse_match_stats,
)
from genomeclaw_toolkit.prep.pgs import (
    PgsRow,
    apply_calibration_decision,
    compute_pgs,
)
from genomeclaw_toolkit.prep.scratch import (
    atomic_promote,
    ephemeral_scratch_base,
    shard_scratch,
)

# Schema version stamped on every tier1.qc.json + tier2.qc.json + pca_sites
# provenance JSON. Bump when the JSON shape changes incompatibly.
SCHEMA_VERSION = "2"  # v2 (pgs-allele-orientation): tier2.qc.json adds orientation_* counts

# plink2 image pin — matches the version pgsc_calc v2.2.0 pulls in its conda
# profile, so the LD-prune we run here aligns mechanically with pgsc_calc's
# internal FILTER_VARIANTS step. Bump in tandem with the pgsc_calc release
# tracked in :mod:`_versions.PRS_RUNTIME_VERSIONS`.
PLINK2_IMAGE = "ghcr.io/pgscatalog/plink2:2.00a5.10"

# Canonical LD-prune parameters. Aligned with pgsc_calc's internal
# FILTER_VARIANTS so the user's PCA-eligible site set mirrors what
# pgsc_calc's FRAPOSA projection uses internally.
_PRUNE_PARAMS = {
    "maf": 0.01,
    "hwe": 1e-6,
    "geno": 0.05,
    "window_kb": 1000,
    "step": 50,
    "r2": 0.05,
}


class MissingCramIndexError(RuntimeError):
    """The CRAM lacks a sibling ``.crai`` index.

    ``bcftools mpileup --regions-file`` requires the CRAM index to seek to
    target sites; without it the pipe would be a sequential scan of the
    entire 50 GB CRAM (~hours instead of ~minutes). Surfaces a clean
    install hint rather than a raw bcftools error.
    """


class MissingPanelError(RuntimeError):
    """The HGDP+1kGP panel is missing or incomplete under ``panel_root``.

    Surfaces a ``genomeclaw refs fetch --source pgs_catalog_ancestry`` hint
    rather than a raw plink2 error.
    """


class Plink2Error(RuntimeError):
    """plink2 LD-prune subprocess exited non-zero. Stderr captured."""


class SamtoolsError(RuntimeError):
    """samtools faidx subprocess exited non-zero. Stderr captured.

    Surfaces during the per-site reference-base lookup that orients PGS
    sites against the actual reference fasta (pgs-allele-orientation
    plan, F7 from prs-runtime-hardening)."""


# ---------------------------------------------------------------------------
# Allele orientation against fasta (pgs-allele-orientation plan, F7)
# ---------------------------------------------------------------------------


def _parse_faidx_fasta(text: str) -> dict[tuple[str, int], str]:
    """Parse ``samtools faidx -r <regions>`` multi-record output into
    ``{(chrom, pos): base}``.

    samtools format (one record per region):
        >chr1:12345-12345
        A
        >chr1:67890-67890
        C

    Bases are uppercased (samtools may emit lowercase for soft-masked
    regions; the orientation comparison is case-blind).
    """
    out: dict[tuple[str, int], str] = {}
    current_key: tuple[str, int] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            # Header like '>chr1:12345-12345' or '>chr1:12345-12345 extra'.
            spec = line[1:].split()[0]
            chrom, _, range_part = spec.partition(":")
            start_str, _, _ = range_part.partition("-")
            try:
                pos = int(start_str)
            except ValueError:
                current_key = None
                continue
            current_key = (chrom, pos)
        else:
            if current_key is not None:
                # Take the first base; samtools emits one base per request
                # for single-position regions, but be defensive.
                out[current_key] = line[0].upper()
                current_key = None
    return out


def _get_reference_bases(
    fasta_path: Path,
    sites: list[tuple[str, int]],
) -> dict[tuple[str, int], str]:
    """Batch-fetch the reference base at each ``(chrom, pos)`` via a single
    ``samtools faidx <fasta> -r <regions>`` subprocess.

    1.7M sites in a single call is feasible (samtools indexes the .fai for
    O(log n) seek per region); 1.7M individual calls would be infeasible.

    Sites that samtools can't resolve (out-of-range pos, missing contig)
    are absent from the dict — the caller treats those as skipped.
    """
    if not sites:
        return {}
    with shard_scratch(
        step="orient_pgs_sites", run_id=fasta_path.stem, base=ephemeral_scratch_base()
    ) as shard:
        regions_file = shard / "regions.tsv"
        with regions_file.open("w") as fh:
            for chrom, pos in sites:
                fh.write(f"{chrom}:{pos}-{pos}\n")
        proc = subprocess.run(
            ["samtools", "faidx", str(fasta_path), "-r", str(regions_file)],
            capture_output=True,
            check=False,
        )
        stdout_text = proc.stdout.decode("utf-8", errors="replace")
        # samtools faidx returns rc=1 if ANY requested region's contig is
        # missing from the .fai (e.g., scorefile sites on alt contigs like
        # ``chr7_KI270803v1_alt`` that our primary-assembly fasta doesn't
        # have). It still emits stdout records for the successful lookups.
        # Treat rc != 0 as fatal only when stdout is empty — otherwise the
        # orientation step naturally skips missing-from-dict sites.
        if proc.returncode != 0 and not stdout_text.strip():
            stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
            raise SamtoolsError(
                f"samtools faidx bulk lookup failed (rc={proc.returncode}) "
                f"AND produced no stdout records:\n{stderr_text}"
            )
        return _parse_faidx_fasta(stdout_text)


def _orient_pgs_sites_against_fasta(
    rows: list[tuple[str, int, str, str]],
    fasta_path: Path,
) -> tuple[list[tuple[str, int, str, str]], int, int]:
    """Orient PGS sites' (REF, ALT) tuples against the actual reference fasta.

    For each row ``(chrom, pos, other_allele, effect_allele)``:

    - if ``actual_ref == other_allele``: KEEP as-is (REF=other, ALT=effect) —
      the PGS Catalog "convention" assumption holds.
    - if ``actual_ref == effect_allele``: SWAP (REF=effect, ALT=other) — the
      effect allele IS the reference; the wrapper's pre-orientation
      assumption was reversed for this site.
    - else: SKIP (neither allele matches the reference; counted toward
      ``skipped_count``; could be tri-allelic, wrong-build, or strand-issue).

    Returns ``(kept_rows, skipped_count, swapped_count)``. The skipped
    rows are NOT in the returned list; the caller persists the count in
    the QC json so a high skip rate flags a setup issue.

    Phase 7 smoke v17 (2026-05-20) surfaced the absence of this step:
    ``bcftools call --constrain alleles`` rejected every Tier 2 site
    where the wrapper's assumed REF didn't match the fasta. Per-site
    fasta lookup + correct orientation closes the gap.
    """
    if not rows:
        return [], 0, 0
    sites = [(chrom, pos) for (chrom, pos, _, _) in rows]
    ref_bases = _get_reference_bases(fasta_path, sites)
    kept: list[tuple[str, int, str, str]] = []
    skipped = 0
    swapped = 0
    for chrom, pos, other, effect in rows:
        actual_ref = ref_bases.get((chrom, pos), "").upper()
        other_u = other.upper()
        effect_u = effect.upper()
        if not actual_ref:
            skipped += 1
        elif actual_ref == other_u:
            kept.append((chrom, pos, other, effect))  # REF=other, ALT=effect
        elif actual_ref == effect_u:
            kept.append((chrom, pos, effect, other))  # REF=effect, ALT=other (swapped)
            swapped += 1
        else:
            skipped += 1
    return kept, skipped, swapped


# ---------------------------------------------------------------------------
# Pure helpers — no subprocess, no I/O against the toolkit image.
# ---------------------------------------------------------------------------


def _parse_prune_in_to_alleles(lines: Iterable[str]) -> list[tuple[str, int, str, str]]:
    """Convert plink2 prune-in IDs to ``(chr_prefixed_chrom, pos, ref, alt)`` rows.

    plink2 emits variant IDs in the form ``<chrom>:<pos>:<ref>:<alt>`` using
    the panel's chromosome naming (``1, 2, …, 22, X, Y`` for the HGDP+1kGP
    panel — no ``chr`` prefix). The user CRAM + GRCh38 FASTA use the
    ``chrN`` convention, so we rewrite the chromosome here once so the
    downstream bcftools targets/regions files match what mpileup expects.

    Malformed lines (empty, too few/many colons, non-integer position) are
    silently skipped. The chr22 prove-out had zero malformed IDs across
    6,812 records; the skip is defensive against future panel quirks.
    """
    rows: list[tuple[str, int, str, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) != 4:
            continue
        chrom, pos_s, ref, alt = parts
        try:
            pos = int(pos_s)
        except ValueError:
            continue
        rows.append((f"chr{chrom}", pos, ref, alt))
    return rows


def _tier1_cache_path(*, derived_root: Path, sample_id: str, panel_version: str) -> Path:
    """Deterministic Tier 1 cache path.

    Layout: ``<derived_root>/prs_coverage/<sample_id>/<panel_version>/tier1.vcf.gz``.

    This is the contract Phase 2's cache-hit detection in ``prs compute``
    relies on; the doctor probe `_collect_prs_coverage_ready` also lookups
    here. Keep the layout explicit so any future move surfaces as a single
    failure point.
    """
    return derived_root / "prs_coverage" / sample_id / panel_version / "tier1.vcf.gz"


def _gt_normalised(gt: str) -> str:
    """Normalise haploid/phased GT strings to the canonical diploid form.

    ``0|1 → 0/1``, ``1/0 → 0/1`` (canonical heterozygous orientation).
    Other genotypes pass through unchanged so the caller can recognise
    them (or bucket them as 'other').
    """
    normed = gt.replace("|", "/")
    if normed == "1/0":
        return "0/1"
    return normed


def _summarize_tier1_qc(vcf_path: Path) -> dict[str, Any]:
    """Walk a bgzipped tier1 VCF, return a single-pass QC summary.

    The summary keys are the QC slice of ``tier1.qc.json``; the caller adds
    INV-R001 provenance fields (source_cram_sha256, panel_version, tool
    versions, …) before writing the JSON. Empty VCFs return all-zero counts
    without a ZeroDivisionError.
    """
    counts = {"0/0": 0, "0/1": 0, "1/1": 0, "./.": 0}
    per_chrom: dict[str, int] = {}
    dp_sum = 0
    dp_count = 0
    total = 0

    with gzip.open(vcf_path, "rt") as fh:
        for raw_line in fh:
            if not raw_line or raw_line.startswith("#"):
                continue
            line = raw_line.rstrip("\n")
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) < 10:
                continue
            chrom = fields[0]
            fmt = fields[8].split(":")
            sample = fields[9].split(":")
            sample_dict = dict(zip(fmt, sample, strict=False))

            gt = _gt_normalised(sample_dict.get("GT", "./."))
            if gt in counts:
                counts[gt] += 1

            dp_s = sample_dict.get("DP")
            if dp_s and dp_s != ".":
                try:
                    dp_v = int(dp_s)
                except ValueError:
                    dp_v = 0
                if gt != "./.":
                    dp_sum += dp_v
                    dp_count += 1

            per_chrom[chrom] = per_chrom.get(chrom, 0) + 1
            total += 1

    missing_rate = counts["./."] / total if total else 0.0
    mean_dp = dp_sum / dp_count if dp_count else 0.0

    return {
        "total_records": total,
        "gt_distribution": counts,
        "missing_rate": missing_rate,
        "mean_dp": mean_dp,
        "per_chrom_record_counts": per_chrom,
    }


# ---------------------------------------------------------------------------
# bcftools pipe construction + execution
# ---------------------------------------------------------------------------


_BCFTOOLS_PIPE_TEMPLATE = (
    "bcftools mpileup "
    "--fasta-ref {fasta} "
    "--regions-file {sites} "
    "--max-depth 250 --min-BQ 20 --min-MQ 20 "
    "--annotate FORMAT/DP,FORMAT/AD "
    "--output-type u "
    "{cram} "
    "| bcftools call "
    "--multiallelic-caller --keep-alts --constrain alleles "
    "--targets-file {alleles} "
    "--output-type u "
    "| bcftools norm "
    "--fasta-ref {fasta} "
    "--multiallelics -any "
    "--output-type z "
    "--output {output} "
    "&& bcftools index --tbi --force {output}"
)


def _count_vcf_records(vcf_path: Path) -> int:
    """Count non-header records in a bgzipped VCF.

    Cheap walk — reads with gzip and counts lines NOT starting with ``#``.
    Used to guard against the silent-failure pattern where bcftools' pipe
    exits 0 but produces a header-only VCF (chr-prefix mismatch, build
    mismatch, empty sites file, etc.). Without this guard, the wrapper
    happily atomic_promotes the empty result + the cache then serves
    zero records on every subsequent call.

    Phase 7 smoke v15 (2026-05-20) surfaced this: the original Tier 2
    cache had ``total_records=0`` and every smoke iteration re-used it.
    The bcftools pipe exit-0'd cleanly while producing nothing.
    """
    count = 0
    with gzip.open(vcf_path, "rt") as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            if line.strip():
                count += 1
    return count


def _build_bcftools_pipe(
    *,
    cram: Path,
    sites: Path,
    alleles: Path,
    fasta: Path,
    output: Path,
) -> str:
    """Build the shell-glued mpileup → call → norm + index pipe.

    Single ``bash -c`` invocation so the streaming pipe stays in-memory
    (no intermediate disk writes) and so the per-stage stderr can be
    captured together. Each path is interpolated as-is; callers are
    responsible for ensuring paths don't contain shell-special characters
    (they don't in any production layout).
    """
    return _BCFTOOLS_PIPE_TEMPLATE.format(
        cram=cram, sites=sites, alleles=alleles, fasta=fasta, output=output
    )


def _force_genotype_tier1(
    *,
    cram_path: Path,
    sites_tsv: Path,
    alleles_tsv: Path,
    fasta: Path,
    output_vcf: Path,
) -> None:
    """Force-genotype the user at every site in ``sites_tsv``; stage + promote.

    The wrapper:

    1. Verifies the CRAM has a sibling ``.crai`` index (else
       ``MissingCramIndexError`` with a ``samtools index`` hint).
    2. Allocates a :func:`shard_scratch` directory under
       :func:`ephemeral_scratch_base`.
    3. Invokes the mpileup → call → norm pipe targeting the scratch path.
    4. :func:`atomic_promote`s the staged VCF (and its ``.tbi`` sidecar)
       to ``output_vcf`` in the ``derived/`` tree.

    Raises:
        MissingCramIndexError: ``cram_path.crai`` not present.
        BcftoolsError: the bash pipe exited non-zero, or the expected
            staged VCF wasn't produced.
    """
    crai = Path(f"{cram_path}.crai")
    if not crai.exists():
        raise MissingCramIndexError(f"CRAM index missing: {crai}. Run: samtools index {cram_path}")

    output_vcf.parent.mkdir(parents=True, exist_ok=True)

    base = ephemeral_scratch_base()
    # run_id keeps shard_scratch dirs distinct across re-runs of the same
    # sample without colliding with parallel runs. The CRAM stem is a
    # good-enough identifier for the Phase 1 prove-out; Phase 2 wires the
    # actual run-id from the orchestrator.
    run_id = cram_path.stem
    with shard_scratch(step="prs_coverage_tier1", run_id=run_id, base=base) as shard:
        scratch_vcf = shard / "tier1.vcf.gz"
        pipe = _build_bcftools_pipe(
            cram=cram_path,
            sites=sites_tsv,
            alleles=alleles_tsv,
            fasta=fasta,
            output=scratch_vcf,
        )
        proc = subprocess.run(
            ["bash", "-c", pipe],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
            raise BcftoolsError(
                f"tier1 force-genotype pipe failed (rc={proc.returncode}):\n{stderr_text}"
            )
        if not scratch_vcf.exists():
            raise BcftoolsError(f"tier1 pipe completed but staged VCF not found: {scratch_vcf}")

        # Validate the pipe produced records BEFORE caching. A 0-record VCF
        # is a silent-failure pattern (chr-prefix mismatch, build mismatch,
        # empty sites file, etc.) that would otherwise be cached + served
        # on every subsequent call. Phase 7 smoke v15 surfaced this for
        # Tier 2; same guard applied here defensively.
        record_count = _count_vcf_records(scratch_vcf)
        if record_count == 0:
            raise BcftoolsError(
                f"tier1 force-genotype produced ZERO output records despite "
                f"the input sites in {sites_tsv}. The bcftools pipe exited "
                f"cleanly but produced a header-only VCF. Common causes:\n"
                f"  - CRAM uses 'chr' prefix but sites file doesn't (or vice versa)\n"
                f"  - Reference build mismatch (CRAM build != fasta build)\n"
                f"  - Sites file empty or malformed\n"
                f"  - CRAM has no reads at any of the sites\n"
                f"NOT caching empty result; resolve the underlying issue and rerun."
            )

        atomic_promote(scratch_vcf, output_vcf)
        scratch_tbi = shard / "tier1.vcf.gz.tbi"
        if scratch_tbi.exists():
            atomic_promote(scratch_tbi, output_vcf.parent / f"{output_vcf.name}.tbi")


# ---------------------------------------------------------------------------
# Orchestrator + cache-hit semantics
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """SHA256 of ``path`` content in 1 MiB chunks (mirrors ``materialize.py``)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_coverage_tier1(
    *,
    sample_id: str,
    cram_path: Path,
    sites_tsv: Path,
    alleles_tsv: Path,
    fasta: Path,
    panel_version: str,
    output_root: Path,
) -> Path:
    """Build (or return cached) the Tier 1 VCF + tier1.qc.json for one sample.

    Cache-hit semantics: a Tier 1 cache is considered warm when

    1. ``<derived>/prs_coverage/<sample>/<panel>/tier1.vcf.gz`` exists, AND
    2. ``tier1.qc.json`` exists alongside it, AND
    3. ``qc["source_cram_sha256"]`` matches the current CRAM's SHA256.

    A SHA256 mismatch (e.g. the user re-aligned their CRAM) invalidates
    the cache and forces a rebuild. The .crai check happens inside
    :func:`_force_genotype_tier1`.

    Returns the path to the Tier 1 VCF (cached or freshly built).
    """
    cache_vcf = _tier1_cache_path(
        derived_root=output_root, sample_id=sample_id, panel_version=panel_version
    )
    cache_qc = cache_vcf.parent / "tier1.qc.json"

    cram_sha = _sha256_file(cram_path)

    if cache_vcf.exists() and cache_qc.exists():
        try:
            qc_existing = json.loads(cache_qc.read_text())
        except (OSError, json.JSONDecodeError):
            qc_existing = None
        if qc_existing and qc_existing.get("source_cram_sha256") == cram_sha:
            return cache_vcf

    _force_genotype_tier1(
        cram_path=cram_path,
        sites_tsv=sites_tsv,
        alleles_tsv=alleles_tsv,
        fasta=fasta,
        output_vcf=cache_vcf,
    )

    try:
        bversion = bcftools_version().version
    except (FileNotFoundError, BcftoolsError, ValueError):
        # ValueError surfaces when the version banner can't be parsed —
        # e.g. an empty stdout from a stubbed subprocess in tests. Treat
        # the same as "bcftools unavailable" rather than failing the cache
        # build over a provenance detail.
        bversion = "unavailable"

    summary = _summarize_tier1_qc(cache_vcf)
    qc_blob: dict[str, Any] = {
        "sample_id": sample_id,
        "source_cram_path": str(cram_path),
        "source_cram_sha256": cram_sha,
        "panel_version": panel_version,
        "bcftools_version": bversion,
        "tool_command": (
            "bcftools mpileup -R sites | bcftools call -C alleles -T alleles "
            "| bcftools norm -m -any"
        ),
        **summary,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": SCHEMA_VERSION,
    }
    cache_qc.write_text(json.dumps(qc_blob, indent=2))
    return cache_vcf


# ---------------------------------------------------------------------------
# Tier 1 — one-time-per-panel PCA-eligible site materialisation (plink2 LD-prune)
# ---------------------------------------------------------------------------


def _build_plink2_argv(*, panel_prefix: Path, out_prefix: Path) -> list[str]:
    """Build the ``docker run … plink2 …`` argv for the LD-prune step.

    Runs plink2 via DooD against :data:`PLINK2_IMAGE` (linux/amd64) because
    plink2 2.0a5.10 isn't packaged on linux/arm64 conda-forge — the chr22
    prove-out (2026-05-18) used the same path.

    Mounts the panel root + the out_prefix's parent at identical paths
    inside the container so plink2's absolute-path arguments resolve
    cleanly through DooD on Apple Silicon.
    """
    mounts = [
        "-v",
        f"{panel_prefix.parent}:{panel_prefix.parent}",
        "-v",
        f"{out_prefix.parent}:{out_prefix.parent}",
    ]
    return [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        *mounts,
        PLINK2_IMAGE,
        "plink2",
        "--pfile",
        str(panel_prefix),
        "vzs",
        "--maf",
        str(_PRUNE_PARAMS["maf"]),
        "--hwe",
        # NB: Python's ``str(1e-6) == "1e-06"`` adds a leading zero in the
        # exponent. plink2 accepts both forms but the chr22 prove-out
        # command line + the canonical plink2 examples both use ``1e-6``,
        # so emit the literal to keep the wire format human-readable.
        "1e-6",
        "--geno",
        str(_PRUNE_PARAMS["geno"]),
        "--indep-pairwise",
        str(_PRUNE_PARAMS["window_kb"]),
        str(_PRUNE_PARAMS["step"]),
        str(_PRUNE_PARAMS["r2"]),
        "--memory",
        "8000",
        "--threads",
        "4",
        "--out",
        str(out_prefix),
    ]


def _materialize_pca_sites(
    *,
    panel_root: Path,
    output_root: Path,
    panel_version: str,
    panel_build: str = "GRCh38",
) -> Path:
    """Build the PCA-eligible sites + alleles TSV pair for one panel release.

    Runs plink2 LD-prune against the HGDP+1kGP panel under ``panel_root``,
    parses the prune-in IDs (which use the panel's bare-chrom naming),
    rewrites to the CRAM ``chrN`` convention, and emits two plaintext
    tab-separated files under ``output_root/<panel_version>/``:

    - ``pca_sites.tsv`` — two columns (``chrom``, ``pos``) — consumed by
      ``bcftools mpileup --regions-file``.
    - ``pca_alleles.tsv`` — three columns (``chrom``, ``pos``,
      ``ref,alt``) — consumed by ``bcftools call --constrain alleles
      --targets-file``.

    A sidecar ``pca_sites.provenance.json`` records the panel SHA256,
    plink2 image pin, prune parameters, and prune-in count + SHA256 so
    the cache is rebuildable from inputs alone (INV-R001).

    Returns the path to ``pca_sites.tsv`` (the canonical anchor).

    Raises:
        MissingPanelError: when the panel's ``pvar.zst`` is absent.
        Plink2Error: when the plink2 subprocess exits non-zero.
    """
    panel_prefix = panel_root / f"{panel_build}_HGDP+1kGP_ALL"
    panel_pvar = panel_prefix.with_suffix(".pvar.zst")
    if not panel_pvar.exists():
        raise MissingPanelError(
            f"HGDP+1kGP panel pvar missing: {panel_pvar}. "
            "Install with: genomeclaw refs fetch --source pgs_catalog_ancestry"
        )

    panel_out = output_root / panel_version
    panel_out.mkdir(parents=True, exist_ok=True)

    # plink2 writes <out>.prune.in / .prune.out / .log under the prefix dir.
    plink_prefix = panel_out / "pca"
    argv = _build_plink2_argv(panel_prefix=panel_prefix, out_prefix=plink_prefix)
    proc = subprocess.run(argv, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise Plink2Error(f"plink2 LD-prune failed (rc={proc.returncode}):\n{stderr_text}")

    prune_in_path = plink_prefix.with_suffix(plink_prefix.suffix + ".prune.in")
    if not prune_in_path.exists():
        raise Plink2Error(f"plink2 returned rc=0 but produced no prune-in file: {prune_in_path}")

    prune_in_lines = prune_in_path.read_text().splitlines()
    rows = _parse_prune_in_to_alleles(prune_in_lines)

    sites_path = panel_out / "pca_sites.tsv"
    alleles_path = panel_out / "pca_alleles.tsv"
    with sites_path.open("w") as fh_sites, alleles_path.open("w") as fh_alleles:
        for chrom, pos, ref, alt in rows:
            fh_sites.write(f"{chrom}\t{pos}\n")
            fh_alleles.write(f"{chrom}\t{pos}\t{ref},{alt}\n")

    panel_sha = _sha256_file(panel_pvar)
    prune_sha = _sha256_file(prune_in_path)
    provenance = {
        "panel_root": str(panel_root),
        "panel_version": panel_version,
        "panel_build": panel_build,
        "panel_pvar_sha256": panel_sha,
        "plink2_image": PLINK2_IMAGE,
        "prune_params": _PRUNE_PARAMS,
        "prune_in_count": len(rows),
        "prune_in_sha256": prune_sha,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": SCHEMA_VERSION,
    }
    (panel_out / "pca_sites.provenance.json").write_text(json.dumps(provenance, indent=2))

    return sites_path


# ---------------------------------------------------------------------------
# Tier 2 — per-PGS forced-genotyping at scoring-file sites
# ---------------------------------------------------------------------------


def _extract_pgs_id_from_scorefile(scorefile_path: Path) -> str:
    """Return the PGS Catalog ID from a scoring file's ``#pgs_id=`` header.

    Reads the (gzipped or plain) header section until the first non-``#``
    line. Raises ``ValueError`` when no ``#pgs_id=`` is found — the cache
    key cannot be computed without it.
    """
    opener = gzip.open if str(scorefile_path).endswith(".gz") else open
    with opener(scorefile_path, "rt") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("#"):
                break
            if stripped.startswith("#pgs_id="):
                return stripped.split("=", 1)[1].strip()
    raise ValueError(f"no #pgs_id= header found in scoring file: {scorefile_path}")


def _extract_pgs_sites_from_scorefile(
    scorefile_path: Path,
) -> list[tuple[str, int, str, str]]:
    """Parse a PGS Catalog hmPOS_GRCh38 scoring file → SNP-only ``(chrN, pos, ref, alt)`` rows.

    Skips comment / blank lines. Parses the column header to locate
    ``hm_chr`` (or ``chr_name``), ``hm_pos`` (or ``chr_position``),
    ``effect_allele``, ``other_allele``. SNP filter per Phase 1 Open
    Question Q2: rows whose REF or ALT length > 1 are skipped (Tier 2
    indel concordance against GATK HC isn't verified yet).

    Panel→CRAM rewrite: scoring files use bare-chrom (``1, 2, …, 22, X``);
    the emitted rows carry the ``chr`` prefix to match the user CRAM +
    GRCh38 FASTA naming.

    REF/ALT orientation: PGS Catalog convention is that ``other_allele``
    matches the reference. So REF=other_allele, ALT=effect_allele.
    """
    opener = gzip.open if str(scorefile_path).endswith(".gz") else open
    rows: list[tuple[str, int, str, str]] = []
    chrom_col: int | None = None
    pos_col: int | None = None
    effect_col: int | None = None
    other_col: int | None = None

    with opener(scorefile_path, "rt") as fh:
        for raw_line in fh:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split("\t")
            if chrom_col is None:
                # First non-comment, non-blank line is the column header.
                lower = [f.lower() for f in fields]
                for i, name in enumerate(lower):
                    if name in {"hm_chr", "chr_name"}:
                        chrom_col = i
                    elif name in {"hm_pos", "chr_position"}:
                        pos_col = i
                    elif name == "effect_allele":
                        effect_col = i
                    elif name == "other_allele":
                        other_col = i
                if None in (chrom_col, pos_col, effect_col, other_col):
                    raise ValueError(
                        f"scoring file header missing required columns "
                        f"(hm_chr, hm_pos, effect_allele, other_allele): "
                        f"got {fields!r}"
                    )
                continue
            # All four *_col indices are non-None here (else the header
            # parser above would have raised); cast for mypy's benefit.
            assert chrom_col is not None
            assert pos_col is not None
            assert effect_col is not None
            assert other_col is not None
            try:
                chrom_raw = fields[chrom_col]
                pos = int(fields[pos_col])
                effect = fields[effect_col]
                other = fields[other_col]
            except (IndexError, ValueError):
                continue
            # SNP filter — Phase 1 scope restricts Tier 2 to single-nucleotide
            # changes until indel concordance is empirically verified.
            if len(effect) != 1 or len(other) != 1:
                continue
            rows.append((f"chr{chrom_raw}", pos, other, effect))

    return rows


def _tier2_cache_path(
    *,
    derived_root: Path,
    sample_id: str,
    panel_version: str,
    pgs_id: str,
    scorefile_sha256: str,
) -> Path:
    """Deterministic Tier 2 cache path keyed by (sample, panel, pgs, scorefile-sha8).

    Layout: ``<derived>/prs_coverage/<sample>/<panel>/pgs/<PGS_ID>-<sha8>/tier2.vcf.gz``.

    The ``sha8`` prefix is the first 8 hex chars of the scoring-file SHA256.
    Upstream silent re-harmonisation → new SHA → new directory → cache miss
    → rebuild. Stale caches stay on disk and can be reaped by a future
    ``genomeclaw prs cache-gc`` step.
    """
    sha8 = scorefile_sha256[:8]
    return (
        derived_root
        / "prs_coverage"
        / sample_id
        / panel_version
        / "pgs"
        / f"{pgs_id}-{sha8}"
        / "tier2.vcf.gz"
    )


def _force_genotype_tier2(
    *,
    cram_path: Path,
    pgs_rows: list[tuple[str, int, str, str]],
    fasta: Path,
    output_vcf: Path,
) -> None:
    """Force-genotype the user at every site in ``pgs_rows``; stage + promote.

    Same pipe shape as :func:`_force_genotype_tier1` but with PGS-derived
    sites/alleles written on-the-fly inside the scratch shard. The
    sites + alleles TSVs are scratch-only (never persisted) since they're
    deterministic from the scoring file.
    """
    crai = Path(f"{cram_path}.crai")
    if not crai.exists():
        raise MissingCramIndexError(f"CRAM index missing: {crai}. Run: samtools index {cram_path}")

    output_vcf.parent.mkdir(parents=True, exist_ok=True)
    base = ephemeral_scratch_base()
    run_id = cram_path.stem
    with shard_scratch(step="prs_coverage_tier2", run_id=run_id, base=base) as shard:
        sites_tsv = shard / "pgs_sites.tsv"
        alleles_tsv = shard / "pgs_alleles.tsv"
        with sites_tsv.open("w") as fh_s, alleles_tsv.open("w") as fh_a:
            for chrom, pos, ref, alt in pgs_rows:
                fh_s.write(f"{chrom}\t{pos}\n")
                fh_a.write(f"{chrom}\t{pos}\t{ref},{alt}\n")

        scratch_vcf = shard / "tier2.vcf.gz"
        pipe = _build_bcftools_pipe(
            cram=cram_path,
            sites=sites_tsv,
            alleles=alleles_tsv,
            fasta=fasta,
            output=scratch_vcf,
        )
        proc = subprocess.run(
            ["bash", "-c", pipe],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
            raise BcftoolsError(
                f"tier2 force-genotype pipe failed (rc={proc.returncode}):\n{stderr_text}"
            )
        if not scratch_vcf.exists():
            raise BcftoolsError(f"tier2 pipe completed but staged VCF not found: {scratch_vcf}")

        # Validate the pipe produced records BEFORE caching. Phase 7 smoke
        # v15 (2026-05-20) caught the silent-failure pattern: bcftools' pipe
        # exited cleanly with a header-only VCF, the wrapper happily
        # atomic_promoted it, and every subsequent smoke iteration inherited
        # the 0-record cache. The pgsc_calc match step then failed at "2.9%
        # match rate" — the symptom 4 layers downstream from the actual bug.
        record_count = _count_vcf_records(scratch_vcf)
        if record_count == 0:
            raise BcftoolsError(
                f"tier2 force-genotype produced ZERO output records despite "
                f"{len(pgs_rows):,} input PGS sites against {cram_path}. The "
                f"bcftools pipe exited cleanly but produced a header-only VCF. "
                f"Common causes:\n"
                f"  - Chromosome naming mismatch (CRAM uses 'chr' prefix? "
                f"Scorefile?)\n"
                f"  - Reference build mismatch (CRAM build != fasta build)\n"
                f"  - PGS scorefile is empty or malformed\n"
                f"  - CRAM has no reads at any of the PGS sites\n"
                f"NOT caching empty result; resolve the underlying issue and rerun."
            )

        atomic_promote(scratch_vcf, output_vcf)
        scratch_tbi = shard / "tier2.vcf.gz.tbi"
        if scratch_tbi.exists():
            atomic_promote(scratch_tbi, output_vcf.parent / f"{output_vcf.name}.tbi")


# Autosomes (chr1..chr22) only — sex chromosomes + mitochondrial dropped
# from the merged VCF before pgsc_calc. plink2 (run inside pgsc_calc's
# DooD siblings) refuses to import chrX without an accompanying sex-info
# file; Phase 7 smoke v9 surfaced this as a clean inside-sibling error:
# ``chrX is present in the input file, but no sex information was
# provided; rerun this import with --psam or --update-sex``.
# Until the wrapper supplies sex via samplesheet ``--psam``, the safe
# behaviour is to drop sex/mito records before they reach pgsc_calc.
# This loses the chrX/chrY/chrM scoring contribution; for autosomal-
# dominated PRS (the v1 supported set) the impact is small. Track via
# the per-variant log's ``match_rate`` — a large drop after this filter
# indicates a sex-chromosome-heavy scorefile that warrants the proper
# --psam fix as a follow-up.
_AUTOSOME_TARGETS = ",".join(f"chr{n}" for n in range(1, 23))


def _merge_tier1_tier2(*, tier1: Path, tier2: Path, output_vcf: Path) -> None:
    """Concat + sort + filter-to-autosomes Tier 1 and Tier 2 into one
    coordinate-sorted, bgzipped, tabix-indexed VCF.

    ``bcftools concat --allow-overlaps`` handles the PCA × PGS overlap
    cleanly; ``bcftools sort`` produces deterministic coordinate ordering;
    ``bcftools view --targets chr1,...,chr22`` drops sex + mito records
    (see :data:`_AUTOSOME_TARGETS` for rationale).

    Both inputs come from the same CRAM via the same forced-genotyping
    pipe, so overlapping sites have identical allele orientations — no
    extra deduplication step required.
    """
    output_vcf.parent.mkdir(parents=True, exist_ok=True)
    pipe = (
        f"bcftools concat --allow-overlaps --output-type u {tier1} {tier2} "
        f"| bcftools sort --output-type u "
        f"| bcftools view --output-type z --output {output_vcf} "
        f"  --targets {_AUTOSOME_TARGETS} "
        f"&& bcftools index --tbi --force {output_vcf}"
    )
    proc = subprocess.run(["bash", "-c", pipe], capture_output=True, check=False)
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise BcftoolsError(f"tier1+tier2 merge failed (rc={proc.returncode}):\n{stderr_text}")


def _normalize_for_pgsc_calc(
    *,
    input_vcf: Path,
    fasta: Path,
    output_vcf: Path,
) -> None:
    """Decompose multi-allelic records via ``bcftools norm -m -any -f <fasta>``.

    Runs upstream of pgsc_calc so the score-matching step sees one
    single-ALT record per scoring-weight position rather than rejecting
    multi-allelic rows. Recovers the ~10% multi-allelic / complex-record
    share of the structural missingness on non-imputed single-sample WGS
    (per docs/reports/prs-real-data-smoke-research-findings.md).

    Pipeline:
        bcftools norm -m -any -f <fasta> --output-type z --output <output_vcf> <input_vcf>
        && bcftools index --tbi --force <output_vcf>

    The ``-m -any`` flag is load-bearing — it's what decomposes multi-
    allelics. The ``-f`` flag passes the reference fasta so REF allele
    integrity is verified during normalization. Output is bgzipped +
    tabix-indexed so pgsc_calc can stream-consume it.

    INV-R002 (Never Cache a Degenerate Result): if bcftools exits
    cleanly but emits a header-only VCF, raises :class:`BcftoolsError`
    + removes the empty output (and its .tbi sidecar) so downstream
    callers don't see a half-baked artifact.

    INV-D001: writes only to ``output_vcf`` + its sidecar; reads
    ``input_vcf`` and ``fasta`` read-only.

    Bcftools idempotency: running on already-normalized input is a
    content no-op (single-ALT records pass through unchanged).
    """
    output_vcf.parent.mkdir(parents=True, exist_ok=True)
    # ``-d both`` deduplicates records matching on BOTH REF and ALT. Tier 1
    # + Tier 2 can both cover the same site (a PGS scoring weight that's
    # also PCA-eligible); ``bcftools concat --allow-overlaps`` in
    # ``_merge_tier1_tier2`` does NOT dedup, so the merged VCF can carry
    # the same variant twice. PLINK2_SCORE later rejects the input with
    # ``variant ID '<chrom>:<pos>:<ref>:<alt>' appears multiple times in
    # main dataset`` (smoke v22i regression, 2026-05-21).
    pipe = (
        f"bcftools norm -m -any -d both -f {fasta} "
        f"--output-type z --output {output_vcf} {input_vcf} "
        f"&& bcftools index --tbi --force {output_vcf}"
    )
    proc = subprocess.run(["bash", "-c", pipe], capture_output=True, check=False)
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise BcftoolsError(
            f"bcftools norm -m -any failed (rc={proc.returncode}):\n{stderr_text}"
        )
    if not output_vcf.exists():
        raise BcftoolsError(
            f"bcftools norm completed but output VCF not found: {output_vcf}"
        )

    # INV-R002 guard: silent-failure pattern surfaces here. A 0-record
    # output means bcftools accepted the inputs but produced nothing —
    # most common when the upstream merge VCF was already degenerate
    # (and somehow slipped past Tier 1 + Tier 2 guards) or when the
    # fasta-VCF build mismatch ate every record.
    record_count = _count_vcf_records(output_vcf)
    if record_count == 0:
        # Clean up the orphan output so callers don't see a half-baked
        # artifact. Mirror the discipline _force_genotype_tier1/2 use:
        # NEVER leave the empty file where a future cache-hit check
        # would find it.
        output_vcf.unlink(missing_ok=True)
        tbi = Path(f"{output_vcf}.tbi")
        tbi.unlink(missing_ok=True)
        raise BcftoolsError(
            f"bcftools norm -m -any produced ZERO output records from "
            f"input {input_vcf}. The pipe exited cleanly but emitted only "
            f"a header-only VCF. Common causes:\n"
            f"  - Input VCF was already empty (Tier 1 + Tier 2 produced 0 records upstream)\n"
            f"  - Fasta build mismatch (input VCF contigs not in the fasta index)\n"
            f"  - All records dropped during normalization (rare; would imply malformed input)\n"
            f"NOT caching empty result; resolve the underlying issue and rerun."
        )


def prepare_coverage_tier2(
    *,
    sample_id: str,
    cram_path: Path,
    scorefile_path: Path,
    fasta: Path,
    panel_version: str,
    output_root: Path,
) -> Path:
    """Build (or return cached) the Tier 2 VCF for one PGS scoring file.

    Cache-hit semantics: the cache path is keyed by
    ``(sample, panel, pgs_id, scorefile_sha256[:8])``. An identical
    scoring file at the same path is a hit; any byte-level change invalidates
    by yielding a new directory.

    Side-effect: writes ``tier2.qc.json`` next to the VCF carrying the
    scoring-file SHA256, the PGS ID, the bcftools version, and the row
    counts (SNP and total) so a future audit can reconstruct what was
    genotyped.

    Returns the Tier 2 VCF path.
    """
    pgs_id = _extract_pgs_id_from_scorefile(scorefile_path)
    scorefile_sha = _sha256_file(scorefile_path)

    cache_vcf = _tier2_cache_path(
        derived_root=output_root,
        sample_id=sample_id,
        panel_version=panel_version,
        pgs_id=pgs_id,
        scorefile_sha256=scorefile_sha,
    )
    cache_qc = cache_vcf.parent / "tier2.qc.json"

    if cache_vcf.exists() and cache_qc.exists():
        return cache_vcf

    pgs_rows = _extract_pgs_sites_from_scorefile(scorefile_path)

    # Orient REF/ALT against the actual reference fasta BEFORE handing
    # rows to bcftools. The PGS Catalog "convention" that other_allele is
    # the reference is partly true; many scorefiles have effect_allele as
    # the reference (e.g., when "this allele increases risk" semantics
    # flips orientation). bcftools call --constrain alleles rejects rows
    # where the declared REF doesn't match the fasta — phase-7 smoke v17
    # surfaced this as 0-record tier2.vcf.gz over 1.7M sites. The
    # orientation step swaps where needed + skips orphan sites
    # (tri-allelic, wrong-build, strand). See pgs-allele-orientation plan.
    oriented_rows, orientation_skipped, orientation_swapped = (
        _orient_pgs_sites_against_fasta(pgs_rows, fasta)
    )

    # Sort by (chrom, pos) so bcftools mpileup emits records in coordinate
    # order. Without this, the downstream ``bcftools index --tbi`` step
    # fails with ``[E::hts_idx_push] Unsorted positions on sequence #N:
    # X followed by Y``. PGS Catalog scorefiles aren't guaranteed sorted
    # within chromosomes; smoke v20 (2026-05-20) surfaced this against
    # PGS001229 — 28k records were produced but the index couldn't be
    # built. Python's natural tuple sort groups same-chromosome rows
    # together + orders positions ascending within each.
    oriented_rows.sort(key=lambda row: (row[0], row[1]))

    _force_genotype_tier2(
        cram_path=cram_path,
        pgs_rows=oriented_rows,
        fasta=fasta,
        output_vcf=cache_vcf,
    )

    try:
        bversion = bcftools_version().version
    except (FileNotFoundError, BcftoolsError, ValueError):
        bversion = "unavailable"

    summary = _summarize_tier1_qc(cache_vcf)
    qc_blob: dict[str, Any] = {
        "sample_id": sample_id,
        "pgs_id": pgs_id,
        "panel_version": panel_version,
        "scorefile_path": str(scorefile_path),
        "scorefile_sha256": scorefile_sha,
        "snp_row_count": len(pgs_rows),
        "orientation_input_count": len(pgs_rows),
        "orientation_kept_count": len(oriented_rows),
        "orientation_skipped_count": orientation_skipped,
        "orientation_swapped_count": orientation_swapped,
        "bcftools_version": bversion,
        "tool_command": (
            "bcftools mpileup -R sites | bcftools call -C alleles -T alleles "
            "| bcftools norm -m -any"
        ),
        **summary,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": SCHEMA_VERSION,
    }
    cache_qc.write_text(json.dumps(qc_blob, indent=2))
    return cache_vcf


# ---------------------------------------------------------------------------
# End-to-end orchestrator — Phase 4c
# ---------------------------------------------------------------------------


def compute_prs_with_coverage_fill(
    *,
    sample_id: str,
    cram_path: Path,
    sites_tsv: Path,
    alleles_tsv: Path,
    scorefile_path: Path,
    fasta: Path,
    panel_version: str,
    reference_root: SiblingMountablePath,
    output_root: Path,
    work_dir: SiblingMountablePath,
    agent_choice_rationale: str,
    requested_for_question: str,
    trait_label: str | None = None,
    match_rate: float | None = None,
    pgs_variant_count: int | None = None,
) -> PgsRow:
    """Chain Tier 1 + Tier 2 + merge + pgsc_calc into one entry point.

    The single-call surface the agent's compute path uses. Each step
    short-circuits on a warm cache, so subsequent invocations for the same
    (sample, panel, PGS, scorefile_sha) skip the bcftools work entirely
    and only re-run pgsc_calc against the cached merged VCF.

    The merged VCF stages under :func:`ephemeral_scratch_base` (INV-D003)
    rather than under ``derived/`` — pgsc_calc consumes it inside a single
    invocation and a stale merged file on disk would just be re-built
    from cached tier1 + tier2 next time anyway.

    Calibration (Phase 3b2): when both ``match_rate`` and
    ``pgs_variant_count`` are supplied the orchestrator runs
    :func:`classify_calibration` after pgsc_calc:

    - CLEAN/WARNING → returned row carries ``calibration_status`` per
      :func:`apply_calibration_decision`.
    - DECLINE → raises :class:`PRSDeclineError` with the structural
      reason + two generated default named reasons (INV-C001 v1.7 +
      INV-A003 two-named-reasons rule).

    Callers that don't yet compute match_rate from pgsc_calc output (a
    Phase 3b3 deliverable) omit both params and get the Phase 4c behaviour
    — the row's ``calibration_status`` is ``None`` and no decline path runs.

    Returns the :class:`PgsRow` from :func:`compute_pgs`, with agent
    rationale + question threaded through (INV-A003).
    """
    # INV-D006 boundary check: pgsc_calc spawns DooD sibling containers; the
    # work_dir + reference_root must be on the host filesystem (canonical
    # mount or GENOMECLAW_HOST_ROOTS overlay). A container-local path (e.g.,
    # `/tmp/genomeclaw-scratch/...`) raises DooDPathError here, BEFORE any
    # bcftools / pgsc_calc subprocess fires. Smoke v3 reproducer guard.
    work_dir = as_sibling_mountable(work_dir)
    reference_root = as_sibling_mountable(reference_root)

    tier1_vcf = prepare_coverage_tier1(
        sample_id=sample_id,
        cram_path=cram_path,
        sites_tsv=sites_tsv,
        alleles_tsv=alleles_tsv,
        fasta=fasta,
        panel_version=panel_version,
        output_root=output_root,
    )

    tier2_vcf = prepare_coverage_tier2(
        sample_id=sample_id,
        cram_path=cram_path,
        scorefile_path=scorefile_path,
        fasta=fasta,
        panel_version=panel_version,
        output_root=output_root,
    )

    # Stage the merged VCF inside ``work_dir`` (NOT in container-local
    # ephemeral scratch). pgsc_calc spawns sibling containers via DooD; those
    # siblings resolve paths against the **host** filesystem, so the merged
    # VCF must live on a bind-mounted, host-visible path. The work_dir is
    # exactly that — the caller passes it as a host-visible bind-mount and
    # pgsc_calc consumes it via ``-work-dir``. Phase 5 smoke 2026-05-19
    # surfaced the prior `/tmp/genomeclaw-scratch` placement as silently
    # broken: sibling containers couldn't see the merged VCF, pgsc_calc
    # exited rc=1 immediately, the only stderr was the Nextflow update
    # banner. The fix: stage at ``work_dir/merged.vcf.gz``.
    pgs_id = _extract_pgs_id_from_scorefile(scorefile_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    merged_vcf = work_dir / "merged.vcf.gz"
    _merge_tier1_tier2(tier1=tier1_vcf, tier2=tier2_vcf, output_vcf=merged_vcf)

    # Decompose multi-allelic records before pgsc_calc sees them. The
    # PGS Catalog scorefile format assumes one ALT per scoring-weight
    # position; multi-allelic rows in the merged VCF (~10% of records on
    # non-imputed single-sample WGS per
    # docs/reports/prs-real-data-smoke-research-findings.md) would be
    # dropped by pgsc_calc's score-matching step. The `-m -any` flag
    # decomposes each multi-allelic site into N single-ALT records.
    # Stages alongside merged_vcf in work_dir (host-visible for DooD).
    #
    # Filename basename ``norm`` is ALPHANUMERIC — pgsc_calc has TWO
    # independent sampleset rules:
    #
    #   1. NO '.' — INTERSECT_VARIANTS truncates at the first dot when
    #      deriving downstream filenames (smoke v13 regression, 2026-05-19;
    #      smoke v22 regression, 2026-05-21 when the original Phase 2
    #      ``merged.norm.vcf.gz`` produced sampleset ``merged.norm``).
    #   2. NO '_' — pgsc_calc's filename convention is
    #      ``GRCh38_<sampleset>_<chrom>.<ext>``; the parser strips the last
    #      ``_<chrom>`` to recover sampleset, so internal underscores break
    #      it (smoke v22b regression, 2026-05-21, when the v22 dot-fix
    #      renamed to ``merged_norm.vcf.gz`` and pgsc_calc rejected at
    #      samplesheet-validation time with "Reserved sampleset name/
    #      character detected").
    #
    # Generalised rule: sampleset (= VCF basename minus .vcf.gz) must be
    # alphanumeric only. The single-word ``norm`` satisfies both rules
    # without ambiguity. Regression guard:
    # ``test_compute_prs_with_coverage_fill_normalized_vcf_basename_has_no_dot``.
    normalized_vcf = work_dir / "norm.vcf.gz"
    _normalize_for_pgsc_calc(input_vcf=merged_vcf, fasta=fasta, output_vcf=normalized_vcf)

    # work_dir is already validated above; normalized_vcf is a child path
    # of work_dir and therefore sibling-mountable by construction. The
    # factory call is idempotent (passing-through valid paths is cheap).
    row = compute_pgs(
        vcf=as_sibling_mountable(normalized_vcf),
        pgs_id=pgs_id,
        reference_root=reference_root,
        work_dir=work_dir,
        agent_choice_rationale=agent_choice_rationale,
        requested_for_question=requested_for_question,
        trait_label=trait_label,
    )

    # Phase 3b3a — auto-discover match_rate from pgsc_calc's per-variant log
    # when the caller didn't supply explicit kwargs. The 2026-05-17 smoke
    # established that ``<work_dir>/<nextflow_hash>/<sampleset>_log.csv.gz``
    # has a ``match_status`` column whose values (matched / unmatched) sum
    # to the unique scoring-variant count for that accession.
    if match_rate is None and pgs_variant_count is None:
        log_csv = find_pgsc_calc_log_csv(work_dir, sampleset=sample_id)
        if log_csv is not None:
            stats = parse_match_stats(
                log_csv,
                pgs_accession=f"{pgs_id}_hmPOS_GRCh38",
            )
            if stats is not None:
                match_rate = stats.match_rate
                pgs_variant_count = stats.matched + stats.unmatched

    if match_rate is None or pgs_variant_count is None:
        return row

    decision = classify_calibration(
        match_rate=match_rate,
        pgs_variant_count=pgs_variant_count,
    )

    if decision.status is CalibrationStatus.DECLINE:
        assert decision.decline_reason is not None  # classifier invariant
        raise PRSDeclineError(
            reason=decision.decline_reason,
            two_named_reasons=(
                f"Match rate {match_rate:.2%} falls below the variant-overlap "
                f"threshold for a {pgs_variant_count:,}-variant PGS scoring file.",
                "Variant-overlap insufficient: too few PGS scoring sites had "
                "genotype calls in the user's input to support an ancestry-"
                "calibrated score (INV-C001 v1.7).",
            ),
            message=(
                f"PRS {row.pgs_id} declined per INV-C001 v1.7 "
                f"(match_rate={match_rate:.4f} below threshold for "
                f"{pgs_variant_count:,}-variant tier)"
            ),
        )

    return apply_calibration_decision(row, decision)


__all__ = [
    "PLINK2_IMAGE",
    "SCHEMA_VERSION",
    "MissingCramIndexError",
    "MissingPanelError",
    "Plink2Error",
    "_extract_pgs_id_from_scorefile",
    "_extract_pgs_sites_from_scorefile",
    "_force_genotype_tier1",
    "_force_genotype_tier2",
    "_materialize_pca_sites",
    "_merge_tier1_tier2",
    "_parse_prune_in_to_alleles",
    "_summarize_tier1_qc",
    "_tier1_cache_path",
    "_tier2_cache_path",
    "atomic_promote",  # re-exported for test patching
    "compute_pgs",  # re-exported for test patching
    "compute_prs_with_coverage_fill",
    "prepare_coverage_tier1",
    "prepare_coverage_tier2",
]

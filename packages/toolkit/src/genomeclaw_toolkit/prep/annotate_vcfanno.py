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
4. Shards the normalized VCF by chromosome and runs vcfanno once per
   shard. Each per-chrom config has exactly three ``[[annotation]]``
   blocks (ClinVar + the matching gnomAD-exomes per-chrom file +
   dbSNP). Chromosomes absent from gnomAD-exomes (chrM, decoys) fall
   back to the first gnomAD-exomes file to keep header declarations
   uniform across shards — the fallback file's tabix index never
   matches the off-chrom variants, so no annotations leak across.
5. Concatenates the per-chrom annotated shards via
   ``bcftools concat --naive`` (uniform headers guarantee a fast,
   block-level stitch) and tabix-indexes the result.
6. ``atomic_promote``s the output into ``run_dir/vcfanno.vcf.gz`` + ``.tbi``.
7. Updates ``manifest.outputs.vcfanno_vcf`` + sha256.
8. Appends a ``vcfanno`` step to ``provenance.json`` capturing each
   overlay's path + sha256 + the inline TOML config.

Phase 4C migrates the Phase-4A ``bcftools annotate`` ClinVar overlay
to vcfanno; the Phase-4A path remains in ``annotate.py`` until 4C.3's
parent-orchestrator rewrite removes it.

Why shard by chromosome (resolves 4C.4 open question 1): vcfanno
doesn't know that a per-chrom overlay file only contains its own
chromosome — for every input variant it tabix-seeks into every
configured overlay source. The earlier "one ``[[annotation]]`` block
per gnomAD chrom file" shape meant each variant triggered 24 redundant
seeks across the 23 mismatched per-chrom files. Empirically that
inflated annotate wall time by ~20× and drowned vcfanno's stderr in
~120 M ``bix.go:251: chromosome chrN not found in chrM.vcf.bgz`` lines
(verified 2026-05-12 on the project owner's Nebula VCF). Sharding the
input by chromosome and using only the matching gnomAD file per shard
removes the redundancy completely.

`INV-D001`: reference overlay files are read-only; the staged copies
in scratch are the only mutations (a chr-rename + tabix-reindex of the
ClinVar staged copy). `INV-D003`: heavy intermediates land under
``_scratch/<step>/<run_id>/``; the final ``vcfanno.vcf.gz`` is the
only thing that crosses into ``derived/``, via ``atomic_promote(...)``.
`INV-R001`: provenance step records every overlay's path + sha256 +
a representative inline TOML config plus the per-chrom shard set so
a rerun against the same overlay SHAs reproduces byte-equivalent
annotation columns.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._bcftools import (
    bcftools_concat,
    bcftools_index_tbi,
    bcftools_run,
    bcftools_view_region,
    bcftools_view_regions_file,
)
from genomeclaw_toolkit.prep._events import emit_beat
from genomeclaw_toolkit.prep._vcfanno import (
    VcfannoConfig,
    build_vcfanno_toml,
    run_vcfanno,
    vcfanno_version,
)
from genomeclaw_toolkit.prep.scratch import atomic_promote, shard_scratch

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit.prep._events import _ProgressEvent

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


# RefSeq accession → chr-prefixed contig map for dbSNP staging
# (resolves 4C.4 W4). NCBI's dbSNP b157 ships with RefSeq accessions on
# the CHROM column (``NC_000001.11`` for GRCh38 chr1, etc.) — neither
# numeric nor chr-prefixed. Without this rename, vcfanno queries for
# ``chr1`` against dbSNP's tabix index, the index has no ``chr1``, and
# 100% of dbsnp_rsid lookups miss. The accession mapping comes from
# NCBI's GCF_000001405.40 assembly_report.txt
# (https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/);
# verified 2026-05-12 against the project owner's b157 layout.
_DBSNP_REFSEQ_TO_UCSC_MAP = (
    "NC_000001.11\tchr1\n"
    "NC_000002.12\tchr2\n"
    "NC_000003.12\tchr3\n"
    "NC_000004.12\tchr4\n"
    "NC_000005.10\tchr5\n"
    "NC_000006.12\tchr6\n"
    "NC_000007.14\tchr7\n"
    "NC_000008.11\tchr8\n"
    "NC_000009.12\tchr9\n"
    "NC_000010.11\tchr10\n"
    "NC_000011.10\tchr11\n"
    "NC_000012.12\tchr12\n"
    "NC_000013.11\tchr13\n"
    "NC_000014.9\tchr14\n"
    "NC_000015.10\tchr15\n"
    "NC_000016.10\tchr16\n"
    "NC_000017.11\tchr17\n"
    "NC_000018.10\tchr18\n"
    "NC_000019.10\tchr19\n"
    "NC_000020.11\tchr20\n"
    "NC_000021.9\tchr21\n"
    "NC_000022.11\tchr22\n"
    "NC_000023.11\tchrX\n"
    "NC_000024.10\tchrY\n"
    "NC_012920.1\tchrM\n"
)


# Persistent cache subdir under ``<scratch_base>/_cache/``. Lives
# inside scratch (so the bind-mount + permissions already work) but
# survives the per-step ``shard_scratch(...)`` purge — the orchestrator
# only ever calls ``shard_scratch`` for the per-step subdir, never for
# ``_cache/``. The user can manually ``rm -rf _scratch/_cache/`` at any
# time; the next run rebuilds. Each entry is keyed by a content hash
# (source sha256 + rename-map text) so re-fetching a new dbSNP file or
# editing the contig-rename table invalidates the cache deterministically
# instead of silently serving stale data.
_PERSISTENT_CACHE_SUBDIR = "_cache"


def _persistent_cache_key(source_sha: str, rename_map: str) -> str:
    """16-char content hash uniquely identifying one (source, rename-map) pair.

    Sub-strings the SHA256 to 16 hex chars (~64 bits) — plenty of room
    against accidental collisions across the handful of overlay sources
    a given GenomeClaw install ever sees, while keeping the directory
    name short enough to read at a glance.
    """
    return hashlib.sha256(f"{source_sha}\n{rename_map}".encode("utf-8")).hexdigest()[:16]


# Canonical GRCh38 chrom set we shard one-at-a-time against. A
# consumer-genomics VCF (Nebula) lifts every contig from the
# no_alt_analysis_set FASTA — that's 1,500+ decoys / alts / unplaced
# contigs alongside the 25 "real" chromosomes. Sharding by every input
# chrom would spin up 1,500+ vcfanno subprocesses where each has a
# multi-second startup cost (open tabix indexes for clinvar + gnomad
# + dbsnp) and where ~99% of those shards annotate <100 variants. The
# canonical set below is what gets its own per-chrom shard; everything
# else lands in one catch-all shard so the subprocess overhead is
# bounded by len(canonical) + 1.
_CANONICAL_GRCH38_CHROMS: frozenset[str] = frozenset(
    [*(f"chr{i}" for i in range(1, 23)), "chrX", "chrY", "chrM"]
)


@dataclass(frozen=True)
class _ShardPlan:
    """One vcfanno-shard work unit.

    ``regions`` is a single-element tuple for canonical-chrom shards
    (``("chr1",)``) and a many-element tuple for the catch-all
    non-canonical shard (``("chrUn_…", "chrEBV", …)``). The extraction
    step turns this into either a single ``--regions`` arg or a
    written-to-scratch regions file consumed by
    ``bcftools_view_regions_file``.
    """

    idx: int
    label: str
    regions: tuple[str, ...]
    gnomad_source: Path
    input_path: Path
    output_path: Path
    work_path: Path


def _format_regions_file(regions: tuple[str, ...]) -> str:
    """Render a tab-delimited regions file for ``bcftools view --regions-file``.

    bcftools rejects a 1-column "just chrom names" file with
    ``bcf_sr_regions_init: Could not parse line, using columns 1,2[,-1]``;
    it requires 2-column ``CHROM\\tPOS`` or 3-column ``CHROM\\tBEG\\tEND``
    (1-based inclusive). We use 3-column with a 1 Gb upper-bound END so
    a single line covers any GRCh38 contig in full — the longest is
    chr1 at ~248 Mb, decoys / alts are smaller, and 1 Gb is well inside
    htslib's int32 POS range without hitting overflow corners.
    """
    return "\n".join(f"{r}\t1\t1000000000" for r in regions) + "\n"


def _build_shard_plan(
    *,
    input_chroms: tuple[str, ...],
    gnomad_map: dict[str, Path],
    gnomad_fallback: Path,
    input_shard_dir: Path,
    annotated_shard_dir: Path,
) -> tuple[list[_ShardPlan], list[str]]:
    """Compute the shard plan for ``input_chroms``.

    Returns ``(plans, non_canonical_chroms)``. Canonical chroms (chr1–22
    + chrX/chrY/chrM, in the order they appear in the input) each get
    their own shard with the matching gnomAD-exomes per-chrom file.
    Every contig outside the canonical set lands in one trailing
    catch-all shard with the gnomAD-exomes fallback; the catch-all is
    absent when no non-canonical contigs are present.
    """
    canonical_in_input = [c for c in input_chroms if c in _CANONICAL_GRCH38_CHROMS]
    non_canonical_in_input = [c for c in input_chroms if c not in _CANONICAL_GRCH38_CHROMS]

    plans: list[_ShardPlan] = []
    for idx, chrom in enumerate(canonical_in_input, start=1):
        plans.append(
            _ShardPlan(
                idx=idx,
                label=chrom,
                regions=(chrom,),
                gnomad_source=gnomad_map.get(chrom, gnomad_fallback),
                input_path=input_shard_dir / f"{chrom}.vcf.gz",
                output_path=annotated_shard_dir / f"{chrom}.vcf.gz",
                work_path=annotated_shard_dir / f"work-{chrom}",
            )
        )
    if non_canonical_in_input:
        plans.append(
            _ShardPlan(
                idx=len(plans) + 1,
                label="non-canonical",
                regions=tuple(non_canonical_in_input),
                gnomad_source=gnomad_fallback,
                input_path=input_shard_dir / "non-canonical.vcf.gz",
                output_path=annotated_shard_dir / "non-canonical.vcf.gz",
                work_path=annotated_shard_dir / "work-non-canonical",
            )
        )
    return plans, non_canonical_in_input


# Per-chrom shard parallelism. Each worker manages one vcfanno
# subprocess; the subprocess itself runs ``-p 1`` (single Go worker)
# because vcfanno's multi-worker mode has hit futex_wait hangs at
# end-of-stream on real-scale inputs (documented in
# ``_bcftools.bcftools_annotate_clinvar``). The OS-level concurrency we
# get from running 4 shards in parallel is safer + simpler than
# tweaking vcfanno's own worker count.
#
# 4 was chosen as a conservative ceiling: on macOS + an external USB-3
# SSD (the project owner's layout), 4 concurrent vcfanno processes
# saturate ~200-300 MB/s of read I/O against the gnomAD tabix indexes
# without contention.  Tunable via ``GENOMECLAW_ANNOTATE_WORKERS``
# (caps at 8 to keep the disk-I/O envelope bounded; below that the
# vcfanno startup overhead would dominate per-shard wall time).
_DEFAULT_ANNOTATE_WORKERS = 4
_MAX_ANNOTATE_WORKERS = 8


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


def _sha256_file_cached(path: Path, *, cache_dir: Path) -> tuple[str, bool]:
    """Return ``(sha256, cache_hit)`` for ``path``; cache keyed on (size, mtime_ns).

    ``INV-R001`` requires the source sha256 land in ``provenance.json``;
    we still need the *value* every run, but recomputing it for ~230 GB
    of read-only overlay sources every annotate run is wasteful when
    nothing about the file has changed. The cache stores
    ``{size, mtime_ns, sha256}`` per file path inside ``cache_dir``; on
    lookup, if either ``size`` or ``mtime_ns`` no longer match the
    on-disk file, the cache is treated as a miss and the sha is
    recomputed + rewritten.

    Returns the cache-hit flag too so the caller can surface a "cached"
    vs "computed" beat in the rich UI — telling the user where the
    one-time cost is being paid.

    Atomicity: each cache entry is written via ``tmp + os.replace`` so a
    crashed write leaves either the prior cached value or no entry, never
    a half-written one that a future lookup might misparse.

    The cache key embeds the absolute path so moving a file to a new
    location triggers a recompute (the new path is the natural identity
    from the orchestrator's point of view). Two files with identical
    contents at different paths each get their own cache entry — that's
    fine, the bytes-on-disk argument is what governs correctness.
    """
    st = path.stat()
    path_key = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:32]
    cache_file = cache_dir / f"{path_key}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if (
                isinstance(cached, dict)
                and cached.get("size") == st.st_size
                and cached.get("mtime_ns") == st.st_mtime_ns
                and isinstance(cached.get("sha256"), str)
                and len(cached["sha256"]) == 64
            ):
                return cached["sha256"], True
        except (OSError, ValueError):
            # Malformed cache entry — fall through to recompute.
            pass

    sha = _sha256_file(path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_name(cache_file.name + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "path": str(path),
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sha256": sha,
            }
        )
    )
    os.replace(tmp, cache_file)
    return sha, False


def _hash_files_parallel(
    sources: list[Path],
    *,
    cache_dir: Path,
    worker_count: int,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> dict[Path, str]:
    """Hash ``sources`` in parallel via :class:`ThreadPoolExecutor`.

    Python's :mod:`hashlib` releases the GIL inside ``update(...)`` on
    blocks larger than ~2 KiB, so a thread pool of N workers gets near-
    N× CPU throughput on SHA256 — bounded only by aggregate read
    bandwidth. On a USB-3 SSD with 4 workers, this typically cuts the
    overlay-hashing phase from ~8 min single-threaded to ~2 min.

    Each per-file hash goes through :func:`_sha256_file_cached`, so a
    re-run against an unmodified reference layout pays only a stat()
    per file (the cache hit takes ~microseconds).

    Args:
        sources: Files to hash. Order doesn't matter for correctness;
            results are keyed by path.
        cache_dir: Persistent sha256 cache (one entry per source path).
        worker_count: Max concurrent hash threads.
        progress_callback: Optional consumer for per-file beat events.

    Returns:
        ``{path: sha256_hex}`` covering every input ``path``.
    """
    results: dict[Path, str] = {}

    def _one(path: Path) -> tuple[Path, str, bool]:
        sha, hit = _sha256_file_cached(path, cache_dir=cache_dir)
        return path, sha, hit

    if worker_count == 1:
        for path in sources:
            p, sha, hit = _one(path)
            results[p] = sha
            emit_beat(
                progress_callback,
                phase="annotate",
                message=f"hashed {p.name} ({'cached' if hit else 'computed'})",
                logger=log,
            )
        return results

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="annotate-vcfanno-hash",
    ) as pool:
        futures = [pool.submit(_one, p) for p in sources]
        for fut in concurrent.futures.as_completed(futures):
            p, sha, hit = fut.result()
            results[p] = sha
            emit_beat(
                progress_callback,
                phase="annotate",
                message=f"hashed {p.name} ({'cached' if hit else 'computed'})",
                logger=log,
            )
    return results


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


def _list_input_chroms(vcf: Path) -> tuple[str, ...]:
    """Return chromosomes present in ``vcf``'s tabix index, in index order.

    Uses ``tabix -l`` against the ``.tbi`` sidecar so the cost is a
    single index-header read regardless of the VCF body size. The
    returned tuple is the authoritative set of chroms the per-chrom
    shard loop iterates over.

    Raises:
        FileNotFoundError: ``vcf.tbi`` is missing — every caller in
            this orchestrator runs after a ``bcftools index --tbi`` step
            so this should be unreachable in practice; surface it
            loudly if the contract gets broken upstream.
    """
    tbi = vcf.with_suffix(vcf.suffix + ".tbi")
    if not tbi.exists():
        raise FileNotFoundError(f"tabix index missing for {vcf}: expected {tbi}")
    proc = subprocess.run(
        ["tabix", "-l", str(vcf)],
        capture_output=True,
        check=True,
    )
    chroms = tuple(
        line for line in proc.stdout.decode("utf-8", errors="replace").splitlines() if line
    )
    if not chroms:
        raise ValueError(f"no chromosomes found in tabix index for {vcf}")
    return chroms


def _resolve_worker_count() -> int:
    """Resolve the concurrent shard count from ``GENOMECLAW_ANNOTATE_WORKERS``.

    Defaults to ``_DEFAULT_ANNOTATE_WORKERS`` when unset / invalid.
    Caps at ``_MAX_ANNOTATE_WORKERS`` to keep the I/O footprint bounded
    on consumer-SSD setups.
    """
    raw = os.environ.get("GENOMECLAW_ANNOTATE_WORKERS")
    if raw is None:
        return _DEFAULT_ANNOTATE_WORKERS
    try:
        n = int(raw)
    except ValueError:
        log.warning(
            "GENOMECLAW_ANNOTATE_WORKERS=%r is not an integer; using default %d",
            raw,
            _DEFAULT_ANNOTATE_WORKERS,
        )
        return _DEFAULT_ANNOTATE_WORKERS
    return max(1, min(n, _MAX_ANNOTATE_WORKERS))


def _gnomad_files_by_chrom(gnomad_files: list[Path]) -> dict[str, Path]:
    """Map ``chr1`` → ``…/by_chrom/chr1.vcf.bgz`` for the resolved gnomAD set.

    Files outside the canonical ``chr<N>.vcf.bgz`` naming are silently
    dropped from the map. The fetcher always lays them out that way; a
    hand-edited reference root that deviates from the convention would
    surface here as a missing chrom in the map (and the per-chrom shard
    loop would route those chroms through the fallback file).
    """
    suffix = ".vcf.bgz"
    out: dict[str, Path] = {}
    for p in gnomad_files:
        name = p.name
        if name.endswith(suffix):
            out[name[: -len(suffix)]] = p
    return out


def _build_shard_configs(
    *,
    clinvar_staged: Path,
    gnomad_for_chrom: Path,
    dbsnp_staged: Path,
) -> tuple[VcfannoConfig, ...]:
    """Build the per-shard vcfanno block tuple.

    Centralised so the shard loop, the representative-config capture,
    and any future tests share one definition of "what overlay blocks
    each shard runs". The shape is fixed: one ClinVar block, one
    gnomAD-exomes block (per-chrom file or fallback), one dbSNP block —
    in that order. Each shard's resulting INFO header is therefore
    identical regardless of chromosome, which is what makes
    ``bcftools concat --naive`` a safe stitch downstream.
    """
    return (
        VcfannoConfig(
            file=clinvar_staged,
            fields=("CLNSIG", "CLNREVSTAT"),
            names=("clinvar_classification", "clinvar_review_status"),
            ops=("self", "self"),
        ),
        VcfannoConfig(
            file=gnomad_for_chrom,
            fields=_GNOMAD_FIELDS,
            names=_GNOMAD_NAMES,
            ops=tuple(["self"] * len(_GNOMAD_FIELDS)),
        ),
        VcfannoConfig(
            file=dbsnp_staged,
            fields=("RS",),
            names=("dbsnp_rsid",),
            ops=("self",),
        ),
    )


def _stage_dbsnp_with_cache(
    *,
    source: Path,
    source_sha: str,
    scratch_base: Path,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path:
    """Return a path to the chr-renamed dbSNP, building + caching it if absent.

    The dbSNP source ships with NCBI RefSeq accessions on the CHROM
    column (``NC_000001.11`` etc.). vcfanno's tabix lookup matches by
    literal CHROM string, so without a rename every dbsnp_rsid lookup
    misses against our chr-prefixed input. The rename itself decodes +
    re-encodes the entire ~29 GB dbSNP file — the dominant single cost
    of the annotate phase.

    Build path: one ``bcftools annotate --threads N --rename-chrs ...``
    invocation streams the source sequentially, decodes + rewrites
    every record's CHROM, re-encodes with N parallel BGZF threads, and
    writes a single output file. We tried per-chrom parallelism
    (``bcftools annotate --regions ... --rename-chrs`` in a thread
    pool); on real-data dbSNP it was substantially slower than the
    single-pass version because (a) the source has ~700 RefSeq contigs
    once patches / alts / unplaced are included, so the pool fragments
    into hundreds of small subprocesses each with ~3-5 s of tabix-seek
    + index-load overhead, and (b) concurrent random-access reads of
    the same 29 GB source from a USB-3 SSD contend for I/O bandwidth
    worse than the sequential single-pass read.

    Cache layout::

        <scratch_base>/_cache/dbsnp/<key>/dbsnp.ucsc.vcf.gz
        <scratch_base>/_cache/dbsnp/<key>/dbsnp.ucsc.vcf.gz.tbi
        <scratch_base>/_cache/dbsnp/<key>/dbsnp_chr_rename.tsv

    where ``<key>`` is ``_persistent_cache_key(source_sha, rename_map)``.
    Re-fetching dbSNP (different source bytes) or editing the rename map
    (different ``_DBSNP_REFSEQ_TO_UCSC_MAP``) produces a different key →
    a fresh build, leaving the old cache entry on disk until the user
    purges it manually.

    Atomicity: the build writes to ``dbsnp.ucsc.vcf.gz.part`` and only
    ``os.replace``s into the canonical name on successful completion.
    A crashed mid-build run leaves the ``.part`` orphan + no canonical
    file, so the next run treats the cache as a miss and rebuilds —
    crash recovery without manual cleanup.
    """
    cache_dir = scratch_base / _PERSISTENT_CACHE_SUBDIR / "dbsnp" / _persistent_cache_key(
        source_sha, _DBSNP_REFSEQ_TO_UCSC_MAP
    )
    cached_vcf = cache_dir / "dbsnp.ucsc.vcf.gz"
    cached_tbi = cache_dir / "dbsnp.ucsc.vcf.gz.tbi"

    if cached_vcf.exists() and cached_tbi.exists():
        emit_beat(
            progress_callback,
            phase="annotate",
            message=f"using cached renamed dbsnp at {cached_vcf}",
            logger=log,
        )
        return cached_vcf

    cache_dir.mkdir(parents=True, exist_ok=True)
    chr_map = cache_dir / "dbsnp_chr_rename.tsv"
    chr_map.write_text(_DBSNP_REFSEQ_TO_UCSC_MAP)

    emit_beat(
        progress_callback,
        phase="annotate",
        message=(
            "building dbsnp cache via single-pass bcftools annotate "
            "(--threads 8; one-time cost; cached for subsequent runs)"
        ),
        logger=log,
    )
    # ``--threads`` parallelises BGZF compression inside the one
    # bcftools process. Diminishing returns past ~8 because the BGZF
    # writer serialises block emission; 8 hits the knee for consumer
    # CPUs without oversubscribing.
    part = cache_dir / "dbsnp.ucsc.vcf.gz.part"
    bcftools_run(
        [
            "annotate",
            "--threads",
            "8",
            "--rename-chrs",
            str(chr_map),
            "-O",
            "z",
            "-o",
            str(part),
            str(source),
        ]
    )
    os.replace(part, cached_vcf)
    bcftools_index_tbi(vcf=cached_vcf, derived_dir=cache_dir)
    emit_beat(
        progress_callback,
        phase="annotate",
        message=f"dbsnp cache populated at {cached_vcf}",
        logger=log,
    )
    return cached_vcf


def _stage_with_chr_rename(
    *, source: Path, scratch: Path, rename_map: str, source_name: str
) -> Path:
    """Stage ``source`` into ``scratch``, renaming contigs per ``rename_map``.

    Always runs the rename: ``bcftools annotate --rename-chrs`` is a no-op
    when the source's contigs are already chr-prefixed (the map's left
    column doesn't match), so this is safe both for the canonical NCBI
    shapes (numeric for ClinVar, RefSeq for dbSNP) and for already-
    renamed test fixtures.

    Reads directly from ``source`` (no scratch copy) — bcftools is
    read-only against the input, so `INV-D001` holds. For dbSNP this
    avoids a ~29 GB redundant copy; for ClinVar the saved ~200 MB is
    nice but not material.

    Args:
        source: bgzipped + tabix-indexed input VCF (read-only).
        scratch: per-step scratch dir.
        rename_map: TSV body ("``<old>\\t<new>\\n``" per line) — passed
            to ``bcftools annotate --rename-chrs``.
        source_name: short label (e.g. ``"clinvar"``, ``"dbsnp"``) used
            for the on-disk filenames inside ``scratch``.

    Returns:
        Path to the freshly-written ``scratch/<source_name>.renamed.vcf.gz``
        (bgzipped + tabix-indexed).
    """
    src_tbi = source.with_suffix(source.suffix + ".tbi")
    if not src_tbi.exists():
        raise FileNotFoundError(f"{source_name} tabix index missing: {src_tbi}")

    chr_map = scratch / f"{source_name}_chr_rename.tsv"
    chr_map.write_text(rename_map)
    renamed = scratch / f"{source_name}.renamed.vcf.gz"
    # --threads parallelises BGZF compression. The rename itself is
    # cheap; the wall-time cost is decompress + recompress of every
    # data record. With the 29 GB dbSNP file this turns a single-
    # threaded ~60 min stage into a ~15-20 min one on a 4-core box.
    # Threads above 4 see diminishing returns because the BGZF writer
    # serialises block emission; 4 matches the per-shard worker
    # ceiling so contended runs don't oversubscribe the CPU.
    bcftools_run(
        [
            "annotate",
            "--threads",
            "4",
            "--rename-chrs",
            str(chr_map),
            "-O",
            "z",
            "-o",
            str(renamed),
            str(source),
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
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
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
        progress_callback: optional event consumer used to emit
            beat-by-beat :class:`PhaseMessage` events ("staging dbsnp",
            "[3/24] chr3 shard complete", "concatenating shards"). The
            parent ``annotate`` orchestrator's ``PhaseStart`` /
            ``PhaseComplete`` pair frames these so the rich renderer
            attributes them to the active phase row.

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
    emit_beat(
        progress_callback,
        phase="annotate",
        message=(
            f"resolved overlay sources · clinvar={clinvar_vcf.name} "
            f"dbsnp={dbsnp_vcf.name} gnomad={len(gnomad_files)} chrom files"
        ),
        logger=log,
    )

    # SHA256 every overlay source for provenance. The 24 gnomAD-exomes
    # chrom files total ~200 GB single-threaded; we (a) run the per-file
    # hashes in parallel via a ThreadPoolExecutor (hashlib releases the
    # GIL inside ``update(...)`` so workers genuinely overlap I/O + CPU),
    # and (b) persist (size, mtime_ns) → sha256 results into the same
    # ``_cache/`` location the dbsnp cache lives in so subsequent runs
    # against an unmodified reference layout pay only a ``stat()`` per
    # source.
    #
    # The norm_vcf is NEVER cache-hit because it's freshly written by
    # the prior ``normalize`` step (new mtime every run); listing it in
    # ``sources`` just lets the parallel pool include it in the same
    # worker rotation.
    # Scratch base: sibling of derived/, matching both production (the
    # shim bind-mounts /mnt/genomeclaw/{derived,scratch} as siblings)
    # and the test layout (the genomeclaw_layout fixture lays out
    # tmp/{derived,scratch}). Computed once here because both the hash
    # cache and the per-step shard_scratch want the same root.
    scratch_base = run_dir.parent.parent / "scratch"
    hash_cache_dir = scratch_base / _PERSISTENT_CACHE_SUBDIR / "sha256"
    worker_count = _resolve_worker_count()
    sources_to_hash: list[Path] = [clinvar_vcf, dbsnp_vcf, *gnomad_files, norm_vcf]
    emit_beat(
        progress_callback,
        phase="annotate",
        message=(
            f"hashing {len(sources_to_hash)} overlay sources for provenance "
            f"({worker_count} concurrent worker(s); cached across runs)"
        ),
        logger=log,
    )
    shas = _hash_files_parallel(
        sources_to_hash,
        cache_dir=hash_cache_dir,
        worker_count=worker_count,
        progress_callback=progress_callback,
    )
    clinvar_sha = shas[clinvar_vcf]
    dbsnp_sha = shas[dbsnp_vcf]
    gnomad_shas: dict[Path, str] = {p: shas[p] for p in gnomad_files}
    norm_vcf_sha = shas[norm_vcf]

    output_vcf = run_dir / "vcfanno.vcf.gz"
    # ``scratch_base`` was computed above (alongside ``hash_cache_dir``);
    # used here for the per-step ``shard_scratch`` context. Keeping a
    # single definition avoids drift if the path convention ever
    # changes.
    representative_config_toml: str | None = None
    chroms_processed: tuple[str, ...] = ()
    with shard_scratch(step="annotate-vcfanno", run_id=run_dir.name, base=scratch_base) as scratch:
        emit_beat(
            progress_callback,
            phase="annotate",
            message=f"staging inputs to {scratch}",
            logger=log,
        )
        emit_beat(
            progress_callback,
            phase="annotate",
            message="staging clinvar with chr-prefix rename",
            logger=log,
        )
        clinvar_staged = _stage_with_chr_rename(
            source=clinvar_vcf,
            scratch=scratch,
            rename_map=_CLINVAR_TO_GRCH38_CHR_MAP,
            source_name="clinvar",
        )
        # dbSNP gets a persistent-cache resolver (separate from the
        # per-run ClinVar staging path) because the rename is by far the
        # dominant cost of the annotate phase (~15-30 min on consumer
        # SSD against the ~29 GB b157 file). Caching keyed on
        # source-sha + rename-map content keeps the cache invalidation
        # honest: a re-fetch or rename-map edit produces a new key →
        # fresh build, with no risk of silently serving stale data.
        dbsnp_staged = _stage_dbsnp_with_cache(
            source=dbsnp_vcf,
            source_sha=dbsnp_sha,
            scratch_base=scratch_base,
            progress_callback=progress_callback,
        )

        input_chroms = _list_input_chroms(norm_vcf)
        chroms_processed = input_chroms
        gnomad_map = _gnomad_files_by_chrom(gnomad_files)
        # Fallback file for chroms with no gnomAD-exomes counterpart
        # (chrM, decoys). Pinning a single fallback keeps the vcfanno
        # config's [[annotation]] block set — and therefore each output
        # shard's INFO header — uniform across chroms, which is what
        # lets ``bcftools concat --naive`` stitch the shards without
        # re-encoding (orders of magnitude faster than re-encoding all
        # ~5 M records). vcfanno tabix-seeks the fallback for those
        # off-chrom variants and finds nothing; the wasted seeks are
        # bounded by the tiny chrom's variant count (chrM ≈ 37) so the
        # overhead is negligible.
        gnomad_fallback = gnomad_files[0]

        input_shard_dir = scratch / "input_by_chrom"
        input_shard_dir.mkdir()
        annotated_shard_dir = scratch / "annotated_by_chrom"
        annotated_shard_dir.mkdir()

        worker_count = _resolve_worker_count()
        shard_plans, non_canonical_chroms = _build_shard_plan(
            input_chroms=input_chroms,
            gnomad_map=gnomad_map,
            gnomad_fallback=gnomad_fallback,
            input_shard_dir=input_shard_dir,
            annotated_shard_dir=annotated_shard_dir,
        )
        emit_beat(
            progress_callback,
            phase="annotate",
            message=(
                f"sharding · {len(shard_plans)} shard(s) over {len(input_chroms)} input contigs "
                + (
                    f"({len(non_canonical_chroms)} non-canonical bundled into 1 catch-all shard), "
                    if non_canonical_chroms
                    else ""
                )
                + f"{worker_count} concurrent worker(s)"
            ),
            logger=log,
        )

        # Build the per-shard input VCFs upfront. Splitting the input
        # ("bcftools view --regions") is cheap and CPU-light; running it
        # serially keeps the parallel section focused on the heavy
        # vcfanno subprocess work and avoids inflating the number of
        # bcftools children in flight at once.
        regions_files_dir = scratch / "regions_files"
        regions_files_dir.mkdir()
        for plan in shard_plans:
            emit_beat(
                progress_callback,
                phase="annotate",
                message=(
                    f"[{plan.idx}/{len(shard_plans)}] {plan.label}: extracting input shard"
                    + (
                        f" ({len(plan.regions)} contigs)"
                        if len(plan.regions) > 1
                        else ""
                    )
                ),
                logger=log,
            )
            if len(plan.regions) == 1:
                bcftools_view_region(
                    input_vcf=norm_vcf,
                    region=plan.regions[0],
                    output_vcf=plan.input_path,
                )
            else:
                regions_file = regions_files_dir / f"{plan.label}.regions.txt"
                regions_file.write_text(_format_regions_file(plan.regions))
                bcftools_view_regions_file(
                    input_vcf=norm_vcf,
                    regions_file=regions_file,
                    output_vcf=plan.input_path,
                )
            bcftools_index_tbi(vcf=plan.input_path, derived_dir=input_shard_dir)
            plan.work_path.mkdir()
            if representative_config_toml is None:
                # Build a representative config now so it's recorded
                # even if a later shard fails before we run vcfanno on
                # the first one.
                representative_config_toml = build_vcfanno_toml(
                    _build_shard_configs(
                        clinvar_staged=clinvar_staged,
                        gnomad_for_chrom=plan.gnomad_source,
                        dbsnp_staged=dbsnp_staged,
                    )
                )

        def _run_shard(plan: _ShardPlan) -> Path:
            shard_configs = _build_shard_configs(
                clinvar_staged=clinvar_staged,
                gnomad_for_chrom=plan.gnomad_source,
                dbsnp_staged=dbsnp_staged,
            )
            shard_config_toml = build_vcfanno_toml(shard_configs)
            emit_beat(
                progress_callback,
                phase="annotate",
                message=(
                    f"[{plan.idx}/{len(shard_plans)}] {plan.label}: vcfanno running "
                    f"(gnomAD source: {plan.gnomad_source.name})"
                ),
                logger=log,
            )
            run_vcfanno(
                input_vcf=plan.input_path,
                output_vcf=plan.output_path,
                config_toml=shard_config_toml,
                work_dir=plan.work_path,
            )
            emit_beat(
                progress_callback,
                phase="annotate",
                message=f"[{plan.idx}/{len(shard_plans)}] {plan.label}: shard complete",
                logger=log,
            )
            return plan.output_path

        annotated_shards: list[Path] = [Path()] * len(shard_plans)
        if worker_count == 1:
            for plan in shard_plans:
                annotated_shards[plan.idx - 1] = _run_shard(plan)
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="annotate-vcfanno-shard",
            ) as pool:
                future_to_idx = {
                    pool.submit(_run_shard, plan): plan.idx for plan in shard_plans
                }
                for fut in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    annotated_shards[idx - 1] = fut.result()

        emit_beat(
            progress_callback,
            phase="annotate",
            message=f"per-chrom vcfanno complete; concatenating {len(annotated_shards)} shards",
            logger=log,
        )
        work_output = scratch / "vcfanno.vcf.gz"
        bcftools_concat(inputs=annotated_shards, output_vcf=work_output, naive=True)
        work_output_tbi = bcftools_index_tbi(vcf=work_output, derived_dir=scratch)

        emit_beat(
            progress_callback,
            phase="annotate",
            message=f"promoting outputs to {run_dir}",
            logger=log,
        )
        atomic_promote(src=work_output, dst=output_vcf)
        atomic_promote(src=work_output_tbi, dst=run_dir / "vcfanno.vcf.gz.tbi")

    # ``representative_config_toml`` is the first shard's config; the
    # only field that differs between shards is which gnomAD-exomes
    # per-chrom file is referenced. The inputs list below records every
    # gnomAD chrom file with its sha256, so the per-chrom routing rule
    # ("chrN uses by_chrom/chrN.vcf.bgz; off-chrom uses the fallback")
    # is reconstructible from inputs + this representative config.
    assert representative_config_toml is not None  # at least 1 shard always processed

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
            "params": {
                "config": representative_config_toml,
                "sharding": "by_chrom",
                "chroms_processed": list(chroms_processed),
            },
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

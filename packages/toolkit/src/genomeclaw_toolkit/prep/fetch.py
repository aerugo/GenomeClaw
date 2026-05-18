"""``genomeclaw refs fetch`` — versioned, checksum-verified downloads of
annotation datasets into ``reference/<source>/<release>/``.

Each call is a deliberate user invocation (a CLI flag, not a background
task — `INV-P001`). The download is HTTPS to a published, well-known
URL; ``base_url`` is overridable in tests so the suite never reaches
outside the runner.

Source shapes:
- **Single-file** (ClinVar, GRCh38, dbSNP): one canonical artifact at a
  fixed URL + an MD5 sidecar in NCBI ``<hex>  <fname>`` form. The
  fetcher downloads + verifies + atomically renames into place.
- **Per-chromosome** (gnomAD v4.1 exomes; 24 files for chr1–22, X, Y):
  no NCBI-style MD5 sidecar; verification is "Content-Length matches
  the server-reported size" + the pre-shipped ``.tbi`` index lands
  alongside the ``.vcf.bgz`` (a corrupt download fails to tabix-query
  at the next pipeline step). The ``chroms=`` kwarg filters which
  chromosomes are fetched; defaults to all 24.

Sub-phase 2B implements ClinVar. Phase 4B adds GRCh38 (with a
``samtools faidx`` post-fetch hook). Phase 4C adds gnomAD-exomes (per-
chromosome) and dbSNP (single-file).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urljoin

from genomeclaw_toolkit.prep._bgzip import (
    IncompleteBgzip,
    is_bgzip_target,
    verify_bgzip_eof_marker,
)
from genomeclaw_toolkit.prep._events import FileComplete, FileFailed, FileProgress, FileStart

log = logging.getLogger(__name__)

# Default retry budget for the resume-on-stall loop. The original
# attempt is not counted; ``max_resume_attempts = 5`` means the
# fetcher makes up to 1 + 5 = 6 HTTP requests for a single file before
# giving up.
_DEFAULT_MAX_RESUME_ATTEMPTS: Final[int] = 5
_DEFAULT_RETRY_BACKOFF_INITIAL_SEC: Final[float] = 1.0
_DEFAULT_RETRY_BACKOFF_CAP_SEC: Final[float] = 30.0

# Default file-level parallelism inside a single ``fetch()`` invocation.
# 4 keeps total open connections modest while letting multi-file sources
# (gnomAD-exomes' 48 files) actually run concurrently. The CLI's outer
# source-level parallelism layers on top: with the default 4 sources × 4
# inner workers the peak is ~16 concurrent downloads, capped naturally
# by single-file sources (clinvar / dbsnp / grch38) having only 1-2
# files each.
_DEFAULT_CONCURRENT_FILES: Final[int] = 4

# Periodic interval between in-flight progress lines on long downloads.
# Tight enough to feel alive on a 100 Mbps link (one line every ~200 MB);
# loose enough not to spam logs when stdout isn't a TTY.
_PROGRESS_INTERVAL_SEC = 1.5
_DOWNLOAD_CHUNK_BYTES = 1 << 20  # 1 MiB


def _human_bytes(n: float) -> str:
    """Compact human-readable byte count (e.g. ``2.4 GB``).

    Uses 1024-byte units like ``ls -h`` so a 1 KiB file reads ``1.0 KB``
    not ``1024 B``. Sub-KB sizes show as integer bytes to avoid the
    awkward ``47.0 B``.
    """
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} PB"


Source = Literal["clinvar", "grch38", "gnomad-exomes", "dbsnp"]


class ChecksumMismatch(RuntimeError):
    """The downloaded payload's checksum did not match the published value.

    The partial download is removed before the exception propagates.
    """


class TruncatedDownload(RuntimeError):
    """The on-disk byte count disagrees with the server's ``Content-Length``.

    Raised after every retry / resume attempt has been exhausted with a
    consistent short-byte response. The partial file is removed before
    the exception propagates.
    """


class DownloadStalled(RuntimeError):
    """Every resume attempt failed; the fetcher gave up.

    Raised after the configured ``max_resume_attempts`` is reached
    without the file finishing. The partial file is preserved on disk
    so a subsequent invocation could in principle resume further
    (current behaviour: a fresh fetch run treats the leftover as a
    re-attempt). The current invocation cleans up its own scratch file
    before this exception propagates.
    """


class VersionAlreadyExists(FileExistsError):
    """The target ``reference/<source>/<release>/`` directory already
    contains the canonical artifact. Re-fetching the same release is a
    no-op by `INV-D001` — the user must remove the old version
    deliberately if they want to re-fetch.
    """


@dataclass(frozen=True)
class _FetchFile:
    """One file in a source's fetch manifest.

    Templates use ``{chrom}`` substitution for per-chromosome sources;
    single-file sources leave the placeholder out and the templating
    is a no-op.

    Three MD5 verification modes:

    1. ``md5_relpath`` set, ``md5_checksums_relpath`` unset — a per-file
       NCBI-style sidecar in ``<hex>  <fname>\\n`` form. Used by ClinVar
       and dbSNP, which publish one sidecar per data file.
    2. ``md5_checksums_relpath`` set, ``md5_relpath`` unset — a
       directory-level ``md5checksums.txt`` listing every file in the
       directory as one ``<hex>  ./<fname>\\n`` line. Used by NCBI's
       grch38 assembly tree, which doesn't ship per-file sidecars.
       ``md5_checksums_key`` names the exact line key (e.g.
       ``"./GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz"``).
    3. Both unset — no verification (gnomAD ships pre-indexed; the
       ``.tbi`` sidecar is the structural integrity check).
    """

    relpath: str
    """Path relative to ``base_url``. May contain ``{chrom}``."""

    output_filename: str
    """Filename inside the target dir. May contain ``{chrom}``."""

    md5_relpath: str | None = None
    """Mode 1: per-file sidecar at this URL."""

    md5_checksums_relpath: str | None = None
    """Mode 2: directory-level ``md5checksums.txt`` to grep through."""

    md5_checksums_key: str | None = None
    """Mode 2: the line key to match inside ``md5checksums.txt`` (NCBI
    prefixes entries with ``./``)."""

    url_override: str | None = None
    """Optional full URL that replaces ``base_url + relpath`` for this
    one file. Used when a single file in a source's manifest legitimately
    lives on a different host than its siblings — e.g. LOFTEE's GERP
    BigWig is hosted on Ensembl FTP at GCS-class bandwidth while the
    rest of LOFTEE's data only exists on Broad's per-IP-throttled
    personal mirror. When set, ``base_url`` and ``relpath`` no longer
    determine the wire URL for this file in production. Tests that pass
    an explicit ``base_url=`` to :func:`fetch` retain full URL control —
    the override is suppressed so the test's mocked HTTP server still
    serves every file via ``base_url + relpath``. ``{release}`` /
    ``{release_n}`` placeholders are substituted at fetch time."""

    def for_chrom(self, chrom: str) -> _FetchFile:
        """Substitute ``{chrom}`` in every templated field."""
        return _FetchFile(
            relpath=self.relpath.format(chrom=chrom),
            output_filename=self.output_filename.format(chrom=chrom),
            md5_relpath=(
                self.md5_relpath.format(chrom=chrom) if self.md5_relpath is not None else None
            ),
            md5_checksums_relpath=(
                self.md5_checksums_relpath.format(chrom=chrom)
                if self.md5_checksums_relpath is not None
                else None
            ),
            md5_checksums_key=(
                self.md5_checksums_key.format(chrom=chrom)
                if self.md5_checksums_key is not None
                else None
            ),
            url_override=(
                self.url_override.format(chrom=chrom) if self.url_override is not None else None
            ),
        )


@dataclass(frozen=True)
class _SourceLayout:
    """Per-source URL pattern + canonical filenames + checksum convention."""

    files: tuple[_FetchFile, ...] = ()
    """Static set of files (no chrom templating). Single-file sources
    have exactly one entry; per-chrom sources have zero (the entries
    are derived from ``chrom_files`` at fetch time)."""

    chrom_files: tuple[_FetchFile, ...] = ()
    """Per-chromosome file templates. Each entry's ``relpath`` and
    ``output_filename`` contain ``{chrom}``; the fetcher applies one
    instantiation per chromosome in the requested set."""

    default_chroms: tuple[str, ...] = ()
    """Chromosome set to use when the caller doesn't pass ``chroms=``.
    For gnomAD-exomes: chr1–22 + X + Y."""

    output_subdir: str = ""
    """Subdirectory under ``target_dir`` where the fetched files land.
    Empty string places them directly under ``target_dir/``; a value
    like ``"by_chrom"`` nests them."""

    post_fetch: Callable[[Path], None] | None = None
    """Optional hook invoked with the ``target_dir`` after every file
    has been atomically moved into place. Used by ``grch38`` to build
    the ``.fai`` index via ``samtools faidx``. Hooks are best-effort:
    if the underlying tool is not on ``PATH`` (e.g. tests running in a
    host venv without samtools), the hook logs a warning and returns;
    production paths inside the ``genomeclaw/toolkit`` image always
    have the tool available."""

    presence_relpath: str | None = None
    """Optional marker path (relative to ``target_dir``, with
    ``{release_n}`` / ``{release}`` substitution) whose existence
    signals "this source has been successfully fetched AND any
    post-fetch processing has completed". When set, the `INV-D001`
    "already present" check uses this marker instead of looping over
    ``files`` — required for sources whose post-fetch hook intentionally
    deletes the canonical artifact (e.g. ``vep_cache`` extracts and
    removes the 21 GB tarball, so ``Path.exists("vep_cache.tar.gz")``
    is always False after a successful fetch and the next ``fetch
    --all`` would otherwise re-download ~21 GB it doesn't need to).

    The marker is an existence test only — it does NOT validate the
    fetched data's bytes / MD5 / index sidecars. ``genomeclaw refs
    verify`` is the structural-integrity tool; the presence marker is
    the cheap "did the user already run fetch successfully" gate."""

    @property
    def is_multi_file(self) -> bool:
        """True iff this layout uses per-chrom templating."""
        return bool(self.chrom_files)


def _samtools_faidx_in_target_dir(target_dir: Path) -> None:
    """Recompress NCBI's plain-gzip FASTA as bgzip + build the ``.fai`` /
    ``.gzi`` indexes alongside the canonical file.

    NCBI publishes ``GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz``
    as a plain gzip stream, but htslib (``samtools faidx``,
    ``bcftools norm -f``, ``mosdepth --fasta``, VEP) requires
    block-gzipped (bgzip) compression for random-access indexing —
    ``samtools faidx`` on a plain gzip refuses with ``Cannot index
    files compressed with gzip, please use bgzip``. So the post-fetch
    hook streams ``gunzip | bgzip`` to rewrite the file in place, then
    runs ``samtools faidx`` against the bgzipped output. The on-disk
    bytes change as a result; the ``.md5`` sidecar that was written
    during download remains a record of the **upstream** NCBI hash
    (what was on the wire), not of the recompressed file. Downstream
    consumers don't read ``.md5`` sidecars, so this is documentation
    only.

    Soft-fails when ``bgzip`` or ``samtools`` are missing from ``PATH``
    so the mocked-HTTP fetch tests can run on a host venv without bio
    binaries. Production runs inside the toolkit image where both are
    always present; downstream consumers fail loudly when the index is
    actually missing, so a soft-fail here can't silently corrupt a
    real run.
    """
    fasta_path = target_dir / "grch38.fa.gz"

    if shutil.which("samtools") is None or shutil.which("bgzip") is None:
        log.warning(
            "samtools or bgzip not on PATH; skipping bgzip recompression + "
            "faidx for %s. Build the index manually with "
            "`gunzip -c <gz> | bgzip > <bgz>; samtools faidx <bgz>` before "
            "running normalize or annotate.",
            fasta_path,
        )
        return

    print("    converting plain gzip → bgzip…", file=sys.stdout, flush=True)
    bgz_scratch = target_dir / ".grch38.fa.gz.bgz.part"
    try:
        with bgz_scratch.open("wb") as out:
            gunzip = subprocess.Popen(
                ["gunzip", "-c", str(fasta_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            bgzip = subprocess.Popen(
                ["bgzip", "-c"],
                stdin=gunzip.stdout,
                stdout=out,
                stderr=subprocess.PIPE,
            )
            # Close the parent's reference to gunzip's stdout so gunzip
            # sees EOF/SIGPIPE if bgzip dies.
            assert gunzip.stdout is not None
            gunzip.stdout.close()
            _, bgzip_stderr = bgzip.communicate()
            _, gunzip_stderr = gunzip.communicate()

        if gunzip.returncode != 0:
            raise RuntimeError(
                "gunzip failed: " + gunzip_stderr.decode("utf-8", errors="replace").strip()
            )
        if bgzip.returncode != 0:
            raise RuntimeError(
                "bgzip failed: " + bgzip_stderr.decode("utf-8", errors="replace").strip()
            )

        # Atomic swap: the recompressed file replaces NCBI's plain gzip.
        os.replace(bgz_scratch, fasta_path)
    finally:
        if bgz_scratch.exists():
            try:
                bgz_scratch.unlink()
            except OSError:
                pass

    print("    running samtools faidx…", file=sys.stdout, flush=True)
    proc = subprocess.run(
        ["samtools", "faidx", str(fasta_path)],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"samtools faidx failed for {fasta_path}: {stderr}")


def _build_alphamissense_tbi_in_target_dir(target_dir: Path) -> None:
    """Build the AlphaMissense tabix index post-fetch.

    DeepMind's ``dm_alphamissense`` GCS bucket publishes
    ``AlphaMissense_hg38.tsv.gz`` but **not** the matching ``.tbi``
    sidecar — verified 2026-05-13 against the live bucket. The
    AlphaMissense VEP plugin needs the index to be present alongside
    the data, so we build it locally with ``tabix``.

    Schema (confirmed against DeepMind's TSV layout): column 1 is
    CHROM, column 2 is POS, header lines start with ``#``. A point-
    variant tabix index keyed on (chrom, pos) is what the plugin
    consumes::

        tabix -f -s 1 -b 2 -e 2 -c '#' AlphaMissense_hg38.tsv.gz

    Soft-fails when ``tabix`` is not on PATH so mocked-HTTP fetch
    tests can run on a host venv without bio binaries — the production
    toolkit image always has tabix via the htslib package, and the
    AlphaMissense VEP plugin's first invocation would fail loudly if
    the index were silently absent (so a soft-fail can't poison a real
    run).
    """
    am_dir = target_dir / "AlphaMissense"
    am_file = am_dir / "AlphaMissense_hg38.tsv.gz"
    if not am_file.exists():
        log.warning("AlphaMissense .tsv.gz not found at %s; skipping tbi build", am_file)
        return
    if shutil.which("tabix") is None:
        log.warning(
            "tabix not on PATH; skipping AlphaMissense .tbi build for %s. "
            "Build manually with `tabix -f -s 1 -b 2 -e 2 -c '#' %s` before "
            "running annotate.",
            am_file,
            am_file,
        )
        return
    print("    building AlphaMissense tabix index…", file=sys.stdout, flush=True)
    build_start = time.monotonic()
    subprocess.run(
        ["tabix", "-f", "-s", "1", "-b", "2", "-e", "2", "-c", "#", str(am_file)],
        check=True,
    )
    print(
        f"    ✓ tabix index built in {time.monotonic() - build_start:.0f}s",
        file=sys.stdout,
        flush=True,
    )


def _gunzip_loftee_sql_in_target_dir(target_dir: Path) -> None:
    """Decompress ``loftee.sql.gz`` → ``loftee.sql`` post-fetch.

    LOFTEE's ``conservation_file`` plugin arg accepts a SQLite database
    file, not a gzipped one — the plugin opens it directly via the
    DBI bindings the toolkit image's perl ships. The mirror hosts the
    file gzipped (~150 MB → ~600 MB uncompressed), so we gunzip once
    at fetch time and keep both on disk: the ``.gz`` for archival /
    re-mirroring, the ``.sql`` for runtime use. Soft-fails if the .gz
    is absent (the plugin would just skip conservation filtering and
    return less-granular ``loftee_filter`` values).
    """
    sql_gz = target_dir / "loftee.sql.gz"
    sql = target_dir / "loftee.sql"
    if not sql_gz.exists():
        log.warning("loftee.sql.gz not found at %s; skipping decompression", sql_gz)
        return
    if sql.exists():
        return
    print("    decompressing loftee.sql.gz…", file=sys.stdout, flush=True)
    start = time.monotonic()
    import gzip

    with gzip.open(sql_gz, "rb") as src, sql.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    print(
        f"    ✓ decompressed in {time.monotonic() - start:.0f}s",
        file=sys.stdout,
        flush=True,
    )


def _extract_pgs_catalog_ancestry_bundle(target_dir: Path) -> None:
    """Extract the PGS Catalog HGDP+1KG ancestry bundle in-place; delete the .tar.zst.

    PGS Catalog publishes the continuous-ancestry reference panel as a
    single ``pgsc_HGDP+1kGP_<release>.tar.zst`` on
    ``ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/``. Verified upstream
    layout (2026-05-17, v1, real-data smoke): the bundle extracts FLAT (no
    outer dir, no per-population subdirs) into ``target_dir/``. The data is
    gnomAD's merged 1000G + HGDP callset (gnomAD v3.1.2) processed by the
    PGS Catalog team with plink2 — both populations live in single combined
    files keyed by reference build:

        GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam,log,king.cutoff.out.id}
        GRCh37_HGDP+1kGP_ALL.{pgen,pvar.zst,psam,log,king.cutoff.out.id}
        Citation.txt, meta.txt, checksums.txt

    Total compressed ~16 GB; extracted ~28 GB (both builds; we only need
    GRCh38, but pruning the GRCh37 half is a future optimisation —
    upstream ships them together).

    Streams ``ZstdDecompressor.stream_reader`` → ``tarfile`` so the full
    ~28 GB extracted tree never lives in memory at once.

    Soft-fails when ``zstandard`` is missing so mocked-HTTP fetch tests run
    on a bare host venv without the dep — production paths inside the
    toolkit image always have it, and ``_check_ancestry_reference`` /
    ``pgsc_calc`` fail loudly when the extracted tree is structurally
    absent, so a soft-fail can't silently corrupt a real run.
    """
    import tarfile

    try:
        import zstandard
    except ImportError:
        log.warning(
            "zstandard not installed; skipping PGS Catalog ancestry extraction. "
            "Install with `uv sync`."
        )
        return

    bundle = target_dir / "pgs_catalog_ancestry.tar.zst"
    if not bundle.exists():
        log.warning("pgs_catalog_ancestry bundle not found at %s; skipping extraction", bundle)
        return
    print(
        "    extracting PGS Catalog ancestry bundle (≈16 GB → ~28 GB on disk)…",
        file=sys.stdout,
        flush=True,
    )
    extract_start = time.monotonic()
    dctx = zstandard.ZstdDecompressor()
    with bundle.open("rb") as fh, dctx.stream_reader(fh) as zst_stream:
        # ``mode="r|"`` is streaming-tarfile mode (no seek required); the
        # ``data`` filter (3.12+) refuses absolute-path / parent-traversal
        # members, defensive against malformed upstream tarballs.
        with tarfile.open(fileobj=zst_stream, mode="r|") as tf:
            tf.extractall(path=target_dir, filter="data")

    print(
        f"    ✓ extracted in {time.monotonic() - extract_start:.0f}s; removing bundle",
        file=sys.stdout,
        flush=True,
    )
    bundle.unlink()


def _extract_vep_cache_tarball(target_dir: Path) -> None:
    """Extract Ensembl's VEP cache tarball in-place, then delete the .tar.gz.

    Ensembl publishes the indexed VEP cache as a single tarball at
    ``/pub/release-N/variation/indexed_vep_cache/homo_sapiens_vep_N_GRCh38.tar.gz``.
    Inside is ``homo_sapiens/<N>_GRCh38/...`` — VEP's ``--dir_cache``
    flag expects the parent dir of ``homo_sapiens/``, so the
    extraction target IS ``target_dir`` and the tarball's existing
    directory structure carries through.

    Post-extraction we delete the .tar.gz to reclaim ~21 GB. The
    fetcher records the upstream md5 in the on-disk ``.md5`` sidecar
    so a re-fetch is detectable by ``doctor`` even after the tarball
    is gone.

    Soft-fails when ``tar`` isn't on PATH so the mocked-HTTP fetch
    tests can run on a host venv without bio binaries. Production
    paths inside the toolkit image always have tar (it's a base-image
    package); downstream consumers fail loudly when the cache
    structure is missing.
    """
    import tarfile

    tarball = target_dir / "vep_cache.tar.gz"
    if not tarball.exists():
        log.warning("vep_cache tarball not found at %s; skipping extraction", tarball)
        return
    print(
        "    extracting VEP cache tarball (≈21 GB → ~75 GB on disk)…", file=sys.stdout, flush=True
    )
    extract_start = time.monotonic()
    # tarfile.data_filter (3.12+) refuses absolute-path / parent-traversal
    # members; ``data`` is the safe-by-default filter for arbitrary
    # tarballs of this shape. Ensembl's tarballs use relative paths
    # exclusively (``homo_sapiens/...``) so this is a defensive guard.
    with tarfile.open(tarball, mode="r:gz") as tf:
        tf.extractall(path=target_dir, filter="data")
    print(
        f"    ✓ extracted in {time.monotonic() - extract_start:.0f}s; removing tarball",
        file=sys.stdout,
        flush=True,
    )
    tarball.unlink()


# Canonical chromosome set for per-chrom human-genome sources. Used as
# ``default_chroms`` for gnomad-exomes; callers can pass a subset via
# ``chroms=`` for partial fetches or test injection.
_HUMAN_CHROMS: tuple[str, ...] = (*(str(i) for i in range(1, 23)), "X", "Y")


_LAYOUTS: dict[str, _SourceLayout] = {
    "clinvar": _SourceLayout(
        files=(
            _FetchFile(
                relpath="/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz",
                output_filename="clinvar.vcf.gz",
                md5_relpath="/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.md5",
            ),
            # Pre-built tabix index — required by annotate_vcfanno's
            # clinvar staging step. ClinVar publishes the .tbi but no
            # matching .tbi.md5 sidecar; integrity is checked
            # structurally at the next pipeline step (a corrupt index
            # fails tabix-query immediately).
            _FetchFile(
                relpath="/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.tbi",
                output_filename="clinvar.vcf.gz.tbi",
            ),
        ),
    ),
    # Phase 4B: NCBI's GRCh38 no_alt analysis-set fasta. The standard
    # short-read-pipeline reference (GATK + most consumer-genomics
    # tooling); chr-prefixed contigs match Nebula deliverables (verified
    # pre-flight 2026-05-09 against MPNRGLQ2K). NCBI does NOT publish
    # per-file ``.md5`` sidecars in the assembly tree — only a
    # directory-level ``md5checksums.txt`` with one line per file.
    "grch38": _SourceLayout(
        files=(
            _FetchFile(
                relpath=(
                    "/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38"
                    "/seqs_for_alignment_pipelines.ucsc_ids"
                    "/GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz"
                ),
                output_filename="grch38.fa.gz",
                md5_checksums_relpath=(
                    "/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38"
                    "/seqs_for_alignment_pipelines.ucsc_ids/md5checksums.txt"
                ),
                md5_checksums_key="./GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz",
            ),
        ),
        post_fetch=_samtools_faidx_in_target_dir,
    ),
    # Phase 4C: gnomAD v4.1 exomes — 24 per-chrom .vcf.bgz + .tbi.
    # ~198 GB total. Hosted on GCS; no NCBI-style MD5 sidecar (GCS
    # exposes md5 via Object metadata JSON API, but v0 verifies via
    # Content-Length match + the pre-indexed .tbi is the structural
    # integrity check). Genomes (563 GB) is a follow-up requiring an
    # explicit large-drive opt-in (per phase-4.md Q8.1).
    "gnomad-exomes": _SourceLayout(
        chrom_files=(
            _FetchFile(
                relpath="/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr{chrom}.vcf.bgz",
                output_filename="chr{chrom}.vcf.bgz",
            ),
            _FetchFile(
                relpath="/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr{chrom}.vcf.bgz.tbi",
                output_filename="chr{chrom}.vcf.bgz.tbi",
            ),
        ),
        default_chroms=_HUMAN_CHROMS,
        output_subdir="by_chrom",
    ),
    # Phase 4C: dbSNP. NCBI restructured the `latest_release/VCF/`
    # layout — the old `00-All.vcf.gz` aggregate is gone (404 since
    # build 156 transitioned out); each assembly now has its own
    # per-accession file. We pull the GRCh38 build via
    # ``GCF_000001405.40.gz`` (the GRCh38.p14 RefSeq accession the b157+
    # releases ship under). Each release directory contains both the
    # legacy GRCh37 (``GCF_000001405.25``) and GRCh38 file — we only
    # fetch GRCh38 since that's what the rest of the pipeline targets.
    # Note: dbSNP uses RefSeq contig IDs (``NC_000001.11``); a future
    # ``annotate_vcfanno`` chr-rename step is needed for it to match
    # chr-prefixed consumer-genomics VCFs. Tracked as a Phase-4D follow-up.
    "dbsnp": _SourceLayout(
        files=(
            _FetchFile(
                relpath="/snp/latest_release/VCF/GCF_000001405.40.gz",
                output_filename="dbsnp.vcf.gz",
                md5_relpath="/snp/latest_release/VCF/GCF_000001405.40.gz.md5",
            ),
            _FetchFile(
                relpath="/snp/latest_release/VCF/GCF_000001405.40.gz.tbi",
                output_filename="dbsnp.vcf.gz.tbi",
                md5_relpath="/snp/latest_release/VCF/GCF_000001405.40.gz.tbi.md5",
            ),
        ),
    ),
    # Phase 4D: VEP cache (Ensembl release-pinned). The indexed cache
    # tarball is ~21 GB compressed → ~75 GB extracted. The fetcher
    # downloads + atomically renames the tarball into
    # ``reference/vep_cache/<release>/vep_cache.tar.gz``, then the
    # post-fetch hook extracts the tarball in place + deletes it. After
    # extraction the layout is
    # ``reference/vep_cache/<release>/homo_sapiens/<N>_GRCh38/...``,
    # which VEP's ``--dir_cache <reference/vep_cache/<release>>``
    # consumes directly. Ensembl publishes the cache without an MD5
    # sidecar — integrity is structural (a corrupt tarball fails
    # extraction; a corrupt cache fails the first VEP invocation).
    # The user must pass an explicit ``--release`` matching their VEP
    # version (e.g. ``ensembl-114`` to match VEP 114.1 in our image).
    "vep_cache": _SourceLayout(
        files=(
            _FetchFile(
                relpath=(
                    "/pub/release-{release_n}/variation/indexed_vep_cache/"
                    "homo_sapiens_vep_{release_n}_GRCh38.tar.gz"
                ),
                output_filename="vep_cache.tar.gz",
            ),
        ),
        post_fetch=_extract_vep_cache_tarball,
        # The post-fetch hook deletes the 21 GB tarball after extracting
        # it, so the canonical ``vep_cache.tar.gz`` is gone on a healthy
        # already-fetched dir and the default existence check would
        # re-trigger the download. Ensembl ships ``info.txt`` at the
        # root of each release cache (``homo_sapiens/<N>_GRCh38/info.txt``)
        # — its presence is a reliable "this release was extracted"
        # signal.
        presence_relpath="homo_sapiens/{release_n}_GRCh38/info.txt",
    ),
    # Phase 4D: AlphaMissense precomputed scores for the AlphaMissense
    # VEP plugin. Hosted on Google Cloud Storage (DeepMind's public
    # bucket); two files — the scores TSV (.gz) + the matching tabix
    # index (.tbi). The plugin's ``file=`` arg consumes the .tsv.gz;
    # the .tbi sidecar must live alongside it (htslib's tabix
    # convention). After fetch, point the plugin at
    # ``reference/vep_cache/Plugins/AlphaMissense/AlphaMissense_hg38.tsv.gz``.
    "alphamissense": _SourceLayout(
        files=(
            _FetchFile(
                relpath="/dm_alphamissense/AlphaMissense_hg38.tsv.gz",
                output_filename="AlphaMissense_hg38.tsv.gz",
            ),
            # DeepMind doesn't publish ``AlphaMissense_hg38.tsv.gz.tbi``
            # on the GCS bucket (verified 2026-05-13). The post-fetch
            # hook builds it locally via tabix; the on-disk layout
            # ends up identical to the published-alongside-data
            # convention the VEP plugin expects.
        ),
        output_subdir="AlphaMissense",
        post_fetch=_build_alphamissense_tbi_in_target_dir,
    ),
    # Phase 4D: LOFTEE plugin data files. Five files in total per the
    # LOFTEE grch38 README. ~1 GB combined for the human_ancestor +
    # loftee.sql trio + ~10-13 GB for the GERP BigWig.
    #
    # Mirror routing (researcher-confirmed 2026-05-13): four files have
    # no public byte-equivalent fast mirror and must come from Konrad
    # Karczewski's Broad personal mirror — that host applies a ~500 kB/s
    # per-IP throttle but the ~1 GB combined size makes the throttle
    # tolerable (~30 min). The fifth file, ``gerp_conservation_scores.
    # homo_sapiens.GRCh38.bw``, is the throttle's worst case (12.6 GB →
    # 8h ETA on residential), so it is routed via the per-file
    # ``url_override`` to Ensembl FTP release-115 where the same data
    # serves at ~10 MB/s with no throttle. The Ensembl copy is the
    # 92_mammals alignment vs Broad's frozen 88_mammals — functionally
    # equivalent for LOFTEE's per-position lookup (LOFTEE issue #96
    # confirms users routinely substitute Ensembl), but it IS a
    # different scientific reference. Pin to release-115 for
    # reproducibility; record the routing in the on-disk provenance
    # manifest. See research-brief in commit message for details.
    #
    # Required for any LOFTEE output:
    #   - human_ancestor.fa.gz (+ .fai + .gzi) — ancestral-allele
    #     reference used to confirm loss-of-function predictions.
    #
    # Optional but enables finer-grained ``loftee_filter`` values
    # (the LoF plugin auto-detects them when present):
    #   - gerp_conservation_scores.homo_sapiens.GRCh38.bw — GERP
    #     BigWig used for the ``gerp_bigwig`` plugin arg.
    #   - loftee.sql.gz — gnomAD constraint database. Decompressed
    #     post-fetch to loftee.sql so the plugin can open it via
    #     ``conservation_file:<path>``.
    #
    # Neither mirror publishes MD5 sidecars (Broad-personal hosting,
    # Ensembl uses a CHECKSUMS file format we don't parse); structural
    # integrity is checked at first LOFTEE invocation. Worth mirroring
    # internally for strict reproducibility — the URLs are stable in
    # practice but not under institutional SLA.
    "loftee": _SourceLayout(
        files=(
            _FetchFile(
                relpath="/human_ancestor.fa.gz",
                output_filename="human_ancestor.fa.gz",
            ),
            _FetchFile(
                relpath="/human_ancestor.fa.gz.fai",
                output_filename="human_ancestor.fa.gz.fai",
            ),
            _FetchFile(
                relpath="/human_ancestor.fa.gz.gzi",
                output_filename="human_ancestor.fa.gz.gzi",
            ),
            _FetchFile(
                relpath="/gerp_conservation_scores.homo_sapiens.GRCh38.bw",
                output_filename="gerp_conservation_scores.homo_sapiens.GRCh38.bw",
                url_override=(
                    "https://ftp.ensembl.org/pub/release-115/compara/"
                    "conservation_scores/92_mammals.gerp_conservation_score/"
                    "gerp_conservation_scores.homo_sapiens.GRCh38.bw"
                ),
            ),
            _FetchFile(
                relpath="/loftee.sql.gz",
                output_filename="loftee.sql.gz",
            ),
        ),
        post_fetch=_gunzip_loftee_sql_in_target_dir,
    ),
    # Phase 4D: gnomAD constraint metrics (per-transcript LOEUF
    # observed/expected upper-bound fraction). A flat TSV (~1-2 MB)
    # used at materialize time to populate the ``gene_loeuf`` column.
    # Hosted on gnomAD's public-data GCS bucket alongside the variant
    # data. Per gnomAD's docs v4.1 fixes minor transcript-annotation
    # bugs from v4.0 and is the recommended pin.
    "gnomad-constraint": _SourceLayout(
        files=(
            _FetchFile(
                relpath="/release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv",
                output_filename="gnomad.v4.1.constraint_metrics.tsv",
            ),
        ),
    ),
    # PRS Reference Bootstrap — PGS Catalog continuous-ancestry reference
    # bundle (1000G + HGDP genotype panels). Required by ``pgsc_calc
    # --run_ancestry`` for ancestry calibration of any PRS the agent
    # surfaces (``INV-C001`` v1.7). One ~5-7 GB ``.tar.zst`` on
    # ``ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/``;
    # extracts to ~50-60 GB. The post-fetch hook streams zstd-decompress +
    # tar-extract + deletes the bundle to reclaim disk. The
    # ``presence_relpath`` marker survives the bundle deletion so ``fetch
    # --all`` skips correctly on an already-fetched dir — same structural
    # reason as ``vep_cache``.
    "pgs_catalog_ancestry": _SourceLayout(
        files=(
            _FetchFile(
                relpath=(
                    "/pub/databases/spot/pgs/resources/pgsc_HGDP+1kGP_{release}.tar.zst"
                ),
                output_filename="pgs_catalog_ancestry.tar.zst",
            ),
        ),
        post_fetch=_extract_pgs_catalog_ancestry_bundle,
        # ``GRCh38_HGDP+1kGP_ALL.pgen`` is the largest + most-essential
        # file in the extracted bundle (~12 GB; the combined GRCh38 1000G+
        # HGDP genotype matrix pgsc_calc consumes via ``--run_ancestry``).
        # Its presence is a durable signal that fetch + extraction
        # succeeded, even after the .tar.zst is removed by the post-fetch
        # hook.
        presence_relpath="GRCh38_HGDP+1kGP_ALL.pgen",
    ),
}

_DEFAULT_BASE_URLS: dict[str, str] = {
    "clinvar": "https://ftp.ncbi.nlm.nih.gov",
    "grch38": "https://ftp.ncbi.nlm.nih.gov",
    "gnomad-exomes": "https://storage.googleapis.com/gcp-public-data--gnomad",
    "dbsnp": "https://ftp.ncbi.nlm.nih.gov",
    "vep_cache": "https://ftp.ensembl.org",
    "alphamissense": "https://storage.googleapis.com",
    # LOFTEE: Broad personal-mirror at the URL the LOFTEE grch38
    # README points at. Hosts human_ancestor.fa.gz + .fai + .gzi,
    # gerp_conservation_scores.homo_sapiens.GRCh38.bw, and
    # loftee.sql.gz.
    "loftee": "https://personal.broadinstitute.org/konradk/loftee_data/GRCh38",
    # gnomAD constraint metrics — public-data GCS bucket, same root
    # as gnomad-exomes (different sub-tree).
    "gnomad-constraint": "https://storage.googleapis.com/gcp-public-data--gnomad",
    # PGS Catalog continuous-ancestry reference bundle (1000G + HGDP),
    # hosted on the EBI FTP under their PGS Catalog resources tree.
    "pgs_catalog_ancestry": "https://ftp.ebi.ac.uk",
}


def _http_get(url: str) -> bytes:
    """Fetch ``url`` and return the raw bytes. No retries, no auth.

    Kept for small, sub-MB sidecars (MD5 files) where streaming would
    add noise. Large data files use ``_stream_to_file`` so we never hold
    a multi-GB payload in memory (and so the user gets progress lines).
    """
    with urllib.request.urlopen(url) as resp:  # noqa: S310 — explicit user invocation
        return resp.read()


def _seed_md5_from_disk(path: Path) -> tuple["hashlib._Hash", int]:
    """Re-hash the already-on-disk bytes when resuming a download.

    Returns ``(hasher, bytes_so_far)`` so the resume loop can continue
    appending without re-reading the file again. Cost is O(N) over the
    bytes already on disk, which is acceptable since the resume already
    paid a network failure.
    """
    md5 = hashlib.md5()
    bytes_so_far = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            md5.update(chunk)
            bytes_so_far += len(chunk)
    return md5, bytes_so_far


def _open_attempt(url: str, *, start_offset: int) -> tuple[object, int | None, int | None, int]:
    """Open one HTTP attempt; return ``(resp, total, status, served_offset)``.

    ``total`` is the full content size (from ``Content-Length`` on a 200
    or ``Content-Range`` on a 206); ``None`` when unknown. ``status`` is
    the HTTP status code. ``served_offset`` is the byte position the
    server is actually serving from — equal to ``start_offset`` on a
    206, but ``0`` when the server ignores ``Range`` and returns 200
    with the full payload.
    """
    req = urllib.request.Request(url)
    if start_offset > 0:
        req.add_header("Range", f"bytes={start_offset}-")
    resp = urllib.request.urlopen(req)  # noqa: S310 — explicit user invocation

    status = getattr(resp, "status", None) or resp.getcode()
    cl_header = resp.headers.get("Content-Length", "")
    cl_val: int | None = None
    if cl_header.isdigit() and int(cl_header) > 0:
        cl_val = int(cl_header)

    # Content-Range: bytes <first>-<last>/<total>
    content_range = resp.headers.get("Content-Range", "")
    total: int | None = None
    served_offset = 0 if status == 200 else start_offset
    if status == 206 and "/" in content_range:
        try:
            total = int(content_range.rsplit("/", 1)[1])
        except ValueError:
            total = None
    elif status == 200 and cl_val is not None:
        total = cl_val

    return resp, total, status, served_offset


def _stream_to_file(  # noqa: PLR0913 — config-heavy entry point
    url: str,
    dest_path: Path,
    *,
    label: str,
    out_stream: object = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    max_resume_attempts: int = _DEFAULT_MAX_RESUME_ATTEMPTS,
    retry_backoff_initial_sec: float = _DEFAULT_RETRY_BACKOFF_INITIAL_SEC,
    retry_backoff_cap_sec: float = _DEFAULT_RETRY_BACKOFF_CAP_SEC,
) -> tuple[str, int, int | None]:
    """Stream ``url`` into ``dest_path``; resume on stall; verify Content-Length.

    Returns ``(md5_hexdigest, bytes_written, server_content_length)``.

    The download proceeds in attempts. The first attempt requests the
    full byte range. If the connection closes before the server's
    advertised ``Content-Length`` is reached, the function sleeps with
    exponential backoff (capped at ``retry_backoff_cap_sec``) and
    reconnects with a ``Range:`` header to resume from the byte count
    already on disk. The MD5 hasher is re-seeded from the on-disk bytes
    when resuming, so the returned digest matches a one-shot fetch.

    A server that ignores ``Range`` (responds 200 + full body on the
    resume request) is detected via the response status; the on-disk
    file is truncated and the download restarts from byte 0.

    Args:
        url: Full URL to download.
        dest_path: Scratch file path; created if absent.
        label: Short label for progress lines (e.g. ``"clinvar.vcf.gz"``).
        out_stream: Where progress lines go; defaults to ``sys.stdout``.
        on_progress: Optional callback invoked with
            ``(bytes_so_far, total_bytes_or_None)`` at the periodic
            progress interval. Stays cheap — caller is responsible for
            throttling its consumers.
        max_resume_attempts: How many ``Range`` reconnects to make
            after the first failed attempt. Default 5.
        retry_backoff_initial_sec: Sleep between attempt 1 and the first
            retry. Doubles each subsequent attempt until ``cap_sec``.
        retry_backoff_cap_sec: Upper bound on inter-retry sleep.

    Raises:
        TruncatedDownload: Server's advertised ``Content-Length`` was
            known and the on-disk file is shorter at the end of the
            attempt window.
        DownloadStalled: Every retry attempt also closed short.
    """
    if out_stream is None:
        out_stream = sys.stdout

    # Suppress the legacy ``↓ ... ✓ ...`` stdout prints when a callback
    # is provided — the callback owns user-facing output (rich
    # Progress, NDJSON stream). Without this, those lines would pollute
    # the JSON-mode stdout stream.
    quiet_stdout = on_progress is not None

    md5 = hashlib.md5()
    bytes_so_far = 0
    expected_total: int | None = None
    start = time.monotonic()
    last_progress = start

    if not quiet_stdout:
        print(f"  ↓ {label}", file=out_stream, flush=True)

    attempt = 0
    while attempt <= max_resume_attempts:
        attempt += 1

        resp, total, status, served_offset = _open_attempt(url, start_offset=bytes_so_far)

        # Server ignored our Range request — truncate + start over.
        if status == 200 and bytes_so_far > 0:
            log.info("server returned 200 on Range request; restarting from byte 0")
            md5 = hashlib.md5()
            bytes_so_far = 0
            with suppress(FileNotFoundError):
                dest_path.unlink()

        if total is not None and expected_total is None:
            expected_total = total
        elif total is not None and expected_total is not None and total != expected_total:
            log.warning(
                "Content-Length changed mid-resume (%d -> %d); trusting later value",
                expected_total,
                total,
            )
            expected_total = total

        mode: Literal["wb", "ab"] = "ab" if bytes_so_far > 0 else "wb"
        try:
            with dest_path.open(mode) as out:  # noqa: SIM117 — readability
                while True:
                    chunk = resp.read(_DOWNLOAD_CHUNK_BYTES)  # type: ignore[attr-defined]
                    if not chunk:
                        break
                    out.write(chunk)
                    md5.update(chunk)
                    bytes_so_far += len(chunk)
                    now = time.monotonic()
                    if now - last_progress >= _PROGRESS_INTERVAL_SEC:
                        if not quiet_stdout:
                            _emit_progress_line(
                                label=label,
                                bytes_so_far=bytes_so_far,
                                total=expected_total,
                                start=start,
                                out_stream=out_stream,
                            )
                        if on_progress is not None:
                            on_progress(bytes_so_far, expected_total)
                        last_progress = now
        finally:
            with suppress(Exception):
                resp.close()  # type: ignore[attr-defined]

        # Did we reach the advertised length?
        if expected_total is None or bytes_so_far >= expected_total:
            break

        # Short read — retry with Range. If we exhausted the budget,
        # the loop exit below raises.
        if attempt > max_resume_attempts:
            break

        sleep_sec = min(
            retry_backoff_initial_sec * (2 ** (attempt - 1)),
            retry_backoff_cap_sec,
        )
        log.info(
            "download stalled at %d / %d bytes; retry %d/%d in %.1fs",
            bytes_so_far,
            expected_total,
            attempt,
            max_resume_attempts,
            sleep_sec,
        )
        if sleep_sec > 0:
            time.sleep(sleep_sec)

        # Re-seed MD5 from on-disk bytes so the final digest matches a
        # one-shot fetch. The hasher walks the scratch file once, then
        # appending resumes from the next chunk.
        md5, bytes_so_far_from_disk = _seed_md5_from_disk(dest_path)
        if bytes_so_far_from_disk != bytes_so_far:  # pragma: no cover — defensive
            log.warning(
                "MD5 reseed read %d bytes; loop counter said %d; trusting disk",
                bytes_so_far_from_disk,
                bytes_so_far,
            )
            bytes_so_far = bytes_so_far_from_disk

    elapsed = time.monotonic() - start
    rate = bytes_so_far / elapsed if elapsed > 0 else 0
    if not quiet_stdout:
        print(
            f"    ✓ {_human_bytes(bytes_so_far)} in {elapsed:.1f}s ({_human_bytes(rate)}/s)",
            file=out_stream,
            flush=True,
        )

    if expected_total is not None and bytes_so_far < expected_total:
        if attempt > max_resume_attempts:
            raise DownloadStalled(
                f"{url}: stalled at {bytes_so_far} / {expected_total} bytes "
                f"after {max_resume_attempts} retries"
            )
        raise TruncatedDownload(
            f"{url}: got {bytes_so_far} bytes; server promised {expected_total}"
        )

    return md5.hexdigest(), bytes_so_far, expected_total


def _emit_progress_line(
    *,
    label: str,
    bytes_so_far: int,
    total: int | None,
    start: float,
    out_stream: object,
) -> None:
    """Print one human-readable progress line."""
    elapsed = time.monotonic() - start
    rate = bytes_so_far / elapsed if elapsed > 0 else 0
    if total:
        pct = 100.0 * bytes_so_far / total
        eta = (total - bytes_so_far) / rate if rate > 0 else 0
        line = (
            f"    {_human_bytes(bytes_so_far)}/{_human_bytes(total)} "
            f"({pct:.1f}%) @ {_human_bytes(rate)}/s  eta {eta:.0f}s"
        )
    else:
        line = f"    {_human_bytes(bytes_so_far)} @ {_human_bytes(rate)}/s"
    print(line, file=out_stream, flush=True)  # type: ignore[arg-type]


def _parse_md5_sidecar(content: bytes) -> str:
    """Extract the hex MD5 from an NCBI-style ``<hex>  <filename>`` sidecar."""
    text = content.decode().strip()
    # First whitespace-separated token is the hex digest.
    return text.split()[0].lower()


def _parse_md5_from_checksums(content: bytes, *, key: str) -> str:
    """Extract the hex MD5 for ``key`` from a multi-line ``md5checksums.txt``.

    NCBI's directory-level checksums file has one ``<hex>  ./<fname>``
    line per file in the directory; this helper finds the line whose
    second whitespace-separated token equals ``key`` (typically prefixed
    with ``./``) and returns the hash. Raises ``ChecksumMismatch`` when
    the key isn't present — same exception class as a hash divergence
    since both are checksum-time failures the caller must surface.
    """
    text = content.decode("utf-8", errors="replace")
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1] == key:
            return parts[0].lower()
    raise ChecksumMismatch(
        f"md5checksums.txt has no entry for {key!r}; the directory layout "
        f"upstream may have changed (toolkit needs a layout update)"
    )


def fetch(  # noqa: PLR0913 — top-level orchestrator
    *,
    source: str,
    reference_root: Path,
    release: str,
    base_url: str | None = None,
    chroms: tuple[str, ...] | None = None,
    progress_callback: Callable[[object], None] | None = None,
    max_resume_attempts: int = _DEFAULT_MAX_RESUME_ATTEMPTS,
    retry_backoff_initial_sec: float = _DEFAULT_RETRY_BACKOFF_INITIAL_SEC,
    retry_backoff_cap_sec: float = _DEFAULT_RETRY_BACKOFF_CAP_SEC,
    concurrent_files: int = _DEFAULT_CONCURRENT_FILES,
) -> Path:
    """Fetch ``source`` at ``release`` into ``reference_root/<source>/<release>/``.

    Args:
        source: one of the keys in ``_LAYOUTS`` (``clinvar``, ``grch38``,
            ``gnomad-exomes``, ``dbsnp``).
        reference_root: the host-side reference dir; usually
            ``/mnt/genomeclaw/reference`` or its container-bind-mounted
            equivalent under ``GENOMECLAW_REF_DIR``.
        release: the canonical version string published by the source —
            e.g. ``"2026-04"`` for ClinVar's monthly release, ``"v4.1"``
            for gnomAD-exomes, ``"b157"`` for dbSNP. Required.
        base_url: optional base URL override (test injection). When not
            given, falls back to the source's canonical published host.
        chroms: per-chromosome filter for multi-file sources
            (gnomad-exomes). When ``None``, the layout's ``default_chroms``
            applies (all 24 for gnomad-exomes). Rejected with
            ``ValueError`` for single-file sources.

    Returns:
        For single-file sources: ``Path`` to the canonical output file
        inside the new versioned dir.
        For multi-file sources: ``Path`` to the versioned dir itself
        (e.g. ``reference/gnomad-exomes/v4.1/``); files land under
        ``<target_dir>/by_chrom/`` per the layout's ``output_subdir``.

    Raises:
        ValueError: ``source`` is unknown, or ``chroms`` was passed for
            a single-file source.
        ChecksumMismatch: server-side MD5 disagrees with the downloaded
            payload (only fires for files with ``md5_relpath`` set).
        VersionAlreadyExists: any of the target output files already
            exists; re-fetching the same release is a no-op.
    """
    # fetch is the one orchestrator that needs reference/ writable; the
    # shim mounts it RW only when $1 == "fetch". Mocked tests override
    # the path via the function arg, so guard the assertion behind the
    # canonical-path default.
    from genomeclaw_toolkit.prep import preflight

    if reference_root == Path("/mnt/genomeclaw/reference"):
        preflight.assert_reference_writable()

    if source not in _LAYOUTS:
        raise ValueError(f"unknown source: {source!r}; supported: {sorted(_LAYOUTS)}")

    layout = _LAYOUTS[source]
    if chroms is not None and not layout.is_multi_file:
        raise ValueError(
            f"source {source!r} is single-file; ``chroms=`` is only valid for "
            f"per-chromosome sources (e.g. gnomad-exomes)"
        )

    target_dir = reference_root / source / release
    out_dir = target_dir / layout.output_subdir if layout.output_subdir else target_dir

    # Resolve the concrete list of files to fetch. Sources whose
    # upstream URLs embed the release tag (e.g. Ensembl's VEP cache at
    # ``/pub/release-114/.../homo_sapiens_vep_114_GRCh38.tar.gz``) use
    # ``{release}`` placeholders in their layout entries; substitute
    # here before any URL-templating happens. Single-file sources
    # (no ``{chrom}`` templating) just get the substitution applied to
    # each entry directly.
    def _apply_release(tmpl: _FetchFile) -> _FetchFile:
        return _FetchFile(
            relpath=tmpl.relpath.replace("{release_n}", release).replace("{release}", release),
            output_filename=tmpl.output_filename.replace("{release_n}", release).replace(
                "{release}", release
            ),
            md5_relpath=(
                tmpl.md5_relpath.replace("{release_n}", release).replace("{release}", release)
                if tmpl.md5_relpath is not None
                else None
            ),
            md5_checksums_relpath=(
                tmpl.md5_checksums_relpath.replace("{release_n}", release).replace(
                    "{release}", release
                )
                if tmpl.md5_checksums_relpath is not None
                else None
            ),
            md5_checksums_key=tmpl.md5_checksums_key,
            url_override=(
                tmpl.url_override.replace("{release_n}", release).replace("{release}", release)
                if tmpl.url_override is not None
                else None
            ),
        )

    files_to_fetch: list[_FetchFile] = [_apply_release(f) for f in layout.files]
    if layout.is_multi_file:
        used_chroms = chroms if chroms is not None else layout.default_chroms
        if not used_chroms:
            raise ValueError(f"source {source!r} has no chroms to fetch (empty default_chroms)")
        for c in used_chroms:
            for tmpl in layout.chrom_files:
                files_to_fetch.append(_apply_release(tmpl).for_chrom(c))

    # `INV-D001`: refuse to overwrite a previously-fetched release.
    # When the layout declares a ``presence_relpath`` marker, use it as
    # the single source of truth — this covers sources whose post-fetch
    # hook deletes the canonical artifact (e.g. vep_cache extracts and
    # removes the tarball, leaving ``homo_sapiens/<N>_GRCh38/info.txt``
    # as the durable signal of "fetched + extracted"). Otherwise fall
    # back to "any canonical file exists".
    if layout.presence_relpath is not None:
        marker_rel = layout.presence_relpath.replace("{release_n}", release).replace(
            "{release}", release
        )
        marker = target_dir / marker_rel
        if marker.exists():
            raise VersionAlreadyExists(
                f"{marker} already exists (post-fetch marker); remove "
                f"{target_dir} deliberately if you want to re-fetch (INV-D001)"
            )
    else:
        for f in files_to_fetch:
            canonical = out_dir / f.output_filename
            if canonical.exists():
                raise VersionAlreadyExists(
                    f"{canonical} already exists; remove the old version "
                    f"deliberately if you want to re-fetch (INV-D001)"
                )

    out_dir.mkdir(parents=True, exist_ok=True)
    # When the caller (a test) injects ``base_url``, suppress per-file
    # ``url_override``s so the mocked HTTP server sees every request. In
    # production ``base_url`` is None and per-file overrides apply.
    base_url_injected = base_url is not None
    resolved_base = base_url or _DEFAULT_BASE_URLS[source]

    # When a progress_callback is provided, the caller owns user-facing
    # output (rich Progress, NDJSON stream). The legacy stdout prints
    # are useful only when nothing else surfaces progress.
    quiet_stdout = progress_callback is not None
    if not quiet_stdout:
        print(
            f"  fetching {len(files_to_fetch)} file(s) into {out_dir}",
            file=sys.stdout,
            flush=True,
        )

    # Download each file; verify MD5 when sidecar present; atomic-rename.
    # Files within a source can run concurrently — they write to
    # disjoint scratch paths and the progress_callback the CLI passes
    # is already thread-safe (see ``_thread_safe_callback`` in
    # ``_cli/commands/refs.py``). Capped at ``concurrent_files`` to
    # keep TCP connection counts modest.
    overall_start = time.monotonic()
    inner_workers = max(1, min(concurrent_files, len(files_to_fetch)))

    def _fetch_one(f: _FetchFile) -> None:
        _fetch_one_file(
            f,
            resolved_base=resolved_base,
            out_dir=out_dir,
            source=source,
            allow_url_override=not base_url_injected,
            progress_callback=progress_callback,
            max_resume_attempts=max_resume_attempts,
            retry_backoff_initial_sec=retry_backoff_initial_sec,
            retry_backoff_cap_sec=retry_backoff_cap_sec,
        )

    if inner_workers == 1:
        # Sequential path — single-file source, or user passed
        # ``concurrent_files=1`` for debugging.
        for idx, f in enumerate(files_to_fetch, start=1):
            if layout.is_multi_file and not quiet_stdout:
                print(f"  [{idx}/{len(files_to_fetch)}]", file=sys.stdout, flush=True)
            _fetch_one(f)
    else:
        # Parallel path — gnomAD-exomes' 48 files (and any other
        # multi-file source) run with ``inner_workers`` threads. The
        # first failure aborts the rest gracefully via the pool's
        # context manager.
        first_exc: BaseException | None = None
        with ThreadPoolExecutor(
            max_workers=inner_workers,
            thread_name_prefix=f"fetch-{source}",
        ) as pool:
            futures = [pool.submit(_fetch_one, f) for f in files_to_fetch]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except BaseException as exc:
                    if first_exc is None:
                        first_exc = exc
        if first_exc is not None:
            raise first_exc

    # Per-source post-fetch hook (e.g. ``samtools faidx`` for grch38).
    # Failures propagate — a missing index is a fixable error the user
    # must see, not a silent skip.
    if layout.post_fetch is not None:
        if not quiet_stdout:
            print("  running post-fetch hook…", file=sys.stdout, flush=True)
        hook_start = time.monotonic()
        layout.post_fetch(target_dir)
        if not quiet_stdout:
            print(
                f"    ✓ post-fetch hook done in {time.monotonic() - hook_start:.1f}s",
                file=sys.stdout,
                flush=True,
            )

    if not quiet_stdout:
        print(
            f"  source '{source}' complete in {time.monotonic() - overall_start:.1f}s",
            file=sys.stdout,
            flush=True,
        )

    # Single-file sources return the canonical file path (Phase-2 contract);
    # multi-file sources return the version directory (per-chrom files live
    # underneath it).
    if not layout.is_multi_file:
        return out_dir / layout.files[0].output_filename
    return target_dir


def _fetch_one_file(  # noqa: PLR0912, PLR0913, PLR0915 — config-heavy entry
    f: _FetchFile,
    *,
    resolved_base: str,
    out_dir: Path,
    source: str = "",
    allow_url_override: bool = True,
    progress_callback: Callable[[object], None] | None = None,
    max_resume_attempts: int = _DEFAULT_MAX_RESUME_ATTEMPTS,
    retry_backoff_initial_sec: float = _DEFAULT_RETRY_BACKOFF_INITIAL_SEC,
    retry_backoff_cap_sec: float = _DEFAULT_RETRY_BACKOFF_CAP_SEC,
) -> None:
    """Download a single ``_FetchFile``, verify integrity, atomic-rename.

    Steps:
    1. Stream the data file via :func:`_stream_to_file` (handles resume +
       Content-Length verification).
    2. For bgzip-suffixed files, verify the canonical BGZF EOF marker;
       fail with :class:`IncompleteBgzip` if absent.
    3. Optionally fetch + verify the MD5 sidecar (per-file or directory
       checksums file) — raise :class:`ChecksumMismatch` on mismatch.
    4. Atomic-rename scratch → canonical (data first, then sidecar).

    Scratch artifacts live alongside the canonical output and are
    cleaned up on any error path so a partial download never leaves a
    corrupted canonical file behind.
    """
    canonical = out_dir / f.output_filename
    scratch_path = out_dir / f".{f.output_filename}.part"

    if allow_url_override and f.url_override is not None:
        file_url = f.url_override
    else:
        file_url = urljoin(resolved_base + "/", f.relpath.lstrip("/"))

    md5_scratch: Path | None = None
    md5_canonical: Path | None = None
    if f.md5_relpath is not None:
        md5_scratch = out_dir / f".{f.output_filename}.md5.part"
        md5_canonical = out_dir / f"{f.output_filename}.md5"
        md5_url = urljoin(resolved_base + "/", f.md5_relpath.lstrip("/"))
    elif f.md5_checksums_relpath is not None:
        md5_scratch = out_dir / f".{f.output_filename}.md5.part"
        md5_canonical = out_dir / f"{f.output_filename}.md5"
        checksums_url = urljoin(resolved_base + "/", f.md5_checksums_relpath.lstrip("/"))

    file_start = time.monotonic()

    try:
        # FileStart event with the server-reported total filled in once
        # we've opened the connection — emit a preliminary event so
        # consumers can show "started" + then update with size on first
        # progress callback.
        if progress_callback is not None:
            progress_callback(FileStart(source=source, relpath=f.output_filename, total_bytes=None))

        # Only forward an on_progress hook to ``_stream_to_file`` when a
        # real outer callback exists — otherwise ``_stream_to_file``
        # would suppress its legacy stdout prints for no reason.
        on_progress: Callable[[int, int | None], None] | None = None
        if progress_callback is not None:

            def _on_progress(bytes_so_far: int, total: int | None) -> None:
                # mypy: progress_callback is not None at this branch.
                assert progress_callback is not None
                progress_callback(
                    FileProgress(
                        source=source,
                        relpath=f.output_filename,
                        bytes_so_far=bytes_so_far,
                        total_bytes=total,
                    )
                )

            on_progress = _on_progress

        actual_md5, bytes_written, _total = _stream_to_file(
            file_url,
            scratch_path,
            label=f.output_filename,
            on_progress=on_progress,
            max_resume_attempts=max_resume_attempts,
            retry_backoff_initial_sec=retry_backoff_initial_sec,
            retry_backoff_cap_sec=retry_backoff_cap_sec,
        )

        # Bgzip-EOF check before sidecar fetch so an integrity failure
        # short-circuits the rest of the work.
        if is_bgzip_target(f.output_filename) and not verify_bgzip_eof_marker(scratch_path):
            raise IncompleteBgzip(
                f"{file_url}: downloaded {bytes_written} bytes but the canonical "
                f"BGZF EOF marker is absent; treating as truncated"
            )

        expected_md5: str | None = None
        sidecar_bytes: bytes | None = None
        if f.md5_relpath is not None:
            sidecar_bytes = _http_get(md5_url)
            expected_md5 = _parse_md5_sidecar(sidecar_bytes)
        elif f.md5_checksums_relpath is not None:
            assert f.md5_checksums_key is not None
            checksums_bytes = _http_get(checksums_url)
            expected_md5 = _parse_md5_from_checksums(checksums_bytes, key=f.md5_checksums_key)
            # Stash a single-file MD5 sidecar so the on-disk layout
            # matches the per-file sidecar mode — downstream consumers +
            # offline reanalysis don't need to know which mode produced
            # the hash, just that ``<output>.md5`` exists alongside.
            sidecar_bytes = f"{expected_md5}  {f.output_filename}\n".encode()

        if md5_scratch is not None and sidecar_bytes is not None:
            md5_scratch.write_bytes(sidecar_bytes)

        if expected_md5 is not None and expected_md5 != actual_md5:
            raise ChecksumMismatch(
                f"MD5 mismatch for {file_url}: expected {expected_md5}, got {actual_md5}"
            )

        # Atomic move into place: data first, then sidecar (so a reader
        # never observes a sidecar without its data).
        os.replace(scratch_path, canonical)
        if md5_scratch is not None and md5_canonical is not None:
            os.replace(md5_scratch, md5_canonical)

        if progress_callback is not None:
            progress_callback(
                FileComplete(
                    source=source,
                    relpath=f.output_filename,
                    bytes_written=bytes_written,
                    md5=actual_md5,
                    duration_sec=time.monotonic() - file_start,
                )
            )
    except (IncompleteBgzip, TruncatedDownload, DownloadStalled, ChecksumMismatch) as exc:
        # Integrity failure: surface a structured FileFailed event before
        # propagating. Renderer consumers (NDJSON / rich) translate
        # ``reason`` into their respective surfaces.
        if progress_callback is not None:
            reason = _failure_reason_code(exc)
            progress_callback(
                FileFailed(
                    source=source,
                    relpath=f.output_filename,
                    reason=reason,
                    message=str(exc),
                )
            )
        raise
    finally:
        # Clean up scratch files on any error path. The canonical file
        # is left untouched (this only runs before the os.replace, or
        # if a later step fails — in which case we want the partial
        # data file removed so a re-fetch starts clean).
        for stray in (scratch_path, md5_scratch):
            if stray is not None and stray.exists():
                with suppress(OSError):
                    stray.unlink()


def _failure_reason_code(exc: BaseException) -> str:
    """Map an integrity exception to its NDJSON ``reason`` discriminator."""
    if isinstance(exc, IncompleteBgzip):
        return "incomplete_bgzip"
    if isinstance(exc, TruncatedDownload):
        return "truncated"
    if isinstance(exc, DownloadStalled):
        return "stalled"
    if isinstance(exc, ChecksumMismatch):
        return "checksum_mismatch"
    return "unknown"


def remove_partial_dir(reference_root: Path, source: str, release: str) -> None:
    """Remove a versioned dir wholesale. Used by callers that want a clean
    slate after a failed fetch. Not invoked by ``fetch`` itself — failed
    fetches preserve the version dir (it may have been pre-existing) and
    only clean up their own scratch files.
    """
    target = reference_root / source / release
    if target.exists():
        shutil.rmtree(target)


__all__ = [
    "ChecksumMismatch",
    "DownloadStalled",
    "Source",
    "TruncatedDownload",
    "VersionAlreadyExists",
    "fetch",
    "remove_partial_dir",
]

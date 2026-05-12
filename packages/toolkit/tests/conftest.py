"""Shared pytest configuration for the toolkit test suite.

The ``needs_bio`` marker is the contract between the toolkit's tests and
the storage-scratch / Docker-image plan: tests that need real
``bcftools`` / ``mosdepth`` / ``samtools`` on PATH (per the MVP Phase 2
plan §Verification) run inside the ``genomeclaw/toolkit`` image, where
the CI ``toolkit-image`` job sets ``GENOMECLAW_HAS_BIO=1``. On the bare
host venv they are skipped.

A user (or developer) can opt in on a host that *does* have the bio
binaries installed by exporting ``GENOMECLAW_HAS_BIO=1`` before running
``uv run pytest``.

Session-scoped synthetic VCF / BAM / BED fixtures live here (rather than
under ``tests/integration/conftest.py``) so they are visible from every
test directory — ``tests/provenance/`` exercises them too. The fixtures
are written under ``tmp_path_factory.mktemp(...)`` and never committed to
the repo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

# Pre-flight assertions defend production by checking the canonical
# ``/mnt/genomeclaw/...`` mounts. Tests use ``tmp_path``-based paths that
# bypass those mounts entirely, so we short-circuit assertions in the
# whole test suite. Phase-3 ``test_preflight.py`` passes explicit
# ``path=`` kwargs and exercises the assertion logic directly; those
# tests don't need (and shouldn't trigger) the env-var skip.
os.environ.setdefault("GENOMECLAW_SKIP_PREFLIGHT", "1")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip ``@pytest.mark.needs_bio`` tests outside the toolkit image."""
    if os.environ.get("GENOMECLAW_HAS_BIO") == "1":
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "requires bcftools / mosdepth / samtools on PATH; "
            "set GENOMECLAW_HAS_BIO=1 to opt in (or run inside the "
            "genomeclaw/toolkit Docker image)"
        )
    )
    for item in items:
        if "needs_bio" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def has_bio_binaries() -> Iterator[bool]:
    """Test-side flag matching the marker behaviour above."""
    yield os.environ.get("GENOMECLAW_HAS_BIO") == "1"


# ---------------------------------------------------------------------------
# CLI testing helpers (available to every test directory).
# ---------------------------------------------------------------------------


import json as _json  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402


@dataclass
class CliResult:
    """Outcome of invoking the new ``genomeclaw`` CLI via the Typer runner.

    Attributes:
        exit_code: Process exit status.
        stdout: Captured stdout (JSON envelope in ``--json`` mode).
        stderr: Captured stderr (rich output / progress / errors).
    """

    exit_code: int
    stdout: str
    stderr: str

    def stdout_json(self) -> dict[str, Any]:
        """Parse stdout as JSON. Raises if it isn't valid JSON."""
        return _json.loads(self.stdout)


@pytest.fixture
def invoke_cli():
    """Return a callable invoking ``genomeclaw`` and returning a ``CliResult``.

    The callable signature: ``invoke_cli(args: list[str]) -> CliResult``.
    Routes through the real ``main()`` so the exception boundary +
    rich/JSON output dispatch + ``SystemExit`` contract are all
    exercised exactly as in production.
    """
    import contextlib
    import io

    from genomeclaw_toolkit._cli import main as cli_main
    from genomeclaw_toolkit._cli.console import reset_console

    def _invoke(args: list[str]) -> CliResult:
        # Drop any cached console so a fresh one picks up the patched
        # ``sys.stderr`` below; otherwise rich writes to the original
        # terminal and our capture buffers stay empty.
        reset_console()
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        exit_code: int = 0
        try:
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                cli_main(args)
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 0
        finally:
            reset_console()
        return CliResult(
            exit_code=exit_code,
            stdout=out_buf.getvalue(),
            stderr=err_buf.getvalue(),
        )

    return _invoke


# ---------------------------------------------------------------------------
# Synthetic VCF fixtures (Phase 2 cases 1, 4–7, 9, 10, 11, 12, 17, 18, 19).
# ---------------------------------------------------------------------------

_TINY_VCF_TEXT = """\
##fileformat=VCFv4.2
##contig=<ID=chr1,length=248956422>
##contig=<ID=chr17,length=83257441>
##INFO=<ID=DP,Number=1,Type=Integer,Description="depth">
##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ttest-001
chr1\t1000\trs1\tA\tG\t60\tPASS\t.\tGT\t0/1
chr1\t2000\t.\tC\tT\t.\tPASS\t.\tGT\t1/1
chr17\t43044295\trs28897672\tG\tA\t100\tPASS\t.\tGT\t0/1
chr17\t43044300\t.\tT\tC,G\t50\tPASS\t.\tGT\t1/2
chr17\t43094000\trs28897696\tA\tG\t75\tPASS\t.\tGT\t0/1
"""

_AMBIGUOUS_VCF_TEXT = """\
##fileformat=VCFv4.2
##contig=<ID=chr1,length=1>
##contig=<ID=chr2,length=2>
##INFO=<ID=DP,Number=1,Type=Integer,Description="depth">
##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ttest-001
chr1\t1\trs1\tA\tG\t60\tPASS\t.\tGT\t0/1
"""


def _have_bcftools() -> bool:
    return os.environ.get("GENOMECLAW_HAS_BIO") == "1" and shutil.which("bcftools") is not None


def _bgzip_and_index(vcf_text: str, out_dir: Path, *, name: str, index: bool) -> Path:
    """Write ``vcf_text`` to ``out_dir/<name>.vcf``, bgzip it, optionally index it."""
    plain = out_dir / f"{name}.vcf"
    plain.write_text(vcf_text)
    bgz = out_dir / f"{name}.vcf.gz"
    subprocess.run(
        ["bcftools", "view", "-Oz", "-o", str(bgz), str(plain)],
        check=True,
        capture_output=True,
    )
    if index:
        subprocess.run(
            ["bcftools", "index", "--tbi", str(bgz)],
            check=True,
            capture_output=True,
        )
    return bgz


@pytest.fixture(scope="session")
def tiny_vcf_gz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A bgzipped + indexed synthetic VCF with GRCh38 contigs and 5 variants."""
    if not _have_bcftools():
        pytest.skip("synthetic VCF fixture requires bcftools (set GENOMECLAW_HAS_BIO=1)")
    out_dir = tmp_path_factory.mktemp("tiny-vcf")
    return _bgzip_and_index(_TINY_VCF_TEXT, out_dir, name="tiny", index=True)


@pytest.fixture(scope="session")
def tiny_unindexed_vcf_gz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Same content as ``tiny_vcf_gz`` but without the ``.tbi`` sidecar."""
    if not _have_bcftools():
        pytest.skip("synthetic VCF fixture requires bcftools (set GENOMECLAW_HAS_BIO=1)")
    out_dir = tmp_path_factory.mktemp("tiny-unindexed")
    return _bgzip_and_index(_TINY_VCF_TEXT, out_dir, name="tiny-unindexed", index=False)


@pytest.fixture(scope="session")
def tiny_ambiguous_vcf_gz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Bgzipped + indexed VCF with contigs that don't match any known build."""
    if not _have_bcftools():
        pytest.skip("synthetic VCF fixture requires bcftools (set GENOMECLAW_HAS_BIO=1)")
    out_dir = tmp_path_factory.mktemp("tiny-ambig")
    return _bgzip_and_index(_AMBIGUOUS_VCF_TEXT, out_dir, name="tiny-ambig", index=True)


# ---------------------------------------------------------------------------
# Synthetic BAM + BED fixtures (Phase 2 cases 20, 21).
# ---------------------------------------------------------------------------

# Hand-crafted SAM with four reads on three chromosomes covering the start
# of BRCA1 (chr17:43044295), BRCA2 (chr13:32315474), and CYP2D6
# (chr22:42126499). Uses GRCh38 chr lengths in the header so a
# downstream reference-build sniffer doesn't reject the BAM. Reads are
# 100 bp of 'A' with full quality — enough for mosdepth to compute mean
# depth across the BED, nothing more.
_TINY_SAM_TEXT = (
    "@HD\tVN:1.6\tSO:coordinate\n"
    "@SQ\tSN:chr17\tLN:83257441\n"
    "@SQ\tSN:chr13\tLN:114364328\n"
    "@SQ\tSN:chr22\tLN:50818468\n"
    "read01\t0\tchr17\t43044295\t60\t100M\t*\t0\t0\t" + "A" * 100 + "\t" + "I" * 100 + "\n"
    "read02\t0\tchr17\t43044300\t60\t100M\t*\t0\t0\t" + "A" * 100 + "\t" + "I" * 100 + "\n"
    "read03\t0\tchr13\t32315474\t60\t100M\t*\t0\t0\t" + "A" * 100 + "\t" + "I" * 100 + "\n"
    "read04\t0\tchr22\t42126499\t60\t100M\t*\t0\t0\t" + "A" * 100 + "\t" + "I" * 100 + "\n"
)

_TINY_BED_TEXT = (
    "chr17\t43044294\t43125483\tBRCA1\n"
    "chr13\t32315473\t32400266\tBRCA2\n"
    "chr22\t42126498\t42130810\tCYP2D6\n"
)


def _have_samtools() -> bool:
    return os.environ.get("GENOMECLAW_HAS_BIO") == "1" and shutil.which("samtools") is not None


@pytest.fixture(scope="session")
def tiny_bam(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A tiny synthetic BAM with 4 reads on chr17/chr13/chr22, sorted + indexed."""
    if not _have_samtools():
        pytest.skip("synthetic BAM fixture requires samtools (set GENOMECLAW_HAS_BIO=1)")
    out_dir = tmp_path_factory.mktemp("tiny-bam")
    sam = out_dir / "tiny.sam"
    sam.write_text(_TINY_SAM_TEXT)
    bam = out_dir / "tiny.bam"

    view = subprocess.run(
        ["samtools", "view", "-bS", str(sam)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["samtools", "sort", "-o", str(bam)],
        input=view.stdout,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["samtools", "index", str(bam)],
        check=True,
        capture_output=True,
    )
    sam.unlink()
    return bam


@pytest.fixture(scope="session")
def tiny_genes_bed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A tiny BED listing BRCA1 / BRCA2 / CYP2D6 in GRCh38 coordinates."""
    out_dir = tmp_path_factory.mktemp("tiny-bed")
    bed = out_dir / "genes.bed"
    bed.write_text(_TINY_BED_TEXT)
    return bed


# ---------------------------------------------------------------------------
# Synthetic GRCh38 reference fasta + CRAM fixtures (Phase 4B cases 5, 6).
#
# The synthetic FASTA covers just enough of chr17 / chr13 / chr22 to
# satisfy ``bcftools norm -f`` left-alignment + ``mosdepth --fasta`` +
# CRAM reference-based decoding for the ``tiny_bam`` / ``tiny_cram``
# reads. Padding bases are 'N' (mosdepth doesn't care; CRAM round-trip
# is correct for diff-from-reference encoding regardless of base
# identity).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def tiny_grch38_fasta(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A bgzipped + ``.fai``-indexed synthetic FASTA covering the three
    BAM regions (chr17:43044295+, chr13:32315474+, chr22:42126499+)
    plus chr1 padding for left-align test variants.

    The reference content is mostly 'N' with ~200 bp of meaningful
    sequence at each region; this is enough for:
    - ``samtools faidx``: produces a usable .fai.
    - ``bcftools norm -f``: left-aligns indels against whatever bases
      are present (the left-align fixture in ``test_normalize_left_align``
      uses chr1 where the synthetic reference has 'A' bases).
    - ``mosdepth --fasta``: needs a fasta with ``.fai`` to decode CRAM.
    - ``samtools view -C --reference``: CRAM compression keys off
      reference bases; the round-trip is correct regardless of base
      content.
    """
    if not _have_samtools():
        pytest.skip("synthetic FASTA fixture requires samtools (set GENOMECLAW_HAS_BIO=1)")
    if shutil.which("bgzip") is None:
        pytest.skip("synthetic FASTA fixture requires bgzip on PATH")

    out_dir = tmp_path_factory.mktemp("tiny-grch38")
    plain = out_dir / "grch38.fa"

    # Build the FASTA. chr1 has a left-alignable A-homopolymer region
    # at positions 996–1010 used by the left-align test (single-base
    # deletion in a homopolymer is the canonical case bcftools' left-
    # aligner handles cleanly; see test_normalize_left_align). The other
    # contigs are mostly N with 'A' bases at the BAM read positions.
    def _seq(length: int, fill: str = "N") -> str:
        return fill * length

    chr1 = (
        _seq(995)
        + "A" * 15  # pos 996–1010: A-homopolymer for left-align fixture
        + _seq(1000)
        + "GCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCAT"
        + _seq(2000)
    )
    chr13 = _seq(32315474 - 1) + "A" * 200 + _seq(1000)
    chr17 = _seq(43044295 - 1) + "A" * 200 + _seq(50000) + "A" * 200 + _seq(1000)
    chr22 = _seq(42126499 - 1) + "A" * 200 + _seq(1000)

    with plain.open("w") as fh:
        for name, seq in (("chr1", chr1), ("chr13", chr13), ("chr17", chr17), ("chr22", chr22)):
            fh.write(f">{name}\n")
            for i in range(0, len(seq), 80):
                fh.write(seq[i : i + 80] + "\n")

    bgz = out_dir / "grch38.fa.gz"
    with bgz.open("wb") as fh:
        subprocess.run(
            ["bgzip", "--keep", "--stdout", str(plain)],
            check=True,
            stdout=fh,
            stderr=subprocess.PIPE,
        )
    plain.unlink()

    # samtools faidx builds .fai + .gzi (the latter for bgzipped input).
    subprocess.run(
        ["samtools", "faidx", str(bgz)],
        check=True,
        capture_output=True,
    )
    return bgz


@pytest.fixture(scope="session")
def tiny_cram(
    tiny_bam: Path,
    tiny_grch38_fasta: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """A CRAM-format copy of ``tiny_bam`` compressed against ``tiny_grch38_fasta``.

    Round-trips bit-identically to the BAM in terms of read content;
    the CRAM body is reference-based-compressed.
    """
    if not _have_samtools():
        pytest.skip("synthetic CRAM fixture requires samtools (set GENOMECLAW_HAS_BIO=1)")

    out_dir = tmp_path_factory.mktemp("tiny-cram")
    cram = out_dir / "tiny.cram"
    subprocess.run(
        [
            "samtools",
            "view",
            "-C",
            "--reference",
            str(tiny_grch38_fasta),
            "-o",
            str(cram),
            str(tiny_bam),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["samtools", "index", str(cram)],
        check=True,
        capture_output=True,
    )
    return cram


# ---------------------------------------------------------------------------
# Synthetic VCF with a left-alignable indel for the Phase 4B normalize test
# (case 5).
#
# The fixture VCF carries one single-base deletion encoded at pos 1009
# of an A-homopolymer (chr1:996-1010 in ``tiny_grch38_fasta`` is
# ``AAAAAAAAAAAAAAA``). The canonical left-aligned position is pos 995
# (one before the start of the homopolymer; bcftools shifts the anchor
# base back to the position immediately preceding the repeat). After
# ``bcftools norm -f``, the variant moves below pos 1009 — that's the
# gate.
# ---------------------------------------------------------------------------

_TINY_INDEL_VCF_TEXT = """\
##fileformat=VCFv4.2
##contig=<ID=chr1,length=248956422>
##INFO=<ID=DP,Number=1,Type=Integer,Description="depth">
##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ttest-001
chr1\t1009\t.\tAA\tA\t60\tPASS\t.\tGT\t0/1
"""


@pytest.fixture(scope="session")
def tiny_indel_vcf_gz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Bgzipped + indexed VCF carrying one not-left-aligned AT-repeat
    deletion. After ``bcftools norm -f <tiny_grch38_fasta>`` the variant
    re-positions to chr1:996 (the canonical left-aligned position)."""
    if not _have_bcftools():
        pytest.skip("synthetic indel VCF fixture requires bcftools (set GENOMECLAW_HAS_BIO=1)")
    out_dir = tmp_path_factory.mktemp("tiny-indel")
    return _bgzip_and_index(_TINY_INDEL_VCF_TEXT, out_dir, name="tiny-indel", index=True)

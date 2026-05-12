"""``mosdepth`` subprocess wrapper + per-region BED parser (spec Q7).

`mosdepth` runs against the BAM/CRAM at ingest time, computes per-gene
mean coverage from a gene-list BED, and emits ``<prefix>.regions.bed.gz``
(the file we care about) plus a few summary tables (which Phase 2 doesn't
consume but ``mosdepth`` writes regardless).

The wrapper invokes mosdepth with ``--no-per-base`` so it does **not**
emit a per-base depth track (which for a 30× WGS genome is several GB
and useless to us). Reads of the input BAM/CRAM are read-only; case 21
(`INV-D001`) asserts the SHA256 of the input is unchanged.
"""

from __future__ import annotations

import gzip
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CoverageRow:
    """One row of ``mosdepth --by genes.bed`` output, one gene per row."""

    gene: str
    mean_depth: float
    low_coverage_exons: list[str]
    """Reserved for Phase 4. Empty for gene-level Phase-2 BEDs."""


@dataclass(frozen=True)
class MosdepthResult:
    """Paths emitted by a successful ``mosdepth`` run."""

    regions_bed: Path
    summary: Path


class MosdepthError(RuntimeError):
    """A ``mosdepth`` invocation exited non-zero. Stderr is captured."""


class MosdepthParseError(ValueError):
    """``mosdepth``'s ``regions.bed.gz`` had a malformed row."""


def parse_regions_bed(regions_bed: Path) -> list[CoverageRow]:
    """Parse ``mosdepth``'s ``<prefix>.regions.bed.gz`` into ``CoverageRow``s.

    Each line is tab-separated: ``chrom start end name mean_depth``. The
    ``name`` column comes from the input BED's 4th column; we treat it
    as the gene symbol.

    Raises:
        MosdepthParseError: any row has fewer than 5 tab-separated columns.
    """
    rows: list[CoverageRow] = []
    with gzip.open(regions_bed, "rt", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                raise MosdepthParseError(f"mosdepth regions row missing columns: {line!r}")
            _chrom, _start, _end, name, mean_depth = parts[:5]
            rows.append(
                CoverageRow(
                    gene=name,
                    mean_depth=float(mean_depth),
                    low_coverage_exons=[],
                )
            )
    return rows


def run_mosdepth(
    *,
    bam: Path,
    bed: Path,
    out_prefix: Path,
    reference_fasta: Path | None = None,
) -> MosdepthResult:
    """Run ``mosdepth --no-per-base --by <bed> <prefix> <bam>``.

    Args:
        bam: source BAM or CRAM (read-only). CRAM input requires
            ``reference_fasta`` so mosdepth (via htslib) can decode the
            reference-based-compressed reads.
        bed: gene-list BED (4th column is the gene name surfaced as
            ``CoverageRow.gene``).
        out_prefix: file-name prefix; ``mosdepth`` writes
            ``<prefix>.regions.bed.gz``, ``<prefix>.mosdepth.summary.txt``,
            and a few sidecar files. Parent dir must exist.
        reference_fasta: optional reference fasta (Phase 4B). Required
            when ``bam`` is a CRAM; ignored for BAM (mosdepth doesn't
            need it). Threaded through as ``mosdepth --fasta <ref>``.

    Returns:
        Paths to the two outputs Phase-2 ingest reads.
    """
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["mosdepth", "--no-per-base", "--by", str(bed)]
    if reference_fasta is not None:
        cmd += ["--fasta", str(reference_fasta)]
    cmd += [str(out_prefix), str(bam)]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise MosdepthError(f"mosdepth failed (rc={proc.returncode}):\n{stderr_text}")

    return MosdepthResult(
        regions_bed=out_prefix.with_name(out_prefix.name + ".regions.bed.gz"),
        summary=out_prefix.with_name(out_prefix.name + ".mosdepth.summary.txt"),
    )


def mosdepth_version() -> str:
    """Capture ``mosdepth --version`` (e.g. ``"mosdepth 0.3.10"`` → ``"0.3.10"``)."""
    proc = subprocess.run(["mosdepth", "--version"], capture_output=True, check=True)
    text = proc.stdout.decode("utf-8", errors="replace").strip()
    # Output is `mosdepth 0.3.10` (single line).
    parts = text.split()
    if len(parts) >= 2 and parts[0] == "mosdepth":
        return parts[1]
    return text


__all__ = [
    "CoverageRow",
    "MosdepthError",
    "MosdepthParseError",
    "MosdepthResult",
    "mosdepth_version",
    "parse_regions_bed",
    "run_mosdepth",
]

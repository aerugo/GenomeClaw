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


def parse_regions_bed(
    regions_bed: Path,
    *,
    low_coverage_threshold: float = 20.0,
) -> list[CoverageRow]:
    """Parse ``mosdepth``'s ``<prefix>.regions.bed.gz`` into per-gene ``CoverageRow``s.

    Each line is tab-separated: ``chrom start end name mean_depth``. The
    ``name`` column comes from the input BED's 4th column. Two label
    shapes are supported:

    - **Per-gene BED** (one row per gene, label = bare gene symbol like
      ``"BRCA1"``): one CoverageRow per row, ``low_coverage_exons=[]``.
    - **Per-exon BED** (one row per exon, label =
      ``"{GENE}_exon_{N}"`` like ``"BRCA1_exon_3"``): rows are grouped
      by gene symbol, ``mean_depth`` is the un-weighted average across
      the gene's exons, and ``low_coverage_exons`` is the sorted list
      of per-exon labels whose mean_depth is below ``low_coverage_threshold``.
      The ``low_coverage_threshold`` default (20×) matches
      ``_DEFAULT_LOW_COVERAGE_THRESHOLD`` in ``ingest.py``.

    Mixed-shape BEDs (some rows per-gene, others per-exon for the same
    gene) are not supported — pick one convention per BED file.

    Raises:
        MosdepthParseError: any row has fewer than 5 tab-separated columns.
    """
    # Map gene symbol -> list of (exon_label, mean_depth). For per-gene
    # BEDs the exon_label is empty and the list has length 1.
    by_gene: dict[str, list[tuple[str, float]]] = {}
    with gzip.open(regions_bed, "rt", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                raise MosdepthParseError(f"mosdepth regions row missing columns: {line!r}")
            _chrom, _start, _end, name, mean_depth = parts[:5]
            # Per-exon label like "BRCA1_exon_3" splits to ("BRCA1", "BRCA1_exon_3");
            # per-gene label like "BRCA1" stays as ("BRCA1", "").
            if "_exon_" in name:
                gene = name.rsplit("_exon_", 1)[0]
                exon_label = name
            else:
                gene = name
                exon_label = ""
            by_gene.setdefault(gene, []).append((exon_label, float(mean_depth)))

    rows: list[CoverageRow] = []
    for gene in sorted(by_gene):
        exons = by_gene[gene]
        mean = sum(d for _, d in exons) / len(exons)
        low_exons = sorted(
            label for label, depth in exons
            if label and depth < low_coverage_threshold
        )
        rows.append(
            CoverageRow(
                gene=gene,
                mean_depth=mean,
                low_coverage_exons=low_exons,
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

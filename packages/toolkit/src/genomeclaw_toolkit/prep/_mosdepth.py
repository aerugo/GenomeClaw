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

    region_class: str = "standard"
    """Per coverage-panel-v2: the gene's coverage-reliability class
    (`"standard"` / `"difficult_pseudogene"` / `"difficult_segdup"` /
    `"requires_dedicated_caller"` / `"mitochondrial"`). Read from BED
    column 5 of the panel BED at parse time (mosdepth doesn't forward
    additional BED columns through its regions output). Defaults to
    `"standard"` when no panel BED is supplied or when the panel is a
    BED4 (pre-v2)."""


@dataclass(frozen=True)
class MosdepthResult:
    """Paths emitted by a successful ``mosdepth`` run."""

    regions_bed: Path
    summary: Path


class MosdepthError(RuntimeError):
    """A ``mosdepth`` invocation exited non-zero. Stderr is captured."""


class MosdepthParseError(ValueError):
    """``mosdepth``'s ``regions.bed.gz`` had a malformed row."""


def _load_panel_region_classes(panel_bed: Path) -> dict[str, str]:
    """Read a BED panel's column 5 (`region_class`) into a `{name: class}` lookup.

    BED4 panels (no col 5) → empty dict (every gene defaults to
    `"standard"` in the consumer). Per coverage-panel-v2 Phase 1: this
    is how the panel-derived class signal reaches `CoverageRow`, since
    mosdepth's regions output only echoes cols 1–4 of the input BED.
    """
    opener = gzip.open if panel_bed.suffix == ".gz" else open
    lookup: dict[str, str] = {}
    with opener(panel_bed, "rt", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue  # BED4 row: no class column
            name = parts[3]
            region_class = parts[4].strip()
            if name and region_class:
                lookup[name] = region_class
    return lookup


def parse_regions_bed(
    regions_bed: Path,
    *,
    low_coverage_threshold: float = 20.0,
    panel_bed: Path | None = None,
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

    Per coverage-panel-v2 Phase 1: when ``panel_bed`` is provided, the
    parser also reads BED column 5 (`region_class`) from that panel and
    sets each ``CoverageRow.region_class`` to the first non-``standard``
    value across the gene's exons. mosdepth does NOT forward additional
    BED columns through its regions output, so the class info must
    come from the panel BED directly.

    Args:
        regions_bed: mosdepth's `<prefix>.regions.bed.gz` output.
        low_coverage_threshold: per-exon depth floor (default 20×).
        panel_bed: the panel BED that was passed to ``mosdepth --by``.
            When provided, BED5 column 5 supplies the `region_class`
            for each name. Optional; absent → every row defaults to
            `region_class="standard"`.

    Raises:
        MosdepthParseError: any row has fewer than 5 tab-separated columns.
    """
    panel_classes: dict[str, str] = (
        _load_panel_region_classes(panel_bed) if panel_bed is not None else {}
    )

    # Map gene symbol -> list of (exon_label, mean_depth). For per-gene
    # BEDs the exon_label is empty and the list has length 1.
    by_gene: dict[str, list[tuple[str, float]]] = {}
    # Map gene symbol -> ordered list of region_class values from the panel
    # (across the gene's exons, in panel order). Used to surface the first
    # non-standard class — a class-uniform gene resolves cleanly; a
    # mixed-class gene preserves the non-standard signal rather than
    # averaging it away.
    by_gene_classes: dict[str, list[str]] = {}
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
            class_value = panel_classes.get(name, "standard")
            by_gene_classes.setdefault(gene, []).append(class_value)

    rows: list[CoverageRow] = []
    for gene in sorted(by_gene):
        exons = by_gene[gene]
        mean = sum(d for _, d in exons) / len(exons)
        low_exons = sorted(
            label for label, depth in exons
            if label and depth < low_coverage_threshold
        )
        # Take the first non-standard class across the gene's exons (in
        # panel order). Class-uniform genes (the common case) resolve
        # to that class; mixed-class genes (a panel-documentation gap)
        # preserve the non-standard signal rather than averaging it.
        classes = by_gene_classes.get(gene, [])
        region_class = next(
            (c for c in classes if c != "standard"),
            "standard",
        )
        rows.append(
            CoverageRow(
                gene=gene,
                mean_depth=mean,
                low_coverage_exons=low_exons,
                region_class=region_class,
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

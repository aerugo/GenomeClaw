"""`CoverageRow.region_class` + `parse_regions_bed(panel_bed=...)` (Plan 5 Phase 1).

Pure unit tests on the parser — no real mosdepth subprocess. The
mosdepth `--by` BED output echoes back columns 1-4 + the computed
mean depth in col 5; it does NOT forward additional BED columns (col
5+ of the input panel). So `region_class` cannot be read from
mosdepth's output: the parser must read it from the panel BED
directly and merge it in at parse time.

Per coverage-panel-v2/phases/phase-1.md spec.
"""

from __future__ import annotations

import gzip
from pathlib import Path


def _write_synthetic_regions_bed(path: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    """Write a mosdepth-style `<prefix>.regions.bed.gz` (gzipped, 5 tab-separated cols)."""
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for chrom, start, end, name, mean_depth in rows:
            fh.write(f"{chrom}\t{start}\t{end}\t{name}\t{mean_depth}\n")


def test_coverage_row_has_region_class_field_defaults_standard() -> None:
    """`CoverageRow` constructed without `region_class` defaults to `"standard"`."""
    from genomeclaw_toolkit.prep._mosdepth import CoverageRow

    row = CoverageRow(gene="BRCA1", mean_depth=30.0, low_coverage_exons=[])
    assert row.region_class == "standard"


def test_coverage_row_accepts_explicit_region_class() -> None:
    """`CoverageRow` can be constructed with a non-standard `region_class`."""
    from genomeclaw_toolkit.prep._mosdepth import CoverageRow

    row = CoverageRow(
        gene="PMS2",
        mean_depth=30.0,
        low_coverage_exons=[],
        region_class="difficult_pseudogene",
    )
    assert row.region_class == "difficult_pseudogene"


def test_parse_regions_bed_no_panel_arg_defaults_standard(tmp_path: Path) -> None:
    """No `panel_bed` arg → every emitted `CoverageRow` has `region_class='standard'`.

    This is the v1 BED4 backwards-compatible path.
    """
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    regions = tmp_path / "sample.regions.bed.gz"
    _write_synthetic_regions_bed(
        regions,
        [
            ("chr1", "100", "200", "BRCA1", "30.0"),
            ("chr1", "300", "400", "PMS2", "25.0"),
        ],
    )

    rows = parse_regions_bed(regions)
    assert len(rows) == 2
    for row in rows:
        assert row.region_class == "standard"


def test_parse_regions_bed_reads_region_class_from_bed5_panel(tmp_path: Path) -> None:
    """`panel_bed=<bed5>` → each gene's `region_class` reflects the panel column 5."""
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    # Synthetic BED5: chrom start end name region_class
    panel = tmp_path / "panel_v2.bed.gz"
    with gzip.open(panel, "wt") as fh:
        fh.write("chr1\t100\t200\tBRCA1\tstandard\n")
        fh.write("chr7\t300\t400\tPMS2\tdifficult_pseudogene\n")
        fh.write("chr5\t500\t600\tSMN1\trequires_dedicated_caller\n")

    regions = tmp_path / "sample.regions.bed.gz"
    _write_synthetic_regions_bed(
        regions,
        [
            ("chr1", "100", "200", "BRCA1", "30.0"),
            ("chr7", "300", "400", "PMS2", "28.5"),
            ("chr5", "500", "600", "SMN1", "22.0"),
        ],
    )

    rows = parse_regions_bed(regions, panel_bed=panel)
    by_gene = {row.gene: row for row in rows}

    assert by_gene["BRCA1"].region_class == "standard"
    assert by_gene["PMS2"].region_class == "difficult_pseudogene"
    assert by_gene["SMN1"].region_class == "requires_dedicated_caller"


def test_parse_regions_bed_bed4_panel_falls_back_to_standard(tmp_path: Path) -> None:
    """A BED4 panel (no col 5) → every row defaults to `region_class='standard'`."""
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    panel = tmp_path / "panel_v1.bed.gz"
    with gzip.open(panel, "wt") as fh:
        fh.write("chr1\t100\t200\tBRCA1\n")
        fh.write("chr7\t300\t400\tPMS2\n")

    regions = tmp_path / "sample.regions.bed.gz"
    _write_synthetic_regions_bed(
        regions,
        [
            ("chr1", "100", "200", "BRCA1", "30.0"),
            ("chr7", "300", "400", "PMS2", "28.5"),
        ],
    )

    rows = parse_regions_bed(regions, panel_bed=panel)
    for row in rows:
        assert row.region_class == "standard"


def test_parse_regions_bed_per_exon_inherits_gene_region_class(tmp_path: Path) -> None:
    """Per-exon BED entries inherit their gene's panel `region_class`.

    The panel BED's exon labels (`PMS2_exon_11`, `PMS2_exon_12`, ...) all map
    to the same gene; the gene's `CoverageRow.region_class` reflects the
    first non-standard exon class (in panel order). All PMS2 exons should
    inherit `difficult_pseudogene` from the panel.
    """
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    panel = tmp_path / "panel.bed.gz"
    with gzip.open(panel, "wt") as fh:
        fh.write("chr7\t100\t200\tPMS2_exon_11\tdifficult_pseudogene\n")
        fh.write("chr7\t300\t400\tPMS2_exon_12\tdifficult_pseudogene\n")

    regions = tmp_path / "sample.regions.bed.gz"
    _write_synthetic_regions_bed(
        regions,
        [
            ("chr7", "100", "200", "PMS2_exon_11", "30.0"),
            ("chr7", "300", "400", "PMS2_exon_12", "28.5"),
        ],
    )

    rows = parse_regions_bed(regions, panel_bed=panel)
    assert len(rows) == 1
    assert rows[0].gene == "PMS2"
    assert rows[0].region_class == "difficult_pseudogene"


def test_parse_regions_bed_mixed_classes_takes_first_nonstandard(tmp_path: Path) -> None:
    """When a gene's exons span multiple classes, the first non-standard wins.

    Defensive: real panels should be class-uniform per gene. If a panel
    has mixed classes for one gene (a documentation gap), the parser
    surfaces the non-standard signal rather than silently dropping it
    by averaging to `standard`.
    """
    from genomeclaw_toolkit.prep._mosdepth import parse_regions_bed

    panel = tmp_path / "panel.bed.gz"
    with gzip.open(panel, "wt") as fh:
        fh.write("chr7\t100\t200\tPMS2_exon_10\tstandard\n")
        fh.write("chr7\t300\t400\tPMS2_exon_11\tdifficult_pseudogene\n")
        fh.write("chr7\t500\t600\tPMS2_exon_12\tdifficult_pseudogene\n")

    regions = tmp_path / "sample.regions.bed.gz"
    _write_synthetic_regions_bed(
        regions,
        [
            ("chr7", "100", "200", "PMS2_exon_10", "30.0"),
            ("chr7", "300", "400", "PMS2_exon_11", "28.5"),
            ("chr7", "500", "600", "PMS2_exon_12", "29.0"),
        ],
    )

    rows = parse_regions_bed(regions, panel_bed=panel)
    assert len(rows) == 1
    assert rows[0].region_class == "difficult_pseudogene", (
        "first non-standard class on a gene's exons should propagate, not be averaged"
    )

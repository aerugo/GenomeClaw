"""Panel v2 content tests (Plan 5 Phase 2).

Verifies the committed `coverage_panel_default_v2.bed.gz`:
- Has BED5 format (5 tab-separated cols per row).
- Includes ACMG SF v3.3 additions (ABCD1, CYP27A1, PLN).
- Includes lifestyle anchors (MC1R, MCM6, HFE, FUT2).
- Includes mitochondrial contig row with `region_class="mitochondrial"`.
- Annotates the known difficult-region genes (PMS2, SMN1, HBA1, etc.)
  with the right `region_class` value.
- Provenance JSON has the documented v2 fields + cites GIAB MRG.

Per coverage-panel-v2/phases/phase-2.md.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path


_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "genomeclaw_toolkit"
    / "data"
)
_V2_BED = _DATA_DIR / "coverage_panel_default_v2.bed.gz"
_V2_PROV = _DATA_DIR / "coverage_panel_default_v2.bed.provenance.json"


def _read_v2_rows() -> list[tuple[str, int, int, str, str]]:
    """Parse the v2 BED into a list of (chrom, start, end, name, region_class)."""
    rows: list[tuple[str, int, int, str, str]] = []
    with gzip.open(_V2_BED, "rt", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            assert len(parts) == 5, f"non-BED5 row: {line!r}"
            chrom, start, end, name, region_class = parts
            rows.append((chrom, int(start), int(end), name, region_class))
    return rows


def _v2_genes() -> set[str]:
    """Return the set of unique gene symbols in the v2 panel."""
    genes: set[str] = set()
    for *_rest, name, _cls in _read_v2_rows():
        gene = name.rsplit("_exon_", 1)[0] if "_exon_" in name else name
        genes.add(gene)
    return genes


def test_panel_v2_bed_exists() -> None:
    """`coverage_panel_default_v2.bed.gz` is committed to package data."""
    assert _V2_BED.exists(), f"v2 panel not found at {_V2_BED}"
    assert _V2_PROV.exists(), f"v2 provenance JSON not found at {_V2_PROV}"


def test_panel_v2_is_bed5() -> None:
    """Every row of the v2 panel is BED5 (5 tab-separated cols)."""
    rows = _read_v2_rows()
    assert len(rows) >= 2000  # v1 had 2798 rows; v2 adds more
    for chrom, start, end, name, region_class in rows:
        assert chrom
        assert end > start
        assert name
        assert region_class in {
            "standard",
            "difficult_pseudogene",
            "difficult_segdup",
            "requires_dedicated_caller",
            "mitochondrial",
        }


def test_panel_v2_has_acmg_sf_v33_added_genes() -> None:
    """ACMG SF v3.3 additions present: ABCD1, CYP27A1, PLN."""
    genes = _v2_genes()
    for gene in ("ABCD1", "CYP27A1", "PLN"):
        assert gene in genes, f"ACMG SF v3.3 gene {gene} missing from v2 panel"


def test_panel_v2_has_lifestyle_anchors() -> None:
    """Lifestyle anchors present: MC1R, MCM6, HFE, FUT2."""
    genes = _v2_genes()
    for gene in ("MC1R", "MCM6", "HFE", "FUT2"):
        assert gene in genes, f"Lifestyle anchor {gene} missing from v2 panel"


def test_panel_v2_has_mitochondrial_row() -> None:
    """At least one chrM row with `region_class="mitochondrial"`."""
    mt_rows = [
        row for row in _read_v2_rows() if row[0] in ("chrM", "chrMT")
    ]
    assert mt_rows, "no mitochondrial row in v2 panel"
    assert all(row[4] == "mitochondrial" for row in mt_rows)


def test_panel_v2_difficult_regions_annotated() -> None:
    """Known difficult-region genes carry the expected `region_class`.

    Per coverage-panel-v2 + the bioinformatics-review-2026-05-25:
    short-read WGS coverage is misleading for these genes; the agent
    must see a non-`standard` class flag.
    """
    rows = _read_v2_rows()
    by_gene: dict[str, set[str]] = {}
    for *_rest, name, region_class in rows:
        gene = name.rsplit("_exon_", 1)[0] if "_exon_" in name else name
        by_gene.setdefault(gene, set()).add(region_class)

    expected = {
        "PMS2": "difficult_pseudogene",
        "GBA": "difficult_pseudogene",  # panel symbol; HGNC: GBA1
        "CYP21A2": "difficult_pseudogene",
        "STRC": "difficult_pseudogene",
        "NCF1": "difficult_pseudogene",
        "HBA1": "difficult_segdup",
        "HBA2": "difficult_segdup",
        "NEB": "difficult_segdup",
        "SMN1": "requires_dedicated_caller",
        "SMN2": "requires_dedicated_caller",
        "CYP2D6": "requires_dedicated_caller",
        "HLA-A": "requires_dedicated_caller",
        "HLA-B": "requires_dedicated_caller",
        "HLA-C": "requires_dedicated_caller",
        "HLA-DRB1": "requires_dedicated_caller",
    }
    for gene, expected_class in expected.items():
        assert gene in by_gene, f"difficult-region gene {gene} missing from v2 panel"
        assert expected_class in by_gene[gene], (
            f"{gene}: expected {expected_class}; got {by_gene[gene]!r}"
        )


def test_panel_v2_provenance_json_documents_v3_3_and_giab() -> None:
    """v2 provenance JSON cites ACMG SF v3.3 + GIAB MRG (Wagner et al. 2022)."""
    prov = json.loads(_V2_PROV.read_text())
    assert prov["version"] == "v2"
    assert prov["schema"] == "bed5_v1"
    assert prov["gene_count"] >= 170
    sources_text = json.dumps(prov["source"])
    assert "ACMG_SF_v3.3" in sources_text or "ACMG SF v3.3" in sources_text.replace("_", " ")
    assert "ABCD1" in sources_text
    assert "GIAB" in sources_text or "Wagner" in sources_text
    distribution = prov["region_class_distribution"]
    assert distribution["standard"] > 0
    assert distribution["mitochondrial"] >= 1
    assert distribution.get("difficult_pseudogene", 0) >= 1
    assert distribution.get("requires_dedicated_caller", 0) >= 1


def test_panel_v2_default_panel_constant_is_v2() -> None:
    """ingest.py's `_DEFAULT_PANEL_BED_NAME` points at the v2 BED file.

    Switching the default is the operational signal that v2 is live.
    The constant is a single source of truth — the orchestrator reads
    it to locate the bundled panel asset.
    """
    from genomeclaw_toolkit.prep.ingest import (
        _DEFAULT_PANEL_BED_NAME,
        _DEFAULT_PANEL_VERSION,
    )

    assert _DEFAULT_PANEL_BED_NAME == "coverage_panel_default_v2.bed.gz"
    assert _DEFAULT_PANEL_VERSION == "v2"

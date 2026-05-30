#!/usr/bin/env python3
"""Build `coverage_panel_default_v2.bed.gz` + its provenance JSON.

coverage-panel-v2 Phase 2 — the v2 panel extends v1 with:

1. **A 5th BED column (`region_class`)** carrying per-region
   coverage-reliability classification:
   - `standard` — short-read WGS gives reliable coverage
   - `difficult_pseudogene` — paralogous-pseudogene interference
     (PMS2/PMS2CL, GBA1/GBAP1, CYP21A2/CYP21A1P, STRC/STRCP1,
     NCF1/NCF1B/NCF1C)
   - `difficult_segdup` — segmental-duplication / VNTR
     (HBA1/HBA2 α-globin segdup, NEB triplicate repeat)
   - `requires_dedicated_caller` — short-read coverage is misleading;
     a dedicated caller is the truth source (SMN1/SMN2 → SMA-callers,
     CYP2D6 → Cyrius, HLA → HLA callers)
   - `mitochondrial` — MT contig (heteroplasmy semantics differ from
     nuclear; aminoglycoside-ototoxicity check via MT-RNR1)

2. **ACMG SF v3.3 additions** (Lee et al., *Genetics in Medicine*
   27(8):101454, July 2025): ABCD1, CYP27A1, PLN. v1 was pinned to
   ACMG SF v3.2 (73 genes); v3.3 brings the total to 84 ACMG SF genes.
   Note: of those 84, ~57 were already in v1 via the disease-area
   panels + ACMG v3.2 union; v2 adds the 3 v3.3-new entries.

3. **Lifestyle / population-genetics anchors**: MC1R (skin/hair),
   MCM6 (LCT lactase-persistence regulator), HFE (hemochromatosis),
   FUT2 (secretor status). These are the most-asked-about lifestyle
   genes in consumer-genomics contexts.

4. **Mitochondrial contig**: a single full-MT row (`chrM:0-16569`)
   so heteroplasmy-style coverage QC can be surfaced. CPIC's
   MT-RNR1 aminoglycoside-ototoxicity guideline depends on this.

The v1 BED's per-exon coordinates are preserved verbatim; only the
5th column is added. New genes from §2-3 are added as **single-row
gene-level entries** (no exon enumeration) using canonical hg38
RefSeq coordinates — sufficient for mosdepth's mean-depth purpose
and avoids needing a fresh GENCODE GTF download at script time.

INV-D009 (proposed): any gene/region in the panel that intersects
the GIAB challenging-MRG BED carries a non-`standard` `region_class`.
This script applies a hardcoded overlay table for the well-known
difficult regions; the GIAB-intersection invariant test
(`tests/invariants/test_invD009_panel_giab_intersection.py`)
verifies the overlay is complete for genes present in the GIAB
challenging-MRG bundle when that BED is fetched locally.

Rebuild command (from the repo root):
    uv run python scripts/build_coverage_panel_v2.py

Outputs:
    packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.gz
    packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v2.bed.provenance.json
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Difficult-region overlay table
# ---------------------------------------------------------------------------
#
# Source: GIAB challenging medically relevant genes (Wagner et al.,
# Nat Biotechnol 2022, doi:10.1038/s41587-021-01158-1) + the
# bioinformatics-review-2026-05-25 enumeration. Each entry's class
# value is the canonical short-read-WGS failure mode:
#
# - difficult_pseudogene: a paralogous pseudogene interferes with
#   short-read mapping; mosdepth depth looks fine but variant calls
#   are unreliable.
# - difficult_segdup: segmental duplication (HBA1/HBA2 α-globin) or
#   VNTR (NEB triplicate repeat) interferes similarly.
# - requires_dedicated_caller: short-read coverage QC is structurally
#   insufficient; the agent must route to a dedicated caller (Cyrius
#   for CYP2D6; HLA-LA / Optitype for HLA; SMA-callers for SMN1).

_DIFFICULT_REGIONS: dict[str, str] = {
    # Pseudogene interference
    "PMS2": "difficult_pseudogene",  # PMS2CL pseudogene; exons 11-15 uncallable
    "GBA": "difficult_pseudogene",  # GBAP1 pseudogene (panel symbol; HGNC: GBA1)
    "GBA1": "difficult_pseudogene",
    "CYP21A2": "difficult_pseudogene",  # CYP21A1P pseudogene
    "STRC": "difficult_pseudogene",  # STRCP1 pseudogene
    "NCF1": "difficult_pseudogene",  # NCF1B/NCF1C pseudogenes
    # Segdup / VNTR
    "HBA1": "difficult_segdup",  # α-globin segdup
    "HBA2": "difficult_segdup",
    "NEB": "difficult_segdup",  # nemaline-myopathy triplicate repeat
    # Dedicated callers required
    "SMN1": "requires_dedicated_caller",  # SMN1/SMN2 paralog problem
    "SMN2": "requires_dedicated_caller",
    "CYP2D6": "requires_dedicated_caller",  # Cyrius (already wired)
    "HLA-A": "requires_dedicated_caller",
    "HLA-B": "requires_dedicated_caller",
    "HLA-C": "requires_dedicated_caller",
    "HLA-DRB1": "requires_dedicated_caller",
}


# ---------------------------------------------------------------------------
# v2-new gene-level entries (no exon enumeration; single canonical row)
# ---------------------------------------------------------------------------
#
# ACMG SF v3.3 additions: ABCD1, CYP27A1, PLN. Coordinates from NCBI
# RefSeq GRCh38.p14 (HGNC-canonical genomic span). Lifestyle anchors:
# MC1R, MCM6, HFE, FUT2 from the same source.
#
# Format: (chrom, start, end, gene_symbol, region_class)

_V2_NEW_GENES: list[tuple[str, int, int, str, str]] = [
    # ACMG SF v3.3 new entries
    ("chrX", 153724867, 153744755, "ABCD1", "standard"),
    ("chr2", 218770821, 218811815, "CYP27A1", "standard"),
    ("chr6", 118548435, 118573491, "PLN", "standard"),
    # Lifestyle / population-genetics anchors
    ("chr16", 89918937, 89920964, "MC1R", "standard"),
    ("chr2", 135839625, 135876495, "MCM6", "standard"),  # LCT regulator
    ("chr6", 26087280, 26098571, "HFE", "standard"),
    ("chr19", 48695974, 48705951, "FUT2", "standard"),
    # Difficult-region genes flagged by _DIFFICULT_REGIONS but NOT in v1.
    # Coordinates from NCBI RefSeq GRCh38.p14 gene-level spans. These
    # are added as gene-level single-row entries so mean-depth coverage
    # QC is still reported, but with the `region_class` marker telling
    # the agent the depth alone is misleading (use the dedicated
    # caller / interpret the segdup caveat).
    ("chr16", 226678, 227519, "HBA1", "difficult_segdup"),
    ("chr16", 222845, 223709, "HBA2", "difficult_segdup"),
    ("chr2", 151485335, 151734476, "NEB", "difficult_segdup"),
    ("chr6", 32038388, 32041670, "CYP21A2", "difficult_pseudogene"),
    ("chr15", 43594023, 43614360, "STRC", "difficult_pseudogene"),
    ("chr7", 74775065, 74790065, "NCF1", "difficult_pseudogene"),
    ("chr5", 70924889, 70953014, "SMN1", "requires_dedicated_caller"),
    ("chr5", 69345349, 69373420, "SMN2", "requires_dedicated_caller"),
    ("chr6", 29942469, 29945883, "HLA-A", "requires_dedicated_caller"),
    ("chr6", 31353870, 31357211, "HLA-B", "requires_dedicated_caller"),
    ("chr6", 31268747, 31272136, "HLA-C", "requires_dedicated_caller"),
    ("chr6", 32578768, 32589836, "HLA-DRB1", "requires_dedicated_caller"),
]


# ---------------------------------------------------------------------------
# Mitochondrial contig: one full-MT row.
# ---------------------------------------------------------------------------
#
# The MT contig is 16569 bp (rCRS / NC_012920.1). One coverage row
# spanning the full MT is sufficient for the aminoglycoside-ototoxicity
# (MT-RNR1) check; per-gene MT enumeration is a future refinement.

_MT_ROW: tuple[str, int, int, str, str] = ("chrM", 0, 16569, "chrM_full", "mitochondrial")


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_V1_PATH = (
    _REPO_ROOT
    / "packages"
    / "toolkit"
    / "src"
    / "genomeclaw_toolkit"
    / "data"
    / "coverage_panel_default_v1.bed.gz"
)
_V2_PATH = _V1_PATH.with_name("coverage_panel_default_v2.bed.gz")
_PROV_PATH = _V1_PATH.with_name("coverage_panel_default_v2.bed.provenance.json")


def _v1_label_to_region_class(name: str) -> str:
    """Map a v1 BED row label to its v2 `region_class`.

    Per-exon labels (`PMS2_exon_11`) → use the gene symbol prefix.
    Per-gene labels (`BRCA1`) → use the symbol directly.
    Default → `"standard"`.
    """
    if "_exon_" in name:
        gene = name.rsplit("_exon_", 1)[0]
    else:
        gene = name
    return _DIFFICULT_REGIONS.get(gene, "standard")


def build_v2_panel() -> tuple[Path, Path]:
    """Build `coverage_panel_default_v2.bed.gz` + provenance JSON. Returns both paths."""
    if not _V1_PATH.exists():
        raise FileNotFoundError(f"v1 panel BED not found at {_V1_PATH}")

    # Load v1 rows: (chrom, start, end, name).
    v1_rows: list[tuple[str, int, int, str]] = []
    with gzip.open(_V1_PATH, "rt", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            chrom = parts[0]
            start = int(parts[1])
            end = int(parts[2])
            name = parts[3]
            v1_rows.append((chrom, start, end, name))

    # Build v2 row set: v1 rows with region_class overlay + new genes + MT.
    v2_rows: list[tuple[str, int, int, str, str]] = []
    for chrom, start, end, name in v1_rows:
        region_class = _v1_label_to_region_class(name)
        v2_rows.append((chrom, start, end, name, region_class))
    v2_rows.extend(_V2_NEW_GENES)
    v2_rows.append(_MT_ROW)

    # Sort: chrom lexicographic (chrM at end), then start numeric.
    def _sort_key(row: tuple[str, int, int, str, str]) -> tuple[int, str, int]:
        chrom = row[0]
        # Put chrM / chrMT after autosomes + sex chroms for stable ordering.
        if chrom in ("chrM", "chrMT"):
            order = 2
        elif chrom in ("chrX", "chrY"):
            order = 1
        else:
            order = 0
        return (order, chrom, row[1])

    v2_rows.sort(key=_sort_key)

    # Write v2 BED.gz (BED5, tab-separated).
    with gzip.open(_V2_PATH, "wt", encoding="utf-8") as fh:
        for chrom, start, end, name, region_class in v2_rows:
            fh.write(f"{chrom}\t{start}\t{end}\t{name}\t{region_class}\n")

    # Stats for provenance JSON.
    gene_set: set[str] = set()
    for _chrom, _start, _end, name, _cls in v2_rows:
        gene = name.rsplit("_exon_", 1)[0] if "_exon_" in name else name
        gene_set.add(gene)
    row_count = len(v2_rows)
    gene_count = len(gene_set)
    classes_counter: dict[str, int] = {}
    for *_rest, region_class in v2_rows:
        classes_counter[region_class] = classes_counter.get(region_class, 0) + 1

    provenance = {
        "version": "v2",
        "created_at": date.today().isoformat(),
        "schema": "bed5_v1",
        "source": {
            "gene_list": [
                {
                    "source": "coverage_panel_default_v1 (carried forward)",
                    "ref": "packages/toolkit/src/genomeclaw_toolkit/data/"
                    "coverage_panel_default_v1.bed.provenance.json",
                    "description": "All 160 v1 genes preserved with their GENCODE v44 "
                    "MANE Select exon coordinates; region_class column added per "
                    "_DIFFICULT_REGIONS overlay where applicable.",
                },
                {
                    "source": "ACMG_SF_v3.3",
                    "url": "https://www.gimjournal.org/article/S1098-3600(25)00148-X/fulltext",
                    "citation": "Lee et al., Genetics in Medicine 27(8):101454, 2025-07-09",
                    "added_genes": ["ABCD1", "CYP27A1", "PLN"],
                    "description": "ACMG SF v3.3 update from v3.2 adds 3 genes; total ACMG SF "
                    "set now 84 genes. v2 panel carries the 3 new entries as gene-level "
                    "rows (no per-exon split) with canonical hg38 RefSeq coordinates.",
                },
                {
                    "source": "Lifestyle / population-genetics anchors",
                    "added_genes": ["MC1R", "MCM6", "HFE", "FUT2"],
                    "description": "The most-asked-about lifestyle genes in consumer-"
                    "genomics contexts. MC1R: skin/hair pigmentation. MCM6: LCT "
                    "lactase-persistence regulatory region. HFE: hemochromatosis. "
                    "FUT2: secretor status. Gene-level coordinates; coverage QC suffices.",
                },
                {
                    "source": "Mitochondrial contig",
                    "added_regions": [{"chrom": "chrM", "start": 0, "end": 16569}],
                    "description": "Full MT contig (rCRS / NC_012920.1, 16569 bp). "
                    "Supports CPIC MT-RNR1 aminoglycoside-ototoxicity coverage QC. "
                    "Per-MT-gene enumeration is a future refinement.",
                },
            ],
            "difficult_region_annotations": {
                "source": "Hardcoded overlay table (scripts/build_coverage_panel_v2.py "
                "::_DIFFICULT_REGIONS); cross-references GIAB challenging-MRG "
                "(Wagner et al., Nat Biotechnol 2022) + the "
                "bioinformatics-review-2026-05-25 difficult-region enumeration.",
                "url": "https://www.nature.com/articles/s41587-021-01158-1",
                "classes_used": sorted(set(_DIFFICULT_REGIONS.values())),
                "genes_annotated": sorted(_DIFFICULT_REGIONS.keys()),
            },
            "exon_coordinates": {
                "source": "GENCODE v44 (inherited from v1 panel rows)",
                "build": "GRCh38",
                "transcript_selection": "MANE Select",
            },
            "build_script": "scripts/build_coverage_panel_v2.py",
        },
        "gene_count": gene_count,
        "row_count": row_count,
        "region_class_distribution": classes_counter,
        "low_coverage_threshold_default": "20x",
        "curation_notes": "v2 extends v1 with: (a) BED5 region_class column, (b) ACMG SF v3.3 "
        "additions ABCD1/CYP27A1/PLN, (c) lifestyle anchors MC1R/MCM6/HFE/FUT2, "
        "(d) MT contig row. The hardcoded difficult-region overlay flags PMS2, "
        "SMN1/SMN2, HBA1/HBA2, CYP21A2, GBA1, STRC, NCF1, NEB, HLA-A/B/C/DRB1, "
        "CYP2D6 as non-standard so the agent's coverage-status surface "
        "(genomeclaw_gene) cannot falsely reassure the user that mosdepth "
        "mean_depth alone is sufficient. INV-D009 (proposed) verifies the overlay "
        "is complete against GIAB challenging-MRG (Wagner et al., 2022).",
    }
    with _PROV_PATH.open("w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, sort_keys=False)
        fh.write("\n")

    return _V2_PATH, _PROV_PATH


def main() -> None:
    bed_path, prov_path = build_v2_panel()
    print(f"Wrote: {bed_path}")
    print(f"Wrote: {prov_path}")
    print(f"  built_at: {datetime.now(UTC).isoformat()}")


if __name__ == "__main__":
    main()

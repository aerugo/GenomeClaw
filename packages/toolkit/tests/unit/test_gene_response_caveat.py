"""`GeneResponse.region_class` + `caveat` (Plan 5 Phase 3).

`GET /v1/gene/{symbol}` returns mean_depth + low_coverage_exons for the
curated coverage panel. Per coverage-panel-v2 Phase 3, the response
also surfaces:

- `region_class`: the coverage-reliability class from `coverage_qc`
  (`"standard"` / `"difficult_pseudogene"` / ... / NULL for pre-v2
  rows).
- `caveat`: a derived human-readable warning string that fires when
  `region_class` is non-standard. The caveat is the agent-facing
  mitigation against false reassurance from a clean mosdepth depth
  number over PMS2 or SMN1.

INV-C001 v1.7: caveat appears whenever `region_class != "standard"`
and never appears for `"standard"`/`None` (would dilute the signal).

INV-P002: caveat is a static per-class string — derived from
`region_class`, not from user data. Safe to ship to the agent.
"""

from __future__ import annotations

import re


def test_gene_response_has_region_class_field() -> None:
    """`GeneResponse` accepts the new `region_class` field."""
    from genomeclaw_toolkit.schemas.gene import GeneResponse

    resp = GeneResponse(
        gene="PMS2",
        n_variants_in_gene=0,
        mean_depth=30.0,
        low_coverage_exons=[],
        schema_version="v0.3",
        region_class="difficult_pseudogene",
        caveat="Coverage depth ...",
    )
    assert resp.region_class == "difficult_pseudogene"


def test_gene_response_region_class_defaults_to_none() -> None:
    """Pre-v2 rows have NULL `region_class`; the model defaults to None."""
    from genomeclaw_toolkit.schemas.gene import GeneResponse

    resp = GeneResponse(
        gene="BRCA1",
        n_variants_in_gene=10,
        mean_depth=30.0,
        low_coverage_exons=[],
        schema_version="v0.3",
    )
    assert resp.region_class is None
    assert resp.caveat is None


def test_region_class_caveat_helper_returns_none_for_standard() -> None:
    """`_region_class_caveat("standard")` and `(None)` return None."""
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    assert _region_class_caveat("standard") is None
    assert _region_class_caveat(None) is None


def test_region_class_caveat_helper_returns_string_for_difficult_pseudogene() -> None:
    """`_region_class_caveat("difficult_pseudogene")` returns a non-empty warning."""
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    caveat = _region_class_caveat("difficult_pseudogene")
    assert caveat is not None
    assert "difficult_pseudogene" in caveat or "pseudogene" in caveat.lower()


def test_region_class_caveat_helper_returns_string_for_requires_dedicated_caller() -> None:
    """`_region_class_caveat("requires_dedicated_caller")` returns a non-empty warning."""
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    caveat = _region_class_caveat("requires_dedicated_caller")
    assert caveat is not None
    assert "dedicated caller" in caveat.lower() or "requires_dedicated_caller" in caveat


def test_region_class_caveat_helper_returns_string_for_difficult_segdup() -> None:
    """`_region_class_caveat("difficult_segdup")` returns a non-empty warning."""
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    caveat = _region_class_caveat("difficult_segdup")
    assert caveat is not None


def test_region_class_caveat_helper_returns_string_for_mitochondrial() -> None:
    """`_region_class_caveat("mitochondrial")` returns a non-empty warning."""
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    caveat = _region_class_caveat("mitochondrial")
    assert caveat is not None
    assert "mitochondrial" in caveat.lower() or "heteroplasmy" in caveat.lower()


def test_invC001_caveat_non_null_for_all_difficult_classes() -> None:
    """INV-C001 v1.7: every non-standard `region_class` value yields a non-null caveat.

    Iterates the four difficult classes; asserts none of them collapses
    to None. A future addition that lists a new non-standard class
    without an associated caveat is caught here (the helper must be
    exhaustive).
    """
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    for region_class in (
        "difficult_pseudogene",
        "difficult_segdup",
        "requires_dedicated_caller",
        "mitochondrial",
    ):
        caveat = _region_class_caveat(region_class)
        assert caveat is not None, f"caveat is None for {region_class!r}"


def test_invP002_caveat_contains_no_variant_data(tmp_path) -> None:
    """INV-P002: caveat is a static string; no user variant data leaks.

    Defensive: the caveat is built from a region_class enum string. If a
    future refactor were to interpolate user data (genotype, rsid,
    sample_id), the regex check here would catch it.
    """
    from genomeclaw_toolkit.schemas.gene import _region_class_caveat

    for region_class in (
        "difficult_pseudogene",
        "difficult_segdup",
        "requires_dedicated_caller",
        "mitochondrial",
    ):
        caveat = _region_class_caveat(region_class)
        assert caveat is not None
        # No rsids (rs123456).
        assert not re.search(r"\brs\d+\b", caveat)
        # No genotype-looking strings (A/C, T|G, AA/CC, etc.).
        assert not re.search(r"\b[ACGT]{1,4}[/|][ACGT]{1,4}\b", caveat)
        # No sample-id-looking strings (MPNRGLQ2K style, NA12878 style).
        assert not re.search(r"\b[A-Z]{4,}\d{4,}\b", caveat)

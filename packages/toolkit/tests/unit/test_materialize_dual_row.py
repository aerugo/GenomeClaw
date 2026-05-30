"""`_consequence_tier` + `_extract_dual_vep_rows` unit tests (Plan 4 Phase 2).

Pure-function tests against synthetic `CsqEntry` tuples — no VCF I/O,
no bcftools/cyvcf2 dependency. The full-pipeline integration test
(materialize against a fixture annotated VCF) lives behind the
`@pytest.mark.needs_bio` gate and runs as part of Phase 3's real-data
smoke; the scoping note in `work-notes.md` documents the deferral.

The dual-row emit logic yields:
- 1 row when both MANE_SELECT and MANE_PLUS_CLINICAL are absent.
- 1 row when only one of MANE_SELECT / MANE_PLUS_CLINICAL is present.
- 1 row when both are present AND have the same consequence IMPACT tier.
- 2 rows when both are present AND have differing consequence IMPACT tiers
  (the row pair carries `transcript_discordant=False` on the Select row
  and `transcript_discordant=True` on the Plus Clinical row).

Per phase-2.md spec; INV-E001 + INV-R001 invariants covered.
"""

from __future__ import annotations

from genomeclaw_toolkit.prep._csq import split_csq


_CSQ_FIELDS = (
    "MANE_SELECT",
    "MANE_PLUS_CLINICAL",
    "CANONICAL",
    "IMPACT",
    "Consequence",
    "SYMBOL",
)


def test_consequence_tier_high_is_3() -> None:
    from genomeclaw_toolkit.prep.materialize import _consequence_tier

    assert _consequence_tier("HIGH") == 3


def test_consequence_tier_moderate_is_2() -> None:
    from genomeclaw_toolkit.prep.materialize import _consequence_tier

    assert _consequence_tier("MODERATE") == 2


def test_consequence_tier_low_is_1() -> None:
    from genomeclaw_toolkit.prep.materialize import _consequence_tier

    assert _consequence_tier("LOW") == 1


def test_consequence_tier_modifier_is_0() -> None:
    from genomeclaw_toolkit.prep.materialize import _consequence_tier

    assert _consequence_tier("MODIFIER") == 0


def test_consequence_tier_unknown_returns_0() -> None:
    """Empty string + None + unknown literal all map to 0 (lowest tier)."""
    from genomeclaw_toolkit.prep.materialize import _consequence_tier

    assert _consequence_tier("") == 0
    assert _consequence_tier(None) == 0
    assert _consequence_tier("UNRECOGNIZED") == 0


def test_extract_dual_vep_rows_no_mane_fields_yields_single_row() -> None:
    """CANONICAL=YES only → 1 row; `transcript_discordant` is None."""
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    # Schema: MANE_SELECT|MANE_PLUS_CLINICAL|CANONICAL|IMPACT|Consequence|SYMBOL
    entries = split_csq("||YES|MODERATE|missense_variant|BRCA1", _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    assert len(rows) == 1
    assert rows[0].get("transcript_discordant") is None
    assert rows[0].get("gene_symbol") == "BRCA1"


def test_extract_dual_vep_rows_mane_select_only_yields_single_row() -> None:
    """MANE Select alone → 1 row; `transcript_discordant` is None."""
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    entries = split_csq("NM_001.1||NO|MODERATE|missense_variant|BRCA1", _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    assert len(rows) == 1
    assert rows[0].get("mane_select_transcript") == "NM_001.1"
    assert rows[0].get("transcript_discordant") is None


def test_extract_dual_vep_rows_plus_clinical_only_yields_single_row() -> None:
    """MANE Plus Clinical alone → 1 row; `transcript_discordant` is None."""
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    entries = split_csq("|NM_002.1|NO|HIGH|stop_gained|TCF3", _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    assert len(rows) == 1
    assert rows[0].get("mane_plus_clinical_transcript") == "NM_002.1"
    assert rows[0].get("transcript_discordant") is None


def test_extract_dual_vep_rows_same_tier_yields_single_row() -> None:
    """Select + PlusClinical with same IMPACT tier → 1 row (Select takes precedence)."""
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    csq_concat = (
        "NM_001.1||NO|MODERATE|missense_variant|TCF3,"
        "|NM_002.1|NO|MODERATE|splice_region_variant|TCF3"
    )
    entries = split_csq(csq_concat, _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    assert len(rows) == 1
    assert rows[0].get("transcript_discordant") is None
    assert rows[0].get("mane_select_transcript") == "NM_001.1"


def test_extract_dual_vep_rows_different_tier_yields_two_rows() -> None:
    """Select + PlusClinical with differing IMPACT tiers → 2 rows.

    Row A (Select transcript): `transcript_discordant=False`.
    Row B (Plus Clinical transcript): `transcript_discordant=True`.
    Both carry the gene symbol from their respective CSQ entry.
    """
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    csq_concat = (
        "NM_001.1||NO|LOW|synonymous_variant|TCF3,"
        "|NM_002.1|NO|HIGH|stop_gained|TCF3"
    )
    entries = split_csq(csq_concat, _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    assert len(rows) == 2
    select_row, plus_row = rows
    assert select_row.get("mane_select_transcript") == "NM_001.1"
    assert select_row.get("transcript_discordant") is False
    assert select_row.get("consequence") == "synonymous_variant"
    assert plus_row.get("mane_plus_clinical_transcript") == "NM_002.1"
    assert plus_row.get("transcript_discordant") is True
    assert plus_row.get("consequence") == "stop_gained"


def test_invE001_dual_rows_carry_evidence_columns() -> None:
    """INV-E001: every emitted row carries the CSQ-derived transcript as evidence.

    The dual-row pair's evidence anchor is split across the two rows: Row A
    carries `mane_select_transcript`; Row B carries `mane_plus_clinical_transcript`.
    A row with NEITHER would be unfounded and is forbidden by INV-E001.
    """
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    csq_concat = (
        "NM_001.1||NO|LOW|synonymous_variant|TCF3,"
        "|NM_002.1|NO|HIGH|stop_gained|TCF3"
    )
    entries = split_csq(csq_concat, _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    for row in rows:
        has_evidence = bool(row.get("mane_select_transcript")) or bool(
            row.get("mane_plus_clinical_transcript")
        )
        assert has_evidence, (
            f"INV-E001 violation: dual-row emit produced a row with no MANE "
            f"transcript anchor; row={row!r}"
        )


def test_extract_dual_vep_rows_empty_entries_yields_no_rows() -> None:
    """Empty CSQ → no rows emitted (caller handles the missing-CSQ branch)."""
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    rows = list(_extract_dual_vep_rows((), _CSQ_FIELDS))
    assert rows == []


def test_extract_dual_vep_rows_dual_pair_share_gene_symbol() -> None:
    """Both rows of a dual-row pair carry the gene symbol from their respective CSQ entry."""
    from genomeclaw_toolkit.prep.materialize import _extract_dual_vep_rows

    csq_concat = (
        "NM_001.1||NO|LOW|synonymous_variant|TCF3,"
        "|NM_002.1|NO|HIGH|stop_gained|TCF3"
    )
    entries = split_csq(csq_concat, _CSQ_FIELDS)
    rows = list(_extract_dual_vep_rows(entries, _CSQ_FIELDS))

    assert all(row.get("gene_symbol") == "TCF3" for row in rows), (
        f"both rows should share gene_symbol; got {[r.get('gene_symbol') for r in rows]!r}"
    )


def test_variants_ddl_carries_mane_plus_clinical_columns() -> None:
    """Schema gate: `_VARIANT_DOMAIN_COLUMNS` and `_VARIANTS_DDL` declare both new columns.

    Phase 2 adds the columns to the DDL without bumping SCHEMA_VERSION
    (Phase 3 owns the version bump + migration test). The
    `_reset_variants_table` path picks up these additions automatically.
    """
    from genomeclaw_toolkit.prep.store import _VARIANT_DOMAIN_COLUMNS, _VARIANTS_DDL

    domain_names = {name for name, _ddl, _null in _VARIANT_DOMAIN_COLUMNS}
    assert "mane_plus_clinical_transcript" in domain_names
    assert "transcript_discordant" in domain_names
    assert "mane_plus_clinical_transcript" in _VARIANTS_DDL
    assert "transcript_discordant" in _VARIANTS_DDL

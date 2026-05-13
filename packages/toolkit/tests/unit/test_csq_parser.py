"""Unit tests for ``prep._csq`` — VEP CSQ INFO field parser.

The CSQ format is positional: each consequence is a pipe-separated
mini-string whose field order is declared in the VCF's ``##INFO=<ID=CSQ,
...,Description="Format: A|B|C|...">``. Materialize uses this parser to
extract Phase-4D typed columns (gene_symbol, mane_select_transcript,
hgvsc, hgvsp, consequence, loftee_lof, loftee_filter,
alphamissense_score, alphamissense_class) from each variant's CSQ string.

These tests are pure-Python — no VEP binary, no fixture files — so
they exercise the parser's edge cases without the bio image.
"""

from __future__ import annotations

import pytest

from genomeclaw_toolkit.prep._csq import (
    csq_entry_to_columns,
    parse_csq_header,
    pick_canonical_entry,
    split_csq,
)

# ---------------------------------------------------------------------------
# parse_csq_header
# ---------------------------------------------------------------------------


def test_parse_csq_header_extracts_pipe_separated_field_list() -> None:
    """The Format: substring is parsed into a per-position field tuple."""
    line = (
        '##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations'
        " from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene|"
        'Feature_type|Feature|BIOTYPE|HGVSc|HGVSp|MANE_SELECT|CANONICAL">'
    )
    fields = parse_csq_header(line)
    assert fields == (
        "Allele",
        "Consequence",
        "IMPACT",
        "SYMBOL",
        "Gene",
        "Feature_type",
        "Feature",
        "BIOTYPE",
        "HGVSc",
        "HGVSp",
        "MANE_SELECT",
        "CANONICAL",
    )


def test_parse_csq_header_raises_on_line_without_format_substring() -> None:
    """A non-VEP INFO line surfaces as ValueError instead of silently returning ()."""
    with pytest.raises(ValueError, match="Format:"):
        parse_csq_header('##INFO=<ID=CSQ,Number=.,Type=String,Description="not a vep line">')


# ---------------------------------------------------------------------------
# split_csq
# ---------------------------------------------------------------------------


def test_split_csq_single_consequence_returns_one_entry() -> None:
    """A CSQ value with no inner commas produces exactly one CsqEntry."""
    fields = ("Allele", "Consequence", "SYMBOL", "MANE_SELECT")
    entries = split_csq("A|missense_variant|BRCA1|ENST00000357654.9", fields)
    assert len(entries) == 1
    assert entries[0].by_name == {
        "Allele": "A",
        "Consequence": "missense_variant",
        "SYMBOL": "BRCA1",
        "MANE_SELECT": "ENST00000357654.9",
    }


def test_split_csq_multiple_consequences_split_on_comma() -> None:
    """VEP emits one consequence per matching transcript; each becomes a CsqEntry."""
    fields = ("Allele", "Consequence", "SYMBOL", "MANE_SELECT")
    entries = split_csq(
        "A|missense_variant|BRCA1|ENST00000357654.9,A|intron_variant|BRCA1|",
        fields,
    )
    assert len(entries) == 2
    assert entries[0].by_name["Consequence"] == "missense_variant"
    assert entries[0].by_name["MANE_SELECT"] == "ENST00000357654.9"
    assert entries[1].by_name["Consequence"] == "intron_variant"
    assert entries[1].by_name["MANE_SELECT"] is None  # empty → None


def test_split_csq_empty_fields_map_to_none() -> None:
    """VEP's ``""`` placeholder for "no value" lands as None, not the empty string."""
    fields = ("Allele", "SYMBOL", "HGVSc", "HGVSp")
    entries = split_csq("A|BRCA1||", fields)
    assert entries[0].by_name == {
        "Allele": "A",
        "SYMBOL": "BRCA1",
        "HGVSc": None,
        "HGVSp": None,
    }


def test_split_csq_empty_value_returns_empty_tuple() -> None:
    """An empty CSQ value is degenerate; return () so the caller short-circuits."""
    assert split_csq("", ("Allele", "Consequence")) == ()


def test_split_csq_pads_when_entry_has_fewer_tokens_than_header() -> None:
    """A malformed entry (truncated mid-pipe) doesn't crash — missing fields become None."""
    fields = ("Allele", "Consequence", "SYMBOL", "MANE_SELECT")
    entries = split_csq("A|missense_variant", fields)
    assert len(entries) == 1
    assert entries[0].by_name == {
        "Allele": "A",
        "Consequence": "missense_variant",
        "SYMBOL": None,
        "MANE_SELECT": None,
    }


def test_split_csq_truncates_when_entry_has_more_tokens_than_header() -> None:
    """Extra tokens (e.g. CSQ format drift between runs) are silently dropped."""
    fields = ("Allele", "SYMBOL")
    entries = split_csq("A|BRCA1|extra|more", fields)
    assert entries[0].by_name == {"Allele": "A", "SYMBOL": "BRCA1"}


# ---------------------------------------------------------------------------
# pick_canonical_entry
# ---------------------------------------------------------------------------


def test_pick_canonical_prefers_mane_select_entry() -> None:
    """MANE Select wins over CANONICAL+first when present."""
    fields = ("MANE_SELECT", "CANONICAL", "SYMBOL")
    entries = split_csq(
        "|YES|first_match,ENST_MANE|YES|mane_match,|YES|canonical_only",
        fields,
    )
    chosen = pick_canonical_entry(entries)
    assert chosen is not None
    assert chosen.by_name["SYMBOL"] == "mane_match"


def test_pick_canonical_falls_through_to_canonical_yes_when_no_mane() -> None:
    """CANONICAL=YES wins when no MANE_SELECT entry exists."""
    fields = ("MANE_SELECT", "CANONICAL", "SYMBOL")
    entries = split_csq("|YES|canonical,|NO|other", fields)
    chosen = pick_canonical_entry(entries)
    assert chosen is not None
    assert chosen.by_name["SYMBOL"] == "canonical"


def test_pick_canonical_falls_through_to_first_when_no_canonical_marker() -> None:
    """First entry wins when neither MANE_SELECT nor CANONICAL flagged.

    VEP's ``--pick`` output is already ranked by impact severity, so
    "first" is a sensible canonical default.
    """
    fields = ("MANE_SELECT", "CANONICAL", "SYMBOL")
    entries = split_csq("||first,||second", fields)
    chosen = pick_canonical_entry(entries)
    assert chosen is not None
    assert chosen.by_name["SYMBOL"] == "first"


def test_pick_canonical_returns_none_for_empty_input() -> None:
    """Empty entry tuple → None (caller should treat as "no canonical")."""
    assert pick_canonical_entry(()) is None


# ---------------------------------------------------------------------------
# csq_entry_to_columns
# ---------------------------------------------------------------------------


def test_csq_entry_to_columns_extracts_all_phase4d_columns() -> None:
    """End-to-end: a populated CsqEntry → fully-typed Phase-4D column dict."""
    fields = (
        "Allele",
        "Consequence",
        "SYMBOL",
        "MANE_SELECT",
        "CANONICAL",
        "HGVSc",
        "HGVSp",
        "LoF",
        "LoF_filter",
        "am_pathogenicity",
        "am_class",
    )
    entries = split_csq(
        "A|missense_variant|BRCA1|ENST00000357654.9|YES|"
        "ENST00000357654.9:c.181T>G|ENSP00000350283.3:p.Cys61Gly|"
        "HC|PHYLOCSF_WEAK|0.857|likely_pathogenic",
        fields,
    )
    cols = csq_entry_to_columns(entries[0])
    assert cols["gene_symbol"] == "BRCA1"
    assert cols["mane_select_transcript"] == "ENST00000357654.9"
    assert cols["hgvsc"] == "ENST00000357654.9:c.181T>G"
    assert cols["hgvsp"] == "ENSP00000350283.3:p.Cys61Gly"
    assert cols["consequence"] == "missense_variant"
    assert cols["loftee_lof"] == "HC"
    assert cols["loftee_filter"] == "PHYLOCSF_WEAK"
    assert cols["alphamissense_score"] == pytest.approx(0.857)
    assert cols["alphamissense_class"] == "likely_pathogenic"
    # LOEUF is reserved for the gnomAD-constraint follow-up — always None here.
    assert cols["gene_loeuf"] is None


def test_csq_entry_to_columns_handles_partial_data() -> None:
    """Missing fields (CSQ header smaller than full Phase-4D field set) become None."""
    fields = ("Allele", "Consequence", "SYMBOL", "MANE_SELECT")
    entries = split_csq("A|synonymous_variant|BRCA1|", fields)
    cols = csq_entry_to_columns(entries[0])
    assert cols["gene_symbol"] == "BRCA1"
    assert cols["consequence"] == "synonymous_variant"
    assert cols["mane_select_transcript"] is None
    assert cols["hgvsc"] is None
    assert cols["alphamissense_score"] is None


def test_csq_entry_to_columns_alphamissense_score_coerces_to_float() -> None:
    """am_pathogenicity is stored as REAL — string ``"0.123"`` becomes ``0.123``."""
    fields = ("am_pathogenicity",)
    entries = split_csq("0.123", fields)
    cols = csq_entry_to_columns(entries[0])
    assert isinstance(cols["alphamissense_score"], float)
    assert cols["alphamissense_score"] == pytest.approx(0.123)


def test_csq_entry_to_columns_alphamissense_score_none_for_unparseable() -> None:
    """Garbage am_pathogenicity → None, not a crash."""
    fields = ("am_pathogenicity",)
    entries = split_csq("not_a_number", fields)
    cols = csq_entry_to_columns(entries[0])
    assert cols["alphamissense_score"] is None

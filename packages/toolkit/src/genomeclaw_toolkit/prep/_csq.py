"""VEP ``CSQ`` INFO field parser.

VEP doesn't emit individual INFO fields per annotation — it packs every
per-transcript prediction into a single ``CSQ`` mega-string. The header
declares the field order::

    ##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations
     from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene|...">

and each variant's record carries one entry per matching transcript,
separated by ``,``::

    CSQ=A|missense_variant|MODERATE|BRCA1|ENSG...|Transcript|ENST...|...
       ,A|intron_variant|MODIFIER|BRCA1|ENSG...|Transcript|ENST...|...

Materialize needs to (a) figure out the field order from the header,
(b) pick one canonical consequence per variant (the MANE Select
transcript when present; otherwise the ``--pick`` default), and (c)
extract the Phase-4D columns into typed scalar values.

This module is pure-Python with no bioinformatics dependencies — every
parsing decision is unit-testable on synthetic CSQ strings without
needing a real VEP binary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_CSQ_HEADER_RE = re.compile(r"Format:\s*([\w|]+)", re.IGNORECASE)


def parse_csq_header(info_header_line: str) -> tuple[str, ...]:
    """Extract the pipe-separated field name list from a CSQ ``##INFO`` line.

    The line shape::

        ##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence
         annotations from Ensembl VEP. Format: Allele|Consequence|...">

    We pluck the ``Format: <fields>`` substring out of the description.
    The returned tuple matches the per-entry pipe-separated layout
    used in every record's CSQ value, so positional lookups (extract
    field N for each consequence) are trivial.

    Raises:
        ValueError: the line doesn't have a parseable ``Format: ...``
            description (i.e. it isn't a VEP-emitted CSQ header).
    """
    match = _CSQ_HEADER_RE.search(info_header_line)
    if match is None:
        raise ValueError(
            f"could not find ``Format: <fields>`` in CSQ header line: {info_header_line!r}"
        )
    raw = match.group(1)
    return tuple(raw.split("|"))


@dataclass(frozen=True)
class CsqEntry:
    """One consequence entry (one transcript) from a CSQ value.

    ``raw`` is the original pipe-separated string; ``by_name`` is the
    same data zipped against the header's field order. Empty fields
    (VEP emits ``""`` for "no value at this position") map to None in
    ``by_name`` so callers don't have to special-case the empty string.
    """

    raw: str
    by_name: Mapping[str, str | None]


def split_csq(value: str, fields: tuple[str, ...]) -> tuple[CsqEntry, ...]:
    """Split a CSQ INFO value into one :class:`CsqEntry` per consequence.

    The value's outer separator is ``,`` (between consequences); the
    inner separator is ``|`` (between fields). When the number of inner
    tokens doesn't match ``len(fields)`` we pad/truncate to the header
    length so positional lookups remain valid — surfacing the mismatch
    as a downstream NULL column is better than crashing the materialize
    loop on one malformed record.
    """
    if not value:
        return ()
    entries: list[CsqEntry] = []
    for chunk in value.split(","):
        parts = chunk.split("|")
        # Normalise to header length: pad with "" or drop trailing.
        if len(parts) < len(fields):
            parts = parts + [""] * (len(fields) - len(parts))
        elif len(parts) > len(fields):
            parts = parts[: len(fields)]
        by_name: dict[str, str | None] = {
            name: (p if p else None) for name, p in zip(fields, parts, strict=True)
        }
        entries.append(CsqEntry(raw=chunk, by_name=by_name))
    return tuple(entries)


def pick_canonical_entry(entries: tuple[CsqEntry, ...]) -> CsqEntry | None:
    """Pick the canonical consequence per variant.

    Order of preference:

    1. The entry with a non-empty ``MANE_SELECT`` field (the
       transcript Phase 4D explicitly pins via ``--mane_select``).
    2. The entry flagged ``CANONICAL`` == ``YES`` (VEP's "this is the
       canonical transcript" boolean).
    3. The first entry (VEP's ``--pick`` output is already ranked by
       impact severity).

    Returns ``None`` when ``entries`` is empty.
    """
    if not entries:
        return None
    for entry in entries:
        if entry.by_name.get("MANE_SELECT"):
            return entry
    for entry in entries:
        if entry.by_name.get("CANONICAL") == "YES":
            return entry
    return entries[0]


# SpliceAI's score is encoded as a pipe-separated mini-string inside the
# CSQ entry's SpliceAI_pred field:
#   SpliceAI_pred = "ALLELE|SYMBOL|DS_AG|DS_AL|DS_DG|DS_DL|DP_AG|DP_AL|DP_DG|DP_DL"
# The four DS_* columns are the per-event delta scores (acceptor gain /
# acceptor loss / donor gain / donor loss). The "max delta" we surface
# is the max of those four.
_SPLICEAI_PRED_FIELDS: tuple[str, ...] = (
    "ALLELE",
    "SYMBOL",
    "DS_AG",
    "DS_AL",
    "DS_DG",
    "DS_DL",
    "DP_AG",
    "DP_AL",
    "DP_DG",
    "DP_DL",
)


def extract_spliceai_max_delta(spliceai_pred_value: str | None) -> float | None:
    """Compute the max delta score from a SpliceAI_pred CSQ value.

    Returns the max of ``DS_AG / DS_AL / DS_DG / DS_DL`` (the four
    per-event delta scores), or ``None`` when the value is absent or
    malformed. We coerce every parseable float and take the max; if no
    DS_* token parses, returns None.

    Note on separators: SpliceAI_pred's plugin documentation declares
    a pipe-separated format (``ALLELE|SYMBOL|DS_AG|...``), but VEP
    escapes embedded ``|`` characters to ``&`` when writing CSQ values
    (CSQ's outer separator is also ``|``, so the inner pipe would
    collide). We accept both: try ``&`` first (the VEP-escaped form),
    then ``|`` as a fallback for plugin outputs that didn't go through
    CSQ escaping.
    """
    if not spliceai_pred_value:
        return None
    parts = spliceai_pred_value.split("&")
    if len(parts) == 1:
        # No ``&`` — try the un-escaped pipe form (e.g. SpliceAI emitted
        # as a top-level INFO field rather than wrapped in CSQ).
        parts = spliceai_pred_value.split("|")
    # Pad to header length so positional lookups are safe.
    if len(parts) < len(_SPLICEAI_PRED_FIELDS):
        parts = parts + [""] * (len(_SPLICEAI_PRED_FIELDS) - len(parts))
    scores: list[float] = []
    for key in ("DS_AG", "DS_AL", "DS_DG", "DS_DL"):
        token = parts[_SPLICEAI_PRED_FIELDS.index(key)]
        if not token or token == ".":
            continue
        try:
            scores.append(float(token))
        except ValueError:
            continue
    return max(scores) if scores else None


# Phase-4D CSQ field-name → variants-table column-name mapping.
# Keys are the field names VEP emits in the CSQ header (these depend on
# the flag set + active plugins); values are the schema column names.
# A field absent from a given run's CSQ header maps to a NULL column —
# the parser silently drops unknown keys, the materialize loop sees a
# None and writes empty into the staging CSV.
_DIRECT_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("SYMBOL", "gene_symbol"),
    ("MANE_SELECT", "mane_select_transcript"),
    ("HGVSc", "hgvsc"),
    ("HGVSp", "hgvsp"),
    ("Consequence", "consequence"),
    ("LoF", "loftee_lof"),
    ("LoF_filter", "loftee_filter"),
    ("am_pathogenicity", "alphamissense_score"),  # AlphaMissense plugin
    ("am_class", "alphamissense_class"),
)


def csq_entry_to_columns(entry: CsqEntry) -> dict[str, Any]:
    """Extract Phase-4D variants-table columns from one :class:`CsqEntry`.

    Returns a dict whose keys match :mod:`store`'s
    ``_VARIANT_DOMAIN_COLUMNS`` column names. Values are typed:

    - ``alphamissense_score`` and ``spliceai_max_delta`` are ``float | None``.
    - everything else is ``str | None``.

    Fields absent from the entry (the CSQ header didn't have them, or
    VEP emitted ``""`` for this transcript) map to ``None``. The
    materialize CSV writer renders ``None`` as the empty CSV field,
    which DuckDB's COPY parses as SQL NULL.
    """
    columns: dict[str, Any] = {}
    for csq_name, sql_name in _DIRECT_FIELD_MAP:
        value = entry.by_name.get(csq_name)
        if sql_name == "alphamissense_score":
            columns[sql_name] = _safe_float(value)
        else:
            columns[sql_name] = value
    spliceai_pred = entry.by_name.get("SpliceAI_pred")
    columns["spliceai_max_delta"] = extract_spliceai_max_delta(spliceai_pred)
    # ``gene_loeuf`` is reserved for the gnomAD-constraint integration;
    # always NULL until that lands.
    columns["gene_loeuf"] = None
    return columns


def _safe_float(value: str | None) -> float | None:
    """Best-effort float parse: returns None on empty / ``.`` / non-numeric input."""
    if value is None or value == "" or value == ".":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CsqEntry",
    "csq_entry_to_columns",
    "extract_spliceai_max_delta",
    "parse_csq_header",
    "pick_canonical_entry",
    "split_csq",
]

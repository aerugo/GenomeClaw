"""Minimal VCF reader for Phase 2 ingest.

Two callables:

- ``read_contigs(path)`` returns a list of ``(name, length)`` pairs for
  the reference-build sniffer.
- ``iter_variant_rows(path)`` yields one dict per data line, shaped to
  match ``prep.store.write_variants``'s row contract.

The reader transparently handles plain ``.vcf`` and gzipped ``.vcf.gz``
files (both vanilla gzip and bgzip — bgzip's multi-block layout is
gzip-compatible for sequential reads). Phase 3's ``bcftools norm`` step
takes over for any serious VCF processing; this reader is deliberately
small.

Phase 2 ingest is single-sample by convention. Multi-sample VCFs raise
``ValueError`` rather than silently dropping samples.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

_CONTIG_RE = re.compile(r"^##contig=<([^>]*)>")
_KV_RE = re.compile(r"(\w+)=([^,]+)")


def _open_vcf(path: Path) -> TextIO:
    """Return a text-mode handle for a plain or gzipped VCF."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def read_contigs(path: Path) -> list[tuple[str, int]]:
    """Extract ``(contig_id, length)`` pairs from the VCF header.

    Lines without an explicit ``length=`` are silently skipped — they
    do not contribute to reference-build sniffing.
    """
    out: list[tuple[str, int]] = []
    with _open_vcf(path) as fh:
        for line in fh:
            if not line.startswith("##"):
                # Header is contiguous; first non-`##` line ends it.
                break
            m = _CONTIG_RE.match(line)
            if not m:
                continue
            kv = dict(_KV_RE.findall(m.group(1)))
            if "ID" not in kv or "length" not in kv:
                continue
            try:
                length = int(kv["length"])
            except ValueError:
                continue
            out.append((kv["ID"], length))
    return out


def _parse_qual(token: str) -> float | None:
    return None if token == "." else float(token)


def _parse_id(token: str) -> str | None:
    return None if token == "." else token


def _extract_gt(format_field: str, sample_field: str) -> str | None:
    """Pick the ``GT`` value out of a colon-separated FORMAT/sample pair.

    Returns ``None`` when GT is absent (a sites-only or annotation-only VCF).
    """
    fields = format_field.split(":")
    values = sample_field.split(":")
    for name, value in zip(fields, values, strict=False):
        if name == "GT":
            return value
    return None


def _parse_info(info: str, *, fields: tuple[str, ...]) -> dict[str, str | None]:
    """Extract requested INFO ``KEY=VALUE`` fields from a VCF INFO column.

    ``info`` is the raw 8th column of a VCF data line (e.g.
    ``"DP=30;CLNSIG=Pathogenic"``). Missing / unset INFO is the literal
    ``"."``. Returns a dict containing exactly the requested keys, with
    ``None`` for keys not present.
    """
    out: dict[str, str | None] = dict.fromkeys(fields)
    if info == "." or not info:
        return out
    for entry in info.split(";"):
        if "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        if key in out:
            out[key] = value
    return out


def iter_variant_rows(
    path: Path,
    *,
    info_fields: tuple[str, ...] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield one dict per VCF data line.

    The dict keys match ``prep.store.write_variants``'s row contract:
    ``chrom``, ``pos``, ``id``, ``ref``, ``alt``, ``qual``, ``filter``,
    ``sample_id``, ``genotype``. Multi-allelic ``alt`` values are
    preserved as-is (Phase 3 splits them).

    When ``info_fields`` is supplied, each requested ``KEY`` from the
    INFO column is added to the row dict under the same name; missing
    keys land as ``None``. Phase-4A ``annotate`` populates the
    ``clinvar_classification`` and ``clinvar_review_status`` INFO
    fields, which materialize then surfaces into the variants table's
    annotation columns.
    """
    info_fields = info_fields or ()
    sample_id: str | None = None
    has_format = False

    with _open_vcf(path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line:
                continue

            if line.startswith("##"):
                continue

            if line.startswith("#CHROM"):
                cols = line.split("\t")
                # Single-sample contract: 8 fixed cols, optional FORMAT (col 9),
                # exactly one sample column (col 10).
                if len(cols) > 10:
                    raise ValueError(
                        f"Phase 2 ingest is single-sample; got {len(cols) - 9} sample columns"
                    )
                if len(cols) == 10:
                    has_format = True
                    sample_id = cols[9]
                continue

            cols = line.split("\t")
            if len(cols) < 8:
                # Malformed data line — skip (defensive; spec-conformant
                # VCFs always have at least 8 fixed cols).
                continue

            chrom, pos_s, id_, ref, alt, qual, filt, info_col = cols[:8]
            genotype: str | None = None
            if has_format and len(cols) >= 10:
                genotype = _extract_gt(cols[8], cols[9])

            row: dict[str, Any] = {
                "chrom": chrom,
                "pos": int(pos_s),
                "id": _parse_id(id_),
                "ref": ref,
                "alt": alt,
                "qual": _parse_qual(qual),
                "filter": filt,
                "sample_id": sample_id,
                "genotype": genotype,
            }
            if info_fields:
                row.update(_parse_info(info_col, fields=info_fields))
            yield row


__all__ = ["iter_variant_rows", "read_contigs"]

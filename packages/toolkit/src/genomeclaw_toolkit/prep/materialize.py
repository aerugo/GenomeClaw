"""``genomeclaw pipeline materialize`` orchestration.

Reads ``run_dir/normalized.vcf.gz`` (produced by ``normalize``) and
rewrites the ``variants`` table in ``run_dir/variants.duckdb`` from it.
Multi-allelic rows that ingest stored as-is are now single-alt rows
(``bcftools norm -m-`` did the splitting).

`INV-D001`: the normalized VCF is read-only here; we only write to the
DuckDB store. `INV-R001`: every row carries the seven canonical
provenance columns; ``source_path`` + ``source_sha256`` reflect the
normalized-VCF identity (the immediate input that produced these rows).
The full chain — source VCF → bcftools norm → normalized VCF → variants
— is recoverable via ``provenance.json``.

The ``coverage_qc`` and ``schema_meta`` tables are untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from genomeclaw_toolkit import __version__ as TOOLKIT_VERSION
from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._csq import (
    csq_entry_to_columns,
    parse_csq_header,
    pick_canonical_entry,
    split_csq,
)
from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart, emit_beat
from genomeclaw_toolkit.prep._vcf import iter_variant_rows
from genomeclaw_toolkit.prep.scratch import shard_scratch
from genomeclaw_toolkit.prep.store import _VARIANTS_DDL, ProvenanceTag, write_variants
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit.prep._events import _ProgressEvent

log = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialise_for_json(value: object) -> object:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unserialisable: {value!r}")


def _read_csq_header_if_present(vcf: Path) -> tuple[str, ...] | None:
    """Scan a VCF's header for ``##INFO=<ID=CSQ,...>``; return the field list.

    Returns the pipe-separated field-name tuple parsed out of the CSQ
    description's ``Format: ...`` substring, or ``None`` when no CSQ
    INFO line is present (typical for pre-VEP runs where the annotated
    VCF is just the vcfanno output).

    Reads the header only — stops as soon as the first non-``##`` line
    is seen — so the cost is one-time and tiny regardless of file size.
    """
    import gzip

    opener = gzip.open if str(vcf).endswith(".gz") else open
    with opener(vcf, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("##"):
                break
            if line.startswith("##INFO=<ID=CSQ,"):
                try:
                    return parse_csq_header(line)
                except ValueError:
                    log.warning("malformed CSQ header in %s; ignoring", vcf)
                    return None
    return None


def _extract_vep_columns(
    csq_value: str | None, csq_fields: tuple[str, ...] | None
) -> dict[str, Any]:
    """Parse one CSQ value into the Phase-4D typed column dict.

    When ``csq_value`` or ``csq_fields`` is None, returns an empty dict
    (the materialize CSV writer interprets missing nullable columns as
    NULL). When both are present, picks the canonical consequence
    (MANE Select → CANONICAL=YES → first) and extracts the columns.
    """
    if csq_value is None or csq_fields is None:
        return {}
    entries = split_csq(csq_value, csq_fields)
    canonical = pick_canonical_entry(entries)
    if canonical is None:
        return {}
    return csq_entry_to_columns(canonical)


def _reset_variants_table(store_path: Path) -> None:
    """Drop and recreate the ``variants`` table on the current schema, and
    bump ``schema_meta.schema_version`` to match.

    Materialize fully rewrites the variants table from the (possibly
    annotated) VCF, so its rows are sourced anew on every call. That
    means we can drop+recreate the table here and transparently upgrade
    a v0.1 store to v0.2 (or any future schema bump that only touches
    the variants table). ``coverage_qc`` and ``schema_meta`` keep their
    rows; only the ``schema_version`` value is updated.
    """
    conn = duckdb.connect(str(store_path))
    try:
        conn.execute("DROP TABLE IF EXISTS variants")
        conn.execute(_VARIANTS_DDL)
        conn.execute("DELETE FROM schema_meta WHERE key = ?", ["schema_version"])
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ["schema_version", SCHEMA_VERSION],
        )
    finally:
        conn.close()


def materialize(
    *,
    run_dir: Path,
    started_at: datetime | None = None,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path:
    """Rewrite the ``variants`` table from the run's normalized VCF.

    Args:
        run_dir: an existing ``derived/<run-id>/`` from a prior
            ``ingest`` + ``normalize``. Must contain ``normalized.vcf.gz``,
            ``manifest.json``, ``provenance.json``, and ``variants.duckdb``.
        started_at: optional fixed UTC timestamp; defaults to
            ``datetime.now(tz=UTC)``. Tests pass a fixed value to drive
            determinism.

    Returns:
        Path to ``run_dir/variants.duckdb``.
    """
    preflight.assert_raw_readonly()
    preflight.assert_reference_readonly()
    preflight.assert_derived_writable()
    preflight.assert_scratch_writable()

    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in run dir: {run_dir}")

    norm_vcf = run_dir / "normalized.vcf.gz"
    if not norm_vcf.exists():
        raise FileNotFoundError(
            f"normalized.vcf.gz not found in {run_dir}; run `genomeclaw pipeline normalize` first"
        )

    if started_at is None:
        started_at = datetime.now(tz=UTC)

    phase_start_mono = time.monotonic()
    if progress_callback is not None:
        progress_callback(PhaseStart(phase="materialize"))

    # Prefer the annotated VCF when present so the materialized variants
    # table carries the v0.2 ClinVar annotation columns. Fall back to
    # the post-normalize VCF (rows have NULL annotation columns).
    annotated_vcf = run_dir / "annotated.vcf.gz"
    if annotated_vcf.exists():
        materialize_input = annotated_vcf
        materialize_input_kind = "annotated"
    else:
        materialize_input = norm_vcf
        materialize_input_kind = "normalized"
    emit_beat(
        progress_callback,
        phase="materialize",
        message=f"reading {materialize_input_kind} VCF ({materialize_input.name})",
        logger=log,
    )

    manifest = json.loads(manifest_path.read_text())
    sample_id = manifest["sample_id"]
    src_vcf_path = manifest["input"]["vcf_path"]
    src_vcf_sha = manifest["input"]["vcf_sha256"]
    materialize_input_sha = _sha256_file(materialize_input)

    store_path = run_dir / "variants.duckdb"

    # Per-row provenance attributes to the **source-of-truth VCF**, not
    # the intermediate normalized VCF. Two reasons:
    # 1. Determinism. ``bcftools norm`` embeds the wall-clock date + the
    #    output path into the VCF header, so ``normalized.vcf.gz``'s
    #    SHA256 isn't byte-stable across runs of identical inputs;
    #    stamping that SHA on every row would poison the determinism
    #    contract.
    # 2. Semantics. The canonical identity of a variant row is the
    #    genome file the user supplied. The intermediate normalize step
    #    is recorded in ``provenance.json`` (step trail) so the chain is
    #    fully recoverable, but per-row identity points at the artifact
    #    that won't move under us.
    tag = ProvenanceTag(
        source_path=src_vcf_path,
        source_sha256=src_vcf_sha,
        tool="genomeclaw-prep",
        tool_version=TOOLKIT_VERSION,
        params_json=json.dumps(
            {"step": "materialize", "sample_id": sample_id},
            sort_keys=True,
        ),
        schema_version=SCHEMA_VERSION,
        created_at=started_at,
    )

    # Replace the existing variants rows (from ingest) with the
    # post-normalize / post-annotate ones. We drop+recreate the table
    # rather than just truncating so a v0.1 store (no clinvar_*
    # columns) is transparently upgraded to v0.2 on the next
    # materialize call.
    _reset_variants_table(store_path)

    # When the annotated VCF is present, pull the vcfanno-produced
    # INFO fields into v0.2 columns; otherwise these columns stay NULL.
    # ClinVar fields come from the `vcfanno` clinvar block; the
    # ``gnomad_af_*`` + ``dbsnp_rsid`` fields come from the
    # gnomAD-exomes per-chrom block + the (cached, renamed) dbSNP block
    # respectively. ``CSQ`` is VEP's mega-string carrying the 10
    # Phase-4D transcript-level columns; the per-row CSQ value gets
    # parsed below via ``_csq``. Every INFO field listed here MUST have
    # a matching nullable column in store.py's ``_VARIANT_DOMAIN_COLUMNS``
    # (or be processed into one by the CSQ parser).
    info_fields: tuple[str, ...] = (
        (
            "clinvar_classification",
            "clinvar_review_status",
            "dbsnp_rsid",
            "gnomad_af_popmax",
            "gnomad_af_popmax_pop",
            "gnomad_af_afr",
            "gnomad_af_amr",
            "gnomad_af_asj",
            "gnomad_af_eas",
            "gnomad_af_fin",
            "gnomad_af_mid",
            "gnomad_af_nfe",
            "gnomad_af_remaining",
            "gnomad_af_sas",
            "CSQ",
        )
        if materialize_input_kind == "annotated"
        else ()
    )

    # Read the CSQ header line up-front (if any). VEP's INFO field
    # order is declared in ``##INFO=<ID=CSQ,...>`` and is stable for
    # the run, so we parse it once and reuse for every record. Falls
    # back to None when CSQ is absent (pre-VEP runs); the per-row CSQ
    # extraction below skips when csq_fields is None.
    csq_fields = _read_csq_header_if_present(materialize_input)

    def _row_stream() -> Iterator[dict[str, Any]]:
        for row in iter_variant_rows(materialize_input, info_fields=info_fields):
            # Convert CSQ → 10 typed columns when present; otherwise
            # leave the column keys absent (write_variants treats
            # missing nullable columns as None / NULL).
            csq_value = row.pop("CSQ", None) if "CSQ" in row else None
            vep_columns = _extract_vep_columns(csq_value, csq_fields)
            yield {**row, "sample_id": sample_id, **vep_columns}

    # CSV-staging + DuckDB temp_directory live on /mnt/genomeclaw/scratch
    # via the shard_scratch primitive (auto-cleanup on exit). The variants
    # table is rewritten in place by DuckDB's transaction; no atomic_promote
    # needed because there's no scratch→derived copy step.
    # Scratch base inferred as a sibling of derived/ — see annotate.py /
    # annotate_vcfanno.py for the same pattern.
    scratch_base = run_dir.parent.parent / "scratch"
    emit_beat(
        progress_callback,
        phase="materialize",
        message="rewriting variants table in DuckDB",
        logger=log,
    )
    with shard_scratch(step="materialize", run_id=run_dir.name, base=scratch_base) as scratch:
        write_variants(store_path, _row_stream(), tag=tag, work_dir=scratch)
    completed_at = datetime.now(tz=UTC)

    # Append step to provenance.json.
    provenance_path = run_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["steps"].append(
        {
            "step": "materialize",
            "tool": "genomeclaw-prep",
            "tool_version": TOOLKIT_VERSION,
            "started_at": started_at,
            "completed_at": completed_at,
            "inputs": [
                {"path": materialize_input.name, "sha256": materialize_input_sha},
            ],
            "outputs": [{"path": "variants.duckdb", "sha256": _sha256_file(store_path)}],
            "params": {
                "sample_id": sample_id,
                "input_kind": materialize_input_kind,
            },
        }
    )
    provenance_path.write_text(json.dumps(provenance, indent=2, default=_serialise_for_json) + "\n")

    log.info("materialize complete: store=%s", store_path)
    if progress_callback is not None:
        progress_callback(
            PhaseComplete(
                phase="materialize",
                duration_sec=time.monotonic() - phase_start_mono,
                run_dir=str(run_dir),
            )
        )
    return store_path


__all__ = ["materialize"]

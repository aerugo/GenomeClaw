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
from genomeclaw_toolkit.prep._gnomad_constraint import (
    join_gene_loeuf,
    resolve_constraint_tsv,
)
from genomeclaw_toolkit.prep._vcf import iter_variant_rows
from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base, shard_scratch
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
    try:
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
    except (OSError, gzip.BadGzipFile):
        # File isn't actually gzip (stub fixtures in unit tests, or a
        # truncated/corrupt VCF). The CSQ-extract path is a no-op
        # without a header anyway — log + return None so the rest of
        # materialize keeps working.
        log.warning("could not read VCF header from %s for CSQ inspection", vcf)
        return None
    return None


def _extract_vep_columns(
    csq_value: str | None, csq_fields: tuple[str, ...] | None
) -> dict[str, Any]:
    """Parse one CSQ value into the Phase-4D typed column dict.

    When ``csq_value`` or ``csq_fields`` is None, returns an empty dict
    (the materialize CSV writer interprets missing nullable columns as
    NULL). When both are present, picks the canonical consequence
    (MANE Select → MANE Plus Clinical → CANONICAL=YES → first) and
    extracts the columns.

    Retained for backwards compatibility. The production path now uses
    :func:`_extract_dual_vep_rows`, which yields 1 or 2 rows per variant
    (the dual-row case is the 73-gene MANE Plus Clinical set with
    differing consequence severity). See vep-mane-plus-clinical Phase 2.
    """
    if csq_value is None or csq_fields is None:
        return {}
    entries = split_csq(csq_value, csq_fields)
    canonical = pick_canonical_entry(entries)
    if canonical is None:
        return {}
    return csq_entry_to_columns(canonical)


# vep-mane-plus-clinical Phase 2: dual-row emit helpers.
# `_consequence_tier` maps VEP IMPACT to a coarse integer (HIGH=3 …
# MODIFIER=0). When MANE Select and MANE Plus Clinical entries disagree
# on tier for the same variant site, we emit BOTH rows so a downstream
# consumer can see the disagreement without losing information.

_IMPACT_TIER: dict[str | None, int] = {
    "HIGH": 3,
    "MODERATE": 2,
    "LOW": 1,
    "MODIFIER": 0,
    None: 0,
    "": 0,
}


def _consequence_tier(impact: str | None) -> int:
    """Map a VEP IMPACT string (HIGH/MODERATE/LOW/MODIFIER) to a tier int.

    Unknown / empty / None → 0 (lowest tier). This is intentional: a
    transcript with no IMPACT annotation cannot outrank one with a
    known tier.
    """
    return _IMPACT_TIER.get(impact, 0)


def _extract_dual_vep_rows(
    entries: tuple[Any, ...], csq_fields: tuple[str, ...] | None
) -> Iterator[dict[str, Any]]:
    """Yield 1 or 2 column dicts from CSQ entries for one variant site.

    Yields two rows when a MANE Select entry and a MANE Plus Clinical
    entry are both present AND differ in their consequence IMPACT tier;
    yields one row otherwise. The single-row path preserves the
    pre-existing canonical-pick behaviour
    (MANE_SELECT → MANE_PLUS_CLINICAL → CANONICAL → first).

    On the dual-row pair:

    - Row A is derived from the MANE Select entry, with
      ``transcript_discordant=False``.
    - Row B is derived from the MANE Plus Clinical entry, with
      ``transcript_discordant=True``.

    Both rows are written to the variants table with the same provenance
    columns by ``write_variants``. Consumers that want one row per
    variant can filter `WHERE transcript_discordant IS NULL OR
    transcript_discordant = false`; consumers that want to see the
    discordance see both rows.

    INV-E001: each emitted row carries the CSQ-derived transcript ID
    (``mane_select_transcript`` on Row A; ``mane_plus_clinical_transcript``
    on Row B) as its evidence anchor.

    INV-R001: ``transcript_discordant`` is NULL on every single-row
    emit; False/True on the two rows of a dual-row pair — preserving
    the per-row provenance contract.
    """
    if not entries:
        return

    select_entry = next(
        (e for e in entries if e.by_name.get("MANE_SELECT")), None
    )
    plus_entry = next(
        (e for e in entries if e.by_name.get("MANE_PLUS_CLINICAL")), None
    )

    # Single-row paths: 0 or 1 MANE entries, OR same-tier disagreement.
    if select_entry is None or plus_entry is None:
        canonical = pick_canonical_entry(entries)
        if canonical is None:
            return
        cols = csq_entry_to_columns(canonical)
        cols["transcript_discordant"] = None
        yield cols
        return

    select_tier = _consequence_tier(select_entry.by_name.get("IMPACT"))
    plus_tier = _consequence_tier(plus_entry.by_name.get("IMPACT"))
    if select_tier == plus_tier:
        # Both MANE entries agree on tier; preserve the Select row only
        # (the materialize pre-Phase-2 contract). MANE Plus Clinical
        # transcript field on the Select row is intentionally empty —
        # it belongs to a different CSQ entry.
        cols = csq_entry_to_columns(select_entry)
        cols["transcript_discordant"] = None
        yield cols
        return

    # Dual-row emit: tiers differ. Emit Row A (Select) + Row B (Plus Clinical),
    # each carrying its own gene_symbol / transcript / consequence /
    # IMPACT-derived fields; both share the variant's provenance via
    # ``write_variants``.
    row_a = csq_entry_to_columns(select_entry)
    row_a["transcript_discordant"] = False
    yield row_a

    row_b = csq_entry_to_columns(plus_entry)
    row_b["transcript_discordant"] = True
    yield row_b


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
    reference_dir: Path | None = None,
    gnomad_constraint_release: str | None = None,
    started_at: datetime | None = None,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path:
    """Rewrite the ``variants`` table from the run's normalized VCF.

    Args:
        run_dir: an existing ``derived/<run-id>/`` from a prior
            ``ingest`` + ``normalize``. Must contain ``normalized.vcf.gz``,
            ``manifest.json``, ``provenance.json``, and ``variants.duckdb``.
        reference_dir: optional toolkit reference root. When provided
            and a gnomAD constraint TSV is staged under
            ``<ref>/gnomad-constraint/<release>/``, a post-write join
            populates the ``gene_loeuf`` column from the constraint
            metrics (MANE Select transcript's LOEUF per gene). When
            ``None`` or no constraint source is staged, ``gene_loeuf``
            stays NULL on every row — same graceful-degradation shape
            as ``annotate_vep``'s "no cache → skip" fallback.
        gnomad_constraint_release: optional release tag (e.g. ``"v4.1"``).
            When ``None`` and ``reference_dir`` is provided, picks the
            lex-largest dir under ``<ref>/gnomad-constraint/``.
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
    # extraction below skips when csq_fields is None. Only inspected
    # for the annotated-input branch — the normalized VCF doesn't
    # carry CSQ and a stubbed / non-gzip normalized.vcf.gz in unit
    # tests would crash the gzip reader otherwise.
    csq_fields = (
        _read_csq_header_if_present(materialize_input)
        if materialize_input_kind == "annotated"
        else None
    )

    def _row_stream() -> Iterator[dict[str, Any]]:
        for row in iter_variant_rows(materialize_input, info_fields=info_fields):
            # vep-mane-plus-clinical Phase 2: convert CSQ → 1 or 2 rows
            # via `_extract_dual_vep_rows`. The dual-row case fires when
            # both a MANE Select and a MANE Plus Clinical entry are
            # present for the same variant AND their consequence IMPACT
            # tiers differ — preserves both annotations rather than
            # silently dropping one. Single-row emits (the common path)
            # carry `transcript_discordant=None`.
            csq_value = row.pop("CSQ", None) if "CSQ" in row else None
            base_row = {**row, "sample_id": sample_id}
            if csq_value is None or csq_fields is None:
                yield {**base_row, "transcript_discordant": None}
                continue
            entries = split_csq(csq_value, csq_fields)
            emitted = False
            for vep_cols in _extract_dual_vep_rows(entries, csq_fields):
                emitted = True
                yield {**base_row, **vep_cols}
            if not emitted:
                # Empty CSQ string parses to zero entries; preserve the
                # variant row so the variants table still has the call,
                # just without VEP-derived columns.
                yield {**base_row, "transcript_discordant": None}

    # CSV-staging + DuckDB temp_directory live on the **ephemeral** scratch
    # base (container-local; off virtiofs) per Phase A of the
    # [annotate-shard-resilience plan](../../../../docs/plans/active/annotate-shard-resilience/development-plan.md).
    # The variants table is rewritten in place by DuckDB's transaction;
    # no atomic_promote needed because there's no scratch→derived copy.
    emit_beat(
        progress_callback,
        phase="materialize",
        message="rewriting variants table in DuckDB",
        logger=log,
    )
    with shard_scratch(
        step="materialize", run_id=run_dir.name, base=ephemeral_scratch_base()
    ) as scratch:
        write_variants(store_path, _row_stream(), tag=tag, work_dir=scratch)

    # gnomAD-constraint → gene_loeuf join. Runs after write_variants
    # because the join targets the freshly-rewritten variants table's
    # ``gene_symbol`` column (populated above from CSQ when the
    # annotated VCF carries one).
    #
    # The join is opt-in via ``reference_dir``: when not provided, the
    # column stays NULL and no constraint input lands in provenance.
    # When ``reference_dir`` is provided but no constraint source is
    # staged on disk, we silently skip — same graceful-degradation shape
    # as ``annotate_vep``'s "no cache → skip" fallback, so a partial
    # reference layout (fetched VEP cache but not constraint, for
    # example) still produces a working variants table.
    constraint_input: dict[str, Any] | None = None
    constraint_release_recorded: str | None = None
    if reference_dir is not None:
        resolved = resolve_constraint_tsv(reference_dir, gnomad_constraint_release)
        if resolved is not None:
            constraint_tsv, constraint_release_recorded = resolved
            emit_beat(
                progress_callback,
                phase="materialize",
                message=(
                    f"joining gene_loeuf from gnomAD constraint {constraint_release_recorded}"
                ),
                logger=log,
            )
            updated = join_gene_loeuf(store_path, constraint_tsv)
            log.info("gene_loeuf populated for %d variant rows", updated)
            constraint_input = {
                "path": str(constraint_tsv),
                "sha256": _sha256_file(constraint_tsv),
            }

    completed_at = datetime.now(tz=UTC)

    # Append step to provenance.json. Inputs always include the
    # materialize input; the constraint TSV joins it when it was used.
    inputs: list[dict[str, Any]] = [
        {"path": materialize_input.name, "sha256": materialize_input_sha},
    ]
    if constraint_input is not None:
        inputs.append(constraint_input)
    params: dict[str, Any] = {
        "sample_id": sample_id,
        "input_kind": materialize_input_kind,
    }
    if constraint_release_recorded is not None:
        params["gnomad_constraint_release"] = constraint_release_recorded

    provenance_path = run_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["steps"].append(
        {
            "step": "materialize",
            "tool": "genomeclaw-prep",
            "tool_version": TOOLKIT_VERSION,
            "started_at": started_at,
            "completed_at": completed_at,
            "inputs": inputs,
            "outputs": [{"path": "variants.duckdb", "sha256": _sha256_file(store_path)}],
            "params": params,
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

"""Active-run resolver + manifest reader for the host service.

Wraps :func:`genomeclaw_toolkit.prep.run_id.resolve_current_run_dir` so
the FastAPI app's request handlers don't reach into the prep package
directly. The resolver runs at startup + on ``SIGHUP``; per-request
handlers consume a cached :class:`ActiveRun` snapshot.

`INV-P002`: this layer never returns full manifest dicts to the route
handlers — it returns a typed, narrow :class:`ActiveRun` shape. The
"minimal-sufficient" discipline starts here, not at the route.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import duckdb

from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ActiveRun:
    """The active run's identity + the bare facts the service exposes.

    Constructed once at startup (and on ``SIGHUP``) by reading the
    ``CURRENT`` symlink + the active run's ``manifest.json``. The route
    handlers consume this rather than re-reading the manifest per request.
    """

    run_id: str
    schema_version: str
    sample_id: str
    run_dir: Path


class ActiveRunError(RuntimeError):
    """Resolution of the active run failed in a user-actionable way.

    Two subclasses cover the documented degraded states. Callers (the
    `/v1/health` route handler) translate these into 503 responses with
    a typed :class:`HealthErrorResponse` body.
    """


class NoActiveRunError(ActiveRunError):
    """No ``CURRENT`` symlink under the derived root, or it doesn't resolve."""


class SchemaVersionMismatchError(ActiveRunError):
    """The active run's manifest declares a schema version this build can't serve."""

    def __init__(self, *, found: str, expected: str) -> None:
        """Build a user-facing message naming the found vs. expected version."""
        super().__init__(
            f"active run uses schema_version={found!r}; "
            f"this toolkit build serves schema_version={expected!r}. "
            "Rebuild with `genomeclaw pipeline run` against the current toolkit."
        )
        self.found = found
        self.expected = expected


def load_active_run(*, derived_root: Path, expected_schema_version: str) -> ActiveRun:
    """Resolve ``derived_root/CURRENT`` and read enough of the manifest to serve.

    Raises:
        NoActiveRunError: when the ``CURRENT`` symlink is missing,
            broken, or points at something other than a directory under
            ``derived_root``.
        SchemaVersionMismatchError: when the active run's manifest
            declares a schema version that doesn't match
            ``expected_schema_version``.
    """
    try:
        run_dir = resolve_current_run_dir(derived_root)
    except ValueError as exc:
        raise NoActiveRunError(str(exc)) from exc

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise NoActiveRunError(
            f"active run {run_dir.name} has no manifest.json; "
            "rerun `genomeclaw pipeline run` to recreate it"
        )

    manifest = json.loads(manifest_path.read_text())
    schema_version = str(manifest.get("schema_version", ""))
    if schema_version != expected_schema_version:
        raise SchemaVersionMismatchError(found=schema_version, expected=expected_schema_version)

    return ActiveRun(
        run_id=str(manifest.get("run_id", run_dir.name)),
        schema_version=schema_version,
        sample_id=str(manifest.get("sample_id", "")),
        run_dir=run_dir,
    )


class InvalidVariantKeyError(ValueError):
    """A user-supplied ``/v1/variants/{key}`` doesn't parse as ``chrom-pos-ref-alt``."""


def parse_variant_key(key: str) -> tuple[str, int, str, str]:
    """Parse ``chrom-pos-ref-alt`` into typed components.

    ``chrom`` may contain underscores (decoy / alt contigs do); ``pos``
    must parse as a positive integer; ``ref`` + ``alt`` are non-empty
    base strings. GRCh38 contig names do not contain ``-`` so splitting
    by ``-`` is unambiguous.

    Raises:
        InvalidVariantKeyError: when the key doesn't decompose into
            exactly four parts, or ``pos`` isn't a positive integer, or
            any of the parts is empty.
    """
    parts = key.split("-")
    if len(parts) != 4:
        raise InvalidVariantKeyError(
            f"variant key {key!r} must be of the form chrom-pos-ref-alt; "
            f"got {len(parts)} dash-separated parts"
        )
    chrom, pos_raw, ref, alt = parts
    if not chrom or not ref or not alt:
        raise InvalidVariantKeyError(f"variant key {key!r} has an empty chrom / ref / alt")
    try:
        pos = int(pos_raw)
    except ValueError as exc:
        raise InvalidVariantKeyError(
            f"variant key {key!r} position {pos_raw!r} is not an integer"
        ) from exc
    if pos <= 0:
        raise InvalidVariantKeyError(f"variant key {key!r} position must be positive, got {pos}")
    return chrom, pos, ref, alt


# Columns selected for the list (summary) view. Kept in sync with
# :class:`genomeclaw_toolkit.schemas.variant.VariantSummary`. Per
# ``INV-P002`` the 9 per-population AFs + provenance columns are
# deliberately absent.
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "chrom",
    "pos",
    "id",
    "ref",
    "alt",
    "gene_symbol",
    "consequence",
    "clinvar_classification",
    "gnomad_af_popmax",
    "gnomad_af_popmax_pop",
    "alphamissense_score",
)

# Extra columns the detail view adds on top of the summary set. The
# DB column ``id`` carries the variant's rsid in the VCF sense.
_DETAIL_EXTRA_COLUMNS: tuple[str, ...] = (
    "sample_id",
    "genotype",
    "qual",
    "filter",
    "clinvar_id",
    "clinvar_review_status",
    "dbsnp_rsid",
    "mane_select_transcript",
    "mane_plus_clinical_transcript",
    "transcript_discordant",
    "hgvsc",
    "hgvsp",
    "loftee_lof",
    "loftee_filter",
    "alphamissense_class",
    "gene_loeuf",
)


def _connect_readonly(store_path: Path) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection over ``store_path``.

    Read-only prevents accidental schema mutation from a query path
    (defense-in-depth on top of ``INV-D001``). DuckDB handles multiple
    concurrent readers without locking — per-request connections are
    cheap.
    """
    return duckdb.connect(str(store_path), read_only=True)


def _row_to_summary_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Translate a row tuple selected via ``_SUMMARY_COLUMNS`` into a dict.

    Maps the DB column ``id`` to the schema field ``rsid`` (the latter is
    the user-facing name; ``id`` collides with HTTP semantics).
    """
    raw = dict(zip(_SUMMARY_COLUMNS, row, strict=True))
    raw["rsid"] = raw.pop("id")
    return raw


def query_variants(*, run_dir: Path, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Return one page of variants + the total row count.

    Stable ordering is ``(chrom, pos, ref, alt)`` so paging is
    deterministic across requests (DuckDB doesn't guarantee insertion
    order across reads).
    """
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        cols_sql = ", ".join(_SUMMARY_COLUMNS)
        rows = conn.execute(
            f"SELECT {cols_sql} FROM variants "  # noqa: S608 — cols are constants
            "ORDER BY chrom, pos, ref, alt LIMIT ? OFFSET ?",
            [limit, offset],
        ).fetchall()
        (total,) = conn.execute("SELECT COUNT(*) FROM variants").fetchone()
    finally:
        conn.close()
    return [_row_to_summary_dict(r) for r in rows], int(total)


def query_variant_by_key(*, run_dir: Path, key: str) -> dict[str, Any] | None:
    """Look up the single variant identified by ``key``.

    Returns ``None`` when no row matches. Raises
    :class:`InvalidVariantKeyError` when ``key`` doesn't parse.

    When multiple rows share the same ``(chrom, pos, ref, alt)`` — the
    Plan-4 dual-row case where MANE Select and MANE Plus Clinical
    disagreed on IMPACT tier — the discordant sibling wins via
    ``ORDER BY transcript_discordant DESC NULLS LAST``. The discordant
    row is the rarer + more clinically interesting view; the canonical
    row's MANE Select transcript is still reachable on the discordant
    row's ``mane_select_transcript`` field. Without this ordering the
    LIMIT 1 returned whichever row DuckDB scanned first (empirically the
    canonical row), hiding the discordance flag the agent system prompt
    asks the agent to consult.
    """
    chrom, pos, ref, alt = parse_variant_key(key)
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        cols = _SUMMARY_COLUMNS + _DETAIL_EXTRA_COLUMNS
        cols_sql = ", ".join(cols)
        row = conn.execute(
            f"SELECT {cols_sql} FROM variants "  # noqa: S608 — cols are constants
            "WHERE chrom = ? AND pos = ? AND ref = ? AND alt = ? "
            "ORDER BY transcript_discordant DESC NULLS LAST LIMIT 1",
            [chrom, pos, ref, alt],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    raw = dict(zip(cols, row, strict=True))
    raw["rsid"] = raw.pop("id")
    return raw


@dataclass(frozen=True)
class GeneAggregate:
    """One gene's variants + coverage summary, as the route consumes it."""

    canonical_symbol: str
    n_variants_in_gene: int
    mean_depth: float | None
    low_coverage_exons: list[str]
    region_class: str | None = None
    """Per coverage-panel-v2: the gene's coverage-reliability class,
    sourced from `coverage_qc.region_class`. None when no `coverage_qc`
    row exists for this gene OR when the row's class is NULL (pre-v2
    rows). The agent surface (Phase 3) maps non-NULL non-`"standard"`
    values to a human-readable caveat string."""


def query_gene(*, run_dir: Path, symbol: str) -> GeneAggregate | None:
    """Aggregate a gene's variant count + coverage_qc row.

    Resolves case-insensitively against the canonical (DB-stored) gene
    symbol. Returns ``None`` when neither table has any row for the
    gene; returns a :class:`GeneAggregate` with ``mean_depth=None`` +
    ``low_coverage_exons=[]`` when variants exist but there's no
    ``coverage_qc`` row (per spec AC8 the curated coverage subset is
    smaller than the universe of genes annotated by VEP).
    """
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        # Canonical symbol: take the first variants.gene_symbol whose
        # case-folded value matches the query. If no variants row exists,
        # fall back to coverage_qc.gene. The DB is treated as the source
        # of truth for casing.
        canonical_row = conn.execute(
            "SELECT gene_symbol FROM variants "
            "WHERE LOWER(gene_symbol) = LOWER(?) "
            "ORDER BY gene_symbol LIMIT 1",
            [symbol],
        ).fetchone()
        if canonical_row is None:
            canonical_row = conn.execute(
                "SELECT gene FROM coverage_qc WHERE LOWER(gene) = LOWER(?) ORDER BY gene LIMIT 1",
                [symbol],
            ).fetchone()
        if canonical_row is None:
            return None
        canonical_symbol = str(canonical_row[0])

        (n_variants,) = conn.execute(
            "SELECT COUNT(*) FROM variants WHERE gene_symbol = ?",
            [canonical_symbol],
        ).fetchone()

        cov_row = conn.execute(
            "SELECT mean_depth, low_coverage_exons, region_class "
            "FROM coverage_qc WHERE gene = ?",
            [canonical_symbol],
        ).fetchone()
    finally:
        conn.close()

    if cov_row is None:
        mean_depth: float | None = None
        low_coverage_exons: list[str] = []
        region_class: str | None = None
    else:
        mean_depth = float(cov_row[0]) if cov_row[0] is not None else None
        low_coverage_exons = list(cov_row[1]) if cov_row[1] is not None else []
        region_class = str(cov_row[2]) if cov_row[2] is not None else None

    return GeneAggregate(
        canonical_symbol=canonical_symbol,
        n_variants_in_gene=int(n_variants),
        mean_depth=mean_depth,
        low_coverage_exons=low_coverage_exons,
        region_class=region_class,
    )


def load_provenance(*, run_dir: Path) -> dict[str, Any]:
    """Read + parse ``run_dir/provenance.json``.

    Returns the raw JSON dict; the route handler validates it through
    :class:`genomeclaw_toolkit.schemas.provenance.Provenance` before
    serving so a malformed on-disk trail surfaces as a typed error.
    """
    provenance_path = run_dir / "provenance.json"
    return json.loads(provenance_path.read_text())


# Phase 6 Slice A — findings query columns.
_FINDING_COLUMNS: tuple[str, ...] = (
    "id",
    "category",
    "title",
    "summary",
    "evidence_ref",
    "evidence_quality",
    "gene_symbols",
    "drugs",
    "clinical_escalation",
)


def _row_to_finding_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Translate a row tuple selected via ``_FINDING_COLUMNS`` into a dict.

    DuckDB returns ``TEXT[]`` columns as ``list[str]``; ``None`` for
    nullable columns. The Pydantic model normalises ``gene_symbols``
    to ``[]`` when null.
    """
    raw = dict(zip(_FINDING_COLUMNS, row, strict=True))
    if raw["gene_symbols"] is None:
        raw["gene_symbols"] = []
    return raw


def query_findings(
    *,
    run_dir: Path,
    category: str | None,
    genes: tuple[str, ...] | None,
    drugs: tuple[str, ...] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return one filtered page of findings + the total filtered count.

    Filters compose AND-wise: a row passes only if every supplied filter
    matches. The `genes` / `drugs` arrays use DuckDB's `list_has_any`
    operator so a row matches when ANY of its values is in the query
    set (`genes = ['BRCA2', 'LCT']` returns findings citing BRCA2 OR LCT).
    """
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if genes:
            clauses.append("list_has_any(gene_symbols, ?)")
            params.append(list(genes))
        if drugs:
            clauses.append("list_has_any(drugs, ?)")
            params.append(list(drugs))
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        cols_sql = ", ".join(_FINDING_COLUMNS)
        rows = conn.execute(
            f"SELECT {cols_sql} FROM findings{where_sql} "  # noqa: S608 — cols + where built from constants/params
            "ORDER BY id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        (total,) = conn.execute(
            f"SELECT COUNT(*) FROM findings{where_sql}",  # noqa: S608
            params,
        ).fetchone()
    finally:
        conn.close()
    return [_row_to_finding_dict(r) for r in rows], int(total)


class InvalidEvidenceRefError(ValueError):
    """A user-supplied evidence ref doesn't parse as ``<kind>:<id>``."""


class UnknownEvidenceKindError(ValueError):
    """The ref's kind isn't one this build supports."""


# Kinds the resolver supports today. Variant-keyed only, per the v1.6
# INVARIANTS revision (gene_note + topic retired; lifestyle calibration
# moved to the agent's research-and-synthesis pattern). Kept in sync with
# :data:`genomeclaw_toolkit.schemas.evidence.EvidenceKind`.
_SUPPORTED_EVIDENCE_KINDS: frozenset[str] = frozenset(
    {"clinvar", "pgs_catalog", "pharmgkb", "cyrius_no_call"}
)


def parse_evidence_ref(ref: str) -> tuple[str, str]:
    """Split ``<kind>:<id>`` on the first colon.

    The id may contain colons + dashes + dots (e.g. PharmGKB ids like
    ``PA166104891`` or PubMed ids); splitting on the first colon gives
    `(kind, rest)` reliably. The kind itself is constrained to lowercase
    + underscores by the supported-kinds set.

    Raises:
        InvalidEvidenceRefError: when the ref doesn't contain ``:``,
            or either side of the colon is empty.
    """
    if ":" not in ref:
        raise InvalidEvidenceRefError(
            f"evidence ref {ref!r} must be of the form kind:id (e.g. clinvar:RCV000031)"
        )
    kind, ident = ref.split(":", 1)
    if not kind or not ident:
        raise InvalidEvidenceRefError(f"evidence ref {ref!r} has an empty kind or id")
    return kind, ident


def _resolve_clinvar(run_dir: Path, clinvar_id: str) -> dict[str, Any] | None:
    """Look up `clinvar_id` in the variants table and synthesise a summary.

    Returns ``None`` when no matching row exists. The body is a typed
    summary (classification + review status + gene + canonical id);
    INV-P002 prohibits returning the full variant row here.
    """
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        row = conn.execute(
            "SELECT clinvar_id, clinvar_classification, clinvar_review_status, "
            "gene_symbol, consequence FROM variants WHERE clinvar_id = ? LIMIT 1",
            [clinvar_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    rcv, classification, review_status, gene_symbol, consequence = row
    body_lines = [
        f"ClinVar {rcv}: classification = {classification}.",
        f"Review status: {review_status}.",
    ]
    if gene_symbol:
        body_lines.append(f"Gene: {gene_symbol}.")
    if consequence:
        body_lines.append(f"Consequence: {consequence}.")
    return {
        "kind": "clinvar",
        "id": rcv,
        "body": " ".join(body_lines),
        "source": "variants.duckdb#clinvar_id",
    }


def resolve_evidence(*, run_dir: Path, ref: str) -> dict[str, Any] | None:
    """Resolve `ref` into an EvidenceRecord-compatible dict.

    The host service resolver supports **variant-keyed kinds only** as
    of the v1.6 INVARIANTS revision (gene_note + topic retired; see
    INVARIANTS.md § INV-C001 v1.6 and the agent-research-and-synthesis
    plan dir under `docs/plans/active/`).

    Returns ``None`` when the kind is supported but no matching record
    exists (route handler turns this into a 404). Raises
    :class:`InvalidEvidenceRefError` for malformed refs and
    :class:`UnknownEvidenceKindError` for refs whose kind isn't in
    :data:`_SUPPORTED_EVIDENCE_KINDS` (route handler turns both into
    400 responses).
    """
    kind, ident = parse_evidence_ref(ref)
    if kind not in _SUPPORTED_EVIDENCE_KINDS:
        raise UnknownEvidenceKindError(
            f"evidence kind {kind!r} not supported in this build; "
            f"known kinds: {sorted(_SUPPORTED_EVIDENCE_KINDS)}"
        )
    if kind == "clinvar":
        return _resolve_clinvar(run_dir, ident)
    if kind == "cyrius_no_call":
        return _resolve_cyrius_no_call(ident)
    # pgs_catalog + pharmgkb resolvers land in Phase 6 Slices D + E. Until
    # then they return None (= 404) — the agent learns the kind exists but
    # no record is available in this build.
    return None


def _resolve_cyrius_no_call(sentinel_path: str) -> dict[str, Any] | None:
    """Resolve a `cyrius_no_call:<absolute_path>` ref by reading the sentinel.

    Per cyp2d6-no-call-finding Phase 2 + INV-A004 (decline taxonomy must
    traverse every layer): the indeterminate CYP2D6 finding's `evidence_ref`
    points at the `cyp2d6_no_call_envelope.json` sentinel that the Cyrius
    wrapper wrote on the no-call path. This resolver reads the sentinel
    and returns a summary-class body the agent can render verbatim.

    Per INV-P002 (minimal-sufficient outputs): the response body names the
    indeterminate state + the binding "do not interpret as Normal
    Metabolizer" rule + the audit details (sample_id, filter_status, tool
    version) — but does NOT echo the raw Cyrius output back. The raw block
    lives on disk for audit.

    Returns ``None`` when the sentinel file doesn't exist (route handler
    turns this into a 404).
    """
    import json
    from pathlib import Path as _Path

    sentinel = _Path(sentinel_path)
    if not sentinel.exists():
        return None

    body_data = json.loads(sentinel.read_text())
    sample_id = body_data.get("sample_id", "unknown")
    filter_status = body_data.get("filter_status", "NO_CALL")
    provenance = body_data.get("provenance", {})
    tool_version = provenance.get("tool_version", "unknown")

    body = (
        f"CYP2D6 indeterminate (no-call) for sample {sample_id}. "
        f"Cyrius v{tool_version} could not resolve a diplotype at the "
        f"CYP2D6/CYP2D7 locus (filter_status={filter_status}). "
        "Do not interpret as Normal Metabolizer — the metaboliser phenotype "
        "is unknown. Recommend the user confirm CYP2D6 status with their "
        "provider before any codeine, tramadol, oxycodone, tamoxifen, "
        "fluoxetine, or other CYP2D6-substrate medication decisions."
    )
    return {
        "kind": "cyrius_no_call",
        "id": sentinel_path,
        "body": body,
        "source": str(sentinel),
    }


def query_finding_by_id(*, run_dir: Path, finding_id: str) -> dict[str, Any] | None:
    """Single-finding lookup by `id`. Returns ``None`` when no match."""
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        cols_sql = ", ".join(_FINDING_COLUMNS)
        row = conn.execute(
            f"SELECT {cols_sql} FROM findings WHERE id = ? LIMIT 1",  # noqa: S608
            [finding_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_finding_dict(row)


# Phase 6 Slice E v2 — pgs_scores query helpers.
_PGS_SCORES_LIST_COLUMNS: tuple[str, ...] = (
    "pgs_id",
    "trait_label",
    "percentile_in_user_ancestry",
    "calibration_warning",
    "calibration_status",
    "decline_reason",
    "superseded_by",
)

_PGS_SCORES_GET_COLUMNS: tuple[str, ...] = (
    "pgs_id",
    "trait_label",
    "percentile_in_user_ancestry",
    "raw_score",
    "study_population",
    "calibration_warning",
    "calibration_status",
    "decline_reason",
    "agent_choice_rationale",
    "requested_for_question",
    "superseded_by",
)


def query_pgs_computed_list(*, run_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """Return all `pgs_scores` rows (slim per-row shape for list view).

    Per Q8 v1.6: PGS is a small per-user set (typically < 100 rows even for an
    extremely curious user); no pagination needed. Sorted by `pgs_id` for
    deterministic output.
    """
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        cols_sql = ", ".join(_PGS_SCORES_LIST_COLUMNS)
        rows = conn.execute(
            f"SELECT {cols_sql} FROM pgs_scores ORDER BY pgs_id"  # noqa: S608
        ).fetchall()
    finally:
        conn.close()
    dicts = [dict(zip(_PGS_SCORES_LIST_COLUMNS, row, strict=True)) for row in rows]
    return dicts, len(dicts)


def query_pgs_computed(*, run_dir: Path, pgs_id: str) -> dict[str, Any] | None:
    """Single-PGS lookup by `pgs_id`. Returns full row (including INV-A003 fields)."""
    store_path = run_dir / "variants.duckdb"
    conn = _connect_readonly(store_path)
    try:
        cols_sql = ", ".join(_PGS_SCORES_GET_COLUMNS)
        row = conn.execute(
            f"SELECT {cols_sql} FROM pgs_scores WHERE pgs_id = ? LIMIT 1",  # noqa: S608
            [pgs_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    raw = dict(zip(_PGS_SCORES_GET_COLUMNS, row, strict=True))
    # `source_pgs_id` echoes `pgs_id` per Q8 v1.6 (response-shape consistency
    # with the retired v1.5 `/v1/pgs/{trait}` shape).
    raw["source_pgs_id"] = raw["pgs_id"]
    return raw


__all__ = [
    "ActiveRun",
    "ActiveRunError",
    "GeneAggregate",
    "InvalidEvidenceRefError",
    "InvalidVariantKeyError",
    "NoActiveRunError",
    "SchemaVersionMismatchError",
    "UnknownEvidenceKindError",
    "load_active_run",
    "load_provenance",
    "parse_evidence_ref",
    "parse_variant_key",
    "query_finding_by_id",
    "query_findings",
    "query_gene",
    "query_pgs_computed",
    "query_pgs_computed_list",
    "query_variant_by_key",
    "query_variants",
    "resolve_evidence",
]

"""Phase 4E — ``materialize`` ``gene_loeuf`` join against gnomAD constraint v4.1.

The ``gene_loeuf`` column is reserved in [_csq.py:171-173](../../src/genomeclaw_toolkit/prep/_csq.py)
for this integration:

    # ``gene_loeuf`` is reserved for the gnomAD-constraint integration;
    # always NULL until that lands.
    columns["gene_loeuf"] = None

This file pins the join's contract: after ``materialize(run_dir,
reference_dir=...)``, rows whose VEP-extracted ``gene_symbol`` matches a
gene in ``reference/gnomad-constraint/<release>/gnomad.v4.1.constraint_metrics.tsv``
carry the matching ``lof.oe_ci.upper`` value as ``gene_loeuf``; rows
without a match carry NULL.

The join key is **gene symbol on the MANE Select transcript row** (the
constraint TSV has one row per transcript per gene; the MANE Select row
is the canonical LOEUF value). Same convention gnomAD's browser uses.

These tests are ``needs_bio`` because they (a) reuse the shared
``tiny_vcf_gz`` fixture which requires bcftools to bgzip+index, and (b)
hand-roll an annotated VCF that needs bgzip+tabix for ``iter_variant_rows``
to read it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import pytest

# Minimum gnomAD constraint TSV schema for the join. The real file
# (~1.2 MB) has 50+ columns; for the tests we only need the columns the
# join consults: ``gene``, ``mane_select``, ``lof.oe_ci.upper``. Other
# columns are present as placeholders so the header line shape doesn't
# diverge from production.
_CONSTRAINT_HEADER = "\t".join(
    [
        "gene",
        "gene_id",
        "transcript",
        "canonical",
        "mane_select",
        "lof.oe_ci.upper",
    ]
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bgz_index(plain: Path) -> Path:
    """bgzip + tabix-index a plain VCF; return the .vcf.gz path."""
    bgz = plain.with_suffix(plain.suffix + ".gz")
    subprocess.run(
        ["bcftools", "view", "-Oz", "-o", str(bgz), str(plain)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["bcftools", "index", "--tbi", str(bgz)],
        check=True,
        capture_output=True,
    )
    plain.unlink()
    return bgz


def _stage_annotated_vcf_with_csq(run_dir: Path, *, gene_symbol: str) -> None:
    """Write a hand-rolled ``annotated.vcf.gz`` whose canonical CSQ entry
    declares ``SYMBOL=<gene_symbol>``.

    The CSQ ``Format:`` field-name list pins the positional layout
    parsed by :mod:`_csq`. The single record's pipe-separated CSQ value
    carries the gene symbol in the SYMBOL position; the rest is sparse
    (other Phase-4D columns will be NULL — only ``gene_symbol`` matters
    for the gene_loeuf join).

    We overwrite any existing annotated.vcf.gz (e.g. one left by the
    parent-chain annotate orchestrator) so the test exercises a known
    materialize input.
    """
    plain = run_dir / "annotated.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations '
        'from Ensembl VEP. Format: Allele|Consequence|SYMBOL|MANE_SELECT|CANONICAL">\n'
        "##contig=<ID=chr17,length=83257441>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\ttest-001\n"
        "chr17\t43044295\t.\tG\tA\t100\tPASS\t"
        f"CSQ=A|missense_variant|{gene_symbol}|NM_007294.4|YES"
        "\tGT\t0/1\n"
    )
    # Remove any prior annotated.vcf.gz from the parent annotate chain
    # so _bgz_index can write the new one without conflict.
    existing = run_dir / "annotated.vcf.gz"
    if existing.exists():
        existing.unlink()
    existing_tbi = run_dir / "annotated.vcf.gz.tbi"
    if existing_tbi.exists():
        existing_tbi.unlink()
    _bgz_index(plain)


def _stage_constraint_release(
    reference_dir: Path,
    release: str = "v4.1",
    *,
    rows: list[tuple[str, str, str]],
) -> Path:
    """Write a synthetic ``gnomad.v4.1.constraint_metrics.tsv`` with the rows
    the test asserts against.

    Args:
        reference_dir: test reference root.
        release: per-source release tag.
        rows: per-row tuple of ``(gene, mane_select, lof_oe_ci_upper)``.
            ``mane_select`` is ``"true"`` or ``"false"`` (the TSV value
            shape — the join filters on ``mane_select = true``).
            ``lof_oe_ci_upper`` is the stringified LOEUF value (e.g.
            ``"0.123"``).

    Returns:
        Path to the written TSV.
    """
    target = reference_dir / "gnomad-constraint" / release
    target.mkdir(parents=True)
    tsv = target / "gnomad.v4.1.constraint_metrics.tsv"
    lines = [_CONSTRAINT_HEADER]
    for gene, mane_select, loeuf in rows:
        lines.append(
            "\t".join(
                [
                    gene,
                    f"{gene}-id",
                    f"{gene}-transcript",
                    "true",
                    mane_select,
                    loeuf,
                ]
            )
        )
    tsv.write_text("\n".join(lines) + "\n")
    return tsv


def _run_through_materialize(
    *,
    tiny_vcf_gz: Path,
    genomeclaw_layout: dict[str, Path],
    gene_symbol: str,
    constraint_rows: list[tuple[str, str, str]] | None,
) -> Path:
    """Drive a run from ingest → normalize → hand-rolled annotated.vcf.gz →
    materialize(with reference_dir).

    ``constraint_rows`` is ``None`` to skip staging any constraint source
    (tests the "constraint absent" path).

    Returns the run dir for downstream DuckDB / provenance queries.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    if constraint_rows is not None:
        _stage_constraint_release(genomeclaw_layout["reference"], rows=constraint_rows)

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="loeuf-001",
    )
    normalize(run_dir=run_dir)
    _stage_annotated_vcf_with_csq(run_dir, gene_symbol=gene_symbol)
    materialize(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])
    return run_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_materialize_populates_gene_loeuf_from_gnomad_constraint(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Happy path: a variant whose CSQ carries ``SYMBOL=BRCA1`` is joined
    against a constraint TSV row for BRCA1, and ``gene_loeuf`` takes the
    matching ``lof.oe_ci.upper`` value.
    """
    run_dir = _run_through_materialize(
        tiny_vcf_gz=tiny_vcf_gz,
        genomeclaw_layout=genomeclaw_layout,
        gene_symbol="BRCA1",
        constraint_rows=[("BRCA1", "true", "0.123")],
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row = conn.execute(
            "SELECT gene_symbol, gene_loeuf FROM variants WHERE chrom = 'chr17' AND pos = 43044295"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "expected chr17:43044295 row to exist after materialize"
    gene_symbol, gene_loeuf = row
    assert gene_symbol == "BRCA1"
    assert gene_loeuf == pytest.approx(0.123)


@pytest.mark.needs_bio
def test_materialize_gene_loeuf_null_when_gene_symbol_absent_from_constraint(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """A variant whose ``gene_symbol`` doesn't appear in the constraint TSV
    gets ``gene_loeuf = NULL``. No crash, no fallback value.
    """
    run_dir = _run_through_materialize(
        tiny_vcf_gz=tiny_vcf_gz,
        genomeclaw_layout=genomeclaw_layout,
        gene_symbol="NONEXISTENT_GENE",
        constraint_rows=[("BRCA1", "true", "0.123")],
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row = conn.execute(
            "SELECT gene_symbol, gene_loeuf FROM variants WHERE chrom = 'chr17' AND pos = 43044295"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    gene_symbol, gene_loeuf = row
    assert gene_symbol == "NONEXISTENT_GENE"
    assert gene_loeuf is None


@pytest.mark.needs_bio
def test_materialize_gene_loeuf_null_when_constraint_source_missing(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """When no ``gnomad-constraint/`` source is staged, materialize succeeds
    with ``gene_loeuf = NULL`` on every row. Same graceful-degradation
    shape as ``annotate_vep``'s "no cache → skip" fallback.
    """
    run_dir = _run_through_materialize(
        tiny_vcf_gz=tiny_vcf_gz,
        genomeclaw_layout=genomeclaw_layout,
        gene_symbol="BRCA1",
        constraint_rows=None,
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT gene_symbol, gene_loeuf FROM variants").fetchall()
    finally:
        conn.close()
    assert rows, "expected at least one variant row"
    for _gene_symbol, gene_loeuf in rows:
        assert gene_loeuf is None


@pytest.mark.needs_bio
def test_materialize_gene_loeuf_picks_mane_select_row_when_gene_has_multiple_transcripts(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """When a gene has multiple constraint rows (one per transcript), the
    join picks the row flagged ``mane_select = true`` — that's the
    canonical LOEUF gnomAD's own browser surfaces.
    """
    run_dir = _run_through_materialize(
        tiny_vcf_gz=tiny_vcf_gz,
        genomeclaw_layout=genomeclaw_layout,
        gene_symbol="BRCA1",
        # Two rows for BRCA1: a non-MANE Select transcript (loeuf=0.9 —
        # red herring) and the MANE Select row (loeuf=0.123 — the
        # canonical value the join should pick).
        constraint_rows=[
            ("BRCA1", "false", "0.900"),
            ("BRCA1", "true", "0.123"),
        ],
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row = conn.execute(
            "SELECT gene_loeuf FROM variants WHERE chrom = 'chr17' AND pos = 43044295"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    (gene_loeuf,) = row
    assert gene_loeuf == pytest.approx(0.123), (
        f"expected MANE Select LOEUF (0.123), got {gene_loeuf} — "
        "join may have picked the non-MANE transcript row"
    )


@pytest.mark.needs_bio
def test_invR001_materialize_records_gnomad_constraint_in_provenance(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``INV-R001``: the materialize step's provenance records the
    gnomAD constraint source path + sha256 + release tag.

    This makes the join reproducible: a future rerun against the same
    constraint TSV produces byte-equivalent gene_loeuf values, and a
    drift surfaces in provenance.json before it surfaces in user-visible
    output.
    """
    run_dir = _run_through_materialize(
        tiny_vcf_gz=tiny_vcf_gz,
        genomeclaw_layout=genomeclaw_layout,
        gene_symbol="BRCA1",
        constraint_rows=[("BRCA1", "true", "0.123")],
    )

    provenance = json.loads((run_dir / "provenance.json").read_text())
    materialize_step = next((s for s in provenance["steps"] if s["step"] == "materialize"), None)
    assert materialize_step is not None

    # Inputs must include the constraint TSV with its sha256.
    constraint_input = next(
        (i for i in materialize_step["inputs"] if "constraint" in i["path"]),
        None,
    )
    assert constraint_input is not None, (
        f"materialize step missing gnomad-constraint input: "
        f"inputs={[i['path'] for i in materialize_step['inputs']]}"
    )
    assert constraint_input["path"].endswith("gnomad.v4.1.constraint_metrics.tsv")
    assert len(constraint_input["sha256"]) == 64

    # Params must record the release tag so a rebuild can re-resolve it.
    assert materialize_step["params"].get("gnomad_constraint_release") == "v4.1"


@pytest.mark.needs_bio
def test_materialize_works_without_reference_dir_backwards_compat(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``materialize(run_dir=...)`` without ``reference_dir`` still works
    (backwards-compat). Every gene_loeuf is NULL; no errors raised; no
    constraint input recorded in provenance.

    Defends the existing call sites in ``test_annotate.py`` and
    ``test_materialize.py`` that don't pass ``reference_dir``.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="loeuf-002",
    )
    normalize(run_dir=run_dir)
    _stage_annotated_vcf_with_csq(run_dir, gene_symbol="BRCA1")
    # Call without reference_dir — must not raise.
    materialize(run_dir=run_dir)

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        row = conn.execute(
            "SELECT gene_loeuf FROM variants WHERE chrom = 'chr17' AND pos = 43044295"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    (gene_loeuf,) = row
    assert gene_loeuf is None

"""Phase 2 — default coverage-QC panel auto-engage tests.

Seven tests covering:
1. Auto-engage with default panel when bam provided, no bed.
2. Explicit --bed overrides the default panel.
3. --no-coverage-qc opt-out skips coverage_qc.
4. No bam → no coverage_qc (unchanged behavior).
5. Default panel missing → WARNING log + ingest continues + coverage_qc empty.
6. INV-R001: params_json records panel provenance.
7. Default panel v1 contains all disease-area genes.

Tests 1–6 mock run_mosdepth to avoid needing the `needs_bio` environment.
Test 7 is pure-Python (reads the bundled BED; no subprocess).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_layout(tmp_path: Path) -> dict[str, Path]:
    """Minimal per-test layout mirroring the integration conftest.

    `reference_fasta` is a touched empty file so `ingest()`'s CRAM precondition
    (`reference_fasta is not None and reference_fasta.exists()`) passes. The
    real fasta is never opened because these tests mock `run_mosdepth` — the
    file only needs to exist for the existence check + the provenance sha256.
    """
    raw = tmp_path / "raw"
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    scratch = tmp_path / "scratch"
    for d in (raw, reference, derived, scratch):
        d.mkdir(parents=True)
    reference_fasta = reference / "GRCh38.fa"
    reference_fasta.write_bytes(b"")  # touch — content not read (run_mosdepth mocked)
    os.environ.setdefault("GENOMECLAW_SKIP_PREFLIGHT", "1")
    return {
        "raw": raw,
        "reference": reference,
        "derived": derived,
        "scratch": scratch,
        "reference_fasta": reference_fasta,
    }


def _make_minimal_vcf(tmp_path: Path) -> Path:
    """Write a minimal bgzip'd VCF with GRCh38 chr1 contig for reference-build sniff."""
    vcf_text = (
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"genotype\">\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
        "chr1\t1000\t.\tA\tG\t60\tPASS\t.\tGT\t0/1\n"
    )
    import subprocess
    plain = tmp_path / "test.vcf"
    plain.write_text(vcf_text)
    bgz = tmp_path / "test.vcf.gz"
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
    return bgz


def _make_minimal_bed(tmp_path: Path, genes: list[str] | None = None) -> Path:
    """Write a minimal plain BED for use as an explicit custom panel."""
    if genes is None:
        genes = ["CUSTOM_GENE_A", "CUSTOM_GENE_B"]
    lines = "\n".join(f"chr1\t{1000 + i * 5000}\t{1000 + i * 5000 + 100}\t{g}" for i, g in enumerate(genes))
    bed = tmp_path / "custom.bed"
    bed.write_text(lines + "\n")
    return bed


def _fake_mosdepth_result(genes: list[str], tmp_path: Path):  # noqa: ANN201
    """Return a MosdepthResult with a synthetic regions.bed.gz matching the given genes."""
    from genomeclaw_toolkit.prep._mosdepth import MosdepthResult

    lines = "".join(
        f"chr1\t{1000 + i * 5000}\t{1000 + i * 5000 + 100}\t{g}\t25.0\n"
        for i, g in enumerate(genes)
    )
    regions_bed = tmp_path / "mos.regions.bed.gz"
    regions_bed.write_bytes(gzip.compress(lines.encode()))
    summary = tmp_path / "mos.mosdepth.summary.txt"
    summary.write_text("chrom\tstart\tend\tmean\n")
    return MosdepthResult(regions_bed=regions_bed, summary=summary)


def _default_panel_genes() -> list[str]:
    """Load the gene list from the bundled default panel BED."""
    from genomeclaw_toolkit.prep.ingest import _DEFAULT_PANEL_BED_NAME
    data_dir = Path(__file__).parent.parent.parent / "src" / "genomeclaw_toolkit" / "data"
    bed_path = data_dir / _DEFAULT_PANEL_BED_NAME
    genes = set()
    with gzip.open(bed_path, "rt") as fh:
        for line in fh:
            if line.strip():
                gene_exon = line.split("\t")[3].strip()
                gene = gene_exon.rsplit("_exon_", 1)[0]
                genes.add(gene)
    return sorted(genes)


# ---------------------------------------------------------------------------
# Test 1 — auto-engage default panel when bam provided, no bed
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_ingest_with_cram_auto_engages_default_panel(tmp_path: pytest.fixture) -> None:
    """When bam provided + bed=None, ingest uses the default panel + populates coverage_qc.

    Mocks run_mosdepth to avoid needing mosdepth binary; validates the
    auto-engage logic and that rows land in coverage_qc.
    """
    layout = _make_layout(tmp_path)
    vcf = _make_minimal_vcf(tmp_path)
    # A fake CRAM path; we patch run_mosdepth so it never actually opens it
    fake_cram = tmp_path / "fake.cram"
    fake_cram.write_bytes(b"fake")

    # Build a fake mosdepth result that uses a subset of the default panel genes
    panel_genes = _default_panel_genes()[:5]
    (tmp_path / "mos_out").mkdir(exist_ok=True)
    fake_result = _fake_mosdepth_result(panel_genes, tmp_path / "mos_out")

    with (
        patch("genomeclaw_toolkit.prep.ingest.run_mosdepth", return_value=fake_result),
        patch("genomeclaw_toolkit.prep.ingest.mosdepth_version", return_value="0.3.10"),
    ):
        from genomeclaw_toolkit.prep.ingest import ingest

        run_dir = ingest(
            vcf=vcf,
            reference_dir=layout["reference"],
            derived_root=layout["derived"],
            sample_id="test-auto",
            bam=fake_cram,
            reference_fasta=layout["reference_fasta"],
            # No bed= — auto-engage should kick in
        )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT gene, mean_depth FROM coverage_qc ORDER BY gene").fetchall()
    finally:
        conn.close()

    assert len(rows) == len(panel_genes), (
        f"Expected {len(panel_genes)} coverage_qc rows; got {len(rows)}"
    )
    gene_names = {r[0] for r in rows}
    assert gene_names == set(panel_genes)
    for _gene, mean_depth in rows:
        assert mean_depth == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Test 2 — explicit --bed overrides the default panel
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_ingest_with_cram_and_explicit_bed_overrides_default(tmp_path: pytest.fixture) -> None:
    """When bam + explicit bed provided, explicit bed is used (not the default panel)."""
    layout = _make_layout(tmp_path)
    vcf = _make_minimal_vcf(tmp_path)
    fake_cram = tmp_path / "fake.cram"
    fake_cram.write_bytes(b"fake")

    custom_genes = ["CUSTOM_GENE_A", "CUSTOM_GENE_B"]
    custom_bed = _make_minimal_bed(tmp_path, genes=custom_genes)

    (tmp_path / "mos_out").mkdir(exist_ok=True)
    fake_result = _fake_mosdepth_result(custom_genes, tmp_path / "mos_out")

    with (
        patch("genomeclaw_toolkit.prep.ingest.run_mosdepth", return_value=fake_result) as mock_run,
        patch("genomeclaw_toolkit.prep.ingest.mosdepth_version", return_value="0.3.10"),
    ):
        from genomeclaw_toolkit.prep.ingest import ingest

        run_dir = ingest(
            vcf=vcf,
            reference_dir=layout["reference"],
            derived_root=layout["derived"],
            sample_id="test-explicit-bed",
            bam=fake_cram,
            bed=custom_bed,  # explicit override
            reference_fasta=layout["reference_fasta"],
        )

    # mosdepth should have been called with the custom bed, not the default
    call_args = mock_run.call_args
    assert call_args is not None
    assert call_args.kwargs["bed"] == custom_bed, (
        f"Expected explicit custom bed; got {call_args.kwargs['bed']}"
    )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT gene FROM coverage_qc ORDER BY gene").fetchall()
    finally:
        conn.close()

    gene_names = {r[0] for r in rows}
    assert gene_names == set(custom_genes), (
        f"Expected custom genes {custom_genes}; got {gene_names}"
    )


# ---------------------------------------------------------------------------
# Test 3 — opt-out skips coverage_qc
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_ingest_with_cram_and_opt_out_skips_coverage_qc(tmp_path: pytest.fixture) -> None:
    """no_coverage_qc=True skips the mosdepth step; coverage_qc remains empty."""
    layout = _make_layout(tmp_path)
    vcf = _make_minimal_vcf(tmp_path)
    fake_cram = tmp_path / "fake.cram"
    fake_cram.write_bytes(b"fake")

    with patch("genomeclaw_toolkit.prep.ingest.run_mosdepth") as mock_run:
        from genomeclaw_toolkit.prep.ingest import ingest

        run_dir = ingest(
            vcf=vcf,
            reference_dir=layout["reference"],
            derived_root=layout["derived"],
            sample_id="test-opt-out",
            bam=fake_cram,
            reference_fasta=layout["reference_fasta"],
            no_coverage_qc=True,  # opt-out
        )

    # mosdepth must NOT have been called
    mock_run.assert_not_called()

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM coverage_qc").fetchone()
    finally:
        conn.close()

    assert rows is not None and rows[0] == 0, (
        f"Expected empty coverage_qc; got {rows[0]} rows"
    )


# ---------------------------------------------------------------------------
# Test 4 — no bam → no coverage_qc
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_ingest_without_cram_does_not_engage(tmp_path: pytest.fixture) -> None:
    """Without bam, the coverage_qc step is unchanged (remains empty)."""
    layout = _make_layout(tmp_path)
    vcf = _make_minimal_vcf(tmp_path)

    with patch("genomeclaw_toolkit.prep.ingest.run_mosdepth") as mock_run:
        from genomeclaw_toolkit.prep.ingest import ingest

        run_dir = ingest(
            vcf=vcf,
            reference_dir=layout["reference"],
            derived_root=layout["derived"],
            sample_id="test-no-bam",
            # No bam= — mosdepth should not fire
        )

    mock_run.assert_not_called()

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM coverage_qc").fetchone()
    finally:
        conn.close()

    assert rows is not None and rows[0] == 0


# ---------------------------------------------------------------------------
# Test 5 — default panel missing → WARNING + continue + empty coverage_qc
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_default_panel_missing_warns_and_skips(
    tmp_path: pytest.fixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When default panel BED is missing, ingest emits WARNING and continues without coverage_qc."""
    layout = _make_layout(tmp_path)
    vcf = _make_minimal_vcf(tmp_path)
    fake_cram = tmp_path / "fake.cram"
    fake_cram.write_bytes(b"fake")

    with (
        patch(
            "genomeclaw_toolkit.prep.ingest._default_panel_bed_path",
            return_value=None,  # Simulate missing panel
        ),
        patch("genomeclaw_toolkit.prep.ingest.run_mosdepth") as mock_run,
        caplog.at_level(logging.WARNING, logger="genomeclaw_toolkit.prep.ingest"),
    ):
        from genomeclaw_toolkit.prep.ingest import ingest

        run_dir = ingest(
            vcf=vcf,
            reference_dir=layout["reference"],
            derived_root=layout["derived"],
            sample_id="test-missing-panel",
            bam=fake_cram,
            reference_fasta=layout["reference_fasta"],
            # No bed= — expects default panel, but it's patched to missing
        )

    # mosdepth must NOT have been called (no panel to use)
    mock_run.assert_not_called()

    # A WARNING should have been logged about the missing panel
    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("panel" in m.lower() or "coverage" in m.lower() for m in warning_msgs), (
        f"Expected a warning about the missing panel; log records: {caplog.records}"
    )

    # coverage_qc should be empty
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM coverage_qc").fetchone()
    finally:
        conn.close()
    assert rows is not None and rows[0] == 0


# ---------------------------------------------------------------------------
# Test 6 — INV-R001: params_json records panel provenance
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_invR001_params_json_records_panel_provenance(tmp_path: pytest.fixture) -> None:
    """INV-R001: coverage_qc row's params_json includes panel_version + panel_path + threshold."""
    layout = _make_layout(tmp_path)
    vcf = _make_minimal_vcf(tmp_path)
    fake_cram = tmp_path / "fake.cram"
    fake_cram.write_bytes(b"fake")

    panel_genes = ["BRCA1"]
    (tmp_path / "mos_out").mkdir(exist_ok=True)
    fake_result = _fake_mosdepth_result(panel_genes, tmp_path / "mos_out")

    with (
        patch("genomeclaw_toolkit.prep.ingest.run_mosdepth", return_value=fake_result),
        patch("genomeclaw_toolkit.prep.ingest.mosdepth_version", return_value="0.3.10"),
    ):
        from genomeclaw_toolkit.prep.ingest import ingest

        run_dir = ingest(
            vcf=vcf,
            reference_dir=layout["reference"],
            derived_root=layout["derived"],
            sample_id="test-provenance",
            bam=fake_cram,
            reference_fasta=layout["reference_fasta"],
            # No bed= — auto-engage default panel
        )

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute("SELECT params_json FROM coverage_qc").fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    params = json.loads(rows[0][0])
    # INV-R001: must record panel version, panel path, and low-coverage threshold
    assert "panel_version" in params, f"params_json missing 'panel_version': {params}"
    assert "panel_path" in params, f"params_json missing 'panel_path': {params}"
    assert "low_coverage_threshold" in params, f"params_json missing 'low_coverage_threshold': {params}"
    assert params["panel_version"] == "v1"
    assert "coverage_panel_default_v1" in params["panel_path"]
    assert params["low_coverage_threshold"] == "20x"


# ---------------------------------------------------------------------------
# Test 7 — bundled BED contains all disease-area panel genes
# ---------------------------------------------------------------------------


def test_default_panel_v1_contains_disease_area_genes() -> None:
    """The bundled default panel BED contains every gene from the sysprompt disease-area panels.

    This test is the cross-link between the agent-system-prompt's canonical
    disease-area panels and the bundled panel BED. If they drift, this test
    catches it.
    """
    # Canonical disease-area genes from agent-system-prompt.md
    REQUIRED_GENES = {
        # Eyesight
        "CFH", "ARMS2", "HTRA1", "C2", "C3", "CFB", "ABCA4", "USH2A",
        "RPE65", "RHO", "RPGR", "MYOC", "OPTN", "TBK1", "CYP1B1", "TIMP3",
        # Cardiovascular
        "LDLR", "APOB", "PCSK9", "APOE", "LPA", "MYH7", "MYBPC3", "TNNT2",
        "KCNQ1", "KCNH2", "SCN5A", "FBN1",
        # Cancer predisposition
        "BRCA1", "BRCA2", "TP53", "MLH1", "MSH2", "MSH6", "PMS2", "APC",
        "MUTYH", "CDH1", "PTEN", "STK11", "PALB2", "ATM", "CHEK2",
        # Neurodegeneration
        "APP", "PSEN1", "PSEN2", "MAPT", "GRN", "C9orf72",
        "LRRK2", "SNCA", "GBA", "HTT",
        # Metabolic
        "TCF7L2", "HNF1A", "HNF4A", "GCK", "MC4R", "FTO", "PPARG",
        "KCNJ11", "GLP1R", "IRS1",
    }

    genes_in_panel = set(_default_panel_genes())

    missing = REQUIRED_GENES - genes_in_panel
    assert not missing, (
        f"Default panel BED is missing {len(missing)} required disease-area genes: "
        f"{sorted(missing)}"
    )


def test_default_panel_uses_real_gencode_coordinates() -> None:
    """Detect drift back to placeholder coordinates.

    The original v1 placeholder shipped exactly 8 deterministic exons per gene
    (1280 total) on chr1 only, with start = chromosome_start + (exon_index * 1200).
    Real GENCODE v44 MANE Select exons number in the thousands and span every
    autosome plus chrX. This test fails if anyone reverts to the placeholder
    pattern.

    Per coverage-panel-v2 Phase 2: accepts BED4 (v1) or BED5 (v2). The v2
    panel adds a 5th `region_class` column; this drift-detection test
    cares about row count + chromosome diversity, not the column count.
    """
    from genomeclaw_toolkit.prep.ingest import _DEFAULT_PANEL_BED_NAME
    data_dir = Path(__file__).parent.parent.parent / "src" / "genomeclaw_toolkit" / "data"
    bed_path = data_dir / _DEFAULT_PANEL_BED_NAME

    rows: list[tuple[str, int, int, str]] = []
    chroms: set[str] = set()
    with gzip.open(bed_path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            assert len(cols) in (4, 5), f"BED row not BED4 or BED5: {line!r}"
            rows.append((cols[0], int(cols[1]), int(cols[2]), cols[3]))
            chroms.add(cols[0])

    # Placeholder shipped 1280 rows; real GENCODE MANE Select for 160 genes is ~2000-5000.
    assert len(rows) > 2000, (
        f"Default panel has only {len(rows)} exons — looks like placeholder data "
        "(real GENCODE v44 MANE Select for 160 genes yields ~2000+ exons)"
    )
    # Placeholder was chr1 only.
    assert len(chroms) > 5, (
        f"Default panel only spans {sorted(chroms)} — looks like placeholder "
        "(real panel spans many chromosomes)"
    )
    # Rows must be sorted by (chrom, start) so mosdepth/htslib treat them efficiently.
    for prev, curr in zip(rows, rows[1:]):
        if prev[0] == curr[0]:
            assert prev[1] <= curr[1], (
                f"BED not sorted at {prev} → {curr} (within-chrom start must be ascending)"
            )

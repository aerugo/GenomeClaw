"""Phase 2 sub-phase 2C-B-2 follow-up — ingest-performance gate.

A real-Nebula smoke (4.8M variants) on 2026-05-09 took 4h09m wall time
under the original ``executemany`` ingest path. Profiling on a 100k
synthetic VCF reproduced the bottleneck (~270s) inside the toolkit
image. After the CSV-staging refactor, the same workload completes in
~1s; this gate locks the speedup in place by failing CI if the same
operation drifts back above 30s.

The test is a perf gate, not an `INV-R001` test per se — but it carries
the ID in its filename because a regression here would make
provenance-correct outputs unusable in practice (the user-facing
"the user makes coffee" expectation in Story 1 disappears).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_PERF_VCF_TEXT_HEADER = """\
##fileformat=VCFv4.2
##contig=<ID=chr1,length=248956422>
##contig=<ID=chr17,length=83257441>
##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tperf-001
"""


def _have_bcftools() -> bool:
    return os.environ.get("GENOMECLAW_HAS_BIO") == "1" and shutil.which("bcftools") is not None


def _generate_synthetic_vcf_text(n: int) -> str:
    """Generate ``n`` synthetic variants — sorted by chrom + pos for tabix.

    Half on chr1, half on chr17, alternating ref/alt bases. Inline (not
    bcftools-driven) so we don't double-bench bcftools' own bgzip cost.
    """
    parts = [_PERF_VCF_TEXT_HEADER]
    refs = "ACGT"
    alts = "CGTA"
    half = n // 2
    for i in range(half):
        parts.append(
            f"chr1\t{1000 + i}\trs{1000000 + i}\t{refs[i % 4]}\t{alts[i % 4]}"
            f"\t60\tPASS\t.\tGT\t{'1/1' if i % 3 == 0 else '0/1'}\n"
        )
    for i in range(n - half):
        parts.append(
            f"chr17\t{1000 + i}\trs{2000000 + i}\t{refs[i % 4]}\t{alts[i % 4]}"
            f"\t60\tPASS\t.\tGT\t{'1/1' if i % 3 == 0 else '0/1'}\n"
        )
    return "".join(parts)


@pytest.fixture(scope="session")
def perf_vcf_gz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 100k-variant bgzipped + indexed synthetic VCF."""
    if not _have_bcftools():
        pytest.skip("perf-gate fixture requires bcftools (set GENOMECLAW_HAS_BIO=1)")
    out_dir = tmp_path_factory.mktemp("perf-vcf")
    plain = out_dir / "perf-100k.vcf"
    plain.write_text(_generate_synthetic_vcf_text(100_000))
    bgz = out_dir / "perf-100k.vcf.gz"
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


_PERF_BUDGET_SECONDS = 30.0


@pytest.mark.needs_bio
def test_ingest_100k_variants_completes_under_30s(perf_vcf_gz: Path, tmp_path: Path) -> None:
    """Ingest a 100k-variant VCF in under 30s — guards against perf regression.

    The pre-fix ``executemany`` path takes ~270s on the same input; the
    CSV-staging path completes in ~1s. The 30s budget leaves headroom
    for noisier CI runners + future incremental work without masking a
    real regression.
    """
    from genomeclaw_toolkit.prep.ingest import ingest

    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    reference.mkdir()
    derived.mkdir()

    started = time.monotonic()
    run_dir = ingest(
        vcf=perf_vcf_gz,
        reference_dir=reference,
        derived_root=derived,
        sample_id="perf-001",
    )
    elapsed = time.monotonic() - started

    # Sanity: the store actually got 100k rows (not a fast no-op).
    import duckdb

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM variants").fetchone()
    finally:
        conn.close()
    assert n is not None and n[0] == 100_000, n

    assert elapsed < _PERF_BUDGET_SECONDS, (
        f"ingest of 100k variants took {elapsed:.1f}s "
        f"(budget {_PERF_BUDGET_SECONDS:.0f}s); a regression has been introduced. "
        "See docs/plans/active/ingest-performance/ for the original bench."
    )

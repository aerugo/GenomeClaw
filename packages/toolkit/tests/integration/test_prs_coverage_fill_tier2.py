"""Phase 2 — Tier 2 per-PGS forced-genotyping + cache + merge tests.

Tier 1 (PCA-eligible HGDP+1kGP sites) is panel-keyed; Tier 2 is per-PGS,
keyed by ``(sample, panel_version, pgs_id, scorefile_sha256)``. On cache
hit subsequent compute calls skip the bcftools shell-out entirely; on
scorefile SHA mismatch (upstream silent re-harmonisation) the cache is
invalidated and re-built.

Contract assertions:

1. Parse — ``_extract_pgs_sites_from_scorefile`` walks a synthetic hmPOS_GRCh38
   scoring file, returns ``(chr_prefixed_chrom, pos, ref, alt)`` rows.
   Comments + blank lines + indel rows are skipped (Phase 1b Open Question
   Q2: restrict Tier 2 to SNPs until indel concordance is verified).
2. Header — the PGS Catalog ID is parsed out of the ``#pgs_id=`` header
   line. Required for the cache path.
3. Cache path — ``_tier2_cache_path`` is byte-stable and includes the
   scorefile SHA prefix; SHA-mismatch yields a different path.
4. Argv — ``_force_genotype_tier2`` emits the same mpileup→call→norm
   pipe with PGS-derived sites/alleles + INV-D003 scratch staging.
5. Merge — ``_merge_tier1_tier2`` concats Tier 1 + Tier 2 into a
   coordinate-sorted output VCF; overlapping sites collapse cleanly.
6. Cache hit — second ``prepare_coverage_tier2`` call against an identical
   scorefile + warm cache short-circuits subprocess.run.
7. Cache miss — second call against a mutated scorefile (SHA changes)
   builds anew.
"""

from __future__ import annotations

import gzip
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_NORM_OUTPUT_RE = re.compile(r"bcftools norm[^|&]*?--output\s+(\S+)")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_synthetic_tier2_vcf(path: Path) -> None:
    """Emit a tiny synthetic Tier 2 VCF + .tbi sidecar at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "##fileformat=VCFv4.2",
        "##contig=<ID=chr22,length=50818468>",
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">',
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="depth">',
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tMPNRGLQ2K",
        "chr22\t20001\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:28",
        "chr22\t20002\t.\tC\tT\t.\tPASS\t.\tGT:DP\t0/0:31",
    ]
    with gzip.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    (path.parent / (path.name + ".tbi")).write_bytes(b"")


def _bcftools_pipe_fake() -> MagicMock:
    """Fake that parses ``bcftools norm --output <path>`` and materialises the VCF.

    Same regex pattern as the Phase 1 fakes; lets Tier 2 reuse the test idiom.
    """

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        match = _NORM_OUTPUT_RE.search(cmd_str)
        if match:
            _write_synthetic_tier2_vcf(Path(match.group(1)))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return MagicMock(side_effect=_runner)


_SYNTHETIC_SCOREFILE_TEXT = """\
###PGS CATALOG SCORING FILE - see https://www.pgscatalog.org/downloads/#dl_ftp_scoring
#format_version=2.0
#pgs_id=PGS000018
#pgs_name=metaGRS_CAD
#trait_reported=Coronary artery disease
#genome_build=GRCh38
#variants_number=4
hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight
22\t20001\tG\tA\t0.0123
22\t20002\tT\tC\t-0.0456
22\t20003\tACGT\tA\t0.0789
22\t20004\tA\tACGT\t-0.0321
22\t20005\tC\tA\t0.0234
"""


@pytest.fixture
def synthetic_scorefile(tmp_path: Path) -> Path:
    """A tiny PGS Catalog hmPOS_GRCh38 scoring file with 3 SNPs + 2 indels.

    Indels (row 3 + row 4) test that ``_extract_pgs_sites_from_scorefile``
    SNP-filters per Open Question Q2 — Tier 2 restricts to SNPs until
    indel concordance against GATK HC is verified.
    """
    scorefile = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    with gzip.open(scorefile, "wt") as fh:
        fh.write(_SYNTHETIC_SCOREFILE_TEXT)
    return scorefile


@pytest.fixture
def synthetic_cram(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"CRAM-fixture")
    (raw / "MPNRGLQ2K.cram.crai").write_bytes(b"")
    return cram


@pytest.fixture
def synthetic_fasta(tmp_path: Path) -> Path:
    ref = tmp_path / "reference" / "grch38"
    ref.mkdir(parents=True)
    fasta = ref / "grch38.fa.gz"
    fasta.write_bytes(b"")
    (ref / "grch38.fa.gz.fai").write_bytes(b"")
    return fasta


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_extract_pgs_sites_from_scorefile_parses_hmpos_grch38(
    synthetic_scorefile: Path,
) -> None:
    """Synthetic PGS Catalog scorefile → ``(chrN, pos, ref, alt)`` SNP rows.

    The other_allele column is REF; effect_allele is ALT. The synthetic
    scorefile has 5 rows; indels (rows 3 + 4 — REF or ALT length > 1) drop
    out, leaving 3 SNPs.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _extract_pgs_sites_from_scorefile

    rows = _extract_pgs_sites_from_scorefile(synthetic_scorefile)

    assert rows == [
        ("chr22", 20001, "A", "G"),
        ("chr22", 20002, "C", "T"),
        ("chr22", 20005, "A", "C"),
    ]


def test_extract_pgs_id_from_scorefile(synthetic_scorefile: Path) -> None:
    """The ``#pgs_id=PGS000018`` header is parsed out cleanly."""
    from genomeclaw_toolkit.prep.coverage_fill import _extract_pgs_id_from_scorefile

    assert _extract_pgs_id_from_scorefile(synthetic_scorefile) == "PGS000018"


def test_extract_pgs_sites_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    """Robust to PGS Catalog comment + blank lines + a trailing newline."""
    from genomeclaw_toolkit.prep.coverage_fill import _extract_pgs_sites_from_scorefile

    scorefile = tmp_path / "tiny.txt.gz"
    with gzip.open(scorefile, "wt") as fh:
        fh.write(
            "###header comment\n"
            "#pgs_id=PGS000999\n"
            "#format_version=2.0\n"
            "\n"
            "hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
            "1\t100\tG\tA\t0.1\n"
            "\n"
        )

    rows = _extract_pgs_sites_from_scorefile(scorefile)
    assert rows == [("chr1", 100, "A", "G")]


# ---------------------------------------------------------------------------
# Cache path semantics
# ---------------------------------------------------------------------------


def test_tier2_cache_path_is_byte_stable(tmp_path: Path) -> None:
    """Identical inputs → identical path. Includes scorefile SHA prefix."""
    from genomeclaw_toolkit.prep.coverage_fill import _tier2_cache_path

    derived = tmp_path / "derived"
    sha = "deadbeefcafe1234" * 4  # 64-char hex
    p1 = _tier2_cache_path(
        derived_root=derived,
        sample_id="MPNRGLQ2K",
        panel_version="v1",
        pgs_id="PGS000018",
        scorefile_sha256=sha,
    )
    p2 = _tier2_cache_path(
        derived_root=derived,
        sample_id="MPNRGLQ2K",
        panel_version="v1",
        pgs_id="PGS000018",
        scorefile_sha256=sha,
    )
    assert p1 == p2
    # Layout contract: sha8 prefix is part of the directory name so cache
    # invalidation on upstream re-harmonisation is visible to the user.
    assert sha[:8] in str(p1)
    assert p1.name == "tier2.vcf.gz"


def test_tier2_cache_path_changes_with_scorefile_sha(tmp_path: Path) -> None:
    """Different scorefile SHA → different cache path (no stale cache hit)."""
    from genomeclaw_toolkit.prep.coverage_fill import _tier2_cache_path

    derived = tmp_path / "derived"
    sha_a = "a" * 64
    sha_b = "b" * 64
    p_a = _tier2_cache_path(
        derived_root=derived,
        sample_id="MPNRGLQ2K",
        panel_version="v1",
        pgs_id="PGS000018",
        scorefile_sha256=sha_a,
    )
    p_b = _tier2_cache_path(
        derived_root=derived,
        sample_id="MPNRGLQ2K",
        panel_version="v1",
        pgs_id="PGS000018",
        scorefile_sha256=sha_b,
    )
    assert p_a != p_b


# ---------------------------------------------------------------------------
# Force-genotype shape + INV-D003
# ---------------------------------------------------------------------------


def test_force_genotype_tier2_invokes_correct_bcftools_pipe(
    tmp_path: Path,
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """Tier 2 reuses the same pipe shape as Tier 1, with scorefile-derived TSVs.

    The wrapper materialises sites + alleles TSVs from the scorefile in
    its scratch dir, then invokes the canonical mpileup→call→norm pipe.
    Asserts the canonical flag set is present in the argv haystack.
    """
    from genomeclaw_toolkit.prep.coverage_fill import (
        _force_genotype_tier2,
    )

    pgs_rows = [("chr22", 20001, "A", "G"), ("chr22", 20002, "C", "T")]
    output_vcf = tmp_path / "derived" / "tier2.vcf.gz"

    fake = _bcftools_pipe_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake):
        _force_genotype_tier2(
            cram_path=synthetic_cram,
            pgs_rows=pgs_rows,
            fasta=synthetic_fasta,
            output_vcf=output_vcf,
        )

    haystack = "\n".join(
        " ".join(str(x) for x in call.args[0]) for call in fake.call_args_list
    )
    # Same canonical flags as Tier 1 (the pipe template is shared).
    assert "bcftools mpileup" in haystack
    assert "bcftools call" in haystack
    assert "bcftools norm" in haystack
    assert "--constrain alleles" in haystack
    assert "--multiallelics -any" in haystack
    assert str(synthetic_cram) in haystack
    # The wrapper wrote PGS-derived TSVs into its scratch dir; their paths
    # show up as the --regions-file / --targets-file args.
    assert "--regions-file" in haystack
    assert "--targets-file" in haystack
    assert output_vcf.exists(), "Tier 2 wrapper must promote its scratch VCF to output_vcf"


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def test_merge_tier1_tier2_concats_and_sorts(tmp_path: Path) -> None:
    """``_merge_tier1_tier2`` shells out to ``bcftools concat --allow-overlaps`` + sort.

    Verified via argv inspection — the fake doesn't run real bcftools, so
    the test asserts the wrapper builds the right pipeline. Materialises
    a placeholder merged VCF on the side so any downstream presence check
    is satisfied.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _merge_tier1_tier2

    tier1 = tmp_path / "tier1.vcf.gz"
    tier2 = tmp_path / "tier2.vcf.gz"
    merged = tmp_path / "merged.vcf.gz"
    tier1.write_bytes(b"\x1f\x8b")
    tier2.write_bytes(b"\x1f\x8b")

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        # bcftools sort emits a stable sorted VCF; presence-only output.
        if "bcftools sort" in cmd_str:
            match = re.search(r"--output\s+(\S+)", cmd_str)
            if match:
                Path(match.group(1)).write_bytes(b"\x1f\x8b")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    fake = MagicMock(side_effect=_runner)
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake):
        _merge_tier1_tier2(tier1=tier1, tier2=tier2, output_vcf=merged)

    haystack = "\n".join(
        " ".join(str(x) for x in call.args[0]) for call in fake.call_args_list
    )
    assert "bcftools concat" in haystack
    assert "--allow-overlaps" in haystack
    assert "bcftools sort" in haystack
    assert str(tier1) in haystack
    assert str(tier2) in haystack
    assert merged.exists()


# ---------------------------------------------------------------------------
# Orchestrator + cache semantics
# ---------------------------------------------------------------------------


def test_prepare_coverage_tier2_cache_hit_skips_subprocess(
    tmp_path: Path,
    synthetic_cram: Path,
    synthetic_fasta: Path,
    synthetic_scorefile: Path,
) -> None:
    """Second invocation against identical inputs hits cache — no subprocess.run."""
    from genomeclaw_toolkit.prep.coverage_fill import prepare_coverage_tier2

    fake_1 = _bcftools_pipe_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_1):
        prepare_coverage_tier2(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            scorefile_path=synthetic_scorefile,
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )
    assert fake_1.call_count >= 1, "first run must shell out to bcftools"

    fake_2 = MagicMock()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_2):
        prepare_coverage_tier2(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            scorefile_path=synthetic_scorefile,
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )
    assert fake_2.call_count == 0, "cache-hit must not shell out"


def test_prepare_coverage_tier2_cache_miss_on_scorefile_change(
    tmp_path: Path,
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """Mutated scorefile content → different SHA → new cache path → new build."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        _extract_pgs_id_from_scorefile,
        prepare_coverage_tier2,
    )

    scorefile = tmp_path / "PGS000018_hmPOS_GRCh38.txt.gz"
    with gzip.open(scorefile, "wt") as fh:
        fh.write(_SYNTHETIC_SCOREFILE_TEXT)

    fake_1 = _bcftools_pipe_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_1):
        first_path = prepare_coverage_tier2(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            scorefile_path=scorefile,
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )

    # Re-write the scorefile with an additional row → SHA changes.
    with gzip.open(scorefile, "wt") as fh:
        fh.write(
            _SYNTHETIC_SCOREFILE_TEXT
            + "22\t20010\tT\tC\t0.0042\n"  # extra SNP row → new SHA
        )
    fake_2 = _bcftools_pipe_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_2):
        second_path = prepare_coverage_tier2(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            scorefile_path=scorefile,
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )

    assert first_path != second_path, "Cache invalidation on scorefile SHA change failed"
    assert fake_2.call_count >= 1, "cache miss must rebuild via bcftools"
    assert _extract_pgs_id_from_scorefile(scorefile) == "PGS000018"

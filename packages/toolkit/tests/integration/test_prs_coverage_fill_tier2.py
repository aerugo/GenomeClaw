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


def test_force_genotype_tier2_refuses_to_cache_empty_vcf(
    tmp_path: Path,
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """Tier 2 MUST raise ``BcftoolsError`` if the bcftools pipe produces a
    header-only VCF (0 records).

    Phase 7 smoke v15 surfaced the silent-cache-of-empty-result pattern:
    the bcftools pipe exited 0 producing only headers; the wrapper happily
    atomic_promoted the empty VCF; every subsequent smoke iteration
    inherited the 0-record cache; the eventual symptom (pgsc_calc match
    rate 2.9%) was 4 layers downstream from the root cause.

    The guard refuses to promote — surfaces the failure loudly + names
    diagnostic categories so the user can fix the underlying issue (most
    common: chromosome-prefix or reference-build mismatch)."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        BcftoolsError,
        _force_genotype_tier2,
    )

    # Fake bcftools pipe that produces a HEADER-ONLY VCF.
    def _empty_runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        match = _NORM_OUTPUT_RE.search(cmd_str)
        if match:
            out_path = Path(match.group(1))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(out_path, "wt") as fh:
                fh.write("##fileformat=VCFv4.2\n")
                fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tMPNRGLQ2K\n")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    pgs_rows = [("chr22", 20001, "A", "G"), ("chr22", 20002, "C", "T")]
    output_vcf = tmp_path / "derived" / "tier2.vcf.gz"
    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_empty_runner),
    ):
        with pytest.raises(BcftoolsError) as exc_info:
            _force_genotype_tier2(
                cram_path=synthetic_cram,
                pgs_rows=pgs_rows,
                fasta=synthetic_fasta,
                output_vcf=output_vcf,
            )

    msg = str(exc_info.value)
    assert "ZERO output records" in msg, msg
    assert "2 input PGS sites" in msg, (
        f"diagnostic should reference the input site count for context; got: {msg}"
    )
    assert "chr" in msg.lower(), f"diagnostic must mention chromosome prefix; got: {msg}"
    assert "NOT caching" in msg, msg
    assert not output_vcf.exists(), (
        f"empty tier2 VCF must NOT be cached; found at {output_vcf}"
    )


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


def test_merge_tier1_tier2_filters_to_autosomes_only(tmp_path: Path) -> None:
    """``_merge_tier1_tier2`` drops sex (chrX, chrY) and mito (chrM) records
    before writing the merged VCF.

    Regression guard: Phase 7 smoke v9 surfaced ``plink2`` (inside a
    pgsc_calc DooD sibling) refusing chrX import without sex info
    (``--psam``). Until the wrapper supplies sex, the merge filter drops
    these chromosomes so the downstream pipeline doesn't fail. The pipe
    must include ``bcftools view --targets chr1,chr2,...,chr22``; the
    target list must be exactly the 22 autosomes (no chrX/chrY/chrM)."""
    from genomeclaw_toolkit.prep.coverage_fill import _merge_tier1_tier2

    tier1 = tmp_path / "tier1.vcf.gz"
    tier2 = tmp_path / "tier2.vcf.gz"
    merged = tmp_path / "merged.vcf.gz"
    tier1.write_bytes(b"\x1f\x8b")
    tier2.write_bytes(b"\x1f\x8b")

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        if "bcftools view" in cmd_str:
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
    assert "bcftools view" in haystack, "merge pipe must include a view step for filtering"
    assert "--targets" in haystack, "filter step must use --targets"
    # Every autosome must appear in the targets list.
    expected_targets = ",".join(f"chr{n}" for n in range(1, 23))
    assert expected_targets in haystack, (
        f"merge pipe must filter to autosomes only; expected '{expected_targets}' in haystack"
    )
    # And the sex/mito chromosomes must NOT appear in --targets.
    # Build a sloppy guard — re-extract the --targets value via regex and
    # assert chrX/chrY/chrM aren't in the comma-list.
    targets_match = re.search(r"--targets\s+(\S+)", haystack)
    assert targets_match is not None
    targets_set = set(targets_match.group(1).split(","))
    assert "chrX" not in targets_set, f"chrX must be filtered out; got {sorted(targets_set)}"
    assert "chrY" not in targets_set, f"chrY must be filtered out; got {sorted(targets_set)}"
    assert "chrM" not in targets_set, f"chrM must be filtered out; got {sorted(targets_set)}"


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


# ---------------------------------------------------------------------------
# Allele orientation against fasta (pgs-allele-orientation plan, F7)
# ---------------------------------------------------------------------------


def test_parse_faidx_fasta_parses_multi_record_output() -> None:
    """``_parse_faidx_fasta`` turns samtools faidx output into a
    ``{(chrom, pos): base}`` dict.

    samtools format:
        >chr1:12345-12345
        A
        >chr1:67890-67890
        C
    """
    from genomeclaw_toolkit.prep.coverage_fill import _parse_faidx_fasta

    text = ">chr1:12345-12345\nA\n>chr1:67890-67890\nC\n>chr22:42126499-42126499\nG\n"
    result = _parse_faidx_fasta(text)
    assert result == {
        ("chr1", 12345): "A",
        ("chr1", 67890): "C",
        ("chr22", 42126499): "G",
    }


def test_parse_faidx_fasta_uppercases_bases() -> None:
    """samtools may emit lowercase bases (soft-masked regions); the parser
    normalises to uppercase so the orientation comparison is case-blind."""
    from genomeclaw_toolkit.prep.coverage_fill import _parse_faidx_fasta

    text = ">chr1:1000-1000\nt\n>chr1:2000-2000\nG\n"
    result = _parse_faidx_fasta(text)
    assert result == {("chr1", 1000): "T", ("chr1", 2000): "G"}


def test_get_reference_bases_issues_single_bulk_subprocess(tmp_path: Path) -> None:
    """``_get_reference_bases`` calls samtools faidx ONCE with a regions
    file, not once per site (1.7M individual calls would be infeasible)."""
    from genomeclaw_toolkit.prep.coverage_fill import _get_reference_bases

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    sites = [("chr1", 100), ("chr1", 200), ("chr22", 30000)]

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        # Must be exactly ONE call: samtools faidx <fasta> -r <regions>.
        assert cmd[0] == "samtools" and cmd[1] == "faidx", cmd
        # Find the -r flag + read the regions file content.
        r_idx = cmd.index("-r")
        regions_path = Path(cmd[r_idx + 1])
        regions_content = regions_path.read_text().splitlines()
        # Each input site → one region line `<chrom>:<pos>-<pos>`.
        assert set(regions_content) == {
            "chr1:100-100",
            "chr1:200-200",
            "chr22:30000-30000",
        }, regions_content
        # Emit a synthetic faidx response.
        stdout = b">chr1:100-100\nA\n>chr1:200-200\nT\n>chr22:30000-30000\nG\n"
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr=b"")

    fake = MagicMock(side_effect=_runner)
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake):
        result = _get_reference_bases(fasta, sites)

    assert fake.call_count == 1, f"expected single bulk call; got {fake.call_count}"
    assert result == {("chr1", 100): "A", ("chr1", 200): "T", ("chr22", 30000): "G"}


def test_prepare_coverage_tier2_sorts_oriented_rows_before_force_genotype(
    tmp_path: Path,
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """``prepare_coverage_tier2`` sorts oriented rows by (chrom, pos) before
    handing them to ``_force_genotype_tier2``.

    Without sort, bcftools mpileup emits records in the regions-file order
    (= scorefile order, which isn't guaranteed sorted within chromosomes);
    ``bcftools index --tbi`` then fails with
    ``[E::hts_idx_push] Unsorted positions on sequence #N``. Phase-7
    smoke v20 (2026-05-20) regression guard."""
    import json as _json

    from genomeclaw_toolkit.prep.coverage_fill import prepare_coverage_tier2

    # A scorefile with INTENTIONALLY out-of-order positions within chr22.
    scorefile = tmp_path / "PGS-unordered_hmPOS_GRCh38.txt.gz"
    scorefile_text = (
        "#pgs_id=PGS999999\n"
        "#genome_build=GRCh38\n"
        "hm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n"
        # Deliberately reversed coordinate order:
        "22\t30000\tG\tA\t0.5\n"
        "22\t20000\tT\tC\t0.3\n"
        "22\t10000\tC\tT\t0.1\n"
    )
    with gzip.open(scorefile, "wt") as fh:
        fh.write(scorefile_text)

    captured_sites_files: list[str] = []

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        if "samtools faidx" in cmd_str:
            # Return reference bases that match the ``other_allele`` for each
            # row, so all three sites are KEPT (no swap, no skip).
            r_idx = cmd.index("-r")
            regions = Path(cmd[r_idx + 1]).read_text().splitlines()
            ref_by_pos = {30000: "A", 20000: "C", 10000: "T"}
            out_lines: list[str] = []
            for region in regions:
                chrom, rest = region.split(":")
                pos = int(rest.split("-")[0])
                out_lines += [f">{region}", ref_by_pos.get(pos, "X")]
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=("\n".join(out_lines) + "\n").encode(),
                stderr=b"",
            )
        if "--regions-file" in cmd_str:
            m = re.search(r"--regions-file\s+(\S+)", cmd_str)
            if m:
                captured_sites_files.append(Path(m.group(1)).read_text())
        if "bcftools" in cmd_str:
            match = re.search(r"bcftools norm[^|&]*?--output\s+(\S+)", cmd_str)
            if match:
                out_path = Path(match.group(1))
                _write_synthetic_tier2_vcf(out_path)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    output_root = tmp_path / "derived"
    fake = MagicMock(side_effect=_runner)
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake):
        prepare_coverage_tier2(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            scorefile_path=scorefile,
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=output_root,
        )

    # The sites file passed to bcftools mpileup MUST be coordinate-sorted.
    assert captured_sites_files, "no --regions-file sites TSV captured"
    sites_content = captured_sites_files[-1]
    lines = [line for line in sites_content.splitlines() if line.strip()]
    # Expected sorted order: chr22 10000, 20000, 30000.
    assert lines == ["chr22\t10000", "chr22\t20000", "chr22\t30000"], (
        f"sites TSV must be coordinate-sorted; got:\n{lines}"
    )


def test_get_reference_bases_tolerates_samtools_partial_failure(
    tmp_path: Path,
) -> None:
    """samtools faidx returns rc=1 if ANY requested region's contig is
    missing from the .fai (alt contigs like ``chr7_KI270803v1_alt`` that
    a primary-assembly fasta doesn't have). It STILL emits stdout records
    for the successful lookups; the orientation step naturally skips
    missing-from-dict sites. Don't fatal on rc != 0 when stdout has
    content.

    Phase 7 smoke v18 (2026-05-20) regression guard."""
    from genomeclaw_toolkit.prep.coverage_fill import _get_reference_bases

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    sites = [("chr1", 100), ("chr7_KI270803v1_alt", 510689), ("chr1", 200)]

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        # samtools emits stdout for the successful lookups + stderr
        # warnings + rc=1.
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout=b">chr1:100-100\nA\n>chr1:200-200\nT\n",
            stderr=(
                b"[W::fai_get_val] Reference chr7_KI270803v1_alt:510689-510689 "
                b"not found in FASTA file, returning empty sequence\n"
                b"[faidx] Failed to fetch sequence in chr7_KI270803v1_alt:510689-510689\n"
            ),
        )

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        result = _get_reference_bases(fasta, sites)

    # The two resolvable sites are returned; the alt-contig site is absent
    # (which downstream orient() treats as a skip).
    assert result == {("chr1", 100): "A", ("chr1", 200): "T"}, result


def test_get_reference_bases_raises_when_no_stdout(tmp_path: Path) -> None:
    """When samtools faidx exits non-zero AND produces no stdout, the
    failure is genuine (e.g., missing fasta, .fai not built) — raise."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        SamtoolsError,
        _get_reference_bases,
    )

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    sites = [("chr1", 100)]

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout=b"", stderr=b"[faidx] no .fai\n"
        )

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        with pytest.raises(SamtoolsError, match="produced no stdout"):
            _get_reference_bases(fasta, sites)


def test_orient_pgs_sites_keeps_correct_orientation(tmp_path: Path) -> None:
    """Site where other_allele == actual reference: ROW IS KEPT AS-IS,
    swapped counter stays at 0."""
    from genomeclaw_toolkit.prep.coverage_fill import _orient_pgs_sites_against_fasta

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    rows = [("chr1", 100, "A", "G")]  # other_allele=A, effect_allele=G

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b">chr1:100-100\nA\n", stderr=b""
        )

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        kept, skipped, swapped = _orient_pgs_sites_against_fasta(rows, fasta)

    assert kept == [("chr1", 100, "A", "G")], kept
    assert skipped == 0
    assert swapped == 0


def test_orient_pgs_sites_swaps_reversed_orientation(tmp_path: Path) -> None:
    """Site where effect_allele == actual reference: REF/ALT are SWAPPED;
    swapped counter += 1.

    This is the smoke v17 reproducer: scorefile gives ``A,G`` but actual
    reference at the position is ``G``; the wrapper must emit
    ``ref=G, alt=A`` (swapped) so bcftools accepts the row."""
    from genomeclaw_toolkit.prep.coverage_fill import _orient_pgs_sites_against_fasta

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    rows = [("chr1", 100, "A", "G")]  # other=A, effect=G; actual ref will be G

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b">chr1:100-100\nG\n", stderr=b""
        )

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        kept, skipped, swapped = _orient_pgs_sites_against_fasta(rows, fasta)

    assert kept == [("chr1", 100, "G", "A")], (
        f"orientation must be swapped — REF=G (actual ref), ALT=A (the other); got: {kept}"
    )
    assert skipped == 0
    assert swapped == 1


def test_orient_pgs_sites_skips_when_neither_allele_matches_reference(
    tmp_path: Path,
) -> None:
    """Site where neither effect nor other matches the actual reference
    (tri-allelic / wrong-build / strand issue): SKIPPED; skipped counter
    += 1; row NOT in output."""
    from genomeclaw_toolkit.prep.coverage_fill import _orient_pgs_sites_against_fasta

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    rows = [("chr1", 100, "A", "G")]  # neither matches T

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b">chr1:100-100\nT\n", stderr=b""
        )

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        kept, skipped, swapped = _orient_pgs_sites_against_fasta(rows, fasta)

    assert kept == []
    assert skipped == 1
    assert swapped == 0


def test_orient_pgs_sites_skips_when_fasta_lookup_missing(tmp_path: Path) -> None:
    """Site whose (chrom, pos) is not in the ref_bases dict (out-of-range
    pos, missing contig, etc.): SKIPPED, not raised."""
    from genomeclaw_toolkit.prep.coverage_fill import _orient_pgs_sites_against_fasta

    fasta = tmp_path / "fake.fa.gz"
    fasta.write_bytes(b"")
    rows = [("chr_invalid", 999, "A", "G")]

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        # samtools couldn't resolve the site; empty stdout.
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_runner),
    ):
        kept, skipped, swapped = _orient_pgs_sites_against_fasta(rows, fasta)

    assert kept == []
    assert skipped == 1
    assert swapped == 0


def test_prepare_coverage_tier2_orients_before_force_genotype(
    tmp_path: Path,
    synthetic_cram: Path,
    synthetic_fasta: Path,
    synthetic_scorefile: Path,
) -> None:
    """End-to-end: ``prepare_coverage_tier2`` calls orientation between
    extract + force-genotype. The alleles TSV bcftools sees carries the
    CORRECTED REF/ALT; the QC json records orientation counts."""
    from genomeclaw_toolkit.prep.coverage_fill import prepare_coverage_tier2

    # The synthetic_scorefile fixture emits known sites; we want to stub
    # the orientation lookup to return one of them swapped.
    output_root = tmp_path / "derived"

    captured_alleles: list[str] = []

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        # samtools faidx for orientation lookup. Synthetic scorefile (above)
        # post-SNP-filter has three sites:
        #   chr22:20001 effect=G other=A → fake ref = A → KEEP (no swap)
        #   chr22:20002 effect=T other=C → fake ref = T → SWAP (REF=T,ALT=C)
        #   chr22:20005 effect=C other=A → fake ref = G → SKIP (neither matches)
        if "samtools faidx" in cmd_str:
            r_idx = cmd.index("-r")
            regions = Path(cmd[r_idx + 1]).read_text().splitlines()
            ref_by_pos: dict[int, str] = {20001: "A", 20002: "T", 20005: "G"}
            out_lines: list[str] = []
            for region in regions:
                chrom, rest = region.split(":")
                pos = int(rest.split("-")[0])
                base = ref_by_pos.get(pos, "X")
                out_lines += [f">{region}", base]
            stdout = ("\n".join(out_lines) + "\n").encode()
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr=b"")
        # bcftools pipe — capture the alleles TSV file path + return non-
        # empty fake output so the empty-cache guard doesn't fire.
        if "--targets-file" in cmd_str:
            m = re.search(r"--targets-file\s+(\S+)", cmd_str)
            if m:
                captured_alleles.append(Path(m.group(1)).read_text())
        if "bcftools" in cmd_str:
            match = re.search(r"bcftools norm[^|&]*?--output\s+(\S+)", cmd_str)
            if match:
                out_path = Path(match.group(1))
                _write_synthetic_tier2_vcf(out_path)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    fake = MagicMock(side_effect=_runner)
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake):
        cache_path = prepare_coverage_tier2(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            scorefile_path=synthetic_scorefile,
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=output_root,
        )

    # The alleles TSV captured BEFORE the bcftools pipe ran:
    assert captured_alleles, "no --targets-file alleles TSV captured"
    alleles_content = captured_alleles[-1]
    # Keep site (20001): scorefile other=A, effect=G; fake ref=A → KEEP as A,G.
    assert "chr22\t20001\tA,G" in alleles_content, alleles_content
    # Swap site (20002): scorefile other=C, effect=T; fake ref=T → SWAP to T,C.
    assert "chr22\t20002\tT,C" in alleles_content, (
        f"swap site should be re-oriented to REF=T,ALT=C; got:\n{alleles_content}"
    )
    # Skip site (20005): scorefile alleles=C,A; fake ref=G → SKIP (NOT in TSV).
    assert "chr22\t20005" not in alleles_content, (
        f"skipped site must NOT be in alleles TSV; got:\n{alleles_content}"
    )

    # QC json schema v2 carries the new orientation counts:
    qc_path = cache_path.parent / "tier2.qc.json"
    import json as _json

    qc = _json.loads(qc_path.read_text())
    assert qc["schema_version"] == "2", qc
    assert "orientation_input_count" in qc, qc
    assert "orientation_kept_count" in qc, qc
    assert "orientation_skipped_count" in qc, qc
    assert "orientation_swapped_count" in qc, qc
    assert qc["orientation_skipped_count"] >= 1, qc
    assert qc["orientation_swapped_count"] >= 1, qc

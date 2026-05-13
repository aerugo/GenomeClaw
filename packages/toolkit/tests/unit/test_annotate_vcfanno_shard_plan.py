"""Unit tests for ``annotate_vcfanno._build_shard_plan``.

Splitting the input by chromosome made the annotate phase parallel and
removed the 24× redundant tabix-seek penalty. But a naive "one shard
per input contig" rule explodes when the input VCF carries the full
GRCh38 contig set (1,500+ decoys / alts / unplaced — verified on the
project owner's Nebula VCF at 2026-05-12: 1,537 contigs total). The
shard planner groups every non-canonical contig into one trailing
catch-all shard so the subprocess overhead is bounded by ``len(canonical) + 1``
rather than ``len(input_chroms)``.

These tests are pure-Python — no bcftools / vcfanno — so they run on
host venvs and protect the partitioning logic against regression
without needing the full bio-image.
"""

from __future__ import annotations

from pathlib import Path

from genomeclaw_toolkit.prep.annotate_vcfanno import (
    _CANONICAL_GRCH38_CHROMS,
    _DBSNP_REFSEQ_TO_UCSC_MAP,
    _build_shard_plan,
    _format_regions_file,
    _persistent_cache_key,
)


def _dummy_gnomad_map() -> dict[str, Path]:
    """Stand-in gnomAD per-chrom map covering all 24 canonical autosomes + X/Y.

    Pinned-fake paths — _build_shard_plan never opens these; it just
    threads them into the returned ShardPlan rows.
    """
    base = Path("/fake/ref/gnomad-exomes/v4.1/by_chrom")
    out = {f"chr{i}": base / f"chr{i}.vcf.bgz" for i in range(1, 23)}
    out["chrX"] = base / "chrX.vcf.bgz"
    out["chrY"] = base / "chrY.vcf.bgz"
    return out


def test_build_shard_plan_one_shard_per_canonical_chrom() -> None:
    """A purely-canonical input set produces N shards, no catch-all."""
    gmap = _dummy_gnomad_map()
    fallback = gmap["chr1"]
    input_chroms = ("chr1", "chr2", "chrX")

    plans, non_canonical = _build_shard_plan(
        input_chroms=input_chroms,
        gnomad_map=gmap,
        gnomad_fallback=fallback,
        input_shard_dir=Path("/scratch/in"),
        annotated_shard_dir=Path("/scratch/out"),
    )

    assert non_canonical == []
    assert len(plans) == 3
    assert [p.label for p in plans] == ["chr1", "chr2", "chrX"]
    assert [p.idx for p in plans] == [1, 2, 3]
    # Each canonical shard gets exactly its own region + matching gnomAD file.
    for plan, chrom in zip(plans, input_chroms, strict=True):
        assert plan.regions == (chrom,)
        assert plan.gnomad_source == gmap[chrom]


def test_build_shard_plan_groups_decoys_into_single_catch_all_shard() -> None:
    """Non-canonical contigs (decoys / alts / unplaced) all land in ONE catch-all shard."""
    gmap = _dummy_gnomad_map()
    fallback = gmap["chr1"]
    input_chroms = (
        "chr1",
        "chr22",
        "chrX",
        "chrUn_KI270742v1",
        "chr1_KI270706v1_random",
        "chr11_KI270721v1_random",
        "chrEBV",
        "chrUn_JTFH01001998v1_decoy",
    )

    plans, non_canonical = _build_shard_plan(
        input_chroms=input_chroms,
        gnomad_map=gmap,
        gnomad_fallback=fallback,
        input_shard_dir=Path("/scratch/in"),
        annotated_shard_dir=Path("/scratch/out"),
    )

    # 3 canonical + 1 catch-all = 4 total, regardless of the 5 non-canonicals.
    assert len(plans) == 4
    assert [p.label for p in plans[:3]] == ["chr1", "chr22", "chrX"]
    catch_all = plans[3]
    assert catch_all.label == "non-canonical"
    assert catch_all.idx == 4
    # Catch-all carries every non-canonical contig in input order.
    assert catch_all.regions == (
        "chrUn_KI270742v1",
        "chr1_KI270706v1_random",
        "chr11_KI270721v1_random",
        "chrEBV",
        "chrUn_JTFH01001998v1_decoy",
    )
    # Catch-all uses the gnomAD fallback because no decoy has its own file.
    assert catch_all.gnomad_source == fallback
    # ``non_canonical`` mirrors the catch-all's region set.
    assert non_canonical == list(catch_all.regions)


def test_build_shard_plan_no_catch_all_when_only_canonical_present() -> None:
    """An input set entirely within the canonical chrom set skips the catch-all entirely."""
    gmap = _dummy_gnomad_map()
    fallback = gmap["chr1"]
    input_chroms = tuple(sorted(_CANONICAL_GRCH38_CHROMS))

    plans, non_canonical = _build_shard_plan(
        input_chroms=input_chroms,
        gnomad_map=gmap,
        gnomad_fallback=fallback,
        input_shard_dir=Path("/scratch/in"),
        annotated_shard_dir=Path("/scratch/out"),
    )

    assert non_canonical == []
    # 22 autosomes + chrX + chrY + chrM = 25 canonical chroms.
    assert len(plans) == 25
    # chrM has no gnomAD-exomes counterpart; the planner routes it to
    # the fallback file rather than spinning a separate catch-all for it.
    chrm_plan = next(p for p in plans if p.label == "chrM")
    assert chrm_plan.regions == ("chrM",)
    assert chrm_plan.gnomad_source == fallback


def test_format_regions_file_uses_tab_delimited_three_column_layout() -> None:
    """Regions file must be 3-column tab-delimited (CHROM\\tBEG\\tEND).

    Regression: a 1-column "just chrom names" file is rejected by
    bcftools with ``bcf_sr_regions_init: Could not parse line, using
    columns 1,2[,-1]``. Verified empirically against the project owner's
    Nebula VCF (2026-05-12); reproduced before this fix, fixed by
    emitting 3-column BED-style content with a 1 Gb END that covers any
    GRCh38 contig in full.
    """
    rendered = _format_regions_file(("chrUn_KI270742v1", "chrEBV"))
    lines = rendered.splitlines()
    assert lines == [
        "chrUn_KI270742v1\t1\t1000000000",
        "chrEBV\t1\t1000000000",
    ]
    # Trailing newline so concat-style consumers don't drop the last row.
    assert rendered.endswith("\n")
    # Every line has exactly 3 tab-separated columns; the END value is
    # parseable as a positive integer well inside int32 (max 2^31-1 =
    # 2147483647), so htslib's tabix layer never overflows.
    for line in lines:
        cols = line.split("\t")
        assert len(cols) == 3, f"expected 3 tab-separated columns; got {len(cols)}: {line!r}"
        assert cols[1] == "1"
        end = int(cols[2])
        assert 0 < end < 2**31, f"END {end} must be a positive int32"


def test_persistent_cache_key_is_deterministic_and_16_hex_chars() -> None:
    """Same (source_sha, rename_map) → same key, every call."""
    key1 = _persistent_cache_key("abc123", "NC_000001.11\tchr1\n")
    key2 = _persistent_cache_key("abc123", "NC_000001.11\tchr1\n")
    assert key1 == key2
    assert len(key1) == 16
    # Hex characters only — directory name safety.
    assert all(c in "0123456789abcdef" for c in key1)


def test_persistent_cache_key_changes_when_source_sha_changes() -> None:
    """A re-fetched dbSNP file (different sha) produces a fresh cache slot.

    This is the cache-invalidation guarantee: if the user re-fetches
    dbSNP and gets different bytes, the orchestrator must NOT silently
    reuse the prior renamed file (which was generated from a different
    upstream version).
    """
    key_v1 = _persistent_cache_key("sha-of-old-fetch", _DBSNP_REFSEQ_TO_UCSC_MAP)
    key_v2 = _persistent_cache_key("sha-of-new-fetch", _DBSNP_REFSEQ_TO_UCSC_MAP)
    assert key_v1 != key_v2


def test_persistent_cache_key_changes_when_rename_map_changes() -> None:
    """Editing _DBSNP_REFSEQ_TO_UCSC_MAP invalidates the cache.

    The renamed dbSNP file's CHROM column reflects whatever rename map
    was active at staging time. Changing the map without changing the
    key would silently serve a file with wrong CHROM values for the
    new map — exactly the silent-staleness failure mode caching must
    guard against.
    """
    key_old = _persistent_cache_key("sha-fixed", "NC_000001.11\tchr1\n")
    key_new = _persistent_cache_key(
        "sha-fixed", "NC_000001.11\tchr1\nNC_000002.12\tchr2\n"
    )
    assert key_old != key_new


def test_build_shard_plan_preserves_input_order_within_canonicals() -> None:
    """Canonical-chrom shards land in the order they appear in input_chroms."""
    gmap = _dummy_gnomad_map()
    fallback = gmap["chr1"]
    # Deliberately scrambled — vcfanno + bcftools concat both expect
    # coordinate-sorted shards downstream, but that's a property of the
    # input VCF's tabix index, not of the planner. Verify the planner
    # itself is a transparent pass-through.
    input_chroms = ("chr3", "chr1", "chrX", "chr2")

    plans, _ = _build_shard_plan(
        input_chroms=input_chroms,
        gnomad_map=gmap,
        gnomad_fallback=fallback,
        input_shard_dir=Path("/scratch/in"),
        annotated_shard_dir=Path("/scratch/out"),
    )
    assert [p.label for p in plans] == ["chr3", "chr1", "chrX", "chr2"]

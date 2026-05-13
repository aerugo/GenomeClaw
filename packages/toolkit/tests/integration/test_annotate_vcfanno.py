"""Phase 4C.2 — ``annotate_vcfanno`` orchestrator integration tests.

Covers test cases 10–17 from
``docs/plans/active/mvp/phases/phase-4.md`` Step 4C.1.

``annotate_vcfanno(run_dir, reference_dir, ...)`` reads
``run_dir/normalized.vcf.gz`` (from a prior ``normalize`` step),
resolves ClinVar / gnomAD-exomes / dbSNP under ``reference_dir/``,
stages each source into ``_scratch/`` with chr-prefix alignment as
needed, builds a vcfanno TOML config, runs ``vcfanno``, and
``atomic_promote``s the result into ``run_dir/vcfanno.vcf.gz``.

Output INFO fields:
- ``clinvar_classification``, ``clinvar_review_status`` (from ClinVar's CLNSIG / CLNREVSTAT)
- ``gnomad_af_popmax``, ``gnomad_af_popmax_pop``, ``gnomad_af_{afr,amr,eas,nfe,sas}`` (from gnomAD)
- ``dbsnp_rsid`` (from dbSNP's RS)

All cases are ``needs_bio`` — they require ``vcfanno`` + ``bcftools``
on PATH (the toolkit image; not the host venv).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bgz_index(plain: Path) -> Path:
    """bgzip + tabix-index a plain VCF; return path to the .vcf.gz."""
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


def _build_clinvar_release(reference_dir: Path, release: str, *, chr_prefixed: bool) -> Path:
    """Stage a tiny ClinVar release. ``chr_prefixed`` switches between the
    real-NCBI shape (numeric contigs ``1`` / ``17``) and the chr-prefixed
    shape ``chr1`` / ``chr17`` that consumer VCFs use. The orchestrator's
    chr-prefix-alignment step renames numeric → chr-prefixed at staging.
    """
    target = reference_dir / "clinvar" / release
    target.mkdir(parents=True)
    plain = target / "clinvar.vcf"
    prefix = "chr" if chr_prefixed else ""
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=CLNSIG,Number=.,Type=String,Description="Clinical significance">\n'
        '##INFO=<ID=CLNREVSTAT,Number=.,Type=String,Description="Review status">\n'
        f"##contig=<ID={prefix}1,length=248956422>\n"
        f"##contig=<ID={prefix}17,length=83257441>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"{prefix}1\t1000\t111\tA\tG\t.\t.\tCLNSIG=Pathogenic;CLNREVSTAT=criteria_provided\n"
        f"{prefix}17\t43044295\t222\tG\tA\t.\t.\tCLNSIG=Likely_benign;CLNREVSTAT=no_assertion\n"
    )
    return _bgz_index(plain)


def _build_gnomad_exomes_release(reference_dir: Path, release: str) -> None:
    """Stage a minimal gnomAD-exomes per-chrom layout (chr1 + chr17 only).

    The fixture's contigs are chr-prefixed (matches the consumer VCF; no
    chr-prefix rename needed for gnomAD in v0). INFO fields use the
    canonical gnomAD v4 exomes-only names: ``AF_grpmax`` (popmax AF),
    ``grpmax`` (popmax population), and per-population ``AF_<pop>``.
    Verified 2026-05-11 against the public gnomAD chr22 sites VCF.
    """
    target = reference_dir / "gnomad-exomes" / release / "by_chrom"
    target.mkdir(parents=True)
    for chrom, pos in (("chr1", 1000), ("chr17", 43044295)):
        plain = target / f"{chrom}.vcf"
        plain.write_text(
            "##fileformat=VCFv4.2\n"
            '##INFO=<ID=AF_grpmax,Number=A,Type=Float,Description="Popmax AF">\n'
            '##INFO=<ID=grpmax,Number=A,Type=String,Description="Popmax population">\n'
            '##INFO=<ID=AF_afr,Number=A,Type=Float,Description="AF in afr">\n'
            '##INFO=<ID=AF_amr,Number=A,Type=Float,Description="AF in amr">\n'
            '##INFO=<ID=AF_eas,Number=A,Type=Float,Description="AF in eas">\n'
            '##INFO=<ID=AF_nfe,Number=A,Type=Float,Description="AF in nfe">\n'
            '##INFO=<ID=AF_sas,Number=A,Type=Float,Description="AF in sas">\n'
            f"##contig=<ID={chrom},length=248956422>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            f"{chrom}\t{pos}\t.\tA\tG\t.\t.\t"
            "AF_grpmax=0.0123;grpmax=nfe;"
            "AF_afr=0.001;AF_amr=0.005;AF_eas=0.0001;AF_nfe=0.0123;AF_sas=0.003\n"
        )
        bgz = _bgz_index(plain)
        # Rename .vcf.gz → .vcf.bgz to match production gnomAD layout.
        bgz.rename(target / f"{chrom}.vcf.bgz")
        # Tabix index file is regenerated; bcftools indexes <bgz>.tbi
        # but our rename leaves the .tbi alongside the .vcf.gz path.
        # Move it too.
        old_tbi = target / f"{chrom}.vcf.gz.tbi"
        if old_tbi.exists():
            old_tbi.rename(target / f"{chrom}.vcf.bgz.tbi")


def _build_dbsnp_release(reference_dir: Path, release: str) -> Path:
    """Stage a tiny dbSNP release (single file, chr-prefixed contigs)."""
    target = reference_dir / "dbsnp" / release
    target.mkdir(parents=True)
    plain = target / "dbsnp.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=RS,Number=1,Type=String,Description="dbSNP rsid">\n'
        "##contig=<ID=chr1,length=248956422>\n"
        "##contig=<ID=chr17,length=83257441>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\trs1\tA\tG\t.\t.\tRS=rs1\n"
        "chr17\t43044295\trs28897672\tG\tA\t.\t.\tRS=rs28897672\n"
    )
    return _bgz_index(plain)


def _stage_full_reference(reference_dir: Path) -> None:
    """Stage one release of each Phase-4C source under ``reference_dir/``."""
    _build_clinvar_release(reference_dir, "2026-05-09", chr_prefixed=True)
    _build_gnomad_exomes_release(reference_dir, "v4.1")
    _build_dbsnp_release(reference_dir, "b157")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_annotate_vcfanno_writes_annotated_vcf_in_run_dir(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 10: happy path — `annotate_vcfanno(run_dir)` produces ``vcfanno.vcf.gz`` + ``.tbi``."""
    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-001",
    )
    normalize(run_dir=run_dir)
    out = annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    assert out == run_dir / "vcfanno.vcf.gz"
    assert out.exists()
    assert (run_dir / "vcfanno.vcf.gz.tbi").exists()


@pytest.mark.needs_bio
def test_annotate_vcfanno_overlays_all_three_sources(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Cases 11+12+13: ClinVar / gnomAD / dbSNP INFO fields all present on matching variants.

    The fixture's chr1:1000 variant is covered by all three sources;
    the output INFO must carry every renamed field.
    """
    import gzip

    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-001",
    )
    normalize(run_dir=run_dir)
    out = annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    with gzip.open(out, "rt") as fh:
        text = fh.read()
    # The chr1:1000 record's INFO column should carry all three sources' fields.
    chr1_lines = [ln for ln in text.splitlines() if ln.startswith("chr1\t1000\t")]
    assert len(chr1_lines) == 1, f"expected one chr1:1000 record, got {len(chr1_lines)}"
    info = chr1_lines[0].split("\t")[7]
    assert "clinvar_classification=Pathogenic" in info, info
    assert "gnomad_af_popmax=" in info, info
    assert "gnomad_af_popmax_pop=" in info, info
    assert "dbsnp_rsid=rs1" in info, info


@pytest.mark.needs_bio
def test_annotate_vcfanno_chr_prefix_alignment_against_numeric_clinvar(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 14: ClinVar with numeric (real-NCBI) contigs is renamed at staging time.

    Without the rename, chr-prefix mismatch between the consumer VCF
    (``chr1``) and ClinVar (``1``) yields zero overlap. The
    orchestrator's chr-prefix-alignment step normalises ClinVar's
    staged copy to chr-prefixed contigs; the user's normalized VCF
    stays canonical.
    """
    import gzip

    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    # Numeric (NCBI-shaped) ClinVar contigs. The orchestrator handles
    # the rename internally.
    _build_clinvar_release(genomeclaw_layout["reference"], "2026-05-09", chr_prefixed=False)
    _build_gnomad_exomes_release(genomeclaw_layout["reference"], "v4.1")
    _build_dbsnp_release(genomeclaw_layout["reference"], "b157")

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-001",
    )
    normalize(run_dir=run_dir)
    out = annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    with gzip.open(out, "rt") as fh:
        text = fh.read()
    chr1_lines = [ln for ln in text.splitlines() if ln.startswith("chr1\t1000\t")]
    assert len(chr1_lines) == 1
    info = chr1_lines[0].split("\t")[7]
    # The clinvar_classification only appears if chr-prefix alignment worked.
    assert "clinvar_classification=Pathogenic" in info, info


@pytest.mark.needs_bio
def test_invR001_annotate_vcfanno_appends_step_to_provenance(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 15: provenance.json gains a ``vcfanno`` step with tool version
    + every overlay source's path + sha256 + the inline TOML config.
    """
    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-001",
    )
    normalize(run_dir=run_dir)
    annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    provenance = json.loads((run_dir / "provenance.json").read_text())
    vcfanno_step = next((s for s in provenance["steps"] if s["step"] == "vcfanno"), None)
    assert vcfanno_step is not None, provenance["steps"]
    assert vcfanno_step["tool"] == "vcfanno"
    assert vcfanno_step["tool_version"]
    # Inputs: normalized VCF + each overlay source.
    input_paths = {i["path"] for i in vcfanno_step["inputs"]}
    assert any("normalized.vcf.gz" in p for p in input_paths)
    assert any("clinvar" in p for p in input_paths)
    assert any("gnomad-exomes" in p for p in input_paths)
    assert any("dbsnp" in p for p in input_paths)
    # The inline TOML config is captured in params.config for rebuildability.
    assert "[[annotation]]" in vcfanno_step["params"].get("config", "")


@pytest.mark.needs_bio
def test_invD001_annotate_vcfanno_does_not_mutate_reference_files(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 16 (`INV-D001`): every overlay source's SHA256 is byte-identical post-run."""
    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    # Capture SHA256s of every reference file before the run.
    ref = genomeclaw_layout["reference"]
    sources = [
        ref / "clinvar" / "2026-05-09" / "clinvar.vcf.gz",
        ref / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr1.vcf.bgz",
        ref / "gnomad-exomes" / "v4.1" / "by_chrom" / "chr17.vcf.bgz",
        ref / "dbsnp" / "b157" / "dbsnp.vcf.gz",
    ]
    pre = {p: _sha256(p) for p in sources}

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-001",
    )
    normalize(run_dir=run_dir)
    annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    for p, before in pre.items():
        assert _sha256(p) == before, f"INV-D001 violation: {p} mutated by annotate_vcfanno"


@pytest.mark.needs_bio
def test_annotate_vcfanno_caches_renamed_dbsnp_across_runs(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Second annotate run reuses the cached renamed dbSNP from the first.

    The dbSNP rename is the dominant cost of the annotate phase
    (~15-30 min single-threaded on real data). Caching the output
    keyed on (source_sha + rename_map) means iterative pipeline
    development pays the rename cost once and reuses across runs. This
    test exercises the cache by running annotate twice against the
    same reference layout and asserting:

    1. The cache directory + cached file appear after the first run.
    2. The second run reuses the cached file (its mtime is unchanged).
    3. Both runs produce structurally-equivalent vcfanno outputs
       (same dbsnp_rsid annotations on the common variants).
    """
    import gzip

    from genomeclaw_toolkit.prep.annotate_vcfanno import (
        _DBSNP_REFSEQ_TO_UCSC_MAP,
        _PERSISTENT_CACHE_SUBDIR,
        _persistent_cache_key,
        annotate_vcfanno,
    )
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    # ----- Run 1: cache miss → builds the cached entry -----
    run_dir_1 = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-cache-1",
    )
    normalize(run_dir=run_dir_1)
    out_1 = annotate_vcfanno(
        run_dir=run_dir_1,
        reference_dir=genomeclaw_layout["reference"],
    )
    assert out_1.exists()

    # Locate the cached dbSNP entry: keyed on the source file's sha256
    # + the rename-map text. The genomeclaw_layout fixture lays scratch
    # at <tmp>/scratch (sibling of derived/).
    dbsnp_source = genomeclaw_layout["reference"] / "dbsnp" / "b157" / "dbsnp.vcf.gz"
    source_sha = _sha256(dbsnp_source)
    key = _persistent_cache_key(source_sha, _DBSNP_REFSEQ_TO_UCSC_MAP)
    cache_dir = (
        genomeclaw_layout["derived"].parent / "scratch" / _PERSISTENT_CACHE_SUBDIR / "dbsnp" / key
    )
    cached_vcf = cache_dir / "dbsnp.ucsc.vcf.gz"
    cached_tbi = cache_dir / "dbsnp.ucsc.vcf.gz.tbi"
    assert cached_vcf.exists(), f"cache miss should have built {cached_vcf}"
    assert cached_tbi.exists()
    first_mtime = cached_vcf.stat().st_mtime_ns

    # ----- Run 2: cache hit → reuses the entry (mtime unchanged) -----
    run_dir_2 = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-cache-2",
    )
    normalize(run_dir=run_dir_2)
    out_2 = annotate_vcfanno(
        run_dir=run_dir_2,
        reference_dir=genomeclaw_layout["reference"],
    )
    assert out_2.exists()
    second_mtime = cached_vcf.stat().st_mtime_ns
    assert second_mtime == first_mtime, (
        "cached dbsnp file mtime changed between runs — the cache wasn't reused"
    )

    # Both annotate outputs should carry the same dbsnp_rsid for the
    # shared chr1:1000 variant — the cache hit must produce the same
    # annotations as the cache miss.
    def _dbsnp_rsid_at_chr1_1000(vcf: Path) -> str | None:
        with gzip.open(vcf, "rt") as fh:
            for line in fh:
                if line.startswith("chr1\t1000\t"):
                    info = line.split("\t")[7]
                    for entry in info.split(";"):
                        if entry.startswith("dbsnp_rsid="):
                            return entry.split("=", 1)[1]
        return None

    assert _dbsnp_rsid_at_chr1_1000(out_1) == _dbsnp_rsid_at_chr1_1000(out_2)


@pytest.mark.needs_bio
def test_annotate_vcfanno_refuses_when_normalized_vcf_missing(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``annotate_vcfanno`` requires a prior ``normalize`` step."""
    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="vcfanno-001",
    )
    with pytest.raises(FileNotFoundError, match="normalized"):
        annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

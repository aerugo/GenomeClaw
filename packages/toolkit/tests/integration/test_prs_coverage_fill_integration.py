"""Phase 1 RED — integration tests for Tier 1 force-genotyping with subprocess stubs.

Same pattern the existing ``test_pgsc_calc_wrapper.py`` uses: stub ``subprocess.run``,
provide fixture output files, assert the wrapper's argv + post-processing behaviour.
This isolates the orchestration logic from the bcftools binary itself; the real-
bcftools path is exercised by ``test_prs_coverage_fill_bcftools.py`` (gated on
``needs_bio``).

Three contract assertions for ``_force_genotype_tier1``:

1. Argv shape — ``bcftools mpileup -R sites | bcftools call -C alleles -T alleles
   | bcftools norm`` against the user CRAM, with the right flags
   (``--max-depth 250 --min-BQ 20 --min-MQ 20``, ``--annotate FORMAT/DP,FORMAT/AD``,
   ``--multiallelic-caller --keep-alts --constrain alleles``, ``--multiallelics -any``).
2. Scratch-then-promote — output VCF is written to scratch first and
   ``atomic_promote``-d to ``derived/`` (``INV-D003``).
3. Provenance JSON — ``tier1.qc.json`` carries all required ``INV-R001`` keys.
"""

from __future__ import annotations

import gzip
import json
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _write_synthetic_tier1_vcf(path: Path, n_refref: int = 5, n_het: int = 2) -> None:
    """Write a tiny synthetic ``tier1.vcf.gz`` to ``path``.

    Used as the side-effect of the ``subprocess.run`` stub so the wrapper's
    QC-summary pass has something realistic to walk.
    """
    lines = [
        "##fileformat=VCFv4.2",
        "##contig=<ID=chr22,length=50818468>",
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="genotype">',
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="depth">',
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tMPNRGLQ2K",
    ]
    pos = 10001
    for _ in range(n_refref):
        lines.append(f"chr22\t{pos}\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/0:30")
        pos += 1
    for _ in range(n_het):
        lines.append(f"chr22\t{pos}\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:28")
        pos += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    # tabix index sidecar (presence-only, contents don't matter for the stub)
    (path.parent / (path.name + ".tbi")).write_bytes(b"")


# Regex for the wrapper's `bcftools norm ... --output <path>` flag inside the
# shell-glued bash pipe. The synthesised path lives wherever the wrapper
# staged it (typically a shard_scratch dir); the fake materialises a
# synthetic VCF there so the wrapper's downstream atomic_promote + QC walk
# have something to consume.
_NORM_OUTPUT_RE = re.compile(r"bcftools norm[^|&]*?--output\s+(\S+)")


def _bcftools_run_fake() -> MagicMock:
    """Build a ``subprocess.run`` fake that parses the bcftools pipe argv to find
    the staging path the wrapper chose, then writes the synthetic VCF there.

    Decouples the test from "where does the wrapper stage things" — the
    fake follows whatever path appears in the wrapper's argv. Works with
    or without shard_scratch.
    """

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_str = " ".join(str(x) for x in cmd)
        match = _NORM_OUTPUT_RE.search(cmd_str)
        if match:
            out_path = Path(match.group(1))
            _write_synthetic_tier1_vcf(out_path)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return MagicMock(side_effect=_runner)


@pytest.fixture
def synthetic_panel_tsvs(tmp_path: Path) -> dict[str, Path]:
    """Stage a plaintext sites + alleles TSV pair under ``tmp_path/pca/``.

    Filename layout matches ``_materialize_pca_sites`` output so the
    integration test can plug straight in. Plaintext (not bgzip) keeps the
    materialize step subprocess-free past plink2 — bcftools
    ``--regions-file`` / ``--targets-file`` accept plaintext TSVs at the
    sub-10 MB scale this set lives at.
    """
    pca = tmp_path / "pca"
    pca.mkdir()
    sites = pca / "pca_sites.tsv"
    alleles = pca / "pca_alleles.tsv"
    # Presence-only — the bcftools binary is stubbed, so contents aren't parsed.
    sites.write_text("")
    alleles.write_text("")
    return {"sites": sites, "alleles": alleles}


@pytest.fixture
def synthetic_cram(tmp_path: Path) -> Path:
    """A placeholder CRAM + .crai pair (presence-only; bcftools binary is stubbed)."""
    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"\x43\x52\x41\x4d")  # "CRAM" magic, presence-only
    (raw / "MPNRGLQ2K.cram.crai").write_bytes(b"")
    return cram


@pytest.fixture
def synthetic_fasta(tmp_path: Path) -> Path:
    """A placeholder FASTA + .fai (presence-only)."""
    ref = tmp_path / "reference" / "grch38"
    ref.mkdir(parents=True)
    fasta = ref / "grch38.fa.gz"
    fasta.write_bytes(b"")
    (ref / "grch38.fa.gz.fai").write_bytes(b"")
    (ref / "grch38.fa.gz.gzi").write_bytes(b"")
    return fasta


def test_force_genotype_tier1_refuses_to_cache_empty_vcf(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """Tier 1 MUST raise ``BcftoolsError`` if the bcftools pipe produces
    a header-only VCF (0 records), instead of silently promoting it.

    Phase 7 smoke v15 regression guard: the original Tier 2 ran with
    bcftools exiting 0 but producing only headers; the wrapper happily
    cached the empty result and every subsequent smoke iteration
    inherited it. The actual symptom (pgsc_calc match-rate 2.9%)
    surfaced 4 layers downstream. Same class of failure could affect
    Tier 1 — guard applies there too defensively.

    Verifies the guard text names the actionable diagnostic categories
    (chr-prefix mismatch, build mismatch, etc.)."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        BcftoolsError,
        _force_genotype_tier1,
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

    output_vcf = tmp_path / "derived" / "tier1.vcf.gz"
    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run",
        MagicMock(side_effect=_empty_runner),
    ):
        with pytest.raises(BcftoolsError) as exc_info:
            _force_genotype_tier1(
                cram_path=synthetic_cram,
                sites_tsv=synthetic_panel_tsvs["sites"],
                alleles_tsv=synthetic_panel_tsvs["alleles"],
                fasta=synthetic_fasta,
                output_vcf=output_vcf,
            )

    msg = str(exc_info.value)
    assert "ZERO output records" in msg, msg
    assert "chr" in msg.lower(), f"diagnostic must mention chromosome prefix mismatch; got: {msg}"
    assert "NOT caching" in msg, msg

    # And critically: the output_vcf MUST NOT exist on disk (no promote).
    assert not output_vcf.exists(), (
        f"empty tier1 VCF must NOT be cached; found at {output_vcf}"
    )


def test_force_genotype_tier1_invokes_correct_bcftools_pipe(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """The wrapper shells out the documented mpileup→call→norm pipe with the right flags."""
    from genomeclaw_toolkit.prep.coverage_fill import _force_genotype_tier1

    output_vcf = tmp_path / "derived" / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
    fake_run = _bcftools_run_fake()

    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_run):
        _force_genotype_tier1(
            cram_path=synthetic_cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            output_vcf=output_vcf,
        )

    # The pipe is a single shell-glued invocation; flatten all argv strings
    # to one big haystack and probe the canonical flag set.
    all_calls = [" ".join(str(x) for x in call.args[0]) for call in fake_run.call_args_list]
    haystack = "\n".join(all_calls)

    assert "bcftools mpileup" in haystack
    assert "bcftools call" in haystack
    assert "bcftools norm" in haystack
    assert "--max-depth 250" in haystack
    assert "--min-BQ 20" in haystack
    assert "--min-MQ 20" in haystack
    assert "FORMAT/DP,FORMAT/AD" in haystack
    assert "--multiallelic-caller" in haystack
    assert "--keep-alts" in haystack
    assert "--constrain alleles" in haystack
    assert "--multiallelics -any" in haystack
    # The targets/regions files are the synthetic TSVs (panel→CRAM rewrite happened upstream).
    assert str(synthetic_panel_tsvs["sites"]) in haystack
    assert str(synthetic_panel_tsvs["alleles"]) in haystack
    assert str(synthetic_cram) in haystack


def test_force_genotype_tier1_writes_to_scratch_first_then_promotes(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_cram: Path,
    synthetic_fasta: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INV-D003 — scratch sharding + ``atomic_promote`` discipline.

    The wrapper writes its in-flight tier1.vcf.gz under
    ``ephemeral_scratch_base()`` and ``atomic_promote``-s it to the
    destination under ``derived/``. A spy on ``atomic_promote`` records
    the source path and confirms it's a scratch path, not a derived path.
    """
    from genomeclaw_toolkit.prep import coverage_fill

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("GENOMECLAW_EPHEMERAL_SCRATCH_DIR", str(scratch))

    output_vcf = tmp_path / "derived" / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"

    promote_calls: list[tuple[Path, Path]] = []
    real_promote = coverage_fill.atomic_promote

    def _spy_promote(src: Path, dst: Path) -> None:
        promote_calls.append((Path(src), Path(dst)))
        real_promote(src, dst)

    with (
        patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", _bcftools_run_fake()),
        patch("genomeclaw_toolkit.prep.coverage_fill.atomic_promote", side_effect=_spy_promote),
    ):
        coverage_fill._force_genotype_tier1(
            cram_path=synthetic_cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            output_vcf=output_vcf,
        )

    # At least one promote happened; the VCF promote (first call) goes from
    # scratch to the user-supplied output_vcf path. A sidecar ``.tbi``
    # promote may also be recorded after it; both must originate under
    # scratch (INV-D003), but only the VCF promote lands at output_vcf
    # itself (the .tbi promote lands at output_vcf + ".tbi").
    assert promote_calls, "atomic_promote was never called"
    vcf_src, vcf_dst = promote_calls[0]
    assert scratch in vcf_src.parents, (
        f"INV-D003: expected promote src under {scratch}, got {vcf_src} "
        f"(parents: {list(vcf_src.parents)})"
    )
    assert vcf_dst == output_vcf
    # Every recorded promote must originate under scratch — no path leaks
    # promote-from-derived back into derived.
    for src, _ in promote_calls:
        assert scratch in src.parents, (
            f"INV-D003 leak: promote src {src} is not under scratch {scratch}"
        )


def test_force_genotype_tier1_does_not_mutate_cram(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """INV-D001 — the CRAM is read-only; SHA256 + mtime unchanged after a run."""
    import hashlib

    from genomeclaw_toolkit.prep.coverage_fill import _force_genotype_tier1

    sha_before = hashlib.sha256(synthetic_cram.read_bytes()).hexdigest()
    mtime_before = synthetic_cram.stat().st_mtime

    output_vcf = tmp_path / "derived" / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
    fake_run = _bcftools_run_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_run):
        _force_genotype_tier1(
            cram_path=synthetic_cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            output_vcf=output_vcf,
        )

    sha_after = hashlib.sha256(synthetic_cram.read_bytes()).hexdigest()
    assert sha_after == sha_before, "INV-D001: tier1 must not mutate the source CRAM"
    assert synthetic_cram.stat().st_mtime == mtime_before


def test_tier1_qc_json_has_required_invR001_fields(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """tier1.qc.json carries all keys ``INV-R001`` rebuilds need.

    Required keys: source_cram_sha256, panel_version, bcftools_version,
    tool_command, total_records, gt_distribution, mean_dp, missing_rate,
    per_chrom_record_counts, created_at, schema_version.
    """
    from genomeclaw_toolkit.prep.coverage_fill import prepare_coverage_tier1

    output_vcf = tmp_path / "derived" / "prs_coverage" / "MPNRGLQ2K" / "v1" / "tier1.vcf.gz"
    output_qc = output_vcf.parent / "tier1.qc.json"
    fake_run = _bcftools_run_fake()

    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_run):
        prepare_coverage_tier1(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )

    qc = json.loads(output_qc.read_text())
    required = {
        "sample_id",
        "source_cram_path",
        "source_cram_sha256",
        "panel_version",
        "bcftools_version",
        "tool_command",
        "total_records",
        "gt_distribution",
        "mean_dp",
        "missing_rate",
        "per_chrom_record_counts",
        "created_at",
        "schema_version",
    }
    missing = required - set(qc)
    assert not missing, f"INV-R001 fields missing from tier1.qc.json: {sorted(missing)}"
    assert qc["sample_id"] == "MPNRGLQ2K"
    assert qc["panel_version"] == "v1"
    # The hash is computed by the wrapper from the synthetic CRAM contents.
    import hashlib as _hashlib

    assert qc["source_cram_sha256"] == _hashlib.sha256(synthetic_cram.read_bytes()).hexdigest()


def test_prepare_coverage_tier1_is_idempotent(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_cram: Path,
    synthetic_fasta: Path,
) -> None:
    """Second invocation against an already-built tier1 cache short-circuits.

    Cache-hit semantics: the wrapper detects the existing tier1.vcf.gz +
    tier1.qc.json + matching source_cram_sha256, and returns without
    re-shelling-out to bcftools.
    """
    from genomeclaw_toolkit.prep.coverage_fill import prepare_coverage_tier1

    fake_run_1 = _bcftools_run_fake()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_run_1):
        prepare_coverage_tier1(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )
    assert fake_run_1.call_count >= 1, "first call must shell out to bcftools"

    fake_run_2 = MagicMock()
    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake_run_2):
        prepare_coverage_tier1(
            sample_id="MPNRGLQ2K",
            cram_path=synthetic_cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            panel_version="v1",
            output_root=tmp_path / "derived",
        )
    assert fake_run_2.call_count == 0, (
        "second call against a warm cache must not shell out to bcftools"
    )


def test_force_genotype_tier1_raises_on_missing_cram_index(
    tmp_path: Path,
    synthetic_panel_tsvs: dict[str, Path],
    synthetic_fasta: Path,
) -> None:
    """Missing .crai → typed ``MissingCramIndexError`` with an actionable hint."""
    from genomeclaw_toolkit.prep.coverage_fill import (
        MissingCramIndexError,
        _force_genotype_tier1,
    )

    raw = tmp_path / "raw" / "MPNRGLQ2K"
    raw.mkdir(parents=True)
    cram = raw / "MPNRGLQ2K.cram"
    cram.write_bytes(b"CRAM")
    # NB: no .crai sidecar.

    output_vcf = tmp_path / "derived" / "tier1.vcf.gz"

    with pytest.raises(MissingCramIndexError) as excinfo:
        _force_genotype_tier1(
            cram_path=cram,
            sites_tsv=synthetic_panel_tsvs["sites"],
            alleles_tsv=synthetic_panel_tsvs["alleles"],
            fasta=synthetic_fasta,
            output_vcf=output_vcf,
        )
    assert "samtools index" in str(excinfo.value).lower()

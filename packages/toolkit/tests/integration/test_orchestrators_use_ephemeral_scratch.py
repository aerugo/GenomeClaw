"""Phase A — orchestrators route ``shard_scratch(...)`` to ephemeral scratch base.

The 2026-05-14 real-data smoke EBADF surfaced when vcfanno's internal
goroutines hammered a staged file on the virtiofs-backed
``/mnt/genomeclaw/scratch/`` mount under concurrent FD pressure. Phase A
of the [annotate-shard-resilience plan](../../../docs/plans/active/annotate-shard-resilience/development-plan.md)
splits scratch into two tiers:

- **Persistent scratch** (``/mnt/genomeclaw/scratch/_cache/``) — keeps
  the dbSNP rename cache + sha256 cache. Bind-mounted from the host;
  contents survive across runs. Stays where it is.
- **Ephemeral scratch** (``ephemeral_scratch_base()``) — per-step
  ``shard_scratch`` dirs. Routed to a container-local path
  (``/tmp/genomeclaw-scratch`` by default; overridable via
  ``GENOMECLAW_EPHEMERAL_SCRATCH_DIR``) so the heavy per-step
  intermediates never traverse virtiofs.

These tests pin the contract per orchestrator: ``shard_scratch(...)``
calls land under the ephemeral base, while ``_cache/`` lookups still
resolve via the persistent base. Without this split, the EBADF tripwire
keeps firing under load.

The tests are needs_bio because each runs the full pipeline up to the
orchestrator under test. ``materialize`` is host-runnable (no bcftools)
so its test omits the marker.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _bgz_index(plain: Path) -> Path:
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


def _build_clinvar_release(reference_dir: Path, release: str) -> Path:
    target = reference_dir / "clinvar" / release
    target.mkdir(parents=True)
    plain = target / "clinvar.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=CLNSIG,Number=.,Type=String,Description="Clinical significance">\n'
        '##INFO=<ID=CLNREVSTAT,Number=.,Type=String,Description="Review status">\n'
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\t111\tA\tG\t.\t.\tCLNSIG=Pathogenic;CLNREVSTAT=criteria_provided\n"
    )
    return _bgz_index(plain)


def _build_gnomad_release(reference_dir: Path, release: str) -> None:
    target = reference_dir / "gnomad-exomes" / release / "by_chrom"
    target.mkdir(parents=True)
    plain = target / "chr1.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=AF_grpmax,Number=A,Type=Float,Description="Popmax AF">\n'
        '##INFO=<ID=grpmax,Number=A,Type=String,Description="Popmax population">\n'
        '##INFO=<ID=AF_afr,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_amr,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_asj,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_eas,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_fin,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_mid,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_nfe,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_remaining,Number=A,Type=Float,Description="AF">\n'
        '##INFO=<ID=AF_sas,Number=A,Type=Float,Description="AF">\n'
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\t.\tA\tG\t.\t.\t"
        "AF_grpmax=0.01;grpmax=nfe;AF_afr=0.001;AF_amr=0.005;"
        "AF_asj=0.002;AF_eas=0.0001;AF_fin=0.011;AF_mid=0.007;"
        "AF_nfe=0.01;AF_remaining=0.004;AF_sas=0.003\n"
    )
    bgz = _bgz_index(plain)
    bgz.rename(target / "chr1.vcf.bgz")
    old_tbi = target / "chr1.vcf.gz.tbi"
    if old_tbi.exists():
        old_tbi.rename(target / "chr1.vcf.bgz.tbi")


def _build_dbsnp_release(reference_dir: Path, release: str) -> Path:
    target = reference_dir / "dbsnp" / release
    target.mkdir(parents=True)
    plain = target / "dbsnp.vcf"
    plain.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=RS,Number=1,Type=String,Description="dbSNP rsid">\n'
        "##contig=<ID=chr1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\trs1\tA\tG\t.\t.\tRS=rs1\n"
    )
    return _bgz_index(plain)


def _stage_full_reference(reference_dir: Path) -> None:
    _build_clinvar_release(reference_dir, "2026-05-09")
    _build_gnomad_release(reference_dir, "v4.1")
    _build_dbsnp_release(reference_dir, "b157")


# ---------------------------------------------------------------------------
# annotate_vcfanno
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_invD003_annotate_vcfanno_shard_scratch_lives_under_ephemeral_base(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``annotate_vcfanno`` writes its per-step shard_scratch dir under
    the ephemeral scratch base, not under the persistent ``scratch/``.

    Asserted by monkey-patching ``shard_scratch`` to record the ``base=``
    kwarg it's called with; verifying it matches ``ephemeral_scratch_base()``.
    """
    from genomeclaw_toolkit.prep import annotate_vcfanno as annotate_vcfanno_module
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base, shard_scratch

    _stage_full_reference(genomeclaw_layout["reference"])

    recorded_bases: list[Path] = []

    def _recording_shard_scratch(**kwargs):
        recorded_bases.append(kwargs["base"])
        return shard_scratch(**kwargs)

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ephem-vcfanno",
    )
    normalize(run_dir=run_dir)

    # Patch only the annotate_vcfanno module's shard_scratch ref so the
    # call we care about is the one we record. Other modules' scratch
    # use isn't relevant to this test.
    import pytest as _pytest  # local import for the monkeypatch context

    mp = _pytest.MonkeyPatch()
    try:
        mp.setattr(annotate_vcfanno_module, "shard_scratch", _recording_shard_scratch)
        annotate_vcfanno_module.annotate_vcfanno(
            run_dir=run_dir, reference_dir=genomeclaw_layout["reference"]
        )
    finally:
        mp.undo()

    expected_base = ephemeral_scratch_base()
    assert recorded_bases, "annotate_vcfanno didn't call shard_scratch at all"
    for base in recorded_bases:
        assert base == expected_base, (
            f"annotate_vcfanno's shard_scratch base={base} is not the ephemeral base "
            f"({expected_base}). EBADF tripwire risk."
        )


@pytest.mark.needs_bio
def test_annotate_vcfanno_persistent_dbsnp_cache_unchanged_by_split(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """The dbSNP rename cache still lives under ``<persistent>/_cache/dbsnp/``.

    Phase A's split must not move the persistent caches. They're large
    (~30 GB on real data), survive across runs, and need to be inspectable
    by the user — so they stay on the bind-mounted persistent scratch.
    """
    from genomeclaw_toolkit.prep.annotate_vcfanno import annotate_vcfanno
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    _stage_full_reference(genomeclaw_layout["reference"])

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ephem-dbsnp",
    )
    normalize(run_dir=run_dir)
    annotate_vcfanno(run_dir=run_dir, reference_dir=genomeclaw_layout["reference"])

    persistent = genomeclaw_layout["scratch"]
    cache_root = persistent / "_cache" / "dbsnp"
    assert cache_root.is_dir(), (
        f"persistent dbSNP cache expected under {persistent / '_cache' / 'dbsnp'} "
        "(the bind-mounted persistent scratch); Phase A must not have moved it"
    )


# ---------------------------------------------------------------------------
# annotate_vep
# ---------------------------------------------------------------------------


def test_invD003_annotate_vep_shard_scratch_lives_under_ephemeral_base(
    genomeclaw_layout: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``annotate_vep`` writes its per-step shard_scratch dir under the
    ephemeral base. VEP's intermediate VCF is the LARGEST single
    transient artifact in the pipeline (~10–15 GB on real data) and is
    exactly the kind of concurrent-write target that pressures virtiofs.

    Test runs host-only via the existing stub fixture from
    test_annotate_vep_invariants.py.
    """
    from genomeclaw_toolkit.prep import annotate_vep as annotate_vep_module
    from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER
    from genomeclaw_toolkit.prep._vep import VepConfig, VepRunStats
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base, shard_scratch

    # Stage just enough of a reference layout to satisfy annotate_vep's
    # resolvers. The vep_run + bcftools_index_tbi stubs handle the rest.
    reference_dir = genomeclaw_layout["reference"]
    (reference_dir / "vep_cache" / "114" / "homo_sapiens").mkdir(parents=True)
    (reference_dir / "vep_cache" / "114" / "homo_sapiens" / "info.txt").write_text("stub")
    grch38 = reference_dir / "grch38" / "ncbi-2014"
    grch38.mkdir(parents=True)
    (grch38 / "grch38.fa.gz").write_bytes(b"stub-fasta")
    (grch38 / "grch38.fa.gz.fai").write_bytes(b"stub-fai")
    (grch38 / "grch38.fa.gz.gzi").write_bytes(b"stub-gzi")

    run_dir = genomeclaw_layout["derived"] / "ephem-vep"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"sample_id": "ephem-vep", "outputs": {}}))
    (run_dir / "provenance.json").write_text(json.dumps({"steps": []}))
    (run_dir / "vcfanno.vcf.gz").write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)
    (run_dir / "vcfanno.vcf.gz.tbi").write_bytes(b"stub")

    recorded_bases: list[Path] = []

    def _recording_shard_scratch(**kwargs):
        recorded_bases.append(kwargs["base"])
        return shard_scratch(**kwargs)

    def _fake_vep_run(config: VepConfig) -> VepRunStats:
        config.output_vcf.parent.mkdir(parents=True, exist_ok=True)
        config.output_vcf.write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)
        return VepRunStats(skipped_variants=0, skipped_chroms={})

    def _fake_index_tbi(*, vcf: Path, derived_dir: Path) -> Path:  # noqa: ARG001
        tbi = vcf.with_suffix(vcf.suffix + ".tbi")
        tbi.write_bytes(b"stub")
        return tbi

    monkeypatch.setattr(annotate_vep_module, "shard_scratch", _recording_shard_scratch)
    monkeypatch.setattr(annotate_vep_module, "vep_run", _fake_vep_run)
    monkeypatch.setattr(annotate_vep_module, "vep_version", lambda: "stub")
    monkeypatch.setattr(annotate_vep_module, "bcftools_index_tbi", _fake_index_tbi)

    annotate_vep_module.annotate_vep(run_dir=run_dir, reference_dir=reference_dir)

    expected_base = ephemeral_scratch_base()
    assert recorded_bases, "annotate_vep didn't call shard_scratch at all"
    for base in recorded_bases:
        assert base == expected_base, (
            f"annotate_vep's shard_scratch base={base} is not the ephemeral base "
            f"({expected_base}). EBADF tripwire risk."
        )


# ---------------------------------------------------------------------------
# materialize
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_invD003_materialize_shard_scratch_lives_under_ephemeral_base(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """``materialize`` writes its per-step shard_scratch dir under the
    ephemeral base. Materialize's intermediate is small (DuckDB temp +
    staging CSV, < 1 GB) so it's not the primary virtiofs-pressure
    surface, but routing it consistently with the other orchestrators
    keeps the architecture predictable.
    """
    from genomeclaw_toolkit.prep import materialize as materialize_module
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base, shard_scratch

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="ephem-materialize",
    )
    normalize(run_dir=run_dir)

    recorded_bases: list[Path] = []

    def _recording_shard_scratch(**kwargs):
        recorded_bases.append(kwargs["base"])
        return shard_scratch(**kwargs)

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(materialize_module, "shard_scratch", _recording_shard_scratch)
        materialize_module.materialize(run_dir=run_dir)
    finally:
        mp.undo()

    expected_base = ephemeral_scratch_base()
    assert recorded_bases
    for base in recorded_bases:
        assert base == expected_base, (
            f"materialize's shard_scratch base={base} is not the ephemeral base ({expected_base})"
        )

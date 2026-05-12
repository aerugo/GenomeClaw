"""Unit coverage for the three new doctor collectors.

Each helper takes a host-side path and returns a structured record
classifying state at one altitude (reference data / raw sample / derived
pipeline runs). Tests stage synthetic fixtures under ``tmp_path`` so
they exercise the file-walking logic without needing real fetched data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# _collect_references
# ---------------------------------------------------------------------------


def _make_release_set(sources: list[dict]):
    """Build a ReleaseSet object without touching the bundled TOML files."""
    from genomeclaw_toolkit.prep.release_sets import ReleaseSet, ReleaseSetEntry

    entries = tuple(
        ReleaseSetEntry(
            source=s["source"],
            release=s["release"],
            chroms=tuple(s["chroms"]) if s.get("chroms") else None,
        )
        for s in sources
    )
    return ReleaseSet(name="test-set", description="synthetic", sources=entries)


def _touch(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_collect_references_all_present_returns_OK(tmp_path: Path) -> None:
    """A release dir with every expected file present → status='OK'."""
    from genomeclaw_toolkit.prep.doctor import _collect_references

    release_set = _make_release_set([{"source": "clinvar", "release": "2026-05-09"}])
    clinvar_dir = tmp_path / "clinvar" / "2026-05-09"
    _touch(clinvar_dir / "clinvar.vcf.gz")
    _touch(clinvar_dir / "clinvar.vcf.gz.md5")
    _touch(clinvar_dir / "clinvar.vcf.gz.tbi")

    states = _collect_references(reference_root=tmp_path, release_set=release_set)

    assert len(states) == 1
    assert states[0].source == "clinvar"
    assert states[0].status == "OK"
    assert states[0].missing_files == ()


def test_collect_references_release_dir_missing_returns_missing(tmp_path: Path) -> None:
    """No release dir at all → status='missing'."""
    from genomeclaw_toolkit.prep.doctor import _collect_references

    release_set = _make_release_set([{"source": "clinvar", "release": "2026-05-09"}])

    states = _collect_references(reference_root=tmp_path, release_set=release_set)

    assert states[0].status == "missing"
    # Caller knows what was expected even when nothing's there.
    assert states[0].expected_release == "2026-05-09"


def test_collect_references_partial_when_md5_sidecar_missing(tmp_path: Path) -> None:
    """Primary data file present, .md5 sidecar absent → status='partial'."""
    from genomeclaw_toolkit.prep.doctor import _collect_references

    release_set = _make_release_set([{"source": "clinvar", "release": "2026-05-09"}])
    clinvar_dir = tmp_path / "clinvar" / "2026-05-09"
    _touch(clinvar_dir / "clinvar.vcf.gz")
    _touch(clinvar_dir / "clinvar.vcf.gz.tbi")
    # md5 sidecar deliberately absent.

    states = _collect_references(reference_root=tmp_path, release_set=release_set)

    assert states[0].status == "partial"
    assert "clinvar.vcf.gz.md5" in states[0].missing_files


def test_collect_references_partial_when_some_gnomad_chroms_missing(tmp_path: Path) -> None:
    """gnomAD with only a subset of chroms staged → partial; missing chroms enumerated."""
    from genomeclaw_toolkit.prep.doctor import _collect_references

    release_set = _make_release_set(
        [{"source": "gnomad-exomes", "release": "v4.1", "chroms": ["1", "2", "X"]}]
    )
    base = tmp_path / "gnomad-exomes" / "v4.1" / "by_chrom"
    # Stage chr1 fully + chr2 fully; skip chrX entirely.
    _touch(base / "chr1.vcf.bgz")
    _touch(base / "chr1.vcf.bgz.tbi")
    _touch(base / "chr2.vcf.bgz")
    _touch(base / "chr2.vcf.bgz.tbi")

    states = _collect_references(reference_root=tmp_path, release_set=release_set)

    assert states[0].status == "partial"
    missing = states[0].missing_files
    assert any("chrX" in m for m in missing)
    # Files staged correctly stay out of the missing list.
    assert not any("chr1" in m for m in missing)


def test_collect_references_grch38_partial_when_fai_or_gzi_missing(tmp_path: Path) -> None:
    """grch38 needs the post-fetch .fai + .gzi to be complete — htslib won't index without them."""
    from genomeclaw_toolkit.prep.doctor import _collect_references

    release_set = _make_release_set([{"source": "grch38", "release": "ncbi-2014"}])
    grch38_dir = tmp_path / "grch38" / "ncbi-2014"
    _touch(grch38_dir / "grch38.fa.gz")
    _touch(grch38_dir / "grch38.fa.gz.md5")
    # No .fai / .gzi — post-fetch hook hasn't run.

    states = _collect_references(reference_root=tmp_path, release_set=release_set)

    assert states[0].status == "partial"
    assert "grch38.fa.gz.fai" in states[0].missing_files
    assert "grch38.fa.gz.gzi" in states[0].missing_files


# ---------------------------------------------------------------------------
# _collect_raw_sample
# ---------------------------------------------------------------------------


def test_collect_raw_sample_empty_returns_not_staged(tmp_path: Path) -> None:
    """``raw/`` exists but contains no sample dirs → staged=False."""
    from genomeclaw_toolkit.prep.doctor import _collect_raw_sample

    state = _collect_raw_sample(raw_root=tmp_path)
    assert state.staged is False
    assert state.sample_id is None
    assert state.files == ()


def test_collect_raw_sample_single_dir_with_files_returns_sample_id(tmp_path: Path) -> None:
    """A single sample dir with recognized files → staged=True; sample_id + files surface."""
    from genomeclaw_toolkit.prep.doctor import _collect_raw_sample

    sample = tmp_path / "MPNRGLQ2K"
    _touch(sample / "MPNRGLQ2K.mm2.sortdup.bqsr.cram")
    _touch(sample / "MPNRGLQ2K.mm2.sortdup.bqsr.cram.crai")
    _touch(sample / "MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz")
    _touch(sample / "MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz.tbi")

    state = _collect_raw_sample(raw_root=tmp_path)

    assert state.staged is True
    assert state.sample_id == "MPNRGLQ2K"
    # Recognized genomic files surface; sidecar indexes (.crai/.tbi) are
    # listed too so the user can confirm what's staged.
    assert "MPNRGLQ2K.mm2.sortdup.bqsr.cram" in state.files
    assert "MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz" in state.files


def test_collect_raw_sample_directory_with_subdir_but_no_files_returns_not_staged(
    tmp_path: Path,
) -> None:
    """A sample subdir that's empty doesn't count as staged."""
    from genomeclaw_toolkit.prep.doctor import _collect_raw_sample

    (tmp_path / "MPNRGLQ2K").mkdir()

    state = _collect_raw_sample(raw_root=tmp_path)
    assert state.staged is False


# ---------------------------------------------------------------------------
# _collect_derived_runs
# ---------------------------------------------------------------------------


def _stage_run(
    derived_root: Path,
    *,
    run_id: str,
    sample_id: str,
    steps: list[str],
    started_at: str = "2026-05-12T18:00:00Z",
) -> Path:
    """Write a minimal manifest.json + provenance.json under derived/<run-id>/."""
    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "schema_version": "0.2",
                "sample_id": sample_id,
                "input": {"vcf": "/mnt/genomeclaw/raw/x.vcf.gz", "sha256": "0" * 64},
                "tools": {},
                "params": {},
                "outputs": {},
                "created_at": started_at,
            }
        )
    )
    step_events = [
        {
            "step": step,
            "tool": step,
            "tool_version": "x",
            "started_at": started_at,
            "completed_at": started_at,
            "inputs": [{"path": "/mnt/x", "sha256": "0" * 64}],
        }
        for step in steps
    ]
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {"run_id": run_id, "schema_version": "0.2", "steps": step_events},
        )
    )
    return run_dir


@pytest.mark.parametrize(
    "trail,expected_stage",
    [
        (["ingest"], "ingested"),
        (["ingest", "bcftools-stats"], "ingested"),
        (["ingest", "bcftools-stats", "mosdepth-coverage"], "ingested"),
        (["ingest", "bcftools-stats", "normalize"], "normalized"),
        (["ingest", "bcftools-stats", "normalize", "vcfanno"], "annotated"),
        (["ingest", "bcftools-stats", "normalize", "vcfanno", "vep"], "annotated"),
        (
            ["ingest", "bcftools-stats", "normalize", "vcfanno", "materialize"],
            "materialized",
        ),
    ],
)
def test_collect_derived_runs_classifies_by_provenance_trail(
    tmp_path: Path, trail: list[str], expected_stage: str
) -> None:
    """The latest "real" pipeline step determines the stage label.

    Auxiliary steps (``bcftools-stats``, ``mosdepth-coverage``) are
    informational + don't move the pipeline forward, so they don't
    influence the stage classification.
    """
    from genomeclaw_toolkit.prep.doctor import _collect_derived_runs

    _stage_run(tmp_path, run_id="r1", sample_id="MPNRGLQ2K", steps=trail)

    runs = _collect_derived_runs(derived_root=tmp_path)

    assert len(runs) == 1
    assert runs[0].run_id == "r1"
    assert runs[0].sample_id == "MPNRGLQ2K"
    assert runs[0].stage == expected_stage


def test_collect_derived_runs_returns_empty_list_when_no_runs(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.doctor import _collect_derived_runs

    runs = _collect_derived_runs(derived_root=tmp_path)
    assert runs == []


def test_collect_derived_runs_sorts_by_started_at_desc(tmp_path: Path) -> None:
    """Newest run first, so the most actionable run shows at the top."""
    from genomeclaw_toolkit.prep.doctor import _collect_derived_runs

    _stage_run(
        tmp_path,
        run_id="older",
        sample_id="X",
        steps=["ingest"],
        started_at="2026-05-10T00:00:00Z",
    )
    _stage_run(
        tmp_path,
        run_id="newer",
        sample_id="X",
        steps=["ingest", "normalize"],
        started_at="2026-05-12T00:00:00Z",
    )

    runs = _collect_derived_runs(derived_root=tmp_path)

    assert [r.run_id for r in runs] == ["newer", "older"]


def test_collect_derived_runs_handles_missing_provenance_gracefully(tmp_path: Path) -> None:
    """A run dir missing ``provenance.json`` gets stage='unknown', not a crash.

    Real-world cause: pipeline crashed mid-ingest before the provenance
    file was written. Doctor still surfaces the partial run so the user
    can decide whether to retry or clean it up.
    """
    from genomeclaw_toolkit.prep.doctor import _collect_derived_runs

    run = tmp_path / "broken"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "broken",
                "schema_version": "0.2",
                "sample_id": "X",
                "input": {"vcf": "/x", "sha256": "0" * 64},
                "tools": {},
                "params": {},
                "outputs": {},
                "created_at": "2026-05-12T00:00:00Z",
            }
        )
    )

    runs = _collect_derived_runs(derived_root=tmp_path)
    assert len(runs) == 1
    assert runs[0].stage == "unknown"


def test_collect_derived_runs_ignores_non_run_dirs(tmp_path: Path) -> None:
    """A stray non-run subdir (e.g. CURRENT symlink target gone) is skipped."""
    from genomeclaw_toolkit.prep.doctor import _collect_derived_runs

    # Stray subdir with no manifest.
    (tmp_path / "not-a-run").mkdir()
    _stage_run(tmp_path, run_id="real", sample_id="X", steps=["ingest"])

    runs = _collect_derived_runs(derived_root=tmp_path)
    assert [r.run_id for r in runs] == ["real"]


# ---------------------------------------------------------------------------
# Smoke: started_at exposure
# ---------------------------------------------------------------------------


def test_collect_derived_runs_exposes_started_at_iso_string(tmp_path: Path) -> None:
    """``started_at`` round-trips as a string consumable by the text renderer."""
    from genomeclaw_toolkit.prep.doctor import _collect_derived_runs

    _stage_run(
        tmp_path,
        run_id="r",
        sample_id="X",
        steps=["ingest"],
        started_at="2026-05-12T18:00:00Z",
    )

    runs = _collect_derived_runs(derived_root=tmp_path)
    # Allow either the raw string or a datetime serialised back to one;
    # the renderer just needs something printable.
    assert runs[0].started_at is not None
    assert "2026-05-12" in str(runs[0].started_at)


# Suppress unused-import warnings for the schema modules we import for
# type-stability checks in the synthetic fixtures.
_ = datetime, timezone

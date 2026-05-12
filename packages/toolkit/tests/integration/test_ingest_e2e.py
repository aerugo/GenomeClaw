"""Phase 2 — end-to-end ``genomeclaw pipeline ingest`` against the synthetic VCF fixtures.

Sub-phase 2C-B-2 scope: the VCF-only path. ``ingest(...)`` must:

1. Validate inputs (vcf exists; reference dir exists).
2. Compute SHA256 of the source VCF (for the manifest).
3. Sniff the reference build from the VCF's ``##contig=`` headers.
4. Generate a deterministic ``run-id``.
5. Create ``derived/<run-id>/`` and the DuckDB store inside it.
6. Index the VCF if ``.tbi`` is missing — writing the index under
   ``derived/<run-id>/``, never alongside the source (`INV-D001`).
7. Stream variant rows into the ``variants`` table with a single
   ``ProvenanceTag`` per row (`INV-R001`).
8. Write ``manifest.json`` + ``provenance.json``.
9. Atomically swing ``CURRENT`` to point at the new run.

Test cases covered (per ``docs/plans/active/mvp/phases/phase-2.md``):
1, 4, 5, 6, 7, 9, 10, 11, 12, 13, 17, 18.

Cases involving ``mosdepth`` / ``bcftools stats`` / BAM (2, 8, 19, 20,
21) land in sub-phase 2C-C.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_current(derived: Path) -> Path:
    """Return the absolute path the CURRENT symlink resolves to."""
    target = os.readlink(derived / "CURRENT")
    return (derived / target).resolve()


# ---------------------------------------------------------------------------
# Pure-Python tests (host venv): input validation
# ---------------------------------------------------------------------------


def test_ingest_refuses_when_vcf_does_not_exist(genomeclaw_layout: dict[str, Path]) -> None:
    """Case 13 (variant): clear error when the input VCF path is missing."""
    from genomeclaw_toolkit.prep.ingest import ingest

    with pytest.raises(FileNotFoundError, match="vcf"):
        ingest(
            vcf=genomeclaw_layout["raw"] / "does-not-exist.vcf.gz",
            reference_dir=genomeclaw_layout["reference"],
            derived_root=genomeclaw_layout["derived"],
            sample_id="x",
        )


def test_ingest_refuses_when_reference_dir_does_not_exist(
    genomeclaw_layout: dict[str, Path], tmp_path: Path
) -> None:
    """Case 13: clear error when the reference directory is missing."""
    from genomeclaw_toolkit.prep.ingest import ingest

    # Create a token file at the VCF path so we get past the vcf-exists check.
    fake_vcf = genomeclaw_layout["raw"] / "fake.vcf.gz"
    fake_vcf.write_bytes(b"\x1f\x8b\x08")  # gzip magic; never parsed

    with pytest.raises(FileNotFoundError, match="reference"):
        ingest(
            vcf=fake_vcf,
            reference_dir=tmp_path / "no-reference-here",
            derived_root=genomeclaw_layout["derived"],
            sample_id="x",
        )


def test_ingest_refuses_when_reference_dir_path_contradicts_sniffed_build(
    genomeclaw_layout: dict[str, Path],
) -> None:
    """A grch37/-rooted reference path against a GRCh38 VCF raises ``ReferenceBuildMismatch``.

    Doesn't need bcftools — ``read_contigs`` parses gzipped VCFs with the
    stdlib's ``gzip`` module. Catches the typo case (user picks the wrong
    build dir) before any output is written.
    """
    import gzip

    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.reference_build import ReferenceBuildMismatch

    # Minimal GRCh38 VCF — only the contig header is needed for the
    # sniffer; iter_variant_rows never runs because validation raises first.
    grch38_vcf_text = (
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        "##contig=<ID=chr17,length=83257441>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    vcf = genomeclaw_layout["raw"] / "tiny.vcf.gz"
    with gzip.open(vcf, "wt") as fh:
        fh.write(grch38_vcf_text)

    # Reference dir whose path positively claims grch37 — contradiction.
    bad_ref = genomeclaw_layout["reference"] / "grch37" / "b37"
    bad_ref.mkdir(parents=True)

    with pytest.raises(ReferenceBuildMismatch, match="grch37"):
        ingest(
            vcf=vcf,
            reference_dir=bad_ref,
            derived_root=genomeclaw_layout["derived"],
            sample_id="test-001",
        )


def test_ingest_refuses_when_derived_root_does_not_exist(
    tmp_path: Path,
) -> None:
    """The derived root must be present (the shim auto-creates it on the host)."""
    from genomeclaw_toolkit.prep.ingest import ingest

    fake_vcf = tmp_path / "fake.vcf.gz"
    fake_vcf.write_bytes(b"\x1f\x8b\x08")
    ref = tmp_path / "ref"
    ref.mkdir()

    with pytest.raises(FileNotFoundError, match="derived"):
        ingest(
            vcf=fake_vcf,
            reference_dir=ref,
            derived_root=tmp_path / "no-derived",
            sample_id="x",
        )


# ---------------------------------------------------------------------------
# needs_bio tests — full ingest pipeline
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_ingest_e2e_produces_manifest_provenance_and_variants_store(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 9: a happy-path ingest produces the canonical artifact set + CURRENT."""
    from genomeclaw_toolkit.prep.ingest import ingest

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )

    assert run_dir.exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "provenance.json").exists()
    assert (run_dir / "variants.duckdb").exists()
    assert _resolve_current(genomeclaw_layout["derived"]) == run_dir.resolve()


@pytest.mark.needs_bio
def test_invD001_ingest_does_not_mutate_source_vcf(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 1 (`INV-D001`): source VCF SHA256 unchanged after ingest."""
    from genomeclaw_toolkit.prep.ingest import ingest

    sha_before = _sha256(tiny_vcf_gz)
    ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    assert _sha256(tiny_vcf_gz) == sha_before


@pytest.mark.needs_bio
def test_invD001_ingest_does_not_mutate_source_index(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 2 (`INV-D001`, partial): source ``.tbi`` SHA256 unchanged."""
    from genomeclaw_toolkit.prep.ingest import ingest

    src_tbi = tiny_vcf_gz.parent / f"{tiny_vcf_gz.name}.tbi"
    assert src_tbi.exists(), "fixture should ship a .tbi"
    tbi_sha_before = _sha256(src_tbi)
    ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    assert _sha256(src_tbi) == tbi_sha_before


@pytest.mark.needs_bio
def test_ingest_indexes_unindexed_vcf_under_derived(
    tiny_unindexed_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 10 (`INV-D001`): a missing ``.tbi`` is built under derived/, not next to source."""
    from genomeclaw_toolkit.prep.ingest import ingest

    src_dir = tiny_unindexed_vcf_gz.parent
    assert not (src_dir / f"{tiny_unindexed_vcf_gz.name}.tbi").exists()

    run_dir = ingest(
        vcf=tiny_unindexed_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-002",
    )

    # Index landed under derived/, not next to source.
    assert (run_dir / f"{tiny_unindexed_vcf_gz.name}.tbi").exists()
    assert not (src_dir / f"{tiny_unindexed_vcf_gz.name}.tbi").exists()


@pytest.mark.needs_bio
def test_ingest_sniffs_grch38_reference_build(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 11: GRCh38 contigs in the header → manifest ``reference_build_inferred='grch38'``."""
    from genomeclaw_toolkit.prep.ingest import ingest

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["input"]["reference_build_inferred"] == "grch38"


@pytest.mark.needs_bio
def test_ingest_refuses_ambiguous_reference_build(
    tiny_ambiguous_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 12: ambiguous contigs → clear error; no derived store written; CURRENT unchanged."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.reference_build import AmbiguousReferenceBuild

    with pytest.raises(AmbiguousReferenceBuild):
        ingest(
            vcf=tiny_ambiguous_vcf_gz,
            reference_dir=genomeclaw_layout["reference"],
            derived_root=genomeclaw_layout["derived"],
            sample_id="x",
        )

    # No derived store written, no CURRENT created.
    assert list(genomeclaw_layout["derived"].iterdir()) == []


@pytest.mark.needs_bio
def test_invR001_manifest_records_tool_versions(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 5: manifest's ``tools`` block has bcftools / python / duckdb / toolkit versions."""
    from genomeclaw_toolkit.prep.ingest import ingest

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    tools = manifest["tools"]
    for required in ("bcftools", "python", "duckdb", "genomeclaw-toolkit"):
        assert required in tools, f"missing tool version: {required}"
        assert tools[required], f"empty tool version: {required}"


@pytest.mark.needs_bio
def test_invR001_provenance_json_step_trail(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 6: ``provenance.json`` carries an ``ingest`` step entry with input identity."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    provenance = json.loads((run_dir / "provenance.json").read_text())
    assert provenance["schema_version"] == SCHEMA_VERSION
    assert provenance["run_id"] == run_dir.name
    assert len(provenance["steps"]) >= 1
    ingest_step = next(s for s in provenance["steps"] if s["step"] == "ingest")
    assert ingest_step["tool"] == "genomeclaw-prep"
    assert ingest_step["tool_version"]
    assert any(inp["sha256"] == _sha256(tiny_vcf_gz) for inp in ingest_step["inputs"])


@pytest.mark.needs_bio
def test_invR001_schema_version_recorded_in_manifest_and_store(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 7: the active ``schema_version`` appears in manifest.json AND schema_meta.

    Phase 2 ran v0.1; Phase 4A bumped to v0.2 (ClinVar annotation columns).
    The exact value is whatever ``schemas.SCHEMA_VERSION`` is at the
    moment ingest runs.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.schemas import SCHEMA_VERSION

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["schema_version"] == SCHEMA_VERSION

    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        version_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()
    assert version_row is not None
    assert version_row[0] == SCHEMA_VERSION


@pytest.mark.needs_bio
def test_invR001_variants_table_has_provenance_columns_populated(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 4 (populated): every emitted variants row has all seven provenance values."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.schemas import PROVENANCE_COLUMNS

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    cols_sql = ", ".join(PROVENANCE_COLUMNS)
    conn = duckdb.connect(str(run_dir / "variants.duckdb"), read_only=True)
    try:
        rows = conn.execute(f"SELECT {cols_sql} FROM variants").fetchall()
    finally:
        conn.close()

    assert len(rows) == 5  # the synthetic fixture has 5 variants
    for row in rows:
        for value in row:
            assert value is not None


@pytest.mark.needs_bio
def test_current_symlink_initial_creation_via_ingest(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 18: first ingest on an empty derived/ creates CURRENT correctly."""
    from genomeclaw_toolkit.prep.ingest import ingest

    assert not (genomeclaw_layout["derived"] / "CURRENT").exists()

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )

    current = genomeclaw_layout["derived"] / "CURRENT"
    assert current.is_symlink()
    target = os.readlink(current)
    assert not Path(target).is_absolute()
    assert _resolve_current(genomeclaw_layout["derived"]) == run_dir.resolve()


@pytest.mark.needs_bio
def test_current_symlink_atomic_update_swings_to_new_run(
    tiny_vcf_gz: Path, genomeclaw_layout: dict[str, Path]
) -> None:
    """Case 17 (happy path): a second ingest swings CURRENT to the new run."""
    from genomeclaw_toolkit.prep.ingest import ingest

    first = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )
    second = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=genomeclaw_layout["reference"],
        derived_root=genomeclaw_layout["derived"],
        sample_id="test-001",
    )

    # Same input + clock returns the same run-id (deterministic) — but the
    # ingest function generates a fresh started_at every call, so the two
    # run-ids differ. Verify CURRENT now points at the second.
    assert first != second
    assert _resolve_current(genomeclaw_layout["derived"]) == second.resolve()

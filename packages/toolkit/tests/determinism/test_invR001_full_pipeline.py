"""Phase 3 — full-pipeline determinism (`INV-R001`).

Two ingest → normalize → materialize runs against the same VCF + same
fixed clock must produce **row-equivalent** variants tables (modulo
declared non-determinism). What "row-equivalent" means in practice:

- Same row count.
- Same domain values per row (chrom / pos / id / ref / alt / qual /
  filter / sample_id / genotype).
- Same provenance values per row, *except* ``source_path`` — which is
  an absolute path that legitimately differs between derived roots. The
  ``source_sha256`` column is the deterministic identity of the source
  file regardless of where it lives.

Two declared sources of non-determinism that the toolkit deliberately
does **not** try to remove:

- ``bcftools norm`` writes a ``##bcftools_normCommand=...; Date=...``
  header into the output VCF. The date + the absolute output path make
  ``normalized.vcf.gz`` byte-non-equivalent across runs. The data
  content (post-header) is deterministic; we compare that instead.
- DuckDB writes per-segment compression headers that aren't byte-stable
  across runs even with identical inputs. The row content is
  deterministic; we compare that.

Phase 3 is the place this contract is anchored. Any future phase that
needs *byte*-equivalence (e.g. a content-addressable cache keyed on
file hash) can layer a deterministic export format (Parquet) on top
without changing the toolkit's ingest semantics.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest


def _strip_bcftools_command_header(vcf_text: str) -> str:
    """Drop ``##bcftools_*Command=`` and ``Date=`` header lines.

    These are the lines bcftools embeds with environment-specific data
    (output path, wall-clock date). Everything else is deterministic.
    """
    return "\n".join(line for line in vcf_text.splitlines() if not line.startswith("##bcftools_"))


@pytest.mark.needs_bio
def test_invR001_full_pipeline_row_equivalent_on_rerun(tiny_vcf_gz: Path, tmp_path: Path) -> None:
    """Two ingest+normalize+materialize runs at the same fixed clock match row-for-row.

    Compares everything except ``source_path``, which is an absolute
    path that legitimately differs between the two derived roots used
    in the test.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    fixed_clock = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)

    derived_a = tmp_path / "derived-a"
    derived_b = tmp_path / "derived-b"
    derived_a.mkdir()
    derived_b.mkdir()

    def _run(derived: Path) -> Path:
        run_dir = ingest(
            vcf=tiny_vcf_gz,
            reference_dir=tmp_path,
            derived_root=derived,
            sample_id="det-001",
            started_at=fixed_clock,
        )
        normalize(run_dir=run_dir, started_at=fixed_clock)
        materialize(run_dir=run_dir, started_at=fixed_clock)
        return run_dir

    run_a = _run(derived_a)
    run_b = _run(derived_b)

    # Identical run-id (same input + same fixed clock).
    assert run_a.name == run_b.name

    def _variants(run: Path) -> list[tuple]:
        conn = duckdb.connect(str(run / "variants.duckdb"), read_only=True)
        try:
            # Project away source_path (legitimately path-dependent).
            return conn.execute(
                "SELECT chrom, pos, id, ref, alt, qual, filter, sample_id, genotype, "
                "source_sha256, tool, tool_version, params_json, "
                "schema_version, created_at "
                "FROM variants ORDER BY chrom, pos, alt"
            ).fetchall()
        finally:
            conn.close()

    rows_a = _variants(run_a)
    rows_b = _variants(run_b)
    assert len(rows_a) == 6  # synthetic fixture: 5 input → 6 after split
    assert rows_a == rows_b


@pytest.mark.needs_bio
def test_invR001_normalized_vcf_data_content_equivalent_on_rerun(
    tiny_vcf_gz: Path, tmp_path: Path
) -> None:
    """The data content of ``normalized.vcf.gz`` (sans bcftools meta-header) is stable.

    bcftools writes a ``##bcftools_normCommand=...; Date=...`` line that
    embeds the absolute output path + the wall-clock date — both make
    the bytes non-equivalent across reruns. The actual VCF data lines
    (header + variants) are deterministic and the gate we can sensibly
    enforce.
    """
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.normalize import normalize

    fixed_clock = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)

    derived_a = tmp_path / "derived-a"
    derived_b = tmp_path / "derived-b"
    derived_a.mkdir()
    derived_b.mkdir()

    def _run(derived: Path) -> Path:
        run_dir = ingest(
            vcf=tiny_vcf_gz,
            reference_dir=tmp_path,
            derived_root=derived,
            sample_id="det-001",
            started_at=fixed_clock,
        )
        return normalize(run_dir=run_dir, started_at=fixed_clock)

    norm_a = _run(derived_a)
    norm_b = _run(derived_b)

    with gzip.open(norm_a, "rt") as fh:
        text_a = fh.read()
    with gzip.open(norm_b, "rt") as fh:
        text_b = fh.read()

    assert _strip_bcftools_command_header(text_a) == _strip_bcftools_command_header(text_b)


@pytest.mark.needs_bio
def test_provenance_step_trail_records_full_pipeline(tiny_vcf_gz: Path, tmp_path: Path) -> None:
    """End-to-end: provenance trail names every step in the right order."""
    from genomeclaw_toolkit.prep.ingest import ingest
    from genomeclaw_toolkit.prep.materialize import materialize
    from genomeclaw_toolkit.prep.normalize import normalize

    derived = tmp_path / "derived"
    derived.mkdir()

    run_dir = ingest(
        vcf=tiny_vcf_gz,
        reference_dir=tmp_path,
        derived_root=derived,
        sample_id="det-001",
    )
    normalize(run_dir=run_dir)
    materialize(run_dir=run_dir)

    provenance = json.loads((run_dir / "provenance.json").read_text())
    step_names = [s["step"] for s in provenance["steps"]]
    assert step_names == ["ingest", "bcftools-stats", "normalize", "materialize"]

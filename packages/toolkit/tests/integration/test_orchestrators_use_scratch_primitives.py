"""Phase 4 — orchestrators wired to ``shard_scratch`` + ``atomic_promote``.

Verifies via monkey-patch that ``materialize`` routes through the new
primitives instead of inline ``tempfile.TemporaryDirectory`` + ``shutil.
copyfile`` calls. Doesn't run the real bcftools / vcfanno chain — those
are covered by ``@needs_bio`` tests in ``test_annotate*.py`` /
``test_materialize.py``.

A Phase-4A-era ``test_annotate_uses_shard_scratch_and_atomic_promote``
was removed during the 4C.3 parent-orchestrator rewrite. ``annotate.py``
is now a thin coordinator that delegates scratch + atomic-promote to
``annotate_vcfanno`` (and later ``annotate_vep``); the structural
``INV-D003`` contract is enforced inside ``annotate_vcfanno`` and
verified end-to-end by the needs_bio tests in
``test_annotate_vcfanno.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_materialize_uses_shard_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``materialize`` opens a ``shard_scratch`` context for its DuckDB CSV staging."""
    from genomeclaw_toolkit.prep import materialize as mat_mod

    shard_scratch_calls: list[dict] = []
    real_shard_scratch = mat_mod.shard_scratch

    def spy(*args, **kwargs):
        kwargs.setdefault("base", tmp_path / "scratch")
        (tmp_path / "scratch").mkdir(exist_ok=True)
        shard_scratch_calls.append({"args": args, "kwargs": kwargs})
        return real_shard_scratch(*args, **kwargs)

    monkeypatch.setattr(mat_mod, "shard_scratch", spy)

    # Stub iter_variant_rows to yield one row, write_variants to be a no-op
    # touching only the on-disk store path.
    def fake_iter_variant_rows(path, *, info_fields=None):
        return iter([])

    def fake_write_variants(store_path, rows, *, tag, work_dir):
        # Touch the store path so the SHA256 calc can succeed.
        store_path.parent.mkdir(parents=True, exist_ok=True)
        if not store_path.exists():
            import duckdb

            conn = duckdb.connect(str(store_path))
            conn.close()
        # Drain the iterator (write_variants is supposed to consume it).
        list(rows)

    def fake_reset_variants_table(store_path):
        # Touch the file; the reset logic isn't what's being tested here.
        if not store_path.exists():
            import duckdb

            conn = duckdb.connect(str(store_path))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS variants (id INTEGER)")
            conn.close()

    monkeypatch.setattr(mat_mod, "iter_variant_rows", fake_iter_variant_rows)
    monkeypatch.setattr(mat_mod, "write_variants", fake_write_variants)
    monkeypatch.setattr(mat_mod, "_reset_variants_table", fake_reset_variants_table)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        '{"sample_id": "sample-001", "input": {"vcf_path": "/dev/null", "vcf_sha256": "abc"}}'
    )
    (run_dir / "provenance.json").write_text('{"steps": []}')
    (run_dir / "normalized.vcf.gz").write_bytes(b"stub")
    import duckdb

    conn = duckdb.connect(str(run_dir / "variants.duckdb"))
    conn.execute("CREATE TABLE IF NOT EXISTS variants (id INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.close()

    mat_mod.materialize(run_dir=run_dir)

    assert len(shard_scratch_calls) == 1
    call = shard_scratch_calls[0]
    assert call["kwargs"].get("step") == "materialize" or "materialize" in call["args"]

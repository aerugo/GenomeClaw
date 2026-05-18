"""CLI wiring for the gnomAD-constraint join on ``pipeline materialize`` + ``pipeline run``.

The 2026-05-14 Phase-4E follow-up extended ``materialize()`` with
``reference_dir`` + ``gnomad_constraint_release`` params (see
[_gnomad_constraint.py](../../src/genomeclaw_toolkit/prep/_gnomad_constraint.py)).
The Python entry point is callable; this file pins the **CLI surface**:

- ``genomeclaw pipeline materialize --reference-dir <X>`` threads
  ``reference_dir=X`` to ``materialize_impl``.
- ``genomeclaw pipeline materialize --gnomad-constraint-release v4.1``
  threads the release tag through.
- ``genomeclaw pipeline materialize`` (no flag) keeps the backwards-
  compat path: ``materialize_impl`` is called with
  ``reference_dir=None``.
- ``genomeclaw pipeline run`` propagates ``--reference-root`` to
  ``materialize_impl`` as ``reference_dir=...`` — the pre-2026-05-14 wiring
  passed it only to annotate. Without this, ``pipeline run`` would never
  populate ``gene_loeuf`` from the CLI even after the Python-side join shipped.

The underlying ``materialize_impl`` is stubbed so these tests lock the
CLI dispatch shape without retesting the orchestrator itself (see
[test_materialize_gene_loeuf.py](test_materialize_gene_loeuf.py) for
end-to-end coverage of the join).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _stage_current_symlink(derived_root: Path, run_id: str) -> Path:
    """Create ``derived_root/<run_id>/`` and point CURRENT at it."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    run_dir = derived_root / run_id
    run_dir.mkdir(parents=True)
    update_current_symlink(derived_root, run_id)
    return run_dir


def _stub_materialize(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace ``materialize_impl`` with a recorder; return the call log."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return Path("/fake/derived/run/variants.duckdb")

    monkeypatch.setattr(pipeline_cmd, "materialize_impl", fake)
    return calls


def _stub_all_pipeline_phases(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Stub every ``pipeline.*_impl`` so ``pipeline run`` can dispatch without I/O."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    calls: dict[str, list[dict]] = {
        "ingest": [],
        "normalize": [],
        "annotate": [],
        "materialize": [],
    }

    def _recorder(label: str, return_value):
        def _fake(**kwargs):
            calls[label].append(kwargs)
            return return_value

        return _fake

    monkeypatch.setattr(
        pipeline_cmd,
        "ingest_impl",
        _recorder("ingest", Path("/fake/derived/run-id")),
    )
    monkeypatch.setattr(
        pipeline_cmd,
        "normalize_impl",
        _recorder("normalize", Path("/fake/derived/run-id/normalized.vcf.gz")),
    )
    monkeypatch.setattr(
        pipeline_cmd,
        "annotate_impl",
        _recorder("annotate", Path("/fake/derived/run-id/annotated.vcf.gz")),
    )
    monkeypatch.setattr(
        pipeline_cmd,
        "materialize_impl",
        _recorder("materialize", Path("/fake/derived/run-id/variants.duckdb")),
    )
    return calls


def _stage_sample(raw_root: Path, sample_id: str, *files: str) -> Path:
    sample_dir = raw_root / sample_id
    sample_dir.mkdir(parents=True)
    for name in files:
        (sample_dir / name).write_bytes(b"")
    return sample_dir


# ---------------------------------------------------------------------------
# pipeline materialize
# ---------------------------------------------------------------------------


def test_pipeline_materialize_threads_reference_dir_to_impl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--reference-dir <X>`` reaches ``materialize_impl`` as ``reference_dir=X``."""
    run_dir = _stage_current_symlink(tmp_path, "2026-05-14T00-00-00Z-mat-001")
    reference = tmp_path / "reference"
    reference.mkdir()
    calls = _stub_materialize(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "materialize",
            "--run-dir",
            str(run_dir),
            "--reference-dir",
            str(reference),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    assert calls[0]["reference_dir"] == reference


def test_pipeline_materialize_threads_gnomad_constraint_release_to_impl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--gnomad-constraint-release v4.1`` reaches ``materialize_impl``."""
    run_dir = _stage_current_symlink(tmp_path, "2026-05-14T00-00-00Z-mat-002")
    reference = tmp_path / "reference"
    reference.mkdir()
    calls = _stub_materialize(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "materialize",
            "--run-dir",
            str(run_dir),
            "--reference-dir",
            str(reference),
            "--gnomad-constraint-release",
            "v4.1",
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["gnomad_constraint_release"] == "v4.1"


def test_pipeline_materialize_defaults_reference_dir_to_canonical_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """No ``--reference-dir`` → defaults to ``/mnt/genomeclaw/reference``.

    Mirrors the ``pipeline annotate`` default established by Phase 4C —
    the user gets the join "for free" when running inside the toolkit
    image where the bind-mount is already at the canonical path, without
    having to repeat the path on every invocation.
    """
    run_dir = _stage_current_symlink(tmp_path, "2026-05-14T00-00-00Z-mat-003")
    calls = _stub_materialize(monkeypatch)

    result = invoke_cli(
        ["pipeline", "materialize", "--run-dir", str(run_dir)],
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["reference_dir"] == Path("/mnt/genomeclaw/reference")


def test_pipeline_materialize_defaults_gnomad_constraint_release_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """No ``--gnomad-constraint-release`` → impl auto-picks (kwarg is None).

    The orchestrator's resolver handles the lex-largest-release fallback;
    the CLI just passes None through.
    """
    run_dir = _stage_current_symlink(tmp_path, "2026-05-14T00-00-00Z-mat-004")
    reference = tmp_path / "reference"
    reference.mkdir()
    calls = _stub_materialize(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "materialize",
            "--run-dir",
            str(run_dir),
            "--reference-dir",
            str(reference),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["gnomad_constraint_release"] is None


# ---------------------------------------------------------------------------
# pipeline run (the one-shot chain)
# ---------------------------------------------------------------------------


def test_pipeline_run_threads_reference_root_to_materialize_impl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``pipeline run --reference-root <Y>`` reaches materialize as ``reference_dir=Y``.

    Before this wiring, ``pipeline run`` passed ``reference_root`` to
    annotate but never to materialize, so the gene_loeuf join couldn't
    fire from a one-shot pipeline-run invocation even after the Python
    join shipped.
    """
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls = _stub_all_pipeline_phases(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert len(calls["materialize"]) == 1
    assert calls["materialize"][0]["reference_dir"] == reference_root


def test_pipeline_run_threads_gnomad_constraint_release_to_materialize_impl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``pipeline run --gnomad-constraint-release v4.1`` reaches materialize.

    Same shape as ``--clinvar-release`` (already wired to annotate); a
    Phase-4-close prerequisite so the one-shot run command exposes the
    gene_loeuf source pin.
    """
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "S1", "S1.hc.vcf.gz")
    reference_root = tmp_path / "reference"
    (reference_root / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()

    calls = _stub_all_pipeline_phases(monkeypatch)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(reference_root),
            "--derived-root",
            str(derived),
            "--gnomad-constraint-release",
            "v4.1",
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls["materialize"][0]["gnomad_constraint_release"] == "v4.1"

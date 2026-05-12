"""CLI coverage for ``--run-dir`` autodetect on pipeline normalize / annotate / materialize.

Each subcommand's ``--run-dir`` is optional: absence and the
bare-flag form both resolve ``<--derived-root>/CURRENT``. An explicit
path passes through. ``pipeline annotate`` additionally defaults
``--reference-dir`` to ``/mnt/genomeclaw/reference``.

The underlying ``*_impl`` callables are stubbed so these tests never
touch the real orchestrators — the goal is to lock the CLI dispatch
shape, not retest the orchestrators.
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


def _stub(monkeypatch: pytest.MonkeyPatch, attr: str, calls: list[dict]) -> None:
    """Replace ``pipeline.<attr>`` with a recorder that returns a fake path."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    def fake(**kwargs):
        calls.append(kwargs)
        return Path("/fake/out")

    monkeypatch.setattr(pipeline_cmd, attr, fake)


# ---------------------------------------------------------------------------
# pipeline normalize
# ---------------------------------------------------------------------------


def test_normalize_omitted_run_dir_resolves_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--run-dir`` absent → resolve CURRENT symlink."""
    run_dir = _stage_current_symlink(tmp_path, "2026-05-06T08-12-34Z-abc123")
    calls: list[dict] = []
    _stub(monkeypatch, "normalize_impl", calls)

    result = invoke_cli(["pipeline", "normalize", "--derived-root", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls[0]["run_dir"] == run_dir.resolve()


def test_normalize_explicit_run_dir_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """Explicit ``--run-dir <path>`` passes through unchanged."""
    explicit = tmp_path / "some-other-run"
    explicit.mkdir()
    calls: list[dict] = []
    _stub(monkeypatch, "normalize_impl", calls)

    result = invoke_cli(["pipeline", "normalize", "--run-dir", str(explicit)])

    assert result.exit_code == 0, result.stderr
    assert calls[0]["run_dir"] == explicit


def test_normalize_errors_when_no_current_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """No CURRENT symlink → precondition error (exit 3)."""
    calls: list[dict] = []
    _stub(monkeypatch, "normalize_impl", calls)

    result = invoke_cli(["pipeline", "normalize", "--derived-root", str(tmp_path)])

    assert result.exit_code == 3
    assert calls == []
    assert "no CURRENT symlink" in result.stderr


# ---------------------------------------------------------------------------
# pipeline materialize (same shape as normalize)
# ---------------------------------------------------------------------------


def test_materialize_omitted_run_dir_resolves_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--run-dir`` absent → resolve CURRENT symlink."""
    run_dir = _stage_current_symlink(tmp_path, "2026-05-06T08-12-34Z-abc123")
    calls: list[dict] = []
    _stub(monkeypatch, "materialize_impl", calls)

    result = invoke_cli(["pipeline", "materialize", "--derived-root", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls[0]["run_dir"] == run_dir.resolve()


def test_materialize_explicit_run_dir_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """Explicit ``--run-dir <path>`` passes through unchanged."""
    explicit = tmp_path / "some-other-run"
    explicit.mkdir()
    calls: list[dict] = []
    _stub(monkeypatch, "materialize_impl", calls)

    result = invoke_cli(["pipeline", "materialize", "--run-dir", str(explicit)])

    assert result.exit_code == 0, result.stderr
    assert calls[0]["run_dir"] == explicit


# ---------------------------------------------------------------------------
# pipeline annotate — autodetect for --run-dir + default for --reference-dir
# ---------------------------------------------------------------------------


def test_annotate_omitted_run_dir_resolves_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--run-dir`` absent → resolve CURRENT symlink; ``--reference-dir`` passes through."""
    run_dir = _stage_current_symlink(tmp_path, "2026-05-06T08-12-34Z-abc123")
    reference = tmp_path / "reference"
    reference.mkdir()
    calls: list[dict] = []
    _stub(monkeypatch, "annotate_impl", calls)

    result = invoke_cli(
        [
            "pipeline",
            "annotate",
            "--derived-root",
            str(tmp_path),
            "--reference-dir",
            str(reference),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert calls[0]["run_dir"] == run_dir.resolve()
    assert calls[0]["reference_dir"] == reference


def test_annotate_reference_dir_defaults_to_canonical_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """No ``--reference-dir`` → defaults to ``/mnt/genomeclaw/reference``."""
    _stage_current_symlink(tmp_path, "2026-05-06T08-12-34Z-abc123")
    calls: list[dict] = []
    _stub(monkeypatch, "annotate_impl", calls)

    result = invoke_cli(["pipeline", "annotate", "--derived-root", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls[0]["reference_dir"] == Path("/mnt/genomeclaw/reference")


def test_annotate_errors_when_no_current_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """No CURRENT symlink → precondition error (exit 3)."""
    calls: list[dict] = []
    _stub(monkeypatch, "annotate_impl", calls)

    result = invoke_cli(["pipeline", "annotate", "--derived-root", str(tmp_path)])

    assert result.exit_code == 3
    assert calls == []
    assert "no CURRENT symlink" in result.stderr

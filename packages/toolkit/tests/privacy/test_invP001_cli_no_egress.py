"""`INV-P001` — CLI commands make zero outbound HTTP calls in default mode.

GenomeClaw's privacy-default invariant: the CLI never silently
exfiltrates state to a remote endpoint. ``refs fetch`` is the one
deliberate egress surface; everything else (``host doctor``,
``runs *``, ``pipeline *`` invocations against synthetic fixtures)
must complete without touching the network.

This test exercises each migrated command under a mocked HTTP layer
that raises on any call. If a future change introduces an
accidental telemetry / auto-update / crash-reporter hook, this test
catches it.

Phase 1 covers ``host doctor``. Each subsequent rich-cli phase
extends this test file as its commands migrate (the
[development plan](../../docs/plans/active/rich-cli/development-plan.md)
calls this out explicitly).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def _no_outbound_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any ``urllib.request.urlopen`` call to assert zero outbound HTTP.

    This is the bluntest possible check — if the CLI ever tries to
    open a URL, the call raises. Tests that genuinely need to fetch
    (``refs fetch``) live elsewhere and don't apply this fixture.
    """

    def fail_urlopen(*args: object, **kwargs: object) -> object:
        raise RuntimeError(
            f"INV-P001 violation: unexpected outbound HTTP call (args={args!r}, kwargs={kwargs!r})"
        )

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)


def _stub_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a clean doctor report so the privacy test focuses on egress."""
    from genomeclaw_toolkit._cli.commands import host as host_cmd

    def fake_doctor() -> tuple[int, dict[str, object]]:
        return (
            0,
            {
                "checks": [],
                "setup_log": {"found": False},
                "colima": {"installed": False},
                "paths": {},
                "references": {"release_set": None, "sources": []},
                "raw_sample": {"staged": False},
                "derived_runs": [],
            },
        )

    monkeypatch.setattr(host_cmd, "doctor_impl", fake_doctor)


def test_invP001_no_egress_during_host_doctor_rich(
    invoke_cli,
    monkeypatch: pytest.MonkeyPatch,
    _no_outbound_http: None,
) -> None:
    """`host doctor` (rich mode) makes zero outbound HTTP calls."""
    _stub_doctor(monkeypatch)
    result = invoke_cli(["host", "doctor"])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_host_doctor_json(
    invoke_cli,
    monkeypatch: pytest.MonkeyPatch,
    _no_outbound_http: None,
) -> None:
    """`host doctor --json` makes zero outbound HTTP calls."""
    _stub_doctor(monkeypatch)
    result = invoke_cli(["--json", "host", "doctor"])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_help() -> None:
    """`genomeclaw --help` doesn't touch the network."""
    # No fixture needed — we don't even import the entry point. Just
    # confirm the help path is purely local by importing the app
    # construction module under a strict no-urlopen monkey-patch.
    import urllib.request

    original = urllib.request.urlopen

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("INV-P001 violation")

    urllib.request.urlopen = fail  # type: ignore[assignment]
    try:
        from genomeclaw_toolkit._cli import app  # noqa: F401 — import-time check
    finally:
        urllib.request.urlopen = original  # type: ignore[assignment]


def test_invP001_no_egress_during_version_flag() -> None:
    """`--version` reads local state only — never the network."""
    import urllib.request

    original = urllib.request.urlopen

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("INV-P001 violation")

    urllib.request.urlopen = fail  # type: ignore[assignment]
    try:
        from genomeclaw_toolkit._cli.version import collect_version

        payload = collect_version()
        # toolkit_version is required; others optional.
        assert payload.toolkit_version
    finally:
        urllib.request.urlopen = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Phase 2 extensions — refs + runs commands
# ---------------------------------------------------------------------------


def test_invP001_no_egress_during_refs_list(
    invoke_cli,
    tmp_path,
    _no_outbound_http: None,
) -> None:
    """`refs list` reads only the local reference tree + bundled release-set TOML."""
    ref = tmp_path / "reference"
    ref.mkdir()
    result = invoke_cli(["refs", "list", "--reference-root", str(ref)])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_refs_verify(
    invoke_cli,
    tmp_path,
    _no_outbound_http: None,
) -> None:
    """`refs verify` only reads file headers/tails; no network."""
    ref = tmp_path / "reference"
    ref.mkdir()
    result = invoke_cli(["refs", "verify", "--reference-root", str(ref)])
    # Exit 4 is expected when nothing is staged (every expected file
    # is missing) — the point of the test is "no HTTP call happened".
    assert result.exit_code in (0, 4)


def test_invP001_no_egress_during_runs_list(
    invoke_cli,
    tmp_path,
    _no_outbound_http: None,
) -> None:
    """`runs list` only reads ``derived/<run-id>/manifest.json``."""
    derived = tmp_path / "derived"
    derived.mkdir()
    result = invoke_cli(["runs", "list", "--derived-root", str(derived)])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_runs_current(
    invoke_cli,
    tmp_path,
    _no_outbound_http: None,
) -> None:
    """`runs current` only reads CURRENT symlink + manifest; no network."""
    derived = tmp_path / "derived"
    derived.mkdir()
    result = invoke_cli(["runs", "current", "--derived-root", str(derived)])
    # Exit 3 when no CURRENT exists — fine; the point is "no HTTP".
    assert result.exit_code in (0, 3)


# ---------------------------------------------------------------------------
# Phase 5: pipeline commands make zero outbound HTTP calls
# ---------------------------------------------------------------------------


def _stub_pipeline_orchestrators(monkeypatch) -> None:
    """Stub every ``pipeline.*_impl`` so the suite can run without bio tools."""
    from pathlib import Path as _Path

    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd

    def _fake(**_kw):  # type: ignore[no-untyped-def]
        return _Path("/fake/derived/run-id")

    monkeypatch.setattr(pipeline_cmd, "ingest_impl", _fake)
    monkeypatch.setattr(pipeline_cmd, "normalize_impl", _fake)
    monkeypatch.setattr(pipeline_cmd, "annotate_impl", _fake)
    monkeypatch.setattr(pipeline_cmd, "materialize_impl", _fake)


def _stage_sample_dir(tmp_path) -> tuple[str, str, str]:
    """Create raw/<sample>/<vcf> + reference/grch38/ + derived/CURRENT layout."""
    raw = tmp_path / "raw"
    raw.mkdir()
    sample_dir = raw / "MPNRGLQ2K"
    sample_dir.mkdir()
    (sample_dir / "MPNRGLQ2K.hc.vcf.gz").write_bytes(b"")
    ref = tmp_path / "reference"
    (ref / "grch38").mkdir(parents=True)
    derived = tmp_path / "derived"
    derived.mkdir()
    run = derived / "fake-run"
    run.mkdir()
    (run / "manifest.json").write_text('{"run_id": "fake-run"}')
    (derived / "CURRENT").symlink_to("fake-run")
    return str(raw), str(ref), str(derived)


def test_invP001_no_egress_during_pipeline_ingest(
    invoke_cli, monkeypatch, tmp_path, _no_outbound_http: None
) -> None:
    """`pipeline ingest` is a local-only operation."""
    _stub_pipeline_orchestrators(monkeypatch)
    raw, ref, derived = _stage_sample_dir(tmp_path)
    result = invoke_cli(
        [
            "pipeline",
            "ingest",
            "--raw-root",
            raw,
            "--reference-root",
            ref,
            "--derived-root",
            derived,
        ]
    )
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_pipeline_normalize(
    invoke_cli, monkeypatch, tmp_path, _no_outbound_http: None
) -> None:
    """`pipeline normalize` is a local-only operation."""
    _stub_pipeline_orchestrators(monkeypatch)
    _raw, _ref, derived = _stage_sample_dir(tmp_path)
    result = invoke_cli(["pipeline", "normalize", "--derived-root", derived])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_pipeline_annotate(
    invoke_cli, monkeypatch, tmp_path, _no_outbound_http: None
) -> None:
    """`pipeline annotate` is a local-only operation (reads bundled refs)."""
    _stub_pipeline_orchestrators(monkeypatch)
    _raw, ref, derived = _stage_sample_dir(tmp_path)
    result = invoke_cli(["pipeline", "annotate", "--derived-root", derived, "--reference-dir", ref])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_pipeline_materialize(
    invoke_cli, monkeypatch, tmp_path, _no_outbound_http: None
) -> None:
    """`pipeline materialize` is a local-only operation."""
    _stub_pipeline_orchestrators(monkeypatch)
    _raw, _ref, derived = _stage_sample_dir(tmp_path)
    result = invoke_cli(["pipeline", "materialize", "--derived-root", derived])
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_pipeline_run(
    invoke_cli, monkeypatch, tmp_path, _no_outbound_http: None
) -> None:
    """`pipeline run` chains 4 stages; none of them touch the network."""
    _stub_pipeline_orchestrators(monkeypatch)
    raw, ref, derived = _stage_sample_dir(tmp_path)
    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            raw,
            "--reference-root",
            ref,
            "--derived-root",
            derived,
        ]
    )
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# Phase 6: destructive commands (under --yes) make zero outbound HTTP calls
# ---------------------------------------------------------------------------


def test_invP001_no_egress_during_host_setup_dry_run_yes(
    invoke_cli, monkeypatch, _no_outbound_http: None
) -> None:
    """`--yes host setup --dry-run --force-reset` is local-only."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    monkeypatch.setattr(host_cmd, "setup_run_smart", lambda: 0)
    monkeypatch.setattr(host_cmd, "setup_run_interactive", lambda **_kw: 0)
    result = invoke_cli(
        [
            "--yes",
            "host",
            "setup",
            "--force-reset",
            "--dry-run",
            "--source",
            "/tmp/nebula",
            "--target-volume",
            "Genome_Work",
        ]
    )
    assert result.exit_code == 0, result.stderr


def test_invP001_no_egress_during_host_eject_yes(
    invoke_cli, monkeypatch, _no_outbound_http: None
) -> None:
    """`--yes host eject` is local-only (diskutil + colima stop)."""
    import genomeclaw_toolkit._cli.commands.host as host_cmd

    monkeypatch.setattr(host_cmd, "eject_impl", lambda **_kw: 0)
    result = invoke_cli(["--yes", "host", "eject", "--drive", "/Volumes/Genome_Work"])
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# Phase 7: completion script generation is local-only
# ---------------------------------------------------------------------------


def test_invP001_no_egress_during_completion_bash(invoke_cli, _no_outbound_http: None) -> None:
    """`completion bash` emits a script to stdout; never touches the network."""
    result = invoke_cli(["completion", "bash"])
    assert result.exit_code == 0, result.stderr
    assert "genomeclaw" in result.stdout

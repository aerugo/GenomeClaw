"""Phase 5 — ``pipeline`` rich panels + NDJSON event stream tests.

The Phase-5 migration plumbs ``progress_callback`` through the four
``prep/`` orchestrators (``ingest`` / ``normalize`` / ``annotate`` /
``materialize``) so each emits ``PhaseStart`` + ``PhaseComplete``
events. ``pipeline run`` aggregates these across all four stages +
emits a terminal ``PipelineComplete``. Rich mode renders one
``Panel`` per stage with duration; JSON mode emits NDJSON one event
per line behind a first-line ``cli_output_schema_version`` envelope.

These tests stub each orchestrator's ``*_impl`` at the CLI module so
the suite runs on the host without bcftools / vcfanno / duckdb.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _stage_sample(raw_root: Path, sample_id: str, *files: str) -> Path:
    sample_dir = raw_root / sample_id
    sample_dir.mkdir(parents=True)
    for name in files:
        (sample_dir / name).write_bytes(b"")
    return sample_dir


def _stub_all(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Stub every ``pipeline.*_impl`` the pipeline calls; return per-phase call logs.

    The fakes inspect ``progress_callback`` if present and emit
    ``PhaseStart`` + ``PhaseComplete`` events themselves, mimicking what
    a fully-graduated orchestrator would do.
    """
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd
    from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart

    calls: dict[str, list[dict]] = {
        "ingest": [],
        "normalize": [],
        "annotate": [],
        "materialize": [],
    }
    run_dir = Path("/fake/derived/run-id")

    def _make_fake(phase: str, out_path: Path):
        def fake(**kwargs):
            calls[phase].append(kwargs)
            cb = kwargs.get("progress_callback")
            if cb is not None:
                cb(PhaseStart(phase=phase))
                cb(
                    PhaseComplete(
                        phase=phase,
                        duration_sec=0.01,
                        run_dir=str(run_dir),
                    )
                )
            return out_path

        return fake

    monkeypatch.setattr(pipeline_cmd, "ingest_impl", _make_fake("ingest", run_dir))
    monkeypatch.setattr(
        pipeline_cmd,
        "normalize_impl",
        _make_fake("normalize", run_dir / "normalized.vcf.gz"),
    )
    monkeypatch.setattr(
        pipeline_cmd, "annotate_impl", _make_fake("annotate", run_dir / "annotated.vcf.gz")
    )
    monkeypatch.setattr(
        pipeline_cmd, "materialize_impl", _make_fake("materialize", run_dir / "variants.duckdb")
    )
    return calls


# ---------------------------------------------------------------------------
# pipeline run — NDJSON event stream
# ---------------------------------------------------------------------------


def test_pipeline_run_json_emits_envelope_then_phase_events_then_pipeline_complete(
    invoke_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--json pipeline run` emits envelope → 4×phase_start/complete → pipeline_complete."""
    _stub_all(monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    ref_root = tmp_path / "reference"
    (ref_root / "grch38").mkdir(parents=True)

    result = invoke_cli(
        [
            "--json",
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(ref_root),
            "--derived-root",
            str(tmp_path / "derived"),
        ]
    )
    assert result.exit_code == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) >= 1, "expected at least the envelope line"

    envelope = json.loads(lines[0])
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "pipeline.run"
    assert envelope.get("stream") is True

    events = [json.loads(line) for line in lines[1:]]
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["event"], []).append(e)

    # Four phases, each emits start + complete.
    assert {e["phase"] for e in by_type.get("phase_start", [])} == {
        "ingest",
        "normalize",
        "annotate",
        "materialize",
    }
    assert {e["phase"] for e in by_type.get("phase_complete", [])} == {
        "ingest",
        "normalize",
        "annotate",
        "materialize",
    }

    # Terminal event.
    assert len(by_type.get("pipeline_complete", [])) == 1
    completion = by_type["pipeline_complete"][0]
    assert completion["run_dir"]
    assert completion["duration_sec"] >= 0.0


def test_pipeline_run_json_emits_phase_failed_on_normalize_error(
    invoke_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--json pipeline run` surfaces a phase_failed event when normalize raises."""
    import genomeclaw_toolkit._cli.commands.pipeline as pipeline_cmd
    from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart

    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    ref_root = tmp_path / "reference"
    (ref_root / "grch38").mkdir(parents=True)

    def fake_ingest(**kwargs):
        cb = kwargs.get("progress_callback")
        if cb is not None:
            cb(PhaseStart(phase="ingest"))
            cb(PhaseComplete(phase="ingest", duration_sec=0.01, run_dir="/fake/run"))
        return Path("/fake/derived/run-id")

    def fake_normalize(**kwargs):
        cb = kwargs.get("progress_callback")
        if cb is not None:
            cb(PhaseStart(phase="normalize"))
        raise FileNotFoundError("synthetic normalize failure")

    monkeypatch.setattr(pipeline_cmd, "ingest_impl", fake_ingest)
    monkeypatch.setattr(pipeline_cmd, "normalize_impl", fake_normalize)

    result = invoke_cli(
        [
            "--json",
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(ref_root),
            "--derived-root",
            str(tmp_path / "derived"),
        ]
    )
    assert result.exit_code == 1, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines[1:]]
    failed = [e for e in events if e["event"] == "phase_failed"]
    assert failed, f"expected phase_failed; got events: {events!r}"
    assert failed[0]["phase"] == "normalize"


# ---------------------------------------------------------------------------
# pipeline run — rich-mode panel rendering
# ---------------------------------------------------------------------------


def test_pipeline_run_rich_renders_phase_panels_in_order(
    invoke_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rich mode names each phase in order in stderr (one Panel per phase)."""
    _stub_all(monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    ref_root = tmp_path / "reference"
    (ref_root / "grch38").mkdir(parents=True)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(ref_root),
            "--derived-root",
            str(tmp_path / "derived"),
        ]
    )
    assert result.exit_code == 0, result.stderr

    # Order: each phase name appears in stderr; the order matches the
    # pipeline ordering.
    out = result.stderr
    pos = {phase: out.find(phase) for phase in ("ingest", "normalize", "annotate", "materialize")}
    for phase, p in pos.items():
        assert p >= 0, f"expected '{phase}' to appear in stderr (got: {out!r})"
    assert pos["ingest"] < pos["normalize"] < pos["annotate"] < pos["materialize"]


# ---------------------------------------------------------------------------
# single-stage commands — NDJSON for each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subcommand", "extra_args", "phase_name"),
    [
        ("ingest", [], "ingest"),
        ("normalize", [], "normalize"),
        ("annotate", [], "annotate"),
        ("materialize", [], "materialize"),
    ],
)
def test_pipeline_single_stage_json_emits_phase_events(
    invoke_cli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subcommand: str,
    extra_args: list[str],
    phase_name: str,
) -> None:
    """Each single-stage command (`pipeline ingest` etc.) emits its NDJSON events."""
    _stub_all(monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    derived = tmp_path / "derived"
    derived.mkdir()
    # The downstream commands (normalize / annotate / materialize) read
    # CURRENT — stage one so autodetect succeeds.
    run_dir = derived / "fake-run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text('{"run_id": "fake-run"}')
    (derived / "CURRENT").symlink_to("fake-run")

    ref_root = tmp_path / "reference"
    (ref_root / "grch38").mkdir(parents=True)

    args = [
        "--json",
        "pipeline",
        subcommand,
    ]
    if subcommand == "ingest":
        args += [
            "--raw-root",
            str(raw),
            "--reference-root",
            str(ref_root),
            "--derived-root",
            str(derived),
        ]
    else:
        args += ["--derived-root", str(derived)]
    args += extra_args

    result = invoke_cli(args)
    assert result.exit_code == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    envelope = json.loads(lines[0])
    assert envelope["command"] == f"pipeline.{subcommand}"
    assert envelope.get("stream") is True

    events = [json.loads(line) for line in lines[1:]]
    types_for_phase = {(e["event"], e.get("phase")) for e in events}
    assert ("phase_start", phase_name) in types_for_phase
    assert ("phase_complete", phase_name) in types_for_phase


# ---------------------------------------------------------------------------
# Cross-cutting NDJSON structural tests
# ---------------------------------------------------------------------------


def test_pipeline_run_no_stdout_pollution_outside_events(
    invoke_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every stdout line in `--json` mode parses as JSON."""
    _stub_all(monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    ref_root = tmp_path / "reference"
    (ref_root / "grch38").mkdir(parents=True)

    result = invoke_cli(
        [
            "--json",
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(ref_root),
            "--derived-root",
            str(tmp_path / "derived"),
        ]
    )
    assert result.exit_code == 0, result.stderr

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Must parse — raises on pollution.
        json.loads(line)


# ---------------------------------------------------------------------------
# INV-D001: source VCF unchanged after rich-mode pipeline run
# (covered by stubbed call args: the source VCF path is passed through
# unchanged; no orchestrator writes to it).
# ---------------------------------------------------------------------------


def test_invD001_pipeline_run_threads_unchanged_source_vcf(
    invoke_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`pipeline run` passes the source VCF path through ingest unchanged.

    The full INV-D001 sha256 check requires the bio-tool image. This
    test verifies the wiring contract: every kwarg ingest received
    matches the on-disk inputs and is path-only (no in-place edits).
    """
    calls = _stub_all(monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    _stage_sample(raw, "MPNRGLQ2K", "MPNRGLQ2K.hc.vcf.gz")
    ref_root = tmp_path / "reference"
    (ref_root / "grch38").mkdir(parents=True)

    result = invoke_cli(
        [
            "pipeline",
            "run",
            "--raw-root",
            str(raw),
            "--reference-root",
            str(ref_root),
            "--derived-root",
            str(tmp_path / "derived"),
        ]
    )
    assert result.exit_code == 0, result.stderr

    assert len(calls["ingest"]) == 1
    src = calls["ingest"][0]["vcf"]
    assert src == raw / "MPNRGLQ2K" / "MPNRGLQ2K.hc.vcf.gz"
    assert src.exists()

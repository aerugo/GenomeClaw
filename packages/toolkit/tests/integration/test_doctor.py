"""Phase 5 — ``genomeclaw host doctor`` subcommand tests.

Doctor is read-only and host-native: checks the four canonical
subdirs exist, probes ``derived/`` and ``_scratch/`` for host-side
writability, reads ``_scratch/setup.log``, surfaces colima status,
and renders text or JSON. Exit 0 iff all checks pass; 1 if any FAIL.

Doctor does NOT enforce raw/reference being read-only — the shim
binds them RO inside the container regardless of host fs perms, and
the in-container ``preflight`` module asserts that at every
orchestrator entry. Doctor is upstream of that.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _make_layout(tmp_path: Path) -> dict[str, Path]:
    """Synthesise the four canonical mounts under tmp_path."""
    raw = tmp_path / "raw"
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    scratch = tmp_path / "scratch"
    for d in (raw, reference, derived, scratch):
        d.mkdir()
    return {"raw": raw, "reference": reference, "derived": derived, "scratch": scratch}


def _restore_perms(layout: dict[str, Path]) -> None:
    for path in layout.values():
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def test_doctor_reports_all_checks_when_layout_healthy(tmp_path: Path) -> None:
    """Healthy layout → all 4 host-side checks OK; exit 0."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    rc, report = doctor(paths=layout, runner=_StubRunner())
    assert rc == 0
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert statuses == {
        "raw_present": "OK",
        "reference_present": "OK",
        "derived_writable": "OK",
        "scratch_writable": "OK",
    }


def test_doctor_reports_failures_clearly_when_layout_broken(tmp_path: Path) -> None:
    """``derived/`` host-RO → FAIL on derived_writable, OK on others; exit 1."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    os.chmod(layout["derived"], 0o555)
    try:
        rc, report = doctor(paths=layout, runner=_StubRunner())
        assert rc == 1
        statuses = {c["name"]: c["status"] for c in report["checks"]}
        assert statuses["derived_writable"] == "FAIL"
        # Every other check should still pass — doctor doesn't bail early.
        assert statuses["raw_present"] == "OK"
        assert statuses["reference_present"] == "OK"
        assert statuses["scratch_writable"] == "OK"
        # The failure carries a usable error message.
        derived = next(c for c in report["checks"] if c["name"] == "derived_writable")
        assert "writable" in derived["message"].lower()
    finally:
        _restore_perms(layout)


def test_doctor_reports_missing_subdir_clearly(tmp_path: Path) -> None:
    """Missing canonical subdir → FAIL with a setup hint; exit 1."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    layout["raw"].rmdir()
    rc, report = doctor(paths=layout, runner=_StubRunner())
    assert rc == 1
    raw_check = next(c for c in report["checks"] if c["name"] == "raw_present")
    assert raw_check["status"] == "FAIL"
    assert "setup" in raw_check["message"].lower()


def test_doctor_reads_setup_log(tmp_path: Path) -> None:
    """Doctor surfaces the most recent ``setup_completed`` event from the audit log."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    scratch_log = layout["scratch"] / "setup.log"
    scratch_log.write_text(
        json.dumps(
            {
                "ts": "2026-05-10T00:30:00Z",
                "step": "setup_completed",
                "phase": "complete",
                "payload": {
                    "completed_at": "2026-05-10T00:30:00Z",
                    "toolkit_version": "0.0.1",
                },
            }
        )
        + "\n"
    )
    rc, report = doctor(paths=layout, runner=_StubRunner())
    assert rc == 0  # all checks still pass
    assert report["setup_log"]["found"] is True
    assert report["setup_log"]["last_completed_at"] == "2026-05-10T00:30:00Z"
    assert report["setup_log"]["toolkit_version"] == "0.0.1"


def test_doctor_handles_missing_setup_log(tmp_path: Path) -> None:
    """No ``setup.log`` → doctor reports it cleanly; doesn't crash."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    rc, report = doctor(paths=layout, runner=_StubRunner())
    assert rc == 0
    assert report["setup_log"]["found"] is False


def test_doctor_json_output_is_machine_readable(tmp_path: Path) -> None:
    """``doctor`` returns a dict; ``json.dumps`` round-trips it."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    _, report = doctor(paths=layout, runner=_StubRunner())
    rendered = json.dumps(report)
    parsed = json.loads(rendered)
    assert {"checks", "setup_log", "colima"} <= parsed.keys()
    assert isinstance(parsed["checks"], list)


def test_doctor_surfaces_colima_status(tmp_path: Path) -> None:
    """Doctor captures colima version + status from the runner."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    runner = _StubRunner()
    runner.responses[("colima", "version")] = (0, "colima version 0.9.1\n", "")
    runner.responses[("colima", "status")] = (
        0,
        "",
        'time="..." level=info msg="colima is running using macOS Virtualization.Framework"\n',
    )
    _, report = doctor(paths=layout, runner=runner)
    assert "0.9.1" in report["colima"]["version"]
    assert report["colima"]["status"] == "running"


# ---------------------------------------------------------------------------
# Pipeline-readiness extension (doctor v2)
# ---------------------------------------------------------------------------


def _stage_run(
    derived_root: Path, run_id: str, steps: list[str], sample_id: str = "MPNRGLQ2K"
) -> None:
    """Stage a derived/<run-id>/ with manifest + provenance trail."""
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
                "created_at": "2026-05-12T18:00:00Z",
            }
        )
    )
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "schema_version": "0.2",
                "steps": [
                    {
                        "step": s,
                        "tool": s,
                        "tool_version": "x",
                        "started_at": "2026-05-12T18:00:00Z",
                        "completed_at": "2026-05-12T18:00:00Z",
                        "inputs": [{"path": "/mnt/x", "sha256": "0" * 64}],
                    }
                    for s in steps
                ],
            }
        )
    )


def test_doctor_reports_references_raw_sample_and_derived_runs(tmp_path: Path) -> None:
    """End-to-end: ``doctor`` report carries three new blocks once the helpers land."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    # Stage a complete clinvar release.
    cv_dir = layout["reference"] / "clinvar" / "2026-05-09"
    cv_dir.mkdir(parents=True)
    (cv_dir / "clinvar.vcf.gz").write_bytes(b"x")
    (cv_dir / "clinvar.vcf.gz.md5").write_bytes(b"x")
    (cv_dir / "clinvar.vcf.gz.tbi").write_bytes(b"x")
    # Stage a sample under raw/.
    sample = layout["raw"] / "MPNRGLQ2K"
    sample.mkdir()
    (sample / "MPNRGLQ2K.vcf.gz").write_bytes(b"x")
    # Stage one derived run mid-pipeline.
    _stage_run(layout["derived"], run_id="run-1", steps=["ingest", "normalize"])

    _, report = doctor(paths=layout, runner=_StubRunner())

    # AC1 — references block surfaces per-source state.
    assert "references" in report
    sources = {s["source"]: s for s in report["references"]["sources"]}
    assert "clinvar" in sources
    assert sources["clinvar"]["status"] == "OK"

    # AC2 — raw sample block surfaces the staged sample id.
    assert report["raw_sample"]["staged"] is True
    assert report["raw_sample"]["sample_id"] == "MPNRGLQ2K"

    # AC3 — derived runs block lists the run + its stage.
    assert len(report["derived_runs"]) == 1
    assert report["derived_runs"][0]["run_id"] == "run-1"
    assert report["derived_runs"][0]["stage"] == "normalized"


def test_doctor_json_extension_is_backwards_compatible(tmp_path: Path) -> None:
    """AC5 — existing JSON keys remain stable; new keys land alongside."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    _, report = doctor(paths=layout, runner=_StubRunner())

    # Existing keys must still exist with the same shape.
    assert {"checks", "setup_log", "colima", "paths"} <= report.keys()
    assert isinstance(report["checks"], list)

    # New keys land alongside.
    assert {"references", "raw_sample", "derived_runs"} <= report.keys()
    # JSON-serialisable.
    json.dumps(report)


def test_doctor_exit_code_unaffected_by_missing_references(tmp_path: Path) -> None:
    """AC6 — missing reference data must not change the exit code.

    Doctor stays infrastructure-only for exit-code purposes; the
    Reference / Raw / Derived blocks are "what to do next" signals,
    not corrupted-state alarms.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    # reference/ is empty — no datasets fetched.
    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0
    # And the references block reports the gap accurately.
    states = report["references"]["sources"]
    assert any(s["status"] == "missing" for s in states)


# Note: `render_text` lived in `prep/doctor.py` pre-rich-cli; it was
# deleted in rich-cli Phase 1 when the renderer moved to
# `_cli/renderers/host.py`. The rich-rendered output is covered by
# `tests/integration/test_cli_host_doctor.py`; the "next step pointer
# for missing references" suggestion line is a Phase 2 deliverable
# (`refs verify`'s output) rather than a doctor concern.


# ---------------------------------------------------------------------------
# Stub subprocess runner — same shape eject.py + doctor.py expect
# ---------------------------------------------------------------------------


class _StubRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[tuple[str, ...], tuple[int, str, str]] = {}

    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        key = tuple(cmd)
        self.calls.append(key)
        return self.responses.get(key, (0, "", ""))

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


# ---------------------------------------------------------------------------
# PRS Reference Bootstrap Phase 2 — ancestry_ready readiness gate.
#
# `host doctor` surfaces a new informational `ancestry_ready` section that
# probes the canonical post-fetch layout under
# `reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/`. Per INV-C001 v1.7 a
# partial fetch (one of two subtrees) must be flagged explicitly — silent
# degradation of ancestry calibration would let PRS findings ship that
# the Slice E.3 PRS-decline pattern cannot defend.
#
# `ancestry_ready` is informational, matching the `references_section`
# pattern: missing reference data is "what to do next", not corrupted
# state, so it does NOT change the doctor exit code.
# ---------------------------------------------------------------------------


def _stage_canonical_ancestry_layout(reference_root: Path, *, release: str = "v1") -> Path:
    """Stage the canonical post-fetch ancestry layout the doctor probe expects.

    Verified upstream layout (2026-05-17 real-data smoke against PGS Catalog
    v1 bundle): gnomAD-merged 1000G + HGDP callset extracts FLAT into the
    release dir — combined files keyed by reference build, no per-
    population subdirs.
    """
    ancestry_dir = reference_root / "pgs_catalog_ancestry" / release
    ancestry_dir.mkdir(parents=True)
    (ancestry_dir / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"data")
    (ancestry_dir / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"data")
    (ancestry_dir / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"data")
    return ancestry_dir


def test_doctor_reports_ancestry_ready_when_canonical_layout_staged(tmp_path: Path) -> None:
    """Canonical `pgs_catalog_ancestry/v1/{1000g,hgdp}/` → status='ready'."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    ancestry_dir = _stage_canonical_ancestry_layout(layout["reference"])

    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0
    assert "ancestry_ready" in report
    ar = report["ancestry_ready"]
    assert ar["status"] == "ready", f"expected ready, got {ar}"
    assert ar["path"] == str(ancestry_dir)


def test_doctor_reports_ancestry_partial_invC001_when_some_files_present(
    tmp_path: Path,
) -> None:
    """Some required files present, some missing → status='partial' + names which.

    INV-C001 v1.7: ancestry calibration requires the full gnomAD-merged
    1000G + HGDP callset (combined files). A partial fetch — say the
    network died mid-extract leaving a truncated tree — must surface
    explicitly so the user (or the Slice E.3 orchestrator) sees the gap
    before invoking compute. Exit code stays 0 because reference-data
    state is "what to do next", not corrupted state.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    ancestry_dir = layout["reference"] / "pgs_catalog_ancestry" / "v1"
    ancestry_dir.mkdir(parents=True)
    # Stage just the .pgen — the .pvar.zst + .psam are missing.
    (ancestry_dir / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"data")

    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0, "ancestry partial state must not flip the exit code"
    ar = report["ancestry_ready"]
    assert ar["status"] == "partial", f"expected partial, got {ar}"
    assert "GRCh38_HGDP+1kGP_ALL.pgen" in ar["present_files"]
    assert "GRCh38_HGDP+1kGP_ALL.pvar.zst" in ar["missing_files"]
    assert "GRCh38_HGDP+1kGP_ALL.psam" in ar["missing_files"]
    assert "fix" in ar and "pgs_catalog_ancestry" in ar["fix"]


def test_doctor_reports_ancestry_missing_with_install_hint(tmp_path: Path) -> None:
    """No `pgs_catalog_ancestry/` dir → status='missing' + actionable fix string."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    # reference/ is present but empty — no pgs_catalog_ancestry subtree at all.

    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0, "missing ancestry data is informational, not a hard fail"
    ar = report["ancestry_ready"]
    assert ar["status"] == "missing", f"expected missing, got {ar}"
    assert "genomeclaw refs fetch --source pgs_catalog_ancestry" in ar["fix"]


# ---------------------------------------------------------------------------
# PRS Runtime Bootstrap Phase 1 — prs_runtime_ready readiness gate.
#
# `host doctor` surfaces a new informational `prs_runtime_ready` section
# probing the toolkit image's Stage 1c contents: nextflow + java + mamba on
# PATH + the pre-warmed pgsc_calc source at /opt/pgsc_calc/main.nf. Like
# `ancestry_ready` (Plan 1 Phase 2), this is INFORMATIONAL — does not affect
# exit code.
#
# Two tests here exercise the pure-Python plumbing via a stubbed runner.
# The end-to-end image-level smoke (real `docker run` against the built
# toolkit image) lives in test_toolkit_image_prs_runtime.py and is gated on
# the `needs_prs_runtime` marker.
# ---------------------------------------------------------------------------


def test_doctor_reports_prs_runtime_ready_when_stubbed_runner_returns_versions(
    tmp_path: Path,
) -> None:
    """Stubbed `nextflow -version` / `java -version` / `mamba --version` → status='ready'.

    Doctor's `_collect_prs_runtime_ready` shells out via the injected runner;
    the stub returns canned successful output for each probe. Pre-warm marker
    file is staged at /opt/pgsc_calc/main.nf — when missing, the section
    drops to 'missing' even if all three binaries respond cleanly.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    runner = _StubRunner()
    runner.responses[("nextflow", "-version")] = (
        0,
        "      N E X T F L O W\n      version 24.10.0 build 5928\n",
        "",
    )
    runner.responses[("java", "-version")] = (
        0,
        "",
        'openjdk version "17.0.10" 2024-01-16\n',
    )
    runner.responses[("mamba", "--version")] = (0, "mamba 1.5.8\nconda 24.5.0\n", "")
    runner.responses[("test", "-f", "/opt/pgsc_calc/main.nf")] = (0, "", "")

    _, report = doctor(paths=layout, runner=runner)

    pr = report["prs_runtime_ready"]
    assert pr["status"] == "ready", f"expected ready, got {pr}"
    assert "24.10" in pr["nextflow_version"]
    assert "17" in pr["java_version"]
    assert "1.5" in pr["mamba_version"]
    assert pr["pgsc_calc_prewarm"] == "/opt/pgsc_calc/main.nf"


def test_doctor_reports_prs_runtime_missing_when_nextflow_unreachable(tmp_path: Path) -> None:
    """Stubbed `nextflow -version` returning rc≠0 → status='missing' + names what's missing.

    Exit code stays 0 — `prs_runtime_ready` is informational like
    `ancestry_ready`. The Slice E.3 orchestrator's compute-time guard is the
    actual enforcement layer; doctor surfaces the precondition so the user
    sees it before invoking compute.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    runner = _StubRunner()
    # Default stub returns (0, "", "") — i.e. command succeeded with no
    # output. Override nextflow to fail explicitly; java/mamba succeed.
    runner.responses[("nextflow", "-version")] = (127, "", "nextflow: not found\n")
    runner.responses[("java", "-version")] = (0, "", 'openjdk version "17.0.10"\n')
    runner.responses[("mamba", "--version")] = (0, "mamba 1.5.8\n", "")
    runner.responses[("test", "-f", "/opt/pgsc_calc/main.nf")] = (0, "", "")

    rc, report = doctor(paths=layout, runner=runner)

    assert rc == 0, "prs_runtime missing must not flip the exit code"
    pr = report["prs_runtime_ready"]
    assert pr["status"] == "missing", f"expected missing, got {pr}"
    assert "nextflow" in pr["missing"], f"expected nextflow in missing list, got {pr['missing']}"
    assert "fix" in pr and "toolkit image" in pr["fix"].lower()


# ---------------------------------------------------------------------------
# Slice 3 of host-mount-lifecycle — stale colima mount detection.
# ---------------------------------------------------------------------------


def _write_colima_cfg(path: Path, mounts: list[dict]) -> None:
    import yaml as _yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml.safe_dump({"mounts": mounts}, sort_keys=False))


def test_doctor_reports_stale_mount_when_drive_not_present(tmp_path: Path) -> None:
    """A colima mount pointing at a path that doesn't exist on the host is stale.

    Defends against the 2026-05-14 boot failure mode: a configured drive
    was unplugged (or renamed), so the next ``colima start`` will fail
    with ``mkdir … permission denied``. Doctor should warn before the
    user discovers this via a cryptic colima error.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    existing = tmp_path / "existing_drive"
    existing.mkdir()
    missing = tmp_path / "missing_drive"  # NOT created
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(
        cfg,
        [
            {"location": str(existing), "writable": True},
            {"location": str(missing), "writable": True},
        ],
    )

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    stale = report["stale_mounts"]
    locations = {entry["location"] for entry in stale}
    assert str(missing) in locations
    assert str(existing) not in locations


def test_doctor_no_stale_mounts_when_all_drives_present(tmp_path: Path) -> None:
    """Every configured drive exists on the host → empty stale_mounts list."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    drive1 = tmp_path / "drive1"
    drive2 = tmp_path / "drive2"
    drive1.mkdir()
    drive2.mkdir()
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(
        cfg,
        [
            {"location": str(drive1), "writable": True},
            {"location": str(drive2), "writable": True},
        ],
    )

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    assert report["stale_mounts"] == []


def test_doctor_handles_missing_colima_config_gracefully(tmp_path: Path) -> None:
    """No colima.yaml on disk → empty stale_mounts list, no crash.

    A fresh user who hasn't run ``host setup`` yet doesn't have a
    colima.yaml. Doctor must still produce a complete report.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    cfg = tmp_path / "nonexistent" / "colima.yaml"

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    assert report["stale_mounts"] == []


def test_doctor_stale_mount_entry_includes_actionable_fix_hint(tmp_path: Path) -> None:
    """Each stale-mount entry carries a ``fix`` field with a concrete next step.

    The string should mention either ``host eject`` (to remove the
    stale entry) or "plug in" (the drive). The user shouldn't have to
    figure out the resolution from a bare path.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    missing = tmp_path / "unplugged_drive"
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(cfg, [{"location": str(missing), "writable": True}])

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    assert len(report["stale_mounts"]) == 1
    entry = report["stale_mounts"][0]
    assert entry["location"] == str(missing)
    fix = entry["fix"]
    assert "host eject" in fix or "plug in" in fix.lower()


def test_doctor_stale_mounts_do_not_fail_exit_code(tmp_path: Path) -> None:
    """A stale mount is a warning, not a failure — exit stays 0 if checks pass.

    Doctor's exit code reflects critical infrastructure failure (missing
    canonical paths, write-blocked mounts). Stale colima entries are
    fixable misconfiguration, not corruption.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    missing = tmp_path / "unplugged_drive"
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(cfg, [{"location": str(missing), "writable": True}])

    rc, _report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    assert rc == 0


# ---------------------------------------------------------------------------
# PRS Input Coverage Fill Phase 1b — `prs_coverage_ready` readiness gate.
#
# `host doctor` surfaces an informational `prs_coverage_ready` section that
# probes per-sample Tier 1 caches under
# `derived/prs_coverage/<sample>/<panel>/{tier1.vcf.gz, tier1.qc.json}`. Like
# `ancestry_ready` and `prs_runtime_ready`, this is INFORMATIONAL — does not
# affect the doctor exit code. The Slice E.3 / Phase 2 compute orchestrator's
# cache-hit check at compute time is the actual enforcement layer.
# ---------------------------------------------------------------------------


import json as _json  # noqa: E402


def _stage_tier1_cache(
    derived_root: Path,
    *,
    sample_id: str = "MPNRGLQ2K",
    panel_version: str = "v1",
    include_qc_json: bool = True,
) -> Path:
    """Stage a tier1.vcf.gz + tier1.qc.json under the canonical cache layout."""
    cache_dir = derived_root / "prs_coverage" / sample_id / panel_version
    cache_dir.mkdir(parents=True)
    (cache_dir / "tier1.vcf.gz").write_bytes(b"\x1f\x8b")  # gzip magic, presence-only
    if include_qc_json:
        (cache_dir / "tier1.qc.json").write_text(
            _json.dumps(
                {
                    "sample_id": sample_id,
                    "panel_version": panel_version,
                    "source_cram_sha256": "deadbeef",
                    "total_records": 6796,
                    "schema_version": "1",
                }
            )
        )
    return cache_dir


def test_doctor_reports_prs_coverage_no_samples_when_directory_empty(
    tmp_path: Path,
) -> None:
    """`derived/` exists but no `prs_coverage/` subtree → status='no_samples'.

    A fresh install with no Tier 1 caches built yet — the user has staged
    the panel but hasn't run `genomeclaw prs prepare-coverage` against any
    sample. Informational; exit stays 0.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)

    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0
    assert "prs_coverage_ready" in report
    pc = report["prs_coverage_ready"]
    assert pc["status"] == "no_samples", f"expected no_samples, got {pc}"
    assert pc["samples"] == []
    assert "fix" in pc


def test_doctor_reports_prs_coverage_ready_when_tier1_cache_present(
    tmp_path: Path,
) -> None:
    """One sample with full tier1 cache → status='ready' + sample listed."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    _stage_tier1_cache(layout["derived"], sample_id="MPNRGLQ2K", panel_version="v1")

    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0
    pc = report["prs_coverage_ready"]
    assert pc["status"] == "ready", f"expected ready, got {pc}"
    assert len(pc["samples"]) == 1
    sample = pc["samples"][0]
    assert sample["sample_id"] == "MPNRGLQ2K"
    assert any(pv["panel_version"] == "v1" and pv["status"] == "ready" for pv in sample["panel_versions"])


def test_doctor_reports_prs_coverage_partial_when_qc_json_missing(
    tmp_path: Path,
) -> None:
    """tier1.vcf.gz present but tier1.qc.json missing → sample status='partial'.

    Catches the failure mode where a previous `prs prepare-coverage` run
    crashed between the VCF promote and the QC JSON write. Informational;
    the next `prepare-coverage` run will rebuild from the orphaned VCF.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    _stage_tier1_cache(
        layout["derived"], sample_id="MPNRGLQ2K", panel_version="v1", include_qc_json=False
    )

    rc, report = doctor(paths=layout, runner=_StubRunner())

    assert rc == 0
    pc = report["prs_coverage_ready"]
    # Whole-section status is "partial" when no sample is fully ready.
    assert pc["status"] == "partial", f"expected partial, got {pc}"
    sample = pc["samples"][0]
    assert sample["sample_id"] == "MPNRGLQ2K"
    pv = sample["panel_versions"][0]
    assert pv["status"] == "partial"
    assert pv["tier1_vcf"] is not None
    assert pv["tier1_qc_json"] is None

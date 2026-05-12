"""``genomeclaw host doctor`` — read-only diagnostic.

Doctor runs *host-native* (the shim auto-routes setup/eject/doctor
outside docker). It diagnoses the user's external-drive layout, the
setup audit log, and the colima/lima version. Output: structured dict
by default; the CLI's ``--json`` flag renders it as JSON, otherwise
text.

Doctor's checks are deliberately host-side: existence of each canonical
subdir + a host-write probe for the writable mounts (``derived`` and
``_scratch``). The in-container ``preflight`` module is the actual
enforcement layer for INV-D001 — it asserts every orchestrator sees
``/mnt/genomeclaw/{raw,reference}`` as read-only at every entry point.
Doctor is upstream of that: it answers "is the host environment laid
out correctly?", which is what the user can fix. Reporting "raw is
writable on the host" as a FAIL would be alarmist (the shim binds it
RO inside the container regardless of host perms).

Exit code: 0 iff every check is OK; 1 if any FAIL.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

# ---------------------------------------------------------------------------
# Subprocess runner injection (same shape as eject.py)
# ---------------------------------------------------------------------------


class _Runner(Protocol):
    def run(self, cmd: list[str]) -> tuple[int, str, str]: ...


class _SubprocessRunner:
    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(cmd, capture_output=True, check=False)
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


# Host-side canonical paths. ``doctor`` is shim-routed host-native (no
# docker), so it diagnoses the actual on-disk state of the user's
# external drive — which is what the user needs to fix when something
# is wrong.
_HOST_ROOT = Path("/Volumes/Genome_Work/genomeclaw")
_DEFAULT_PATHS = {
    "raw": _HOST_ROOT / "raw",
    "reference": _HOST_ROOT / "reference",
    "derived": _HOST_ROOT / "derived",
    "scratch": _HOST_ROOT / "_scratch",
}


def _probe_writable(path: Path) -> bool:
    """Attempt to create + delete a probe file; return True iff it succeeded."""
    probe = path / ".genomeclaw_doctor_probe"
    try:
        probe.touch()
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def _check_present(path: Path, label: str) -> tuple[str, str]:
    if not path.exists():
        return "FAIL", f"{label} not found at {path} — run `genomeclaw host setup`"
    if not path.is_dir():
        return "FAIL", f"{label} at {path} is not a directory"
    return "OK", ""


def _check_host_writable(path: Path, label: str) -> tuple[str, str]:
    status, msg = _check_present(path, label)
    if status == "FAIL":
        return status, msg
    if not _probe_writable(path):
        return (
            "FAIL",
            f"{label} at {path} is not writable on the host — pipeline "
            "outputs would be blocked. Re-run `genomeclaw host setup` "
            "or check filesystem permissions.",
        )
    return "OK", ""


def _run_checks(paths: dict[str, Path]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    status, msg = _check_present(paths["raw"], "raw")
    checks.append({"name": "raw_present", "status": status, "message": msg})

    status, msg = _check_present(paths["reference"], "reference")
    checks.append({"name": "reference_present", "status": status, "message": msg})

    status, msg = _check_host_writable(paths["derived"], "derived")
    checks.append({"name": "derived_writable", "status": status, "message": msg})

    status, msg = _check_host_writable(paths["scratch"], "_scratch")
    checks.append({"name": "scratch_writable", "status": status, "message": msg})

    return checks


def _collect_setup_log(scratch_dir: Path) -> dict[str, Any]:
    """Surface the most recent ``setup_completed`` event's payload."""
    log_path = scratch_dir / "setup.log"
    if not log_path.exists():
        return {"found": False}

    last_completed: dict[str, Any] | None = None
    last_started: dict[str, Any] | None = None
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("step") == "setup_completed":
            last_completed = event
        elif event.get("step") == "setup_started":
            last_started = event

    if last_completed is not None:
        payload = last_completed.get("payload", {})
        return {
            "found": True,
            "last_completed_at": payload.get("completed_at"),
            "toolkit_version": payload.get("toolkit_version"),
            "target_partition": payload.get("target_partition"),
        }
    if last_started is not None:
        payload = last_started.get("payload", {})
        return {
            "found": True,
            "incomplete": True,
            "last_started_at": payload.get("started_at"),
            "toolkit_version": payload.get("toolkit_version"),
        }
    return {"found": True, "no_events": True}


def _collect_colima(runner: _Runner) -> dict[str, Any]:
    """Read colima version + status; tolerate not-installed gracefully."""
    out: dict[str, Any] = {"installed": False}

    rc, stdout, _ = runner.run(["colima", "version"])
    if rc == 0:
        out["installed"] = True
        m = re.search(r"colima version\s+(\S+)", stdout)
        if m:
            out["version"] = m.group(1)

    rc, stdout, stderr = runner.run(["colima", "status"])
    combined = (stdout + stderr).lower()
    if "is running" in combined:
        out["status"] = "running"
    elif "is not running" in combined:
        out["status"] = "stopped"
    else:
        out["status"] = "unknown"
    return out


# ---------------------------------------------------------------------------
# Pipeline readiness — references / raw sample / derived runs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReferenceState:
    """Per-source classification of ``reference/<source>/<release>/``."""

    source: str
    expected_release: str
    on_disk_release: str | None
    status: Literal["OK", "partial", "missing"]
    present_files: tuple[str, ...]
    missing_files: tuple[str, ...]


@dataclass(frozen=True)
class _RawSampleState:
    """Classification of the staged Nebula deliverable under ``raw/``."""

    staged: bool
    sample_id: str | None
    files: tuple[str, ...]


@dataclass(frozen=True)
class _DerivedRunState:
    """Classification of one ``derived/<run-id>/`` directory."""

    run_id: str
    sample_id: str | None
    started_at: str | None
    stage: Literal["ingested", "normalized", "annotated", "materialized", "unknown"]


# Step → stage label. ``vcfanno`` and ``vep`` both classify as
# ``annotated`` since they're alternate / chained annotation engines.
# ``bcftools-stats`` + ``mosdepth-coverage`` are auxiliary QC steps —
# they don't advance the pipeline, so they're skipped at classification
# time (a run with only ``ingest`` and ``bcftools-stats`` is still just
# ``ingested``).
_STEP_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("materialize", "materialized"),
    ("vep", "annotated"),
    ("vcfanno", "annotated"),
    ("normalize", "normalized"),
    ("ingest", "ingested"),
)
_AUXILIARY_STEPS: frozenset[str] = frozenset(("bcftools-stats", "mosdepth-coverage"))


def _classify_run_stage(step_names: list[str]) -> str:
    """Pick the highest-precedence step in the trail; skip QC auxiliaries."""
    seen = {s for s in step_names if s not in _AUXILIARY_STEPS}
    for step_name, label in _STEP_PRECEDENCE:
        if step_name in seen:
            return label
    return "unknown"


def _expected_files_under_release_dir(
    source: str, layout: Any, chroms: tuple[str, ...] | None
) -> list[str]:
    """Filenames (relative to the release dir) a complete fetch produces.

    Walks the fetch layout's ``files`` (flat) + ``chrom_files`` (templated
    against ``chroms``), appending ``.md5`` for any file declaring a
    sidecar in either upstream MD5 mode. Adds source-specific
    post-fetch extras (currently grch38's ``.fai`` + ``.gzi``) so the
    classification reflects the full on-disk state a successful fetch
    leaves behind, not just the bytes that came over the wire.
    """
    files: list[str] = []
    subdir = f"{layout.output_subdir}/" if layout.output_subdir else ""

    def _add(file_obj: Any) -> None:
        files.append(subdir + file_obj.output_filename)
        if file_obj.md5_relpath or file_obj.md5_checksums_relpath:
            files.append(subdir + file_obj.output_filename + ".md5")

    for f in layout.files:
        _add(f)

    if layout.is_multi_file and chroms:
        for c in chroms:
            for tmpl in layout.chrom_files:
                _add(tmpl.for_chrom(c))

    # Source-specific post-fetch extras. Kept inline rather than
    # adding a new field to ``_SourceLayout`` — there's only one
    # source that needs it today.
    if source == "grch38":
        files.append("grch38.fa.gz.fai")
        files.append("grch38.fa.gz.gzi")

    return files


def _collect_references(
    *,
    reference_root: Path,
    release_set: Any = None,
) -> list[_ReferenceState]:
    """Classify each source in the active release set vs. on-disk state.

    ``release_set`` is the ``ReleaseSet`` to compare against; defaults
    to the bundled ``"default"`` set when callers don't override (tests
    pass a synthetic set to avoid staging the full 24-chrom gnomAD
    file list).
    """
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS
    from genomeclaw_toolkit.prep.release_sets import load_release_set

    rs = release_set if release_set is not None else load_release_set()

    states: list[_ReferenceState] = []
    for entry in rs.sources:
        layout = _LAYOUTS.get(entry.source)
        if layout is None:
            # Release set references a source the fetcher doesn't know
            # about. Surface as missing rather than crashing — the user
            # can fix this by upgrading the toolkit or bumping the set.
            states.append(
                _ReferenceState(
                    source=entry.source,
                    expected_release=entry.release,
                    on_disk_release=None,
                    status="missing",
                    present_files=(),
                    missing_files=(),
                )
            )
            continue

        release_dir = reference_root / entry.source / entry.release
        if not release_dir.is_dir():
            states.append(
                _ReferenceState(
                    source=entry.source,
                    expected_release=entry.release,
                    on_disk_release=None,
                    status="missing",
                    present_files=(),
                    missing_files=(),
                )
            )
            continue

        expected = _expected_files_under_release_dir(entry.source, layout, entry.chroms)
        present: list[str] = []
        missing: list[str] = []
        for rel in expected:
            if (release_dir / rel).exists():
                present.append(rel)
            else:
                missing.append(rel)

        status: Literal["OK", "partial", "missing"] = "OK" if not missing else "partial"
        states.append(
            _ReferenceState(
                source=entry.source,
                expected_release=entry.release,
                on_disk_release=entry.release,
                status=status,
                present_files=tuple(present),
                missing_files=tuple(missing),
            )
        )

    return states


def _collect_raw_sample(*, raw_root: Path) -> _RawSampleState:
    """Walk ``raw/`` looking for a staged Nebula deliverable.

    Treats the lexicographically-first sample subdir as the "active"
    sample (matches setup's ``_inspect_nebula`` logic). An empty
    sample dir doesn't count as staged.
    """
    if not raw_root.is_dir():
        return _RawSampleState(staged=False, sample_id=None, files=())
    sample_dirs = sorted(p for p in raw_root.iterdir() if p.is_dir())
    if not sample_dirs:
        return _RawSampleState(staged=False, sample_id=None, files=())
    first = sample_dirs[0]
    files = tuple(sorted(p.name for p in first.iterdir() if p.is_file()))
    if not files:
        return _RawSampleState(staged=False, sample_id=None, files=())
    return _RawSampleState(staged=True, sample_id=first.name, files=files)


def _collect_derived_runs(*, derived_root: Path) -> list[_DerivedRunState]:
    """Walk ``derived/`` and classify each run by its provenance trail."""
    if not derived_root.is_dir():
        return []
    runs: list[_DerivedRunState] = []
    for entry in derived_root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            # Not a real run dir (could be CURRENT symlink target, a
            # stray scratch leftover, etc.). Skip rather than mislabel.
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        sample_id = manifest.get("sample_id")
        started_at = manifest.get("created_at")

        stage = "unknown"
        prov_path = entry / "provenance.json"
        if prov_path.is_file():
            try:
                prov = json.loads(prov_path.read_text())
                step_names = [s.get("step", "") for s in prov.get("steps", [])]
                stage = _classify_run_stage(step_names)
            except (json.JSONDecodeError, OSError):
                stage = "unknown"

        runs.append(
            _DerivedRunState(
                run_id=entry.name,
                sample_id=sample_id,
                started_at=started_at,
                stage=stage,  # type: ignore[arg-type]
            )
        )

    # Newest first — the most actionable run is usually the latest.
    runs.sort(key=lambda r: r.started_at or "", reverse=True)
    return runs


def doctor(
    *,
    paths: dict[str, Path] | None = None,
    runner: _Runner | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run host-side layout checks + collect setup-log + colima status +
    reference / raw-sample / derived-run state.

    Returns ``(exit_code, report_dict)``. Exit 0 iff every infrastructure
    check passes — missing reference data / no raw sample / no derived
    runs do **not** change the exit code (they're "what to do next"
    signals, not corrupted-state alarms).
    """
    paths = paths or _DEFAULT_PATHS
    runner = runner or _SubprocessRunner()

    checks = _run_checks(paths)
    any_failed = any(c["status"] == "FAIL" for c in checks)

    setup_log = _collect_setup_log(paths["scratch"])
    colima = _collect_colima(runner)

    # Pipeline-readiness sections. These never affect the exit code; if
    # release_sets can't load (toolkit packaging bug, etc.) we still
    # want the host-layout part of doctor to be useful.
    references_section: dict[str, Any]
    try:
        ref_states = _collect_references(reference_root=paths["reference"])
        from genomeclaw_toolkit.prep.release_sets import load_release_set

        rs_name = load_release_set().name
        references_section = {
            "release_set": rs_name,
            "sources": [asdict(s) for s in ref_states],
        }
    except Exception as exc:  # pragma: no cover — defensive
        references_section = {"release_set": None, "sources": [], "error": str(exc)}

    raw_sample = asdict(_collect_raw_sample(raw_root=paths["raw"]))
    derived_runs = [asdict(r) for r in _collect_derived_runs(derived_root=paths["derived"])]

    report = {
        "checks": checks,
        "setup_log": setup_log,
        "colima": colima,
        "paths": {k: str(v) for k, v in paths.items()},
        "references": references_section,
        "raw_sample": raw_sample,
        "derived_runs": derived_runs,
    }
    return (1 if any_failed else 0, report)


__all__ = ["doctor"]

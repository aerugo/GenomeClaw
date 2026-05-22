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


def _collect_prs_runtime_ready(runner: _Runner) -> dict[str, Any]:
    """Probe the toolkit image's PRS runtime stack. Informational only.

    PRS Runtime Bootstrap Phase 1 ships a new Stage 1c that bakes Nextflow +
    JRE 17 + mamba + the pre-warmed ``pgsc_calc`` pipeline source into the
    toolkit image. This section confirms those four pieces are reachable
    inside the runtime container so the user sees the gap before invoking
    ``genomeclaw pipeline pgs-compute``.

    Does NOT affect the doctor exit code — same informational pattern as
    ``ancestry_ready``. The Slice E.3 orchestrator's compute-time guard is
    the actual enforcement layer; doctor surfaces the precondition.

    Probes shell out via the injected ``runner`` (tests stub it; production
    uses ``subprocess``). Each probe is rc==0 to count as present; the
    captured stdout/stderr provides version-string evidence.
    """
    probes: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("nextflow", ("nextflow", "-version")),
        ("java", ("java", "-version")),
        ("mamba", ("mamba", "--version")),
    )

    versions: dict[str, str] = {}
    missing: list[str] = []
    for label, cmd in probes:
        rc, stdout, stderr = runner.run(list(cmd))
        if rc != 0:
            missing.append(label)
            continue
        # ``java -version`` writes to stderr by convention; nextflow + mamba
        # write to stdout. Store the full captured output; downstream
        # consumers parse what they need (nextflow's first line is a banner;
        # the version is on line 2).
        versions[label] = (stdout.strip() or stderr.strip()).strip()

    # Pre-warmed pgsc_calc pipeline source — single file probe at the
    # canonical bake-in path.
    pgsc_calc_marker = "/opt/pgsc_calc/main.nf"
    rc, _stdout, _stderr = runner.run(["test", "-f", pgsc_calc_marker])
    pgsc_calc_prewarm: str | None = pgsc_calc_marker if rc == 0 else None
    if pgsc_calc_prewarm is None:
        missing.append("pgsc_calc")

    if not missing:
        return {
            "status": "ready",
            "nextflow_version": versions["nextflow"],
            "java_version": versions["java"],
            "mamba_version": versions["mamba"],
            "pgsc_calc_prewarm": pgsc_calc_prewarm,
        }

    return {
        "status": "missing",
        "missing": tuple(missing),
        "nextflow_version": versions.get("nextflow"),
        "java_version": versions.get("java"),
        "mamba_version": versions.get("mamba"),
        "pgsc_calc_prewarm": pgsc_calc_prewarm,
        "fix": (
            "Rebuild the genomeclaw/toolkit image with the PRS runtime stage "
            "(see docs/plans/active/prs-runtime-bootstrap/) — Nextflow + JRE 17 "
            "+ mamba + pre-warmed pgsc_calc source must be on the in-container PATH."
        ),
    }


def _collect_ancestry_ready(reference_root: Path) -> dict[str, Any]:
    """Probe the canonical PGS Catalog ancestry layout. Informational only.

    Per ``INV-C001`` v1.7 ``pgsc_calc --run_ancestry`` requires BOTH 1000G
    and HGDP panels. A partial fetch (one subtree but not the other) would
    silently degrade ancestry calibration; this section surfaces the gap
    explicitly so the user (or the Slice E.3 orchestrator) sees it before
    invoking compute.

    Does NOT affect the doctor exit code — matches the ``references_section``
    pattern where missing reference data is "what to do next", not corrupted
    state. The Slice E.3 orchestrator + the existing
    ``_check_ancestry_reference`` guard at compute-time are the actual
    enforcement layer for ``INV-C001`` v1.7.
    """
    from genomeclaw_toolkit.prep.pgs import (
        _PGS_ANCESTRY_PRESENCE_FILES,
        _ancestry_reference_dir,
    )

    ancestry_dir = _ancestry_reference_dir(reference_root)
    # Verified upstream layout (2026-05-17): bundle extracts FLAT, no per-
    # population subdirs. Probe the three combined files pgsc_calc reads
    # via --run_ancestry. File presence (not directory existence) catches
    # the "user made the dir manually but never extracted" failure mode.
    present_files: list[str] = []
    missing_files: list[str] = []
    for relpath in _PGS_ANCESTRY_PRESENCE_FILES:
        if (ancestry_dir / relpath).exists():
            present_files.append(relpath)
        else:
            missing_files.append(relpath)

    if not missing_files:
        return {
            "status": "ready",
            "path": str(ancestry_dir),
            "present_files": tuple(present_files),
        }

    fix = "Install with `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1`."
    if present_files:
        return {
            "status": "partial",
            "path": str(ancestry_dir),
            "present_files": tuple(present_files),
            "missing_files": tuple(missing_files),
            "fix": fix,
        }
    return {
        "status": "missing",
        "path": str(ancestry_dir),
        "missing_files": tuple(missing_files),
        "fix": fix,
    }


def _collect_pgs_scorefiles_ready(reference_root: Path) -> dict[str, Any]:
    """Probe the canonical PGS Catalog scorefile layout vs. release-set expectation.

    Phase 5a — for every ``pgs_scorefile`` entry in the default release set,
    verify the file is staged at
    ``reference/pgs_scorefile/<PGS_ID>/<PGS_ID>_hmPOS_GRCh38.txt.gz``.

    Informational only — like ``ancestry_ready`` / ``prs_runtime_ready``,
    a missing scorefile doesn't change the doctor exit code. The Phase 5
    smoke driver's pre-flight + the agent's compute-time guard are the
    actual enforcement layers; doctor surfaces the gap so the user sees
    it before invoking compute.
    """
    expected: list[str] = []
    try:
        from genomeclaw_toolkit.prep.release_sets import load_release_set

        release_set = load_release_set()
        expected = [
            entry.release for entry in release_set.sources if entry.source == "pgs_scorefile"
        ]
    except Exception:  # pragma: no cover — defensive
        expected = []

    present: list[str] = []
    missing: list[str] = []
    for pgs_id in expected:
        target = (
            reference_root / "pgs_scorefile" / pgs_id / f"{pgs_id}_hmPOS_GRCh38.txt.gz"
        )
        if target.exists():
            present.append(pgs_id)
        else:
            missing.append(pgs_id)

    fix = (
        "Install with `genomeclaw refs fetch --source pgs_scorefile --release <PGS_ID>` "
        "for individual scoring files, or `genomeclaw host setup --fetch-all` to stage "
        "every default-release-set entry."
    )

    if not expected:
        # No scorefiles configured in the release set (unusual; the default
        # toml lists at least PGS000018 post-Phase-5a). Treat as informational
        # rather than as an error — a custom release set may legitimately omit.
        return {
            "status": "no_scorefiles_configured",
            "release_set_pgs_ids": [],
            "present_pgs_ids": [],
            "missing_pgs_ids": [],
        }
    if not missing:
        return {
            "status": "ready",
            "release_set_pgs_ids": tuple(expected),
            "present_pgs_ids": tuple(present),
            "missing_pgs_ids": (),
        }
    if present:
        return {
            "status": "partial",
            "release_set_pgs_ids": tuple(expected),
            "present_pgs_ids": tuple(present),
            "missing_pgs_ids": tuple(missing),
            "fix": fix,
        }
    return {
        "status": "missing",
        "release_set_pgs_ids": tuple(expected),
        "present_pgs_ids": (),
        "missing_pgs_ids": tuple(missing),
        "fix": fix,
    }


def _collect_prs_coverage_ready(derived_root: Path) -> dict[str, Any]:
    """Probe per-sample Tier 1 caches under ``derived/prs_coverage/``. Informational.

    For each sample directory found under ``derived/prs_coverage/<sample>/``,
    walks the per-panel subdirectories and reports the presence of the
    canonical tier1 outputs (``tier1.vcf.gz`` + ``tier1.qc.json``). A
    panel-version is ``ready`` when both files exist, ``partial`` when only
    one does.

    Whole-section status:

    - ``no_samples`` — no ``prs_coverage/`` dir, or the dir is empty.
    - ``ready`` — at least one sample × panel pair is fully cached.
    - ``partial`` — at least one sample is present but no sample × panel
      pair is fully ready (e.g. every cache is mid-build).

    Does NOT affect the doctor exit code — matches ``ancestry_ready`` /
    ``prs_runtime_ready`` discipline. The Phase 2 compute orchestrator's
    cache-hit check at compute time is the actual enforcement layer.
    """
    coverage_root = derived_root / "prs_coverage"
    fix = (
        "Build a Tier 1 cache with `genomeclaw prs prepare-coverage --sample <id>` "
        "(needs the panel staged via `genomeclaw refs fetch --source pgs_catalog_ancestry`)."
    )

    if not coverage_root.exists():
        return {"status": "no_samples", "samples": [], "fix": fix}

    samples_out: list[dict[str, Any]] = []
    any_ready = False
    any_partial = False
    sample_dirs = sorted(p for p in coverage_root.iterdir() if p.is_dir())
    for sample_dir in sample_dirs:
        panel_versions: list[dict[str, Any]] = []
        panel_dirs = sorted(p for p in sample_dir.iterdir() if p.is_dir())
        for panel_dir in panel_dirs:
            tier1_vcf = panel_dir / "tier1.vcf.gz"
            tier1_qc = panel_dir / "tier1.qc.json"
            vcf_present = tier1_vcf.exists()
            qc_present = tier1_qc.exists()
            if vcf_present and qc_present:
                status = "ready"
                any_ready = True
            else:
                status = "partial"
                any_partial = True
            panel_versions.append(
                {
                    "panel_version": panel_dir.name,
                    "tier1_vcf": str(tier1_vcf) if vcf_present else None,
                    "tier1_qc_json": str(tier1_qc) if qc_present else None,
                    "status": status,
                }
            )
        samples_out.append(
            {"sample_id": sample_dir.name, "panel_versions": panel_versions}
        )

    if not samples_out:
        return {"status": "no_samples", "samples": [], "fix": fix}

    section_status = "ready" if any_ready else "partial" if any_partial else "no_samples"
    out: dict[str, Any] = {"status": section_status, "samples": samples_out}
    if section_status != "ready":
        out["fix"] = fix
    return out


_DEFAULT_COLIMA_CONFIG = Path.home() / ".colima" / "default" / "colima.yaml"


def _collect_stale_colima_mounts(config_path: Path) -> list[dict[str, str]]:
    """Return colima mount entries whose ``location`` doesn't exist on the host.

    Slice 3 of [host-mount-lifecycle](../../../../docs/plans/active/host-mount-lifecycle/development-plan.md):
    a stale mount (configured drive that's been unplugged or renamed)
    causes ``colima start`` to fail with ``mkdir … permission denied``.
    Surfacing this in doctor's read-only report lets the user fix it
    before the next colima boot.

    Each returned entry has ``location`` (the stale path) and ``fix``
    (an actionable next-step string). Empty list when no config exists
    or every configured mount path is present.
    """
    if not config_path.exists():
        return []
    try:
        import yaml

        loaded = yaml.safe_load(config_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(loaded, dict):
        return []
    mounts = loaded.get("mounts") or []

    stale: list[dict[str, str]] = []
    for entry in mounts:
        if not isinstance(entry, dict):
            continue
        location = entry.get("location")
        if not isinstance(location, str):
            continue
        # Trailing-slash insensitive existence check.
        candidate = Path(location.rstrip("/") or "/")
        if candidate.exists():
            continue
        stale.append(
            {
                "location": location,
                "fix": (
                    f"Plug in the drive at {location}, OR run "
                    f"`bin/genomeclaw host eject {location}` to remove the stale entry."
                ),
            }
        )
    return stale


def _collect_colima_mount_visible(raw_dir: Path, runner: _Runner) -> dict[str, Any]:
    """Probe whether Colima's VM can bind-mount the canonical raw dir.

    prs-smoke-resilience Phase 1 — closes the L4-at-startup brittleness
    from the v22 ledger (v22h #2): host-side sees the drive, but Colima
    VM's virtiofs view is stale (`bad file descriptor` / `mkdir: file
    exists`). The smoke driver gates on this BEFORE INV-D001 pre-snapshot
    so future iterations fail in ≤30s with an actionable hint instead of
    after a futile docker run cascade.

    Probe: ``docker run --rm -v <raw_dir>:/probe alpine test -d /probe``.
    Informational only (doesn't change doctor exit code); the smoke
    driver's pre-flight gate is the enforcement layer.
    """
    rc, _stdout, _stderr = runner.run(
        ["docker", "run", "--rm", "-v", f"{raw_dir}:/probe", "alpine", "test", "-d", "/probe"]
    )
    if rc == 0:
        return {
            "status": "visible",
            "probed_path": str(raw_dir),
        }
    return {
        "status": "broken",
        "probed_path": str(raw_dir),
        "fix": (
            "Colima VM cannot bind-mount the raw dir. Run: "
            "`colima stop && colima start --mount /Volumes/Genome_Work:w` "
            "(or whatever drive root your `host setup` chose) — the VM's "
            "virtiofs view of the host bind is stale and needs a restart."
        ),
    }


def _collect_external_drive_readable(raw_dir: Path) -> dict[str, Any]:
    """Probe whether the external drive's raw dir is host-side readable.

    prs-smoke-resilience Phase 1 — closes the L4-at-startup brittleness
    from the v22 ledger (v22h #1): drive unmounted at smoke launch
    surfaces as ``sha256sum: Device not configured``. This field surfaces
    it earlier, in the readable structural shape the smoke driver's gate
    checks.

    Probe: ``raw_dir.exists() and raw_dir.is_dir() and bool(list(raw_dir.iterdir())) or
    raw_dir.exists()`` — directory exists + accessible. Empty-but-readable
    counts as readable; the smoke driver is responsible for sample-existence
    checks separately.
    """
    if not raw_dir.exists():
        return {
            "status": "unreadable",
            "probed_path": str(raw_dir),
            "fix": (
                "External drive not mounted (raw dir missing). Plug in the "
                "drive + confirm it appears under `/Volumes/`, then verify "
                "with `ls /Volumes/Genome_Work/genomeclaw/raw/`."
            ),
        }
    try:
        # Touch the directory to confirm it's not a stale FD.
        list(raw_dir.iterdir())
    except OSError as exc:
        return {
            "status": "unreadable",
            "probed_path": str(raw_dir),
            "error": str(exc),
            "fix": (
                "External drive read failed mid-probe (Device not configured / "
                "I/O error). Unmount + remount the drive, then re-run the "
                "smoke."
            ),
        }
    return {
        "status": "readable",
        "probed_path": str(raw_dir),
    }


def _collect_leftover_smoke_containers(runner: _Runner) -> dict[str, Any]:
    """List docker containers labeled ``genomeclaw-smoke`` left from prior runs.

    prs-smoke-resilience Phase 1 — closes the L5-zombie-container
    brittleness from the v22 ledger (v22e + v22g): pgsc_calc / Nextflow
    sibling containers stayed running after the parent toolkit container
    died; the next smoke conflicted on the same work-dir + on container
    names. Phase 2 will auto-stop these; for now the doctor field
    surfaces them so the user can `docker stop` manually.

    Informational only (doesn't change doctor exit code). The smoke
    driver's pre-flight gate (Phase 1.3) reads this and either
    auto-cleans (default) or aborts with a list.
    """
    rc, stdout, _stderr = runner.run(
        ["docker", "ps", "-a", "--filter", "label=genomeclaw-smoke", "--format", "{{.ID}}"]
    )
    if rc != 0:
        # Docker daemon unreachable. Be conservative — say "unknown".
        return {
            "status": "unknown",
            "container_ids": [],
            "fix": "Docker daemon unreachable; ensure Colima is running before launching a smoke.",
        }
    ids = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not ids:
        return {"status": "clean", "container_ids": []}
    return {
        "status": "leftover",
        "container_ids": ids,
        "fix": (
            f"Stop leftover smoke containers before launching a new smoke: "
            f"`docker stop {' '.join(ids)}` "
            f"(or wait for prs-smoke-resilience Phase 2's auto-cleanup to land)."
        ),
    }


def doctor(
    *,
    paths: dict[str, Path] | None = None,
    runner: _Runner | None = None,
    colima_config_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run host-side layout checks + collect setup-log + colima status +
    reference / raw-sample / derived-run state + stale-mount warnings.

    Returns ``(exit_code, report_dict)``. Exit 0 iff every infrastructure
    check passes — missing reference data / no raw sample / no derived
    runs / stale colima mount entries do **not** change the exit code
    (they're "what to do next" signals, not corrupted-state alarms).

    Args:
        paths: Canonical-layout overrides (tests). Defaults to
            :data:`_DEFAULT_PATHS`.
        runner: Subprocess runner injection point (tests).
        colima_config_path: Override path to ``colima.yaml`` for the
            stale-mount check (Slice 3 of host-mount-lifecycle). Defaults
            to ``~/.colima/default/colima.yaml``.
    """
    paths = paths or _DEFAULT_PATHS
    runner = runner or _SubprocessRunner()
    if colima_config_path is None:
        colima_config_path = _DEFAULT_COLIMA_CONFIG

    checks = _run_checks(paths)
    any_failed = any(c["status"] == "FAIL" for c in checks)

    setup_log = _collect_setup_log(paths["scratch"])
    colima = _collect_colima(runner)
    stale_mounts = _collect_stale_colima_mounts(colima_config_path)

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
    ancestry_ready = _collect_ancestry_ready(paths["reference"])
    pgs_scorefiles_ready = _collect_pgs_scorefiles_ready(paths["reference"])
    prs_runtime_ready = _collect_prs_runtime_ready(runner)
    prs_coverage_ready = _collect_prs_coverage_ready(paths["derived"])
    # prs-smoke-resilience Phase 1 readiness probes (informational; gated by
    # the smoke driver's pre-flight check before INV-D001 pre-snapshot).
    colima_mount_visible = _collect_colima_mount_visible(paths["raw"], runner)
    external_drive_readable = _collect_external_drive_readable(paths["raw"])
    leftover_genomeclaw_containers = _collect_leftover_smoke_containers(runner)

    report = {
        "checks": checks,
        "setup_log": setup_log,
        "colima": colima,
        "stale_mounts": stale_mounts,
        "paths": {k: str(v) for k, v in paths.items()},
        "references": references_section,
        "ancestry_ready": ancestry_ready,
        "pgs_scorefiles_ready": pgs_scorefiles_ready,
        "prs_runtime_ready": prs_runtime_ready,
        "prs_coverage_ready": prs_coverage_ready,
        "colima_mount_visible": colima_mount_visible,
        "external_drive_readable": external_drive_readable,
        "leftover_genomeclaw_containers": leftover_genomeclaw_containers,
        "raw_sample": raw_sample,
        "derived_runs": derived_runs,
    }
    return (1 if any_failed else 0, report)


__all__ = ["doctor"]

"""`INV-D006` — `host doctor` warns when colima mounts don't cover the derived dir.

Onboard-persistent-agent-fix Phase 3 — closes the operator-visible failure
mode where the docker-wrapped `bin/genomeclaw host service` silently
returns `no_active_run` because colima's `mounts:` list doesn't include
the operator's derived directory. The doctor surfaces this as a warning
(non-blocking, doesn't change exit code) with both fixes named:
`bin/genomeclaw host setup` (to add the mount) OR `GENOMECLAW_NATIVE=1`
(to run the host service natively, bypassing the docker mount altogether).

Companion to the existing `_collect_stale_colima_mounts` check — same
colima.yaml read, complementary concern (stale = path-was-there-and-gone;
uncovered = path-is-here-but-not-shared).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as _yaml


def _make_layout(tmp_path: Path) -> dict[str, Path]:
    """Synthesise the four canonical mounts under tmp_path.

    Mirrors `tests/integration/test_doctor.py::_make_layout`.
    """
    raw = tmp_path / "raw"
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    scratch = tmp_path / "scratch"
    for d in (raw, reference, derived, scratch):
        d.mkdir()
    return {"raw": raw, "reference": reference, "derived": derived, "scratch": scratch}


def _write_colima_cfg(path: Path, mounts: list[dict] | None) -> None:
    """Write a colima.yaml. `None` means write `mounts: []`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"mounts": mounts if mounts is not None else []}
    path.write_text(_yaml.safe_dump(body, sort_keys=False))


class _StubRunner:
    """Minimal runner that always returns rc=0; mirrors test_doctor.py."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        self.calls.append(tuple(cmd))
        return (0, "", "")


def test_invD006_doctor_warns_when_colima_mounts_empty_and_derived_uncovered(
    tmp_path: Path,
) -> None:
    """`mounts: []` + derived on a path not covered → warning."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(cfg, [])

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    section = report.get("colima_mounts_cover_derived")
    assert section is not None, (
        "report.colima_mounts_cover_derived section missing entirely; "
        "Phase 3's wiring is incomplete."
    )
    assert section["status"] == "uncovered", (
        f"expected status='uncovered' when mounts:[] + derived not in $HOME; "
        f"got {section!r}"
    )
    assert "host setup" in section["fix"]
    assert "GENOMECLAW_NATIVE=1" in section["fix"]


def test_invD006_doctor_no_warning_when_mounts_cover_derived(tmp_path: Path) -> None:
    """A mount covering the derived dir → status='covers', no warning."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    # Mount the parent of the derived dir — derived is under it.
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(cfg, [{"location": str(tmp_path), "writable": True}])

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    section = report["colima_mounts_cover_derived"]
    assert section["status"] == "covers", (
        f"expected status='covers' when mount covers derived; got {section!r}"
    )
    # Covers-case must NOT include a `fix` (no remediation needed).
    assert "fix" not in section


def test_invD006_doctor_warns_when_mounts_populated_but_dont_cover(
    tmp_path: Path,
) -> None:
    """Mounts present but pointing elsewhere → warning."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(cfg, [{"location": str(elsewhere), "writable": True}])

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    section = report["colima_mounts_cover_derived"]
    assert section["status"] == "uncovered", (
        f"expected status='uncovered' when mounts present but don't cover derived; "
        f"got {section!r}"
    )


def test_invD006_doctor_no_warning_when_colima_config_absent(tmp_path: Path) -> None:
    """No colima.yaml → status='no_config' (different failure mode's territory).

    The existing stale-mount check handles the "configured-then-gone" shape.
    A fresh host that hasn't run `host setup` yet has no yaml at all; this
    check returns a structurally distinct status so the doctor renderer
    can skip noise for the fresh-host case.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    cfg = tmp_path / "nonexistent" / "colima.yaml"

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    section = report["colima_mounts_cover_derived"]
    assert section["status"] == "no_config", (
        f"expected status='no_config' when colima.yaml absent; got {section!r}"
    )
    assert "fix" not in section


def test_invD006_doctor_exit_code_is_zero_when_only_finding_is_this_warning(
    tmp_path: Path,
) -> None:
    """Warning is non-blocking — exit 0 when nothing else is wrong.

    Matches the existing stale-mount precedent: warnings inform but don't
    fail the exit code.
    """
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    cfg = tmp_path / "colima.yaml"
    _write_colima_cfg(cfg, [])  # warning will fire

    rc, _report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    assert rc == 0, (
        f"doctor exit code {rc}; expected 0 (this warning is non-blocking)"
    )


def test_invD006_doctor_handles_yaml_with_quoted_paths_and_trailing_slashes(
    tmp_path: Path,
) -> None:
    """Mount paths with trailing slashes or quoted forms still match correctly."""
    from genomeclaw_toolkit.prep.doctor import doctor

    layout = _make_layout(tmp_path)
    cfg = tmp_path / "colima.yaml"
    # yaml.safe_dump strips quotes but keeps trailing slashes if present in the value.
    _write_colima_cfg(cfg, [{"location": str(tmp_path) + "/", "writable": True}])

    _rc, report = doctor(paths=layout, runner=_StubRunner(), colima_config_path=cfg)
    section = report["colima_mounts_cover_derived"]
    assert section["status"] == "covers", (
        f"trailing-slash mount path should still cover derived; got {section!r}"
    )

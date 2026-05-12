"""Smart-setup — end-to-end integration tests via FakePlatform.

Tests the dispatch + action-handler wiring without invoking real
``diskutil`` / ``colima`` shellouts. Each test stages a synthetic
``SystemState`` on-disk + via a FakePlatform that records every method
call, then asserts the post-dispatch on-disk + side-effect shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

import pytest

from genomeclaw_toolkit.prep.setup._types import DriveIdentity, Volume


@dataclass
class _SpyPlatform:
    """Records every Platform-method call; returns canned values."""

    volumes: list[Volume]
    colima_status_value: str = "running"
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)

    def _record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))

    def list_volumes(self) -> list[Volume]:
        self._record("list_volumes")
        return list(self.volumes)

    def colima_status(self) -> str:
        self._record("colima_status")
        return self.colima_status_value

    def colima_stop(self) -> None:
        self._record("colima_stop")
        self.colima_status_value = "stopped"

    def colima_start(self) -> None:
        self._record("colima_start")
        self.colima_status_value = "running"

    # Stubs for unused Protocol methods.
    def read_drive_identity(self, volume: Volume) -> DriveIdentity:
        raise NotImplementedError

    def bcftools_view_header(self, vcf: Path) -> tuple[str, str]:
        raise NotImplementedError

    def unmount_disk(self, parent_disk: str) -> None:
        raise NotImplementedError

    def partition_disk_apfs(self, parent_disk: str, label: str) -> Path:
        raise NotImplementedError

    def verify_mounts_via_shim(self, target_root: Path) -> None:
        raise NotImplementedError

    def copy_file_with_sha(self, src: Path, dst: Path) -> tuple[str, str]:
        raise NotImplementedError


def _make_volume(name: str, mount_point: str, filesystem: str = "apfs") -> Volume:
    return Volume(
        name=name,
        mount_point=mount_point,
        size_bytes=2_000_000_000_000,
        parent_disk="/dev/disk4",
        filesystem=filesystem,
        is_system_disk=False,
    )


def _stage_canonical_layout(mountpoint: Path, *, with_nebula: bool = True) -> None:
    root = mountpoint / "genomeclaw"
    for sub in ("raw", "reference", "derived", "_scratch"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if with_nebula:
        sample = root / "raw" / "MPNRGLQ2K"
        sample.mkdir(parents=True, exist_ok=True)
        (sample / "MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz").write_bytes(b"stub")


def _write_canonical_colima_yaml(home: Path, partition_mountpoint: str) -> None:
    yaml_path = home / ".colima" / "default" / "colima.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        dedent(f"""\
            cpu: 4
            memory: 8
            disk: 100
            mounts:
              - location: {partition_mountpoint}
                writable: true
        """)
    )


def _write_drifted_colima_yaml(home: Path) -> None:
    yaml_path = home / ".colima" / "default" / "colima.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        dedent("""\
            cpu: 2
            memory: 2
            disk: 100
            mounts: []
        """)
    )


# ---------------------------------------------------------------------------
# 5 end-to-end integration cases
# ---------------------------------------------------------------------------


def test_setup_no_op_on_fully_configured_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Case 14: fully-configured fixture → exits 0, zero mutations, no destructive prompt."""
    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_canonical_layout(mp, with_nebula=True)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _SpyPlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    # Snapshot raw/'s mtime before the run; assert unchanged after.
    raw_dir = mp / "genomeclaw" / "raw"
    raw_mtime_before = raw_dir.stat().st_mtime_ns

    rc = run_smart(platform=platform)

    assert rc == 0
    captured = capsys.readouterr()
    assert "already" in captured.out.lower() or "configured" in captured.out.lower()
    # INV-D001: raw/ untouched.
    assert raw_dir.stat().st_mtime_ns == raw_mtime_before
    # Platform was queried but no destructive method was called.
    method_names = [name for name, _, _ in platform.calls]
    assert "colima_stop" not in method_names
    assert "colima_start" not in method_names


def test_setup_reconfigure_colima_when_drifted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 15: drifted colima.yaml → rewrite + stop + start; audit-log event."""
    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_canonical_layout(mp, with_nebula=True)
    _write_drifted_colima_yaml(tmp_path)
    platform = _SpyPlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    rc = run_smart(platform=platform)

    assert rc == 0
    # Platform received colima_stop + colima_start in that order.
    method_names = [name for name, _, _ in platform.calls]
    stop_idx = method_names.index("colima_stop")
    start_idx = method_names.index("colima_start")
    assert stop_idx < start_idx

    # colima.yaml was rewritten: mounts now lists the canonical path; memory ≥ 4.
    yaml_text = (tmp_path / ".colima" / "default" / "colima.yaml").read_text()
    assert str(mp) in yaml_text
    # Memory bumped from 2.
    assert "memory: 2\n" not in yaml_text

    # Audit-log event recorded under _scratch/setup.log.
    setup_log = mp / "genomeclaw" / "_scratch" / "setup.log"
    assert setup_log.exists()
    events = [json.loads(line) for line in setup_log.read_text().splitlines() if line.strip()]
    reconfigure_events = [e for e in events if e["step"] == "reconfigure_colima"]
    assert len(reconfigure_events) >= 1


def test_invD001_setup_recreate_layout_does_not_touch_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 16: missing _scratch → mkdir it; raw/ mtime unchanged (`INV-D001`)."""
    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    # Stage layout EXCEPT _scratch.
    root = mp / "genomeclaw"
    (root / "raw" / "MPNRGLQ2K").mkdir(parents=True)
    (root / "raw" / "MPNRGLQ2K" / "sample.vcf.gz").write_bytes(b"stub")
    (root / "reference").mkdir(parents=True)
    (root / "derived").mkdir(parents=True)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _SpyPlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    raw_mtime_before = (root / "raw").stat().st_mtime_ns
    raw_file_sha_before = (root / "raw" / "MPNRGLQ2K" / "sample.vcf.gz").read_bytes()

    rc = run_smart(platform=platform)

    assert rc == 0
    # _scratch/ now exists.
    assert (root / "_scratch").is_dir()
    # raw/ untouched.
    assert (root / "raw").stat().st_mtime_ns == raw_mtime_before
    assert (root / "raw" / "MPNRGLQ2K" / "sample.vcf.gz").read_bytes() == raw_file_sha_before

    # Audit-log records the recreate_layout step.
    setup_log = root / "_scratch" / "setup.log"
    assert setup_log.exists()
    events = [json.loads(line) for line in setup_log.read_text().splitlines() if line.strip()]
    recreate_events = [e for e in events if e["step"] == "recreate_layout"]
    assert len(recreate_events) == 1
    assert "_scratch" in recreate_events[0]["payload"].get("subdirs_recreated", [])


def test_setup_start_colima_when_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 17: everything green but colima stopped → colima_start called once."""
    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_canonical_layout(mp, with_nebula=True)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _SpyPlatform(
        volumes=[_make_volume("Genome_Work", str(mp))],
        colima_status_value="stopped",
    )

    rc = run_smart(platform=platform)

    assert rc == 0
    method_names = [name for name, _, _ in platform.calls]
    assert "colima_start" in method_names
    assert "colima_stop" not in method_names

    setup_log = mp / "genomeclaw" / "_scratch" / "setup.log"
    events = [json.loads(line) for line in setup_log.read_text().splitlines() if line.strip()]
    assert any(e["step"] == "start_colima" for e in events)


def test_setup_full_destructive_when_no_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Case 18: no Genome_Work → dispatch identifies FULL_DESTRUCTIVE and exits with
    a clear pointer (run_smart doesn't auto-run the destructive path without
    confirmation; that's the existing run_interactive flow, covered separately).
    """
    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    platform = _SpyPlatform(volumes=[], colima_status_value="stopped")

    rc = run_smart(platform=platform)

    # Exits with rc != 0 (pointer to the interactive destructive path).
    assert rc != 0
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "destructive" in combined or "first-time" in combined or "partition" in combined
    # No destructive method calls — run_smart is for non-destructive auto-heal only.
    method_names = [name for name, _, _ in platform.calls]
    assert "colima_stop" not in method_names
    assert "partition_disk_apfs" not in method_names


def _stage_empty_genomeclaw_root(mountpoint: Path) -> None:
    """Partition is mounted + genomeclaw/ exists but all four subdirs are missing."""
    (mountpoint / "genomeclaw").mkdir(parents=True, exist_ok=True)


def test_setup_empty_partition_prompts_and_recreates_on_default_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """All four subdirs missing + interactive TTY → prompt, default (Enter / "1") recreates."""
    import builtins
    import sys as _sys

    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_empty_genomeclaw_root(mp)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _SpyPlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_a, **_kw: "")

    rc = run_smart(platform=platform)

    assert rc == 0
    root = mp / "genomeclaw"
    for sub in ("raw", "reference", "derived", "_scratch"):
        assert (root / sub).is_dir()
    captured = capsys.readouterr()
    assert "How would you like to proceed?" in captured.out
    # Verbose recreate output is visible.
    assert "Created under" in captured.out


def test_setup_empty_partition_routes_to_destructive_on_choice_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """All four subdirs missing + user picks "2" → returns 2; no subdirs created."""
    import builtins
    import sys as _sys

    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_empty_genomeclaw_root(mp)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _SpyPlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_a, **_kw: "2")

    rc = run_smart(platform=platform)

    assert rc == 2
    root = mp / "genomeclaw"
    # No mkdir happened — caller will hand off to run_interactive.
    for sub in ("raw", "reference", "derived", "_scratch"):
        assert not (root / sub).exists()


def test_setup_empty_partition_auto_heals_on_non_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All four subdirs missing + stdin not a TTY → skip prompt, recreate silently."""
    import builtins
    import sys as _sys

    from genomeclaw_toolkit.prep.setup.run import run_smart

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_empty_genomeclaw_root(mp)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _SpyPlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)

    def _fail_input(*_a, **_kw) -> str:
        raise AssertionError("input() must not be called on non-TTY callers")

    monkeypatch.setattr(builtins, "input", _fail_input)

    rc = run_smart(platform=platform)

    assert rc == 0
    root = mp / "genomeclaw"
    for sub in ("raw", "reference", "derived", "_scratch"):
        assert (root / sub).is_dir()

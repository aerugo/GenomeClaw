"""Smart-setup — state inspection tests.

`inspect_system(platform=...)` is a pure function that reads:
- partition presence/format/mountpoint via Platform.list_volumes
- the four canonical subdirs (raw, reference, derived, _scratch) under
  the partition mountpoint
- Nebula presence via globbing raw/<*>/
- colima.yaml drift via reading + parsing the colima.yaml on disk
- colima runtime status via Platform.colima_status

Tests inject a FakePlatform + on-disk tmp_path layout to drive each
state combination synthetically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from genomeclaw_toolkit.prep.setup._types import DriveIdentity, Volume


@dataclass
class _FakePlatform:
    """Minimal Platform-protocol stub for state inspection."""

    volumes: list[Volume]
    colima_status_value: str = "running"

    def list_volumes(self) -> list[Volume]:
        return list(self.volumes)

    def colima_status(self) -> str:
        return self.colima_status_value

    # Unused by inspect; stubs to satisfy the Protocol.
    def read_drive_identity(self, volume: Volume) -> DriveIdentity:
        raise NotImplementedError

    def bcftools_view_header(self, vcf: Path) -> tuple[str, str]:
        raise NotImplementedError

    def colima_stop(self) -> None:
        raise NotImplementedError

    def colima_start(self) -> None:
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


def _stage_canonical_layout(mountpoint: Path, *, with_nebula: bool = False) -> None:
    """Create the four canonical subdirs under ``mountpoint``."""
    root = mountpoint / "genomeclaw"
    for sub in ("raw", "reference", "derived", "_scratch"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if with_nebula:
        sample = root / "raw" / "MPNRGLQ2K"
        sample.mkdir(parents=True, exist_ok=True)
        (sample / "MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz").write_bytes(b"stub")


def _write_canonical_colima_yaml(home: Path, partition_mountpoint: str) -> None:
    """Write a colima.yaml with the canonical mounts + memory ≥ 4 GB."""
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
    """colima.yaml with empty mounts + tiny memory."""
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
# 6 inspect cases
# ---------------------------------------------------------------------------


def test_inspect_returns_fresh_state_when_no_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 1: no Genome_Work volume detected → partition_present=False, all-other defaults."""
    from genomeclaw_toolkit.prep.setup.inspect import inspect_system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    platform = _FakePlatform(volumes=[], colima_status_value="running")

    state = inspect_system(platform=platform)
    assert state.partition_present is False
    assert state.partition_format is None
    assert state.partition_mountpoint is None
    assert state.layout_present is False
    assert state.nebula_present is False


def test_inspect_detects_wrong_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 2: Genome_Work exists but is exFAT."""
    from genomeclaw_toolkit.prep.setup.inspect import inspect_system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    mp.mkdir()
    platform = _FakePlatform(volumes=[_make_volume("Genome_Work", str(mp), filesystem="exfat")])

    state = inspect_system(platform=platform)
    assert state.partition_present is True
    assert state.partition_format == "exfat"
    assert state.partition_mountpoint == mp


def test_inspect_detects_layout_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 3: partition is APFS but raw/ doesn't exist."""
    from genomeclaw_toolkit.prep.setup.inspect import inspect_system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    (mp / "genomeclaw" / "reference").mkdir(parents=True)
    (mp / "genomeclaw" / "derived").mkdir(parents=True)
    (mp / "genomeclaw" / "_scratch").mkdir(parents=True)
    # raw/ deliberately not created
    platform = _FakePlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    state = inspect_system(platform=platform)
    assert state.partition_present is True
    assert state.partition_format == "apfs"
    assert state.layout_present is False
    assert "raw" in state.layout_missing_subdirs


def test_inspect_detects_nebula_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 4: layout present but raw/ is empty (no sample subdir)."""
    from genomeclaw_toolkit.prep.setup.inspect import inspect_system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_canonical_layout(mp, with_nebula=False)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _FakePlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    state = inspect_system(platform=platform)
    assert state.layout_present is True
    assert state.nebula_present is False
    assert state.nebula_sample_id is None


def test_inspect_parses_colima_yaml_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 5: drifted colima.yaml (empty mounts + memory: 2)."""
    from genomeclaw_toolkit.prep.setup.inspect import inspect_system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_canonical_layout(mp, with_nebula=True)
    _write_drifted_colima_yaml(tmp_path)
    platform = _FakePlatform(volumes=[_make_volume("Genome_Work", str(mp))])

    state = inspect_system(platform=platform)
    assert state.colima_yaml_canonical is False
    # Drift list should call out both gaps.
    drift_blob = " ".join(state.colima_yaml_drift)
    assert "mounts" in drift_blob or "Genome_Work" in drift_blob
    assert "memory" in drift_blob


def test_inspect_fully_configured_system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 6: every condition green."""
    from genomeclaw_toolkit.prep.setup.inspect import inspect_system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mp = tmp_path / "vol-genome-work"
    _stage_canonical_layout(mp, with_nebula=True)
    _write_canonical_colima_yaml(tmp_path, str(mp))
    platform = _FakePlatform(
        volumes=[_make_volume("Genome_Work", str(mp))], colima_status_value="running"
    )

    state = inspect_system(platform=platform)
    assert state.partition_present is True
    assert state.partition_format == "apfs"
    assert state.layout_present is True
    assert state.layout_missing_subdirs == ()
    assert state.nebula_present is True
    assert state.nebula_sample_id == "MPNRGLQ2K"
    assert state.colima_yaml_canonical is True
    assert state.colima_yaml_drift == ()
    assert state.colima_running is True

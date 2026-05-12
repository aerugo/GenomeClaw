"""Phase 2 — unit tests for ``prep/setup/_yaml_writer.py`` (Option A).

The writer rewrites ``~/.colima/default/colima.yaml`` to ensure the
GenomeClaw partition mount (e.g. ``/Volumes/Genome_Work``) is declared
as a single writable virtiofs entry. Per-subdir RO/RW is enforced at
docker bind-mount level by the host shim, *not* at colima.yaml.

Other user-managed mounts (e.g. ``/Users/hugi``) are preserved.
``additionalDisks`` is dropped (colima 0.9.1 silently strips it).
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_yaml_writer_adds_partition_mount_when_absent(tmp_path: Path) -> None:
    """Empty mounts → exactly one writable entry for the partition."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml

    cfg = tmp_path / "colima.yaml"
    _write(cfg, "cpu: 4\nmounts: []\n")
    write_colima_yaml(cfg, partition_mount=Path("/Volumes/Genome_Work"), backup=False)

    data = _read_yaml(cfg)
    assert data["mounts"] == [
        {"location": "/Volumes/Genome_Work", "writable": True},
    ]


def test_yaml_writer_preserves_unrelated_user_mounts(tmp_path: Path) -> None:
    """``/Users/hugi`` and other user-managed mounts survive the rewrite."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml

    cfg = tmp_path / "colima.yaml"
    _write(
        cfg,
        """\
cpu: 4
mounts:
  - location: /Users/hugi
    writable: true
""",
    )
    write_colima_yaml(cfg, partition_mount=Path("/Volumes/Genome_Work"), backup=False)

    data = _read_yaml(cfg)
    locations = [m["location"] for m in data["mounts"]]
    assert "/Users/hugi" in locations
    assert "/Volumes/Genome_Work" in locations


def test_yaml_writer_replaces_existing_partition_entry(tmp_path: Path) -> None:
    """Re-running setup against an already-mounted partition → de-duplicated, not appended."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml

    cfg = tmp_path / "colima.yaml"
    _write(
        cfg,
        """\
cpu: 4
mounts:
  - location: /Volumes/Genome_Work
    writable: false
""",
    )
    write_colima_yaml(cfg, partition_mount=Path("/Volumes/Genome_Work"), backup=False)

    data = _read_yaml(cfg)
    matching = [m for m in data["mounts"] if m["location"] == "/Volumes/Genome_Work"]
    assert len(matching) == 1
    assert matching[0]["writable"] is True


def test_yaml_writer_preserves_unrelated_top_level_fields(tmp_path: Path) -> None:
    """``cpu`` / ``memory`` / ``runtime`` / ``hostname`` survive the rewrite."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml

    cfg = tmp_path / "colima.yaml"
    _write(
        cfg,
        """\
cpu: 4
memory: 6
runtime: docker
hostname: colima
mounts: []
""",
    )
    write_colima_yaml(cfg, partition_mount=Path("/Volumes/Genome_Work"), backup=False)

    data = _read_yaml(cfg)
    assert data["cpu"] == 4
    assert data["memory"] == 6
    assert data["runtime"] == "docker"
    assert data["hostname"] == "colima"


def test_yaml_writer_drops_additional_disks(tmp_path: Path) -> None:
    """If ``additionalDisks`` is present from a stale prior run, it's removed.

    Colima 0.9.1 silently strips the field on start anyway; we drop it
    explicitly so the on-disk config doesn't mislead anyone reading it.
    """
    from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml

    cfg = tmp_path / "colima.yaml"
    _write(
        cfg,
        """\
cpu: 4
mounts: []
additionalDisks:
  - name: stale-disk
""",
    )
    write_colima_yaml(cfg, partition_mount=Path("/Volumes/Genome_Work"), backup=False)

    data = _read_yaml(cfg)
    assert "additionalDisks" not in data


def test_yaml_writer_writes_backup_when_requested(tmp_path: Path) -> None:
    """``backup=True`` writes ``colima.yaml.bak.<ts>`` next to the original."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml

    cfg = tmp_path / "colima.yaml"
    _write(cfg, "cpu: 4\nmounts: []\n")
    original_text = cfg.read_text()

    write_colima_yaml(cfg, partition_mount=Path("/Volumes/Genome_Work"), backup=True)
    backups = list(tmp_path.glob("colima.yaml.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original_text

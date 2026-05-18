"""Slice 2 of host-mount-lifecycle — ``remove_colima_mount`` helper.

Tests the inverse of :func:`write_colima_yaml` — removing a mount entry
by location. Same idempotent shape: re-running the removal against a
config that no longer has the entry is a no-op.

Per the 2026-05-14 Kingston-drive incident, a stale mount entry blocks
``colima start`` with ``mkdir … permission denied``. ``host eject``
needs to call this on the drive being ejected so the same drive can
never be the cause of a future boot failure.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _write_colima_yaml_with_mounts(path: Path, mounts: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"mounts": mounts}, sort_keys=False))


def test_remove_colima_mount_drops_matching_entry(tmp_path: Path) -> None:
    """A mount whose ``location`` matches gets removed; others preserved."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import remove_colima_mount

    cfg = tmp_path / "colima.yaml"
    _write_colima_yaml_with_mounts(
        cfg,
        [
            {"location": "/Volumes/Genome_Work_Kingston", "writable": False},
            {"location": "/Users/hugi/GitRepos", "writable": True},
            {"location": "/Volumes/Genome_Work", "writable": True},
        ],
    )

    remove_colima_mount(cfg, location=Path("/Volumes/Genome_Work_Kingston"), backup=False)

    data = yaml.safe_load(cfg.read_text())
    locations = [m["location"] for m in data["mounts"]]
    assert "/Volumes/Genome_Work_Kingston" not in locations
    assert "/Users/hugi/GitRepos" in locations
    assert "/Volumes/Genome_Work" in locations


def test_remove_colima_mount_idempotent_when_entry_missing(tmp_path: Path) -> None:
    """Re-running against a config that no longer has the entry is a no-op.

    Defends ``host eject``-after-``host eject`` (or running eject on a
    drive that was never set up): the second call shouldn't blow up.
    """
    from genomeclaw_toolkit.prep.setup._yaml_writer import remove_colima_mount

    cfg = tmp_path / "colima.yaml"
    _write_colima_yaml_with_mounts(
        cfg,
        [
            {"location": "/Users/hugi/GitRepos", "writable": True},
            {"location": "/Volumes/Genome_Work", "writable": True},
        ],
    )

    # The drive isn't in the config; removing it should succeed silently.
    remove_colima_mount(cfg, location=Path("/Volumes/Never_Configured"), backup=False)

    data = yaml.safe_load(cfg.read_text())
    locations = [m["location"] for m in data["mounts"]]
    assert locations == ["/Users/hugi/GitRepos", "/Volumes/Genome_Work"]


def test_remove_colima_mount_handles_missing_config_file(tmp_path: Path) -> None:
    """Config doesn't exist (fresh user) → no-op, no error.

    A fresh user who runs ``host eject`` before ever running ``host
    setup`` shouldn't crash. Their colima.yaml doesn't exist; there's
    nothing to remove.
    """
    from genomeclaw_toolkit.prep.setup._yaml_writer import remove_colima_mount

    cfg = tmp_path / "nonexistent" / "colima.yaml"
    # Must not raise.
    remove_colima_mount(cfg, location=Path("/Volumes/Anything"), backup=False)
    assert not cfg.exists()


def test_remove_colima_mount_writes_backup_when_requested(tmp_path: Path) -> None:
    """``backup=True`` preserves the pre-edit config for diff/recovery."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import remove_colima_mount

    cfg = tmp_path / "colima.yaml"
    _write_colima_yaml_with_mounts(
        cfg,
        [{"location": "/Volumes/Foo", "writable": True}],
    )
    original_bytes = cfg.read_bytes()

    remove_colima_mount(cfg, location=Path("/Volumes/Foo"), backup=True)

    # Backup files are named <name>.bak.<ts>; find by prefix.
    backups = list(cfg.parent.glob("colima.yaml.bak.*"))
    assert len(backups) == 1, f"expected one backup file, got {backups}"
    assert backups[0].read_bytes() == original_bytes


def test_remove_colima_mount_normalises_trailing_slash(tmp_path: Path) -> None:
    """Trailing slash on either side of the comparison shouldn't matter.

    Match the ``write_colima_yaml`` normalisation — if the user typed
    ``/Volumes/Foo/`` in the config, removing ``/Volumes/Foo`` still
    drops it (and vice versa).
    """
    from genomeclaw_toolkit.prep.setup._yaml_writer import remove_colima_mount

    cfg = tmp_path / "colima.yaml"
    _write_colima_yaml_with_mounts(
        cfg,
        [
            {"location": "/Volumes/Foo/", "writable": True},
            {"location": "/Volumes/Bar", "writable": True},
        ],
    )

    remove_colima_mount(cfg, location=Path("/Volumes/Foo"), backup=False)

    data = yaml.safe_load(cfg.read_text())
    locations = [m["location"] for m in data["mounts"]]
    assert "/Volumes/Foo/" not in locations
    assert "/Volumes/Foo" not in locations
    assert "/Volumes/Bar" in locations


def test_remove_colima_mount_preserves_other_top_level_keys(tmp_path: Path) -> None:
    """Memory / cpu / disk fields in colima.yaml survive the mount edit."""
    from genomeclaw_toolkit.prep.setup._yaml_writer import remove_colima_mount

    cfg = tmp_path / "colima.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "cpu": 4,
                "memory": 8,
                "disk": 100,
                "mounts": [{"location": "/Volumes/Foo", "writable": True}],
            },
            sort_keys=False,
        )
    )

    remove_colima_mount(cfg, location=Path("/Volumes/Foo"), backup=False)

    data = yaml.safe_load(cfg.read_text())
    assert data["cpu"] == 4
    assert data["memory"] == 8
    assert data["disk"] == 100
    assert data["mounts"] == []

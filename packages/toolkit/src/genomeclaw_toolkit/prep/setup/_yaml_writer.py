"""Rewrite ``~/.colima/default/colima.yaml`` for Phase-2 setup (Option A).

Ensures the partition mount (e.g. ``/Volumes/Genome_Work``) is declared
as a single writable virtiofs entry. Per-subdir RO/RW is enforced at
docker bind-mount level by the host shim, *not* at colima.yaml — colima
0.9.1 + lima 1.2.1 + macOS Sequoia returned per-subdir mounts as RO
regardless of ``writable: true``, so we expose the partition root and
let the shim's ``--mount type=bind`` flags carry the discipline.

Other user-managed mounts (e.g. ``/Users/hugi``) are preserved as-is.
Any prior entry pointing at the same partition is replaced (de-duped),
so re-running setup is idempotent.

Block-attached scratch (``additionalDisks``) is *not* written — colima
0.9.1 silently strips that field on start. See
``docs/reports/cram-scratch-strategy.md`` for the architectural pivot.

PyYAML drops comments on round-trip; the writer always backs up the
original to ``<path>.bak.<ts>`` (when ``backup=True``) so the user can
diff to recover commentary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def _normalise_location(loc: str) -> str:
    """Strip trailing slash for comparison."""
    return loc.rstrip("/") or "/"


def write_colima_yaml(
    config_path: Path,
    *,
    partition_mount: Path,
    backup: bool = True,
) -> Path:
    """Ensure ``partition_mount`` is declared as a writable virtiofs entry.

    Args:
        config_path: Path to ``colima.yaml``.
        partition_mount: The partition mount point (e.g.
            ``/Volumes/Genome_Work``). The whole partition is exposed
            with ``writable: true``; per-subdir RO/RW is the shim's job.
        backup: If True, copy the existing file to ``<path>.bak.<ts>`` first.

    Returns:
        The path that was rewritten (same as ``config_path``).
    """
    if backup and config_path.exists():
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        bak = config_path.with_name(f"{config_path.name}.bak.{ts}")
        bak.write_bytes(config_path.read_bytes())

    data: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded

    target_loc = _normalise_location(str(partition_mount))
    existing_mounts = data.get("mounts") or []
    # Preserve any user-managed mounts that aren't the partition mount.
    preserved = [
        m
        for m in existing_mounts
        if isinstance(m, dict) and _normalise_location(m.get("location", "")) != target_loc
    ]
    preserved.append({"location": str(partition_mount), "writable": True})
    data["mounts"] = preserved

    # Block-attached scratch is unsupported on colima 0.9.1 (silently
    # stripped on start). Drop ``additionalDisks`` if present, so we
    # don't leave a stale-looking config that suggests it works.
    data.pop("additionalDisks", None)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return config_path


__all__ = ["write_colima_yaml"]

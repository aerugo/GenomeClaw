"""Smart-setup — non-destructive colima.yaml + memory rewrite.

When ``inspect_system`` detects that the partition + layout + Nebula
are intact but ``~/.colima/default/colima.yaml`` has drifted (typically
after a ``colima delete && colima start`` which resets mounts/memory),
the dispatcher picks this action:

1. Reuse ``write_colima_yaml`` to inject the canonical partition mount
   (preserves the user's other mounts).
2. Bump ``memory:`` to a minimum (default 8 GB) if it's currently lower.
3. ``colima_stop`` → ``colima_start`` so the new config takes effect.
4. Append a structured event to ``_scratch/setup.log``.

The current production min-memory threshold is 4 GB (per
``inspect.py:_MIN_COLIMA_MEMORY_GB``). When this handler fires it bumps
to 8 GB — production margin, not just the bare-minimum threshold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml
from genomeclaw_toolkit.prep.setup.audit import AuditLog
from genomeclaw_toolkit.prep.setup.inspect import SystemState
from genomeclaw_toolkit.prep.setup.platform import Platform

_PRODUCTION_MEMORY_GB = 8


def _bump_memory_if_needed(config_path: Path, min_gb: int) -> tuple[int, int]:
    """Read ``memory:`` from ``config_path``; bump to ``min_gb`` if lower.

    Returns (before, after).
    """
    data: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(data, dict):
        data = {}

    mem_raw = data.get("memory", 0)
    try:
        before = int(mem_raw) if isinstance(mem_raw, int) else int(str(mem_raw).rstrip("GgIiBb"))
    except (TypeError, ValueError):
        before = 0

    if before >= min_gb:
        return before, before

    data["memory"] = min_gb
    config_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return before, min_gb


def reconfigure_colima(state: SystemState, *, platform: Platform) -> int:
    """Rewrite colima.yaml's mounts + memory; restart colima.

    Returns process-style exit code (0 on success).
    """
    assert state.partition_mountpoint is not None
    config_path = Path.home() / ".colima" / "default" / "colima.yaml"

    # 1. Ensure the canonical mount is in `mounts:` (idempotent — preserves
    #    other user-managed mounts).
    write_colima_yaml(config_path, partition_mount=state.partition_mountpoint, backup=True)

    # 2. Bump memory if below the production threshold.
    mem_before, mem_after = _bump_memory_if_needed(config_path, _PRODUCTION_MEMORY_GB)

    # 3. Restart colima so the new config takes effect.
    platform.colima_stop()
    platform.colima_start()

    # 4. Audit-log event.
    log_path = state.partition_mountpoint / "genomeclaw" / "_scratch" / "setup.log"
    log = AuditLog(log_path)
    try:
        log.event(
            step="reconfigure_colima",
            phase="complete",
            payload={
                "partition_mountpoint": str(state.partition_mountpoint),
                "drift_detected": list(state.colima_yaml_drift),
                "memory_before": mem_before,
                "memory_after": mem_after,
            },
        )
    finally:
        log.close()

    return 0


__all__ = ["reconfigure_colima"]

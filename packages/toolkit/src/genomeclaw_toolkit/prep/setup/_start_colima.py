"""Smart-setup — start colima (non-destructive, idempotent).

When `inspect_system` detects that everything else is green but colima
is stopped, the dispatcher picks this action: a single
``Platform.colima_start()`` call + an audit-log event.
"""

from __future__ import annotations

from genomeclaw_toolkit.prep.setup.audit import AuditLog
from genomeclaw_toolkit.prep.setup.inspect import SystemState
from genomeclaw_toolkit.prep.setup.platform import Platform


def start_colima(state: SystemState, *, platform: Platform) -> int:
    """Start colima; record an audit-log event.

    Returns process-style exit code (0 on success).
    """
    assert state.partition_mountpoint is not None
    platform.colima_start()

    log_path = state.partition_mountpoint / "genomeclaw" / "_scratch" / "setup.log"
    log = AuditLog(log_path)
    try:
        log.event(
            step="start_colima",
            phase="complete",
            payload={"partition_mountpoint": str(state.partition_mountpoint)},
        )
    finally:
        log.close()

    return 0


__all__ = ["start_colima"]

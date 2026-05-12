"""Smart-setup — recreate canonical layout subdirs (non-destructive).

When `inspect_system` detects that the Genome_Work partition exists +
is APFS but one or more canonical subdirs (``raw``, ``reference``,
``derived``, ``_scratch``) are absent, the dispatcher picks this
action: ``mkdir -p`` each missing subdir under
``<partition>/genomeclaw/``. Does not touch existing subdirs;
in particular, does not modify ``raw/`` (`INV-D001`).
"""

from __future__ import annotations

import sys

from genomeclaw_toolkit.prep.setup.audit import AuditLog
from genomeclaw_toolkit.prep.setup.inspect import SystemState


def recreate_layout(state: SystemState) -> int:
    """Create the canonical subdirs that are missing under the partition.

    Returns process-style exit code (0 on success).
    """
    assert state.partition_mountpoint is not None
    root = state.partition_mountpoint / "genomeclaw"

    created: list[str] = []
    for sub in state.layout_missing_subdirs:
        (root / sub).mkdir(parents=True, exist_ok=True)
        created.append(sub)

    if created:
        print(f"Created under {root}/:", file=sys.stdout)
        for sub in created:
            print(f"  + {sub}/", file=sys.stdout)

    # Audit-log lives under _scratch/setup.log. After mkdir, _scratch/
    # is guaranteed to exist (we just created it or it was already there).
    log = AuditLog(root / "_scratch" / "setup.log")
    try:
        log.event(
            step="recreate_layout",
            phase="complete",
            payload={
                "partition_mountpoint": str(state.partition_mountpoint),
                "subdirs_recreated": created,
            },
        )
    finally:
        log.close()

    return 0


__all__ = ["recreate_layout"]

"""``genomeclaw host setup`` — interactive flow for laying out the
external drive and configuring colima/lima for the CRAM-scale pipeline.

Phase 1 is non-destructive: detection, validation, and a complete
dry-run preview. The destructive partition / format / move runner
lands in Phase 2 (see ``docs/plans/active/cram-scratch-strategy/``).
"""

from genomeclaw_toolkit.prep.setup.audit import AuditLog
from genomeclaw_toolkit.prep.setup.detect import (
    InsufficientSpaceError,
    KnownBadFirmwareError,
    NebulaDeliverableError,
    SameDiskError,
    SetupError,
    build_plan,
    list_volumes,
    run_interactive,
    validate_nebula,
)
from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action
from genomeclaw_toolkit.prep.setup.dryrun import render
from genomeclaw_toolkit.prep.setup.execute import (
    ConfirmationMismatchError,
    DataIntegrityError,
    DestructiveStepError,
    MountFlagError,
    execute,
)
from genomeclaw_toolkit.prep.setup.inspect import SystemState, inspect_system
from genomeclaw_toolkit.prep.setup.run import run_smart

__all__ = [
    "AuditLog",
    "ConfirmationMismatchError",
    "DataIntegrityError",
    "DestructiveStepError",
    "InsufficientSpaceError",
    "KnownBadFirmwareError",
    "MountFlagError",
    "NebulaDeliverableError",
    "SameDiskError",
    "SetupAction",
    "SetupError",
    "SystemState",
    "build_plan",
    "decide_action",
    "execute",
    "inspect_system",
    "list_volumes",
    "render",
    "run_interactive",
    "run_smart",
    "validate_nebula",
]

"""Smart-setup — state → action dispatcher.

``decide_action(state)`` is a pure function that maps a ``SystemState``
to one of seven ``SetupAction``s plus a human-readable rationale. The
decision tree is documented in
``docs/plans/active/smart-setup/spec.md`` § Seven defined states.
"""

from __future__ import annotations

from enum import StrEnum

from genomeclaw_toolkit.prep.setup.inspect import SystemState


class SetupAction(StrEnum):
    FULL_DESTRUCTIVE = "full_destructive"
    RECONFIGURE_COLIMA = "reconfigure_colima"
    START_COLIMA = "start_colima"
    RECREATE_LAYOUT = "recreate_layout"
    RESTAGE_NEBULA = "restage_nebula"
    NO_OP = "no_op"


def decide_action(state: SystemState) -> tuple[SetupAction, str]:
    """Map state to action + a one-line rationale.

    Decision tree (ordered; first match wins):

    1. No partition → FULL_DESTRUCTIVE
    2. Wrong format (not APFS) → FULL_DESTRUCTIVE
    3. Layout incomplete → RECREATE_LAYOUT
    4. Nebula raw/ empty → RESTAGE_NEBULA
    5. colima.yaml drifted → RECONFIGURE_COLIMA
    6. colima stopped → START_COLIMA
    7. Otherwise → NO_OP
    """
    if not state.partition_present:
        return (
            SetupAction.FULL_DESTRUCTIVE,
            "No Genome_Work partition detected — first-time onboarding required.",
        )

    if state.partition_format != "apfs":
        return (
            SetupAction.FULL_DESTRUCTIVE,
            f"Partition is {state.partition_format!r}, not APFS — reformat required.",
        )

    if not state.layout_present:
        missing = ", ".join(state.layout_missing_subdirs)
        return (
            SetupAction.RECREATE_LAYOUT,
            f"Partition exists but canonical subdirs missing: {missing}.",
        )

    if not state.nebula_present:
        return (
            SetupAction.RESTAGE_NEBULA,
            (
                "Layout present but raw/ is empty — re-run setup with "
                "--source <path-to-nebula-deliverable> to re-stage."
            ),
        )

    if not state.colima_yaml_canonical:
        drift = ", ".join(state.colima_yaml_drift)
        return (
            SetupAction.RECONFIGURE_COLIMA,
            f"colima.yaml drifted ({drift}) — will rewrite + restart colima.",
        )

    if not state.colima_running:
        return (
            SetupAction.START_COLIMA,
            "Colima is stopped — will start.",
        )

    return (SetupAction.NO_OP, "System already configured; nothing to do.")


__all__ = ["SetupAction", "decide_action"]

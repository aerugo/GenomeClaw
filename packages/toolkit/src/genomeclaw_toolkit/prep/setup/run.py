"""Smart-setup — state-driven entry point.

``run_smart(platform=...)`` is the non-destructive auto-heal path:
it inspects current system state, dispatches to the right action
handler (or no-ops), and returns. The destructive "first-time
onboarding" path remains in ``detect.run_interactive(...)`` — when
``run_smart`` detects that destructive setup is needed, it exits with
a non-zero code + a pointer to ``run_interactive``.

This is intentional separation: ``run_smart`` is safe to invoke
unattended; the destructive path requires the typed-confirmation
prompt + an interactive TTY.
"""

from __future__ import annotations

import sys

from genomeclaw_toolkit.prep.setup import detect as _detect
from genomeclaw_toolkit.prep.setup._reconfigure_colima import reconfigure_colima
from genomeclaw_toolkit.prep.setup._recreate_layout import recreate_layout
from genomeclaw_toolkit.prep.setup._start_colima import start_colima
from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action
from genomeclaw_toolkit.prep.setup.inspect import inspect_system
from genomeclaw_toolkit.prep.setup.platform import Platform


def _print_state_summary(state, action: SetupAction, rationale: str) -> None:
    """One-paragraph human-readable preview of the chosen action."""
    print(f"Detected action: {action.value}", file=sys.stdout)
    print(f"Rationale: {rationale}", file=sys.stdout)


def _prompt_empty_partition_choice() -> str:
    """Ask whether to recreate the layout in-place or reformat from scratch.

    Returns ``"destructive"`` if the user picked the reformat path,
    ``"recreate"`` (default) otherwise. Uses ``builtins.input`` so tests
    can monkey-patch it directly, mirroring ``detect.run_interactive``.
    """
    import builtins

    print("", file=sys.stdout)
    print("Genome_Work is mounted but the genomeclaw/ layout is empty.", file=sys.stdout)
    print("How would you like to proceed?", file=sys.stdout)
    print(
        "  [1] Use the existing partition — create raw/, reference/, derived/, _scratch/ (default)",
        file=sys.stdout,
    )
    print(
        "  [2] Start from scratch — reformat the partition (DESTRUCTIVE)",
        file=sys.stdout,
    )
    print("", file=sys.stdout)
    answer = builtins.input("Choice [1/2]: ").strip()
    if answer == "2":
        return "destructive"
    return "recreate"


def run_smart(*, platform: Platform | None = None) -> int:
    """Inspect state + dispatch the right non-destructive action.

    Returns process-style exit code:
    - 0 on NO_OP / successful action.
    - 2 when destructive setup is needed (caller should fall back to
      ``run_interactive``).
    - non-zero on action-handler failure (the underlying handler
      raises; we let it propagate after logging).
    """
    # Resolve via the ``detect`` module's attribute so tests that
    # ``monkeypatch.setattr(detect, "default_platform", ...)`` apply
    # to both ``run_smart`` and ``run_interactive``.
    plat = platform or _detect.default_platform()
    state = inspect_system(platform=plat)
    action, rationale = decide_action(state)

    _print_state_summary(state, action, rationale)

    if action == SetupAction.NO_OP:
        return 0

    if action == SetupAction.FULL_DESTRUCTIVE:
        # Caller (the CLI) falls through to the interactive destructive
        # flow. Standalone callers can interpret rc==2 + action ==
        # FULL_DESTRUCTIVE via inspect+dispatch directly if they need to.
        return 2

    if action == SetupAction.RESTAGE_NEBULA:
        # Same shape: the CLI falls through; standalone callers handle.
        return 2

    if action == SetupAction.RECREATE_LAYOUT:
        # When all four canonical subdirs are missing, the partition is
        # effectively empty — that's ambiguous enough (stale leftover vs.
        # fresh format) that we ask before mutating. Partial-missing
        # (one or two subdirs gone) is unambiguous recovery — auto-heal
        # silently. Skip the prompt on non-TTY callers (CI, pipes) so
        # unattended invocations keep the prior auto-heal behavior.
        if len(state.layout_missing_subdirs) == 4 and sys.stdin.isatty():
            if _prompt_empty_partition_choice() == "destructive":
                return 2
        return recreate_layout(state)

    if action == SetupAction.RECONFIGURE_COLIMA:
        return reconfigure_colima(state, platform=plat)

    if action == SetupAction.START_COLIMA:
        return start_colima(state, platform=plat)

    raise AssertionError(f"unhandled action: {action}")


__all__ = ["run_smart"]

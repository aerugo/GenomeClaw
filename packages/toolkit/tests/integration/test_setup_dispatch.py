"""Smart-setup — dispatcher decision tests.

`decide_action(state)` is a pure function: ``SystemState`` → ``(SetupAction,
rationale)``. Tests construct synthetic ``SystemState``s + assert the
chosen action + that the rationale string contains an expected substring
(so future rationale edits don't break tests over surface wording).
"""

from __future__ import annotations

from pathlib import Path


def _make_state(**overrides) -> object:
    """Construct a fully-green ``SystemState``, overriding selected fields.

    Imported lazily so the test file doesn't fail at collection time
    before the GREEN implementation lands.
    """
    from genomeclaw_toolkit.prep.setup.inspect import SystemState

    defaults = {
        "partition_present": True,
        "partition_format": "apfs",
        "partition_mountpoint": Path("/Volumes/Genome_Work"),
        "layout_present": True,
        "layout_missing_subdirs": (),
        "nebula_present": True,
        "nebula_sample_id": "MPNRGLQ2K",
        "colima_yaml_canonical": True,
        "colima_yaml_drift": (),
        "colima_running": True,
    }
    defaults.update(overrides)
    return SystemState(**defaults)


def test_decide_no_partition_dispatches_full_destructive() -> None:
    """Case 7: no Genome_Work partition → FULL_DESTRUCTIVE."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state(
        partition_present=False,
        partition_format=None,
        partition_mountpoint=None,
        layout_present=False,
        nebula_present=False,
        colima_yaml_canonical=False,
        colima_running=False,
    )
    action, rationale = decide_action(state)
    assert action == SetupAction.FULL_DESTRUCTIVE
    assert "first-time" in rationale.lower() or "no partition" in rationale.lower()


def test_decide_wrong_format_dispatches_full_destructive() -> None:
    """Case 8: partition exists but exFAT → FULL_DESTRUCTIVE."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state(partition_format="exfat", layout_present=False)
    action, rationale = decide_action(state)
    assert action == SetupAction.FULL_DESTRUCTIVE
    assert "apfs" in rationale.lower() or "format" in rationale.lower()


def test_decide_layout_missing_dispatches_recreate_layout() -> None:
    """Case 9: APFS partition exists but a subdir is absent → RECREATE_LAYOUT."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state(
        layout_present=False,
        layout_missing_subdirs=("raw", "_scratch"),
        nebula_present=False,
    )
    action, rationale = decide_action(state)
    assert action == SetupAction.RECREATE_LAYOUT
    assert "raw" in rationale or "_scratch" in rationale


def test_decide_nebula_missing_dispatches_restage_nebula() -> None:
    """Case 10: layout OK but raw/<sample>/ empty → RESTAGE_NEBULA."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state(nebula_present=False, nebula_sample_id=None)
    action, rationale = decide_action(state)
    assert action == SetupAction.RESTAGE_NEBULA
    assert "source" in rationale.lower() or "nebula" in rationale.lower()


def test_decide_colima_drifted_dispatches_reconfigure_colima() -> None:
    """Case 11: drifted colima.yaml → RECONFIGURE_COLIMA."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state(
        colima_yaml_canonical=False,
        colima_yaml_drift=("mounts_missing_genome_work", "memory_too_low"),
    )
    action, rationale = decide_action(state)
    assert action == SetupAction.RECONFIGURE_COLIMA
    assert "colima" in rationale.lower()


def test_decide_colima_stopped_dispatches_start_colima() -> None:
    """Case 12: everything else green, colima stopped → START_COLIMA."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state(colima_running=False)
    action, rationale = decide_action(state)
    assert action == SetupAction.START_COLIMA
    assert "colima" in rationale.lower()


def test_decide_everything_green_dispatches_no_op() -> None:
    """Case 13: fully configured → NO_OP."""
    from genomeclaw_toolkit.prep.setup.dispatch import SetupAction, decide_action

    state = _make_state()  # all defaults = green
    action, rationale = decide_action(state)
    assert action == SetupAction.NO_OP
    assert "already" in rationale.lower() or "configured" in rationale.lower()

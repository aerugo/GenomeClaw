"""Phase 2 — unit tests for ``prep/setup/audit.py``.

The audit log is JSON-Lines. ``AuditLog`` initially writes to
``~/.genomeclaw/setup-{ts}.log``; once the partition is created and
``mkdir_layout`` succeeds, ``promote(target_scratch_dir)`` atomically
moves the file to ``<target>/_scratch/setup.log``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_audit_log_writes_one_json_object_per_event(tmp_path: Path) -> None:
    """Each ``event(...)`` call appends one valid JSON object on its own line."""
    from genomeclaw_toolkit.prep.setup.audit import AuditLog

    log_dir = tmp_path / ".genomeclaw"
    log = AuditLog.open(log_dir, prefix="setup")
    log.event("step_a", "start", {"k": 1})
    log.event("step_a", "complete", {"k": 1, "result": "ok"})
    log.event("step_b", "start", {})
    log.close()

    files = list(log_dir.glob("setup-*.log"))
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    parsed = [json.loads(line) for line in lines if line.strip()]
    assert len(parsed) == 3
    for event in parsed:
        assert {"ts", "step", "phase", "payload"} <= set(event)


def test_audit_log_promote_moves_file_to_scratch(tmp_path: Path) -> None:
    """``promote(scratch_dir)`` moves the temp log into ``scratch_dir/setup.log``
    and the original temp file is gone."""
    from genomeclaw_toolkit.prep.setup.audit import AuditLog

    log_dir = tmp_path / ".genomeclaw"
    log = AuditLog.open(log_dir, prefix="setup")
    log.event("setup_started", "start", {})
    temp_path = log.path

    scratch_dir = tmp_path / "Genome_Work" / "genomeclaw" / "_scratch"
    scratch_dir.mkdir(parents=True)
    final = log.promote(scratch_dir)

    assert final == scratch_dir / "setup.log"
    assert final.exists()
    assert not temp_path.exists(), "temp log was not removed after promote"


def test_audit_log_promote_preserves_event_content(tmp_path: Path) -> None:
    """Pre- and post-promote, every event line round-trips intact."""
    from genomeclaw_toolkit.prep.setup.audit import AuditLog

    log = AuditLog.open(tmp_path / ".genomeclaw", prefix="setup")
    log.event("a", "start", {"x": 1})
    log.event("b", "complete", {"y": 2})
    pre_text = log.path.read_text()

    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    final = log.promote(scratch_dir)

    assert final.read_text() == pre_text


def test_audit_log_continues_writing_after_promote(tmp_path: Path) -> None:
    """Events appended *after* promote land in the promoted file."""
    from genomeclaw_toolkit.prep.setup.audit import AuditLog

    log = AuditLog.open(tmp_path / ".genomeclaw", prefix="setup")
    log.event("a", "start", {})

    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    final = log.promote(scratch_dir)

    log.event("b", "complete", {})
    log.close()

    events = [json.loads(line) for line in final.read_text().splitlines() if line.strip()]
    steps = [e["step"] for e in events]
    assert steps == ["a", "b"]


def test_audit_log_event_payload_must_be_json_serialisable(tmp_path: Path) -> None:
    """Non-JSON values raise ``TypeError`` at event time, not silently."""
    from genomeclaw_toolkit.prep.setup.audit import AuditLog

    log = AuditLog.open(tmp_path / ".genomeclaw", prefix="setup")
    with pytest.raises(TypeError):
        log.event("bad", "start", {"unserialisable": object()})

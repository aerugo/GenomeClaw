"""Phase 3 — ``ProgressEvent`` dataclass + NDJSON adapter tests.

The event hierarchy is the canonical seam between long-running
orchestrators and the rich/JSON renderers. These tests pin the shape +
serialisation contract before downstream consumers depend on it.
"""

from __future__ import annotations

import json


def test_progress_event_is_frozen_dataclass() -> None:
    """Events are immutable so handlers can safely cache + dedup them."""
    from dataclasses import FrozenInstanceError

    from genomeclaw_toolkit.prep._events import FileStart

    evt = FileStart(source="clinvar", relpath="clinvar.vcf.gz", total_bytes=42)
    try:
        evt.source = "tampered"  # type: ignore[misc]
    except FrozenInstanceError:
        return
    raise AssertionError("FileStart should be frozen")


def test_file_start_serialises_as_dict_with_event_type() -> None:
    """``to_json_dict`` emits a ``{"event": ..., ...fields}`` payload."""
    from genomeclaw_toolkit.prep._events import FileStart

    evt = FileStart(source="clinvar", relpath="clinvar.vcf.gz", total_bytes=42)
    encoded = evt.to_json_dict()
    assert encoded["event"] == "file_start"
    assert encoded["source"] == "clinvar"
    assert encoded["relpath"] == "clinvar.vcf.gz"
    assert encoded["total_bytes"] == 42


def test_file_progress_carries_bytes_so_far_and_total() -> None:
    """``FileProgress`` is the per-chunk update emitted during a download."""
    from genomeclaw_toolkit.prep._events import FileProgress

    evt = FileProgress(
        source="clinvar",
        relpath="clinvar.vcf.gz",
        bytes_so_far=1_048_576,
        total_bytes=10_000_000,
    )
    assert evt.bytes_so_far == 1_048_576
    encoded = evt.to_json_dict()
    assert encoded["event"] == "file_progress"
    assert encoded["bytes_so_far"] == 1_048_576


def test_file_complete_carries_sha_and_duration() -> None:
    """``FileComplete`` records the final identity + wall time."""
    from genomeclaw_toolkit.prep._events import FileComplete

    evt = FileComplete(
        source="clinvar",
        relpath="clinvar.vcf.gz",
        bytes_written=10_000_000,
        md5="0123456789abcdef0123456789abcdef",
        duration_sec=12.5,
    )
    encoded = evt.to_json_dict()
    assert encoded["event"] == "file_complete"
    assert encoded["md5"].startswith("0123")
    assert encoded["duration_sec"] == 12.5


def test_phase_start_and_complete_for_pipeline_chaining() -> None:
    """``PhaseStart`` / ``PhaseComplete`` mark pipeline-stage boundaries."""
    from genomeclaw_toolkit.prep._events import PhaseComplete, PhaseStart

    start = PhaseStart(phase="ingest")
    end = PhaseComplete(phase="ingest", duration_sec=71.2, run_dir="/x/y")
    assert start.to_json_dict()["event"] == "phase_start"
    payload = end.to_json_dict()
    assert payload["event"] == "phase_complete"
    assert payload["phase"] == "ingest"
    assert payload["duration_sec"] == 71.2
    assert payload["run_dir"] == "/x/y"


def test_pipeline_complete_emits_final_run_dir() -> None:
    """``PipelineComplete`` is the terminal event from ``pipeline run``."""
    from genomeclaw_toolkit.prep._events import PipelineComplete

    evt = PipelineComplete(run_dir="/derived/abc", duration_sec=900.0)
    payload = evt.to_json_dict()
    assert payload["event"] == "pipeline_complete"
    assert payload["run_dir"] == "/derived/abc"
    assert payload["duration_sec"] == 900.0


def test_event_round_trips_through_json() -> None:
    """Every event's ``to_json_dict`` is json-encodable as one NDJSON line."""
    from genomeclaw_toolkit.prep._events import FileStart

    evt = FileStart(source="clinvar", relpath="clinvar.vcf.gz", total_bytes=42)
    line = json.dumps(evt.to_json_dict())
    parsed = json.loads(line)
    assert parsed["event"] == "file_start"
    assert "\n" not in line  # NDJSON is line-oriented

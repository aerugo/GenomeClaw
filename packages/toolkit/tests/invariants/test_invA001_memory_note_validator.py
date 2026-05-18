"""`INV-A001` — Agent Memory Provenance contract tests.

The memory-note validator at
[src/genomeclaw_toolkit/memory/note_validator.py](
../../src/genomeclaw_toolkit/memory/note_validator.py) is the canonical
spec for what a well-formed memory note looks like. The agent's system
prompt at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](
../../../../nemoclaw-plugin/sandbox/agent-system-prompt.md) teaches the
agent to comply with this schema.

These tests exercise the validator against golden fixtures under
[fixtures/memory_notes/](fixtures/memory_notes/) covering each
contract rule:

- Well-formed note → parses, returns a typed :class:`MemoryNote`.
- Missing required section → `MemoryNoteValidationError` naming the gap.
- Missing Freshness date → `MemoryNoteValidationError` naming the gap.
- Memory-only citations (no primary source) → rejected, naming the
  hallucination-propagation risk.
- Well-formed supersession note → parses, surfaces `supersedes` field.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit.memory import (
    MemoryNote,
    MemoryNoteValidationError,
    validate_memory_note,
)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "memory_notes"


def _read_fixture(name: str) -> str:
    """Read a fixture memory note by filename stem."""
    return (_FIXTURES_DIR / f"{name}.md").read_text()


def test_invA001_well_formed_memory_note_parses() -> None:
    """The reference well-formed note parses cleanly + carries all fields.

    Pins the canonical shape so a future schema-tightening edit that
    accidentally rejects valid notes surfaces here.
    """
    note = validate_memory_note(_read_fixture("well_formed"))
    assert isinstance(note, MemoryNote)
    assert "CYP1A2" in note.title
    # All required section labels present.
    for required in (
        "Question",
        "Tool calls",
        "Sources retrieved",
        "Synthesis",
        "Calibration",
        "Recommendation framing",
        "Citations surfaced to the user",
        "Freshness",
    ):
        assert required in note.sections
    # Freshness parsed to a date string.
    assert note.freshness_date == "2026-05-15"
    # Primary sources detected — a mix of URLs + PMIDs.
    assert len(note.primary_sources) >= 2
    assert any("pharmgkb.org" in s for s in note.primary_sources)
    assert any("PMID 12345678" in s for s in note.primary_sources)
    # Not a supersession note.
    assert note.supersedes is None


def test_invA001_rejects_memory_only_citations() -> None:
    """Memory note citing only other memory notes is rejected.

    Closes the hallucination-propagation loop: a note's evidence chain
    must terminate in at least one primary source (URL, PMID, ClinVar,
    etc.), never solely in other memory notes. The error message names
    the rule + the offending memory: refs so the agent (reading its own
    rejection) can re-run fresh research.
    """
    with pytest.raises(MemoryNoteValidationError) as exc_info:
        validate_memory_note(_read_fixture("memory_only_citations"))
    msg = str(exc_info.value).lower()
    assert "memory-only" in msg or "primary source" in msg, (
        f"error message must name the rule; got: {exc_info.value}"
    )
    assert "memory:" in msg, "error message must surface the offending memory: refs"


def test_invA001_rejects_missing_required_section() -> None:
    """A note missing one of the required sections is rejected.

    The validator names the missing fields + the full required set so
    the agent's writer step can self-correct.
    """
    with pytest.raises(MemoryNoteValidationError) as exc_info:
        validate_memory_note(_read_fixture("missing_required_field"))
    msg = str(exc_info.value)
    assert "missing required section" in msg.lower()
    # The fixture deliberately omits Calibration, Recommendation framing,
    # Citations, Freshness — at least Calibration must be named.
    assert "Calibration" in msg


def test_invA001_rejects_missing_freshness_date() -> None:
    """A Freshness section without an `as of YYYY-MM-DD` date is rejected.

    The freshness field is what later validation (per `INV-C001` v1.6)
    uses to decide re-research vs. recall. Without a parseable date the
    recall path can't compute staleness, so the writer must reject.
    """
    with pytest.raises(MemoryNoteValidationError) as exc_info:
        validate_memory_note(_read_fixture("missing_freshness"))
    msg = str(exc_info.value)
    assert "Freshness" in msg
    assert "as of" in msg


def test_invA001_well_formed_supersession_note_parses() -> None:
    """A supersession note carries `Supersedes:` + parses cleanly.

    Per the v1.6 supersession mechanism: when memory validation fails,
    the agent writes a new note pointing at the prior anchor. The prior
    note stays on disk for the audit trail; the new note is what gets
    cited going forward.
    """
    note = validate_memory_note(_read_fixture("well_formed_supersession"))
    assert note.supersedes is not None
    assert note.supersedes.startswith("memory:")
    assert "2026-03-15-cyp1a2.md" in note.supersedes
    # Supersession notes still satisfy all the standard contract rules.
    assert note.freshness_date == "2026-05-15"
    assert len(note.primary_sources) >= 2


def test_invA001_empty_note_rejected() -> None:
    """Trivial — an empty string is not a valid memory note."""
    with pytest.raises(MemoryNoteValidationError):
        validate_memory_note("")
    with pytest.raises(MemoryNoteValidationError):
        validate_memory_note("   \n\n\n  ")


def test_invA001_note_without_title_heading_rejected() -> None:
    """A note without a `## <title>` heading is malformed."""
    body = "**Question**: foo\n\n(everything else, no title)\n"
    with pytest.raises(MemoryNoteValidationError) as exc_info:
        validate_memory_note(body)
    assert "title" in str(exc_info.value).lower()

"""Phase 5 — INV-C004 is promoted in INVARIANTS.md.

Doc-shape gate for the host-profile-personal-context plan's promotion of
INV-C004 (Host Profile Context Must Inform Genome-Informable Turns). Asserts
the canonical entry exists with the four required sections, an Invariant
Index row, a verification section that references all three Phase-4 gates,
and a bumped document Version + Last-Updated date.
"""

from __future__ import annotations

import re
from pathlib import Path

_INVARIANTS = (
    Path(__file__).resolve().parents[4] / "docs" / "reference" / "INVARIANTS.md"
)


def _doc() -> str:
    return _INVARIANTS.read_text()


def _invC004_section(doc: str) -> str:
    start = doc.index("## INV-C004:")
    # Next top-level invariant heading or the Invariant Index, whichever first.
    nxt = re.search(r"\n## (INV-|Invariant Index)", doc[start + 3 :])
    end = start + 3 + nxt.start() if nxt else len(doc)
    return doc[start:end]


def test_invC004_heading_and_sections_present() -> None:
    """INV-C004 has a heading + Rule / Requirements / Where it applies / How to verify."""
    section = _invC004_section(_doc())
    assert "Host Profile Context Must Inform Genome-Informable Turns" in section
    for required in ("**Rule**", "**Requirements**", "**Where it applies**", "**How to verify**"):
        assert required in section, f"INV-C004 entry missing the {required} section"


def test_invC004_verification_references_all_three_gates() -> None:
    """The How-to-verify section names the prompt-content, trace-walk, and live_llm gates."""
    section = _invC004_section(_doc())
    assert "test_invC004_trace_walk_host_profile_called.py" in section
    assert "test_agent_system_prompt_contract.py" in section
    assert "test_host_profile_gap_framing.py" in section


def test_invC004_in_invariant_index() -> None:
    """The Invariant Index table carries an INV-C004 row."""
    doc = _doc()
    index_start = doc.index("## Invariant Index")
    index = doc[index_start:]
    assert re.search(r"\|\s*INV-C004\s*\|", index), "INV-C004 missing from the Invariant Index table"


def test_invariants_doc_version_bumped_for_c004() -> None:
    """The document Version is bumped past 1.25 and Last Updated is the promotion day."""
    doc = _doc()
    version_match = re.search(r"^\*\*Version\*\*:\s*([\d.]+)", doc, re.MULTILINE)
    assert version_match, "INVARIANTS.md missing a Version line"
    version = tuple(int(p) for p in version_match.group(1).split("."))
    assert version > (1, 25), f"INVARIANTS.md Version {version_match.group(1)} not bumped past 1.25"
    assert re.search(r"^\*\*Last Updated\*\*:\s*2026-05-31", doc, re.MULTILINE), (
        "INVARIANTS.md Last Updated not set to the INV-C004 promotion day (2026-05-31)"
    )

"""Memory-note parser + validator implementing `INV-A001`.

A well-formed memory note carries:
- Question (verbatim user question)
- Tool calls (with reasoning level for the research phase)
- Sources retrieved (at least one primary source — not a memory: ref)
- Synthesis (with reasoning level for the synthesis phase)
- Calibration (effect size + evidence quality + heterogeneity + modulators)
- Recommendation framing
- Citations surfaced to the user
- Freshness ("as of YYYY-MM-DD")

Plus, for supersession notes:
- Supersedes (anchor of the prior note)
- Gap found in prior note

The validator parses a Markdown note (the agent's writer step output) and
either returns a typed :class:`MemoryNote` or raises a
:class:`MemoryNoteValidationError` naming the specific contract violation.
The error message names the rule + the source field so an agent reading
its own validation failure can correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The required section labels in the memory-note schema. These are the
# bold-prefixed field labels the agent's system prompt teaches as the
# writer skeleton. The validator looks for `**<label>**:` markers.
_REQUIRED_SECTIONS: tuple[str, ...] = (
    "Question",
    "Tool calls",
    "Sources retrieved",
    "Synthesis",
    "Calibration",
    "Recommendation framing",
    "Citations surfaced to the user",
    "Freshness",
)

# Pattern: matches `**<label>**:` (bold prefix with optional trailing colon)
# OR a heading `## <label>` form, so the writer has formatting latitude.
_SECTION_HEADING_RE = re.compile(
    r"(?:\*\*([^*]+?)\*\*\s*:|^#+\s+([^\n]+))",
    re.MULTILINE,
)

# Primary-source citation patterns. Memory notes citing only `memory:`
# refs are malformed; at least one of these patterns must appear.
_PRIMARY_SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://\S+"),
    re.compile(r"\b(?:PMID|pubmed:)\s*\d+", re.IGNORECASE),
    re.compile(r"\b(?:RCV|VCV)\d{4,}", re.IGNORECASE),  # ClinVar accessions
    re.compile(r"\bPA\d+", re.IGNORECASE),  # PharmGKB accessions
    re.compile(r"\bPGS\d+", re.IGNORECASE),  # PGS Catalog ids
    re.compile(r"\bclinvar:\S+", re.IGNORECASE),
    re.compile(r"\bpharmgkb:\S+", re.IGNORECASE),
    re.compile(r"\bpgs_catalog:\S+", re.IGNORECASE),
)

# Freshness format: "as of YYYY-MM-DD" (extra trailing text allowed).
_FRESHNESS_RE = re.compile(r"as of (\d{4}-\d{2}-\d{2})", re.IGNORECASE)


class MemoryNoteValidationError(ValueError):
    """A memory note doesn't satisfy ``INV-A001``.

    The message names the specific rule + offending content so the agent
    (or a human reviewer) can correct the note.
    """


@dataclass(frozen=True)
class MemoryNote:
    """A parsed, validated memory note.

    Carries the structural fields the validator extracted. The body of
    each section stays as raw Markdown — interpretation is the agent's
    job, not the validator's.
    """

    title: str
    """The first `## <title>` heading of the note, sans the `##` markers."""

    sections: dict[str, str]
    """Mapping from required-section label → raw body content."""

    primary_sources: tuple[str, ...]
    """The primary-source citation strings found in the note body."""

    freshness_date: str
    """The `as of YYYY-MM-DD` date string."""

    supersedes: str | None
    """The `Supersedes: <anchor>` value if this is a supersession note, else None."""


def _extract_title(text: str) -> str:
    """Pull the first `## <title>` heading off the note."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return stripped[3:].strip()
    raise MemoryNoteValidationError("INV-A001: memory note missing `## <title>` heading")


def _extract_section_bodies(text: str) -> dict[str, str]:
    """Walk the note's `**<label>**:` (or heading) markers + collect bodies.

    Each body is the text between this marker and the next marker (or
    the end of the note). Trims leading/trailing whitespace.
    """
    matches: list[tuple[str, int, int]] = []
    for m in _SECTION_HEADING_RE.finditer(text):
        label_bold, label_heading = m.group(1), m.group(2)
        label = (label_bold or label_heading or "").strip()
        if not label:
            continue
        matches.append((label, m.start(), m.end()))

    sections: dict[str, str] = {}
    for i, (label, _start, body_start) in enumerate(matches):
        body_end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
        sections[label] = text[body_start:body_end].strip()
    return sections


def _find_primary_sources(text: str) -> list[str]:
    """Scan the whole note for primary-source citations.

    Returns the list of unique matches. The validator considers a note
    well-grounded if at least one primary source appears anywhere —
    typically inside the "Sources retrieved" or "Citations" sections.
    """
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _PRIMARY_SOURCE_PATTERNS:
        for m in pattern.finditer(text):
            citation = m.group(0)
            if citation not in seen:
                seen.add(citation)
                found.append(citation)
    return found


def _find_memory_only_citations(text: str) -> list[str]:
    """Find `memory:<file>#<anchor>` style citations.

    Returns the list of unique memory: ref strings. Used to detect the
    "memory-only" failure mode: a note that cites only other memory
    notes (no primary sources).
    """
    memory_ref = re.compile(r"\bmemory:\S+", re.IGNORECASE)
    return list(dict.fromkeys(m.group(0) for m in memory_ref.finditer(text)))


def validate_memory_note(text: str) -> MemoryNote:
    """Parse + validate a memory-note Markdown blob per ``INV-A001``.

    Raises:
        MemoryNoteValidationError: when any contract rule fails. The
            message names the specific rule + the offending content.

    Returns:
        A typed :class:`MemoryNote` carrying the parsed fields.
    """
    if not text or not text.strip():
        raise MemoryNoteValidationError("INV-A001: memory note is empty")

    title = _extract_title(text)
    extracted = _extract_section_bodies(text)

    # The schema lets the agent annotate section labels with parenthetical
    # context (e.g. `**Tool calls (research phase, reasoning=high)**:`).
    # Match each required label against extracted-label prefixes so the
    # annotated form passes. Build a canonical-label → body map.
    sections: dict[str, str] = {}
    for required_label in _REQUIRED_SECTIONS:
        for extracted_label, body in extracted.items():
            if extracted_label == required_label or extracted_label.startswith(
                (required_label + " ", required_label + "(")
            ):
                sections[required_label] = body
                break

    missing = [label for label in _REQUIRED_SECTIONS if label not in sections]
    if missing:
        raise MemoryNoteValidationError(
            f"INV-A001: memory note missing required section(s): {missing}. "
            f"Schema requires: {list(_REQUIRED_SECTIONS)}."
        )

    # Freshness must be a parseable `as of YYYY-MM-DD` date inside the
    # Freshness section.
    freshness_section = sections.get("Freshness", "")
    freshness_match = _FRESHNESS_RE.search(freshness_section)
    if freshness_match is None:
        raise MemoryNoteValidationError(
            "INV-A001: memory note's Freshness section must contain "
            f"`as of YYYY-MM-DD`; got body: {freshness_section[:200]!r}"
        )
    freshness_date = freshness_match.group(1)

    # At least one primary source must appear anywhere in the note.
    # Memory-only citations are explicitly NOT primary sources.
    primary_sources = _find_primary_sources(text)
    if not primary_sources:
        memory_only = _find_memory_only_citations(text)
        if memory_only:
            raise MemoryNoteValidationError(
                "INV-A001: memory note cites only other memory notes "
                f"({memory_only}); at least one primary source citation "
                "(URL / PubMed / ClinVar / PharmGKB / PGS Catalog id) is "
                "required. Memory-only chains compound hallucinations across "
                "sessions; the writer must run fresh research instead."
            )
        raise MemoryNoteValidationError(
            "INV-A001: memory note has no primary source citations. "
            "At least one URL or external authority id (PMID, ClinVar, "
            "PharmGKB, PGS Catalog) is required."
        )

    # Optional: supersession field.
    supersedes_match = re.search(r"\*\*Supersedes\*\*\s*:\s*([^\n]+)", text, re.IGNORECASE)
    supersedes = supersedes_match.group(1).strip() if supersedes_match else None
    if supersedes and "memory:" not in supersedes.lower():
        raise MemoryNoteValidationError(
            "INV-A001: Supersedes field must reference a memory note "
            f"(`memory:<file>#<anchor>`); got {supersedes!r}"
        )

    return MemoryNote(
        title=title,
        sections=sections,
        primary_sources=tuple(primary_sources),
        freshness_date=freshness_date,
        supersedes=supersedes,
    )


__all__ = [
    "MemoryNote",
    "MemoryNoteValidationError",
    "validate_memory_note",
]

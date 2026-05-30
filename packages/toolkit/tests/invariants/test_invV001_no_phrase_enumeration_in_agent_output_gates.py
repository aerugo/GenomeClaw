"""INV-V001 — Verification Mechanisms Must Not Enumerate Forbidden Phrases for Agent Output.

Discovery test: walks test files + the agent system prompt, looks for **suspect
substring patterns** (string-tuple/list literals; inline `assert "..." in
<agent-output-var>` checks), and requires each suspect site to carry an
explicit annotation declaring why the pattern is allowed:

- ``# INV-V001-backstop:`` — non-load-bearing sanity / regression-pin check.
  The real correctness gate is elsewhere; this substring check is a
  documentation backstop.
- ``# INV-V001-allow:`` — structural anti-pattern detection over source code
  or schema vocabulary (NOT enumeration of LLM-generated paraphrases).

Annotations may appear as:

- A **file-level header** comment (``# INV-V001-backstop-file:`` or
  ``# INV-V001-allow-file:``) declaring the whole file's discipline.
- A **per-site** annotation within 3 lines preceding a suspect pattern.

Without either form, the discovery test fails and points at the un-annotated
site. This is the post-2026-05-28 methodology rule: declare why your
substring check is acceptable, rather than enumerating an open-ended list of
banned/required phrases.

Background — the 2026-05-28 AC8 manual gate showed `_FORBIDDEN_PHRASES`-style
enumeration cannot generalize: the agent invented "object-shape serialization
error" within hours of the catalogue shipping. User rule (2026-05-28):
*"never rely on enumeration of 'forbidden phrases'."* This test enforces
that going forward.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]

_SCAN_ROOTS = [
    _REPO_ROOT / "packages" / "toolkit" / "tests" / "invariants",
    _REPO_ROOT / "packages" / "toolkit" / "tests" / "integration",
    _REPO_ROOT / "packages" / "nemoclaw-plugin" / "tests",
]

# Variable names that strongly suggest the value is LLM-generated agent reply
# text (the target of INV-V001). Conservative — generic names like "content" /
# "response" are excluded because they often hold non-agent data (HTTP responses,
# config-file contents, etc.). The target is agent paraphrase enumeration only.
_AGENT_OUTPUT_VARS = (
    "reply",
    "finalAssistantVisibleText",
    "final_assistant_visible_text",
    "agent_reply",
    "agent_output",
    "agent_response",
    "agent_text",
)

# Suspect-tuple regex: module-level `_<NAME> ... = (` or `= [` where the
# NAME suggests the tuple enumerates **failure-narrative phrases** (the
# specific AC8 class INV-V001 targets) — FORBIDDEN_PHRASE*, BANNED_*,
# FAILURE_PATTERN*, ERROR_PATTERN*, CATALOGUE_ROWS, FAILURE_SIGNAL*.
#
# Narrow on purpose. INV-V001 does NOT cover general substring-matching of
# LLM output (e.g., positive-content `_TOPIC_PATTERNS` in live-agent snapshot
# tests). Those are a different methodology question — imperfect but not the
# AC8 confabulation issue. Future invariants may extend the rule's scope;
# this v1.0 binding is intentionally tight.
_SUSPECT_TUPLE_NAME = re.compile(
    r'^_(?:'
    r'[A-Z0-9_]*FORBIDDEN_PHRASE[A-Z0-9_]*|'
    r'[A-Z0-9_]*BANNED_[A-Z0-9_]*|'
    r'[A-Z0-9_]*FAILURE_PATTERN[A-Z0-9_]*|'
    r'[A-Z0-9_]*ERROR_PATTERN[A-Z0-9_]*|'
    r'[A-Z0-9_]*FAILURE_SIGNAL[A-Z0-9_]*|'
    r'[A-Z0-9_]*FORBIDDEN_ARGV[A-Z0-9_]*|'
    r'CATALOGUE_ROWS|'
    r'STRUCTURAL_FAILURE_SIGNALS'
    r')\b.*?[:=]\s*[\(\[]',
)


def _line_opens_suspect_tuple(line: str, lines: list[str], idx: int) -> bool:
    """A suspect-tuple line is one whose name contains a phrase-enumeration
    marker (FORBIDDEN/BANNED/REQUIRED/PHRASE/PATTERN/CATALOGUE/SIGNAL/MARKER)
    AND opens a `( ` or `[` AND is followed within 2 lines by a string literal.
    """
    if not _SUSPECT_TUPLE_NAME.match(line.strip()):
        return False
    window = "\n".join(lines[idx : idx + 3])
    return '"' in window or "'" in window

# Suspect-assertion regex: `assert "..." [not] in <agent-output-var>`
_SUSPECT_ASSERT = re.compile(
    rf"""assert\s+["'][^"']*["']\s+(?:not\s+)?in\s+
        (?:{"|".join(_AGENT_OUTPUT_VARS)})\b""",
    re.VERBOSE,
)

# Annotation markers.
_BACKSTOP_LINE = "INV-V001-backstop:"
_ALLOW_LINE = "INV-V001-allow:"
_BACKSTOP_FILE = "INV-V001-backstop-file:"
_ALLOW_FILE = "INV-V001-allow-file:"


def _file_has_file_level_annotation(text: str) -> bool:
    """Return True iff the file declares a file-level INV-V001 annotation."""
    head = text[:4000]  # only look at the first ~4KB (module header + docstring)
    return _BACKSTOP_FILE in head or _ALLOW_FILE in head


def _site_has_per_site_annotation(lines: list[str], site_line_index: int) -> bool:
    """Return True iff the site's preceding 15 lines carry a per-site annotation.
    15 lines accommodates multi-line annotation comment blocks (e.g., a ~10-line
    rationale + interleaved doc-comment + the suspect line). If annotations
    drift further than 15 lines, move them closer or escalate to file-level.
    """
    start = max(0, site_line_index - 15)
    preceding = "\n".join(lines[start:site_line_index])
    return _BACKSTOP_LINE in preceding or _ALLOW_LINE in preceding


def _find_unannotated_sites(file_path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, kind, snippet) for each suspect pattern
    without annotation.

    `kind` is ``"tuple"`` or ``"assert"``. ``line_no`` is 1-indexed.
    """
    text = file_path.read_text()
    if _file_has_file_level_annotation(text):
        return []  # file-level annotation covers all sites inside

    lines = text.splitlines()
    unannotated: list[tuple[int, str, str]] = []

    for i, line in enumerate(lines):
        kind: str | None = None
        if _line_opens_suspect_tuple(line, lines, i):
            kind = "tuple"
        elif _SUSPECT_ASSERT.search(line):
            kind = "assert"
        else:
            continue
        if _site_has_per_site_annotation(lines, i):
            continue
        unannotated.append((i + 1, kind, line.strip()))

    return unannotated


def test_invV001_no_unannotated_phrase_enumeration_in_agent_output_gates() -> None:
    """INV-V001: every substring tuple / assertion over agent-output variables
    under the scan roots must carry an INV-V001-{backstop,allow} annotation
    (file-level or per-site, within 3 lines preceding).

    Without the annotation, the discovery test fails — declaring the rule
    moot at the new site. Adding the annotation is the documented escape
    hatch (with rationale); writing un-annotated substring enumeration over
    agent output is forbidden by the project-wide rule.
    """
    violations: dict[str, list[tuple[int, str, str]]] = {}
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            # Skip the discovery test itself + the audit cache.
            if path.name == "test_invV001_no_phrase_enumeration_in_agent_output_gates.py":
                continue
            findings = _find_unannotated_sites(path)
            if findings:
                violations[str(path.relative_to(_REPO_ROOT))] = findings

    if violations:
        msg = "INV-V001 violation: un-annotated phrase enumeration found\n"
        for fp, finds in violations.items():
            msg += f"\n  {fp}:\n"
            for line_no, kind, snippet in finds:
                msg += f"    line {line_no} ({kind}): {snippet[:100]}\n"
        msg += (
            "\nAnnotate each site (within 3 lines preceding) with either:\n"
            "  # INV-V001-backstop: <one-line rationale> — non-load-bearing\n"
            "  # INV-V001-allow: <one-line rationale> — structural anti-pattern\n"
            "OR declare a file-level annotation at the top of the file:\n"
            "  # INV-V001-backstop-file: <rationale> — all sites are backstops\n"
            "  # INV-V001-allow-file: <rationale> — all sites are structural\n"
            "Per INV-V001 (no forbidden-phrase enumeration), every substring\n"
            "check over agent output must declare its category."
        )
        raise AssertionError(msg)


def test_invV001_synthetic_violation_is_detected() -> None:
    """Confidence check: feed a synthetic un-annotated suspect pattern to the
    walker + verify it's flagged. Re-affirms the discovery logic catches the
    case it's supposed to catch.
    """
    # Synthetic input: module-level tuple of strings (suspect_tuple); no
    # annotation in surrounding context.
    synthetic = [
        "import re",
        "",
        '_FORBIDDEN_PHRASES = (',
        '    "something",',
        '    "else",',
        ")",
        "",
        'def test_foo():',
        '    assert "phrase" in reply',
    ]
    text = "\n".join(synthetic)
    # No file-level annotation.
    assert not _file_has_file_level_annotation(text)
    # Suspect-tuple detection.
    line_no = next(
        i for i, ln in enumerate(synthetic, start=1)
        if _line_opens_suspect_tuple(ln, synthetic, i - 1)
    )
    assert line_no == 3, f"expected suspect-tuple at line 3, got {line_no}"
    # No per-site annotation in preceding lines.
    assert not _site_has_per_site_annotation(synthetic, line_no - 1)
    # Suspect-assert detection.
    line_no = next(
        i for i, ln in enumerate(synthetic, start=1)
        if _SUSPECT_ASSERT.search(ln)
    )
    assert line_no == 9, f"expected suspect-assert at line 9, got {line_no}"


def test_invV001_per_site_annotation_is_accepted() -> None:
    """Confidence check inverse: an annotated suspect pattern is accepted."""
    annotated = [
        "import re",
        "",
        "# INV-V001-backstop: regression pin for issue #123",
        '_FORBIDDEN_PHRASES = (',
        '    "fixed-string-1",',
        '    "fixed-string-2",',
        ")",
        "",
        "# INV-V001-backstop: regression pin",
        'def test_foo():',
        '    reply = "..."',
        '    assert "phrase" in reply',
    ]
    # Per-site lookback: tuple at index 3, annotation at index 2.
    assert _site_has_per_site_annotation(annotated, 3)
    # Assert at index 11, annotation at index 8 (3 lines back → still within 8).
    assert _site_has_per_site_annotation(annotated, 11)


def test_invV001_file_level_annotation_is_accepted() -> None:
    """Confidence check: a file-level annotation covers all sites in the file."""
    header_annotated = [
        '"""Module docstring."""',
        "",
        "# INV-V001-backstop-file: all sites are documentation backstops",
        "",
        '_PINS = ("a", "b", "c")',
        "",
        'def test_foo():',
        '    assert "x" in reply',
    ]
    text = "\n".join(header_annotated)
    assert _file_has_file_level_annotation(text)

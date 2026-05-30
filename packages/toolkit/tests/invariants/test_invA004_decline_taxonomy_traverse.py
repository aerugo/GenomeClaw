"""INV-A004 — Decline taxonomy must traverse every layer (DB → Pydantic → TypeBox).

Cross-language schema diff: every Python `CalibrationStatus` and
`DeclineReason` value that exists at the DB column layer must appear in the
nemoclaw-plugin's TypeBox schema for `genomeclaw_pgs_list` and
`genomeclaw_pgs_get`. A Python enum value absent from the TypeBox union
breaks the agent's machine-readable decline signal.

**Expected RED state during Phase 1**: the TypeBox unions for
`calibration_status` and `decline_reason` do not yet exist in
`packages/nemoclaw-plugin/src/index.ts`. These tests fail intentionally
until Phase 2 adds the TypeBox additions; the RED output is documented in
the plan's work-notes. Phase 2 turns both tests GREEN.
"""

from __future__ import annotations

import re
from pathlib import Path

from genomeclaw_toolkit.prep._pgs_qc import CalibrationStatus, DeclineReason

# Resolve the plugin's index.ts from this test file's location. Walks up:
# tests/invariants/test_invA004... → tests → toolkit → packages → repo root.
_PLUGIN_INDEX = (
    Path(__file__).resolve().parents[3]
    / "nemoclaw-plugin"
    / "src"
    / "index.ts"
)


def _extract_typebox_literals_for_field(source: str, field_name: str) -> set[str]:
    """Extract the set of `Type.Literal("...")` values associated with `field_name`.

    The Phase 2 TypeBox shape is expected to be one of:

    - ``field_name: Type.Union([Type.Literal("a"), Type.Literal("b"), ...])``
    - ``field_name: Type.Union([Type.Literal("a"), Type.Literal("b"), Type.Null()])``

    The Null() arm is permitted (the Python side is `CalibrationStatus | None`
    / `DeclineReason | None`) — only the string-literal values are compared.

    Returns an empty set if `field_name` is absent or its union has no
    `Type.Literal` arms — which is the Phase 1 RED state.
    """
    # Find `field_name:` followed by a Type.Union(...) up to the matching ]).
    # Allow whitespace and an optional `Type.Optional(` wrapper.
    pattern = (
        rf'\b{re.escape(field_name)}\s*:\s*'
        r'(?:Type\.Optional\(\s*)?'
        r'Type\.Union\(\s*\[(.*?)\]\s*\)'
    )
    match = re.search(pattern, source, flags=re.DOTALL)
    if not match:
        return set()
    literal_block = match.group(1)
    return set(re.findall(r'Type\.Literal\(\s*"([^"]+)"\s*\)', literal_block))


def test_invA004_decline_taxonomy_traverse_calibration_status() -> None:
    """INV-A004: Python `CalibrationStatus` values must match TypeBox literals."""
    source = _PLUGIN_INDEX.read_text()
    python_values = {member.value for member in CalibrationStatus}
    typebox_values = _extract_typebox_literals_for_field(source, "calibration_status")

    assert python_values == typebox_values, (
        f"INV-A004 violation for `calibration_status`:\n"
        f"  Python enum values: {sorted(python_values)}\n"
        f"  TypeBox literals:   {sorted(typebox_values)}\n"
        f"  in {_PLUGIN_INDEX}"
    )


def test_invA004_decline_taxonomy_traverse_decline_reason() -> None:
    """INV-A004: Python `DeclineReason` values must match TypeBox literals."""
    source = _PLUGIN_INDEX.read_text()
    python_values = {member.value for member in DeclineReason}
    typebox_values = _extract_typebox_literals_for_field(source, "decline_reason")

    assert python_values == typebox_values, (
        f"INV-A004 violation for `decline_reason`:\n"
        f"  Python enum values: {sorted(python_values)}\n"
        f"  TypeBox literals:   {sorted(typebox_values)}\n"
        f"  in {_PLUGIN_INDEX}"
    )

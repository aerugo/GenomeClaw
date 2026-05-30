"""INV-A006 — Plugin Tool-Result Returns Structured Envelopes.

Discovery test: walk the nemoclaw plugin source and assert every failure-path
return goes through a structured `ToolFailureEnvelope` shape (with an explicit
`error_type` discriminator), not a prose-only string.

This is the architectural counterpart of INV-A005 v1.22's quote-verbatim
discipline: the agent can only quote `error_type` if the plugin emits it
structurally. The 2026-05-28 AC8 manual gate showed that prose-only failure
returns force downstream verification into substring-list enumeration of
banned/required phrases (`_FORBIDDEN_PHRASES`), which doesn't generalize
against LLM paraphrase-space.

Without `INV-A006`, a contributor could ship a new tool wrapper that returns
prose-only on failure, and the discipline silently regresses.

The test is structural (parses the plugin source for the `ToolFailureEnvelope`
type + its enum arms + the `failureEnvelopeResult` helper that wraps every
failure-path return). No phrase enumeration.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_SOURCE = (
    _REPO_ROOT / "packages" / "nemoclaw-plugin" / "src" / "index.ts"
)

# The four `error_type` enum values declared by `ToolFailureEnvelope`. Mirror
# of the same set in [test_invA005_no_serialization_bug_confabulation.py];
# the two files declare it independently so this discovery test would fail
# if the plugin extended the enum without updating the walker (or vice versa)
# — and the cross-reference comment below makes the dependency visible.
_EXPECTED_ERROR_TYPES = (
    "placeholder_rejected",
    "host_failure",
    "network_error",
    "http_error",
)


def test_invA006_plugin_source_declares_ToolFailureEnvelope_type() -> None:
    """The plugin source must declare a `ToolFailureEnvelope` discriminated-
    union type. This is the structural type whose shape downstream tests
    (INV-A005 v1.22 walker) read from the trajectory.
    """
    assert _PLUGIN_SOURCE.is_file(), (
        f"plugin source missing at {_PLUGIN_SOURCE}; cannot verify INV-A006"
    )
    src = _PLUGIN_SOURCE.read_text()
    assert "type ToolFailureEnvelope" in src or "interface ToolFailureEnvelope" in src, (
        "INV-A006: plugin source must declare a `ToolFailureEnvelope` "
        "TypeScript type. Found neither `type ToolFailureEnvelope` nor "
        "`interface ToolFailureEnvelope` in index.ts."
    )


def test_invA006_plugin_source_declares_all_four_error_type_enum_values() -> None:
    """The `ToolFailureEnvelope` type's discriminated union must include all
    four declared `error_type` enum values: placeholder_rejected, host_failure,
    network_error, http_error.

    If the plugin extends the enum, this test should be updated in lockstep
    with the INV-A005 walker's `_ERROR_TYPE_ENUM_VALUES` (cross-referenced
    via comment in both files).
    """
    src = _PLUGIN_SOURCE.read_text()
    # Look for `error_type: "<value>"` literal type declarations in the union.
    for value in _EXPECTED_ERROR_TYPES:
        pattern = rf'error_type:\s*"{value}"'
        assert re.search(pattern, src), (
            f"INV-A006: plugin source must declare `error_type: \"{value}\"` as "
            f"one of the `ToolFailureEnvelope` union arms. The INV-A005 v1.22 "
            f"walker expects this enum value to exist in the trajectory's "
            f"toolResult envelopes."
        )


def test_invA006_failure_helpers_route_through_failureEnvelopeResult() -> None:
    """The three failure-path helpers (`rejectIfPlaceholder`, `wrapHostResponse`,
    `safeCall`/`safePost` catch blocks) must call `failureEnvelopeResult` for
    every failure-path return. No callsite may invoke `failedTextResult` with
    a bare prose string directly; the wrapper enforces the envelope shape.

    The check is heuristic: count `failedTextResult(` callsites in `index.ts`
    that are NOT inside `failureEnvelopeResult`'s body. The only acceptable
    location for a raw `failedTextResult(` is inside `failureEnvelopeResult`
    itself (where it constructs the SDK envelope wrapping the JSON-stringified
    structured envelope).
    """
    src = _PLUGIN_SOURCE.read_text()
    assert "function failureEnvelopeResult" in src, (
        "INV-A006: plugin source must define a `failureEnvelopeResult` helper "
        "that wraps `ToolFailureEnvelope` values into the SDK's failedTextResult "
        "envelope. Without this central wrapper, individual failure-path "
        "returns can't be audited."
    )

    # Strip block comments + line comments before locating callsites, so
    # JSDoc references to `failedTextResult(reason, details?)` (documentation,
    # not code) don't trigger false positives.
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", src)
    stripped = re.sub(r"^\s*//.*$", "", stripped, flags=re.MULTILINE)

    # Identify `failedTextResult(` callsites + check they're inside the wrapper.
    # We use a coarse rule: find the byte range of `failureEnvelopeResult`'s
    # function body + flag any `failedTextResult(` callsite outside it.
    fer_match = re.search(
        r"function failureEnvelopeResult\b.*?^\}",
        stripped,
        re.DOTALL | re.MULTILINE,
    )
    assert fer_match is not None, (
        "INV-A006: `failureEnvelopeResult`'s function body could not be parsed. "
        "Did the formatter change the closing-brace convention?"
    )
    fer_body_start, fer_body_end = fer_match.span()

    # Find all `failedTextResult(` callsites + their offsets within the stripped
    # source (no comments).
    callsites = [
        m.start() for m in re.finditer(r"\bfailedTextResult\s*\(", stripped)
    ]
    outside = [
        offset for offset in callsites
        if not (fer_body_start <= offset <= fer_body_end)
    ]
    assert not outside, (
        f"INV-A006: {len(outside)} `failedTextResult(` callsite(s) found "
        f"outside `failureEnvelopeResult`'s body (at byte offsets {outside!r} "
        f"in the comment-stripped source). Every failure-path return must "
        f"route through `failureEnvelopeResult` so the JSON `ToolFailureEnvelope` "
        f"shape is enforced. A bare `failedTextResult(prose)` call means a tool "
        f"wrapper emits prose-only on failure — INV-V001 forbids this "
        f"(substring enumeration would be required to interpret it downstream)."
    )

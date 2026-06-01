"""Phase 2 (host-profile-personal-context) — profile renderer tests.

The renderers write to the shared rich console; the tests inject a
``StringIO``-backed ``Console`` so the rendered text is capturable and
ANSI-free. The completeness renderer must reuse the established status
glyphs (``✓`` / ``~`` / ``✗``) rather than inventing new visual vocabulary.
"""

from __future__ import annotations

import io

from rich.console import Console

from genomeclaw_toolkit._cli.commands.host import (
    _ProfileCompletenessPayload,
    _ProfileShowPayload,
)
from genomeclaw_toolkit._cli.console import reset_console, set_console
from genomeclaw_toolkit._cli.renderers.host import render_profile, render_profile_completeness
from genomeclaw_toolkit.schemas.host_profile import HostProfile

_META = {"created_at": "2026-05-31T00:00:00Z", "updated_at": "2026-05-31T00:00:00Z"}


def _capture(render, payload) -> str:
    buf = io.StringIO()
    set_console(Console(file=buf, force_terminal=False, no_color=True, width=100))
    try:
        render(payload)
    finally:
        reset_console()
    return buf.getvalue()


def _fixture_profile() -> HostProfile:
    return HostProfile.model_validate(
        {
            "schema_version": "host_profile/1.0",
            "meta": dict(_META),
            "identity": {
                "sex_assigned_at_birth": "male",
                "date_of_birth": "1988-11-12",
                "ancestry": {"groups": ["european"]},
            },
            "biometrics": {"height_cm": 195.0, "weight_kg": 104.0},
        }
    )


def test_render_profile_snapshot() -> None:
    """`render_profile` surfaces the key section labels + derived ancestry code."""
    profile = _fixture_profile()
    payload = _ProfileShowPayload(
        profile=profile,
        missing=False,
        completeness={"identity": "complete", "lifestyle": "missing"},
        init_command=None,
    )
    out = _capture(render_profile, payload)
    assert "Identity" in out
    assert "Biometrics" in out
    assert "Lifestyle" in out
    assert "Medical history" in out
    assert "Family history" in out
    # The derived 1000G code surfaces (european → EUR).
    assert "EUR" in out


def test_render_profile_completeness_marks_missing_with_caution_glyph() -> None:
    """Missing sections render with the established `✗` caution glyph."""
    payload = _ProfileCompletenessPayload(
        sections={"identity": "complete", "medical_history.medications": "missing"},
        missing=False,
    )
    out = _capture(render_profile_completeness, payload)
    assert "✗" in out  # missing marker (established fail glyph)
    assert "✓" in out  # complete marker
    assert "medical_history.medications" in out

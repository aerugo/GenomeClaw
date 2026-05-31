"""INV-C004 (provisional) — captured health-interpretation traces call the host profile.

Once the Phase-4 prompt change ships, every captured demo trace that is a
*health-interpretation* turn (heuristic: it invokes `genomeclaw_gene` or
`genomeclaw_pgs_compute`) MUST also invoke `genomeclaw_host_profile` — the
agent retrieves the user's self-reported context before interpreting their
genome (Step 1.5).

This is a forward-looking gate. Traces dated **before** the land date
(`_PHASE4_LAND_DATE`) predate the prompt change — the tool didn't exist in
the prompt protocol then — so they are skipped as historical artifacts.
The gate becomes load-bearing for any trace captured on/after the land
date (i.e. after the canonical demo battery is re-run against the rebuilt
sandbox image). With no qualifying traces yet, the test passes and reports
how many historical traces it skipped, so a silent zero-coverage state is
visible rather than mistaken for a pass.

INV-V001 note: this is *structural* trace inspection — it checks for the
presence of tool-call names in the recorded trajectory file, not a
substring scan of the agent's natural-language reply. Allowed as a
load-bearing gate under INV-V001 (the target is the tool-call record).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORTS_DIR = _REPO_ROOT / "docs" / "reports"

# The boundary after which host-profile retrieval is mandatory in captured
# traces. Set to the day after the Phase-4 prompt landed (2026-05-31) so
# every pre-prompt trace (all dated ≤ 2026-05-31) is treated as historical.
# When the demo battery is re-run, its traces will be dated ≥ this boundary
# and the gate engages.
_PHASE4_LAND_DATE = date(2026, 6, 1)

_DEMO_DIR_DATE = re.compile(r"demo-(\d{4})-(\d{2})-(\d{2})-logs")


def _trace_date(trace_path: Path) -> date | None:
    """Parse the capture date from the ``demo-YYYY-MM-DD-logs/`` parent dir."""
    for part in trace_path.parts:
        m = _DEMO_DIR_DATE.fullmatch(part)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _is_health_interpretation(text: str) -> bool:
    """A trace is a health-interpretation turn if it queries gene or PRS-compute."""
    return "genomeclaw_gene" in text or "genomeclaw_pgs_compute" in text


def test_invC004_health_interpretation_traces_call_host_profile() -> None:
    """Post-land health-interpretation traces must invoke genomeclaw_host_profile."""
    if not _REPORTS_DIR.is_dir():
        pytest.skip("no docs/reports directory")

    skipped_historical = 0
    checked = 0
    violations: list[str] = []

    for trace_path in sorted(_REPORTS_DIR.rglob("*.trace.json")):
        captured = _trace_date(trace_path)
        if captured is None or captured < _PHASE4_LAND_DATE:
            skipped_historical += 1
            continue
        text = trace_path.read_text()
        if not _is_health_interpretation(text):
            continue
        checked += 1
        if "genomeclaw_host_profile" not in text:
            violations.append(str(trace_path.relative_to(_REPO_ROOT)))

    assert not violations, (
        "INV-C004: these post-land health-interpretation traces never called "
        "genomeclaw_host_profile (Step 1.5):\n  " + "\n  ".join(violations)
    )
    # Visibility: surface coverage so a vacuous pass (zero post-land traces)
    # isn't mistaken for real enforcement. Re-run the demo battery against the
    # rebuilt sandbox to populate post-land traces.
    print(
        f"\nINV-C004 trace-walk: checked {checked} post-land health-interpretation "
        f"trace(s); skipped {skipped_historical} historical (pre-{_PHASE4_LAND_DATE})."
    )

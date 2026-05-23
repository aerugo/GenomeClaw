"""Phase 1 RED + Phase 2 GREEN — pin the validation boundary.

The 2026-05-23 AMD-question agent invocation hit ``HTTP 422`` twice on
``POST /v1/pgs/compute`` (once for AMD PGS004606, once for glaucoma
PGS000137). The agent gracefully degraded, but the user-facing capability
was broken. Phase 1 reproduced the failure shape as RED tests; Phase 2
lowered ``rationale: min_length`` from 50 to 10 + this file now pins the
new boundary.

Four boundary checks:

1. Agent-typical short rationale (41 chars) — accepted post-fix (was RED).
2. Empty rationale (0 chars) — still 422 (INV-A003 non-empty floor).
3. 9-char rationale (boundary -1) — 422.
4. 10-char rationale (boundary) — accepted.
5. 49-char rationale (above old threshold) — accepted (was 422 on old main).

Plus extra-fields rejection (INV-P002 `extra="forbid"`) + happy path.

Plan: [docs/plans/active/agent-prs-compute-fix/phases/phase-2.md](../../../../docs/plans/active/agent-prs-compute-fix/phases/phase-2.md)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from genomeclaw_toolkit.prep.run_id import update_current_symlink
from genomeclaw_toolkit.prep.store import create_store
from genomeclaw_toolkit.schemas import SCHEMA_VERSION
from genomeclaw_toolkit.service.app import build_app
from genomeclaw_toolkit.service.pgs_compute_orchestrator import (
    create_pgs_compute_tasks_db_if_missing,
)

_RUN_ID = "2026-05-23T00-00-00Z-pgsfix01"

# A representative agent-generated short rationale, typical of what gpt-5.5
# emits when computing two PRSs in the same turn (e.g. AMD + glaucoma).
# 41 chars — below the current ``minLength=50`` threshold.
_AGENT_SHORT_RATIONALE = "Canonical AMD PRS; smoker-relevant trait."

# A canonically-shaped rationale that meets the current threshold.
_AGENT_LONG_RATIONALE = (
    "Canonical AMD PRS. PGS004606 has the largest cross-ancestry training "
    "set (UKB + DiscovEHR + IGAP); considered PGS000060 but rejected for "
    "smaller validation cohort."
)


def _stage_run(derived_root: Path) -> Path:
    """Stage a minimal derived/<run-id>/ with manifest + tasks DB."""
    run_dir = derived_root / _RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {"run_id": _RUN_ID, "schema_version": SCHEMA_VERSION, "sample_id": "pgsfix-fixture"}
        )
    )
    store_path = run_dir / "variants.duckdb"
    create_store(store_path)
    create_pgs_compute_tasks_db_if_missing(run_dir / "pgs_compute_tasks.sqlite")
    update_current_symlink(derived_root, _RUN_ID)
    return run_dir


def test_pgs_compute_accepts_agent_short_rationale(tmp_path: Path) -> None:
    """**RED on current main**: a 41-char agent-typical rationale gets 422.

    The fix lowers the ``rationale`` minLength from 50 to e.g. 10 so
    agent-generated brevity doesn't break the compute path. After the
    fix, this test passes (202).

    Captures the failure shape from the 2026-05-23 AMD-question agent
    invocation: the agent computed two PRSs in the same turn (AMD +
    glaucoma); under reasoning pressure each rationale was abbreviated
    below the 50-char threshold; both 422'd; agent degraded with "I
    don't have a percentile for you yet".
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    run_dir = _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": _AGENT_SHORT_RATIONALE,  # 41 chars; agent-typical
                "requested_for_question": "do I have any increased risk of losing eye sight when I age?",
            },
        )

    # POST-FIX expectation:
    assert response.status_code == 202, (
        f"agent-typical short rationale ({len(_AGENT_SHORT_RATIONALE)} chars) should be "
        f"accepted after the threshold is lowered; got {response.status_code}.\n"
        f"body: {response.text}"
    )

    body = response.json()
    assert body["status"] in ("queued", "running")
    assert body["pgs_id"] == "PGS004606"

    # Side-effect: task row landed in pgs_compute_tasks.sqlite.
    conn = sqlite3.connect(str(run_dir / "pgs_compute_tasks.sqlite"))
    try:
        rows = conn.execute("SELECT pgs_id, status FROM pgs_compute_tasks").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1


def test_pgs_compute_still_rejects_empty_rationale_after_fix(tmp_path: Path) -> None:
    """Even after lowering the threshold, rationale="" must remain 422.

    INV-A003 requires a non-empty rationale (the floor is non-empty,
    not the specific 50-char threshold). This test pins that floor so a
    future "lower the threshold" change doesn't accidentally accept
    empty strings.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": "",  # INV-A003 floor violation
                "requested_for_question": "?",
            },
        )

    assert response.status_code == 422, response.text


def test_pgs_compute_long_rationale_still_accepted(tmp_path: Path) -> None:
    """Sanity-check: rationales above the current threshold continue to be accepted.

    Regression guard: the fix shouldn't break the happy path.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": _AGENT_LONG_RATIONALE,
                "requested_for_question": "do I have AMD risk?",
            },
        )

    assert response.status_code == 202, response.text


def test_pgs_compute_rejects_extra_fields(tmp_path: Path) -> None:
    """Sanity-check: ``extra="forbid"`` rejects unknown fields with 422.

    If a future plugin change accidentally adds a field to the request
    body (e.g. mirroring ``source_pgs_id`` from the wrapper), this is
    the test that catches it before it reaches production.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": _AGENT_LONG_RATIONALE,
                "requested_for_question": "?",
                "source_pgs_id": "PGS004606",  # not in the request schema
            },
        )

    assert response.status_code == 422, response.text


def test_pgs_compute_49_char_rationale_accepted_post_fix(tmp_path: Path) -> None:
    """Phase 2 boundary check: rationales above the old 50-char threshold still accepted.

    On old main (Phase 1 RED-pinned), 49 chars → 422 because the threshold
    was 50. Phase 2 lowered the threshold to 10, so 49 chars is now well
    above the floor + lands 202. Regression guard against an accidental
    re-tightening that would re-break the AMD-question agent path.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    rationale_49 = "x" * 49
    assert len(rationale_49) == 49

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": rationale_49,
                "requested_for_question": "?",
            },
        )

    assert response.status_code == 202, response.text


def test_pgs_compute_9_char_rationale_rejected_post_fix(tmp_path: Path) -> None:
    """Phase 2 boundary check: 9-char rationale is one below the new threshold → 422.

    Pins the new 10-char floor. If a future widening accidentally lowers
    the threshold below 10 (or removes it), this test catches it before
    the agent's compute path silently accepts trivially-empty rationales
    and INV-A003's "alternatives considered + why this one" framing
    degenerates to a single token.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    rationale_9 = "x" * 9
    assert len(rationale_9) == 9

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": rationale_9,
                "requested_for_question": "?",
            },
        )

    assert response.status_code == 422, response.text


def test_pgs_compute_10_char_rationale_accepted_post_fix(tmp_path: Path) -> None:
    """Phase 2 boundary check: exactly 10 chars → 202.

    Pins the new threshold's accept side. Pair with the 9-char rejection
    test above to fully constrain the boundary at 10.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    _stage_run(derived_root)

    rationale_10 = "x" * 10
    assert len(rationale_10) == 10

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        response = client.post(
            "/v1/pgs/compute",
            json={
                "pgs_id": "PGS004606",
                "trait_label": "age-related macular degeneration",
                "rationale": rationale_10,
                "requested_for_question": "?",
            },
        )

    assert response.status_code == 202, response.text

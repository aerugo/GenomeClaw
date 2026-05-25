"""INV-R002 — `pgs_compute_tasks` ↔ `pgs_scores` cross-table consistency.

Closes the failure mode the investigate-pgs-compute-ack-without-row
plan diagnosed and fixed: pre-fix, every `pgs_compute_tasks` row could
reach `status=done` without a matching `pgs_scores` row (because the
missing-config path was treated as a no-op success). Post-fix, the
worker either writes the row OR transitions to `failed` with a
structured error — never `done`-without-row.

This invariant test walks any provided derived-run dir's task tracker
+ score table and asserts the structural rule that the pre-fix bug
violated. If a future regression reintroduces the no-op-success path,
this test fails loudly with a per-task offender list.

Walks every dir under `/Volumes/Genome_Work/genomeclaw/derived/` that
looks like a run-id directory (skips gracefully when the operator's
mount isn't present — keeps CI green without the real data). The
operator's affected run `2026-05-24T12-52-11Z-f2dae2` carries 11
legacy `done`-without-row rows from sessions prior to the fix; the
test special-cases that historical state via the
`GENOMECLAW_PGS_LEGACY_OK_RUN_IDS` env var so the rule can bind for
post-fix runs without retroactively failing on the diagnostic record.

Tracks the [investigate-pgs-compute-ack-without-row plan]
(../../../../../docs/plans/active/investigate-pgs-compute-ack-without-row/).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import duckdb
import pytest

# Default search location for the operator's derived runs. Override with
# the env var (used by CI to skip cleanly when the mount isn't there).
_DERIVED_ROOT = Path(
    os.environ.get("GENOMECLAW_DERIVED_DIR", "/Volumes/Genome_Work/genomeclaw/derived")
)

# Comma-separated run-ids that carry pre-fix legacy state and are
# allowed to violate the rule. Defaults to the one affected run from
# the 2026-05-24 demo session — that historical state is preserved as
# the diagnostic record motivating this plan. Anyone re-running the
# pipeline on that run after the fix can drop the run-id from this
# allowlist + the new computes will land cleanly.
_LEGACY_OK_RUN_IDS = set(
    s.strip()
    for s in os.environ.get(
        "GENOMECLAW_PGS_LEGACY_OK_RUN_IDS",
        # Two affected runs from sessions prior to the fix:
        # - 2026-05-24T11-05-35Z-25dfaa: 2 done-without-row rows
        # - 2026-05-24T12-52-11Z-f2dae2: 11 done-without-row rows (the
        #   primary diagnostic record cited in the RCA brief)
        "2026-05-24T11-05-35Z-25dfaa,2026-05-24T12-52-11Z-f2dae2",
    ).split(",")
    if s.strip()
)


def _is_run_dir(path: Path) -> bool:
    """Heuristic: directory whose name looks like an ISO timestamp + suffix."""
    if not path.is_dir():
        return False
    name = path.name
    return name.startswith("2") and "T" in name and "Z" in name


def _discover_runs() -> list[Path]:
    """Find every plausible run dir under the configured derived root."""
    if not _DERIVED_ROOT.exists():
        return []
    return sorted(p for p in _DERIVED_ROOT.iterdir() if _is_run_dir(p))


def _walk_run(run_dir: Path) -> tuple[list[dict], set[str], set[str]]:
    """Return (done_tasks, pgs_ids_with_row, pgs_ids_with_non_null_percentile).

    `done_tasks` is a list of dicts {task_id, pgs_id, status, error}.
    The set returns are convenience for the assertion logic.
    """
    task_db = run_dir / "pgs_compute_tasks.sqlite"
    score_db = run_dir / "variants.duckdb"
    if not task_db.exists() or not score_db.exists():
        return [], set(), set()

    with sqlite3.connect(str(task_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT task_id, pgs_id, status, error FROM pgs_compute_tasks "
            "WHERE status = 'done'"
        ).fetchall()
    done_tasks = [dict(r) for r in rows]

    pgs_ids_with_row: set[str] = set()
    pgs_ids_with_non_null_percentile: set[str] = set()
    try:
        with duckdb.connect(str(score_db), read_only=True) as conn:
            for pgs_id, percentile in conn.execute(
                "SELECT pgs_id, percentile_in_user_ancestry FROM pgs_scores"
            ).fetchall():
                pgs_ids_with_row.add(pgs_id)
                if percentile is not None:
                    pgs_ids_with_non_null_percentile.add(pgs_id)
    except duckdb.CatalogException:
        # pgs_scores table doesn't exist yet — treat as empty.
        pass

    return done_tasks, pgs_ids_with_row, pgs_ids_with_non_null_percentile


@pytest.mark.skipif(
    not _DERIVED_ROOT.exists(),
    reason=(
        "operator's derived dir not mounted "
        "(GENOMECLAW_DERIVED_DIR points at a missing path); "
        "invariant test skips cleanly when there's no data to walk"
    ),
)
def test_invR002_pgs_compute_done_implies_pgs_scores_row() -> None:
    """For every pgs_compute_tasks row with status='done', pgs_scores has a row.

    Walks every discoverable run directory; collects offenders across
    all of them; reports once. Allowlisted legacy run-ids (the pre-fix
    diagnostic record) are excluded.
    """
    runs = _discover_runs()
    if not runs:
        pytest.skip(f"no run directories under {_DERIVED_ROOT}")

    offenders: list[str] = []
    for run_dir in runs:
        if run_dir.name in _LEGACY_OK_RUN_IDS:
            continue
        done_tasks, _row_pgs_ids, percentile_pgs_ids = _walk_run(run_dir)
        for task in done_tasks:
            pgs_id = task["pgs_id"]
            if pgs_id not in percentile_pgs_ids:
                offenders.append(
                    f"  run={run_dir.name} task={task['task_id']} pgs_id={pgs_id}: "
                    f"status=done but no pgs_scores row with non-null percentile"
                )

    assert not offenders, (
        f"INV-R002 violations — pgs_compute_tasks marked status=done without a "
        f"matching pgs_scores row carrying a non-null percentile. The exact "
        f"failure mode the investigate-pgs-compute-ack-without-row plan fixed; "
        f"a regression has reintroduced the inconsistency:\n"
        + "\n".join(offenders)
    )

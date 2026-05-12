"""Phase 7 — ``genomeclaw --help`` cold-start performance gate.

The strict `prep/ → _cli/` boundary (Phase 1) ensures the CLI never
transitively imports heavy bio deps (duckdb, pysam, cyvcf2) just to
render ``--help``. This test pins the budget.

The realistic target is ``< 1.0 s`` on a typical developer host
(Phase-1 measurement was 0.18 s). The aspirational 200 ms target from
the original plan pre-dated the Typer + Pydantic + rich dependency
footprint; the looser 1.0 s bound guards against regressions without
chasing absolute timing on hardware we don't control.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_BUDGET_SEC = 1.0


def _resolve_genomeclaw_entrypoint() -> list[str]:
    """Find the installed ``genomeclaw`` script (skips test on bare installs)."""
    # Preferred: the script installed alongside the test runner's python.
    venv_script = Path(sys.executable).parent / "genomeclaw"
    if venv_script.exists():
        return [str(venv_script)]
    # Fallback: search PATH.
    on_path = shutil.which("genomeclaw")
    if on_path:
        return [on_path]
    pytest.skip("genomeclaw entrypoint not installed in the test environment")


def test_genomeclaw_help_cold_start_under_budget() -> None:
    """``genomeclaw --help`` runs under the cold-start budget."""
    entrypoint = _resolve_genomeclaw_entrypoint()
    cmd = [*entrypoint, "--help"]
    start = time.monotonic()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        check=False,
        timeout=10,
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 0, (
        f"--help exited non-zero ({proc.returncode}); "
        f"stderr={proc.stderr.decode('utf-8', errors='replace')[:400]!r}"
    )
    assert elapsed < _BUDGET_SEC, (
        f"cold start took {elapsed:.3f}s; budget is {_BUDGET_SEC}s. "
        "Likely cause: a new heavy module (duckdb / pysam / cyvcf2) is being "
        "imported at top level of ``_cli`` or one of its dependencies. "
        "Audit the import graph from genomeclaw_toolkit._cli."
    )

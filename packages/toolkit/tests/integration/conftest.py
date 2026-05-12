"""Integration-test-only fixtures.

Session-scoped synthetic VCF / BAM / BED fixtures live in the top-level
[`tests/conftest.py`](../conftest.py) so they can be consumed by tests in
other directories (provenance, perf, etc.). The CLI-runner helpers
(``cli_runner`` + ``invoke_cli``) also live there for the same reason.
Per-test layout helpers stay here.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def genomeclaw_layout(tmp_path: Path) -> dict[str, Path]:
    """A per-test four-mount layout matching the architecture's bind-mount discipline.

    Tests can use this to mimic the production ``/mnt/genomeclaw/{raw,
    reference, derived, scratch}`` layout without colliding across runs.
    """
    raw = tmp_path / "raw"
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    scratch = tmp_path / "scratch"
    for d in (raw, reference, derived, scratch):
        d.mkdir(parents=True)
    return {"raw": raw, "reference": reference, "derived": derived, "scratch": scratch}

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
def genomeclaw_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A per-test five-mount layout matching the architecture's split-scratch discipline.

    Tests can use this to mimic the production ``/mnt/genomeclaw/{raw,
    reference, derived, scratch}`` layout without colliding across runs.

    Phase A of [annotate-shard-resilience](../../../docs/plans/active/annotate-shard-resilience/development-plan.md)
    introduces a second scratch tier — ``ephemeral_scratch`` — that the
    orchestrators route shard_scratch dirs through. The fixture provisions
    it as a separate sibling directory and exports its path via the
    ``GENOMECLAW_EPHEMERAL_SCRATCH_DIR`` env var, which
    ``ephemeral_scratch_base()`` reads at orchestrator-call time.

    Keys:

    - ``scratch``: persistent scratch (``_cache/dbsnp/``, ``_cache/sha256/``,
      and post-Phase-B per-shard caches). Bind-mounted in production.
    - ``ephemeral_scratch``: per-step scratch (shard_scratch dirs).
      Container-local in production (off virtiofs); test fixture path here.
    """
    raw = tmp_path / "raw"
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    scratch = tmp_path / "scratch"
    ephemeral_scratch = tmp_path / "ephemeral_scratch"
    for d in (raw, reference, derived, scratch, ephemeral_scratch):
        d.mkdir(parents=True)
    monkeypatch.setenv("GENOMECLAW_EPHEMERAL_SCRATCH_DIR", str(ephemeral_scratch))
    return {
        "raw": raw,
        "reference": reference,
        "derived": derived,
        "scratch": scratch,
        "ephemeral_scratch": ephemeral_scratch,
    }

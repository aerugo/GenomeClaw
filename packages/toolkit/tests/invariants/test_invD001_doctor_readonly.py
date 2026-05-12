"""INV-D001 — ``genomeclaw host doctor`` must never mutate raw data.

Doctor is a read-only diagnostic. The pipeline-readiness extension
expands its filesystem reach (it now walks ``reference/``, ``raw/``,
and ``derived/`` looking for files), which makes regression risk
higher than the original host-layout-only version. This invariant
test pins the contract: snapshot every file under ``raw/<sample>/``
before doctor runs; assert each one's mtime + content hash is
unchanged afterwards.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """``(rel_path → (mtime_ns, sha256))`` for every file under ``root``."""
    snap: dict[str, tuple[int, str]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root))
            snap[rel] = (p.stat().st_mtime_ns, _hash_file(p))
    return snap


class _StubRunner:
    def run(self, cmd: list[str]) -> tuple[int, str, str]:
        return 0, "", ""


def test_invD001_doctor_does_not_mutate_raw(tmp_path: Path) -> None:
    """INV-D001: doctor leaves every file under ``raw/<sample>/`` byte-identical."""
    from genomeclaw_toolkit.prep.doctor import doctor

    raw = tmp_path / "raw"
    reference = tmp_path / "reference"
    derived = tmp_path / "derived"
    scratch = tmp_path / "scratch"
    for d in (raw, reference, derived, scratch):
        d.mkdir()

    sample = raw / "MPNRGLQ2K"
    sample.mkdir()
    (sample / "MPNRGLQ2K.vcf.gz").write_bytes(b"VCF-MOCK-CONTENT" * 64)
    (sample / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"TBI-MOCK" * 16)
    (sample / "MPNRGLQ2K.cram").write_bytes(b"CRAM-MOCK" * 256)

    # Stage a derived run too — doctor walks derived/, so changes there
    # could leak under provenance reads. raw/ snapshot is the primary
    # contract per INV-D001.
    run = derived / "run-1"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "schema_version": "0.2",
                "sample_id": "MPNRGLQ2K",
                "input": {"vcf": "/x", "sha256": "0" * 64},
                "tools": {},
                "params": {},
                "outputs": {},
                "created_at": "2026-05-12T00:00:00Z",
            }
        )
    )
    (run / "provenance.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "schema_version": "0.2",
                "steps": [
                    {
                        "step": "ingest",
                        "tool": "x",
                        "tool_version": "x",
                        "started_at": "2026-05-12T00:00:00Z",
                        "completed_at": "2026-05-12T00:00:00Z",
                        "inputs": [{"path": "/x", "sha256": "0" * 64}],
                    }
                ],
            }
        )
    )

    snap_before = _snapshot(raw)

    doctor(
        paths={"raw": raw, "reference": reference, "derived": derived, "scratch": scratch},
        runner=_StubRunner(),
    )

    snap_after = _snapshot(raw)
    assert snap_before == snap_after, (
        "INV-D001 violated: doctor changed at least one file under raw/. "
        f"diff={set(snap_before.items()) ^ set(snap_after.items())}"
    )

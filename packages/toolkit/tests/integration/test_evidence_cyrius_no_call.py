"""Evidence resolver round-trip for `cyrius_no_call:<path>` refs.

Phase 1 of cyp2d6-no-call-finding wired the indeterminate finding into
`findings.duckdb` with `evidence_ref="cyrius_no_call:<absolute_path>"`.
The agent's `genomeclaw_evidence` tool resolves the ref via
`GET /v1/evidence/{ref}` → `resolve_evidence()`. Without a registered
`cyrius_no_call` handler the resolver raises `UnknownEvidenceKindError`
(400) and the agent gets a dead-link finding.

Phase 2 adds the resolver. These tests pin the contract:

- The resolver returns an `EvidenceRecord`-compatible dict when the
  sentinel file exists.
- The body explicitly carries the "do not interpret as Normal
  Metabolizer" rule so the agent rendering the evidence cannot infer a
  diplotype.
- Per INV-P002, the response does NOT include the raw Cyrius output
  block — that data lives on disk for audit, but the summary surface
  the agent reads is minimal-sufficient.
- Missing sentinel returns None (route turns into 404).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.service.store import (
    UnknownEvidenceKindError,
    resolve_evidence,
)


def _write_sentinel(run_dir: Path, *, sample_id: str = "MPNRGLQ2K") -> Path:
    """Write a synthetic `cyp2d6_no_call_envelope.json` mirroring the wrapper's shape."""
    sentinel = run_dir / "cyp2d6_no_call_envelope.json"
    sentinel.write_text(
        json.dumps(
            {
                "cyp2d6_status": "no_call",
                "sample_id": sample_id,
                "diplotype": None,
                "filter_status": "NO_CALL",
                "raw_cyrius_output": {
                    sample_id: {"Genotype": "", "Filter": "NO_CALL"}
                },
                "provenance": {
                    "source_path": "/dummy/sample.bam",
                    "source_sha256": "f" * 64,
                    "tool": "cyrius",
                    "tool_version": "1.1.1",
                    "params_json": "{}",
                    "schema_version": "v0.2",
                    "created_at": "2026-05-25T00:00:00+00:00",
                },
            }
        )
    )
    return sentinel


def test_evidence_resolver_handles_cyrius_no_call_ref(tmp_path: Path) -> None:
    """Resolver returns an EvidenceRecord dict for a valid `cyrius_no_call:<path>` ref."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = _write_sentinel(run_dir)

    record = resolve_evidence(run_dir=run_dir, ref=f"cyrius_no_call:{sentinel}")

    assert record is not None
    assert record["kind"] == "cyrius_no_call"
    assert record["id"] == str(sentinel)
    assert record["body"]
    assert record["source"]


def test_evidence_resolver_cyrius_no_call_body_forbids_normal_metabolizer(
    tmp_path: Path,
) -> None:
    """INV-C001 v1.7 / INV-E001: the evidence body explicitly forbids the NM inference.

    The agent reads `body` verbatim into its evidence rendering. If the
    body omits the structural rule, the agent could pattern-match the
    indeterminate state as "no PGx data" and infer Normal Metabolizer
    silently. This test pins the body's explicit guard.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = _write_sentinel(run_dir)

    record = resolve_evidence(run_dir=run_dir, ref=f"cyrius_no_call:{sentinel}")

    assert record is not None
    assert "Normal Metabolizer" in record["body"] or (
        "normal metabolizer" in record["body"].lower()
    ), (
        f"INV-C001 v1.7: evidence body must explicitly name the 'Normal Metabolizer' "
        f"phrase it forbids; got body={record['body']!r}"
    )
    assert "indeterminate" in record["body"].lower() or "no-call" in record["body"].lower()


def test_invP002_evidence_resolver_excludes_raw_cyrius_output(tmp_path: Path) -> None:
    """INV-P002: response is minimal-sufficient; raw_cyrius_output stays on disk.

    The sentinel JSON carries the full Cyrius output for the audit trail
    on disk. The evidence resolver's response is the agent-facing surface,
    and per INV-P002 must be minimal-sufficient — not echo back the raw
    block.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = _write_sentinel(run_dir)

    record = resolve_evidence(run_dir=run_dir, ref=f"cyrius_no_call:{sentinel}")

    assert record is not None
    body_lower = record["body"].lower()
    assert "raw_cyrius_output" not in record
    assert "raw_cyrius_output" not in body_lower
    # The Cyrius JSON inner-key shouldn't leak into the body either.
    assert '"genotype": ""' not in body_lower


def test_evidence_resolver_cyrius_no_call_missing_sentinel_returns_none(
    tmp_path: Path,
) -> None:
    """When the sentinel file doesn't exist, the resolver returns None (→ 404)."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    missing_path = run_dir / "no_such_sentinel.json"

    record = resolve_evidence(run_dir=run_dir, ref=f"cyrius_no_call:{missing_path}")

    assert record is None


def test_evidence_resolver_rejects_unknown_kind_still(tmp_path: Path) -> None:
    """Other unknown kinds still raise — the Phase 2 addition is narrow."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(UnknownEvidenceKindError):
        resolve_evidence(run_dir=run_dir, ref="some_other_kind:abc")

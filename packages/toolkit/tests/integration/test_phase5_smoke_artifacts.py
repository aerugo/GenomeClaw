"""Phase 5 — verification gates against ``bin/genomeclaw-prs-smoke`` artifacts.

These tests don't drive compute. They verify that the smoke driver has
produced a healthy set of measurements + invariant audits + cache files
under ``$GENOMECLAW_PHASE5_SMOKE_DIR``. Without that env var set, every
test in this file auto-skips (see conftest's ``needs_phase5_smoke_artifacts``
gate).

To run them:

.. code-block:: bash

    bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
    export GENOMECLAW_PHASE5_SMOKE_DIR=/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<UTC-iso>
    uv run pytest -m needs_phase5_smoke_artifacts -v

The 10 acceptance gates land here. Each cites the phase-5.md AC it
verifies, plus the invariant(s) under load.

Phase-5.md: [docs/plans/active/prs-input-coverage-fill/phases/phase-5.md](../../../../docs/plans/active/prs-input-coverage-fill/phases/phase-5.md)
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

# ---------------------------------------------------------------------------
# AC1 — Tier 1 QC JSON shape + GT distribution health
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_tier1_qc_json_present_and_healthy(phase5_smoke_dir: Path) -> None:
    """tier1.qc.json present, mean DP healthy, per-chrom counts populated.

    Verifies INV-R001 (QC JSON provenance complete) + the post-bridge
    GT distribution shape expected on a Northern European 30× WGS sample.
    """
    qc_path = (
        phase5_smoke_dir
        / "derived"
        / "prs_coverage"
        / "MPNRGLQ2K"
        / "v1"
        / "tier1.qc.json"
    )
    assert qc_path.exists(), f"tier1.qc.json missing: {qc_path}"

    qc = json.loads(qc_path.read_text())

    # Mean depth — healthy 30× WGS lands here.
    assert 20.0 <= qc["mean_dp"] <= 35.0, (
        f"mean_dp {qc['mean_dp']} outside [20×, 35×] healthy range"
    )

    # REF/REF rate — chr22 prove-out measured 84.5%; full-autosome similar.
    total = qc["total_records"]
    assert total > 0, "tier1.vcf.gz produced zero records"
    refref = qc["gt_distribution"]["0/0"]
    refref_pct = refref / total
    assert 0.75 <= refref_pct <= 0.92, (
        f"REF/REF rate {refref_pct:.2%} outside [75%, 92%] expected range"
    )

    # Missing rate — chr22 prove-out: 0.9%. Cap at 5% as a sanity gate.
    assert qc["missing_rate"] < 0.05, (
        f"missing_rate {qc['missing_rate']:.2%} > 5%; high-DP regions misaligned?"
    )

    # All 22 autosomes populated.
    expected_autosomes = {f"chr{i}" for i in range(1, 23)}
    present = set(qc["per_chrom_record_counts"])
    missing = expected_autosomes - present
    assert not missing, f"per_chrom_record_counts missing autosomes: {sorted(missing)}"


# ---------------------------------------------------------------------------
# AC2 — Tier 1 wall-clock within budget (Open Question Q1 resolution)
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_tier1_wallclock_within_budget(phase5_smoke_dir: Path) -> None:
    """Tier 1 wall-clock recorded + within the 90-min upper bound on 2-CPU Colima.

    Resolves Open Question Q1. The chr22 prove-out extrapolated to 53 min
    on 2 CPUs; the 90-min budget is that + 70% safety margin. If this fails,
    the smoke recorded the actual time → spec.md's Q1 gets updated → this
    threshold gets raised to the measured value + 15%.
    """
    timings_path = phase5_smoke_dir / "timings.json"
    assert timings_path.exists(), f"timings.json missing: {timings_path}"

    timings = json.loads(timings_path.read_text())
    tier1 = timings.get("prepare_coverage_tier1") or {}
    wallclock_s = tier1.get("wallclock_s")
    assert wallclock_s is not None, (
        f"prepare_coverage_tier1.wallclock_s missing from timings.json: "
        f"{list(timings.keys())}"
    )

    # 90 min = 5400s upper bound. If exceeded: this test FAILS → the regression
    # guard now records the real value, and the SLA-to-the-agent gets revised.
    assert wallclock_s < 5400, (
        f"Tier 1 wallclock {wallclock_s:.0f}s > 90 min budget. "
        "Update phase-5.md threshold to the measured value + 15% safety margin "
        "and revise the agent-facing SLA accordingly."
    )


# ---------------------------------------------------------------------------
# AC3 — Tier 1 peak RAM stays well under the Colima ceiling
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_tier1_peak_memory_below_ceiling(phase5_smoke_dir: Path) -> None:
    """Peak RAM during Tier 1 stays below 1 GB (chr22 prove-out: 127 MiB).

    The streaming bcftools pipe shouldn't accumulate state proportional to
    site count. A regression here would imply something unbounded leaked in;
    catches that early.
    """
    timings = json.loads((phase5_smoke_dir / "timings.json").read_text())
    peak_rss_mib = (timings.get("prepare_coverage_tier1") or {}).get("peak_rss_mib")
    assert peak_rss_mib is not None, "peak_rss_mib missing from timings.json"
    assert peak_rss_mib < 1024, (
        f"Tier 1 peak RSS {peak_rss_mib} MiB > 1 GB; "
        "the streaming pipe should be O(coverage-at-current-locus), not O(sites)"
    )


# ---------------------------------------------------------------------------
# AC4 — INV-D001: CRAM unchanged after smoke
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_invD001_cram_unchanged_after_smoke(phase5_smoke_dir: Path) -> None:
    """Pre/post CRAM SHA256 + mtime recorded equal. The smoke must not mutate raw."""
    audit_path = phase5_smoke_dir / "invariant_audit.json"
    assert audit_path.exists(), f"invariant_audit.json missing: {audit_path}"

    audit = json.loads(audit_path.read_text())
    d001 = audit.get("INV-D001") or {}
    assert d001.get("cram_sha256_pre") == d001.get("cram_sha256_post"), (
        f"INV-D001 violated: CRAM SHA256 changed during smoke "
        f"(pre={d001.get('cram_sha256_pre')!r}, post={d001.get('cram_sha256_post')!r})"
    )
    assert d001.get("equal") is True, (
        f"INV-D001 audit doesn't agree equal=True: {d001}"
    )


# ---------------------------------------------------------------------------
# AC5 — Tier 2 cache present for PGS000018
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_tier2_qc_json_present_for_pgs000018(phase5_smoke_dir: Path) -> None:
    """Tier 2 cache for PGS000018 (cache-keyed by scorefile SHA-8) exists + healthy."""
    pgs_root = (
        phase5_smoke_dir
        / "derived"
        / "prs_coverage"
        / "MPNRGLQ2K"
        / "v1"
        / "pgs"
    )
    # The sha8 suffix is unknown at test time; find any PGS000018-* dir.
    matches = sorted(pgs_root.glob("PGS000018-*"))
    assert matches, (
        f"no Tier 2 cache dir found under {pgs_root}; expected PGS000018-<sha8>/"
    )
    tier2_qc = matches[0] / "tier2.qc.json"
    assert tier2_qc.exists(), f"tier2.qc.json missing: {tier2_qc}"

    qc = json.loads(tier2_qc.read_text())
    assert qc.get("pgs_id") == "PGS000018"
    assert qc.get("snp_row_count", 0) > 0
    assert qc.get("bcftools_version") not in (None, "", "unavailable")


# ---------------------------------------------------------------------------
# AC6 — Real pgsc_calc match-rate parses + post-bridge match-rate > 50%
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_match_rate_parses_from_real_pgsc_calc_log(
    phase5_smoke_dir: Path,
) -> None:
    """Parse the real smoke's pgsc_calc log; assert post-bridge match-rate > 50%.

    The 2026-05-17 pre-bridge baseline was 28.37%. After Tier 1 + Tier 2
    forced genotyping, the rate should jump substantially. If it doesn't,
    that's the **structural finding** the plan was built to surface:
    the bridge alone isn't sufficient and the spec gets a documented
    limitation note. 50% is a loose floor — anything below it means
    something is structurally wrong with the bridge.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_match import (
        find_pgsc_calc_log_csv,
        parse_match_stats,
    )

    work_dir = phase5_smoke_dir / "pgsc_calc_work"
    assert work_dir.is_dir(), f"pgsc_calc_work missing: {work_dir}"

    log = find_pgsc_calc_log_csv(work_dir, sampleset="MPNRGLQ2K")
    assert log is not None, (
        f"could not find MPNRGLQ2K_log.csv.gz under {work_dir}; "
        "the smoke driver should have preserved it"
    )

    stats = parse_match_stats(log, pgs_accession="PGS000018_hmPOS_GRCh38")
    assert stats is not None
    total = stats.matched + stats.unmatched
    assert total > 1_500_000, (
        f"PGS000018 has ~1.7M scoring variants; the parser found only {total:,}. "
        "Either accession naming changed upstream or the log is incomplete."
    )
    assert stats.match_rate > 0.50, (
        f"Post-bridge match rate is {stats.match_rate:.2%}; expected > 50%. "
        "If this fails, the bridge alone isn't sufficient — update spec.md's "
        "Open Risks with the measured value and document the limitation."
    )


# ---------------------------------------------------------------------------
# AC7 — pgs_scores row persisted (DDL migration round-trip on real data)
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_pgs_scores_row_persisted(phase5_smoke_dir: Path) -> None:
    """A pgs_scores row for PGS000018 lands with INV-A003 + INV-R001 provenance."""
    derived = phase5_smoke_dir / "derived"
    duckdb_files = sorted(derived.rglob("variants.duckdb"))
    assert duckdb_files, f"no variants.duckdb under {derived}"

    db = duckdb_files[0]
    conn = duckdb.connect(str(db), read_only=True)
    try:
        row = conn.execute(
            """
            SELECT pgs_id, agent_choice_rationale, requested_for_question,
                   source_path, tool, schema_version,
                   calibration_status, decline_reason
            FROM pgs_scores
            WHERE pgs_id = 'PGS000018'
            """
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, (
        f"no PGS000018 row in pgs_scores at {db}; the smoke driver didn't "
        "persist the result"
    )
    (
        pgs_id,
        rationale,
        question,
        source_path,
        tool,
        schema_version,
        calibration_status,
        decline_reason,
    ) = row
    assert pgs_id == "PGS000018"
    assert rationale, "INV-A003: agent_choice_rationale must be non-empty"
    assert question, "INV-A003: requested_for_question must be non-empty"
    assert source_path, "INV-R001: source_path must be populated"
    assert tool == "pgsc_calc", f"INV-R001: tool must be pgsc_calc, got {tool!r}"
    assert schema_version, "INV-R001: schema_version must be populated"
    # The Phase 3b3b1 calibration columns must persist (NULL is acceptable
    # only if the smoke explicitly disabled calibration — record the value
    # without asserting a specific status here; AC8 handles that).
    assert calibration_status in {"clean", "warning", "decline", None}
    if calibration_status == "decline":
        assert decline_reason, (
            "DECLINE row missing decline_reason; INV-C001 v1.7 requires it"
        )


# ---------------------------------------------------------------------------
# AC8 — Calibration outcome recorded structurally
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_calibration_outcome_recorded(phase5_smoke_dir: Path) -> None:
    """invariant_audit.json records the structural calibration decision (INV-C001 v1.7).

    Whichever outcome the smoke produces (CLEAN / WARNING / DECLINE), it
    must surface as a typed value in the audit log — not as a stack trace
    or a silent miss. This is what the agent layer reads to render the
    user-facing message.
    """
    audit = json.loads((phase5_smoke_dir / "invariant_audit.json").read_text())
    c001 = audit.get("INV-C001-v1.7") or {}
    status = c001.get("calibration_status")
    assert status in {"clean", "warning", "decline"}, (
        f"INV-C001 v1.7 audit must record a structural calibration_status; "
        f"got {status!r}"
    )
    if status == "decline":
        reason = c001.get("decline_reason")
        assert reason in {
            "population_transferability_insufficient",
            "pgs_catalog_tier_insufficient",
            "phenotype_heterogeneous",
            "variant_overlap_insufficient",
            "ancestry_calibration_uncertain",
        }, f"DECLINE recorded with non-canonical decline_reason: {reason!r}"


# ---------------------------------------------------------------------------
# AC9 — CLI JSON envelope captured + conforms to INV-C002
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_cli_json_envelope_recorded(phase5_smoke_dir: Path) -> None:
    """`pipeline prs-compute --json` envelope captured; INV-C002 shape verified."""
    envelope_path = phase5_smoke_dir / "cli_envelope.json"
    assert envelope_path.exists(), f"cli_envelope.json missing: {envelope_path}"

    envelope = json.loads(envelope_path.read_text())
    assert envelope.get("cli_output_schema_version") == "1.0", (
        f"INV-C002: envelope schema_version mismatch: {envelope!r}"
    )
    assert envelope.get("command") == "pipeline.prs-compute", (
        f"INV-C002: command must be 'pipeline.prs-compute', got {envelope.get('command')!r}"
    )
    payload = envelope.get("payload") or {}
    assert payload.get("sample_id") == "MPNRGLQ2K"
    assert payload.get("pgs_id") == "PGS000018"


# ---------------------------------------------------------------------------
# AC10 — Invariant audit complete; covers the discipline
# ---------------------------------------------------------------------------


@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_invariant_audit_complete(phase5_smoke_dir: Path) -> None:
    """invariant_audit.json enumerates every invariant verified in the smoke.

    Single-file review surface: a future contributor reading this confirms
    the smoke didn't quietly drop an invariant check.
    """
    audit = json.loads((phase5_smoke_dir / "invariant_audit.json").read_text())
    expected_ids = {"INV-D001", "INV-D003", "INV-R001", "INV-P001", "INV-C001-v1.7"}
    missing = expected_ids - set(audit)
    assert not missing, (
        f"invariant_audit.json missing required IDs: {sorted(missing)}. "
        f"Got: {sorted(audit)}"
    )

    # INV-P001 audit: zero outbound network egress during the smoke.
    p001 = audit.get("INV-P001") or {}
    egress = p001.get("network_egress_attempts")
    assert egress == 0, (
        f"INV-P001 violated: {egress} outbound network egress attempts during "
        "the smoke (expected 0; the smoke runs entirely on-device)"
    )

# Phase 5: Real-data smoke against `MPNRGLQ2K.cram`

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Run the full Phase 1–4 pipeline end-to-end against the project owner's real Nebula CRAM (`MPNRGLQ2K`) on the real toolkit image (`genomeclaw/toolkit:prs-phase1`) to:

1. **Resolve Open Question Q1** — the full-autosome Tier 1 wall-clock. Phase 1's chr22 prove-out extrapolated to 50–60 min on a 2-CPU Colima / 12–15 min on 8 CPUs; Phase 5 measures the actual number.
2. **Resolve Open Question Q3** — the per-chromosome REF/REF / het / hom-alt / missing distribution on the full autosomes (chr22 prove-out gave 84.5% / 9.5% / 5.1% / 0.9% at mean DP 27.98×).
3. **Validate the agent path empirically** — `pipeline prs-compute --sample MPNRGLQ2K --scorefile <PGS000018>` flows from CRAM → Tier 1 → Tier 2 → merge → pgsc_calc → match-rate auto-discovery → classifier → either a CLEAN/WARNING `pgs_scores` row or a `PRSDeclineError` → typed CLI JSON envelope.
4. **Catch the 2026-05-17 smoke failure** in its post-fix form: the canonical case (PGS000018 on Nebula variant-only CRAM) should now produce a calibrated CLEAN/WARNING row, **not** a 28% match-rate DECLINE — because the Tier 1+Tier 2 force-genotyping bridge fixes the input-coverage gap. If it still declines after the bridge, that's a real finding and Phase 5 records it.

Phase 5 promotes the agent-surface SLA from "hopeful 15–25 min/Q" to a **measured number** with a recorded date, host configuration, and reproducer command.

## Scope Boundaries

- **In scope**:
  - End-to-end smoke against the real CRAM, real panel, real toolkit image.
  - Per-stage wall-clock + peak RAM measurement.
  - Per-chromosome GT distribution in `tier1.qc.json`.
  - Real pgsc_calc invocation with `-profile docker` (Phase 4a path).
  - Real match-rate parsing from pgsc_calc's `<sampleset>_log.csv.gz` (Phase 3b3a auto-discovery).
  - Real `pgs_scores` row INSERT (Phase 3b3b1) — verifying the calibration columns land with the right values.
  - Updated SLA in [spec.md](../spec.md) Open Question Q1.
  - New reference doc [docs/reference/prs-pipeline.md](../../../reference/prs-pipeline.md) describing the measured architecture for future contributors.

- **Out of scope** (defer to follow-up plans):
  - 8-CPU Colima provisioning + re-measurement (the 2-CPU baseline is the first number; 8-CPU is the second).
  - PGS003725 / caPRS / other multi-PGS smoke runs.
  - Indel-heavy PGS scoring files (Phase 1 Open Question Q2 stays deferred).
  - Ancestry-driven decline reasons (`POPULATION_TRANSFERABILITY_INSUFFICIENT` et al — Phase 3a stub-only).
  - `SCHEMA_VERSION` bump.

## Invariants Enforced in This Phase

This phase doesn't introduce new invariants; it **verifies existing invariants under realistic load**:

- **INV-D001**: the smoke must not mutate `MPNRGLQ2K.mm2.sortdup.bqsr.cram` — SHA256 + mtime captured pre- and post-smoke, asserted equal.
- **INV-D003**: the smoke driver writes pgsc_calc work-dir + bcftools scratch under `_scratch/`; the final cached VCFs live under `derived/prs_coverage/<sample>/v1/`.
- **INV-R001**: `tier1.qc.json` + `tier2.qc.json` carry source CRAM SHA256 + bcftools version + tool command; `pca_sites.provenance.json` carries the panel SHA256 + plink2 image pin. A rebuild from the same inputs produces matching SHA values (the underlying VCFs are bgzip-block-deterministic; the QC JSONs differ in `created_at` only).
- **INV-P001**: the smoke runs with `_no_outbound_http` semantics — no network egress beyond the deliberate, named `refs fetch` destinations (and `refs fetch` is NOT exercised in Phase 5; the panel + FASTA + scorefile are already on disk).
- **INV-C001 v1.7**: whichever calibration outcome the smoke produces (CLEAN / WARNING / DECLINE), it surfaces structurally — not as an unhandled exception.

---

## TDD Steps

### Step 5.1 — RED: Write Failing Tests

The RED tests in this phase are **verification gates against recorded smoke artifacts**, not unit-test stubs. They presume the smoke has been run by a driver script (Step 5.2). The driver writes its outputs to a canonical layout under `_scratch/prs_phase5_smoke/<timestamp>/`, and these tests assert the outputs are present + carry the expected shape.

Two new pytest markers gate them:

- `needs_prs_runtime` (existing) — requires the toolkit image + docker on PATH.
- `needs_phase5_smoke_artifacts` (new) — requires `GENOMECLAW_PHASE5_SMOKE_DIR` to point at a smoke output directory. Auto-skipped on a bare CI without that env var.

**Test cases** (target: 10 tests):

1. `test_phase5_tier1_qc_json_present_and_healthy` — `<smoke_dir>/derived/prs_coverage/MPNRGLQ2K/v1/tier1.qc.json` exists; mean DP ∈ [20×, 35×]; REF/REF rate ∈ [75%, 92%]; missing rate < 5%; per-chrom record counts populated for all 22 autosomes.
2. `test_phase5_tier1_wallclock_within_budget` — wall-clock recorded in `<smoke_dir>/timings.json` is < 90 min on 2-CPU Colima (corresponds to the chr22-extrapolated 53-min upper bound + 70% safety margin); the actual value is what resolves Q1.
3. `test_phase5_tier1_peak_memory_below_ceiling` — peak RAM recorded in `<smoke_dir>/timings.json` is < 1 GB (chr22 prove-out measured 127 MB; full-autosome should be similar since the streaming pipe doesn't accumulate).
4. `test_phase5_invD001_cram_unchanged_after_smoke` — pre/post SHA256 of `MPNRGLQ2K.mm2.sortdup.bqsr.cram` is recorded in `<smoke_dir>/invariant_audit.json`; equal.
5. `test_phase5_tier2_qc_json_present_for_pgs000018` — Tier 2 cache for PGS000018 exists at `<smoke_dir>/derived/prs_coverage/MPNRGLQ2K/v1/pgs/PGS000018-<sha8>/tier2.qc.json`; SNP row count > 0; bcftools version recorded.
6. `test_phase5_match_rate_parses_from_real_pgsc_calc_log` — feeding `_pgsc_calc_match.parse_match_stats` the real smoke's `<sampleset>_log.csv.gz` returns a `MatchStats` for `PGS000018_hmPOS_GRCh38` with `matched + unmatched > 1.5M` and `match_rate > 0.5` (post-bridge — the variant-only-VCF baseline was 28%; with Tier 1+Tier 2 the rate should jump substantially).
7. `test_phase5_pgs_scores_row_persisted` — DuckDB at `<smoke_dir>/derived/<run-id>/variants.duckdb` has a `pgs_scores` row for `PGS000018` with non-null `calibration_status`, `agent_choice_rationale`, `requested_for_question`, `source_path`, `tool`.
8. `test_phase5_calibration_outcome_recorded` — the row's `calibration_status` is one of `"clean"` / `"warning"` / `"decline"`; whichever it is, the smoke records the **decision** and (on decline) the `decline_reason` snake_case.
9. `test_phase5_cli_json_envelope_recorded` — the smoke driver captures the CLI's `--json` envelope at `<smoke_dir>/cli_envelope.json`; conforms to `INV-C002` (`cli_output_schema_version: "1.0"`, `command: "pipeline.prs-compute"`).
10. `test_phase5_invariant_audit_complete` — `<smoke_dir>/invariant_audit.json` enumerates every invariant the smoke checked, with PASS/FAIL/N-A per ID (INV-D001, INV-D003, INV-R001, INV-P001, INV-C001 v1.7) — so a future reviewer reads one file to confirm the smoke covered the discipline.

**Sketch** (Python / pytest, illustrative):

```python
@pytest.mark.needs_prs_runtime
@pytest.mark.needs_phase5_smoke_artifacts
def test_phase5_tier1_qc_json_present_and_healthy(
    phase5_smoke_dir: Path,
) -> None:
    """Tier 1 QC JSON exists; mean DP healthy; per-chrom counts populated."""
    qc = json.loads(
        (phase5_smoke_dir / "derived" / "prs_coverage" / "MPNRGLQ2K" / "v1"
         / "tier1.qc.json").read_text()
    )
    assert 20.0 <= qc["mean_dp"] <= 35.0, f"mean_dp out of healthy range: {qc['mean_dp']}"
    refref = qc["gt_distribution"]["0/0"]
    total = qc["total_records"]
    assert 0.75 <= refref / total <= 0.92
    assert qc["missing_rate"] < 0.05
    # all 22 autosomes present
    expected_chroms = {f"chr{i}" for i in range(1, 23)}
    assert expected_chroms.issubset(set(qc["per_chrom_record_counts"]))
```

After writing the tests, run them on a bare host (no smoke yet) and **confirm they auto-skip** (the marker gate fires cleanly). Paste the auto-skip output into [work-notes.md](../work-notes.md). The "RED" step here is more accurately "tests in place, awaiting smoke artifacts".

### Step 5.2 — GREEN: Smoke Driver Script

Write `bin/genomeclaw-prs-smoke` (host-side shell wrapper) that:

1. Resolves the toolkit image tag from `GENOMECLAW_TOOLKIT_PRS_IMAGE` (or defaults to `genomeclaw/toolkit:prs-phase1`).
2. Pre-flights: panel staged, FASTA + .fai + .gzi present, CRAM + .crai present, `_scratch/` + `derived/` writable.
3. Captures SHA256 of `MPNRGLQ2K.cram` pre-smoke.
4. Creates a timestamped smoke output dir under `_scratch/prs_phase5_smoke/<UTC-iso>/`.
5. Calls `genomeclaw refs materialize --target prs_pca_sites` if the prune-in TSVs don't already exist for the panel version. Measures wall-clock with `/usr/bin/time -v` (peak RSS + user/sys CPU).
6. Calls `genomeclaw pipeline prs-prepare-coverage --sample MPNRGLQ2K ...` for the full Tier 1 build. Measures wall-clock + peak RAM.
7. Calls `genomeclaw pipeline prs-compute --sample MPNRGLQ2K --pgs-id PGS000018 ...` for the end-to-end agent path. Captures the JSON envelope to `<smoke_dir>/cli_envelope.json`.
8. Captures SHA256 of `MPNRGLQ2K.cram` post-smoke; writes the pre/post pair to `<smoke_dir>/invariant_audit.json`.
9. Walks `_scratch/prs_phase5_smoke/<UTC-iso>/derived/` to confirm `tier1.qc.json`, `tier2.qc.json`, `variants.duckdb` are present.
10. Emits `<smoke_dir>/timings.json` with per-stage wall-clock + peak RSS.

The driver does NOT call into pytest. It's a Bash + jq pipeline that produces measurement artifacts.

**Files affected**:
- `bin/genomeclaw-prs-smoke` — CREATE (executable).
- `packages/toolkit/tests/integration/test_phase5_smoke_artifacts.py` — CREATE (the 10 RED tests).
- `packages/toolkit/tests/conftest.py` — MODIFY (add the `needs_phase5_smoke_artifacts` marker auto-skip + the `phase5_smoke_dir` fixture).
- `packages/toolkit/pyproject.toml` — MODIFY (register the `needs_phase5_smoke_artifacts` marker).

### Step 5.3 — REFACTOR + Document

With the smoke artifacts in place + tests green:

- Update [spec.md](../spec.md) Open Question Q1 with the measured wall-clock (with date + host config: CPUs, RAM, OS, toolkit image digest).
- Resolve Open Question Q3 by recording the per-chromosome GT distribution from the smoke's `tier1.qc.json` into work-notes + spec.
- Create [docs/reference/prs-pipeline.md](../../../reference/prs-pipeline.md) documenting the architecture for future contributors. Sections: data-flow diagram, cache layout, decline taxonomy, measured SLAs.
- Move the plan from `docs/plans/active/prs-input-coverage-fill/` to `docs/plans/completed/prs-input-coverage-fill/`.

---

## Implementation Details

### Smoke output layout

```text
<external-drive>/genomeclaw/_scratch/prs_phase5_smoke/<UTC-iso>/
├── timings.json
│   ├── materialize_pca_sites: { wallclock_s, peak_rss_mib, exit_code }
│   ├── prepare_coverage_tier1: { wallclock_s, peak_rss_mib, exit_code }
│   ├── prs_compute_PGS000018: { wallclock_s, peak_rss_mib, exit_code }
│   └── total: { wallclock_s, started_at_utc, finished_at_utc }
├── invariant_audit.json
│   ├── INV-D001: { cram_sha256_pre, cram_sha256_post, equal: bool, mtime_pre, mtime_post }
│   ├── INV-D003: { scratch_used: paths[], derived_used: paths[], scratch_disjoint_from_derived: bool }
│   ├── INV-R001: { provenance_jsons_present: bool, tool_versions_recorded: dict }
│   ├── INV-P001: { network_egress_attempts: int (expect 0) }
│   └── INV-C001-v1.7: { calibration_status: str, decline_reason: str | null }
├── cli_envelope.json       # the `pipeline prs-compute --json` output
├── derived/
│   └── (mirror of canonical derived/ layout, scoped to this smoke)
├── pgsc_calc_work/
│   └── (Nextflow work-dir, pruned to retain only the log_csv.gz + aggregated_scores.txt.gz)
└── smoke.log               # raw stdout/stderr from each stage
```

### Edge Cases to Handle

- **2-CPU Colima ceiling**: Phase 1's chr22 measurement was on 2 CPUs. The full-autosome timing might exceed the 90-min test budget. If so, the test asserts FAIL → driver writes the actual time → spec.md records the measured value → the test threshold is then raised to that value + 15% safety margin (the test is the regression guard, not the SLA).
- **Cache warm-up across runs**: a second smoke run against the same sample should hit the Tier 1 + Tier 2 caches; `<smoke_dir>/timings.json` records "cache hit" for the relevant stages.
- **pgsc_calc DENOM column semantics**: confirmed empirically from the 2026-05-17 smoke that the match-rate parser computes correctly from the `<sampleset>_log.csv.gz`. Phase 5 re-confirms this on the post-bridge data.
- **Network egress**: the smoke must NOT call `refs fetch`. Pre-flight asserts the panel + FASTA + scorefile are already on disk. If any are missing the driver exits non-zero with a hint, not a fetch.

### Error Handling

- Driver exit codes: `0` on success (smoke completed; results in place); `1` on a hard failure (pgsc_calc crashed, plink2 not found, etc.); `2` on a pre-flight failure (panel missing, CRAM index missing, disk full).
- Each stage's exit code lands in `timings.json` so a partial smoke produces partial results without crashing the verification suite.

### Privacy / Egress Notes

- The smoke runs entirely on-device. `_no_outbound_http` semantics apply.
- The CRAM SHA256 is computed locally (slow on a 50 GB file — ~3–5 min). Recorded once pre- and once post- to keep INV-D001 honest.
- The pgsc_calc Nextflow work-dir is pruned post-smoke: keep only the log_csv.gz + aggregated_scores.txt.gz + report.html; drop the per-chromosome intermediates (10–100 GB depending on PGS). The driver does this cleanup; otherwise the smoke fills the drive.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `bin/genomeclaw-prs-smoke` | CREATE | Host-side smoke driver script |
| `packages/toolkit/tests/integration/test_phase5_smoke_artifacts.py` | CREATE | 10 verification gates |
| `packages/toolkit/tests/conftest.py` | MODIFY | `needs_phase5_smoke_artifacts` marker auto-skip + `phase5_smoke_dir` fixture |
| `packages/toolkit/pyproject.toml` | MODIFY | Register `needs_phase5_smoke_artifacts` marker |
| `docs/reference/prs-pipeline.md` | CREATE | Architecture reference doc (post-smoke) |
| `docs/plans/active/prs-input-coverage-fill/spec.md` | MODIFY | Q1 + Q3 resolved with measured values |
| `docs/plans/active/prs-input-coverage-fill/work-notes.md` | MODIFY | Phase 5 session log + smoke measurements |
| `docs/plans/active/prs-input-coverage-fill/` → `docs/plans/completed/...` | MOVE | On completion |

---

## Verification

```bash
# 1. Pre-flight (auto-skips when env not set up)
export GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:prs-phase1
export GENOMECLAW_HAS_BIO=1
cd packages/toolkit
uv run pytest -m needs_phase5_smoke_artifacts -v
# Expect: all 10 SKIPPED (GENOMECLAW_PHASE5_SMOKE_DIR not set)

# 2. Run the smoke driver (~50–60 min on 2-CPU Colima; one-time per release)
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018

# 3. Verify the recorded artifacts
export GENOMECLAW_PHASE5_SMOKE_DIR=/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<UTC-iso>
uv run pytest -m needs_phase5_smoke_artifacts -v
# Expect: 10 PASSED

# 4. Update SLA in spec + create reference doc + move plan to completed
```

---

## Completion Criteria

- [ ] All 10 verification tests pass against a real smoke run on `MPNRGLQ2K.cram`.
- [ ] `tier1.qc.json` mean DP within [20×, 35×]; REF/REF rate within [75%, 92%]; missing rate < 5%; per-chromosome counts populated for all 22 autosomes.
- [ ] Wall-clock + peak RAM recorded in `timings.json`; the spec's Open Question Q1 is updated with the measured value + date + host config.
- [ ] `pgs_scores` row for PGS000018 lands with `calibration_status` set; if DECLINE, the `decline_reason` is recorded with rationale in work-notes.
- [ ] INV-D001 (CRAM unchanged) + INV-P001 (no egress) + INV-C001 v1.7 (decline-or-decision) audit recorded in `invariant_audit.json`.
- [ ] [docs/reference/prs-pipeline.md](../../../reference/prs-pipeline.md) created with the measured architecture.
- [ ] Plan moved from `docs/plans/active/` to `docs/plans/completed/`.

---

## Open Risks

- **The full-autosome smoke might still produce a DECLINE** even with the Tier 1+Tier 2 bridge. If match_rate stays < 75% on PGS000018 (a >500k variant score) after the bridge, the structural decline is the **correct** outcome and the spec gets a "known limitation: the bridge alone is insufficient for ≥1M-variant scores; needs imputation" note. The smoke result is what determines whether the plan ships fully or with a documented limitation.
- **Wall-clock might exceed 90 min** on the 2-CPU baseline. The test threshold is the regression guard, not the SLA. The smoke records the true value; the SLA promise to the agent is set to that value + 15%.
- **Colima might be under-provisioned**. If the smoke runs out of RAM or fails for environmental reasons, the driver records the failure cleanly and the SLA promise becomes conditional on the host configuration.

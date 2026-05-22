# Phase 4: Real-data smoke v22 — Stage 3 GREEN gate

**Status**: Pending — awaits user invocation
**Started**:
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Run `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` against the project owner's real Nebula 30× WGS CRAM with the post-Phase-1+2+3 code (lowered `--min_overlap 0.5` from Phase 1; `bcftools norm -m -any` upstream from Phase 2; orientation fix already inherited from the closed pgs-allele-orientation plan). Acceptance: pgsc_calc produces a non-empty `pgs_scores` row with a non-null ancestry-calibrated `percentile_in_user_ancestry`. This is the Stage 3 GREEN gate of [prs-bootstrap-meta](../../prs-bootstrap-meta.md).

## Scope Boundaries

- **In scope**: a single end-to-end run of `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018`; verification of the produced `cli_envelope.json` + `pgs_scores.params_json`; smoke-ledger entry in [../work-notes.md](../work-notes.md).
- **Out of scope**:
  - Performance tuning of pgsc_calc beyond what's already configured.
  - A second smoke against PGS001229 — keeping the gate single-scorefile so the success/failure signal is unambiguous.
  - Any code changes. If the smoke surfaces a new bug, it triggers a new plan (or a Phase 5 of this plan), not in-place edits.
  - The `live_llm` decline-with-fifth-reason behavioural test deferred from Phase 3 — that's a separate fixture infra slice.

## Why this isn't a TDD phase

This phase has no RED → GREEN cycle. The cycle ran in Phases 1–3 (each with its own test gate); Phase 4 is the **integration verification** that the three slices compose into a working end-to-end PRS path on real data. The smoke driver is the test; the project owner's actual hardware is the test environment.

Real-data smokes as phase-completion gates are documented in [docs/plans/CLAUDE.md § Test Categories](../../../CLAUDE.md): "For phases touching scale-sensitive surfaces (... coverage / PRS computation over a genome), synthetic fixtures alone are insufficient — run the pipeline against the project owner's actual genome on actual hardware as part of the GREEN gate. The synthetic→real gap is exactly where production bugs live."

---

## Pre-flight checks

Before the smoke runs, confirm:

1. **Toolkit image is at the post-Phase-2 pin.** Build a fresh image:
   ```bash
   docker build -t genomeclaw/toolkit:phase6 -f packages/toolkit/Dockerfile packages/toolkit
   ```
2. **Tier 1 + Tier 2 caches from prior smoke iterations are nuked** so smoke v22 starts cold:
   ```bash
   rm -rf /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/{pgsc_calc_work,derived/prs_coverage/MPNRGLQ2K/v1/pgs}
   ```
3. **Reference data still on the external drive**:
   ```bash
   ls /Volumes/Genome_Work/genomeclaw/reference/pgs_catalog_ancestry/v1/pgs_catalog_ancestry.tar.zst
   # ~16 GB; if missing, `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` first.
   ```
4. **Colima is running with the canonical mounts** (`/Volumes/Genome_Work/...:/Volumes/Genome_Work/...`). `colima status` shows `Running`.

## Verification command

```bash
mkdir -p /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/pgsc_calc_work

GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:phase6 \
GENOMECLAW_PHASE5_SMOKE_DIR_OVERRIDE=/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z \
  bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```

Wall-clock estimate (per meta-plan AC3 revised budget):
- **Cold** (Tier 1 + Tier 2 caches empty): ~60–90 min on 16 GB-RAM M-series host.
- **Warm** (Tier 1 + Tier 2 caches hit): ~10–15 min — only the pgsc_calc PCA + score-matching steps run.

The 7586s smoke v21 SIGTERM was the background-task system's 2h cap, not a runtime cap. Run this directly (foreground) so it doesn't hit the same wall.

## Acceptance Criteria

- [ ] **AC4.1**: `cli_envelope.json` is a success envelope (no `error` field; `cli_output_schema_version == "1.0"`).
- [ ] **AC4.2**: The DuckDB `pgs_scores` row for PGS000018 has:
  - non-null `percentile_in_user_ancestry`.
  - non-null `raw_score`.
  - `tool == "pgsc_calc"`.
  - `agent_choice_rationale` matching the smoke driver's rationale.
  - `params_json` containing `min_overlap_used: 0.5` + `keep_ambiguous_used: false` (Phase 1 deliverable).
- [ ] **AC4.3**: pgsc_calc's empirical match rate (from its `MATCH_COMBINE` log) is in the 45–65% range expected for non-imputed single-sample WGS against PGS000018 (per the research findings doc).
- [ ] **AC4.4**: A matching `findings` row exists with `category == "clinical-non-actionable"`, `evidence_ref == "pgs_catalog:PGS000018"`, NULL `clinical_escalation`.
- [ ] **AC4.5**: `_scratch/pgsc_calc_work/<run-id>/.nextflow.log` has no fatal stack traces; the run terminated via successful MATCH_COMBINE, not via a degraded-input rejection.
- [ ] **AC4.6**: Tier 2 cache + the new `merged.norm.vcf.gz` are present on disk; both non-zero records (`bcftools view -h ... | tail` shows real data lines).
- [ ] **AC4.7**: Smoke-ledger entry appended to [../work-notes.md](../work-notes.md) with wall-clock + peak RSS + empirical match rate + any surprises.

If AC4.1–4.7 all pass, this plan moves to `docs/plans/completed/prs-non-imputed-wgs/` and the meta-plan's Stage 3.5 row gets updated to Complete. The meta-plan's Stage 4 (docs cleanup) then becomes unblocked.

If any AC fails, capture the failure mode in [../work-notes.md](../work-notes.md) and triage: (a) a missing piece in this plan → Phase 5; (b) a different subsystem's bug → new plan.

## Verification queries (post-run)

```bash
# Pull the pgs_scores row + its params_json.
duckdb /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/derived/current/variants.duckdb <<'SQL'
SELECT pgs_id, percentile_in_user_ancestry, raw_score, tool, tool_version,
       params_json, calibration_warning
FROM pgs_scores
WHERE pgs_id = 'PGS000018';
SQL

# Pull the matching findings row.
duckdb /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/derived/current/variants.duckdb <<'SQL'
SELECT category, evidence_ref, clinical_escalation, title
FROM findings
WHERE evidence_ref = 'pgs_catalog:PGS000018';
SQL

# Sanity check: the normalized VCF has records.
bcftools view -h /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/pgsc_calc_work/merged.norm.vcf.gz | tail -1
bcftools view -H /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/pgsc_calc_work/merged.norm.vcf.gz | wc -l

# Pull pgsc_calc's match-rate log (the per-variant match-status CSV).
zcat /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/pgsc_calc_work/*/MPNRGLQ2K_log.csv.gz | \
  awk -F, 'NR>1 {m[$NF]++} END {for (k in m) print k, m[k]}'
```

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/prs-non-imputed-wgs/work-notes.md` | MODIFY | Append smoke v22 ledger entry. |
| `docs/plans/active/prs-bootstrap-meta.md` | MODIFY | Update Stage 3.5 row + Stage 4 unblock. |

No code changes in this phase.

---

## Completion Criteria

- [ ] Pre-flight checks pass.
- [ ] `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` returns exit 0.
- [ ] All 7 ACs verified via the verification queries above.
- [ ] Smoke-ledger entry appended to work-notes.
- [ ] Meta-plan's Stage 3.5 row + Stage 4 status updated.
- [ ] Plan moved from `docs/plans/active/prs-non-imputed-wgs/` to `docs/plans/completed/prs-non-imputed-wgs/`.
- [ ] Open follow-ups (deferred `live_llm` decline test; cache-add for the normalized VCF if smoke timings motivate; F1 / F3–F6 from prs-runtime-hardening) listed in the close-out block of work-notes.

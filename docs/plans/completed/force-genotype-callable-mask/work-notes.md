# Work Notes: Force-Genotype Callable-Region Mask

**Plan**: [development-plan.md](./development-plan.md)  
**Spec**: [spec.md](./spec.md)  
**Started**: (not started)  
**Last updated**: 2026-05-25

---

## Session log

### 2026-05-25 — Plan drafted

**Context reviewed**:
- Root `CLAUDE.md` — Critical Invariants section.
- `docs/reference/INVARIANTS.md` v1.17 — INV-D001, INV-R001, INV-E001, INV-P001, INV-C001.
- `docs/plans/active/bioreview-followup-meta/meta-plan.md` — Stage 3 sequencing context; confirmed this plan must land before `prs-calibration-phase3b`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` — `_BCFTOOLS_PIPE_TEMPLATE` (lines 378–396); `SCHEMA_VERSION = "2"` (line 68); `prepare_coverage_tier1` cache-hit logic (lines 541–613); `_count_vcf_records` guard (lines 399–420).
- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py` — `parse_match_stats` and `MatchStats` dataclass; no sidecar awareness.
- `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` — `PgsRow` dataclass; `compute_pgs` orchestration.
- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — `_PGS_SCORES_DDL` (lines 205–233); no `uncallable_sites_excluded` column.
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — `_LAYOUTS` dict (line 550+); existing source registrations.

**Applicable invariants reaffirmed**: INV-D001, INV-R001, INV-E001, INV-P001, INV-C001 v1.7.
**Proposed new invariant**: INV-C002 (uncallable sites must not inflate PGS denominator).

**Completed this session**:
- `spec.md` drafted.
- `development-plan.md` drafted.
- `work-notes.md` created.
- `phases/phase-1.md` drafted.
- `phases/phase-2.md` drafted.

**Decisions recorded**:
- Minimum callable depth threshold: 10 reads (GATK convention). Value hardcoded in
  Phase 2; persisted to `tier1.qc.json` as `min_callable_depth` for auditability.
- Sidecar format: `.tsv.zst` (Zstandard-compressed TSV). Consistent with the streaming
  anti-pattern guidance in the bioinformatics pipeline agent spec.
- `SCHEMA_VERSION` in `coverage_fill.py`: bump from `"2"` to `"3"` in Phase 2.
- GIAB release pin: NA12878/HG001 v4.2.1 from NCBI FTP (2021 release). Public-domain.
- GIAB BED intersection: Python `bisect` on sorted coordinate list, no external tool call.
- Sidecar must be treated as a required co-artifact of the VCF cache: a VCF-present but
  sidecar-absent state is a cache miss in schema-v3.

**Blockers**: None. Plan awaiting approval before implementation starts.

**Next steps**:
1. Obtain approval for `spec.md` and `development-plan.md` from triage author + project owner.
2. Begin Phase 1 implementation (GIAB BED registration in `fetch.py`).
3. Write failing tests for Phase 1 before touching `fetch.py`.

---

*(Append new sessions below this line in reverse-chronological order.)*

---

### 2026-05-25 — End-to-end HTTP smoke against running v0.3 host service

**Setup**:
- Host service restarted natively on `127.0.0.1:8645` using the new source (`SCHEMA_VERSION="v0.3"`).
- Seeded a synthetic v0.3 derived store at `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T17-00-00Z-bioreviewsmoke/` via `prep.store.create_store` + `write_coverage_qc` + `prep.pgs.stamp_pgs_row`.
- CURRENT symlink repointed; service restarted to pick up new run; `/v1/health` → `{"status":"ok","schema_version":"v0.3"}`.

**Result for this plan**: **GREEN** at the HTTP layer (the smoke evidence specific to this plan is in the synthesis block below).

The smokes covered (across all 7 plans):
- **Plan 1**: `/v1/pgs/computed/PGS999999` returns `"calibration_status": "decline"` + `"decline_reason": "variant_overlap_insufficient"`; `/v1/pgs/computed/PGS000018` returns `"calibration_status": "clean"` + `"decline_reason": null`. Both fields visible to the agent. INV-A004 verified end-to-end.
- **Plan 2**: `/v1/evidence/cyrius_no_call:<sentinel>` resolves to a `body` carrying the binding "Do not interpret as Normal Metabolizer" prose + the 8 CPIC substrates. Evidence kind registered.
- **Plan 3**: `RefsVerifyPayload.alignment_warnings` field present in the Pydantic model.
- **Plan 4**: `/v1/health` returns `schema_version="v0.3"`; `variants` table DDL carries `mane_plus_clinical_transcript` + `transcript_discordant`.
- **Plan 5**: `/v1/gene/PMS2` returns `region_class="difficult_pseudogene"` + a non-null `caveat` quoting the canonical short-read-WGS warning; `/v1/gene/CYP2D6` returns `requires_dedicated_caller` + Cyrius-specific caveat; `/v1/gene/BRCA1` (standard) returns `caveat=null` (no signal dilution).
- **Plan 6**: `load_uncallable_sites_from_sidecar` correctly extracts the 2 `uncallable` rows from a 5-row sidecar TSV.
- **Plan 7 Phase 1**: `classify_calibration` produces the correct verdict on all 4 scenarios (clean / weight-axis-decline / count-axis-decline / backwards-compat).

**What this smoke does NOT cover** (still project-owner manual gate before move to `completed/`):
- Full `pipeline run` against the real CRAM exercising annotate (`--mane` flag through real VEP), materialize (dual-row emit), mosdepth-against-real-CRAM with v2 panel, force-genotyping with real bcftools, end-to-end pgsc_calc + sidecar consumption. Those need a toolkit Docker image rebuild + a 30 min – 6 hour wall-clock run.

# PRS pipeline non-imputed single-sample WGS hardening — Development Plan

**Plan**: [spec.md](spec.md) | **Work Notes**: [work-notes.md](work-notes.md)
**Lineage**: closes the operational gap surfaced by the [pgs-allele-orientation](../../completed/pgs-allele-orientation/) (closed 2026-05-20) smoke v18–v21 + [research findings](../../../reports/prs-real-data-smoke-research-findings.md)

---

## Critical Invariants to Respect

- **`INV-D001`** — `bcftools norm` writes to a derived path; never mutates source VCFs.
- **`INV-P001`** — no new egress; the `--min_overlap` lowering is a local-only configuration change. Cloud imputation services remain out.
- **`INV-R001`** — `pgs_scores.params_json` gains `min_overlap_used`, `keep_ambiguous_used`, `norm_decompose_multi_allelics` so the row reproduces deterministically from the recorded inputs + parameters.
- **`INV-R002`** — unchanged; the existing 0-record guard in `coverage_fill.py` still applies. The "Not to be confused with" subsection of `INV-R002` (added 2026-05-20) is the doctrinal source distinguishing degenerate caches from low-but-valid match rates.
- **`INV-T001`** — `_pgsc_calc_conventions.py` gains a `min_overlap_default_for_non_imputed_wgs` field with a docstring citing the research findings doc; wrapper consumes the dataclass field, not a hardcoded literal.
- **`INV-A003`** — agent's `agent_choice_rationale` gains a "scorefile modelling method" sentence; the PRS-decline pattern in `INV-C001` v1.7 gains a fifth named reason (only-imputation-dependent-scorefile-available for the trait).
- **`INV-C001 v1.7`** — PRS-decline pattern gains a fifth reason; prompt-content gate test updates.

## Proposed New Invariants

**None.** Operational refinements only; fits within existing INV-R001 / INV-R002 / INV-T001 / INV-A003 / INV-C001 v1.7.

## Current State Analysis

**What's already in place:**

- `coverage_fill.py` Tier 1 + Tier 2 force-genotyping produces a merged VCF that is non-degenerate (INV-R002 guard ensures this).
- `pgs.py` invokes `pgsc_calc` with hardcoded `--min_overlap 0.0` (or whichever the wrapper currently sets) on a path that fails to produce an ancestry-calibrated `pgs_scores` row when the empirical match rate is below 0.75.
- `_pgsc_calc_conventions.py` already carries `verified_against_version` + value-type patterns (per `INV-T001` v1.14).
- The [pgs-allele-orientation](../../completed/pgs-allele-orientation/) Phase 1 work (closed 2026-05-20) corrects scorefile-to-reference allele orientation but does not change the `--min_overlap` default. After F7, the smoke produces ~28K → 53% match-rate Tier 2 records; smoke v21 hit pgsc_calc's 0.75 gate at 52.97% match rate.

**What this plan delivers:**

1. A `bcftools norm -m -any -f <fasta>` step between Tier 1 merge + pgsc_calc invocation; normalized VCF cached under `derived/prs_coverage/<sample>/v1/normalized/`.
2. `PgscCalcConventions.min_overlap_default_for_non_imputed_wgs = 0.5` field + env-var override `GENOMECLAW_PGSC_CALC_MIN_OVERLAP`; wrapper passes the value through to pgsc_calc argv.
3. `pgs_scores.params_json` records the three new keys.
4. Documentation update: HapMap3+ / C+T scorefile preference + the fifth PRS-decline reason.
5. Real-data smoke v22 as the GREEN gate.

## Solution Design

### Phase 1: Tunable `--min_overlap` + conventions field

```python
# _pgsc_calc_conventions.py
@dataclasses.dataclass(frozen=True)
class PgscCalcConventions:
    ...existing fields...
    # New (cite docs/reports/prs-real-data-smoke-research-findings.md):
    min_overlap_default_for_non_imputed_wgs: float = 0.5
    # Rationale: Lambert et al. 2024 calibrated 0.75 on cohort-imputed data;
    # 45-65% match-rate ceiling on non-imputed single-sample WGS makes 0.75
    # a structural rejection of healthy artifacts.
```

```python
# pgs.py (sketch)
min_overlap = os.environ.get(
    "GENOMECLAW_PGSC_CALC_MIN_OVERLAP",
    str(PgscCalcConventions.min_overlap_default_for_non_imputed_wgs),
)
argv = [..., "--min_overlap", min_overlap, ...]
params_json["min_overlap_used"] = float(min_overlap)
params_json["keep_ambiguous_used"] = False
```

### Phase 2: Pre-pgsc_calc `bcftools norm -m -any`

```python
# pgs.py orchestrator (sketch)
normalized_vcf = _normalize_for_pgsc_calc(
    input_vcf=merged_tier_vcf,
    fasta=fasta,
    cache_root=derived_root / "normalized",
)
argv = [..., "--target", str(normalized_vcf), ...]
```

The wrapper:
- Uses `shard_scratch(...)` + `atomic_promote(...)` per `INV-D003`.
- Caches keyed on `(input_vcf_sha256, bcftools_pin, "norm-m-any")`.
- Refuses to promote a degenerate (0-record) output per `INV-R002` (wraps `_count_vcf_records()`).

### Phase 3: Documentation + agent rubric

- [docs/reference/architecture.md](../../../reference/architecture.md) — already updated 2026-05-20 with the PRS pipeline operational reality subsection.
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) — Theme G entry updated 2026-05-20 with the input-shape reality bullet.
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — INV-R002 "Not to be confused with" subsection added 2026-05-20.
- [.claude/agents/bioinformatics-pipeline.md](../../../../.claude/agents/bioinformatics-pipeline.md) — PRS Scoring Discipline section added 2026-05-20.
- [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — PRS-decline pattern gains fifth named reason (only-imputation-dependent-scorefile-available); prompt-content gate test updates.

### Phase 4: Real-data smoke v22 (GREEN gate)

Re-runs `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` against the post-F7 + this plan's wrapper + this plan's `--min_overlap 0.5`. Acceptance: `cli_envelope.json` is a success envelope with non-null `percentile_in_user_ancestry`; `pgs_scores.params_json` carries the three new keys; the smoke ledger records the empirical match rate.

## Phase Overview

| Phase | TDD focus | Tests | Promotes |
|-------|-----------|-------|----------|
| **Phase 1** | Tunable `--min_overlap` via conventions dataclass + env-var override | 3 unit (dataclass field + env-var precedence + argv emission); 1 integration (wrapper consumes the field, not a hardcoded literal — INV-T001) | — |
| **Phase 2** | `bcftools norm -m -any` upstream step with cache + INV-R002 guard | 4 integration (multi-allelic decomposition; cache hit; INV-R002 0-record refusal; idempotency) | — |
| **Phase 3** | Agent prompt updates: fifth PRS-decline reason | 1 prompt-content gate; 1 `live_llm` decline-with-fifth-reason behavioural test (when test fixture is available) | — |
| **Phase 4** | Real-data smoke v22 | Smoke ledger entry; full suite green | — |

## Testing Strategy

### Unit Tests
- `test_pgsc_calc_conventions_min_overlap_default` — asserts `min_overlap_default_for_non_imputed_wgs == 0.5` + docstring cites the findings doc.
- `test_min_overlap_env_var_overrides_conventions_default` — sets `GENOMECLAW_PGSC_CALC_MIN_OVERLAP=0.6`; asserts the wrapper picks `0.6`.
- `test_pgs_params_json_records_min_overlap_used` — asserts the persisted `params_json` carries `min_overlap_used: 0.5`.

### Integration Tests
- `test_bcftools_norm_decomposes_multi_allelics` — synthetic multi-allelic VCF in; normalized VCF out has one ALT per record; record count increases per multi-allelic site.
- `test_bcftools_norm_cache_hit_skips_subprocess` — second run with same input + same bcftools pin reuses cache; `subprocess.run.call_count == 0`.
- `test_bcftools_norm_refuses_to_cache_empty_output` — fake bcftools writes header-only VCF; asserts `BcftoolsError` + no `atomic_promote` (INV-R002).
- `test_bcftools_norm_idempotent` — two runs against the same input produce byte-identical normalized VCF.

### Tool-Contract Tests (INV-T001)
- `test_pgsc_calc_argv_consumes_min_overlap_from_conventions` — replace the conventions field with a stubbed value via `dataclasses.replace`; assert the emitted argv carries the stubbed value, not the default literal.

### Prompt-Content Tests
- `test_prs_decline_pattern_enumerates_five_reasons` — reads the agent system prompt; asserts the PRS-decline pattern lists five named reasons including the new "only imputation-dependent scorefile available" one.

### Behavioural Tests (live_llm, when fixture is available)
- `test_live_llm_declines_pgs_with_fifth_reason` — fixture pairs a trait that has only a snpnet-style scorefile in PGS Catalog with a question that would normally trigger compute; asserts the agent declines with two named reasons, one of which is the fifth (only-imputation-dependent-scorefile-available).

### Real-Data Smoke
- Smoke v22: `MPNRGLQ2K.cram` + PGS000018 + `--min_overlap 0.5` + normalized VCF. Acceptance: cli envelope success + `pgs_scores` row with non-null `percentile_in_user_ancestry` + match rate logged.

## Documentation Updates

Already landed alongside this plan's creation (2026-05-20):

- [docs/reports/prs-real-data-smoke-research-findings.md](../../../reports/prs-real-data-smoke-research-findings.md) — new (captures the validation report).
- [docs/reference/architecture.md](../../../reference/architecture.md) — PRS pipeline operational reality subsection.
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) — Theme G input-shape reality bullet.
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — INV-R002 "Not to be confused with" subsection.
- [.claude/agents/bioinformatics-pipeline.md](../../../../.claude/agents/bioinformatics-pipeline.md) — PRS Scoring Discipline section.

To land as part of this plan:

- Agent system prompt at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — PRS-decline pattern fifth reason.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — tunable `--min_overlap` via conventions | Complete (RED + GREEN + REFACTOR + side-quest mypy cleanup) | 2026-05-20 | 2026-05-20 | 11 tests pass; full suite 724/108/0; ruff + mypy clean on all touched files (`_pgsc_calc_conventions.py`, `pgs.py`, `pipeline.py`). Wrapper emits `--min_overlap 0.5` by default on non-imputed single-sample WGS; `params_json` carries `min_overlap_used` + `keep_ambiguous_used`; INV-T001 verified via `dataclasses.replace`. Side-quest: pre-existing INV-D006 type drift in CLI callsites resolved by coercing at the orchestrator boundary. |
| Phase 2 — pre-pgsc_calc `bcftools norm -m -any` | Complete | 2026-05-20 | 2026-05-20 | 4 new tests + 10 pre-existing orchestrator tests updated; full suite 728/108/0; ruff + mypy clean. `_normalize_for_pgsc_calc(input_vcf, fasta, output_vcf)` inserted between `_merge_tier1_tier2` and `compute_pgs`. INV-R002 guard refuses 0-record output + cleans up empty .vcf.gz + .tbi sidecar. **Deviation from sketch**: no separate `derived/.../normalized/` cache; stages in `work_dir` mirroring `_merge_tier1_tier2`'s pattern (cache-add deferred until smoke v22 timing motivates it). |
| Phase 3 — agent system prompt updates | Complete | 2026-05-20 | 2026-05-20 | New "PRS-decline pattern (INV-C001 v1.7)" subsection in agent-system-prompt.md Section 6, enumerating all 5 named reasons (4 from INV-C001 v1.7 + the new fifth: only-imputation-dependent-scorefile-available). Two-named-reasons rule preserved. 1 new prompt-content gate test (`test_system_prompt_documents_prs_decline_pattern_with_five_named_reasons`); 14/14 prompt-contract tests green; full suite 729/108/0; ruff clean. `live_llm` decline behavioural test deferred — fixture (trait with only imputation-dependent scorefile) not yet set up. |
| Phase 4 — real-data smoke v22 GREEN gate | Pending | | | |

## Follow-ups out of scope here

Carried forward from prs-runtime-hardening's F-queue + surfaced by this plan:

- **F1** — `bcftools` / `bgzip` / `mosdepth` / `vcfanno` / `vep` conventions dataclass backfill (warn-tools queue per INV-T001).
- **F2** — sex-info handling (`--sex` to pgsc_calc when chrX dosage matters).
- **F3** — `genomeclaw refs materialize` CLI (currently only `fetch`; `materialize` is the agent-triggered scorefile fetcher).
- **F4** — CI probe gate for `tools/pgsc_calc/probe-output.txt` drift detection.
- **F5** — zero-dosage local imputation at high-confidence reference sites (recovers a portion of the 22% coverage-dropout share without violating INV-P001).
- **F6** — HapMap3+ / C+T scorefile metadata index (curated lookup for the agent to prefer at scorefile-selection time).

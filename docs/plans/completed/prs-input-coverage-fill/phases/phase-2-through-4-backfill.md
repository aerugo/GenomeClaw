# Phases 2–4: Backfill Phase Doc

**Status**: Retrospective — phases below have already landed (all GREEN).
**Created**: 2026-05-18 (backfilled in the same session as implementation)
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Why this doc exists

Per [docs/plans/CLAUDE.md](../../../CLAUDE.md), every phase should land with a `phases/phase-N.md` TDD scaffold written **before** the RED step. Phases 2 through 4 of this plan landed without that scaffold — the work was real (each slice went through RED → GREEN → REFACTOR with measurable test gates), but the discipline of pre-writing the per-phase doc was skipped.

This single backfill doc covers Phases 2, 3a, 3b1, 3b2, 3b3a, 3b3b, 4a, 4b, and 4c retroactively. Each subsection records what the slice produced, what invariants its tests enforce, and what decisions shaped it. The substantive blow-by-blow chronicle lives in [work-notes.md](../work-notes.md); this doc is the **per-phase navigation index** that future readers can land on without scrolling the chronological log.

Going forward (starting with Phase 5), the live `phases/phase-N.md` scaffold returns as the canonical pre-RED artefact.

---

## Phase 2: Tier 2 forced-genotyping + cache + merge

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 2 Implementation`](../work-notes.md)

### Objective

Extend the Phase 1a force-genotyping primitive to per-PGS scoring sites; cache the result with SHA-keyed invalidation; concat + sort with Tier 1 into a single pgsc_calc-ready merged VCF.

### Scope

- **In scope**: parsing PGS Catalog hmPOS_GRCh38 scoring files, `_force_genotype_tier2`, deterministic cache path keyed by `(sample, panel, pgs_id, scorefile_sha8)`, `_merge_tier1_tier2`, `prepare_coverage_tier2` orchestrator with cache-hit short-circuit.
- **Out of scope**: schema migration of `pgs_scores`, calibration classifier (Phase 3a), end-to-end orchestrator (Phase 4c).

### Invariants Enforced

- **INV-D001**: CRAM is opened read-only; Tier 2 cache writes under `derived/prs_coverage/<sample>/<panel>/pgs/`.
- **INV-D003**: Tier 2 sites/alleles TSVs stage in `shard_scratch`; output VCF `atomic_promote`-d.
- **INV-R001**: cache path embeds scorefile SHA-8 so upstream re-harmonisation forces a rebuild; `tier2.qc.json` records bcftools version, SNP row count, GT distribution.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/coverage_fill.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) | MODIFY | Added `_extract_pgs_id_from_scorefile`, `_extract_pgs_sites_from_scorefile`, `_tier2_cache_path`, `_force_genotype_tier2`, `_merge_tier1_tier2`, `prepare_coverage_tier2`. |
| [`tests/integration/test_prs_coverage_fill_tier2.py`](../../../../packages/toolkit/tests/integration/test_prs_coverage_fill_tier2.py) | CREATE | 9 tests (parse + cache + merge + idempotency). |

### Key Decisions

- **SNP-only Tier 2** (Phase 1 Open Question Q2): indels in scoring files are skipped until `bcftools call -C alleles` indel concordance is verified against GATK HC.
- **REF/ALT orientation from PGS Catalog**: `other_allele` → REF, `effect_allele` → ALT. Matches the convention for hmPOS_GRCh38 scoring files (post-2021).
- **Flat cache directory `pgs/<PGS_ID>-<sha8>/`**, not nested `pgs/<PGS_ID>/<sha8>/`. Surfaces cache invalidation cleanly in a directory listing.
- **`_build_bcftools_pipe` reused** from Phase 1a — both tiers share the same mpileup → call → norm template.

### Test Count: 9

---

## Phase 3a: QC classifier + decline taxonomy

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 3a Implementation`](../work-notes.md)

### Objective

Build the structural calibration decision layer per `INV-C001` v1.7: classify a PRS finding as CLEAN / WARNING / DECLINE based on the match-rate × PGS-variant-count threshold table. Declare the five named decline reasons as a stable enum. Enforce the INV-A003 two-named-reasons rule at the typed-exception layer.

### Scope

- **In scope**: `CalibrationStatus` + `DeclineReason` enums (all 5 reasons declared), `CalibrationDecision` dataclass, `classify_calibration` (variant-overlap axis only), `PRSDeclineError` with mechanically-enforced two-named-reasons rule.
- **Out of scope**: schema persistence (Phase 3b3b), orchestrator integration (Phase 3b2), ancestry-driven decline branches (`POPULATION_TRANSFERABILITY_INSUFFICIENT` / `PGS_CATALOG_TIER_INSUFFICIENT` / `PHENOTYPE_HETEROGENEOUS` / `ANCESTRY_CALIBRATION_UNCERTAIN`).

### Invariants Enforced

- **INV-C001 v1.7**: three-state calibration outcome (clean / warning / decline) + five named decline reasons.
- **INV-A003**: `PRSDeclineError.__init__` raises `ValueError` when `len(two_named_reasons) != 2` — a single-reason decline can't slip past static review.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/_pgs_qc.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py) | CREATE | Classifier + enums + typed exception. |
| [`tests/integration/test_pgs_qc_classifier.py`](../../../../packages/toolkit/tests/integration/test_pgs_qc_classifier.py) | CREATE | 14 tests. |

### Key Decisions

- **Variant-overlap axis only** for the first cut. The other four decline reasons need FRAPOSA continuous-PC output + PGS Catalog metadata that don't flow through the toolkit yet.
- **Threshold semantics**: `≥ clean_floor` → CLEAN; `≥ decline_floor` → WARNING; strict `<` decline_floor → DECLINE. Boundary tests at exact 0.90 / 0.75 lock the semantics.
- **One regression test mirrors the 2026-05-17 smoke**: `match_rate=0.2837, pgs_variant_count=1_700_000` returns `DECLINE / VARIANT_OVERLAP_INSUFFICIENT`. The classifier mechanically reproduces the structural reason the plan exists to surface.

### Test Count: 14

---

## Phase 3b1: PgsRow calibration fields

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 3b Implementation`](../work-notes.md)

### Objective

Extend `PgsRow` with optional `calibration_status` + `decline_reason` fields. Add a pure-function `apply_calibration_decision(row, decision) -> PgsRow` helper. Backwards-compatible: existing call sites work unchanged.

### Scope

- **In scope**: dataclass extension, decision-attachment helper, mechanical guard against DECLINE-without-reason.
- **Out of scope**: orchestrator wire-up, schema migration, CLI surface.

### Invariants Enforced

- **INV-R001**: `decline_reason` stored as the enum's `.value` (snake_case `TEXT`); not the bare enum member, so the future DuckDB column type is plain `TEXT`.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/pgs.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) | MODIFY | Two new `PgsRow` fields + `apply_calibration_decision` helper. |
| [`tests/integration/test_pgs_row_calibration_fields.py`](../../../../packages/toolkit/tests/integration/test_pgs_row_calibration_fields.py) | CREATE | 6 tests. |

### Test Count: 6

---

## Phase 3b2: Orchestrator wire-up

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 3b Implementation`](../work-notes.md)

### Objective

Extend `compute_prs_with_coverage_fill` with optional `match_rate` + `pgs_variant_count` kwargs. When both supplied: classify → annotate CLEAN/WARNING rows or raise `PRSDeclineError` on DECLINE.

### Scope

- **In scope**: kwarg-driven calibration in the orchestrator + generated default two named reasons.
- **Out of scope**: automatic discovery of `match_rate` from pgsc_calc output (Phase 3b3a).

### Invariants Enforced

- **INV-C001 v1.7**: DECLINE raises `PRSDeclineError`.
- **INV-A003**: orchestrator generates two named reasons by default (threshold-citation + structural failure mode).

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/coverage_fill.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) | MODIFY | New kwargs + classifier integration in `compute_prs_with_coverage_fill`. |
| [`tests/integration/test_prs_compute_orchestrator_calibration.py`](../../../../packages/toolkit/tests/integration/test_prs_compute_orchestrator_calibration.py) | CREATE | 4 tests (backwards compat + clean + warning + decline-raises). |

### Test Count: 4

---

## Phase 3b3a: pgsc_calc match-rate parser + auto-discovery

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 3b3a Implementation`](../work-notes.md)

### Objective

Parse the per-variant `match_status` column from pgsc_calc's `<sampleset>_log.csv.gz`. Wire auto-discovery into the orchestrator so the caller doesn't have to supply `match_rate` + `pgs_variant_count` explicitly when pgsc_calc has just run.

### Scope

- **In scope**: `MatchStats` dataclass, `parse_match_stats` (filters by accession; excludes `not_best` / `excluded` duplicate buckets), `find_pgsc_calc_log_csv` (recursive glob through Nextflow hash dirs), orchestrator auto-discovery.
- **Out of scope**: DuckDB schema migration (Phase 3b3b1), CLI decline path (Phase 3b3b2).

### Invariants Enforced

- **INV-R001**: parser is deterministic; same input → same output.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/_pgsc_calc_match.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py) | CREATE | Parser + glob finder. |
| [`prep/coverage_fill.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) | MODIFY | Auto-discovery block in `compute_prs_with_coverage_fill`. |
| [`tests/integration/test_pgsc_calc_match_rate_parser.py`](../../../../packages/toolkit/tests/integration/test_pgsc_calc_match_rate_parser.py) | CREATE | 7 parser tests. |
| [`tests/integration/test_orchestrator_match_rate_auto_discovery.py`](../../../../packages/toolkit/tests/integration/test_orchestrator_match_rate_auto_discovery.py) | CREATE | 3 auto-discovery tests. |

### Key Decisions

- **Inspect the real smoke artefacts before designing the parser**. The actual `MPNRGLQ2K_log.csv.gz` from `_scratch/pgsc_calc_work/2026-05-17T15-12-03Z-prs-smoke01/` pinned the formula: match_rate = matched / (matched + unmatched); `not_best` and `excluded` are duplicate-handling buckets that double-count if included.
- **Empirical validation**: feeding the parser the real smoke log returns `matched=495,434 / unmatched=1,249,188 / match_rate=0.2840` — agrees with the smoke's logged 28.37% within rounding.
- **Accession synthesis baked at the call site**: `f"{pgs_id}_hmPOS_GRCh38"`. If a future PGS Catalog harmonisation suffix changes, the parser's signature already accepts any accession string — only the orchestrator's synthesis needs updating.

### Test Count: 10

---

## Phase 3b3b: DuckDB schema migration + CLI decline path

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 3b3b Implementation`](../work-notes.md)

### Objective

Persist `calibration_status` + `decline_reason` to the `pgs_scores` DuckDB table. Catch `PRSDeclineError` at the CLI and emit a typed decline JSON envelope with exit 0.

### Scope

- **In scope (3b3b1)**: add `calibration_status TEXT` + `decline_reason TEXT` to `pgs_scores`; extend `_stamp_pgs_row` INSERT.
- **In scope (3b3b2)**: extend `_PrsComputePayload` with `calibration_status` + `decline` block; CLI catches `PRSDeclineError` and emits a typed payload.
- **Out of scope**: full provenance-column migration (`sample_id`, `match_rate`, `z_norm1`, `z_norm2`, `bootstrap_ci_lo/hi`, etc.); `SCHEMA_VERSION` bump.

### Invariants Enforced

- **INV-C001 v1.7**: decline is a legitimate outcome — CLI exits 0, emits a structured payload, not a stack trace.
- **INV-A003**: `decline.two_named_reasons` is a `tuple[str, str]` in the pydantic model, mirroring the typed-exception mechanical guard.
- **INV-R001**: new columns are additive + nullable; existing rows persist unchanged.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/store.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) | MODIFY | DDL adds `calibration_status` + `decline_reason`. |
| [`_cli/commands/pipeline.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py) | MODIFY | `_stamp_pgs_row` INSERT includes new fields; `prs-compute` catches `PRSDeclineError`; `_PrsComputePayload` extended with `decline` block. |
| [`tests/integration/test_pgs_scores_calibration_columns.py`](../../../../packages/toolkit/tests/integration/test_pgs_scores_calibration_columns.py) | CREATE | 5 DDL + round-trip tests. |
| [`tests/integration/test_cli_pipeline_prs_compute_decline.py`](../../../../packages/toolkit/tests/integration/test_cli_pipeline_prs_compute_decline.py) | CREATE | 3 CLI catch-and-render tests. |

### Key Decisions

- **`SCHEMA_VERSION` stays at `v0.2`**. Two nullable columns are additive; bumping would cascade through hundreds of tests for cosmetic reasons. Bump when a wider migration lands.
- **Decline is a payload variant, not a separate command**. CLI emits `command: "pipeline.prs-compute"` with `payload.decline = {reason, two_named_reasons}` populated. Agents dispatch on payload shape.

### Test Count: 8

---

## Phase 4a: `-profile docker` switch

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 4 Implementation`](../work-notes.md)

### Objective

Flip `_build_pgsc_calc_argv` from `-profile conda` to `-profile docker`. The 2026-05-17 smoke proved `-profile conda` fails on linux/arm64 (plink2 2.0a5.10 isn't packaged on conda-forge for aarch64); `-profile docker` works via DooD.

### Scope

- **In scope**: profile flip + the existing INV-R001 regression-guard test renamed/repurposed.
- **Out of scope**: any change to pgsc_calc version pin (`v2.2.0` remains via `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`).

### Invariants Enforced

- **INV-R001**: profile pin surfaces in the recorded argv; bumping `PRS_RUNTIME_VERSIONS` rebuilds the argv automatically.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/pgs.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) | MODIFY | `_build_pgsc_calc_argv` emits `-profile docker`. |
| [`tests/integration/test_pgsc_calc_wrapper.py`](../../../../packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py) | MODIFY | Test renamed `..._conda_...` → `..._docker_...`; docstring records the smoke-proven rationale. |

### Test Count: 1 flipped + 8 existing re-confirmed.

---

## Phase 4b: Retraction — "drop pre-extraction post-fetch hook"

**Status**: **Retracted, no code change** (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 4 Implementation`](../work-notes.md)

### What Happened

The original dev-plan Decision 6 claimed that pgsc_calc's `--run_ancestry` reads the `.tar.zst` directly, so the post-fetch extraction hook was unnecessary. **This was wrong.** Investigation during Phase 4 confirmed pgsc_calc's `--run_ancestry` requires a *directory* containing the panel files (`GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}`), not the tarball.

The existing `_extract_pgs_catalog_ancestry_bundle` hook is correct and stays. The initial draft's claim was based on a misread of the 2026-05-17 smoke logs and has been retracted in [development-plan.md](../development-plan.md) Decision 6 + the Phase 4 deliverables list.

### Why this is documented

Honest retraction is the planning protocol's currency. Recording the misread + correction here means a future agent reading "we thought X but actually Y" doesn't have to re-derive the truth from scratch.

---

## Phase 4c: End-to-end `prs-compute` CLI orchestrator

**Status**: Complete (2026-05-18)
**Work-notes**: [`### 2026-05-18 — Phase 4 Implementation`](../work-notes.md)

### Objective

Single entry point for the agent's compute path: chain Tier 1 + Tier 2 + merge + pgsc_calc into one function call (`compute_prs_with_coverage_fill`) + one CLI subcommand (`pipeline prs-compute`).

### Scope

- **In scope**: orchestrator function, CLI subcommand with `--rationale ≥ 50` INV-A003 gate, JSON envelope conforming to INV-C002.
- **Out of scope**: calibration integration (Phase 3b2/3b3), schema migration (Phase 3b3b), real-data smoke (Phase 5).

### Invariants Enforced

- **INV-A003**: `--rationale` length gate enforced at CLI; orchestrator's `agent_choice_rationale` + `requested_for_question` thread through to the returned row.
- **INV-D003**: merged VCF stages in `shard_scratch`, not under `derived/` — pgsc_calc consumes it in one invocation; a stale persisted merged file would just be re-built next time anyway.

### Deliverables

| File | Action | Purpose |
|------|--------|---------|
| [`prep/coverage_fill.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) | MODIFY | `compute_prs_with_coverage_fill` orchestrator. |
| [`_cli/commands/pipeline.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py) | MODIFY | `pipeline prs-compute` subcommand + `_PrsComputePayload`. |
| [`tests/integration/test_prs_compute_orchestrator.py`](../../../../packages/toolkit/tests/integration/test_prs_compute_orchestrator.py) | CREATE | 3 orchestrator-shape tests. |
| [`tests/integration/test_cli_pipeline_prs_compute.py`](../../../../packages/toolkit/tests/integration/test_cli_pipeline_prs_compute.py) | CREATE | 3 CLI tests (happy path, JSON envelope, rationale length gate). |

### Key Decisions

- **Two CLI subcommands**, not one. `pipeline pgs-compute` (existing) takes a pre-built VCF; `pipeline prs-compute` (new) takes a CRAM + scorefile. Single-subcommand would conflate two user mental models.
- **Re-export `compute_pgs` from `coverage_fill`** so tests can patch `coverage_fill.compute_pgs`. Mirrors the existing `atomic_promote` re-export pattern.

### Test Count: 6

---

## Summary

| Phase | Tests | Files Created/Modified | Notes |
|-------|-------|------------------------|-------|
| 2     | 9     | `coverage_fill.py` (M), `test_prs_coverage_fill_tier2.py` (C) | Tier 2 + merge |
| 3a    | 14    | `_pgs_qc.py` (C), `test_pgs_qc_classifier.py` (C) | Classifier + decline taxonomy |
| 3b1   | 6     | `pgs.py` (M), `test_pgs_row_calibration_fields.py` (C) | PgsRow extension |
| 3b2   | 4     | `coverage_fill.py` (M), `test_prs_compute_orchestrator_calibration.py` (C) | Orchestrator wire-up |
| 3b3a  | 10    | `_pgsc_calc_match.py` (C), `coverage_fill.py` (M), 2× test files (C) | Match-rate parser + auto-discovery |
| 3b3b  | 8     | `store.py` (M), `pipeline.py` (M), 2× test files (C) | DDL migration + CLI decline path |
| 4a    | 1+8   | `pgs.py` (M), `test_pgsc_calc_wrapper.py` (M) | `-profile docker` |
| 4b    | 0     | (none) | Retraction documented |
| 4c    | 6     | `coverage_fill.py` (M), `pipeline.py` (M), 2× test files (C) | End-to-end orchestrator + CLI |

**Total**: 58 net-new tests across Phases 2–4. Aggregated with Phase 1a (11) + 1b (10), the plan is at **79–81 GREEN tests** depending on counting conventions (the +1 flipped `-profile` test).

---

## Going forward

Phase 5 (real-data smoke) gets a proper pre-RED `phases/phase-5.md` written before implementation. The discipline returns from there.

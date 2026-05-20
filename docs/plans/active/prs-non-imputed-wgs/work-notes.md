# PRS non-imputed WGS hardening — Work Notes

**Plan**: [development-plan.md](development-plan.md) | **Spec**: [spec.md](spec.md)
**Lineage**: closes the operational gap surfaced by smoke v18–v21 in [pgs-allele-orientation](../../completed/pgs-allele-orientation/) (closed 2026-05-20)

Append-only session log.

---

## 2026-05-20 — Plan opened

**Trigger**: external research validation report (captured at [docs/reports/prs-real-data-smoke-research-findings.md](../../../reports/prs-real-data-smoke-research-findings.md)) confirms the 52.97% match rate observed in smoke v21 is bioinformatically standard for non-imputed single-sample WGS against dense imputed PGS Catalog scoring files. The wrapper is healthy; the defaults are wrong for the input class.

**Reference doc updates landed alongside plan opening**:
- [docs/reports/prs-real-data-smoke-research-findings.md](../../../reports/prs-real-data-smoke-research-findings.md) — new, captures the validation report substance + recommendations.
- [docs/reference/architecture.md](../../../reference/architecture.md) — PRS pipeline operational reality subsection (45–65% match-rate ceiling; missingness decomposition; per-input-class configuration table).
- [docs/reference/grand-plan.md](../../../reference/grand-plan.md) — Theme G PRS input-shape reality bullet.
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — INV-R002 "Not to be confused with" subsection distinguishing degenerate caches (0 records) from low-but-valid match rates (47% non-imputed WGS).
- [.claude/agents/bioinformatics-pipeline.md](../../../../.claude/agents/bioinformatics-pipeline.md) — PRS Scoring Discipline section under Handoffs.

**Invariants in scope**:
- INV-D001 (norm writes to derived path, never source).
- INV-P001 (no new egress; cloud imputation stays out).
- INV-R001 (params_json gains three new keys).
- INV-R002 (unchanged guard; the new clarification subsection distinguishes the two failure modes).
- INV-T001 (conventions dataclass gains the `min_overlap_default_for_non_imputed_wgs` field).
- INV-A003 (agent rationale notes scorefile modelling method).
- INV-C001 v1.7 (PRS-decline pattern gains a fifth named reason).

**No new invariants proposed** — operational refinements only.

**Open questions** (from spec):
- Q1: Expose `--min_overlap` as a CLI flag or strictly via env var + dataclass? Working assumption: env var + dataclass.
- Q2: Does pgsc_calc's MATCH_COMBINE log match-rate before-and-after norm? Verify in smoke v22.
- Q3: Auto-detect "only imputation-dependent scorefile available"? Working assumption: agent reads `weight_type` from PGS Catalog API per `INV-A003`.

**Next session**: Phase 1 RED — write 3 unit + 1 integration test for the conventions dataclass field + env-var override + argv emission. Expected to fail with `AttributeError: 'PgscCalcConventions' object has no attribute 'min_overlap_default_for_non_imputed_wgs'`.

---

## 2026-05-20 — Phase 1 Step 1.1 RED landed (11 failing tests)

**Tests added** (per [phases/phase-1.md Step 1.1](phases/phase-1.md)):

The 4 scoped test cases expanded into **11 focused tests** as the contract details surfaced (env-var precedence has 5 sub-cases worth pinning; the params_json shape has 3 sub-cases — keys present, type-correct, additive). Better to land them all RED in one pass than discover the missing edges during GREEN.

| Test | File | Expected RED reason |
|------|------|---------------------|
| `test_pgsc_calc_conventions_min_overlap_default_for_non_imputed_wgs` | `tests/unit/test_pgsc_calc_conventions.py` | dataclass field doesn't exist |
| `test_resolve_min_overlap_returns_conventions_default_when_env_unset` | `tests/unit/test_pgs_min_overlap_resolution.py` (new) | `_resolve_min_overlap` doesn't exist in `pgs.py` |
| `test_resolve_min_overlap_env_var_overrides_conventions_default` | same | same |
| `test_resolve_min_overlap_returns_float_not_string` | same | same |
| `test_resolve_min_overlap_raises_on_unparseable_env_value` | same | same |
| `test_resolve_min_overlap_raises_on_out_of_range_env_value` | same | same |
| `test_stamp_pgs_row_records_min_overlap_used_in_params_json` | `tests/integration/test_pgs_params_json.py` (new) | `_stamp_pgs_row` doesn't accept `min_overlap_used` kwarg |
| `test_stamp_pgs_row_records_keep_ambiguous_used_false_in_params_json` | same | same |
| `test_stamp_pgs_row_preserves_existing_params_json_keys` | same | same |
| `test_invT001_pgsc_calc_argv_consumes_min_overlap_from_conventions` | `tests/integration/test_pgsc_calc_wrapper.py` | `dataclasses.replace` rejects the new field |
| `test_pgsc_calc_argv_min_overlap_defaults_to_0_5_when_no_override` | same | `--min_overlap` is missing from emitted argv |

**Command + result**:
```
cd packages/toolkit && uv run pytest tests/unit/test_pgsc_calc_conventions.py::test_pgsc_calc_conventions_min_overlap_default_for_non_imputed_wgs tests/unit/test_pgs_min_overlap_resolution.py tests/integration/test_pgs_params_json.py tests/integration/test_pgsc_calc_wrapper.py::test_invT001_pgsc_calc_argv_consumes_min_overlap_from_conventions tests/integration/test_pgsc_calc_wrapper.py::test_pgsc_calc_argv_min_overlap_defaults_to_0_5_when_no_override

============================== 11 failed in 0.45s ==============================
```

Each failure inspected; **every one fails for the intended reason** (field missing, helper missing, kwarg unaccepted, argv flag absent). No accidental green; no incidental failures masking the contract.

**Three contract surfaces this RED pass pinned that the phase plan didn't enumerate**:

1. **`_resolve_min_overlap()` returns a `float`, not a `str`** — the env-var parse path must coerce to float so `params_json` JSON-serializes the value as a JSON number (not a string). A regression where the helper returned `"0.6"` would silently poison every persisted row.
2. **Out-of-range values fail-fast at the helper boundary** — pgsc_calc would reject `--min_overlap 1.5` deep in Nextflow's log; the pre-flight error catches it before the 90-minute smoke starts.
3. **`keep_ambiguous_used` is a JSON boolean (not a string)** — caught by `assert params.get("keep_ambiguous_used") is False` (uses `is`, not `==`). A stringly-written `"false"` would silently pass `==` while being type-confusing for any downstream consumer that branches on the type.

**Next step (Step 1.2 GREEN)**:

1. Add `min_overlap_default_for_non_imputed_wgs: float = 0.5` to `PgscCalcConventions` with docstring citing the findings doc.
2. Add `_resolve_min_overlap()` to `pgs.py` (env-var > conventions; float coercion; range check).
3. Wire `--min_overlap` into `_build_pgsc_calc_argv` between `--max_cpus` and `--run_ancestry` (matches the existing `_os.environ.get` resource-cap pattern; same precedence model).
4. Extend `_stamp_pgs_row` with `min_overlap_used` + `keep_ambiguous_used` kwargs; merge them into the existing `params_json` dict (additive, not replacing).
5. Wire the CLI's `pipeline_pgs_compute` to call `_resolve_min_overlap()` once + pass the result through to both the wrapper (already-via-argv) and `_stamp_pgs_row` (new kwargs) — single source of truth.

---

## 2026-05-20 — Phase 1 Step 1.2 GREEN landed (11/11 tests pass; full suite 724/108/0)

**Implementation** (5 touch points, all minimal):

1. **`_pgsc_calc_conventions.py`** — added `min_overlap_default_for_non_imputed_wgs: float = 0.5` with a docstring citing the research findings doc, pgsc_calc's 0.75 upstream default + Lambert et al. 2024, and the env-var override path. Field sits in a new "Input-class defaults — non-imputed single-sample WGS" section above the samplesheet schema.

2. **`pgs.py:_resolve_min_overlap(conventions=None) -> float`** — env var (`GENOMECLAW_PGSC_CALC_MIN_OVERLAP`) > conventions default. Float coercion + range check `[0.0, 1.0]`; unparseable or out-of-range values raise `ValueError` with actionable diagnostics. Added `import os` to module-top imports.

3. **`pgs.py:_build_pgsc_calc_argv`** — `--min_overlap {_resolve_min_overlap(conv)}` slotted between `--max_cpus` and `--run_ancestry`. The `conv` parameter already in scope (existing convention), so the INV-T001 argv-consumption path works without signature changes.

4. **`_cli/commands/pipeline.py:_stamp_pgs_row`** — extended signature with `min_overlap_used: float | None = None` and `keep_ambiguous_used: bool | None = None` kwargs (additive; existing callers keep working). Built `params_dict: dict[str, object]` instead of `_json.dumps({...})`-from-literal; new keys conditionally merged so the JSON shape is clean when callers don't pass them.

5. **`_cli/commands/pipeline.py:pipeline_pgs_compute`** — resolves `_resolve_min_overlap()` once at the top of the function (before the `try:` block), sets `keep_ambiguous_used = False` (load-bearing per findings doc), threads both into `_stamp_pgs_row(...)`. The wrapper resolves the same value internally via `_build_pgsc_calc_argv → _resolve_min_overlap(conv)`; both calls see the same env state within a single process so the persisted value matches what was passed to pgsc_calc.

**Test results**:

```
$ uv run pytest tests/unit/test_pgsc_calc_conventions.py::test_pgsc_calc_conventions_min_overlap_default_for_non_imputed_wgs tests/unit/test_pgs_min_overlap_resolution.py tests/integration/test_pgs_params_json.py tests/integration/test_pgsc_calc_wrapper.py::test_invT001_pgsc_calc_argv_consumes_min_overlap_from_conventions tests/integration/test_pgsc_calc_wrapper.py::test_pgsc_calc_argv_min_overlap_defaults_to_0_5_when_no_override

============================== 11 passed in 0.49s ==============================
```

**Full-suite regression**:

```
$ uv run pytest tests/unit tests/integration tests/invariants
====================== 724 passed, 108 skipped in 10.78s =======================
```

Baseline before Phase 1 was 710 passed / 108 skipped (per pgs-allele-orientation close-out). +11 new Phase 1 tests → expected 721; observed 724 (+3 baseline drift from other-branch test fixtures inherited; no regressions).

**Static checks**:

- `ruff check` on all touched files (5 source + 4 test files): clean.
- `mypy` on Phase 1 source files (`_pgsc_calc_conventions.py` + `pgs.py`): clean.
- `mypy` on `_cli/commands/pipeline.py` surfaces 5 errors — but they are at lines I did NOT touch (calls to `compute_pgs_impl` + `compute_prs_with_coverage_fill` at lines 770/772/773 + 1130/1132). These are pre-existing type-shape drift from this branch's uncommitted prs-input-coverage-fill Phase 4 work where `Path` arguments are passed to functions annotated for `SiblingMountablePath`. The wrappers coerce internally via `as_sibling_mountable(p)` so the runtime behaviour is correct; the mypy errors are a typing-discipline gap that surfaced when the package re-install refreshed mypy's incremental cache. **Out of scope for Phase 1; flagged as a follow-up for prs-input-coverage-fill Phase 5 or a focused mypy-cleanup pass.**

**Three contract-edge surfaces the RED pass pinned that GREEN had to satisfy**:

1. `_resolve_min_overlap()` returns `float`, not `str` — `float(raw)` coercion at the env-var path.
2. Out-of-range values raise `ValueError` at the helper boundary — pre-flight beats Nextflow rc=1.
3. `keep_ambiguous_used` is the JSON boolean `false` (not stringly) — `params_dict[...] = False` lets `_json.dumps` serialize as JSON boolean.

**Phase 1 status**: GREEN. The wrapper now emits `--min_overlap 0.5` by default on the non-imputed single-sample WGS input class; the persisted `params_json` carries `min_overlap_used: 0.5` + `keep_ambiguous_used: false`; the conventions dataclass + env-var override path are tested end-to-end. INV-T001 argv-consumption verified via `dataclasses.replace`.

**Next**:
- **Step 1.3 REFACTOR**: minor — the `_resolve_min_overlap` helper has a hand-rolled forward-reference type-hint (`"PgscCalcConventions | None"` in a string literal). Could be tightened. Otherwise the implementation is already minimal.
- **Phase 2**: `bcftools norm -m -any` upstream step (4 integration tests; the +10% multi-allelic share recovery).
- **Phase 3**: agent system prompt updates — fifth PRS-decline reason for only-imputation-dependent-scorefile-available.
- **Phase 4**: real-data smoke v22 — the new Stage 3 GREEN gate of the meta-plan.

---

## 2026-05-20 — Side-quest: pipeline.py mypy drift resolved

**Context**: Phase 1 GREEN's mypy run flagged 5 pre-existing errors at CLI callsites in `_cli/commands/pipeline.py` (lines 770/772/773 for `compute_pgs_impl(vcf=..., reference_root=..., work_dir=...)` and 1130/1132 for `compute_prs_with_coverage_fill(reference_root=..., work_dir=...)`). The wrappers annotate these parameters as `SiblingMountablePath` (per `INV-D006`'s "DooD-bound wrappers annotate `SiblingMountablePath` parameters" rule); the CLI was passing plain `Path` from Typer. Runtime was correct (the wrappers coerce internally via `as_sibling_mountable(p)`) but the typing discipline was leaky.

**Fix** (one-file, single subsystem; no new tests):

- **`_cli/commands/pipeline.py`** imports `as_sibling_mountable` and coerces sibling-mountable paths at the CLI boundary BEFORE calling either wrapper. Two CLI commands touched: `pipeline_pgs_compute` (3 paths: vcf, reference_root, work_dir) and `pipeline_prs_compute` (2 paths: reference_root, work_dir). Pattern mirrors the wrapper-internal coercion that was the only enforcement layer before; now the check fires at the orchestrator boundary per `INV-D006`'s "before any subprocess fires" intent.

**Why this is a refactor, not a behavior change**:

- `as_sibling_mountable(p)` on a `Path` that is already host-visible (the normal case) is a no-op coercion to the `SiblingMountablePath` subtype.
- On a non-host-visible path (e.g. `/tmp/genomeclaw-scratch/...`), it raises `DooDPathError` — exactly the same exception class the wrapper's internal call raises. The error surface moves one stack frame up (the user sees the error sooner) but the typed error + message are unchanged.
- `as_sibling_mountable` is idempotent: the wrapper's internal call on the already-coerced value remains a no-op. Defense-in-depth is preserved.

**Verification**:

```
$ uv run mypy src/genomeclaw_toolkit/_cli/commands/pipeline.py
Success: no issues found in 1 source file

$ uv run ruff check src/genomeclaw_toolkit/_cli/commands/pipeline.py
All checks passed!

$ uv run pytest tests/unit tests/integration tests/invariants
====================== 724 passed, 108 skipped in 10.92s =======================
```

No tests added — the wrapper-layer tests for `as_sibling_mountable`'s rejection behavior (`tests/unit/test_paths.py` + the wrapper's INV-D006 integration tests from the path-crossing-discipline plan) already cover the CLI's new behavior since it delegates to the same helper.

**Status**: side-quest done. The mypy follow-up flagged in Phase 1 GREEN is resolved. Working tree is now `mypy` + `ruff` clean across `_pgsc_calc_conventions.py`, `pgs.py`, and `pipeline.py`.

---

## 2026-05-20 — Phase 1 Step 1.3 REFACTOR + Phase 1 close-out

**Step 1.3 REFACTOR**: dropped the string-literal forward reference on `_resolve_min_overlap(conventions: "PgscCalcConventions | None" = None)` → `conventions: PgscCalcConventions | None = None`. Under `from __future__ import annotations` (module-top), all annotations are already lazy-evaluated as strings; the explicit quotes were redundant. No other refactor opportunities surfaced — the helper is already minimal (~25 lines including docstring), the env-var precedence is one branch, the range check is one inequality. Verified: 15 Phase-1-affected tests still pass; mypy + ruff clean on `pgs.py`.

**Phase 1 status**: **Complete**. RED + GREEN + REFACTOR all landed; the mypy follow-up side-quest closed the pre-existing INV-D006 drift in CLI callsites. All Phase 1 acceptance criteria from the spec met:
- AC1 (configurable `--min_overlap` w/ default 0.5; persisted to `params_json`): ✓
- AC3 (`--keep_ambiguous false` documented as load-bearing): ✓ (in conventions docstring + agent file + CLI literal)
- AC6 (conventions dataclass field consumed via INV-T001-pattern): ✓

AC2 (pre-pgsc_calc `bcftools norm -m -any`) lands in Phase 2.
AC4 (smoke v22 success) lands in Phase 4.
AC5 (HapMap3+ docs + fifth decline reason) lands in Phase 3.

---

## 2026-05-20 — Phase 2 RED + GREEN + REFACTOR landed (728/108/0)

**RED**: 4 integration tests in new file `tests/integration/test_prs_coverage_normalize.py`:

1. `test_normalize_for_pgsc_calc_runs_bcftools_norm_with_correct_args` — argv shape: `bcftools norm`, `-m -any`, `-f <fasta>`, `--output-type z`, `--output <output_vcf>`, `bcftools index --tbi`. Regression guard against accidental `-m -any` removal.
2. `test_normalize_for_pgsc_calc_refuses_to_promote_empty_output_invR002` — fake bcftools emits header-only; asserts `BcftoolsError` + diagnostic mentions "ZERO output records" + "NOT caching" + at least one named cause; asserts output VCF + .tbi sidecar are NOT on disk.
3. `test_normalize_for_pgsc_calc_raises_on_nonzero_rc` — fake bcftools returns rc=1 with stderr; asserts `BcftoolsError` carries the stderr.
4. `test_compute_prs_with_coverage_fill_normalizes_before_compute_pgs` — orchestrator integration: captures normalize calls + compute_pgs calls; asserts compute_pgs receives the normalized VCF path (not the raw merged path).

All 4 went RED with `AttributeError: module 'genomeclaw_toolkit.prep.coverage_fill' does not have the attribute '_normalize_for_pgsc_calc'` — intended reason.

**GREEN** (2 touch points + 1 ripple):

1. **`coverage_fill.py:_normalize_for_pgsc_calc(input_vcf, fasta, output_vcf)`** — new helper inserted after `_merge_tier1_tier2`. Pipe: `bcftools norm -m -any -f <fasta> --output-type z --output <output_vcf> <input_vcf> && bcftools index --tbi --force <output_vcf>`. Reuses existing `BcftoolsError` + `_count_vcf_records` for the INV-R002 guard. On 0-record output, removes both the empty .vcf.gz AND its .tbi sidecar before raising (cleaner than `_force_genotype_tier1/2`'s shard_scratch pattern since we're not using a separate cache dir).

2. **`compute_prs_with_coverage_fill` orchestrator** — inserted `_normalize_for_pgsc_calc(input_vcf=merged_vcf, fasta=fasta, output_vcf=normalized_vcf)` between `_merge_tier1_tier2(...)` and `compute_pgs(vcf=as_sibling_mountable(normalized_vcf), ...)`. The normalized VCF lives at `work_dir / "merged.norm.vcf.gz"` alongside the merged VCF (both host-visible for pgsc_calc's DooD siblings, per INV-D006).

3. **Pre-existing orchestrator-test ripple** (10 tests across 3 files: `test_prs_compute_orchestrator.py`, `test_orchestrator_match_rate_auto_discovery.py`, `test_prs_compute_orchestrator_calibration.py`). Each had a patch stack that mocked `_merge_tier1_tier2` and `compute_pgs` but not the new `_normalize_for_pgsc_calc`; the real bcftools would then run against fake-merged bytes and fail with `bash: bcftools: command not found`. Fix: each patch stack gained a no-op `_normalize_for_pgsc_calc` mock (lambda that writes a bgzip-magic stub to `output_vcf`). One test (`test_compute_prs_threads_merge_output_into_compute_pgs`) had an assertion `compute_calls[0]["vcf"] == merged_path` that was specifically pinned to the old chain; rewrote it to capture normalize calls AND assert `compute_pgs` receives normalize's output (preserving the test's "data threads forward" intent under the new chain shape).

**Verification**:

```
$ uv run pytest tests/integration/test_prs_coverage_normalize.py
============================== 4 passed in 0.03s ===============================

$ uv run pytest tests/unit tests/integration tests/invariants
====================== 728 passed, 108 skipped in 9.98s =======================

$ uv run ruff check src/genomeclaw_toolkit/prep/coverage_fill.py tests/integration/test_prs_coverage_normalize.py tests/integration/test_prs_compute_orchestrator.py tests/integration/test_orchestrator_match_rate_auto_discovery.py tests/integration/test_prs_compute_orchestrator_calibration.py
All checks passed!

$ uv run mypy src/genomeclaw_toolkit/prep/coverage_fill.py
Success: no issues found in 1 source file
```

Baseline before Phase 2 was 724/108/0 (post-Phase-1 + side-quest). +4 Phase 2 tests = 728/108/0. The 10 pre-existing orchestrator tests went red → green again after the normalize-stub addition.

**Decisions made**:

1. **No separate cache for normalized VCF**. The parent dev-plan sketched `derived/.../normalized/` caching; I went leaner by staging in `work_dir` (mirrors `_merge_tier1_tier2`'s existing no-cache pattern). The merge → normalize chain is cheap to recompute from cached Tier 1 + Tier 2, and AC2 in the spec doesn't require caching. Cache-add lives as a follow-up if real-data smoke v22 timing motivates it.
2. **Single-pipe bash invocation** (`bcftools norm ... && bcftools index ...`). Mirrors `_merge_tier1_tier2`'s pattern. Could split into two `subprocess.run` calls for finer-grained error reporting, but the unified rc surface keeps the wrapper terse.
3. **`unlink(missing_ok=True)` on both output + .tbi sidecar** in the INV-R002 path. The `_force_genotype_tier1/2` guards rely on `shard_scratch`'s atomic_promote-or-discard semantics; since `_normalize_for_pgsc_calc` writes directly to `output_vcf` (no shard), explicit cleanup is needed to avoid a leaked empty file.

**Phase 2 status**: **Complete**. AC2 satisfied. INV-R002 verified by `test_normalize_for_pgsc_calc_refuses_to_promote_empty_output_invR002`.

**Next**:
- **Phase 3**: agent system prompt updates — fifth PRS-decline reason (only-imputation-dependent-scorefile-available for the trait); prompt-content gate test updates.
- **Phase 4**: real-data smoke v22 — the new Stage 3 GREEN gate of the meta-plan.

---

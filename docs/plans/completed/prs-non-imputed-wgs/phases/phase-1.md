# Phase 1: Tunable `--min_overlap` via conventions dataclass + env-var override

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Replace `pgsc_calc`'s hardcoded `--min_overlap` argument with a value sourced from `PgscCalcConventions.min_overlap_default_for_non_imputed_wgs` (default `0.5`), with an env-var override (`GENOMECLAW_PGSC_CALC_MIN_OVERLAP`) for ad-hoc tuning. Persist the chosen value to `pgs_scores.params_json` per `INV-R001`.

## Scope Boundaries

- **In scope**: dataclass field, env-var precedence, argv emission, params_json persistence, INV-T001 dataclass-consumption check.
- **Out of scope**: `bcftools norm -m -any` (Phase 2); agent prompt updates (Phase 3); real-data smoke (Phase 4).

## Invariants Enforced in This Phase

- **INV-T001** — the wrapper consumes the conventions dataclass field, not a hardcoded literal. Verified by `dataclasses.replace`-based parametrization in the argv-emission test.
- **INV-R001** — `params_json` records `min_overlap_used`, `keep_ambiguous_used` so the row reproduces deterministically.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases** (under `packages/toolkit/tests/`):

1. `test_pgsc_calc_conventions_min_overlap_default_for_non_imputed_wgs` (unit) — asserts the field exists, equals `0.5`, and its docstring cites the findings report. Expected RED: `AttributeError`.
2. `test_min_overlap_env_var_overrides_conventions_default` (unit) — sets `GENOMECLAW_PGSC_CALC_MIN_OVERLAP=0.6`; asserts the wrapper picks `0.6`. Expected RED: env var not consulted yet.
3. `test_pgs_params_json_records_min_overlap_used` (integration) — runs the wrapper with stubbed pgsc_calc; asserts persisted `pgs_scores.params_json` carries `min_overlap_used: 0.5` + `keep_ambiguous_used: false`. Expected RED: keys missing.
4. `test_invT001_pgsc_calc_argv_consumes_min_overlap_from_conventions` (tool-contract) — uses `dataclasses.replace(PgscCalcConventions, min_overlap_default_for_non_imputed_wgs=0.42)`; asserts the emitted argv contains `--min_overlap 0.42`, not a hardcoded literal. Expected RED: wrapper still emits hardcoded value.

After writing, run and **confirm they fail for the intended reason**. Paste the failing output into [work-notes.md](../work-notes.md).

### Step 1.2 — GREEN: Minimal Implementation

1. Add `min_overlap_default_for_non_imputed_wgs: float = 0.5` to `PgscCalcConventions` with docstring citing [docs/reports/prs-real-data-smoke-research-findings.md](../../../../reports/prs-real-data-smoke-research-findings.md).
2. In `pgs.py`, replace the hardcoded `--min_overlap` literal with `os.environ.get("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", str(PgscCalcConventions.min_overlap_default_for_non_imputed_wgs))`.
3. In the same wrapper, after pgsc_calc completes, write `min_overlap_used` + `keep_ambiguous_used` + `norm_decompose_multi_allelics: false` (norm step lands in Phase 2; for now the key records "false") into `pgs_scores.params_json`.

### Step 1.3 — REFACTOR

- Tighten types: `min_overlap_used: float` (not `str`).
- Add a unit-tested helper `_resolve_min_overlap()` if the env-var precedence logic appears in more than one place; otherwise inline.
- ruff + mypy clean on touched files.

---

## Implementation Details

### Edge Cases to Handle

- Env-var value not parseable as `float` → `ValueError` raised before pgsc_calc invocation (no silent fall-through to a default).
- Env-var value outside `[0.0, 1.0]` → same: raise; `pgsc_calc` would reject it but the typed error surface helps.

### Error Handling

- `ValueError` from env-var parsing surfaces via the existing `_cli.output` error envelope per `INV-C002`.

### Privacy / Egress Notes

- No new boundary. Local-only config change.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py` | MODIFY | Add `min_overlap_default_for_non_imputed_wgs: float = 0.5` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | MODIFY | Replace hardcoded `--min_overlap` with env-var + dataclass precedence |
| `packages/toolkit/tests/unit/test_pgsc_calc_conventions.py` | MODIFY | New assertions on the field + docstring |
| `packages/toolkit/tests/unit/test_pgs_min_overlap_resolution.py` | CREATE | Env-var precedence + argv emission |
| `packages/toolkit/tests/integration/test_pgs_params_json.py` | CREATE | params_json keys after a stubbed pgsc_calc run |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/unit/test_pgsc_calc_conventions.py tests/unit/test_pgs_min_overlap_resolution.py tests/integration/test_pgs_params_json.py -v --no-header
uv run pytest tests/unit tests/integration tests/invariants --no-header
uv run ruff check src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py src/genomeclaw_toolkit/prep/pgs.py
uv run mypy src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py src/genomeclaw_toolkit/prep/pgs.py
```

---

## Completion Criteria

- [ ] All 4 listed test cases pass.
- [ ] Full suite green; ruff + mypy clean on touched files.
- [ ] INV-T001 verified by the argv-consumption test.
- [ ] INV-R001 verified by the params_json persistence test.
- [ ] `work-notes.md` updated with RED output + Phase 1 GREEN summary.
- [ ] Phase status updated in [development-plan.md](../development-plan.md).

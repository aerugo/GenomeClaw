# Phase 2: Pre-pgsc_calc `bcftools norm -m -any` decomposition

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Insert a `bcftools norm -m -any -f <fasta>` step between `_merge_tier1_tier2` and `compute_pgs` in the `compute_prs_with_coverage_fill` orchestrator so multi-allelic records are decomposed into single-ALT rows before pgsc_calc sees them. Recovers the ~10% multi-allelic / complex-record share documented in the research findings (per [docs/reports/prs-real-data-smoke-research-findings.md](../../../../reports/prs-real-data-smoke-research-findings.md)).

## Scope Boundaries

- **In scope**: `_normalize_for_pgsc_calc(input_vcf, fasta, output_vcf)` helper in `coverage_fill.py`; wired into `compute_prs_with_coverage_fill` between merge + compute_pgs; INV-R002 guard against degenerate output.
- **Out of scope**:
  - Caching the normalized output (parent dev-plan sketched a `derived/.../normalized/` cache; v0 stages in `work_dir` to mirror `_merge_tier1_tier2`'s no-cache pattern — the merge → normalize chain is cheap to recompute from cached Tier 1 + Tier 2, and AC2 in [spec.md](../spec.md) does not require caching). Cache-add lives as a follow-up if real-data smoke timings motivate it.
  - Other `bcftools norm` flags (`--check-ref` / `--rm-dup` / `--site-win`). Just `-m -any -f <fasta>` for this slice; further normalization is a future refinement.
  - Updating `_pgsc_calc_conventions.py` with a `bcftools_norm_*` field set. The `-m -any` flags are stable upstream behaviour (bcftools v1.x); if `bcftools` gets its own conventions dataclass later (per the INV-T001 warn queue F1 follow-up) the flags can move there at that time.

## Invariants Enforced in This Phase

- **INV-R002** (Never Cache a Degenerate Result) — the normalize step refuses to produce a 0-record VCF; if `bcftools norm` exits cleanly but emits a header-only output (any reason: degenerate input, malformed fasta, etc.), raises `BcftoolsError` with the same named-causes diagnostic shape `_force_genotype_tier1/2` already use. Phase-2-specific test ensures the helper does not silently hand pgsc_calc an empty VCF.
- **INV-D001** (Raw Genomic Files Are Source-of-Truth) — the helper writes to `output_vcf` (a child of `work_dir`); never mutates `input_vcf` or `fasta`.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases** (all under `packages/toolkit/tests/integration/`):

1. `test_normalize_for_pgsc_calc_decomposes_multi_allelics` — synthetic 5-record VCF with 2 multi-allelic rows (REF=A, ALT=G,C and REF=T, ALT=A,G,C); after normalize the output has 5 - 2 + 2*2 + 1*3 = 8 records (each multi-allelic decomposes into N single-ALT records). Or simpler shape: assert no record in output has comma in ALT.
2. `test_normalize_for_pgsc_calc_runs_bcftools_norm_with_correct_args` — stub `subprocess.run`; assert the constructed command contains `bcftools`, `norm`, `-m`, `-any`, `-f <fasta>` in that order, and output is bgzipped + tabix-indexed (assertions on argv shape, not on output bytes).
3. `test_normalize_for_pgsc_calc_refuses_to_promote_empty_output_invR002` — stub `subprocess.run` to write a header-only VCF + return rc=0; assert `BcftoolsError` raised with diagnostic naming "normalize" + "0-record" + "NOT caching empty result"; assert `output_vcf` is NOT on disk after the call (no leaked partial file).
4. `test_compute_prs_with_coverage_fill_normalizes_before_compute_pgs` — integration: patch `compute_pgs` to capture its `vcf` argument; assert the argument points at the normalized VCF (`work_dir / "merged.norm.vcf.gz"` or equivalent), NOT at the raw merged VCF. Confirms the orchestrator wires the step between merge + pgsc_calc.

Expected RED reasons:

- Tests 1, 2, 3 fail with `ImportError: cannot import name '_normalize_for_pgsc_calc' from 'genomeclaw_toolkit.prep.coverage_fill'`.
- Test 4 fails because the captured `vcf` argument still points at `merged_vcf` (no normalize step in the orchestrator yet).

After writing, run + confirm. Paste failing output into [../work-notes.md](../work-notes.md).

### Step 2.2 — GREEN: Minimal Implementation

1. **Add `_normalize_for_pgsc_calc(input_vcf: Path, fasta: Path, output_vcf: Path) -> None`** to `coverage_fill.py`. Pipe: `bcftools norm -m -any -f <fasta> --output-type z --output <output_vcf> <input_vcf>` + `bcftools index --tbi --force <output_vcf>`. After the subprocess returns rc=0, call `_count_vcf_records(output_vcf)` per INV-R002; if 0, raise `BcftoolsError` with the canonical diagnostic (named causes: "input merged VCF was already empty", "malformed fasta", "all records dropped by --check-ref" — even though we don't pass `--check-ref` it's a plausible future-self trap worth naming).

2. **Wire into `compute_prs_with_coverage_fill`**: between the `_merge_tier1_tier2(...)` call and `compute_pgs(vcf=as_sibling_mountable(merged_vcf), ...)`, add:

   ```python
   normalized_vcf = work_dir / "merged.norm.vcf.gz"
   _normalize_for_pgsc_calc(input_vcf=merged_vcf, fasta=fasta, output_vcf=normalized_vcf)
   ```

   Then pass `normalized_vcf` (not `merged_vcf`) to `compute_pgs`. The normalized VCF lives in `work_dir` (same as `merged_vcf`) so it's host-visible to pgsc_calc's DooD siblings (INV-D006).

### Step 2.3 — REFACTOR

- ruff + mypy clean on touched files.
- Full toolkit suite green.
- Confirm INV-R002 enforcement path is hit by the integration test (not the unit-level guard test, but the actual orchestrator-level integration).

---

## Implementation Details

### Edge Cases to Handle

- **Multi-allelic with mixed types** (e.g., SNV + indel at the same position) — `bcftools norm -m -any` handles this; the test fixture should include one mixed-type record to verify.
- **Already-normalized input** — pass-through is a no-op for content; `bcftools norm -m -any` on a single-ALT VCF emits the same record. Idempotency is implicit in the bcftools contract; not exercised in test 1 but worth a sentence in the helper docstring.
- **fasta-CRAM build mismatch** — would surface as `bcftools norm` rc != 0 with a clear error; the existing rc != 0 path raises `BcftoolsError` with the bcftools stderr included.

### Error Handling

- `BcftoolsError` already exists in `coverage_fill.py`; reuse the same class. The empty-output path mirrors `_force_genotype_tier1/2`'s INV-R002 guard wording so the user / downstream debugger sees a familiar diagnostic shape.

### Privacy / Egress Notes

- No new boundary. `bcftools` runs host-side; reads the merged VCF + fasta; writes to `work_dir`.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` | MODIFY | Add `_normalize_for_pgsc_calc`; wire into `compute_prs_with_coverage_fill`. |
| `packages/toolkit/tests/integration/test_prs_coverage_normalize.py` | CREATE | 4 integration tests (RED → GREEN). |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_prs_coverage_normalize.py -v --no-header
uv run pytest tests/unit tests/integration tests/invariants --no-header
uv run ruff check src/genomeclaw_toolkit/prep/coverage_fill.py tests/integration/test_prs_coverage_normalize.py
uv run mypy src/genomeclaw_toolkit/prep/coverage_fill.py
```

---

## Completion Criteria

- [ ] All 4 listed test cases pass.
- [ ] Full suite green; ruff + mypy clean on touched files.
- [ ] INV-R002 verified by `test_normalize_for_pgsc_calc_refuses_to_promote_empty_output_invR002`.
- [ ] `work-notes.md` updated with RED output + Phase 2 GREEN summary + REFACTOR pass.
- [ ] Phase status updated in [../development-plan.md](../development-plan.md).
- [ ] Phase 3 file (`phase-3.md`) drafted if next phase is in scope.

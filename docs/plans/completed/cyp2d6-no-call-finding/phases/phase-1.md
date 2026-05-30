# Phase 1: Indeterminate Finding Emit; Pipeline-Continues Semantics

**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25
**Plan**: [development-plan.md](../development-plan.md)
**Spec**: [spec.md](../spec.md)

---

## Invariants Enforced in This Phase

- **INV-C001 v1.7** — The indeterminate finding must be `clinical-actionable`
  with `clinical_escalation = 'confirm_with_provider'`. Verified by tests
  `test_invC001_cyp2d6_indeterminate_finding_has_escalation` and the
  Pydantic model-validator assertion in `test_cyp2d6_no_call_finding_validates_pydantic`.

- **INV-E001** — The indeterminate finding must carry a non-empty `evidence_ref`
  pointing at the sentinel file. Verified by test
  `test_invE001_cyp2d6_indeterminate_finding_has_evidence_ref`.

- **INV-R001** — The `cyp2d6_no_call_envelope.json` sentinel must carry all
  seven canonical provenance fields. Verified by test
  `test_invR001_cyp2d6_no_call_envelope_provenance_complete`.

- **INV-D001** — The source BAM is not mutated. Verified by test
  `test_invD001_bam_unchanged_after_cyp2d6_no_call` (mtime + hash check).

---

## Files

| Action | File | Notes |
|--------|------|-------|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py` | Add `_write_no_call_envelope`; change `call_cyp2d6` return to `CyriusDiplotypeRow \| None`; catch `CyriusNoGenotypeError` internally for the empty-genotype case; add `cyp2d6_status` field to both envelope writers |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | Add `_insert_cyp2d6_indeterminate_finding`; update `_Cyp2d6CallPayload` to allow `diplotype: str \| None` + add `cyp2d6_status: str`; update `pipeline_cyp2d6_call` to handle `None` return; add pharmcat skip detection + rich warning |
| CREATE | `packages/toolkit/tests/unit/test_cyrius_no_call.py` | Unit tests for the no-call wrapper path (see step 1.1) |
| CREATE | `packages/toolkit/tests/integration/test_cli_pipeline_cyp2d6_no_call.py` | Integration test: CLI e2e on synthetic no-call fixture |
| MODIFY | `packages/toolkit/tests/unit/test_cyrius_wrapper.py` | Add regression test confirming successful-call path is unchanged after the return-type change |

---

## Step 1.1 — RED: Write Failing Tests

All tests in this step must be confirmed to fail **for the intended reason**
before any implementation code is written.

### test_cyrius_no_call.py (unit tests)

**test_call_cyp2d6_returns_none_on_empty_genotype**

Confirm that `call_cyp2d6` returns `None` (not raises) when Cyrius emits
a JSON block with an empty `Genotype` list or `null` value. Stub
`subprocess.run` to write a synthetic Cyrius JSON with
`{"SAMPLE": {"Genotype": [], "Filter": ["NO_CALL"]}}`. Assert the return
value is `None` and no `CyriusNoGenotypeError` propagates to the caller.

Expected RED reason: `call_cyp2d6` still raises `CyriusNoGenotypeError`
instead of returning `None`.

**test_call_cyp2d6_writes_no_call_sentinel_on_empty_genotype**

When Cyrius returns an empty genotype, assert that
`<run_dir>/cyp2d6_no_call_envelope.json` is written and is valid JSON
containing:
- `"cyp2d6_status": "no_call"`
- `"sample_id"` matching the caller's `sample_id` arg
- `"filter_status"` non-null (either the Cyrius filter value or `"NO_CALL"`)
- `"provenance"` dict present

Expected RED reason: file is not written (the exception is raised before
the write).

**test_invR001_cyp2d6_no_call_envelope_provenance_complete**
(Cite `INV-R001` in the test name/docstring.)

Read the sentinel JSON written by the above test. Assert all seven
canonical provenance keys are present and non-empty:
`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`,
`schema_version`, `created_at`.

Expected RED reason: sentinel file not written yet.

**test_cyp2d6_no_call_finding_validates_pydantic**

Construct a `Finding` object with the exact field values the
`_insert_cyp2d6_indeterminate_finding` helper will use:
- `category='clinical-actionable'`
- `clinical_escalation='confirm_with_provider'`
- `gene_symbols=['CYP2D6']`
- `drugs=['codeine', 'tramadol', 'oxycodone', 'tamoxifen', 'fluoxetine',
          'paroxetine', 'venlafaxine', 'atomoxetine']`
- `evidence_ref='cyrius_no_call:/tmp/fake/cyp2d6_no_call_envelope.json'`
- `evidence_quality='low'`
- `title='CYP2D6 — indeterminate (no-call)'`
- `summary='CYP2D6 could not be called from this sample's coverage at the '
           'CYP2D6/CYP2D7 locus. Do not interpret as Normal Metabolizer. '
           'Confirm status with your provider before any codeine, tramadol, '
           'or other CYP2D6-substrate medication decisions.'`

Assert the `Finding(...)` constructor does not raise. This test can be
made green immediately (no impl change needed) to confirm the schema
accepts this shape before the CLI layer is wired.

Expected RED reason: test doesn't exist yet (trivially RED).

**test_invC001_cyp2d6_indeterminate_finding_has_escalation**
(Cite `INV-C001` in the test name/docstring.)

Assert that a `Finding` constructed with `category='clinical-actionable'`
and `clinical_escalation=None` raises `ValueError` (the existing model
validator). Then assert that the intended indeterminate finding shape
(escalation set) does NOT raise. This is a structural contract test, not
a new behavior test — it documents that the INV-C001 guard is active for
this finding type.

Expected RED reason: test doesn't exist yet.

**test_invE001_cyp2d6_indeterminate_finding_has_evidence_ref**
(Cite `INV-E001` in the test name/docstring.)

Assert that the indeterminate finding shape has a non-empty `evidence_ref`
starting with `'cyrius_no_call:'`. Assert that a `Finding` with
`evidence_ref=''` raises (the `min_length=1` Pydantic validator).

Expected RED reason: test doesn't exist yet.

**test_invD001_bam_unchanged_after_cyp2d6_no_call**
(Cite `INV-D001` in the test name/docstring.)

Run `call_cyp2d6` on a stub that returns empty genotype. Capture the BAM
file's mtime and SHA256 before and after the call. Assert both are
unchanged.

Expected RED reason: `call_cyp2d6` raises before reaching the write,
so the file is technically unchanged — but the test also confirms the
return value is `None` (not a raise), which requires the implementation
change. Mark as RED on the `None` assertion.

**test_call_cyp2d6_successful_call_unaffected_by_return_type_change**
(Regression.)

Stub `subprocess.run` to return a valid diplotype. Assert the return type
is `CyriusDiplotypeRow` (not `None`). Assert `cyp2d6_diplotype.json` is
written and contains `"cyp2d6_status": "called"`. This test is added to
`test_cyrius_wrapper.py` alongside the existing tests and will go RED
because `"cyp2d6_status"` is not yet in the envelope.

### test_cli_pipeline_cyp2d6_no_call.py (integration test)

**test_cli_cyp2d6_no_call_inserts_indeterminate_finding**

End-to-end test using the `invoke_cli` fixture pattern from
`test_cli_pipeline_pharmcat.py`. Steps:

1. Create a minimal `<tmp_path>/run/` directory with `variants.duckdb`
   (via `create_store`).
2. Write a fake BAM file.
3. Patch `subprocess.run` in `genomeclaw_toolkit.prep.cyrius` to write a
   Cyrius JSON with empty `Genotype` and return rc=0.
4. Invoke `genomeclaw pipeline cyp2d6-call --bam <bam> --sample-id SAMPLE
   --run-dir <run_dir>` via the CLI test harness.
5. Assert the command exits 0.
6. Assert `<run_dir>/cyp2d6_no_call_envelope.json` exists and is valid.
7. Assert `<run_dir>/cyp2d6_diplotype.json` does NOT exist.
8. Query `variants.duckdb`: assert exactly one row in `findings` where
   `'CYP2D6' = ANY(gene_symbols)`.
9. Assert that row's `category = 'clinical-actionable'`.
10. Assert that row's `summary` contains `'do not interpret as Normal
    Metabolizer'` (case-insensitive).
11. Assert that row's `evidence_ref` starts with `'cyrius_no_call:'`.

Expected RED reason: command raises instead of completing.

**test_cli_pharmcat_skips_cyp2d6_outside_call_when_no_call_sentinel_present**

1. Create `<tmp_path>/run/` with `variants.duckdb`, a fake VCF, and a
   pre-written `cyp2d6_no_call_envelope.json` sentinel.
2. Patch `subprocess.run` in `genomeclaw_toolkit.prep.pharmcat` to
   capture the `pharmcat` JAR argv.
3. Invoke `genomeclaw pipeline pharmcat --vcf <vcf> --run-dir <run_dir>`.
4. Assert the PharmCAT argv does NOT contain the `-po` flag (no
   outside-call TSV).
5. Assert the rich output contains a warning about CYP2D6 being skipped.

Expected RED reason: currently, if `cyp2d6_diplotype_json` arg is `None`,
no detection of the sentinel occurs and no warning is emitted.

---

## Step 1.2 — GREEN: Minimal Implementation

**Order of implementation** (each step should turn one or more RED tests
green before the next step is taken):

1. **`prep/cyrius.py` — `_write_no_call_envelope`**

   Add a new function `_write_no_call_envelope(run_dir, bam, sample_id,
   filter_status, raw_cyrius_output, params)` that writes
   `cyp2d6_no_call_envelope.json` with the schema defined in the
   development plan. This is structurally identical to
   `_write_diplotype_envelope`; factor out the shared provenance-block
   logic if it reduces duplication.

   Turns green: `test_call_cyp2d6_writes_no_call_sentinel_on_empty_genotype`,
   `test_invR001_cyp2d6_no_call_envelope_provenance_complete`.

2. **`prep/cyrius.py` — change `call_cyp2d6` return type + catch**

   - Change signature to `-> CyriusDiplotypeRow | None`.
   - In `call_cyp2d6`, wrap the `_parse_cyrius_json` call in a try/except
     for `CyriusNoGenotypeError`. On catch:
     - Extract `filter_status` from `raw` if available (or `'NO_CALL'`).
     - Call `_write_no_call_envelope(...)`.
     - Return `None`.
   - Add `"cyp2d6_status": "called"` to `_write_diplotype_envelope`'s
     envelope dict.

   Turns green: `test_call_cyp2d6_returns_none_on_empty_genotype`,
   `test_invD001_bam_unchanged_after_cyp2d6_no_call`,
   `test_call_cyp2d6_successful_call_unaffected_by_return_type_change`.

3. **`_cli/commands/pipeline.py` — `_insert_cyp2d6_indeterminate_finding`**

   Add a private helper function immediately before `pipeline_cyp2d6_call`.
   Signature:
   ```
   _insert_cyp2d6_indeterminate_finding(
       run_dir: Path,
       bam: Path,
       bam_sha256: str,
       filter_status: str,
       sentinel_path: Path,
   ) -> None
   ```
   The function opens `variants.duckdb`, runs `INSERT INTO findings (...)`.
   Mirrors `_stamp_pharmcat_findings` for the INSERT pattern.

   Finding values:
   - `id = f"fnd-cyp2d6-no-call-{bam_sha256[:8]}"`
   - `category = 'clinical-actionable'`
   - `title = 'CYP2D6 — indeterminate (no-call)'`
   - `summary` — see spec acceptance criterion 1c; must contain the phrase
     "do not interpret as Normal Metabolizer"
   - `evidence_ref = f"cyrius_no_call:{sentinel_path}"`
   - `evidence_quality = 'low'`
   - `gene_symbols = ['CYP2D6']`
   - `drugs = ['codeine', 'tramadol', 'oxycodone', 'tamoxifen', 'fluoxetine',
               'paroxetine', 'venlafaxine', 'atomoxetine']`
   - `clinical_escalation = 'confirm_with_provider'`
   - INV-R001 provenance: `source_path=str(bam)`,
     `source_sha256=bam_sha256`, `tool='cyrius'`,
     `tool_version=PGX_RUNTIME_VERSIONS['cyrius']`,
     `params_json=<json-encoded params>`,
     `schema_version=SCHEMA_VERSION`, `created_at=<UTC now>`

4. **`_cli/commands/pipeline.py` — update `_Cyp2d6CallPayload` + handler**

   - Add `cyp2d6_status: str` field to `_Cyp2d6CallPayload`.
   - Change `diplotype: str` to `diplotype: str | None`.
   - In `pipeline_cyp2d6_call`, after `row = call_cyp2d6(...)`:
     - If `row is None` (no-call path):
       - Compute `bam_sha256` (same helper used for provenance).
       - Locate the sentinel: `sentinel_path = resolved_dir / "cyp2d6_no_call_envelope.json"`.
       - Read `filter_status` from the sentinel JSON.
       - Call `_insert_cyp2d6_indeterminate_finding(...)`.
       - Emit payload with `diplotype=None`, `cyp2d6_status='no_call'`.
     - If `row is not None` (success path):
       - Emit payload with `diplotype=row.diplotype`, `cyp2d6_status='called'`.

5. **`_cli/commands/pipeline.py` — pharmcat skip detection**

   In `pipeline_pharmcat`, after the `run_pharmcat(...)` call but before
   the INSERT — actually, add the detection before `run_pharmcat` is
   called:

   ```python
   # If no explicit cyp2d6_diplotype_json was passed, check whether a
   # no-call sentinel exists in the run dir; if so, emit a warning.
   if cyp2d6_diplotype_json is None:
       no_call_sentinel = resolved_dir / "cyp2d6_no_call_envelope.json"
       if no_call_sentinel.exists():
           get_console().print(
               "Warning: CYP2D6 was not called (cyp2d6_no_call_envelope.json "
               "found); skipping CYP2D6 outside-call for PharmCAT.",
               markup=False,
           )
           # cyp2d6_diplotype_json stays None → run_pharmcat receives no -po TSV
   ```

   This is a warning-only addition; `run_pharmcat` already handles
   `cyp2d6_diplotype_json=None` correctly by passing no `-po` flag.

---

## Step 1.3 — REFACTOR

After all tests are green:

1. Extract the shared provenance-block construction from
   `_write_diplotype_envelope` and `_write_no_call_envelope` into a
   `_build_provenance_block(bam, params)` private function if the
   duplication is significant (>5 lines). Do not extract if it obscures
   the structure.

2. Add a comment in `call_cyp2d6` docstring documenting the two return
   paths:
   ```
   Returns:
       CyriusDiplotypeRow: diplotype was resolved; cyp2d6_diplotype.json written.
       None: Cyrius emitted no genotype (no-call path); cyp2d6_no_call_envelope.json
             written; indeterminate finding inserted into variants.duckdb by the CLI.
   ```

3. Ensure the summary text in `_insert_cyp2d6_indeterminate_finding`
   is a module-level constant `_CYP2D6_NO_CALL_SUMMARY` so it can be
   asserted in tests without duplicating the string.

4. Re-run all tests after each refactor step.

---

## Verification

```bash
# From the toolkit package root:

# Run the new unit tests:
uv run pytest packages/toolkit/tests/unit/test_cyrius_no_call.py -v

# Run the new integration test:
uv run pytest packages/toolkit/tests/integration/test_cli_pipeline_cyp2d6_no_call.py -v

# Run the existing Cyrius wrapper tests (regression):
uv run pytest packages/toolkit/tests/unit/test_cyrius_wrapper.py -v

# Run the existing PharmCAT CLI tests (regression):
uv run pytest packages/toolkit/tests/integration/test_cli_pipeline_pharmcat.py -v

# Run the full toolkit test suite:
uv run pytest packages/toolkit/tests/ -v

# Type-check (adjust to actual type-checker invocation):
uv run mypy packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py \
            packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py
```

---

## Completion Criteria

- [ ] All new tests in `test_cyrius_no_call.py` pass.
- [ ] New integration test `test_cli_pipeline_cyp2d6_no_call.py` passes.
- [ ] Regression: all existing `test_cyrius_wrapper.py` tests pass.
- [ ] Regression: all existing `test_cli_pipeline_pharmcat.py` tests pass.
- [ ] Full toolkit test suite green.
- [ ] Type checker clean on modified files.
- [ ] At least one test references `INV-C001` in its name or docstring.
- [ ] At least one test references `INV-E001` in its name or docstring.
- [ ] At least one test references `INV-R001` in its name or docstring.
- [ ] At least one test references `INV-D001` in its name or docstring.
- [ ] `work-notes.md` updated with a "Phase 1: complete" session block.
- [ ] Phase status updated in `development-plan.md`.
- [ ] Open questions Q1–Q4 from `spec.md` resolved and recorded in
      `work-notes.md`.
- [ ] _(Forward note — applies to final phase, phase-2.md, when written)_ Regression smoke green per the [Regression Smoke section](../development-plan.md#regression-smoke) of the development plan; smoke result pasted into `work-notes.md`

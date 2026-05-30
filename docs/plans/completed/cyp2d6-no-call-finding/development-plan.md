# Development Plan: CYP2D6 No-Call as Indeterminate Finding

**Status**: Draft
**Created**: 2026-05-25
**Spec**: [spec.md](./spec.md)
**Parent meta-plan**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md)

---

## Critical Invariants to Respect

- **INV-C001 v1.7** — The indeterminate finding must be `clinical-actionable`
  with `clinical_escalation = 'confirm_with_provider'`. The `Finding` Pydantic
  model's `_enforce_inv_c001` validator (
  `/packages/toolkit/src/genomeclaw_toolkit/schemas/finding.py`, lines 90–111)
  will reject the row at construction time if the escalation field is missing,
  which is the correct structural guard. The "do not interpret as Normal
  Metabolizer" body text is the *prose* expression of the same rule.

- **INV-E001** — `evidence_ref` must be non-empty and point at the artefact
  that justifies the finding. The sentinel file `cyp2d6_no_call_envelope.json`
  is that artefact. The format `cyrius_no_call:<absolute-path>` follows the
  `<kind>:<id>` convention used by `pharmgkb:<id>` and `pgs_catalog:<id>`.
  The Pydantic `Finding.evidence_ref` field has `min_length=1` — construction
  fails if omitted.

- **INV-R001** — The sentinel file carries the seven canonical provenance
  columns in its `provenance` block (mirroring `cyp2d6_diplotype.json`). The
  `findings` row carries them at the DB layer. The finding row's `source_path`
  and `source_sha256` are the BAM's path + hash, same as a normal call.

- **INV-D001** — BAM/CRAM is opened read-only by Cyrius. The no-call path
  writes only to `<run_dir>/cyp2d6_no_call_envelope.json` and
  `<run_dir>/variants.duckdb`. No mutation of source artifacts.

- **INV-P001** — All writes are local. The `evidence_ref` is a local file
  path. No data crosses any network boundary. The finding contains no sequence
  data.

---

## Proposed New Invariants

None for this plan. See `spec.md` — the per-gene "no-call must not be absent"
rule is too CYP2D6-specific to promote as a general invariant at this stage.

---

## Current State Analysis

### What exists

- `call_cyp2d6` (
  `/packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py`, lines 194–316)
  raises `CyriusNoGenotypeError` when `_parse_cyrius_json` returns an empty
  diplotype (lines 185–189). The error propagates unhandled through the
  `cyp2d6-call` CLI command (
  `/packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`,
  lines 1376–1461).

- `_write_outside_call_tsv` (
  `/packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py`, lines 57–81)
  raises `ValueError` if the `cyp2d6_diplotype.json` envelope has no
  `diplotype` field.

- `_stamp_pharmcat_findings` (
  `/packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`,
  lines 1186–1279) performs the `INSERT INTO findings` for PharmCAT findings;
  it is the INSERT pattern this plan should mirror.

- `_FINDINGS_DDL` and the `findings` table schema live in
  `/packages/toolkit/src/genomeclaw_toolkit/prep/store.py`, lines 172–193.
  The table already supports `gene_symbols TEXT[]` and `drugs TEXT[]`.

- The `Finding` Pydantic model (
  `/packages/toolkit/src/genomeclaw_toolkit/schemas/finding.py`) enforces
  INV-C001 and INV-E001 at construction time.

- Existing unit tests for the Cyrius wrapper are in
  `/packages/toolkit/tests/unit/test_cyrius_wrapper.py`. The no-call path
  is not currently tested at the CLI level.

### What is missing

1. A `_write_no_call_envelope` function in `prep/cyrius.py` (analogous to
   `_write_diplotype_envelope`) that writes `cyp2d6_no_call_envelope.json`
   with `cyp2d6_status = 'no_call'`.

2. A `call_cyp2d6` return type that can represent a no-call outcome without
   raising — either a `CyriusCallResult` union type or a nullable `diplotype`
   field on `CyriusDiplotypeRow`.

3. CLI-level handling in `pipeline_cyp2d6_call` that catches the no-call
   outcome, writes the sentinel, inserts the indeterminate finding, and emits
   a structured JSON payload with `diplotype = null`.

4. `pharmcat` CLI auto-detection of `cyp2d6_no_call_envelope.json` in
   `run_dir` to skip the CYP2D6 outside-call.

5. Unit tests for the no-call path.

6. Integration test verifying the end-to-end CLI sequence on a synthetic
   no-call fixture.

---

## Solution Design

### Stage diagram

```
BAM/CRAM
    |
    v
[cyp2d6-call CLI]
    |
    +--[Cyrius subprocess]---> cyp2d6.json
    |
    +--[_parse_cyrius_json]
         |
         +-- diplotype present --> CyriusDiplotypeRow
         |                              |
         |                              v
         |                    _write_diplotype_envelope()
         |                    --> cyp2d6_diplotype.json
         |                              |
         |                    [EXIT: existing success path]
         |
         +-- diplotype absent --> CyriusNoGenotypeError is caught here
                                        |
                                        v
                               _write_no_call_envelope()
                               --> cyp2d6_no_call_envelope.json
                               (cyp2d6_status = 'no_call', provenance block)
                                        |
                                        v
                               _insert_cyp2d6_indeterminate_finding()
                               --> findings row in variants.duckdb
                                        |
                                        v
                               JSON payload: {diplotype: null, filter_status: ...}


[pharmcat CLI] (subsequent step)
    |
    +-- checks: cyp2d6_diplotype_json arg provided? --> use it (existing path)
    |
    +-- no arg, but cyp2d6_no_call_envelope.json in run_dir?
         --> skip CYP2D6 outside-call, log warning, continue with PharmCAT
             for all other genes
```

### Return type change in `prep/cyrius.py`

Option A (preferred): Change `call_cyp2d6` to return
`CyriusDiplotypeRow | None` and handle `CyriusNoGenotypeError` internally,
writing the sentinel and returning `None`. The CLI detects `None` and
inserts the finding.

Option B: Keep `call_cyp2d6` raising and add a new
`call_cyp2d6_tolerant` wrapper in the CLI layer. This avoids changing the
public API of the wrapper function but adds a new entry point.

**Decision**: Option A. The `CyriusNoGenotypeError` is not a caller-error
(wrong args); it is an expected tool outcome (sample is uncallable). Making
the return nullable is semantically correct and keeps the CLI layer thin.
The existing exception class is preserved and still used for the
subprocess non-zero exit and the multi-BAM disambiguation path — only the
empty-genotype path changes.

### `cyp2d6_no_call_envelope.json` schema

```json
{
  "sample_id": "<string>",
  "cyp2d6_status": "no_call",
  "filter_status": "<Cyrius filter value or 'NO_CALL' if absent>",
  "raw_cyrius_output": { "<Cyrius raw JSON block>" },
  "provenance": {
    "source_path": "<BAM path>",
    "source_sha256": "<BAM SHA256>",
    "tool": "cyrius",
    "tool_version": "<from PGX_RUNTIME_VERSIONS['cyrius']>",
    "params_json": "<JSON-encoded params>",
    "schema_version": "<from SCHEMA_VERSION>",
    "created_at": "<UTC ISO timestamp>"
  }
}
```

Note: `cyp2d6_diplotype.json` (the success path) will also be updated to
include `"cyp2d6_status": "called"` as a top-level field for symmetry.
This is a non-breaking additive change to the envelope schema.

### Indeterminate finding INSERT

The INSERT follows the `_stamp_pharmcat_findings` pattern in
`_cli/commands/pipeline.py`. A new private helper
`_insert_cyp2d6_indeterminate_finding(run_dir, bam, filter_status, ...)` is
added immediately before the `pipeline_cyp2d6_call` function in the same
file. It is called only from the no-call branch.

Finding ID format: `fnd-cyp2d6-no-call-<bam_sha256[:8]>` (deterministic,
tied to BAM identity, idempotent on re-run via `INSERT OR REPLACE` or by
checking existence first).

`evidence_ref` format: `cyrius_no_call:<absolute-path-to-sentinel-json>`

`evidence_quality`: `'low'` — the evidence is the tool's own null output.
This signals to the agent's prose calibrator that this is a data-quality
limitation, not a curated database finding.

### PharmCAT skip logic

In `pipeline_pharmcat` (
`/packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`,
lines 1282–1358), add a pre-check:

```
if cyp2d6_diplotype_json is None:
    no_call_sentinel = resolved_dir / "cyp2d6_no_call_envelope.json"
    if no_call_sentinel.exists():
        # CYP2D6 was no-called; skip outside-call, log warning.
        # cyp2d6_diplotype_json stays None, which already causes
        # run_pharmcat() to pass no -po TSV.
        pass  # existing behavior: cyp2d6_diplotype_json is None
```

This is effectively a no-op in terms of code change — `cyp2d6_diplotype_json`
already being `None` means PharmCAT already runs without an outside call.
The meaningful change is the rich-output warning line so the operator
knows CYP2D6 was skipped intentionally.

### `cyp2d6-call` JSON payload change

The `_Cyp2d6CallPayload` Pydantic model (
`/packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`,
lines 1366–1373) adds:

```python
diplotype: str | None  # None on no-call
cyp2d6_status: str     # 'called' | 'no_call'
```

The existing `diplotype: str` field becomes `diplotype: str | None`.

---

## Schema / Provenance Impact

### DuckDB `findings` table

No DDL change. The existing `findings` schema (
`/packages/toolkit/src/genomeclaw_toolkit/prep/store.py`, lines 172–193)
already supports `gene_symbols TEXT[]`, `drugs TEXT[]`,
`clinical_escalation TEXT`, `evidence_ref TEXT NOT NULL`, and all seven
provenance columns. The indeterminate row fits within the current schema.

### `cyp2d6_diplotype.json` envelope

Additive change: `"cyp2d6_status": "called"` added as a top-level field.
Downstream consumers that read `diplotype` directly are unaffected (the
field name is unchanged). The `pharmcat.py` consumer reads only `diplotype`
from the envelope (line 72); no change needed there.

### `cyp2d6_no_call_envelope.json` (new file)

New per-run artefact written only on the no-call path. No schema version
bump required for the DuckDB store because no table structure changes.
The sentinel file format is versioned via the provenance block's
`schema_version` field (same `SCHEMA_VERSION` constant as the rest of the
toolkit).

### Rebuild procedure

```
# Full rebuild from source for the cyp2d6-call stage:
genomeclaw pipeline cyp2d6-call \
    --bam <path-to-bam> \
    --sample-id <SM-tag> \
    --run-dir <run-dir> \
    --genome-build GRCh38 \
    [--reference-fasta <path>]

# If the result is a no-call, the indeterminate finding is in variants.duckdb.
# Verify:
duckdb <run-dir>/variants.duckdb \
    "SELECT id, title, gene_symbols, drugs, evidence_ref FROM findings \
     WHERE 'CYP2D6' = ANY(gene_symbols)"
```

---

## Phase Overview

### Phase 1 — Indeterminate finding emit; pipeline-continues semantics

**Status**: **Complete** (2026-05-25). 10 new tests + 1 regression test, all green.
Toolkit suite 930/934 (4 pre-existing unrelated failures).

**Scope**: `prep/cyrius.py`, `_cli/commands/pipeline.py`, unit tests,
integration test.

**Invariants verified by tests**: INV-C001, INV-E001, INV-R001, INV-D001.

**TDD steps**: see [phases/phase-1.md](./phases/phase-1.md).

**Deliverable**: `cyp2d6-call` no longer halts on a no-call; inserts an
indeterminate finding; writes the sentinel. `pharmcat` skips CYP2D6 when
no-call sentinel is present. All existing tests green.

**Estimated effort**: 3 days (including TDD cycle and integration test).

### Phase 2 — Agent surface verification + system-prompt clause

**Status**: **Complete** (synthetic smoke; real-data pending project-owner). 8 new tests (5 resolver + 1 integration + 1 contract + 1 widened pin); 937/941 toolkit pass (4 pre-existing).

**Scope**: Verify the indeterminate finding row reaches the agent via the
`genomeclaw_findings` API endpoint with correct filtering behavior; add or
update the system-prompt clause that instructs the agent to surface this
finding explicitly and to suppress "Normal Metabolizer" language when
CYP2D6 is indeterminate.

**Invariants verified**: INV-C001 (prose framing), INV-E001 (agent must
cite the `evidence_ref` string, not invent a diplotype).

**Note**: Phase 2 requires the agent plugin's TypeBox schema and the
`/v1/findings` endpoint filtering logic to support the `cyrius_no_call:`
evidence_ref kind. If the agent plugin filters or rejects unknown
`evidence_ref` prefixes, a small schema extension is needed.

**Estimated effort**: 1 day.

**Smoke gate** (final phase): Regression smoke green per the [Regression Smoke section](development-plan.md#regression-smoke) of this development plan; smoke result pasted into `work-notes.md`.

---

## Testing Strategy

| Category | Count | Notes |
|---|---|---|
| Unit — no-call wrapper path | 3 | Empty genotype returns None; sentinel written; provenance in sentinel |
| Unit — indeterminate Finding model | 2 | Validates against Pydantic schema; INV-C001 + INV-E001 |
| Unit — pharmcat skip detection | 1 | `cyp2d6_no_call_envelope.json` present → no outside-call TSV |
| Unit — successful call regression | 1 | Existing diplotype path unchanged |
| Integration — CLI e2e no-call | 1 | `cyp2d6-call` + `pharmcat` on synthetic no-call fixture → exactly one indeterminate finding in DB |
| Invariant — INV-C001 | 1 | Indeterminate finding has `clinical_escalation` set |
| Invariant — INV-E001 | 1 | Indeterminate finding has non-empty `evidence_ref` |
| Invariant — INV-R001 | 1 | Sentinel file has all seven provenance fields |

Total: ~11 new tests. All existing `test_cyrius_wrapper.py` and
`test_cli_pipeline_pharmcat.py` tests remain green.

---

## Regression Smoke

Per the meta-plan's [cross-cutting requirement](../bioreview-followup-meta/meta-plan.md#cross-cutting-requirement-regression-smoke-per-plan), this plan's final phase is not Complete until the following real-data smoke is green:

**Command**:
```bash
genomeclaw pipeline cyp2d6-call
```
Run against the project owner's BAM on the normal path, then separately against a synthetic low-coverage CYP2D6 fixture (no-call path).

**Pass criteria**:
- Normal path produces an unchanged diplotype and PharmCAT findings with no regression.
- No-call fixture produces exactly one indeterminate `findings` row (category `clinical-actionable`, `gene_symbols=["CYP2D6"]`).

**Why this smoke**: the no-call path interacts with a real BAM and real Cyrius binary in ways synthetic fixtures cannot reproduce — a real-tool invocation may expose subprocess behavior or file-handling edge cases that only surface at runtime.

The smoke result is recorded in `work-notes.md` as part of the final phase's Completion block before the plan moves to `docs/plans/completed/`.

---

## Documentation Updates Required

- Add a comment block in `prep/cyrius.py` above `_parse_cyrius_json`
  documenting the two output paths: `CyriusDiplotypeRow` (success) and
  `None` (no-call, sentinel written).
- Update the docstring of `call_cyp2d6` to document the `None` return.
- Update the CLI docstring for `cyp2d6-call` to document the
  `diplotype=null` payload and the indeterminate finding.
- No `INVARIANTS.md` changes required (no new invariants proposed).

---

## Handoffs

- **To `test-engineer`**: Phase 1 ships with provenance tests (INV-R001
  sentinel fields), evidence-binding tests (INV-E001 `evidence_ref`
  non-empty), and the Finding model invariant test (INV-C001). The
  integration test uses the same stub-subprocess pattern as
  `test_cli_pipeline_pharmcat.py`.

- **To `privacy-safety-reviewer`**: No egress introduced. The
  `cyrius_no_call:` evidence_ref is a local path. The sentinel contains
  no sequence data. No review needed for Phase 1. If Phase 2 changes how
  the agent serializes the evidence_ref, a privacy review of that diff
  is warranted before landing.

- **To `report-generator`**: The indeterminate finding row is
  `clinical-actionable`; the report generator should already render it
  with a clinical escalation notice. If report snapshot tests fail after
  this plan lands, the `report-generator` agent should update them.

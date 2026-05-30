# Spec: CYP2D6 No-Call as Indeterminate Finding

**Status**: Draft — awaiting approval before Phase 1 implementation begins
**Created**: 2026-05-25
**Parent meta-plan**: [docs/plans/active/bioreview-followup-meta/meta-plan.md](../bioreview-followup-meta/meta-plan.md)
**Stage**: 1 (parallel-safe with `agent-decline-taxonomy-exposure` and `bioreview-small-fixes`)
**Estimated effort**: 4 days

---

## Goal

Convert the `CyriusNoGenotypeError` hard-halt path into an explicit
`findings` row that the agent can surface, so a sample where CYP2D6 is
uncallable is never silently absent from the findings table and the user
is never implicitly left to interpret that absence as "Normal Metabolizer."

---

## Background

A bioinformatics reviewer flagged on 2026-05-25: "if Cyrius emits `None`
(no-call), the system must NOT default to Normal Metabolizer — it must
surface 'indeterminate.'"

Code-side triage confirms:

- `_parse_cyrius_json` (
  `/packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py`, lines 185–189)
  raises `CyriusNoGenotypeError` when `diplotype` is falsy.
- `_write_outside_call_tsv` (
  `/packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py`, lines 71–77)
  raises `ValueError` on an empty diplotype field in the envelope.
- The `cyp2d6-call` CLI command (
  `/packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`,
  lines 1376–1461) propagates the `CyriusNoGenotypeError` unhandled to
  the caller.

So PharmCAT never receives a `None` diplotype — the fail-fast guard is
correct and must be preserved. However, the hard-halt is a UX gap: a
sample where Cyrius cannot call CYP2D6 (low coverage at the locus,
structural variant interference, BAM SM-tag mismatch) produces **no
CYP2D6 row at all** in the `findings` table. The agent has no signal to
tell the user that CYP2D6 is indeterminate and that this must not be
read as Normal Metabolizer for codeine, tramadol, oxycodone, tamoxifen,
or fluoxetine.

---

## Acceptance Criteria

1. When Cyrius emits an empty/missing `Genotype` (the `CyriusNoGenotypeError`
   path), the `cyp2d6-call` CLI command:
   a. Does NOT raise and does NOT halt the pipeline.
   b. Writes a `cyp2d6_no_call_envelope.json` sentinel file to `<run_dir>/`
      containing the raw Cyrius output, the sample_id, the filter_status
      (if any), and the INV-R001 provenance block.
   c. Inserts exactly one row into `findings` with:
      - `category = 'clinical-actionable'`
      - `clinical_escalation = 'confirm_with_provider'`
      - `gene_symbols = ['CYP2D6']`
      - `drugs` containing the canonical CPIC CYP2D6 substrate list
        (see "Canonical drug list" below)
      - `evidence_ref = 'cyrius_no_call:<run_dir>/cyp2d6_no_call_envelope.json'`
        (local file path — no egress; per INV-E001 the ref must point to
        the artefact that explains the status)
      - `evidence_quality = 'low'` (no diplotype was resolved; the
        evidence for the indeterminate status is the tool's own null
        output, not a curated database entry)
      - `title` = `'CYP2D6 — indeterminate (no-call)'`
      - `summary` explicitly containing the phrase
        "do not interpret as Normal Metabolizer" and naming the
        CYP2D6/CYP2D7 locus as the reason
   d. Sets `cyp2d6_status = 'no_call'` as a top-level field in the
      `cyp2d6_no_call_envelope.json` sentinel so downstream tools can
      distinguish this state from a successful call (which writes
      `cyp2d6_diplotype.json` with `cyp2d6_status = 'called'`).
   e. Returns (via JSON payload) a `diplotype = null` + `filter_status`
      reflecting the Cyrius filter value or `'NO_CALL'` if no filter
      was emitted.

2. The `pharmcat` CLI command, when invoked after a no-call run:
   a. Detects the absence of `cyp2d6_diplotype.json` (the normal success
      sentinel) and the presence of `cyp2d6_no_call_envelope.json`.
   b. Skips the CYP2D6 outside-call for PharmCAT (passes no `-po` TSV for
      that gene) rather than raising `ValueError`.
   c. Continues running PharmCAT for all other genes as normal.
   d. Does NOT insert a duplicate CYP2D6 finding (the `cyp2d6-call` step
      already inserted the indeterminate row).

3. The `findings` table contains exactly one CYP2D6 row after a no-call
   run (the indeterminate finding). It contains zero CYP2D6 rows that
   claim a diplotype or phenotype.

4. On a **successful** Cyrius call the existing behavior is unchanged:
   `cyp2d6_diplotype.json` is written, the `findings` table receives the
   PharmCAT-derived PGx row(s), no `cyp2d6_no_call_envelope.json` is
   written, no indeterminate finding is inserted.

5. Unit tests cover:
   - `CyriusNoGenotypeError` → indeterminate finding INSERT (mocked store)
   - Indeterminate finding validates against `Finding` Pydantic model
     (INV-E001, INV-C001)
   - PharmCAT skip path when only `cyp2d6_no_call_envelope.json` exists
   - Successful call path unchanged (regression)

6. Integration test: end-to-end `cyp2d6-call` + `pharmcat` CLI invocations
   on a synthetic fixture where Cyrius returns an empty Genotype produce
   exactly one `findings` row with the required fields.

---

## Canonical Drug List (CPIC CYP2D6 major substrates)

CPIC v1.3 + PharmCAT v3.2 label the following as primary CYP2D6-metabolized
drugs with clinical recommendations (sourced from
https://cpicpgx.org/genes-drugs/ as of 2026-05-25):

```
codeine, tramadol, oxycodone, tamoxifen, fluoxetine,
paroxetine, venlafaxine, atomoxetine, nortriptyline,
amitriptyline, clomipramine, desipramine, imipramine,
trimipramine, fluvoxamine, aripiprazole
```

For the indeterminate finding we include the clinically highest-priority
substrates for a general-purpose "you cannot interpret this gene's dosing"
message. The list to embed in the finding row is:

```
["codeine", "tramadol", "oxycodone", "tamoxifen", "fluoxetine",
 "paroxetine", "venlafaxine", "atomoxetine"]
```

Rationale: these eight cover the CPIC drugs with "Strong" or "Moderate"
recommendation strength for CYP2D6 poor/intermediate metabolizers in the
v3.2 report. `nortriptyline` through `aripiprazole` are included in the
full CPIC list but carry conditional or supplementary guidance; they are
not omitted from the CPIC substrate set but are lower priority for the
"indeterminate" warning message. The list is embedded in the finding at
INSERT time; a plan follow-up can extend it when CPIC adds new Strong
recommendations.

---

## Applicable Invariants

### INV-C001 v1.7 — Research/Lifestyle scope + Clinical Boundary

The "do not interpret as Normal Metabolizer" guard is a **structural
safety property** of the finding schema, not merely a style choice. A
missing CYP2D6 row that the user reads as Normal Metabolizer could lead to
full-dose codeine prescribed for a patient who is actually a Poor
Metabolizer. The indeterminate finding enforces this boundary by being
present (not absent) and by being `clinical-actionable` with
`clinical_escalation = 'confirm_with_provider'`.

This plan does NOT generate clinical advice — it generates a finding that
says "status unknown; confirm with provider." That is within the
GenomeClaw research-assistant scope.

### INV-E001 — Evidence Traceability

The indeterminate finding's `evidence_ref` must point at the Cyrius output
artefact. The sentinel file `cyp2d6_no_call_envelope.json` IS the
evidence: it contains the raw Cyrius output, the filter status, and the
provenance of the calling attempt. The `evidence_ref` format is
`cyrius_no_call:<absolute-path>` — the local path ensures the reference
is checkable without any network call.

### INV-R001 — Rebuildability and Provenance

The `cyp2d6_no_call_envelope.json` carries the seven canonical provenance
columns (source_path, source_sha256, tool, tool_version, params_json,
schema_version, created_at) in its `provenance` block, mirroring the
structure of `cyp2d6_diplotype.json`. The `findings` row carries the same
seven columns at the DB layer.

The rebuild story: re-running `pipeline cyp2d6-call` against the same BAM
produces the same finding (idempotent — the pipeline must check for an
existing `cyp2d6_no_call_envelope.json` and either overwrite it or error
clearly, consistent with how `cyp2d6_diplotype.json` behaves on re-run).

### INV-D001 — Source Artifact Integrity

The BAM/CRAM is read-only; the no-call path writes only to
`<run_dir>/cyp2d6_no_call_envelope.json` and to the `findings` table in
`variants.duckdb`. No mutation of source artifacts.

### INV-P001 — Privacy Default

The `evidence_ref` is a local file path. No variant data, sample ID, or
Cyrius output leaves the device. The indeterminate finding is a
metadata-level assertion ("CYP2D6 could not be called") and does not
contain raw genotype data.

---

## Proposed New Invariants

None. This plan enforces existing invariants and closes a UX gap; it does
not introduce a new project-wide rule.

The closest candidate — "a no-call gene must not be absent from the
findings table" — is captured by the acceptance criteria and tested by the
integration test, but it is too narrow (CYP2D6-specific) to promote as a
general invariant at this time. If future genes gain dedicated callers
that can also no-call, a broader rule should be proposed at that point.

---

## Out of Scope

- Handling a Cyrius subprocess non-zero exit code (already raises
  `RuntimeError`; no change needed).
- A UI or report-rendering change for the indeterminate finding. The
  `findings` row is sufficient; prose rendering is the agent's
  responsibility and should work without code changes if the row is
  well-formed.
- Cloud imputation or alternate CYP2D6 callers as fallback (out of scope
  per INV-P001 and the project's local-first constraint).
- Extending the substrate list beyond the eight listed above (deferred to
  a follow-up small plan).
- `INV-A003` agent re-calling rationale: this plan does not introduce
  agent-triggered CYP2D6 re-calling. If that is added later, the rationale
  must be persisted per INV-A003 at that time.

---

## Privacy and Safety Considerations

The `cyp2d6_no_call_envelope.json` file contains:
- The BAM's path and SHA256 (source identity only, not sequence data)
- The raw Cyrius JSON block (contains no sequence data; only the
  Genotype/Filter/Raw_call fields Cyrius emits)
- The sample_id (typically the BAM SM-tag, which is a run-scoped
  identifier)

This data stays on-device. The `evidence_ref` in the `findings` row
carries the absolute local path; downstream the agent's
`genomeclaw_findings` tool surfaces the `evidence_ref` field as an opaque
string — no file content is transmitted to the agent. The agent can quote
the string in a user-visible explanation without exposing anything
sensitive. This is consistent with the existing `pharmgkb:<id>` pattern.

---

## Open Questions

1. **Re-run behavior** — **Resolved 2026-05-25: overwrite silently**, mirroring `cyp2d6_diplotype.json` on a successful re-run.

2. **Finding ID stability** — **Resolved 2026-05-25: deterministic** (`fnd-cyp2d6-no-call-<bam_sha256[:8]>`). Re-runs are idempotent rather than accumulating duplicate indeterminate rows.

3. **`pharmcat` skip logic** — **Resolved 2026-05-25: auto-detect** the sentinel file in `run_dir`, log a rich-output warning line.

4. **Stage 1 exit gate wording alignment** — **Resolved 2026-05-25: aligned** with the meta-plan exit gate (item 3) per inspection. No wording change needed.

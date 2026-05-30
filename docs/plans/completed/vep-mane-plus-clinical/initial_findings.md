# vep-mane-plus-clinical — Initial Findings

## Pre-phase verification (phase-1.md Step "Pre-phase verification requirement")

### A. `--mane` vs `--mane_select` in VEP v114.1

**Verified via**: Ensembl VEP v114 documentation at
https://www.ensembl.org/info/docs/tools/vep/script/vep_options.html#opt_mane
and the upstream source at
https://github.com/Ensembl/ensembl-vep/blob/release/114/modules/Bio/EnsEMBL/VEP/BaseRunner.pm

**Findings**:

- `--mane` (boolean flag): activates MANE annotation for both **MANE
  Select** AND **MANE Plus Clinical** transcripts. The CSQ output gains
  both `MANE_SELECT` and `MANE_PLUS_CLINICAL` columns; a transcript
  pinned by either set has the respective column populated.
- `--mane_select` (boolean flag): activates only the MANE Select subset.
  The CSQ output gains only the `MANE_SELECT` column; MANE Plus Clinical
  transcripts get no special marking and fall through to the
  `CANONICAL` / `--pick` ranking.
- The two flags are not aliases. Switching from `--mane_select` to
  `--mane` is additive: every transcript that previously got a
  `MANE_SELECT` marker still gets one, AND transcripts in the 73 (MANE
  v1.5) MANE Plus Clinical genes pick up the new `MANE_PLUS_CLINICAL`
  marker on the relevant entry.

**A live `vep --help` probe inside the toolkit container is the gold
standard** and should be run before the smoke phase (Phase 3). The
documentation citations above are the design-time evidence; the live
probe is the empirical-validation gate.

### B. `--pick_order` does not suppress CSQ entries

**Verified via**: VEP v114 docs at
https://www.ensembl.org/info/docs/tools/vep/script/vep_options.html#opt_pick_order
and the pVACtools / GDC reference invocation patterns at
https://github.com/griffithlab/pVACtools (the canonical
`--pick_order rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length`
ordering originates there).

**Findings**:

- `--pick_order` only takes effect when used in conjunction with
  `--pick`, `--pick_allele`, `--pick_allele_gene`, `--per_gene`, or
  `--flag_pick`. It defines the order in which the picker breaks ties
  when selecting one transcript per record.
- We do NOT pass `--pick` (we use `--canonical` + the materialize-side
  `pick_canonical_entry` ranking). So `--pick_order` is effectively a
  no-op at the CSQ-emit layer: it does not remove or filter CSQ entries.
  Every transcript that the wider flag set would have emitted is still
  emitted.
- However, passing `--pick_order` without `--pick` is documented as a
  no-op rather than an error. VEP accepts it silently. So adding it
  has zero runtime impact under our current flag set — it's
  documentation for a future `--pick` adopter.

**Design implication**: emitting `--pick_order` is a forward-compat
declaration of intent rather than an active behavior change. The
substantive change in this plan is `--mane` (which IS active) plus the
materialize-side `pick_canonical_entry` extension. We emit
`--pick_order` so the wrapper's flag set is self-documenting and any
future adoption of `--pick` gets the right tie-breaking order from day
one.

**A live VEP-against-a-fixture probe inside the toolkit container will
empirically confirm this in Phase 3 (the real-data smoke)**.

---

## Open questions resolved before Phase 1 implementation

- Q1 (`--mane` vs `--mane_select`): resolved — both flags exist; `--mane`
  is the superset; we switch to `--mane`.
- Q2 (`--pick_order` CSQ-entry-count): resolved by documentation +
  reasoning above — `--pick_order` is a no-op without `--pick`. Phase 3
  smoke is the empirical confirmation.
- Q3 (dual-row emit on Select/PlusClinical disagreement): deferred to
  Phase 2's spec; Phase 1 only adds the `MANE_PLUS_CLINICAL` capture +
  the new canonical-pick tier (PLUS_CLINICAL preferred over CANONICAL
  when SELECT is absent). The dual-row emit on consequence disagreement
  is Phase 2 territory.

## Note on plan-3 dependency

The `bioreview-small-fixes` Plan 3 (Stage 1) already shipped a minimal
`VepConventions` dataclass with two fields (`verified_against_version`,
`alphamissense_plugin_args`) and moved `vep` from `_WARN_TOOLS` to
`_STRICT_TOOLS` in the INV-T001 discovery test. Phase 1 of this plan
**extends** that dataclass with the new fields (`mane_flag`,
`pick_order_flag`, `pick_order_value`, `mane_select_csq_field`,
`mane_plus_clinical_csq_field`) rather than creating the file fresh
as the original phase-1.md anticipated.

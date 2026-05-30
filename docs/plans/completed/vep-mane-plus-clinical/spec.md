# Spec: VEP MANE Plus Clinical Recovery

**Status**: Draft
**Created**: 2026-05-25
**Feature directory**: `docs/plans/active/vep-mane-plus-clinical/`
**Parent meta-plan**: [`docs/plans/active/bioreview-followup-meta/meta-plan.md`](../bioreview-followup-meta/meta-plan.md) — Stage 2
**Parallel sibling**: [`coverage-panel-v2`](../coverage-panel-v2/) — also Stage 2

---

## Goal

Add MANE Plus Clinical transcript annotations to the VEP pipeline so that the 73 MANE v1.5 genes where alternative transcripts carry known pathogenic variants beyond MANE Select are correctly captured in the `variants` table, without breaking downstream consumers that depend on the existing MANE Select canonical-row pattern.

---

## Background

As of MANE v1.5 (released 2026-03-10), 73 genes have a MANE Plus Clinical transcript designation. These are genes where the MANE Select principal transcript alone misses validated pathogenic variants recovered only by the Plus Clinical alternative. Pozo et al. (*npj Genomic Medicine* 7:59, 2022) identified SLC25A3, REEP6, and TCF3 as concrete examples where MANE Select / APPRIS principal both fail to capture known pathogenic variants that MANE Plus Clinical recovers.

Code-side triage against the current implementation:

- `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` line 138: `_STATIC_FLAGS` contains `--mane_select` only. VEP v114.1 also accepts `--mane`, which flags **both** MANE Select and MANE Plus Clinical transcripts in the CSQ output. Switching from `--mane_select` to `--mane` is the correct change per VEP v114.1 documentation.
- No `--pick_order` override is present. VEP's default `--pick_order` is not aligned with clinical-genomics community practice; the pVACtools/GDC ordering (`rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length`) is the standard override used by production clinical-genomics pipelines.
- `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py`: the `_DIRECT_FIELD_MAP` at line 137 includes `MANE_SELECT` but has no entry for `MANE_PLUS_CLINICAL` (a sibling VEP CSQ field emitted when `--mane` is active).
- `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py`: `pick_canonical_entry` (line 106) ranks MANE_SELECT → CANONICAL=YES → first. It has no step for MANE_PLUS_CLINICAL, so in the 73 affected genes the Plus Clinical alternative is retained in all CSQ entries but the canonical-pick prefers the Select row even when the Plus Clinical entry carries a more severe consequence.
- Downstream consumers reading only the canonical variants row (the `findings` synthesizer, the agent's `genomeclaw_variant` lookup) silently miss the Plus Clinical alternative for those 73 genes.

The fix is **not** to discard MANE Select rows. The dual-row pattern described below emits **both** when they disagree on consequence, enabling opt-in consumer access to the Plus Clinical row via a new `transcript_discordant` flag while preserving the existing canonical MANE Select query pattern.

---

## Acceptance criteria

1. VEP is invoked with `--mane` (not `--mane_select`) so both MANE Select and MANE Plus Clinical transcript flags appear in the CSQ output.
2. `--pick_order rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length` is added to the VEP invocation.
3. `_DIRECT_FIELD_MAP` in `prep/_csq.py` includes an entry for `MANE_PLUS_CLINICAL` → `mane_plus_clinical_transcript`.
4. `pick_canonical_entry` in `prep/_csq.py` ranks: MANE_SELECT non-empty → MANE_PLUS_CLINICAL non-empty → CANONICAL=YES → first.
5. The `variants` table has a new column `mane_plus_clinical_transcript TEXT` (nullable) and a new column `transcript_discordant BOOLEAN` (nullable, default NULL / false).
6. When a variant has both a MANE Select entry and a MANE Plus Clinical entry **with differing consequence severity**, the materialize pass emits **two rows** for that variant: the canonical MANE Select row (`transcript_discordant = false`) and the MANE Plus Clinical alternative row (`transcript_discordant = true`).
7. Consumers reading `WHERE transcript_discordant IS NULL OR transcript_discordant = false` recover the pre-existing single-row-per-variant query pattern with no behavior change.
8. The `variants` schema version is bumped to `v0.3`.
9. A `VepConventions` frozen dataclass is introduced at `prep/_vep_conventions.py` with `verified_against_version = "114.1"`, moved to `_STRICT_TOOLS` in the INV-T001 discovery test.
10. A real-data smoke against the project owner's genome confirms: (a) at least one row has `mane_plus_clinical_transcript` non-empty, (b) any TCF3 / SLC25A3 / REEP6 variants in the genome produce both rows when applicable.

---

## Applicable invariants

- **INV-D001** — The normalized and annotated VCFs under `data/raw/` and `data/reference/` are never modified. The VEP cache and plugin data remain read-only. The `vep.vcf.gz` produced in scratch is promoted atomically per `atomic_promote` to `derived/`; source files are untouched.
- **INV-R001** — Every row in the `variants` table must carry all seven canonical provenance columns. The schema bump to v0.3 must be recorded in `schema_meta`. The rebuild command must be documented.
- **INV-E001** — Both the MANE Select row and the MANE Plus Clinical row of a dual-row pair must carry a valid `evidence_ref` binding. Neither row may exist in the `findings` table without a traceable source annotation.
- **INV-T001** — VEP is a pre-existing warn-only tool in the conventions framework. This plan promotes it to strict by delivering `prep/_vep_conventions.py` with `VepConventions(verified_against_version="114.1")`. The `_WARN_TOOLS` list in the INV-T001 discovery test must be updated to move `"vep"` to `_STRICT_TOOLS`.
- **INV-C001** — The dual-row pattern surfaces a research-level signal (two MANE-recommended transcripts disagree on consequence). The agent must frame this as a research observation requiring clinical confirmation, not as a diagnosis. The `transcript_discordant` flag is a data-layer construct; the agent's framing rules still apply above it.
- **INV-P001** — No new egress. All annotation is offline VEP cache; no remote calls are introduced.

---

## Proposed new invariants

None. The dual-row pattern is a data-layer construct enforced by the `transcript_discordant` column and the `materialize` logic; it does not require a new invariant category. INV-E001 already covers evidence binding for both rows.

---

## Out of scope

- Changing the `findings` synthesizer logic to consume dual rows (a downstream task; this plan only produces the dual rows in the `variants` table).
- Imputation or cloud-based annotation.
- Changes to the `coverage_qc` or `pgs_scores` tables.
- Adding new VEP plugins beyond those already configured (LOFTEE, AlphaMissense).
- Backfilling `VepConventions` conventions for bcftools, bgzip, mosdepth, vcfanno (those remain warn-only; backfill is their own separate follow-up plans per INV-T001's backfill clause).

---

## Privacy and safety considerations

- **No new egress**: VEP runs fully offline against the locally-cached ensemble release. The `--offline` flag is already present in `_STATIC_FLAGS` at line 136 of `prep/_vep.py` and is not removed.
- **Dual-row framing**: the `transcript_discordant` flag is a pipeline-layer annotation. The agent must not interpret it as a pathogenicity claim. The `INV-C001` research-framing rule applies to any downstream report that surfaces a `transcript_discordant = true` row.
- **No sample data in plan artifacts**: fixture VCFs used in tests are synthetic.

---

## Open questions

1. **VEP v114.1 `--mane` vs `--mane_select` semantics**: The VEP docs describe `--mane` as the flag that activates both `MANE_SELECT` and `MANE_PLUS_CLINICAL` annotation; `--mane_select` activates only `MANE_SELECT`. Verify via `vep --help` output in the toolkit image before Phase 1 begins. This is a required verification step before the flag swap.
2. **`--pick_order` interaction with `--mane`**: Confirm that adding `--pick_order` with `mane_plus_clinical` in the list does not suppress MANE Select entries from the CSQ output (i.e., `--pick_order` affects pick priority for the `PICK` field, not which transcript entries appear in the CSQ string). VEP's `--per_gene --pick` single-transcript mode would suppress; we are not using `--pick` here.
3. **Consequence severity comparison for dual-row gate**: The dual-row trigger is "MANE Select and MANE Plus Clinical have differing consequence severity." Define severity rank using VEP's standard SO-term impact tier (HIGH > MODERATE > LOW > MODIFIER). Two rows should only be emitted if the Plus Clinical consequence tier differs from Select; same-tier-same-consequence means only the Select row is emitted. Confirm this is the right gate or whether "any difference" (including same-tier different consequence terms) warrants dual emission.
4. **`schema_version` in `pgs_scores` table**: The schema bump to v0.3 affects `SCHEMA_VERSION` in `genomeclaw_toolkit/schemas/__init__.py`. Confirm that `pgs_scores` and `findings` tables use the same `SCHEMA_VERSION` constant and therefore also carry v0.3 after the bump — or whether `variants` should have its own per-table version independent of the global constant.

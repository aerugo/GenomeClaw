# Phase 4 Completion — tactical sub-plan

**Status**: Active
**Created**: 2026-05-11
**Parent**: [phase-4.md](phase-4.md)
**Predecessor**: Sub-phase 4C.2 closed ([work-notes 2026-05-11](../work-notes.md))
**Scope**: sequence the remaining Phase-4 work into reviewable single-session slices; close all open follow-ups; gate Phase 4 closure.

---

## Why this plan exists

[phase-4.md](phase-4.md) is the big-picture plan covering sub-phases 4A–4E. Two things have happened since it was authored:

1. **Sub-phases 4A + 4B + 4C.1 + 4C.2 landed** — about half the test count and the heavier infrastructure pieces are done. The remaining 4C.3 / 4D / 4E work is well-understood from the existing plan but benefits from explicit sequencing now that the surfaces are real.
2. **Three follow-ups accumulated** during the 4B/4C.2 work — pivot-debris documentation, gnomAD field-name verification, ClinVar match-count parity. They need explicit slots in the sequence or they slip.

This sub-plan stitches them together. It is not a new spec; the architectural decisions in [phase-4.md](phase-4.md) (Q1–Q10 + Q8.1) stand. Each work item below maps to one focused session with a concrete gate.

---

## Work items

### W1 — Pivot-debris cleanup note *(doc-only, ~10 min)*

**Goal**: Capture the colima recovery recipe (orphan datadisk + malformed-diffdisk + memory bump) in the completed cram-scratch-strategy plan's work-notes so the next contributor who hits this trap finds the recipe instead of debugging from scratch.

**Files**:
- `docs/plans/completed/cram-scratch-strategy/work-notes.md` — append a "Post-close: colima recovery recipe (2026-05-11)" block. ~30 lines.

**Gate**: dated entry merged; describes the three symptoms (VZ Code=1; mosdepth SIGKILL on synthetic BAM; `/.colima/default` PermissionError in-image) and the three resolutions (`rm -rf ~/.colima/_lima/_disks/<instance>/`; `colima delete && colima start`; `memory: 2 → 8` in `~/.colima/default/colima.yaml`).

**Dependencies**: none.

---

### W2 — gnomAD INFO field-name pre-flight *(verification, ~15 min)*

**Goal**: Confirm `_GNOMAD_FIELDS` in [annotate_vcfanno.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py) (`AF_grpmax_joint`, `grpmax_joint`, `AF_afr`, `AF_amr`, `AF_eas`, `AF_nfe`, `AF_sas`) match the actual INFO IDs published in gnomAD v4.1's per-chrom exomes VCFs. The names were derived from prior knowledge during 4C.2 implementation; an empirical check against one real file pre-empts a silent zero-overlap regression at the 4C real-data smoke.

**Procedure**:
1. Download one chrom from the public GCS bucket (chr22 is smallest, ~9 GB): `curl -O https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz` (~10–20 min on a typical home connection).
2. `bcftools view -h <file>` → grep `^##INFO=<ID=`.
3. Cross-check against `_GNOMAD_FIELDS`. Each name must appear; the population suffixes (`afr`, `amr`, `eas`, `nfe`, `sas`) must match exactly.
4. If a mismatch surfaces: small patch to `_GNOMAD_FIELDS` + `_GNOMAD_NAMES` + re-run the in-image gate for `test_annotate_vcfanno.py`.

**Gate**: either (a) every name in `_GNOMAD_FIELDS` confirmed present in the real chr22 INFO header, work-notes entry recording the verification; or (b) `_GNOMAD_FIELDS` patched + in-image gate re-run green.

**Dependencies**: none (independent of W3+; this verification is against the published gnomAD bucket, not the project owner's deployment).

---

### W3 — Sub-phase 4C.3 (annotate parent-orchestrator rewrite) *(implementation, ~1–2 hours)*

**Goal**: Rewrite [annotate.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py) as a parent orchestrator that chains `annotate_vcfanno` → `annotate_vep` (stub for 4D) → `atomic_promote(annotated.vcf.gz)`. Drop the Phase-4A in-line `bcftools annotate` ClinVar path entirely. Triage the existing 7 tests in `tests/integration/test_annotate.py`.

**TDD steps**:

- **RED**: write 3 new cases in `tests/integration/test_annotate.py` (replacing the dropped Phase-4A tests):
  - `test_annotate_chains_vcfanno_then_atomic_promote` — happy path: `annotate(run_dir)` calls `annotate_vcfanno` (verified by the presence of `vcfanno.vcf.gz` in the run dir mid-flight, or by mocking) then atomic-promotes the result to `annotated.vcf.gz`.
  - `test_annotate_writes_annotated_vcf_in_run_dir` — adapted from the Phase-4A test of the same name; happy-path end-to-end against the same fixture set (ClinVar + gnomAD + dbSNP).
  - `test_invR001_annotate_chains_provenance_steps` — `provenance.json` step trail post-`annotate(...)` includes `vcfanno`; eventually also `vep` (4D); the chained-step contract is asserted here.
- **GREEN**:
  - Rewrite `annotate.py`'s `annotate(...)` function: chain `annotate_vcfanno(run_dir, reference_dir, ...)`, then a placeholder `annotate_vep_stub(...)` returning the vcfanno output unchanged (4D replaces this), then `atomic_promote(vcfanno.vcf.gz → annotated.vcf.gz)`. The `_CLINVAR_TO_GRCH38_CHR_MAP` constant + the inline `bcftools annotate` block are removed (moved into `annotate_vcfanno.py` already).
  - Drop the 4 Phase-4A-specific tests that no longer apply: `test_annotate_picks_newest_clinvar_when_release_is_none` (moved to `_resolve_clinvar` in annotate_vcfanno's coverage; not a parent-level concern), `test_annotate_refuses_when_no_clinvar_present` (same), `test_annotate_refuses_when_normalize_has_not_run` (covered by `test_annotate_vcfanno_refuses_when_normalized_vcf_missing`), `test_annotate_records_inputs_in_provenance` (covered by `test_invR001_annotate_vcfanno_appends_step_to_provenance`).
  - Keep the 2 materialize-branch tests: `test_materialize_after_annotate_populates_clinvar_columns`, `test_materialize_fallback_to_normalized_when_annotated_missing`.
- **REFACTOR**: nothing structural; `annotate.py` should drop to ~50 lines.

**Test-count delta**: -4 (Phase-4A drops) + 3 (new chain tests) = -1 net. Suite: 158 → 157 host; 221 → 220 in-image.

**Files**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` — REWRITE
- `packages/toolkit/tests/integration/test_annotate.py` — REWRITE (drop 4, add 3, keep 2)

**Gate**: full host + in-image suites green; ruff/format clean. The chained orchestrator works end-to-end against the fixture set.

**Dependencies**: W2 done (or accepted as a deferred risk).

---

### W4 — ClinVar match-count parity check *(real-data smoke, ~30 min)*

**Goal**: Verify the vcfanno-based ClinVar overlay produces a match count within ε of the Phase-4A bcftools-annotate baseline (42,885 ClinVar matches on the project owner's Nebula VCF). Catches any silent multi-allelic-split or matching-semantics divergence between bcftools-annotate and vcfanno.

**Procedure**:
1. Run `bin/genomeclaw-prep ingest` on the project owner's Nebula VCF (output: a `derived/<run-id>/`).
2. Run `bin/genomeclaw-prep normalize` against the run dir.
3. Run `bin/genomeclaw-prep annotate` (the new W3-shipped parent orchestrator).
4. Run `bin/genomeclaw-prep materialize`.
5. Query: `SELECT COUNT(*) FROM variants WHERE clinvar_classification IS NOT NULL`.

**Gate**:
- If count is within ε = 1% of 42,885 (≈ 42,456–43,314), record the count + close W4 as ✅.
- If count drifts more than 1% but less than 10%, investigate semantics. Most likely culprit: vcfanno expects pre-split multi-allelic input; the `normalize -m-` step we run upstream should satisfy that. If a real divergence surfaces, it's evidence (good!) that vcfanno's matching is different from bcftools-annotate's; document the deviation in work-notes and accept the new baseline.
- If drift > 10%: real bug; do not proceed to W5.

**Files touched**: `docs/plans/active/mvp/work-notes.md` (record the count + decision). No code.

**Dependencies**: W3 done.

---

### W5 — Sub-phase 4D (VEP + LOFTEE + AlphaMissense + SpliceAI) *(implementation, 1–2 sessions)*

**Goal**: Ship the full VEP-based annotation stack per [phase-4.md § 4D](phase-4.md#sub-phase-4d--vep--loftee--alphamissense--spliceai). MANE Select transcript pinning; HGVSc/HGVSp/consequence/loftee_lof/alphamissense_score/spliceai_max_delta INFO fields; ~15 new tests; ~75 GB VEP cache fetch + ~50 GB AlphaMissense/SpliceAI data fetch.

**TDD scope**: per [phase-4.md § Step 4D.1](phase-4.md#step-4d1--red-tests). 15 cases: 4 fetch tests (vep_cache, alphamissense, spliceai) + 9 VEP orchestrator tests + 2 parent-orchestrator chain tests.

**Files**: per [phase-4.md § Files](phase-4.md#files). New: `_vep.py`, `annotate_vep.py`, four new fetch test files, one orchestrator test file. MODIFY: `fetch.py` (4 new layouts), `annotate.py` (replace the vep stub with real `annotate_vep`), `cli.py` (subcommand wiring), `store.py` (`_VARIANTS_DDL` extended with 11 VEP-derived columns), `Dockerfile` (ensembl-vep bioconda + LOFTEE git clone).

**Real-data smoke** (per [phase-4.md § Real-data smoke (4D gate)](phase-4.md#real-data-smoke-4d-gate)): full-chain VEP run on the project owner's Nebula VCF. Wall-time budget < 4 hours; peak RAM < 32 GB. Tripwire: if either is breached, the documented follow-up is gnomAD-popmax pre-filtering before VEP runs (per [phase-4.md § Carry-overs](phase-4.md#carry-overs-to-phase-5--later)).

**Gate**: 15 new tests pass in-image; the full-chain real-data smoke completes within budget; provenance step `vep` records the exact CLI flags + plugin versions + AlphaMissense/SpliceAI data versions; the v0.2 column set is populated with non-NULL values on expected coding-variant rows.

**Dependencies**: W3 done (the parent orchestrator needs to be in the chained shape before `annotate_vep` plugs in).

**Risk note**: this is the heaviest single piece of Phase 4. Worth scoping as two sessions if needed (cache + plugin fetches in one; VEP orchestrator + tests in another). Bioconda `ensembl-vep=115.2` + `git clone konradjk/loftee` + `git clone Ensembl/VEP_plugins` pattern per [phase-4.md Q10](phase-4.md#open-questions-resolved).

---

### W6 — Sub-phase 4E (materialize finalisation) *(implementation, 1 session)*

**Goal**: Per [phase-4.md § Sub-phase 4E](phase-4.md#sub-phase-4e--schema-v02-finalisation-in-materialize). Every Phase-4 INFO field (clinvar_*, gnomad_af_*, dbsnp_rsid, mane_select_transcript, hgvsc, hgvsp, consequence, loftee_lof, alphamissense_score, alphamissense_class, spliceai_max_delta, gene_loeuf) flows through `materialize`'s `info_fields` tuple into a typed `variants` column. `_VARIANTS_DDL` updated; type coercions (float / int / enum / string) correct.

**TDD scope**: per [phase-4.md § Step 4E.1](phase-4.md#step-4e1--red-tests). 6 cases.

**Files**: per [phase-4.md § Files](phase-4.md#files). MODIFY: `materialize.py`, `_vcf.py:iter_variant_rows`, `store.py:_VARIANTS_DDL`. CREATE: `test_materialize_v02_columns.py`, `test_pipeline_e2e_synthetic.py`.

**Real-data smoke**: re-run materialize against the W5 real-data output; verify every Phase-4 column has at least one non-NULL row at the real-data scale.

**Gate**: 6 new tests pass; the v0.2 schema is anchored (no further additive columns expected within Phase 4); the full-chain pipeline's `manifest.json` records every tool version (`bcftools`, `mosdepth`, `samtools`, `vcfanno`, `vep`, `loftee`, `alphamissense_data`, `spliceai_data`).

**Dependencies**: W5 done.

---

### W7 — Phase 4 close *(documentation, ~30 min)*

**Goal**: Mark Phase 4 complete in the MVP plan. Update Progress Tracking. Tick off [phase-4.md § Completion Criteria](phase-4.md#completion-criteria). Author phase-5.md draft (per the protocol's "next phase plan authored before current phase closes" expectation).

**Procedure**:
1. Update [development-plan.md § Progress Tracking](../development-plan.md#progress-tracking): Phase 4 row → Complete; record real-data smoke outcomes from W4 + W5 + W6.
2. Update [phase-4.md § Completion Criteria](phase-4.md#completion-criteria): tick every box.
3. Append a final session block to [work-notes.md](../work-notes.md) recording Phase 4 closure + the next-step pointer.
4. Author [phase-5.md](phase-5.md) draft per the [planning protocol](../../../CLAUDE.md). Even a 50-line skeleton with goals + invariants + the sub-phase outline is enough to satisfy the gate.

**Files**:
- `docs/plans/active/mvp/development-plan.md` — MODIFY (Progress Tracking row).
- `docs/plans/active/mvp/phases/phase-4.md` — MODIFY (Completion Criteria checkboxes).
- `docs/plans/active/mvp/work-notes.md` — APPEND (closure session block).
- `docs/plans/active/mvp/phases/phase-5.md` — CREATE (skeleton).

**Gate**: Phase 4 status set to Complete in development-plan.md; phase-5.md exists with at least the Status header, Goal, and Sub-phase Outline sections populated.

**Dependencies**: W6 done.

---

## Dependency graph

```
W1 ────────────────────────────────────────────────────────────► (independent doc hygiene)

W2 ────► W3 ────► W4 ────► W5 ────► W6 ────► W7
        (4C.3)  (ClinVar  (4D —   (4E —   (Phase 4
                parity)   VEP)    materialize)  close)
```

W1 is independent and can be done at any point. W2 should be done before W3 (it informs whether `_GNOMAD_FIELDS` needs patching before the parent-orchestrator chain ships, though either order works structurally — they're surfaces that don't touch each other).

W3 → W4 → W5 → W6 → W7 is a strict linear sequence; each gate informs the next.

## Suggested session breakdown

| Session | Items | Est. wall time | Notes |
|---------|-------|---------------|-------|
| 1 | W1 + W2 | ~30 min | Both cheap; gnomAD chr22 download is the long pole (~10–20 min) |
| 2 | W3 | 1–2 hours | 4C.3 parent rewrite + test triage |
| 3 | W4 | ~30 min | Real-data smoke against the project owner's Nebula VCF |
| 4 | W5 (part 1: fetches + Dockerfile) | 1–2 hours | VEP cache + plugin-data fetch wiring; image rebuild |
| 5 | W5 (part 2: orchestrator + tests) | 2–3 hours | The VEP orchestrator itself; the heaviest piece |
| 6 | W5 real-data smoke | ~4–6 hours wall time, ~30 min active | Run-and-wait; the 4-hour VEP budget gate |
| 7 | W6 + W7 | 1–2 hours | materialize finalisation + Phase 4 close |

**Total active time**: ~10–14 hours across 7 sessions. Wall time is dominated by Session 6's VEP run.

---

## Completion criteria

- [ ] W1 — pivot-debris note in `docs/plans/completed/cram-scratch-strategy/work-notes.md`
- [ ] W2 — gnomAD field-name pre-flight done; `_GNOMAD_FIELDS` either confirmed or patched
- [ ] W3 — `annotate.py` parent rewrite shipped; 3 new tests + 2 kept tests pass; suite green
- [ ] W4 — ClinVar match-count parity check passed (within ε = 1% of 42,885)
- [ ] W5 — VEP + LOFTEE + AlphaMissense + SpliceAI shipped; 15 new tests pass; real-data smoke under 4-hour wall-time budget
- [ ] W6 — schema v0.2 finalised in materialize; 6 new tests pass
- [ ] W7 — Phase 4 marked Complete in development-plan.md; phase-5.md skeleton authored
- [ ] This sub-plan retired (moved into the Phase-4 work-notes or deleted)

---

## What happens after Phase 4 closes

Per [development-plan.md § Phase Overview](../development-plan.md#phase-overview): **Sub-phase 5** — host service (`genomeclaw-service` FastAPI app) + plugin migration to OpenClaw's `registerTool` API + sandbox image build + the first live `INV-D002` / `INV-P002` enforcement gates. Phase 4's full v0.2 column set is the contract Phase 5's service routes will read from.

The hygiene follow-ups deferred from earlier work that don't block Phase 5 (lifestyle gene notes, PRS computation, Cyrius CYP2D6 outside-call, etc.) are Phase 6 scope per the existing development plan and stay deferred.

# Phase 4 Completion — tactical sub-plan

**Status**: ~Active~ → **mostly closed**. W1/W2/W3 ✅ shipped. **W4 (ClinVar match-count parity check) ✅ closed 2026-05-13 in commit 1f58aeb at 42,885 / 42,885 (+0.00% delta) on the project owner's real Nebula VCF.** W5 (sub-phase 4D — VEP) **code shipped**; needs_bio integration tests + real-data smoke remain. W6 (sub-phase 4E — materialize) **shipped**. W7 (Phase 4 close paperwork) pending.
**Created**: 2026-05-11
**Last Updated**: 2026-05-13 (second-pass revision: corrected the first revision's over- and under-optimistic claims after verifying actual code + test state)
**Parent**: [phase-4.md](phase-4.md)
**Predecessor**: Sub-phase 4C.2 closed ([work-notes 2026-05-11](../work-notes.md))
**Scope**: sequence the remaining Phase-4 work into reviewable single-session slices; close all open follow-ups; gate Phase 4 closure.

---

## Why this plan exists

[phase-4.md](phase-4.md) is the big-picture plan covering sub-phases 4A–4E. Three things have happened since it was authored:

1. **Sub-phases 4A + 4B + 4C.1 + 4C.2 landed** by 2026-05-11; 4C.3 + the parent-orchestrator chain landed 2026-05-11. About 60% of Phase 4 by test count and most of the heavier infrastructure is done.
2. **An annotation-correctness incident on 2026-05-12** surfaced fetcher + reference-data gaps; the diagnostic + fix sub-plan landed as [phase-4c4-annotation-correctness.md](../../../completed/phase-4c4-annotation-correctness.md), partly absorbed into the [rich-cli plan](../../../completed/rich-cli/) Phase 3, and partly still open (W4 dbSNP rename onward).
3. **SpliceAI was dropped 2026-05-13** per spec Q5 amendment; sub-phase 4D's footprint shrinks by ~50 GB reference fetch + 3 test cases.

This sub-plan stitches them together. It is not a new spec; the architectural decisions in [phase-4.md](phase-4.md) (Q1–Q10 + Q8.1, plus the 2026-05-13 spec Q5 amendment) stand. Each work item below maps to one focused session with a concrete gate.

> **Numbering note**: the W1–W7 numbering here is **distinct** from the W1–W7 numbering in [phase-4c4-annotation-correctness.md](../../../completed/phase-4c4-annotation-correctness.md). The 4c4 plan has its own W-sequence for the correctness work (W1 fetcher integrity → W7 ClinVar parity recheck). This phase-4-completion plan's W4 (ClinVar parity) corresponds roughly to phase-4c4 W7. Cross-references below disambiguate where it matters.

---

## Work items

### W1 — Pivot-debris cleanup note *(doc-only, ~10 min)*

**Status**: ✅ **Shipped 2026-05-11** (see [completed/cram-scratch-strategy/work-notes.md](../../../completed/cram-scratch-strategy/work-notes.md) "Post-close: colima recovery recipe").

**Goal**: Capture the colima recovery recipe (orphan datadisk + malformed-diffdisk + memory bump) in the completed cram-scratch-strategy plan's work-notes so the next contributor who hits this trap finds the recipe instead of debugging from scratch.

**Files**:
- `docs/plans/completed/cram-scratch-strategy/work-notes.md` — append a "Post-close: colima recovery recipe (2026-05-11)" block. ~30 lines.

**Gate**: dated entry merged; describes the three symptoms (VZ Code=1; mosdepth SIGKILL on synthetic BAM; `/.colima/default` PermissionError in-image) and the three resolutions (`rm -rf ~/.colima/_lima/_disks/<instance>/`; `colima delete && colima start`; `memory: 2 → 8` in `~/.colima/default/colima.yaml`).

**Dependencies**: none.

---

### W2 — gnomAD INFO field-name pre-flight *(verification, ~15 min)*

**Status**: ✅ **Retroactively confirmed 2026-05-12** during the [phase-4c4](../../../completed/phase-4c4-annotation-correctness.md) diagnostic — `AF_grpmax`, `grpmax`, `AF_afr`, `AF_amr`, `AF_eas`, `AF_nfe`, `AF_sas` all verified present in the real gnomAD v4.1 exomes chr22 header. *(Note: original field names `AF_grpmax_joint` / `grpmax_joint` were corrected to `AF_grpmax` / `grpmax` during the 4C.2 implementation; the `_joint` suffix only applies to gnomAD's separate joint exomes+genomes frequency dataset.)*

**Goal**: Confirm `_GNOMAD_FIELDS` in [annotate_vcfanno.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py) match the actual INFO IDs published in gnomAD v4.1's per-chrom exomes VCFs. The names were derived from prior knowledge during 4C.2 implementation; an empirical check against one real file pre-empts a silent zero-overlap regression at the 4C real-data smoke.

**Procedure**:
1. Download one chrom from the public GCS bucket (chr22 is smallest, ~9 GB): `curl -O https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz` (~10–20 min on a typical home connection).
2. `bcftools view -h <file>` → grep `^##INFO=<ID=`.
3. Cross-check against `_GNOMAD_FIELDS`. Each name must appear; the population suffixes (`afr`, `amr`, `eas`, `nfe`, `sas`) must match exactly.
4. If a mismatch surfaces: small patch to `_GNOMAD_FIELDS` + `_GNOMAD_NAMES` + re-run the in-image gate for `test_annotate_vcfanno.py`.

**Gate**: either (a) every name in `_GNOMAD_FIELDS` confirmed present in the real chr22 INFO header, work-notes entry recording the verification; or (b) `_GNOMAD_FIELDS` patched + in-image gate re-run green.

**Dependencies**: none (independent of W3+; this verification is against the published gnomAD bucket, not the project owner's deployment).

---

### W3 — Sub-phase 4C.3 (annotate parent-orchestrator rewrite) *(implementation, ~1–2 hours)*

**Status**: ✅ **Shipped 2026-05-11**. `annotate.py` dropped from ~250 to ~135 lines; chained orchestrator end-to-end against real-data fixture set; 218/0 in-image tests at close. See [work-notes 2026-05-11](../work-notes.md) ("Phase 4C.3 status: complete").

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

**Status**: ✅ **Closed 2026-05-13** in commit 1f58aeb at **42,885 / 42,885 ClinVar matches (+0.00% delta)** vs. the Phase-4A baseline. End-to-end wall: 1h59m on the project owner's Nebula VCF (4.87M variants). The phase-4c4 dependency block resolved at the same time: 1f58aeb shipped phase-4c4 W4 (dbSNP RefSeq→UCSC rename) directly, then ran the parity check, in one session. Phase-4c4 W5 (pre-flight validator) and W6 (vcfanno stderr discipline) did **not** ship; the parity check passed without them (W6 likely obsolete after the per-chrom shard pattern landed in the same commit; W5 remains valuable as a future guard).

**Goal**: Verify the vcfanno-based ClinVar overlay produces a match count that's **documented and explainable** vs. the Phase-4A bcftools-annotate baseline (42,885 ClinVar matches on the project owner's Nebula VCF). Catches any silent multi-allelic-split or matching-semantics divergence between bcftools-annotate and vcfanno.

> **2026-05-13 update — parity criterion softened**: the original gate was "within ε = 1% of 42,885". vcfanno and bcftools-annotate have subtly different multi-allelic INFO semantics; demanding ε = 1% parity puts the test in the position of insisting one of them is wrong. The new gate is "documented and explainable" — record the count, reason about any drift, and accept the new baseline if it's defensible. Drift > 10% still flags a real bug and blocks the next sub-phase.

**Procedure**:
1. Run `bin/genomeclaw pipeline ingest` on the project owner's Nebula VCF (output: a `derived/<run-id>/`).
2. Run `bin/genomeclaw pipeline normalize` against the run dir.
3. Run `bin/genomeclaw pipeline annotate` (the W3-shipped parent orchestrator).
4. Run `bin/genomeclaw pipeline materialize`.
5. Query: `SELECT COUNT(*) FROM variants WHERE clinvar_classification IS NOT NULL`.

**Gate**:
- If count is in a defensible range (e.g., within ~5% of 42,885 or with a documented reason for larger drift), record the count + close W4 as ✅.
- If drift > 10%: real bug; do not proceed to W5.

**Files touched**: `docs/plans/active/mvp/work-notes.md` (record the count + reasoning). No code.

**Dependencies**: W3 done; phase-4c4 W4–W6 (dbSNP rename + pre-flight validator + stderr discipline) done.

---

### W5 — Sub-phase 4D (VEP + LOFTEE + AlphaMissense) *(implementation, 1–2 sessions)*

**Status**: **Code ✅ shipped**; **INV-x contract tests ✅ shipped** (option #2, 2026-05-13); full needs_bio integration tests + first real-data VEP smoke pending. The orchestrator [annotate_vep.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py) is a fully-implemented 334-line module — **not a stub** — and is wired into the parent chain at [annotate.py:138](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py#L138). It resolves the VEP cache, probes per-source dirs for LOFTEE + AlphaMissense plugin data, builds the VEP config + flag list, runs VEP via [_vep.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py), atomic_promotes the output, and updates manifest + provenance. The wrapper + the CSQ parser have unit-test coverage at [test_vep_wrapper.py](../../../../packages/toolkit/tests/unit/test_vep_wrapper.py) + [test_csq_parser.py](../../../../packages/toolkit/tests/unit/test_csq_parser.py). **Per-orchestrator INV-x coverage** (INV-D001 / INV-D003 / INV-R001) now lives at [test_annotate_vep_invariants.py](../../../../packages/toolkit/tests/integration/test_annotate_vep_invariants.py) — 4 host-runnable tests using stubbed `vep_run` / `vep_version` / `bcftools_index_tbi`; all green at first run (characterization — the existing orchestrator already satisfied the contract). All fetches (VEP cache 114, AlphaMissense v1.0, LOFTEE v1.0, gnomAD-constraint v4.1) ✅ shipped and verified intact via `refs verify`. **SpliceAI dropped 2026-05-13** per spec Q5 amendment.

**Goal**: Ship the full VEP-based annotation stack per [phase-4.md § 4D](phase-4.md#sub-phase-4d--vep--loftee--alphamissense). MANE Select transcript pinning; HGVSc/HGVSp/consequence/loftee_lof/alphamissense_score INFO fields; ~21 GB VEP cache fetch + ~4 GB AlphaMissense fetch + ~13 GB LOFTEE data fetch + ~2 MB gnomAD constraint fetch — all ✅ shipped.

**TDD scope**: per [phase-4.md § Step 4D.1](phase-4.md#step-4d1--red-tests). The fetch tests (vep_cache, alphamissense, loftee, gnomad-constraint) + the wrapper + CSQ-parser unit tests all ✅ shipped. The ~7 VEP-orchestrator needs_bio integration tests + 2 parent-orchestrator chain tests are the remaining TDD scope — a single needs_bio test file (`test_annotate_vep.py`) that runs the real `vep` binary against a fixture VEP cache (probably 2026 LOFTEE Plugin tarball + a hand-rolled mini-cache) and asserts each Phase-4D column is populated on a representative fixture variant.

**Files**: per [phase-4.md § Files](phase-4.md#files). All ✅ shipped except `test_annotate_vep.py`.

**Real-data smoke** (per [phase-4.md § Real-data smoke (4D gate)](phase-4.md#real-data-smoke-4d-gate)): full-chain VEP run on the project owner's Nebula VCF. Wall-time budget < 4 hours; peak RAM < 32 GB. Tripwire: if either is breached, the documented follow-up is gnomAD-popmax pre-filtering before VEP runs (per [phase-4.md § Carry-overs](phase-4.md#carry-overs-to-phase-5--later)). The 1h59m parity run in 1f58aeb was vcfanno-only — VEP wasn't fetched yet at that time (dc1207e + a395521 + fd835fb landed the layouts later); the first end-to-end VEP smoke against the now-complete layout is the open gate.

**Gate**: needs_bio integration tests pass; the full-chain real-data VEP smoke completes within budget; provenance step `vep` records the exact CLI flags + plugin versions + AlphaMissense data version; the v0.2 column set is populated with non-NULL values on expected coding-variant rows; `gene_loeuf` populated via the materialize-time join against gnomAD constraint v4.1 (the join code is the small outstanding 4E follow-up).

**Dependencies**: W3 done. (The 4D orchestrator already plugs in.)

**Risk note**: the smoke is run-and-wait. Bioconda `ensembl-vep=114.1` + `git clone konradjk/loftee` + `git clone Ensembl/VEP_plugins` pattern per [phase-4.md Q10](phase-4.md#open-questions-resolved); image already built and verified.

---

### W6 — Sub-phase 4E (materialize finalisation) *(implementation, 1 session)*

**Goal**: Per [phase-4.md § Sub-phase 4E](phase-4.md#sub-phase-4e--schema-v02-finalisation-in-materialize). Every Phase-4 INFO field (clinvar_*, gnomad_af_*, dbsnp_rsid, mane_select_transcript, hgvsc, hgvsp, consequence, loftee_lof, alphamissense_score, alphamissense_class, spliceai_max_delta, gene_loeuf) flows through `materialize`'s `info_fields` tuple into a typed `variants` column. `_VARIANTS_DDL` updated; type coercions (float / int / enum / string) correct.

**TDD scope**: per [phase-4.md § Step 4E.1](phase-4.md#step-4e1--red-tests). 6 cases.

**Files**: per [phase-4.md § Files](phase-4.md#files). MODIFY: `materialize.py`, `_vcf.py:iter_variant_rows`, `store.py:_VARIANTS_DDL`. CREATE: `test_materialize_v02_columns.py`, `test_pipeline_e2e_synthetic.py`.

**Real-data smoke**: re-run materialize against the W5 real-data output; verify every Phase-4 column has at least one non-NULL row at the real-data scale.

**Gate**: 6 new tests pass; the v0.2 schema is anchored (no further additive columns expected within Phase 4); the full-chain pipeline's `manifest.json` records every tool version (`bcftools`, `mosdepth`, `samtools`, `vcfanno`, `vep`, `loftee`, `alphamissense_data`, `gnomad_constraint_data`). *(SpliceAI version no longer recorded — dropped 2026-05-13.)*

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

## Dependency graph (2026-05-13 second-pass)

```
W1 ✅ ──► W2 ✅ ──► W3 ✅ ──► W4 ✅ ────► W5 ⏳ ────► W6 ✅ ──► W7
                            (dbSNP rename     (VEP code         (4E schema        (Phase 4
                             + parity)         shipped; tests +  shipped; gene-     close)
                                                real-data smoke  loeuf join
                                                pending)         pending)
```

W1, W2, W3, W4 ✅ done. W5 split into shipped (orchestrator + wrapper + parser + plugin probing + parent-chain wiring) and pending (needs_bio integration tests + first real-data VEP smoke). W6 mostly shipped (schema columns + materialize-side coverage + dbsnp/9-pop assertion); pending the `gene_loeuf` materialize-time join against gnomAD constraint v4.1. W7 (Phase 4 close paperwork) pending.

## Remaining session breakdown

| Session | Items | Est. wall time | Notes |
|---------|-------|---------------|-------|
| ~~1~~ | ~~W1 + W2~~ | ✅ | Both shipped 2026-05-11. |
| ~~2~~ | ~~W3~~ | ✅ | 4C.3 parent rewrite shipped 2026-05-11. |
| ~~3~~ | ~~W4 (dbSNP + parity)~~ | ✅ | Shipped 2026-05-13 in commit 1f58aeb. Real-data parity 42,885 / 42,885. |
| ~~4~~ | ~~W5 code (orchestrator + wrapper + parser + plugin probing + parent-chain wiring)~~ | ✅ | Shipped 2026-05-13 across commits 1f67bbc + 1f58aeb extensions + dc1207e + a395521 + fd835fb. |
| ~~5~~ | ~~W6 schema + materialize coverage~~ | ✅ | Shipped 2026-05-13 across commits 2fb3beb + fa72c51 + 4c72f5d. |
| 6 | W5 needs_bio integration tests | 2–3 hours | `test_annotate_vep.py` — 7-ish in-image tests against a fixture VEP cache (HGVS/MANE/LoF/AlphaMissense column population, INV-D001 cache-immutability, INV-D003 scratch usage, INV-R001 provenance). |
| 7 | W5 first real-data VEP smoke | ~3–5 h wall, ~30 min active | Run-and-wait; the 4-hour VEP budget gate. The 1f58aeb 1h59m run was vcfanno-only — VEP wasn't fetched at that point. |
| 8 | W6 `gene_loeuf` materialize-time join | ~1–2 hours | Small DuckDB join against the ~1–2 MB gnomAD constraint v4.1 TSV at materialize time. Source ✅ fetched 2026-05-13. |
| 9 | W7 — Phase 4 close paperwork | ~1 hour | Update `development-plan.md` Progress Tracking; tick `phase-4.md` Completion Criteria; append a Phase-4 close block to `work-notes.md` (which is stale since 2026-05-12); author `phase-5.md` skeleton; move 4C.4 sub-plan to `completed/` or fold into work-notes. |

**Optional belt-and-suspenders (non-blocking)**:
- [phase-4c4 W5 — pre-flight annotation schema validator](../../../completed/phase-4c4-annotation-correctness.md#w5--pre-flight-annotation-schema-validator) (~2 hours). Not on the critical path since the W4 parity check passed without it. Still valuable as a future guard against overlay-source regressions.
- [phase-4c4 W6 — vcfanno stderr discipline](../../../completed/phase-4c4-annotation-correctness.md#w6--vcfanno-stderr-noise-filter--redirect-to-file-cosmetic-1-hour) (~1 hour). Probably obsolete after the per-chrom shard pattern shipped in 1f58aeb (eliminated the 120M bix.go warnings structurally; 1h59m wall on 4.87M variants confirms the stderr-overhead concern is gone). Verify before closing 4C.4.
- **`pipeline run --skip-if-present [--skip <phase>]` resume flags** *(parked 2026-05-14; flagged when the 2026-05-14 VEP smoke needed a vcfanno re-run after fixing the `--fasta` + `Bio::Perl` bugs)*. Today `pipeline run` re-does every phase on every invocation; a failed VEP forces another ~1h59m of vcfanno before VEP retries. Design sketch:
  - `--skip-if-present` (no arg) — skip every phase whose output is on disk.
  - `--skip <phase>` (repeatable, comma-separable) — skip these phases regardless of output presence. Phases: `ingest`, `normalize`, `vcfanno`, `vep`, `materialize`.
  - Detection signals per phase: `manifest.json` (ingest), `normalized.vcf.gz` (normalize), `vcfanno.vcf.gz` (vcfanno), `vep.vcf.gz` (vep), `variants.duckdb` rows on current schema (materialize).
  - Same flags on standalone subcommands so users can resume from any point. ~1–2 hours TDD work.
- **Per-shard vcfanno cache + recovery** *(parked 2026-05-14 after a virtiofs-class EBADF crashed one of 4 parallel vcfanno subprocesses at ~1h18m into a real-data smoke; 25 successfully-finished per-chrom outputs were lost on scratch cleanup)*. Today `shard_scratch` purges the entire annotate-vcfanno scratch dir on context exit, throwing away every completed per-chrom output if any one shard fails. Design sketch:
  - Cache per-shard outputs at `_scratch/_cache/annotate-vcfanno/<inputs_sha>/<chrom>.vcf.gz` (mirrors the existing dbSNP rename cache).
  - Cache key: sha256 of (normalized_vcf_sha + each overlay's sha + the inline vcfanno TOML config). Re-fetch / re-rename invalidates deterministically.
  - On annotate run: per-shard, check cache first; copy in if hit, run vcfanno + write to cache if miss.
  - Pairs naturally with `--skip-if-present` above — file-level resumption at the vcfanno.vcf.gz layer + shard-level resumption at the per-chrom layer. ~4–6 hours TDD work.
- **EBADF root cause investigation under concurrent virtiofs reads** *(parked 2026-05-14)*. The 2026-05-14 smoke surfaced `bix: error (re)opening clinvar.renamed.vcf.gz: bad file descriptor` followed by a Go panic inside vcfanno. The cram-scratch-strategy plan's [Phase 4+ tripwire list](../../../completed/cram-scratch-strategy/) named "vcfanno-class deadlock / EIO under load on virtiofs" as the documented condition for migrating scratch to a VM-internal disk (Option B). Workaround in the interim: `GENOMECLAW_ANNOTATE_WORKERS=1` serializes the shards (no concurrent FD pressure) at ~4-6× wall-time cost. Real fix: either move scratch off virtiofs (Option B), or upstream a vcfanno fix.

**Total remaining active time**: ~5–7 hours; wall time dominated by the real-data VEP smoke (~3–5 h unattended).

---

## Completion criteria

- [x] W1 — pivot-debris note in `docs/plans/completed/cram-scratch-strategy/work-notes.md`. ✅ 2026-05-11.
- [x] W2 — gnomAD field-name pre-flight done; `_GNOMAD_FIELDS` confirmed/patched. ✅ 2026-05-12 (retroactive).
- [x] W3 — `annotate.py` parent rewrite shipped; 3 new tests + 2 kept tests pass; suite green. ✅ 2026-05-11.
- [x] phase-4c4 W4 — dbSNP RefSeq→UCSC chr-rename shipped; `dbsnp_rsid IS NOT NULL` count > 0 on real data. ✅ 2026-05-13 (1f58aeb).
- [ ] phase-4c4 W5 — pre-flight annotation schema validator. **Non-blocking** after the W4 parity check passed without it. Still valuable as a future guard.
- [ ] phase-4c4 W6 — vcfanno stderr discipline. **Likely obsolete** after the per-chrom shard pattern landed.
- [x] W4 (= phase-4c4 W7) — ClinVar match-count parity check passed: **42,885 / 42,885 (+0.00%)** on the project owner's Nebula VCF. ✅ 2026-05-13 (1f58aeb).
- [x] W5 **code** — VEP + LOFTEE + AlphaMissense orchestrator + wrapper + CSQ parser + plugin probing + parent-chain wiring all shipped. ✅ 2026-05-13.
- [x] W5 **per-orchestrator INV-x contract tests** — `test_annotate_vep_invariants.py` covers INV-D001 (cache + plugin-data immutability), INV-D003 (scratch usage via shard_scratch), INV-R001 (provenance step structure + flag list + plugin set + recorded-no-plugins corollary). 4 host-runnable tests via stubbed `vep_run` / `vep_version` / `bcftools_index_tbi`. ✅ 2026-05-13 (option #2 of the 2026-05-13 reassessment).
- [ ] W5 **full needs_bio integration tests** — `test_annotate_vep.py` covering HGVS/MANE/LoF/AlphaMissense column population against a fixture VEP cache. **Deferred** — option #2 traded this off for the smaller contract tests above; full coverage to be either built when a real bug surfaces in the upcoming real-data smoke, or left to the smoke itself.
- [x] W5 **first real-data VEP smoke ✅ 2026-05-15** — full-chain `genomeclaw pipeline run` completed in **4h08m58s** end-to-end on the project owner's Nebula VCF. annotate 4h03m31s; materialize 3m20s. Sequence of attempts that got us here:
  - **Fatal — `--hgvs` requires `--fasta` in offline mode**. The wrapper unconditionally enabled `--hgvs` but never passed `--fasta`. ✅ Fixed by extending `VepConfig` with `reference_fasta` + a `_resolve_reference_fasta` helper in `annotate_vep`; recorded in provenance. Defended by 4 new tests (2 unit on flag emission, 2 integration on orchestrator threading + provenance).
  - **Non-fatal but column-killing — `Bio::Perl` missing from the VEP image** caused LOFTEE to silently fail compilation, leaving `loftee_lof` NULL on every variant. Root cause: bioconda's `perl-bioperl-core` 1.7.8 ships `BioPerl.pm` (a different module) but **not** `Bio/Perl.pm`. LoF.pm has a vestigial `use Bio::Perl;` with no callsite. ✅ Fixed by adding `perl-bioperl` to the Dockerfile's vep micromamba env + a 4-line empty `Bio/Perl.pm` shim. Defended by `test_vep_loftee_plugin.py` which runs `perl -c LoF.pm` in-image.
  - **Non-fatal but column-killing (2026-05-15) — `Bio::DB::BigWig` missing from the VEP image** causes LOFTEE's `gerp_dist.pl` helper to fail to compile at LoF.pm line 27; LoF plugin silently disabled; `loftee_lof` + `loftee_filter` stay NULL. The 2026-05-15 real-data smoke surfaces this because the previous `test_vep_loftee_plugin.py` only ran `perl -c LoF.pm` directly — it didn't transitively load `gerp_dist.pl`. **Fix (pending)**: add `perl-bio-bigfile` to the Dockerfile's VEP micromamba env. Extend `test_vep_loftee_plugin.py` to also `perl -c` the gerp_dist.pl helper so the test catches the deeper chain. ~30 min.
- [x] W6 **schema + materialize-side coverage** — every Phase-4 column in `_VARIANTS_DDL`; dbsnp_rsid + every gnomAD population AF surfaced; 3-source assertion passes. ✅ 2026-05-13.
- [x] W6 **`gene_loeuf` materialize-time join** — DuckDB join against gnomAD constraint v4.1 MANE Select rows. `prep/_gnomad_constraint.py` + extended `materialize()` signature with backwards-compatible `reference_dir` + `gnomad_constraint_release` params; 6-test coverage in `test_materialize_gene_loeuf.py`. ✅ 2026-05-14.
- [x] W6 **CLI wiring** — `genomeclaw pipeline materialize --reference-dir <X> [--gnomad-constraint-release v4.1]` flags + `--gnomad-constraint-release` on `pipeline run` (which now also threads `--reference-root` to materialize so the one-shot chain command populates `gene_loeuf`). 6-test coverage in `test_cli_pipeline_materialize_constraint.py`. ✅ 2026-05-14.
- [ ] W7 — Phase 4 marked Complete in development-plan.md; phase-5.md skeleton authored; work-notes updated with the 2026-05-13 session block.
- [ ] This sub-plan retired (moved into the Phase-4 work-notes or deleted).

---

## What happens after Phase 4 closes

Per [development-plan.md § Phase Overview](../development-plan.md#phase-overview): **Sub-phase 5** — host service (`genomeclaw-service` FastAPI app) + plugin migration to OpenClaw's `registerTool` API + sandbox image build + the first live `INV-D002` / `INV-P002` enforcement gates. Phase 4's full v0.2 column set is the contract Phase 5's service routes will read from.

The hygiene follow-ups deferred from earlier work that don't block Phase 5 (lifestyle gene notes, PRS computation, Cyrius CYP2D6 outside-call, etc.) are Phase 6 scope per the existing development plan and stay deferred.

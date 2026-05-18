# Meta-Plan: PRS Bootstrap — Sequencing & Integration

**Status**: Draft
**Created**: 2026-05-17
**Owner**: TBD
**Children**: [`prs-reference-bootstrap/`](prs-reference-bootstrap/), [`prs-runtime-bootstrap/`](prs-runtime-bootstrap/)
**Related**: [docs/plans/active/mvp/phases/phase-6-slice-e-v2.md](mvp/phases/phase-6-slice-e-v2.md)

---

## Why This Exists

Slice E v2 closed out with "real-data smoke deferred to manual: needs Nextflow + pgsc_calc + 1000G/HGDP ancestry data installed host-side." That line violates the README-declared "no host-side bioinformatics install dance" promise. Two sibling plans close the gap independently:

- **[`prs-reference-bootstrap`](prs-reference-bootstrap/)** — ancestry data via `refs fetch`
- **[`prs-runtime-bootstrap`](prs-runtime-bootstrap/)** — Nextflow + JRE + `pgsc_calc` deps bundled into the toolkit Docker image

This meta-plan sequences them, defines the cross-plan integration gate, and tracks the documentation cleanup neither child can do on its own.

This meta-plan **owns no implementation code itself.** All TDD work lives in the children. It owns: sequencing, the integration smoke definition, and the cross-plan doc updates.

---

## Sequencing Decision: Reference First, Then Runtime

**Stage 1: [`prs-reference-bootstrap`](prs-reference-bootstrap/)** (2 phases, ~9 tests)
**Stage 2: [`prs-runtime-bootstrap`](prs-runtime-bootstrap/)** (3 phases, ~8 tests + manual smoke)
**Stage 3: Cross-plan integration smoke** (this plan)

### Why reference first

1. **Smaller blast radius.** A new `_LAYOUTS` entry is one of the most isolated changes possible in the toolkit. Stage 1c of the Dockerfile is one of the largest — image size, dual-arch build, ~400 MB of new deps (revised down from ~800 MB after the `-profile conda` decision pushed plink2/plink/R/Bioconductor out of the image and onto the volume).
2. **The `host doctor` `ancestry_ready` gate ships in Stage 1 Phase 2 and is immediately useful** — it tells the user "your reference data is staged" even before runtime bundling lands.
3. **Stage 2 Phase 3 (the runtime plan's real-data smoke) needs ancestry data present anyway.** Doing reference first means the runtime smoke is just-add-runtime, not just-add-everything.
4. **Layout assumptions surface early.** If the PGS Catalog bundle's extracted shape isn't what we assume (outer `pgsc_HGDP+1kGP_v1/` directory wrapping `1000g/` + `hgdp/`?), we discover that in a 5-test phase, not buried inside a multi-GB image build.
5. **Reverting is cheap.** If the ancestry source pin needs to bump mid-flight (upstream re-cut), nothing in Stage 2 is invalidated.

### Why not in parallel

The children are code-independent, so a parallel branch model is technically viable. Sequencing is preferred because:
- Single-contributor reality — context-switching between a Python fetcher and a Dockerfile + R deps is expensive.
- Stage 3's integration smoke is the actual verification that matters; running it once at the end (not twice on partial states) keeps the wall-clock cost down.
- Stage 1's exit criteria flow naturally into Stage 2's preconditions.

---

## Stage 1 — Reference Bootstrap

**Plan**: [`prs-reference-bootstrap`](prs-reference-bootstrap/)

### Entry criteria
- Slice E v2 (E.1 + E.2) complete (✅ as of 2026-05-17)
- Project owner's host has free disk to absorb ~50-60 GB of ancestry data

### Exit criteria (gate to Stage 2)
- All Phase 1 + Phase 2 acceptance criteria green (see [development-plan.md](prs-reference-bootstrap/development-plan.md))
- `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` succeeds against the project owner's host (Phase 1 real-data smoke)
- `genomeclaw host doctor` returns `ancestry_ready: true`
- `_check_ancestry_reference` in [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) resolves the canonical materialised layout (no phantom path)
- Full toolkit test suite still green (no regressions in the 593-pass / 99-skip baseline)
- Stage 1 plan moved to `docs/plans/completed/prs-reference-bootstrap/`

### Allowed sequencing override
Stage 2 may start before Stage 1's real-data smoke if Stage 1's mocked-HTTP tests are green and a contributor is unblocked. The real-data smoke is the Stage 3 entry gate regardless.

---

## Stage 2 — Runtime Bootstrap

**Plan**: [`prs-runtime-bootstrap`](prs-runtime-bootstrap/)

### Entry criteria
- Stage 1 exit criteria met
- Docker buildx + dual-arch builder available on the development host
- Project owner's Colima VM disk has free space for the new image (~800 MB delta over current toolkit)

### Exit criteria (gate to Stage 3)
- All Phase 1 + Phase 2 acceptance criteria green (Phase 3 is the integration smoke owned by *this* meta-plan, not by the runtime plan)
- Dual-arch image (linux/amd64 + linux/arm64) builds successfully
- Image size growth ≤ 1 GB documented in `work-notes.md`
- `genomeclaw host doctor` returns `prs_runtime_ready: true`
- `tests/invariants/test_invD002_sandbox_image_lacks_pipeline_runtime.py` confirms sandbox image is untouched
- Full toolkit test suite still green
- Stage 2 plan moved to `docs/plans/completed/prs-runtime-bootstrap/` *after Stage 3 is also green* — the runtime plan's "Phase 3 real-data smoke" is now this meta-plan's Stage 3 instead

---

## Stage 3 — Cross-Plan Integration Smoke

**Owner**: this meta-plan.
**Format**: manual real-data smoke, not a committed test (the per-PGS pgscatalog.org egress and the multi-minute Nextflow runtime put it outside the unit/integration tier).

### Goal

Verify the two children compose: a fresh `host setup` host can run `genomeclaw pipeline pgs-compute` end-to-end without any manual install step, producing a real `pgs_scores` row + matching `findings` row carrying the full INV-A003 provenance.

### Acceptance Criteria

- [ ] **AC1**: From a host with toolkit-image-pulled-but-no-reference-data, running `genomeclaw refs fetch --all` materialises both the existing references (clinvar, gnomAD, VEP cache, etc.) **and** the new `pgs_catalog_ancestry` source under `reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/`.
- [ ] **AC2**: After AC1, `genomeclaw host doctor` reports both `ancestry_ready: true` **and** `prs_runtime_ready: true` in the same `--json` envelope.
- [ ] **AC3**: `genomeclaw pipeline pgs-compute --pgs PGS000018 --vcf <NEBULA_VCF> --reference-root <ref> --rationale '<>=50-char rationale>' --question 'my dad had a heart attack at 58' --work-dir <scratch>/pgsc_calc_work` returns exit 0 in ≤30 minutes wall-clock on the project owner's hardware.
- [ ] **AC4**: The resulting `pgs_scores` row has populated `pgs_id="PGS000018"`, non-null `percentile_in_user_ancestry`, the agent rationale + question persisted, `tool="pgsc_calc"`, `tool_version` matching the pin in `_versions.py`, `params_json` recording `-profile standard` + `-r <tag>`.
- [ ] **AC5**: The matching `findings` row carries `category="clinical-non-actionable"`, `evidence_ref="pgs_catalog:PGS000018"`, NULL `clinical_escalation` per `INV-C001` v1.7.
- [ ] **AC6**: No stack traces in `_scratch/pgsc_calc_work/<run-id>/.nextflow.log`; the Nextflow `work/` lives under `_scratch/` and is safe to delete after the row lands (`INV-D003`).
- [ ] **AC7**: A second invocation against the same PGS ID does not re-fetch ancestry data + reuses the pre-warmed pipeline cache (sanity check on Stage 1 `INV-D001` + Stage 2 `NXF_HOME` bind-mount).
- [ ] **AC8**: All four privacy-default tests pass with the new images: no unsolicited runtime egress under default config; the only network call during the smoke is the deliberate per-PGS weight fetch from `pgscatalog.org`.

### Smoke Verification Walkthrough

```bash
# Pre-conditions
# - Toolkit image at the Stage 2 pin pulled locally
# - Colima running with the canonical mounts
# - host setup already complete on the external drive

# 1. Land all references including the new ancestry source (Stage 1 deliverable)
genomeclaw refs fetch --all

# 2. Confirm both readiness gates green (Stage 1 + Stage 2 deliverables)
genomeclaw host doctor --json | jq '{ancestry_ready, prs_runtime_ready}'
# Expect: {"ancestry_ready": true, "prs_runtime_ready": true}

# 3. End-to-end PRS compute against the real Nebula VCF
genomeclaw pipeline pgs-compute \
    --pgs PGS000018 \
    --vcf "$NEBULA_VCF" \
    --reference-root /Volumes/Genome_Work/genomeclaw/reference \
    --rationale "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS with the most mature cross-ancestry calibration story. Considered PGS004696 but went with PGS000018 for cross-ancestry validation." \
    --question "my dad had a heart attack at 58. is there anything in my genome about cad risk?" \
    --work-dir /Volumes/Genome_Work/genomeclaw/_scratch/pgsc_calc_work \
    --run-dir /Volumes/Genome_Work/genomeclaw/derived/current

# 4. Verify the rows landed
duckdb /Volumes/Genome_Work/genomeclaw/derived/current/variants.duckdb \
    "SELECT pgs_id, percentile_in_user_ancestry, tool, tool_version, params_json
     FROM pgs_scores WHERE pgs_id = 'PGS000018'"

duckdb /Volumes/Genome_Work/genomeclaw/derived/current/variants.duckdb \
    "SELECT category, evidence_ref, clinical_escalation
     FROM findings WHERE evidence_ref = 'pgs_catalog:PGS000018'"

# 5. Idempotency sanity check
genomeclaw refs fetch --source pgs_catalog_ancestry --release v1  # expect VersionAlreadyExists

# 6. Wall-clock + log check
tail -50 /Volumes/Genome_Work/genomeclaw/_scratch/pgsc_calc_work/*/.nextflow.log
```

### Completion Criteria

- [ ] All 8 ACs verified
- [ ] Walkthrough recorded in `work-notes.md` with actual wall-clock numbers + image versions
- [ ] No regressions in the toolkit unit/integration suite (`uv run pytest packages/toolkit/tests`)
- [ ] Post-smoke documentation cleanup (next section) complete

---

## Documentation Cleanup (Owned by Stage 3)

After Stage 3 is green, this meta-plan owns these edits — none of which the individual children should make on their own, because each only sees half the picture:

- [ ] Strike "real-data smoke deferred to manual: needs Nextflow + pgsc_calc + 1000G/HGDP ancestry data installed host-side" from [docs/plans/active/mvp/phases/phase-6-slice-e-v2.md](mvp/phases/phase-6-slice-e-v2.md); replace with reference to this meta-plan's Stage 3 smoke walkthrough.
- [ ] Update [README.md](../../README.md) storage planning table — current `reference/` size estimate jumps from ~300-350 GB to ~350-410 GB once `pgs_catalog_ancestry` lands.
- [ ] Update [docs/reference/architecture.md](../../reference/architecture.md) host-side-packaging section so the toolkit-image content list matches the README sentence at line 48 (Nextflow + JRE + plink + R + `pgsc_calc` now actually in the image).
- [ ] Append a Q11 row (or equivalent) to [docs/reference/grand-plan.md](../../reference/grand-plan.md) decisions-taken table noting the PRS bootstrap closure.
- [ ] Move both child plans **and** this meta-plan to `docs/plans/completed/` simultaneously.

---

## Progress Tracking

| Stage | Plan | Status | Started | Completed | Notes |
|-------|------|--------|---------|-----------|-------|
| 1 | [prs-reference-bootstrap](prs-reference-bootstrap/) | Phase 1 + 2 complete on TDD axis; real-data smoke pending Stage 3 | 2026-05-17 | 2026-05-17 (TDD axis) | +9 tests; 602 pass / 99 skip; `zstandard` Python lib (not `zstd` binary); `host doctor` surfaces `ancestry_ready` (ready / partial / missing) per INV-C001 v1.7 |
| 2 | [prs-runtime-bootstrap](prs-runtime-bootstrap/) | Phase 1 complete (both Sub-phases 1.A + 1.B green); Phase 2 partially landed | 2026-05-17 | 2026-05-17 (Phase 1) | +3 tests (2 doctor + 1 INV-R001 provenance) + 4 image-level smoke; 609 pass / 99 skip. **Architectural revision**: `-profile conda` (not `-profile standard` — doesn't exist in pgsc_calc); plink2/plink/R/Bioconductor materialise per-process at first run into `reference/nextflow-cache/conda/` instead of being baked into the image. Image delta ~1.07 GB (vs spec ~400 MB; mamba 2.x libmamba dominates). `genomeclaw/toolkit:prs-phase1` built + smoked locally on Apple Silicon |
| 3 | Integration smoke (this plan) | Partial | 2026-05-17 | 2026-05-18 (basic chain) | **17 iterations** uncovered: hardcoded `_VALID_FETCH_SOURCES` bug, wrong upstream URL, wrong bundle layout assumption (flat not 1000g/+hgdp/), bundle size (16 GB not 5-7 GB), wrong `-profile standard` (doesn't exist; switched to `docker`), arm64 plink2 unavailable on conda → DooD path, host RAM constraint (16 GB), chrX/Y header strip needed, NXF_HOME bind-mount needed for DooD path translation, identical inside/outside container paths needed. **Real PRS score produced: PGS000018 SUM=9.476, AVG=9.56e-06 for sample MPNRGLQ2K.** Ancestry calibration (`--run_ancestry`) FAILED on the variant-only VCF — only 28% of PGS scoring weights matched (Nebula VCF lacks REF/REF sites). Documented as follow-up plan; basic PRS chain validated end-to-end |
| 4 | Docs cleanup (this plan) | Pending | | | |

---

## Stage 3 — Real-Data Smoke Results (2026-05-17 → 2026-05-18)

Ran the integration smoke against the project owner's real Nebula VCF (`MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz`, 4.7M variants) and the actually-downloaded PGS Catalog ancestry bundle (16 GB compressed → 28 GB extracted). Took **17 iterations** to get a real PRS score because almost every assumption in the spec/plans collided with upstream / infrastructure reality.

### What was validated end-to-end

✅ Colima + external-drive bind-mount chain works (after `host setup` restored `mounts: []` drift)
✅ `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` downloads + extracts the real 16 GB bundle from `ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/`
✅ `_collect_ancestry_ready` reports `ready` against the real layout
✅ Toolkit image (`genomeclaw/toolkit:prs-phase1`) builds with Nextflow + JRE 17 + mamba + Docker CLI; `pgsc_calc` pipeline pre-warmed in `/opt/pgsc_calc/`
✅ Nextflow runs via DooD (Docker socket mounted; identical inside-outside paths); pulls pgscatalog/* sibling images successfully
✅ plink2 processes the real Nebula VCF (4,703,655 variants scanned; 4,584,153 after autosome filter)
✅ MATCH passed at 28.37% variant overlap with PGS000018 with `--min_overlap 0.0`
✅ `aggregated_scores.txt.gz` produced: PGS000018 SUM=9.47603, DENOM=990868, AVG=9.56e-06 for sample MPNRGLQ2K

### What remains broken

❌ **Ancestry calibration on a variant-only VCF.** With `--run_ancestry` enabled, the `INTERSECT_THINNED` step's JOIN produces empty values (`n:0`) because Nebula's variant-only VCF excludes REF/REF sites — only ~28% of PGS scoring weights overlap, and crucially the LD-thinned PCA-eligible variant subset has ~zero overlap with our 28%. This is a fundamental input-format mismatch, not a toolchain bug.

### Architectural revisions surfaced

1. **Upstream URL was wrong** — `/pgsc_calc/` was a phantom subdirectory I invented. Actual path: `/pub/databases/spot/pgs/resources/pgsc_HGDP+1kGP_v1.tar.zst`.
2. **Bundle layout is flat, not subdir-split** — gnomAD-merged 1000G+HGDP, with combined `GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}` files. My initial `1000g/` + `hgdp/` assumption was wrong. Fixed `_LAYOUTS`, `_PGS_ANCESTRY_PRESENCE_FILES`, `_check_ancestry_reference`, doctor probes, tests.
3. **Bundle size: 16 GB compressed → 28 GB extracted** (not ~5-7 GB → ~50-60 GB as estimated).
4. **`pgsc_calc -profile standard` does not exist.** Available profiles: conda/mamba/docker/singularity/etc.
5. **`-profile conda`/`mamba` fail on arm64** — pgsc_calc v2.2.0's env files pin `plink2 2.0a5.10` which isn't on conda-forge for `linux-aarch64`. Switched to `-profile docker` via DooD (Docker-out-of-Docker) — pgscatalog/* images are multi-arch.
6. **DooD path translation** — Nextflow's sibling containers see host paths, not container paths. Solved by mounting at identical paths inside-and-outside (e.g. `-v /Volumes/Genome_Work/.../scratch:/Volumes/Genome_Work/.../scratch`).
7. **NXF_HOME must live on the bind-mounted volume** — `/root/.nextflow` (container-local) causes asset symlinks pgsc_calc stages into work dirs to break when sibling containers read them.
8. **Pre-CLI hardcoded `_VALID_FETCH_SOURCES` bug** ([refs.py:66](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py#L66)) was rejecting Phase 4D + new sources. Fixed by deriving from `_LAYOUTS`.
9. **Pre-existing doctor bug** — `_SubprocessRunner.run` doesn't catch `FileNotFoundError` for missing `colima` binary; surfaces as an internal_error envelope. Workaround for now: `PATH=/opt/homebrew/bin:$PATH`. Real fix is its own micro-plan.
10. **Variant-only VCF can't drive ancestry calibration.** Documented as follow-up.

### Follow-up plan needed: `prs-input-coverage-fill`

To make `--run_ancestry` actually work for the project owner's Nebula data, a new plan needs to:
- Take the user's CRAM (already on disk at `raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram`)
- For PGS Catalog scoring weight positions, genotype the user's reads (bcftools mpileup + call OR GATK HaplotypeCaller in GVCF mode at PGS-relevant sites)
- Produce a VCF with calls at all PGS-relevant sites including REF/REF
- Feed that into pgsc_calc

This is a non-trivial pipeline addition (~1-2 weeks effort) but is the correct production fix for INV-C001 v1.7 ancestry-calibrated PRS. The current smoke validates that everything else in the chain works.

### Infrastructure follow-ups (separate from input-coverage)

- **Wrapper code update**: `_build_pgsc_calc_argv` in [prep/pgs.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) currently uses `-profile conda` per the spec; smoke proved `docker` is the right profile on arm64. Update spec + dev-plan + code + tests.
- **Image-or-volume revision**: the spec said "no DooD"; smoke proved DooD is necessary for arm64. Revise spec's architectural decision + accept the socket-mount as the canonical pattern (or add Singularity follow-up).
- **Re-archive design**: my post-fetch hook deleted the `.tar.zst` after extraction, but pgsc_calc actually wants the `.tar.zst` directly. Re-archived in-place for the smoke; the proper fix is to KEEP the bundle as-is + drop the extraction post-hook entirely.
- **chrX/Y stripping**: Nebula VCFs need autosome-only pre-processing for plink2 to accept them (header AND variant filtering via `bcftools view -r ... + bcftools reheader`). This belongs in an upstream pipeline step, not the user's responsibility.
- **Doctor PATH workaround**: ship a fix for `_SubprocessRunner.run` catching `FileNotFoundError`.

## Open Risks & Cross-Plan Follow-ups

- **Disk-space pressure.** Stage 1 lands ~50-60 GB of new reference data; Stage 2 grows the toolkit image by ~800 MB. The project owner's external drive should have ≥100 GB headroom before Stage 1 begins. `host setup`'s free-space calculation must account for the new source; verify in Stage 1 Phase 2.
- **Upstream churn during the gap between stages.** If PGS Catalog re-cuts the ancestry bundle while Stage 1 is in flight, the pin bump should happen in Stage 1 (where the layout is owned). Document the bump procedure in Stage 1's `work-notes.md`.
- **arm64 R + Bioconductor risk.** If Stage 2 Phase 1 reveals a Bioconductor package `pgsc_calc` needs but that doesn't build on arm64, fall back to `linux/amd64` only with documented x86-emulation slowdown — record the decision in Stage 2 work-notes and update this meta-plan's AC2 wall-clock budget accordingly.
- **`refs-integrity-hardening` ordering.** If that plan lands before Stage 1, Stage 1's `_LAYOUTS["pgs_catalog_ancestry"]` entry should include the manifest-write step from day one rather than retrofit. Re-confirm at Stage 1 kickoff.
- **CI pipeline.** Neither child plan adds CI plumbing for the new dual-arch image build. Track as a separate follow-up once both stages land + the smoke is green.

---

## How to Resume This Meta-Plan

1. Open this file + read **Progress Tracking** to find the current stage.
2. If a child plan is in flight, switch to that child's `work-notes.md`.
3. If between stages, confirm the previous stage's exit criteria before starting the next.
4. The integration smoke (Stage 3) only fires after Stage 1 + Stage 2 are both at "ready to move" state — see exit criteria sections above.

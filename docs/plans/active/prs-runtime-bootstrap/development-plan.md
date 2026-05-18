# PRS Runtime Bootstrap — Development Plan

**Status**: In Progress (Phase 1 complete — both Sub-phases 1.A + 1.B green; Phase 2 partially landed; Phase 3 deferred to meta-plan Stage 3)
**Created**: 2026-05-17
**Branch**: `feature/prs-runtime-bootstrap`
**Spec**: [spec.md](spec.md)

---

## Summary

Add a Stage 1c to the toolkit Dockerfile that bakes Nextflow + JRE 17 + mamba + a pre-warmed `pgsc_calc` pipeline source (`pgsc_calc -profile conda` materialises plink2/plink/R/Bioconductor per-process at first run, cached on the bind-mounted volume). Add a `host doctor` PRS-runtime readiness section. Delivers on the README-declared "no host-side bioinformatics install dance" promise for PRS, on the same image-or-volume footing as VEP — heavy scoring deps land on the volume (governed by `INV-R001`), not in the image.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — `pgsc_calc` reads the user's VCF read-only via the existing bind-mount discipline; writes only to `_scratch/` + `derived/`. Unchanged.
- **INV-D002** Sandbox Is Bioinformatics-Free — binaries land in the **toolkit** image, not the **sandbox** image. The agent sandbox stays untouched.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — Nextflow `work/` lives under `_scratch/pgsc_calc_work/<run-id>/`, not `derived/`.
- **INV-P001** Privacy Default — no new always-on egress. `pgsc_calc`'s per-PGS weight fetch from `pgscatalog.org` is install-time-consented separately.
- **INV-R001** Rebuildability — image rebuild is deterministic from `Dockerfile + lockfiles`; pinned tool versions surface in `pgs_scores.tool_version` provenance.

## Proposed New Invariants

**None.** Delivering already-declared architecture.

## Current State Analysis

The toolkit Dockerfile contains four stages (1 / 1a / 1b / 2) covering bcftools/samtools/VEP and Python. Zero Nextflow, JRE, plink, or R. The Slice E v2 PRS wrapper at [pgs.py:97-109](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L97-L109) subprocess-invokes `pgsc_calc` which doesn't exist on a fresh `host setup`. The shim [bin/genomeclaw](../../../bin/genomeclaw) wraps `docker run` with the four canonical bind mounts; this plan reuses that contract unchanged.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/toolkit/Dockerfile` | 5 stages, no pipeline runtime | Add a `prs-runtime` build stage and extend the `bio` env (or wire a Stage 1c COPY) so the runtime image carries Nextflow + JRE 17 + mamba + pre-warmed `pgsc_calc` source |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | 4 readiness checks + `ancestry_ready` informational section | Add `prs_runtime_ready` informational section (probes `nextflow -version`, `java -version`, `mamba --version`, `/opt/pgsc_calc/main.nf` pre-warm). Same informational pattern — doesn't change exit code |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` | Records pinned tool versions for provenance | Add Nextflow + JRE + mamba + pgsc_calc pins |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | `_build_pgsc_calc_argv` returns the argv | Add `-profile conda` + pinned `-r v2.2.0` to the argv; document the NXF_HOME / NXF_CONDA_CACHEDIR env contract |
| `bin/genomeclaw` | Wraps `docker run` with four bind mounts | Add `NXF_HOME` + `NXF_CONDA_CACHEDIR` env passthrough so the Nextflow cache + materialised conda envs land on the bind-mounted reference root |
| `packages/toolkit/pyproject.toml` + `packages/toolkit/tests/conftest.py` | Has `needs_bio`, `needs_sandbox`, `live_llm` markers | Add `needs_prs_runtime` marker (auto-skip unless `GENOMECLAW_TOOLKIT_PRS_IMAGE` points at a built image carrying the Stage 1c additions) |
| `README.md` | "designed for" lists current image size implicitly | Note ~400 MB image growth + new Nextflow + JRE + mamba bundling |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/integration/test_toolkit_image_prs_runtime.py` | Image-level smoke: nextflow/java/mamba reachable, `/opt/pgsc_calc/main.nf` present + parses, `nextflow run pgscatalog/pgsc_calc --version` resolves through the pre-warm cache. Skipped unless `GENOMECLAW_TOOLKIT_PRS_IMAGE` is set |
| `packages/toolkit/tests/integration/test_doctor_prs_runtime.py` | `prs_runtime_ready` reports `ready` / `missing` against a stubbed-runner doctor invocation. Pure Python; no image needed |

## Solution Design

```text
toolkit Dockerfile
  ├── Stage bio          bcftools / samtools / vcfanno / mosdepth        (existing)
  ├── Stage vep          VEP 114.1 in /opt/conda-vep                      (existing)
  ├── Stage vep-plugins  LOFTEE + Ensembl VEP_plugins                     (existing)
  ├── Stage prs-runtime  Nextflow + JRE 17 + mamba                        (NEW)
  │                      pre-warm pgsc_calc source into /opt/pgsc_calc/
  ├── Stage pybuild      Python toolkit + uv venv                         (existing)
  └── Stage runtime      composes everything                              (existing, +COPY from prs-runtime)

runtime:
  bin/genomeclaw  →  docker run \
                       -e NXF_HOME=/mnt/genomeclaw/reference/nextflow-cache \
                       -e NXF_CONDA_CACHEDIR=/mnt/genomeclaw/reference/nextflow-cache/conda \
                       -v /Volumes/Genome_Work/genomeclaw/...:/mnt/genomeclaw/... \
                       genomeclaw/toolkit:<tag> \
                       pipeline pgs-compute ...

  pgsc_calc -profile conda  →  Nextflow shells out to mamba/conda to materialise
                                per-process scoring envs at first run
                                envs cached at $NXF_CONDA_CACHEDIR (on the volume)
                                no nested containers, no DinD, no socket mount
                                per-PGS weight fetch from pgscatalog.org (INV-P001)
```

### Key Design Decisions

1. **`-profile conda`, not `-profile standard` (which doesn't exist) or `-profile docker`.** Verified against [pgsc_calc nextflow.config](https://github.com/PGScatalog/pgsc_calc/blob/main/nextflow.config). The conda profile is the only path that stays cleanly inside the image-or-volume boundary without a Docker socket mount. PGScatalog's "last resort" warning is HPC-context; single-host PoC is fine.
2. **First-run env materialisation lives on the volume, NOT the image.** plink2/plink/R/Bioconductor packages land in `reference/nextflow-cache/conda/<env-hash>/` on first compute, cached across container restarts, and are `refs verify`-able. Trade-off: ~5-10 min one-time tax on the first PGS compute; subsequent computes hit the cache. Keeps the image small (~400 MB Stage 1c addition vs ~800 MB if we baked everything in).
3. **Pre-warm the `pgsc_calc` pipeline source at image-build time.** `nextflow pull pgscatalog/pgsc_calc -r v2.2.0` during Stage 1c bakes the pipeline DSL into `/opt/pgsc_calc/`. First user run does not pay a 30-60s GitHub pull tax + the image is deterministic from its hash.
4. **Bind-mount both `NXF_HOME` and `NXF_CONDA_CACHEDIR` to `reference/nextflow-cache/`.** Auto-pulled pipeline updates + Nextflow's metadata land at `$NXF_HOME`; materialised conda envs land at `$NXF_CONDA_CACHEDIR`. Both persist across container restarts + are host-visible.
5. **Nextflow `work/` lands in `_scratch/`, not `derived/`.** `INV-D003` requires heavy scratch separated from authoritative outputs. The wrapper at [pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) already accepts a `work_dir` param; the CLI sets it to `_scratch/pgsc_calc_work/<run-id>/`.
6. **arm64-native image build** (`docker buildx --platform linux/arm64,linux/amd64`). Project owner runs Apple Silicon via Colima; x86 emulation tanks `pgsc_calc` runtime by 3-5x AND poisons the materialised conda envs (arch-specific binaries). The materialised envs are NOT portable across architectures; first-run arch is sticky.

### Schema / Provenance Impact

- New / changed schemas: none.
- Schema version bumps: none.
- Provenance columns added: none (existing `pgs_scores.tool_version` will record the pinned `pgsc_calc` version now that it's reachable).
- Rebuild procedure: `docker build -t genomeclaw/toolkit:<tag> packages/toolkit/`.

### Privacy & Egress Impact

- New network egress points at **build time**: Nextflow installer, plink release URLs, R package mirror, nf-core pipeline pull. All occur on CI / developer machine, not on user's host.
- New network egress points at **runtime**: zero new always-on. `pgsc_calc`'s per-PGS weight fetch from `pgscatalog.org` is the only runtime egress and is install-time-consented separately.
- New secret-handling surfaces: none.
- Redaction added: n/a.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Dockerfile Stage 1c + image-level smoke + version pins in `_versions.py` | Each binary reachable + at pinned version in the built image | 5 |
| 2 | `host doctor` `prs_runtime_ready` check + `bin/genomeclaw` `NXF_HOME` passthrough | Doctor reports readiness against in-container probes; works against `--json` consumer | 3 |
| 3 | Real-data smoke against project owner's host (Story 10 end-to-end through Slice E.2 manual CLI path) | `genomeclaw pipeline pgs-compute` produces real `pgs_scores` + `findings` rows on real Nebula VCF | manual smoke; not a committed test |

## Phase 1: Dockerfile Stage 1c

**Goal**: Build `genomeclaw/toolkit:<tag>` containing Nextflow + JRE 17 + plink2 + plink + R + Bioconductor + pre-warmed `pgsc_calc` pipeline cache, with each binary reachable on PATH.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `packages/toolkit/Dockerfile` Stage 1c.
2. `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` pins for the new tools.
3. `packages/toolkit/tests/integration/test_toolkit_image_prs_runtime.py` exercising each binary inside a `docker run --rm` call.
4. README size + tool-list note.

### Invariants Enforced Here
- **INV-D002**: Test asserts the *sandbox* image does NOT contain these binaries (regression guard against accidentally adding them to the wrong image).
- **INV-R001**: Test asserts `nextflow --version`, `java --version`, `plink2 --version`, `Rscript --version`, `pgsc_calc --version` all return the values pinned in `_versions.py`.

### Success Criteria
- [ ] All 5 tests for this phase pass (RED → GREEN → REFACTOR visible)
- [ ] `docker buildx build --platform linux/amd64,linux/arm64` succeeds
- [ ] Image size growth ≤ 1 GB
- [ ] No regressions in the existing toolkit test suite

## Phase 2: Doctor Gate + Shim Plumbing

**Goal**: `genomeclaw host doctor` reports PRS runtime readiness; `bin/genomeclaw` sets `NXF_HOME` so the in-container Nextflow cache lands on the bind-mounted reference root.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md) (created when Phase 1 lands)

### Deliverables
1. `prs_runtime_ready` check in `prep/doctor.py`.
2. `bin/genomeclaw` env passthrough for `NXF_HOME` → `reference/nextflow-cache/`.
3. CLI wrapper at `prep/pgs.py` passes `-profile standard` and the pinned `-r <tag>` to `pgsc_calc`.

### Invariants Enforced Here
- **INV-R001**: Test that the params recorded by the wrapper into `pgs_scores.params_json` include the pinned `pgsc_calc` revision tag.

### Success Criteria
- [ ] All 3 tests for this phase pass
- [ ] `host doctor --json` includes `prs_runtime_ready` boolean
- [ ] Empty `reference/nextflow-cache/` is auto-created on first PRS-compute invocation

## Phase 3: Real-Data Smoke (Manual)

**Goal**: End-to-end smoke from `host setup` → `refs fetch` → `pipeline pgs-compute` against the project owner's actual Nebula VCF + real `pgsc_calc` pipeline + real PGS Catalog egress. Verifies the synthetic→real gap doesn't hide a regression.

### Deliverables
1. A walkthrough recorded in `work-notes.md` covering: fresh `host setup`, `refs fetch --all` (both `pgs_catalog_ancestry` from sibling plan + everything else), pulling the new toolkit image, invoking `pipeline pgs-compute --pgs PGS000018 --vcf <NEBULA_VCF> ...`, verifying the `pgs_scores` + `findings` rows landed.
2. Wall-clock timing measurement (cap at 30 min per `INV-A002` v1.7 long-task expectation).

### Success Criteria
- [ ] Smoke succeeds end-to-end
- [ ] `pgs_scores` row records pinned `pgsc_calc` version + full INV-A003 provenance
- [ ] Matching `findings` row carries `clinical-non-actionable` category + `evidence_ref=pgs_catalog:PGS000018`
- [ ] No errors in `_scratch/pgsc_calc_work/<run-id>/.nextflow.log`

---

## Testing Strategy

### Integration Tests
- `tests/integration/test_toolkit_image_prs_runtime.py`: image-level smoke (each binary reachable + pinned).
- `tests/integration/test_doctor_prs_runtime.py`: doctor readiness check.

### Provenance Tests
- Extension of existing `tests/integration/test_cli_pipeline_pgs_compute.py`: assert the recorded `params_json` includes `-r <tag>` and `-profile standard`.

### Determinism Tests
- Image-build determinism is handled by Docker's content-addressed layers + pinned tool versions. No new determinism test required.

### Privacy-Default Tests
- The existing `tests/privacy/test_invP001_*` suite asserts no unsolicited runtime egress. This plan adds no new runtime egress; verify the suite still passes.

### Invariant Tests
- `tests/invariants/test_invD002_sandbox_image_lacks_pipeline_runtime.py`: assert the sandbox image (built from `packages/sandbox/Dockerfile` or equivalent) does NOT contain `nextflow`, `pgsc_calc`, `plink2`. Regression guard against accidentally leaking pipeline tools into the agent sandbox.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — no change; existing INVs already cover this surface.
- [ ] [docs/reference/architecture.md](../../reference/architecture.md) — extend the host-side packaging section to list Stage 1c contents.
- [ ] [README.md](../../../README.md) — confirm the "host pipeline ships as the `genomeclaw/toolkit` Docker image — pinned ... `pgsc_calc` ride along with it" sentence now matches reality; note +800 MB image growth in storage planning.
- [ ] [docs/plans/active/mvp/phases/phase-6-slice-e-v2.md](../mvp/phases/phase-6-slice-e-v2.md) — strike "real-data smoke deferred to manual: needs Nextflow + pgsc_calc + 1000G/HGDP ancestry data installed host-side" line; replace with reference to this plan + sibling.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 (Sub-phase 1.A — code authoring) | Complete | 2026-05-17 | 2026-05-17 | +3 new tests (2 doctor + 1 INV-R001 provenance); +4 skipped pending 1.B; 605 pass / 103 skip; profile decision **revised** from `-profile standard` to `-profile conda` (no `-profile standard` exists in pgsc_calc); image-size budget revised ~800 MB → ~400 MB |
| Phase 1 (Sub-phase 1.B — image build + smoke) | Complete | 2026-05-17 | 2026-05-17 | Built `genomeclaw/toolkit:prs-phase1` linux/arm64 in 3 iterations (PATH-before-install order; JAR cache preservation; `/work` chown; mamba 2.x version output). 4/4 image-level smoke tests pass; full suite 609 pass / 99 skip. Image delta ~1.07 GB (vs ~400 MB spec) — mamba 2.x libmamba native deps + chmod-layer duplication dominate; acceptable for PoC, optimisation deferred |
| Phase 2 | Pending | | | Doctor + shim plumbing — partially landed in Phase 1 (`prs_runtime_ready` informational section); shim `NXF_HOME` passthrough still pending |
| Phase 3 | Pending | | | Real-data smoke, deferred to meta-plan Stage 3 |

---

## Open Risks & Follow-ups

- **Image size**: ~800 MB growth pushes the toolkit image past 4 GB. For Apple Silicon users on Colima with a small VM-disk default, this can force a `colima delete` / `colima start --disk <N>` cycle. Confirm against the project owner's host.
- **arm64 R + Bioconductor builds**: Some Bioconductor packages have flaky arm64 builds. If `pgsc_calc`'s required packages don't build natively on arm64, fall back to `linux/amd64` only and accept the colima x86-emulation slowdown — document the decision.
- **Nextflow + JRE pinning churn**: When `pgsc_calc` releases a new version that requires a different Nextflow LTS or JRE, the pin bump touches all three layers. Document the bump procedure in `work-notes.md`.
- **CI pipeline**: Image build + push to GHCR needs CI plumbing. Out of scope here; track as a follow-up once both PRS plans land.

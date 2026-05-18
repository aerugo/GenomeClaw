# Feature: PRS Runtime Bootstrap

**Status**: Draft
**Created**: 2026-05-17
**Owner**: TBD
**Related Plans**: [docs/plans/active/mvp/phases/phase-6-slice-e-v2.md](../mvp/phases/phase-6-slice-e-v2.md) (this closes the runtime-dependency gap that Slice E.3's orchestrator needs); [docs/plans/active/prs-reference-bootstrap/](../prs-reference-bootstrap/) (sibling — reference-data side)

---

## Goal

Bundle Nextflow + JRE 17 + a `pgsc_calc` pipeline pre-warm into a new Stage 1c of the toolkit Docker image, plus expose conda/mamba on the in-image PATH so `pgsc_calc -profile conda` can materialise per-process scoring dependencies (plink2, plink, R + Bioconductor) into a bind-mounted Nextflow cache on the reference volume. The result: `genomeclaw pipeline pgs-compute` + the Slice E.3 async orchestrator run end-to-end with **zero host-side bioinformatics install dance**, matching the README's declared architecture.

## Background

The [README.md:48](../../../README.md#L48) declaration is explicit:

> The host pipeline ships as the `genomeclaw/toolkit` Docker image — pinned `bcftools` / `mosdepth` / `samtools` / `htslib` / VEP / Cyrius / `pgsc_calc` ride along with it, so there is no host-side bioinformatics install dance.

`pgsc_calc` is listed in that sentence but **not present** in the toolkit image today. [packages/toolkit/Dockerfile](../../../packages/toolkit/Dockerfile) currently contains:

- **Stage `bio`** — bcftools 1.21, mosdepth 0.3.10, samtools 1.21, htslib 1.21, vcfanno 0.3.5
- **Stage `vep`** — VEP 114.1 in isolated micromamba env `/opt/conda-vep`
- **Stage `vep-plugins`** — LOFTEE + Ensembl VEP_plugins (plugin code, not data)
- **Stage `pybuild`** — Python toolkit + uv venv
- **Stage `runtime`** — composed final image

No Nextflow. No JRE. No `pgsc_calc` pipeline cache. The Slice E v2 wrapper at [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py:97-109](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L97-L109) subprocess-invokes `pgsc_calc`, which only exists if the user has installed Nextflow + the pipeline manually on their host. This silently violates the README promise; any user following the documented install path will hit an opaque `FileNotFoundError: pgsc_calc` on first PRS compute.

### Profile decision (revised from earlier draft)

`pgsc_calc` ships with `conda`, `mamba`, `docker`, `singularity`, `podman`, etc. profiles — **there is no `-profile standard`**. Verified directly against [PGScatalog/pgsc_calc nextflow.config](https://github.com/PGScatalog/pgsc_calc/blob/main/nextflow.config) (2026-05-17). The original spec drafted around `-profile standard` (pre-baked plink2 + plink + R + Bioconductor in the image) is structurally not how `pgsc_calc` runs.

The three viable options for the GenomeClaw image-or-volume model:

1. **`-profile conda`** — bake Nextflow + JRE + mamba; let `pgsc_calc` materialise per-process conda envs on first run, cached on the bind-mounted volume. Image gains ~250 MB. First PGS compute is ~5-10 min slower (env materialisation); subsequent computes hit the cache. **Chosen.**
2. **`-profile docker` with DooD** — mount the Colima Docker socket; Nextflow spawns sibling containers. Smaller image, but the socket mount leaks outside the image-or-volume boundary.
3. **`-profile singularity`** — Singularity binary in the image. Heavier than mamba; weaker macOS support via Colima.

Option 1 is the only option that stays cleanly inside the README-declared boundary AND avoids socket-mounting. The PGScatalog maintainers flag conda as "last resort" for HPC scenarios where env materialisation is slow + flaky across many cluster nodes; for our single-host PoC the trade-off is favourable. The materialised envs land on the bind-mounted volume, so they survive container restarts + are `refs verify`-able + count toward the reference-data footprint, not the image footprint.

## Acceptance Criteria

Each maps to one or more tests under the phase plans.

- [ ] **AC1**: `docker run --rm genomeclaw/toolkit:<tag> nextflow -version` returns a Nextflow version `>= 23.10.0` (pgsc_calc's documented minimum).
- [ ] **AC2**: `docker run --rm genomeclaw/toolkit:<tag> java -version` returns a JRE 17+ version (Nextflow's minimum + matches the toolkit pin).
- [ ] **AC3**: `docker run --rm genomeclaw/toolkit:<tag> mamba --version` returns a mamba version (required by `pgsc_calc -profile conda` to materialise per-process scoring envs at first run).
- [ ] **AC4**: `docker run --rm genomeclaw/toolkit:<tag> ls /opt/pgsc_calc/main.nf` confirms the `pgsc_calc` pipeline source is pre-warmed inside the image (no first-run network hit to fetch it; deterministic from image hash).
- [ ] **AC5**: `docker run --rm genomeclaw/toolkit:<tag> nextflow run pgscatalog/pgsc_calc --version` resolves through the pre-warm cache + returns the pinned `pgsc_calc` version.
- [ ] **AC6**: `genomeclaw host doctor` adds a `prs_runtime_ready` section that probes `nextflow -version`, `java -version`, `mamba --version`, and the `/opt/pgsc_calc/main.nf` pre-warm. Informational; matches the `ancestry_ready` pattern from Plan 1 — does not change exit code.
- [ ] **AC7**: Image size growth ≤ 400 MB (Nextflow JAR ~50 MB + OpenJDK 17 JRE ~200 MB + mamba install ~50 MB + pgsc_calc pipeline source ~few MB). README's "designed for" section notes the new bundling.
- [ ] **AC8**: A real-data smoke against the project owner's host runs `genomeclaw pipeline pgs-compute --pgs PGS000018 --vcf <NEBULA_VCF> ...` end-to-end against `-profile conda` and produces a real `pgs_scores` row + matching `findings` row. First-run env materialisation lands at `reference/nextflow-cache/conda/` and persists across container restarts. This is the meta-plan Stage 3 integration-smoke gate.

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — `pgsc_calc` reads the user's VCF read-only via the bind-mounted `raw/` (or `derived/<run-id>/normalized.vcf.gz`); writes only into `_scratch/pgsc_calc_work/<run-id>/` and the derived `pgs_scores` row. Unchanged by this plan.
- **INV-D002** Sandbox Is Bioinformatics-Free — these binaries land in the **toolkit** image, not the agent **sandbox** image. The sandbox stays free of pipeline runtimes per existing invariant.
- **INV-P001** Privacy Default — `pgsc_calc` itself fetches per-PGS scoring weights from `pgscatalog.org` at compute time. This egress is install-time-consented via the user invoking `genomeclaw pipeline pgs-compute` / agreeing to agent-driven PRS, governed by the Slice E.3 prompt + INV-P001 install model. No always-on egress added by this plan.
- **INV-R001** Rebuildability — image rebuild is deterministic from `Dockerfile + lockfiles`. Pinned tool versions persist in the `pgs_scores.tool_version` provenance column.

## Proposed New Invariants

**None.** The plan delivers on the README's already-declared architecture; no new project-wide rule is needed.

## Technical Requirements

### Source Data Inputs
- None new. The PGS scoring weights flow remains the same (pgsc_calc fetches per-PGS at compute time).

### Derived Outputs
- None new at the data-store level. The toolkit image itself is the derived artifact of this plan.

### Schema / Migration Impact
- None.

### Pipeline / Workflow Impact
- `genomeclaw pipeline pgs-compute` and the Slice E.3 async orchestrator now work on a fresh `host setup` host without manual install — first PGS compute pays a one-time ~5-10 min env-materialisation tax; subsequent computes hit the cache.
- Nextflow `work/` directory: directed at `_scratch/pgsc_calc_work/<run-id>/` so it shares the scratch lifecycle + `INV-D003` (heavy scratch separated from authoritative outputs).
- `NXF_HOME` set to `/mnt/genomeclaw/reference/nextflow-cache/` so the auto-pulled pipeline metadata + Nextflow's own state persist on the bind-mounted volume.
- `NXF_CONDA_CACHEDIR` set to `/mnt/genomeclaw/reference/nextflow-cache/conda/` so the per-process scoring envs (plink2 + plink + R + Bioconductor packages, etc.) materialise once + persist across container restarts.

### Agent / UX Impact
- No new agent-visible tool. The agent's PGS-compute flow (Slice E.3) is the consumer and is unchanged.

### External Dependencies (in the image)
- **Nextflow** — single Java JAR; install via `curl -s https://get.nextflow.io | bash`; pin via `NXF_VER` env to a release ≥ 23.10.0 (pgsc_calc's documented minimum).
- **OpenJDK 17 JRE** — installed via micromamba into the existing `/opt/conda` env (matches the Stage `bio` pattern). Nextflow needs Java 17+ for current releases.
- **mamba** — installed into `/opt/conda` so `pgsc_calc -profile conda` can shell out to it for env materialisation. Already present in some forms (the image's `/opt/conda` came from the micromamba base) but mamba may not be on PATH explicitly — add it.
- **`pgsc_calc` pipeline source** — `nextflow pull pgscatalog/pgsc_calc -r <tag>` during Stage 1c bakes the pipeline DSL into `/opt/pgsc_calc/`. Pin to `v2.2.0` (latest stable as of 2026-05-17).

### External Dependencies (deferred to first-run materialisation under reference/nextflow-cache/conda/)
- **plink2**, **plink**, **R + Bioconductor** — `pgsc_calc` declares the per-process conda envs in its own `modules/` tree; Nextflow materialises them at first run. We do NOT bake these in. The materialised envs become reference data, governed by `INV-R001` (rebuildable from `Dockerfile + pinned pgsc_calc release tag`).

## Privacy & Safety Considerations

- **Boundary scan**: Pulls during image build — Nextflow installer, plink binaries, R packages. All happen at image-build time on a CI host or developer machine, not at runtime on the user's host. The user pulls the pre-built image from GHCR (or builds locally).
- **Default-off remote calls**: At runtime, the only new egress is `pgsc_calc`'s per-PGS weight fetch from `pgscatalog.org`, governed by INV-P001 install-time consent. No new always-on egress.
- **Redaction surface**: N/A — no PII flows through the new binaries.
- **Clinical escalation**: Indirect. The Slice E.3 PRS-decline pattern (INV-C001 v1.7) governs which PRS computes actually surface to the user.

## Out of Scope

- **Reference data setup** (1000G + HGDP panels, scoring weights cache). Sibling plan [`prs-reference-bootstrap`](../prs-reference-bootstrap/).
- **Singularity / Apptainer / podman / Docker backends.** `-profile conda` is the chosen backend per the profile-decision section above; alternative backends would re-introduce socket-mount / DinD / binary-install complexity this plan deliberately avoids.
- **Pre-baking plink2 / plink / R + Bioconductor in the image.** Deferred to first-run materialisation under `reference/nextflow-cache/conda/` (governed by Nextflow's per-process env management). Pre-baking would fork pgsc_calc's own env definitions + would have to track upstream changes manually.
- **GPU acceleration.** Not relevant to `pgsc_calc` workloads.
- **`pgsc_calc` v3+ migration.** Pin to v2.2.0; major-version upgrades are a follow-up.
- **Outside-call tools beyond `pgsc_calc`.** Cyrius (Slice D) is governed by the same image-bundling principle but lives in its own plan.

## Dependencies

- [`prs-reference-bootstrap`](../prs-reference-bootstrap/) provides the ancestry data this runtime consumes. The two plans are independent at the code level and can ship in parallel; an end-to-end smoke needs both.

## Open Questions

- [x] **Q1 (resolved)**: Image size budget. Revised to ~400 MB (Nextflow + JRE 17 + mamba + pgsc_calc source); plink2 + R + Bioconductor are deferred to first-run materialisation on the volume, not baked in.
- [x] **Q2 (resolved)**: Nextflow pipeline cache location. Bind-mount to `reference/nextflow-cache/` via `NXF_HOME` env so auto-pulled pipeline + materialised conda envs persist + are host-visible.
- [x] **Q3 (resolved)**: Nextflow version. Pin to ≥ 23.10.0 per pgsc_calc's documented minimum. Pick a concrete recent release (e.g. `24.10.x` LTS); confirm against `pgsc_calc` v2.2.0's nextflow.config at image-build time.
- [x] **Q4 (resolved)**: Pin `pgsc_calc` call-side via `nextflow run pgscatalog/pgsc_calc -r v2.2.0`; record the revision tag in the wrapper's `params_json` provenance column.
- [ ] **Q5**: Dual-arch image build (`linux/amd64` + `linux/arm64`). Project owner runs Apple Silicon via Colima. Without arm64, x86 emulation tanks `pgsc_calc` runtime by 3-5x — but more critically, the first-run conda env materialisation downloads arch-specific binaries, so arm64 vs amd64 ALSO affects whether the cached envs are reusable across hosts. Recommendation: arm64-native build required for the project owner's host; amd64 build optional for CI / Linux deployments.
- [ ] **Q6**: Does `nextflow pull` at image-build time require network access to GitHub + Conda Forge? If image builds run offline, defer the pre-warm to first-container-start instead (background warm-up hook). Recommendation: keep at image-build time for deterministic-from-hash image; document the network requirement for image builds.

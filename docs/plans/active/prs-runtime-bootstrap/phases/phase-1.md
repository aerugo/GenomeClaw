# Phase 1: Dockerfile `prs-runtime` Stage + Doctor Readiness

**Status**: In Progress
**Goal**: Build `genomeclaw/toolkit:<tag>` carrying Nextflow + JRE 17 + mamba + pre-warmed `pgsc_calc` pipeline source so `pgsc_calc -profile conda` materialises plink2/plink/R/Bioconductor on first run into a bind-mounted conda cache. Add `host doctor`'s `prs_runtime_ready` informational section.

---

## Invariants Enforced in This Phase

- **INV-D002** Sandbox Is Bioinformatics-Free — already covered by the existing [test_invD002_sandbox_image_no_bio_binaries.py](../../../../packages/toolkit/tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py) (lines 50-54 explicitly list `pgsc_calc` and `nextflow` as forbidden in the sandbox image). No new regression-guard test needed; we verify the existing one still passes after this phase lands.
- **INV-R001** Rebuildability — the image is deterministic from `Dockerfile + pinned tool versions + pinned pgsc_calc release tag` baked into the Stage 1c invocation. Materialised conda envs at `reference/nextflow-cache/conda/` are reproducible from the pinned pgsc_calc release.

---

## Split: Code-Authorable vs Build-Verification

This phase has two natural sub-divisions because the image-build step needs Docker on the project owner's host:

### Sub-phase 1.A — Code authoring (no Docker required)

Author the changes blind from a regular development host. All TDD that doesn't need a built image happens here.

1. **Dockerfile `prs-runtime` stage** — additive; doesn't break the existing `bio` / `vep` / `vep-plugins` / `pybuild` / `runtime` stages
2. **`_versions.py` pin constants** — pure Python
3. **`needs_prs_runtime` pytest marker** — pyproject.toml + conftest.py auto-skip
4. **`doctor.py` `_collect_prs_runtime_ready`** — informational section, same shape as `ancestry_ready`
5. **2 doctor tests** — pure Python; stubbed-runner; no image required
6. **2 image-level smoke tests** — `needs_prs_runtime`-marked; auto-skip until the project owner builds + sets `GENOMECLAW_TOOLKIT_PRS_IMAGE`
7. **`prep/pgs.py` argv update** — add `-profile conda` + `-r v2.2.0` + `NXF_HOME` / `NXF_CONDA_CACHEDIR` env contract documentation
8. **README size note**

### Sub-phase 1.B — Build verification (project owner's host)

1. `docker buildx build --platform linux/arm64 -t genomeclaw/toolkit:prs-phase1 packages/toolkit/`
2. `docker image inspect genomeclaw/toolkit:prs-phase1` — confirm size delta ≤ 400 MB
3. `export GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:prs-phase1`
4. `uv run pytest packages/toolkit/tests/integration/test_toolkit_image_prs_runtime.py -v` — image-level smoke runs against the built image
5. `uv run pytest packages/toolkit/tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py` — INV-D002 regression sweep against the sandbox image; the existing test should still pass (sandbox is unchanged, but we verify nothing leaked)

Sub-phase 1.B feeds back into 1.A if version pins / Dockerfile shape fail.

---

## TDD Steps

### Step 1.1 — Doctor section (pure Python TDD)

Append to `packages/toolkit/tests/integration/test_doctor.py`:

1. **`test_doctor_reports_prs_runtime_ready_when_stubbed_runner_returns_versions`** — stub the doctor's subprocess runner to return canned `nextflow -version`, `java -version`, `mamba --version` outputs + assert `report["prs_runtime_ready"]["status"] == "ready"`.

2. **`test_doctor_reports_prs_runtime_missing_when_nextflow_unreachable`** — stub the runner to return non-zero for `nextflow -version`; assert `report["prs_runtime_ready"]["status"] == "missing"` and the `fix` field names the install path (toolkit image rebuild).

RED → GREEN: implement `_collect_prs_runtime_ready(runner)` in `prep/doctor.py` paralleling `_collect_ancestry_ready` + `_collect_colima`. Returns one of `{"status": "ready", "nextflow_version": <str>, "java_version": <str>, "mamba_version": <str>, "pgsc_calc_prewarm": <str>}` or `{"status": "missing", "missing": [<str>...], "fix": <str>}`.

Wire into the `doctor()` return dict alongside `ancestry_ready`.

### Step 1.2 — Image-level smoke tests (RED until 1.B runs)

Create `packages/toolkit/tests/integration/test_toolkit_image_prs_runtime.py`:

3. **`test_toolkit_image_carries_nextflow_at_minimum_version`** — `docker run --rm $GENOMECLAW_TOOLKIT_PRS_IMAGE nextflow -version` exits 0; output contains a version ≥ 23.10.0.

4. **`test_toolkit_image_carries_jre_17_or_later`** — `docker run --rm $GENOMECLAW_TOOLKIT_PRS_IMAGE java -version` exits 0; output contains a JRE version ≥ 17.

5. **`test_toolkit_image_carries_mamba_on_path`** — `docker run --rm $GENOMECLAW_TOOLKIT_PRS_IMAGE mamba --version` exits 0.

6. **`test_toolkit_image_pgsc_calc_pipeline_prewarmed`** — `docker run --rm $GENOMECLAW_TOOLKIT_PRS_IMAGE ls /opt/pgsc_calc/main.nf` exits 0.

All four marked `@pytest.mark.needs_prs_runtime`; auto-skipped when `GENOMECLAW_TOOLKIT_PRS_IMAGE` env var is unset.

### Step 1.3 — Dockerfile + pin GREEN (no test feedback until 1.B)

1. Add `prs-runtime` build stage to the toolkit Dockerfile:
   ```dockerfile
   FROM mambaorg/micromamba:${MAMBA_TAG} AS prs-runtime
   USER root
   RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
       && rm -rf /var/lib/apt/lists/*
   ARG JRE_VERSION=17
   ARG MAMBA_PKG=mamba
   ARG NEXTFLOW_VERSION
   ARG PGSC_CALC_VERSION=v2.2.0
   RUN micromamba install -y -n base -c conda-forge \
           "openjdk=${JRE_VERSION}" \
           "${MAMBA_PKG}" \
       && micromamba clean -a -y
   ENV PATH="/opt/conda/bin:${PATH}"
   ENV NXF_VER=${NEXTFLOW_VERSION}
   RUN curl -fsSL https://get.nextflow.io | bash \
       && mv nextflow /opt/conda/bin/nextflow
   # Pre-warm pgsc_calc pipeline source so first user run is offline + deterministic.
   # Cache target deliberately separate from runtime NXF_HOME (which will be
   # bind-mounted to the user's reference volume).
   ENV NXF_HOME=/opt/nextflow-build-warm
   RUN nextflow pull pgscatalog/pgsc_calc -r ${PGSC_CALC_VERSION} \
       && cp -r $NXF_HOME/assets/pgscatalog/pgsc_calc /opt/pgsc_calc \
       && rm -rf $NXF_HOME
   ```
2. In the final `runtime` stage, `COPY --from=prs-runtime /opt/conda /opt/conda` is already in place via Stage `bio` (`/opt/conda` is the same micromamba env layer). Need to verify the layered COPY merges cleanly OR move the prs-runtime additions INTO the `bio` stage's micromamba install line.

   **Decision**: merge `nextflow + openjdk + mamba` into the `bio` stage's micromamba install line; do the `nextflow pull` step AFTER the env install in a new layer. Avoids the multi-COPY merge problem. Pre-warmed `pgsc_calc` copies via a separate `COPY --from=...` from a thin Debian intermediate (or just do the pull in `bio` and `COPY --from=bio /opt/pgsc_calc ...` in `runtime`).

   Re-revise on first iteration of sub-phase 1.B if bioconda resolution fails.

3. Add to `_versions.py`:
   ```python
   PRS_RUNTIME_VERSIONS = {
       "nextflow": "24.10.0",   # pgsc_calc requires ≥ 23.10.0; 24.10.x is a current stable
       "jre": "17",
       "mamba": "1.5.x",        # micromamba conda-forge pin
       "pgsc_calc": "v2.2.0",   # PGScatalog/pgsc_calc release tag, latest stable as of 2026-05-17
   }
   ```

### Step 1.4 — Pgs wrapper argv update + Pytest marker registration

1. `prep/pgs.py` `_build_pgsc_calc_argv` — add `-profile conda` + `-r v2.2.0` to the argv list. Document the `NXF_HOME` / `NXF_CONDA_CACHEDIR` env contract in the docstring.
2. `pyproject.toml` — add `needs_prs_runtime` marker; same shape as `needs_sandbox`.
3. `tests/conftest.py` — extend `pytest_collection_modifyitems` to auto-skip `needs_prs_runtime` tests when `GENOMECLAW_TOOLKIT_PRS_IMAGE` env var is unset OR `docker` is not on PATH.

### Step 1.5 — REFACTOR

- Verify the existing wrapper tests in [test_pgsc_calc_wrapper.py](../../../packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py) still pass after the `_build_pgsc_calc_argv` argv update (they assert `--run_ancestry` is present; the new `-profile conda` + `-r v2.2.0` additions are additive). Update assertions if needed.
- `ruff check` + `ruff format` clean on all touched files.
- Full suite re-run: confirm no regressions in the 602-pass baseline + 2 new doctor tests (the 4 image-level tests stay skipped).

---

## Files

### MODIFY

| File | Change |
|------|--------|
| `packages/toolkit/Dockerfile` | Add `prs-runtime` stage (or merge into `bio`) — Nextflow + JRE 17 + mamba + pre-warmed pgsc_calc source |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` | Add `PRS_RUNTIME_VERSIONS` constants |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | Add `_collect_prs_runtime_ready` + wire into `doctor()` report dict |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | Add `-profile conda` + `-r v2.2.0` to `_build_pgsc_calc_argv`; document NXF env contract |
| `packages/toolkit/pyproject.toml` | Register `needs_prs_runtime` marker |
| `packages/toolkit/tests/conftest.py` | Auto-skip `needs_prs_runtime` tests when `GENOMECLAW_TOOLKIT_PRS_IMAGE` unset |
| `packages/toolkit/tests/integration/test_doctor.py` | +2 tests for `prs_runtime_ready` (stubbed runner; no image) |
| `packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py` | Adjust argv assertions if the new flags are checked |
| `README.md` | Note ~400 MB image growth + new bundling |

### CREATE

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/integration/test_toolkit_image_prs_runtime.py` | +4 image-level smoke tests; skipped unless `GENOMECLAW_TOOLKIT_PRS_IMAGE` is set |

---

## Verification

### Sub-phase 1.A (this session)
```bash
# Pure-Python TDD — no image needed
uv run pytest packages/toolkit/tests/integration/test_doctor.py -k prs_runtime -v
uv run pytest packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py -v
uv run pytest packages/toolkit/tests  # full suite regression
uv run ruff check packages/toolkit
uv run ruff format --check packages/toolkit
```

### Sub-phase 1.B (project owner's host with Docker)
```bash
# Build
docker buildx build --platform linux/arm64 \
    -t genomeclaw/toolkit:prs-phase1 \
    packages/toolkit/

# Smoke
export GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:prs-phase1
uv run pytest packages/toolkit/tests/integration/test_toolkit_image_prs_runtime.py -v

# INV-D002 regression sweep (sandbox image stays bio-free)
export GENOMECLAW_SANDBOX_IMAGE=<sandbox-tag>
uv run pytest packages/toolkit/tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py -v

# Image size delta
docker images genomeclaw/toolkit:prs-phase1
```

---

## Completion Criteria

### Sub-phase 1.A
- [ ] All sub-phase 1.A tests pass (pure Python + skipped image tests)
- [ ] `ruff check` + `ruff format` clean
- [ ] Full toolkit test suite still green (no regressions in the Plan 1 baseline of 602 pass / 99 skip + 2 new doctor tests = 604 pass / 99 skip + 4 image tests skipped pending 1.B)
- [ ] Existing INV-D002 sandbox-image test still passes (sandbox unchanged)
- [ ] `prep/pgs.py` argv records `-profile conda` + `-r v2.2.0`; provenance trail in `pgs_scores.params_json` captures both
- [ ] Sub-phase 1.A code review

### Sub-phase 1.B (project owner)
- [ ] Image build succeeds for `linux/arm64` (and ideally `linux/amd64`)
- [ ] Image size delta ≤ 400 MB
- [ ] All 4 image-level smoke tests pass with `GENOMECLAW_TOOLKIT_PRS_IMAGE` set
- [ ] `nextflow run pgscatalog/pgsc_calc --version` resolves through the pre-warm cache (no GitHub fetch)
- [ ] Sub-phase 1.B observations recorded in `work-notes.md`

### Both green
- [ ] Phase status updated to **Complete** in `development-plan.md`, `work-notes.md`, and meta-plan progress tracking
- [ ] Meta-plan Stage 2 marked ready to move to Stage 3 (cross-plan integration smoke)

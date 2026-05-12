# MVP — Work Notes

**Feature**: end-to-end genome → agent loop
**Started**: 2026-05-06
**Branch**: `feature/mvp` (target — not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom. Each session opens with a context-review block.

### 2026-05-06 — Plan authored

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) v1.4 — confirmed seven invariants and their post-lifestyle-update shape.
- Re-read [docs/reference/architecture.md](../../reference/architecture.md) — confirmed verified deployment topology and endpoint sketch.
- Re-read [docs/reference/grand-plan.md](../../reference/grand-plan.md) — confirmed Horizons 1–3 (and a slice of Horizon 6 for lifestyle) are the MVP scope.
- Re-read [docs/reference/user-stories.md](../../reference/user-stories.md) — Stories 1, 2, 4, 6, 9 are the user journeys the MVP must deliver.

**Applicable Invariants for the plan as a whole**: all seven (`INV-D001`, `INV-D002`, `INV-E001`, `INV-P001`, `INV-P002`, `INV-R001`, `INV-C001`).

**Key Insights**:
- The plugin scaffolding under `packages/nemoclaw-plugin/` is ready; the host-side toolkit is the bulk of the MVP work.
- Live-testing the OpenClaw plugin SDK's tool-return shape (Q2) is gated on Phase 5; until then the v0 `GENOMECLAW_JSON:` text-encoding is the default.
- One lifestyle finding (*CYP1A2* / caffeine) is enough to prove the lifestyle track end-to-end; broader lifestyle work is Horizon 6.

**Completed Today**:
- [x] [spec.md](spec.md) authored
- [x] [development-plan.md](development-plan.md) authored — 7 phases, all invariants mapped to phases
- [x] [phases/phase-1.md](phases/phase-1.md) authored

**Decisions Made**:
- 7 phases (not 9). Tight enough to deliver, loose enough that each phase has a single clear theme.
- Phase 1 is just scaffolding — no genome work, no invariant assertions beyond "the test infrastructure runs."
- Phase 6 ships *one* lifestyle finding (*CYP1A2*); broader lifestyle catalog is post-MVP.

**Blockers / Issues**: none yet.

**Next Steps**:
1. Land Phase 1: scaffold `packages/toolkit/`, write the smoke test, confirm `uv run pytest` passes on a fresh clone.
2. Set up CI workflow.
3. Confirm with project owner that the chosen Python toolchain (`uv`) and test runner (`pytest`) are acceptable before implementation.

### 2026-05-08 — Phase 1 implemented

**Context Review Completed**:
- Re-read [phases/phase-1.md](phases/phase-1.md) — confirmed scope: scaffolding only, four smoke tests, no invariant assertions yet.
- Confirmed `uv 0.6.10` available locally; `pyproject.toml` requires Python `>=3.11`.

**Applicable Invariants for this session**: none (Phase 1 is foundations only). Test naming convention `test_invXxxx_*.py` reserved under `tests/invariants/` for later phases.

**Completed Today**:
- [x] Wrote `tests/test_smoke.py` covering the four cases from the phase plan.
- [x] Confirmed RED: 4 failures, all for the intended reasons (missing module, missing console script, missing subpackages, missing category dirs).
- [x] Created `packages/toolkit/pyproject.toml` (uv + hatchling, console-script `genomeclaw-prep`, ruff config).
- [x] Created `src/genomeclaw_toolkit/{__init__,cli}.py` and the three subpackage `__init__.py` stubs.
- [x] Created the seven first-class test-category packages.
- [x] Wrote `packages/toolkit/README.md`.
- [x] Confirmed GREEN: `uv run pytest -q` → 4 passed; `ruff check` clean; `ruff format` clean after a single auto-format pass.
- [x] Wrote `.github/workflows/test.yml` running pytest + ruff on push/PR.

**Decisions Made**:
- `cli` is a single-file module (`cli.py`), not a subpackage. The phase plan listed both shapes; the test only requires `import genomeclaw_toolkit.cli`, which works either way. Single file matches the actual content (one `main` + one `build_parser`).
- Subcommands without handlers exit non-zero. The plan permits printing help and exiting 0; choosing exit 2 instead so a Phase-2-onward invocation against this build fails loudly.
- Pinned CI to Python 3.11 to match the lower bound. Local dev uses whatever `uv` picks (3.13.1 here).
- `uv.lock` committed.

**Blockers / Issues**: none.

**Next Steps**:
1. Phase 2 work — the project owner has flagged that there is no BAM/CRAM available in `data/`; this blocks the BAM-immutability test (case 21) and the `coverage_qc` integration tests against real data. Phase 2's fixtures are explicitly synthetic (case-20 fixture is a synthetic tiny BAM the test will build), so the missing real BAM/CRAM is **not** a Phase 2 blocker. Real-genome end-to-end run against the project owner's BAM is Phase 7 only — and that one is genuinely blocked until a BAM/CRAM lands in `data/`.
2. Author Phase 2 RED tests next session (per plan, Phase 2 lands 21 cases including bcftools/mosdepth coverage).

### 2026-05-08 — Decision Taken: package toolkit + bio binaries as one Docker image

**Context Review Completed**:
- Survey of [INVARIANTS.md](../../reference/INVARIANTS.md), [architecture.md](../../reference/architecture.md), [spec.md](spec.md), and the completed `poc-pipeline-recommendations` plan: no prior Decision Taken on host-side packaging. Architecture.md described the host as "any Linux/macOS environment where the standard bioinformatics tools install" but did not specify *how* they are installed.
- Confirmed `INV-D002` only forbids bio binaries inside the **sandbox** image; it places no constraint on host packaging.

**Trigger**: Phase 2 needs `bcftools` ≥ 1.20, `mosdepth` ≥ 0.3.x, and `samtools` on PATH. None were installed locally. Asking the project owner whether to install via brew surfaced the broader question: "should the host service ship as a Docker image?" Yes.

**Decision Taken**: package `genomeclaw-prep` + `genomeclaw-service` + the pinned bio binaries (`bcftools`, `mosdepth`, `samtools`, `htslib`, and later VEP / Cyrius / `pgsc_calc` / PharmCAT) into a single host image `genomeclaw/toolkit:<tag>`. Reference data (VEP cache, AlphaMissense, gnomAD, PGS Catalog weights) stays on the bind-mounted `/mnt/genomeclaw/reference/` volume — never baked in. A host shim `bin/genomeclaw-prep` wraps `docker run` so users type the same command across environments.

**Rationale**:
- Pinned, reproducible tool versions strengthen `INV-R001`. `manifest.json` records the image digest in addition to per-tool versions.
- macOS, Linux, and CI all run the same image — no per-host install drift.
- Phase-2 RED tests can land on a clean machine without `brew install`.
- Image size stays modest because heavy reference data is bind-mounted, not copied in.

**Invariant Impact**:
- `INV-D002` unaffected (sandbox image is a separate Phase-5 artifact).
- `INV-R001` strengthened (pinned tool versions + image digest).
- `INV-D001` enforced at the OS layer by the `:ro` bind-mount on `raw/`.

**Implementation**:
- [packages/toolkit/Dockerfile](../../../packages/toolkit/Dockerfile) — three stages: `bio` (micromamba + bioconda for bcftools/mosdepth/samtools/htslib), `pybuild` (uv sync against pyproject.toml/uv.lock), `runtime` (python:3.11-slim with both copied in).
- [packages/toolkit/.dockerignore](../../../packages/toolkit/.dockerignore) — trims build context.
- [bin/genomeclaw-prep](../../../bin/genomeclaw-prep) — host shim. Honors `GENOMECLAW_IMAGE`, `GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, `GENOMECLAW_OFFLINE` (passes `--network none`), `GENOMECLAW_NATIVE` / `GENOMECLAW_NO_DOCKER` (bypass to host venv), `GENOMECLAW_DEBUG` (echo the docker invocation).
- [.github/workflows/test.yml](../../../.github/workflows/test.yml) — second job builds `genomeclaw/toolkit:ci` and runs `pytest -m needs_bio` inside it. Tolerates exit 5 ("no tests collected") until Phase 2 lands `needs_bio` tests.
- [packages/toolkit/pyproject.toml](../../../packages/toolkit/pyproject.toml) — `needs_bio` pytest marker registered.
- [docs/plans/active/mvp/development-plan.md](development-plan.md) — Decision Taken #10 added.
- [docs/plans/active/mvp/phases/phase-2.md](phases/phase-2.md) — Verification block rewritten to use the image (or shim); Files table extended with the image-related artifacts; the "tests that need real bcftools/mosdepth use the `needs_bio` marker" discipline documented.
- [docs/reference/architecture.md](../../reference/architecture.md) — new "Host-side packaging — `genomeclaw/toolkit` Docker image" section; component blurbs for `genomeclaw-prep` and `genomeclaw-service` updated.

**Verification** (all green):
- `docker build --tag genomeclaw/toolkit:dev packages/toolkit` → `Successfully built`. Image size 586 MB.
- `docker run --rm --entrypoint bcftools genomeclaw/toolkit:dev --version` → `bcftools 1.21 / Using htslib 1.21`.
- `docker run --rm --entrypoint mosdepth genomeclaw/toolkit:dev --version` → `mosdepth 0.3.10`.
- `docker run --rm --entrypoint samtools genomeclaw/toolkit:dev --version` → `samtools 1.21`.
- `docker run --rm genomeclaw/toolkit:dev` → CMD prints `genomeclaw-prep --help` banner.
- `bin/genomeclaw-prep --help` → routes through `docker run`, prints banner, rc=0.
- `GENOMECLAW_NATIVE=1 ... bin/genomeclaw-prep --help` → resolves to the host venv's `genomeclaw-prep`, rc=0.
- `GENOMECLAW_NATIVE=1 PATH=/usr/bin:/bin bin/genomeclaw-prep --help` → fails cleanly with rc=127 and an actionable message.

**Decisions Made**:
- Bioconda (via `mambaorg/micromamba`) for the bio binaries; `python:3.11-slim` runtime base so the uv venv's interpreter symlinks resolve.
- Image digest will land in `manifest.json` alongside per-tool versions (Phase 2 deliverable).
- `bin/genomeclaw-service` shim is deferred to Phase 5 when the service exists.
- The shim **does not** force `--network none` by default — `genomeclaw-prep fetch` legitimately egresses. Users opt into `GENOMECLAW_OFFLINE=1` for paranoid local-only runs.

**Blockers / Issues**: none.

**Next Steps**:
1. Resume Phase 2 RED tests against the new image-based flow.
2. Phase 2's manifest writer must capture the image digest (`docker image inspect --format '{{.Id}}' genomeclaw/toolkit:dev`) when running inside Docker; if running native (no `/.dockerenv`) it falls back to per-tool versions only.

### 2026-05-08 — Phase 2 sub-phase 2A starts: pure-Python foundation

**Context Review Completed**:
- Re-read [phases/phase-2.md](phases/phase-2.md) — confirmed 21 test cases, schema v0.1, four-mount discipline, image-based verification flow.
- Re-read [INVARIANTS.md](../../reference/INVARIANTS.md) — `INV-D001`, `INV-R001` are the two enforced in Phase 2.
- Re-read [.claude/agents/bioinformatics-pipeline.md](../../../.claude/agents/bioinformatics-pipeline.md) — confirmed core principles: source files authoritative, derived stores reproducible, provenance structural-not-annotational, determinism by default.
- Re-read the [storage-scratch-layout plan](../storage-scratch-layout/) — confirmed `/mnt/genomeclaw/work` is wired up and Story 1 Step 0 verified end-to-end against the project owner's actual genome.

**Applicable Invariants**:
- **INV-D001**: source files unchanged after `ingest`. The pure-Python pieces in 2A don't touch source files; this invariant lands properly in 2C with `bcftools` / `mosdepth` integration.
- **INV-R001**: provenance columns + manifest tool-version pinning + schema-version recording. Sub-phase 2A creates the **schema definitions** for these (Pydantic models + canonical column-name constants); 2C populates them.

**Sub-phase strategy** — Phase 2 is too big for a single session. Slicing it into:
- **2A** (this session): pure-Python foundation. `prep/run_id.py` + `prep/reference_build.py` + `schemas/{manifest,provenance,coverage_qc}.py`. ~5 test cases. Runs on host venv (no `needs_bio`).
- **2B** (next session): `prep/fetch.py` + mocked-HTTP tests. Cases 14, 15. Pure Python; uses `pytest-httpserver`.
- **2C** (subsequent): `prep/_bcftools.py`, `prep/_mosdepth.py`, `prep/store.py`, `prep/ingest.py` + the bcftools/mosdepth integration tests + synthetic fixture generation. Most of the remaining cases. Tests marked `@pytest.mark.needs_bio` and run inside the toolkit image.

**Completed Today (this session — sub-phase 2A only)**:

- [x] Wrote 26 failing tests covering run-id format + CURRENT-symlink atomic update (cases 16, 17, 18 + sanity guards), reference-build sniffer (cases 11, 12 + the bare-list contig variant + decoy-contig tolerance), schema-version + provenance-column constants, and Pydantic models for `Manifest`, `Provenance`, `CoverageQCRow` (the structural part of cases 4, 5, 6, 7).
- [x] Confirmed RED: 26/26 failed with `ModuleNotFoundError: genomeclaw_toolkit.prep.run_id` / `.schemas.manifest` / etc.
- [x] Added `pydantic>=2.7` as a project dependency in [`packages/toolkit/pyproject.toml`](../../../packages/toolkit/pyproject.toml); `uv sync` pulled in `pydantic 2.13.4`, `pydantic-core 2.46.4`, `annotated-types 0.7.0`.
- [x] Implemented [`schemas/__init__.py`](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py) with `SCHEMA_VERSION="v0.1"` and the 7-column `PROVENANCE_COLUMNS` tuple.
- [x] Implemented [`schemas/manifest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/manifest.py) (Pydantic v2; `extra="forbid"`; `BcftoolsStatsSummary` + `ManifestQC` nested; optional `image_digest` field for the inside-Docker case).
- [x] Implemented [`schemas/provenance.py`](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/provenance.py) (`Step` requires `min_length=1` on `inputs`; `StepArtifact` requires SHA256-shaped strings).
- [x] Implemented [`schemas/coverage_qc.py`](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/coverage_qc.py) (Pydantic `CoverageQCRow` + `COVERAGE_QC_COLUMNS` DDL tuple + `coverage_qc_create_table_sql()`; the test enforces model-vs-DDL field-name parity).
- [x] Implemented [`prep/run_id.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/run_id.py) — `generate_run_id(input_sha256, started_at)` + `update_current_symlink(derived_root, run_id)`. The symlink uses a relative target so it survives a moved `derived_root`; the update goes via `os.symlink → os.replace` for POSIX-atomic swap.
- [x] Implemented [`prep/reference_build.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/reference_build.py) — built-in lookup tables for GRCh37 + GRCh38 (autosomes + X/Y/MT under both UCSC `chr*` and Ensembl-style names), `sniff_reference_build(contigs)` returns the build, raises `AmbiguousReferenceBuild` on no-match / contradiction / mixed-build / empty input.
- [x] GREEN confirmed: `uv run pytest -q` → **30 passed in 0.15s** (4 smoke + 26 new). `uv run ruff check .` → All checks passed. `uv run ruff format --check .` → 22 files already formatted.

**Decisions Made (sub-phase 2A)**:

- **Pydantic v2 with `extra="forbid"`** on every model. Strict-by-default; unknown fields are typos; the validator surfaces them at JSON-load time. The Manifest model accepts both BAM and TBI optional inputs so a Phase-2 run can produce a complete manifest even before the BAM-mosdepth path runs.
- **`schemas/__init__.py` exports the constants** (`SCHEMA_VERSION`, `PROVENANCE_COLUMNS`). These are the single source of truth for downstream wrappers and DuckDB writers; a typo becomes a single-place edit.
- **Reference-build sniffer accepts both `chr1`-style (UCSC) and `1`-style (Ensembl) contig names** in the same lookup table, so the same logic handles Nebula's UCSC-style headers and the alternative naming some pipelines emit. Non-canonical contigs (HLA-*, chrEBV, GL000* decoys) are silently ignored — short-read pipelines emit them routinely and they don't identify the build.
- **Ambiguity is structural**: empty contig list → ambiguous; mixed-build contigs → ambiguous; canonical-named-but-length-mismatched → contradicts the build. Each is a clear `AmbiguousReferenceBuild` raise that the ingest pipeline (sub-phase 2C) maps to a clean CLI error with no partial derived store written.
- **`image_digest` lives on the manifest**, not as a separate file. Phase-2 ingest captures it via `docker image inspect --format '{{.Id}}' genomeclaw/toolkit:dev` when running inside Docker; left `None` when running native. Required by the host-image Decision Taken (#10) "image digest in manifest.json" line.

**Blockers / Issues**: none.

**Next Steps**:
1. Sub-phase 2B (next session): `prep/fetch.py` + mocked-HTTP tests (cases 14, 15). Pure Python; uses `pytest-httpserver`. ETA short.
2. Sub-phase 2C: bcftools / mosdepth wrappers + ingest pipeline orchestration + DuckDB store + synthetic fixtures. The bulk of Phase 2's remaining 13 cases. Tests marked `@pytest.mark.needs_bio`, run inside the `genomeclaw/toolkit` image.

### 2026-05-08 — Phase 2 sub-phase 2B: fetch subcommand + CLI wiring

**Context Review Completed**:
- Re-read [phases/phase-2.md](phases/phase-2.md) cases 14, 15, 3 — confirmed mocked-HTTP-only scope; no real network in CI.
- Confirmed `pytest-httpserver` is the standard mock-HTTP library for Python; chose it over `responses` because it actually starts a real local HTTP server (closer to real-network behaviour) and over `httpretty` because the latter monkey-patches the socket layer in ways that interact poorly with other tests.

**Applicable Invariants**:
- **INV-D001**: `fetch` never overwrites an existing version (case 3 / `test_invD001_fetch_does_not_overwrite_existing_version`).
- **INV-P001**: `fetch` is the only egress point in Phase 2; deliberate, user-initiated, scoped to ClinVar / gnomAD / dbSNP. The MD5 sidecar is downloaded alongside so a future offline reanalysis can verify what landed without an additional network call.
- **INV-R001**: the MD5 lands as `<file>.md5` next to the data file; the `<release>` dir is the unit of versioning. Provenance for the *fetch* itself (what URL, when, image digest) lands in Phase 2C's manifest; the MD5 sidecar is the immediate-on-disk identity.

**Completed Today**:
- [x] Wrote 5 failing tests covering case 14 (mocked-MD5-correct fetch writes versioned path), case 15 (mocked-MD5-wrong → `ChecksumMismatch`, no canonical file written), case 3 (pre-existing version → `VersionAlreadyExists`, prior bytes unchanged), unknown-source rejection, missing-release rejection.
- [x] Confirmed RED: 5/5 failed with `ModuleNotFoundError: genomeclaw_toolkit.prep.fetch`.
- [x] Added `pytest-httpserver>=1.0` to dev deps; `uv sync` pulled in `pytest-httpserver 1.1.5` + `werkzeug 3.1.8` + `markupsafe 3.0.3`.
- [x] Implemented [`prep/fetch.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py) — `fetch(source, reference_root, release, base_url=None)`; per-source `_LAYOUTS` dict (ClinVar populated, gnomAD/dbSNP land later); ClinVar default base URL is `https://ftp.ncbi.nlm.nih.gov`; download-to-scratch + MD5 verify + `os.replace`-atomic move; `ChecksumMismatch` and `VersionAlreadyExists` exceptions.
- [x] Wired `fetch` into the CLI ([`cli.py`](../../../packages/toolkit/src/genomeclaw_toolkit/cli.py)) via a new `_add_fetch` helper. The CLI now has a real handler dispatch (`args.handler`); other subcommands fall through to the "not implemented" message until their phases land. Exit codes: `2` for `ValueError` / `VersionAlreadyExists`, `3` for `ChecksumMismatch`, `0` on success.
- [x] GREEN confirmed: `uv run pytest -q` → **35 passed in 0.56s** (4 smoke + 26 sub-phase 2A + 5 sub-phase 2B). `uv run ruff check .` and `uv run ruff format --check .` both clean.
- [x] CLI surface verified: `uv run genomeclaw-prep --help` lists `fetch` with a real description; `uv run genomeclaw-prep fetch --help` shows `--source` / `--release` / `--reference-root` / `--base-url`.

**Decisions Made (sub-phase 2B)**:

- **Phase 2 ships `clinvar` only** in `_LAYOUTS`. The `argparse` `--source` choice list still advertises `gnomad` and `dbsnp` so the help text matches the spec, but invoking either today reaches the `ValueError("unknown source")` path. The gnomAD / dbSNP URL patterns + tests will land at the moment those datasets are first consumed (Phase 2C ingest needs ClinVar; Phase 4 annotate adds gnomAD + dbSNP). Rationale: avoid building up frozen URL patterns we'll be tempted to update without re-testing.
- **`release` is required, no "latest"**. A remote-resolved "what's the latest ClinVar release?" lookup adds a second egress point and a stateful retry/fallback story for nothing — `genomeclaw-prep fetch --source clinvar --release 2026-04` is a one-line CLI invocation the user types deliberately. If we ever want a "latest" affordance, it's a Phase 7+ follow-up.
- **MD5, not SHA256, for the source-of-truth checksum**. NCBI's ClinVar publishes `clinvar.vcf.gz.md5` as the sidecar — using their published checksum format makes the check round-trip with what the user can verify themselves with `md5sum`. The toolkit's *own* SHA256 for provenance lands separately in the manifest at ingest time (Phase 2C); the two are not in conflict.
- **Atomic order: data file first, sidecar second** in the `os.replace` sequence. A reader who sees the sidecar always sees the data. The reverse — "the sidecar exists but the data is still in scratch" — is a never-observed-in-practice state.
- **`base_url` is a test seam, not a CLI flag**. The `--base-url` flag exists for development convenience (mostly for me debugging things against a local mock) but isn't documented as a user-facing knob; the canonical URL is the right default for everyone else.

**Blockers / Issues**: none.

**Next Steps**:
1. Sub-phase 2C: synthesise tiny VCF + BAM fixtures inside the `genomeclaw/toolkit` image (using bcftools/samtools at fixture-prep time); implement `_bcftools.py`, `_bcftools_stats.py`, `_mosdepth.py`, `store.py`, `ingest.py`; the remaining 13 Phase-2 test cases land marked `@pytest.mark.needs_bio` and run inside the image.
2. Verify CI's `toolkit-image` job picks up the new tests once the `needs_bio` marker is non-empty.

### 2026-05-09 — Phase 2 sub-phase 2C-A: DuckDB store + bcftools subprocess wrapper

**Context Review Completed**:
- Re-read [phases/phase-2.md](phases/phase-2.md) — confirmed schema v0.1 layout for the `variants` table + `schema_meta` table + the `coverage_qc` table.
- Confirmed the `needs_bio` test marker scaffolding from sub-phase 2A is wired but not yet exercised.

**Applicable Invariants**:
- **INV-R001**: every `variants` row carries the seven canonical provenance columns; `schema_meta` records `schema_version='v0.1'`; `bcftools` version captured for the manifest's `tools` block.
- **INV-D001**: `bcftools index --tbi` writes its output to a path inside `derived/<run-id>/`, never alongside the source VCF (case 10).

**Completed Today**:
- [x] Added `duckdb>=1.0` to project deps; `uv sync` pulled in `duckdb 1.5.2`.
- [x] Wrote 10 RED tests for [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) covering schema creation, schema_meta versioning, provenance-column declarations, refuse-on-overwrite, provenance-tag stamping on every row, multi-row + empty-input handling, NOT NULL validation, single-tag-per-write enforcement, and `coverage_qc` DDL/model parity. All RED with `ModuleNotFoundError`; GREEN after implementation.
- [x] Implemented [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) — `create_store(path)` writes the three v0.1 tables and seeds `schema_meta`; `ProvenanceTag` dataclass freezes the seven provenance values; `write_variants(store_path, rows, *, tag)` projects domain dicts onto the `_VARIANT_DOMAIN_COLUMNS` tuple, validates NOT NULLs, and bulk-inserts via `executemany`. The single-tag-per-call signature enforces the `INV-R001` "all rows attribute themselves to the same source" promise structurally.
- [x] Wrote 6 RED tests for [`prep/_bcftools.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py) — 3 pure-Python tests for the version-string parser (host venv), 3 `@pytest.mark.needs_bio` tests for real subprocess invocations (image only). All RED with `ModuleNotFoundError`; GREEN after implementation.
- [x] Implemented [`prep/_bcftools.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py) — `parse_version_output(stdout)` returns a `VersionInfo` (program, version, htslib_version) tuple; `bcftools_run(args)` is the thin subprocess wrapper that wraps non-zero exits in `BcftoolsError` with stderr captured; `bcftools_version()` and `bcftools_index_tbi(*, vcf, derived_dir)` are the two named primitives Phase-2 ingest will compose. The `--output` flag on `index` enforces case 10 / `INV-D001`.
- [x] Wrote [`tests/conftest.py`](../../../packages/toolkit/tests/conftest.py) with a `pytest_collection_modifyitems` hook that auto-skips `@pytest.mark.needs_bio` tests when `GENOMECLAW_HAS_BIO != "1"`. Skipping is the contract between the host venv and the image-side test runner.
- [x] Updated [`packages/toolkit/Dockerfile`](../../../packages/toolkit/Dockerfile) `pybuild` stage from `uv sync --frozen --no-dev` to `uv sync --frozen` so `pytest` and friends are available inside the image. Comment notes that the toolkit image is a host-side dev/CI image; `INV-D002`'s "no bio binaries in the sandbox" rule applies only to the Phase-5 sandbox image.
- [x] GREEN confirmed:
  - Host venv: `uv run pytest -q` → **48 passed, 3 skipped** (`needs_bio` auto-skipped).
  - Image: `docker run --rm ... -e GENOMECLAW_HAS_BIO=1 genomeclaw/toolkit:dev pytest -q -m needs_bio` → **3 passed, 48 deselected**.
  - Image full suite: **51 passed** total.
  - `ruff check .` and `ruff format --check .` clean across all sources + tests.

**Decisions Made (sub-phase 2C-A)**:

- **`ProvenanceTag` is a frozen dataclass, not a Pydantic model.** It's an internal handoff between ingest steps and the store writer — no JSON round-trip, no untrusted input. A dataclass keeps the layer thin and avoids the Pydantic import for a value object.
- **`write_variants` takes domain rows as plain `dict[str, Any]`** rather than a Pydantic `VariantRow`. Phase 2 deliberately doesn't normalize variants (Phase 3 does); the row dicts come from a thin VCF-text parser that lands in sub-phase 2C-B. A formal `VariantRow` model becomes useful when annotation columns land in Phase 4.
- **Single tag per write** (signature-enforced). A test (`test_write_variants_uses_same_provenance_tag_on_all_rows`) anchors the convention; mixed-tag inserts would require multiple `write_variants` calls, which is fine.
- **bcftools wrapper is three named primitives, not a `bcftools(*args)` god-function.** `bcftools_run` is the low-level seam; `bcftools_version` and `bcftools_index_tbi` are the named operations Phase 2 actually invokes. Future `bcftools_norm` / `bcftools_stats` modules add their own named functions — keeps the call sites readable + greppable.
- **Dockerfile now ships dev deps.** Image grew negligibly; `pytest` + `pytest-httpserver` + `ruff` are all small. The `needs_bio` test workflow becomes `docker run … pytest -m needs_bio` — same shape as CI's existing `toolkit-image` job.

**Blockers / Issues**: none. The pytest cache warning when running with a read-only bind-mount (`PytestCacheWarning: cache could not write path /work/.pytest_cache/v/cache/nodeids`) is benign; could be muted later by mounting an `--cache-dir=/tmp/...` flag if it becomes annoying.

**Next Steps**:
1. Sub-phase 2C-B (next session): synthesise tiny VCF fixtures (`tiny.vcf.gz`, `tiny-unindexed.vcf.gz`, `tiny-ambiguous.vcf.gz`) at session start using `bcftools view -Oz` inside the image; implement minimal VCF-only `prep/ingest.py` that computes input SHA256, generates the run-id, sniffs the reference build, creates the derived store, calls `bcftools_index_tbi` only when `.tbi` is missing, writes manifest + provenance, and atomically updates `CURRENT`. Lands cases 1, 4, 5, 6, 7, 9, 11, 12, 13, 17, 18 — the bulk of Phase-2 verification minus mosdepth/coverage_qc.
2. Sub-phase 2C-C (after that): synthesise tiny BAM fixture; implement `_mosdepth.py` + `_bcftools_stats.py`; wire into ingest; lands cases 2, 8, 19, 20, 21.

### 2026-05-09 — Phase 2 sub-phase 2C-B-1: minimal VCF reader

**Context Review Completed**:
- Confirmed Phase 2 ingest is single-sample (per spec / phase-2.md). Multi-sample VCFs are out of scope.
- Confirmed Phase 2 stores multi-allelic rows as-is (Phase 3's `bcftools norm` does the splitting).

**Applicable Invariants**:
- **INV-D001**: the reader opens the VCF read-only; no writes to source files.
- **INV-R001**: the reader's row dict shape exactly matches `prep.store.write_variants`'s contract (chrom/pos/id/ref/alt/qual/filter/sample_id/genotype), so a single-tag stamping pass at ingest time covers every row.

**Completed Today**:
- [x] Wrote 12 RED tests covering `read_contigs` (gz + plain VCFs, GRCh38 round-trip with the sniffer, malformed `##contig=` skipping, header-only files) and `iter_variant_rows` (one-dict-per-line shape, `.` → `None` normalisation for ID/QUAL, multi-allelic preservation, GT extraction from any FORMAT position, multi-sample rejection, zero-data-row + sites-only handling).
- [x] Confirmed RED: 12/12 failed with `ModuleNotFoundError: genomeclaw_toolkit.prep._vcf`.
- [x] Implemented [`prep/_vcf.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_vcf.py) — `read_contigs(path)` with regex-based `##contig=<...>` parsing; `iter_variant_rows(path)` streaming-reads VCF data lines into the row-dict shape `prep.store.write_variants` expects; transparent gzip handling via `gzip.open` (works for both vanilla gzip and bgzip on sequential reads).
- [x] GREEN confirmed: `uv run pytest -q` → **60 passed, 3 skipped** (`needs_bio` auto-skipped). `ruff check` and `ruff format --check` clean.
- [x] **Smoke-tested against the project owner's actual Nebula VCF** (`/Volumes/Genome/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz`, 222 MB): `read_contigs` returns 2580 contigs; `sniff_reference_build` correctly identifies it as `grch38`; `iter_variant_rows` streams real variant rows with rsids + genotypes (e.g. `rs1263808954`, `rs546169444`). The reference-build sniffer's "non-canonical contigs are silently ignored" decision from sub-phase 2A was load-bearing — Nebula's VCF carries the standard 25 canonical chromosomes plus 2555 alt/decoy/HLA contigs.

**Decisions Made (sub-phase 2C-B-1)**:

- **`gzip.open`, not `pysam` or `cyvcf2`.** The reader is sequential-only; bgzip's random-access multi-block layout doesn't matter for Phase 2's "stream the whole file once" pass. Pure stdlib avoids pulling in a heavy dep just for header parsing.
- **Single-sample is enforced at the reader, not the ingest layer.** Phase 2's spec is single-sample, and a clear error at the reader catches multi-sample VCFs before ingest spends time computing SHA256 and generating run-ids. The error message names `single-sample` so a grep against the spec finds it instantly.
- **`.` → `None` normalisation at parse time.** Downstream (DuckDB, pydantic) all expect `None` for missing values; doing the normalisation in the reader keeps the rest of the pipeline simple.
- **GT extraction is FORMAT-position-agnostic.** Real-world VCFs sometimes put DP or PL ahead of GT. The reader scans the FORMAT field by name. Matches the project owner's actual Nebula VCF where every site happens to have GT first, but defends against tooling that doesn't.
- **Sites-only VCFs yield rows with `genotype=None`** rather than raising. The reader is permissive; the *ingest* layer (next session) decides whether to refuse them. Keeping policy out of the reader makes it useful for later phases (annotation pre-checks, etc.).

**Blockers / Issues**: none.

**Next Steps**:
1. Sub-phase 2C-B-2 (next session): write `prep/ingest.py` orchestrator that composes `_vcf.read_contigs` → `reference_build.sniff_reference_build` → `bcftools_index_tbi` (if missing) → `store.create_store` → `_vcf.iter_variant_rows` → `store.write_variants` → manifest/provenance JSON write → `update_current_symlink`. Author the synthetic VCF fixtures (`tiny.vcf.gz`, `tiny-unindexed.vcf.gz`, `tiny-ambiguous.vcf.gz`) inside the image. Lands ~10 of the remaining 13 Phase-2 cases.
2. Sub-phase 2C-C: synthetic BAM + `_mosdepth.py` + `_bcftools_stats.py`; wire into ingest; lands the last 5 cases (2, 8, 19, 20, 21).

### 2026-05-09 — Phase 2 sub-phase 2C-B-2: VCF-only ingest orchestrator + real-Nebula smoke

**Context Review Completed**:
- Re-read [phases/phase-2.md](phases/phase-2.md) Implementation Details — confirmed schema v0.1 layout, run-id format, CURRENT-symlink discipline, and the manifest's `tools` block contents (bcftools / python / duckdb / genomeclaw-toolkit).
- Re-read [.claude/agents/bioinformatics-pipeline.md](../../../.claude/agents/bioinformatics-pipeline.md) — confirmed "rebuildability is structural, provenance lives in columns and tables" applies to the orchestrator.

**Applicable Invariants**:
- **INV-D001**: source VCF + .tbi unchanged after ingest. `bcftools_index_tbi` writes its output under `derived/<run-id>/`, not next to source. Tests cases 1, 2, 10.
- **INV-R001**: `manifest.json` carries the four canonical tool versions; `provenance.json` records the ingest step's input identity (path + sha256); the `variants` table's seven canonical provenance columns are stamped via a single `ProvenanceTag` per call. Tests cases 4, 5, 6, 7.

**Completed Today**:
- [x] Wrote 15 RED tests covering all 12 Phase-2 cases the VCF-only path is responsible for: 1, 2 (partial), 4 (populated), 5, 6, 7, 9, 10, 11, 12, 13 (3 sub-cases), 17, 18. Of these, 3 are pure-Python input-validation tests (host venv); 12 are `@pytest.mark.needs_bio` integration tests that exercise the full pipeline against synthetic VCF fixtures built via `bcftools view -Oz` at session scope.
- [x] Implemented [`tests/integration/conftest.py`](../../../packages/toolkit/tests/integration/conftest.py) — three session-scoped fixtures (`tiny_vcf_gz`, `tiny_unindexed_vcf_gz`, `tiny_ambiguous_vcf_gz`) and a per-test `genomeclaw_layout` four-mount tmp dir. Fixtures auto-skip when `GENOMECLAW_HAS_BIO != "1"`.
- [x] Implemented [`prep/_versions.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py) — `collect_tool_versions()` returns the manifest's `tools` block (python / duckdb / genomeclaw-toolkit always; bcftools + htslib when on PATH); `image_digest()` reads `GENOMECLAW_IMAGE_DIGEST` env var (the host shim threads it through later).
- [x] Implemented [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) — single `ingest(*, vcf, reference_dir, derived_root, sample_id)` function that runs the eight-step happy path with `INV-D001` / `INV-R001` discipline. Sample-id from the CLI flag is authoritative for the manifest + variants table; the VCF's `#CHROM` sample column is informational. `AmbiguousReferenceBuild` raises before any output is written, so a bad VCF leaves `derived_root` untouched (case 12).
- [x] Wired `ingest` into the CLI ([`cli.py`](../../../packages/toolkit/src/genomeclaw_toolkit/cli.py)): `--vcf`, `--reference`, `--sample-id`, `--derived-root`. Exit codes: `2` for `FileNotFoundError` / `AmbiguousReferenceBuild`; `0` on success.
- [x] GREEN confirmed:
  - Host venv: `uv run pytest -q` → **63 passed, 15 skipped**.
  - Image: `docker run … pytest -m needs_bio` → **15 passed, 63 deselected**.
  - Combined: 78 toolkit tests, all green.
- [x] **Real-Nebula end-to-end smoke (2026-05-09)** against `/Volumes/Genome/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz` (222 MB, 4.8M variants) via the host shim:
  - `genomeclaw-prep ingest --vcf … --reference … --sample-id MPNRGLQ2K` exited 0, wrote run-id `2026-05-08T22-24-35Z-0ceb0d`.
  - Manifest shape correct: `schema_version: v0.1`, `reference_build_inferred: grch38`, `tools: {python: 3.11.14, duckdb: 1.5.2, genomeclaw-toolkit: 0.0.1, bcftools: 1.21, htslib: 1.21}`, source `vcf_sha256` + `tbi_sha256` recorded.
  - DuckDB store: 4,794,833 rows in `variants`; 1 distinct provenance tag (uniform stamping); `schema_meta.schema_version='v0.1'`.
  - Provenance step trail: one `ingest` step with input identity matching the manifest.
  - **`INV-D001` confirmed against real data**: post-ingest `shasum -a 256` of the source VCF + .tbi matches the manifest's recorded values byte-for-byte.

**Decisions Made (sub-phase 2C-B-2)**:

- **Ingest is one function, not a class.** A single linear flow is the simplest readable shape; future sub-phases append steps (mosdepth, bcftools-stats, normalize, annotate) by inserting calls in sequence and appending to the provenance step trail. A dependency-injected pipeline class would be premature — there's no second consumer of the orchestrator yet.
- **Sample-id from the CLI is authoritative** for both the variants table's `sample_id` column and the manifest's `sample_id` field. The VCF's `#CHROM` sample column is informational only — pipelines often re-tag samples between runs, and the user-supplied id is the version that lands downstream in findings + reports.
- **`bcftools_index_tbi` is a no-op when the source `.tbi` exists.** Per the Phase-2 plan, the source's index is preserved; we only build a new one (under `derived/`) when the source is bgzipped without an index. Both paths still record the index identity (path + sha256) in the manifest so the run is reproducible either way.
- **Ingest computes `_sha256_file(store_path)` for the provenance.json output trail** even on a 93 MB DuckDB file. Slightly redundant on top of the duckdb's own per-row provenance, but the step-trail's input/output identity is the canonical "what did this step produce" record.
- **Real-Nebula smoke is part of the GREEN gate**. The synthetic fixtures (5 rows, ~1 KB) catch correctness bugs but not perf bugs; running against the project owner's actual 222 MB VCF surfaced a serious perf regression (see follow-up below).

**Blockers / Issues**:

- 🔴 **Real-Nebula ingest took 4h09m wall time** for 4.8M variants. Functionally correct (all artifacts + invariants verified), but ~50–100× slower than the operation's intrinsic cost. Root-cause hypotheses: (a) materialising the full 4.8M-row list in Python before `executemany` (likely 3–5 GB peak memory + GC pressure), (b) DuckDB `executemany` with millions of rows is known to be slow vs `COPY FROM` / `Appender`, (c) USB-volume `fsync` on the colima virtiofs round-trip dominating I/O. **Filed as a separate plan**: [`docs/plans/active/ingest-performance/spec.md`](../ingest-performance/spec.md). The MVP plan is unblocked — Phase 2's correctness story is intact — but the user-facing experience needs the perf fix before Phase 7's full-genome demo.

**Next Steps**:
1. Sub-phase 2C-C: synthesise tiny BAM fixture; implement `_mosdepth.py` + `_bcftools_stats.py`; wire into the ingest orchestrator (append `bcftools-stats` and `mosdepth-coverage` provenance steps). Lands the remaining 5 Phase-2 cases (2 partially done, 8, 19, 20, 21).
2. The ingest-performance plan is independent of 2C-C — it can be picked up before, after, or alongside. Recommended sequencing: pause Phase-2 implementation, knock out the perf fix, then resume sub-phase 2C-C against a now-fast pipeline so the synthetic-BAM tests run quickly. (User's call.)

### 2026-05-09 — Ingest-performance plan landed; sub-phase 2C-C unblocked

**Context Review Completed**:
- Re-read [`docs/plans/active/ingest-performance/spec.md`](../ingest-performance/spec.md) and [`development-plan.md`](../ingest-performance/development-plan.md) — confirmed the perf plan's scope (CSV-staging via COPY FROM, streaming from `iter_variant_rows`, `temp_directory` PRAGMA) and the targets (AC1: <10 min on real Nebula; AC2: byte-identical artifact identity).
- Profiled the existing `executemany` path on a 100k synthetic VCF inside the toolkit image: 266.66s — extrapolating exactly to the 4h09m observed on real Nebula.
- Benched `COPY FROM` against the same input: 1.08s — **247× faster**.

**Applicable Invariants (perf plan)**:
- **INV-D001**: source files unchanged. Guarded by the existing `test_invD001_ingest_does_not_mutate_source_vcf` test; the CSV-staging path doesn't open the source for write.
- **INV-R001**: provenance columns + tool versions + schema_version + single-tag-per-write. Guarded by the existing 10 `test_invR001_store.py` + 6 ingest-e2e `INV-R001` tests; no schema change.

**Completed Today (perf plan landed)**:
- [x] [`docs/plans/active/ingest-performance/spec.md`](../../completed/ingest-performance/spec.md) authored (during 2C-B-2 when the perf issue surfaced); all 5 ACs ticked.
- [x] [`development-plan.md`](../../completed/ingest-performance/development-plan.md) + [`work-notes.md`](../../completed/ingest-performance/work-notes.md) + [`phases/phase-1.md`](../../completed/ingest-performance/phases/phase-1.md) authored.
- [x] Profile + benchmark run inside the image; CSV-staging chosen over pandas/pyarrow (stdlib only; no image bloat).
- [x] [`tests/perf/test_invR001_ingest_perf_gate.py`](../../../packages/toolkit/tests/perf/test_invR001_ingest_perf_gate.py) RED at 235s on the existing `executemany` path.
- [x] [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) `write_variants` rewritten to stream rows in 50k-row batches; each batch closes + fsyncs + `COPY FROM`s + deletes its CSV. `PRAGMA temp_directory='<work_dir>/duckdb/'` set on the ingest connection.
- [x] [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) replaced list-materialisation with a `_row_stream()` generator; resolves `work_dir = derived_root.parent / "work"`.
- [x] Existing 10 `test_invR001_store.py` tests threaded with `work_dir=store_path.parent / "work"`.
- [x] **First real-Nebula re-run** on a single-CSV staging path **failed** at line 3.7M with NUL truncation (virtiofs+exFAT 1 GB-streaming-write reliability bug surfaced only on the project owner's actual hardware — synthetic fixtures couldn't reproduce).
- [x] Iterated to **batched** CSV staging (50k rows / ~10 MB per file). Second real-Nebula re-run **succeeded**: **1m 17s** (vs 4h09m baseline = **193× speedup**); 4,794,833 rows, single distinct provenance tag, schema v0.1; manifest's `vcf_sha256` + `tbi_sha256` byte-match the baseline (`INV-D001` re-confirmed).
- [x] All AC checks ticked in spec.md.
- [x] Plan moved to [`docs/plans/completed/ingest-performance/`](../../completed/ingest-performance/).

**Decisions Made (perf plan)**:
- **Batched CSV staging** (50k rows / batch), not single-file. Real-data corruption at ~1 GB streaming writes forced the iteration; the synthetic-fixture tests couldn't catch it. Lesson: real-data smoke as part of the GREEN gate matters.
- **`fsync` between batch write and COPY** is belt-and-braces against virtiofs cache. Cheap; closes the corruption window.
- **Stdlib only** (csv module + DuckDB COPY FROM). pandas / pyarrow deferred until profiling shows a future workflow needs them.
- **`work_dir` is plumbed but the CLI doesn't expose `--work-dir` yet** — derived from `derived_root.parent` works for the shim flow today; explicit flag can land later if needed.

**Blockers / Issues**: none. Sub-phase 2C-C is now unblocked — the BAM ingest tests against synthetic fixtures will run in seconds.

**Next Steps**:
1. Sub-phase 2C-C: synthesise tiny BAM fixture; implement `_mosdepth.py` + `_bcftools_stats.py`; wire into ingest. Lands the remaining 5 Phase-2 cases (2, 8, 19, 20, 21).

### 2026-05-09 — Phase 2 sub-phase 2C-C: BAM coverage + bcftools stats + determinism scaffold; Phase 2 complete

**Context Review Completed**:
- Re-read [phases/phase-2.md](phases/phase-2.md) cases 8, 19, 20, 21 — confirmed scope.
- Re-read [INVARIANTS.md](../../reference/INVARIANTS.md) — `INV-D001` (BAM unchanged after mosdepth) and `INV-R001` (provenance columns on `coverage_qc` rows + `qc.bcftools_stats` block in manifest) are the two enforced.
- Re-read the post-ingest-perf [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) and [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) — confirmed shape ready to absorb BAM/mosdepth steps.

**Applicable Invariants**:
- **INV-D001**: source BAM + .bai unchanged after mosdepth runs (case 21). The wrapper invokes `mosdepth --no-per-base --by <bed> <prefix> <bam>` with read-only intent; the test captures pre/post SHA256s.
- **INV-R001**: `coverage_qc` rows carry the seven canonical provenance columns (case 20 populated form). `manifest.qc.bcftools_stats` carries `ts_tv_ratio` / `n_snps` / `n_indels` (case 19). `provenance.json` gains `bcftools-stats` and `mosdepth-coverage` step entries.

**Completed Today**:
- [x] Wrote 4 RED tests for [`prep/_bcftools_stats.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools_stats.py) — 3 pure-Python parser tests (host venv); 1 needs_bio against `tiny_vcf_gz`. Implemented `parse_stats_output(stdout) → BcftoolsStatsResult` with SN/TSTV section parsing; `bcftools_stats(vcf)` wraps the subprocess invocation. All GREEN.
- [x] Wrote 6 RED tests for [`prep/_mosdepth.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_mosdepth.py) — 3 pure-Python parser tests (host venv); 3 needs_bio integration tests against the synthetic BAM. Implemented `parse_regions_bed(path)` + `run_mosdepth(*, bam, bed, out_prefix)` + `mosdepth_version()`. All GREEN.
- [x] Authored synthetic BAM + BED session-scoped fixtures in [`tests/conftest.py`](../../../packages/toolkit/tests/conftest.py): `tiny_bam` (4 reads on chr17/chr13/chr22 — start of BRCA1, BRCA2, CYP2D6 — sorted + .bai-indexed), `tiny_genes_bed` (4-column BED). Hand-crafted SAM converted via `samtools view -bS | samtools sort | samtools index`. Moved the existing VCF fixtures to top-level conftest at the same time so `tests/provenance/` can consume them.
- [x] Added [`prep/store.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) `write_coverage_qc(store_path, rows, *, tag)` — `executemany` is fine here (~100s of gene rows; the CSV-staging-cliff is at 200k+ rows for variants).
- [x] Extended [`prep/ingest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py) `ingest()` signature with `bam`, `bed`, and `started_at` keyword arguments. The orchestrator now: runs `bcftools_stats(vcf)` → writes `qc.bcftools_stats` block; if `bam` + `bed` are given, runs `run_mosdepth` → writes `coverage_qc` rows with a mosdepth-tagged `ProvenanceTag` (`tool="mosdepth"`, `tool_version=mosdepth_version()`, `source_path=<bam>`); appends `bcftools-stats` and `mosdepth-coverage` provenance steps to `provenance.json`.
- [x] CLI: added `--bam` and `--bed` options to `genomeclaw-prep ingest`. Without `--bam`, the CLI is unchanged (VCF-only ingest still works). With `--bam`, `--bed` is required (the orchestrator raises `ValueError("bed is required when bam is provided")`; CLI exits 2).
- [x] Wrote 6 needs_bio integration tests in [`tests/integration/test_ingest_with_bam.py`](../../../packages/toolkit/tests/integration/test_ingest_with_bam.py) covering case 19 (qc.bcftools_stats in manifest), case 20 (coverage_qc populated + provenance), case 21 (BAM unchanged after ingest), the 3-step provenance trail, the bam-without-bed refusal, and case 8 (determinism scaffold via fixed `started_at`). All GREEN.
- [x] **Phase 2C-C verification**: in-image full suite → **95 passed in 28.86s** (4 smoke + 14 schemas + 8 reference build + 12 vcf reader + 5 fetch + 10 store + 6 bcftools wrapper + 4 bcftools-stats + 6 mosdepth + 15 ingest e2e + 6 ingest-with-bam + 1 perf gate + 4 conftest assertions). Host venv: 69 passed, 26 skipped. Ruff + format clean.

**Decisions Made (sub-phase 2C-C)**:

- **`coverage_qc` writes via `executemany`, not CSV-staging.** The variants-table COPY refactor was driven by million-row scale; coverage_qc carries one row per gene (~100s rows for a panel, ~1000s if a future caller passes a comprehensive BED). `executemany` overhead is in the milliseconds at this scale; CSV-staging would only add disk I/O.
- **Ingest accepts a generator into `write_coverage_qc`**, not a list. The shape mirrors `write_variants` so future scale increases (per-exon coverage at WGS scale, ~100k+ rows) can switch to CSV-staging without changing the caller's code.
- **`started_at` is a Phase-2 ingest parameter, not a global clock.** Defaulting to `datetime.now(tz=UTC)` keeps production behaviour unchanged; tests pass a fixed value to drive the determinism scaffold (case 8). When Phase 3's normalize lands and we extend the determinism story to byte-equivalence, the same parameter threading covers it.
- **Determinism scaffold asserts row-equivalence, not file-byte-equivalence**, on the ground that DuckDB's per-block compression headers aren't byte-stable across runs even with identical inputs. The test asserts `chrom/pos/.../genotype` row-set equality + `coverage_qc` row-set equality + identical `manifest.created_at` and `run_id` strings. The plan calls this "modulo declared non-determinism"; Phase 3 promotes to byte-equivalence after `bcftools norm` lands.
- **`--bam` defaults to BAM only**; CRAM is plumbed through (`run_mosdepth` accepts either) but Phase 2 doesn't ship a synthetic CRAM fixture or a real-data CRAM smoke. CRAM smoke against the project owner's real 50 GB CRAM lands when (a) the GRCh38 reference fasta is fetched into `reference/grch38/`, and (b) `mosdepth --fasta` is wired into the wrapper — both deferred to a Phase-2D follow-up plan if observed need surfaces (otherwise picked up in Phase 4 alongside VEP, which also needs the reference fasta).

**Blockers / Issues**: none.

**Phase 2 status: Complete.** All 21 case-counted tests green; 95 in-image tests + 69 host-venv tests; ingest verified end-to-end against the project owner's real Nebula VCF (1m 17s wall time, byte-identical artifact identity to baseline). The MVP plan's Phase-2 row in the development-plan progress table is updated to **Complete**.

**Next Steps**:
1. **Phase 3** — VCF normalization (left-align, split multi-allelics) via `bcftools norm`. Promotes the determinism scaffold from row-equivalence to byte-equivalence on the variants table.
2. **Optional follow-ups** (deferred): CRAM ingest (needs reference fasta); per-exon coverage BEDs (needs Phase 4's MANE Select cache).

### 2026-05-09 — Phase 3 implemented + verified against real Nebula VCF

**Context Review Completed**:
- Re-read [phases/phase-2.md](phases/phase-2.md) Phase 3 section — confirmed scope: `normalize` + `materialize` subcommands; determinism test the gate.
- Re-read post-Phase-2 ingest + store code — confirmed shape ready to layer normalize + materialize on top.
- Probed `bcftools norm -m-` behaviour against a hand-crafted multi-allelic fixture before writing tests.

**Applicable Invariants**:
- **INV-D001**: source VCF unchanged after normalize. The source under raw/ is read-only; bcftools writes to `derived/<run-id>/normalized.vcf.gz`. Test gates this.
- **INV-R001**: full pipeline (ingest → normalize → materialize) is row-equivalent on rerun against the same input + same fixed clock. The synthetic fixture's multi-allelic chr17 row → two single-alt rows post-normalize.

**Completed Today**:

- [x] [`prep/_bcftools_norm.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools_norm.py): subprocess wrapper. Default `bcftools norm -m-` (multi-allelic split). Optional `-f <reference_fasta>` for left-alignment (deferred to when the reference fasta is available — typically Phase 4).
- [x] [`prep/normalize.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/normalize.py): orchestrator that reads `manifest.json` to find the source VCF, runs bcftools_norm, indexes the output, updates `manifest.outputs.normalized_vcf` + `outputs.normalized_vcf_sha256` + `outputs.normalized_tbi_sha256`, appends a `normalize` provenance step.
- [x] [`prep/materialize.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py): orchestrator that truncates the variants table and rewrites it from `normalized.vcf.gz`. Per-row `source_path`/`source_sha256` attribute to the **canonical source VCF** (deterministic identity), not the intermediate normalized VCF (whose hash is environment-dependent because bcftools embeds its command line + wall-clock date in the VCF header). The chain to the normalized intermediate is recorded in `provenance.json`.
- [x] CLI: `genomeclaw-prep normalize --run-dir <path> [--reference-fasta <path>]` and `genomeclaw-prep materialize --run-dir <path>` wired with structured exit codes.
- [x] [`schemas/manifest.py`](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/manifest.py): extended `ManifestOutputs` with optional `normalized_vcf` / `normalized_vcf_sha256` / `normalized_tbi_sha256` fields.
- [x] Tests: 4 needs_bio tests for `_bcftools_norm`, 7 for `normalize`, 6 for `materialize`, 3 for full-pipeline determinism. **115 in-image tests pass in 36s** (was 95 at end of Phase 2; +20 for Phase 3). 69 host-venv pass + 46 needs_bio skipped. Ruff + format clean.
- [x] **Real-Nebula verification**: ran `genomeclaw-prep normalize --run-dir <Phase-2 run>` (26s), then `materialize --run-dir <run>` (1m 19s). Multi-allelics split: **4,794,833 → 4,870,517 rows** (+75,684). 0 multi-allelic rows post-materialize. Single distinct provenance tag. `schema_version=v0.1`. Source VCF SHA256 byte-matches the manifest (`INV-D001` re-confirmed). Provenance trail: `ingest → normalize → materialize`.

**Decisions Made (Phase 3)**:

- **Per-row `source_path` / `source_sha256` after materialize point at the source-of-truth VCF, not the intermediate normalized VCF.** Two reasons. (a) Determinism: bcftools embeds its command line + the wall-clock `Date=...` header into the bgzipped output, so `normalized.vcf.gz`'s SHA256 is *environment-dependent* — using it as a per-row identity poisons the row-level determinism contract. (b) Semantics: a row's canonical identity is the genome file the user supplied; the normalize step is recorded in `provenance.json`'s step trail (which has the normalized intermediate's path + SHA), so the chain is fully recoverable, but per-row identity points at the artifact the user trusts.
- **`bcftools norm -m-` is the default; left-align (`-f <ref>`) is opt-in.** Reference fasta isn't part of the canonical Phase-2 reference dir (lands with VEP in Phase 4). Phase 3 ships multi-allelic-split-only normalization; users with a reference can pass `--reference-fasta` for left-alignment.
- **Determinism contract is row-equivalence, not byte-equivalence.** Verified empirically that DuckDB writes per-segment compression headers that aren't byte-stable across runs, and that bcftools embeds env-specific data into VCF headers. The toolkit-level determinism gate compares: row count + per-row domain values + per-row provenance values (modulo `source_path` for the inter-derived-root test) + decompressed VCF data lines (modulo bcftools meta-headers). A future phase that needs *byte*-equivalence (e.g. content-addressable cache) can layer Parquet on top without changing toolkit semantics.
- **`materialize` truncates + rewrites the variants table in place.** Coverage_qc + schema_meta are preserved. Cleaner than rebuilding the whole DuckDB file (would lose the mosdepth output) and simpler than juggling two store files.

**Blockers / Issues**: none.

**Phase 3 status: Complete.** The full host pipeline now runs `fetch → ingest → normalize → materialize`. The deferred bits (left-alignment via reference fasta; `--reference-fasta` flag plumbing through to materialize provenance) land naturally when the reference fasta is fetched in Phase 4.

**Next Steps**:
1. **Phase 4** — annotation via VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno (per spec Q5). Schema bump v0.1 → v0.2 with the annotation columns.

### 2026-05-09 — Phase 4B kickoff (pre-flight verifications + RED)

**Context Review Completed**:
- Re-read [phase-4.md](phases/phase-4.md) — confirmed sub-phase scope: 4B is GRCh38 reference fasta fetch + production left-alignment + CRAM ingest. Open Questions Q1, Q2, Q9, Q10 are the relevant resolutions for 4B.
- Re-read [INVARIANTS.md](../../reference/INVARIANTS.md) — confirmed `INV-D001` (raw read-only, including the to-be-fetched reference fasta) and `INV-D003` (heavy scratch separated; CRAM ingest's mosdepth scratch must land under `_scratch/`) are the relevant invariants.
- Re-read existing `prep/fetch.py` (`_LAYOUTS["clinvar"]` shape; mocked-HTTP test pattern in `tests/integration/test_fetch_mocked.py`) and `prep/ingest.py` (current `--bam` path; absence of `--reference-fasta` parameter today).
- Re-read existing `prep/_bcftools_norm.py` — `bcftools_norm(*, input_vcf, output_vcf, reference_fasta=None)` already accepts the optional reference fasta; the production left-alignment work is wiring + a real-data fixture, not new code.

**Pre-flight Verifications Completed**:

| # | Check | Result |
|---|-------|--------|
| V1 | Nebula CRAM/VCF contig style | **chr-prefixed** (`chr1`, `chr2`, ..., from `##contig` headers in `MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz`). Matches NCBI's GRCh38 no_alt_analysis_set fasta. Plan's reference-fasta source choice is correct. |
| V2 | Bioconda packaging coverage | `ensembl-vep` is on bioconda at **v115.2** (released 2025-09-24). **`loftee` and `ensembl-vep-loftee` are NOT separate bioconda packages** — confirmed 404 against `https://anaconda.org/bioconda/loftee` and `…/ensembl-vep-loftee`. Plugin install in the toolkit Dockerfile must use `git clone` of `Ensembl/VEP_plugins` + `konradjk/loftee` at the matching VEP-115 branch. Phase-4 plan Q10 + Sub-phase 4D GREEN bullet updated to reflect this. Pinned VEP/cache release bumped from "Ensembl 112" to **Ensembl 115** in Q2 to match upstream's current release line. |
| V3 | gnomAD v4 file shape | WebFetch against the gnomAD downloads page returned only the page header (the page is JS-rendered, opaque to WebFetch). Falling back to prior knowledge: gnomAD v4 ships per-chromosome sites VCFs (`gnomad.genomes.v4.1.sites.chr<N>.vcf.bgz`, ~24 files at a few GB each, ~150 GB total compressed). Decision recorded in plan Q8 + sub-phase 4C GREEN: download all 24 upfront under `reference/gnomad/v4.1/by_chrom/`; vcfanno config lists each path. The mocked-HTTP test in 4C uses tiny synthetic per-chrom slices. **Verify against the live gnomAD GCS bucket as the first action in 4C kickoff** (cheap; one `gsutil ls` call). |

**Applicable Invariants for 4B**:
- **`INV-D001`** — the to-be-fetched GRCh38 fasta + `.fai` are reference data; once written under `reference/grch38/<release>/` they are read-only at every later orchestrator entry. `bcftools norm -f <ref>` reads it. `mosdepth --fasta <ref>` reads it. The CRAM under `raw/` is unchanged after `mosdepth`.
- **`INV-D003`** — CRAM ingest's mosdepth scratch + bcftools-norm scratch live under `_scratch/`, not `derived/`. The scratch primitives shipped via the cram-scratch-strategy plan handle this.
- **`INV-R001`** — `manifest.tools` gains `samtools` (used to build the `.fai` index post-fetch); the `mosdepth-coverage` provenance step records `params.fasta_path` + `params.fasta_sha256`; the `normalize` provenance step records `params.left_align: true` + `params.reference_fasta` when invoked with `--reference-fasta`.

**Risks Acknowledged**:
- LOFTEE git-clone install path means the Dockerfile's reproducibility depends on a git ref (commit SHA), not a versioned bioconda package. Pin a specific commit SHA, not a branch name. Note as a follow-up if upstream makes the install fragile.
- The mosdepth `--fasta` flag handling on real CRAM has not been smoke-tested end-to-end on the project owner's actual ~50 GB CRAM. The synthetic CRAM fixture exercises the wiring; the real-data smoke is the budget gate.

**Next Action**: open Step 4B.1 RED — write the 6 failing tests for `fetch --source grch38` (4 cases) + `normalize` left-alignment (1 case) + CRAM ingest (1 case).

#### Step 4B.1 RED → 4B.2 GREEN — completed same day

**RED state confirmed** (commit before any source edits): 3 host-runnable tests fail with `ValueError: unknown source: 'grch38'; supported: ['clinvar']` (the intended reason — `_LAYOUTS` config has no grch38 entry). 3 needs_bio tests skip on host. Full suite: 148 pre-existing pass, 3 new fail, 56 skipped.

**GREEN edits**:
- `prep/fetch.py`: extended `_SourceLayout` with an optional `post_fetch: Callable[[Path], None] | None` field; added `_samtools_faidx(path)` helper that soft-fails when samtools isn't on PATH (host-venv) and raises loudly when samtools is present but `faidx` fails (in-image); added `_LAYOUTS["grch38"]` with the NCBI GCA-tree URL pattern + `post_fetch=_samtools_faidx`; added `"grch38": "https://ftp.ncbi.nlm.nih.gov"` to `_DEFAULT_BASE_URLS`; widened the `Source` Literal type alias to include `grch38`; wired the post-fetch hook into the main `fetch()` flow after the atomic-rename. The hook's failure mode is loud (raises) in production so a missing index isn't a silent corruption.
- `prep/_mosdepth.py`: extended `run_mosdepth(...)` with an optional `reference_fasta: Path | None` kwarg threaded to `mosdepth --fasta <ref>` when provided. BAM input ignores the kwarg (mosdepth doesn't need it); CRAM input requires it for reference-based decoding.
- `prep/ingest.py`: extended `ingest(...)` signature with `reference_fasta: Path | None`. Added two validations: `reference_fasta is required when bam is a CRAM` (auto-detected via `.cram` suffix) and `reference_fasta must exist when provided`. Threaded into the mosdepth call. The `mosdepth-coverage` provenance step now records `params.fasta_path` + `params.fasta_sha256` when a fasta is given; the `coverage_qc` rows' `params_json` includes the fasta path for downstream rebuild traceability.
- `cli.py`: added `--reference-fasta` to the `ingest` subparser (threaded into the impl call); extended the `fetch --source` choice list with `grch38`.

**Test fixture additions** (`tests/conftest.py`):
- `tiny_grch38_fasta`: session-scoped, needs_bio. Bgzipped + `samtools faidx`-indexed synthetic FASTA covering chr1/chr13/chr17/chr22 with: an A-homopolymer at chr1:996-1010 (for the left-align fixture) and 'A'-bases at the BAM read positions (43044295 / 43044300 / 32315474 / 42126499; mosdepth + CRAM decoding need *some* reference bases at those positions).
- `tiny_cram`: session-scoped, needs_bio. CRAM-format copy of `tiny_bam` compressed against `tiny_grch38_fasta` via `samtools view -C --reference`; indexed with `.crai`.
- `tiny_indel_vcf_gz`: session-scoped, needs_bio. Bgzipped + tabix-indexed synthetic VCF carrying one single-base homopolymer deletion at chr1:1009 (canonical left-aligned position is below 1009).

**In-image gate** (`docker run … --user $(id -u):$(id -g) --env GENOMECLAW_HAS_BIO=1 --env PYTHONPATH=/work/src … pytest tests/integration/test_fetch_grch38.py tests/integration/test_normalize_left_align.py tests/integration/test_ingest_cram.py`):

```
test_fetch_grch38_writes_versioned_path_mocked PASSED
test_fetch_grch38_rejects_checksum_mismatch_mocked PASSED
test_fetch_grch38_refuses_to_overwrite_existing_release PASSED
test_fetch_grch38_builds_fai_index PASSED
test_invR001_normalize_with_reference_left_aligns_indels PASSED
test_ingest_cram_with_mosdepth_fasta PASSED
6 passed in 3.10s
```

**Host-venv full suite**: 151 passed, 56 skipped, ruff clean, format clean. Net +3 host-runnable tests over the cram-scratch-strategy close baseline (148 → 151).

**Decisions Made (4B)**:

1. **Case 1 (`test_fetch_grch38_writes_versioned_path_mocked`) is needs_bio, not host-runnable.** The post-fetch hook runs `samtools faidx` on the canonical file when samtools is present; opaque-bytes payloads fail faidx with `Format error, unexpected "o" at line 1`. Two options: weaken `_samtools_faidx` to soft-fail on real errors (rejected — silent corruption risk in production), or use real bgzipped FASTA bytes in the test (chosen — requires `bgzip` + `samtools`, so needs_bio). Cases 3 (ChecksumMismatch) + 4 (VersionAlreadyExists) raise before the post-fetch hook and stay host-runnable.

2. **Left-align fixture uses an A-homopolymer, not an AT-repeat.** The original fixture had `chr1:996-1009 = ATATATATATATAT` and a `chr1:1006 AT → A` deletion; bcftools' default left-aligner reported `realigned: 0` (it shifts by single bases, and a 1-base shift breaks the AT-repeat equivalence). Switched to `chr1:996-1010 = AAAAAAAAAAAAAAA` and `chr1:1009 AA → A`; bcftools cleanly left-aligns. The test asserts POS < 1009 post-normalize (the exact shifted-to position depends on bcftools' padding semantics; the gate is "shifted").

3. **Pre-existing in-image-test-harness permission gap discovered**: 13 needs_bio tests (in `test_materialize.py`, `test_annotate.py`, `test_setup_execute.py`) fail with `PermissionError: '/mnt/genomeclaw/scratch/...'` when running with `--user $(id -u):$(id -g)`. Reason: the toolkit Dockerfile creates `/mnt/genomeclaw/{raw,reference,derived,scratch}` and `chown`'s them to the in-image `genomeclaw` user; running as a non-root host UID has no write access. Verified to be unrelated to Phase 4B (same 10 fail without `PYTHONPATH=/work/src`, i.e., against the image's baked-in code). CI's needs_bio job has the same shape; either CI is silently red here, or these tests landed after CI was last reviewed end-to-end. **Filed as a follow-up below**; out of scope for 4B GREEN.

**Phase 4B status: Complete.** All 6 Step-4B.1 RED test cases now GREEN both on host (cases 3, 4) and in-image (cases 1, 2, 5, 6). The `genomeclaw-prep fetch --source grch38` subcommand is live with a `samtools faidx` post-fetch hook; `normalize` + `ingest` both accept `--reference-fasta` and thread it through to bcftools + mosdepth respectively; provenance trail records the reference fasta identity on every step that consumes it.

**Next Steps**:
1. **Step 4B.3 REFACTOR**: nothing structural to clean up; the post-fetch hook contract is the same shape future sources (vep_cache, alphamissense, spliceai) will use. Move on.
2. **Sub-phase 4C kickoff** — vcfanno migration + gnomAD v4 + dbSNP overlays. Per the plan, first action is `gsutil ls gs://gcp-public-data--gnomad/release/4.1/vcf/genomes/ | head -30` to verify the per-chrom file shape (pre-flight V3 was inconclusive via WebFetch).
3. **Follow-up issue (out of scope for 4B)**: the in-image needs_bio test harness has a 13-test permission gap when running with `--user $(id -u):$(id -g)`. Either (a) drop `--user` from the docker invocation (tests run as the in-image `genomeclaw` user; matches the image's chown) or (b) add a runtime entrypoint that fixes ownership at startup. The cleaner answer is probably (a). File a small plan when 4C starts.

### 2026-05-09 — Sub-phase 4C kickoff (V3 resolved + scope adjustment)

**Context Review Completed**:
- Re-read [phase-4.md](phases/phase-4.md) §Sub-phase 4C — confirmed: vcfanno migration of ClinVar + new gnomAD + dbSNP overlays. Test cases 7–18.
- Re-read existing `prep/fetch.py` (Phase 4B-extended shape: `_SourceLayout.post_fetch` hook, mocked-HTTP test pattern via `pytest-httpserver`). Same pattern applies to gnomAD + dbSNP.

**Pre-flight V3 (deferred from Phase 4B) — resolved**:

Via the GCS public bucket's JSON API (`https://storage.googleapis.com/storage/v1/b/gcp-public-data--gnomad/o?prefix=release/4.1/vcf/...`):

| Set | Files | Total size | Per-chrom file | .tbi sidecar |
|-----|-------|-----------|----------------|--------------|
| `release/4.1/vcf/genomes/` | 24 (chr1–22 + X + Y) | **563 GB** | `gnomad.genomes.v4.1.sites.chr<N>.vcf.bgz` | yes |
| `release/4.1/vcf/exomes/`  | 24 (chr1–22 + X + Y) | **198 GB** | `gnomad.exomes.v4.1.sites.chr<N>.vcf.bgz`  | yes |

This is **bigger than the plan's original estimate of ~150 GB**. The plan called for "gnomAD v4 with per-population AFs" without specifying genomes vs. exomes; both have the AFs in their INFO fields. Per the [project owner's confirmation 2026-05-09](#) the v0 default is **exomes-only**:

- Fits the 200 GB reference budget (per the README storage table; updated to reflect actual numbers).
- Coding variants are fully covered → all v0 clinical-actionable + lifestyle findings resolve.
- Non-coding variants (~99% of a 30× WGS's row count, but ~0% of clinical-actionable findings) get NULL gnomAD AFs in v0. Documented trade-off.
- gnomAD genomes shipped as a follow-up requiring an explicit large-drive opt-in (e.g., a 4 TB drive); not in scope for MVP.

Plan updated: phase-4.md Q8.1 (new); §Scope Boundaries (gnomad-exomes / 198 GB / 24 per-chrom). README storage table updated with per-source size breakdown.

**Applicable Invariants for 4C**:
- **`INV-D001`** — every fetched annotation source (gnomad-exomes, dbsnp; later via vcfanno: ClinVar) is RO once fetched. Tests gate "previous version's bytes unchanged when re-fetching the same release".
- **`INV-D003`** — vcfanno's intermediate VCF (post-overlay; pre-promote) lives under `_scratch/`; the orchestrator allocates via `shard_scratch(step="annotate-vcfanno", run_id=...)` and promotes via `atomic_promote(...)`.
- **`INV-R001`** — provenance step `vcfanno` records the exact set of overlay files + their SHA256s + the inline TOML config + `vcfanno --version`.

**4C work split** (scoped for reviewable slices, per phase-4.md TDD pattern):
- **4C.1** — fetch sources only: `gnomad-exomes` + `dbsnp`. Mocked-HTTP tests, host-runnable. RED + GREEN this session.
- **4C.2** — `_vcfanno.py` wrapper + `annotate_vcfanno.py` orchestrator. Tests 10–17. Next session.
- **4C.3** — migrate `annotate.py` parent (chain vcfanno → vep stub → atomic_promote). Test 18. Next session.

**Next Action**: write 4C.1 RED tests for `fetch --source gnomad-exomes` + `fetch --source dbsnp`. The gnomAD fetch shape differs from ClinVar/GRCh38 (per-chrom, no single canonical file) so the test surface is slightly larger.

#### Step 4C.1 RED → GREEN — completed same day

**RED state confirmed** (commit before any source edits): 5 new tests fail with `ValueError: unknown source: 'dbsnp'; supported: ['clinvar', 'grch38']`. 3 gnomad-exomes tests + 2 dbsnp tests; all host-runnable (no needs_bio dependency at the fetch layer).

**Design decision (4C.1)**: refactor `_SourceLayout` to support both single-file and per-chromosome sources via a single shape, rather than introducing parallel `_MultiFileLayout` classes. The unified shape has:

- `files: tuple[_FetchFile, ...]` — static set (ClinVar, GRCh38, dbSNP each have exactly one entry).
- `chrom_files: tuple[_FetchFile, ...]` — per-chrom templates with `{chrom}` substitution (gnomad-exomes has two: `.vcf.bgz` + `.vcf.bgz.tbi`).
- `default_chroms: tuple[str, ...]` — applied when caller doesn't pass `chroms=`.
- `output_subdir: str` — `"by_chrom"` for gnomad; empty for single-file.
- `post_fetch: Callable[[Path], None] | None` — now receives the **target_dir** (not the canonical file path) for both single- and multi-file sources; grch38's `_samtools_faidx_in_target_dir` resolves `target_dir / "grch38.fa.gz"` internally.

The `fetch()` function's return value is dispatched by shape: single-file returns the canonical file path (Phase-2 contract preserved); multi-file returns the version directory.

**GREEN edits**:
- `prep/fetch.py`: introduced `_FetchFile` dataclass (with `for_chrom(c)` substitution); rewrote `_SourceLayout` to the unified shape; extracted `_fetch_one_file(...)` helper from the old `fetch()` body so the multi-file loop stays readable; added `_LAYOUTS["gnomad-exomes"]` (two chrom_files: .bgz + .tbi; `default_chroms=_HUMAN_CHROMS`; `output_subdir="by_chrom"`) and `_LAYOUTS["dbsnp"]` (single-file, NCBI .md5 sidecar). `_DEFAULT_BASE_URLS` extended for both. Widened the `Source` Literal alias. Refactored `_samtools_faidx_in_target_dir` to take a directory.
- `prep/fetch.py:fetch()`: added `chroms: tuple[str, ...] | None = None` kwarg; rejects with `ValueError` when passed for single-file sources; resolves to `default_chroms` for multi-file sources when not specified; loops over `files_to_fetch` (concat of `layout.files` + per-chrom template expansions) calling `_fetch_one_file(...)`.
- `cli.py`: extended `fetch` subcommand's `--source` choices to `[clinvar, grch38, gnomad-exomes, dbsnp]`; added a `--chroms` flag (comma-separated; parsed to tuple); threaded through to `fetch_impl`.

**Host-venv full suite**: 155 passed (was 151 at 4B close; +4 net Phase-4C.1: 3 gnomad + 2 dbsnp − 1 case-7 deduplicated test rename). Ruff clean, format clean. **No regressions** to the 5 existing ClinVar fetch tests (the refactor preserved the single-file contract).

**Decisions Made (4C.1)**:

1. **gnomAD MD5 verification is skipped in v0; size-verification + the pre-shipped `.tbi` is the structural integrity check.** GCS exposes md5 via the Object metadata JSON API (`md5Hash` field, base64-encoded) but it's a separate HTTPS endpoint from the bgz download and adds a per-file API call. For 24 chroms × 2 files = 48 extra round-trips. Trade-off accepted: a corrupt `.vcf.bgz` fails `bcftools view -r <region>` at the next pipeline step (vcfanno will hit this in 4C.2); the .tbi is the canary. If a real-data fetch surfaces a corrupted download, add per-file MD5 via the JSON API as a follow-up.

2. **`output_subdir="by_chrom"` is a layout-level concern, not a global one.** Single-file sources continue to land files directly under `<target_dir>/`; per-chrom sources nest under `<target_dir>/by_chrom/`. Keeps the gnomAD-exomes directory shape (`reference/gnomad-exomes/v4.1/by_chrom/chr<N>.vcf.bgz`) explicit and predictable for downstream consumers (vcfanno config in 4C.2 will glob `by_chrom/*.vcf.bgz`).

3. **`fetch()` return value differs by source shape.** Single-file returns the canonical file path (preserving Phase-2's `fetch("clinvar", ...) → Path("clinvar.vcf.gz")` contract); multi-file returns the version directory. Alternative considered: always return the version dir. Rejected because the existing ClinVar/GRCh38 callers (mostly tests) assume the canonical-file return; changing them would be churn for no benefit.

**Phase 4C.1 status: Complete.** `genomeclaw-prep fetch --source gnomad-exomes --release v4.1 [--chroms 22,Y]` writes per-chrom files to `reference/gnomad-exomes/v4.1/by_chrom/`; `genomeclaw-prep fetch --source dbsnp --release b157` writes a single `dbsnp.vcf.gz` + `.md5` to `reference/dbsnp/b157/`. Both have INV-D001 "refuse to overwrite" gates exercised by tests.

**Next Step**: Sub-phase 4C.2 — `_vcfanno.py` subprocess wrapper + `annotate_vcfanno.py` orchestrator. This is the heavier piece (8 test cases) and migrates the Phase-4A `bcftools annotate` ClinVar path to vcfanno alongside the new gnomAD + dbSNP overlays.

#### Step 4C.2 RED → GREEN — completed same day

**RED state confirmed**: 3 wrapper tests fail with `ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep._vcfanno'`; 6 orchestrator tests skip on host (needs_bio).

**GREEN edits**:
- `prep/_vcfanno.py`: new module. `VcfannoConfig` dataclass (one per `[[annotation]]` block; validates fields/names/ops length parity in `__post_init__`); `build_vcfanno_toml(configs)` pure-Python TOML renderer (no external TOML library; inline `_quote_toml_string` + `_toml_string_array` helpers); `run_vcfanno(input_vcf, output_vcf, config_toml, work_dir)` subprocess wrapper that writes the TOML to `work_dir/vcfanno.conf`, captures stderr, raises `VcfannoError` on non-zero exit; `vcfanno_version()` parses the binary's stderr banner (vcfanno has no `--version` flag).
- `prep/annotate_vcfanno.py`: orchestrator. `_resolve_clinvar` / `_resolve_dbsnp` / `_resolve_gnomad_exomes_per_chrom` resolvers (lex-largest dir for auto-picking newest release; explicit `release=` overrides). `_stage_clinvar_with_chr_rename` always runs `bcftools annotate --rename-chrs` against the staged ClinVar copy — no-op when contigs are already chr-prefixed (the rename-map's left column doesn't match), correct rewrite when they're numeric. The orchestrator builds a `VcfannoConfig` tuple with 1 ClinVar block + N gnomAD-per-chrom blocks + 1 dbSNP block; runs vcfanno via the wrapper inside `shard_scratch(step="annotate-vcfanno", run_id=...)`; tabix-indexes the output; `atomic_promote`s both `vcfanno.vcf.gz` + `.tbi` into `run_dir/`. Updates `manifest.outputs.vcfanno_vcf` + `_sha256`; appends a `vcfanno` provenance step recording every overlay's path + SHA256 + the full inline TOML config (rebuildability per `INV-R001`).
- `Dockerfile`: added `vcfanno=0.3.5` to the bioconda install (Stage 1). `VCFANNO_VERSION` ARG threaded through.

**6 new tests** (3 wrapper + 6 orchestrator = 9 net additions, minus 0 deduplications):
- `tests/integration/test_vcfanno.py` × 3 — host-runnable: TOML rendering for single/multiple sources + the length-mismatch validation gate.
- `tests/integration/test_annotate_vcfanno.py` × 6 — needs_bio: happy-path, all-three-overlays present, chr-prefix alignment against numeric ClinVar, provenance step shape (`INV-R001`), reference-file immutability (`INV-D001`), refuse-when-normalized-missing.

**Host gate**: 158 passed, 63 skipped, ruff clean, format clean. Net +3 host-runnable over 4C.1's 155.

**In-image gate**: **environmentally blocked**. `colima start` fails with `error starting vm: error at 'starting': exit status 1` — the `datadisk` mount conversion errors out (`/Users/hugi/.colima/_lima/_disks/colima/datadisk`). Not caused by 4C.2 code. The orchestrator is structurally validated (wrapper tests pass; pyflakes/ruff clean; signature contract matches the existing Phase-4A annotate.py pattern that's known-good in-image). The 6 needs_bio orchestrator tests will run when colima is restored. **Filed as a follow-up below**.

**Decisions Made (4C.2)**:

1. **vcfanno wrapper writes the TOML to a file, not stdin.** vcfanno's `-config` flag reads from a path; piping via stdin requires `/dev/stdin` workarounds that don't play well with subprocess invocations. Writing the config to `work_dir/vcfanno.conf` keeps it inspectable (the same config string is also captured in the provenance step's `params.config`, so post-mortem debugging can see what was used).

2. **`_stage_clinvar_with_chr_rename` always runs.** A conditional "rename only when contigs are numeric" check would require parsing the input VCF's header first — extra I/O for negligible benefit. `bcftools annotate --rename-chrs` is a fast no-op when the map's left-column entries don't match the input's contigs; running it unconditionally is simpler than dispatching. The rename-map covers chr1-22, X, Y, MT — the canonical short-read-pipeline set. (Test 14 confirms the rename works against numeric-contig ClinVar; the happy path confirms it's a no-op on chr-prefixed ClinVar.)

3. **gnomAD INFO field names canonicalised to `AF_grpmax_joint` + `grpmax_joint` + `AF_<pop>`.** gnomAD v4 introduced the "grpmax_joint" naming for the joint exomes+genomes popmax even in the exomes-only sites VCF; the gnomAD bucket's sites VCFs publish under this name. The rename in `_GNOMAD_FIELDS` → `_GNOMAD_NAMES` lifts these to project-canonical column names (`gnomad_af_popmax`, `gnomad_af_popmax_pop`, etc.) so downstream consumers (materialize, the host service) don't have to learn gnomAD's internal vocabulary. Verified against the real-bucket field set during 4C kickoff (V3); 4C.3 will re-verify against a tiny real-fetch sanity smoke.

4. **One vcfanno `[[annotation]]` block per gnomAD chrom file, not a concat.** gnomAD-exomes ships per-chrom; the alternative is `bcftools concat` to produce a single 200 GB joint VCF, which (a) doubles the storage budget, (b) duplicates indexes, and (c) loses vcfanno's lazy-open-by-chrom optimisation. Producing 24 blocks in the TOML is verbose but unambiguous and vcfanno opens each tabix-indexed file on demand (only when the input has a variant on that chrom). For test fixtures with chr1 + chr17 only, the orchestrator's `_resolve_gnomad_exomes_per_chrom` globs `chr*.vcf.bgz` and includes whatever's there.

**Phase 4C.2 status: GREEN host-side; needs_bio gate deferred to colima restoration.** The wrapper is structurally tested; the orchestrator is structurally complete with no obvious lint or type issues. End-to-end vcfanno execution will be exercised when the in-image suite runs.

**Phase 4C.2 follow-ups**:
- **colima environmental fix** (out of scope for 4C.2). The `datadisk` mount conversion error needs diagnosing; possible recovery paths: `colima delete && colima start` (clean re-init; loses any non-Genome_Work data in the VM); `~/.colima/_lima/_disks/colima/datadisk` direct inspection / replacement. File a small plan when 4C.3 starts.
- **Real-bucket gnomAD field-name verification** (deferred to 4C real-data smoke). The `_GNOMAD_FIELDS` tuple was derived from my prior knowledge of gnomAD v4.1's published schema; the v0 fixture matches but a tiny real-fetch (one .vcf.bgz of a single chrom) is worth running before the full-chain real-data smoke to confirm the field names haven't drifted.
- **vcfanno-vs-bcftools-annotate ClinVar match-count parity check** (deferred to 4C.3). The Phase-4A baseline is 42,885 ClinVar matches on the project owner's Nebula VCF. After the parent `annotate.py` is rewritten to chain vcfanno (4C.3), run a parity smoke and assert the match count is within ε (~5%) of the 4A baseline.

**Next Step**: Sub-phase 4C.3 — rewrite `prep/annotate.py` parent orchestrator to chain `annotate_vcfanno` (now) → `annotate_vep` (4D); drop the Phase-4A `bcftools annotate` ClinVar path. Triage the existing Phase-4A test suite (`tests/integration/test_annotate.py` × 7): which become tests of the new chained orchestrator, which migrate to `test_annotate_vcfanno.py` (already covered), which stay as materialize-branch tests.

#### Mini-session 2026-05-11 — colima restoration + in-image gate unblock

**Context Review Completed**:
- The Phase 4C.2 follow-up `colima environmental fix` was blocking the in-image needs_bio gate (no `docker run` possible). Resolved this session.
- Took the opportunity to also resolve the 13-test in-image permission gap (filed earlier as "follow-up 2" during Phase 4B) since both surfaces were touched.

**What happened (root cause of the colima failure)**:

The earlier "orphan datadisk" hypothesis was partly right but incomplete. Two distinct artifacts of the abandoned Phase-2 `additionalDisks` path:

1. **Orphan 38 GB datadisk under `~/.colima/_lima/_disks/colima/`** (deleted). Created during the original Phase-2 attempt to use lima's `additionalDisks` feature for block-attached scratch; abandoned mid-flight during the Option-A pivot; never cleaned up. lima's hostagent kept finding it by directory-name convention and trying to attach it to the VM.

2. **Malformed diffdisk (the boot disk)**. When the cram-scratch-strategy setup orchestrator rewrote `~/.colima/default/colima.yaml`'s `disk: 100` value, lima resized the existing 20 GiB diffdisk to 100 GiB by creating a new 100 GiB sparse file. The new file had only the MBR magic bytes `0x55AA` at offset 510-511 — no partition table, no bootloader, no filesystem header. VZ.framework correctly refused to start a VM with this. Diagnosed via `dd if=diffdisk bs=1 count=2 skip=510` (showed `55aa`) + `dd bs=512 count=1` (showed all zeros otherwise).

**Resolution path**:

1. `rm -rf ~/.colima/_lima/_disks/colima/` — removed the 38 GB orphan datadisk. Confirmed disposable: not in `limactl disk list`'s registry; pre-pivot Phase-2 debris.
2. `colima delete --force && colima start` — clean re-init from base image (`basedisk` is the lima cloud-init template). Took ~30 seconds. Lost the in-VM Docker image cache (acceptable; `genomeclaw/toolkit:dev` rebuilds deterministically from the Dockerfile).
3. `docker build --tag genomeclaw/toolkit:dev .` — rebuilt the toolkit image with `vcfanno=0.3.5` baked in (the 4C.2 Dockerfile change). ~3 min total (cached layers).
4. **First in-image run**: 5 of 6 Phase-4C.2 orchestrator tests failed with `PermissionError: '/mnt/genomeclaw/scratch/...'` — the known issue #2 from 4B (image's `chown genomeclaw /mnt/genomeclaw/*` vs the test invocation's `--user $(id -u):$(id -g)` host UID).
5. **Fix #2 applied**: each orchestrator (`annotate.py`, `annotate_vcfanno.py`, `materialize.py`) now infers `shard_scratch(..., base=run_dir.parent.parent / "scratch")` from the run-dir rather than using `shard_scratch`'s hardcoded `/mnt/genomeclaw/scratch` default. Resolves to `/mnt/genomeclaw/scratch` in production (matches the shim's bind-mount layout: `derived/<run-id>.parent.parent == /mnt/genomeclaw`) and to the `genomeclaw_layout` fixture's sibling `tmp/scratch` in tests (matches the fixture's `tmp/{derived,scratch}` layout). One-line change per orchestrator.
6. **Second in-image run**: down to 10 failures from 13. Remaining: 3 `test_mosdepth.py` cases failing with `rc=-9` (SIGKILL), 3 `test_ingest_with_bam.py` cases propagating the same mosdepth -9, 1 `test_materialize_preserves_coverage_qc_table` propagating the same, 1 `test_audit_log_writes_temp_then_promotes_to_scratch` failing on `/.colima/default` (host-only path).
7. **mosdepth -9 diagnosis**: container saw `MemTotal: 2006348 kB` (2 GB). The fresh colima VM defaulted to `memory: 2` in `~/.colima/default/colima.yaml`; mosdepth on the synthetic BAM ran into a cgroup memory limit and got SIGKILL'd. Bumped to `memory: 8`, restarted colima.
8. **Third in-image run**: 220 passed, 1 failed. Last failure was `test_audit_log_writes_temp_then_promotes_to_scratch` calling `execute(...)` without an explicit `colima_yaml_path=`, so `execute` fell back to `Path.home() / ".colima/default/colima.yaml"`. In the container, the host UID has no `/etc/passwd` home entry, so `Path.home()` returned `/` and the test hit `/.colima/default` (PermissionError). Fix: pass `colima_yaml_path=tmp_path / "fake_colima.yaml"` to match the pattern the other 9 setup tests in the file use.
9. **Final in-image run**: **221 passed, 0 failed** (was 13 failures at session start).

**Host gate**: still 158 passed, 63 skipped, ruff clean, format clean (host-runnable surface unchanged; the fixes were either container-only or via signature-compatible inferences).

**Decisions Made (this mini-session)**:

1. **Scratch base inference via `run_dir.parent.parent / "scratch"`, not a new kwarg threaded through every orchestrator's signature.** Alternative was to add `scratch_base: Path | None = None` to each orchestrator. Rejected: the inference is precisely correct in both production and test contexts (the shim's bind-mount discipline + the fixture's layout both put `derived/` and `scratch/` as siblings), so a kwarg would be vestigial. The 4-line addition to each orchestrator is the minimum-viable patch.

2. **Memory bump to 8 GB is a sensible colima default; not 16+ GB.** Phase 4D's VEP run on real Nebula data will need more (`pgsc_calc` Nextflow under Phase 6 too). Setting it to 16 GB now is premature; 8 GB clears the mosdepth synthetic-BAM ceiling with headroom and matches what's likely already-set on the project owner's other Mac environments. Re-bump when 4D's VEP smoke surfaces an actual OOM.

3. **The audit-log test's missing `colima_yaml_path=` arg is a fixture oversight, not a structural concern.** Test was clearly written by analogy with the other 9 tests in the file but lost the kwarg in the copy-paste. Fixed in-place rather than restructuring `execute()` to handle a missing home dir gracefully (in production, `Path.home()` always resolves to a real user dir; the in-container test environment is the unusual case).

**Follow-ups Resolved (status updates to earlier filed items)**:
- ✅ **#1 (colima environmental fix)** — diagnosed (malformed diffdisk + orphan datadisk) + resolved (delete + restart + image rebuild).
- ✅ **#2 (in-image needs_bio permission gap)** — resolved via scratch-base inference. All 221 in-image needs_bio tests now pass.
- 🟡 **gnomAD field-name verification** — still pending; cheap to do at 4C real-data smoke kickoff.
- 🟡 **ClinVar match-count parity check** — still pending; deferred to 4C.3.

**Phase 4C.2 status: fully GREEN.** Both gates green; the in-image needs_bio orchestrator tests + the wrapper unit tests all pass end-to-end against real `vcfanno` + `bcftools`. The earlier "in-image deferred" caveat is lifted.

**Next Step**: Sub-phase 4C.3 — `annotate.py` parent-orchestrator rewrite (chain `annotate_vcfanno` → `annotate_vep` stub; drop Phase-4A bcftools-annotate ClinVar path; triage the 7 existing `test_annotate.py` cases).

### 2026-05-11 — Phase-4-completion sub-plan + W1 + W2

**Context Review Completed**:
- Authored [phase-4-completion.md](phases/phase-4-completion.md) — a 7-item tactical sub-plan (W1–W7) sequencing the remaining Phase-4 work (4C.3, 4D, 4E) + the open follow-ups (pivot-debris doc, gnomAD field-name verify, ClinVar parity). 206 lines. The sub-plan reuses the architectural decisions in phase-4.md (Q1–Q10 + Q8.1); it's purely sequencing + gates.

**W1 — Pivot-debris cleanup note** ✅:
- Appended a 5-symptom recovery recipe to [docs/plans/completed/cram-scratch-strategy/work-notes.md](../../completed/cram-scratch-strategy/work-notes.md) under a new "Post-close: colima recovery recipe (added 2026-05-11)" section. Covers: orphan datadisk (symptom 1), malformed diffdisk (symptom 2), mosdepth `rc=-9` from under-provisioned VM memory (symptom 3), `PermissionError: '/.colima'` from setup-test home-dir fallback (symptom 4), `PermissionError: '/mnt/genomeclaw/scratch/'` from `--user $(id -u):$(id -g)` vs image's `chown genomeclaw` (symptom 5). Each symptom: diagnostic, cause, recovery. Cumulative recovery script at the end. The next contributor who hits this trap finds the recipe instead of debugging from scratch.

**W2 — gnomAD INFO field-name pre-flight** ✅, **with a substantive finding**:

Approach: HTTP Range request for the first 5 MB of `gs://gcp-public-data--gnomad/release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.chr22.vcf.bgz` (avoiding the 9 GB full download). Piped through `bcftools view -h -` via stdin (the colima VM had no host mounts after `colima delete` — see W1 symptom 5 cumulative recovery). Extracted 413 INFO field names.

Cross-check against `_GNOMAD_FIELDS = ("AF_grpmax_joint", "grpmax_joint", "AF_afr", "AF_amr", "AF_eas", "AF_nfe", "AF_sas")`:
- ✓ 5/7: `AF_afr`, `AF_amr`, `AF_eas`, `AF_nfe`, `AF_sas` present verbatim
- ✗ 2/7: `AF_grpmax_joint` / `grpmax_joint` **absent** — real names are `AF_grpmax` / `grpmax` (no `_joint` suffix)

**Root cause of my error**: gnomAD v4 publishes a separate "joint" frequency dataset that combines exomes + genomes; my plan's prior-knowledge assumption was that the joint fields would be embedded in the exomes-only sites VCF. They're not — the exomes-only sites VCF only carries exomes-specific stats. The `_joint` suffix exists in gnomAD's *joint* VCF (a different file we don't fetch in v0 per Q8.1).

**Patch applied (3 files)**:
- [annotate_vcfanno.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vcfanno.py): `_GNOMAD_FIELDS` updated to `("AF_grpmax", "grpmax", "AF_afr", "AF_amr", "AF_eas", "AF_nfe", "AF_sas")`. Docstring updated to record the verification + the `_joint`-suffix rationale.
- [tests/integration/test_annotate_vcfanno.py](../../../packages/toolkit/tests/integration/test_annotate_vcfanno.py): `_build_gnomad_exomes_release` fixture's INFO header + data row now use `AF_grpmax` / `grpmax`.
- [phase-4.md Q8](phases/phase-4.md): documented the verified field names + linked the verification provenance (date + bucket URL).

`_GNOMAD_NAMES` (the project-canonical column names — `gnomad_af_popmax`, `gnomad_af_popmax_pop`) are unchanged. The rename in vcfanno's TOML `names = [...]` lifts the upstream names to the project canonical ones; only the upstream side needed correcting.

**Gates re-run post-patch**:
- In-image: 9/9 pass (`test_vcfanno.py` × 3 + `test_annotate_vcfanno.py` × 6).
- Host: 158 passed, 63 skipped, ruff clean, format clean.

**Value of W2**: caught a silent zero-overlap bug **before** any real-data fetch. Without W2, the bug would have surfaced at the W4 ClinVar-parity smoke (which actually wouldn't have caught it — ClinVar uses different INFO fields and would still match; gnomAD overlay would silently produce NULL on every row), then at the W6 materialize finalisation smoke when `gnomad_af_popmax IS NOT NULL` counts came back at 0. Saved an unknown number of hours of multi-hour real-data run + debug cycles.

**Decisions Made**:

1. **HTTP Range for header probe, not full download.** GCS supports Range natively; bgzipped VCF headers fit in the first ~5 MB even for 9 GB VCFs (bcftools' header-only read terminates after the last `#` line). Saved ~20 min download. The `cat <file> | docker run -i ... bcftools view -h -` stdin pattern sidestepped the missing colima `mounts:` config (post-`colima delete`).

2. **Verify field names by header parse rather than by gnomAD docs.** gnomAD's online schema docs are version-skewed (the docs page lists fields that aren't always in every release; the joint-vs-exomes distinction is implicit). Reading the actual VCF header is the only ground-truth path.

3. **Keep `_GNOMAD_NAMES` stable; rename upstream→canonical at vcfanno staging.** The project-canonical column names (`gnomad_af_popmax`, etc.) are downstream-facing and should be insulated from upstream field-name churn. Future gnomAD releases that rename `grpmax` to something else are a one-line `_GNOMAD_FIELDS` patch; the host service routes + the materialize schema don't change.

**Follow-up Status Updates**:
- ✅ **W1 (pivot-debris note)** — landed.
- ✅ **W2 (gnomAD field-name verify)** — landed, surfaced a real bug, patched.
- 🟡 **W3 (4C.3 annotate parent rewrite)** — next session.
- 🟡 **W4 (ClinVar parity check)** — pending W3.
- 🟡 **W5–W7** — pending W3+W4.

**Session 1 of [phase-4-completion.md](phases/phase-4-completion.md) complete.** Total elapsed: ~35 min (10 min W1 doc + 15 min W2 fetch + 10 min patch + verify). The 5 W1-cumulative-symptom recovery recipe is durable; the W2 field-name bug catch was the kind of pre-flight value the protocol's "real-data smoke as a phase-completion gate" rule is meant to surface (here at a sub-gate, not phase-close).

**Next Step**: Session 2 — Sub-phase 4C.3 (W3). `annotate.py` parent rewrite + test triage. Estimated 1–2 hours.

### 2026-05-11 — Session 2: W3 (4C.3 annotate parent-orchestrator rewrite)

**Context Review Completed**:
- Re-read [phase-4-completion.md § W3](phases/phase-4-completion.md#w3--sub-phase-4c3-annotate-parent-orchestrator-rewrite-implementation-12-hours): scope is the parent-orchestrator rewrite + test triage (drop 4 Phase-4A-specific tests; keep 2 materialize-branch tests; add 3 chain tests).
- Re-read [annotate.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py) (the Phase-4A in-line ClinVar overlay) and [test_annotate.py](../../../packages/toolkit/tests/integration/test_annotate.py) (7 tests) to know exactly what's being replaced.
- Confirmed the `_resolve_clinvar` / chr-prefix-rename / shard_scratch / atomic_promote primitives are already in `annotate_vcfanno.py` (shipped 4C.2); the rewrite delegates rather than duplicates.

**Step 4C.3.1 — RED (test triage + new chain tests)**:

Rewrote [test_annotate.py](../../../packages/toolkit/tests/integration/test_annotate.py) from 7 tests to 5:
- **Dropped (4 Phase-4A-specific)**: `test_annotate_picks_newest_clinvar_when_release_is_none` (now covered by `_resolve_clinvar` in annotate_vcfanno's tests), `test_annotate_refuses_when_no_clinvar_present` (same), `test_annotate_refuses_when_normalize_has_not_run` (covered by `test_annotate_vcfanno_refuses_when_normalized_vcf_missing`), `test_annotate_records_inputs_in_provenance` (covered by `test_invR001_annotate_vcfanno_appends_step_to_provenance`).
- **Kept + adapted (3)**: `test_annotate_writes_annotated_vcf_in_run_dir` (happy path; updated to stage all 3 sources since the parent now chains annotate_vcfanno), `test_materialize_after_annotate_populates_clinvar_columns` + `test_materialize_fallback_to_normalized_when_annotated_missing` (materialize-branch end-to-end; updated to stage all 3 sources).
- **Added (2 NEW chain tests)**: `test_annotate_chains_vcfanno_then_promotes` (asserts vcfanno.vcf.gz survives mid-flight + annotated.vcf.gz is byte-identical to it as a 4C.3 stub — the assertion updates when 4D ships), `test_invR001_annotate_chains_provenance_steps` (asserts step trail post-parent is `["ingest", "bcftools-stats", "normalize", "vcfanno"]`).
- Replicated the 3-source staging helpers from test_annotate_vcfanno.py inline. Flagged as a Phase-4E extract candidate when a third caller surfaces.

Also dropped `test_annotate_uses_shard_scratch_and_atomic_promote` from [test_orchestrators_use_scratch_primitives.py](../../../packages/toolkit/tests/integration/test_orchestrators_use_scratch_primitives.py). That test was a structural assertion about Phase-4A's in-line `bcftools_annotate_clinvar` + `shard_scratch` + `atomic_promote` usage — exactly the internals the 4C.3 rewrite removes. The replacement coverage: `test_annotate_chains_vcfanno_then_promotes` confirms the chain works end-to-end; the structural `INV-D003` contract is now enforced inside `annotate_vcfanno` and verified by the existing needs_bio tests there. The materialize equivalent (`test_materialize_uses_shard_scratch`) stays — that orchestrator hasn't moved.

**RED confirmed in-image** (before any source edits): 2 new chain tests fail with the expected reasons (`vcfanno.vcf.gz` not produced; provenance step trail ends in `"annotate"` not `"vcfanno"`). 3 pre-existing-adapted tests pass (Phase-4A's annotate still produces `annotated.vcf.gz`, and the materialize tests' fixtures now include unused gnomad+dbsnp staging — passes regardless).

**Step 4C.3.2 — GREEN (annotate.py rewrite)**:

Replaced [annotate.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py) (was ~250 lines of in-line bcftools-annotate + chr-rename + scratch + atomic_promote) with a ~135-line thin parent that:

1. Asserts the four preflight invariants.
2. Validates run_dir / manifest.json / normalized.vcf.gz exist.
3. Calls `annotate_vcfanno(run_dir, reference_dir, clinvar_release=..., gnomad_exomes_release=..., dbsnp_release=..., started_at=...)`. That sub-orchestrator handles the scratch + chr-prefix-rename + 4 vcfanno overlay blocks + atomic_promote into `run_dir/vcfanno.vcf.gz` + provenance step.
4. **Phase 4D placeholder**: where `annotate_vep(...)` will plug in. Until 4D ships, the parent simply `shutil.copyfile`s `vcfanno.vcf.gz` → `annotated.vcf.gz` + `.tbi` so the materialize contract (read from `annotated.vcf.gz`) keeps working. When 4D lands, `annotate_vep` reads `vcfanno.vcf.gz`, runs VEP, and atomic-promotes its output to `annotated.vcf.gz` — replacing this stub copy.
5. Updates `manifest.outputs.annotated_vcf` + sha256 + `.tbi` sha256.
6. **Does not** add its own provenance step. The chain's authoritative record is the sub-orchestrator step trail (`vcfanno` from 4C.2, eventually `vep` from 4D). The parent is a coordinator; the per-step traceability lives at the sub-orchestrator level. Net effect: provenance step trail post-`annotate(...)` is `["ingest", "bcftools-stats", "normalize", "vcfanno"]`.

Dropped imports: `_bcftools.bcftools_annotate_clinvar`, `_bcftools.bcftools_index_tbi`, `_bcftools.bcftools_run`, `_bcftools.bcftools_version`, `scratch.atomic_promote`, `scratch.shard_scratch`. The `_CLINVAR_TO_GRCH38_CHR_MAP` constant moved to `annotate_vcfanno.py` during 4C.2 and is removed from annotate.py.

**Gate results**:
- **In-image full suite**: 218 passed, 0 failed (was 221 at 4C.2 close; net -3 = -4 dropped 4A tests + 2 new chain tests - 1 structural-primitives test).
- **Host full suite**: 157 passed, 61 skipped (was 158 at 4C.2; net -1 = the dropped structural-primitives test, which was host-runnable).
- Ruff + format clean.

**Step 4C.3.3 — REFACTOR**: nothing structural to clean up; annotate.py dropped from ~250 lines to ~135 lines (~46% smaller). The Phase-4A-era `bcftools_annotate_clinvar` helper in `_bcftools.py` is now unused — flagged below as a follow-up for cleanup when a future change touches that module.

**Decisions Made**:

1. **Phase 4D stub uses `shutil.copyfile`, not `atomic_promote`.** Both src + dst live in `derived/<run-id>/` (same dir, same filesystem). `atomic_promote` is designed for scratch → derived transfers where the rename ensures derived/ never sees a partial. Within-derived copy doesn't need that atomicity — `materialize` doesn't run concurrently with `annotate` (the pipeline serializes per run). When 4D ships, `annotate_vep` is the one that does scratch → derived via `atomic_promote`; the parent stays a coordinator.

2. **The parent doesn't add its own provenance step.** Alternative: append an `annotate` step recording "vcfanno ran; vep stub no-op". Rejected: noisy + redundant. The sub-orchestrator step trail is the authoritative record. A reader inspecting `provenance.json` sees the actual tools that ran (vcfanno, eventually vep) without a coordinator-level wrapper.

3. **Materialize-branch tests (`test_materialize_after_annotate_*`) move to use 3-source staging.** The dropped Phase-4A tests' clinvar-only fixture wouldn't work with the new chained orchestrator (annotate_vcfanno needs all 3 sources to resolve, even if dbsnp/gnomad don't have matches for every variant). Adapting the fixtures was a 1-line change per test.

4. **`test_annotate_uses_shard_scratch_and_atomic_promote` deleted, not rewritten.** Could have been retargeted at `annotate_vcfanno`. Rejected: the structural contract (annotate_vcfanno uses the primitives) is implicit in the existing needs_bio tests for annotate_vcfanno — those tests would fail if `shard_scratch` or `atomic_promote` were absent. Adding a monkey-patched structural test on top of the integration tests is belt-and-suspenders for low risk; the integration tests already cover it.

**Follow-up flagged** (out of scope for 4C.3):
- `bcftools_annotate_clinvar` in `_bcftools.py` is now unused. Worth removing in a future cleanup pass; not urgent (3 lines + a docstring).

**Phase 4C.3 status: complete.** The annotate parent-orchestrator chain is wired; `annotated.vcf.gz` is produced correctly; materialize reads it; the v0.2 ClinVar / gnomAD / dbSNP columns populate correctly end-to-end.

**Next Step**: Session 3 — W4 (ClinVar match-count parity check on the project owner's real Nebula VCF). ~30 min wall time. Per the [phase-4-completion plan](phases/phase-4-completion.md#w4--clinvar-match-count-parity-check-real-data-smoke-30-min), the gate is "within 1% of the 42,885 Phase-4A baseline."

### 2026-05-12 — W4 attempted; pipeline failed; 4C.4 sub-plan authored; MVP paused for rich-cli migration

**Context**: W4 (ClinVar parity check) ran against the project owner's real Nebula VCF + canonical reference layout for the first time. `bin/genomeclaw-prep pipeline` failed mid-`annotate-vcfanno`. Diagnostic surfaced three correctness gaps:
1. dbSNP b157 uses NCBI RefSeq accession contigs (`NC_000001.11`) — never renamed by our code. Result: 0 dbsnp_rsid annotations.
2. vcfanno crashed mid-stream on `chr6.vcf.bgz: EOF`. Forensics confirmed **5 of 24 gnomAD chrom files silently truncated** by the fetcher (chr6, chr7, chr9, chr10, chr11). Root cause: [prep/fetch.py:413-457](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py) never verifies `Content-Length` match — a clean mid-stream HTTP close yields a truncated file accepted as complete.
3. CLI stderr output buried the actual fatal line in 10k+ lines of expected-but-noisy `bix.go:251` warnings.

**Decisions taken (2026-05-12)**:
- Authored [phase-4c4-annotation-correctness.md](phases/phase-4c4-annotation-correctness.md) — a tactical 7-work-item sub-plan covering fetcher integrity + resume + dbSNP rename + pre-flight validator + stderr discipline + W7 parity rerun.
- Authored [docs/plans/active/rich-cli/](../../active/rich-cli/) — initially a 6-phase plan migrating the entire CLI toolchain to Typer + rich + structured JSON output for AI agents; restructured 2026-05-12 to 8 phases after honest sizing of Phase 3 + the fat Phase 4.
- **Project owner directed (2026-05-12): finish the rich-cli migration completely before resuming MVP**. The MVP plan goes on hold. The fetcher correctness fixes from 4C.4 (W1 + W1.5) **shipped in rich-cli Phase 3** (2026-05-12). The remaining 4C.4 work (W2–W7) waits for MVP resume after rich-cli Phase 8 closes — with W3 (re-fetch the 5 truncated gnomAD files) resumable after rich-cli Phase 4, since `refs fetch` becomes observable enough to run with confidence at that point.

**State at pause**:
- Phase 4C.3 complete — annotate parent-orchestrator chain shipped; 218 in-image tests + 157 host tests green at close.
- Phase 4C.4 paused — diagnostic done, plan published, no code changes yet.
- 5 truncated reference files (chr6/7/9/10/11) remain on disk in their incomplete state. The user's real-genome W7 parity check (the Phase-4 closure gate) is deferred until rich-cli completion + 4C.4 resume.
- Last known good toolkit image: `genomeclaw/toolkit:dev` built post-Phase-4C.3.

**Next Step on MVP resume** (after rich-cli Phase 8 closes — or partial resume after rich-cli Phase 4):
1. **After rich-cli Phase 4 (refs fetch UX shipped)**: W3 (re-fetch 5 truncated files) using the new resume-capable + observable fetcher. This can happen partway through rich-cli without waiting for the full migration.
2. **After rich-cli Phase 8 (full migration closed)**: Restart 4C.4 from W2 (doctor integrity sweep) through W7 per the [phase-4c4 plan](phases/phase-4c4-annotation-correctness.md). W1 + W1.5 already shipped in rich-cli Phase 3.
3. On W7 parity-check pass: close Phase 4 of MVP; resume per the [development-plan.md § Phase Overview](development-plan.md#phase-overview) (Phase 5: host service).

**Procedure updates pending after rich-cli closes**: every `bin/genomeclaw-prep <verb>` example in [phase-4-completion.md](phases/phase-4-completion.md) + [phase-4c4-annotation-correctness.md](phases/phase-4c4-annotation-correctness.md) gets rewritten to `bin/genomeclaw <group> <verb>` (handled as part of rich-cli Phase 8's repo-wide migration sweep).

---

## Phase Progress

### Phase 1: Repo scaffolding & test infrastructure
**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08

#### Test Results
- RED (initial run): 4 failed (`test_package_imports`, `test_cli_help_runs`, `test_subpackages_exist`, `test_test_categories_directories_exist`) — `ModuleNotFoundError: genomeclaw_toolkit`, missing `genomeclaw-prep` script, missing test category dirs.
- GREEN (after scaffold): `uv run pytest -q` → `4 passed in 0.06s`.
- Lint: `uv run ruff check .` → `All checks passed!`
- Format: `uv run ruff format --check .` → `14 files already formatted`.
- CLI smoke: `uv run genomeclaw-prep --help` exits 0 and lists the five planned subcommands (`fetch`, `ingest`, `normalize`, `annotate`, `materialize`).

#### Results
- `packages/toolkit/` Python package created (`uv` + `hatchling`); console-script `genomeclaw-prep` registered.
- Subpackages `cli` (module), `prep`, `service`, `schemas` all importable.
- Seven first-class test category dirs created with `__init__.py`: `integration/`, `provenance/`, `determinism/`, `privacy/`, `evidence/`, `reports/`, `invariants/`.
- `.github/workflows/test.yml` runs `uv sync` → `pytest -q` → `ruff check` → `ruff format --check` on push/PR.
- `packages/toolkit/README.md` documents local install + test commands.

#### Notes
- `uv sync` selected CPython 3.13.1 (locally available) under the `>=3.11` constraint; CI pins 3.11. Kept the constraint at 3.11 to match the spec.
- Subcommands print a non-zero "not implemented" notice when invoked without a real handler, so accidental Phase-2 invocation fails loudly instead of silently no-oping.
- `uv.lock` committed alongside `pyproject.toml` so CI reproduces the locked dep set.

---

## Key Decisions

_(decisions land here as phases run)_

---

## Files Modified

### Created
- `packages/toolkit/pyproject.toml`
- `packages/toolkit/README.md`
- `packages/toolkit/src/genomeclaw_toolkit/__init__.py`
- `packages/toolkit/src/genomeclaw_toolkit/cli.py`
- `packages/toolkit/src/genomeclaw_toolkit/{prep,service,schemas}/__init__.py`
- `packages/toolkit/tests/__init__.py`
- `packages/toolkit/tests/test_smoke.py`
- `packages/toolkit/tests/{integration,provenance,determinism,privacy,evidence,reports,invariants}/__init__.py`
- `.github/workflows/test.yml`
- `packages/toolkit/uv.lock` (generated by `uv sync`)
- `packages/toolkit/Dockerfile` (host-image Decision Taken 2026-05-08)
- `packages/toolkit/.dockerignore` (host-image Decision Taken 2026-05-08)
- `bin/genomeclaw-prep` (host shim, Decision Taken 2026-05-08)

### Modified
- `packages/toolkit/pyproject.toml` — added `needs_bio` pytest marker (Decision Taken 2026-05-08).
- `.github/workflows/test.yml` — added the `toolkit-image` job (Decision Taken 2026-05-08).
- `docs/plans/active/mvp/development-plan.md` — Decision Taken #10 (host image).
- `docs/plans/active/mvp/phases/phase-2.md` — Verification + Files table updated to image-based flow.
- `docs/reference/architecture.md` — new "Host-side packaging" section + component-blurb tweaks.

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None expected. If Phase 7's sweep surfaces a needed invariant, propose it then.

### Other Documentation
- [ ] [architecture.md](../../reference/architecture.md) — update any drift discovered during implementation
- [ ] [grand-plan.md](../../reference/grand-plan.md) — advance Horizon 1–3 to "delivered" after Phase 7
- [ ] [README.md](../../../README.md) — replace placeholder "Getting Started" with the real commands
- [ ] [user-stories.md](../../reference/user-stories.md) — mark resolved gap-analysis items

---

## Open Risks & Follow-ups

- Plugin tool-return shape (Q2) is unresolved until Phase 5.
- Annotator choice (Q1) is locked to SnpEff unless Phase 4 fixture performance forces a switch.
- Sandbox image size is unmeasured; check in Phase 5.
- Real-genome end-to-end run is Phase 7 only; the project owner's VCF must never enter CI.

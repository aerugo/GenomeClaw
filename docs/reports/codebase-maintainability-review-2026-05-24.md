# Codebase Maintainability Review

**Date**: 2026-05-24
**Scope**: repository-wide structural, typing, convention, and maintainability audit
**Method**: parallel fact-gathering across four review axes (architecture, typing, code quality, testing), synthesized in this document
**Audience**: contributors and maintainers triaging where to invest engineering effort next

---

## 0. TL;DR

GenomeClaw is in **substantially better shape than its phase-of-life implies**. Layering is clean, the privacy/provenance invariants are mirrored by structural tests, and the strict-typed core (`_cli`, `schemas`, `nemoclaw-plugin`) is genuinely strict. The maintainability surface has three concentrated risks worth investing in next:

1. **Legacy `prep/` annotation debt** — ~30 mypy errors and ~0% return-type coverage outside the seven graduated modules.
2. **Three large modules** (`fetch.py`, `pipeline.py`, `coverage_fill.py`) carry most of the >150-line functions; `fetch.py` mixes too many concerns.
3. **Subprocess invocation is inconsistent** — `_bcftools` has a clean wrapper, but `coverage_fill.py` mixes `run` and `Popen` without shared error/timeout discipline.

Two test-tree gaps are worth tracking: `tests/evidence/` and `tests/reports/` are empty placeholders, and `tests/determinism/` has a single file that is fully `needs_bio`-gated (zero passing on a bare host).

Everything else (architecture, schemas, CLI ergonomics, invariant test discipline) is in good condition.

---

## 1. Repository Structure

```text
/
├── bin/                              # thin Bash orchestration harnesses
│   ├── genomeclaw                    # docker-run wrapper (~420 lines, DooD-aware)
│   └── genomeclaw-prs-smoke          # Phase 5 real-data driver
├── packages/
│   ├── toolkit/                      # Python: host-side CLI + FastAPI service
│   │   └── src/genomeclaw_toolkit/
│   │       ├── _cli/                 # command surface, error boundary, renderers
│   │       ├── prep/                 # ingest|normalize|annotate|materialize|pgs|cyp2d6|pharmcat
│   │       ├── schemas/              # Pydantic v2 models (the shared contract)
│   │       ├── service/              # FastAPI read-only service + compute orchestrator
│   │       ├── memory/               # agent memory-note validator (INV-A001)
│   │       └── data/                 # bundled reference assets (coverage panel)
│   └── nemoclaw-plugin/              # TypeScript: agent-callable plugin (one file, ~650 lines)
├── tools/                            # convention-probe scripts (NOT vendored tools)
│   ├── cyrius/probe.sh
│   ├── pgsc_calc/probe.sh
│   └── pharmcat/probe.sh
└── docs/
    ├── reference/                    # INVARIANTS.md, architecture.md, grand-plan.md
    ├── plans/                        # active/, completed/, templates/ — phased plan ledger
    └── reports/                      # this directory
```

The convention is **two production languages, two deployment domains**, mirrored by the two packages:

- `packages/toolkit/` runs on the host (Python 3.11, mypy-strict, ruff-strict in graduated regions).
- `packages/nemoclaw-plugin/` runs in the sandbox under OpenShell (Node ≥22, TypeScript with the strictest tsconfig).

The `tools/` directory is **misleadingly named** — it contains `probe.sh` scripts that document external-tool argv/samplesheet contracts so the in-toolkit wrapper code can stay pinned. The actual binaries (pgsc_calc, Cyrius, PharmCAT) ship inside the toolkit Docker image. Worth noting: the probes are documentation artifacts, not vendored source.

---

## 2. Architecture and Module Boundaries

### 2.1 Layering as implemented

| Layer | Direction | Notes |
|---|---|---|
| `_cli` | → `prep`, `service`, `schemas` | Single entry point at `_cli/__init__.py:189`; central exception boundary at `_cli/__init__.py:196-267` |
| `prep` | → `prep` only | Self-contained pipeline phases; no upward edges |
| `service` | → `prep`, `schemas` | FastAPI app at `service/app.py`; compute worker at `service/pgs_compute_orchestrator.py` |
| `schemas` | (leaf) | Pydantic v2 models shared across layers |
| `memory` | (leaf) | Specialized, validates agent memory-note shape |
| `nemoclaw-plugin` | (separate package) | HTTP-only; no file I/O; no bioinformatics logic |

**No circular imports detected.** Dependencies flow unidirectionally upward through the diagram in [docs/reference/architecture.md](../reference/architecture.md).

### 2.2 One intentional cross-layer call

`service/pgs_compute_orchestrator.py` imports `prep.coverage_fill`, `prep.pgs`, `prep.fetch`. This looks like a layering violation at first glance — the read-only service calling back into the heavyweight compute layer — but it is **intentional**: the orchestrator is an in-process `asyncio` task spawned by the FastAPI lifespan hook and documented as such in architecture.md. The dependency is unidirectional (prep does not import service). Acceptable.

### 2.3 Bin scripts are thin

Both `bin/genomeclaw` and `bin/genomeclaw-prs-smoke` are orchestration harnesses, not duplicates of toolkit logic. `bin/genomeclaw` implements INV-D005 (identical-path bind mounts for DooD siblings) and routes `host setup/doctor/eject` natively because they touch `diskutil` / `colima`. The shape is sound.

### 2.4 Architecture doc agreement

`docs/reference/architecture.md` (58 KB) describes layers, components, network topology, and invariant traceability. The doc and the code agree on essentially everything we sampled. Mild lag exists in the "Phase 1 scaffolding" language for the service, which now exists at Phase 5 — expected drift in a living plan-of-record document.

---

## 3. Type Safety

### 3.1 What is strict, today

| Region | Strictness | Status |
|---|---|---|
| `_cli/` | mypy `strict = true` | ✅ 24 files, **0 errors** |
| `schemas/` | Pydantic v2 + `extra="forbid"` | ✅ Tight field types; no `dict[str, Any]` escapes |
| `nemoclaw-plugin/` | tsconfig `strict` + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes` | ✅ TypeBox schemas; **zero `any` usage** |
| `prep/` graduated modules (7) | ruff `ANN` enforced | ✅ `_bgzip`, `runs`, `references`, `ingest`, `normalize`, `annotate`, `materialize` |
| `prep/` legacy modules (~30) | ruff `ANN` disabled per [pyproject.toml:127-130](../../packages/toolkit/pyproject.toml#L127-L130) | ⚠️ Annotation debt |

### 3.2 Annotation debt sample

Return-type annotation coverage in non-graduated `prep/` modules:

| Module | Functions | With `->` | Coverage |
|---|---|---|---|
| `annotate_vcfanno.py` | 13 | 1 | 7% |
| `pgs.py` | 9 | 0 | 0% |
| `pharmcat.py` | 8 | 0 | 0% |
| `cyrius.py` | 1 | 0 | 0% |

The graduation pattern documented in `pyproject.toml:131-144` is the right escape route — modules join the strict scope per-module as their callers move. Worth noting: there are **30 mypy errors** when the strict scope is expanded to all of `src/genomeclaw_toolkit/`, concentrated in `prep/setup/platform.py` (5), `prep/pgs.py` (5), `prep/fetch.py` (4), `service/store.py` (1), `prep/setup/run.py` (1).

### 3.3 `Any` and `# type: ignore`

- **`Any` usage**: 7 instances across `src/`. All justified (signal handlers, untyped config dicts, untyped library boundaries).
- **`# type: ignore`**: 28 instances. Most are scoped (`[attr-defined]`, `[arg-type]`, `[union-attr]`). Several `[union-attr]` suppressions in `prep/pgs.py:547-589` are now reported as **unused ignores** by mypy — a small janitorial task.

### 3.4 Schema quality

The Pydantic models in `schemas/` set the bar for the rest of the codebase: precise field types, `extra="forbid"` to prevent schema creep, and a single deliberate loose escape (`params: dict[str, object]` in `provenance.py:41`) that is scoped and documented. The `PROVENANCE_COLUMNS` tuple in `schemas/__init__.py:27-35` is the canonical 7-column trail referenced by INV-R001 — a strong example of "the contract lives in one place."

---

## 4. Conventions and Code Style

### 4.1 Error handling

A clear custom-exception taxonomy in `_cli/errors.py`:

- `CliError` base + `RuntimeFailure`, `UsageError`, `PreconditionError`, `DataIntegrityError`
- Tool-specific errors: `BcftoolsError`, `VepError`, `VcfannoError`, `IncompleteBgzip`, `MosdepthError`, `DooDPathError`, `PRSDeclineError`
- 17 custom types in total, each with clear scope and a documented exit-code contract (0, 1, 2, 3, 4, 130)

Broad `except Exception` is used responsibly — the top-level boundary at `_cli/__init__.py:256` wraps unstructured exceptions as `InternalError`, which is exactly what a CLI entry point should do.

**One soft spot**: `service/pgs_compute_orchestrator.py:628-646` silently catches and discards job-cleanup errors with no retry or escalation. Worth a follow-up.

### 4.2 Subprocess invocation — inconsistent

`prep/_bcftools.py:82-100` defines a clean `bcftools_run()` wrapper (capture, error-to-typed-exception). However:

- `prep/fetch.py` calls `subprocess.run()` inline for samtools and gunzip post-processing (no shared wrapper)
- `prep/coverage_fill.py` mixes `subprocess.run()` and `subprocess.Popen()` for bcftools pipes and plink2 (lines 38, 304, 309, 1067); some plink2 invocations lack explicit error checking

The pattern is right where it exists. Extending it to plink2 and samtools would reduce surface area for leaks and inconsistent error handling.

### 4.3 Logging vs print

Standard library `logging` is the norm. `print()` appears ~94 times in `src/`, almost all in `prep/fetch.py` for streaming download progress to the user. Acceptable trade-off; not a refactor priority. The `_cli/console.py` module exports a `get_console()` singleton that writes Rich output to stderr while keeping stdout reserved for JSON — a good discipline for a CLI that has both interactive and machine-readable outputs.

### 4.4 Version pinning is centralized

`prep/_versions.py` is the single source of truth: `PRS_RUNTIME_VERSIONS`, `PGX_RUNTIME_VERSIONS`, `collect_tool_versions()`, `image_digest()`. Path constants in `prep/_paths.py` are equally centralized (`_CANONICAL_MOUNT_ROOT`, `_CANONICAL_MOUNT_TRANSLATION`, `SiblingMountablePath`). **No `TODO`, `FIXME`, or `HACK` markers found anywhere in `src/`** — unusual for a project this size and a meaningful signal of upkeep discipline.

---

## 5. Code Quality Hotspots

Top 3 files by line count:

| File | LoC | Functions >150 lines | Concerns |
|---|---|---|---|
| `prep/fetch.py` | 1,654 | 5, incl. `_extract_vep_cache_tarball` (348) and `_human_bytes` (185 — appears mis-named or misattributed; worth re-checking) | Multi-source download orchestration mixed with retry/resume, MD5 verification, tarball extraction, bgzip validation |
| `_cli/commands/pipeline.py` | 1,464 | 4, incl. `pipeline_prs_compute` (237) and `pipeline_run` (187) | Multi-step orchestration with event-callback plumbing; size is justified, splitting would fragment the user-facing command surface |
| `prep/coverage_fill.py` | 1,388 | 1, `compute_prs_with_coverage_fill` (199) | Tier 1/Tier 2 genotyping orchestrator; well-chunked internally |

**`fetch.py` is the primary refactor candidate.** A 348-line `_extract_vep_cache_tarball` handling tar I/O + decompression + indexing would be cleaner as a dedicated module, and the HTTP retry/resume logic is independent of file I/O. The other two are large but cohesive — the size reflects orchestration responsibility.

### 5.1 Duplication audit

`annotate.py`/`annotate_vcfanno.py`/`annotate_vep.py` and `_bcftools.py`/`_bcftools_norm.py`/`_bcftools_stats.py` look like duplicate-prefix smells from the outside but are **cleanly separated by responsibility** on inspection. The shared `bcftools_run()` wrapper is the cohesion point. No refactor needed.

---

## 6. Testing Strategy

### 6.1 Coverage shape

| Directory | Test files | Notes |
|---|---|---|
| `integration/` | 114 | Outsized — likely contains tests that belong in more specific categories |
| `unit/` | 20 | Focused, fast |
| `invariants/` | 15 | Strong INV-ID filename discipline (with 3 exceptions) |
| `provenance/` | 4 | All `test_invR001_*` — clean naming |
| `privacy/` | 2 | Real-boundary tests (not mocks-of-mocks) |
| `perf/` | 2 | One file documents the 4h09m → ~1s regression budget |
| `determinism/` | 1 | All 3 tests are `needs_bio`-gated — **zero passing on bare host** |
| `evidence/` | 0 | Empty placeholder |
| `reports/` | 0 | Empty placeholder |

The integration directory is doing too much heavy lifting — 114 files is hard to navigate, and several tests that look structural (e.g., live-LLM snapshot tests) live there alongside true integration coverage.

### 6.2 Strengths

- **Invariant ID discipline**: 19 distinct `INV-xxx` IDs appear in test names; INV-R001, INV-C001, INV-P001 each cited 50–70 times across the suite. The convention is real and load-bearing.
- **Privacy tests are structural**: `tests/privacy/test_invP001_cli_no_egress.py` asserts that 16 CLI surfaces make no outbound HTTP under a real mock of `urllib.request.urlopen` — this tests the boundary, not a mock of the boundary.
- **Skip discipline is centralized**: 4 of 5 `needs_*` markers are evaluated in `pytest_collection_modifyitems` at [conftest.py:40](../../packages/toolkit/tests/conftest.py#L40). Bare-host `pytest` runs green without any bio binaries.
- **Conftest fixtures are well-designed**: `tiny_vcf_gz`, `tiny_unindexed_vcf_gz`, `tiny_ambiguous_vcf_gz`, `tiny_bam`, `tiny_cram`, `tiny_genes_bed`, `tiny_grch38_fasta` (session-scoped synthetic artifacts) are the load-bearing primitives.

### 6.3 Gaps

- `tests/evidence/` and `tests/reports/` are empty (`__init__.py` only). INV-E001 has only 11 references, all in `integration/` — no dedicated category exists for evidence-binding or report-rendering tests.
- `tests/invariants/` has no `INV-R001`, `INV-R002`, or `INV-C001` files; that coverage lives in `provenance/` and `determinism/`. Acceptable, but means there is no single canonical home for an INV-xxx audit walk.
- `tests/determinism/` is one file, fully `needs_bio`-gated. The category produces zero passing tests on a bare host.
- `needs_prs_runtime` and `needs_prod_python` share the same env var (`GENOMECLAW_TOOLKIT_PRS_IMAGE`) — enabling one silently enables both.
- `needs_sandbox` is the one marker whose skip lives inside a fixture (`sandbox_image`) rather than `pytest_collection_modifyitems` — inconsistent with peers.

### 6.4 Brittle patterns

- `test_invP001_no_egress_during_help` and `test_invP001_no_egress_during_version_flag` (in `tests/privacy/test_invP001_cli_no_egress.py`) monkeypatch `urllib.request.urlopen` at the module level with `urllib.request.urlopen = fail` rather than via the `monkeypatch` fixture. If the test errors before the `finally`, the global is corrupted for the rest of the process.
- `test_live_story*.py` (in `tests/integration/`, `live_llm`-gated) assert on prose presence ("mentions the gene + phenotype"). Correctly gated, but not structurally protected against semantically-equivalent prompt reformulations.

### 6.5 Plugin tests

`packages/nemoclaw-plugin/tests/index.test.ts` (540 lines) is well-targeted: tool registration, TypeBox parameter validation, URL routing, error surfaces, config resolution, INV-P002 output-class assertion. No retry/backoff test, no `outputClass: bulk` path test, no timeout assertion — modest gaps.

---

## 7. Maintainability Risks (Ranked)

| # | Risk | Severity | Where |
|---|---|---|---|
| 1 | Legacy `prep/` annotation debt — ~30 mypy errors, ~0% return-type coverage outside the 7 graduated modules | **Medium** | `prep/setup/platform.py`, `prep/pgs.py`, `prep/fetch.py`, `service/store.py` |
| 2 | `fetch.py` mixes too many concerns (HTTP, retry, tarball, MD5, bgzip validation) | **Medium** | `prep/fetch.py:1-1654` |
| 3 | Subprocess invocation is inconsistent (clean `_bcftools` wrapper, ad-hoc elsewhere) | **Medium** | `prep/coverage_fill.py`, `prep/fetch.py` |
| 4 | `pgs_compute_orchestrator.py:628-646` silently swallows job-cleanup errors | **Low–Medium** | `service/pgs_compute_orchestrator.py:628-646` |
| 5 | Stale `# type: ignore[union-attr]` in `prep/pgs.py:547-589` (mypy reports unused) | **Low** | `prep/pgs.py:547-589` |
| 6 | `tests/integration/` is overloaded (114 files); `evidence/` + `reports/` empty | **Low** | test tree organization |
| 7 | `tests/determinism/` is fully `needs_bio`-gated — zero bare-host coverage | **Low** | `tests/determinism/test_invR001_full_pipeline.py` |
| 8 | `needs_prs_runtime` and `needs_prod_python` share one env var | **Low** | `tests/conftest.py:91, 111` |
| 9 | Privacy test monkeypatches `urllib.request.urlopen` globally without `monkeypatch` fixture | **Low** | `tests/privacy/test_invP001_cli_no_egress.py` |

---

## 8. Recommendations

Investment ranking, ordered by leverage:

1. **Continue the `prep/` graduation pattern**. Move the four error-bearing modules into the strict ANN scope per-module (`pyproject.toml:131-144` already documents the pattern). Audit and trim stale `# type: ignore` comments at the same time.
2. **Refactor `prep/fetch.py`**. Extract tarball extraction to a dedicated module, separate HTTP retry/resume from file I/O. This is the single largest module-shape problem in the codebase.
3. **Centralize subprocess invocation**. Promote the `bcftools_run()` shape to a generic wrapper covering plink2, samtools, gunzip — same capture, same typed-exception conversion, same timeout policy.
4. **Backfill `tests/evidence/` and `tests/reports/`**, or remove the empty directories. Right now they signal an intent that has never been filled, which is a documentation lie.
5. **Add a bare-host determinism test** that operates on synthetic VCFs rather than `needs_bio` binaries. The current single file produces zero passing tests on a bare host, which means the determinism category effectively does not run in CI.
6. **Split `tests/integration/`**. 114 files in one directory is hard to navigate; identify which tests are truly cross-component and which belong in invariants/, provenance/, or unit/.
7. **Fix the `needs_prod_python` / `needs_prs_runtime` env-var collision**. Separate gates would let CI exercise one without silently enabling the other.
8. **Use `monkeypatch` for the two `urllib.request.urlopen` patches** in privacy tests. Removes a process-state corruption risk on test error.

---

## 9. Appendix: What This Review Did Not Cover

- **Performance** beyond what `tests/perf/` already encodes
- **Dependency security** (no SCA was run; `uv.lock` and `package-lock.json` were not audited)
- **Doc coverage of `prep/` internals** — `prep/` modules are documented enough for a competent reader, but a structured per-module summary doc does not exist
- **The `nemoclaw-plugin` index.ts at full depth** — sampled for structure, not line-by-line
- **The Dockerfile** at `packages/toolkit/Dockerfile` (23KB) — large and worth its own focused review
- **Runtime behavior** — this is a static review only; no `pytest` or `bin/genomeclaw` execution was performed

---

## 10. Cross-References

- [CLAUDE.md](../../CLAUDE.md) — project invariants and working-style expectations
- [docs/reference/INVARIANTS.md](../reference/INVARIANTS.md) — canonical INV-xxx rules
- [docs/reference/architecture.md](../reference/architecture.md) — layered design of record
- [packages/toolkit/pyproject.toml](../../packages/toolkit/pyproject.toml) — typing/lint configuration
- [packages/nemoclaw-plugin/tsconfig.json](../../packages/nemoclaw-plugin/tsconfig.json) — TypeScript strictness configuration

# PRS Input Coverage Fill — Work Notes

**Feature**: Two-tier targeted forced-genotyping cache so `pgsc_calc --run_ancestry` works on Nebula variant-only WGS
**Started**: 2026-05-18
**Branch**: TBD
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-18 — Phase 2 Implementation (Tier 2 + merge + cache semantics)

**Context Review Completed**:
- Re-read Phase 2 deliverables in [development-plan.md](development-plan.md).
- Reused the Phase 1 test idioms (regex-based bcftools fake parsing `--output` path).
- Confirmed Open Question Q2 stance — Tier 2 SNP-only for MVP, indel concordance deferred.

**Applicable Invariants** (Phase 1 carryovers):
- INV-D001 (CRAM read-only — `_force_genotype_tier2` checks `.crai`).
- INV-D003 (scratch staging via `shard_scratch` + `atomic_promote`).
- INV-R001 (cache path embeds scorefile SHA8 → upstream silent re-harmonisation forces rebuild).
- INV-P001 (no new egress).

**RED step output**:

```text
tests/integration/test_prs_coverage_fill_tier2.py  9 ImportError on:
  _extract_pgs_sites_from_scorefile, _extract_pgs_id_from_scorefile,
  _tier2_cache_path, _force_genotype_tier2, _merge_tier1_tier2,
  prepare_coverage_tier2
9 failed in 0.04s — all imports against the absent Tier 2 surface.
```

**Completed Today (Phase 2 — 9 new tests, all GREEN)**:
- [x] `_extract_pgs_sites_from_scorefile` — parses hmPOS_GRCh38 scoring files; SNP-only (indels filtered per Q2); panel→CRAM `chr` prefix rewrite; robust to PGS Catalog comment + blank header lines.
- [x] `_extract_pgs_id_from_scorefile` — pulls `#pgs_id=` out of the header section.
- [x] `_tier2_cache_path` — keyed by `(sample, panel, pgs_id, scorefile_sha8)`. Layout: `derived/prs_coverage/<sample>/<panel>/pgs/<PGS_ID>-<sha8>/tier2.vcf.gz`.
- [x] `_force_genotype_tier2` — same `bcftools mpileup → call → norm` pipe as Tier 1; PGS-derived sites/alleles TSVs are scratch-only (never persisted, deterministic from the scoring file).
- [x] `_merge_tier1_tier2` — `bcftools concat --allow-overlaps | bcftools sort` + `index --tbi`. Single `bash -c` pipe for atomicity.
- [x] `prepare_coverage_tier2` — orchestrator with cache-hit short-circuit; writes `tier2.qc.json` with INV-R001 provenance (scorefile SHA, PGS ID, bcftools version, SNP row count, GT distribution, mean DP, per-chrom counts).

**Decisions Made**:
- **REF/ALT orientation from PGS Catalog scoring files**: `other_allele` → REF, `effect_allele` → ALT. PGS Catalog convention (post-2021 scoring files) puts `other_allele` matching the reference. `bcftools --constrain alleles` accepts any pair regardless of orientation; pgsc_calc later normalises.
- **Two-tier cache directory layout**: `pgs/<PGS_ID>-<sha8>/` not `pgs/<PGS_ID>/<sha8>/`. Flat per-PGS dirs surface cache invalidation cleanly (a directory listing shows the sha8 suffix changing); also makes a future `prs cache-gc` step easy ("delete any `pgs/<id>-*` dir whose scorefile sha8 isn't current").
- **Both tiers reuse `_build_bcftools_pipe`**. The bcftools mpileup → call → norm pipe is identical; only the sites/alleles TSV source differs. No duplication, single rule for changes (e.g. when bumping `--max-depth`).
- **Tier 2 sites/alleles TSVs are scratch-only**, not promoted to derived. They're trivially regenerable from the scoring file and would otherwise duplicate data already on disk.

**Blockers / Issues**:
- None. Phase 2 cleanly extended the Phase 1 surface; no Tier 1 refactor needed.

**REFACTOR step**:
- ruff: one unused-import fix in the test file (auto-applied).
- mypy: replaced `# type: ignore[index]` comments with explicit `assert *_col is not None` blocks. Mypy narrows correctly from the asserts; the type-ignores were stale once the upstream `if None in (...) raise ValueError` guard landed.
- Full suite: 636 passed / 104 skipped / 0 failed (Phase 1 baseline was 627/104; +9 Phase 2 tests).

**Phase 2 status — COMPLETE**:
- 9 new tests covering Tier 2 force-genotyping, merge, scoring-file parsing, cache invariance.
- Total plan progress: 30 tests across Phase 1a + 1b + 2, all GREEN (1 `needs_bio`-gated skip).

**Next Steps**:
1. Commit Phase 2 (or batch with Phase 1).
2. Phase 3 (QC threshold table + 5-named-reasons decline taxonomy + `INV-C001` v1.7 typed exceptions + `INV-A003` rationale persistence). Bigger conceptual chunk; bumping deeper into the agent-facing surface.
3. Phase 4 (switch `_build_pgsc_calc_argv` from `-profile conda` to `-profile docker`; drop the `pgs_catalog_ancestry` post-fetch extraction hook; doctor section already in 1b; CLI surface for end-to-end compute).
4. Phase 5 (real-data smoke against `MPNRGLQ2K.cram` — resolves Open Question Q1 wall-clock).

---

### 2026-05-18 — Phase 1b Implementation (RED → GREEN → REFACTOR)

**Context Review Completed**:
- Re-read Phase 1a outputs + the pending-1b list in the previous work-notes entry.
- Studied existing patterns: [pgsc_calc wrapper CLI subcommand](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py), [ancestry_ready / prs_runtime_ready doctor probes](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py), [test_invP001_cli_no_egress.py](../../../../packages/toolkit/tests/privacy/test_invP001_cli_no_egress.py) urllib-stub pattern.
- Confirmed `tiny_cram` + `tiny_grch38_fasta` fixtures from [tests/conftest.py](../../../../packages/toolkit/tests/conftest.py) have aligned reads at chr17:43044295+ over a synthetic FASTA where the reference at that region is 'A' — perfect for a real-bcftools force-genotype smoke against `REF=A ALT=T` → 0/0.

**Applicable Invariants** (recurring from Phase 1a):
- INV-D001 / INV-D003 / INV-R001 / INV-P001 stay relevant.
- INV-A003 implicitly: the CLI subcommand surface preserves the agent's path to wire rationale + alternatives at Phase 2.

**RED step output**:

```text
test_prs_coverage_fill_materialize.py:  4 ImportError on `_materialize_pca_sites`
test_doctor.py (3 prs_coverage tests):  3 KeyError on `prs_coverage_ready`
test_cli_pipeline_prs_prepare_coverage:  3 UsageError "No such command 'prs-prepare-coverage'"

10 failed in 0.04s — all for the expected reason (absent symbols / unregistered command).
```

**Completed Today (Phase 1b — 10 new tests, all GREEN)**:
- [x] `_materialize_pca_sites` — plink2 LD-prune via DooD against `ghcr.io/pgscatalog/plink2:2.00a5.10`; emits plaintext `pca_sites.tsv` + `pca_alleles.tsv` + `pca_sites.provenance.json` under `reference/prs_pca_sites/<panel_version>/`. 4 tests covering argv shape, output layout, provenance JSON, chr-prefix rewrite.
- [x] `_collect_prs_coverage_ready` — doctor probe; 3 tests covering `no_samples` / `ready` / `partial` states. Wired into `doctor()` report alongside `ancestry_ready` + `prs_runtime_ready`.
- [x] `genomeclaw pipeline prs-prepare-coverage` — Typer subcommand; 3 tests covering happy path, cache-hit semantics, `--json` envelope conformance per `INV-C002`.
- [x] Privacy `test_invP001_no_egress_during_pipeline_prs_prepare_coverage` — confirms the CLI dispatch + wrapper logic never call `urllib.request.urlopen` (bcftools subprocess stubbed).
- [x] Real-bcftools `test_force_genotype_tier1_against_tiny_cram_emits_refref` (`needs_bio`-gated) — invokes the actual bcftools pipe against the synthetic `tiny_cram` + `tiny_grch38_fasta`, asserts `0/0` at chr17:43044300 where reference + reads are both 'A'.

**Decisions Made**:
- **Plaintext `.tsv`, not bgzip + tabix**, for the materialise outputs. bcftools `--regions-file` / `--targets-file` accept plaintext, and the full-autosome ~436k-line set still fits well under 10 MB. Avoids stubbing bgzip + tabix in the test fakes; keeps the materialise function subprocess-free past plink2. (Production correctness preserved — plain TSVs are a documented bcftools input format.)
- **Cache status string is `"built" | "hit"`** (not a richer enum). The CLI computes it by snapshotting cache presence before invoking the wrapper. Phase 2 can extend if a third state (e.g. `"invalidated_sha_mismatch"`) becomes useful.
- **`needs_bio` gate stays as-is** for the real-bcftools test. Skipping on the bare host venv matches the existing `test_invR001_bcftools_wrapper.py` discipline. The toolkit Docker image's CI job sets `GENOMECLAW_HAS_BIO=1` and runs it for real.

**Blockers / Issues**:
- None. The `needs_bio` test is correctly skipped locally (no samtools/bcftools on host); it will activate inside the toolkit image's CI job.

**REFACTOR step**:
- ruff: 1 import-order fix in the privacy test, auto-applied (`uv run ruff check --fix`).
- mypy: clean across `coverage_fill.py` + `doctor.py` + `pipeline.py`.
- Full suite: 627 passed / 104 skipped / 0 failed (Phase 1a baseline was 616/103; +11 new tests / +1 skip for `needs_bio` real-bcftools test).

**Phase 1 status — COMPLETE**:
- 1a: 11 tests (primitives + orchestrator) — done in earlier session.
- 1b: 10 tests (materialize + doctor + CLI + privacy + real-bcftools) — done this session.
- Total: 21 tests, all GREEN (1 `needs_bio`-gated skip on host venv).

**Next Steps**:
1. Commit Phase 1 (1a + 1b).
2. Phase 2 (Tier 2 per-PGS cache + merge + pgsc_calc wiring) — bigger chunk; defer to a fresh session.

---

### 2026-05-18 — Phase 1a Implementation (RED → GREEN → REFACTOR)

**Context Review Completed**:
- Re-read [development-plan.md](development-plan.md) Phase 1 deliverables + [phases/phase-1.md](phases/phase-1.md) TDD scaffold.
- Studied existing toolkit patterns: [_bcftools.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py) subprocess wrapper conventions, [scratch.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py) (`shard_scratch` + `atomic_promote`), [test_pgsc_calc_wrapper.py](../../../../packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py) subprocess-stub idiom.
- Confirmed `needs_bio` + `needs_prs_runtime` markers auto-skip on a bare venv via [conftest.py](../../../../packages/toolkit/tests/conftest.py); the unit-style tests use neither marker (no real bcftools required for the stubbed path).

**Applicable Invariants**:
- **INV-D001**: tests assert CRAM SHA256 unchanged after a run.
- **INV-D003**: tests assert in-flight VCF stages under `shard_scratch` and `atomic_promote`-s to derived/.
- **INV-R001**: `tier1.qc.json` carries source_cram_sha256 + panel_version + bcftools_version + tool_command + GT distribution + mean DP + per-chrom counts + schema_version.

**RED step output** (`uv run pytest tests/integration/test_prs_coverage_fill_*.py --tb=line`):

```text
collected 11 items
tests/integration/test_prs_coverage_fill_unit.py        FFFFF                  [ 45%]
tests/integration/test_prs_coverage_fill_integration.py FFFFFF                 [100%]

ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep.coverage_fill'  × 10
ImportError: cannot import name 'coverage_fill' from 'genomeclaw_toolkit.prep'  × 1

============================== 11 failed in 0.04s ==============================
```

All 11 tests fail with `ModuleNotFoundError` — confirms the RED step is honest (failure cause is exactly the absent module, not an unrelated regression).

**GREEN step**: created [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) (327 lines). Key design points:

- The bcftools pipe is one `bash -c` invocation — streaming `mpileup → call → norm + index` in a single subprocess so the pipe stays in-memory and the per-stage stderr is captured together.
- `shard_scratch` step name is `prs_coverage_tier1`; `run_id` derives from `cram_path.stem` for the Phase 1 prove-out — Phase 2 will wire the actual run-id from the orchestrator.
- Cache-hit detection compares `qc["source_cram_sha256"]` against a fresh hash of the current CRAM. A SHA mismatch (e.g. re-aligned CRAM) invalidates the cache.
- `MissingCramIndexError` carries a `samtools index <path>` hint so a missing `.crai` surfaces as an actionable error rather than a 50 GB sequential CRAM scan.
- `bcftools_version()` parse failures (empty stdout in stubbed tests) are caught and recorded as `"unavailable"` — the cache build doesn't fail over a provenance detail.

**Two minor RED→GREEN iterations** (kept honest):

1. The scratch-promote spy initially asserted `dst == output_vcf` against `promote_calls[-1]`, but the wrapper also promotes the `.tbi` sidecar (second call). Changed the assertion to inspect `promote_calls[0]` (the VCF promote) and added a loop verifying every recorded promote originates under scratch (the INV-D003 leak guard).
2. `bcftools_version()` in tests with stubbed subprocess returns empty stdout → `ValueError`. Added `ValueError` to the catch-clause so cache writes succeed with `bcftools_version="unavailable"` rather than failing the orchestrator.

**REFACTOR step**: ruff + mypy clean. One unused-variable lint fixed in idempotency test. Full toolkit suite 616 passed / 103 skipped / 0 failed — no regressions.

**Completed Today**:
- [x] 5 unit tests (parse_prune_in × 2, summarize_qc × 2, cache_path × 1) — all GREEN, no subprocess
- [x] 6 integration tests (argv shape, scratch→promote, INV-D001 immutable CRAM, INV-R001 QC fields, idempotency, missing .crai error) — all GREEN, subprocess stubbed
- [x] [coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) — primitives + orchestrator + typed error + module-level `atomic_promote` re-export for test patching
- [x] Full suite green (616/616 non-skipped); ruff + mypy clean

**Decisions Made**:
- Single `bash -c` pipe (not three sequential `subprocess.run` calls) for the bcftools mpileup→call→norm chain. Keeps the stream in-memory + per-stage stderr unified; matches what the chr22 prove-out actually ran.
- `bash -c` rather than constructing the pipe manually via Python `subprocess.PIPE` — the pipe template is human-readable, the shell-stop-on-error semantics (`&&`) are explicit, and the test fakes parse the argv with a single regex.
- Re-export `atomic_promote` from the module so tests can patch via `genomeclaw_toolkit.prep.coverage_fill.atomic_promote` rather than the canonical scratch module. Mirrors the `pgs.py:subprocess.run` patch pattern.

**Blockers / Issues**:
- None for Phase 1a. The deferred Phase 1b work (real-bcftools integration test, plink2 materialize, CLI subcommand, doctor section, privacy egress test) is scoped intentionally; each adds a new test surface with its own gating marker.

**Phase 1 status**: split into 1a (this session, primitives + orchestrator, 11 tests, all GREEN) and 1b (still pending, ~6 tests):

- `_materialize_pca_sites` via DooD against `ghcr.io/pgscatalog/plink2:2.00a5.10` — gated on `needs_prs_runtime`
- `genomeclaw prs prepare-coverage --sample <id>` CLI subcommand + 2 CLI tests (happy path, cache-hit)
- `_collect_prs_coverage_ready` doctor probe + 1 doctor test
- Privacy zero-egress test (whole prepare-coverage flow, mocked socket factory)
- Real-bcftools integration test against `tiny_cram` (gated on `needs_bio`)

**Next Steps**:
1. Land Phase 1a (commit) — primitives + orchestrator are independently useful and stable.
2. Phase 1b: write the deferred 6 tests RED, implement, GREEN.
3. Phase 2: Tier 2 per-PGS force-genotyping + merge + cache-key invariance.

---

### 2026-05-18 — Prove-out + Plan Drafting

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — applicable invariants confirmed: INV-D001, INV-D002, INV-D003, INV-P001, INV-R001, INV-C001 v1.7, INV-A003.
- Re-read [docs/plans/CLAUDE.md](../../CLAUDE.md) — followed the spec → dev-plan → work-notes → phase-1 flow; respected the real-data smoke gate principle.
- Re-read [docs/reports/prs-real-data-smoke-research-brief.md](../../../reports/prs-real-data-smoke-research-brief.md) — the brief that documented the failure and the four candidate fixes (A–D).
- Received the agent recommendation document (2026-05-18) — synthesizes two independent reviews into a two-tier bcftools-based cache recommendation; rejected the GATK GVCF approach (option B) in favour of bcftools forced-genotyping (option A+C hybrid).

**Applicable Invariants**:
- **INV-D001**: CRAM is read-only; force-genotype output writes to `derived/prs_coverage/`.
- **INV-P001**: zero new network egress; bcftools/plink2/pgsc_calc all on-device.
- **INV-R001**: cache key = (sample, pgs_id, scorefile_sha256, panel_version); tool versions on every row.
- **INV-C001 v1.7**: five-named-reasons decline taxonomy is structural, not advisory; wired as typed exceptions.
- **INV-A003**: agent rationale + two alternatives recorded on every agent-triggered `pgs_scores` row.

**Key Insights**:
- The bcftools pipe `mpileup -R sites | call -C alleles -T alleles | norm` is single-threaded compute; `--threads` only adds I/O compression threads, not parallel pileup. Wall-clock speed-up path is **parallelism across chromosomes**, bounded by Colima CPU count (currently 2).
- The chr22 PCA-eligible site count (6,812) was lower than the agent recommendation document's 1.14M target. Difference is the LD-prune r² threshold: we use `--indep-pairwise 1000 50 0.05` (r²<0.05, matching pgsc_calc's internal `FILTER_VARIANTS`); the document's 1.14M presumably comes from a less aggressive prune (r²<0.1 or r²<0.2). Decision: stick with r²<0.05 — it matches what pgsc_calc does internally, so the PCA projection alignment is mechanical.
- The panel uses chromosome naming `1, 2, …, 22, X, Y` (no `chr` prefix); the user CRAM and FASTA use `chr1, chr2, …, chr22, chrX, chrY, chrM`. The bcftools targets file must carry the `chr` prefix to match CRAM/FASTA — handled at TSV emission time with a single `awk` rewrite.

**Prove-out measurements (chr22, MPNRGLQ2K.cram, 2026-05-18, Apple Silicon M-series, 2-CPU 12 GB Colima)**:

| Step | Wall-clock | Peak RAM | Output |
|---|---|---|---|
| plink2 `--chr 22 --maf 0.01 --hwe 1e-6 --geno 0.05 --indep-pairwise 1000 50 0.05` via DooD (`ghcr.io/pgscatalog/plink2:2.00a5.10`, linux/amd64 emulated) | **114s** | n/a (plink2 internal `--memory 8000`) | 6,812 prune-in IDs |
| bcftools `mpileup -R sites.tsv.gz | call -C alleles -T alleles.tsv.gz | norm` against full CRAM, single-threaded | **99s** (cold cache) / **97s** (`--threads 2`) | **127 MiB** | 6,796 records in tier1.vcf.gz (198 KB) |

GT distribution (6,796 records / 6,812 sites → 16 collapsed during indel-normalization):

| GT | Count | % |
|---|---|---|
| `0/0` (REF/REF) | 5,744 | 84.52% |
| `0/1` (het) | 644 | 9.48% |
| `1/1` (hom-alt) | 347 | 5.11% |
| `./.` (low coverage) | 61 | 0.90% |
| Other | 0 | 0.00% |

Mean DP: **27.98×** (healthy 30× WGS). Indel-normalization realigned 204 records (3.0%) — expected for the LD-pruned set.

**Extrapolation to whole-autosome Tier 1 (Open Question Q1)**:
- chr22 panel-variant fraction of autosomes: 1,253,126 / ~80M (autosome subset of 84.3M total) ≈ **1.56%**
- Extrapolated autosome PCA-eligible site count: ~6,812 / 0.0156 ≈ **436,000**
- Single-threaded wall-clock: 99s × (436,000 / 6,812) = **6,330s ≈ 105 min**
- 2-CPU parallel (current Colima): **~53 min**
- 4-CPU: **~26 min**
- 8-CPU: **~13 min**

The agent recommendation document's "10–15 min for Tier 1" estimate is achievable with 8 CPUs. Current 2-CPU Colima delivers ~50–60 min; the user's M-series host has 8+ cores so bumping Colima is feasible. **Decision deferred to Phase 5**: measure full autosomes first, then choose CPU allocation based on the actual SLA cost.

**Completed Today**:
- [x] Verified chr22 force-genotyping primitive end-to-end on real data
- [x] Measured wall-clock, peak RAM, GT distribution, mean DP
- [x] Extrapolated to full-autosome SLA range
- [x] Drafted spec.md
- [x] Drafted development-plan.md
- [x] Drafted work-notes.md (this file)
- [x] Drafted phases/phase-1.md

**Decisions Made**:
- Reject GATK GVCF reconstruction (option B). bcftools `-C alleles` is the textbook primitive and is RAM-cheap; GATK's local reassembly is wasted work for known-allele forced genotyping.
- Adopt the two-tier cache architecture from the agent recommendation document. Tier 1 keyed by panel version; Tier 2 keyed by scoring-file SHA256.
- Switch `_build_pgsc_calc_argv` default from `-profile conda` to `-profile docker` (proven via smoke; conda fails on linux/arm64).
- Plan to drop the `pgs_catalog_ancestry` post-fetch extraction hook (pgsc_calc reads `.tar.zst` directly). Defer to Phase 4 so the cleanup doesn't entangle with Phase 1 TDD.
- Adopt the per-variant-count QC threshold table from the agent recommendation document Section 5.1 verbatim. Adopt the five-named-reasons decline taxonomy from Section 5.2 verbatim.
- Restrict initial Tier 2 site lists to SNPs (Open Question Q2). Revisit if/when an indel-heavy PGS lands.
- Stick with LD-prune r²<0.05 (matches pgsc_calc internal `FILTER_VARIANTS`).
- Use DooD for plink2 (one-time per panel release); do NOT bake plink2 into the toolkit image.

**Blockers / Issues**:
- None. Real CRAM, real panel, real toolkit image all available on the external drive (1.4 TB free of 1.8 TB).
- The `prs-real-data-smoke-recommendation.md` referenced in the spec doesn't exist yet as a separate doc — the recommendation lives only in the conversation that produced this plan. Follow-up: distill the recommendation document into `docs/reports/prs-real-data-smoke-recommendation.md` so the plan's external citation resolves.

**Next Steps**:
1. Land this plan (spec + dev-plan + work-notes + phase-1) on `main` or on a feature branch.
2. Begin Phase 1: write RED tests for `_materialize_pca_sites` and `_force_genotype_tier1`.
3. Optional: write the recommendation memo (`docs/reports/prs-real-data-smoke-recommendation.md`) so the plan's reference resolves.

---

## Phase Progress

### Phase 1: Tier 1 Materialize + Force-Genotype
**Status**: In Progress — 1a Complete, 1b Pending
**Started**: 2026-05-18
**Completed**: (1a) 2026-05-18

#### Test Results — Phase 1a
```text
tests/integration/test_prs_coverage_fill_unit.py .....                   [ 45%]
tests/integration/test_prs_coverage_fill_integration.py ......           [100%]
============================== 11 passed in 0.07s ==============================

Full toolkit suite: 616 passed, 103 skipped, 0 failed
ruff: All checks passed
mypy: Success: no issues found in 1 source file
```

#### Results — Phase 1a
- Created [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py)
- Created [packages/toolkit/tests/integration/test_prs_coverage_fill_unit.py](../../../../packages/toolkit/tests/integration/test_prs_coverage_fill_unit.py) (5 unit tests)
- Created [packages/toolkit/tests/integration/test_prs_coverage_fill_integration.py](../../../../packages/toolkit/tests/integration/test_prs_coverage_fill_integration.py) (6 integration tests with subprocess stubs)

#### Notes — Phase 1a
- All 11 tests went RED→GREEN cleanly. Two minor iterations during GREEN (spy on `.tbi` promote; `ValueError` on stubbed `bcftools --version` parsing) — both kept honest in the implementation rather than papered over.
- Module-level `atomic_promote` re-export so tests can patch via `coverage_fill.atomic_promote` (mirrors `pgs.py:subprocess.run` patching).
- INV-D001 (CRAM read-only), INV-D003 (scratch → promote), INV-R001 (qc.json schema) verified by tests.

#### Phase 1b Deferred Work
- `_materialize_pca_sites` (plink2 LD-prune via DooD) — gated `needs_prs_runtime`
- CLI subcommand `genomeclaw prs prepare-coverage` + 2 tests
- Doctor `_collect_prs_coverage_ready` + 1 test
- Privacy zero-egress test
- Real-bcftools integration test against `tiny_cram` — gated `needs_bio`

---

### Phase 2: Tier 2 + Cache + Merge

**Status**: Pending

### Phase 3: QC + Decline Taxonomy + INV-C001/INV-A003

**Status**: Pending

### Phase 4: -profile docker, doctor, CLI polish

**Status**: Pending

### Phase 5: Real-data smoke gate

**Status**: Pending

---

## Key Decisions

### Decision 1: bcftools `-C alleles`, not GATK HaplotypeCaller `-ERC GVCF`
**Date**: 2026-05-18
**Context**: Need to recover REF/REF dosages from the Nebula variant-only VCF for pgsc_calc PCA projection.
**Decision**: Use `bcftools mpileup -R sites | bcftools call -C alleles -T alleles | bcftools norm` as the forced-genotyping primitive.
**Rationale**: Textbook tool for forced genotyping at known alleles. RAM-cheap (127 MiB measured on chr22 vs. multi-GB JVM heap for GATK). No new dependency — bcftools already in `genomeclaw/toolkit:prs-phase1`. Skips local reassembly, which is wasted work when alleles are known.
**Alternatives Considered**: GATK HaplotypeCaller GVCF + ReblockGVCF + bcftools convert (option B from research brief); naive `missing2ref` backfill (rejected — false REF/REF at low-coverage sites corrupts PCA); the Fasold "force-ALT-allele" rewrite (rejected — author advises against, fails on indels and strand-ambiguous sites); local imputation (rejected — >20 GB RAM ceiling violation).
**Affected Invariants**: INV-R001 (rebuildability — bcftools is pinned in `_versions.PRS_RUNTIME_VERSIONS`), INV-P001 (privacy — all on-device).

### Decision 2: Two-tier cache, not one-tier
**Date**: 2026-05-18
**Context**: PCA-eligible site set is fixed by panel; PGS scoring sites vary per agent question.
**Decision**: Tier 1 = PCA-eligible sites, one-time per (sample, panel_version). Tier 2 = per-PGS scoring sites, cached by (sample, pgs_id, scorefile_sha256).
**Rationale**: Amortizes the expensive CRAM-decoding cost across questions. First-time question against a new PGS: Tier 2 build (~5–10 min for 100k-variant PGS) + pgsc_calc (~10–15 min). Subsequent question against same PGS: pgsc_calc only (~10–15 min).
**Alternatives Considered**: Single PCA-only cache (would still need ad-hoc per-PGS genotyping); single per-PGS cache (re-pays PCA layer on every PGS).
**Affected Invariants**: INV-R001 (cache key includes everything that determines output).

### Decision 3: `-profile docker`, not `-profile conda`
**Date**: 2026-05-17 (during smoke), formalized 2026-05-18
**Context**: pgsc_calc v2.2.0 requires `-profile <something>`; `-profile conda` failed on linux/arm64.
**Decision**: Switch `_build_pgsc_calc_argv` default to `-profile docker`. Use DooD (mount `/var/run/docker.sock`, identical-path bind-mounts) so the nested Nextflow can spawn sibling containers.
**Rationale**: Empirically the only profile that works on Apple Silicon. plink2 2.0a5.10 (pgsc_calc's pinned version) is not packaged on linux/arm64 conda-forge.
**Alternatives Considered**: `-profile mamba` (same plink2 packaging issue); `-profile singularity` (not installed on host).
**Affected Invariants**: INV-D002 (sibling containers spawned by DooD run host-side, not in sandbox), INV-R001 (pinned via `_versions.PRS_RUNTIME_VERSIONS`).

### Decision 4: LD-prune r² < 0.05, not r² < 0.1 or r² < 0.2
**Date**: 2026-05-18
**Context**: Agent recommendation document quotes ~1.14M PCA-eligible sites; chr22 prove-out yielded 6,812 → extrapolated ~436k autosome sites. The gap is the LD-prune threshold.
**Decision**: Use `--indep-pairwise 1000 50 0.05` (matches pgsc_calc internal `FILTER_VARIANTS`).
**Rationale**: We want the PCA projection to align mechanically with what pgsc_calc does internally. Less aggressive prune (r²<0.1 or r²<0.2) gives a denser set but doubles the Tier 1 wall-clock. Stick with 0.05; revisit only if FRAPOSA Mahalanobis distance is structurally too noisy on the user's PC vector.
**Affected Invariants**: INV-R001 (the prune parameters are pinned).

---

## Files Modified

### Created
- `docs/plans/active/prs-input-coverage-fill/spec.md` — feature specification
- `docs/plans/active/prs-input-coverage-fill/development-plan.md` — chosen solution + phase overview
- `docs/plans/active/prs-input-coverage-fill/work-notes.md` — this file
- `docs/plans/active/prs-input-coverage-fill/phases/phase-1.md` — Tier 1 TDD scaffold

### Modified
- (none yet)

### Deleted
- (none)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None planned. If implementation surfaces a structural rule worth promoting, propose it via the standard channel.

### Other Documentation
- [ ] `docs/reports/prs-real-data-smoke-recommendation.md` — distill the agent recommendation document so the spec's reference resolves (deferred; not blocking).
- [ ] `docs/reference/prs-pipeline.md` — architecture, cache semantics, decline taxonomy (created in Phase 5).
- [ ] `docs/reference/grand-plan.md` — update Theme G PRS surface (after Phase 5).
- [ ] `docs/plans/active/prs-bootstrap-meta.md` — link this plan as Stage 5 follow-up.

---

## Open Risks & Follow-ups

- **Q1 (Tier 1 full-autosome wall-clock)**: chr22 measurement extrapolates to 53–105 min depending on Colima CPU allocation. Resolution in Phase 5 GREEN.
- **Q2 (indel reliability under `-C alleles`)**: spot-check at Phase 5; restrict initial Tier 2 to SNPs.
- **Q3 (per-chromosome GT distribution)**: emit per-chrom QC in tier1.qc.json from Phase 1.
- **Q4 (LD-prune aggressiveness)**: stuck at r²<0.05 for MVP; revisit if FRAPOSA noisy.
- **Q5 (plink2 packaging)**: DooD for MVP; bake into image only if Tier 2 ever calls plink2 (it doesn't).
- **pgsc_calc v3 trajectory**: if v3 ships native CRAM/VCF before Phase 5, consider whether to short-circuit this plan.
- **PGS Catalog scoring-file mirror**: quarterly refresh cadence; cache key includes SHA256 so silent re-harmonization doesn't return stale Tier 2.

---

## Prove-out Artefacts (2026-05-18)

Scratch workspace: `/Volumes/Genome_Work/genomeclaw/_scratch/prs-coverage-prove/`

```text
prs-coverage-prove/
├── logs/
│   ├── plink2_chr22.log         # plink2 RED→prune-in (114s)
│   ├── timing.txt               # bcftools pipe wall-clock (99s)
│   ├── timing_t2.txt            # --threads 2 wall-clock (97s, no improvement)
│   ├── docker_stats.log         # peak memory sampling (127 MiB peak)
│   ├── mpileup.err / call.err / norm.err
├── pca_sites/
│   ├── chr22_pca.prune.in       # 6,812 IDs
│   ├── chr22_pca.prune.out      # 132,483 IDs filtered out by LD
│   ├── chr22_alleles.tsv.gz{,.tbi}   # bcftools call -C alleles input
│   └── chr22_sites.tsv.gz{,.tbi}     # bcftools mpileup -R input
└── tier1_chr22/
    ├── chr22_tier1.vcf.gz       # 198 KB, 6,796 records, 84.5% REF/REF
    └── chr22_tier1.vcf.gz.tbi
```

Keep this workspace until Phase 5 completes — it's the empirical anchor for the SLA conversations.

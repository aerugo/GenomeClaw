# PRS Reference-Data Bootstrap — Development Plan

**Status**: In Progress (Phase 1 + 2 complete; real-data smoke deferred to meta-plan Stage 3)
**Created**: 2026-05-17
**Branch**: `feature/prs-reference-bootstrap`
**Spec**: [spec.md](spec.md)

---

## Summary

Add `pgs_catalog_ancestry` as a first-class `refs fetch` source, wire it into the default release set, extend `host doctor` with a readiness gate, and repoint the existing Slice E.3 ancestry-reference check at the materialised path. Closes the phantom-CLI gap left open by Slice E v2.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — reference bundle is written once into `reference/`, never mutated; skip-detection enforced by existing `VersionAlreadyExists` path.
- **INV-D002** Sandbox Is Bioinformatics-Free — all fetch + extract work runs in the toolkit container, not the agent sandbox.
- **INV-P001** Privacy Default — single deliberate-invocation egress to `ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/`. No background fetch, no telemetry.
- **INV-R001** Rebuildability — fetcher records source URL, content size + (where available) upstream checksum, fetcher version, fetched-at timestamp via the existing `_LAYOUTS` contract.
- **INV-C001 v1.7** PRS Findings Must Be Ancestry-Calibrated — this plan is the precondition that makes the orchestrator's pre-flight gate actually reachable.

## Proposed New Invariants

**None.**

## Current State Analysis

The Slice E v2 ancestry check ([pgs.py:59-75](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L59-L75)) points users at a phantom command. The `_LAYOUTS` registry ([prep/fetch.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py)) has eight sources today (grch38, clinvar, dbsnp, gnomad-exomes, vep_cache, alphamissense, loftee, gnomad-constraint); `pgs_catalog_ancestry` is missing. The `host doctor` readiness checks ([prep/doctor.py:104-120](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py#L104-L120)) cover raw / reference / derived / scratch directory presence + colima status + per-source reference classification, but have no notion of ancestry readiness specifically.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | 8-entry `_LAYOUTS` registry | Add `pgs_catalog_ancestry` entry with PGS Catalog FTP URL, `.tar.zst` extraction post-hook, `ancestry/{1000g,hgdp}/` canonical layout |
| `packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml` | 9 sources | Add `{ source = "pgs_catalog_ancestry", release = "v1" }` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | 4 readiness checks | Add `ancestry_ready` check (file-presence + count gate on `1000g/` and `hgdp/`) |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | `_check_ancestry_reference` points at phantom layout | Repoint at canonical materialised path; ensure install hint matches the real `refs fetch` invocation |
| `packages/toolkit/Dockerfile` | No `zstd` binary | Add `zstd` to Stage 1 micromamba env (single conda-forge package) |
| `packages/toolkit/tests/integration/test_fetch_mocked.py` | Covers existing 8 sources | Extend with `pgs_catalog_ancestry` happy-path + skip-detection cases |
| `packages/toolkit/tests/integration/test_doctor.py` | Covers existing readiness checks | Add `ancestry_ready` case |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/integration/test_refs_fetch_pgs_ancestry.py` | End-to-end mocked-HTTP fetch + extract + skip-detection coverage for the new source |

## Solution Design

The fetcher already abstracts source-specific quirks behind `_LAYOUTS`. Adding `pgs_catalog_ancestry` is a one-entry extension that the existing `fetch()` driver handles uniformly: download → checksum → extract → record canonical filenames for skip-detection.

```text
genomeclaw refs fetch --source pgs_catalog_ancestry --release v1
  │
  ├─ _LAYOUTS["pgs_catalog_ancestry"]  → URL, filename, expected size,
  │                                       extraction post-hook
  ├─ download to reference/pgs_catalog_ancestry/v1/_staging/<bundle>.tar.zst
  ├─ zstd-decompress + tar-extract into reference/pgs_catalog_ancestry/v1/
  │     producing  reference/pgs_catalog_ancestry/v1/1000g/{*.pgen,*.pvar,*.psam}
  │           and  reference/pgs_catalog_ancestry/v1/hgdp/{*.pgen,*.pvar,*.psam}
  ├─ remove _staging/
  └─ host doctor's ancestry_ready check now passes
```

### Key Design Decisions

1. **Use `zstd` host binary, not `zstandard` Python lib.** Matches the existing bgzip / htslib / samtools pattern (shell out to a pinned binary). Adds one micromamba package to Stage 1 of the Dockerfile. No new Python dep.
2. **Land under `reference/pgs_catalog_ancestry/<release>/` not `reference/ancestry/`.** Consistent with how every other source nests under `reference/<source>/<release>/`. The current `_check_ancestry_reference` path (`reference/ancestry/{1000g,hgdp}/`) is a Slice E v2 placeholder — repoint it at the canonical layout in Phase 1.
3. **Do not pre-cache PGS scoring weights.** Scoring weights are fetched per-PGS-ID by `pgsc_calc` at compute time. Pre-caching all of them is wasteful (~tens of GB unused). The install-time consent for that egress lives in `INV-P001`, governed separately.
4. **Defer hash-recompute / manifest verification to [refs-integrity-hardening](../refs-integrity-hardening/).** That plan adds manifest-based integrity to all sources uniformly — adding it here in advance would fork the implementation.

### Schema / Provenance Impact

- New / changed schemas: none.
- Schema version bumps: none.
- Provenance columns added: none (no derived store touched).
- Rebuild procedure: `rm -rf reference/pgs_catalog_ancestry/v1 && genomeclaw refs fetch --source pgs_catalog_ancestry --release v1`.

### Privacy & Egress Impact

- New network egress points: one — `ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/`. Mirrors the existing pattern (gnomAD GCS, Ensembl FTP, Broad mirror).
- New secret-handling surfaces: none.
- Redaction added: n/a.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | `_LAYOUTS` entry + `zstd` extract post-hook + release-set entry + `_check_ancestry_reference` repoint | Mocked-HTTP fetch happy path, `.tar.zst` extraction, skip-detection, repointed install hint | 6 |
| 2 | `host doctor` ancestry-ready check + integration with `host setup --fetch-all` flow | Doctor readiness gate, setup `--fetch-all` includes new source | 3 |

## Phase 1: Fetcher + Release-Set Integration ✅ Complete

**Goal**: Make `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` work end-to-end and have `_check_ancestry_reference` find the result.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables (as landed)
1. ✅ `_LAYOUTS["pgs_catalog_ancestry"]` entry in `fetch.py` + matching `_DEFAULT_BASE_URLS` entry (`ftp.ebi.ac.uk`).
2. ✅ `.tar.zst` extraction post-hook (`_extract_pgs_catalog_ancestry_bundle`) — streams via `zstandard.ZstdDecompressor.stream_reader` + `tarfile.open(mode="r|")`; defensively flattens an outer `pgsc_*/` directory if upstream wraps the bundle; deletes the bundle after extraction.
3. **Revised**: `zstandard>=0.22` added to toolkit Python deps (not `zstd` binary in Dockerfile). Reasons in [work-notes.md](work-notes.md) — keeps Stage 1 of the runtime plan clean + lets the hook stream without holding multi-GB in memory + tests work on bare host venv.
4. ✅ `release_sets/default.toml` entry pinned to `v1`.
5. ✅ `_check_ancestry_reference` + `_build_pgsc_calc_argv` in `pgs.py` repointed at the canonical layout via `_ancestry_reference_dir(reference_root, release)` helper.
6. ✅ `tests/integration/test_refs_fetch_pgs_ancestry.py` with 6 tests: happy_path, skip_detection_invD001, layout_declares_presence_marker, in_default_release_set, check_ancestry_reference_resolves_canonical_layout, install_hint_points_at_real_subcommand.

### Deferred
- **Real-data smoke** against project owner's host (`genomeclaw refs fetch --source pgs_catalog_ancestry --release v1`) — runs as part of meta-plan Stage 3 once Plan 2 lands, since the cross-plan integration smoke needs both.

### Invariants Enforced Here
- **INV-D001**: Test that a second `refs fetch` invocation raises `VersionAlreadyExists` without re-downloading.
- **INV-R001**: Test that the materialised tree contains the canonical filenames recorded in `_LAYOUTS` (file-list assertion, not a content hash — content hashing is [refs-integrity-hardening](../refs-integrity-hardening/)'s scope).

### Success Criteria
- [ ] All 6 tests for this phase pass (RED → GREEN → REFACTOR visible in history)
- [ ] `ruff check` + `ruff format` clean
- [ ] `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` succeeds against the project owner's host (real-data smoke; documented in work-notes, not committed as a test)
- [ ] `_check_ancestry_reference` against the materialised layout returns cleanly

## Phase 2: Doctor Gate + Setup Wiring ✅ Complete

**Goal**: Make `genomeclaw host doctor` and `genomeclaw host setup --fetch-all` first-class entry points for PRS readiness.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables (as landed)
1. ✅ `ancestry_ready` informational section in `prep/doctor.py` (probes canonical presence files in both `1000g/` + `hgdp/` subtrees, NOT bare directory existence). Three statuses: `ready` / `partial` / `missing`.
2. ✅ `host setup --fetch-all` automatically iterates `pgs_catalog_ancestry` via the Phase 1 release-set entry — already covered end-to-end by [tests/integration/test_cli_fetch_all.py](../../../packages/toolkit/tests/integration/test_cli_fetch_all.py) after the Phase 1 source-set updates landed.
3. **Deferred**: `genomeclaw refs list` reporting via `_collect_references` — would inherit the latent vep_cache "partial after extraction" classification bug (`_collect_references` walks `layout.files` which includes the post-fetch-deleted `.tar.zst`). `ancestry_ready` is the canonical PRS-readiness signal regardless; the cross-source `presence_relpath`-aware classification fix is a separate scope. See work-notes Session 2026-05-17 (Phase 2).
4. ✅ `_PGS_ANCESTRY_PRESENCE_FILES` constant in [prep/pgs.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) — single source of truth shared by the fetch `presence_relpath` marker + the doctor probe.

### Invariants Enforced Here
- ✅ **INV-C001 v1.7**: `test_doctor_reports_ancestry_partial_invC001_when_only_one_subtree_present` asserts that one-subtree-present is classified as `partial` (the agent + the Slice E.3 compute-time guard both refuse to ship PRS output until both subtrees land).

### Success Criteria
- [x] All 3 tests for this phase pass (RED → GREEN → REFACTOR visible)
- [x] `host doctor` JSON output includes `ancestry_ready` field (`status: ready|partial|missing`)
- [x] `host doctor` exit code stays 0 for missing/partial ancestry data per existing informational-section convention

---

## Testing Strategy

### Integration Tests
- `tests/integration/test_refs_fetch_pgs_ancestry.py`: mocked-HTTP fetch, `.tar.zst` extraction against a synthetic tiny bundle, canonical-filename inventory, skip-detection, repair-on-corruption (existing fetch behaviour).
- `tests/integration/test_doctor.py` extension: `ancestry_ready` returning true / false / partial against staged fixtures.

### Provenance Tests
- None new — no derived rows touched.

### Determinism Tests
- None new — `refs fetch` determinism is covered by the existing fetch test suite uniformly.

### Privacy-Default Tests
- The existing `tests/privacy/test_invP001_*` suite asserts no unsolicited egress in default config. Adding a new opt-in source does not alter the default-off posture; no new test required, but verify the existing privacy sweep still passes.

### Invariant Tests
- `tests/invariants/test_invD001_refs_skip_detection.py` (if it exists; create if not): assert that a second `refs fetch --source pgs_catalog_ancestry` invocation does not re-download.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — no change; existing INVs already cover this surface.
- [ ] [docs/reference/architecture.md](../../reference/architecture.md) — extend the reference-data layout section with `pgs_catalog_ancestry`.
- [ ] [README.md](../../../README.md) — update the storage planning table's `reference/` size estimate to include the ~50-60 GB ancestry data.
- [ ] [docs/plans/active/mvp/phases/phase-6-slice-e-v2.md](../mvp/phases/phase-6-slice-e-v2.md) — strike "real-data smoke deferred to manual" line; replace with reference to this plan.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete (TDD; real-data smoke deferred to meta-plan Stage 3) | 2026-05-17 | 2026-05-17 | +6 tests; 599 pass / 99 skip; `zstandard` Python lib in deps; canonical layout `reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/` |
| Phase 2 | Complete (TDD; real-data smoke deferred to meta-plan Stage 3) | 2026-05-17 | 2026-05-17 | +3 tests; 602 pass / 99 skip; `ancestry_ready` informational section in doctor; `_PGS_ANCESTRY_PRESENCE_FILES` single-source-of-truth constant |

---

## Open Risks & Follow-ups

- The PGS Catalog reference bundle may be re-cut without notice (upstream is not under our control); when that happens, bump `release` in `default.toml`. Document the bump procedure in `work-notes.md`.
- If [refs-integrity-hardening](../refs-integrity-hardening/) lands first, this plan's `_LAYOUTS` entry should include the manifest-write step from day one. Coordinate sequencing in `work-notes.md`.
- Disk-space gate: ~50-60 GB extracted. `host setup` already calculates required free space; verify the calculation accounts for the new source.

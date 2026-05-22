# Development Plan — From-scratch-setup protections

**Status**: Active
**Created**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Branch**: `main` (small enough to land directly; no separate feature branch needed)

## Summary

Two bug classes surfaced inside one Phase 7 canonical real-data run. Both share a "contract drift outside the toolkit code, no test catches it" pattern. This plan adds the missing tests + sharpens the symptom-to-diagnosis path + lands the one-line fixes the tests then enforce.

## Critical Invariants to Respect

- **INV-D006** (DooD-Safe Path Annotation) — this plan **extends** the invariant's enforcement surface from "wrapper-side annotation" to "shim-side propagation". No invariant text change needed; the existing rule already implies the shim must enable DooD mode for any subcommand whose wrapper requires `as_sibling_mountable`. The plan adds the test that mechanically verifies it.
- **INV-T001** (External-Tool Conventions Captured as Typed Wrappers) — extends the discovery-sweep pattern from argv pinning to plugin-load pinning for VEP plugins.
- **INV-R001** (Rebuildability) — silent NULL columns violate rebuildability without a test failure. AC4 closes that gap for VEP plugins.

## Proposed New Invariants

None. Both bug classes are subsumed by INV-D006 + INV-T001 extensions.

## Current State Analysis

### What exists today

- **INV-D006 wrapper-side enforcement**: [tests/invariants/test_invD006_dood_safe_path_annotation.py](../../../packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py) — walks every wrapper that imports `as_sibling_mountable` + asserts each Path-typed parameter is annotated `SiblingMountablePath`. Catches "wrapper forgets to mark a param". Does NOT catch "shim forgets to enable DooD mode for the subcommand".
- **VEP plugin syntax check**: [tests/integration/test_vep_loftee_plugin.py](../../../packages/toolkit/tests/integration/test_vep_loftee_plugin.py) — runs `perl -c LoF.pm` + `perl -c gerp_dist.pl` inside the toolkit image. Catches syntax errors + the `Bio::DB::BigFile` regression (per the 2026-05-15 fix). Does NOT catch runtime `do '...'`-loaded modules like `DBD::SQLite`.
- **`bin/genomeclaw` shim**: `_dood_scan_args` function lists `prs-compute` + `prs-prepare-coverage` as DooD-needing subcommands; auto-enables `GENOMECLAW_DOOD=1` only for those two. `pgs-compute` is missing despite calling the same `compute_pgs(...)` wrapper.

### What's missing

- A meta-invariant test that asserts shim's `_dood_scan_args` is exhaustive over `as_sibling_mountable` callers.
- A plugin-instantiation test for VEP plugins (vs. the current syntax-only check).
- A sharper `DooDPathError` message for the empty-allowlist case.
- `perl-dbd-sqlite` in the Dockerfile's `vep` stage.

## Solution Design

Five protections at four layers:

1. **Shim layer**: add `pgs-compute` to `_dood_scan_args` regex list. One-line fix.
2. **Wrapper layer**: extend `DooDPathError` in [prep/_paths.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py) to distinguish "empty allowlist" from "un-allowlisted prefix". Surface a fix-hint that names the shim's scan function.
3. **Image layer**: add `perl-dbd-sqlite` to the Dockerfile's `vep` stage's conda install. One-line fix.
4. **Test layer**: two new tests — `test_invD006_shim_dood_scan_exhaustive.py` (meta-invariant) + extended `test_vep_loftee_plugin.py` (plugin-instantiation check via `vep --plugin LoF --help`).
5. **Doc layer**: update INVARIANTS.md v1.14 → v1.15 with the scope clarification on INV-D006 + INV-T001; cross-reference both new tests; update phase-7.md's close-session-2 carry-forward list to acknowledge these protections exist.

### Schema / Provenance Impact

None. The plan touches tests + shim + Dockerfile + a doc reference; no schema columns, no provenance fields.

### Privacy & Egress Impact

None. No new egress, no new credentials. The `vep --plugin LoF --help` test invocation runs entirely inside the toolkit image's local env.

## Phase Overview

| Phase | Description | Tests | TDD focus |
|-------|-------------|-------|-----------|
| 1 | All five protections — RED → GREEN → REFACTOR in one phase | 2 new tests (meta-invariant + plugin-load) + 4-5 existing tests still green | All in one phase since the protections are tightly coupled + small |

The work is small enough to land in one phase. The meta-invariant test fails on current main (catches `pgs-compute`); the shim fix makes it pass. The plugin-instantiation test fails on current `slice-d-prime` (catches `DBD::SQLite`); the Dockerfile fix + image rebuild makes it pass.

### Phase 1 sequencing

**RED**:
1. Write `test_invD006_shim_dood_scan_exhaustive.py` (mechanical walk + assertion).
2. Extend `test_vep_loftee_plugin.py` with `test_loftee_lof_plugin_instantiates_inside_image` (gated on `GENOMECLAW_SANDBOX_IMAGE` env var; equivalent gate would be `GENOMECLAW_HAS_BIO` for in-image runs).
3. Confirm both new tests fail for the intended reasons.

**GREEN**:
1. One-line shim fix: add `pgs-compute` to `_dood_scan_args`.
2. Extend `DooDPathError` branch in `_paths.py` to distinguish empty-allowlist + name the fix.
3. Add `perl-dbd-sqlite` to Dockerfile's `vep` stage.
4. Rebuild toolkit image `genomeclaw/toolkit:contract-drift-protected` (or bump `slice-d-prime` tag).
5. Re-run both new tests → expect GREEN.

**REFACTOR**:
1. Tighten the meta-invariant test's discovery loop (avoid duplicates, sort outputs for stable diffs).
2. Update INVARIANTS.md v1.14 → v1.15 with the scope-clarification note + cross-reference both new tests.
3. Full toolkit suite stays green.

## Testing Strategy

### Unit + Invariant

- `test_invD006_shim_dood_scan_exhaustive.py`: pure unit test, no docker / no real-data dependency. Walks the `_cli/commands/pipeline.py` AST + parses the shim's `_dood_scan_args` function. Runs in <1s.

### Integration

- `test_vep_loftee_plugin.py` extended test: requires the toolkit image + `GENOMECLAW_SANDBOX_IMAGE` (or the in-image `GENOMECLAW_HAS_BIO=1` gate). Runs `docker run --rm genomeclaw/toolkit:<tag> vep --plugin LoF --help` (or equivalent that exercises the plugin's `BEGIN`-time module loads). Asserts no "Failed to instantiate plugin" line in stderr.

### Determinism / Provenance / Privacy / Evidence-binding / Report

Not applicable — the protections don't touch the pipeline's data path.

## Documentation Updates Required

- [docs/reference/INVARIANTS.md](../../../docs/reference/INVARIANTS.md): v1.14 → v1.15, scope-clarification on INV-D006 (shim-side propagation) + INV-T001 (plugin-load coverage), Invariant Index unchanged.
- [docs/plans/active/mvp/phases/phase-7.md](../mvp/phases/phase-7.md): close-session-2 carry-forward list gets a note acknowledging the protections.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 | Pending | | | RED → GREEN → REFACTOR for the five protections |

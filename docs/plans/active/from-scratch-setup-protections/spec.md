# Spec — From-scratch-setup protections

**Status**: Active
**Created**: 2026-05-23
**Companion**: surfaced during Phase 7 close session 1 (2026-05-22/23) — pgs-compute failed twice on the canonical real-data run because the shim's DooD-detection list didn't include `pgs-compute`. Same session: VEP's LOFTEE plugin silently NULL-ed every row because the `DBD::SQLite` perl module is missing from the toolkit image.

---

## Goal

Catch the two bug classes that surfaced during Phase 7's canonical real-data run at unit-test time so a future from-scratch GenomeClaw setup doesn't re-discover the same failures:

1. **Shim DooD-detection drift** — a subcommand that spawns DooD siblings (via Nextflow / pgsc_calc / bcftools-shard) but isn't in `bin/genomeclaw`'s `_dood_scan_args` list. The shim runs in non-DooD mode → `GENOMECLAW_HOST_ROOTS=[]` → the in-container `as_sibling_mountable(...)` pre-flight rejects every path → 1-second failure with a misleading error.
2. **Toolkit-image dep regressions** — a perl module / system library that a VEP plugin needs at runtime but isn't installed in the image. The pipeline runs end-to-end (no rc=1) but the affected annotation column is silently NULL on every row. Surfaces only at the 4-hour real-data smoke.

## Background

Phase 7's canonical real-data run on 2026-05-22 surfaced both classes inside the same ~5h smoke:

- **DooD-detection drift** (1-second symptom): `pgs-compute` invocation failed with `not under any sibling-mountable prefix (GENOMECLAW_HOST_ROOTS=[])`. Root cause: `bin/genomeclaw`'s `_dood_scan_args` lists `prs-compute` + `prs-prepare-coverage` but NOT `pgs-compute` — even though `pgs-compute` calls `compute_pgs(...)` which uses `as_sibling_mountable(...)` (the exact INV-D006 pre-flight that requires DooD mode). Fix at the shim layer is one line; fix at the test layer is a mechanical exhaustiveness check.
- **VEP LOFTEE silent failure** (5-hour symptom): `WARNING: Failed to instantiate plugin LoF: install_driver(SQLite) failed: Can't locate DBD/SQLite.pm` at VEP startup. VEP continues; `loftee_lof` is NULL on every variant. The existing `test_gerp_dist_helper_compiles_with_vep_perl_inside_image` test catches `Bio::DB::BigFile` regressions (a 2026-05-15 fix) but not `DBD::SQLite` because the test only checks `perl -c gerp_dist.pl` syntax-compile, not full plugin instantiation. LoF.pm uses `DBD::SQLite` via `do '...'` at runtime — out of `perl -c` reach.

Both bug classes share a pattern: **a contract held outside the toolkit code (the shim's DooD detection, the perl module set in the conda env) is not pinned by a test that catches drift**. Today's protections add the missing tests + sharpen the symptoms-to-diagnosis path.

## Acceptance Criteria

- [ ] **AC1**: A new test asserts the shim's `_dood_scan_args` list is exhaustive over every wrapper that uses `as_sibling_mountable(...)`. Running the test against the current main branch fails (`pgs-compute` is missing); after fixing the shim, the test passes. (`INV-D006` enforcement at the unit-test layer.)
- [ ] **AC2**: The shim's `_dood_scan_args` includes `pgs-compute` (matches AC1 expectation). The one-line shim fix.
- [ ] **AC3**: The `DooDPathError` raised when `GENOMECLAW_HOST_ROOTS=[]` distinguishes "no allowlist set by shim" from "path doesn't match an allowlisted prefix" — the empty-allowlist case suggests the shim ran in non-DooD mode + names the fix.
- [ ] **AC4**: A new test asserts every VEP plugin used in our annotate path successfully instantiates inside the toolkit image (not just syntax-compiles). For LoF + AlphaMissense specifically, the test invokes VEP against a 1-variant fixture VCF with the plugins listed + asserts the `--help`-equivalent output reports "plugin X instantiated" (or equivalent) rather than the "Failed to instantiate" warning. (`INV-T001` extension to plugin-loading regression class.)
- [ ] **AC5**: The Dockerfile's `vep` stage adds `perl-dbd-sqlite` to the conda install list. AC4's test passes after this addition.
- [ ] **AC6**: A small post-MVP follow-up note in [phase-7.md](../../mvp/phases/phase-7.md) carry-forwards documents that the shim-detection meta-invariant test exists + the LOFTEE plugin-load test exists, so a future Phase 7 close run doesn't re-discover the same gaps.

## Applicable Invariants

- **INV-D006** (DooD-Safe Path Annotation, INVARIANTS.md v1.12) — the existing invariant; this plan extends its coverage from "wrapper-side annotation" to "shim-side propagation". AC1 + AC2 + AC3 enforce this.
- **INV-T001** (External-Tool Conventions Captured as Typed Wrappers, INVARIANTS.md v1.12) — extending the discovery sweep pattern from argv-level pinning to plugin-load-level pinning. AC4 + AC5 enforce this.
- **INV-R001** (Rebuildability) — the bigger contract this plan protects. A from-scratch GenomeClaw setup should produce identical artifacts; today's regressions silently nullify a column (`loftee_lof`) without flagging it, which violates rebuildability without a corresponding test failure.

## Proposed New Invariants

None. Both bug classes are subsumed by INV-D006 + INV-T001 extensions. The protections add tests + a sharper error message + a Dockerfile dep, none of which warrant a new invariant ID.

## Out of Scope

- A full kernel-level Landlock + seccomp + netns SSRF probe (already a separate post-MVP follow-up).
- A from-scratch fresh-Mac setup smoke (also a separate post-MVP item; this plan covers the in-toolkit + in-image regression classes that the existing tooling can verify on the development host).
- Fixing the broader LOFTEE warning that emits a JSON-decoder error after the SQLite failure — same regression, same fix; AC4 + AC5 cover it.
- A retrospective fix to the just-completed Phase 7 canonical run-dir's NULL `loftee_lof` column. The protections apply forward; today's run-dir stands as the canonical Phase 7 artifact with `loftee_lof` documented as NULL for follow-up.

## Privacy & Safety Considerations

No new egress, no new credentials, no new phenotype-linked content. The protections are entirely about test discipline + a Dockerfile dep + a shim configuration value. No `privacy-safety-reviewer` invocation needed.

## Files Likely Touched

- `bin/genomeclaw` — `_dood_scan_args` extended (one line).
- `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` — sharper `DooDPathError` message.
- `packages/toolkit/Dockerfile` — `perl-dbd-sqlite` added to the vep stage.
- `packages/toolkit/tests/invariants/test_invD006_shim_dood_scan_exhaustive.py` — NEW (AC1).
- `packages/toolkit/tests/integration/test_vep_loftee_plugin.py` — extended for plugin-instantiation check (AC4).
- `docs/reference/INVARIANTS.md` — version-stamp + scope-clarification update on INV-D006 + INV-T001.
- `docs/plans/active/mvp/phases/phase-7.md` — close-session-2 carry-forward note (AC6).

## Open Questions

1. **Does the AC4 LOFTEE plugin-load test need an image rebuild?** If we ship the test + the Dockerfile fix together, the test will fail on the current `slice-d-prime` image (the regression is what we're catching). Resolution: gate the AC4 test on `GENOMECLAW_SANDBOX_IMAGE` env var (mirror the existing pattern); after the next image rebuild, the test passes + becomes a regression guard. Document the gating clearly.
2. **Does the AC3 sharper error message need to distinguish more than two cases?** The current `DooDPathError` covers: (a) canonical-mount path, (b) ephemeral scratch path, (c) un-allowlisted prefix. Add a fourth: (d) empty allowlist (shim ran in non-DooD mode). Four total cases; readable + diagnostic.

# Work Notes — From-scratch-setup protections

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored mid-Phase-7-close-session-1

**Context**: pgs-compute failed twice during Phase 7's canonical real-data run + VEP LOFTEE plugin silently NULL-ed every row. User asked: "How do we make sure this does not happen when setting up GenomeClaw from scratch later?" Plan authored alongside the ongoing Phase 7 work; protections apply forward.

**Applicable Invariants**: INV-D006 (DooD-Safe Path Annotation; extended to shim-side propagation), INV-T001 (External-Tool Conventions; extended to plugin-load coverage), INV-R001 (Rebuildability; the meta-rule both protections serve).

**Open Questions**:
- AC4 LOFTEE plugin-load test needs an image rebuild — gate on `GENOMECLAW_SANDBOX_IMAGE` env var (mirror existing pattern).
- AC3 sharper `DooDPathError` — four cases (canonical-mount, ephemeral-scratch, un-allowlisted, empty-allowlist).

**Next Step**: Phase 1 RED — author the two new tests + confirm both fail for the intended reasons before any fix lands.

---

## 2026-05-23 — Phase 1 RED → GREEN → REFACTOR complete; plan archived

**Completed in one session**:

- **Phase 1.1 RED**: authored `test_invD006_shim_dood_scan_exhaustive.py` (mechanical AST walk + shim regex parse). Initial run flagged `pgs-compute` AND `cyp2d6-call` as missing — but `cyp2d6-call`'s wrapper doesn't actually import `as_sibling_mountable` (the substring-match in my first draft false-positive'd on a comment). Tightened discovery to AST-based import detection; re-run flagged only `pgs-compute` (the real bug). Authored `test_dbd_sqlite_loadable_from_vep_perl_inside_image` extension to `test_vep_loftee_plugin.py` — verified RED against the current `slice-d-prime` image (`Can't locate DBD/SQLite.pm`, EXIT=2).
- **Phase 1.2 GREEN**:
  - Added `pgs-compute` to the shim's `_dood_scan_args` (one-line + a comment block citing the new invariant test).
  - Extended `DooDPathError` in `prep/_paths.py` with the empty-allowlist branch — names `_dood_scan_args` in the fix hint.
  - Added `perl-dbd-sqlite` to the Dockerfile's vep stage's bioconda install.
  - Rebuilt `genomeclaw/toolkit:slice-d-prime` (~5 min); verified `perl -MDBD::SQLite -e 1` exits 0 + DBD::SQLite 1.78.
- **Phase 1.3 REFACTOR**:
  - Updated INVARIANTS.md → v1.15 with scope clarifications on INV-D006 + INV-T001 (no new invariant IDs; rule text unchanged; v1.15 bullet added).
  - Updated phase-7.md's carry-forward list to acknowledge the protections landed.
  - Toolkit suite stays green: **778 passed** (was 776; +2 from the new meta-invariant tests).
- **Commit + push**: 806b6ec on origin/main.

**Status**: Complete. Plan moved from `active/` to `completed/`.

**Carry-forward (none blocking)**: future image rebuilds + the next from-scratch GenomeClaw setup will encounter the two protections at unit-test time, not at the next 5-hour real-data smoke.

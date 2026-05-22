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

# GenomeClaw — TODO Index

Parked work that doesn't yet have an active implementation owner. Each entry points to a planning artifact or an issue with enough context to pick up cold.

For active work, see [docs/plans/active/](plans/active/). For the planning protocol itself, see [docs/plans/CLAUDE.md](plans/CLAUDE.md).

---

## Parked Plans

### Reference-data integrity hardening

**Plan**: [docs/plans/active/refs-integrity-hardening/](plans/active/refs-integrity-hardening/)
**Status**: Drafted 2026-05-13, not yet picked up
**Trigger to pick up**:
- A real corruption / partial-fetch event surfaces (most likely signal).
- The project owner wants forwardable "this annotation was definitely ClinVar release X" evidence for a clinician handoff.
- Any expansion of the reference-fetch surface (a new source, a new mirror, a new external dataset) that would benefit from manifest provenance up-front.

**Why it's parked rather than done now**: the existing integrity check (`Path.exists()` + per-source MD5 sidecars for clinvar/dbsnp/grch38) is sufficient for accidental corruption in the single-user threat model, and the project owner has not yet hit a real failure mode that the gap explains. Five phases, ~30–40 tests, no new invariant (extends INV-R001).

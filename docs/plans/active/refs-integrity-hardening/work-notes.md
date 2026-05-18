# Reference-Data Integrity Hardening — Work Notes

**Feature**: Manifest-anchored integrity for `refs fetch` / skip-check / `refs verify`.
**Started**: not yet picked up
**Branch**: `feature/refs-integrity-hardening` (TBD)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-13 — Plan inception

**Context**:
- Trigger: during MVP Phase 4 refs work (LOFTEE mirror routing + vep_cache skip-detection fix), audit of [fetch.py:1104](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py#L1104) revealed three distinct integrity gaps:
  1. 5 of 8 sources lack MD5 sidecars (Content-Length-only verification).
  2. `VersionAlreadyExists` skip check is `Path.exists()` only — passes 0-byte files, bit-rot, manual tampering, partial multi-file fetches.
  3. `refs verify` only checks bgzip-EOF on `.vcf.gz/.vcf.bgz/.bcf`; ignores FASTA, BigWig, TSV, SQL, tarballs, vep_cache structure, sidecar presence.
- The vep_cache `presence_relpath` shim landed as a narrow fix for a single concrete bug (re-downloading 21 GB on every `refs fetch --all`). It is structurally a `Path.exists()` check on a different filename — same class of guarantee, same gap class. It should be removed once the manifest is in place.
- No new invariant required. INV-R001 already mandates "input identity (path + content hash or version)" — this work implements that at the reference-fetch layer.

**Applicable Invariants**:
- **INV-D001**: skip check must continue to refuse overwriting healthy already-fetched dirs; the strengthening is on detection, not on the refuse-to-overwrite rule.
- **INV-R001**: this plan is the long-overdue completion of INV-R001 at the reference layer.
- **INV-P001**: no new egress; manifests are local-only.

**Key Insights**:
- Hashing cost for the 12.6 GB GERP file or 200 GB gnomad-exomes is the design pivot. Solution: hash inline during fetch (free — bytes already stream through hashlib), use cheap `fast_hash` (first 64 KiB + last 64 KiB + size) for skip-check, reserve full sha256 for explicit `refs verify`.
- Per-file repair (`refs fetch --repair`) is the killer feature. Without it, a 1-byte corruption in a 200 GB source forces a full re-download, which is so painful that users will work around the verify check instead of fixing the underlying corruption.
- Backfill must be opt-in. Auto-backfilling on first `refs fetch --all` would trust whatever's on disk — exactly the opposite of what this plan is about.

**Completed Today**:
- [x] spec.md drafted
- [x] development-plan.md drafted
- [x] Phase 1–5 outlined in development-plan; phase-N.md files not yet created (deferred to pickup)
- [x] TODO.md pointer added
- [x] grand-plan.md reference added under "Risks & Open Questions"

**Decisions Made**:
- **Single manifest per source-release** (not per-file). Atomic write semantics, easier `refs verify` traversal.
- **Schema-versioned JSON.** Stdlib-parsable, line-diffable, agent-readable.
- **`fast_hash` for skip-check, `sha256` for verify.** Re-hashing GERP on every `refs fetch --all` would defeat the skip-check's purpose.
- **No new INV-xxx.** Reuses INV-R001; cleaner than proliferating IDs for a layered enforcement of the same rule.

**Blockers / Issues**:
- Not yet picked up. No blockers — plan is ready for a future implementation session.

**Next Steps**:
1. When picked up, draft `phases/phase-1.md` first (Manifest schema + write-on-fetch) — Phase 1 lands the foundation, every subsequent phase depends on it.
2. Confirm Q1–Q4 from spec.md before Phase 1's RED step.
3. Run the privacy-safety-reviewer agent on the diff once the manifest schema is concrete.

---

## Phase Progress

### Phase 1: Manifest Schema + Write-On-Fetch
**Status**: Pending

### Phase 2: Manifest-Anchored Skip Check
**Status**: Pending

### Phase 3: `refs verify` Deep Checks
**Status**: Pending

### Phase 4: `refs fetch --repair`
**Status**: Pending

### Phase 5: Backfill + `host doctor` + Docs
**Status**: Pending

---

## Key Decisions

### Decision 1: No new invariant
**Date**: 2026-05-13
**Context**: The work strengthens existing integrity guarantees. Should it promote a new INV-Rxxx?
**Decision**: No. INV-R001 already requires content hashes on derived store inputs; the reference layer is just another input. Promoting a new ID would suggest a new rule when in fact it's the same rule reaching a new layer.
**Rationale**: Invariant IDs are precious; proliferation dilutes them.
**Alternatives Considered**: `INV-R002: Fetched References Carry Manifests` — rejected as a re-statement.
**Affected Invariants**: INV-R001 ("How to verify" section to be updated to mention manifest check).

### Decision 2: `fast_hash` for skip-check
**Date**: 2026-05-13
**Context**: Full sha256 of 12.6 GB GERP on every `refs fetch --all` is unacceptable.
**Decision**: Use sha256 of first 64 KiB + last 64 KiB + size for the skip-check predicate; reserve full sha256 for explicit `refs verify`.
**Rationale**: Catches truncation, manual editing, and most accidental corruption at near-zero cost. Adversarial bit-flips in the middle of the file pass — but the threat model is "single-user, accidental corruption / partial fetch / disk full," not "adversary with file-edit access."
**Alternatives Considered**: Full sha256 always (rejected on cost); Content-Length only (rejected — that's status quo); merkle-tree of 1 MiB chunks (rejected as over-engineering for the single-user threat model).
**Affected Invariants**: INV-R001 strengthened.

---

## Files Modified

### Created (planned)
- `docs/plans/active/refs-integrity-hardening/spec.md` — feature spec
- `docs/plans/active/refs-integrity-hardening/development-plan.md` — phased plan
- `docs/plans/active/refs-integrity-hardening/work-notes.md` — this file
- Implementation files: see development-plan §"Files to Create"

### Modified (planned)
- See development-plan §"Files to Modify"

### Deleted (planned)
- `_SourceLayout.presence_relpath` field (introduced 2026-05-13 as a narrow vep_cache fix; obsoleted by Phase 2's manifest predicate)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Update INV-R001 "How to verify" to reference the manifest check (no new ID).

### Other Documentation
- [ ] `docs/reference/refs-manifest.md` — new schema reference
- [ ] `docs/reference/architecture.md` — note manifest in host-side ref-data layout
- [ ] `.claude/agents/bioinformatics-pipeline.md` — add manifest as a first-class artifact

---

## Open Risks & Follow-ups

- Hashing cost on large sources — addressed via `fast_hash` design (see Decision 2).
- Concurrent-fetch manifest write race — mitigated by atomic rename + per-release lock file.
- Backfill manifest with stale `_LAYOUTS` URL when a mirror has changed since legacy fetch — acceptable; downstream cares about sha256, not URL.
- vep_cache structural walk surface area — Phase 3 decision deferred to walk only top-level markers.

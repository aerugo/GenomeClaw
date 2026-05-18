# Phase 5: Backfill, `host doctor`, Docs

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Cover the long tail: legacy release dirs (fetched before this feature) get an opt-in backfill path; `host doctor` reports verify status per source; the manifest schema is documented for future contributors and external readers.

## Scope Boundaries

- **In scope**: `genomeclaw refs verify --backfill-manifest` flag; `host doctor` reads manifests and reports a per-source "verified" / "verified-stale (>30 d)" / "unverified" badge; `docs/reference/refs-manifest.md` with schema + example; INV-R001 "How to verify" section updated.
- **Out of scope**: Automatic backfill on first run after upgrade (must be explicit user action); cross-toolkit-version manifest migration (schema_version field is in place but no v1 → v2 migration is shipped here).

## Invariants Enforced in This Phase

- **INV-R001**: backfill produces a valid manifest for legacy dirs, bringing them into the same "input identity = content hash" contract.

---

## TDD Steps

### Step 5.1 — RED: Write Failing Tests

**Test cases**:

1. `test_backfill_writes_manifest_for_legacy_dir` — release dir with canonical files but no `manifest.json`; `refs verify --backfill-manifest --yes` writes a valid manifest with sha256 of every file.
2. `test_backfill_uses_live_layouts_urls` — backfilled manifest's `source_url` field is the current `_LAYOUTS` URL (acknowledged trade-off; documented in spec.md Q4).
3. `test_backfill_requires_explicit_yes` — without `--yes` in non-TTY mode, command prompts for confirmation and refuses to write.
4. `test_backfill_refuses_when_manifest_already_present` — release dir already has a manifest; `--backfill-manifest` exits with "manifest already exists; use `--force-overwrite` if you really mean it" (and that flag is deliberately not shipped — user must `rm manifest.json` first).
5. `test_doctor_reports_verify_status` — three release dirs: one with fresh manifest, one with manifest fetched_at >30 d ago, one without manifest → `host doctor` prints `verified`, `verified-stale`, `unverified` respectively.
6. `test_doctor_summary_aggregates_status` — multi-source release set → doctor's summary line counts each status category.
7. `test_backfill_handles_per_chrom_source` — legacy gnomad-exomes dir with 48 files → backfill walks all 48 and records each.
8. `test_invR001_backfill_satisfies_input_identity` — after backfill, every file in the release dir has a manifest record with non-null sha256.

### Step 5.2 — GREEN: Minimal Implementation

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` — MODIFY. Add `--backfill-manifest` and `--yes` flags to `refs verify`; route to a new `backfill_manifest_for_release_dir(...)` function in `prep/manifest.py`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` — MODIFY. Add `backfill_manifest_for_release_dir(release_dir, layout, release) -> Manifest` (walks layout's expected files; for each present, computes sha256 + builds FileRecord with live `_LAYOUTS` URL; for each missing, raises explicit error).
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` — MODIFY. `host doctor` reads each release dir's manifest, classifies status, includes in payload + rich output.
- `docs/reference/refs-manifest.md` — CREATE. Schema reference + on-disk example + migration guidance.
- `docs/reference/INVARIANTS.md` — MODIFY. Update INV-R001 "How to verify" to mention the manifest check.

### Step 5.3 — REFACTOR

- Extract the doctor's per-source status classifier (`classify_refs_status(manifest, now)`) so it's testable in isolation.
- Re-read the doc once code stabilizes; check that the on-disk example matches what `refs fetch` actually produces.

---

## Implementation Details

### Edge Cases to Handle

- **Backfill on a partially-populated legacy dir** (e.g., a failed multi-file fetch that left chr1-15 only) → backfill refuses; user must either delete the partial dir or run `refs fetch --source <name> --release <r>` to complete it first.
- **Doctor running on a host that has no reference dir yet** → status is `not-fetched`, not `unverified`; this is a different category.
- **30-day staleness threshold**: hard-coded for now; surface as a named constant in the doctor module; revisit if the project owner wants to tune.

### Error Handling

- Backfill failure on a single file (read error, permission denied) → fail loudly; do NOT write a partial manifest.

### Privacy / Egress Notes

- None — backfill and doctor are local-only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` | MODIFY | `--backfill-manifest` + `--yes` flags |
| `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` | MODIFY | `backfill_manifest_for_release_dir` |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Doctor reads + classifies manifest status |
| `packages/toolkit/tests/integration/test_refs_backfill_manifest.py` | CREATE | Cases 1–4, 7, 8 |
| `packages/toolkit/tests/integration/test_cli_host_doctor.py` | MODIFY | Cases 5–6 |
| `docs/reference/refs-manifest.md` | CREATE | Schema reference |
| `docs/reference/INVARIANTS.md` | MODIFY | INV-R001 "How to verify" update |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_refs_backfill_manifest.py tests/integration/test_cli_host_doctor.py -q
uv run pytest tests/ -q  # full regression — final gate before plan completes
uv run ruff check src/ tests/
uv run mypy src/
```

Manual smoke:

```bash
# Legacy dir (pre-feature)
rm -f /mnt/genomeclaw/reference/clinvar/2026-05-09/manifest.json
genomeclaw refs verify --backfill-manifest --yes
genomeclaw host doctor   # should show clinvar as 'verified'
```

---

## Completion Criteria

- [ ] All listed test cases pass
- [ ] Static checks pass
- [ ] `INV-R001` verified by `test_invR001_backfill_satisfies_input_identity`
- [ ] `docs/reference/refs-manifest.md` reviewed by an external reader (or the report-generator agent for clarity)
- [ ] INV-R001 "How to verify" section updated
- [ ] `work-notes.md` updated; final session block + plan-complete summary
- [ ] Phase 5 status updated to Complete in `development-plan.md`
- [ ] Plan moved from `docs/plans/active/refs-integrity-hardening/` to `docs/plans/completed/refs-integrity-hardening/`

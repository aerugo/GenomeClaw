# Phase 2: Manifest-Anchored Skip Check

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Replace the `Path.exists()` skip-check loop in `fetch()` with a manifest-anchored predicate: a release dir is "already fetched" only when its `manifest.json` parses, every listed file is present at the recorded size, and a cheap `fast_hash` of each file matches the manifest record.

## Scope Boundaries

- **In scope**: Skip-predicate logic; legacy-dir fallback (no manifest → existing `Path.exists()` behaviour); `fast_hash` helper; per-file partial-fetch detection (signals to the orchestrator that one or more files need repair).
- **Out of scope**: Actually performing repair (Phase 4); recomputing full sha256 (Phase 3). When Phase 2's predicate detects a tampered file it raises a new `NeedsRepair` exception which is documented but not yet handled by `refs fetch` — the user sees a clear "refs are corrupt, run `refs fetch --repair` (Phase 4)" message and exits.

## Invariants Enforced in This Phase

- **INV-D001**: skip-check refuses to overwrite a healthy already-fetched release, but does not skip a corrupt or partial one.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases**:

1. `test_skip_when_manifest_intact` — manifest present, all files exist at recorded sizes + fast_hash matches → `VersionAlreadyExists`.
2. `test_no_skip_when_canonical_file_zero_bytes` — manifest says size=N, file is 0 bytes → `NeedsRepair`, not `VersionAlreadyExists`.
3. `test_no_skip_when_canonical_file_deleted` — manifest lists 48 files (gnomad-exomes), one is missing → `NeedsRepair` naming the missing file.
4. `test_no_skip_when_fast_hash_mismatch` — manifest's fast_hash for a file disagrees with the on-disk first-and-last 64 KiB → `NeedsRepair`.
5. `test_legacy_fallback_when_manifest_absent` — no `manifest.json` exists in the release dir; fall through to existing `Path.exists()` check → `VersionAlreadyExists` if any canonical file exists.
6. `test_legacy_fallback_emits_doctor_hint` — when legacy fallback triggers, log a one-line hint suggesting `refs verify --backfill-manifest`.
7. `test_invD001_intact_release_not_overwritten` — even after the skip is bypassed for one file, the other files in the release are not touched (no `os.replace`, no scratch writes).
8. `test_fast_hash_is_deterministic` — repeated calls on the same byte content produce the same digest; matches a hand-computed reference.

Run RED. The first six fail because the skip-check is still `Path.exists()`. Tests 7 + 8 may pass trivially — implementation must keep them green.

### Step 2.2 — GREEN: Minimal Implementation

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` — MODIFY. Add `fast_hash(path) -> str` helper; `verify_manifest_against_disk(release_dir, manifest) -> ManifestVerifyResult` returning per-file pass/fail.
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY. Replace the `Path.exists()` loop with: `manifest = read_manifest(target_dir); if manifest: result = verify_manifest_against_disk(...); if all_pass → VersionAlreadyExists; elif any_fail → NeedsRepair; else legacy path`.
- `NeedsRepair` new exception class with `affected_relpaths: tuple[str, ...]` payload.
- Remove `_SourceLayout.presence_relpath` and its substitution in `_apply_release`; remove vep_cache's marker entry (manifest replaces it).

### Step 2.3 — REFACTOR

- Extract the skip-check into `_check_already_fetched(target_dir, layout, files_to_fetch) -> AlreadyFetchedStatus` so `fetch()` stays narrow.
- Update the CLI's `_fetch_one_source` wrapper in `_cli/commands/refs.py` to map `NeedsRepair` into a structured error event + actionable suggestion ("run `refs fetch --repair` once Phase 4 lands").

---

## Implementation Details

### Edge Cases to Handle

- **Manifest claims more files than `_LAYOUTS` knows about** (e.g., user deleted a file from `_LAYOUTS` between fetches) → treat as "manifest is from a future version"; legacy-fallback with a warning.
- **`_LAYOUTS` claims more files than the manifest knows about** (release set grew) → treat as `NeedsRepair`; new file is missing.
- **Per-chrom source skip-predicate**: the manifest lists all 48 files; skip only when all 48 verify. Repair signals the failing chroms.

### Error Handling

- `NeedsRepair` until Phase 4: surface as a `DataIntegrityError` with `suggested_actions=["Run 'genomeclaw refs verify' for details; 'refs fetch --repair' will be wired in Phase 4. As a workaround, 'rm -rf <release-dir>' and re-fetch."]`.

### Privacy / Egress Notes

None — purely local predicate.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` | MODIFY | Add `fast_hash` + verifier |
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | New skip-predicate; remove `presence_relpath` shim |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` | MODIFY | Map `NeedsRepair` to user-facing message |
| `packages/toolkit/tests/integration/test_fetch_mocked.py` | MODIFY | Add the eight cases above |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_fetch_mocked.py -q
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv run mypy src/genomeclaw_toolkit/prep/
```

---

## Completion Criteria

- [ ] All listed test cases pass
- [ ] Static checks pass
- [ ] `INV-D001` is verified by `test_invD001_intact_release_not_overwritten`
- [ ] `presence_relpath` is removed; no test in the suite references it
- [ ] `work-notes.md` updated
- [ ] Phase 2 status updated to Complete

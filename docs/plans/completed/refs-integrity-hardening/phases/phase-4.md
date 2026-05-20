# Phase 4: `refs fetch --repair`

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Add a per-file repair path so a single corrupted file in a 200 GB release dir no longer forces a full re-download. After this phase, the `NeedsRepair` exception raised by Phase 2's skip-check has an actionable resolution: `genomeclaw refs fetch --repair --source X --release Y` (or `--all`).

## Scope Boundaries

- **In scope**: `--repair` flag on `refs fetch`; per-file re-fetch using the same `_fetch_one_file` orchestrator path; manifest update for repaired files (new sha256 + new `fetched_at` for the affected file only); healthy files left untouched (mtime preserved).
- **Out of scope**: Auto-repair on `refs fetch --all` (must be opt-in via `--repair`); repair-driven backfill (a release dir without any manifest cannot be "repaired" — that's Phase 5's backfill).

## Invariants Enforced in This Phase

- **INV-D001**: repair touches **only** the files that fail verification; healthy files in the same release remain byte-immutable.

---

## TDD Steps

### Step 4.1 — RED: Write Failing Tests

**Test cases**:

1. `test_repair_refetches_only_failing_file` — release with two files, one corrupted; `--repair` re-fetches only the corrupted file, the healthy file's bytes + mtime are preserved.
2. `test_repair_updates_manifest_for_repaired_file_only` — after repair, the manifest's `fetched_at` for the repaired file is new; for the untouched file it is unchanged.
3. `test_repair_recomputes_sha256_for_repaired_file` — the new manifest entry's sha256 matches the freshly-fetched bytes.
4. `test_repair_refuses_when_no_manifest` — release dir without manifest → `--repair` exits with "no manifest to repair against; run `refs verify --backfill-manifest` or fetch fresh".
5. `test_repair_passes_through_for_healthy_release` — already-healthy release + `--repair` flag → no-op, exit 0, manifest unchanged.
6. `test_repair_handles_per_chrom_source` — gnomad-exomes with chr15 corrupted → repair fetches chr15 only (one .vcf.bgz + one .tbi), the other 47 files untouched.
7. `test_repair_atomicity_on_mid_repair_failure` — patch the network call to fail mid-repair; assert the corrupted-but-known file is still there (scratch cleanup ran), the manifest was NOT updated, and a subsequent repair retries cleanly.
8. `test_invD001_repair_does_not_overwrite_healthy_files` — explicit invariant test: pre-record sha256 + mtime of every healthy file in a 3-file release where one is corrupted; after repair, assert every healthy file's sha256 + mtime is unchanged.

### Step 4.2 — GREEN: Minimal Implementation

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` — MODIFY. Add `--repair: bool` flag on `refs fetch`; when set, switch to the repair code path.
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY. New `repair()` entry point that takes a manifest + list of failing relpaths and re-runs `_fetch_one_file` for each. Reuses the same atomic-rename + scratch-cleanup logic so failure mid-repair leaves a clean (still-failing) state.
- Manifest update: re-run `compute_file_record` for the repaired files, splice into the existing manifest, atomic-rewrite.

### Step 4.3 — REFACTOR

- Extract a `repair_files(release_dir, manifest, failing_relpaths)` helper so `fetch()` and `repair()` share the per-file orchestrator without duplication.
- Update help text and `--help` snapshot tests.

---

## Implementation Details

### Edge Cases to Handle

- **Repair target's URL has changed since the original fetch** (mirror swap like LOFTEE GERP) → repair uses the *current* `_LAYOUTS` URL; manifest records the new URL post-repair. Trade-off discussed in plan §"Open Risks": acceptable; sha256 is what consumers bind to.
- **Repair target file is a sidecar (e.g., `.tbi`)** → the layout doesn't model sidecars as standalone fetches today; they ride with the canonical file. Repair re-fetches the canonical file's full bundle (data + sidecar) when either is corrupt. Manifest records both.
- **User passes `--repair` without an `--all`, `--source`, or `--release-set`** → CLI usage error; require an explicit target.

### Error Handling

- A repair that itself fails to fetch the new bytes → `RuntimeFailure`; pre-repair state preserved.
- A repair that succeeds in fetch but the new bytes also fail hash verification → `DataIntegrityError`; pre-repair scratch deleted; manifest unchanged.

### Privacy / Egress Notes

- Same egress profile as a regular `refs fetch`. Repair surfaces only the per-file URL it's re-fetching.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` | MODIFY | `--repair` flag + plumbing |
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | `repair()` entry point + manifest splice |
| `packages/toolkit/tests/integration/test_refs_repair.py` | CREATE | Eight cases above |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_refs_repair.py -q
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv run mypy src/
```

Manual smoke:

```bash
# Corrupt one file deliberately
truncate -s 100 /mnt/genomeclaw/reference/clinvar/2026-05-09/clinvar.vcf.gz

# Repair
genomeclaw refs fetch --repair --source clinvar --release 2026-05-09

# Verify
genomeclaw refs verify
```

---

## Completion Criteria

- [ ] All listed test cases pass
- [ ] Static checks pass
- [ ] `INV-D001` verified by `test_invD001_repair_does_not_overwrite_healthy_files`
- [ ] Manual smoke completes; verify reports clean after repair
- [ ] `work-notes.md` updated
- [ ] Phase 4 status updated to Complete

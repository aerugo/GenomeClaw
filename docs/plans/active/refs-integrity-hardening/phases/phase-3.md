# Phase 3: `refs verify` Deep Checks

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Grow `genomeclaw refs verify` from a bgzip-EOF sweep into a manifest-anchored re-hash + sidecar audit + structural cache walk. After this phase, the command can credibly answer "is my on-disk reference data byte-identical to what was fetched?"

## Scope Boundaries

- **In scope**: Full sha256 recompute against the manifest for every file in every release dir; tabix `.tbi` presence check for `.vcf.gz` / `.tsv.gz`; FASTA `.fai` + `.gzi` presence for `.fa.gz`; structural walk of `vep_cache/<release>/homo_sapiens/<N>_GRCh38/` (top-level `info.txt` + one per-chromosome marker); structured per-file report.
- **Out of scope**: Repair (Phase 4); backfill (Phase 5); `host doctor` integration (Phase 5). Phase 3 only **reports**; remediation is deferred.

## Invariants Enforced in This Phase

- **INV-R001**: re-verification that the recorded content hashes still match disk content; the strongest in-toolkit integrity check.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

**Test cases**:

1. `test_verify_passes_when_all_hashes_match` — synthetic release dir + manifest with correct sha256s → exit 0, every file reported `sha256_match: true`.
2. `test_verify_fails_on_sha256_mismatch` — flip one byte in one canonical file, leave manifest unchanged → exit 4, that file reported `sha256_match: false`, others unaffected.
3. `test_verify_reports_missing_tabix_sidecar` — `.vcf.gz` present, `.tbi` absent → reported as `sidecar_missing` with the expected sidecar relpath.
4. `test_verify_reports_missing_fasta_index` — `.fa.gz` present, `.fai` or `.gzi` absent → reported.
5. `test_verify_walks_vep_cache_structural_markers` — vep_cache release missing `homo_sapiens/<N>_GRCh38/info.txt` → reported as `structural_incomplete`.
6. `test_verify_legacy_dir_without_manifest_falls_back_to_eof_check` — release dir has no manifest; verify runs the existing bgzip-EOF check + sidecar audit and emits a "manifest absent — run `refs verify --backfill-manifest`" hint.
7. `test_verify_payload_has_per_file_records` — `RefsVerifyPayload` JSON output includes one record per checked file with all four boolean fields populated.
8. `test_verify_streams_sha256_for_large_files` — fixture file > 200 MB; verify completes without loading the whole file into memory (assert via tracemalloc or by streaming a generator file).
9. `test_invR001_verify_recomputes_hashes` — at least one test in this phase is named with `invR001` and asserts the recompute path.

### Step 3.2 — GREEN: Minimal Implementation

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` — MODIFY. `refs_verify` walks each release dir, reads manifest, recomputes sha256, audits sidecars, walks vep_cache markers, emits structured payload.
- `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` — MODIFY. Add `recompute_sha256(path) -> str` (streamed); `audit_sidecars(release_dir, canonical_relpath) -> list[str]` for each file class.
- `packages/toolkit/src/genomeclaw_toolkit/_cli/payloads.py` (or wherever payloads live) — extend `RefsVerifyPayload` with the new per-file fields.

### Step 3.3 — REFACTOR

- Extract per-file-class sidecar-audit helpers (`audit_vcf_gz_sidecars`, `audit_fa_gz_sidecars`, `audit_vep_cache_structure`) — three concrete callers makes the abstraction earn its keep.
- Tighten the rich renderer (`render_refs_verify`) to print per-file pass/fail in tabular form when output is a TTY.

---

## Implementation Details

### Edge Cases to Handle

- **Manifest exists but is malformed** → exit 4, report as `manifest_unreadable` with parse-error detail.
- **File listed in manifest but missing from disk** → exit 4, report as `file_missing`. (Phase 2's fast_hash check catches this at fetch time; verify catches it for inert state.)
- **`vep_cache` post-fetch deletion**: manifest records the tarball's sha256 captured at fetch time, but the tarball is gone. Verify should NOT try to recompute that hash. Mark tarball entries with a `transient: true` flag at manifest-write time (Phase 1 follow-up) or detect by relpath suffix.
- **Bgzip EOF check stays**: a `.vcf.gz` can have a correct sha256 but a missing EOF marker (truncation that happens to land at a chunk boundary in some pathological storage). Keep the EOF check as a cheap belt-and-braces structural cross-check.

### Error Handling

- `DataIntegrityError` with structured `details` listing every failing file. Exit 4.

### Privacy / Egress Notes

- None — verify is local-only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` | MODIFY | Expand `refs_verify` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` | MODIFY | Recompute + sidecar-audit helpers |
| `packages/toolkit/tests/integration/test_cli_refs_verify.py` | MODIFY | Add the eight cases above |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_cli_refs_verify.py -q
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv run mypy src/
```

Manual smoke (on the user's actual reference root):

```bash
genomeclaw refs verify
genomeclaw refs verify --reference-root /mnt/genomeclaw/reference  # explicit
```

---

## Completion Criteria

- [ ] All listed test cases pass
- [ ] Static checks pass
- [ ] `INV-R001` verified by `test_invR001_verify_recomputes_hashes`
- [ ] Manual smoke against the user's reference root completes without false positives
- [ ] `work-notes.md` updated
- [ ] Phase 3 status updated to Complete

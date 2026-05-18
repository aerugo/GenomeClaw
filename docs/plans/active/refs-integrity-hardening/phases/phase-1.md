# Phase 1: Manifest Schema + Write-On-Fetch

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land the manifest primitive: a `prep/manifest.py` module that defines the v1 schema, can read / write / verify a manifest, and is invoked at the end of every successful `refs fetch --source X` to record sha256 + size + source URL + upstream MD5 per canonical file.

## Scope Boundaries

- **In scope**: Manifest dataclass; sha256 computation (streamed); JSON I/O with atomic rename; integration into `fetch()` post-source-completion hook.
- **Out of scope**: Skip-check changes (Phase 2); `refs verify` recompute (Phase 3); repair (Phase 4); backfill (Phase 5). Phase 1 only **writes** manifests — reading them affects nothing yet.

## Invariants Enforced in This Phase

- **INV-R001**: every fetched source-release records content hashes, satisfying "input identity (path + content hash or version)" at the reference layer for the first time.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases**:

1. `test_manifest_roundtrip` — write a synthetic `Manifest` to a tmp_path, read it back, assert structural equality.
2. `test_manifest_records_sha256_matching_disk` — write a fixture byte string to a file, build a manifest entry for it, assert the recorded sha256 matches `hashlib.sha256(file.read_bytes()).hexdigest()`.
3. `test_manifest_records_upstream_md5_when_available` — for a source with `md5_relpath` (clinvar), the manifest records the published MD5 alongside the locally-computed sha256. For a source without (loftee), `upstream_md5` is null.
4. `test_manifest_write_is_atomic` — patch `os.replace` to raise mid-call; assert no partial `manifest.json` is left on disk.
5. `test_invR001_fetch_writes_manifest_for_every_source` — integration: run `fetch` against the mocked httpserver for each source in the default release set; assert `manifest.json` exists and lists every layout file with non-null sha256.
6. `test_manifest_schema_version_is_present` — every written manifest has `schema_version: 1`.
7. `test_manifest_records_source_url_actually_used` — when a file's `url_override` was used (LOFTEE GERP), the manifest records the override URL, not the layout's `base_url + relpath`.

Run all RED tests; confirm they fail because `prep/manifest.py` does not exist and `fetch()` does not write manifests.

### Step 1.2 — GREEN: Minimal Implementation

**Files affected**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` — CREATE. Dataclasses `FileRecord`, `Manifest`; functions `compute_file_record(path, source_url, upstream_md5)`, `read_manifest(release_dir) -> Manifest | None`, `write_manifest(release_dir, manifest) -> None` (atomic).
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY. After the `post_fetch` hook completes (line ~1180), build a `Manifest` from `files_to_fetch` + recorded MD5s + observed sha256s and write it to `target_dir`.
- `_fetch_one_file` — accumulate the sha256 alongside the existing md5; pass it back to the orchestrator so `fetch()` can build the manifest without re-hashing.

### Step 1.3 — REFACTOR

- Move sha256 streaming into `_stream_to_file` cleanly (it already streams for md5; sha256 is a one-line addition to the same loop).
- Extract `Manifest.from_fetch_results(...)` constructor to keep `fetch()` readable.
- Tighten types on `FileRecord`.

---

## Implementation Details

### Edge Cases to Handle

- **A source has zero files** (synthetic test case) → manifest is written with an empty `files` list, schema_version present.
- **post_fetch hook deletes the canonical file** (vep_cache) → manifest records the file's sha256 as observed at fetch time (before deletion). Subsequent skip-checks consult the manifest, not the absent file — Phase 2 work.
- **Per-chrom source** (gnomad-exomes) → manifest's `files` list contains all 48 entries (24 .vcf.bgz + 24 .tbi).

### Error Handling

- Manifest write failure (disk full, permission denied) → propagate as `RuntimeError` after the fetch has otherwise succeeded. The user sees "fetch succeeded but manifest write failed — refs verify will treat this dir as legacy." Acceptable: the data is on disk.

### Privacy / Egress Notes

None — manifest is a pure local artifact.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` | CREATE | Manifest primitives |
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | Write manifest at end of fetch |
| `packages/toolkit/tests/unit/test_manifest.py` | CREATE | Unit coverage for manifest module |
| `packages/toolkit/tests/integration/test_fetch_mocked.py` | MODIFY | Add manifest-write assertions |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/unit/test_manifest.py -q
uv run pytest tests/integration/test_fetch_mocked.py -q
uv run pytest tests/ -q  # full regression
uv run ruff check src/ tests/
uv run mypy src/genomeclaw_toolkit/prep/manifest.py
```

---

## Completion Criteria

- [ ] All listed test cases pass (RED → GREEN → REFACTOR visible in commits)
- [ ] Static checks pass (ruff, mypy)
- [ ] `INV-R001` is verified by `test_invR001_fetch_writes_manifest_for_every_source`
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures
- [ ] `work-notes.md` updated with RED output, GREEN diff summary, and Phase-1-complete block
- [ ] Phase 1 status updated to Complete in `development-plan.md`

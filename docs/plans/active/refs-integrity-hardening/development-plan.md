# Reference-Data Integrity Hardening — Development Plan

**Status**: Draft (not yet picked up)
**Created**: 2026-05-13
**Branch**: `feature/refs-integrity-hardening` (TBD)
**Spec**: [spec.md](spec.md)

---

## Summary

Replace the existing `Path.exists()`-based "already fetched" gate with a per-release `manifest.json` recording sha256 + upstream MD5 + source URL per file, and grow `refs verify` from a bgzip-EOF sweep into a manifest-anchored re-hash + index-presence + extracted-cache walk. Adds a `refs fetch --repair` path so a single bad file no longer forces a full `rm -rf <release-dir>`.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth Artifacts — the strengthened skip check must still **refuse to overwrite** a healthy already-fetched dir. Repair semantics are limited to files that fail manifest verification; healthy files are immutable.
- **INV-R001** Derived Assistant Stores Must Stay Rebuildable — this work extends INV-R001's "input identity (path + content hash or version)" requirement to the reference-fetch layer. Once landed, every downstream pipeline step can join its provenance to a manifest sha256, not just a filename.
- **INV-P001** Privacy Is the Default Operating Mode — manifests record only public-data URLs and content hashes; no new egress, no PII.

## Proposed New Invariants

**None.** This plan implements an existing INV-R001 obligation at a layer that has so far ducked it.

## Current State Analysis

| Surface | Current behaviour | Gap |
|---|---|---|
| `refs fetch` MD5 verification | clinvar / dbsnp / grch38 verify against sidecars | gnomad-exomes / vep_cache / alphamissense / loftee / gnomad-constraint verify only Content-Length |
| `refs fetch` skip check (`INV-D001`) | `Path.exists()` on canonical filenames (or `presence_relpath` marker for vep_cache) | 0-byte files, bit-rot, manual tampering, partial multi-file fetches all pass |
| `refs verify` | bgzip-EOF on `.vcf.gz / .vcf.bgz / .bcf` | Ignores FASTA, BigWig, TSV, SQL, tarballs, vep_cache structure, sidecar presence |
| `refs fetch --repair` | does not exist | a single bad file forces full `rm -rf <release-dir>` and re-download |
| `host doctor` refs awareness | reports presence-of-release-dir | does not run integrity checks |

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | Skip check is `Path.exists()` loop (line 1104–1126); per-source `presence_relpath` field added 2026-05-13 | Write `manifest.json` post-fetch; replace skip-check with manifest predicate; per-file repair entry point; remove `presence_relpath` shim |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py` | `refs_verify` only checks bgzip EOF | Add manifest-hash recompute, sidecar presence, extracted-cache walk |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | `host doctor` is presence-aware only | Surface a "references verified" badge |
| `packages/toolkit/tests/integration/test_fetch_mocked.py` | Existence-only assertions | Manifest-shape and skip-predicate assertions |
| `packages/toolkit/tests/integration/test_cli_refs_verify.py` | Bgzip-EOF only | Manifest-recompute, sidecar, structural-cache cases |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/manifest.py` | Manifest read/write/verify primitives (single sha256 walker; schema-versioned JSON I/O) |
| `packages/toolkit/tests/unit/test_manifest.py` | Round-trip, schema, malformed-input behaviour |
| `packages/toolkit/tests/integration/test_refs_repair.py` | `refs fetch --repair` happy + edge paths |
| `packages/toolkit/tests/integration/test_refs_backfill_manifest.py` | Legacy-dir backfill flow |
| `docs/reference/refs-manifest.md` | Schema documentation; on-disk example |

## Solution Design

```text
reference/<source>/<release>/
├── <canonical files...>                ← unchanged on disk
├── <sidecars: .md5, .tbi, .fai, .gzi>  ← unchanged
└── manifest.json                       ← NEW, single source of truth
                                          for "fetched + verified"

manifest.json (v1):
{
  "schema_version": 1,
  "source": "loftee",
  "release": "v1.0",
  "fetched_at": "2026-05-13T19:00:00Z",
  "fetcher_version": "genomeclaw-toolkit-0.4.2",
  "files": [
    {
      "relpath": "human_ancestor.fa.gz",
      "bytes": 885231320,
      "sha256": "…",
      "source_url": "https://personal.broadinstitute.org/…/human_ancestor.fa.gz",
      "upstream_md5": null
    },
    {
      "relpath": "gerp_conservation_scores.homo_sapiens.GRCh38.bw",
      "bytes": 9600895779,
      "sha256": "…",
      "source_url": "https://ftp.ensembl.org/pub/release-115/…/gerp_….bw",
      "upstream_md5": null
    },
    ...
  ]
}
```

**Skip-check predicate** (replaces `Path.exists()` loop):

```text
manifest = read_manifest(release_dir)
if manifest is None:
    fall through to existing Path.exists() check (legacy-dir compatibility)
else:
    for f in manifest.files:
        if not (release_dir / f.relpath).exists(): re-fetch f only
        elif (release_dir / f.relpath).stat().st_size != f.bytes: re-fetch f only
        elif fast_hash(release_dir / f.relpath) != f.fast_hash: re-fetch f only
    if every file passed: raise VersionAlreadyExists
```

`fast_hash` = sha256 of first 64 KiB + last 64 KiB + total bytes. Catches truncation, manual edit, and most bit-rot without re-hashing multi-GB files on every `refs fetch --all`. Full sha256 stays the gold standard, run by `refs verify`.

### Key Design Decisions

1. **Single manifest per source-release** (not per-file). Easier to write atomically, easier for `refs verify` to walk, easier to back up.
2. **Schema-versioned JSON, not TOML / protobuf.** JSON is stdlib-readable, line-diffable, agent-readable. Schema version field guards future migrations.
3. **`fast_hash` for skip-check, `sha256` for verify.** Re-hashing the 12.6 GB GERP file on every `refs fetch --all` would defeat the purpose of "already fetched." First-and-last-64-KiB-plus-size is the cheap detector; `refs verify` is the strong one.
4. **No new invariant.** This is INV-R001 implemented at the right layer.
5. **Backfill is opt-in.** A legacy release dir without a manifest stays trusted (skip-check falls back to `Path.exists()`) until the user explicitly runs `refs verify --backfill-manifest`.
6. **Repair is per-file.** A bad sha256 on one of 48 gnomad-exomes files re-fetches just that one; the other 47 stay untouched. This is the killer feature that makes the system actually maintainable.

### Schema / Provenance Impact

- New schema: `manifest.json` v1 (see Solution Design).
- Schema-version field on the manifest itself; upward migrations are scripted under `prep/manifest.py`.
- Provenance columns: downstream tables (`materialize` outputs) gain an optional `reference_manifest_sha256` field that bind their annotation to a specific manifest hash. Not breaking — old rows have `NULL`.
- Rebuild procedure: `rm -rf reference/<source>/<release>/ && genomeclaw refs fetch --source <source> --release <release>` regenerates the manifest as a side effect. No separate manifest-build command.

### Privacy & Egress Impact

- No new network egress points. Manifests are local-only.
- No new secret-handling surfaces.
- No new redaction surface.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Manifest schema + write-on-fetch | round-trip, schema, atomicity | 6–8 |
| 2 | Manifest-anchored skip check (replaces `Path.exists()` loop) | predicate behaviour, legacy-dir fallback, fast_hash semantics | 6–8 |
| 3 | `refs verify` deep checks (sha256 recompute, sidecar presence, structural walks) | per-file pass/fail, vep_cache walk, sidecar-missing report | 8–10 |
| 4 | `refs fetch --repair` per-file re-fetch path | partial-file replacement, no full-dir wipe | 5–7 |
| 5 | Backfill + `host doctor` integration + docs | legacy-dir backfill flow, doctor badge, schema doc | 4–6 |

## Phase 1: Manifest Schema + Write-On-Fetch

**Goal**: Every successful `refs fetch --source X --release Y` writes a parseable `manifest.json` recording each canonical file's path, size, sha256, source URL, and upstream MD5.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `prep/manifest.py` — `Manifest` dataclass; `read_manifest()`, `write_manifest()`, `compute_file_record()`.
2. Modified `prep/fetch.py` — manifest write at end of source fetch, post `post_fetch` hook.

### Invariants Enforced Here
- **INV-R001**: every fetched source-release records content hashes, satisfying "input identity (path + content hash or version)" at the reference layer.

### Success Criteria
- [ ] Manifest round-trips (write → read → assert equal).
- [ ] sha256 in manifest matches `sha256sum` of the canonical file on disk.
- [ ] Manifest write is atomic (scratch + rename).
- [ ] Existing `test_fetch_mocked` + `test_cli_fetch_all` suites pass unchanged.

## Phase 2: Manifest-Anchored Skip Check

**Goal**: Replace [fetch.py:1104](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py#L1104) `Path.exists()` loop with a manifest-anchored predicate. Multi-file sources skip only when every file is intact.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. Modified `prep/fetch.py` — new skip predicate; legacy-dir fallback.
2. Removed `presence_relpath` shim from `_SourceLayout` (vep_cache manifest records `info.txt` directly).

### Invariants Enforced Here
- **INV-D001**: skip-check refuses to overwrite a verified release; tampered or partial dirs no longer trip the skip.

### Success Criteria
- [ ] 0-byte canonical file → re-fetch (not skip).
- [ ] manifest absent → fall through to legacy `Path.exists()` (compat).
- [ ] manifest present but one file missing → repair that file only (Phase 4 wires the actual repair; Phase 2 raises a "needs repair" error).
- [ ] manifest's `fast_hash` mismatch → repair the affected file.

## Phase 3: `refs verify` Deep Checks

**Goal**: `refs verify` recomputes sha256 against the manifest, asserts tabix/.fai/.gzi sidecar presence, and walks vep_cache for structural completeness.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. Expanded `_cli/commands/refs.py:refs_verify` — manifest-recompute path; sidecar audit; vep_cache walk.
2. New `RefsVerifyPayload` fields: per-file `sha256_match: bool`, `expected_sidecars_present: bool`, `structural_complete: bool`.

### Invariants Enforced Here
- **INV-R001**: verifies the recorded content hashes still match disk content.

### Success Criteria
- [ ] sha256 mismatch in any manifest file → exit 4 with structured failure.
- [ ] `.vcf.gz` without `.tbi` → reported.
- [ ] `.fa.gz` without `.fai` or `.gzi` → reported.
- [ ] vep_cache release dir missing `homo_sapiens/<N>_GRCh38/info.txt` → reported.

## Phase 4: `refs fetch --repair`

**Goal**: A single-bad-file scenario no longer requires `rm -rf <release-dir>`.
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables
1. New CLI flag `--repair` on `refs fetch`.
2. New code path in `prep/fetch.py` that, given a manifest + a list of failed-file relpaths, re-fetches and re-hashes those files only, then rewrites the manifest.

### Invariants Enforced Here
- **INV-D001**: repair touches only the files that fail verification; healthy files remain immutable.

### Success Criteria
- [ ] Healthy file + corrupted file in same release → repair leaves healthy file untouched (mtime preserved) and re-fetches the corrupted one.
- [ ] Repair updates manifest with new sha256 + fetched_at for the repaired file only.

## Phase 5: Backfill, `host doctor`, Docs

**Goal**: Legacy release dirs (fetched pre-this-feature) can opt in to manifest coverage; `host doctor` shows verify state; the manifest schema is documented.
**Detailed Plan**: [phases/phase-5.md](phases/phase-5.md)

### Deliverables
1. `refs verify --backfill-manifest` — walks release dir, hashes existing files, writes manifest using live `_LAYOUTS` URLs.
2. `host doctor` "references verified" badge (last-verified timestamp from each manifest).
3. `docs/reference/refs-manifest.md` — schema reference + on-disk example.

### Success Criteria
- [ ] Backfill respects `--yes` for non-interactive; prints planned manifest first.
- [ ] `host doctor` reports unverified, verified-stale (>30d), and verified-fresh per source.
- [ ] Docs cover schema versioning + migration guidance.

---

## Testing Strategy

### Unit Tests
- `tests/unit/test_manifest.py`: schema round-trip; malformed-JSON behaviour; sha256 streaming correctness; fast_hash determinism.

### Integration Tests
- `tests/integration/test_fetch_mocked.py`: extend existing tests; add manifest-write + manifest-skip cases.
- `tests/integration/test_cli_refs_verify.py`: add per-source manifest-recompute cases; sidecar audit; structural walks.
- `tests/integration/test_refs_repair.py`: new — per-file repair, no full-dir wipe.
- `tests/integration/test_refs_backfill_manifest.py`: new — legacy-dir backfill flow.

### Provenance Tests
- `tests/provenance/test_manifest_provenance.py`: every manifest file record has all required fields populated; schema_version present.

### Determinism Tests
- `tests/determinism/test_manifest_redo.py`: fetch the same fixture twice; sha256s match; only `fetched_at` differs.

### Privacy-Default Tests
- `tests/privacy/test_manifest_egress.py`: with default config, manifest write produces zero outbound network calls beyond the fetch itself.

### Invariant Tests
- `tests/invariants/test_invR001_refs_manifest.py`: walks every release-set source, asserts the manifest exists post-fetch and lists every layout file.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — no new ID; update INV-R001 "How to verify" to mention reference-manifest check.
- [ ] `docs/reference/refs-manifest.md` — new; schema + on-disk example + migration guidance.
- [ ] `docs/reference/architecture.md` — mention the manifest file in the "host-side reference data" layout section.
- [ ] Root [CLAUDE.md](../../../CLAUDE.md) — no change.
- [ ] `.claude/agents/bioinformatics-pipeline.md` — add manifest as a first-class artifact.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Pending | | | Manifest schema + write-on-fetch |
| Phase 2 | Pending | | | Manifest-anchored skip check |
| Phase 3 | Pending | | | `refs verify` deep checks |
| Phase 4 | Pending | | | `refs fetch --repair` |
| Phase 5 | Pending | | | Backfill + doctor integration + docs |

---

## Open Risks & Follow-ups

- **Hashing cost for large multi-file sources.** gnomad-exomes is ~200 GB. Even at 500 MB/s, full sha256 is ~400 s — too slow to run on every `refs fetch --all`. Mitigations: hash inline at fetch (free, since bytes are already streaming through `hashlib.md5` in `_stream_to_file`); use `fast_hash` for skip-check; restrict full-sha256 to explicit `refs verify` invocations.
- **Manifest race with concurrent `refs fetch`.** If a user runs `refs fetch --source X` twice in parallel (unintended), both might try to write the same manifest. Mitigation: atomic rename + per-release lock file in the same dir.
- **vep_cache structural walk surface area.** A complete walk of the extracted cache (~thousands of files) is expensive. Decision (carry into Phase 3): walk only top-level structural markers (`info.txt`, one per-chromosome `dna_index.txt`); fall back to "VEP itself will fail loudly if a leaf file is missing during the first invocation."
- **What happens to `refs verify --backfill-manifest` when the live `_LAYOUTS` URLs have changed since the legacy fetch?** (E.g., the user fetched LOFTEE GERP from Broad before the Ensembl re-routing.) The backfilled manifest records the current `_LAYOUTS` URL, which may not match what was actually fetched. Acceptable — the manifest is forward-looking; downstream consumers care about sha256 + presence, not URL provenance accuracy.

# Feature: Reference-Data Integrity Hardening

**Status**: Draft
**Created**: 2026-05-13
**Owner**: TBD
**Related Plans**: [docs/plans/active/mvp/](../mvp/) (this hardens infrastructure delivered by the MVP's Phase 4 refs work)

---

## Goal

Make `genomeclaw refs fetch`, the `INV-D001` "already fetched" skip check, and `genomeclaw refs verify` guarantee that on-disk reference data is byte-identical to a recorded upstream snapshot — not just "a file with the expected name exists."

## Background

The reference-fetch surface ships today with three distinct integrity gaps. Each is currently silent: a partially-downloaded, bit-rotten, or manually-tampered reference passes every check and gets used by the annotation pipeline without complaint.

**Gap 1 — Download-time validation is mode-mixed.** Three of eight sources (clinvar, dbsnp, grch38) verify a streaming MD5 against a published sidecar. The other five (gnomad-exomes, vep_cache, alphamissense, loftee, gnomad-constraint) verify only `Content-Length` parity + a bgzip-EOF marker where applicable. Content-Length is not a checksum — a transport that returned correct byte counts but wrong bytes (proxy corruption, range-stitch bugs, the LOFTEE Ensembl mirror swap we just shipped) passes silently.

**Gap 2 — Skip-detection (`INV-D001`) is `Path.exists()` only.** [fetch.py:1104-1126](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py#L1104) loops over the layout's canonical filenames and raises `VersionAlreadyExists` on first hit. Zero content validation. A 0-byte file from a full-disk crash, a bit-rotted FASTA, a partial multi-file gnomad-exomes fetch that completed chr1 but failed chr2-22, a `touch homo_sapiens/114_GRCh38/info.txt` from a confused operator — all skip cleanly. The `presence_relpath` marker added in commit-pending for vep_cache is structurally identical: existence-only, same class of guarantee.

**Gap 3 — `refs verify` covers one file class.** [refs.py:719](../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py#L719) runs a bgzip-EOF sweep over `.vcf.gz / .vcf.bgz / .bcf` files. It ignores FASTA (`.fa.gz`, `.fai`, `.gzi`), BigWig (`.bw`), TSV (`.tsv.gz`), SQL (`.sql.gz` / `.sql`), tarballs, vep_cache extracted directory structure, and the presence of tabix `.tbi` sidecars. The phrase "verify integrity" overpromises against what the command actually checks.

This plan closes all three gaps with a manifest-anchored design: every successful fetch writes a content-hash manifest; skip-detection becomes "manifest parses cleanly and lists files match disk"; `refs verify` recomputes hashes against the manifest. The manifest is also the durable evidence the project owner can hand a clinician asking "is this annotation actually ClinVar 2026-05-09" — the current answer is "the filename says so."

## Acceptance Criteria

Each maps to one or more tests under the phase plans.

- [ ] **AC1**: Every successful `refs fetch --source X` writes a `manifest.json` under `reference/<source>/<release>/` listing each canonical file's path, byte size, sha256, source URL, upstream-md5-if-known, fetched-at timestamp, fetcher version, and schema version.
- [ ] **AC2**: A second `refs fetch --source X --release Y` invocation raises `VersionAlreadyExists` iff the manifest parses, every listed file exists on disk at the recorded size, and (for the cheap check) every file's first/last 64 KiB hash matches the manifest. Disk-tampered or partial fetches do **not** trip the skip.
- [ ] **AC3**: `refs verify` recomputes sha256 of every canonical file listed in every present manifest and reports per-file pass/fail. The bgzip-EOF check stays as a structural cross-check.
- [ ] **AC4**: `refs verify` reports missing tabix sidecars (`*.vcf.gz` without `*.vcf.gz.tbi`), missing FASTA indexes (`*.fa.gz` without `*.fa.gz.fai` + `*.fa.gz.gzi`), and a structurally-incomplete `vep_cache/<release>/homo_sapiens/<N>_GRCh38/` tree.
- [ ] **AC5**: A new flag — `refs fetch --repair` or `refs verify --fix` — re-downloads exactly the files whose manifest hashes do not match, without requiring the user to `rm -rf` the entire release directory.
- [ ] **AC6**: For multi-file sources (gnomad-exomes, 48 files), the skip check is per-file against the manifest. A partial fetch that produced chr1 but not chr2 re-fetches chr2 on the next `--all` invocation rather than skipping the whole source.
- [ ] **AC7**: The `presence_relpath` shim added for vep_cache is removed; the manifest is the single source of truth for "already fetched." `vep_cache.tar.gz` may continue to be deleted post-extraction since the manifest records the extracted-cache file inventory instead.
- [ ] **AC8**: The verification gate that currently passes existence-only is reachable from `host doctor` so the project owner can run one command to confirm their refs state.

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth Artifacts — reference data is the analogous "source-of-truth" for the annotation pipeline. The plan strengthens the existing "refuse to overwrite" rule from filename-based to content-hash-based.
- **INV-R001** Derived Assistant Stores Must Stay Rebuildable — INV-R001 already requires "input identity (path + content hash or version)" on every pipeline step. This plan extends the same requirement to fetched references themselves, so that downstream provenance has a content hash to bind to rather than a filename.
- **INV-P001** Privacy Is the Default Operating Mode — manifests record only public-data URLs and content hashes; no PII surface, no new egress.

## Proposed New Invariants

**None new.** The work explicitly implements existing INV-R001 ("input identity (path + content hash or version)") at the reference-fetch layer, which has so far only enforced "path."

## Technical Requirements

### Source Data Inputs
- The current `_LAYOUTS` definitions in [packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py).
- Existing on-disk `reference/<source>/<release>/` directories (these need a one-shot manifest backfill via `refs verify --backfill-manifest`).

### Derived Outputs
- `reference/<source>/<release>/manifest.json` — one per source-release. Schema versioned.

### Schema / Migration Impact
- New schema: `manifest.json` v1. Fields: `schema_version`, `source`, `release`, `fetched_at`, `fetcher_version`, `files: [{relpath, bytes, sha256, source_url, upstream_md5_or_null}]`.
- Backward compatibility: an existing release dir without a manifest is "untrusted" — `refs verify --backfill-manifest` walks the dir, hashes existing files, and writes the manifest using the live `_LAYOUTS` URLs. The user opts in deliberately (no auto-backfill on first `refs fetch --all`).

### Pipeline / Workflow Impact
- `fetch()` adds a manifest-write step at end of source-fetch (post `post_fetch` hook).
- `fetch()` skip check switches to manifest-based predicate (with a structural fallback when no manifest exists, preserving INV-D001 for legacy dirs).
- `refs verify` grows hash-recompute + index-presence + extracted-cache walks.
- A new `refs fetch --repair` subcommand path.

### Agent / UX Impact
- `host doctor` surfaces a "references verified" badge.
- `refs fetch --all` output gains a "verifying manifest…" line after each source completes. Single-file sources see no observable change.

### External Dependencies
- None new. `hashlib.sha256` is stdlib; no new pinned binaries.

## Privacy & Safety Considerations

- **Boundary scan**: Manifests live alongside the data they describe — no new egress, no telemetry, no remote registry. The user's reference root stays self-contained.
- **Default-off remote calls**: None added. The manifest schema records the *source URL* it was fetched from, not anything user-identifying.
- **Redaction surface**: Not applicable — manifests are public-data metadata.
- **Clinical escalation**: Indirect — a stronger integrity guarantee makes findings derived from these references more defensible when the project owner forwards them to a clinician. Stronger evidence, not new clinical claims.

## Out of Scope

- **Cross-source consistency checks** (e.g., "gnomAD release version matches what the VEP cache references"). That's a separate semantic-consistency concern.
- **Mirror promotion / pinning** (e.g., the LOFTEE Broad-vs-Ensembl decision). Stays a deliberate per-file routing in `_LAYOUTS`.
- **Continuous re-verification** (cron, file-watcher). The model is "verify on user request or before a pipeline run" — opt-in, not background.
- **Hash-chained, signed manifests.** A single sha256 per file is sufficient for the personal-host single-user threat model. No notary, no blockchain, no remote attestation.

## Dependencies

- MVP Phase 4 refs work (currently active) must land first — manifests are written for the eight layouts that exist post-Phase 4.

## Open Questions

- [ ] **Q1**: When a source has no published upstream MD5 (gnomad-exomes, vep_cache, alphamissense, loftee, gnomad-constraint), the manifest's `upstream_md5` is null and the local sha256 is the only integrity anchor. Is that sufficient, or should the plan add a post-download-hash-vs-second-fetch consistency check? Recommendation: ship without, revisit if a real corruption event happens.
- [ ] **Q2**: For `vep_cache`, the manifest currently would record only `vep_cache.tar.gz` — which the post-fetch hook deletes. Should it instead record the extracted file inventory (~thousands of files)? Or a representative subset (info.txt + one per-chromosome dna_index.txt)? Recommendation: representative subset; full inventory is excessive for a multi-GB cache.
- [ ] **Q3**: `refs verify --backfill-manifest` — should it require the user to explicitly confirm the source URLs match? A legacy dir might be the wrong release. Recommendation: yes, print the planned manifest and require `--yes` or interactive confirm.
- [ ] **Q4**: Should `refs fetch --repair` re-download via the same URL the manifest recorded, or via the live `_LAYOUTS` URL (which may have changed mirror, like the LOFTEE GERP)? Recommendation: live `_LAYOUTS` URL; record the new mirror in the regenerated manifest. The original URL is recorded historically in `work-notes.md` of the plan that changed it.

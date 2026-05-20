# Annotate-Shard Resilience — Development Plan

**Status**: Closed partial — 2026-05-19. **Phase A code shipped 2026-05-14** (split-scratch: `ephemeral_scratch_base()` + `/tmp/genomeclaw-scratch/` tmpfs routing for vcfanno / VEP / materialize shards; persistent caches stay on `/mnt/genomeclaw/scratch/_cache/`). Phase A's real-data smoke gate (< 4h annotate wall, no EBADF on the project owner's Nebula VCF) **was never run** before closure. Phases B (per-shard vcfanno output caching), C (`--skip-if-present` / `--skip <phase>` resume flags), and D (virtiofs-detection tripwire) remain unstarted. The shipped split-scratch design has held empirically in test suites; the smoke remains an open verification debt. **Doc reconciliation on closure**: the `ephemeral_scratch_base()` seam was subsequently documented under [`INV-D006`](../../../reference/INVARIANTS.md#inv-d006-dood-safe-path-annotation) by the active `path-crossing-discipline` plan, which is the primary canonical reference now. INV-D003's wording still says "intermediates write to `/mnt/genomeclaw/scratch`" — technically narrowed by Phase A's tmpfs routing for shard intermediates, but the *separation* principle INV-D003 enforces survives, and INV-D006 captures the seam. No urgent INV-D003 update required. The `--skip-if-present` and per-shard-cache items in [mvp/phases/phase-4-completion.md](../mvp/phases/phase-4-completion.md) stay parked — they remain valid future work; their closure here doesn't kill them. **If Phase A's smoke later fires EBADF or wall-clock cliffs**, promote Phases A.1 (cram-scratch-strategy Option B lima `additionalDisks`) + B + C back from this file unchanged.
**Created**: 2026-05-14
**Closed**: 2026-05-19 (Phase A shipped, smoke deferred; B/C/D abandoned)
**Branch**: not yet cut
**Spec**: [spec.md](spec.md) — TODO once outline approved
**Parent context**: triggered by the 2026-05-14 real-data smoke failure documented at the bottom of [docs/plans/active/mvp/phases/phase-4-completion.md](../mvp/phases/phase-4-completion.md). Closes one of the [cram-scratch-strategy plan's Phase-4+ tripwires](../../completed/cram-scratch-strategy/) ("vcfanno-class deadlock / EIO under load on virtiofs").

---

## Summary

The 2026-05-14 `genomeclaw pipeline run` against the project owner's real Nebula VCF crashed at ~1h18m into the annotate phase: one of four concurrent vcfanno subprocesses panicked with `bix: error (re)opening clinvar.renamed.vcf.gz: bad file descriptor` followed by `panic: runtime error: index out of range [-1]` inside vcfanno's Go runtime. The 25 successfully-finished per-chrom shards' outputs were thrown away on scratch cleanup. The single-threaded workaround (`GENOMECLAW_ANNOTATE_WORKERS=1`) is rejected as too slow (~6–8h wall on annotate alone).

This plan ships three independently-shippable phases that together (a) make the next smoke run reliable within the < 4h annotate budget, (b) make per-shard work survive a transient failure, and (c) let users resume from any phase whose output is on disk.

A deferred Phase D adds observability tripwires; not on the critical path.

## Critical Invariants to Respect

- **`INV-D001`** Raw genomic files source-of-truth — unchanged. Reference + raw paths stay read-only regardless of where ephemeral scratch lives.
- **`INV-D003`** Heavy scratch separated from authoritative outputs — *strengthened*. We're doubling down on this invariant by giving ephemeral and persistent scratch separate physical locations.
- **`INV-R001`** Rebuildability — *extended*. Per-shard cache hits must be provenance-recorded; resume flags must not silently skip phases without that being visible in the run's provenance.

## Proposed New Invariants

None. The work strengthens existing invariants rather than proposing new ones.

## Current State Analysis

### What's broken (2026-05-14 smoke)

1. **vcfanno crashes on concurrent-FD access to virtiofs-mounted scratch.** Confirmed root-cause class per the cram-scratch-strategy plan's documented tripwires. The proximate error is `EBADF` (bad file descriptor) inside vcfanno's bix tabix library while four shards concurrently re-open the same staged ClinVar file under load.
2. **`shard_scratch` purges everything on context exit.** When one shard panics, the 25 completed shards' per-chrom outputs are deleted before the orchestrator can reuse them.
3. **No phase-level resume.** `pipeline run` re-does every phase on every invocation. A failure at annotate forces re-running ingest + normalize even though their outputs are on disk.

### What works

- 4-mount canonical layout (`raw / reference / derived / scratch`) is intact.
- Persistent dbSNP rename cache + per-source sha256 cache at `_scratch/_cache/` survive across runs.
- Per-chrom shard pattern itself is sound — `bcftools concat --naive` stitches uniform-header shards in seconds.
- All Phase-4D code is shipped; the only gap is reliability + resumption.

### What we know about the EBADF

- The error is `bix: error (re)opening … bad file descriptor` from a goroutine inside one vcfanno subprocess. The file path is on `/mnt/genomeclaw/scratch/` — virtiofs-mounted from the macOS host through colima.
- The `cram-scratch-strategy` plan called out exactly this scenario as a documented escalation condition.
- We don't have positive proof that virtiofs is the only cause (could be a vcfanno-internal race surfacing only under FS-pressure), but it's the most likely class.

## Solution Design

### The split-scratch architecture

Today scratch is a single bind-mount: `host:/Volumes/Genome_Work/genomeclaw/_scratch ↔ container:/mnt/genomeclaw/scratch`. Every transient + persistent scratch artifact lives there, traversed via virtiofs.

The plan splits scratch into two tiers with different lifetimes + filesystem requirements:

| Tier | Path (container) | Filesystem | Lifetime | Used for |
|------|------------------|------------|----------|----------|
| **Persistent scratch** | `/mnt/genomeclaw/scratch/_cache/` (unchanged) | virtiofs (current) | across runs | dbSNP rename cache, sha256 cache, **new**: per-shard vcfanno outputs |
| **Ephemeral scratch** | `/tmp/genomeclaw/` (new) | tmpfs or VM-local ext4 (NOT virtiofs) | per-step | shard_scratch dirs — clinvar.renamed.vcf.gz staging, vcfanno intermediates, VEP intermediates |

Concurrent-FD pressure happens on the ephemeral path (vcfanno re-opening staged sources mid-run). Routing that off virtiofs eliminates the EBADF class. Persistent caches keep their virtiofs-mounted home so the user can `ls /Volumes/Genome_Work/genomeclaw/_scratch/_cache/` to inspect them.

### Per-shard cache as a first-class artifact

Today shard outputs live under `_scratch/<step>-<run-id>/annotated_by_chrom/<chrom>.vcf.gz` and die with the shard_scratch context. Phase B promotes them to `_scratch/_cache/annotate-vcfanno/<inputs_sha>/<chrom>.vcf.gz`, keyed on a sha that invalidates whenever the inputs, the rename map, or the vcfanno config drift.

This makes "transient failure costs hours" no longer true: a retry hits the cache for completed shards and only re-runs the failed ones. Combined with Phase C's `--skip-if-present`, retries are fast.

### `--skip-if-present` CLI surface

Per the [earlier parked design](../mvp/phases/phase-4-completion.md):

```bash
bin/genomeclaw pipeline run --skip-if-present
bin/genomeclaw pipeline run --skip vcfanno --skip vep
bin/genomeclaw pipeline annotate --skip vcfanno   # standalone-subcommand resumption
```

Per-phase detection signals: `manifest.json` (ingest), `normalized.vcf.gz` (normalize), `vcfanno.vcf.gz` (vcfanno step), `vep.vcf.gz` (vep step), populated `variants.duckdb` on current schema (materialize).

### What we explicitly do not do

- We don't reach for the cram-scratch-strategy "Option B" (lima `additionalDisks` block-device passthrough) yet. Phase A's lighter-weight split-scratch approach is sufficient if it eliminates the EBADF, which it should. Option B is the documented next escalation if Phase A's smoke still fires the tripwire.
- We don't lower vcfanno's internal goroutine count. Phase A targets the FS-layer cause, not the in-process race (if it's that).
- We don't add a virtiofs-detection tripwire on the critical path. That's the deferred Phase D — useful but not blocking.

## Phase Overview

| Phase | Description | TDD Focus | Est. work | Real-data gate |
|-------|-------------|-----------|-----------|----------------|
| **A** | Split-scratch: route ephemeral shard scratch to non-virtiofs path | scratch primitives + orchestrator wiring | ~3–4h active + 1 real-data smoke (~3–5h compute) | full `pipeline run` completes under 4h annotate budget |
| **B** | Per-shard vcfanno output caching | cache key invariance, hit/miss correctness, INV-R001 cache provenance | ~4–6h active + 1 real-data smoke | second-attempt-after-mid-flight-failure reuses 25/26 completed shards |
| **C** | `--skip-if-present` + `--skip` resume flags | CLI wiring + per-phase detection signals | ~1–2h active | re-running `pipeline run --skip-if-present` after a completed run is a no-op |
| **D** *(deferred)* | Virtiofs-detection tripwire + worker-count auto-tune | preflight observability | ~2h active | optional; ships if a future smoke fires the tripwire |

Phases A–C are the critical path. Phase D is filed as a parked enhancement; promote if needed.

Total active time A–C: ~8–12 hours across 4-ish focused sessions; real-data smokes are run-and-wait.

---

## Phase A — Split-scratch: ephemeral path off virtiofs

**Goal**: every orchestrator's `shard_scratch(...)` call writes to a container path that is **not** virtiofs-mounted. Persistent caches stay on `/mnt/genomeclaw/scratch/_cache/`. Default real-data smoke completes the annotate phase under the 4h wall budget.

### Design

- New env var `GENOMECLAW_EPHEMERAL_SCRATCH_DIR` with default `/tmp/genomeclaw-scratch/`.
- Container image declares `/tmp/genomeclaw-scratch/` as a `tmpfs` mount (or `--tmpfs /tmp/genomeclaw-scratch:size=16G` via the shim) so writes go to the VM's RAM-backed tmpfs, not virtiofs.
- `shard_scratch(...)` orchestrator callers compute `base=` from this env var.
- Persistent cache paths (`_scratch/_cache/dbsnp/`, `_scratch/_cache/sha256/`) **stay where they are** — they need to survive across runs and never hit the concurrent-FD pressure.

### Files

- `prep/scratch.py` — currently defaults `base=_SCRATCH_BASE = /mnt/genomeclaw/scratch`. Add a sibling `_EPHEMERAL_BASE` reading from env.
- `prep/annotate_vcfanno.py` — switch `shard_scratch(...)` call to `base=ephemeral_scratch_base()`.
- `prep/annotate_vep.py` — same.
- `prep/materialize.py` — same (its shard_scratch is short-lived too).
- `bin/genomeclaw` shim — `--tmpfs /tmp/genomeclaw-scratch:size=16G` or similar so the path exists with capacity.
- `packages/toolkit/Dockerfile` — declare the tmpfs mountpoint if shipping it via Dockerfile instead of shim.

### TDD

- **Unit**: `shard_scratch(..., base=Path("/some/path"))` writes under that path. (Already covered.)
- **Unit**: a new helper `ephemeral_scratch_base()` resolves from env var → default. Test env-var override + default + invalid-path fallback behavior.
- **Integration**: orchestrator runs end-to-end with `GENOMECLAW_EPHEMERAL_SCRATCH_DIR` pointed at `tmp_path` (not the canonical /tmp); assert shard intermediates land there + persistent caches at the unchanged location.

### Real-data gate

```bash
bin/genomeclaw pipeline run  # default workers=4, default scratch split
```

Pass: completes within 4h annotate budget; no EBADF in stderr.

---

## Phase B — Per-shard vcfanno output caching

**Goal**: a mid-flight annotate failure preserves all completed per-chrom shards. A retry reuses them; only the failed shard re-runs.

### Design

- Cache layout: `<persistent_scratch>/_cache/annotate-vcfanno/<inputs_sha>/<chrom>.vcf.gz` + `.tbi`.
- Cache key = sha256 of:
  - `normalized_vcf_sha`
  - sorted list of overlay source sha256s (`clinvar`, `gnomad-exomes` per-chrom, `dbsnp`)
  - the inline vcfanno TOML config (so a config change invalidates)
- Per-shard flow:
  1. Compute the cache key for this shard (uses the gnomAD chrom-specific source).
  2. If `<cache_dir>/<chrom>.vcf.gz` + `.tbi` both exist → copy to scratch's `annotated_by_chrom/<chrom>.vcf.gz`; record cache hit in provenance.
  3. Otherwise run vcfanno + copy result into the cache + scratch.
- Provenance: the vcfanno step's `params.shard_cache` dict records `{chrom: "hit" | "computed"}` per shard.

### TDD

- **Unit**: cache-key computation is stable across runs with identical inputs; changes when any input drifts.
- **Integration**: stage a known-good cached output; run annotate_vcfanno; assert vcfanno was not invoked for the cached shard.
- **Integration**: mock one shard to fail mid-run; verify the other 25 shards' outputs land in the cache; retry the same annotate call and verify the failed shard is the only one that re-runs vcfanno.
- **INV-R001**: provenance records the cache hit/miss per shard.

### Real-data gate

Replay the 2026-05-14 failure scenario:
1. Run `pipeline run` to completion (Phase A makes it succeed).
2. Manually delete one cached chrom (simulate corruption).
3. Re-run `pipeline annotate`; verify only the deleted chrom re-runs vcfanno; the other 25 are reused; total wall < 5 min.

---

## Phase C — `--skip-if-present` + `--skip <phase>` resume flags

**Goal**: re-running `pipeline run` after a partial completion is a no-op for phases whose outputs are on disk.

### Design

- New flag `--skip-if-present` (no arg): orchestrator inspects per-phase detection signals; skips phases whose output exists.
- New flag `--skip <phase>` (repeatable / comma-separable): unconditionally skips the named phase regardless of detection.
- Detection signals:
  - **ingest**: `manifest.json` present + valid.
  - **normalize**: `normalized.vcf.gz` present + tabix index.
  - **annotate-vcfanno**: `vcfanno.vcf.gz` present + tabix index. (Phase B's per-shard cache is a separate layer.)
  - **annotate-vep**: `vep.vcf.gz` present + tabix index.
  - **materialize**: `variants.duckdb` exists + `schema_meta.schema_version == current`.
- Both flags work on standalone subcommands (`pipeline annotate --skip vcfanno`).
- Provenance: skipped phases get a step recorded as `{step: "...", skipped: "reason"}` so the trail isn't silently truncated.

### TDD

- **CLI**: `--skip-if-present` flag flows through to each `*_impl` as a kwarg.
- **CLI**: `--skip vcfanno` works on `pipeline annotate` (the standalone subcommand path).
- **Integration**: stage a run dir with normalized.vcf.gz + vcfanno.vcf.gz already present; invoke `pipeline run --skip-if-present`; assert only annotate-vep + materialize ran.
- **INV-R001**: skipped phases visible in `provenance.json`.

### Real-data gate

After a full successful run, re-invoking `pipeline run --skip-if-present` is a no-op (completes in seconds).

---

## Phase D *(deferred)* — Virtiofs-detection tripwire

Filed as a parked enhancement. Promote if a future smoke fires the tripwire despite Phase A.

Scope sketch:
- `preflight.detect_filesystem_type(path)` helper using `stat -f` or `findmnt`.
- annotate_vcfanno checks at orchestrator entry; if scratch is on virtiofs/9P, log a warning and (optionally) auto-clamp `GENOMECLAW_ANNOTATE_WORKERS` to 1.
- Skipped under Phase A by default because ephemeral scratch is off virtiofs.

---

## Testing Strategy

Per-phase test commitments above. Cross-cutting:

- **Determinism**: rerunning `pipeline run` against the same inputs after Phase A + Phase B produces row-equivalent `variants.duckdb` (the existing INV-R001 determinism contract carries forward — no new shape).
- **Privacy default**: no new egress surface; Phase A's ephemeral scratch is container-local.
- **Provenance**: every cache hit + skipped phase is recorded in `provenance.json`.

## Documentation Updates

- `docs/reference/architecture.md` — note the split-scratch tier in the storage section.
- `docs/reference/INVARIANTS.md` — `INV-D003` "Where it applies" gains the ephemeral/persistent tier distinction.
- `docs/plans/active/mvp/phases/phase-4-completion.md` — link to this plan from the 2026-05-14 follow-up entry; tick the parked items when their corresponding phases land.

## Open Risks

- **Phase A might not fully fix EBADF.** Mitigation: the real-data smoke at Phase-A close is the gate. If EBADF persists, the cram-scratch-strategy Option B (lima `additionalDisks`) becomes Phase A.1; doesn't invalidate Phases B + C.
- **Tmpfs sizing.** A 16 GB tmpfs is generous for vcfanno intermediates (~5 GB) but tight for VEP's intermediate VCF on a 30× WGS (could be 10–15 GB). Phase A includes sizing validation against the real-data smoke.
- **Cache invalidation drift.** Phase B's cache key includes the inline TOML config; a refactor that changes the TOML emission (whitespace, ordering) would invalidate caches. Mitigation: sort + canonicalize the TOML before hashing.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase A | **Code shipped 2026-05-14; real-data smoke gate pending** | 2026-05-14 | (code) 2026-05-14 | New `ephemeral_scratch_base()` in `prep/scratch.py`; threaded through `annotate_vcfanno`, `annotate_vep`, `materialize`. `genomeclaw_layout` fixture now provisions a `ephemeral_scratch` sibling + sets `GENOMECLAW_EPHEMERAL_SCRATCH_DIR`. Persistent caches (`_cache/dbsnp/`, `_cache/sha256/`) remain on the bind-mounted `/mnt/genomeclaw/scratch/`. Default ephemeral base: `/tmp/genomeclaw-scratch/` (container-local, off virtiofs). 3 unit tests + 4 integration tests; host 467 pass / 72 needs_bio skipped; in-image 50/50 on the adjacency suite. **Open**: full real-data `pipeline run` against the project owner's Nebula VCF; gate is < 4h annotate wall + no EBADF in stderr. |
| Phase B | Pending | | | |
| Phase C | Pending | | | |
| Phase D | Deferred | | | Promote if Phase A's smoke fires the virtiofs tripwire. |

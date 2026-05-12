# CRAM Scratch Strategy — Development Plan

**Status**: Draft
**Created**: 2026-05-09
**Branch**: `feature/cram-scratch-strategy`
**Spec**: [spec.md](spec.md)
**Design**: [docs/reports/cram-scratch-strategy.md](../../reports/cram-scratch-strategy.md)
**Supersedes**: [docs/plans/active/storage-scratch-layout/](../storage-scratch-layout/)

---

## Summary

Implements the chosen design from `docs/reports/cram-scratch-strategy.md`: an interactive `genomeclaw-prep setup` subcommand that repartitions the user's external drive (APFS for processing, optional exFAT for interop), creates a 300 GB ext4 block-attached scratch image exposed to the colima VM via lima `additionalDisks`, mounts source-of-truth dirs read-only via virtiofs, and migrates the existing `annotate` / `materialize` orchestrators off the Phase-4A `/tmp` workaround onto the new scratch tier. Lands the pipeline primitives (`shard_scratch`, `atomic_promote`, pre-flight assertions) that MVP Phase 5+ (CRAM → VCF) depends on, but stops short of any actual variant-calling integration.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the *one* destructive moment is the user-confirmed `move` during setup, performed before the runtime mount discipline is in effect. Once setup completes, `raw/` is virtiofs RO inside the container; no orchestrator can write to it. Setup-time provenance (source path, destination path, file SHAs) is captured in `_scratch/setup.log`.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — scratch is a host-side VM disk, accessed only by the toolkit container, never by the OpenShell sandbox. This plan adds zero new paths from the agent boundary.
- **INV-P001** Privacy Default — the entire setup flow is offline. No new egress paths. `genomeclaw-prep fetch …` (the only optional egress, unchanged here) remains gated.
- **INV-R001** Rebuildability — pre-flight scratch assertions, atomic promotion to `derived/`, and ext4 journaling preserve "rerun against the same inputs and tools yields byte-equivalent outputs." Per-row provenance columns and per-run `manifest.json` / `provenance.json` are unchanged.
- **INV-C001** Separate Research Assistance from Clinical Advice — confirmation-prompt copy and any user-facing error message is reviewed by `privacy-safety-reviewer` before merge. Not a heavy surface here, but the destructive-operation copy must not overclaim ("safely guarantees …") nor over-defer ("consult your clinician before partitioning your USB drive").

## Proposed New Invariants

- **NEW INV-D003 — Heavy Scratch Is Separated From Authoritative Outputs.** Pipeline steps generating > 1 GB of intermediates write under `/mnt/genomeclaw/scratch/` (or its current mount); final validated outputs are atomically promoted to `/mnt/genomeclaw/derived/<run-id>/`. The original Phase-2 framing ("block-attached, not virtiofs") was tied to a specific implementation (lima `additionalDisks`) that turned out to be unimplementable on colima 0.9.1 — see [docs/reports/cram-scratch-strategy.md](../../reports/cram-scratch-strategy.md) § Post-implementation discovery. The underlying separation-of-concerns rule is still valid; the mechanism (block-attached vs virtiofs-on-APFS) is implementation detail. Verified by integration tests that observe write targets during a real-data run, plus a lint guard against new code paths writing > 1 GB to `/mnt/genomeclaw/derived/<run-id>/` outside an allowlist of final artifacts (final VCF, manifest, provenance, post-promotion DuckDB store). Promoted to `INVARIANTS.md` after Phase 6 ships.

## Current State Analysis

### What exists today (post-Phase-4A)

- `bin/genomeclaw-prep` — the host shim. Has subcommand-aware mount logic (`fetch` writes to `reference/`, everything else mounts it RO). Defaults `GENOMECLAW_WORK_DIR` to `$HOME/.genomeclaw/work`. Mounts four virtiofs binds: `raw` RO, `reference` RO/RW (per subcommand), `derived` RW, `work` RW.
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` — uses `tempfile.TemporaryDirectory(dir="/tmp")` for staging. Calls `bcftools annotate` (vcfanno was removed in Phase 4A after deadlock).
- `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` — uses `tempfile.TemporaryDirectory(dir="/tmp")` for DuckDB CSV staging. Drops + recreates `variants` table on each call.
- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — accepts a `work_dir` parameter, stages CSVs there for DuckDB COPY FROM, sets `PRAGMA temp_directory=<work_dir>`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` — computes `work_dir = derived_root.parent / "work"` (broken on macOS Sequoia per Phase-4A findings; the existing successful Nebula ingest predates the issue surfacing).
- `docs/reference/user-stories.md` Story 1 Step 0 — describes the manual four-mount discipline.
- `docs/plans/active/storage-scratch-layout/` — the earlier plan that defined the four-mount discipline. Now superseded.

### What's missing

- An interactive setup CLI that the user can run once.
- Disk / volume detection, same-device verification, partition / format machinery.
- Block-attached scratch lifecycle (mkfs.ext4, mount discipline, smoke test).
- Pre-flight assertion library.
- Pipeline primitives (`shard_scratch`, `atomic_promote`, mid-run scratch monitoring).
- The `eject` and `doctor` subcommands.
- Updated user stories + README.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `bin/genomeclaw-prep` | Defaults `GENOMECLAW_WORK_DIR=$HOME/.genomeclaw/work`; mounts four virtiofs binds; subcommand-aware reference RW only on `fetch`. | Replace `work` mount with block-device `additionalDisks` reference; add `setup`, `eject`, `doctor` subcommand routing; rename `GENOMECLAW_WORK_DIR` → `GENOMECLAW_SCRATCH_DIR`; emit a deprecation warning for the old env var for one release. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` | Stages on `/tmp` via `tempfile.TemporaryDirectory(dir="/tmp")`. | Stage on `/mnt/genomeclaw/scratch/annotate-<run-id>/` via the new `shard_scratch` helper. Promote outputs via `atomic_promote`. Add pre-flight assertions. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` | Stages on `/tmp`. | Same migration as `annotate.py`. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | Accepts `work_dir` param; stages CSVs there. | Accept `scratch_dir` (renamed); honor caller-supplied path; no behavior change to staging logic itself. Old `work_dir` keyword aliased to `scratch_dir` for one release. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` | Computes `derived_root.parent / "work"`. | Replace with `/mnt/genomeclaw/scratch/ingest-<run-id>/` resolved via the new pipeline primitives. |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | Has `fetch`, `ingest`, `normalize`, `annotate`, `materialize` subcommands. | Add `setup`, `eject`, `doctor` subcommands. |
| `docs/reference/user-stories.md` | Story 1 Step 0 describes the manual four-mount flow. | Rewrite Step 0 to describe `genomeclaw-prep setup`. Keep the rest of Story 1 (Steps 1–4+) intact except for env-var renames. |
| `README.md` | "Storage planning" section describes the manual flow. | Rewrite to describe `genomeclaw-prep setup`; cross-reference `docs/reports/cram-scratch-strategy.md` for the architecture rationale. |
| `docs/reference/architecture.md` | "Host-side packaging" section describes the four-mount discipline. | Update mount table to reflect (raw, reference, derived, scratch); cite `INV-D003`. |
| `docs/reference/INVARIANTS.md` | Currently at v1.5. | Add `INV-D003` after Phase 6 ships; bump to v1.6. |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` | Package marker. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/detect.py` | Volume / disk / Nebula-deliverable detection. macOS-first; abstracted around a `Platform` interface to allow future Linux. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/dryrun.py` | Renders a complete dry-run preview from a `SetupPlan` dataclass. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/execute.py` | Executes a confirmed `SetupPlan`: partitions, formats, moves data, writes `scratch.raw`, edits colima/lima YAML, restarts colima. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/audit.py` | Writes `_scratch/setup.log` with timestamps, paths, file SHAs, partition diff. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/preflight.py` | The pre-flight assertion library. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py` | `shard_scratch(step, shard_id)` context manager + `atomic_promote(scratch_path, derived_path)` + mid-run scratch monitor. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/eject.py` | The `eject` subcommand implementation. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | The `doctor` subcommand implementation. |
| `packages/toolkit/tests/integration/test_setup_dryrun.py` | Dry-run preview against a fake `Platform` shows the expected SetupPlan. |
| `packages/toolkit/tests/integration/test_setup_execute.py` | Confirmed plan executes against a sparse-image-on-tmpfs test rig. **No real partitions** — uses a loop-mounted disk image inside the test runner. |
| `packages/toolkit/tests/integration/test_preflight.py` | Each assertion fails for the right reason and passes when satisfied. |
| `packages/toolkit/tests/integration/test_scratch_helpers.py` | `shard_scratch` purges on exit (including on exception); `atomic_promote` is atomic within a filesystem and crash-safe. |
| `packages/toolkit/tests/integration/test_eject.py` | Eject stops colima before `diskutil eject`; refuses to eject if a pipeline is mid-run. |
| `packages/toolkit/tests/integration/test_doctor.py` | Doctor reports specific, actionable failures in a misconfigured environment. |
| `packages/toolkit/tests/invariants/test_invD003_scratch_discipline.py` | Walks a recorded run's I/O log and asserts no > 1 GB write target lives under `/mnt/genomeclaw/derived/`. |
| `docs/plans/active/cram-scratch-strategy/phases/phase-1.md` ... `phase-6.md` | Phase plans (this document creates them as work begins). |

### Files to Delete

| File | Reason |
|------|--------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_work_dir.py` (if present) | Old `work_dir` resolution helper; replaced by `prep/scratch.py`. |
| `docs/plans/active/storage-scratch-layout/` | Moved to `completed/` with a closing note pointing here. |

## Solution Design

### Data flow at runtime (post-implementation)

Validated target hardware: **Samsung T7 Shield 2 TB (USB-C)**. Architecture is drive-model-agnostic; the SKU sets the throughput tier and seeds the firmware-revision known-bad list (currently empty for this model — see spec § AC3, `docs/reports/cram-scratch-strategy.md` § External Drive Topology).

```text
                ┌──────────────────────────────────────────────────┐
host            │ /Volumes/Genome_Work/  (APFS, 2 TB external SSD) │
                │   genomeclaw/                                    │
                │     raw/<sample>/        ─┐                      │
                │     reference/<src>/<rel>/─┐                     │
                │     derived/<run-id>/      │                     │
                │     _scratch/              │                     │
                │       scratch.raw  ─── 300 GB sparse, ext4 ───┐  │
                │       setup.log               │              │  │
                └────────────────────────────────┼─────────────┼──┘
                                                 │             │
                                            virtiofs       virtio-blk
                                                 │             │
                ┌────────────────────────────────┼─────────────┼──┐
colima VM       │ /mnt/genomeclaw/                              │ │
                │   raw/                  ── virtiofs RO  ──────┘ │
                │   reference/            ── virtiofs RO          │
                │   derived/              ── virtiofs RW (small)  │
                │   scratch/              ── ext4 RW   ───────────┘
                └──────────────────────────────────────────────────┘
                                      │
                   pipelines read from raw/+reference/, write
                   heavy intermediates to scratch/, atomically
                   promote final artifacts to derived/.
```

### Setup flow

```text
genomeclaw-prep setup
        │
        ▼
 detect mounted volumes (diskutil list -plist)
        │
        ▼
 prompt: "where is your Nebula deliverable?"
        │
        ▼
 validate Nebula shape (bcftools view -h, file size sanity)
        │
        ▼
 prompt: "select target external drive (cannot be the same physical disk)"
        │
        ▼
 detect parent-disk identity of source vs. target; fail if same
        │
        ▼
 detect existing layout on target → adopt-or-reformat branch (Q2)
        │
        ▼
 render dry-run: partition diff, files moved, files created, YAML diffs
        │
        ▼
 require typed confirmation phrase: "WIPE /Volumes/<name>"
        │
        ▼
 execute (the destructive piece):
   1. write _scratch/setup.log with pre-state SHAs
   2. diskutil partitionDisk: APFS Genome_Work [+ optional exFAT Genome_Bulk]
   3. mkdir genomeclaw/{raw,reference,derived,_scratch}/
   4. mv Nebula deliverable → genomeclaw/raw/<sample>/
   5. truncate -s 300G _scratch/scratch.raw
   6. write ~/.colima/default/colima.yaml (3 virtiofs mounts)
   7. write lima additionalDisks config
   8. colima stop && colima start
   9. inside VM: blkid; mkfs.ext4 -L genomeclaw-scratch; mount; smoke test
        │
        ▼
 print summary: "setup complete — scratch 300 GB, derived 1.4 TB free"
```

### Key Design Decisions

1. **Block-attached ext4 for scratch, not virtiofs.** Per `docs/reports/cram-scratch-strategy.md`: virtiofs's FUSE-message protocol serializes per-share and produces async deadlocks under bioinformatics-tool I/O patterns. Block-attached gives Linux native semantics — proper `fsync` ordering, atomic rename within the same FS, ext4 journaling. Cost: an opaque `scratch.raw` blob the user cannot inspect from the host.
2. **APFS, not exFAT, for the source-of-truth tier.** exFAT lacks fine-grained POSIX locking; macOS VFS falls back to coarse volume-level locks under concurrent multi-threaded I/O, which is the trigger for failure mode #3 from Phase 4A. APFS handles this natively.
3. **Move, not copy, for the Nebula deliverable.** The target drive is being repartitioned; the user has explicitly opted in. Copying would require the user to have ≥ Nebula-deliverable-size of free space *on a third drive*, which is unrealistic. Setup audit log is written before the move so a partial-failure recovery is possible.
4. **Typed confirmation phrase, not just `y/N`.** The destructive step is large enough that muscle-memory confirmation is dangerous. Forcing the user to type the disk name (e.g., `WIPE /Volumes/MyUSB`) prevents accidents and forces the user to actively confirm *which* disk.
5. **`setup`, `eject`, `doctor` as new subcommands of `genomeclaw-prep`, not separate scripts.** Keeps the entire user-facing surface inside the same shim and the same Docker image. The shim runs the setup logic *inside the toolkit container*, which means we can use the same `bcftools view -h` for validation that the rest of the pipeline uses — no duplicate dependencies on the host.
6. **Pre-flight assertions are a library, not a decorator.** Each orchestrator calls `assert_*` functions explicitly at the top of its main entry. A decorator would make the call site invisible; we want it visible because the assertions are part of the orchestrator's contract with the user.
7. **`shard_scratch` is a context manager, not a kwarg.** Pipeline steps work in a `with shard_scratch(step, shard_id) as scratch:` block. The scratch dir is purged on `__exit__` even on exception. This pattern matches the existing `tempfile.TemporaryDirectory` shape that Phase 4A introduced, so the Phase-4A migration is mostly mechanical.
8. **Lima `additionalDisks` config goes in `~/.lima/colima/lima.yaml`, not a separate config file.** Per `docs/reports/cram-scratch-strategy.md`. Confirmed at Phase-2 against pinned colima version — open question Q5 in spec.
9. **No two-disk split for scratch.** The cram-scratch-strategy report's hybrid-tier option (random scratch on APFS, sequential scratch on exFAT) is **not** taken in this plan. The block-attached ext4 image satisfies both patterns natively. The `Genome_Bulk` exFAT partition exists only for cross-OS interop handoffs (e.g., copying a final VCF to a Windows machine) and is never written to by the pipeline. Skippable at setup time if the user doesn't need it.

### Schema / Provenance Impact

- **No schema changes.** Schema v0.2 from Phase 4A remains current.
- **No new provenance columns.** Existing seven canonical columns are preserved.
- **New audit file**: `_scratch/setup.log` records the one-time setup operation. Format: JSON Lines, one event per line, `{"ts": ..., "event": "...", "args": {...}}`. Fields: timestamps, source paths, dest paths, file SHAs, colima/lima config diffs, partition state before/after. Not part of the per-run `provenance.json` (the setup is *outside* the run lifecycle), but referenced by `doctor` for "when was this set up, by what version of the toolkit?"
- **Rebuild procedure unchanged**: a clean rerun from `raw/<sample>` against the same toolkit image yields row-equivalent outputs. The setup itself is one-time and deterministic — re-running it on an already-set-up drive is a no-op (Q2 → adopt path).

### Privacy & Egress Impact

- **New network egress points**: none.
- **New secret-handling surfaces**: none. The setup script does not handle credentials.
- **Redaction added**: n/a. No data is ever transmitted.
- **New surface for accidental egress**: `_scratch/setup.log` contains paths and sample IDs. It is written under `_scratch/` (not `derived/`), explicitly excluded from anything that flows to NemoClaw. Documented in Q3.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Setup script foundation: detection + dry-run preview, no destructive ops. Update `user-stories.md` Step 0 to describe the new flow. | Detection correctness, dry-run rendering, same-device rejection | ~12 |
| 2 | Setup script destructive path: partition, format external drive as APFS, move data, write `colima.yaml`, restart colima, verify mounts via shim. (Post-pivot: 9-step sequence; block-attached scratch deferred per cram-scratch-strategy.md § Post-implementation discovery.) | Confirmation gate, partition execution, audit log, restart-colima sequencing | ~10 |
| 3 | **(Re-scoped post-pivot)** Pre-flight assertion library + migrate `annotate` and `materialize` off `/tmp` onto `/mnt/genomeclaw/scratch`. **Real-data smoke gate** (full pipeline against MPNRGLQ2K survives the new scratch tier with row-equivalent results). This is the test of the Option-A bet. The original Phase-3 in-VM ext4 lifecycle is obsolete. | Assertion fail-fast, error-message specificity, row equivalence vs. baseline (4,870,517 / 42,885 ClinVar matches), virtiofs+APFS scratch survival under bcftools-annotate I/O patterns | ~10 + real-data run |
| 4 | Pipeline primitives: `shard_scratch`, `atomic_promote`, mid-run scratch monitor. Migrate `ingest` and `normalize` to use them. | Atomicity under simulated crash, scratch purge on exception, monitor-triggered abort | ~12 |
| 5 | `eject` + `doctor` subcommands; user-stories.md / README finalisation; `INV-D003` promotion to `INVARIANTS.md`. Move `storage-scratch-layout/` to `completed/`. | Eject preconditions, doctor failure modes, lint guard against >1 GB writes to derived/ | ~8 |

Total estimated test count: ~52, plus one real-data smoke per Phase-3 completion gate.

> **Note on phase numbering**: post-pivot, the original Phase 3 (in-VM
> mkfs.ext4 lifecycle) is gone. The remaining work has been renumbered:
> what was Phase 4 → Phase 3, Phase 5 → Phase 4, Phase 6 → Phase 5.
> The original phase-3.md / phase-4.md / etc. are *not* used; phase-3.md
> is rewritten with the new scope. The plan's overall shape doesn't
> change — same total work, one fewer phase.

## Phase 1: Setup Foundation + Dry-Run

**Goal**: User can run `genomeclaw-prep setup`, see exactly what would happen, and bail without any side effect. `user-stories.md` Step 0 reflects the new flow.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. New `setup` subcommand wired into `bin/genomeclaw-prep` and `cli.py`. Dispatches into the toolkit container.
2. `prep/setup/detect.py` — volume detection, Nebula deliverable validation, parent-disk identity check.
3. `prep/setup/dryrun.py` — renders a `SetupPlan` to a human-readable preview.
4. `user-stories.md` Story 1 Step 0 rewritten to describe the `setup` flow, including the typed-confirmation phrase.
5. README's Storage planning section rewritten to point at `setup`.

### Invariants Enforced Here
- **INV-D001**: tests assert that the dry-run path makes zero filesystem mutations of any kind under the source or target drive. The preview is rendered to stdout; no audit log is written; no YAML files are touched.
- **INV-P001**: tests assert that detection makes zero network calls (mocked HTTP layer expects no requests).

### Success Criteria
- [ ] All Phase-1 tests pass (RED → GREEN → REFACTOR visible in commit history)
- [ ] Static checks pass (ruff + mypy)
- [ ] At least one test per enforced invariant
- [ ] `genomeclaw-prep setup` against a synthetic two-disk fixture produces a complete dry-run preview
- [ ] `genomeclaw-prep setup` rejects a same-device source/target with a specific error message
- [ ] `user-stories.md` Step 0 reads cleanly without referencing the old four-`mkdir` flow
- [ ] No code path mutates host filesystem outside the test sandbox

## Phase 2: Setup Destructive Path

**Goal**: After typed confirmation, the setup script actually partitions, formats, moves data, writes `scratch.raw`, edits colima/lima configs, and restarts colima. Audit log captures every step.
**Detailed Plan**: phases/phase-2.md (created when Phase 1 lands)

### Deliverables
1. `prep/setup/execute.py` — the destructive runner.
2. `prep/setup/audit.py` — `_scratch/setup.log` writer.
3. Test rig using loop-mounted sparse images (NOT real partitions).
4. Resolution of Q5 (lima additionalDisks config path); pinned in this plan and in the README.

### Invariants Enforced Here
- **INV-D001**: tests assert that the move step preserves source-file content hash before and after; setup.log records both.
- **INV-R001**: tests assert that the audit log captures `colima_version`, `lima_version`, `toolkit_version`, `timestamp`, and the resolved paths, so a future investigation can reconstruct the setup.

### Success Criteria
- [ ] Confirmed plan executes end-to-end against the test rig
- [ ] Aborting between any two steps leaves the system in a documented, recoverable state (audit log captures partial progress)
- [ ] Same-disk source-and-destination rejection holds even if the disk identifiers are obscured by mount-point names
- [ ] Real-data smoke: project owner runs `setup` against their actual environment with a spare drive; setup completes; first-time VM start succeeds

## Phase 3: VM-Side Scratch Lifecycle

**Goal**: First VM start after setup formats the attached block device with ext4 and mounts it correctly. Subsequent starts re-detect and skip mkfs. The shim verifies all four mount flags by parsing `mount` output inside the VM and fails loud on any mismatch.
**Detailed Plan**: phases/phase-3.md

### Deliverables
1. VM-side init script (runs on container start) that does the blkid detect / mkfs.ext4 / mount / smoke-test sequence.
2. Updated `bin/genomeclaw-prep` mount-flag verifier that parses `/proc/self/mountinfo` (or `mount` output) and asserts (`raw` ro, `reference` ro, `derived` rw, `scratch` rw + ext4).
3. Smoke test: write 1 GB random file, read it back, verify checksum, delete. Runs on every VM start; ~5 seconds.

### Invariants Enforced Here
- **INV-D001**: tests assert that first-attach mkfs.ext4 only runs against the block device when blkid reports no existing filesystem. A second VM start with an already-formatted block device must skip mkfs.
- **INV-R001**: smoke test result captured in a startup health summary; available via `doctor` post-Phase-6.

### Success Criteria
- [ ] First VM start: mkfs runs, mount succeeds, smoke test passes, container ready
- [ ] Second VM start: mkfs skipped, mount succeeds, smoke test passes, container ready
- [ ] Pre-formatted block device with the *wrong* filesystem (ext2, xfs) surfaces a specific error and refuses to overwrite
- [ ] All four mount flags verified from inside the VM; offending flag printed verbatim if wrong

## Phase 4: Pre-Flight Assertions + Migrate Annotate/Materialize

**Goal**: Drop the Phase-4A `/tmp` workaround. `annotate` and `materialize` use `/mnt/genomeclaw/scratch` via the new pre-flight assertion library. Real-data smoke gate against the project owner's Nebula VCF: row-equivalent or byte-equivalent results vs. the Phase-4A baseline.
**Detailed Plan**: phases/phase-4.md

### Deliverables
1. `prep/preflight.py` — `assert_genome_work_apfs()`, `assert_scratch_attached()`, `assert_scratch_budget(step, gb)`, `assert_derived_writable()`. Each raises a typed exception with a specific, fixable message.
2. Migration of `annotate.py` off `tempfile.TemporaryDirectory(dir="/tmp")`.
3. Migration of `materialize.py` off `/tmp`. `store.py:write_variants(work_dir=...)` accepts the new scratch dir.
4. Real-data smoke gate documented in `work-notes.md`.

### Invariants Enforced Here
- **INV-D001**: assertions confirm `raw/` is mounted RO before any pipeline step runs.
- **INV-R001**: row-equivalence test against the Phase-4A `/tmp`-baseline run (not byte-equivalence — the timestamps differ — but a SQL diff against the variants table that excludes provenance-timestamp columns shows zero changes).
- **NEW INV-D003**: integration test observes that all > 1 GB writes during the run target `/mnt/genomeclaw/scratch`, not `/mnt/genomeclaw/derived`.

### Success Criteria
- [ ] `annotate` succeeds end-to-end on the new scratch tier against the real Nebula VCF
- [ ] `materialize` succeeds end-to-end on the new scratch tier
- [ ] DuckDB store row count matches Phase-4A baseline; ClinVar match count matches (42,885)
- [ ] Schema version unchanged (v0.2)
- [ ] Pre-flight assertions reject a missing scratch mount with the printed mount-line offending flag

## Phase 5: Pipeline Primitives

**Goal**: `shard_scratch` and `atomic_promote` are first-class library primitives that future Phase-5+ orchestrators (CRAM → VCF) will use uniformly. Mid-run scratch monitor logs `df -h` and aborts if observed-growth × estimated-remaining-time exceeds free space. `ingest` and `normalize` migrate to the new primitives.
**Detailed Plan**: phases/phase-5.md

### Deliverables
1. `prep/scratch.py` — `shard_scratch(step, shard_id) -> ContextManager[Path]`, `atomic_promote(scratch_path, derived_path)`, `ScratchMonitor(step, budget_gb).__enter__()` (background thread).
2. Migration of `ingest.py` and `normalize.py`.
3. Property-based tests for `atomic_promote` under simulated SIGKILL between stages.

### Invariants Enforced Here
- **INV-R001**: `atomic_promote` test asserts that interrupting the cp leaves `derived/` unchanged (the `.tmp` file is orphaned but no half-written final artifact ever appears).
- **INV-D001**: `shard_scratch` test asserts purge on `__exit__` even on exception (no zombie scratch dirs accumulating to fill the disk).

### Success Criteria
- [ ] `shard_scratch` purges cleanly on success and exception
- [ ] `atomic_promote` is atomic (mv-within-fs) and crash-safe (no partial-rename observable)
- [ ] `ScratchMonitor` aborts a synthetic test job when growth-rate × remaining-time projection exceeds free space
- [ ] Full Phase-4A pipeline (ingest → normalize → annotate → materialize) runs against real Nebula VCF on the new primitives

## Phase 6: Eject + Doctor + Docs + Invariant Promotion

**Goal**: User can `genomeclaw-prep eject` cleanly, `genomeclaw-prep doctor` diagnoses common misconfigurations, the user-facing docs match the implementation, `INV-D003` is promoted into `INVARIANTS.md`. Storage-scratch-layout plan moves to `completed/`.
**Detailed Plan**: phases/phase-6.md

### Deliverables
1. `prep/eject.py` + `genomeclaw-prep eject` subcommand.
2. `prep/doctor.py` + `genomeclaw-prep doctor` subcommand. Reads `_scratch/setup.log` for "when was this set up?"; runs the full pre-flight battery; reports.
3. `user-stories.md` finalized — already started in Phase 1, finalized here once the implementation is real.
4. README "Storage planning" section finalized.
5. `docs/reference/architecture.md` mount table updated.
6. `docs/reference/INVARIANTS.md` v1.6: `INV-D003` added with full Rule / Requirements / Where it applies / How to verify.
7. `docs/plans/active/storage-scratch-layout/` → `docs/plans/completed/storage-scratch-layout/` with a closing note.
8. Lint guard against new code paths writing > 1 GB to `/mnt/genomeclaw/derived/<run-id>/` outside the allowlist.

### Invariants Enforced Here
- **NEW INV-D003** promoted: lint guard test + integration test (a synthetic violator under `prep/` triggers the lint failure).

### Success Criteria
- [ ] `eject` refuses if a pipeline is mid-run; succeeds otherwise; the drive is fully ejected (kernel says so)
- [ ] `doctor` against a misconfigured environment (e.g., scratch unmounted, derived RO) reports each failure with a fixable message
- [ ] All docs match the code
- [ ] `INV-D003` lint guard catches a synthetic violator
- [ ] `INVARIANTS.md` version bumped, index updated, last-updated bumped

---

## Testing Strategy

### Unit Tests
- `prep/setup/detect.py` — disk-list parsing, Nebula-shape validation, parent-disk identity comparison
- `prep/setup/dryrun.py` — SetupPlan → preview rendering (snapshot tests)
- `prep/preflight.py` — each assertion in isolation against a fake `Mount` object
- `prep/scratch.py` — `shard_scratch` and `atomic_promote` against `tmp_path`
- `prep/eject.py` — sequencing logic with mocked `colima` / `diskutil`

### Integration Tests
- `tests/integration/test_setup_dryrun.py` — full setup flow from `setup` invocation through dry-run preview, against a synthetic two-disk fixture (loop-mounted sparse images)
- `tests/integration/test_setup_execute.py` — confirmed plan executes against the same fixture; audit log written; partial-failure recovery
- `tests/integration/test_vm_init_first_attach.py` — first-attach mkfs.ext4 + smoke test
- `tests/integration/test_vm_init_re_attach.py` — second-attach skips mkfs
- `tests/integration/test_annotate_on_scratch.py` — Phase-4 migration: annotate against `/mnt/genomeclaw/scratch`
- `tests/integration/test_materialize_on_scratch.py` — materialize against `/mnt/genomeclaw/scratch`
- `tests/integration/test_eject.py` — eject sequencing
- `tests/integration/test_doctor.py` — doctor against a misconfigured environment

### Provenance Tests
- `tests/provenance/test_setup_audit_log.py` — `_scratch/setup.log` carries the required fields (timestamp, source, dest, file SHAs, versions)
- Existing Phase-4A provenance tests re-run on the new scratch tier

### Determinism Tests
- `tests/determinism/test_phase4a_on_new_scratch.py` — Phase-4A pipeline run row-equivalent to the `/tmp`-baseline run

### Privacy-Default Tests
- `tests/privacy/test_setup_zero_egress.py` — full `setup` flow makes zero outbound network calls (httpserver fixture asserts no requests)

### Invariant Tests
- `tests/invariants/test_invD001_setup_does_not_mutate_source.py` — content-hash before and after dry-run is unchanged; content-hash after move equals content-hash before move (different path, same bytes)
- `tests/invariants/test_invD002_no_sandbox_path_to_scratch.py` — the OpenShell policy preset has no path under `/mnt/genomeclaw/scratch`
- `tests/invariants/test_invD003_scratch_discipline.py` — recorded I/O during a real-data run shows no > 1 GB write to `/mnt/genomeclaw/derived/`
- `tests/invariants/test_invR001_atomic_promote_crash_safety.py` — simulated SIGKILL between cp and mv leaves `derived/` clean

### Real-Data Smoke (Phase-4 completion gate)
- Project owner runs the full Phase-4A pipeline (ingest → normalize → annotate → materialize) on the real Nebula VCF on the new scratch tier. Assertions: total variants 4,870,517; ClinVar matches 42,885; schema v0.2; manifest.json + provenance.json well-formed. Logged in `work-notes.md` with elapsed time per stage.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — add `INV-D003`, bump to v1.6
- [ ] `docs/reference/user-stories.md` Story 1 Step 0 — rewritten in Phase 1, finalized in Phase 6
- [ ] `docs/reference/architecture.md` — mount table updated; cite `INV-D003`
- [ ] `README.md` — "Storage planning" section rewritten
- [ ] `.claude/agents/bioinformatics-pipeline.md` — note the scratch-discipline change and the new pre-flight library
- [ ] `docs/plans/active/storage-scratch-layout/` — closing note + move to `completed/`

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-09 | 2026-05-09 | Setup foundation + dry-run. 17 new tests (10 unit + 7 integration); 86/86 suite green; real-data validation against Kingston XS2000 + 55.4 GB Nebula succeeded. |
| Phase 2 | Complete (Option A pivot) | 2026-05-09 | 2026-05-10 | Destructive setup runner. Real-data run on Kingston discovered colima 0.9.1 strips `additionalDisks` → architectural pivot to virtiofs-on-APFS (Option A). 12-step sequence collapsed to 9. Tests updated; 109/109 suite green; lint clean. Block-attached scratch deferred; tripwires documented in cram-scratch-strategy report. **Phase-4A end-to-end smoke against new layout passes**: 4,870,517 variants / 42,885 ClinVar matches, row-equivalent to old layout. |
| Phase 3 | Complete | 2026-05-10 | 2026-05-10 | Pre-flight assertions + annotate/materialize migration off `/tmp` + env var rename + canonical-layout auto-detect. 13 new preflight tests; 122/122 suite green; lint clean. **Real-data smoke validates Option-A bet**: full pipeline on virtiofs+APFS scratch produces row-equivalent results (4,870,517 / 42,885 / v0.2) with ~32% wall-time overhead vs `/tmp` overlay; no deadlocks, no EIO, none of the Phase-5+ tripwires fired. |
| Phase 4 | Complete | 2026-05-10 | 2026-05-10 | Pipeline primitives. `shard_scratch` (auto-cleanup context manager) + `atomic_promote` (copy + fsync + within-FS rename). Migrated annotate (uses both) and materialize (uses shard_scratch). 15 new tests; 137/137 suite green; lint clean. Smoke retains row equivalence (4,870,517 / 42,885). `monitor_scratch` deferred to Phase 5+ when actual budgets exist. |
| Phase 5 | Complete | 2026-05-09 | 2026-05-09 | `eject` + `doctor` subcommands; INV-D003 promoted to `INVARIANTS.md` v1.6. 11 new tests (4 eject + 7 doctor); 148/148 suite green. Doctor rewritten host-side after live-Kingston smoke surfaced false-positive FAILs from reusing in-container preflight assertions: doctor diagnoses what the user can fix on the host (existence + write-probe), preflight remains the in-container INV-D001 enforcement layer. user-stories.md / README.md / architecture.md finalised; `_scratch/` rename propagated. `storage-scratch-layout/` retired with `_SUPERSEDED.md` closing note. |

---

## Open Risks & Follow-ups

- **Risk**: Drive firmware advisories post-launch. The Samsung T7 Shield has no published recall today, so the known-bad list ships empty. If Samsung publishes a future advisory (or the user uses a non-validated drive that has one), `doctor` surfaces drive model + firmware so the user can re-check and the maintainers can update the known-bad list as a config change rather than a code change. Mitigation: encode the known-bad list as a versioned data file rather than inline in `detect.py`, and surface drive identity in `doctor` from day one.
- **Risk**: Lima `additionalDisks` API may change between colima versions during the implementation window. Mitigation: pin colima + lima versions in `bin/genomeclaw-prep` doctor output; verify on every host's first run.
- **Risk**: macOS Sequoia could change virtiofs RO defaults again in a point release. Mitigation: `doctor` reports OS version + virtiofs flags per mount; flag known-bad combinations.
- **Follow-up**: Linux host support — separate plan once macOS lands and stabilizes.
- **Follow-up**: PRS computation (`pgsc_calc`) Nextflow `work/` sizing — measured on first integration during MVP Phase 5+; this plan ships the assertion machinery, not the budget number.
- **Follow-up**: GATK HaplotypeCaller integration as cross-validation only — `--tmp-dir` + `-Djava.io.tmpdir` plumbing is correct after this plan; the actual integration is MVP Phase 5+ scope.
- **Follow-up**: 350 GB scratch resize procedure if cross-validation runs become routine — `truncate -s 350G` + `resize2fs`. Document in Phase 6 README; not implemented as automation.
- **Follow-up**: Two concurrent runs are out of scope; the orchestrator serializes. Re-open if multi-run usage becomes routine.

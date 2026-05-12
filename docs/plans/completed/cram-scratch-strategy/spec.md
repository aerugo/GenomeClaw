# Feature: CRAM-Scale Scratch Strategy + Interactive Setup

**Status**: Draft
**Created**: 2026-05-09
**Owner**: GenomeClaw maintainers
**Related Plans**:
- [research-brief.md](research-brief.md) (the consultant brief that produced the chosen design)
- [docs/reports/cram-scratch-strategy.md](../../reports/cram-scratch-strategy.md) (the design itself; this plan implements it)
- [storage-scratch-layout/](../storage-scratch-layout/) (the earlier plan this **supersedes**)

---

## Goal

Land the storage architecture from `docs/reports/cram-scratch-strategy.md` end-to-end — interactive setup script, partition/format flow, block-attached ext4 scratch, pre-flight assertions, scratch helpers, and pipeline migration — so MVP Phase 5+ (CRAM → VCF alignment + variant calling) can begin against a configuration that is known-safe at scale.

## Background

Phase 4A shipped end-to-end against the project owner's real Nebula VCF (4.87M variants, 42,885 ClinVar matches), but only by routing scratch through the container's `/tmp` overlay (local SSD), `bcftools annotate` instead of vcfanno, and a per-orchestrator `tempfile.TemporaryDirectory(dir="/tmp")` workaround. Three concrete failures during Phase 4A development demonstrated that the original four-mount discipline (storage-scratch-layout plan) cannot survive CRAM-scale workloads:

1. **vcfanno end-of-stream deadlock** under virtiofs FUSE serialization on USB-3 exFAT — both vcfanno and bgzip stuck in `futex_wait` / `pipe_read` for 45+ minutes after producing 196 MB of output. Reproducible.
2. **`work` mount silently read-only** on macOS Sequoia + colima/VZ.framework when rooted under `$HOME`, even with `writable: true` declared — `OSError: [Errno 30]` from any orchestrator that writes there.
3. **Concurrent random-read + sequential-write throughput collapse** to single-digit MB/s on USB-3 exFAT virtiofs under tabix-style I/O.

A consultant engagement produced the design now in `docs/reports/cram-scratch-strategy.md`. The design replaces virtiofs scratch with a block-attached ext4 disk image (lima `additionalDisks`), reformats the external drive's processing tier from exFAT to APFS, mounts source-of-truth dirs RO via virtiofs, enforces per-chromosome scatter-gather, and adds pre-flight scratch-budget assertions and atomic promotion to `derived/`.

The design also requires the user to repartition / reformat their external drive, which is a destructive operation. The current `Step 0 — storage prep` user-story (in `user-stories.md`) was written for the old four-mount discipline and assumes the user hand-edits `colima.yaml` and `mkdir`s four directories. It is no longer correct, and even if updated by hand, the destructive partition step needs interactive confirmation, dry-run preview, and validation gates that prose-only instructions cannot reliably enforce.

This plan replaces those manual steps with an interactive `genomeclaw-prep setup` subcommand and ships the rest of the cram-scratch-strategy alongside it.

## Acceptance Criteria

Each criterion maps to one or more tests in the phase plans. Criteria marked **(real-data)** require validation on the project owner's actual hardware per `docs/plans/CLAUDE.md` "Real-data smoke as a phase-completion gate."

- [ ] AC1: `genomeclaw-prep setup` runs interactively, detects all mounted volumes via `diskutil list -plist` (or Linux equivalent), and asks the user to point at their Nebula deliverable directory.
- [ ] AC2: The setup script validates the Nebula deliverable shape — at minimum one of `*.vcf.gz`, `*.cram`/`*.bam`, `*.fastq.gz` is present; `*.vcf.gz.tbi` exists when `*.vcf.gz` does; basic header read via `bcftools view -h` succeeds. Surfaces a specific, fixable error message on each failure mode.
- [ ] AC3: The setup script prompts the user to select a target external drive for `Genome_Work`, and **rejects** any selection that resolves to the same physical device as the Nebula deliverable. Same-device detection uses `diskutil info -plist` parent-disk identity, not just path comparison. The script then runs three target-validation checks before any destructive op, each with a specific fixable error on failure:
  1. **Hardware identity check.** Read model + firmware revision from `diskutil info -plist`, surface them in the dry-run preview, and check the firmware revision against a maintained known-bad list. For the validated Samsung T7 Shield 2 TB the list is currently **empty** (no Samsung portable-SSD recall analogous to the 2023 SanDisk Extreme Pro data-loss issue); the gate stays in place so a future Samsung advisory becomes a config update rather than a code change. For other drive models / brands, the same mechanism surfaces the identity and applies the corresponding known-bad list. Non-validated drives proceed by default unless they match a known-bad entry.
  2. **Free-space check.** Compute `sizeof(raw) + sizeof(reference for chosen annotation set) + sizeof(scratch.raw, default 300 GB) + 50 GB safety margin` and compare against the target drive's free space. Reject with a shortfall message if insufficient. The required size is computed at runtime, never hardcoded — for a typical Nebula CRAM-only deliverable (~55 GB CRAM + ~220 MB VCF + indexes), Phase-4A-only configuration needs ~360 GB and full Phase-5+ with annotations needs ~505 GB. See `docs/reports/cram-scratch-strategy.md` § External Drive Topology for the per-configuration table.
  3. **Filesystem starting state.** Detect current filesystem (APFS, exFAT, HFS+, unformatted, etc.) and surface it in the dry-run preview so the user knows what is about to be wiped.
- [ ] AC4: The setup script displays a complete dry-run of what it would do (partition table changes, files moved, files created, colima/lima config diffs) and requires the user to type a non-trivial confirmation phrase (e.g., `WIPE /Volumes/<diskname>`) before any destructive operation.
- [ ] AC5: After confirmation, the setup script partitions the target drive into `Genome_Work` (APFS; sized to the actual computed need — see AC1's pre-flight, not a fixed minimum) and optionally `Genome_Bulk` (exFAT, 200–500 GB; skippable), creates `genomeclaw/{raw,reference,derived,_scratch}/` on `Genome_Work`, and **moves** the Nebula deliverable into `genomeclaw/raw/<sample-id>/` (not copies — the source drive is being repartitioned and the user explicitly opted in).
- [ ] AC6: The setup script creates `_scratch/scratch.raw` as a 300 GB sparse file, writes `~/.colima/default/colima.yaml` with three virtiofs mounts (`raw` RO, `reference` RO, `derived` RW) all rooted under `/Volumes/Genome_Work/genomeclaw/`, and writes `~/.lima/colima/lima.yaml` (or equivalent) declaring `additionalDisks` pointing at `scratch.raw`.
- [ ] AC7: First VM start after setup formats the attached block device with `mkfs.ext4 -L genomeclaw-scratch` and `tune2fs -m 5`, mounts at `/mnt/genomeclaw/scratch`, and runs a 1 GB write/read/checksum smoke test inside the VM. Subsequent starts re-detect the existing filesystem and skip mkfs.
- [ ] AC8: `genomeclaw-prep` (any subcommand) verifies all four mounts (`raw`, `reference`, `derived`, `scratch`) at startup by parsing `mount` output **inside the VM** and fails loud, printing the offending mount line, if any flag is wrong.
- [ ] AC9: Pre-flight assertion library exposes `assert_scratch_budget_gb(step, required_gb)`, `assert_genome_work_apfs()`, `assert_derived_writable()`. Each orchestrator (`annotate`, `materialize`, future Phase-5 entry points) calls them before any work and surfaces specific, fixable errors.
- [ ] AC10: The `annotate` and `materialize` orchestrators are migrated off the Phase-4A `/tmp` workaround onto `/mnt/genomeclaw/scratch`. The `tempfile.TemporaryDirectory(dir="/tmp")` calls are removed. **(real-data)** — re-run Phase 4A end-to-end against the real Nebula VCF on the new layout; assert byte-equivalent or row-equivalent outputs vs. the Phase-4A `/tmp`-based run.
- [ ] AC11: Pipeline primitives module exposes `shard_scratch(step, shard_id)` (yields a per-shard scratch dir, purges on exit) and `atomic_promote(scratch_path, derived_path)` (cp + fsync + mv-within-fs). Both have unit tests and integration tests.
- [ ] AC12: A `genomeclaw-prep eject` subcommand stops colima, ejects the external drive via `diskutil`, and reports done. Surfaces a clear error if the VM cannot stop cleanly (e.g., a pipeline still running).
- [ ] AC13: `user-stories.md` Story 1 Step 0 is rewritten to describe the new `genomeclaw-prep setup` flow. The README's Storage planning section is rewritten to match. The previous manual `mkdir` instructions are removed (not commented-out — removed; they are actively misleading under the new design).
- [ ] AC14: `docs/plans/active/storage-scratch-layout/` is moved to `docs/plans/completed/` with a closing note pointing at this plan as its successor.

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the setup script *moves* Nebula data into `raw/`, then the runtime mounts `raw/` virtiofs read-only inside the VM. Once setup completes, no pipeline path can mutate `raw/`. The `move` step is itself a one-time, user-confirmed operation outside the run lifecycle, not a pipeline step. Provenance of the move is logged to a setup audit file under `_scratch/setup.log`.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — scratch lives on `/mnt/genomeclaw/scratch`, accessible only inside the toolkit container. The agent sandbox has no mount of any genomeclaw path. This plan adds no path through which the OpenShell sandbox could reach scratch or `raw/`.
- **INV-P001** Privacy Default — setup is entirely local. The only optional egress is `genomeclaw-prep fetch …` (already gated, not in this plan's scope). The setup script makes no network calls. The dry-run preview does not transmit any sample identifiers anywhere.
- **INV-R001** Rebuildability — every pipeline step's scratch budget is asserted pre-flight; ext4 journaling guarantees on-disk consistency across drive yanks; atomic promotion ensures `derived/` only ever holds validated outputs. Provenance columns and per-run `manifest.json` / `provenance.json` are unchanged.
- **INV-C001** Separate Research Assistance from Clinical Advice — the setup script's confirmation copy and any error message it surfaces is reviewed by `privacy-safety-reviewer` for over-claim before merge (it touches user-facing copy that mentions genome data destination).

## Proposed New Invariants

- **NEW INV-D003 — Heavy Scratch Is Block-Attached, Not virtiofs.** Any pipeline step generating > 1 GB of intermediates must write to `/mnt/genomeclaw/scratch` (block-attached ext4) and not to a virtiofs-backed mount. Final, validated outputs are then atomically promoted to `/mnt/genomeclaw/derived/` (virtiofs RW, small writes only). Rationale: virtiofs's FUSE-message protocol serializes per-share and produces async deadlocks under bioinformatics-tool I/O patterns (vcfanno + bgzip class). The class of failure is not specific to vcfanno; it surfaces with any concurrent multi-threaded I/O at scale. Promoting this rule to an invariant means future pipeline authors cannot accidentally re-introduce the failure mode by routing scratch through `derived/` or `work/`. Verification: integration tests assert that after a pipeline step, `/mnt/genomeclaw/scratch` was the target of all > 1 GB writes; lint/grep guard rejects new code under `packages/toolkit/src/genomeclaw_toolkit/prep/` that opens write paths under `/mnt/genomeclaw/derived/<run-id>/` larger than a small allowlisted set (final VCF, manifest, provenance, DuckDB store post-promotion).

## Technical Requirements

### Source Data Inputs

- Nebula deliverable directory on the user's existing storage (any filesystem, any mount point). Must contain at least one of: `*.vcf.gz`, `*.cram`/`*.bam`, `*.fastq.gz`. Tabix indexes accepted but not required.
- **Target hardware**: Samsung T7 Shield 2 TB (USB-C). 2 TB capacity, USB 3.2 Gen 2 (10 Gbps; real ~900–1050 MB/s sequential on Apple Silicon Mac USB-C ports), NVMe internals (~100K+ random IOPS), bus-powered, no external power, IP65 + 3 m drop rating. The lean configuration uses ~19% of the drive, full Phase-5+ annotations ~27%, future-proof (10 runs + scratch resize) ~43% — comfortable headroom across all anticipated configurations. exFAT, APFS, or unformatted starting states are all acceptable; the setup script reformats. Setup reads the drive's model + firmware revision before partitioning and checks the revision against a maintained known-bad list — currently empty for Samsung T7 Shield, kept in place as a forward-compatible gate against any future Samsung firmware advisory. The runtime pre-flight space check (AC3) is the safety belt for users who run setup against a different drive. Choice rationale: Samsung's portable SSD line has no equivalent of the 2023 SanDisk Extreme Pro firmware data-loss incident; same speed tier as alternatives at the price point; the drive's IP65 + drop rating is bonus for users who carry it.

### Derived Outputs

- New external-drive layout under `/Volumes/Genome_Work/genomeclaw/{raw,reference,derived,_scratch}/`.
- `_scratch/scratch.raw` — 300 GB sparse file, ext4 on first VM attach, mounted at `/mnt/genomeclaw/scratch`.
- `_scratch/setup.log` — host-side audit trail of the setup-script run (timestamps, source path, dest path, partition layout, confirmation phrase typed).
- Updated `~/.colima/default/colima.yaml` and `~/.lima/colima/lima.yaml` (or equivalents).

### Schema / Migration Impact

- No changes to the DuckDB derived store schema. (Schema v0.2 from Phase 4A remains current.)
- The four-mount discipline changes from `(raw, reference, derived, work)` to `(raw, reference, derived, scratch)`. `work` is removed as a canonical mount; legacy code paths that reference `GENOMECLAW_WORK_DIR` are deprecated and rerouted to `/mnt/genomeclaw/scratch` with a one-release deprecation warning.
- The `bin/genomeclaw-prep` host shim's mount table changes accordingly. `GENOMECLAW_WORK_DIR` becomes `GENOMECLAW_SCRATCH_DIR` (defaulting to the lima additionalDisks block device path).

### Pipeline / Workflow Impact

- New `genomeclaw-prep setup` subcommand (interactive; emits dry-run; commits on confirmation phrase).
- New `genomeclaw-prep eject` subcommand.
- New `genomeclaw-prep doctor` subcommand (read-only — runs the full pre-flight assertion battery and reports). Cheap to add; high value during support; documented as the first thing a user with a problem should run.
- Existing `annotate`, `materialize`, `ingest`, `normalize` orchestrators migrated to use `/mnt/genomeclaw/scratch` instead of the Phase-4A `/tmp` fallback.
- New library modules: `prep/preflight.py`, `prep/scratch.py` (shard_scratch + atomic_promote helpers), `prep/setup/` (the interactive flow + the dry-run renderer).

### Agent / UX Impact

- The `genomeclaw-prep setup` confirmation prompts are user-facing copy. They name the disk by its identifier (`/dev/disk4`, `/Volumes/<old-name>`) and require an unambiguous, typed phrase. Reviewed by `privacy-safety-reviewer` for over-claim and over-defer.
- `user-stories.md` Story 1 Step 0 rewrite — see AC13.
- README's Storage planning section rewrite.
- No changes to the agent (NemoClaw) interaction surface. No new tools exposed to the agent. No new endpoints on the host service.

### External Dependencies

- `diskutil` (macOS-native; present on every macOS install).
- `colima` ≥ track latest stable (mount-config behavior pinned per `docs/reports/cram-scratch-strategy.md`).
- `lima` ≥ 1.1 (per cram-scratch-strategy.md — earlier versions had `additionalDisks` truncate-to-0 bug, lima #1964).
- `truncate` (coreutils on macOS via Homebrew or built-in; presence detected at setup-script start).
- `samtools` ≥ 1.17, `bcftools` ≥ 1.17 (already in toolkit image).
- No new annotation datasets or reference builds.

## Privacy & Safety Considerations

- **Boundary scan**: The setup script reads the Nebula deliverable directory (host-side, no network), writes to the target external drive (host-side, no network), edits two YAML files in `$HOME` (host-side, no network), restarts colima (host-side, no network). No information about the user's genome leaves the device at any point. No telemetry. No crash reporter.
- **Default-off remote calls**: None. The setup script is fully offline. Network egress remains exclusively in `genomeclaw-prep fetch …` which is unchanged by this plan.
- **Redaction surface**: The dry-run preview displays the user's sample-id and source paths to the user's terminal. This is intentional — they need to see what the script will move. The dry-run output is not written to any log file that is shared, sync'd, or transmitted; it is rendered to stdout and discarded.
- **Clinical escalation**: This plan introduces no new findings or interpretations. It does not surface any biomedical content. `INV-C001` does not apply at the technical surface but applies to the user-facing copy of confirmation prompts (must not over-claim that this guarantees data integrity for clinical use).
- **Destructive-operation safety**: AC4 (typed confirmation phrase) and AC5 (move-not-copy semantics with the precondition that source and destination are different physical disks) together enforce that the user cannot accidentally lose their Nebula data. The setup script also writes a hash of every Nebula file under `_scratch/setup.log` before the partition step so that even if the move is interrupted, the user has a manifest of what was where.

## Out of Scope

- **Any actual variant-calling implementation.** This plan delivers the *infrastructure* that MVP Phase 5+ (CRAM → VCF) needs. DeepVariant integration, GATK HaplotypeCaller integration, the streaming bcftools-call pipeline, the per-shard orchestrator, and Phase-5 spec/plan creation all happen in subsequent MVP plans that depend on this one.
- **Linux host support.** The setup script targets macOS in this plan. The same architecture (ext4 on a block device, virtiofs RO for source data) works on Linux but the `diskutil` call, colima default, and ejection flow differ. Adding Linux support is a follow-up plan.
- **Windows host support.** Out of scope project-wide.
- **Two concurrent runs.** The 300 GB scratch image accommodates a single Tier-1 caller run with margin (per `docs/reports/cram-scratch-strategy.md` storage budget table). Concurrent runs require either a larger scratch or a serialization layer; the orchestrator will *serialize* concurrent requests, not run them in parallel. A future plan may revisit if multi-run usage becomes routine.
- **PRS computation (`pgsc_calc`) scratch sizing.** PRS lands on the same `/mnt/genomeclaw/scratch` and the same per-step scratch budget assertions, but the specific budget number for `pgsc_calc` is measured-on-first-integration per the cram-scratch-strategy report. This plan ships the assertion machinery; the budget number is filled in when MVP Phase 5+ runs PRS for the first time.
- **GATK benchmarking.** Scope-bounded to MVP Phase 5+'s caller-selection work. This plan ensures GATK *can* run (correct `--tmp-dir` + `-Djava.io.tmpdir` plumbing) but does not measure it.

## Dependencies

- Phase 4A complete (it is — schema v0.2, ClinVar overlay shipped).
- The user has the validated target drive — Samsung T7 Shield 2 TB (USB-C) — connected to the host (see Technical Requirements § Source Data Inputs above). The setup script verifies firmware revision and computes the actual required free space from the user's selections before any destructive op; both checks run before partitioning.
- The user is willing to destructively repartition that drive. (The setup script obtains explicit consent.)
- `colima` ≥ stable + `lima` ≥ 1.1 installed on the host. (The setup script verifies versions and refuses to proceed on older lima.)

## Open Questions

- [ ] Q1: Should `genomeclaw-prep setup` accept a `--non-interactive` flag with a config file, for CI / scripted-deployment scenarios? **Tentatively no** for MVP — the destructive nature of the operation is exactly the kind of thing where interactive confirmation is the right default. Re-open in a follow-up plan if a self-hosting deployment surface needs it.
- [ ] Q2: How does the setup script behave if the user has an existing `/Volumes/Genome` drive from the Phase-4A layout and runs `setup` again? **Tentative answer**: detect the existing layout, offer to either *adopt* it (skip partition; just write the new colima/lima configs and create `_scratch/scratch.raw`) or *reformat* it (full destructive flow). Phase-1 implements the detection; Phase-2 implements the adopt path; full reformat is also Phase-2.
- [ ] Q3: Where does `_scratch/setup.log` live long-term? It contains paths, sample IDs, and partition history — sensitive enough that it should not be casually shared, but not so sensitive that it needs to live behind encryption. **Tentative**: keep it on `Genome_Work` under `_scratch/`, never copy to `derived/` (which is what gets shared with NemoClaw), document its existence in the README, do not rotate (it's small and historical).
- [ ] Q4: Should the pre-flight `doctor` subcommand be permitted to run before `setup` has completed? **Tentative**: yes — it should be the *first* tool a confused user reaches for. It must therefore degrade gracefully and report exactly what's missing without erroring out.
- [ ] Q5: Lima's `additionalDisks` config path varies between colima versions. Which file does the setup script edit? **Open** — Phase-2 research item; cram-scratch-strategy.md mentions `~/.lima/colima/lima.yaml` but this may be `~/.colima/default/colima.yaml`'s `disk:` field in newer versions. Verify against the pinned colima version before Phase-2 lands.

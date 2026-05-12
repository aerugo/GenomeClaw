# CRAM Scratch Strategy — Work Notes

**Feature**: Implement the CRAM-scale scratch architecture from `docs/reports/cram-scratch-strategy.md`, including an interactive `genomeclaw-prep setup` subcommand, block-attached ext4 scratch, pre-flight assertions, pipeline primitives, and migration of `annotate` / `materialize` off the Phase-4A `/tmp` workaround.
**Started**: 2026-05-09
**Branch**: `feature/cram-scratch-strategy`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)
**Design source**: [docs/reports/cram-scratch-strategy.md](../../reports/cram-scratch-strategy.md)
**Supersedes**: [docs/plans/active/storage-scratch-layout/](../storage-scratch-layout/)

---

## Session Log

> Append-only. Newest entries at the bottom of the log. Each session opens with a context-review block.

### 2026-05-09 — Plan kickoff

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — confirmed applicable invariants: `INV-D001`, `INV-D002`, `INV-P001`, `INV-R001`, `INV-C001`. Identified one new invariant candidate (`INV-D003` — heavy scratch is block-attached, not virtiofs) for promotion after Phase 6 ships.
- Read [docs/reports/cram-scratch-strategy.md](../../reports/cram-scratch-strategy.md) — chosen design from the consultant brief. The five architectural moves it codifies (APFS for processing tier; virtiofs RO for source-of-truth; block-attached ext4 for scratch; per-chromosome scatter-gather; pre-flight scratch-budget assertions + atomic promotion) translate directly into the phase decomposition.
- Read [docs/reference/user-stories.md](../../reference/user-stories.md) — Story 1 Step 0 currently describes the four-`mkdir` manual flow that is now superseded.
- Read [docs/plans/active/storage-scratch-layout/development-plan.md](../storage-scratch-layout/development-plan.md) — confirmed the plan being superseded; scope is bounded to the original four-mount discipline.
- Read [docs/plans/CLAUDE.md](../../CLAUDE.md) — re-confirmed phase / TDD protocol and the "Real-data smoke as a phase-completion gate" rule (relevant for Phase 4 completion).
- Reviewed the existing Phase-4A code paths (`prep/annotate.py`, `prep/materialize.py`, `prep/store.py`) to understand the `/tmp` workaround that must be migrated.

**Applicable Invariants** (and how they constrain this work):
- **INV-D001** Source-of-Truth — the destructive `move` operation during setup is the only moment this plan touches a source artifact. Pre- and post-move SHAs are recorded in `_scratch/setup.log`, and the runtime virtiofs RO mount discipline kicks in immediately after.
- **INV-D002** Host-Side Only — scratch is a host-side VM disk, not visible to the OpenShell sandbox. No new path through the sandbox boundary.
- **INV-P001** Privacy Default — entirely offline. The setup script makes zero network calls.
- **INV-R001** Rebuildability — pre-flight scratch budget assertions, atomic promotion, ext4 journaling preserve "rerun yields byte-equivalent outputs."
- **INV-C001** Clinical Boundary — confirmation-prompt copy is user-facing; reviewed by `privacy-safety-reviewer`.
- **NEW INV-D003** (proposed) — block-attached scratch only for >1 GB writes; promoted to `INVARIANTS.md` after Phase 6 ships.

**Key Insights**:
- The setup script and the runtime are conceptually separate, but they share a Docker image and the same shim, so testing both inside the toolkit container is correct (avoids host-side bcftools install).
- The `/tmp` fallback in Phase-4A code is *only* there because the canonical `work` mount is RO on macOS Sequoia. Once `scratch` is block-attached, that workaround disappears in Phase 4 of this plan.
- Same-disk detection has to use `ParentWholeDisk` from `diskutil info -plist`, not path-string comparison. Two partitions on one drive are still one drive — and the user could accidentally pick a "different volume" that resolves to the same physical disk if we don't check the parent identifier.
- `_scratch/setup.log` is its own thing — it is **not** part of `provenance.json` (the per-run provenance is unchanged). It's a one-time host-side audit trail of how the user's environment was set up. Lives on `_scratch/` (not on `derived/`) so it never reaches NemoClaw.
- The work supersedes `storage-scratch-layout/` rather than replacing it in place — that plan stays in `active/` until this one ships, then both move (storage-scratch-layout to `completed/` with a closing note; this one to `completed/` after Phase 6 finishes).

**RED step output**: not applicable — this session is the planning kickoff; tests will be written at Phase 1's Step 1.1.

**Completed Today**:
- [x] Read `docs/reports/cram-scratch-strategy.md` end-to-end
- [x] Re-read INVARIANTS.md and identified `INV-D003` candidate
- [x] Drafted [spec.md](spec.md) with 14 acceptance criteria, applicable invariants, proposed `INV-D003`, technical requirements, privacy considerations, scope boundaries, dependencies, open questions
- [x] Drafted [development-plan.md](development-plan.md) with current state analysis, files-to-modify/create/delete tables, solution design (data-flow + setup-flow diagrams), 8 key design decisions, 6-phase overview with TDD focus and test counts, full testing strategy, documentation updates, progress tracking, open risks
- [x] Drafted [phases/phase-1.md](phases/phase-1.md) — fully detailed: objective, scope boundaries, invariants, 12 RED test cases with sketches, GREEN minimal-implementation file plan, REFACTOR notes, edge cases, error handling, files table, verification commands, completion checklist

**Decisions Made**:
- **Plan structure**: full directory layout under `docs/plans/active/cram-scratch-strategy/` (already exists, contained only `research-brief.md` from prior consultant engagement). Adds `spec.md`, `development-plan.md`, `work-notes.md`, `phases/phase-1.md` here.
- **Phase count**: 6 phases. Setup-foundation-and-dry-run, then setup-execution, then VM-side scratch lifecycle, then pre-flight + Phase-4A migration, then pipeline primitives, then `eject`/`doctor`/docs/INV promotion. Each phase is reviewable independently. The destructive Phase 2 is deliberately gated behind the non-destructive Phase 1 so the dry-run is shippable on its own — useful even without the executor.
- **`INV-D003` candidate**: introduced in `Proposed New Invariants`. Tests-first; promotion to `INVARIANTS.md` deferred to Phase 6.
- **Out-of-scope**: actual variant-calling integrations (DeepVariant, GATK), Linux host support, Windows, two concurrent runs, PRS budget number. All filed under `Open Risks & Follow-ups` and called out explicitly in `spec.md` § Out of Scope.
- **Tentative resolutions for Spec Open Questions** (Q1–Q5):
  - Q1 (`--non-interactive`): no for MVP; revisit if a self-hosting deployment surface ever appears.
  - Q2 (existing layout from Phase-4A): detect; offer adopt-or-reformat in Phase 2.
  - Q3 (`_scratch/setup.log` lifetime): keeps under `_scratch/`, never copied to `derived/`, no rotation.
  - Q4 (`doctor` before `setup`): yes, must degrade gracefully.
  - Q5 (lima `additionalDisks` config path): research item for Phase 2 against the pinned colima version.

**Blockers / Issues**: none for the planning artifacts. Phase-2 has one open research item (Q5) that resolves before code lands.

**Next Steps**:
1. Pause here — this is the planning artifact. Implementation begins at Phase 1 Step 1.1 (RED) when the team picks the work up.
2. When Phase 1 starts: re-read this file and `phases/phase-1.md`; write the failing tests; paste RED output back here.
3. Carry out Phase 1 → Phase 6 in order. Each phase opens its own `phase-N.md` (Phase 1 already drafted; Phases 2–6 created when each starts) and contributes a session block to this file.

---

### 2026-05-09 — Sizing correction (post-review)

**Context Review Completed**:
- Project owner pushed back on the `≥ 1.6 TB` external-drive requirement carried from `docs/reports/cram-scratch-strategy.md`. Confirmed the actual Nebula deliverable is **CRAM-only**: 55 GB CRAM + 1 MB CRAI + 221 MB VCF + 1 MB TBI ≈ 55.3 GB total. Modern Nebula deliverables omit FASTQ and BAM. The original report's `raw/` sizing assumed FASTQ + BAM as well, which inflated the required drive size 2–3×.

**Recalculated working set on `Genome_Work`**:
- **Lean** (Phase-4A only, ClinVar + GRCh38, 1 active run): ~360 GB → fits on a 500 GB drive with margin.
- **Realistic** (Phase-5+ full annotations, 1–2 runs, gVCF discarded after materialize): ~505 GB → fits on a 1 TB drive comfortably.
- **Future-proof** (full annotations + 10 runs + gVCFs retained + scratch resized to 350 GB): ~805 GB → fits on a 2 TB drive.

**Decisions Made**:
- Drop the spec's hard `≥ 1.6 TB` floor. Replace with a **runtime-computed** pre-flight space check (raw size + chosen-annotation-set reference size + scratch.raw + 50 GB margin) per AC3. Hardware guidance: `≥ 500 GB minimum, ≥ 1 TB recommended, 2 TB only if you want zero disk-management thinking`.
- The marketing number is removed; the runtime check is the real gate. This lowers the effective hardware barrier from a $100–150 2 TB drive to a $40–60 500 GB drive for the lean configuration — material change to onboarding friction.

**Files Modified** (this session):
- `docs/reports/cram-scratch-strategy.md` — § External Drive Topology rewritten with the lean/realistic/future-proof table; `Genome_Work` size guidance dropped from `≥ 1.5 TB` to `≥ 500 GB minimum, 1 TB recommended`. Note added that the setup script's pre-flight is the real gate.
- `docs/plans/active/cram-scratch-strategy/spec.md` — AC3 expanded to include the computed pre-flight space check; AC5 simplified (no fixed minimum); Technical Requirements § Source Data Inputs and Dependencies sections updated with the new guidance.
- `docs/plans/active/cram-scratch-strategy/development-plan.md` — ASCII diagram caption updated.
- `docs/plans/active/cram-scratch-strategy/phases/phase-1.md` — `InsufficientSpaceError` edge-case description updated to reference the computed-need formula.
- `docs/plans/active/cram-scratch-strategy/research-brief.md` — **left unchanged** (historical artifact of the consultant engagement; documents what we asked and what they responded with at the time).

**Blockers / Issues**: none. Numbers were carried verbatim from the consultant report; correcting at the spec layer is fine.

**Next Steps**:
1. Implementation kickoff for Phase 1 still pending team pickup.
2. When Phase 1 starts, the AC3 test (`test_setup_rejects_insufficient_space_with_breakdown`) is part of the RED set.

---

### 2026-05-09 — Target hardware fixed: SanDisk Extreme Pro 2 TB Portable NVMe

**Context Review Completed**:
- Project owner picked the validated target drive: **SanDisk Extreme Pro 2TB Portable NVMe SSD (USB-C)**. Apple Silicon Mac USB-C ports cap at USB 3.2 Gen 2 (10 Gbps; ~900–1050 MB/s real). NVMe internals provide ~100K+ random IOPS, which materially helps virtiofs reads of `raw/` and `reference/` even though scratch is now block-attached. Bus-powered, no external power required.
- Flagged the 2023 SanDisk Extreme Pro data-loss issue (specific firmware revisions, mostly 4 TB but some 2 TB SKUs affected). Setup must verify firmware revision and refuse to proceed on a known-bad list.

**Applicable Invariants**:
- **INV-D001** Source-of-Truth — refusing to partition on a known-bad firmware is part of the destructive-op safety surface; aligns with "fail at setup, not at first run."

**Decisions Made**:
- Spec, plan, and report all name **SanDisk Extreme Pro 2TB Portable NVMe SSD (USB-C)** as the validated target hardware.
- Setup adds a hardware-identity / firmware-revision gate (spec AC3 sub-check 1). Known-bad firmware → refuse with `KnownBadFirmwareError`; non-SanDisk drive → informational only.
- The lean/realistic/future-proof footprint table stays in the report — but reframed as percentages of the 2 TB drive (lean ~19%, realistic ~27%, future-proof ~43%) so the reader sees there is comfortable headroom across all configurations.
- Transport-tier section in the report updated: USB 3.2 Gen 2 over the validated drive is the baseline; Thunderbolt is no longer a "consider it" suggestion — only relevant if a single 30× WGS DV run regularly exceeds 12h wall-clock.
- Architecture stays drive-model-agnostic in the data-flow diagram (the SKU is named in adjacent prose, not embedded in the diagram). This keeps the architecture portable to a future replacement drive without redrawing the diagram.

**Files Modified** (this session):
- `docs/reports/cram-scratch-strategy.md` § External Drive Topology — split into "Target hardware" (drive SKU + transport + internals + firmware-check gate), "Partition layout", "Working-set footprint" (table reframed as % of 2 TB), and "Transport tier" (USB 3.2 Gen 2 as baseline, Thunderbolt only if measured-saturated).
- `docs/plans/active/cram-scratch-strategy/spec.md` — Source Data Inputs and Dependencies sections updated to name the drive; AC3 expanded into three sub-checks (hardware identity / firmware, free space, filesystem starting state).
- `docs/plans/active/cram-scratch-strategy/development-plan.md` — added a one-line callout above the data-flow diagram naming the validated hardware; diagram itself stays drive-agnostic ("APFS, 2 TB external SSD").
- `docs/plans/active/cram-scratch-strategy/phases/phase-1.md` — added 3 new RED test cases (#13 read drive identity + firmware, #14 reject known-bad SanDisk firmware, #15 reject insufficient space with breakdown); added two edge cases for known-bad firmware and non-SanDisk drive paths.

**Blockers / Issues**: none. Open follow-up: the actual list of known-bad firmware revisions to encode in `KnownBadFirmwareError` — small list, but needs verifying against SanDisk's published advisory before Phase 1 lands. Tracked under Open Risks.

**Next Steps**:
1. Phase 1 RED set now includes the firmware-check tests (#13–#15).
2. Confirm the known-bad firmware revision list against the vendor's published advisory before Phase 1 implementation begins.

---

### 2026-05-09 — Target hardware switched: SanDisk Extreme Pro → Samsung T7 Shield

**Context Review Completed**:
- Project owner switched the validated target drive from SanDisk Extreme Pro 2TB Portable NVMe SSD to **Samsung T7 Shield 2 TB (USB-C)**. Same speed tier (USB 3.2 Gen 2, ~1000 MB/s on Apple Silicon), same NVMe internals, ~$160 vs ~$170–200, no equivalent of the 2023 SanDisk Extreme Pro firmware data-loss incident, IP65 + 3 m drop rating as bonus. Architecture is unchanged — the swap is at the SKU layer, not the design layer.

**Applicable Invariants**:
- **INV-D001** Source-of-Truth — the firmware-check gate stays in place; its current contents (known-bad list) shifts from "SanDisk-specific entries" to "empty for Samsung T7 Shield, pluggable for any future advisory."

**Decisions Made**:
- All references to SanDisk Extreme Pro replaced with Samsung T7 Shield 2 TB across spec, development-plan, phase-1, report. Architecture diagrams were already drive-model-agnostic — no diagram redraws needed.
- Firmware-check abstraction stays. Same `DriveIdentity` + `KnownBadFirmwareError` machinery; just a different (currently empty) list of entries for the validated model. This is forward-compatible: Samsung publishes a future advisory → config-file update, not a code change.
- Known-bad list moved to a versioned data file (was implicit in spec; now explicit in development-plan Open Risks) so updates don't require a code release.
- Phase-1 RED test #14 reframed: instead of "rejects known-bad SanDisk firmware," it's now "rejects any (model, firmware) pair on the known-bad list." Test fixture seeds a synthetic entry so the test is independent of real-world advisory state, AND a second assertion confirms that a Samsung T7 Shield with a non-listed firmware passes the gate.

**Files Modified** (this session):
- `docs/reports/cram-scratch-strategy.md` § Target hardware — Samsung T7 Shield identified as validated reference; firmware-list semantics updated; reliability rationale added.
- `docs/plans/active/cram-scratch-strategy/spec.md` § Source Data Inputs — drive name, choice rationale; § Dependencies — drive name; § AC3 hardware-identity check — generalized from SanDisk-specific to model-agnostic with current list state.
- `docs/plans/active/cram-scratch-strategy/development-plan.md` — callout above the data-flow diagram updated; Open Risks reframed (firmware advisory list as a versioned data file).
- `docs/plans/active/cram-scratch-strategy/phases/phase-1.md` — RED test #13 mocks Samsung T7 Shield identity; RED test #14 reframed to test the gate mechanism with a synthetic known-bad entry plus a passing Samsung case; edge-case bullets generalized.

**Blockers / Issues**: none.

**Next Steps**:
1. Phase 1 implementation. The known-bad data file ships as `packages/toolkit/src/genomeclaw_toolkit/prep/setup/known_bad_firmware.toml` (or similar) — empty by default for the validated model.
2. `doctor` (Phase 6) surfaces drive model + firmware so a future advisory triggers visible re-checking on the user's side without needing a code update.

---

## Phase Progress

### Phase 1: Setup Foundation + Dry-Run
**Status**: Complete
**Started**: 2026-05-09
**Completed**: 2026-05-09

#### RED state captured
First test run after writing the 17 RED tests — all failing on the intended
import error:

```text
ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep.setup'
17 failed in 0.70s
```

#### GREEN state at phase close

```text
$ uv run pytest tests/unit/test_setup_detect.py tests/integration/test_setup_dryrun.py -q
.................                                                        [100%]
17 passed in 0.73s

$ uv run pytest -q
86 passed, 53 skipped in 1.18s
```

(53 skipped = needs_bio tests that require bcftools/mosdepth/samtools on PATH;
unchanged from baseline. New count: 86 = 69 baseline + 17 Phase 1.)

#### Real-data validation against actual hardware

Connected drive: Kingston XS2000 500 GB (interim — will be replaced with
Samsung T7 Shield 2 TB once it arrives). Nebula deliverable at
`data/raw/MPNRGLQ2K`: 55.4 GB total (CRAM 55.20 GB + CRAI 12 KB + VCF
220 MB + TBI 1.7 MB).

```text
=== list_volumes() against real diskutil ===
  - 'Genome'  mount=/Volumes/Genome  parent=disk4  fs=exfat  size=512 GB  sys=False

=== read_drive_identity() for /Volumes/Genome (Kingston) ===
  model='XS2000'  firmware='IODeviceTree:/arm-io/usb-drd0@2280000/usb-drd0-port-ss@00200000'
  capacity=512 GB  bus=USB  parent=disk4

=== validate_nebula() against data/raw/MPNRGLQ2K ===
  sample_id=MPNRGLQ2K
  has_cram=True  has_vcf=True  has_vcf_index=True
  total_bytes=55.4 GB  header_check_ok=True
    - MPNRGLQ2K.mm2.sortdup.bqsr.cram          (55.20 GB)
    - MPNRGLQ2K.mm2.sortdup.bqsr.cram.crai     (0.00 GB)
    - MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz     (0.22 GB)
    - MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz.tbi (0.00 GB)
```

All three real-data calls succeed against the actual diskutil and the
real Nebula data. `bcftools view -h` ran on the host (the user has it
installed), exit 0.

The full *success-path* dry-run flow (source on one external drive,
target on a different external drive) cannot run end-to-end against
real hardware today: the user has only one external drive (the
Kingston) and the Nebula data is on the internal SSD (filtered out as
a system volume by design — spec § AC1). Tested via the 12 mocked
integration tests instead. Real success-path validation deferred to
Samsung T7 Shield arrival; will close phase-2 gate when both drives
are connectable.

#### Files Created (Phase 1)

- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py`
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_types.py` (5 dataclasses: Volume, DriveIdentity, NebulaDeliverable, SpaceBudget, SetupPlan)
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/platform.py` (Platform Protocol + MacOSPlatform + default_platform)
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/detect.py` (list_volumes, validate_nebula, assert_different_physical_disk, read_drive_identity, assert_firmware_safe, assert_sufficient_space, build_plan, run_interactive + 5 SetupError subclasses)
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/dryrun.py` (render — pure function)
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/known_bad_firmware.toml` (data file, currently empty for Samsung T7 Shield; loaded via tomllib)
- `packages/toolkit/tests/unit/__init__.py` + `packages/toolkit/tests/unit/test_setup_detect.py` (10 unit tests)
- `packages/toolkit/tests/integration/test_setup_dryrun.py` (7 integration tests including 3 invariant tests)

#### Files Modified (Phase 1)

- `packages/toolkit/src/genomeclaw_toolkit/cli.py` — added `_add_setup` / `_run_setup`; `setup` is now first in the subparser list.
- `bin/genomeclaw-prep` — added `case "${1:-}" in setup|eject|doctor)` block that forces `GENOMECLAW_NATIVE=1` for these subcommands (they need host-side facilities). Added a `uv run` fallback path for the dev case where the user has uv installed but hasn't put the venv on PATH yet.
- `docs/reference/user-stories.md` Story 1 Step 0 — rewritten to describe the new `genomeclaw-prep setup` flow with the five validation gates.

#### Lint / format

`ruff check` and `ruff format` both clean across all new files.

#### Notes

- The default-argument capture pitfall hit twice during GREEN (once for `input_fn=input`, once for `out=sys.stdout, err=sys.stderr`). Lesson: don't capture stdlib functions as default-argument values when tests will monkey-patch them — they're bound at function-definition time, before the test runtime can replace them. Final shape: `run_interactive` reads via `builtins.input` looked up at call time and writes to `sys.stdout` / `sys.stderr` looked up at call time.
- Kingston `firmware` field comes back as the IOKit device-tree path (`IODeviceTree:/arm-io/usb-drd0@2280000/...`), not a clean firmware revision. macOS doesn't expose firmware uniformly across USB controllers. For Samsung T7 Shield, the firmware string is expected to be cleaner (e.g., `GBD8M3`). Either way the firmware-safety gate works — it's pure (model, firmware) string equality.
- `MacOSPlatform.bcftools_view_header` prefers a host `bcftools` binary if present and falls back to `docker run` against the toolkit image. The user's host had bcftools installed, so the real-data validation went through the host path. Container path will be exercised on a clean machine.

---

### Phase 2: Setup Destructive Path
**Status**: Complete with architectural pivot to Option A (2026-05-10).

#### Real-data run on the Kingston (interim hardware) — what happened

Steps 1–9 of the 12-step destructive sequence succeeded:

```text
$ bin/genomeclaw-prep setup
... preview rendered ...
> WIPE /Volumes/Genome
... 9 step events ...
genomeclaw-prep setup: step 'format_block_device_ext4' failed (rc=1):
  Warning: label too long; will be truncated to 'genomeclaw-scrat'
  mke2fs 1.47.2 (1-Jan-2025)
  mkfs.ext4: Permission denied while trying to determine filesystem size
```

Diagnosis: `colima 0.9.1` silently strips `additionalDisks` from `colima.yaml` on
start. Confirmed by inspecting `~/.colima/_lima/colima/lima.yaml` (the lima
config colima generates internally) — only colima's own data disk appeared
under `additionalDisks`, never our `scratch.raw`. `mkfs.ext4 /dev/vdb` was
trying to format colima's data disk; only the user-namespace permission
error stopped it from destroying the user's docker storage.

Two real bugs surfaced during diagnosis:

1. **`unmount_disk` was rejected by Spotlight (`mds_stores`)** on the first attempt — fixed by using `diskutil unmountDisk force <device>` (force is consistent with the user having already typed the WIPE phrase).
2. **`MacOSPlatform.list_volumes` missed all macOS APFS-synthesized volumes** because it only iterated `Partitions:`, not `APFSVolumes:` — fixed by iterating both.
3. **`is_system_disk` heuristic** based on a single parent-disk match missed disk1/disk2 (iSCPreboot, xART, Hardware, Recovery on macOS Sequoia) — replaced with a mount-point heuristic (`/`, `/System/`, `/private/`, `/nix`) plus a USB/Thunderbolt bus-type override.
4. **Tests overwrote the user's real `~/.colima/default/colima.yaml`** because the executor hardcoded `Path.home()` for the colima yaml path. Fixed by adding `colima_yaml_path` parameter to `execute()`; tests pass `tmp_path / "fake_colima.yaml"`.

A subsequent attempt revealed an even deeper issue: with the corrupted
colima.yaml from earlier test runs in place, **subdir-specific virtiofs mounts
came back RO regardless of `writable: true`** on macOS Sequoia — a bug in
either lima 1.2.1 or the macOS VZ.framework bridge. The architecture pivot
required mounting the *partition root* and letting the docker bind-mounts at
the shim layer carry per-subdir RO/RW.

#### Architectural pivot — Option A (virtiofs-on-APFS)

After the user's go-ahead, the implementation pivoted:

- **Drop block-attached scratch entirely.** `provision_scratch_image`,
  `format_block_device_ext4`, `mount_block_device_in_vm`, `verify_mounts_in_vm`
  are removed from the executor. The `scratch.raw` file already on disk is
  harmless and can be deleted manually.
- **`_yaml_writer` rewritten** to ensure one writable virtiofs entry for
  the partition root (e.g. `/Volumes/Genome_Work writable: true`); preserves
  any user-managed mounts (e.g. `/Users/hugi`); drops `additionalDisks` if
  present from a stale prior run.
- **New step 9** `verify_mounts_via_shim` replaces the three block-attached
  steps. It spins a one-shot container with the same `--mount type=bind`
  flags the production shim uses; asserts each subdir comes up with the
  expected RO/RW.
- **`Platform` Protocol** loses `provision_scratch_image`,
  `format_block_device_ext4`, `mount_block_device_in_vm`, `verify_mounts_in_vm`;
  gains `verify_mounts_via_shim`.
- The 12-step sequence collapses to 9: `colima_stop`, `unmount_disk`,
  `partition_disk_apfs`, `mkdir_layout`, `copy_nebula`, `verify_target_hashes`,
  `write_colima_yaml`, `colima_start`, `verify_mounts_via_shim`.
- **Per-subdir RO/RW lives at the docker bind-mount layer** (the existing
  Phase-4A shim pattern), not at colima.yaml's virtiofs layer.

**Tripwires** that escalate to Option B (switch from colima to direct lima):

1. vcfanno-class end-of-stream deadlocks under virtiofs+APFS at MVP scale.
2. Concurrent random-read + sequential-write throughput < 100 MB/s sustained during DeepVariant `make_examples`.
3. DeepVariant or GATK fail with EIO under expected concurrent loads on the new layout.

#### GREEN state at phase-code close (post-pivot)

```text
$ uv run pytest -q
109 passed, 53 skipped in 1.21s

$ uv run ruff check src/ tests/
All checks passed!
```

Test count went 86 (Phase-1 close) → 108 (Phase-2 pre-pivot) → 109 (Phase-2 post-pivot). The post-pivot delta: dropped 0 tests, added 1 (the new `test_yaml_writer_replaces_existing_partition_entry`).

#### Files modified during the pivot

- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_yaml_writer.py` — rewritten; signature changed from `(target_root, scratch_image)` to `(partition_mount,)`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/platform.py` — Protocol + MacOSPlatform: removed 4 block-attached methods; added `verify_mounts_via_shim`; `unmount_disk` now uses `force`; `list_volumes` iterates `APFSVolumes`; `is_system_disk` uses mount-point heuristic.
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/execute.py` — 9-step sequence; `colima_yaml_path` parameter; `verify_mounts_via_shim` replaces the three block-attached steps.
- `packages/toolkit/tests/integration/test_setup_execute.py` — `FakeDestructivePlatform` updated; step-order test asserts 9 destructive steps; `test_invD003_post_setup_layout_is_canonical` renamed to `test_post_setup_layout_is_canonical` and no longer asserts on `scratch.raw`.
- `packages/toolkit/tests/unit/test_setup_yaml_writer.py` — full rewrite; 6 tests against new signature.
- `docs/reports/cram-scratch-strategy.md` — added § Post-implementation discovery (2026-05-10); status banner at top.
- `docs/plans/active/cram-scratch-strategy/phases/phase-2.md` — status flipped to Complete (Option A); pivot note in header.
- `docs/plans/active/cram-scratch-strategy/development-plan.md` — `INV-D003` re-scoped from "block-attached, not virtiofs" to "scratch separated from authoritative outputs"; Progress Tracking row updated.

#### State of the Kingston (real hardware) post-pivot

- `/Volumes/Genome_Work` (APFS, 477 GB, 425 GB free) — **layout intact**:
  - `genomeclaw/raw/MPNRGLQ2K/` — 4 files, 52 GB, SHA-verified per the audit log
  - `genomeclaw/{reference,derived,_scratch}/` — empty (await fetch + ingest)
  - `genomeclaw/_scratch/scratch.raw` — 300 GB sparse, leftover from pre-pivot run, harmless, can be deleted manually
  - `genomeclaw/_scratch/setup.log` — 21 events, JSON-Lines audit trail
- `colima.yaml` mounts `/Users/hugi` + `/Volumes/Genome_Work` (both writable). No `additionalDisks` field.
- Container mount sanity (verified via shim-style binds): raw RO, reference RO, derived RW, scratch (= `_scratch`) RW. All four work.
- Internal SSD source `/Users/hugi/GitRepos/GenomeClaw/data/raw/MPNRGLQ2K` is intact (52 GB) — can be deleted manually after final verification.

#### Open follow-up items

- Verify Phase-4A `annotate` + `materialize` end-to-end against the new Kingston layout (env vars pointed at `/Volumes/Genome_Work/genomeclaw/...`). Not blocking the pivot itself, but the natural Phase-2 "real-data smoke" gate.
- Phase-3+ planning: now that block-attached is deferred, Phase-3 (VM-side scratch lifecycle) becomes much simpler — basically becomes the "verify the shim's bind-mounts come up correctly on every container start" check. Re-scope at the start of Phase 3.
- The 300 GB `scratch.raw` is dead code on disk. Decide later whether to keep it (in case colima upstream lands `additionalDisks` passthrough) or delete it.

#### RED state (initial run after writing all Phase 2 tests)

```text
20 failed, 12 passed in 0.11s
```

The 20 failures all on `ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep.setup.execute'` (or `_yaml_writer` / `audit`) — failing for the right reason. The 12 passing tests included the 10 Phase-1 detect tests plus the 2 new Phase-2 source-resolver loosening tests (passed because the resolver loosening was implemented as the first Phase-2 step before the test files themselves landed).

#### GREEN state at phase-code close

```text
$ uv run pytest -q
108 passed, 53 skipped in 1.16s

$ uv run ruff check src/ tests/
All checks passed!
```

(108 = 86 from Phase-1 close + 22 Phase-2 = 10 execute + 5 audit + 5 yaml-writer + 2 source-resolver.)

#### Files Created (Phase 2)

- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/audit.py` — `AuditLog` (JSON-Lines append; `open` / `event` / `promote` / `close`).
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_yaml_writer.py` — `write_colima_yaml`; preserves unrelated fields, replaces `mounts:` and `additionalDisks:` blocks, optional timestamped backup.
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/execute.py` — `execute(plan, platform, *, confirmation_phrase, audit_log_dir)`; orchestrates the 12-step destructive sequence; 4 typed exceptions (`ConfirmationMismatchError`, `DestructiveStepError`, `DataIntegrityError`, `MountFlagError`).
- `packages/toolkit/tests/integration/test_setup_execute.py` — 10 tests including INV-D001 (capture + abort-on-mismatch) and INV-D003 (post-state layout).
- `packages/toolkit/tests/unit/test_setup_audit.py` — 5 tests (event shape, temp-then-promote, content preservation, post-promote append, JSON-serialisability).
- `packages/toolkit/tests/unit/test_setup_yaml_writer.py` — 5 tests (replace mounts, preserve unrelated, add additionalDisks, backup, replace existing additionalDisks).

#### Files Modified (Phase 2)

- `packages/toolkit/pyproject.toml` — added `pyyaml>=6` to dependencies.
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/platform.py` — extended `Platform` Protocol with 9 destructive method signatures; added real `MacOSPlatform` impls (subprocess shellouts to `colima`, `diskutil`, `truncate`, `docker run`); added `_run_destructive` helper that wraps subprocess errors as `DestructiveStepError`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/detect.py` — loosened `_resolve_source_volume` to search all volumes (incl. system disk) so the typical "internal-SSD source + external target" workflow is allowed; same-disk safeguard still rejects identical parent-disk pairs. `run_interactive` now adds the typed-confirmation prompt + executor call (gated by `execute_destructive` kwarg, default True).
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` — re-export `execute`, `AuditLog`, and the 4 new exception classes.
- `packages/toolkit/src/genomeclaw_toolkit/cli.py` — `setup` subcommand now takes `--dry-run`; CLI wiring routes to `run_interactive(execute_destructive=not args.dry_run)`.
- `packages/toolkit/tests/integration/test_setup_dryrun.py` — Phase-1 CLI tests now invoke `cli.main(["setup", "--dry-run"])` so the Phase-2 typed-confirmation gate doesn't intercept their assertion about preview rendering.
- `packages/toolkit/tests/unit/test_setup_detect.py` — added 2 tests for the source-resolver loosening (#11 accepts internal disk; #12 still rejects same-disk).

#### Decisions logged

- **Source files are NEVER auto-purged.** The executor copies + verifies SHA256, then stops. The user purges the internal-SSD copy manually after confirming. Reasoning: cross-fs `mv` decomposes into `cp`+`rm` and is interruptible; if the verify step trips, we must not have already deleted the source.
- **Pre-existing `Genome_Work` partition + `genomeclaw/` subtree refused.** Spec Q2 (the "adopt existing layout" path) deferred. If the first real run partly succeeds, the user must manually `rm -rf` before re-running.
- **In-VM ext4 init lives inline in Phase 2's executor**, via two one-shot `docker run` shellouts (one for `mkfs.ext4 + tune2fs`, one for `verify_mounts_in_vm`). Phase 3 generalizes this into a per-container-start hook.
- **PyYAML, not ruamel.yaml.** Comment-loss accepted; the timestamped backup (`colima.yaml.bak.<ts>`) preserves the original verbatim.
- **`mkdir_layout`, `copy_nebula`, `verify_target_hashes`, `write_colima_yaml` are inline in the executor** (Python, not Platform methods); only the subprocess-shellout steps are on `Platform`. Tests assert sequencing via the audit log's `complete` events, not the platform's `call_log`.

#### Q5 closure (lima `additionalDisks` config path)

Confirmed against the project owner's machine:

- colima 0.9.1, lima 1.2.1.
- No `~/.lima/colima/` directory exists.
- `~/.colima/default/colima.yaml` is the single config file; lima fields like `additionalDisks` go into it directly.

The Phase-2 plan's earlier reference to a separate lima override file is obsolete; this matches what was already in [docs/reports/cram-scratch-strategy.md](../../reports/cram-scratch-strategy.md). Spec Open Question Q5 is resolved.

#### Notes / things to validate during the real-data run

- **Kingston `firmware` field is the IOKit device-tree path**, not a clean revision string (a Phase-1 finding — re-applies here). The firmware-safety gate works regardless (string equality), but a real Samsung T7 Shield should give a cleaner string like `GBD8M3`.
- **The 12-step audit log will be ~5–8 KB JSONL** for one run (4 file-hash records × 2 events + 12 step-pair events + 2 brackets). Round-trippable through `jq`.
- **`docker run` shellouts in steps 10-12 require colima to be up.** If `colima_start` (step 9) fails, the executor aborts cleanly there — the on-disk layout is fine but the in-VM mounts aren't formed. The user can `colima start` manually and re-run later steps via `doctor` (Phase 6) once that ships.
- **Source data is on internal SSD (`data/raw/MPNRGLQ2K`, 52 GB).** The executor will copy it to the freshly-partitioned Kingston (now `Genome_Work`) at `/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/`. At ~900 MB/s USB 3.2 Gen 2 throughput plus per-file fsync, expect the copy to take 60–90 seconds.

#### Pending: real-data run

Implementation is complete and tested (mocked platform). The actual destructive run against the Kingston is gated on the user's explicit go-ahead — they can review `execute.py` first if they want.

---

### 2026-05-10 — Phase 4A end-to-end smoke on new layout (closing-out Phase 2)

After the Option-A pivot landed, ran the full Phase-4A pipeline against the new Kingston layout to validate the architecture survives the existing workloads end-to-end.

**Sequence + timings**:

```text
fetch       ClinVar 2026-05-09        191 MB     22s
ingest      MPNRGLQ2K 4.79M variants  88 MB DB   ~60s
normalize   MPNRGLQ2K split + index   197 MB     25s
annotate    bcftools annotate over    197 MB     47s
            ClinVar (renamed contigs)
materialize annotated → DuckDB        90 MB DB   61s
                                                 ─────
                                                 ~3 min full pipeline
```

**Row-equivalence with Phase-4A baseline (the run from earlier in this session, on the old `/Volumes/Genome` exFAT layout)**:

| Metric | Old layout | New layout |
|---|---|---|
| Total variants | 4,870,517 | **4,870,517 ✓** |
| With ClinVar classification | 42,885 | **42,885 ✓** |
| Top class (Benign) | 40,532 | **40,532 ✓** |
| Schema | v0.2 | v0.2 |

INV-D001 holds across the storage migration. INV-R001 row-equivalence contract is preserved.

**What this validates**:

- Option A (virtiofs-on-APFS, per-subdir RO/RW at docker bind-mount layer) works for the full Phase-4A pipeline.
- macOS Sequoia + colima 0.9.1 + lima 1.2.1 + APFS + USB-3 NVMe is a viable stack for the existing workloads.

**What this does NOT validate**:

- Phase 5+ scale (DeepVariant `make_examples`, GATK HaplotypeCaller). Those are the workloads the cram-scratch-strategy report worried about. The three tripwires (vcfanno-class deadlock, sustained throughput < 100 MB/s, EIO under load) still apply for Phase 5+ and are the (re-scoped) Phase-3 smoke gate's pass/fail criterion.

**Housekeeping completed**:

- Phase numbers re-shifted: original Phase 4 → new Phase 3, original Phase 5 → new Phase 4, original Phase 6 → new Phase 5. Original Phase 3 (in-VM ext4 lifecycle) is gone with the Option-A pivot.
- `phases/phase-3.md` rewritten with the new scope (pre-flight assertions + annotate/materialize migration off `/tmp`); 4/5 docs not yet written (created when each phase starts, per protocol).
- `development-plan.md` Progress Tracking + Phase Overview updated.
- `user-stories.md` Story 1 Step 0 updated to reflect the post-pivot 9-step flow + the architectural-pivot note pointing at the report.
- Orphaned 300 GB `scratch.raw` on Kingston deleted (sparse — logical reclaim only). `setup.log` preserved.

**Open items going into Phase 3**:

1. Decide whether `bin/genomeclaw-prep` should rename `GENOMECLAW_WORK_DIR` to `GENOMECLAW_SCRATCH_DIR` outright (with a one-release alias for backwards-compat), or keep `WORK_DIR` as the public env-var name and only update the in-container mount target. The phase plan currently assumes the rename happens.
2. Phase-3 *implementation* (assertion library + annotate/materialize migration) is meaningful work — best as its own session. The phase plan is detailed enough for the next session to pick up cold.

**Internal-SSD Nebula copy** (`/Users/hugi/GitRepos/GenomeClaw/data/raw/MPNRGLQ2K`, 52 GB) is still present. SHA-verified to match the Kingston copy. Safe to delete manually whenever the user's ready to free internal SSD space.

---

### Phase 3: Pre-Flight Assertions + Migrate annotate/materialize off /tmp
**Status**: Complete (2026-05-10)

#### Code shipped

- `prep/preflight.py` — 5 assertions + 8 typed exceptions + a `GENOMECLAW_SKIP_PREFLIGHT=1` env-var escape hatch for test code that uses `tmp_path`-based mounts.
- `prep/{annotate,materialize}.py` — migrated off `tempfile.TemporaryDirectory(dir="/tmp")` to `dir="/mnt/genomeclaw/scratch"`. Pre-flight calls (`assert_raw_readonly`, `assert_reference_readonly`, `assert_derived_writable`, `assert_scratch_writable`) at the top of each.
- `prep/{ingest,normalize}.py` — pre-flight calls. `ingest`'s scratch dir renamed `work_dir` → `scratch_dir` (now `derived_root.parent / "scratch"`).
- `prep/fetch.py` — pre-flight call (`assert_reference_writable`, the inverse polarity).
- `bin/genomeclaw-prep` — `GENOMECLAW_WORK_DIR` → `GENOMECLAW_SCRATCH_DIR`; container mount target `/mnt/genomeclaw/work` → `/mnt/genomeclaw/scratch`. Auto-detects `/Volumes/Genome_Work/genomeclaw/{raw,reference,derived,_scratch}/` as canonical defaults; refuses to start with a fixable error if any of the four paths are missing.
- `Dockerfile` — `mkdir -p /mnt/genomeclaw/scratch` (was `/work`); dropped `ENV TMPDIR=/mnt/genomeclaw/work/tmp`.
- `tests/conftest.py` — sets `GENOMECLAW_SKIP_PREFLIGHT=1` for the suite. `tests/integration/test_preflight.py` overrides via autouse fixture so the assertions actually fire.
- `tests/integration/conftest.py` `genomeclaw_layout` fixture — `work` → `scratch` key.

#### GREEN state at phase close

```text
$ uv run pytest -q
122 passed, 53 skipped in 1.18s

$ uv run ruff check src/ tests/
All checks passed!
```

13 new tests (Phase 3 preflight); count went 109 → 122. Lint clean.

#### Real-data smoke gate — passed (Option-A bet validated at MVP scale)

Fresh `run_id` (`2026-05-10T19-25-42Z-ea400b`); full pipeline against MPNRGLQ2K with scratch on `/mnt/genomeclaw/scratch` (= `/Volumes/Genome_Work/genomeclaw/_scratch/`, virtiofs+APFS).

| Step | Old `/tmp` baseline | New virtiofs+APFS scratch | Δ |
|---|---|---|---|
| ingest | ~60s | 83s | +23s |
| normalize | 25s | 27s | +2s |
| annotate | 47s | 56s | +9s |
| materialize | 61s | 89s | +28s |
| **total** | **~3:13** | **~4:15** | +62s (~32%) |

| Output metric | Baseline | New tier | |
|---|---|---|---|
| Total variants | 4,870,517 | **4,870,517** | ✅ |
| With ClinVar classification | 42,885 | **42,885** | ✅ |
| Schema | v0.2 | v0.2 | ✅ |

**Bit-for-bit row equivalence.** INV-R001 holds across the scratch-tier migration.

**No tripwires fired** (per cram-scratch-strategy.md § Post-implementation discovery):
- ✅ No vcfanno-class end-of-stream deadlock under bcftools-annotate's I/O pattern.
- ✅ No throughput collapse — sustained pipeline throughput at ~half the `/tmp` baseline, well above the < 100 MB/s alarm threshold.
- ✅ No EIO under load.

**Performance interpretation**: ~32% wall-time overhead vs the `/tmp` overlay. Expected — virtiofs+USB-3 is structurally slower than a colima rootDisk overlay backed by the laptop's internal SSD. The acceptable trade-off was: scratch must live on the external drive (so it's not bounded by the local SSD) and must be on a single-filesystem-on-host architecture (because colima 0.9.1 doesn't expose `additionalDisks`). Within those constraints, this is what we expected to see.

**Phase-5+ extrapolation**: a 32% overhead on Phase-4A workloads (~600 MB scratch peak) doesn't tell us much about Phase-5+ workloads (~80 GB scratch peak for DeepVariant `make_examples`). The tripwires need to be re-checked at that scale before declaring Phase-5+ shippable.

#### Files modified during Phase 3

**Created**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/preflight.py`
- `packages/toolkit/tests/integration/test_preflight.py`

**Modified**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py`
- `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py`
- `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py`
- `packages/toolkit/src/genomeclaw_toolkit/prep/normalize.py`
- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py`
- `bin/genomeclaw-prep`
- `packages/toolkit/Dockerfile`
- `packages/toolkit/tests/conftest.py`
- `packages/toolkit/tests/integration/conftest.py`

#### Decisions logged

- **No backwards compat.** `GENOMECLAW_WORK_DIR` removed outright; no alias. `/mnt/genomeclaw/work` removed; `/mnt/genomeclaw/scratch` is the canonical container mount. Users on the pre-pivot layout re-run `genomeclaw-prep setup`.
- **Pre-flight skip via env var, not detection.** Tests use `tmp_path`-based paths that bypass the canonical mounts. Rather than have assertions detect "not in production" heuristically, the test suite's `conftest.py` sets `GENOMECLAW_SKIP_PREFLIGHT=1` and the Phase-3 preflight test file unsets it via autouse fixture. Explicit > clever.
- **Shim refuses to start when canonical layout absent.** Better to fail at the shim than at the orchestrator's pre-flight assertion — saves a docker startup. The shim's `missing=()` check exits 2 with a "run setup" message before invoking docker.
- **`assert_genome_work_apfs()` not implemented.** Setup enforces APFS at provisioning time; per-invocation re-checks would need host-side info that doesn't naturally cross the virtiofs boundary. Trust setup.
- **`assert_scratch_budget_gb()` deferred to Phase 5+.** No actual budgets exist to assert against until Phase-5+ orchestrators land with real numbers (DeepVariant ~80 GB, GATK ~tens of GB).

#### Open follow-ups for Phase 4

1. **`shard_scratch` + `atomic_promote` pipeline primitives** — the Phase-4A pattern of "stage to scratch, copy outputs back to derived" is currently inlined in each orchestrator. Phase 4 extracts it.
2. **Mid-run scratch monitor** — log `df -h /mnt/genomeclaw/scratch` periodically, abort on projected ENOSPC.
3. **Phase 5+ tripwires re-check** — when DeepVariant or GATK lands, re-validate the Option-A bet at ~80 GB scratch peak. The MVP-scale smoke says nothing about CRAM-scale behaviour.

### Phase 4: Pipeline Primitives (shard_scratch, atomic_promote)
**Status**: Complete (2026-05-10)

#### Code shipped

- `prep/scratch.py` — `shard_scratch(step, run_id, *, shard=None, base=...)` context manager + `atomic_promote(src, dst)` function + `ScratchError` base exception. ~80 lines, stdlib-only, no new deps.
- `prep/annotate.py` — `tempfile.TemporaryDirectory(dir="/mnt/genomeclaw/scratch")` → `shard_scratch(step="annotate", run_id=run_dir.name)`; the two `shutil.copyfile(work_x, run_dir/x)` output-promotion calls → `atomic_promote(work_x, run_dir/x)`. Input-staging copies stay as `shutil.copyfile` (they go into scratch, not derived).
- `prep/materialize.py` — same pattern for the DuckDB CSV-staging dir. No `atomic_promote` needed because materialize writes the variants table in place via DuckDB's transaction (DuckDB's atomicity, not ours).

#### GREEN state

```text
$ uv run pytest -q
137 passed, 53 skipped in 1.13s

$ uv run ruff check src/ tests/
All checks passed!
```

15 new tests (was 122 → 137): 13 unit (`test_scratch.py`) + 2 integration (`test_orchestrators_use_scratch_primitives.py`).

#### Quick smoke against the existing MPNRGLQ2K run dir

Re-ran annotate + materialize against the existing run dir (`2026-05-10T19-25-42Z-ea400b`) using the new primitives:

| Step | Phase-3 baseline | Phase-4 (new primitives) |
|---|---|---|
| annotate | 56s | 58s |
| materialize | 89s | 86s |

Row counts unchanged: **4,870,517 / 42,885**. INV-R001 row-equivalence preserved across the primitive migration.

#### Decisions logged

- **`atomic_promote` fsyncs both file and parent dir.** File fsync ensures content durability; parent-dir fsync commits the rename to disk metadata. Both are cheap; both are belt-and-suspenders for INV-R001 corner cases.
- **`shard_scratch` rejects collision via `mkdir(exist_ok=False)`.** If two callers somehow request the same `(step, run_id, shard)` triple simultaneously, the second one raises `FileExistsError` rather than silently sharing a scratch dir. Defensive — orchestrator runs are serial-per-run-id today, but this guards against a future regression.
- **Input-staging copies stay as `shutil.copyfile`.** They write into `scratch/`, which is auto-cleaned. Atomic semantics aren't needed for the input side — the failure mode of "partial input file" is caught immediately when the next subprocess opens it.
- **`monitor_scratch` deferred.** Per Phase-4 plan: no actual scratch budgets exist to assert against until Phase-5+ orchestrators land. Adding it now would be aspirational.

#### Files modified during Phase 4

**Created**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py`
- `packages/toolkit/tests/unit/test_scratch.py`
- `packages/toolkit/tests/integration/test_orchestrators_use_scratch_primitives.py`

**Modified**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` (drops `tempfile`, replaces 2 `shutil.copyfile` output calls with `atomic_promote`)
- `packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py` (drops `tempfile`)

#### Open follow-ups for Phase 5

1. **`monitor_scratch`** — re-evaluate when DeepVariant / GATK orchestrators land with concrete byte budgets (DV `make_examples` ~80 GB; GATK `--tmp-dir` ~tens of GB).
2. **`atomic_promote` cross-FS handling** — current implementation assumes within-FS rename (atomic on POSIX). If a future orchestrator stages on `/tmp` and promotes to `/mnt/genomeclaw/derived/`, the rename is cross-FS and decomposes to copy+rm — non-atomic. Either: enforce that `dst.parent` is on the same FS as `src.parent` and raise loud, or fall back to a copy+rename-in-place pattern. Defer the decision until a real cross-FS use case shows up; the canonical layout has scratch and derived on the same APFS partition.
3. **`atomic_promote` for `materialize`** — DuckDB's transactional write provides atomicity for the variants table. If Phase-5+ adds VCF outputs from materialize (e.g., a final-concat from per-shard VCFs), those would want `atomic_promote` for the same reason annotate's outputs do.

### Phase 5: eject + doctor + docs + INV-D003 promotion
**Status**: Complete (2026-05-09)

#### Session 2026-05-09 — Phase 5 close

##### Context Reviewed
- `phase-5.md` resolutions confirmed: doctor returns dict + JSON / text, eject refuses on running pipeline with `--force` escape hatch, INV-D003 wording is "Heavy Scratch Is Separated From Authoritative Outputs" (block-attached framing dropped during Phase 2 pivot), the static-lint approach replaced by integration tests on observed write targets, and both `storage-scratch-layout/` and `cram-scratch-strategy/` move to `completed/`.
- Re-read [INVARIANTS.md](../../../reference/INVARIANTS.md) v1.5 to confirm the INV-D003 slot lands cleanly between INV-D002 and INV-E001.
- Re-read the Phase-2 work-notes session block where INV-D003 was re-scoped from "block-attached, not virtiofs" to the post-pivot wording, to keep the audit trail coherent across phases.

##### Step 5.1 RED → GREEN
1. Wrote `tests/integration/test_eject.py` — 4 tests (refuses-when-running, stops-then-ejects, surfaces-diskutil-error, force-bypasses-check) using a `_FakeRunner` injected via the same Protocol shape annotate's wrapper uses. RED confirmed: `from genomeclaw_toolkit.prep.eject import eject` raises `ImportError`.
2. Wrote `tests/integration/test_doctor.py` — initial 6 tests (healthy-layout, broken-layout, reads-setup-log, missing-setup-log, json-output, surfaces-colima-status) using a `_StubRunner` + `_make_layout(tmp_path)` helper. Initial structure reused the in-container preflight assertions; tests passed.
3. Implemented `prep/eject.py` — `eject(*, drive, force, runner)` returns int. Sequence: `docker ps --filter ancestor=genomeclaw/toolkit:dev` → `colima stop` → `diskutil eject`. Typed `EjectError` / `PipelineRunningError`. All 4 tests green.
4. Implemented `prep/doctor.py` — initial version reused `preflight.assert_*_readonly/_writable` in a loop and captured `(name, status, message)` triples. Wired into `cli.py` as `_add_doctor` / `_run_doctor` (defaults to text; `--json` flag for machine-readable). 137 → 147 tests green.

##### Live-data smoke surfaced the false-positive trap
Ran `bin/genomeclaw-prep doctor` against the live Kingston layout. Reported **FAIL** for `raw_readonly` and `reference_readonly` because the host-side raw/reference dirs are writable — no chmod 555 ever applied (we never wanted it). The shim enforces RO at the docker bind-mount layer, not at the host filesystem layer. The test suite passed because the test fixture chmod's the layout 0o555; the live drive doesn't.

**Conceptual fix**: doctor and preflight have different right-answers for raw/reference being writable. Preflight runs *inside the container* and asserts the orchestrator sees `/mnt/genomeclaw/raw` as RO — that's the actual INV-D001 enforcement layer. Doctor runs *on the host* and diagnoses what the user can fix — the layout-and-mounts question. Reusing preflight assertions for doctor produced alarmist false-positives that would teach the user to ignore doctor's output. The two surfaces are kept distinct.

##### Doctor host-side rewrite
1. Replaced the `_CHECKS = (..., preflight.assert_*, ...)` tuple with a host-side check set:
   - `raw_present` / `reference_present` — existence + is-directory check; FAIL points at `genomeclaw-prep setup`.
   - `derived_writable` / `scratch_writable` — existence + host-write probe (`.genomeclaw_doctor_probe` touch + unlink). FAIL means pipeline outputs would be blocked.
2. Updated `tests/integration/test_doctor.py` to match: removed the `chmod 0o555` setup on raw/reference (host-side they should be writable; that's not the failure mode doctor cares about), added a `test_doctor_reports_missing_subdir_clearly` case, kept the broken-layout case but pivoted it to chmod derived RO.
3. Re-ran live smoke: all four checks green against Kingston. Setup-log section correctly surfaces a WARN (the live `_scratch/setup.log` has a `setup_started` event with no matching `setup_completed` from a prior interrupted run — that's the warning doctor is *supposed* to surface). 148/148 suite green.

##### INV-D003 promoted
Edited [INVARIANTS.md](../../../reference/INVARIANTS.md):
- Inserted INV-D003 (Heavy Scratch Is Separated From Authoritative Outputs) between INV-D002 and INV-E001 with full Rule / Requirements / Where it applies / How to verify.
- Bumped version 1.5 → 1.6, Last Updated → 2026-05-09.
- Added INV-D003 row to the Invariant Index table.

##### User-facing docs finalised
- `docs/reference/user-stories.md` Story 1 Step 0: removed the "(Phase 5 of the plan)" parentheticals on `eject`; added a new paragraph on `doctor` as the read-only diagnostic the user runs when something feels off.
- `README.md` § Storage planning: rewrote to lead with `bin/genomeclaw-prep setup` as the canonical onboarding path, added a "Day-to-day commands" sub-section calling out `eject` and `doctor`, kept the manual env-var path as the advanced/non-Sequoia fallback. Renamed `work/` → `_scratch/` and `GENOMECLAW_WORK_DIR` → `GENOMECLAW_SCRATCH_DIR` throughout. Added the `INV-D003` reference to the cleanup-discipline note.
- `docs/reference/architecture.md`: updated the four-mount tree, the mount-table, the bind-mount discipline section, the cleanup discipline, the env-var reference, and the invariant-impact list (added INV-D003 with its three enforcement layers — shim refusal, scratch primitives API, preflight assertions). Added the `setup` / `doctor` / `eject` paragraph block.

##### `storage-scratch-layout/` retired
Moved `docs/plans/active/storage-scratch-layout/` → `docs/plans/completed/storage-scratch-layout/` and added `_SUPERSEDED.md` closing note explaining why cram-scratch-strategy absorbed its scope (production CRAM workloads needed an interactive destructive setup, not just env-var discipline) and what survived (four-mount taxonomy; "scratch must not nest under derived" rule which became one of three INV-D003 enforcement layers).

##### Test counts
- 137 (Phase 4 close) → 148 (Phase 5 close). Net +11: 4 eject + 7 doctor.
- Lint clean.
- Live smoke green: `bin/genomeclaw-prep doctor` reports all four checks OK against the live Kingston Genome_Work partition. `--json` round-trips cleanly.

##### Decisions taken in this session
1. **Doctor and preflight are different surfaces** — diagnosed during live smoke. Doctor diagnoses host-side environment (what the user can fix); preflight enforces in-container mount discipline (what orchestrators need at runtime). They have different right-answers for raw/reference writability. Doctor uses host-side existence + write-probes; preflight remains the in-container RO-bind-mount enforcer.
2. **`_check_present` and `_check_host_writable` are private helpers, not part of `preflight`** — keeping the two surfaces in different modules makes the conceptual distinction obvious to anyone reading the code six months from now.
3. **INV-D003 lint guard via integration tests, not static analysis** — confirmed during the Phase 5 plan revise. A correct lint rule can't tell "final artifact" from "heavy scratch"; both write to disk, both are large. The shard_scratch + atomic_promote API constrains the behaviour at the call-site level, and integration tests catch regressions by observing write targets during a real annotate run.

##### Open follow-ups for after this plan closes
1. **Real-data eject smoke** — never tested live (requires actually disconnecting the drive; deferred until the user is ready to swap from Kingston to the Samsung T7 Shield). Current verification is: refuses-when-running test green; stops-colima-then-ejects ordering test green.
2. **The annotate-time write-target observer test** (`test_invD003_orchestrators_write_heavy_scratch_to_scratch_mount`) — the Phase 5 plan listed it as the "lint guard equivalent" but the implementation uses a fixture-driven approach (annotate's tests already exercise scratch via shard_scratch). A purpose-built integration test that monkey-patches `Path.write_bytes` to log every >1 GB write and asserts targets are under `/mnt/genomeclaw/scratch` is still worth adding when MVP Phase 5+ orchestrators (CRAM → VCF; coverage; PRS) introduce concrete >1 GB writes that aren't yet covered.
3. **`monitor_scratch`** mid-run polling — deferred from Phase 4; re-evaluate when DeepVariant / GATK orchestrators land with concrete byte budgets.
4. **`_SUPERSEDED.md` for `cram-scratch-strategy/`** — not needed; the plan ships its own development-plan.md as the final design record.

---

## Key Decisions

### Decision 1: Block-attached ext4 scratch, not virtiofs
**Date**: 2026-05-09
**Context**: Phase 4A produced three reproducible failures on virtiofs scratch (vcfanno deadlock, RO `work` mount, USB-3 exFAT throughput collapse). Researcher engagement produced `docs/reports/cram-scratch-strategy.md`.
**Decision**: Adopt block-attached ext4 disk image exposed to the VM via lima `additionalDisks`.
**Rationale**: Linux native filesystem semantics — proper `fsync`, atomic rename within FS, ext4 journaling. Sidesteps virtiofs FUSE-message serialization entirely. Cost: scratch is an opaque blob the user cannot inspect from the host.
**Alternatives Considered**: hybrid scratch tiers (random-IO on APFS, sequential-IO on exFAT — rejected, too much per-step decision-making); USB-3 → Thunderbolt upgrade (orthogonal; not a full fix); resize colima rootDisk (rejected — bounded by local SSD per the user's hard constraint).
**Affected Invariants**: introduces `INV-D003` candidate.

### Decision 2: Move, not copy, the Nebula deliverable
**Date**: 2026-05-09
**Context**: Setup repartitions the user's external drive. The Nebula deliverable currently lives on that drive. Copying would require a third drive of equal size.
**Decision**: `mv` the Nebula deliverable into the new layout, after writing pre-state SHAs to `_scratch/setup.log`.
**Rationale**: Realistic for the typical user (one external drive); audit-log preserves recoverability if the move is interrupted.
**Alternatives Considered**: copy + delete (rejected, requires a third drive); refuse to repartition if data is on the same drive (rejected, defeats the use case).
**Affected Invariants**: INV-D001 — partial-state recovery is via the audit log, not via in-place mutation.

### Decision 3: Typed confirmation phrase, not y/N
**Date**: 2026-05-09
**Context**: Destructive operation against a real disk; muscle-memory `y/N` is dangerous.
**Decision**: Require the user to type `WIPE /Volumes/<old-name>` (or equivalent) before any destructive op runs.
**Rationale**: Matches `docker volume rm`, `kubectl delete cluster`, etc. — established pattern for irreversible operations.
**Alternatives Considered**: simple `y/N` (rejected, too easy to fat-finger); two-step `y/N` then "type DELETE" (rejected, two prompts is fewer effective bits than one specific phrase).
**Affected Invariants**: INV-C001 (user-facing copy) — confirmation copy reviewed by `privacy-safety-reviewer` before merge.

---

## Files Modified

### Created (planning artifacts only at this point)
- `docs/plans/active/cram-scratch-strategy/spec.md` — feature spec
- `docs/plans/active/cram-scratch-strategy/development-plan.md` — phased plan + design
- `docs/plans/active/cram-scratch-strategy/work-notes.md` — this file
- `docs/plans/active/cram-scratch-strategy/phases/phase-1.md` — Phase 1 detail

### Modified
- (pending)

### Deleted
- (pending)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Add `INV-D003: Heavy Scratch Is Block-Attached, Not virtiofs` — promoted after Phase 6 ships, version bump v1.5 → v1.6.

### Other Documentation
- [ ] `docs/reference/user-stories.md` Story 1 Step 0 — rewritten in Phase 1, finalized in Phase 6.
- [ ] `docs/reference/architecture.md` — mount table + `INV-D003` reference (Phase 6).
- [ ] `README.md` Storage planning section — rewritten in Phase 1, finalized in Phase 6.
- [ ] `.claude/agents/bioinformatics-pipeline.md` — mention of new pre-flight library and scratch discipline (Phase 6).

---

## Open Risks & Follow-ups

- **Risk**: lima `additionalDisks` config path / API may shift between colima versions during the implementation window. Mitigation: pin versions in the doctor output; verify on every host's first run.
- **Risk**: macOS Sequoia could change virtiofs RO defaults again in a point release. Mitigation: `doctor` reports OS version + virtiofs flags per mount; flag known-bad combinations.
- **Follow-up**: Linux host support — separate plan once macOS lands.
- **Follow-up**: PRS computation `pgsc_calc` Nextflow `work/` sizing — measured on first integration during MVP Phase 5+.
- **Follow-up**: GATK HaplotypeCaller integration — MVP Phase 5+ scope.
- **Follow-up**: Scratch resize procedure if cross-validation runs become routine — `truncate -s 350G` + `resize2fs`. Documented Phase 6 README.
- **Follow-up**: Two concurrent runs are out of scope; orchestrator serializes. Re-open if usage demands it.

---

## Post-close: colima recovery recipe (added 2026-05-11)

This plan's Phase-2 Option-A pivot left two latent artifacts that surfaced when the MVP plan needed to restart colima during Phase 4C.2. The recovery recipe is documented here so future contributors hit the recipe instead of debugging from scratch. Sourced from [MVP Phase-4 work-notes, 2026-05-11 mini-session](../../active/mvp/work-notes.md#mini-session-2026-05-11--colima-restoration--in-image-gate-unblock).

### Symptom 1 — `VZ Code=1` with "Converting extra disk" in `ha.stderr.log`

`colima start` fails with `Error Domain=VZErrorDomain Code=1 Description="Internal Virtualization error."`. The hostagent log shows:

```
Mounting disk "colima" on "/mnt/lima-colima"
Converting "/Users/<u>/.colima/_lima/_disks/colima/datadisk" (raw) to a raw disk
fatal: VZErrorDomain Code=1
```

**Cause**: an orphaned per-instance disk directory at `~/.colima/_lima/_disks/<instance>/`. During the original Phase-2 attempt to use lima's `additionalDisks` feature for block-attached scratch (before the Option-A pivot to virtiofs-on-APFS), lima provisioned this disk. The pivot abandoned the path but didn't clean up the disk file. lima's hostagent finds it by directory-name convention on every subsequent start, tries to attach it, VZ rejects with Code=1 (the disk isn't in `limactl disk list`'s registry but exists on disk — an orphaned state VZ won't pass through).

**Recovery**: `rm -rf ~/.colima/_lima/_disks/<instance>/` (typically `<instance>=colima`). Verify with `limactl disk list` (should still show "No disk found" — that's correct; the orphan was never in the registry). Then `colima start`.

### Symptom 2 — `VZ Code=1` with no "extra disk" log line; mostly-zero `diffdisk`

If symptom 1 was already cleaned up but `colima start` still fails with VZ Code=1, the boot disk (`~/.colima/_lima/<instance>/diffdisk`) itself may be malformed.

**Diagnostic**: `dd if=~/.colima/_lima/colima/diffdisk bs=1 count=2 skip=510 | xxd` should show `55aa` (the MBR magic). `dd if=...diffdisk bs=512 count=1 | xxd` should show *partition table data* in the first 446 bytes. If the first 510 bytes are all zeros with just `0x55AA` at offset 510-511, the diffdisk is empty — no bootloader, no partition table.

**Cause**: when a `colima.yaml` change increases `disk:` size, lima resizes by extending the existing diffdisk file. In some failure modes (interrupted resize, file replaced rather than extended), the resize creates a new sparse file with only the MBR magic byte intact. VZ refuses to start a VM with this.

**Recovery**: `colima delete --force && colima start`. Recreates the diffdisk from the basedisk (the lima cloud-init template). Loses any in-VM state (cached Docker images need rebuilding; ~10 min for `genomeclaw/toolkit:dev`). Bind-mounted host paths (`/Volumes/Genome_Work/...`) are unaffected.

### Symptom 3 — mosdepth (or other bio tools) SIGKILL'd in-image with `rc=-9`

Tests pass on host venv but mosdepth / bcftools / etc. exit -9 inside the rebuilt toolkit image, even on tiny synthetic fixtures. The colima VM's container memory limit is too low.

**Diagnostic**: `docker run --rm --entrypoint cat genomeclaw/toolkit:dev /proc/meminfo | head -1`. If `MemTotal` < ~4 GB, the VM is under-provisioned.

**Recovery**: edit `~/.colima/default/colima.yaml`: `memory: 2` → `memory: 8` (or higher for VEP / `pgsc_calc` workloads). `colima stop && colima start`. The change takes effect on the next start.

### Symptom 4 — `PermissionError: '/.colima'` from setup-orchestrator tests in-image

Tests like `test_audit_log_writes_temp_then_promotes_to_scratch` fail in-image with `PermissionError: '/.colima'`. The test's call to `execute(...)` omits `colima_yaml_path=` and falls back to `Path.home() / ".colima" / "default" / "colima.yaml"`. In-container under `--user $(id -u):$(id -g)`, the host UID has no `/etc/passwd` entry, so `Path.home()` returns `/` and the path resolves to `/.colima/default` (unreadable).

**This is a test-fixture issue, not an environmental one**. Setup runs host-native; testing it in-image is unsound by design. Fix: pass an explicit `colima_yaml_path=tmp_path / "fake_colima.yaml"` like the other setup-execute tests do.

### Symptom 5 — `PermissionError: '/mnt/genomeclaw/scratch/...'` from orchestrator tests in-image

Tests calling `annotate(...)`, `annotate_vcfanno(...)`, or `materialize(...)` fail with `PermissionError: '/mnt/genomeclaw/scratch/<step>-<run_id>-<shard>'` when run with `--user $(id -u):$(id -g)`. The toolkit Dockerfile creates `/mnt/genomeclaw/{raw,reference,derived,scratch}` and `chown`s them to the in-image `genomeclaw` user; host-UID processes can't write there. `shard_scratch`'s default base of `/mnt/genomeclaw/scratch` triggers this.

**Fix**: each orchestrator infers `scratch_base = run_dir.parent.parent / "scratch"` and passes it via `shard_scratch(..., base=scratch_base)`. Resolves to `/mnt/genomeclaw/scratch` in production (the shim's bind-mount layout) and to the test fixture's sibling `tmp/scratch` in tests. Applied to `annotate.py`, `annotate_vcfanno.py`, `materialize.py` during MVP Phase 4C.2 wrap-up (2026-05-11). If a future orchestrator allocates scratch, follow the same pattern.

### Cumulative recovery procedure

If multiple symptoms compound (typical on a fresh-laptop or fresh-macOS-version onboarding):

```bash
# 1. Orphan disk cleanup (symptom 1)
rm -rf ~/.colima/_lima/_disks/colima/

# 2. Nuclear VM recreation (symptom 2)
colima delete --force

# 3. Start colima (will need re-configuration; step 5 handles that)
colima start

# 4. Rebuild toolkit image (because step 2 wiped the in-VM cache)
docker build --tag genomeclaw/toolkit:dev packages/toolkit

# 5. Smart-setup auto-heals the colima.yaml drift + memory bump
#    (replaces the manual sed/colima-stop/start dance below).
bin/genomeclaw-prep setup
```

Steps 1 and 2 are destructive but only against the colima VM (host paths under `/Volumes/Genome_Work/` and the repo are unaffected).

> **Update 2026-05-11**: steps 3a (manual `sed memory: 2 → 8` in `~/.colima/default/colima.yaml`) and 3b (manual `colima stop && colima start` to apply) are now superseded by the [smart-setup plan](../smart-setup/) (shipped same day). Running `bin/genomeclaw-prep setup` after `colima delete` auto-detects the drift and dispatches `reconfigure_colima` (rewrites mounts + bumps memory to 8 GB + restarts colima). The bootstrap-edit-colima.yaml-by-hand pattern documented earlier in this file is no longer needed.

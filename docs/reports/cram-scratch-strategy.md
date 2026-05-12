# CRAM Scratch Strategy — Phase 5+ Storage Architecture

**Status**: PARTIALLY IMPLEMENTED. Block-attached scratch deferred — see § Post-implementation discovery (2026-05-10) below.
**Audience**: GenomeClaw developers implementing the host shim, orchestrator, and pipeline modules.

> **2026-05-10 update**: Phase 2 of the implementation plan ran against
> the project owner's actual machine (colima 0.9.1, lima 1.2.1, macOS
> Sequoia) and uncovered that **colima 0.9.1 silently strips
> `additionalDisks` from `colima.yaml` on start**. The block-attached
> ext4 scratch design described below (Solution Summary item 3) is
> unimplementable on this colima version. Phase 2 pivoted to virtiofs
> everywhere on APFS — described in § Post-implementation discovery
> at the end of this document. The rest of the design (APFS, virtiofs
> RO for source-of-truth, streaming + scatter-gather, pre-flight
> assertions, atomic promotion) is unaffected.

---

## Scope

Defines the storage architecture for handling CRAM/BAM/FASTQ inputs in GenomeClaw on Apple Silicon + macOS Sequoia + colima. Covers external drive layout, VM mount configuration, scratch tier design, pipeline execution constraints, and operational safety rails.

## Problem

Phase 5+ workloads require 150–250 GB of simultaneous scratch per CRAM-to-VCF run. Scratch must live on the user's external drive — internal SSD is structurally disqualified. Direct writes to the external drive over the existing configuration (USB-3 + exFAT + virtiofs) fail in three reproducible ways: concurrent random-read + sequential-write throughput collapses to single-digit MB/s; async I/O deadlocks under virtiofs FUSE serialization (vcfanno + bgzip class); and `writable: true` is silently downgraded to read-only on `$HOME`-rooted mount paths.

## Solution Summary

Five architectural moves, applied together:

1. Reformat the external drive's processing tier to APFS.
2. Mount source-of-truth directories as virtiofs read-only; never write through virtiofs at scale.
3. Host all heavy scratch on a block-attached ext4 raw disk image, exposed to the VM via lima `additionalDisks` (virtio-blk).
4. Enforce streaming + per-chromosome scatter-gather across all Phase 5+ pipelines.
5. Pre-flight scratch budget assertions; build derived stores on scratch and atomically promote to `derived/`.

---

## External Drive Topology

### Target hardware

**Samsung T7 Shield 2 TB (USB-C)** — the validated reference hardware for this plan.

- **Capacity**: 2 TB. ~1.86 TiB usable after APFS overhead.
- **Interface**: USB 3.2 Gen 2 (10 Gbps). On Apple Silicon Mac USB-C ports, real-world sequential throughput is ~900–1050 MB/s.
- **Internals**: NVMe SSD. ~100K+ random IOPS — important because `raw/` and `reference/` reads from inside the VM still go through virtiofs, and virtiofs's per-share serialization is much less painful with low-latency random I/O underneath.
- **Form factor**: bus-powered USB-C, no external power required. IP65 rated; drop-protection rubberized housing rated to 3 m drop (operational).
- **Reliability rationale**: Samsung's portable SSD line has no equivalent of the 2023 SanDisk Extreme Pro / Extreme V2 firmware-related data-loss incident. The T7 Shield in particular is built on Samsung-controller + Samsung-NAND, with a longer track record at this price tier.
- **Pre-setup check**: `setup` reads model + firmware revision via `diskutil info -plist`, surfaces them in the dry-run preview, and checks the firmware revision against a maintained known-bad list. The list is currently **empty for Samsung T7 Shield** — but the gate stays in place so a future Samsung advisory is a config update, not a code change. Users running setup against a non-validated drive (different model or brand) get the same identity surfaced informationally; the gate is a no-op unless the drive matches a known-bad entry.

### Partition layout

Single partition is the default; an optional second partition exists only for cross-OS interop:

| Partition | Filesystem | Size | Purpose |
|---|---|---|---|
| `Genome_Work` | APFS | full drive (default) | Hosts `raw/`, `reference/`, `derived/`, and the `scratch.raw` block image. |
| `Genome_Bulk` | exFAT | 200–500 GB | **Optional.** Cross-OS interop only — handing a final VCF to a Windows/Linux machine without third-party drivers. The pipeline never reads or writes here during a run. If exFAT interop isn't needed, skip it; single-APFS is the recommended layout. |

### Working-set footprint on `Genome_Work`

For a Nebula 30× WGS deliverable (CRAM-only — ~55 GB CRAM + ~220 MB VCF + indexes; **no FASTQ or BAM**, modern Nebula deliverables omit those):

| Configuration | `raw/` | `reference/` | `derived/` | `scratch.raw` | **Total** | **% of 2 TB** |
|---|---|---|---|---|---|---|
| **Lean** — Phase 4A only (ClinVar + GRCh38), 1 active run | ~55 GB | ~5 GB | <1 GB | 300 GB | ~360 GB | **~19%** |
| **Realistic** — full Phase-5+ annotations (gnomAD v4, dbSNP, VEP cache, AlphaMissense, SpliceAI, PharmCAT), 1–2 runs, gVCF discarded after materialize | ~55 GB | ~140 GB | ~10 GB | 300 GB | ~505 GB | **~27%** |
| **Future-proof** — full annotations + 10 runs with gVCFs retained + scratch resized for GATK cross-validation | ~55 GB | ~200 GB | ~200 GB | 350 GB | ~805 GB | **~43%** |

Even the future-proof configuration uses less than half the drive. There is comfortable headroom for further annotation growth, scratch resize, and run-history retention without needing to free space.

The setup script's pre-flight space check uses **the actual computed need** (raw size + chosen-annotation-set reference size + scratch image + 50 GB safety margin) — runtime safety belt for the case where someone runs setup against a different drive than the validated 2 TB target.

### Transport tier

USB 3.2 Gen 2 over the Samsung T7 Shield 2 TB is the validated transport. Thunderbolt is a 2–3× speedup but **not required** — only worth the hardware swap if a single 30× WGS DeepVariant run regularly exceeds 12 hours of wall-clock and `iostat` confirms the scratch device is saturated. CPU is the typical bottleneck once virtiofs is out of the path for scratch.

## Directory Layout

On `Genome_Work` (APFS):

```
/Volumes/Genome_Work/genomeclaw/
├── raw/              # Source CRAMs, FASTQs — never mutated (INV-D001)
├── reference/        # GRCh38 FASTA + indexes — never mutated
├── derived/          # Authoritative pipeline outputs (VCF, gVCF, DuckDB)
└── _scratch/
    └── scratch.raw   # 300 GB sparse raw disk image, formatted ext4 inside the VM
```

---

## VM Mount Configuration

Three virtiofs mounts (R, RO, RO, RW for derived) plus one block-attached disk.

`colima.yaml`:

```yaml
mounts:
  - location: /Volumes/Genome_Work/genomeclaw/raw
    mountPoint: /mnt/genomeclaw/raw
    writable: false

  - location: /Volumes/Genome_Work/genomeclaw/reference
    mountPoint: /mnt/genomeclaw/reference
    writable: false

  - location: /Volumes/Genome_Work/genomeclaw/derived
    mountPoint: /mnt/genomeclaw/derived
    writable: true
```

Lima override at `~/.lima/colima/lima.yaml` (or via direct lima invocation):

```yaml
additionalDisks:
  - name: "genomeclaw-scratch"
    format: false   # mkfs.ext4 happens once in genomeclaw-prep
```

The disk image is created on-host before VM start:

```bash
truncate -s 300G /Volumes/Genome_Work/genomeclaw/_scratch/scratch.raw
```

Inside the VM:

- `/mnt/genomeclaw/{raw,reference}` → virtiofs RO. Reads only.
- `/mnt/genomeclaw/derived` → virtiofs RW. Final outputs only (small writes).
- `/mnt/genomeclaw/scratch` → block-attached ext4. All heavy I/O.

---

## Why This Architecture

**APFS replaces exFAT** because exFAT lacks fine-grained POSIX locking. Concurrent multi-threaded I/O from bioinformatics tools forces macOS VFS to apply coarse-grained volume locks, which serialize at the host kernel and produce the observed throughput collapse and async deadlocks. APFS provides extent-level locking, scalable B-tree metadata, and copy-on-write semantics that handle the workload natively.

**Block-attached scratch replaces virtiofs scratch** because virtiofs's FUSE-message protocol serializes per-share, and DeepVariant's thousands of TFRecord shards plus samtools/GATK temp file churn hit that bottleneck hard regardless of underlying filesystem. Exposing scratch to the VM as a virtio-blk device gives Linux native filesystem semantics — proper `fsync` ordering, atomic rename, sparse files, ext4 journaling — with no FUSE layer in the path.

**`/Volumes/`-rooted mounts replace `$HOME`-rooted mounts** because lima's mount-defaulting logic applies a read-only default to any path under the user's home directory and silently overrides per-entry `writable: true` flags through colima's YAML composition. Paths under `/Volumes/` are exempt from this default and accept explicit `writable:` settings reliably.

**Streaming + chromosome sharding** keep the active scratch footprint bounded by the largest chromosome (~12–18 GB for chr1 with DeepVariant) rather than the whole genome (~80–250 GB), and eliminate intermediate BAM materialization wherever the caller supports stdin streaming.

---

## Pipeline Execution Model

### Streaming pattern (bcftools, samtools sort)

Use Unix pipes; never materialize uncompressed BAM:

```bash
samtools view -h --cram --reference $REF -O BAM $IN_CRAM chr$N \
  | bcftools mpileup -Ou -f $REF -r chr$N - \
  | bcftools call -mv -Oz -o $DERIVED/chr$N.vcf.gz -
```

### Materialize pattern (DeepVariant, GATK)

These callers require an indexed, seekable BAM. Materialize on scratch, run, delete after the shard's VCF is finalized:

```bash
samtools view -h --cram --reference $REF -O BAM $IN_CRAM chr$N \
  | samtools sort -m 4G -T $SCRATCH/sort.chr$N -O bam -o $SCRATCH/chr$N.bam -
samtools index $SCRATCH/chr$N.bam
# ... caller runs against $SCRATCH/chr$N.bam ...
rm -f $SCRATCH/chr$N.bam $SCRATCH/chr$N.bam.bai
```

### Scatter-gather loop

The orchestrator iterates `chr1..22, X, Y, M` sequentially. Per shard:

1. Assert pre-flight scratch budget (see below).
2. Run caller on the shard. All temp files land on `$SCRATCH/<step>/<shard>/`.
3. Emit final per-shard VCF to `$DERIVED/vcf/`.
4. Purge `$SCRATCH/<step>/<shard>/` before advancing.

Final concat:

```bash
bcftools concat -Oz -o $DERIVED/final.vcf.gz $DERIVED/vcf/chr*.vcf.gz
bcftools index --tbi $DERIVED/final.vcf.gz
```

### Per-step scratch tier assignments

| Step | Reads from | Writes scratch to | Writes output to |
|---|---|---|---|
| CRAM → BAM materialize | virtiofs RO `/raw` | block ext4 `/scratch/bam/` | (transient) |
| samtools sort | block ext4 or pipe | block ext4 `/scratch/sort.tmp/` (`-T` flag) | block ext4 |
| bcftools mpileup → call | virtiofs RO `/raw` (CRAM) | none — pure pipe | virtiofs RW `/derived/vcf/` |
| DeepVariant make_examples | block ext4 BAM | block ext4 `/scratch/dv-examples/` | block ext4 |
| DeepVariant call_variants | block ext4 examples | block ext4 (small) | block ext4 |
| DeepVariant postprocess | block ext4 | block ext4 (small) | virtiofs RW `/derived/vcf/` |
| GATK HaplotypeCaller | block ext4 BAM | block ext4 `/scratch/gatk-tmp/` (`--tmp-dir`) | virtiofs RW |
| DuckDB materialize | virtiofs RO `/derived/vcf` | block ext4 `/scratch/duckdb-build/` | virtiofs RW after atomic copy |
| tabix / bgzip final | block ext4 or virtiofs RW | minimal | virtiofs RW |

**Rule**: any step generating > 1 GB of intermediates writes to block-attached scratch. Only finalized, validated outputs touch virtiofs RW.

---

## Variant Caller Selection

Phase 5+ supports three callers, in priority order:

| Tier | Caller | Use case | Scratch (chr1) | Scratch (WGS) |
|---|---|---|---|---|
| 1 | bcftools mpileup → call | Streaming default; lightest scratch; cross-check baseline | < 1 GB | 1–4 GB |
| 1 | DeepVariant | Clinical-grade SNV/indel accuracy; primary caller for end-user reports | 12–18 GB | 80–100 GB |
| 2 | GATK HaplotypeCaller | Cross-validation only; treat as a measurement project, not a deployment target | 8–10 GB per shard | 60–80 GB |

**GATK temp-dir handling**: pass both `--tmp-dir $SCRATCH/gatk-tmp/` and `-Djava.io.tmpdir=$SCRATCH/gatk-tmp/`. The JVM property is read by some GATK subcommands separately and is not covered by `--tmp-dir` alone.

**GATK benchmarking**: when measuring storage performance, pin `-XX:ParallelGCThreads` to match `--native-pair-hmm-threads` and capture `iostat -x 5` plus `gc.log` simultaneously. Otherwise JVM GC time and storage time are confounded.

**DeepVariant constraint**: `make_examples` cannot consume a pipe — it requires an indexed BAM. Plan the materialize step accordingly. There is no streaming-only DeepVariant pipeline.

---

## Storage Budget

Single 30× WGS sample, GRCh38, on a 300 GB scratch image:

| Workload | Peak scratch | Notes |
|---|---|---|
| bcftools mpileup → call (whole genome, sharded) | ~5 GB | Near-streaming |
| DeepVariant full pipeline (whole genome, sharded) | ~240 GB | BAM materialize 130 GB + DV intermediates 80 GB + 30 GB margin |
| GATK HaplotypeCaller (single sample, sharded) | ~80 GB | Per shard with `--tmp-dir` pinned |
| Worst-case rebuild (DV + GATK cross-check) | ~320 GB | Resize scratch image to 350 GB if this is in routine use |
| Two concurrent runs | ~440 GB | **Out of budget — orchestrator must serialize, not parallelize.** |

The 300 GB image accommodates any single Tier-1 run with margin. Resize via `truncate -s 350G` + `resize2fs` inside the VM if cross-validation runs become routine.

---

## Safety Rails

### Pre-flight assertions

Before each pipeline kickoff, the orchestrator must verify:

1. `/Volumes/Genome_Work` is mounted and APFS-formatted (`diskutil info | grep "File System Personality"`).
2. The scratch image is attached and mounted in the VM at `/mnt/genomeclaw/scratch` with `rw` flags. **Parse the actual `mount` output, not the config.**
3. `os.statvfs('/mnt/genomeclaw/scratch').f_bavail * f_frsize >= step_budget + 10 GB safety margin`. Per-step budgets follow the table above.
4. Test write + `fsync` to `/mnt/genomeclaw/derived/` succeeds. Fail loud if RO.

Reject the run with a specific error if any assertion fails. Do not start the pipeline and discover the problem mid-run.

### Mid-run monitoring

For long-running steps (anything > 10 minutes wall clock):

- Log `df -h /mnt/genomeclaw/scratch` every 60 seconds.
- Track `du -sh $SCRATCH/<current-step>` against the step's budget. If observed growth rate × estimated remaining wall-clock exceeds free space, abort and dump diagnostics.
- ext4 mounted with 5% reserved-for-root (`tune2fs -m 5` once at format time): the unprivileged container user hits ENOSPC at 95% full, leaving the orchestrator process headroom to write final logs and clean up.

### Atomic promotion to `derived/`

DuckDB stores and other authoritative outputs are built on block-attached scratch, validated, then copied to virtiofs RW `/derived/`:

```bash
# Build on scratch
duckdb $SCRATCH/duckdb-build/variants.tmp.db < build.sql

# Validate (row count, schema version, checksum)
duckdb $SCRATCH/duckdb-build/variants.tmp.db -c \
  "SELECT count(*), max(schema_version) FROM variants" > $SCRATCH/duckdb-build/validation.txt

# Copy to derived/, then atomic rename within the same FS
cp $SCRATCH/duckdb-build/variants.tmp.db $DERIVED/variants.db.tmp
sync
mv $DERIVED/variants.db.tmp $DERIVED/variants.db   # atomic — same filesystem

# Only after the rename succeeds, purge scratch
rm -rf $SCRATCH/duckdb-build/
```

Same pattern for VCF outputs: bgzip + tabix on scratch, validate EOF marker and tabix index, then `cp` + atomic `mv` into `/derived/vcf/`.

The `cp` (not `mv`) avoids the trap where `mv` across filesystem boundaries decomposes into copy-then-delete and leaves no valid copy if interrupted. Within the same filesystem, `mv` is atomic and fine.

### Drive ejection

The scratch raw image is an open file held by the VM. Eject sequence:

```
colima stop                               # VM releases the image file
diskutil eject /Volumes/Genome_Work
# physical disconnect now safe
```

Yanking the drive while the VM is running produces EIO inside the container, ext4 remounts read-only, and the journal replays on next mount. No host kernel panic, no APFS corruption — but the in-flight pipeline run is lost. Surface this prominently in any user-facing UI: stop the VM before unplugging.

### vcfanno deprecated

vcfanno is no longer permitted in the production pipeline. Use `bcftools annotate` for all overlay annotation. The async deadlock observed in vcfanno + bgzip under heavy I/O contention was the original trigger for this architecture work, and even with block-attached scratch the goroutine sync pattern that produced the deadlock is not formally proven safe under all concurrent loads. `bcftools annotate` is the supported substitute.

---

## `bin/genomeclaw-prep` Implementation Checklist

The host shim must, in order:

1. Verify `/Volumes/Genome_Work` is mounted and APFS. Abort with a specific error message naming the volume if not.
2. Verify `_scratch/scratch.raw` exists. If not, create it (`truncate -s 300G`).
3. Verify the lima override declares the additional disk and points at the correct path. Re-render the override from a template if missing.
4. Start colima/lima if not already running.
5. On first VM start with the disk attached: detect via `blkid` whether the block device has a filesystem; if not, run `mkfs.ext4 -L genomeclaw-scratch` and `tune2fs -m 5`. Mount at `/mnt/genomeclaw/scratch`.
6. Verify all four mounts (`raw`, `reference`, `derived`, `scratch`) are present and have the expected `ro`/`rw` flags by parsing `mount` output **inside the VM**. Fail loud, with the exact mount line, if any flag is wrong.
7. Test write + `fsync` in `/mnt/genomeclaw/derived` and `/mnt/genomeclaw/scratch`. Fail loud if either fails.
8. Smoke test: write a 1 GB file to scratch, read it back, verify checksum, delete. Catches lima `additionalDisks` regressions before they hit a real run.
9. Print a summary line: `prep: ok — scratch 287 GB free, derived 1.4 TB free`.

---

## Pinned Versions and Known Footguns

| Component | Constraint | Reason |
|---|---|---|
| lima | ≥ 1.1 | Earlier versions had `additionalDisks` truncate-to-0 (lima #1964) and qemu-img convert failures (#3720). Pin a tested patch version. |
| colima | track latest stable | Composition of YAML defaults has churned; verify the resolved `~/.lima/colima/lima.yaml` after start matches expected mount flags. |
| ext4 | mounted with `data=ordered` (default) | Survives drive yanks via journal replay. |
| samtools | ≥ 1.17 | CRAM 3.1 reference resolution stable. |
| bcftools | ≥ 1.17 | `mpileup` + `call` streaming chain. |

After every lima or colima upgrade: re-run the prep smoke test. Mount-flag composition logic is the most fragile part of the stack.

---

## Open Items — Measure on First Integration

The following must be measured on first integration, not assumed:

- **DeepVariant `make_examples` whole-genome scratch peak.** Planned 80 GB; confirm with first real run, log the actual.
- **GATK HaplotypeCaller temp-dir growth pattern** under JVM auto-thread-detection. Run with explicit thread/GC pinning per the GATK section above; confirm wall-clock and storage utilization separable.
- **Drive-yank recovery.** Deliberately unplug mid-run on a test sample once. Verify ext4 journal replay, EIO surfacing in the container, orchestrator non-zero exit code, no host instability.
- **USB-3 vs Thunderbolt benchmark on the user's actual hardware.** Only if Tier-1 wall-clock regularly exceeds 12 hours.

---

## Post-implementation discovery (2026-05-10)

Phase 2 of the implementation plan repartitioned the project owner's external drive (Kingston XS2000, interim hardware) to APFS named `Genome_Work`, copied the 52 GB Nebula deliverable in, SHA-verified, provisioned the 300 GB sparse `scratch.raw`, and rewrote `~/.colima/default/colima.yaml` with the canonical mounts + `additionalDisks` block. Then `colima start` succeeded but `mkfs.ext4 /dev/vdb` failed with permission denied. Diagnosis revealed the actual problem:

**colima 0.9.1 silently strips the `additionalDisks` field from `colima.yaml` on start.**

Confirmed by inspecting the lima instance config that colima generates at `~/.colima/_lima/colima/lima.yaml`: only colima's own internal data disk appears under `additionalDisks` (`name: colima, format: false, fsType: ext4`), never our scratch image. The `/dev/vdb` we attempted to format was colima's data disk, not our 300 GB sparse file. The lima feature is real (lima 1.2.1 supports `additionalDisks` end-to-end), but colima 0.9.1's YAML composition step doesn't pass it through.

This makes the report's Solution Summary item 3 — *"Host all heavy scratch on a block-attached ext4 raw disk image, exposed to the VM via lima additionalDisks"* — unimplementable on the validated software stack.

### Two paths forward

**A) Defer block-attached. Use virtiofs everywhere on APFS.** The implementation plan's Phase 2 took this path: `colima.yaml` declares one writable virtiofs entry per host volume (e.g. `/Volumes/Genome_Work writable: true`); per-subdir RO/RW (`raw` ro, `reference` ro, `derived` rw, `_scratch` rw) is enforced at the docker bind-mount layer by the host shim — the same pattern Phase 4A already uses. The 12-step destructive sequence collapses to 9 (drop `provision_scratch_image`, `format_block_device_ext4`, `mount_block_device_in_vm`; replace `verify_mounts_in_vm` with `verify_mounts_via_shim` that uses the docker bind-mount discipline directly). The original justification for block-attached was virtiofs FUSE serialization on **exFAT**; APFS has fine-grained POSIX locking and may not exhibit the same throughput collapse. Open question for Phase 5+ measurement.

**B) Switch from colima to direct lima.** Lima 1.2.1 fully supports `additionalDisks`. The toolkit would manage a lima instance directly. Bigger UX/install change for the user (`limactl start genomeclaw` replaces `colima start`; the toolkit sets up a separate docker context). Reversible only at similar cost.

Phase 2 chose **A** as the MVP path. Decision rationale logged in `docs/plans/active/cram-scratch-strategy/work-notes.md`.

### Tripwires that escalate to B

If any of the following surface during Phase 5+ measurement, revisit:

1. **vcfanno-class end-of-stream deadlocks under virtiofs+APFS** at MVP-scale workloads. (Phase-4A's vcfanno deadlock was on USB-3 + exFAT + virtiofs; if it reproduces on APFS, the throughput-collapse hypothesis was wrong and we need block-attached.)
2. **Concurrent random-read + sequential-write throughput < 100 MB/s sustained** during DeepVariant `make_examples` against APFS+virtiofs scratch. Equivalent to the original exFAT failure pattern.
3. **DeepVariant or GATK fail with EIO under expected concurrent loads** on the new layout. Indicates a deeper FUSE-message-protocol issue we can't paper over.

### State on disk after the pivot

- `/Volumes/Genome_Work/genomeclaw/_scratch/scratch.raw` (300 GB sparse, currently unused). Harmless; can be deleted manually. Re-attaching it later as a real block device requires colima upstream support OR migration to direct lima.
- `colima.yaml` has a single `mounts:` entry: `/Volumes/Genome_Work writable: true` (plus any user-managed mounts like `/Users/hugi`). No `additionalDisks` field.
- Per-subdir RO/RW is the host shim's job: `bin/genomeclaw-prep` does `--mount type=bind,source=$GENOMECLAW_RAW_DIR,target=/mnt/genomeclaw/raw,readonly` etc. Reference, derived, work, scratch are bound separately with the right flags.

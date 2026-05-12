# Research brief — CRAM-scale scratch strategy on an external drive

**Status**: open question, blocking Phase 5+ pipeline work.
**Audience**: external bioinformatics / storage consultant. **Assume zero prior context on this codebase or project.**
**Drafted**: 2026-05-09, immediately after Phase 4A shipped end-to-end.

---

## TL;DR

We're building a privacy-first personal-genomics tool that runs on a laptop. The user's genomic data — including 50–80 GB CRAM files — is staged on an **external drive**, not the laptop's internal SSD. Today's pipeline (annotation overlays, VCF processing) fits in a few GB of scratch and runs fine. The next phase (alignment + variant calling from CRAM) needs **150–250 GB of simultaneous scratch**, and that scratch **cannot fall back to the user's local SSD** — it has to live on an external drive too. We've already hit three concrete I/O failures at MVP scale that suggest the obvious "just use the external drive as scratch" answer isn't safe by default. We need an external-drive-compatible scratch design before we touch Phase 5+ code.

---

## Project context

### What GenomeClaw is

GenomeClaw is a **privacy-first, local-first personal genomics assistant**. A single individual user keeps their own raw genomic data (FASTQ / BAM / CRAM / VCF — depending on what their sequencing provider returned) and uses the tool to:

- ingest, normalize, and annotate variants;
- materialize compact local stores (DuckDB) for fast querying;
- (eventually) interactively explore findings against curated evidence — ClinVar, gnomAD, PharmCAT, literature.

The project's defining property is that **the user's genome never leaves their device**. That means everything is local: pipeline execution, annotation databases, derived stores, retrieval, and (where practical) language-model inference. External egress is opt-in, per-operation, and applies only to *redacted* / *minimal-sufficient* derivatives — never to raw reads, BAMs, CRAMs, or full VCFs.

### Who the user is

A single, technically-comfortable individual processing their *own* genome on a personal laptop. Not a multi-tenant service, not a research consortium, not a clinic. The threat model is "my laptop or external drive gets stolen / my cloud account gets breached" — not "an APT is targeting me."

### The hardware shape

The reference deployment we're designing for:

- **Laptop**: Apple Silicon Mac (M-series), macOS Sequoia, modest internal SSD (i.e. NOT large enough to hold a 50 GB CRAM plus a 120 GB BAM plus a 30 GB gVCF concurrently).
- **External drive**: USB-3 or Thunderbolt-attached portable drive, currently exFAT-formatted, where all genomic source files and derived outputs live (`/Volumes/Genome/genomeclaw/{raw, reference, derived, work}`).
- **Linux runtime inside a VM**: a `genomeclaw/toolkit:dev` container running under colima (lima-based Linux VM, default driver: VZ.framework) so that bcftools / samtools / mosdepth / DuckDB run on Linux regardless of the host OS. The container is invoked via a host shim (`bin/genomeclaw-prep`) that bind-mounts the four canonical directories from the external drive into the container at `/mnt/genomeclaw/{raw, reference, derived, work}`.

The internal SSD is treated as **scarce** — fine for ephemeral compute, the colima VM image, and small caches, but not where the user's data lives.

### Current pipeline shape

```
raw VCF
  → ingest      (DuckDB store skeleton + provenance + optional mosdepth coverage)
  → normalize   (bcftools norm: split multi-allelic, left-align)
  → annotate    (bcftools annotate against ClinVar — the step we just shipped)
  → materialize (rewrite the DuckDB variants table from the annotated VCF)
  → query       (interactive)
```

Each step writes into `derived/<run-id>/` on the external drive. A `manifest.json` and `provenance.json` per run record every input's SHA256, every tool version, and every parameter, so the run is rebuildable from raw + tooling alone.

### Invariants (verbatim from `docs/reference/INVARIANTS.md`)

The whole system is built around three rules that any new design must respect:

- **`INV-D001` — Source-of-truth.** Raw genomic artifacts are authoritative and never mutated in place. Derived stores are disposable products of pipelines.
- **`INV-R001` — Rebuildability.** Every derived row carries seven canonical provenance columns (source path, source SHA256, tool, tool version, params JSON, schema version, timestamp). A clean rerun on the same inputs and tools must produce row-equivalent output.
- **`INV-P001` — Privacy default.** Genomic source files never leave the device. Network egress is opt-in per operation. Even our agent integration only sees redacted / minimal-sufficient summaries.

### Where we are vs. where we're going

- **Just shipped (Phase 4A)**: ClinVar overlay onto a pre-existing VCF — verified end-to-end on a real 4.87M-variant Nebula VCF (42,885 variants annotated, schema v0.2, including real Pathogenic / Likely_pathogenic findings).
- **Coming next (Phase 4B–4E)**: more annotation overlays (VEP / LOFTEE, AlphaMissense, SpliceAI, gnomAD frequencies). Still annotation-of-an-existing-VCF — fits comfortably in a few GB of scratch.
- **The problem we're writing this brief about (Phase 5+)**: handle the case where the user's source artifact is a **CRAM** (or BAM, or FASTQ) rather than a pre-called VCF. That means we need to run alignment and/or variant-calling locally. CRAMs are 50–80 GB. Variant callers need tens of GB of temp. Suddenly scratch sizing matters a lot.

---

## The problem

### Scratch budget for Phase 5+

A single CRAM-to-VCF pass (numbers from typical DeepVariant / GATK HaplotypeCaller workloads on whole-genome data):

| Item | Typical size |
|---|---|
| Raw CRAM | 50–80 GB |
| BAM derived from CRAM (if needed) | 120–200 GB |
| Reference FASTA + indexes (GRCh38 + decoys) | ~3.5 GB |
| gVCF intermediate | 10–30 GB |
| Variant-caller temp (sort, partial calls) | tens of GB |
| Sort / shard temp during tabix indexing | workload-dependent |

Held simultaneously, that's **150–250 GB of scratch** for one run, with no headroom for a concurrent rerun.

### The hard constraint

**Scratch must not be bounded by the user's local SSD.**

- The whole point of GenomeClaw's storage shape is that genomic data lives on the user's external drive. Forcing scratch onto the laptop's internal SSD breaks that promise on machines with small SSDs (which is the common case for the M-series Mac users we expect).
- Anything that depends on the colima rootDisk (the VM's overlay filesystem, where the container's `/tmp` lives) is bounded by the laptop's local SSD by construction. So even though `/tmp` is the *fastest* writable path inside the container, it is **not a viable home for CRAM-scale scratch**.

This is the constraint that makes the problem hard. The naïve answer "give the VM a bigger rootDisk" is off the table.

### The privacy constraint

Scratch must stay on the user's device. No cloud egress, no network filesystems backed by remote storage, no third-party sync. This is non-negotiable per `INV-P001`.

### The rebuildability constraint

Scratch is non-authoritative. Losing it must never lose user data. Authoritative outputs always end up under `derived/`, which is itself on the external drive. Scratch that disappears between runs is fine; scratch that disappears mid-run must surface as a clean error, not a silent partial write.

---

## What broke at MVP scale (concrete failures, all reproduced)

These are real failures we hit during Phase 4A development — they're cheap to reproduce, and they shape the option space below.

1. **vcfanno end-of-stream deadlock when both inputs and output were on the external drive (USB-3 exFAT, virtiofs-mounted into the container).** With ClinVar (192 MB) and a normalized user VCF (197 MB) on the external drive, vcfanno + a downstream bgzip writer ran for ~1 minute, produced ~196 MB of output, then **both** processes blocked: vcfanno in `futex_wait` (Go-runtime workers stuck on internal goroutine sync), bcftools in `pipe_read` (waiting on vcfanno to flush). Combined CPU dropped to <0.01%. Reproduced with `vcfanno -p 1` (single worker) too. Resolution: replaced vcfanno with `bcftools annotate` and staged inputs on container-local `/tmp` (overlay-backed). The same workload finished in 32s. Open question for this brief: was the deadlock *caused* by virtiofs latency, or just exposed by it? If we move scratch to a different external-drive layout, do we still hit it?
2. **The canonical `work` mount is read-only on macOS Sequoia + colima/VZ.framework**, even though `colima.yaml` declares `writable: true`. Inside the container, `mount` reports `/mnt/genomeclaw/work … virtiofs (ro,relatime)`. Any orchestrator that writes there fails with `OSError: [Errno 30] Read-only file system`. `/Volumes/...` paths are *not* affected by the same gating — only `$HOME`-backed paths. We don't yet know whether this is colima's behavior, VZ.framework's, or a config mistake.
3. **Concurrent random-read + random-write throughput collapse on USB-3 exFAT virtiofs.** Setting aside the vcfanno-specific deadlock: even sequentially well-behaved tools hit single-digit MB/s when they read one file from the external drive while writing another *to the same external drive*, both via virtiofs. Sequential reads alone, or sequential writes alone, are fine.

These three together are why MVP scratch ended up on `/tmp`. None of them block the MVP, because the MVP fits in 2 GB of scratch and `/tmp` is enough. They become blockers the moment we need 150+ GB.

---

## Available filesystems (macOS + colima setup)

What a designer has to work with on the test machine. Linux equivalents exist for each.

| Path | Backing | Throughput | RW from container | Bounded by | Notes |
|---|---|---|---|---|---|
| Container `/tmp` | colima rootDisk overlay (local SSD) | very fast | yes | **local SSD** | ruled out for CRAM scratch by constraint above |
| `$HOME/.genomeclaw/work` (canonical `work`) | virtiofs over macOS APFS | fast in principle | **RO under VZ.framework today** | local SSD | currently broken; would still be local-SSD-bounded even if fixed |
| `/Volumes/Genome/genomeclaw/work` | virtiofs over USB-3 exFAT | slow + concurrency-fragile | RW | external drive size | sequential streaming OK, random + concurrent I/O collapses (failure #3 above) |
| `tmpfs` inside the container | RAM | very fast | yes | RAM | unrealistic at 200 GB working set |
| Bind a dedicated APFS / HFS+ volume on the external drive (untested) | virtiofs | unknown | unknown | external drive size | the most interesting unexplored option |
| Thunderbolt-attached drive (untested) | virtiofs | unknown (probably much faster than USB-3) | unknown | external drive size | likely solves the throughput problem; need real numbers |
| Pass the external drive to the VM as a raw block device, mount it Linux-side | direct (no virtiofs) | should be near-native | yes | external drive size | bypasses macOS's virtiofs layer entirely |

The interesting design space is the bottom three rows — every option above them is either ruled out by the SSD constraint or known-broken.

---

## Options to investigate

In rough order of expected leverage. The first three are external-drive-resident by construction; the last three are mitigations.

1. **Reformat the external drive (or carve out a partition) as APFS, not exFAT.** APFS handles random-access workloads dramatically better than exFAT and is what virtiofs is presumably tuned for on macOS. Question for the consultant: does this remove failure mode #3 (concurrent-IO collapse)? Does it change anything about failure mode #2 (RO virtiofs under VZ)?
2. **Use a Thunderbolt-attached SSD instead of USB-3.** A Thunderbolt 3/4 NVMe enclosure can sustain 1–3 GB/s sequential and tolerates random I/O far better than USB-3. The constraint is that scratch isn't on the *internal* SSD; an external Thunderbolt SSD is fine. Question for the consultant: do the virtiofs throughput collapses we saw on USB-3 exFAT survive on Thunderbolt + APFS?
3. **Pass the external drive to the VM as a raw block device** (`virtio-blk` / `virtio-fs` with passthrough, or plain disk passthrough) instead of relying on macOS-side virtiofs at all. The Linux VM then sees the external drive directly, formats it however it wants (ext4 / xfs / btrfs), and the host can't poke at it while the VM has it open. This is the "bypass virtiofs" answer. Question for the consultant: is this supported under colima + VZ.framework? Is there a clean colima config knob for it, or do we need to drop colima and configure lima directly? What happens when the user unmounts the drive while the VM holds it?
4. **Hybrid scratch tiers, with neither tier on the local SSD.** Two scratch backends, picked per-step:
   - **Random + concurrent + smaller** → a small APFS partition on the external drive (or a Thunderbolt SSD if available).
   - **Sequential streaming + bigger** → the bulk-storage exFAT partition on the external drive.
   Orchestrators declare what they need; the runtime picks. Open: how to make this not feel like setup hell for the user.
5. **Rework Phase-5 pipelines to stream rather than stage.** CRAM → BAM → variant call doesn't strictly need each intermediate on disk. `samtools view` can stream into the next stage. Sort and tabix index do need on-disk temp; but the sort temp is much smaller than the full BAM. Question: which Phase-5 stages can be wired as Unix pipes, and what's the residual scratch budget after eliminating the stage-able intermediates?
6. **Shard by region / chromosome.** Operate one chromosome at a time, keep its active scratch in a small APFS workspace, write the per-shard output to `derived/`, then concatenate. Caps simultaneous scratch at ~5 GB (one chromosome's worth of CRAM). Compatible with the bind-mount discipline. Trade-off: orchestration complexity, edge cases around inter-chromosomal events; some variant callers may fight this.

Notably **not on the list**: "increase the colima rootDisk." That's bounded by the local SSD (constraint #1) and so is structurally disqualified, even though it would be the cheapest fix if the constraint didn't exist.

---

## Open questions for the consultant

Concrete, repro-able, would-actually-change-our-design questions:

1. **Why is `$HOME` virtiofs RO under colima + VZ.framework on macOS Sequoia?** Is this a colima default, an Apple VZ restriction, or a config we got wrong? Reproducer: see `bin/genomeclaw-prep` host shim and `mount | grep work` from inside the container. Can we configure a non-`$HOME` writable virtiofs mount that lives on the external drive?
2. **Does the USB-3 exFAT concurrent-IO collapse persist on USB-3 APFS, on Thunderbolt exFAT, and on Thunderbolt APFS?** Goal: a 2x2 matrix of (transport, filesystem) → throughput under "tabix-style random read + bgzip-style sequential write to the same volume." If APFS alone fixes it, that's a much smaller change for the user.
3. **Can colima pass an external block device through to the VM as a raw disk under VZ.framework?** If yes, the VM can format it as ext4 and we sidestep virtiofs entirely. Open: how the user safely ejects the drive when the VM is using it.
4. **What's the realistic minimum scratch footprint per CRAM-class pipeline if we shard by chromosome?** Numbers per-tool, please — DeepVariant vs GATK HaplotypeCaller vs strelka2. We need actuals to budget storage tiers.
5. **What's the failure mode when the chosen scratch tier fills up?** Per option above: what happens when the APFS scratch partition is full, the exFAT bulk volume is full, the VM-passthrough block device is full? Hard hang, ENOSPC, filesystem corruption, kernel panic? Critical for designing safety rails.
6. **Is there a CRAM→VCF pipeline (alignment + calling) that's known to behave well on Linux with all working data on a slower-than-local-SSD volume?** I.e., explicitly designed not to thrash random I/O. We'd rather adopt one than fight a fast caller into behaving on slow storage.

---

## Success criteria

The output of this engagement is enough information to write `docs/plans/active/cram-scratch-strategy/development-plan.md` with confidence — i.e., we can answer:

- What does the user's external-drive layout look like? (Single exFAT partition? exFAT + APFS dual partition? Thunderbolt SSD?)
- What is the virtiofs / passthrough configuration we ship in the host shim?
- For each Phase-5+ pipeline step, which scratch tier does it use and why?
- What's the storage budget for one run, two concurrent runs, and a worst-case rebuild?
- How do we surface "out of scratch space" to the user *before* they hit it, not as a mid-run crash?

Until that plan exists, **Phase 5+ is not safe to start**. Phase 4A's MVP-scale workaround (`/tmp` + `bcftools annotate` over vcfanno + DuckDB CSV-staging on `/tmp`) is sufficient through Phases 4B–4E (still annotation-overlay-only — VEP cache, AlphaMissense, SpliceAI, gnomAD frequencies). The moment we touch CRAM, we need an answer.

---

## Pointers into the codebase (in case the consultant wants to reproduce)

- `bin/genomeclaw-prep` — host shim; the bind-mount discipline, env vars, and where the four canonical mounts come from.
- `docs/reference/architecture.md` — overall pipeline diagram, host-side packaging notes, mount semantics.
- `docs/reference/INVARIANTS.md` — `INV-D001`, `INV-R001`, `INV-P001`, `INV-P002`.
- `docs/plans/active/storage-scratch-layout/` — earlier plan that defined the four-mount discipline; the writable-`work`-mount assumption it relies on is exactly what's now broken on macOS Sequoia.
- `packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py` — current `/tmp`-based scratch workaround in production code; useful for seeing the failure-and-fix shape concretely.
- `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` — DuckDB CSV-staging that hits the same RO-`work` problem and currently routes around it via `/tmp`.
- `~/.colima/default/colima.yaml` (on the test machine) — current colima configuration; both `/Users/hugi` and `/Volumes/Genome` are declared `writable: true`, but only `/Volumes/...` is actually writable inside the VM.

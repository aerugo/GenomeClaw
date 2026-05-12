# Feature: Storage & scratch layout (the `work/` bind-mount)

**Status**: Complete
**Created**: 2026-05-08
**Owner**: project owner + Claude
**Related Plans**: [docs/plans/active/mvp/](../mvp/) (Phase 2 onward consumes this)

---

## Goal

Add a fourth canonical host bind-mount, `/mnt/genomeclaw/work`, for ephemeral pipeline scratch (temp, sort-temp, DuckDB spill, Nextflow `work/`) so that a user with limited local SSD space can point all transient pipeline I/O at an external drive without filling their boot disk.

## Background

The `genomeclaw/toolkit` Docker image ships with `bcftools`, `mosdepth`, `samtools`, and (later) VEP / Cyrius / `pgsc_calc`. Every one of those tools (plus DuckDB, Python's `tempfile`, and Nextflow) writes intermediate files to a temp / scratch / work directory. The defaults all land somewhere on the local filesystem:

- Inside the container, `$TMPDIR` defaults to `/tmp`, which lives in the container's writable layer — i.e., in the Docker engine VM's disk, on the local SSD.
- `bcftools sort -T` defaults to the current working directory.
- DuckDB spills to its `temp_directory` PRAGMA (default: CWD or `/tmp`) when an annotation join exceeds memory.
- Nextflow (used by `pgsc_calc`) materialises a `work/` directory in CWD; for a 30× WGS this can reach **multi-tens-of-GB**.

The project owner's actual setup is the textbook case:

> Local SSD: ~30 GB free. CRAM is 50+ GB and lives on a USB-attached external drive.

Without an explicit scratch mount, a single Phase 6 `pgsc_calc` run can fill the local SSD (or the colima VM disk under `~/.colima/`), then fail mid-pipeline. That outcome would falsely look like a GenomeClaw bug.

This plan introduces an explicit scratch mount, threads it through the image and the host shim, and documents the host-side storage discipline (USB layout, colima/Docker Desktop VM-disk concerns, recommended directory placement) end-to-end so the user can set it up once and not think about it again.

## Acceptance Criteria

- [ ] **AC1**: A fourth canonical host path, `/mnt/genomeclaw/work`, is documented in [`architecture.md`](../../reference/architecture.md) alongside `raw/reference/derived` with explicit RW semantics and the discipline that nothing inside `work/` is authoritative.
- [ ] **AC2**: The `genomeclaw/toolkit` image creates `/mnt/genomeclaw/work/` at build time and sets `ENV TMPDIR=/mnt/genomeclaw/work/tmp` so any tool that respects `$TMPDIR` writes to the bind-mounted volume by default.
- [ ] **AC3**: `bin/genomeclaw-prep` honours a new `GENOMECLAW_WORK_DIR` env var (default `/mnt/genomeclaw/work`), `mkdir -p`s it on the host if missing, and bind-mounts it RW into the container at `/mnt/genomeclaw/work`.
- [ ] **AC4**: The shim's `--help` smoke continues to work (no path required); a new test exercise runs the shim with `GENOMECLAW_WORK_DIR` pointed at a tmp host dir and asserts `/mnt/genomeclaw/work` is writable inside the container and `$TMPDIR` resolves there.
- [ ] **AC5**: The README has a **Storage planning** section explaining (i) the four-mount layout, (ii) recommended placement (USB for `raw/`, `reference/`, `work/`; local SSD acceptable for `derived/`), (iii) colima / Docker Desktop VM-disk caveats and how to expose external paths, (iv) per-mount expected sizes.
- [ ] **AC6**: [`user-stories.md`](../../reference/user-stories.md) Story 1 is updated to walk the user through the four-mount setup, including the USB-mount-into-colima step, before the first `genomeclaw-prep ingest` invocation.
- [ ] **AC7**: The MVP [Phase 2 plan](../mvp/phases/phase-2.md) Verification block threads `GENOMECLAW_WORK_DIR` through every shim invocation and shows the canonical bind-mount layout.
- [ ] **AC8**: Subprocess-wrapper conventions for tools that don't auto-respect `$TMPDIR` are documented in this spec for future-phase implementers: `bcftools sort -T <work>/bcftools/`, DuckDB `PRAGMA temp_directory='<work>/duckdb/'`, `nextflow -work-dir <work>/nextflow/`. (Implementation lands when each wrapper does, in its phase.)
- [ ] **AC9**: A documented **migration path off the work mount** — i.e., `rm -rf /mnt/genomeclaw/work/*` is always safe between runs — is recorded in the architecture doc, the README, and Story 1.

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — *unchanged*. `work/` is the most disposable surface in the system; `raw/` is still the most authoritative. The new mount strengthens the separation by making "what's safe to delete" structurally obvious.
- **INV-R001** Derived Stores Must Stay Rebuildable — *strengthened*. Pipelines explicitly route scratch outside the derived store, so `derived/<run-id>/` contains only authoritative outputs and provenance. A `work/` blowup never corrupts a `derived/` artifact mid-write.
- **INV-P001** Privacy Default — *unchanged*. `work/` carries the same privacy posture as `derived/`: host-side, never touched by the sandbox, never traversed by network egress.
- **INV-P002** Agent egress is named, minimal-sufficient — *unchanged*. The host service does not read `work/`; the plugin has no path to it.
- **INV-D002** Raw Artifacts Host-Side Only — *unchanged*. The `work/` mount lives on the host alongside `raw/`, `reference/`, and `derived/`. The sandbox image has none of these.
- **INV-E001** Evidence Traceability — *unchanged*. Evidence references resolve under `derived/` and `reference/`, not `work/`.
- **INV-C001** Clinical / Lifestyle Distinction — *unchanged*. No user-facing surface changes.

## Proposed New Invariants

**None.** The `work/` mount fits inside the existing invariants' envelope. A candidate informal rule worth recording in this spec but **not** promoting to an `INV-xxx`:

> **Discipline (not an invariant)**: nothing inside `/mnt/genomeclaw/work/` is authoritative. Anything that survives across runs belongs in `/mnt/genomeclaw/derived/<run-id>/`. The toolkit may delete `work/` contents at any time without warning.

If a future phase tries to write authoritative output to `work/`, the resulting test failure is the canonical signal that something belongs in `derived/` instead.

## Technical Requirements

### Source Data Inputs

- None (this plan introduces a new on-host directory; no new genomic inputs).

### Derived Outputs

- None (this plan adds an *explicitly non-authoritative* directory; nothing inside it is a derived output).

### Schema / Migration Impact

- None. Schemas are unchanged.

### Pipeline / Workflow Impact

- Future pipeline subcommands (Phase 2 onward) must route their temp / scratch / spill writes to `/mnt/genomeclaw/work/<subdir>/`:
  - **VEP, mosdepth, generic Python `tempfile`** — pick up `$TMPDIR=/mnt/genomeclaw/work/tmp` automatically (provided the image's `ENV TMPDIR=...` is set).
  - **`bcftools sort`** — wrapper passes `-T /mnt/genomeclaw/work/bcftools/sort.XXXX`.
  - **DuckDB** — every connection sets `PRAGMA temp_directory='/mnt/genomeclaw/work/duckdb/'`.
  - **`pgsc_calc` (Nextflow)** — wrapper passes `-work-dir /mnt/genomeclaw/work/nextflow/`.
  - Subdirs are created lazily by the wrapper code; the toolkit does not pre-create them all.

### Agent / UX Impact

- The agent / sandbox-side surface is **unchanged**. The work mount is purely host-side and invisible to the plugin and the host service.
- The host shim (`bin/genomeclaw-prep`) gains one env var (`GENOMECLAW_WORK_DIR`); the rest of the user-facing CLI is unchanged.

### External Dependencies

- None new. The plan depends on the existing `genomeclaw/toolkit` image and shim from the [development-plan.md Decision Taken #10](../mvp/development-plan.md) host-image amendment.

## Privacy & Safety Considerations

- **Boundary scan**: `work/` lives on the host alongside `derived/`. It never enters the sandbox. The host service does not read it. The plugin has no path to it. Privacy posture is identical to `derived/`.
- **Default-off remote calls**: none introduced. The plan adds zero new network surfaces.
- **Redaction surface**: n/a (no egress).
- **Clinical escalation**: n/a (no user-facing finding surface changes).

## Out of Scope

- **Automatic cleanup of `work/` between runs** — leaving as user responsibility. A future plan may add `genomeclaw-prep work clean --older-than 7d` once we have observed need; not now.
- **Per-tool resource caps** (memory limits, disk quotas) — out of scope. Standard Docker resource limits suffice; the user can apply `--memory` / `--storage-opt` via env-var on the shim if needed.
- **Bundling colima or configuring it on behalf of the user** — out of scope. The README documents the commands; the user runs them once. Automating colima setup risks fighting whatever the user already has configured for other workloads.
- **Sandbox-side storage** — `INV-D002` keeps the sandbox image small and stateless; the sandbox does not need a scratch volume.
- **Schema-version bump** — `work/` is not part of any schema.

## Dependencies

- The `genomeclaw/toolkit` Docker image and `bin/genomeclaw-prep` shim, both of which landed alongside the host-image Decision Taken on 2026-05-08 ([MVP development-plan.md](../mvp/development-plan.md) Decision #10).
- No upstream-tool changes needed — `bcftools`, `mosdepth`, `samtools`, DuckDB, Nextflow, and VEP all expose explicit scratch-dir flags or honour `$TMPDIR`.

## Open Questions

- [ ] **Q1**: Should the shim refuse to start if `GENOMECLAW_WORK_DIR` resolves to a path inside `derived/` (i.e., the user accidentally points scratch at the authoritative dir)? *Tentative answer*: yes — emit a clear error and exit 2. Cheap insurance; recorded as a Phase 1 implementation detail.
- [ ] **Q2**: Should the image's `ENV TMPDIR` point at `/mnt/genomeclaw/work/tmp` (the bind-mount) or `/tmp` (in-container)? *Tentative answer*: bind-mount. `/tmp` lives in the writable layer and grows the VM disk. The bind-mount path also exists at build time as a directory; tools that try to use it before the shim mounts anything still get a writable directory, just one in the container's writable layer.

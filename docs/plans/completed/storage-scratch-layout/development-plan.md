# Storage & scratch layout — Development Plan

**Status**: Complete
**Created**: 2026-05-08
**Branch**: `feature/storage-scratch-layout` (target — not yet created)
**Spec**: [spec.md](spec.md)

---

## Summary

Single-phase change. Adds `/mnt/genomeclaw/work` as the fourth canonical host bind-mount, threads it through the `genomeclaw/toolkit` image (`ENV TMPDIR`, mount point) and the `bin/genomeclaw-prep` shim (`GENOMECLAW_WORK_DIR`, fourth bind-mount, host `mkdir -p`), and documents the host-side storage discipline (USB layout, colima/Docker Desktop VM caveats, four-mount sizing) in the README, the architecture doc, and Story 1 of the user stories. No schema changes, no new endpoints, no plugin or sandbox effects.

## Critical Invariants to Respect

- **INV-D001** Raw Genomic Files Are Source-of-Truth — `work/` is the most disposable surface; `raw/` keeps its `:ro` discipline. The plan does not alter how raw files are read.
- **INV-R001** Derived Stores Must Stay Rebuildable — strengthened. Pipelines are explicitly told to spill outside `derived/`, so `derived/<run-id>/` only contains authoritative outputs and provenance. A `work/` blowup never half-writes a derived artifact.
- **INV-P001** Privacy Default — unchanged. `work/` is host-side, invisible to the sandbox, and never traversed by network egress.
- **INV-P002** Agent egress is named, minimal-sufficient — unchanged. Host service does not read `work/`; plugin has no path to it.
- **INV-D002** Raw Artifacts Host-Side Only — unchanged. The new mount is host-side only.
- **INV-E001** Evidence Traceability — unchanged. No evidence references resolve into `work/`.
- **INV-C001** Clinical / Lifestyle Distinction — unchanged. No user-facing finding surface changes.

## Proposed New Invariants

**None.** The discipline "nothing in `work/` is authoritative" is recorded as a design rule, not promoted to an `INV-xxx`.

## Current State Analysis

### What exists today

- The `genomeclaw/toolkit` image creates three mount points (`raw/`, `reference/`, `derived/`) and chowns them to the `genomeclaw` user (uid 1000). No `work/` mount, no `$TMPDIR` discipline.
- `bin/genomeclaw-prep` honours three env vars (`GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`) and bind-mounts each only if it exists on the host (silent skip otherwise).
- [`architecture.md`](../../reference/architecture.md) "Data layout" section names the three mount points; the new "Host-side packaging" section names the same three.
- [`README.md`](../../../README.md) has no Storage planning section. "Designed For" mentions Docker but says nothing about VM-disk sizing or USB layout.
- [`user-stories.md`](../../reference/user-stories.md) Story 1 walks the user through the host shell but does not mention scratch space, USB drive prep, or the colima VM disk.
- [MVP Phase 2 plan](../mvp/phases/phase-2.md) Verification block already uses the shim but does not pass `GENOMECLAW_WORK_DIR` (because the env var doesn't exist yet).

### What's missing

- The `work/` mount (image, shim, docs, story).
- A clear story about *where on disk* the user should put each of the four mounts, especially when the local SSD is small.
- A clear story about how to expose external paths to the colima VM (or Docker Desktop VM) so the bind-mount works at all.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [`packages/toolkit/Dockerfile`](../../../packages/toolkit/Dockerfile) | 3 mount points, no `TMPDIR` | Add `mkdir -p /mnt/genomeclaw/work`; `ENV TMPDIR=/mnt/genomeclaw/work/tmp`; chown `work/` to `genomeclaw`. |
| [`bin/genomeclaw-prep`](../../../bin/genomeclaw-prep) | 3 env vars, 3 bind-mounts, silent-skip-if-missing | Add `GENOMECLAW_WORK_DIR` (default `/mnt/genomeclaw/work`); `mkdir -p` it on the host; bind-mount RW; refuse-with-error if it resolves under `GENOMECLAW_DERIVED_DIR` (per spec Q1). |
| [`docs/reference/architecture.md`](../../reference/architecture.md) | "Data layout" + "Host-side packaging" name 3 mounts | Add `work/` to the data layout tree; expand Host-side packaging with the 4-mount discipline + lifecycle ("nothing in work is authoritative"); add a one-paragraph "Storage planning" subsection cross-linked from the README. |
| [`README.md`](../../../README.md) | "Designed For" mentions Docker; no storage planning section | Add a new "Storage planning" section after "Designed For" with the 4-mount layout, USB guidance, colima notes, sizing table. |
| [`docs/reference/user-stories.md`](../../reference/user-stories.md) | Story 1 has no storage prep step | Add a "Step 0 — storage prep" block before the existing first action; thread `GENOMECLAW_WORK_DIR` through the existing commands; note that the agent never touches `work/`. |
| [`docs/plans/active/mvp/phases/phase-2.md`](../mvp/phases/phase-2.md) | Verification block sets RAW/REF/DERIVED only | Thread `GENOMECLAW_WORK_DIR` through the shim invocations; mention `work/` cleanup is safe between runs. |

### Files to Create

| File | Purpose |
|------|---------|
| [`docs/plans/active/storage-scratch-layout/spec.md`](spec.md) | This plan's spec (written first). |
| [`docs/plans/active/storage-scratch-layout/development-plan.md`](development-plan.md) | This file. |
| [`docs/plans/active/storage-scratch-layout/work-notes.md`](work-notes.md) | Append-only session log. |
| [`docs/plans/active/storage-scratch-layout/phases/phase-1.md`](phases/phase-1.md) | RED → GREEN → REFACTOR for the single phase. |

No new test files (the smoke happens via the shim invocation; coverage of the wrapper code that consumes `work/` lands in the wrappers' own phases).

## Solution Design

```text
Host filesystem                                          Inside genomeclaw/toolkit container
─────────────────────────────────                        ──────────────────────────────────
$GENOMECLAW_RAW_DIR        ──── bind RO  ──────────────► /mnt/genomeclaw/raw       (RO)
$GENOMECLAW_REF_DIR        ──── bind RO  ──────────────► /mnt/genomeclaw/reference (RO at runtime)
$GENOMECLAW_DERIVED_DIR    ──── bind RW  ──────────────► /mnt/genomeclaw/derived   (RW; authoritative)
$GENOMECLAW_WORK_DIR (NEW) ──── bind RW  ──────────────► /mnt/genomeclaw/work      (RW; ephemeral)
                                                         └─ ENV TMPDIR=/mnt/genomeclaw/work/tmp
                                                            └─ subdirs created lazily by wrappers:
                                                               work/tmp/        $TMPDIR
                                                               work/duckdb/     PRAGMA temp_directory
                                                               work/bcftools/   `bcftools sort -T`
                                                               work/nextflow/   `pgsc_calc -work-dir`
```

The four mounts are the **only** writable bind-mounts. Anything inside `derived/<run-id>/` is authoritative and provenance-tracked. Anything inside `work/` is disposable and fine to delete between runs. The discipline is enforced socially (this plan + docs) rather than mechanically (no permissions trick stops a wrapper from writing authoritative data into `work/`); future-phase wrappers that violate it will fail their own provenance / determinism tests.

### Key Design Decisions

1. **Four mounts, not three plus one umbrella RW mount.** The user's mental model is "ephemeral vs. authoritative". A single combined `state/` directory containing both `derived/` and `work/` would be cheaper to maintain, but it would force users to remember the discipline manually every time they thought about disk planning. Four named mounts make the discipline structurally obvious.
2. **Bind-mount, not Docker volume.** The four mounts are user-owned host paths. Named volumes would put the data inside the engine VM's disk, defeating the point of the work-mount design (and re-introducing the local-SSD blowup risk).
3. **`ENV TMPDIR` set at image build time, not via the shim.** The image is the right layer to pick the default — anything *inside* the container that doesn't go through the shim still gets a writable scratch dir. The shim's job is to make that path actually point at the bind-mount; the env var is a contract between the image and any tool the wrappers spawn.
4. **`mkdir -p` on the host before bind-mount.** The shim auto-creates `$GENOMECLAW_WORK_DIR` on the host if missing. Without this, Docker would create a root-owned anonymous dir on the host, leaving the user surprised. For RAW/REF/DERIVED we keep the existing "skip if missing" because users explicitly stage those before running the pipeline; for WORK we want the opposite default because the user should never have to think about it.
5. **Refuse-if-`work`-is-inside-`derived`.** Single sanity check. Cheap to enforce in the shim; saves the user from a footgun where `pgsc_calc` Nextflow work files end up under `derived/<run-id>/` and confuse provenance-aware tooling later. Q1 in the spec, settled here.
6. **No automatic cleanup.** The toolkit never deletes `work/` files. Users (or a cron job) clean it. Future plan can add `genomeclaw-prep work clean` once we observe the need.
7. **Storage planning section lives in README, deeply linked from architecture.md and the spec.** The README is where users first encounter the project; the architecture doc is for once they're already implementing. Both link to each other.

### Schema / Provenance Impact

- **None.** No new schemas, no new columns, no schema-version bump. Provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`) are unchanged. The `work/` mount carries no schema because nothing inside it is authoritative.
- **Rebuild procedure**: unchanged. `genomeclaw-prep ingest --vcf … --bam …` regenerates `derived/<run-id>/` from inputs; `work/` content is ephemeral and never required for rebuild.

### Privacy & Egress Impact

- **No new network egress points.** The `work/` mount is host-only.
- **No new secret-handling surfaces.** Tool intermediates in `work/` carry no credentials.
- **No new redaction.** The host service does not read `work/`; the plugin has no path to it.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Image + shim changes; doc updates (architecture, README, user-stories Story 1, MVP Phase 2 plan) | shim smoke (work mount writable + `$TMPDIR` resolves there); refusal test (work inside derived); image-build smoke | ~3 (all in the toolkit's existing test harness; the underlying wrappers that *consume* `work/` get their own tests in their own phases) |

A single phase is enough — the change is mechanical, the doc updates are coupled to the implementation, and there's no schema work to gate behind a separate slice.

## Phase 1: Add the `work/` mount end-to-end

**Goal**: a fresh-checkout user can run `bin/genomeclaw-prep --help` against the image and see `/mnt/genomeclaw/work` writable inside the container; the four-mount discipline is reflected in the README, architecture doc, Story 1, and the MVP Phase 2 plan.

**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables

1. [`packages/toolkit/Dockerfile`](../../../packages/toolkit/Dockerfile) — `mkdir -p /mnt/genomeclaw/work`, chown to `genomeclaw`, `ENV TMPDIR=/mnt/genomeclaw/work/tmp`.
2. [`bin/genomeclaw-prep`](../../../bin/genomeclaw-prep) — `GENOMECLAW_WORK_DIR` env var, host-side `mkdir -p`, fourth bind-mount, refuse-if-inside-derived check, `--help` output unchanged.
3. [`docs/reference/architecture.md`](../../reference/architecture.md) — `work/` in the data-layout tree; expanded Host-side packaging "Bind-mount discipline"; new "Storage planning" subsection.
4. [`README.md`](../../../README.md) — new "Storage planning" section under "Designed For" with the four-mount layout, USB guidance, colima/Docker Desktop notes, sizing table.
5. [`docs/reference/user-stories.md`](../../reference/user-stories.md) Story 1 — "Step 0 — storage prep" block prepended; existing commands threaded with `GENOMECLAW_WORK_DIR`.
6. [`docs/plans/active/mvp/phases/phase-2.md`](../mvp/phases/phase-2.md) — Verification block threads `GENOMECLAW_WORK_DIR` through every shim invocation.

### Invariants Enforced Here

- **INV-R001** *(structurally, via design)*: future pipelines route scratch outside `derived/`. Phase 1 establishes the convention; the wrappers that consume it carry the actual test enforcement.
- All other invariants are *not enforced by new tests in this phase* — they are confirmed unchanged by the existing test suite (which still passes after the change).

### Success Criteria

- [ ] `docker build packages/toolkit` succeeds; `genomeclaw-prep --help` runs as the default CMD.
- [ ] `docker run --rm genomeclaw/toolkit:dev sh -c 'echo $TMPDIR'` prints `/mnt/genomeclaw/work/tmp`.
- [ ] `GENOMECLAW_WORK_DIR=$(mktemp -d) bin/genomeclaw-prep --help` exits 0; the work dir is bind-mounted RW; touching a file inside it from inside the container succeeds.
- [ ] Refuse-if-inside-derived test passes (shim exits non-zero with a clear message).
- [ ] All four target docs reflect the four-mount layout consistently (architecture, README, user-stories Story 1, MVP Phase 2 plan).
- [ ] Pre-existing toolkit tests (Phase 1 of MVP, four-pass smoke) still pass.

---

## Testing Strategy

This plan touches infrastructure and docs, not the toolkit's domain logic. The test categories used are:

### Unit Tests (none)

No domain code lands in this plan; subprocess wrappers that depend on `work/` arrive in their respective MVP phases (Phase 2 onward). Those phases write the unit tests.

### Integration / Smoke Tests (in this plan)

- `tests/integration/test_shim_work_mount.sh` (or its pytest-driven equivalent) — exercises the shim with `GENOMECLAW_WORK_DIR=$(mktemp -d)` and asserts:
  - `/mnt/genomeclaw/work` is bind-mounted and writable inside the container.
  - `$TMPDIR` inside the container resolves to `/mnt/genomeclaw/work/tmp`.
  - The shim refuses (exit 2, message printed) when `GENOMECLAW_WORK_DIR` resolves underneath `GENOMECLAW_DERIVED_DIR`.

(The toolkit doesn't have a Bash test harness yet, and adding one for one test is overkill. These three checks land as inline verification in the phase plan's Verification block; once a real shim test harness exists, they migrate into it.)

### Provenance Tests (none)

No new derived rows; no new provenance columns.

### Determinism Tests (none)

No pipeline behavior changes.

### Privacy-Default Tests (none)

No new egress points; existing privacy-default tests remain valid (and will run inside the new image once the rest of the pipeline lands).

### Evidence-Binding Tests (none)

No finding / evidence shape changes.

### Report Rendering Tests (none)

No agent-facing surface changes.

### Invariant Tests (none new)

Phase 1 of MVP's invariant-test naming scaffold (`tests/invariants/test_invXxxx_*.py`) stays as-is. No new `INV-xxx` IDs.

---

## Documentation Updates

After Phase 1 lands:

- [x] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — **no change**. Plan does not promote a new invariant; the disciplined "nothing in `work/` is authoritative" is recorded in this plan's spec and in architecture.md, not as an `INV-xxx`.
- [x] [docs/reference/architecture.md](../../reference/architecture.md) — `work/` in the data-layout tree; "Storage planning" subsection; bind-mount discipline expanded.
- [x] [docs/reference/user-stories.md](../../reference/user-stories.md) — Story 1 storage prep step.
- [x] [README.md](../../../README.md) — new Storage planning section.
- [x] [docs/plans/active/mvp/phases/phase-2.md](../mvp/phases/phase-2.md) — Verification block threads the new env var.
- [ ] [docs/plans/active/mvp/development-plan.md](../mvp/development-plan.md) — *no change required*. The host-image Decision Taken (#10) already names the bind-mount layout; the new mount is a refinement, not a contradiction. A small "Decision Taken — refined 2026-05-08: fourth `work/` bind-mount added" note could land if the surface gets confusing later, but is unnecessary today.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-08 | 2026-05-08 | All probes green; toolkit smoke suite still passes; default `GENOMECLAW_WORK_DIR` switched to `${HOME}/.genomeclaw/work` for macOS UX. |

---

## Open Risks & Follow-ups

- **colima storage drift over time**: as the user runs more of the pipeline, the colima VM may still grow on its own (image layers, metadata, system journals). The README will document the `colima delete && colima start --disk … --mount …` reset path, but won't try to automate it.
- **Wrapper-side enforcement is in future phases**: this plan creates the convention but does not yet wire DuckDB / bcftools / Nextflow to actually use `work/`. Phase 2 of MVP will land the bcftools-sort and DuckDB pieces; Phase 6 will land Nextflow. Until then, `work/` is reserved real estate, not actively used by every step.
- **Default `GENOMECLAW_WORK_DIR=/mnt/genomeclaw/work` requires the user's host to have that path writable**: macOS users typically don't have `/mnt/`. Story 1 will tell the user to point the env var at a path under `/Volumes/<USB>/genomeclaw/work` instead. The shim's host-side `mkdir -p` makes this graceful.
- **`bin/genomeclaw-prep` is currently the only shim**: Phase 5 will add `bin/genomeclaw-service`. That shim will need the same four bind-mounts (the service reads `derived/`, has no use for `raw/` or `work/` in principle, but routing `work/` through anyway costs nothing and keeps the contract consistent across both shims). Recorded here as a Phase-5 follow-up.

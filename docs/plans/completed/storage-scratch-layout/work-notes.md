# Storage & scratch layout — Work Notes

**Feature**: Add the `work/` bind-mount + 4-mount discipline + Storage Planning docs
**Started**: 2026-05-08
**Branch**: `feature/storage-scratch-layout` (target — not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom.

### 2026-05-08 — Plan authored

**Context Review Completed**:
- Re-read [INVARIANTS.md](../../reference/INVARIANTS.md) — confirmed `INV-D001`, `INV-D002`, `INV-P001`, `INV-P002`, `INV-R001` envelope; the `work/` mount fits inside without any new invariant.
- Re-read [architecture.md](../../reference/architecture.md) "Data layout" + "Host-side packaging" — confirmed three bind-mounts today; the doc clearly anticipates this kind of refinement.
- Re-read [MVP development-plan.md](../mvp/development-plan.md) Decision Taken #10 (host image, 2026-05-08) — confirmed the four-mount layout is a refinement, not a contradiction.
- Re-read [user-stories.md](../../reference/user-stories.md) Story 1 — confirmed the storage prep step is missing today; users would hit the colima VM disk wall before reaching the actual pipeline.
- Reviewed [`bin/genomeclaw-prep`](../../../bin/genomeclaw-prep) — confirmed three env vars + silent-skip-if-missing today.
- Reviewed [`packages/toolkit/Dockerfile`](../../../packages/toolkit/Dockerfile) — confirmed three mount points + chown to `genomeclaw` today.

**Applicable Invariants**:
- All seven canonical invariants apply unchanged. `INV-R001` is structurally strengthened by the convention "spill outside `derived/`" but the new tests in this plan don't directly assert it (the assertions land in the wrappers' own phases).

**Key Insights**:
- The user's "30 GB free / 50 GB CRAM on USB" setup is the textbook case the four-mount layout solves. Without `work/`, a Phase-6 `pgsc_calc` run can fill the colima VM disk (Nextflow `work/` for a 30× WGS is multi-tens-of-GB) and fail mid-pipeline.
- The image's `ENV TMPDIR` is the right enforcement point for tools we don't directly orchestrate (VEP, generic Python `tempfile`). The shim's job is only to make sure that path is bind-mounted to a host-controlled directory.
- `mkdir -p` on the host before bind-mounting (for `work/`) is the smoothest UX. Without it, Docker creates a root-owned anonymous dir and the user is surprised.
- Refuse-if-`work`-is-inside-`derived` is a cheap sanity check that prevents a real footgun (Nextflow `work/` files ending up under `derived/<run-id>/`).

**Completed Today**:
- [x] [spec.md](spec.md) authored.
- [x] [development-plan.md](development-plan.md) authored.
- [x] [phases/phase-1.md](phases/phase-1.md) authored.

**Decisions Made**:
- Single-phase plan (the change is mechanical + docs-coupled).
- Four bind-mounts, not three plus an umbrella `state/` — clearer mental model.
- `ENV TMPDIR` set at image build, not via the shim — makes the contract image-internal.
- `mkdir -p` on the host for `work/` only; existing skip-if-missing behavior preserved for `raw/`, `reference/`, `derived/`.
- Refuse-if-`work`-is-inside-`derived` (settles spec Q1 in the affirmative).
- No automatic cleanup — user owns the lifecycle.
- Storage planning lives in README; architecture.md cross-links to it.

**Blockers / Issues**: none.

**Next Steps**:
1. Implement Phase 1: Dockerfile + shim changes; doc updates; image rebuild + smoke.
2. Update MVP Phase 2 verification block to thread the new env var.

### 2026-05-08 — Phase 1 implemented

**Context Review Completed**:
- Re-read [phases/phase-1.md](phases/phase-1.md) — confirmed scope: Dockerfile env + mount-point, shim env-var + auto-mkdir + refuse-if-inside-derived, doc updates.
- Confirmed `colima` is the user's local Docker engine (`Context: colima`).

**Applicable Invariants**: none enforced by new tests; existing seven invariants confirmed unchanged.

**RED probe output** (run before implementation):
```text
== Probe 1: TMPDIR before == TMPDIR=
== Probe 2: work dir before == MISSING
== Probe 3: shim ignores GENOMECLAW_WORK_DIR == rc=0 (silently ignored)
== Probe 4: refuse-inside-derived == "bind source path does not exist" (no early refusal)
```

**Completed Today**:
- [x] Dockerfile: added `mkdir -p /mnt/genomeclaw/work` and `ENV TMPDIR=/mnt/genomeclaw/work/tmp`.
- [x] Shim: added `GENOMECLAW_WORK_DIR` env var, host-side `mkdir -p`, fourth bind-mount, refuse-if-inside-derived check (uses `pwd -P` to resolve symlinks).
- [x] Image rebuilt; size unchanged (586 MB).
- [x] All four GREEN probes pass.
- [x] **Default `GENOMECLAW_WORK_DIR` changed from `/mnt/genomeclaw/work` to `${HOME}/.genomeclaw/work`** — discovered during refactor that the original default broke `bin/genomeclaw-prep --help` on a fresh macOS host (`mkdir: /mnt: Read-only file system`). Updated shim, architecture.md, and shim env-var docstring to reflect the new default. README's Storage planning section already shows users explicit USB paths for real workloads, so the doc surface is consistent.
- [x] [docs/reference/architecture.md](../../reference/architecture.md): added `work/` to the data-layout tree; expanded "Bind-mount discipline" with the fourth mount; added a new "Storage planning (where to put each mount)" subsection with the per-mount sizing table + colima `--mount` instructions.
- [x] [README.md](../../../README.md): new "Storage planning" section under "Designed For" — sizing table, env-var snippet, macOS / colima file-sharing notes, `work/` is disposable note.
- [x] [docs/reference/user-stories.md](../../reference/user-stories.md) Story 1: added "Step 0 — storage prep" block (colima `--mount`, four-mount layout, env-var setup); renumbered subsequent steps; switched bare `genomeclaw-prep` invocations to the `bin/genomeclaw-prep` shim; struck through the obsolete "scratch space unaccounted-for" gap entry.
- [x] [docs/plans/active/mvp/phases/phase-2.md](../mvp/phases/phase-2.md) Verification block: threads `GENOMECLAW_WORK_DIR` through the shim invocations; documents the bcftools/DuckDB/Nextflow temp-routing convention.
- [x] Existing toolkit smoke suite (`uv run pytest -q`, `ruff check`, `ruff format --check`) still passes.

**Decisions Made (during implementation)**:
- Default `GENOMECLAW_WORK_DIR` is `${HOME}/.genomeclaw/work`, not `/mnt/genomeclaw/work`. Reason: macOS hosts can't `mkdir -p /mnt/...`; switching the default to `$HOME` makes `bin/genomeclaw-prep --help` work on a fresh checkout without env-var gymnastics. The in-container target is unchanged at `/mnt/genomeclaw/work` (the image expects that path). Documented in the shim docstring + architecture bind-mount discipline.
- The `colima` engine VM only auto-shares `$HOME` and `/Volumes`; `mktemp -d`'s default `/var/folders/...` is invisible. The phase-2 Verification block now uses `~/.genomeclaw-test/...` paths for that reason. Documented in the README Storage planning section as a "if you see 'bind source path does not exist'..." note.

**Verification (all GREEN)**:
```text
== Probe 1: TMPDIR ==      TMPDIR=/mnt/genomeclaw/work/tmp
== Probe 2: work dir ==    OK
== Probe 3: shim ==        usage: genomeclaw-prep [-h] <subcommand> ...
== Probe 3b: write-through == /Users/hugi/.genomeclaw-test.X/probe.txt OK
== Probe 4: refuse-inside-derived == rc=2; clear error message
== Probe 5: shim default (no env vars) == rc=0; help banner; ~/.genomeclaw/work auto-created

uv run pytest -q  ==>  4 passed
uv run ruff check . ==>  All checks passed!
uv run ruff format --check . ==>  14 files already formatted
```

**Blockers / Issues**: none.

**Next Steps**:
1. The plan is complete pending move to `docs/plans/completed/`. That move waits for either (a) a final commit, or (b) the user's explicit approval that the implementation is done.
2. Phase 2 of the MVP plan picks up the threaded `GENOMECLAW_WORK_DIR` invocations naturally; subprocess wrappers (bcftools, DuckDB) plug into `/mnt/genomeclaw/work/` per the convention recorded in [phase-2.md](../mvp/phases/phase-2.md).

---

## Phase Progress

### Phase 1: Add the `work/` mount end-to-end
**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08

#### Test Results
- RED probes (all 4): TMPDIR empty, `work/` missing, shim ignored env var, no refuse-check.
- GREEN probes (all 5 including default-no-env-var): TMPDIR resolves, `work/` exists, shim threads env var, write-through works, refuse-if-inside-derived fires with rc=2, default-no-env-var works on fresh macOS.
- Existing toolkit smoke suite: 4/4 still pass; ruff clean.
- Image rebuild: 36 steps `Successfully built`; size 586 MB (unchanged).

#### Results
- Dockerfile: 3-line change (+ comment block). New mount point + `ENV TMPDIR`.
- Shim: ~20-line change. Env var, refuse-check, auto-mkdir, fourth bind-mount.
- 4 docs updated: architecture.md, README.md, user-stories.md (Story 1), MVP phase-2.md.
- Plan directory created: `docs/plans/active/storage-scratch-layout/`.

#### Notes
- Default `GENOMECLAW_WORK_DIR` decision changed late in implementation (`/mnt/...` → `${HOME}/.genomeclaw/work`) for macOS UX. Worth remembering for any future shim env var: prefer `$HOME` defaults over `/mnt/` defaults on macOS hosts.
- The colima engine-VM file-sharing footgun (only `$HOME` + `/Volumes` auto-shared) is now documented in three places (README Storage planning, architecture.md Storage planning subsection, MVP phase-2.md Verification block). That's intentional — it's the single most likely first-time-user trip-up.

---

### 2026-05-08 — Live validation against the project owner's USB-attached genome

**Context**: walked Step 0 of Story 1 against the project owner's actual hardware — macOS Sequoia 15.1 + colima 0.9.1 + a 477 GB USB drive at `/Volumes/Genome` already populated with their Nebula CRAM (~50 GB), CRAM index, VCF (211 MB), and VCF index.

**Discoveries that contradicted the plan's prior assumptions**:

1. **`colima start --mount X:w` REPLACES the default `$HOME` mount, not appends.** Running `colima start --mount /Volumes/Genome:w` after a fresh `colima stop` dropped the auto-shared `/Users/hugi` mount, leaving only `/Users/hugi/Library/Caches/colima` (RO) and `/Volumes/Genome` (RW) in the rendered `~/.colima/_lima/colima/lima.yaml`. Symptom: the project owner's `bbu-api-1` container restart-looped because `/Users/hugi/GitRepos/bbu/data/bbu_export.json` was no longer visible inside the VM. The fix was to edit `~/.colima/default/colima.yaml` and explicitly list both `/Users/hugi` and `/Volumes/Genome` under `mounts:`. The previous draft of the docs claimed `colima auto-shares $HOME and /Volumes` which is **only true on first VM creation**, not on subsequent `colima start` invocations.
2. **macOS Sequoia + VZ.framework virtiofs gates `$HOME` to read-only inside the container** even with `writable: true` set in the lima/colima config. Granting `limactl` Full Disk Access in System Settings → Privacy & Security would unblock RW; the user had not done that, so the fallback is to put all four GenomeClaw mounts on the external drive. `/Volumes/...` paths are not subject to this gate. Both `mount` (inside the VM) and a container-side `touch` reproduced the symptom.
3. **`mktemp -d` produces paths under `/var/folders/...`** which colima does *not* share by default. The MVP Phase 2 verification block already uses `~/.genomeclaw-test/...` for that reason; reaffirmed during live validation.

**Patches applied**:

- [bin/genomeclaw-prep](../../../../bin/genomeclaw-prep): the shim now also creates `$GENOMECLAW_WORK_DIR/tmp` (the in-image `$TMPDIR` target) on the host, not just `$GENOMECLAW_WORK_DIR`. Without this, `python -c "tempfile.mkdtemp()"` inside the container failed with `No such file or directory` because `/mnt/genomeclaw/work/tmp/` didn't exist.
- [README.md](../../../README.md), [docs/reference/architecture.md](../../reference/architecture.md), [docs/reference/user-stories.md](../../reference/user-stories.md): rewrote the colima file-sharing guidance to (a) edit `colima.yaml` directly rather than rely on `--mount` append behavior, (b) name the Sequoia + VZ.framework RO-on-`$HOME` caveat with the Full Disk Access workaround, (c) recommend a USB-only four-mount layout for users who haven't granted that permission. Story 1 Step 0 now ends with a concrete bcftools-against-the-real-VCF smoke test the user can paste verbatim.

**Live verification (all GREEN against the project owner's actual genome)**:
```text
== shim --help ==                          rc=0; banner printed
== GENOMECLAW_DEBUG ==                      4 bind-mounts wired (raw RO, ref RO, derived RW, work RW)
== bcftools view -h .../sample.vcf.gz ==   ##fileformat=VCFv4.2 / ##FILTER=<ID=PASS> / ##ALT=<ID=NON_REF>
== python tempfile.mkdtemp() ==             /mnt/genomeclaw/work/tmp/tmpzn8xu9ru (write succeeded)
== touch /mnt/genomeclaw/derived/test ==    OK (RW confirmed)
== touch /mnt/genomeclaw/raw/should-fail == "Read-only file system" (INV-D001 enforced at OS layer)
== production containers ==                ui-postgres-1 + bbu-api-1 + ancestral-vision-db all healthy
```

The project owner's actual Nebula CRAM + VCF are now reachable from inside the `genomeclaw/toolkit` image, sitting at `/Volumes/Genome/genomeclaw/raw/MPNRGLQ2K/`, with `derived/`, `reference/`, and `work/` co-located on the same USB drive. The user's local SSD is unaffected — Phase 2 onward can run against this layout without filling the boot disk.

**Decisions Made**:
- The shim seeds `$GENOMECLAW_WORK_DIR/tmp` in addition to `$GENOMECLAW_WORK_DIR`, because the image's `ENV TMPDIR=/mnt/genomeclaw/work/tmp` requires that subdir to exist before any `tempfile.mkdtemp()` call. Subdirs for `bcftools/`, `duckdb/`, `nextflow/` will be created lazily by their respective wrappers when those land.
- The "edit `~/.colima/default/colima.yaml` directly" advice replaces the previous `colima start --mount` advice in all three docs. The `--mount` flag is still acceptable on a *fresh* colima setup with no other workloads, but the editing-the-yaml path is less footgun-prone.
- Documented the macOS Sequoia + VZ.framework RO-on-`$HOME` gate in all three docs. Granting Full Disk Access to `limactl` is a one-time fix the user can do later; the docs make clear the USB-only layout works without it.

**Blockers / Issues**: none — Story 1 Step 0 verified end-to-end on real hardware.

**Follow-ups / Risks (recorded but not closed by this session)**:
- Production container `ui-postgres-1` had `restart=no`; users with similar workloads should know that `colima stop` then `colima start` won't bring it back automatically. Documented in the live-validation context above; not a GenomeClaw concern.
- The `chmod -R a-w` belt-and-braces on `raw/` was dropped from Story 1 because the bind-mount-side `:ro` is sufficient for `INV-D001` and `chmod` may not work on exFAT-formatted USB drives. Documented inline in Story 1 Step 3.
- The shim currently always seeds `work/tmp`; if the user explicitly wants a tmpfs-only `$TMPDIR` they have to override `ENV TMPDIR` via `docker run -e`. Not adding a shim flag for this until someone asks.

---

## Key Decisions

### Decision 1: Four bind-mounts, not three plus an umbrella `state/`
**Date**: 2026-05-08
**Context**: A single combined `state/` directory containing both `derived/` and `work/` would save one mount but blur the ephemeral-vs-authoritative distinction.
**Decision**: Four named mounts.
**Rationale**: The discipline ("nothing in `work/` is authoritative") becomes structurally obvious to users. Cheaper to teach, harder to misuse.
**Alternatives Considered**: One umbrella `state/` mount with two subdirs; per-tool dedicated mounts.
**Affected Invariants**: `INV-R001` (strengthened structurally, not in Requirements text).

### Decision 2: `ENV TMPDIR` at image build, `GENOMECLAW_WORK_DIR` env var at the shim
**Date**: 2026-05-08
**Context**: The image and the shim both need to know where scratch goes. Picking the layer matters.
**Decision**: `TMPDIR` at the image (build time, fixed); `GENOMECLAW_WORK_DIR` at the shim (per-invocation, configurable host path).
**Rationale**: Makes the in-container contract image-internal (anything the image runs respects `$TMPDIR` automatically), while leaving the host-side path under the user's control.
**Alternatives Considered**: Pass `TMPDIR` via `docker run -e`; bind-mount only and not set `TMPDIR`.
**Affected Invariants**: none.

### Decision 3: Refuse if `work/` resolves inside `derived/`
**Date**: 2026-05-08
**Context**: Spec Q1.
**Decision**: shim exits 2 with a clear error when `GENOMECLAW_WORK_DIR` is under `GENOMECLAW_DERIVED_DIR`.
**Rationale**: Prevents Nextflow / DuckDB temp output from contaminating the authoritative store. Cheap to enforce, expensive to debug otherwise.
**Alternatives Considered**: Warn-only; rely on docs.
**Affected Invariants**: structurally protects `INV-R001` (no authoritative-vs-ephemeral confusion in `derived/`).

---

## Files Modified

### Created
- [`docs/plans/active/storage-scratch-layout/spec.md`](spec.md)
- [`docs/plans/active/storage-scratch-layout/development-plan.md`](development-plan.md)
- [`docs/plans/active/storage-scratch-layout/work-notes.md`](work-notes.md)
- [`docs/plans/active/storage-scratch-layout/phases/phase-1.md`](phases/phase-1.md)

### Modified
- [`packages/toolkit/Dockerfile`](../../../packages/toolkit/Dockerfile) — `mkdir -p .../work`; `ENV TMPDIR=/mnt/genomeclaw/work/tmp`.
- [`bin/genomeclaw-prep`](../../../bin/genomeclaw-prep) — `GENOMECLAW_WORK_DIR` env var (default `${HOME}/.genomeclaw/work`); host `mkdir -p`; refuse-if-inside-derived; fourth bind-mount.
- [`docs/reference/architecture.md`](../../reference/architecture.md) — `work/` in data-layout tree; expanded "Bind-mount discipline"; new "Storage planning" subsection.
- [`README.md`](../../../README.md) — new "Storage planning" section under "Designed For".
- [`docs/reference/user-stories.md`](../../reference/user-stories.md) — Story 1 "Step 0 — storage prep" block; subsequent steps renumbered + threaded through the shim; "scratch space unaccounted-for" gap struck through.
- [`docs/plans/active/mvp/phases/phase-2.md`](../mvp/phases/phase-2.md) — Verification block threads `GENOMECLAW_WORK_DIR`; new "Scratch / temp routing" paragraph documents the bcftools/DuckDB/Nextflow convention.

### Deleted
_(none expected)_

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None expected. Plan does not promote a new invariant.

### Other Documentation
- [ ] [`docs/reference/architecture.md`](../../reference/architecture.md) — `work/` in data-layout tree; bind-mount discipline expanded; new "Storage planning" subsection.
- [ ] [`README.md`](../../../README.md) — new "Storage planning" section.
- [ ] [`docs/reference/user-stories.md`](../../reference/user-stories.md) — Story 1 storage prep step.
- [ ] [`docs/plans/active/mvp/phases/phase-2.md`](../mvp/phases/phase-2.md) — Verification block threading.

---

## Open Risks & Follow-ups

- **colima storage drift**: README documents the reset path; not automated.
- **Wrapper-side enforcement is in future phases**: Phase 2 of MVP wires bcftools-sort + DuckDB to use `work/`; Phase 6 wires Nextflow.
- **`bin/genomeclaw-service` shim** (Phase 5) needs the same four-mount layout.
- **macOS `/mnt/` not standard**: Story 1 + README will tell macOS users to point env vars at `/Volumes/<USB>/genomeclaw/...`. The shim's host-side `mkdir -p` makes this graceful.

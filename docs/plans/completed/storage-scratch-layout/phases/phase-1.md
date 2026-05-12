# Phase 1: Add the `work/` mount end-to-end

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land the `work/` bind-mount across the `genomeclaw/toolkit` image, the `bin/genomeclaw-prep` host shim, the architecture / README / user-stories / MVP-Phase-2 docs in one coherent slice. After this phase: a fresh-checkout user can run the shim against the image, `/mnt/genomeclaw/work` is bind-mounted RW from a host path under their control, `$TMPDIR` inside the container resolves there, and the four-mount discipline ("nothing in `work/` is authoritative") is documented end-to-end.

## Scope Boundaries

- **In scope**:
  - `Dockerfile` build-time changes (mount point dir, chown, `ENV TMPDIR`).
  - `bin/genomeclaw-prep` shim changes (`GENOMECLAW_WORK_DIR` env var, host `mkdir -p`, fourth bind-mount, refuse-if-inside-derived sanity check).
  - Doc updates: architecture.md (data layout, host-side packaging, new Storage planning subsection); README (new Storage planning section); user-stories.md (Story 1 storage prep step); MVP phase-2.md Verification block.
  - Smoke verification (image rebuild + shim invocation + container introspection).
- **Out of scope**:
  - Subprocess-wrapper changes (`bcftools sort -T`, DuckDB `PRAGMA temp_directory`, Nextflow `-work-dir`) — they land in their own MVP phases (Phase 2, Phase 4, Phase 6).
  - `bin/genomeclaw-service` shim — lands in MVP Phase 5.
  - Automated cleanup of `work/` between runs.
  - Any schema changes (none).
  - Any new `INV-xxx`.

## Invariants Enforced in This Phase

The plan does not introduce new invariant tests. The phase reaffirms the unchanged status of the canonical seven via the existing toolkit smoke suite (which still passes after the change). Specifically:

- **INV-R001** Rebuildability — *structurally strengthened* by the four-mount discipline; the new shim refusal (Q1, "work cannot be inside derived") is the closest thing to a test for this in Phase 1, but it's a sanity check, not an invariant assertion.

All other invariants — `INV-D001`, `INV-D002`, `INV-E001`, `INV-P001`, `INV-P002`, `INV-C001` — are *unchanged* by this phase; the existing test naming scaffold (`tests/invariants/test_invXxxx_*.py`, currently empty placeholder dirs) is preserved.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

The shim does not yet accept `GENOMECLAW_WORK_DIR`. The image does not yet have `/mnt/genomeclaw/work`. We don't have a Bash test harness for the shim yet, so this phase's "RED" is exercised by command-line probes that fail today and will pass after Step 1.2.

**Probes that should fail before implementation, pass after**:

1. `docker run --rm genomeclaw/toolkit:dev sh -c 'echo $TMPDIR'` — should print `/mnt/genomeclaw/work/tmp`. **Today**: prints empty (TMPDIR not set in the image).
2. `docker run --rm genomeclaw/toolkit:dev sh -c 'test -d /mnt/genomeclaw/work && echo OK'` — should print `OK`. **Today**: directory does not exist; the `test -d` exits 1 with no output.
3. `WORKDIR=$(mktemp -d) && GENOMECLAW_WORK_DIR=$WORKDIR bin/genomeclaw-prep --help` — should exit 0 and the dir should be bind-mounted. **Today**: shim ignores the env var; the dir on the host is created (because we `mktemp -d` it) but never bind-mounted into the container. We can detect this by adding a side-effect probe (write a file inside the container, look for it on the host).
4. `RAW=$(mktemp -d); DERIVED=$(mktemp -d); WORK="$DERIVED/inside" && GENOMECLAW_DERIVED_DIR=$DERIVED GENOMECLAW_WORK_DIR=$WORK bin/genomeclaw-prep --help` — should exit non-zero with a "work cannot be inside derived" message. **Today**: shim doesn't know about `GENOMECLAW_WORK_DIR`, so it silently exits 0.

These four probes are the de-facto RED set. Run each, capture output, paste into [work-notes.md](../work-notes.md). Implementation in Step 1.2 turns them all green.

### Step 1.2 — GREEN: Minimal Implementation

**Dockerfile changes** ([packages/toolkit/Dockerfile](../../../../packages/toolkit/Dockerfile)):

```dockerfile
# Mount points for the on-disk layout that architecture.md documents.
RUN mkdir -p /mnt/genomeclaw/raw /mnt/genomeclaw/reference \
             /mnt/genomeclaw/derived /mnt/genomeclaw/work

# Default scratch directory points at the bind-mounted work/ volume.
# Tools that respect $TMPDIR (VEP, mosdepth, generic Python tempfile) write here.
ENV TMPDIR=/mnt/genomeclaw/work/tmp

# … chown over all four mount points (extends existing chown):
RUN groupadd --system --gid 1000 genomeclaw \
    && useradd --system --uid 1000 --gid genomeclaw --home-dir /home/genomeclaw \
        --create-home --shell /usr/sbin/nologin genomeclaw \
    && chown -R genomeclaw:genomeclaw /mnt/genomeclaw
```

(The `chown -R /mnt/genomeclaw` already extends to the new `work/` dir; only the `mkdir -p` line needs the new path.)

**Shim changes** ([bin/genomeclaw-prep](../../../../bin/genomeclaw-prep)):

1. Add `GENOMECLAW_WORK_DIR` to the documented env-var block (default `/mnt/genomeclaw/work`).
2. After resolving the four host paths, **abort** if `GENOMECLAW_WORK_DIR` resolves to a path *inside* `GENOMECLAW_DERIVED_DIR` (per spec Q1):
   ```bash
   work_real="$(cd "$work_dir" 2>/dev/null && pwd -P || echo "$work_dir")"
   derived_real="$(cd "$derived_dir" 2>/dev/null && pwd -P || echo "$derived_dir")"
   case "$work_real" in
     "$derived_real"|"$derived_real"/*)
       echo "genomeclaw-prep: GENOMECLAW_WORK_DIR ($work_dir) cannot be inside GENOMECLAW_DERIVED_DIR ($derived_dir)" >&2
       echo "  scratch and authoritative outputs must live on separate trees" >&2
       exit 2
       ;;
   esac
   ```
3. `mkdir -p "$work_dir"` on the host (only this mount auto-creates).
4. Add the fourth bind-mount unconditionally (since we just created it):
   ```bash
   mounts+=("--mount" "type=bind,source=${work_dir},target=/mnt/genomeclaw/work")
   ```

**Image rebuild + verification**:

```bash
docker build --tag genomeclaw/toolkit:dev packages/toolkit
docker run --rm genomeclaw/toolkit:dev sh -c 'echo $TMPDIR && test -d /mnt/genomeclaw/work && echo OK'
# Expected:
#   /mnt/genomeclaw/work/tmp
#   OK

WORKDIR=$(mktemp -d) bin/genomeclaw-prep --help        # exit 0; help banner

# refuse-if-inside-derived
DERIVED=$(mktemp -d)
WORK="$DERIVED/inside"
GENOMECLAW_DERIVED_DIR="$DERIVED" GENOMECLAW_WORK_DIR="$WORK" bin/genomeclaw-prep --help
# Expected: exit 2, message about scratch-cannot-be-inside-derived

# write probe (the work dir from inside the container is reachable on the host)
WORKDIR=$(mktemp -d)
GENOMECLAW_WORK_DIR=$WORKDIR \
  bin/genomeclaw-prep --help   # ignores arg; we want the side-effect path
# Then probe via a manual run:
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$WORKDIR,target=/mnt/genomeclaw/work" \
  genomeclaw/toolkit:dev sh -c 'touch /mnt/genomeclaw/work/probe.txt'
ls "$WORKDIR/probe.txt"   # should exist on the host
```

**Doc updates** (no shell verification — these are content edits):

- `docs/reference/architecture.md` — see "Implementation Details" below.
- `README.md` — see "Implementation Details" below.
- `docs/reference/user-stories.md` Story 1 — see "Implementation Details" below.
- `docs/plans/active/mvp/phases/phase-2.md` Verification block — see "Implementation Details" below.

### Step 1.3 — REFACTOR

With the shim probes green and the docs landed:

- Re-read the Dockerfile diff: confirm `mkdir -p` precedes the `chown` (so the new dir gets the right ownership).
- Re-read the shim diff: confirm the refuse-if-inside-derived check uses real paths (`pwd -P`) so it survives symlinks.
- Re-run all four probes from Step 1.1; record their now-green output in [work-notes.md](../work-notes.md).
- Confirm the existing toolkit smoke suite still passes:
  ```bash
  cd packages/toolkit
  uv run pytest -q
  uv run ruff check .
  uv run ruff format --check .
  ```

---

## Implementation Details

### `architecture.md` edits

In the "Data layout" section, the on-disk tree gets a fourth top-level entry:

```text
/mnt/genomeclaw/
├── raw/         (RO — Nebula FASTQ/BAM/CRAM/VCF; chmod-enforced read-only)
├── reference/   (RO at runtime; written only by `genomeclaw-prep fetch` and `pgsc_calc fetch-weights`)
├── derived/     (RW; pipeline writes <run-id>/ here — authoritative)
└── work/        (RW; ephemeral scratch — bcftools sort, DuckDB spill, Nextflow work,
                  $TMPDIR. Safe to delete between runs. Nothing here is authoritative.)
```

The "Host-side packaging — `genomeclaw/toolkit` Docker image" section's "Bind-mount discipline" gets a fourth bullet:

> - `/mnt/genomeclaw/work` — `:rw`. Ephemeral scratch — temp files, sort buffers, DuckDB spill, Nextflow work directories. The toolkit may delete contents at any time. **Nothing inside `work/` is authoritative.** If the host's local SSD is small, point `GENOMECLAW_WORK_DIR` at an external drive.

A new "Storage planning" subsection lands at the end of "Host-side packaging":

```markdown
### Storage planning (where to put each mount)

The four mounts have very different lifecycles and sizing profiles:

| Mount | Lifecycle | Typical size (one user, 30× WGS) | Recommended placement when local SSD is small |
|-------|-----------|----------------------------------|------------------------------------------------|
| `raw/` | Permanent (the source-of-truth artifacts) | 50–80 GB (FASTQ + BAM/CRAM + VCF) | External drive (USB, NAS, slow tier OK — read sequentially) |
| `reference/` | Slowly mutating (versioned downloads) | 50–100 GB once VEP cache + AlphaMissense + gnomAD slices + PGS Catalog land | External drive |
| `derived/` | Per-run, additive (each run is a new `<run-id>/`) | 1–2 GB per run; small enough for many runs to coexist | Local SSD acceptable; external drive also fine |
| `work/` | Ephemeral (deleted at user's discretion) | Up to multi-tens-of-GB during `pgsc_calc` Nextflow runs | External drive when local SSD is tight |

**Quick verification**: `du -sh /mnt/genomeclaw/{raw,reference,derived,work}` is the lifetime check.

The `bin/genomeclaw-prep` host shim takes four env vars (`GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, `GENOMECLAW_WORK_DIR`); set them once in your shell rc, point the heavy paths at the external drive, and forget about it.

For colima or Docker Desktop users on macOS: the external drive must be **mounted into the engine VM** before bind-mounts work. With colima:

```bash
colima stop
colima start --mount /Volumes/MyUSB:w --disk 80
# then point GENOMECLAW_RAW_DIR et al. at /Volumes/MyUSB/genomeclaw/...
```

(Docker Desktop has a comparable "File sharing" preference under Settings → Resources → File sharing.)

`work/` is always safe to delete: `rm -rf $GENOMECLAW_WORK_DIR/*` between runs is a perfectly normal hygiene step.
```

### `README.md` edits

Add a new section after "Designed For" (or alongside it, depending on the final flow):

```markdown
## Storage planning

GenomeClaw's host pipeline needs four directories, each with a different lifecycle and size profile. Plan placement before you ingest, especially if your local SSD is tight.

| Mount | Lifecycle | Size (one 30× WGS user) | Where to put it |
|-------|-----------|-------------------------|-----------------|
| `raw/` | Permanent — Nebula source-of-truth artifacts | 50–80 GB (FASTQ + BAM/CRAM + VCF) | External drive (USB / NAS) |
| `reference/` | Slowly versioned — annotation datasets | 50–100 GB once VEP cache + AlphaMissense + gnomAD + PGS Catalog land | External drive |
| `derived/` | Per-run — `<run-id>/` directories accumulate | 1–2 GB per run | Local SSD or external |
| `work/` | Ephemeral — temp / spill / Nextflow `work/` | Up to multi-tens-of-GB during `pgsc_calc` | External drive if local SSD is small |

The `bin/genomeclaw-prep` host shim picks up four env vars:

```bash
export GENOMECLAW_RAW_DIR=/Volumes/MyUSB/genomeclaw/raw
export GENOMECLAW_REF_DIR=/Volumes/MyUSB/genomeclaw/reference
export GENOMECLAW_DERIVED_DIR=$HOME/genomeclaw/derived            # local is fine
export GENOMECLAW_WORK_DIR=/Volumes/MyUSB/genomeclaw/work         # external when SSD is tight
```

The shim auto-creates `GENOMECLAW_WORK_DIR` on first run. The other three you stage yourself.

### macOS / colima users

The external drive must be **mounted into the engine VM** before any bind-mount works:

```bash
colima stop
colima start --mount /Volumes/MyUSB:w --disk 80
```

(Docker Desktop has the same idea under Settings → Resources → File sharing.)

### `work/` is always disposable

Nothing inside `$GENOMECLAW_WORK_DIR` is authoritative. `rm -rf $GENOMECLAW_WORK_DIR/*` between runs is normal hygiene. If a pipeline crashes mid-run, the next clean attempt starts from scratch — no state recovery in `work/`.

For the deeper architectural rationale, see [docs/reference/architecture.md § Host-side packaging — Storage planning](docs/reference/architecture.md#storage-planning-where-to-put-each-mount).
```

### `user-stories.md` Story 1 edits

Insert a new "Step 0 — storage prep" before the existing "ls /mnt/genomeclaw/raw" step. The user's actions section becomes:

```markdown
**Step 0 — storage prep (one-time)**:

The user's local SSD is ~30 GB free; their Nebula CRAM is on a USB drive. Following [the README's Storage planning section](../../README.md#storage-planning), they:

1. Mount the USB drive into colima:
   ```bash
   colima stop
   colima start --mount /Volumes/MyUSB:w --disk 60
   ```
2. Lay out the four canonical directories:
   ```bash
   mkdir -p /Volumes/MyUSB/genomeclaw/{raw,reference,work}
   mkdir -p $HOME/genomeclaw/derived          # local is fine — runs are 1–2 GB each
   ```
3. Point the shim at them (they add this to `~/.zshrc` once):
   ```bash
   export GENOMECLAW_RAW_DIR=/Volumes/MyUSB/genomeclaw/raw
   export GENOMECLAW_REF_DIR=/Volumes/MyUSB/genomeclaw/reference
   export GENOMECLAW_DERIVED_DIR=$HOME/genomeclaw/derived
   export GENOMECLAW_WORK_DIR=/Volumes/MyUSB/genomeclaw/work
   ```

That's the storage setup. They never think about it again.
```

The existing actions (`ls`, `genomeclaw-prep ingest`, etc.) stay the same — they already use `/mnt/genomeclaw/...` paths, which the shim now bind-mounts to the user's chosen host paths.

A new sentence in the "Surfaced gaps" section confirms `work/` lifecycle is documented:

```markdown
- ~~Pipeline scratch space (DuckDB spill, Nextflow `work/`, bcftools sort temp) is unaccounted-for in the host layout — risk of filling the local SSD on the user's actual hardware (30 GB free, 50 GB CRAM on USB).~~ ✅ Resolved by the [storage-scratch-layout](../plans/active/storage-scratch-layout/) plan: fourth canonical bind-mount `/mnt/genomeclaw/work` plus the README's Storage planning section.
```

### `docs/plans/active/mvp/phases/phase-2.md` Verification block edits

Thread `GENOMECLAW_WORK_DIR` through every shim invocation in the existing Verification block:

```bash
mkdir -p /tmp/genomeclaw-test/{raw,reference/grch38,derived,work}
GENOMECLAW_IMAGE=genomeclaw/toolkit:dev \
GENOMECLAW_RAW_DIR=$(pwd)/tests/fixtures \
GENOMECLAW_REF_DIR=/tmp/genomeclaw-test/reference \
GENOMECLAW_DERIVED_DIR=/tmp/genomeclaw-test/derived \
GENOMECLAW_WORK_DIR=/tmp/genomeclaw-test/work \
  ../../bin/genomeclaw-prep ingest \
    --vcf /mnt/genomeclaw/raw/tiny.vcf.gz \
    --bam /mnt/genomeclaw/raw/tiny.bam \
    --reference /mnt/genomeclaw/reference/grch38/ \
    --sample-id test-sample-001
```

Plus a one-liner in the "Tests that need real bcftools / mosdepth" paragraph: "Phase-2 wrappers route bcftools sort temp via `-T /mnt/genomeclaw/work/bcftools/`, DuckDB connections set `PRAGMA temp_directory='/mnt/genomeclaw/work/duckdb/'`. See [storage-scratch-layout](../../storage-scratch-layout/) plan."

### Edge Cases to Handle

- **`$GENOMECLAW_WORK_DIR` is on a tmpfs / RAM disk**: works, but obviously bounded — user's call.
- **`$GENOMECLAW_WORK_DIR` is the same physical drive as `$GENOMECLAW_DERIVED_DIR` but a different tree**: fine. The check is for path-containment, not physical-drive overlap.
- **`$GENOMECLAW_WORK_DIR` is a relative path**: the shim resolves it via `pwd -P` before the containment check, so a relative path that resolves outside `derived/` works correctly.
- **`$GENOMECLAW_WORK_DIR` doesn't exist and the host is a read-only filesystem**: `mkdir -p` fails; the shim error surfaces the underlying error message. Acceptable; no special handling.
- **The user runs the shim before mounting the USB into colima**: the shim's `mkdir -p` creates a dir on the macOS host, but colima can't bind-mount a path it doesn't know about. The user gets a docker-side mount error. Story 1's Step 0 covers this; the shim does not try to detect VM-mount state.

### Error Handling

- Refuse-if-inside-derived: exit 2, two-line stderr message naming both paths and the rule.
- `mkdir -p $work_dir` failure: bash propagates the error code; the shim exits with that code. Acceptable.

### Privacy / Egress Notes

- No new network egress points.
- No new secret-handling surfaces.
- The new mount carries the same privacy posture as `derived/`: host-only, never seen by the sandbox.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [`packages/toolkit/Dockerfile`](../../../../packages/toolkit/Dockerfile) | MODIFY | `mkdir -p .../work`; `ENV TMPDIR=/mnt/genomeclaw/work/tmp` |
| [`bin/genomeclaw-prep`](../../../../bin/genomeclaw-prep) | MODIFY | `GENOMECLAW_WORK_DIR` env var; host `mkdir -p`; fourth bind-mount; refuse-if-inside-derived check |
| [`docs/reference/architecture.md`](../../../reference/architecture.md) | MODIFY | data layout tree; bind-mount discipline; new "Storage planning" subsection |
| [`README.md`](../../../../README.md) | MODIFY | new "Storage planning" section |
| [`docs/reference/user-stories.md`](../../../reference/user-stories.md) | MODIFY | Story 1 "Step 0 — storage prep" block |
| [`docs/plans/active/mvp/phases/phase-2.md`](../../mvp/phases/phase-2.md) | MODIFY | Verification block threading |

---

## Verification

```bash
# Rebuild the image
docker build --tag genomeclaw/toolkit:dev packages/toolkit

# Probes that should all pass after Step 1.2
docker run --rm genomeclaw/toolkit:dev sh -c 'echo $TMPDIR'
# expect: /mnt/genomeclaw/work/tmp

docker run --rm genomeclaw/toolkit:dev sh -c 'test -d /mnt/genomeclaw/work && echo OK'
# expect: OK

WORKDIR=$(mktemp -d)
GENOMECLAW_WORK_DIR=$WORKDIR bin/genomeclaw-prep --help
# expect: exit 0; help banner; $WORKDIR exists on host (it always did from mktemp)

# write-through probe
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$WORKDIR,target=/mnt/genomeclaw/work" \
  genomeclaw/toolkit:dev sh -c 'touch /mnt/genomeclaw/work/probe.txt'
ls "$WORKDIR/probe.txt"
# expect: file exists on host

# refuse-if-inside-derived probe
DERIVED=$(mktemp -d)
GENOMECLAW_DERIVED_DIR=$DERIVED GENOMECLAW_WORK_DIR="$DERIVED/inside" \
  bin/genomeclaw-prep --help
# expect: exit 2 with "GENOMECLAW_WORK_DIR ... cannot be inside ..." message

# Toolkit smoke suite still passes
cd packages/toolkit
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

---

## Completion Criteria

- [ ] All four Step-1.1 probes pass after Step-1.2 implementation.
- [ ] Image rebuild succeeds; size is comparable to the previous build (one extra dir, one ENV — should not move size meaningfully).
- [ ] Refuse-if-inside-derived check fires under the test condition.
- [ ] `architecture.md` data-layout tree shows four mounts; "Host-side packaging" bind-mount discipline lists `work/`; new "Storage planning" subsection exists.
- [ ] `README.md` has the new "Storage planning" section.
- [ ] `user-stories.md` Story 1 has the "Step 0 — storage prep" block; the obsolete "scratch space unaccounted-for" gap entry is struck through.
- [ ] `docs/plans/active/mvp/phases/phase-2.md` Verification threads `GENOMECLAW_WORK_DIR` through the shim invocations.
- [ ] Existing toolkit smoke suite (`uv run pytest -q`, `ruff check`, `ruff format --check`) passes.
- [ ] [`work-notes.md`](../work-notes.md) updated with Step-1.1 RED probe output, Step-1.2 GREEN diff summary, and the final state.
- [ ] Phase 1 status set to **Complete** in [development-plan.md](../development-plan.md).
- [ ] No follow-on `phase-2.md` is created — this plan is single-phase.

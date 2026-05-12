# Phase 2: Setup Destructive Runner

**Status**: Complete (Option A architectural pivot — virtiofs-on-APFS)
**Started**: 2026-05-09
**Completed**: 2026-05-10
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-1.md](phase-1.md) (complete — non-destructive dry-run shipped)

> **Architectural pivot during implementation**: the original 12-step
> plan included a block-attached ext4 scratch image declared via lima
> `additionalDisks`. Real-data run on colima 0.9.1 / lima 1.2.1 / macOS
> Sequoia uncovered that **colima 0.9.1 silently strips
> `additionalDisks` from `colima.yaml` on start**. Block-attached
> scratch is unimplementable on this colima version. We pivoted to
> **Option A** — virtiofs everywhere, per-subdir RO/RW enforced at the
> docker bind-mount layer (the existing Phase-4A shim pattern), all on
> the new APFS partition. The 12-step sequence collapses to 9 steps;
> see [docs/reports/cram-scratch-strategy.md](../../../reports/cram-scratch-strategy.md)
> § Post-implementation discovery for the architectural rationale.

---

## Objective

After Phase 1 produces a `SetupPlan` and renders a preview, Phase 2 adds the typed-confirmation gate and the destructive runner that actually carries out the plan: stop colima, unmount + repartition the target drive as APFS, lay out `genomeclaw/{raw,reference,derived,_scratch}/`, copy the Nebula deliverable across, provision the 300 GB sparse `scratch.raw`, rewrite `~/.colima/default/colima.yaml` with the new mounts + lima `additionalDisks` block-device declaration, restart colima, and format + mount the block device as ext4 inside the VM. Every destructive operation writes to a JSON-Lines audit log so a failed run leaves enough provenance for manual recovery. By the end of Phase 2, the user's external drive is in the canonical CRAM-scale layout and a subsequent `genomeclaw-prep ingest` (Phase 4) finds `/mnt/genomeclaw/{raw,reference,derived,scratch}` mounted with the right flags.

## Scope Boundaries

- **In scope**:
  - Typed-confirmation gate ("type `WIPE /Volumes/<name>`" verbatim) wired into the existing `setup` interactive flow.
  - `prep/setup/audit.py` — JSON-Lines audit-log writer with rolling file rotation between temp and final locations.
  - `prep/setup/execute.py` — the executor: orchestrates the 12-step destructive sequence below; emits audit-log events before and after each step.
  - Destructive `Platform` methods: `unmount_disk`, `partition_disk_apfs`, `colima_stop`, `colima_start`, `provision_scratch_image`, `format_block_device_ext4`, `mount_block_device`, `verify_mounts`. Each shells out to the corresponding host command with structured stderr capture.
  - `prep/setup/_yaml_writer.py` — rewrites `~/.colima/default/colima.yaml` with the new `mounts:` block (3 virtiofs entries) and the `additionalDisks:` block-device declaration. Preserves any unrelated colima.yaml fields the user may have set (`cpu`, `memory`, `runtime`, etc.).
  - Source-resolver loosening: `_resolve_source_volume` now searches **all** volumes (including the system disk), so an internal-SSD Nebula deliverable + external target works. The same-disk safeguard from Phase 1 still catches the dangerous case (source and target on the same parent disk).
  - One-shot in-VM ext4 init for the freshly-attached block device. Lives in `execute.py` for now (a docker-run shellout against `genomeclaw/toolkit:dev` doing `blkid` + `mkfs.ext4 -L genomeclaw-scratch` + `tune2fs -m 5` + `mount`). Phase 3 generalizes this into a proper container-startup hook.
  - Resolution of spec Open Question Q5: confirmed colima 0.9.1 + lima 1.2.1 on the project owner's machine compose lima config from `~/.colima/default/colima.yaml` exclusively. No separate `~/.lima/colima/lima.yaml`. Q5 closed; pinned in this plan.

- **Out of scope** (explicitly defer):
  - Per-container-start mount-flag verification + 1 GB smoke test (Phase 3). Phase 2 does a one-time post-format smoke test inline; the every-start version comes later.
  - Pre-flight assertion library + orchestrator migration off `/tmp` (Phase 4).
  - `shard_scratch` / `atomic_promote` pipeline primitives (Phase 5).
  - `eject` / `doctor` subcommands (Phase 6).
  - Linux host support — `diskutil` is macOS-only. Linux follow-up plan.
  - Resume-after-failure semantics. The audit log captures enough state for *manual* recovery; programmatic resume is out of scope.
  - Multi-partition layouts (`Genome_Bulk` exFAT). The MVP does single-APFS only; the `Genome_Bulk` option from `docs/reports/cram-scratch-strategy.md` lands as a follow-up if a user actually needs cross-OS interop.

## Invariants Enforced in This Phase

- **INV-D001** Source-of-Truth — the move step computes per-file SHA256 of the source *before* copy and again at the target *after* copy; mismatch raises `DataIntegrityError` and the run aborts before the source is deleted. The audit log records both hashes. The runtime virtiofs RO mount discipline takes effect immediately after `colima_start`, so no pipeline path can mutate `raw/` thereafter.
- **INV-R001** Rebuildability — `_scratch/setup.log` captures `colima_version`, `lima_version`, `toolkit_version`, `started_at`, `completed_at`, `source_path`, `target_partition`, `target_parent_disk`, `target_filesystem_before`, `target_filesystem_after`, `scratch_image_path`, `scratch_image_bytes`, every per-file `(name, sha256_before, sha256_after, bytes)` triple, the resolved `colima.yaml` diff, and any subprocess return codes. A reviewer reading only the log can reconstruct what happened.
- **NEW INV-D003** (proposed; not yet promoted) — Phase 2 establishes the *physical layout* `INV-D003` constrains. The setup-time choice of block-attached scratch is the first opportunity to enforce it: tests assert the partition is APFS and the block device is ext4 (not virtiofs) post-setup.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

Tests live under `packages/toolkit/tests/integration/test_setup_execute.py` (orchestration + invariant) and `packages/toolkit/tests/unit/test_setup_audit.py` (audit-log shape). All tests use a `FakeDestructivePlatform` that records every method call without performing real partition/colima ops; the `tmp_path` fixture provides a synthetic source + a synthetic target dir that stand in for the Kingston.

**Test cases**:

1. `test_executor_refuses_without_typed_confirmation` — caller submits the wrong phrase (`WIPE wrong-name`); executor raises `ConfirmationMismatchError`; **no** destructive method on the platform was called. Verifies the typed-confirmation gate fails closed.

2. `test_executor_runs_steps_in_required_order` — caller submits the correct phrase; executor walks the 12-step sequence (see Implementation Details below); the platform's call log is `[colima_stop, unmount_disk, partition_disk_apfs, mkdir_layout, copy_nebula, verify_target_hashes, provision_scratch_image, write_colima_yaml, colima_start, format_block_device_ext4, mount_block_device, verify_mounts]`. Order is asserted exactly; out-of-order would mask sequencing bugs (e.g., `mkdir` before `partition` on a stale filesystem).

3. `test_invD001_executor_captures_source_hashes_before_destruction` — fake platform's `colima_stop` is rigged to fail; executor still has computed source SHAs (writes them to the audit log) before any destructive op. Verifies INV-D001's "source state captured before mutation" promise.

4. `test_invD001_executor_aborts_on_post_copy_hash_mismatch` — fake platform's `copy_nebula` writes corrupted bytes (different SHA); executor's `verify_target_hashes` step raises `DataIntegrityError`; the source files are still present (executor never reached the implicit "remove source" step); the audit log records the mismatch with both hashes. Verifies the data-integrity gate.

5. `test_invR001_audit_log_carries_required_fields` — at executor completion, `_scratch/setup.log` has at least one event whose payload includes `colima_version`, `lima_version`, `toolkit_version`, `started_at`, `completed_at`, `source_path`, `target_partition`, and the per-file hash table. Field presence is the assertion (not exact values, which depend on the host).

6. `test_audit_log_writes_temp_then_promotes_to_scratch` — `audit.AuditLog` initially writes to `~/.genomeclaw/setup-{ts}.log` (because `_scratch/` doesn't exist until step 4 of the executor); after `partition_disk_apfs` + `mkdir_layout` succeed, `audit.promote(scratch_dir)` moves the file to `<target>/_scratch/setup.log`. Test asserts both paths exist + contain the same byte content at the right times.

7. `test_audit_log_writes_event_per_step` — for a clean run, count(events) >= 12 (one per destructive step) + 2 (start/end). Each event has `step_name`, `phase` ∈ `{"start", "complete", "fail"}`, `ts`, and step-specific `payload`. Allows a future reviewer to walk the log linearly.

8. `test_executor_propagates_subprocess_failure_with_diagnostics` — fake platform's `partition_disk_apfs` returns a non-zero exit; executor raises `DestructiveStepError` carrying the captured stderr; the audit log gets a `phase="fail"` event with the same stderr embedded; subsequent steps are not attempted. Verifies fail-closed semantics.

9. `test_yaml_writer_preserves_unrelated_fields` — given a starting colima.yaml with `cpu: 4 / memory: 6 / runtime: docker / hostname: colima`, the rewriter sets `mounts:` and `additionalDisks:` to the canonical Phase-2 values and **leaves the other fields untouched**. Verifies we don't reset the user's preferences.

10. `test_yaml_writer_replaces_existing_mounts_block` — given a starting colima.yaml with the *old* Phase-4A mounts block (4 entries: raw/reference/derived/work), the rewriter replaces it with the Phase-2 3-entry block (raw/reference/derived) and adds `additionalDisks:`. Verifies the migration path from the old layout.

11. `test_resolve_source_volume_accepts_internal_disk` — given a Nebula path on a `is_system_disk=True` volume and an external target, `_resolve_source_volume` returns the system volume (does *not* raise). Verifies the resolver loosening that unblocks the project owner's "internal SSD source + external target" workflow.

12. `test_resolve_source_volume_still_rejects_same_disk` — given a Nebula path on `parent_disk=disk4` and a target volume also on `parent_disk=disk4`, `build_plan` raises `SameDiskError` (from Phase 1). Verifies the resolver loosening did NOT weaken the same-disk safeguard.

13. `test_invD003_post_setup_layout_is_canonical` — after a successful executor run against the synthetic fixture, `<target>/genomeclaw/{raw,reference,derived,_scratch}/` all exist; `<target>/genomeclaw/_scratch/scratch.raw` is exactly 300 GB (sparse); `<target>/genomeclaw/_scratch/setup.log` exists. The fake platform records that `format_block_device_ext4` was invoked with the scratch.raw path. Verifies the canonical post-setup layout (precondition for `INV-D003`'s "block-attached, not virtiofs" runtime check in Phase 4).

14. `test_executor_skips_colima_stop_if_not_running` — fake platform reports colima isn't running; executor calls `colima_stop` which the fake records as a no-op (return code 0); no error. Real-world: a fresh user's first `setup` run won't have colima up yet; executor must not require it.

After writing these tests, run them and confirm they fail with `ImportError: cannot import name 'execute' from 'genomeclaw_toolkit.prep.setup'` (or similar). Paste the failing output into `work-notes.md`.

### Step 2.2 — GREEN: Minimal Implementation

Files to create / modify (see Files table below for the full list). The implementation order matters because of how the modules cross-import:

1. **Source-resolver loosening** in `prep/setup/detect.py` — change `_resolve_source_volume` to call `plat.list_volumes()` directly (unfiltered) instead of `list_volumes(plat)` (which filters out the system disk). The same-disk safeguard in `assert_different_physical_disk` still triggers, so the dangerous case (source and target on the same `parent_disk`) is still rejected. **One-line change; flips Phase 2 tests #11 and #12 immediately.**

2. **Destructive Platform methods** in `prep/setup/platform.py` — extend the `Platform` Protocol with the eight method signatures listed in Scope. Add real implementations to `MacOSPlatform` (subprocess shellouts to `colima`, `diskutil`, `truncate`, `docker run`).

3. **Audit log** in `prep/setup/audit.py` — `AuditLog(temp_path).event(step_name, phase, payload)` writes one JSON object per line; `AuditLog.promote(scratch_dir)` atomically moves the file from temp to `<scratch_dir>/setup.log`.

4. **YAML writer** in `prep/setup/_yaml_writer.py` — load `~/.colima/default/colima.yaml`, replace the `mounts:` block, replace or insert `additionalDisks:`, write back. Uses `pyyaml` (already in the toolkit's dep tree via duckdb? — check at GREEN-time and add to `pyproject.toml` if not).

5. **Executor** in `prep/setup/execute.py` — `execute(plan, platform, *, confirmation_phrase, audit_log)`. Twelve steps; each wraps a platform method call with `audit_log.event(..., "start")` / `..., "complete")` / `..., "fail")`. Returns the path to the final audit log.

6. **CLI flow** in `detect.run_interactive` — after rendering the preview, prompt for the typed-confirmation phrase. If it matches `plan.confirmation_phrase`, call `execute(plan, platform, confirmation_phrase=typed, audit_log=...)`. If not, print "confirmation phrase did not match; aborting" and exit non-zero.

7. **Source-resolver test cases** for the loosening (already in tests #11, #12).

### Step 2.3 — REFACTOR

With tests green:

- Extract a `_run_subprocess(platform_method)` helper if the same try/except/audit-log pattern repeats more than 3 times across the executor (rule of three).
- Tighten `DestructiveStepError` to carry the step name + captured stderr + return code; the bare-string variant is enough for tests but doctor (Phase 6) wants structured fields.
- Drop any unused fields from `SetupPlan` if Phase 2 doesn't actually consume them (the dataclass was sketched broadly during Phase 1).
- Re-run tests after each refactor step.

---

## Implementation Details

### The 12-step destructive sequence

Order is load-bearing. Each step is a method on `Platform`; the executor calls them in this exact order. Audit-log events bracket each step.

1. **`colima_stop`** — best-effort; no-op if colima isn't running. Required because the next step needs the drive un-held.
2. **`unmount_disk(parent_disk)`** — `diskutil unmountDisk /dev/<diskN>`. Releases the drive for partition.
3. **`partition_disk_apfs(parent_disk, "Genome_Work")`** — `diskutil partitionDisk /dev/<diskN> 1 GPT APFS Genome_Work R`. Creates one APFS partition consuming the whole drive; auto-mounts at `/Volumes/Genome_Work`.
4. **`mkdir_layout("/Volumes/Genome_Work/genomeclaw/")`** — creates `raw/`, `reference/`, `derived/`, `_scratch/` directly via `os.makedirs`. No subprocess.
5. **`copy_nebula(source, target)`** — host-side `shutil.copy2` per file (cross-fs copy with metadata). Computes SHA256 incrementally during read. Records `(name, src_sha256, dst_sha256, bytes)` in the audit-log event.
6. **`verify_target_hashes(records)`** — pure check: every `(src_sha256, dst_sha256)` pair matches. Raises `DataIntegrityError` on any mismatch. **Source files are NOT removed** — the original copy stays intact. (Future enhancement: a separate `purge_source` step the user opts into post-verification. For Phase 2, source stays; user manually deletes when satisfied.)
7. **`provision_scratch_image("/Volumes/Genome_Work/genomeclaw/_scratch/scratch.raw", 300 * 1024**3)`** — `truncate -s 300G <path>`. Sparse file; the actual blocks aren't allocated until ext4 writes to them.
8. **`write_colima_yaml(plan)`** — rewrites `~/.colima/default/colima.yaml` per the YAML-writer module. Backs up the previous version to `~/.colima/default/colima.yaml.bak.{ts}` first.
9. **`colima_start()`** — `colima start`. Lima creates the block device on first start with the new `additionalDisks` declaration.
10. **`format_block_device_ext4(label="genomeclaw-scratch")`** — one-shot `docker run --rm --privileged genomeclaw/toolkit:dev` that runs `blkid /dev/vdb` + (if no FS) `mkfs.ext4 -L genomeclaw-scratch /dev/vdb` + `tune2fs -m 5 /dev/vdb`. Idempotent: re-running the executor against an already-formatted disk skips mkfs.
11. **`mount_block_device(target="/mnt/genomeclaw/scratch")`** — second one-shot docker run; mounts and verifies via `df -h /mnt/genomeclaw/scratch`.
12. **`verify_mounts(expected)`** — third one-shot docker run; reads `/proc/self/mountinfo` and asserts `raw` is `ro`, `reference` is `ro`, `derived` is `rw`, `scratch` is `rw + ext4`. Mismatch → `MountFlagError` carrying the offending line.

After step 12: write the final audit-log event with `started_at`, `completed_at`, the resolved diff. Print a summary line: `setup: ok — scratch 300 GB provisioned, derived 1.4 TB free`.

### Audit-log schema (JSON Lines)

One JSON object per line. Each object:

```json
{
  "ts": "2026-05-09T12:34:56Z",
  "step": "partition_disk_apfs",
  "phase": "complete",
  "payload": { "parent_disk": "disk4", "label": "Genome_Work", "stderr": "" }
}
```

`step` ∈ {12 destructive steps + `setup_started` + `setup_completed`}. `phase` ∈ `{"start", "complete", "fail"}`. `payload` is step-specific; the start/complete events for `copy_nebula` are the bulkiest because they carry the per-file hash table.

### Test rig — fake destructive platform

`tests/integration/test_setup_execute.py` defines a `FakeDestructivePlatform` extending the Phase-1 `_FakePlatform`:

- All 8 destructive methods are mocked. They append `(method_name, args, kwargs)` to `self.call_log`.
- Each method has a `failure_mode` knob: `None` (default), `"return_code_2"`, `"stderr_only"`, `"corrupt_data"` (for `copy_nebula` — writes wrong bytes).
- The fake `mkdir_layout` and `provision_scratch_image` actually create directories and files under the `tmp_path`-based fake target — so post-setup layout invariants can be verified without real disks.
- The fake `format_block_device_ext4` records the call but doesn't actually format anything (the synthetic target dir isn't a real block device).

This lets us assert call order, error propagation, and post-state layout without touching a real partition.

### Source-resolver loosening — exact diff

In `prep/setup/detect.py`, `_resolve_source_volume`:

```python
# BEFORE (Phase 1):
def _resolve_source_volume(volumes: list[Volume], nebula_dir: Path) -> Volume:
    """Return the volume that contains nebula_dir; require an exact prefix match."""

# AFTER (Phase 2):
def _resolve_source_volume(all_volumes: list[Volume], nebula_dir: Path) -> Volume:
    """Return the volume that contains nebula_dir.
    
    Searches *all* volumes — including the system disk — because the
    project owner's typical workflow has the Nebula deliverable on the
    internal SSD (system disk) and the target on an external drive.
    The same-disk safeguard in assert_different_physical_disk still
    rejects the dangerous case.
    """
```

Caller (`build_plan`) changes from `list_volumes(plat)` to `plat.list_volumes()` for the source-resolution step. The target resolution still uses the filtered list (system disk is never a valid target).

### Edge Cases to Handle

- **colima not installed** — pre-flight `which colima` in the executor; raise `ColimaNotInstalledError` with a brew-install hint before any destructive step. Caught by a Phase-1-style assertion in `build_plan`, not Phase 2 itself, but Phase 2's executor double-checks.
- **Drive already partitioned as APFS Genome_Work from a previous setup** — spec Q2 ("adopt existing layout"). For Phase 2 MVP: detect via `diskutil info -plist`, if the partition is already APFS + named `Genome_Work` AND `genomeclaw/` exists, skip steps 2–4 and resume from step 5 (copy data). This is the "re-run setup safely" path. Out of scope for the first pass — Phase 2 just refuses with a specific error: "target already has Genome_Work partition; adopt-existing path lands in Phase 2.x."
- **scratch.raw already exists** — same as above; if it's the right size, skip step 7. Out of scope for first pass.
- **Source has > 100k files** — `copy_nebula` should batch SHA computation in a streaming loop, not load files into memory. A 55 GB CRAM is one big file, so this isn't a real concern for the project owner's case, but the implementation should handle it correctly anyway.
- **User typed phrase has trailing whitespace** — strip both sides before comparison; document in error message ("type the phrase exactly as shown above").
- **Target drive has data the user forgot about** — addressed by the typed-confirmation gate. Pre-confirmation, the dry-run preview lists what will be wiped.
- **colima.yaml has YAML constructs the writer doesn't preserve** (anchors, aliases, etc.) — write a structural roundtrip test that loads + re-dumps and asserts byte equivalence on a synthetic fixture with anchors. If the writer can't preserve them, fail loud and tell the user to flatten their colima.yaml before running setup.
- **The Mac is on battery** — power loss mid-setup is recoverable via the audit log + APFS journal. ext4 isn't formatted yet at the point colima.yaml is written. We document but don't add automation.
- **User runs setup twice in quick succession** — the first run leaves the audit log under `~/.genomeclaw/setup-{ts}.log` (because `_scratch/` may not exist on the failure path). Second run gets a fresh timestamped log. No collision.

### Error Handling

- All destructive-step errors are `SetupError` subclasses (sit alongside Phase 1's `NebulaDeliverableError` etc.).
- `DestructiveStepError` carries `step_name`, `return_code`, `stderr`, plus a one-sentence remediation hint when known (e.g., "diskutil partitionDisk failed: drive may be held by Spotlight indexer; run `mdutil -i off /Volumes/<name>` and retry").
- `DataIntegrityError` carries `file_name`, `expected_sha256`, `observed_sha256`, `bytes_copied`. Always indicates a real bug — surfaces with maximum diagnostic detail.
- `MountFlagError` carries the offending mount line verbatim. The fix is almost always "edit colima.yaml manually; re-run colima start."
- `ConfirmationMismatchError` is the gentle one — just "phrase didn't match; nothing changed; type it again or abort."

### Privacy / Egress Notes

- No new egress points. Same as Phase 1.
- Audit log contains paths and SHAs of the user's genomic files. Lives on the user's drive only; never written to `derived/` (which can flow to NemoClaw). Phase 6 doctor surfaces a summary, not the full log.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/detect.py` | MODIFY | Loosen `_resolve_source_volume` to allow internal-SSD sources; update `run_interactive` to add typed-confirmation gate and call `execute`. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/platform.py` | MODIFY | Extend `Platform` Protocol with 8 destructive method signatures; add real implementations to `MacOSPlatform` (subprocess shellouts). |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/audit.py` | CREATE | JSON-Lines audit-log writer with temp-then-promote semantics. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/execute.py` | CREATE | The executor: orchestrates the 12-step destructive sequence. Pure logic; takes a `Platform` for all I/O. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_yaml_writer.py` | CREATE | Surgically rewrites `~/.colima/default/colima.yaml`. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` | MODIFY | Re-export `execute`, `AuditLog`, the new error classes. |
| `packages/toolkit/pyproject.toml` | MODIFY (maybe) | Add `pyyaml` if not already present (the YAML writer needs round-trip-safe parsing). |
| `packages/toolkit/tests/integration/test_setup_execute.py` | CREATE | 14 RED tests above (orchestration, INV-D001, INV-R001, NEW INV-D003 layout). |
| `packages/toolkit/tests/unit/test_setup_audit.py` | CREATE | Audit-log shape, temp-then-promote semantics, per-step event coverage. |
| `packages/toolkit/tests/unit/test_setup_yaml_writer.py` | CREATE | YAML preservation + replacement tests. |
| `packages/toolkit/tests/integration/conftest.py` | MODIFY | Add `fake_destructive_platform` fixture. |
| `docs/plans/active/cram-scratch-strategy/work-notes.md` | MODIFY | Append Phase 2 RED-state output and GREEN-state summary. |
| `docs/plans/active/cram-scratch-strategy/development-plan.md` | MODIFY | Update Progress Tracking row for Phase 2. |
| `docs/reference/user-stories.md` | MODIFY | Step 0 already mentions Phase 2's typed-confirmation gate (Phase 1 wording was forward-looking). Confirm wording matches what shipped. |

---

## Verification

```bash
# Run this phase's tests
cd packages/toolkit
uv run pytest tests/integration/test_setup_execute.py tests/unit/test_setup_audit.py tests/unit/test_setup_yaml_writer.py -v

# Run all tests (regression check)
uv run pytest

# Type check
uv run mypy src/

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

**Real-data validation** (after mocked tests are green; gated on the user's explicit "go ahead"):

```bash
# Pre-flight: confirm Kingston (or Samsung T7 Shield) is connected at /Volumes/Genome.
diskutil list

# Run setup; type the WIPE phrase when prompted; expect it to print a summary.
bin/genomeclaw-prep setup

# Post-run: verify the layout.
ls /Volumes/Genome_Work/genomeclaw/{raw,reference,derived,_scratch}/
ls /Volumes/Genome_Work/genomeclaw/_scratch/scratch.raw
cat /Volumes/Genome_Work/genomeclaw/_scratch/setup.log | jq .

# Inside the VM, confirm the mounts.
docker run --rm --user "$(id -u):$(id -g)" --entrypoint sh genomeclaw/toolkit:dev \
    -c 'mount | grep -E "/mnt/genomeclaw/(raw|reference|derived|scratch)"'
# Expected:
#   /mnt/genomeclaw/raw       virtiofs  ro
#   /mnt/genomeclaw/reference virtiofs  ro
#   /mnt/genomeclaw/derived   virtiofs  rw
#   /mnt/genomeclaw/scratch   ext4      rw

# Confirm the Phase-4A pipeline still runs end-to-end against the new layout.
# (This is technically Phase 4 territory but is the simplest end-to-end sanity check.)
RUN_ID=$(readlink /Volumes/Genome_Work/genomeclaw/derived/CURRENT 2>/dev/null || echo "")
if [[ -n "$RUN_ID" ]]; then
    bin/genomeclaw-prep annotate --run-dir "/mnt/genomeclaw/derived/$RUN_ID" \
        --reference-dir /mnt/genomeclaw/reference
fi
```

---

## Completion Criteria

- [ ] All 14 listed test cases pass (RED → GREEN → REFACTOR cycle visible in commits)
- [ ] Static checks pass (`mypy` + `ruff`)
- [ ] `INV-D001` test (`test_invD001_executor_aborts_on_post_copy_hash_mismatch`) passes
- [ ] `INV-R001` test (`test_invR001_audit_log_carries_required_fields`) passes
- [ ] Proposed `NEW INV-D003` test (`test_invD003_post_setup_layout_is_canonical`) passes
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures or repo
- [ ] **Real-data run**: `bin/genomeclaw-prep setup` against the actual Kingston (interim) succeeds end-to-end. Post-state matches the canonical layout. Audit log is well-formed and round-trips through `jq`. Phase-4A annotate still runs against the new mounts.
- [ ] Source files under `data/raw/MPNRGLQ2K` are intact post-run (we do not auto-purge; the user purges manually after verifying the copy).
- [ ] `work-notes.md` updated with RED state, decisions, real-run timeline, audit-log excerpt
- [ ] Phase status updated in `development-plan.md`
- [ ] Phase 2 plan file (this document) status flipped to Complete
- [ ] `phases/phase-3.md` drafted as the next slice

# Phase 1: Setup Foundation + Dry-Run

**Status**: Complete
**Started**: 2026-05-09
**Completed**: 2026-05-09
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land a non-destructive `genomeclaw-prep setup` subcommand. After this phase, a user can run `setup`, see exactly what it would do (dry-run preview), and bail without any side effect on either the source or target drive. Detection logic correctly identifies mounted volumes, validates the Nebula deliverable, and refuses to proceed when source and target resolve to the same physical disk. `user-stories.md` Story 1 Step 0 is rewritten to describe the new flow. **No code path in this phase mutates the host filesystem outside the test sandbox.**

The destructive operations (partition, format, move data, edit YAML) are explicitly **deferred to Phase 2**. The dry-run output of this phase becomes the input that Phase 2 executes after the typed-confirmation gate.

## Scope Boundaries

- **In scope**:
  - `genomeclaw-prep setup` subcommand wired through the host shim and `cli.py`.
  - `prep/setup/detect.py` — disk/volume detection on macOS via `diskutil list -plist` and parent-disk identity.
  - `prep/setup/dryrun.py` — render a `SetupPlan` dataclass to a human-readable preview.
  - Synthetic disk fixture (loop-mounted sparse images) the test rig uses to mimic two distinct physical disks.
  - `user-stories.md` Story 1 Step 0 rewritten to describe the new flow (drafted here; finalized in Phase 6 once the implementation is real).
  - Reading `bcftools view -h` against candidate Nebula VCFs to validate format (uses the existing toolkit container).

- **Out of scope** (explicitly defer):
  - Any actual partitioning, formatting, or file movement (Phase 2).
  - Any colima or lima YAML edits (Phase 2).
  - VM-side ext4 init + mount discipline (Phase 3).
  - Pre-flight assertion library (Phase 4).
  - `eject` and `doctor` subcommands (Phase 6).
  - README "Storage planning" rewrite (drafted here, finalized Phase 6).

## Invariants Enforced in This Phase

- **INV-D001** Raw Genomic Files Are Source-of-Truth — Phase 1 must not mutate any source genomic file. The dry-run path must be observably side-effect-free against both source and target drives. Verified by content-hash assertions before/after the test runs (see Step 1.1.).
- **INV-P001** Privacy Default — `setup` makes no network calls during detection or dry-run. Verified by an `httpserver` fixture that asserts zero requests during a full dry-run pass.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

Tests live in `packages/toolkit/tests/integration/test_setup_dryrun.py` (and a few unit tests under `packages/toolkit/tests/unit/test_setup_detect.py` for the parsing pieces).

**Test cases**:

1. `test_detect_lists_external_volumes_and_skips_system_disk` — given a mocked `diskutil list -plist` response with three volumes (one system, two external), `detect.list_volumes()` returns the two external volumes and excludes the system disk. Catches the regression where system-disk shows up as a partition target.

2. `test_detect_validates_nebula_deliverable_happy_path` — point detection at a directory containing `sample.vcf.gz`, `sample.vcf.gz.tbi`, `sample.bam`. Returns a `NebulaDeliverable` dataclass with sample-id, present-files, header-checked-ok=True. The header check shells out to the toolkit image's `bcftools view -h`.

3. `test_detect_rejects_nebula_dir_with_no_recognizable_files` — point at an empty dir. Raises `NebulaDeliverableError` with a message naming the dir and listing what's expected.

4. `test_detect_rejects_nebula_vcf_with_corrupt_header` — point at a dir containing a `sample.vcf.gz` whose first 1 KB is random bytes. The `bcftools view -h` call exits non-zero; detection raises `NebulaDeliverableError` with the bcftools error message embedded.

5. `test_detect_parent_disk_identity_same_disk_rejected` — given two paths that resolve (per `diskutil info -plist`) to the same parent `/dev/disk4`, `detect.assert_different_physical_disk(src, dst)` raises `SameDiskError` with a message naming the disk identifier.

6. `test_detect_parent_disk_identity_different_disks_accepted` — given two paths resolving to different parents, the same call returns silently.

7. `test_dryrun_renders_complete_preview` — given a `SetupPlan(source=..., target=..., partitions=[...], moves=[...], yaml_diffs={...})`, `dryrun.render(plan)` returns a multi-section text block containing: partition table changes, files moved (with sizes), files created, colima.yaml diff, lima.yaml diff. Snapshot test against a fixed plan.

8. `test_dryrun_preview_does_not_touch_filesystem` — run `dryrun.render(plan)` against a fixture that has both src and dst dirs writable. Capture content-hash of every file under both before and after. Assert no change. **Enforces INV-D001 for Phase 1.**

9. `test_setup_cli_with_no_args_starts_interactive_flow` — invoking `genomeclaw-prep setup` with no args goes through the interactive prompts (mocked stdin); produces a `SetupPlan`; renders it; exits 0 without confirmation phrase being typed.

10. `test_setup_cli_with_invalid_nebula_path_exits_2` — invoking `setup` interactively, user provides a Nebula path that fails validation. Process exits 2 with the validation error on stderr.

11. `test_invD001_dryrun_does_not_mutate_source_or_target` — explicit invariant test: SHA256 of every file under the source and target drives is unchanged after a dry-run pass. Citation: `INV-D001` in test name.

12. `test_invP001_setup_makes_zero_outbound_calls` — `httpserver` fixture; full setup interactive flow with mocked stdin; asserts zero requests reached the server. Citation: `INV-P001` in test name.

13. `test_detect_reads_drive_model_and_firmware` — given a mocked `diskutil info -plist` response for a Samsung T7 Shield 2 TB, `detect.read_drive_identity(target)` returns `DriveIdentity(model="Samsung Portable SSD T7 Shield", firmware="...", capacity_gb=2000, ...)`. For a non-validated drive (different model / brand), model + firmware are returned as informational.

14. `test_detect_rejects_known_bad_firmware` — given a mocked drive identity whose `(model, firmware)` pair appears in the known-bad data file, `detect.assert_firmware_safe(identity)` raises `KnownBadFirmwareError` with a message naming the model + revision and pointing the user at the vendor's firmware updater. Verifies the gate triggers before any destructive op is queued. Test fixture seeds the known-bad data file with a synthetic entry (e.g., `Test Vendor Bad Drive` firmware `BAD-001`) so the test is independent of any real-world advisory state. A second assertion in the same test confirms that a Samsung T7 Shield with a non-listed firmware revision passes the gate (the known-bad list is currently empty for that model).

15. `test_detect_rejects_insufficient_space_with_breakdown` — target drive has 100 GB free but the configured plan needs 360 GB. `detect.assert_sufficient_space(target, plan)` raises `InsufficientSpaceError` with: shortfall in GB; per-component breakdown (raw N GB, reference N GB, scratch.raw N GB, margin 50 GB); the chosen reference set's name. Verifies the safety-belt path for users running setup against a non-validated drive (spec § AC3 free-space check).

**Sketch** (Python / pytest):

```python
# tests/integration/test_setup_dryrun.py

def test_detect_parent_disk_identity_same_disk_rejected(
    same_disk_fixture: SameDiskFixture,
) -> None:
    """Phase 1: detection must reject source and destination on the same physical disk."""
    from genomeclaw_toolkit.prep.setup.detect import (
        SameDiskError,
        assert_different_physical_disk,
    )

    src, dst = same_disk_fixture.src_path, same_disk_fixture.dst_path
    with pytest.raises(SameDiskError, match="/dev/disk4"):
        assert_different_physical_disk(src, dst)


def test_invD001_dryrun_does_not_mutate_source_or_target(
    two_disk_fixture: TwoDiskFixture,
) -> None:
    """INV-D001: dry-run must be side-effect-free across both drives."""
    from genomeclaw_toolkit.prep.setup.detect import build_plan
    from genomeclaw_toolkit.prep.setup.dryrun import render

    before = two_disk_fixture.snapshot_all_hashes()
    plan = build_plan(
        source=two_disk_fixture.nebula_dir,
        target=two_disk_fixture.target_volume,
    )
    output = render(plan)
    assert "WIPE" in output  # the confirmation phrase appears in the preview
    after = two_disk_fixture.snapshot_all_hashes()
    assert before == after, "dry-run mutated the filesystem"
```

After writing these tests, run them and **confirm they fail for the intended reason** (`ImportError: cannot import name 'SameDiskError'`, `ModuleNotFoundError: genomeclaw_toolkit.prep.setup.detect`, etc.). Paste the failing output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

Write the smallest implementation that turns the tests green:

1. **`prep/setup/__init__.py`** — package marker; re-exports `detect`, `dryrun`.

2. **`prep/setup/detect.py`** — three responsibilities:
   - `list_volumes() -> list[Volume]`. Shells out to `diskutil list -plist` (or accepts an injected `Platform` for tests). `Volume` dataclass: `name`, `mount_point`, `size_bytes`, `parent_disk`, `filesystem`.
   - `validate_nebula(path: Path) -> NebulaDeliverable`. Walks the directory, checks for at least one of `*.vcf.gz`, `*.cram`, `*.bam`, `*.fastq.gz`. Runs `bcftools view -h` against a present `*.vcf.gz` (uses the toolkit image; in tests, mocked).
   - `assert_different_physical_disk(src: Path, dst: Path) -> None`. Resolves each to its parent disk via `diskutil info -plist`; raises `SameDiskError` if they match.

3. **`prep/setup/dryrun.py`** — one responsibility:
   - `render(plan: SetupPlan) -> str`. Pure function; no I/O. Sections: partition table changes, files moved, files created, colima.yaml diff, lima.yaml diff. The output includes the confirmation phrase the user would type to proceed (e.g., `WIPE /Volumes/MyUSB`).

4. **`SetupPlan` dataclass** in `prep/setup/__init__.py` (or `prep/setup/_types.py`). Frozen, fully serializable to JSON.

5. **CLI wiring**: add a `_add_setup` / `_run_setup` pair to `cli.py`. In Phase 1, `_run_setup` calls into detection + dry-run, emits the preview to stdout, and exits 0. The typed-confirmation prompt and execution gate happen in Phase 2.

6. **Test rig**: `tests/conftest.py` (or a new `tests/integration/conftest.py`) gains a `two_disk_fixture` and a `same_disk_fixture` that each create loop-mounted sparse images on macOS / tmpfs on Linux CI. The fixture exposes `snapshot_all_hashes()` for the invariant test.

**Files affected**:

- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` — CREATE
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/detect.py` — CREATE
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/dryrun.py` — CREATE
- `packages/toolkit/src/genomeclaw_toolkit/cli.py` — MODIFY (add `setup` subcommand, dispatch into the new modules)
- `bin/genomeclaw-prep` — MODIFY (route `setup` through the existing docker-run path so detection happens inside the container)
- `packages/toolkit/tests/integration/test_setup_dryrun.py` — CREATE
- `packages/toolkit/tests/unit/test_setup_detect.py` — CREATE
- `packages/toolkit/tests/integration/conftest.py` — MODIFY (add the two-disk and same-disk fixtures)
- `docs/reference/user-stories.md` — MODIFY (Story 1 Step 0 rewritten)
- `README.md` — MODIFY (Storage planning section drafted; finalized Phase 6)

### Step 1.3 — REFACTOR

With tests green:

- Tighten `Volume` and `NebulaDeliverable` dataclass fields. Drop any field no test exercises.
- Extract a `Platform` protocol if the test rig has duplicated mock setup across test files (rule of three).
- Add comments only where the *why* is non-obvious — specifically: the parent-disk identity comparison (`why diskutil info -plist and not realpath`), the `bcftools view -h` validation choice (`why we run it inside the container, not on the host`).
- Re-run tests after each refactor step.

---

## Implementation Details

### Specific technical points

- **Why detection runs inside the toolkit container**: validating a Nebula VCF requires `bcftools`. We already ship `bcftools` in the toolkit image. Running detection on the host would either require a host-side `bcftools` install (defeating the toolkit-image-as-source-of-truth principle) or skipping VCF validation (defeating the "fail at setup, not at first run" goal). The host shim therefore dispatches `setup` into the container the same way it does every other subcommand.
- **macOS-first `diskutil` parsing**: `diskutil list -plist` and `diskutil info -plist <identifier>` return XML plist. Use Python's `plistlib` (stdlib). No third-party plist library.
- **Linux test environment**: CI runs tests on Linux. The `Platform` protocol abstracts `list_volumes()` and `parent_disk()` so tests can inject a fake. Real Linux production support is a follow-up plan; this phase needs only enough Linux abstraction to test on CI.
- **Same-disk detection**: must compare *parent disk identifiers* (e.g., `disk4`), not mount points or paths. Two partitions on the same physical drive are still on the same drive. `diskutil info -plist` returns `ParentWholeDisk` for any partition; that's the canonical comparison key.
- **Sparse-image test rig**: on macOS, `hdiutil create -size 100m -fs APFS -volname …`. On Linux CI, loop-mount via `losetup`. Both wrapped in a fixture that yields paths and tears down on session end.

### Edge Cases to Handle

- Nebula deliverable directory contains a corrupt `*.vcf.gz` whose `bcftools view -h` fails → surface the bcftools error verbatim.
- Nebula deliverable directory contains a `*.vcf.gz` that's actually `gzip`-compressed (not `bgzip`) → `bcftools view -h` will fail; surface the specific error.
- User points detection at a disk image, not a mounted volume → `diskutil info -plist` returns nothing useful; raise `VolumeNotMountedError`.
- User points detection at the system disk → exclude system disk from `list_volumes()`; if explicitly specified by mount-point, raise `SystemDiskRefusedError`.
- Source and target are different mount points but resolve to the same `ParentWholeDisk` (e.g., two partitions on one drive) → `SameDiskError`.
- Target volume has insufficient free space (computed from raw size + reference set + scratch image + 50 GB margin per spec AC3) → `InsufficientSpaceError` with the specific shortfall in GB and the breakdown.
- Target drive's `(model, firmware)` pair matches the known-bad data file (no entries today for the validated Samsung T7 Shield, but the gate stays in place for future advisories or non-validated drives) → `KnownBadFirmwareError` naming the model + revision and pointing at the vendor's firmware updater. Triggered before any destructive op is queued.
- Target drive is *not* the validated Samsung T7 Shield (different model / brand) → setup proceeds; the drive's model + firmware are surfaced as informational in the dry-run preview, and the firmware-check gate applies the same known-bad-list lookup against whichever entries are present for that model.

### Error Handling

- Each error class above is a subclass of a common `SetupError`. The CLI layer in `cli.py` catches `SetupError`, prints `f"genomeclaw-prep setup: {error}"` to stderr, exits 2.
- No error includes a stack trace in the user-facing message. Stack traces go to a debug log under `_scratch/setup.log` (when `_scratch/` exists; if not yet, a temp file under `$TMPDIR`) — this only matters in Phase 2 onward; Phase 1 errors die in stdout/stderr and exit.

### Privacy / Egress Notes

- Detection makes zero network calls. The `bcftools view -h` invocation is local-only. Verified by `test_invP001_setup_makes_zero_outbound_calls` in this phase.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` | CREATE | Package marker; re-exports |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_types.py` | CREATE | `SetupPlan`, `Volume`, `NebulaDeliverable` dataclasses |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/detect.py` | CREATE | Volume detection + Nebula validation + same-disk check |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/dryrun.py` | CREATE | Plan → preview rendering |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | MODIFY | Add `setup` subcommand routing |
| `bin/genomeclaw-prep` | MODIFY | Route `setup` into the toolkit container |
| `packages/toolkit/tests/integration/test_setup_dryrun.py` | CREATE | End-to-end dry-run integration tests |
| `packages/toolkit/tests/unit/test_setup_detect.py` | CREATE | Unit tests for detection helpers |
| `packages/toolkit/tests/integration/conftest.py` | MODIFY | Two-disk and same-disk loop-mount fixtures |
| `docs/reference/user-stories.md` | MODIFY | Story 1 Step 0 rewritten |
| `README.md` | MODIFY | Storage planning section drafted |

---

## Verification

```bash
# Run this phase's tests
cd packages/toolkit
uv run pytest tests/integration/test_setup_dryrun.py tests/unit/test_setup_detect.py -v

# Run all tests (regression check)
uv run pytest

# Type check
uv run mypy src/

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# CLI smoke (host-side; no destructive ops)
bin/genomeclaw-prep setup --help
# Expected: usage block listing flags
```

For the integration test fixture (loop-mounted images), no separate command is needed — pytest invokes it via the fixture.

---

## Completion Criteria

- [ ] All listed test cases pass (RED → GREEN → REFACTOR cycle visible in commits)
- [ ] Static checks pass (`mypy` + `ruff`)
- [ ] `INV-D001` test (`test_invD001_dryrun_does_not_mutate_source_or_target`) passes
- [ ] `INV-P001` test (`test_invP001_setup_makes_zero_outbound_calls`) passes
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures or repo
- [ ] `genomeclaw-prep setup` renders a complete dry-run preview against a synthetic two-disk fixture
- [ ] `genomeclaw-prep setup` rejects same-disk source-and-target with a specific, fixable error message
- [ ] `user-stories.md` Story 1 Step 0 reads cleanly without referencing the old four-`mkdir` flow (final wording confirmed in Phase 6)
- [ ] `work-notes.md` updated with RED output, decisions, and final state
- [ ] Phase status updated in `development-plan.md`

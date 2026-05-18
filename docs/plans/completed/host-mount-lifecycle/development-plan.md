# Host Mount Lifecycle — Development Plan

**Status**: ✅ **Complete 2026-05-14**
**Created**: 2026-05-14
**Completed**: 2026-05-14
**Branch**: not cut
**Parent context**: pre-open-source UX polish. Filed after the 2026-05-14 incident where stale colima mount config (an unmounted Kingston drive entry from a prior `host setup`) blocked colima from booting, forcing manual editing of `~/.colima/_lima/colima/colima.yaml`. Same trap will hit every open-source user the first time they replace a drive.

## Outcome

All three slices shipped + a documentation polish pass:

| Surface | Change | Defends against |
|---------|--------|-----------------|
| `setup/_preconditions.py` (new) + `setup/run.py` | Fail-fast with platform-aware install hints if colima/docker/diskutil missing | New users skipping the prerequisite install step |
| `_yaml_writer.remove_colima_mount` (new) + `eject.py` | `host eject <drive>` removes the drive's colima.yaml mount entry with backup | The Kingston-class colima boot failure |
| `doctor.py::_collect_stale_colima_mounts` (new) | `host doctor` flags stale mounts with concrete fix hints | The same boot failure, but caught proactively before next colima start |
| [`README.md`](../../../../README.md) | Added prerequisites + documented eject's new behavior + doctor's stale-mount check | First-time user onboarding |
| `host eject` / `host doctor` docstrings | Reflect new behavior in `--help` output | Day-to-day reference |

24 new tests (10 unit + 14 integration). Full host suite **491 passed / 72 needs_bio skipped** at close. Ruff + format clean.

---

## Summary

Three focused slices that close the gap between today's "you need to understand colima internals" onboarding and a "clone + one command" experience that survives drive plug/unplug/replace cycles. None of these reimplement the smart-setup flow that already lands the colima mount on first run — they extend the **lifecycle**: pre-flight checks before setup, cleanup on eject, observability via doctor.

## Critical Invariants to Respect

- **`INV-D001`** Raw genomic files source-of-truth — unchanged. None of these slices touch data paths; only colima config.
- **`INV-D004`** Destructive Operations require confirmation — extends. Slice 2 (eject removes colima mount) is a config write that takes effect after a `colima restart`. Eject already requires confirmation; the new mount-removal step inherits the same confirmation gate.
- **`INV-R001`** Rebuildability — extends. Slice 2 records the colima.yaml edit in eject's audit log; slice 3's doctor output records the inspected mount state.

## Proposed New Invariants

None. The work strengthens existing UX-resilience patterns rather than proposing new contracts.

## Current State Analysis

Already shipped by the [cram-scratch-strategy plan](../../completed/cram-scratch-strategy/):

- `host setup` detects an external drive, partitions/formats if needed, creates the canonical layout, **and injects the colima mount** via [`_yaml_writer.write_colima_yaml`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/_yaml_writer.py) (idempotent text edit that preserves user's other mounts + comments).
- `_reconfigure_colima.py` handles the "drift recovery" case (post-`colima delete && colima start` resets).
- `host eject` exists with `INV-D004` confirmation gate.
- `host doctor` exists as a read-only diagnostic.

Gaps that motivate this plan:

1. **`host setup` assumes colima + docker are installed.** A new user cloning the repo and running setup gets a deep traceback if colima isn't on PATH. Wrong layer for a useful error.
2. **`host eject` does not remove the colima mount entry.** When a user retires a drive, the stale mount entry stays in colima.yaml. The next `colima start` (or VM restart) hits the same Kingston-class `mkdir … permission denied` failure that just bit the project owner on 2026-05-14.
3. **`host doctor` does not check colima mount health.** A stale mount entry is invisible until you try to start colima and see a cryptic mkdir failure. Doctor should surface this proactively.

## Solution Design

Three small slices, in order. Each closes one gap, can be reviewed independently, ships its own tests.

### Slice 1 — Audit pre-check for required host tooling

Extend `host setup`'s audit step so it errors loudly with a fixable message when colima or docker isn't on PATH. Platform-aware: macOS users see `brew install colima docker`; Linux users see `apt install docker.io` (and an "n/a on Linux" note for colima).

The audit module already has the shape for this — it just doesn't currently check for these binaries.

### Slice 2 — Eject removes the colima mount entry

When `host eject <drive>` runs, after the existing layout-eject + ejection-confirmation:

1. Read `~/.colima/default/colima.yaml`.
2. Remove the `mounts:` entry whose `location` matches `/Volumes/<drive>`.
3. Write atomically with backup.
4. Prompt: "Restart colima now so the change takes effect? [Y/n]".
5. If yes, `colima_stop && colima_start`.
6. Record the edit in the eject audit log.

If colima isn't running, we still rewrite the config — the next `colima start` will pick it up.

The `_yaml_writer` module already does idempotent additive edits; the inverse (idempotent removal) is the same shape with a different filter.

### Slice 3 — Doctor checks for stale mount entries

Extend `host doctor` to inspect colima's mount config:

1. Read `~/.colima/default/colima.yaml`'s `mounts:` block.
2. For each `location:` entry under `/Volumes/`, check whether the path exists on the host.
3. For any missing one: emit a warning row "stale mount — drive `<name>` is configured for colima but not currently plugged in. Either plug it in or run `bin/genomeclaw host eject <drive>` to remove the entry."
4. Exit non-zero only if a critical issue is found; otherwise stay informational.

Pure inspection — no writes, no restarts.

## Phase Overview

| Phase | Description | Est. work |
|-------|-------------|-----------|
| Slice 1 | Audit pre-check for colima + docker availability | ~1–1.5h |
| Slice 2 | Eject removes the colima mount entry + restart prompt | ~2–3h |
| Slice 3 | Doctor reports stale colima mount entries | ~1–1.5h |

Total: ~5–7 hours active.

## Testing Strategy

Cross-cutting:

- **Unit**: each slice's pure-Python helper (binary detection, YAML mount-entry removal, mount-staleness check) gets host-runnable unit coverage.
- **Integration**: each slice's CLI surface gets a `test_cli_host_*.py` test using `invoke_cli` from conftest. These are host-runnable too — they don't need bcftools or colima itself, just the toolkit's Python entry points + a tmp_path-based colima.yaml fixture.

Per-slice TDD shape:

- Slice 1: monkeypatch `shutil.which` to simulate "colima missing" / "docker missing" / "both present"; assert audit's error envelope matches expected.
- Slice 2: stage a fake colima.yaml under tmp_path; invoke the YAML helper directly with `--remove <drive>`; assert the entry is gone and other entries + comments are preserved. CLI test: `invoke_cli(["host", "eject", ...])` with monkey-patched `colima_stop` / `colima_start`.
- Slice 3: stage a fake colima.yaml with both present and missing drive paths; assert doctor lists the missing one with the expected "plug in or eject" message.

## Documentation Updates

- README's "First-time setup" gets the three-command flow: `brew install colima docker` → `git clone …` → `bin/genomeclaw host setup`.
- `host eject --help` gains a line about the colima mount cleanup behavior.
- `host doctor --help` gains a line about the stale-mount check.

## Progress Tracking

| Slice | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Slice 1 | ✅ Complete | 2026-05-14 | 2026-05-14 | New `setup/_preconditions.py` (`check_required_tools` + `format_precondition_error` + `raise_if_missing`). Platform-aware: macOS checks colima+docker+diskutil with brew hints; Linux checks docker with apt hints. Wired into `setup/run.py:run_smart()` entry path so missing tools fail fast with a one-line fix. 10 unit tests. |
| Slice 2 | ✅ Complete | 2026-05-14 | 2026-05-14 | New `_yaml_writer.remove_colima_mount()` — inverse of `write_colima_yaml`; idempotent; trailing-slash insensitive; preserves other mounts + top-level keys; writes backup. Wired into `eject.py` with a new `colima_config_path` injection parameter for testability. Defaults to `~/.colima/default/colima.yaml`. 6 unit tests + 3 integration tests. Closes the 2026-05-14 Kingston-class boot-failure trap. |
| Slice 3 | ✅ Complete | 2026-05-14 | 2026-05-14 | New `doctor._collect_stale_colima_mounts()` — surfaces every colima mount entry whose location is missing from the host. Each entry carries an actionable `fix` string (plug-in or `host eject`). Stale mounts don't fail doctor's exit code (warning-level, not error-level). 5 integration tests. |

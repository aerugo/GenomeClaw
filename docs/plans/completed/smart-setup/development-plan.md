# Smart setup — development plan

**Status**: Active — single phase, est. 1.5–2 hours active implementation
**Spec**: [spec.md](spec.md)
**Started**: 2026-05-11
**Targets**: MVP Phase 4C (resumes W4 after this plan ships)

---

## Critical invariants to respect

- **`INV-D001`** Raw Genomic Files Are Source-of-Truth Artifacts — state inspection is read-only; the "Nebula missing" recovery action copies *into* `raw/` only, with the existing per-file SHA256 verification contract. Non-destructive actions never touch `raw/`.
- **`INV-D003`** Heavy Scratch Is Separated From Authoritative Outputs — the "Layout missing" action's `mkdir -p` recreates `_scratch/` as a sibling of `derived/` (the canonical layout), preserving the separation. The "Colima drifted" action's rewritten `mounts:` block keeps the four-mount discipline intact (separate entries per canonical subdir).
- **`INV-R001`** Rebuildability — every dispatched action appends a structured event to `_scratch/setup.log`. The dispatcher is a pure function of `SystemState` so the inspect → dispatch → execute chain is reproducible.

The set of invariants applicable here is unchanged from the cram-scratch-strategy plan that originally shipped `setup`. This plan refactors how setup decides what to do, not what `setup` is allowed to do.

## Proposed new invariants

None.

## Current state analysis

### What `setup` does today (post-cram-scratch-strategy)

`prep/setup/run.py:run_interactive(execute_destructive=True)` is the CLI entry point. It:

1. Prompts for Nebula deliverable path + target volume name.
2. Runs the 5-gate validation (volume detect / Nebula validate / same-disk safeguard / firmware safety / computed-need pre-flight).
3. Renders the dry-run preview.
4. Asks for typed confirmation (`WIPE /Volumes/<name>`).
5. Invokes `execute.py:execute(...)` which runs the 9-step destructive sequence.

The architecture assumes a single use case: "first-time onboarding of a fresh drive." There is no logic for detecting "the drive is already set up and you just need to fix colima."

### Code structure (relevant modules)

- `prep/setup/run.py` — CLI orchestration + interactive prompts.
- `prep/setup/detect.py` — `diskutil list` parsing; volume-shape detection.
- `prep/setup/dryrun.py` — renders the preview text.
- `prep/setup/execute.py` — the 9-step destructive runner.
- `prep/setup/platform.py` — `Platform` protocol + `MacOSPlatform` impl backed by `diskutil` / `colima` / `docker` shellouts.
- `prep/setup/_types.py` — `SetupPlan`, `NebulaDeliverable`, etc. dataclasses.
- `prep/setup/_yaml_writer.py` — colima.yaml round-tripper (preserves comments + non-mount entries).
- `prep/setup/known_bad_firmware.toml` — firmware-safety known-bad list.

### What's missing

- No way to read current system state (partition exists? layout intact? colima.yaml canonical? colima running?).
- No dispatch logic mapping state → action.
- No action handlers other than the full destructive flow.
- No "Already configured, exiting" report path.

## Solution design

### State inspection module — `prep/setup/inspect.py` (NEW)

Pure function: `inspect_system(*, platform: Platform, canonical_partition: str = "Genome_Work") -> SystemState`.

`SystemState` is a frozen dataclass:

```python
@dataclass(frozen=True)
class SystemState:
    partition_present: bool
    partition_format: str | None      # "apfs" / "exfat" / "ntfs" / None
    partition_mountpoint: Path | None # e.g. Path("/Volumes/Genome_Work")
    layout_present: bool              # all four subdirs exist
    layout_missing_subdirs: tuple[str, ...]   # ("raw", "scratch") etc.
    nebula_present: bool              # raw/<*>/ has ≥1 file
    nebula_sample_id: str | None      # discovered from raw/
    colima_yaml_canonical: bool       # mounts include partition_mountpoint + memory ≥ 4 GB
    colima_yaml_drift: tuple[str, ...]  # ("mounts_missing_genome_work", "memory_too_low")
    colima_running: bool
```

Side effects: read-only. Subprocess captures via the injected `Platform`.

### Dispatcher — `prep/setup/dispatch.py` (NEW)

Pure function: `decide_action(state: SystemState) -> tuple[SetupAction, str]`. Returns the chosen action + a human-readable rationale.

```python
class SetupAction(StrEnum):
    FULL_DESTRUCTIVE = "full_destructive"
    RECONFIGURE_COLIMA = "reconfigure_colima"
    START_COLIMA = "start_colima"
    RECREATE_LAYOUT = "recreate_layout"
    RESTAGE_NEBULA = "restage_nebula"
    NO_OP = "no_op"
```

Decision tree (in order):

1. `not state.partition_present` → `FULL_DESTRUCTIVE` ("no `Genome_Work` partition detected; first-time onboarding required").
2. `state.partition_format != "apfs"` → `FULL_DESTRUCTIVE` ("partition is `{format}`, not APFS; reformat required").
3. `not state.layout_present` → `RECREATE_LAYOUT` ("partition exists, but {missing_subdirs} are absent; will mkdir").
4. `not state.nebula_present` → `RESTAGE_NEBULA` ("layout exists but `raw/` is empty; re-stage Nebula deliverable via `--source`").
5. `not state.colima_yaml_canonical` → `RECONFIGURE_COLIMA` ("colima.yaml drifted: {drift_details}; will rewrite + restart").
6. `not state.colima_running` → `START_COLIMA` ("colima is stopped; will start").
7. Otherwise → `NO_OP` ("already configured; nothing to do").

### Action handlers

Three new (others already exist as parts of `execute.py`):

- **`prep/setup/_reconfigure_colima.py`** (NEW): reads current colima.yaml; ensures `mounts:` includes the canonical four bind-mounts for the detected partition; ensures `memory: ≥ 4` (default 8 if currently lower); writes the file via `_yaml_writer.py` (preserves comments + user-added entries); calls `platform.colima_stop()` + `colima_start()`. Records a `reconfigure_colima` event to `_scratch/setup.log` (`{step, detected_state, mounts_added, memory_before, memory_after}`).
- **`prep/setup/_recreate_layout.py`** (NEW): `mkdir -p` for each missing subdir under the existing partition mountpoint. Records a `recreate_layout` event.
- **`prep/setup/_start_colima.py`** (NEW): single `platform.colima_start()` call. Records a `start_colima` event.
- `prep/setup/_restage_nebula.py` (NEW, only-if-source-provided): re-runs the per-file SHA256-verified copy from a user-provided source into `raw/<sample-id>/`.
- The existing `execute.py:execute(...)` is the `FULL_DESTRUCTIVE` action; no changes to it.

### Updated orchestrator — `prep/setup/run.py` (REWRITE)

```python
def run_interactive(execute_destructive: bool = True) -> int:
    platform = MacOSPlatform()
    state = inspect_system(platform=platform)
    action, rationale = decide_action(state)

    print(f"Detected state: {_summarize_state(state)}")
    print(f"Chosen action: {action.value} — {rationale}")

    if action == SetupAction.NO_OP:
        return 0

    if action == SetupAction.RESTAGE_NEBULA:
        # Need --source; if not provided, fail-fast with clear pointer.
        ...

    if action == SetupAction.FULL_DESTRUCTIVE:
        return _run_full_destructive(state, execute_destructive=execute_destructive)

    # Non-destructive actions: no typed-confirmation prompt.
    if action == SetupAction.RECONFIGURE_COLIMA:
        return reconfigure_colima(state, platform=platform)
    if action == SetupAction.RECREATE_LAYOUT:
        return recreate_layout(state, platform=platform)
    if action == SetupAction.START_COLIMA:
        return start_colima(state, platform=platform)

    raise AssertionError(f"unhandled action: {action}")
```

### CLI surface — `cli.py`

No changes. The `--dry-run` flag still works (the dispatcher runs; the chosen non-destructive action's "would write…" preview prints; the destructive action skips the actual write). `bin/genomeclaw-prep setup` is the same entry point.

### Schema / provenance impact

The `_scratch/setup.log` audit log gains new event types (`reconfigure_colima`, `recreate_layout`, `start_colima`, `no_op`). The schema is `{ts: str, step: str, phase: str, payload: dict}` — additive non-breaking. The downstream `doctor` orchestrator that reads the log already handles unknown `step` values gracefully.

### Privacy & egress impact

None. State inspection is local-only. The existing destructive path's privacy contract carries forward unchanged.

## Phase overview

| Phase | Description | TDD focus | Est. tests |
|-------|-------------|-----------|------------|
| 1 | State inspection + dispatcher + 4 new action handlers + run.py orchestrator + tests | unit (inspect, dispatch), integration (end-to-end per state) | ~18 |

Single phase. Total estimated implementation: ~1.5–2 hours active.

## Testing strategy

### Unit tests (host venv)

- `tests/integration/test_setup_inspect.py` (~6 cases): each `SystemState` field returns the right value given a synthetic on-disk + Platform-stub combination.
- `tests/integration/test_setup_dispatch.py` (~7 cases): one per state→action mapping; assert the action + rationale string contains the expected substring.

### Integration tests (host venv with FakePlatform; or in-image needs_bio for real-disk paths)

- `tests/integration/test_setup_smart.py` (~5 cases):
  - End-to-end NO_OP path (fully-configured fixture → reports green, no side effects).
  - End-to-end RECONFIGURE_COLIMA path (drifted-colima.yaml fixture → rewritten yaml + colima-stop+start sequence on FakePlatform).
  - End-to-end RECREATE_LAYOUT path (missing-subdirs fixture → mkdir + audit-log event).
  - End-to-end START_COLIMA path.
  - End-to-end FULL_DESTRUCTIVE dispatch (no-partition fixture → falls through to existing destructive runner; existing tests cover the destructive runner itself).

### Invariant tests

The existing invariant suite covers `INV-D001` + `INV-D003` + `INV-R001` for the destructive path. The smart-dispatch refactor inherits coverage via the FakePlatform integration tests above; no new invariant tests needed.

### Determinism tests

Inspect + dispatch are pure functions. A property-style test: same `SystemState` always yields the same `SetupAction`. Belongs in the unit-test file above.

## Documentation updates

- [README.md](../../../README.md) Storage planning section — add a one-paragraph note that `setup` is now idempotent + auto-heals colima drift; mention that the user can re-run `setup` whenever something feels off.
- [user-stories.md](../../reference/user-stories.md) Story 1 Step 0 — mention the auto-heal behavior in the diagnostics paragraph.
- [docs/plans/completed/cram-scratch-strategy/work-notes.md](../../completed/cram-scratch-strategy/work-notes.md) "Post-close: colima recovery recipe" section — add a note that the manual bootstrap pattern is no longer needed after smart-setup ships; `bin/genomeclaw-prep setup` handles it.

No `docs/reference/INVARIANTS.md` changes — no new invariants.

## Documentation updates required

- [ ] [README.md](../../../README.md) Storage planning section
- [ ] [docs/reference/user-stories.md](../../../reference/user-stories.md) Story 1 Step 0 (diagnostics paragraph)
- [ ] [docs/plans/completed/cram-scratch-strategy/work-notes.md](../../completed/cram-scratch-strategy/work-notes.md) recovery-recipe section

## Progress tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Pending | 2026-05-11 | | Single-phase plan; ~18 tests; ~1.5–2 hours active |

## Open risks & follow-ups

- **Colima version skew**: `colima.yaml`'s exact schema can shift between colima versions. The `_yaml_writer.py` helper already exists for the destructive path; reusing it inherits whatever robustness was built there. If a future colima release breaks the round-trip, surfaces during the in-image gate.
- **Companion doctor extension** (out of scope; filed as follow-up): doctor could read colima.yaml and report drift before the user tries to run a pipeline. Smart-setup auto-heals at the setup entry point; doctor would provide the proactive heads-up. ~30 min if/when added.
- **Linux host support** (out of scope; defer to a future plan). Setup is macOS-only by design; smart-setup inherits the limitation.

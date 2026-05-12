# Phase 1: Smart-setup state dispatcher + action handlers

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD or blank>
**Parent plan**: [development-plan.md](../development-plan.md)

---

## Objective

Ship the entire smart-setup feature in one reviewable slice:

1. **State inspection** — pure function `inspect_system(*, platform: Platform) -> SystemState` reads partition + layout + Nebula + colima.yaml + colima status. Read-only side effects only.
2. **Dispatcher** — pure function `decide_action(state: SystemState) -> tuple[SetupAction, str]` maps state to one of seven actions + a human-readable rationale.
3. **Three new action handlers**: `reconfigure_colima`, `recreate_layout`, `start_colima`. (The destructive action delegates to the existing `execute.py`; the `restage_nebula` handler is a thin re-use of the existing copy-with-SHA256 loop; `no_op` is a one-line report.)
4. **Updated `run.py`** orchestrator that wires inspect → dispatch → execute the chosen action, with the typed-confirmation guard fired only for `FULL_DESTRUCTIVE`.
5. **18 new tests** covering: 6 inspect-state, 7 dispatch-decisions, 5 end-to-end smart-setup paths (NO_OP, RECONFIGURE_COLIMA, RECREATE_LAYOUT, START_COLIMA, FULL_DESTRUCTIVE-dispatch).

After Phase 1: `bin/genomeclaw-prep setup` is idempotent + state-driven. Running it on a system that just had `colima delete` works without manual bootstrapping.

## Scope boundaries

- **In scope**:
  - `prep/setup/inspect.py` (new) + 6 unit tests.
  - `prep/setup/dispatch.py` (new) + 7 unit tests.
  - `prep/setup/_reconfigure_colima.py` + `_recreate_layout.py` + `_start_colima.py` (new action handlers).
  - `prep/setup/_restage_nebula.py` (re-use of existing Nebula copy loop; thin wrapper).
  - `prep/setup/run.py` (rewrite the entry point to dispatch).
  - 5 end-to-end integration tests (`test_setup_smart.py`).
  - Audit-log event-type additions (`reconfigure_colima`, `recreate_layout`, `start_colima`, `no_op`).

- **Out of scope**:
  - Doctor extension to surface colima drift (companion follow-up, ~30 min when filed).
  - Linux platform support — setup remains macOS-only.
  - Concurrent setup invocations.
  - Cross-drive migration tooling.

## Invariants enforced in this phase

- **`INV-D001`** — state inspection never mutates `raw/` or any source file; the integration test for the NO_OP path asserts no filesystem mutations occur. The `restage_nebula` action reuses the existing per-file SHA256-verified copy contract from `execute.py`.
- **`INV-D003`** — the `recreate_layout` action recreates `_scratch/` as a sibling of `derived/` (not nested); test gates this structural rule. The `reconfigure_colima` action's rewritten `mounts:` block keeps the four canonical paths as separate entries (preserves bind-mount discipline).
- **`INV-R001`** — every dispatched action appends a structured event to `_scratch/setup.log` with timestamp + chosen action + detected-state snapshot. Tests verify the log entries match the documented schema (`{ts, step, phase, payload}`).

---

## TDD steps

### Step 1.1 — RED: write failing tests

Test cases by file. INV-IDs in the test name where applicable.

#### State inspection (`tests/integration/test_setup_inspect.py`, 6 cases)

1. `test_inspect_returns_fresh_state_when_no_partition` — Platform stub returns no `Genome_Work` volume; `SystemState.partition_present == False`, all other fields default.
2. `test_inspect_detects_wrong_format` — Platform stub returns `Genome_Work` as exFAT; `partition_format == "exfat"`, `partition_present == True`.
3. `test_inspect_detects_layout_missing` — partition is APFS but `raw/` doesn't exist; `layout_present == False`, `layout_missing_subdirs == ("raw",)`.
4. `test_inspect_detects_nebula_missing` — layout present but `raw/` is empty; `nebula_present == False`.
5. `test_inspect_parses_colima_yaml_drift` — given a colima.yaml with `mounts: []`, `colima_yaml_canonical == False`, `colima_yaml_drift` contains `"mounts_missing_genome_work"`. Given memory: 2, drift contains `"memory_too_low"`.
6. `test_inspect_fully_configured_system` — every condition green; all `*_present` are True; `colima_yaml_canonical == True`; `colima_running == True`.

#### Dispatcher (`tests/integration/test_setup_dispatch.py`, 7 cases — one per state)

7. `test_decide_no_partition_dispatches_full_destructive` — `SystemState(partition_present=False, ...)` → `SetupAction.FULL_DESTRUCTIVE`. Rationale contains `"first-time onboarding"`.
8. `test_decide_wrong_format_dispatches_full_destructive` — partition exists but is exFAT → `FULL_DESTRUCTIVE`. Rationale contains `"not APFS"`.
9. `test_decide_layout_missing_dispatches_recreate_layout` — `RECREATE_LAYOUT`. Rationale lists missing subdirs.
10. `test_decide_nebula_missing_dispatches_restage_nebula` — `RESTAGE_NEBULA`. Rationale points the user at `--source`.
11. `test_decide_colima_drifted_dispatches_reconfigure_colima` — `RECONFIGURE_COLIMA`. Rationale lists drift details.
12. `test_decide_colima_stopped_dispatches_start_colima` — `START_COLIMA`.
13. `test_decide_everything_green_dispatches_no_op` — `NO_OP`. Rationale: `"already configured"`.

#### End-to-end smart-setup integration (`tests/integration/test_setup_smart.py`, 5 cases)

14. `test_setup_no_op_on_fully_configured_system` — fully-configured FakePlatform + on-disk fixture; `run_interactive(execute_destructive=True)` exits 0; **no filesystem mutations** (asserted via mtime snapshots); audit log has zero new entries.
15. `test_setup_reconfigure_colima_when_drifted` — drifted-colima.yaml fixture; `run_interactive` rewrites colima.yaml (mounts + memory canonical); FakePlatform records `colima_stop` then `colima_start`; audit log has a `reconfigure_colima` event with `{mounts_added, memory_before, memory_after}`.
16. `test_setup_recreate_layout_when_missing` — partition exists but `_scratch/` is absent; `run_interactive` creates it via `mkdir`; **does not touch `raw/`** (mtime preserved — `INV-D001`); audit log has `recreate_layout` event with `{missing_subdirs_recreated}`.
17. `test_setup_start_colima_when_stopped` — FakePlatform: `colima_status` returns "stopped"; `run_interactive` calls `colima_start`; audit log has `start_colima` event.
18. `test_setup_full_destructive_when_no_partition` — empty FakePlatform (no Genome_Work); `run_interactive(execute_destructive=False)` (dry-run) prints the full-destructive preview + the typed-confirmation phrase. Real destructive flow is covered by existing `test_setup_execute.py`.

After writing all 18 tests, **run them and confirm they fail for the intended reasons** (e.g., `ImportError: cannot import name 'inspect_system'`, `AttributeError: no attribute 'SetupAction'`). Paste the failing output into [work-notes.md](../work-notes.md).

### Step 1.2 — GREEN: minimal implementation

Land the smallest set of code that turns the tests green.

**New modules under `packages/toolkit/src/genomeclaw_toolkit/prep/setup/`:**

- `inspect.py`:
  ```python
  @dataclass(frozen=True)
  class SystemState:
      partition_present: bool
      partition_format: str | None
      partition_mountpoint: Path | None
      layout_present: bool
      layout_missing_subdirs: tuple[str, ...]
      nebula_present: bool
      nebula_sample_id: str | None
      colima_yaml_canonical: bool
      colima_yaml_drift: tuple[str, ...]
      colima_running: bool

  def inspect_system(*, platform: Platform, canonical_partition: str = "Genome_Work") -> SystemState:
      # 1. Platform.list_volumes() → find Genome_Work
      # 2. If present: stat the four canonical subdirs
      # 3. If layout present: glob raw/<*>/ for files → nebula_sample_id
      # 4. Read ~/.colima/default/colima.yaml → check mounts + memory
      # 5. platform.colima_status() → colima_running
      ...
  ```

- `dispatch.py`:
  ```python
  class SetupAction(StrEnum):
      FULL_DESTRUCTIVE = "full_destructive"
      RECONFIGURE_COLIMA = "reconfigure_colima"
      START_COLIMA = "start_colima"
      RECREATE_LAYOUT = "recreate_layout"
      RESTAGE_NEBULA = "restage_nebula"
      NO_OP = "no_op"

  def decide_action(state: SystemState) -> tuple[SetupAction, str]:
      # Decision tree per spec.md § Seven defined states
      ...
  ```

- `_reconfigure_colima.py`:
  ```python
  def reconfigure_colima(state: SystemState, *, platform: Platform, audit_log_dir: Path) -> int:
      # 1. Read ~/.colima/default/colima.yaml via _yaml_writer.py
      # 2. Inject canonical mounts (idempotent — keep user's other mounts)
      # 3. Set memory: max(8, current)
      # 4. Write file
      # 5. platform.colima_stop() + colima_start()
      # 6. Append audit-log event
      ...
  ```

- `_recreate_layout.py`:
  ```python
  def recreate_layout(state: SystemState, *, audit_log_dir: Path) -> int:
      # mkdir -p each missing subdir under state.partition_mountpoint
      # Append audit-log event
      ...
  ```

- `_start_colima.py`:
  ```python
  def start_colima(*, platform: Platform, audit_log_dir: Path) -> int:
      # platform.colima_start()
      # Append audit-log event
      ...
  ```

- `_restage_nebula.py` (thin re-use):
  ```python
  def restage_nebula(state: SystemState, source: Path, *, platform: Platform, audit_log_dir: Path) -> int:
      # Re-use the per-file SHA256-verified copy loop from execute.py § 5
      # Append audit-log event
      ...
  ```

**Updated module:**

- `run.py` — replace the body of `run_interactive(execute_destructive=True)` with:
  ```python
  state = inspect_system(platform=platform)
  action, rationale = decide_action(state)
  _print_state_summary(state, action, rationale)

  if action == SetupAction.NO_OP:
      return 0
  if action == SetupAction.FULL_DESTRUCTIVE:
      return _run_full_destructive_with_confirmation(...)  # existing flow
  # Non-destructive dispatch:
  return _run_action(action, state, platform=platform)
  ```

After each test transitions to GREEN, commit. The RED → GREEN → REFACTOR cadence should be visible in `git log` — one commit per test group (inspect, dispatch, integration).

### Step 1.3 — REFACTOR

- Extract `_print_state_summary(state, action, rationale)` into a single helper if it gets duplicated.
- The four action handlers all share a "open audit log → append event → close" pattern. If duplication shows up, extract `_audit.append_event(audit_log_dir, step, payload)` helper (the existing `execute.py` may already have this — re-use rather than duplicate).
- Run `ruff check` + `ruff format --check`. Re-run full suite. Confirm test count: 158 → 176 host (~+18), 218 → ~218 in-image (most new tests run on host venv via FakePlatform).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/inspect.py` | CREATE | `SystemState` dataclass + `inspect_system(...)` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/dispatch.py` | CREATE | `SetupAction` enum + `decide_action(...)` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_reconfigure_colima.py` | CREATE | Non-destructive colima.yaml rewrite + restart |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_recreate_layout.py` | CREATE | `mkdir -p` missing canonical subdirs |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_start_colima.py` | CREATE | Single `colima start` invocation |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/_restage_nebula.py` | CREATE | Per-file SHA256-verified copy (re-use existing helpers) |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/run.py` | REWRITE | Dispatch-driven entry point |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` | MODIFY | Export `inspect_system`, `decide_action`, `SetupAction`, `SystemState` |
| `packages/toolkit/tests/integration/test_setup_inspect.py` | CREATE | 6 unit cases for `inspect_system` |
| `packages/toolkit/tests/integration/test_setup_dispatch.py` | CREATE | 7 unit cases for `decide_action` |
| `packages/toolkit/tests/integration/test_setup_smart.py` | CREATE | 5 end-to-end integration cases |

---

## Verification

```bash
cd packages/toolkit

# Host-venv unit + integration tests. Most smart-setup tests run on host
# venv (FakePlatform; no docker needed).
uv run pytest tests/integration/test_setup_inspect.py \
              tests/integration/test_setup_dispatch.py \
              tests/integration/test_setup_smart.py -v
# Expected: 18 passed.

# Full host suite (confirms no regressions to existing setup_execute tests).
uv run pytest -q
# Expected: ~176 passed (was 157 at start of session 3; +~18 new).

# Static checks.
uv run ruff check .
uv run ruff format --check .

# In-image suite (the existing setup_execute + new smart-setup tests).
docker run --rm --user $(id -u):$(id -g) --env GENOMECLAW_HAS_BIO=1 \
  --env PYTHONPATH=/work/src \
  --mount type=bind,source=$(pwd),target=/work --workdir /work \
  --entrypoint pytest genomeclaw/toolkit:dev -q
# Expected: ~218 passed (smart-setup tests are host-runnable via FakePlatform;
# no new in-image cases).
```

### Real-data smoke

Per the planning protocol's scale-sensitive-phase rule, this phase is **not** scale-sensitive (no genome data flows through the dispatcher). The unit + integration tests are sufficient. The first real exercise will be next session's W4 (resume MVP Phase 4C): running `bin/genomeclaw-prep setup` against the project owner's actual T7 Shield + Kingston environment — the smart-dispatcher should pick `FULL_DESTRUCTIVE` against the fresh T7 (or `RECONFIGURE_COLIMA` against the bootstrapped-but-drifted Kingston) without manual intervention.

---

## Completion criteria

- [ ] All 18 test cases pass on host venv (6 inspect + 7 dispatch + 5 integration).
- [ ] Full host suite green (~176 passed, 0 failed).
- [ ] Full in-image suite green (no regressions to existing setup_execute tests).
- [ ] `ruff check` + `ruff format --check` clean.
- [ ] `bin/genomeclaw-prep setup --dry-run` on the project owner's current dual-drive state (Kingston bootstrapped + T7 factory-clean) correctly identifies and prints the dispatch decision (without executing).
- [ ] Audit-log events for `reconfigure_colima`, `recreate_layout`, `start_colima`, `no_op` documented in the schema-comment in `_audit.py` (or wherever the event schema lives).
- [ ] [work-notes.md](../work-notes.md) updated with: RED failing output, GREEN diff summary, REFACTOR notes, final test counts.
- [ ] Phase 1 status set to **Complete** in [development-plan.md](../development-plan.md) progress table.
- [ ] Documentation updates:
  - [ ] [README.md](../../../../README.md) Storage planning section — one paragraph on `setup`'s idempotent + auto-heal behavior.
  - [ ] [user-stories.md](../../../reference/user-stories.md) Story 1 Step 0 diagnostics paragraph.
  - [ ] [docs/plans/completed/cram-scratch-strategy/work-notes.md](../../../completed/cram-scratch-strategy/work-notes.md) recovery-recipe section — note that the manual bootstrap pattern is superseded by smart-setup.

### Carry-overs to follow-ups

- **Doctor extension**: file a small (~30 min) plan to add a fifth doctor check that parses colima.yaml and warns on drift. Complementary to smart-setup's auto-heal at the setup entry point.
- **Linux host support** — out of scope; defer to a future plan.

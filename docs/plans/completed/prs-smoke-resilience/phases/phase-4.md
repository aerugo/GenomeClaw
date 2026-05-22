# Phase 4: Mid-run watchdog + Nextflow resume + Colima mount recovery

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Close mid-run L4 brittleness (v22g, v22j cases): external-drive bind-mount goes stale during pgsc_calc execution; today the whole DAG crashes + the smoke driver loses 25–90 min of completed pgsc_calc work. Phase 4 detects the disconnect in ≤60 seconds via a canary watchdog, refreshes the Colima mount, and re-invokes pgsc_calc with Nextflow's native `-resume` so the cached task outputs in `work_dir` get picked up. Recovery is bounded (`--max-recovery-attempts`, default 3) — past that, the smoke fails with a documented "drive too unstable" diagnostic.

## Scope Boundaries

- **In scope**:
  - `-resume` flag baked into `_build_pgsc_calc_argv`'s emitted argv.
  - Canary file staged at smoke start under `<raw_dir>/.canary`.
  - Background bash watchdog in `bin/genomeclaw-prs-smoke` that probes the canary every 60s.
  - Bounded recovery loop: detect → kill toolkit container → wait for stable drive reconnection → `colima stop && colima start --mount ...` → re-invoke pgsc_calc.
  - `host setup` writes the canonical Colima start args to `~/.config/genomeclaw/colima.json`; recovery loop reads from there.
  - `pgs_scores.params_json` gains `resume_count` (number of pgsc_calc invocations) + `recovery_attempts` (number of mount-recovery cycles).
- **Out of scope**:
  - Per-task retry inside Nextflow (Phase 3 territory; `errorStrategy = 'retry'` already lands there).
  - Recovery from Colima itself crashing (vs. a stale mount) — addressed implicitly by `colima start` doing a full bring-up, but debugging the underlying VZ.framework / virtiofs fault stays out.
  - Internal-SSD staging (originally F9; reality-checked as infeasible on 30 GB free SSD; deferred).
  - Singularity profile for pgsc_calc (F10; bigger architectural change).

## Invariants Enforced in This Phase

- **INV-D003** Heavy scratch separated — canary file lives at `<raw_dir>/.canary` (which is read-only host-side per shim INV-D001). For our purposes, the canary writes via the smoke driver staging step are an opt-in deviation: the smoke driver is a development tool that already writes to `_scratch/`; the canary is a 1-byte file with a deliberately-trivial content (timestamp).
- **INV-D005 / D006 / D007** — recovery loop refreshes the canonical bind-mount with the canonical paths via `colima start --mount /Volumes/Genome_Work:w`; same canonical seams.
- **INV-P001** Privacy default — watchdog reads ONE 1-byte canary file every 60s; no network egress; no external API.
- **INV-R001** Rebuildability — `pgs_scores.params_json` gains `resume_count` + `recovery_attempts` so the row's provenance reflects how many pgsc_calc invocations + mount recoveries were needed. Determinism note: `-resume` preserves task output determinism (Nextflow caches the work_dir's `.exitcode` + outputs; deterministic-input tasks produce identical outputs on re-run).
- **INV-C002** CLI Output Contract — `cli_envelope.json` gains `recovery_attempts` field additively (no schema bump).

---

## TDD Steps

### Step 4.1 — `-resume` flag in pgsc_calc argv

**RED**:

1. `test_pgsc_calc_argv_includes_resume_flag` (unit) — asserts `_build_pgsc_calc_argv(...)` returns argv containing `-resume`. RED with the current argv (no -resume).

**GREEN**:

```python
# pgs.py:_build_pgsc_calc_argv
argv += [
    conv.input_flag,
    ...
    "-resume",  # NEW
    conv.work_dir_flag,
    str(work_dir),
]
```

Safe to enable unconditionally: a fresh `work_dir` makes `-resume` a no-op.

**REFACTOR**: docstring update to reference the recovery contract.

### Step 4.2 — Canary + watchdog in smoke driver

**RED**:

1. `test_smoke_driver_stages_canary_file_at_start` (integration) — runs the smoke driver against a stub setup; asserts `<raw_dir>/.canary` exists with timestamp content. RED until driver adds the staging line.
2. `test_smoke_driver_watchdog_detects_unmounted_drive` (integration) — stubs the canary as unreadable (simulated unmount); asserts the watchdog touches `<smoke_dir>/.recovery_needed`. RED until the watchdog is wired.

**GREEN**:

- Smoke driver writes canary at start: `echo "$(date -u +%s)" > "${DRIVE}/genomeclaw/raw/.canary"`.
- Watchdog runs as a background subshell during `prs_compute_$PGS_ID`:
  ```bash
  watchdog() {
      local pgsc_pid=$1
      while kill -0 "$pgsc_pid" 2>/dev/null; do
          if ! timeout 10 docker run --rm -v "${DRIVE}":/probe alpine \
                test -r "/probe/genomeclaw/raw/.canary" >/dev/null 2>&1; then
              echo "WATCHDOG: bind-mount lost; signaling recovery" \
                  | tee -a "$SMOKE_DIR/recovery.log"
              touch "$SMOKE_DIR/.recovery_needed"
              docker stop "$TOOLKIT_CID" >/dev/null 2>&1 || true
              return
          fi
          sleep 60
      done
  }
  ```

**REFACTOR**: extract the watchdog and the canary-staging into `bin/genomeclaw-prs-smoke-helpers.sh` so the smoke driver's main flow stays readable.

### Step 4.3 — Recovery loop with bounded retries

**RED**:

1. `test_smoke_driver_recovery_loop_invokes_colima_restart` (integration) — stubs `.recovery_needed` to fire once; asserts the recovery loop shells out to `colima stop` + `colima start` with the persisted args. RED until the recovery loop exists.
2. `test_smoke_driver_recovery_waits_for_stable_reconnect` (integration) — stubs a "bouncing" drive (ls succeeds, then fails, then succeeds); asserts the loop waits until 30s of continuous success before restarting Colima. RED until the stability check exists.
3. `test_smoke_driver_bounds_recovery_to_max_attempts` (integration) — stubs `.recovery_needed` to fire on every iteration; asserts the loop exits with rc=87 after 3 attempts. RED until the bound exists.

**GREEN**:

```bash
run_pgsc_calc_with_recovery() {
    local max_attempts="${GENOMECLAW_MAX_RECOVERY_ATTEMPTS:-3}"
    local attempt=0
    while (( attempt < max_attempts )); do
        run_pgsc_calc_with_watchdog
        local rc=$?
        if (( rc == 0 )); then return 0; fi
        if [[ ! -f "$SMOKE_DIR/.recovery_needed" ]]; then
            return "$rc"  # real pgsc_calc failure
        fi
        attempt=$((attempt + 1))
        wait_for_stable_drive_reconnect 30
        restart_colima_with_persisted_args
        rm "$SMOKE_DIR/.recovery_needed"
    done
    return 87
}
```

**REFACTOR**: extract `wait_for_stable_drive_reconnect` + `restart_colima_with_persisted_args` into helper functions; document the rc=87 ("max recovery attempts hit") in the smoke driver's rc table.

### Step 4.4 — Colima config persistence via `host setup`

**RED**:

1. `test_host_setup_writes_colima_config_json` (unit) — runs `host setup`'s config-write step against a tmp HOME; asserts `~/.config/genomeclaw/colima.json` exists with `start_args` + `written_by` + `written_at` keys. RED until the writer is added.
2. `test_smoke_driver_recovery_fails_actionable_when_colima_config_missing` (integration) — stubs `~/.config/genomeclaw/colima.json` as absent; asserts the recovery loop exits with rc=2 and a printed hint ("Run: genomeclaw host setup to persist Colima config"). RED until the missing-config path is wired.

**GREEN**:

```python
# packages/toolkit/src/genomeclaw_toolkit/host/setup.py
def _persist_colima_config(drive_root: Path) -> None:
    config_dir = Path.home() / ".config" / "genomeclaw"
    config_dir.mkdir(parents=True, exist_ok=True)
    colima_config = config_dir / "colima.json"
    colima_config.write_text(
        json.dumps({
            "start_args": [
                "--cpu", "2",
                "--memory", "12",
                "--disk", "40",
                "--mount", f"{drive_root}:w",
            ],
            "written_by": "genomeclaw host setup",
            "written_at": datetime.now(UTC).isoformat(),
        }, indent=2)
    )
```

Smoke driver reads it:

```bash
colima_args=$(jq -r '.start_args | join(" ")' "$COLIMA_ARGS_FILE")
colima start $colima_args
```

**REFACTOR**: doc the config file shape in `docs/reference/host-setup.md` or inline in `host/setup.py`.

### Step 4.5 — `resume_count` + `recovery_attempts` provenance

**RED**:

1. `test_pgs_scores_params_json_carries_resume_count` (integration) — stubs a smoke run with 2 pgsc_calc invocations (1 recovery); asserts persisted `params_json` has `resume_count: 2` + `recovery_attempts: 1`. RED until the smoke driver writes the counters.

**GREEN**:

- Smoke driver passes recovery counters via env vars to the inner shim invocation: `--env GENOMECLAW_RESUME_COUNT=$attempt --env GENOMECLAW_RECOVERY_ATTEMPTS=$attempt`.
- `_stamp_pgs_row` in `pipeline.py` reads them and merges into `params_json`.

**REFACTOR**: extract counter reading into a small helper.

### Step 4.6 — Manual real-data verification smoke

**Test**: forced disconnect → recovery → resume → success.

1. Launch a smoke against `MPNRGLQ2K + PGS000018`.
2. Once pgsc_calc reaches FILTER_VARIANTS or later (~10 min in), force a virtiofs disconnect from the host: `sudo umount -f /Volumes/Genome_Work` (or eject + remount).
3. Watch `recovery.log`: WATCHDOG should fire within 60s; recovery loop should colima-stop, wait for stable drive, colima-start, re-invoke pgsc_calc.
4. Pgsc_calc re-invocation should pick up via `-resume` and run only the post-disconnect tasks.
5. Final state: `aggregated_scores.txt.gz` lands; `cli_envelope.json` has `recovery_attempts: 1`.

Document the manual verification result in [../work-notes.md](../work-notes.md).

---

## Implementation Details

### Edge Cases to Handle

- **Drive disconnects during recovery loop itself** (between `colima stop` and `colima start`): caught by the stable-reconnect check; loop waits for ≥30s of continuous host-side readability before proceeding.
- **Multiple consecutive disconnects in one smoke** (e.g., flaky cable): bounded by `--max-recovery-attempts` = 3. Past that, the smoke fails with rc=87 + a clean diagnostic; user investigates hardware.
- **Disconnect while toolkit container is shutting down**: cascade may take a few seconds; the recovery loop's first `colima stop` waits for Colima's own settle period before exiting.
- **`-resume` with a partially-corrupt work_dir** (e.g., a task was mid-write when the disconnect hit): Nextflow detects via the missing `.exitcode` file + reruns the task. Verified by the manual smoke (step 4.6).
- **Watchdog firing on a transient I/O glitch** (false positive): `timeout 10` on the `docker run` test gives 10 seconds for the I/O to recover. If it doesn't, we treat it as a real disconnect; if it WAS just a glitch, the recovery overhead (Colima restart) is ~30s — acceptable cost for the safety margin.

### Error Handling

- rc=87 (max recovery attempts) surfaces in `cli_envelope.json` as `error_type: "internal_error"` with message naming the count + hint to investigate hardware.
- Watchdog's docker probe failure is NOT a fatal smoke error by itself — only the recovery loop's rc=87 (after max retries) is.

### Privacy / Egress Notes

- Canary file content: timestamp (8 bytes) — no genomic data, no sample identifier.
- Watchdog probe runs Alpine Linux container: no network access; reads canary; that's it.
- `colima start` / `colima stop`: standard Colima invocations; no new external surfaces.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | MODIFY | `-resume` in `_build_pgsc_calc_argv` |
| `packages/toolkit/src/genomeclaw_toolkit/host/setup.py` *(or wherever host setup writes config)* | MODIFY | Add `_persist_colima_config(drive_root)` |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | `_stamp_pgs_row` reads resume/recovery counters from env vars |
| `bin/genomeclaw-prs-smoke` | MODIFY | Canary staging + watchdog subshell + recovery loop |
| `bin/genomeclaw-prs-smoke-helpers.sh` *(new)* | CREATE | Extracted watchdog + recovery helpers |
| `packages/toolkit/tests/unit/test_pgs_resume_argv.py` *(new)* | CREATE | `-resume` argv test |
| `packages/toolkit/tests/integration/test_host_setup_colima_config.py` *(new)* | CREATE | `host setup` writes colima.json |
| `packages/toolkit/tests/integration/test_smoke_recovery_loop.py` *(new)* | CREATE | Recovery loop stubs (watchdog + colima restart + bounded retry) |
| `packages/toolkit/tests/integration/test_pgs_resume_provenance.py` *(new)* | CREATE | `params_json` carries `resume_count` + `recovery_attempts` |

---

## Verification

```bash
cd packages/toolkit
uv run pytest \
    tests/unit/test_pgs_resume_argv.py \
    tests/integration/test_host_setup_colima_config.py \
    tests/integration/test_smoke_recovery_loop.py \
    tests/integration/test_pgs_resume_provenance.py \
    -v --no-header
uv run pytest tests/unit tests/integration tests/invariants --no-header
uv run ruff check src/genomeclaw_toolkit/prep/pgs.py \
    src/genomeclaw_toolkit/host/setup.py \
    src/genomeclaw_toolkit/_cli/commands/pipeline.py \
    bin/genomeclaw-prs-smoke
uv run mypy src/genomeclaw_toolkit/prep/pgs.py
```

Manual real-data verification (project owner's host):

```bash
# 1. Bake colima config (once, after `host setup` lands the writer):
genomeclaw host setup
cat ~/.config/genomeclaw/colima.json

# 2. Run a smoke; in a separate terminal, force a disconnect ~10 min in:
GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:phase6 \
GENOMECLAW_PHASE5_SMOKE_DIR_OVERRIDE=/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<utc> \
  bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018 &
SMOKE_PID=$!

sleep 600  # wait ~10 min so pgsc_calc has tasks worth resuming from
sudo umount -f /Volumes/Genome_Work  # forces the disconnect

# 3. Wait for the smoke to finish; inspect:
wait $SMOKE_PID
cat /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<utc>/recovery.log
cat /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<utc>/cli_envelope.json | jq '{recovery_attempts}'
# Expected: recovery.log has ≥1 cycle; recovery_attempts ≥ 1; pgsc_calc completed; aggregated_scores.txt.gz lands.
```

---

## Completion Criteria

- [ ] All listed test cases pass (≥7 tests across 4 new test files).
- [ ] Full suite green; ruff + mypy clean on touched files.
- [ ] Manual forced-disconnect smoke (step 4.6) recovers + completes with `recovery_attempts: 1` recorded in cli_envelope + params_json.
- [ ] [../work-notes.md](../work-notes.md) updated with RED outputs + Phase 4 GREEN summary + the manual smoke ledger entry.
- [ ] Phase 4 status updated in [../development-plan.md](../development-plan.md).
- [ ] Phase 5 (smoke v23+ verification) drafted if this phase closes naturally.
- [ ] F12 in the meta-plan's open-follow-ups table marked closed (already promoted INTO Phase 4.2 at plan amendment time; just confirm).

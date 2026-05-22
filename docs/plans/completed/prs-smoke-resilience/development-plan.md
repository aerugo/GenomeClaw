# PRS smoke iteration resilience — Development Plan

**Plan**: [spec.md](spec.md) | **Work Notes**: [work-notes.md](work-notes.md)
**Lineage**: closes L3 + L4 + L5 brittleness surfaced by the [prs-non-imputed-wgs](../prs-non-imputed-wgs/) Phase 4 smoke v22 ledger (v22 through v22i; 9 attempts, 4 layers of failure modes documented at [prs-non-imputed-wgs/work-notes.md](../prs-non-imputed-wgs/work-notes.md))

---

## Critical Invariants to Respect

- **`INV-D003`** Heavy scratch separated — pre-flight read-test stays in the bind-mount; doesn't write any derived data.
- **`INV-D005` / `INV-D006` / `INV-D007`** — pre-flight checks exercise the canonical mount + shim seam; same checks path-crossing-discipline already enforces, surfaced as `host doctor` probes.
- **`INV-P001`** Privacy default — pre-flight reads ONE small sidecar file; no new egress.
- **`INV-R001`** Rebuildability — Nextflow retries are bounded (`maxRetries = 2`); successful-on-retry rows record `retry_count` in `params_json`.
- **`INV-C002`** CLI Output Contract — new doctor fields are additive (no schema bump); smoke driver's typed error envelope handles pre-flight failure.

## Proposed New Invariants

**None.** Each phase strengthens existing invariants without introducing a new project-wide rule.

## Current State Analysis

**What's already in place** (from prior plans):

- `bin/genomeclaw-prs-smoke`: end-to-end driver with INV-D001 pre-snapshot + per-stage timing + smoke.log writing.
- `host doctor` (per prs-runtime-bootstrap Phase 2): reports `ancestry_ready`, `prs_runtime_ready`. No mount/drive/container probes.
- pgsc_calc wrapper (`pgs.py`): does NOT pass docker labels; does NOT clean up on failure; ERROR captures stderr only.
- `_TMPDIR_REDIRECT_CONFIG` (pgs.py): writes `beforeScript` + `stageInMode = 'copy'` + `scratch = false` + (Phase 2.E) parent-env TMPDIR override. **No `errorStrategy`** for transient task retries.

**What this plan delivers:**

1. **`host doctor` smoke-readiness probes** (Phase 1): three new fields (`colima_mount_visible`, `external_drive_readable`, `leftover_genomeclaw_containers`) + smoke driver pre-flight gate.
2. **Container-cleanup discipline** (Phase 2): label every smoke-spawned container; auto-stop on smoke entry + exit.
3. **Error capture improvements** (Phase 2): stdout+stderr in pgsc_calc RuntimeError; SIGTERM trap in smoke driver to flush partial state.
4. **Nextflow retry strategy** (Phase 3): `errorStrategy 'retry'` + `maxRetries 2` in our config + `retry_count` in `params_json`.

## Solution Design

### Phase 1 — Smoke pre-flight readiness

```python
# host doctor new fields (in _cli/commands/host.py doctor handler)
{
    "colima_mount_visible": _probe_colima_mount_visible(),
    "external_drive_readable": _probe_external_drive_read(reference_root),
    "leftover_genomeclaw_containers": _probe_leftover_smoke_containers(),
}
```

- `_probe_colima_mount_visible()`: runs a tiny `docker run --rm -v ${RAW_DIR}:/probe alpine test -d /probe` (≤2s); returns False if `docker run` rc != 0 OR if `test -d` rc != 0.
- `_probe_external_drive_read()`: reads the first 4 bytes of the canonical CRAM sidecar at `<raw>/<sample>/<sample>.cram.crai` (the smallest known file); fails if read returns 0 bytes or raises OSError. Uses `pathlib.Path.read_bytes()[:4]`; if `<sample>` is `MPNRGLQ2K`, file is ~1 MB so safe.
- `_probe_leftover_smoke_containers()`: shells out to `docker ps -a --filter label=genomeclaw-smoke --format '{{.ID}} {{.Status}}'` and returns the parsed list; empty list = clean.

Smoke driver pre-flight gate (in `bin/genomeclaw-prs-smoke`, BEFORE the existing INV-D001 pre-snapshot stage):

```bash
preflight_json=$(genomeclaw --json doctor)
if ! echo "$preflight_json" | jq -e '.colima_mount_visible' >/dev/null; then
    echo "PRE-FLIGHT FAIL: Colima mount not visible. Run: colima start --mount /Volumes/Genome_Work:w"
    exit 2
fi
# ... similar for external_drive_readable + leftover_genomeclaw_containers
```

### Phase 2 — Container cleanup + error capture

**Labels**: shim adds `--label genomeclaw-smoke=$GENOMECLAW_SMOKE_RUN_ID` (defaults to current UTC iso) when invoked from a smoke run. Existing `--mount` block stays unchanged.

**Cleanup pass**: smoke driver `trap 'genomeclaw_cleanup' EXIT INT TERM` that runs:

```bash
genomeclaw_cleanup() {
    local rc=$?
    docker ps -aq --filter "label=genomeclaw-smoke=$GENOMECLAW_SMOKE_RUN_ID" | xargs -r docker stop > "$SMOKE_DIR/cleanup.log" 2>&1
    docker ps -aq --filter "label=genomeclaw-smoke=$GENOMECLAW_SMOKE_RUN_ID" | xargs -r docker rm >> "$SMOKE_DIR/cleanup.log" 2>&1
    # If smoke driver was killed mid-stage, flush partial progress
    if [[ -n "$CURRENT_STAGE" && -z "${STAGE_COMPLETED:-}" ]]; then
        echo "PARTIAL-EXIT: stage=$CURRENT_STAGE rc=$rc (smoke driver SIGTERM'd)" >> "$SMOKE_DIR/smoke.log"
    fi
}
```

**Improved error capture in `compute_pgs`** (pgs.py):

```python
if proc.returncode != 0:
    stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
    stdout_text = proc.stdout.decode("utf-8", errors="replace").strip()
    raise RuntimeError(
        f"pgsc_calc failed (rc={proc.returncode}):\n"
        f"--- stderr ---\n{stderr_text}\n"
        f"--- stdout (last 50 lines) ---\n"
        + "\n".join(stdout_text.splitlines()[-50:])
    )
```

### Phase 3 — Nextflow retry strategy

Extend `_TMPDIR_REDIRECT_CONFIG` in pgs.py:

```groovy
process {
    beforeScript = 'export TMPDIR="${PWD}"'
    stageInMode = 'copy'
    scratch = false  // (already present)
    // NEW: bounded retry for known-transient task failures.
    // pgsc_calc's pgscatalog-intersect uses tempfile + heapq.merge in
    // a way that surfaces ~5% KeyError on the heap-init step (smoke
    // v22d, 2026-05-21). 2 retries is enough — empirically the
    // failure rate per task is <10%, so success after 2 retries is
    // (1 - 0.1^3) = 99.9%.
    errorStrategy = { task.attempt < 3 ? 'retry' : 'terminate' }
    maxRetries = 2
}
```

Plus extend `_stamp_pgs_row` to parse Nextflow's `.nextflow.log` for retry events and persist `retry_count` per task.

### Phase 4 — Mid-run watchdog + Nextflow resume + Colima mount recovery

The post-v22-ledger reality check (v22g/v22h/v22j: 3 of 10 attempts died to mid-run external-drive bind-mount loss) made this phase mandatory rather than stretch. The previously-sketched F9 (internal-SSD staging) is infeasible on the project owner's ~30 GB free SSD vs. pgsc_calc's ~58 GB peak work_dir — so the L4 fix has to be **detect-kill-recover-resume** instead of "avoid the external drive entirely."

Key insight: **Nextflow has native `-resume` support**. The work_dir's task-completion markers survive the disconnect (the drive is fine; only Colima's view of it is bad). Refresh the Colima mount → rerun with `-resume` → skip completed tasks → continue.

Four sub-phases:

**4.1 — `-resume` flag in pgsc_calc argv**

```python
# pgs.py:_build_pgsc_calc_argv (sketch)
argv += [
    ...,
    "-resume",  # NEW
    conv.work_dir_flag,
    str(work_dir),
]
```

One-line change + a unit test asserting `-resume` is in the emitted argv. Safe to enable unconditionally: on a fresh `work_dir`, `-resume` is a no-op (no cached tasks to skip).

**4.2 — Smoke driver watchdog**

A background bash loop in `bin/genomeclaw-prs-smoke` that probes a canary file every 60s while pgsc_calc runs:

```bash
# Stage a canary file on smoke start
echo "$(date -u +%s)" > "${DRIVE}/genomeclaw/raw/.canary"

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

The watchdog runs as a subshell `&`; cleans up when pgsc_calc exits OR when the recovery flag fires.

**4.3 — Recovery loop in the smoke driver**

```bash
COLIMA_ARGS_FILE="${HOME}/.config/genomeclaw/colima.json"
run_pgsc_calc_with_recovery() {
    local max_attempts="${GENOMECLAW_MAX_RECOVERY_ATTEMPTS:-3}"
    local attempt=0
    while (( attempt < max_attempts )); do
        run_pgsc_calc_with_watchdog
        local rc=$?
        if (( rc == 0 )); then return 0; fi
        if [[ ! -f "$SMOKE_DIR/.recovery_needed" ]]; then
            # Real pgsc_calc failure (not infra) — don't retry.
            return "$rc"
        fi
        attempt=$((attempt + 1))
        echo "Recovery attempt $attempt/$max_attempts: refreshing Colima mount" \
            | tee -a "$SMOKE_DIR/recovery.log"
        colima stop
        # Wait for stable drive presence — don't recover into a bouncing drive.
        local stable_seconds=0
        while (( stable_seconds < 30 )); do
            if timeout 10 ls "${DRIVE}/genomeclaw/raw/" >/dev/null 2>&1; then
                stable_seconds=$((stable_seconds + 5))
            else
                stable_seconds=0
            fi
            sleep 5
        done
        # Restart Colima with the canonical args persisted by host setup.
        local colima_args
        colima_args=$(jq -r '.start_args | join(" ")' "$COLIMA_ARGS_FILE")
        colima start $colima_args
        rm "$SMOKE_DIR/.recovery_needed"
        # Loop continues; next iteration runs pgsc_calc with -resume already
        # in argv, so completed tasks get skipped.
    done
    echo "RECOVERY EXHAUSTED: $max_attempts attempts; drive too unstable" \
        | tee -a "$SMOKE_DIR/recovery.log"
    return 87  # custom rc for "max recovery attempts hit"
}
```

**4.4 — Colima config persistence via `host setup`**

```python
# packages/toolkit/src/genomeclaw_toolkit/host/setup.py (sketch)
# At install time, write the canonical colima args used during host setup:
config_dir = Path.home() / ".config" / "genomeclaw"
config_dir.mkdir(parents=True, exist_ok=True)
colima_config = config_dir / "colima.json"
colima_config.write_text(json.dumps({
    "start_args": [
        "--cpu", "2",
        "--memory", "12",
        "--disk", "40",
        "--mount", f"{drive_root}:w",
    ],
    "written_by": "genomeclaw host setup",
    "written_at": datetime.now(UTC).isoformat(),
}, indent=2))
```

The smoke driver's recovery loop sources from this file. If missing, the driver fails with a documented "run `genomeclaw host setup` first" hint instead of guessing.

**4.5 — `resume_count` provenance**

Extend `_stamp_pgs_row` to record the number of pgsc_calc invocations it took (1 = clean run; 2+ = at least one recovery cycle). Surfaced in `pgs_scores.params_json` per INV-R001 so a downstream report can flag "this run needed N recovery cycles; drive may be unstable."

## Phase Overview

| Phase | TDD focus | Tests | Promotes |
|-------|-----------|-------|----------|
| **Phase 1** — Smoke pre-flight readiness | host doctor probes + smoke driver gate | 3 unit (one per new doctor field) + 1 integration (smoke driver rc=2 on pre-flight fail) | Catches L4-at-startup (v22h case) |
| **Phase 2** — Container cleanup + error capture | label discipline + cleanup pass + pgsc_calc error includes stdout | 2 unit (cleanup pass invokes label filter; pgsc_calc RuntimeError contains both streams) + 1 integration (smoke driver labels + cleans containers) | Closes L5 (smoke-driver fragility); makes iteration cheaper |
| **Phase 3** — Nextflow retry strategy | `errorStrategy 'retry'` + `maxRetries 2` baked into config; `retry_count` in params_json | 1 unit (config text gate); 1 integration (params_json carries retry_count after retried Nextflow run) | Closes L3 (transient pgsc_calc bugs like v22d's KeyError) |
| **Phase 4** *(promoted from stretch)* — Mid-run watchdog + Nextflow resume + Colima recovery | `-resume` in argv + canary watchdog + recovery loop + colima.json persistence + resume_count provenance | 1 unit (argv contains `-resume`); 1 unit (host setup writes colima.json); 1 integration (recovery loop invokes `colima start` with persisted args + reruns pgsc_calc); 1 manual real-data smoke (forced disconnect → recovery → resume → success) | **Closes mid-run L4** (v22g, v22j cases); enables long pgsc_calc smokes on flaky external-drive setups |
| **Phase 5** *(new stretch)* — Smoke v23+ verification | post-Phase-1-through-4 smoke ledger entry; confirm all five resilience layers exercised end-to-end | Smoke ledger entry | — |

## Testing Strategy

### Unit Tests
- `test_doctor_reports_colima_mount_visible_field` — doctor's JSON envelope carries the field; asserts True/False on a stubbed docker-probe.
- `test_doctor_reports_external_drive_readable_field` — same shape.
- `test_doctor_reports_leftover_genomeclaw_containers_field` — same shape; asserts list type.
- `test_tmpdir_redirect_config_includes_errorStrategy_retry` — text assertion on `_TMPDIR_REDIRECT_CONFIG`.
- `test_compute_pgs_error_includes_both_stdout_and_stderr` — RuntimeError message contains both `--- stderr ---` and `--- stdout` markers.
- `test_genomeclaw_cleanup_filters_by_label` — cleanup function shells out with the right `--filter label=` argument.

### Integration Tests
- `test_smoke_driver_pre_flight_exits_rc2_on_unmounted_drive` — fixtured "unmounted drive" state; smoke driver exits rc=2 BEFORE Tier 1.
- `test_smoke_driver_labels_toolkit_container` — shim's docker run includes `--label genomeclaw-smoke=<run-id>`; verified by argv inspection.
- `test_pgs_scores_params_json_carries_retry_count` — synthetic Nextflow .log with 1 retry event; params_json records `retry_count: 1`.

### Real-data Smoke Gate
- **Smoke v23** (Phase 4 stretch): post-resilience-fixes rerun of v22; should complete to `pgs_scores` row OR fail-fast with actionable diagnostic in ≤30s if pre-flight check fails.

## Documentation Updates

- [docs/reference/architecture.md](../../../reference/architecture.md): no new architectural concept; the PRS pipeline operational reality section gets a 1-line addition about pre-flight readiness.
- [docs/reports/prs-real-data-smoke-research-findings.md](../../../reports/prs-real-data-smoke-research-findings.md): no change (the findings doc captures the bioinformatics; this plan captures the operations).
- [docs/plans/active/prs-bootstrap-meta.md](../prs-bootstrap-meta.md): Stage 3.6 row added; cascade diagram extended.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — Smoke pre-flight readiness | RED + GREEN landed; REFACTOR pending | 2026-05-21 | 2026-05-21 (GREEN) | 6 doctor probe tests (3 fields × {ready, broken}) + 3 new collectors in `prep/doctor.py` + smoke driver pre-flight gate at lines 89-141 of `bin/genomeclaw-prs-smoke`. 737 passed / 108 skipped / 0 failed. ruff + mypy clean. |
| Phase 2 — Container cleanup + error capture | RED + GREEN landed | 2026-05-21 | 2026-05-21 | 2.1 — `compute_pgs` RuntimeError now includes BOTH stdout + stderr (the v22 ledger's "Nextflow 26.04.1 is available" red herring is gone; real DAG-abort errors surface from stdout). 2.2 — shim threads `GENOMECLAW_SMOKE_RUN_ID` → `--label genomeclaw-smoke=<id>` onto every docker run; smoke driver exports run-id + installs EXIT/INT/TERM trap that cleans up labeled containers. 3 new tests; 740 passed / 108 skipped / 0 failed. Plus INV-D007 allow-list updated to permit the Phase 1 Alpine probe with justification. |
| Phase 3 — Nextflow retry strategy | RED + GREEN landed | 2026-05-21 | 2026-05-21 | `errorStrategy = 'retry'` + `maxRetries = 2` added to `_TMPDIR_REDIRECT_CONFIG`'s process block. 1 new test (config-text gate). 741 passed / 108 / 0. v22d's transient KeyError class would now retry up to 2 times instead of aborting the DAG. |
| Phase 4 — Mid-run watchdog + Nextflow resume + Colima recovery | 4.1–4.3 RED + GREEN landed; 4.4–4.6 deferred | 2026-05-21 | 2026-05-21 (4.1–4.3 GREEN) | 4.1 — `-resume` added to `_build_pgsc_calc_argv` (1 unit test gates argv contains `-resume`). 4.2 — smoke driver stages `<raw>/.canary` + runs `prs_smoke_watchdog` subshell on a 60s loop with `recovery_needed` signal flag (2 driver-text tests). 4.3 — smoke driver wraps Stage C in `run_pgsc_calc_with_recovery` bounded loop: on `.recovery_needed`, runs `colima stop && colima start --mount $DRIVE:w` and retries with `-resume` (Nextflow picks up cached tasks); rc=87 if `GENOMECLAW_MAX_RECOVERY_ATTEMPTS` (default 3) exhausted (1 driver-text test). 745 passed / 108 skipped / 0 failed. ruff/mypy unchanged (1 pre-existing F401 + 16 pre-existing mypy errors unrelated to Phase 4). 4.4 (colima.json persistence in `host setup`) + 4.5 (`recovery_attempts` in `params_json`) + 4.6 (real-data smoke with forced disconnect) deferred pending a smoke v23 run to confirm the recovery loop closes mid-run L4. |
| Phase 5 *(stretch)* — Smoke v23+ verification | **PASS** | 2026-05-22 | 2026-05-22 | v23 produced ancestry-calibrated PRS end-to-end: MPNRGLQ2K PGS000018 SUM=9.665, DENOM=1,728,050, Z=-1.04 vs EUR, **percentile=14.54 within EUR**. Match rate 49.51% (vs v17's 28.4%). Tier 1: 91 min / Tier 2+merge+norm+pgsc_calc: 235 min. Pre-flight L4 probe caught stale Colima mount at startup (rc=2, ≤30s) on first launch — proved the Phase 1 fail-fast diagnostic. Watchdog armed throughout Stage C; bind-mount held stable; recovery loop didn't need to fire. Post-processing heredoc bug surfaced (`$INV_D001_EQUAL` bash `true` substituted into Python) — fixed in-place. Invariant audit all green (INV-D001/D003/R001/P001/C001 v1.7). |

## Follow-ups out of scope here

- **F9** *(deferred but no longer the targeted L4 fix)*: pgsc_calc internal-SSD staging. Reality check 2026-05-21: pgsc_calc work_dir peaks at ~58 GB during a run; project owner's setup has ~30 GB free internal SSD. Bundle-only staging (16 GB) is feasible but doesn't remove mid-run external-drive write I/O — and Phase 4's recovery loop addresses the mid-run case more directly. F9 stays open for future setups with bigger internal SSDs.
- **F10**: pgsc_calc Singularity profile (avoids DooD complications altogether; image-build path change + conventions dataclass update).
- **F11**: CI integration for the real-data smoke (per the meta-plan's existing CI follow-up).
- ~~**F12**: Periodic in-flight pre-flight re-check during long pgsc_calc runs~~ *(closed 2026-05-21 — promoted INTO this plan as Phase 4.2 watchdog)*.

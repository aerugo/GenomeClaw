# Phase 1: Smoke pre-flight readiness probes

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Add three structural readiness fields to `genomeclaw host doctor`'s output, then gate the smoke driver on those fields BEFORE the expensive Tier 1 + pgsc_calc stages. Closes L4 brittleness (v22g + v22h ×2): when Colima loses its mount, or the external drive disconnects, or a prior smoke left zombie containers running, the smoke now fails fast (≤30s) with an actionable diagnostic instead of burning 1–8 hours before crashing.

## Scope Boundaries

- **In scope**: `host doctor` JSON envelope gains `colima_mount_visible: bool`, `external_drive_readable: bool`, `leftover_genomeclaw_containers: list[str]`. Smoke driver checks all three before invoking Tier 1 stages.
- **Out of scope**:
  - Container cleanup-on-exit (Phase 2 — label discipline + EXIT trap).
  - Auto-recovery (e.g., auto-`colima start` if mount missing). Doctor reports + smoke aborts; remediation stays human-driven.
  - Per-canonical-path read-tests (per spec Q1: one representative is enough).
  - Periodic in-flight heartbeat (per spec Q2: punted to F12).

## Invariants Enforced in This Phase

- **INV-D003** — pre-flight read-test reads from the bind-mount; never writes derived data.
- **INV-D005 / D006 / D007** — `colima_mount_visible` probe exercises the same shim-+-mount seam path-crossing-discipline enforces. Test asserts the probe uses the canonical mount target (`/Volumes/Genome_Work/...`).
- **INV-P001** — `external_drive_readable` reads ONE small sidecar file (~1 MB); no new external network egress.
- **INV-C002** — three new doctor fields are additive (no `cli_output_schema_version` bump); smoke driver's typed error envelope handles pre-flight failure (rc=2).

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases** (under `packages/toolkit/tests/`):

1. `test_doctor_reports_colima_mount_visible_field` (unit) — patches `subprocess.run` to simulate `docker run alpine test -d /probe` returning rc=0; asserts the doctor envelope has `colima_mount_visible: True`. RED: `KeyError` (field absent).
2. `test_doctor_reports_colima_mount_visible_false_when_docker_unavailable` (unit) — patches docker to rc != 0; asserts the doctor envelope has `colima_mount_visible: False` (NOT a raise).
3. `test_doctor_reports_external_drive_readable_field` (unit) — patches a temp sidecar file; asserts the doctor envelope has `external_drive_readable: True`. RED: field absent.
4. `test_doctor_reports_leftover_genomeclaw_containers_field` (unit) — patches `docker ps -a --filter label=genomeclaw-smoke` to return 2 container IDs; asserts the doctor envelope's `leftover_genomeclaw_containers` is a 2-element list. RED: field absent.
5. `test_smoke_driver_pre_flight_exits_rc2_on_unmounted_drive` (integration) — fixtures a stub `genomeclaw doctor` that returns `colima_mount_visible: False`; runs `bin/genomeclaw-prs-smoke` against it; asserts the smoke driver exits rc=2 BEFORE invoking the Tier 1 stage. Verified by inspecting `smoke.log` for the absence of `prepare_coverage_tier1`. Expected RED: smoke driver doesn't check pre-flight; runs into Tier 1; exits with whatever rc the docker invocation produces.

After writing, run + confirm. Paste failing output into [../work-notes.md](../work-notes.md).

### Step 1.2 — GREEN: Minimal Implementation

1. **`_cli/commands/host.py`** (doctor handler): add `_probe_colima_mount_visible(raw_dir)`, `_probe_external_drive_read(reference_root)`, `_probe_leftover_smoke_containers()` helpers. Wire the three fields into the existing doctor JSON envelope.
2. **`bin/genomeclaw-prs-smoke`**: at the top (BEFORE INV-D001 pre-snapshot), add the pre-flight gate:
   ```bash
   echo "==> pre-flight readiness check" | tee -a "$SMOKE_DIR/smoke.log"
   preflight_json=$(genomeclaw --json doctor)
   if ! echo "$preflight_json" | jq -e '.colima_mount_visible == true' >/dev/null; then
       echo "PRE-FLIGHT FAIL: Colima mount not visible. Run: colima start --mount /Volumes/Genome_Work:w" | tee -a "$SMOKE_DIR/smoke.log"
       exit 2
   fi
   # ... similar for external_drive_readable + leftover_genomeclaw_containers
   ```

### Step 1.3 — REFACTOR

- Tighten types: `colima_mount_visible` and `external_drive_readable` are `bool` (not `str`); `leftover_genomeclaw_containers` is `list[str]` (container IDs only, not full status strings — that goes in cleanup.log).
- Extract `_DoctorPreflight` dataclass if the three probes share more than ~3 lines of setup.
- ruff + mypy clean on touched files.

---

## Implementation Details

### Edge Cases to Handle

- **Docker daemon not running**: `_probe_colima_mount_visible` returns False (not a raise). Caller sees `colima_mount_visible: False` and the user-facing error message tells them to start Colima.
- **External drive unmounted**: `Path.read_bytes()` raises `OSError` with errno=ENOENT or errno=EIO. Probe catches OSError → returns False.
- **Multiple leftover containers**: `leftover_genomeclaw_containers` returns ALL of them; Phase 2 will auto-stop them.
- **Doctor invoked without bind-mount paths configured**: the canonical raw_dir/reference_root come from `GENOMECLAW_*_DIR` env vars; if missing, probes return False with a "not-configured" reason.

### Error Handling

- `genomeclaw --json doctor` always returns a JSON envelope (per INV-C002); pre-flight readiness fields are inside the existing envelope structure, not separate top-level commands.
- The smoke driver's `exit 2` is a deliberate rc choice — distinguishes "pre-flight failure" from `exit 1` (pgsc_calc failure) and `exit 0` (success).

### Privacy / Egress Notes

- Pre-flight reads ≤4 bytes from one bind-mounted file. No network egress.
- The leftover-containers probe shells out to `docker ps -a` (local socket); no external calls.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Add 3 probe helpers + extend doctor envelope |
| `bin/genomeclaw-prs-smoke` | MODIFY | Add pre-flight gate before existing INV-D001 stage |
| `packages/toolkit/tests/integration/test_doctor.py` | MODIFY | + 3 unit tests for the new fields |
| `packages/toolkit/tests/integration/test_prs_smoke_preflight.py` | CREATE | 1 integration test for smoke driver pre-flight gate |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/integration/test_doctor.py tests/integration/test_prs_smoke_preflight.py -v --no-header
uv run pytest tests/unit tests/integration tests/invariants --no-header
uv run ruff check src/genomeclaw_toolkit/_cli/commands/host.py bin/genomeclaw-prs-smoke
uv run mypy src/genomeclaw_toolkit/_cli/commands/host.py
```

Manual verification (on the project owner's host):

```bash
# 1. With Colima running + drive mounted:
genomeclaw --json doctor | jq '{colima_mount_visible, external_drive_readable, leftover_genomeclaw_containers}'
# Expect: {"colima_mount_visible": true, "external_drive_readable": true, "leftover_genomeclaw_containers": []}

# 2. Stop Colima:
colima stop
genomeclaw --json doctor | jq '.colima_mount_visible'
# Expect: false

# 3. Smoke driver pre-flight gate (after Colima still stopped):
bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018 ; echo "rc=$?"
# Expect: rc=2 within 30s, with the "Run: colima start --mount ..." hint
```

---

## Completion Criteria

- [ ] All 5 listed test cases pass.
- [ ] Full suite green; ruff + mypy clean on touched files.
- [ ] Manual verification (above) confirms the pre-flight gate fires + the smoke driver exits rc=2 in <30s.
- [ ] [../work-notes.md](../work-notes.md) updated with RED output + Phase 1 GREEN summary.
- [ ] Phase status updated in [../development-plan.md](../development-plan.md).
- [ ] [../phases/phase-2.md](phase-2.md) drafted if next phase is in scope.

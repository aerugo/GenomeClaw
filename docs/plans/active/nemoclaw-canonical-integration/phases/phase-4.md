# Phase 4: Simplify Onboard Script + Recovery Wrapper

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Now that NemoClaw owns the gateway lifecycle (Phase 3), strip the remaining workaround layers from `scripts/onboard-sandbox.sh` and update `scripts/sandbox-up.sh` to delegate gateway recovery to `nemoclaw <name> recover`. Decide whether `sandbox-up.sh` should remain a separate entry point or fold into `onboard-sandbox.sh` based on Phase 3 results.

## Scope Boundaries

- **In scope**: cleanup of `onboard-sandbox.sh` (rewrite Step 8 smoke; possibly drop Step 6 if NemoClaw credential system replaces auth-profiles.json); rewrite of `sandbox-up.sh` recovery logic.
- **Out of scope**: Dockerfile changes (Phase 2); credential system migration (Phase 3, already done); UX docs (Phase 6).

## Invariants Enforced in This Phase

- **INV-V001** Verification Methodology — recovery success verified via HTTP probe + process inspection; no log-grep enumeration.

---

## TDD Steps

### Step 4.1 — RED: Write Failing Tests

**Test cases**:

1. `test_onboard_script_no_docker_exec_gateway_run` — static check on `scripts/onboard-sandbox.sh`: assert no line matches `docker exec.*openclaw gateway run` (Step 7b ghost). Should pass already if Phase 3 went clean, but pin it as a regression guard here.
2. `test_sandbox_up_delegates_to_nemoclaw_recover` — static check on `scripts/sandbox-up.sh`: assert it invokes `nemoclaw .* recover` (or equivalent) as its primary recovery action; any direct `docker exec ... gateway run` is gated by an explicit fallback flag (e.g., `--force-direct-restart`) AND is documented in the script comments as a fallback.
3. `test_recovery_after_kill_restores_gateway` — boot the sandbox, kill `openclaw gateway` PID inside the container, run `./scripts/sandbox-up.sh`, assert gateway responds at 127.0.0.1:18789 within 30s.
4. `test_recovery_after_container_restart` — `docker restart <container>`, then `./scripts/sandbox-up.sh`, assert gateway healthy. Verifies the credential reloader survives container restart.
5. `test_no_step_8_log_grep_remnants` — confirm Step 8's rewritten smoke test uses an HTTP probe (`curl http://127.0.0.1:18789/healthz`) or `openclaw plugins list --json | jq`, not log substring matching — INV-V001 discipline.
6. `test_phase4_muscle_question_after_recovery_smoke` — **end-to-end smoke gate**. Boot the sandbox; kill the gateway (`pkill -f openclaw\ gateway` inside the container); run `./scripts/sandbox-up.sh`; after gateway HTTP probe is green, run `./scripts/ask.sh --capture "<muscle question>"`. Assert: trace parses; reply > 200 chars; ≥1 successful `genomeclaw_*` tool call; with `GENOMECLAW_REPLAY_LLM=1`, LLM-judge clean. This is the test that proves recovery actually restores a *working* agent, not just a process that listens on a port.

**Sketch**:

```python
def test_onboard_script_no_docker_exec_gateway_run():
    script = Path("scripts/onboard-sandbox.sh").read_text()
    assert not re.search(r"docker exec.*openclaw gateway run", script), \
        "Phase 3 leftover: Step 7b docker-exec gateway-run pattern still present"

def test_sandbox_up_delegates_to_nemoclaw_recover():
    script = Path("scripts/sandbox-up.sh").read_text()
    assert re.search(r"nemoclaw \S+ recover", script), "must delegate to nemoclaw recover"
    # Any direct docker-exec restart must be gated by an explicit flag
    direct_restart = re.findall(r"docker exec.*gateway", script)
    if direct_restart:
        for line in direct_restart:
            # The lines must follow a guarded if-block checking a flag like --force-direct-restart
            assert "FORCE_DIRECT" in script or "--force-direct" in script, \
                "direct restart present without an explicit fallback flag"

def test_recovery_after_kill_restores_gateway(onboarded_sandbox):
    docker_exec(onboarded_sandbox, ["pkill", "-f", "openclaw gateway"])
    subprocess.run(["./scripts/sandbox-up.sh"], check=True, timeout=60)
    assert httpx.get("http://127.0.0.1:18789/healthz", timeout=5).status_code == 200
```

Run; confirm RED for the appropriate reasons (sandbox-up still has direct restart unconditionally; recovery test fails depending on current sandbox-up.sh behavior). Paste output into work-notes.

### Step 4.2 — GREEN: Minimal Implementation

1. In `scripts/onboard-sandbox.sh`:
   - Rewrite Step 8 (smoke test) to verify via HTTP probe + structured CLI (`openclaw plugins list --json | jq -e '.plugins[] | select(.id=="genomeclaw")'`).
   - If Phase 3 found NemoClaw credentials make `auth-profiles.json` redundant, drop Step 6; otherwise keep but document why.
2. In `scripts/sandbox-up.sh`:
   - Primary recovery action: `nemoclaw genomeclaw recover`.
   - Wait for gateway HTTP health (poll up to 30s).
   - If `nemoclaw recover` fails AND the user set `GENOMECLAW_FORCE_DIRECT_RESTART=1`, fall back to `docker exec`-based restart. Print a clear warning. Default: bail with a clear error pointing to upstream NemoClaw docs.
3. Re-run all five tests. Confirm green.

**Files affected**:
- [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh): MODIFY
- [scripts/sandbox-up.sh](../../../../scripts/sandbox-up.sh): MODIFY
- `packages/toolkit/tests/integration/test_phase4_recovery.py`: CREATE
- `packages/toolkit/tests/integration/test_phase4_script_shape.py`: CREATE

### Step 4.3 — REFACTOR

- Extract the gateway-health-wait loop into a shared bash helper sourced by both scripts.
- Move comment lineage to a brief CHANGELOG block at the top of each script.

---

## Implementation Details

### Edge Cases to Handle

- **NemoClaw `recover` itself fails** (upstream bug in 2026.5.18): trip the fallback warning; document in work-notes; file an upstream bug as a follow-up if so.
- **Container restart loses /sandbox state**: shouldn't happen with the canonical persistence model, but if NemoClaw doesn't auto-restart the gateway on container restart, `sandbox-up.sh`'s `recover` call is what brings it back.
- **Concurrent invocation**: if two users run `sandbox-up.sh` simultaneously, both call `nemoclaw recover`. Should be idempotent; if not, add a lockfile.

### Error Handling

- All recovery paths surface non-zero exit codes with actionable error messages pointing to `nemoclaw <name> status` and `docs/plans/active/nemoclaw-canonical-integration/`.
- The fallback `docker exec` path explicitly warns about credential-reloader drift (the same hazard Phase 3 removed).

### Privacy / Egress Notes

- No new egress.
- The fallback docker-exec restart path, if triggered, re-introduces the `-e OPENAI_API_KEY` injection. INV-P003 is still satisfied because env vars are not argv, but the credential reloader divergence returns — that's why it's gated behind an opt-in flag.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) | MODIFY | Rewrite Step 8 smoke; drop Step 6 if redundant |
| [scripts/sandbox-up.sh](../../../../scripts/sandbox-up.sh) | MODIFY | Delegate recovery to `nemoclaw recover` |
| `packages/toolkit/tests/integration/test_phase4_recovery.py` | CREATE | Tests 3, 4 (kill + container-restart recovery) |
| `packages/toolkit/tests/integration/test_phase4_script_shape.py` | CREATE | Tests 1, 2, 5 (static script analysis) |
| [docs/plans/active/nemoclaw-canonical-integration/work-notes.md](../work-notes.md) | MODIFY | Phase 4 progress + decisions |

---

## Verification

```bash
# Run Phase 4 tests
uv --project packages/toolkit run pytest \
  packages/toolkit/tests/integration/test_phase4_recovery.py \
  packages/toolkit/tests/integration/test_phase4_script_shape.py -v

# Manual: kill recovery loop
docker exec --user sandbox $(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1) pkill -f openclaw\ gateway
./scripts/sandbox-up.sh
curl -s http://127.0.0.1:18789/healthz

# Manual: container restart
docker restart $(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)
./scripts/sandbox-up.sh
curl -s http://127.0.0.1:18789/healthz

# End-to-end smoke gate after recovery
GENOMECLAW_REPLAY_LLM=1 ./scripts/ask.sh --capture \
  "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."
```

---

## Completion Criteria

- [ ] `onboard-sandbox.sh` Step 8 uses HTTP probe + structured CLI, not log substring matching
- [ ] `sandbox-up.sh` primary path is `nemoclaw <name> recover`
- [ ] Any direct `docker exec gateway run` is gated by `GENOMECLAW_FORCE_DIRECT_RESTART=1` opt-in and clearly warned
- [ ] All six Phase 4 tests pass (5 structural + 1 muscle-question-after-recovery smoke)
- [ ] Manual kill-and-recover smoke works
- [ ] Manual container-restart smoke works
- [ ] Muscle-question smoke after recovery: synthesized reply + LLM-judge clean
- [ ] No regression in existing tests
- [ ] `work-notes.md` Phase 4 § Test Results updated
- [ ] Phase status updated in `development-plan.md`

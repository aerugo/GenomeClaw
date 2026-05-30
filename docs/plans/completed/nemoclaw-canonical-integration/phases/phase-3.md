# Phase 3: Gateway Lifecycle + Credential System Hand-Off

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Stop launching the gateway via `docker exec -d openclaw gateway run`. Register `OPENAI_API_KEY` through NemoClaw's credential system at onboard time so NemoClaw's supervisor owns the gateway and the credential reloader can restart it on recovery. After this phase, a fresh onboard finishes with the gateway healthy at the expected port (18789) without any direct `docker exec` involvement in gateway lifecycle. `INV-P003` continues to hold.

## ⚠️ Prerequisites discovered during the Phase 2 smoke (2026-05-30)

The Phase 2 muscle-question smoke FAILED and the root-cause investigation (see work-notes Phase 2) found that this phase is now **load-bearing for the entire plan** — it is the unifying fix for the original dashboard/connect/TUI breakage, not just a credential-storage cleanup. Two concrete facets must be fixed here, BEFORE any agent smoke can pass:

- **Facet A — ✅ RESOLVED (2026-05-30).** A1: baked `gateway.bind=loopback` (no token — privacy review). A2: deleted onboard Step 6 (literal-key `auth-profiles.json`, reviewer HIGH finding) + dead Step 7 (`inference.local`); the key stays env-only via Step 7b (`docker exec -e`, INV-P003-clean), guarded by `test_invP003_onboard_*`. The full native L7-proxy credential ownership is infeasible on local Docker (no `inference.local` DNS / model-router; `nemoclaw inference set` sandbox-sync uses a failing k8s path) — documented as an upstream/Phase-4 follow-up. Clean re-onboard verified end-to-end. Diagnostic narrative retained below for context.
- **Facet A (original diagnosis) — the gateway refuses to start in-container without auth.** `sandbox-base:v0.0.50`'s gateway, in a container, defaults to `bind=auto` (0.0.0.0) and prints *"Refusing to bind gateway to auto without auth"* unless a token/password is configured. The image bakes `gateway.mode=local` but NOT `gateway.bind` or `gateway.auth.mode`. This is why onboard Step 7b's bare `openclaw gateway run` fails, why `nemoclaw genomeclaw connect --probe-only` reports *"automatic recovery failed"* (its `/tmp/gateway.log` shows the exact refusal), and why the dashboard/TUI never come up.
  - **Fix options** (pick deliberately — this is a security-posture decision, run it past `privacy-safety-reviewer`):
    1. Bake `gateway.bind=loopback` + `gateway.auth.mode=none`. Simplest; the gateway is loopback-only inside the container and reached via NemoClaw's authenticated port-forward/SSH. Verify the dashboard port-forward still reaches a loopback-bound gateway.
    2. Bake `gateway.auth.mode=token` + a persisted `gateway.auth.token`, and ensure every client (embedded agent, dashboard, TUI) uses the same token. Keeps `bind=auto` working for port-forward but adds token plumbing (and an INV-P003 check that the token isn't placed on argv).
  - Empirically, `openclaw gateway run --bind loopback --auth none` DOES start cleanly (`auth mode=none … ready`), so option 1 is known-startable — but see Facet B (it alone is not sufficient).
- **Facet B — ✅ RESOLVED (2026-05-30).** Fixed by adding `activation.onStartup: true` + `contracts.tools` (the 9 production tool names) to `packages/nemoclaw-plugin/openclaw.plugin.json`, guarded by `packages/toolkit/tests/invariants/test_plugin_manifest_tool_contract.py`. Verified live: gateway loads `1 plugin: genomeclaw`, agent calls `genomeclaw_status` (`toolSummary.calls=1`, `thinking=xhigh`). No Dockerfile change needed (the manifest is already COPY'd). The diagnostic narrative below is retained for context. (Deep-dived 2026-05-30 — see work-notes Phase 2 "Facet B deep-dive" for the full evidence.) With a loopback+auth-none gateway up, the gateway logs `http server listening (0 plugins)` and `openclaw agent --agent genomeclaw` (via gateway, `thinking=xhigh`) still gets `genomeclaw_status: command not found`. The gateway loads plugins via **npm-package resolution** (it auto-enables `weixin` from `~/.openclaw/npm/node_modules/`), and **ignores `plugins.load.paths`** (set by `install --link`) — `load.paths` is honored only by the CLI and the embedded agent, which is why `plugins list` shows `enabled` and `registered 9 tools` logs on every CLI load while the gateway's tool registry stays empty. A non-`--link` install copies to `~/.openclaw/extensions/` (NOT auto-scanned in v0.0.50), and a symlink into `~/.openclaw/npm/node_modules/@genomeclaw/nemoclaw-plugin` also failed to load.
  - **ROOT CAUSE FOUND via online research (2026-05-30) — see [initial_findings.md](../initial_findings.md).** OpenClaw builds the gateway/agent tool catalog from **cold manifest metadata** (`openclaw.plugin.json` → `contracts.tools`), read *without importing the plugin runtime*. Our manifest has **no `contracts` and no `activation` block**, so the gateway never learns the plugin owns any tools → 0 surfaced. The `registerTool(...)` calls only execute when the runtime is imported (CLI/embedded), which is why CLI logs "registered 9 tools" while the gateway catalog is empty. Documented behavior, not a bug (GitHub openclaw#61790/#47683/#50328 closed as such). Reconciles the OLD-image anchor: OpenClaw **2026.4.24** surfaced runtime-registered tools eagerly; **2026.5.18** (our `:v0.0.50` pin) requires the cold-metadata contract.
  - **Fix (documented contract)**: add to `packages/nemoclaw-plugin/openclaw.plugin.json`:
    - `"contracts": { "tools": [<every name passed to api.registerTool>] }` — the discovery contract.
    - `"activation": { "onStartup": true }` — so the gateway loads the plugin at startup.
    Keep `definePluginEntry` + `api.registerTool` (already used) and `@sinclair/typebox` in `dependencies` (already present). If `openclaw plugins build` exists in v0.0.50, run it to generate the manifest from source so `contracts.tools` can't drift; otherwise add a structural test asserting `contracts.tools` ⊇ the registered tool names.
  - **DISPROVEN leads (do NOT re-pursue)**: package-name↔manifest-id alignment (weixin also mismatches yet loads); `load.paths` clearing; copying into `extensions/` or `npm/node_modules/` + repointing `installs.json`. All were symptoms of the missing cold-metadata contract, not the cause.
  - **Verify independently of Facet A**: the manifest fix can be tested against the already-running loopback+auth-none gateway — no token needed — so do Facet B first.

  **Facet A — bake a TOKEN, not `auth=none` (2026-05-30 refinement)**: `gateway.auth.mode=none` in config does NOT satisfy the bind=auto guard — `openclaw gateway run --port 18789` (nemoclaw's supervised command) still refuses. `auth=none` only works with explicit `--bind loopback`. Since the dashboard/TUI need bind=auto port-forward, Phase 3 should bake `gateway.auth.mode=token` + a persisted `gateway.auth.token` (INV-P003-clean: token via config file at build, never on argv) and ensure clients use it. Loopback-only (ask.sh) can fall back to `--bind loopback --auth none`.

These two facets fold into Step 3.2 GREEN alongside the credential registration. The existing Phase 3 plan below (credential hand-off + Step 7b deletion) still applies, but is necessary-not-sufficient on its own.

## Scope Boundaries

- **In scope**: removal of `scripts/onboard-sandbox.sh` Step 7b; addition of NemoClaw credential registration; **gateway bind/auth config bake (Facet A)**; **plugin tool-surfacing fix (Facet B)**; verification of gateway health + INV-P003.
- **Out of scope**: cleaning up the rest of `onboard-sandbox.sh` (that's Phase 4); `sandbox-up.sh` recovery delegation (Phase 4); UX docs (Phase 6).

## Invariants Enforced in This Phase

- **INV-P003** Secrets Pass via stdin or env, Never via argv — re-verified by the existing discovery test [test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py). The new credential registration step must read the key from env / stdin and not place it on a command line.
- **INV-V001** Verification Methodology — gateway health verified via HTTP probe, not log-grep.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

**Test cases**:

1. `test_invP003_credential_registration_no_argv_leak` — static analysis of the rewritten `onboard-sandbox.sh`: assert that any line invoking `nemoclaw credentials set` (or equivalent) passes the secret via stdin (`<<<`, `<`, or `echo | nemoclaw ...`) or env, never as a literal `--value=$OPENAI_API_KEY` style flag. Extends the existing discovery test's pattern.
2. `test_gateway_running_after_onboard_without_docker_exec_step` — boot a fresh sandbox using the updated onboard flow; assert `curl -s http://127.0.0.1:18789/healthz` (or whatever NemoClaw's documented health endpoint is) returns 200; assert no `docker exec -d ... gateway run` ever ran (recorded by trace test).
3. `test_gateway_owned_by_nemoclaw_supervisor` — `docker exec <name> ps -ef | grep gateway` shows the gateway, but its parent PID is NOT a detached `docker exec` shell — instead it's the NemoClaw entrypoint or a NemoClaw-supervised init. Verified structurally via process tree inspection.
4. `test_credential_recovery_after_kill` — kill the gateway process inside the container; run `nemoclaw genomeclaw recover`; assert the gateway is back up + responding at the same port. (Validates the credential reloader actually has the key.)
5. `test_phase3_muscle_question_smoke_via_ask_sh` — **end-to-end smoke gate, bypass path**. After the rewritten onboard finishes, run `./scripts/ask.sh --capture "<muscle question>"`. Assert: trace parses; `meta.finalAssistantVisibleText` > 200 chars; ≥1 successful `genomeclaw_*` tool call in trajectory. With `GENOMECLAW_REPLAY_LLM=1`: LLM-judge `faithful=true` AND `understandable=true`.
6. `test_phase3_muscle_question_smoke_via_nemoclaw_path` — **end-to-end smoke gate, NemoClaw-managed path**. Send the muscle question through whichever supervised surface works in 2026.5.18:
   - **Preferred**: `nemoclaw genomeclaw exec openclaw agent --local --json --message "<muscle question>"` (if upstream fixed the multi-line / WebSocket bug).
   - **Fallback**: `docker exec --user sandbox <container> openclaw tui --non-interactive --message "<muscle question>"`.
   - **Last resort**: drive the dashboard via headless browser (Playwright) and capture the chat response.
   Same pass criteria as Test 5. This is the test that proves Phase 3 actually fixed the dashboard / TUI / connect surfaces — not just the ask.sh bypass path.

**Sketch**:

```python
def test_invP003_credential_registration_no_argv_leak():
    script = Path("scripts/onboard-sandbox.sh").read_text()
    # Find every line invoking the credential-set subcommand
    for line in script.splitlines():
        if "nemoclaw credentials set" in line or "nemoclaw secret" in line:
            # Must NOT have $OPENAI_API_KEY or ${OPENAI_API_KEY} as a positional/flag value
            assert not re.search(r"--value[= ]\$\{?OPENAI_API_KEY\}?", line), \
                f"INV-P003: secret leaked to argv at: {line}"

def test_gateway_running_after_onboard_without_docker_exec_step(onboarded_sandbox):
    # The fixture runs scripts/onboard-sandbox.sh; no Step 7b helper called.
    resp = httpx.get("http://127.0.0.1:18789/healthz", timeout=5)
    assert resp.status_code == 200

def test_gateway_owned_by_nemoclaw_supervisor(onboarded_sandbox):
    out = docker_exec(onboarded_sandbox, ["ps", "-eo", "pid,ppid,cmd"])
    gateway_lines = [l for l in out.splitlines() if "openclaw gateway" in l]
    assert gateway_lines, "gateway not running"
    # Parent should be the openclaw supervisor / init, not a detached shell
    for line in gateway_lines:
        ppid = int(line.split()[1])
        assert ppid != 1 or "init" in get_pid_cmd(onboarded_sandbox, 1), \
            f"gateway parent is not nemoclaw-managed: {line}"
```

Run the tests. They fail because:
- (1) the onboard script still has Step 7b's `-e OPENAI_API_KEY=$OPENAI_API_KEY` injection but also doesn't have a `nemoclaw credentials set` line yet.
- (2) without changes, gateway is started by Step 7b, not NemoClaw, so the test depends on Step 7b's behavior.
- (3) ppid currently traces to a detached docker-exec shell, not the supervisor.
- (4) recovery currently fails because credential reloader has no key.

Paste RED output into `work-notes.md`.

### Step 3.2 — GREEN: Minimal Implementation

1. In `scripts/onboard-sandbox.sh`:
   - **Delete Step 7b** entirely.
   - **Add a new credential-registration step** before `nemoclaw onboard`. Pipe the secret via stdin: `printf '%s' "$OPEN_AI_API_KEY" | nemoclaw credentials set openai_api_key --stdin --sandbox genomeclaw` (exact command depends on upstream docs surveyed in Phase 1 Q2).
   - Confirm `nemoclaw onboard` already runs the gateway as part of its normal flow (per upstream docs); if not, add the documented `nemoclaw <name> start-gateway` invocation.
2. Re-run all four tests. Confirm green.
3. Run the existing argv-leak test as a sanity check.

**Files affected**:
- [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh): MODIFY (delete Step 7b, add credential registration)
- `packages/toolkit/tests/integration/test_phase3_gateway_lifecycle.py`: CREATE
- `packages/toolkit/tests/invariants/test_invP003_credential_registration_no_argv_leak.py`: CREATE (or extend the existing INV-P003 test)

### Step 3.3 — REFACTOR

- Move the credential-registration step into a small named helper function inside `onboard-sandbox.sh` (`register_credentials_with_nemoclaw`) so its responsibility is self-documenting.
- Add an inline comment explaining the `--stdin` choice is `INV-P003`-driven, with a `# INV-V001-allow: structural shell pattern, not LLM output` note on the regex check.

---

## Implementation Details

### Edge Cases to Handle

- **NemoClaw credential subcommand syntax**: confirm exact form in Phase 1 audit. Might be `nemoclaw credentials set <name>` or `nemoclaw secret add <name>` or `nemoclaw <sandbox> credential set <name>`. Verify before writing.
- **Credential storage location on disk**: Phase 3 RED audit MUST inspect where NemoClaw writes the credential file. Confirm permissions (mode 0600, owned by the host user). Document in work-notes.
- **Recovery after host restart**: kill the host's NemoClaw daemon (if any), restart, verify credential reloader still has the key.
- **Onboard idempotency**: re-running `scripts/onboard-sandbox.sh` should not fail because the credential is already registered. Either the credential set is idempotent or we add a check-first guard.

### Error Handling

- If `nemoclaw credentials set --stdin` is not supported in 2026.5.18, the next-best option is env: `OPENAI_API_KEY=... nemoclaw credentials set openai_api_key --from-env OPENAI_API_KEY`. Still INV-P003-clean. If neither is supported, escalate.
- If `nemoclaw onboard` doesn't auto-start the gateway, add explicit start step and document.

### Privacy / Egress Notes

- **Credential file audit**: as part of GREEN gating, run:
  ```bash
  find ~/.nemoclaw ~/.openclaw ~/Library/Application\ Support/nemoclaw -name '*credential*' -o -name '*secret*' 2>/dev/null | xargs -I {} ls -la {}
  ```
  Confirm mode 0600 and owned by the host user. If world-readable, raise a privacy issue in work-notes and consider whether to land the change.
- **Log audit**: run `nemoclaw --log-level debug genomeclaw status` and grep the output for any unmasked credential. If found, escalate.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) | MODIFY | Delete Step 7b, add credential registration |
| `packages/toolkit/tests/integration/test_phase3_gateway_lifecycle.py` | CREATE | Tests 2, 3, 4 (gateway up + owned by NemoClaw + recovery) |
| `packages/toolkit/tests/invariants/test_invP003_credential_registration_no_argv_leak.py` | CREATE | Test 1 (extends existing INV-P003 surface) |
| [docs/plans/active/nemoclaw-canonical-integration/work-notes.md](../work-notes.md) | MODIFY | Phase 3 progress + credential storage audit findings |

---

## Verification

```bash
# Build prerequisite from Phase 2
docker buildx build -t genomeclaw-sandbox:latest packages/nemoclaw-plugin/sandbox/

# Clean any prior sandbox to test the fresh-onboard path
nemoclaw genomeclaw destroy --force 2>/dev/null || true

# Run the rewritten onboard
./scripts/onboard-sandbox.sh

# Run Phase 3 tests
uv --project packages/toolkit run pytest \
  packages/toolkit/tests/integration/test_phase3_gateway_lifecycle.py \
  packages/toolkit/tests/invariants/test_invP003_credential_registration_no_argv_leak.py \
  packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py -v

# Manual: confirm gateway endpoint
curl -s http://127.0.0.1:18789/healthz

# Manual: confirm process tree
docker exec --user sandbox $(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1) \
  ps -ef

# End-to-end smoke gate (bypass path)
GENOMECLAW_REPLAY_LLM=1 ./scripts/ask.sh --capture \
  "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."

# End-to-end smoke gate (NemoClaw-managed path — pick the one that works in 2026.5.18)
nemoclaw genomeclaw exec openclaw agent --local --json --message \
  "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet." \
  | tee docs/reports/demo-$(date +%Y-%m-%d)-logs/muscle-question-via-nemoclaw.trace.json
```

---

## Completion Criteria

- [ ] `scripts/onboard-sandbox.sh` Step 7b deleted
- [ ] Credential registration step added; secret travels via stdin or env, not argv
- [ ] Gateway running at 127.0.0.1:18789 after onboard completes
- [ ] Gateway parent process is the NemoClaw supervisor (NOT a detached `docker exec`)
- [ ] All six Phase 3 tests pass (4 structural + 2 muscle-question smokes)
- [ ] Existing `INV-P003` argv-leak test passes
- [ ] `nemoclaw genomeclaw recover` actually restores the gateway after a kill
- [ ] Credential storage file permissions audited (mode 0600)
- [ ] Log audit confirms no plaintext credential leakage
- [ ] Muscle-question smoke via ask.sh: synthesized reply + LLM-judge clean
- [ ] Muscle-question smoke via NemoClaw-managed path: synthesized reply + LLM-judge clean (this is the headline AC of this plan)
- [ ] `work-notes.md` Phase 3 § Test Results contains test output + credential audit findings + both smoke verdicts
- [ ] Phase status updated in `development-plan.md`

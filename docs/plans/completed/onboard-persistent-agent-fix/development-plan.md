# Onboard Persistent Agent Fix — Development Plan

**Status**: Draft
**Created**: 2026-05-24
**Branch**: `feature/onboard-persistent-agent-fix`
**Spec**: [spec.md](spec.md)

---

## Summary

Make `./scripts/onboard-sandbox.sh` produce a working persistent `nemoclaw genomeclaw` sandbox in one run by (1) baking the config that the post-install step currently fails to set, (2) rewriting the auth-profile write to use stdin instead of argv (closing the API-key leak path), and (3) teaching `bin/genomeclaw host doctor` to warn when colima is configured in a way that will silently break the docker-wrapped host service.

## Critical Invariants to Respect

- **INV-P001** Privacy Is the Default Operating Mode — Phase 2's argv-elimination is the structural close-out for the 2026-05-24 API-key-into-log leak. The script will never put the operator's OpenAI key on a command line again.
- **INV-P002** Agent Egress Is a Named, Minimal-Sufficient Boundary — we configure the named egress destination (OpenAI). No new egress destinations introduced. The `auth.profiles.openai_default` + `models.providers.openai.apiKey` shape is consistent with how the live-smoke harness already configures the same provider.
- **INV-D006** DooD-Safe Path Annotation — colima mount coverage is the operator-side prerequisite for the docker-wrapped host service to see the derived dir. Phase 3's doctor check is the detection layer for the failure mode.
- **INV-T001** External-Tool Conventions Captured as Typed Wrappers — `nemoclaw onboard` and `openclaw config set` and `docker exec` are external tools we wrap. Phase 1 + Phase 2 do not add new typed wrappers (the existing shell-script seam is appropriate for these one-off operator commands), but the discovery tests proposed in Phase 2 enforce that the existing wrapping is correct.

## Proposed New Invariants

**NEW INV-P003 — Secrets Pass via stdin or env, Never via argv**

See [spec.md § Proposed New Invariants](spec.md#proposed-new-invariants) for the rule, rationale, and verification approach. Promoted into [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) only after Phase 2's tests are merged and green. Proposed assignment: `INV-P003` (next available `INV-P` number; P001 = privacy default, P002 = agent egress).

## Current State Analysis

The 2026-05-24 demo session ([docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md)) walked the full onboard flow on a fresh `nemoclaw onboard --fresh` and produced empirical evidence for every failure mode this plan addresses. The patched-2026-05-24 shim-Dockerfile fix made the `nemoclaw onboard` step itself succeed; the deployed container then failed three more ways:

1. Gateway refused to start (`Gateway start blocked: existing config is missing gateway.mode`). Root cause: the Dockerfile bakes `tools.web.search.enabled`, `agents.defaults.model`, `agents.defaults.thinkingDefault` — but not `gateway.mode`, not `plugins.allow`, not the plugin's `hostService.baseUrl`. The post-install script tries to set them via `nemoclaw genomeclaw exec` but...
2. `nemoclaw genomeclaw exec` wraps every command in openshell's filesystem-restriction layer, which `EACCES`es on `/opt/genomeclaw` even though the in-container `sandbox` user owns the dir at 755. Confirmed by comparing `mountinfo` (byte-identical) and ownership (uid 998, sandbox, world-readable) between `docker exec --user sandbox` (works) and `nemoclaw genomeclaw exec` (EACCES). The restriction is kernel-level (landlock-ish) and outside our control to disable.
3. The auth-profile-write step's `nemoclaw exec ... python3 -c "import base64; ...base64.b64decode('$PROFILE_B64')..."` invocation crashed when the target directory `/sandbox/.openclaw/agents/genomeclaw/agent/` didn't exist. The Python traceback echoed the full `-c` source string — including the base64 blob — into the captured log file (`docs/reports/demo-2026-05-24-logs/03-onboard-v2.log`). Redacted at write-time, but the leak path is structural.

Additionally, when the script reached step 8 (smoke test → host service), the docker-wrapped `bin/genomeclaw host service` couldn't see the derived dir because the operator's colima had `mounts: []`. The native-uvicorn fallback (Python in-process) worked; the docker-wrapped path didn't.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/nemoclaw-plugin/sandbox/Dockerfile` | Bakes `tools.web.search.enabled`, `tools.web.fetch.enabled`, `agents.defaults.model`, `agents.defaults.thinkingDefault`. Does NOT bake `gateway.mode`, `plugins.allow`, `hostService.baseUrl`, `hostService.timeoutMs`. Does NOT set `ENV HOME=/sandbox`. | Phase 1: Add `ENV HOME=/sandbox`. Add `RUN openclaw config set gateway.mode local && openclaw config set plugins.allow '["genomeclaw"]' && openclaw config set plugins.entries.genomeclaw.config.hostService.baseUrl "http://host.openshell.internal:${GENOMECLAW_HOST_PORT}" && openclaw config set plugins.entries.genomeclaw.config.hostService.timeoutMs 30000`. Add `RUN openclaw config set models.providers.openai.apiKey --ref-provider default --ref-source env --ref-id OPENAI_API_KEY`. |
| `scripts/onboard-sandbox.sh` | Post-install steps use `nemoclaw genomeclaw exec --no-tty -- bash -c "openclaw config set ..."` (broken — EACCES). Auth-profile write uses `nemoclaw exec ... python3 -c "...$PROFILE_B64..."` (leaks key on traceback). models.json inference.local routing uses similar argv-interpolation pattern. | Phase 2: Delete the post-install `openclaw config set` exec calls (now baked). Rewrite auth-profile write to `docker exec -i --user sandbox <CID> bash -c 'mkdir -p ... && cat > .../auth-profiles.json' <<< "$json"` reading JSON from stdin. Same for the models.json inference.local-routing patch. Add an explicit gateway-start step `docker exec -d -e HOME=/sandbox -e OPENAI_API_KEY="$OPEN_AI_API_KEY" --user sandbox <CID> bash -c 'openclaw gateway run > /tmp/gateway.log 2>&1'`. Keep the smoke test via `nemoclaw genomeclaw exec` (that path works for `openclaw agent` because the agent talks to the already-running gateway over WebSocket, no `/opt/genomeclaw` scan). |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | `host doctor` checks four canonical subdirs, surfaces `setup_completed`, reports colima status, flags stale colima mounts. Does NOT check whether colima's `mounts:` list covers `$GENOMECLAW_DERIVED_DIR`. | Phase 3: Add a `_check_colima_mounts_cover_derived` function that reads `~/.colima/default/colima.yaml`, parses the `mounts:` block (regex or simple line-walker), and emits a warning-level finding if (a) `mounts: []` or no `mounts:` block AND (b) `$GENOMECLAW_DERIVED_DIR` is not on the system disk (i.e. an external drive). |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py` | Phase 1 RED: AC3 + AC4 — load the freshly-built sandbox image's `/sandbox/.openclaw/openclaw.json` + `Config.Env`; assert gateway.mode/plugins.allow/hostService.baseUrl/timeoutMs/apiKey-ref/ENV HOME are all present with the expected shape. Follows the pattern from existing `test_invP001_sandbox_web_egress_contract.py`. |
| `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` | Phase 2 RED: AC5 — discovery test that walks `scripts/`, greps every `.sh` file for the rendered-shape argv-interpolation patterns (`python3 -c.*\$.*B64`, `--key.*\$.*KEY`, `bash -c.*\$.*TOKEN`, `bash -c.*\$.*SECRET`), and asserts zero matches. New invariant test for the proposed INV-P003. |
| `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py` | Phase 3 RED: AC6 — three parametrized cases (empty mounts / populated-and-covers-derived / populated-but-doesn't-cover-derived); monkeypatch `~/.colima/default/colima.yaml`; assert `host doctor` exit code + emitted JSON `findings` array contains the expected warning entry (and only when appropriate). |
| `docs/plans/active/onboard-persistent-agent-fix/phases/phase-{1,2,3}.md` | Per-phase TDD scaffolds. |
| `docs/plans/active/onboard-persistent-agent-fix/work-notes.md` | Append-only session log. |

## Solution Design

The script today is a sequence of openclaw-config mutations issued through `nemoclaw exec`. The fix flips the configuration-vs-credential split: **configuration that's constant across operators bakes into the image at Phase 1; credentials that vary per-operator land via stdin at Phase 2**. The leftover `nemoclaw exec` paths (the smoke test) only touch the already-running gateway, not the plugin source dir, so they don't hit the openshell EACCES.

```text
Before this plan:
  Dockerfile bakes  ┌── tools.web.search.enabled
                    │── tools.web.fetch.enabled
                    │── agents.defaults.model
                    └── agents.defaults.thinkingDefault

  Onboard script    ┌── nemoclaw exec ... openclaw config set gateway.mode local           [EACCES]
  (post-install)    │── nemoclaw exec ... openclaw config set plugins.allow '[genomeclaw]' [EACCES]
                    │── nemoclaw exec ... openclaw config set plugins.entries.*.baseUrl    [EACCES]
                    │── nemoclaw exec ... openclaw config set plugins.entries.*.timeoutMs  [EACCES]
                    │── nemoclaw exec ... python3 -c "...base64.b64decode('$PROFILE_B64')" [LEAKS KEY ON TB]
                    │── nemoclaw exec ... python3 -c "...models.json inference.local..."   [argv-shaped]
                    └── nemoclaw exec ... openclaw agent (smoke test)                       [works]

After this plan:
  Dockerfile bakes  ┌── tools.web.search.enabled
                    │── tools.web.fetch.enabled
                    │── agents.defaults.model
                    │── agents.defaults.thinkingDefault
                    │── gateway.mode = local                              [NEW — Phase 1]
                    │── plugins.allow = [genomeclaw]                      [NEW — Phase 1]
                    │── plugins.entries.genomeclaw.config.*.baseUrl       [NEW — Phase 1, ${GENOMECLAW_HOST_PORT}-templated]
                    │── plugins.entries.genomeclaw.config.*.timeoutMs     [NEW — Phase 1]
                    │── models.providers.openai.apiKey = ref(env:OPENAI_API_KEY)  [NEW — Phase 1]
                    └── ENV HOME=/sandbox                                  [NEW — Phase 1]

  Onboard script    ┌── docker exec -i ... cat > .../auth-profiles.json (stdin)   [NEW — Phase 2]
  (post-install)    │── docker exec -i ... cat > .../models.json (stdin)          [NEW — Phase 2]
                    │── docker exec -d -e OPENAI_API_KEY=... openclaw gateway run [NEW — Phase 2]
                    └── nemoclaw exec ... openclaw agent (smoke test)             [unchanged — works]

  bin/genomeclaw host doctor                                                       [NEW — Phase 3]
                    └── _check_colima_mounts_cover_derived → warning finding if mounts:[] AND derived on external drive
```

### Key Design Decisions

1. **Bake `gateway.mode=local` into the Dockerfile rather than have the onboard script set it post-install.** The post-install path is structurally broken under nemoclaw's exec wrapper; the bake-time path is a known-good place where the Dockerfile already sets four similar config keys. The trade-off is that `gateway.mode` becomes harder to override post-install — but the operator can still `docker exec -e HOME=/sandbox --user sandbox <CID> openclaw config set gateway.mode <other>` if they need to. Local is the only meaningful value for GenomeClaw's single-user-on-own-hardware shape anyway.

2. **Reference the OpenAI API key via `--ref-source env --ref-id OPENAI_API_KEY`, not by writing the value into a config file.** The live-smoke harness already uses this pattern; promoting it to the persistent path means the key only needs to be present in env at gateway-start time, which the onboard script can do via `docker exec -e OPENAI_API_KEY=...` (env-passed, not argv-passed). The `auth-profiles.json` file is still written (for the agent's own bookkeeping), but its `key` field carries the literal key only because the upstream `nemoclaw inference set --provider openai-api` path is broken on local Docker. Once that upstream bug is fixed, `auth-profiles.json` can be removed entirely.

3. **Auth-profile write uses `docker exec -i ... cat > ... <<EOF`, not `nemoclaw exec ... python3 -c "...base64..."`.** Two reasons. First, the JSON content reaches the container's filesystem via stdin and never appears in any process's argv, so a crash inside the container or a `set -x` upstream cannot echo it to a log. Second, `docker exec --user sandbox` works (no openshell exec wrapper, no EACCES), so the write step is reliable.

4. **The host-doctor colima-mounts check is a warning, not an error.** The operator's chosen workflow (docker-wrapped host service vs `GENOMECLAW_NATIVE=1` uvicorn) is a legitimate choice — some operators run the host service natively on purpose. The doctor's job is to surface the inconsistency, not to fail the run. Warning-level keeps the doctor's exit code at 0 if it's the only finding, matching the existing `flags stale colima mounts` behavior.

### Schema / Provenance Impact

- None. No derived stores touched.

### Privacy & Egress Impact

- New network egress points: none. The OpenAI provider was already named in user config; we're just changing how the key reaches the gateway process.
- New secret-handling surfaces: none introduced. **One existing secret-handling surface tightened**: `scripts/onboard-sandbox.sh` no longer puts the OpenAI API key on a command-line argv. Phase 2's stdin-based write closes the structural leak path that produced the 2026-05-24 log leak.
- Redaction added: n/a (the fix is at the source — secrets that never reach a log can't need redaction).

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Bake gateway.mode + plugins.allow + hostService.baseUrl + hostService.timeoutMs + openai.apiKey-via-env-ref + ENV HOME into the sandbox Dockerfile | Baked-image-config invariant gate (AC3 + AC4) | 5–6 |
| 2 | Rewrite `scripts/onboard-sandbox.sh` to delete the now-redundant nemoclaw-exec config calls, write auth-profile + models.json via `docker exec -i ... cat > ...` (stdin), add explicit gateway-start, keep smoke-test path | Discovery test for argv-interpolated secrets (AC5), end-to-end smoke test against a real onboard (AC1+AC2+AC7) | 3–4 (+ 1 end-to-end live integration test) |
| 3 | Add `_check_colima_mounts_cover_derived` to `bin/genomeclaw host doctor`; emit warning-level finding when colima mounts don't cover the derived dir on an external drive | Parametrized doctor-output test across three colima.yaml shapes (AC6) | 3–4 |

## Phase 1: Bake the Persistent-Path Config

**Goal**: A freshly built `genomeclaw/sandbox:port-${GENOMECLAW_HOST_PORT}` image starts a working gateway with the GenomeClaw plugin loaded on first `openclaw gateway run`, without any post-install `openclaw config set` having to succeed first.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. Modified `packages/nemoclaw-plugin/sandbox/Dockerfile` with the five new config bakes + `ENV HOME=/sandbox`.
2. New test file `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py` covering AC3 + AC4.

### Invariants Enforced Here
- **INV-P001** Privacy Default — the baked-config gate is the same shape as the existing `test_invP001_sandbox_web_egress_contract.py`; this extension asserts the persistent-path config bake-up is correct.

### Success Criteria
- [ ] All 5–6 new tests pass against a freshly built image (RED → GREEN → REFACTOR visible).
- [ ] Static checks pass (mypy strict on the new test file, ruff clean).
- [ ] The existing `test_invP001_sandbox_web_egress_contract.py` still passes (no regression).
- [ ] Manually verified: `docker run --rm --entrypoint cat genomeclaw/sandbox:port-8645 /sandbox/.openclaw/openclaw.json | jq '.gateway.mode, .plugins.allow, .plugins.entries.genomeclaw.config.hostService.baseUrl'` returns `"local"`, `["genomeclaw"]`, `"http://host.openshell.internal:8645"`.

## Phase 2: Onboard Script — stdin for secrets, gateway-start, delete dead config calls

**Goal**: `./scripts/onboard-sandbox.sh` succeeds end-to-end on a fresh host without the operator's OpenAI API key ever appearing on a command-line argv.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. Rewritten `scripts/onboard-sandbox.sh` per the design above.
2. New test file `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` covering AC5 (proposes INV-P003 — promoted into `INVARIANTS.md` after this phase is green).
3. New integration test file (gated on `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE` env vars, `@pytest.mark.live_onboard`) covering AC1 + AC2 + AC7 — runs the script against a throwaway `nemoclaw onboard --fresh --name genomeclaw-test`, asserts `nemoclaw list` shape, runs the smoke-test agent call, and validates the auth-profile JSON in the deployed container.

### Invariants Enforced Here
- **INV-P001** Privacy Default — the script no longer puts a credential on argv.
- **NEW INV-P003** Secrets via stdin/env Never argv — promoted into `INVARIANTS.md` once Phase 2's tests are green.

### Success Criteria
- [ ] AC5 discovery test passes (zero argv-interpolated secret patterns in `scripts/`).
- [ ] AC1 + AC2 + AC7 live-onboard test passes on the project owner's host (manual gate; the test is `live_onboard`-marked so CI doesn't try to run it without the env vars).
- [ ] No regression in any existing onboarding tests.
- [ ] `nemoclaw list` after a fresh onboard run shows `genomeclaw` with `(healthy)` status.

## Phase 3: `host doctor` colima-mounts coverage check

**Goal**: An operator whose colima is misconfigured for the docker-wrapped host service gets a clear actionable warning from `bin/genomeclaw host doctor` instead of a silent `no_active_run` from the agent.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. New function `_check_colima_mounts_cover_derived(colima_yaml_path, derived_dir, system_disk_path)` in `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py`.
2. Wire the new check into the existing `host doctor` finding pipeline; emit `severity: warning` JSON when triggered.
3. New test file `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py` covering AC6 (three parametrized cases).

### Invariants Enforced Here
- **INV-D006** DooD-Safe Path Annotation — the colima mounts cover the operator's chosen derived path is a prerequisite for the docker-wrapped path-resolution layer. The doctor check is the detection point.

### Success Criteria
- [ ] All three parametrized cases pass.
- [ ] `bin/genomeclaw host doctor` continues to exit 0 in the no-issues case (the new warning is non-blocking when it's the only finding, matching the stale-mount precedent).
- [ ] Doctor warning text contains both fixes ("re-run `host setup`" + `GENOMECLAW_NATIVE=1`).

---

## Testing Strategy

### Unit Tests
- `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py` — Phase 1; reads built image's openclaw.json + env; asserts shape.
- `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` — Phase 2; greps `scripts/` for forbidden patterns.
- Per-function unit tests on `_check_colima_mounts_cover_derived` — Phase 3; cases for missing-yaml / empty-mounts / present-not-covering / present-and-covering.

### Integration Tests
- `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py` — Phase 3; parametrized end-to-end via the `host doctor` CLI surface.
- `packages/toolkit/tests/integration/test_live_onboard_persistent_agent.py` (new, `@pytest.mark.live_onboard`) — Phase 2; runs the script against a throwaway `genomeclaw-test` sandbox name, asserts `nemoclaw list` and a one-shot agent call. Skipped in CI without `OPENAI_API_KEY + GENOMECLAW_SANDBOX_IMAGE`.

### Provenance Tests
- n/a — no derived store touched.

### Determinism Tests
- n/a — the Dockerfile's bake-time config is the same on every build (Phase 1's image hash is determined by inputs + Dockerfile content, already covered by existing image-build determinism).

### Privacy-Default Tests
- AC5's discovery test IS the privacy-default test for this plan. INV-P003 promotion adds it to the canonical privacy-default test suite.

### Evidence-Binding Tests
- n/a — no findings or interpretations.

### Report Rendering Tests
- n/a — no user-facing report.

### Invariant Tests
- See above — `test_invP001_sandbox_baked_config_persistent_path.py`, `test_invP003_onboard_script_no_secrets_in_argv.py`.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — promote `INV-P003` (after Phase 2 tests green). Bump Version + Last Updated.
- [ ] [README.md](../../../../README.md) — update the "Sandbox setup — the GenomeClaw NemoClaw agent" section to reflect the new onboarding flow:
  - Step 5 ("Sets `plugins.entries.genomeclaw.config.hostService.baseUrl`") is **deleted** — Phase 1 bakes it. Renumber subsequent steps.
  - Step 6 ("Writes the agent's `auth-profiles.json`") — **fix the load-bearing inaccuracy**. The current text says *"The key is base64-encoded on the host (never lands in argv or process list) and decoded inside the sandbox"* — this was empirically false as of 2026-05-24 (the base64 blob was passed as a `python3 -c` argv, leaked into a log via Python traceback). Phase 2 makes the claim true by switching to `docker exec -i ... cat > ... <<EOF` (stdin). New wording: *"The JSON payload (including the key) is piped via `docker exec -i` stdin into the container's filesystem — never lands in argv, never appears in `ps`, never echoes in tracebacks (Python's default traceback prints `-c` source strings, which is how the pre-2026-05-24 base64-argv trick leaked the key into a committed log)."*
  - Step 7 ("Points the agent's `openai` provider at `inference.local`") — keep the description, but note the mechanism changed to `docker exec --user sandbox -e HOME=/sandbox` (no longer `nemoclaw exec`). Add: a new step 7b ("Starts the openclaw gateway with `OPENAI_API_KEY` in its env, not argv").
  - Step 8 (smoke test) — wording unchanged; the smoke test still works through `nemoclaw genomeclaw exec` because that path only talks to the already-running gateway over WebSocket.
  - Troubleshooting section: add a new entry **"Gateway start blocked: existing config is missing `gateway.mode`"** pointing at Phase 1's bake (operator hits this only if they're on a pre-Phase-1 image build). Also add **"colima mounts: [] — agent reports `no_active_run`"** pointing at the new Phase-3 `host doctor` check.
  - The "Where state lives" section (line 446 today, currently says *"`auth-profiles.json` (OpenAI credential — written by `scripts/onboard-sandbox.sh` step 6)"*) — adjust the step number after renumbering.
- [ ] `bin/genomeclaw host doctor`'s help text — document the new colima-mounts coverage check.
- [ ] `.claude/agents/privacy-safety-reviewer.md` — add `INV-P003` to the agent's invariant coverage list.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-25 | 2026-05-25 | Dockerfile baked: ENV HOME=/sandbox + gateway.mode/plugins.allow/hostService config + openai provider via batch-file + apiKey env-ref. 6/6 invariant tests green. |
| Phase 2 | Complete | 2026-05-25 | 2026-05-25 | Script rewritten: stdin auth-profile + docker exec config + explicit gateway-start with OPENAI_API_KEY via env. INV-P003 promoted into INVARIANTS.md (v1.17). 3/3 invariant tests green. README + privacy-safety-reviewer updated. Live-onboard integration test deferred — operator runs script end-to-end as the manual gate. |
| Phase 3 | Complete | 2026-05-25 | 2026-05-25 | `_collect_colima_mounts_cover_derived` added to doctor; warning surfaced as report section. 6/6 tests green; 51/51 pre-existing doctor tests still green. README updated. |

---

## Open Risks & Follow-ups

- **Risk**: `nemoclaw onboard` upstream may change its build-context behavior or its exec-wrapper, invalidating either the shim-Dockerfile workaround or the `docker exec` bypass. Mitigation: the live-onboard test will fail loudly if upstream behavior shifts; revisit then.
- **Risk**: The openshell exec-wrapper EACCES on `/opt/genomeclaw` is technically a behavior of `nemoclaw genomeclaw exec` we don't control. If upstream tightens the restriction further (e.g., blocks `docker exec` from outside the sandbox boundary too), Phase 2's workaround would also break. Mitigation: documented in Phase 2's plan; if it happens, the fix is to move all post-install config into the image bake (Phase 1 already does most of it; auth-profile would need to be added as a build-time `ARG`-injected file, which has its own privacy concerns — defer until forced).
- **Follow-up plan**: `genomeclaw_pgs_compute` ack-without-row bug. Surfaced in 2026-05-24 demo against PGS000014 (Q3) and PGS000334 (Q5). Belongs in a new plan against the host service's PRS-task lifecycle.
- **Follow-up plan**: `genomeclaw_gene` argument-serialization bug. Surfaced in 2026-05-24 demo against CYP1A2/ADORA2A/AHR/POR/BRCA1/BRCA2/TP53 panels. Belongs in a new plan against the plugin's TypeBox parameter shapes.
- **Follow-up (out of scope here, worth a tracking note)**: make `bin/genomeclaw host service` auto-fall-back to native uvicorn when colima mounts don't cover the derived dir. The Phase 3 doctor warning is the operator-visible stopgap; the automatic fallback would close the failure mode entirely but requires reworking the shim's path-resolution logic.

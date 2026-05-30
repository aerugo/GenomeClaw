# NemoClaw Canonical Integration — Development Plan

**Status**: Implementation complete + committed (Phases 1–4 + Phase 5 surface gate). Closeout follow-ups deferred on external blockers (v0.4 data rebuild needs a pipeline host; doc-file edits + INV-D011 registry entry blocked by unrelated in-flight WIP in those files). See **Deferred Follow-ups** below. Kept in `active/` until the deferred closeout lands.
**Created**: 2026-05-29
**Completed (implementation)**: 2026-05-30
**Branch**: `main` (working from `main` per repo convention)
**Commits**: `0403859` (Phase 2 + 3B + 3A1), `8e9090a` (3A2), `226e3b9` (Phase 4), `c7d7931` (Phase 5 surface gate + A1 auth.mode=none)
**Spec**: [spec.md](spec.md)

---

## Summary

Move the GenomeClaw plugin from `/opt/genomeclaw/` (Landlock-blocked) to `/sandbox/.openclaw-data/extensions/genomeclaw/` (the NemoClaw-canonical writable plugin tree), pin the sandbox base image by SHA to eliminate version skew with the host CLI, and hand the gateway lifecycle + `OPENAI_API_KEY` storage back to NemoClaw's credential system. End state: dashboard, `nemoclaw connect`, and `openclaw tui` all work; `scripts/ask.sh` continues to work as the scripted-CI path; no `INV-P003` regression.

## Critical Invariants to Respect

Reference IDs from [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md).

- **INV-P003** Secrets Pass via stdin or env, Never via argv — the Phase 3 credential hand-off MUST route `OPENAI_API_KEY` through NemoClaw's credential storage (stdin / env at process boot), not via `nemoclaw <flag>=$OPENAI_API_KEY` on a command line. The argv-leak discovery test at [test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py) is the structural guard; it must continue to pass after the onboard script is rewritten.
- **INV-P001** Privacy Default — unchanged. No new egress destinations; only the plumbing between host and sandbox changes. Phase 5 re-runs the privacy-default tests to confirm.
- **INV-A005 v1.23** Reply Synthesis Over Tool Data — must continue to pass. The replay-test fixtures + LLM-judge harness target the *agent's reply behavior*; they are agnostic to the install path of the plugin. Phase 5 re-runs the full replay suite after the path migration to confirm.
- **INV-A006** No Phrase Enumeration in Output Gates — unchanged. This plan introduces no new agent-output gates.
- **INV-V001** Verification Methodology — applies to *this plan's* tests. Phase 1 and Phase 5 use structural inspection (file-exists checks, `docker inspect`, `openclaw plugins list`) rather than substring-grepping log output.
- **INV-D006** + **INV-D007** DooD Discipline — re-verify against the new plugin path. The plugin doesn't spawn DooD siblings, but Phase 5 includes a re-run of the relevant integration tests as part of GREEN gating.

## Proposed New Invariants

- **NEW `INV-D011` (proposed)** *Plugin Install Path Follows NemoClaw's Canonical Pattern*: any plugin baked into a GenomeClaw sandbox image MUST live under `/sandbox/.openclaw-data/extensions/<plugin-id>/` (or the upstream-documented equivalent inside the OpenShell Landlock baseline). Plugins MUST NOT live under `/opt/`, `/usr/local/lib/`, or any other path that the sandbox runtime cannot read. **Promotion deferred to end of Phase 5** — promote if Phase 1–3 validate the canonical path on first try; defer if upstream changes the convention.

## Current State Analysis

Three load-bearing problems caused the dashboard / connect / TUI breakage tonight (2026-05-29). The spec covers them in detail; the development-plan summarizes:

1. **Plugin at `/opt/genomeclaw/`**: outside the OpenShell Landlock baseline → `EACCES` from any process started via the sandbox runtime (i.e. all NemoClaw-managed surfaces).
2. **Sandbox base image cached at `:latest = OpenClaw 2026.4.24`** while the host CLI is `nemoclaw 2026.5.18`. The version skew produces the `--port 18790` mismatch and the `Run: nemoclaw genomeclaw rebuild` hint.
3. **Gateway lifecycle owned by `docker exec -d`** in `scripts/onboard-sandbox.sh` Step 7b, outside NemoClaw's supervisor → credential reloader has no key → `nemoclaw recover` can't restart it.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) | Bakes plugin at `/opt/genomeclaw/`; uses `:latest` tag for base image | Build under `/sandbox/.openclaw-data/extensions/genomeclaw/`; pin base by SHA |
| [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) | Step 7b launches gateway via `docker exec -d`; Steps 6/8 layer in custom checks | Delete Step 7b; let `nemoclaw onboard` own gateway start; rewrite Step 8 smoke to verify via gateway HTTP probe |
| [scripts/sandbox-up.sh](../../../../scripts/sandbox-up.sh) | Restarts gateway directly via `docker exec` when missing | Delegate to `nemoclaw <name> recover`; keep docker-exec restart as a final fallback only |
| [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml) | Only `network_policies` | Audit; add `filesystem_policy` only if the canonical path needs explicit allowance |
| [README.md](../../../../README.md) § Sandbox setup, § Troubleshooting | Documents `docker exec` as the working path; warns `nemoclaw exec` is broken | Document dashboard / connect / TUI as the primary paths; `scripts/ask.sh` as scripted alternative |
| [CLAUDE.md](../../../../CLAUDE.md) § Running the Agent Locally | Same workaround notes as README | Same canonical-path update |
| [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) | References docker-exec workaround in agent test guidance | Update agent guidance to reflect canonical paths |

### Files to Create

| File | Purpose |
|------|---------|
| `docs/plans/active/nemoclaw-canonical-integration/phases/phase-{1..6}.md` | Phase scaffolds (this file's siblings) |
| Possibly: `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` | Discovery test for the proposed `INV-D011` (only if Phase 5 promotes it) |

## Solution Design

```text
                          Host
                          ├── nemoclaw 2026.5.18  ── credential store ── OPENAI_API_KEY
                          ├── nemoclaw onboard ─── owns gateway lifecycle ───┐
                          ├── nemoclaw connect ────── docker exec ───┐      │
                          └── nemoclaw dashboard-url ───── browser ──┤      │
                                                                    │      │
                          Sandbox container (genomeclaw)             │      │
                          /sandbox/.openclaw-data/extensions/        │      │
                            └── genomeclaw/                          │      │
                                ├── package.json                     │      │
                                ├── dist/index.js                    │      │
                                └── policy-preset.yaml               │      │
                          /sandbox/.openclaw/extensions/             │      │
                            └── genomeclaw → ../.openclaw-data/...   │      │
                                                                     │      │
                          openclaw gateway (port 18789) ◄────────────┴──────┘
                          openclaw tui ─── ws://127.0.0.1:18789
                          openclaw agent --local --json ─── scripts/ask.sh (bypass path)
```

### Key Design Decisions

1. **Canonical install path is `/sandbox/.openclaw-data/extensions/genomeclaw/`**. NemoClaw's install docs specify this is where writable agent state lives, and it sits inside `/sandbox` which IS in the Landlock baseline. Phase 1 verifies whether the docs want the symlink at `/sandbox/.openclaw/extensions/genomeclaw/` set up at build time or whether `openclaw plugins install --link` does it.
2. **Base image pinned by SHA, not tag**. `ghcr.io/nvidia/nemoclaw/sandbox-base@sha256:<digest>`. The SHA must correspond to the same `openclaw` version as the host `nemoclaw` CLI. Documented bump cadence: every time the host nemoclaw is upgraded, re-run a small image probe to confirm the cached `:latest` matches before pinning. Pin maintenance lives in a note inside the Dockerfile + a README troubleshooting section.
3. **NemoClaw owns the gateway lifecycle**. Drop `scripts/onboard-sandbox.sh` Step 7b entirely. The OpenAI key is registered via `nemoclaw credentials set` (or equivalent — Phase 3 RED confirms the exact subcommand from upstream docs) and NemoClaw's credential reloader passes it into the gateway env on each (re)start.
4. **`scripts/ask.sh` stays**. Useful for one-shot CI / scripted questions regardless of dashboard state. It will be slightly cleaned up to drop the `OPENAI_API_KEY` env injection once NemoClaw is the credential owner, but the underlying `docker exec openclaw agent --local --json` path is preserved.
5. **`scripts/sandbox-up.sh` keeps its identity as the recovery wrapper**, but delegates to `nemoclaw <name> recover` instead of restarting the gateway directly. If `nemoclaw recover` itself proves unreliable in 2026.5.18, the script retains a final `docker exec` fallback gated by a flag so the user explicitly opts in.

### Schema / Provenance Impact

- **None.** Pure operational plumbing change. No derived stores touched. No schema bumps.

### Privacy & Egress Impact

- **No new egress destinations.** Same: NemoClaw → OpenAI for the agent.
- **Credential storage surface changes**: `OPENAI_API_KEY` moves from `docker exec -e` injection (held in shell env, never persisted by us) → NemoClaw's credential store on the host. Phase 3 RED MUST verify: where on disk does NemoClaw store the key? Is the file readable only by the host user? Is the key logged anywhere? `nemoclaw credentials show` masking behavior?
- **Redaction**: n/a. The plugin's data redaction (minimal-sufficient evidence per `INV-P002`) is unchanged.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Audit upstream docs + plugin path migration target | Structural: where does upstream put plugins; is `openclaw plugins install` needed; what does `policy-preset.yaml` need; file/symlink expectations | 1–2 audit-style tests (file presence + parse) |
| 2 | Dockerfile rewrite to canonical path + base-image SHA pin | Build-time: image builds, plugin tree lands at canonical path; `openclaw plugins list` shows `genomeclaw` after container start | 2–3 image / container tests |
| 3 | Hand gateway lifecycle + `OPENAI_API_KEY` to NemoClaw | Onboard succeeds via `nemoclaw onboard`; gateway runs at port 18789 owned by NemoClaw; `INV-P003` argv-leak test still passes | 2 tests + re-run INV-P003 |
| 4 | Simplify `onboard-sandbox.sh` + update `sandbox-up.sh` | Script-shape: Step 7b is gone; `sandbox-up.sh` delegates to `nemoclaw recover`; recovery path actually recovers | 2–3 script tests |
| 5 | Verification gate: dashboard / connect / TUI work; all existing tests green | Integration: dashboard 200s; TUI shows `genomeclaw_*` tools; full replay suite + INV-A005/A006/V001 pass | Re-runs existing suite; ~1 new connectivity test |
| 6 | Documentation cleanup + (optional) `INV-D011` promotion | Docs: README, CLAUDE.md, test-engineer agent. Invariant promotion if Phase 1 path discipline held. | 1 discovery test if `INV-D011` promotes |

## Phase 1: Upstream Docs Audit + Path Target Confirmation

**Goal**: Confirm the exact target path, the role of `openclaw plugins install`, and what (if anything) needs to be added to `policy-preset.yaml` for filesystem access. Resolve open questions Q1 and Q2 from the spec.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. Decision recorded in `work-notes.md`: target plugin path, install vs auto-discovery, policy delta.
2. (Optional) Audit test that asserts the chosen target path matches what NemoClaw's `openclaw plugins list` reports after a probe container start.

### Invariants Enforced Here
- **INV-V001**: structural inspection (`docker exec ... openclaw plugins list`) drives the decision; no log-grep enumeration.

### Success Criteria
- [ ] Target path documented + justified
- [ ] Open questions Q1, Q2 resolved or escalated
- [ ] Audit test (if any) is green

## Phase 2: Dockerfile Rewrite + Base-Image SHA Pin

**Goal**: Rewrite [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) so the plugin lands at the canonical path and the base image is pinned by SHA. Confirm `openclaw plugins list` shows `genomeclaw` after a clean container start.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. Updated Dockerfile.
2. SHA pin recorded in Dockerfile comments + README troubleshooting.
3. Build + container-start test.

### Invariants Enforced Here
- **NEW INV-D011 (provisional)**: enforced structurally — a build-time check (or post-build container probe) confirms `/sandbox/.openclaw-data/extensions/genomeclaw/package.json` exists and `/opt/genomeclaw/` does not.

### Success Criteria
- [ ] Dockerfile builds cleanly against the pinned SHA
- [ ] Plugin tree is at the canonical path
- [ ] `/opt/genomeclaw/` absent
- [ ] `openclaw plugins list` shows `genomeclaw` from inside the container

## Phase 3: Gateway Lifecycle + Credential System Hand-Off

**Goal**: Replace `scripts/onboard-sandbox.sh` Step 7b with a NemoClaw-native credential registration + onboard. The gateway lifecycle is owned by NemoClaw after this phase. `INV-P003` argv-leak test passes; the key is not visible in `ps -ef`, container logs, or `nemoclaw` CLI output.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. Updated `scripts/onboard-sandbox.sh` (with Step 7b deleted, credential registration added).
2. Re-run of `test_invP003_onboard_script_no_secrets_in_argv.py` showing green.
3. Test: gateway responds at `http://127.0.0.1:18789/healthz` (or equivalent) after onboard completes without any manual gateway start.

### Invariants Enforced Here
- **INV-P003**: re-verified by the existing discovery test.
- **INV-V001**: gateway health check uses HTTP probe (structural), not log-grep.

### Success Criteria
- [ ] `nemoclaw onboard` completes without manual gateway-start helper
- [ ] Gateway is up on the expected port owned by NemoClaw's supervisor
- [ ] `INV-P003` argv-leak test passes
- [ ] Key is not visible in process list, container logs, or `nemoclaw credentials show` plaintext

## Phase 4: Simplify Onboard Script + Recovery Wrapper

**Goal**: Strip `scripts/onboard-sandbox.sh` of the workaround layers no longer needed. Update `scripts/sandbox-up.sh` to delegate to `nemoclaw <name> recover`. Decide based on Phase 3 results whether `sandbox-up.sh` stays or merges into `onboard-sandbox.sh`.
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables
1. Updated `scripts/onboard-sandbox.sh` (smoke step rewritten).
2. Updated `scripts/sandbox-up.sh` (delegates to `nemoclaw recover`).
3. Recovery integration test: kill gateway → `sandbox-up.sh` recovers it via NemoClaw.

### Invariants Enforced Here
- **INV-V001**: recovery success verified by HTTP probe + process inspection; no log-grep.

### Success Criteria
- [ ] Scripts are leaner; no `docker exec -d openclaw gateway run` anywhere
- [ ] Recovery test green

## Phase 5: Verification Gate

**Goal**: End-to-end verification that all three surfaces work: dashboard browser UI, `nemoclaw connect`, `openclaw tui`. Full existing test suite passes — especially the replay suite from `agent-synthesis-over-rich-tool-data`, `INV-A005/A006/V001`, and the DooD discipline tests.
**Detailed Plan**: [phases/phase-5.md](phases/phase-5.md)

### Deliverables
1. Test or documented manual gate: dashboard URL returns 200, chat UI shows the genomeclaw agent.
2. Test or documented manual gate: `nemoclaw connect → openclaw tui` shows `genomeclaw_*` tools in the catalog.
3. Full replay suite green.
4. `scripts/ask.sh` smoke test green with the muscle question from prior session.

### Invariants Enforced Here
- **All previously-enforced invariants re-verified**: INV-A005, INV-A006, INV-V001, INV-P003, INV-P001, INV-D006/D007.

### Success Criteria
- [ ] Dashboard works
- [ ] TUI works
- [ ] `scripts/ask.sh` works
- [ ] Full test suite green (no regressions)

## Phase 6: Documentation Cleanup + Optional Invariant Promotion

**Goal**: Update README, CLAUDE.md, and `.claude/agents/test-engineer.md` to remove docker-exec-as-canonical guidance. If Phase 1–5 validated the canonical path discipline, promote `INV-D011` with a discovery test.
**Detailed Plan**: [phases/phase-6.md](phases/phase-6.md)

### Deliverables
1. Updated README § Sandbox setup, § Troubleshooting.
2. Updated CLAUDE.md § Running the Agent Locally.
3. Updated `.claude/agents/test-engineer.md`.
4. (Optional) `INV-D011` promoted in INVARIANTS.md + discovery test.

### Invariants Enforced Here
- **INV-D011 (new)** — only if promotion happens; discovery test asserts plugin tree at canonical path + absence of `/opt/<plugin>` references in any sandbox Dockerfile.

### Success Criteria
- [ ] Docs accurate
- [ ] Stale workaround notes deleted
- [ ] If promoted: INV-D011 discovery test green; INVARIANTS.md version bumped

---

## Testing Strategy

### Unit Tests
- No new unit tests anticipated. Plugin TypeScript is unchanged.

### Integration Tests
- `packages/toolkit/tests/integration/test_sandbox_plugin_at_canonical_path.py` (new) — asserts `/sandbox/.openclaw-data/extensions/genomeclaw/package.json` exists inside a fresh sandbox container and `openclaw plugins list` reports the plugin (Phase 2).
- `packages/toolkit/tests/integration/test_sandbox_gateway_recovery.py` (new) — boot, kill gateway, run `scripts/sandbox-up.sh`, assert gateway healthy (Phase 4).

### Provenance Tests
- n/a — no derived stores changed.

### Determinism Tests
- n/a — no pipelines changed.

### Privacy-Default Tests
- Existing privacy-default tests re-run unchanged. No new egress destinations.

### Evidence-Binding Tests
- n/a — interpretations unchanged.

### Report Rendering Tests
- n/a — reports unchanged.

### Invariant Tests
- `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` — re-run, must continue green.
- `packages/toolkit/tests/invariants/test_invV001_no_phrase_enumeration_in_agent_output_gates.py` — re-run.
- (Optional, Phase 6) `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` — discovery test for the proposed invariant.

### Replay / Agent-Synthesis Tests
- `packages/toolkit/tests/agent_replay/` full suite — re-run in Phase 5 to confirm no regression in `INV-A005 v1.23` / `INV-A006` behavior.

### Tool-Contract Tests
- n/a — no external bioinformatics tool added or upgraded.

### End-to-End Smoke Gate (Muscle Question)

Every phase that touches a runtime surface (Phases 2–6) ends with an **explicit end-to-end smoke** using the canonical muscle question:

> *"Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."*

This is the same question used during the prior session's `agent-synthesis-over-rich-tool-data` Phase-5 manual gate. It exercises multi-tool orchestration (`genomeclaw_status`, `genomeclaw_gene`, host-service queries), so it's a good integration probe.

The smoke gate is **not** a substring check — per `INV-V001` and `INV-A006`, we don't enumerate forbidden phrases. The pass criteria are:
- **Tool-trajectory shape**: the agent calls at least one `genomeclaw_*` tool successfully (read structurally from the trajectory file).
- **Reply non-empty**: `meta.finalAssistantVisibleText` is a non-empty string > 200 chars.
- **LLM-judge verdict** (gated by `GENOMECLAW_REPLAY_LLM=1`): the same `_judge.py` harness scores `(trajectory, reply)`; pass = `faithful=true` AND `understandable=true`.

Per-phase smoke wiring (which surfaces are exercised):

| Phase | Surface(s) exercised | Why |
|-------|---------------------|-----|
| Phase 2 | `scripts/ask.sh` (docker-exec path) | Confirms the rewritten Dockerfile produced a sane image — plugin loads, agent answers. The `nemoclaw connect` path may not be wired yet at this phase boundary. |
| Phase 3 | `scripts/ask.sh` **and** the NemoClaw-managed agent path (e.g. `nemoclaw genomeclaw exec openclaw agent --local --message ...` if it works in 2026.5.18, otherwise via the `openclaw tui --non-interactive` path) | Confirms gateway is healthy via both bypass and supervised paths. |
| Phase 4 | `scripts/ask.sh` **after killing the gateway and recovering** via `sandbox-up.sh` | Confirms recovery delegation actually works end-to-end, not just that the gateway HTTP probe returns 200. |
| Phase 5 | All three surfaces: dashboard (manual browser test), TUI (manual), `scripts/ask.sh` (scripted) | Full gate. The LLM-judge is mandatory here. |
| Phase 6 | `scripts/ask.sh` (regression check after doc edits) | Catches the case where a doc-driven config example or env-var rename accidentally regresses behavior. |

Each phase's RED step adds a `test_phaseN_muscle_question_smoke` test (or a manual gate documented in work-notes if the path isn't yet scriptable). GREEN requires the smoke to pass with the LLM-judge verdict captured in `work-notes.md` Phase N § Test Results.

If a smoke gate **fails**, the phase does NOT close. We diagnose the failure (`tail` the trajectory, inspect the trace JSON), file the cause, and either fix-in-phase or escalate to a new phase before moving on.

---

## Documentation Updates

- [ ] [README.md](../../../../README.md) — § Sandbox setup, § Troubleshooting (Phase 6)
- [ ] [CLAUDE.md](../../../../CLAUDE.md) — § Running the Agent Locally (Phase 6)
- [ ] [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) — workaround references (Phase 6)
- [ ] [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — only if `INV-D011` promotes (Phase 6)
- [ ] [docs/plans/active/nemoclaw-canonical-integration/work-notes.md](work-notes.md) — continuous

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-29 | 2026-05-29 | Path: `/sandbox/build/genomeclaw/` (install --link rejects in-scan-tree); pin: `:v0.0.50`; Q1=install required; Q2=env-only credentials |
| Phase 2 | Structural complete; smoke BLOCKED | 2026-05-29 | structural 2026-05-30 | Path migration + `:v0.0.50` pin DONE, 8/8 structural tests GREEN, plugin enabled in running sandbox. Muscle-question smoke BLOCKED by gateway-lifecycle (Facet A: v0.0.50 gateway refuses `bind=auto` w/o auth in-container; Facet B: started gateway loads 0 plugin tools, no `user:` source root) → escalated to Phase 3. See work-notes Phase 2. |
| Phase 3 | Facets B ✅ + A1 ✅ + A2 ✅ (pragmatic) — verified end-to-end | 2026-05-30 | 2026-05-30 | **B** (manifest `contracts.tools`+`activation.onStartup`; agent calls tools). **A1** (bake `gateway.bind=loopback` — no token, per privacy review). **A2** (delete onboard Step 6 literal-key `auth-profiles.json` write [reviewer HIGH finding] + dead Step 7 `inference.local`; key stays env-only via Step 7b, INV-P003-clean). The native L7-proxy credential ownership is infeasible on local Docker (no `inference.local` DNS / model-router; `inference set` sandbox-sync uses a failing k8s path) → documented upstream/Phase-4 follow-up. Clean re-onboard verified: auth-profiles.json absent, gateway loopback, `1 plugin: genomeclaw`, agent calls `genomeclaw_status`. Research: [initial_findings.md](initial_findings.md). |
| Phase 4 | Complete | 2026-05-30 | 2026-05-30 | `sandbox-up.sh`/`onboard-sandbox.sh` cleanup: canonical-path plugin check, port-based gateway detection, best-effort `nemoclaw recover` + keyed docker-exec restart (local-Docker recovery; nemoclaw recover infeasible locally). 5 script-shape tests + manual kill-and-recover smoke (agent calls `genomeclaw_status` after recovery). |
| Phase 5 | Surface gate ✅; data gate ⛔ blocked (infra) | 2026-05-30 | | Surface gate PASSED: regression suite 1175 passed (8 failures all pre-existing/in-flight, outside this plan); ask.sh muscle-question smoke = 22 tool calls incl. 4 `genomeclaw_*`, faithful reply handling the 503 honestly (vs 0 tools pre-fix); spec-Q4 clean. Completed A1 (`gateway.auth.mode=none` → gateway-routed surfaces token-free on loopback). **Data-grounded gate + dashboard/TUI BLOCKED**: no `v0.4` derived store (existing data v0.3) and a rebuild is infeasible here (colima won't mount `/Volumes/Genome_Work`; native bio tools absent) → host 503. Follow-up: rebuild on a pipeline host. |
| Phase 6 | Reconciled + handed off | 2026-05-30 | 2026-05-30 | Premise invalidated by Phase 5 (docker-exec/ask.sh stays canonical on local Docker → no sweeping doc rewrite). INV-D011 enforced by committed tests (path-pin + cold-metadata tool contract); registry entry + residual README `/opt`-staleness edits SPECIFIED + handed off (doc files have unrelated in-flight WIP — INVARIANTS.md +224 lines). See phase-6 "Reconciliation". |

---

## Open Risks & Follow-ups

- **Upstream `nemoclaw recover` reliability**: if it's broken in 2026.5.18 for reasons unrelated to our integration, Phase 4 falls back to a docker-exec final-fallback in `sandbox-up.sh` and we document the upstream bug as a follow-up.
- **Credential storage location on disk**: Phase 3 RED MUST verify file permissions and audit whether the key gets logged anywhere. If NemoClaw's storage is world-readable, escalate before continuing.
- **Plugin auto-discovery may need a manifest convention**: Phase 1 audit will tell us. If `openclaw plugins install` is still the right invocation, Phase 2 keeps it; if file-drop alone suffices, the Dockerfile loses a step.
- **Base-image SHA bump cadence**: this is a one-time pin now, but we'll drift again as soon as NemoClaw upstream releases. Track in `work-notes.md` § Open Risks; add a CLAUDE.md note in Phase 6.
- **`packages/toolkit/tests/integration/test_host_service_toolkit_image.py` may reference `/opt/genomeclaw/`** (spec Q4). Phase 5 audit; small follow-up if so.

---

## Deferred Follow-ups (external blockers — not implementation gaps)

The plan's implementation is complete and committed (4 commits). These remaining closeout items are blocked by factors outside this plan and outside safe reach in this environment:

1. **v0.4 derived-store rebuild + data-grounded smoke + dashboard/TUI manual gates** (Phase 5). The host service serves schema `v0.4`; the only derived store on disk is `v0.3` → `/v1/health` 503. Rebuilding is infeasible here: colima does not mount `/Volumes/Genome_Work` into its VM (docker pipeline can't reach the inputs) and native bio tools (`bcftools`/`tabix`/`vep`/`vcfanno`/`samtools`/`nextflow`) are absent. **Action**: run `genomeclaw pipeline run` on a pipeline host (or after wiring colima mounts / installing the toolchain), then re-run `scripts/ask.sh` for the data-grounded muscle-question smoke and do the dashboard/TUI manual gates (their auth/plumbing is already fixed — loopback + auth=none, canonical plugin path).
2. **Doc-file edits** (Phase 6): README's stale `/opt/genomeclaw`-EACCES troubleshooting (the migration fixed it; plugin is at `/sandbox/build/genomeclaw`) and the in-flight README `sandbox-up.sh` description need updating. **Blocked** because README/CLAUDE.md/`.claude/agents/test-engineer.md` carry unrelated uncommitted in-flight WIP in the exact sections to edit. **Action**: apply the edits specified in `phases/phase-6.md` alongside committing that doc WIP.
3. **INV-D011 registry entry** (Phase 6): the invariant is enforced by committed tests (`test_invD011_plugin_install_path.py` + `test_plugin_manifest_tool_contract.py`), but its INVARIANTS.md entry is deferred because INVARIANTS.md has +224 lines of unrelated in-flight WIP. **Action**: paste the entry text from `phases/phase-6.md` + bump the Version/Index when that WIP settles.

Once (1)–(3) land, set Status to **Complete** and move the plan to `docs/plans/completed/nemoclaw-canonical-integration/`.

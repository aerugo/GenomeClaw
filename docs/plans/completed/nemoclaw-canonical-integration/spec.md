# Feature: NemoClaw Canonical Integration (Fix the docker-exec Workaround)

**Status**: Draft
**Created**: 2026-05-29
**Owner**: aerugo
**Related Plans**:
- [agent-stale-memory-and-failure-mode-confabulation (completed)](../../completed/agent-stale-memory-and-failure-mode-confabulation/) — origin of `scripts/sandbox-up.sh` + the docker-exec workaround pattern this plan reverses.
- [agent-synthesis-over-rich-tool-data (active)](../agent-synthesis-over-rich-tool-data/) — the most recent plan that depended on the workaround; will benefit from canonical integration but doesn't block this.
- [onboard-persistent-agent-fix (completed)](../../completed/onboard-persistent-agent-fix/) — set up the current Dockerfile-based onboarding flow; this plan revises several of its choices.

---

## Goal

Stop bypassing NemoClaw via direct `docker exec` and the home-grown `scripts/sandbox-up.sh` gateway-restart loop. Move the GenomeClaw plugin to NemoClaw's documented canonical install path, fix the version skew that's breaking `nemoclaw connect` / the dashboard, and let NemoClaw own the gateway lifecycle. End state: `nemoclaw genomeclaw connect`, the dashboard at `http://127.0.0.1:18789/`, and `openclaw tui` all work as documented upstream; `scripts/ask.sh` continues to work as the scripted path.

## Background

Over the past three plans we've accumulated a load-bearing workaround pattern documented in [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) Step 8 ("docker exec is the working path; see step 8 comment for why nemoclaw exec is broken upstream") and in [README.md § Sandbox setup](../../../../README.md). The pattern: bake the plugin into `/opt/genomeclaw/`, run the gateway via `docker exec -d openclaw gateway run` after onboarding, and ask the agent questions via raw `docker exec` because everything via NemoClaw's own surfaces (`nemoclaw connect`, `nemoclaw exec`, dashboard at `127.0.0.1:18790`) fails with cryptic errors.

**Tonight (2026-05-29 evening) the workaround stopped working for interactive use** — the user wanted to ask the muscle question via the dashboard / TUI, and got:

1. Dashboard at `127.0.0.1:18790`: `ERR_EMPTY_RESPONSE` (port-forward didn't start).
2. `nemoclaw genomeclaw recover`: *"OpenClaw gateway is not running ... automatic recovery failed."*
3. After `./scripts/sandbox-up.sh --rebuild` (which onboards from scratch), `nemoclaw genomeclaw connect` succeeded but the TUI showed:
   - *"plugin: failed to read extensions dir: /opt/genomeclaw (Error: EACCES: permission denied, scandir '/opt/genomeclaw')"*
   - *"not connected to gateway — message not sent"* (TUI looking at `ws://127.0.0.1:18789`)
   - The onboard's recovery hint suggested launching the gateway with `--port 18790`, which the TUI doesn't look at.

Reading the upstream NemoClaw + OpenShell docs revealed three root causes that the docker-exec workaround was papering over:

### Root cause 1: Plugin location violates the Landlock baseline

Per OpenShell's policy docs ([source](https://docs.nvidia.com/openshell/sandboxes/policies)), the sandbox process is confined by **Landlock LSM at the kernel level** with this baseline:

- read-only: `/usr`, `/lib`, `/etc`, `/var/log`
- read-write: `/sandbox`, `/tmp`
- **any path not listed is inaccessible**

Our Dockerfile bakes the plugin at `/opt/genomeclaw/`. That path is NOT in the baseline → Landlock blocks `scandir` → the plugin loader fails with EACCES every time the sandbox is entered through the OpenShell runtime (i.e. `nemoclaw connect`, the dashboard's chat UI, or the TUI inside the container). Plain `docker exec` bypasses the OpenShell runtime entirely — that's why our docker-exec-based test paths and `scripts/ask.sh` always worked, and the interactive surfaces always failed.

Per the NemoClaw plugin install docs ([source](https://docs.nvidia.com/nemoclaw/latest/deployment/install-openclaw-plugins)), the canonical install path for OpenClaw plugins is **under `/sandbox/.openclaw/extensions/`** (which is symlinked to `/sandbox/.openclaw-data/extensions/` so the path is writable inside the Landlock baseline). The docs explicitly note: *"writable agent state such as plugins, skills, hooks, and workspace metadata lives directly under `/sandbox/.openclaw`"* — `/opt/<plugin-name>/` is not the canonical pattern, just a path that happens to work via docker-exec.

### Root cause 2: Sandbox base image version skew

The local image cache has `ghcr.io/nvidia/nemoclaw/sandbox-base:latest` resolved to a digest that ships OpenClaw 2026.4.24. The host's `nemoclaw` CLI is on 2026.5.18. Per the troubleshooting hint NemoClaw printed: *"Sandbox 'genomeclaw' is running OpenClaw 2026.4.24 (current: 2026.5.18). Run: nemoclaw genomeclaw rebuild."* The skew is the cause of the *"openclaw gateway run --port 18790"* mismatch — newer NemoClaw expects the gateway on a different port than older OpenClaw binds to.

### Root cause 3: Gateway lifecycle owned by the wrong actor

[scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) Step 7b restarts the gateway via `docker exec -d -e OPENAI_API_KEY=... openclaw gateway run`. That detaches a gateway process inside the container outside of NemoClaw's supervisor. When the gateway dies later (container restart, sandbox hibernation, host reboot), `nemoclaw recover` can't bring it back because NemoClaw's credential reloader doesn't have the secret — it was injected via `docker exec -e` only. The user then has to re-run `sandbox-up.sh`, which restarts the gateway (works) but leaves the dashboard port-forward + NemoClaw's session token out of sync.

The supported pattern (per NemoClaw docs) is to let `nemoclaw onboard` register the OpenAI key once via the credential system, and let NemoClaw own the gateway process. We bypassed that because of a separate bug in an earlier nemoclaw version that has likely been fixed in 2026.5.18 — the `INV-P003` traceback leak of base64-encoded keys (see [completed/onboard-persistent-agent-fix](../../completed/onboard-persistent-agent-fix/)). That bug was the original justification for `docker exec -e`; the structural protection is now also enforced by [test_invP003_onboard_script_no_secrets_in_argv.py](../../../../packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py), so we don't need the `docker exec -e` workaround to satisfy `INV-P003` — we need to satisfy it differently when handing credential management back to NemoClaw.

## Acceptance Criteria

- [ ] **AC1** — Plugin lives at `/sandbox/.openclaw-data/extensions/genomeclaw/` (or wherever NemoClaw's install docs canonically place it; see Phase 1 RED). The Dockerfile copies into this path and `openclaw plugins install` is invoked against it (or auto-discovery picks it up). `/opt/genomeclaw/` is not used anywhere.
- [ ] **AC2** — `nemoclaw genomeclaw connect` followed by `openclaw tui` inside the sandbox successfully starts the TUI **with the `genomeclaw` plugin loaded** (no EACCES warnings; the tool catalog shows `genomeclaw_status`, `genomeclaw_gene`, etc.).
- [ ] **AC3** — The NemoClaw dashboard at `http://127.0.0.1:<port>/` (port reported by `nemoclaw genomeclaw dashboard-url`) loads in a browser and lets the user chat with the `genomeclaw` agent.
- [ ] **AC4** — Sandbox base image is pinned by SHA digest (not `:latest`) so version skew can't drift silently again. The pin matches the current `nemoclaw` CLI version. Documentation explains when to bump the pin.
- [ ] **AC5** — `OPENAI_API_KEY` is registered via NemoClaw's credential system at onboard time (`nemoclaw credentials set` or the equivalent flow that the install docs document) rather than injected via `docker exec -e`. The gateway picks up the key from NemoClaw's reloader, so a future `nemoclaw recover` restores it without manual intervention.
- [ ] **AC6** — `scripts/onboard-sandbox.sh` no longer contains the Step 7b *"(re)starts the openclaw gateway"* docker-exec block. The gateway lifecycle is owned by `nemoclaw onboard`.
- [ ] **AC7** — `scripts/sandbox-up.sh` is **either** updated to leverage `nemoclaw <name> recover` (rather than starting the gateway directly) **or** deleted, with `scripts/onboard-sandbox.sh` becoming the only entry point. Decide in Phase 4 based on whether `nemoclaw recover` actually works after Phase 3 lands.
- [ ] **AC8** — `scripts/ask.sh` continues to work for scripted/CI question-asking. Documented in README + CLAUDE.md as the canonical CLI path for one-shot questions.
- [ ] **AC9** — `INV-P003` discovery test still passes (no secrets in argv). Verified that NemoClaw's credential system stores the key without exposing it on a command line.
- [ ] **AC10** — Existing plugin tests + the agent prompt-contract tests + the INV-A005/A006 tests continue to pass. No regression in the previously-shipped `agent-synthesis-over-rich-tool-data` work.
- [ ] **AC11** — README + CLAUDE.md + `.claude/agents/test-engineer.md` updated:
  - Remove the *"nemoclaw exec is broken upstream"* warnings.
  - Document the canonical NemoClaw-managed path (dashboard / connect / TUI).
  - Keep `scripts/ask.sh` as the scripted path.
  - Document the base-image-pin bump cadence.

## Applicable Invariants

- **INV-P003** Secrets Pass via stdin or env, Never via argv — preserved. Phase 3 routes the key through NemoClaw's credential system, which stores it server-side and reloads it into the gateway env — no argv exposure.
- **INV-P001** Privacy Default — unchanged. Egress destinations stay the same; this is purely a plumbing fix.
- **INV-A005 v1.23** + **INV-A006** + **INV-V001** — must continue to pass. Tests are unchanged; the underlying plugin source + agent prompt are unchanged; only the install path and onboarding flow change.
- **INV-D006** + **INV-D007** DooD discipline — re-verify against the new plugin path. The plugin doesn't spawn DooD siblings directly (the host service does), so changing `/opt/genomeclaw/` → `/sandbox/.openclaw-data/extensions/genomeclaw/` shouldn't affect the DooD seam, but Phase 5 includes an explicit re-check.

## Proposed New Invariants

- **NEW `INV-D011` (proposed)** *Plugin Install Path Follows NemoClaw's Canonical Pattern*: any plugin baked into a GenomeClaw sandbox image MUST live under `/sandbox/.openclaw-data/extensions/<plugin-id>/` (or the upstream-documented equivalent) so it remains accessible to processes started via the OpenShell sandbox runtime (Landlock baseline). Plugins MUST NOT be placed under `/opt/`, `/usr/local/lib/`, or any other path outside the Landlock baseline + the documented plugin tree.

  Decision deferred to Phase 1 review — promote if the path discipline applies cleanly + we want to prevent regression.

## Technical Requirements

### Source Data Inputs

- [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) — primary surface. Plugin install path lives here.
- [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) — multi-step onboarding flow. Steps 1–5 stay; Step 6 (auth-profiles.json write) may stay or move into NemoClaw's credential flow; Step 7 (inference.local routing) stays; Step 7b (docker-exec gateway run) is **deleted**; Step 8 (smoke test) is rewritten to verify via the dashboard or `nemoclaw connect`.
- [scripts/sandbox-up.sh](../../../../scripts/sandbox-up.sh) — auto-recovery wrapper. Adjusted to delegate to `nemoclaw recover` instead of restarting the gateway directly.
- [scripts/ask.sh](../../../../scripts/ask.sh) — canonical scripted question path. Stays. May be simplified once the gateway is healthy more reliably.
- [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml) — network policy. Check whether anything filesystem-related needs to be added; Phase 1 audits.
- [README.md](../../../../README.md) § Sandbox setup + § Troubleshooting — documentation cleanup.
- [CLAUDE.md](../../../../CLAUDE.md) § Running the Agent Locally — documentation cleanup.

### Derived Outputs

- Updated Dockerfile + sandbox image (with plugin at the canonical path; pinned base SHA).
- Updated onboard-sandbox.sh (shorter; gateway-lifecycle steps removed).
- Updated scripts/sandbox-up.sh (delegating to `nemoclaw recover`).
- Updated README + CLAUDE.md + test-engineer agent.
- Possibly: new `INV-D011` invariant + discovery test.

### Schema / Migration Impact

- **None for derived stores.** Pure operational plumbing change.
- Sandbox image rebuild required (one-time). The plugin code itself doesn't change.

### Pipeline / Workflow Impact

- **None.** Host service / pipeline unchanged.

### Agent / UX Impact

- **End-state UX is the user-visible improvement**: dashboard works, `nemoclaw connect` works, TUI works. Agent code itself unchanged.

### External Dependencies

- A `ghcr.io/nvidia/nemoclaw/sandbox-base` SHA matching the host's `nemoclaw` CLI version. Phase 4 selects the pin.

## Privacy & Safety Considerations

- **Boundary scan**: Phase 3 moves `OPENAI_API_KEY` from `docker exec -e` injection to NemoClaw's credential system. NemoClaw's credential storage is documented but Phase 3 RED must explicitly verify: where does the key land on disk? Is it world-readable? Is it logged?
- **INV-P003**: argv-leak test must continue to pass. Phase 3 includes an explicit re-run as part of GREEN gating.
- **Default-off remote calls**: unchanged.

## Out of Scope

- **Upstream NemoClaw bug fixes.** If `nemoclaw recover` is itself broken in 2026.5.18 (independent of our integration), this plan documents the gap and falls back to `scripts/sandbox-up.sh`-style local restart, but does not patch upstream.
- **Plugin code changes.** TypeScript stays as-is; only the install path inside the image moves.
- **Host service changes.** `bin/genomeclaw host service` and its derived-data integration are unaffected.
- **Removing `scripts/ask.sh`.** It's a useful one-shot tool regardless of whether the dashboard works.

## Dependencies

- Working `nemoclaw` CLI on the host (currently 2026.5.18).
- Network access to `ghcr.io/nvidia/nemoclaw/sandbox-base` for the pinned SHA pull.

## Open Questions

- [ ] **Q1**: Does `openclaw plugins install` need to be invoked at all if the plugin tree is `cp -a`'d into `/sandbox/.openclaw-data/extensions/<plugin-id>/` at image build time? The docs hint that auto-discovery picks it up. Resolve during Phase 1 RED.
- [ ] **Q2**: Does NemoClaw's credential system have a non-interactive mode that fits the existing `scripts/onboard-sandbox.sh` flow (which already uses `NEMOCLAW_NON_INTERACTIVE=1`)? If yes, Phase 3 is straightforward. If no, the script needs an interactive prompt or an `expect`-style workaround. Resolve during Phase 3 RED.
- [ ] **Q3**: Does `nemoclaw <name> rebuild` (vs `nemoclaw onboard --fresh --recreate-sandbox`) suffice when only the base image SHA changes? Faster iteration if yes. Resolve during Phase 4 RED.
- [ ] **Q4**: Do any of our integration tests under `packages/toolkit/tests/integration/test_host_service_toolkit_image.py` reference `/opt/genomeclaw/`? Phase 5 audit will find out; minor follow-up if so.

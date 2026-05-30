# NemoClaw Canonical Integration — Work Notes

**Feature**: Move plugin to NemoClaw's canonical install path, pin sandbox base image by SHA, hand gateway lifecycle + credentials back to NemoClaw.
**Started**: 2026-05-29
**Branch**: `main`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom. Each session opens with a context-review block before getting into the work.

### 2026-05-29 — Plan creation session

**Context Review Completed**:
- Re-read root [CLAUDE.md](../../../../CLAUDE.md) — confirmed the 5 critical invariants. Plan touches `INV-P003` (secrets), nothing else materially.
- Re-read [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) v1.24 — relevant: INV-P001, INV-P003, INV-A005 v1.23, INV-A006, INV-V001, INV-D006/D007.
- Re-read [docs/plans/CLAUDE.md](../../CLAUDE.md) planning protocol — confirmed multi-subsystem effort warrants full directory layout.
- Read upstream docs:
  - OpenShell sandbox policies → Landlock baseline = `/usr`, `/lib`, `/etc`, `/var/log` (RO), `/sandbox`, `/tmp` (RW).
  - NemoClaw install OpenClaw plugins → canonical install path under `/sandbox/.openclaw-data/extensions/<plugin-id>/` (symlinked from `/sandbox/.openclaw/extensions/`).
- Read [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh) — identified Step 7b as the gateway-ownership leak.
- Read [scripts/ask.sh](../../../../scripts/ask.sh) — confirmed it bypasses NemoClaw entirely via raw `docker exec`; that's why it always works regardless of dashboard / TUI state.

**Applicable Invariants**:
- **INV-P003**: secrets must not appear in argv. Phase 3 RED MUST verify NemoClaw's credential storage uses env / stdin, not argv. The existing argv-leak discovery test guards the *script* surface; we'll re-run it after the script rewrite.
- **INV-V001**: no phrase enumeration for any verification gate. All Phase 5 connectivity checks are HTTP-probe + structural (`docker inspect`, `openclaw plugins list`), not log-grep.
- **INV-A005 v1.23**: the replay suite must continue to pass after the install-path migration. The plugin code is unchanged; only its location changes.

**Key Insights**:
- Three independent failure modes have been treated as one "nemoclaw is broken" symptom. Separating them: Landlock-blocked path (root cause 1) → no plugin loads inside sandbox runtime; version skew (root cause 2) → gateway port mismatch; gateway lifecycle ownership (root cause 3) → recovery fails. Fixing each in isolation lets us verify the gain at each phase boundary.
- `scripts/ask.sh` is the only path that's worked end-to-end — *because* it bypasses the OpenShell runtime. It will continue to work after the migration but stops being load-bearing for interactive use.
- `INV-P003`'s structural protection (argv-leak discovery test) decouples *how* we pass the secret from the invariant. NemoClaw's credential system is acceptable as long as it doesn't put the key on argv. Phase 3 RED confirms.

**Completed Today**:
- [x] Created [spec.md](spec.md) with goal, background (3 root causes), 11 ACs, applicable invariants, proposed `INV-D011`, technical requirements, open questions Q1–Q4.
- [x] Created [development-plan.md](development-plan.md) with critical invariants, current state, solution design diagram, key design decisions, phase overview (6 phases), testing strategy, progress tracking.
- [x] Created phase scaffolds [phases/phase-1.md](phases/phase-1.md) through [phases/phase-6.md](phases/phase-6.md).
- [x] Created this work-notes.md.

**Decisions Made**:
- **Plan target path is `/sandbox/.openclaw-data/extensions/genomeclaw/`** (with the symlink from `/sandbox/.openclaw/extensions/genomeclaw/` to be confirmed in Phase 1). Rationale: docs say writable agent state lives there; it's inside the Landlock baseline; matches upstream convention.
- **Base image pin by SHA, not tag**. Rationale: `:latest` drifted silently; the cached digest from a prior pull no longer matches the host CLI. Pinning forces an intentional bump.
- **6 phases, not 3 or 4**. Each phase is independently verifiable. Smaller phases reduce blast radius for a rollback if Phase 2 build or Phase 3 credential hand-off goes sideways.
- **Don't delete `scripts/ask.sh`**. It's useful in CI / scripted contexts independent of dashboard state. Spec AC8.

**Blockers / Issues**:
- None for plan creation. Phase 1 RED will surface anything blocking implementation.

**Next Steps**:
1. Start Phase 1: probe upstream docs more carefully (specifically: does `openclaw plugins install` need to run at all if the plugin is `cp -a`'d to the canonical path), and write/run any Phase 1 audit test.
2. After Phase 1 path target is confirmed, move to Phase 2 (Dockerfile + SHA pin).

### 2026-05-29 — Phase 1 implementation session

**Context Review Completed**:
- Re-read `docs/plans/CLAUDE.md` planning protocol (TDD per phase + structural verification).
- Re-read `docs/reference/INVARIANTS.md` invariant index — confirmed INV-V001 governs the Phase 1 verification methodology (structural inspection over substring grep).
- Read existing `scripts/onboard-sandbox.sh` to ground Phase 3 design in the current credential-handling code path.

**Applicable Invariants**:
- **INV-V001**: probe results captured via `docker run … openclaw plugins list` structured output + `ls -la` directory listings — not log-grepping for keywords.
- **INV-P003**: noted in passing — Phase 1 confirmed NemoClaw's modern credential store writes nothing to disk (`saveCredential` is in-process env mutation), so Phase 3 can rely on env-only handoff and remain structurally protected.

**Completed Today**:
- [x] Probed `ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` against the local cache + the host CLI's bundled provider table.
- [x] Confirmed canonical path = `/sandbox/.openclaw/extensions/genomeclaw/` (no `.openclaw-data` symlink in v0.0.50).
- [x] Resolved Q1: file-drop alone is not auto-discovered; `openclaw plugins install --link` is still required.
- [x] Resolved Q2: non-interactive credential flow = env-only via `NEMOCLAW_PROVIDER=openai` + `OPENAI_API_KEY` exported before `nemoclaw onboard --non-interactive`.
- [x] Audited `policy-preset.yaml` — no `filesystem_policy` changes needed.
- [x] Revised Decision 1 (path) + Decision 2 (pin strategy) in this work-notes.md to reflect probe findings.

**Decisions Made**:
- Path target revised to `/sandbox/.openclaw/extensions/genomeclaw/` (not `/sandbox/.openclaw-data/extensions/`).
- Base image pin = `:v0.0.50` tag (host-version-matching), not a raw `sha256:` digest, for multi-arch portability.

**Blockers / Issues**:
- None. Phase 2 can proceed.

**Next Steps**:
1. Phase 2: rewrite `packages/nemoclaw-plugin/sandbox/Dockerfile` to use the canonical path + the `:v0.0.50` pin.
2. Build the new image + verify `openclaw plugins list` shows `genomeclaw` in the user root from a fresh container.

---

## Phase Progress

### Phase 1: Upstream Docs Audit + Path Target Confirmation
**Status**: Complete
**Started**: 2026-05-29
**Completed**: 2026-05-29

#### Test Results

Probes run against `ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` (local digest `sha256:3d9391e6c27c986f4ded2e36c874b5f16f59001cdda3415daa48a43ccb5a2ed3`).

```text
$ docker run --rm --user sandbox <image> openclaw --version
OpenClaw 2026.5.18 (50a2481)

$ docker run --rm --user sandbox <image> ls -la /sandbox/.openclaw/extensions/
drwxrwsr-x 2 sandbox sandbox 4096 May 23 04:45 .
drwx------ 1 sandbox sandbox 4096 May 23 04:52 ..
# (empty — direct writable canonical dir; no .openclaw-data symlink in v0.0.50)

$ docker run --rm --user sandbox <image> ls -la /sandbox/.openclaw-data/
ls: cannot access '/sandbox/.openclaw-data/': No such file or directory

$ docker run --rm --user sandbox <image> openclaw plugins list
Plugins (65/91 enabled)
Source roots:
  stock: /usr/local/lib/node_modules/openclaw/dist/extensions
(no `user:` root unless openclaw plugins install has run)

$ docker run --rm -v <probe-dir>:/sandbox/.openclaw/extensions/probe-test:ro <image> openclaw plugins list
# Same output — file-drop alone is NOT auto-discovered. `Source roots:` still shows only `stock:`.

$ docker run --rm <image> openclaw plugins install <path> --link
# Installs into ~/.openclaw/npm/node_modules/<scope>/<pkg> (visible in existing weixin row).
```

Credential flow probe (host CLI):
```text
$ nemoclaw credentials --help
COMMANDS:
  credentials list   List stored credential providers
  credentials reset  Remove a provider credential
# No `credentials set` subcommand. Credentials are registered ONLY through onboard.

$ nemoclaw onboard --help
… --non-interactive …
# Source: /Users/hugi/.nemoclaw/source/dist/lib/onboard/providers.js:33
#   openai: { credentialEnv: "OPENAI_API_KEY", ... }
# Source: /Users/hugi/.nemoclaw/source/dist/lib/credentials/store.js:157 saveCredential
#   "Nothing is persisted to disk … the gateway is the system of record."
```

#### Results

- **Path**: canonical install location is `/sandbox/.openclaw/extensions/genomeclaw/` directly. The `.openclaw-data/extensions/` symlink path referenced in the development-plan does NOT exist in `sandbox-base:v0.0.50`; the plan's path needs revising. The direct path is already inside the Landlock RW baseline (`/sandbox`).
- **Base image SHA**: `ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` — the version-tagged digest matches host `nemoclaw v0.0.50` exactly; contains OpenClaw 2026.5.18. Pin candidate: this tag (which resolves to a stable multi-arch index digest upstream).
- **Q1 resolved**: file-drop alone is NOT auto-discovered. `openclaw plugins install <path> --link` is still required (matches the current Dockerfile's pattern). Phase 2 retains the install step.
- **Q2 resolved**: NemoClaw's non-interactive credential path = `NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_PROVIDER=openai OPENAI_API_KEY=... nemoclaw onboard --non-interactive --yes ...`. Credentials are env-only inside the credential store (gateway is system of record; nothing persisted to host disk). Structurally satisfies `INV-P003` — credential travels env-only, never argv.
- **Policy preset**: `packages/nemoclaw-plugin/policy-preset.yaml` is purely `network_policies`; no `filesystem_policy:` section. Because the new plugin path is inside the Landlock RW baseline, no filesystem allowance is needed. Policy preset stays as-is for Phase 2.

#### Notes

- Reference for credential env-only flow: `~/.nemoclaw/source/dist/lib/credentials/store.js:147-165` (saveCredential is in-process env mutation, no fs writes).
- The local `sandbox-base:latest` cached digest (`sha256:3d36a38a...`) is 7 days old and differs from `:v0.0.50` (6 days old, `sha256:3d9391e6...`). The `:latest` drift confirms the spec's root cause 2 hypothesis. Pinning by tag `:v0.0.50` is the simplest forward-compatible pin (re-resolves to the same multi-arch index each pull); pinning by full sha256 digest would require an arch-specific digest. Phase 2 will use the `:v<nemoclaw-version>` tag pattern with a comment + lockfile in the Dockerfile recording the resolved multi-arch digest at pin time.

---

### Phase 2: Dockerfile Rewrite + Base-Image SHA Pin
**Status**: Structural deliverable COMPLETE + verified; muscle-question SMOKE **BLOCKED** (gateway-lifecycle root cause → escalated to Phase 3)
**Started**: 2026-05-29
**Completed**: structural work 2026-05-30; smoke gate pending Phase 3

#### Session log (2026-05-30 implementation session)

**Context review**: re-read development-plan, phase-2.md (reconciled to actual `/sandbox/build/genomeclaw/` path + `:v0.0.50` pin — the scaffold predated the Phase 1 probe), Dockerfile, ask.sh, onboard-sandbox.sh, INVARIANTS governance for INV-V001/INV-D011.

**Prior-session state recovered**: the Dockerfile had already been rewritten (working tree, uncommitted) to the canonical `/sandbox/build/genomeclaw/` path with the `:v0.0.50` pin, and both Phase 2 test files were created. Work-notes still said "Pending". `genomeclaw/sandbox:phase2` image had been built ~42 min before this session.

**Structural deliverable — DONE + GREEN**:
- Reconciled `phases/phase-2.md` to the actual implementation (path, pin, test names, verification commands, completion criteria).
- `test_invD011_plugin_install_path.py` — **4/4 PASS** (no docker): Landlock-baseline install path, no `/opt/genomeclaw` ref, `:v0.0.50` version-tag pin, cross-Dockerfile sweep.
- `test_sandbox_image_canonical_plugin_path.py` — **4/4 PASS** against `genomeclaw/sandbox:phase2`: package.json + dist/index.js at canonical path, `/opt/genomeclaw` absent, `openclaw plugins list` shows `genomeclaw` enabled.
- Ran `./scripts/onboard-sandbox.sh` → rebuilt from the canonical Dockerfile + recreated the sandbox (exit 0). Verified in the **running** sandbox: plugin enabled at `~/build/genomeclaw/dist/index.js`, `/opt/genomeclaw` absent.

**Muscle-question smoke — FAILED criterion (c) (≥1 genomeclaw_* tool call)**. Captured trace: `docs/reports/demo-2026-05-29-logs/give-personalized-recommendations-based-on-genome-on-how-i-should-train-to-build.trace.json`. Reply was a coherent >200-char *non-genomic* fallback ("I can't give genome-personalized recommendations… the GenomeClaw plugin tools aren't exposed here"). `toolSummary`: 4 calls = `update_plan, memory_search, web_search`; **zero `genomeclaw_*`**. `requestShaping.thinking: off` (baked default is `xhigh`).

**Root-cause investigation (structural, INV-V001-compliant — `docker exec` + log/cmdline/config inspection, no log-grep gating)**:

The plugin *loads* fine — every process that opens the openclaw config logs `GenomeClaw plugin registered (9 tools)`. The failure is entirely in the **gateway/agent runtime layer**, which has two coupled facets:

- **Facet A — gateway refuses to start in-container without auth.** `sandbox-base:v0.0.50`'s gateway, in a container, defaults to `bind=auto` (0.0.0.0) and *"Refuses to bind gateway to auto without auth"* unless `OPENCLAW_GATEWAY_TOKEN`/`--token`/`--password` is set. The image bakes `gateway.mode=local` but **not** `gateway.bind` or `gateway.auth.mode`. Confirmed identical failure on THREE start paths: onboard Step 7b (`docker exec -d openclaw gateway run`), `nemoclaw genomeclaw connect --probe-only` (automatic recovery → `/tmp/gateway.log` shows the exact refusal), and the dashboard. **This is the unifying root cause behind all three original symptoms (dashboard/connect/TUI) and the smoke failure.**
- **Facet B — even a manually-started clean gateway surfaces 0 plugin tools.** Starting `openclaw gateway run --bind loopback --auth none` succeeds (`auth mode=none … ready`), but logs `http server listening (0 plugins)` and the embedded `openclaw agent --local --agent genomeclaw` still gets `toolSummary={}` + `thinking=off`. `openclaw plugins list` shows `genomeclaw` enabled BUT `Source roots:` lists only `stock:` — there is **no `user:` source root**. Config is correct (`plugins.load.paths=[/sandbox/build/genomeclaw]`, `plugins.allow=[genomeclaw]`, `entries.genomeclaw.enabled=true`), and the agent registers the 9 tools in-process, yet they never reach the model's callable tool catalog. Hypothesis (unconfirmed, needs Phase 3 source-dive): the gateway/agent tool catalog is sourced from auto-scanned source roots, and `install --link` from `/sandbox/build` records `plugins.load.paths` (visible to `plugins list`) without surfacing a `user:` source root the tool catalog consumes.

**Comparison anchor**: the working `post-v123-muscle-question` run earlier today (2026-05-29 21:23, OLD `/opt` image, same `openclaw agent --local --agent genomeclaw` command) had `thinking=xhigh` + 18 tool calls incl. `genomeclaw_status/gene/findings/pgs_*`. The OLD Dockerfile used the **identical** `openclaw plugins install … --link` mechanism (only the path differed), so the registration approach is not the regression — the gateway runtime state is.

**Why this is NOT a fix-in-Phase-2 item**: Facet A is a gateway auth-mode/bind decision (security-relevant: `auth=none` on a loopback gateway vs a persisted token) that the plan routes through **Phase 3** (gateway lifecycle + credential hand-off) with privacy-safety review. Facet B is gateway tool-surfacing wiring, also Phase 3. Baking `gateway.auth.mode=none` unilaterally would pre-empt that security decision. Per the plan's smoke-failure protocol ("diagnose the failure, file the cause, and either fix-in-phase or escalate") and the planning protocol ("do not paper over with a workaround that violates an invariant / surface the blocker"), this is **escalated to Phase 3** rather than worked around in Phase 2.

**Environmental note (separate, non-blocking)**: the host derived store is at schema `v0.3` (CURRENT → `2026-05-25T19-42-58Z-c88e02`) but this toolkit build serves `v0.4`; `/v1/health` returns `schema_version_mismatch`. So even once the gateway is fixed, a `v0.4` rebuild (`genomeclaw pipeline run`) is needed for the muscle question to ground on real genomic data. Also: native host service requires `--derived-root /Volumes/Genome_Work/genomeclaw/derived` because colima does not mount `/Volumes/Genome_Work` into its VM (the documented `GENOMECLAW_NATIVE=1` case).

**Sandbox left state**: a manual `openclaw gateway run --bind loopback --auth none` (gwX) is currently the only gateway; it is loopback-only and unauthenticated (low risk in-container, but to be replaced by the Phase 3 supervised gateway). Phase 1 runtime-config bakes + canonical-path image are in the recreated sandbox.

#### Test Results

```text
$ uv --project packages/toolkit run pytest packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py -v
4 passed

$ GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase2 uv --project packages/toolkit run pytest \
    packages/toolkit/tests/integration/test_sandbox_image_canonical_plugin_path.py -v -m needs_sandbox
4 passed

Running sandbox (recreated via onboard from canonical Dockerfile):
  openclaw plugins list → │ GenomeClaw │ genomeclaw │ enabled │ ~/build/genomeclaw/dist/index.js │ 0.0.1 │
  test -e /opt/genomeclaw → absent (good)

Muscle-question smoke (ask.sh --capture): FAILED criterion (c).
  toolSummary={"calls":4,"tools":["update_plan","memory_search","web_search"],"failures":0}  (zero genomeclaw_*)
  thinking=off ; reply coherent >200 chars but explicitly non-genomic fallback.
  Root cause: gateway-lifecycle (Facet A + Facet B above) → escalated to Phase 3.
```

#### Facet B deep-dive (2026-05-30, at user request before pausing)

Goal: understand why even a cleanly-started gateway surfaces 0 plugin tools, before choosing the Facet A auth posture. Findings (all structural / empirical, INV-V001-clean):

1. **Agent-via-gateway vs embedded `--local`**: running `openclaw agent --agent genomeclaw` *without* `--local` (i.e. through the gateway) DOES pick up the baked agent config (`thinking=xhigh`) — but still gets `genomeclaw_status: command not found` and falls back to `exec`. So the gateway's own tool registry lacks the genomeclaw tools; it's not an embedded-mode quirk.
2. **What the gateway loads**: the gateway auto-enables `openclaw-weixin` (which lives in `~/.openclaw/npm/node_modules/@tencent-weixin/`) but never `genomeclaw`. It logs `http server listening (0 plugins)`. The gateway loads plugins via npm-package resolution, **not** from `plugins.load.paths`.
3. **`install --link` is gateway-invisible**: `openclaw plugins install /sandbox/build/genomeclaw --link` records `plugins.load.paths=[/sandbox/build/genomeclaw]`. The CLI (`plugins list`) and the embedded agent honor this (plugin shows `enabled`, logs `registered 9 tools` on every config load), but the gateway ignores it. `plugins list` "Source roots:" shows ONLY `stock:` — there is no `user:` source root.
4. **Non-link install → `extensions/`, also not loaded**: `openclaw plugins install /sandbox/build/genomeclaw` (no `--link`) copies the full tree (dist + node_modules) into `~/.openclaw/extensions/genomeclaw/` and says "Restart the gateway to load plugins" — but after a clean gateway restart it STILL loads 0 plugins. v0.0.50 does not auto-scan `~/.openclaw/extensions/` as a source root (matches the Phase 1 file-drop probe).
5. **Symlink into `npm/node_modules` → still not loaded**: symlinking `~/.openclaw/npm/node_modules/@genomeclaw/nemoclaw-plugin → ~/.openclaw/extensions/genomeclaw` and restarting the gateway STILL yields 0 plugins. **Strong lead**: every load logs `Plugin manifest id "genomeclaw" differs from npm package name "@genomeclaw/nemoclaw-plugin"; using manifest id as the config key.` `plugins.allow=["genomeclaw"]` (the manifest id) may not resolve against the npm package name `@genomeclaw/nemoclaw-plugin` during the gateway's npm-based discovery, so the gateway never selects it.
6. **Supervised gateway can't be used as the comparison anchor on v0.0.50**: nemoclaw launches the supervised gateway as `openclaw gateway run --port <port>` (`~/.nemoclaw/source/dist/lib/agent/runtime.js:196`) — no `--bind`/`--auth` — so it hits the Facet A guard and never starts. The OLD working `post-v123` run therefore ran on the cached `:latest` base (OpenClaw **2026.4.24**, the spec's root cause 2), where neither the auth guard NOR the `--link`→`load.paths`/gateway-invisible behavior existed. **The v0.0.50 migration is what introduced both Facet A and Facet B.** Facet B cannot be fully closed by manual gateway runs alone — the working path requires the supervised gateway, which needs Facet A fixed first. The two facets are coupled.

**Facet B fix candidates for Phase 3** (in priority order, all need Facet A fixed first so the supervised gateway can run):
- **(a) Align the plugin's npm package name with its manifest id.** Make `package.json` `name` = `genomeclaw` (or set `plugins.allow`/`entries` to the package name `@genomeclaw/nemoclaw-plugin`) so the gateway's npm-package discovery resolves the allowlist entry. This is the highest-probability fix given lead #5.
- **(b) Install into `~/.openclaw/npm/node_modules/<name>` the way bundled plugins (weixin) are**, using whatever `openclaw plugins install` flag (or `npm install <local-path>`) lands it there under the resolvable package name — NOT `--link` (load.paths) and NOT the bare copy (extensions).
- **(c) Once Facet A is fixed, re-test whether the supervised `openclaw gateway run --port` honors `plugins.load.paths`** (it may, where the manual `--bind loopback` run does not — though that's unlikely, it's cheap to confirm).
- Consult upstream nemoclaw v0.0.50 plugin docs for the canonical gateway-visible install path.

**Experimental mutations left in the running sandbox** (ephemeral; next onboard recreates clean): a copy of the plugin at `~/.openclaw/extensions/genomeclaw`, a symlink `~/.openclaw/npm/node_modules/@genomeclaw/nemoclaw-plugin`, and a manual `openclaw gateway run --bind loopback --auth none` gateway. None of these are baked; they were diagnostic only.

**PAUSED here per user direction** — investigate Facet B (done), then pause before implementing the Phase 3 fix / choosing the Facet A auth posture.

#### Facet B — package-name alignment retest (2026-05-30, user-requested) — HYPOTHESIS DISPROVEN

User directive: "align the package name and retest the gateway." Done, with controls. The package-name-vs-manifest-id mismatch is **not** the cause:

- Set the installed plugin's `package.json` `name` → `genomeclaw` (aligned with the manifest `id`). `installs.json` `plugins[]` then shows a single clean entry: `pluginId=genomeclaw`, `packageName=genomeclaw`, `enabled=true`, no `diagnostics`, no duplicate. Gateway restart → **still `0 plugins`**, agent still `genomeclaw_status: command not found`.
- Counter-evidence the mismatch was never the cause: the **working** `weixin` plugin ALSO has `pluginId` (`openclaw-weixin`) ≠ `packageName` (`@tencent-weixin/openclaw-weixin`), yet loads fine. The discriminator is **install location**, not naming.
- Ruled out, each with a clean gateway restart: (1) `--link`/`load.paths` cleared to `[]`; (2) plugin copied into `~/.openclaw/extensions/genomeclaw` (the bare/tarball `openclaw plugins install` target) — **not loaded**; (3) plugin copied into `~/.openclaw/npm/node_modules/genomeclaw` + `installs.json` repointed there with `origin=npm` — **not loaded**; (4) `import "openclaw"` fails standalone from BOTH `extensions/` and `npm/node_modules/` (openclaw is global-only), yet `weixin` loads → the gateway injects SDK resolution, so import-resolution is not the discriminator.
- **`openclaw plugins install <local-path|.tgz>` always installs to `~/.openclaw/extensions/`**, never `npm/node_modules`. Only npm-registry-spec installs (like `weixin@2.4.3`) land in `npm/node_modules`. The manually-run gateway (`openclaw gateway run --bind loopback --auth none`) loads **only** `npm/node_modules` + `stock` plugins, never `extensions/` — regardless of name/registration.
- **Facet A refinement** (found while retesting): `gateway.auth.mode=none` in *config* does NOT satisfy the bind=auto guard — launching `openclaw gateway run --port 18789` (exactly nemoclaw's supervised command) STILL prints *"Refusing to bind gateway to auto without auth … Set OPENCLAW_GATEWAY_TOKEN/PASSWORD or pass --token/--password"*. `auth=none` only works with explicit `--bind loopback`. **Therefore the dashboard/TUI path (which needs bind=auto port-forward) requires a baked gateway TOKEN, not auth=none.** Loopback-only (ask.sh) can use `--bind loopback --auth none`.

**Net**: the remaining untested variable is the **supervised gateway**, which is blocked behind Facet A (can't start without a token). The two facets are confirmed coupled. Next concrete step (Phase 3): bake a gateway token (`gateway.auth.mode=token` + persisted `gateway.auth.token`, INV-P003-clean) so the supervised gateway starts with bind=auto, THEN re-test plugin loading in the real supervised gateway. If `extensions/`-installed plugins still don't load there, escalate to an upstream nemoclaw question with this evidence (how is a *locally-built* tool plugin made gateway-visible in v0.0.50, given local installs only target `extensions/`).

Source `packages/nemoclaw-plugin/package.json` was NOT modified (the name change was applied only to the in-container copies for the test). Live sandbox config was mutated (`plugins.load.paths=[]`, `gateway.auth.mode=none`) — ephemeral, wiped by the next onboard. A loopback+auth-none gateway is left running.

#### Facet B ROOT CAUSE FOUND via online research (2026-05-30) → [initial_findings.md](initial_findings.md)

The user asked to research best practices online. Result (authoritative, from `docs.openclaw.ai`):

- **OpenClaw builds the gateway/agent tool catalog from COLD MANIFEST METADATA** — it reads `openclaw.plugin.json` → **`contracts.tools`** *without importing the plugin runtime*. Our manifest has no `contracts` and no `activation` block, so the gateway never discovers that the plugin owns any tools → 0 surfaced. The `registerTool()` calls only run when the runtime is imported (CLI/embedded), which is why CLI logs "registered 9 tools" but the gateway catalog is empty. This is documented, intended behavior (GitHub openclaw#61790/#47683/#50328). It also reconciles the OLD-image anchor: 2026.4.24 surfaced runtime-registered tools eagerly; 2026.5.18 requires the cold-metadata contract.
- **Fix**: add `"contracts": { "tools": [<all registered tool names>] }` + `"activation": { "onStartup": true }` to `openclaw.plugin.json`. Verifiable against the already-running loopback gateway (no token needed) → do this FIRST in Phase 3.
- **Facet A best practice**: dashboard/TUI need bind=auto (nemoclaw launches `gateway run --port`), which requires a token → bake `gateway.auth.mode=token` + persisted `gateway.auth.token` (INV-P003-clean, token in baked config file not argv). Loopback+auth=none stays valid for `ask.sh`.
- All prior Facet B leads (package-name alignment, load.paths, install location) were symptoms of the missing manifest contract, not the cause — do not re-pursue.

Full synthesis + sources in [initial_findings.md](initial_findings.md); Phase 3 plan ([phases/phase-3.md](phases/phase-3.md)) updated with the concrete fix.

#### Facet B FIX IMPLEMENTED + VERIFIED LIVE (2026-05-30)

TDD:
- **RED**: added `packages/toolkit/tests/invariants/test_plugin_manifest_tool_contract.py` (3 tests: manifest declares `contracts.tools`; `activation.onStartup` true; `contracts.tools` ⊇ all non-gated `registerTool` names in `src/index.ts`). All 3 failed against the contract-less manifest.
- **GREEN**: added to `packages/nemoclaw-plugin/openclaw.plugin.json`:
  - `"activation": { "onStartup": true }`
  - `"contracts": { "tools": [9 production tools] }` — `genomeclaw_status, _findings, _variant, _evidence, _gene, _pgs_list, _pgs_get, _pgs_compute, _pgs_compute_status`. (`genomeclaw_ssrf_probe_batch` is test-only/env-gated → excluded.) All 3 tests pass.
- **Live verification** (running sandbox; copied the fixed manifest into `/sandbox/build/genomeclaw`, clean `openclaw plugins uninstall --force` + `openclaw plugins install --link`, restarted the loopback+auth-none gateway):
  - Gateway now logs **`http server listening (1 plugin: genomeclaw; 4.5s)`** (was `0 plugins`).
  - Agent probe (`openclaw agent --json --agent genomeclaw`): **`toolSummary={"calls":1,"tools":["genomeclaw_status"],"failures":0}`**, `thinking=xhigh`. The tool executed and reached the host service; reply: *"genomeclaw_status reached the GenomeClaw host, but /v1/health returned HTTP 503"* — the 503 is the SEPARATE known v0.3/v0.4 schema-staleness (host data needs a `v0.4` rebuild), orthogonal to the plugin fix. The tool round-trip itself succeeded.
  - The in-place test used the exact mechanism the Dockerfile bakes (`openclaw plugins install /sandbox/build/genomeclaw --link` with the manifest at that path), so it faithfully represents the rebuilt image. A rebuild+onboard confirmation is recommended as part of the Phase 5 gate.
- **No Dockerfile change needed for Facet B** — the image already `COPY`s `openclaw.plugin.json`, so a rebuild bakes the new contract automatically.
- **No new regressions**: toolkit invariant suite 64 passed / 29 skipped / **1 failed**, and the 1 failure (`test_invP002_policy_preset_targets_host_openshell_internal`: asserts port 8643 but repo moved to 8645) is **pre-existing and unrelated** (reads `policy-preset.yaml`, which this change does not touch). Flag for a separate follow-up.

**Facet B = RESOLVED.** Remaining for Phase 3: Facet A (bake gateway token so the supervised/dashboard path starts) + credential hand-off + full muscle-question smoke. Facet A involves a security-posture decision (gateway token) the user wants run past `privacy-safety-reviewer`.

#### Facet A split + A1 LANDED, privacy-safety review, A2 deferred (2026-05-30)

Investigating Facet A revealed it is two sub-problems:

**Facet A1 — gateway bind refusal — ✅ FIXED + LANDED.** The fix is NOT a token (the user's pre-approved approach) — it is simpler and secret-free: bake `gateway.bind=loopback`. Empirically, with `gateway.bind=loopback` in config, nemoclaw's flag-less supervised launch `openclaw gateway run --port 18789` starts cleanly (binds `127.0.0.1`/`[::1]` only — confirmed via `ss -lntp`, so openclaw#65619 is not triggered here), loads `1 plugin: genomeclaw`. Implemented:
- Dockerfile: added `openclaw config set gateway.bind loopback` to the persistent-path config bake (with a comment explaining the v0.0.50 guard + why no token is baked).
- Tests: `test_invP001_baked_gateway_bind_is_loopback` + `test_invP001_no_static_gateway_token_baked` (regression guard against a future baked token). Rebuilt `genomeclaw/sandbox:phase3` → baked `gateway: {"mode":"local","bind":"loopback"}`, manifest `activation.onStartup=true` + 9 `contracts.tools`. **All 12 baked-config / manifest / canonical-path tests pass against the rebuilt image.**

**Facet A2 — credential hand-off — DEFERRED (the original Phase 3 core; needs care).** With A1 fixed, nemoclaw's recovery now progresses past the bind guard but fails at: `SecretRefResolutionError: Environment variable "OPENAI_API_KEY" is missing or empty`. The baked `models.providers.openai.apiKey` is an ENV ref; nemoclaw's recovery relaunch (`~/.nemoclaw/source/dist/lib/agent/runtime.js:196`, `openclaw gateway run --port`) sources only `/tmp/nemoclaw-proxy-env.sh`, NOT the OpenAI key. `nemoclaw credentials list` shows OpenAI IS registered ("openai-api"), so the supervisor *has* the credential — the gap is wiring it into the supervised gateway's env on every (re)start.

**privacy-safety-reviewer verdict (full review in this session's transcript)** — *Accept A1-loopback with required guardrails; A2 has a HIGH-severity finding*:
- **A1**: loopback+auth=none is the correct default — do NOT bake a token (a static baked token persists in image history, same INV-P003 risk class as a baked API key, and adds no capability against an in-container attacker who can already read files). A bind=auto dashboard token, if ever needed, must be runtime-generated + env-injected, never baked. ✅ matches what landed.
- **A2 [HIGH]**: the onboard's Step 6 writes the **literal OpenAI key** into `/sandbox/.openclaw/agents/genomeclaw/agent/auth-profiles.json` (plaintext, persistent, not 0600, would enter any `docker commit`). This undermines the Dockerfile's correct env-ref design. **Preferred fix**: rely on nemoclaw's credential store (env-only, gateway is system of record) and DELETE the literal-key write; if unavailable, enforce `chmod 0600` + comment + a permissions test.
- **Required guardrail tests for A2**: (1) gateway bound-address is 127.0.0.1 [done manually; make it a needs_sandbox test]; (2) `auth-profiles.json` is 0600 or absent; (3) no static `gateway.auth.token` baked [done]; (4) extend the INV-P003 argv test so `OPENAI_API_KEY` appears only in `-e` env positions; (5) re-run INV-P003 + INV-P001 egress tests.
- Other: audit `/tmp/gateway.log` for tool-call payloads (add `--log-level warn` if genome-derived data appears); confirm nemoclaw's port-forward actually reaches a loopback gateway (functional + privacy overlap).

**A2 is the genuine Phase 3 credential redesign** — it needs (a) empirical confirmation that nemoclaw's credential store injects `OPENAI_API_KEY` into the supervised gateway env, (b) the onboard-script rewrite (delete Step 7b's manual gateway launch + the literal-key auth-profiles.json write, hand the gateway to nemoclaw's supervisor), and (c) the guardrail tests above. Pausing before A2 to confirm direction with the user.

#### A2 FEASIBILITY INVESTIGATION (2026-05-30, user-requested) → FEASIBLE; intended design found

Traced the nemoclaw/OpenShell credential architecture in `~/.nemoclaw/source/dist`:
- Both primary and recovery gateway launches go through the same `startGatewayWithOptions` (`onboard.js:2841`; `startGatewayForRecovery` → same). So the recovery failure I observed (`OPENAI_API_KEY missing`) is representative of the primary supervised launch — nemoclaw's native gateway lifecycle does NOT put the raw OpenAI key in the in-sandbox gateway env.
- **That is by design.** `onboard.js:4150-4152`: *"OpenShell providers — the gateway injects them as **placeholders** and the **L7 proxy rewrites Authorization headers with real secrets at egress**. See: crates/openshell-sandbox/src/secrets.rs (placeholder rewriting)."* And `oauth-device-code.js:17`: *"sandbox receives only the normal OpenShell inference placeholder, never raw [key]."* `verify-deployment.js`: the sandbox reaches `inference.local` and the proxy responds.
- So the INTENDED flow: the provider credential is registered with OpenShell (`upsertProvider` → `nemoclaw credentials list` shows `openai-api`); the in-sandbox gateway holds only a **placeholder**; calls egress through OpenShell's **L7 proxy** which rewrites the `Authorization` header with the real secret. The gateway never needs the raw key in its env → it starts cleanly and survives `nemoclaw recover`.
- **Empirical support**: the working `post-v123` run used `models.json baseUrl=https://inference.local/v1`, proving the inference.local proxy path reaches OpenAI. Our onboard Step 7 already routes the agent baseUrl → inference.local.

**Why our sandbox fights the design** (the 3 workarounds to remove): (Step 6) writes the literal key into `auth-profiles.json`; (Dockerfile) bakes `models.providers.openai.apiKey` as an env-ref to the *real* `OPENAI_API_KEY` (→ the gateway treats it as a required secret and fails recovery); (Step 7b) manually launches the gateway with `-e OPENAI_API_KEY`. All three predate the canonical-path + bind=loopback fixes and were workarounds for the old `/opt` EACCES / exec breakage.

**FEASIBILITY VERDICT: A2's clean fix is FEASIBLE and is the documented OpenShell design.** Recommended A2 implementation:
1. Rely on `nemoclaw onboard`'s native provider flow (`NEMOCLAW_PROVIDER=openai` + `OPENAI_API_KEY` in the onboarding shell env → `upsertProvider` registers it with OpenShell). The onboard script already exports these.
2. Configure the gateway provider to route via `inference.local` with the OpenShell-injected **placeholder** (not a real-key env-ref). Let the L7 proxy attach the real secret at egress.
3. Delete onboard Step 6 (literal-key `auth-profiles.json`) and Step 7b (manual keyed gateway launch); let nemoclaw's supervisor own the gateway (now startable thanks to A1's bind=loopback).
4. Verification (the empirical confirmation step): after the rewrite, launch the gateway via nemoclaw's native path WITHOUT `-e OPENAI_API_KEY`, confirm it starts (no `SecretRefResolutionError`) AND an agent LLM turn succeeds (proving the proxy attaches the real key). This is the gate that proves the placeholder+proxy path works end-to-end on v0.0.50.

Remaining unknown to settle during implementation: the exact OpenShell-injected placeholder value/shape the gateway provider must carry (OpenShell decides it; hand-setting a random literal won't be rewritten). This is why the native onboard provider flow — not a manual config edit — is the correct mechanism. Guardrail tests from the privacy review still apply (auth-profiles.json absent/0600; no real key in any layer; bound-address loopback; INV-P003 env-position).

#### A2 IMPLEMENTED (pragmatic, local-Docker-appropriate) + VERIFIED END-TO-END (2026-05-30)

The full native path proved NOT operational on local Docker (empirically: `inference.local` does not resolve in the sandbox — `curl` error 6, no DNS — and no model-router process runs; `nemoclaw inference set` configures the route but its sandbox-sync uses a Kubernetes `kubectl exec` path that fails locally → `No such container: openshell-cluster-nemoclaw`). So nemoclaw cannot self-own the gateway credential via the L7 proxy here. That is the upstream/local-Docker limitation behind the original manual workarounds.

**What WAS implemented (the achievable, high-value fix — addresses the reviewer's HIGH finding):**
- **Deleted onboard Step 6** (the literal-key `auth-profiles.json` write). Empirically verified the agent completes an LLM turn with NO auth-profiles.json — it resolves the credential from the gateway's `models.providers.openai.apiKey` env-ref (key supplied via Step 7b `docker exec -e`, INV-P003-clean). So the durable plaintext-secret file is gone with zero functional loss.
- **Deleted onboard Step 7** (the dead `inference.local` rewrite of the agent's models.json — non-functional locally; the agent uses the gateway provider).
- **Kept Step 7b** (gateway launch with `docker exec -e OPENAI_API_KEY`) — still required because the native proxy path is unavailable locally. Now works because A1's baked `gateway.bind=loopback` lets the launch bind 127.0.0.1.
- **Tests** (`test_invP003_onboard_script_no_secrets_in_argv.py`): replaced the obsolete "writes auth-profile via stdin" test with `test_invP003_onboard_writes_no_literal_key_to_authprofiles` (no `cat >`/`tee` into auth-profiles.json) + `test_invP003_openai_key_only_in_env_positions` (the key VALUE expands only inside a `docker exec -e OPENAI_API_KEY=...` flag; escaped `\$` help-echoes excluded). 4/4 pass.

**End-to-end verification on a CLEAN re-onboard** (rebuilt image + edited script, `./scripts/onboard-sandbox.sh`, exit 0):
- `auth-profiles.json` ABSENT in the agent dir (only `models.json`). ✓
- Gateway bound `127.0.0.1`/`[::1]` only (loopback). ✓
- Gateway loads `1 plugin: genomeclaw`. ✓
- Onboard step-8 smoke: `toolSummary={"calls":1,"tools":["genomeclaw_status"]}` — agent calls the genomeclaw tool with no auth-profiles.json and no inference.local. ✓

**Local-Docker recovery limitation (documented for Phase 4 / upstream follow-up)**: `nemoclaw recover` cannot self-restore the gateway credential on local Docker (the recovery relaunch doesn't inject `OPENAI_API_KEY`, and the native proxy path is absent). Recovery-after-gateway-death is handled by re-running the keyed launch via `scripts/sandbox-up.sh` (Phase 4). The full "nemoclaw owns the credential via the L7 proxy" end state requires the OpenShell inference-routing infra (inference.local DNS + model-router) — track as an upstream/infra follow-up.

**A2 = RESOLVED to the extent feasible on local Docker.** The HIGH-severity plaintext-key finding is fixed; the credential travels env-only (INV-P003-clean); the gateway/agent work end-to-end.

**Sandbox state**: a working loopback gateway (key in env) is running with `1 plugin: genomeclaw`; ask.sh works for tool calls (host service returns 503 until a v0.4 derived rebuild). The running sandbox is still the earlier `port-8645` onboard image with in-place patches; `genomeclaw/sandbox:phase3` is the rebuilt clean artifact.

---

### Phase 3: Gateway Lifecycle + Credential System Hand-Off
**Status**: Pending
**Started**:
**Completed**:

---

### Phase 4: Simplify Onboard Script + Recovery Wrapper
**Status**: Complete (reconciled to local-Docker reality)
**Started**: 2026-05-30
**Completed**: 2026-05-30

**Premise reconciled**: the original Phase 4 ("delegate recovery to `nemoclaw recover`") is invalid on local Docker — Phase 3 proved `nemoclaw recover` can't inject the credential there. So the keyed `docker exec -e OPENAI_API_KEY` restart (INV-P003-clean) is the sanctioned local recovery; `sandbox-up.sh` now tries `nemoclaw genomeclaw connect --probe-only` best-effort first (supervised path when available, e.g. remote) then falls through to the keyed restart.

**Changes (GREEN)**:
- `scripts/sandbox-up.sh`: Step 2 plugin check now targets the canonical `/sandbox/build/genomeclaw/dist/index.js` (was the stale `/opt/genomeclaw` EACCES grep); gateway liveness is PORT-based (`ss … :18789`, via a `gateway_listening()` helper) instead of the fragile `grep openclaw-gatew`; added the best-effort supervised-recover attempt before the keyed restart, with comments documenting the local-Docker credential limitation.
- `scripts/onboard-sandbox.sh`: Step 7b wait-loop switched to the same port-based check.
- Step 8 smoke is left as the docker-exec **agent** smoke (a superset of the plan's suggested HTTP probe — it exercises the agent + a `genomeclaw_*` tool, INV-V001-clean, not log-grep).

**Tests**: `packages/toolkit/tests/integration/test_phase4_script_shape.py` (5 structural: no legacy `/opt` ref in either script; port-based detection; keyed restart env-not-argv [INV-P003]; best-effort recover wired) — 5/5 pass. INV-P003 onboard tests still pass (9/9 combined). No new regressions (only the pre-existing `test_invP002_policy_preset` 8643/8645 failure).

**Recovery smoke (manual, INV-V001 structural — captured here rather than a fragile live pytest)**:
```text
# kill the gateway, then run sandbox-up.sh:
$ docker exec --user sandbox <CID> pkill -9 openclaw   → PORT FREE (gateway down)
$ ./scripts/sandbox-up.sh
  [sandbox-up] gateway down — trying supervised recovery (nemoclaw connect --probe-only, best-effort)
  [sandbox-up] starting gateway directly with OPENAI_API_KEY in env (never argv; INV-P003)
  [sandbox-up] gateway ready
$ ss -lntp | grep :18789   → 127.0.0.1:18789 (loopback), new pid
  gateway log: "http server listening (1 plugin: genomeclaw)"
$ openclaw agent --agent genomeclaw -m "Call genomeclaw_status now."
  → toolSummary={"calls":1,"tools":["genomeclaw_status"],"failures":0}, stop
```
Recovery restores a **working** agent (not just a listening port). `nemoclaw recover` itself remains non-functional on local Docker (documented; tracked as upstream/infra follow-up).

---

### Phase 5: Verification Gate
**Status**: Surface gate PASSED; data-grounded gate BLOCKED on infra (v0.4 derived-store rebuild not feasible on this host)
**Started**: 2026-05-30
**Completed**: surface portions 2026-05-30; full data gate deferred (see blocker)

**v0.4 rebuild BLOCKER (hard infra, outside this plan's plumbing scope)**: the host service needs a derived store at the toolkit's schema version, but none exists and a rebuild can't run here:
- No `v0.4` derived run exists anywhere; existing data is `v0.3`. Committed `SCHEMA_VERSION` is `v0.2`; the working tree bumps it to `v0.4` (uncommitted in-flight work). So NO toolkit version matches the existing data — a rebuild is mandatory to serve anything → `/v1/health` returns 503 `schema_version_mismatch`.
- **Docker pipeline blocked**: colima does not mount `/Volumes/Genome_Work` into its VM (`docker run -v /Volumes/Genome_Work:/probe alpine ls /probe/genomeclaw` → not found), so the toolkit container can't reach the 212MB VCF / reference.
- **Native pipeline blocked**: `bcftools`, `tabix`, `bgzip`, `vep`, `vcfanno`, `samtools`, `nextflow` are all MISSING on PATH (`host doctor` crashes on missing nextflow).
- Rebuilding requires reconfiguring colima (disruptive — stops colima/kills the sandbox; external-volume mounts are finicky) or installing the full bio toolchain + VEP cache + datasets (hours, GBs). Both are large infra tasks beyond this plan. **Follow-up: run the v0.4 pipeline on the canonical pipeline host (or after wiring colima mounts), then re-run the data-grounded smoke.**

**Surface gate — PASSED (the plan's actual goal: the agent invokes `genomeclaw_*` tools end-to-end)**:
- **Full regression suite**: `1175 passed, 163 skipped, 8 failed`. All 8 failures are **pre-existing, from the broader uncommitted in-flight work — NOT regressions from this plan's commits** (verified by file-targeting): `test_invP001_plugin_default_egress` ×2 read `src/index.ts` (in-flight modified); `test_prs_compute_config_write` ×4 target `service/pgs_compute_config.py`/`prep/pgs.py` (in-flight); `test_invP002_policy_preset` is the known 8643/8645; `test_host_service_toolkit_image` is the colima-mount/in-flight area. My commits touch only the manifest, Dockerfile, the two scripts, and the (passing) test files I added.
- **spec Q4**: no test references `/opt/genomeclaw` as a *live* path (the hits are comments + absence-assertions like `test_invD011` asserting `/opt` is gone).
- **ask.sh muscle-question smoke** (`docs/reports/demo-2026-05-30-logs/give-personalized-recommendations-…trace.json`): **22 tool calls, 4 distinct `genomeclaw_*` tools** (`genomeclaw_status, _findings, _gene, _pgs_list`), `failures: 0` — vs the Phase 2 baseline of **zero** genomeclaw tools. The reply (2615 chars) is a **faithful synthesis**: it honestly attributes the gap to the 503 ("the live GenomeClaw service is not healthy… I don't have your actual ACTN3/ACE/FTO… data"), does NOT fabricate genome data, lists what it would query, and gives a non-personalized baseline. INV-A005 (synthesis over tool data) + no confabulation upheld.
- **A1 completed (`gateway.auth.mode=none`)**: the trace showed the Phase-4-recovered gateway still emitted `unauthorized: gateway token missing` (bind=loopback alone auto-generates a per-startup token). Baked `gateway.auth.mode=none` alongside `gateway.bind=loopback`; verified the gateway-ROUTED agent (no `--local`) now connects token-free, calls `genomeclaw_status` (`failures:0`, `thinking=xhigh`). Rebuilt `genomeclaw/sandbox:phase5` → baked `gateway: {mode:local, bind:loopback, auth:{mode:none}}`; new guard `test_invP001_baked_gateway_auth_mode_is_none` + 9/9 baked-config tests pass. This makes the dashboard/TUI/connect (gateway-routed) surfaces viable token-free on loopback — though their full end-to-end verification still needs the v0.4 data + manual browser/interactive testing.

**Dashboard / TUI manual gates**: deferred — they require the v0.4 data store (blocked) AND manual browser/interactive interaction. The gateway-routed connectivity they depend on is now token-free (A1 complete), so they are unblocked on the *auth/plumbing* axis; only the data axis remains.

---

### Phase 6: Documentation Cleanup + Optional Invariant Promotion
**Status**: Reconciled — premise invalidated by Phase 5; doc edits + INV-D011 registry entry SPECIFIED + handed off (in-flight doc WIP blocks clean commit). INV-D011 enforced by committed test.
**Started**: 2026-05-30
**Completed**: spec + handoff 2026-05-30

**Two findings reshaped Phase 6** (full detail in [phases/phase-6.md](phases/phase-6.md) "Reconciliation"):
1. **Premise invalidated**: Phase 6 assumed "dashboard/connect/TUI now work → remove docker-exec guidance, make them primary." Phase 5 proved the opposite on local Docker — `docker exec`/`ask.sh` REMAINS canonical (embedded agent + keyed gateway); dashboard/TUI are plumbing-fixed (canonical path + loopback-tokenless gateway) but data-blocked (host 503) + manual. So the sweeping doc rewrite is WITHDRAWN; the in-flight `CLAUDE.md` "Running the Agent Locally" is already accurate.
2. **Clean-commit blocker**: README/CLAUDE.md/test-engineer.md/INVARIANTS.md all carry substantial uncommitted in-flight WIP that is NOT this plan's (INVARIANTS.md alone is +224 lines of other invariants; the in-flight README diff even *adds* a stale `/opt/genomeclaw` probe line overlapping the exact troubleshooting sections this phase would edit). Editing+committing them would bundle the maintainer's WIP. So the doc edits are **specified + handed off**, not applied here.

**What was done in Phase 6**:
- Reconciled `phases/phase-6.md` with the above + the residual doc-edit handoff list (mainly: README's stale `/opt/genomeclaw`-EACCES troubleshooting entries describe a problem the migration FIXED → update to `/sandbox/build/genomeclaw`; reconcile the in-flight README `sandbox-up.sh` description to its new canonical-path + port-based behavior).
- **INV-D011**: enforced by the committed `test_invD011_plugin_install_path.py` (path + version-tag pin) + `test_plugin_manifest_tool_contract.py` (cold-metadata tool contract), green through Phases 2–5. The INVARIANTS.md **registry entry text is written in phase-6.md** for the maintainer to paste once INVARIANTS.md's +224-line WIP settles (a Version bump + Invariant Index entry). De-facto promoted at the test level; registry entry deferred.

**Not done (handed off / external blockers)** — see development-plan "Deferred Follow-ups":
- README/CLAUDE.md/test-engineer.md doc edits (blocked by in-flight doc WIP).
- INV-D011 INVARIANTS.md registry entry (blocked by INVARIANTS.md WIP).
- Phase 5 data-grounded smoke + dashboard/TUI manual gates (blocked by the v0.4 derived-store rebuild → needs a pipeline host / colima mounts / native bio tools).

---

## Key Decisions

### Decision 1: Plan target path is `/sandbox/.openclaw/extensions/genomeclaw/`
**Date**: 2026-05-29 (revised after Phase 1 probe)
**Context**: `/opt/genomeclaw/` is outside the Landlock baseline → all NemoClaw-managed surfaces fail with EACCES. Phase 1 probe of `sandbox-base:v0.0.50` found `/sandbox/.openclaw/extensions/` is the direct writable canonical dir; `/sandbox/.openclaw-data/` does NOT exist in this base image (the symlink pattern referenced in the development-plan is from an older NemoClaw layout).
**Decision**: Migrate to `/sandbox/.openclaw/extensions/genomeclaw/` (direct path; no `.openclaw-data` symlink needed for v0.0.50).
**Rationale**: It's inside the Landlock RW baseline (`/sandbox`); matches the structural layout the host CLI's own probe of v0.0.50 returned; the docker-exec workaround is no longer load-bearing once this lands. Upstream reference: `openclaw plugins list` output from probe shows `~/.openclaw/npm/node_modules/*` as the install destination of `openclaw plugins install <path> --link`, with `Source roots:` ready to surface a `user:` root once an extension is registered.
**Alternatives Considered**:
- Extend the sandbox's filesystem policy to allow `/opt/genomeclaw/` — rejected: requires destroy+recreate of the sandbox + ongoing policy maintenance; we'd be inventing a custom convention upstream doesn't share.
- Keep `/opt/` but only use docker-exec everywhere — rejected: the dashboard, `nemoclaw connect`, and TUI all use the OpenShell runtime; we'd be permanently giving up the documented UX.
**Affected Invariants**: Proposed `INV-D011`; possibly tightens `INV-V001` story (structural inspection).

### Decision 2: Base image pinned by `:v<nemoclaw-version>` tag (revised after Phase 1)
**Date**: 2026-05-29 (revised)
**Context**: `ghcr.io/nvidia/nemoclaw/sandbox-base:latest` resolved to a cached digest from 2026.4.24 while the host nemoclaw is v0.0.50 (which ships OpenClaw 2026.5.18), producing the port mismatch. Phase 1 probe found that the host CLI's installer already publishes a per-version tag: `ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` is locally cached and contains OpenClaw 2026.5.18 (matches host).
**Decision**: Pin by `:v<nemoclaw-version>` tag in the Dockerfile (i.e., `:v0.0.50` for the current host). Record the resolved multi-arch index digest in a Dockerfile comment so reviewers can verify. Bump cadence: whenever `nemoclaw --version` is upgraded on the host, update the Dockerfile pin to match in the same change.
**Rationale**: Tag-based pulls + a local image cache are an unsafe combination only when the tag is mutable (`:latest`). Version-tagged digests on GHCR are stable per upstream practice. Pinning by `:vX.Y.Z` keeps the cross-arch index portable (works on amd64 + arm64 without separate digest pins) and makes the version a code change reviewers can see. Documenting the digest in a comment provides the structural-inspection breadcrumb.
**Alternatives Considered**:
- Full `@sha256:` digest pin: portable per-arch but requires picking amd64 OR arm64; complicates the multi-host case. Rejected for now.
- Always `--pull` on build with `:latest`: doesn't solve the case where a user upgrades `nemoclaw` after the last build; the host/image versions can still drift. Rejected.
**Affected Invariants**: None directly. Adds a maintenance discipline. Recorded as an entry in `Open Risks & Follow-ups` (already noted in development-plan.md).

### Decision 3: NemoClaw owns the gateway lifecycle
**Date**: 2026-05-29
**Context**: `docker exec -d openclaw gateway run` runs the gateway outside NemoClaw's supervisor → recovery fails because the credential reloader doesn't have the key.
**Decision**: Hand the key to NemoClaw's credential system at onboard; remove Step 7b from `onboard-sandbox.sh`.
**Rationale**: Aligns with upstream's supported flow. Makes `nemoclaw recover` actually recover. Doesn't compromise `INV-P003` (verified in Phase 3 RED).
**Alternatives Considered**: Keep docker-exec + add a sidecar to restart the gateway on death — rejected: yet another workaround layer; doesn't fix the dashboard / TUI / connect surfaces; we'd still own ongoing maintenance NemoClaw should own.
**Affected Invariants**: `INV-P003` re-verified by existing discovery test.

---

## Files Modified

### Created
- [spec.md](spec.md)
- [development-plan.md](development-plan.md)
- [work-notes.md](work-notes.md)
- [phases/phase-1.md](phases/phase-1.md)
- [phases/phase-2.md](phases/phase-2.md)
- [phases/phase-3.md](phases/phase-3.md)
- [phases/phase-4.md](phases/phase-4.md)
- [phases/phase-5.md](phases/phase-5.md)
- [phases/phase-6.md](phases/phase-6.md)

### Modified
(none yet — implementation hasn't started)

### Deleted
(none yet)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Promote `INV-D011` *Plugin Install Path Follows NemoClaw's Canonical Pattern* — after Phase 5 confirms the discipline holds.

### Other Documentation
- [ ] [README.md](../../../../README.md) — § Sandbox setup, § Troubleshooting (Phase 6)
- [ ] [CLAUDE.md](../../../../CLAUDE.md) — § Running the Agent Locally (Phase 6)
- [ ] [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) — workaround references (Phase 6)

---

## Open Risks & Follow-ups

- **Upstream `nemoclaw recover` reliability**: tonight (2026-05-29) it failed. The failure may be entirely caused by root causes 1–3; if recovery still fails after Phase 3, file an upstream bug and keep a docker-exec final-fallback in `sandbox-up.sh`.
- **NemoClaw credential storage audit**: Phase 3 RED must check file permissions, masking, and logging behavior of the credential store.
- **Plugin auto-discovery vs explicit install**: Phase 1 audit will resolve. If `openclaw plugins install` is still needed, Phase 2 retains it; otherwise the Dockerfile loses a step.
- **Base-image SHA bump cadence**: needs a documented review point any time we upgrade the host `nemoclaw` CLI.
- **Integration test references to `/opt/genomeclaw/`** (spec Q4): Phase 5 audit will surface; small follow-up if so.

# Online Research — OpenClaw plugin gateway-visibility + gateway auth/bind

**Date**: 2026-05-30
**Context**: Phase 2 smoke root-caused two coupled gateway-layer failures (work-notes Phase 2, "Facet A"/"Facet B"). This note captures the online research the user requested into best practices / common patterns for both, so Phase 3 implements the *documented* OpenClaw contract rather than a reverse-engineered workaround.

> Source distinction: **OpenShell** (NVIDIA, `docs.nvidia.com/openshell`) is the sandbox layer; **OpenClaw** (`docs.openclaw.ai`) is the agent + gateway that runs *inside* the sandbox. Our plugin-loading + gateway-auth problems are **OpenClaw** concerns. The NVIDIA OpenShell docs only cover baking an image + `default_image`, not OpenClaw plugin/tool discovery.

---

## Facet B — why the gateway surfaces 0 tools, and the documented fix

### Root cause (confirmed by docs): tools must be declared in **cold manifest metadata**, not only registered at runtime

OpenClaw builds the agent/gateway **tool catalog from cold metadata** — it reads each plugin's `openclaw.plugin.json` manifest *without importing the plugin runtime*, to learn which plugin owns which tool. Per the docs:

> "`contracts.tools` is the important discovery contract. It tells OpenClaw which plugin owns each tool without loading every installed plugin runtime."
> "OpenClaw discovers installed plugins from cold metadata and must be able to read the plugin manifest before importing plugin runtime code." — [agent-tools / building-plugins]

Our plugin calls `api.registerTool(...)` at **runtime** (in `src/index.ts`), and our `openclaw.plugin.json` has **no `contracts` block and no `activation` block**. Therefore:
- CLI / embedded loads (which *do* import the runtime) execute `registerTool` and log `GenomeClaw plugin registered (9 tools)`.
- The **gateway** never imports the runtime to build its catalog — it reads cold metadata, finds no `contracts.tools`, and surfaces **0 tools**. This is exactly the observed `0 plugins` / `genomeclaw_status: command not found`.

This is **intended OpenClaw behavior**, not a bug. The matching GitHub reports — [#61790](https://github.com/openclaw/openclaw/issues/61790) (closed *not planned*), [#47683](https://github.com/openclaw/openclaw/issues/47683), [#50328](https://github.com/openclaw/openclaw/issues/50328) — are all "registerTool tools not visible to agents"; the resolution is to declare the tools in the manifest.

> Reconciles the "OLD `/opt` image worked" mystery: the cached base was OpenClaw **2026.4.24**, which evidently surfaced runtime-registered tools eagerly. **2026.5.18** (our `:v0.0.50` pin) moved to cold-metadata discovery, so the missing `contracts.tools` now matters. The fix is forward-compatible.

### The documented manifest contract

`openclaw.plugin.json` must declare, as **cold metadata**:

```json
{
  "id": "genomeclaw",
  "name": "GenomeClaw",
  "version": "0.0.1",
  "description": "...",
  "configSchema": { /* unchanged */ },
  "activation": { "onStartup": true },
  "contracts": { "tools": ["genomeclaw_status", "genomeclaw_findings", "...all registered tool names..."] }
}
```

- **`contracts.tools`** — array of tool *name* strings. Must match every name passed to `api.registerTool({ name: ... })`. (Our source registers ~9–13: `genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_gene`, `genomeclaw_pgs_list`, `genomeclaw_pgs_get`, `genomeclaw_pgs_compute`, `genomeclaw_pgs_compute_status`, `genomeclaw_report`, `genomeclaw_toolkit`, plus test-only `genomeclaw_ssrf_probe_batch` — declare exactly the set actually registered; the live gateway logs "9 tools".)
- **`activation.onStartup: true`** — tells the **gateway** to load the plugin at startup (otherwise it can stay lazy and never surface). Docs: *"Set `activation.onStartup` intentionally. This example starts on Gateway startup."*
- Registration pattern stays `definePluginEntry` + `api.registerTool(...)` (NOT `defineChannelPluginEntry`) — which our plugin already uses.
- Keep `@sinclair/typebox` in `dependencies` (runtime import) — already done.

### Keeping manifest ↔ source in sync

Docs mention a generator (`openclaw plugins build`) that regenerates `openclaw.plugin.json` from source after changing plugin id/name/description/config schema/activation/tool names. If available in v0.0.50, prefer running it in the build so `contracts.tools` can't drift from the `registerTool` calls. Otherwise, add a test asserting the manifest `contracts.tools` set equals the set of registered tool names (a cheap structural guard, INV-V001-clean).

### Install location — secondary to the manifest

For **bundled / source-checkout** plugins, OpenClaw "discovers source-checkout plugin packages from the `extensions/*` workspace, making them available to both CLI and Gateway." `openclaw plugins install -l <path>` (link, dev) and `openclaw plugins install <path>` (copy → `~/.openclaw/extensions/`) are the local-dev installers; `openclaw plugins install clawhub:<org>/<pkg>` is the published path. Our empirical finding (work-notes) that the manual gateway only loaded `npm/node_modules` is most likely a *symptom of the missing `contracts.tools`* (no cold metadata to discover), not an independent location rule — **re-test install location only after the manifest contract is fixed.**

---

## Facet A — gateway bind/auth in a container (documented patterns)

"Refusing to bind gateway to auto without auth" is documented behavior: **non-loopback binds (`auto`, `lan`, `tailnet`, `custom`) require an auth path.** In a container the gateway defaults to `bind=auto` (0.0.0.0) for port-forward compatibility, so it needs auth. Two supported patterns:

1. **Loopback-only** (simplest, for the `ask.sh`/local path): `gateway.bind: loopback`. Loopback needs no token; in fact `doctor`/`configure` adding auth to a loopback gateway is a known nuisance ([#18225](https://github.com/openclaw/openclaw/issues/18225)). Caveat: a known bug where `bind=loopback` resolves to 0.0.0.0 and refuses / 1006-on-health on some setups ([#65619](https://github.com/openclaw/openclaw/issues/65619)) — matches our intermittent `1006 abnormal closure`.
2. **Token auth** (required when `bind=auto` for the dashboard/TUI port-forward):
   - `gateway.auth.mode: "token"` + `gateway.auth.token: "<secret>"`, **or** `OPENCLAW_GATEWAY_TOKEN=<secret>` env.
   - All clients (embedded agent, dashboard, TUI) must present the same token.
   - Note: legacy key `gateway.token` does **not** replace `gateway.auth.token`.
   - `trusted-proxy` mode is incompatible with `bind=loopback` ([#20073](https://github.com/openclaw/openclaw/issues/20073)).

Confirmed empirically (work-notes): `gateway.auth.mode=none` in config does **not** satisfy the `bind=auto` guard — only `--bind loopback` or a token does.

### Recommended for GenomeClaw (Phase 3)

- **nemoclaw launches the supervised gateway as `openclaw gateway run --port <port>`** (bind=auto) — so to make the **dashboard/TUI/connect** path work we must bake a **token**: `gateway.auth.mode=token` + persisted `gateway.auth.token`, and make sure the agent/dashboard clients use it. INV-P003: write the token into the baked config file at build time; never on argv. (The token is a gateway access secret, not the OpenAI key — privacy-safety-reviewer should still weigh in.)
- The **loopback + auth=none** path (what `ask.sh` uses via `docker exec`) remains valid as the scripted bypass.

---

## Net recommendation for Phase 3 (priority order)

1. **Fix Facet B first — add the manifest tool contract** (`contracts.tools` + `activation.onStartup: true`) to `packages/nemoclaw-plugin/openclaw.plugin.json` (or generate it via `openclaw plugins build`). This is the highest-probability fix for "agent has no genomeclaw tools" and is independent of the gateway start path — it can be verified even with the loopback+auth-none gateway already running.
2. **Fix Facet A — bake a gateway token** (`gateway.auth.mode=token` + persisted token) so nemoclaw's supervised `gateway run --port` (bind=auto) starts and the dashboard/TUI/connect surfaces come up; keep loopback+auth-none for `ask.sh`.
3. Re-run the muscle-question smoke (ask.sh + a supervised-path probe). Add a structural test that `contracts.tools` ⊇ the registered tool names.

---

## Sources

- OpenClaw — Building plugins: <https://docs.openclaw.ai/plugins/building-plugins>
- OpenClaw — Tool plugins: <https://docs.openclaw.ai/plugins/tool-plugins>
- OpenClaw — Registering agent tools: <https://docs.openclaw.ai/plugins/agent-tools>
- OpenClaw — Plugins overview: <https://docs.openclaw.ai/tools/plugin>
- OpenClaw — Gateway troubleshooting: <https://docs.openclaw.ai/gateway/troubleshooting>
- GitHub openclaw#61790 — registerTool tools not visible to agents: <https://github.com/openclaw/openclaw/issues/61790>
- GitHub openclaw#47683 — registerTool tools not surfaced to agent runtime: <https://github.com/openclaw/openclaw/issues/47683>
- GitHub openclaw#50328 — registerTool tools not available in agent runtime: <https://github.com/openclaw/openclaw/issues/50328>
- GitHub openclaw#18225 — doctor adds unnecessary auth to loopback gateway: <https://github.com/openclaw/openclaw/issues/18225>
- GitHub openclaw#65619 — bind=loopback resolves to 0.0.0.0 and refuses (1006 on health): <https://github.com/openclaw/openclaw/issues/65619>
- GitHub openclaw#20073 — trusted-proxy + loopback incompatible: <https://github.com/openclaw/openclaw/issues/20073>
- NVIDIA OpenShell — Manage sandboxes (bake custom image): <https://docs.nvidia.com/openshell/sandboxes/manage-sandboxes>
- NVIDIA OpenShell — Gateway config reference: <https://docs.nvidia.com/openshell/reference/gateway-config>

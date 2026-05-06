# @genomeclaw/nemoclaw-plugin

> **Status**: scaffolding (v0 — pre-implementation, no live build yet)

This package is the **NemoClaw / OpenClaw plugin** half of GenomeClaw. It runs inside an OpenShell sandbox managed by NemoClaw on the project owner's host (any Linux or macOS environment where NemoClaw and the bioinformatics tools install).

It does not contain any genomics logic. The genomics work lives on the host (in [`packages/toolkit/`](../toolkit/) — pending). This package only registers agent-callable commands and proxies them to the host-side `genomeclaw-service` over HTTP.

For the architectural rationale, see [`docs/reference/architecture.md`](../../docs/reference/architecture.md).

---

## Layout

```text
packages/nemoclaw-plugin/
├── README.md                  ← this file
├── package.json               ← Node 22 / TypeScript package
├── tsconfig.json
├── openclaw.plugin.json       ← OpenClaw plugin manifest (id, version, configSchema)
├── policy-preset.yaml         ← OpenShell network policy preset (genomeclaw)
├── src/
│   └── index.ts               ← Plugin entrypoint — registers tools, proxies HTTP
└── sandbox/
    └── Dockerfile             ← Sandbox image that bakes the plugin in
```

---

## How it fits into the stack

```text
LLM (OpenAI gpt-5.4 — or any NemoClaw-supported provider)
  ⇕  via inference.local (OpenShell L7 proxy)
SANDBOX
├── OpenClaw agent
└── @genomeclaw/nemoclaw-plugin  ← this package
       registers agent tools:
         genomeclaw_status
         genomeclaw_findings
         genomeclaw_variant
         genomeclaw_evidence
         genomeclaw_report
       implementation: HTTP GET → host.openshell.internal:8643
  ⇕  whitelisted by genomeclaw policy preset (policy-preset.yaml)
HOST
└── genomeclaw-service (read-only HTTP, lives in packages/toolkit/)
```

Raw genomic artifacts are **never** reachable from the sandbox (`INV-D002`).

---

## Install (target flow — not yet runnable)

### 1. Build the plugin

```bash
cd packages/nemoclaw-plugin
npm install
npm run build       # produces dist/
```

### 2. Build the sandbox image and onboard

NemoClaw's documented mechanism for installing OpenClaw plugins is "bake into a custom sandbox image, then onboard from that Dockerfile." The build context is this package directory:

```bash
nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile
```

This:

1. Builds an image based on `ghcr.io/nvidia/nemoclaw/sandbox-base:latest`.
2. Copies the plugin into `/sandbox/.openclaw/extensions/genomeclaw/`.
3. Runs `openclaw doctor --fix` to register the extension.

### 3. Apply the policy preset

The preset at [`policy-preset.yaml`](policy-preset.yaml) must be merged into the active blueprint. The intended flow is to pass it to `nemoclaw onboard` (TBD: NemoClaw docs only show interactive selection of *built-in* presets; we'll need to confirm the path for adding an external preset, possibly by copying it into `nemoclaw-blueprint/policies/presets/` before onboard, or via a future `--preset-file` flag).

### 4. Configure the host service URL (post-install, no rebuild)

```bash
nemoclaw <sandbox-name> config set \
  --key plugins.entries.genomeclaw.config.hostService.baseUrl \
  --value '"http://host.openshell.internal:8643"' \
  --restart
```

Plugin config is read at registration time from `plugins.entries.genomeclaw.config.*` in the sandbox `openclaw.json`. In-sandbox `openclaw config set` is intercepted by NemoClaw because changes there do not survive a rebuild.

### 5. Start the host-side service

The plugin is useless without the host-side `genomeclaw-service` (and a derived store to query). Start it from the toolkit package:

```bash
# Pending — see packages/toolkit/
genomeclaw-service start --port 8643
```

---

## Tools exposed to the agent

All tool returns are JSON-encoded inside the `text` field of `PluginCommandResult` with a `GENOMECLAW_JSON: ` prefix, until structured tool returns are confirmed in the OpenClaw plugin SDK (see [open issues](#open--deferred)).

| Tool | Purpose | Output class |
|------|---------|--------------|
| `genomeclaw_status` | Service health, active run-id, schema version | summary |
| `genomeclaw_findings` | Scoped findings list (`category=`, `gene=`, `limit=`) | summary |
| `genomeclaw_variant` | Single-variant lookup by canonical key | summary |
| `genomeclaw_evidence` | Single evidence record by reference id | summary |
| `genomeclaw_report` | Report skeleton (sections, finding ids, evidence refs) — agent renders the prose | summary |

Bulk variants of any of these tools are reserved per `INV-P002` and not enabled in v0.

---

## Invariants this package is responsible for

- **`INV-P002`** (Agent Egress Is a Named, Minimal-Sufficient Boundary) — outputs default to summary class; bulk requires explicit opt-in (currently rejected).
- **`INV-D001` / `INV-D002`** — by absence: this package contains no path or tool that touches raw genomic files.
- **`INV-E001`** (Evidence Traceability) — every finding result is expected to include evidence references forwarded verbatim from the host service.

These are referenced inline in [`src/index.ts`](src/index.ts) and in the [policy preset](policy-preset.yaml).

---

## Open / deferred

Tracked with revisit criteria in [`docs/reference/grand-plan.md`](../../docs/reference/grand-plan.md#decisions-deferred):

- **Structured tool returns**: confirm whether OpenClaw plugin command handlers can return structured JSON instead of text. If yes, drop the `GENOMECLAW_JSON:` text-encoding scheme.
- **`nodeHostCommands` mechanism**: a future optimization that could remove the host HTTP service entirely by brokering host calls through OpenClaw's runtime. Deferred until v1 ships and only with a documented third-party API path.
- **External-preset onboard flow**: the cleanest mechanism for adding `policy-preset.yaml` during `nemoclaw onboard` is unconfirmed; for now, expect to copy the preset into `nemoclaw-blueprint/policies/presets/` before onboarding.

---

## License

Apache-2.0 (matches NemoClaw/OpenClaw/OpenShell upstream licensing).

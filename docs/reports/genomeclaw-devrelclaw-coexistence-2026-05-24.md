# GenomeClaw + DevRelClaw Coexistence on One Host

**Date**: 2026-05-24
**Trigger**: Today's eyesight-agent-question session ran GenomeClaw's agent against `host.openshell.internal:8643`, the same host:port DevRelClaw also uses. I had to kill DevRelClaw's `drg-service` (PID 8860, then PID 99218, then PID 37577 — each time the operator restarted it) to free the port for GenomeClaw's host service. That repeated, manual port-stealing dance is the symptom of a real architectural collision. This report investigates what needs to change so both projects can run as first-class isolated NemoClaw sandboxes on the same machine.

---

## 0. TL;DR

There's exactly one root cause: **both projects hardcode `host.openshell.internal:8643` as their host-side service port**, in both the host-side binding AND the in-sandbox policy preset. Everything else — workspaces, dashboards, openclaw config, container names, sandbox images — is already isolated (or auto-isolates) because NemoClaw was designed for multiple sandboxes.

Fix scope: ~6 file edits in GenomeClaw, one `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile` invocation, then both projects coexist cleanly. The current `bin/genomeclaw` shim + ad-hoc live-smoke harness path stays working unchanged but becomes an internal/test surface; user-facing agent use goes through the onboarded NemoClaw sandbox.

DevRelClaw stays on 8643 (it's older, already wired, has a custom policy preset registered). GenomeClaw moves to a new port (recommendation: **8645** — leaves 8644 as a documented "second project I haven't onboarded yet" slot since DevRelClaw and GenomeClaw might not be the only two).

---

## 1. Current state — what runs where

### DevRelClaw
- **Onboarded as a NemoClaw sandbox** (in `~/.nemoclaw/sandboxes.json`, named `devrelclaw`, dashboardPort 18789, openshellDriver vm, openshellVersion 0.0.44).
- **Host-side service**: `drg-service` (Python uvicorn) on `127.0.0.1:8643` — the only authoritative interface into the Neo4j+Graphiti graph.
- **In-sandbox plugin**: `packages/devrelclaw-plugin/` — registers tools that POST/GET against `host.openshell.internal:8643`.
- **Custom policy preset** registered via `nemoclaw devrelclaw policy add devrelgraph --from-file …`: allows ALL methods on `host.openshell.internal:8643` with the canonical RFC 1918 `allowed_ips` block.
- **Sandbox base image**: `openshell/sandbox-from:1779631276` (built from `packages/devrelclaw-plugin/Dockerfile`).
- **Active container**: `openshell-devrelclaw-15cd34a6-…`.

### GenomeClaw
- **NOT onboarded as a NemoClaw sandbox**. `~/.nemoclaw/sandboxes.json` only lists `devrelclaw`.
- **Host-side service**: `genomeclaw-service` (FastAPI uvicorn via `bin/genomeclaw host service`) on `127.0.0.1:8643` — the read-only window into the active derived run. Defaults are baked into `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py:512` (`port: int = 8643`).
- **In-sandbox plugin**: `packages/nemoclaw-plugin/` — 9 production tools + an env-gated SSRF probe tool. Hardcodes `http://host.openshell.internal:8643` as the default `hostService.baseUrl` (`src/index.ts:75`).
- **Policy preset**: `packages/nemoclaw-plugin/policy-preset.yaml` — single endpoint `host.openshell.internal:8643`, read-only paths only, binary allowlist `openclaw` + `node`. **Hardcoded 8643** with no operator-facing override (`policy-preset.yaml:52`).
- **Sandbox image**: `genomeclaw/sandbox:phase-6c` (built from `packages/nemoclaw-plugin/sandbox/Dockerfile`, whose docstring already documents `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile` as the intended onboarding path — but the operator hasn't run that command yet).
- **Toolkit image**: `genomeclaw/toolkit:dev` / `:phase3-close` / `:worker-self-sufficient` (all aliases of the same image, rebuilt today). This is the bioinformatics-toolkit host-side image invoked by the `bin/genomeclaw` shim — separate from the sandbox image, talks to no agents.

### Where the collision actually fires
Both project's in-sandbox plugins try to call `host.openshell.internal:8643`. The container's `--add-host=host.openshell.internal:host-gateway` makes that alias resolve to the macOS host. The host has exactly one process listening on 8643 at any time. Whoever started last wins. The other agent silently fails.

Today's session exposed this concretely: every time I needed to run a GenomeClaw agent test (eyesight #1, eyesight #2, Path Y v1–v6, today's operator-as-agent eyesight call), I killed `drg-service`, ran the test, then restarted `drg-service`. Five times.

---

## 2. The five isolation dimensions

NemoClaw handles four of these automatically once both projects are onboarded. The fifth (host-service port) is the only thing we have to fix manually.

| # | Dimension | Current state | What changes |
|---|-----------|---------------|--------------|
| 1 | **Sandbox container identity** | DevRelClaw container is `openshell-devrelclaw-…`; GenomeClaw containers are ephemeral `genomeclaw-ssrf-y-<uuid>` or live-smoke `--rm` spawns. | After `nemoclaw onboard --from … --name genomeclaw`, GenomeClaw gets `openshell-genomeclaw-<uuid>` as a long-lived sandbox. NemoClaw guarantees name uniqueness; no collision. |
| 2 | **OpenClaw gateway port (dashboard)** | DevRelClaw is on 18789. Auto-managed. | NemoClaw's `onboard` auto-scans 18789–18799 for the next free port. GenomeClaw lands on 18790 automatically. Documented behavior in `nemoclaw-user-manage-sandboxes` skill. |
| 3 | **Agent workspace + memory** | DevRelClaw: `/sandbox/.openclaw/workspace/` baked at image build + persisted across `nemoclaw rebuild` per the manifest. GenomeClaw: same path inside the ephemeral live-smoke container — wiped every run (today's eyesight #1 wrote a memory note that didn't survive into eyesight #2; we confirmed this hours ago). | After onboarding, GenomeClaw's workspace persists like DevRelClaw's. The `live-smoke` harness's ephemeral-workspace pattern stays useful for tests, but the operator's day-to-day agent surface gets durable memory. |
| 4 | **OpenClaw config + credentials** | DevRelClaw has its own openclaw config dir under NemoClaw's managed state. GenomeClaw's live-smoke harness writes `openclaw config set` inline per test run into the container's ephemeral `~/.openclaw/openclaw.json` — disposable. | After onboarding, GenomeClaw gets its own managed config. `~/.nemoclaw/credentials.json` is shared between sandboxes (one OpenAI key, one Anthropic key) — that's by design and matches NemoClaw's model. |
| 5 | **Host-side service port** | **COLLISION** — both want 8643. | Manual fix in GenomeClaw: pick a new port, propagate it through 6 source locations (see §3). |

The fifth row is the entire substantive work item. The other four become true the moment `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile --name genomeclaw` runs.

---

## 3. The host-service port: propagation chain

GenomeClaw's port 8643 is currently set in six source locations. All six need to change in lockstep, because the runtime fans out from one logical decision (which port does the host service bind?) into multiple enforcement surfaces (which port does the sandbox call? which port does the L7 policy allowlist?).

| Source | Path | What references 8643 |
|--------|------|----------------------|
| Host service CLI default | `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py:512` | `port: int = 8643` |
| Live-smoke harness default | `packages/toolkit/tests/_live_smoke/run.py:40` | `DEFAULT_HOST_PORT = 8643` |
| Plugin default config | `packages/nemoclaw-plugin/src/index.ts:75` | `baseUrl: "http://host.openshell.internal:8643"` |
| Policy preset (hard requirement — L7 enforcement) | `packages/nemoclaw-plugin/policy-preset.yaml:52` | `port: 8643` |
| Plugin's openclaw config batch | `packages/toolkit/tests/_live_smoke/run.py:_build_openclaw_config_batch` | `f"http://host.openshell.internal:{host_port}"` (already parameterised, just uses 8643 as default) |
| Shim docs / health check | `bin/genomeclaw` (host service subcommand wiring) | references 8643 in default config + the curl health probe inside the in-container script |

The right approach is NOT to make the port runtime-configurable on the sandbox side — the policy preset is L7 enforcement, and L7 enforcement is precisely where you want a baked-in literal so a runtime config flip can't accidentally widen the surface. Instead: **pick one new port for GenomeClaw + hard-fork it through all six locations + bump the policy preset version**.

### Recommended new port

**8645**. Rationale:
- Adjacent to DevRelClaw's 8643 for mnemonic association ("8643 = DevRelClaw, 8645 = GenomeClaw").
- Skips 8644 to leave space for a hypothetical third project. The operator already runs at least two services on this host; assuming a third will exist eventually is cheap.
- Above the well-known port range, well below typical ephemeral ranges; matches the existing convention (8643).
- Not 18790 (NemoClaw dashboard band) or 19001 (openclaw dev profile gateway) so it doesn't visually collide with NemoClaw-owned ports.

### Plain port-only fix (no NemoClaw onboarding yet)

The fastest unblock — gets both services coexisting tonight without onboarding GenomeClaw as a NemoClaw sandbox:

1. Change the six locations from 8643 → 8645.
2. Bump policy preset schema version (`packages/nemoclaw-plugin/policy-preset.yaml`: add a comment block noting the port change + version).
3. Rebuild `packages/nemoclaw-plugin/dist/index.js` (`npm run build`).
4. Run the live-smoke + Path Y tests end-to-end to confirm no caller still has 8643 baked in.
5. DevRelClaw stays on 8643 untouched.
6. The `bin/genomeclaw host service` shim now binds 8645 instead of 8643 — no more port-stealing.

This is the minimum-viable fix. Doesn't address workspace persistence, doesn't address sandbox isolation. Just unblocks the daily collision.

### Full fix (proper NemoClaw onboarding)

After the port change, onboard:

```console
$ nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile --name genomeclaw
```

This:
- Creates a `genomeclaw` entry in `~/.nemoclaw/sandboxes.json` next to `devrelclaw`.
- Builds the sandbox image with the GenomeClaw plugin pre-installed.
- Allocates the next free dashboard port (18790).
- Provisions a persistent workspace under NemoClaw's managed state.
- Registers the updated policy preset.

Then:

```console
$ nemoclaw genomeclaw connect       # opens shell into the sandbox
$ openclaw tui                      # opens the chat UI bound to the genomeclaw sandbox
```

The operator's day-to-day eyesight question becomes a TUI conversation against the onboarded sandbox — no more `python /tmp/ask_agent_eyesight.py` orchestration, no more port-killing dance.

The `bin/genomeclaw` shim's other subcommands (`pipeline ingest`, `pipeline annotate`, `host service`, `setup`, `doctor`, `eject`) stay unchanged as the operator-facing host-side surface. The shim becomes the "set up + maintain the data pipeline" tool, and the onboarded NemoClaw sandbox becomes the "ask the agent questions about the data" surface. Two clearly-separated roles.

---

## 4. What stays in the live-smoke harness

Once GenomeClaw is properly onboarded as a NemoClaw sandbox, what's the role of `packages/toolkit/tests/_live_smoke/`?

It stays as **the CI / programmatic test surface**, distinct from the operator's daily-use surface:

- The 4 existing live LLM tests (`test_live_story4_clopidogrel_snapshot`, etc.) need programmatic agent invocation with fixture-controlled derived runs. NemoClaw-managed sandboxes can't substitute — they have ONE persistent workspace that tests would step on.
- The Path Y SSRF probe test needs `GENOMECLAW_ENABLE_SSRF_PROBE=1` set in container env + the freshly-built plugin overlay-mounted. NemoClaw sandboxes are built once + rebuilt rarely; test-time plugin replacement is incompatible.
- The harness's `running_sandbox_container` context manager is purpose-built for short-lived, fixture-staged sandboxes. The operator's daily agent isn't.

So after onboarding, the live-smoke harness keeps its current shape — it just stops being "the only way to talk to a GenomeClaw agent." It becomes "the test mode."

---

## 5. What about the toolkit image?

`genomeclaw/toolkit:dev` (the bioinformatics-toolkit image — bcftools, mosdepth, samtools, pgsc_calc, the Python `genomeclaw-prep` + `genomeclaw-service` packages) is unrelated to this discussion. It's not an agent surface. It's not onboarded into NemoClaw. It's invoked by `bin/genomeclaw` as a one-shot `docker run --rm` per command. No collision with DevRelClaw because DevRelClaw has nothing analogous.

The toolkit image's only relevance: it hosts the `genomeclaw host service` process when invoked via `bin/genomeclaw host service`. That's the process bound to the 8643/8645 port we just discussed. Same image; different invocation pattern.

---

## 6. Cross-project secret + state hygiene

NemoClaw's design already gives us most of what we need here. Two clarifying notes:

### Shared credentials
`~/.nemoclaw/credentials.json` holds the OpenAI / Anthropic / etc. keys, shared across all onboarded sandboxes. This is the operator's choice: one key per provider, multiple sandboxes consuming it.

Implication for GenomeClaw: the OpenAI key today's session used (`OPEN_AI_API_KEY` from `.env`) would migrate into `~/.nemoclaw/credentials.json` during `nemoclaw onboard`. The `.env` file becomes superfluous for agent invocation — it stays useful only for non-NemoClaw scripts (the `/tmp/ask_agent_*.py` style harnesses + the live-smoke tests that source it manually).

No security regression: NemoClaw stores credentials with the same file permissions the operator's `.env` had (and Keychain on macOS if `nemoclaw configure` is used). The change is "single source of truth in `~/.nemoclaw`" instead of "two parallel sources (`.env` + `~/.nemoclaw`)."

### Workspace files
DevRelClaw's workspace files (SOUL.md, USER.md, IDENTITY.md, daily memory notes, agent's research-corpus pointers) live inside its sandbox's persistent workspace. GenomeClaw's `packages/nemoclaw-plugin/sandbox/workspace/IDENTITY.md` + `USER.md` are baked into the sandbox image at build time; after onboarding they'd land in GenomeClaw's persistent workspace.

The two workspaces are physically separate dirs. No cross-contamination. The agent in DevRelClaw cannot see GenomeClaw's IDENTITY.md and vice versa. This was already true today (different sandbox containers, different image filesystems); onboarding just makes it persistent.

### Host-side data
DevRelClaw's authoritative graph: `/Users/hugi/GitRepos/DevRelClaw/data/` (Neo4j) + `research-corpus/` (markdown).
GenomeClaw's authoritative genomic data: `/Volumes/Genome_Work/genomeclaw/{raw,reference,derived}` (bind-mounted into the toolkit image via the shim; served to the agent over the host service).

These never share a mount. The toolkit image's bind-mount set is GenomeClaw-only. DevRelClaw's drg-service has its own scope. The L7 policy on each sandbox prevents the wrong direction of access (DevRelClaw's sandbox cannot reach 8645/GenomeClaw because its policy doesn't allowlist that port; GenomeClaw's sandbox cannot reach 8643/DevRelClaw because its policy doesn't allowlist that port).

This is the strongest privacy property of the proposed design: **genomic data cannot leak into DevRelClaw's agent context and DevRelClaw's research data cannot leak into GenomeClaw's agent context, because each sandbox's L7 policy explicitly excludes the other's host-service port.** That's enforced by OpenShell at runtime, not just by convention. (Today we shipped the SSRF runtime probe that proves this enforcement layer actually fires for GenomeClaw — see `docs/plans/completed/ssrf-runtime-probe/`. DevRelClaw would benefit from the equivalent probe; its policy preset is also tested only for static shape today.)

---

## 7. Recommended sequence (concrete steps for the operator)

Two stages. Stage 1 is the unblock; stage 2 is the proper landing.

### Stage 1 — Port change (today)

1. Bump GenomeClaw's host-service port from 8643 → 8645 across the six locations enumerated in §3.
2. Bump the policy preset's comment + add a `version: 2` field or equivalent (so any future tool tracking preset versions can detect the change).
3. Rebuild plugin: `cd packages/nemoclaw-plugin && npm run build`.
4. Rebuild the sandbox image: `docker build -t genomeclaw/sandbox:port-8645 -f packages/nemoclaw-plugin/sandbox/Dockerfile packages/nemoclaw-plugin/` (or similar; the current build command isn't in a Makefile so check the Dockerfile docstring for the actual invocation).
5. Update the live-smoke harness's `SANDBOX_IMAGE` references in `/tmp/ask_agent_*.py` and the pytest fixtures to point at the new tag.
6. Re-run the Path Y SSRF probe pytest test to confirm end-to-end wiring: `GENOMECLAW_HAS_DOCKER=1 GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:port-8645 OPENAI_API_KEY=… pytest packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py -v`.
7. Restart DevRelClaw on 8643 (it's been resilient to my restarts today, but now it's the long-term resident of 8643 and won't be killed for GenomeClaw tests anymore).

Cost: ~30 min of file edits + a sandbox-image rebuild (~5 min on second build with layer cache). No new credentials, no new infrastructure.

### Stage 2 — Onboard as NemoClaw sandbox (this week)

1. Confirm stage 1 is green — port change works in isolation.
2. Run `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile --name genomeclaw` from the GenomeClaw repo root.
3. The wizard provisions: a `genomeclaw` entry in `~/.nemoclaw/sandboxes.json`, a long-lived sandbox container, a persistent workspace, an auto-allocated dashboard port (probably 18790).
4. Register the GenomeClaw policy preset: `nemoclaw genomeclaw policy add genomeclaw --from-file packages/nemoclaw-plugin/policy-preset.yaml` (matches the DevRelClaw model).
5. Test the agent flow via TUI: `nemoclaw genomeclaw connect; openclaw tui` then ask the eyesight question.
6. Update the agent-system-prompt's first-tool-call instruction so the agent knows to discover the active derived run via `genomeclaw_status` (this was already the case but worth a re-read in the onboarded context).
7. Optional but valuable: document the operator's daily flow in `docs/reference/` — when to use `bin/genomeclaw pipeline ingest` (host-side data prep) vs `nemoclaw genomeclaw connect → openclaw tui` (agent conversation against the active derived run).

Cost: ~1 hour of onboarding + smoke. Net result: clean separation between the two projects, both first-class sandboxes, no port collision, persistent agent memory, operator never has to kill drg-service again.

### Stage 3 (later) — DevRelClaw SSRF runtime probe

DevRelClaw's policy preset (`packages/devrelclaw-plugin/policy-preset.yaml`) only has static-shape coverage today, same as GenomeClaw before this week. The runtime probe we just shipped for GenomeClaw (Path Y, in `docs/plans/completed/ssrf-runtime-probe/`) is directly transferable to DevRelClaw — copy the test, swap the policy assertions (DevRelClaw allows broader internet egress so the probe shape is different), invoke against `openshell-devrelclaw-…`. Worth filing as a DevRelClaw-side plan if the operator wants symmetric privacy-enforcement evidence.

---

## 8. What we don't propose

- **Running both sandboxes on the same dashboard port via reverse proxy** — NemoClaw auto-allocates dashboard ports already; introducing a proxy adds attack surface without benefit.
- **Sharing a single host-service port via a router** (e.g., DevRelClaw at `/devrel/*` and GenomeClaw at `/genome/*` behind nginx) — possible but introduces a new component to harden, breaks the simple `host.openshell.internal:<port>` policy assertion, and complicates the L7 policy preset (path-based routing inside one host:port is harder to reason about than two host:port pairs).
- **Eliminating the host service entirely and giving the sandbox direct file-system access** — violates INV-D002 (raw genomic artifacts are host-side only). The host service is the load-bearing privacy boundary; replacing it with mounts would let any agent read any genomic file.
- **Onboarding the toolkit image as a NemoClaw sandbox** — the toolkit image is for one-shot pipeline invocation, not for hosting a long-lived agent. Two different problems.

---

## 9. What's at stake if we don't fix this

The current ad-hoc setup has three failure modes that get worse as more projects join:

1. **Silent agent failure when ports collide.** Today the symptom was "host service unreachable" in the agent log. Tomorrow it could be "agent's call to fetch CFH variants returned 200 OK with DevRelClaw's payload schema" — the wrong service answering the call because the policy allowlist matches the host:port string but the actual service behind it is the wrong one. The path is closed (different schemas, different routes) but it's an unhardened failure mode.

2. **Privacy boundary erosion.** If a future project (third, fourth) also claims `host.openshell.internal:8643` and the operator runs them in parallel, the L7 policy on each sandbox still allowlists 8643. Whichever service binds first gets all the agent traffic. There's no policy-level guard against "wrong service on the right port" because the policy only sees host:port pairs, not service identity. **This is the strongest argument for distinct ports as a hard rule.**

3. **Per-test port killing doesn't scale.** Today's session killed drg-service 5 times. The operator restarted it 3 times in parallel. That's already a friction point; adding the SSRF probe test to CI (which the user might want once the toolkit image is rebuilt + the test is wired up) would compound it. The proper fix removes the entire class of operator-intervention need.

---

## 10. Open questions for the operator

1. **Port assignment**: agree to GenomeClaw=8645? Or prefer a different number?
2. **NemoClaw onboard timing**: do stage 1 (port change) today, stage 2 (onboarding) this week — or bundle them into one session?
3. **`.env` migration**: after onboarding, `OPEN_AI_API_KEY` from `.env` becomes superfluous for agent invocation. Migrate to `~/.nemoclaw/credentials.json` and delete from `.env`, or keep both for tests + scripts?
4. **DevRelClaw SSRF probe**: file a parallel plan in the DevRelClaw repo for runtime-probe coverage there too?
5. **Daily-use surface**: after onboarding, do you want a `bin/genomeclaw agent` shim that wraps `nemoclaw genomeclaw connect; openclaw tui` as a one-liner, or is the two-step invocation fine?

---

## 11. References

- DevRelClaw policy preset: `~/GitRepos/DevRelClaw/packages/devrelclaw-plugin/policy-preset.yaml`
- DevRelClaw devrelgraph preset (registered): `~/GitRepos/DevRelClaw/packages/devrelclaw-plugin/policy-presets/devrelgraph.yaml`
- DevRelClaw plugin Dockerfile: `~/GitRepos/DevRelClaw/packages/devrelclaw-plugin/Dockerfile`
- DevRelClaw CLAUDE.md: `~/GitRepos/DevRelClaw/CLAUDE.md` (architecture section calls out the `host.openshell.internal:8643` choice)
- NemoClaw sandbox registry: `~/.nemoclaw/sandboxes.json`
- GenomeClaw plugin policy preset: `packages/nemoclaw-plugin/policy-preset.yaml`
- GenomeClaw plugin Dockerfile (onboarding-ready): `packages/nemoclaw-plugin/sandbox/Dockerfile`
- GenomeClaw shim port wiring: `bin/genomeclaw` + `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py`
- GenomeClaw live-smoke harness: `packages/toolkit/tests/_live_smoke/run.py`
- NemoClaw skill — managing multiple sandboxes: `.claude/skills/nemoclaw-user-manage-sandboxes/SKILL.md`
- NemoClaw skill — `nemoclaw onboard --from`: `.claude/skills/nemoclaw-user-deploy-remote/SKILL.md`
- INV-P002 (the egress invariant this whole discussion serves): `docs/reference/INVARIANTS.md` v1.16

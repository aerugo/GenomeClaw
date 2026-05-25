# SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
# SPDX-License-Identifier: Apache-2.0
#
# GenomeClaw sandbox image for NemoClaw / OpenShell.
#
# Builds on the NemoClaw sandbox base image (which already includes OpenClaw,
# Node.js, and the NemoClaw plugin). We add:
#   - the GenomeClaw OpenClaw plugin (TypeScript, built into ./dist)
#   - copies the plugin into /sandbox/.openclaw/extensions/genomeclaw
#   - runs `openclaw doctor --fix` to register the new plugin
#
# This image is consumed via:
#   nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile
#
# The Dockerfile build context is the parent of this file:
#   packages/nemoclaw-plugin/
#
# Invariants this Dockerfile is responsible for:
#   - INV-D002: bioinformatics tools (samtools, bcftools, SnpEff, etc.) are
#     intentionally NOT installed here. Raw genomic artifacts are processed
#     only on the host; the sandbox has no path to them.
#   - INV-R001: the plugin source is built into immutable `dist/` artifacts;
#     the same Dockerfile + same plugin source produces the same image.
#
# To rebuild: nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile
# To override the host-service port (default 8645):
#   docker build --build-arg GENOMECLAW_HOST_PORT=<n> ...
# OR rely on the GENOMECLAW_HOST_SERVICE_PORT env var which is read by the
# plugin's TypeScript at runtime + by the host-side shim + by the live-smoke
# harness, all defaulting to 8645 when unset. The Dockerfile ARG below
# substitutes the value into policy-preset.yaml at COPY time so the
# baked-in L7 enforcement stays in lockstep with the runtime config.
#
# To reconfigure post-build (no rebuild needed):
#   nemoclaw <sandbox> config set \
#     --key plugins.entries.genomeclaw.config.hostService.baseUrl \
#     --value '"http://host.openshell.internal:8645"' \
#     --restart

ARG SANDBOX_BASE=ghcr.io/nvidia/nemoclaw/sandbox-base:latest
ARG GENOMECLAW_HOST_PORT=8645
FROM ${SANDBOX_BASE}

# ARGs reset on every FROM — re-declare so the RUN below can read it.
ARG GENOMECLAW_HOST_PORT=8645

USER root

# Stage the policy preset + render the port into it. Default value (8645)
# matches what ships in policy-preset.yaml; the sed is a no-op unless the
# operator overrode --build-arg GENOMECLAW_HOST_PORT. Done early so the
# rest of the build can reference the rendered file at a known path.
COPY policy-preset.yaml /opt/genomeclaw/policy-preset.yaml
RUN sed -i "s/port: 8645/port: ${GENOMECLAW_HOST_PORT}/g" /opt/genomeclaw/policy-preset.yaml \
    && echo "[build] genomeclaw policy preset rendered with host port ${GENOMECLAW_HOST_PORT}"

# Stage the plugin source under /opt and build it there.
# The build context is `packages/nemoclaw-plugin/`, so `./` here refers to
# the plugin package root containing package.json, tsconfig.json, src/.
COPY package.json package-lock.json* tsconfig.json openclaw.plugin.json /opt/genomeclaw/
COPY src/ /opt/genomeclaw/src/
# `types/` carries the local stub of `openclaw/plugin-sdk` that `tsc` needs
# to compile the plugin (Slice D, 2026-05-15). The real SDK is provided by
# the sandbox base image at runtime; the stub only exists for build-time
# type resolution.
COPY types/ /opt/genomeclaw/types/

WORKDIR /opt/genomeclaw
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
RUN npm run build

# Install the built plugin via `openclaw plugins install --link`, the
# documented registration path. This:
#   1. Validates the package.json carries the required `openclaw.extensions`
#      field pointing at the compiled entry point (./dist/index.js).
#   2. Registers the plugin id (`genomeclaw`) in OpenClaw's plugin index so
#      `openclaw plugins list` + `plugins.allow: [genomeclaw]` actually
#      resolve to this extension.
#   3. Links instead of copying so we still inspect from /opt/genomeclaw.
#
# `node_modules/` must be present at the link target because Slice D
# introduced a runtime dep on `@sinclair/typebox` (the TypeBox schemas the 5
# tools declare for their parameters). Without it the sandbox Node runtime
# fails the plugin's first `import` with `ERR_MODULE_NOT_FOUND: Cannot find
# package '@sinclair/typebox'`. Discovered via the 2026-05-15 live sweep.
# Trade-off: ships ~250KB extra (typebox has zero transitive runtime deps).
# Bundling via esbuild/rollup would shrink it but adds tooling complexity
# without a clear win at this scale.
#
# `chown` to the sandbox user so the plugin is readable when openclaw runs
# under USER sandbox below.
RUN chown -R sandbox:sandbox /opt/genomeclaw
USER sandbox
WORKDIR /sandbox

# `openclaw config` resolves its config root from $HOME (defaulting to
# /root/.openclaw if HOME is unset). The base image leaves HOME unset for
# user `sandbox`, so without this ENV, every `openclaw config set` issued
# at build time (and worse, at runtime via docker exec / nemoclaw exec)
# tries to write /root/.openclaw and EACCESes because uid 998 can't write
# /root. Surfaced 2026-05-24 during the onboard-persistent-agent-fix demo:
# every post-install `openclaw config set` failed with
# `EACCES: permission denied, mkdir '/root/.openclaw'`. Setting HOME here
# fixes the build-time and the runtime path in one line. See
# docs/plans/active/onboard-persistent-agent-fix/.
ENV HOME=/sandbox

RUN openclaw plugins install /opt/genomeclaw --link

# `INV-P001` v1.7 (per agent-research-and-synthesis Phase 2b, 2026-05-15):
# native OpenAI `web_search` (the hosted `web_search` tool that OpenAI's
# Responses API exposes) flows through the **same** egress destination the
# user already opted into when they configured the OpenAI provider — it is
# NOT a new named egress destination. So we enable `tools.web.search.enabled`
# by default; per the OpenClaw web-search docs, with `enabled: true` AND no
# `tools.web.search.provider` pinned, native OpenAI search auto-activates
# for Responses-API agent calls and the managed `web_search` tool no-ops.
#
# A managed provider (Brave / Tavily / Perplexity / etc.) IS a third named
# egress destination per INV-P001 and stays opt-in: the user explicitly runs
# `openclaw config set tools.web.search.provider <name>` post-install + adds
# the provider's API key. Pinning a provider here would expose the user to
# egress they did not consent to.
#
# `web_fetch` does outbound HTTP from the sandbox to arbitrary URLs and is
# NOT part of the OpenAI Responses API contract — it remains a third named
# egress destination and ships disabled. The user enables it explicitly when
# their workflow requires it (rare for research-and-synthesis; web_search
# usually covers the use case).
#
# All three settings are auditable in the baked openclaw.json and verified
# by tests/invariants/test_invP001_sandbox_web_egress_contract.py.
RUN openclaw config set tools.web.search.enabled true \
 && openclaw config set tools.web.fetch.enabled false

# Persistent-path runtime config (onboard-persistent-agent-fix, 2026-05-24):
# the `nemoclaw genomeclaw exec` wrapper runs commands inside openshell's
# filesystem-restriction layer that EACCESes on `/opt/genomeclaw`, so any
# post-install `openclaw config set ...` issued by the operator's onboard
# script fails. We bake the four keys that script used to set into the
# image at build time (where the USER-sandbox-with-HOME-set context can
# actually write to /sandbox/.openclaw). Without these bakes:
#   - missing gateway.mode → "Gateway start blocked: existing config is
#     missing gateway.mode" + gateway refuses to start
#   - missing plugins.allow → plugin loaded but disabled, 0 tools surfaced
#   - missing hostService.baseUrl → plugin defaults wrong, ECONNREFUSED
#     on every tool call
# Verified by tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py.
RUN openclaw config set gateway.mode local \
 && openclaw config set plugins.allow '["genomeclaw"]' \
 && openclaw config set plugins.entries.genomeclaw.config.hostService.baseUrl \
      "http://host.openshell.internal:${GENOMECLAW_HOST_PORT}" \
 && openclaw config set plugins.entries.genomeclaw.config.hostService.timeoutMs 30000

# OpenAI provider entry — bake baseUrl + models + auth profile together
# via `openclaw config set --batch-file`. Single-key sets fail the
# validator's cross-field check (baseUrl requires models, models requires
# baseUrl — circular for individual sets but resolvable in a batch). The
# values mirror what the live-smoke harness sets via
# _build_openclaw_config_batch in packages/toolkit/tests/_live_smoke/run.py
# so both execution paths configure the provider the same way.
# Single RUN that writes the batch file via printf (portable across docker
# builders; heredoc-RUN requires BuildKit which we don't assume here),
# applies it, and cleans up. The JSON is a single line so printf's %s works.
RUN printf '%s' '[{"path":"models.providers.openai.baseUrl","value":"https://api.openai.com/v1"},{"path":"models.providers.openai.models","value":[{"id":"gpt-5.5","name":"GPT 5.5","api":"openai-responses","contextWindow":200000,"maxTokens":16384}]},{"path":"auth.profiles.openai_default.provider","value":"openai"},{"path":"auth.profiles.openai_default.mode","value":"api_key"}]' \
      > /tmp/openai-provider.json \
 && openclaw config set --batch-file /tmp/openai-provider.json \
 && rm /tmp/openai-provider.json

# Bind the OpenAI provider's apiKey to the OPENAI_API_KEY env var at
# runtime. The gateway process reads the key from its env at startup
# (operator passes it via `docker exec -e OPENAI_API_KEY=...` per the
# onboard script). The literal key NEVER lands in this image layer —
# only the ref-to-env-var-name lands. This makes the built image safe
# to push to a private registry without leaking the operator's credential.
# Ref shape (verified empirically): {"source":"env","provider":"default","id":"OPENAI_API_KEY"}.
RUN openclaw config set models.providers.openai.apiKey \
      --ref-provider default --ref-source env --ref-id OPENAI_API_KEY

# `INV-A002` synthesis-reasoning floor (agent-research-and-synthesis Phase 3
# slice 5, 2026-05-15): health-interpretation turns compose at the maximum
# reasoning level the configured model supports. For the canonical default
# model (OpenAI gpt-5.5), that ceiling is `xhigh` — the supported set is
# `off | minimal | low | medium | high | xhigh`. The level `max` is silently
# REJECTED for gpt-5.5 at per-call validation time (it is an o-series-only
# level) — slice 1-4 baked `max` here and the gateway silently coerced /
# rejected it. The probe at
# tests/invariants/test_sandbox_thinking_default_supported.py reads back the
# baked value and asserts it's a valid level for the configured default
# model so this regression can't recur.
#
# We bake BOTH `agents.defaults.model` AND `agents.defaults.thinkingDefault`
# together because the per-model gate validates consistency between them.
# Users on a different default model (e.g. `openai/o3` or `openai/o4`) should
# update both fields together — `max` is the right value for o-series.
# The user still has to supply their OpenAI API key post-install before the
# agent can actually run; baking the model+thinking pair just pins the
# canonical default contract.
RUN openclaw config set agents.defaults.model openai/gpt-5.5 \
 && openclaw config set agents.defaults.thinkingDefault xhigh

# Agent system prompt (agent-research-and-synthesis Phase 2, 2026-05-15):
# teaches the research-and-synthesis protocol + memory-note schema +
# turn-classification + the synthesis-reasoning-floor `INV-A002` + the
# memory-validation three-check protocol `INV-C001` v1.6. Verified by
# tests/invariants/test_agent_system_prompt_contract.py.
#
# The prompt installs as a `genomeclaw` named agent with the prompt
# text in `agents.list[].systemPromptOverride`. We use a small Python
# helper to read the prompt off disk + emit a `--strict-json` batch so
# the multi-line text survives shell quoting.
COPY --chown=sandbox:sandbox sandbox/agent-system-prompt.md /opt/genomeclaw/sandbox/agent-system-prompt.md
COPY --chown=sandbox:sandbox sandbox/install-agent-prompt.py /opt/genomeclaw/sandbox/install-agent-prompt.py
RUN python3 /opt/genomeclaw/sandbox/install-agent-prompt.py

# Workspace bootstrap (agent-research-and-synthesis Phase 3 slice 4, 2026-05-15):
# the OpenClaw `pi` agent harness auto-injects workspace files into the system
# prompt context + runs an "identity bootstrap" flow when IDENTITY.md / USER.md
# are blank templates. Phase 2a/2b live smokes saw the harness fully intercept
# the user's first genomics question to ask "what should I call you?" — that's
# the right behaviour for a generic agent but the wrong default for GenomeClaw
# (the agent is *named* and the user's identity is encoded in their genome data
# + the agent's protocol). We bake non-blank defaults so the bootstrap flow is
# already complete at first run + delete any pre-existing BOOTSTRAP.md trigger.
#
# Users who want different identity / vibe can edit these files post-install;
# the next session reload picks up the changes.
#
# Verified by tests/invariants/test_sandbox_workspace_bootstrap_baked.py
# (needs_sandbox-gated: asserts both files exist + non-empty + no BOOTSTRAP.md).
COPY --chown=sandbox:sandbox sandbox/workspace/IDENTITY.md /sandbox/.openclaw/workspace/IDENTITY.md
COPY --chown=sandbox:sandbox sandbox/workspace/USER.md /sandbox/.openclaw/workspace/USER.md
RUN rm -f /sandbox/.openclaw/workspace/BOOTSTRAP.md

USER root
WORKDIR /opt/genomeclaw

# Drop back to the unprivileged sandbox user; NemoClaw's entrypoint expects this.
USER sandbox
WORKDIR /opt/nemoclaw

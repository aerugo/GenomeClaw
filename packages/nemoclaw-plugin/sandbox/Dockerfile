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
# To reconfigure post-build (no rebuild needed):
#   nemoclaw <sandbox> config set \
#     --key plugins.entries.genomeclaw.config.hostService.baseUrl \
#     --value '"http://host.openshell.internal:8643"' \
#     --restart

ARG SANDBOX_BASE=ghcr.io/nvidia/nemoclaw/sandbox-base:latest
FROM ${SANDBOX_BASE}

USER root

# Stage the plugin source under /opt and build it there.
# The build context is `packages/nemoclaw-plugin/`, so `./` here refers to
# the plugin package root containing package.json, tsconfig.json, src/.
COPY package.json package-lock.json* tsconfig.json openclaw.plugin.json /opt/genomeclaw/
COPY src/ /opt/genomeclaw/src/

WORKDIR /opt/genomeclaw
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
RUN npm run build

# Install the built plugin into OpenClaw's extensions directory.
# This is the documented install path for OpenClaw plugins under NemoClaw:
#   /sandbox/.openclaw/extensions/<plugin-name>/
# `openclaw doctor --fix` registers the new extension with OpenClaw's config.
RUN mkdir -p /sandbox/.openclaw/extensions/genomeclaw \
 && cp -a openclaw.plugin.json /sandbox/.openclaw/extensions/genomeclaw/ \
 && cp -a package.json         /sandbox/.openclaw/extensions/genomeclaw/ \
 && cp -a dist                  /sandbox/.openclaw/extensions/genomeclaw/ \
 && chown -R sandbox:sandbox /sandbox/.openclaw/extensions/genomeclaw \
 && openclaw doctor --fix

# Drop back to the unprivileged sandbox user; NemoClaw's entrypoint expects this.
USER sandbox
WORKDIR /opt/nemoclaw

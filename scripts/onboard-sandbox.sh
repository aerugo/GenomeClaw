#!/usr/bin/env bash
# scripts/onboard-sandbox.sh — canonical end-to-end onboarding for the
# GenomeClaw NemoClaw sandbox. Idempotent: re-running rebuilds cleanly.
#
# Usage (from repo root):
#   ./scripts/onboard-sandbox.sh
#
# Reads from .env:
#   OPEN_AI_API_KEY         (mandatory)         → exported as OPENAI_API_KEY
#
# Prereqs (verified on entry):
#   - nemoclaw CLI on PATH (install via `curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`)
#   - docker on PATH + colima running (on macOS)
#   - genomeclaw/toolkit:dev image built (run `bin/genomeclaw --help` first
#     to trigger the build via the shim, OR
#     `docker build -t genomeclaw/toolkit:dev packages/toolkit`)
#
# What this script does, in order:
#   1. Sanity-check the prereqs (nemoclaw, docker, .env, toolkit image).
#   2. Build the GenomeClaw sandbox image with the canonical host port
#      (8645) baked into the policy preset via Dockerfile ARG, AND build
#      the plugin TypeScript first so the freshly-built dist lands inside
#      the image.
#   3. Run `nemoclaw onboard --fresh --recreate-sandbox --from
#      packages/nemoclaw-plugin/sandbox/Dockerfile --name genomeclaw`.
#   4. Register the GenomeClaw policy preset (host-service egress +
#      RFC1918 allowlist for the SSRF guard).
#   5. Set `plugins.entries.genomeclaw.config.hostService.baseUrl` to
#      `http://host.openshell.internal:8645`.
#   6. Inject the OpenAI auth-profile into the agent's auth-profiles.json
#      (workaround for `nemoclaw inference set` failing on local Docker
#      installs — same mechanism DevRelClaw's onboarding uses).
#   7. Route the openai provider through `inference.local` (sandbox L7
#      proxy blocks `api.openai.com:443`; only `inference.local` is on
#      the base policy allowlist).
#   8. Smoke-test the agent with a one-shot natural-language probe.
#
# Sibling project DevRelClaw uses an analogous script at
# /Users/hugi/GitRepos/DevRelClaw/scripts/onboard-sandbox.sh — both
# projects coexist on one host with distinct host-service ports
# (DevRelClaw=8643, GenomeClaw=8645). See
# docs/reports/genomeclaw-devrelclaw-coexistence-2026-05-24.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found at $REPO_ROOT/.env" >&2
  echo "  Create it with: OPEN_AI_API_KEY=sk-proj-…" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source ./.env; set +a

if [[ -z "${OPEN_AI_API_KEY:-}" ]]; then
  echo "ERROR: OPEN_AI_API_KEY not set in .env" >&2
  exit 1
fi
export OPENAI_API_KEY="$OPEN_AI_API_KEY"

if ! command -v nemoclaw >/dev/null 2>&1; then
  echo "ERROR: nemoclaw CLI not on PATH. Install via:" >&2
  echo "  curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not on PATH. Install Docker Desktop or Colima first." >&2
  exit 1
fi

# Operator-configurable host port (default 8645; DevRelClaw uses 8643).
HOST_PORT="${GENOMECLAW_HOST_SERVICE_PORT:-8645}"
echo "[onboard] GenomeClaw host-service port: ${HOST_PORT}"

# ---- step 1: pre-build the plugin TypeScript ------------------------------
#
# The sandbox Dockerfile builds the plugin INSIDE the image via
# `npm ci && npm run build`, so this pre-build is mostly a developer-ergonomics
# step (faster type-error feedback than waiting for the image build to fail).
# We also rely on `packages/nemoclaw-plugin/dist/index.js` being current
# whenever the live-smoke harness runs the Path Y SSRF probe test.

echo "[onboard] pre-building plugin TypeScript"
(cd packages/nemoclaw-plugin && npm install --no-audit --no-fund >/dev/null 2>&1 || true)
(cd packages/nemoclaw-plugin && npm run typecheck && npm run build)

# ---- step 2: ensure toolkit image is present ------------------------------
#
# The toolkit image is the host-side bioinformatics container — separate
# from the sandbox image. It carries bcftools/mosdepth/samtools/etc. The
# shim wraps it. Onboarding doesn't need it for the agent surface, but
# the operator will need it for any `bin/genomeclaw pipeline …` invocation
# (and the agent's `genomeclaw_status` tool fails meaningfully against an
# empty derived store, so having the toolkit image makes follow-up work
# possible).

if ! docker image inspect genomeclaw/toolkit:dev >/dev/null 2>&1; then
  echo "[onboard] toolkit image genomeclaw/toolkit:dev not present; building"
  docker build -t genomeclaw/toolkit:dev packages/toolkit
else
  echo "[onboard] toolkit image genomeclaw/toolkit:dev present"
fi

# ---- step 3: pre-build sandbox image + onboard via shim Dockerfile --------

export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_PROVIDER=openai
export NEMOCLAW_POLICY_MODE=suggested
export NEMOCLAW_NO_EXPRESS=1

# `nemoclaw onboard --from <Dockerfile>` stages only the Dockerfile (or its
# parent dir) into a temp build context, so any `COPY` reaching outside
# `dirname(<from>)` fails. Our sandbox Dockerfile lives at
# `packages/nemoclaw-plugin/sandbox/Dockerfile` and intentionally references
# parent-dir files (`policy-preset.yaml`, `package.json`, `src/`, `types/`,
# `openclaw.plugin.json`, etc.) — `docker build -f sandbox/Dockerfile
# packages/nemoclaw-plugin/` works fine because docker accepts an explicit
# context, but `nemoclaw onboard` doesn't expose a `--context` flag.
#
# Sidestep: pre-build the heavy image ourselves with the correct context
# (and the right --build-arg for the host port), then hand `nemoclaw
# onboard` a one-line shim Dockerfile that just `FROM`s the pre-built tag.
# nemoclaw stages only the trivial shim — no parent-dir COPY needed —
# and the layer cache means the pre-build + onboard sequence does the
# heavy work exactly once.
#
# Side benefit: --build-arg GENOMECLAW_HOST_PORT now genuinely flows
# through, so non-8645 ports work end-to-end without the
# "edit-the-script" workaround the original comment described.

SANDBOX_TAG="genomeclaw/sandbox:port-${HOST_PORT}"
echo "[onboard] pre-building sandbox image ${SANDBOX_TAG}"
docker build \
  --build-arg GENOMECLAW_HOST_PORT="${HOST_PORT}" \
  -t "${SANDBOX_TAG}" \
  -f packages/nemoclaw-plugin/sandbox/Dockerfile \
  packages/nemoclaw-plugin/

SHIM_DIR="$(mktemp -d -t genomeclaw-onboard-shim.XXXXXX)"
trap 'rm -rf "${SHIM_DIR}"' EXIT
cat > "${SHIM_DIR}/Dockerfile" <<EOF
# Shim consumed by \`nemoclaw onboard --from\` to sidestep nemoclaw's
# "stage Dockerfile-only" build-context behaviour. The real image
# (${SANDBOX_TAG}) is built by scripts/onboard-sandbox.sh from the
# multi-file Dockerfile at packages/nemoclaw-plugin/sandbox/Dockerfile;
# this shim just re-tags it into nemoclaw's onboarding flow.
FROM ${SANDBOX_TAG}
EOF

echo "[onboard] nemoclaw onboard --from ${SHIM_DIR}/Dockerfile --name genomeclaw"
nemoclaw onboard \
  --fresh \
  --non-interactive \
  --yes \
  --yes-i-accept-third-party-software \
  --recreate-sandbox \
  --from "${SHIM_DIR}/Dockerfile" \
  --name genomeclaw

# ---- step 4: register the GenomeClaw policy preset ------------------------
#
# Default onboard policy allowlists npm / pypi / huggingface / brew.
# The GenomeClaw preset opens host.openshell.internal:<HOST_PORT> so the
# sandbox-side plugin can reach the host genomeclaw-service. The preset
# also lists the RFC1918 IP ranges in `allowed_ips:` — without that,
# OpenShell's hard-coded SSRF guard rejects the resolved internal
# address with `ssrf_denied: internal address` even though the host:port
# is on the policy allowlist. See
# packages/nemoclaw-plugin/policy-preset.yaml.

echo "[onboard] applying GenomeClaw policy preset (host-service egress + SSRF allowlist)"
nemoclaw genomeclaw policy-add \
  --from-file packages/nemoclaw-plugin/policy-preset.yaml \
  --yes

# ---- step 5 (DELETED): hostService.baseUrl + timeoutMs are now Phase-1-baked --
#
# The two `nemoclaw genomeclaw exec --no-tty -- bash -c "openclaw config
# set plugins.entries.genomeclaw.config.hostService.*"` calls that used
# to live here are now redundant: the sandbox Dockerfile bakes both at
# build time (packages/nemoclaw-plugin/sandbox/Dockerfile after the
# onboard-persistent-agent-fix Phase 1 changes — see the `RUN openclaw
# config set ...hostService.baseUrl ...` block). Deleting them avoids
# the EACCES under nemoclaw's exec wrapper that 2026-05-24 surfaced. If
# you ever need to override the baked baseUrl at runtime, do it via
# `docker exec -e HOME=/sandbox --user sandbox <CID> openclaw config set
# ...` (NOT via `nemoclaw genomeclaw exec`) — the latter runs inside
# openshell's filesystem-restriction wrapper that EACCESes on
# /opt/genomeclaw.

# ---- step 6 (DELETED): no more literal-key auth-profiles.json write ---------
#
# nemoclaw-canonical-integration Phase 3, Facet A2 (2026-05-30). This step
# used to render the OpenAI API key into a `"key": "<literal>"` field of
# /sandbox/.openclaw/agents/genomeclaw/agent/auth-profiles.json inside the
# container. The 2026-05-30 privacy-safety review flagged that as HIGH
# severity: the literal key persisted in the container's writable layer
# (readable by any `docker exec --user sandbox`, and it would enter any
# `docker commit`), undermining the Dockerfile's correct env-ref design
# (`models.providers.openai.apiKey` → {source:env, id:OPENAI_API_KEY}).
#
# It is also REDUNDANT: verified empirically (2026-05-30) that the agent
# completes an LLM turn with NO auth-profiles.json present — it resolves the
# credential from the gateway's `models.providers.openai.apiKey` env-ref,
# which is supplied via the gateway's env at launch (Step 7b, `docker exec
# -e OPENAI_API_KEY`, INV-P003-clean). So deleting this write removes a
# durable plaintext-secret footprint with no functional loss.
#
# NOTE (local-Docker credential limitation): the ideal Phase 3 end state —
# nemoclaw's credential store owning the gateway credential via the OpenShell
# L7 inference proxy (inference.local → placeholder rewritten to the real
# secret at egress) — is NOT operational on local Docker: `inference.local`
# does not resolve in the sandbox and no model-router runs there, and
# `nemoclaw inference set` configures the route but its sandbox-sync step
# uses a Kubernetes `kubectl exec` path that fails locally. So the gateway
# still gets the key via Step 7b's env injection (the INV-P003-clean
# `docker exec -e` path), and `nemoclaw recover` cannot self-restore the
# credential on local Docker. Recovery on local Docker re-injects the key
# via scripts/sandbox-up.sh (Phase 4). Tracked as an upstream/infra
# follow-up in docs/plans/active/nemoclaw-canonical-integration/work-notes.md.
#
# Guarded by tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py
# (no literal key written to auth-profiles.json).

echo "[onboard] locating the deployed genomeclaw container"
CID="$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)"
if [[ -z "${CID}" ]]; then
  echo "ERROR: no openshell-genomeclaw-* container found after onboard step 3" >&2
  exit 3
fi
echo "[onboard] container: ${CID}"

# ---- step 7 (DELETED): inference.local rewrite of the agent models.json -----
#
# Removed alongside Step 6 (Facet A2, 2026-05-30). It pointed the agent's
# models.json openai baseUrl at https://inference.local/v1 — but that route
# is non-functional on local Docker (no inference.local DNS / model-router,
# see the Step 6 note). The agent resolves its model calls through the
# gateway's `models.providers.openai` provider (baked baseUrl
# https://api.openai.com/v1 + the env-ref key), so writing a dead
# inference.local baseUrl into the agent config was vestigial and
# misleading. Verified (2026-05-30): the agent completes an LLM turn with
# the gateway provider and no agent-level inference.local override.

# ---- step 7b: start the openclaw gateway with OPENAI_API_KEY in env ---------
#
# Phase 1 baked `models.providers.openai.apiKey` as a ref to OPENAI_API_KEY
# in the gateway process's env. The gateway reads the key at startup;
# we pass it via `docker exec -e` (env, not argv, so it doesn't appear
# in `ps` or in tracebacks of unrelated failures).
#
# We kill any pre-existing gateway first so the new env takes effect.

echo "[onboard] (re)starting openclaw gateway (OPENAI_API_KEY supplied via env, not argv)"
docker exec --user sandbox "${CID}" bash -c 'pkill -f "openclaw gateway" 2>/dev/null; sleep 1' || true
docker exec -d -e HOME=/sandbox -e OPENAI_API_KEY="${OPENAI_API_KEY}" --user sandbox "${CID}" \
  bash -c 'rm -f /tmp/gateway.log; openclaw gateway run > /tmp/gateway.log 2>&1'

echo "[onboard] waiting for gateway to bind 127.0.0.1:18789 (max 30s)"
for _ in $(seq 1 30); do
  # Port-based liveness (the process is named `openclaw`; the old
  # `grep openclaw-gatew` name match was fragile/version-dependent).
  if docker exec --user sandbox "${CID}" bash -c 'ss -lntp 2>/dev/null | grep -q ":18789 "'; then
    echo "[onboard] gateway ready"
    break
  fi
  sleep 1
done

# ---- step 8: smoke test (via docker exec — see comment) ------------------------
#
# Hits `genomeclaw_status` which calls /v1/health on the host service. If
# the host service isn't running this will return `no_active_run` or
# `unreachable` — that's informative, not a failure of onboarding itself.
# Start the host service via `bin/genomeclaw host service` (or natively
# via `GENOMECLAW_NATIVE=1 bin/genomeclaw host service` when colima
# mounts don't cover the derived dir — `host doctor` warns about this).
#
# Historical note (2026-05-25): this used to be `nemoclaw genomeclaw exec
# --no-tty -- bash -c 'openclaw agent ...'`. Two upstream-nemoclaw bugs
# now make that path unusable: (a) the gRPC layer rejects multi-line
# `bash -c` args ("command argument 2 contains newline or carriage
# return characters"), and (b) even single-line bash -c invocations
# can't reach the in-container gateway over WebSocket — the agent
# client's WS connection inside the openshell-exec wrapper is rejected
# even though the gateway is bound on 0.0.0.0:18789 inside the same
# container. We don't fully understand why (b) — likely a kernel-level
# filesystem-or-socket restriction analogous to the /opt/genomeclaw
# EACCES — but `docker exec --user sandbox -e HOME=/sandbox` consistently
# works as the bypass. The path used by the smoke test below is the
# same one the rest of the script uses for config writes, so we know
# it's exercised.

echo "[onboard] smoke test (agent → genomeclaw_status via docker exec)"
SMOKE_REPLY="$(docker exec -i \
  -e HOME=/sandbox \
  -e OPENAI_API_KEY="${OPENAI_API_KEY}" \
  --user sandbox \
  "${CID}" \
  bash -c 'openclaw agent --local --json --agent genomeclaw --message "Smoke test. Call genomeclaw_status and report the active run id in one sentence."' 2>&1)" \
  || echo "[onboard] smoke test exited non-zero — see below; not necessarily a setup failure (host service may not be running yet)"
echo "${SMOKE_REPLY}" | tail -30

echo
echo "[onboard] done. Next steps:"
echo
echo "  1. Start the host service (in another shell, against your active derived run):"
echo "       bin/genomeclaw host service"
echo
echo "  2. Talk to the agent (docker exec is the working path; see step 8 comment for why nemoclaw exec is broken upstream):"
echo "       CID=\$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)"
echo "       docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY=\"\$OPENAI_API_KEY\" --user sandbox \"\$CID\" \\"
echo "         bash -c 'openclaw agent --local --json --agent genomeclaw --message \"...\"'"
echo
echo "  3. Or open the dashboard:"
echo "       nemoclaw genomeclaw dashboard-url"
echo
echo "Sibling project DevRelClaw runs in parallel on port 8643 — both"
echo "agents coexist on one host. See README §'Coexisting with other Claw"
echo "projects on one host' for the port discipline."

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

# ---- step 6 (REWRITTEN): write auth-profiles.json via docker exec stdin ---
#
# Replaces the prior `nemoclaw genomeclaw exec -- python3 -c
# "import base64; ...base64.b64decode('$PROFILE_B64')..."` invocation
# which leaked the operator's API key into a log on the 2026-05-24
# onboard attempt (Python's default traceback prints the entire `-c`
# source string verbatim — including the interpolated $PROFILE_B64 — on
# any failure of the target command, structurally exposing the secret).
#
# The new pattern: render the JSON on Python's stdout, pipe into
# `docker exec -i --user sandbox` with a `cat > .../auth-profiles.json`
# in-container, never letting the payload land on argv. `set +x` guards
# against an upstream `bash -x` that would echo the heredoc body to stderr.
# Enforced by tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py
# (INV-P003 — Secrets via stdin or env, Never via argv).
#
# Required (preceded by onboard step 3): the openshell-genomeclaw-*
# container is running. We bypass `nemoclaw exec` for the write because
# its openshell-sandbox wrapper EACCESes on /opt/genomeclaw (per the
# diagnosis in docs/reports/genomeclaw-demo-questions-2026-05-24.md);
# plain `docker exec --user sandbox` has no such restriction.

echo "[onboard] locating the deployed genomeclaw container"
CID="$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)"
if [[ -z "${CID}" ]]; then
  echo "ERROR: no openshell-genomeclaw-* container found after onboard step 3" >&2
  exit 3
fi
echo "[onboard] container: ${CID}"

echo "[onboard] writing genomeclaw agent auth-profiles.json (OpenAI credential, stdin-only)"
set +x  # defense in depth: keep heredoc body out of any upstream `bash -x` trace
python3 -c '
import json, os
profile = {
    "version": 1,
    "profiles": {
        "openai/gpt-5.5": {"type": "api_key", "provider": "openai", "key": os.environ["OPENAI_API_KEY"]},
        "openai":         {"type": "api_key", "provider": "openai", "key": os.environ["OPENAI_API_KEY"]},
    },
}
print(json.dumps(profile))
' | docker exec -i --user sandbox -e HOME=/sandbox "${CID}" \
      bash -c 'mkdir -p /sandbox/.openclaw/agents/genomeclaw/agent && cat > /sandbox/.openclaw/agents/genomeclaw/agent/auth-profiles.json'

# ---- step 7 (REWRITTEN): route the openai provider through inference.local ----
#
# Carries no secret (just a baseUrl string) so INV-P003 doesn't strictly
# require this rewrite — but it does need to switch off `nemoclaw exec`
# for the same EACCES reason that broke step 5/6.

echo "[onboard] pointing genomeclaw openai provider at inference.local"
docker exec -i --user sandbox -e HOME=/sandbox "${CID}" \
  python3 -c "
import json, os
p = '/sandbox/.openclaw/agents/genomeclaw/agent/models.json'
d = json.load(open(p)) if os.path.exists(p) else {}
d.setdefault('providers', {}).setdefault('openai', {})['baseUrl'] = 'https://inference.local/v1'
json.dump(d, open(p, 'w'), indent=2)
"

# ---- step 7b (NEW): start the openclaw gateway with OPENAI_API_KEY in env ----
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

echo "[onboard] waiting for gateway to bind 0.0.0.0:18789 (max 30s)"
for _ in $(seq 1 30); do
  if docker exec --user sandbox "${CID}" bash -c 'ss -lntp 2>/dev/null | grep -q openclaw-gatew'; then
    echo "[onboard] gateway ready"
    break
  fi
  sleep 1
done

# ---- step 8 (UNCHANGED-ish): smoke test ---------------------------------------
#
# Hits `genomeclaw_status` which calls /v1/health on the host service. If
# the host service isn't running this will return `no_active_run` or
# `unreachable` — that's informative, not a failure of onboarding itself.
# Start the host service via `bin/genomeclaw host service` in another
# shell before issuing real questions.
#
# The smoke test uses `nemoclaw genomeclaw exec` because the openshell
# wrapper's EACCES on /opt/genomeclaw doesn't bite for `openclaw agent`
# (the agent client talks to the already-running gateway over WebSocket
# and doesn't scandir /opt).

echo "[onboard] smoke test (agent → genomeclaw_status → host service health)"
nemoclaw genomeclaw exec --no-tty --timeout 240 -- bash -c \
  'openclaw agent --local --json --agent genomeclaw \
     --message "Smoke test. Call genomeclaw_status and report back in one sentence."' \
  | tail -20 || echo "[onboard] smoke test exited non-zero — see above; not necessarily a setup failure (host service may not be running yet)"

echo
echo "[onboard] done. Next steps:"
echo
echo "  1. Start the host service (in another shell, against your active derived run):"
echo "       bin/genomeclaw host service"
echo
echo "  2. Talk to the agent:"
echo "       nemoclaw genomeclaw exec --no-tty --timeout 240 -- bash -c 'openclaw agent --local --json --agent genomeclaw --message \"...\"'"
echo
echo "  3. Or open the dashboard:"
echo "       nemoclaw genomeclaw dashboard-url"
echo
echo "Sibling project DevRelClaw runs in parallel on port 8643 — both"
echo "agents coexist on one host. See README §'Coexisting with other Claw"
echo "projects on one host' for the port discipline."

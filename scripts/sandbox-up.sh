#!/usr/bin/env bash
# scripts/sandbox-up.sh — bring the GenomeClaw sandbox to a usable state.
#
# Usage (from repo root):
#   ./scripts/sandbox-up.sh             # smart mode: rebuild only if needed
#   ./scripts/sandbox-up.sh --rebuild   # force full onboard (delegates to onboard-sandbox.sh)
#
# What "usable" means:
#   1. A container `openshell-genomeclaw-*` is running.
#   2. The genomeclaw plugin loads (no `failed to read extensions dir` warning).
#   3. The openclaw gateway is up with OPENAI_API_KEY in its env.
#
# "This does not happen again": before today (2026-05-28) the sandbox could
# silently drift into a state where the gateway died with `OPENAI_API_KEY is
# missing` or the plugin had EACCES on /opt/genomeclaw — neither of which is
# self-healing. This script makes the recovery path one command, sourced from
# the repo's .env so secrets never live in argv (INV-P003).
#
# Reads from .env (repo root):
#   OPEN_AI_API_KEY  → exported as OPENAI_API_KEY for the gateway env.
#
# Companion script: scripts/onboard-sandbox.sh (canonical full reset; this
# script delegates to it when a fresh build is needed).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FORCE_REBUILD=0
if [[ "${1:-}" == "--rebuild" ]]; then
  FORCE_REBUILD=1
fi

# ---- step 0: load .env --------------------------------------------------------

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

# ---- step 1: locate / check the running sandbox container ---------------------

CID="$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1 || true)"

if [[ -z "${CID}" || "${FORCE_REBUILD}" -eq 1 ]]; then
  echo "[sandbox-up] no running container (or --rebuild requested) — delegating to scripts/onboard-sandbox.sh"
  exec "${REPO_ROOT}/scripts/onboard-sandbox.sh"
fi
echo "[sandbox-up] running container: ${CID}"

# ---- step 2: is the plugin readable at the canonical path? --------------------
#
# The plugin now lives at /sandbox/build/genomeclaw (Phase 2 — inside the
# OpenShell Landlock RW baseline). The pre-2026-05-29 broken state had the
# plugin under /opt/genomeclaw, OUTSIDE the baseline, which EACCESed for every
# NemoClaw-managed surface. That class of failure is gone, but a stale image
# (older tag, missing dist/) is still possible — if the compiled entrypoint
# isn't readable, only a rebuild fixes it.

if ! docker exec --user sandbox -e HOME=/sandbox "${CID}" \
      test -r /sandbox/build/genomeclaw/dist/index.js; then
  echo "[sandbox-up] plugin entrypoint not readable at /sandbox/build/genomeclaw/dist/index.js"
  echo "[sandbox-up] (stale image?) — delegating to scripts/onboard-sandbox.sh for a full rebuild"
  exec "${REPO_ROOT}/scripts/onboard-sandbox.sh"
fi
echo "[sandbox-up] plugin entrypoint readable at /sandbox/build/genomeclaw"

# ---- step 3: is the gateway running? -----------------------------------------
#
# Liveness is detected by PORT (127.0.0.1:18789), not the process name — the
# gateway process is named `openclaw`, so the old `grep openclaw-gatew` match
# was fragile/version-dependent.

gateway_listening() {
  docker exec --user sandbox "${CID}" bash -c 'ss -lntp 2>/dev/null | grep -q ":18789 "'
}

GATEWAY_OK=0
if gateway_listening; then
  GATEWAY_OK=1
fi

if [[ "${GATEWAY_OK}" -eq 1 ]]; then
  echo "[sandbox-up] gateway already listening on :18789"
else
  # Best-effort supervised recovery first. On a remote/GPU deployment with the
  # OpenShell inference proxy wired up, `nemoclaw recover` brings the gateway
  # back with the credential attached at egress. On LOCAL DOCKER this does NOT
  # work — the gateway relaunch doesn't inject OPENAI_API_KEY and inference.local
  # isn't routed (see Phase 3 work-notes) — so we treat it as best-effort and
  # fall through to the keyed docker-exec restart, which is the sanctioned
  # local-Docker recovery (INV-P003-clean: key via env `-e`, never argv).
  echo "[sandbox-up] gateway down — trying supervised recovery (nemoclaw connect --probe-only, best-effort)"
  nemoclaw genomeclaw connect --probe-only >/dev/null 2>&1 || true
  sleep 2
  if gateway_listening; then
    echo "[sandbox-up] gateway recovered via nemoclaw"
    GATEWAY_OK=1
  fi
fi

if [[ "${GATEWAY_OK}" -ne 1 ]]; then
  echo "[sandbox-up] starting gateway directly with OPENAI_API_KEY in env (never argv; INV-P003)"
  echo "[sandbox-up]   (local-Docker recovery path — nemoclaw recover can't inject the credential here)"
  docker exec --user sandbox "${CID}" bash -c 'pkill -f "openclaw gateway" 2>/dev/null; sleep 1' || true
  docker exec -d -e HOME=/sandbox -e OPENAI_API_KEY="${OPENAI_API_KEY}" --user sandbox "${CID}" \
    bash -c 'rm -f /tmp/gateway.log; openclaw gateway run > /tmp/gateway.log 2>&1'

  echo "[sandbox-up] waiting for gateway to bind :18789 (max 30s)"
  for _ in $(seq 1 30); do
    if gateway_listening; then
      echo "[sandbox-up] gateway ready"
      GATEWAY_OK=1
      break
    fi
    sleep 1
  done
  if [[ "${GATEWAY_OK}" -ne 1 ]]; then
    echo "ERROR: gateway failed to start within 30s. Tail of /tmp/gateway.log:" >&2
    docker exec --user sandbox "${CID}" bash -c 'tail -40 /tmp/gateway.log' >&2 || true
    exit 4
  fi
fi

# ---- step 4: report state -----------------------------------------------------

echo
echo "[sandbox-up] sandbox ready."
echo "  container: ${CID}"
echo "  agent CLI: docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY=\"\$OPENAI_API_KEY\" --user sandbox \"${CID}\" \\"
echo "             bash -c 'openclaw agent --local --json --agent genomeclaw --message \"...\"'"
echo
echo "  to force a full rebuild (new prompt / plugin / image): ./scripts/sandbox-up.sh --rebuild"

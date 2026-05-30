#!/usr/bin/env bash
# scripts/ask.sh — send a single message to the GenomeClaw agent over CLI.
#
# Usage (from repo root):
#   ./scripts/ask.sh "your question here"
#   ./scripts/ask.sh --capture "your question here"   # also save trace + trajectory
#
# Wraps the canonical docker-exec invocation per CLAUDE.md § Running the
# Agent Locally. Bypasses the nemoclaw dashboard port-forward + the
# `nemoclaw genomeclaw exec` upstream bug; goes straight to the gateway
# inside the openshell-genomeclaw-* container.
#
# Prereqs:
#   - .env at repo root with OPEN_AI_API_KEY set
#   - sandbox running (./scripts/sandbox-up.sh once if needed)
#
# Outputs:
#   - default: streams the agent's reply JSON to stdout
#   - --capture: saves trace + trajectory under docs/reports/demo-<date>-logs/
#     and prints the reply text to stdout

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CAPTURE=0
if [[ "${1:-}" == "--capture" ]]; then
  CAPTURE=1
  shift
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: ./scripts/ask.sh [--capture] \"your question\"" >&2
  exit 1
fi
MESSAGE="$*"

# ---- load .env -------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found at $REPO_ROOT/.env" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source ./.env; set +a
if [[ -z "${OPEN_AI_API_KEY:-}" ]]; then
  echo "ERROR: OPEN_AI_API_KEY not set in .env" >&2
  exit 1
fi
export OPENAI_API_KEY="$OPEN_AI_API_KEY"

# ---- locate the sandbox container -----------------------------------------
CID="$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1 || true)"
if [[ -z "${CID}" ]]; then
  echo "ERROR: no running openshell-genomeclaw-* container." >&2
  echo "  Bring one up with: ./scripts/sandbox-up.sh" >&2
  exit 2
fi

# ---- send the message -----------------------------------------------------
if [[ $CAPTURE -eq 1 ]]; then
  DATE="$(date +%Y-%m-%d)"
  LOGS_DIR="docs/reports/demo-${DATE}-logs"
  mkdir -p "$LOGS_DIR"
  # File-name slug from first 6 words, lowercase, dashes
  SLUG="$(echo "$MESSAGE" | head -c 80 | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/-$//')"
  if [[ -z "$SLUG" ]]; then SLUG="ask"; fi
  TRACE="${LOGS_DIR}/${SLUG}.trace.json"
  TRAJECTORY="${LOGS_DIR}/${SLUG}.trajectory.jsonl"

  echo "[ask] sending to ${CID}; trace -> ${TRACE}" >&2
  docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY="$OPENAI_API_KEY" --user sandbox "$CID" \
    openclaw agent --local --json --agent genomeclaw --message "$MESSAGE" \
    > "$TRACE" 2>&1
  RC=$?

  # Strip the plugin-loader log prefix if present (JSON envelope often starts a few lines down)
  JSON_START_LINE="$(grep -n '^{' "$TRACE" | head -1 | cut -d: -f1 || true)"
  if [[ -n "$JSON_START_LINE" && "$JSON_START_LINE" != "1" ]]; then
    tail -n +"$JSON_START_LINE" "$TRACE" | python3 -m json.tool > "${TRACE}.tmp" 2>/dev/null \
      && mv "${TRACE}.tmp" "$TRACE" \
      || rm -f "${TRACE}.tmp"
  fi

  # Capture the sibling trajectory (per-tool-call records)
  LATEST="$(docker exec --user sandbox "$CID" bash -c 'ls -t /sandbox/.openclaw/agents/genomeclaw/sessions/*.trajectory.jsonl 2>/dev/null | head -1' || true)"
  if [[ -n "$LATEST" ]]; then
    docker cp "$CID":"$LATEST" "$TRAJECTORY" 2>/dev/null || true
    echo "[ask] trajectory -> ${TRAJECTORY}" >&2
  fi

  # Print the reply
  python3 -c "
import json, sys
with open('$TRACE') as f:
    t = json.load(f)
print(t.get('result', t).get('meta', {}).get('finalAssistantVisibleText', ''))
" 2>/dev/null || cat "$TRACE"

  exit $RC
else
  # No capture — stream the raw JSON directly
  docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY="$OPENAI_API_KEY" --user sandbox "$CID" \
    openclaw agent --local --json --agent genomeclaw --message "$MESSAGE"
fi

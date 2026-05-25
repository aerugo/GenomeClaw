#!/usr/bin/env bash
# Round-2 demo runner — asks the 5 layman questions through the
# PERSISTENT nemoclaw genomeclaw sandbox (not the ephemeral live-smoke
# harness). Bypasses `nemoclaw genomeclaw exec` (which the openshell
# sandbox wrapper EACCESes on /opt/genomeclaw) in favor of plain
# `docker exec --user sandbox -e HOME=/sandbox -e OPENAI_API_KEY=...`.
#
# Prereqs (already in place when this runs):
#   - persistent sandbox container named openshell-genomeclaw-* up + healthy
#   - openclaw gateway running inside it (pid visible in `docker exec ps -ef`)
#   - native host service on 127.0.0.1:8645 serving the active derived run
#   - .env with OPEN_AI_API_KEY
#
# Usage (from repo root):
#   bash docs/reports/demo-2026-05-24-logs/runner_round2.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
set -a; source .env; set +a
export OPENAI_API_KEY="$OPEN_AI_API_KEY"

CID="$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)"
if [[ -z "$CID" ]]; then
  echo "ERROR: no openshell-genomeclaw-* container found. Run scripts/onboard-sandbox.sh first." >&2
  exit 1
fi
echo "[round2] container: $CID"

LOG_DIR="$REPO_ROOT/docs/reports/demo-2026-05-24-logs"
mkdir -p "$LOG_DIR"

RUN_LOG="$LOG_DIR/04-runner-round2.log"
SUMMARY_JSON="$LOG_DIR/05-summary-round2.json"
: > "$RUN_LOG"
: > "$SUMMARY_JSON"
echo "[" > "$SUMMARY_JSON"

log() {
  local stamp; stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '[%s] %s\n' "$stamp" "$*" | tee -a "$RUN_LOG"
}

run_q() {
  local slug="$1"; shift
  local question="$1"; shift
  local trace_file="$LOG_DIR/round2-${slug}.trace.json"
  local reply_file="$LOG_DIR/round2-${slug}.reply.txt"
  local raw_file="$LOG_DIR/round2-${slug}.raw.txt"
  log "--- $slug START ---"
  log "Q: $question"
  local t0; t0=$(date +%s)
  # Run agent; capture combined stdout+stderr to raw_file (which may carry
  # node warnings + the JSON envelope). Extract JSON afterwards.
  local rc=0
  docker exec -i \
    -e HOME=/sandbox \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    --user sandbox \
    "$CID" \
    bash -c "openclaw agent --local --json --agent genomeclaw --timeout 360 --message $(printf %q "$question")" \
    > "$raw_file" 2>&1 || rc=$?
  local elapsed=$(( $(date +%s) - t0 ))
  if [[ $rc -ne 0 ]]; then
    log "$slug FAILED rc=$rc after ${elapsed}s — see $raw_file"
    cat >> "$SUMMARY_JSON" <<EOF
  { "slug": "$slug", "status": "error", "rc": $rc, "elapsed_s": $elapsed, "raw_file": "round2-${slug}.raw.txt" },
EOF
    return
  fi
  # Parse JSON (it may be preceded by node warnings).
  python3 - <<PY > /tmp/round2-extract.json 2>/dev/null || true
import json, re, sys
raw = open("$raw_file").read()
m = re.search(r'\{[\s\S]*\}', raw)
if not m: sys.exit(1)
t = json.loads(m.group(0))
result = t.get('result') or t
payloads = result.get('payloads', [])
reply_chunks = []
for p in payloads:
    if isinstance(p, dict) and isinstance(p.get('text'), str):
        reply_chunks.append(p['text'])
reply = '\n\n'.join(reply_chunks).strip()
meta = result.get('meta', {})
ts = meta.get('toolSummary', {})
out = {
    "trace": t,
    "reply": reply,
    "tools": ts.get('tools', []),
    "calls": ts.get('calls', 0),
    "failures": ts.get('failures', 0),
    "duration_ms_agent": meta.get('durationMs'),
}
json.dump(out, open("/tmp/round2-extract.json", "w"))
PY
  if [[ ! -s /tmp/round2-extract.json ]]; then
    log "$slug FAILED to parse JSON after ${elapsed}s — see $raw_file"
    cat >> "$SUMMARY_JSON" <<EOF
  { "slug": "$slug", "status": "parse_error", "elapsed_s": $elapsed, "raw_file": "round2-${slug}.raw.txt" },
EOF
    return
  fi
  python3 -c "
import json
d = json.load(open('/tmp/round2-extract.json'))
open('$trace_file', 'w').write(json.dumps(d['trace'], indent=2))
open('$reply_file', 'w').write(d['reply'])
print('OK',
      'reply_chars=' + str(len(d['reply'])),
      'tools=' + ','.join(d['tools']),
      'calls=' + str(d['calls']),
      'failures=' + str(d['failures']),
      'agent_ms=' + str(d['duration_ms_agent']))
" | while read -r line; do log "$slug $line wall_s=$elapsed"; done
  python3 -c "
import json
d = json.load(open('/tmp/round2-extract.json'))
print(json.dumps({
    'slug': '$slug',
    'status': 'ok',
    'wall_elapsed_s': $elapsed,
    'agent_duration_ms': d['duration_ms_agent'],
    'reply_chars': len(d['reply']),
    'tool_calls': d['calls'],
    'tools': d['tools'],
    'failures': d['failures'],
    'trace_file': 'round2-$slug.trace.json',
    'reply_file': 'round2-$slug.reply.txt',
}, indent=2))
" >> "$SUMMARY_JSON"
  echo "," >> "$SUMMARY_JSON"
}

log "host service /v1/health check"
curl -sf --max-time 3 http://127.0.0.1:8645/v1/health > /dev/null \
  || { log "host service unreachable — abort"; exit 2; }

run_q "q1-serious-risk" \
  "Is there anything serious in my DNA I should know about — something I should bring up with a doctor?"
run_q "q2-drug-response" \
  "Are there any common medications I'd react to differently than most people, based on my genes?"
run_q "q3-diabetes" \
  "Based on my DNA, am I more or less likely than average to develop type-2 diabetes?"
run_q "q4-caffeine" \
  "How well do I handle caffeine? Should I cut off coffee earlier in the day?"
run_q "q5-alzheimers" \
  "Is my risk of getting Alzheimer's disease higher or lower than most people's?"

# Trim trailing comma + close summary array.
sed -i '' -e '$s/,$//' "$SUMMARY_JSON" 2>/dev/null || sed -i -e '$s/,$//' "$SUMMARY_JSON" || true
echo "]" >> "$SUMMARY_JSON"

log "--- round2 done ---"

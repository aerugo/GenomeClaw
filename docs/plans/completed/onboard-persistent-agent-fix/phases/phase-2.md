# Phase 2: Onboard Script — stdin for Secrets, Explicit Gateway Start, Delete Dead Config Calls

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Rewrite `scripts/onboard-sandbox.sh` so that (a) every post-install `openclaw config set` that was failing under nemoclaw's exec wrapper is deleted (Phase 1 baked them), (b) the auth-profile and models.json patches are written via `docker exec -i ... cat > ...` reading JSON from stdin (no argv interpolation of secrets), (c) the gateway is started explicitly via `docker exec -d -e OPENAI_API_KEY=...`, and (d) `./scripts/onboard-sandbox.sh` succeeds end-to-end on a fresh host with `nemoclaw list` then showing a healthy `genomeclaw` sandbox.

## Scope Boundaries

- **In scope**: edits to `scripts/onboard-sandbox.sh`; two new test files (the discovery test for INV-P003 and the live integration test); promoting `INV-P003` into `docs/reference/INVARIANTS.md` after tests are green.
- **Out of scope**: the Dockerfile bakes (Phase 1 — prerequisite, must be complete before Phase 2 starts); the colima-mounts doctor check (Phase 3); making the upstream `nemoclaw inference set --provider openai-api` path work (out of our control).

## Invariants Enforced in This Phase

- **INV-P001** Privacy Is the Default Operating Mode — the script no longer puts the operator's OpenAI API key on a command-line argv; the existing privacy-default tests continue to pass.
- **NEW INV-P003** Secrets via stdin/env Never argv — proposed in [spec.md](../spec.md); promoted into [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) after this phase's tests are green.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases**:

1. `test_invP003_onboard_script_has_no_python_dash_c_base64_argv` (`tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py`) — read `scripts/onboard-sandbox.sh`; grep for the pattern `python3 -c.*b64decode.*\$` (or any `python -c .* \$[A-Z_]+_(B64|KEY|TOKEN|SECRET)`); assert zero matches. RED today because the script still has the `nemoclaw genomeclaw exec ... python3 -c "import base64; ...base64.b64decode('$PROFILE_B64').decode()..."` line.
2. `test_invP003_onboard_script_has_no_bash_dash_c_with_interpolated_key` — grep for `bash -c.*\$.*KEY` and `bash -c.*\$.*SECRET`; assert zero matches.
3. `test_invP003_discovery_no_argv_secret_patterns_across_scripts_dir` — walk every `.sh` file in `scripts/`; apply both patterns; assert zero matches across all of them. This is the structural floor; it catches future script additions that re-introduce the pattern.
4. `test_invP003_onboard_script_writes_authprofile_via_stdin` — grep for the positive shape: `docker exec -i.*\.openclaw/agents/genomeclaw/agent/auth-profiles\.json` AND `cat > .*auth-profiles\.json` in the same script. Assert both present. This is the positive complement to tests 1+2.
5. `test_live_onboard_persistent_agent_one_shot` (`tests/integration/test_live_onboard_persistent_agent.py`, gated `@pytest.mark.live_onboard`) — runs `./scripts/onboard-sandbox.sh` against a throwaway sandbox name (`genomeclaw-test`), asserts: (a) script exit code 0, (b) `nemoclaw list` output contains `genomeclaw-test` with `healthy` status, (c) a one-shot agent call returns `status=ok` + ≥1 tool call, (d) `docker exec` reads back `/sandbox/.openclaw/agents/genomeclaw/agent/auth-profiles.json` as valid JSON with a non-empty `profiles.openai/gpt-5.5.key` field, (e) after the test, `nemoclaw genomeclaw destroy --name genomeclaw-test` cleans up. Skipped in CI without `OPENAI_API_KEY + GENOMECLAW_SANDBOX_IMAGE` env vars; gated by an additional `GENOMECLAW_LIVE_ONBOARD=1` opt-in so it doesn't run unintentionally even with the API key present (the test mutates the local nemoclaw state).

**Test sketch**:

```python
"""INV-P003 (proposed): operator-supplied secrets never reach a subprocess
via argv. Discovery test across scripts/ + per-pattern negative test on
the onboarding script that surfaced the 2026-05-24 leak.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
ONBOARD_SCRIPT = SCRIPTS_DIR / "onboard-sandbox.sh"

# Patterns that historically (or canonically) ship a secret through argv.
_FORBIDDEN_ARGV_PATTERNS: tuple[re.Pattern[str], ...] = (
    # python3 -c "...base64.b64decode('$<NAME>_B64')..."
    re.compile(r"python3?\s+-c\s+.*b64decode\(['\"]\$"),
    # bash -c "... $<NAME>_KEY ..." or "... $<NAME>_SECRET ..." or "... $<NAME>_TOKEN ..."
    re.compile(r"bash\s+-c\s+['\"][^'\"]*\$[A-Z_]*(?:KEY|SECRET|TOKEN)"),
    # --key $<NAME>_KEY or --secret $<NAME>_SECRET — argv flag interpolation
    re.compile(r"--(?:key|secret|token|password)[=\s]+\$"),
)


def test_invP003_onboard_script_has_no_argv_secret_patterns() -> None:
    """The auth-profile-write step that leaked the API key in 2026-05-24 must stay closed."""
    text = ONBOARD_SCRIPT.read_text()
    matches = [
        (i, line) for i, line in enumerate(text.splitlines(), start=1)
        for p in _FORBIDDEN_ARGV_PATTERNS if p.search(line)
    ]
    assert not matches, (
        f"INV-P003: {ONBOARD_SCRIPT.relative_to(REPO_ROOT)} still has argv-interpolated secret patterns:\n"
        + "\n".join(f"  L{i}: {line.strip()[:120]}" for i, line in matches)
    )


def test_invP003_discovery_no_argv_secret_patterns_across_scripts_dir() -> None:
    """Structural floor: every .sh under scripts/ is clean of argv-secret patterns."""
    offenders: list[tuple[Path, int, str]] = []
    for script in SCRIPTS_DIR.rglob("*.sh"):
        for i, line in enumerate(script.read_text().splitlines(), start=1):
            for p in _FORBIDDEN_ARGV_PATTERNS:
                if p.search(line):
                    offenders.append((script.relative_to(REPO_ROOT), i, line.strip()))
    assert not offenders, (
        "INV-P003 violations:\n" + "\n".join(f"  {p}:{i}  {l[:120]}" for p, i, l in offenders)
    )


def test_invP003_onboard_script_writes_authprofile_via_stdin() -> None:
    """Positive complement: the auth-profile must be written via docker exec stdin, not argv."""
    text = ONBOARD_SCRIPT.read_text()
    assert re.search(
        r"docker\s+exec\s+(?:-[a-zA-Z]+\s+)*-i\b[^\n]*?auth-profiles\.json", text,
    ), "expected `docker exec -i ... auth-profiles.json` pattern in onboard-sandbox.sh"
    assert "cat > " in text and "auth-profiles.json" in text, (
        "expected `cat > ... auth-profiles.json` heredoc/stdin shape"
    )
```

After writing the tests, run them and **confirm they fail for the intended reason**. The discovery test should turn up at least one offender on the existing script (the `python3 -c "import base64..." $PROFILE_B64` line at ~L194 and the similar models.json patch at ~L200). Paste the failing output into `work-notes.md`.

### Step 2.2 — GREEN: Minimal Implementation

Rewrite the relevant section of `scripts/onboard-sandbox.sh`. The structure becomes:

```bash
# ---- step 4 (deleted): policy preset application stays as-is ----------------
# (kept; works under nemoclaw genomeclaw policy-add which doesn't go through the exec wrapper)

# ---- step 5 (DELETED): hostService.baseUrl + timeoutMs were Phase-1-baked ---
#
# The two `nemoclaw genomeclaw exec --no-tty -- bash -c "openclaw config
# set plugins.entries.genomeclaw.config.hostService.*"` calls that used
# to live here are now redundant: the sandbox Dockerfile bakes both at
# build time (see packages/nemoclaw-plugin/sandbox/Dockerfile after the
# Phase 1 changes, the `RUN openclaw config set ...hostService.baseUrl
# ...` block). Deleting them avoids the EACCES under nemoclaw's exec
# wrapper that 2026-05-24 surfaced. If someone reintroduces a runtime
# need to override the baked baseUrl, do it via `docker exec -e
# HOME=/sandbox --user sandbox <CID> openclaw config set ...` (not via
# `nemoclaw genomeclaw exec`) so it actually succeeds.

# ---- step 6 (REWRITTEN): write auth-profiles.json via docker exec stdin ----
#
# Replaces the prior `nemoclaw genomeclaw exec -- python3 -c
# "...base64.b64decode('$PROFILE_B64')..."` invocation which leaked
# the operator's API key into a log on the 2026-05-24 onboard attempt
# (the python3 -c source string is echoed in tracebacks by default).
#
# Stdin-based writes keep the JSON payload off argv. The container is
# already up (nemoclaw onboard step 3 spawned it); we use plain
# `docker exec --user sandbox` to bypass nemoclaw's exec wrapper
# (which EACCESes on /opt/genomeclaw — see the report at
# docs/reports/genomeclaw-demo-questions-2026-05-24.md).

echo "[onboard] writing genomeclaw agent auth-profiles.json (OpenAI credential, stdin-only)"
CID="$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)"
if [[ -z "${CID}" ]]; then
  echo "ERROR: no openshell-genomeclaw-* container found after onboard" >&2
  exit 3
fi

# Render the JSON on stdout, pipe into docker exec -i, never let it land on argv.
# set +x guards against an upstream `set -x` that would echo the heredoc body to stderr.
set +x
python3 - <<'PY' | docker exec -i --user sandbox -e HOME=/sandbox "${CID}" \
  bash -c "mkdir -p /sandbox/.openclaw/agents/genomeclaw/agent && \
           cat > /sandbox/.openclaw/agents/genomeclaw/agent/auth-profiles.json"
import json, os
profile = {
    "version": 1,
    "profiles": {
        "openai/gpt-5.5": {"type": "api_key", "provider": "openai", "key": os.environ["OPENAI_API_KEY"]},
        "openai":         {"type": "api_key", "provider": "openai", "key": os.environ["OPENAI_API_KEY"]},
    },
}
print(json.dumps(profile))
PY

# ---- step 7 (REWRITTEN): models.json inference.local routing via docker exec stdin ----
echo "[onboard] routing genomeclaw openai provider through inference.local"
docker exec -i --user sandbox -e HOME=/sandbox "${CID}" \
  python3 -c 'import json, sys
p = "/sandbox/.openclaw/agents/genomeclaw/agent/models.json"
d = json.load(open(p)) if __import__("os").path.exists(p) else {}
d.setdefault("providers", {}).setdefault("openai", {})["baseUrl"] = "https://inference.local/v1"
json.dump(d, open(p, "w"), indent=2)
'
# Note: this python3 -c carries NO secret in its argv — only a baseUrl string.
# That makes it safe under INV-P003. The discovery test's pattern targets
# argv invocations that interpolate $<NAME>_<KEY|TOKEN|SECRET|B64>, not any
# python -c.

# ---- step 7b (NEW): start the gateway with OPENAI_API_KEY in its env --------
#
# The bake (Phase 1) configured `models.providers.openai.apiKey` as a
# ref to OPENAI_API_KEY in the gateway process's env. The gateway needs
# the env var present at startup time; we pass it via `docker exec -e`
# which is env-not-argv, so it doesn't appear in ps or in tracebacks.

echo "[onboard] starting openclaw gateway (OPENAI_API_KEY supplied via env, not argv)"
docker exec --user sandbox "${CID}" bash -c 'pkill -f "openclaw gateway" 2>/dev/null; sleep 1' || true
docker exec -d -e HOME=/sandbox -e OPENAI_API_KEY="${OPENAI_API_KEY}" --user sandbox "${CID}" \
  bash -c 'rm -f /tmp/gateway.log; openclaw gateway run > /tmp/gateway.log 2>&1'

# Wait for ready
echo "[onboard] waiting for gateway to bind 0.0.0.0:18789"
for _ in $(seq 1 30); do
  if docker exec --user sandbox "${CID}" bash -c 'ss -lntp 2>/dev/null | grep -q openclaw-gatew'; then
    echo "[onboard] gateway ready"
    break
  fi
  sleep 1
done

# ---- step 8 (UNCHANGED): smoke test stays via nemoclaw genomeclaw exec ------
# That path works for `openclaw agent --local` because the agent client
# talks to the already-running gateway over WebSocket; it doesn't scandir
# /opt/genomeclaw so the openshell EACCES doesn't bite.
```

**Files affected**:
- `scripts/onboard-sandbox.sh`: rewrite ~step-5-through-step-8 section per above. Net diff: ~50 lines added (new step 7b + reorganized steps 5/6/7), ~25 lines deleted (the now-baked config-set calls).

### Step 2.3 — REFACTOR

With tests green:

- Extract the JSON-via-stdin pattern into a helper `_docker_exec_write_file(cid, path, content_on_stdin)` if it's used in more than one place (rule of three — currently 2 uses: auth-profiles.json + models.json patch. Don't extract yet).
- Confirm the `set +x` guards are placed correctly (immediately before the secret-touching block, with a `set -x`-restore at the end if the script started with -x; safer to leave them locally scoped to the secret-touching subshell).
- Promote `INV-P003` into `docs/reference/INVARIANTS.md`:
  - Pick the next `INV-P` number (P001 = privacy default, P002 = agent egress → P003).
  - Fill Rule / Requirements / Where it applies / How to verify per the spec's proposed text.
  - Bump Version + Last Updated.
  - Add an Invariant Index entry.
- Update `README.md`'s "Sandbox setup" section to reflect the new flow (the `nemoclaw exec ... openclaw config set` steps are gone; the `docker exec -i ... cat > ...` pattern is documented).

---

## Implementation Details

### The set +x guard

If an operator runs the script with `bash -x ./scripts/onboard-sandbox.sh`, every interpolated value would echo to stderr including the heredoc body. The `set +x` guard before the heredoc + `set -x` after (only if it was on) keeps the secret out of trace output. Alternative: write the JSON to a temp file with restrictive permissions, then `cat <tmpfile> | docker exec -i`, but that creates a file on the host filesystem briefly — defense-in-depth says less time on disk is better.

### Why models.json patch is also rewritten

The current models.json patch uses `nemoclaw genomeclaw exec --no-tty -- python3 -c "import json; ..."`. The `python3 -c` contains no secret (just `https://inference.local/v1`), so INV-P003 doesn't strictly require rewriting it. **But** the `nemoclaw genomeclaw exec` wrapper still hits the openshell EACCES, so the call fails for the same reason the config-set calls did. The rewrite to `docker exec --user sandbox` is required for *correctness*, not for *security* — but it's adjacent enough to bundle into this phase.

### Edge Cases to Handle

- **Container not found**: if `docker ps --filter 'name=openshell-genomeclaw-'` returns empty, something earlier failed. The script exits 3 with an error message.
- **OPENAI_API_KEY missing**: the existing script already checks `OPEN_AI_API_KEY` is set in `.env` and exports it as `OPENAI_API_KEY`. No new check needed.
- **Multiple `openshell-genomeclaw-*` containers**: if the operator has previously onboarded then re-onboarded without `nemoclaw genomeclaw destroy`, there could be two. The `head -1` is defensive; in practice `--fresh --recreate-sandbox` removes the old one before creating the new one.
- **Gateway never binds**: the wait-for-ready loop is 30 seconds. If it doesn't bind, the smoke test in step 8 will fail and the operator gets a useful error.

### Error Handling

- All `docker exec` calls fail loud via `set -e` at the top of the script.
- The `set +x` block is scoped local to the secret-touching subshell.

### Privacy / Egress Notes

- Phase 2 is the load-bearing privacy improvement of this whole plan. After it lands:
  - No argv on any process carries the OpenAI API key.
  - The key reaches the running gateway via `docker exec -e` (env, not argv).
  - The key reaches the container's filesystem (`auth-profiles.json`) via stdin (`docker exec -i ... cat > ...`).
  - If any of these steps crash, the traceback may contain *paths* and *bash commands* but never the key value.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `scripts/onboard-sandbox.sh` | MODIFY | Rewrite steps 5–8 per Step 2.2. |
| `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` | CREATE | Discovery + per-pattern + positive-shape tests for INV-P003. |
| `packages/toolkit/tests/integration/test_live_onboard_persistent_agent.py` | CREATE | `@pytest.mark.live_onboard`-gated end-to-end test. |
| `packages/toolkit/conftest.py` (or `tests/conftest.py`) | MODIFY (maybe) | Register the `live_onboard` mark + add an env-var gate. |
| `docs/reference/INVARIANTS.md` | MODIFY | Promote `INV-P003` per the spec's proposed text. Bump Version. |
| `README.md` | MODIFY | (1) Delete step 5 of "Sandbox setup — the GenomeClaw NemoClaw agent" (Phase 1 bakes it); renumber. (2) Fix the inaccurate "never lands in argv" claim in step 6 — current wording describes a property the pre-Phase-2 code did not have (proven by the 2026-05-24 leak); Phase 2 makes it true. (3) Add step 7b for the explicit gateway-start. (4) Add a "Gateway start blocked: existing config is missing `gateway.mode`" entry to Troubleshooting. See development-plan.md's "Documentation Updates" section for the full sub-bullet list. |
| `.claude/agents/privacy-safety-reviewer.md` | MODIFY | Add `INV-P003` to the agent's invariant coverage list. |

---

## Verification

```bash
# Run Phase 2 unit tests
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py -v

# Run the live-onboard integration test (manual gate)
GENOMECLAW_LIVE_ONBOARD=1 OPENAI_API_KEY=... GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:port-8645 \
  .venv/bin/pytest tests/integration/test_live_onboard_persistent_agent.py -v

# Manual sanity check
./scripts/onboard-sandbox.sh
nemoclaw list                                                       # expect: genomeclaw shown as (healthy)
nemoclaw genomeclaw exec --no-tty --timeout 60 -- bash -c \
  'openclaw agent --local --json --agent genomeclaw \
     --message "Smoke test. Call genomeclaw_status, report the run id."' \
  | tail -30                                                        # expect: status=ok, 1+ tool call

# Confirm no secret in any log
grep -r "sk-proj-" docs/reports/ 2>&1 | head -5                     # expect: empty

# Confirm INVARIANTS.md promotion
grep -A 2 "INV-P003" docs/reference/INVARIANTS.md | head -10        # expect: present
```

---

## Completion Criteria

- [ ] All AC5 test cases pass (`test_invP003_*`).
- [ ] Live-onboard test passes on the project owner's host (manual gate).
- [ ] `nemoclaw list` after a fresh onboard run shows `genomeclaw` with `(healthy)` status.
- [ ] One-shot agent call returns `status=ok` with ≥1 tool call against the active derived run.
- [ ] No regression in any existing onboarding tests.
- [ ] `docs/reference/INVARIANTS.md` updated with `INV-P003` (Version + Last Updated bumped).
- [ ] `README.md` "Sandbox setup" section reflects the new flow.
- [ ] `.claude/agents/privacy-safety-reviewer.md` lists `INV-P003`.
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures or repo.
- [ ] `work-notes.md` updated with RED output, decisions, and final state.
- [ ] Phase status updated to "Complete" in `development-plan.md`.

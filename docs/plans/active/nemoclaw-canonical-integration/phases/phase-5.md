# Phase 5: Verification Gate

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

End-to-end verification that the three NemoClaw-managed surfaces — the dashboard browser UI, `nemoclaw connect → openclaw tui`, and `scripts/ask.sh` — all work after Phases 1–4. Re-run the full existing test suite to confirm no regression in the `agent-synthesis-over-rich-tool-data` replay suite, the `INV-A005 v1.23` / `INV-A006` / `INV-V001` invariant tests, or the DooD discipline tests. This is the gate that unlocks Phase 6 documentation cleanup.

## Scope Boundaries

- **In scope**: cross-surface integration check (dashboard + TUI + ask.sh); full existing test suite re-run; confirmation that `scripts/ask.sh`'s smoke (e.g. the muscle question from prior session) returns a sensible reply.
- **Out of scope**: documentation cleanup (Phase 6); invariant promotion (Phase 6); upstream bug fixes.

## Invariants Enforced in This Phase

All previously-enforced invariants are re-verified here as part of the gate:

- **INV-P001** Privacy Default — no new egress.
- **INV-P003** Secrets Pass via stdin or env, Never via argv — discovery test re-run.
- **INV-A005 v1.23** Reply Synthesis Over Tool Data — replay suite re-run.
- **INV-A006** No Phrase Enumeration in Output Gates — discovery test re-run.
- **INV-V001** Verification Methodology — this phase's connectivity tests must be HTTP probes / structured CLI, not log-grep.
- **INV-D006** + **INV-D007** DooD Discipline — host-service integration tests re-run; spec Q4 audit (do any integration tests reference `/opt/genomeclaw/`?) resolved here.

---

## TDD Steps

### Step 5.1 — RED: Write Failing Tests

**Test cases**:

1. `test_dashboard_url_returns_200` — call `nemoclaw genomeclaw dashboard-url` to discover the port; `curl -s -o /dev/null -w '%{http_code}'` the URL; assert `200`.
2. `test_tui_shows_genomeclaw_tool_catalog` — boot a non-interactive `openclaw tui --list-tools` (or the closest equivalent in 2026.5.18); assert `genomeclaw_status`, `genomeclaw_gene` (etc.) are present in the tool catalog. This is a structural inspection of the tool registry, not a transcript-grep.
3. `test_ask_sh_replies_with_synthesis_to_muscle_question` — run `./scripts/ask.sh --capture "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."`; assert the captured `.trace.json` parses and contains a non-empty `meta.finalAssistantVisibleText`; pipe the trace + reply to the LLM-judge (the same harness from `agent-synthesis-over-rich-tool-data`) and assert `faithful=true` AND `understandable=true`. (LLM-judge run is gated by `GENOMECLAW_REPLAY_LLM=1`; if unset, the test skips structurally — same default-skip discipline as the existing replay tests.)

3a. `test_dashboard_muscle_question_smoke` — **manual gate** (recorded in work-notes, not in pytest): open the dashboard URL, paste the muscle question into the chat UI, capture the rendered reply, paste a screenshot + reply text into `work-notes.md` Phase 5 § Test Results. Pass criteria same as Test 3 (LLM-judge `faithful=true` AND `understandable=true`).

3b. `test_tui_muscle_question_smoke` — **manual gate**: `nemoclaw genomeclaw connect`, then inside the sandbox shell `openclaw tui`, paste the muscle question, capture reply, paste into work-notes. Same pass criteria as Test 3.
4. `test_no_integration_tests_reference_opt_genomeclaw` — discovery test: walk `packages/toolkit/tests/`; assert no test source contains the string `/opt/genomeclaw`. Resolves spec Q4.
5. `test_full_replay_suite_passes_after_migration` — re-run `packages/toolkit/tests/agent_replay/` with `GENOMECLAW_REPLAY_LLM=1` set; assert all pass.

**Sketch**:

```python
def test_dashboard_url_returns_200():
    url = subprocess.check_output(["nemoclaw", "genomeclaw", "dashboard-url"]).decode().strip()
    resp = httpx.get(url, timeout=10)
    assert resp.status_code == 200, f"dashboard returned {resp.status_code}: {resp.text[:200]}"

def test_tui_shows_genomeclaw_tool_catalog(onboarded_sandbox):
    out = docker_exec(onboarded_sandbox, ["openclaw", "tui", "--list-tools", "--json"])
    parsed = json.loads(out)
    tool_ids = {t["id"] for t in parsed.get("tools", [])}
    assert "genomeclaw_status" in tool_ids
    assert "genomeclaw_gene" in tool_ids

def test_no_integration_tests_reference_opt_genomeclaw():
    leaked = []
    for path in Path("packages/toolkit/tests/").rglob("*.py"):
        if "/opt/genomeclaw" in path.read_text():
            leaked.append(str(path))
    assert not leaked, f"INV-D011 follow-up: tests still reference /opt/genomeclaw: {leaked}"
```

Run; confirm RED for the right reasons. Paste output into work-notes.

### Step 5.2 — GREEN: Minimal Implementation

The "implementation" for this phase is mostly verifying-the-state-of-the-world rather than writing new code:

1. If `test_no_integration_tests_reference_opt_genomeclaw` is RED, update those tests to use the canonical path (minor refactor; spec Q4 cleanup).
2. Run the full test suite end-to-end:
   ```bash
   uv --project packages/toolkit run pytest packages/toolkit/tests/ -v
   GENOMECLAW_REPLAY_LLM=1 OPENAI_API_KEY="$OPENAI_API_KEY" \
     uv --project packages/toolkit run pytest packages/toolkit/tests/agent_replay/ -v
   ```
3. Manual: open browser to dashboard URL; verify chat UI loads and a message round-trips.
4. Manual: `nemoclaw genomeclaw connect → openclaw tui`; send the muscle question; observe a synthesized reply (not a JSON dump and not a confabulated failure).

**Files affected**:
- `packages/toolkit/tests/integration/test_phase5_canonical_surfaces.py`: CREATE
- Any test files that referenced `/opt/genomeclaw/`: MODIFY (small string substitution)

### Step 5.3 — REFACTOR

- Consolidate any near-duplicate fixture code under `tests/conftest.py` if the new tests duplicated boot/teardown logic.

---

## Implementation Details

### Edge Cases to Handle

- **Dashboard URL port drift**: if NemoClaw still picks 18790 as a fallback under certain conditions, the test must accept whatever port `nemoclaw dashboard-url` returns (don't hardcode 18789 in the test).
- **TUI `--list-tools` may not exist** in 2026.5.18: if so, query the gateway's tool catalog via HTTP (`openclaw agent --local --list-tools` style) and inspect that. The point is structural verification, not a specific CLI flag.
- **LLM-judge flakiness**: the judge is deterministic per `_judge.py` defaults; if a transient API issue produces a false negative, document in work-notes but don't loosen the assertion.

### Error Handling

- Any phase-5 failure pauses Phase 6 documentation work — don't ship docs that claim a working dashboard if it doesn't load.

### Privacy / Egress Notes

- The LLM-judge step makes a network call to OpenAI's API. That's same as the existing replay tests, gated by `GENOMECLAW_REPLAY_LLM=1`. No new egress beyond what's already documented.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/integration/test_phase5_canonical_surfaces.py` | CREATE | Tests 1, 2, 3 (dashboard + TUI + ask.sh smoke) |
| `packages/toolkit/tests/invariants/test_invD011_no_opt_genomeclaw_references.py` | CREATE | Test 4 (provisional — promotes in Phase 6) |
| Any tests under `packages/toolkit/tests/` referencing `/opt/genomeclaw/` | MODIFY | Replace with `/sandbox/.openclaw-data/extensions/genomeclaw/` |

---

## Verification

```bash
# Full integration + invariant suite
uv --project packages/toolkit run pytest packages/toolkit/tests/ -v

# Replay suite (requires LLM-judge)
GENOMECLAW_REPLAY_LLM=1 \
  uv --project packages/toolkit run pytest packages/toolkit/tests/agent_replay/ -v

# Manual surface checks — paste the same muscle question into each
open "$(nemoclaw genomeclaw dashboard-url)"     # dashboard chat UI
nemoclaw genomeclaw connect                      # then run `openclaw tui` inside
GENOMECLAW_REPLAY_LLM=1 ./scripts/ask.sh --capture \
  "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."

# Capture all three replies into work-notes.md Phase 5 § Test Results,
# tagged: [dashboard], [tui], [ask.sh]. Run each through the LLM-judge
# (manually for dashboard/tui, scripted for ask.sh).
```

---

## Completion Criteria

- [ ] Dashboard loads in a browser and chat UI works
- [ ] `nemoclaw connect → openclaw tui` shows the `genomeclaw_*` tools
- [ ] `scripts/ask.sh` returns a synthesized reply for the muscle question
- [ ] LLM-judge over the muscle-question reply: `faithful=true`, `understandable=true`
- [ ] Full pytest suite green (no regressions)
- [ ] No test file references `/opt/genomeclaw/` (spec Q4 resolved)
- [ ] `work-notes.md` Phase 5 § Test Results updated
- [ ] Phase status updated in `development-plan.md`

# Phase 6: AC8 Re-Run Gate — Semantic Verification (Not Literal)

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Rebuild the sandbox with all Phase 1–5 changes baked in. Re-run the verbatim muscle question. Confirm the agent's reply is **plain-language synthesis**, NOT JSON-field transcription. Auto-verify via the Phase 5 LLM-judge harness. Document side-by-side against the v1.22 trace.

## Scope Boundaries

- **In scope**:
  - Sandbox rebuild via `./scripts/sandbox-up.sh --rebuild`.
  - One agent turn with the verbatim muscle question.
  - Trace + trajectory capture (both files).
  - LLM-judge auto-verification of the new trace.
  - Side-by-side comparison vs. the v1.22 trace.
  - Plan close-out (move to `completed/` on pass).
- **Out of scope**:
  - Iterating on the prompt if the gate fails (loop back to Phase 4).
  - Running additional demo-battery questions (separate scope).

## Invariants Verified By This Gate

- **INV-A005** v1.23 (semantic faithfulness via LLM-judge).
- **INV-A006** (plugin envelope shape — still correct).
- **INV-V001** (no phrase enumeration — semantic verification is the sanctioned alternative).
- **INV-A002** Step 3 (capability-claim bullet — unchanged; passes if the agent doesn't cite stale memory notes when live data contradicts).

---

## Steps

### Step 6.1 — Sandbox Rebuild

```bash
./scripts/sandbox-up.sh --rebuild
```

This runs the onboard script + bakes the new prompt + new plugin envelopes into the image.

Expected: clean rebuild, smoke test passes (one tool call, no failures).

### Step 6.2 — Send the Verbatim Muscle Question

```bash
set -a; source ./.env; set +a; export OPENAI_API_KEY="$OPEN_AI_API_KEY"
CID=$(docker ps --filter 'name=openshell-genomeclaw-' --format '{{.Names}}' | head -1)
mkdir -p docs/reports/demo-2026-05-28-logs  # or use the date when running
TRACE=docs/reports/demo-2026-05-28-logs/post-v123-muscle-question.trace.json

docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY="$OPENAI_API_KEY" --user sandbox "$CID" \
  bash -c 'openclaw agent --local --json --agent genomeclaw --message "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."' \
  > "$TRACE" 2>&1
```

The host service is intentionally NOT started — Phase 6 exercises the network-failure path, the same scenario that drove the parent plan's bug discovery.

### Step 6.3 — Capture the Trajectory File

```bash
# Find the latest trajectory inside the sandbox + copy it out.
LATEST=$(docker exec --user sandbox "$CID" bash -c 'ls -t /sandbox/.openclaw/agents/genomeclaw/sessions/*.trajectory.jsonl | head -1')
docker cp "$CID":"$LATEST" docs/reports/demo-2026-05-28-logs/post-v123-muscle-question.trajectory.jsonl
```

### Step 6.4 — Run the LLM-Judge

```bash
cd packages/toolkit
GENOMECLAW_REPLAY_LLM=gpt-5.5 OPENAI_API_KEY="$OPEN_AI_API_KEY" \
  uv run pytest tests/agent_replay/test_invA005_v123_reply_is_faithful_to_trajectory.py -xvs
```

**Pass criteria**: judge returns `faithful=True` AND `understandable=True` for the new trace.

If the judge flags violations:
- Read the violations.
- If they're real (agent still transcribing, missing context, confabulating): loop back to Phase 4 — refine the prompt's worked examples.
- If they're judge over-reach (judge being too strict): iterate on the judge's system prompt (Phase 5).

### Step 6.5 — Side-by-Side Comparison

Diff the v1.22 reply vs. the v1.23 reply. Document in `work-notes.md`:

| Aspect | v1.22 reply | v1.23 reply |
|--------|-------------|-------------|
| Reply style | Robotic JSON transcription | Plain-language synthesis |
| Uses `error_type:` token literally? | Yes (×3) | No |
| Names failure mode | Transcribed enum value | Translated to "couldn't reach host service" / "received placeholder argument" |
| User-actionable next steps? | None or minimal | Concrete suggestions |
| Genome-baseline guidance under failure? | Generic + present | Generic + present (similar quality) |
| LLM-judge verdict | Would flag (transcription) | Passes (synthesis) |

Side-by-side proof is what the user needs to see — the v1.22 result was the empirical motivator for this plan; v1.23 must demonstrably differ in reply style.

### Step 6.6 — Move Plan to Completed

Once AC8 passes:

- Update progress table: all phases Complete.
- Append final summary to `work-notes.md`.
- `git mv docs/plans/active/agent-synthesis-over-rich-tool-data docs/plans/completed/`.
- Fix any cross-reference paths post-move (use the bulk-fix script pattern from prior plans).

---

## Pass Criteria (Repeated for Clarity)

1. **Agent's reply is plain language**, not JSON transcription. Manual read-through confirms; LLM-judge verdict confirms.
2. **No `error_type:`-token-quoted phrases** dominating the reply. The agent may MENTION `error_type` if explaining the system's internal classifier to a technically-curious user, but the reply shouldn't be a string of envelope-field dumps.
3. **LLM-judge passes** with `faithful=True` and `understandable=True`.
4. **Trajectory still carries the structured envelopes** — the plugin-side `INV-A006` shape is unchanged.
5. **The structured-envelope test (INV-A006)** still passes — no regression on the plugin's contract.

---

## Failure Modes

If the gate fails, document which:

- **Agent still transcribes**: prompt rewrite (Phase 4) needs another iteration. Worked examples may be too thin; add a stronger anti-pattern with the actual v1.22 captured transcription as the "do not do this" example.
- **Agent omits causes**: the reply skips over what tools actually returned (under-synthesis instead of over-transcription). Adjust prompt to emphasize giving the user a real explanation of what happened.
- **Agent confabulates again**: invents a failure that didn't happen. This is the original bug; needs a structural fix (re-examine the trajectory; check the agent followed multi-turn investigation rule).
- **Judge over-reach**: judge flags reasonable replies as problematic. Adjust judge prompt; possibly distinguish "fully faithful" from "minor wording-quality issues."
- **Sandbox state issues**: if the sandbox is in a broken state (gateway down, plugin not loaded), the rebuild step is the fix.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/reports/demo-<date>-logs/post-v123-muscle-question.trace.json` | CREATE | Captured agent turn output. |
| `docs/reports/demo-<date>-logs/post-v123-muscle-question.trajectory.jsonl` | CREATE | Sibling per-tool-call trajectory. |
| [work-notes.md](../work-notes.md) | MODIFY | Append AC8 gate result + side-by-side comparison + LLM-judge verdict. |

---

## Verification

```bash
# Manual check — read the reply
python3 -c "
import json, sys
text = open('docs/reports/demo-2026-05-28-logs/post-v123-muscle-question.trace.json').read()
# Skip prefix log lines
start = text.find('\n{')
trace = json.loads(text[start+1:] if start >= 0 else text)
print(trace['result']['meta']['finalAssistantVisibleText'])
"

# Auto check — LLM judge
cd packages/toolkit
GENOMECLAW_REPLAY_LLM=gpt-5.5 OPENAI_API_KEY="$OPEN_AI_API_KEY" \
  uv run pytest tests/agent_replay/test_invA005_v123_reply_is_faithful_to_trajectory.py -xvs

# Plugin-side regression check
cd ../nemoclaw-plugin
npm test
```

---

## Completion Criteria

- [ ] Sandbox rebuilt with Phases 1–5 baked.
- [ ] Verbatim muscle question sent + reply captured.
- [ ] Trajectory file captured alongside the trace.
- [ ] Reply read manually + confirmed plain-language (not JSON transcription).
- [ ] LLM-judge verdict: `faithful=True` AND `understandable=True`.
- [ ] Side-by-side comparison vs. v1.22 documented in `work-notes.md`.
- [ ] Plan moved to `docs/plans/completed/`.
- [ ] Phase 6 row in `development-plan.md` progress table set to **Complete**.
- [ ] If `INV-D010` was promoted in Phase 3: verify it's still consistent post-rebuild.

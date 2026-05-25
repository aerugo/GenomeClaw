# Phase 2: Fix + RCA

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land the minimal-diff fix that matches Phase 1's pinned hypothesis. Write the RCA brief.

## Scope Boundaries

- **In scope**: the code change for the diagnosed branch (server / plugin / system-prompt); updates to existing tests if their behaviour expectations need to shift; RCA brief.
- **Out of scope**: structural invariant enforcement (Phase 3); live verification (Phase 3); expanding the curated gene panel.

## Invariants Enforced in This Phase

- **INV-A001** Agent Memory Provenance — the fix closes the agent-claim-vs-tool-output divergence for the diagnosed cause.
- **INV-E001** Evidence Traceability — same theme.

---

## TDD Steps

### Step 2.1 — Confirm Phase 1's RED state

Re-run Phase 1's probe test if needed to confirm the bug shape hasn't changed. If hypothesis #6 (confabulation) was confirmed, this step is "confirm the system prompt still lacks the no-serialization-bug rule".

### Step 2.2 — Land the fix per the diagnosed branch

#### Branch S — Server-side fix

If the route handler returns non-2xx for some genes OR shape-inconsistent bodies:

```python
# packages/toolkit/src/genomeclaw_toolkit/service/app.py — pseudo-diff

@app.get("/v1/gene/{symbol}")
def get_gene(symbol: str) -> dict:
    # Always return 200 with a uniform shape; the in-panel vs not-in-panel
    # distinction goes into a structured field the agent can read.
    if not _is_hgnc_valid(symbol):
        return {"status": "invalid_symbol", "symbol": symbol}
    try:
        data = store.read_gene_summary(symbol)
    except KeyError:
        return {
            "status": "not_in_panel",
            "symbol": symbol,
            "reason": (
                f"{symbol} is not in the curated per-gene panel for the active run. "
                "This means the per-gene coverage + variant aggregation has not been "
                "computed for this gene — it does not mean the gene is absent from "
                "the user's genome."
            ),
        }
    return {"status": "ok", "symbol": symbol, "data": data}
```

Then update the plugin's response handling to read the `status` field and surface it to the agent as a clean field rather than a generic error.

#### Branch P — Plugin-side fix

If `rejectIfPlaceholder` false-positives or `safeCall` obscures the response:

```typescript
// packages/nemoclaw-plugin/src/index.ts — pseudo-diff

// If rejectIfPlaceholder is the culprit:
const rejectIfPlaceholder = (args, field, opts) => {
  const value = args[field];
  // OLD (too broad):
  if (/^[A-Z]{2,4}$/.test(value)) { /* reject as placeholder */ }
  // NEW (tighter): only reject obvious template strings
  if (/^<[a-z_]+>$|^TODO$|^EXAMPLE$/i.test(value)) { /* reject */ }
};

// If safeCall obscures the response:
const safeCall = async (host, path) => {
  try {
    const r = await fetch(`${host}${path}`);
    if (!r.ok) {
      return jsonResult({
        status: "tool_failure",
        http_status: r.status,
        message: await r.text(),  // not "argument-serialization bug"
      });
    }
    return jsonResult(await r.json());
  } catch (exc) {
    return jsonResult({ status: "tool_failure", message: String(exc) });
  }
};
```

#### Branch A — System-prompt fix

If Phase 1 confirmed hypothesis #6 (the agent paraphrases "no data" as "serialization bug" without a real failure):

```markdown
<!-- Add to packages/nemoclaw-plugin/sandbox/agent-system-prompt.md
     in the genomeclaw_gene section or the tool-error-handling section -->

### Paraphrasing `genomeclaw_gene` responses

The `genomeclaw_gene` tool returns one of three response shapes:

1. **`{status: "ok", symbol, data}`** — real per-gene summary. Paraphrase
   data into the user-visible reply naturally.
2. **`{status: "not_in_panel", symbol, reason}`** — the gene exists as
   a real HGNC symbol but the curated panel doesn't include it for this
   run. Paraphrase as "<SYMBOL> isn't in the curated per-gene panel for
   your current run", NOT as "argument-serialization bug" and NOT as
   "you don't have this gene".
3. **`{status: "tool_failure", message}`** — actual tool error. Paraphrase
   as "the `genomeclaw_gene` lookup failed with <message>". Only this
   shape gets the word "failure" or "bug" in the reply.

The phrase "argument-serialization bug" must NEVER appear in your reply
prose unless you have actually invoked `genomeclaw_gene` and received a
`tool_failure` response shape with that specific error message. The
phrase was introduced in error in earlier sessions; don't reproduce it.
```

Plus extend the existing `tests/invariants/test_agent_system_prompt_contract.py` to assert this section exists.

### Step 2.3 — REFACTOR

With the fix in:

- Re-run Phase 1's probe test — what was "soft assertion" becomes "PASS asserting the post-fix shape".
- Update Phase 1's test to assert the new shape rather than just capturing it.

### Step 2.4 — Write the RCA brief

`docs/reports/genomeclaw-gene-tool-bug-rca.md` — sections:

1. **Symptom** — the agent reports "argument-serialization bug" for some genes; trace's failure count is 0.
2. **Reproduction** — pointer to Phase 1's probe test.
3. **Root cause** — single sentence + supporting evidence.
4. **Why the existing tests didn't catch it** — important context.
5. **Fix** — pointer to the commit + 2-paragraph summary.
6. **Hypotheses considered + ruled out** — the other 5 from spec.md, one sentence each.
7. **Open questions** — anything still unresolved.

≤ 200 lines.

---

## Implementation Details

### Edge Cases to Handle

- **Mixed branches**: it's possible Phase 1 confirms TWO root causes (e.g., the server returns 404 for some genes AND the agent paraphrases differently for true 404s vs no-data 200s). If so, ship both fixes in the same Phase 2.
- **Backward compatibility**: if any existing test asserts the OLD response shape (e.g., 404 for not-in-panel genes), update those tests to assert the new uniform shape.

### Error Handling

- The `tool_failure` shape MUST carry a useful `message` — not just the HTTP status. The agent's downstream paraphrase quality depends on it.

### Privacy / Egress Notes

- The `not_in_panel` `reason` field doesn't leak variant data; safe.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY (if Branch S) | Uniform response shape for `/v1/gene/{symbol}`. |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY (maybe) | Read-path adjustment to return None instead of raising. |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY (if Branch P) | Tighter `rejectIfPlaceholder` or more-informative `safeCall` wrapping. |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY (if Branch A) | Explicit no-serialization-bug paraphrasing rule. |
| `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` | MODIFY (if Branch A) | Assert the new section exists. |
| `docs/reports/genomeclaw-gene-tool-bug-rca.md` | CREATE | RCA brief. |
| `docs/plans/active/investigate-genomeclaw-gene-tool-bug/work-notes.md` | MODIFY | Session log + fix decision. |

---

## Verification

```bash
cd packages/toolkit
.venv/bin/pytest tests/integration/test_service_gene_endpoint_per_gene.py -v
# Expect: GREEN under the post-fix uniform shape.

.venv/bin/pytest tests/integration/test_service_provenance_and_gene.py -v
# Expect: still passes.

# Plugin tests (Node)
cd ../nemoclaw-plugin
npm run typecheck && npm run test
# Expect: pass.

# Agent-system-prompt contract (if Branch A)
cd ../toolkit
.venv/bin/pytest tests/invariants/test_agent_system_prompt_contract.py -v
# Expect: passes, including the new no-serialization-bug rule check.
```

---

## Completion Criteria

- [ ] Phase 1's probe test passes asserting the post-fix uniform shape.
- [ ] No existing tests regress.
- [ ] RCA brief landed, ≤ 200 lines.
- [ ] Fix diff is ≤ 100 lines.
- [ ] `work-notes.md` updated.
- [ ] Phase status updated to "Complete" in `development-plan.md`.

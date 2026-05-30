# Phase 3: Structural Trace-Walker + Promote INV-A006

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Delete the parent plan's phrase-list enforcement (`_FORBIDDEN_PHRASES`, `_STRUCTURAL_FAILURE_SIGNALS`, `_GENOMECLAW_HTTP_ERROR_PATTERN`). Replace the trace-walker with a structural mechanism: walk per-tool-call records in the trace and assert the agent's reply quotes the `error_type` value for any failure narrative. Promote `INV-A006` ("plugin returns structured envelopes") to a formal invariant with a discovery test.

## Scope Boundaries

- **In scope**:
  - Full rewrite of [test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py).
  - New `test_invA006_plugin_returns_structured_envelopes.py` discovery test.
  - `INVARIANTS.md` v1.22 update: `INV-A005` rule rewrite + new `INV-A006` entry + Invariant Index update.
- **Out of scope**:
  - LLM-judge harness (Phase 4; scope-reducible).
  - Re-running the AC8 manual gate (parent plan's responsibility; rerun is documented under Phase 4 if Phase 4 ships, or under this plan's wrap-up if it doesn't).

## Invariants Enforced in This Phase

- **INV-A005** v1.22 (new structural enforcement; rule text lands here).
- **NEW INV-A006** Plugin Tool-Result Returns Structured Envelopes — promoted with the discovery test.

## Open Question Q1 — Per-Tool-Call Records in Trace

The structural walker depends on the trace exposing per-tool-call records (tool name, args, structured result envelope). Current evidence from the 2026-05-28 AC8 trace shows `openclaw agent --json` only emits the final reply + `meta.toolSummary` aggregate — **no per-call records**.

Three resolution paths, in order of preference:

1. **Upstream openclaw**: file an issue / PR to expose `meta.toolCalls[]` in `--json` output. Tracks the agent's reasoning trail. Heavy but durable.
2. **WebSocket-interception harness**: capture per-call records by intercepting the openclaw gateway's WebSocket frames during the agent turn — `_live_smoke/`-style. Adds harness complexity.
3. **Fall back to `toolSummary.failures` aggregate**: the walker only enforces "if reply mentions failure, `toolSummary.failures > 0`." Weaker than the design — doesn't catch per-tool homogenization — but better than the substring whack-a-mole we're replacing.

**Default for Phase 3**: path 3 (fallback). Phase 4's LLM-judge fills the per-tool gap semantically. Document path 1 as a follow-up to file with upstream openclaw if/when bandwidth allows. **Resolve Q1 before Phase 3 RED.**

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

**Test cases**:

1. **`test_invA005_no_serialization_bug_confabulation.py` rewrite — the new shape**:
   - `test_invA005_failure_narrative_requires_toolSummary_failures` — if reply text contains failure-narrative cues (case-insensitive: "failed", "could not", "unable to retrieve" + structured field literals like `error_type:`), the trace's `toolSummary.failures > 0`. **Coarser** than the old phrase-list — no enumeration. Trigger: `error_type:` appears in reply.
   - `test_invA005_failure_narrative_quotes_error_type` — if reply text contains `"error_type:"`, the value following it must match one of the known enum values (`placeholder_rejected`, `host_failure`, `network_error`, `http_error`, or a documented new enum). **This is the structural check** — it's parametric over the enum set, not enumerated phrases.
   - Both tests run over `docs/reports/**/*.trace.json` like the old walker.

2. **`test_invA006_plugin_returns_structured_envelopes.py`** — new discovery test:
   - Walks the plugin's exported tool list (parses [index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts) or `dist/index.js` for failure-path return types).
   - Asserts every failure-path return statement either (a) returns a `ToolFailureEnvelope` discriminated-union value, or (b) is wrapped by one of the three canonical helpers (`rejectIfPlaceholder`, `wrapHostResponse`, `safeCall`/`safePost`).
   - Discovery shape: similar to [test_invT001_tool_conventions_exist.py](../../../../../packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py) — walks the source + asserts a structural property.

3. **Deletion-guard test** (lightweight): `test_invA005_no_phrase_enumeration_tuples` — explicit assertion that `_FORBIDDEN_PHRASES`, `_STRUCTURAL_FAILURE_SIGNALS`, `_CATALOGUE_ROWS`, `_GENOMECLAW_HTTP_ERROR_PATTERN` do **not** appear in any file under `packages/toolkit/tests/invariants/`. Grep + assert empty. This is the structural enforcement of "no more phrase enumeration here" (sister plan covers the project-wide case).

Run all three. Expect:
- (1) fails because the old `_FORBIDDEN_PHRASES` still lives in the file.
- (2) fails because `INV-A006` discovery test file doesn't exist yet.
- (3) fails because the parent plan's `_FORBIDDEN_PHRASES` etc. still exist.

### Step 3.2 — GREEN: Delete + Replace

1. **Delete** `_FORBIDDEN_PHRASES`, `_STRUCTURAL_FAILURE_SIGNALS`, `_GENOMECLAW_HTTP_ERROR_PATTERN` from `test_invA005_no_serialization_bug_confabulation.py`. Replace the body with the two new structural tests (parametrized over trace files).
2. **Create** `test_invA006_plugin_returns_structured_envelopes.py` per the spec sketched above.
3. **Update `INVARIANTS.md`**:
   - `INV-A005` rule rewrite to v1.22 (replace "specific banned phrases require licensing signals" with the structural rule). Bump section header.
   - New `INV-A006` entry following the project's invariant-section template (Rule / Why / Requirements / Where it applies / How to verify / Related plans).
   - Invariant Index table appended with `INV-A006`.
   - Top-of-file version bump (v1.21.1 → v1.22) + dated changelog entry.

### Step 3.3 — REFACTOR

- Re-run the three new tests + full invariants suite → all green.
- Confirm `grep -rn '_FORBIDDEN_PHRASES\|_CATALOGUE_ROWS\|_STRUCTURAL_FAILURE_SIGNALS' packages/toolkit/tests/` returns empty.
- Run the structural walker against the 2026-05-28 AC8 trace ([docs/reports/demo-2026-05-28-logs/manual-ac8-muscle-question.trace.json](../../../../../docs/reports/demo-2026-05-28-logs/manual-ac8-muscle-question.trace.json)). Expectation: the walker may now SKIP if the agent's reply doesn't contain `error_type:` (the agent hasn't been re-run against the new prompt yet — that's the AC8 re-run gate, deferred).
- Tighten the new test names + docstrings to cite `INV-A005` v1.22 + `INV-A006`.

---

## Implementation Details

### Edge Cases

- **Traces dated before the §INV-A005 v1.22 binding date** (2026-05-29 or whenever Phase 2 lands) should skip the new structural tests — same date-gating pattern as the parent plan's walker.
- **Reply that mentions failure without quoting `error_type:`** — under the new prompt rule, the agent SHOULD quote it. If a real trace doesn't, that's a regression worth flagging — test fails. (Tradeoff vs. coarser `toolSummary.failures > 0` fallback; see Q1.)
- **Future `error_type` enum values** — Phase 3's enum-set assertion must be parametric over the values declared in `index.ts`. Either (a) parse them out of `index.ts` at test runtime, or (b) define a Python-side mirror with a discovery test ensuring it stays in sync (similar to `INV-A004`'s cross-language enum-diff test).

### `INV-A006` Rule Text (Draft)

```markdown
## INV-A006: Plugin Tool-Result Returns Structured Envelopes

**Rule** *(v1.22, per inv-a005-structural-faithfulness Phase 3)*: any failure-path return from a tool wrapper in the nemoclaw plugin MUST be a structured envelope with an explicit `error_type` enum field. Prose paraphrases of error states MAY appear as an `advisory` field but MUST NOT be the only signal of error class.

**Why this exists** — Without `INV-A006`, the agent's only handle on tool failures is paraphrased prose. Substring-matching prose forces downstream test enforcement to enumerate phrases, which doesn't generalize against the agent's paraphrase-space (AC8 manual gate, 2026-05-28, captured "object-shape serialization error" — a paraphrase the catalogue didn't list).

**Requirements**:
- Every failure-path return in [packages/nemoclaw-plugin/src/index.ts](...) MUST be a `ToolFailureEnvelope` discriminated-union value (or be wrapped by a helper that produces one: `rejectIfPlaceholder`, `wrapHostResponse`, `safeCall`/`safePost`).
- The discriminator field is named `error_type`. The enum is a closed set of named values; future additions extend the set + update tests in lockstep.
- The `advisory` field is human-readable text for operator-facing logs; it MUST NOT be load-bearing for any test or downstream consumer.

**Where it applies**:
- [packages/nemoclaw-plugin/src/index.ts](../../packages/nemoclaw-plugin/src/index.ts) — primary surface.
- Future tool wrappers in any plugin under `packages/*-plugin/src/`.

**How to verify**:
- [packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py](../../packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py) — discovery test walks the plugin's failure-path returns.

**Related plans**: [inv-a005-structural-faithfulness](../plans/completed/inv-a005-structural-faithfulness/) — promotes this invariant alongside the `INV-A005` v1.22 rule rewrite.
```

### Privacy / Egress Notes

- None. Test + invariants-doc edits only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) | REWRITE | Delete phrase tuples; replace with structural walker (two new tests). |
| `packages/toolkit/tests/invariants/test_invA006_plugin_returns_structured_envelopes.py` | CREATE | Discovery test for the new `INV-A006`. |
| [docs/reference/INVARIANTS.md](../../../../reference/INVARIANTS.md) | MODIFY | `INV-A005` v1.22 rule rewrite + new `INV-A006` entry + Invariant Index update + version bump. |
| [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../../agent-replay-harness-for-prompt-regression.md) | MOVE / SUPERSEDE | Move to `completed/` with a header noting it's superseded by this plan. |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/invariants/test_invA005_no_serialization_bug_confabulation.py -xvs
uv run pytest tests/invariants/test_invA006_plugin_returns_structured_envelopes.py -xvs
uv run pytest tests/invariants/ -x
grep -rn '_FORBIDDEN_PHRASES\|_CATALOGUE_ROWS\|_STRUCTURAL_FAILURE_SIGNALS' tests/invariants/ || echo "clean"
```

---

## Completion Criteria

- [ ] Three new tests pass (`test_invA005_*` rewrites + `test_invA006_*` discovery + deletion guard).
- [ ] No `_FORBIDDEN_PHRASES` / `_CATALOGUE_ROWS` / `_STRUCTURAL_FAILURE_SIGNALS` / `_GENOMECLAW_HTTP_ERROR_PATTERN` token anywhere under `packages/toolkit/tests/`.
- [ ] `INVARIANTS.md` v1.22: `INV-A005` rule rewrite + new `INV-A006` entry + index.
- [ ] `agent-replay-harness-for-prompt-regression.md` moved to `completed/` with a supersession note.
- [ ] Static checks pass (`ruff check tests/invariants/`).
- [ ] `work-notes.md` updated.
- [ ] Phase 3 row in `development-plan.md` progress table set to **Complete**.

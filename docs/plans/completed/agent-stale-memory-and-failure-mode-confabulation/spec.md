# Feature: Agent Stale-Memory Bias + Failure-Mode Confabulation Guardrails

**Status**: Draft
**Created**: 2026-05-27
**Owner**: aerugo (filed during 2026-05-27 muscle-question regression sweep)
**Related Plans**:
- [investigate-prs-compute-config-missing](../../completed/investigate-prs-compute-config-missing.md) (Plan 1; shipped 2026-05-27)
- [investigate-toolsummary-failure-counter-blindness](../../completed/investigate-toolsummary-failure-counter-blindness.md) (Plan 2; shipped 2026-05-27)
- [investigate-genomeclaw-gene-tool-bug](../../completed/investigate-genomeclaw-gene-tool-bug/) (origin of `INV-A005`)

---

## Goal

Extend the agent system prompt + `INV-A005` enforcement so the agent stops (a) citing stale memory notes about *tool capability gaps* after the capability has been repaired in-turn, and (b) homogenizing distinct failure modes into whichever failure phrase is most rehearsed.

## Background

Both bugs surfaced during the 2026-05-27 muscle-question regression sweep, *after* Plan 1 (sidecar repair) and Plan 2 (`wrapHostResponse` host-failure surfacing) landed and the `INV-A005` prompt strengthening of 2026-05-26 was live.

**Bug 1 — stale-memory bias for repaired capabilities.** Run 4 (rebuild-2 sandbox, 30 minutes after Plan 1 landed): the agent answered the muscle question in 108s with only 8 tool calls — *no* [`genomeclaw_gene`](../../../../packages/nemoclaw-plugin/src/index.ts) panel, no `_pgs_get`, no `_pgs_compute` retry. The reply was served almost entirely from a memory note written 2026-05-26 that said *"PGS000027 not computable due to prs_compute_config_missing"* and *"live GenomeClaw refresh is currently unavailable."* Both were structurally false *at the time of run 4*: Plan 1 had repaired the sidecar 30 minutes earlier (PGS000018 was computed end-to-end at percentile 14.54), and `genomeclaw_status` in the very same turn returned HTTP 200. The agent had two staleness signals — (a) a memory note about a *capability failure* + (b) a live tool response that contradicted the memory — and ignored both.

**Bug 2 — failure-mode confabulation under network failure.** Run 5 (rebuild-3 sandbox, host service lost because the previous `epic_meitner` container was `--rm` and didn't survive the rebuild): all `genomeclaw_*` calls genuinely returned HTTP connection-refused errors (`Failed to connect to host.openshell.internal port 8645`). But the agent's reply said *"`status`, findings, and PRS list returned fetch failures, and gene/PRS calls hit the argument-shape guard"* — conflating the actual failure (network unreachable) with the §INV-A005-banned phrase "argument-shape guard." The 2026-05-26 strengthening added a worked example for *mixed-outcome* turns (some succeed, one rejected) but did not address the *all-failed-for-the-same-network-reason* case.

These are two faces of the same underlying issue: **the agent's failure narratives drift toward whichever explanation is most accessible from its prior context, not the one supported by this turn's structured trace.**

## Acceptance Criteria

Each criterion maps to one or more tests; the test names are sketched in [development-plan.md](development-plan.md) Phase 1 / Phase 2 / Phase 3.

- [ ] **AC1**: The agent system prompt's Step 3 (Memory validation) carries an explicit *capability-claim* check that overrides the freshness-date rule: any memory note describing a tool failure, missing data path, or "X is currently unavailable" must be re-verified against this turn's tool trace before being cited.
- [ ] **AC2**: The agent system prompt's §INV-A005 section carries a *catalogue* of failure-phrase / structural-signal pairs (not just the single "argument-shape guard" phrase it forbids today). Each phrase the agent might reach for is paired with the literal tool-result text shape it requires.
- [ ] **AC3**: The §INV-A005 catalogue includes the explicit rule: *"if multiple tool calls fail in the same turn, report each one's failure mode separately based on its specific tool-result text. Do NOT homogenize 'all my GenomeClaw calls failed' into a single guess at the cause."*
- [ ] **AC4**: `test_agent_system_prompt_contract.py::test_invA005_*` keeps passing (existing assertions: `inv-a005` marker present, `argument-serialization bug` named as forbidden, `region_class` + `n_variants_in_gene` worked examples present) AND a new assertion: every entry in the catalogue table is present in the prompt.
- [ ] **AC5**: `test_invA005_no_serialization_bug_confabulation.py` is extended with the new forbidden-phrase entries from the catalogue (e.g., "argument-shape guard fired" without a `rejectIfPlaceholder` payload), and trace-walk continues to pass against all `docs/reports/*.trace.json`.
- [~] **AC6**: ~~A new agent-replay test surface under `packages/toolkit/tests/agent_replay/` provides three scenarios with mocked tool-result envelopes~~ **Deferred 2026-05-28** to follow-up plan [agent-replay-harness-for-prompt-regression](../agent-replay-harness-for-prompt-regression.md). The three scenarios (stale-capability supersession, all-network-failure phrasing, mixed-outcome decomposition) remain valuable but not load-bearing for this plan's bug fix — Phase 1's Step 3 bullet + Phase 2's catalogue + trace-walker already close the reported regressions at the prompt-discipline layer.
- [~] **AC7**: ~~Each agent-replay test asserts the reply text does/doesn't contain catalogue phrases.~~ **Deferred** with AC6.
- [ ] **AC8**: Manual real-data verification gate: after Phase 1 + 2 land, the verbatim muscle-question prompt — *"Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."* — is re-run against the rebuilt sandbox. The agent's reply does not cite "GenomeClaw is unavailable" while live tools work, does cite the actual PGS000018 percentile if `_pgs_list` returns it, and uses the correct failure-phrase from the catalogue if any tools fail. Trace + result captured in `work-notes.md`.

## Applicable Invariants

- **INV-A005** Tool-Failure Narratives Match Trace Evidence — this plan **extends** the invariant's enforcement surface. The 2026-05-26 strengthening covered the *mixed-outcome* turn (one rejected, others succeeded); this plan adds (a) the *all-failed-same-reason* turn and (b) the *memory-citation-of-stale-capability-claim* turn. The invariant text itself stays unchanged at v1.21; only the prompt + tests that enforce it grow.
- **INV-A002** Synthesis Reasoning Floor — the §INV-A002 v1.8 amendment *(memory-validation requirement on every `memory:<id>` citation)* requires the agent to validate the cited memory's freshness in-turn. Bug 1 is a direct violation: the agent cited `memory:<id>` capability claims **without** the in-turn validation pass that the freshness check (v1.8 bullet 3) is supposed to compel. Phase 1's Step 3 amendment tightens the freshness bullet so capability claims are special-cased.
- **INV-A001** Agent Memory Provenance — adjacent (memory notes must record provenance + freshness dates), but not directly extended; the stale-memory bug is a *use-site* failure, not a *write-site* failure.
- **INV-P001** Privacy Default — pure prompt edits + a local test harness; **no new egress, no new tool surface**. The replay harness in Phase 3 explicitly uses a *mocked* tool-result envelope and either the existing local LLM endpoint or a smaller remote model that already lives in the configured-egress allowlist. No new sensitive-payload surface is introduced.

## Proposed New Invariants

**None.** Both fixes fit inside the existing `INV-A005` + `INV-A002` envelope. If during Phase 3 the catalogue-fixture pattern (Open Question Q3 below) is adopted, the catalogue's "must stay in sync between prompt and tests" rule may warrant a small dedicated invariant — defer that decision to Phase 3 review.

## Technical Requirements

### Source Data Inputs

- The agent system prompt at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — specifically Step 3 (around line 177) and the §INV-A005 block (lines 156–175).
- The plugin's failure-shape source code at [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) — specifically:
  - `rejectIfPlaceholder` prose (lines 297–333)
  - `wrapHostResponse` prose (lines 220–244)
  - `safeCall` / `safePost` catch-block prose (lines 185–197, 254–266)
- Existing trace artifacts under `docs/reports/*.trace.json` (the trace-walker fixture corpus the `INV-A005` invariant test already iterates).

### Derived Outputs

- Updated `agent-system-prompt.md` (Phase 1 + Phase 2).
- Extended `test_invA005_no_serialization_bug_confabulation.py` forbidden-phrase list (Phase 2).
- Extended `test_agent_system_prompt_contract.py` catalogue-presence assertion (Phase 2).
- New `packages/toolkit/tests/agent_replay/` test directory + conftest + three scenario tests (Phase 3).
- No derived data stores, no schema changes, no provenance columns.

### Schema / Migration Impact

**None.** Prompt + test edits only.

### Pipeline / Workflow Impact

**None.** No ingest, no annotate, no compute. Agent-side cognition discipline only.

### Agent / UX Impact

- Step 3 (Memory validation) grows a fourth bullet ("Capability claims") that special-cases tool-failure memory notes.
- §INV-A005 grows from one forbidden phrase + worked-example pair into a *catalogue table* of phrase ↔ structural-signal pairs, plus the "decompose per-tool" rule.
- Worked-example pair added: an over-trusted memory citation (anti-pattern) vs. the correct in-turn supersession (target pattern).

### External Dependencies

- *(Originally scoped)* The agent-replay harness would need the project's pinned `gpt-5.5` model (matching `_live_smoke/run.py:224`); cheaper substitutes are not used in GenomeClaw. **Resolved 2026-05-28**: automated harness deferred to a follow-up plan ([agent-replay-harness-for-prompt-regression](../agent-replay-harness-for-prompt-regression.md)); Phase 3 reduces to the manual AC8 gate (no new external dependency required).

## Privacy & Safety Considerations

- **Boundary scan**: no new egress, no new tool surface, no new secret-handling. Both prompt edits stay inside the existing NemoClaw plugin, which is already a *named, user-configured* egress destination per `INV-P001`.
- **Default-off remote calls**: n/a — this plan adds none. The replay harness in Phase 3 mocks tool-result envelopes; it does not call real `genomeclaw_*` tools.
- **Redaction surface**: n/a — fixtures use synthetic memory notes + synthetic tool-result envelopes; no real genome data is embedded.
- **Clinical escalation**: indirect. The agent's stale-capability-citation behavior in Bug 1 actively *suppressed* surfacing PGS000018's actual percentile (which has clinical-escalation framing). Fixing the bug restores correct clinical-escalation behavior; it doesn't introduce a new one.

## Out of Scope

- **Host service restart resilience** — the 2026-05-27 run-5 failure happened because `epic_meitner` ran with `--rm` and didn't survive the sandbox rebuild's docker churn, then couldn't restart because colima had lost its `/Volumes/Genome_Work` mount. That's an infrastructure / `bin/genomeclaw host service` lifecycle concern. File separately if needed. The agent should still gracefully describe "host unreachable" when it happens, but it shouldn't be responsible for preventing the infrastructure failure.
- **Promoting `wrapHostResponse` upstream** — Plan 2's local fix handles the host-side structured-failure path in our plugin. If/when OpenClaw exposes a `clientRejections` counter or per-call telemetry event surface, the local workaround can be removed. Tracked separately.
- **Editing `_real_compute_fn` to make pgsc_calc faster** — the 25-minute compute time is orthogonal.
- **Auto-writing superseding memory notes** — Open Question Q2 below; default is block-only (don't cite the stale note). A later plan may add auto-write.
- **Promoting the failure-phrase catalogue to a versioned fixture under `packages/nemoclaw-plugin/sandbox/failure-phrases.md`** — Open Question Q3 below; defer until the catalogue churns enough to warrant central registration.

## Dependencies

- Plan 1 (sidecar repair) and Plan 2 (`wrapHostResponse` host-failure surfacing) — both shipped 2026-05-27. The new catalogue entry for *"host returned status=failed for /v1/..."* requires Plan 2's `wrapHostResponse` text to be in production, which it is.
- The existing `INV-A005` test corpus + prompt-contract test — Phase 2 extends these in place.

## Open Questions

- [x] **Q1**: ~~Can the replay harness use a smaller / cheaper model than `gpt-5.5`?~~ **Resolved 2026-05-28 (user-confirmed)**: GenomeClaw pins `gpt-5.5` across the agent + all test harnesses. Cheaper-model substitutes are NOT used in this project — the prompt-following discipline being verified is reasoning-ceiling-sensitive (INV-A002 synthesis-reasoning-floor). Together with the Phase 3 scope-reduction decision (Option 3), the question is moot: the automated harness is deferred to a follow-up plan, and the manual AC8 gate exercises the real `gpt-5.5` agent against the live sandbox.
- [ ] **Q2**: Should the memory-supersession rule auto-write a superseding memory note (the agent already has the schema), or just block the citation? Auto-write keeps the memory store fresh; block-only keeps the agent's writes scoped to deliberate synthesis. *Default chosen for this plan: block-only.* File a follow-up plan if auto-write becomes desirable.
- [ ] **Q3**: How does the failure-phrase catalogue stay in sync as the plugin's failure shapes evolve? Option A — link it to a fixture under `packages/nemoclaw-plugin/sandbox/failure-phrases.md` that both the prompt and the replay tests read. Option B — keep the catalogue inline in the prompt and rely on the contract test to assert presence. *Default chosen for this plan: Option B (inline) for the first iteration; revisit if the catalogue grows past 5–6 entries.*

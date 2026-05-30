# Agent Stale-Memory + Failure-Mode Confabulation — Work Notes

**Feature**: Two prompt-layer strengthenings + a new agent-replay test surface to stop the agent from (a) citing stale memory notes about repaired tool capabilities and (b) homogenizing distinct in-turn tool failures into whichever failure phrase is most rehearsed.
**Started**: 2026-05-27 (single-file plan filed); promoted to phased layout 2026-05-28.
**Branch**: `feature/agent-stale-memory-and-failure-mode-confabulation`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-27 — Bug discovery + single-file plan filed

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — confirmed applicable invariants: `INV-A005` (Tool-Failure Narratives Match Trace Evidence, v1.21), `INV-A002` (Synthesis Reasoning Floor, v1.8 bullet 3 memory-validation requirement).
- Re-read [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — confirmed Step 3 freshness rule at line 183 and §INV-A005 block at lines 156–175 reflect the 2026-05-26 strengthening.
- Reviewed muscle-question regression sweep runs 4 + 5 (against rebuild-2 and rebuild-3 sandboxes). Run 4 reproduced Bug 1; Run 5 reproduced Bug 2.

**Applicable Invariants**:
- **INV-A005**: extended (catalogue + decompose rule); not modified at v1.21.
- **INV-A002 v1.8 bullet 3**: Step 3 currently has a freshness check but no capability-claim override. Bug 1 violates the v1.8 memory-validation requirement at the use-site.
- **INV-P001**: no new egress, no new tool surface — prompt + local test edits only.

**Key Insights**:
- The two bugs share the same root cause: **the agent's failure narratives drift toward the most-accessible explanation from prior context, not the one supported by this turn's structured trace.** Bug 1 is the memory-citation face of this; Bug 2 is the rehearsed-phrasing face.
- Plan 1 (sidecar repair) and Plan 2 (`wrapHostResponse` host-failure surfacing) shipped 2026-05-27 — both prerequisites for the catalogue's Row 2 entry, which describes Plan 2's prose verbatim.
- The catalogue's structural-signal column must quote the plugin's actual failure prose verbatim, not paraphrase it. Source: [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) — `rejectIfPlaceholder` (lines 297–333), `wrapHostResponse` (lines 220–244), `safeCall`/`safePost` (lines 185–197, 254–266).

**Completed Today**:
- [x] Filed single-file plan at `docs/plans/active/agent-stale-memory-and-failure-mode-confabulation.md`.

**Decisions Made**:
- Default Q2 resolution: block-only memory supersession, no auto-write. Rationale: keep agent writes scoped to deliberate synthesis turns.
- Default Q3 resolution: inline catalogue in the prompt, no external `failure-phrases.md` fixture. Rationale: lower coordination cost for the first iteration; promote if the catalogue grows past 6 entries.

**Blockers / Issues**:
- None.

**Next Steps**:
1. Promote to full phased layout per [docs/plans/CLAUDE.md](../../CLAUDE.md).
2. Begin Phase 1 (Step 3 amendment) via TDD.

---

### 2026-05-28 — Promoted to full phased layout

**Context Review Completed**:
- Re-read [docs/plans/CLAUDE.md](../../CLAUDE.md) — confirmed the full directory layout is required because Phase 3 adds a new test surface (`tests/agent_replay/`) and the prompt edits affect `INV-A005` + `INV-A002` enforcement (more than one subsystem touched).
- Mapped the code surfaces this plan touches via an Explore agent. Captured exact line numbers for:
  - Step 3 freshness bullet ([agent-system-prompt.md:183](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L183))
  - §INV-A005 anchor ([agent-system-prompt.md:156](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L156)) + forbidden-phrase rule ([line 172](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L172))
  - Plugin failure-prose templates in [index.ts:185–333](../../../../packages/nemoclaw-plugin/src/index.ts#L185)
  - Existing INV-A005 invariant tests ([test_invA005_no_serialization_bug_confabulation.py:50–98](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py#L50), [test_agent_system_prompt_contract.py:435–482](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py#L435))
  - Replay-harness landscape: `_live_smoke/` exists (live LLM orchestrator, no fixture-driven mocked envelopes); `tests/agent_replay/` does not exist.
- Confirmed muscle question text from user: *"Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."* Used verbatim in AC8 + Phase 3 fixtures + manual gate.

**Applicable Invariants**:
- Unchanged from 2026-05-27.

**Completed Today**:
- [x] Created [spec.md](spec.md) — goal, background, 8 ACs, applicable invariants, privacy-and-safety section, out-of-scope, dependencies, 3 open questions (Q1 model choice, Q2 auto-write default, Q3 catalogue-fixture default).
- [x] Created [development-plan.md](development-plan.md) — current-state analysis, files-to-modify table, files-to-create table, solution diagram, 5 key design decisions, schema/provenance impact (none), privacy/egress impact (none in production runtime; opt-in env var for replay harness), phase overview table, per-phase deliverables + invariants + success criteria, testing strategy by category, documentation updates checklist, progress tracking table, 4 open risks.
- [x] Created [phases/phase-1.md](phases/phase-1.md) — Step 3 capability-claim amendment. 1 new test (`test_invA002_step3_memory_validation_special_cases_capability_claims`). Verifies `INV-A002` v1.8 bullet 3.
- [x] Created [phases/phase-2.md](phases/phase-2.md) — §INV-A005 catalogue extension. 4 new tests (2 contract + 2 trace-walker). Verifies `INV-A005` v1.21. Catalogue table draft with 5 rows + decompose rule + anti-pattern worked example.
- [x] Created [phases/phase-3.md](phases/phase-3.md) — Agent-replay harness. 3 scenario tests with mocked envelopes + real LLM call. Verifies `INV-A005` + `INV-A002` (round-trip) + `INV-P001` (default-no-egress).

**Decisions Made**:
- **Promotion to full directory layout** was the right call: the protocol's threshold is "more than one subsystem" or "changes the test surface," and Phase 3 introduces an entirely new `tests/agent_replay/` test category that affects `INV-P001` enforcement (the egress-gated LLM call). A single-file plan would have hidden the test-surface decision.
- **Inline catalogue (Q3 default)** preserved during promotion. If the catalogue grows past 6 entries during Phase 2 RED, revisit toward an external fixture.
- **Block-only memory supersession (Q2 default)** preserved during promotion.
- **Q1 (model choice)** explicitly deferred to Phase 3 Step 3.2. Initial draft proposed trying a cheaper model first — *corrected 2026-05-28* (see later session): GenomeClaw pins `gpt-5.5`; no cheaper-model substitutes are used in this project.

**Blockers / Issues**:
- None.

**Next Steps**:
1. Resolve Open Question Q1 (which model the replay harness uses). Check the configured-egress allowlist for `gpt-4o-mini` availability; if absent, escalate as a Phase 3 prerequisite or default to `gpt-5.5`.
2. Begin Phase 1 RED: write `test_invA002_step3_memory_validation_special_cases_capability_claims`, confirm it fails for the right reason, paste output here.
3. Move to Phase 1 GREEN: insert the 4th Step 3 bullet + anti-pattern / target-pattern worked example.

---

### 2026-05-28 — Phase 1 RED → GREEN → REFACTOR

**Context Review Completed**:
- Re-read [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) to match the existing test-file style (simple `_read_prompt()` + substring assertions; one regex-based test).
- Read the live Step 3 section in [agent-system-prompt.md:177–185](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L177) to ground the test on the actual section text.
- Decided to add a small `_extract_step3_section` helper so the new test's signal-name checks (`_pgs_list`, `genomeclaw_status`, `genomeclaw_gene`) are section-scoped. Without scoping, the assertion would always pass — the tool-catalog elsewhere in the prompt names two of those tools regardless of whether Step 3 teaches them as supersession signals.

**Applicable Invariants**:
- **INV-A002** v1.8 bullet 3 — directly enforced by the new test.
- **INV-A001** supersession mechanism — adjacent; the existing `test_invA001_system_prompt_documents_supersession_mechanism` continues to pass.
- **INV-P001** — n/a for this phase; prompt + test edits only.

**RED step output** (failing because Step 3 had no capability-claim bullet):

```text
tests/invariants/test_agent_system_prompt_contract.py::test_invA002_step3_memory_validation_special_cases_capability_claims FAILED

E       AssertionError: INV-A002 v1.8 bullet 3: Step 3 must carry a dedicated
        capability-claim validation bullet that special-cases tool-failure /
        'X is unavailable' memory notes
E       assert ('capability claim' in "### step 3 — memory validation ..." or
                'capability claims' in "### step 3 — memory validation ...")

tests/invariants/test_agent_system_prompt_contract.py:193: AssertionError
```

The failure showed the live Step 3 had exactly three bullets (conclusion / source quality / freshness), confirming the test fails for the **right** reason ("4th bullet is missing"), not for a transient issue.

**GREEN step**: edited [agent-system-prompt.md:179–197](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L179):

- Promoted "Apply three independent checks" → "Apply four independent checks".
- Inserted bullet 4 ("Capability claims") with the freshness-override rule + three signal examples (`_pgs_list`, `genomeclaw_status`, `genomeclaw_gene`) + anti-pattern citation + target-pattern supersession example.
- Closing "If any check fails" still applies — phrasing already general, now covers four checks.

**REFACTOR step**: ran lint (`ruff check`) — clean. Read the rendered Step 3 section back end-to-end — flows cleanly; bullet 4's nested structure (signals + worked-example pair) is the most complex check but warranted given it teaches a discipline shift, not just a check.

**Completed Today**:
- [x] Added `_extract_step3_section` helper + `test_invA002_step3_memory_validation_special_cases_capability_claims` to [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py).
- [x] Added Step 3 bullet 4 (Capability claims) + worked-example pair to [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md).
- [x] Verified: 14 prompt-contract tests pass, all previously-passing tests still pass.
- [x] Verified: lint clean.

**Decisions Made**:
- Section-scoped assertions via a small inline `_extract_step3_section` helper. Rationale: the existing test file has no shared section-extraction utility and the new test is the first one needing section-scoped logic. If a second Step-3-scoped test arrives (e.g., during Phase 2), promote the helper to a module-level utility.

**Blockers / Issues**:
- One pre-existing failure in [test_invP002_policy_preset_shape.py::test_invP002_policy_preset_targets_host_openshell_internal](../../../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py) — asserts port 8643, current policy preset has port 8645. Confirmed unrelated: my edits touched only `agent-system-prompt.md` and `test_agent_system_prompt_contract.py`; this test is about the network policy preset. **Out of scope for this plan.** Mentioned here so a future contributor doesn't blame Phase 1 for it.

**Next Steps**:
1. Phase 2 RED: write the four new tests covering catalogue rows + decompose-per-tool rule + trace-walker forbidden-phrase extensions.
2. Resolve Open Question Q1 before starting Phase 3.

---

### 2026-05-28 — Phase 2 RED → GREEN → REFACTOR

**Context Review Completed**:
- Re-read [test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) to ground the new trace-walker tests in the existing module shape. Found the parametrized walker iterates `docs/reports/*.trace.json`; adding fixture files to that tree would pollute the production trace corpus. Decided to use **inline synthetic trace dicts** in new standalone tests, not file fixtures.
- Re-read §INV-A005 in [agent-system-prompt.md:156–175](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L156). Confirmed the existing section already named `"argument-shape guard fired"` as a forbidden paraphrase at line 172 (since 2026-05-26) but the trace-walker's `_FORBIDDEN_PHRASES` tuple did NOT include it — so the prompt taught the rule but the test didn't enforce it. Phase 2 closes that gap.
- Grep-checked the prompt for `"Failed to connect"`, `"placeholder string"`, `"host-side structured failure"`, `"TypeBox"`, `"connection refused"`. Only `"host-side structured failure"` was present (line 174); section-scoping needed for the catalogue contract test.

**Applicable Invariants**:
- **INV-A005** v1.21 — extended enforcement surface (prompt + tests). Invariant text unchanged.

**RED step output** (7 failures, 1 pass):

```text
FAILED test_invA005_system_prompt_carries_failure_phrase_catalogue[argument-shape guard-placeholder string]
FAILED test_invA005_system_prompt_carries_failure_phrase_catalogue[host returned status=failed-host-side structured failure]
FAILED test_invA005_system_prompt_carries_failure_phrase_catalogue[connection refused-Failed to connect]
FAILED test_invA005_system_prompt_carries_failure_phrase_catalogue[TypeBox-Expected]
FAILED test_invA005_system_prompt_carries_decompose_per_tool_rule
FAILED test_invA005_trace_walker_flags_argument_shape_guard_without_signal
FAILED test_invA005_trace_walker_recognizes_safecall_catchblock_prose_as_real_failure
PASSED test_invA005_system_prompt_carries_failure_phrase_catalogue[n_variants_in_gene-region_class]
========================= 7 failed, 1 passed in 0.05s ==========================
```

Row 5 (`n_variants_in_gene`/`region_class`) passed in RED because the 2026-05-26 INV-A005 strengthening already taught those at prompt line 173 — the catalogue absorbs that pair into the table now. All other 7 failures are for the right reason: catalogue/decompose-rule absent; new forbidden phrases not in tuple; signal predicate doesn't recognize safeCall catch-block prose.

**GREEN steps**:

1. **Prompt edit** at [agent-system-prompt.md:170–204](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L170): replaced the single forbidden-phrase rule (old line 172) with a 5-row catalogue table + a fallback-for-unfamiliar-shapes rule + a decompose-per-tool rule + 3 worked examples (homogenization anti-pattern; decomposed target pattern; stale-memory anti-pattern cross-linking to Step 3 bullet 4). Kept lines 203-204's per-shape paraphrasing guidance unchanged — it complements the catalogue rather than duplicating it.
2. **Tuple extension** at [test_invA005_no_serialization_bug_confabulation.py:50–67](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py#L50): added 6 new phrases to `_FORBIDDEN_PHRASES` — `"argument-shape guard fired"`, `"rejectifplaceholder rejected"`, `"typebox rejected the parameters"`, `"http connection refused"`, `"network unreachable"`, `"genomeclaw wasn't reachable"`.
3. **Signal-predicate extension** at [test_invA005_no_serialization_bug_confabulation.py:79–138](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py#L79): added `_STRUCTURAL_FAILURE_SIGNALS` tuple covering `rejectIfPlaceholder` prose (`placeholder string`, `argument resolution lost track`), `wrapHostResponse` prose (`host-side structured failure`, `host returned status=failed`), `safeCall`/`safePost` catch-block prose (`Failed to connect`, `fetch failed`). Added `_GENOMECLAW_HTTP_ERROR_PATTERN` regex for `genomeclaw-service <path> -> HTTP <code>`. Rewrote `_trace_has_real_failure` to walk both signal tuples + the regex.

**Test results after GREEN**:
- All 4 new tests pass.
- All 14 previously-passing contract tests still pass.
- All 14 parametrized trace-walker tests still skip (historical traces predate 2026-05-26 binding date).
- 26 passed, 14 skipped in the combined `test_agent_system_prompt_contract.py` + `test_invA005_no_serialization_bug_confabulation.py` run.
- Full invariants suite: 55 passed, 43 skipped, 1 failed — the failure is the pre-existing port-mismatch [test_invP002_policy_preset_shape.py::test_invP002_policy_preset_targets_host_openshell_internal](../../../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py) (same as Phase 1).

**REFACTOR step**:
- Re-read the rendered §INV-A005 section end-to-end (lines 156–204). Flows cleanly: positive rule → mixed-outcome worked example → catalogue → fallback for unfamiliar shapes → decompose rule → 3 anti/target patterns → per-shape paraphrasing. Cross-link to Step 3 bullet 4 in the stale-memory anti-pattern ties Phase 1 and Phase 2 together.
- Lint clean for my two touched files. Pre-existing ruff errors in unrelated test files (`test_invP002_ssrf_runtime_probe.py`, `test_invR002_pgs_compute_task_row_consistency.py`) — out of scope.

**Completed Today**:
- [x] Added 2 prompt-contract tests + 2 trace-walker tests (4 new tests total) to enforce the catalogue and decompose rule.
- [x] Extended `_FORBIDDEN_PHRASES` with 6 new banned phrases.
- [x] Extended `_trace_has_real_failure` to recognize 6 structural-failure prose strings + 1 HTTP-error regex.
- [x] Inserted the §INV-A005 catalogue table (5 rows) + decompose-per-tool rule + 3 worked examples into the prompt.
- [x] Verified: 4 new tests pass; existing contract + walker tests unchanged.

**Decisions Made**:
- **Inline synthetic trace dicts, not file fixtures.** Rationale: keeps the production trace corpus under `docs/reports/` clean. The parametrized walker test iterates that tree, so adding fixture files there would either pollute the corpus or require excluding them — added complexity for no gain.
- **Coarse signal predicate + strict prompt-contract enforcement.** The trace-walker's `_trace_has_real_failure` recognizes *any* structural-failure signal (collapsed across `rejectIfPlaceholder` / `wrapHostResponse` / safeCall / network-error families), while the prompt-contract test's `_CATALOGUE_ROWS` enforces the strict per-phrase pairing. Rationale: the walker is a coarse safety net for catching gross confabulation; per-phrase pairing is something the agent must learn from the prompt, and the prompt content is what the contract test pins.
- **Kept legacy line-174 host-side-failure guidance** in addition to the catalogue's Row 2. The line-174 content is a *practical "when in doubt, say X"* — the catalogue is the *strict per-phrase rule*. They serve different reader-tasks; both stay.

**Blockers / Issues**:
- One pre-existing failure in `test_invP002_policy_preset_shape.py` (port 8643 vs 8645) — same as noted under Phase 1. Out of scope.

**Next Steps**:
1. Resolve Open Question Q1 (model choice for the replay harness).
2. Begin Phase 3 RED: write the three scenario tests + conftest with skip-when-`GENOMECLAW_REPLAY_LLM`-not-set guard.

---

### 2026-05-28 — Phase 3 scope-reduction (Option 3) + Q1 resolution

**Context Review Completed**:
- Read [tests/_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py) — confirmed the existing live harness pins `gpt-5.5` at line 224 and uses a docker-sandbox + real host service pattern (heavy).
- Counted Phase 3's implementation cost as scoped: ~200+ lines of conftest + driver + tool-schema translation + 3 fixture sets, real `gpt-5.5` API calls per run, brand-new test category to maintain.
- Re-read the spec's AC6/AC7 (automated replay scenarios) vs. AC8 (manual muscle-question gate). The manual gate is the highest-fidelity verification — it's the actual regression scenario that surfaced both bugs.
- Asked the user before building: presented three options (lightweight `httpx` harness; reuse `_live_smoke/`; defer automated harness, run manual gate).

**Applicable Invariants**:
- **INV-A005** (catalogue + decompose enforcement) — already shipped via Phase 2 content tests.
- **INV-A002** v1.8 bullet 3 — already shipped via Phase 1 content test.
- **INV-P001** — preserved: no new egress surface added.

**Key User Corrections**:
- *"No! We use gpt-5.5 in this project."* — proposed `gpt-4o-mini` as a cost-saving substitute. **Rejected**: GenomeClaw pins `gpt-5.5` across all harnesses (the live-smoke harness pins it, the agent runs on it, no project-wide budget for cheaper substitutes). Saved as a feedback memory at `~/.claude/projects/-Users-hugi-GitRepos-GenomeClaw/memory/feedback_pinned_model.md` so this rule applies project-wide going forward.
- *"Option 3."* — user chose to defer the automated harness to a follow-up plan; Phase 3 reduces to the manual AC8 gate.

**Completed Today**:
- [x] Rewrote [phase-3.md](phases/phase-3.md) to reflect Option 3 — manual AC8 gate is the verification path; automated replay harness deferred.
- [x] Scrubbed all `gpt-4o-mini` references from [spec.md](spec.md), [development-plan.md](development-plan.md), and earlier work-notes entries (the original Q1 wording carried the wrong default-model suggestion).
- [x] Marked Q1 resolved + AC6/AC7 as deferred in [spec.md](spec.md).
- [x] Filed follow-up plan stub at [docs/plans/completed/agent-replay-harness-for-prompt-regression.md](../agent-replay-harness-for-prompt-regression.md) — single-file plan documenting the deferred harness, its scope, its prioritization trigger, and the project rule that `gpt-5.5` is the model (no cheaper substitutes).
- [x] Updated [INVARIANTS.md](../../../reference/INVARIANTS.md) to v1.21.1: added the Phase 1 + Phase 2 enforcement-surface extensions to `INV-A005`'s **How to verify** + linked the new contract test under `INV-A002`'s **How to verify** (bullet 4 = capability claims). Logged the v1.21.1 changelog entry referencing this plan.

**Decisions Made**:
- **Phase 3 scope reduced to the manual AC8 gate.** Rationale: Phase 1 + Phase 2 already shipped the prompt-discipline guardrails + content-gate tests that close the actual reported regressions; an automated behavioral replay harness adds value but isn't load-bearing here.
- **`gpt-5.5` is the pinned model — no cheaper substitutes.** Project-wide rule; saved as a feedback memory.
- **Follow-up plan filed as a single-file stub**, not a phased directory layout. Rationale: it's a "filed, not yet scoped" plan; the directory layout is premature until prioritization fires.

**Blockers / Issues**:
- The pre-existing `test_invP002_policy_preset_shape.py` port-mismatch failure (8643 vs 8645) persists — still out of scope; flagged again here so it doesn't get accidentally attributed to this plan when the closure is reviewed.

**Next Steps (operator action)**:
1. Execute the manual AC8 gate per [phase-3.md](phases/phase-3.md) — verbatim muscle question against the rebuilt sandbox.
2. Capture the trace under `docs/reports/manual-ac8-muscle-question-<YYYY-MM-DD>.trace.json`.
3. Append the result + assertions check to the "Manual AC8 Gate" section below.
4. Move the plan to `docs/plans/completed/` once the manual gate is verified.

---

## Manual AC8 Gate

**Status**: Executed 2026-05-28. **Mixed result — partial regression discovered.**

**Setup (actual)**: Sandbox rebuilt via the new [scripts/sandbox-up.sh --rebuild](../../../../scripts/sandbox-up.sh) which delegates to [scripts/onboard-sandbox.sh](../../../../scripts/onboard-sandbox.sh). New container: `openshell-genomeclaw-3fc60667-25fa-4740-bfb7-25546c16f032`. Phases 1+2 prompt edits baked into the new image. Plugin loaded successfully (no EACCES warning). Gateway started with `OPENAI_API_KEY` in env. Model: `gpt-5.5`, thinking: `xhigh`, runner: embedded. **Host service NOT started before the gate run** — which is actually closer to the Bug-2 scenario (every `genomeclaw_*` call hits a network failure).

**Verbatim user prompt** sent:

> Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet.

**Trace path**: [docs/reports/demo-2026-05-28-logs/manual-ac8-muscle-question.trace.json](../../../reports/demo-2026-05-28-logs/manual-ac8-muscle-question.trace.json) (placed under the dated-logs subdirectory so the existing trace-walker date convention picks it up).

**Tool summary**: 31 calls across 9 tool types (`update_plan`, `genomeclaw_status`, `memory_search`, `genomeclaw_gene`, `genomeclaw_pgs_list`, `genomeclaw_findings`, `genomeclaw_pgs_compute`, `exec`, `write`). `toolSummary.failures: 0` — see Finding 3 below.

**Final-assistant-visible-text excerpt**:

> I can't honestly give **genome-personalized** recommendations yet: `genomeclaw_status`, `genomeclaw_findings`, and `genomeclaw_pgs_list` returned `fetch failed`, **and the gene/PRS calls hit an object-shape serialization error**, so I don't have your ACTN3/FTO/APOE/etc. results.
>
> [generic recommendations follow…]

### Assertion check

- [x] **Reply does NOT cite "GenomeClaw is currently unavailable" if `genomeclaw_status` returns HTTP 200.** Vacuous pass — the host service was down, so `genomeclaw_status` did NOT return HTTP 200; the precondition didn't fire. The agent did honestly describe the current state ("not reachable for this turn"), not a stale memory claim. **Bug 1 not directly exercised** because no pre-staged stale memory note was injected; would need a follow-up turn with `nemoclaw genomeclaw exec` writing a stale capability note before the prompt.
- [x] **If `_pgs_list` returns PGS000018, reply cites the live percentile.** Vacuous pass — same reason; `_pgs_list` itself fetch-failed.
- [ ] **Failure phrases match the §INV-A005 catalogue's required structural signals.** ❌ **FAIL.** The agent reached for the phrase **"object-shape serialization error"** for the gene/PRS calls. This is not literally in the Phase 2 `_FORBIDDEN_PHRASES` tuple ("argument-serialization bug" / "argument-shape guard fired" / "rejectIfPlaceholder rejected"), so the trace-walker doesn't flag it — but it is the **same class of confabulation**: a guard-rejection paraphrase asserted without `rejectIfPlaceholder` prose in the actual tool output. **The catalogue is incomplete.**
- [ ] **If multiple tools fail, reply decomposes per-tool.** ⚠ **Partial.** The reply does decompose `genomeclaw_status`/`_findings`/`_pgs_list` (named correctly as "fetch failed") *separately* from the gene/PRS cluster — but then homogenizes the gene/PRS cluster as "object-shape serialization error." Half-honored, half-violated. Same root cause as Bug 2: reaching for the most-rehearsed framing for a cluster whose actual failure mode (host unreachable) is identical to the rest.

### Trace-walker test result

```bash
$ uv run pytest tests/invariants/test_invA005_no_serialization_bug_confabulation.py::test_invA005_no_serialization_bug_phrasing_without_real_failure[manual-ac8-muscle-question.trace.json] -xvs
PASSED
```

**But the pass is vacuous.** See Finding 3.

### Findings — three gaps surfaced by the manual gate

1. **Catalogue incomplete: "object-shape serialization error" paraphrase not caught.** The agent found a way to assert a fictitious guard rejection using a phrase not in the catalogue. Phase 2's Row 1 enumerates *"argument-shape guard fired" / "rejectIfPlaceholder rejected" / "argument-serialization bug" / "Q-001 fired"* but not *"object-shape serialization error"* or *"serialization error"* without the *"bug"* suffix. Both prompt + `_FORBIDDEN_PHRASES` need extending. The agent's natural-language space for this class of confabulation is wider than the explicit enumeration.

2. **Decompose rule needs a host-down worked example.** Phase 2's anti/target examples covered the all-failed-network case explicitly, and the reply did honor it for the first cluster of tools — but the same agent slid into homogenization for the second cluster on the same turn. The rule's discipline doesn't transfer across tool clusters within one reply. Either the rule needs strengthening ("apply the decompose discipline cluster-by-cluster, not just turn-globally") or the worked example needs an explicit "all gene/PRS calls hit the same network failure" case.

3. **Trace-walker `_trace_has_real_failure` is structurally circular under `openclaw agent --json`.** The Phase 2 extension scans `payloads[].text` for structural failure signals (`Failed to connect`, `placeholder string`, etc.) — but in `openclaw agent --json` output, the only payload IS the agent's final reply text. So the agent saying "fetch failed" in its reply satisfies the signal predicate that's supposed to license the agent's use of the phrase. The predicate is now self-fulfilling. The test still works for `toolSummary.failures > 0` cases (the original check), but the payload-text extension is unreachable on standard agent traces. **The test passed on this trace not because the agent was correct, but because the predicate's circular structure trivially accepted it.** Either:
   - The trace output format needs to surface per-tool-call envelopes (a plugin/host change), or
   - The trace-walker should restrict signal-text scanning to tool-result payloads (which `agent --json` doesn't currently emit), or
   - Fall back to `toolSummary.failures > 0` only and accept that the catalogue's enforcement is prompt-content-only.

### Follow-ups filed (not in this plan's scope to fix)

- [ ] Extend `_FORBIDDEN_PHRASES` with "object-shape serialization error" + adjacent paraphrases. File as a small fast-follow plan.
- [ ] Iterate on §INV-A005 catalogue/decompose-rule wording to cover the cluster-by-cluster discipline. Same fast-follow plan.
- [ ] Fix the trace-walker's predicate-circularity issue. Either depends on a plugin change to surface tool-call envelopes, or accept the prompt-content-only enforcement scope. File as a separate plan.
- [ ] Run the AC8 gate WITH the host service up + a pre-staged stale memory note to actually exercise Bug 1's supersession path.

The plan's content-gate tests (Phase 1 + Phase 2 contract tests) all still pass as expected — the prompt teaches the rule correctly, the trace-walker mechanism is sound, but the catalogue's coverage of the agent's actual paraphrase-space is genuinely incomplete. **Phases 1+2 are a real improvement, not the full fix.**

---

## Phase Progress

### Phase 1: Step 3 Capability-Claim Amendment
**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28

#### Test Results

```text
tests/invariants/test_agent_system_prompt_contract.py::test_invA002_step3_memory_validation_special_cases_capability_claims PASSED
```

Full contract suite: **14 passed, 14 skipped** (skips are 2026-05-24/25 traces that predate the 2026-05-26 INV-A005 binding date — expected).

#### Results

- Added `_extract_step3_section` helper + new contract test to [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py).
- Added Step 3 bullet 4 ("Capability claims") to [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) with the freshness-override rule, three signal examples (`_pgs_list`, `genomeclaw_status`, `genomeclaw_gene`), and an anti-pattern/target-pattern worked-example pair.
- 18 net new lines in the prompt; 80 new lines in the test file.

#### Notes

- Section-scoped assertions required a small inline helper since the existing test file uses whole-prompt substring checks. Promote to module-level if a second Step-3-scoped test arrives.
- Pre-existing failure in `test_invP002_policy_preset_shape.py` (port 8643 vs 8645) is unrelated and out of scope for this plan.

---

### Phase 2: §INV-A005 Catalogue Extension
**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28

#### Test Results

```text
test_invA005_system_prompt_carries_failure_phrase_catalogue[argument-shape guard-placeholder string]         PASSED
test_invA005_system_prompt_carries_failure_phrase_catalogue[host returned status=failed-host-side ...]       PASSED
test_invA005_system_prompt_carries_failure_phrase_catalogue[connection refused-Failed to connect]            PASSED
test_invA005_system_prompt_carries_failure_phrase_catalogue[TypeBox-Expected]                                PASSED
test_invA005_system_prompt_carries_failure_phrase_catalogue[n_variants_in_gene-region_class]                 PASSED
test_invA005_system_prompt_carries_decompose_per_tool_rule                                                   PASSED
test_invA005_trace_walker_flags_argument_shape_guard_without_signal                                          PASSED
test_invA005_trace_walker_recognizes_safecall_catchblock_prose_as_real_failure                               PASSED
```

Combined contract + walker run: **26 passed, 14 skipped** (skips: 2026-05-24/25 traces predating the 2026-05-26 binding date — expected). Full invariants suite: 55 passed, 43 skipped, 1 pre-existing failure (port mismatch, unrelated).

#### Results

- Added [`_extract_invA005_section`](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) helper + `_CATALOGUE_ROWS` tuple + 2 new contract tests (parametrized catalogue + decompose rule).
- Added [`_STRUCTURAL_FAILURE_SIGNALS`](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) tuple + `_GENOMECLAW_HTTP_ERROR_PATTERN` regex + 2 new trace-walker tests (synthetic dicts: argument-shape-guard-without-signal flagging + safeCall-prose recognition).
- Extended `_FORBIDDEN_PHRASES` with 6 new banned phrases.
- Edited [agent-system-prompt.md:170–204](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md#L170): replaced single forbidden-phrase rule with the 5-row catalogue table + fallback rule for unfamiliar shapes + decompose-per-tool rule + 3 worked examples (homogenization anti-pattern, decomposed target pattern, stale-memory anti-pattern with cross-link to Step 3 bullet 4).

#### Notes

- Decision: inline synthetic trace dicts, not file fixtures (rationale logged in work-notes session above).
- Decision: coarse `_trace_has_real_failure` predicate (collapsed-signal) + strict prompt-contract enforcement (per-phrase pairing) — different layers, different jobs.
- Cross-references between §INV-A005's stale-memory anti-pattern and Step 3 bullet 4 tie Phase 1 + Phase 2 together for the reader.

---

### Phase 3: Agent-Replay Harness
**Status**: Pending
**Started**: <date>
**Completed**: <date>

#### Test Results
*(populated after Phase 3 GREEN lands)*

#### Results
*(populated after Phase 3 GREEN lands)*

#### Notes
*(populated during Phase 3 work)*

---

## Key Decisions

### Decision 1: Promote single-file plan to full directory layout
**Date**: 2026-05-28
**Context**: The single-file plan ([the old `docs/plans/active/agent-stale-memory-and-failure-mode-confabulation.md`, now deleted]) was filed 2026-05-27 against the [docs/plans/CLAUDE.md](../../CLAUDE.md) "small efforts" exception. On promotion review, two factors pushed past the threshold: (a) Phase 3 introduces a brand-new `tests/agent_replay/` test category that doesn't exist in the toolkit today, and (b) the prompt edits affect `INV-A005` + `INV-A002` enforcement surfaces simultaneously (two invariants, two existing test files).
**Decision**: Migrate to full directory layout with `spec.md` + `development-plan.md` + `work-notes.md` + `phases/phase-{1,2,3}.md`. The original single-file plan was already absent from disk + git at promotion time; content was migrated forward from the promoting session's loaded copy.
**Rationale**: The protocol's "more than one subsystem / changes test surface / changes provenance-or-egress behavior" rule applies. A single-file plan would have hidden the egress-gate decision in the replay harness.
**Alternatives Considered**: Keep single-file + add a work-notes section. Rejected because Phase 3's test-surface introduction warrants the full TDD-scaffold-per-phase treatment.
**Affected Invariants**: `INV-A005`, `INV-A002`, `INV-P001`.

### Decision 2: Block-only memory supersession (Q2 default)
**Date**: 2026-05-27
**Context**: When Step 3's new capability-claim bullet fires, the agent supersedes the stale memory note. Should it also auto-write a superseding note?
**Decision**: Block-only — the agent stops citing the stale claim, does not auto-write a replacement.
**Rationale**: Keep agent writes scoped to deliberate synthesis turns. Auto-write would conflate "I noticed this note is stale" with "this is now the canonical fact" — the latter requires synthesis discipline that this plan doesn't introduce.
**Alternatives Considered**: Auto-write a superseding note with the live tool result as the new claim. Rejected for v1; revisit if the memory store accumulates stale capability notes.
**Affected Invariants**: `INV-A001` (write-site provenance discipline preserved by *not* auto-writing).

### Decision 3: Inline catalogue, not external fixture (Q3 default)
**Date**: 2026-05-27
**Context**: The §INV-A005 catalogue can either live inline in the agent system prompt (with the contract test asserting presence) or in a separate fixture file at `packages/nemoclaw-plugin/sandbox/failure-phrases.md` that both prompt and tests read.
**Decision**: Inline for the first iteration. Promote to external fixture if the catalogue grows past 6 entries or the plugin team needs to register new phrases independently of prompt edit cycles.
**Rationale**: Lower coordination cost. The catalogue is small (5 rows) and the failure prose is stable.
**Alternatives Considered**: External fixture from day one. Rejected for v1 — premature abstraction; promote when the churn cost actually materializes.
**Affected Invariants**: `INV-A005` enforcement surface — both options are valid; this is a packaging choice.

---

## Files Modified

### Created
- [spec.md](spec.md) — feature specification.
- [development-plan.md](development-plan.md) — chosen-solution plan + phase overview.
- [phases/phase-1.md](phases/phase-1.md) — Step 3 amendment TDD scaffold.
- [phases/phase-2.md](phases/phase-2.md) — §INV-A005 catalogue TDD scaffold.
- [phases/phase-3.md](phases/phase-3.md) — Agent-replay harness TDD scaffold.

### Modified
- [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — Phase 1: added 4th Step 3 validation bullet (Capability claims) with worked-example pair. Phase 2: replaced single forbidden-phrase rule with 5-row catalogue + decompose-per-tool rule + 3 worked examples.
- [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — Phase 1: added `_extract_step3_section` + `test_invA002_step3_memory_validation_special_cases_capability_claims`. Phase 2: added `_extract_invA005_section` + `_CATALOGUE_ROWS` + parametrized `test_invA005_system_prompt_carries_failure_phrase_catalogue` + `test_invA005_system_prompt_carries_decompose_per_tool_rule`.
- [packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py](../../../../packages/toolkit/tests/invariants/test_invA005_no_serialization_bug_confabulation.py) — Phase 2: extended `_FORBIDDEN_PHRASES` (+6 phrases); added `_STRUCTURAL_FAILURE_SIGNALS` + `_GENOMECLAW_HTTP_ERROR_PATTERN`; rewrote `_trace_has_real_failure`; added `_trace_walker_flags` helper + 2 synthetic-trace tests.

### Deleted
- None during promotion. The original single-file plan at `docs/plans/active/agent-stale-memory-and-failure-mode-confabulation.md` was no longer on disk and was never tracked in git history at the time of promotion (verified via `git log --all -- <path>` and `find`). Its content (read into the promoting session's context from an earlier Read tool call) was migrated forward into the directory layout above.

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None proposed. After Phase 3 lands, update `INV-A005`'s **How to verify** entry to point at the new `tests/agent_replay/` directory.

### Other Documentation
- [ ] [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — Phase 1 + Phase 2 edits.
- [ ] `.claude/agents/*.md` — none.
- [ ] Root [CLAUDE.md](../../../../CLAUDE.md) — none.

---

## Open Risks & Follow-ups

- **R1** Replay tests may flake under model nondeterminism — see development-plan R1 mitigation.
- **R2** Catalogue may grow past 6 entries — see development-plan R2 mitigation.
- **R3** Auto-write of superseding memory notes (deferred Q2) — file a follow-up plan if observed need.
- **R4** Host-service restart fragility (out of scope) — file a separate infrastructure plan if Bug 2 recurs from network failures rather than fixture-driven scenarios.

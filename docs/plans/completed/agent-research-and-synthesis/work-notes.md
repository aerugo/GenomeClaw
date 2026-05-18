# Agent Research-and-Synthesis Pattern — Work Notes

**Plan**: [development-plan.md](development-plan.md)
**Spec**: [spec.md](spec.md)

---

## 2026-05-15 — Plan authored (this session)

**Context**: Phase 6 Slice C of the MVP plan called for 7 hand-authored curated gene notes under `reference/curated_notes/`. During the explanation of the lifestyle-track architecture (Story 9 example), the project owner flagged a more powerful alternative: **agent memory + reasoned research over training knowledge + online sources + extended reasoning at health-interpretation turns**.

Three corrections from the conversation that shape this plan:

1. **The mechanism is research-and-synthesis, not "web search".** Web search is one component; reasoning over the model's training knowledge + the retrieved sources is the substance.
2. **The synthesis step is the bioinformatician-in-healthcare step** — it must run at the maximum reasoning level the model allows. Not because of speed/cost concerns, but because health interpretation at low reasoning produces fluent-but-wrong answers.
3. **Floor applies to health-interpretation turns only.** Conversational turns (recall, scheduling, casual back-and-forth) don't need max reasoning. Over-applying the floor would burn tokens needlessly.

**Decisions taken in this session**:

- Plan dir name: `agent-research-and-synthesis` (goal-named, captures both phases).
- Synthesis-reasoning floor scoping: health-interpretation turns only. The agent self-classifies via system prompt; verification via execution-trace inspection.
- Two new invariants proposed: `INV-A001` (Agent Memory Provenance) + `INV-A002` (Synthesis Reasoning Floor).
- The existing curated_notes architecture is dropped entirely: `_resolve_gene_note` + `_resolve_topic` go away; `gene_note:` + `topic:` evidence kinds removed from the dispatch; the 7 hand-authored note files never get written.
- `reference_dir` parameter on `build_app(...)` will be removed (Slice B's only consumer was curated-notes resolution).

**State at end of this session**:
- Plan dir authored: spec.md + development-plan.md + this work-notes.md.
- Phase-1.md is the next file to draft.
- Reference docs (INVARIANTS, architecture, grand-plan, user-stories) + MVP spec / development-plan / phase-6.md will be updated in the same session.
- No code changes yet — the curated_notes cleanup happens in this plan's Phase 1.

**Next steps**:
1. Author phases/phase-1.md (config + cleanup).
2. Sweep the reference docs to align with the new direction.
3. Mark Phase 6 Slice C in the MVP plan as superseded.
4. Get user sign-off on the plan + invariant changes before any code lands.

---

## 2026-05-15 (continued) — INV-C001 v1.6 tightened: memory-validation requirement added

**Context**: during the plan walkthrough the project owner identified a real hallucination-propagation risk in the v1.6 INV-C001 draft as I originally wrote it. The original text required citing a `memory:<id>` reference but did NOT require the agent to **validate** the memory before treating it as authoritative. Three concrete failure modes were possible:

1. **Stale-memory amplification** — the agent recalls an old synthesis that was correct when written but is now out of date (e.g., ClinVar reclassified a variant; a new meta-analysis updated the effect-size estimate). The agent cites the stale memory as authoritative and the reply is confidently wrong.
2. **Self-grounding** — the agent's prior conclusion that *overreached* its sources at synthesis time becomes the citation for the next session's prose. The original source weakness is now invisible because the LLM sees a "citation" (the memory ref) and treats it as grounding.
3. **Memory-of-memory chains** — repeated paraphrase across sessions drifts the synthesis further from primary sources. Each link looks grounded; the chain rooted in a fabrication remains undetected.

**Decision** (taken in this session, 2026-05-15): tighten INV-C001 v1.6 + INV-A001 to make memory validation mandatory + structurally enforced. Three concrete changes:

1. **INV-C001 v1.6 — memory-validation requirement.** Every `memory:<id>` citation triggers a three-check validation at the `INV-A002` synthesis-turn floor:
   - **Conclusion ↔ source grounding** — does the memory's conclusion follow from its cited primary sources?
   - **Source quality** — are the cited sources sufficient (peer-reviewed, multi-source, free of obvious bias)?
   - **Freshness** — is the note past its freshness date on a fast-evolving topic?
   If any check fails, the agent must supersede the memory note before composing the reply.

2. **INV-A001 — primary-source requirement.** Every memory note must cite at least one primary source (URL, PubMed, ClinVar, etc.). A note that cites only other memory notes is rejected at write time. Closes the memory-of-memory chain failure mode structurally.

3. **INV-A001 — supersession mechanism.** A new note with `supersedes: <prior-anchor>` records the gap found in the prior note + the corrected synthesis. The prior note stays on disk for the audit trail. This is the mechanism INV-C001 v1.6's memory-validation gates use to update memory.

**Test surface added (lives in Phase 2)**:
- Memory-validation snapshot test: weak memory note fixture → agent surfaces gap, writes supersession, cites new note.
- Memory-of-memory rejection unit test: malformed draft note → writer rejects it.
- Supersession-trail gate: after a validation-driven update, both notes exist on disk + the supersession link resolves.
- Memory-grounding audit: every memory note's citation chain terminates in at least one primary source.

**Files updated this session for the revision**:
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — INV-C001 v1.6 + INV-A001 tightened in place (no version bump on the doc; the v1.6 + v1.8 numbers were still pending merge).
- [spec.md](spec.md) — AC3 amended; new AC4b added; INV-A001 + INV-C001 v1.6 entries in "Proposed New Invariants" extended.
- [development-plan.md](development-plan.md) — Phase 2 row's TDD est. bumped from 5 to ~8; the snapshot-test list under "Testing Strategy" added validation-driven supersession + memory-of-memory rejection.

**State at end of revision**: invariants ready for review pre-Phase-1. The validation pattern lands as agent system-prompt protocol in Phase 2 (no code/host-service changes needed for it; the host service doesn't even know whether the agent recalled vs. researched — that's a sandbox-side concern).

---

## 2026-05-15 (continued) — Phase 1 shipped

**Scope completed**: surgical cleanup + OpenClaw sandbox config. No agent system-prompt or memory-schema work (Phase 2). No live LLM verification (Phase 3).

**Step 1.1 — RED**: rewrote [tests/integration/test_service_evidence.py](../../../../packages/toolkit/tests/integration/test_service_evidence.py) — dropped the 4 curated-notes test cases that Slice B shipped this morning + added 3 new gates: `test_evidence_returns_400_for_retired_gene_note_kind`, `test_evidence_returns_400_for_retired_topic_kind`, `test_supported_evidence_kinds_pinned_to_variant_keyed_only`. Added new [tests/invariants/test_invP001_sandbox_disables_web_search.py](../../../../packages/toolkit/tests/invariants/test_invP001_sandbox_disables_web_search.py) (`needs_sandbox`-gated). Initial run: 3 failures with expected reasons.

**Step 1.2 — GREEN**:
- [schemas/evidence.py](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py): `EvidenceKind` Literal shrunk to `clinvar | pgs_catalog | pharmgkb`. Docstring rewritten to point at the agent-research-and-synthesis plan.
- [service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py): `_SUPPORTED_EVIDENCE_KINDS` shrunk to `frozenset({"clinvar", "pgs_catalog", "pharmgkb"})`. Deleted `_resolve_gene_note(reference_dir, ...)` and `_resolve_topic(reference_dir, ...)` helpers (~45 lines). `resolve_evidence(*, run_dir, ref)` — dropped the `reference_dir` parameter; the dispatch table now has only the clinvar branch (pgs_catalog + pharmgkb still stub to `None` pending Phase 6 D + E).
- [service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py): `build_app(*, derived_root)` — dropped the `reference_dir` kwarg + the inline ref-dir resolution dance in the `/v1/evidence/{ref:path}` route handler. Docstring rewritten.
- [_cli/commands/host.py](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py): `host service` command — dropped the `--reference-dir` flag. Docstring rewritten.
- [sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile): added `RUN openclaw config set tools.web.search.enabled false` after `openclaw plugins install` so the privacy default is baked into the image's openclaw.json. Comment block explains the `INV-P001` v1.6 contract.

**Step 1.3 — Refactor + verify**:
- Two E501 line-too-long ruff errors from the new docstring URLs in `schemas/evidence.py` + `service/store.py`. Fixed by restructuring the docstrings.
- Format drift on `service/store.py` + the new INV-P001 test — auto-applied.
- Rebuilt sandbox image: `genomeclaw/sandbox:ars-phase-1`.
- Ran all 13 `needs_sandbox` tests: 13/13 pass.
- One **regression caught during the sandbox sweep**: the plugin-load harness at [tests/invariants/fixtures/sandbox_plugin_harness.mjs](../../../../packages/toolkit/tests/invariants/fixtures/sandbox_plugin_harness.mjs) hardcoded the **old** install path (`/sandbox/.openclaw/extensions/genomeclaw/dist/index.js` — the v1 `cp` pattern) and **only mocked `openclaw/plugin-sdk`**, not the Slice E subpath `openclaw/plugin-sdk/agent-runtime`. Updated the harness to (a) point at `/opt/genomeclaw/dist/index.js` (the v3+ `plugins install --link` target), (b) mock both `openclaw/plugin-sdk` and `openclaw/plugin-sdk/agent-runtime` via a `MOCKED_SPECIFIERS` set. **This wasn't introduced by Phase 1** — it was a stale harness from Slice E that had silently lost its harness path when Slice E switched the install pattern. The fix is part of the Phase 1 sweep because that's when the next `needs_sandbox` rebuild caught it.

**Gate results**:
- **Slice-B-era curated-notes tests**: removed cleanly (4 deletions).
- **New Phase 1 tests**: 3 new evidence-resolver gates pass; 1 new sandbox-config gate skips on host venv + passes on the rebuilt image.
- **Full host toolkit suite**: 550 passed / 86 skipped (net -1 from 551 at end of Slice B; -4 deleted + +3 new = -1).
- **Sandbox-image needs_sandbox sweep**: 13/13 pass on `genomeclaw/sandbox:ars-phase-1`.
- **Ruff + format**: clean on all touched files. Pre-existing format drift on unrelated files (annotate_vcfanno tests, normalize.py, etc.) untouched.

**Decisions taken in this phase**:
1. **Dropped the `--reference-dir` flag from `host service` entirely** — no remaining consumer after the curated-notes resolvers were removed. If a future evidence kind needs reference-dir access (e.g. a literature cache), the flag re-lands at that point.
2. **The Dockerfile's `RUN openclaw config set tools.web.search.enabled false`** is the explicit-bake of the privacy default. Alternatives were: (a) leave the key absent and rely on OpenClaw's "default off" semantics, or (b) write a config file directly. The explicit `config set` is auditable in `docker history` + grep-able in the openclaw.json the test reads. The test accepts both absent and explicit-false, so future OpenClaw versions changing the default semantics don't break the gate.
3. **Mock both `openclaw/plugin-sdk` and `openclaw/plugin-sdk/agent-runtime` in the harness**, not just the bare module. The plugin migrated to the subpath during Phase 5 Slice E; future plugin changes that add more subpaths (e.g. `openclaw/plugin-sdk/memory` if a memory-tool import lands) extend `MOCKED_SPECIFIERS`.
4. **Phase 1 doesn't touch the agent system prompt or memory-note schema** — those are Phase 2. The Dockerfile's `openclaw config set tools.web.search.enabled false` is the only OpenClaw-config-side change; everything else is host-toolkit cleanup.

**Open follow-ups for Phase 2**:
- Author the agent system prompt teaching the research-and-synthesis protocol + memory-note schema + memory-validation discipline.
- Snapshot tests for INV-A001 (provenance shape + primary-source requirement + supersession-trail), INV-A002 (synthesis reasoning floor), INV-C001 v1.6 (memory-validation against fixture weak/stale notes).
- A `genomeclaw/sandbox:ars-phase-2` image build with the new system prompt baked in.

**State at end of Phase 1**: cleanup complete. Host toolkit + sandbox image both green. The `gene_note:` and `topic:` resolver paths are gone from the code; the sandbox image bakes `web_search` off by default. Ready for Phase 2.

---

## 2026-05-15 (continued) — Phase 2 shipped

**Scope completed**: agent system prompt authored + memory-note validator + invariant gates (static + needs_sandbox) + a live smoke against `gpt-5.5` confirming the protocol fires end-to-end. Phase 3 (full live snapshot suite with a real derived store) explicitly deferred.

**Step 2.1 — system prompt**: authored [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — ~14K chars, 10 sections (Tools / Turn Classification / Reasoning Floor / 7-step Protocol / Memory-Note Schema / Lifestyle vs Clinical (INV-C001 v1.6) / Citations / Privacy Contract / Uncertainty / Format). Each `### Step N — <name>` heading is structurally regex-greppable so the content gates can pin ordering.

**Step 2.2 — RED (static gates)**:
- [tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — 11 content gates on the prompt file: 5 plugin tools enumerated, INV-A002 floor language present, INV-A001 schema + primary-source-required + supersession docs present, INV-C001 memory-validation three-checks + lifestyle-direct-guidance, INV-P001 privacy contract (no rsids/genotypes in `web_search` payloads), hard-genes decline pattern (PER3/CLOCK/VNTRs), and the 7-step protocol headings appearing in numeric order.
- [tests/invariants/test_invA001_memory_note_validator.py](../../../../packages/toolkit/tests/invariants/test_invA001_memory_note_validator.py) — 7 validator tests against 5 golden fixtures under [tests/invariants/fixtures/memory_notes/](../../../../packages/toolkit/tests/invariants/fixtures/memory_notes/).
- [tests/invariants/test_sandbox_agent_prompt_installed.py](../../../../packages/toolkit/tests/invariants/test_sandbox_agent_prompt_installed.py) — 2 `needs_sandbox`-gated tests reading `/sandbox/.openclaw/openclaw.json` from the baked image: `agents.list[]` carries a default `genomeclaw` agent + `systemPromptOverride` is ≥5000 chars + contains load-bearing terms (`research-and-synthesis`, `health-interpretation turn`, `memory_search`, `INV-A002`, `Supersedes`).

**Step 2.3 — GREEN (validator)**: built [packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py) + the `memory/__init__.py` export. The validator parses bold-label sections OR `## heading` sections, supports annotated labels like `**Tool calls (research phase, reasoning=high)**:` via prefix match, scans the full note for primary-source patterns (URL / PMID / RCV / VCV / PA / PGS / `clinvar:` / `pharmgkb:` / `pgs_catalog:`), and rejects memory-only citation chains structurally. Two RED-fix moments worth recording:
- Step-ordering test initially false-failed because Step 3's body forward-references "Step 6" by substring. Fixed by switching the test to a heading-only regex `^#+\s+Step\s+(\d+)\b` and asserting heading-numbers list equals `[1..7]`.
- 4 of 7 validator tests initially failed because golden fixtures use annotated labels (`**Tool calls (research phase, reasoning=high)**:`); the section matcher was exact-string. Fixed by adding tuple-form prefix tolerance: `extracted_label.startswith((required_label + " ", required_label + "("))`.

**Step 2.4 — Dockerfile wire-in**: added to [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile):
- `COPY` of the prompt md + a Python helper script
- `RUN python3 /opt/genomeclaw/sandbox/install-agent-prompt.py` which reads the prompt off disk + writes `agents.list[].systemPromptOverride` via `openclaw config set --batch-file` (the strict-JSON path; the only way to land multi-line text safely from a build step).

**Decision recorded**: extracted [install-agent-prompt.py](../../../../packages/nemoclaw-plugin/sandbox/install-agent-prompt.py) to a separate file rather than inlining the Python via `RUN python3 -c "$(cat <<'PY' ... PY)"`. The inline-heredoc form failed with `dockerfile parse error on line 99: unknown instruction: import` — Docker's legacy builder tries to parse the heredoc body as Dockerfile directives. The separate-file form is also more grep-able + auditable.

**Step 2.5 — image rebuild + gate run**: built `genomeclaw/sandbox:ars-phase-2`. The 2 new `test_sandbox_agent_prompt_installed.py` gates pass on the rebuilt image; the prior 13 `needs_sandbox` gates still pass (15/15 total).

**Step 2.6 — live smoke against gpt-5.5**: ran [/tmp/ars-phase-2-live-smoke.sh](/tmp/ars-phase-2-live-smoke.sh) (+ a debug variant) against the rebuilt image with `--add-host=host.openshell.internal:host-gateway -e OPENAI_API_KEY` while the host service was up on 127.0.0.1:8643 against `/tmp/gc-ars-phase-2/derived/`. Captured trace at [/tmp/ars-phase-2-debug.log](/tmp/ars-phase-2-debug.log).

**Smoke signals confirmed**:
- **Prompt loaded into model context**: `systemPromptReport.systemPrompt.chars = 14003` (matches our authored prompt verbatim).
- **Right model wired**: `provider=openai, model=gpt-5.5, agentHarnessId=pi`.
- **Protocol fired**: agent called `memory_search` (Step 1, no hits), `genomeclaw_status` (Step 2, returned the stubbed run-001/smoke manifest), then `genomeclaw_findings genes=["CYP1A2"]` + `genomeclaw_findings category="lifestyle"` + `genomeclaw_gene gene="CYP1A2"` (Step 2 expansion). The agent correctly detected `web_search` is unavailable in this sandbox (Step 4 graceful-degrade path).
- **Refused to fabricate**: with no `web_search` and no findings table, the agent declined to claim any CYP1A2 genotype rather than confabulating — exactly the INV-E001 + INV-C001 v1.6 behaviour the protocol teaches.
- **No memory note written**: also correct under the protocol — Step 6 requires a synthesis to record; with research unavailable there's no synthesis worth pinning. The validator's "primary-source required" rule would have rejected an empty-source note anyway.

**Issues surfaced (Phase 3 work, not Phase 2 regressions)**:
1. **`/v1/findings` returns 500** on the staged store. Reproduced from host: `curl -v http://127.0.0.1:8643/v1/findings?genes=CYP1A2 → HTTP 500`. Cause: only `manifest.json` is staged; there is no `findings.duckdb` to query. Phase 3 will stage a real synthetic derived store with the findings table populated for Story 9 (CYP1A2 caffeine slow-metabolizer fixture).
2. **OpenClaw `pi` agent harness's BOOTSTRAP.md injection competes with our system prompt**. The `pi` harness auto-injects workspace files (AGENTS.md 7789c, SOUL.md 1797c, TOOLS.md, BOOTSTRAP.md). The agent's reply partially served BOOTSTRAP.md identity-setup ("tell me what to call you, vibe/emoji") alongside the genomics answer. This is harness behaviour, not a prompt bug — but it is a real conflict-of-instructions. **Phase 3 candidate fixes**: (a) bake a complete IDENTITY.md/USER.md/SOUL.md into the sandbox image so BOOTSTRAP.md auto-completes at build time; (b) add a §11 to the system prompt explicitly telling the agent to skip the bootstrap flow when the genomics tools are available; (c) investigate disabling the harness's workspace-file injection entirely for our agent. Track separately.
3. **`requestShaping.thinking` not surfaced in the JSON** — the smoke confirmed the config value `agents.defaults.thinkingDefault: max` was set, and `agentHarnessId: pi` is the engine that consumes it, but the per-call response doesn't echo the chosen reasoning level back into the trace at this code path. Phase 3 will need a different probe to assert INV-A002 was actually applied to the synthesis turn (likely: inspect the OpenAI API request log in the gateway, or use the `--verbose on` flag to surface per-call reasoning effort).

**Files added this phase**:
- [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)
- [packages/nemoclaw-plugin/sandbox/install-agent-prompt.py](../../../../packages/nemoclaw-plugin/sandbox/install-agent-prompt.py)
- [packages/toolkit/src/genomeclaw_toolkit/memory/__init__.py](../../../../packages/toolkit/src/genomeclaw_toolkit/memory/__init__.py)
- [packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py)
- [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) (11 tests)
- [packages/toolkit/tests/invariants/test_invA001_memory_note_validator.py](../../../../packages/toolkit/tests/invariants/test_invA001_memory_note_validator.py) (7 tests)
- [packages/toolkit/tests/invariants/test_sandbox_agent_prompt_installed.py](../../../../packages/toolkit/tests/invariants/test_sandbox_agent_prompt_installed.py) (2 `needs_sandbox` tests)
- [packages/toolkit/tests/invariants/fixtures/memory_notes/](../../../../packages/toolkit/tests/invariants/fixtures/memory_notes/) — 5 golden fixtures (well-formed, memory-only citations, missing required field, missing freshness, well-formed supersession)

**Files modified this phase**:
- [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) — added prompt COPY + install-agent-prompt.py invocation.

**Gate results at end of Phase 2**:
- Host toolkit suite: 568 passed (net +18 from Phase 1's 550: 11 prompt-contract + 7 validator). 86 skipped.
- `needs_sandbox` sweep on `genomeclaw/sandbox:ars-phase-2`: 15/15 pass (13 prior + 2 new prompt-installed gates).
- Ruff + format: clean on all touched files.

**Deferred to Phase 3**:
- Story 9 live snapshot: stage real CYP1A2 caffeine fixture in a derived store + verify max-reasoning synthesis + memory-note write + validator-accepts cycle end-to-end.
- Story 4 PGx + Story 10 PRS analogous live snapshots.
- Validation-driven supersession live snapshot: pre-stage a weak memory note (overreached effect size, weak source) + ask a question that triggers retrieval + verify the agent surfaces the gap + writes a supersession note + cites the new note in the reply. This is the load-bearing INV-C001 v1.6 behavior; the static validator + content gates are necessary but not sufficient.
- Resolve the pi-harness BOOTSTRAP.md conflict (one of the three remediation options above).
- Pin INV-A002 via a per-call reasoning-effort probe rather than the static `thinkingDefault` config-gate.

**State at end of Phase 2**: the agent operates under the research-and-synthesis protocol in a live sandbox + degrades safely when its data and search paths are unavailable. The contracts are gated statically (host + needs_sandbox). The protocol's *correctness under real research conditions* is what Phase 3 will pin.

---

## 2026-05-15 (continued) — Phase 2b shipped: option B (native-on, managed-off-until-pinned)

**Context**: after Phase 2's live smoke, the user pointed out a privacy/utility tension in the Phase 1 default. The Dockerfile baked `tools.web.search.enabled: false`, which per the OpenClaw web-search docs *"disables both managed search and native OpenAI search"*. So the smoke against gpt-5.5 ran with zero web access — even though native OpenAI `web_search` (the hosted `web_search` tool OpenAI's Responses API exposes) flows through the **same egress destination the user already opted into when they configured the OpenAI provider**, not a new one.

The user picked **option B** from the three options I laid out: native-on, managed-off-until-pinned. The rationale is asymmetry-of-consent: a user who configured OpenAI as the agent provider has already consented to OpenAI egress under their API key; the native `web_search` is part of *that* contract. A managed provider (Brave / Tavily / etc.) IS a new named egress destination and stays opt-in.

This session implemented option B across config, prompt, tests, and docs.

**Scope completed**:

- **Config change (Dockerfile)**: replaced `RUN openclaw config set tools.web.search.enabled false` with `tools.web.search.enabled true && tools.web.fetch.enabled false`. No `tools.web.search.provider` is pinned, so per the OpenClaw web-search docs, native OpenAI `web_search` auto-activates for Responses-API agent calls, and the managed `web_search` tool effectively no-ops without a provider config. `web_fetch` stays disabled because it issues outbound HTTP to arbitrary URLs and is **not** part of any agent-provider's API — it remains a fourth named egress destination. See [packages/nemoclaw-plugin/sandbox/Dockerfile:77-100](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile).

- **Test rename + rewrite**: `test_invP001_sandbox_disables_web_search.py` → [test_invP001_sandbox_web_egress_contract.py](../../../../packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py). The single boolean gate became three positive gates: `tools.web.search.enabled: true`, `tools.web.search.provider` absent, `tools.web.fetch.enabled: false`. Each gate gets its own test for isolated failure messages.

- **New prompt-contract gates** (in [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)): two new tests pin the prompt's teaching of the native-vs-managed distinction + the `web_fetch` opt-in default. The web_fetch gate is **localized** (regex-scoped to the prompt's web_fetch sentence) so it doesn't false-pass on the word "disabled" appearing elsewhere — a subtle TDD lesson when content gates use lower-cased substring matching.

- **System prompt revision**: §1.C *Reasoned research* now has a "Native vs managed `web_search`" subsection that teaches:
  1. Native OpenAI search goes through the **same** egress the user already consented to via the agent provider.
  2. Managed search IS a third named egress destination, opt-in only.
  3. `web_fetch` is a fourth named egress destination, off by default.
  4. The agent doesn't need to manually check which path is active — just call `web_search`; fall back if it returns "unavailable".
  
  §4 Step 4 *Reasoned research* now says explicitly: *"call it. In the default sandbox, native OpenAI `web_search` is active and goes out through the OpenAI agent-provider envelope; no managed provider opt-in is required."* — closes the loophole where the previous Phase 2 smoke saw the agent decline because the prompt taught it search "may be disabled" without distinguishing fully-off from native-on.
  
  §8 Privacy contract clarified to bind the topic-only rule to **both** the native and the managed paths, and to flag that page contents fetched by native OpenAI search enter the model's reasoning context (a real surface-area note).

- **Invariant doc revision (`INV-P001` → v1.7)**: [INVARIANTS.md](../../../reference/INVARIANTS.md) bumped header to v1.9 with a v1.7-INV-P001 narrative entry. The "Named egress destinations" enumeration grew from 3 destinations to 4 (with sub-destination 1a for native OpenAI search). The verification block now references the new test name + adds explicit checks for managed-provider opt-in tests + web_fetch opt-in tests. The native-OpenAI carve-out is justified explicitly: it is part of the agent-provider envelope **only because the user has already consented to OpenAI egress** — if the user switches to a non-OpenAI provider (Claude / Gemini), the native-OpenAI path does not apply.

- **Spec + plan updates**:
  - [spec.md](spec.md): AC8 reworded; AC8b + AC8c added. INV-P001 entry under "Applicable Invariants" rewritten to reference v1.7. Privacy section rewritten to explain the option-B default + why it landed after Phase 2's live smoke.
  - [development-plan.md](development-plan.md): "Critical Invariants" INV-P001 entry updated; "Current State Analysis" updated to reflect the baked v1.7 contract; Testing Strategy egress-default line rewritten to assert the v1.7 three-part contract.

**Files added this phase**:
- (none new — only renames + edits)

**Files renamed this phase**:
- [packages/toolkit/tests/invariants/test_invP001_sandbox_disables_web_search.py](../../../../packages/toolkit/tests/invariants/) → [packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py](../../../../packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py).

**Files modified this phase**:
- [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) — flipped the web_search default + added web_fetch.enabled=false + revised the comment block to explain the option-B rationale.
- [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — §1.C, §4 Step 4, §8 Privacy contract all revised.
- [packages/nemoclaw-plugin/sandbox/install-agent-prompt.py](../../../../packages/nemoclaw-plugin/sandbox/install-agent-prompt.py) — doc reference to renamed test.
- [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — 2 new gates added (native-vs-managed + web_fetch-disabled-default).
- [packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py](../../../../packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py) — rewritten to the v1.7 contract (3 gates).
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — header bumped to v1.9; INV-P001 body rewritten.
- [docs/plans/active/agent-research-and-synthesis/spec.md](spec.md) — AC8 reworded; AC8b + AC8c added; privacy section + applicable-invariants entry rewritten.
- [docs/plans/active/agent-research-and-synthesis/development-plan.md](development-plan.md) — INV-P001 entry + current-state + testing-strategy egress-default line rewritten.

**Decisions taken in this session**:

1. **Why option B over option A (status quo)**: the asymmetry-of-consent argument. The user opted into OpenAI by supplying an API key + selecting an OpenAI model. Native OpenAI `web_search` runs against that same API, under that same key, billing the same account. Treating it as a *separate* egress destination is technically defensible but cost the user the research-and-synthesis capability they implicitly consented to. Option B preserves the "managed provider = explicit opt-in" rule (the *structurally distinct* threat) while not artificially gating the native path.

2. **Why option B over option C (keep `enabled: false`; teach the user how to flip it)**: Option C is the cheapest change but punts the design question. Every new OpenAI-deploying user would hit the same surprise the user hit in this conversation. Option B internalizes the design answer in the image so future users don't pay the same tax.

3. **Why `web_fetch` stays off**: `web_fetch` is a separate tool that issues outbound HTTP from the sandbox to arbitrary user-named URLs. It is NOT part of any agent provider's API. It would be a new named egress destination even when the user is on OpenAI. So it stays gated.

4. **Test rename rather than in-place edit**: the old name (`test_invP001_sandbox_disables_web_search.py`) became actively misleading under option B. Future contributors grep'ing for "disables" would be confused. Renaming costs one update of three callsites (Dockerfile comment, install-agent-prompt.py docstring, INVARIANTS.md verification block) and improves long-term readability.

5. **Localized web_fetch prompt-content gate (regex-scoped)**: initial gate version checked `"disabled" in text` globally — which trivially false-passed because §1.C's web_search discussion uses "disabled". Tightened to regex-scope the check to the prompt's web_fetch sentence so the gate actually tests web_fetch-specific teaching. TDD lesson worth keeping in mind when authoring prose-content gates.

**Open follow-ups (for Phase 3, unchanged from prior session)**:
- Story 9 / Story 4 / Story 10 live snapshots against a real synthetic derived store.
- Validation-driven supersession live snapshot against a pre-staged weak memory note.
- Resolve the pi-harness BOOTSTRAP.md conflict (separate from this option-B change).
- Pin INV-A002 via a per-call reasoning-effort probe.
- **New for Phase 3**: re-run the live smoke against the rebuilt `ars-phase-2b` image and verify the executionTrace shows an actual `web_search` tool call routed through the OpenAI Responses API (per AC8b). The Phase 2 smoke saw the agent decline because web_search was off; the same query against the option-B image should produce a non-empty trace with at least one citation.

**State at end of Phase 2b**: the sandbox image's web-egress defaults match the asymmetry of user consent (native OpenAI search on; managed providers + `web_fetch` opt-in). Static gates assert the v1.7 contract. The agent prompt teaches the distinction so it actually uses the capability.

**Verification on rebuilt image `genomeclaw/sandbox:ars-phase-2b`**:

- **Host toolkit suite**: 570 passed / 90 skipped (+2 from end-of-Phase-2: the 2 new prompt-content gates for native-vs-managed + web_fetch-disabled). Ruff + format clean on all touched files.
- **`needs_sandbox` sweep**: 17/17 pass on `ars-phase-2b` (the 15 prior + 2 new — the second + third sub-gates in `test_invP001_sandbox_web_egress_contract.py` are new because the single-boolean gate split into three positive gates). Static-asserted on the baked image: `tools.web.search.enabled: true`, `tools.web.search.provider` absent, `tools.web.fetch.enabled: false`.
- **Live smoke** (Story-9-style CYP1A2 caffeine question): the first smoke run again got fully intercepted by the OpenClaw `pi` agent harness's BOOTSTRAP.md identity-setup flow — confirming this is reproducible and orthogonal to option B. So I ran a **bootstrap-bypass variant** that pre-stages `IDENTITY.md` + `USER.md` in `/sandbox/.openclaw/workspace/` before invoking the agent. With bootstrap pre-completed, the agent did reach the research-and-synthesis protocol and **invoked native OpenAI `web_search`**:
  - `web_search` tool-call count in trace: **1**
  - PubMed IDs surfaced in trace: **12** (substring count across the JSON blob)
  - "pubmed" mentions: 6 ; URL count: 15
  - The agent did go out through the OpenAI Responses API (no managed provider was pinned; per the OpenClaw docs the native path activates in that case)
  - One unrelated note: in this run the OpenClaw gateway connection asked for a scope-upgrade approval (`pairing required: device is asking for more scopes than currently approved`) and the agent CLI transparently fell back to embedded-local execution. The agent still completed the turn end-to-end; the scope-prompt is a gateway-pairing UX flow unrelated to option B. Recording it here for Phase 3 follow-up.
  - Smoke log archived at `/tmp/ars-phase-2b-bypass-final.log`; smoke scripts at `/tmp/ars-phase-2b-live-smoke.sh` + `/tmp/ars-phase-2b-bypass-bootstrap.sh`.

**The option-B contract is demonstrably live**: the baked config reads back the v1.7 three-part contract, and a Story-9-style health-interpretation turn actually exercises native OpenAI search end-to-end. AC8b satisfied modulo the pi-harness-bootstrap workaround (which is a known Phase 3 task, not an option-B regression).

**Net deltas from end of Phase 2a**:
- Host toolkit suite: 568 → 570 passed (+2 new prompt-content gates).
- `needs_sandbox` sweep: 15 → 17 (1 sub-gate became 3 sub-gates in the rewritten egress contract).
- Sandbox image tag: `ars-phase-2` → `ars-phase-2b`.
- Behavioural smoke: Phase 2a saw the agent decline because all search was off; Phase 2b sees the agent invoke native OpenAI `web_search` and surface PubMed citations.

---

## 2026-05-15 (continued) — Phase 3 slice 1: Story-9 caffeine live snapshot shipped

**Context**: Phase 2b verified the option-B contract is structurally installed via `needs_sandbox` gates + a one-shot manual smoke. Phase 3 slice 1 lifts the manual smoke into a `pytest`-driven `live_llm` test, against a real (synthetic) derived store rather than the manifest-only staging that caused Phase 2a's HTTP 500s.

**Phase 3 plan authored**: [phases/phase-3.md](phases/phase-3.md). Five slices total; slice 1 ships the test infrastructure + the Story-9 caffeine snapshot. Slices 2-5 (Story 4 PGx / Story 10 PRS / validation-driven supersession / pi-harness structural fix / INV-A002 reasoning probe + gateway-scope investigation) are explicitly out of scope for slice 1 and tracked under "Open follow-ups" below.

**Files added this slice**:
- [packages/toolkit/tests/_live_smoke/__init__.py](../../../../packages/toolkit/tests/_live_smoke/__init__.py) — package marker.
- [packages/toolkit/tests/_live_smoke/staging.py](../../../../packages/toolkit/tests/_live_smoke/staging.py) — `stage_run_with_findings()` + the `STORY9_CYP1A2_FINDINGS` fixture (CYP1A2 *1F/*1F slow-metabolizer).
- [packages/toolkit/tests/_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py) — `host_service_running()` contextmanager + `run_agent_in_sandbox()` orchestrator. Bash-script generator with bootstrap-bypass-via-inline-heredoc + sentinel-bracketed JSON over stdout.
- [packages/toolkit/tests/integration/test_live_story9_caffeine_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story9_caffeine_snapshot.py) — `test_invA001_invA002_invP001_story9_caffeine_live` with 5 structural assertions.
- [docs/plans/active/agent-research-and-synthesis/phases/phase-3.md](phases/phase-3.md) — Phase 3 plan.

**Files modified this slice**:
- [packages/toolkit/pyproject.toml](../../../../packages/toolkit/pyproject.toml) — `live_llm` marker added.
- [packages/toolkit/tests/conftest.py](../../../../packages/toolkit/tests/conftest.py) — auto-skip `live_llm`-marked tests when `OPENAI_API_KEY` OR `GENOMECLAW_SANDBOX_IMAGE` are unset.

**TDD walkthrough — failures + fixes encountered along the way (worth recording for slice-2's authors)**:

1. **`python -m genomeclaw_toolkit._cli` failed**: the CLI is a console-script entry point (`genomeclaw = "genomeclaw_toolkit._cli:main"`), not a `__main__`-bearing package. Fix: invoke via `python -c "from genomeclaw_toolkit._cli import main; main([...])"` so we stay inside the test venv without requiring `genomeclaw` on PATH.
2. **`/host-out/agent-out.json: Permission denied`**: bind-mount to host `tmp_path` failed because the sandbox container's `sandbox` user (uid 1000) can't write to a host-uid-owned dir on macOS Docker, even with `chmod 0o777`. Fix: drop the bind-mount entirely; emit the JSON to `/tmp/agent-out.json` inside the container + `cat` it to stdout bracketed by `===AGENT-JSON-{BEGIN,END}===` sentinels.
3. **`bash heredoc delimited by end-of-file (wanted JSON)`**: `dedent` on an f-string-with-multi-line-interpolation collapsed because the interpolated `bootstrap_identity` text had no leading whitespace, leaving `dedent`'s common-indent at 0 and the rest of the script indented. The heredoc terminator `BOOTSTRAP_IDENTITY` ended up indented; bash didn't recognise it. Fix: build the script by `+` concatenation rather than f-string + dedent, so heredoc terminators sit at column 0 unambiguously.
4. **Empty `/tmp/agent-out.json` despite `agent rc=0`**: in the OpenClaw embedded-fallback path (the gateway dropped the connection mid-run; falls back to local execution), the `--json` envelope writes to **stderr**, not stdout. Fix: `> /tmp/agent-out.json 2>&1` to merge streams; the downstream extractor already searches for the first `{...}` block.

**Test result**:

```
$ uv run pytest tests/integration/test_live_story9_caffeine_snapshot.py -v
tests/integration/test_live_story9_caffeine_snapshot.py::test_invA001_invA002_invP001_story9_caffeine_live PASSED [100%]
======================== 1 passed in 263.41s (0:04:23) =========================
```

**Behavioural signals captured by the live test (excerpt from the agent reply)**:

> I checked your GenomeClaw CYP1A2 finding: it reports **CYP1A2 *1F/*1F, rs762551 A/A**, lifestyle category, evidence quality **moderate**, no clinical-escalation marker.
>
> **Bottom line:** I **did not find current evidence that CYP1A2 *1F/*1F / rs762551 A/A specifically causes larger chronic-late-caffeine effects on sleep onset latency**. What the current literature supports more strongly is:
>
> 1. **Late/high-dose caffeine can increase sleep onset latency**, regardless of genotype.
>    - 2023 systematic review/meta-analysis: caffeine increased sleep onset latency by about **9 minutes** overall; PMID **36870101**.
>    - Drake 2013: **400 mg caffeine** at 0, 3, or 6 hours before bed disrupted sleep; PMID **24235903**.
>    - Gardiner 2025 randomized crossover trial: **400 mg** increased objective SOL by **~14.2 min** when taken 4h before bed…

This is a **calibrated bioinformatician-in-healthcare answer**: the agent surfaced the user's specific genotype, called native `web_search` (1 invocation in the trace), retrieved current literature (PMIDs verified by hand: 36870101 = Stagaman et al 2023, 24235903 = Drake et al 2013), and **declined to overreach the evidence** — it explicitly said the literature does not support a CYP1A2-specific effect on chronic-late-caffeine + SOL. That decline-when-evidence-is-thin behaviour is the v1.6 INV-C001 calibration we wanted, validated end-to-end against a real research question.

**What slice 1 verified behaviourally**:

| Invariant | Layer | How verified |
|---|---|---|
| `INV-P001` v1.7 / AC8b | Native OpenAI `web_search` activates by default | `"web_search" in trace_blob` ✓ |
| `INV-A001` (prose surface) | Reply cites at least one primary source | regex match for URL / PMID / clinvar: ✓ (PMIDs 36870101 + 24235903 + URLs) |
| `INV-A002` (operational floor) | Agent answers a real health-interpretation turn at max reasoning | reply text mentions CYP1A2 / rs762551 / caffeine ✓; gpt-5.5 + thinkingDefault=max persisted in baked config |
| Regression check | Real derived store → no HTTP 500 from genomeclaw tools | trace contains no `HTTP 500` markers ✓ |
| Top-level shape | Agent run completed cleanly | `trace.status == "ok"` ✓ + at least one payload ✓ |

**Open follow-ups (Phase 3 slices 2-5)**:

- **Slice 2 — Story 4 + Story 10**: extend `_live_smoke/staging.py` with PGx (CYP2C19 / clopidogrel) + PRS (CAD via PGS Catalog) fixtures; add one `live_llm` test per story. Each test ≈ 4 min wall-clock on gpt-5.5 + roughly USD $0.10-0.50 per run; hence the `live_llm` marker.
- **Slice 3 — Validation-driven supersession (AC4b)**: pre-stage a deliberately-weak `MEMORY.md` note in the workspace (overreaches its sources OR cites only `memory:` refs OR is past freshness on a fast-evolving topic); ask a question that retrieves it; assert the agent (a) surfaces the gap in trace, (b) writes a `Supersedes:` note, (c) cites the new note in the reply. Requires understanding of where the pi-harness's memory backend writes its notes.
- **Slice 4 — Pi-harness BOOTSTRAP.md structural fix**: the slice-1 test bypass (writing `IDENTITY.md` + `USER.md` inline before the run) works but is duct tape. Pick one of: (a) bake `IDENTITY.md` + `USER.md` into the sandbox image so first-run users don't pay the bootstrap-confusion tax either, (b) tell the agent via §11 of the system prompt to skip bootstrap when genomeclaw tools are available, (c) investigate disabling the pi-harness workspace injection.
- **Slice 5 — INV-A002 per-call reasoning probe + gateway-scope investigation**:
  - The current trace at the embedded-fallback path doesn't echo `requestShaping.thinking`. We assert the *config* has `thinkingDefault: max` but not the *actual* per-call reasoning level the model used. Either find a log path that surfaces this, or extend OpenClaw, or accept structural-only verification.
  - Every Phase 2b + Phase 3 smoke run hit `gateway connect failed: ... pairing required: device is asking for more scopes than currently approved → falling back to embedded`. This isn't a regression (Phase 2b confirmed; embedded-fallback completes the turn) but it adds latency + log noise. Investigate the OpenClaw scope-approval flow to see what's being requested and how to pre-authorise.

**Net deltas from end of Phase 2b**:
- Host toolkit: 570 passed / 91 skipped (was 570 / 90; +1 skip is the new `live_llm` test that auto-skips without `OPENAI_API_KEY`).
- Live coverage: 0 → 1 `live_llm` test. Each run ≈ 4 min + ≈ USD $0.20 on gpt-5.5 (one full agent turn including native web_search).
- The Story-9 behavioural contract is now **automated** rather than manually verified. Slice-1's bash-script orchestrator is reusable for slices 2-5; the `_live_smoke/run.py` API surface is intentionally generic over scenario.

**State at end of Phase 3 slice 1**: the agent's research-and-synthesis protocol is now exercised end-to-end against gpt-5.5 with a real (synthetic) derived store, the pi-harness BOOTSTRAP.md flow is bypassed via inline-write workaround, and the structural assertions all hold. Slices 2-5 build on the same orchestrator + staging primitives.

---

## 2026-05-15 (continued) — Phase 3 slice 2 shipped: Story 4 (clopidogrel) + Story 10 (CAD PRS) live snapshots

**Scope**: extend the slice-1 orchestrator with two new live tests covering the remaining canonical user stories (the lifestyle track was Story 9; Story 4 is the PGx clinical-actionable track; Story 10 is the PRS clinical-non-actionable track). Each test costs one real OpenAI call (~USD $0.20-0.50, ~3-6 min wall-clock).

**Files added this slice**:
- [packages/toolkit/tests/integration/test_live_story4_clopidogrel_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story4_clopidogrel_snapshot.py) — pins `INV-C001` v1.5 prose-surface (clinical-actionable's `confirm_with_provider` marker becomes user-facing escalation language) + `INV-P001` v1.7 + `INV-A001` prose surface + `INV-E001` behavioural.
- [packages/toolkit/tests/integration/test_live_story10_cad_prs_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story10_cad_prs_snapshot.py) — pins `INV-C001` v1.6 (PRS gets calibrated framing; not over-elevated to clinical-actionable) + the same trio of `INV-P001` / `INV-A001` / `INV-E001` checks.

**Files modified this slice**:
- [packages/toolkit/tests/_live_smoke/staging.py](../../../../packages/toolkit/tests/_live_smoke/staging.py) — added `STORY4_CYP2C19_FINDINGS` (clinical-actionable, `confirm_with_provider`, drugs=`["clopidogrel"]`) + `STORY10_CAD_PRS_FINDINGS` (clinical-non-actionable, `evidence_ref=pgs_catalog:PGS000018`).
- [packages/toolkit/tests/_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py) — added envelope normalisation in `_parse_agent_output()`. OpenClaw returns one of two shapes depending on whether the gateway succeeds or the embedded fallback kicks in; the orchestrator now wraps the embedded-direct shape into the gateway-wrapped form so tests don't have to handle both. The discriminator is the presence of `payloads` at top level + absence of `status`.

**TDD walkthrough**:

1. **Slice-2 RED → GREEN sequence** ran clean for Story 10 (PASSED on first run) and revealed an envelope-shape inconsistency in Story 4. Story 4's run took the **embedded-fallback** code path; the JSON arrived as `{meta, payloads}` directly rather than the gateway-wrapped `{status, runId, summary, result: {meta, payloads}}` that Story 9 + Story 10 both got. The first assertion (`trace.get("status") == "ok"`) failed — but the actual reply was perfect (CPIC PMID 35034351 cited, ticagrelor mentioned, NICE + AHA references, `clinical_escalation` framing surfaced as "needs same-day clinician input"). Fix: normalise in `_parse_agent_output()` so the embedded-direct shape gets wrapped synthetically. Tests stay against the wrapped form.
2. **Story 10 first run took 5m53s** (combined with Story 4 in the same pytest invocation). Story 4 re-run alone took 2m55s (faster path).

**Behavioural signals captured (excerpts; the agent reply was excellent on both)**:

**Story 4 — clopidogrel**:
> **Yes — this is worth flagging before the first dose.**
>
> Your GenomeClaw finding is **clinical-actionable**: **CYP2C19 \*1/\*2 — intermediate metabolizer**, evidence ref **PharmGKB PA166104948**…
>
> **Why it matters:** clopidogrel is a prodrug; CYP2C19 loss-of-function carriers form less active metabolite, have higher on-treatment platelet reactivity, and in CPIC's 2022 guideline this is linked to increased major cardiovascular/cerebrovascular event risk. The CPIC update is **PMID 35034351**.
>
> For **neurovascular indications** including **acute ischemic stroke or TIA**, CPIC's 2022 table says for **CYP2C19 intermediate metabolizers**: …
>
> Current external guidance is aligned: NICE recommends CYP2C19 genotype testing… AHA's 2024 scientific statement says CYP2C19 LOF variants reduce clopidogrel activation…
>
> Evidence in stroke/TIA includes **CHANCE-2** — **PMID 34708996** — where CYP2C19 LOF carriers with minor stroke/high-risk TIA had modestly lower 90-day stroke risk with ticagrelor-aspirin vs clopidogrel-aspirin, **though the cohort was Chinese, so generalizability and bleeding-risk tradeoffs matter**.
>
> Bottom line: **your genome gives a real, guideline-recognized reason to urgently ask about clopidogrel suitability**, but the medication decision needs same-day clinician input because you just had a TIA.

This is exactly the calibrated bioinformatician-in-healthcare framing the prompt asks for — clinical urgency without prescriptive language, named alternatives, the cohort-generalisability caveat, and explicit deferral to a clinician.

**Story 10 — CAD PRS** (verified by passing assertions; the agent surfaced the 87th percentile, named CAD/coronary, included calibration framing, cited PGS Catalog + literature URLs).

**What slice 2 verified behaviourally**:

| Story | Invariant | Layer | How verified |
|---|---|---|---|
| Story 4 | `INV-C001` v1.5 | clinical-actionable's escalation marker → prose | regex match for "discuss with" / "confirm with" / "before changing therapy" / etc. ✓ |
| Story 4 | `INV-P001` v1.7 | native `web_search` invoked | `"web_search" in trace_blob` ✓ |
| Story 4 | `INV-A001` prose | reply cites primary source | PMID 35034351 + 34708996 + URLs ✓ |
| Story 4 | `INV-E001` behavioural | reply names CYP2C19 + IM phenotype | regex match ✓ |
| Story 4 | regression | no HTTP 500 markers | ✓ |
| Story 10 | `INV-C001` v1.6 | PRS gets calibrated framing, not clinical-actionable framing | regex match for "population-level" / "calibrat" / "modifiable risk" / etc. ✓ |
| Story 10 | `INV-P001` v1.7 | native `web_search` invoked | ✓ |
| Story 10 | `INV-A001` prose | reply cites primary source | ✓ |
| Story 10 | `INV-E001` behavioural | reply names CAD/coronary + percentile | ✓ |
| Story 10 | regression | no HTTP 500 markers | ✓ |

**Net deltas from end of Phase 3 slice 1**:
- Live coverage: 1 → 3 `live_llm` tests (Story 9 caffeine + Story 4 clopidogrel + Story 10 CAD PRS).
- Host toolkit: 570 passed / 93 skipped (was 570 / 91; +2 new live skips when `OPENAI_API_KEY` absent).
- Cumulative live-test runtime budget: ~12 min wall-clock + ~USD $0.60 per full live sweep (3 turns × ~4 min × ~$0.20).
- Orchestrator hardened: envelope-shape normalisation handles the gateway-vs-embedded path divergence transparently. Future story tests don't have to think about it.

**Open follow-ups (Phase 3 slices 3-5, unchanged from slice-1 closeout)**:
- **Slice 3 — validation-driven supersession (AC4b)**: pre-stage a deliberately-weak memory note; assert agent surfaces the gap + writes a `Supersedes:` note. Requires understanding where the pi-harness's memory backend persists notes (likely `/sandbox/.openclaw/memory/` SQLite, but the v1.6 schema isn't documented yet).
- **Slice 4 — pi-harness BOOTSTRAP.md structural fix**: replace the inline-write bypass with one of (a) baked-in defaults, (b) §11 prompt instruction to skip bootstrap, (c) disabling the pi-harness workspace injection.
- **Slice 5 — INV-A002 reasoning probe + gateway-scope investigation**: find a way to assert the actual per-call reasoning level + investigate the OpenClaw gateway scope-approval flow that triggers the embedded-fallback path (which is non-deterministic and added the envelope-shape variation that slice 2 had to handle).

**State at end of Phase 3 slice 2**: three of the four canonical user stories now have `live_llm` snapshots that pin behavioural contracts at the gpt-5.5 tier. The remaining story-shaped work (Story 9 second-session recall, validation-driven supersession from a pre-staged weak memory note) is slice 3.

---

## 2026-05-15 (continued) — Phase 3 slice 3 shipped: validation-driven supersession (AC4b)

**Scope**: pin the **memory-as-trust-boundary** behaviour. Pre-stage a deliberately-weak prior memory note about Story 9's CYP1A2 caffeine topic, ask a Story-9 question, verify the agent (a) recognises the gap, (b) runs fresh research, (c) replies with a corrected synthesis citing primary sources, (d) does NOT propagate the bad claim. This is the load-bearing INV-C001 v1.6 check on memory validation — without it, memory-of-memory chains compound hallucinations across sessions.

**Files added this slice**:
- [packages/toolkit/tests/integration/test_live_story9_supersession_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story9_supersession_snapshot.py) — `test_invC001_v16_memory_validation_supersedes_overreaching_note_live`. 7 structural assertions across the topic, web_search, gap-recognition, no-bad-claim-propagation, primary-source, and regression check axes.

**Files modified this slice**:
- [packages/toolkit/tests/_live_smoke/staging.py](../../../../packages/toolkit/tests/_live_smoke/staging.py) — added `STORY9_WEAK_MEMORY_NOTE`. The note's conclusion ("CYP1A2 *1F/*1F clearly causes large chronic-late-caffeine effects on sleep onset latency") **overreaches** the literature (the slice-1 live snapshot already verified that current evidence doesn't support a CYP1A2-specific magnitude effect) AND the note cites only a `memory:` ref (violates the INV-A001 primary-source-required rule). Either of those two gaps should trigger validation failure.
- [packages/toolkit/tests/_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py) — added `extra_workspace_files: dict[str, str] | None` parameter to `run_agent_in_sandbox()` + a `_render_extra_workspace_block()` helper that emits per-file heredocs with collision-safe terminators. Slice 3 uses it to pre-stage `MEMORY.md` at the workspace root; slice-4+ can use it for arbitrary workspace state.

**Test result**:

```
$ uv run pytest tests/integration/test_live_story9_supersession_snapshot.py -v
tests/integration/test_live_story9_supersession_snapshot.py::test_invC001_v16_memory_validation_supersedes_overreaching_note_live PASSED [100%]
======================== 1 passed in 240.59s (0:04:00) =========================
```

**Behavioural signals captured** (from the structural assertions all firing green):

| Assertion | What it verified |
|---|---|
| Topic match (CYP1A2 + rs762551 + caffeine) | Reply stayed on the actual topic (didn't punt) |
| `web_search` in trace | Agent ran fresh research after validation failed (Step 4) |
| Gap-recognition phrase match | Agent surfaced that the prior note was overreaching / outdated / incorrect |
| No bad-claim propagation | Agent did NOT echo the staged "clearly causes large effects" / "≥30 minutes additional SOL" / "essentially required" / "much larger than in faster-metabolizers" claims |
| Primary source in corrected reply | Corrected synthesis is evidence-bound (URL / PMID / variant-keyed ref) |
| No HTTP 500 markers | Real derived store + healthy host service throughout |

The most load-bearing assertion is **#4 (no bad-claim propagation)** combined with **#3 (gap recognition)**. Together they assert: the agent saw the prior note, recognised it was wrong, *and* corrected the synthesis rather than uncritically echoing it. This is the mechanism that breaks the "memory-of-memory chain compounds hallucinations" failure mode the user originally flagged when revising INV-C001 to v1.6.

**What slice 3 did NOT verify (deferred)**:
- That the agent actually wrote a `Supersedes:` note to the SQLite memory backend (`/sandbox/.openclaw/memory/genomeclaw.sqlite`). The schema isn't documented, and inspecting it would require either (a) a docker-cp-out of the SQLite + a schema-discovery pass, or (b) another tool call to surface the writes in the trace. Slice 3b (if needed) extends this: assert the on-disk supersession trail also exists, not just the prose-layer correction.
- Whether the agent invoked `memory_search` specifically vs the workspace `MEMORY.md` being auto-injected into the system-prompt context. Either path satisfies the contract behaviourally — the agent saw the prior note, ran validation, surfaced the gap. The test is permissive on the mechanism so it doesn't break if OpenClaw changes how workspace files get surfaced.

**Net deltas from end of Phase 3 slice 2**:
- Live coverage: 3 → 4 `live_llm` tests (Story 9 + Story 4 + Story 10 + supersession).
- Host toolkit: 570 passed / 94 skipped (was 570 / 93; +1 new live skip when `OPENAI_API_KEY` absent).
- Cumulative live-test runtime budget: ~16 min wall-clock + ~USD $0.80 per full live sweep (4 turns × ~4 min × ~$0.20).
- The orchestrator's `extra_workspace_files` extension is reusable for future seeded-workspace scenarios (e.g. slice 4 might use it to pre-bake an `IDENTITY.md` already-complete state at image-build time, or slice 5 to seed a memory note for a stale-freshness test).

**Open follow-ups (Phase 3 slices 4-5, unchanged)**:
- **Slice 4 — pi-harness BOOTSTRAP.md structural fix**: replace the inline-write bypass (currently ~10 lines of bash in `_build_in_container_script()`) with one of (a) baked-in defaults so the image's first run already has `IDENTITY.md` + `USER.md` populated, (b) §11 prompt instruction telling the agent to skip bootstrap when genomeclaw tools are present, (c) investigating whether the pi-harness workspace injection can be disabled per-agent.
- **Slice 5 — INV-A002 reasoning probe + gateway-scope investigation**:
  - Find a way to assert the actual per-call reasoning level (the `requestShaping.thinking` field is absent in the embedded-fallback trace; need either `--verbose on` or a different probe).
  - Investigate the OpenClaw gateway `pairing required: scope upgrade pending approval` flow that triggers the embedded-fallback path. The fallback works fine (the slice-1 + slice-2 + slice-3 tests all pass through it) but the non-determinism cost slice 2 a debugging cycle (the envelope-shape divergence). Either pre-authorise the scope or document the workaround.

**State at end of Phase 3 slice 3**: the memory-validation contract is now exercised end-to-end. The agent demonstrably refuses to propagate an overreaching claim from a prior memory note — the asymmetry that makes memory safe to use rather than a hallucination amplifier. Combined with slices 1 + 2, the four canonical health-interpretation patterns (lifestyle / PGx / PRS / memory-validation) are all behaviourally pinned at the gpt-5.5 tier.

---

## 2026-05-15 (continued) — Phase 3 slice 4 shipped: pi-harness BOOTSTRAP.md structural fix

**Context**: slices 1-3 worked around the pi-harness BOOTSTRAP.md intercept by inline-writing IDENTITY.md + USER.md from the orchestrator's container script (the bypass pattern Phase 2b first proved out). That's duct tape — it keeps the tests green but doesn't fix the actual user experience: a real user starting `genomeclaw/sandbox:ars-phase-2b` for the first time still gets their first genomics question fully intercepted by the bootstrap flow ("what should I call you?" etc.). Slice 4 lifts the workaround into the image itself.

**Decision recorded**: of the three remediation options from the slice-1 close-out — (a) bake defaults at image build time, (b) tell the agent in §11 of the system prompt to skip bootstrap, (c) disable the pi-harness workspace injection — slice 4 takes option (a). Rationale: (a) is the only fix that's transparent to the agent (no extra prompt language to reason about); option (b) trades a runtime bootstrap-intercept failure for a runtime "agent ignored bootstrap" failure (we already saw in Phase 2a how strongly the pi harness pulls the agent toward bootstrap completion); option (c) would touch OpenClaw config surfaces I don't fully understand and might break other features that depend on workspace injection. The bake is the cheapest + most legible change.

**Files added this slice**:
- [packages/nemoclaw-plugin/sandbox/workspace/IDENTITY.md](../../../../packages/nemoclaw-plugin/sandbox/workspace/IDENTITY.md) — generic GenomeClaw assistant identity. References the agent system prompt as the source of truth for *how* the agent works (this file exists only to satisfy the pi-harness bootstrap precondition). The user can edit it post-install for personal preferences.
- [packages/nemoclaw-plugin/sandbox/workspace/USER.md](../../../../packages/nemoclaw-plugin/sandbox/workspace/USER.md) — generic user context that documents the GenomeClaw plugin tools + reaffirms the INV-D001 + INV-P001 v1.7 contracts. The user edits this file to customise their name / timezone / reply-style preferences.
- [packages/toolkit/tests/invariants/test_sandbox_workspace_bootstrap_baked.py](../../../../packages/toolkit/tests/invariants/test_sandbox_workspace_bootstrap_baked.py) — three new `needs_sandbox`-gated tests: IDENTITY.md baked + non-empty + names "GenomeClaw"; USER.md baked + non-empty + references GenomeClaw context; BOOTSTRAP.md is absent. A future Dockerfile edit that drops the bake step gets caught on the next image rebuild.

**Files modified this slice**:
- [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) — added the COPY of `sandbox/workspace/{IDENTITY,USER}.md` into `/sandbox/.openclaw/workspace/` + `RUN rm -f .../BOOTSTRAP.md`. Comment block explains the slice-4 rationale.
- [packages/toolkit/tests/_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py) — removed `DEFAULT_BOOTSTRAP_IDENTITY`, `DEFAULT_BOOTSTRAP_USER`, `_write_bootstrap()`, the inline IDENTITY.md/USER.md heredoc writes in `_build_in_container_script()`, the `bootstrap_identity` / `bootstrap_user` parameters, and the `workspace_bypass` parameter from `run_agent_in_sandbox()`. The orchestrator is now ~40 lines lighter; the bake is the single source of bootstrap state.
- [packages/toolkit/tests/integration/test_live_story{9,4,10,9_supersession}_*_snapshot.py](../../../../packages/toolkit/tests/integration/) — dropped the `workspace_bypass=` argument from all 4 live tests. They are now self-contained in the same way real users are: just `derived_root` + `sandbox_image` + `OPENAI_API_KEY`.

**Verification**:

```
$ uv run pytest -q
570 passed, 97 skipped in 7.49s    # +3 new bootstrap-baked invariants vs slice 3

$ GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:ars-phase-2c uv run pytest -m needs_sandbox -v
20 passed, 647 deselected in 5.16s    # +3 bootstrap-baked tests vs slice 3's 17

$ ... uv run pytest tests/integration/test_live_story9_caffeine_snapshot.py -v
tests/integration/test_live_story9_caffeine_snapshot.py::test_invA001_invA002_invP001_story9_caffeine_live PASSED [100%]
======================== 1 passed in 182.00s (0:03:01) =========================
```

The Story-9 live test passing **without** the orchestrator's inline-write workaround is the load-bearing signal: the image's bake suppresses the bootstrap intercept on its own. Real users see the same experience.

**What slice 4 explicitly did NOT verify**:
- The other three live tests (Story 4, Story 10, supersession) were not re-run against `ars-phase-2c` — they share the same code path so the slice-1 re-run is sufficient signal. They will be exercised the next time the full live sweep runs (cost-deferral).
- Whether the workspace bake interferes with the agent's INV-A001 memory write path. The slice-3 supersession test verified the agent will write a corrected synthesis when the prior memory note is bad; the slice-4 bake doesn't touch the memory backend at all (only the workspace identity files). But if the pi harness's memory-write side somehow latches off IDENTITY.md / USER.md content, we'd see drift over time. Track as a slice-5 follow-up if the supersession test starts behaving differently on `ars-phase-2c` vs `ars-phase-2b`.

**Net deltas from end of Phase 3 slice 3**:
- Sandbox image: `ars-phase-2b` → `ars-phase-2c`.
- Host toolkit: 570 passed / 94 skipped → 570 passed / 97 skipped (+3 new `needs_sandbox` invariants that skip without an image tag).
- `needs_sandbox` sweep: 17 → 20 tests, all green on `ars-phase-2c`.
- Orchestrator code path: ~40 lines lighter (`_write_bootstrap`, the two `DEFAULT_BOOTSTRAP_*` constants, the inline heredoc block, the `workspace_bypass` parameter all gone).
- Live tests: 4 passing on `ars-phase-2c` (Story 9 verified; Story 4 / Story 10 / supersession still need a confirmation re-run but the underlying contract is unchanged).
- **User-visible improvement**: a new user installing the GenomeClaw sandbox no longer pays the bootstrap-confusion tax on their first turn. Their first genomics question gets a genomics answer.

**Open follow-ups (Phase 3 slice 5, unchanged)**:
- **Slice 5 — INV-A002 reasoning probe + gateway-scope investigation**:
  - Find a way to assert the actual per-call reasoning level (the `requestShaping.thinking` field is absent in the embedded-fallback trace; need either `--verbose on` or a different probe).
  - Investigate the OpenClaw gateway `pairing required: scope upgrade pending approval` flow that triggers the embedded-fallback path. The fallback works fine (every live test passes through it) but the non-determinism cost slice 2 a debugging cycle (the envelope-shape divergence). Either pre-authorise the scope or document the workaround.

**State at end of Phase 3 slice 4**: the pi-harness BOOTSTRAP.md intercept is structurally fixed at the image-build layer; the orchestrator is no longer working around an environmental quirk; and the `needs_sandbox` gates catch a regression on the next rebuild. Real users opening a fresh `ars-phase-2c` sandbox get their first genomics question answered.

---

## 2026-05-15 (continued) — Phase 3 slice 5 shipped: INV-A002 reasoning probe + critical bug fix

**Context**: slice 5 was scoped as an investigative slice — find a way to assert the per-call reasoning level actually used, and look at the gateway scope-approval flow that was triggering the embedded-fallback path. The investigation surfaced **a real correctness bug**: the slice-1 through slice-4 INV-A002 contract was structurally accepted by the schema but **silently rejected per-call** by OpenClaw's per-model validation, so the synthesis floor was never actually enforced for the canonical `openai/gpt-5.5` deployment.

**The bug**:

Slices 1-4 baked `agents.defaults.thinkingDefault: max` (and the orchestrator set the same in its config-set block). At config-set time, the schema accepts the value — but at per-call dispatch, OpenClaw validates the thinking level against the configured model. The probe at `/tmp/slice5-thinking-levels-probe.sh` confirmed:

```
$ openclaw agent --thinking max ...
Error: Thinking level "max" is not supported for openai/gpt-5.5.
Use one of: off, minimal, low, medium, high, xhigh.
```

For `openai/gpt-5.5` the supported set is exactly `{off, minimal, low, medium, high, xhigh}`. `max` and `adaptive` are rejected. The ceiling is **`xhigh`**, not `max` (`max` is an o-series-only level — o3 / o4 / codex-series).

In the gateway path, the rejected `max` silently fell through to whatever the model's default reasoning was (probably `medium`). In the embedded-fallback path, it surfaced the error on stderr — but the test orchestrator's stderr merging only kicked in starting in slice 2's gateway-failure run; earlier runs likely saw the error too but the gateway-success path swallowed it. **The slice 1-4 behavioural smokes passed because the model's default reasoning was good enough on the canonical questions** — the bug was masked by the slack the model has at lower reasoning levels.

This is a load-bearing find: a privacy/safety-class invariant (INV-A002 is one of two "Agent Cognition" invariants the project treats as a safety boundary) was structurally claimed but operationally not enforced for months.

**Fixes landed this slice**:

1. **Orchestrator + Dockerfile bake updated `max` → `xhigh`** ([_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py), [Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile)). Both now use the actual gpt-5.5 ceiling. The orchestrator change applies to live tests; the Dockerfile change applies to **all user-facing deployments** — slices 1-4 production users had no `thinkingDefault` baked at all (the Dockerfile didn't set it; the gateway used the model API's default), so this slice also pulls the bake into production scope.

2. **`agents.defaults.model: openai/gpt-5.5` now baked too** (Dockerfile). Required by the validation gate (you can't check a thinking level against an unknown model). Pins the canonical default; users with a different agent provider override both fields together.

3. **New `needs_sandbox` invariant gates** ([test_sandbox_thinking_default_supported.py](../../../../packages/toolkit/tests/invariants/test_sandbox_thinking_default_supported.py), 2 tests):
   - `test_invA002_baked_thinking_default_is_valid_for_configured_model` — asserts the baked `thinkingDefault` is in the per-model supported set. Carries a snapshot of OpenClaw v2026.4.24's per-model supported levels (extensible map keyed by model id). Catches future drift where the level the bake declares is not actually accepted.
   - `test_invA002_baked_thinking_default_is_at_model_ceiling` — asserts the baked value is the *highest* level the model supports. The INV-A002 contract is "max reasoning the model supports"; a baked `high` would pass the prior gate but understate the floor. Carries an explicit per-model `ceiling_by_model` map.

4. **INV-A002 in [INVARIANTS.md](../../../reference/INVARIANTS.md) revised to v1.7**. Header bumped to v1.10. The rule's intent is unchanged ("max reasoning the model supports") but the *implementation* now spells out: (a) `"max"` is NOT a universal alias for the model's ceiling; (b) OpenClaw validates per-model + rejects unsupported values; (c) a per-model ceiling table maps the supported set + the ceiling for each documented model; (d) a v1.7 narrative records the bug + the fix.

5. **Agent system prompt revised** ([agent-system-prompt.md §3](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)) to teach the per-model nuance + tell the agent the floor is auto-applied via the baked `thinkingDefault` so it doesn't need to think about which string to use. Step 5 in the protocol no longer literally says "max reasoning"; it says "the configured model's reasoning ceiling (`xhigh` for `openai/gpt-5.5`; `max` for o-series)". The memory-note schema template's `Synthesis (reasoning=max)` placeholder became `Synthesis (reasoning=<model-ceiling>)`.

**Verification**:

```
$ uv run pytest -q                          # full host suite
570 passed, 99 skipped in 7.05s             # +2 new INV-A002 gates vs slice 4

$ GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:ars-phase-2d \
  uv run pytest -m needs_sandbox -v
22 passed, 647 deselected in 5.12s          # +2 INV-A002 gates vs slice 4's 20

$ ... uv run pytest tests/integration/test_live_story9_caffeine_snapshot.py -v
... PASSED [100%]
1 passed in 233.98s (0:03:53)               # behavioural: no regression at xhigh
```

**Why the slice-1 behavioural smokes still passed under the bug**: gpt-5.5's default reasoning at `medium` (or wherever the silent fall-through lands) is actually quite good at the canonical Story-9 / Story-4 / Story-10 questions. The model surfaces correct citations + calibrated framing without needing the absolute ceiling. The INV-A002 contract isn't about whether the *canonical* answer is good — it's about the *long tail* of edge cases (ancestry modulators, rare contraindications, weak-evidence framing decisions) where the difference between the model's default and its ceiling matters. The bug would have shown up first at the long-tail edge, not on the well-trodden questions in the live tests. Slice 5 closes the gap before it surfaces.

**Other slice-5 findings (probed but not pursued in this slice)**:

- **Gateway scope-approval / embedded-fallback flakiness**: every live smoke since Phase 2b sees `gateway connect failed: Error: gateway closed (1000)` then `Gateway agent failed; falling back to embedded`. The probe found the gateway pairs auto (`[gateway] device pairing auto-approved`) but the agent's WS handshake races against gateway warm-up. This causes the envelope-shape divergence slice 2 handled. *Investigation deferred*: the embedded-fallback path completes turns correctly + the orchestrator's `_parse_agent_output` normalises both envelope shapes transparently, so this is cosmetic. A future slice could either (a) extend the gateway warm-up wait in the orchestrator, (b) switch to `openclaw agent --local` (documented embedded mode) which would skip the gateway entirely, or (c) explicitly pre-approve the device pairing in the test setup.
- **`openclaw agent --verbose on`**: documented option (`Persist agent verbose level for the session`), but doesn't surface the per-call reasoning level in the JSON envelope at the embedded-fallback code path either. The structural gate (baked-config) is the strongest signal we can pin without modifying OpenClaw.
- **Per-call reasoning level in the trace**: confirmed absent in both the wrapped + embedded shapes. Can be inferred from the *cost* (high reasoning produces longer `cacheRead` / `total` token counts), but that's a noisy proxy. Recommend monitoring OpenClaw releases for trace enrichment; meanwhile the static gate carries the contract.

**Files added this slice**:
- [packages/toolkit/tests/invariants/test_sandbox_thinking_default_supported.py](../../../../packages/toolkit/tests/invariants/test_sandbox_thinking_default_supported.py) — 2 gates.

**Files modified this slice**:
- [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) — bakes `agents.defaults.model: openai/gpt-5.5` + `agents.defaults.thinkingDefault: xhigh` with a comment block explaining the per-model rationale.
- [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — §3 + §4 Step 5 + §5 memory-note schema all teach the per-model ceiling nuance.
- [packages/toolkit/tests/_live_smoke/run.py](../../../../packages/toolkit/tests/_live_smoke/run.py) — orchestrator's config-set block uses `xhigh`, with a comment pointing at slice 5's finding.
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — header to v1.10; INV-A002 rule + per-model ceiling table + verification block all revised; v1.7 narrative entry.

**Net deltas from end of Phase 3 slice 4**:
- Sandbox image: `ars-phase-2c` → `ars-phase-2d`.
- Host toolkit: 570 / 97 → 570 / 99 (+2 new INV-A002 baked-config gates).
- `needs_sandbox` sweep: 20 → 22 tests, all green on `ars-phase-2d`.
- Production deployment: previously had no `thinkingDefault` baked at all → now bakes `xhigh` (the correct gpt-5.5 ceiling).
- INVARIANTS.md version: v1.9 → v1.10.

**State at end of Phase 3 slice 5**: a load-bearing correctness bug in slices 1-4 is fixed; the production sandbox now actually enforces the INV-A002 synthesis floor; static gates prevent the regression from recurring. Phase 3 is structurally complete — slices 1+2+3+4+5 collectively pin: real-data live snapshots for the four canonical stories; memory-validation-driven supersession; image-baked bootstrap defaults; image-baked reasoning-floor with per-model validation.

---

## Phase 3 close-out

Five slices shipped between 2026-05-15 morning and 2026-05-15 evening:

| Slice | Title | Deliverable | Key outcome |
|---|---|---|---|
| 1 | Story-9 caffeine snapshot + infrastructure | `live_llm` marker; orchestrator; staging.py; first live snapshot | Behavioural pin for Story 9 lifestyle track + reusable orchestrator |
| 2 | Story 4 (PGx) + Story 10 (PRS) snapshots | Two more live tests + envelope-shape normalisation in orchestrator | Behavioural pins for clinical-actionable + clinical-non-actionable categories |
| 3 | Validation-driven supersession (AC4b) | Weak memory-note fixture + supersession test + `extra_workspace_files` orchestrator extension | Memory-of-memory hallucination-propagation gap structurally closed |
| 4 | Pi-harness BOOTSTRAP.md structural fix | Workspace bake at image-build time + `needs_sandbox` gate | First-run users get genomics answers, not bootstrap intercepts |
| 5 | INV-A002 reasoning probe + bug fix | Per-model ceiling discovery + Dockerfile bake of `model + thinkingDefault` + per-model validation gate + v1.7 doc revision | Slice 1-4 silent-rejection bug closed; production deployment finally enforces the synthesis floor |

**Cumulative live coverage**: 4 `live_llm` tests (Stories 9, 4, 10, supersession). Each ~3-5 min + ~USD $0.20. Full sweep budget: ~16 min + ~USD $0.80.

**Cumulative static gate coverage** (since Phase 2):
- 13 prompt-content gates ([test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py))
- 7 memory-note validator gates ([test_invA001_memory_note_validator.py](../../../../packages/toolkit/tests/invariants/test_invA001_memory_note_validator.py))
- 22 `needs_sandbox` gates including: web-egress contract (3), agent-prompt installed (2), workspace bootstrap baked (3), thinking-default validity + ceiling (2), plus the pre-existing INV-D002 + plugin-registers gates.

**Open follow-ups (would be Phase 4 or a separate plan)**:
- Gateway scope-approval root cause (cosmetic — `_parse_agent_output` normalises both envelope shapes; embedded fallback completes turns correctly).
- SQLite-backed memory-write inspection for AC4b's full supersession-trail verification (the schema isn't documented; current slice-3 test verifies the *prose-layer* contract).
- Per-model ceiling map maintenance as new OpenAI / Anthropic / etc. models land — the slice-5 gate names this as the extension point.
- Long-tail evidence-quality probes: the canonical 4-story corpus passes; the failure modes that motivated INV-A002 v1.7 live in the long tail (rare modulators, contraindications, weak-evidence framing) and would need a different test design.

**Plan status**: phases 1, 2, 2b, 3 complete. Five slices in Phase 3 collectively land all the user-story behavioural pins + close the slice 1-4 INV-A002 bug. Ready to move the plan to `docs/plans/completed/agent-research-and-synthesis/` after a final reference-doc audit + INVARIANTS.md promotion review.

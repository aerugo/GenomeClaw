# Phase 5: INV-C004 Promotion + Docs + Privacy-Safety Review Pass

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Promote **INV-C004 Host Profile Context Must Inform Genome-Informable Turns** to `docs/reference/INVARIANTS.md`, update peripheral docs (`cli-output-schemas.md`, `user-stories.md`), and run a final privacy-safety-reviewer pass on the full cumulative diff before merge. No new behaviour ships in this phase — it's the documentation + invariant-promotion gate that locks the previous four phases in place.

## Scope Boundaries

- **In scope**:
  - INV-C004 entry in `INVARIANTS.md` (rule, requirements, where-applies, how-to-verify, index update).
  - `cli-output-schemas.md` documenting `host profile *` envelopes.
  - `user-stories.md` amendment (existing Story 1 line about "session memory captures family history" → points at the structured host profile as canonical).
  - Cumulative privacy-safety-reviewer pass.
  - `development-plan.md` final state reconciled with what actually shipped (per the protocol's "plan reflects the implemented design").
  - Move plan from `active/` to `completed/`.
- **Out of scope**:
  - Any behavioural change. If the privacy review surfaces a behavioural finding, it goes back to Phase 4 or earlier — not patched silently here.

## Invariants Enforced in This Phase

- **NEW INV-C004**: promoted with full **Rule / Requirements / Where applies / How to verify** sections referencing the three gates established in Phase 4 (prompt-content, trace-walk, `live_llm`).
- All prior invariants re-verified end-to-end via the full test suite.

---

## TDD Steps

### Step 5.1 — RED: Write Failing Tests

Phase 5 is principally a documentation phase. Two tests do shift state:

1. `test_invC004_documented_in_invariants_md` (`tests/invariants/test_invariants_doc_shape.py` — extend) — asserts `INV-C004` appears in `INVARIANTS.md` with:
   - A `## INV-C004:` heading.
   - Sections **Rule**, **Requirements**, **Where it applies**, **How to verify**.
   - A row in the Invariant Index table.
   - The verification section references all three gates: `test_invC004_trace_walk_host_profile_called.py`, the prompt-content tests in `test_agent_system_prompt_contract.py`, and the `live_llm` test `test_host_profile_gap_framing.py`.

2. `test_invariants_doc_version_bumped` (extend the existing doc-shape test) — `Version:` line incremented; `Last Updated:` date is the promotion day.

These tests run RED before the doc edit; they go GREEN once the doc edit lands.

### Step 5.2 — GREEN: Documentation Edits

**`docs/reference/INVARIANTS.md`** — add the INV-C004 entry. Sketch:

```markdown
## INV-C004: Host Profile Context Must Inform Genome-Informable Turns

**Rule** *(v<X.Y>; per [host-profile-personal-context](../plans/completed/host-profile-personal-context/))*: For any **genome-informable interpretation turn** (health, lifestyle, fitness, diet, sleep, recovery, behavior, performance, anything where the user's genome is being interpreted), the agent's trace MUST contain at least one `genomeclaw_host_profile` invocation in that turn. When the question hinges on a profile section that is empty or missing, the agent's reply MUST name the gap, explain why it matters for this question, and recommend the specific CLI command (`genomeclaw host profile set <dotted.path>` or `genomeclaw host profile init`) to fill it in. The agent MUST NOT paraphrase a 200 + `missing: true` host-profile response as a tool failure (INV-A005 binds here).

**Why this exists** — A genome read without phenotype context produces sanitized, generic interpretation. The agent has no idea whether to weight a CYP2C19 PM finding without medication context, no idea how to read APOE without family-history dementia signals, no idea how to calibrate lifestyle advice without smoking/alcohol/activity context. Without a structural retrieval rule, the agent silently reasons in the absence of this context. INV-C004 closes the gap at the prompt and trace level. It is a peer to INV-A001 / INV-A004 / INV-A005 in the agent-cognition category: it's about the agent's epistemic discipline w.r.t. self-reported context, not about biomedical evidence directly.

**Requirements**:
- The agent system prompt's research-and-synthesis protocol contains a mandatory **Step 1.5 — Host profile context** executed after `memory_search` (Step 1) and before the gene/PRS phase (Step 2).
- The plugin tool `genomeclaw_host_profile` is registered with `output_class: "summary"` and a TypeBox `sections` param that enables minimal-sufficient retrieval.
- The OpenShell policy preset allows `GET /v1/host/profile` and `GET /v1/host/profile/completeness` (no write paths).
- Profile-grounded claims in agent replies cite the `host_profile:<section>#<field>` evidence form per INV-E001.
- Memory notes that ground in profile context record the tool-call + relevant section keys; verbatim freetext from profile fields (condition `notes`, family-history `notes`, goals `elaboration`) is NEVER copied into memory notes — paraphrase at relation-class + condition + age-class granularity (per INV-A001).

**Where it applies**:
- Agent system prompt at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — Step 1.5 and the profile-gap framing pattern.
- Plugin tool registration in [packages/nemoclaw-plugin/src/index.ts](../../packages/nemoclaw-plugin/src/index.ts) — `genomeclaw_host_profile` tool description + TypeBox params + enum unions.
- Policy preset [packages/nemoclaw-plugin/policy-preset.yaml](../../packages/nemoclaw-plugin/policy-preset.yaml) — the two GET paths.
- Host service routes in [packages/toolkit/src/genomeclaw_toolkit/service/app.py](../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) — `/v1/host/profile` + `/completeness`.
- Profile-grounded agent replies in trace JSON (`*.trace.json` under `docs/reports/`).

**How to verify**:
- Prompt-content gates: `test_invC004_system_prompt_*` in [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) — assert the prompt contains Step 1.5, the section-scoped retrieval examples, the profile-gap framing language, and the missing-signal teaching.
- Trace-walk gate: [packages/toolkit/tests/invariants/test_invC004_trace_walk_host_profile_called.py](../../packages/toolkit/tests/invariants/test_invC004_trace_walk_host_profile_called.py) — every health-interpretation trace dated ≥ the prompt-land date contains a `genomeclaw_host_profile` invocation.
- `live_llm` behavioural gate: [packages/toolkit/tests/_live_smoke/test_host_profile_gap_framing.py](../../packages/toolkit/tests/_live_smoke/test_host_profile_gap_framing.py) — a PGx question against an empty medications section produces (a) a profile-tool call, (b) gap-naming language in the reply, (c) the canonical CLI recommendation, (d) no fabricated medication context.
- Policy preset shape: extended `_ALLOWED_V0_PATHS` in [packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py](../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py).
- Cross-language enum diff: [packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py](../../packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py).

---
```

Append to the **Invariant Index** table:

```markdown
| INV-C004 | Host Profile Context Must Inform Genome-Informable Turns | Clinical Boundary |
```

Bump the document's **Version** + **Last Updated** at the top.

**`docs/reference/cli-output-schemas.md`** — append a `host profile *` subsection with the worked envelopes for `init` (one-shot + skip), `show` (present + missing), `set`, `edit`, `review`. Each example carries `cli_output_schema_version: "1.0"`.

**`docs/reference/user-stories.md`** — amend Story 1's bullet about "session memory captures family history" to:

> The agent's canonical anchor for who-the-user-is is the **host profile** at `<derived_root>/host_profile.json` (identity, biometrics, lifestyle, medical history, family history, goals) — captured during onboarding via `genomeclaw host profile init`, retrieved per turn via `genomeclaw_host_profile`. Session memory captures **per-turn free-form context** (mood, transient concerns, conversational state) that doesn't belong in the structured profile.

### Step 5.3 — REFACTOR

- Reconcile `development-plan.md` with the as-shipped design. If anything diverged during Phases 1–4 (different storage path, different section structure, additional / removed CLI subcommand), update the plan so future readers see what actually shipped — not the original guess.
- Confirm `work-notes.md` reflects every session's actual work + decisions + diverges.
- Move the plan directory:
  ```bash
  git mv docs/plans/active/host-profile-personal-context docs/plans/completed/host-profile-personal-context
  ```

---

## Implementation Details

### Privacy-Safety Review Pass

Invoke the privacy-safety-reviewer agent on the cumulative diff. Required focus areas:

- The new evidence kind `host_profile:<section>#<field>` — does it leak structure into agent replies that could identify family members?
- The audit log freetext-length placeholder — is `<freetext len=N>` enough or does it need a hash?
- The agent's gap-framing language — does it inadvertently encourage the user to share more than they wanted to?
- The `host setup` chain — does the non-interactive fallback (auto-skip with `meta.skipped_init_at`) hide a privacy decision behind a recorded timestamp the user didn't see?
- Family-history identity-leakage paraphrase rule — is "relation-class + condition + age-class granularity" actually sufficient guidance, or does it need worked examples in the prompt?

File the review output at `docs/plans/active/host-profile-personal-context/privacy-review.md` (or already exists from Phase 4; this is a second pass on the cumulative diff).

### Edge Cases to Handle

- INV-C004's promotion language must be reconciled against INV-C001 v1.7 (PRS-decline pattern) — the two interact when the agent declines a PRS *and* the profile is gappy. Confirm § 6 of the prompt handles the interaction.
- The `live_llm` gate's cost (~ $0.10–0.50 per run) — add the marker to the appropriate gated-tests config so it doesn't run on every PR.

### Error Handling

- If the privacy-safety-reviewer flags a blocking issue, revert to Phase 4 (or earlier) per the planning protocol's "stale plan is worse than no plan" rule. Do not patch silently in Phase 5.

### Privacy / Egress Notes

- This phase ships documentation changes only — no new code paths, no new egress.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/reference/INVARIANTS.md` | MODIFY | Promote INV-C004; bump Version + Last Updated; update Invariant Index. |
| `docs/reference/cli-output-schemas.md` | MODIFY | Document `host profile *` envelopes. |
| `docs/reference/user-stories.md` | MODIFY | Amend Story 1 to point at the host profile. |
| `docs/plans/active/host-profile-personal-context/development-plan.md` | MODIFY | Reconcile with as-shipped design. |
| `docs/plans/active/host-profile-personal-context/privacy-review.md` | CREATE / MODIFY | Privacy-safety-reviewer output (cumulative pass). |
| `docs/plans/active/host-profile-personal-context/` | MOVE | → `docs/plans/completed/host-profile-personal-context/`. |
| `packages/toolkit/tests/invariants/test_invariants_doc_shape.py` | MODIFY | Assert INV-C004 entry + Version bump. |

---

## Verification

```bash
# Doc-shape gate
uv run --project packages/toolkit pytest \
  packages/toolkit/tests/invariants/test_invariants_doc_shape.py -v

# Full suite — must be green end-to-end
uv run --project packages/toolkit pytest -q

# Plugin tests
cd packages/nemoclaw-plugin && bun test

# Live LLM gate (gated marker — once before declaring complete)
uv run --project packages/toolkit pytest -m live_llm -v
```

---

## Completion Criteria

- [ ] INV-C004 entry lands in `INVARIANTS.md` with full Rule / Requirements / Where it applies / How to verify sections.
- [ ] Invariant Index table updated.
- [ ] `INVARIANTS.md` Version bumped, Last Updated set.
- [ ] `cli-output-schemas.md` documents every `host profile *` envelope.
- [ ] `user-stories.md` Story 1 amended.
- [ ] Privacy-safety-reviewer pass approved + any findings addressed.
- [ ] `development-plan.md` reflects the as-shipped design (not the original guess).
- [ ] `work-notes.md` reflects actual work performed across all phases.
- [ ] Full test suite green (unit + integration + invariant + privacy default + provenance + `live_llm` once).
- [ ] No raw genomic data, secrets, or sample identifiers in the repo.
- [ ] Plan moved from `active/` to `completed/`.

# Privacy-safety review — Phase 4 (agent system prompt)

**Date**: 2026-05-31
**Reviewer**: `privacy-safety-reviewer` agent (blocking pass per phase-4.md § 4.3)
**Artifact reviewed**: `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` (Phase-4 diff:
§ 1 tool row, § 4 Step 1.5 + topic-discovery sentence, § 5 profile-grounded memory notes,
§ 6 profile-section gating, § 7 citation form, § 8 privacy bullet, § 9 pattern 4, § 10 lead).

**Verdict**: Accept with required changes — three small targeted amendments (all applied this session); four Phase-5 follow-ups recorded.

---

## Required changes (all applied)

| # | Issue | Invariant | Fix applied |
|---|-------|-----------|-------------|
| A | The § 4 topic-discovery "carry the relevant sections forward into your tool-call planning text" sentence could leak profile content into `web_search` query construction — the carry-forward and the § 8 topic-only rule lived in different sections, so a reasoning-pressured model could interpolate a recorded medication / family-history condition into a search query. (Highest-priority.) | INV-P001 / INV-P002 | Scoped the carry to **GenomeClaw** tool framing and inlined the explicit "do NOT carry verbatim profile content into `web_search` queries — the § 8 topic-only rule binds the carried content" restriction. Regression gate: `test_invP002_system_prompt_carry_forward_excludes_web_search`. |
| B | § 10's format lead bullet named "family history" as a reply-lead element without a self-report / paraphrase qualifier — the last instruction before reply composition, where framing drift is most likely. | INV-C001 | Added "Profile context is cited as self-report ('you've recorded …', not 'you have …'); family history is paraphrased at relation-class + condition + age-class granularity (§ 4 Step 1.5 / § 7), never quoted verbatim." Regression gate: `test_invC001_system_prompt_format_lead_marks_family_history_self_report`. |
| C | § 5 used `family_history.notes` as an example "section key" for memory provenance, but the `sections` selector vocabulary is `family_history` (the schema field is `family_history.notes`, but it is not a valid `sections` value). Risked normalizing a non-section path + a 400 if used as a filter. | INV-A001 / INV-E001 | Changed the example to `family_history` and noted these are "the `sections` selector names the tool accepts." |

## Findings confirmed sound (no change)

- **Family-history third-party protection** — paraphrase discipline (relation-class + condition + age-class) is taught at three layers (§ 4 Step 1.5, § 5, § 8). The only residual reply-lead path was Change B, now closed.
- **Research-vs-clinical boundary** — self-report framing consistently taught; § 6 profile-section gating correctly refuses actionable framing when the relevant section is empty ("calibrate to the gap rather than assume").
- **Confabulation risk** ("invent a medication list") — Step 1.5's steps 1–3 (name gap → explain → recommend CLI) establish the gap is real before step 4's "proceed with what you DO have, calibrated to the gap"; the live_llm gate (test 10d) tests exactly this failure mode. Acceptable as written.
- **No internal contradictions** on when retrieval is mandatory, `init` vs `set`, or self-report framing.

## Phase-5 follow-ups (recorded, not blocking)

1. **INV-C004 promotion** — prompt is structurally ready; no blockers against the trace-walk / live gates beyond the three fixed issues.
2. **"BEFORE continuing the interpretation" wording** in Step 1.5 (missing-signal path) reads slightly stronger than step 4's "proceed with what you DO have" — settle to one intended reading in Phase 5.
3. **"Calibrated to the gap" hardening** — make explicit that "calibrated" means treat the section as *unknown/unassumed*, not *absent-and-safe*, for a more-compliant future model.
4. **Tool-description parity** — verify the `genomeclaw_host_profile` description in `index.ts` carries the same minimal-sufficient / paraphrase reminder (memory notes are user-readable + durable).

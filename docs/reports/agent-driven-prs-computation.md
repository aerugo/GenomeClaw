# Agent-Driven Polygenic Risk Score Computation

**Status**: Architecture proposal. Supersedes static-panel framing in MVP spec Q8 (which had not yet been implemented).
**Audience**: GenomeClaw developers building Phase 6 Slice E; project owner deciding whether to accept a Q8 v1.6 amendment along the lines proposed here.
**Date**: 2026-05-16
**Companion plan target**: would supersede [phase-6-slice-e.md](../plans/active/mvp/phases/phase-6-slice-e.md) if accepted.

---

## Solution Summary

Replace the v1.5/Q8 *fixed-three-trait static panel* with an **agent-driven, host-computed, memory-cached** PRS architecture. The agent (running on a long-horizon reasoning model like Claude 4.x / GPT-5 / o-series) decides which PGS Catalog scorefile is right for the user's question; the GenomeClaw host toolchain runs `pgsc_calc` against the chosen scorefile; results land in a persistent `pgs_scores` table keyed by **PGS Catalog ID** (not by curator-named trait); memory carries the agent's reasoning trail so future sessions reuse the choice without re-deciding.

Five architectural moves, applied together:

1. **PGS Catalog ID, not trait name, is the canonical key.** The host's `pgs_scores` table is keyed by `pgs_id` (e.g. `PGS000018`) — not by `cad` / `t2d` / `prostate`. A trait *label* is a human-readable secondary field the agent supplies at compute time; multiple PGSs per trait are first-class.
2. **A four-tool host surface, not a one-tool surface.** `genomeclaw_pgs_list` / `genomeclaw_pgs_get` / `genomeclaw_pgs_compute` / `genomeclaw_pgs_compute_status`. The compute step is async from the agent's POV (so the agent can talk back to the user while pgsc_calc runs in the background) but does NOT require per-request user approval.
3. **Consent is one-time at install, not per-compute.** PGS Catalog egress is already a documented INV-P001 destination — the user opted in when they accepted the install-time egress destinations. Per-compute approval would be friction without a real check (the user isn't a PGS expert second-guessing "PGS000018 vs PGS004696"; the choice-quality gate is the agent's reasoning + the memory-validation contract). Runaway-compute risk is bounded by a **concurrency cap (1 in-flight compute at a time)** + a **kill-switch** (`genomeclaw config set pgs.compute_enabled false` revokes the path entirely). A daily wall-clock budget was considered + rejected as overengineering for a single-user PoC (see the "Why no daily wall-clock budget?" note in Layer 3); add back later if a real failure mode appears.
4. **Agent-validated PGS choice as a memory contract.** When the agent picks a PGS for a user question, it writes a memory note carrying the **alternatives it considered + why this one** — the same INV-A001 + INV-C001 v1.6 discipline applied to PGS curation rather than to gene-note synthesis. The choice rationale is *the* trust layer; it's auditable via `memory_get` after the fact + supersedable when literature moves.
5. **No pre-curated trait panel ships in code.** No `reference/pgs_panel/<trait>.yaml`. No `_PGS_PANEL` constant. The "panel" is the union of what the agent has chosen to compute for *this* user; it grows over time as a side-effect of use.
6. **The PRS-decline pattern.** Before computing, the agent evaluates whether the PRS literature for the trait is mature enough to produce a meaningful result. If not, it **declines gracefully with two specific named reasons** rather than computing a poorly-validated score. The decline criteria + the decline language live in the agent system prompt as a peer to the existing "hard-genes decline" pattern (PER3 / CLOCK / VNTRs). The default is *good enough to be actually meaningful, or nothing* — not *best available, regardless of quality*. Added 2026-05-17 after a methodological-review pass: the agent will reach into PGS Catalog for almost any trait the user asks about; the decline gate is what stops it from confidently computing scores whose top-decile relative risk doesn't warrant a percentile, whose replication is thin, or whose ancestry calibration fails for the user.

The result: Story 10's "what about my CAD risk?" turn becomes the same shape as Story 9's "what about caffeine?" turn — research-and-synthesis at max reasoning, with the user's genome data as the bedrock, with one extra orchestrated compute step instead of one extra lookup. The agent's long-horizon reasoning ceiling is the choice-quality ceiling. Pre-curation can't beat what the model can reason about for the user.

---

## Problem

### The trap I almost re-introduced

MVP spec Q8 (signed off 2026-05-08) commits the system to three pre-picked traits — CAD, T2D, and one of (breast cancer, prostate cancer) — each mapped to a curator-chosen PGS Catalog scorefile. The Phase 6 Slice E plan I drafted on 2026-05-15 leaned into this: a `reference/pgs_panel/<trait>.yaml` mapping table, a one-shot `pgs-compute --traits cad,t2d,prostate` command, a `genomeclaw_pgs(trait="cad")` lookup tool. The project owner flagged this as the curated-notes mistake in PRS clothing. They were right.

The agent-research-and-synthesis plan (closed 2026-05-15) walked the project through the same lesson for *lifestyle calibration*. The pre-baked `reference/curated_notes/<gene>.md` pattern failed three ways:

1. **Suppressed the frontier model's training knowledge.** The curator wrote the answer; the model paraphrased. The model's deeper knowledge of long-tail edge cases stayed locked.
2. **Didn't scale beyond the curator's pre-defined set.** "What about ABCG2 and uric acid?" → silence, unless the curator pre-thought to author the note.
3. **Didn't self-update.** ClinVar reclassifies a variant; a new meta-analysis shifts an effect size; the static note silently rots.

The PRS-panel version repeats every line:

1. **Suppresses model judgement** about PGS quality. Which of the 39 published CAD PRSs is right for *this* user (their ancestry, their question framing)? The curator's pick stands forever.
2. **Doesn't scale.** "What's my Alzheimer's risk?" → silence, until a curator amends the YAML + a Dockerfile rebuild ships.
3. **Doesn't self-update.** PGS Catalog gets new scorefiles weekly; some supersede prior ones for specific populations. Static YAML can't reason about it.

### Why PRS is *not* fundamentally different from lifestyle calibration

Pre-empting an objection — *"but PRS is heavy compute; you can't just dynamically pick the answer like a web search"*. True. There IS a real structural difference: pgsc_calc takes minutes per scorefile, not seconds. **But the editorial layer — which scorefile to use, why, how to label it, how to frame the result — does not benefit from being pre-baked.** That layer is exactly where long-horizon reasoning earns its tokens.

The compute layer needs orchestration discipline (cache, approval, async). The editorial layer needs reasoning, not curation.

---

## Why long-horizon reasoning models change the cost-benefit

The original Q8 reasoning was sound *for the model era it was written in*. In 2024 a frontier model invoked at moderate reasoning would have produced a noisy, citation-poor PGS choice. Pre-curation made sense: pay the human curator cost once + cap the agent's failure surface.

Two things changed in 2025–2026:

**(a) Reasoning ceilings rose substantially.** OpenAI gpt-5.5 at `xhigh`, Claude 4.x at `high`/`xhigh`, the o-series at `max` — these models produce calibrated, multi-source-grounded reasoning over technical literature that a single curator can't match for breadth. PGS Catalog choice is exactly the kind of decision they're good at: the catalog has structured metadata (sample sizes, ancestries, training cohorts, validation studies); the literature on PRS calibration is well-indexed; the question "best PGS for this user's question" decomposes cleanly into sub-questions the model can answer one at a time.

**(b) The agent's research-and-synthesis protocol now exists.** Phase 2 of the agent-research-and-synthesis plan shipped a 14K-character agent system prompt that teaches the model how to: classify a turn as health-interpretation, hit memory before re-research, validate retrieved memory at max reasoning, supersede stale notes, cite primary sources verbatim. This protocol generalises to PGS choice without modification — the choice IS a health-interpretation turn, the cited sources are PGS Catalog entries + PRS-methodology papers, the memory carries the rationale.

The pre-curated panel was a reasonable answer to "we don't trust the model with this decision". The model now warrants the trust, *if and only if* the orchestration around it (compute approval, provenance, supersession) is right.

---

## Proposed architecture

### Layer 1 — Persistent state

**`pgs_scores` table** (host-side, in `derived/<run-id>/variants.duckdb`):

| Column | Type | Notes |
|---|---|---|
| `pgs_id` | TEXT NOT NULL | PGS Catalog ID, e.g. `PGS000018`. **Primary key.** |
| `trait_label` | TEXT NOT NULL | Agent-chosen human-readable label, e.g. `coronary artery disease (2018 CARDIoGRAMplusC4D)`. The agent decides + can rename later via supersession. |
| `percentile_in_user_ancestry` | DOUBLE | Continuous-ancestry-calibrated percentile. NULL if calibration failed. |
| `raw_score` | DOUBLE | Pre-calibration raw score. |
| `study_population` | TEXT | The scorefile's training population (e.g. "European-ancestry meta-analysis, UK Biobank + CARDIoGRAMplusC4D"). |
| `calibration_warning` | TEXT NULL | Set when continuous-ancestry calibration flags low-confidence. Surfaced verbatim. |
| `requested_for_question` | TEXT | The verbatim user question that triggered this compute (provenance). |
| `agent_choice_rationale` | TEXT | The agent's reasoning for picking this PGS — alternatives considered, why this one. Memory-note-shaped. |
| `+ 7 canonical provenance columns` | ... | per INV-R001 |

**Memory side** (in agent workspace `MEMORY.md`):

When the agent picks a PGS, it writes a memory note keyed by `pgs:<id>` containing the choice rationale, alternatives considered, freshness date, and any subsequent validation/supersession (per INV-A001). On the next session, `memory_search "PGS for CAD risk"` returns this note before the agent re-researches.

### Layer 2 — Host tool surface (4 tools, replaces the 1 in Q8)

```typescript
// 1. List what's already been computed for this user.
api.registerTool({
  name: "genomeclaw_pgs_list",
  description: "List PRSs already computed for this user. Each row shows pgs_id, trait_label, percentile, calibration_warning, freshness. Call this first when the user asks about a trait — if the right PGS is already computed, skip the compute step.",
  parameters: Type.Object({}, { additionalProperties: false }),
  outputClass: "summary",
});

// 2. Fetch one computed PRS in full (incl. agent_choice_rationale).
api.registerTool({
  name: "genomeclaw_pgs_get",
  description: "Fetch one computed PRS by its PGS Catalog ID. Returns percentile, raw_score, study_population, calibration_warning, the question that triggered it, and the agent's choice rationale.",
  parameters: Type.Object({ pgs_id: Type.String({ minLength: 1 }) }, { additionalProperties: false }),
  outputClass: "summary",
});

// 3. Compute a PGS not yet in the user's store. Async from the agent's POV
// (returns immediately with a task_id; pgsc_calc runs in the background on
// the host); the agent polls _compute_status until done. No per-request
// user approval — the egress to PGS Catalog is INV-P001-class consent given
// once at install. Bounded by a host-side concurrency cap (1 in-flight) +
// a kill-switch (`pgs.compute_enabled false` revokes the path entirely).
api.registerTool({
  name: "genomeclaw_pgs_compute",
  description: "Compute a PRS for a new PGS Catalog ID. Returns a `task_id` immediately; pgsc_calc runs in the background. Poll `genomeclaw_pgs_compute_status` for progress; once done, fetch the result via `genomeclaw_pgs_get`. **Always populate `rationale`**: it lands as a column on the `pgs_scores` row and is the user's audit trail for why this PGS was chosen. Always populate `requested_for_question`: it stamps the row with the verbatim question that triggered the compute.",
  parameters: Type.Object({
    pgs_id: Type.String({ minLength: 1 }),
    trait_label: Type.String({ minLength: 1 }),
    rationale: Type.String({ minLength: 50 }),  // force the agent to explain
    requested_for_question: Type.String({ minLength: 1 }),
  }, { additionalProperties: false }),
  outputClass: "summary",
});

// 4. Check progress on an in-flight compute.
api.registerTool({
  name: "genomeclaw_pgs_compute_status",
  description: "Check status of an in-flight `pgs_compute`. Returns one of `queued | running | done | failed`. When `done`, fetch the result via `genomeclaw_pgs_get`. `failed` carries an error message — surface it to the user; one failure mode is `compute_path_disabled` when the user has set `genomeclaw config set pgs.compute_enabled false`.",
  parameters: Type.Object({ task_id: Type.String({ minLength: 1 }) }, { additionalProperties: false }),
  outputClass: "summary",
});
```

The plugin tool count goes from 5 → 9 (the four new PGS tools land alongside the existing `_status` / `_findings` / `_variant` / `_evidence` / `_gene`). The `genomeclaw_pgs` singular tool from the Q8 sketch is retired.

### Layer 3 — Compute orchestration

`pgs_compute` lands on the host service. The host:

1. Validates the PGS ID against PGS Catalog (one HTTPS GET to confirm the scorefile exists; INV-P001-class egress, already authorised at install).
2. Checks the kill-switch: if `pgs.compute_enabled` is `false`, returns `status=failed` with error `compute_path_disabled` immediately + the agent surfaces this to the user.
3. Checks the concurrency cap: if another `pgs_compute` is in-flight, the new request lands in a queue with `status=queued`. Cap default: 1 concurrent compute. (Bounded by the personal-host envelope per spec Q8.)
4. Otherwise enqueues a backgrounded Nextflow `pgsc_calc` invocation. Status transitions: `queued → running → done | failed`. The agent's `_compute_status` polls until terminal.
5. On completion: stamps the seven canonical provenance columns + writes the row to `pgs_scores`; also INSERTs a matching `clinical-non-actionable` row into `findings` with `evidence_ref=pgs_catalog:PGS<id>`.

The compute runs in a sandbox-isolated subprocess on the host (not inside the OpenClaw sandbox container, which has no bio binaries per INV-D002). The bridge is the same one Phase 4 + Phase 5 established for `genomeclaw pipeline {ingest,normalize,annotate,materialize}`.

**Why no per-request user approval?** The user already consented to PGS Catalog egress at install time (INV-P001 documents PGS Catalog as one of the allowed deliberate-egress destinations). A per-compute prompt would not add a meaningful check — the user isn't a PGS-Catalog expert who can second-guess "PGS000018 vs PGS004696", and the agent's choice rationale is already auditable via the `agent_choice_rationale` column on `pgs_scores` + the memory note. The concurrency cap + kill-switch bound runaway-compute risk without requiring a click per compute. If the user wants to *revoke* a compute, they can delete the row or disable the compute path entirely with `genomeclaw config set pgs.compute_enabled false`.

**Why no daily wall-clock budget?** *(decision reverted 2026-05-17 from an earlier draft of this report)* — a daily cumulative-wall-clock cap on pgsc_calc was considered as an additional runaway safeguard but rejected as overengineering for a single-user PoC. The user is one sophisticated person who already ran `pgsc_calc` manually under the v1.5 Q8 design; the threats a budget would protect against (agent loops, exploration ramping, background-load degradation) are bounded sufficiently by the concurrency cap (no simultaneous waste), the kill-switch (full revocation), and the natural per-compute time bound (~5 min per PGS). The budget would have added ~30 LOC of tracking + a budget-check race condition + a `budget_exceeded` status path without protecting against a failure mode that actually exists for one curious user. Add back later if/when a real failure surfaces.

### Layer 4 — Memory shape

When the agent decides to compute a PGS, it writes a memory note *before* invoking `pgs_compute_request`. The note carries the INV-A001 schema:

```markdown
## 2026-05-16 — Choosing a CAD PRS for the user's first CAD-risk question

**Question**: my dad had a heart attack at 58. is there anything in my genome about cad risk?

**Tool calls (research phase, reasoning=high)**:
- web_search "PGS Catalog coronary artery disease best score 2025 ancestry calibration": returned top hits including PGS003725 (Inouye 2018, UK Biobank), PGS000018 (CARDIoGRAMplusC4D), PGS004696 (Tamlander 2024).
- web_fetch "https://www.pgscatalog.org/score/PGS000018/": metadata page; training cohort: meta-analysis UK Biobank + CARDIoGRAMplusC4D; n=171,191 cases / 537,481 controls; European-only training; cross-ancestry validation present with calibration warnings for non-European cohorts.

**Sources retrieved**:
- https://www.pgscatalog.org/score/PGS000018/: canonical mid-size European CAD PRS with cross-ancestry calibration metadata.
- PMID 31346155 (Inouye 2018): foundational CARDIoGRAMplusC4D analysis.
- PMID 38123456 (Tamlander 2024): newer PGS004696 with better Eu discrimination but less cross-ancestry validation.

**Synthesis (reasoning=xhigh)**:
For the user's question (ancestry unknown so far; family history strongly suggesting follow-up), PGS000018 is the best default: it has the most cross-ancestry calibration metadata + the strongest replication record, and the continuous-ancestry calibration in pgsc_calc handles the user's specific ancestry estimation. PGS004696 has better Eu discriminative power but its calibration story isn't yet mature. PGS003725 is essentially the prior version of PGS000018 (same underlying data, earlier release). Choosing PGS000018.

**Calibration**:
- Effect size: 2-3× lifetime CAD risk for top-decile cohort (well-replicated across PGS000018's validation cohorts).
- Evidence quality: strong-replicated.
- Heterogeneity: moderate across ancestries; the calibration_warning surfaces if the user's continuous ancestry falls outside Eu training distribution.
- Modulators: family history, traditional risk factors (LDL, BP, smoking, T2D) — PRS adds context to but does not replace the standard premature-CAD workup.

**Recommendation framing**: shifted-prior interpretation, not a clinical-actionable call.

**Citations surfaced to the user**: https://www.pgscatalog.org/score/PGS000018/, PMID 31346155, PMID 38123456 (mentioned as the better-Eu-discrimination alternative considered + why not chosen).

**Freshness**: as of 2026-05-16. Re-research if asked after 6 months OR if user explicitly asks for the newest PGS.
```

This note IS the editorial layer. It does what the YAML would have done — but does it under the agent's reasoning, with citations, with rationale, with supersession-on-demand. Future sessions retrieve it; the agent validates it (per INV-C001 v1.6); if a better PGS lands in 2027, the agent supersedes + recomputes.

### Layer 5 — The PRS-decline pattern

PGS Catalog has scorefiles for almost any trait someone has thought to GWAS. The catalog is a *repository*, not a *curated set of validated tools*. The quality is heterogeneous: some scores come from large rigorous consortia with deep replication, others from single-lab analyses with no independent validation, others from heritability-only proof-of-concepts with no useful predictive power. A naïve agent ("the user asked about creativity → search PGS Catalog → find a scorefile → compute it") will produce confident-looking percentiles for traits where no meaningful percentile exists.

The decline pattern is the methodological gate that prevents this. Modelled on the existing "hard-genes decline" pattern in the agent system prompt (PER3 VNTR / CLOCK / ACTN3 / VNTRs / paralogs / MT genome — gene loci where the agent declines with two named reasons rather than fabricating an answer), the PRS-decline pattern asks the agent to refuse a compute when the literature isn't mature enough.

**Decline criteria** (any one triggers a decline; the agent names two specific reasons in its reply):

1. **Top-decile relative risk < ~1.5×**: the PRS's discriminative power is too low for the result to materially shift the user's prior. A percentile is mathematically computable but informationally near-empty.
2. **No independent replication**: the best available scorefile has been validated only on a holdout of the original training cohort (or on overlapping cohorts), not on independent cohorts. Single-lab PRSs in the published literature have repeatedly failed to replicate on external validation.
3. **Ancestry-calibration failure for this user**: when the user's continuous ancestry estimate falls outside the training-data distribution AND no cross-ancestry validation exists for the available scorefiles, the `calibration_warning` would dominate the meaningful signal. Computing produces a number with no honest interpretation.
4. **No biologically-grounded polygenic basis**: the available "scorefiles" are heritability estimates, not predictive scores (most personality minor dimensions, "creativity", "leadership", "happiness", many curated lifestyle traits). A percentile here is a category error — the underlying paper makes a heritability claim, not a per-individual prediction claim.

**The decline turn shape** (modelled on the hard-genes decline language in [agent-system-prompt.md § 9](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)):

```
User: "what about my creativity? is there a polygenic risk score for that?"

Agent (at xhigh):
Step 1: memory_search "creativity PRS" → 0 hits.
Step 2: web_search "PGS Catalog creativity polygenic score" + web_fetch on the
        most relevant hits → finds 2 scorefiles, both from single-lab studies
        on small cohorts (~30K), no independent replication, heritability-claim
        framing in the underlying papers rather than predictive validation.
Step 3: Reasoning at xhigh → this triggers PRS-decline criteria 2 + 4 (no
        independent replication; the scorefiles encode a heritability estimate
        not a predictive score). Don't invoke genomeclaw_pgs_compute.
Step 4: Write a memory note recording the decline + the two specific reasons
        so future sessions hit the decline rather than re-evaluating.
Step 5: Reply:

"I'm going to decline computing a creativity PRS, and I want to be specific
 about why so you can push back if you disagree.

 Two reasons:

 1. The two scorefiles available in PGS Catalog for 'creativity' are from
    single-lab studies on small cohorts (~30K) with no independent
    replication. Single-lab PRSs in the published literature have a high
    rate of failing to replicate on external cohorts.

 2. The underlying papers make heritability claims, not per-individual
    predictive claims. A scorefile derived from a heritability estimate
    can be mathematically computed against your genome, but the resulting
    percentile doesn't have an honest interpretation — heritability is a
    population-level concept, not a per-person one.

 If you want me to compute one anyway to see the number, I can — but the
 number wouldn't tell you anything actionable about you specifically. A
 different framing of the question (e.g., 'do I have variants linked to
 specific cognitive traits with mature literature?') might land somewhere
 useful. Want to try that?"
```

This is the *right* answer. The wrong answer is to find a scorefile, compute it, and return a confident-looking percentile. The decline costs the user nothing (no compute spent, no anxiety produced); the bad alternative costs them a false signal they have to manage.

**Enforcement**:
- **Agent system prompt addition** (lands in Slice E.3, see [agent-system-prompt.md § 9](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)). The decline criteria + the two-named-reasons rule become part of the prompt's "When you are uncertain" section, peer to the existing hard-genes decline language.
- **Prompt-content gate** in [test_agent_system_prompt_contract.py](../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py): a new test asserts the prompt names the decline criteria + the two-named-reasons rule + a worked example trait that should decline.
- **Behavioural live_llm test**: ask the agent about a known-immature trait (e.g. "creativity PRS" or "leadership PRS"); assert (a) the agent does NOT invoke `genomeclaw_pgs_compute`, (b) the reply names two specific decline reasons, (c) the trace shows the agent did the research step before declining (i.e. it's a *reasoned* decline, not a hardcoded refusal).
- **Decline note in memory**: the agent writes a memory note recording the decline + the two reasons so future sessions hit the decline note before re-deciding (memory_search hit; INV-C001 v1.6 validation; freshness check). The decline note has the same INV-A001 schema as a compute-success note, with `compute_decision: decline` as a section.

The decline pattern is the methodological *spine* that justifies the agent-driven architecture as a whole. Without it, "the agent decides which PGS to compute" reduces to "the agent will compute something for any trait you ask about", which is exactly the failure mode a methodological reviewer would correctly flag. With it, the agent has the same kind of disciplined boundary the static panel had — *fewer things are computed* — but the boundary is drawn at "what has meaningful evidence" rather than "what the curator pre-decided".

---

## Walked-through example: Story 10 under the new architecture

```
User: "my dad had a heart attack at 58. is there anything in my genome about cad risk?"

Agent (composing at xhigh — health-interpretation turn per INV-A002):

Step 1: memory_search "CAD risk" → 0 hits.
Step 2: genomeclaw_status → confirms active run.
Step 3: genomeclaw_findings genes=[] category="clinical-non-actionable" → no CAD finding yet.
Step 4: genomeclaw_pgs_list → 0 PRSs computed.
Step 5: web_search + web_fetch on PGS Catalog (see memory note above).
Step 6: Synthesis at xhigh → decision: compute PGS000018.
Step 7: Write memory note (the one above).
Step 8: genomeclaw_pgs_compute(
          pgs_id="PGS000018",
          trait_label="coronary artery disease (CARDIoGRAMplusC4D + UK Biobank)",
          rationale=<the rationale section of the memory note, verbatim>,
          requested_for_question="my dad had a heart attack at 58. is there anything in my genome about cad risk?"
        )
        → task_id="t-abc123" (status: running)
Step 9: Agent surfaces the in-flight state to the user:
        "I'm computing your CAD polygenic risk score using PGS000018 — the canonical
         CARDIoGRAMplusC4D + UK Biobank PRS with the best cross-ancestry calibration
         metadata. I considered PGS004696 (better Eu discrimination, less cross-ancestry
         calibration) and went with PGS000018 for the cross-ancestry story. Compute takes
         ~5 min; I'll continue when it lands."
Step 10: Agent polls genomeclaw_pgs_compute_status every ~30s (OR cuts the turn and resumes
         when the next user message arrives — both are fine; the result persists).
Step 11: Done. genomeclaw_pgs_get(pgs_id="PGS000018") → {percentile: 87, raw_score: 0.42, ...}.
Step 12: Synthesis turn at xhigh — combine the percentile with father's MI, modifiable-risk
         literature, framing nuances, the calibration_warning text. Cite PGS000018 + the two
         PMIDs from the choice note.
Step 13: Reply.
```

This is a **long-horizon reasoning task**: 13 numbered steps, async compute, persistent memory side-effect. The pre-curated panel reduces it to a 3-step "lookup → format → reply" path. The long-horizon model is the wrong tool for that 3-step path; it's the *right* tool for the 13-step path.

---

## Trade-off analysis

| Dimension | Static panel (Q8 v1.5) | Agent-driven (this proposal) | Hybrid (seed + extend) |
|---|---|---|---|
| **Time-to-first-PRS** | Pre-staged at install: < 1s per ask | ~5 min cold; instant on re-ask | < 1s for seeded; ~5 min cold for new |
| **Long-tail trait coverage** | Curator-bounded | Open | Open with default-batch warm path |
| **PGS quality decision** | Curator (one-shot, static) | Model at xhigh (per-question, dynamic, citable) | Mixed |
| **Adapts to new PGS publications** | Requires Dockerfile + spec edit + rebuild | Just works; supersession via INV-A001 | Manual for seeded; auto for extended |
| **Cost per cold-ask** | $0 (already computed) | ~5 min compute + ~$0.50 reasoning at xhigh | $0 for seeded; same as agent-driven otherwise |
| **User consent surface area** | One-time INV-P001 install opt-in | Same one-time INV-P001 opt-in; runaway risk capped by concurrency cap + kill-switch | Same |
| **Runaway-compute safety** | Trivially bounded (3 traits, eager) | Concurrency cap (1 in-flight) + kill-switch (`pgs.compute_enabled false`); no daily budget for the PoC | Same as agent-driven |
| **Code complexity** | Low (1 tool, 1 endpoint, 1 YAML, 1 table) | Higher (4 tools, async compute, concurrency enforcement, memory shape) | Highest (both paths) |
| **Faithfulness to Q9 lesson** | Violates | Honors | Compromised |
| **Failure mode** | Silent under-coverage (long tail) | Compute denial (user friction) + agent over-confidence in PGS choice | Both, partial |

**The honest cost** of the agent-driven path: the FIRST CAD-risk question costs ~5 min of wall-clock while pgsc_calc runs in the background. The agent surfaces the in-flight state to the user ("I'm computing PGS000018 because…; back in ~5 min") and can either poll until done OR cut the turn and resume on the next user message. The static panel front-loads that cost at install time (eager-compute all 3 traits as part of `genomeclaw pipeline pgs-compute --traits cad,t2d,prostate`).

**The honest benefit**: the SECOND CAD-risk question (and the long tail of "what about asthma?" "what about ADHD?" "what about T2D?") is exactly the same code path. No spec amendments. No Dockerfile rebuilds. No YAML edits. No per-compute clicks. The system *scales* with use.

For a personal-genomics assistant being used over years, the second behavior dominates the first.

---

## Comparison to the original Q8 framing

Q8 (2026-05-08, project-owner-signed): three traits, ancestry-normalized, pgsc_calc, single tool, single endpoint, fixed panel.

Q8 v1.6 (proposed by this report): N user-relevant PGSs, ancestry-normalized, pgsc_calc per request, four tools, async compute, agent-curated trait → PGS mapping persisted as memory + as the `pgs_scores` table.

What stays the same:
- `pgsc_calc` is the compute engine. Continuous-ancestry calibration via `--run_ancestry` is mandatory.
- PRS findings carry `category: clinical-non-actionable` + no `clinical_escalation` marker (INV-C001).
- PGS Catalog is the inbound egress destination — host-side, deliberate, opt-in (INV-P001).
- The compute respects the personal-host resource envelope (16 GB RAM, 2 CPUs).
- Genomic data never traverses the network (INV-D001) — only scoring weights flow inbound.

What changes:
- Trait → PGS mapping moves from `reference/pgs_panel/<trait>.yaml` (curator) to the agent's memory note (model at xhigh).
- The tool surface goes from one tool (`genomeclaw_pgs`) to four (`_list`, `_get`, `_compute_request`, `_compute_status`).
- Compute is async + user-approved per request, not eager-at-install.
- The "panel" emerges from use, not from spec.

Q8 v1.6 is a structural pivot — same scope as Q9 v1.6 (curated_notes → research-and-synthesis). The Q8 v1.5 ACs (specifically AC9) need a parallel rewrite.

---

## Implementation phasing

Three sub-slices (replaces the four in [phase-6-slice-e.md](../plans/active/mvp/phases/phase-6-slice-e.md)):

**Slice E.1 — schema + tool surface + endpoint contracts (host-side, fast):**
- `pgs_scores` table per the schema above
- `Pgs{Row,RowResponse,ListResponse,ComputeTaskResponse}` Pydantic models
- 4 host service endpoints: `/v1/pgs/computed` (list), `/v1/pgs/computed/{pgs_id}` (get), `POST /v1/pgs/compute` (request — host returns task_id + queued/running), `/v1/pgs/compute/{task_id}` (status)
- 4 plugin tools registered with the right TypeBox schemas
- Compute orchestration stubbed (real pgsc_calc runner lands in E.2; concurrency cap + kill-switch enforcement land in E.3)
- ~12 host tests + 4 plugin vitest tests

**Slice E.2 — pgsc_calc compute runner + provenance:**
- `prep/pgs.py` `compute_pgs(*, vcf, pgs_id, derived_root, reference_root) -> PgsRow` synchronous compute (mocked + real-data smoke)
- CLI subcommand `genomeclaw pipeline pgs-compute --pgs PGS000018 --rationale '<text>' --question '<text>'` for manual invocation outside the agent path
- Reference-data check (1000G + HGDP for ancestry calibration)
- Real-data smoke against the project owner's Nebula VCF + at least one PGS (probably PGS000018 — CAD)
- ~6 tests + manual smoke

**Slice E.3 — async orchestration + concurrency + kill-switch + decline pattern + agent system prompt update:**
- The `_compute` → backgrounded task → status polling loop (Nextflow runs in a subprocess; status held in a small SQLite table at `derived/<run-id>/pgs_compute_tasks.sqlite`)
- Concurrency cap (1 in-flight; new requests queue with `status=queued`)
- `genomeclaw config set pgs.compute_enabled false` kill-switch for users who want to fully revoke the compute path post-install
- INV-P001 deployment gate: `needs_sandbox` test that the sandbox image doesn't add `pgscatalog.org` to any policy preset allowlist (compute happens host-side)
- The auto-INSERT of a matching `clinical-non-actionable` finding row when compute completes
- **Agent system prompt update** ([agent-system-prompt.md](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md)): two additions — (a) §4 Step 3 / Step 4 paragraph teaching the PGS-compute flow (when to invoke `_compute`, what to write in the rationale, how to surface the in-flight wait), and (b) **the PRS-decline pattern** added to §9 ("When you are uncertain") as a peer to the existing hard-genes decline. The decline pattern names the four criteria + the two-reasons rule + a worked example.
- **Prompt-content gates** in [test_agent_system_prompt_contract.py](../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py): one new test for the PGS-compute teaching, one new test asserting the PRS-decline pattern names the four criteria + the two-reasons rule + at least one worked-example trait.
- **Behavioural `live_llm` decline test**: ask the agent about a known-immature trait (e.g. creativity PRS); assert (a) the agent does NOT invoke `genomeclaw_pgs_compute`, (b) the reply names two specific decline reasons, (c) the trace shows the agent did the research step before declining (the decline is *reasoned*, not hardcoded refusal).
- ~9 tests (concurrency-cap enforcement; kill-switch; INV-P001 gate; auto-finding-insert; polling loop terminal-state correctness; 2 prompt-content gates; PRS-decline memory-note schema; decline-rehydrates-from-memory on second ask) + 2 `live_llm` snapshot tests: Story 10 end-to-end against a real (computed) PRS + the decline behavioural test against an immature trait.

**Slice E.4** (deferred per the methodological review's items 1 + 2): validation study of agent PGS-selection quality against expert-curated benchmarks for 8-12 canonical traits, plus the pre-compute consent turn. Out of scope for the personal-use PoC; revisit before any deployment beyond the project owner.

---

## Test surface (architectural)

The same three layers from the agent-research-and-synthesis plan apply:

**Static gates** (host-runnable, fast):
- Pydantic model contracts (each new shape).
- `pgs_scores` DDL via `create_store()`.
- Endpoint shape (mock store + TestClient).
- Plugin vitest covering the 4 new tools' TypeBox schemas + correct host-service routing.
- Approval state-machine transitions (each state → each terminal state).

**`needs_sandbox` gates** (image-baked):
- Plugin registers 9 tools (was 5).
- Policy preset includes `/v1/pgs/*` paths.
- `pgscatalog.org` is NOT on the sandbox-side allowlist (host-side egress only).
- The PGS-compute flow's surface area + the **PRS-decline pattern** are documented in the agent system prompt (two new prompt-content gates in [test_agent_system_prompt_contract.py](../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)).

**`live_llm` gates** (real OpenAI calls):
- Story 10 end-to-end against a real PRS (after Slice E.2's real-data smoke seeds at least one PGS row).
- The "PGS choice rationale" assertion: the agent's memory note for the chosen PGS lists ≥1 alternative + a defended choice.
- A negative gate: a fast follow-up question about the same PGS doesn't trigger a re-compute (memory hit).
- A supersession gate: pre-stage a memory note for an outdated PGS choice; the agent re-evaluates + writes a `Supersedes:` note when current literature has moved.
- **A decline-behavioural gate**: ask the agent about a known-immature trait (e.g. "what's my creativity PRS?"); assert (a) the agent does NOT invoke `genomeclaw_pgs_compute`, (b) the reply names two specific decline reasons from the four-criteria set, (c) the trace shows the agent did the research step before declining (reasoned decline, not hardcoded refusal), (d) a decline-shaped memory note lands on disk so future sessions hit the decline rehydrated rather than re-deciding.
- **A decline-rehydration gate** (slice F or later, requires multi-session): the second session asking the same immature-trait question hits the prior decline note via `memory_search` + validates it (INV-C001 v1.6 three-check) + replies from the validated note rather than re-researching the same dead-end literature.

---

## Open questions (require project-owner decision before Slice E.1)

1. **Q-E1' (revised)**: do you accept the Q8 v1.6 rewrite? It's the same scope as the Q9 v1.6 rewrite the agent-research-and-synthesis plan made. If yes, Q-E1 (which third trait) becomes moot — there is no fixed trait list. **Accepted 2026-05-17** by the propagation of canonical-doc updates.
2. **Q-E2'**: when an existing `pgs_scores` row gets superseded by a newer PGS, do we keep both rows (audit trail) or replace (clean state)? **My lean: keep both**, with a `superseded_by` field pointing at the newer `pgs_id` — mirrors INV-A001's "prior note stays on disk" rule for memory notes.
3. **Q-E3'**: does PGS Catalog have a stable JSON API that's preferable to the agent doing web_fetch + HTML parsing? If yes, building a thin `genomeclaw_pgs_catalog_lookup` tool (host-side) might simplify the agent's PGS-discovery work. **Lean: investigate first** — if PGS Catalog's REST API is stable + well-documented, the thin tool is high-value; if not, web_search + web_fetch are already on the agent's belt and we don't need to add a tool.

Decisions on Q-E2' + Q-E3' unblock the corresponding Slice E.3 sub-tasks but are not on the critical path for Slice E.1.

(Earlier drafts of this report included two now-removed open questions: a Q-E2' pair around per-compute user approval — removed 2026-05-17 after the project owner pointed out that per-compute approval is overcautious paternalism — and a Q-E2' around a daily wall-clock budget default — removed 2026-05-17 after agreeing that for a single-user PoC the concurrency cap + kill-switch + natural per-compute time bound cover runaway-compute risk without the budget mechanism. See the "Why no per-request user approval?" + "Why no daily wall-clock budget?" notes in Layer 3.)

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Agent picks a poor-quality PGS (low replication, wrong ancestry training) | Memory note schema forces the agent to enumerate alternatives + cite quality metadata; INV-C001 v1.6 memory-validation step catches drift session-over-session; the `agent_choice_rationale` column on every `pgs_scores` row is the user's after-the-fact audit surface (read via `genomeclaw_pgs_get` OR by inspecting the row directly). The user can delete + force a recompute if they disagree. |
| Agent computes a confident-looking PRS for a trait with no meaningful evidence base | **The PRS-decline pattern** (Layer 5). Before computing, the agent evaluates four decline criteria (top-decile RR < ~1.5×; no independent replication; ancestry-calibration failure for this user; no biologically-grounded polygenic basis); if any triggers, the agent declines with two named reasons rather than computing. The decline gate is the methodological spine of the agent-driven design — it draws the boundary at "meaningful evidence" instead of "what the curator pre-decided". Enforced by an agent-system-prompt addition + a prompt-content gate + a `live_llm` decline-behavioural test (Slice E.3). |
| Agent runs away with computes (e.g. 100 PGSs in a session) | **Concurrency cap (1 in-flight)** + **kill-switch** (`genomeclaw config set pgs.compute_enabled false` revokes the path entirely). For a single-user PoC the concurrency cap + the natural ~5-min-per-compute bound (pgsc_calc against one PGS on a 30× WGS) keep cumulative damage bounded; a daily wall-clock budget was considered + rejected as overengineering. Add back later if a real failure surfaces. |
| pgsc_calc consumes the personal-host envelope (CPU, memory) for tail compute | The sequential per-request compute model (one PGS at a time) caps simultaneous resource pressure; failure to converge surfaces as `failed` task status, not a host crash. |
| The compute step blocks the agent's reasoning | The async + polling shape lets the agent surface "I'm computing…; back in ~5 min" to the user immediately + either poll until done OR cut the turn and resume on the next message. The compute persists across sessions. |
| Provenance trail across the agent's choice + the compute + the result + the memory note becomes hard to audit | Every layer carries the seven canonical provenance columns; the agent's choice rationale lands as a column on `pgs_scores`; INV-A001 memory schema captures the agent-side trail. Audit is reconstructible end-to-end. |
| Agent's PGS-selection quality has not been benchmarked against expert curation | **Deferred to Slice E.4** per the methodological-review recommendation. Personal-use PoC scope accepts the risk; before any deployment beyond the project owner, run the validation study (8-12 canonical traits, agent choice vs. expert-curated choice, blind-rated by ≥2 PGS specialists). |
| User receives a sensitive PRS result without pre-test counseling | **Deferred to Slice E.4** per the methodological-review recommendation. Personal-use PoC scope accepts the risk; production deployment requires a pre-compute consent turn analogous to the clinical genetic-counseling pre-test discussion. |

---

## Recommendation

Accept the Q8 v1.6 rewrite. Replace the static panel with the agent-driven architecture above, **including the Layer-5 PRS-decline pattern as a non-negotiable part of Slice E.3** (not deferred). The decline pattern is the methodological spine that lets the agent-driven design be defensible: without it, "the agent decides which PGS to compute" reduces to "the agent will compute something for any trait", which is exactly the failure mode a methodological reviewer correctly flags. With it, the agent has a disciplined boundary at "what has meaningful evidence" rather than "what the curator pre-decided".

The two heaviest review concerns — the agent's PGS-selection quality benchmarked against expert curation, and the pre-compute consent turn — are **explicitly deferred to Slice E.4** for the personal-use PoC scope. They must land before any deployment beyond the project owner.

If accepted: archive [phase-6-slice-e.md](../plans/active/mvp/phases/phase-6-slice-e.md), draft a new `phase-6-slice-e-v2.md` along these lines, write a Q8 v1.6 amendment to [docs/plans/active/mvp/spec.md](../plans/active/mvp/spec.md) (parallel to the Q9 v1.6 work), update INV-C001 + propose any new INV-A03 (Agent-Curated Compute Provenance) if needed, then start Slice E.1 RED.

If rejected: the static-panel design in [phase-6-slice-e.md](../plans/active/mvp/phases/phase-6-slice-e.md) stands; this report becomes a recorded alternative path the project chose not to take, for future reference.

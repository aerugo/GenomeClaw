# Agent Research-and-Synthesis Pattern — Development Plan

**Status**: Complete (closed 2026-05-15)
**Created**: 2026-05-15
**Completed**: 2026-05-15
**Branch**: `feature/agent-research-and-synthesis`
**Spec**: [spec.md](spec.md)
**Supersedes**: [MVP Phase 6 Slice C](../mvp/phases/phase-6.md) (7 curated gene notes + topics/hard-genes.md)

---

## Critical Invariants to Respect

- **`INV-D001`** — raw genome stays host-side. Agent research never sends user variants in a web search query; the only payload that goes over the wire is the topic-term query (e.g., `"CYP1A2 rs762551 caffeine half-life 2024"`).
- **`INV-D002`** — sandbox image carries no bio binaries. Adding `web_search` egress doesn't change this.
- **`INV-P001` v1.7** *(revised 2026-05-15)*. Native OpenAI `web_search` flows through the agent-provider's existing egress envelope (on by default when agent is OpenAI). Managed `web_search` providers (Brave / Tavily / etc.) are a separate third named egress destination (opt-in). `web_fetch` is a fourth named egress destination (opt-in; off by default).
- **`INV-P002`** — unchanged at the host-service layer. The host service still ships minimal-sufficient JSON.
- **`INV-C001` v1.6** — revised. Lifestyle findings cite `memory:<id>` or `web:<url>`, not `gene_note:<gene>`.

## Proposed New Invariants

- **`INV-A001` Agent Memory Provenance** — every memory note records: timestamp, question, tools+sources, reasoning levels, synthesis confidence, freshness date.
- **`INV-A002` Synthesis Reasoning Floor** — health-interpretation turns compose at the maximum reasoning level the configured model supports.

## Current State Analysis

### What exists today

- [`EvidenceRecord`](../../../packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py) model supports five kinds: `gene_note`, `topic`, `clinvar`, `pgs_catalog`, `pharmgkb`. The first two (`gene_note`, `topic`) point at `reference/curated_notes/` and need removal.
- [`_resolve_gene_note`](../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py) + [`_resolve_topic`](../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py) helper functions read curated-notes files off disk.
- [`build_app(reference_dir=...)`](../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) carries the `reference_dir` parameter primarily for curated-notes resolution; other uses of `reference_dir` (grch38, AlphaMissense, etc.) are pipeline-side, not service-side.
- [Phase 6 Slice B integration tests](../../../packages/toolkit/tests/integration/test_service_evidence.py) cover 9 cases, 3 of which exercise the curated-notes path (`test_evidence_resolves_gene_note_from_curated_dir`, `test_evidence_resolves_gene_note_case_insensitively`, `test_evidence_resolves_topic_from_curated_dir`).
- Phase 6 Slice A's `Finding` model accepts `evidence_ref` as any non-empty string — no enum constraint on the prefix. This stays.
- OpenClaw `memory-core` plugin is bundled in the sandbox image and `loaded` by default (verified via `openclaw plugins list` during the Phase 5 live sweep).
- OpenClaw `web_search` v1.7 contract baked at image build time (Phase 2b, 2026-05-15): `tools.web.search.enabled: true` + no managed provider + `tools.web.fetch.enabled: false`. See [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../packages/nemoclaw-plugin/sandbox/Dockerfile).
- The agent's `thinkingDefault` is unset; the gateway uses the model's default (typically `medium` for gpt-5.5).

### What's missing for the research-and-synthesis pattern

1. **OpenClaw `web_search` configured** in the sandbox image's openclaw.json with a provider (OpenAI native for gpt-5.5 is the simplest; falls back to `BRAVE_API_KEY` or `DuckDuckGo` if pinned).
2. **Agent system prompt** teaching the protocol: try memory first → research if needed (at moderate reasoning) → synthesise at max reasoning (for health-interpretation turns) → save memory note before replying → cite sources verbatim.
3. **Memory-note template** — a structured Markdown skeleton the agent fills in, satisfying `INV-A001`.
4. **`gene_note:` / `topic:` cleanup** — remove from `_SUPPORTED_EVIDENCE_KINDS`; delete `_resolve_gene_note` + `_resolve_topic`; remove the 3 curated-notes test cases; remove the `reference_dir` kwarg from `build_app` (or repurpose it for non-evidence uses if still needed).
5. **Policy preset update** — `policy-preset.yaml` allowlists the chosen `web_search` provider host (e.g. `api.openai.com` if using OpenAI native, or `api.brave.com` for Brave).
6. **Snapshot tests** for `INV-A002`: assert `executionTrace.thinking == "max"` on Story 4/9/10 health-interpretation turns; assert it's NOT `max` on conversational turns.
7. **Default-config egress test** for the clarified `INV-P001`: `tools.web.search.enabled: false` (default) → no `web_search` / `web_fetch` calls happen.

## Solution Design

### The four-input model

The agent at every decision point can draw from:

1. **Model training knowledge** — vast, cheap, cutoff-dated. Always available.
2. **Online sources** — current, varying quality. Available when `web_search` is configured.
3. **Memory** — prior synthesis; user-specific. Always available via `memory_search` / `memory_get`.
4. **GenomeClaw host service** — authoritative for the user's genome data. Always available via the 5 (→ 6 in Phase 6E) registered tools.

### Two reasoning regimes

- **Research reasoning** (`thinking: medium` or `high`) — exploratory, source-gathering. Goal: cover the space, identify sources, note conflicts.
- **Synthesis reasoning** (`thinking: max`) — bioinformatician-in-healthcare judgment. Goal: produce the calibrated, evidence-bound, appropriately-hedged answer the user will rely on.

These can run as one inference call (frontier models with extended reasoning interleave naturally — `thinking: max` covers both phases) or as two calls. The architecture treats them as logically distinct; the floor invariant (`INV-A002`) applies to the synthesis phase only.

### How "health-interpretation turn" is detected

The agent self-classifies via its system prompt:

> When composing a response that interprets your user's genomic data — including variant implications, gene-level findings, PRS interpretations, lifestyle guidance based on genotype, or PGx recommendations — use the maximum reasoning level. For conversational replies (recall, scheduling, casual back-and-forth, confirmation of prior facts), use your standard reasoning.

The agent emits its reasoning level as part of the response metadata; the gateway honours it via OpenClaw's per-message `thinking` parameter. Phase 2 snapshot tests verify:
- Story 9 (lifestyle CYP1A2): `thinking == "max"` on the synthesis turn.
- Story 4 (PGx clopidogrel): `thinking == "max"` on the synthesis turn.
- Story 10 (PRS CAD): `thinking == "max"` on the synthesis turn.
- A conversational turn ("hi", "what did we talk about yesterday?", "can you remind me of my caffeine plan?"): `thinking < "max"`.

### Memory note schema (satisfies `INV-A001`)

Every memory note written by the research-and-synthesis pattern follows this skeleton:

```markdown
## YYYY-MM-DD — <topic, 5-10 words>

**Question**: <verbatim user message that triggered this research>

**Research turn** (reasoning=<level>, model=<model-id>):
- Tools called:
  - <tool name> <args>: <one-line summary of result>
- Sources retrieved:
  - <citation>: <key fact extracted>

**Synthesis turn** (reasoning=max, model=<model-id>):
- Bioinformatician-in-healthcare judgment:
  - <numbered claims with confidence notes>
- Calibration notes:
  - <effect sizes, heterogeneity, modulators>
- Recommendation framing:
  - <falsifiable experiment / lifestyle change / clinical escalation>

**Citations surfaced to the user**:
- <inline URL or evidence ref>

**Freshness**: as of YYYY-MM-DD. Consider re-researching after <N months> or on user request.
```

The agent writes this note **before** generating the user-visible reply, so a future session reading the note knows exactly what was synthesised, at what reasoning level, from what sources.

### What stays vs. what gets cut

| Component | Status |
|-----------|--------|
| `Finding` schema + `/v1/findings` endpoints (Slice A) | unchanged |
| `EvidenceRecord` + `/v1/evidence/{ref}` route + dispatch architecture (Slice B) | unchanged shape; smaller dispatch table |
| `clinvar:` / `pgs_catalog:` / `pharmgkb:` evidence kinds (variant-keyed) | kept |
| `gene_note:` / `topic:` evidence kinds (curated-notes) | **removed** |
| `_resolve_gene_note` / `_resolve_topic` helpers | **removed** |
| `reference/curated_notes/` filesystem layout | **removed from scope** (not in v0) |
| `build_app(reference_dir=...)` parameter | **removed if no remaining consumer**; otherwise repurposed |
| 7 curated gene notes (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR) | **never written** |
| privacy-safety-reviewer-per-curated-note workflow | **dropped** |
| 5 plugin tools | unchanged |
| Sandbox image | rebuilt with `web_search` configured |
| OpenClaw `memory-core` plugin | **enabled by default** (already bundled; just allowlisted) |
| Agent system prompt | **new** — teaches the research-and-synthesis protocol |

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests | Status |
|-------|-------------|-----------|------------|--------|
| **1** | Configure OpenClaw memory + web_search in sandbox; remove `gene_note:` / `topic:` kinds from host service; cleanup tests | invariant (INV-P001 egress default), endpoint shape, sandbox image rebuild | ~6 (-3 deleted + ~9 added) | **complete** 2026-05-15 |
| **2** | Author the agent system prompt + memory-note schema; ship one end-to-end research-and-synthesis run against gpt-5.5 + OpenAI native web_search; snapshot tests for INV-A001 + INV-A002 + **INV-C001 v1.6 memory-validation** | snapshot (story 9 prose + execution trace), invariant (INV-A001 provenance shape + primary-source-required gate + supersession trail, INV-A002 reasoning floor, INV-C001 v1.6 memory validation against weak/stale fixture notes) | ~8 (delivered 20: 11 prompt-content + 7 validator + 2 sandbox-installed) | **complete** 2026-05-15 |
| **3** | Live verification sweep — Story 9 over `openclaw chat`; Story 4 (PGx); Story 10 (PRS); session-2 recall test; staleness re-research test; **validation-driven supersession** against pre-staged weak memory note; resolve pi-harness BOOTSTRAP.md conflict (see Phase 2 work-notes); pin INV-A002 via per-call reasoning-effort probe | live-LLM snapshot via `openclaw agent --json` against a real synthetic derived store | ~4 + 1 supersession | pending (Phase 3) |

Phase 1 is the surgical cleanup + configuration phase (1 session, **complete 2026-05-15**). Phase 2 is the new-content phase (system prompt authoring + invariant gates + a one-shot live smoke against gpt-5.5; **complete 2026-05-15**). Phase 3 is the live verification sweep (1 session, gated on a built sandbox image + the user's OPENAI_API_KEY + a real synthetic derived store).

## Testing Strategy

### Unit + integration (host-runnable)

- **Endpoint shape**: after Phase 1, `/v1/evidence/gene_note:CYP1A2` returns 400 ("unknown kind") instead of 404. The supported-kinds enum shrinks.
- **Egress default (`INV-P001` v1.7)**: `test_invP001_sandbox_web_egress_contract` asserts the v1.7 contract on the baked image's openclaw.json — `tools.web.search.enabled: true` (native OpenAI search activates by default for the canonical OpenAI deployment), `tools.web.search.provider` absent (no managed provider pinned), `tools.web.fetch.enabled: false` (`web_fetch` opt-in only). Managed providers and `web_fetch` require explicit user action post-install.
- **Memory-note schema**: a unit test asserts the agent system prompt's memory-note skeleton parses correctly when the agent fills it in (i.e., a small fixture-format-validation test).

### Snapshot (live LLM via `openclaw agent --json`)

Run against a built sandbox image + gpt-5.5 + the user's OPENAI_API_KEY:

- **Story 9 — first ask**: the response's `executionTrace.thinking == "max"` for the synthesis turn AND `executionTrace.toolSummary.tools` includes `memory_search`, `genomeclaw_variant`, AND a web/research tool. The reply cites at least one URL or pubmed ID.
- **Story 9 — second ask (same session, follow-up)**: a turn like "remind me of the caffeine plan" runs at non-max thinking — recall-only, no fresh research.
- **Story 9 — session 2 (fresh session, same topic)**: `memory_search` finds the prior note; the synthesis turn shows a **memory-validation step** in its reasoning trace; if validation passes, no fresh `web_search`; if validation fails, the agent supersedes the note + cites the new note.
- **Story 9 — session 3 ("any newer studies?")**: re-research triggers a new `web_search`; updates the prior memory note via the supersession mechanism (the old note stays on disk).
- **Validation-driven supersession** *(new, added 2026-05-15)*: a fixture starts the agent with a deliberately-weak prior memory note pre-staged in the workspace (a conclusion that overreaches its cited sources, OR cites only other memory notes, OR is past its freshness date on a fast-evolving topic). The agent's response must (a) surface the gap in `executionTrace`, (b) write a `supersedes:` note, (c) cite the new note (not the original), (d) reflect the corrected synthesis in user-facing prose.
- **Memory-of-memory rejection** *(new, added 2026-05-15)*: unit test feeding the note-writer step a draft note that cites only other memory notes — the writer must reject it; no on-disk note results; the agent runs fresh research instead.
- **Story 4 — PGx clopidogrel**: synthesis at `thinking: max`; CPIC guideline cited.
- **Story 10 — PRS CAD**: synthesis at `thinking: max`; calibration warning surfaced from PGS catalog data + percentile interpretation reasoned over.

### Memory-provenance (audit)

Inspect a memory note after Phase 2:
- Contains the verbatim user question.
- Lists tool calls with their result summaries.
- Records reasoning levels for both research and synthesis.
- Records source citations.
- Records freshness date.

## Documentation Updates Required

- [INVARIANTS.md](../../reference/INVARIANTS.md) — bump to v1.6; revise INV-C001 (drop curated_notes reference; cite memory + web instead), clarify INV-P001 (web_search as 3rd named egress), add INV-A001 + INV-A002.
- [architecture.md](../../reference/architecture.md) — add the four-input + two-reasoning-regime diagram; revise the evidence resolver table; remove curated_notes from the canonical layout figure.
- [grand-plan.md](../../reference/grand-plan.md) — replace the "lifestyle calibration via curated_notes" passage with the research-and-synthesis pattern; bump the corresponding Horizon-2 deliverable.
- [user-stories.md](../../reference/user-stories.md) — revise Story 9 (the canonical demo of this pattern); add a "Notable" section flagging the memory + research surfaces; update Stories 4 + 10 to reflect the synthesis-floor invariant.
- [docs/plans/active/mvp/spec.md](../mvp/spec.md) — rewrite AC5 + AC10; supersede Q9 with a Q9-revised pointer at this plan; add ACs for web_search opt-in egress + memory provenance + reasoning floor.
- [docs/plans/active/mvp/development-plan.md](../mvp/development-plan.md) — mark Phase 6 Slice C superseded; reference this plan's slices in the same row.
- [docs/plans/active/mvp/phases/phase-6.md](../mvp/phases/phase-6.md) — strike Slice C from the slice plan; note the cleanup in Phase 1 of this plan.

# Feature: Agent research-and-synthesis pattern (supersedes curated_notes/)

**Status**: Implemented (closed 2026-05-15)
**Created**: 2026-05-15
**Completed**: 2026-05-15
**Owner**: project owner + Claude (planning agent)
**Supersedes**: [MVP spec Q9](../mvp/spec.md) (`reference/curated_notes/` lifestyle calibration), Phase 6 Slice C, `gene_note:` + `topic:` evidence kinds.

---

## Goal

Replace the pre-authored `reference/curated_notes/<gene>.md` lifestyle-calibration mechanism with a **research-and-synthesis** pattern built on OpenClaw's first-class primitives: agent memory (`memory_search` / `MEMORY.md` / `memory/YYYY-MM-DD.md`), web search (`web_search` / `web_fetch` / `x_search`), and the model's extended reasoning effort. The agent acts as a **bioinformatician-in-healthcare**: it researches the literature at moderate reasoning, then synthesises a calibrated, evidence-bound answer at the model's **maximum reasoning level**, and persists what it learned so future sessions don't re-research from zero.

## Background

### Why the curated-notes pattern is wrong for v0

The MVP plan's Q9 decision shipped a `reference/curated_notes/<gene>.md` directory: the project owner pre-authors markdown files carrying their calibrated stance on each gene (effect sizes, modulators, experiment proposals, evidence-quality hedging). The agent retrieves these via `genomeclaw_evidence(ref="gene_note:<gene>")` and composes lifestyle responses on top of the note.

Three structural problems:

1. **Doesn't scale beyond the pre-curated set.** Long-tail genes ("anything about ABCG2 and uric acid?") fail because there's no note. The user has to anticipate every topic they'll ever ask about.
2. **Static.** Curated notes don't update with new literature. ClinVar releases monthly; PharmGKB updates regularly; the curated notes don't.
3. **Doesn't leverage the frontier model's training knowledge.** GPT-5.5 has read every paper through its training cutoff. The curated-notes pattern actively suppresses that — it asks the agent to defer to the project owner's pre-codification rather than reason from what it already knows. **This is a 100× capability mismatch in the wrong direction.**

### What we're leveraging instead

Two OpenClaw built-in technologies the MVP plan didn't account for:

- **Memory** (built-in OpenClaw plugin `memory-core`, with optional `memory-wiki` / `memory-honcho`): the agent writes plain Markdown notes per session in its workspace under `~/.openclaw/workspace/<agent>/`. Indexed for semantic + keyword search. Daily notes promote to durable memory via the dreaming pass. The agent recalls prior synthesis without re-research.
- **Web search** (built-in OpenClaw managed tool `web_search` + provider-native variants): the agent can search the web through a configured provider (OpenAI's native `web_search` for Responses-API models is the cheapest path; Brave / Tavily / DuckDuckGo as fallbacks). Adds current online sources to the model's research substrate.
- **Extended reasoning** (frontier-model native, exposed via OpenClaw's `thinking` config): the agent can compose a response at the model's maximum reasoning effort. For health interpretation specifically, this is the difference between a coherent paraphrase and an actual bioinformatician-in-healthcare judgment.

Together these compose into a much more powerful pattern than pre-authored notes.

## Acceptance Criteria

- [ ] **AC1**: A fresh agent session asking *"my sleep has been bad lately. anything in my genome about caffeine metabolism?"* produces a response whose execution trace shows: (a) a `memory_search` call (returning empty on first ask), (b) a `genomeclaw_variant` call for the diagnostic SNP, (c) a `web_search` or model-native research call, and (d) the user-facing synthesis turn at the maximum reasoning level the configured model supports.
- [ ] **AC2**: The synthesis turn writes a structured memory note before replying. The note records: the question, the tools used, the reasoning level for research and for synthesis, the sources cited (URLs / PMIDs), the synthesis verdict + confidence, and a "freshness as of" date.
- [ ] **AC3**: A second session asking the same topic produces a response whose execution trace shows a `memory_search` hit AND a **memory-validation step** (reasoning over the recalled note's conclusion ↔ its cited primary sources at the `INV-A002` synthesis-turn floor). When validation passes, no fresh `web_search` runs and the reply cites the existing memory note. When validation fails — even on a same-topic recall — the agent runs fresh research, writes a superseding memory note per `INV-A001`, and cites the new note in its reply.
- [ ] **AC4**: A third session asking "any newer studies?" triggers a fresh `web_search` even when memory has a prior note; the new synthesis updates or supersedes the prior memory note via the supersession mechanism (the old note stays on disk for the audit trail).
- [ ] **AC4b** *(added 2026-05-15)*: A session where the agent recalls a deliberately-weak memory note (fixture: a conclusion that overreaches its cited sources) shows the agent (a) surfacing the gap in its execution trace, (b) writing a superseding note via `INV-A001`'s supersession mechanism, (c) citing the superseding note (not the original) in its reply, (d) reflecting the corrected synthesis in user-facing prose. Closes the hallucination-propagation failure mode where uncritical recall of a prior over-extension becomes the new "source of truth".
- [ ] **AC5** *(replaces MVP spec AC5)*: The agent answers lifestyle questions about the user's genome by combining `genomeclaw_variant` results with reasoned research over (training knowledge + online sources + memory), then composing direct lifestyle guidance at maximum reasoning. No clinician-deferral default for lifestyle topics; no pre-authored curated notes required.
- [ ] **AC6**: A health-interpretation turn (any reply that interprets genomic data or gives guidance the user might act on) is composed at the maximum reasoning level the configured model supports. Verified by inspection of the execution trace's `thinking` field.
- [ ] **AC7**: A non-health-interpretation turn (recall, scheduling, casual back-and-forth) is composed at the agent's standard reasoning level — the max-reasoning floor does not apply to conversational turns.
- [ ] **AC8**: With web search **fully** disabled in config (`tools.web.search.enabled: false`), the agent still answers from memory + training knowledge + GenomeClaw data, and explicitly tells the user it cannot research fresh information. No silent fallback to stale or fabricated citations.
- [ ] **AC8b** *(added 2026-05-15, option-B revision)*: With the default sandbox config (`tools.web.search.enabled: true` + no managed provider pinned), the agent **uses** native OpenAI `web_search` automatically when interpreting a health question on an OpenAI agent. The execution trace shows a `web_search` tool call routed through the OpenAI Responses API (not through a managed-provider host). The reply cites at least one fresh URL or PubMed ID returned by the native search.
- [ ] **AC8c** *(added 2026-05-15)*: With `tools.web.fetch.enabled: false` (the default), the agent never issues a `web_fetch` call. If the agent decides a specific URL is worth fetching, it asks the user to enable `web_fetch` first rather than silently failing.
- [ ] **AC9** *(replaces MVP spec AC10)*: The host service evidence resolver supports only variant-keyed kinds (`clinvar:`, `pgs_catalog:`, `pharmgkb:`). The `gene_note:` and `topic:` kinds are dropped from the resolver; the `reference/curated_notes/` directory is not part of the v0 layout.
- [ ] **AC10**: The agent cites its sources verbatim in its reply — URLs for web sources, `memory:<file>#<anchor>` for prior memory notes, `clinvar:RCV...` / `pharmgkb:PA...` / `pgs_catalog:PGS...` for variant-keyed evidence. The plugin's `genomeclaw_evidence` tool accepts the variant-keyed kinds.

## Applicable Invariants

- **`INV-D001`** — unchanged. Raw artifacts stay host-side.
- **`INV-D002`** — unchanged. Sandbox image carries no bio binaries.
- **`INV-E001`** — extended. Findings carry an evidence_ref; the resolved kinds shrink to variant-keyed only (host service) plus `memory:<id>` and `web:<url>` as agent-side citation forms.
- **`INV-P001` v1.7** — revised 2026-05-15 to distinguish two `web_search` paths. **Native OpenAI `web_search`** (hosted by the OpenAI Responses API) flows through the agent-provider's existing egress envelope — not a new named egress destination — and is **on by default** when the agent provider is OpenAI. **Managed `web_search` providers** (Brave, Tavily, Perplexity, etc.) ARE a third named egress destination and remain opt-in via `tools.web.search.provider`. **`web_fetch`** is a fourth named egress destination (outbound HTTP to arbitrary URLs; not part of any agent-provider API) and ships disabled in the sandbox image.
- **`INV-P002`** — unchanged. The agent endpoint stays minimal-sufficient.
- **`INV-R001`** — unchanged for the genome pipeline. The agent's memory notes are not part of the derived-store provenance; they're agent-workspace state.
- **`INV-C001` v1.6** — revised. Lifestyle findings cite a `memory:<id>` reference (synthesis from prior research) or a `web:<url>` reference (current research); the `gene_note:<gene>` form is retired.

## Proposed New Invariants

- **`INV-A001` — Agent Memory Provenance.** Every memory note the agent writes via the research-and-synthesis pattern records: timestamp, the question that triggered the research, the tool calls made (with their results' source attributions), the reasoning level used for research and for synthesis, the synthesis verdict + confidence, and a "freshness as of" date so a future session can decide whether to re-research. **Each memory note must cite at least one primary source** (web URL, PubMed ID, ClinVar ID, gene-database identifier, etc.) — a note that cites only other memory notes is malformed and rejected at write time, closing the memory-of-memory hallucination loop. **Supersession** is the mechanism by which validation-driven memory updates land: a superseding note records `supersedes: <prior-anchor>` + the gap found + the corrected synthesis; the prior note stays on disk for the audit trail.
- **`INV-A002` — Synthesis Reasoning Floor.** Any user-facing **health-interpretation turn** must be composed at the maximum reasoning level the configured model supports. A *health-interpretation turn* is any reply that (a) interprets the user's genomic data (variant, finding, gene-level, PRS) for clinical or lifestyle meaning, or (b) gives guidance the user might plausibly act on (medication, lifestyle change, lab follow-up, clinician consultation). Non-interpretation turns (recall confirmation, conversational pacing, scheduling) are exempt — the floor does not over-apply.
- **`INV-C001` v1.6 — Memory-validation requirement** *(added 2026-05-15)*. When a synthesis turn cites a `memory:<id>` reference, the agent must validate the cited note at the `INV-A002` floor with three independent checks: (1) does the conclusion follow from the cited primary sources? (2) are the sources sufficient (peer-reviewed, multi-source)? (3) is the note past its freshness date for a topic with evolving evidence? If any check fails, the agent supersedes the note via `INV-A001`'s supersession mechanism before composing the reply. Closes the hallucination-propagation failure mode where stale or over-extended prior synthesis becomes the new "source of truth".

## Out of Scope

- **Curated-notes content authoring** (the 7 lifestyle gene notes + topics/hard-genes.md from MVP Q9). Dropped entirely; the research-and-synthesis pattern replaces it.
- **The `gene_note:` and `topic:` evidence-resolver kinds.** Removed from `_SUPPORTED_EVIDENCE_KINDS` + corresponding tests deleted in Phase 1 of this plan.
- **Custom memory schemas / backends.** Default OpenClaw `memory-core` (SQLite) is sufficient for v0; `memory-wiki` is a deferred enhancement.
- **Web-content caching / persistence**. Fetched web pages are not persisted independently of the memory note that cites them; the citation is the URL + a per-session timestamp. Caching is OpenClaw's `web_search` `cacheTtlMinutes` (default 15 min) — sufficient for within-session reuse.
- **Multi-agent collaboration patterns.** Single agent per user; memory is scoped to that agent's workspace.

## Privacy & Safety Considerations

### Web search as a third named egress destination

**Native OpenAI `web_search`** is **enabled by default** in v0 *when the user has configured OpenAI as the agent provider* — it flows through the same egress destination the user already consented to when they supplied their OpenAI API key, and the OpenClaw web-search docs confirm it activates automatically for Responses-API traffic when `tools.web.search.enabled: true` + no managed provider is pinned. **Managed `web_search` providers** (Brave, Tavily, etc.) remain off by default and require explicit user opt-in via `openclaw config set tools.web.search.provider <name>` + the provider's API key. **`web_fetch`** is off by default in the sandbox image (`tools.web.fetch.enabled: false`) because it issues outbound HTTP to arbitrary URLs and is not part of any agent-provider API.

This option-B default landed 2026-05-15 (after Phase 2's live smoke surfaced that the prior `tools.web.search.enabled: false` default disabled native OpenAI search too — costing the user a capability they had already consented to via the agent-provider API key).

The privacy contract:
- **The user's genomic data never leaves via web search.** The agent's web queries are about *external knowledge* ("CYP1A2 caffeine metabolism") not about the user's specific variants. The query payload never contains user-identifying information.
- **`INV-P001` v1.7 test asserts** (the v1.7 default-config contract): in default-config runs (`tools.web.search.enabled: true` + no managed provider + `tools.web.fetch.enabled: false`), the agent's `web_search` calls route through the OpenAI Responses API (the agent provider's existing envelope); zero `web_fetch` calls happen; queries carry only topic terms. In managed-provider opt-in runs, the request egresses to the managed provider's host; same topic-only payload rule. In `web_fetch` opt-in runs, the URL is the only destination.
- **Policy preset** (OpenShell L7 proxy): the sandbox container's outbound egress is governed by `policy-preset.yaml`. The OpenAI API host (`api.openai.com`) is on the allowlist as part of the agent-provider envelope (transparent to the user; it's where the agent already calls). Managed `web_search` provider hosts (`api.brave.com`, etc.) are added to the allowlist only when the user explicitly pins a provider. `web_fetch` egress remains gated until the user enables it.

### Memory provenance + the "what does the agent know about you" surface

The agent's memory lives in `~/.openclaw/workspace/<agent>/` inside the sandbox container. It includes:
- `MEMORY.md` — durable facts about the user (e.g. "user prefers SI units", "user is concerned about sleep").
- `memory/YYYY-MM-DD.md` — daily notes including research synthesis.
- `DREAMS.md` — dreaming consolidation summaries.

This data is **inside the sandbox**. It doesn't traverse the network except via the same agent-endpoint inference call that all conversation does. But it IS user-identifying once it grows: it accumulates the user's reading history, their concerns, their gene-by-gene exploration trail.

**`INV-A001`** (memory provenance) ensures every memory entry is auditable: the user can `cat ~/.openclaw/workspace/<agent>/MEMORY.md` and see exactly what the agent knows about them. The agent's `memory` tools (`memory_get`, `memory_search`) are part of the standard plugin allowlist; the user can ask "what do you remember about me?" and the agent reads its own notes back.

### Synthesis reasoning floor as a safety property

`INV-A002` (synthesis reasoning floor) is fundamentally a **safety invariant**, not just a quality knob. Health interpretation at low reasoning produces fluent-but-wrong answers; at max reasoning, the model spends more compute on edge-cases, contraindications, and confidence calibration. The floor closes a failure mode where the agent gives plausible-sounding but unconsidered advice.

## Open Questions

- **Q1**: How does the agent reliably classify a turn as "health-interpretation" vs "conversational"? Three candidates: (a) system-prompt teaches self-classification; (b) post-hoc heuristic (any turn invoking `genomeclaw_*` tools); (b) the model exposes a per-turn `thinking` decision the agent makes explicitly. v0 default: **(a) — system-prompt classification**, with verification via execution-trace inspection in Phase 2 snapshot tests.
- **Q1b** *(added 2026-05-15)*: How does the agent decide when a memory note's validation check has failed? The system prompt teaches a structured 3-check protocol (conclusion-↔-source, source-quality, freshness). Phase 2 will iterate on the exact phrasing based on what trips snapshot tests; one open knob is how aggressive the validation should be — too lax fails to catch propagation; too strict turns every recall into a re-research, defeating the memory's purpose. Start conservative (lean toward re-research on borderline) and tune from observed snapshot behaviour.
- **Q2**: Should memory notes from health-interpretation turns be promoted to `MEMORY.md` more aggressively than the default dreaming pass would? *(Defaults to: no; let dreaming handle it.)*
- **Q3**: How does the agent decide a memory note is stale? *(Defaults to: 6 months age + user explicitly asking for an update. Tunable per-topic in a follow-up.)*
- **Q4**: Should the agent be allowed to use `web_search` to interpret a *finding* (which is host-data), or only to research *gene topics* (which is external knowledge)? *(Default: both; the boundary is "user-identifying payload never goes in the query".)*

## Success Metrics

- Story 9 (Caffeine + sleep) plays out end-to-end through the new pattern at gpt-5.5 reasoning=max on the synthesis turn.
- A second session a week later recalls the prior synthesis without re-research.
- INV-A001 + INV-A002 promoted into [INVARIANTS.md](../../reference/INVARIANTS.md) after Phase 2 tests pass.
- `reference/curated_notes/` directory and `gene_note:` / `topic:` evidence kinds removed from the codebase by Phase 1 close.

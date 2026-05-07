# Feature: MVP — End-to-end genome → agent loop

**Status**: Draft
**Created**: 2026-05-06
**Owner**: project owner
**Related Plans**: none yet

---

## Goal

Deliver the smallest end-to-end loop that lets a NemoClaw agent answer real questions about a real Nebula-derived genome — both clinical-track ("any actionable findings?") and lifestyle-track ("what does my genome say about caffeine?") — with all canonical `INV-xxx` invariants enforced.

## Background

The repo currently has docs, agents, plan templates, plugin scaffolding (manifest + policy preset + sandbox `Dockerfile` + TypeScript skeleton), and `INVARIANTS.md` v1.4. There is **no working host pipeline, no host service, and no live agent integration**. The MVP closes that gap.

Until the MVP lands, the project's claims (privacy-default, host/sandbox split, evidence-traced findings, lifestyle vs. clinical distinction) are aspirational. After the MVP, the project owner can use GenomeClaw daily over Telegram for the most common journeys covered in [user-stories.md](../../reference/user-stories.md) Stories 1–4, 6, and 9.

## Acceptance Criteria

- [ ] **AC1**: Running `genomeclaw-prep ingest` against a real Nebula 30× WGS VCF produces a populated derived store under `/mnt/genomeclaw/derived/<run-id>/` with all required provenance columns.
- [ ] **AC2**: The host service `genomeclaw-service` listens on `127.0.0.1:8643` and serves the v0 endpoints documented in [architecture.md](../../reference/architecture.md): `/v1/health`, `/v1/findings`, `/v1/findings/{id}`, `/v1/variants`, `/v1/variants/{key}`, `/v1/evidence/{ref}`, `/v1/provenance/{run-id}`. (Per Q3 decision below: no `/v1/report` endpoint in the MVP.)
- [ ] **AC3**: A sandbox image built from `packages/nemoclaw-plugin/sandbox/Dockerfile` and onboarded via `nemoclaw onboard --from <Dockerfile>` registers the four plugin tools (`genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`) and successfully reaches the host service via `host.openshell.internal`.
- [ ] **AC4**: The agent (in the project owner's NemoClaw sandbox, OpenAI gpt-5.4 over Telegram) can answer "any actionable findings?" with structured response carrying `clinical_escalation` markers and evidence references where appropriate.
- [ ] **AC5**: The agent can answer "what does my genome say about caffeine?" with **direct** lifestyle advice and an `evidence_quality` caveat — no clinician-deferral default (`INV-C001` lifestyle track).
- [ ] **AC6**: Default-config integration tests confirm no outbound call goes anywhere other than the configured agent endpoint and the configured host service.
- [ ] **AC7**: The pipeline is **deterministic**: a fresh ingest of the same VCF + same reference + same tool versions produces a byte-equivalent derived store.

## Applicable Invariants

All canonical invariants ([INVARIANTS.md](../../reference/INVARIANTS.md) v1.4) are exercised by the MVP. The MVP is the first place the project's invariant claims are made live.

- **INV-D001** — `genomeclaw-prep` writes only to `/mnt/genomeclaw/derived/`; raw paths are read-only by OS chmod and verified post-run.
- **INV-D002** — the sandbox image contains no bioinformatics tools; the policy preset whitelists only the host service host/port. Smoke test asserts both.
- **INV-E001** — every finding carries an evidence reference; the host service rejects findings without one.
- **INV-P001** — privacy-default tests cover the full agent flow with default config.
- **INV-P002** — host service shapes minimal-sufficient JSON; plugin re-shapes; OpenShell policy preset enforces the network floor with the RFC 1918 SSRF allowlist; tested with a live policy probe in the sandbox.
- **INV-R001** — every derived row carries the seven canonical provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`); determinism test runs the pipeline twice and diffs.
- **INV-C001** — finding schema has `category`, `clinical_escalation`, `evidence_quality`; lifestyle findings ship with non-empty `evidence_quality`; over-deferral and over-claim both fail snapshot tests.

## Proposed New Invariants

None. The MVP exercises the existing invariants; it does not propose new ones.

## Technical Requirements

### Source Data Inputs
- A real Nebula Genomics 30× WGS VCF (project-owner-provided).
- ClinVar release (downloaded by `genomeclaw-prep fetch --source clinvar`).
- gnomAD v4.1 (downloaded by `genomeclaw-prep fetch --source gnomad`).
- dbSNP build 156 (downloaded by `genomeclaw-prep fetch --source dbsnp`).
- GRCh38 reference.

### Derived Outputs
- DuckDB derived store under `/mnt/genomeclaw/derived/<run-id>/variants.duckdb`.
- `manifest.json` and `provenance.json` per run.
- A `CURRENT` symlink at `/mnt/genomeclaw/derived/CURRENT` pointing at the active run.

### Schema / Migration Impact
- Schema v0.1 defined in `packages/toolkit/src/genomeclaw_toolkit/schemas/`.
- Finding schema with `category` (`clinical-actionable | clinical-non-actionable | lifestyle | mixed`), `clinical_escalation`, and `evidence_quality` per `INV-C001` v1.4.

### Pipeline / Workflow Impact
- New host CLI: `genomeclaw-prep` with subcommands `fetch`, `ingest`, `normalize`, `annotate`, `materialize`.
- New host service: `genomeclaw-service` (FastAPI, Uvicorn).

### Agent / UX Impact
- Four plugin tools become callable agent tools after `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile`.
- The user can ask both clinical and lifestyle questions over Telegram.

### External Dependencies
- Host: `samtools`, `bcftools`, `tabix`, `bgzip`, `bedtools`, `SnpEff`, `SnpSift`.
- Host Python deps: `cyvcf2`, `pysam`, `duckdb`, `fastapi`, `uvicorn`, `pydantic`.
- Annotation data files (downloaded; never bundled).

## Privacy & Safety Considerations

- **Boundary scan**: the MVP introduces three network surfaces — agent → OpenAI (managed by OpenShell L7 proxy), plugin → host service (HTTP via `host.openshell.internal`), `genomeclaw-prep fetch` → annotation source URLs (host-side only, deliberate user invocation). Genomic source files traverse none of them.
- **Default-off remote calls**: only the configured agent provider is on by default. `genomeclaw-prep fetch` is a deliberate user-initiated command, not background.
- **Redaction surface**: host service responses are minimal-sufficient by construction; the plugin re-shapes; OpenShell L7 policy is the runtime floor.
- **Clinical escalation**: ACMG SF and PharmCAT actionable findings carry `clinical_escalation` markers. The initial MVP finding set is conservative — fewer than 5 categories — to keep manual review tractable.
- **Lifestyle / clinical separation**: lifestyle findings (Phase 6) carry non-empty `evidence_quality` and no `clinical_escalation`. Clinical findings carry the opposite. Snapshot tests enforce the partition.

## Out of Scope

The following are explicitly *not* part of the MVP. They live in later horizons.

- Reanalysis loop (Horizon 7).
- Local retrieval / embeddings (Horizon 8).
- Bulk transfer modes (`?class=bulk`) — wired in the schema, disabled at the host service.
- Optional remote integrations (PubMed lookup, alternative annotators).
- A standalone GUI; NemoClaw is the UI.
- Multi-genome / family support.
- Imputation.
- Reanalysis-diff endpoint.
- A complete lifestyle finding catalog. The MVP ships **one** lifestyle finding category: caffeine metabolism via *CYP1A2*. Lactase persistence, *ACTN3*, alcohol metabolism, chronotype, etc. are deferred to Horizon 6 follow-ups.

## Dependencies

- A working NemoClaw setup on the project owner's host (already in place — confirmed by the in-sandbox investigation in earlier sessions).
- A real Nebula 30× WGS VCF (project owner has it).
- Network access to ClinVar / gnomAD / dbSNP for `fetch`. One-time, deliberate.

## Decisions Taken

Decisions land here as the corresponding open question is worked through. Each entry records what was decided, why, and the conditions under which it should be revisited.

### Q1 — Annotator: SnpEff + SnpSift

**Decided**: 2026-05-06.

**Decision**: ship the MVP with **SnpEff + SnpSift** as the sole variant annotator. Effect predictions come from SnpEff; ClinVar / gnomAD / dbSNP joins come from SnpSift overlays of the local `reference/` caches.

**Rationale**: setup cost is the lowest of the three candidates — a single Java JAR vs. VEP's Perl + multi-GB cache, or vcfanno's join-only scope that would still require a second tool for effect predictions. Effect-annotation depth beyond what SnpEff provides is **not needed** under the generic-primitives + minimal-curation finding model: clinical reasoning leans on ClinVar pathogenicity (already overlaid by SnpSift), and lifestyle reasoning leans on genotype at known SNPs (which doesn't need effect prediction at all). VEP's plugin ecosystem is a Theme G concern, not an MVP concern.

**Revisit when**:
- Phase 4 fixture timings on the project owner's VCF exceed ~30 minutes (a vcfanno hybrid would be the fix).
- The agent flubs answers because SnpEff's canonical-transcript choice produces wrong-gene effects (VEP would be the fix).
- A specific ClinVar / gnomAD / dbSNP field we need is inaccessible via SnpSift (vcfanno or a VEP plugin would be the fix).

**Affected files**: [development-plan.md](development-plan.md) Phase 4 (already names SnpEff + SnpSift); no other doc changes.

### Q2 — Plugin tool surface: `registerTool` (not `registerCommand`)

**Decided**: 2026-05-06.

**Decision**: register the four GenomeClaw tools (`genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`) with OpenClaw's **`registerTool`** API, using **TypeBox schemas** for parameters and **`jsonResult(payload)`** for return values. Drop the v0 `GENOMECLAW_JSON: <json>` text-encoding entirely; drop the `parseArgs` `key=value` parser. (Per Q3: `genomeclaw_report` is dropped from the MVP tool set.)

**Rationale**: an in-sandbox investigation of the installed `openclaw/plugin-sdk` (v 2026.4.24) showed that `registerCommand` is documented as bypassing the LLM agent — it builds **chat slash commands**, not agent-callable tools. Plugin-command results return as `ReplyPayload` to the channel, never landing in an OpenAI-style `tool_result` envelope. The published agent-tool API is `registerTool`, which accepts a TypeBox-typed `parameters` schema and an `execute(...)` returning `AgentToolResult<TDetails>`. Helper `jsonResult(payload)` builds the result envelope by JSON-pretty-printing into `content[{type:'text', text}]` while preserving the structured object in `details`. The LLM-visible side is text (pretty-printed JSON in a text block), but modern LLMs parse this trivially and the structured `details` is preserved for runtime consumers.

**Caveat**: even with `registerTool`, the LLM-visible content is still text. Tool results must remain machine-friendly and concise even with structured `details`. We treat `details` as supplemental, not as a guaranteed first-class structured channel to the LLM.

**Revisit when**:
- OpenClaw exposes a richer LLM-facing structured-content channel (parallel to the MCP `structuredContent` path, but for first-party `registerTool`).
- A specific lifestyle / clinical question fails because the LLM mis-parses a JSON return — would prompt review of the result-shaping conventions.

**Affected files**:
- [packages/nemoclaw-plugin/src/index.ts](../../../packages/nemoclaw-plugin/src/index.ts) — substantial rewrite (Phase 5 deliverable): replace `registerCommand` calls with `registerTool`, add TypeBox parameter schemas, swap text-encoding helpers for `jsonResult`. Drop `parseArgs` and the `GENOMECLAW_JSON:` / `GENOMECLAW_ERROR:` markers.
- [packages/nemoclaw-plugin/package.json](../../../packages/nemoclaw-plugin/package.json) — add `@sinclair/typebox` dependency.
- [development-plan.md](development-plan.md) — Phase 5 deliverables include the `registerTool` migration explicitly.
- [docs/reference/user-stories.md](../../reference/user-stories.md) — note the resolution in the running gap-analysis.

---

### Q3 — Defer `/v1/report` entirely

**Decided**: 2026-05-06.

**Decision**: the MVP ships **without** a `/v1/report` endpoint and **without** a `genomeclaw_report` plugin tool. The agent assembles reports from `/v1/findings` + `/v1/health` + its own framing knowledge. Plugin tool count drops from five to four.

**Rationale**: a server-side report-skeleton endpoint reintroduces the curation we cut at Q1 (generic primitives + minimal curation). The agent already had everything it needed in Stories 4, 6, and 9 — the `genomeclaw_report` tool calls in those stories were redundant with the `genomeclaw_findings` calls that preceded them. Forbidden-phrase enforcement (`INV-C001`) lands at the plugin tool descriptions + agent prompt template layer, where it already sits. Section breakdown / triage rules belong in the agent's prompt + reasoning, not in host-service code.

**Revisit when**:
- The agent triages reports inconsistently turn-to-turn in a way fixture tests can't catch.
- A persistable, printable report artifact (Markdown or PDF) becomes a real user need that the agent's prose can't satisfy.
- The set of report scopes grows large enough that prompt-side enforcement becomes brittle.

**Affected files**:
- This spec — AC2 endpoint list, AC3 tool count, Technical Requirements tool count (all done above).
- [development-plan.md](development-plan.md) — Phase 5 (four-tool migration), Phase 6 (drop `/v1/report` deliverable + scopes), Testing Strategy (Report Rendering Tests reframed as agent-output snapshots).
- [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) `INV-C001` "Where it applies" — drop the `genomeclaw_report` tool reference.
- [docs/reference/architecture.md](../../reference/architecture.md) — drop `genomeclaw_report` from the layered diagram's tool list.
- [docs/reference/user-stories.md](../../reference/user-stories.md) — Profile 2 tool list, Story 6 tool calls, gap-analysis items A1 / A5 / Story-4-handoff-pattern / Story-9-experiment-template / Plan-section.
- [packages/nemoclaw-plugin/src/index.ts](../../../packages/nemoclaw-plugin/src/index.ts) — drop the `genomeclaw_report` registration block and banner line.
- [packages/nemoclaw-plugin/README.md](../../../packages/nemoclaw-plugin/README.md) — drop `genomeclaw_report` from the tool table and banner.

---

### Q4 — Multi-gene queries: typed array `genes: string[]`

**Decided**: 2026-05-06.

**Decision**: filter-by-collection tools (`genomeclaw_findings` and any future tool of the same shape) accept **typed array** parameters — `genes: string[]`, `drugs: string[]`, `rsids: string[]` — using TypeBox `Type.Array(Type.String(), { minItems: 1 })`. Single-record lookup tools (`genomeclaw_variant`, `genomeclaw_evidence`) keep scalar `key: string` / `ref: string` parameters because they return one record.

The host-service URL pattern for arrays is **repeated query parameters** (`/v1/findings?category=lifestyle&genes=PER3&genes=CLOCK&genes=ADORA2A`), backed by FastAPI's `genes: list[str] | None = Query(default=None)`. Empty arrays are rejected with a clear error; missing parameters mean "no filter" where that makes sense.

**Rationale**: Q1's generic-primitives + minimal-curation stance puts the gene→topic map in the agent's training (no `topic=` parameter — the host service should not own a curated topic→gene map that duplicates the agent's training). Q2's `registerTool` + TypeBox decision rejects stringified blobs (no comma-separated string parsed server-side). That leaves single-gene-per-call vs. typed array. Typed array wins on three counts: latency (one round trip per logical question, fitting Telegram-conversational expectations), idiomatic fit (TypeBox arrays + repeated query params are FastAPI-natural), and host-side cleanliness (`WHERE gene IN (?, ?)` instead of brittle string-split).

**Revisit when**:
- The LLM struggles to construct array parameters reliably (extremely unlikely with modern tool-use protocols).
- A curated topic catalog earns its keep — e.g., a "what's interesting in my genome?" discovery surface for someone who isn't sure what to ask first.
- URL length becomes a real constraint, in which case the host service adds a POST variant for the same endpoint.

**Affected files**:
- This spec (Q4 in Decisions Taken; Open Questions section now empty).
- [development-plan.md](development-plan.md) Phase 5 deliverables — TypeBox schema spelled out with `Type.Array(Type.String(), { minItems: 1 })`.
- [docs/reference/architecture.md](../../reference/architecture.md) Component 2 endpoint sketch — `/v1/findings` query parameters listed explicitly.
- [docs/reference/user-stories.md](../../reference/user-stories.md) Stories 3, 4, 9 tool-call lines updated to typed-array syntax; gap-analysis items A3 (drug-keyed PGx), A10 (lifestyle category), A12 (topic-keyed) marked ✅ Resolved; Plan section bullets updated.
- [packages/nemoclaw-plugin/README.md](../../../packages/nemoclaw-plugin/README.md) tool table updated to `genes=[...]`, `drugs=[...]`.

---

## Open Questions

All MVP open questions are resolved as of 2026-05-06. New design questions surfaced during implementation should land here as they appear, then move to Decisions Taken once resolved.

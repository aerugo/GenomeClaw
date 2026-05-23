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

- [ ] **AC1**: Running `genomeclaw-prep ingest` against a real Nebula 30× WGS VCF + BAM/CRAM produces a populated derived store under `/mnt/genomeclaw/derived/<run-id>/` with all required provenance columns, including the `coverage_qc` table populated by `mosdepth` (per Q7).
- [ ] **AC2**: The host service `genomeclaw-service` listens on `127.0.0.1:8643` and serves the v0 endpoints documented in [architecture.md](../../reference/architecture.md): `/v1/health`, `/v1/findings`, `/v1/findings/{id}`, `/v1/variants`, `/v1/variants/{key}`, `/v1/evidence/{ref}`, `/v1/provenance/{run-id}`, **`/v1/gene/{symbol}`** (per Q7), **`/v1/pgs/{trait}`** (per Q8). (Per Q3 decision: no `/v1/report` endpoint in the MVP.)
- [ ] **AC3**: A sandbox image built from `packages/nemoclaw-plugin/sandbox/Dockerfile` and onboarded via `nemoclaw onboard --from <Dockerfile>` registers the **six** plugin tools (`genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, **`genomeclaw_gene`**, **`genomeclaw_pgs`**) and successfully reaches the host service via `host.openshell.internal`.
- [ ] **AC4**: The agent (in the project owner's NemoClaw sandbox, OpenAI gpt-5.4 over Telegram) can answer "any actionable findings?" with structured response carrying `clinical_escalation` markers and evidence references where appropriate. PGx-flavored sub-questions resolve against the Cyrius diplotype + PharmCAT outside-call path (per Q6).
- [ ] **AC5** *(revised 2026-05-15; supersedes the Q9 curated-notes version)*: The agent can answer "what does my genome say about caffeine?" using the **research-and-synthesis pattern** *(per [agent-research-and-synthesis spec](../agent-research-and-synthesis/spec.md), [INVARIANTS v1.8](../../reference/INVARIANTS.md) `INV-C001` v1.6 + `INV-A001` + `INV-A002`)*: (a) `memory_search` for prior synthesis on the topic, (b) `genomeclaw_variant` for the user's diagnostic-SNP genotype, (c) reasoned research over the model's training knowledge + current online sources via `web_search`, (d) **synthesis at the maximum reasoning level the configured model supports** (`INV-A002` — bioinformatician-in-healthcare turn), (e) **a structured memory note written before the reply** (`INV-A001`), (f) **direct** lifestyle guidance — no clinician-deferral default.
- [ ] **AC6** *(revised 2026-05-15)*: Default-config integration tests confirm `tools.web.search.enabled` is **`false`** by default in the sandbox image's openclaw.json and that no outbound call goes anywhere other than the configured agent endpoint and the configured host service. Opt-in tests with `tools.web.search.enabled: true` confirm the web_search query payload contains only topic-term strings — never rsids, gene symbols from the user's variants, sample ids, or genotype strings. The PGS Catalog fetch (per Q8) is host-side, opt-in, and not exercised by default-config tests.
- [ ] **AC7**: The pipeline is **deterministic**: a fresh ingest of the same VCF + same reference + same tool versions produces a byte-equivalent derived store.
- [ ] **AC8**: A fresh `genomeclaw-prep ingest` populates the **`coverage_qc` table** under `/mnt/genomeclaw/derived/<run-id>/` with **one row per gene in the genome** (gene-level mean coverage from `mosdepth` against a comprehensive gene BED — e.g., the MANE Select transcript set; the per-gene layer is **uncurated by design**, so `genomeclaw_gene` and `/v1/gene/{symbol}` serve any gene the agent asks about). **Per-exon** mean coverage is materialized only for a **curated subset of clinically important genes** (ACMG SF + PharmCAT pharmacogenes + the Q9 lifestyle shortlist), feeding the `low_coverage_exons` field on `/v1/gene/{symbol}`. `mean_depth` is a non-negative real on every row; the seven canonical provenance columns are populated on every row (per Q7).
- [ ] **AC9** *(revised 2026-05-17; supersedes the v1.5 fixed-three-trait formulation per Q8 v1.6 + [agent-driven PRS report](../../../reports/agent-driven-prs-computation.md))*: PRS is **agent-driven, host-computed, memory-cached**. There is **no pre-staged trait panel**. An agent-triggered `genomeclaw_pgs_compute` invocation (the agent picked a PGS Catalog ID after reasoning at `INV-A002` ceiling over PGS Catalog metadata + recent literature) drives a host-side `pgsc_calc` run + populates one row in the **`pgs_scores` table** keyed by PGS Catalog ID. Each row carries: `percentile_in_user_ancestry`, `raw_score`, `source_pgs_id`, `study_population`, `calibration_warning`, **`agent_choice_rationale`** (per `INV-A003` — the agent's reasoning for picking this scorefile + alternatives considered), **`requested_for_question`** (the verbatim user question that triggered the compute), and the seven canonical provenance columns. The compute is async + bounded by a host-side concurrency cap (1 in-flight) + a kill-switch (`genomeclaw config set pgs.compute_enabled false` revokes the path entirely). The agent **declines** to compute when the literature is too immature (per the `INV-C001` v1.7 PRS-decline pattern — two named reasons from the four-criteria set); the decline is itself persisted as a memory note for future-session reuse. The host-service surface is four endpoints — `/v1/pgs/computed` (list), `/v1/pgs/computed/{pgs_id}` (get), `POST /v1/pgs/compute` (request), `/v1/pgs/compute/{task_id}` (status) — replacing the v1.5 single `/v1/pgs/{trait}` endpoint.
- [ ] **AC10** *(revised 2026-05-15; supersedes the Q9 curated-notes resolver)*: The host service evidence resolver accepts **variant-keyed reference kinds only**: `clinvar:<id>`, `pgs_catalog:<id>`, `pharmgkb:<id>`. The `gene_note:<gene>` and `topic:<topic>` kinds previously documented under Q9 are **retired** *(per [INVARIANTS v1.8](../../reference/INVARIANTS.md) `INV-C001` v1.6 + the [agent-research-and-synthesis plan](../agent-research-and-synthesis/spec.md))*; lifestyle calibration now flows through agent memory + reasoned research, not host-side curated markdown. Agent-side citation forms (`memory:<file>#<anchor>` and `web:<url>`) are sandbox-workspace concerns; the host service does not resolve them.
- [ ] **AC13** *(new, 2026-05-15)*: A second session asking the same lifestyle question (e.g., a follow-up about caffeine + sleep a week later) shows `memory_search` hits the prior synthesis without a fresh `web_search` call — unless the user explicitly asks for an update or the memory note is past its freshness date.
- [ ] **AC14** *(new, 2026-05-15)*: A health-interpretation turn (any reply that interprets the user's genomic data or gives guidance the user might plausibly act on) is composed at the maximum reasoning level the configured model supports. Verified by inspection of `executionTrace.thinking` in live-LLM snapshot tests over Stories 4 / 9 / 10. Non-interpretation turns (recall, scheduling, casual back-and-forth) are exempt; the floor does not over-apply.
- [ ] **AC11**: A fresh ingest invokes **Cyrius** against the BAM/CRAM and writes the resulting CYP2D6 diplotype as `derived/<run-id>/cyp2d6_diplotype.json`; the diplotype is consumed by PharmCAT's outside-call interface in the `annotate` step (per Q6).
- [ ] **AC12**: A fresh ingest invokes **`bcftools stats`** against the input VCF and writes the summary into `manifest.json` under `qc.bcftools_stats`; **`mosdepth`** is invoked against the BAM/CRAM read-only (BAM SHA256 unchanged post-run, `INV-D001`).

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
- A real Nebula Genomics 30× WGS BAM/CRAM (project-owner-provided; needed for `mosdepth` per Q7 and Cyrius per Q6).
- ClinVar release (downloaded by `genomeclaw-prep fetch --source clinvar`).
- gnomAD v4 with per-population allele frequencies (downloaded by `genomeclaw-prep fetch --source gnomad`; per Q5).
- dbSNP build 156 (downloaded by `genomeclaw-prep fetch --source dbsnp`).
- GRCh38 reference.
- VEP cache + LOFTEE + AlphaMissense data files (host-installed; per Q5; SpliceAI dropped 2026-05-13 per Q5 amendment).
- **gnomAD constraint metrics (`gnomad-constraint` v4.1)** — per-transcript LOEUF / pLI scores; used at materialize time to populate `gene_loeuf` from the canonical-transcript gene symbol VEP extracts (added 2026-05-13).
- PGS Catalog scoring weights for the three initial traits (downloaded host-side by `pgsc_calc` on user invocation; per Q8).

### Derived Outputs
- DuckDB derived store under `/mnt/genomeclaw/derived/<run-id>/variants.duckdb` with the canonical `variants` table plus annotation columns from Q5 (MANE Select HGVSc/HGVSp, AlphaMissense score+class, LOFTEE flag, gnomAD per-ancestry AFs, gene LOEUF). (SpliceAI max delta dropped 2026-05-13.)
- **`coverage_qc` table** in the derived store with per-gene mean coverage from `mosdepth` (per Q7).
- **`pgs_scores` table** in the derived store with rows for the three initial traits (per Q8).
- **`cyp2d6_diplotype.json`** per run with the Cyrius diplotype call (per Q6).
- `manifest.json` and `provenance.json` per run; `manifest.json` includes a `qc.bcftools_stats` block (per Q5/Phase 2).
- A `CURRENT` symlink at `/mnt/genomeclaw/derived/CURRENT` pointing at the active run.
- ~~`reference/curated_notes/<gene>.md` files~~ — **retired in v1.6** (per [Q9 revised](#q9--lifestyle-calibration-via-referencecurated_notes-via-agent-research-and-synthesis); lifestyle calibration moves to agent memory + reasoned research per [agent-research-and-synthesis plan](../agent-research-and-synthesis/spec.md)).

### Schema / Migration Impact
- Schema **v0.1** defined in `packages/toolkit/src/genomeclaw_toolkit/schemas/` (Phase 2/3 deliverable).
- Schema **v0.2** reserved for the Q5/Q7/Q8 additions: VEP-stack annotation columns on `variants`, plus the new `coverage_qc` and `pgs_scores` tables. Phase 4/6 of the MVP plan lands the bump.
- Finding schema with `category` (`clinical-actionable | clinical-non-actionable | lifestyle | mixed`), `clinical_escalation`, and `evidence_quality` per `INV-C001` v1.4 (preserved for future-proofing per Q9; not the primary lifestyle calibration surface).

### Pipeline / Workflow Impact
- New host CLI: `genomeclaw-prep` with subcommands `fetch`, `ingest`, `normalize`, `annotate`, `materialize`, plus Phase-6-owned subcommands for Cyrius (`cyp2d6-call`) and `pgsc_calc` (`pgs-compute`).
- `ingest` invokes `bcftools stats` (summary into manifest) and `mosdepth` (writes `coverage_qc`) per Q7 and Phase 2 deliverables 5/6.
- `annotate` runs **VEP + LOFTEE + AlphaMissense + vcfanno** (per Q5; SpliceAI dropped 2026-05-13), pinning **MANE Select** as the reporting transcript; HGVSc/HGVSp emitted server-side. `gene_loeuf` is populated at materialize time from gnomAD constraint v4.1.
- New host service: `genomeclaw-service` (FastAPI, Uvicorn) with the endpoint set from AC2.

### Agent / UX Impact
- **Six** plugin tools (per Q7/Q8) become callable agent tools after `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile`: `genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_gene`, `genomeclaw_pgs`.
- The user can ask clinical, PGx, lifestyle, and PRS questions over Telegram.
- Lifestyle question handling follows the **agent research-and-synthesis pattern** *(v1.6; per [agent-research-and-synthesis plan](../agent-research-and-synthesis/spec.md))*: `memory_search` → `genomeclaw_variant` → reasoned `web_search` + training-knowledge research → synthesis at the configured model's maximum reasoning (`INV-A002`) → structured memory note (`INV-A001`) → reply with verbatim citations.
- Coverage-aware false-reassurance prevention: the agent reads `mean_coverage` and `low_coverage_exons` from `genomeclaw_gene` and includes them naturally in negative answers (per Q7).

### External Dependencies
- Host: `samtools`, `bcftools` (incl. `bcftools stats`), `tabix`, `bgzip`, `bedtools`, **`mosdepth`** (per Q7), **VEP + LOFTEE + AlphaMissense + vcfanno** (per Q5; SpliceAI dropped 2026-05-13), **Cyrius** (per Q6), **`pgsc_calc`** Nextflow pipeline (per Q8), **PharmCAT** (per Q6 outside-call interface).
- Host Python deps: `cyvcf2`, `pysam`, `duckdb`, `fastapi`, `uvicorn`, `pydantic`.
- Annotation + scoring data files (downloaded; never bundled): VEP cache, LOFTEE data, AlphaMissense data, **gnomAD constraint v4.1** (per-transcript LOEUF / pLI), ClinVar, gnomAD v4 exomes, dbSNP, PGS Catalog scoring weights for the three initial traits. (SpliceAI data dropped 2026-05-13.)
- **Superseded by Q5**: SnpEff + SnpSift. The host can have them installed for ad-hoc use; they are no longer the default annotation path.

## Privacy & Safety Considerations

- **Boundary scan**: the MVP introduces **four** network surfaces — agent → OpenAI (managed by OpenShell L7 proxy), plugin → host service (HTTP via `host.openshell.internal`), `genomeclaw-prep fetch` → annotation source URLs (host-side only, deliberate user invocation), and **`pgsc_calc` → PGS Catalog** (host-side, deliberate, opt-in; per Q8). Genomic source files traverse none of them.
- **Default-off remote calls**: only the configured agent provider is on by default. `genomeclaw-prep fetch` and `pgsc_calc` weight-fetches are deliberate user-initiated commands, not background. Same discipline (host-side, deliberate) governs both.
- **Redaction surface**: host service responses are minimal-sufficient by construction; the plugin re-shapes; OpenShell L7 policy is the runtime floor. The two new tools (`genomeclaw_gene`, `genomeclaw_pgs`) inherit `output_class: summary` (`INV-P002`); their response shapes are enumerated in Q7/Q8 and never include raw PGS variant lists or per-variant coverage dumps.
- **Clinical escalation**: ACMG SF and PharmCAT actionable findings carry `clinical_escalation` markers. PGx findings sourced from the Cyrius + PharmCAT outside-call path (per Q6) flow through this same pathway. The initial MVP finding set is conservative — fewer than 5 categories — to keep manual review tractable.
- **PRS findings classification**: PRS findings (per Q8) carry `category: clinical-non-actionable` (population-level percentile estimates, not pathogenic variant calls); they do **not** carry a `clinical_escalation` marker. The `calibration_warning` string makes ancestry-normalization explicit when the user's continuous-ancestry estimate falls in a region with sparse training data.
- **Lifestyle / clinical separation** *(v1.6)*: lifestyle findings (Phase 6) are calibrated via the **agent research-and-synthesis pattern** (per [agent-research-and-synthesis plan](../agent-research-and-synthesis/spec.md), `INV-C001` v1.6 + `INV-A001` + `INV-A002` in [INVARIANTS.md v1.8](../../reference/INVARIANTS.md)). Each lifestyle finding cites a `memory:<id>` or `web:<url>` evidence reference; over-deferral and over-claim both fail snapshot tests. The structured `evidence_quality` field is preserved in the schema for future-proofing.
- **Agent system prompt is the user-facing-copy surface** *(v1.6)*: the prompt teaching the research-and-synthesis protocol + memory-note schema is what the `privacy-safety-reviewer` agent reviews. Memory notes themselves accumulate inside the sandbox and are user-inspectable via `memory_get`; they are not reviewed per-note.

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
- ~~A complete lifestyle finding catalog. The MVP ships **one** lifestyle finding category: caffeine metabolism via *CYP1A2*.~~ ~~**Updated by Q9.** The MVP ships **seven** lifestyle finding categories...~~ **Updated by Q9-revised (v1.6, 2026-05-15)**: there is no pre-defined lifestyle gene shortlist. The MVP ships the **agent research-and-synthesis pattern** which handles lifestyle questions for any gene the user asks about, via memory + reasoned research at max reasoning. The long-tail of gene questions ("anything about ABCG2 + uric acid?") works through the same path as the canonical ones.
- **PER3, CLOCK, and ACTN3 stay out of the lifestyle track** *(v1.6: still out, but on different grounds)* — the agent declines on each ask with specific reasons (repeated non-replication, unreliable VNTR genotyping on short-read WGS, elite-cohort effects not transferring), not on a curation-list basis. The decline is part of the synthesis at max reasoning.
- HLA typing (T1K), structural-variant calling (Manta), repeat expansions (ExpansionHunter), mt-aware mtDNA calling (mity), population-specific reference panels, automated ACMG/AMP rule classifiers (InterVar, Genebe), schema-enforced citation stripping, tool-use forcing, deterministic server-rendered findings cards, phrasing templates for high-risk categories, eval harness with synthetic test cases, additional PRS traits beyond the initial three, quarterly automated reanalysis, and additional vcfanno sources (OMIM, ClinGen Gene-Disease Validity, dbNSFP, MaxEntScan, UTRannotator) — all **deferred under Q10's defer-by-default discipline**, each with a specific trigger condition.

## Dependencies

- A working NemoClaw setup on the project owner's host (already in place — confirmed by the in-sandbox investigation in earlier sessions).
- A real Nebula 30× WGS VCF (project owner has it).
- Network access to ClinVar / gnomAD / dbSNP for `fetch`. One-time, deliberate.

## Decisions Taken

Decisions land here as the corresponding open question is worked through. Each entry records what was decided, why, and the conditions under which it should be revisited.

### Q1 — Annotator: SnpEff + SnpSift

**Decided**: 2026-05-06.

**Superseded by Q5 on 2026-05-08.** SnpEff was chosen for setup-cost reasons; the [POC pipeline recommendations report](../../completed/poc-pipeline-recommendations/work-notes.md#archive--source-recommendations-report) demonstrates that SnpEff's pathogenicity-call divergence from VEP is large enough to make clinical-track findings unsafe (independent benchmarks: LoF-prediction concordance 65–44% under different transcript sets; ~67% incorrect downgrades of pathogenic / likely-pathogenic variants in standardized testing). The original Q1 rationale is preserved verbatim below for historical clarity; the new annotator stack is documented in Q5.

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

### Q5 — Annotator stack: VEP + LOFTEE + AlphaMissense + vcfanno + gnomAD constraint (supersedes Q1)

**Decided**: 2026-05-08. **Amended 2026-05-13** — SpliceAI dropped from the default stack; gnomAD constraint v4.1 added as the canonical source for `gene_loeuf`. See "Amendment 2026-05-13" below.

**Decision**: ship the MVP with **VEP** as the variant annotator, augmented with **LOFTEE** (predicted-LoF confidence filter), **AlphaMissense** (missense pathogenicity), and **SpliceAI** (splice-altering variant predictor). **MANE Select** is the default reporting transcript; HGVSc and HGVSp are emitted server-side, never constructed by the LLM. **vcfanno** stamps tabix-indexed annotations onto the VCF for ClinVar (latest release) and gnomAD v4 (with per-population AFs). Q1's SnpEff + SnpSift stack is superseded.

**Rationale**: independent benchmarks comparing SnpEff, VEP, and ANNOVAR on curated truth sets show LoF-prediction concordance falling to 65–44% when transcript sets differ between tools, and standardized testing finds SnpEff incorrectly downgrades ~67% of pathogenic / likely-pathogenic variants. For an agent that emits clinical-track findings with `clinical_escalation` markers, this rate of disagreement with the clinical-grade reference standard is unsafe (`INV-C001`). VEP + LOFTEE + AlphaMissense + SpliceAI is the smallest stack that closes the gap; vcfanno fills in ClinVar + gnomAD without requiring SnpSift's ad-hoc joins. LOFTEE's 2023 curation study found ~67% of "high-confidence" heterozygous predicted-LoF variants in dominant disease genes were not actually LoF after manual review — i.e., LOFTEE is the *floor* on LoF filtering, not the ceiling.

**Schema additions** (land in Phase 4): zygosity, depth (DP), allele balance, FILTER, ClinVar classification + review status, gnomAD popmax + per-ancestry AFs, gene LOEUF, MANE Select HGVSc and HGVSp, AlphaMissense score + class, ~~SpliceAI max delta~~ *(dropped 2026-05-13)*, LOFTEE high-confidence flag.

**Out of scope for Q5**: dbNSFP (REVEL / CADD / PrimateAI), MaxEntScan, UTRannotator, automated ACMG/AMP rule classifiers (InterVar, Genebe). These are deferred under Q10's defer-by-default discipline.

#### Amendment 2026-05-13 — SpliceAI dropped; gnomAD constraint added

**What changed**: SpliceAI is removed from the default Phase-4D annotation stack. gnomAD constraint v4.1 (per-transcript LOEUF / pLI) is added as a small (~1–2 MB TSV) fetch source consumed at materialize time to populate `gene_loeuf`.

**Why**: a researcher-confirmed-defaults review (commit fd835fb, 2026-05-13) found SpliceAI's ~50 GB dataset footprint and per-variant scoring cost are disproportionate to the MVP's tool surface — none of the six v0 plugin tools surface splice-impact predictions directly, and ACMG-relevant splice variants are already covered indirectly via ClinVar pathogenic / likely-pathogenic classifications. Dropping SpliceAI eliminates ~50 GB of reference storage and shaves an estimated 30–60 min off the 4D real-data smoke wall time without losing a tool-surfaced capability. gnomAD constraint is the source the original Q5 plan vaguely referred to as "dedicated LOEUF source"; making it explicit closes that ambiguity.

**Schema impact**: the planned `spliceai_max_delta` column does NOT land. The planned `gene_loeuf` column lands as documented but is populated via a materialize-time join against gnomAD constraint, not from VEP's `--af_gnomadg` flag.

**Trigger to revisit**: a user-stated need for splice-impact reasoning that ClinVar alone can't satisfy — e.g., a VUS in a splice region where the question is "could this be splice-altering?" At that point SpliceAI returns as a deferred-feature add per Q10's defer-by-default discipline.

**Affected files (this revision)**: [development-plan.md](development-plan.md) §"Key Design Decisions" #3 + §"Schema / Provenance Impact"; [phases/phase-4.md](phases/phase-4.md) throughout sub-phase 4D; [phases/phase-4-completion.md](phases/phase-4-completion.md) §W5.

**Revisit when**:
- Phase 4 fixture timings on the project owner's VCF exceed the personal-host budget (~30 min/genome target). Mitigation candidate: drop AlphaMissense data files to a smaller subset, or pre-filter against gnomAD AF before running plugins.
- The agent flubs answers because MANE Select's transcript choice produces wrong-gene effects for a specific gene — would prompt review of transcript-pinning policy.
- A specific ClinVar / gnomAD field we need is inaccessible via vcfanno — would prompt a VEP plugin add.

**Affected files**:
- [development-plan.md](development-plan.md) Phase 4 — rewritten in Phase 4 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md).
- [docs/reference/architecture.md](../../reference/architecture.md) Component 1 description — updated in Phase 2 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md).
- [docs/reference/grand-plan.md](../../reference/grand-plan.md) Theme B + Decisions Taken — updated in Phase 3.

---

### Q6 — CYP2D6 outside-call via Cyrius into PharmCAT

**Decided**: 2026-05-08.

**Decision**: invoke **Cyrius** (Illumina) at ingest against the BAM/CRAM, produce a star-allele diplotype, and feed it into **PharmCAT's outside-call interface**. CYP2D6 is **not** called from the VCF (PharmCAT explicitly does not support this; the official documentation directs users to provide an outside-call diplotype).

**Rationale**: CYP2D6 metabolizes ~25% of clinically prescribed drugs (codeine, tramadol, oxycodone, tamoxifen, many antidepressants, antipsychotics). It is genetically complex (>130 star alleles, copy-number variation, hybrid alleles with the CYP2D7 pseudogene); standard small-variant callers fail at the locus because of 94% sequence homology with CYP2D7. Independent benchmarking on the GeT-RM truth set: Cyrius 96.5–99.3% overall concordance, vs. Aldy 86.8–92.2% and Stargazer 84.0%. Without Cyrius, the PGx track of the agent (`INV-C001` clinical-track) is unsafe for any CYP2D6-relevant prescription — and the next user follow-up after Story 4's clopidogrel question is exactly that class of question (codeine, SSRIs, tamoxifen).

**Implementation cost**: one extra host-side container or Python tool; ~50 lines of glue to feed the diplotype into PharmCAT. Host-side only (`INV-D002`); BAM read-only (`INV-D001`); diplotype JSON lands under `derived/<run-id>/cyp2d6_diplotype.json` with the seven canonical provenance columns reflected in the manifest.

**Revisit when**:
- Cyrius's GeT-RM concordance drops in a future release (revisit tool choice; Aldy is the next candidate).
- A CYP2D6 hybrid allele observed in the user's BAM is not in Cyrius's call set (revisit; possibly run Aldy as a cross-check).

**Affected files**:
- [development-plan.md](development-plan.md) Phase 6 — updated in Phase 4 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md).
- [docs/reference/architecture.md](../../reference/architecture.md) Component 1 description, data layout — updated in Phase 2.
- [docs/reference/grand-plan.md](../../reference/grand-plan.md) Theme G — updated in Phase 3.
- [docs/reference/user-stories.md](../../reference/user-stories.md) Story 4 — updated in Phase 3.

---

### Q7 — Coverage-aware gene queries: mosdepth + genomeclaw_gene (5th tool)

**Decided**: 2026-05-08.

**Decision**: add **`mosdepth`** to the ingest pipeline (Phase 2 deliverable per Phase 4 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md)); materialize a **`coverage_qc` table** in the derived store with per-gene mean coverage (and per-exon mean coverage for a curated set of clinically important genes). Add **`genomeclaw_gene`** to the plugin tool surface (5th tool; tool count 4 → 5). The host service exposes a new endpoint **`GET /v1/gene/{symbol}`** returning `{top_user_variants, gene_loeuf, omim_disease, omim_inheritance, mean_coverage, low_coverage_exons}`. `mean_coverage` is a scalar (number, scaled to 1× depth); `low_coverage_exons` is a list of exon IDs whose mean depth fell below a configurable threshold (default 10×).

**Rationale**: the most dangerous failure mode of a personal genomic agent is **false reassurance** — "you don't have a pathogenic *BRCA1* variant" when the relevant exon wasn't covered. Short-read 30× WGS systematically miscalls or misses variants in regions including PMS2, GBA, CYP21A2, SMN1, STRC, NCF1, HBA1/HBA2, IKBKG, CYP2D6, and the HLA region; even in well-behaved genes, individual exons can fall below confidence thresholds. The agent reads `mean_coverage` and `low_coverage_exons` and includes them naturally in negative answers ("no pathogenic *BRCA1* variants in your callset; mean coverage of *BRCA1* averaged 28×, which is adequate" — or, conversely, "but exon 11 averaged 4×, below the threshold for confident calls; clinical confirmation would require targeted Sanger sequencing"). One number, one tool, most of the false-reassurance failure mode addressed.

**Tool shape** (TypeBox; reflects Q2 `registerTool` + Q4 typed-array conventions):
- `genomeclaw_gene` — `Type.Object({ gene: Type.String({ minLength: 1 }) })` (single-record lookup; scalar param).
- `output_class: summary` (`INV-P002` default; minimal-sufficient response shape enumerated above).

**Companion: agent reasoning about hard-genes** *(revised v1.6)*. The systematic-blind-spot caveat (PMS2, GBA, CYP21A2, SMN1, etc.) lives in the agent's accumulated research memory + the model's training knowledge, not in a pre-authored `reference/curated_notes/topics/hard-genes.md` file. The agent reaches for this caveat naturally when a query touches a known-hard gene; the calibration emerges from the agent's research-and-synthesis pattern (`INV-C001` v1.6 + `INV-A002`). A `topic:hard-genes` evidence-resolver path is no longer planned.

**Revisit when**:
- The user repeatedly asks coverage-related follow-ups that `mean_coverage` alone can't answer (revisit: per-exon coverage table, per-region mappability scores).
- A gene's coverage table is consistently misleading because of repetitive regions (revisit: report mappability alongside coverage).

**Affected files**:
- [development-plan.md](development-plan.md) Phase 5 — updated in Phase 4 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md) (adds `genomeclaw_gene` deliverable).
- [phases/phase-2.md](phases/phase-2.md) — updated in Phase 4 (adds `mosdepth` deliverable + 3 test cases).
- [docs/reference/architecture.md](../../reference/architecture.md) Component 2 endpoint list, plugin tool table, data layout — updated in Phase 2.
- [docs/reference/user-stories.md](../../reference/user-stories.md) Story 3 — updated in Phase 3 (BRCA1 answer references coverage from `genomeclaw_gene`).

---

### Q8 — PRS via pgsc_calc — ~~fixed three-trait panel + `genomeclaw_pgs` (6th tool)~~ → agent-driven, four-tool surface, no pre-curated panel

**Decided**: 2026-05-08. **Revised v1.6: 2026-05-17** *(supersedes the v1.5 fixed-panel design; per [agent-driven PRS report](../../../reports/agent-driven-prs-computation.md))*.

#### v1.6 amendment (2026-05-17)

**What changed and why**: the v1.5 design pre-picked three traits (CAD, T2D, breast or prostate) and mapped each to a single curator-chosen PGS Catalog scorefile, baked into a `reference/pgs_panel/<trait>.yaml`. A methodological review during the slice-E pre-implementation pass — and the project owner's direct callout — identified this as the curated_notes mistake in PRS form: the curator pre-decides which traits matter + which scorefiles are right, freezing the editorial layer against the long-tail of trait questions a user actually asks ("what about my asthma? ADHD? schizophrenia? prostate? Alzheimer's?"). The agent-research-and-synthesis plan retired the parallel curated_notes design for lifestyle calibration in v1.6; Q8 v1.6 makes the same move for PRS.

**The new design** (per [agent-driven PRS report](../../../reports/agent-driven-prs-computation.md)):

1. **PGS Catalog ID is the canonical key**, not curator-named trait. The `pgs_scores` table is keyed by `pgs_id` (e.g. `PGS000018`), not by `cad` / `t2d` / `prostate`. Multiple PGSs per trait are first-class.
2. **Four host tools, not one**: `genomeclaw_pgs_list` / `genomeclaw_pgs_get` / `genomeclaw_pgs_compute` / `genomeclaw_pgs_compute_status`. The plugin tool count is 9 (was 6).
3. **Agent-curated PGS choice as a memory + provenance contract**: the agent reasons at `INV-A002` ceiling over PGS Catalog metadata + recent literature + the user's likely ancestry; picks a scorefile; persists the rationale + alternatives considered + the verbatim user question both as columns on the `pgs_scores` row (per `INV-A003`) and as a memory note (per `INV-A001`).
4. **Consent at INV-P001 install-time, not per-compute**: PGS Catalog egress is already an `INV-P001`-class destination the user opted into at install. No per-compute user-approval prompts. Runaway-compute risk is bounded by a concurrency cap (1 in-flight) + a kill-switch (`genomeclaw config set pgs.compute_enabled false` revokes the path entirely). A daily wall-clock budget was considered + rejected as overengineering for the single-user PoC; the concurrency cap + the natural per-compute time bound (~5 min for `pgsc_calc` on one PGS at 30× WGS) keep cumulative damage bounded without the budget mechanism. Add back later if a real failure surfaces.
5. **PRS-decline pattern in the agent system prompt** *(per `INV-C001` v1.7)*: the agent declines to compute when the literature is too immature (top-decile RR < ~1.5×; no independent replication; ancestry-calibration failure for this user; no biologically-grounded polygenic basis). The decline is *reasoned* (the agent runs the research step first); names two specific reasons; is itself persisted as a memory note so future sessions hit the decline before re-deciding.
6. **No pre-curated trait panel in code**: the "panel" is whatever the agent has chosen to compute for *this* user; it grows as a side-effect of use.

**Why this is the right structural pivot**: long-horizon reasoning models (Claude 4.x at `xhigh`, GPT-5 at `xhigh`, o-series at `max`) make PGS selection a decision they're genuinely good at — multi-criteria, citation-bound, well-suited to the kind of metadata reasoning PGS Catalog supports. The compute layer needs orchestration discipline (cache, concurrency cap, kill-switch); the editorial layer needs reasoning, not curation.

**What stays the same as v1.5**: `pgsc_calc` is still the compute engine. Continuous-ancestry calibration via `--run_ancestry` is mandatory. PRS findings still carry `category: clinical-non-actionable` + no `clinical_escalation` marker (per `INV-C001`). PGS Catalog is still the inbound egress destination, host-side, INV-P001-class opt-in. The compute still respects the personal-host resource envelope (16 GB RAM, 2 CPUs).

**Deferred to a Slice E.4 (post-PoC)**: validation study of agent PGS-selection quality against expert-curated benchmarks for 8-12 canonical traits + a pre-compute consent turn analogous to clinical genetic-counseling pre-test discussion. The methodological review (recorded as a section in the report) identifies both as required before any deployment beyond the project owner.

**Affected files (v1.6)**:
- [INVARIANTS.md](../../../reference/INVARIANTS.md) v1.11 — adds `INV-A003` (Agent-Curated Compute Provenance); revises `INV-C001` to v1.7 with the PRS-decline pattern.
- [grand-plan.md](../../../reference/grand-plan.md) — Theme G PRS bullet + Decisions Taken Q8 row revised; Q10 "additional PRS traits" deferred decision retired.
- [architecture.md](../../../reference/architecture.md) — plugin tool table (6→9), 4 new PGS endpoints, `pgs_scores` table description, `pgs_compute_tasks.sqlite` added under `derived/<run-id>/`, INV-A003 row added to the invariant-traceability table.
- [user-stories.md](../../../reference/user-stories.md) — Story 10 tool-call block rewritten; resolved-gap entry added for retired Q10 trigger.
- This spec — AC9 rewritten above; Q8 v1.6 amendment block (this section).
- [development-plan.md](development-plan.md) Phase 6 row + [phases/phase-6.md](phases/phase-6.md) Slice E description revised.
- [phases/phase-6-slice-e.md](phases/phase-6-slice-e.md) marked **Status: Superseded** — the v2 plan replaces it.

#### v1.5 (original, 2026-05-08; superseded by v1.6 — kept below for the historical record)

**Decision**: add **`pgsc_calc`** (PGS Catalog Calculator, Nextflow) to compute polygenic risk scores for **three initial traits**: **coronary artery disease (CAD)**, **type 2 diabetes (T2D)**, and **breast cancer or prostate cancer** (project owner's choice; PRS313/BCAC for breast, PRS269 for prostate). All scores **ancestry-normalized** via `pgsc_calc --run_ancestry` (continuous-ancestry normalization against 1000G + HGDP; reporting raw percentiles without ancestry calibration produces systematically wrong numbers for non-European users). Materialize a **`pgs_scores` table** in the derived store. Add **`genomeclaw_pgs`** to the plugin tool surface (6th tool; tool count 5 → 6). The host service exposes a new endpoint **`GET /v1/pgs/{trait}`** returning `{percentile_in_user_ancestry, raw_score, source_pgs_id, study_population, calibration_warning}`.

**Rationale**: single-SNP findings cannot meaningfully answer common-disease risk questions; PRS can. `pgsc_calc` handles the canonical concerns (genome build liftovers, strand alignment, multi-allelic variant matching, continuous-ancestry normalization) and runs comfortably on a personal host (16 GB RAM, 2 CPUs on Linux). Three initial traits are chosen for maximum lifestyle-motivation value (CAD, T2D both well-established and lifestyle-modifiable) plus one user-interest trait (breast or prostate). The full panel of 8–10 traits is **deferred under Q10's defer-by-default discipline** — additional traits are a one-line config change in `pgsc_calc` when the user asks.

**Privacy**: `pgsc_calc` introduces a new **deliberate, host-side, opt-in** egress — fetching PGS scoring weights from the **PGS Catalog over HTTPS**. Same shape as the existing `genomeclaw-prep fetch --source clinvar` operation. **Genomic data does not traverse the boundary**; only PGS scoring weights flow inbound. (`INV-P001` preserved.)

**Findings classification**: PRS findings carry `category: clinical-non-actionable` (population-level percentile estimates, not pathogenic variant calls). They do **not** carry a `clinical_escalation` marker. The `calibration_warning` string makes ancestry-normalization explicit when the user's continuous-ancestry estimate falls in a region with sparse training data. (`INV-C001` preserved; not blurring research vs. clinical.)

**Tool shape**:
- `genomeclaw_pgs` — `Type.Object({ trait: Type.String({ minLength: 1 }) })` (scalar param; the trait list is small).
- `output_class: summary` (`INV-P002`); response includes the calibration warning structurally; never returns raw PGS variant lists.

**Revisit when**:
- The user asks about a trait not in the panel of three (one-line config add — defer-driven, not a redesign).
- The continuous-ancestry calibration produces a warning that's hard for the agent to communicate cleanly (revisit response shape).
- `pgsc_calc` resource budget exceeds the personal-host envelope for a specific trait (revisit panel size).

**Affected files**:
- [development-plan.md](development-plan.md) Phase 6 — updated in Phase 4 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md) (adds `pgsc_calc` + `genomeclaw_pgs` + `pgs_scores` table deliverables).
- [docs/reference/architecture.md](../../reference/architecture.md) Component 1, Component 2, Component 3 tool table, data layout, network topology — updated in Phase 2.
- [docs/reference/grand-plan.md](../../reference/grand-plan.md) Theme G + Decisions Taken — updated in Phase 3.
- [docs/reference/user-stories.md](../../reference/user-stories.md) — new short PRS story added in Phase 3.

---

### Q9 — Lifestyle calibration ~~via reference/curated_notes/~~ via agent research-and-synthesis

**Decided**: 2026-05-08 (v1.5 — curated notes).
**Revised**: 2026-05-15 (v1.6 — agent research-and-synthesis). See [agent-research-and-synthesis plan](../agent-research-and-synthesis/spec.md).

**Original decision (v1.5; superseded)**: lifestyle calibration driven by a host-side `reference/curated_notes/<gene>.md` directory. Retired in v1.6 because the pattern (a) didn't leverage the frontier model's training knowledge, (b) didn't scale beyond the curator's pre-defined topic set, (c) didn't self-update with new literature.

**Revised decision (v1.6)**: lifestyle calibration is driven by the **agent research-and-synthesis pattern** built on OpenClaw's first-class primitives:
1. **Memory** (`memory_search` / `MEMORY.md` / `memory/YYYY-MM-DD.md`) — prior synthesis the agent persisted in its workspace; recalled before re-research.
2. **Reasoned research** (`web_search` + the model's training knowledge under extended reasoning) — current online sources combined with the model's existing knowledge at moderate-to-high reasoning effort.
3. **Synthesis at maximum reasoning** (`INV-A002`) — the bioinformatician-in-healthcare turn for any user-facing health interpretation.
4. **Structured memory notes** (`INV-A001`) — persisted before reply so future sessions recall instead of re-researching.

The structured `evidence_quality` field on lifestyle findings (per `INV-C001` v1.4) is **preserved** in the schema for future-proofing but is **not the primary calibration surface** — the agent composes lifestyle responses from the user's variant call plus its reasoned synthesis.

**No pre-authored gene shortlist (v1.6)**. The seven-gene shortlist (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR) + the `topics/hard-genes.md` companion note from v1.5 are **retired**. The agent's research-and-synthesis pattern handles the long-tail of gene questions through the same path — there's no curator-pre-defined topic set the system is constrained to. APOE's disclosure-protocol framing (lifetime AD risk numbers + "this is fraught" cue) becomes a property of the agent's accumulated reasoning + system prompt, not of a baked markdown file.

**Genes dropped from the lifestyle track (unchanged from v1.5)** — but now the agent declines on each ask with specific reasons rather than refusing on a curation-list basis:
- **PER3 VNTR / CLOCK** (chronotype) — repeated non-replication; VNTRs unreliably called from short-read 30× WGS.
- **ACTN3 R577X** (athletic performance) — elite-cohort effect that doesn't transfer to recreational performance.

**Rationale for the v1.6 revision**: the v1.5 pre-authored-notes pattern was a 100× capability mismatch with frontier models. GPT-5.5 has read every paper through its training cutoff; the curated-notes pattern actively suppressed that knowledge in favor of the project owner's pre-codification. v1.6 leverages: (a) the model's training knowledge as a default substrate, (b) current online sources via `web_search` for freshness, (c) extended reasoning at `max` for the synthesis step, (d) agent memory to avoid re-researching settled topics. The user is no longer the curator; the user is the **directional-feedback giver** ("be more conservative about RCT vs. observational evidence") whose feedback the agent persists to memory + applies on future synthesis turns.

**N-of-1 experiment framing**: defensible only for outcomes with within-individual variability and short washout windows. Unchanged in v1.6 — the constraint lives in the agent's system prompt + synthesis discipline.

**`INV-C001` recognition**: INVARIANTS.md bumped to **v1.8** on 2026-05-15 — INV-C001 to v1.6 (research-and-synthesis), plus two new invariants `INV-A001` (memory provenance) + `INV-A002` (synthesis reasoning floor). See [INVARIANTS.md](../../reference/INVARIANTS.md).

**Affected files** (revised 2026-05-15):
- [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — v1.8 sweep landed 2026-05-15.
- [docs/reference/architecture.md](../../reference/architecture.md) — agent cognition layer section added 2026-05-15; data layout's `curated_notes/` removed.
- [docs/reference/grand-plan.md](../../reference/grand-plan.md) Theme H — rewritten 2026-05-15.
- [docs/reference/user-stories.md](../../reference/user-stories.md) Story 9 — rewritten 2026-05-15 as the canonical research-and-synthesis demo.
- [development-plan.md](development-plan.md) Phase 6 — Slice C (7 curated gene notes) **superseded** by [agent-research-and-synthesis plan](../agent-research-and-synthesis/spec.md).

---

### Q10 — Defer-by-default scope discipline + trigger list

**Decided**: 2026-05-08.

**Decision**: adopt a **defer-by-default** scope discipline for the POC. Each deferred feature has a specific **trigger condition**; building until the trigger fires is the wrong call. The grand plan codifies this as a Strategic Constraint in Phase 3 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md).

**Deferred features and their triggers**:

| Feature | Trigger |
|---|---|
| HLA typing (T1K) | User asks about abacavir (HLA-B\*57:01), carbamazepine (HLA-B\*15:02 / HLA-A\*31:01), celiac (HLA-DQ2/DQ8), or ankylosing spondylitis (HLA-B\*27). |
| Manta / structural-variant calling | User asks about a known familial deletion. (Honest answer often "request MLPA / clinical-grade testing" first.) |
| ExpansionHunter / repeat expansions | User asks about Huntington's, ALS/FTD (C9orf72), Friedreich's (FXN), spinocerebellar ataxias, or Fragile X. |
| mt-aware mtDNA caller (mity) | User asks an mtDNA-specific question. |
| Population-specific reference panels (SweGen, GenomeAsia, etc.) | Run somalier ancestry inference; if the user's ancestry concentrates in a public-panel population, add it. |
| Schema-enforced citation stripping | LLM observed hallucinating PMIDs in practice. |
| Tool-use forcing | LLM observed answering clinical / lifestyle questions from parametric memory without calling tools. |
| Deterministic server-rendered findings card | LLM observed dropping schema fields when summarizing into prose. |
| Phrasing templates for high-risk categories | A specific category of response repeatedly produces wrong framing. |
| Automated ACMG/AMP rule classifier (InterVar, Genebe) | The agent's natural ACMG composition produces wrong P/LP calls in observed conversations. |
| Eval harness with synthetic test cases | A regression breaks something twice. |
| Additional PRS traits beyond the initial 3 | User asks about a trait not yet in the panel. |
| Quarterly automated reanalysis | A ClinVar release lands that the user actually wants reprocessed. |
| OMIM, ClinGen Gene-Disease Validity, dbNSFP, MaxEntScan, UTRannotator vcfanno sources | The agent's responses visibly need richer evidence in a specific category. |

**Rationale**: building infrastructure for hypothetical needs ages poorly; each deferred feature is a one- to two-day add when the trigger fires; the bar should be observed need, not anticipated need. This applies equally to safety scaffolding (citation stripping, tool-use forcing) — modern frontier models with clear system prompts and structured tool returns produce reasonable, calibrated output on this stack, and the architectural mitigations are real safeguards for regulated products and adversarial users, neither of which applies here.

**Where this constraint lives**: a new Strategic Constraint **"Defer-by-default"** in [docs/reference/grand-plan.md](../../reference/grand-plan.md), authored in Phase 3 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md). The trigger table above is duplicated into grand-plan.md's Decisions Deferred table where the existing structure permits.

**Revisit when**:
- A deferred feature's trigger fires (move it to Decisions Taken; author a small plan).
- The defer policy itself proves wrong-headed — i.e., the project regularly catches up to features it should have built sooner. (Track this in `work-notes.md` of the relevant phase.)

**Affected files**:
- [docs/reference/grand-plan.md](../../reference/grand-plan.md) Strategic Constraints + Decisions Deferred — updated in Phase 3 of the [POC pipeline recommendations plan](../../completed/poc-pipeline-recommendations/development-plan.md).

---

## Open Questions

All MVP open questions are resolved as of 2026-05-08 (Q1–Q4 on 2026-05-06; Q5–Q10 on 2026-05-08). New design questions surfaced during implementation should land here as they appear, then move to Decisions Taken once resolved.

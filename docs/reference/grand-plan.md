# GenomeClaw — Grand Plan

**Status**: Living vision document
**Scope**: Strategic roadmap, not a tactical plan
**Audience**: Future-you, future contributors, and any agent planning new work
**Last Updated**: 2026-05-08

**Operational companion**: [architecture.md](architecture.md) — verified deployment shape (components, file paths, network topology, install/config flow)
**Canonical rules**: [INVARIANTS.md](INVARIANTS.md) — `INV-xxx` IDs cited throughout this document
**Planning protocol**: [docs/plans/CLAUDE.md](../plans/CLAUDE.md) — how features are spec'd, tested, and landed

This document is the **why** and the **where next** of GenomeClaw. It does not specify components, file layouts, or commands — those live in [architecture.md](architecture.md). It does not specify rules of conduct — those live in [INVARIANTS.md](INVARIANTS.md). Per-feature plans cite this document for context; this document does not cite per-feature plans by name.

The grand plan moves slowly and on purpose. It does not get a phase tracker, RED/GREEN tests, or a completion date. It evolves as the project's understanding of itself evolves.

---

## Mission

Help one person — the project owner — **explore, annotate, reason about, and optimize their lifestyle from their own genome on hardware they own**, with evidence-linked outputs and no compromise on privacy.

GenomeClaw is the **local genomics surface for a NemoClaw agent stack**. It turns standard bioinformatics tools and curated annotation resources into a coherent, agent-friendly toolkit that handles **two distinct conversational tracks** — clinical questions (research framing + clinician-confirmation cues) and lifestyle questions (direct, actionable advice with calibrated evidence quality).

Said more concretely:

> Take a Nebula Genomics WGS dump, drop it next to any Linux or macOS host running NemoClaw, and let the user ask informed, cautious, evidence-linked questions about their genome — *both* clinical questions (which get research framing and clinician-confirmation cues) *and* lifestyle questions about caffeine, diet, exercise, sleep, alcohol, recovery, and similar (which get direct, actionable advice with calibrated evidence). The genomic source files never leave the device. The agent driving the conversation may run on a cloud frontier model (OpenAI gpt-5.4, Claude Opus, Gemini, or any NemoClaw-supported provider), but it sees only what's necessary to answer the current question — scoped findings and evidence, never bulk dumps.

---

## Audience

A single user, running locally:

- They have their own genomic data (initially a Nebula Genomics 30× WGS output).
- They want to ask informed questions about it without uploading it anywhere.
- They are comfortable letting an agent orchestrate complex workflows on their behalf.
- They expect cautious, evidence-linked answers, not clinical advice.

The CLI is shaped for **agent consumption first**, human consumption second. Most invocations come from a NemoClaw agent.

---

## Operating Environment

- **Host**: any Linux or macOS environment with **Docker** (or compatible engine) and **NemoClaw**. The bioinformatics binaries (`samtools`, `bcftools`, `mosdepth`, `htslib`, VEP, Cyrius, `pgsc_calc`, PharmCAT) and the Python toolkit (`cyvcf2`, `pysam`, DuckDB, FastAPI) ride together in the **`genomeclaw/toolkit`** host Docker image, so the host's bare PATH stays clean and tool versions are pinned, reproducible, and traceable in `manifest.json` (`INV-R001`). The project is deliberately agnostic about the specific hardware — if Docker + NemoClaw run there, GenomeClaw runs there.
- **Runtime**: NemoClaw / OpenClaw / OpenShell agentic stack.
- **Agent provider**: typically a cloud frontier model — OpenAI gpt-5.4 in the project owner's setup; other NemoClaw-supported providers (Anthropic, Google Gemini, Local Ollama, Local NIM, Local vLLM, etc.) are interchangeable per the NemoClaw inference-options matrix.
- **Network**: required only for the configured agent provider and the host-side `genomeclaw-service`. All other network use is opt-in. Genomic source files (FASTQ, BAM/CRAM, VCF/gVCF) themselves never leave the device, and per `INV-D002` they never even enter the agent-facing sandbox.

For the verified deployment topology — Docker daemon, OpenShell gateway container, embedded k3s cluster, sandbox pod, host bridge over `host.openshell.internal`, RFC 1918 SSRF allowlist — see [architecture.md](architecture.md).

---

## Pillars

The canonical invariants ([INVARIANTS.md](INVARIANTS.md)) are restated here as design pillars — the lenses through which every choice is evaluated.

| Pillar | Invariant(s) | Design implication |
|--------|--------------|-------------------|
| Source authority | `INV-D001` | Raw artifacts are read-only; pipelines write to derived stores only |
| Host-only raw artifacts | `INV-D002` | Raw genomic data is processed only host-side; the sandbox has no path to it |
| Evidence traceability | `INV-E001` | Every claim is linkable to an observation, annotation, evidence record, or labeled heuristic |
| Privacy default | `INV-P001`, `INV-P002` | Genomic source files never leave the device; the configured NemoClaw agent is a named, minimal-sufficient egress boundary; *other* remote calls are per-operation opt-in |
| Rebuildability | `INV-R001` | Derived stores are deterministic products of recorded inputs + tools |
| Clinical / lifestyle distinction | `INV-C001` | Clinical-actionability findings carry escalation markers and clinician-confirmation cues; lifestyle/wellbeing findings get direct, calibrated guidance — clinician-deferral is *not* the default for lifestyle questions |

Decisions that violate a pillar are not made. Decisions that are merely *uncomfortable* against a pillar require an explicit trade-off note in the relevant plan.

---

## The System, At a Glance

GenomeClaw splits across **two execution domains**, forced by `INV-D002`:

- **Host** — heavy bioinformatics pipeline, a small read-only HTTP service, and the derived store. Lives in `packages/toolkit/`. Runs as ordinary host processes on Linux or macOS. Raw artifacts live here and never leave.
- **Sandbox (NemoClaw / OpenShell)** — a small TypeScript plugin registering agent-callable tools. Lives in `packages/nemoclaw-plugin/`. Reaches the host service over HTTP, whitelisted by an OpenShell policy preset.

GenomeClaw is **not** a fork of NemoClaw, OpenClaw, or OpenShell. It plugs into them via published extension surfaces — an OpenClaw plugin (`openclaw.plugin.json`), a NemoClaw network policy preset, and a custom sandbox `Dockerfile` consumed by `nemoclaw onboard --from`.

For the layered diagram, file layout, install/config flow, and runtime topology, see [architecture.md](architecture.md).

---

## Capability Themes

These are the **functional surfaces** the system grows. Each theme has a purpose, a rough scope, what it gates, and what's open. Themes are not delivered all at once; the **roadmap horizons** below sequence them.

### Theme A — Source artifact handling

- Ingest Nebula Genomics outputs (FASTQ, BAM/CRAM, VCF, gVCF).
- Integrity checks: md5/sha256 verification, indexing, reference-build sniffing.
- Format-aware listing and preview without mutating sources.

**Gates**: every downstream theme depends on reliable, hashed, indexed source artifacts.
**Open**: which Nebula deliverable variant to prioritize first (raw FASTQ vs. processed VCF).

### Theme B — Reproducible annotation pipelines

- VCF normalization (left-align, split multi-allelics, canonical representation).
- **VEP + LOFTEE + AlphaMissense + SpliceAI** for effect predictions and pathogenicity scoring (per [MVP spec Q5](../plans/active/mvp/spec.md)). **MANE Select** is the default reporting transcript; HGVSc and HGVSp are emitted server-side, never constructed by the LLM.
- **vcfanno** for ClinVar (latest release) and gnomAD v4 (with per-population AFs) overlays. dbSNP join via vcfanno as well.
- **False-reassurance prevention via coverage-aware queries** (per [MVP spec Q7](../plans/active/mvp/spec.md)) — `mosdepth` runs at ingest and materializes per-gene mean coverage into a `coverage_qc` table; the host service `/v1/gene/{symbol}` endpoint and the `genomeclaw_gene` plugin tool surface `mean_coverage` and `low_coverage_exons` so the agent can ground negative answers ("no pathogenic *BRCA1* variants in your callset; mean coverage was 28×, exon 11 averaged 4× — clinical confirmation would require Sanger").
- Materialization into the query layer with full provenance columns.
- Determinism guarantees and tests.

**Gates**: query-layer correctness; agentic interpretation needs structured, annotated input.
**Open**: ~~which annotator (SnpEff vs. VEP vs. vcfanno) is the default;~~ resolved by Q5 (VEP + plugins + vcfanno). How regional restrictions on annotation datasets are handled remains open.

### Theme C — Local queryable evidence

- DuckDB / GenomicSQLite as the query substrate.
- Joins between findings, annotations, and curated evidence.
- A small evidence cache with versioned source fingerprints.
- The host service (`genomeclaw-service`) exposing scoped reads as JSON.

**Gates**: agentic interpretation requires fast, structured access. Reporting requires evidence joins.
**Open**: schema design; whether to layer GenomicSQLite over DuckDB or pick one.

### Theme D — Agentic interpretation

- Tool surface for NemoClaw agents (the plugin's registered commands).
- Structured **findings** emission with categorical confidence and evidence references.
- An uncertainty taxonomy (observation / annotation / heuristic / speculation).
- Prompts that are evidence-linked **by construction**, not by exhortation.

**Gates**: reporting depends on structured findings.
**Open**: how much interpretation logic lives in the host service vs. in NemoClaw agent prompts.

### Theme E — Cautious reporting

- Report skeletons with evidence citations rendered structurally.
- Clinical-escalation markers on `clinical-actionable` findings; lifestyle findings rendered with their own framing — direct guidance + evidence-quality calibration, no clinician-deferral by default (`INV-C001`).
- Forbidden-phrase tests on plugin tool descriptions and host-service report responses (over-claim *and* over-deferral both fail the test).
- Provenance section on every report (pipeline + dataset versions).
- **Clinician-handoff artifacts** — research-grade text the user can forward verbatim to a clinician (per Story 4 / Story 6). Generated by the agent from `/v1/findings` + `/v1/health` primitives, not by a host-service report endpoint (per [MVP spec Q3](../plans/active/mvp/spec.md)).

**Gates**: this is where over-claim and over-deferral risk concentrate; gating is the point.
**Open**: ~~report format(s) — Markdown, structured JSON, both?~~ resolved by Q3 — no `/v1/report` endpoint; the agent assembles report-shaped responses from primitives.

### Theme F — Reanalysis loop

- Detect annotation source updates (e.g., ClinVar release).
- Replay specific findings against new annotations.
- Diff between previous and new interpretations.
- Surface "your old finding may have changed" prompts cautiously.

**Gates**: requires solid provenance + rebuildability; can't reanalyze if the original run isn't reproducible.
**Open**: cadence and trigger model.

### Theme G — Pharmacogenomics & specialized panels

- **PharmCAT v3.2.0 integration shipped 2026-05-22** *(MVP Phase 6 Slice D'; see [phase-6-slice-d-prime.md](../plans/active/mvp/phases/phase-6-slice-d-prime.md))*. Two-subprocess architecture (`pharmcat_vcf_preprocessor` → `pharmcat` JAR with `-po` outside-call), parses `report.json` for user-applicable per-(gene × drug) annotations, INSERTs one `clinical-actionable` `findings` row per actionable recommendation with `evidence_ref=pharmgkb:<drug-id>` + `clinical_escalation=confirm_with_provider`. Real-data smoke against the project owner's Nebula VCF + CYP2D6 outside-call (135s wall) produced 9 user-applicable PGx findings (atomoxetine + tamoxifen via CYP2D6 *1/*35 outside-call; atazanavir via UGT1A1 *1/*80+*28; efavirenz + sertraline via CYP2B6 *1/*6; 4 PPIs via CYP2C19 *1/*1).
- **CYP2D6 outside-call via Cyrius shipped 2026-05-22** *(MVP Phase 6 Slice D; per [spec Q6](../plans/active/mvp/spec.md) + [phase-6-slice-d.md](../plans/active/mvp/phases/phase-6-slice-d.md))*. PharmCAT does not call CYP2D6 from VCF; Cyrius v1.1.1 (Illumina; GitHub-only — not on bioconda) runs against the BAM/CRAM, produces a star-allele diplotype, and feeds it into PharmCAT's outside-call interface. Real-data smoke against the project owner's Nebula CRAM (170s wall) returned diplotype `*1/*35`, filter PASS. CYP2D6 metabolizes ~25% of clinically prescribed drugs (codeine, tramadol, oxycodone, tamoxifen, many antidepressants, antipsychotics); without this, the PGx track would be unsafe for any CYP2D6-relevant prescription.
- **Polygenic risk scores via `pgsc_calc`**, **agent-driven** *(v1.6, 2026-05-17; per [MVP spec Q8 v1.6](../plans/active/mvp/spec.md) + [agent-driven PRS report](../reports/agent-driven-prs-computation.md))*. The agent (running at the model's reasoning ceiling per `INV-A002`) reads PGS Catalog metadata + recent literature, picks the right scorefile for the user's question, records its choice rationale + alternatives considered (per `INV-A003`), and triggers a host-side compute. Results land in a `pgs_scores` table keyed by PGS Catalog ID (e.g. `PGS000018`), **not** by curator-named trait. The "panel" is whatever the agent has computed for *this* user; it grows over time as a side-effect of use. Ancestry-normalized via continuous-ancestry calibration against 1000G + HGDP. PRS findings classification is `clinical-non-actionable` (population-level percentile estimates, not pathogenic variant calls); they do not carry a `clinical_escalation` marker. Calibration warning is structural. The agent declines a compute (per the **PRS-decline pattern** in `INV-C001` v1.7) when the literature is too immature to produce a meaningful percentile — naming two specific reasons rather than computing a poorly-validated score. The v1.5 fixed-three-trait panel (CAD, T2D, breast or prostate) is **retired**; the pre-codification didn't scale to the long-tail of conditions a curious adult actually asks about.
- **PRS input-shape reality** *(2026-05-20, per [research validation findings](../reports/prs-real-data-smoke-research-findings.md))*. The default input class — non-imputed single-sample WGS — caps the match rate between a user's variant-sites-only VCF and a dense imputed PGS Catalog scoring file (e.g. snpnet/LASSO models like PGS001229) at **45–65%** empirically, not the 75% the `pgsc_calc` default `--min_overlap` was calibrated on (Lambert et al. 2024 *Nature Genetics* — cohort-imputed data). The ~47% structural loss decomposes as ~15% ambiguous (palindromic) SNPs dropped by `--keep_ambiguous false`, ~10% multi-allelic / complex records, and ~22% rare-variant / coverage-dropout sites the variant-sites-only VCF doesn't emit. Operational consequences: `--min_overlap` is treated as a per-input-class parameter (default `0.5` for non-imputed single-sample WGS, persisted in `pgs_scores.params_json` per `INV-R001`); `--keep_ambiguous false` is documented as **load-bearing** (flipping it to `true` recovers ~15% match rate at the cost of systematic strand-error on ~half of recovered weights); `bcftools norm -m -any` runs upstream of the wrapper to recover the multi-allelic share; **HapMap3+ / C+T scorefiles are preferred** over snpnet/imputation-dependent scorefiles for this input class. When only an imputation-dependent scorefile is available for a trait, that becomes a fifth named reason for the agent to consider declining under the `INV-C001` v1.7 PRS-decline pattern.
- ACMG SF gene-list awareness.
- Haplotype-aware reporting and escalation markers.

**Gates**: highest clinical-adjacency surface area; depends on Themes B–E being solid.
**Open**: ~~which PharmCAT outputs to surface and how~~ resolved by Slice D' (2026-05-22) — emit one finding per (drug × user-applicable annotation) where `dosingInformation || alternateDrugAvailable || otherPrescribingGuidance`. CPIC guideline branch only in v0; DPWG + FDA branches deferred to a follow-on slice if those recommendations become user-actionable downstream.

### Theme H — Lifestyle and wellbeing optimization

Lifestyle calibration is driven by the **agent research-and-synthesis pattern** *(v1.6; per [agent-research-and-synthesis plan](../plans/active/agent-research-and-synthesis/spec.md))*, built on OpenClaw's first-class primitives: **agent memory** (`memory_search` / `MEMORY.md` / `memory/YYYY-MM-DD.md`), **reasoned research** (web_search + the model's training knowledge, combined under extended reasoning), and the **synthesis-reasoning floor** for health-interpretation turns (`INV-A002`). The agent acts as a bioinformatician-in-healthcare: researches the literature at moderate reasoning, synthesises at the model's maximum reasoning level for any user-facing interpretation, persists what it learned to its workspace memory, and recalls prior synthesis without re-research on subsequent sessions.

- **No pre-authored gene shortlist.** The long-tail of "anything about ABCG2 and uric acid?" works as well as the canonical "what about my CYP1A2 + caffeine?" — both flow through the same research-and-synthesis pattern. The earlier v1.5 seven-note shortlist (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR) under `reference/curated_notes/<gene>.md` is **retired**; the pre-codification doesn't scale beyond the curator's pre-defined topics and actively suppresses the frontier model's training knowledge. The genes still get well-calibrated answers — the calibration is the *agent's*, accumulated and refined through use, rather than the *project owner's* baked into a markdown file.
- **PER3 / CLOCK / ACTN3 stay out**, not because of curation policy but because the agent's research-and-synthesis pattern will surface the same conclusions when asked: VNTRs unreliable on short-read WGS (PER3), repeated non-replication (CLOCK), elite-cohort effect that doesn't transfer (ACTN3). The agent declines gracefully with reasons rather than refusing on a curation-list basis.
- Direct, actionable agent guidance on lifestyle topics, framed as **falsifiable experiments** rather than clinical guidelines (`INV-C001` v1.6). N-of-1 framing is defensible only for outcomes with within-individual variability and short washout windows.
- The agent's voice tracks what its accumulated research notes (in `MEMORY.md`) plus the user's directional feedback over time have shaped. The user can ask "remember to be more conservative about RCT vs. observational evidence" — the agent saves that to memory and applies it on future synthesis turns. Memory is inspectable via `memory_get` or by reading the workspace directly.

**Gates**: depends on Themes B–D being solid (findings infrastructure + agentic interpretation surface). Plus OpenClaw `memory-core` + `web_search` configured in the sandbox (off-by-default web_search per `INV-P001`; opt-in).
**Open**: how the agent self-classifies "health-interpretation turn" vs "conversational turn" for the `INV-A002` synthesis-reasoning floor — initial approach is system-prompt self-classification, verified by snapshot tests over the execution trace. Tunable per-topic in a future iteration if the heuristic over- or under-applies.

### Theme I — Local retrieval (optional, later)

- Local embeddings for evidence retrieval (papers, curated notes).
- Local reranker.

**Gates**: only after Themes B–E are solid.
**Open**: which embedding model fits an interactive retrieval workflow with acceptable latency on the user's host.

---

## Roadmap Horizons

Horizons are **rough chronology**, not commitments. The point is to communicate sequencing logic ("X depends on Y") without freezing scope or dates. Each horizon is delivered as one or more plans under [docs/plans/active/](../plans/active/) following the [planning protocol](../plans/CLAUDE.md).

### Horizon 1 — Foundations

*Scope themes: A (partial), tooling*

**Status**: **Delivered** (MVP Phases 1–3 + cram-scratch-strategy interlude; 2026-05-08 through 2026-05-09).

- Repository scaffolding under `packages/toolkit/` and `packages/nemoclaw-plugin/`, language toolchains (Python + TypeScript), CI shape.
- Host CLI entrypoint and subcommand framework (`genomeclaw`).
- Plugin scaffolding with the manifest, policy preset, and Dockerfile already in place; first tool round-trip with the host service over HTTP.
- Ingest of Nebula Genomics outputs with integrity checks (Theme A).
- Minimal derived-store substrate with provenance columns (foundations of Theme C).
- Test infrastructure for the first-class categories (provenance, determinism, privacy default, evidence binding).

**Exit criteria** — met 2026-05-15 (Phase 5 close): a NemoClaw agent in the project owner's sandbox can call `genomeclaw_status` and receive structured JSON from the host service; the plugin is policy-denied any other egress.

### Horizon 2 — Annotation pipelines

*Scope themes: B, C*

**Status**: **Delivered** (MVP Phase 4 close 2026-05-15 — full VEP + LOFTEE + AlphaMissense + vcfanno + gnomAD-constraint stack, MANE Select transcript pinning, 4h08m58s real-data smoke against the project owner's Nebula VCF).

- VCF normalization.
- ClinVar + gnomAD + dbSNP annotation paths.
- Materialization into DuckDB / GenomicSQLite.
- Determinism + provenance test coverage across the pipeline.
- Host service query endpoints (`/v1/variants`, `/v1/findings`).

**Exit criteria** — met 2026-05-15: a deterministic, evidence-cited variant store can be rebuilt from a fixture (4.87M variant rows, ClinVar parity 42,885/42,885 vs. the Phase-4A baseline), and `genomeclaw_findings` returns structured rows with provenance.

### Horizon 3 — Agentic interpretation surface

*Scope themes: D, partial E*

**Status**: **Delivered** (MVP Phase 6 close 2026-05-22 — Slices A/B + agent-research-and-synthesis companion plan + Slice E PRS + Slice D Cyrius + Slice D' PharmCAT + Slice F live LLM sweep). 4/4 live tests against gpt-5.5 pass (Stories 2 + 4 + 9 + 10).

- Structured **findings** emission with categorical confidence.
- Evidence-record schema and joins.
- Plugin tool surface formalized; safe-by-default vs. opt-in classification implemented; bulk-class wired but disabled by default.
- Privacy-default tests across the full agent flow.

**Exit criteria** — met 2026-05-22: a NemoClaw agent can drive the full ingest → annotate → query → finding loop; default-config integration tests confirm no outbound call goes anywhere other than the configured agent provider and the configured host service. Plugin's 9-tool surface (status / findings / variant / evidence / gene / pgs_list / pgs_get / pgs_compute / pgs_compute_status) loads + registers cleanly inside the sandbox image; 798 toolkit tests pass + 58/58 invariants green.

### Horizon 4 — Cautious reporting

*Scope theme: E*

- Report skeletons with evidence citation rendering.
- Clinical-escalation markers.
- Forbidden-phrase tests on plugin tool descriptions and host service report responses.
- Provenance section on every report.

**Exit criteria**: every report passes evidence-binding, escalation-marker, and forbidden-phrase tests against fixtures.

### Horizon 5 — Pharmacogenomics & specialized panels

*Scope theme: G*

- PharmCAT integration.
- ACMG SF awareness.
- Haplotype-aware findings + escalation markers in reports.

**Exit criteria**: a small, fixture-backed PGx flow returns actionable findings with appropriate escalation markers.

### Horizon 6 — Lifestyle and wellbeing optimization

*Scope theme: H*

- `lifestyle` finding category in the host service and finding schema, plus `evidence_quality` field.
- Initial lifestyle finding set: caffeine metabolism, caffeine sensitivity, lactase persistence, ACTN3 muscle fiber, basic chronotype, alcohol metabolism.
- Plugin tool surface exposes `category=lifestyle`.
- Agent prompt-template guidance for lifestyle answers: direct guidance + evidence calibration + experiment framing — no clinician-deferral default.

**Exit criteria**: a NemoClaw agent can answer a "what does my genome say about caffeine?"-style question with direct lifestyle advice plus an evidence-quality caveat, without invoking clinician-deferral; clinician-deferral remains automatic for `clinical-actionable` findings.

### Horizon 7 — Reanalysis loop

*Scope theme: F*

- Detect annotation source updates.
- Replay specific findings against new annotation versions.
- Finding-level diff between runs.

**Exit criteria**: rerunning against a newer ClinVar release yields a structured diff of impacted findings.

### Horizon 8 — Optional local retrieval

*Scope theme: I*

- Local embeddings for evidence retrieval.
- Local reranker.

**Exit criteria**: revisited only after Horizons 1–7 are stable.

---

## Strategic Constraints

These are the constraints under which every architectural decision is made.

### Personal-host performance

Every default workflow must run within the resource envelope of a typical personal computer (a developer laptop, a small Linux home server, an Apple Silicon Mac, etc.) — no cloud bursting, no distributed compute. If a feature can't run on a personal host, it's either: broken into stages that can, pushed behind explicit user opt-in for a more capable host, or deferred.

### Privacy by named-boundary default

The only remote destination active by default is the user-configured NemoClaw agent provider (OpenAI gpt-5.4 in the project owner's setup; Anthropic / Gemini / others are interchangeable). Tool outputs flowing to the agent are **minimal-sufficient**: scoped findings, scoped variants, scoped evidence — never bulk dumps. Bulk transfers and *other* remote integrations require explicit per-operation opt-in. Genomic source files never leave the device and never enter the agent-facing sandbox. Logs and traces never carry sample IDs or variant coordinates at default verbosity. Runtime enforcement combines host-service shaping, plugin re-shaping, and the OpenShell L7 proxy + SSRF guard.

### Wrappers over rewrites

GenomeClaw orchestrates standard tools (samtools, bcftools, **VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno**, **Cyrius**, **mosdepth**, **`pgsc_calc`**, PharmCAT, etc.); it does not reimplement them. Where a tool is missing or unfit, the project chooses *adoption* (use a different tool) or *adapter* (wrap with provenance) before *replacement*.

### Defer-by-default

The POC ships a deliberately small surface area; each deferred feature has an explicit trigger condition. Building infrastructure for hypothetical needs ages poorly; the bar is observed need, not anticipated need (per [MVP spec Q10](../plans/active/mvp/spec.md)). This applies equally to safety scaffolding (citation stripping, tool-use forcing, deterministic findings cards) — modern frontier models with clear system prompts and structured tool returns produce reasonable, calibrated output on this stack, and the architectural mitigations are real safeguards for regulated products and adversarial users, neither of which applies to a single sophisticated user with clinician-handoff for anything actionable.

The full trigger list lives in the Decisions Deferred table below.

### Reproducibility over cleverness

A deterministic pipeline that's a little slower beats a clever heuristic that drifts. Non-determinism is allowed only when declared and justified.

### Single-user assumption

No multi-tenancy, no auth/permission complexity, no shared storage semantics. If the project ever needs multi-genome support (siblings, family), it's a deliberate scope expansion, not an emergent one.

### Agent-first interface

The plugin tool surface and the host service API are shaped for agents. Structured JSON is the default; human formatting is opt-in. Tools are small and composable; one tool does one thing.

### Plug into NemoClaw, don't fork it

GenomeClaw extends NemoClaw via its first-class plugin contract (manifest + policy preset + custom sandbox image). Forking the upstream codebase is rejected: it carries ongoing rebase cost, requires re-shipping every NemoClaw improvement, and provides no benefit GenomeClaw needs.

---

## Decisions Taken

These are the decisions the project starts with. Revisit only if a strong reason emerges; record the revisit in the relevant plan's `work-notes.md`.

| Decision | Reason |
|----------|--------|
| **Nebula Genomics outputs are the primary data target** | Concrete, well-shaped 30× WGS deliverables; user already has the data |
| **GRCh38 is the initial reference build** | Modern default; Nebula deliverables align |
| **DuckDB + GenomicSQLite as the query substrate** | Strong local performance, embeddable, columnar; aligned with bioinformatics use |
| **Two-domain split: host (heavy pipeline + service) + sandbox (plugin)** | `INV-D002`; OpenShell sandboxes have no documented host bind-mount mechanism |
| **GenomeClaw is a NemoClaw plugin (not a fork)** | NemoClaw exposes a first-class plugin contract via `openclaw.plugin.json` + `plugins.entries.<id>.config`; forking carries no benefit and ongoing rebase cost |
| **Host bridge is HTTP via `host.openshell.internal`, modeled on `local-inference.yaml`** | The only verified sandbox→host transport on this stack; UNIX socket bridge is refuted by inspection |
| **Plugin language is TypeScript** | Matches OpenClaw's Node.js host; uses the published `openclaw/plugin-sdk` |
| **Toolkit (host pipeline) language is Python** | Driven by ecosystem (`cyvcf2`, `pysam`, DuckDB Python, PharmCAT bindings) |
| **Workspace layout: `packages/toolkit/` + `packages/nemoclaw-plugin/`** | Clean seam aligned to deployment domain; cheap to extract either package later |
| **Wrap, don't reimplement** | Keeps scope sane; leans on community-maintained tools |
| **Local-first, no cloud sync** | `INV-P001`; project identity |
| **Inference provider is configurable via NemoClaw onboard; OpenAI gpt-5.4 confirmed working** | NemoClaw's inference-options matrix is provider-agnostic; the user's setup is OpenAI today |
| **Annotator stack: VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno** *(2026-05-08; per [MVP spec Q5](../plans/active/mvp/spec.md))* | SnpEff's pathogenicity-call divergence from VEP makes clinical-track findings unsafe; VEP's plugin ecosystem closes the gap. MANE Select pinned. |
| **CYP2D6 outside-call via Cyrius into PharmCAT** *(2026-05-08; per [MVP spec Q6](../plans/active/mvp/spec.md))* | PharmCAT does not call CYP2D6 from VCF; Cyrius 96.5–99.3% concordance on GeT-RM truth set. |
| **Coverage-aware gene queries via mosdepth + `genomeclaw_gene` (5th tool)** *(2026-05-08; per [MVP spec Q7](../plans/active/mvp/spec.md))* | Closes the most dangerous false-reassurance failure mode at minimal cost. |
| ~~**PRS via `pgsc_calc` + `genomeclaw_pgs` (6th tool); initial three-trait panel (CAD, T2D, breast or prostate)**~~ → **PRS via agent-driven PGS Catalog selection + `pgsc_calc` (4 tools, plugin count 5→9); no fixed trait panel** *(v1.6, 2026-05-17; per [MVP spec Q8 v1.6](../plans/active/mvp/spec.md), [INVARIANTS v1.11](INVARIANTS.md) INV-A003 + INV-C001 v1.7, [agent-driven PRS report](../reports/agent-driven-prs-computation.md))* | The v1.5 fixed-panel design recapitulated the v1.5 curated_notes mistake in PRS form: a curator pre-decides which traits matter + which scorefiles to use, baked into YAML, frozen against the long-tail of trait questions a user actually asks. The agent-driven design lets the model (at `INV-A002` ceiling) pick the right PGS from PGS Catalog metadata + recent literature + the user's ancestry, persist the choice rationale per `INV-A003`, decline gracefully via the PRS-decline pattern (`INV-C001` v1.7) when literature is too immature. Single-SNP findings still can't answer common-disease risk; PRS still can; the editorial layer that picks the right PRS moves from a curator's YAML to the agent's reasoning. The 6th-tool plan is retired; the new surface is 4 tools (`genomeclaw_pgs_list` / `_get` / `_compute` / `_compute_status`) bringing plugin tool count to 9. Bounded by a host-side concurrency cap (1 in-flight) + a kill-switch (`genomeclaw config set pgs.compute_enabled false`); consent stays at INV-P001 install-time. |
| ~~**Lifestyle calibration via `reference/curated_notes/<gene>.md`**~~ → **Lifestyle calibration via agent research-and-synthesis (v1.6, 2026-05-15)** *(per [agent-research-and-synthesis plan](../plans/active/agent-research-and-synthesis/spec.md), [INVARIANTS v1.8](INVARIANTS.md) INV-C001 v1.6 + INV-A001 + INV-A002)* | The v1.5 curated-notes pattern didn't leverage the frontier model's training knowledge, didn't scale beyond the curator's pre-defined topics, and didn't self-update with new literature. The research-and-synthesis pattern uses OpenClaw built-ins (memory + web_search) + max-reasoning for health interpretation. The seven-gene shortlist is no longer special-cased; the long-tail of gene questions works through the same path. |
| **Defer-by-default scope discipline with explicit trigger list** *(2026-05-08; per [MVP spec Q10](../plans/active/mvp/spec.md))* | Building infrastructure for hypothetical needs ages poorly; the bar is observed need, not anticipated need. |
| **Toolkit + bioinformatics binaries packaged as a single `genomeclaw/toolkit` Docker image** *(2026-05-08; see [architecture.md](architecture.md#host-side-packaging--genomeclawtoolkit-docker-image))* | Pinned tool versions strengthen `INV-R001`; one image runs identically on Linux, macOS, and CI; large reference data stays bind-mounted, never baked in. `INV-D002` is unaffected (it forbids bio binaries in the **sandbox** image, not the host one). |
| **PRS bootstrap closed: agent-driven `pgsc_calc` runs end-to-end with non-imputed force-genotyping bridge + resilience-first sequencing** *(2026-05-22; see [prs-bootstrap-meta](../plans/active/prs-bootstrap-meta.md), [smoke v23 results](../plans/active/prs-smoke-resilience/work-notes.md))* | Stage 3 went GREEN after a six-plan cascade closed the path-crossing, runtime-hardening, allele-orientation, non-imputed-WGS, and smoke-resilience gaps surfaced by the original integration smoke. The architectural pattern crystallised: Tier 1 + Tier 2 force-genotyping closes the variant-only-VCF gap; `--min_overlap 0.45` is the empirical threshold for non-imputed single-sample WGS; pre-flight L4 probes + mid-run watchdog + Nextflow `-resume` + Colima mount recovery turn a 25-90 min iteration cost into a 30s fail-fast or a 2-5 min self-heal; the `prs-compute --run-dir` flag persists the calibrated row into `variants.duckdb`. v23 produced MPNRGLQ2K PGS000018 percentile=14.54 within EUR @ 49.51% match rate. INV-D005/D006/D007/D008, INV-R002, INV-T001 v1.14 promoted across the cascade. |

---

## Decisions Deferred

Each of these has a **revisit criterion** — a condition that, if met, moves the decision to "taken".

| Deferred decision | Revisit when |
|-------------------|--------------|
| **Imputation support** | A user request appears AND a local imputation tool fits a personal-host resource budget |
| **Standalone GUI** | Default is "no — NemoClaw is the UI"; revisit only if NemoClaw integration proves insufficient |
| **Multi-genome support (siblings/family)** | Single-user end-to-end works *and* a real use case appears |
| **Federation across multiple data sources** | Out of scope until single Nebula source works end-to-end |
| ~~**Default annotator: SnpEff vs. VEP vs. vcfanno**~~ | ✅ Resolved by [MVP spec Q5](../plans/active/mvp/spec.md) — VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno (2026-05-08). |
| ~~**Report format(s) — Markdown / JSON / both**~~ | ✅ Resolved by [MVP spec Q3](../plans/active/mvp/spec.md) — no `/v1/report` endpoint; agent assembles report-shaped responses from primitives. |
| **Embedding model choice for Theme I** | Theme I is scoped (post-MVP); latency on a personal host is measured against an interactive-agent threshold |
| ~~**Whether OpenClaw plugin commands can return structured JSON instead of text**~~ | ✅ Resolved by [MVP spec Q2](../plans/active/mvp/spec.md) — `registerTool` with TypeBox + `jsonResult(...)`. |
| **Whether to use OpenClaw `nodeHostCommands` to drop the host HTTP service** | After v1 ships, only if the host HTTP service becomes painful — and only with a documented third-party API path |
| **Whether to split GenomeClaw into two repos (`genomeclaw` toolkit + `genomeclaw-nemoclaw-plugin`)** | The toolkit earns the right to publish standalone, OR external NemoClaw users want the plugin without the genomics toolkit weight |
| **HLA typing (T1K)** *(per [MVP spec Q10](../plans/active/mvp/spec.md))* | User asks about abacavir (HLA-B\*57:01), carbamazepine (HLA-B\*15:02 / HLA-A\*31:01), celiac (HLA-DQ2/DQ8), or ankylosing spondylitis (HLA-B\*27). |
| **Manta / structural-variant calling** *(per Q10)* | User asks about a known familial deletion. Honest answer often "request MLPA / clinical-grade testing" first. |
| **ExpansionHunter / repeat expansions** *(per Q10)* | User asks about Huntington's, ALS/FTD (C9orf72), Friedreich's (FXN), spinocerebellar ataxias, or Fragile X. |
| **mt-aware mtDNA caller (mity)** *(per Q10)* | User asks an mtDNA-specific question. |
| **Population-specific reference panels (SweGen, GenomeAsia, etc.)** *(per Q10)* | Run somalier ancestry inference; if the user's ancestry concentrates in a public-panel population, add it. |
| **Schema-enforced citation stripping** *(per Q10)* | LLM observed hallucinating PMIDs in practice. |
| **Tool-use forcing** *(per Q10)* | LLM observed answering clinical / lifestyle questions from parametric memory without calling tools. |
| **Deterministic server-rendered findings card** *(per Q10)* | LLM observed dropping schema fields when summarizing into prose. |
| **Phrasing templates for high-risk categories** *(per Q10)* | A specific category of response repeatedly produces wrong framing. |
| **Automated ACMG/AMP rule classifier (InterVar, Genebe)** *(per Q10)* | The agent's natural ACMG composition produces wrong P/LP calls in observed conversations. |
| **Eval harness with synthetic test cases** *(per Q10)* | A regression breaks something twice. |
| ~~**Additional PRS traits beyond the initial three**~~ → **N/A under Q8 v1.6** *(retired 2026-05-17)* | The fixed three-trait panel was retired in favor of agent-driven PRS selection (Q8 v1.6). The agent decides per-question which PGS Catalog scorefile to compute; there is no "initial panel" to extend. The long-tail of trait questions is the default path, not a deferred extension. |
| **Quarterly automated reanalysis** *(per Q10)* | A ClinVar release lands that the user actually wants reprocessed. |
| **OMIM, ClinGen Gene-Disease Validity, dbNSFP, MaxEntScan, UTRannotator vcfanno sources** *(per Q10)* | The agent's responses visibly need richer evidence in a specific category. |

---

## Out of Scope (Long-Term)

- Clinical decision support, diagnosis, treatment guidance.
- Mass / population analyses.
- Cloud sync of raw genomic data.
- Real-time clinical alerting.
- Hosting GenomeClaw as a service for other users.
- Mobile / browser-side execution of pipelines.

These items aren't deferred — they are explicitly *not the project*. Bringing them in scope would require renegotiating the mission.

---

## Risks & Open Questions

- **Personal-host performance** for annotation against gnomAD-scale datasets is unproven for this project. Theme B should validate early on the host class the user actually deploys to.
- **Annotation dataset licensing and redistribution** — datasets are downloaded by the user, not bundled. Each integration must document fetch + license expectations.
- **Drift between Nebula output formats** over time. The ingest layer (Theme A) needs format-version detection.
- **Over-claim drift** in agent prompts as the project grows. Forbidden-phrase tests and the privacy-safety-reviewer agent are the main controls.
- **Reproducibility of upstream tools** across versions. Pinning tool versions in derived-store provenance is the main control.
- **NemoClaw / OpenClaw / OpenShell upstream churn**. Pin compatible versions in the plugin's `package.json` and the policy preset; bump deliberately.
- **Reference-data integrity is currently filename-deep, not content-deep.** `refs fetch` skip-check is `Path.exists()`; only 3 of 8 sources verify an upstream MD5 at download time; `refs verify` only checks bgzip-EOF on `.vcf.gz/.vcf.bgz/.bcf`. Partial fetches, bit-rot, manual tampering, and 0-byte files all pass silently and feed downstream annotation. A manifest-anchored hardening plan is drafted at [docs/plans/active/refs-integrity-hardening/](../plans/active/refs-integrity-hardening/) (five phases, INV-R001 extension, no new invariant); parked until a real failure surfaces or the project owner needs clinician-forwardable provenance evidence. Indexed in [docs/TODO.md](../TODO.md).

---

## Relationship to Other Planning Artifacts

- The **grand plan** *informs* the per-feature [spec.md](../plans/templates/spec-template.md) and [development-plan.md](../plans/templates/development-plan-template.md) under `docs/plans/active/`.
- It does **not replace** them. Every implementation still goes through the [planning protocol](../plans/CLAUDE.md) with strict TDD.
- Per-feature plans cite this document for context (e.g., "this feature lives in Theme C, Horizon 2").
- The grand plan does not list per-feature plans by name. That coupling rots fast.
- Operational specifics — file paths, command syntax, network topology — live in [architecture.md](architecture.md). When the operational shape changes (e.g., a new extension surface, a new integration), update architecture.md first; touch the grand plan only if the *strategic* shape changed.

---

## How to Update This Document

The grand plan is a living document, but it is not edited casually.

Update when:

- A pillar interpretation needs sharpening.
- A capability theme's scope or sequence changes materially.
- A deferred decision becomes a taken decision (or vice versa).
- A horizon is reshaped because exit criteria changed.

Don't update for:

- Per-feature progress. That belongs in `docs/plans/active/<feature>/work-notes.md`.
- Tactical implementation choices that don't change the system's shape — those go in [architecture.md](architecture.md).
- Naming changes that aren't reflected in code or invariants.

When you do update, follow the [planning protocol](../plans/CLAUDE.md) for the change: file a small plan, propose the edit, land it. The grand plan moves slowly and on purpose.

# GenomeClaw — Grand Plan

**Status**: Living vision document
**Scope**: Strategic roadmap, not a tactical plan
**Audience**: Future-you, future contributors, and any agent planning new work
**Last Updated**: 2026-05-06

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

- **Host**: any Linux or macOS environment where NemoClaw runs and where the standard bioinformatics tools install (`samtools`, `bcftools`, `SnpEff`, `cyvcf2`, `pysam`, `DuckDB`, `PharmCAT`, etc.). The project is deliberately agnostic about the specific hardware — if NemoClaw and the toolchain run there, GenomeClaw runs there.
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
- Annotation against ClinVar, gnomAD, dbSNP at minimum.
- Materialization into the query layer with full provenance columns.
- Determinism guarantees and tests.

**Gates**: query-layer correctness; agentic interpretation needs structured, annotated input.
**Open**: which annotator (SnpEff vs. VEP vs. vcfanno) is the default; how regional restrictions on annotation datasets are handled.

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

**Gates**: this is where over-claim and over-deferral risk concentrate; gating is the point.
**Open**: report format(s) — Markdown, structured JSON, both?

### Theme F — Reanalysis loop

- Detect annotation source updates (e.g., ClinVar release).
- Replay specific findings against new annotations.
- Diff between previous and new interpretations.
- Surface "your old finding may have changed" prompts cautiously.

**Gates**: requires solid provenance + rebuildability; can't reanalyze if the original run isn't reproducible.
**Open**: cadence and trigger model.

### Theme G — Pharmacogenomics & specialized panels

- PharmCAT integration for actionable pharmacogenomic haplotypes.
- ACMG SF gene-list awareness.
- Haplotype-aware reporting and escalation markers.

**Gates**: highest clinical-adjacency surface area; depends on Themes B–E being solid.
**Open**: which PharmCAT outputs to surface and how.

### Theme H — Lifestyle and wellbeing optimization

- Surface lifestyle/optimization findings: caffeine metabolism (`CYP1A2`), caffeine sensitivity (`ADORA2A`), lactase persistence (`LCT`), muscle-fiber composition (`ACTN3`), circadian preference (`PER3`, `CLOCK`), alcohol metabolism (`ALDH2`, `ADH1B`), and similar.
- A `lifestyle` finding category in the schema with its own `evidence_quality` field (distinct from ClinVar review-status stars).
- Direct, actionable agent guidance on lifestyle topics, framed as **falsifiable experiments** rather than clinical guidelines (`INV-C001`).
- Explicit evidence-base calibration: the lifestyle literature is generally weaker than ClinVar-grade pathogenicity calls; the agent says so as a structural part of every lifestyle response.
- Optional "experiment templates" — e.g., a 2-week caffeine-cutoff trial, a lactose elimination trial — bundled into report scopes.

**Gates**: depends on Themes B–D being solid (findings infrastructure + agentic interpretation surface).
**Open**: which lifestyle finding categories ship first; how to express `evidence_quality` structurally; whether to bundle experiment templates into the report endpoint.

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

- Repository scaffolding under `packages/toolkit/` and `packages/nemoclaw-plugin/`, language toolchains (Python + TypeScript), CI shape.
- Host CLI entrypoint and subcommand framework (`genomeclaw-prep`).
- Plugin scaffolding with the manifest, policy preset, and Dockerfile already in place; first tool round-trip with the host service over HTTP.
- Ingest of Nebula Genomics outputs with integrity checks (Theme A).
- Minimal derived-store substrate with provenance columns (foundations of Theme C).
- Test infrastructure for the first-class categories (provenance, determinism, privacy default, evidence binding).

**Exit criteria**: a NemoClaw agent in the project owner's sandbox can call `genomeclaw_status` and receive structured JSON from the host service; the plugin is policy-denied any other egress.

### Horizon 2 — Annotation pipelines

*Scope themes: B, C*

- VCF normalization.
- ClinVar + gnomAD + dbSNP annotation paths.
- Materialization into DuckDB / GenomicSQLite.
- Determinism + provenance test coverage across the pipeline.
- Host service query endpoints (`/v1/variants`, `/v1/findings`).

**Exit criteria**: a deterministic, evidence-cited variant store can be rebuilt from a fixture, and `genomeclaw_findings` returns structured rows with provenance.

### Horizon 3 — Agentic interpretation surface

*Scope themes: D, partial E*

- Structured **findings** emission with categorical confidence.
- Evidence-record schema and joins.
- Plugin tool surface formalized; safe-by-default vs. opt-in classification implemented; bulk-class wired but disabled by default.
- Privacy-default tests across the full agent flow.

**Exit criteria**: a NemoClaw agent can drive the full ingest → annotate → query → finding loop; default-config integration tests confirm no outbound call goes anywhere other than the configured agent provider and the configured host service.

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

GenomeClaw orchestrates standard tools (samtools, bcftools, SnpEff, etc.); it does not reimplement them. Where a tool is missing or unfit, the project chooses *adoption* (use a different tool) or *adapter* (wrap with provenance) before *replacement*.

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

---

## Decisions Deferred

Each of these has a **revisit criterion** — a condition that, if met, moves the decision to "taken".

| Deferred decision | Revisit when |
|-------------------|--------------|
| **Imputation support** | A user request appears AND a local imputation tool fits a personal-host resource budget |
| **Standalone GUI** | Default is "no — NemoClaw is the UI"; revisit only if NemoClaw integration proves insufficient |
| **Multi-genome support (siblings/family)** | Single-user end-to-end works *and* a real use case appears |
| **Federation across multiple data sources** | Out of scope until single Nebula source works end-to-end |
| **Default annotator: SnpEff vs. VEP vs. vcfanno** | Theme B begins; evaluate against fixture performance + personal-host resource budget |
| **Report format(s) — Markdown / JSON / both** | Theme E begins |
| **Embedding model choice for Theme H** | Theme H is scoped; latency on a personal host is measured against an interactive-agent threshold |
| **Whether OpenClaw plugin commands can return structured JSON instead of text** | A v0 plugin ships and we can test live; if structured returns aren't supported, keep the `GENOMECLAW_JSON:` text-encoded format |
| **Whether to use OpenClaw `nodeHostCommands` to drop the host HTTP service** | After v1 ships, only if the host HTTP service becomes painful — and only with a documented third-party API path |
| **Whether to split GenomeClaw into two repos (`genomeclaw` toolkit + `genomeclaw-nemoclaw-plugin`)** | The toolkit earns the right to publish standalone, OR external NemoClaw users want the plugin without the genomics toolkit weight |

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

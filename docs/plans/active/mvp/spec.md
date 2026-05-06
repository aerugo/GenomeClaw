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
- [ ] **AC2**: The host service `genomeclaw-service` listens on `127.0.0.1:8643` and serves the v0 endpoints documented in [architecture.md](../../reference/architecture.md): `/v1/health`, `/v1/findings`, `/v1/findings/{id}`, `/v1/variants`, `/v1/variants/{key}`, `/v1/evidence/{ref}`, `/v1/provenance/{run-id}`, `/v1/report`.
- [ ] **AC3**: A sandbox image built from `packages/nemoclaw-plugin/sandbox/Dockerfile` and onboarded via `nemoclaw onboard --from <Dockerfile>` registers all five plugin tools and successfully reaches the host service via `host.openshell.internal`.
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
- Five plugin tools become callable agent tools after `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile`.
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

## Open Questions

- [ ] **Q1**: Which annotator ships in the MVP — SnpEff (simplest, default), VEP (richer), or vcfanno (fastest)? **Decision deferred to Phase 4; default is SnpEff** unless fixture performance shows it's unworkable.
- [ ] **Q2**: Does the OpenClaw plugin SDK support structured JSON tool returns, or does the MVP ship the v0 `GENOMECLAW_JSON:` text-encoding? **Decision deferred to Phase 5; live-test in the project owner's sandbox**.
- [ ] **Q3**: Should the MVP include the `/v1/report` endpoint or defer it? **Decision: include with `physician-handoff` and `lifestyle-experiment` scopes in Phase 6**.
- [ ] **Q4**: Topic-keyed lifestyle queries (`topic=caffeine`) vs. comma-separated `gene=` values (Story 9 user-stories gap A12). **Decision: comma-separated `gene=` for MVP; topic-keyed deferred**.

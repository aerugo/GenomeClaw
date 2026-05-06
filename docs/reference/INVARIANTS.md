# GenomeClaw Project Invariants

**Status**: Living document
**Version**: 1.4
**Last Updated**: 2026-05-06

This is the **canonical reference** for GenomeClaw's project invariants. Every implementation plan, phase plan, and substantive code review must reference applicable invariants by their canonical ID (e.g., `INV-D001`). The five top-level rules in the root [CLAUDE.md](../../CLAUDE.md) are formalized here.

If a rule is not in this document, it is not yet a project invariant. Convert hard rules into invariants here before treating them as enforceable.

---

## How to Use This Document

- **Plans** must enumerate applicable invariants in their **Critical Invariants to Respect** section, citing them by ID.
- **Phase plans** must list which invariants are *verified by tests* in that phase.
- **New invariants** are proposed in a development plan and promoted into this document only after the corresponding tests are merged.
- **Pull requests / reviews** that touch sensitive surfaces should cite the relevant `INV-xxx` so trade-offs are explicit.
- **Subagents** in `.claude/agents/` cite the invariants they are responsible for protecting.

---

## Invariant ID Convention

`INV-<CATEGORY><NUMBER>` where category is one of:

| Prefix | Category | Description |
|--------|----------|-------------|
| `INV-D` | Data & Source Artifact Integrity | Source-of-truth handling, raw file protection |
| `INV-E` | Evidence & Traceability | Citations, provenance of assistant claims |
| `INV-P` | Privacy & Sensitivity Boundaries | Local-first defaults, egress controls, secret separation |
| `INV-R` | Rebuildability & Provenance | Deterministic rebuilds, schema/tool versioning |
| `INV-C` | Communication & Clinical Boundary | Research vs. clinical framing, uncertainty handling |

Numbers are assigned in order of introduction within a category and never reused.

---

## INV-D001: Raw Genomic Files Are Source-of-Truth Artifacts

**Rule**: Source genomic artifacts (FASTQ, BAM, CRAM, VCF, gVCF, reference indexes, downloaded annotation datasets) are read-only by convention and must never be mutated in place.

**Requirements**:
- Pipelines write derived outputs to separate locations (e.g., `/mnt/genomeclaw/derived/<run-id>/`).
- Source paths are referenced, not modified — tools that would rewrite a source file (e.g., in-place sort, in-place index rebuild) must instead emit to a derived path.
- Reference and annotation downloads are versioned by URL or checksum, not overwritten.
- Any modification to a source-shaped file in `/mnt/genomeclaw/raw/` or `/mnt/genomeclaw/reference/` is treated as a bug.

**Where it applies**:
- All ingest, normalization, and annotation code under `packages/toolkit/src/genomeclaw_toolkit/prep/`.
- Any host-side tool that accepts paths under `/mnt/genomeclaw/raw/` or `/mnt/genomeclaw/reference/`.
- Any code path in `packages/toolkit/` that resolves source artifact paths.

**How to verify**:
- Pipeline tests assert source file content hash / mtime is unchanged after a run.
- File-system permissions: raw directories are mounted read-only at the OS layer; CI replicates this.
- Lint check forbids known mutating CLI flags against source paths.

---

## INV-D002: Raw Genomic Artifacts Are Host-Side Only

**Rule**: Raw genomic source files (FASTQ, BAM/CRAM, VCF, gVCF) and their immediate normalized intermediates must be processed exclusively by **host-side** code. They must never enter the OpenShell sandbox or any agent-reachable runtime.

**Requirements**:
- The agent-facing OpenShell sandbox has **no filesystem path** to `/mnt/genomeclaw/raw/` or to any other location holding raw artifacts.
- The host-side pipeline (`genomeclaw-prep` and equivalents) runs as ordinary host processes, outside any NemoClaw / OpenShell sandbox.
- The sandbox accesses only the *derived* store, and only through a host-side HTTP service that exposes minimum-sufficient queries (governed by `INV-P002`).
- Bioinformatics tooling (`samtools`, `bcftools`, `bgzip`, `tabix`, `bedtools`, `SnpEff`, `SnpSift`, `cyvcf2`, `pysam`, `PharmCAT`, etc.) is installed only on the host, never in the sandbox image.

**Where it applies**:
- Host installation of the bioinformatics CLI (`packages/toolkit/`).
- The GenomeClaw sandbox `Dockerfile` (`packages/nemoclaw-plugin/sandbox/Dockerfile`) — must not COPY or RUN against `data/raw/` or any genomic source binary.
- The OpenShell network policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`) — whitelists only the host service endpoint(s), never a generic file-server endpoint that would expose raw artifacts.

**How to verify**:
- A test asserting the built sandbox image does not contain bioinformatics tool binaries on PATH (`samtools`, `bcftools`, `bgzip`, `SnpEff.jar`, etc.).
- A test asserting the OpenShell policy preset for GenomeClaw exposes only the agreed host service endpoint, not a generic file-server endpoint.
- A test asserting the host service refuses to serve raw byte ranges from `/mnt/genomeclaw/raw/`.

---

## INV-E001: Assistant Claims Must Be Traceable to Evidence

**Rule**: Every user-facing biomedical statement in a report, finding, or assistant response must be linkable to one of: a normalized observation, an annotation record, a literature/evidence record, or an explicitly labeled heuristic.

**Requirements**:
- The output schema for findings, reports, and assistant turns includes an `evidence` field (or equivalent) referencing source records.
- Generated text without an evidence link is labeled as `speculation` or `heuristic` and visually/structurally distinguished from evidence-backed text.
- Citations preserve enough identity to re-fetch the source (variant ID, ClinVar ID, gnomAD frequency record, paper identifier, internal record ID).
- Removing an evidence record invalidates dependent findings on the next rebuild — they must not silently persist.

**Where it applies**:
- Host service finding/report endpoints in `packages/toolkit/src/genomeclaw_toolkit/service/`.
- Plugin tool handlers in `packages/nemoclaw-plugin/src/` that forward findings to the agent.
- Finding/evidence/provenance schemas in `packages/toolkit/src/genomeclaw_toolkit/schemas/`.
- Any code path that emits an interpretation to the user.

**How to verify**:
- Snapshot tests for host service responses that fail if an evidence-bearing block lacks a citation.
- Unit tests on the finding schema rejecting an interpretation without an evidence reference.
- Integration tests confirming that deleting an evidence record causes dependent findings to be marked stale on the next rebuild.

---

## INV-P001: Privacy Is the Default Operating Mode

**Rule**: User genomic data and derived phenotype-linked data are sensitive by default. They must not leave the local trusted environment **except** via the user-configured NemoClaw agent boundary (governed by `INV-P002`) or via an explicit, per-operation opt-in.

**Requirements**:
- **Genomic source files** (FASTQ, BAM/CRAM, VCF/gVCF) **never leave the device**, regardless of agent or integration configuration.
- The NemoClaw agent provider (e.g., Claude Opus, Gemini) is the only remote destination active by default for tool-call results, and is governed by `INV-P002`.
- Other remote integrations (literature lookups, alternative annotators, telemetry) are off by default and gated behind a per-operation, per-target opt-in.
- Secrets, tokens, and credentials live outside `data/` and are never committed.
- Logs, traces, and crash dumps must not contain raw variants, sample identifiers, or phenotype-linked content unless the user enabled verbose local logging.
- Redaction or summarization happens *before* any payload constructed for an external service is materialized.

**Where it applies**:
- Network-egress code paths in `packages/toolkit/` (host service HTTP layer, fetcher modules) and `packages/nemoclaw-plugin/src/` (plugin's outbound `fetch` calls).
- The OpenShell network policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`) — the runtime egress floor.
- Logging, telemetry, and error reporting in both packages.
- Host config and environment-variable handling; secrets must live outside `data/` and outside any committed config.
- Any caching layer that might serialize sensitive content.

**How to verify**:
- Privacy-default tests: with default config, simulate a full assistant flow and assert no outbound call carries genomic source files, and no outbound call goes to an endpoint other than the configured agent provider or the configured host service.
- Unit tests on redaction utilities.
- Lint check / type guard around an `egress_safe(...)` boundary type so unredacted payloads cannot reach external clients.

---

## INV-P002: Agent Egress Is a Named, Minimal-Sufficient Boundary

**Rule**: GenomeClaw is driven by a NemoClaw agent that typically runs on a cloud frontier model (e.g., OpenAI gpt-5.4, Claude Opus, Gemini). That model is a **named, user-configured egress destination** — not a free-for-all. Tool outputs that may travel to the agent must contain only the information the agent needs to answer the current request.

**Requirements**:
- The configured agent provider is named in user config and is changed only by deliberate user action.
- Tool outputs default to **minimal-sufficient** summaries: scoped findings, scoped variants, scoped evidence — not bulk dumps.
- Bulk transfer modes (e.g., shipping a whole VCF, a full annotation table, or unfiltered cohort data to the agent context) are gated behind explicit per-operation opt-in flags.
- Each plugin tool declares an `output_class` of `summary` or `bulk`. The default for any new tool is `summary`. Agent prompt scaffolding respects the classification.
- The agent boundary is the *only* remote destination for tool-call results by default. Other remote APIs are governed by `INV-P001`.

**Runtime enforcement layers** (all must hold):

1. **Host service shaping** — the host-side `genomeclaw-service` returns minimal-sufficient JSON over HTTP; bulk endpoints are distinct routes.
2. **Plugin output shaping** — the in-sandbox plugin re-shapes responses before returning to the agent, never widening fields the host service redacted.
3. **OpenShell L7 proxy + SSRF guard** — the GenomeClaw policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`) must declare both an explicit `endpoints` allow list and an `allowed_ips:` allowlist for the RFC 1918 ranges that `host.openshell.internal` resolves to (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). Without `allowed_ips:`, OpenShell's SSRF guard rejects requests with `ssrf_denied: blocked: internal address`, even if the policy block exists.

**Where it applies**:
- Host service route definitions and response shapes.
- The plugin's command/tool handlers (`packages/nemoclaw-plugin/src/**`).
- The GenomeClaw OpenShell policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`).
- Any future capability manifest emitted by the plugin.

**How to verify**:
- Tests asserting default-mode tool outputs exclude bulk fields (full VCF rows, full annotation tables, unfiltered evidence dumps).
- Tests asserting every registered plugin tool has an `output_class` tag.
- Tests asserting the policy preset includes the `allowed_ips:` allowlist and limits HTTP methods/paths to the read-only host-service surface.
- Live policy test (in a NemoClaw sandbox) asserting the sandbox can reach the configured host service URL only via the whitelisted host alias and port, and is denied at every other host or port.
- Default-config integration tests asserting no outbound call goes anywhere other than the configured agent endpoint and the configured host service.
- Snapshot tests on representative tool outputs to catch accidental field bloat over time.

---

## INV-R001: Derived Assistant Stores Must Stay Rebuildable

**Rule**: Any derived store (DuckDB tables, SQLite/GenomicSQLite indexes, annotation caches, vector indexes, chunked literature corpora, materialized report inputs) must be reproducible from the recorded source inputs and pipeline configuration, modulo declared non-determinism.

**Requirements**:
- Each pipeline step records: input identity (path + content hash or version), tool name, tool version, parameters, schema version, run timestamp.
- Re-running a step against the same inputs and tools yields byte-equivalent outputs unless non-determinism is declared and documented.
- Schema versions are explicit; migrations are scripted and idempotent.
- Hand-edited derived data is forbidden unless explicitly marked and justified inline.

**Where it applies**:
- All host-side pipeline code under `packages/toolkit/src/genomeclaw_toolkit/prep/`.
- Derived store schema and migration code under `packages/toolkit/src/genomeclaw_toolkit/service/` (or equivalent).
- Caching layers that persist between sessions.

**How to verify**:
- Determinism tests: run a pipeline twice on a fixture, compare outputs byte-for-byte.
- Provenance tests: every derived row has the required provenance columns populated (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`).
- Schema-version tests: the host service refuses to load a derived store whose schema version is missing or unknown.

---

## INV-C001: Separate Clinical Advice from Lifestyle and Research Assistance

**Rule**: GenomeClaw is positioned as a research, exploration, and lifestyle/wellbeing assistant — *not* a clinical decision-maker. The boundary is not "no opinions"; it is **clinical advice (diagnosis, prescription, dose, treatment changes) is out, lifestyle and wellbeing optimization is in**. Both surfaces must be evidence-cited, but they have different framing rules.

**Requirements**:
- Findings carry a structural `category` field. Four canonical categories drive `INV-C001`:
  - **`clinical-actionable`** (e.g., ACMG SF list pathogenic, PharmCAT actionable PGx haplotypes) — carries a `clinical_escalation` marker; agent recommends clinical confirmation; agent does not issue diagnostic, prescriptive, or dose-changing advice.
  - **`clinical-non-actionable`** (variants in clinical-relevance genes that are benign / VUS / unlikely-pathogenic) — no escalation marker; agent reports cleanly without alarmism and without unprompted clinician-deferral.
  - **`lifestyle`** (e.g., caffeine metabolism via `CYP1A2`, lactase persistence via `LCT`, muscle-fiber composition via `ACTN3`, circadian preference, alcohol metabolism via `ALDH2`/`ADH1B`) — no escalation marker; agent may give **direct lifestyle advice with calibrated evidence framing**; clinician-deferral is *not* the default response. Recommendations are framed as falsifiable experiments rather than guidelines.
  - **`mixed`** (a finding with both a lifestyle dimension and a clinical-actionability angle) — carries both lifestyle framing and an escalation marker; the agent disambiguates the two angles in its response.
- Lifestyle advice must still cite evidence and **calibrate uncertainty explicitly**. The evidence base for lifestyle findings is generally weaker than for ClinVar-grade pathogenicity calls; the agent acknowledges this when relevant. Lifestyle findings include an `evidence_quality` field (e.g., `meta-analysis`, `replicated-rct`, `observational`, `mechanistic-only`) distinct from ClinVar's review-status stars.
- Clinical findings use research/educational framing, never diagnostic phrasing.
- Uncertainty is expressed structurally (categorical confidence levels and evidence-quality fields), not buried in prose.
- Default report copy and prompt templates are reviewed for **over-claim *and* over-deferral** before merge — punting every lifestyle question to a clinician is its own failure mode.

**Where it applies**:
- Report assembly endpoints in `packages/toolkit/src/genomeclaw_toolkit/service/` and the report skeleton returned by the plugin's `genomeclaw_report` tool.
- Plugin tool descriptions (the `description` strings registered via `registerCommand` in `packages/nemoclaw-plugin/src/`) — these flow into the agent's tool catalog and shape its framing.
- The finding schema in `packages/toolkit/src/genomeclaw_toolkit/schemas/` where `category`, `clinical_escalation`, and `evidence_quality` are structural fields.
- Agent prompt templates rendered by the user's NemoClaw stack (out-of-repo but in-scope for review).

**How to verify**:
- Lint / snapshot tests on host service report responses and on plugin tool descriptions asserting absence of disallowed phrases for `clinical-actionable` findings (configurable list).
- Schema tests asserting that `clinical_escalation` is set on findings whose category is `clinical-actionable` and unset on `lifestyle` and `clinical-non-actionable`.
- Schema tests asserting `evidence_quality` is populated on `lifestyle` findings.
- Snapshot tests on lifestyle-category responses asserting that the response provides **direct guidance plus an evidence-quality caveat** — i.e., it does not punt to a clinician for what is a lifestyle question.
- Manual privacy-safety-reviewer agent pass before user-facing copy changes.

---

## Promoting a New Invariant

When a development plan proposes a new invariant:

1. The plan's `development-plan.md` includes a `Proposed New Invariants` section listing each candidate with rule + rationale.
2. The implementation lands tests that enforce the proposed rule.
3. After tests are green, this document is updated:
   - Pick the next available number in the appropriate category.
   - Fill in **Rule**, **Requirements**, **Where it applies**, **How to verify**.
   - Increment the **Version** at the top.
   - Update **Last Updated**.
4. The development plan moves to `docs/plans/completed/` with the invariant adoption noted.

If a proposed invariant is rejected, the plan records the rejection and rationale in `work-notes.md`.

---

## Invariant Index

| ID | Title | Category |
|----|-------|----------|
| INV-D001 | Raw Genomic Files Are Source-of-Truth Artifacts | Data |
| INV-D002 | Raw Genomic Artifacts Are Host-Side Only | Data |
| INV-E001 | Assistant Claims Must Be Traceable to Evidence | Evidence |
| INV-P001 | Privacy Is the Default Operating Mode | Privacy |
| INV-P002 | Agent Egress Is a Named, Minimal-Sufficient Boundary | Privacy |
| INV-R001 | Derived Assistant Stores Must Stay Rebuildable | Rebuildability |
| INV-C001 | Separate Research Assistance from Clinical Advice | Clinical Boundary |

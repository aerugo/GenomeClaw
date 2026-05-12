# GenomeClaw Project Invariants

**Status**: Living document
**Version**: 1.7
**Last Updated**: 2026-05-12

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
- The host-side pipeline (`genomeclaw` and equivalents) runs as ordinary host processes, outside any NemoClaw / OpenShell sandbox.
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

## INV-D003: Heavy Scratch Is Separated From Authoritative Outputs

**Rule**: Pipeline intermediates of meaningful size (anything > 1 GB) write to a scratch mount that is structurally distinct from the authoritative derived store. The scratch mount can be wiped without breaking derived; a mid-run crash on scratch can never produce a half-written artifact under derived. Originally proposed as "block-attached scratch, not virtiofs" — that framing was a Phase-2 implementation hypothesis that became unimplementable on colima 0.9.1; the underlying separation principle survives the pivot.

**Requirements**:
- Orchestrators (`ingest`, `normalize`, `annotate`, `materialize`, and any future CRAM→VCF / coverage / PRS step) write multi-GB intermediates to `/mnt/genomeclaw/scratch` (host-side: `<drive>/genomeclaw/_scratch/`), never to `/mnt/genomeclaw/derived`.
- Per-step shards are allocated via `shard_scratch(step, run_id, *, shard, base)` (a context manager): `<scratch>/<step>/<run-id>/<shard>/`. Cleanup runs on `__exit__`, even on exception, so zombie scratch dirs cannot accumulate.
- Final artifact promotion goes through `atomic_promote(src, dst)`: copy + fsync(file) + within-FS rename + fsync(parent dir). The destination directory under `derived/` never observes a partially-written file.
- Pre-flight assertions (`assert_derived_writable`, `assert_scratch_writable`) run at every orchestrator entry — a missing or read-only scratch mount is a typed `PreflightError` with a `genomeclaw host setup` hint.
- The setup orchestrator creates both mounts on the canonical layout; the container shim binds both at every container entry.

**Where it applies**:
- All orchestrators under `packages/toolkit/src/genomeclaw_toolkit/prep/` that emit large intermediates.
- The scratch-primitives library `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py` (`shard_scratch`, `atomic_promote`).
- The pre-flight assertion library `packages/toolkit/src/genomeclaw_toolkit/prep/preflight.py`.
- The setup orchestrator under `packages/toolkit/src/genomeclaw_toolkit/prep/setup/`.
- The host-side container shim `bin/genomeclaw`.

**How to verify**:
- `shard_scratch` tests assert per-step purge on success and on exception — no zombie scratch dirs.
- `atomic_promote` tests assert crash-safety: an interrupted promotion leaves `derived/` byte-identical; the orphaned `.tmp` lives on scratch and is harmless.
- Setup tests (`test_setup_execute.py`) assert the post-state layout contains all four canonical subdirs (`raw`, `reference`, `derived`, `_scratch`).
- Pre-flight tests assert each canonical mount-shape failure raises a typed exception with a fixable message.
- Doctor (`genomeclaw host doctor`) host-side existence + write probes for `derived/` and `_scratch/` give the user a single command to confirm the structural separation is intact.
- A scratch-discipline integration test observes write targets during a real `annotate` run and asserts every > 1 GB target is under `/mnt/genomeclaw/scratch`, none under `/mnt/genomeclaw/derived`. (Replaces the originally-proposed static lint rule, which couldn't reliably distinguish "final artifact" from "heavy scratch" — both write to disk, both are large.)

---

## INV-D004: Destructive Operations Require Explicit Confirmation

**Rule**: Any CLI command that mutates host state outside `derived/` (reformats a disk, ejects a drive, modifies colima/lima state, alters the canonical mount layout) requires one of two deliberate consents before it executes: an explicit `--yes` flag on the command line, or an interactive TTY where the user types an operation-specific phrase (the typed-confirmation pattern). Without either, the command refuses with exit code 2 (usage error) and an error envelope naming both ways forward.

**Requirements**:
- Destructive commands invoke `genomeclaw_toolkit._cli.confirm.require_destructive_confirmation()` (or equivalent gate) before any irreversible action.
- The typed-confirmation phrase is operation-specific (e.g., `REFORMAT GENOMECLAW DRIVE` for `host setup --force-reset`; the drive's mount-point basename for `host eject`). Generic yes/no prompts are not sufficient — the typed-phrase pattern is preferred because it prevents thoughtless `y\n` muscle-memory.
- Non-TTY invocation without `--yes` always refuses. This protects scripts and CI from accidental destructive flows.
- The confirmation gate is independent of other safety bypass flags (e.g., `host eject --force` bypasses the in-flight-pipeline check but does **not** imply confirmation; the user must pass `--yes --force` together).
- The error envelope on refusal names both routes forward (`--yes` and the typed phrase) in `suggested_actions` so the user / agent can pick the appropriate one.

**Where it applies**:
- `genomeclaw host setup --force-reset` (the destructive drive-reformat path).
- `genomeclaw host eject`.
- Any future command that mutates host state outside `derived/` (e.g., a hypothetical `host reset` or `host wipe-cache`).
- The `_cli/confirm.py` helper is the single seam for this invariant; new commands gain enforcement by calling it.

**How to verify**:
- Per-command refusal tests (`test_cli_host_setup_confirmation.py`, `test_cli_host_eject_confirmation.py`) cover both refusal paths: non-TTY without `--yes` → exit 2, and TTY with wrong-phrase → exit 2.
- Per-command accept tests cover both consent paths: `--yes` on non-TTY → proceeds, and typed-phrase on TTY → proceeds.
- Integration tests assert that `--force` (the pipeline-safety bypass) is independent of `--yes` — passing `--force` alone on non-TTY still refuses.
- The error envelope's `suggested_actions` is asserted to include both routes forward in the refusal-path tests.

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
- **Curated lifestyle calibration via `reference/curated_notes/`** *(v1.5; per [MVP spec Q9](../plans/active/mvp/spec.md))*: lifestyle findings may cite a `gene_note:<gene>` evidence reference resolving to a host-side, user-authored markdown note under `reference/curated_notes/<gene>.md`. Companion topic notes resolve under `reference/curated_notes/topics/<topic>.md` (e.g., `topic:hard-genes` per Q7). The note carries the project owner's calibrated framing of the variant's effect, evidence quality, and any disclosure language. The structured `evidence_quality` field above remains in the schema for future-proofing but is **not the primary calibration surface** in v0; the agent composes lifestyle responses from the user's variant call plus the curated note's framing, in the user's voice. This pattern is uniquely well-suited to single-user systems (the user is the curator; the agent is the reader) and uniquely poorly-suited to multi-user systems.
- Clinical findings use research/educational framing, never diagnostic phrasing.
- Uncertainty is expressed structurally (categorical confidence levels and evidence-quality fields), not buried in prose.
- Default report copy and prompt templates are reviewed for **over-claim *and* over-deferral** before merge — punting every lifestyle question to a clinician is its own failure mode.

**Where it applies**:
- Agent-rendered prose for report-shaped responses (assembled by the agent from `/v1/findings` + `/v1/health` plus its training; there is no host-service `/v1/report` endpoint in v0). Snapshot tests on the agent's rendered output against fixture conversations are the verification surface.
- Plugin tool descriptions (the `description` strings registered via `registerTool` in `packages/nemoclaw-plugin/src/`) — these flow into the agent's tool catalog and shape its framing.
- The finding schema in `packages/toolkit/src/genomeclaw_toolkit/schemas/` where `category`, `clinical_escalation`, and `evidence_quality` are structural fields.
- Agent prompt templates rendered by the user's NemoClaw stack (out-of-repo but in-scope for review).
- The `reference/curated_notes/<gene>.md` and `reference/curated_notes/topics/<topic>.md` files *(v1.5; per [MVP spec Q9](../plans/active/mvp/spec.md))*. Editing a curated note is a user-facing-copy change. The privacy-safety-reviewer agent reviews curated-note diffs before merge.

**How to verify**:
- Lint / snapshot tests on host service report responses and on plugin tool descriptions asserting absence of disallowed phrases for `clinical-actionable` findings (configurable list).
- Schema tests asserting that `clinical_escalation` is set on findings whose category is `clinical-actionable` and unset on `lifestyle` and `clinical-non-actionable`.
- Schema tests asserting `evidence_quality` is populated on `lifestyle` findings.
- Snapshot tests on lifestyle-category responses asserting that the response provides **direct guidance plus an evidence-quality caveat** — i.e., it does not punt to a clinician for what is a lifestyle question.
- Snapshot tests on lifestyle-category responses asserting that the agent cites a `gene_note:<gene>` evidence reference and that the response prose tracks the curated note's framing — no new claims introduced by the agent that aren't in the note. Failure modes: agent over-extending the note ("the note doesn't say that"), agent ignoring the note (over-deferral or generic clinical-deferral on a lifestyle question). *(v1.5)*
- Manual privacy-safety-reviewer agent pass before user-facing copy changes (including curated-note diffs).

---

## INV-C002: CLI Output Contract Stability

**Rule**: Every `genomeclaw` subcommand provides a `--json` mode whose stdout payload conforms to a versioned schema. The schema version travels with every payload as the `cli_output_schema_version` field. Stdout in `--json` mode is reserved for the structured result (single envelope, or NDJSON event stream); stderr is for progress, log, and diagnostic output. Adding new optional fields is additive (no version bump); renaming or removing fields requires a major-version bump and a deprecation cycle.

**Requirements**:
- Every command's `--json` output is a JSON object (or NDJSON stream of objects) carrying `cli_output_schema_version` at the envelope level.
- Two output modes coexist:
  - **One-shot envelope** for short commands: a single line `{"cli_output_schema_version": "1.0", "command": "...", "payload": {...}}` on stdout.
  - **NDJSON stream** for long-running commands: a first-line envelope `{"cli_output_schema_version": "1.0", "command": "...", "stream": true}` followed by one event object per line. The `"stream": true` field is the discriminator agents use to branch on stream-vs-envelope.
- Stdout is reserved for the structured result in `--json` mode. Rich-progress output, logs, and diagnostic prints go to stderr. The fetcher (`prep/fetch.py`) and any orchestrator that grew a `progress_callback` parameter suppress their legacy stdout prints when the callback is wired — the callback is the canonical surface for user-facing output.
- Trailing error envelopes (when a command fails mid-stream) go to **stderr** so they don't corrupt the stream. The `_cli.output.stdout_already_consumed` sentinel tracks whether a payload has been emitted; the exception boundary routes the error envelope accordingly.
- The per-command JSON shapes are documented in [docs/reference/cli-output-schemas.md](cli-output-schemas.md) with worked examples for both happy and failure paths.
- Field additions don't bump the version. Field renames or removals require a major version bump (`1.0` → `2.0`) and a deprecation cycle where both shapes are accepted.

**Where it applies**:
- `src/genomeclaw_toolkit/_cli/` — every command-handler module, the `emit()` dispatcher in `_cli/output.py`, the envelope writers in `commands/pipeline.py`, `commands/refs.py`, `commands/host.py`.
- `docs/reference/cli-output-schemas.md` — the single source of truth for the documented schemas + worked examples per command.
- The schema-version constant `CLI_OUTPUT_SCHEMA_VERSION = "1.0"` in `_cli/types/envelope.py`.

**How to verify**:
- Per-command JSON-shape tests assert `cli_output_schema_version == "1.0"` on every envelope.
- `test_cli_pipeline_events.py::test_pipeline_run_no_stdout_pollution_outside_events` asserts every stdout line in NDJSON mode parses as JSON — no legacy print pollution.
- `test_cli_refs_fetch.py::test_refs_fetch_json_emits_ndjson_event_stream` asserts the first-line envelope shape (`"stream": true`).
- The `stdout_already_consumed` sentinel is exercised by every test that emits a payload then triggers an error — the error envelope must appear on stderr, not stdout.
- `cli-output-schemas.md` documents the contract; PR reviewers cite this invariant when reviewing changes to the per-command schemas.

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
| INV-D003 | Heavy Scratch Is Separated From Authoritative Outputs | Data |
| INV-D004 | Destructive Operations Require Explicit Confirmation | Data |
| INV-E001 | Assistant Claims Must Be Traceable to Evidence | Evidence |
| INV-P001 | Privacy Is the Default Operating Mode | Privacy |
| INV-P002 | Agent Egress Is a Named, Minimal-Sufficient Boundary | Privacy |
| INV-R001 | Derived Assistant Stores Must Stay Rebuildable | Rebuildability |
| INV-C001 | Separate Clinical Advice from Lifestyle and Research Assistance | Clinical Boundary |
| INV-C002 | CLI Output Contract Stability | Communication |

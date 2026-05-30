# Feature: Host Profile — Personal, Family, and Medical Context for the Agent

**Status**: Draft
**Created**: 2026-05-28
**Owner**: aerugo
**Related Plans**:
- [completed/mvp](../../completed/mvp/) — established the agent + host-service surface this feature plugs into
- [completed/agent-research-and-synthesis](../../completed/agent-research-and-synthesis/) — the protocol this feature extends with a host-profile retrieval step
- [completed/smart-setup](../../completed/smart-setup/) — the onboarding flow this feature appends a profile-init stage to

---

## Goal

Give GenomeClaw a structured, host-side **host profile** (basic identity, biometrics, lifestyle, medical history, family history, goals) that is captured during onboarding, editable from the CLI, exposed by the host service, retrieved by the agent via a plugin tool, and required reading before any genome-informable reply.

## Background

Today the agent reasons about variants and PRS without knowing anything specific about the person who owns the genome. Concretely:

- The agent has no idea whether a CYP2C19 poor-metabolizer call matters today (it does if the user takes clopidogrel; it does not if they don't).
- The agent has no anchor for APOE counseling (a strong dementia family history changes the framing entirely).
- The agent cannot calibrate lifestyle advice (smoking status, current activity, current diet) against the user's actual context.
- The agent currently *invents* a user model from sandbox-side memory notes — which means each fresh sandbox starts blind, and the agent has no canonical "who am I talking to?" anchor distinct from accumulated conversational memory.

The result is generic interpretation that reads like a textbook. The fix is a small, structured, host-resident profile that the agent retrieves like any other genomeclaw_* tool — but as a mandatory step before genome-informable interpretation.

The data is **self-reported** (not clinical-grade). The agent must treat it as such: useful context, not a medical record.

## Acceptance Criteria

Each criterion maps to one or more tests in the phased plan.

- [ ] AC1: A typed `HostProfile` schema exists with versioned sections (`identity`, `biometrics`, `lifestyle`, `medical_history`, `family_history`, `meta`) and is validated end-to-end (Python Pydantic + TypeScript TypeBox mirror). `family_history` is a single bounded free-text field (no per-relative list). `identity.ancestry` captures both a free-text self-description (with worked examples for mixed ancestry) and a multi-select of friendly **reference-population groups** (European / African / East Asian / South Asian / American Indigenous-Latino / Middle Eastern-North African / Oceanian / Mixed-unsure / Prefer-not-to-say) which the schema maps internally to 1000G super-population codes for PRS-calibration consumption.
- [ ] AC2: The profile is persisted as a single JSON file at `<derived_root>/host_profile.json` with atomic write semantics, schema version, and audit fields (`created_at`, `updated_at`, `last_full_review_at`).
- [ ] AC3: `GET /v1/host/profile` returns the profile (with section-level completeness map) on the host service; when the profile file is absent, the endpoint returns HTTP 200 with `{"profile": null, "missing": true, "init_command": "genomeclaw host profile init"}` — the agent's structured no-profile signal.
- [ ] AC4: `GET /v1/host/profile/completeness` returns a compact summary (sections present / missing / partial) without the full payload, for cheap orientation calls.
- [ ] AC5: A new CLI command group `genomeclaw host profile` ships with `init`, `show`, `set`, `edit`, and `review` subcommands. All support `--json` per INV-C002. Interactive prompts use **Questionary** for modern UX (arrow-key single-select for enums, space-bar multi-select for ancestry groups + condition lists, validated inline text input, `[e]dit / [t]ype-inline / [s]kip` chooser for the family-history free-text field). The existing `confirm.py` stays for destructive-flow yes/no confirmations. Questionary writes to stderr so `--json` envelope output on stdout remains clean.
- [ ] AC6: `genomeclaw host setup` (interactive + smart variants) chains into `host profile init` at the end of onboarding so a fresh GenomeClaw install always finishes with a populated profile (or an explicit user-skip recorded in the profile's `meta.skipped_init_at` field).
- [ ] AC7: A `genomeclaw_host_profile` plugin tool is registered (TypeBox params: optional `sections: string[]`; output class: `summary`). It calls the host endpoint, returns the profile or the no-profile signal, and shapes the response per INV-P002.
- [ ] AC8: The OpenShell policy preset allows `GET /v1/host/profile` and `GET /v1/host/profile/completeness`; no write paths are added.
- [ ] AC9: The agent system prompt has a new mandatory step in the research-and-synthesis protocol: **Step 1.5 — Host profile context**, executed after `memory_search` and before the gene/PRS phase. The step calls `genomeclaw_host_profile` (full or sections-scoped) and incorporates the result into the synthesis.
- [ ] AC10: When sections of the profile relevant to the current question are empty or `null`, the agent must (a) name what is missing, (b) explain why it matters for *this* question, (c) recommend the specific CLI command to fill it in (`genomeclaw host profile set <section>` or `init`). A prompt-content gate and a `live_llm` behavioural gate enforce this.
- [ ] AC11: The `genomeclaw_host_profile` tool description in [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) explicitly enumerates the sections + the incompleteness-surfacing requirement so the agent's tool catalog teaches the contract.
- [ ] AC12: A new invariant **INV-C004** (Host Profile Context Must Inform Genome-Informable Turns) is promoted with: trace-walk gate (every health-interpretation trace contains a `genomeclaw_host_profile` call), prompt-content gate, and live_llm gate.
- [ ] AC13: Default-config privacy tests confirm the profile payload travels only to the configured agent provider and the host service — no third-party egress. The profile JSON file lives outside `data/raw/` and is not committed.

## Applicable Invariants

Reference [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md).

- **INV-D001** Raw Genomic Files Are Source-of-Truth — n/a directly; the profile is *self-reported*, not a derived store from raw variants. We note it explicitly so a reviewer doesn't conflate the profile with a derived genomics artifact.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — the profile JSON is host-side too; lives under `<derived_root>/`, never copied into the sandbox image, never bundled with logs.
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — when the agent grounds an interpretation in profile context (e.g., "given your current clopidogrel prescription, this CYP2C19 call matters because…"), the cited reference uses a new evidence kind `host_profile:<section>#<field>` so the trail is auditable.
- **INV-P001** Privacy Is the Default Operating Mode — the profile is *highly sensitive* (medical, family). It never leaves the host except via the named agent egress; it never appears in `web_search` queries; it is excluded from logs by default. Adding the endpoint adds **no new external egress**.
- **INV-P002** Agent Egress Is Named, Minimal-Sufficient — the new tool declares `output_class: "summary"`. The `sections` parameter lets the agent fetch a scoped subset when only one section is relevant (e.g., `sections: ["medical_history.medications"]` for a PGx question). Three-layer enforcement (host service shape, plugin re-shape, policy preset) must all hold.
- **INV-P003** Secrets in stdin/env, never argv — n/a (the profile contains no secrets).
- **INV-R001** Derived Stores Must Stay Rebuildable — n/a in the rebuild sense; the profile is user-authored, not derived. The schema *version* and audit timestamps are still required so a future migration is mechanical.
- **INV-C001** Separate Clinical Advice from Lifestyle/Research — profile content *enriches* this distinction: with medication context the agent can give cleaner PGx framing; with family history it can frame penetrance calibration without alarmism. The category-driven framing rules don't change.
- **INV-C002** CLI Output Contract Stability — every new `genomeclaw host profile ...` subcommand carries `cli_output_schema_version` and conforms to the documented per-command schema.
- **INV-A001** Agent Memory Provenance — when the agent persists a memory note grounded in profile context, the note's tool-calls list includes the `genomeclaw_host_profile` call and the relevant profile-section keys (NOT verbatim free-text fields like "describes feeling tired").
- **INV-A002** Synthesis Reasoning Floor — unchanged; any reply grounded in profile context is still a health-interpretation turn and runs at the model's reasoning ceiling.
- **INV-A004** Decline Taxonomy Must Traverse Every Layer — the profile's structured enums (sex, smoking status, relationship class, etc.) must be mirrored across Python Pydantic + TypeScript TypeBox + tool description, with a cross-language diff test catching drift.
- **INV-A005** Tool-Failure Narratives Match Trace Evidence — the agent must NOT paraphrase a successful 200 + `missing: true` host-profile response as a "tool failure"; it is a structured no-profile signal and must be reported as such.

## Proposed New Invariants

- **NEW INV-C004 Host Profile Context Must Inform Genome-Informable Turns** — for any genome-informable reply (health, lifestyle, fitness, diet, sleep, recovery, behavior, performance, anything where the user's genome is being interpreted), the agent's trace MUST contain at least one `genomeclaw_host_profile` invocation in this turn, OR the agent MUST surface "no host profile is set" and recommend `genomeclaw host profile init`. When the question hinges on a profile section that is empty (e.g., PGx without `medical_history.medications`), the reply MUST name the gap, explain why it matters for this question, and recommend the specific CLI command to fill it in. Rationale: a genome read without phenotype context yields generic interpretation; a structural retrieval rule is the only way to keep the agent honest about what it does and doesn't know about the user.

## Technical Requirements

### Source Data Inputs

- User keyboard input (interactive prompts) during `genomeclaw host profile init` / `edit` / `set`.
- No file imports in v0 (no FHIR import, no 23andMe profile parsing). Out of scope.

### Derived Outputs

- `<derived_root>/host_profile.json` — single canonical file, atomically written. Sibling of the per-run derived directories (NOT inside a `<run-id>/` subdir).
- `<derived_root>/host_profile.audit.log` — append-only newline-delimited JSON audit log of profile mutations (field-level diffs, no value verbatim where free-text). Useful for the user inspecting their own change history.

### Schema / Migration Impact

- New module `packages/toolkit/src/genomeclaw_toolkit/schemas/host_profile.py` carrying the `HostProfile` Pydantic model with `ConfigDict(extra="forbid")` and a top-level `schema_version: Literal["host_profile/1.0"]`.
- The DuckDB derived stores are NOT touched. The profile is a flat JSON file at the host-profile-root; this keeps profile mutation cheap and decouples it from variant-store rebuild cycles.
- A `migrate_host_profile(profile_dict)` helper is included from day one so future `host_profile/1.1` upgrades have a clear seam.

### Pipeline / Workflow Impact

- `prep/setup/__init__.py` (or `run_interactive` / `run_smart`) gains a final stage: invoke `host profile init` interactively, with a `--skip-profile` opt-out for non-interactive setup. The stage is non-blocking — a sandbox can be brought online without a profile — but the profile gap surfaces on the agent's first genome-informable turn.

### Agent / UX Impact

- `packages/nemoclaw-plugin/src/index.ts`: register a new `genomeclaw_host_profile` tool.
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`: add **Step 1.5 — Host profile context** to § 4, add the tool to § 1, add a profile-gap framing pattern to § 9 (When you are uncertain), and add a privacy line to § 8.
- `packages/nemoclaw-plugin/policy-preset.yaml`: allow `GET /v1/host/profile` and `GET /v1/host/profile/completeness`.

### External Dependencies

- **Questionary** *(new, Phase 2)*: pure-Python interactive prompts (`select`, `checkbox`, `text`, `confirm`, `path`). Added to `packages/toolkit/pyproject.toml`. No native dependencies. Respects stderr/stdout discipline so `--json` envelope output on stdout stays clean.
- Existing: Pydantic, Typer, TypeBox, FastAPI, Rich.

## Privacy & Safety Considerations

- **Boundary scan**: the profile is the *most identifying* host-side dataset GenomeClaw stores after the raw genome itself (medical conditions, family history, current medications). Three boundaries matter:
  1. Host → agent provider: governed by INV-P001 + INV-P002. The agent provider is already a named egress; adding profile data to its envelope does not add a new egress destination, but the *content sensitivity* climbs significantly.
  2. Host → managed `web_search` provider: the profile MUST NEVER appear in a web search query. Topic-only payload rule (INV-P001).
  3. Host → logs / crash dumps: profile fields must be excluded from log records by default. A redaction list is added to the logging configuration.
- **Default-off remote calls**: no new remote calls introduced. The host endpoint is local. The plugin tool only talks to `host.openshell.internal`. No third-party APIs.
- **Redaction surface**: free-text fields (medical-history `notes`, family-history `notes`, goals `red_flags`) are tagged in the schema with `freetext: True` metadata. Any future serialization to an external boundary (e.g., a hypothetical telemetry channel) must drop freetext fields unless the user has explicitly opted in per-operation.
- **Clinical escalation**: the profile is *self-reported*, not a clinical record. The agent must never paraphrase a profile field as a diagnosis. INV-C001's category framing still applies to interpretations grounded in profile context.
- **Audit trail**: the `host_profile.audit.log` records timestamped diffs of which sections changed. This lets the user inspect their own profile-edit history and gives privacy-safety reviewers a surface to audit on real data.
- **Per-section sensitivity**: `family_history` is special — it carries narrative information about people other than the genome owner (parents, siblings, etc.). Because v0 captures family history as a single free-text field (per the dropped-structured-list decision), the verbatim narrative MAY contain identifying detail. The schema tags the field `freetext: True` + `family_member_narrative: True`; the agent system prompt instructs the agent NOT to copy verbatim family-history text into memory notes (paraphrase at relation-class + condition + age-class granularity), NOT to include it in `web_search` payloads, and to redact it from any future external boundary.

A privacy-safety-reviewer agent pass is mandatory before Phase 4 ships (system prompt change crosses the agent boundary).

## Out of Scope

- **Multi-user profiles**. v0 supports one profile per host (matches the single-genome-owner deployment model).
- **Cloud sync or remote backup** of the profile. Local-only.
- **FHIR / HL7 / EHR import**. v0 captures self-reported data only; structured medical-record imports are a future phase.
- **23andMe / Ancestry profile import**. Same reasoning.
- **Wearable integrations** (Oura, Whoop, Apple Health). Future.
- **Photo / image / lab-result uploads**. Out.
- **Editable from the sandbox** (agent side). The agent reads the profile; only the host-side CLI writes. Keeping the write surface host-side preserves the existing trust boundary.
- **Free-form long-form narrative beyond the bounded fields**. `family_history` is a single bounded (~4000 char) free-text field by design; medical-history sub-fields stay structured with bounded freetext notes. No "write your life story" surface.
- **Structured per-relative family history.** A list-of-relatives shape (relation enum, age-at-onset, age-at-death, etc.) was considered and explicitly dropped for v0 — too much friction at onboarding, and the agent reads narrative family history at the right level of granularity on its own. A future plan can revisit if downstream consumers need structured access.
- **Goals / primary questions section.** The "what do you want GenomeClaw to help you explore?" capture was considered and dropped from v0. The agent infers user goals from conversation. If the gap becomes load-bearing, a future plan adds a structured goals layer.

## Dependencies

- Working `genomeclaw-service` (already shipped).
- Working `genomeclaw host setup` flow (already shipped).
- `genomeclaw_status` tool + memory tools in the agent surface (already shipped).
- Privacy-safety-reviewer agent (already available).

## Open Questions

- [x] ~~Q1: Goals section structure.~~ **Resolved (2026-05-28)**: dropped from v0 per user feedback. The agent infers goals from conversation; if the gap becomes load-bearing, a future plan can add a structured goals layer.
- [x] ~~Q2: Ancestry capture — population codes?~~ **Resolved (2026-05-28)**: yes, but presented to the user as **friendly reference-population groups** (European, African, East Asian, South Asian, American Indigenous-Latino, Middle Eastern-North African, Oceanian, Mixed-unsure, Prefer-not-to-say) selected via space-bar multi-select. The schema maps these internally to 1000G super-population codes (`EUR`, `AFR`, `EAS`, `SAS`, `AMR`, `MID`, `OCE`, `ADM`) for PRS-calibration consumption. Mixed ancestry is captured both in the free-text `self_reported` field (with worked examples like "50% Icelandic, 25% Czech, 25% Kazakh") AND as multiple selected groups.
- [x] ~~Q3: Audit log location.~~ **Resolved**: same dir as the JSON, `host_profile.audit.log`.
- [x] ~~Q4: Empty section serialization.~~ **Resolved**: explicit nulls.
- [x] ~~Q5: Quick vs thorough init.~~ **Resolved**: `init --quick` = identity (incl. ancestry) only; default `init` walks identity → biometrics → lifestyle → medical history → family history (goals dropped).
- [x] ~~Q6: Profile retrieval caching.~~ **Resolved**: always re-fetch per turn.
- [ ] Q7 *(new)*: Should the ancestry friendly-group descriptions in the CLI prompt link to a short doc explaining *why* population groups affect PRS calibration, or keep it strictly inline? **Tentative answer**: inline one-liner per group + a `[?]` key opens a short doc panel. Decide at Phase 2 prompt design.
- [ ] Q8 *(new)*: For the family-history free-text field, should the CLI offer a "scaffold prompt" pre-populated in `$EDITOR` (with comment-line questions: "Parents — any heart disease, cancer, diabetes, dementia?", "Grandparents — what did they die of?", "Anyone diagnosed with a genetic condition?")? **Tentative answer**: yes — the scaffold dramatically reduces blank-page friction. Decide at Phase 2.

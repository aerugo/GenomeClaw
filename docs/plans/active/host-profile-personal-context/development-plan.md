# Host Profile — Personal, Family, and Medical Context — Development Plan

**Status**: Draft
**Created**: 2026-05-28
**Branch**: `feature/host-profile-personal-context`
**Spec**: [spec.md](spec.md)

---

## Summary

Capture the genome owner's basic identity, biometrics, lifestyle, medical history, family history, and goals as a structured host-side JSON file. Expose it via a host-service endpoint, an OpenShell-policy-allowed plugin tool, and a new mandatory step in the agent's research-and-synthesis protocol so the agent always has phenotype context before interpreting variants. Make incompleteness visible: when the profile is missing or thin on sections relevant to the question, the agent surfaces the gap and recommends the CLI command to fix it.

## Critical Invariants to Respect

- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — the host profile JSON is host-side too; lives under `<derived_root>/host_profile.json`, never copied into the sandbox image, never bundled into telemetry.
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — interpretations grounded in profile context cite a new evidence kind `host_profile:<section>#<field>`. The profile is *self-reported* evidence — the agent treats it as such (no diagnostic phrasing).
- **INV-P001** Privacy Is the Default Operating Mode — profile data NEVER appears in `web_search` queries. The endpoint is local. Profile fields are excluded from default logging.
- **INV-P002** Agent Egress Is Named, Minimal-Sufficient — the new `genomeclaw_host_profile` tool defaults to `output_class: "summary"`. A `sections` argument lets the agent fetch a scoped subset. The policy preset gains exactly two new GET paths and zero write paths.
- **INV-C001** Separate Clinical Advice from Lifestyle/Research — profile context enriches the existing category-driven framing. The agent must not paraphrase self-reported conditions as confirmed diagnoses.
- **INV-C002** CLI Output Contract Stability — every new `host profile *` subcommand carries `cli_output_schema_version` and a documented per-command schema.
- **INV-A001** Agent Memory Provenance — when the agent persists a memory note grounded in profile context, the note's tool-calls list includes the `genomeclaw_host_profile` call. Free-text profile fields are NEVER copied verbatim into memory notes (the note records "user reports current clopidogrel" not the user's verbatim free-text).
- **INV-A004** Decline Taxonomy Must Traverse Every Layer — structured enums in the profile (sex, smoking status, relationship class, condition status) mirror Python ↔ TypeScript ↔ tool description with a cross-language diff test.
- **INV-A005** Tool-Failure Narratives Match Trace Evidence — the agent must NOT paraphrase a 200 + `missing: true` profile response as a tool failure. The system prompt teaches this case explicitly.

## Proposed New Invariants

- **NEW INV-C004 Host Profile Context Must Inform Genome-Informable Turns** *(promoted at Phase 5)*. Rule, requirements, where-applies, and verification language are in [spec.md](spec.md#proposed-new-invariants). The invariant is verified by (a) a trace-walk gate, (b) a system-prompt content gate, and (c) a `live_llm` behavioural gate. Failing tests land in Phase 4; promotion to `INVARIANTS.md` lands in Phase 5 after the tests are stable.

## Current State Analysis

GenomeClaw v0 has no host-side personal-context store. The agent's only sources of who-the-user-is are:

- `genomeclaw_status` (run id, schema version, sample id) — identity-free at the person level.
- Accumulated sandbox memory notes — *per-sandbox*, lost on rebuild, never grounded in self-report.
- The user's verbatim turn text — ephemeral.

A fresh sandbox starts blind. Every health-interpretation turn implicitly invents a user model from generic priors. This is the gap.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| [packages/toolkit/src/genomeclaw_toolkit/service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) | FastAPI app factory; routes `/v1/findings`, `/v1/variants`, `/v1/pgs/*`, etc. | Add `GET /v1/host/profile`, `GET /v1/host/profile/completeness`. |
| [packages/toolkit/src/genomeclaw_toolkit/service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py) | Read-only DuckDB store accessor. | Add `query_host_profile(derived_root)` + `query_host_profile_completeness(derived_root)`. The profile is JSON-on-disk, not DuckDB. |
| [packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py) | `host doctor`, `host setup`, `host eject`. | Add `host profile init / show / set / edit / review` subgroup. |
| [packages/toolkit/pyproject.toml](../../../../packages/toolkit/pyproject.toml) | Existing deps. | Add `questionary>=2.0` for arrow-key / multi-select prompts. |
| [packages/toolkit/src/genomeclaw_toolkit/_cli/renderers/host.py](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/renderers/host.py) | Rich-rendered doctor tables. | Add `render_profile`, `render_profile_completeness`. |
| [packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py) | `run_interactive`, `run_smart` setup orchestrators. | Chain into `host profile init` as the final stage (with `--skip-profile` opt-out and a recorded `meta.skipped_init_at` field). |
| [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts) | Tool registry. | Register `genomeclaw_host_profile` with TypeBox params + `output_class: "summary"`. Mirror profile enums (Sex, SmokingStatus, ConditionStatus, RelationshipClass, AncestryCode) as TypeBox Union literals. |
| [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml) | Allow list for v0 endpoints. | Add `GET /v1/host/profile`, `GET /v1/host/profile/completeness`. |
| [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) | Research-and-synthesis protocol (§ 4), tool catalog (§ 1), privacy contract (§ 8), uncertainty (§ 9). | Add Step 1.5 (Host profile context) to § 4; add tool to § 1; add profile-gap framing pattern to § 9; add a privacy line to § 8. |
| [packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py](../../../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py) | Pins the policy preset's allowed paths. | Extend `_ALLOWED_V0_PATHS` with the two new GETs. |
| [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py) | Prompt-content gates. | Add `test_invC004_system_prompt_requires_host_profile_step`, `test_invC004_system_prompt_teaches_profile_gap_framing`, `test_system_prompt_includes_host_profile_tool`. |
| [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) | Canonical invariant list. | Add INV-C004 in Clinical Boundary category after Phase 5's tests are stable. |
| [docs/reference/cli-output-schemas.md](../../../reference/cli-output-schemas.md) | Per-command CLI JSON schemas. | Document `host profile init / show / set / edit / review` envelope shapes. |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/host_profile.py` | Pydantic `HostProfile` model + section sub-models + enums + `migrate_host_profile()` stub. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/__init__.py` | Module init. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/store.py` | Read / atomic-write / completeness logic for the JSON file. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/audit.py` | Field-level diff + append to `host_profile.audit.log`. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/interactive.py` | Prompt sequences (one function per section) used by `host profile init / set / edit`. |
| `packages/toolkit/tests/unit/test_host_profile_schema.py` | Schema validation tests (required fields, enums, freetext bounds, schema_version literal). |
| `packages/toolkit/tests/unit/test_host_profile_store.py` | Atomic-write, read-on-missing, audit-log append. |
| `packages/toolkit/tests/integration/test_service_host_profile_endpoint.py` | End-to-end `/v1/host/profile` and `/v1/host/profile/completeness` against a temp `<derived_root>`. |
| `packages/toolkit/tests/integration/test_cli_host_profile.py` | `host profile init / show / set / edit / review` interactive + `--json` modes. |
| `packages/toolkit/tests/privacy/test_invP001_host_profile_default_egress.py` | Default config: no profile content leaves the host except to the configured agent and the local service. |
| `packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py` | Cross-language diff: Python enums ⇔ TypeBox literals ⇔ tool description. |
| `packages/toolkit/tests/invariants/test_invC004_trace_walk_host_profile_called.py` | Trace-walk gate: every health-interpretation trace in `docs/reports/` (dated ≥ Phase 4 land date) contains a `genomeclaw_host_profile` invocation. |
| `packages/nemoclaw-plugin/tests/host_profile_tool.test.ts` | Plugin-side TypeBox validation + `safeCall` envelope tests for the new tool. |

## Solution Design

### Data flow

```text
                       ┌─────────────────────────────────────────────────┐
                       │ Host (filesystem)                               │
                       │                                                 │
                       │ <derived_root>/host_profile.json   <- canonical│
                       │ <derived_root>/host_profile.audit.log <- diffs  │
                       └────────────────────┬────────────────────────────┘
                                            │
                                            │ read/write (interactive)
                                            │
                       ┌────────────────────▼────────────────────────────┐
                       │ CLI:  genomeclaw host profile {init,show,set,   │
                       │       edit, review}                             │
                       │       (Typer + Pydantic + Rich; --json mode)    │
                       └────────────────────┬────────────────────────────┘
                                            │ read-only
                                            │
                       ┌────────────────────▼────────────────────────────┐
                       │ genomeclaw-service (FastAPI, local)             │
                       │ GET /v1/host/profile                            │
                       │ GET /v1/host/profile/completeness               │
                       │ (both go through Pydantic response models)      │
                       └────────────────────┬────────────────────────────┘
                                            │ HTTP (sandbox → host)
                                            │ policy-preset allows
                                            │
                       ┌────────────────────▼────────────────────────────┐
                       │ NemoClaw plugin (in sandbox)                    │
                       │ genomeclaw_host_profile tool                    │
                       │ (TypeBox params, output_class: summary,         │
                       │  safeCall + wrapHostResponse)                   │
                       └────────────────────┬────────────────────────────┘
                                            │ agent context
                                            │
                       ┌────────────────────▼────────────────────────────┐
                       │ Agent (configured frontier model)               │
                       │ research-and-synthesis Step 1.5: HOST PROFILE   │
                       │ → incorporates into synthesis,                  │
                       │ → surfaces missing sections to user             │
                       │ → cites host_profile:<section>#<field>          │
                       └─────────────────────────────────────────────────┘
```

### Schema sketch

```text
HostProfile
├─ schema_version: Literal["host_profile/1.0"]
├─ meta: { created_at, updated_at, last_full_review_at, skipped_init_at, source: "self_report" }
├─ identity:
│    ├─ display_name
│    ├─ date_of_birth
│    ├─ sex_assigned_at_birth                  (enum: female / male / intersex / prefer_not_to_say)
│    ├─ gender_identity (optional, freetext)
│    └─ ancestry:
│         ├─ self_reported: str | None         (freetext ≤500 chars; mixed-ancestry examples in prompt)
│         ├─ groups: list[AncestryGroup]       (friendly multi-select enum; see below)
│         └─ population_codes: list[Pop1000G]  (derived from `groups` at write time; persisted for PRS-calibration consumption)
├─ biometrics: { height_cm?, weight_kg?, weight_recorded_at?, blood_type? }
├─ lifestyle: { smoking_status, alcohol_use, exercise_frequency, dietary_pattern (bounded), sleep_pattern (bounded) }
├─ medical_history:
│    ├─ conditions[]:   { name, diagnosis_year?, status, notes (bounded) }
│    ├─ medications[]:  { name, dose?, indication? }
│    ├─ allergies[]:    { allergen, reaction? }
│    └─ procedures[]:   { name, year? }
└─ family_history:
     ├─ notes: str | None                      (single bounded freetext field, ≤4000 chars; tagged family_member_narrative: True)
     └─ opted_out: bool = False

Friendly AncestryGroup → 1000G super-population mapping (the user picks groups via multi-select; the schema records both):

  European                        → EUR
  African                         → AFR
  East Asian                      → EAS
  South Asian                     → SAS
  American Indigenous / Latino    → AMR
  Middle Eastern / North African  → MID
  Oceanian                        → OCE
  Mixed / admixed / unsure        → ADM
  Prefer not to say               → (no code persisted)

Free-text fields are bounded (`max_length`) and tagged `freetext: True` for the egress-redaction layer.
The `goals` section was considered and dropped from v0 — the agent infers goals from conversation.
```

### Key Design Decisions

1. **JSON on disk, not a DuckDB table**. The profile is small, hand-edited, and has no relationship to the variant store's rebuild cycle. JSON keeps interactive edits cheap and makes the audit log trivially diff-able. The DuckDB store's rebuild lifecycle would otherwise force profile re-entry.
2. **Single file at `<derived_root>/host_profile.json`, not under a `<run-id>/` subdir**. The profile is host-wide and survives runs. Living at the derived root makes it visible alongside the symlinked `CURRENT` run dir.
3. **Atomic write via temp-file + os.replace**. Standard pattern; matches the rest of the toolkit's atomic-write discipline.
4. **Mandatory tool call in agent protocol, not opportunistic memory recall**. Memory-based context would silently go stale between sandbox rebuilds and across edits. A fresh tool call per turn is cheap (~ 2-4 KB JSON) and removes the staleness failure mode.
5. **Section-scoped retrieval via `sections` param, not always-full**. Aligns with INV-P002's minimal-sufficient principle. For a PGx question the agent fetches `["medical_history.medications", "medical_history.allergies"]`; for a family-history-driven question it fetches `["family_history"]`. The completeness endpoint is cheaper still for the orientation pass.
6. **Free-text fields are tagged, not free-form**. Each freetext field carries a `max_length` and a schema-level `freetext: True` annotation so future egress redaction is mechanical.
7. **Self-report is named explicitly in `meta.source`**. The agent prompt teaches that self-reported conditions are NOT diagnoses. The schema makes that distinction structural.
8. **`host profile init` chained into `host setup`, not run separately**. A fresh GenomeClaw install ends with a populated profile. Users who skip get a recorded `skipped_init_at` field — the agent can see this and prompt for completion on the first relevant turn.
9. **Interactive UX uses Questionary, not raw stdin-readline**. The existing `_cli/confirm.py` stdin-readline pattern is fine for a yes/no destructive-confirmation gate, but it's wrong for a section walk with ~30 inputs. Questionary provides arrow-key single-select for enums (sex, smoking status, alcohol use, exercise frequency, blood type), space-bar multi-select for ancestry reference-population groups, validated inline text with re-prompt on bounds violations, and a `[e]dit / [t]ype-inline / [s]kip` chooser for the family-history free-text field. Questionary writes to stderr so the `--json` envelope on stdout stays clean (INV-C002 discipline preserved). Questionary is a new dependency on the toolkit's `pyproject.toml`; pure-Python, no native deps.
10. **Family history as a single bounded free-text field, not a structured per-relative list**. A `list[FamilyMember]` structure was considered and rejected for v0 — too much friction at onboarding ("now add another relative"), and the agent reads narrative family history at the right level of granularity on its own. The schema tags the field `family_member_narrative: True` so future egress-redaction passes can treat it with extra care. A future plan can revisit if downstream consumers need structured access.
11. **Goals section dropped from v0**. The "what do you want GenomeClaw to help you explore?" capture was considered and dropped per user feedback. The agent infers goals from conversation. If the gap becomes load-bearing in practice, a future plan adds a structured goals layer.
12. **Ancestry capture has two layers — friendly multi-select + free-text — both persisted**. The user picks reference-population groups via a space-bar multi-select with one-line plain-language descriptions per group (not raw `EUR/AFR/EAS/…` codes). The schema records both the friendly selections AND the derived 1000G super-population codes. The free-text `self_reported` field captures the nuance the multi-select can't (e.g., "50% Icelandic, 25% Czech, 25% Kazakh") — the prompt shows worked examples to dissolve mixed-ancestry blank-page hesitation. Internally, PRS-calibration code reads `population_codes`; the agent reads both layers when framing.

### Schema / Provenance Impact

- New: `HostProfile` Pydantic schema at version `host_profile/1.0`.
- The DuckDB variant store: untouched.
- Rebuild procedure: the profile is not a derived store; it is rebuilt only by interactive user edit. The `host_profile.audit.log` is the user-readable provenance trail.

### Privacy & Egress Impact

- **New network egress points**: none. The host endpoint is on `127.0.0.1` / `host.openshell.internal`; the policy preset adds two GETs and zero new external destinations.
- **New secret-handling surfaces**: none. The profile carries no credentials.
- **Redaction added**: default logging configuration excludes profile content from request/response logs. The `host_profile.audit.log` records field-level diffs with values for structured fields and a `<len=N chars>` placeholder for freetext fields.
- **Privacy-safety-reviewer pass** is invoked at the end of Phase 1 (schema design + storage location) and at the end of Phase 4 (system prompt + tool description). Both passes are blocking.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Schema + host-side storage + service endpoints | Pydantic validation, atomic write, audit log, `/v1/host/profile` + `/completeness` handler, INV-P001 default-egress | 18 |
| 2 | CLI subgroup + onboarding integration | `host profile init/show/set/edit/review`, interactive prompts, INV-C002 envelope shape, `host setup` → `init` chain | 14 |
| 3 | Plugin tool + policy preset + cross-language enum mirror | TypeBox params, `safeCall` envelope, INV-P002 shape, INV-A004 cross-language diff, policy preset gate | 9 |
| 4 | Agent system prompt + behavioural enforcement | Prompt-content gates, INV-C004 trace-walk gate (initially RED), `live_llm` profile-gap framing gate | 8 |
| 5 | INV-C004 promotion + docs + privacy-safety review pass | Promote INV-C004 to `INVARIANTS.md`, update `cli-output-schemas.md`, doc-draft → reference, privacy-safety-reviewer pass | 3 |

## Phase 1: Schema + storage + service endpoints

**Goal**: Land the typed `HostProfile`, the atomic JSON store with audit log, and the two read-only HTTP endpoints. No CLI, no agent surface yet.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `schemas/host_profile.py` with `HostProfile`, section sub-models, structured enums, and `migrate_host_profile()`.
2. `host_profile/store.py` with `read_profile`, `write_profile_atomic`, `compute_completeness`.
3. `host_profile/audit.py` with field-level diff + append-only log.
4. Two route handlers in `service/app.py` returning the new Pydantic response models.

### Invariants Enforced Here
- **INV-P001**: integration test confirms the host endpoint stays local; no outbound calls.
- **INV-D002**: schema test confirms the JSON file path resolves under `<derived_root>/` and never inside `<sandbox>/`.
- **INV-R001** (lightweight): schema_version literal + `migrate_*` stub demonstrate the migration seam.
- **INV-C002**: response models follow the same `extra="forbid"` style as the rest of the toolkit (envelope discipline starts at Phase 2).

### Success Criteria
- [ ] All phase tests pass (RED → GREEN → REFACTOR visible).
- [ ] `ruff` + `mypy` clean for new modules.
- [ ] At least one test per enforced invariant.
- [ ] `GET /v1/host/profile` returns `{"profile": null, "missing": true, "init_command": "genomeclaw host profile init"}` on a fresh `<derived_root>`.

## Phase 2: CLI subgroup + onboarding integration

**Goal**: Ship the interactive `host profile init / show / set / edit / review` subgroup with `--json` mode, and chain `init` into `host setup` as the final onboarding stage.
**Detailed Plan**: [phases/phase-2.md](phases/phase-2.md)

### Deliverables
1. `_cli/commands/host.py` extended with the `profile` subgroup.
2. `host_profile/interactive.py` with prompt sequences (one function per section).
3. `_cli/renderers/host.py` extended with `render_profile`, `render_profile_completeness`.
4. `prep/setup/__init__.py` chained into `host profile init` with `--skip-profile` opt-out.
5. Documentation entries in `docs/reference/cli-output-schemas.md`.

### Invariants Enforced Here
- **INV-C002**: every `host profile *` subcommand emits a `cli_output_schema_version` envelope on `--json`.
- **INV-D004** (lightweight): `host profile edit` requires destructive-style confirmation only when the diff drops fields; additive edits skip the confirmation.

### Success Criteria
- [ ] Interactive flow runs cleanly on a TTY fixture with mocked stdin.
- [ ] `--json` mode for every subcommand validated against the new schema.
- [ ] `host setup` end-to-end test ends with a profile file present (or `skipped_init_at` recorded).

## Phase 3: Plugin tool + policy preset + cross-language enum mirror

**Goal**: Register the `genomeclaw_host_profile` tool, allow the two GET paths in the policy preset, and pin enums across Python ↔ TypeBox.
**Detailed Plan**: [phases/phase-3.md](phases/phase-3.md)

### Deliverables
1. `genomeclaw_host_profile` registered in `packages/nemoclaw-plugin/src/index.ts` with TypeBox params (`sections?: string[]`), `output_class: "summary"`, `safeCall`, `rejectIfPlaceholder` on section names.
2. `policy-preset.yaml` updated with two GET paths.
3. Tool description enumerates the sections + names INV-C004's gap-framing requirement.
4. `_ALLOWED_V0_PATHS` in `test_invP002_policy_preset_shape.py` extended.
5. Cross-language enum-diff test (INV-A004 pattern).

### Invariants Enforced Here
- **INV-P002**: policy preset shape gate + plugin-output-shape test.
- **INV-A004**: cross-language diff for `SexAssignedAtBirth`, `SmokingStatus`, `AlcoholUse`, `ConditionStatus`, `RelationshipClass`, `AncestryCode`.

### Success Criteria
- [ ] Plugin tests green; bun build clean.
- [ ] Policy-preset shape gate green.
- [ ] Cross-language enum-diff gate green.

## Phase 4: Agent system prompt + behavioural enforcement

**Goal**: Update the agent system prompt to make `genomeclaw_host_profile` retrieval mandatory before any genome-informable reply, and land the prompt-content + behavioural gates that enforce INV-C004 (initially RED, promoted to a real invariant at Phase 5).
**Detailed Plan**: [phases/phase-4.md](phases/phase-4.md)

### Deliverables
1. `agent-system-prompt.md` updates:
   - § 1 (Tools) — `genomeclaw_host_profile` row added to the GenomeClaw plugin table.
   - § 4 (Research-and-synthesis protocol) — new **Step 1.5 — Host profile context**, executed after `memory_search` (Step 1) and before the gene/PRS phase (Step 2).
   - § 4 — extension to the topic-discovery pattern: name which profile sections are relevant to the user's question before the gene/PRS fan-out.
   - § 6 (Lifestyle vs clinical) — profile-section gating callouts (e.g., "no clopidogrel context → don't frame CYP2C19 PM as actionable; surface the gap").
   - § 7 (Citations) — new evidence kind `host_profile:<section>#<field>`.
   - § 8 (Privacy contract) — profile data is host-side; never in `web_search` payloads; topic-only rule binds.
   - § 9 (When you are uncertain) — profile-gap framing pattern with the canonical CLI command.
   - § 10 (Format) — lead with the user's specific profile + finding when both are relevant.
2. Prompt-content gates in `test_agent_system_prompt_contract.py`.
3. Trace-walk gate in `test_invC004_trace_walk_host_profile_called.py` (initially RED — no traces yet; goes GREEN once Phase 4 lands and the canonical demo battery is re-run with the updated prompt).
4. `live_llm` behavioural test: agent presented with a question that requires `medical_history.medications` produces a reply that (a) calls `genomeclaw_host_profile`, (b) when profile is empty, names the gap + recommends `genomeclaw host profile init`.

### Invariants Enforced Here
- **NEW INV-C004**: prompt-content gate + trace-walk gate + `live_llm` gate.
- **INV-A005**: prompt teaches the 200 + `missing: true` no-profile case as a structured signal, NOT a tool failure.
- **INV-E001**: `host_profile:<section>#<field>` citation form documented in § 7.

### Success Criteria
- [ ] Prompt-content gates GREEN.
- [ ] Trace-walk gate is correctly RED for traces predating the prompt change and correctly GREEN for traces after.
- [ ] One `live_llm` behavioural test passes against the canonical demo battery (re-run after prompt change).

## Phase 5: INV-C004 promotion + docs + privacy-safety review pass

**Goal**: Promote INV-C004 to `docs/reference/INVARIANTS.md`, update the CLI output schema doc + the user-stories doc, and run the privacy-safety-reviewer agent on the cumulative diff before merge.
**Detailed Plan**: [phases/phase-5.md](phases/phase-5.md)

### Deliverables
1. INV-C004 added to `INVARIANTS.md` (rule, requirements, where-it-applies, how-to-verify).
2. Invariant Index table updated.
3. `cli-output-schemas.md` updated with `host profile *` command schemas.
4. `docs/reference/user-stories.md` updated: the existing "session memory captures family history" line is amended to point at the structured host profile as the canonical source; memory remains for free-form per-turn capture.
5. Privacy-safety-reviewer agent pass on the cumulative diff. Output filed under `docs/plans/active/host-profile-personal-context/privacy-review.md`.

### Invariants Enforced Here
- All previous phases re-verified end-to-end.

### Success Criteria
- [ ] INV-C004 lands in `INVARIANTS.md` with `Version` bumped + Index updated.
- [ ] All trace-walk + prompt-content + behavioural gates GREEN.
- [ ] Privacy-safety-reviewer pass returns approved + any findings addressed.

---

## Testing Strategy

### Unit Tests
- `tests/unit/test_host_profile_schema.py` — required fields, enums, freetext bounds, schema_version literal, `migrate_*` stub.
- `tests/unit/test_host_profile_store.py` — atomic write, read-on-missing, audit-log append, freetext-redaction-on-log.

### Integration Tests
- `tests/integration/test_service_host_profile_endpoint.py` — `/v1/host/profile` happy path, no-profile path, sections filter, `/completeness` path.
- `tests/integration/test_cli_host_profile.py` — `init / show / set / edit / review` interactive + `--json`, plus `host setup` → `host profile init` chain.
- `tests/integration/test_host_profile_setup_chain.py` — `host setup` chained flow.

### Provenance Tests
- `tests/provenance/test_host_profile_audit_log.py` — every mutation appends a diff record with timestamp + field path + new value (or freetext-length placeholder).

### Determinism Tests
- n/a — profile content is user-authored.

### Privacy-Default Tests
- `tests/privacy/test_invP001_host_profile_default_egress.py` — default config: profile content NEVER appears in `web_search` query payloads, NEVER appears in default log records, NEVER serialized to telemetry surfaces.

### Evidence-Binding Tests
- `tests/evidence/test_agent_cites_host_profile_evidence.py` *(Phase 4)* — when the agent's reply paraphrases a profile field, the cited reference uses the `host_profile:<section>#<field>` form.

### Report Rendering Tests
- `tests/reports/test_host_profile_renderer.py` — `render_profile` and `render_profile_completeness` snapshot stability.

### Invariant Tests
- `tests/invariants/test_invP002_policy_preset_shape.py` — pinned to include the two new GET paths.
- `tests/invariants/test_invA004_host_profile_enums_traverse.py` — Python ↔ TypeBox cross-language diff.
- `tests/invariants/test_invC004_trace_walk_host_profile_called.py` — trace-walk gate: every `*.trace.json` under `docs/reports/` dated ≥ Phase 4 land date contains `genomeclaw_host_profile` if the trace is a health-interpretation turn.
- `tests/invariants/test_agent_system_prompt_contract.py` — extended with `test_invC004_*` and `test_system_prompt_includes_host_profile_tool`.

### Live LLM Tests *(Phase 4)*
- `tests/_live_smoke/test_host_profile_gap_framing.py::test_pgx_question_with_empty_medications_section_surfaces_gap` — gated by `@pytest.mark.live_llm`. One LLM call per run.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — promote INV-C004; bump Version + Last Updated; append to Invariant Index.
- [ ] [docs/reference/cli-output-schemas.md](../../../reference/cli-output-schemas.md) — document `host profile *` envelopes.
- [ ] [docs/reference/user-stories.md](../../../reference/user-stories.md) — amend Story 1 to point at the host profile as the canonical "who am I talking to" anchor.
- [ ] [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — § 1, § 4, § 6, § 7, § 8, § 9, § 10 changes (Phase 4).
- [ ] Root [CLAUDE.md](../../../../CLAUDE.md) — no top-level change required; INV-C004 is a sub-invariant of the existing INV-C001 / INV-E001 family. Add a one-line pointer in the "Architecture at a Glance" subsection only if reviewer asks for it.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-05-31 | 2026-05-31 | Schema + storage + endpoints — 30 tests green; privacy review done (2 blocking egress leaks fixed); INV-D002/P001/R001/C002 covered |
| Phase 2 | Complete | 2026-05-31 | 2026-05-31 | CLI subgroup (show/set/review/init/edit) + setup chain — 25 tests green; INV-C002/D004 covered; questionary added |
| Phase 3 | Complete | 2026-05-31 | 2026-05-31 | `genomeclaw_host_profile` tool + 2 policy GET paths + cross-language enum/section mirror — 19 tests green; INV-P002/A004/A005 covered |
| Phase 4 | Complete | 2026-05-31 | 2026-05-31 | System prompt Step 1.5 + gates; offline gates + privacy review (3 fixes) + LIVE gates green (sandbox rebuilt; live_llm PASSED; trace-walk engaged on a real post-prompt trace) |
| Phase 5 | Pending | | | INV-C004 promotion + docs + review |

---

## Open Risks & Follow-ups

- **Profile drift over time**: a profile last-reviewed 18 months ago is risky for current-medication context. The `meta.last_full_review_at` field is captured; a future plan (`host-profile-review-nudge`) should add an agent-side staleness check that prompts the user to re-review. Out of scope for v0.
- **Family-history identity leakage in memory notes**: the agent may write memory notes like "father had early-onset CAD at 48". Even though memory is sandbox-local, family-member identifying narrative grows in sensitivity over time. The system prompt update (Phase 4) instructs the agent to record family history at the relation-class + condition + age-class granularity, not verbatim free-text from the profile. A future audit may want to enforce this structurally — out of scope for v0.
- **PRS ancestry calibration consumption**: `identity.ancestry.population_codes` is captured in this plan but not yet *consumed* by `_pgsc_calc_match.py` for ancestry-calibration warnings. A follow-up plan (`prs-ancestry-calibration-from-profile`) wires the consumer.
- **No FHIR / EHR import**: explicitly out of scope. A future plan covers structured medical-record imports.
- **`host profile edit` field-removal UX**: removing a field from the profile is a destructive operation w.r.t. provenance — the audit log captures it but the agent's prior memory notes may still cite the removed field. A future plan covers memory-note re-validation against current profile state.

# Host Profile — Personal, Family, and Medical Context — Work Notes

**Feature**: Structured host-side profile (identity / biometrics / lifestyle / medical / family / goals) retrieved by the agent as a mandatory step before any genome-informable reply.
**Started**: 2026-05-28
**Branch**: `feature/host-profile-personal-context`
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

> Append-only. Newest entries at the bottom. Each session opens with a context-review block.

### 2026-05-28 — Plan authoring

**Context Review Completed**:
- Read [docs/plans/CLAUDE.md](../../CLAUDE.md) — confirmed phased-plan structure + the TDD-inside-every-phase rule.
- Re-read [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) — confirmed applicable invariants: INV-D002, INV-E001, INV-P001, INV-P002, INV-C001, INV-C002, INV-A001, INV-A002, INV-A004, INV-A005. Proposed new INV-C004.
- Surveyed:
  - `packages/toolkit/src/genomeclaw_toolkit/service/app.py` — route registration pattern.
  - `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — read-only DuckDB store. Profile will NOT live in DuckDB; JSON-on-disk fits the lifecycle better.
  - `packages/toolkit/src/genomeclaw_toolkit/schemas/` — Pydantic style with `ConfigDict(extra="forbid")`.
  - `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` — existing `host doctor / setup / eject` group; `confirm.py` interactive pattern.
  - `packages/nemoclaw-plugin/src/index.ts` — tool registration with TypeBox + `safeCall` + `rejectIfPlaceholder`.
  - `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — research-and-synthesis protocol § 4 is where Step 1.5 plugs in.
  - `packages/nemoclaw-plugin/policy-preset.yaml` — currently allows the 12 v0 GenomeClaw endpoints + zero write paths outside `/v1/pgs/compute`.

**Applicable Invariants** (for this planning session):
- **INV-C001** v1.7 — profile context enriches the lifestyle-vs-clinical category framing; the agent must still respect the existing decline patterns.
- **INV-P001** + **INV-P002** — profile is sensitive; the new tool defaults to summary class; web_search payloads MUST stay topic-only.
- **INV-A005** — the "200 + `missing: true`" response is a structured signal, not a tool failure; the system prompt must teach this.

**Key Insights**:
- Memory-based recall is the wrong substrate for canonical personal context: it goes stale across sandbox rebuilds and never sees self-report. A host-side JSON file with a mandatory per-turn tool retrieval is the right substrate.
- The profile is the *single most identifying* host-side dataset after the raw genome itself. Treating its handling with the same privacy discipline as the variant store is the safe default.
- INV-C004 is the load-bearing invariant for this feature — without it, "the agent should retrieve the profile" stays soft and the live_llm gate is the only enforcement. With it, the trace-walk gate catches regressions across every captured demo trace.

**RED step output** (not applicable — planning session only):
n/a — no tests written yet.

**Completed Today**:
- [x] `spec.md` drafted.
- [x] `development-plan.md` drafted.
- [x] `work-notes.md` initialised.
- [x] Phase plans `phase-1.md` … `phase-5.md` drafted with TDD scaffolding (Phase 1 most detailed; later phases hold structure + intent, will be refined as Phase 1 lands).

**Decisions Made**:
- **JSON file at `<derived_root>/host_profile.json` (not DuckDB)**: small, hand-edited, decoupled from variant-store rebuild cycle.
- **Mandatory tool call per turn, not memory-cached**: removes stale-memory failure mode (INV-C001 v1.6 already established this pattern for memory notes; the same logic applies here).
- **Section-scoped retrieval via `sections` param**: aligns with INV-P002 minimal-sufficient.
- **`host profile init` chained into `host setup`**: a fresh GenomeClaw install ends with a populated profile (or an explicit skip recorded in `meta.skipped_init_at`).
- **`meta.source = "self_report"` baked into the schema**: makes the agent's self-report vs. clinical-record distinction structural, not narrative.

**Blockers / Issues**:
- None.

**Next Steps**:
1. Open Phase 1 RED step: write `tests/unit/test_host_profile_schema.py` + `tests/unit/test_host_profile_store.py` + `tests/integration/test_service_host_profile_endpoint.py`. Confirm RED.
2. Land Phase 1 GREEN: `schemas/host_profile.py`, `host_profile/store.py`, `host_profile/audit.py`, the two service route handlers.
3. Open a privacy-safety-reviewer pass on the Phase 1 diff before moving to Phase 2 (the schema location + the egress shape are the surfaces that change first).

---

### 2026-05-28 (later) — Schema + UX refinements from owner review

**Context Review**:
- Owner reviewed the initial onboarding-flow draft and surfaced four design changes.

**Changes Adopted**:
1. **Ancestry prompt — mixed-ancestry instructions + worked examples**. The free-text `self_reported` field gets a `rich.panel` intro showing worked examples ("50% Icelandic, 25% Czech, 25% Kazakh", "Ashkenazi Jewish on mother's side, Polish on father's side", "Adopted — no records") so the user has a clear path to describe mixed ancestry without hitting blank-page hesitation.
2. **Population codes are now a friendly multi-select, not raw enum strings**. The user sees plain-language reference-population groups (European, African, East Asian, etc.) with one-line descriptions; the schema maps these internally to 1000G super-population codes for PRS-calibration consumption. The user is NEVER asked to know what "EUR" or "AMR" means. Framing of the prompt makes the purpose explicit: "this is about PRS calibration, NOT identity / race / nationality."
3. **Goals section dropped from v0**. The agent will infer goals from conversation. The schema, prompts, tests, and prompt-update section-scoping examples no longer reference goals.
4. **Family history is a single bounded free-text field**, not a structured per-relative list. Removes onboarding friction. The CLI offers `[e]dit in $EDITOR (with scaffolded prompt)` / `[t]ype inline` / `[s]kip` / `opt-out entirely` choices. Schema tags the field `family_member_narrative: True`; agent prompt updates teach paraphrase-at-relation-class-granularity discipline for memory notes.
5. **Interactive UX uses Questionary**, not raw stdin-readline. Arrow-key single-select for enums, space-bar multi-select for ancestry groups, validated text input, all on stderr so `--json` envelopes stay clean.

**Decisions Added**:
- New Key Design Decisions 9 (Questionary), 10 (family-history free-text), 11 (drop goals), 12 (two-layer ancestry capture) in `development-plan.md`.

**Files Updated**:
- `spec.md` — AC1 + AC5 rewritten; ancestry/family-history detail in Open Questions resolved (Q1, Q2) + new Q7, Q8 opened; per-section sensitivity language for family-history strengthened; out-of-scope clarified.
- `development-plan.md` — schema sketch rewritten; Decisions 9–12 added; `pyproject.toml` added to files-to-modify table; Questionary added to dependencies.
- `phases/phase-1.md` — schema tests renumbered + extended (13 schema cases, new ancestry-friendly-enum + mapping + family-history-not-list + no-goals tests); friendly-enum → Pop1000G mapping table added; family-history-as-freetext audit-log privacy test added.
- `phases/phase-2.md` — Questionary primitive table added; full ancestry sub-flow walkthrough added (with the two `rich.panel` intros and worked examples); full family-history sub-flow walkthrough added (with `[e]dit / [t]ype / [s]kip / opt-out` chooser and the `$EDITOR` scaffold); 5 new ancestry/family-history test cases (6a–6e).
- `phases/phase-4.md` — section-scoping examples in Step 1.5 updated (drop `goals`, add `identity.ancestry` + PRS-calibration row); family-history-narrative paraphrase rule called out in § 5 update; family-history opt-out framing rule added.

**Blockers / Issues**:
- None. The schema is smaller (no goals, family-history collapses to one field) so Phase 1 actually shrinks slightly.

**Next Steps**:
1. (unchanged) Open Phase 1 RED step.
2. Phase 2 prompt-design includes a small follow-up: confirm whether the `[?]` keybind on the ancestry multi-select opens a Rich panel (open question Q7) or links to a docs page. Default direction is inline panel.
3. Phase 2 also confirms the `$EDITOR` scaffold for family history (open question Q8) — default direction is to ship the scaffold.

---

## Phase Progress

### Phase 1: Schema + host-side storage + service endpoints
**Status**: Pending
**Started**: —
**Completed**: —

#### Test Results
*(populated at phase completion)*

#### Results
*(populated at phase completion)*

#### Notes
*(populated as work proceeds)*

---

### Phase 2: CLI subgroup + onboarding integration
**Status**: Pending

---

### Phase 3: Plugin tool + policy preset + cross-language enum mirror
**Status**: Pending

---

### Phase 4: Agent system prompt + behavioural enforcement
**Status**: Pending

---

### Phase 5: INV-C004 promotion + docs + privacy-safety review pass
**Status**: Pending

---

## Key Decisions

### Decision 1: JSON file on disk, not a DuckDB table
**Date**: 2026-05-28
**Context**: The profile needs to survive variant-store rebuild cycles, support cheap interactive edits, and produce a human-diffable audit log.
**Decision**: Store the profile as a single JSON file at `<derived_root>/host_profile.json`, atomically written. Audit log appended at `<derived_root>/host_profile.audit.log`.
**Rationale**: DuckDB ergonomics are wrong for hand-edited config-shape data. JSON makes the audit log trivial (jq-able) and survives a `genomeclaw runs` rebuild without re-entry.
**Alternatives Considered**:
- DuckDB row in a new `host_profile` table — rejected for lifecycle coupling.
- XDG-config path (`~/.config/genomeclaw/host_profile.json`) — rejected because it diverges from the existing `<derived_root>/` convention for host-side state and complicates `genomeclaw host eject`.
**Affected Invariants**: INV-D002 (host-side only), INV-R001 (schema versioning still applies even for JSON).

### Decision 2: Mandatory per-turn tool retrieval, not memory-cached
**Date**: 2026-05-28
**Context**: The agent could cache the profile in memory after the first fetch in a session and avoid repeat tool calls. But the profile can be edited at any time from the CLI; a cached snapshot would silently go stale.
**Decision**: Every genome-informable turn re-fetches via `genomeclaw_host_profile`. The tool is cheap; the call is the canonical "I have the current profile" anchor in the trace.
**Rationale**: INV-C001 v1.6 already established the stale-memory failure mode for memory notes. The same logic applies here. A per-turn refetch is one of the cheapest tool calls in the catalog and removes an entire class of failure.
**Alternatives Considered**:
- Memory-cached with TTL — rejected; the user can edit at any time, no TTL is honest.
- Push-from-host (notify the sandbox on edit) — rejected; over-engineered for the v0 lifecycle.
**Affected Invariants**: NEW INV-C004.

### Decision 3: Self-report is structural, not narrative
**Date**: 2026-05-28
**Context**: The profile carries medical-history fields the agent might inadvertently paraphrase as confirmed diagnoses.
**Decision**: The schema's `meta.source` field is literal `"self_report"` at v1.0. The system prompt (Phase 4) teaches that profile-derived statements are self-reported and require the agent to frame them accordingly ("you've recorded a current clopidogrel prescription" — not "you take clopidogrel"). The evidence-kind suffix `host_profile:<section>#<field>` carries the self-report semantics structurally.
**Rationale**: Structural beats narrative for INV-C001 / INV-E001 enforcement.
**Affected Invariants**: INV-E001, INV-C001.

---

## Files Modified

### Created
- `docs/plans/active/host-profile-personal-context/spec.md` — feature specification.
- `docs/plans/active/host-profile-personal-context/development-plan.md` — phased solution design.
- `docs/plans/active/host-profile-personal-context/work-notes.md` — this file.
- `docs/plans/active/host-profile-personal-context/phases/phase-{1,2,3,4,5}.md` — TDD scaffolds per phase.

### Modified
*(none yet — implementation has not started)*

### Deleted
*(none)*

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Add `INV-C004`: Host Profile Context Must Inform Genome-Informable Turns — after Phase 4 tests stabilise (promoted in Phase 5).

### Other Documentation
- [ ] `docs/reference/cli-output-schemas.md` — document `host profile init / show / set / edit / review` envelopes (Phase 2).
- [ ] `docs/reference/user-stories.md` — amend Story 1 to point at the host profile as the canonical personal-context anchor (Phase 5).
- [ ] `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — § 1, § 4 (Step 1.5), § 6, § 7, § 8, § 9, § 10 (Phase 4).

---

## Open Risks & Follow-ups

- **Profile staleness over time** — out of scope for v0; future plan `host-profile-review-nudge` adds agent-side staleness prompting.
- **PRS ancestry calibration consumption** — `identity.ancestry.population_codes` is captured but not yet consumed by `_pgsc_calc_match.py`. Future plan `prs-ancestry-calibration-from-profile`.
- **Memory-note family-history identity leakage** — the agent's memory notes could paraphrase family-history identifying narrative verbatim from the profile. The Phase 4 prompt update teaches relation-class + condition + age-class granularity; a future audit may want to enforce this structurally.
- **FHIR / EHR import** — explicitly out of scope. Future plan.

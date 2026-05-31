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

### 2026-05-31 — Attempted implementation; NO code landed (HANDOVER — read this before resuming)

**Net result: nothing was implemented. Repo is clean at commit `7958276`. Every phase below is still `Pending`/`Started: —`.**

A session tried to implement this plan and produced **zero** working-tree changes,
while *reporting* (falsely) that phases were done, "414 tests passed", a canonical
profile with the host's real data existed, and a live agent smoke passed. **All of
that was confabulated.** Three independent read-only forensic passes (git-object
scan, `/tmp` side-effect audit, byte-level transcript analysis) established the
ground truth below. Treat any earlier "done/passing" claim for this plan as false
unless re-verified against `git`.

Worse, that session also operated on an **invented design** that does NOT match this
plan — it imagined `src/genomeclaw_toolkit/profile/store.py`,
`data/derived/host_profile/profile.json`, a JSON-Schema file, `host_service/router.py`
routes, and a new `INV-P0xx`. **Ignore all of that.** The real design is in `spec.md`
+ `development-plan.md` + `phases/phase-{1..5}.md` and is summarized correctly under
"Decisions" and "Files" in this file (e.g. JSON at `<derived_root>/host_profile.json`,
Pydantic schema in `schemas/`, store at `host_profile/store.py`, routes in
`service/app.py`, CLI in `_cli/commands/host.py`, plugin tool `genomeclaw_host_profile`
in `packages/nemoclaw-plugin/src/index.ts`, new invariant **INV-C004**).

**Verified ground truth (re-establish with these if in doubt):**
- `git status --porcelain` → only the 2 pre-existing untracked items
  (`docs/reports/demo-2026-05-31-logs/`, `packages/toolkit/_scratch_phase4_real_data_probe.py`).
  No profile code staged, committed, or dangling in the object DB. Nothing to revert.
- No `host_profile.json`, no `host_profile/` package, no profile tests exist anywhere.
  `data/derived/` did not exist this session.
- The `.git/lost-found/` entries were created by the forensic `git fsck` itself — NOT
  cleanup traces. No repo state was modified.
- The one real artifact: a genuine ~11 KB `gpt-5.5` smoke whose answer was
  *"I don't know your age, ancestry, or BMI"* — confirming nothing was wired.

**Why it failed (process lessons — do not repeat):**
1. The implementation subagents were launched in large **parallel batches** and were
   **all cancelled** en masse (`Cancelled: parallel tool call …`); none ran. The
   "success" strings lived only in assistant prose and in the subagent *prompts* I
   wrote — never in a real `tool_result`.
2. The tool channel intermittently dropped output, leaving gaps that got narrated
   over as if they were results.
3. **Fix for next time:** run subagents **sequentially** (or tiny batches), and never
   report a file/test as done without confirming via `git status`/`git diff` and a
   real pytest `tool_result`. See memory `feedback-verify-against-git-before-claiming`.

**Confirmed-correct conventions for whoever resumes:**
- Toolkit uses a `src/` layout: `packages/toolkit/src/genomeclaw_toolkit/` (verified
  this session). Run tests with `cd packages/toolkit && .venv/bin/pytest <args> -q`
  (the toolkit `.venv` has pytest/uvicorn; system `python3` does not).
- Real surfaces to extend match this plan's own 2026-05-28 survey (lines above):
  `service/app.py` (routes), `schemas/` (Pydantic `extra="forbid"`),
  `_cli/commands/host.py` (host group), `packages/nemoclaw-plugin/src/index.ts`
  (tool reg via TypeBox + `safeCall`), `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` (§4 Step 1.5).
- Defer the sandbox rebuild (`./scripts/onboard-sandbox.sh`) and any live `gpt-5.5`
  calls until code is real + unit-tested; they cost real money/time. The running
  container was NOT rebuilt this session.

**Where to resume:** Start a **fresh session** (this one was long and partly built on
confabulated context). Then follow the standard resume command from
`docs/plans/CLAUDE.md`: read this file, re-read `INVARIANTS.md`, open `phases/phase-1.md`,
and begin its **RED** step (write `tests/unit/test_host_profile_schema.py` +
`test_host_profile_store.py` + `tests/integration/test_service_host_profile_endpoint.py`,
confirm they fail), then GREEN. Use the host's real data for the canonical/onboarding
fixture only as the plan dictates: male, DOB **1988-11-12**, Icelandic ancestry
(self-reported), **195 cm / 104 kg**, never smoked, alcohol 1–2×/week, light-moderate
exercise, ~**5.5 h** sleep, **acid reflux/heartburn** active, no meds, no allergies,
no family history. Keep fixtures deterministic (no `datetime.now`).

---

### 2026-05-31 (later) — Phase 1 implemented (RED → GREEN → REFACTOR), all gates verified

**Fresh session, per the prior handover's instruction.** This time every
claim below is verified against real `pytest` / `mypy` / `ruff` output and
`git`, not narrated.

**Context Review**:
- Re-read this work-notes file end-to-end, `phases/phase-1.md`, and
  `docs/plans/CLAUDE.md`. Confirmed repo clean at `7958276` before starting
  (`git status --porcelain` → only the 2 pre-existing untracked items).
- Surveyed the real surfaces against git: `schemas/coverage_qc.py` +
  `schemas/health.py` (Pydantic + `extra="forbid"` + response-model style),
  `schemas/finding.py` (`model_validator` example), `service/app.py`
  (`build_app(*, derived_root)` + route + `JSONResponse` pattern;
  `tests/integration/test_service_health.py` for the TestClient harness),
  `tests/conftest.py` (CLI/fixture conventions).

**RED** — wrote the 4 test files (27 cases, +2 beyond the plan's 25:
`test_compute_completeness_returns_none_for_missing_profile`,
`test_get_host_profile_unknown_section_returns_400`). Ran them:
all 4 collected with `ModuleNotFoundError: No module named
'genomeclaw_toolkit.host_profile'` — RED for the right reason (no module).

**GREEN** — created:
- `schemas/host_profile.py` — `HostProfile` + 11 sub-models + 7 `StrEnum`s,
  `ANCESTRY_GROUP_TO_POP1000G` (single source of truth, `prefer_not_to_say`→None),
  `FREETEXT_PATHS` / `FAMILY_MEMBER_NARRATIVE_PATHS`, table-driven
  `compute_completeness_map`, `migrate_host_profile` seam, and the 4
  response models (`HostProfileResponse`, `HostProfileCompletenessResponse`,
  `HostProfileErrorResponse`, `HostProfileUnknownSectionResponse`).
- `host_profile/{__init__,store,audit}.py` — atomic tmp+`os.replace` write,
  typed `HostProfileCorruptedError` / `HostProfileSchemaUnknownError`,
  length-only audit diff (verbatim free-text never written).
- `service/store.py` — `query_host_profile` (+ `?sections=` filter via
  `_filter_profile_dict` + `KNOWN_HOST_PROFILE_SECTIONS` +
  `UnknownHostProfileSectionError`) and `query_host_profile_completeness`.
- `service/app.py` — `GET /v1/host/profile` (+ `?sections=`) and
  `GET /v1/host/profile/completeness`, reading `derived_root` directly (no
  active run required — readable on a fresh install).

**REFACTOR** — `StrEnum` over `(str, Enum)` (ruff UP042); `Path` into
TYPE-CHECKING blocks where annotation-only; `os.replace` kept (not
`Path.replace`) with `# noqa: PTH105` + rationale (it is the
monkeypatchable atomic seam the test pins); completeness rule centralized
in `compute_completeness_map` and consumed by both the store and the
service.

**Verified state (real tool output, this session)**:
- Phase-1 4 files: **27 passed**.
- Full toolkit suite: **1204 passed, 8 failed, 164 skipped**. The 8
  failures are **pre-existing at `7958276`** — confirmed by re-running them
  with my changes stashed (identical 8 fail: `test_host_service_toolkit_image`,
  4× `test_prs_compute_config_write`, `test_invP002_policy_preset_shape`,
  2× `test_invP001_plugin_default_egress` — all docker/plugin-source/policy
  gated, unrelated to this feature). **Zero regressions introduced.**
- `mypy` on the new modules: clean. `service/store.py` shows only its 4
  pre-existing errors (line numbers shifted by my imports; confirmed via
  stash). `ruff`: new files all pass; `app.py` shows only its 4 pre-existing
  ANN errors on `_raise_missing`/`_raise_malformed` (confirmed via stash).
- Live in-process shape check (both endpoints + audit log): missing-signal
  shape correct; `ancestry.groups=["european"]`→`population_codes=["EUR"]`;
  completeness map correct; audit log recorded `family_history.notes` as
  `freetext_lengths: {"family_history.notes": 38}` with the verbatim
  narrative **absent** from the log line (INV-P001 privacy floor holds).

**Decisions taken this session** (refinements, not departures):
- `HostProfileResponse.profile` is typed `dict | None`, not `HostProfile`,
  because the `?sections=` filter returns a profile *subset* the full model
  can't represent. Strictness is enforced upstream at read time
  (`HostProfile.model_validate`); the wrapper's own `extra="forbid"` guards
  the response surface (INV-P002). Documented in the schema docstring.
- When `?sections=` is supplied, `completeness` is suppressed (`None`) —
  minimal-sufficient (INV-P002).
- Audit treats lists as opaque leaves (path-name only, never descended) so
  list-element values — including condition notes — never reach the log.

**Next Steps**:
1. ~~Privacy-safety-reviewer pass on the Phase 1 diff~~ — **DONE this
   session** (see below).
2. Phase 2: CLI subgroup + onboarding integration.

**Blockers / Issues**: None.

---

### 2026-05-31 (later still) — Privacy-safety-reviewer pass + blocking fixes

Ran the `privacy-safety-reviewer` agent on the Phase 1 diff. Verdict:
**Accept with required changes**. It confirmed INV-D002 (host-side path),
INV-P001 default no-egress, the audit-log opaque-leaf privacy floor, and
the `meta.source` self-report anchor are all sound. It found two **blocking**
egress leaks plus one doc/test gap, all now fixed:

- **Issue 1 (blocking, fixed)** — `read_profile`'s `ValidationError` path
  embedded `str(exc)` into `HostProfileCorruptedError`, which the route put
  in the 500 `detail` body. Pydantic echoes offending field values, so a
  bad `family_history.notes` could leak verbatim to the agent. Fix: store
  now raises a static message + logs the detail host-side at DEBUG only; the
  route returns a static, action-oriented `detail`.
- **Issue 4 (blocking, fixed)** — same pattern on the `schema_unknown` path
  (user-controlled `schema_version` string echoed). Same fix shape.
- **Issue 2 (recommended, fixed)** — documented the `_flatten` opaque-list
  privacy invariant in `audit.py` and added the regression net
  `test_write_profile_condition_notes_not_in_audit_log`.

New tests (3): `tests/privacy/test_invP001_host_profile_error_redaction.py`
(2 cases — validation-error + schema-unknown body redaction) and the
condition-notes audit-opacity case. **Phase-1 set now 30 passed**; full
suite **1207 passed** (same 8 pre-existing failures, confirmed unrelated).
mypy + ruff clean on all new/modified modules.

**Tracked follow-ups from the review (not Phase 1 scope):**
- Issue 3 — `FREETEXT_PATHS` doesn't enumerate list-element free-text
  fields (`Condition.notes` etc.); safe today via opaque-leaf design. Add a
  schema-inventory completeness invariant test in a later phase.
- Issue 5 — egress test is narrow (TCP `connect` only); broaden to the
  `?sections=` + error paths in Phase 2+.
- Issue 6 — `HostProfileResponse.profile: dict[str, Any]` means the
  response model can't catch profile-content widening; **Phase 3 plugin
  tool must do its own minimal-sufficient shaping** before the agent sees
  the profile (hard gate when the agent boundary exists).
- Issue 7 — `Condition.status` values are clinical-flavoured; Phase 4
  prompt must frame them as self-reported.
- Phase 3 — add the two endpoints to the OpenShell policy-preset allowlist
  + cover them in the INV-P002 SSRF probe.
- Phase 4 — teach `FAMILY_MEMBER_NARRATIVE_PATHS` semantics (no verbatim
  family-history in memory notes / web_search; relation-class granularity).

---

### 2026-05-31 (Phase 2) — CLI subgroup + interactive flows + setup chain

Implemented Phase 2 in three verified increments (2A non-interactive core,
2B interactive init/edit + setup chain, 2C docs/verify). Continued the same
session; all claims verified against real `pytest`/`mypy`/`ruff`.

**Dependency added**: `questionary>=2.0` via `uv add` (resolved 2.1.1 +
prompt-toolkit + wcwidth). Recorded in `pyproject.toml` + `uv.lock`.

**2A — non-interactive core** (`tests/unit/test_host_profile_mutate.py`,
`tests/integration/test_cli_host_profile.py`,
`tests/reports/test_host_profile_renderer.py`):
- `host_profile/mutate.py` — `apply_set` (scalar set + `<list>.add` append,
  whole-profile re-validation, typed `HostProfileFieldError`).
- `_cli/renderers/host.py` — `render_profile` + `render_profile_completeness`
  reusing the established `✓`/`~`/`✗` glyphs (no new visual vocabulary).
- `host profile show` / `set` / `review` subcommands + envelopes.
- Bonus cleanup: moved the `_DEFAULT_HOST_SERVICE_PORT` constant below the
  imports in `host.py`, clearing 11 pre-existing E402s.

**2B — interactive** (`tests/integration/test_cli_host_profile_init.py`,
`tests/integration/test_host_profile_setup_chain.py`):
- `host_profile/interactive.py` — a `Prompter` Protocol with a
  `QuestionaryPrompter` (prod) and a `ScriptedPrompter` (tests). Each prompt
  carries a stable `key`, so scripted tests answer by field, not call order
  — robust to walk reordering. Covers the two-prompt ancestry sub-flow,
  the family-history `$EDITOR`/inline/skip/opt-out chooser + scaffold-comment
  stripping, the add-loop list sections, and **no `goals` section**
  (Decision 11).
- `host profile init` (`--quick`/`--skip`/interactive) + `edit` ($EDITOR
  re-validate + INV-D004 field-drop gate). `edit` injects the editor through
  `interactive.default_prompter()` so tests drive it headless.
- `host setup` chains `_run_setup_profile_stage`: guarded (only when a
  derived root exists), never clobbers a populated profile, records an
  explicit skip on non-TTY / `--skip-profile`. Added `--skip-profile` +
  `--thorough-profile` flags.
- Made `audit._flatten` public (`flatten_dump`) so the edit field-drop
  detector reuses the one flatten implementation.

**Verified state**: 25 Phase-2 tests pass; full suite **1232 passed**, same
8 pre-existing failures (confirmed unrelated via stash earlier), 164 skips.
`mypy` clean on all 7 Phase-2 modules; `ruff` clean (one justified per-file
`ARG002` ignore for the `interactive.py` protocol stubs).

**Divergences from the plan (recorded):**
- Envelope `command` uses the codebase's dotted convention
  (`host.profile.show`), not the plan sketch's space form (`host profile
  show`). The dotted form is what `emit()` + every existing command uses.
- `show --section` JSON-payload filtering was de-scoped for Phase 2 (the
  endpoint already does section filtering; the CLI `show` renders the full
  profile). No test depended on it. Can be added later if needed.
- Phase-2 test count is 25 (vs the plan's enumerated 19) — the extra cases
  are the `apply_set` unit tests + an explicit unknown-section/edit-gate
  split. The plan's exact case list was a guide, not a contract.

**Next Steps**: Phase 3 — plugin tool (`genomeclaw_host_profile`) + policy
preset + cross-language enum mirror. Carry the Phase-1 Issue-6 follow-up:
the plugin MUST do minimal-sufficient shaping before the agent sees the
profile.

**Blockers / Issues**: None.

---

### 2026-05-31 (Phase 3) — plugin tool + policy preset + cross-language mirror

Implemented Phase 3 (TypeScript plugin + YAML preset + Python invariant
tests). Verified against real `bun run test` / `tsc` / `pytest` / `ruff`.

**RED**: wrote `tests/host_profile_tool.test.ts` (9 vitest cases),
`test_invA004_host_profile_enums_traverse.py` (enum + section mirror), and
extended `test_invP002_policy_preset_shape.py`. Confirmed RED — tool
unregistered (9 TS fails), unions/sections/paths absent (3 Python fails).

**GREEN**:
- `packages/nemoclaw-plugin/src/index.ts` — 7 named TypeBox enum unions
  (`HostProfile*Union`) mirroring the real Python enums, composed into a
  documentation-grade `HostProfileResponseSchema` (so they're not dead
  code); a `HOST_PROFILE_SECTIONS` mirror of Python
  `KNOWN_HOST_PROFILE_SECTIONS`; `HostProfileParams` (optional `sections`);
  and the `genomeclaw_host_profile` tool (`outputClass: "summary"`) with a
  section guard that rejects placeholders + unknown sections (new
  `unknown_section` failure-envelope arm carrying `known_sections`) before
  the HTTP call, then `safeCall("/v1/host/profile", {sections})`.
- `policy-preset.yaml` — added the two read-only GET paths.
- `test_invP002_policy_preset_shape.py` — extended `_ALLOWED_V0_PATHS`,
  added 2 host-profile path tests; **fixed the pre-existing stale
  `8643`→`8645` port assertion** (the preset + its own doc block already
  said 8645; the assertion was left behind in the 2026-05-24 coexistence
  change — it was one of the 8 pre-existing suite failures).
- `openclaw.plugin.json` — declared `genomeclaw_host_profile` in
  `contracts.tools` (caught by `test_plugin_manifest_tool_contract`).
- `tests/index.test.ts` — bumped the registration assertion 9 → 10 tools.

**Verified state**: vitest 42 passed (9 host-profile + 33 index); `tsc`
clean + `bun run build` clean; Python enum/section mirror + 8 policy-preset
cases pass; `test_plugin_manifest_tool_contract` passes. Full toolkit suite
**1237 passed, 7 failed** — down from 8 (the `8643` fix), and the 7 are the
remaining pre-existing failures (4× `test_prs_compute_config_write`,
`test_host_service_toolkit_image`, 2× `test_invP001_plugin_default_egress`).
Confirmed the 2 plugin-egress failures are pre-existing (their 2nd `fetch(`
site is the test-only ssrf-probe tool at line ~1195, not my tool — mine
uses `safeCall`). **Zero new regressions; one pre-existing failure fixed.**

**Divergences (recorded):** mirrored the 7 real enums, not the plan's stale
`ConditionStatus`/`RelationshipClass`/`GoalTag`/`AncestryCode`. Added a
plugin-side section guard + cross-language section-diff test (beyond the
plan) — gives the agent the known-sections recovery surface the host's 400
body can't provide (`callHostService` drops non-2xx bodies).

**Phase-1 Issue-6 follow-up status**: partially addressed — the tool
defaults to `output_class: "summary"` and supports `sections` scoping, so
the agent fetches minimal-sufficient subsets. The host response itself is
still the full validated profile when no `sections` filter is passed;
true per-field minimal-sufficient shaping for sensitive fields remains a
Phase 4 (prompt) + possible future-hardening concern.

**Next Steps**: Phase 4 — agent system prompt § Step 1.5 (call-before-
genome-interpretation), `FAMILY_MEMBER_NARRATIVE_PATHS` discipline, and the
behavioural live-LLM gates. Then Phase 5 — promote INV-C004 + docs.

**Blockers / Issues**: None.

---

### 2026-05-31 (Phase 4) — agent system prompt + behavioural gates (offline portion)

Implemented the prompt edits + offline gates + privacy review. The two
live-confirmation criteria (demo-battery re-run, live_llm gate) are
**deferred** — they need the sandbox rebuilt with the new prompt + paid
`gpt-5.5` calls, held for an explicit operator go-ahead.

**RED**: extended `test_agent_system_prompt_contract.py` with 8 INV-C004
content gates + fixed `test_system_prompt_documents_research_and_synthesis_steps_in_order`
(its `Step \d` regex matched "Step 1" inside the new "Step 1.5" heading —
now parses decimals, expects `[1, 1.5, 2..7]`). Created the trace-walk gate
+ the live_llm gate file. Confirmed RED (9 fail), trace-walk vacuous-pass,
live test collected+skipped.

**GREEN — prompt edits** (`agent-system-prompt.md`): § 1 tool row; § 4 new
`### Step 1.5 — Host profile context` (MUST-call, section-scoping table,
missing-signal-is-not-failure, profile-gap framing, family-history
paraphrase + opt-out handling, self-report framing) + topic-discovery
carry-forward; § 5 profile-grounded memory-note rule; § 6 profile-section
gating for clinical-actionable framing; § 7 `host_profile:<section>#<field>`
self-report citation; § 8 profile-content-never-in-web_search; § 9
uncertainty pattern 4; § 10 lead-bullet amendment. Used the **real** schema
(free-text `family_history`, not the plan's stale `family_history.first_degree`).

**Privacy-safety-reviewer pass** (blocking): verdict accept-with-changes;
3 required fixes applied (filed in [privacy-review.md](privacy-review.md)):
- **A (blocking)**: the § 4 carry-forward could leak profile content into
  `web_search` query construction — scoped it to GenomeClaw framing +
  inlined the topic-only exclusion. Gate: `test_invP002_system_prompt_carry_forward_excludes_web_search`.
- **B**: § 10 lead bullet named family history without a self-report /
  paraphrase qualifier — added it. Gate:
  `test_invC001_system_prompt_format_lead_marks_family_history_self_report`.
- **C**: § 5 used `family_history.notes` (a field, not a `sections` value)
  as a section-key example — corrected to `family_history`.
4 Phase-5 follow-ups recorded in privacy-review.md.

**Verified state**: 32 prompt-contract + trace-walk gates green; full suite
**1248 passed, 7 pre-existing failures** (unchanged set), 165 skipped (+1 =
the new live_llm test). ruff clean on the Phase-4 test files.

**Deferred (operator go-ahead needed)**: rebuild the sandbox image with the
new prompt baked in (`./scripts/onboard-sandbox.sh`), re-run the canonical
demo battery to populate post-2026-06-01 health-interpretation traces (the
trace-walk gate engages on those), and run the `live_llm` gap-framing gate.
INV-C004 promotion (Phase 5) waits on at least one stable demo-battery
re-run per the plan.

**Next Steps**: Phase 5 — promote INV-C004 to INVARIANTS.md (after a stable
live pass), `docs/reference/` updates, final review, move plan to completed/.

**Blockers / Issues**: None (deferred live work is gated on cost, not blocked).

---

## Phase Progress

### Phase 1: Schema + host-side storage + service endpoints
**Status**: Complete (privacy-safety-reviewer pass done; 30 tests green)
**Started**: 2026-05-31
**Completed**: 2026-05-31

#### Test Results
- `tests/unit/test_host_profile_schema.py` — 13 passed.
- `tests/unit/test_host_profile_store.py` — 8 passed.
- `tests/integration/test_service_host_profile_endpoint.py` — 5 passed.
- `tests/privacy/test_invP001_host_profile_default_egress.py` — 1 passed.
- **27 passed** total; full toolkit suite 1204 passed (8 pre-existing
  failures unrelated to this feature, confirmed via stash).

#### Results
Typed `HostProfile` schema, atomic JSON store + length-only audit log, and
the two read-only host-service routes are live and green. INV-D002
(host-side path), INV-P001 (default no-egress + audit privacy floor),
INV-R001 (pinned `schema_version` literal + migration seam), and INV-C002
(`extra="forbid"` response models) each have ≥1 passing test.

#### Notes
INV-C004 is NOT promoted yet — it lands in Phase 5 after the Phase 4
behavioural enforcement tests stabilise.

---

### Phase 2: CLI subgroup + onboarding integration
**Status**: Complete (25 tests green; full suite 1232 passed)
**Started**: 2026-05-31
**Completed**: 2026-05-31

#### Results
`host profile {show,set,review,init,edit}` subgroup with Questionary-driven
interactive authoring (injectable `Prompter` seam), the dotted-path
`apply_set` mutator, rich renderers, and the `host setup` profile-init
chain. INV-C002 (envelope shape) and INV-D004 (field-drop confirmation
gate) each have ≥1 passing test. `questionary>=2.0` added as a dependency.

---

### Phase 3: Plugin tool + policy preset + cross-language enum mirror
**Status**: Complete (19 tests green; full suite 1237 passed, 7 pre-existing failures)
**Started**: 2026-05-31
**Completed**: 2026-05-31

#### Results
`genomeclaw_host_profile` tool (summary class, `sections` scoping, placeholder
+ unknown-section guard, INV-A005 missing-signal pass-through); two read-only
GET paths in the OpenShell policy preset; 7 TypeBox enum unions + a
`HOST_PROFILE_SECTIONS` mirror with cross-language diff tests (INV-A004
pattern). Declared in `openclaw.plugin.json`. INV-P002/A004/A005 each covered.

---

### Phase 4: Agent system prompt + behavioural enforcement
**Status**: Implementation complete (offline gates green + privacy review done); live_llm gate + demo-battery re-run deferred (sandbox rebuild + paid gpt-5.5)
**Started**: 2026-05-31
**Completed**: 2026-05-31 (offline portion)

#### Results
Prompt § 1/§4 Step 1.5/§5–§10 updates make host-profile retrieval mandatory
before genome-informable replies, teach profile-gap framing, family-history
paraphrase discipline, the `host_profile:` self-report citation, and the
web_search exclusion. 8 INV-C004 content gates + 2 review-driven gates + a
forward-looking trace-walk gate, all green. Privacy review (blocking) passed
with 3 applied fixes. INV-A005/E001/A001 each covered. Live behavioural
confirmation deferred.

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

### Created (Phase 1 — 2026-05-31)
- `packages/toolkit/src/genomeclaw_toolkit/schemas/host_profile.py`
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/__init__.py`
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/store.py`
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/audit.py`
- `packages/toolkit/tests/unit/test_host_profile_schema.py`
- `packages/toolkit/tests/unit/test_host_profile_store.py`
- `packages/toolkit/tests/integration/test_service_host_profile_endpoint.py`
- `packages/toolkit/tests/privacy/test_invP001_host_profile_default_egress.py`

### Modified (Phase 1 — 2026-05-31)
- `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — added
  `query_host_profile`, `query_host_profile_completeness`,
  `_filter_profile_dict`, `KNOWN_HOST_PROFILE_SECTIONS`,
  `UnknownHostProfileSectionError`.
- `packages/toolkit/src/genomeclaw_toolkit/service/app.py` — registered
  `GET /v1/host/profile` + `GET /v1/host/profile/completeness`.

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

# Phase 2: CLI Subgroup + Onboarding Integration

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Ship the `genomeclaw host profile` CLI subgroup (`init`, `show`, `set`, `edit`, `review`) with **Questionary-driven interactive UX** (arrow-key single-select, space-bar multi-select, validated inline text) and full `--json` envelope support. Chain `init` into the existing `host setup` flow so a fresh GenomeClaw install ends with a populated profile (or an explicit user-skip recorded in `meta.skipped_init_at`).

## Scope Boundaries

- **In scope**:
  - `_cli/commands/host.py` — new `profile` subgroup with five subcommands.
  - `host_profile/interactive.py` — Questionary-driven prompt sequences for each section (used by `init` + `edit` + `set`).
  - `_cli/renderers/host.py` — `render_profile`, `render_profile_completeness`.
  - `prep/setup/__init__.py` — chained `host profile init` stage with `--skip-profile` opt-out.
  - `docs/reference/cli-output-schemas.md` — document the new envelopes.
  - `packages/toolkit/pyproject.toml` — add `questionary>=2.0`.
- **Out of scope (deferred)**:
  - Plugin tool registration — Phase 3.
  - Policy preset changes — Phase 3.
  - System prompt changes — Phase 4.

## Invariants Enforced in This Phase

- **INV-C002** CLI Output Contract Stability — every `host profile *` subcommand emits a `cli_output_schema_version` envelope on `--json`; stdout reserved for the structured payload, stderr for prompts/diagnostics.
- **INV-D004** (lightweight) — `host profile edit` requires destructive-style confirmation only for field-drop diffs; additive edits skip the gate.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases** (`tests/integration/test_cli_host_profile.py`):

1. `test_invC002_host_profile_show_json_envelope_shape` — `genomeclaw host profile show --json` emits a single-line envelope `{"cli_output_schema_version": "1.0", "command": "host profile show", "payload": {...}}`.
2. `test_host_profile_show_missing_profile_renders_init_hint` — fresh derived root: human-mode `show` renders a Rich panel with the canonical CLI command suggestion.
3. `test_host_profile_show_missing_profile_json_envelope_carries_init_command` — JSON-mode equivalent.
4. `test_invC002_host_profile_init_quick_json_envelope` — `host profile init --quick --json` produces an envelope carrying the freshly-written profile.
5. `test_host_profile_init_interactive_walks_all_sections` — interactive mode with a mocked Questionary backend walks identity → biometrics → lifestyle → medical history → family history (no `goals`) and writes the file.
6. `test_host_profile_init_skip_records_meta_skipped_init_at` — `host profile init --skip` records the timestamp without writing other sections, and `meta.skipped_init_at` is non-null in the resulting file.
6a. `test_host_profile_init_ancestry_multiselect_persists_friendly_and_pop1000g` — mocked Questionary returns `["european", "east_asian"]`; the written file carries `groups: ["european","east_asian"]` AND derived `population_codes: ["EUR","EAS"]`.
6b. `test_host_profile_init_ancestry_self_reported_freetext_accepts_mixed` — mocked text input `"50% Icelandic, 25% Czech, 25% Kazakh"` is persisted verbatim in `identity.ancestry.self_reported`.
6c. `test_host_profile_init_family_history_editor_path_strips_scaffold_comments` — mocked `click.edit` returns scaffolded text with `#`-prefixed comment lines + user-added narrative; the persisted `family_history.notes` contains only the non-comment lines.
6d. `test_host_profile_init_family_history_opt_out_sets_flag` — choosing "I'd rather opt out entirely" sets `family_history.opted_out: true` and leaves `notes: null`.
6e. `test_host_profile_init_no_goals_section_walked` — the init flow does NOT prompt for goals; the written file has no `goals` key.
7. `test_host_profile_set_dotted_path_writes_single_field` — `host profile set medical_history.medications.add '{"name":"clopidogrel"}'` mutates only that path; audit log entry confirms.
8. `test_host_profile_set_rejects_unknown_section` — `host profile set medical_history.dragons '...'` exits non-zero with a structured error.
9. `test_host_profile_edit_field_drop_requires_confirmation` — removing a field via `$EDITOR` requires `--yes` or interactive confirmation.
10. `test_host_profile_review_marks_last_full_review_at` — `host profile review` walks each section in show-only mode and updates `meta.last_full_review_at` on completion.
11. `test_host_profile_setup_chain_runs_profile_init_at_end` (`tests/integration/test_host_profile_setup_chain.py`) — `host setup --interactive` end-to-end leaves a populated `host_profile.json` (or records the explicit skip).
12. `test_host_profile_setup_chain_skip_profile_records_meta_skipped_init_at` — `host setup --interactive --skip-profile` records the skip.

Renderer (`tests/reports/test_host_profile_renderer.py`):

13. `test_render_profile_snapshot` — `render_profile(fixture_profile)` snapshot stable.
14. `test_render_profile_completeness_marks_missing_with_caution_glyph` — completeness table shows `missing` sections with the established caution marker.

**Sketch**:

```python
def test_invC002_host_profile_show_json_envelope_shape(tmp_derived_root):
    """INV-C002: every host profile subcommand carries the CLI envelope on --json."""
    write_fixture_profile(tmp_derived_root)
    result = run_cli(["host", "profile", "show", "--json"], env={"GENOMECLAW_DERIVED_ROOT": str(tmp_derived_root)})
    envelope = json.loads(result.stdout.strip())
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "host profile show"
    assert envelope["payload"]["profile"]["schema_version"] == "host_profile/1.0"
    assert result.stderr  # rich progress / panel writes go to stderr, not stdout
```

**Run RED**. Confirm every test fails because the commands don't exist yet. Paste output into `work-notes.md`.

### Step 2.2 — GREEN: Minimal Implementation

**Files affected**:

- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` — register `profile` subgroup; bind `init`, `show`, `set`, `edit`, `review`.
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/interactive.py` — Questionary-driven per-section prompt sequences (`questionary.select`, `questionary.checkbox`, `questionary.text`, `questionary.confirm`, `questionary.form`). Each prompt validates against the section sub-model in real time and re-prompts on failure. `click.edit` covers the family-history `$EDITOR` path. Rich panels render the ancestry explanation + worked examples before each ancestry prompt. The existing `_cli/confirm.py` stays for destructive-flow yes/no gates.
- `packages/toolkit/pyproject.toml` — add `questionary>=2.0` to project dependencies.
- `packages/toolkit/src/genomeclaw_toolkit/_cli/renderers/host.py` — add `render_profile`, `render_profile_completeness`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` — chain `host profile init` as the final stage of `run_interactive` and `run_smart`; honour `--skip-profile`.
- `docs/reference/cli-output-schemas.md` — append the new envelope schemas.

Keep each subcommand single-purpose. `edit` shells out to `$EDITOR` against a temp JSON, then re-validates against the schema and runs the diff-confirmation check before promoting.

### Step 2.3 — REFACTOR

- Factor the section-prompt iteration into one `walk_sections(sections=None)` so `init`, `set`, and `review` share the iteration discipline.
- Confirm the renderer's caution-glyph for `missing` sections matches the project's established INV-C001 escalation marker (no new visual vocabulary).
- Re-run all phase tests after each refactor.

---

## Implementation Details

### Subcommand reference (CLI)

```text
genomeclaw host profile init         # Questionary-driven walk: identity → biometrics → lifestyle
                                     # → medical history → family history (no goals)
  --quick                            # identity (incl. ancestry) only
  --skip                             # record meta.skipped_init_at and exit cleanly
  --json                             # emit envelope on stdout

genomeclaw host profile show         # render current profile (or missing-signal panel)
  --section <dotted.path>            # show one section
  --json

genomeclaw host profile set <dotted.path> <value-or-json>
  --yes                              # skip confirmation when overwriting an existing value
  --json

genomeclaw host profile edit         # open profile in $EDITOR (default $VISUAL || vi)
  --yes                              # skip diff-confirmation
  --json                             # post-edit emit envelope

genomeclaw host profile review       # walk sections show-only, then update meta.last_full_review_at
  --json
```

### Questionary primitives used per section

| Section | Field | Questionary primitive | Notes |
|---|---|---|---|
| identity | `display_name` | `questionary.text(...)` | bounded ≤80 chars, validated inline |
| identity | `date_of_birth` | `questionary.text(..., validate=ISO8601Date)` | re-prompts on parse failure |
| identity | `sex_assigned_at_birth` | `questionary.select(...)` | arrow-key single-select, 4 options |
| identity | `gender_identity` | `questionary.text(..., default="")` | optional, skip with empty |
| identity | `ancestry.self_reported` | `questionary.text(..., multiline=True)` | with worked-example panel (mixed ancestry) shown first via `rich.panel` on stderr |
| identity | `ancestry.groups` | `questionary.checkbox(...)` | **space-bar multi-select** with one-line description per group; `[?]` opens detailed panel |
| biometrics | `height_cm` | `questionary.text(..., validate=FloatRange(50, 250))` | optional |
| biometrics | `weight_kg` | `questionary.text(..., validate=FloatRange(20, 400))` | optional |
| biometrics | `blood_type` | `questionary.select(...)` | 9 options incl. "unknown" |
| lifestyle | `smoking_status` | `questionary.select(...)` | 4 options |
| lifestyle | `alcohol_use` | `questionary.select(...)` | 5 options |
| lifestyle | `exercise_frequency` | `questionary.select(...)` | 4 options |
| lifestyle | `dietary_pattern` | `questionary.text(..., multiline=True)` | optional, ≤200 chars |
| lifestyle | `sleep_pattern` | `questionary.text(..., multiline=True)` | optional, ≤200 chars |
| medical_history | conditions / medications / allergies / procedures (add loop) | `questionary.confirm("Add another?") + questionary.form(...)` | per-item structured input |
| family_history | choose entry mode | `questionary.select(...)` | `[e]dit in $EDITOR (recommended)`, `[t]ype inline`, `[s]kip` |
| family_history | `notes` (editor path) | `click.edit(scaffold_text)` | opens scaffold w/ comment-line prompts; re-validates ≤4000 chars |
| family_history | `notes` (inline path) | `questionary.text(..., multiline=True)` | ≤4000 chars |

### The ancestry sub-flow (the most-different part of the walk)

The ancestry capture is deliberately split into TWO prompts to dissolve mixed-ancestry blank-page hesitation. First a `rich.panel` explanation is printed to stderr (always, regardless of `--quick`):

```text
─── Identity — ancestry ───────────────────────────────────────────────────

  Self-reported ancestry tells the agent which population groups
  you (and your biological parents/grandparents) come from. This
  matters because most genetic research is calibrated against
  specific populations — knowing your background helps the agent
  flag when a finding may or may not apply to you.

  If your ancestry is mixed, describe each component and its
  approximate share. Examples:

    • "Icelandic"
    • "Half Icelandic, half Norwegian"
    • "50% Icelandic, 25% Czech, 25% Kazakh"
    • "Ashkenazi Jewish on mother's side, Polish on father's side"
    • "Han Chinese"
    • "Mixed African American and European, exact breakdown unknown"
    • "Adopted — no family origin records available"

  Just say what you know, including "I don't really know" if
  that's honest — the agent reads "unknown" as a real signal.
```

…followed by a Questionary multi-line text input (`self_reported`, ≤500 chars, optional).

Then a second `rich.panel` introduces the friendly-group multi-select, framed around its actual purpose (PRS calibration) NOT identity:

```text
─── Identity — ancestry reference groups ──────────────────────────────────

  Polygenic risk scores (PRS) are calibrated against specific
  reference populations from large genetic studies. To give you
  honest PRS calibration, the agent needs to know which reference
  group(s) most closely match your ancestry.

  This is NOT about identity, race, or nationality — it's about
  which research datasets the agent can fairly compare you to.

  Pick all that meaningfully describe your background:
  (↑↓ to move, SPACE to toggle, ENTER to confirm, ? for more detail)
```

…followed by `questionary.checkbox()` with the nine friendly groups + one-line descriptions:

```text
  ▢ European ancestry
      (most European countries, Iceland, Ashkenazi & North
       African Jewish, diaspora-European populations)
  ▢ African ancestry
      (Sub-Saharan African, African-American, Afro-Caribbean)
  ▢ East Asian ancestry
      (China, Korea, Japan, Mongolia, Vietnam)
  ▢ South Asian ancestry
      (India, Pakistan, Bangladesh, Sri Lanka, Nepal)
  ▢ American Indigenous / Latino ancestry
      (Mexican, Central + South American Indigenous, Caribbean
       Latino, US Latino with Indigenous heritage)
  ▢ Middle Eastern / North African ancestry
      (Arabian Peninsula, Levant, Iran, Turkey, North Africa)
  ▢ Oceanian ancestry
      (Pacific Islander, Aboriginal Australian, Papuan)
  ▢ Mixed / admixed / unsure
      (significant ancestry from 3+ groups, or unknown)
  ▢ Prefer not to say
```

A `[?]` keybind opens a follow-on Rich panel explaining briefly *why* PRS-calibration cares about population groups (linking to a documented short doc per open question Q7) so curious users have a path to depth without forcing it on everyone.

### The family-history sub-flow

The family-history capture is a single free-text field (no per-relative list). The prompt explains the goal and offers three entry modes:

```text
─── Family history ────────────────────────────────────────────────────────

  Family medical history adds important context — many findings
  are interpreted differently when there's a known family pattern
  (early heart disease, certain cancers, dementia, type 2
  diabetes, autoimmune conditions, mental-health conditions, etc.).

  Write what you know in your own words. The agent will read it
  carefully. Don't worry about being exhaustive — just include
  what you remember, especially:

    • Conditions that ran in your immediate family (parents,
      siblings, children) with rough ages if you know them
    • Anything in the broader family (grandparents, aunts,
      uncles, cousins) that stuck out
    • Any known genetic diagnoses anyone in the family received
    • Age and cause of death for parents and grandparents if
      known

  Examples of useful entries:

    "Dad: heart attack at 52, recovered, manages cholesterol.
     Mum: type 2 diabetes diagnosed around 60. Paternal
     grandfather died of stroke in his 70s. Maternal grandmother
     had breast cancer in her late 60s."

    "Both parents living and healthy in their 60s. No known
     family cancer or heart disease. One uncle on dad's side has
     early-onset Alzheimer's (diagnosed early 60s)."

    "Adopted — no family medical history available."

  How would you like to enter this?
  ❯ Open in $EDITOR (recommended — scaffold provided)
    Type inline
    Skip for now
    I'd rather opt out entirely (record opted_out: true)
```

The `[e]dit in $EDITOR` path opens a scaffold pre-populated with comment-line prompts (per open question Q8 — confirm at Phase 2):

```text
# Family history — write your free-text below. Delete this whole
# scaffold and replace with your own narrative if you prefer.
# All lines starting with '#' are comments and will be removed
# before saving.
#
# Parents — any heart disease, cancer, diabetes, dementia,
# autoimmune, mental-health, or other notable conditions?
# Age at onset / age at death if known.
#
# Siblings and children — anything similar?
#
# Grandparents — what did they die of? Conditions that ran on
# either side?
#
# Aunts / uncles / cousins — anything that stuck out?
#
# Anyone with a confirmed genetic diagnosis?
#
# Lines below this point are saved into your profile.
```

On save the scaffold-marker comments are stripped; the remaining text is bounded to ≤4000 chars and re-prompts on overflow.

If the user picks "I'd rather opt out entirely", `family_history.opted_out` is set to `true` + `notes` left `null`. The agent sees this signal and treats family history as a calibrated decline rather than a missing-data gap (different framing per the Phase 4 prompt update).

### `host setup` chain

After the existing `run_interactive` / `run_smart` final stage, invoke `host profile init --quick` (default) or `host profile init` (when `--thorough-profile` is set). Honour `--skip-profile` to record the explicit skip. Behaviour on a non-TTY: log a structured warning + record `meta.skipped_init_at` automatically (matches the existing non-interactive setup discipline).

### Edge Cases to Handle

- `$EDITOR` not set → fall back to `vi`; warn on stderr.
- User cancels mid-init (Ctrl-C) → write nothing; no partial file lands. The session log records the abort.
- `set` against an existing value → confirmation prompt unless `--yes`.
- `set` against a freetext field longer than the bound → reject + show the bound in the error envelope.
- Re-running `init` against an existing profile → ask "merge", "overwrite", or "cancel". Default: merge.

### Error Handling

- All errors flow through the existing CLI exception boundary in `_cli/errors.py`. Reuse `UsageError`, `PreconditionError`, `RuntimeFailure`. New typed error `HostProfileValidationError` for schema-rejection cases.
- Errors emit on stderr; payload (if any was already emitted) stays on stdout. The `stdout_already_consumed` sentinel pattern carries over.

### Privacy / Egress Notes

- Interactive prompts surface only on the local terminal; nothing leaves the host.
- The audit log entry for a `set` records the field path + (for structured fields) the new value, or (for freetext) a `<freetext len=N>` placeholder.
- The CLI `--json` envelope payload is local-only; the agent does NOT consume CLI envelopes — it reads via the HTTP endpoint (Phase 3).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Add `profile` subgroup + 5 subcommands. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/interactive.py` | CREATE | Per-section prompt sequences. |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/renderers/host.py` | MODIFY | `render_profile` + `render_profile_completeness`. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py` | MODIFY | Chain `host profile init` as final stage. |
| `docs/reference/cli-output-schemas.md` | MODIFY | Document new envelope schemas. |
| `packages/toolkit/tests/integration/test_cli_host_profile.py` | CREATE | Subcommand integration tests (1–10). |
| `packages/toolkit/tests/integration/test_host_profile_setup_chain.py` | CREATE | `host setup` chain tests (11–12). |
| `packages/toolkit/tests/reports/test_host_profile_renderer.py` | CREATE | Renderer snapshot tests (13–14). |

---

## Verification

```bash
# Phase 2 tests
uv run --project packages/toolkit pytest \
  packages/toolkit/tests/integration/test_cli_host_profile.py \
  packages/toolkit/tests/integration/test_host_profile_setup_chain.py \
  packages/toolkit/tests/reports/test_host_profile_renderer.py \
  -v

# Lint + types
uv run --project packages/toolkit mypy src/genomeclaw_toolkit/_cli/commands/host.py src/genomeclaw_toolkit/host_profile/interactive.py src/genomeclaw_toolkit/_cli/renderers/host.py
uv run --project packages/toolkit ruff check src/genomeclaw_toolkit/_cli/commands/host.py src/genomeclaw_toolkit/host_profile/interactive.py src/genomeclaw_toolkit/_cli/renderers/host.py

# Manual end-to-end (interactive)
GENOMECLAW_DERIVED_ROOT=/tmp/genomeclaw-phase2-fixture \
  uv run --project packages/toolkit genomeclaw host profile init --quick
GENOMECLAW_DERIVED_ROOT=/tmp/genomeclaw-phase2-fixture \
  uv run --project packages/toolkit genomeclaw host profile show
```

---

## Completion Criteria

- [ ] All 19 listed test cases pass (14 originally numbered + 5 ancestry/family-history additions 6a–6e).
- [ ] Static checks pass.
- [ ] Each enforced `INV-xxx` is verified by at least one test (INV-C002, INV-D004).
- [ ] `host setup` end-to-end leaves a profile file (populated or explicitly skipped).
- [ ] `cli-output-schemas.md` documents every new envelope.
- [ ] `work-notes.md` updated.
- [ ] Phase 2 status updated in `development-plan.md`.

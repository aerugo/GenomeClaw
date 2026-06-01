# Phase 1: Audit Lock-In + Consistency-Test Harness

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Write the code-derived README-consistency test (`test_readme_accuracy.py`) that derives ground truth from the Typer app + `openclaw.plugin.json` + `service/app.py` + `INVARIANTS.md` and asserts the README matches. Confirm it fails (RED) against the current, drifted README for the *right* reasons. Resolve Q1 (version-pin) + Q2 (command subset).

## Scope Boundaries

- **In scope**: the new test file; resolving Q1/Q2; capturing RED output.
- **Out of scope**: editing `README.md` (Phases 2–4); pinning prose/wording.

## Invariants Enforced in This Phase

- **INV-V001** — the test is *structural inspection over a source document + code* (the sanctioned alternative to phrase-enumeration). The handful of "retired-string absent" assertions (`8643` for the service, "six … tools", `/v1/pgs/{trait}`) target the static README and each carry a `# INV-V001-allow:` annotation.
- **INV-C002** (prose side) — the test pins the documented CLI surface against the actual command tree.

---

## TDD Steps

### Step 1.1 — RED: Write the consistency test

`packages/toolkit/tests/invariants/test_readme_accuracy.py`. Ground truth is **derived at test time** (never hardcoded), so the gate tracks the code:

**Test cases** (each reads ground truth from code, asserts against `README.md`):

1. `test_readme_lists_every_plugin_tool` — parse `openclaw.plugin.json` `contracts.tools`; assert each tool name (all 10) appears in the README.
2. `test_readme_does_not_undercount_tools` — assert the README does not contain the stale "six" tool-count claim (`# INV-V001-allow:` — static-doc retired-string check). Prefer asserting the *number of distinct documented tools* ≥ the manifest count over matching a specific word.
3. `test_readme_host_service_port_is_8645` — assert `8645` appears in the README's host-service references and no GenomeClaw-service line says `8643` (the coexistence section may *name* DevRelClaw's 8643; scope the assertion to lines describing the GenomeClaw service). `# INV-V001-allow:`.
4. `test_readme_documents_host_profile_endpoints` — assert `/v1/host/profile` is present and the retired `/v1/pgs/{trait}` is absent. `# INV-V001-allow:` for the absence half.
5. `test_readme_documents_cli_groups_and_host_profile` — import the Typer app (or parse the command-group sources); assert the README documents the five groups + the `host profile` subcommands (`init/show/set/review/edit`).
6. `test_readme_documents_pipeline_subcommands_and_refs_fetch` — assert the README's pipeline list matches the actual `pipeline` group and that `fetch` is shown under `refs` (not pipeline).
7. `test_readme_invariants_link_present` — assert the README links `docs/reference/INVARIANTS.md`; per Q1, either (a) version-less (link only) or (b) the version string matches `INVARIANTS.md`'s current `**Version**`.

**Helper**: a small `_read_readme()` + ground-truth extractors (`_manifest_tools()`, `_cli_command_tree()`, `_host_service_routes()`, `_invariants_version()`). Reuse the parse patterns from `test_invA004_host_profile_enums_traverse.py` (regex over source) + `test_plugin_manifest_tool_contract.py` (manifest JSON) + `test_invP002_policy_preset_shape.py` (route/yaml parsing) where applicable.

**Run RED**. Confirm failures: missing `genomeclaw_host_profile`, "six tools" present, `8643` present, `/v1/host/profile` absent / `/v1/pgs/{trait}` present, `host profile` commands absent. Paste the RED output into `work-notes.md`.

### Step 1.2 — GREEN

Not in this phase — the test goes green incrementally as Phases 2–4 edit the README. Phase 1's "green" is only that the test *collects + runs + fails for the intended reasons*.

### Step 1.3 — REFACTOR

- Factor the ground-truth extractors so Phases 2–4 don't need to touch the test.
- Resolve Q1 + Q2; record the decisions in `work-notes.md`.

---

## Implementation Details

### Edge cases
- The coexistence section legitimately mentions DevRelClaw's **8643** by name — assertion #3 must scope to GenomeClaw-service references (e.g. lines containing "genomeclaw" + a port, or the specific service-description lines), not a blanket `"8643" not in readme`.
- Importing the Typer app in a test: prefer `typer.main.get_command(app)` + walking `.commands` (mirrors `_registered_subcommand_names()` in `_cli/__init__.py`), or regex over the command-group sources if importing pulls heavy deps. Pick whichever is lighter + stable.

### Privacy / Egress Notes
None — the test reads local files only.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/invariants/test_readme_accuracy.py` | CREATE | Code-derived README consistency gate. |

---

## Verification

```bash
# This phase's test (expect RED for the documented reasons)
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_readme_accuracy.py -v

# Lint the new test
.venv/bin/ruff check tests/invariants/test_readme_accuracy.py
```

---

## Completion Criteria

- [ ] `test_readme_accuracy.py` created; derives ground truth from code (no hardcoded fact copies).
- [ ] Runs + fails (RED) on the current README for the intended reasons; RED output in `work-notes.md`.
- [ ] Q1 (version-pin) + Q2 (command subset) resolved + recorded.
- [ ] `ruff` clean; retired-string assertions annotated `# INV-V001-allow:`.
- [ ] Phase 1 status updated in `development-plan.md`.

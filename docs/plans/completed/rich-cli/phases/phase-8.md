# Phase 8: Final cleanup + invariant promotion

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-7.md](phase-7.md) — polish + agent ergonomics complete (completion, "did you mean", cold-start perf gate, two latent JSON-mode error-path bugs retro-fixed).
**Successor**: None — this is the closing phase. Plan moves to `docs/plans/completed/rich-cli/` after this phase ships.

---

## Objective

Close the rich-cli plan. Three workstreams:

1. **Repo grep-clean**: rewrite every `genomeclaw-prep <verb>` reference in user-facing docs (README, architecture, user-stories, INVARIANTS.md, root CLAUDE.md, `.claude/agents/`) to the canonical `genomeclaw <group> <verb>` form. The Phase 1 clean-slate cutover deleted the code; this phase fixes the documentation.
2. **Invariant promotion**: promote two provisional invariants accumulated through this plan into canonical `INVARIANTS.md`:
   - **`INV-C002`** — CLI Output Contract Stability (from Phase 1; gated since on schemas staying stable through Phase 7).
   - **`INV-D004`** — Destructive Operations Require Explicit Confirmation (from Phase 6).
3. **Plan move**: relocate `docs/plans/active/rich-cli/` → `docs/plans/completed/rich-cli/` per the planning protocol's closing ritual.

The `genomeclaw-prep` cleanup is **scoped to user-facing reference docs + agent instruction files**. The MVP plan docs (`docs/plans/active/mvp/`) are explicitly on hold and contain references to historical artifacts (Phase 4C.3 ran with `genomeclaw-prep`); rewriting those would be a separate scope. Their cleanup happens when MVP resumes and 4C.4 W4 is rerun under the new CLI.

## Scope Boundaries

**In scope**:

- `README.md` — every `bin/genomeclaw-prep <verb>` rewritten to `bin/genomeclaw <group> <verb>`.
- `docs/reference/architecture.md` — host-side packaging section + every example invocation.
- `docs/reference/user-stories.md` — flow walkthroughs.
- `docs/reference/INVARIANTS.md` — body references in INV-D003 / INV-P001 / INV-P002, plus add the two new entries + bump version to 1.7 + update Last Updated.
- `docs/reference/grand-plan.md` — example invocations.
- `docs/reports/open-source-tool-alignment.md` — narrative references.
- `.claude/agents/bioinformatics-pipeline.md` / `.claude/agents/report-generator.md` / `.claude/agents/privacy-safety-reviewer.md` / `.claude/agents/test-engineer.md` — CLI references in agent instructions.
- Root `CLAUDE.md` — already clean (per earlier audit); verify.
- New invariants added to `INVARIANTS.md` with full Rule / Requirements / Where it applies / How to verify; appended to the Invariant Index table.
- Plan moved from `docs/plans/active/rich-cli/` to `docs/plans/completed/rich-cli/`.

**Out of scope**:

- `docs/plans/active/mvp/**` — explicitly on hold; cleanup happens when MVP resumes.
- `docs/plans/completed/**` — historical record, intentionally frozen.
- `docs/plans/active/rich-cli/**` — historical record of this plan; intentionally not rewritten (the plan ran with `genomeclaw-prep` references during early phases; those are part of the record).
- Source code (`src/**`, `tests/**`) — already clean from Phase 1 (the code base never re-introduced `genomeclaw-prep` references after the cutover).

## Invariants Enforced in This Phase

- **NEW canonical `INV-C002`** — CLI Output Contract Stability. Tests landed across Phases 1–7 verify the rule; promotion is purely the documentation update.
- **NEW canonical `INV-D004`** — Destructive Operations Require Explicit Confirmation. Tests landed in Phase 6 verify the rule; promotion is the documentation update.

---

## TDD Steps

This phase is mostly mechanical doc surgery; the verification is grep-based rather than test-based. The two TDD-shaped checks:

### Step 8.1 — RED: tests that pin the cleanup gates

`tests/integration/test_no_legacy_cli_references.py` (CREATE):

1. `test_user_facing_docs_have_no_genomeclaw_prep_references` — grep the in-scope set (README, architecture, user-stories, INVARIANTS, grand-plan, .claude/agents); assert zero matches. Excludes plans-active/ and plans-completed/.
2. `test_invariants_md_contains_inv_c002` — read INVARIANTS.md; assert `INV-C002` is defined.
3. `test_invariants_md_contains_inv_d004` — same for INV-D004.

### Step 8.2 — GREEN: do the cleanup

Rewrite every in-scope reference. The cleanup is essentially a sed pass with a few manual fixups for context-sensitive cases (e.g., `genomeclaw-prep setup --fetch-all` becomes `genomeclaw host setup --fetch-all`; `genomeclaw-prep fetch` becomes `genomeclaw refs fetch`).

Append the two new invariants to `INVARIANTS.md` with full sections + index rows + version bump.

### Step 8.3 — REFACTOR

Walk the diff once for typos, broken cross-references, and orphaned anchor links.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `README.md` | MODIFY | Rewrite every `genomeclaw-prep <verb>` to `genomeclaw <group> <verb>` |
| `docs/reference/architecture.md` | MODIFY | Same |
| `docs/reference/user-stories.md` | MODIFY | Same |
| `docs/reference/grand-plan.md` | MODIFY | Same |
| `docs/reference/INVARIANTS.md` | MODIFY | Cleanup + 2 new invariant sections + version bump |
| `docs/reports/open-source-tool-alignment.md` | MODIFY | Same |
| `.claude/agents/bioinformatics-pipeline.md` | MODIFY | Same |
| `.claude/agents/report-generator.md` | MODIFY | Same |
| `.claude/agents/privacy-safety-reviewer.md` | MODIFY | Same |
| `.claude/agents/test-engineer.md` | MODIFY | Same |
| `tests/integration/test_no_legacy_cli_references.py` | CREATE | grep-based regression guard |
| `docs/plans/active/rich-cli/` | MOVE | → `docs/plans/completed/rich-cli/` after everything else passes |

---

## Verification

```bash
cd packages/toolkit

# Cleanup-gate test
uv run pytest tests/integration/test_no_legacy_cli_references.py -v

# Full suite
uv run pytest -q

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli

# Manual grep audits
grep -r "genomeclaw-prep" README.md docs/reference/ .claude/agents/ CLAUDE.md   # expect zero matches
grep -E "INV-C002|INV-D004" docs/reference/INVARIANTS.md                         # expect both present
```

---

## Completion Criteria

- [x] All listed tests pass (3 new in `test_no_legacy_cli_references.py`; **391 passed, 61 skipped** — +3 over Phase 7).
- [x] Static checks pass: `ruff check` + `ruff format --check` + `mypy --strict` on `_cli/`.
- [x] `grep -r "genomeclaw-prep" README.md docs/reference/ .claude/agents/` returns only the carved-out `cli-output-schemas.md` example showing the legacy provenance literal (preserved for back-compat).
- [x] `INVARIANTS.md` contains both `INV-C002` and `INV-D004` with full sections + index rows + version bumped to 1.7.
- [x] Privacy-safety-reviewer pass: **Accept with required changes (resolved)**. Reviewer flagged one yellow item — the `runs show` schema example carrying `"tool": "genomeclaw-prep"` needed annotation explaining the legacy value. Fixed with an in-doc note clarifying that the field carries whatever was recorded at run time, that existing runs carry the legacy value, and that agents should accept either string without branching. Everything else: green.
- [x] No raw genomic data committed.
- [x] `work-notes.md` updated with the closing block.
- [x] Phase status updated in `development-plan.md` (Phase 8 → Complete).
- [x] Plan moved from `docs/plans/active/rich-cli/` to `docs/plans/completed/rich-cli/`.

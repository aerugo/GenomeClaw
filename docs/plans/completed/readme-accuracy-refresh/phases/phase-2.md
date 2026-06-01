# Phase 2: CLI Surface Section Rewrite

**Status**: Pending
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Rewrite the README's CLI sections to match the real command tree: the `host` group including the `profile {init,show,set,review,edit}` subgroup + the `host setup --skip-profile`/`--thorough-profile` onboarding-chain flags, and corrected `refs` / `runs` / `pipeline` command lists (`fetch` belongs under `refs`).

## Invariants Enforced in This Phase

- **INV-C002** — the documented CLI surface matches the actual Typer command tree.

## TDD Steps

- **GREEN**: the Phase-1 gate's CLI/host-profile/pipeline assertions (#5, #6) turn green as this rewrite lands. No new tests; this phase satisfies existing assertions.
- **Edits**:
  - Add a `host profile` block near the `doctor`/`eject`/`service` bullets: one-line purpose per subcommand (`init` — guided onboarding walk / `--quick` / `--skip`; `show` — render current profile or missing signal; `set <dotted.path> <value>` — single-field / `<list>.add`; `review` — stamp last-full-review; `edit` — `$EDITOR` + field-drop confirmation). Note it's host-side self-reported context the agent reads before genome-informable replies.
  - Document `host setup --skip-profile` + `--thorough-profile`.
  - Correct the pipeline subcommand enumeration; move `fetch` under `refs`; document `runs` (`list/show/current`).
- **REFACTOR**: ensure command names match exactly (copy from the Typer app); keep one-liners tight.

## Files

| File | Action | Purpose |
|------|--------|---------|
| `README.md` | MODIFY | CLI sections (host incl. profile + setup flags; refs/runs/pipeline). |

## Verification

```bash
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_readme_accuracy.py -v -k "cli or host_profile or pipeline or groups"
```

## Completion Criteria

- [ ] `host profile` subgroup + `host setup` profile flags documented (AC1).
- [ ] `refs`/`runs`/`pipeline` command lists correct; `fetch` under `refs` (AC5).
- [ ] Phase-1 gate CLI/host-profile/pipeline assertions pass.
- [ ] `work-notes.md` + `development-plan.md` updated.

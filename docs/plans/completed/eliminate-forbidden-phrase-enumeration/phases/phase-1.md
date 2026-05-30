# Phase 1: Audit — Catalog Phrase-Enumeration Sites

**Status**: Complete
**Started**: 2026-05-28
**Completed**: 2026-05-28
**Parent Plan**: [development-plan.md](../development-plan.md)
**Output**: [phase-1-audit-findings.md](phase-1-audit-findings.md)

---

## Objective

Produce a file-by-file inventory of every substring/regex enumeration touching agent output in the repo. Categorize each site as **primary** (must be replaced), **backstop** (annotate + keep), **structural** (annotate + keep with different rationale), or **future-plan** (filed proposal to be retracted/updated).

The audit is documentation-first; no code edits in this phase. Output drives Phase 2's cleanup.

## Scope Boundaries

- **In scope**:
  - `packages/toolkit/tests/invariants/`
  - `packages/toolkit/tests/integration/`
  - `packages/nemoclaw-plugin/tests/`
  - `packages/nemoclaw-plugin/sandbox/*.md` (prompt files)
  - `docs/plans/active/**/*.md` (look for proposals — file follow-ups if needed)
- **Out of scope**:
  - Pipeline / data-processing code (no agent-output gates there).
  - Documentation prose (no enforcement layer).

## Invariants Enforced in This Phase

- None directly enforced; audit feeds Phase 2's cleanup + Phase 4's `INV-V001` promotion.

---

## Steps

### Step 1.1 — Repo-wide pattern scan

Find every string-tuple/list literal in test + prompt files. Search patterns:

```bash
# Test-file tuples
grep -rn -E "^\s*_[A-Z_]+\s*[:=]\s*\(" packages/toolkit/tests/ packages/nemoclaw-plugin/tests/

# Prompt-file "do not say" tables
grep -rn -E "MUST NOT|do NOT|forbidden|catalogue|paraphrase" packages/nemoclaw-plugin/sandbox/*.md

# Substring checks against agent output / replies
grep -rn -E '" in (reply|text|content|response|message)' packages/toolkit/tests/

# Plan-file proposals
grep -rn -E "forbidden.{0,5}phrase|catalogue|enumerat" docs/plans/active/
```

### Step 1.2 — Categorize each finding

For each site, classify into one of four categories:

| Category | Definition | Action in Phase 2 |
|----------|------------|-------------------|
| **Primary** | Substring enumeration IS the load-bearing correctness gate (the test fails only if a phrase appears or is missing) | **Replace** with structural / semantic mechanism (sister plan covers known cases; new cases get follow-up plans). |
| **Backstop** | Substring check is a non-load-bearing sanity / regression-pin (the real correctness check is elsewhere — schema, integration smoke, etc.) | **Annotate** `# INV-V001-backstop: <one-line why>`. |
| **Structural** | The check is on a *shape* (regex for argv-leak patterns, type-system) rather than a paraphrase enumeration | **Annotate** `# INV-V001-allow: <one-line why>`. |
| **Future-plan** | A draft plan proposes phrase enumeration as a verification mechanism | **Retract or amend** the plan to align with `INV-V001`. |

### Step 1.3 — Produce the inventory report

Write `phases/phase-1-audit-findings.md` with one section per file. Each finding includes:

- File:line(s)
- Snippet (≤10 lines context)
- Category
- 1-line justification
- Phase 2 action (annotate / replace / retract)

### Step 1.4 — Update work-notes

Summarize the audit's headline numbers (X primary, Y backstop, Z structural, W future-plan) in [work-notes.md](../work-notes.md).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `phases/phase-1-audit-findings.md` | CREATE | The inventory report. |
| [work-notes.md](../work-notes.md) | MODIFY | Append audit headline summary. |

---

## Verification

The audit is correct when:

```bash
# Re-running the scans returns sites that all appear in the inventory report
grep -rn -E "^\s*_[A-Z_]+\s*[:=]\s*\(" packages/toolkit/tests/ | wc -l
# Compare against the inventory's count.
```

---

## Completion Criteria

- [ ] `phases/phase-1-audit-findings.md` exists + lists every site.
- [ ] Each site has a category + action.
- [ ] Headline numbers in `work-notes.md`.
- [ ] No new "primary" site discovered that the sister plan doesn't cover. (If found: log as Phase 2 prerequisite.)
- [ ] Phase 1 row in `development-plan.md` progress table set to **Complete**.

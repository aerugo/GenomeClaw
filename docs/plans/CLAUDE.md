# AI Agent Implementation Planning Guide

This directory is where AI agents should put plans for features, data pipelines, architecture changes, documentation efforts, and workflow refactors.
Small efforts can live as a single markdown file in `docs/plans/`.
Larger efforts should get their own directory under `docs/plans/`.

## Directory Structure for Larger Plans

Each larger plan directory should use this structure:

```text
docs/plans/<feature-name>/
├── initial_findings.md      # Research/discovery notes if applicable
├── development-plan.md      # Phased development plan (required)
├── work_notes.md            # Session notes and implementation progress (required)
├── doc-draft.md             # Draft documentation updates
└── phases/
    ├── phase_1.md           # Detailed plan for phase 1
    ├── phase_2.md           # Detailed plan for phase 2
    └── ...
```

---

## Starting a New Implementation

### 1. Understand the Project Context

Before writing code or changing pipeline behavior:

- **Read all relevant `CLAUDE.md` files** and `.claude/agents/` guides for project conventions
- **Read relevant docs in `docs/reference/`** for architecture, data flow, provenance, and privacy constraints
- **Study existing implementations** that solve similar problems in the codebase
- **Analyze the current state** of files you plan to modify before changing them
- **Identify which invariants from the root `CLAUDE.md` apply** and write them down explicitly in the plan

### 2. Create the Development Plan

Save to `docs/plans/<feature-name>/development-plan.md`:

```markdown
# <Feature Name> - Development Plan

**Status**: In Progress
**Created**: <date>
**Branch**: <branch-name>

## Summary

<1-2 sentence description of what this implementation accomplishes>

## Critical Invariants to Respect

- **INV-1**: Raw Genomic Files Are Source-of-Truth Artifacts - <how this work preserves source authority>
- **INV-2**: Assistant Claims Must Be Traceable to Evidence - <how this work preserves traceability>
- **INV-3**: Privacy Is the Default Operating Mode - <how this work avoids unnecessary exposure>
- **INV-4**: Derived Assistant Stores Must Stay Rebuildable - <how rebuildability is preserved>
- **INV-5**: Separate Research Assistance from Clinical Advice - <how outputs stay appropriately scoped>

If this implementation introduces a new invariant, note it here and plan a documentation update.

## Current State Analysis

<Describe what exists now and what problem is being solved>

### Files to Modify
| File | Current State | Planned Changes |
|------|---------------|-----------------|
| ...  | ...           | ...             |

## Solution Design

<Describe the solution approach, interfaces, data flow, and why this is the right fit>

## Phased Implementation Plan

### Phase 1: <name>
- Goal:
- Changes:
- Risks:
- Verification:

### Phase 2: <name>
- Goal:
- Changes:
- Risks:
- Verification:

## Testing Strategy

- Unit tests:
- Integration tests:
- Pipeline/provenance checks:
- Privacy/safety checks:
- Manual verification:

## Documentation Updates Required

- Root or subsystem `CLAUDE.md`
- `docs/reference/...`
- User-facing examples or reports
```

### 3. Create `work_notes.md`

Track implementation progress as work proceeds.
Each work session should append notes with:

- date/time
- what changed
- decisions made
- blockers
- next steps

Template:

```markdown
# Work Notes

## <date/time>
- Investigated:
- Changed:
- Verified:
- Blockers:
- Next:
```

### 4. Use Phases for Larger Changes

If the work spans multiple substantial stages, create `phases/phase_N.md` files.
Each phase file should include:

- objective
- scope boundaries
- files/components affected
- invariants at risk
- test plan
- completion criteria

---

## Planning Standards

### A. Plans must be concrete
Avoid vague items like:
- "improve pipeline"
- "add genomics support"

Prefer:
- "import normalized VCF records into DuckDB variant table with provenance columns"
- "add ClinVar annotation join stage and evidence citation rendering in report summaries"

### B. Name data boundaries explicitly
Plans should say:
- what inputs exist
- what derived artifacts are produced
- where sensitive data crosses boundaries
- what is cached and how it is invalidated/rebuilt

### C. Track provenance and rebuildability explicitly
If a change creates or alters derived data, the plan should state:
- source inputs
- transformation tools
- schema/version impact
- rebuild procedure

### D. Separate exploration from implementation
Use `initial_findings.md` for research notes.
Keep `development-plan.md` focused on the chosen solution.

### E. Prefer phased delivery
Break work into small reviewable slices that can be validated independently.

---

## Required Verification Thinking

Every plan should define the smallest meaningful gates before claiming success.
Examples:

- schema migration applies cleanly
- import pipeline runs on a small fixture VCF
- derived table rebuild is deterministic on the same inputs
- report output includes provenance/evidence citations
- sensitive data is not sent to optional remote services by default
- tests cover both happy paths and risky edge cases

---

## When to Update an Existing Plan

Update the plan when:
- scope changes materially
- a new subsystem is affected
- a design decision changes
- an invariant risk is discovered
- verification strategy changes

Do not leave plans stale while implementation diverges.

---

## Completion Criteria for a Planned Effort

Before marking a planned effort complete:

- `development-plan.md` reflects the final implemented design
- `work_notes.md` reflects the actual work performed
- verification steps are recorded
- relevant docs are updated
- open follow-ups are explicitly listed

If work is partial, mark the remaining items clearly instead of implying completion.

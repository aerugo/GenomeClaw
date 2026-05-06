# <Feature Name> — Development Plan

**Status**: Draft | In Progress | Complete
**Created**: <YYYY-MM-DD>
**Branch**: `feature/<feature-name>`
**Spec**: [spec.md](spec.md)

---

## Summary

<1–2 sentences describing what this implementation accomplishes.>

## Critical Invariants to Respect

Reference IDs from [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md). Be specific about how each constrains *this* implementation, not just what the rule says.

- **INV-D001** Raw Genomic Files Are Source-of-Truth — <how it applies>
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — <how it applies>
- **INV-P001** Privacy Is the Default Operating Mode — <how it applies>
- **INV-R001** Derived Stores Must Stay Rebuildable — <how it applies>
- **INV-C001** Separate Research Assistance from Clinical Advice — <how it applies>

## Proposed New Invariants

If this plan promotes a new project-wide rule, propose it here. Otherwise: **None**.

- **NEW INV-?**: <Proposed name> — <rule + rationale>

## Current State Analysis

<What exists today? What's missing? What problem are we solving?>

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `src/...` | <what's there now> | <what changes> |
| `pipelines/...` | <what's there now> | <what changes> |

### Files to Create

| File | Purpose |
|------|---------|
| `src/...` | <purpose> |
| `tests/...` | <purpose> |

## Solution Design

<Describe the chosen solution: interfaces, data flow, schema impact, pipeline ordering. Reject alternatives concisely with rationale; deeper exploration belongs in `initial_findings.md`.>

```text
<ASCII diagram showing data flow, pipeline stages, or store layout if helpful>
```

### Key Design Decisions

1. **<Decision>**: <rationale>
2. **<Decision>**: <rationale>

### Schema / Provenance Impact

- New / changed schemas: <list>
- Schema version bumps: <list>
- Provenance columns added: <list>
- Rebuild procedure: <command(s) to recreate the store from scratch>

### Privacy & Egress Impact

- New network egress points: <list, or "none">
- New secret-handling surfaces: <list, or "none">
- Redaction added: <list, or "n/a">

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | <description> | <what tests verify> | X |
| 2 | <description> | <what tests verify> | X |
| ... | ... | ... | ... |

## Phase 1: <Name>

**Goal**: <clear objective>
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. <file or component>
2. <file or component>

### Invariants Enforced Here
- **INV-xxx**: <how this phase's tests verify it>

### Success Criteria
- [ ] All tests for this phase pass (RED → GREEN → REFACTOR visible in history)
- [ ] Static checks pass
- [ ] At least one test per enforced invariant
- [ ] <feature-specific success criterion>

## Phase 2: <Name>

...

---

## Testing Strategy

### Unit Tests
- `<path>`: <what it verifies>

### Integration Tests
- `tests/integration/<feature>...`: <what it verifies>

### Provenance Tests
- `tests/provenance/...`: <what it asserts about derived rows>

### Determinism Tests
- `tests/determinism/...`: <which pipelines are reproved byte-equivalent>

### Privacy-Default Tests
- `tests/privacy/...`: <which flows are exercised with default config and asserted to make zero outbound sensitive calls>

### Evidence-Binding Tests
- `tests/evidence/...`: <which interpretations are checked for citation completeness>

### Report Rendering Tests
- `tests/reports/...`: <snapshots / structural assertions>

### Invariant Tests
- `tests/invariants/<inv-id>_*.py`: <which `INV-xxx` are enforced cross-cuttingly>

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — add new invariants if any were promoted
- [ ] `docs/reference/<area>.md` — update or create
- [ ] Root [CLAUDE.md](../../../CLAUDE.md) — only if a top-level invariant or domain term changes
- [ ] `.claude/agents/<agent>.md` — only if a specialist agent's responsibilities shift
- [ ] User-facing examples or report copy

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Pending | | | |
| Phase 2 | Pending | | | |
| ... | ... | | | |

---

## Open Risks & Follow-ups

- <risk or follow-up to track>
